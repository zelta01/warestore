import pytest

from warestore.infrastructure.steam import process_gateway


class FakeProcess:
    def __init__(self, name: str = "steam.exe") -> None:
        self.info = {"name": name}
        self.pid = 42
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1


def _ignore_taskkill(monkeypatch) -> None:
    monkeypatch.setattr(process_gateway.subprocess, "run", lambda *args, **kwargs: None)


def test_kill_waits_until_process_list_is_empty(monkeypatch) -> None:
    """taskkill returns before the process is gone; writing loginusers.vdf while
    Steam is alive silently reverts the switch.
    """
    process = FakeProcess()
    snapshots = iter([[process], []])
    monkeypatch.setattr(
        process_gateway.psutil,
        "process_iter",
        lambda _attrs: iter(next(snapshots)),
    )
    monkeypatch.setattr(process_gateway.time, "sleep", lambda _seconds: None)
    times = iter([0.0, 0.0, 0.1])
    monkeypatch.setattr(process_gateway.time, "monotonic", lambda: next(times))
    _ignore_taskkill(monkeypatch)

    process_gateway.SteamProcessGateway().kill(timeout=1.0)

    assert process.kill_calls == 0


def test_kill_escalates_then_returns_when_process_exits(monkeypatch) -> None:
    process = FakeProcess()
    snapshots = iter([[process], []])
    monkeypatch.setattr(
        process_gateway.psutil,
        "process_iter",
        lambda _attrs: iter(next(snapshots)),
    )
    _ignore_taskkill(monkeypatch)

    process_gateway.SteamProcessGateway().kill(timeout=0.0)

    assert process.kill_calls == 1


def test_kill_raises_when_process_survives_deadline(monkeypatch) -> None:
    process = FakeProcess()
    monkeypatch.setattr(
        process_gateway.psutil,
        "process_iter",
        lambda _attrs: iter([process]),
    )
    _ignore_taskkill(monkeypatch)

    with pytest.raises(process_gateway.SteamStillRunningError, match="steam.exe"):
        process_gateway.SteamProcessGateway().kill(timeout=0.0)

    assert process.kill_calls == 1
