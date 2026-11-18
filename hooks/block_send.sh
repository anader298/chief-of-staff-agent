#!/bin/bash
# PreToolUse hook for Bash: block commands that would SEND mail unless outbox/APPROVED is under 60 min old.
# Matches the program being run, not words inside the command text, so reading or searching files is never blocked.
# Fails closed: if the command cannot be parsed, block on any mention of a send tool.
#
# Wire it in .claude/settings.json (see .claude/settings.example.json):
#   "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "<repo>/hooks/block_send.sh"}]}]
# Exit 2 tells Claude Code to refuse the tool call and show the stderr message to the model.

REPO="${COS_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
F="$REPO/outbox/APPROVED"
PY="${COS_PYTHON:-python3}"

IN=$(cat)
CMD=$(printf '%s' "$IN" | "$PY" -I -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)
if [ -z "$CMD" ]; then
  # python missing or unparsable input: fall back to a raw substring scan and fail closed on a hit
  if printf '%s' "$IN" | grep -Eq 'mailmerge\.py|send_fast|smtplib|sendmail|msmtp|mail\.py +send'; then
    echo "Blocked (fail-closed): could not parse command; it mentions a send tool." >&2; exit 2
  fi
  exit 0
fi

# File age in epoch seconds. Try GNU first: on Linux, `stat -f` means "filesystem status" and prints
# text before failing, which broke the age check (approval never opened). BSD/macOS stat rejects -c cleanly.
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }

# Split on command separators and inspect each segment's first program word.
printf '%s\n' "$CMD" | tr ';|&' '\n\n\n' | while IFS= read -r seg; do
  seg="${seg#"${seg%%[![:space:]]*}"}"            # ltrim
  [ -z "$seg" ] && continue
  # strip leading env assignments and sudo/nohup/time wrappers
  while printf '%s' "$seg" | grep -Eq '^([A-Za-z_][A-Za-z0-9_]*=[^ ]* +|sudo +|nohup +|time +)'; do
    seg=$(printf '%s' "$seg" | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*=[^ ]* +|sudo +|nohup +|time +)//')
  done
  prog=$(printf '%s' "$seg" | awk '{print $1}'); prog="${prog##*/}"
  second=$(printf '%s' "$seg" | awk '{print $2}'); second="${second##*/}"
  hit=0
  case "$prog" in
    sendmail|msmtp|mutt|mailx) hit=1 ;;
    mail) printf '%s' "$seg" | grep -Eq ' -s ' && hit=1 ;;
    python|python3|bash|sh|zsh)
      case "$second" in mailmerge.py|send_fast*|send_mail*|send_email*) hit=1 ;; esac
      case "$second" in mail.py) printf '%s' "$seg" | grep -Eq 'mail\.py +send' && hit=1 ;; esac
      printf '%s' "$seg" | grep -Eq -- '-c .*(smtplib|users\.messages\.send)' && hit=1 ;;
    mailmerge.py|send_fast*|send_mail*|send_email*) hit=1 ;;
  esac
  if [ "$hit" = 1 ]; then
    if [ -f "$F" ] && [ $(( $(date +%s) - $(mtime "$F") )) -lt 3600 ]; then exit 0; fi
    echo "Blocked: '$prog $second' sends mail. Create outbox/APPROVED (valid 60 min) after reviewing the draft." >&2
    exit 2
  fi
done
exit $?
