# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Account grid loading, selection, and online status."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PyQt5.QtWidgets import QFileDialog, QMessageBox, QWidget

from warestore.application.account_manager.controller import AccountManagerController
from warestore.application.account_manager.presenter import AccountManagerPresenter
from warestore.domain.auth.jwt_service import is_expired_beyond_grace
from warestore.infrastructure.persistence import export_bundle
from warestore.infrastructure.persistence.atomic import write_bytes, write_text
from warestore.presentation.account_manager.features.accounts.cs2_rank_worker import (
    Cs2RankWorker,
)
from warestore.presentation.account_manager.features.accounts.status_worker import (
    StatusFetchWorker,
)
from warestore.presentation.account_manager.support.account_targets import (
    normalize_account_targets,
)
from warestore.presentation.account_manager.support.worker_registry import WorkerRegistry
from warestore.presentation.account_manager.support.secret_clipboard import copy_secret
from warestore.presentation.account_manager.support.vault_unlock import prompt_new_password

logger = logging.getLogger(__name__)


class AccountCoordinator:
    def __init__(
        self,
        parent: QWidget,
        presenter: AccountManagerPresenter,
        controller: AccountManagerController,
        settings: dict,
        *,
        account_grid,
        info_label,
        sync_layout: Callable[[], None],
        refresh_log: Callable[[], None],
        is_switch_busy: Callable[[], bool],
        on_accounts_loaded: Callable[[], None],
        get_search_text: Callable[[], str],
        filter_accounts: Callable[[str], None],
        worker_registry: WorkerRegistry,
    ) -> None:
        self._parent = parent
        self._presenter = presenter
        self._ctrl = controller
        self._settings = settings
        self._grid = account_grid
        self._info = info_label
        self._sync_layout = sync_layout
        self._refresh_log = refresh_log
        self._is_switch_busy = is_switch_busy
        self._on_accounts_loaded = on_accounts_loaded
        self._get_search = get_search_text
        self._filter = filter_accounts
        self._workers = worker_registry
        self._shutting_down = False
        self._selected: dict | None = None
        self._status_worker: StatusFetchWorker | None = None
        self._cs2_rank_worker: Cs2RankWorker | None = None
        # Sequential CS2 rank queue: minting a web session touches the account,
        # so ranks are fetched one at a time — the next account only starts once
        # the previous worker finishes (never concurrently).
        self._cs2_rank_queue: list[dict] = []
        self._cs2_batch_total = 0
        self._cs2_batch_done = 0
        self._cs2_batch_ok = 0
        self._cs2_batch_skipped = 0
        self._cs2_last_on_cooldown = False
        # Accounts flagged dead during a sweep (expired offline, or logon-rejected)
        # -> prompted for removal when the batch finishes.
        self._cs2_dead: list[dict] = []
        self._cs2_accounts_by_id: dict[str, dict] = {}
        self._cs2_cm_rejections = 0
        self._cs2_unattended = False
        self._info.linkActivated.connect(self._on_status_link)

    @property
    def selected_account(self) -> dict | None:
        return self._selected

    @selected_account.setter
    def selected_account(self, acc: dict | None) -> None:
        self._selected = acc

    def accounts_on_grid(self) -> list[dict]:
        return self._grid.accounts()

    def apply_card_metadata(self) -> None:
        hwid_names = self._ctrl.hwid_profile_names()
        self._grid.apply_view_states(
            lambda acc, **kw: self._presenter.card_view_state_for(
                acc, hwid_profile_names=hwid_names, **kw
            )
        )
        # Colour/cooldown filters depend on the state just applied above, so
        # re-evaluate visibility once the cards are up to date.
        if self._grid.has_active_filters():
            self._grid.reapply_filters()
            self._sync_layout()

    def load_accounts(self) -> None:
        self._selected = None
        if not self._is_switch_busy():
            self._info.setText("")

        result = self._presenter.load_accounts()
        if not result.steam_dir:
            self._info.setText(result.status_message)
            return

        self._grid.populate(result.accounts, result.steam_dir)
        self._filter(self._get_search())
        self.apply_card_metadata()
        self._sync_layout()

        if result.accounts:
            self._info.setText(result.status_message)

        self._on_accounts_loaded()
        self.start_status_fetch()
        self._refresh_log()

    def select_accounts(self, accounts: list[dict]) -> None:
        self._selected = accounts[0] if accounts else None
        if len(accounts) > 1 and not self._is_switch_busy():
            self._info.setText(f"{len(accounts)} accounts selected")

    def delete_accounts(self, accounts) -> None:
        targets = normalize_account_targets(accounts)
        if not targets:
            return

        deleted = 0
        for acc in targets:
            if self._presenter.delete_account(acc.get("steamid", "")):
                deleted += 1

        if deleted:
            self.load_accounts()
            self._info.setText(f"Deleted {deleted} account(s).")

    def set_color(self, accounts, color: str) -> None:
        targets = normalize_account_targets(accounts)
        changed = False
        for acc in targets:
            sid = acc.get("steamid", "")
            if sid:
                self._ctrl.set_account_color(sid, color)
                changed = True
        if changed:
            self.apply_card_metadata()

    def reset_hwid(self, account) -> None:
        acc = account[0] if isinstance(account, list) else account
        name = acc.get("account_name", "")
        if name and self._ctrl.reset_hwid_profile(name):
            self._info.setText(f"HWID profile reset for {name} — new values generated on next login.")
            self.apply_card_metadata()

    def set_cs2_source(self, account) -> None:
        acc = account[0] if isinstance(account, list) else account
        sid = acc.get("steamid", "")
        if not sid:
            return
        if self._settings.get("cs2_config_source_sid") == sid:
            self._save_cs2_source("")
            self._info.setText("CS2 config source cleared.")
        else:
            self._save_cs2_source(sid)
            name = acc.get("account_name", "") or sid
            self._info.setText(
                f"CS2 config source set to {name}. "
                "New accounts copy its CS2 config on first login."
            )
        self.apply_card_metadata()

    def _save_cs2_source(self, sid: str) -> None:
        # Write through the shared settings dict so a later settings-panel save
        # (which persists that same dict) can't clobber the source back to "".
        self._settings["cs2_config_source_sid"] = sid
        self._ctrl.save_settings(self._settings)

    def apply_cs2_source(self, accounts) -> None:
        targets = normalize_account_targets(accounts)
        if not targets:
            return
        if not self._ctrl.cs2_config_source():
            self._info.setText("No CS2 config source set.")
            return
        applied = 0
        for acc in targets:
            sid = acc.get("steamid", "")
            if sid and self._ctrl.apply_cs2_config(sid):
                applied += 1
        if applied:
            self._info.setText(
                f"Overrode CS2 config from source on {applied} account(s)."
            )
        else:
            self._info.setText("No CS2 config applied (source has no 730 config?).")
        self.apply_card_metadata()

    def copy_export_tokens(self, accounts) -> None:
        self._export_tokens(accounts, clipboard=True, save_file=False)

    def export_tokens_to_file(self, accounts) -> None:
        self._export_tokens(accounts, clipboard=False, save_file=True)

    def _export_tokens(
        self,
        accounts,
        *,
        clipboard: bool,
        save_file: bool,
    ) -> bool:
        targets = normalize_account_targets(accounts)
        lines = self._presenter.export_entries_for(targets)
        if not lines:
            self._info.setText("No saved tokens to export.")
            return False

        skipped = len(targets) - len(lines)
        suffix = f" ({skipped} missing token(s) skipped.)" if skipped else ""

        if clipboard:
            copy_secret("\n".join(lines))
            self._info.setText(
                f"Copied {len(lines)} token(s) to clipboard for 60 seconds.{suffix}"
            )

        if save_file:
            path, selected_filter = QFileDialog.getSaveFileName(
                self._parent,
                "Export tokens",
                "tokens.wsx",
                "WareStore encrypted bundles (*.wsx);;Plain text (*.txt);;All files (*)",
            )
            if not path:
                return False
            plain_text = selected_filter.startswith("Plain text") or Path(path).suffix.lower() == ".txt"
            if plain_text:
                warning = QMessageBox(self._parent)
                warning.setWindowTitle("Export unencrypted tokens?")
                warning.setIcon(QMessageBox.Warning)
                warning.setText(
                    "This writes every selected refresh token as readable plain text."
                )
                warning.setInformativeText(
                    "Anyone or any synced service with access to the file can use "
                    "the tokens. Delete it securely as soon as the other tool has imported it."
                )
                warning.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
                warning.setDefaultButton(QMessageBox.Cancel)
                if warning.exec_() != QMessageBox.Yes:
                    return False
                write_text(path, "\n".join(lines) + "\n")
                kind = "plain-text"
            else:
                if not Path(path).suffix:
                    path += ".wsx"
                passphrase = prompt_new_password(
                    title="Protect encrypted export",
                    label="Export passphrase",
                )
                if passphrase is None:
                    return False
                blob = export_bundle.export_encrypted(lines, passphrase)
                write_bytes(path, blob)
                kind = "encrypted"
            self._info.setText(
                f"Exported {len(lines)} token(s) to {kind} bundle {path}.{suffix}"
            )
        return True


    def start_status_fetch(self) -> None:
        if self._shutting_down:
            return
        if self._status_worker and self._status_worker.isRunning():
            return
        all_sids = self._grid.steam_ids()
        if not all_sids:
            return
        if not self._is_switch_busy():
            self._info.setText("Fetching status…")
        self._status_worker = StatusFetchWorker(all_sids, ctrl=self._ctrl)
        self._status_worker.progress.connect(self._on_status_progress)
        self._status_worker.done.connect(self._on_status_done)
        self._workers.track(self._status_worker)
        self._status_worker.start()

    def _on_status_progress(self, msg: str) -> None:
        if not self._is_switch_busy() and not (
            self._cs2_unattended and self._cs2_dead
        ):
            self._info.setText(msg)

    def _on_status_done(self, statuses: dict) -> None:
        if not self._is_switch_busy() and not self._selected:
            n = self._grid.card_count()
            if n:
                self._info.setText(f"Loaded {n} account(s).")

        for card in self._grid.cards():
            sid = card.acc.get("steamid", "")
            if sid not in statuses:
                continue
            status = statuses[sid]
            card.set_status(
                status.get("state", 0),
                status.get("game", ""),
                stale=status.get("stale", False),
            )
            card.set_ban_info(status.get("ban"))
            card.set_level(status.get("level"))
            if status.get("persona"):
                card.set_persona(status["persona"])
            if status.get("avatar_path"):
                card.set_avatar_from_file(status["avatar_path"])

        # Cache the fresh persona names + avatar hashes so the next launch shows
        # them immediately (one batched write).
        profiles = {
            sid: {"persona": s.get("persona", ""), "avatar_hash": s.get("avatar_hash", "")}
            for sid, s in statuses.items()
            if s.get("persona") or s.get("avatar_hash")
        }
        if profiles:
            self._ctrl.persist_profiles(profiles)

        # Bans arrive after the initial render, so the "no bans" filter must be
        # re-evaluated once they're known.
        if self._grid.has_active_filters():
            self._grid.reapply_filters()
            self._sync_layout()

        # A late profile/status response must not erase the only affordance for
        # reviewing an unattended sweep. Re-surface it after applying the data.
        if self._cs2_unattended and self._cs2_dead:
            self._show_dead_review_affordance()

    def fetch_all_cs2_ranks(self, unattended: bool = False) -> None:
        """Fetch CS2 rank for every account on the grid (sequentially)."""
        self.fetch_cs2_ranks(self.accounts_on_grid(), unattended=unattended)

    def fetch_cs2_ranks(self, accounts, *, unattended: bool = False) -> None:
        """Fetch CS2 rank for one or more accounts, strictly sequentially.

        Minting a web session touches each account, so ranks are fetched one at
        a time: the next account only starts once the previous worker finishes.
        Accounts without a saved token are skipped.
        """
        if self._shutting_down:
            return
        if self._cs2_rank_worker and self._cs2_rank_worker.isRunning():
            self._info.setText("A CS2 rank fetch is already running…")
            return
        targets = normalize_account_targets(accounts)
        queue = [
            acc
            for acc in targets
            if acc.get("steamid", "")
            and self._ctrl.saved_token_entry(acc["steamid"]).get("token", "")
        ]
        if not queue:
            self._info.setText(
                "No saved tokens for the selected account(s) — can't fetch rank."
            )
            return
        self._cs2_rank_queue = queue
        self._cs2_batch_total = len(queue)
        self._cs2_batch_done = 0
        self._cs2_batch_ok = 0
        self._cs2_batch_skipped = len(targets) - len(queue)
        self._cs2_dead = []
        self._cs2_accounts_by_id = {
            acc.get("steamid", ""): dict(acc) for acc in queue if acc.get("steamid", "")
        }
        self._cs2_cm_rejections = 0
        self._cs2_unattended = unattended
        self._start_next_cs2_rank()

    def _flag_dead(self, acc: dict, reason: str) -> None:
        self._cs2_dead.append(
            {
                "steamid": acc.get("steamid", ""),
                "name": acc.get("persona_name")
                or acc.get("account_name", "")
                or acc.get("steamid", ""),
                "reason": reason,
            }
        )

    def _start_next_cs2_rank(self) -> None:
        if self._shutting_down:
            self._cs2_rank_queue.clear()
            return
        # Only a confidently expired JWT, well outside the clock-skew grace, may
        # bypass CM and enter review. Malformed or unfamiliar token shapes get a
        # normal CM attempt: our parser alone is not authority to delete them.
        while self._cs2_rank_queue:
            acc = self._cs2_rank_queue[0]
            token = self._ctrl.saved_token_entry(acc.get("steamid", "")).get("token", "")
            verdict, expires_in = self._ctrl.classify_token(token)
            if is_expired_beyond_grace(verdict, expires_in):
                self._cs2_rank_queue.pop(0)
                self._cs2_batch_done += 1
                self._flag_dead(acc, "Token expired")
            else:
                break
        if not self._cs2_rank_queue:
            self._finish_cs2_batch()
            return
        acc = self._cs2_rank_queue.pop(0)
        sid = acc.get("steamid", "")
        token = self._ctrl.saved_token_entry(sid).get("token", "")
        name = acc.get("account_name", "") or sid
        if self._cs2_batch_total > 1:
            self._info.setText(
                f"Fetching CS2 rank {self._cs2_batch_done + 1}/{self._cs2_batch_total} — {name}…"
            )
        else:
            self._info.setText(f"Fetching CS2 rank for {name}…")
        self._cs2_rank_worker = Cs2RankWorker(sid, token, ctrl=self._ctrl)
        self._cs2_rank_worker.done.connect(self._on_cs2_rank_done)
        self._workers.track(self._cs2_rank_worker)
        self._cs2_rank_worker.start()

    def _on_cs2_rank_done(self, steam_id: str, data, dead: bool = False) -> None:
        if self._shutting_down:
            self._cs2_rank_queue.clear()
            return
        self._cs2_batch_done += 1
        if dead:
            # The worker-emitted id is the stable attribution. Queue position or
            # mutable "current account" state must never choose a deletion target.
            acc = self._cs2_accounts_by_id.get(steam_id, {"steamid": steam_id})
            self._flag_dead(acc, "Logon rejected")
            self._cs2_cm_rejections += 1
        elif data:
            self._cs2_batch_ok += 1
            premier = data.get("premier_rating", -1)
            premier_wins = data.get("premier_wins", -1)
            wingman = data.get("wingman_rank", -1)
            wingman_wins = data.get("wingman_wins", -1)
            cooldown = data.get("cooldown_expires_unix", 0)
            for card in self._grid.cards():
                if card.acc.get("steamid", "") != steam_id:
                    continue
                card.set_cs2_rank(
                    premier, wingman, cooldown, premier_wins, wingman_wins
                )
                # Keep the acc dict in sync so a later reload re-applies it too.
                card.acc["premier_rating"] = premier
                card.acc["premier_wins"] = premier_wins
                card.acc["wingman_rank"] = wingman
                card.acc["wingman_wins"] = wingman_wins
                card.acc["cs2_cooldown_expires"] = cooldown
                break
            # Persist so it survives a grid reload / relaunch.
            self._ctrl.persist_cs2_rank(
                steam_id, premier, wingman, cooldown, premier_wins, wingman_wins
            )
            self._cs2_last_on_cooldown = bool(cooldown)
        # One failure never aborts the batch — carry on to the next account.
        self._start_next_cs2_rank()

    def prepare_shutdown(self) -> None:
        """Stop the sequential rank driver from creating another worker."""
        self._shutting_down = True
        self._cs2_rank_queue.clear()
        self._cs2_dead.clear()
        self._cs2_accounts_by_id.clear()

    def _finish_cs2_batch(self) -> None:
        total = self._cs2_batch_total
        ok = self._cs2_batch_ok
        dead = len(self._cs2_dead)
        if total <= 1:
            if ok:
                self._info.setText(
                    "CS2 rank updated — competitive cooldown active."
                    if self._cs2_last_on_cooldown
                    else "CS2 rank updated."
                )
            elif dead:
                self._info.setText("CS2 rank fetch failed — the token looks dead.")
            else:
                self._info.setText(
                    "CS2 rank fetch failed — check the dev log for details."
                )
        else:
            parts = [f"{ok} updated"]
            if dead:
                parts.append(f"{dead} not working")
            transient = total - ok - dead
            if transient:
                parts.append(f"{transient} failed")
            if self._cs2_batch_skipped:
                parts.append(f"{self._cs2_batch_skipped} skipped (no token)")
            self._info.setText("CS2 ranks: " + ", ".join(parts) + ".")
        # A cluster of definitive-looking failures is much more likely to be a
        # service/rate-limit event than simultaneous token revocation. Allow one
        # isolated rejection, but suppress review when over 25% of a roster (and
        # at least two accounts) is rejected. This keeps blast radius from scaling.
        rejection_limit = max(1, int(total * 0.25))
        if total > 1 and self._cs2_cm_rejections > rejection_limit:
            logger.warning(
                "CS2 sweep suppressed %d removal candidates after %d/%d CM rejections",
                len(self._cs2_dead),
                self._cs2_cm_rejections,
                total,
            )
            self._cs2_dead.clear()
            self._info.setText(
                "Steam rejected an unusual share of the sweep. Nothing was marked "
                "for removal — wait a while and retry."
            )
            return

        # Only offer removal after a multi-account sweep — a single
        # right-click fetch just reports the dead token in the status bar.
        if self._cs2_dead and self._cs2_batch_total > 1:
            if self._cs2_unattended:
                self._show_dead_review_affordance()
            else:
                self._prompt_dead_accounts()

    def _show_dead_review_affordance(self) -> None:
        count = len(self._cs2_dead)
        self._info.setText(
            f"{count} account{'s' if count != 1 else ''} not working — "
            '<a href="review-dead-accounts">review</a>'
        )

    def _on_status_link(self, target: str) -> None:
        if target == "review-dead-accounts" and self._cs2_dead:
            self._prompt_dead_accounts()

    def _prompt_dead_accounts(self) -> None:
        """Offer to remove accounts flagged dead during the sweep (expired token
        or a logon Steam rejected). Removal purges the login entry + token."""
        from warestore.presentation.account_manager.ui.dialogs import DeadAccountsDialog

        dead = self._cs2_dead
        self._cs2_dead = []
        dialog = DeadAccountsDialog(
            self._parent,
            dead,
            exclude_from_capture=bool(self._settings.get("exclude_from_capture", True)),
        )
        if not dialog.exec_():
            return
        selected = dialog.selected_accounts()
        if selected and self._offer_token_export(selected):
            self.remove_accounts(selected)

    def _offer_token_export(self, accounts: list[dict]) -> bool:
        """Offer a recoverable token backup before irreversible deletion."""
        prompt = QMessageBox(self._parent)
        prompt.setWindowTitle("Back up saved tokens?")
        prompt.setIcon(QMessageBox.Warning)
        prompt.setText(
            "Removing these accounts permanently erases their saved tokens."
        )
        prompt.setInformativeText(
            "Export an encrypted .wsx backup first? Removal continues only after "
            "the export is saved."
        )
        export_btn = prompt.addButton(
            "Export encrypted bundle…", QMessageBox.AcceptRole
        )
        remove_btn = prompt.addButton(
            "Remove without export", QMessageBox.DestructiveRole
        )
        cancel_btn = prompt.addButton(QMessageBox.Cancel)
        prompt.setDefaultButton(cancel_btn)
        prompt.exec_()
        if prompt.clickedButton() is export_btn:
            return self._export_tokens(accounts, clipboard=False, save_file=True)
        return prompt.clickedButton() is remove_btn

    def remove_accounts(self, accounts: list[dict]) -> None:
        removed = 0
        for acc in accounts:
            logger.info(
                "Removing reviewed dead account: %s (%s)",
                acc.get("name", "") or acc.get("account_name", "") or "account",
                acc.get("steamid", ""),
            )
            if self._presenter.delete_account(acc.get("steamid", "")):
                removed += 1
        if removed:
            self.load_accounts()
            self._info.setText(f"Removed {removed} dead account(s).")
