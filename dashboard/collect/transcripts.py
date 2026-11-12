"""Incremental reader for ~/.claude/projects/<slug>/*.jsonl and subagent transcripts.

Keeps a byte offset per file (reset when the inode changes or the file shrinks),
reads complete lines only, skips api-request-blob lines before json.loads.

Dedupe is global, not per file: copied project folders and resumed sessions repeat
the same lines, so line uuids, tool_use ids and message ids are remembered across
files (seen.json). Usage is counted per message id as the final value: streamed
repeats of one message only add their extra output tokens.
"""
import json
import os
import re
import time
from datetime import datetime

from classify import classify, workspace_of, workspace_of_slug

PROJECTS = os.path.expanduser("~/.claude/projects")
SLASH = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")
SKIP_LINE_MARKERS = ('"api-request-blob"', '"type":"api-request"', '"api-request-shape"',
                     '"file-history-snapshot"', '"deferred_tools_record"')
SKILL_LINE = re.compile(r"^- ([\w:.-]+):", re.M)


def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def day_of(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def norm_model(m):
    return re.sub(r"\[.*?\]$", "", m or "")


def weighted(u):
    return (u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0)
            + 0.1 * u.get("cache_read_input_tokens", 0) + 5 * u.get("output_tokens", 0))


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def new_session(sid, slug):
    return {"id": sid, "ws": workspace_of_slug(slug), "cwd": "", "title": "", "title_src": "",
            "started": None, "last_t": None, "prompts": 0, "msgs": 0, "tokens": 0, "ctx": 0,
            "model": "", "last": "", "first_prompt": "", "cost_state": None, "model_cost": {},
            "cost_start": None, "skills": {}, "mcp": {}, "subagents": {}, "res": {}, "usage": {}, "slug": slug,
            "entry": "", "compacts": 0, "remote": "", "today_w": {}}


def _bump(d, k, n=1):
    d[k] = d.get(k, 0) + n


def iter_files(max_age_days):
    cutoff = time.time() - max_age_days * 86400
    for slug in sorted(os.listdir(PROJECTS)):
        pdir = os.path.join(PROJECTS, slug)
        if not os.path.isdir(pdir):
            continue
        for name in sorted(os.listdir(pdir)):
            path = os.path.join(pdir, name)
            if name.endswith(".jsonl"):
                if os.path.getmtime(path) >= cutoff:
                    yield path, slug, name[:-6], None
            elif os.path.isdir(os.path.join(path, "subagents")):
                sdir = os.path.join(path, "subagents")
                for sub in sorted(os.listdir(sdir)):
                    if sub.endswith(".jsonl") and os.path.getmtime(os.path.join(sdir, sub)) >= cutoff:
                        meta = {}
                        mp = os.path.join(sdir, sub[:-6] + ".meta.json")
                        if os.path.exists(mp):
                            try:
                                meta = json.load(open(mp))
                            except (OSError, ValueError):
                                pass
                        atype = meta.get("agentType") or "general-purpose"
                        yield os.path.join(sdir, sub), slug, name, ("cos" if atype == "cos" else "sub:" + atype)


class Reader:
    def __init__(self, state, sessions, seen):
        self.state = state                    # {"files": {...}, "pending": {...}, "inv": {...}}
        self.sessions = sessions              # sid -> acc
        self.seen = seen                      # {"lines": set(uuid|tool id), "msgs": {msg id: [output tokens, sid]}}
        self.events = []                      # new events this pass
        inv = state.setdefault("inv", {})
        for k in ("mcp", "mcp_failed", "skills", "agents"):
            inv.setdefault(k, {})
        self.inv = inv

    def run(self, max_age_days=120):
        files = self.state.setdefault("files", {})
        pending = self.state.setdefault("pending", {})
        for path, slug, sid, agent in iter_files(max_age_days):
            try:
                st = os.stat(path)
            except OSError:
                continue
            f = files.get(path)
            if not f or f.get("ino") != st.st_ino or st.st_size < f.get("off", 0):
                f = files[path] = {"ino": st.st_ino, "off": 0}
            if st.st_size == f["off"]:
                continue
            with open(path, "rb") as fh:
                fh.seek(f["off"])
                chunk = fh.read()
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            f["off"] += end + 1
            acc = self.sessions.setdefault(sid, new_session(sid, slug))
            for raw in chunk[:end].split(b"\n"):
                if any(m.encode() in raw[:200] for m in SKIP_LINE_MARKERS):
                    continue
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                self.line(o, acc, agent or "cos", pending, sub=bool(agent))
        # flush tool calls whose result never arrived within 30 min
        now = time.time()
        for k in list(pending):
            if now - pending[k]["t"] > 1800:
                ev = pending.pop(k)
                ev.setdefault("st", "ok")
                self.events.append(ev)

    def line(self, o, acc, agent, pending, sub):
        typ = o.get("type")
        # copied/resumed transcripts repeat lines with the same uuid: process each once
        uid = o.get("uuid")
        if uid and typ in ("user", "assistant", "attachment", "system"):
            if uid in self.seen["lines"]:
                return
            self.seen["lines"].add(uid)
        t = ts(o.get("timestamp")) if o.get("timestamp") else None
        if t:
            acc["started"] = min(acc["started"] or t, t)
            acc["last_t"] = max(acc["last_t"] or t, t)
        if o.get("cwd") and not sub and not acc["cwd"]:
            acc["cwd"] = o["cwd"]
            acc["ws"] = workspace_of(o["cwd"])
        if o.get("entrypoint") and not acc["entry"]:
            acc["entry"] = o["entrypoint"]

        if typ == "custom-title":
            acc["title"], acc["title_src"] = o.get("customTitle", "")[:120], "custom"
            return
        if typ == "ai-title" and acc["title_src"] != "custom":
            acc["title"], acc["title_src"] = o.get("aiTitle", "")[:120], "ai"
            return
        if typ == "cost-state" and not sub:
            acc["cost_state"] = o.get("totalCostUSD")
            acc["cost_start"] = o.get("startTime")
            mc = {}
            for m, v in (o.get("modelUsage") or {}).items():
                mc[norm_model(m)] = mc.get(norm_model(m), 0) + (v.get("costUSD") or 0)
            acc["model_cost"] = mc
            return
        if typ == "system" and o.get("subtype") == "compact_boundary":
            acc["compacts"] += 1
            return
        if typ == "attachment" and t:
            self.attachment(o.get("attachment") or {}, acc, t, sub)
            return
        if typ == "user" and t:
            self.user(o, acc, agent, t, pending, sub)
            return
        if typ == "assistant" and t:
            self.assistant(o, acc, agent, t, pending, sub)

    def attachment(self, a, acc, t, sub):
        typ = a.get("type")
        if typ == "deferred_tools_delta" and not sub:
            for n in a.get("addedNames") or []:
                if n.startswith("mcp__"):
                    parts = n.split("__")
                    rec = self.inv["mcp"].setdefault(parts[1], {"tools": [], "listed": 0})
                    if len(parts) > 2 and parts[2] not in rec["tools"]:
                        rec["tools"].append(parts[2])
                    rec["listed"] = max(rec["listed"], t)
            for fobj in a.get("failedMcpServers") or []:
                name = fobj.get("name", "?")
                prev = self.inv["mcp_failed"].get(name, {})
                if t >= prev.get("t", 0):
                    self.inv["mcp_failed"][name] = {"t": t, "err": str(fobj.get("error", ""))[:160],
                                                    "code": str(fobj.get("errorCode", ""))}
        elif typ == "skill_listing" and not sub:
            for name in SKILL_LINE.findall(a.get("content") or ""):
                self.inv["skills"][name] = max(self.inv["skills"].get(name, 0), t)
        elif typ == "agent_listing_delta" and not sub:
            for name in a.get("addedTypes") or []:
                self.inv["agents"][name] = max(self.inv["agents"].get(name, 0), t)
        elif typ == "remote_session_change" and not sub:
            acc["remote"] = (a.get("url") or "").rsplit("/", 1)[-1]

    def user(self, o, acc, agent, t, pending, sub):
        msg = o.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    ev = pending.pop(b.get("tool_use_id", ""), None)
                    if ev:
                        ev["st"] = "failed" if b.get("is_error") else "ok"
                        ev["dur"] = max(0, round((t - ev["t"]) * 1000))
                        self.events.append(ev)
        if sub or o.get("isMeta") or o.get("toolUseResult") is not None:
            return
        txt = text_of(content)
        if not txt:
            return
        human = (o.get("origin") or {}).get("kind") == "human" or o.get("promptSource") == "typed"
        m = SLASH.search(txt)
        if m:
            name = m.group(1)
            res = "plugins" if ":" in name else "skills"
            # built-in commands are filtered at build time against the skill inventory
            self.events.append({"t": t, "k": "skill", "s": acc["id"], "w": acc["ws"], "a": agent,
                                "r": res, "p": "read", "n": name, "d": "/" + name, "st": "ok", "src": "local",
                                "slash": True})
        if human or (isinstance(content, str) and not txt.startswith("<")):
            acc["prompts"] += 1
            if not acc["first_prompt"] and not txt.startswith("<"):
                acc["first_prompt"] = " ".join(txt.split())[:120]

    def assistant(self, o, acc, agent, t, pending, sub):
        msg = o.get("message") or {}
        mid = msg.get("id")
        u = msg.get("usage")
        model = norm_model(msg.get("model"))
        if mid and u and model and model != "<synthetic>":
            out = u.get("output_tokens", 0)
            prev = self.seen["msgs"].get(mid)
            if prev is None:
                inp = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                       + u.get("cache_read_input_tokens", 0))
                self.seen["msgs"][mid] = [out, acc["id"]]
                tok, wt = inp + out, weighted(u)
                if not sub:
                    acc["msgs"] += 1
                    acc["ctx"] = inp
                    acc["model"] = model
            elif out > prev[0] and prev[1] == acc["id"]:
                tok, wt = out - prev[0], 5 * (out - prev[0])   # streamed repeat: only the extra output
                prev[0] = out
            else:
                tok = wt = 0
            if tok:
                acc["tokens"] += tok
                key = "|".join((model, day_of(t), agent))
                cell = acc["usage"].setdefault(key, [0, 0])
                cell[0] += wt
                cell[1] += tok
        for b in msg.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and not sub and b.get("text", "").strip():
                acc["last"] = " ".join(b["text"].split())[:160]
            if b.get("type") != "tool_use":
                continue
            tid = b.get("id")
            if tid:
                if "t:" + tid in self.seen["lines"]:
                    continue
                self.seen["lines"].add("t:" + tid)
            name = b.get("name", "")
            inp = b.get("input") or {}
            c = classify(name, inp)
            if not c:
                continue
            res, perm, item, detail = c
            if name == "Agent":
                _bump(acc["subagents"], item)
            elif name == "Skill":
                _bump(acc["skills"], item)
            elif name.startswith("mcp__"):
                _bump(acc["mcp"], item)
            _bump(acc["res"], res)
            kind = {"Agent": "subagent", "Skill": "skill"}.get(name) or (
                "mcp" if name.startswith("mcp__") else "memory_write" if res == "memory" and perm == "write" else "tool")
            ev = {"t": t, "k": kind, "s": acc["id"], "w": acc["ws"], "a": agent, "r": res, "p": perm,
                  "n": str(item)[:80], "tool": name if not name.startswith("mcp__") else "mcp", "d": detail,
                  "src": "local"}
            if name.startswith("mcp__"):
                ev["mt"] = name.split("__")[-1][:60]
            pending[tid or "%s-%s" % (acc["id"], t)] = ev
