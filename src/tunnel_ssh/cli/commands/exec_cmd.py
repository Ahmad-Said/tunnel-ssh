"""``tunnel exec`` — execute remote commands with streaming output.

Supports single commands, ``--script`` batch mode, stdin pipe, and ``--sudo``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer

from tunnel_ssh.cli.http_client import execute_remote
from tunnel_ssh.shared.config import resolve_server


def register(app: typer.Typer) -> None:
    """Register the ``exec`` command on *app*."""

    @app.command()
    def exec(
        server: Annotated[str | None, typer.Argument(help="Server name (from config) or hostname/IP. Uses current context if omitted.")] = None,
        command: Annotated[list[str] | None, typer.Argument(help="The command (and arguments) to execute remotely.")] = None,
        port: Annotated[int | None, typer.Option("--port", "-p", help="Override server port.")] = None,
        cwd: Annotated[str | None, typer.Option("--cwd", "-C", help="Working directory on the remote machine.")] = None,
        token: Annotated[str | None, typer.Option("--token", "-t", help="Override auth token.")] = None,
        timeout: Annotated[float, typer.Option("--timeout", help="Connection timeout in seconds.")] = 10.0,
        script: Annotated[str | None, typer.Option("--script", "-S", help="Path to a file with commands (one per line).")] = None,
        sudo: Annotated[bool, typer.Option("--sudo", help="Prepend 'sudo' to each command.")] = False,
    ) -> None:
        """Execute COMMAND on SERVER and stream the output to this terminal."""
        try:
            profile = resolve_server(server)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1)
        host = profile.host
        p = port if port is not None else profile.port
        tok = token or profile.token

        # ── Collect commands ──────────────────────────────────────────────
        commands_to_run: list[str] = _collect_commands(command, script)

        # Apply sudo prefix
        if sudo:
            commands_to_run = [f"sudo {cmd}" for cmd in commands_to_run]

        # ── Execute ──────────────────────────────────────────────────────
        worst_exit = 0
        try:
            for cmd in commands_to_run:
                if len(commands_to_run) > 1:
                    typer.echo(f"▶ {cmd}", err=True)
                exit_code = asyncio.run(execute_remote(host, p, cmd, cwd, tok, timeout))
                if exit_code != 0:
                    worst_exit = exit_code
        except KeyboardInterrupt:
            typer.echo("\nInterrupted.", err=True)
            worst_exit = 130

        raise typer.Exit(code=worst_exit)


def _collect_commands(
    command: list[str] | None,
    script: str | None,
) -> list[str]:
    """Parse command input from arguments, script file, or stdin."""
    commands: list[str] = []

    if script:
        script_path = Path(script)
        if not script_path.is_file():
            typer.echo(f"Script file not found: {script_path}", err=True)
            raise typer.Exit(code=1)
        for line in script_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                commands.append(stripped)
        if not commands:
            typer.echo("Script file is empty or contains only comments.", err=True)
            raise typer.Exit(code=1)

    elif command and command != ["-"]:
        full_command = " ".join(command)
        if not full_command.strip():
            typer.echo("No command provided.", err=True)
            raise typer.Exit(code=1)
        commands.append(full_command)

    elif not sys.stdin.isatty() or (command == ["-"]):
        stdin_text = sys.stdin.read().strip()
        if not stdin_text:
            typer.echo("No input received from stdin.", err=True)
            raise typer.Exit(code=1)
        for line in stdin_text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                commands.append(stripped)

    else:
        typer.echo("No command provided. Pass a command, use --script, or pipe via stdin.", err=True)
        raise typer.Exit(code=1)

    return commands

