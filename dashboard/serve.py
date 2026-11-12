#!/usr/bin/env python3
"""Serve the dashboard on 127.0.0.1:8765 and refresh data/ every 5 minutes while it runs.

GET /api/refresh runs one pass now. Set COS_DASH_NO_COLLECT=1 to serve existing data/ only
(for example the synthetic sample from sample/make_sample.py).
"""
import functools
import http.server
import os
import subprocess
import sys
import threading
import time

DASH = os.path.dirname(os.path.abspath(__file__))
COLLECT = [sys.executable, "-I", os.path.join(DASH, "collect", "collect.py"), "run"]
LOG = os.environ.get("COS_DASH_LOG", os.path.join(DASH, "data", "collector.log"))
_lock = threading.Lock()


def refresh():
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        with open(LOG, "a") as fh:
            r = subprocess.run(COLLECT, stdout=fh, stderr=fh, timeout=600)
        return "ok" if r.returncode == 0 else "failed (%d)" % r.returncode
    except (OSError, subprocess.SubprocessError) as e:
        return "failed: %s" % e
    finally:
        _lock.release()


def loop(interval):
    while True:
        refresh()
        time.sleep(interval)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/refresh"):
            body = refresh().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # page, scripts and data all change between pulls
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.makedirs(os.path.join(DASH, "data"), exist_ok=True)
    if not os.environ.get("COS_DASH_NO_COLLECT"):
        threading.Thread(target=loop, args=(300,), daemon=True).start()
    port = int(os.environ.get("COS_DASH_PORT", "8765"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=DASH))
    print("serving http://127.0.0.1:%d/ (refresh every 5 min)" % port, flush=True)
    srv.serve_forever()
