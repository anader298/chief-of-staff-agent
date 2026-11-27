#!/bin/bash
# PreToolUse hook for Bash, Write, Edit, MultiEdit and NotebookEdit. Three rules, all fail closed:
#   1. Nothing the model runs or writes may create, change or mention outbox/APPROVED. Only the owner creates
#      that file, by hand, outside the agent. Always blocked, even while a fresh approval exists.
#   2. curl, wget, openssl s_client, nc, telnet or socat aimed at an SMTP server, graph.microsoft.com or
#      gmail.googleapis.com is blocked always. Mail goes through tools/mail.py, which checks recipients.
#   3. A command that runs tools/mail.py with `send` or `send-draft` (any interpreter, any flags, any global
#      option before the subcommand), sendmail-style programs, or inline smtplib code is blocked unless
#      outbox/APPROVED is under 60 minutes old.
# Rule 3 matches programs being run, so reading or searching files that mention a send is not blocked.
# If the hook input cannot be parsed, it blocks on any mention of a send tool, a mail endpoint or APPROVED.
#
# Wire it in .claude/settings.json (see .claude/settings.example.json):
#   "PreToolUse": [{"matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": "<repo>/hooks/block_send.sh"}]}]
# Exit 2 tells Claude Code to refuse the tool call and show the stderr message to the model.

REPO="${COS_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
F="$REPO/outbox/APPROVED"
PY="${COS_PYTHON:-python3}"

block() { echo "Blocked: $1" >&2; exit 2; }
OWNER_ONLY="outbox/APPROVED is created only by the owner, by hand, outside the agent. Ask the owner to run 'touch outbox/APPROVED' in his own terminal, or to send the draft from his own mail client."

IN=$(cat)
if ! PARSED=$(printf '%s' "$IN" | "$PY" -I -c '
import sys, json
d = json.load(sys.stdin); t = d.get("tool_input") or {}
print((t.get("file_path") or t.get("notebook_path") or "").replace("\n", " "))
print((d.get("cwd") or "").replace("\n", " "))
print(t.get("command") or "")' 2>/dev/null); then
  # python missing or unparsable input: raw substring scan, fail closed on a hit
  if printf '%s' "$IN" | grep -Eiq 'APPROVED|mailmerge\.py|send_fast|smtplib|sendmail|msmtp|mail\.py.*send|mail .*send|smtp|graph\.microsoft\.com|gmail\.googleapis\.com'; then
    block "(fail-closed) could not parse the tool call; it mentions a send tool, a mail endpoint or the approval file."
  fi
  exit 0
fi
FP=$(printf '%s\n' "$PARSED" | sed -n 1p)
CWD=$(printf '%s\n' "$PARSED" | sed -n 2p)
CMD=$(printf '%s\n' "$PARSED" | sed -n '3,$p')

# ---- Rule 1a: file tools (Write, Edit, MultiEdit, NotebookEdit) on the approval file
if [ -n "$FP" ]; then
  norm=$(printf '%s' "$FP" | sed -E 's#/+#/#g; s#(/\.)+/#/#g')
  case "$norm" in
    APPROVED|*/outbox/APPROVED|outbox/APPROVED) block "the agent may not write the approval file. $OWNER_ONLY" ;;
  esac
  case "$CWD" in */outbox) [ "${norm##*/}" = APPROVED ] && block "the agent may not write the approval file. $OWNER_ONLY" ;; esac
fi
[ -z "$CMD" ] && exit 0

# ---- Rule 1b: any shell command that mentions the approval file
if printf '%s' "$CMD" | grep -Eq 'outbox/+(\./+)*APPROVED' \
   || { printf '%s' "$CMD" | grep -q 'outbox' && printf '%s' "$CMD" | grep -q 'APPROVED'; } \
   || { case "$CWD" in */outbox) true ;; *) false ;; esac && printf '%s' "$CMD" | grep -q 'APPROVED'; }; then
  block "the command touches outbox/APPROVED. $OWNER_ONLY"
fi

# ---- Rule 2: raw network tools aimed at a mail endpoint
W='(^|[^A-Za-z0-9_.-])'
if printf '%s' "$CMD" | grep -Eq "${W}(curl|wget|openssl|nc|ncat|telnet|socat)([^A-Za-z0-9_.-]|\$)" \
   && printf '%s' "$CMD" | grep -Eiq 'smtp|graph\.microsoft\.com|gmail\.googleapis\.com'; then
  block "raw network call to a mail endpoint. Mail goes only through tools/mail.py, which checks every recipient."
fi

# ---- Rule 3: send commands, opened only by a fresh owner approval
# File age in epoch seconds. Try GNU first: on Linux, `stat -f` means "filesystem status" and prints
# text before failing, which broke the age check (approval never opened). BSD/macOS stat rejects -c cleanly.
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }

hit=""
# inline send code run by an interpreter, including heredocs (their lines are not separate commands)
if printf '%s' "$CMD" | grep -Eq "${W}(python[0-9.]*|node|perl|ruby|bash|sh|zsh)([[:space:]]|\$)" \
   && printf '%s' "$CMD" | grep -Eq 'smtplib|users\.messages\.send|sendMail'; then
  hit="inline send code"
fi

# Split on command separators and inspect each segment.
while IFS= read -r seg; do
  [ -n "$hit" ] && break
  seg="${seg#"${seg%%[![:space:]]*}"}"            # ltrim
  seg="${seg#[(\{]}"; seg="${seg#"${seg%%[![:space:]]*}"}"
  [ -z "$seg" ] && continue
  # strip leading env assignments and wrappers
  while printf '%s' "$seg" | grep -Eq '^([A-Za-z_][A-Za-z0-9_]*=[^ ]* +|(sudo|nohup|time|exec|command|env|nice) +)'; do
    seg=$(printf '%s' "$seg" | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*=[^ ]* +|(sudo|nohup|time|exec|command|env|nice) +)//')
  done
  prog=$(printf '%s' "$seg" | awk '{print $1}'); prog="${prog##*/}"
  second=$(printf '%s' "$seg" | awk '{print $2}'); second="${second##*/}"
  case "$prog" in
    sendmail|msmtp|mutt|mailx) hit="$prog" ;;
    mail) printf '%s' "$seg" | grep -Eq ' -s ' && hit="mail -s" ;;
    mailmerge.py|send_fast*|send_mail*|send_email*) hit="$prog" ;;
    python*|bash|sh|zsh)
      case "$second" in mailmerge.py|send_fast*|send_mail*|send_email*) hit="$prog $second" ;; esac ;;
  esac
  [ -n "$hit" ] && break

  # tools/mail.py run in any form. Searching text (grep, rg) is exempt unless it hides a command substitution.
  case "$prog" in
    grep|egrep|fgrep|rg) printf '%s' "$seg" | grep -Eq '\$\(|`' || continue ;;
  esac
  # walk the words: after a mail.py reference, a bare `send`/`send-draft` (or a $variable) that is not the
  # value of an option is the subcommand. Quotes are stripped, so `bash -c 'python3 tools/mail.py send'` counts.
  r=$(printf '%s\n' "$seg" | awk '
    { for (i = 1; i <= NF; i++) {
        w = $i; gsub(/["'"'"'(){}]/, "", w)
        if (!seen) {
          n = split(w, p, "/"); b = p[n]
          if (b == "mail.py" || (prev == "-m" && (w == "mail" || w ~ /\.mail$/))) { seen = 1; prev = w; continue }
          if (b == "xargs" || b == "parallel") xa = 1
        } else {
          if ((w == "send" || w == "send-draft" || w ~ /^\$/) && !(prev ~ /^-/ && prev !~ /=/)) { print "hit"; exit }
        }
        prev = w
      }
      if (seen && xa) { print "hit"; exit }
    }')
  [ "$r" = hit ] && hit="tools/mail.py send"
done <<< "$(printf '%s\n' "$CMD" | tr ';|&' '\n\n\n')"

if [ -n "$hit" ]; then
  if [ -f "$F" ] && [ $(( $(date +%s) - $(mtime "$F") )) -lt 3600 ]; then exit 0; fi
  block "'$hit' sends mail and no owner approval is open. Leave it in outbox/ as a draft. $OWNER_ONLY"
fi
exit 0
