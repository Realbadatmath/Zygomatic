#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Entry point: `python -m zyg_workflows.run_scene_shores_v25 [--verify-only]`."""

from zyg_workflows.run_scene_shores_v25.main import main

raise SystemExit(main())
