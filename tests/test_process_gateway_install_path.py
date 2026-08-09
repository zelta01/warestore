import os
import sys
from types import SimpleNamespace

from warestore.infrastructure.steam import process_gateway


class _Key:
    def __init__(self, value: str) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_install_path_falls_back_to_machine_registry(monkeypatch, tmp_path) -> None:
    steam_dir = tmp_path / "Steam"
    steam_dir.mkdir()
    (steam_dir / "steam.exe").write_bytes(b"")

    def open_key(root, _subkey, *_args):
        if root == "HKCU":
            raise OSError("per-user key missing")
        return _Key(str(steam_dir))

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        HKEY_LOCAL_MACHINE="HKLM",
        KEY_READ=1,
        KEY_WOW64_32KEY=2,
        KEY_WOW64_64KEY=4,
        OpenKey=open_key,
        QueryValueEx=lambda key, _name: (key.value, 1),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    assert process_gateway.SteamProcessGateway().install_path() == os.path.normpath(
        str(steam_dir)
    )
