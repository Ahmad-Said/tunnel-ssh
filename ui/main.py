"""tunnel-ssh Desktop UI – Flet-based file explorer + terminal.

Launch with ``tunnel-ui`` (after ``pip install -e .``) or ``python -m ui.main``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath

import flet as ft
import httpx
import websockets

from shared.config import DEFAULT_PORT, resolve_server
from shared.models import CommandOutput, CommandPayload, DirectoryListing

DEFAULT_PORT_STR = str(DEFAULT_PORT)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _base_url(server: str, port: int) -> str:
    return f"http://{server}:{port}"


def _ws_url(server: str, port: int, token: str | None = None) -> str:
    base = f"ws://{server}:{port}/ws/execute"
    if token:
        base += f"?token={token}"
    return base


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} PB"


def _human_time(epoch: float) -> str:
    """Convert epoch seconds to a short human-readable timestamp."""
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def _parent_path(path: str) -> str:
    """Return the parent of *path*, handling both POSIX and Windows style."""
    # Try Windows first (contains backslash or drive letter)
    if "\\" in path or (len(path) >= 2 and path[1] == ":"):
        parent = str(PureWindowsPath(path).parent)
    else:
        parent = str(PurePosixPath(path).parent)
    return parent


def _join_path(base: str, name: str) -> str:
    """Join base path and child name, respecting platform style."""
    sep = "\\" if "\\" in base else "/"
    return f"{base.rstrip(sep)}{sep}{name}"


# ── App ──────────────────────────────────────────────────────────────────────

async def app_main(page: ft.Page):
    page.title = "tunnel-ssh"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10

    # ── State ────────────────────────────────────────────────────────────
    current_path: list[str] = ["/"]
    command_history: list[str] = []
    history_index: list[int] = [-1]  # mutable holder

    # ── Server connection bar ────────────────────────────────────────────
    server_field = ft.TextField(label="Server", value="localhost", width=200, dense=True)
    port_field = ft.TextField(label="Port", value=DEFAULT_PORT_STR, width=80, dense=True, keyboard_type=ft.KeyboardType.NUMBER)
    token_field = ft.TextField(label="Token", width=200, dense=True, password=True, can_reveal_password=True)

    def _get_conn() -> tuple[str, int, str | None]:
        """Read current connection params from the UI fields."""
        server = server_field.value or "localhost"
        port = int(port_field.value or DEFAULT_PORT)
        token = token_field.value or None
        return server, port, token

    def _auth_headers(token: str | None) -> dict[str, str]:
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    # ── File explorer widgets ────────────────────────────────────────────
    breadcrumb_row = ft.Row(wrap=True, spacing=0)
    status_icon = ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREY_500, size=14, tooltip="Not connected")
    file_list = ft.ListView(expand=True, spacing=2, auto_scroll=False)
    file_status = ft.Text(value="", size=12, italic=True, color=ft.Colors.GREY_400)

    def _build_breadcrumbs(path: str):
        """Rebuild the breadcrumb row from path segments."""
        breadcrumb_row.controls.clear()
        breadcrumb_row.controls.append(status_icon)
        breadcrumb_row.controls.append(ft.Container(width=6))

        # Determine separator
        sep = "\\" if "\\" in path else "/"

        # Split the path into meaningful segments
        if sep == "\\":
            # Windows: C:\foo\bar → ["C:", "foo", "bar"]
            parts = path.split("\\")
            cumulative = parts[0]  # "C:"
            breadcrumb_row.controls.append(
                ft.TextButton(
                    cumulative + "\\",
                    style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4)),
                    on_click=lambda e, p=cumulative + "\\": asyncio.ensure_future(fetch_files(p)),
                )
            )
            for part in parts[1:]:
                if not part:
                    continue
                cumulative += "\\" + part
                breadcrumb_row.controls.append(ft.Text("›", size=14, color=ft.Colors.GREY_500))
                breadcrumb_row.controls.append(
                    ft.TextButton(
                        part,
                        style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4)),
                        on_click=lambda e, p=cumulative: asyncio.ensure_future(fetch_files(p)),
                    )
                )
        else:
            # POSIX: /home/user/dir → ["", "home", "user", "dir"]
            parts = path.split("/")
            breadcrumb_row.controls.append(
                ft.TextButton(
                    "/",
                    style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4)),
                    on_click=lambda e: asyncio.ensure_future(fetch_files("/")),
                )
            )
            cumulative = ""
            for part in parts[1:]:
                if not part:
                    continue
                cumulative += "/" + part
                breadcrumb_row.controls.append(ft.Text("›", size=14, color=ft.Colors.GREY_500))
                breadcrumb_row.controls.append(
                    ft.TextButton(
                        part,
                        style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4)),
                        on_click=lambda e, p=cumulative: asyncio.ensure_future(fetch_files(p)),
                    )
                )

    async def fetch_files(path: str = "/"):
        server, port, token = _get_conn()
        file_list.controls.clear()
        file_status.value = "Loading…"
        page.update()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_base_url(server, port)}/files",
                    params={"path": path},
                    headers=_auth_headers(token),
                )
                resp.raise_for_status()

            listing = DirectoryListing.model_validate(resp.json())
            current_path[0] = listing.path
            _build_breadcrumbs(listing.path)
            file_status.value = f"{len(listing.items)} items"

            # Connection succeeded
            status_icon.color = ft.Colors.GREEN_400
            status_icon.tooltip = "Connected"

            # Back button (if not root)
            is_root = listing.path in ("/", "\\") or (len(listing.path) <= 3 and listing.path.endswith(":\\"))
            if not is_root:
                parent = _parent_path(listing.path)
                file_list.controls.append(
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.ARROW_UPWARD, color=ft.Colors.AMBER),
                        title=ft.Text(".."),
                        on_click=lambda e, p=parent: asyncio.ensure_future(fetch_files(p)),
                        dense=True,
                    )
                )

            for item in listing.items:
                icon = ft.Icons.FOLDER if item.is_dir else ft.Icons.INSERT_DRIVE_FILE
                color = ft.Colors.AMBER if item.is_dir else ft.Colors.BLUE_200

                # Build subtitle with metadata
                subtitle_parts: list[str] = []
                if item.permissions:
                    subtitle_parts.append(item.permissions)
                if item.size is not None:
                    subtitle_parts.append(_human_size(item.size))
                if item.modified is not None:
                    subtitle_parts.append(_human_time(item.modified))

                full_path = _join_path(listing.path, item.name)

                if item.is_dir:
                    on_click = lambda e, p=full_path: asyncio.ensure_future(fetch_files(p))
                else:
                    on_click = lambda e, p=full_path: asyncio.ensure_future(_download_file(p))

                # Context menu (trailing popup)
                menu_items = [
                    ft.PopupMenuItem(
                        text="Copy Path",
                        icon=ft.Icons.COPY,
                        on_click=lambda e, p=full_path: _copy_path(p),
                    ),
                ]
                if not item.is_dir:
                    menu_items.insert(0, ft.PopupMenuItem(
                        text="Download",
                        icon=ft.Icons.DOWNLOAD,
                        on_click=lambda e, p=full_path: asyncio.ensure_future(_download_file(p)),
                    ))
                menu_items.extend([
                    ft.PopupMenuItem(),  # divider
                    ft.PopupMenuItem(
                        text="Rename",
                        icon=ft.Icons.EDIT,
                        on_click=lambda e, p=full_path, n=item.name: asyncio.ensure_future(_rename_dialog(p, n)),
                    ),
                    ft.PopupMenuItem(
                        text="Delete",
                        icon=ft.Icons.DELETE,
                        on_click=lambda e, p=full_path, n=item.name: asyncio.ensure_future(_delete_confirm(p, n)),
                    ),
                ])

                tile = ft.ListTile(
                    leading=ft.Icon(icon, color=color),
                    title=ft.Text(item.name),
                    subtitle=ft.Text(" · ".join(subtitle_parts)) if subtitle_parts else None,
                    on_click=on_click,
                    trailing=ft.PopupMenuButton(items=menu_items),
                    dense=True,
                )
                file_list.controls.append(tile)

        except Exception as exc:
            file_status.value = f"Error: {exc}"
            status_icon.color = ft.Colors.RED_400
            status_icon.tooltip = f"Connection failed: {exc}"

        page.update()

    async def _download_file(remote_path: str):
        """Download a remote file and save it via Flet's file picker."""
        server, port, token = _get_conn()
        file_status.value = f"Downloading {remote_path}…"
        page.update()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{_base_url(server, port)}/file",
                    params={"path": remote_path},
                    headers=_auth_headers(token),
                )
                resp.raise_for_status()

            # Save to current working directory
            from pathlib import Path
            filename = Path(remote_path).name
            dest = Path.cwd() / filename
            dest.write_bytes(resp.content)
            file_status.value = f"Saved → {dest} ({len(resp.content):,} bytes)"
        except Exception as exc:
            file_status.value = f"Download failed: {exc}"

        page.update()

    def _copy_path(remote_path: str):
        """Copy a remote path to the clipboard."""
        page.set_clipboard(remote_path)
        file_status.value = f"Copied: {remote_path}"
        page.update()

    async def _delete_remote(remote_path: str):
        """Call DELETE /file on the server, then refresh."""
        server, port, token = _get_conn()
        file_status.value = f"Deleting {remote_path}…"
        page.update()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{_base_url(server, port)}/file",
                    params={"path": remote_path},
                    headers=_auth_headers(token),
                )
                resp.raise_for_status()
            file_status.value = f"Deleted: {remote_path}"
        except Exception as exc:
            file_status.value = f"Delete failed: {exc}"
        page.update()
        await fetch_files(current_path[0])

    async def _rename_remote(remote_path: str, new_name: str):
        """Call PATCH /file on the server, then refresh."""
        server, port, token = _get_conn()
        file_status.value = f"Renaming…"
        page.update()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.patch(
                    f"{_base_url(server, port)}/file",
                    params={"path": remote_path, "new_name": new_name},
                    headers=_auth_headers(token),
                )
                resp.raise_for_status()
            data = resp.json()
            file_status.value = f"Renamed → {data.get('new_path', new_name)}"
        except Exception as exc:
            file_status.value = f"Rename failed: {exc}"
        page.update()
        await fetch_files(current_path[0])

    async def _delete_confirm(remote_path: str, name: str):
        """Show a confirmation dialog before deleting."""
        result: list[bool] = []

        def on_yes(e):
            result.append(True)
            dlg.open = False
            page.update()

        def on_no(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm Delete"),
            content=ft.Text(f"Delete '{name}'?\n\n{remote_path}"),
            actions=[
                ft.TextButton("Cancel", on_click=on_no),
                ft.TextButton("Delete", on_click=on_yes, style=ft.ButtonStyle(color=ft.Colors.RED_400)),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        # Wait for the dialog to close
        while dlg.open:
            await asyncio.sleep(0.1)

        page.overlay.remove(dlg)
        if result:
            await _delete_remote(remote_path)

    async def _rename_dialog(remote_path: str, old_name: str):
        """Show a rename dialog."""
        name_field = ft.TextField(value=old_name, autofocus=True, width=300)
        confirmed: list[bool] = []

        def on_ok(e):
            confirmed.append(True)
            dlg.open = False
            page.update()

        def on_cancel(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Rename"),
            content=name_field,
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel),
                ft.TextButton("Rename", on_click=on_ok),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        while dlg.open:
            await asyncio.sleep(0.1)

        page.overlay.remove(dlg)
        new_name = (name_field.value or "").strip()
        if confirmed and new_name and new_name != old_name:
            await _rename_remote(remote_path, new_name)

    connect_btn = ft.ElevatedButton(
        "Connect",
        icon=ft.Icons.POWER,
        on_click=lambda e: asyncio.ensure_future(fetch_files("/")),
    )

    refresh_btn = ft.IconButton(
        icon=ft.Icons.REFRESH,
        tooltip="Refresh",
        on_click=lambda e: asyncio.ensure_future(fetch_files(current_path[0])),
    )

    # ── Terminal widgets ─────────────────────────────────────────────────
    terminal_output = ft.ListView(expand=True, spacing=0, auto_scroll=True)
    cmd_field = ft.TextField(
        label="Command",
        hint_text="e.g. ls -la /home",
        expand=True,
        dense=True,
        on_submit=lambda e: asyncio.ensure_future(_run_command()),
    )

    def _on_cmd_key(e: ft.KeyboardEvent):
        """Navigate command history with Up/Down, Ctrl+L clear, Ctrl+R refresh."""
        if e.ctrl and e.key == "L":
            terminal_output.controls.clear()
            page.update()
            return
        if e.ctrl and e.key == "R":
            asyncio.ensure_future(fetch_files(current_path[0]))
            return
        if e.key == "Arrow Up" and command_history:
            idx = history_index[0]
            if idx < len(command_history) - 1:
                idx += 1
            history_index[0] = idx
            cmd_field.value = command_history[-(idx + 1)]
            page.update()
        elif e.key == "Arrow Down":
            idx = history_index[0]
            if idx > 0:
                idx -= 1
                history_index[0] = idx
                cmd_field.value = command_history[-(idx + 1)]
            else:
                history_index[0] = -1
                cmd_field.value = ""
            page.update()

    page.on_keyboard_event = _on_cmd_key

    run_btn = ft.IconButton(
        icon=ft.Icons.PLAY_ARROW,
        tooltip="Run",
        icon_color=ft.Colors.GREEN_400,
        on_click=lambda e: asyncio.ensure_future(_run_command()),
    )

    async def _run_command():
        command_text = (cmd_field.value or "").strip()
        if not command_text:
            return

        # Save to history
        command_history.append(command_text)
        history_index[0] = -1

        server, port, token = _get_conn()

        # Show the command in the terminal
        terminal_output.controls.append(
            ft.Text(f"$ {command_text}", color=ft.Colors.GREEN_400, font_family="Consolas", size=13)
        )
        cmd_field.value = ""
        page.update()

        payload = CommandPayload(command=command_text, cwd=current_path[0] if current_path[0] != "/" else None)

        try:
            async with websockets.connect(_ws_url(server, port, token), open_timeout=10) as ws:
                await ws.send(payload.model_dump_json())

                async for raw in ws:
                    msg = CommandOutput.model_validate_json(raw)
                    if msg.stream == "exit":
                        color = ft.Colors.GREEN_400 if msg.data == "0" else ft.Colors.RED_400
                        terminal_output.controls.append(
                            ft.Text(f"[exit {msg.data}]", color=color, font_family="Consolas", size=12, italic=True)
                        )
                        break
                    else:
                        color = ft.Colors.WHITE if msg.stream == "stdout" else ft.Colors.RED_300
                        terminal_output.controls.append(
                            ft.Text(msg.data.rstrip("\n"), color=color, font_family="Consolas", size=13)
                        )
                    page.update()
        except Exception as exc:
            terminal_output.controls.append(
                ft.Text(f"[error] {exc}", color=ft.Colors.RED_400, font_family="Consolas", size=12)
            )

        page.update()

    clear_btn = ft.IconButton(
        icon=ft.Icons.DELETE_SWEEP,
        tooltip="Clear terminal",
        on_click=lambda e: (terminal_output.controls.clear(), page.update()),
    )

    # ── Layout ───────────────────────────────────────────────────────────
    file_panel = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [server_field, port_field, token_field, connect_btn, refresh_btn],
                    alignment=ft.MainAxisAlignment.START,
                    wrap=True,
                ),
                breadcrumb_row,
                ft.Divider(height=1),
                file_list,
                file_status,
            ],
            expand=True,
        ),
        expand=1,
        padding=10,
        border=ft.border.all(1, ft.Colors.GREY_800),
        border_radius=8,
    )

    terminal_panel = ft.Container(
        content=ft.Column(
            [
                ft.Row([cmd_field, run_btn, clear_btn]),
                ft.Divider(height=1),
                ft.Container(
                    content=terminal_output,
                    expand=True,
                    bgcolor=ft.Colors.BLACK,
                    border_radius=6,
                    padding=8,
                ),
            ],
            expand=True,
        ),
        expand=1,
        padding=10,
        border=ft.border.all(1, ft.Colors.GREY_800),
        border_radius=8,
    )

    page.add(
        ft.Row(
            [file_panel, terminal_panel],
            expand=True,
            spacing=10,
        )
    )


def main():
    """Setuptools / direct entrypoint."""
    ft.app(target=app_main)


if __name__ == "__main__":
    main()

