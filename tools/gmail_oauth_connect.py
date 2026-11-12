#!/usr/bin/env python3
"""One-time (per Gmail account) OAuth consent for the Gmail REST API. Run on a machine with a browser.

  python3 tools/gmail_oauth_connect.py you@example.com

Needs a Google OAuth client (Desktop app type) saved as google_oauth_client.json next to the tokens file
(env COS_MAIL_TOKENS, default ~/.config/cos/tokens.json).

Starts a loopback listener, opens Google's consent page in Chrome, waits for the redirect, exchanges the code,
and stores {method_rest: gmail_oauth, refresh_token, ...} on that account in the tokens file (an app
password entry, if any, is kept as a sibling key). Scope: gmail.modify (read, draft, send, delete). Nothing is printed
but the account name and status.
"""
import http.server, json, os, pathlib, secrets, sys, threading, time, urllib.parse, urllib.request, webbrowser

TOKENS = pathlib.Path(os.environ.get("COS_MAIL_TOKENS", pathlib.Path.home() / ".config/cos/tokens.json"))
CLIENT = json.loads((TOKENS.with_name("google_oauth_client.json")).read_text())
SCOPE = "https://www.googleapis.com/auth/gmail.modify"
PORT = 8765

def main(account):
    state = secrets.token_urlsafe(16); got = {}
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.end_headers()
            self.wfile.write(b"<h2>Connected. You can close this tab.</h2>")
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    redirect = f"http://127.0.0.1:{PORT}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": CLIENT["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state, "login_hint": account, "include_granted_scopes": "true"})
    webbrowser.open(url)
    print(f"[{account}] consent page opened in the browser; waiting up to 10 minutes for approval...", flush=True)
    t0 = time.time()
    while "code" not in got and "error" not in got and time.time() - t0 < 600:
        time.sleep(1)
    threading.Thread(target=srv.shutdown, daemon=True).start()
    if "code" not in got:
        sys.exit(f"[{account}] no code received ({got.get('error', 'timeout')})")
    if got.get("state") != state:
        sys.exit("state mismatch")
    data = urllib.parse.urlencode({"code": got["code"], "client_id": CLIENT["client_id"], "client_secret": CLIENT["client_secret"],
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
        tok = json.loads(r.read())
    if "refresh_token" not in tok:
        sys.exit(f"[{account}] Google returned no refresh token; revoke the app at myaccount.google.com/permissions and rerun.")
    # confirm which mailbox granted
    req = urllib.request.Request("https://gmail.googleapis.com/gmail/v1/users/me/profile", headers={"Authorization": "Bearer " + tok["access_token"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        who = json.loads(r.read())["emailAddress"].lower()
    if who != account.lower():
        sys.exit(f"[{account}] the consent was given by {who}, not {account}. Rerun and pick the right Google account.")
    d = json.loads(TOKENS.read_text()) if TOKENS.exists() else {}
    e = d.setdefault(account, {})
    e.update({"method_rest": "gmail_oauth", "refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
              "expires_at": time.time() + tok.get("expires_in", 3600) - 60, "scope": SCOPE})
    TOKENS.parent.mkdir(parents=True, exist_ok=True)
    TOKENS.write_text(json.dumps(d, indent=2)); os.chmod(TOKENS, 0o600)
    print(f"[{account}] connected via Gmail REST; refresh token stored in tokens.json")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: gmail_oauth_connect.py you@example.com")
    main(sys.argv[1])
