"""tunnel-ssh CLI — ``tunnel exec/ls/get/put/rm/mv/cat/config``.

This module builds the top-level Typer app and registers all sub-commands
from their dedicated modules.  The ``run()`` function is the setuptools
console_scripts entrypoint.
"""

from __future__ import annotations

import typer

from tunnel_ssh.cli.commands import config as config_cmd
from tunnel_ssh.cli.commands import exec_cmd
from tunnel_ssh.cli.commands import files as files_cmd

app = typer.Typer(
    name="tunnel",
    help="Remote execution and file management via tunnel-ssh.",
    add_completion=False,
)

# Register all command groups
exec_cmd.register(app)
files_cmd.register(app)
config_cmd.register(app)


def run() -> None:
    """Setuptools console_scripts entrypoint."""
    app()


if __name__ == "__main__":
    run()

