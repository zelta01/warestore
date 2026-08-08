# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import json
import logging
import os
import shutil
import sys
import urllib.request

from warestore.infrastructure.persistence.download import (
    download_limited,
    remove_if_exists,
)
from warestore.infrastructure.persistence.secure_dir import (
    ensure_admin_only_file,
    is_reparse_point,
)

logger = logging.getLogger(__name__)

_URL = (
    "https://raw.githubusercontent.com/bet3rd/steam_hwid_spoofer"
    "/main/tools/hardware_pool.json"
)
_FILENAME = "hardware_pool.json"
_DOWNLOAD_TIMEOUT = 30
_MAX_POOL_BYTES = 5 * 1024 * 1024
_POOL_KEYS = {
    "gpus",
    "ram_mb",
    "monitors",
    "boards",
    "storage",
    "sound_cards",
    "display_models",
}


def _persistent_dir() -> str:
    """Use the injector's protected directory in frozen builds."""
    from warestore.infrastructure.steam.injector_stage import data_dir

    return data_dir()


def _dict_items(items, fields: dict[str, type | tuple[type, ...]]) -> bool:
    return isinstance(items, list) and bool(items) and all(
        isinstance(item, dict)
        and all(isinstance(item.get(key), expected) for key, expected in fields.items())
        for item in items
    )


def _valid_pool(data: object) -> bool:
    if not isinstance(data, dict) or set(data) != _POOL_KEYS:
        return False
    return all(
        (
            _dict_items(
                data["gpus"],
                {"name": str, "vendor_id": str, "device_id": str, "vram_mb": int},
            ),
            isinstance(data["ram_mb"], list)
            and bool(data["ram_mb"])
            and all(isinstance(value, int) and value > 0 for value in data["ram_mb"]),
            _dict_items(
                data["monitors"], {"width": int, "height": int, "refresh": int}
            ),
            _dict_items(data["boards"], {"model": str, "manufacturer": str}),
            _dict_items(
                data["storage"],
                {
                    "ssds": int,
                    "ssd_size": str,
                    "hdds": int,
                    "hdd_size": (str, type(None)),
                },
            ),
            isinstance(data["sound_cards"], list)
            and bool(data["sound_cards"])
            and all(isinstance(value, str) and value for value in data["sound_cards"]),
            isinstance(data["display_models"], list)
            and bool(data["display_models"])
            and all(isinstance(value, str) and value for value in data["display_models"]),
        )
    )


def _validate_file(path: str) -> None:
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    if not _valid_pool(data):
        raise ValueError("hardware_pool.json has an invalid schema")


def _protect_privileged_file(path: str) -> None:
    if not getattr(sys, "frozen", False):
        return
    if is_reparse_point(path):
        raise OSError("hardware_pool.json is a reparse point")
    ensure_admin_only_file(path)


def ensure(injector_path: str) -> bool:
    """Ensure a bounded, schema-validated hardware pool is beside the injector."""
    injector_dir = os.path.dirname(injector_path)
    dest = os.path.join(injector_dir, _FILENAME)

    if os.path.exists(dest):
        try:
            _protect_privileged_file(dest)
            _validate_file(dest)
            return True
        except Exception as exc:
            logger.warning("Discarding invalid hardware_pool.json: %s", exc)
            remove_if_exists(dest)

    cache_dir = _persistent_dir()
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, _FILENAME)

    if not os.path.exists(cache):
        tmp = cache + ".part"
        logger.info("hardware_pool.json not found — downloading from remote")
        try:
            download_limited(
                _URL,
                tmp,
                timeout=_DOWNLOAD_TIMEOUT,
                max_bytes=_MAX_POOL_BYTES,
                opener=urllib.request.urlopen,
            )
            _validate_file(tmp)
            os.replace(tmp, cache)
            _protect_privileged_file(cache)
            logger.info("hardware_pool.json downloaded, validated, and cached")
        except Exception as exc:
            remove_if_exists(tmp)
            logger.warning("Failed to download hardware_pool.json: %s", exc)
            return False
    else:
        try:
            _protect_privileged_file(cache)
            _validate_file(cache)
        except Exception as exc:
            logger.warning("Cached hardware_pool.json is invalid: %s", exc)
            return False

    if dest != cache:
        try:
            shutil.copy2(cache, dest)
            _protect_privileged_file(dest)
        except Exception as exc:
            logger.warning("Failed to copy hardware_pool.json to injector dir: %s", exc)
            return False

    return True
