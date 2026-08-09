# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Fetches Steam level via the Steam Web API (GetSteamLevel).

GetSteamLevel takes a single steamid per call (no batch endpoint exists), so
this loops; it fails soft per account and only runs when a key is configured.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from warestore.infrastructure.persistence.download import read_limited

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.steampowered.com/IPlayerService/GetSteamLevel/v1/"
_MAX_RESPONSE_BYTES = 256 * 1024


class SteamLevelGateway:
    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def fetch_levels(self, api_key: str, steam_ids: list[str]) -> dict[str, int]:
        if not api_key or not steam_ids:
            return {}
        out: dict[str, int] = {}
        for sid in steam_ids:
            level = self._fetch_one(api_key, sid)
            if level is not None:
                out[sid] = level
        return out

    def _fetch_one(self, api_key: str, steam_id: str) -> int | None:
        query = urllib.parse.urlencode({"key": api_key, "steamid": steam_id})
        try:
            with urllib.request.urlopen(f"{_ENDPOINT}?{query}", timeout=self._timeout) as resp:
                payload = json.loads(read_limited(resp, _MAX_RESPONSE_BYTES))
        except Exception as exc:
            logger.debug(f"Level fetch failed ({steam_id}): {exc}")
            return None
        response = payload.get("response", {}) if isinstance(payload, dict) else {}
        level = response.get("player_level") if isinstance(response, dict) else None
        try:
            return int(level) if level is not None else None
        except (TypeError, ValueError, OverflowError):
            return None
