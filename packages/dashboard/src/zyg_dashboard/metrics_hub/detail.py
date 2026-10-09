# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Quality detail: the rows behind one metric or verdict (?detail=<token>)."""

from __future__ import annotations

from .detail_context import build_detail_context
from .detail_runs import day_section, receipt_section, run_section, vlm_section
from .detail_tiles import fallback_section, family_section, tile_section

# One builder per token kind. `run` and `debug` share one: a debug token names a single filed
# verdict and a run token names every verdict filed under the run id, but both draw one run.
_SECTIONS = {
    'tile': tile_section,
    'family': family_section,
    'fallback': fallback_section,
    'receipt': receipt_section,
    'vlm': vlm_section,
    'day': day_section,
    'run': run_section,
    'debug': run_section,
}


def quality_detail(token, days=30, now=None):
    """One Quality-tab metric or verdict, opened out into the rows behind it.

    `token` is what the tab shipped with the row it drew — tile:<id>, family:<gate family>,
    fallback:<id>, receipt:<gate>, vlm:<counter>, day:<bucket>, run:<run id>, debug:<run id>.
    Windowed rows honour `days`; all-time counters say so in their own note."""
    ctx = build_detail_context(token, days=days, now=now)
    build = _SECTIONS.get(ctx.kind)
    if build is None:
        return {'ok': False, 'error': f'unknown detail token {token!r}'}
    return build(ctx)
