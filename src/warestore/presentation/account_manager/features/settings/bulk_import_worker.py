# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import logging

from PyQt5.QtCore import QThread, pyqtSignal

from warestore.application.account_manager.controller import AccountManagerController
from warestore.infrastructure.steam.process_gateway import SteamStillRunningError

logger = logging.getLogger(__name__)


class BulkImportWorker(QThread):
    shutdown_critical = True
    shutdown_description = "bulk import"

    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    done = pyqtSignal(int, int)

    def __init__(
        self,
        tokens: list[str],
        *,
        ctrl: AccountManagerController,
    ):
        super().__init__()
        self._ctrl = ctrl
        self.tokens = tokens

    def run(self):
        success, total = 0, len(self.tokens)
        for i, tok in enumerate(self.tokens):
            # A token login is one indivisible file-mutation pipeline. Honour
            # cancellation only at the safe boundary between tokens.
            if self.isInterruptionRequested():
                break
            self.progress.emit(i + 1, total)
            self.status.emit(f"Importing {i + 1} / {total}…")
            try:
                self._ctrl.kill_steam()
                if self._ctrl.perform_token_login(tok):
                    success += 1
            except SteamStillRunningError as exc:
                logger.error("Bulk import stopped because Steam is still running: %s", exc)
                self.status.emit(
                    "Steam is still running — bulk import stopped to protect loginusers.vdf."
                )
                break
            except Exception as exc:
                logger.error(f"Bulk import token {i + 1} error: {exc}")
        self.done.emit(success, total)
