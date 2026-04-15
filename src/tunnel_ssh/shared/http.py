"""Shared HTTP utilities used by both CLI and UI.

Centralises helpers that would otherwise be duplicated across client components.
"""

from __future__ import annotations


def auth_headers(token: str | None) -> dict[str, str]:
    """Return an ``Authorization: Bearer`` header dict, or empty if *token* is ``None``."""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def base_url(host: str, port: int) -> str:
    """Build the HTTP base URL for a tunnel-ssh server."""
    return f"http://{host}:{port}"


def ws_url(host: str, port: int, token: str | None = None) -> str:
    """Build the WebSocket URL for the ``/ws/execute`` endpoint."""
    url = f"ws://{host}:{port}/ws/execute"
    if token:
        url += f"?token={token}"
    return url

