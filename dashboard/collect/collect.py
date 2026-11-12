#!/usr/bin/env python3
"""CoS dashboard collector. Stdlib only. Reads ~/.claude transcripts, the cos log and git.

  collect.py run [--max-age-days N]   one pass, writes dashboard/data/*.json
  collect.py --watch N                pass every N seconds
  collect.py reset                    forget offsets and accumulators
  collect.py public [--out DIR]       allow-listed copy of data/ for publishing (default dashboard/dist/data)
"""
import argparse
import fcntl
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build  # noqa: E402
import sources  # noqa: E402
import vault  # noqa: E402
from transcripts import Reader  # noqa: E402

DASH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(DASH, "data")
STATE = os.path.join(DATA, ".state.json")
ACC = os.path.join(DATA, ".sessions-acc.json")
SEEN = os.path.join(DATA, ".seen.json")
LOCK = os.path.join(DATA, ".lock")
EVENTS = os.path.join(DATA, "events.jsonl")
CONFIG = os.path.join(DASH, "config.json") if os.path.exists(os.path.join(DASH, "config.json")) else os.path.join(DASH, "config.example.json")
MAX_EVENTS = 60000


def _load(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _dump(path, obj):
    with open(path + ".tmp", "w") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(path + ".tmp", path)


def read_events():
    out = []
    try:
        with open(EVENTS) as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def run_once(max_age_days):
    t0 = time.time()
    os.makedirs(DATA, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another collector pass is running; skipped", flush=True)
        return
    state = _load(STATE, {})
    sessions = _load(ACC, {})
    raw = _load(SEEN, {})
    seen = {"lines": set(raw.get("lines", [])), "msgs": raw.get("msgs", {})}
    reader = Reader(state, sessions, seen)
    reader.run(max_age_days)
    events = read_events() + sorted(reader.events, key=lambda e: e["t"])
    if len(events) > MAX_EVENTS:
        events = events[-MAX_EVENTS:]
        with open(EVENTS + ".tmp", "w") as fh:
            fh.writelines(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
        os.replace(EVENTS + ".tmp", EVENTS)
    elif reader.events:
        with open(EVENTS, "a") as fh:
            fh.writelines(json.dumps(e, separators=(",", ":")) + "\n" for e in sorted(reader.events, key=lambda e: e["t"]))
    _dump(ACC, sessions)
    _dump(STATE, state)
    _dump(SEEN, {"lines": sorted(seen["lines"]), "msgs": seen["msgs"]})
    if state.get("last_fetch", 0) < time.time() - 240:
        sources.git_fetch()
        state["last_fetch"] = time.time()
        _dump(STATE, state)
    stats = build.build(DATA, sessions, events, sources.catalog(), sources.memory_stores(), sources.live_sessions(),
                        sources.cos_log(), sources.git_commits(), _load(CONFIG, {}), inv=state.get("inv"),
                        remote=sources.gh_remote())
    _extras(DATA)
    print("%s pass %.1fs: +%d events, %d sessions, today $%.2f, month $%.2f" % (
        time.strftime("%H:%M:%S"), time.time() - t0, len(reader.events), stats["sessions_30d"],
        stats["cost_today"], stats["cost_month"]), flush=True)


def _extras(out):
    """vault.json and registry.json next to the built files."""
    vault.export(os.environ.get("VAULT_DIR") or _load(CONFIG, {}).get("vault", os.path.expanduser("~/vault")),
                 os.path.join(out, "vault.json"))
    reg = os.path.join(DASH, "..", "registry", "registry.json")
    if os.path.exists(reg):
        shutil.copyfile(reg, os.path.join(out, "registry.json"))


def run_cloud(out):
    """The GitHub half only: log, commits, PRs, routines, registry, vault. Runs anywhere the repo is checked out."""
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    cfg = _load(CONFIG, {})
    cfg["source"] = "cloud"
    stats = build.build(out, {}, [], sources.catalog(), [], {}, sources.cos_log(), sources.git_commits(), cfg,
                        inv=None, remote=sources.gh_remote())
    _extras(out)
    print("%s cloud pass %.1fs: %d runs in graph, %d files -> %s" % (
        time.strftime("%H:%M:%S"), time.time() - t0, stats.get("runs_last_hour", 0), len(os.listdir(out)), out), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "reset", "public", "cloud"])
    ap.add_argument("--out", default=os.path.join(DASH, "dist", "data"))
    ap.add_argument("--watch", type=int, default=0)
    ap.add_argument("--max-age-days", type=int, default=120)
    a = ap.parse_args()
    if a.cmd == "reset":
        for p in (STATE, ACC, EVENTS, SEEN):
            if os.path.exists(p):
                os.remove(p)
        print("reset")
        return
    if a.cmd == "cloud":
        run_cloud(a.out)
        return
    if a.cmd == "public":
        print("wrote", build.public_export(DATA, a.out))
        return
    while True:
        run_once(a.max_age_days)
        if not a.watch:
            break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
