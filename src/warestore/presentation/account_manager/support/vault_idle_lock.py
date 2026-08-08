# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Application-wide user-activity timer for the password vault."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QEvent, QObject, QTimer

from warestore.presentation.account_manager.support.worker_registry import WorkerRegistry


class VaultIdleLock(QObject):
    """Drop the session key after inactivity and unlock on the next real input."""

    _ACTIVITY_EVENTS = frozenset(
        {
            QEvent.KeyPress,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseMove,
            QEvent.Wheel,
            QEvent.TouchBegin,
            QEvent.TouchUpdate,
        }
    )
    _UNLOCK_EVENTS = frozenset(
        {QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.Wheel, QEvent.TouchBegin}
    )

    def __init__(
        self,
        parent: QObject,
        *,
        minutes: int,
        enabled: Callable[[], bool],
        workers: WorkerRegistry,
        lock: Callable[[], None],
        unlock: Callable[[], bool],
    ) -> None:
        super().__init__(parent)
        self._minutes = max(0, int(minutes))
        self._enabled = enabled
        self._workers = workers
        self._lock_callback = lock
        self._unlock_callback = unlock
        self._locked = False
        self._unlocking = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self.reset()

    @property
    def is_locked(self) -> bool:
        return self._locked

    def set_minutes(self, minutes: int) -> None:
        self._minutes = max(0, int(minutes))
        self.reset()

    def reset(self) -> None:
        if self._locked or not self._minutes or not self._enabled():
            self._timer.stop()
            return
        self._timer.start(self._minutes * 60_000)

    def _on_timeout(self) -> None:
        if self._locked or not self._minutes or not self._enabled():
            return
        if self._workers.any_running(critical_only=True):
            # Re-check soon after the worker reaches its safe completion point.
            self._timer.start(1000)
            return
        self._lock_callback()
        self._locked = True

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type not in self._ACTIVITY_EVENTS or self._unlocking:
            return False

        if self._locked:
            if event_type not in self._UNLOCK_EVENTS:
                return False
            self._unlocking = True
            try:
                unlocked = self._unlock_callback()
            finally:
                self._unlocking = False
            if not unlocked:
                return True  # swallow the click/key that could not be authorized
            self._locked = False
        self.reset()
        return False
