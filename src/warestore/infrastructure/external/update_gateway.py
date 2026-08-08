# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import hashlib
import hmac
import os
import re
import urllib.request
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
        latest = info["latest_version"]
        force_below = info["force_update_below_version"]
        download_url = info["download_url"]
        download_sha256 = info["download_sha256"]
        if urlparse(download_url).scheme.lower() != "https":
            raise ValueError("update download URL must use HTTPS")
        if not _SHA256_RE.fullmatch(download_sha256):
            raise ValueError("update manifest has an invalid download_sha256")
        return {
            "latest_version": latest,
            "change_log": info["change_log"],
            "download_url": download_url,
            "download_sha256": download_sha256.lower(),
            "force_update": CURRENT_VERSION <= force_below,
            "update_available": latest != CURRENT_VERSION,
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
