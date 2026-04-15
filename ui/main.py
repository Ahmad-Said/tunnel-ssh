"""tunnel-ssh Desktop UI – Flet-based file explorer + terminal.

Launch with ``tunnel-ui`` (after ``pip install -e .``) or ``python -m ui.main``.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import flet as ft
import httpx
import websockets

from shared.models import CommandOutput, CommandPayload, DirectoryListing

DEFAULT_PORT = int(os.getenv("TUNNEL_SSH_PORT", "222"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _base_url(server: str, port: int) -> str:
    return f"http://{server}:{port}"


def _ws_url(server: str, port: int) -> str:
    return f"ws://{server}:{port}/ws/execute"


# ── App ──────────────────────────────────────────────────────────────────────

async def app_main(page: ft.Page):
    page.title = "tunnel-ssh"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10

    # ── State ────────────────────────────────────────────────────────────
    current_path: list[str] = ["/"]  # stack for breadcrumb navigation

    # ── Server connection bar ────────────────────────────────────────────
    server_field = ft.TextField(
        label="Server",
        value="localhost",
        width=200,
        dense=True,
    )
    port_field = ft.TextField(
        label="Port",
        value=str(DEFAULT_PORT),
        width=80,
        dense=True,
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    # ── File explorer widgets ────────────────────────────────────────────
    path_text = ft.Text(value="/", size=14, weight=ft.FontWeight.BOLD, selectable=True)
    file_list = ft.ListView(expand=True, spacing=2, auto_scroll=False)
    file_status = ft.Text(value="", size=12, italic=True, color=ft.Colors.GREY_400)

    async def fetch_files(path: str = "/"):
        server = server_field.value or "localhost"
        port = int(port_field.value or DEFAULT_PORT)
        file_list.controls.clear()
        file_status.value = "Loading…"
        page.update()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{_base_url(server, port)}/files", params={"path": path})
                resp.raise_for_status()

            listing = DirectoryListing.model_validate(resp.json())
            current_path[0] = listing.path
            path_text.value = listing.path
            file_status.value = f"{len(listing.items)} items"

            # Back button (if not root)
            if listing.path not in ("/", "\\"):
                parent = str(__import__("pathlib").PurePosixPath(listing.path).parent)
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
                subtitle_parts: list[str] = []
                if item.size is not None:
                    subtitle_parts.append(_human_size(item.size))

                full_path = f"{listing.path.rstrip('/')}/{item.name}"
                tile = ft.ListTile(
                    leading=ft.Icon(icon, color=color),
                    title=ft.Text(item.name),
                    subtitle=ft.Text(" · ".join(subtitle_parts)) if subtitle_parts else None,
                    on_click=(
                        (lambda e, p=full_path: asyncio.ensure_future(fetch_files(p)))
                        if item.is_dir
                        else None
                    ),
                    dense=True,
                )
                file_list.controls.append(tile)

        except Exception as exc:
            file_status.value = f"Error: {exc}"

        page.update()

    connect_btn = ft.ElevatedButton(
        "Connect",
        icon=ft.Icons.POWER,
        on_click=lambda e: asyncio.ensure_future(fetch_files("/")),
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

        server = server_field.value or "localhost"
        port = int(port_field.value or DEFAULT_PORT)

        # Show the command in the terminal
        terminal_output.controls.append(
            ft.Text(f"$ {command_text}", color=ft.Colors.GREEN_400, font_family="Consolas", size=13)
        )
        page.update()

        payload = CommandPayload(command=command_text, cwd=current_path[0] if current_path[0] != "/" else None)

        try:
            async with websockets.connect(_ws_url(server, port)) as ws:
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
        cmd_field.value = ""
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
                ft.Row([server_field, port_field, connect_btn], alignment=ft.MainAxisAlignment.START),
                path_text,
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


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} PB"


def main():
    """Setuptools / direct entrypoint."""
    ft.app(target=app_main)


if __name__ == "__main__":
    main()


