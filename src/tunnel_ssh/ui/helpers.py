"""Pure utility functions for the desktop UI.

These are stateless helpers that don't depend on Flet or network I/O,
making them easy to unit-test independently.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath


def human_size(nbytes: int | float) -> str:
    """Format *nbytes* as a human-readable size string (e.g. ``"4.2 MB"``)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def human_time(epoch: float) -> str:
    """Convert epoch seconds to a short human-readable timestamp."""
    dt = datetime.fromtimestamp(epoch, tz=UTC).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def parent_path(path: str) -> str:
    """Return the parent of *path*, handling both POSIX and Windows style."""
    if "\\" in path or (len(path) >= 2 and path[1] == ":"):
        return str(PureWindowsPath(path).parent)
    return str(PurePosixPath(path).parent)


def join_path(base: str, name: str) -> str:
    """Join *base* path and *name*, respecting platform style."""
    sep = "\\" if "\\" in base else "/"
    return f"{base.rstrip(sep)}{sep}{name}"


def is_root_path(path: str) -> bool:
    """Return ``True`` if *path* represents a filesystem root."""
    return path in ("/", "\\") or (len(path) <= 3 and path.endswith(":\\"))

