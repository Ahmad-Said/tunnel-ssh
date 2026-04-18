"""Centralized configuration for tunnel-ssh components.

Reads defaults from environment variables and manages the on-disk server
profiles stored in ``~/.tunnel-ssh.json`` (or ``$TUNNEL_SSH_CONFIG``).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger("tunnel-ssh.config")

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_PORT: int = int(os.getenv("TUNNEL_SSH_PORT", "222"))
DEFAULT_TOKEN: str | None = os.getenv("TUNNEL_SSH_TOKEN") or None
CONFIG_PATH: Path = Path(os.getenv("TUNNEL_SSH_CONFIG", Path.home() / ".tunnel-ssh.json"))


# ── Data models ──────────────────────────────────────────────────────────────

class ServerProfile(BaseModel):
    """A named remote server entry stored in ``~/.tunnel-ssh.json``."""

    host: str
    port: int = DEFAULT_PORT
    token: str | None = None


class TunnelConfig(BaseModel):
    """Top-level config file schema."""

    current_context: str | None = None
    servers: dict[str, ServerProfile] = {}
    user_id: str | None = None


# ── Persistence ──────────────────────────────────────────────────────────────

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
        logger.warning("Failed to parse config at %s — using defaults", CONFIG_PATH)
        return TunnelConfig()


def save_config(cfg: TunnelConfig) -> None:
    """Persist the config to disk."""
    CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    logger.debug("Config saved to %s", CONFIG_PATH)


def get_or_create_user_id() -> str:
    """Return the persistent user ID, generating one on first use."""
    cfg = load_config()
    if cfg.user_id:
        return cfg.user_id
    cfg.user_id = uuid.uuid4().hex
    save_config(cfg)
    logger.info("Generated new user ID: %s", cfg.user_id)
    return cfg.user_id


def resolve_server(name_or_host: str | None = None) -> ServerProfile:
    """Resolve a server argument.

    If *name_or_host* is ``None``, use the current context from config.
    If it matches a key in the config file, return that profile.
    Otherwise treat it as a raw hostname and return a default profile.
    """
    cfg = load_config()

    if name_or_host is None:
        if cfg.current_context and cfg.current_context in cfg.servers:
            logger.debug("Using current context '%s'", cfg.current_context)
            return cfg.servers[cfg.current_context]
        raise ValueError(
            "No server specified and no current context set. "
            "Use 'tunnel config use-context <name>' or pass a server argument."
        )

    if name_or_host in cfg.servers:
        logger.debug("Resolved profile '%s'", name_or_host)
        return cfg.servers[name_or_host]
    return ServerProfile(host=name_or_host)
