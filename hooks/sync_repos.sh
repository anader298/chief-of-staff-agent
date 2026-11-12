#!/bin/bash
# Keep a laptop's clone level with what cloud sessions pushed, before work starts.
#
# When most work happens in cloud sessions, the repo that holds skills and agent definitions moves
# without the laptop knowing. If ~/.claude/skills/* are symlinks into this repo, a stale clone means a
# local session silently runs yesterday's rules. This fast-forwards each repo first.
#
# Wire it to SessionStart and to PreToolUse on Skill (see .claude/settings.example.json).
# List repos in COS_SYNC_REPOS (colon-separated); default is this repo only.
#
# Safe by construction: --ff-only, never on a dirty tree, never resolves a conflict, never
# switches branch. Anything it cannot do cleanly it reports and leaves alone.

DEFAULT_REPO="$(cd "$(dirname "$0")/.." && pwd)"
IFS=':' read -r -a REPOS <<< "${COS_SYNC_REPOS:-$DEFAULT_REPO}"

THROTTLE=180                       # seconds; a Skill call every prompt should not hit the network
STAMP_DIR="${TMPDIR:-/tmp}/claude-skill-pull"
mkdir -p "$STAMP_DIR"

notes=""

for repo in "${REPOS[@]}"; do
  [ -d "$repo/.git" ] || continue

  stamp="$STAMP_DIR/$(echo "$repo" | tr '/' '_')"
  now=$(date +%s)
  if [ -f "$stamp" ]; then
    last=$(cat "$stamp" 2>/dev/null || echo 0)
    [ $((now - last)) -lt "$THROTTLE" ] && continue
  fi
  echo "$now" > "$stamp"

  name=$(basename "$repo")

  # A dirty tree is work in progress. Say so, change nothing.
  if [ -n "$(git -C "$repo" status --porcelain 2>/dev/null | grep -v '^??')" ]; then
    notes="${notes}${name}: uncommitted changes, not pulled. "
    continue
  fi

  git -C "$repo" fetch --quiet 2>/dev/null || { notes="${notes}${name}: fetch failed (offline?). "; continue; }

  behind=$(git -C "$repo" rev-list --count HEAD..@{u} 2>/dev/null) || continue
  ahead=$(git -C "$repo" rev-list --count @{u}..HEAD 2>/dev/null) || continue
  [ "${behind:-0}" -eq 0 ] && continue

  if [ "${ahead:-0}" -gt 0 ]; then
    notes="${notes}${name}: diverged, ${ahead} local / ${behind} remote commits. Needs a merge by hand. "
    continue
  fi

  if git -C "$repo" merge --ff-only @{u} --quiet 2>/dev/null; then
    notes="${notes}${name}: pulled ${behind} commit(s) from the cloud. "
  else
    notes="${notes}${name}: ${behind} commit(s) behind, fast-forward refused. "
  fi
done

[ -n "$notes" ] && echo "[repo sync] $notes"
exit 0
