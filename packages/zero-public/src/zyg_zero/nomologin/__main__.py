# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Keeps `python -m zyg_zero.nomologin <cmd>` working now that the module is a package."""

from __future__ import annotations

import sys

from zyg_zero.nomologin.cli import main

sys.exit(main(sys.argv[1:]))
