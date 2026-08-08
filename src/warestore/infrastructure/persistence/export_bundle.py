# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Portable encrypted roster bundles.

Layout::

    MAGIC(4) | version(1) | iterations(4, big-endian) | salt(16) |
    vault_crypto blob (WSV1)

The KDF iteration count is part of every bundle.  This is deliberately not
inferred from :data:`vault_crypto.PBKDF2_ITERATIONS`: a bundle written with an
older work factor must remain importable after the application raises its
current default.  ``WSX1`` is distinct from the token-vault ``WSV1`` magic so
the two encrypted formats cannot be mistaken for one another.
"""

from __future__ import annotations

import json
import struct

from warestore.infrastructure.persistence import vault_crypto

MAGIC = b"WSX1"
VERSION = 1
_HEADER = struct.Struct(">4sBI16s")
_MIN_VAULT_BLOB_BYTES = len(vault_crypto.MAGIC) + vault_crypto.NONCE_BYTES + 16
_MAX_ITERATIONS = 10_000_000


def export_encrypted(entries: list[str], passphrase: str) -> bytes:
    """Return *entries* as a self-describing, passphrase-encrypted bundle."""
    if not all(isinstance(entry, str) for entry in entries):
        raise TypeError("bundle entries must be strings")

    iterations = int(vault_crypto.PBKDF2_ITERATIONS)
    if not 1 <= iterations <= min(0xFFFFFFFF, _MAX_ITERATIONS):
        raise ValueError("unsupported PBKDF2 iteration count")
    salt = vault_crypto.new_salt()
    key = vault_crypto.derive_key(passphrase, salt, iterations)
    payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    encrypted = vault_crypto.encrypt(key, payload)
    return _HEADER.pack(MAGIC, VERSION, iterations, salt) + encrypted


def import_encrypted(blob: bytes, passphrase: str) -> list[str]:
    """Decrypt and validate a roster bundle.

    Authentication, malformed headers, invalid JSON, and partial/corrupt data
    all raise; this function never returns a partially recovered roster.
    """
    if not isinstance(blob, bytes):
        raise TypeError("bundle must be bytes")
    if len(blob) < len(MAGIC):
        raise ValueError("truncated encrypted export bundle")
    if blob[: len(MAGIC)] != MAGIC:
        raise ValueError("not a WSX1 encrypted export bundle")
    if len(blob) < _HEADER.size + _MIN_VAULT_BLOB_BYTES:
        raise ValueError("truncated encrypted export bundle")

    _magic, version, iterations, salt = _HEADER.unpack_from(blob)
    if version != VERSION:
        raise ValueError(f"unsupported encrypted export bundle version: {version}")
    if not 1 <= iterations <= _MAX_ITERATIONS:
        raise ValueError("invalid PBKDF2 iteration count in bundle")

    encrypted = blob[_HEADER.size :]
    if not vault_crypto.is_vault_blob(encrypted):
        raise ValueError("encrypted export payload is not a WSV1 blob")
    key = vault_crypto.derive_key(passphrase, salt, iterations)
    plaintext = vault_crypto.decrypt(key, encrypted)
    try:
        entries = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("encrypted export payload is invalid") from exc
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) for entry in entries
    ):
        raise ValueError("encrypted export payload must contain a list of strings")
    return entries
