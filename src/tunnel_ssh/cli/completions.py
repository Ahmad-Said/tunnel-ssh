"""Remote path tab-completion for CLI arguments.

Queries the tunnel-ssh server's ``/files`` endpoint to provide live
autocompletion of remote file and directory paths when the user presses Tab.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

import httpx

from tunnel_ssh.cli.http_client import api_url
from tunnel_ssh.shared.config import resolve_server
from tunnel_ssh.shared.http import auth_headers
from tunnel_ssh.shared.models import DirectoryListing

logger = logging.getLogger("tunnel-ssh.completions")


def complete_remote_path(incomplete: str) -> list[str]:
    """Return remote path suggestions that match *incomplete*.

    Called by Typer/Click's shell-completion machinery.  Silently returns an
    empty list on any error (network failure, no context configured, etc.) so
    that the shell simply shows no suggestions rather than crashing.
    """
    try:
        profile = resolve_server(None)
    except Exception:
        return []

    host, port, tok = profile.host, profile.port, profile.token

    # Determine which directory to list.
    # If incomplete ends with '/' treat it as the directory itself,
    # otherwise list its parent and filter by the basename prefix.
    if not incomplete or incomplete == "/":
        parent = "/"
        prefix = ""
    elif incomplete.endswith("/"):
        parent = incomplete
        prefix = ""
    else:
        p = PurePosixPath(incomplete)
        parent = str(p.parent)
        prefix = p.name

    url = api_url(host, port, "/files")
    try:
        resp = httpx.get(
            url,
            params={"path": parent},
            headers=auth_headers(tok),
            timeout=5,
        )
        resp.raise_for_status()
    except Exception:
        return []

    listing = DirectoryListing.model_validate(resp.json())

    results: list[str] = []
    for item in listing.items:
        if prefix and not item.name.lower().startswith(prefix.lower()):
            continue
        # Build the full path for the suggestion
        if parent == "/":
            full = f"/{item.name}"
        else:
            full = f"{parent.rstrip('/')}/{item.name}"
        if item.is_dir:
            full += "/"
        results.append(full)

    return results


