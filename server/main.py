"""tunnel-ssh API server – run on the *remote* machine (port 222 by default).

Endpoints
---------
GET    /health                       Health check.
GET    /files?path=<dir>             List directory contents.
GET    /file?path=<filepath>         Download a single file.
GET    /file/preview?path=<fp>       Preview text file contents (first N lines).
POST   /file                         Upload a file  (multipart: ``path`` + ``file``).
DELETE /file?path=<filepath>         Delete a file or directory.
PATCH  /file?path=<fp>&new_name=<n>  Rename a file or directory.
WS     /ws/execute                   Execute a shell command and stream output.

Authentication
--------------
Set ``TUNNEL_SSH_TOKEN`` (env-var or ``--token`` CLI arg) to enable bearer-token
auth.  When set, every HTTP request must include ``Authorization: Bearer <token>``
and every WebSocket connection must pass ``?token=<token>`` as a query parameter.
If no token is configured, authentication is disabled (open access).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import stat as stat_mod
from pathlib import Path
from typing import Annotated

import aiofiles
import typer as _typer
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware

from shared.config import DEFAULT_PORT, DEFAULT_TOKEN
from shared.models import CommandOutput, CommandPayload, DirectoryListing, FileItem, FilePreview

# ── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("tunnel-ssh.server")

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="tunnel-ssh server", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Runtime token – set via env var or start() CLI arg.
_auth_token: str | None = DEFAULT_TOKEN

# Shell executable used for command execution.
_shell_path: str = os.getenv("TUNNEL_SSH_SHELL", "/bin/bash")


def set_auth_token(token: str | None) -> None:
    global _auth_token
    _auth_token = token or None


def set_shell_path(shell: str) -> None:
    global _shell_path
    _shell_path = shell


# ── Auth dependency ──────────────────────────────────────────────────────────

async def _verify_token(request: Request) -> None:
    """Raise 401 if a token is configured and the request doesn't carry it."""
    if _auth_token is None:
        return  # auth disabled
    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {_auth_token}":
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_permissions(mode: int) -> str:
    """Convert a numeric file mode to a human-readable string like ``rwxr-xr-x``."""
    parts = []
    for who in (stat_mod.S_IRUSR, stat_mod.S_IWUSR, stat_mod.S_IXUSR,
                stat_mod.S_IRGRP, stat_mod.S_IWGRP, stat_mod.S_IXGRP,
                stat_mod.S_IROTH, stat_mod.S_IWOTH, stat_mod.S_IXOTH):
        parts.append("r" if who in (stat_mod.S_IRUSR, stat_mod.S_IRGRP, stat_mod.S_IROTH) and mode & who else
                      "w" if who in (stat_mod.S_IWUSR, stat_mod.S_IWGRP, stat_mod.S_IWOTH) and mode & who else
                      "x" if who in (stat_mod.S_IXUSR, stat_mod.S_IXGRP, stat_mod.S_IXOTH) and mode & who else
                      "-")
    return "".join(parts)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Simple liveness probe."""
    return {"status": "ok"}


# ── File management endpoints ────────────────────────────────────────────────

@app.get("/files", response_model=DirectoryListing, dependencies=[Depends(_verify_token)])
async def list_files(path: Annotated[str, Query()] = "/"):
    """Return the contents of *path* on the remote machine."""
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {target}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {target}")

    items: list[FileItem] = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                st = entry.stat()
                items.append(
                    FileItem(
                        name=entry.name,
                        is_dir=entry.is_dir(),
                        size=st.st_size if not entry.is_dir() else None,
                        modified=st.st_mtime,
                        permissions=_format_permissions(st.st_mode),
                    )
                )
            except PermissionError:
                items.append(FileItem(name=entry.name, is_dir=entry.is_dir()))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")

    logger.debug("Listed %d items in %s", len(items), target)
    return DirectoryListing(path=str(target), items=items)


@app.get("/file", dependencies=[Depends(_verify_token)])
async def download_file(path: Annotated[str, Query()]):
    """Download a single file from the remote machine."""
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {target}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a regular file: {target}")
    try:
        target.stat()
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")

    logger.info("Download: %s", target)
    return FileResponse(path=str(target), filename=target.name)


@app.get("/file/preview", response_model=FilePreview, dependencies=[Depends(_verify_token)])
async def preview_file(
    path: Annotated[str, Query()],
    max_size: Annotated[int, Query()] = 512_000,  # 500 KB default limit
):
    """Return the text content of a file (up to *max_size* bytes).

    Useful for previewing text files without downloading the whole thing.
    Returns 400 if the file appears to be binary.
    """
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {target}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a regular file: {target}")
    try:
        file_size = target.stat().st_size
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")

    truncated = file_size > max_size
    read_size = min(file_size, max_size)

    try:
        async with aiofiles.open(target, "rb") as f:
            raw = await f.read(read_size)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")

    # Detect binary content (presence of null bytes in the first chunk)
    if b"\x00" in raw[:8192]:
        raise HTTPException(status_code=400, detail="File appears to be binary")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = raw.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Unable to decode file as text")

    logger.info("Preview: %s (%d bytes, truncated=%s)", target, file_size, truncated)
    return FilePreview(path=str(target), content=content, size=file_size, truncated=truncated)


@app.post("/file", dependencies=[Depends(_verify_token)])
async def upload_file(path: Annotated[str, Query()], file: UploadFile):
    """Upload a file to the remote machine at *path*/<filename>."""
    dest_dir = Path(path).resolve()
    if not dest_dir.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {dest_dir}")
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {dest_dir}")

    dest_file = dest_dir / (file.filename or "upload")
    try:
        async with aiofiles.open(dest_file, "wb") as f:
            while chunk := await file.read(1024 * 256):
                await f.write(chunk)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {dest_file}")

    logger.info("Upload: %s (%d bytes)", dest_file, dest_file.stat().st_size)
    return {"status": "ok", "path": str(dest_file), "size": dest_file.stat().st_size}


@app.delete("/file", dependencies=[Depends(_verify_token)])
async def delete_file(path: Annotated[str, Query()]):
    """Delete a file or directory on the remote machine."""
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {target}")

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")

    logger.info("Deleted: %s", target)
    return {"status": "ok", "path": str(target)}


@app.patch("/file", dependencies=[Depends(_verify_token)])
async def rename_file(
    path: Annotated[str, Query()],
    new_name: Annotated[str, Query()],
):
    """Rename a file or directory on the remote machine."""
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {target}")
    if "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="new_name must be a simple filename, not a path")

    new_path = target.parent / new_name
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {new_path}")

    try:
        target.rename(new_path)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Rename failed: {exc}")

    logger.info("Renamed: %s → %s", target, new_path)
    return {"status": "ok", "old_path": str(target), "new_path": str(new_path)}


# ── WebSocket command execution ──────────────────────────────────────────────

@app.websocket("/ws/execute")
async def ws_execute(ws: WebSocket, token: str | None = Query(default=None)):
    """Accept a command, execute it in a subprocess, stream output back."""
    # ── Auth check for WebSocket ─────────────────────────────────────────
    if _auth_token is not None and token != _auth_token:
        await ws.accept()
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or missing token")
        return

    await ws.accept()
    proc: asyncio.subprocess.Process | None = None

    try:
        while True:
            raw = await ws.receive_text()
            payload = CommandPayload.model_validate_json(raw)
            logger.info("Execute: %s (cwd=%s)", payload.command, payload.cwd)

            try:
                proc = await asyncio.create_subprocess_shell(
                    payload.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=payload.cwd,
                    executable=_shell_path,
                )
            except (FileNotFoundError, PermissionError, OSError) as exc:
                await ws.send_text(
                    CommandOutput(stream="stderr", data=f"Failed to start process: {exc}\n").model_dump_json()
                )
                await ws.send_text(
                    CommandOutput(stream="exit", data="1").model_dump_json()
                )
                continue

            async def _stream(pipe: asyncio.StreamReader | None, name: str):
                if pipe is None:
                    return
                while True:
                    line = await pipe.readline()
                    if not line:
                        break
                    msg = CommandOutput(stream=name, data=line.decode(errors="replace"))  # type: ignore[arg-type]
                    await ws.send_text(msg.model_dump_json())

            await asyncio.gather(
                _stream(proc.stdout, "stdout"),
                _stream(proc.stderr, "stderr"),
            )

            exit_code = await proc.wait()
            proc = None
            await ws.send_text(
                CommandOutput(stream="exit", data=str(exit_code)).model_dump_json()
            )

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    finally:
        # ── Cleanup: kill the subprocess if the client disconnects ────────
        if proc is not None and proc.returncode is None:
            logger.warning("Killing orphaned subprocess (pid=%s)", proc.pid)
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass


# ── CLI Entrypoint (uses Typer for --port / --token flags) ───────────────────

_cli = _typer.Typer(add_completion=False)


@_cli.command()
def start(
    host: Annotated[str, _typer.Option("--host", "-H", help="Bind address.")] = "0.0.0.0",
    port: Annotated[int, _typer.Option("--port", "-p", help="Bind port.")] = DEFAULT_PORT,
    token: Annotated[str | None, _typer.Option("--token", "-t", help="Auth token (or set TUNNEL_SSH_TOKEN env).")] = DEFAULT_TOKEN,
    shell: Annotated[str, _typer.Option("--shell", "-s", help="Shell executable for command execution.")] = "/bin/bash",
    log_level: Annotated[str, _typer.Option("--log-level", help="Logging level.")] = "info",
):
    """Start the tunnel-ssh API server."""
    # Propagate token to env (for any sub-workers / reloads).
    if token:
        os.environ["TUNNEL_SSH_TOKEN"] = token

    set_auth_token(token)
    set_shell_path(shell)

    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
    logger.info("Shell: %s", _shell_path)
    if _auth_token:
        logger.info("Auth enabled (token set)")
    else:
        logger.warning("Auth DISABLED – server is open to anyone who can reach it")

    # Pass the app object directly so uvicorn does NOT re-import the module
    # (which would reset _auth_token to the default).
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
    )


if __name__ == "__main__":
    _cli()
