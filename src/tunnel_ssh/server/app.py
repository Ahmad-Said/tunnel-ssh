"""FastAPI application factory.

Using a factory function (``create_app``) instead of a module-level ``app``
makes the server testable — you can create isolated app instances in tests
without worrying about shared global state.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from tunnel_ssh._version import __version__
from tunnel_ssh.server.routes import register_routes


def create_app() -> FastAPI:
    """Build and return a fully configured FastAPI application."""
    application = FastAPI(
        title="tunnel-ssh server",
        version=__version__,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_routes(application)

    return application


# Default application instance — used by the CLI entrypoint and uvicorn.
app = create_app()

