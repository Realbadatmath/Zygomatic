# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""finish_schedule — the finishes arrive BY CONSTRUCTION, not by repainting.

Why this family exists: on 2026-09-12 the assistant spent 6 `search_materials`
and 8 `set_material` / `set_finish` calls — 14 of a 28-call drawing budget —
hunting for ids to repaint flat `mat_*` presets, because
`finish_rules.check_luxury_finishes` errors on every preset left on a luxury
job. It still ended with "door x2 (mat_timber), pool x1 (mat_plaster)" open at
done(). A schedule of finishes is a thing an architect writes once, per kind,
and it is the same schedule every time; it does not belong in the model's
call budget.

So this module owns ONE table — SCHEDULE, keyed by finish level and then by
record kind — and three ways into it:

  · `apply_finishes(level, group)`  — the tool: one call paints every flat
    preset in the drawing per the schedule.
  · `default_mat(d, kind, mat)`     — the hook `Drawing.new` uses, so a record
    is born with its finish (wired by a later task).
  · `autofinish(d)`                 — the hook done() runs before the gate.

Rules the table obeys:
  · A LIBRARY material already on a record is a choice the user or the tool
    made — it is never repainted. Only the 21 flat `mat_*` presets (and a
    missing material) are the schedule's business.
  · `mat_glass` on a kind that is made of glass (finish_rules.GLASS_KINDS) IS
    the finish. Turning a glass porte-cochère into concrete was the 2026-09-11
    bug; it does not come back here.
  · Every id in the table is verified against
    `architecture_materials.catalogue()['defs']` by
    tests_arch_ext/test_finish_schedule.py, and the surfaces a person stands
    on or faces (floor, wall, partition) must measure lum >= 60. Marble006 is
    BLACK (lum 25/255) and is never a floor — that is `check_dark_finishes`.

No new kinds, no prompt: PROMPT is '' on purpose, the words live on the tool's
description where the model actually reads them (the system prompt has a hard
ceiling).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import Drawing, MATERIALS, EXT_MODULES, FINISHES

KINDS: dict = {}
OPENINGS: list = []
PROMPT = ''

# ── the palette ─────────────────────────────────────────────────────────────
# Every id here exists in architecture_materials.catalogue()['defs'] and its
# measured luminance is in the comment (0..255 off the albedo map).
LUX_FLOOR = 'acg_Marble021'  # 242.6 white — A.FINISHES['luxury']['floor']
LUX_ROOF = 'pht_wood_floor_deck'  # 65.4  — A.FINISHES['luxury']['roof'], a timber pool deck
LUX_PLASTER = 'acg_Plaster005'  # 165.5 light — the light interior plaster
LUX_PARTITION = 'acg_Plaster001'  # 212.0 light — 2026-09-16: Plaster005 read as grey concrete in the
#                                      lobby render, so the surfaces a visitor stands among get the
#                                      lighter plaster; the lift shaft keeps Plaster005.
LUX_WALL = 'acg_Concrete033'  # 76.3  — board-formed concrete: the LIBRARY twin of mat_concrete,
#                                      so a massing wall keeps the word the user said and stops being a
#                                      flat preset. (A.FINISHES['luxury']['wall'] stays None: set_finish
#                                      still leaves the caller's wall word alone.)
LUX_STONE = 'pht_granite_tile_04'  # 102.7 mid — light stone for stairs and landings
LUX_METAL = 'acg_Metal032'  # 134.6 mid — brushed metal
LUX_DOOR = 'pht_oak_veneer_01'  # 132.5 mid — oak leaf
LUX_POOL = 'acg_Tiles135A'  # 71.4  — deep blue tile, water_leisure's own default
LUX_COPING = 'pht_slab_tiles'  # 58.9  — the parapet cap
LUX_DECK_WOOD = 'pht_oak_veneer_04'  # 191.7 light — deck furniture
LUX_FABRIC = 'acg_Fabric045'  # 195.5 light — parasols
LUX_LEATHER = 'pht_fabric_leather_01'  # 94.0 — sofas and armchairs
LUX_DARK_OAK = 'pht_black_oak_veneer'  # 99.3 — desks
LUX_TABLE = 'pht_oak_veneer_02'  # 191.5 light — low tables
LUX_PLANTER = 'acg_Concrete034'  # 184.6 light
LUX_RUG = 'acg_Carpet003'  # 163.6 light

SCHEDULE: dict = {
    'luxury': {
        # the surfaces you stand on
        'slab': LUX_FLOOR,
        'slab_poly': LUX_FLOOR,
        'balcony': LUX_FLOOR,
        'roof_flat': LUX_ROOF,
        # the surfaces you face
        'partition': LUX_PARTITION,
        'wall': LUX_WALL,
        'wall_arc': LUX_WALL,
        'curtain_wall': LUX_WALL,
        'parapet': LUX_WALL,
        'parapet_cap': LUX_COPING,
        # leaves
        'door': LUX_DOOR,
        'double_door': LUX_DOOR,
        'door_sliding': LUX_DOOR,
        'door_french': LUX_DOOR,
        # vertical circulation
        'stair_straight': LUX_STONE,
        'stair_u': LUX_STONE,
        'stair_l': LUX_STONE,
        'stair_winder': LUX_STONE,
        'stair_spiral': LUX_STONE,
        'stair_landing': LUX_STONE,
        'railing': LUX_METAL,
        'balustrade': LUX_METAL,
        'elevator_shaft': LUX_PLASTER,
        'elevator_car': LUX_METAL,
        # structure
        'column_round': LUX_WALL,
        'column_rect': LUX_WALL,
        'column_square': LUX_WALL,
        # the deck
        'pool': LUX_POOL,
        'sun_lounger': LUX_DECK_WOOD,
        'deck_chair': LUX_DECK_WOOD,
        'umbrella': LUX_FABRIC,
        'parasol': LUX_FABRIC,
        'planter': LUX_PLANTER,
        # the lobby
        'desk': LUX_DARK_OAK,
        'reception_desk': LUX_DARK_OAK,
        'sofa': LUX_LEATHER,
        'armchair': LUX_LEATHER,
        'coffee_table': LUX_TABLE,
        'rug': LUX_RUG,
        # plant
        'hvac_unit': LUX_METAL,
        'water_tank': LUX_METAL,
        'antenna': LUX_METAL,
    },
    'standard': {
        # A standard job keeps A.FINISHES['standard'] — mat_concrete floors and
        # a bitumen roof are the honest answer to a massing study. Only the two
        # things that are WRONG as a preset are mapped: a mat_timber door leaf
        # and a pool that is not water-coloured.
        'slab': FINISHES['standard']['floor'],
        'slab_poly': FINISHES['standard']['floor'],
        'roof_flat': FINISHES['standard']['roof'],
        'door': LUX_DOOR,
        'double_door': LUX_DOOR,
        'door_sliding': LUX_DOOR,
        'door_french': LUX_DOOR,
        'pool': LUX_POOL,
    },
}

# Kinds that take the material of the WALLS of their own group rather than an
# id of their own: a string course is a band of the wall it runs across, and a
# head house is the same building as the tower under it.
GROUP_WALL_KINDS = frozenset({'string_course'})
HEAD_HOUSE_SUFFIX = ' head house'

# `canopy` is deliberately absent from SCHEDULE: add_canopy's own default is
# mat_glass, glass IS the finish of a porte-cochère (it is in GLASS_KINDS), and
# repainting one into concrete is the bug finish_rules fixed on 2026-09-11.
# `window` is absent for the same reason — a window frame is not a surface.

MAX_KINDS_IN_REPLY = 8  # kinds named in apply_finishes' answer before the '...'
DARK_LUM = 45.0  # below this a library material renders as black
MAX_DARK = 6  # findings check_dark_finishes names before folding the rest
DARK_KINDS = ('slab', 'slab_poly', 'roof_flat', 'partition', 'wall', 'wall_arc')
# how a dark surface is named, and which set_finish argument repaints it
_DARK_WORD = {
    'slab': ('floor', 'floor_material'),
    'slab_poly': ('floor', 'floor_material'),
    'roof_flat': ('roof deck', 'roof_material'),
    'partition': ('partition', 'wall_material'),
    'wall': ('wall', 'wall_material'),
    'wall_arc': ('wall', 'wall_material'),
}


# ── library / catalogue helpers ─────────────────────────────────────────────
def _rules():
    """finish_rules, fetched lazily (families load alphabetically)."""
    return EXT_MODULES.get('finish_rules')


def _glass_kinds() -> frozenset:
    F = _rules()
    return getattr(F, 'GLASS_KINDS', frozenset()) if F is not None else frozenset()


def _lib() -> set:
    try:
        return MATERIALS._library()
    except Exception:  # noqa: BLE001 — never block the drawing
        return set()


def is_preset(mat) -> bool:
    """A FLAT preset: a valid material id the PBR library does not hold."""
    m = str(mat or '')
    return bool(m) and m in MATERIALS and m not in _lib()


_DEFS: dict | None = None


def _defs() -> dict:
    global _DEFS
    if _DEFS is None:
        try:
            from zyg_workflows import architecture_materials as AM

            _DEFS = dict(AM.catalogue().get('defs') or {})
        except Exception:  # noqa: BLE001
            _DEFS = {}
    return _DEFS


def lum_of(mat) -> float | None:
    """The measured luminance (0..255) of a library material, or None."""
    row = _defs().get(str(mat or ''))
    if not isinstance(row, dict):
        return None
    v = row.get('lum')
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── the schedule ────────────────────────────────────────────────────────────
def finish_level(d: Drawing) -> str:
    F = _rules()
    if F is not None:
        try:
            lvl = str(F.finish_level(d))
        except Exception:  # noqa: BLE001
            lvl = 'standard'
    else:
        lvl = str(((getattr(d, 'ext', None) or {}).get('building_program') or {}).get('finish_level') or 'standard')
    return lvl if lvl in SCHEDULE else 'standard'


def schedule_for(d: Drawing) -> dict:
    """The kind -> library id map of THIS drawing's finish level."""
    return SCHEDULE[finish_level(d)]


def _group_wall_mat(d: Drawing, grp, sched: dict):
    """The material the walls of this group carry — the answer for a string
    course or a head house. A head house borrows from the tower under it."""
    names = [str(grp or '')]
    if names[0].endswith(HEAD_HOUSE_SUFFIX):
        names.append(names[0][: -len(HEAD_HOUSE_SUFFIX)])
    for g in names:
        if not g:
            continue
        counts: dict = {}
        for o in d.objs:
            if o.get('hidden') or str(o.get('grp') or '') != g:
                continue
            if str(o.get('kind') or '') not in ('wall', 'wall_arc'):
                continue
            m = str(o.get('mat') or '')
            if m and not is_preset(m):
                counts[m] = counts.get(m, 0) + 1
        if counts:
            return max(counts.items(), key=lambda kv: kv[1])[0]
    return sched.get('wall')


def material_for(d: Drawing, rec: dict):
    """The library id this record should carry, or None to leave it alone."""
    kind = str(rec.get('kind') or '')
    mat = str(rec.get('mat') or '')
    if mat == 'mat_glass' and kind in _glass_kinds():
        return None  # glass IS the finish here
    sched = schedule_for(d)
    if kind in GROUP_WALL_KINDS:
        return _group_wall_mat(d, rec.get('grp'), sched)
    return sched.get(kind)


def apply(d: Drawing, only_presets: bool = True, group: str = '') -> tuple:
    """Paint the schedule onto the drawing.

    `only_presets` (the default) touches only records that carry a flat mat_*
    preset or no material at all — a library id is somebody's choice.
    Returns (n_changed, {kind: {'n': int, 'mat': id}})."""
    want = str(group or '')
    by_kind: dict = {}
    # two passes: the walls settle first, then the pieces that borrow from them
    for second in (False, True):
        for o in d.objs:
            if o.get('hidden'):
                continue
            if want and str(o.get('grp') or '') != want:
                continue
            kind = str(o.get('kind') or '')
            if (kind in GROUP_WALL_KINDS) != second:
                continue
            mat = str(o.get('mat') or '')
            if only_presets and mat and not is_preset(mat):
                continue
            new = material_for(d, o)
            if not new or new == mat:
                continue
            o['mat'] = new
            row = by_kind.setdefault(kind, {'n': 0, 'mat': new})
            row['n'] += 1
            row['mat'] = new
    return sum(r['n'] for r in by_kind.values()), by_kind


def left_untouched(d: Drawing, group: str = '') -> int:
    """Records the schedule has an opinion about but did not touch, because
    they already carry a library material somebody chose."""
    want = str(group or '')
    sched = schedule_for(d)
    n = 0
    for o in d.objs:
        if o.get('hidden'):
            continue
        if want and str(o.get('grp') or '') != want:
            continue
        kind = str(o.get('kind') or '')
        if kind not in sched and kind not in GROUP_WALL_KINDS:
            continue
        m = str(o.get('mat') or '')
        if m and not is_preset(m):
            n += 1
    return n


# ── the hooks arch_assistant will call (wired by a later task) ──────────────
def default_mat(d: Drawing, kind: str, mat=None):
    """The material `Drawing.new` should stamp on a new record of this kind.

    A library id the caller named always wins. A flat preset, or nothing, is
    answered by the schedule — that is what "finishes by construction" means."""
    m = str(mat or '')
    if m and not is_preset(m):
        return mat  # the caller named a real finish
    if m == 'mat_glass' and str(kind or '') in _glass_kinds():
        return mat  # glass IS the finish here
    # 2026-09-16 (creator): only the KIND'S OWN DEFAULT preset is a blank the
    # schedule may fill. A preset the caller chose on purpose (draw_box
    # material="mat_stone", floor_material="mat_timber") is the user's word and
    # wins — test_finishes proves it. DEFAULT_MAT is read at call time so a
    # later edit to the table is honoured.
    from zyg_workflows.arch_assistant import DEFAULT_MAT

    k = str(kind or '')
    blank = (str(DEFAULT_MAT.get(k, 'mat_concrete')), TOOL_BLANKS.get(k, ''))
    if m and m not in blank:
        return mat
    return SCHEDULE[finish_level(d)].get(k) or mat


# The preset each TOOL stamps on a kind when the user named nothing — measured
# 2026-09-16 on a standard-level tower (draw_box, add_core, build_entrance,
# layout_floor, build_roof_deck, add_balconies, add_parapet, add_facade_bands).
# These, and the kind's DEFAULT_MAT, are the only presets the schedule may fill.
TOOL_BLANKS = {
    'partition': 'mat_plaster',
    'elevator_car': 'mat_steel',
    'elevator_shaft': 'mat_concrete',
    'parapet_cap': 'mat_stone',
    'string_course': 'mat_stone',
    'balcony': 'mat_concrete',
    'sun_lounger': 'mat_timber',
    'deck_chair': 'mat_timber',
    'sofa': 'mat_timber',
    'armchair': 'mat_timber',
    'coffee_table': 'mat_timber',
    'rug': 'mat_timber',
    'desk': 'mat_timber',
    'reception_desk': 'mat_timber',
    'umbrella': 'mat_paint_white',
    'parasol': 'mat_paint_white',
    'railing': 'mat_steel',
    'balustrade': 'mat_steel',
    'planter': 'mat_concrete',
    'stair_landing': 'mat_concrete',
    'column_round': 'mat_concrete',
    'column_rect': 'mat_concrete',
    'column_square': 'mat_concrete',
}


def autofinish(d: Drawing) -> int:
    """done()'s hook: paint every remaining preset. Returns how many changed."""
    return apply(d)[0]


# ── the tool ────────────────────────────────────────────────────────────────
def t_apply_finishes(d: Drawing, a, level='auto', group=''):
    lvl = str(level or 'auto').strip().lower()
    if lvl not in ('auto', '', 'luxury', 'standard'):
        return (
            f'refused: level must be "auto", "luxury" or "standard" — not "{level}"; '
            f'"auto" reads the finish level of the building programme'
        )
    grp = str(group or '').strip()
    if grp and not any(str(o.get('grp') or '') == grp for o in d.objs):
        groups = sorted({str(o.get('grp') or '') for o in d.objs if o.get('grp')})
        return (
            f'refused: nothing is in group "{grp}" — get_state(detail="objects") lists the groups'
            + (' (' + ', '.join(groups[:8]) + ')' if groups else '')
            + '; apply_finishes() with no group finishes the whole drawing'
        )

    ext = getattr(d, 'ext', None)
    if not isinstance(ext, dict):
        ext = {}
        d.ext = ext
    had = 'building_program' in ext
    orig = ext.get('building_program')
    prog = orig if isinstance(orig, dict) else {}
    # an explicit level is read for THIS call only; it is not a change of programme
    forced = lvl in ('luxury', 'standard') and str(prog.get('finish_level') or '') != lvl
    if forced:
        ext['building_program'] = dict(prog, finish_level=lvl)
    try:
        used = finish_level(d)
        n, by_kind = apply(d, only_presets=True, group=grp)
        left = left_untouched(d, grp)
    finally:
        if forced:
            if had:
                ext['building_program'] = orig
            else:
                ext.pop('building_program', None)

    where = f' in "{grp}"' if grp else ''
    if not n:
        return (
            f'nothing to finish{where}: no flat mat_* preset is left on a kind the {used} schedule '
            f'has an opinion about ({left} record(s) already carry a library material). '
            f'design_check() reports what is still open.'
        )
    rows = sorted(by_kind.items(), key=lambda kv: (-kv[1]['n'], kv[0]))
    shown = ', '.join(f'{k} x{r["n"]} -> {r["mat"]}' for k, r in rows[:MAX_KINDS_IN_REPLY])
    more = f' ... and {len(rows) - MAX_KINDS_IN_REPLY} more kind(s)' if len(rows) > MAX_KINDS_IN_REPLY else ''
    return (
        f'{n} records finished{where} per the {used} schedule: {shown}{more}; '
        f'{left} left (user-named library materials are never touched)'
    )


TOOLS = [
    (
        {
            'name': 'apply_finishes',
            'description': "Paints every flat preset (mat_*) surface with the finish schedule of the job's finish "
            'level in ONE call — floors marble, doors oak, stairs stone, lifts metal, pool blue tile. '
            'Run it once after the shell, core, rooms and roof are built; done() runs it automatically. '
            'Never repaints a library material you chose.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'level': {
                        'type': 'string',
                        'enum': ['auto', 'luxury', 'standard'],
                        'description': "auto = the building programme's finish level",
                    },
                    'group': {'type': 'string', 'description': 'one group only; omit to finish the whole drawing'},
                },
                'required': [],
            },
        },
        t_apply_finishes,
    ),
]

# Worked examples, none of them 'core': system_prompt() puts the core ones first
# and cuts the list at 40, so these teach the tool in help() and in the test's
# pooled count without spending a character of the tower prompt.
EXAMPLES = [
    {
        'ask': 'now give the whole thing the luxury finishes',
        'calls': [{'tool': 'apply_finishes', 'args': {'level': 'luxury'}}],
    },
    {
        'ask': 'finish the tower to whatever the brief said, but leave the other buildings alone',
        'calls': [{'tool': 'apply_finishes', 'args': {'level': 'auto', 'group': 'tower'}}],
    },
]


# ── the design check: a finish so dark it renders black ─────────────────────
def check_dark_finishes(d: Drawing) -> list:
    try:
        out = []
        for o in d.objs:
            if o.get('hidden'):
                continue
            kind = str(o.get('kind') or '')
            if kind not in DARK_KINDS:
                continue
            mat = str(o.get('mat') or '')
            lum = lum_of(mat)
            if lum is None or lum >= DARK_LUM:
                continue
            word, arg = _DARK_WORD.get(kind, ('surface', 'wall_material'))
            grp = str(o.get('grp') or o.get('name') or o['id'])
            fix = SCHEDULE['luxury'].get(kind) or LUX_FLOOR
            out.append(
                {
                    'sev': 'warn',
                    'code': 'finish_dark',
                    'text': (
                        f'{o["id"]} {word} {mat} renders black (lum {int(lum)}/255) — '
                        f'set_finish("{grp}", {arg}="{fix}")'
                    ),
                }
            )
        if len(out) > MAX_DARK:
            rest = len(out) - MAX_DARK
            out = out[:MAX_DARK] + [
                {
                    'sev': 'warn',
                    'code': 'finish_dark',
                    'text': (
                        f'... and {rest} more record(s) carry a library material darker '
                        f'than lum {DARK_LUM:.0f}/255 — apply_finishes() repaints the '
                        f'flat presets, set_finish(group, floor_material="{LUX_FLOOR}") '
                        f'the rest'
                    ),
                }
            ]
        return out
    except Exception as e:  # noqa: BLE001 — a check never blocks the drawing
        return [
            {
                'sev': 'info',
                'code': 'finish_dark',
                'text': f'the dark-finish check could not run ({e!r}) — nothing is claimed about the finishes',
            }
        ]


DESIGN_CHECKS = [check_dark_finishes]
