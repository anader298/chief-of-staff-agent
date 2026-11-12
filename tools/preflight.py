#!/usr/bin/env python3
"""Preflight: check what the owner will actually see before it reaches him. Stdlib only.

  python3 tools/preflight.py email <body.txt> [--html]

Exit 1 on any failure and print every failure, so the fix is one pass. tools/mail.py calls
wrapped_runs() itself before every draft or send.

Why this exists: on one day several things reached the owner broken, including an email whose
paragraphs were hard-wrapped at 72 columns and a document whose page count had been predicted
rather than measured. Each was a property of the delivered file. So check the delivered file,
not the spec. Add a check here the same day a new rule is stated.
"""
import argparse, pathlib, re, sys

# --- email rules -------------------------------------------------------------------------------
def wrapped_runs(text):
    """Paragraphs that were hard-wrapped by a text editor: two or more consecutive non-blank lines
    that are all 45-100 chars wide. A real paragraph is one long line; a signature is short lines."""
    runs, run = [], []
    def is_wrapped(r):
        # A list of one-per-line items ends every line with punctuation; a wrapped paragraph does not.
        return len(r) >= 2 and any(not ln.rstrip().endswith((".", ":", "?", "!", ";")) for ln in r[:-1])
    for ln in text.replace("\r\n", "\n").split("\n") + [""]:
        if ln.strip() and 45 <= len(ln) <= 100 and not ln.lstrip().startswith((">", "-", "*", "|", "#")):
            run.append(ln)
        else:
            if is_wrapped(run): runs.append(run)
            run = []
    return runs

def check_email(path, html):
    fails = []
    text = pathlib.Path(path).read_text()
    if not html:
        for run in wrapped_runs(text):
            fails.append("hard-wrapped paragraph (will show ragged in Gmail): " + run[0][:60] + "...")
    bad = sorted({c for c in text if ord(c) > 127})
    if bad: fails.append(f"non-ASCII characters that can render as boxes: {bad}")
    if "**" in text: fails.append("markdown bold markers (**) in the body")
    if re.search(r"^(# DRAFT|\*\*To:\*\*|Status:)", text, re.M):
        fails.append("outbox draft header left in the body")
    # round trip through the real builder: decoded plain text must equal the source
    try:
        import importlib.util, types, email, email.policy
        spec = importlib.util.spec_from_file_location("m", pathlib.Path(__file__).with_name("mail.py"))
        m = importlib.util.module_from_spec(spec)
        try: spec.loader.exec_module(m)
        except SystemExit: pass
        a = types.SimpleNamespace(to="owner@example.com", cc=None, subject="preflight", body_file=None,
                                  body=text, html=html, attach=None, allow_wrapped=True)
        raw = m.build(a, "owner@example.com").as_bytes()
        if max(len(l) for l in raw.split(b"\n")) > 998: fails.append("raw line over the 998-byte SMTP limit")
        back = email.message_from_bytes(raw, policy=email.policy.default)
        parts = {p.get_content_type(): p for p in back.walk() if not p.is_multipart()}
        if not html:
            if parts["text/plain"].get_content().strip() != text.strip():
                fails.append("decoded text/plain differs from the source (transport inserted breaks)")
            if "text/html" not in parts: fails.append("no HTML alternative; Gmail will not wrap to the window")
    except Exception as e:  # pragma: no cover
        fails.append(f"round trip through mail.py failed: {e}")
    return fails

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["email"]); ap.add_argument("path")
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()
    fails = check_email(a.path, a.html)
    name = pathlib.Path(a.path).name
    if fails:
        print(f"PREFLIGHT FAIL {name}"); [print("  - " + f) for f in fails]; sys.exit(1)
    print(f"PREFLIGHT OK {name}")

if __name__ == "__main__":
    main()
