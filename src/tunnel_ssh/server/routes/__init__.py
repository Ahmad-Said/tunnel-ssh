"""Server route registration.

Import and include all route modules into the FastAPI application.
"""

from __future__ import annotations

from fastapi import FastAPI

from tunnel_ssh.server.routes import files, health, websocket


def register_routes(app: FastAPI) -> None:
    """Include all route modules on *app*."""
    app.include_router(health.router)
    app.include_router(files.router)
    app.include_router(websocket.router)

