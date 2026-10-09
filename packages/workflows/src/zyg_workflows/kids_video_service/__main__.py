# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""``python -m zyg_workflows.kids_video_service <song dir>`` — the old file's CLI."""

from __future__ import annotations

import sys

from zyg_workflows.kids_video_service.cli import _main

raise SystemExit(_main(sys.argv[1:]))
