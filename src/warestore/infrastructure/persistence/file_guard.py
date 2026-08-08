# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Backup and rollback for a group of related file mutations."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from collections.abc import Iterator

from warestore.infrastructure.persistence.atomic import write_bytes

logger = logging.getLogger(__name__)


class FileGuard:
    """Keep one backup generation and restore protected files on failure."""

    @contextmanager
    def protect(self, *paths: str) -> Iterator[None]:
        protected = list(dict.fromkeys(os.fspath(path) for path in paths))
        existed: dict[str, bool] = {}

        for path in protected:
            backup_path = f"{path}.warestore.bak"
            existed[path] = os.path.isfile(path)
            if existed[path]:
                with open(path, "rb") as file:
                    write_bytes(backup_path, file.read())
            elif os.path.exists(backup_path):
                os.remove(backup_path)

        try:
            yield
        except Exception:
            rolled_back: list[str] = []
            rollback_errors: list[Exception] = []
            for path in protected:
                try:
                    if existed[path]:
                        backup_path = f"{path}.warestore.bak"
                        with open(backup_path, "rb") as file:
                            write_bytes(path, file.read())
                    elif os.path.exists(path):
                        os.remove(path)
                    rolled_back.append(path)
                except Exception as exc:
                    rollback_errors.append(exc)
                    logger.exception("Failed to roll back %s", path)

            logger.error("Rolled back Steam files: %s", ", ".join(rolled_back))
            if rollback_errors:
                raise ExceptionGroup(
                    "One or more files could not be rolled back", rollback_errors
                )
            raise
