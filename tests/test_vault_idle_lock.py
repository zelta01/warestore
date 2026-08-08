import os

import pytest

pytest.importorskip("PyQt5")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from warestore.presentation.account_manager.support.vault_idle_lock import VaultIdleLock


class _Workers:
    def __init__(self, critical=False):
        self.critical = critical

    def any_running(self, *, critical_only=False):
        return bool(critical_only and self.critical)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_timeout_locks_when_no_critical_worker_is_running(app):
    calls = []
    idle = VaultIdleLock(
        app,
        minutes=5,
        enabled=lambda: True,
        workers=_Workers(),
        lock=lambda: calls.append("locked"),
        unlock=lambda: True,
    )
    idle._on_timeout()

    assert calls == ["locked"]
    assert idle.is_locked


def test_timeout_is_deferred_while_critical_worker_runs(app):
    calls = []
    workers = _Workers(critical=True)
    idle = VaultIdleLock(
        app,
        minutes=5,
        enabled=lambda: True,
        workers=workers,
        lock=lambda: calls.append("locked"),
        unlock=lambda: True,
    )
    idle._on_timeout()
    assert calls == []
    assert not idle.is_locked

    workers.critical = False
    idle._on_timeout()
    assert calls == ["locked"]
