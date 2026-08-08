"""Envelope glue: password + recovery both unwrap the same DEK (no Qt app needed)."""

import pytest

from warestore.infrastructure.persistence import vault_crypto
from warestore.presentation.account_manager.support import vault_unlock


def test_password_and_recovery_unlock_same_dek():
    dek = vault_crypto.new_dek()
    code = vault_crypto.generate_recovery_code()
    settings: dict = {}
    vault_unlock.set_password(settings, dek, "hunter2pass")
    vault_unlock.set_recovery(settings, dek, code)

    assert vault_unlock.unlock_password(settings, "hunter2pass") == dek
    assert vault_unlock.unlock_recovery(settings, code) == dek
    # recovery code is format/case-insensitive
    assert vault_unlock.unlock_recovery(settings, code.lower().replace("-", " ")) == dek


def test_wrong_password_raises():
    settings: dict = {}
    vault_unlock.set_password(settings, vault_crypto.new_dek(), "right-password")
    with pytest.raises(Exception):
        vault_unlock.unlock_password(settings, "wrong-password")


def test_change_password_keeps_dek_and_recovery_still_works():
    dek = vault_crypto.new_dek()
    code = vault_crypto.generate_recovery_code()
    settings: dict = {}
    vault_unlock.set_password(settings, dek, "old-password")
    vault_unlock.set_recovery(settings, dek, code)

    vault_unlock.set_password(settings, dek, "new-password")  # re-wrap same DEK
    assert vault_unlock.unlock_password(settings, "new-password") == dek
    with pytest.raises(Exception):
        vault_unlock.unlock_password(settings, "old-password")
    assert vault_unlock.unlock_recovery(settings, code) == dek  # recovery unchanged


class _SettingsRepo:
    def __init__(self):
        self.saved = None

    def save(self, settings):
        self.saved = dict(settings)


def test_unlock_upgrades_low_iteration_wrap_without_changing_dek(monkeypatch):
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 1000)
    dek = vault_crypto.new_dek()
    settings: dict = {}
    vault_unlock.set_password(settings, dek, "password")
    old_wrap = settings["vault_pw_wrap"]

    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 2000)
    repo = _SettingsRepo()
    unlocked = vault_unlock.unlock_password(
        settings, "password", settings_repo=repo
    )

    assert unlocked == dek
    assert settings["vault_kdf_iterations"] == 2000
    assert settings["vault_pw_kdf_iterations"] == 2000
    assert settings["vault_pw_wrap"] != old_wrap
    assert repo.saved == settings
    assert vault_unlock.unlock_password(settings, "password") == dek


def test_absent_iteration_metadata_defaults_to_legacy_600k(monkeypatch):
    dek = vault_crypto.new_dek()
    password = "legacy-password"
    salt = vault_crypto.new_salt()
    settings = {
        "vault_pw_salt": salt.hex(),
        "vault_pw_wrap": vault_crypto.wrap_dek(
            vault_crypto.derive_key(password, salt, 600_000), dek
        ),
    }
    # Keep current at the legacy value so this assertion tests the fallback,
    # independently of the transparent-upgrade branch.
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 600_000)

    assert vault_unlock.unlock_password(settings, password) == dek


def test_password_upgrade_preserves_old_recovery_iteration_count(monkeypatch):
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 1000)
    dek = vault_crypto.new_dek()
    code = vault_crypto.generate_recovery_code()
    settings: dict = {}
    vault_unlock.set_password(settings, dek, "password")
    vault_unlock.set_recovery(settings, dek, code)
    settings.pop("vault_pw_kdf_iterations")
    settings.pop("vault_rc_kdf_iterations")

    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 2000)
    assert vault_unlock.unlock_password(settings, "password") == dek
    assert settings["vault_rc_kdf_iterations"] == 1000
    assert vault_unlock.unlock_recovery(settings, code) == dek
