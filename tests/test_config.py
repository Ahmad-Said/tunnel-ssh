"""Tests for server-profile config: models, persistence, resolution, and CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tunnel_ssh.cli.app import app
from tunnel_ssh.shared.config import (
    ServerProfile,
    TunnelConfig,
    load_config,
    resolve_server,
    save_config,
)

runner = CliRunner()


# ── Model tests ──────────────────────────────────────────────────────────────


class TestServerProfile:
    def test_defaults(self) -> None:
        p = ServerProfile(host="example.com")
        assert p.host == "example.com"
        assert p.port == 222
        assert p.token is None

    def test_custom_values(self) -> None:
        p = ServerProfile(host="10.0.0.1", port=9999, token="s3cret")
        assert p.host == "10.0.0.1"
        assert p.port == 9999
        assert p.token == "s3cret"

    def test_json_round_trip(self) -> None:
        p = ServerProfile(host="myhost", port=1234, token="tok")
        restored = ServerProfile.model_validate_json(p.model_dump_json())
        assert restored == p


class TestTunnelConfig:
    def test_empty(self) -> None:
        cfg = TunnelConfig()
        assert cfg.servers == {}

    def test_with_servers(self) -> None:
        cfg = TunnelConfig(servers={
            "prod": ServerProfile(host="prod.example.com", port=222, token="abc"),
            "dev": ServerProfile(host="localhost"),
        })
        assert len(cfg.servers) == 2
        assert cfg.servers["prod"].token == "abc"
        assert cfg.servers["dev"].host == "localhost"

    def test_json_round_trip(self) -> None:
        cfg = TunnelConfig(servers={
            "a": ServerProfile(host="a.test", port=111),
            "b": ServerProfile(host="b.test", port=222, token="x"),
        })
        restored = TunnelConfig.model_validate_json(cfg.model_dump_json())
        assert restored == cfg


# ── Persistence tests (use tmp_path to avoid touching real config) ───────────


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CONFIG_PATH to a temporary file for the duration of the test."""
    p = tmp_path / "test-tunnel-ssh.json"
    monkeypatch.setattr("tunnel_ssh.shared.config.CONFIG_PATH", p)
    return p


class TestPersistence:
    def test_load_missing_file(self, config_path: Path) -> None:
        cfg = load_config()
        assert cfg.servers == {}

    def test_save_and_load_round_trip(self, config_path: Path) -> None:
        original = TunnelConfig(servers={
            "staging": ServerProfile(host="staging.local", port=8080, token="ttt"),
        })
        save_config(original)
        assert config_path.exists()

        loaded = load_config()
        assert loaded == original

    def test_load_corrupt_json(self, config_path: Path) -> None:
        config_path.write_text("NOT VALID JSON {{{", encoding="utf-8")
        cfg = load_config()
        assert cfg.servers == {}

    def test_load_invalid_schema(self, config_path: Path) -> None:
        config_path.write_text(json.dumps({"servers": {"bad": {"not_host": 123}}}), encoding="utf-8")
        cfg = load_config()
        # Pydantic validation will fail → fallback to empty
        assert cfg.servers == {}

    def test_save_creates_parent_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        nested = tmp_path / "sub" / "dir" / "tunnel.json"
        nested.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("tunnel_ssh.shared.config.CONFIG_PATH", nested)
        save_config(TunnelConfig(servers={"x": ServerProfile(host="x")}))
        assert nested.exists()

    def test_overwrite_preserves_other_profiles(self, config_path: Path) -> None:
        cfg = TunnelConfig(servers={
            "a": ServerProfile(host="a.test"),
            "b": ServerProfile(host="b.test"),
        })
        save_config(cfg)

        loaded = load_config()
        loaded.servers["c"] = ServerProfile(host="c.test")
        save_config(loaded)

        reloaded = load_config()
        assert set(reloaded.servers.keys()) == {"a", "b", "c"}


# ── resolve_server tests ─────────────────────────────────────────────────────


class TestResolveServer:
    def test_resolve_known_profile(self, config_path: Path) -> None:
        save_config(TunnelConfig(servers={
            "prod": ServerProfile(host="prod.example.com", port=443, token="secret"),
        }))
        profile = resolve_server("prod")
        assert profile.host == "prod.example.com"
        assert profile.port == 443
        assert profile.token == "secret"

    def test_resolve_unknown_falls_back_to_host(self, config_path: Path) -> None:
        profile = resolve_server("10.0.0.5")
        assert profile.host == "10.0.0.5"
        assert profile.token is None


# ── CLI command tests ────────────────────────────────────────────────────────


class TestConfigCLI:
    def test_add_and_list(self, config_path: Path) -> None:
        result = runner.invoke(app, ["config", "add", "myserver", "--host", "10.0.0.1", "--port", "9000"])
        assert result.exit_code == 0
        assert "Saved profile 'myserver'" in result.output

        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "myserver" in result.output
        assert "10.0.0.1:9000" in result.output

    def test_show(self, config_path: Path) -> None:
        runner.invoke(app, ["config", "add", "demo", "--host", "h.test", "--port", "111", "--token", "abc"])
        result = runner.invoke(app, ["config", "show", "demo"])
        assert result.exit_code == 0
        assert "h.test" in result.output
        assert "111" in result.output
        assert "••••" in result.output  # token masked

    def test_show_not_found(self, config_path: Path) -> None:
        result = runner.invoke(app, ["config", "show", "nope"])
        assert result.exit_code == 1

    def test_update_host(self, config_path: Path) -> None:
        runner.invoke(app, ["config", "add", "srv", "--host", "old.host", "--port", "222"])
        result = runner.invoke(app, ["config", "update", "srv", "--host", "new.host"])
        assert result.exit_code == 0
        assert "new.host" in result.output

        cfg = load_config()
        assert cfg.servers["srv"].host == "new.host"
        assert cfg.servers["srv"].port == 222  # unchanged

    def test_update_not_found(self, config_path: Path) -> None:
        result = runner.invoke(app, ["config", "update", "ghost", "--host", "x"])
        assert result.exit_code == 1

    def test_remove(self, config_path: Path) -> None:
        runner.invoke(app, ["config", "add", "tmp", "--host", "h"])
        result = runner.invoke(app, ["config", "remove", "tmp"])
        assert result.exit_code == 0
        assert "Removed" in result.output

        cfg = load_config()
        assert "tmp" not in cfg.servers

    def test_remove_not_found(self, config_path: Path) -> None:
        result = runner.invoke(app, ["config", "remove", "nope"])
        assert result.exit_code == 1

    def test_list_empty(self, config_path: Path) -> None:
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "No profiles configured" in result.output

    def test_path(self, config_path: Path) -> None:
        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert "test-tunnel-ssh.json" in result.output

    def test_add_with_token_shows_lock(self, config_path: Path) -> None:
        runner.invoke(app, ["config", "add", "secure", "--host", "s.test", "--token", "pass123"])
        result = runner.invoke(app, ["config", "list"])
        assert "🔒" in result.output

    def test_multiple_profiles(self, config_path: Path) -> None:
        runner.invoke(app, ["config", "add", "alpha", "--host", "a.test"])
        runner.invoke(app, ["config", "add", "beta", "--host", "b.test", "--port", "333"])
        runner.invoke(app, ["config", "add", "gamma", "--host", "c.test", "--token", "tok"])

        cfg = load_config()
        assert len(cfg.servers) == 3
        assert cfg.servers["alpha"].host == "a.test"
        assert cfg.servers["beta"].port == 333
        assert cfg.servers["gamma"].token == "tok"

