#!/bin/bash
# Start the dashboard server (it refreshes data/ every 5 min while it runs) and open it in the browser.
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${COS_PYTHON:-python3}"
PORT=8765
if ! curl -s -o /dev/null "http://127.0.0.1:$PORT/api/refresh"; then
  nohup "$PY" -I "$DIR/serve.py" >> "$DIR/data/collector.log" 2>&1 &
  sleep 1
fi
URL="http://127.0.0.1:$PORT/"
command -v open >/dev/null && open "$URL" || { command -v xdg-open >/dev/null && xdg-open "$URL"; } || echo "$URL"
