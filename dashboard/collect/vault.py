"""Copy the Obsidian vault's notes into one JSON file for the dashboard's Memory tab.

Plain markdown only; frontmatter is parsed into fm. Skips .git and .obsidian. Personal: data/ is
gitignored and the public export leaves this file empty.
"""
import json
import os
import re
import time

FM = re.compile(r"^---\n(.*?)\n---\n", re.S)
WIKI = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def _frontmatter(text):
    m = FM.match(text)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
            fm[k.strip()] = v
    return fm, text[m.end():]


def export(root, out):
    notes = []
    if not os.path.isdir(root):
        json.dump({"root": root, "generated_at": time.time(), "notes": [], "missing": True}, open(out, "w"))
        return
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in (".git", ".obsidian", ".trash"))
        for fn in sorted(fns):
            if not fn.endswith(".md"):
                continue
            full = os.path.join(dp, fn)
            try:
                raw = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            rel = os.path.relpath(full, root)
            fm, body = _frontmatter(raw)
            title = next((l[2:].strip() for l in body.split("\n") if l.startswith("# ")), fn[:-3])
            notes.append({"path": rel, "folder": os.path.dirname(rel) or "", "name": fn[:-3], "title": title,
                          "mtime": os.path.getmtime(full), "size": len(raw), "fm": fm, "text": body.strip(),
                          "links": sorted({m.group(1).strip() for m in WIKI.finditer(body)})})
    json.dump({"root": root, "generated_at": time.time(), "notes": notes}, open(out, "w"))
