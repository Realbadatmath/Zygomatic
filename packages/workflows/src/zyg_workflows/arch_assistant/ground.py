# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Extensions, ground height, the current drawing, decks and buildings on the ground.

Moved verbatim out of the old single-file arch_assistant.py (lines 1709-2156).
"""

from __future__ import annotations

import logging as _zyg_logging
import math
import os

from zyg_workflows.arch_assistant._base import HERE

# ── extensions (2026-09-06) ─────────────────────────────────────────────────
# arch_assistant_ext/*.py — one file per capability family. Each may define:
#   TOOLS    = [(tool_def_dict, fn)]   fn(d: Drawing, args: dict) -> str
#   KINDS    = {kind: {param: default}}   (accepted by add_object, listed in the prompt)
#   OPENINGS = ['window_arch', ...]       (kinds arSyncHoles should cut for)
#   PROMPT   = 'one paragraph the system prompt gains'
#   EXAMPLES = [{'ask': '...', 'calls': [{'tool': 'draw_curved_wall', 'args': {...}}]}]
# A broken module costs its own tools, never the assistant.
EXT_PROMPTS: list[str] = []
EXT_EXAMPLES: list[dict] = []
EXT_KINDS: dict = {}
EXT_MODULES: dict = {}


def load_extensions(force=False):
    import glob
    import importlib
    import importlib.util

    d = os.path.join(HERE, 'arch_assistant_ext')
    # An extension may be a FILE or a PACKAGE directory: the 2026-10 modularization
    # splits turn the big ones (blender_power, …) into `<name>/__init__.py`, which a
    # `*.py` glob cannot see.  A package is imported by name — arch_assistant_ext/ has
    # an __init__.py — so its absolute intra-package imports resolve and it executes once.
    cand = [(os.path.splitext(os.path.basename(f))[0], f, False) for f in glob.glob(os.path.join(d, '*.py'))]
    cand += [(os.path.basename(os.path.dirname(f)), f, True) for f in glob.glob(os.path.join(d, '*', '__init__.py'))]
    for name, f, is_pkg in sorted(cand):
        if name.startswith('_') or (name in EXT_MODULES and not force):
            continue
        try:
            if is_pkg:
                mod = importlib.import_module('zyg_workflows.arch_assistant_ext.' + name)
            else:
                spec = importlib.util.spec_from_file_location('arch_assistant_ext.' + name, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            for tdef, fn in getattr(mod, 'TOOLS', []) or []:
                if tdef['name'] in TOOL_FN and not force:
                    continue
                TOOL_DEFS[:] = [t for t in TOOL_DEFS if t['name'] != tdef['name']] + [tdef]
                TOOL_FN[tdef['name']] = fn
            for k, v in (getattr(mod, 'KINDS', {}) or {}).items():
                KINDS[k] = dict(v)
                EXT_KINDS[k] = dict(v)
            for k in getattr(mod, 'OPENINGS', []) or []:
                if k not in OPENINGS_EXT:
                    OPENINGS_EXT.append(k)
            for k, fn in (getattr(mod, 'HEIGHTS', {}) or {}).items():
                EXT_HEIGHTS[k] = fn
            pr = str(getattr(mod, 'PROMPT', '') or '').strip()
            if pr and pr not in EXT_PROMPTS:
                EXT_PROMPTS.append(pr)
            for ex in getattr(mod, 'EXAMPLES', []) or []:
                EXT_EXAMPLES.append(ex)
            for b in getattr(mod, 'BUTTONS', []) or []:  # dock/side icons the tab may press for the model
                EXT_BUTTONS.add(str(b))
            EXT_MODULES[name] = mod
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[arch_assistant] extension {name} skipped: {e!r}')


OPENINGS_EXT: list[str] = []
# icon ids (AR_TOOLS / AR_EXT.tools) an extension declares pressable through
# view_scene_ops.press_button — the tab's arAssistUi accepts an extension tool
# only when its registration says `assist:1`, so both sides must agree.
EXT_BUTTONS: set = set()

# ── ground (2026-09-07) ───────────────────────────────────────────────────────
# A family that draws GROUND (terrain, hills, slopes, mountains, dunes, cliff tops…)
# exports HEIGHTS = {kind: fn(p, lx, lz) -> y | None}: the height of that kind's top
# surface, in metres above the record's own base, at a point given in the record's
# LOCAL plan frame (the record's x/z is the origin, ry already removed, +X along,
# +Z the studio's south). None = the point is outside the footprint. Every placement
# tool asks ground_at() so nothing is buried inside a slope or floats over a valley.
EXT_HEIGHTS: dict = {}


def world_to_local(o: dict, x: float, z: float) -> tuple:
    """(lx, lz) of world (x, z) in record o's plan frame (position + ry removed).
    THREE rotation.y = ry maps local +X to (cos ry, -sin ry) on the plan."""
    dx, dz = x - o['x'], z - o['z']
    c, s = math.cos(o.get('ry') or 0.0), math.sin(o.get('ry') or 0.0)
    return dx * c - dz * s, dx * s + dz * c


# ── the current drawing (2026-09-07, v3) ──────────────────────────────────────
# A HEIGHTS fn is handed (p, lx, lz) — its own parameters and a point. The v3
# `ground` is not a shape of its own: its height is the base noise PLUS the
# contribution of every sculpt_* record in the SAME drawing, so its height fn
# has to be able to read the other records. `current_drawing()` is that seam:
# ground_height() publishes the drawing it is walking for the duration of the
# call, and a HEIGHTS fn asks for it. Outside a HEIGHTS call it is None — a fn
# that needs it must cope with that (an empty drawing is the honest answer).
_CTX: dict = {'d': None}


class _Current:
    """Publishes `d` as the current drawing for the length of a `with` block.
    Re-entrant: nested HEIGHTS evaluation restores the outer drawing."""

    def __init__(self, d):
        self.d = d
        self.prev = None

    def __enter__(self):
        self.prev = _CTX['d']
        _CTX['d'] = self.d
        return self.d

    def __exit__(self, *a):
        _CTX['d'] = self.prev
        return False


def current_drawing():
    """The Drawing whose ground is being evaluated, or None outside a HEIGHTS call."""
    return _CTX['d']


def sculpts_of(d) -> list:
    """The drawing's sculpt records — the void kinds (`sculpt_peak`, `sculpt_cut`,
    `sculpt_basin`…) that carve the one ground heightfield. Hidden records are
    left out: hiding a sculpt in the outliner takes its feature out of the land."""
    if d is None:
        return []
    return [o for o in getattr(d, 'objs', []) or [] if is_sculpt(o.get('kind')) and not o.get('hidden')]


# The surfaces that LIE ON the ground rather than stand on it. They take the
# ground's height like anything else, but they must never level it: a pad under
# a lake would flatten the very basin the lake sits in.
WATER_SURFACES = ('water_body', 'water_path', 'water_plane', 'lake', 'pond')


def is_sculpt(kind) -> bool:
    """A void sculpt record — parameters of the one ground heightfield, never a
    solid of its own. Like a `ground` kind it IS the ground: it keeps the base
    plane and levels nothing (a sculpt_flat laid under a sculpt_peak would
    flatten the mountain it is carving)."""
    return str(kind or '').startswith('sculpt_')


def ground_height(d, x: float, z: float) -> float:
    """The highest ground surface under world (x, z): the top of any HEIGHTS kind
    whose footprint covers the point, plus that record's y. The base plane (0) is
    the answer ONLY where no ground record covers the point — a ground cut to -15 m
    reads -15, it is not floored at the plane."""
    best = None
    with _Current(d):
        for o in d.objs:
            fn = EXT_HEIGHTS.get(o['kind'])
            if fn is None or o.get('hidden'):
                continue
            lx, lz = world_to_local(o, x, z)
            sc = o.get('s') or 1.0
            try:
                h = fn(o['p'], lx / sc, lz / sc)
            except Exception:  # noqa: BLE001 — a bad height fn must not kill placement
                h = None
            if h is None:
                continue
            y = o['y'] + h * sc
            if best is None or y > best:
                best = y
    return pad_level(d, x, z, best if best is not None else 0.0)


def ground_at(d, x: float, z: float, eps: float = 0.5) -> tuple:
    """(y, gx, gz): ground height at (x, z) and its gradient dy/dx, dy/dz (central
    differences over ±eps m). gx, gz are slopes (rise per metre), not angles."""
    y = ground_height(d, x, z)
    gx = (ground_height(d, x + eps, z) - ground_height(d, x - eps, z)) / (2 * eps)
    gz = (ground_height(d, x, z + eps) - ground_height(d, x, z - eps)) / (2 * eps)
    return y, gx, gz


def ground_plane(d, x: float, z: float, w: float, dd: float, ry: float = 0.0, n: int = 3) -> tuple:
    """(y, glx, glz, spread): a least-squares plane through the ground sampled on an
    n x n lattice over a w x dd footprint centred on (x, z) and turned by ry. y is the
    plane height at the centre, glx/glz its slope along the record's LOCAL x and z,
    spread the largest |sample − plane| in metres (0 = the ground really is flat or
    planar; > ~1 m means the footprint should be tiled into smaller records)."""
    c, s = math.cos(ry), math.sin(ry)
    pts = []
    for j in range(n):
        for i in range(n):
            lx = -w / 2 + (i + 0.5) * w / n
            lz = -dd / 2 + (j + 0.5) * dd / n
            wx = x + lx * c + lz * s
            wz = z - lx * s + lz * c
            pts.append((lx, lz, ground_height(d, wx, wz)))
    m = len(pts)
    sx = sum(p[0] for p in pts) / m
    sz = sum(p[1] for p in pts) / m
    sy = sum(p[2] for p in pts) / m
    sxx = sum((p[0] - sx) ** 2 for p in pts) or 1e-9
    szz = sum((p[1] - sz) ** 2 for p in pts) or 1e-9
    glx = sum((p[0] - sx) * (p[2] - sy) for p in pts) / sxx
    glz = sum((p[1] - sz) * (p[2] - sy) for p in pts) / szz
    y0 = sy - glx * sx - glz * sz
    spread = max(abs(p[2] - (y0 + glx * p[0] + glz * p[1])) for p in pts)
    return y0, glx, glz, spread


def ground_tilt(glx: float, glz: float) -> tuple:
    """(rx, rz) in radians that lay a record flat on a plane with LOCAL slopes glx
    (along its +X) and glz (along its +Z). rz lifts +X by atan(glx); rx lifts +Z by
    atan(glz) (THREE: rotation about +X turns +Y toward +Z, so +Z goes DOWN for a
    positive rx — hence the minus). Exact for ry = 0; for a yawed record both engines
    compose the axes in a different order (THREE XYZ intrinsic vs Blender XYZ
    extrinsic), so keep tilts under ~25 deg or split the record."""
    return -math.atan(glz), math.atan(glx)


def place_height(d, x: float, z: float, base_height=None) -> float:
    """The y a record at (x, z) should get: the explicit base_height when the caller
    gave one, else the ground under the point. Tools use this instead of 0.0.
    An explicit base_height that lands INSIDE a slab or flat roof covering the
    point (the classic "base_height=54 on a 20-storey roof whose deck is 54.3")
    is lifted to that deck's top — see deck_top()."""
    if base_height is None or base_height == '':
        return round(ground_height(d, x, z), 4)
    y = _num(base_height, 0.0)
    top, rec = deck_top(d, x, z, y)
    return round(top, 4) if rec is not None else y  # an explicit base stays exact


# ── decks (2026-09-08, design rules) ─────────────────────────────────────────
# A slab spans [y, y + t] and a flat roof [y, y + t]: the walkable DECK is the
# top, y + t, not y. Twenty storeys of 2.7 m put the roof record at 54 and its
# deck at 54.3; everything the model then places "on the roof" at base_height 54
# stands 0.3 m inside the roof — a pool's water surface, 0.1 m under its own
# rim, ends up 0.4 m below the deck and is simply never seen. So a base that
# lies inside a covering deck (or within DECK_TOL below its top) is lifted to
# the top, and design_check reports anything that still is.
DECK_KINDS = {'slab': 0.22, 'roof_flat': 0.3}  # kind -> default thickness
DECK_TOL = 0.35


def _deck_covers(o: dict, x: float, z: float) -> bool:
    """True when the rectangular slab/flat roof `o` covers world (x, z)."""
    p = o.get('p') or {}
    w, dd = _num(p.get('w'), 0.0), _num(p.get('d'), 0.0)
    if w <= 0 or dd <= 0:
        return False
    sc = o.get('s') or 1.0
    lx, lz = world_to_local(o, x, z)
    return abs(lx) <= w * sc / 2 + 1e-6 and abs(lz) <= dd * sc / 2 + 1e-6


def deck_tops(d, x: float, z: float) -> list:
    """Every deck (slab / flat roof) covering (x, z), as [(top_y, record), ...]
    highest first. Hidden records are skipped; sculpt/void kinds are not decks."""
    out = []
    for o in d.objs:
        t0 = DECK_KINDS.get(o.get('kind'))
        if t0 is None or o.get('hidden'):
            continue
        if not _deck_covers(o, x, z):
            continue
        t = _num((o.get('p') or {}).get('t'), t0)
        out.append((o['y'] + t, o))
    out.sort(key=lambda q: -q[0])
    return out


def deck_top(d, x: float, z: float, y: float, tol: float = DECK_TOL) -> tuple:
    """(y', record): the base a record placed at (x, z, y) should get. When y lies
    inside a covering deck — between its underside and its top — or within `tol`
    below that top, the answer is the deck's top and the deck; otherwise (y, None)."""
    for top, o in deck_tops(d, x, z):
        t = _num((o.get('p') or {}).get('t'), DECK_KINDS.get(o['kind'], 0.22))
        if top - t - 1e-6 <= y < top - 1e-6 or (top - tol <= y < top):
            return round(top, 4), o
    return y, None


def surface_top(d, x: float, z: float) -> float:
    """The highest walkable surface under (x, z): the top of the highest deck
    covering the point, else the ground. A camera or a person "standing at"
    a cell stands here."""
    tops = deck_tops(d, x, z)
    g = ground_height(d, x, z)
    return round(max([g] + [t for t, _o in tops]), 4)


# ── buildings on the ground (2026-09-07) ─────────────────────────────────────
# Storey 0 of anything a drawing tool builds sits on the GROUND under the middle
# of its own footprint, not on the y = 0 base plane, unless the caller names a
# base_height. Where the ground under that footprint is not level the tool does
# not refuse and does not tilt the building: it LEVELS the ground first, exactly
# as flatten_pad does — one `sculpt_flat` (the v3 void record that pulls the one
# heightfield toward `level` inside its footprint, feathered to nothing over the
# batter) plus one visible `pad` — and says so in its reply.
LEVEL_TOL = 0.30  # metres of out-of-level a footprint may keep
LEVEL_BATTER = 0.20  # the sculpt_flat feather, as a fraction of the short side


def _sculpt_flat_weight(p, lx, lz) -> float:
    """How hard a sculpt_flat pulls at a LOCAL plan point: 1 over the pad itself,
    smoothstepped to 0 across the `feather` band at its rim, 0 outside."""
    w, dd = abs(_num(p.get('w'), 0.0)), abs(_num(p.get('d'), 0.0))
    if w <= 0 or dd <= 0 or abs(lx) > w / 2 or abs(lz) > dd / 2:
        return 0.0
    f = _num(p.get('feather'), 0.0)
    f = min(max(f, 0.0), w / 2, dd / 2)
    if f <= 1e-9:
        return 1.0
    t = min((w / 2 - abs(lx)) / f, (dd / 2 - abs(lz)) / f, 1.0)
    return t * t * (3.0 - 2.0 * t)


def pad_level(d, x: float, z: float, y: float) -> float:
    """`y` after every sculpt_flat in the drawing has pulled it toward its own
    level (cut AND fill). Idempotent: a point already at the level does not move,
    so it costs nothing to apply on top of a v3 ground that summed it already."""
    for o in getattr(d, 'objs', None) or ():
        if o.get('kind') != 'sculpt_flat' or o.get('hidden'):
            continue
        lx, lz = world_to_local(o, x, z)
        sc = o.get('s') or 1.0
        wgt = _sculpt_flat_weight(o['p'], lx / sc, lz / sc)
        if wgt > 0.0:
            y += (_num(o['p'].get('level'), 0.0) - y) * wgt
    return y


def has_ground(d) -> bool:
    """True when anything in the drawing moves the ground off the base plane.
    False keeps every old drawing on the fast, byte-identical y = 0 path."""
    for o in getattr(d, 'objs', None) or ():
        if o.get('hidden'):
            continue
        if o['kind'] in EXT_HEIGHTS or o['kind'] == 'sculpt_flat':
            return True
    return False


def footprint_level(d, x: float, z: float, w: float, dd: float, ry: float = 0.0, n: int = 5) -> tuple:
    """(level, off): the MEAN ground height over a w x dd footprint centred on
    (x, z) and turned by ry, and the largest |sample - level| in metres. `off` is
    how far the ground is from LEVEL — unlike ground_plane's `spread`, which is
    the residual left after a best-fit TILT is removed and so reads 0 on a
    perfectly planar hillside that a building would still float over."""
    c, s = math.cos(ry), math.sin(ry)
    hs = []
    for j in range(n):
        for i in range(n):
            lx = -w / 2 + (i + 0.5) * w / n
            lz = -dd / 2 + (j + 0.5) * dd / n
            hs.append(ground_height(d, x + lx * c + lz * s, z - lx * s + lz * c))
    lvl = sum(hs) / len(hs)
    return lvl, max(abs(h - lvl) for h in hs)


def level_ground(
    d, x: float, z: float, w: float, dd: float, ry: float = 0.0, level=None, material='mat_gravel', grp='terrain'
) -> tuple:
    """Level the ground under a w x dd footprint: a sculpt_flat (the parameters)
    and a pad (the visible surface). Returns (level, note)."""
    fe = round(max(0.5, LEVEL_BATTER * min(w, dd)), 3)
    lvl = round(footprint_level(d, x, z, w, dd, ry)[0] if level is None else _num(level, 0.0), 4)
    if len(d.objs) + 2 > MAX_OBJECTS:
        return lvl, ''
    d.new(
        'sculpt_flat',
        {'w': round(w + 2 * fe, 4), 'd': round(dd + 2 * fe, 4), 'level': lvl, 'feather': fe},
        x,
        z,
        lvl,
        ry,
        'mat_soil',
        name=f'level {lvl:g} m',
        grp=grp,
    )
    pad = d.new(
        'pad',
        {'w': round(w, 4), 'd': round(dd, 4), 't': 0.2},
        x,
        z,
        lvl,
        ry,
        material if material in MATERIALS else 'mat_gravel',
        name=f'pad {lvl:g} m',
        grp=grp,
    )
    return lvl, (f'levelled the ground at {lvl:.1f} m first (pad {pad["id"]}, {w:g} x {dd:g} m, {fe:g} m batter). ')


def footprint_base(
    d, x: float, z: float, w: float, dd: float, ry: float = 0.0, base_height=None, level: bool = True
) -> tuple:
    """(y, note): the y that storey 0 of a footprint gets. An explicit base_height
    wins; otherwise the ground under the middle of the footprint, having levelled
    it first (and said so in `note`) when it is more than LEVEL_TOL out of level."""
    if base_height is not None and base_height != '':
        y0 = _num(base_height, 0.0)
        top, deck = deck_top(d, x, z, y0)
        if deck is not None and abs(top - y0) > 1e-6:
            return top, (
                f'base {y0:g} m lay inside {deck["id"]} ({_label(deck["kind"])}); lifted to its deck at {top:g} m. '
            )
        return y0, ''
    if not has_ground(d):
        return 0.0, ''
    if level and w > 0 and dd > 0:
        lvl, off = footprint_level(d, x, z, w, dd, ry)
        if off > LEVEL_TOL:
            return level_ground(d, x, z, w, dd, ry, level=lvl)
    return place_height(d, x, z), ''


def storey_index(d, rec, storey_h: float = 0.0, ground=None) -> int:
    """Which storey a record sits on, counted from ITS OWN base rather than from
    y = 0: (y - base) / storey_h. The base is the one the drawing tool stamped
    into p['base'], else the ground under the record. Ground records keep their
    raw y and sculpts are always storey 0 (they ARE the ground, not a storey of
    anything). A record with no base on a drawing with no
    ground is exactly the old storey_of(y, h). `ground` is has_ground(d) when the
    caller has it already — it is the expensive part of a whole-drawing listing."""
    h = storey_h or getattr(d, 'storey_h', 0.0) or STOREY_M
    if is_sculpt(rec.get('kind')):
        return 0  # a sculpt is the ground: it is on no storey
    if rec.get('kind') in EXT_HEIGHTS:
        return storey_of(rec.get('y'), h)
    p = rec.get('p') if isinstance(rec.get('p'), dict) else {}
    b = p.get('base')
    if b is None:
        if not (has_ground(d) if ground is None else ground):
            return storey_of(rec.get('y'), h)
        b = ground_height(d, _num(rec.get('x'), 0.0), _num(rec.get('z'), 0.0))
    return int(round(((_num(rec.get('y'), 0.0)) - _num(b, 0.0)) / h))


def _with_base(p: dict, base: float) -> dict:
    """Stamp a non-zero base onto a record's parameters so storey_index can read
    it back. Zero is left out: a drawing on flat ground keeps its old records."""
    if base:
        p['base'] = round(float(base), 4)
    return p


def is_opening(kind: str) -> bool:
    return kind in OPENINGS or kind in OPENINGS_EXT


def t_help(d: Drawing, a, topic=''):
    """What the assistant can do — the tool list with one line each."""
    out = []
    for t in TOOL_DEFS:
        if topic and topic.lower() not in (t['name'] + ' ' + t['description']).lower():
            continue
        out.append(f'{t["name"]}: {t["description"].split(". ")[0]}')
    return '\n'.join(out) if out else 'nothing matches'


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    KINDS,
    MATERIALS,
    MAX_OBJECTS,
    OPENINGS,
    STOREY_M,
    _num,
    storey_of,
)
from zyg_workflows.arch_assistant.drawing import (  # noqa: E402
    Drawing,
    _label,
)
from zyg_workflows.arch_assistant.walls import (  # noqa: E402
    TOOL_DEFS,
    TOOL_FN,
)

_zyg_log = _zyg_logging.getLogger(__name__)
