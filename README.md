# imsg-bridge

Lightweight HTTP bridge for agent-driven iMessage access. Wraps the [`imsg`](https://github.com/steipete/imsg) CLI into a local HTTP API so an AI agent can send and receive texts through its own iMessage identity.

## Architecture

```
Agent's macOS User                    Your macOS User
┌──────────────────────┐             ┌──────────────────┐
│ Messages.app         │             │ AI Agent         │
│ (agent's Apple ID)   │             │ → POST /send     │
│       ↕              │             │ → GET /history   │
│ imsg CLI             │             │ → GET /health    │
│       ↕              │             │                  │
│ bridge.py            │◄─localhost──┤                  │
│ port 8646            │   :8646     │                  │
└──────────────────────┘             └──────────────────┘
```

The bridge runs as a **dedicated macOS user** with its own Apple ID signed into Messages.app. This keeps the agent's identity completely separate from yours — it has its own phone number, its own messages, its own permissions.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Bridge + imsg status check |
| `GET` | `/chats` | List recent conversations |
| `GET` | `/history/<chat_id>` | Message history for a chat |
| `GET` | `/watch-file` | Read real-time watch file (from `imsg watch`) |
| `POST` | `/send` | Send a message `{"to": "+1...", "text": "..."}` |
| `POST` | `/clear-watch` | Clear processed watch entries |

## Quick Start

### Prerequisites

- macOS with Messages.app
- A second macOS user account for the agent (or a second Apple ID in a shared Messages.app)
- [imsg](https://github.com/steipete/imsg) installed via Homebrew: `brew install steipete/tap/imsg`

### Setup

1. **Create an agent macOS user** and sign into Messages.app with the agent's Apple ID.

2. **Grant permissions** on the agent user:
   - System Settings → Privacy → Full Disk Access → Terminal
   - System Settings → Privacy → Automation → Terminal → Messages

3. **Copy and run the bridge** on the agent user:
   ```bash
   python3 bridge.py
   ```

4. **Configure your agent** to poll the bridge. Example Hermes Agent cron (every 1 minute):
   ```
   Read /watch-file → parse incoming → respond via /send → clear processed
   ```

5. **Optional: launchd auto-start** for the agent user:
   ```bash
   sudo launchctl submit -l ai.imsg-bridge \
     -p /usr/bin/python3 \
     -o /Users/<agent>/Library/Logs/imsg-bridge.log \
     -e /Users/<agent>/Library/Logs/imsg-bridge-error.log \
     -- /Users/<agent>/path/to/bridge.py
   ```

## Design Notes

- **Zero dependencies.** Pure Python stdlib — `http.server`, `subprocess`, `threading`, `json`. No pip install needed.
- **Real-time watch thread.** `imsg watch --json` streams incoming messages to `/tmp/imsg_watch.json` as they arrive. Your agent reads this file instead of polling history.
- **No cloud services.** The bridge runs entirely on localhost. No API keys, no tunnels, no third-party dependencies.
- **~100 lines.** The entire bridge is a single file. Easy to audit, easy to modify.

## Caveats

- `imsg` sends from whatever Apple ID is active in the **current macOS user's** Messages.app. This is why the bridge runs as a dedicated user — it guarantees message identity.
- Automation permission is required for sending. Without it, `imsg send` returns exit 0 but the message never departs.
- The watch file grows unbounded. Your agent should call `/clear-watch` after processing new messages.

## Built With

- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** — The agent framework this runs on. Cron-driven autonomous operation, tool-use, and subagent delegation.
- **[ponytail](https://github.com/DietrichGebert/ponytail)** — Made the bridge ~54% smaller by cutting dead code, redundant pollers, and unnecessary CORS headers. Lazy senior dev methodology.
- **[Holographic Memory](https://github.com/NousResearch/hermes-agent)** — Local SQLite+FTS5 fact store that remembers user preferences, system state, and session history across restarts.
- **[imsg](https://github.com/steipete/imsg)** — The CLI that bridges to macOS Messages.app private frameworks. The foundation this whole thing sits on.

## License

MIT
