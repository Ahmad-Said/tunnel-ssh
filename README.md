# tunnel-ssh

> Remote execution and file management over HTTP / WebSocket – for when SSH port 22 is blocked.

`tunnel-ssh` exposes a lightweight FastAPI server on the remote machine (default port **222**) and gives you three ways
to interact with it:

| Component  | Tech                       | Purpose                                          |
|------------|----------------------------|--------------------------------------------------|
| **server** | FastAPI + uvicorn          | REST file manager + WebSocket command execution  |
| **cli**    | Typer + websockets + httpx | `tunnel exec/ls/get/put` from your terminal      |
| **ui**     | Flet (Flutter)             | Desktop GUI – file explorer + streaming terminal |
| **shared** | Pydantic                   | Data models + config shared by all components    |

---

## Installation

### Install from GitHub (no clone needed)

```bash
# Using pipx (recommended — isolated env, globally available)
pipx install git+https://github.com/Ahmad-Said/tunnel-ssh.git

# With extras (server or UI)
pipx install "tunnel-ssh[server] @ git+https://github.com/Ahmad-Said/tunnel-ssh.git"
pipx install "tunnel-ssh[all] @ git+https://github.com/Ahmad-Said/tunnel-ssh.git"

# Or using pip
pip install git+https://github.com/Ahmad-Said/tunnel-ssh.git
```

> **Don't have pipx?** `pip install pipx && pipx ensurepath` (restart your shell)
>
> **Windows users:** You can install Python and pipx easily via [Scoop](https://scoop.sh):
> ```powershell
> # Install Scoop (see https://scoop.sh for details)
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
>
> # Then install Python and pipx
> scoop install python
> pip install pipx && pipx ensurepath
> ```

### Install from a local clone

```bash
# Using pipx
pipx install .

# Or pip with --user
pip install --user .
```

### Development install (editable, inside a venv)

```bash
cd tunnel-ssh
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

> ⚠️ A venv install only makes `tunnel` available while the venv is activated.
> For shell completion and system-wide access, use `pipx install` instead.

---

## Quick Start

```bash
# If not installed globally yet:
pipx install .
# Or for development:
pip install -e .
```

### 1. Start the server (on the remote machine)

```bash
tunnel-server                                 # default: 0.0.0.0:222, no auth
tunnel-server --port 2222                     # custom port
tunnel-server --token s3cret                  # enable bearer-token auth
tunnel-server --host 127.0.0.1 --port 2222   # bind to localhost only
tunnel-server --shell /bin/sh                 # use a different shell (default: /bin/bash)
tunnel-server --log-level debug               # verbose logging
```

> **Note:** Port 222 may require elevated privileges on Linux/macOS.  
> You can also set `TUNNEL_SSH_PORT`, `TUNNEL_SSH_TOKEN`, and `TUNNEL_SSH_SHELL` env vars.

### 2. Use the CLI

```bash
# Execute remote commands (uses current context — see section 3)
tunnel exec ls -la /home
tunnel exec tail -f /var/log/syslog
tunnel exec --cwd /var/log cat access.log

# Override server per-command with --server / -s
tunnel exec -s myserver uname -a

# Batch mode — run multiple commands from a file
tunnel exec --script commands.txt

# Pipe support — read commands from stdin
echo "uname -a" | tunnel exec -
cat deploy-steps.sh | tunnel exec -s prod -

# List remote directory
tunnel ls /var/log
tunnel ls /etc -l              # long format: permissions, size, date

# Download a remote file
tunnel get /etc/hostname
tunnel get /var/log/app.log ./local-copy.log

# Upload a local file
tunnel put ./backup.tar.gz /tmp

# Override port or token per-command
tunnel exec -s myserver --port 2222 --token s3cret whoami
```

### 3. Named Server Profiles & Contexts

Save server configs in `~/.tunnel-ssh.json` so you never have to type host/port/token again.
Works like `kubectl config` — set a **current context** and all commands use it by default:

```bash
# Add server profiles
tunnel config add prod --host 10.0.0.5 --port 2222 --token s3cret
tunnel config add staging --host 10.0.0.10 --token staging-tok
tunnel config add dev --host 192.168.1.100 --token dev-tok

# Set the current context (like kubectl config use-context)
tunnel config use-context prod

# Show current context
tunnel config current-context        # → prod

# List all contexts (current one marked with *)
tunnel config get-contexts
#   CURRENT   NAME                 SERVER                         AUTH
#   *         prod                 10.0.0.5:2222                  token
#             staging              10.0.0.10:222                  token
#             dev                  192.168.1.100:222              token

# Now commands use the current context automatically — no server arg needed!
tunnel exec uname -a               # runs on prod (current context)
tunnel ls /home                    # lists /home on prod
tunnel get /etc/hostname           # downloads from prod

# Override context per-command with --server / -s
tunnel exec -s staging uname -a
tunnel exec -s 10.0.0.99 --token abc whoami

# Manage profiles
tunnel config list
tunnel config show prod
tunnel config update prod --port 443
tunnel config remove staging
```

> **Config file location:** `~/.tunnel-ssh.json` (override with `$TUNNEL_SSH_CONFIG`).
> See [`examples/tunnel-ssh-config.example.json`](examples/tunnel-ssh-config.example.json) for the full format.

### 4. Shell Completion (Tab Suggestions)

Enable tab-completion for commands, options, and arguments — similar to `kubectl completion`.

> **Prerequisite:** `tunnel` must be globally available (installed via `pipx install .` or `pip install --user .`).
> Shell completion won't work if `tunnel` is only installed inside a virtualenv.

#### Automatic install (all shells)

```bash
tunnel --install-completion
```

This auto-detects your shell and installs the completion script. Restart your shell afterwards.

#### Manual setup per shell

<details>
<summary><strong>PowerShell</strong></summary>

Add this line to your PowerShell profile (`$PROFILE`):

```powershell
tunnel --show-completion powershell | Out-String | Invoke-Expression
```

Or install permanently:

```powershell
tunnel --install-completion powershell
```

</details>

<details>
<summary><strong>Bash</strong></summary>

Add to `~/.bashrc`:

```bash
eval "$(tunnel --show-completion bash)"
```

Or install permanently:

```bash
tunnel --install-completion bash
```

</details>

<details>
<summary><strong>Zsh</strong></summary>

Add to `~/.zshrc`:

```zsh
eval "$(tunnel --show-completion zsh)"
```

Or install permanently:

```zsh
tunnel --install-completion zsh
```

</details>

<details>
<summary><strong>Fish</strong></summary>

```fish
tunnel --show-completion fish | source
```

Or install permanently:

```fish
tunnel --install-completion fish
```

</details>

After setup, press **Tab** to get suggestions for commands (`exec`, `ls`, `config`, …), options (`--server`,
`--port`, …), and sub-commands (`config add`, `config use-context`, …).

### 5. Launch the Desktop UI

```bash
tunnel-ui
```

- Enter server address, port, and optional auth token, then click **Connect**
- **File Explorer (left panel):**
    - Browse directories — click folders to navigate, `..` to go up
    - Breadcrumb navigation — click any path segment to jump directly
    - Click a file to download it to your working directory
    - Right-click (context menu) → **Download**, **Rename**, **Delete**, **Copy Path**
    - Connection status indicator (green/red dot)
- **Terminal (right panel):**
    - Run commands with real-time streamed output
    - Use `↑` / `↓` arrow keys to browse command history
- **Keyboard shortcuts:**
    - `Enter` — send command
    - `Ctrl+L` — clear terminal
    - `Ctrl+R` — refresh file list

---

## Project Structure

```
tunnel-ssh/
├── pyproject.toml              # Build config, dependencies, ruff/mypy/pytest settings
├── README.md
├── TODO.md
├── tests/                      # pytest test suite
│   ├── test_shared.py
│   └── test_server_helpers.py
└── src/tunnel_ssh/             # All source code under a proper namespace
    ├── __init__.py             # Package root (__version__)
    ├── _version.py             # Single source of truth for version
    ├── py.typed                # PEP 561 type-checking marker
    ├── shared/                 # Models + config shared by all components
    │   ├── config.py           # Server profiles, defaults, load/save
    │   ├── models.py           # Pydantic: FileItem, DirectoryListing, CommandPayload, CommandOutput
    │   └── http.py             # Shared HTTP helpers (auth_headers, base_url, ws_url)
    ├── server/                 # FastAPI app (runs on the remote machine)
    │   ├── app.py              # create_app() factory
    │   ├── settings.py         # ServerSettings singleton (token, shell)
    │   ├── auth.py             # Bearer-token dependency
    │   ├── helpers.py          # format_permissions, etc.
    │   ├── routes/
    │   │   ├── health.py       # GET /health
    │   │   ├── files.py        # GET/POST/DELETE/PATCH /file, GET /files
    │   │   └── websocket.py    # WS /ws/execute
    │   └── __main__.py         # Typer CLI entrypoint (tunnel-server)
    ├── cli/                    # Typer CLI (runs on your local machine)
    │   ├── app.py              # Top-level Typer app + run()
    │   ├── http_client.py      # HTTP/WS client helpers
    │   └── commands/
    │       ├── exec_cmd.py     # tunnel exec
    │       ├── files.py        # tunnel ls/get/put/rm/mv/cat
    │       └── config.py       # tunnel config add/list/remove
    └── ui/                     # Flet desktop app (runs on your local machine)
        ├── app.py              # Main Flet app + layout
        └── helpers.py          # Pure utility functions (human_size, path utils)
```

## API Reference

| Endpoint                | Method    | Auth        | Description                                                       |
|-------------------------|-----------|-------------|-------------------------------------------------------------------|
| `/health`               | GET       | No          | Liveness probe                                                    |
| `/files?path=`          | GET       | Bearer      | List directory contents (returns `DirectoryListing`)              |
| `/file?path=`           | GET       | Bearer      | Download a file                                                   |
| `/file?path=`           | POST      | Bearer      | Upload a file (multipart: `path` query + `file` form)             |
| `/file?path=`           | DELETE    | Bearer      | Delete a file or directory (recursive)                            |
| `/file?path=&new_name=` | PATCH     | Bearer      | Rename a file or directory                                        |
| `/ws/execute?token=`    | WebSocket | Query param | Send `CommandPayload` JSON, receive streamed `CommandOutput` JSON |

> When no `--token` / `TUNNEL_SSH_TOKEN` is set on the server, auth is disabled entirely.

## Authentication

| Transport | How token is sent                      |
|-----------|----------------------------------------|
| HTTP REST | `Authorization: Bearer <token>` header |
| WebSocket | `?token=<token>` query parameter       |

## Configuration

| Env var             | Default              | Description                                 |
|---------------------|----------------------|---------------------------------------------|
| `TUNNEL_SSH_PORT`   | `222`                | Default server port                         |
| `TUNNEL_SSH_TOKEN`  | *(none)*             | Bearer token (disables auth if unset)       |
| `TUNNEL_SSH_SHELL`  | `/bin/bash`          | Shell executable used for command execution |
| `TUNNEL_SSH_CONFIG` | `~/.tunnel-ssh.json` | Path to server profiles config              |

## Data Models

All models live in `src/tunnel_ssh/shared/models.py` and are shared across server, CLI, and UI.

| Model              | Used by         | Description                                                     |
|--------------------|-----------------|-----------------------------------------------------------------|
| `FileItem`         | Server → Client | Single file/directory entry (name, size, modified, permissions) |
| `DirectoryListing` | Server → Client | `GET /files` response — path + list of `FileItem`               |
| `CommandPayload`   | Client → Server | WebSocket message: command string + optional cwd                |
| `CommandOutput`    | Server → Client | WebSocket message: stream (`stdout`/`stderr`/`exit`) + data     |

## Security Notice

⚠️ This tool executes arbitrary shell commands remotely. Use it only on **trusted networks**.

- Always set a **token** in production: `tunnel-server --token <secret>`
- Consider binding to `127.0.0.1` and using an SSH tunnel or VPN for the transport layer
- No TLS by default — put behind a reverse proxy with HTTPS for public-facing deployments

## Development

```bash
# Clone the repository
git clone <repo-url> && cd tunnel-ssh

# Create a virtual environment (Python 3.12+)
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# Install in editable mode (with dev tools)
pip install -e ".[dev]"
```

### Running locally

```bash
# Terminal 1 — start the server
tunnel-server --token dev123

# Terminal 2 — use the CLI
tunnel exec localhost --token dev123 whoami

# Or launch the GUI
tunnel-ui
```

### Quality tools

```bash
ruff check src/ tests/        # lint
ruff format src/ tests/       # auto-format
python -m pytest tests/ -v    # test suite
mypy src/                     # type checking
```

### Project layout at a glance

| Directory                | Purpose                                                                 |
|--------------------------|-------------------------------------------------------------------------|
| `src/tunnel_ssh/shared/` | Pydantic models, config & HTTP helpers — imported by all other packages |
| `src/tunnel_ssh/server/` | FastAPI app (runs on the remote machine)                                |
| `src/tunnel_ssh/cli/`    | Typer CLI (runs on your local machine)                                  |
| `src/tunnel_ssh/ui/`     | Flet desktop app (runs on your local machine)                           |
| `tests/`                 | pytest test suite                                                       |

## Roadmap

See [`TODO.md`](TODO.md) for the full feature backlog. Highlights:

- **Server:** Session management (persistent shell sessions), Docker image for Rocky Linux
- **CLI:** Sudo support, multiple profiles from `~/.tunnel-ssh.json`
- **UI:** Drag-and-drop upload, text file preview pane, multi-server tabs, theme switcher, auto-reconnect
- **Packaging:** Standalone executables via PyInstaller / Nuitka, Docker image for Rocky Linux
- **Testing:** `pytest` unit & integration test suite

## License

MIT

