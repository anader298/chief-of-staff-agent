"""Fixture covering each line type: run with  python -I collect/tests/test_events.py"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import classify as C  # noqa: E402
# fixture workspaces, independent of whatever config.json is on this machine
C.WORKSPACES = [(os.path.expanduser("~/general/cos"), "cos"), (os.path.expanduser("~/general"), "general"),
                (os.path.expanduser("~/racing"), "racing")]
import transcripts  # noqa: E402
from classify import classify  # noqa: E402

T = "2026-10-26T15:00:0%dZ"


N = [0]


def uid():
    N[0] += 1
    return "u%d" % N[0]


def asst(mid, blocks, i, out=5):
    m = {"id": mid, "model": "claude-opus-5-5", "role": "assistant", "content": blocks,
         "usage": {"input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0}}
    return {"type": "assistant", "uuid": uid(), "timestamp": T % i, "message": m, "cwd": os.path.expanduser("~/general/cos")}


def result(tid, i, err=False):
    return {"type": "user", "uuid": uid(), "timestamp": T % i, "toolUseResult": {}, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": err}]}}


LINES = [
    {"type": "user", "uuid": uid(), "timestamp": T % 0, "origin": {"kind": "human"}, "message": {"role": "user", "content": "hello there"},
     "cwd": os.path.expanduser("~/general/cos")},
    {"type": "api-request-blob", "blob": "{not json"},
    asst("m1", [{"type": "text", "text": "ok"}], 1),
    asst("m1", [{"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": "skill-feedback"}}], 1, out=25),  # same id, more output
    result("t1", 2),
    asst("m2", [{"type": "tool_use", "id": "t2", "name": "mcp__claude_ai_Claude_Docs__batch", "input": {}}], 3),
    result("t2", 4, err=True),
    asst("m3", [{"type": "tool_use", "id": "t3", "name": "Write",
                 "input": {"file_path": os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.path.expanduser("~/racing")) + "/memory/x.md")}}], 5),
    result("t3", 6),
    {"type": "ai-title", "aiTitle": "Fixture"},
    {"type": "cost-state", "totalCostUSD": 1.5, "startTime": 1, "modelUsage": {"claude-opus-5-5[1m]": {"costUSD": 1.5}}},
]


def main():
    d = tempfile.mkdtemp()
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.expanduser("~/general/cos"))
    os.makedirs(os.path.join(d, slug))
    with open(os.path.join(d, slug, "s1.jsonl"), "w") as fh:
        fh.writelines(json.dumps(x) + "\n" for x in LINES)
    # a copied project folder: same lines under another slug and session id
    os.makedirs(os.path.join(d, "zz-copy"))
    with open(os.path.join(d, "zz-copy", "s2.jsonl"), "w") as fh:
        fh.writelines(json.dumps(x) + "\n" for x in LINES)
    transcripts.PROJECTS = d
    state, sessions, seen = {}, {}, {"lines": set(), "msgs": {}}
    r = transcripts.Reader(state, sessions, seen)
    r.run(9999)
    s = sessions["s1"]
    assert s["msgs"] == 3, s["msgs"]                       # m1 counted once despite two lines
    assert s["tokens"] == 3 * 115 + 20, s["tokens"]         # final output of m1 (25) counts, not the first (5)
    assert s["model_cost"] == {"claude-opus-5-5": 1.5}      # [1m] suffix normalised
    assert sessions["s2"]["msgs"] == 0 and sessions["s2"]["tokens"] == 0, sessions["s2"]  # copy adds nothing
    assert s["prompts"] == 1 and s["title"] == "Fixture" and s["cost_state"] == 1.5
    kinds = sorted((e["k"], e["r"], e["p"], e["st"]) for e in r.events)
    assert kinds == [("mcp", "connectors", "write", "failed"), ("memory_write", "memory", "write", "ok"),
                     ("skill", "skills", "read", "ok")], kinds
    assert next(e for e in r.events if e["k"] == "memory_write")["n"] == "racing"
    assert s["ws"] == "cos"
    assert len(r.events) == 3, len(r.events)
    r2 = transcripts.Reader(state, sessions, seen)                 # second pass reads nothing new
    r2.run(9999)
    assert r2.events == [] and sessions["s1"]["msgs"] == 3
    assert classify("Bash", {"command": "python3 tools/mail.py --account a@b.com send x"})[:3] == ("email", "write", "a@b.com")
    assert classify("Bash", {"command": "git push origin main"})[:2] == ("github", "write")
    assert classify("mcp__plugin_small-business_gmail__create_draft", {})[:2] == ("email", "write")
    assert classify("Skill", {"skill": "session-report:session-report"})[0] == "plugins"
    assert classify("Bash", {"command": "ls", "description": "token GOCSPX-abcdefghijklmnop"})[3] == "token [redacted]"
    # Bash heuristics the audit flagged
    assert classify("Bash", {"command": "grep -n auth auth.py"})[:2] == ("folders", "read")
    assert classify("Bash", {"command": "ls foo 2>/dev/null"})[:2] == ("folders", "read")
    assert classify("Bash", {"command": "echo hi > out.txt"})[:2] == ("folders", "write")
    assert classify("Bash", {"command": "python3 - <<'EOF'\nprint('osascript')\nx = 1 > 0\nEOF"})[:2] == ("folders", "read")
    assert classify("Bash", {"command": "curl -s -X POST https://x/y -d '{}'"})[:2] == ("internet", "write")
    assert classify("Bash", {"command": "cat ~/.claude/projects/x/memory/a.md"})[:2] == ("memory", "read")
    assert classify("Bash", {"command": "cd /tmp && osascript -e 'tell app'"})[0] == "browser"
    print("ok: all event checks pass")


if __name__ == "__main__":
    main()
