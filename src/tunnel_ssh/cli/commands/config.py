"""``tunnel config`` — manage saved server profiles."""

from __future__ import annotations

from typing import Annotated

import typer

from tunnel_ssh.shared import config as _config_mod
from tunnel_ssh.shared.config import (
    DEFAULT_PORT,
    ServerProfile,
    load_config,
    save_config,
)

config_app = typer.Typer(name="config", help="Manage saved server profiles (~/.tunnel-ssh.json).")


def _complete_profile_name(incomplete: str) -> list[str]:
    """Return profile names matching *incomplete* for shell completion."""
    cfg = load_config()
    return [name for name in cfg.servers if name.startswith(incomplete)]


def register(app: typer.Typer) -> None:
    """Register the ``config`` sub-app on *app*."""
    app.add_typer(config_app, name="config")


# ── config add ───────────────────────────────────────────────────────────────

@config_app.command(name="add")
def config_add(
    name: Annotated[str, typer.Argument(help="Profile name (e.g. 'prod', 'server1').")],
    host: Annotated[str, typer.Option("--host", "-H", help="Hostname or IP.")] = "localhost",
    port: Annotated[int, typer.Option("--port", "-p", help="Port.")] = DEFAULT_PORT,
    token: Annotated[str | None, typer.Option("--token", "-t", help="Auth token.")] = None,
) -> None:
    """Save a named server profile."""
    cfg = load_config()
    cfg.servers[name] = ServerProfile(host=host, port=port, token=token)
    save_config(cfg)
    typer.echo(f"Saved profile '{name}' → {host}:{port}")


# ── config show ──────────────────────────────────────────────────────────────

@config_app.command(name="show")
def config_show(
    name: Annotated[str, typer.Argument(help="Profile name to display.", autocompletion=_complete_profile_name)],
) -> None:
    """Display details of a single saved profile."""
    cfg = load_config()
    if name not in cfg.servers:
        typer.echo(f"Profile '{name}' not found.", err=True)
        raise typer.Exit(code=1)

    profile = cfg.servers[name]
    typer.echo(f"  Name  : {name}")
    typer.echo(f"  Host  : {profile.host}")
    typer.echo(f"  Port  : {profile.port}")
    typer.echo(f"  Token : {'••••' if profile.token else '(none)'}")


# ── config list ──────────────────────────────────────────────────────────────

@config_app.command(name="list")
def config_list() -> None:
    """Show all saved server profiles."""
    cfg = load_config()
    if not cfg.servers:
        typer.echo("No profiles configured. Use: tunnel config add <name> --host <host>")
        return

    for name, profile in cfg.servers.items():
        auth = " 🔒" if profile.token else ""
        typer.echo(f"  {name:20s} {profile.host}:{profile.port}{auth}")


# ── config update ────────────────────────────────────────────────────────────

@config_app.command(name="update")
def config_update(
    name: Annotated[str, typer.Argument(help="Profile name to update.", autocompletion=_complete_profile_name)],
    host: Annotated[str | None, typer.Option("--host", "-H", help="New hostname or IP.")] = None,
    port: Annotated[int | None, typer.Option("--port", "-p", help="New port.")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t", help="New auth token.")] = None,
) -> None:
    """Update fields of an existing profile (only supplied options are changed)."""
    cfg = load_config()
    if name not in cfg.servers:
        typer.echo(f"Profile '{name}' not found.", err=True)
        raise typer.Exit(code=1)

    profile = cfg.servers[name]
    if host is not None:
        profile.host = host
    if port is not None:
        profile.port = port
    if token is not None:
        profile.token = token

    cfg.servers[name] = profile
    save_config(cfg)
    typer.echo(f"Updated profile '{name}' → {profile.host}:{profile.port}")


# ── config remove ────────────────────────────────────────────────────────────

@config_app.command(name="remove")
def config_remove(
    name: Annotated[str, typer.Argument(help="Profile name to remove.", autocompletion=_complete_profile_name)],
) -> None:
    """Remove a saved server profile."""
    cfg = load_config()
    if name not in cfg.servers:
        typer.echo(f"Profile '{name}' not found.", err=True)
        raise typer.Exit(code=1)

    del cfg.servers[name]
    save_config(cfg)
    typer.echo(f"Removed profile '{name}'.")


# ── config path ──────────────────────────────────────────────────────────────

@config_app.command(name="path")
def config_path() -> None:
    """Print the path to the config file."""
    typer.echo(str(_config_mod.CONFIG_PATH))


# ── config use-context ───────────────────────────────────────────────────────

@config_app.command(name="use-context")
def config_use_context(
    name: Annotated[str, typer.Argument(help="Profile name to set as the current context.", autocompletion=_complete_profile_name)],
) -> None:
    """Set the current context (like ``kubectl config use-context``)."""
    cfg = load_config()
    if name not in cfg.servers:
        typer.echo(f"Profile '{name}' not found. Add it first with: tunnel config add {name} --host <host>", err=True)
        raise typer.Exit(code=1)

    cfg.current_context = name
    save_config(cfg)
    typer.echo(f"Switched to context '{name}'.")


# ── config current-context ───────────────────────────────────────────────────

@config_app.command(name="current-context")
def config_current_context() -> None:
    """Display the current context."""
    cfg = load_config()
    if cfg.current_context:
        typer.echo(cfg.current_context)
    else:
        typer.echo("No current context set. Use: tunnel config use-context <name>")


# ── config get-contexts ──────────────────────────────────────────────────────

@config_app.command(name="get-contexts")
def config_get_contexts() -> None:
    """List all contexts, highlighting the current one (like ``kubectl config get-contexts``)."""
    cfg = load_config()
    if not cfg.servers:
        typer.echo("No profiles configured. Use: tunnel config add <name> --host <host>")
        return

    typer.echo(f"  {'CURRENT':<9} {'NAME':<20} {'SERVER':<30} {'AUTH'}")
    for name, profile in cfg.servers.items():
        marker = "*" if name == cfg.current_context else " "
        auth = "token" if profile.token else ""
        typer.echo(f"  {marker:<9} {name:<20} {profile.host}:{profile.port:<20} {auth}")


