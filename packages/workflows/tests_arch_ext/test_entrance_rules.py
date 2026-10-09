# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_entrance_rules — 'a nice entrance into the building with a lobby'.

Check-only family, so there is nothing to draw and no browser/Blender pass: the
proof is that the entrance the TOOLS build (add_opening + add_canopy + add_room +
furnish_lobby) raises no ent_ error, and that every defect the rules name does.

Each rule is proved as an A/B pair on the same good drawing: the good build is
silent, the one changed number fires, and the finding says the number back.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
EN = A.EXT_MODULES['entrance_rules']
DR = A.EXT_MODULES['design_rules']

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, 'fixtures', 'live_tower_20260911.json')


# ── the contract ─────────────────────────────────────────────────────────────
check('entrance_rules is loaded as a family', 'entrance_rules' in A.EXT_MODULES)
check(
    'it is check-only: no kinds, no openings, no tools',
    not EN.KINDS and not EN.OPENINGS and not EN.TOOLS,
    (len(EN.KINDS), len(EN.OPENINGS), len(EN.TOOLS)),
)
check('it spends nothing of the prompt budget', EN.PROMPT == '', repr(EN.PROMPT)[:60])
check('it contributes exactly one check', len(EN.DESIGN_CHECKS) == 1, EN.DESIGN_CHECKS)
check(
    'design_rules collects it', any(getattr(fn, '__module__', '').endswith('entrance_rules') for fn in DR.contributed())
)


def findings(d):
    out = []
    for fn in EN.DESIGN_CHECKS:
        out.extend(fn(d))
    return out


def codes(d):
    return [f['code'] for f in findings(d)]


def errs(d):
    return [f['code'] for f in findings(d) if f['sev'] == 'error']


def texts(d):
    return ' | '.join(f['text'] for f in findings(d))


def build(
    storeys=8,
    door_w=2.8,
    canopy=True,
    canopy_w=12,
    canopy_h=4.2,
    columns=4,
    lobby=('FD103', 'FM109'),
    furnish=True,
    request='a luxurious tower with a nice entrance',
    programme=True,
):
    """The entrance the brief asks for, with one number at a time turned bad."""
    d = A.Drawing(None)
    d.request = request
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=storeys, roof='flat', name='tower'))
    if programme:
        A.call_tool(
            d, 'plan_building', dict(use='office', storeys=storeys, cell_from='EX90', cell_to='FQ109', request=request)
        )
    A.call_tool(
        d, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=door_w, height=3.0)
    )
    if canopy:
        A.call_tool(
            d,
            'add_canopy',
            dict(
                group='tower',
                side='south',
                storey=0,
                width=canopy_w,
                depth=5,
                height=canopy_h,
                columns=columns,
                material='mat_glass',
            ),
        )
    if lobby:
        A.call_tool(d, 'add_room', dict(cell_from=lobby[0], cell_to=lobby[1], storey=0, name='Lobby'))
        if furnish:
            A.call_tool(d, 'furnish_lobby', dict(cell_from=lobby[0], cell_to=lobby[1], storey=0, entrance_side='south'))
    return d


def entrance(d):
    """(door, x, z, inward normal) of the one entrance these builds make."""
    e = EN.entrances(d)[0]
    return e['door'], e['x'], e['z'], -e['nx'], -e['nz']


# ── the good entrance: no ent_ error at all ──────────────────────────────────
d0 = build()
c0 = codes(d0)
check('the tools build one entrance', len(EN.entrances(d0)) == 1, EN.entrances(d0))
check(
    'add_opening put a 2.8 m double door on the south wall',
    entrance(d0)[0]['p']['w'] == 2.8 and entrance(d0)[0]['kind'] == 'double_door',
    entrance(d0)[0],
)
check(
    'add_room put the lobby behind it with no partition on the facade line',
    sum(1 for o in d0.objs if o.get('grp') == 'Lobby' and o['kind'] == 'partition') == 3,
    [o['id'] for o in d0.objs if o.get('grp') == 'Lobby'],
)
check(
    'furnish_lobby put desks and seats in it',
    sum(1 for o in d0.objs if o['kind'] in EN.DESK_KINDS) >= 1
    and sum(
        1
        for o in d0.objs
        if o['kind'] in EN.SEAT_KINDS
        or (o['kind'] == 'asset' and any(w in str(o.get('name') or '').lower() for w in ('sofa', 'armchair')))
    )
    >= 2,  # luxury seats are pack models (2026-09-16)
    [o['kind'] for o in d0.objs if o.get('grp', '').endswith('fit-out')],
)
check('THE GATE: the good entrance raises no ent_ error', errs(d0) == [], errs(d0))
check(
    'its only word is the floor warning, and it is a warning',
    [f['sev'] for f in findings(d0)] == ['warn'] * len(findings(d0)),
    findings(d0),
)

# ── (1) ent_door_width ───────────────────────────────────────────────────────
d1 = build(door_w=0.9)
check('a 0.9 m door into an 8-storey building is an error', 'ent_door_width' in errs(d1), codes(d1))
check('the finding names the width and the storeys', '0.9 m wide' in texts(d1) and '8 storeys' in texts(d1), texts(d1))
check('the finding names the fix by tool', 'add_opening' in texts(d1) and 'double_door' in texts(d1), texts(d1))
check('a 2.8 m door is silent', 'ent_door_width' not in codes(d0), codes(d0))
d1b = build(storeys=3, door_w=0.9)
check(
    'the same 0.9 m door into a 3-storey building is NOT an error — a house has a house door',
    'ent_door_width' not in codes(d1b),
    codes(d1b),
)

# ── (2) ent_canopy_missing ───────────────────────────────────────────────────
d2 = build(canopy=False)
check('a luxury entrance with no canopy is an error', 'ent_canopy_missing' in errs(d2), codes(d2))
check('the finding names add_canopy with a size', 'add_canopy' in texts(d2), texts(d2))
check('a canopy over the door is silent', 'ent_canopy_missing' not in codes(d0), codes(d0))
d2b = build(canopy=False, request='a plain warehouse', programme=False)
check('a plain building is not asked for a canopy', 'ent_canopy_missing' not in codes(d2b), codes(d2b))
d2c = build(canopy=False, request='a grand entrance for the offices', programme=False)
check('the words "grand entrance" alone ask for one', 'ent_canopy_missing' in errs(d2c), codes(d2c))
d2d = build(canopy=False, request='an office with a porte cochere', programme=False)
check('so does "porte"', 'ent_canopy_missing' in errs(d2d), codes(d2d))

# ── (3) ent_canopy_low ───────────────────────────────────────────────────────
d3 = build(canopy_h=2.8)
check('a canopy soffit at 2.8 m over a 2.7 m door is an error', 'ent_canopy_low' in errs(d3), codes(d3))
check('the finding gives both heights', '2.80 m' in texts(d3) and '2.70 m' in texts(d3), texts(d3))
check('the 4.2 m soffit of the good build is silent', 'ent_canopy_low' not in codes(d0), codes(d0))

# ── (4) ent_canopy_narrow — a warning, not an error ──────────────────────────
d4 = build(canopy_w=4, columns=0)
f4 = [f for f in findings(d4) if f['code'] == 'ent_canopy_narrow']
check('a 4 m canopy over a 2.8 m door is a narrowness finding', len(f4) == 1, codes(d4))
check('and it is a WARNING — a narrow canopy still shelters the door', f4 and f4[0]['sev'] == 'warn', f4)
check(
    'the finding gives the canopy and door widths',
    f4 and '4 m wide' in f4[0]['text'] and '2.8 m door' in f4[0]['text'],
    f4,
)
check('the 12 m canopy of the good build is silent', 'ent_canopy_narrow' not in codes(d0), codes(d0))

# ── (5) ent_column_axis ──────────────────────────────────────────────────────
d5 = build()
_door5, x5, z5, inx5, inz5 = entrance(d5)
d5.new(
    'column_round',
    {'r': 0.3, 'h': 5.0},
    x5 - inx5 * 3.0,
    z5 - inz5 * 3.0,
    0.0,
    0.0,
    'mat_concrete',
    name='rogue column',
    grp='tower',
)
check('a column planted on the door axis 3 m out is an error', 'ent_column_axis' in errs(d5), codes(d5))
check('the finding says how far out it stands — measured to its near face, 2.7 m', '2.7 m out' in texts(d5), texts(d5))
check(
    'the finding names the record and the tool that places columns properly',
    'rogue column' in texts(d5) or d5.objs[-1]['id'] in texts(d5),
    texts(d5),
)
check("add_canopy's own 4 columns are NOT on the axis", 'ent_column_axis' not in codes(d0), codes(d0))
_inner = sorted(
    abs(o['x'] - entrance(d0)[1]) for o in d0.objs if o['kind'] in DR.COLUMN_KINDS and o.get('grp') == 'tower'
)
check(
    'measured: the inner pair of a 12 m / 4-column canopy stands 1.41 m off the axis',
    _inner and abs(_inner[0] - 1.41) < 0.05,
    _inner,
)

# ── (6) ent_lamp_canopy ──────────────────────────────────────────────────────
# Two ways in: standing under the canopy plan rect at all, or standing clear of it
# but taller than its soffit and close enough to run through the edge.
d6 = build()
_door6, x6, z6, inx6, inz6 = entrance(d6)
d6.new(
    'lamp_post',
    {'h': 5.0, 'r': 0.12},
    x6 - inx6 * 2.0,
    z6 - inz6 * 2.0,
    0.0,
    0.0,
    'mat_steel',
    name='tall lamp',
    grp='site',
)
check('a lamp standing under the canopy is an error', 'ent_lamp_canopy' in errs(d6), codes(d6))
check(
    'the finding says it is UNDER the canopy and names both records',
    'UNDER' in texts(d6) and 'tall lamp' in texts(d6) and 'o43' in texts(d6),
    texts(d6),
)
check('the good build has no lamp under its canopy', 'ent_lamp_canopy' not in codes(d0), codes(d0))
d6c = build()  # just clear of the 5 m deep canopy, but touching its edge, and 5.0 m tall
_d, x6c, z6c, inx6c, inz6c = entrance(d6c)
d6c.new(
    'lamp_post',
    {'h': 5.0, 'r': 0.12},
    x6c - inx6c * 5.3,
    z6c - inz6c * 5.3,
    0.0,
    0.0,
    'mat_steel',
    name='tall lamp',
    grp='site',
)
check('a 5.0 m lamp touching the canopy edge runs through it', 'ent_lamp_canopy' in errs(d6c), codes(d6c))
check(
    'and that finding gives the lamp height and the soffit',
    '5.00 m' in texts(d6c) and '4.20 m' in texts(d6c),
    texts(d6c),
)
d6b = build()
_d, x6b, z6b, inx6b, inz6b = entrance(d6b)
d6b.new(
    'lamp_post',
    {'h': 3.0, 'r': 0.12},
    x6b - inx6b * 5.3,
    z6b - inz6b * 5.3,
    0.0,
    0.0,
    'mat_steel',
    name='short lamp',
    grp='site',
)
check('a 3.0 m lamp in the same place passes under the 4.2 m soffit', 'ent_lamp_canopy' not in codes(d6b), codes(d6b))

# ── (7) ent_lobby_behind ─────────────────────────────────────────────────────
d7 = build(lobby=None)
check('no lobby at all is an error', 'ent_lobby_behind' in errs(d7), codes(d7))
check('the finding names add_room', 'add_room' in texts(d7), texts(d7))
d7b = build(lobby=('FD90', 'FM96'))  # a lobby at the far end of the plate
check('a lobby that is not behind the door is an error', 'ent_lobby_behind' in errs(d7b), codes(d7b))
check(
    'the finding says how far in the lobby starts and what is behind the door instead',
    'm further in' in texts(d7b) and '1 m inside the door' in texts(d7b),
    texts(d7b),
)
check('the good build opens straight into its lobby', 'ent_lobby_behind' not in codes(d0), codes(d0))

# ── (8) ent_lobby_size — only when building_program is NOT loaded ────────────
# 4 cells across x 6 deep, its south side ON the facade so only the size is wrong
d8 = build(lobby=('FF104', 'FI109'), furnish=False, programme=False)
check('a 4 x 6 m luxury lobby with no programme loaded is a size error', 'ent_lobby_size' in errs(d8), codes(d8))
check(
    'the finding gives the size and the two minima',
    '6.1 x 4.1 m' in texts(d8) and '8 m across' in texts(d8) and '6 m deep' in texts(d8),
    texts(d8),
)
check(
    'and it is the only lobby error — the room really is behind the door',
    'ent_lobby_behind' not in codes(d8),
    codes(d8),
)
d8b = build(lobby=('FF104', 'FI109'), furnish=False, programme=True)
check(
    'with plan_building loaded the rule stands down — building_program measures it',
    'ent_lobby_size' not in codes(d8b),
    codes(d8b),
)
check('the 10 x 7 m lobby of the good build is silent', 'ent_lobby_size' not in codes(d0), codes(d0))

# ── (9) ent_lobby_fitout ─────────────────────────────────────────────────────
d9 = build(furnish=False)
check('a bare luxury lobby is an error', 'ent_lobby_fitout' in errs(d9), codes(d9))
check(
    'the finding names furnish_lobby and the entrance side',
    'furnish_lobby' in texts(d9) and 'entrance_side' in texts(d9),
    texts(d9),
)
check('the furnished lobby is silent', 'ent_lobby_fitout' not in codes(d0), codes(d0))
d9b = build(furnish=False, request='a plain office block', programme=False)
check('a plain building is not asked to furnish its lobby', 'ent_lobby_fitout' not in codes(d9b), codes(d9b))

# ── (10) ent_lobby_floor — a warning ─────────────────────────────────────────
f10 = [f for f in findings(d0) if f['code'] == 'ent_lobby_floor']
check('a bare mat_ slab under a luxury lobby is a floor finding', len(f10) == 1, codes(d0))
check('and it is a WARNING — a grey floor is not a fault, only a missed chance', f10 and f10[0]['sev'] == 'warn', f10)
check(
    'the finding names set_finish and a real preset',
    f10 and 'set_finish' in f10[0]['text'] and 'acg_' in f10[0]['text'],
    f10,
)
d10 = build()
for _o in d10.objs:
    if _o['kind'] in ('slab', 'slab_poly') and abs(_o.get('y', 0.0)) < 0.5:
        _o['mat'] = 'acg_Marble021'
check('a marble floor is silent', 'ent_lobby_floor' not in codes(d10), codes(d10))

# ── (11) ent_door_clutter ────────────────────────────────────────────────────
d11 = build()
_door11, x11, z11, _ix, _iz = entrance(d11)
d11.new('door', {'w': 0.9, 'h': 2.1}, x11 + 0.8, z11, 0.0, 0.0, 'mat_wood', name='spare door', grp='tower')
check('a second door 0.8 m from the entrance is an error', 'ent_door_clutter' in errs(d11), codes(d11))
check(
    'the finding gives the distance and says to delete it',
    '0.80 m' in texts(d11) and 'delete' in texts(d11),
    texts(d11),
)
check('the good build has one door in its facade', 'ent_door_clutter' not in codes(d0), codes(d0))
d11b = build()
_d, x11b, z11b, _ix, _iz = entrance(d11b)
d11b.new('door', {'w': 0.9, 'h': 2.1}, x11b + 4.0, z11b, 0.0, 0.0, 'mat_wood', name='side door', grp='tower')
check('a second door 4 m away is a second door, not a duplicate', 'ent_door_clutter' not in codes(d11b), codes(d11b))

# ── (12) ent_axis_blocked ────────────────────────────────────────────────────
d12 = build()
_door12, x12, z12, inx12, inz12 = entrance(d12)
d12.new(
    'partition',
    {'len': 6.0, 'h': 2.7, 't': 0.1},
    x12 + inx12 * 2.0,
    z12 + inz12 * 2.0,
    0.0,
    0.0,
    'mat_plaster',
    name='screen',
    grp='tower',
)
check('a partition 2 m inside the door, across the axis, is an error', 'ent_axis_blocked' in errs(d12), codes(d12))
check('the finding says how far in it stands', '2.0 m inside' in texts(d12), texts(d12))
check("the good build's own fit-out does NOT block its axis", 'ent_axis_blocked' not in codes(d0), codes(d0))
check(
    "nor do the lobby's own partitions — they are what draws the room",
    'ent_axis_blocked' not in codes(build(furnish=False)),
    codes(build(furnish=False)),
)

# ── the whole check never raises, and never floods ───────────────────────────
check('an empty drawing is silent', findings(A.Drawing(None)) == [], findings(A.Drawing(None)))
dj = A.Drawing(None)
dj.request = 'luxurious'
for _i in range(30):
    dj.new('door', {'w': 0.5, 'h': 2.0}, float(_i) * 0.3, 0.0, 0.0, 0.0, 'mat_wood', grp='junk')
_fj = findings(dj)
check('a drawing full of junk does not raise', all('sev' in f for f in _fj), _fj[:2])
_per = {}
for f in _fj:
    _per[f['code']] = _per.get(f['code'], 0) + 1
check('no code exceeds the 8-finding cap', not _per or max(_per.values()) <= 8, _per)
dbad = A.Drawing(None)
dbad.objs = [{'id': 'oX', 'kind': 'double_door'}]  # a record missing every field
check('a malformed record does not raise either', isinstance(findings(dbad), list), findings(dbad))

# ── the live tower: what these rules say about the job that passed ───────────
dlive = A.Drawing(json.load(open(FIXTURE)))
check('the live tower fixture loads', len(dlive.objs) == 336, len(dlive.objs))
clive = codes(dlive)
tlive = texts(dlive)
check(
    'it has one exterior entrance on storey 0, o102, though it has 5 doors there',
    [e['door']['id'] for e in EN.entrances(dlive)] == ['o102'],
    [e['door']['id'] for e in EN.entrances(dlive)],
)
check('its 2.4 m door is wide enough for the rule', 'ent_door_width' not in clive, clive)
check(
    'its canopy o103 is found, so no canopy finding',
    'ent_canopy_missing' not in clive and 'ent_canopy_low' not in clive and 'ent_canopy_narrow' not in clive,
    clive,
)
check('none of its columns stands on the door axis', 'ent_column_axis' not in clive, clive)
# TRUE FINDING. The fixture's "Lobby" is four bare partitions (o511..o514) forming
# a 10.1 x 3.1 m box whose south side, o512, stands 1.0 m INSIDE the entrance —
# so the visitor steps out of o102 into the tower's own storey-0 volume and has
# to find the little 0.9 m door o515 in that partition to get into the "lobby".
check('TRUE FINDING: the entrance does not open into the lobby', 'ent_lobby_behind' in clive, clive)
check('and the finding names the door and the gap', 'o102' in tlive and '1.0 m further in' in tlive, tlive)
# TRUE FINDING. Not one desk, chair or sofa was ever put in it.
check('TRUE FINDING: that lobby is empty', 'ent_lobby_fitout' in clive, clive)
check('and the finding gives its 10.1 x 3.1 m', '10.1 x 3.1 m' in tlive, tlive)
# o515 is 1.41 m from the entrance but it is hosted by the LOBBY's own partition
# o512, not by the tower's south wall, so it is not a second leaf in one opening —
# it is the door of the room behind, and ent_lobby_behind is what names that.
check('o515 is not called door clutter: it is in another wall', 'ent_door_clutter' not in clive, clive)
check(
    "and its 5 lamp posts clear the canopy — light_lamps_env's defaults stand 1.06 m out",
    'ent_lamp_canopy' not in clive,
    clive,
)
check('and the corridor wall o535 blocks the way in', 'ent_axis_blocked' in clive and 'o535' in tlive, tlive)
check(
    'everything it says is an error or a warning, nothing is info',
    all(f['sev'] in ('error', 'warn') for f in findings(dlive)),
    [(f['code'], f['sev']) for f in findings(dlive)],
)
check(
    'it says at most 8 things per code',
    max([0] + [sum(1 for f in findings(dlive) if f['code'] == c) for c in set(clive)]) <= 8,
    clive,
)

finish()
