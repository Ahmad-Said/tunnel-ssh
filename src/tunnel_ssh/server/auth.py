"""Authentication dependency for FastAPI routes.

Reads the token from ``ServerSettings`` and validates incoming requests.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from tunnel_ssh.server.settings import settings


async def verify_token(request: Request) -> None:
    """Raise 401 if a token is configured and the request doesn't carry it.

    Used as a FastAPI dependency on all protected endpoints.
    """
    if not settings.auth_enabled:
        return  # auth disabled

    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {settings.auth_token}":
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing token",
    )

