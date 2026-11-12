"""Turn accumulated sessions + events + sources into dashboard/data/*.json."""
import json
import os
import re
import time
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

from classify import CONFIG
from sources import ROUTINES, routine_resources

CT = ZoneInfo(CONFIG.get("timezone", "UTC"))
REPO = CONFIG.get("repo", "cos repo")
RESOURCES = [
    ("github", "GitHub", "GH", "GitHub", "The cos repo and git/gh calls from any workspace."),
    ("skills", "Skills", "SK", "This Mac", "Skills in ~/.claude/skills and cos/skills, called with the Skill tool or a slash command."),
    ("folders", "Folders", "FD", "This Mac", "Files read and written in the workspaces, plus shell work."),
    ("plugins", "Plugins", "PL", "This Mac", "Installed Claude Code plugins and their skills."),
    ("connectors", "Connectors", "CN", "Claude cloud", "MCP connectors: Claude Docs, Claude Design, Netlify and others."),
    ("email", "Email", "EM", "Google + Microsoft", "The mailboxes through tools/mail.py and the Gmail connector."),
    ("internet", "Internet", "WW", "Internet", "Web search, page fetches, Firecrawl and curl."),
    ("calendar", "Calendar", "CL", "Google", "Google Calendar through the connector."),
    ("memory", "Memory", "ME", "This Mac", "The per-project memory folders (the brains) under ~/.claude/projects."),
    ("browser", "Browser & apps", "BR", "This Mac", "Chrome and Mac apps driven by AppleScript, cmux-cua or DevTools."),
    ("agents", "Delegation", "AG", "This Mac", "Spawning subagents, messaging other sessions and remote triggers."),
]
SUB_DESC = {
    "general-purpose": "General subagent COS spawns for research and multi-step work.",
    "Explore": "Read-only search agent for sweeping files.",
    "Plan": "Architect agent that designs implementation plans.",
    "fork": "A copy of the calling session that runs in the background.",
    "claude-code-guide": "Answers questions about Claude Code and the API.",
    "skill-writer": "Turns a described task into a new skill folder.",
}
DAY = 86400
# watcher runs hourly 7am-10pm local time; briefs daily; optimizer Wed; weekly review Sun
EXPECT = {"watcher": 3 * 3600, "brief-8am": 26 * 3600, "brief-1pm": 26 * 3600, "brief-6pm": 26 * 3600,
          "optimizer": 8 * DAY, "weekly-review": 8 * DAY}
CADENCE = {"watcher": "hourly 7am-10pm", "brief-8am": "daily 8am", "brief-1pm": "daily 1pm", "brief-6pm": "daily 6pm",
           "optimizer": "weekly Wed 3am", "weekly-review": "weekly Sun 7pm"}


def _day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _midnight(now):
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def agent_list(catalog, events, subs_seen, listed_agents):
    agents = [{"id": "cos", "name": "COS", "kind": "cos", "where": "This Mac", "model": "",
               "sub": "Chief of staff · every Claude Code session",
               "desc": "Every interactive Claude Code session on this machine, across all workspaces. "
                       "Plans, calls skills and connectors, and spawns the other agents."}]
    types = Counter(e["a"][4:] for e in events if e["a"].startswith("sub:"))
    for name in subs_seen:
        types.setdefault(name, 0)
    for name in catalog["agents"]:
        if name not in ("cos", "registry"):
            types.setdefault(name, 0)
    for name, _ in types.most_common():
        agents.append({"id": "sub:" + name, "name": name, "kind": "subagent", "where": "This Mac", "model": "",
                       "sub": "Subagent",
                       "desc": SUB_DESC.get(name) or catalog["agents"].get(name) or "Subagent type."})
    for rid in catalog["routines"]:
        label, sub = ROUTINES.get(rid, (rid, "Cloud routine"))
        src = "routines/%s.md" % rid
        agents.append({"id": "routine:" + rid, "name": label, "kind": "routine", "where": "Claude cloud", "model": "",
                       "sub": sub, "cadence": CADENCE.get(rid, ""),
                       "desc": "Cloud routine (%s). Prompt in %s. Runs come from log/ lines and its commits; "
                               "its links are what the prompt declares, not observed calls." % (CADENCE.get(rid, ""), src)})
    agents.append({"id": "cloud", "name": "Cloud sessions", "kind": "cloud", "where": "Claude cloud", "model": "",
                   "sub": "claude.ai/code sessions",
                   "desc": "Interactive Claude Code sessions run in the cloud (claude.ai/code or the phone). "
                           "Seen only through the commits they push to the cos repo."})
    return agents


def costs(sessions):
    """Spread cost-state dollars over (model, day, agent) cells by weighted tokens.

    Sessions that share a cost-state startTime are one lineage (a resume or a copy): the
    lineage's highest total is spread once over all its cells. Cost for a model with no
    transcript usage (web-search haiku calls) is spread over all the lineage's cells.
    Sessions with no cost-state use the per-model $/weighted-token rate learned from the rest."""
    lineages = defaultdict(list)
    for s in sessions.values():
        key = ("start", s["cost_start"]) if s.get("cost_start") and s.get("model_cost") else ("sid", s["id"])
        lineages[key].append(s)
    rate_num, rate_den = Counter(), Counter()
    plans = []  # (sessions, model_cost or None)
    for key, group in lineages.items():
        mc = None
        if key[0] == "start":
            best = max(group, key=lambda s: s["cost_state"] or 0)
            mc = best["model_cost"]
            w = Counter()
            for s in group:
                for k, (wt, _) in s["usage"].items():
                    w[k.split("|")[0]] += wt
            for m, c in mc.items():
                if w[m] > 0:
                    rate_num[m] += c
                    rate_den[m] += w[m]
        plans.append((group, mc))
    tot_num, tot_den = sum(rate_num.values()), sum(rate_den.values())
    default_rate = tot_num / tot_den if tot_den else 5e-6
    cells = []  # (sid, model, day, agent, usd, tokens)
    for group, mc in plans:
        allcells = [(s["id"],) + tuple(k.split("|")) + tuple(v) for s in group for k, v in s["usage"].items()]
        if mc is None:
            for sid, m, day, agent, wt, tok in allcells:
                r = rate_num[m] / rate_den[m] if rate_den[m] else default_rate
                cells.append((sid, m, day, agent, wt * r, tok))
            continue
        w = Counter()
        for _, m, _, _, wt, _ in allcells:
            w[m] += wt
        total_w = sum(w.values())
        orphan = sum(c for m, c in mc.items() if w[m] <= 0)
        for sid, m, day, agent, wt, tok in allcells:
            usd = (mc.get(m, 0) * wt / w[m] if w[m] > 0 and m in mc else 0)
            if orphan and total_w:
                usd += orphan * wt / total_w
            cells.append((sid, m, day, agent, usd, tok))
        if not allcells and mc:
            pass  # cost-state with no usable usage lines: nothing to date it by
    return cells


def watcher_missed(runs, now):
    """Hours today (CT, 7am-10pm, already past) with no watcher run."""
    from datetime import datetime
    d = datetime.fromtimestamp(now, CT)
    done = {datetime.fromtimestamp(r["t"], CT).hour for r in runs
            if r["routine"] == "watcher" and datetime.fromtimestamp(r["t"], CT).date() == d.date()}
    last_full = d.hour - 1 if d.minute < 20 else d.hour
    # the watcher skips the brief hours (8am, 1pm, 6pm)
    return [h for h in range(7, min(22, last_full) + 1) if h not in done and h not in (8, 13, 18)]


def _edge(edges, aid, e, windows):
    g = edges.setdefault(aid + ">" + e["r"], {"a": aid, "r": e["r"], "perm": "read", "d1": 0, "d7": 0, "d30": 0,
                                             "w1": 0, "w7": 0, "w30": 0, "items": Counter(), "last": 0, "failed": 0,
                                             "declared": bool(e.get("declared")), "ws": {}})
    wsb = g["ws"].setdefault(e.get("w") or "other", [0, 0, 0, 0, 0, 0])  # d1 d7 d30 w1 w7 w30
    for j, (wk, start) in enumerate(windows.items()):
        if e["t"] >= start:
            g[wk] += 1
            wsb[j] += 1
            if e["p"] == "write":
                g["w" + wk[1:]] += 1
                wsb[j + 3] += 1
    if e["p"] == "write":
        g["perm"] = "write"
    g["items"][e.get("n") or "?"] += 1
    g["last"] = max(g["last"], e["t"])
    if e.get("st") == "failed":
        g["failed"] += 1


def _health(h, e, now, windows):
    if not h or now - e["t"] > 30 * DAY or (e.get("declared") and not e.get("primary")):
        return
    h["last"] = max(h["last"] or 0, e["t"])
    for wk, start in windows.items():
        if e["t"] >= start:
            h["r" + wk[1:]] += 1
            if e.get("st") == "failed":
                h["f" + wk[1:]] += 1
    if e.get("k") == "run":
        h["last_st"] = e["st"]


def build(data_dir, sessions, events, catalog, memory, live, runs, commits, config, inv=None, remote=None):
    now = time.time()
    inv = inv or {}
    today0 = _midnight(now)
    windows = {"d1": today0, "d7": now - 7 * DAY, "d30": now - 30 * DAY}

    known_skills = set(catalog["skills"]) | set((inv.get("skills") or {}).keys())
    events = [e for e in events if not (e.get("slash") and e["n"] not in known_skills)]

    # cloud: one run per log line; a commit by the same routine within 20 min is the same run
    declared = {rid: routine_resources(txt) for rid, txt in catalog["routine_text"].items()}
    run_list = [dict(r) for r in runs]
    for c in commits:
        if c["src"] != "cloud" or not c["routine"]:
            continue
        match = next((r for r in run_list if r["routine"] == c["routine"] and abs(r["t"] - c["t"]) < 1200), None)
        if match:
            match.setdefault("commits", []).append(c["h"])
            c["run_matched"] = True
        else:  # log line missing: the commit is the only receipt
            run_list.append({"t": c["t"], "routine": c["routine"], "d": "commit %s · %s" % (c["h"], c["s"]),
                             "st": "ok", "from_commit": True})
    run_list.sort(key=lambda r: r["t"])
    cloud = []
    for r in run_list:
        res = declared.get(r["routine"]) or {"github": "write"}
        aid = "cloud" if r["routine"] == "cloud" else "routine:" + r["routine"]  # web/phone sessions log their own lines
        for i, (rk, perm) in enumerate(sorted(res.items())):
            cloud.append({"t": r["t"], "k": "run", "s": "", "w": "cos", "a": aid, "r": rk, "p": perm,
                          "n": "declared", "d": r["d"] if i == 0 else "", "st": r["st"], "src": "cloud",
                          "primary": i == 0, "declared": True})
    for c in commits:
        if c["src"] == "cloud" and not c["routine"]:
            cloud.append({"t": c["t"], "k": "commit", "s": c["session"], "w": "cos", "a": "cloud", "r": "github", "p": "write",
                          "n": REPO, "d": "commit %s · %s" % (c["h"], c["s"]), "st": "ok", "src": "cloud",
                          "primary": True})
    allev = sorted(events + cloud, key=lambda e: e["t"])

    subs_seen = set()
    for s in sessions.values():
        subs_seen.update(s["subagents"])
    agents = agent_list(catalog, allev, subs_seen, inv.get("agents") or {})
    aids = {a["id"] for a in agents}
    for e in allev:
        if e["a"] not in aids:
            e["a"] = "cos"

    # every open chat gets its own row under COS; its calls stay counted in COS too
    live_ids = {}
    for sid in live:
        ss = sessions.get(sid)
        if not ss or (not ss["msgs"] and not ss["prompts"]):
            continue
        busy = live[sid].get("status") in ("busy", "running", "working") or now - (ss["last_t"] or 0) < 120
        title = ss["title"] or (ss.get("first_prompt") or "")[:60] or "(untitled)"
        live_ids[sid] = {"id": "live:" + sid, "name": title, "kind": "live", "where": "This Mac", "model": ss["model"] or "",
                         "cadence": "%s · %s" % (ss["ws"], "running" if busy else "waiting on you"), "session": sid,
                         "sub": "Open chat in %s · %s" % (ss["ws"], "running" if busy else "waiting on you"),
                         "desc": "An open Claude Code chat. Its calls are part of COS; this row shows them on their own.",
                         "last_t": ss["last_t"] or 0}
    live_agents = sorted(live_ids.values(), key=lambda a: -a["last_t"])
    agents[1:1] = live_agents
    aids |= {a["id"] for a in live_agents}

    # edges agent x resource, items per resource
    edges = {}
    hourly = defaultdict(lambda: [0] * 24)
    items = {}
    for e in allev:
        if not e.get("r") or now - e["t"] > 30 * DAY:
            continue
        for aid in (e["a"], "live:" + e["s"]) if e["a"] == "cos" and e.get("s") in live_ids else (e["a"],):
            _edge(edges, aid, e, windows)
        if e["t"] >= today0 and not (e.get("declared") and not e.get("primary")):
            h = time.localtime(e["t"]).tm_hour
            hourly[e["a"]][h] += 1
            hourly[e["r"]][h] += 1
        if not e.get("declared"):
            ik = e["r"] + "|" + (e.get("n") or "?")
            it = items.setdefault(ik, {"r": e["r"], "n": e.get("n") or "?", "d1": 0, "d7": 0, "d30": 0, "w30": 0,
                                       "f30": 0, "last": 0, "agents": Counter(), "tools": Counter()})
            for wk, start in windows.items():
                if e["t"] >= start:
                    it[wk] += 1
            it["w30"] += e["p"] == "write"
            it["f30"] += e.get("st") == "failed"
            it["last"] = max(it["last"], e["t"])
            it["agents"][e["a"]] += 1
            if e.get("mt"):
                it["tools"][e["mt"]] += 1
    edge_list = []
    for g in edges.values():
        g["items"] = g["items"].most_common(12)
        edge_list.append(g)

    # per-agent health
    health = {a["id"]: {"last": None, "f1": 0, "f7": 0, "f30": 0, "r1": 0, "r7": 0, "r30": 0, "last_st": None}
              for a in agents}
    for e in allev:
        for aid in (e["a"], "live:" + e["s"]) if e["a"] == "cos" and e.get("s") in live_ids else (e["a"],):
            _health(health.get(aid), e, now, windows)
    from datetime import datetime
    ct_hour = datetime.fromtimestamp(now, CT).hour
    missed = watcher_missed(run_list, now)
    for a in agents:
        h = health[a["id"]]
        if a["kind"] == "routine":
            rid = a["id"].split(":", 1)[1]
            gap = EXPECT.get(rid)
            stale = bool(gap and h["last"] and now - h["last"] > gap)  # never ran yet is not overdue
            if rid == "watcher":
                stale = stale and 8 <= ct_hour < 23  # quiet hours 10pm-7am
                h["missed_today"] = missed
            h["stale"] = stale
        a["health"] = h

    # resource subtitles from the catalog
    mem_files = sum(m["count"] for m in memory)
    mcp_inv = inv.get("mcp") or {}
    sub = {
        "github": REPO, "skills": "%d installed" % len(catalog["skills"]),
        "folders": "%d workspaces" % len(CONFIG.get("workspaces", [])), "plugins": "%d installed" % len(catalog["plugins"]),
        "connectors": "%d live · %d sign-in only" % (
            sum(1 for k, v in mcp_inv.items() if not re.match(r"^(ccd|[0-9a-f]{8}-)", k) and not set(v.get("tools") or ["x"]) <= {"authenticate", "complete_authentication"}),
            sum(1 for v in mcp_inv.values() if v.get("tools") and set(v["tools"]) <= {"authenticate", "complete_authentication"})),
        "email": "%d mailboxes" % len(catalog["mailboxes"]), "internet": "Search + fetch", "calendar": "Google",
        "memory": "%d brains · %d files" % (len(memory), mem_files), "browser": "Chrome, cmux-cua",
        "agents": "Subagents, messages",
    }
    resources = [{"id": rid, "name": n, "mono": mono, "where": where, "desc": d, "sub": sub.get(rid, "")}
                 for rid, n, mono, where, d in RESOURCES]

    # costs
    cells = costs(sessions)
    by_day, by_agent_day, by_agent_month, by_model, sess_cost, sess_today = (Counter() for _ in range(6))
    by_ws_day = Counter()
    month = time.strftime("%Y-%m", time.localtime(now))
    lt = time.localtime(now)
    last_month = "%04d-%02d" % ((lt.tm_year, lt.tm_mon - 1) if lt.tm_mon > 1 else (lt.tm_year - 1, 12))
    tokens_day = Counter()
    today = _day(now)
    for sid, m, day, agent, usd, tok in cells:
        by_day[day] += usd
        tokens_day[day] += tok
        sess_cost[sid] += usd
        if agent not in aids:
            agent = "cos"
        if day == today:
            by_agent_day[agent] += usd
            sess_today[sid] += usd
            by_ws_day[sessions[sid]["ws"]] += usd
        if day.startswith(month):
            by_agent_month[agent] += usd
            by_model[m] += usd
    month_cost = sum(v for d, v in by_day.items() if d.startswith(month))
    last_month_cost = sum(v for d, v in by_day.items() if d.startswith(last_month))
    estimated_today = sum(sess_today[s["id"]] for s in sessions.values() if not s.get("model_cost"))

    # sessions
    remote_to_sid = {s["remote"]: s["id"] for s in sessions.values() if s.get("remote")}
    commits_by_sid = defaultdict(list)
    for c in commits:
        sid = remote_to_sid.get(c.get("session"))
        if sid:
            c["local_session"] = sid
            commits_by_sid[sid].append({"h": c["h"], "s": c["s"], "t": c["t"]})
    sess_out = []
    for s in sessions.values():
        if not s["last_t"] or now - s["last_t"] > 30 * DAY or (not s["msgs"] and not s["prompts"]):
            continue
        lv = live.get(s["id"])
        if lv:
            status = "running" if lv["status"] in ("busy", "running", "working") or now - s["last_t"] < 120 else "waiting"
        else:
            status = "idle" if now - s["last_t"] < 6 * 3600 else "ended"
        ctx = []
        for name, n in Counter(s["skills"]).most_common(2):
            ctx.append(["skill", name])
        if s["subagents"]:
            n = sum(s["subagents"].values())
            ctx.append(["agents", "%d %s" % (n, "subagents" if n > 1 else "subagent")])
        for name, n in Counter(s["mcp"]).most_common(2):
            ctx.append(["connector", name])
        if not ctx:
            for rk, n in Counter(s["res"]).most_common(2):
                ctx.append([rk, rk])
        cost_state = s["cost_state"]
        sess_out.append({"id": s["id"], "ws": s["ws"], "title": s["title"] or s["first_prompt"][:60] or "(untitled)",
                         "status": status, "started": s["started"], "last_t": s["last_t"], "prompts": s["prompts"],
                         "msgs": s["msgs"], "tokens": s["tokens"], "ctx_tokens": s["ctx"], "model": s["model"],
                         "cost": round(cost_state if cost_state else sess_cost[s["id"]], 4),
                         "cost_today": round(sess_today[s["id"]], 4), "cost_estimated": not cost_state,
                         "last": s["last"], "ctx": ctx, "skills": s["skills"], "subagents": s["subagents"],
                         "mcp": s["mcp"], "res": s["res"], "live": bool(lv), "compacts": s["compacts"],
                         "entry": s["entry"], "resume": "claude --resume " + s["id"],
                         "commits": commits_by_sid.get(s["id"], [])[:10]})
    sess_out.sort(key=lambda x: -x["last_t"])

    # recent runs: last 300 events with a resource (cloud runs only once)
    runs_out = []
    for e in reversed(allev):
        if not e.get("r") or e.get("primary") is False:
            continue
        runs_out.append({k: e.get(k) for k in ("t", "k", "a", "r", "p", "n", "d", "st", "dur", "s", "w", "src", "declared")})
        if len(runs_out) >= 300:
            break
    hour_ago = now - 3600
    runs_last_hour = sum(1 for e in allev if e["t"] >= hour_ago and e.get("r") and e.get("primary") is not False)

    # inventory: every installed thing with its use
    inventory = build_inventory(catalog, inv, items, memory, agents, health, now)

    # health signals
    signals = build_health(agents, run_list, inv, remote, catalog, memory, now, missed)

    days_list = sorted(by_day)
    stats = {
        "generated_at": now, "today": today, "month": month, "source": config.get("source", "mac"),
        "cost_today": round(by_day.get(today, 0), 2), "cost_today_estimated": round(estimated_today, 2),
        "cost_month": round(month_cost, 2), "cost_last_month": round(last_month_cost, 2),
        "by_day": [{"day": d, "usd": round(by_day[d], 2), "tokens": tokens_day[d]} for d in days_list if d >= _day(now - 60 * DAY)],
        "by_agent_day": {k: round(v, 3) for k, v in by_agent_day.items()},
        "by_agent_month": {k: round(v, 2) for k, v in by_agent_month.items()},
        "by_model_month": {k: round(v, 2) for k, v in by_model.most_common()},
        "by_ws_day": {k: round(v, 2) for k, v in by_ws_day.most_common()},
        "live_sessions": len(live), "running": sum(1 for s in sess_out if s["status"] == "running"),
        "open": sum(1 for s in sess_out if s["status"] == "waiting"),
        "sessions_30d": len(sess_out), "events_total": len(allev), "runs_last_hour": runs_last_hour,
        "cloud_runs_7d": sum(1 for r in run_list if now - r["t"] < 7 * DAY),
        "plan": config.get("plan", {}),
    }
    graph = {"generated_at": now, "agents": agents, "resources": resources, "edges": edge_list,
             "hourly": dict(hourly), "runs": runs_out, "workspaces": sorted({s["ws"] for s in sess_out})}
    github = {"generated_at": now, "commits": commits[:200], "remote": remote,
              "last_watcher": max((r["t"] for r in run_list if r["routine"] == "watcher"), default=None)}
    cat_out = {k: v for k, v in catalog.items() if k != "routine_text"}
    cat_out["routine_resources"] = declared

    def write(name, obj):
        p = os.path.join(data_dir, name)
        with open(p + ".tmp", "w") as fh:
            json.dump(obj, fh, separators=(",", ":"), default=str)
        os.replace(p + ".tmp", p)

    write("graph.json", graph)
    write("sessions.json", {"generated_at": now, "sessions": sess_out})
    write("stats.json", stats)
    write("memory.json", {"generated_at": now, "stores": memory})
    write("github.json", github)
    write("catalog.json", cat_out)
    write("inventory.json", {"generated_at": now, "groups": inventory})
    write("health.json", {"generated_at": now, "signals": signals})
    return stats


def _item_row(name, kind, source, it, extra=None):
    row = {"name": name, "kind": kind, "source": source,
           "d1": it["d1"] if it else 0, "d7": it["d7"] if it else 0, "d30": it["d30"] if it else 0,
           "writes": it["w30"] if it else 0, "failed": it["f30"] if it else 0, "last": it["last"] if it else None,
           "agents": dict(it["agents"].most_common(4)) if it else {}}
    if extra:
        row.update(extra)
    return row


def find_any(items, name):
    for k, v in items.items():
        if v["n"] == name:
            return v
    return None


def build_inventory(catalog, inv, items, memory, agents, health, now):
    def find(r, *names):
        for n in names:
            if r + "|" + n in items:
                return items[r + "|" + n]
        return None

    groups = []
    # skills: installed (folders) + listed to sessions (bundled and plugin skills)
    listed = inv.get("skills") or {}
    names = sorted(set(catalog["skills"]) | {n for n in listed if ":" not in n})
    rows = []
    for n in names:
        src = "~/.claude/skills or cos/skills" if n in catalog["skills"] else "built in / bundled"
        rows.append(_item_row(n, "skill", src, find("skills", n), {"listed": listed.get(n)}))
    groups.append({"id": "skills", "title": "Skills", "rows": rows})
    prow = []
    for n in sorted(n for n in listed if ":" in n):
        prow.append(_item_row(n, "plugin skill", n.split(":")[0], find("plugins", n), {"listed": listed.get(n)}))
    groups.append({"id": "plugin-skills", "title": "Plugin skills", "rows": prow,
                   "note": "Installed plugins on this Mac: " + (", ".join(catalog["plugins"]) or "none")})
    # agents
    arows = []
    for a in agents:
        h = a.get("health") or {}
        arows.append({"name": a["name"], "kind": a["kind"], "source": a["where"], "d1": h.get("r1", 0), "d7": h.get("r7", 0),
                      "d30": h.get("r30", 0), "failed": h.get("f30", 0), "last": h.get("last"),
                      "cadence": a.get("cadence", ""), "id": a["id"]})
    groups.append({"id": "agents", "title": "Agents and routines", "rows": arows})
    # connectors: MCP servers seen loading in sessions, with tool counts and failures
    from classify import mcp_item, mcp_server
    crow = []
    failed = inv.get("mcp_failed") or {}
    mcp = inv.get("mcp") or {}
    internal = re.compile(r"^(ccd|[0-9a-f]{8}-[0-9a-f]{4})")
    for server, rec in sorted(mcp.items()):
        if internal.match(server):
            continue  # Claude desktop app internals, not connectors
        short, _ = mcp_server("mcp__%s__x" % server)
        name = mcp_item(short)
        tools = rec.get("tools", [])
        auth_only = bool(tools) and set(tools) <= {"authenticate", "complete_authentication"}
        it = None if auth_only else find_any(items, name)
        pretty = name if not server.startswith("plugin_") else "%s (plugin %s)" % (name, server.split("_")[1])
        crow.append(_item_row(pretty, "mcp", server, it,
                              {"tools": len(tools), "status": "needs sign-in" if auth_only else "connected",
                               "last_listed": rec.get("listed")}))
    for name, f in sorted(failed.items()):
        listed_ok = any(name.split(":")[-1] in s for s in mcp)
        if not listed_ok or f["t"] > max((mcp.get(s, {}).get("listed", 0) for s in mcp if name.split(":")[-1] in s), default=0):
            crow.append({"name": name, "kind": "mcp", "source": "failed to connect", "status": "failing",
                         "error": f["err"], "last": f["t"], "d1": 0, "d7": 0, "d30": 0, "writes": 0, "failed": 0, "agents": {}})
    for n in catalog["mcp_config"]:
        if not any(n in s for s in mcp):
            crow.append({"name": n, "kind": "mcp", "source": "~/.claude.json", "status": "configured, not seen loading",
                         "d1": 0, "d7": 0, "d30": 0, "writes": 0, "failed": 0, "agents": {}, "last": None})
    groups.append({"id": "connectors", "title": "Connectors (MCP)", "rows": crow})
    # mailboxes
    mrows = []
    for mb in catalog["mailboxes"]:
        mrows.append(_item_row(mb, "mailbox", "tools/mail.py", find("email", mb)))
    gm = find("email", "Gmail connector")
    if gm:
        mrows.append(_item_row("Gmail connector", "mcp", "claude.ai connector", gm))
    groups.append({"id": "mailboxes", "title": "Mailboxes", "rows": mrows})
    # hooks, launchd, n8n
    groups.append({"id": "hooks", "title": "Hooks", "rows": [
        {"name": h["command"] or "?", "kind": "hook", "source": "%s %s" % (h["event"], h["matcher"]), "status": "active",
         "d1": 0, "d7": 0, "d30": 0, "last": None} for h in catalog["hooks"]]})
    groups.append({"id": "launchd", "title": "Scheduled jobs on this Mac", "rows": [
        {"name": j["label"], "kind": "launchd", "source": "~/Library/LaunchAgents",
         "status": j["state"] + (" · last exit " + j["last_exit"] if j["last_exit"] else ""), "last": None,
         "d1": 0, "d7": 0, "d30": 0} for j in catalog["launchd"]]})
    groups.append({"id": "n8n", "title": "n8n workflows", "rows": [
        {"name": w["name"], "kind": "n8n", "source": "tools/n8n/" + w["file"], "status": "%d nodes · not deployed here" % w["nodes"],
         "last": None, "d1": 0, "d7": 0, "d30": 0} for w in catalog["n8n"]]})
    # memory stores
    groups.append({"id": "memory", "title": "Memory (brains)", "rows": [
        _item_row(m["ws"] + " · " + re.sub(r"^-(Users|home)-[^-]+-", "~/", m["slug"]).replace("-", "/"), "memory", "%d files%s" % (
            m["count"], ", %d not in MEMORY.md" % m["unindexed"] if m["unindexed"] else ""),
            find("memory", m["ws"]), {"last_write": m["last"]}) for m in memory]})
    return groups


def build_health(agents, run_list, inv, remote, catalog, memory, now, missed):
    sig = []

    def add(level, area, text, ref=None):
        sig.append({"level": level, "area": area, "text": text, "ref": ref})

    for a in agents:
        h = a.get("health") or {}
        if a["kind"] == "routine":
            rid = a["id"].split(":", 1)[1]
            if h.get("stale"):
                add("bad", "routine", "%s is overdue: last run %s" % (a["name"], _ago(h.get("last"), now)), a["id"])
            if h.get("last_st") == "failed":
                add("bad", "routine", "%s: last run logged FAILED" % a["name"], a["id"])
            if rid == "watcher" and missed:
                add("warn", "routine", "Watcher missed %d hourly pass%s today (%s)" % (
                    len(missed), "" if len(missed) == 1 else "es", ", ".join("%d:00" % m for m in missed)), a["id"])
        elif h.get("r1", 0) >= 8 and h.get("f1", 0) / max(1, h.get("r1", 1)) > 0.25:
            add("warn", "agent", "%s: %d of %d calls failed today" % (a["name"], h["f1"], h["r1"]), a["id"])
    for r in run_list:
        if now - r["t"] < DAY and re.search(r"FAILED:\s*(?!none)\S", r["d"], re.I):
            add("bad", "mail", "Log %s: %s" % (time.strftime("%H:%M", time.localtime(r["t"])), r["d"][:120]), "routine:" + r["routine"])
    mcp = inv.get("mcp") or {}
    for name, f in (inv.get("mcp_failed") or {}).items():
        base = name.split(":")[-1]
        ok_after = max((rec.get("listed", 0) for s, rec in mcp.items() if base in s), default=0)
        if f["t"] >= ok_after and now - f["t"] < 7 * DAY:
            add("bad", "connector", "%s failed to connect (%s) %s" % (name, f["err"][:80], _ago(f["t"], now)), "connectors")
    auth = [s for s, rec in mcp.items() if rec.get("tools") and set(rec["tools"]) <= {"authenticate", "complete_authentication"}]
    if auth:
        add("info", "connector", "%d plugin connectors offer only sign-in tools (not connected)" % len(auth), "connectors")
    if remote:
        for p in remote.get("pulls", []):
            if p["state"] == "open":
                age = (now - _iso(p["created"])) / DAY if p.get("created") else 0
                add("warn" if age > 7 else "info", "github", "PR #%d open %d days: %s" % (p["n"], age, p["title"]), "github")
    for j in catalog.get("launchd", []):
        if j["label"].endswith("cos-dashboard") and j["state"] == "running":
            pass
        elif j["last_exit"] not in ("", "0", "(never") and not j["last_exit"].startswith("(never"):
            add("warn", "mac", "%s last exit %s" % (j["label"], j["last_exit"]), None)
    unindexed = sum(m["unindexed"] for m in memory)
    if unindexed:
        add("info", "memory", "%d memory files are not listed in their MEMORY.md index" % unindexed, "memory")
    order = {"bad": 0, "warn": 1, "info": 2}
    sig.sort(key=lambda s: order[s["level"]])
    return sig


def _iso(s):
    from datetime import datetime
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0


def _ago(t, now):
    if not t:
        return "never"
    m = (now - t) / 60
    return "%d min ago" % m if m < 60 else "%.0f h ago" % (m / 60) if m < 1440 else "%.0f d ago" % (m / 1440)


# ---------- public export ----------
PUBLIC_GRAPH_AGENT = ("id", "name", "kind", "where", "sub", "cadence", "health")
PUBLIC_RUN = ("t", "k", "a", "r", "p", "st", "dur", "src")


def public_export(data_dir, out_dir):
    """Allow-list copy for publishing: counts, timings, resources, statuses. No titles, prompts,
    paths, session ids, mailbox addresses or commit subjects."""
    g = json.load(open(os.path.join(data_dir, "graph.json")))
    st = json.load(open(os.path.join(data_dir, "stats.json")))
    sess = json.load(open(os.path.join(data_dir, "sessions.json")))["sessions"]
    pub_g = {
        "generated_at": g["generated_at"],
        "agents": [{k: a.get(k) for k in PUBLIC_GRAPH_AGENT} | {"desc": ""} for a in g["agents"] if a["kind"] != "live"],
        "resources": [{k: r[k] for k in ("id", "name", "mono", "where")} | {"desc": "", "sub": "" if r["id"] == "github" else r["sub"]}
                      for r in g["resources"]],
        "edges": [{k: e[k] for k in ("a", "r", "perm", "d1", "d7", "d30", "w1", "w7", "w30", "failed", "last", "declared")}
                  | {"items": []} for e in g["edges"] if not e["a"].startswith("live:")],
        "hourly": {k: v for k, v in g["hourly"].items() if not k.startswith("live:")},
        "workspaces": [],
        "runs": [{k: r.get(k) for k in PUBLIC_RUN} | {"d": "", "n": ""} for r in g["runs"]],
    }
    pub_s = [{"id": "s%d" % i, "ws": "", "title": "Session", "status": s["status"], "started": s["started"],
              "last_t": s["last_t"], "prompts": s["prompts"], "msgs": s["msgs"], "tokens": s["tokens"],
              "ctx_tokens": s["ctx_tokens"], "model": s["model"], "cost": s["cost"], "cost_today": s["cost_today"],
              "last": "", "ctx": [], "skills": {}, "subagents": {}, "mcp": {}, "res": s["res"], "resume": "",
              "commits": [], "compacts": s["compacts"]} for i, s in enumerate(sess)]
    pub_st = {k: v for k, v in st.items() if k != "plan"}
    pub_st["plan"] = {"name": st.get("plan", {}).get("name", "")}
    os.makedirs(out_dir, exist_ok=True)
    for name, obj in (("graph.json", pub_g), ("stats.json", pub_st), ("sessions.json", {"sessions": pub_s}),
                      ("health.json", {"signals": []}), ("inventory.json", {"groups": []}), ("github.json", {"commits": []}),
                      ("vault.json", {"notes": []}), ("registry.json", [])):
        with open(os.path.join(out_dir, name), "w") as fh:
            json.dump(obj, fh, separators=(",", ":"))
    leaks = leak_check(out_dir)
    if leaks:
        raise SystemExit("public export blocked, possible personal data: " + "; ".join(leaks[:5]))
    return out_dir


def leak_check(out_dir):
    terms = "".join("|" + re.escape(t) for t in CONFIG.get("private_terms", []) if t)
    bad = re.compile(r"(/Users/|/home/|@[\w-]+\.\w|session_0|claude --resume|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}" + terms + ")")
    # credentials too
    bad = re.compile(bad.pattern[:-1] + r"|sk-ant-|sk-[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|gh[pousr]_\w{20}|github_pat_|AIza[\w-]{30}|GOCSPX-|xox[baprs]-|eyJ[\w-]{10,}\.eyJ|PRIVATE KEY|refresh_token\W+\w{10})")
    leaks = []
    for n in os.listdir(out_dir):
        if n.endswith(".json"):
            txt = open(os.path.join(out_dir, n)).read()
            for m in bad.finditer(txt):
                leaks.append("%s: %s" % (n, txt[max(0, m.start() - 30):m.end() + 30]))
    return leaks
