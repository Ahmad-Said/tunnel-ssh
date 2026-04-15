"""WebSocket command-execution endpoint.

Accepts shell commands over a persistent WebSocket connection, runs them via
``asyncio.create_subprocess_shell``, and streams stdout/stderr back in real time.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from tunnel_ssh.server.settings import settings
from tunnel_ssh.shared.models import CommandOutput, CommandPayload

logger = logging.getLogger("tunnel-ssh.server.ws")

router = APIRouter(tags=["execute"])


@router.websocket("/ws/execute")
async def ws_execute(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    """Accept a command, execute it in a subprocess, stream output back."""

    # ── Auth check ────────────────────────────────────────────────────────
    if settings.auth_enabled and token != settings.auth_token:
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
                    executable=settings.shell_path,
                )
            except (FileNotFoundError, PermissionError, OSError) as exc:
                await ws.send_text(
                    CommandOutput(stream="stderr", data=f"Failed to start process: {exc}\n").model_dump_json()
                )
                await ws.send_text(
                    CommandOutput(stream="exit", data="1").model_dump_json()
                )
                continue

            async def _stream(pipe: asyncio.StreamReader | None, name: str) -> None:
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
        # Kill the subprocess if the client disconnects mid-execution
        if proc is not None and proc.returncode is None:
            logger.warning("Killing orphaned subprocess (pid=%s)", proc.pid)
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

