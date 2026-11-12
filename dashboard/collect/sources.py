"""Everything that is not a transcript: catalog, memory stores, live sessions,
cos log lines (cloud routine runs) and git commits."""
import json
import os
import re
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from classify import CONFIG, workspace_of_slug

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
COS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CT = ZoneInfo(CONFIG.get("timezone", "UTC"))  # the owner's local time; log lines are written in it

ROUTINES = {
    "brief-8am": ("Brief 8am", "Morning brief"),
    "brief-1pm": ("Brief 1pm", "Midday brief"),
    "brief-6pm": ("Brief 6pm", "Evening brief"),
    "watcher": ("Watcher", "Hourly mail + calendar pass"),
    "optimizer": ("Optimizer", "Weekly audit Wed 3am, proposes edits"),
    "weekly-review": ("Weekly review", "Sunday 7pm, lessons as a PR on review/<date>"),
}
# declared resources for routines whose prompt is not in routines/
EXTRA_ROUTINES = {}


def _mailbox_labels():
    """Labels only, never addresses: from config/mailboxes.json (or its example)."""
    for n in ("mailboxes.json", "mailboxes.example.json"):
        try:
            with open(os.path.join(COS, "config", n)) as fh:
                return [m["label"] for m in json.load(fh).get("mailboxes", [])]
        except (OSError, ValueError, KeyError):
            continue
    return []


OWN_MAILBOXES = _mailbox_labels()
LAUNCHD_PREFIX = CONFIG.get("launchd_prefix", "com.example.cos")


def _frontmatter(path):
    out = {}
    try:
        with open(path, errors="replace") as fh:
            head = fh.read(2000)
    except OSError:
        return out
    if head.startswith("---"):
        block = head[3:head.find("\n---", 3)]
        for line in block.splitlines():
            m = re.match(r"\s*(name|description|type):\s*(.*)", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"')[:200]
    return out


def catalog():
    skills = set()
    for base in (os.path.join(CLAUDE, "skills"), os.path.join(CLAUDE, "skills", "synced"), os.path.join(COS, "skills")):
        if os.path.isdir(base):
            for n in os.listdir(base):
                if n != "synced" and os.path.exists(os.path.join(base, n, "SKILL.md")):
                    skills.add(n)
    agents = {}
    for base in (os.path.join(CLAUDE, "agents"), os.path.join(COS, "agents")):
        if os.path.isdir(base):
            for n in os.listdir(base):
                if n.endswith(".md"):
                    fm = _frontmatter(os.path.join(base, n))
                    agents[n[:-3]] = fm.get("description", "")
    plugins = []
    try:
        plugins = [k.split("@")[0] for k in json.load(open(os.path.join(CLAUDE, "plugins", "installed_plugins.json")))["plugins"]]
    except (OSError, ValueError, KeyError):
        pass
    mcp = set()
    try:
        cj = json.load(open(os.path.join(HOME, ".claude.json")))
        mcp.update((cj.get("mcpServers") or {}).keys())
        for p in (cj.get("projects") or {}).values():
            mcp.update((p.get("mcpServers") or {}).keys())
    except (OSError, ValueError):
        pass
    routines = {}
    rdir = os.path.join(COS, "routines")
    for n in sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []:
        if n.endswith(".md"):
            routines[n[:-3]] = open(os.path.join(rdir, n), errors="replace").read()
    for rid, txt in EXTRA_ROUTINES.items():
        routines.setdefault(rid, txt)
    hooks = []
    try:
        for event, groups in (json.load(open(os.path.join(CLAUDE, "settings.json"))).get("hooks") or {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    hooks.append({"event": event, "matcher": g.get("matcher", ""),
                                  "command": os.path.basename((h.get("command") or "").split()[0]) if h.get("command") else ""})
    except (OSError, ValueError, AttributeError):
        pass
    launchd = []
    ldir = os.path.join(HOME, "Library", "LaunchAgents")
    for n in sorted(os.listdir(ldir)) if os.path.isdir(ldir) else []:
        if n.startswith(LAUNCHD_PREFIX):
            label = n[:-6]
            try:
                out = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), label)],
                                     capture_output=True, text=True, timeout=5).stdout
            except (OSError, subprocess.SubprocessError):
                out = ""
            state = re.search(r"\bstate = (\w+)", out)
            code = re.search(r"last exit code = (\S+)", out)
            launchd.append({"label": label, "loaded": bool(out), "state": state.group(1) if state else "not loaded",
                            "last_exit": code.group(1) if code else ""})
    n8n = []
    ndir = os.path.join(COS, "tools", "n8n")
    for n in sorted(os.listdir(ndir)) if os.path.isdir(ndir) else []:
        if n.endswith(".json"):
            try:
                d = json.load(open(os.path.join(ndir, n)))
                n8n.append({"file": n, "name": d.get("name", n), "nodes": len(d.get("nodes", []))})
            except (OSError, ValueError):
                pass
    return {"skills": sorted(skills), "agents": agents, "plugins": plugins, "mcp_config": sorted(mcp),
            "routines": sorted(routines), "routine_text": routines, "n8n": n8n, "hooks": hooks,
            "launchd": launchd, "mailboxes": OWN_MAILBOXES}


def routine_resources(text):
    """Resources a routine prompt declares, with read/write."""
    t = text.lower()
    out = {}
    if "mail.py" in t or "mailbox" in t or "gmail" in t:
        out["email"] = "write" if re.search(r"email (it|to)|mail\.py draft|send", t) else "read"
    if "calendar" in t:
        out["calendar"] = "read"
    if re.search(r"commit|push|append one line to log", t):
        out["github"] = "write"
    if "skills/" in t or "job-triage" in t:
        out["skills"] = "read"
    if "outbox/" in t or "briefs/" in t:
        out["folders"] = "write"
    if "websearch" in t or "web search" in t:
        out["internet"] = "read"
    if "memory" in t:
        out["memory"] = "read"
    return out


def memory_stores():
    out = []
    pdir = os.path.join(CLAUDE, "projects")
    for slug in sorted(os.listdir(pdir)):
        mdir = os.path.join(pdir, slug, "memory")
        if not os.path.isdir(mdir):
            continue
        files = []
        index = ""
        if os.path.exists(os.path.join(mdir, "MEMORY.md")):
            index = open(os.path.join(mdir, "MEMORY.md"), errors="replace").read()
        for n in os.listdir(mdir):
            if not n.endswith(".md") or n == "MEMORY.md":
                continue
            p = os.path.join(mdir, n)
            fm = _frontmatter(p)
            files.append({"file": n, "name": fm.get("name", n[:-3]), "desc": fm.get("description", ""),
                          "type": fm.get("type", ""), "mtime": os.path.getmtime(p), "indexed": n in index})
        files.sort(key=lambda f: -f["mtime"])
        out.append({"slug": slug, "ws": workspace_of_slug(slug), "count": len(files),
                    "last": files[0]["mtime"] if files else None,
                    "unindexed": sum(1 for f in files if not f["indexed"]), "files": files[:40]})
    return out


def live_sessions():
    """pid files only (never the .key files); keep processes that are alive."""
    out = {}
    sdir = os.path.join(CLAUDE, "sessions")
    for n in os.listdir(sdir) if os.path.isdir(sdir) else []:
        if not re.fullmatch(r"\d+\.json", n):
            continue
        try:
            d = json.load(open(os.path.join(sdir, n)))
            os.kill(int(d["pid"]), 0)
        except (OSError, ValueError, KeyError, ProcessLookupError, PermissionError):
            continue
        if d.get("sessionId"):
            out[d["sessionId"]] = {"pid": d["pid"], "status": d.get("status", ""), "updated": (d.get("updatedAt") or 0) / 1000,
                                   "kind": d.get("kind", ""), "cwd": d.get("cwd", "")}
    return out


def _routine_of(trigger):
    t = trigger.lower()
    if "watcher" in t:
        return "watcher"
    if "weekly review" in t:
        return "weekly-review"
    if "optimizer" in t:
        return "optimizer"
    if "brief" in t:
        m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", t)
        if m:
            hh = int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)
        else:
            m = re.search(r"\b(\d{3,4})\b", t)
            hh = int(m.group(1)[:-2]) if m else -1
        if hh < 0:
            return None
        return "brief-8am" if hh < 11 else "brief-1pm" if hh < 16 else "brief-6pm"
    return None


ROUTINE_SUBJECT = re.compile(r"^\s*(cos\s+)?(brief\s+\d{3,4}|watcher\b|weekly review|optimizer\b)", re.I)


def _log_texts():
    """Log files from the working tree plus origin/main (cloud routines push there first)."""
    texts = {}
    ldir = os.path.join(COS, "log")
    for n in sorted(os.listdir(ldir)) if os.path.isdir(ldir) else []:
        texts[n] = open(os.path.join(ldir, n), errors="replace").read()
    try:
        names = subprocess.run(["git", "-C", COS, "ls-tree", "--name-only", "origin/main", "log/"],
                               capture_output=True, text=True, timeout=10).stdout.split()
        for path in names:
            remote = subprocess.run(["git", "-C", COS, "show", "origin/main:" + path],
                                    capture_output=True, text=True, timeout=10).stdout
            n = os.path.basename(path)
            local = texts.get(n, "")
            extra = [l for l in remote.splitlines() if l not in set(local.splitlines())]
            texts[n] = local + "\n" + "\n".join(extra)
    except (OSError, subprocess.SubprocessError):
        pass
    return texts


def git_fetch():
    try:
        subprocess.run(["git", "-C", COS, "fetch", "-q", "origin"], capture_output=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        pass


def cos_log():
    """log/YYYY-MM.md lines `YYYY-MM-DD HH:MM CT | trigger | summary` -> routine runs."""
    runs = []
    seen = set()
    for n, text in sorted(_log_texts().items()):
        for line in text.splitlines():
            m = re.match(r"\s*-?\s*~?(\d{4}-\d{2}-\d{2}) ~?(\d{1,2}:\d{2}) (CT|UTC)[^|]*\| ([^|]+)\|?(.*)", line)
            if not m:
                continue
            day, hm, zone, trig, summary = m.groups()
            if not summary.strip():  # watcher lines often have no third column
                summary = trig
            rid = _routine_of(trig)
            if not rid and re.search(r"\b(cloud session|interactive)\b", trig, re.I):
                rid = "cloud"  # a web/phone session's own receipt (agents/cos.md rule 4)
            if not rid:
                continue
            tz = CT if zone == "CT" else ZoneInfo("UTC")
            t = datetime.strptime(day + " " + hm, "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp()
            if (rid, t) in seen:
                continue
            seen.add((rid, t))
            failed = re.search(r"FAILED:\s*(?!none)\S", summary, re.I)
            runs.append({"t": t, "routine": rid, "d": " ".join(summary.split())[:160],
                         "st": "failed" if failed else "ok"})
    return runs


def git_commits(days=45):
    try:
        out = subprocess.run(["git", "-C", COS, "log", "--all", "--since=%d days ago" % days,
                              "--format=%H%x1f%an%x1f%at%x1f%s%x1f%(trailers:key=Claude-Session,valueonly,separator=%x2C)%x1f%D"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    commits = []
    for line in out.splitlines():
        h, author, at, subj, trailer, refs = (line.split("\x1f") + [""] * 6)[:6]
        cloud = author == "Claude"
        session = trailer.strip().rsplit("/", 1)[-1] if trailer.strip() else ""
        commits.append({"h": h[:8], "author": author, "t": int(at), "s": subj[:120], "src": "cloud" if cloud else "local",
                        "routine": _routine_of(subj) if cloud and ROUTINE_SUBJECT.search(subj) else None,
                        "session": session, "refs": refs.strip()[:80]})
    # a cloud session that made several commits is interactive work, not a routine run
    per = {}
    for c in commits:
        if c["src"] == "cloud" and c["session"]:
            per.setdefault(c["session"], []).append(c)
    for group in per.values():
        if len(group) > 2:
            for c in group:
                c["routine"] = None
    return commits


def gh_remote(repo=None):
    """Branches, PRs and repo size via gh (cached 4 min by gh itself). Best effort."""
    repo = repo or CONFIG.get("repo")
    if not repo:
        return None
    def call(path):
        try:
            r = subprocess.run(["gh", "api", "--cache", "240s", path], capture_output=True, text=True, timeout=20)
            return json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    meta = call("repos/%s" % repo)
    if not meta:
        return None
    pulls = call("repos/%s/pulls?state=all&per_page=20" % repo) or []
    branches = call("repos/%s/branches?per_page=50" % repo) or []
    return {
        "repo": repo, "private": meta.get("private"), "size_kb": meta.get("size"), "pushed_at": meta.get("pushed_at"),
        "default_branch": meta.get("default_branch"),
        "branches": [b.get("name") for b in branches],
        "pulls": [{"n": p.get("number"), "title": (p.get("title") or "")[:100], "state": p.get("state"),
                   "merged": bool(p.get("merged_at")), "branch": (p.get("head") or {}).get("ref"),
                   "created": p.get("created_at"), "updated": p.get("updated_at"), "url": p.get("html_url")}
                  for p in pulls],
    }
