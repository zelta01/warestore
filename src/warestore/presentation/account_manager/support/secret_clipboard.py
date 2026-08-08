# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Short-lived clipboard handling for refresh tokens and recovery codes."""

from __future__ import annotations

import hashlib

from PyQt5.QtCore import QMimeData, QTimer
from PyQt5.QtWidgets import QApplication

_HISTORY_MIME = (
    'application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"'
)
_CLOUD_MIME = (
    'application/x-qt-windows-mime;value="CanUploadToCloudClipboard"'
)


def copy_secret(
    text: str,
    *,
    clear_after_ms: int = 60_000,
    exclude_from_history: bool = False,
) -> None:
    """Copy a secret and clear it after a delay if it is still unchanged.

    Auto-clearing narrows the exposure window but does not by itself defeat
    Windows clipboard history.  ``exclude_from_history`` additionally asks
    Windows not to include this item in history or cloud clipboard; other
    clipboard managers may ignore those advisory formats.
    """
    clipboard = QApplication.clipboard()
    if exclude_from_history:
        mime = QMimeData()
        mime.setText(text)
        # Registered Windows clipboard formats documented for Cloud Clipboard.
        # A zero DWORD requests exclusion. Qt preserves these alongside text.
        mime.setData(_HISTORY_MIME, b"\x00\x00\x00\x00")
        mime.setData(_CLOUD_MIME, b"\x00\x00\x00\x00")
        clipboard.setMimeData(mime)
    else:
        clipboard.setText(text)

    expected = hashlib.sha256(text.encode("utf-8")).digest()

    def clear_if_unchanged() -> None:
        current = clipboard.text()
        if hashlib.sha256(current.encode("utf-8")).digest() == expected:
            clipboard.clear()

    QTimer.singleShot(max(0, int(clear_after_ms)), clear_if_unchanged)
