"""Server-side helper utilities."""

from __future__ import annotations

import stat as stat_mod


def format_permissions(mode: int) -> str:
    """Convert a numeric file mode to a human-readable string like ``rwxr-xr-x``.

    Maps the nine standard POSIX permission bits to their ``rwx`` representation.
    """
    flags = (
        (stat_mod.S_IRUSR, "r"),
        (stat_mod.S_IWUSR, "w"),
        (stat_mod.S_IXUSR, "x"),
        (stat_mod.S_IRGRP, "r"),
        (stat_mod.S_IWGRP, "w"),
        (stat_mod.S_IXGRP, "x"),
        (stat_mod.S_IROTH, "r"),
        (stat_mod.S_IWOTH, "w"),
        (stat_mod.S_IXOTH, "x"),
    )
    return "".join(char if mode & bit else "-" for bit, char in flags)

