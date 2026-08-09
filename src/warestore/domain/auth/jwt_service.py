# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import base64
import binascii
import enum
import json
import logging
import time

import jwt

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_GRACE_SECONDS = 3 * 60 * 60
MAX_REFRESH_TOKEN_CHARS = 16 * 1024


class TokenVerdict(enum.Enum):
    VALID = "valid"
    EXPIRED = "expired"
    MALFORMED = "malformed"
    UNRECOGNISED = "unrecognised"


def is_expired_beyond_grace(
    verdict: TokenVerdict,
    expires_in: int,
    *,
    grace_seconds: int = TOKEN_EXPIRY_GRACE_SECONDS,
) -> bool:
    """True only for a recognised expiry comfortably outside clock skew."""
    return verdict is TokenVerdict.EXPIRED and expires_in <= -grace_seconds


class SteamJwtService:
    @staticmethod
    def is_valid_format(token: str) -> bool:
        """True when `token` is structurally a JWT (three dot-separated parts)."""
        return (
            isinstance(token, str)
            and 0 < len(token) <= MAX_REFRESH_TOKEN_CHARS
            and token.count(".") == 2
        )

    @staticmethod
    def looks_like_jwt(token: str) -> bool:
        """Heuristic for a Steam refresh-token JWT (base64 payload starts 'ey')."""
        return SteamJwtService.is_valid_format(token) and token.lower().startswith("ey")

    def decode_steam_id(self, token: str) -> str | None:
        payload = self._parse_payload(token)
        if not payload:
            return None
        try:
            decoded = json.loads(payload)
            steam_id = decoded.get("sub") if isinstance(decoded, dict) else None
            if (
                isinstance(steam_id, str)
                and len(steam_id) == 17
                and steam_id.startswith("76")
                and steam_id.isascii()
                and steam_id.isdigit()
            ):
                return steam_id
            return None
        except json.JSONDecodeError:
            return None

    def issued_at(self, token: str) -> int:
        """The token's `iat` (issued-at) unix time, or 0 if unparseable."""
        payload = self._parse_payload(token)
        if not payload:
            return 0
        try:
            decoded = json.loads(payload)
            return int(decoded.get("iat", 0) or 0) if isinstance(decoded, dict) else 0
        except (json.JSONDecodeError, TypeError, ValueError, OverflowError):
            return 0

    def classify(self, refresh_token: str) -> tuple[TokenVerdict, int]:
        """Classify a refresh token without treating an unfamiliar shape as dead.

        The integer is seconds until (or since) ``exp``.  Valve can change JWT
        issuer/audience conventions independently of WareStore, so a token that
        parses but has unexpected claims is deliberately *unrecognised*, not
        expired.  The CM logon remains the authority for those tokens.
        """
        if not self.is_valid_format(refresh_token):
            return TokenVerdict.MALFORMED, -1
        try:
            decoded = jwt.decode(
                refresh_token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                },
            )
            expires_in = int(float(decoded["exp"]) - time.time())
        except Exception:  # noqa: BLE001 - every decode/claim error is malformed
            return TokenVerdict.MALFORMED, -1

        issuer = decoded.get("iss")
        audience = decoded.get("aud")
        audiences = audience if isinstance(audience, (list, tuple, set)) else [audience]
        if issuer != "steam" or "client" not in audiences:
            # Claims are safe to log; the refresh token itself never is.
            logger.warning(
                "Unrecognised Steam token claims (iss=%r, aud=%r); deferring to CM logon",
                issuer,
                audience,
            )
            return TokenVerdict.UNRECOGNISED, expires_in

        if expires_in <= 0:
            return TokenVerdict.EXPIRED, min(-1, expires_in)
        return TokenVerdict.VALID, expires_in

    def verify_expiry(self, refresh_token: str) -> int:
        """Compatibility wrapper returning ``-1`` only for actually dead input."""
        verdict, expires_in = self.classify(refresh_token)
        if verdict in (TokenVerdict.EXPIRED, TokenVerdict.MALFORMED):
            return -1
        # An unfamiliar but parseable JWT may still be live.  Preserve its real
        # positive expiry where possible and, if already past, keep it eligible
        # for a CM check instead of feeding destructive legacy callers ``-1``.
        return max(1, expires_in)

    @staticmethod
    def _parse_payload(token: str) -> str | None:
        if not SteamJwtService.is_valid_format(token):
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = len(payload) % 4
        if padding:
            payload += "=" * (4 - padding)
        try:
            return base64.urlsafe_b64decode(payload).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return None
