# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import hashlib
import hmac
import logging
import os
import re
import urllib.request
from itertools import zip_longest
from urllib.parse import urlparse

import requests

from warestore.config.settings import (
    CURRENT_VERSION,
    PRIVILEGED_DATA_DIR,
    VERSION_CHECK_URL,
)
from warestore.infrastructure.persistence.download import (
    download_limited,
    remove_if_exists,
)
from warestore.infrastructure.persistence.secure_dir import (
    ensure_admin_only_dir,
    ensure_admin_only_file,
)

_DOWNLOAD_TIMEOUT = 30
_MAX_INSTALLER_BYTES = 256 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")

logger = logging.getLogger(__name__)


def _parse_version(value: str) -> tuple[int, ...]:
    """Numeric-component version tuple; unparseable parts sort as 0."""
    if not isinstance(value, str):
        return (0,)
    parsed: list[int] = []
    for part in value.split("."):
        try:
            parsed.append(int(part) if part.isdigit() else 0)
        except (ValueError, OverflowError):
            parsed.append(0)
    return tuple(parsed) or (0,)


def _compare_versions(left: str, right: str) -> int:
    """Compare numeric versions, padding omitted components with zeroes."""
    for left_part, right_part in zip_longest(
        _parse_version(left), _parse_version(right), fillvalue=0
    ):
        if left_part != right_part:
            return 1 if left_part > right_part else -1
    return 0


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return urlparse(value).scheme.lower() == "https"
    except ValueError:
        return False


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class UpdateGateway:
    def check(self) -> dict:
        response = requests.get(VERSION_CHECK_URL, timeout=15)
        response.raise_for_status()
        info = response.json()
        if not isinstance(info, dict):
            info = {}

        latest = info.get("latest_version", CURRENT_VERSION)
        force_below = info.get("force_update_below_version", "0")
        change_log = info.get("change_log", "")
        download_url = info.get("download_url", "")
        download_sha256 = info.get("download_sha256", "")

        versions_valid = (
            "latest_version" in info
            and "force_update_below_version" in info
            and isinstance(latest, str)
            and _VERSION_RE.fullmatch(latest) is not None
            and isinstance(force_below, str)
            and _VERSION_RE.fullmatch(force_below) is not None
        )
        download_valid = (
            _is_https_url(download_url)
            and isinstance(download_sha256, str)
            and _SHA256_RE.fullmatch(download_sha256) is not None
        )
        manifest_valid = versions_valid and download_valid
        if not manifest_valid:
            logger.warning("Update manifest is malformed; ignoring it")

        latest = latest if isinstance(latest, str) else CURRENT_VERSION
        force_below = force_below if isinstance(force_below, str) else "0"
        change_log = change_log if isinstance(change_log, str) else ""
        download_url = download_url if isinstance(download_url, str) else ""
        download_sha256 = download_sha256 if isinstance(download_sha256, str) else ""
        return {
            "latest_version": latest,
            "change_log": change_log,
            "download_url": download_url,
            "download_sha256": download_sha256.lower(),
            "force_update": manifest_valid
            and _compare_versions(CURRENT_VERSION, force_below) <= 0,
            "update_available": manifest_valid
            and _compare_versions(latest, CURRENT_VERSION) > 0,
        }

    def download_installer(self, url: str, expected_sha256: str) -> str:
        """Download and verify an update inside the protected ProgramData tree."""
        if urlparse(url).scheme.lower() != "https":
            raise ValueError("update download URL must use HTTPS")
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise ValueError("missing or invalid installer SHA-256")

        expected = expected_sha256.lower()
        privileged_root = ensure_admin_only_dir(PRIVILEGED_DATA_DIR)
        update_dir = ensure_admin_only_dir(os.path.join(privileged_root, "updates"))
        destination = os.path.join(
            update_dir, f"WareStoreSetup-{expected[:12]}.exe"
        )
        remove_if_exists(destination)

        partial = destination + ".part"
        try:
            # Recover from an interrupted earlier download while retaining the
            # exclusive-create protection inside download_limited().
            remove_if_exists(partial)
            download_limited(
                url,
                partial,
                timeout=_DOWNLOAD_TIMEOUT,
                max_bytes=_MAX_INSTALLER_BYTES,
                opener=urllib.request.urlopen,
            )
            actual = _sha256_file(partial)
            if not hmac.compare_digest(actual, expected):
                raise ValueError(
                    "installer SHA-256 digest mismatch: "
                    f"expected {expected}, got {actual}"
                )
            os.replace(partial, destination)
            ensure_admin_only_file(destination)
            return destination
        except Exception:
            remove_if_exists(partial)
            raise
