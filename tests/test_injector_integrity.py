"""Network-free injector integrity and bounded-download regressions."""

import hashlib
import io

import pytest

from warestore.infrastructure.steam import injector_stage


class Response(io.BytesIO):
    def __init__(self, data: bytes, *, advertise_size: bool = True):
        super().__init__(data)
        self.headers = (
            {"Content-Length": str(len(data))} if advertise_size else {}
        )


def _stage(monkeypatch, tmp_path, payload: bytes, expected: str):
    monkeypatch.setattr(injector_stage, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(injector_stage, "INJECTOR_SHA256", expected)
    monkeypatch.setattr(
        injector_stage.urllib.request,
        "urlopen",
        lambda _url, timeout: Response(payload),
    )


def test_hash_mismatch_cleans_part_and_preserves_destination(monkeypatch, tmp_path):
    destination = tmp_path / "injector.exe"
    destination.write_bytes(b"existing")
    payload = b"wrong"
    expected = hashlib.sha256(b"expected").hexdigest()
    actual = hashlib.sha256(payload).hexdigest()
    _stage(monkeypatch, tmp_path, payload, expected)

    with pytest.raises(
        injector_stage.InjectorIntegrityError, match="digest mismatch"
    ) as raised:
        injector_stage.download_injector()

    assert expected in str(raised.value)
    assert actual in str(raised.value)
    assert destination.read_bytes() == b"existing"
    assert not (tmp_path / "injector.exe.part").exists()


def test_hash_match_promotes_verified_file(monkeypatch, tmp_path):
    payload = b"verified injector"
    _stage(monkeypatch, tmp_path, payload, hashlib.sha256(payload).hexdigest())

    injector_stage.download_injector()

    assert (tmp_path / "injector.exe").read_bytes() == payload
    assert not (tmp_path / "injector.exe.part").exists()


def test_size_cap_aborts_and_cleans_partial(monkeypatch, tmp_path):
    payload = b"0123456789"
    monkeypatch.setattr(injector_stage, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(injector_stage, "MAX_INJECTOR_BYTES", 5)
    monkeypatch.setattr(
        injector_stage.urllib.request,
        "urlopen",
        lambda _url, timeout: Response(payload, advertise_size=False),
    )

    with pytest.raises(ValueError, match="exceeds"):
        injector_stage.download_injector()

    assert not (tmp_path / "injector.exe").exists()
    assert not (tmp_path / "injector.exe.part").exists()


def test_download_passes_timeout_to_urlopen(monkeypatch, tmp_path):
    payload = b"verified"
    calls = []
    monkeypatch.setattr(injector_stage, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        injector_stage, "INJECTOR_SHA256", hashlib.sha256(payload).hexdigest()
    )

    def fake_open(url, *, timeout):
        calls.append((url, timeout))
        return Response(payload)

    monkeypatch.setattr(injector_stage.urllib.request, "urlopen", fake_open)

    injector_stage.download_injector()

    assert calls == [(injector_stage.INJECTOR_URL, injector_stage.DOWNLOAD_TIMEOUT)]
