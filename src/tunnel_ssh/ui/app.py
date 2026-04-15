"""tunnel-ssh Desktop UI — Flet-based file explorer + streaming terminal.

Launch with ``tunnel-ui`` (after ``pip install -e .``) or::

    python -m tunnel_ssh.ui.app
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import flet as ft
import httpx
import websockets

from tunnel_ssh.shared.config import DEFAULT_PORT, load_config
from tunnel_ssh.shared.http import auth_headers, base_url, ws_url
from tunnel_ssh.shared.models import CommandOutput, CommandPayload, DirectoryListing, StdinInput
from tunnel_ssh.ui.helpers import human_size, human_time, is_root_path, join_path, parent_path

logger = logging.getLogger("tunnel-ssh.ui")

_DEFAULT_PORT_STR = str(DEFAULT_PORT)


# ── Main application ─────────────────────────────────────────────────────────

async def app_main(page: ft.Page) -> None:
    """Build the entire UI and attach it to *page*."""
    page.title = "tunnel-ssh"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10

    # ── State ────────────────────────────────────────────────────────────
    current_path: list[str] = ["/"]
    command_history: list[str] = []
    history_index: list[int] = [-1]
    _background_tasks: list[asyncio.Task] = []  # prevent GC of fire-and-forget tasks

    # ── Connection bar ───────────────────────────────────────────────────
    server_field = ft.TextField(label="Server", value="localhost", width=200, dense=True)
    port_field = ft.TextField(
        label="Port", value=_DEFAULT_PORT_STR, width=80, dense=True,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    token_field = ft.TextField(label="Token", width=200, dense=True, password=True, can_reveal_password=True)

    # ── Profile dropdown (loaded from ~/.tunnel-ssh.json) ─────────────
    _MANUAL_ENTRY = "__manual__"

    def _build_profile_options() -> list[ft.dropdown.Option]:
        """Build dropdown options from saved profiles."""
        options: list[ft.dropdown.Option] = [
            ft.dropdown.Option(key=_MANUAL_ENTRY, text="Manual entry"),
        ]
        cfg = load_config()
        for name, profile in cfg.servers.items():
            auth = " 🔒" if profile.token else ""
            label = f"{name}  ({profile.host}:{profile.port}{auth})"
            options.append(ft.dropdown.Option(key=name, text=label))
        return options

    profile_dropdown = ft.Dropdown(
        label="Profile",
        width=280,
        dense=True,
        options=_build_profile_options(),
        value=_MANUAL_ENTRY,
    )

    def _on_profile_change(e: object) -> None:
        """Fill connection fields from the selected profile."""
        selected = profile_dropdown.value
        if selected == _MANUAL_ENTRY or selected is None:
            return
        cfg = load_config()
        profile = cfg.servers.get(selected)
        if profile is None:
            return
        server_field.value = profile.host
        port_field.value = str(profile.port)
        token_field.value = profile.token or ""
        page.update()

    profile_dropdown.on_change = _on_profile_change

    def _refresh_profiles() -> None:
        """Reload profile dropdown options from disk."""
        profile_dropdown.options = _build_profile_options()
        page.update()

    refresh_profiles_btn = ft.IconButton(
        icon=ft.Icons.SYNC, tooltip="Reload profiles",
        icon_size=18,
        on_click=lambda e: _refresh_profiles(),
    )

    def _get_conn() -> tuple[str, int, str | None]:
        server = server_field.value or "localhost"
        port = int(port_field.value or DEFAULT_PORT)
        token = token_field.value or None
        return server, port, token

    # ── File explorer widgets ────────────────────────────────────────────
    breadcrumb_row = ft.Row(wrap=True, spacing=0)
    status_icon = ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREY_500, size=14, tooltip="Not connected")
    file_list = ft.ListView(expand=True, spacing=2, auto_scroll=False)
    file_status = ft.Text(value="", size=12, italic=True, color=ft.Colors.GREY_400)

    # ── Breadcrumbs ──────────────────────────────────────────────────────

    def _build_breadcrumbs(path: str) -> None:
        breadcrumb_row.controls.clear()
        breadcrumb_row.controls.append(status_icon)
        breadcrumb_row.controls.append(ft.Container(width=6))

        sep = "\\" if "\\" in path else "/"
        _btn_style = ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4))

        if sep == "\\":
            parts = path.split("\\")
            cumulative = parts[0]
            breadcrumb_row.controls.append(
                ft.TextButton(cumulative + "\\", style=_btn_style,
                              on_click=lambda e, p=cumulative + "\\": asyncio.ensure_future(fetch_files(p)))
            )
            for part in parts[1:]:
                if not part:
                    continue
                cumulative += "\\" + part
                breadcrumb_row.controls.append(ft.Text("\u203a", size=14, color=ft.Colors.GREY_500))
                breadcrumb_row.controls.append(
                    ft.TextButton(part, style=_btn_style,
                                  on_click=lambda e, p=cumulative: asyncio.ensure_future(fetch_files(p)))
                )
        else:
            parts = path.split("/")
            breadcrumb_row.controls.append(
                ft.TextButton("/", style=_btn_style,
                              on_click=lambda e: asyncio.ensure_future(fetch_files("/")))
            )
            cumulative = ""
            for part in parts[1:]:
                if not part:
                    continue
                cumulative += "/" + part
                breadcrumb_row.controls.append(ft.Text("\u203a", size=14, color=ft.Colors.GREY_500))
                breadcrumb_row.controls.append(
                    ft.TextButton(part, style=_btn_style,
                                  on_click=lambda e, p=cumulative: asyncio.ensure_future(fetch_files(p)))
                )

    # ── Fetch & display files ────────────────────────────────────────────

    async def fetch_files(path: str = "/") -> None:
        server, port, token = _get_conn()
        file_list.controls.clear()
        file_status.value = "Loading…"
        page.update()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{base_url(server, port)}/files",
                    params={"path": path},
                    headers=auth_headers(token),
                )
                resp.raise_for_status()

            listing = DirectoryListing.model_validate(resp.json())
            current_path[0] = listing.path
            _build_breadcrumbs(listing.path)
            file_status.value = f"{len(listing.items)} items"

            status_icon.color = ft.Colors.GREEN_400
            status_icon.tooltip = "Connected"

            # Parent directory link
            if not is_root_path(listing.path):
                parent = parent_path(listing.path)
                file_list.controls.append(
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.ARROW_UPWARD, color=ft.Colors.AMBER),
                        title=ft.Text(".."),
                        on_click=lambda e, p=parent: asyncio.ensure_future(fetch_files(p)),
                        dense=True,
                    )
                )

            for item in listing.items:
                _add_file_tile(listing.path, item)

        except Exception as exc:
            file_status.value = f"Error: {exc}"
            status_icon.color = ft.Colors.RED_400
            status_icon.tooltip = f"Connection failed: {exc}"
            logger.warning("fetch_files failed: %s", exc)

        page.update()

    def _add_file_tile(dir_path: str, item: object) -> None:
        """Build a ListTile for a single FileItem and append it to file_list."""
        icon = ft.Icons.FOLDER if item.is_dir else ft.Icons.INSERT_DRIVE_FILE
        color = ft.Colors.AMBER if item.is_dir else ft.Colors.BLUE_200

        subtitle_parts: list[str] = []
        if item.permissions:
            subtitle_parts.append(item.permissions)
        if item.size is not None:
            subtitle_parts.append(human_size(item.size))
        if item.modified is not None:
            subtitle_parts.append(human_time(item.modified))

        full_path = join_path(dir_path, item.name)

        def _make_click_handler(path: str, is_directory: bool):
            if is_directory:
                def handler(e, p=path):
                    _background_tasks.append(asyncio.ensure_future(fetch_files(p)))
            else:
                def handler(e, p=path):
                    _background_tasks.append(asyncio.ensure_future(_download_file(p)))
            return handler

        on_click = _make_click_handler(full_path, item.is_dir)

        # Context menu
        menu_items = [
            ft.PopupMenuItem(text="Copy Path", icon=ft.Icons.COPY,
                             on_click=lambda e, p=full_path: _copy_path(p)),
        ]
        if not item.is_dir:
            menu_items.insert(0, ft.PopupMenuItem(
                text="Download", icon=ft.Icons.DOWNLOAD,
                on_click=lambda e, p=full_path: asyncio.ensure_future(_download_file(p)),
            ))
        menu_items.extend([
            ft.PopupMenuItem(),  # divider
            ft.PopupMenuItem(text="Rename", icon=ft.Icons.EDIT,
                             on_click=lambda e, p=full_path, n=item.name: asyncio.ensure_future(_rename_dialog(p, n))),
            ft.PopupMenuItem(text="Delete", icon=ft.Icons.DELETE,
                             on_click=lambda e, p=full_path, n=item.name: asyncio.ensure_future(_delete_confirm(p, n))),
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

    # ── File operations ──────────────────────────────────────────────────

    async def _download_file(remote_path: str) -> None:
        server, port, token = _get_conn()
        file_status.value = f"Downloading {remote_path}…"
        page.update()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{base_url(server, port)}/file",
                    params={"path": remote_path},
                    headers=auth_headers(token),
                )
                resp.raise_for_status()
            filename = Path(remote_path).name
            dest = Path.cwd() / filename
            dest.write_bytes(resp.content)
            file_status.value = f"Saved → {dest} ({len(resp.content):,} bytes)"
        except Exception as exc:
            file_status.value = f"Download failed: {exc}"
        page.update()

    def _copy_path(remote_path: str) -> None:
        page.set_clipboard(remote_path)
        file_status.value = f"Copied: {remote_path}"
        page.update()

    async def _delete_remote(remote_path: str) -> None:
        server, port, token = _get_conn()
        file_status.value = f"Deleting {remote_path}…"
        page.update()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{base_url(server, port)}/file",
                    params={"path": remote_path},
                    headers=auth_headers(token),
                )
                resp.raise_for_status()
            file_status.value = f"Deleted: {remote_path}"
        except Exception as exc:
            file_status.value = f"Delete failed: {exc}"
        page.update()
        await fetch_files(current_path[0])

    async def _rename_remote(remote_path: str, new_name: str) -> None:
        server, port, token = _get_conn()
        file_status.value = "Renaming…"
        page.update()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.patch(
                    f"{base_url(server, port)}/file",
                    params={"path": remote_path, "new_name": new_name},
                    headers=auth_headers(token),
                )
                resp.raise_for_status()
            data = resp.json()
            file_status.value = f"Renamed → {data.get('new_path', new_name)}"
        except Exception as exc:
            file_status.value = f"Rename failed: {exc}"
        page.update()
        await fetch_files(current_path[0])

    # ── Dialogs ──────────────────────────────────────────────────────────

    async def _delete_confirm(remote_path: str, name: str) -> None:
        result: list[bool] = []

        def on_yes(e: object) -> None:
            result.append(True)
            dlg.open = False
            page.update()

        def on_no(e: object) -> None:
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

        while dlg.open:
            await asyncio.sleep(0.1)

        page.overlay.remove(dlg)
        if result:
            await _delete_remote(remote_path)

    async def _rename_dialog(remote_path: str, old_name: str) -> None:
        name_field = ft.TextField(value=old_name, autofocus=True, width=300)
        confirmed: list[bool] = []

        def on_ok(e: object) -> None:
            confirmed.append(True)
            dlg.open = False
            page.update()

        def on_cancel(e: object) -> None:
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

    async def _sudo_password_dialog(prompt_text: str) -> str | None:
        """Show a modal dialog asking for a sudo password. Returns the password or *None* if cancelled."""
        pw_field = ft.TextField(
            value="", password=True, can_reveal_password=True,
            autofocus=True, width=300, label="Password",
        )
        result: list[str] = []

        def on_ok(e: object) -> None:
            result.append(pw_field.value or "")
            dlg.open = False
            page.update()

        def on_cancel(e: object) -> None:
            dlg.open = False
            page.update()

        def on_submit(e: object) -> None:
            on_ok(e)

        pw_field.on_submit = on_submit

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("sudo — password required"),
            content=ft.Column(
                [ft.Text(prompt_text.strip(), font_family="Consolas", size=13), pw_field],
                tight=True, spacing=12,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel),
                ft.TextButton("OK", on_click=on_ok),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        while dlg.open:
            await asyncio.sleep(0.1)

        page.overlay.remove(dlg)
        return result[0] if result else None

    # ── Buttons ──────────────────────────────────────────────────────────

    connect_btn = ft.ElevatedButton(
        "Connect", icon=ft.Icons.POWER,
        on_click=lambda e: asyncio.ensure_future(fetch_files("/")),
    )
    refresh_btn = ft.IconButton(
        icon=ft.Icons.REFRESH, tooltip="Refresh",
        on_click=lambda e: asyncio.ensure_future(fetch_files(current_path[0])),
    )

    # ── Terminal ─────────────────────────────────────────────────────────

    terminal_output = ft.ListView(expand=True, spacing=0, auto_scroll=True)
    cmd_field = ft.TextField(
        label="Command", hint_text="e.g. ls -la /home", expand=True, dense=True,
        on_submit=lambda e: asyncio.ensure_future(_run_command()),
    )

    def _on_cmd_key(e: ft.KeyboardEvent) -> None:
        if e.ctrl and e.key == "L":
            terminal_output.controls.clear()
            page.update()
            return
        if e.ctrl and e.key == "R":
            _background_tasks.append(asyncio.ensure_future(fetch_files(current_path[0])))
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
        icon=ft.Icons.PLAY_ARROW, tooltip="Run", icon_color=ft.Colors.GREEN_400,
        on_click=lambda e: asyncio.ensure_future(_run_command()),
    )

    async def _run_command() -> None:
        command_text = (cmd_field.value or "").strip()
        if not command_text:
            return

        command_history.append(command_text)
        history_index[0] = -1

        server, port, token = _get_conn()

        terminal_output.controls.append(
            ft.Text(f"$ {command_text}", color=ft.Colors.GREEN_400, font_family="Consolas", size=13)
        )
        cmd_field.value = ""
        page.update()

        payload = CommandPayload(command=command_text, cwd=current_path[0] if current_path[0] != "/" else None)

        try:
            async with websockets.connect(ws_url(server, port, token), open_timeout=10) as ws_conn:
                await ws_conn.send(payload.model_dump_json())

                async for raw in ws_conn:
                    msg = CommandOutput.model_validate_json(raw)
                    if msg.stream == "exit":
                        color = ft.Colors.GREEN_400 if msg.data == "0" else ft.Colors.RED_400
                        terminal_output.controls.append(
                            ft.Text(f"[exit {msg.data}]", color=color, font_family="Consolas", size=12, italic=True)
                        )
                        break
                    elif msg.stream == "prompt":
                        # Server requests interactive input (sudo password).
                        terminal_output.controls.append(
                            ft.Text(msg.data.strip(), color=ft.Colors.AMBER, font_family="Consolas", size=13)
                        )
                        page.update()
                        password = await _sudo_password_dialog(msg.data)
                        if password is not None:
                            await ws_conn.send(StdinInput(stdin=password).model_dump_json())
                        else:
                            # User cancelled — we can't abort the remote process
                            # cleanly, so send empty string to let sudo fail.
                            await ws_conn.send(StdinInput(stdin="").model_dump_json())
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
            logger.warning("Command execution failed: %s", exc)

        page.update()

    clear_btn = ft.IconButton(
        icon=ft.Icons.DELETE_SWEEP, tooltip="Clear terminal",
        on_click=lambda e: (terminal_output.controls.clear(), page.update()),
    )

    # ── Layout ───────────────────────────────────────────────────────────

    file_panel = ft.Container(
        content=ft.Column([
            ft.Row([profile_dropdown, refresh_profiles_btn, server_field, port_field, token_field, connect_btn, refresh_btn],
                   alignment=ft.MainAxisAlignment.START, wrap=True),
            breadcrumb_row,
            ft.Divider(height=1),
            file_list,
            file_status,
        ], expand=True),
        expand=1, padding=10,
        border=ft.border.all(1, ft.Colors.GREY_800), border_radius=8,
    )

    terminal_panel = ft.Container(
        content=ft.Column([
            ft.Row([cmd_field, run_btn, clear_btn]),
            ft.Divider(height=1),
            ft.Container(content=terminal_output, expand=True,
                         bgcolor=ft.Colors.BLACK, border_radius=6, padding=8),
        ], expand=True),
        expand=1, padding=10,
        border=ft.border.all(1, ft.Colors.GREY_800), border_radius=8,
    )

    page.add(ft.Row([file_panel, terminal_panel], expand=True, spacing=10))


# ── Entrypoint ───────────────────────────────────────────────────────────────

def main() -> None:
    """Setuptools / direct entrypoint."""
    ft.app(target=app_main)


if __name__ == "__main__":
    main()






