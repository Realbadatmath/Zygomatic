# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mountains plumbing: the size/slope/snow limits, the v3 sculpt seam and the
refusal and wording helpers the four tools share."""

from __future__ import annotations


from zyg_workflows.arch_assistant import (
    MATERIALS,
    _num,
)


# ── plumbing ────────────────────────────────────────────────────────────────
_STYLES = ('peak', 'volcano', 'mesa')
MAX_R = 400.0
MIN_R = 5.0
MAX_H = 3000.0
MAX_BLOCK = 800.0

SNOW_MIN_SUMMIT = 60.0  # below this a summit is bare rock: an alp, not an Alp
SNOW_AUTO_LINE = 0.75  # where 'auto' puts the line when the summit earns one
NO_SNOW = 2.0  # a line at or above 1.0 leaves the geometry one part

MOUNT_MAX_SLOPE = 1.0  # height <= 1.0 x radius: a 45-degree flank at most
MOUNT_MIN_SLOPE = 0.25  # under that it is a hill — add_hill draws those
MESA_MAX_SLOPE = 0.8
RIDGE_MAX_SLOPE = 0.8  # crest <= 0.8 x foot-to-foot width
VALLEY_MAX_DEPTH = 0.4  # depth <= 0.4 x the distance across
VALLEY_DEF_DEPTH = 0.35  # what a valley takes when the caller names no depth
RANGE_DEF_HEIGHT = 0.7  # of the peak radius, when the caller names no height


# ── v3: is this drawing a sculpted heightfield? ──────────────────────────────
SCULPT_FEATHER = 0.20  # a sculpt's rim feather as a fraction of its size —
# the same FEATHER_FRAC arch_assistant_ext/ground_v3 uses
RANGE_SPREAD = 0.5  # a range's summits vary +-25 %: 1 + 0.5 * (hash - 0.5)
SCULPT_MAT = 'mat_soil'  # a void record's material is never seen; ground_v3 uses this


def has_ground(d) -> bool:
    """True when the drawing carries a v3 `ground` record — then everything this
    family draws is a SCULPT of that one heightfield instead of a solid on it."""
    return any(o.get('kind') == 'ground' for o in getattr(d, 'objs', None) or ())


def ground_of(d):
    """The drawing's one `ground` record, or None."""
    for o in getattr(d, 'objs', None) or ():
        if o.get('kind') == 'ground':
            return o
    return None


def sculpt_y(base_height):
    """The `y` a sculpt record gets. A sculpt's contribution is ADDITIVE — it is
    summed onto whatever the ground already is under the point — so a raise on
    rolling ground rises from that ground with y = 0, and a non-zero y would
    count the land twice. An explicit base_height still overrides and shifts the
    whole feature (ground_v3.field_at adds `y * mask`, so the rim stays welded)."""
    return 0.0 if base_height is None or base_height == '' else _num(base_height, 0.0)


def ground_snow_words(d) -> str:
    """What the reply says about snow on a v3 drawing: the ground colours itself
    above its own ABSOLUTE snow_h, so the record's snow_line sets nothing."""
    g = ground_of(d)
    return "snow follows the ground's snow height (%g m)" % _num((g or {}).get('p', {}).get('snow_h'), 60.0)


SOLID_WORDS = 'as a solid (no sculpted ground)'
SCULPT_WORDS = 'sculpted into the ground'


def _mat(m, default='mat_rock'):
    return m if m in MATERIALS else default


def _bad_size(r, h):
    if r < MIN_R or r > MAX_R:
        return f'refused: radius must be between {MIN_R:g} and {MAX_R:g} m — a mountain is a landform, not a mound'
    if h <= 0 or h > MAX_H:
        return f'refused: height must be more than 0 and at most {MAX_H:g} m'
    return ''


def _res_for(span: float) -> int:
    return max(16, min(96, int(round(span / 2.5))))


def resolve_snow(snow_line, summit: float):
    """(line, why) for a summit that many metres above its own base.
    'auto' (the default) caps only a summit of SNOW_MIN_SUMMIT m or more, and
    then at SNOW_AUTO_LINE; 'none' never caps; a number is taken as given.
    line is NO_SNOW when there is no cap; (None, msg) when the value is junk."""
    v = snow_line
    if v is None:
        v = 'auto'
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ('none', 'no', 'off', 'bare'):
            return NO_SNOW, 'none'
        if t in ('', 'auto'):
            if summit >= SNOW_MIN_SUMMIT:
                return SNOW_AUTO_LINE, 'auto'
            return NO_SNOW, 'auto-bare'
        try:
            v = float(t)
        except ValueError:
            return None, (
                'refused: snow_line must be a number (the fraction of the height the snow starts at), '
                "'auto' (snow only above %g m of summit) or 'none'" % SNOW_MIN_SUMMIT
            )
    v = _num(v, SNOW_AUTO_LINE)
    if v < 0:
        return None, "refused: snow_line cannot be negative — use 'none' for a bare summit"
    return v, 'set'


def _snow_words(line: float, why: str, summit: float) -> str:
    if line >= 1.0:
        if why == 'auto-bare':
            return f'no snow — a {summit:g} m summit is under the {SNOW_MIN_SUMMIT:g} m snow line'
        return 'no snow cap'
    return 'snow above %.0f m' % (line * summit)
