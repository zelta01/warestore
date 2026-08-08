# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Discovery + SHA-256-verified download of the HWID spoofer injector.

The injector is deliberately not bundled with the app. Frozen builds keep the
binary and its privileged inputs in an admin-controlled ProgramData directory.
"""

import hashlib
import hmac
import logging
import os
import sys
import urllib.request
from pathlib import Path

from warestore.config.settings import ACCOUNT_MANAGER_DATA_DIR, PRIVILEGED_DATA_DIR
from warestore.infrastructure.persistence.download import (
    download_limited,
    remove_if_exists,
)
from warestore.infrastructure.persistence.secure_dir import (
    ensure_admin_only_dir,
    ensure_admin_only_file,
    is_admin_only_dir,
    is_reparse_point,
)

logger = logging.getLogger(__name__)

INJECTOR_URL = (
    "https://github.com/bet3rd/steam_hwid_spoofer/releases/latest/download/injector.exe"
)
INJECTOR_SHA256 = "94ef309115c6fa374126231aa5ff88d4e2be1978772c25dbe1cee4495bc9b5f9"
DOWNLOAD_TIMEOUT = 30
MAX_INJECTOR_BYTES = 32 * 1024 * 1024


class InjectorIntegrityError(RuntimeError):
    pass


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_injector_hash(path: str) -> str:
    actual = sha256_file(path)
    if not hmac.compare_digest(actual.lower(), INJECTOR_SHA256.lower()):
        raise InjectorIntegrityError(
            "injector SHA-256 digest mismatch: "
            f"expected {INJECTOR_SHA256}, got {actual}"
        )
    return actual


def verify_injector(path: str, *, require_secure_dir: bool = True) -> str:
    """Re-check the pin and protected parent immediately before execution."""
    if require_secure_dir:
        if not is_admin_only_dir(os.path.dirname(path)):
            raise InjectorIntegrityError(
                f"injector directory is not admin-only: {os.path.dirname(path)}"
            )
        if is_reparse_point(path):
            raise InjectorIntegrityError("injector is a reparse point")
        ensure_admin_only_file(path)
    return verify_injector_hash(path)


def _delete_legacy_injector() -> None:
    legacy = os.path.join(ACCOUNT_MANAGER_DATA_DIR, "bin", "injector.exe")
    if not os.path.exists(legacy):
        return
    os.remove(legacy)
    logger.warning(
        "Deleted legacy unverified injector from user-writable directory: %s; "
        "a verified copy must be downloaded again",
        legacy,
    )


def data_dir() -> str:
    """Persistent directory holding the injector and its privileged inputs.

    Frozen: protected ``%PROGRAMDATA%\\WareStore\\bin``. Dev: the repo root,
    where locally built injector.exe / hardware_pool.json already live.
    """
    if getattr(sys, "frozen", False):
        root = ensure_admin_only_dir(PRIVILEGED_DATA_DIR)
        protected = ensure_admin_only_dir(os.path.join(root, "bin"))
        _delete_legacy_injector()
        return protected
    return str(Path(__file__).resolve().parents[4])


def injector_path() -> str:
    return os.path.join(data_dir(), "injector.exe")


def is_installed() -> bool:
    path = injector_path()
    if not os.path.exists(path):
        return False
    if not getattr(sys, "frozen", False):
        return True
    try:
        verify_injector(path)
        return True
    except Exception as exc:
        logger.error("Installed injector failed integrity checks: %s", exc)
        return False


def download_injector() -> None:
    """Download, bound, verify, then atomically promote ``injector.exe``."""
    target_dir = data_dir()
    os.makedirs(target_dir, exist_ok=True)
    dest = os.path.join(target_dir, "injector.exe")
    tmp = dest + ".part"
    logger.info("Downloading HWID spoofer from %s", INJECTOR_URL)
    try:
        download_limited(
            INJECTOR_URL,
            tmp,
            timeout=DOWNLOAD_TIMEOUT,
            max_bytes=MAX_INJECTOR_BYTES,
            opener=urllib.request.urlopen,
        )
        try:
            actual = verify_injector(tmp, require_secure_dir=False)
        except InjectorIntegrityError:
            actual = sha256_file(tmp)
            logger.error(
                "Injector digest mismatch; expected %s, got %s",
                INJECTOR_SHA256,
                actual,
            )
            raise
        os.replace(tmp, dest)
        if getattr(sys, "frozen", False):
            ensure_admin_only_file(dest)
        logger.info("HWID spoofer installed (SHA-256 %s)", actual)
    except Exception:
        remove_if_exists(tmp)
        raise
