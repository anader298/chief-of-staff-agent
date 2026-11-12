"""Map one tool call to (resource, perm, item, detail).

Resources are the columns of the Agent Mesh design. Only allow-listed input
fields leave this module: skill name, subagent_type, description, file_path,
mailbox account, URL host. Never commands, queries or message bodies.
"""
import json
import os
import re
from urllib.parse import urlparse

HOME = os.path.expanduser("~")
DASH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    """dashboard/config.json, falling back to config.example.json."""
    for n in ("config.json", "config.example.json"):
        try:
            with open(os.path.join(DASH, n)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return {}


CONFIG = load_config()

# cwd prefix -> workspace label (longest prefix wins), from config "workspaces": [["~/path", "label"], ...]
WORKSPACES = [(os.path.expanduser(p), label) for p, label in CONFIG.get("workspaces", [])]


def workspace_of(path):
    if not path:
        return "other"
    for prefix, label in WORKSPACES:
        if path == prefix or path.startswith(prefix + "/"):
            return label
    if path.startswith(HOME + "/.claude"):
        return "claude"
    return "other"


def workspace_of_slug(slug):
    """Project dir slug (-home-me-work) -> workspace label."""
    best, label = 0, "other"
    for prefix, lab in WORKSPACES:
        s = re.sub(r"[^A-Za-z0-9]", "-", prefix)
        if (slug == s or slug.startswith(s + "-")) and len(s) > best:
            best, label = len(s), lab
    return label


WRITE_VERB = re.compile(
    r"(create|update|delete|write|send|label|trash|spam|deploy|put|batch|add|remove|"
    r"set|click|type|press|drag|launch|kill|move|copy|upload|publish|import|respond|"
    r"perform|scroll|hotkey|finalize|ack)", re.I)

MCP_PRETTY = {
    "claude_ai_Claude_Docs": "Claude Docs", "claude_ai_Firecrawl": "Firecrawl",
    "claude_design": "Claude Design", "cmux-cua": "cmux-cua", "chrome-devtools": "Chrome DevTools",
    "netlify": "Netlify", "claude_ai_Netlify": "Netlify",
}


def mcp_server(name):
    parts = name.split("__")
    server = parts[1] if len(parts) > 1 else name
    tool = parts[2] if len(parts) > 2 else ""
    if server.startswith("plugin_"):  # plugin_small-business_gmail
        server = server.split("_", 2)[-1]
    return server, tool


def mcp_item(server):
    """The item name classify() files an MCP server's calls under."""
    low = server.lower()
    if "gmail" in low:
        return "Gmail connector"
    if "calendar" in low:
        return "Google Calendar"
    if "github" in low:
        return "GitHub MCP"
    if "firecrawl" in low:
        return "Firecrawl"
    return MCP_PRETTY.get(server, server.replace("claude_ai_", "").replace("_", " "))


def _host(url):
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


SECRETISH = re.compile(r"(GOCSPX-\S+|sk-[A-Za-z0-9_-]{12,}|ya29\.\S+|gh[pousr]_[A-Za-z0-9]{20,}|(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{40,})")


def scrub(text):
    return SECRETISH.sub("[redacted]", text or "")


HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\s*\1\s*$", re.S | re.M)


def _strip_heredocs(cmd):
    """Drop heredoc bodies so code inside `python - <<EOF` is not read as shell."""
    return HEREDOC.sub("", cmd)


def _command_words(cmd):
    """First word of every shell command segment (after ;, &&, ||, |, newline, `cd x &&`)."""
    body = _strip_heredocs(cmd)
    words = set()
    for seg in re.split(r"(?:\|\||&&|[;|\n(])", body):
        toks = seg.strip().split()
        while toks and ("=" in toks[0] and not toks[0].startswith("=")):  # VAR=x cmd
            toks = toks[1:]
        if toks:
            words.add(os.path.basename(toks[0]))
    return words


WRITE_CMDS = {"mkdir", "cp", "mv", "rm", "tee", "touch", "ln", "rsync", "unzip", "tar", "install", "chmod", "trash"}


def _shell_writes(cmd, head):
    if head & WRITE_CMDS:
        return True
    body = _strip_heredocs(cmd)
    if re.search(r"\bsed\s+-i\b", body):
        return True
    # a redirect into a real file; ignore 2>, &>, >&2 and anything to /dev/null
    for m in re.finditer(r"(?<![0-9&>])>>?\s*([^\s&|;]+)", body):
        target = m.group(1)
        if not target.startswith("/dev/") and not target.startswith("&"):
            return True
    return "<<" in cmd and re.search(r"\bcat\s*>", cmd) is not None


def classify(name, inp):
    """Return (resource, perm, item, detail) or None when the tool touches no resource."""
    inp = inp if isinstance(inp, dict) else {}
    desc = scrub((inp.get("description") or "")[:160])

    if name == "Bash":
        cmd = inp.get("command") or ""
        if "mail.py" in cmd:
            m = re.search(r"--account\s+(\S+)", cmd)
            acct = m.group(1) if m and "@" in m.group(1) and "$" not in m.group(1) else "mailbox"
            write = re.search(r"\b(send|send-draft|draft|delete-draft)\b", cmd)
            return ("email", "write" if write else "read", acct, desc)
        if re.search(r"\bgit\s+(push|commit)\b", cmd):
            return ("github", "write", CONFIG.get("repo", "git") if "/cos" in cmd else "git", desc)
        if re.search(r"(^|[\s;&|(])gh\s", cmd) or re.search(r"\bgit\s+(pull|fetch|clone|log)\b", cmd):
            return ("github", "read", "git", desc)
        head = _command_words(cmd)
        if head & {"osascript"} or re.search(r"(^|[;&|]\s*)open\s+-a\b", cmd, re.M):
            return ("browser", "write", "Chrome / macOS apps", desc)
        if head & {"curl", "wget", "yt-dlp"}:
            post = re.search(r"\s(-X\s*(POST|PUT|PATCH|DELETE)|-d\s|--data\b|-F\s|--form\b)", cmd)
            return ("internet", "write" if post else "read", "curl", desc)
        write = _shell_writes(cmd, head)
        if "/memory/" in cmd:
            return ("memory", "write" if write else "read", "shell", desc)
        return ("folders", "write" if write else "read", "shell", desc)

    if name in ("Read", "Glob", "Grep", "Write", "Edit", "NotebookEdit", "MultiEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
        perm = "read" if name in ("Read", "Glob", "Grep") else "write"
        if "/memory/" in path:
            return ("memory", perm, workspace_of_slug(path.split("/memory/")[0].rsplit("/", 1)[-1]), os.path.basename(path))
        return ("folders", perm, workspace_of(path), path[-160:])

    if name in ("WebSearch",):
        return ("internet", "read", "web search", "")
    if name in ("WebFetch",):
        return ("internet", "read", _host(inp.get("url") or "") or "fetch", "")

    if name == "Skill":
        skill = inp.get("skill") or inp.get("command") or "?"
        return ("plugins" if ":" in skill else "skills", "read", skill, "")

    if name == "Agent":
        return ("agents", "write", inp.get("subagent_type") or "general-purpose", desc)
    if name in ("SendMessage", "TaskStop", "RemoteTrigger", "CronCreate", "CronDelete"):
        return ("agents", "write", name, "")
    if name in ("ListAgents", "CronList", "ReadNotifications"):
        return ("agents", "read", name, "")

    if name == "DesignSync":
        return ("connectors", "read", "Claude Design", "")

    if name.startswith("mcp__"):
        server, tool = mcp_server(name)
        perm = "write" if WRITE_VERB.search(tool) else "read"
        low = server.lower()
        if "gmail" in low:
            return ("email", perm, "Gmail connector", "")
        if "calendar" in low:
            return ("calendar", perm, "Google Calendar", "")
        if "github" in low:
            return ("github", perm, "GitHub MCP", "")
        if "firecrawl" in low:
            return ("internet", "read", "Firecrawl", "")
        if any(k in low for k in ("cmux", "chrome", "computer", "browser")):
            return ("browser", perm, MCP_PRETTY.get(server, server), "")
        return ("connectors", perm, MCP_PRETTY.get(server, server.replace("claude_ai_", "").replace("_", " ")), "")

    return None
