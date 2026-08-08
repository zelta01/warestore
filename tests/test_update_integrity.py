import hashlib
import io
import json
import os

import pytest

from warestore.infrastructure.external import update_gateway


class DownloadResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class ManifestResponse:
    def __init__(self, manifest: dict):
        self._manifest = manifest

    def raise_for_status(self):
        pass

    def json(self):
        return self._manifest


def _manifest(**overrides):
    manifest = {
        "latest_version": "99.0",
        "change_log": "security update",
        "download_url": "https://example.test/WareStoreSetup.exe",
        "download_sha256": "a" * 64,
        "force_update_below_version": "0",
    }
    manifest.update(overrides)
    return manifest


def test_update_manifest_requires_installer_digest(monkeypatch):
    manifest = _manifest()
    del manifest["download_sha256"]
    monkeypatch.setattr(
        update_gateway.requests,
        "get",
        lambda *args, **kwargs: ManifestResponse(manifest),
    )

    with pytest.raises(KeyError, match="download_sha256"):
        update_gateway.UpdateGateway().check()


def test_update_manifest_rejects_non_https_url(monkeypatch):
    monkeypatch.setattr(
        update_gateway.requests,
        "get",
        lambda *args, **kwargs: ManifestResponse(
            _manifest(download_url="http://example.test/update.exe")
        ),
    )

    with pytest.raises(ValueError, match="HTTPS"):
        update_gateway.UpdateGateway().check()


def test_installer_is_verified_before_promotion(monkeypatch, tmp_path):
    payload = b"signed installer bytes"
    digest = hashlib.sha256(payload).hexdigest()
    calls = []
    monkeypatch.setattr(update_gateway, "PRIVILEGED_DATA_DIR", str(tmp_path))

    def fake_secure(path):
        os.makedirs(path, exist_ok=True)
        return path

    def fake_open(url, *, timeout):
        calls.append((url, timeout))
        return DownloadResponse(payload)

    monkeypatch.setattr(update_gateway, "ensure_admin_only_dir", fake_secure)
    monkeypatch.setattr(update_gateway, "ensure_admin_only_file", lambda path: path)
    monkeypatch.setattr(update_gateway.urllib.request, "urlopen", fake_open)

    path = update_gateway.UpdateGateway().download_installer(
        "https://example.test/WareStoreSetup.exe", digest
    )

    assert os.path.isfile(path)
    assert open(path, "rb").read() == payload
    assert calls == [
        ("https://example.test/WareStoreSetup.exe", update_gateway._DOWNLOAD_TIMEOUT)
    ]


def test_installer_digest_mismatch_cleans_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(update_gateway, "PRIVILEGED_DATA_DIR", str(tmp_path))

    def fake_secure(path):
        os.makedirs(path, exist_ok=True)
        return path

    monkeypatch.setattr(update_gateway, "ensure_admin_only_dir", fake_secure)
    monkeypatch.setattr(update_gateway, "ensure_admin_only_file", lambda path: path)
    monkeypatch.setattr(
        update_gateway.urllib.request,
        "urlopen",
        lambda _url, timeout: DownloadResponse(b"tampered"),
    )

    with pytest.raises(ValueError, match="digest mismatch"):
        update_gateway.UpdateGateway().download_installer(
            "https://example.test/WareStoreSetup.exe", hashlib.sha256(b"good").hexdigest()
        )

    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.exe"))
