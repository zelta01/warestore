# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

from dataclasses import dataclass


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


@dataclass
class AccountRecord:
    eya: str = ""
    last_played: int = 0
    cooldown_until: int = 0
    cooldown_duration: int = 0
    color: str = ""
    cs2_seeded: bool = False
    # Cached from the last status refresh so the card shows the current name +
    # avatar on launch, before the next refresh completes.
    persona: str = ""
    avatar_hash: str = ""
    # Cached from the last on-demand CS2 rank fetch so it survives a grid reload
    # / relaunch. -1 = unknown/unranked; cooldown expiry is unix (0 = none).
    premier_rating: int = -1
    premier_wins: int = -1
    wingman_rank: int = -1
    wingman_wins: int = -1
    cs2_cooldown_expires: int = 0

    @classmethod
    def from_raw(cls, raw: object) -> "AccountRecord":
        if isinstance(raw, str):
            return cls(eya=raw)
        if isinstance(raw, dict):
            return cls(
                eya=_as_str(raw.get("eya", "")),
                last_played=_as_int(raw.get("last_played", 0), 0),
                cooldown_until=_as_int(raw.get("cooldown_until", 0), 0),
                cooldown_duration=_as_int(raw.get("cooldown_duration", 0), 0),
                color=_as_str(raw.get("color", "")),
                cs2_seeded=bool(raw.get("cs2_seeded", False)),
                persona=_as_str(raw.get("persona", "")),
                avatar_hash=_as_str(raw.get("avatar_hash", "")),
                premier_rating=_as_int(raw.get("premier_rating", -1), -1),
                premier_wins=_as_int(raw.get("premier_wins", -1), -1),
                wingman_rank=_as_int(raw.get("wingman_rank", -1), -1),
                wingman_wins=_as_int(raw.get("wingman_wins", -1), -1),
                cs2_cooldown_expires=_as_int(
                    raw.get("cs2_cooldown_expires", 0), 0
                ),
            )
        return cls()

    def to_dict(self) -> dict:
        return {
            "eya": self.eya,
            "last_played": self.last_played,
            "cooldown_until": self.cooldown_until,
            "cooldown_duration": self.cooldown_duration,
            "color": self.color,
            "cs2_seeded": self.cs2_seeded,
            "persona": self.persona,
            "avatar_hash": self.avatar_hash,
            "premier_rating": self.premier_rating,
            "premier_wins": self.premier_wins,
            "wingman_rank": self.wingman_rank,
            "wingman_wins": self.wingman_wins,
            "cs2_cooldown_expires": self.cs2_cooldown_expires,
        }
