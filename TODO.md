# tunnel-ssh — TODO / Future Features

> Features and improvements to implement in future iterations.
> Ordered roughly by priority within each category.
> However we don't care about security feature but we care more about functionality first.
> Always think of goood project structure and code quality, so some of these may be split into multiple smaller tasks or combined as needed.
primary
the ui must be built on windows
the cli also must be executable on windows
the server must be run on linux
let's container the build of server to be runned on rocky linux
you have access to git commit and push at milestone
when you done something mark it to other agent know your step
if you see missing feature todo add it
---

## 🖥️ Server
- [ ] **Authentication** — Support bearer token auth via `Authorization saved in json config file for each server
- [x] Choose of which full path shell to use for command execution (default: `/bin/bash`, but could be `/bin/sh`, `/bin/zsh`, etc.)
- [ ] **Session management** — Persistent shell sessions that survive WebSocket reconnection (like `tmux`/`screen` on the server side)
- [x] **Delete endpoint** — `DELETE /file?path=...` to delete files and directories
- [x] **Rename endpoint** — `PATCH /file?path=...&new_name=...` to rename files and directories


---

## ⌨️ CLI
- [x] multiple server profiles stored in `~/.tunnel-ssh.json` with host/port/token
- [x] support command with sudo
- [x] **Batch mode** — `tunnel exec <server> --script commands.txt` to run multiple commands from a file
- [x] **Pipe support** — `cat local.sql | tunnel exec prod -` (read stdin and send as command input)

---

## 🖼️ Desktop UI (Flet)

- [ ] **File upload via drag-and-drop** — Drag local files onto the file panel to upload them and ctrl+c ctrl +v to copy file or upload one
- [ ] **Save-as dialog for downloads** — Use Flet's `FilePicker` to let the user choose where to save downloaded files
- [x] **File context menu** — Right-click → Download, Delete, Rename, Copy Path, copy file
- [ ] **Text file preview pane** — Click a file to preview its contents in a third panel (syntax-highlighted)
- [ ] **Multi-server tabs** — Connect to multiple servers simultaneously in separate tabs
- [x] **Breadcrumb navigation** — Clickable path segments instead of just a text label
- [ ] **Search / filter bar** — Filter the file list by name pattern
- [ ] **Terminal tabs** — Multiple terminal sessions side-by-side or in tabs
- [ ] **Persistent command history** — Save history to disk across sessions (like `~/.bash_history`)
- [ ] **Theme switcher** — Light / dark / system theme toggle
- [x] **Connection status indicator** — Green/red dot showing whether the server is reachable
- [ ] **Auto-reconnect** — Automatically retry the WebSocket connection if it drops
- [x] **Keyboard shortcuts** — `Ctrl+L` clear terminal, `Ctrl+R` refresh files, `Ctrl+Enter` run command
- [x] **Load profile from config** — Dropdown selector to pick from `~/.tunnel-ssh.json` profiles

---

## 📦 Packaging & Distribution

- [ ] **Standalone executables** — Build with `PyInstaller` or `Nuitka` for single-binary distribution (no Python required on client)
- [ ] **CLI installer** — `pip install tunnel-ssh` to get the CLI tool globally available
- [ ] **Docker image** — `Dockerfile` for the server component (`docker run -p 222:222 tunnel-ssh-server`)
- [ ] Build server for rocky linux even on widnwos using docker

---

## 🧪 Testing & Quality

- [ ] **Unit tests** — `pytest` suite for shared models, config loading, server endpoints, CLI commands
- [ ] **Integration tests** — Spin up server in a fixture, run CLI commands against it, assert output

---

## 📖 Documentation

- [ ] **API docs (Swagger)** — Ensure FastAPI's auto-generated `/docs` page is polished with examples
- [ ] **Man page** — Generate a man page from Typer's help output
- [ ] **Architecture diagram** — Visual showing server ↔ CLI/UI communication flow
- [ ] **Contributing guide** — `CONTRIBUTING.md` with dev setup, coding style, PR process
- [ ] **Changelog** — `CHANGELOG.md` following Keep a Changelog format

---