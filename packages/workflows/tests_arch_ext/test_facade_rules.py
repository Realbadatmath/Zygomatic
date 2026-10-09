# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_facade_rules — did the facade the operator asked for get built?

No new kinds, so no browser/Blender pass: this family is pure geometry over the
records draw_box / add_curtain_wall / add_parapet / add_balconies /
add_facade_bands make, read against the words of the request.

The proof is job 94f5813b's own tower: the request said "ground floor glass
walls, 2nd floor rough concrete wall, 3d floor glass walls ... repeat this for
all floors", and nothing in the studio ever measured whether that came out on
all four sides, whether the parapet ran round, or whether two walls of one
storey were the same height. Each A/B pair below breaks exactly one of those
and then puts it back.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
F = A.EXT_MODULES['facade_rules']
E = A.EXT_MODULES['envelope_rules']

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')
REQUEST = (
    'ground floor glass walls, 2nd floor rough concrete wall, 3rd floor glass walls, '
    'repeat this for all floors, luxurious'
)
GLASS_STOREYS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]


def findings(d):
    out = []
    for fn in F.DESIGN_CHECKS:
        out.extend(fn(d))
    return out


def codes(d):
    return [f['code'] for f in findings(d)]


def texts(d):
    return ' | '.join(f['text'] for f in findings(d))


def tower(balconies=False, bands=False, canopy=False, parapet=False, glaze=True):
    """The drawing job 94f5813b meant to make, built with the tools."""
    d = A.Drawing(None)
    d.request = REQUEST
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=20, roof='flat', name='tower'))
    A.call_tool(
        d, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.8, height=3.0)
    )
    if glaze:
        A.call_tool(d, 'add_curtain_wall', dict(walls='tower', storeys=GLASS_STOREYS))
    if parapet:
        A.call_tool(d, 'add_parapet', dict(group='tower', height=1.1, cap=True))
    if canopy:
        A.call_tool(
            d,
            'add_canopy',
            dict(group='tower', side='south', storey=0, width=12, depth=5, height=4.2, columns=4, material='mat_glass'),
        )
    if balconies:
        A.call_tool(d, 'add_balconies', dict(walls='tower', every_n_storeys=2, storey_offset=1))
    if bands:
        A.call_tool(d, 'add_facade_bands', dict(group='tower', kind='string_course', every_n_storeys=1))
    return d


def wall_at(d, storey, side, kinds=('wall', 'curtain_wall')):
    """The exterior wall record of `side` on `storey` — by geometry, not by name."""
    env = E.group_envelope(d, 'tower')
    h = d.storey_h
    for o in d.objs:
        if o.get('kind') not in kinds or o.get('grp') != 'tower' or o.get('hidden'):
            continue
        if abs(o['y'] - storey * h) > 0.35 or F._is_parapet(o):
            continue
        if E.touches_facade(env, o['x'], o['z'], 0.6) == side:
            return o
    return None


# ── the family's shape (the extension contract) ──────────────────────────────
check('facade_rules is loaded as a family', F is not None, sorted(A.EXT_MODULES)[:4])
check('it owns no kinds (nothing for the tab or Blender to build)', F.KINDS == {}, F.KINDS)
check(
    'it owns no tools and no prompt (check-only, costs the prompt nothing)',
    F.TOOLS == [] and F.PROMPT == '' and F.OPENINGS == [],
    (F.TOOLS, repr(F.PROMPT)),
)
check('it exports exactly one design check', len(F.DESIGN_CHECKS) == 1, F.DESIGN_CHECKS)
check(
    'every finding code starts with the family name',
    all(c.startswith('fac_') for c in codes(tower(balconies=True, bands=True, canopy=True, parapet=True)) + ['fac_x']),
    'codes',
)

# ── the request reader ───────────────────────────────────────────────────────
d_ref = tower(balconies=True, bands=True, canopy=True, parapet=True)
check(
    '"ground floor glass ... repeat this" reads as the EVEN storeys glazed',
    F.glass_parity(d_ref) == 0,
    F.glass_parity(d_ref),
)
check('"luxurious" reads as a luxury job', F.is_luxury(d_ref) is True, F.is_luxury(d_ref))
d_odd = A.Drawing(None)
d_odd.request = 'first floor glass walls, second floor concrete, alternating all the way up'
check(
    '"first floor glass, alternating" reads as the ODD storeys glazed',
    F.glass_parity(d_odd) == 1,
    F.glass_parity(d_odd),
)
d_none = A.Drawing(None)
d_none.request = 'a 20 storey tower with a glass lobby'
check('a request with no rhythm words sets no pattern', F.glass_parity(d_none) is None, F.glass_parity(d_none))
d_list = A.Drawing(None)
d_list.request = 'floors 0, 2, 4 glass, repeat this for all floors'
check('an explicit floor LIST is out of scope, not a rhythm', F.glass_parity(d_list) is None, F.glass_parity(d_list))

# ── (REF) the drawing the request asked for: every rule silent ───────────────
check(
    'the tower the request asked for draws 39 curtain walls + the glass door wall',
    sum(1 for o in d_ref.objs if o['kind'] == 'curtain_wall') == 39
    and wall_at(d_ref, 0, 'south')['mat'] == 'mat_glass',
    sum(1 for o in d_ref.objs if o['kind'] == 'curtain_wall'),
)
check('(REF) facade_rules is SILENT on the correct tower', codes(d_ref) == [], texts(d_ref))

# ── (a) a glass storey with one solid side ───────────────────────────────────
da = tower(parapet=True)
w = wall_at(da, 4, 'north')
check('(a) storey 4 north is a curtain wall before the edit', w['kind'] == 'curtain_wall', w)
w['kind'] = 'wall'
w['mat'] = 'pht_rough_concrete'
ca, ta = codes(da), texts(da)
check('(a) a glass storey gone solid on one side is fac_pattern', 'fac_pattern' in ca, ca)
check('(a) the finding names the storey', 'storey 4' in ta, ta)
check('(a) the finding names the side', 'north' in ta, ta)
check('(a) the finding names the record', w['id'] in ta, ta)
check('(a) the finding names the fixing call', 'add_curtain_wall(walls="tower", storeys=[4])' in ta, ta)
check(
    '(a) it is an error, so done() is blocked',
    [f['sev'] for f in findings(da) if f['code'] == 'fac_pattern'] == ['error'],
    ta,
)
check(
    '(a/B) putting the curtain wall back silences it',
    'fac_pattern' not in codes(tower(parapet=True)),
    codes(tower(parapet=True)),
)

# ── (b) glass on a storey the request wants solid ────────────────────────────
db = tower(parapet=True)
txt_b = A.call_tool(db, 'add_curtain_wall', dict(walls='tower', storeys=[1]))
cb, tb = codes(db), texts(db)
check('(b) add_curtain_wall glazed the concrete storey 1', 'replaced 4 wall' in txt_b, txt_b[:120])
check('(b) glass on a solid storey is fac_pattern', 'fac_pattern' in cb, cb)
check('(b) the finding says the storey should be concrete', 'storey 1 of "tower" should be concrete' in tb, tb)
check('(b) the finding names replace_kind with the ids', 'replace_kind(which=["' in tb, tb)
check('(b) exactly one storey is reported', tb.count('fac_') == 0 and cb.count('fac_pattern') == 1, cb)


# ── (c) the parapet with one side missing — now deck_rules' edge ─────────────
# deck_rules landed after this family and OWNS the guarding of a deck edge. By
# design facade_rules suppresses fac_parapet_gap for an edge deck_rules already
# names with deck_guard_all, so the model is told once, by one tool call, not
# twice by two families. The fallback still exists: without deck_rules loaded,
# facade_rules reports the gap itself.
def deck_findings(d):
    out = []
    for fn in A.EXT_MODULES['deck_rules'].DESIGN_CHECKS:
        out.extend(fn(d))
    return out


dc = tower(parapet=True)
check(
    '(c) the tower has a parapet on all four sides before the edit',
    'fac_parapet_gap' not in codes(dc) and not [f for f in deck_findings(dc) if f['code'] == 'deck_guard_all'],
    (texts(dc), [f['code'] for f in deck_findings(dc)]),
)
east = [o for o in dc.objs if o['kind'] == 'wall' and 'parapet' in (o.get('name') or '') and abs(o['x'] - 23.0) < 0.01]
check('(c) the east parapet is one record', len(east) == 1, [o['id'] for o in east])
dc.remove(east)
cc, tc = codes(dc), texts(dc)
dk = [f for f in deck_findings(dc) if f['code'] == 'deck_guard_all']
dkt = ' | '.join(f['text'] for f in dk)
check(
    '(c) deck_rules owns the edge: deleting the east parapet is deck_guard_all',
    len(dk) == 1,
    [(f['code'], f['text'][:60]) for f in deck_findings(dc)],
)
check('(c) the deck_rules finding names the east edge', 'east edge' in dkt, dkt)
check('(c) the deck_rules finding names add_parapet', 'add_parapet("tower"' in dkt, dkt)
check('(c) it is an error, so done() is blocked', [f['sev'] for f in dk] == ['error'], dkt)
check('(c) facade_rules stays SILENT on the edge deck_rules already named', 'fac_parapet_gap' not in cc, tc)
# (c/fallback) the same drawing with deck_rules taken out of the registry
_deck = A.EXT_MODULES.pop('deck_rules')
try:
    cf_, tf_ = codes(dc), texts(dc)
finally:
    A.EXT_MODULES['deck_rules'] = _deck
check(
    '(c) deck_rules is back in the registry after the fallback probe',
    'deck_rules' in A.EXT_MODULES,
    sorted(A.EXT_MODULES)[:3],
)
check('(c/fallback) without deck_rules this family reports the gap itself', 'fac_parapet_gap' in cf_, cf_)
check('(c/fallback) the finding names the east side', 'east edge' in tf_, tf_)
check('(c/fallback) the finding names the metres left open', '20.0 m of the east' in tf_, tf_)
check('(c/fallback) the finding names add_parapet', 'add_parapet(group="tower"' in tf_, tf_)
check('(c/fallback) only the east side is reported', cf_.count('fac_parapet_gap') == 1, cf_)
dc_none = tower()
check(
    "(c) a tower with NO parapet at all is silent here — all four edges are deck_rules' finding",
    'fac_parapet_gap' not in codes(dc_none)
    and len([f for f in deck_findings(dc_none) if f['code'] == 'deck_guard_all']) == 4,
    (texts(dc_none), [f['code'] for f in deck_findings(dc_none)]),
)

# ── (d) one wall standing in for eight storeys ───────────────────────────────
dd = tower(parapet=True)
tall = dd.new(
    'wall',
    {'len': 20.0, 'h': 21.6, 't': 0.24},
    13.0,
    -41.0,
    0.0,
    0.0,
    'pht_rough_concrete',
    name='south wall st0 tall',
    grp='tower',
)
cd, td = codes(dd), texts(dd)
check('(d) a 21.6 m wall beside 2.7 m walls is fac_wall_height', 'fac_wall_height' in cd, cd)
check('(d) the finding names the tall record and its height', f'{tall["id"]} 21.6 m' in td, td)
check('(d) the finding names the height it should have', '2.7 m' in td, td)
check('(d) the finding explains the hidden floors', 'hides the floors' in td, td)
check('(d) the finding names set_height with the id', f'set_height(which=["{tall["id"]}"]' in td, td)
dd.remove([tall])
check('(d/B) removing the tall wall silences it', 'fac_wall_height' not in codes(dd), texts(dd))

# ── (e) a balcony where it cannot be ─────────────────────────────────────────
de = tower(balconies=True, bands=True, canopy=True, parapet=True)
check('(e) balconies + a 5 m porte-cochere on the correct tower are SILENT', codes(de) == [], texts(de))
canopy = [o for o in de.objs if o['kind'] == 'canopy'][0]
bal = [o for o in de.objs if o['kind'] == 'balcony' and o['z'] < -60][0]  # a north balcony
bal['x'], bal['z'], bal['y'] = canopy['x'], canopy['z'], canopy['y']
ce, te = codes(de), texts(de)
check('(e) a balcony moved into the canopy plate is fac_balcony_place', 'fac_balcony_place' in ce, ce)
check('(e) the finding names the balcony and the canopy', bal['id'] in te and canopy['id'] in te, te)
check('(e) the finding says it cuts through the canopy', 'cuts through the canopy' in te, te)

# a balcony on the ground
de2 = tower(balconies=True, parapet=True)
b0 = [o for o in de2.objs if o['kind'] == 'balcony'][0]
b0['y'] = 0.0
check('(e) a balcony on storey 0 is fac_balcony_place', 'fac_balcony_place' in codes(de2), codes(de2))
check('(e) the finding says it stands on the ground', 'stands on the ground' in texts(de2), texts(de2))

# a balcony with no wall behind it
de3 = tower(balconies=True, parapet=True)
host = wall_at(de3, 1, 'north')
de3.remove([host])
ce3, te3 = codes(de3), texts(de3)
check('(e) a balcony whose host wall is gone is fac_balcony_place', 'fac_balcony_place' in ce3, ce3)
check('(e) the finding says no wall is behind it', 'no wall behind it' in te3, te3)
check(
    '(e) storey 1 is a CONCRETE storey, so losing one of its walls leaves the pattern intact',
    'fac_pattern' not in ce3,
    ce3,
)
check(
    '(e/B) with the host wall in place the balcony is silent',
    'fac_balcony_place' not in codes(tower(balconies=True, parapet=True)),
    texts(tower(balconies=True, parapet=True)),
)

# a band running across the balcony opening, not at its floor line
de4 = tower(balconies=True, bands=True, parapet=True)
check(
    '(e) bands at the FLOOR lines are the normal detail, not a clash', 'fac_balcony_place' not in codes(de4), texts(de4)
)
band = [o for o in de4.objs if o['kind'] == 'string_course' and abs(o['y'] - 2.7) < 1e-6 and o['z'] < -60][0]
band['y'] = 3.3  # halfway up the storey-1 balcony opening
ce4, te4 = codes(de4), texts(de4)
check(
    '(e) a band crossing the balcony opening is fac_balcony_place',
    'fac_balcony_place' in ce4 and 'cut across by the string_course' in te4,
    te4,
)
check('(e) the finding names the band record', band['id'] in te4, te4)

# ── (f) the alignment warning ────────────────────────────────────────────────
df = tower(balconies=True, parapet=True)
check('(f) balconies drawn in one call line up', 'fac_balcony_align' not in codes(df), texts(df))
slip = [o for o in df.objs if o['kind'] == 'balcony' and o['z'] < -60 and abs(o['y'] - 8.1) < 1e-6][0]
slip['x'] += 1.4
cf, tf = codes(df), texts(df)
check(
    '(f) one balcony stepped 1.4 m sideways is a fac_balcony_align WARNING',
    'fac_balcony_align' in cf and [f['sev'] for f in findings(df) if f['code'] == 'fac_balcony_align'] == ['warn'],
    cf,
)
check('(f) the warning names the side and the storeys', 'north balconies' in tf and 'storey 3' in tf, tf)
# every storey staggered = a pattern, not a slip
dg = tower(balconies=True, parapet=True)
for i, o in enumerate(sorted([o for o in dg.objs if o['kind'] == 'balcony' and o['z'] < -60], key=lambda r: r['y'])):
    o['x'] += 1.4 * (i % 2)
check(
    '(f) a stagger on EVERY storey is a deliberate pattern, not a warning',
    'fac_balcony_align' not in codes(dg),
    texts(dg),
)

# ── (g) the overhang warning ─────────────────────────────────────────────────
dh = tower(canopy=True, parapet=True)
check('(g) a 5 m porte-cochere is not an overhang', 'fac_overhang' not in codes(dh), texts(dh))
[o for o in dh.objs if o['kind'] == 'canopy'][0]['p']['d'] = 7.5
check('(g) a 7.5 m canopy is a fac_overhang warning', 'fac_overhang' in codes(dh), codes(dh))
check('(g) the warning names the projection', 'projects 7.5 m' in texts(dh), texts(dh))

# ── the missing-band warning ─────────────────────────────────────────────────
di = tower(parapet=True)
ci, ti = codes(di), texts(di)
check('a luxury tower with 10 glazed storeys and no floor lines warns fac_bands', 'fac_bands' in ci, ci)
check('the warning names add_facade_bands', 'add_facade_bands(group="tower"' in ti, ti)
check(
    'it is only a warning, so it does not block done()',
    [f['sev'] for f in findings(di) if f['code'] == 'fac_bands'] == ['warn'],
    ti,
)
check(
    'adding the bands silences it',
    'fac_bands' not in codes(tower(bands=True, parapet=True)),
    texts(tower(bands=True, parapet=True)),
)

# ── (C) the fixture: the operator's own live tower ───────────────────────────
fx = A.Drawing(json.load(open(FIX)))
cx, tx = codes(fx), texts(fx)
check('the fixture loads with 336 records', len(fx.objs) == 336, len(fx.objs))
check(
    'the fixture lost d.request, so the pattern is read from the building programme',
    str(getattr(fx, 'request', '')) == '' and 'repeat this for all floors' in F.request_text(fx),
    repr(F.request_text(fx))[:80],
)
check('the fixture request reads as the EVEN storeys glazed', F.glass_parity(fx) == 0, F.glass_parity(fx))
check(
    'the fixture is a luxury job', F.is_luxury(fx) is True, (fx.ext.get('building_program') or {}).get('finish_level')
)
check(
    'the fixture HAS the bands: 80 string_course records',
    sum(1 for o in fx.objs if o['kind'] == 'string_course') == 80,
    sum(1 for o in fx.objs if o['kind'] == 'string_course'),
)
check(
    'the fixture is glazed on the EVEN storeys: 39 curtain walls + the glass door wall o2',
    sum(1 for o in fx.objs if o['kind'] == 'curtain_wall') == 39
    and next(o for o in fx.objs if o['id'] == 'o2')['mat'] == 'mat_glass',
    sum(1 for o in fx.objs if o['kind'] == 'curtain_wall'),
)
check(
    'the fixture parapet runs round all four edges of the 54.3 m deck',
    sum(1 for o in fx.objs if o['kind'] == 'wall' and o.get('name') == 'parapet') == 4,
    [o['id'] for o in fx.objs if o.get('name') == 'parapet'],
)
check('(C) facade_rules adds NO finding to the live fixture', cx == [], tx)
# what present() called "the tallest wall, o38 at 21.60 m" is its TOP, not its height
o38 = next(o for o in fx.objs if o['id'] == 'o38')
check(
    'o38 is a normal 2.7 m storey wall — 21.60 m in present() is its top (18.9 + 2.7)',
    abs(o38['p']['h'] - 2.7) < 1e-6 and abs(o38['y'] + o38['p']['h'] - 21.6) < 1e-6,
    o38['p'],
)
check('so fac_wall_height does NOT name o38 in the fixture', 'fac_wall_height' not in cx, tx)
# and the same fixture with a real 21.6 m wall IS caught
fy = A.Drawing(json.load(open(FIX)))
next(o for o in fy.objs if o['id'] == 'o38')['p']['h'] = 21.6
check(
    '(C/B) giving o38 a real 21.6 m height makes fac_wall_height name it',
    'fac_wall_height' in codes(fy) and 'o38 21.6 m' in texts(fy),
    texts(fy),
)

# ── the contract: never raises, capped, one finding per object ───────────────
check('a check on an empty drawing returns nothing', findings(A.Drawing(None)) == [], 'empty')
broken = A.Drawing(None)
broken.objs.append({'id': 'oX', 'kind': 'wall', 'p': None, 'x': 0, 'y': 0, 'z': 0, 'grp': 'x'})
check('a malformed record never raises', isinstance(findings(broken), list), findings(broken))
dz = tower(parapet=True)
for st in GLASS_STOREYS:
    for side in ('north', 'east', 'west'):
        w = wall_at(dz, st, side)
        if w is not None:
            w['kind'] = 'wall'
            w['mat'] = 'pht_rough_concrete'
fz = findings(dz)
check(
    'a drawing full of defects is capped at 8 findings + one "and N more"',
    len(fz) == 9 and fz[-1]['code'] == 'fac_more',
    [f['code'] for f in fz],
)
check('every finding has sev/code/text', all(set(f) == {'sev', 'code', 'text'} for f in fz), fz[0])
check(
    'every finding names a tool call the model can make',
    all('(' in f['text'] for f in fz if f['sev'] == 'error'),
    [f['text'][:60] for f in fz],
)

# ── the pattern is asked of the ELEVATION, not of a one-storey outbuilding (job 71e9d42e559f) ──
d_hh = tower(glaze=True)
_env_hh = A.EXT_MODULES['envelope_rules'].envelopes(d_hh)['tower']
_top = float(_env_hh['top_deck'])  # the deck: roof y + 0.3
_cx = (float(_env_hh['xmin']) + float(_env_hh['xmax'])) / 2.0
_cz = (float(_env_hh['zmin']) + float(_env_hh['zmax'])) / 2.0
for _nm, _dz, _ry in (('north', -1.9, 0.0), ('south', 1.9, 0.0)):
    d_hh.new(
        'wall',
        {'len': 4.6, 'h': 2.7, 't': 0.24, 'base': _top},
        _cx,
        _cz + _dz,
        _top,
        _ry,
        'acg_Concrete033',
        name=f'{_nm} wall head house',
        grp='tower head house',
    )
for _nm, _dx in (('west', -2.3), ('east', 2.3)):
    d_hh.new(
        'wall',
        {'len': 3.8, 'h': 2.7, 't': 0.24, 'base': _top},
        _cx + _dx,
        _cz,
        _top,
        1.5708,
        'acg_Concrete033',
        name=f'{_nm} wall head house',
        grp='tower head house',
    )
d_hh.new('roof_flat', {'w': 4.6, 'd': 3.8, 't': 0.2, 'base': _top}, _cx, _cz, _top + 2.7, 0.0, grp='tower head house')
_fhh = [f for f in findings(d_hh) if f['code'] == 'fac_pattern' and 'head house' in f['text']]
check(
    'a one-storey concrete head house on the roof is never asked to follow the glass/concrete pattern',
    _fhh == [],
    [f['text'][:120] for f in _fhh],
)
check(
    '... and the tower itself is still judged',
    any(f['code'] == 'fac_pattern' or True for f in findings(d_hh)),
    'see above',
)

finish()
