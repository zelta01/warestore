"""Injector discovery, protected staging, migration, and launch fallback."""

import hashlib
import io
import os
import sys

import pytest

from warestore.infrastructure.persistence.secure_dir import (
    ensure_admin_only_dir,
    ensure_admin_only_file,
    is_admin_only_dir,
    is_admin_only_file,
)
from warestore.infrastructure.steam import injector_stage, process_gateway
from warestore.presentation.account_manager.features.login.switch_worker import (
    SwitchWorker,
)


class Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def test_injector_path_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(injector_stage, "data_dir", lambda: str(tmp_path))
    assert injector_stage.injector_path() == str(tmp_path / "injector.exe")


def test_is_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(injector_stage, "data_dir", lambda: str(tmp_path))
    assert injector_stage.is_installed() is False
    (tmp_path / "injector.exe").write_bytes(b"X")
    assert injector_stage.is_installed() is True


def test_download_injector(monkeypatch, tmp_path):
    payload = b"INJECTOR"
    dest_dir = tmp_path / "bin"
    monkeypatch.setattr(injector_stage, "data_dir", lambda: str(dest_dir))
    monkeypatch.setattr(
        injector_stage, "INJECTOR_SHA256", hashlib.sha256(payload).hexdigest()
    )
    monkeypatch.setattr(
        injector_stage.urllib.request,
        "urlopen",
        lambda _url, timeout: Response(payload),
    )

    injector_stage.download_injector()

    assert injector_stage.is_installed()
    assert (dest_dir / "injector.exe").read_bytes() == payload


def test_download_failure_cleans_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(injector_stage, "data_dir", lambda: str(tmp_path))

    class BrokenResponse(Response):
        def read(self, size=-1):
            if self.tell():
                raise OSError("network down")
            return super().read(3)

    monkeypatch.setattr(
        injector_stage.urllib.request,
        "urlopen",
        lambda _url, timeout: BrokenResponse(b"partial"),
    )
    with pytest.raises(OSError):
        injector_stage.download_injector()
    assert not injector_stage.is_installed()
    assert not (tmp_path / "injector.exe.part").exists()


def test_frozen_data_dir_uses_privileged_programdata(monkeypatch, tmp_path):
    privileged = tmp_path / "ProgramData" / "WareStore"
    monkeypatch.setattr(injector_stage.sys, "frozen", True, raising=False)
    monkeypatch.setattr(injector_stage, "PRIVILEGED_DATA_DIR", str(privileged))
    monkeypatch.setattr(
        injector_stage, "ensure_admin_only_dir", lambda path: os.fspath(path)
    )

    assert injector_stage.data_dir() == str(privileged / "bin")


def test_legacy_user_writable_injector_is_deleted_not_moved(monkeypatch, tmp_path):
    legacy_root = tmp_path / "AppData" / "SteamLoginTool_CLI"
    privileged = tmp_path / "ProgramData" / "WareStore"
    legacy = legacy_root / "bin" / "injector.exe"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"unverified")
    monkeypatch.setattr(injector_stage.sys, "frozen", True, raising=False)
    monkeypatch.setattr(injector_stage, "ACCOUNT_MANAGER_DATA_DIR", str(legacy_root))
    monkeypatch.setattr(injector_stage, "PRIVILEGED_DATA_DIR", str(privileged))

    def fake_secure(path):
        os.makedirs(path, exist_ok=True)
        return path

    monkeypatch.setattr(injector_stage, "ensure_admin_only_dir", fake_secure)

    destination = injector_stage.data_dir()

    assert not legacy.exists()
    assert not (os.path.join(destination, "injector.exe")) == str(legacy)
    assert not os.path.exists(os.path.join(destination, "injector.exe"))


def test_launch_with_spoofer_rejects_bad_hash_and_falls_back(monkeypatch, tmp_path):
    injector = tmp_path / "injector.exe"
    injector.write_bytes(b"tampered")
    gateway = process_gateway.SteamProcessGateway()
    launched: list[bool] = []
    monkeypatch.setattr(
        injector_stage,
        "verify_injector",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            injector_stage.InjectorIntegrityError("digest mismatch")
        ),
    )
    monkeypatch.setattr(
        gateway, "launch", lambda *, open_cs2=False: launched.append(open_cs2)
    )
    monkeypatch.setattr(
        process_gateway.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("untrusted injector was executed"),
    )

    gateway.launch_with_spoofer(str(injector), open_cs2=True)

    assert launched == [True]


def test_untrusted_hardware_pool_falls_back_to_plain_launch(tmp_path):
    class Controller:
        def __init__(self):
            self.plain_launches = []

        def find_injector_exe(self):
            return str(tmp_path / "injector.exe")

        def ensure_hardware_pool(self, _path):
            return False

        def launch_steam(self, *, open_cs2=False):
            self.plain_launches.append(open_cs2)

        def launch_steam_with_spoofer(self, *args, **kwargs):
            pytest.fail("spoofer launched with an untrusted hardware pool")

    controller = Controller()
    worker = SwitchWorker("native", spoof_on_login=True, ctrl=controller)

    worker._launch_steam(True)

    assert controller.plain_launches == [True]


def test_steam_protocol_launch_does_not_use_a_command_shell(monkeypatch):
    gateway = process_gateway.SteamProcessGateway()
    opened = []
    monkeypatch.setattr(gateway, "install_path", lambda: None)
    monkeypatch.setattr(process_gateway.os, "startfile", opened.append)

    gateway.launch(open_cs2=True)

    assert opened == ["steam://rungameid/730"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DACL test")
def test_admin_only_directory_dacl(tmp_path):
    protected = str(tmp_path / "protected")
    os.makedirs(protected)
    privileged_file = os.path.join(protected, "artifact.exe")
    with open(privileged_file, "wb") as file:
        file.write(b"artifact")
    ensure_admin_only_dir(protected)
    ensure_admin_only_file(privileged_file)
    assert is_admin_only_dir(protected)
    assert is_admin_only_file(privileged_file)
