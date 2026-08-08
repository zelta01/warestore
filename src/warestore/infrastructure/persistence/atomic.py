# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Crash-safe helpers for replacing files.

Data is flushed and fsynced before the temporary file replaces the destination.
That ordering matters: without the fsync, a power loss can persist the rename
while the replacement's data is still only in the operating system's cache,
leaving the destination empty or partially written after reboot.
"""

from __future__ import annotations

import os
import tempfile


def write_bytes(path: str, data: bytes) -> None:
    """Atomically replace *path* with *data*."""
    target = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(target)}.", suffix=".tmp", dir=parent
    )
    try:
        file = os.fdopen(fd, "wb")
        fd = -1
        with file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def write_text(path: str, text: str, *, encoding: str = "utf-8") -> None:
    """Encode *text* and atomically replace *path*."""
    write_bytes(path, text.encode(encoding))
