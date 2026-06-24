#!/usr/bin/env python3
"""
imsg-bridge — Lightweight HTTP bridge for agent-driven iMessage access.

Runs as a dedicated macOS user with its own Apple ID signed into Messages.app.
Provides a local HTTP API for an AI agent to send and receive iMessages.

Architecture:
  macOS User A (agent)                      macOS User B (you)
  ┌──────────────────────┐                  ┌──────────────────┐
  │ Messages.app         │                  │ Hermes Agent     │
  │ (signed in as agent) │                  │ → POST /send     │
  │       ↕              │                  │ → GET /history   │
  │ imsg CLI             │                  │ → GET /health    │
  │       ↕              │                  │                  │
  │ imsg_bridge.py       │◄── localhost ────┤                  │
  │ :8646                │     :8646        │                  │
  └──────────────────────┘                  └──────────────────┘

Background watch thread streams incoming messages to /tmp/imsg_watch.json
for near-instant detection by a polling agent cron.
"""

import json, subprocess, time, os, shutil, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HOST, PORT = "127.0.0.1", 8646
WATCH_FILE = "/tmp/imsg_watch.json"

# Find imsg — try Homebrew paths first, then PATH
IMSG = None
for p in ["/opt/homebrew/bin/imsg", "/usr/local/bin/imsg"]:
    if os.path.exists(p) and os.access(p, os.X_OK):
        IMSG = p
        break
if not IMSG:
    IMSG = shutil.which("imsg")


def run(args, timeout=15):
    try:
        r = subprocess.run([IMSG] + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.stderr, r.returncode
    except Exception as e:
        return "", str(e), -1


def watch_thread():
    """Run imsg watch --json in a subprocess, write new messages to watch file."""
    try:
        proc = subprocess.Popen(
            [IMSG, "watch", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for line in iter(proc.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)  # validate it's JSON
                with open(WATCH_FILE, "a") as f:
                    f.write(line + "\n")
            except json.JSONDecodeError:
                pass
    except Exception:
        pass


# Start watch thread (daemon — auto-exits when bridge stops)
threading.Thread(target=watch_thread, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/health":
            out, err, rc = run(["chats"])
            self._json({"status": "ok" if rc == 0 else "degraded",
                        "imsg": rc == 0, "error": err if rc else None})

        elif path == "/chats":
            out, err, rc = run(["chats"])
            if rc == 0:
                chats = [l.strip() for l in out.split("\n") if l.strip()]
                self._json({"chats": chats})
            else:
                self._json({"error": err, "rc": rc})

        elif path.startswith("/history/"):
            chat_id = path[len("/history/"):]
            out, err, rc = run(["history", "--chat-id", chat_id])
            if rc == 0:
                messages = [{"raw": l.strip(), "ts": time.time()}
                            for l in out.split("\n") if l.strip()]
                self._json({"messages": messages})
            else:
                self._json({"error": err, "rc": rc, "stdout": out[:500]})

        elif path == "/watch-file":
            messages = []
            if os.path.exists(WATCH_FILE):
                with open(WATCH_FILE) as f:
                    messages = [l.strip() for l in f.readlines() if l.strip()]
            self._json({"messages": messages, "count": len(messages)})

        else:
            self._json({"error": f"Unknown: {path}"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/send":
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if not body:
                self._json({"error": "Missing request body"}, 400)
                return
            data = json.loads(body)
            to, text = data.get("to", ""), data.get("text", "")
            if not to or not text:
                self._json({"error": "Missing 'to' or 'text'"}, 400)
                return
            out, err, rc = run(["send", "--to", to, "--text", text], timeout=30)
            self._json({"sent": rc == 0, "rc": rc, "stdout": out, "stderr": err})

        elif path == "/clear-watch":
            if os.path.exists(WATCH_FILE):
                os.remove(WATCH_FILE)
            self._json({"cleared": True})

        else:
            self._json({"error": f"Unknown: {path}"}, 404)


print(f"imsg-bridge running on http://{HOST}:{PORT}  [imsg={IMSG}]", flush=True)
HTTPServer((HOST, PORT), Handler).serve_forever()
