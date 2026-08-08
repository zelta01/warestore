import os

import pytest

pytest.importorskip("PyQt5")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from warestore.presentation.account_manager.support import secret_clipboard


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_copy_secret_schedules_clear_and_clears_if_unchanged(app, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        secret_clipboard.QTimer,
        "singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )

    secret_clipboard.copy_secret("sensitive", clear_after_ms=1234)

    assert QApplication.clipboard().text() == "sensitive"
    assert scheduled[0][0] == 1234
    scheduled[0][1]()
    assert QApplication.clipboard().text() == ""


def test_copy_secret_does_not_clobber_new_clipboard_contents(app, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        secret_clipboard.QTimer,
        "singleShot",
        lambda _delay, callback: scheduled.append(callback),
    )

    secret_clipboard.copy_secret("sensitive")
    QApplication.clipboard().setText("something the user copied later")
    scheduled[0]()

    assert QApplication.clipboard().text() == "something the user copied later"


def test_history_exclusion_uses_windows_registered_clipboard_formats(app, monkeypatch):
    monkeypatch.setattr(secret_clipboard.QTimer, "singleShot", lambda *_args: None)

    secret_clipboard.copy_secret("recovery-code", exclude_from_history=True)
    mime = QApplication.clipboard().mimeData()

    assert mime.hasFormat(secret_clipboard._HISTORY_MIME)
    assert mime.hasFormat(secret_clipboard._CLOUD_MIME)
