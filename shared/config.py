"""Centralized configuration for tunnel-ssh components."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_PORT = int(os.getenv("TUNNEL_SSH_PORT", "222"))
DEFAULT_TOKEN: str | None = os.getenv("TUNNEL_SSH_TOKEN") or None
CONFIG_PATH = Path(os.getenv("TUNNEL_SSH_CONFIG", Path.home() / ".tunnel-ssh.json"))


# ── Server profile (used by CLI & UI) ───────────────────────────────────────

class ServerProfile(BaseModel):
    """A named remote server entry stored in ``~/.tunnel-ssh.json``."""

    host: str
    port: int = DEFAULT_PORT
    token: str | None = None


class TunnelConfig(BaseModel):
    """Top-level config file schema."""

    servers: dict[str, ServerProfile] = {}


def load_config() -> TunnelConfig:
    """Load ``~/.tunnel-ssh.json`` (or ``$TUNNEL_SSH_CONFIG``).

    Returns an empty config if the file doesn't exist or is invalid.
    """
    if not CONFIG_PATH.exists():
        return TunnelConfig()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return TunnelConfig.model_validate(data)
    except Exception:
        return TunnelConfig()


def resolve_server(name_or_host: str) -> ServerProfile:
    """Resolve a server argument.

    If *name_or_host* matches a key in the config file, return that profile.
    Otherwise treat it as a raw hostname and return a default profile.
    """
    cfg = load_config()
    if name_or_host in cfg.servers:
        return cfg.servers[name_or_host]
    return ServerProfile(host=name_or_host)


def save_config(cfg: TunnelConfig) -> None:
    """Persist the config to disk."""
    CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")

