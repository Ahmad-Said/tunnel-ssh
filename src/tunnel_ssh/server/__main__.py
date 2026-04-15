"""CLI entrypoint for ``tunnel-server``.

Uses Typer to expose ``--host``, ``--port``, ``--token``, ``--shell``, and
``--log-level`` flags, then starts uvicorn with the FastAPI app.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated

import typer
import uvicorn

from tunnel_ssh.server.settings import settings
from tunnel_ssh.shared.config import DEFAULT_PORT, DEFAULT_TOKEN

logger = logging.getLogger("tunnel-ssh.server")

cli = typer.Typer(add_completion=False)


@cli.command()
def start(
    host: Annotated[str, typer.Option("--host", "-H", help="Bind address.")] = "0.0.0.0",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port.")] = DEFAULT_PORT,
    token: Annotated[
        str | None, typer.Option("--token", "-t", help="Auth token (or set TUNNEL_SSH_TOKEN env).")
    ] = DEFAULT_TOKEN,
    shell: Annotated[
        str, typer.Option("--shell", "-s", help="Shell executable for command execution.")
    ] = "/bin/bash",
    log_level: Annotated[str, typer.Option("--log-level", help="Logging level.")] = "info",
) -> None:
    """Start the tunnel-ssh API server."""
    # Propagate token to env for any sub-workers / reloads.
    if token:
        os.environ["TUNNEL_SSH_TOKEN"] = token

    settings.configure(token=token, shell=shell)

    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
    logger.info("Shell: %s", settings.shell_path)
    if settings.auth_enabled:
        logger.info("Auth enabled (token set)")
    else:
        logger.warning("Auth DISABLED — server is open to anyone who can reach it")

    # Import app here so the settings are already configured before routes load.
    from tunnel_ssh.server.app import app

    # Pass the app object directly so uvicorn does NOT re-import the module
    # (which would reset settings to their defaults).
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
    )


def run() -> None:
    """Setuptools console_scripts entrypoint."""
    cli()


if __name__ == "__main__":
    cli()

