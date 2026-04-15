"""File management REST endpoints.

Handles listing, downloading, uploading, previewing, deleting, and renaming
files and directories on the remote machine.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from tunnel_ssh.server.auth import verify_token
from tunnel_ssh.server.helpers import format_permissions
from tunnel_ssh.shared.models import DirectoryListing, FileItem, FilePreview

logger = logging.getLogger("tunnel-ssh.server.files")

router = APIRouter(tags=["files"])


# ── List directory ───────────────────────────────────────────────────────────

@router.get("/files", response_model=DirectoryListing, dependencies=[Depends(verify_token)])
async def list_files(path: Annotated[str, Query()] = "/") -> DirectoryListing:
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
                        permissions=format_permissions(st.st_mode),
                    )
                )
            except PermissionError:
                items.append(FileItem(name=entry.name, is_dir=entry.is_dir()))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}") from None

    logger.debug("Listed %d items in %s", len(items), target)
    return DirectoryListing(path=str(target), items=items)


# ── Download file ────────────────────────────────────────────────────────────

@router.get("/file", dependencies=[Depends(verify_token)])
async def download_file(path: Annotated[str, Query()]) -> FileResponse:
    """Download a single file from the remote machine."""
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {target}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a regular file: {target}")
    try:
        target.stat()
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}") from None

    logger.info("Download: %s", target)
    return FileResponse(path=str(target), filename=target.name)


# ── Preview text file ────────────────────────────────────────────────────────

@router.get("/file/preview", response_model=FilePreview, dependencies=[Depends(verify_token)])
async def preview_file(
    path: Annotated[str, Query()],
    max_size: Annotated[int, Query()] = 512_000,
) -> FilePreview:
    """Return the text content of a file (up to *max_size* bytes).

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
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}") from None

    truncated = file_size > max_size
    read_size = min(file_size, max_size)

    try:
        async with aiofiles.open(target, "rb") as f:
            raw = await f.read(read_size)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}") from None

    # Detect binary content (null bytes in the first chunk)
    if b"\x00" in raw[:8192]:
        raise HTTPException(status_code=400, detail="File appears to be binary")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = raw.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Unable to decode file as text") from None

    logger.info("Preview: %s (%d bytes, truncated=%s)", target, file_size, truncated)
    return FilePreview(path=str(target), content=content, size=file_size, truncated=truncated)


# ── Upload file ──────────────────────────────────────────────────────────────

@router.post("/file", dependencies=[Depends(verify_token)])
async def upload_file(path: Annotated[str, Query()], file: UploadFile) -> dict:
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
        raise HTTPException(status_code=403, detail=f"Permission denied: {dest_file}") from None

    size = dest_file.stat().st_size
    logger.info("Upload: %s (%d bytes)", dest_file, size)
    return {"status": "ok", "path": str(dest_file), "size": size}


# ── Delete file / directory ──────────────────────────────────────────────────

@router.delete("/file", dependencies=[Depends(verify_token)])
async def delete_file(path: Annotated[str, Query()]) -> dict:
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
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}") from None
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from None

    logger.info("Deleted: %s", target)
    return {"status": "ok", "path": str(target)}


# ── Rename file / directory ──────────────────────────────────────────────────

@router.patch("/file", dependencies=[Depends(verify_token)])
async def rename_file(
    path: Annotated[str, Query()],
    new_name: Annotated[str, Query()],
) -> dict:
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
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}") from None
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Rename failed: {exc}") from None

    logger.info("Renamed: %s → %s", target, new_path)
    return {"status": "ok", "old_path": str(target), "new_path": str(new_path)}
