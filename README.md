# tunnel-ssh

> Remote execution and file management over HTTP / WebSocket – for when SSH port 22 is blocked.

`tunnel-ssh` exposes a lightweight FastAPI server on the remote machine (default port **222**) and gives you three ways to interact with it:

| Component | Tech | Purpose |
|-----------|------|---------|
| **server** | FastAPI + uvicorn | REST file manager + WebSocket command execution |
| **cli** | Typer + websockets + httpx | `tunnel exec/ls/get/put` from your terminal |
| **ui** | Flet (Flutter) | Desktop GUI – file explorer + streaming terminal |
| **shared** | Pydantic | Data models + config shared by all components |

---

## Quick Start

```bash
# Clone & install (editable mode)
cd tunnel-ssh
pip install -e .
```

### 1. Start the server (on the remote machine)

```bash
tunnel-server                                 # default: 0.0.0.0:222, no auth
tunnel-server --port 2222                     # custom port
tunnel-server --token s3cret                  # enable bearer-token auth
tunnel-server --host 127.0.0.1 --port 2222   # bind to localhost only
```

> **Note:** Port 222 may require elevated privileges on Linux/macOS.  
> You can also set `TUNNEL_SSH_PORT` and `TUNNEL_SSH_TOKEN` env vars.

### 2. Use the CLI

```bash
# Execute remote commands (streaming output)
tunnel exec myserver ls -la /home
tunnel exec myserver tail -f /var/log/syslog
tunnel exec myserver --cwd /var/log cat access.log

# List remote directory
tunnel ls myserver /var/log
tunnel ls myserver /etc -l              # long format: permissions, size, date

# Download a remote file
tunnel get myserver /etc/hostname
tunnel get myserver /var/log/app.log ./local-copy.log

# Upload a local file
tunnel put myserver ./backup.tar.gz /tmp

# Override port or token per-command
tunnel exec myserver --port 2222 --token s3cret whoami
```

### 3. Named Server Profiles

Save server configs in `~/.tunnel-ssh.json` so you never have to type host/port/token again:

```bash
tunnel config add prod --host 10.0.0.5 --port 2222 --token s3cret
tunnel config add staging --host 10.0.0.10
tunnel config list
tunnel config remove staging

# Now use the profile name instead of host:
tunnel exec prod uname -a
tunnel ls prod /home
tunnel get prod /etc/hostname
```

### 4. Launch the Desktop UI

```bash
tunnel-ui
```

- Enter server address, port, and optional auth token
- **File Explorer (left panel):** Browse directories, click folders to navigate, click files to download
- **Terminal (right panel):** Run commands with real-time streamed output, use ↑/↓ for command history

---

## Project Structure

```
tunnel-ssh/
├── pyproject.toml          # Build config & dependencies
├── README.md
├── shared/
│   ├── __init__.py
│   ├── config.py           # Centralized config: port, token, server profiles
│   └── models.py           # Pydantic: FileItem, DirectoryListing, CommandPayload, CommandOutput
├── server/
│   ├── __init__.py
│   └── main.py             # FastAPI app (GET /health, /files, /file, POST /file, WS /ws/execute)
├── cli/
│   ├── __init__.py
│   └── main.py             # Typer CLI (tunnel exec/ls/get/put/config)
└── ui/
    ├── __init__.py
    └── main.py             # Flet desktop app (file explorer + terminal)
```

## API Reference

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Liveness probe |
| `/files?path=` | GET | Bearer | List directory contents (returns `DirectoryListing`) |
| `/file?path=` | GET | Bearer | Download a file |
| `/file?path=` | POST | Bearer | Upload a file (multipart form) |
| `/ws/execute?token=` | WebSocket | Query param | Send `CommandPayload` JSON, receive streamed `CommandOutput` JSON |

> When no `--token` / `TUNNEL_SSH_TOKEN` is set on the server, auth is disabled entirely.

## Authentication

| Transport | How token is sent |
|-----------|-------------------|
| HTTP REST | `Authorization: Bearer <token>` header |
| WebSocket | `?token=<token>` query parameter |

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `TUNNEL_SSH_PORT` | `222` | Default server port |
| `TUNNEL_SSH_TOKEN` | *(none)* | Bearer token (disables auth if unset) |
| `TUNNEL_SSH_CONFIG` | `~/.tunnel-ssh.json` | Path to server profiles config |

## Security Notice

⚠️ This tool executes arbitrary shell commands remotely. Use it only on **trusted networks**.
- Always set a **token** in production: `tunnel-server --token <secret>`
- Consider binding to `127.0.0.1` and using an SSH tunnel or VPN for the transport layer
- No TLS by default — put behind a reverse proxy with HTTPS for public-facing deployments

## License

MIT

