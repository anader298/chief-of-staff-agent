#!/bin/bash
# Claude Code Stop hook: refresh the dashboard data in the background, at most once a minute.
# Always exits 0 at once so it never slows a turn down.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${COS_PYTHON:-python3}"
STAMP="$DIR/data/.hook-stamp"
if [ -d "$DIR/data" ] && [ -z "$(find "$STAMP" -mmin -1 2>/dev/null)" ]; then
  touch "$STAMP"
  ( "$PY" -I "$DIR/collect/collect.py" run ) >> "$DIR/data/collector.log" 2>&1 &
fi
exit 0
