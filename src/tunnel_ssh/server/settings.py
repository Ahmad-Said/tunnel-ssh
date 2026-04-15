"""Runtime settings for the tunnel-ssh server.

Instead of scattered global variables, all mutable server configuration lives
in a single ``ServerSettings`` instance that is configured once at startup and
read by route handlers via import.
"""

from __future__ import annotations

import os


class ServerSettings:
    """Holds runtime configuration for the running server process."""

    __slots__ = ("auth_token", "shell_path")

    def __init__(self) -> None:
        self.auth_token: str | None = os.getenv("TUNNEL_SSH_TOKEN") or None
        self.shell_path: str = os.getenv("TUNNEL_SSH_SHELL", "/bin/bash")

    def configure(
        self,
        *,
        token: str | None = ...,  # type: ignore[assignment]
        shell: str | None = ...,  # type: ignore[assignment]
    ) -> None:
        """Update settings.  Pass explicit ``None`` to clear a value."""
        if token is not ...:
            self.auth_token = token or None
        if shell is not ...:
            self.shell_path = shell or self.shell_path

    @property
    def auth_enabled(self) -> bool:
        return self.auth_token is not None


# Module-level singleton — imported by route modules.
settings = ServerSettings()

