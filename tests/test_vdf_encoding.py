import pytest

from warestore.infrastructure.steam.vdf_file_gateway import VdfFileGateway


def test_utf8_non_ascii_round_trip_is_byte_identical(tmp_path):
    path = tmp_path / "localconfig.vdf"
    original = '"PersonaName"\t\t"İpek 日本語"\r\n'.encode()
    path.write_bytes(original)
    gateway = VdfFileGateway()

    gateway.write_text(str(path), gateway.read_text(str(path)))

    assert path.read_bytes() == original


def test_utf16_fallback_preserves_text_without_replacement(tmp_path):
    path = tmp_path / "legacy.vdf"
    original = '"PersonaName"\t\t"Łukasz"\n'
    path.write_bytes(original.encode("utf-16"))
    gateway = VdfFileGateway()

    text = gateway.read_text(str(path))
    gateway.write_text(str(path), text)

    assert text == original
    assert "\ufffd" not in text
    assert gateway.read_text(str(path)) == original


def test_ascii_prefix_does_not_hide_later_utf8_content(tmp_path):
    """Regression: chardet on only the first 8 KB missed later persona text."""
    path = tmp_path / "large-localconfig.vdf"
    original = (" " * 8192 + '"PersonaName"\t\t"Çağla"\n').encode()
    path.write_bytes(original)
    gateway = VdfFileGateway()

    gateway.write_text(str(path), gateway.read_text(str(path)))

    assert path.read_bytes() == original


def test_read_text_never_silently_replaces_undecodable_bytes(tmp_path, monkeypatch):
    path = tmp_path / "broken.vdf"
    path.write_bytes(b'"PersonaName" "\xff"')
    gateway = VdfFileGateway()
    monkeypatch.setattr(gateway, "detect_encoding", lambda _path: "ascii")

    with pytest.raises(UnicodeDecodeError):
        gateway.read_text(str(path))
