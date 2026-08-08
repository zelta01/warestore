# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Bounded HTTP downloads shared by privileged and non-privileged caches."""

from __future__ import annotations

import os
import urllib.request
from collections.abc import Callable
from typing import BinaryIO

_CHUNK_SIZE = 64 * 1024


class DownloadTooLargeError(ValueError):
    pass


def download_limited(
    url: str,
    destination: str,
    *,
    timeout: int,
    max_bytes: int,
    opener: Callable[..., BinaryIO] | None = None,
) -> int:
    """Download to ``destination`` with an explicit timeout and byte ceiling."""
    open_url = opener or urllib.request.urlopen
    response = open_url(url, timeout=timeout)
    try:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > max_bytes:
            raise DownloadTooLargeError(
                f"download exceeds {max_bytes} byte limit: {content_length} bytes"
            )

        total = 0
        with open(destination, "wb") as output:
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise DownloadTooLargeError(
                        f"download exceeds {max_bytes} byte limit"
                    )
                output.write(chunk)
        return total
    finally:
        response.close()


def remove_if_exists(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
