"""Tests for shared models and config."""

from tunnel_ssh.shared.config import ServerProfile, TunnelConfig
from tunnel_ssh.shared.http import auth_headers, base_url, ws_url
from tunnel_ssh.shared.models import CommandOutput, CommandPayload, DirectoryListing, FileItem
from tunnel_ssh.ui.helpers import human_size, human_time, is_root_path, join_path, parent_path

# ── Models ───────────────────────────────────────────────────────────────────

class TestFileItem:
    def test_file_item_basic(self) -> None:
        item = FileItem(name="test.txt", is_dir=False, size=1024)
        assert item.name == "test.txt"
        assert item.is_dir is False
        assert item.size == 1024

    def test_directory_listing(self) -> None:
        listing = DirectoryListing(path="/tmp", items=[
            FileItem(name="a", is_dir=True),
            FileItem(name="b.txt", is_dir=False, size=42),
        ])
        assert listing.path == "/tmp"
        assert len(listing.items) == 2

    def test_command_round_trip(self) -> None:
        payload = CommandPayload(command="ls -la", cwd="/home")
        json_str = payload.model_dump_json()
        restored = CommandPayload.model_validate_json(json_str)
        assert restored.command == "ls -la"
        assert restored.cwd == "/home"

    def test_command_output(self) -> None:
        out = CommandOutput(stream="stdout", data="hello\n")
        assert out.stream == "stdout"
        assert out.data == "hello\n"


# ── Config ───────────────────────────────────────────────────────────────────

class TestConfig:
    def test_server_profile_defaults(self) -> None:
        profile = ServerProfile(host="example.com")
        assert profile.host == "example.com"
        assert profile.token is None

    def test_tunnel_config_empty(self) -> None:
        cfg = TunnelConfig()
        assert cfg.servers == {}


# ── HTTP helpers ─────────────────────────────────────────────────────────────

class TestHttp:
    def test_auth_headers_with_token(self) -> None:
        assert auth_headers("secret") == {"Authorization": "Bearer secret"}

    def test_auth_headers_without_token(self) -> None:
        assert auth_headers(None) == {}

    def test_base_url(self) -> None:
        assert base_url("myhost", 222) == "http://myhost:222"

    def test_ws_url_no_token(self) -> None:
        assert ws_url("myhost", 222) == "ws://myhost:222/ws/execute"

    def test_ws_url_with_token(self) -> None:
        assert ws_url("myhost", 222, "tok") == "ws://myhost:222/ws/execute?token=tok"


# ── UI helpers ───────────────────────────────────────────────────────────────

class TestUiHelpers:
    def test_human_size(self) -> None:
        assert human_size(500) == "500.0 B"
        assert "KB" in human_size(2048)

    def test_human_time(self) -> None:
        result = human_time(0)
        assert "1970" in result

    def test_parent_path_posix(self) -> None:
        assert parent_path("/home/user/docs") == "/home/user"

    def test_parent_path_windows(self) -> None:
        assert parent_path("C:\\Users\\me\\docs") == "C:\\Users\\me"

    def test_join_path_posix(self) -> None:
        assert join_path("/home/user", "file.txt") == "/home/user/file.txt"

    def test_join_path_windows(self) -> None:
        assert join_path("C:\\Users", "file.txt") == "C:\\Users\\file.txt"

    def test_is_root_path(self) -> None:
        assert is_root_path("/") is True
        assert is_root_path("C:\\") is True
        assert is_root_path("/home") is False

