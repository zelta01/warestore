import os

import pytest

from warestore.infrastructure.persistence.atomic import write_bytes, write_text


def test_writing_fresh_path_creates_expected_content(tmp_path):
    path = tmp_path / "fresh.txt"

    write_text(str(path), "hello")

    assert path.read_text(encoding="utf-8") == "hello"


def test_replacing_existing_file_leaves_no_temp_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("old", encoding="utf-8")

    write_text(str(path), "new")

    assert path.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob("*.tmp")) == []


def test_mid_write_failure_preserves_original_and_removes_temp(monkeypatch, tmp_path):
    """Regression: a failed fsync must not truncate the existing destination."""
    path = tmp_path / "loginusers.vdf"
    original = b"all Steam accounts"
    path.write_bytes(original)

    def fail_fsync(_fd):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="simulated disk failure"):
        write_bytes(str(path), b"partial replacement")

    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_parent_directory_is_created(tmp_path):
    path = tmp_path / "new" / "nested" / "vault.bin"

    write_bytes(str(path), b"vault")

    assert path.read_bytes() == b"vault"
