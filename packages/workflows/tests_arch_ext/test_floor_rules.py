# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_floor_rules — the typical floor, read back after the tool generated it.

A 20-storey tower is laid out ONCE and repeated eighteen times, so a wrong
storey 1 is eighteen wrong storeys and nothing in the stack reads them back.
Every check here is an A/B pair: the defect drawing returns the code, the same
drawing corrected returns nothing, and the live fixture stays silent.

Two of the eight rules hand over to a sibling family when it is loaded
(floor_corridor_core -> walk_rules, floor_partition_core -> clash_rules), so
each is proved twice: silent with the sibling present, speaking without it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['floor_rules']
E = A.EXT_MODULES['envelope_rules']
DR = A.EXT_MODULES['design_rules']

Y = 2.7  # storey 1 of a 2.7 m storey
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')


def findings(d):
    return M.check_typical_floors(d)


def solo(d, drop=('walk_rules', 'clash_rules', 'building_program')):
    """The same check with the families it defers to taken off the stack."""
    saved = {k: A.EXT_MODULES.pop(k) for k in drop if k in A.EXT_MODULES}
    try:
        return M.check_typical_floors(d)
    finally:
        A.EXT_MODULES.update(saved)


def codes(fs):
    return [f['code'] for f in fs]


def texts(fs):
    return ' | '.join(f['text'] for f in fs)


def tower(storeys=20):
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=storeys, roof='flat', name='tower'))
    return d


def lift(d, cell='FD93'):
    A.call_tool(d, 'add_elevator', dict(cell=cell, from_storey=0, to_storey=20, w=1.8, depth=2.0, door_side='south'))
    return [o for o in d.objs if o['kind'] == 'elevator_shaft'][-1]


def zone(d, name, use, x0, z0, x1, z1, grp='st1'):
    w, dp = x1 - x0, z1 - z0
    return d.new(
        'zone',
        {
            'pts': [[-w / 2, -dp / 2], [w / 2, -dp / 2], [w / 2, dp / 2], [-w / 2, dp / 2]],
            'name': name,
            'use': use,
            'h': 0.05,
        },
        (x0 + x1) / 2.0,
        (z0 + z1) / 2.0,
        Y,
        0,
        'mat_paint',
        grp=grp,
    )


def door(d, x, z, grp='st1'):
    return d.new('door', {'w': 0.9, 'h': 2.1}, x, z, Y, 0, 'mat_wood', grp=grp)


def partition(d, length, x, z, ry=0.0, grp='st1'):
    return d.new('partition', {'len': length, 'h': 2.5, 't': 0.1}, x, z, Y, ry, 'mat_paint', grp=grp)


# ── the plate the corridor rules are argued on ──────────────────────────────
# A 20 x 20 m tower: lift at FD93 with its doors facing south onto a landing at
# x 8.6..10.4, z -56.5..-55.3; a corridor band along z -55.3..-53.5; three
# apartments filling the south of the plate. The corridor's north wall is drawn
# in two pieces so the 1.8 m in front of the lift doors stays open.
def plate(corridor_zone=False, seal_landing=False, use='living'):
    d = tower()
    sh = lift(d)
    cz0, cz1 = -55.3, -53.5
    if corridor_zone:
        zone(d, 'Corridor st1', 'corridor', 3.0, cz0, 23.0, cz1, grp='st1 corr')
    for i, (x0, x1) in enumerate([(3.0, 9.6667), (9.6667, 16.3333), (16.3333, 23.0)]):
        cx = (x0 + x1) / 2.0
        zone(d, f'Apartment 1.0{i + 1}', use, x0, cz1, x1, -41.0, grp=f'st1 u{i}')
        door(d, cx, cz1, grp=f'st1 u{i}')
        partition(d, x1 - x0, cx, cz1, grp=f'st1 u{i}')
        if i:
            partition(d, -41.0 - cz1, x0, (cz1 - 41.0) / 2.0, -1.570796, grp=f'st1 u{i}')
    partition(d, 5.6, 5.8, cz0, grp='st1 corr')  # west of the lift doors
    partition(d, 12.6, 16.7, cz0, grp='st1 corr')  # east of them
    if seal_landing:
        partition(d, 1.8, 9.5, cz0, grp='st1 corr')  # and now across them
    return d, sh


# ── (B) the plate laid out right: every rule silent ─────────────────────────
db, shb = plate()
fb = findings(db)
check('the corrected plate is silent on the full stack', fb == [], texts(fb))
check(
    'and silent with walk_rules and clash_rules taken off the stack',
    solo(db, drop=('walk_rules', 'clash_rules')) == [],
    texts(solo(db, drop=('walk_rules', 'clash_rules'))),
)
dz, _ = plate(corridor_zone=True)
check(
    'a plate with a declared corridor zone is silent too',
    findings(dz) == [] and solo(dz, drop=('walk_rules', 'clash_rules')) == [],
    texts(solo(dz, drop=('walk_rules', 'clash_rules'))),
)
check(
    'the lift landing really is the strip the rule measures',
    [round(v, 2) for v in M.landing_rect(shb, 1.2)] == [8.6, -56.5, 10.4, -55.3],
    [round(v, 2) for v in M.landing_rect(shb, 1.2)],
)
check(
    'zone_rect reads the polygon envelope_rules.bbox_of cannot',
    [round(v, 2) for v in M.zone_rect([o for o in db.objs if o['kind'] == 'zone'][0])] == [3.0, -53.5, 9.67, -41.0],
    [round(v, 2) for v in M.zone_rect([o for o in db.objs if o['kind'] == 'zone'][0])],
)

# ── (c) a partition drawn across the corridor in front of the lift ──────────
dc, shc = plate(seal_landing=True)
cc, tc = codes(findings(dc)), texts(findings(dc))
check(
    'walk_rules is loaded, so floor_corridor_core stays quiet',
    'walk_rules' in A.EXT_MODULES and 'floor_corridor_core' not in cc,
    cc,
)
sc = solo(dc)
check(
    'without walk_rules the sealed landing is a corridor_core error',
    'floor_corridor_core' in codes(sc) and sc[0]['sev'] == 'error',
    codes(sc),
)
check(
    'the finding names the lift and the landing',
    shc['id'] in texts(sc) and 'landing at the shaft doors' in texts(sc),
    texts(sc),
)
check('the finding names the storey it is on', texts(sc).startswith('storey 1:'), texts(sc))
check(
    'the only difference from the silent plate is that one partition',
    len(dc.objs) == len(db.objs) + 1,
    (len(dc.objs), len(db.objs)),
)

# ── (b) one unit with no door ───────────────────────────────────────────────
dd, _ = plate()
gone = [o for o in dd.objs if o['kind'] == 'door' and abs(o['x'] - 6.3334) < 0.1][0]
dd.objs[:] = [o for o in dd.objs if o is not gone]
fd = findings(dd)
check(
    'a unit whose door was deleted is a floor_unit_door error',
    codes(fd) == ['floor_unit_door'] and fd[0]['sev'] == 'error',
    codes(fd),
)
check(
    'the finding names the unit by name and by id',
    'Apartment 1.01' in fd[0]['text'] and 'has no door' in fd[0]['text'],
    fd[0]['text'],
)
check('and names layout_floor as the fix', 'layout_floor' in fd[0]['text'], fd[0]['text'])
check('the other two units are not accused', fd[0]['text'].count('Apartment') == 1, fd[0]['text'])

# ── (d) a unit in the middle of the plate with no facade ────────────────────
de, _ = plate()
dark = zone(de, 'Apartment 1.09', 'living', 11.0, -49.0, 15.0, -45.0, grp='st1 mid')
door(de, 13.0, -49.0, grp='st1 mid')
fe = findings(de)
check(
    'a landlocked living unit is a floor_unit_daylight error',
    codes(fe) == ['floor_unit_daylight'] and fe[0]['sev'] == 'error',
    codes(fe),
)
check(
    'the daylight finding names the unit and says why',
    dark['id'] in fe[0]['text'] and 'no external wall' in fe[0]['text'],
    fe[0]['text'],
)
df, _ = plate()
store = zone(df, 'Store 1.09', 'storage', 11.0, -49.0, 15.0, -45.0, grp='st1 mid')
door(df, 13.0, -49.0, grp='st1 mid')
check(
    'the same rect used as storage needs no window',
    'floor_unit_daylight' not in codes(findings(df)),
    texts(findings(df)),
)
dg, _ = plate()
office = zone(dg, 'Office 1.09', 'office', 11.0, -49.0, 15.0, -45.0, grp='st1 mid')
fg = [f for f in findings(dg) if f['code'] == 'floor_unit_daylight']
check(
    'a landlocked office is only a warning, not an error',
    len(fg) == 1 and fg[0]['sev'] == 'warn' and office['id'] in fg[0]['text'],
    [(f['sev'], f['text'][:60]) for f in fg],
)

# ── a SURVEYED PLAN's zones are rooms, not units of accommodation ────────────
# 2026-09-16: place_plan and tile_units draw the plan's own room schedule, so a
# replayed Swiss floor is 21 zones per storey named Kitchen, Bathroom, Bedroom,
# Living Dining, Corridor, Loggia. Judged as units they gave five hard errors on
# one replayed tower that are all category mistakes — a kitchen open to the
# living room "has no door", a bedroom off an internal hall "has no external
# wall" (its zone box stops 0.75 m short of the facade, past the 0.6 m
# touches_facade allows) — on a floor that is a real building, surveyed as
# built. floor_layouts records the provenance on the document, so the rule can
# tell one from the other; the finding is still said, as a warning, naming the
# room as a room.
check(
    '(plan-A) the two errors above are errors because layout_floor drew those units',
    fd[0]['sev'] == 'error' and fe[0]['sev'] == 'error' and not M.plan_storeys(dd) and not M.plan_storeys(de),
    (fd[0]['sev'], fe[0]['sev'], M.plan_storeys(dd), M.plan_storeys(de)),
)
check(
    '(plan-B) plan_storeys reads floor_layouts, and knows plan from plan_tiles',
    M.PLAN_LAYOUT_USES == {'plan', 'plan_tiles'}
    and M.plan_storeys(
        A.Drawing(
            {
                'objects': [],
                'ext': {
                    'floor_layouts': {'1': {'use': 'plan'}, '7': {'use': 'plan_tiles'}, '9': {'use': 'residential'}}
                },
            }
        )
    )
    == {1, 7},
    sorted(M.PLAN_LAYOUT_USES),
)

for _dsrc, _fs, _code, _word in (
    (dd, fd, 'floor_unit_door', 'has no door'),
    (de, fe, 'floor_unit_daylight', 'no external wall'),
):
    _dsrc.ext.setdefault('floor_layouts', {})['1'] = {'use': 'plan', 'ids': [], 'units': 1}
    _pf = [f for f in findings(_dsrc) if f['code'] == _code]
    check(
        f'(plan-B) {_code} on a plan storey is a warning, not an error',
        len(_pf) == 1 and _pf[0]['sev'] == 'warn',
        [(f['sev'], f['code']) for f in _pf],
    )
    check(
        '(plan-B) ...and it calls the zone a room, not a unit',
        len(_pf) == 1
        and _pf[0]['text'].startswith('storey 1: room "')
        and _word in _pf[0]['text']
        and 'surveyed plan' in _pf[0]['text'],
        _pf and _pf[0]['text'][:150],
    )

# ── (4) a unit too narrow to be a room ──────────────────────────────────────
dn = tower()
thin = zone(dn, 'Apartment 1.01', 'living', 3.0, -53.0, 5.5, -41.0, grp='st1 u')
door(dn, 4.25, -53.0, grp='st1 u')
fn = [f for f in findings(dn) if f['code'] == 'floor_unit_narrow']
check(
    'a 2.5 m unit is a floor_unit_narrow warning',
    len(fn) == 1 and fn[0]['sev'] == 'warn' and thin['id'] in fn[0]['text'],
    texts(findings(dn)),
)
check('the finding states the measured size', '2.5 x 12.0 m' in fn[0]['text'], fn[0]['text'])
check(
    'the 6.67 m units of the corrected plate are not narrow',
    'floor_unit_narrow' not in codes(findings(db)),
    texts(findings(db)),
)

# ── (5) a corridor two people cannot pass in ────────────────────────────────
dw = tower()
lift(dw)
zone(dw, 'Corridor st1', 'corridor', 3.0, -55.3, 23.0, -54.3, grp='st1 corr')
for i, (x0, x1) in enumerate([(3.0, 9.6667), (9.6667, 16.3333), (16.3333, 23.0)]):
    zone(dw, f'Apartment 1.0{i + 1}', 'living', x0, -54.3, x1, -41.0, grp=f'st1 u{i}')
    door(dw, (x0 + x1) / 2.0, -54.3, grp=f'st1 u{i}')
fw = findings(dw)
check(
    'a 1.0 m corridor is a floor_corridor_width error',
    codes(fw) == ['floor_corridor_width'] and fw[0]['sev'] == 'error',
    codes(fw),
)
check(
    'the finding states the clear width and the 1.2 m it is under',
    '1.00 m clear' in fw[0]['text'] and '1.2 m' in fw[0]['text'],
    fw[0]['text'],
)
check(
    'the 1.8 m corridor of the corrected plate is not reported',
    'floor_corridor_width' not in codes(findings(dz)),
    texts(findings(dz)),
)

# ── (6) a partition drawn through the lift shaft ────────────────────────────
dp = tower()
shp = lift(dp)
cut = partition(dp, 8.0, 9.5, -57.5)
check(
    'clash_rules is loaded, so floor_partition_core stays quiet',
    'clash_rules' in A.EXT_MODULES and 'floor_partition_core' not in codes(findings(dp)),
    codes(findings(dp)),
)
sp = [f for f in solo(dp) if f['code'] == 'floor_partition_core']
check(
    'without clash_rules the partition through the shaft is an error',
    len(sp) == 1 and sp[0]['sev'] == 'error',
    [f['code'] for f in solo(dp)],
)
check(
    'the finding names both records and the overlap it measured',
    cut['id'] in sp[0]['text'] and shp['id'] in sp[0]['text'] and '1.80 x 0.10 m overlap' in sp[0]['text'],
    sp[0]['text'],
)

# ── (7) a storey that is a bare slab ────────────────────────────────────────
dbare = tower()
check(
    'building_program owns the missing-plan finding, so this family is quiet',
    'building_program' in A.EXT_MODULES and findings(dbare) == [],
    texts(findings(dbare)),
)
sb = solo(dbare)
check(
    'without building_program the bare storeys are one folded warning',
    codes(sb) == ['floor_empty'] and sb[0]['sev'] == 'warn',
    codes(sb),
)
check('the warning folds all nineteen of them onto one line', sb[0]['text'].startswith('storeys 1..19:'), sb[0]['text'])
check(
    'the envelope walls draw_box gives each storey do not count as a fitout',
    'a bare slab' in sb[0]['text'],
    sb[0]['text'],
)

# ── (a) the drawing the tools actually make, and (e) the odd storey ─────────
da = tower()
A.call_tool(da, 'add_stair', dict(cell='FH93', from_storey=0, to_storey=20, kind='u', width=1.2))
lift_a = lift(da)
txt_a = A.call_tool(
    da,
    'layout_floor',
    dict(cell_from='EX90', cell_to='FQ109', use='residential', storey=1, core_from='FC91', core_to='FK96'),
)
txt_r = A.call_tool(da, 'repeat_floor', dict(from_storey=2, to_storey=19, source_storey=1))
fa = findings(da)
check(
    'layout_floor + repeat_floor laid out 19 storeys',
    'storey 1 laid out' in txt_a and 'repeated onto storeys' in txt_r,
    txt_a[:80],
)
check('on the full stack the tool-built tower draws no floor finding', fa == [], texts(fa))
check(
    'every unit the tool drew has its door and its facade',
    not [
        f
        for f in solo(da)
        if f['code'] in ('floor_unit_door', 'floor_unit_daylight', 'floor_unit_narrow', 'floor_corridor_width')
    ],
    [f['text'][:70] for f in solo(da)],
)
# and the true finding underneath: layout_floor(core_from, core_to) does not put
# the corridor along the core, it only leaves those unit slots out — so the
# stair and the lift end up in a pocket with no way in. Reported in not_done.
sa = solo(da)
check(
    'without walk_rules the core pocket layout_floor leaves is an error',
    [f['code'] for f in sa] == ['floor_corridor_core', 'floor_corridor_core'],
    [f['code'] for f in sa],
)
check(
    'both findings fold all nineteen storeys onto one line each',
    all(f['text'].startswith('storeys 1..19:') for f in sa),
    [f['text'][:40] for f in sa],
)
check(
    'one names the lift, the other the stair',
    lift_a['id'] in sa[0]['text'] and 'the stair' in sa[1]['text'],
    [f['text'][:80] for f in sa],
)
check(
    'folding kept the measurement intact, it only genericised the labels',
    'the 1.2 m of floor' in sa[1]['text'],
    sa[1]['text'],
)

# (e) storey 7 laid out unlike its neighbours
kill = [o for o in da.objs if o['kind'] == 'partition' and abs(o['y'] - 7 * Y) < 0.01]
da.objs[:] = [o for o in da.objs if o not in kill[: len(kill) // 2]]
f7 = [f for f in findings(da) if f['code'] == 'floor_repeat_mismatch']
check(
    'half of storey 7 removed is a floor_repeat_mismatch warning',
    len(f7) == 1 and f7[0]['sev'] == 'warn',
    codes(findings(da)),
)
# 2026-09-16: layout_floor draws more partitions per storey than it used to (the
# three-sided stair enclosure and the core-door walls), so the two counts are read off
# the drawing instead of hard-coded — what is proved here is that the finding states
# BOTH of them, not what they happen to be this month.
_left = len([o for o in da.objs if o['kind'] == 'partition' and abs(o['y'] - 7 * Y) < 0.01])
_typ = len([o for o in da.objs if o['kind'] == 'partition' and abs(o['y'] - 2 * Y) < 0.01])
check(
    'the warning names storey 7 and both counts',
    f7[0]['text'].startswith('storey 7:') and ('%d partitions against %d' % (_left, _typ)) in f7[0]['text'],
    '%s :: expected "%d partitions against %d"' % (f7[0]['text'], _left, _typ),
)
check('and names repeat_floor as the fix', 'repeat_floor(' in f7[0]['text'], f7[0]['text'])

# ── (f) the live fixture ────────────────────────────────────────────────────
fx = A.Drawing(json.load(open(FIX)))
check('the fixture loads', len(fx.objs) == 336, len(fx.objs))
check('the family is silent on the live tower', findings(fx) == [], texts(findings(fx)))
sfx = solo(fx)
check(
    'its storeys 1-19 are bare, so only floor_empty has anything to say',
    codes(sfx) == ['floor_empty'] and sfx[0]['text'].startswith('storeys 1..19:'),
    texts(sfx),
)

# ── the check never raises, whatever it is handed ───────────────────────────
check('an empty drawing is silent', M.check_typical_floors(A.Drawing(None)) == [])
check('a one-storey box is silent', M.check_typical_floors(tower(storeys=1)) == [], texts(findings(tower(storeys=1))))


class _Blows:
    objs = property(lambda self: (_ for _ in ()).throw(RuntimeError('no objs')))
    storey_h = 2.7


bad = M.check_typical_floors(_Blows())
check(
    'a drawing it cannot read returns one info finding, never an exception',
    len(bad) == 1 and bad[0]['sev'] == 'info' and bad[0]['code'] == 'floor_rules_error',
    bad,
)

# ── the family contract ─────────────────────────────────────────────────────
check(
    'DESIGN_CHECKS exports the two checks (typical floors, partition head — 2026-09-16)',
    [f.__name__ for f in M.DESIGN_CHECKS] == ['check_typical_floors', 'check_partition_head'],
    [f.__name__ for f in M.DESIGN_CHECKS],
)
check('design_rules collects it', M.check_typical_floors in DR.contributed())
check(
    'run_checks reports nothing about the floors of the fixture',
    [f for f in DR.run_checks(fx) if f['code'].startswith('floor_')] == [],
    [f['text'] for f in DR.run_checks(fx) if f['code'].startswith('floor_')],
)
check(
    'this family is check-only: no kinds, no tools, no openings, no prompt',
    M.KINDS == {} and M.TOOLS == [] and M.OPENINGS == [] and M.PROMPT == '' and M.EXAMPLES == [],
    (M.KINDS, M.TOOLS, M.OPENINGS, M.PROMPT, M.EXAMPLES),
)
check(
    'it never reports more than eight findings',
    M.MAX_FINDINGS == 8
    and len(M._fold([{'sev': 'warn', 'code': 'floor_x', 'st': i, 'key': i, 'msg': str(i)} for i in range(30)])) == 9,
    len(M._fold([{'sev': 'warn', 'code': 'floor_x', 'st': i, 'key': i, 'msg': str(i)} for i in range(30)])),
)
check(
    'every finding names a tool the model can call',
    all(
        (
            'layout_floor' in f['text']
            or 'repeat_floor' in f['text']
            or 'tile_units' in f['text']
            or 'add a door' in f['text']
            or 'move the partition' in f['text']
        )
        for f in sa + sb + sc + sp + fd + fe + fw + f7
    ),
    [
        f['text']
        for f in sa + sb + sc + sp + fd + fe + fw + f7
        if 'layout_floor' not in f['text'] and 'repeat_floor' not in f['text']
    ][:2],
)

# ── part_head_gap: a partition that stops short of the slab above (2026-09-16) ──
FR = A.EXT_MODULES['floor_rules']
dph = tower(3)
slab0 = [o for o in dph.objs if o['kind'] == 'slab'][0]
cx, cz = slab0['x'], slab0['z']  # inside the plate (the tower is centred on FH100, not the origin)
lo = dph.new('partition', {'len': 8.0, 'h': 2.5, 't': 0.1}, cx, cz, 0.0, 0.0, grp='tower')
fph = FR.check_partition_head(dph)
check(
    'part_head_gap: a 2.5 m partition under a 2.7 m storey fires (warn)',
    [f['code'] for f in fph] == ['part_head_gap'] and fph[0]['sev'] == 'warn',
    fph,
)
check(
    '... and names the partition, the storey and the height to draw',
    fph and lo['id'] in fph[0]['text'] and 'storey 0' in fph[0]['text'] and 'wall_h=2.7' in fph[0]['text'],
    [f['text'] for f in fph],
)
lo['p']['h'] = 2.7
check(
    'part_head_gap: the same partition run to the slab is silent',
    FR.check_partition_head(dph) == [],
    FR.check_partition_head(dph),
)
hi = dph.new('partition', {'len': 8.0, 'h': 1.2, 't': 0.1}, cx, cz, 3 * dph.storey_h, 0.0, grp='tower')
check(
    'part_head_gap: a low screen on the roof (no slab above) is silent',
    FR.check_partition_head(dph) == [],
    FR.check_partition_head(dph),
)
lo2 = dph.new('partition', {'len': 8.0, 'h': 2.5, 't': 0.1}, cx, cz, dph.storey_h, 0.0, grp='tower')
DRr = A.EXT_MODULES['design_rules']
check(
    'part_head_gap is wired into run_checks', 'part_head_gap' in codes(DRr.run_checks(dph)), codes(DRr.run_checks(dph))
)
check(
    'add_room now draws its partitions to the slab underside (the gate is silent by construction)',
    (
        lambda dd: (
            A.call_tool(dd, 'add_room', dict(cell_from='FB96', cell_to='FJ104', storey=0, name='Lobby')),
            FR.check_partition_head(dd) == []
            and all(abs(o['p']['h'] - dd.storey_h) < 1e-9 for o in dd.objs if o['kind'] == 'partition'),
        )[1]
    )(tower(3)),
    'see add_room',
)

finish()
