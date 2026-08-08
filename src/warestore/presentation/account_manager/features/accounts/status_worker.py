# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

from PyQt5.QtCore import QThread, pyqtSignal

from warestore.application.account_manager.controller import AccountManagerController
from warestore.presentation.account_manager.ui.avatars import ensure_avatar_downloaded


class StatusFetchWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(
        self,
        steamids: list[str],
        *,
        ctrl: AccountManagerController,
    ):
        super().__init__()
        self._ctrl = ctrl
        self.steamids = steamids

    def run(self):
        result: dict = {}
        for sid in self.steamids:
            if self.isInterruptionRequested():
                break
            status = self._ctrl.fetch_profile_statuses(
                [sid], on_progress=self.progress.emit
            )
            result.update(status)
            if self.isInterruptionRequested():
                break
            # Ban/level info needs an API key; both are no-ops without one.
            for found_sid, info in self._ctrl.fetch_bans([sid]).items():
                result.setdefault(found_sid, {})["ban"] = info
            if self.isInterruptionRequested():
                break
            for found_sid, level in self._ctrl.fetch_levels([sid]).items():
                result.setdefault(found_sid, {})["level"] = level
            if self.isInterruptionRequested():
                break
            # Fetch fresh avatars off the UI thread; hash-keyed cache means an
            # unchanged picture is downloaded at most once.
            info = result.get(sid, {})
            path = ensure_avatar_downloaded(
                info.get("avatar", ""), info.get("avatar_hash", "")
            )
            if path:
                info["avatar_path"] = path
        self.done.emit(result)
