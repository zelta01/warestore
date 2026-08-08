import pytest

from warestore.infrastructure.persistence import export_bundle, vault_crypto
from warestore.infrastructure.persistence.secure_store import (
    SecureJsonStore,
    SecureStoreUnavailable,
)


def test_round_trip_returns_original_entries(monkeypatch):
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 1000)
    entries = ["alice----eyA.one", "eyA.two", "ünicode----eyA.three"]
    blob = export_bundle.export_encrypted(entries, "correct horse battery staple")

    assert blob.startswith(b"WSX1")
    assert export_bundle.import_encrypted(blob, "correct horse battery staple") == entries


def test_wrong_passphrase_raises_without_leaking_it(monkeypatch):
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 1000)
    secret = "definitely-not-in-an-error"
    blob = export_bundle.export_encrypted(["eyA.token"], "right passphrase")

    with pytest.raises(Exception) as raised:
        export_bundle.import_encrypted(blob, secret)
    assert secret not in str(raised.value)


def test_old_iteration_count_is_read_from_header(monkeypatch):
    """Regression: changing the current default must not strand old bundles."""
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 1000)
    blob = export_bundle.export_encrypted(["eyA.old"], "passphrase")
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 6000)

    assert export_bundle.import_encrypted(blob, "passphrase") == ["eyA.old"]


def test_bundle_and_secure_store_formats_are_not_interchangeable(tmp_path, monkeypatch):
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 1000)
    bundle = export_bundle.export_encrypted(["eyA.token"], "passphrase")
    bundle_path = tmp_path / "tokens.wsx"
    bundle_path.write_bytes(bundle)

    with pytest.raises(SecureStoreUnavailable):
        SecureJsonStore(str(bundle_path)).read(strict=True)

    vault_path = tmp_path / "tokens.json"
    SecureJsonStore(str(vault_path), key=b"k" * 32).write({"a": 1})
    with pytest.raises(ValueError, match="WSX1"):
        export_bundle.import_encrypted(vault_path.read_bytes(), "passphrase")


@pytest.mark.parametrize("mutation", ["truncate", "header", "payload"])
def test_truncated_or_corrupt_bundle_raises_cleanly(monkeypatch, mutation):
    monkeypatch.setattr(vault_crypto, "PBKDF2_ITERATIONS", 1000)
    blob = bytearray(export_bundle.export_encrypted(["eyA.token"], "passphrase"))
    if mutation == "truncate":
        blob = blob[:20]
    elif mutation == "header":
        blob[4] = 99
    else:
        blob[-1] ^= 0xFF

    with pytest.raises(Exception):
        export_bundle.import_encrypted(bytes(blob), "passphrase")
