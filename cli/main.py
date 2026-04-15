"""tunnel-ssh CLI – run commands on a remote tunnel-ssh server.

Usage::

    tunnel myserver ls -la /home
    tunnel 192.168.1.50 cat /etc/hostname
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Annotated, Optional

import typer
import websockets

from shared.models import CommandOutput, CommandPayload

app = typer.Typer(
    name="tunnel",
    help="Execute a shell command on a remote tunnel-ssh server and stream the output.",
    add_completion=False,
)

DEFAULT_PORT = int(os.getenv("TUNNEL_SSH_PORT", "222"))


async def _execute(server: str, port: int, command: str, cwd: str | None) -> int:
    """Connect to the remote server, send the command, print streamed output."""
    uri = f"ws://{server}:{port}/ws/execute"
    payload = CommandPayload(command=command, cwd=cwd)

    try:
        async with websockets.connect(uri) as ws:
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
    except OSError as exc:
        typer.echo(f"Connection failed: {exc}", err=True)
        return 1

    return 0


@app.command()
def tunnel(
    server: Annotated[str, typer.Argument(help="Hostname or IP of the tunnel-ssh server.")],
    command: Annotated[list[str], typer.Argument(help="The command (and arguments) to execute remotely.")],
    port: Annotated[int, typer.Option("--port", "-p", help="Server port.")] = DEFAULT_PORT,
    cwd: Annotated[Optional[str], typer.Option("--cwd", "-C", help="Working directory on the remote machine.")] = None,
):
    """Execute COMMAND on SERVER and stream the output to this terminal."""
    full_command = " ".join(command)
    if not full_command.strip():
        typer.echo("No command provided.", err=True)
        raise typer.Exit(code=1)

    try:
        exit_code = asyncio.run(_execute(server, port, full_command, cwd))
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.", err=True)
        exit_code = 130

    raise typer.Exit(code=exit_code)


def run():
    """Setuptools entrypoint."""
    app()


if __name__ == "__main__":
    run()

