"""Regression coverage for v3.4's unsafe dead-token pre-filter."""

import base64
import json
import time
from types import SimpleNamespace

import pytest

from warestore.application.account_manager.controller import AccountManagerController
from warestore.domain.auth.jwt_service import (
    SteamJwtService,
    TokenVerdict,
    is_expired_beyond_grace,
)


def _jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (
            lambda now: _jwt({"iss": "steam", "aud": "client", "exp": now + 86_400}),
            TokenVerdict.VALID,
        ),
        (
            lambda now: _jwt({"iss": "steam", "aud": ["web"], "exp": now + 86_400}),
            TokenVerdict.UNRECOGNISED,
        ),
        (
            lambda now: _jwt({"iss": "steam3", "aud": "client", "exp": now + 86_400}),
            TokenVerdict.UNRECOGNISED,
        ),
        (
            lambda now: _jwt({"iss": "steam", "exp": now + 86_400}),
            TokenVerdict.UNRECOGNISED,
        ),
        (
            lambda now: _jwt({"iss": "steam", "aud": "client", "exp": now - 86_400}),
            TokenVerdict.EXPIRED,
        ),
        (lambda _now: "malformed garbage", TokenVerdict.MALFORMED),
    ],
)
def test_token_shapes_do_not_collapse_unexpected_claims_into_expiry(token, expected):
    """A valid JWT with unexpected aud/iss must never classify as EXPIRED."""
    verdict, _expires_in = SteamJwtService().classify(token(int(time.time())))
    assert verdict is expected


def test_unrecognised_is_never_safe_for_the_offline_dead_prefilter():
    assert not is_expired_beyond_grace(TokenVerdict.UNRECOGNISED, -86_400)


class _TokenRepo:
    def __init__(self, tokens: dict):
        self.tokens = tokens
        self.saved = None

    def load_all(self):
        return dict(self.tokens)

    def save_all(self, tokens):
        self.saved = tokens
        self.tokens = tokens


def _controller_with_token(token: str) -> tuple[AccountManagerController, _TokenRepo]:
    repo = _TokenRepo({"1": {"username": "alice", "token": token}})
    facade = SimpleNamespace(tokens=repo, jwt=SteamJwtService())
    return AccountManagerController(facade), repo


def test_purge_expired_tokens_keeps_unrecognised_token_in_vault():
    token = _jwt(
        {"iss": "steam3", "aud": ["web"], "exp": int(time.time()) - 86_400}
    )
    controller, repo = _controller_with_token(token)

    assert controller.purge_expired_tokens() == 0
    assert repo.tokens["1"]["token"] == token
    assert repo.saved is None


def test_clock_skew_grace_does_not_flag_token_expired_two_seconds_ago():
    token = _jwt(
        {"iss": "steam", "aud": "client", "exp": int(time.time()) - 2}
    )
    verdict, expires_in = SteamJwtService().classify(token)
    assert verdict is TokenVerdict.EXPIRED
    assert not is_expired_beyond_grace(verdict, expires_in)

    controller, repo = _controller_with_token(token)
    assert controller.purge_expired_tokens() == 0
    assert "1" in repo.tokens


def test_dead_accounts_dialog_starts_with_no_destructive_selection(monkeypatch):
    pytest.importorskip("PyQt5")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication, QPushButton

    from warestore.presentation.account_manager.ui.dialogs import DeadAccountsDialog

    app = QApplication.instance() or QApplication([])
    dialog = DeadAccountsDialog(
        None,
        [{"steamid": "1", "name": "Alice", "reason": "Token expired"}],
    )
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}

    assert dialog.selected_accounts() == []
    assert not buttons["Remove selected"].isEnabled()
    assert buttons["Keep them"].isDefault()
    app.processEvents()
