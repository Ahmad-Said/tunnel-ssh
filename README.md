# tunnel-ssh

> Remote execution and file management over HTTP / WebSocket – for when SSH port 22 is blocked.

`tunnel-ssh` exposes a lightweight FastAPI server on the remote machine (default port **222**) and gives you three ways to interact with it:

| Component | Tech | Purpose |
|-----------|------|---------|
| **server** | FastAPI + uvicorn | REST file manager + WebSocket command execution |
| **cli** | Typer + websockets | `tunnel <server> <cmd>` from your terminal |
| **ui** | Flet (Flutter) | Desktop GUI – file explorer + streaming terminal |
| **shared** | Pydantic | Data models shared by all components |

---

## Quick Start

```bash
# Clone & install (editable mode)
cd tunnel-ssh
pip install -e .
```

### 1. Start the server (on the remote machine)

```bash
tunnel-server
# Listening on 0.0.0.0:222
```

> **Note:** Port 222 may require elevated privileges on Linux/macOS. Override with:
> ```bash
> TUNNEL_SSH_PORT=2222 tunnel-server
> ```

### 2. Use the CLI

```bash
# List files
tunnel myserver ls /home

# Stream output in real-time
tunnel myserver tail -f /var/log/syslog

# Specify a custom port
tunnel myserver --port 2222 cat /etc/hostname

# Set remote working directory
tunnel myserver --cwd /var/log ls -la
```

### 3. Launch the Desktop UI

```bash
tunnel-ui
```

Enter the server address and port, click **Connect** to browse files, type commands in the terminal pane and see output streamed live.

---

## Project Structure

```
tunnel-ssh/
├── pyproject.toml          # Build config & dependencies
├── README.md
├── shared/
│   ├── __init__.py
│   └── models.py           # Pydantic: FileItem, DirectoryListing, CommandPayload, CommandOutput
├── server/
│   ├── __init__.py
│   └── main.py             # FastAPI app (GET /files, GET /file, POST /file, WS /ws/execute)
├── cli/
│   ├── __init__.py
│   └── main.py             # Typer CLI (tunnel <server> <command>)
└── ui/
    ├── __init__.py
    └── main.py             # Flet desktop app (file explorer + terminal)
```

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/files?path=` | GET | List directory contents |
| `/file?path=` | GET | Download a file |
| `/file?path=` | POST | Upload a file (multipart) |
| `/ws/execute` | WebSocket | Send `CommandPayload` JSON, receive streamed `CommandOutput` JSON frames |

## Security Notice

⚠️ This tool has **no authentication**. It is designed for trusted networks / development use only. For production, consider adding token-based auth or mTLS.

## License

MIT

