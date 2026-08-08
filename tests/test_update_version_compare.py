import pytest

from warestore.infrastructure.external import update_gateway


class _Response:
    def __init__(self, manifest: dict):
        self._manifest = manifest

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._manifest


def _manifest(**overrides) -> dict:
    manifest = {
        "latest_version": "3.4",
        "force_update_below_version": "3",
        "change_log": "changes",
        "download_url": "https://example.test/WareStoreSetup.exe",
        "download_sha256": "a" * 64,
    }
    manifest.update(overrides)
    return manifest


def _check(monkeypatch, current: str, manifest: dict) -> dict:
    monkeypatch.setattr(update_gateway, "CURRENT_VERSION", current)
    monkeypatch.setattr(
        update_gateway.requests,
        "get",
        lambda *args, **kwargs: _Response(manifest),
    )
    return update_gateway.UpdateGateway().check()


@pytest.mark.parametrize(
    ("current", "force_below", "expected"),
    [
        ("3.4", "3", False),
        ("3.10", "3.9", False),
        ("3.10.0", "3.9.0", False),
        ("10.0.0", "9.0.0", False),
        ("3.9.0", "3.10.0", True),
    ],
)
def test_force_update_uses_numeric_version_order(
    monkeypatch, current, force_below, expected
):
    """Regression: lexicographic comparison treated 3.10 as older than 3.9."""
    info = _check(
        monkeypatch,
        current,
        _manifest(latest_version=current, force_update_below_version=force_below),
    )

    assert info["force_update"] is expected


def test_short_and_padded_versions_compare_equal(monkeypatch):
    info = _check(
        monkeypatch,
        "3",
        _manifest(latest_version="3.0.0", force_update_below_version="3.0.0"),
    )

    assert info["update_available"] is False
    assert info["force_update"] is True


def test_newer_local_build_has_no_update_available(monkeypatch):
    info = _check(monkeypatch, "3.10", _manifest(latest_version="3.9"))

    assert info["update_available"] is False


@pytest.mark.parametrize(
    "manifest",
    [
        {
            key: value
            for key, value in _manifest(force_update_below_version="99").items()
            if key != "latest_version"
        },
        _manifest(latest_version="next"),
        {
            key: value
            for key, value in _manifest(latest_version="99").items()
            if key != "force_update_below_version"
        },
        _manifest(force_update_below_version="three"),
        _manifest(download_url="https://["),
    ],
)
def test_malformed_manifest_is_ignored(monkeypatch, manifest):
    info = _check(monkeypatch, "3.4", manifest)

    assert info["update_available"] is False
    assert info["force_update"] is False
