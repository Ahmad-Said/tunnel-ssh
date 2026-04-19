"""Pydantic models shared across server, CLI, and UI.

Every data structure that crosses the HTTP / WebSocket boundary is defined here
so that server, CLI, and UI always agree on the schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── File Management ──────────────────────────────────────────────────────────

class FileItem(BaseModel):
    """A single entry (file or directory) returned by the file-listing endpoint."""

    name: str
    is_dir: bool
    size: int | None = None
    modified: float | None = None  # epoch seconds
    permissions: str | None = None  # e.g. "rwxr-xr-x"


class DirectoryListing(BaseModel):
    """Response for ``GET /files`` — the contents of a directory."""

    path: str
    items: list[FileItem] = Field(default_factory=list)


class FilePreview(BaseModel):
    """Response for ``GET /file/preview`` — text content of a file."""

    path: str
    content: str
    size: int
    truncated: bool = False


# ── Command Execution ────────────────────────────────────────────────────────

class CommandPayload(BaseModel):
    """WebSocket message *sent by the client* to request command execution."""

    command: str
    cwd: str | None = None
    user_id: str | None = None


class CommandOutput(BaseModel):
    """WebSocket message *sent by the server* with execution output.

    ``stream`` is one of:

    * ``"stdout"``  — a chunk of standard output
    * ``"stderr"``  — a chunk of standard error
    * ``"exit"``    — the process has exited; ``data`` contains the return code
    * ``"prompt"``  — the process requires interactive input (e.g. sudo password)
    * ``"warning"`` — a non-fatal warning (e.g. cwd fallback)
    """

    stream: Literal["stdout", "stderr", "exit", "prompt", "warning"]
    data: str


class StdinInput(BaseModel):
    """WebSocket message *sent by the client* to write data to a running process's stdin.

    Typically used to supply a sudo password after the server sends a ``prompt`` message.
    """

    stdin: str


