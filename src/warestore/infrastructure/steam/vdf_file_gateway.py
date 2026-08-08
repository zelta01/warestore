# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import logging
import os

import chardet
import vdf

from warestore.infrastructure.persistence.atomic import write_text

logger = logging.getLogger(__name__)


class VdfFileGateway:
    def detect_encoding(self, file_path: str) -> str:
        """Detect a legacy file's encoding from all of its bytes."""
        with open(file_path, "rb") as f:
            raw = f.read()
        return chardet.detect(raw).get("encoding") or "utf-8"

    def read_text(self, file_path: str) -> str:
        """Read Steam VDF text as strict UTF-8, detecting only as a fallback."""
        try:
            with open(file_path, encoding="utf-8", newline="") as f:
                return f.read()
        except UnicodeDecodeError:
            encoding = self.detect_encoding(file_path)
            logger.warning(
                f"{os.path.basename(file_path)} is not UTF-8; read as {encoding}"
            )
            with open(file_path, encoding=encoding, newline="") as f:
                return f.read()

    def write_text(self, file_path: str, text: str) -> None:
        write_text(file_path, text)

    def read_vdf(self, file_path: str) -> dict:
        return vdf.loads(self.read_text(file_path))

    def write_vdf(self, file_path: str, data: dict) -> None:
        write_text(file_path, vdf.dumps(data, pretty=True))
