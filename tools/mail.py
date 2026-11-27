#!/usr/bin/env python3
"""Mail drafts and gated sends across several mailboxes, from any session (cloud or local). Stdlib only.

  --account NAME    a mailbox label or address from config/mailboxes.json (default: the first one)
  draft         --to A [--cc B] --subject S (--body-file F | --body T) [--html] [--attach P ...]
  send          same flags; every recipient must be one of the owner's own addresses unless outbox/APPROVED (created by the owner, never the agent) is < 60 min old
  list-drafts   [--contains TEXT]
  delete-draft  --contains TEXT
  inbox         [--hours N | --since ISO] [--max N] [--account NAME | --all]   read-only: received mail, newest first
  send-draft    --contains TEXT   send the one existing draft whose subject matches (keeps thread + attachments); same gate as send

Gmail accounts use the Gmail REST API (OAuth) or IMAP + an app password. Microsoft 365 accounts use the Graph REST API
(https only, so it also works behind a cloud sandbox proxy) with a refresh token.

Mailboxes and the owner's own addresses: config/mailboxes.json (copy config/mailboxes.example.json).
Credentials, in order:
  1. env MAIL_ACCOUNTS_B64: base64 of a JSON object {address: {...}} (see config/tokens.example.json),
     plus env GRAPH_CLIENT_ID for Microsoft accounts.                (cloud environment variables)
  2. a local tokens file: env COS_MAIL_TOKENS, default ~/.config/cos/tokens.json   (laptop)
  3. env GMAIL_APP_PASSWORD (+ GMAIL_USER) for a single Gmail account.
Secrets are never printed.
"""
import argparse, base64, email, imaplib, json, mimetypes, os, pathlib, re, smtplib, sys, time, urllib.request, urllib.parse, urllib.error
from email.message import EmailMessage
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from email.utils import formatdate, make_msgid, getaddresses

REPO = pathlib.Path(__file__).resolve().parent.parent
APPROVED = REPO / "outbox" / "APPROVED"
CONFIG = pathlib.Path(os.environ.get("COS_MAILBOXES", REPO / "config" / "mailboxes.json"))
LOCAL_TOKENS = pathlib.Path(os.environ.get("COS_MAIL_TOKENS", pathlib.Path.home() / ".config/cos/tokens.json"))
GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = "offline_access Mail.ReadWrite Mail.Send User.Read"


def load_config():
    """{label: address} and the owner's own addresses. A missing config means no own addresses,
    so the gate below treats every recipient as outside: it fails closed."""
    try:
        cfg = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}, []
    boxes = {m["label"]: m["address"].lower() for m in cfg.get("mailboxes", [])}
    own = [a.lower() for a in cfg.get("owner_addresses", [])] or list(boxes.values())
    return boxes, own


MAILBOXES, OWN = load_config()
DEFAULT = next(iter(MAILBOXES.values()), "")


def resolve(name):
    return MAILBOXES.get(name, name).lower() if name else DEFAULT

# ----------------------------------------------------------------- credentials

def load_accounts():
    b64 = os.environ.get("MAIL_ACCOUNTS_B64")
    if b64:
        return json.loads(base64.b64decode(b64)), os.environ.get("GRAPH_CLIENT_ID", ""), None
    if LOCAL_TOKENS.exists():
        return json.loads(LOCAL_TOKENS.read_text()), os.environ.get("GRAPH_CLIENT_ID", ""), LOCAL_TOKENS
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if pw:
        u = os.environ.get("GMAIL_USER", DEFAULT)
        return {u: {"method": "gmail_imap", "app_password": pw}}, "", None
    sys.exit("No credentials: set MAIL_ACCOUNTS_B64 (+GRAPH_CLIENT_ID), or create " + str(LOCAL_TOKENS) + ".")

def account(email_addr):
    accts, cid, local_path = load_accounts()
    key = next((k for k in accts if k.lower() == email_addr.lower()), None)
    if not key:
        sys.exit(f"No credentials for {email_addr}. Known: {', '.join(sorted(k for k in accts if not k.startswith('_')))}")
    return key, accts[key], cid, local_path, accts

# ----------------------------------------------------------------- message build

def html_from_text(text):
    """Plain paragraphs -> minimal HTML so Gmail and Outlook wrap to the window instead of
    showing fixed-width lines. Blank line = paragraph break; single newline = <br>."""
    import html as _h
    paras = [pp for pp in re.split(r"\n\s*\n", text.strip()) if pp.strip()]
    body = "".join("<p>" + _h.escape(pp).replace("\n", "<br>") + "</p>" for pp in paras)
    return ('<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'line-height:1.4">' + body + "</body></html>")


def build(a, user):
    m = EmailMessage()
    m["From"] = user; m["To"] = a.to
    if a.cc: m["Cc"] = a.cc
    m["Subject"] = a.subject; m["Date"] = formatdate(localtime=True); m["Message-ID"] = make_msgid()
    body = pathlib.Path(a.body_file).read_text() if a.body_file else (a.body or "")
    if a.html:
        m.set_content("This message is HTML."); m.add_alternative(body, subtype="html")
    else:
        # Never hard-wrap paragraphs. Gmail ignores RFC 3676 format=flowed and displays any
        # line break literally, so a 72-column pre-wrap shows up as a ragged block (seen
        # in practice, after an earlier attempt did exactly that). Keep each paragraph on one
        # line; quoted-printable soft breaks (=\n) vanish on decode, so long lines are safe
        # for SMTP. Add an HTML alternative so clients wrap to the window width.
        m.set_content(body, cte="quoted-printable")
        m.add_alternative(html_from_text(body), subtype="html")
    for p in a.attach or []:
        p = pathlib.Path(p)
        if not p.exists(): sys.exit(f"attachment missing: {p}")
        ctype, _ = mimetypes.guess_type(p.name); main, sub = (ctype or "application/octet-stream").split("/", 1)
        m.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
    return m

def recipients(a):
    return [addr.lower() for _, addr in getaddresses([a.to or "", a.cc or ""]) if addr]

def gate(a):
    gate_list(recipients(a))

def gate_list(rcpts):
    if not rcpts: sys.exit("BLOCKED: no recipients read from the message; refusing to send.")
    outside = [r for r in rcpts if r not in OWN]
    if outside:
        fresh = APPROVED.exists() and time.time() - APPROVED.stat().st_mtime < 3600
        if not fresh:
            sys.exit(f"BLOCKED: recipients outside the owner's own addresses ({', '.join(outside)}). Write it to outbox/ as a "
                     f"draft instead. To send it, the owner reviews the draft and either sends it himself from his own mail "
                     f"client or creates outbox/APPROVED himself in his own terminal (touch outbox/APPROVED, valid 60 min). "
                     f"The agent never creates that file.")

# ----------------------------------------------------------------- gmail (imap/smtp)

def gmail_imap(user, pw):
    c = imaplib.IMAP4_SSL("imap.gmail.com", 993); c.login(user, pw); return c

def gmail_draft(a, user, pw):
    m = build(a, user); c = gmail_imap(user, pw)
    typ, _ = c.append('"[Gmail]/Drafts"', "\\Draft", imaplib.Time2Internaldate(time.time()), m.as_bytes()); c.logout()
    if typ != "OK": sys.exit("IMAP append failed")
    print(f"DRAFT CREATED in {user} Drafts: '{a.subject}' to {a.to}" + (f" with {len(a.attach)} attachment(s)" if a.attach else ""))

def gmail_send(a, user, pw):
    gate(a); m = build(a, user)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw); s.send_message(m)
    print(f"SENT from {user}: '{a.subject}' to {', '.join(recipients(a))}")

def gmail_drafts(c, contains):
    c.select('"[Gmail]/Drafts"'); _, data = c.search(None, "ALL"); out = []
    for i in data[0].split():
        _, d = c.fetch(i, "(BODY.PEEK[HEADER.FIELDS (SUBJECT TO DATE)])")
        hdr = email.message_from_bytes(d[0][1]); subj = str(hdr.get("Subject", ""))
        if not contains or contains.lower() in subj.lower():
            out.append((i, subj, str(hdr.get("To", "")), str(hdr.get("Date", ""))))
    return out

def gmail_list(a, user, pw):
    c = gmail_imap(user, pw)
    for _, s, to, d in gmail_drafts(c, a.contains): print(f"{s!r:60} to {to} ({d})")
    c.logout()

def gmail_delete(a, user, pw):
    c = gmail_imap(user, pw); hits = gmail_drafts(c, a.contains)
    for i, s, to, _ in hits: c.store(i, "+FLAGS", "\\Deleted"); print(f"DELETED draft {s!r} to {to}")
    c.expunge(); c.logout()
    if not hits: print("no draft matched")

# ----------------------------------------------------------------- microsoft 365 (graph)

def graph_token(key, cred, cid, local_path, accts):
    if cred.get("expires_at", 0) > time.time() + 60 and cred.get("access_token"):
        return cred["access_token"]
    if not cred.get("refresh_token"): sys.exit(f"{key}: no refresh token; run the OAuth consent again and store the new token.")
    if not cid: sys.exit("GRAPH_CLIENT_ID is not set.")
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": cid, "refresh_token": cred["refresh_token"], "scope": GRAPH_SCOPES}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://login.microsoftonline.com/common/oauth2/v2.0/token", data=data), timeout=30) as r:
            b = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"{key}: token refresh failed ({e.code}). Reconnect the account and rebuild MAIL_ACCOUNTS_B64.")
    cred.update({"access_token": b["access_token"], "refresh_token": b.get("refresh_token", cred["refresh_token"]), "expires_at": time.time() + b.get("expires_in", 3600) - 60})
    if local_path:
        accts[key] = cred; local_path.write_text(json.dumps(accts, indent=2))
    return cred["access_token"]

def graph_call(tok, method, path, body=None):
    req = urllib.request.Request(GRAPH + path, method=method, headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read(); return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"Graph {method} {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}")

def graph_message(a):
    body = pathlib.Path(a.body_file).read_text() if a.body_file else (a.body or "")
    def rcpts(s): return [{"emailAddress": {"address": addr, "name": name or addr}} for name, addr in getaddresses([s or ""]) if addr]
    msg = {"subject": a.subject, "body": {"contentType": "HTML" if a.html else "Text", "content": body}, "toRecipients": rcpts(a.to)}
    if a.cc: msg["ccRecipients"] = rcpts(a.cc)
    atts = []
    for p in a.attach or []:
        p = pathlib.Path(p)
        if not p.exists(): sys.exit(f"attachment missing: {p}")
        if p.stat().st_size > 3 * 1024 * 1024: sys.exit(f"{p.name} is over 3 MB; Graph simple attachments cap there.")
        atts.append({"@odata.type": "#microsoft.graph.fileAttachment", "name": p.name,
                     "contentType": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                     "contentBytes": base64.b64encode(p.read_bytes()).decode()})
    if atts: msg["attachments"] = atts
    return msg

def graph_draft(a, key, tok):
    r = graph_call(tok, "POST", "/me/messages", graph_message(a))
    print(f"DRAFT CREATED in {key} Drafts: '{a.subject}' to {a.to}" + (f" with {len(a.attach)} attachment(s)" if a.attach else "") + f" (id ...{r.get('id','')[-12:]})")

def graph_send(a, key, tok):
    gate(a); graph_call(tok, "POST", "/me/sendMail", {"message": graph_message(a), "saveToSentItems": True})
    print(f"SENT from {key}: '{a.subject}' to {', '.join(recipients(a))}")

def graph_drafts(tok, contains):
    q = "/me/mailFolders/drafts/messages?$top=50&$select=id,subject,toRecipients,lastModifiedDateTime&$orderby=lastModifiedDateTime%20desc"
    items = graph_call(tok, "GET", q).get("value", [])
    return [m for m in items if not contains or contains.lower() in (m.get("subject") or "").lower()]

def graph_list(a, key, tok):
    for m in graph_drafts(tok, a.contains):
        to = ", ".join(r["emailAddress"]["address"] for r in m.get("toRecipients", []))
        print(f"{(m.get('subject') or '')!r:60} to {to} ({m.get('lastModifiedDateTime')})")

def graph_delete(a, key, tok):
    hits = graph_drafts(tok, a.contains)
    for m in hits:
        graph_call(tok, "DELETE", f"/me/messages/{m['id']}")
        print(f"DELETED draft {(m.get('subject') or '')!r} to {', '.join(r['emailAddress']['address'] for r in m.get('toRecipients', []))}")
    if not hits: print("no draft matched")

def graph_send_draft(a, key, tok):
    hits = graph_drafts(tok, a.contains)
    if len(hits) != 1: sys.exit(f"send-draft needs exactly one matching draft, found {len(hits)}")
    m = graph_call(tok, "GET", f"/me/messages/{hits[0]['id']}?$select=subject,toRecipients,ccRecipients,bccRecipients")
    rc = [r["emailAddress"]["address"].lower() for k in ("toRecipients", "ccRecipients", "bccRecipients") for r in m.get(k, [])]
    gate_list(rc); graph_call(tok, "POST", f"/me/messages/{hits[0]['id']}/send")
    print(f"SENT draft from {key}: {m.get('subject')!r} to {', '.join(rc)}")

# ----------------------------------------------------------------- gmail (REST, OAuth) — works from the cloud

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"

def google_client(accts):
    gc = accts.get("_google_client")
    if gc: return gc
    p = LOCAL_TOKENS.with_name("google_oauth_client.json")
    if p.exists(): return json.loads(p.read_text())
    sys.exit("Google OAuth client missing (google_oauth_client.json next to the tokens file, or _google_client in MAIL_ACCOUNTS_B64).")

def gmail_rest_token(key, cred, local_path, accts):
    if cred.get("expires_at", 0) > time.time() + 60 and cred.get("access_token"):
        return cred["access_token"]
    gc = google_client(accts)
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": gc["client_id"], "client_secret": gc["client_secret"],
                                   "refresh_token": cred["refresh_token"]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
            b = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"{key}: Google token refresh failed ({e.code}): {e.read()[:200].decode(errors='replace')}. Rerun tools/gmail_oauth_connect.py.")
    cred.update({"access_token": b["access_token"], "expires_at": time.time() + b.get("expires_in", 3600) - 60})
    if local_path:
        accts[key] = cred; local_path.write_text(json.dumps(accts, indent=2))
    return cred["access_token"]

def gmail_call(tok, method, path, body=None):
    req = urllib.request.Request(GMAIL_API + path, method=method, headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read(); return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"Gmail API {method} {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}")

def gmail_raw(a, user):
    return base64.urlsafe_b64encode(build(a, user).as_bytes()).decode()

def gmail_rest_draft(a, key, tok):
    r = gmail_call(tok, "POST", "/drafts", {"message": {"raw": gmail_raw(a, key)}})
    print(f"DRAFT CREATED in {key} Drafts: '{a.subject}' to {a.to}" + (f" with {len(a.attach)} attachment(s)" if a.attach else "") + f" (id {r.get('id','')})")

def gmail_rest_send(a, key, tok):
    gate(a); gmail_call(tok, "POST", "/messages/send", {"raw": gmail_raw(a, key)})
    print(f"SENT from {key}: '{a.subject}' to {', '.join(recipients(a))}")

def gmail_rest_drafts(tok, contains):
    out = []
    items = gmail_call(tok, "GET", "/drafts?maxResults=100").get("drafts", [])
    for d in items:
        m = gmail_call(tok, "GET", f"/messages/{d['message']['id']}?format=metadata&metadataHeaders=Subject&metadataHeaders=To&metadataHeaders=Date")
        h = {x["name"]: x["value"] for x in m.get("payload", {}).get("headers", [])}
        if not contains or contains.lower() in h.get("Subject", "").lower():
            out.append((d["id"], h.get("Subject", ""), h.get("To", ""), h.get("Date", "")))
    return out

def gmail_rest_list(a, key, tok):
    for _, s, to, d in gmail_rest_drafts(tok, a.contains): print(f"{s!r:60} to {to} ({d})")

def gmail_rest_delete(a, key, tok):
    hits = gmail_rest_drafts(tok, a.contains)
    for i, s, to, _ in hits:
        gmail_call(tok, "DELETE", f"/drafts/{i}"); print(f"DELETED draft {s!r} to {to}")
    if not hits: print("no draft matched")

def gmail_rest_send_draft(a, key, tok):
    hits = gmail_rest_drafts(tok, a.contains)
    if len(hits) != 1: sys.exit(f"send-draft needs exactly one matching draft, found {len(hits)}")
    d = gmail_call(tok, "GET", f"/drafts/{hits[0][0]}?format=raw")
    h = email.message_from_bytes(base64.urlsafe_b64decode(d["message"]["raw"]))
    rc = [addr.lower() for _, addr in getaddresses([h.get("To", ""), h.get("Cc", ""), h.get("Bcc", "")]) if addr]
    gate_list(rc); gmail_call(tok, "POST", "/drafts/send", {"id": hits[0][0]})
    print(f"SENT draft from {key}: {h.get('Subject')!r} to {', '.join(rc)}")

# ----------------------------------------------------------------- inbox (read-only)

def since_epoch(a):
    if a.since:
        from datetime import datetime
        d = datetime.fromisoformat(a.since.replace("Z", "+00:00"))
        return d.timestamp() if d.tzinfo else time.mktime(d.timetuple())
    return time.time() - 3600 * (a.hours or 24)

def show(key, rows):
    print(f"== {key}: {len(rows)} message(s)")
    for when, frm, subj, unread, snip in rows:
        print(f"{'*' if unread else ' '} {when}  {frm[:45]:45}  {subj[:80]}")
        if snip: print(f"      {snip[:160]}")

def gmail_rest_inbox(a, key, tok):
    q = urllib.parse.quote(f"in:inbox after:{int(since_epoch(a))}")
    rows = []
    for m in gmail_call(tok, "GET", f"/messages?q={q}&maxResults={a.max}").get("messages", []):
        x = gmail_call(tok, "GET", f"/messages/{m['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date")
        h = {i["name"]: i["value"] for i in x.get("payload", {}).get("headers", [])}
        rows.append((h.get("Date", ""), h.get("From", ""), h.get("Subject", ""), "UNREAD" in x.get("labelIds", []), x.get("snippet", "")))
    show(key, rows)

def graph_inbox(a, key, tok):
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(since_epoch(a), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = (f"/me/mailFolders/inbox/messages?$top={a.max}&$orderby=receivedDateTime%20desc"
         f"&$filter=receivedDateTime%20ge%20{iso}&$select=receivedDateTime,from,subject,isRead,bodyPreview")
    rows = [(m.get("receivedDateTime", ""), (m.get("from") or {}).get("emailAddress", {}).get("address", ""), m.get("subject") or "",
             not m.get("isRead"), (m.get("bodyPreview") or "").replace("\r", " ").replace("\n", " ")) for m in graph_call(tok, "GET", q).get("value", [])]
    show(key, rows)

# ----------------------------------------------------------------- main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["draft", "send", "list-drafts", "delete-draft", "send-draft", "inbox"])
    ap.add_argument("--account", default="")
    ap.add_argument("--to"); ap.add_argument("--cc"); ap.add_argument("--subject", default="")
    ap.add_argument("--body-file"); ap.add_argument("--body"); ap.add_argument("--html", action="store_true")
    ap.add_argument("--attach", nargs="*"); ap.add_argument("--contains")
    ap.add_argument("--allow-wrapped", action="store_true", help="send a body whose short lines are deliberate")
    ap.add_argument("--hours", type=float); ap.add_argument("--since"); ap.add_argument("--max", type=int, default=50); ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    a.account = resolve(a.account)
    if not a.account and not a.all:
        sys.exit("No mailbox: pass --account or create config/mailboxes.json (see config/mailboxes.example.json).")
    if a.cmd in ("draft", "send") and not a.html and not a.allow_wrapped:
        # Refuse a hard-wrapped body: Gmail shows every line break literally, so a paragraph
        # wrapped by a text editor arrives as a ragged block . Fix the file, or pass
        # --allow-wrapped for a body that is meant to be line-based (a table, a list).
        from preflight import wrapped_runs
        body_text = pathlib.Path(a.body_file).read_text() if a.body_file else (a.body or "")
        runs = wrapped_runs(body_text)
        if runs:
            sys.exit("REFUSED: body has hard-wrapped paragraphs (Gmail shows the breaks). First one: "
                     + runs[0][0][:70] + "...  Unwrap it, or pass --allow-wrapped if the lines are deliberate.")
    if a.cmd in ("draft", "send") and not (a.to and a.subject and (a.body or a.body_file)):
        sys.exit("--to, --subject and --body/--body-file are required")
    if a.cmd in ("delete-draft", "send-draft") and not a.contains:
        sys.exit(f"--contains is required for {a.cmd}")
    if a.cmd == "inbox":
        if a.all and not MAILBOXES:
            sys.exit("No mailboxes configured: copy config/mailboxes.example.json to config/mailboxes.json.")
        for addr in (list(MAILBOXES.values()) if a.all else [a.account]):
            key, cred, cid, local_path, accts = account(addr)
            try:
                if cred.get("method") == "graph": graph_inbox(a, key, graph_token(key, cred, cid, local_path, accts))
                elif cred.get("method_rest") == "gmail_oauth" and cred.get("refresh_token"): gmail_rest_inbox(a, key, gmail_rest_token(key, cred, local_path, accts))
                else: print(f"== {key}: inbox needs Gmail REST or Graph credentials")
            except SystemExit as e:
                print(f"== {key}: FAILED {e}")
        sys.exit(0)
    key, cred, cid, local_path, accts = account(a.account)
    if cred.get("method") == "graph":
        tok = graph_token(key, cred, cid, local_path, accts)
        {"draft": graph_draft, "send": graph_send, "list-drafts": graph_list, "delete-draft": graph_delete, "send-draft": graph_send_draft}[a.cmd](a, key, tok)
    elif cred.get("method_rest") == "gmail_oauth" and cred.get("refresh_token"):
        tok = gmail_rest_token(key, cred, local_path, accts)
        {"draft": gmail_rest_draft, "send": gmail_rest_send, "list-drafts": gmail_rest_list, "delete-draft": gmail_rest_delete, "send-draft": gmail_rest_send_draft}[a.cmd](a, key, tok)
    else:
        pw = cred.get("app_password")
        if not pw: sys.exit(f"{key}: no app password on file.")
        if a.cmd == "send-draft": sys.exit("send-draft needs the Gmail REST or Graph path, not IMAP.")
        {"draft": gmail_draft, "send": gmail_send, "list-drafts": gmail_list, "delete-draft": gmail_delete}[a.cmd](a, key, pw)
