import pytest

from warestore.application.account_manager.presenter import AccountManagerPresenter


class _FakeController:
    def __init__(self):
        self.steam_path: str | None = r"C:\Steam"
        self.accounts: list[dict] = [
            {
                "steamid": "76561198000000001",
                "account_name": "alice",
                "persona_name": "Alice",
                "timestamp": 1_700_000_000,
            }
        ]
        self.tokens: dict = {
            "76561198000000001": {
                "username": "alice",
                "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig",
            }
        }
        self.deleted: list[str] = []
        self.removed_tokens: list[str] = []

    def steam_install_path(self):
        return self.steam_path

    def list_steam_accounts(self):
        return self.accounts

    def extract_tokens_from_steam(self):
        return 0

    def saved_token_entry(self, steam_id: str):
        return self.tokens.get(steam_id, {})

    def verify_token_expiry(self, token: str):
        return 3600 if token else -1

    def get_metadata(self, steam_id: str):
        from warestore.domain.accounts.models import AccountRecord

        return AccountRecord(last_played=0)

    def all_metadata(self):
        return {}

    def format_last_played(self, timestamp: int):
        return "Never"

    def delete_account(self, steam_id: str):
        self.deleted.append(steam_id)
        return True

    def delete_metadata(self, steam_id: str):
        pass

    def remove_token(self, steam_id: str):
        self.removed_tokens.append(steam_id)
        return True

    def load_settings(self):
        return {
            "open_cs2": True,
            "cs2_launch_options": "-high",
            "auto_remove_expired_tokens": False,
        }

    def purge_expired_tokens(self):
        removed = 0
        for sid, entry in list(self.tokens.items()):
            token = entry.get("token", "")
            if token and self.verify_token_expiry(token) < 0:
                del self.tokens[sid]
                removed += 1
        return removed

    def load_tokens(self):
        return dict(self.tokens)

    def purge_tokenless_accounts(self):
        token_ids = set(self.tokens.keys())
        if not token_ids:  # fail-closed: never mass-delete on an empty store
            return 0
        before = len(self.accounts)
        self.accounts = [a for a in self.accounts if a["steamid"] in token_ids]
        return before - len(self.accounts)


def test_load_accounts_no_steam():
    ctrl = _FakeController()
    ctrl.steam_path = None
    result = AccountManagerPresenter(ctrl).load_accounts()
    assert result.steam_dir is None
    assert result.status_message == "Steam not found."


def test_load_accounts_success():
    result = AccountManagerPresenter(_FakeController()).load_accounts()
    assert len(result.accounts) == 1
    assert result.steam_dir == r"C:\Steam"
    assert "Loaded 1 account" in result.status_message


def test_load_accounts_prefers_cached_persona_and_avatar():
    from warestore.domain.accounts.models import AccountRecord

    ctrl = _FakeController()
    ctrl.all_metadata = lambda: {  # type: ignore[method-assign]
        "76561198000000001": AccountRecord(persona="FreshName", avatar_hash="hash123")
    }
    result = AccountManagerPresenter(ctrl).load_accounts()
    acc = result.accounts[0]
    assert acc["persona_name"] == "FreshName"  # cached name wins over loginusers.vdf
    assert acc["avatar_hash"] == "hash123"


def test_load_accounts_removes_tokenless_when_setting_on():
    ctrl = _FakeController()
    # a second account in loginusers.vdf with NO saved token
    ctrl.accounts.append(
        {"steamid": "76561198000000002", "account_name": "bob", "timestamp": 1}
    )
    settings = ctrl.load_settings()
    settings["auto_remove_expired_tokens"] = True
    ctrl.load_settings = lambda: settings  # type: ignore[method-assign]

    result = AccountManagerPresenter(ctrl).load_accounts()
    ids = {a["steamid"] for a in result.accounts}
    assert "76561198000000002" not in ids   # tokenless account removed
    assert "76561198000000001" in ids        # account with a token kept
    assert "Removed 1 tokenless account" in result.status_message


def test_load_accounts_keeps_tokenless_when_setting_off():
    ctrl = _FakeController()
    ctrl.accounts.append(
        {"steamid": "76561198000000002", "account_name": "bob", "timestamp": 1}
    )
    # setting defaults off -> tokenless accounts are left alone
    result = AccountManagerPresenter(ctrl).load_accounts()
    ids = {a["steamid"] for a in result.accounts}
    assert "76561198000000002" in ids


def test_relogin_entry_for():
    entry = AccountManagerPresenter(_FakeController()).relogin_entry_for(
        {"steamid": "76561198000000001", "account_name": "alice"}
    )
    assert entry and entry.startswith("alice----eyJ")


def test_relogin_entry_missing_token():
    ctrl = _FakeController()
    ctrl.tokens = {}
    assert AccountManagerPresenter(ctrl).relogin_entry_for({"steamid": "76561198000000001"}) is None


def test_export_entries_for_skips_missing_tokens():
    ctrl = _FakeController()
    ctrl.accounts.append(
        {
            "steamid": "76561198000000002",
            "account_name": "bob",
            "persona_name": "Bob",
            "timestamp": 1_700_000_001,
        }
    )
    lines = AccountManagerPresenter(ctrl).export_entries_for(ctrl.accounts)
    assert len(lines) == 1
    assert lines[0].startswith("alice----eyJ")


def test_delete_account_calls_metadata_cleanup():
    ctrl = _FakeController()
    assert AccountManagerPresenter(ctrl).delete_account("76561198000000001")
    assert ctrl.deleted == ["76561198000000001"]
    # The saved token is purged too, so the account can't reappear on refresh.
    assert ctrl.removed_tokens == ["76561198000000001"]


def test_load_accounts_purges_expired_when_enabled():
    ctrl = _FakeController()
    ctrl.tokens["76561198000000002"] = {
        "username": "bob",
        "token": "expired.jwt.token",
    }

    def expiry(token: str):
        return -1 if token == "expired.jwt.token" else 3600

    ctrl.verify_token_expiry = expiry  # type: ignore[method-assign]

    settings = ctrl.load_settings()
    settings["auto_remove_expired_tokens"] = True
    ctrl.load_settings = lambda: settings  # type: ignore[method-assign]

    result = AccountManagerPresenter(ctrl).load_accounts()
    assert result.removed_expired == 1
    assert "76561198000000002" not in ctrl.tokens
    assert "Removed 1 expired" in result.status_message


def test_switch_worker_options_from_settings():
    opts = AccountManagerPresenter(_FakeController()).switch_worker_options(
        mode="native", acc={"steamid": "1"}
    )
    assert opts["open_cs2"] is True
    assert opts["cs2_options"] == "-high"


def test_access_denied_is_not_a_definitive_cm_token_rejection():
    from warestore.infrastructure.steam.cs2_cm_mint import _REJECTED_ERESULTS

    assert "AccessDenied" not in _REJECTED_ERESULTS


def test_dead_flag_attribution_uses_worker_emitted_steam_id():
    pytest.importorskip("PyQt5")
    from warestore.presentation.account_manager.features.accounts.coordinator import (
        AccountCoordinator,
    )

    coordinator = AccountCoordinator.__new__(AccountCoordinator)
    coordinator._shutting_down = False
    coordinator._cs2_batch_done = 0
    coordinator._cs2_dead = []
    coordinator._cs2_cm_rejections = 0
    coordinator._cs2_accounts_by_id = {
        "emitted": {"steamid": "emitted", "account_name": "Right account"},
        "other": {"steamid": "other", "account_name": "Wrong account"},
    }
    coordinator._start_next_cs2_rank = lambda: None

    coordinator._on_cs2_rank_done("emitted", None, True)

    assert coordinator._cs2_dead == [
        {"steamid": "emitted", "name": "Right account", "reason": "Logon rejected"}
    ]


def test_one_definitive_rejection_among_transient_failures_is_offered():
    pytest.importorskip("PyQt5")
    from warestore.presentation.account_manager.features.accounts.coordinator import (
        AccountCoordinator,
    )

    class _Info:
        text = ""

        def setText(self, text):
            self.text = text

    coordinator = AccountCoordinator.__new__(AccountCoordinator)
    coordinator._cs2_batch_total = 4
    coordinator._cs2_batch_ok = 0
    coordinator._cs2_batch_skipped = 0
    coordinator._cs2_last_on_cooldown = False
    coordinator._cs2_dead = [
        {"steamid": "one", "name": "One", "reason": "Logon rejected"}
    ]
    coordinator._cs2_cm_rejections = 1
    coordinator._cs2_unattended = False
    coordinator._info = _Info()
    prompted = []
    coordinator._prompt_dead_accounts = lambda: prompted.extend(coordinator._cs2_dead)

    coordinator._finish_cs2_batch()

    assert [account["steamid"] for account in prompted] == ["one"]


def test_large_rejection_cluster_is_suppressed_as_probable_throttling():
    pytest.importorskip("PyQt5")
    from warestore.presentation.account_manager.features.accounts.coordinator import (
        AccountCoordinator,
    )

    class _Info:
        text = ""

        def setText(self, text):
            self.text = text

    coordinator = AccountCoordinator.__new__(AccountCoordinator)
    coordinator._cs2_batch_total = 4
    coordinator._cs2_batch_ok = 0
    coordinator._cs2_batch_skipped = 0
    coordinator._cs2_last_on_cooldown = False
    coordinator._cs2_dead = [
        {"steamid": "one", "name": "One", "reason": "Logon rejected"},
        {"steamid": "two", "name": "Two", "reason": "Logon rejected"},
    ]
    coordinator._cs2_cm_rejections = 2
    coordinator._cs2_unattended = False
    coordinator._info = _Info()
    coordinator._prompt_dead_accounts = lambda: pytest.fail("must not prompt")

    coordinator._finish_cs2_batch()

    assert coordinator._cs2_dead == []
    assert "Nothing was marked for removal" in coordinator._info.text


def test_unattended_sweep_surfaces_review_link_without_opening_dialog():
    pytest.importorskip("PyQt5")
    from warestore.presentation.account_manager.features.accounts.coordinator import (
        AccountCoordinator,
    )

    class _Info:
        text = ""

        def setText(self, text):
            self.text = text

    coordinator = AccountCoordinator.__new__(AccountCoordinator)
    coordinator._cs2_batch_total = 4
    coordinator._cs2_batch_ok = 0
    coordinator._cs2_batch_skipped = 0
    coordinator._cs2_last_on_cooldown = False
    coordinator._cs2_dead = [
        {"steamid": "one", "name": "One", "reason": "Logon rejected"}
    ]
    coordinator._cs2_cm_rejections = 1
    coordinator._cs2_unattended = True
    coordinator._info = _Info()
    coordinator._prompt_dead_accounts = lambda: pytest.fail("must not auto-open")

    coordinator._finish_cs2_batch()

    assert 'href="review-dead-accounts"' in coordinator._info.text
