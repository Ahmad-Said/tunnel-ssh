"""Tests for the server helpers module."""

from tunnel_ssh.server.helpers import format_permissions


class TestFormatPermissions:
    def test_all_permissions(self) -> None:
        # 0o777 = rwxrwxrwx
        assert format_permissions(0o777) == "rwxrwxrwx"

    def test_no_permissions(self) -> None:
        assert format_permissions(0o000) == "---------"

    def test_typical_file(self) -> None:
        # 0o644 = rw-r--r--
        assert format_permissions(0o644) == "rw-r--r--"

    def test_typical_dir(self) -> None:
        # 0o755 = rwxr-xr-x
        assert format_permissions(0o755) == "rwxr-xr-x"

