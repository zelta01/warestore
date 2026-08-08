import io
import json

from warestore.infrastructure.steam import hardware_pool_gateway


class Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def _valid_pool() -> dict:
    return {
        "gpus": [
            {
                "name": "GPU",
                "vendor_id": "0x10de",
                "device_id": "0x0001",
                "vram_mb": 8192,
            }
        ],
        "ram_mb": [16384],
        "monitors": [{"width": 1920, "height": 1080, "refresh": 60}],
        "boards": [{"model": "Board", "manufacturer": "Vendor"}],
        "storage": [
            {"ssds": 1, "ssd_size": "1000G", "hdds": 0, "hdd_size": None}
        ],
        "sound_cards": ["Audio"],
        "display_models": ["Display"],
    }


def test_hardware_pool_is_bounded_and_validated_before_cache(monkeypatch, tmp_path):
    payload = json.dumps(_valid_pool()).encode()
    injector = tmp_path / "injector.exe"
    injector.write_bytes(b"injector")
    calls = []
    monkeypatch.setattr(
        hardware_pool_gateway, "_persistent_dir", lambda: str(tmp_path)
    )

    def fake_open(url, *, timeout):
        calls.append((url, timeout))
        return Response(payload)

    monkeypatch.setattr(
        hardware_pool_gateway.urllib.request, "urlopen", fake_open
    )

    assert hardware_pool_gateway.ensure(str(injector)) is True
    assert json.loads((tmp_path / "hardware_pool.json").read_text()) == _valid_pool()
    assert calls == [
        (hardware_pool_gateway._URL, hardware_pool_gateway._DOWNLOAD_TIMEOUT)
    ]


def test_invalid_hardware_pool_is_not_cached(monkeypatch, tmp_path):
    injector = tmp_path / "injector.exe"
    injector.write_bytes(b"injector")
    monkeypatch.setattr(
        hardware_pool_gateway, "_persistent_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        hardware_pool_gateway.urllib.request,
        "urlopen",
        lambda _url, timeout: Response(b'{"gpus": []}'),
    )

    assert hardware_pool_gateway.ensure(str(injector)) is False
    assert not (tmp_path / "hardware_pool.json").exists()
    assert not (tmp_path / "hardware_pool.json.part").exists()
