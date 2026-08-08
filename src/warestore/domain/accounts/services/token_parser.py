# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import re


class TokenParser:
    _VALID_USERNAME = re.compile(r"^[A-Za-z0-9_\-\[\]]{1,64}$")

    @staticmethod
    def is_valid_username(name: str) -> bool:
        return bool(TokenParser._VALID_USERNAME.fullmatch(name))

    @staticmethod
    def sanitize_token(token: str) -> str:
        token = token.strip()
        if "|" in token:
            token = token.split("|", 1)[0]
        return token

    def sanitize_entry(self, raw: str) -> str | None:
        raw = raw.strip()
        if not raw:
            return None
        if "----" in raw:
            parts = [p.strip() for p in raw.split("----")]
            jwt_tok = next(
                (p for p in parts if p.lower().startswith("ey") and p.count(".") == 2),
                None,
            )
            if not jwt_tok:
                return None
            username = None if parts[0] == jwt_tok else parts[0]
            if username is not None and not self.is_valid_username(username):
                return None
            return f"{username}----{jwt_tok}" if username else jwt_tok
        if raw.lower().startswith("ey") and raw.count(".") == 2:
            return raw
        return None

    @staticmethod
    def jwt_from_entry(entry: str) -> str:
        if "----" in entry:
            return entry.split("----", 1)[1].strip()
        return entry.strip()

    def parse_bulk(self, text: str) -> list[str]:
        tokens: list[str] = []
        seen: set[str] = set()
        for line in text.splitlines():
            entry = self.sanitize_entry(line)
            if entry and entry not in seen:
                tokens.append(entry)
                seen.add(entry)
        return tokens
