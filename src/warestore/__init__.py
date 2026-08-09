# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""WareStore — Steam account management."""

import os

# ValvePython 1.4.4 bundles old generated descriptors. Patched protobuf releases
# load them through the supported compatibility backend. Select it at package
# startup, before any `google.protobuf` / `steam` import can occur.
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

__version__ = "3.4"
