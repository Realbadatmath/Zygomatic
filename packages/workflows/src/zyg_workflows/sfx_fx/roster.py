# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.roster — The assembled roster and the module public API."""

from zyg_workflows.sfx_fx.roster_a import FX_A
from zyg_workflows.sfx_fx.roster_b import FX_B
from zyg_workflows.sfx_fx.roster_c import FX_C


FX = FX_A + FX_B + FX_C

_BY_ID = {f['id']: f for f in FX}

# What sfx_merger imports: the public spec (no callables — this crosses to JSON)
EFFECT_TYPES = [{'id': f['id'], 'title': f['title'], 'cat': f['cat'], 'racks': f['racks']} for f in FX]
FILTER_IDS = frozenset(f['id'] for f in FX if f['_build'])
RENDER_IDS = frozenset(f['id'] for f in FX if f['_render'])


def is_fx(typ):
    return typ in _BY_ID


def filters(typ, p, ctx=None):
    """The -af filter list for one batchable fx slot."""
    f = _BY_ID.get(typ)
    if not f or not f['_build']:
        raise ValueError(f'{typ} is not a filter effect')
    return f['_build'](p, ctx or {})


def render(typ, p, src, dst, work_dir=None):
    """Run one standalone fx slot as its own pass."""
    f = _BY_ID.get(typ)
    if not f or not f['_render']:
        raise ValueError(f'{typ} is not a render effect')
    if f['_workdir']:
        return f['_render'](p, src, dst, work_dir)
    return f['_render'](p, src, dst)


def dur_after(typ, p, d):
    """What this slot does to the layer's length — sfx_merger's length fence
    asks before it renders, so a Stretch × 8 is refused instead of discovered."""
    f = _BY_ID.get(typ)
    if not f:
        return d
    if f['_dur']:
        try:
            return max(0.0, float(f['_dur'](p, d)))
        except Exception:  # noqa: BLE001
            return d
    return d
