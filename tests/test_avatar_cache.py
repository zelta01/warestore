# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import os
import io

import warestore.presentation.account_manager.ui.avatars as av


class Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def test_ensure_avatar_downloaded_caches_by_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "_AVATAR_CACHE_DIR", str(tmp_path / "avatars"))
    calls = {"n": 0}

    def fake_open(url, *, timeout):
        calls["n"] += 1
        return Response(b"img-bytes")

    monkeypatch.setattr(av.urllib.request, "urlopen", fake_open)

    p1 = av.ensure_avatar_downloaded("https://avatars.steamstatic.com/abc_full.jpg", "abc")
    assert p1 and os.path.exists(p1) and calls["n"] == 1

    # second call for the same hash: served from cache, no re-download
    p2 = av.ensure_avatar_downloaded("https://avatars.steamstatic.com/abc_full.jpg", "abc")
    assert p2 == p1 and calls["n"] == 1

    # different hash: downloads again to a different file
    p3 = av.ensure_avatar_downloaded("https://avatars.steamstatic.com/def_full.jpg", "def")
    assert p3 != p1 and calls["n"] == 2


def test_ensure_avatar_downloaded_noop_without_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "_AVATAR_CACHE_DIR", str(tmp_path))
    assert av.ensure_avatar_downloaded("", "abc") is None
    assert av.ensure_avatar_downloaded("https://avatars.steamstatic.com/y", "") is None


def test_ensure_avatar_downloaded_cleans_up_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "_AVATAR_CACHE_DIR", str(tmp_path / "avatars"))

    def boom(url, *, timeout):
        raise OSError("network down")

    monkeypatch.setattr(av.urllib.request, "urlopen", boom)
    assert av.ensure_avatar_downloaded(
        "https://avatars.steamstatic.com/z_full.jpg", "z"
    ) is None
    # no leftover .part file
    assert not os.path.exists(av.cached_avatar_path("z") + ".part")


def test_avatar_cache_rejects_path_traversal_and_untrusted_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "_AVATAR_CACHE_DIR", str(tmp_path / "avatars"))
    assert av.ensure_avatar_downloaded(
        "https://avatars.steamstatic.com/a.jpg", "../../escape"
    ) is None
    assert av.ensure_avatar_downloaded("file:///etc/passwd", "safe") is None
    assert av.ensure_avatar_downloaded("https://example.test/a.jpg", "safe") is None
    assert not list(tmp_path.rglob("*"))
