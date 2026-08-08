import os

import vdf

from warestore.config.settings import STEAMID64_BASE
from warestore.domain.steam.services.login_service import SteamLoginService
from warestore.infrastructure.persistence.atomic import write_text
from warestore.infrastructure.persistence.file_guard import FileGuard
from warestore.infrastructure.steam.vdf_file_gateway import VdfFileGateway

STEAM_ID = str(STEAMID64_BASE + 12345)
ACCOUNT_NAME = "rollback_user"


class FakeProcess:
    def __init__(self, steam_dir: str, local_vdf: str) -> None:
        self._steam_dir = steam_dir
        self._local_vdf = local_vdf

    def install_path(self):
        return self._steam_dir

    def local_vdf_path(self):
        return self._local_vdf


class CountingFiles(VdfFileGateway):
    def __init__(self, fail_on: int | None = None) -> None:
        self.write_count = 0
        self._fail_on = fail_on

    def _after_write(self) -> None:
        self.write_count += 1
        if self.write_count == self._fail_on:
            raise OSError(f"write {self.write_count} failed")

    def write_text(self, file_path: str, text: str) -> None:
        super().write_text(file_path, text)
        self._after_write()

    def write_vdf(self, file_path: str, data: dict) -> None:
        super().write_vdf(file_path, data)
        self._after_write()


class FakePersona:
    def __init__(self, files: CountingFiles) -> None:
        self._files = files

    def set_state(self, steam_dir: str, steam_id: str, state: int) -> None:
        steam_id32 = str(int(steam_id) - STEAMID64_BASE)
        path = os.path.join(
            steam_dir, "userdata", steam_id32, "config", "localconfig.vdf"
        )
        self._files.write_text(path, f'"PersonaStateDesired"\t\t"{state}"\n')

    def set_remote_play(self, steam_dir: str, steam_id: str, enabled: bool) -> None:
        pass


class FakeCrypto:
    def encrypt(self, token: str, username: str) -> str:
        return "encrypted-token"

    def crc32_key(self, username: str) -> str:
        return "abcdef1"


class FakeRegistry:
    def set_autologin_with_remember(self, username: str) -> None:
        pass


class FakeTokens:
    def store(self, steam_id: str, username: str, token: str) -> None:
        pass


class FakeJwt:
    def is_valid_format(self, token: str) -> bool:
        return True

    def decode_steam_id(self, token: str) -> str:
        return STEAM_ID


class FakeParser:
    def sanitize_token(self, token: str) -> str:
        return token.strip()


def _paths(tmp_path):
    steam_dir = tmp_path / "Steam"
    config_dir = steam_dir / "config"
    config_path = config_dir / "config.vdf"
    loginusers_path = config_dir / "loginusers.vdf"
    localconfig_path = (
        steam_dir / "userdata" / "12345" / "config" / "localconfig.vdf"
    )
    local_vdf_path = tmp_path / "local.vdf"
    return steam_dir, config_path, loginusers_path, localconfig_path, local_vdf_path


def _seed(path, data: dict) -> None:
    write_text(str(path), vdf.dumps(data, pretty=True))


def _seed_required_files(tmp_path, *, include_localconfig: bool = True):
    paths = _paths(tmp_path)
    steam_dir, config_path, loginusers_path, localconfig_path, local_vdf_path = paths
    _seed(config_path, {"InstallConfigStore": {}})
    _seed(
        loginusers_path,
        {
            "users": {
                str(STEAMID64_BASE + 1): {
                    "AccountName": "existing",
                    "MostRecent": "1",
                }
            }
        },
    )
    if include_localconfig:
        _seed(localconfig_path, {"UserLocalConfigStore": {"friends": {}}})
    _seed(
        local_vdf_path,
        {
            "MachineUserConfigStore": {
                "Software": {"Valve": {"Steam": {"ConnectCache": {}}}}
            }
        },
    )
    return paths


def _service(steam_dir, local_vdf_path, files):
    return SteamLoginService(
        process=FakeProcess(str(steam_dir), str(local_vdf_path)),
        files=files,
        guard=FileGuard(),
        crypto=FakeCrypto(),
        registry=FakeRegistry(),
        persona=FakePersona(files),
        tokens=FakeTokens(),
        jwt=FakeJwt(),
        parser=FakeParser(),
    )


def test_third_write_failure_restores_all_four_files_byte_for_byte(tmp_path):
    paths = _seed_required_files(tmp_path)
    steam_dir, config_path, loginusers_path, localconfig_path, local_vdf_path = paths
    protected = [config_path, loginusers_path, localconfig_path, local_vdf_path]
    before = {path: path.read_bytes() for path in protected}
    files = CountingFiles(fail_on=3)

    result = _service(steam_dir, local_vdf_path, files).perform_token_login(
        f"{ACCOUNT_NAME}----token"
    )

    assert result is False
    assert files.write_count == 3
    assert {path: path.read_bytes() for path in protected} == before


def test_failed_login_removes_file_created_during_transaction(tmp_path):
    paths = _seed_required_files(tmp_path, include_localconfig=False)
    steam_dir, _config, _loginusers, localconfig_path, local_vdf_path = paths
    files = CountingFiles(fail_on=3)

    result = _service(steam_dir, local_vdf_path, files).perform_token_login(
        f"{ACCOUNT_NAME}----token"
    )

    assert result is False
    assert not localconfig_path.exists()
    assert not localconfig_path.with_name("localconfig.vdf.warestore.bak").exists()


def test_success_keeps_one_backup_for_each_touched_file(tmp_path):
    paths = _seed_required_files(tmp_path)
    steam_dir, config_path, loginusers_path, localconfig_path, local_vdf_path = paths
    files = CountingFiles()

    result = _service(steam_dir, local_vdf_path, files).perform_token_login(
        f"{ACCOUNT_NAME}----token"
    )

    assert result is True
    protected = [config_path, loginusers_path, localconfig_path, local_vdf_path]
    assert all(path.with_name(f"{path.name}.warestore.bak").is_file() for path in protected)
    assert len(list(tmp_path.rglob("*.warestore.bak"))) == 4
