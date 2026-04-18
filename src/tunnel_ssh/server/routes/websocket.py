"""WebSocket command-execution endpoint.

Accepts shell commands over a persistent WebSocket connection, runs them via
``asyncio.create_subprocess_shell``, and streams stdout/stderr back in real time.

Sudo support
~~~~~~~~~~~~
When a command contains ``sudo``, the server automatically injects the ``-S``
flag so that sudo reads the password from stdin.  If a password prompt is
detected on stderr the server either auto-supplies a cached password (from a
previous successful sudo in the same session) or sends a ``"prompt"`` message
to the client and waits for a ``StdinInput`` reply.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from tunnel_ssh.server.settings import settings
from tunnel_ssh.shared.models import CommandOutput, CommandPayload, StdinInput

logger = logging.getLogger("tunnel-ssh.server.ws")

router = APIRouter(tags=["execute"])

# ── Per-user session state (in-memory, lives as long as the server) ──────────

_user_sessions: dict[str, dict] = {}
"""Maps user_id → session dict. Currently tracks ``cwd`` (last working directory)."""


def _get_user_cwd(user_id: str | None) -> str | None:
    """Return the last known working directory for *user_id*, or ``None``."""
    if user_id and user_id in _user_sessions:
        return _user_sessions[user_id].get("cwd")
    return None


def _set_user_cwd(user_id: str | None, cwd: str) -> None:
    """Persist the working directory for *user_id* in memory."""
    if user_id:
        _user_sessions.setdefault(user_id, {})["cwd"] = cwd

# ── Sudo helpers ─────────────────────────────────────────────────────────────

_SUDO_RE = re.compile(r"\bsudo\b")
_SUDO_PROMPT_RE = re.compile(
    r"(?:password|contraseña|mot de passe|passwort|密码)[^:]*:\s*$",
    re.IGNORECASE,
)


def _is_sudo_command(command: str) -> bool:
    """Return *True* if *command* invokes ``sudo``."""
    return bool(_SUDO_RE.search(command))


def _inject_sudo_s(command: str) -> str:
    """Ensure every ``sudo`` in *command* carries the ``-S`` flag.

    ``-S`` makes sudo read the password from stdin instead of ``/dev/tty``,
    which is required when there is no controlling terminal.
    """
    if "-S" in command:
        return command
    return _SUDO_RE.sub("sudo -S", command)


# ── WebSocket endpoint ───────────────────────────────────────────────────────

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

    # Cached sudo password — persists across commands within the same WS session.
    cached_sudo_pw: str | None = None

    try:
        while True:
            raw = await ws.receive_text()
            payload = CommandPayload.model_validate_json(raw)
            logger.info("Execute: %s (cwd=%s, user=%s)", payload.command, payload.cwd, payload.user_id)

            # Resolve working directory: explicit > user session > server default
            effective_cwd = payload.cwd or _get_user_cwd(payload.user_id)

            command = payload.command
            sudo = _is_sudo_command(command)
            if sudo:
                command = _inject_sudo_s(command)
                logger.debug("Sudo detected — rewritten command: %s", command)

            # ── Handle `cd` specially — update user session cwd ─────────
            cd_match = re.match(r"^\s*cd\s+(.*)", command)
            if cd_match and payload.user_id:
                target = cd_match.group(1).strip().strip("'\"")
                # Resolve relative to current effective cwd
                if effective_cwd:
                    target = os.path.normpath(os.path.join(effective_cwd, target)) if not os.path.isabs(target) else target
                _set_user_cwd(payload.user_id, target)
                await ws.send_text(
                    CommandOutput(stream="exit", data="0").model_dump_json()
                )
                continue

            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.PIPE if sudo else None,
                    cwd=effective_cwd,
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

            # ── Stream helpers ────────────────────────────────────────────

            # Track whether the cached password was already attempted for
            # *this* command so we don't loop forever on a stale password.
            cached_tried = False

            async def _stream_stdout() -> None:
                if proc.stdout is None:
                    return
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    await ws.send_text(
                        CommandOutput(stream="stdout", data=chunk.decode(errors="replace")).model_dump_json()
                    )

            async def _stream_stderr() -> None:
                nonlocal cached_sudo_pw, cached_tried
                if proc.stderr is None:
                    return
                while True:
                    chunk = await proc.stderr.read(4096)
                    if not chunk:
                        break
                    text = chunk.decode(errors="replace")

                    # ── Sudo password prompt detection ────────────────────
                    if sudo and _SUDO_PROMPT_RE.search(text):
                        if cached_sudo_pw and not cached_tried:
                            # Auto-supply the cached password silently.
                            logger.debug("Auto-supplying cached sudo password")
                            cached_tried = True
                            if proc.stdin:
                                proc.stdin.write((cached_sudo_pw + "\n").encode())
                                await proc.stdin.drain()
                            continue  # don't forward prompt to client

                        # Ask the client for a password.
                        logger.debug("Requesting sudo password from client")
                        await ws.send_text(
                            CommandOutput(stream="prompt", data=text).model_dump_json()
                        )
                        pw_raw = await ws.receive_text()
                        pw_msg = StdinInput.model_validate_json(pw_raw)
                        if proc.stdin:
                            proc.stdin.write((pw_msg.stdin + "\n").encode())
                            await proc.stdin.drain()
                        cached_sudo_pw = pw_msg.stdin
                        cached_tried = True
                        continue

                    # Normal stderr output
                    await ws.send_text(
                        CommandOutput(stream="stderr", data=text).model_dump_json()
                    )

            await asyncio.gather(_stream_stdout(), _stream_stderr())

            # Close stdin so the process doesn't hang waiting for input.
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

            exit_code = await proc.wait()
            proc = None

            # Persist the effective cwd for this user's session
            if payload.user_id and effective_cwd:
                _set_user_cwd(payload.user_id, effective_cwd)

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

