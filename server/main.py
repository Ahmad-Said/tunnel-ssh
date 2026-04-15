"""tunnel-ssh API server – run on the *remote* machine (port 222 by default).

Endpoints
---------
GET  /files?path=<dir>       List directory contents.
GET  /file?path=<filepath>   Download a single file.
POST /file                   Upload a file  (multipart: ``path`` + ``file``).
WS   /ws/execute             Execute a shell command and stream output.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from typing import Annotated

import aiofiles
import uvicorn
from fastapi import FastAPI, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware

from shared.models import CommandOutput, CommandPayload, DirectoryListing, FileItem

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="tunnel-ssh server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_PORT = int(os.getenv("TUNNEL_SSH_PORT", "222"))


# ── File management endpoints ────────────────────────────────────────────────

@app.get("/files", response_model=DirectoryListing)
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
                    )
                )
            except PermissionError:
                items.append(FileItem(name=entry.name, is_dir=entry.is_dir()))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")

    return DirectoryListing(path=str(target), items=items)


@app.get("/file")
async def download_file(path: Annotated[str, Query()]):
    """Download a single file from the remote machine."""
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {target}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a regular file: {target}")
    try:
        # Quick permission check
        target.stat()
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")

    return FileResponse(path=str(target), filename=target.name)


@app.post("/file")
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

    return {"status": "ok", "path": str(dest_file), "size": dest_file.stat().st_size}


# ── WebSocket command execution ──────────────────────────────────────────────

@app.websocket("/ws/execute")
async def ws_execute(ws: WebSocket):
    """Accept a command, execute it in a subprocess, stream output back."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            payload = CommandPayload.model_validate_json(raw)

            proc = await asyncio.create_subprocess_shell(
                payload.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=payload.cwd,
            )

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
            await ws.send_text(
                CommandOutput(stream="exit", data=str(exit_code)).model_dump_json()
            )
    except WebSocketDisconnect:
        pass


# ── Entrypoint ───────────────────────────────────────────────────────────────

def start():
    """CLI entrypoint (``tunnel-server``)."""
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=DEFAULT_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    start()

