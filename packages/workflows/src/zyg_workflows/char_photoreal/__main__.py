#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI entry point: `python -m zyg_workflows.char_photoreal <body> [--stage ...]`."""

from __future__ import annotations

from zyg_workflows.char_photoreal.publish import main

if __name__ == '__main__':
    main()
