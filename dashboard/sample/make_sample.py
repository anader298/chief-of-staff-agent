#!/usr/bin/env python3
"""Build a SYNTHETIC data set for the dashboard by running the real collector on made-up input.

  python3 -I dashboard/sample/make_sample.py [--out dashboard/data] [--seed 7]

Writes fake Claude Code transcripts into a temp folder, reads them with collect/transcripts.Reader,
invents a week of routine log lines and commits, and calls collect/build.build() exactly as a real
pass does. Every session title, prompt, workspace and count is invented. Nothing is read from
~/.claude or from any mailbox.

Then serve it without the collector overwriting it:
  COS_DASH_NO_COLLECT=1 python3 -I dashboard/serve.py   ->  http://127.0.0.1:8765/
"""
import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

os.environ["TZ"] = "America/New_York"  # sample runs in one fixed zone so the watcher's hours line up
time.tzset()

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.dirname(HERE)
REPO = os.path.dirname(DASH)
sys.path.insert(0, os.path.join(DASH, "collect"))

import classify  # noqa: E402

SAMPLE_HOME = "/home/sample"
classify.WORKSPACES = [(SAMPLE_HOME + "/cos", "cos"), (SAMPLE_HOME + "/work", "work"),
                       (SAMPLE_HOME + "/racing", "racing"), (SAMPLE_HOME + "/personal", "personal")]
classify.CONFIG.update({"timezone": "America/New_York", "repo": "example-user/cos", "workspaces": [[p, l] for p, l in classify.WORKSPACES]})

import build  # noqa: E402
import transcripts  # noqa: E402

DAY = 86400
MODELS = ["claude-opus-5-5", "claude-sonnet-5", "claude-haiku-5"]

# (workspace, title, tool calls). Every title is invented.
SESSIONS = [
    ("cos", "Tune the watcher's urgency rules", ["Read:cos/config/urgency.md", "Skill:skill-feedback", "Edit:cos/config/urgency.md",
                                                  "Bash:git commit -m urgency", "Bash:git push origin main"]),
    ("cos", "Draft replies for the morning brief", ["Bash:python3 tools/mail.py inbox --all --hours 12",
                                                     "Write:cos/outbox/d/reply-a.md", "Write:cos/outbox/d/reply-b.md",
                                                     "Bash:python3 tools/mail.py draft --account C-work",
                                                     "mcp__claude_ai_Gmail__create_draft", "mcp__claude_ai_Google_Calendar__list_events"]),
    ("work", "Comparable deals research for a memo", ["Agent:Explore", "Agent:general-purpose", "WebSearch", "WebFetch:https://example.org/a",
                                                       "WebFetch:https://example.org/b", "Read:work/memo.md", "Write:work/memo.md"]),
    ("work", "Rebuild the cash-flow model tabs", ["Read:work/model.py", "Edit:work/model.py", "Bash:python3 work/model.py",
                                                   "Bash:python3 work/model.py", "Write:work/out.csv"]),
    ("racing", "Event logistics checklist", ["Read:racing/plan.md", "Edit:racing/plan.md", "mcp__claude_ai_Google_Calendar__create_event",
                                              "WebSearch"]),
    ("racing", "Sponsor deck numbers check", ["Read:racing/deck.md", "Agent:general-purpose", "Edit:racing/deck.md"]),
    ("personal", "Insurance renewal comparison", ["WebSearch", "WebFetch:https://example.org/plans", "Write:personal/compare.md"]),
    ("cos", "Add a preflight check for wrapped email", ["Read:cos/tools/preflight.py", "Edit:cos/tools/preflight.py",
                                                        "Bash:python3 tools/preflight.py email /tmp/body.txt", "Bash:git push origin main"]),
    ("cos", "Weekly review follow-ups", ["Read:cos/briefs/w/weekly.md", "Agent:Plan", "Skill:skill-feedback", "Edit:cos/agents/cos.md"]),
    ("work", "Data room index", ["Bash:ls work/dataroom", "Read:work/index.md", "Write:work/index.md", "Agent:Explore"]),
]


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def tool_block(spec, n):
    name, _, arg = spec.partition(":")
    if name in ("Read", "Write", "Edit"):
        inp = {"file_path": SAMPLE_HOME + "/" + arg}
    elif name == "Bash":
        inp = {"command": arg, "description": arg.split()[0]}
    elif name == "Skill":
        inp = {"skill": arg}
    elif name == "Agent":
        inp = {"subagent_type": arg, "description": "sample task"}
    elif name == "WebFetch":
        inp = {"url": arg}
    else:
        inp = {}
    return {"type": "tool_use", "id": "tool%d" % n, "name": name, "input": inp}


def write_transcripts(root, rng, now):
    n = 0
    for i, (ws, title, calls) in enumerate(SESSIONS):
        cwd = SAMPLE_HOME + "/" + ws
        slug = cwd.replace("/", "-")
        os.makedirs(os.path.join(root, slug), exist_ok=True)
        sid = "sample-%02d" % i
        # six sessions today (one still running), the rest over the last 6 days
        today0 = build._midnight(now)
        if i == 0:
            start = now - 1500
        elif i < 6:
            start = max(today0 + 300, now - rng.uniform(0.05, 0.5) * DAY)
        else:
            start = now - rng.uniform(1, 6) * DAY
        t = start
        model = MODELS[0] if i % 3 else MODELS[1]
        lines = [{"type": "user", "uuid": "u%d" % n, "timestamp": iso(t), "origin": {"kind": "human"},
                  "message": {"role": "user", "content": title}, "cwd": cwd},
                 {"type": "ai-title", "aiTitle": title}]
        for rep in range(rng.randint(2, 5)):
            for spec in calls:
                n += 1
                t += rng.uniform(5, 90)
                u = {"input_tokens": rng.randint(5, 50), "output_tokens": rng.randint(80, 900),
                     "cache_read_input_tokens": rng.randint(20000, 160000), "cache_creation_input_tokens": rng.randint(0, 4000)}
                lines.append({"type": "assistant", "uuid": "a%d" % n, "timestamp": iso(t), "cwd": cwd,
                              "message": {"id": "m%d" % n, "model": model, "role": "assistant", "usage": u,
                                          "content": [{"type": "text", "text": "Working on: " + title}, tool_block(spec, n)]}})
                t += rng.uniform(1, 20)
                lines.append({"type": "user", "uuid": "r%d" % n, "timestamp": iso(t), "toolUseResult": {},
                              "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool%d" % n,
                                                                       "is_error": rng.random() < 0.04}]}})
            if rep:
                lines.append({"type": "user", "uuid": "p%d-%d" % (i, rep), "timestamp": iso(t), "origin": {"kind": "human"},
                              "message": {"role": "user", "content": "next step"}, "cwd": cwd})
        lines.append({"type": "cost-state", "totalCostUSD": round(rng.uniform(0.4, 9), 2), "startTime": int(start * 1000),
                      "modelUsage": {model: {"costUSD": round(rng.uniform(0.4, 9), 2)}}})
        subs = [c.split(":", 1)[1] for c in calls if c.startswith("Agent:")]
        for k, atype in enumerate(subs):
            sdir = os.path.join(root, slug, sid, "subagents")
            os.makedirs(sdir, exist_ok=True)
            st, sub_lines = start + 120 * (k + 1), []
            for spec in ("WebSearch", "WebFetch:https://example.org/s", "Read:%s/notes.md" % ws, "Bash:grep -rn total %s" % ws) * 3:
                n += 1
                st += rng.uniform(3, 40)
                u = {"input_tokens": 9, "output_tokens": rng.randint(60, 600), "cache_read_input_tokens": rng.randint(8000, 60000),
                     "cache_creation_input_tokens": rng.randint(0, 3000)}
                sub_lines.append({"type": "assistant", "uuid": "sa%d" % n, "timestamp": iso(st), "message": {
                    "id": "sm%d" % n, "model": MODELS[2] if atype == "Explore" else model, "role": "assistant", "usage": u,
                    "content": [tool_block(spec, n)]}})
                sub_lines.append({"type": "user", "uuid": "sr%d" % n, "timestamp": iso(st + 2), "toolUseResult": {},
                                  "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool%d" % n}]}})
            with open(os.path.join(sdir, "agent-%d.jsonl" % k), "w") as fh:
                fh.writelines(json.dumps(x) + "\n" for x in sub_lines)
            with open(os.path.join(sdir, "agent-%d.meta.json" % k), "w") as fh:
                json.dump({"agentType": atype}, fh)
        path = os.path.join(root, slug, sid + ".jsonl")
        with open(path, "w") as fh:
            fh.writelines(json.dumps(x) + "\n" for x in lines)
        os.utime(path, (t, t))
    return n


def routine_runs(rng, now):
    """A week of cloud routine runs in the log's shape. Mostly silent watcher passes."""
    runs, midnight = [], build._midnight(now)
    for d in range(7, -1, -1):
        day0 = midnight - d * DAY
        for h in range(7, 23):
            t = day0 + h * 3600 + rng.randint(300, 700)
            if t > now:
                break
            if h in (8, 13, 18):
                slot = {8: "brief-8am", 13: "brief-1pm", 18: "brief-6pm"}[h]
                runs.append({"t": t, "routine": slot, "d": "4 mailboxes read, FAILED: none; emailed brief to owner only", "st": "ok"})
            else:
                alert = rng.random() < 0.06
                runs.append({"t": t, "routine": "watcher", "st": "ok",
                             "d": "alert: rule 2 calendar change; emailed owner only" if alert
                             else "quiet, %d new, FAILED: none, held for next brief" % rng.randint(0, 12)})
    runs.append({"t": midnight - 4 * DAY + 3 * 3600, "routine": "optimizer", "d": "proposed 1 change on optimizer/ branch", "st": "ok"})
    runs.append({"t": midnight - 2 * DAY + 19 * 3600, "routine": "weekly-review", "d": "3 lessons proposed on review/ branch", "st": "ok"})
    return [r for r in runs if r["t"] <= now]


def catalog():
    rdir = os.path.join(REPO, "routines")
    text = {n[:-3]: open(os.path.join(rdir, n)).read() for n in sorted(os.listdir(rdir)) if n.endswith(".md")}
    return {"skills": ["skill-feedback"], "agents": {"skill-writer": "Turns a task into a skill folder."},
            "plugins": [], "mcp_config": [], "routines": sorted(text), "routine_text": text, "n8n": [],
            "hooks": [{"event": "PreToolUse", "matcher": "Bash", "command": "block_send.sh"},
                      {"event": "SessionStart", "matcher": "", "command": "sync_repos.sh"},
                      {"event": "Stop", "matcher": "", "command": "refresh.sh"}],
            "launchd": [], "mailboxes": ["A-personal", "B-personal2", "C-work", "D-racing"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(DASH, "data"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    now = time.time()
    tmp = tempfile.mkdtemp(prefix="cos-sample-")
    try:
        write_transcripts(tmp, rng, now)
        transcripts.PROJECTS = tmp
        state, sessions, seen = {}, {}, {"lines": set(), "msgs": {}}
        r = transcripts.Reader(state, sessions, seen)
        r.run(30)
        events = sorted(r.events, key=lambda e: e["t"])
        live = {"sample-00": {"pid": 1, "status": "busy", "updated": now, "kind": "interactive", "cwd": SAMPLE_HOME + "/cos"}}
        commits = [{"h": "%08x" % rng.getrandbits(32), "author": "Claude", "t": int(rr["t"]) + 60, "s": "brief " + rr["routine"][6:],
                    "src": "cloud", "routine": rr["routine"], "session": "", "refs": ""}
                   for rr in routine_runs(rng, now) if rr["routine"].startswith("brief")][-12:]
        remote = {"repo": "example-user/cos", "private": True, "size_kb": 2048, "pushed_at": iso(now - 900),
                  "default_branch": "main", "branches": ["main", "review/sample", "optimizer/sample"],
                  "pulls": [{"n": 3, "title": "Weekly review: 3 proposed lessons", "state": "open", "merged": False,
                             "branch": "review/sample", "created": iso(now - 2 * DAY), "updated": iso(now - 2 * DAY),
                             "url": "https://github.com/example-user/cos/pull/3"},
                            {"n": 2, "title": "Optimizer: move the watcher to a smaller model", "state": "closed", "merged": True,
                             "branch": "optimizer/sample", "created": iso(now - 5 * DAY), "updated": iso(now - 4 * DAY),
                             "url": "https://github.com/example-user/cos/pull/2"}]}
        cfg = {"plan": {"name": "Sample data", "note": "Synthetic numbers from dashboard/sample/make_sample.py."}}
        os.makedirs(a.out, exist_ok=True)
        stats = build.build(a.out, sessions, events, catalog(), [], live, routine_runs(rng, now), commits, cfg,
                            inv=state.get("inv"), remote=remote)
        print("sample written to %s: %d sessions, %d events, %d routine runs in 7 days" % (
            a.out, stats["sessions_30d"], stats["events_total"], stats["cloud_runs_7d"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
