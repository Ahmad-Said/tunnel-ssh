"""tunnel-ssh CLI – run commands and manage files on a remote tunnel-ssh server.

Usage::

    tunnel exec myserver ls -la /home
    tunnel exec 192.168.1.50 cat /etc/hostname
    tunnel exec prod --script commands.txt          # batch mode
    echo "ls -la" | tunnel exec prod -              # stdin pipe
    tunnel ls   myserver /var/log
    tunnel get  myserver /etc/hostname ./hostname.local
    tunnel put  myserver ./backup.tar.gz /tmp
    tunnel config add prod --host 10.0.0.5 --port 2222 --token s3cret
    tunnel config list
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Optional

import httpx
import typer
import websockets

from shared.config import (
    DEFAULT_PORT,
    TunnelConfig,
    load_config,
    resolve_server,
    save_config,
)
from shared.models import CommandOutput, CommandPayload, DirectoryListing

app = typer.Typer(
    name="tunnel",
    help="Remote execution and file management via tunnel-ssh.",
    add_completion=False,
)

# ── Sub-apps ─────────────────────────────────────────────────────────────────

config_app = typer.Typer(name="config", help="Manage saved server profiles (~/.tunnel-ssh.json).")
app.add_typer(config_app, name="config")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _auth_headers(token: str | None) -> dict[str, str]:
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}




# ── exec ─────────────────────────────────────────────────────────────────────

@app.command()
def exec(
    server: Annotated[str, typer.Argument(help="Server name (from config) or hostname/IP.")],
    command: Annotated[Optional[list[str]], typer.Argument(help="The command (and arguments) to execute remotely.")] = None,
    port: Annotated[Optional[int], typer.Option("--port", "-p", help="Override server port.")] = None,
    cwd: Annotated[Optional[str], typer.Option("--cwd", "-C", help="Working directory on the remote machine.")] = None,
    token: Annotated[Optional[str], typer.Option("--token", "-t", help="Override auth token.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="Connection timeout in seconds.")] = 10.0,
    script: Annotated[Optional[str], typer.Option("--script", "-S", help="Path to a file with commands to execute (one per line).")] = None,
    sudo: Annotated[bool, typer.Option("--sudo", help="Prepend 'sudo' to each command.")] = False,
):
    """Execute COMMAND on SERVER and stream the output to this terminal.

    Supports --script to run multiple commands from a file, stdin pipe
    (pass '-' as the command or pipe into tunnel exec), and --sudo.
    """
    profile = resolve_server(server)
    host = profile.host
    p = port if port is not None else profile.port
    tok = token or profile.token

    # ── Collect commands to run ───────────────────────────────────────────
    commands_to_run: list[str] = []

    if script:
        # Batch mode: read commands from a file
        script_path = Path(script)
        if not script_path.is_file():
            typer.echo(f"Script file not found: {script_path}", err=True)
            raise typer.Exit(code=1)
        for line in script_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                commands_to_run.append(stripped)
        if not commands_to_run:
            typer.echo("Script file is empty or contains only comments.", err=True)
            raise typer.Exit(code=1)
    elif command and command != ["-"]:
        # Normal single-command mode
        full_command = " ".join(command)
        if not full_command.strip():
            typer.echo("No command provided.", err=True)
            raise typer.Exit(code=1)
        commands_to_run.append(full_command)
    elif not sys.stdin.isatty() or (command == ["-"]):
        # Pipe / stdin mode: read command(s) from stdin
        stdin_text = sys.stdin.read().strip()
        if not stdin_text:
            typer.echo("No input received from stdin.", err=True)
            raise typer.Exit(code=1)
        for line in stdin_text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                commands_to_run.append(stripped)
    else:
        typer.echo("No command provided. Pass a command, use --script, or pipe via stdin.", err=True)
        raise typer.Exit(code=1)

    # ── Execute ──────────────────────────────────────────────────────────
    # Apply sudo prefix if requested
    if sudo:
        commands_to_run = [f"sudo {cmd}" for cmd in commands_to_run]

    worst_exit = 0
    try:
        for cmd in commands_to_run:
            if len(commands_to_run) > 1:
                typer.echo(f"▶ {cmd}", err=True)
            exit_code = asyncio.run(_execute(host, p, cmd, cwd, tok, timeout))
            if exit_code != 0:
                worst_exit = exit_code
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.", err=True)
        worst_exit = 130

    raise typer.Exit(code=worst_exit)


async def _execute(server: str, port: int, command: str, cwd: str | None, token: str | None, timeout: float) -> int:
    """Connect to the remote server, send the command, print streamed output."""
    uri = f"ws://{server}:{port}/ws/execute"
    if token:
        uri += f"?token={token}"
    payload = CommandPayload(command=command, cwd=cwd)

    try:
        async with websockets.connect(uri, open_timeout=timeout) as ws:
            await ws.send(payload.model_dump_json())

            async for raw in ws:
                msg = CommandOutput.model_validate_json(raw)
                if msg.stream == "stdout":
                    sys.stdout.write(msg.data)
                    sys.stdout.flush()
                elif msg.stream == "stderr":
                    sys.stderr.write(msg.data)
                    sys.stderr.flush()
                elif msg.stream == "exit":
                    return int(msg.data)
    except websockets.exceptions.ConnectionClosedError:
        typer.echo("Connection closed unexpectedly.", err=True)
        return 1
    except TimeoutError:
        typer.echo(f"Connection timed out after {timeout}s.", err=True)
        return 1
    except OSError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        return 1

    return 0


# ── ls (list remote directory) ───────────────────────────────────────────────

@app.command(name="ls")
def ls(
    server: Annotated[str, typer.Argument(help="Server name or hostname/IP.")],
    path: Annotated[str, typer.Argument(help="Remote directory path.")] = "/",
    port: Annotated[Optional[int], typer.Option("--port", "-p")] = None,
    token: Annotated[Optional[str], typer.Option("--token", "-t")] = None,
    long: Annotated[bool, typer.Option("--long", "-l", help="Long format with size and permissions.")] = False,
):
    """List files in a remote directory."""
    profile = resolve_server(server)
    host = profile.host
    p = port if port is not None else profile.port
    tok = token or profile.token

    url = f"http://{host}:{p}/files"
    try:
        resp = httpx.get(url, params={"path": path}, headers=_auth_headers(tok), timeout=10)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1)
    except httpx.ConnectError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        raise typer.Exit(code=1)

    listing = DirectoryListing.model_validate(resp.json())
    typer.echo(f"  {listing.path}\n")

    for item in listing.items:
        if long:
            perms = item.permissions or "---------"
            size = f"{item.size:>10,}" if item.size is not None else "       DIR"
            name = f"{item.name}/" if item.is_dir else item.name
            typer.echo(f"  {perms}  {size}  {name}")
        else:
            suffix = "/" if item.is_dir else ""
            typer.echo(f"  {item.name}{suffix}")


# ── get (download remote file) ──────────────────────────────────────────────

@app.command(name="get")
def get(
    server: Annotated[str, typer.Argument(help="Server name or hostname/IP.")],
    remote_path: Annotated[str, typer.Argument(help="Remote file path to download.")],
    local_path: Annotated[Optional[str], typer.Argument(help="Local destination (default: current dir).")] = None,
    port: Annotated[Optional[int], typer.Option("--port", "-p")] = None,
    token: Annotated[Optional[str], typer.Option("--token", "-t")] = None,
):
    """Download a file from the remote server."""
    profile = resolve_server(server)
    host = profile.host
    p = port if port is not None else profile.port
    tok = token or profile.token

    url = f"http://{host}:{p}/file"
    try:
        with httpx.stream("GET", url, params={"path": remote_path}, headers=_auth_headers(tok), timeout=30) as resp:
            resp.raise_for_status()

            # Determine local filename
            if local_path:
                dest = Path(local_path)
                if dest.is_dir():
                    filename = Path(remote_path).name
                    dest = dest / filename
            else:
                dest = Path(Path(remote_path).name)

            total = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
                    total += len(chunk)

            typer.echo(f"Downloaded {dest} ({total:,} bytes)")

    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1)
    except httpx.ConnectError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        raise typer.Exit(code=1)


# ── put (upload local file) ─────────────────────────────────────────────────

@app.command(name="put")
def put(
    server: Annotated[str, typer.Argument(help="Server name or hostname/IP.")],
    local_path: Annotated[str, typer.Argument(help="Local file to upload.")],
    remote_dir: Annotated[str, typer.Argument(help="Remote directory to upload into.")],
    port: Annotated[Optional[int], typer.Option("--port", "-p")] = None,
    token: Annotated[Optional[str], typer.Option("--token", "-t")] = None,
):
    """Upload a local file to the remote server."""
    profile = resolve_server(server)
    host = profile.host
    p = port if port is not None else profile.port
    tok = token or profile.token

    src = Path(local_path)
    if not src.is_file():
        typer.echo(f"Local file not found: {src}", err=True)
        raise typer.Exit(code=1)

    url = f"http://{host}:{p}/file"
    try:
        with open(src, "rb") as f:
            resp = httpx.post(
                url,
                params={"path": remote_dir},
                files={"file": (src.name, f)},
                headers=_auth_headers(tok),
                timeout=60,
            )
            resp.raise_for_status()

        data = resp.json()
        typer.echo(f"Uploaded → {data['path']} ({data['size']:,} bytes)")

    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1)
    except httpx.ConnectError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        raise typer.Exit(code=1)


# ── config add ───────────────────────────────────────────────────────────────

@app.command(name="rm")
def rm(
    server: Annotated[str, typer.Argument(help="Server name or hostname/IP.")],
    remote_path: Annotated[str, typer.Argument(help="Remote file or directory to delete.")],
    port: Annotated[Optional[int], typer.Option("--port", "-p")] = None,
    token: Annotated[Optional[str], typer.Option("--token", "-t")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation prompt.")] = False,
):
    """Delete a file or directory on the remote server."""
    profile = resolve_server(server)
    host = profile.host
    p = port if port is not None else profile.port
    tok = token or profile.token

    if not force:
        confirm = typer.confirm(f"Delete '{remote_path}' on {host}:{p}?")
        if not confirm:
            raise typer.Abort()

    url = f"http://{host}:{p}/file"
    try:
        resp = httpx.delete(url, params={"path": remote_path}, headers=_auth_headers(tok), timeout=10)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1)
    except httpx.ConnectError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Deleted: {remote_path}")


@app.command(name="mv")
def mv(
    server: Annotated[str, typer.Argument(help="Server name or hostname/IP.")],
    remote_path: Annotated[str, typer.Argument(help="Remote file or directory to rename.")],
    new_name: Annotated[str, typer.Argument(help="New name (filename only, not a path).")],
    port: Annotated[Optional[int], typer.Option("--port", "-p")] = None,
    token: Annotated[Optional[str], typer.Option("--token", "-t")] = None,
):
    """Rename a file or directory on the remote server."""
    profile = resolve_server(server)
    host = profile.host
    p = port if port is not None else profile.port
    tok = token or profile.token

    url = f"http://{host}:{p}/file"
    try:
        resp = httpx.patch(url, params={"path": remote_path, "new_name": new_name}, headers=_auth_headers(tok), timeout=10)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1)
    except httpx.ConnectError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    typer.echo(f"Renamed: {data.get('old_path')} → {data.get('new_path')}")


@app.command(name="cat")
def cat(
    server: Annotated[str, typer.Argument(help="Server name or hostname/IP.")],
    remote_path: Annotated[str, typer.Argument(help="Remote file to preview.")],
    port: Annotated[Optional[int], typer.Option("--port", "-p")] = None,
    token: Annotated[Optional[str], typer.Option("--token", "-t")] = None,
    max_size: Annotated[int, typer.Option("--max-size", help="Max bytes to read.")] = 512_000,
):
    """Preview the text content of a remote file."""
    profile = resolve_server(server)
    host = profile.host
    p = port if port is not None else profile.port
    tok = token or profile.token

    url = f"http://{host}:{p}/file/preview"
    try:
        resp = httpx.get(url, params={"path": remote_path, "max_size": max_size}, headers=_auth_headers(tok), timeout=15)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1)
    except httpx.ConnectError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    sys.stdout.write(data["content"])
    if data.get("truncated"):
        typer.echo(f"\n… [truncated at {max_size:,} bytes, total {data['size']:,} bytes]", err=True)


# ── config add ───────────────────────────────────────────────────────────────

@config_app.command(name="add")
def config_add(
    name: Annotated[str, typer.Argument(help="Profile name (e.g. 'prod', 'server1').")],
    host: Annotated[str, typer.Option("--host", "-H", help="Hostname or IP.")] = "localhost",
    port: Annotated[int, typer.Option("--port", "-p", help="Port.")] = DEFAULT_PORT,
    token: Annotated[Optional[str], typer.Option("--token", "-t", help="Auth token.")] = None,
):
    """Save a named server profile."""
    from shared.config import ServerProfile

    cfg = load_config()
    cfg.servers[name] = ServerProfile(host=host, port=port, token=token)
    save_config(cfg)
    typer.echo(f"Saved profile '{name}' → {host}:{port}")


# ── config list ──────────────────────────────────────────────────────────────

@config_app.command(name="list")
def config_list():
    """Show all saved server profiles."""
    cfg = load_config()
    if not cfg.servers:
        typer.echo("No profiles configured. Use: tunnel config add <name> --host <host>")
        return

    for name, profile in cfg.servers.items():
        auth = " 🔒" if profile.token else ""
        typer.echo(f"  {name:20s} {profile.host}:{profile.port}{auth}")


# ── config remove ────────────────────────────────────────────────────────────

@config_app.command(name="remove")
def config_remove(
    name: Annotated[str, typer.Argument(help="Profile name to remove.")],
):
    """Remove a saved server profile."""
    cfg = load_config()
    if name not in cfg.servers:
        typer.echo(f"Profile '{name}' not found.", err=True)
        raise typer.Exit(code=1)

    del cfg.servers[name]
    save_config(cfg)
    typer.echo(f"Removed profile '{name}'.")


# ── Entrypoint ───────────────────────────────────────────────────────────────

def run():
    """Setuptools entrypoint."""
    app()


if __name__ == "__main__":
    run()

