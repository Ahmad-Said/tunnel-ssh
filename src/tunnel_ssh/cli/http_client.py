"""HTTP and WebSocket client helpers for the CLI.

Encapsulates the low-level network logic so that individual command modules
stay focused on argument parsing and output formatting.
"""

from __future__ import annotations

import getpass
import logging
import sys

import httpx
import typer
import websockets

from tunnel_ssh.shared.http import ws_url
from tunnel_ssh.shared.models import CommandOutput, CommandPayload, StdinInput

logger = logging.getLogger("tunnel-ssh.cli")


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def api_url(host: str, port: int, path: str) -> str:
    """Build a full HTTP URL for a server endpoint."""
    return f"http://{host}:{port}{path}"


def handle_http_error(exc: httpx.HTTPStatusError) -> None:
    """Print a standardised HTTP error and exit."""
    typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
    raise typer.Exit(code=1)


def handle_connect_error(exc: httpx.ConnectError) -> None:
    """Print a standardised connection error and exit."""
    typer.echo(f"Connection failed: {exc}", err=True)
    raise typer.Exit(code=1)


# ── WebSocket execution ─────────────────────────────────────────────────────

async def execute_remote(
    host: str,
    port: int,
    command: str,
    cwd: str | None,
    token: str | None,
    timeout: float,
) -> int:
    """Connect to the remote server, send *command*, print streamed output.

    Returns the remote process exit code (or 1 on connection failure).
    """
    uri = ws_url(host, port, token)
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
                elif msg.stream == "prompt":
                    # Server is requesting interactive input (e.g. sudo password).
                    password = getpass.getpass(msg.data)
                    await ws.send(StdinInput(stdin=password).model_dump_json())
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

