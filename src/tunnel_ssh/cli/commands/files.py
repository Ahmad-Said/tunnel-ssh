"""File-management CLI commands: ``ls``, ``get``, ``put``, ``rm``, ``mv``, ``cat``."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer

from tunnel_ssh.cli.http_client import api_url, handle_connect_error, handle_http_error
from tunnel_ssh.shared.config import ServerProfile, resolve_server
from tunnel_ssh.shared.http import auth_headers
from tunnel_ssh.shared.models import DirectoryListing


def _resolve_or_exit(server: str | None) -> ServerProfile:
    """Resolve server or exit with helpful message."""
    try:
        return resolve_server(server)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    """Register all file-management commands on *app*."""

    # ── ls ────────────────────────────────────────────────────────────────

    @app.command(name="ls")
    def ls(
        path: Annotated[str, typer.Argument(help="Remote directory path.")] = "/",
        server: Annotated[str | None, typer.Option("--server", "-s", help="Server name or hostname/IP. Uses current context if omitted.")] = None,
        port: Annotated[int | None, typer.Option("--port", "-p")] = None,
        token: Annotated[str | None, typer.Option("--token", "-t")] = None,
        long: Annotated[bool, typer.Option("--long", "-l", help="Long format with size and permissions.")] = False,
    ) -> None:
        """List files in a remote directory."""
        profile = _resolve_or_exit(server)
        host, p, tok = profile.host, port or profile.port, token or profile.token

        url = api_url(host, p, "/files")
        try:
            resp = httpx.get(url, params={"path": path}, headers=auth_headers(tok), timeout=10)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            handle_http_error(exc)
        except httpx.ConnectError as exc:
            handle_connect_error(exc)

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

    # ── get ───────────────────────────────────────────────────────────────

    @app.command(name="get")
    def get(
        remote_path: Annotated[str, typer.Argument(help="Remote file path to download.")],
        local_path: Annotated[str | None, typer.Argument(help="Local destination (default: current dir).")] = None,
        server: Annotated[str | None, typer.Option("--server", "-s", help="Server name or hostname/IP. Uses current context if omitted.")] = None,
        port: Annotated[int | None, typer.Option("--port", "-p")] = None,
        token: Annotated[str | None, typer.Option("--token", "-t")] = None,
    ) -> None:
        """Download a file from the remote server."""
        profile = _resolve_or_exit(server)
        host, p, tok = profile.host, port or profile.port, token or profile.token

        url = api_url(host, p, "/file")
        try:
            with httpx.stream("GET", url, params={"path": remote_path}, headers=auth_headers(tok), timeout=30) as resp:
                resp.raise_for_status()

                if local_path:
                    dest = Path(local_path)
                    if dest.is_dir():
                        dest = dest / Path(remote_path).name
                else:
                    dest = Path(Path(remote_path).name)

                total = 0
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                        f.write(chunk)
                        total += len(chunk)

                typer.echo(f"Downloaded {dest} ({total:,} bytes)")

        except httpx.HTTPStatusError as exc:
            handle_http_error(exc)
        except httpx.ConnectError as exc:
            handle_connect_error(exc)

    # ── put ───────────────────────────────────────────────────────────────

    @app.command(name="put")
    def put(
        local_path: Annotated[str, typer.Argument(help="Local file to upload.")],
        remote_dir: Annotated[str, typer.Argument(help="Remote directory to upload into.")],
        server: Annotated[str | None, typer.Option("--server", "-s", help="Server name or hostname/IP. Uses current context if omitted.")] = None,
        port: Annotated[int | None, typer.Option("--port", "-p")] = None,
        token: Annotated[str | None, typer.Option("--token", "-t")] = None,
    ) -> None:
        """Upload a local file to the remote server."""
        profile = _resolve_or_exit(server)
        host, p, tok = profile.host, port or profile.port, token or profile.token

        src = Path(local_path)
        if not src.is_file():
            typer.echo(f"Local file not found: {src}", err=True)
            raise typer.Exit(code=1)

        url = api_url(host, p, "/file")
        try:
            with open(src, "rb") as f:
                resp = httpx.post(
                    url,
                    params={"path": remote_dir},
                    files={"file": (src.name, f)},
                    headers=auth_headers(tok),
                    timeout=60,
                )
                resp.raise_for_status()

            data = resp.json()
            typer.echo(f"Uploaded → {data['path']} ({data['size']:,} bytes)")

        except httpx.HTTPStatusError as exc:
            handle_http_error(exc)
        except httpx.ConnectError as exc:
            handle_connect_error(exc)

    # ── rm ────────────────────────────────────────────────────────────────

    @app.command(name="rm")
    def rm(
        remote_path: Annotated[str, typer.Argument(help="Remote file or directory to delete.")],
        server: Annotated[str | None, typer.Option("--server", "-s", help="Server name or hostname/IP. Uses current context if omitted.")] = None,
        port: Annotated[int | None, typer.Option("--port", "-p")] = None,
        token: Annotated[str | None, typer.Option("--token", "-t")] = None,
        force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation prompt.")] = False,
    ) -> None:
        """Delete a file or directory on the remote server."""
        profile = _resolve_or_exit(server)
        host, p, tok = profile.host, port or profile.port, token or profile.token

        if not force:
            confirm = typer.confirm(f"Delete '{remote_path}' on {host}:{p}?")
            if not confirm:
                raise typer.Abort()

        url = api_url(host, p, "/file")
        try:
            resp = httpx.delete(url, params={"path": remote_path}, headers=auth_headers(tok), timeout=10)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            handle_http_error(exc)
        except httpx.ConnectError as exc:
            handle_connect_error(exc)

        typer.echo(f"Deleted: {remote_path}")

    # ── mv ────────────────────────────────────────────────────────────────

    @app.command(name="mv")
    def mv(
        remote_path: Annotated[str, typer.Argument(help="Remote file or directory to rename.")],
        new_name: Annotated[str, typer.Argument(help="New name (filename only, not a path).")],
        server: Annotated[str | None, typer.Option("--server", "-s", help="Server name or hostname/IP. Uses current context if omitted.")] = None,
        port: Annotated[int | None, typer.Option("--port", "-p")] = None,
        token: Annotated[str | None, typer.Option("--token", "-t")] = None,
    ) -> None:
        """Rename a file or directory on the remote server."""
        profile = _resolve_or_exit(server)
        host, p, tok = profile.host, port or profile.port, token or profile.token

        url = api_url(host, p, "/file")
        try:
            resp = httpx.patch(
                url,
                params={"path": remote_path, "new_name": new_name},
                headers=auth_headers(tok),
                timeout=10,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            handle_http_error(exc)
        except httpx.ConnectError as exc:
            handle_connect_error(exc)

        data = resp.json()
        typer.echo(f"Renamed: {data.get('old_path')} → {data.get('new_path')}")

    # ── cat ───────────────────────────────────────────────────────────────

    @app.command(name="cat")
    def cat(
        remote_path: Annotated[str, typer.Argument(help="Remote file to preview.")],
        server: Annotated[str | None, typer.Option("--server", "-s", help="Server name or hostname/IP. Uses current context if omitted.")] = None,
        port: Annotated[int | None, typer.Option("--port", "-p")] = None,
        token: Annotated[str | None, typer.Option("--token", "-t")] = None,
        max_size: Annotated[int, typer.Option("--max-size", help="Max bytes to read.")] = 512_000,
    ) -> None:
        """Preview the text content of a remote file."""
        profile = _resolve_or_exit(server)
        host, p, tok = profile.host, port or profile.port, token or profile.token

        url = api_url(host, p, "/file/preview")
        try:
            resp = httpx.get(
                url,
                params={"path": remote_path, "max_size": max_size},
                headers=auth_headers(tok),
                timeout=15,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            handle_http_error(exc)
        except httpx.ConnectError as exc:
            handle_connect_error(exc)

        data = resp.json()
        sys.stdout.write(data["content"])
        if data.get("truncated"):
            typer.echo(f"\n… [truncated at {max_size:,} bytes, total {data['size']:,} bytes]", err=True)

