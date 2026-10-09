#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Amsterdam-time helpers for the dashboard.

Moved verbatim out of crewai_web_gui.py (2026-10-06 round-2 split). The three
formatting/parsing helpers are owned by ``zyg_workflows.runtime`` since the
2026-10-05 layering pass; this module is the dashboard-side import site for
them, next to the ``_AMS_TZ`` tzinfo object it does own.
"""

# ruff: noqa: F401  every name here is a re-export read off this module (and off crewai_web_gui)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


_AMS_TZ = None
if ZoneInfo:
    try:
        _AMS_TZ = ZoneInfo('Europe/Amsterdam')
    except Exception:
        _AMS_TZ = None


# 2026-10-05 layering: pure helpers, so they live in zyg_workflows.runtime now and
# the pipelines import them from there instead of from the dashboard.
from zyg_workflows.runtime import _ams_now, _parse_iso_to_ams  # noqa: E402  kept at the old definition site
from zyg_workflows.runtime import ams_iso as _ams_iso  # noqa: E402  kept at the old definition site
