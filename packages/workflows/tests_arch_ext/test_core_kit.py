# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_core_kit — the whole vertical core in one call, clash-free.

No new kinds and no new checks, so no browser / Blender pass: core_kit only
arranges the records add_stair and add_elevator already make. The proof is the
defect live run 038ca075c052 shipped — a 3.44 x 2.60 m u stair at FH93 with
lift shafts 0.62 m inside it either side — reproduced as the thing add_core is
not allowed to produce, on every position, at every size, and with an inner
refusal in the middle of the sequence.
"""

import ast
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
M = A.EXT_MODULES['core_kit']
C = A.EXT_MODULES['circulation_rules']
E = A.EXT_MODULES['envelope_rules']
S = A.EXT_MODULES['stairs_vertical']
CL = A.EXT_MODULES.get('clash_rules')  # may not exist yet — guarded everywhere


def tower(width=20, depth=20, storeys=20, name='tower'):
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=width, depth=depth, storeys=storeys, roof='flat', name=name))
    return d


def circ(d):
    out = []
    for fn in C.DESIGN_CHECKS:
        out.extend(fn(d) or [])
    return out


def clash(d):
    if CL is None:
        return []
    out = []
    for fn in getattr(CL, 'DESIGN_CHECKS', []) or []:
        out.extend(fn(d) or [])
    return out


def core_errors(d, ids, findings):
    """The ERROR findings that name one of the core's own records."""
    pat = re.compile(r'\b(' + '|'.join(re.escape(i) for i in ids) + r')\b')
    return [f for f in findings if f['sev'] == 'error' and pat.search(f['text'])]


# ── (a) the 20-storey tower the whole tree is about ──────────────────────────
da = tower()
ra = A.call_tool(da, 'add_core', dict(group='tower', position='north', lifts=2))
check('add_core on the 20-storey tower is not refused', 'refused' not in ra, ra)
check(
    'the reply names the core, the lifts and the stair', 'core "core"' in ra and 'lifts o' in ra and 'U-stair' in ra, ra
)
check(
    'the reply names the shared landing and the head house',
    'shared landing' in ra and 'head house on the deck' in ra,
    ra,
)
check('the reply names the lobby side', 'Lobby side: south' in ra, ra)

ext = (da.ext.get('core') or {}).get('tower') or {}
ids = list(ext.get('lifts') or []) + list(ext.get('stair') or [])
check(
    'd.ext["core"]["tower"] records lifts, stair, landing and position',
    len(ext.get('lifts') or []) == 2
    and len(ext.get('stair') or []) == 20
    and len(ext.get('landing') or []) == 4
    and ext.get('position') == 'north',
    ext,
)

fa = circ(da)
codes_a = [f['code'] for f in fa]
check('no circ_core_clash anywhere in the drawing', 'circ_core_clash' not in codes_a, codes_a)
check('no circ_stair_approach anywhere in the drawing', 'circ_stair_approach' not in codes_a, codes_a)
check(
    'circulation_rules give 0 errors for the core records',
    not core_errors(da, ids, fa),
    [f['text'] for f in core_errors(da, ids, fa)],
)
check('check_head_house is silent', not C.check_head_house(da), C.check_head_house(da))
check('check_continuity is silent', not C.check_continuity(da), [f['text'] for f in C.check_continuity(da)])
check('envelope_rules.check_envelope is silent', not E.check_envelope(da), [f['text'] for f in E.check_envelope(da)])

stairs = [o for o in da.objs if o['kind'] in C.STAIR_KINDS]
shafts = [o for o in da.objs if o['kind'] == C.SHAFT_KIND]
check('20 stair records, one per storey', len(stairs) == 20, len(stairs))
check('2 lift shafts', len(shafts) == 2, len(shafts))
check(
    'every shaft has a door on every served storey (0..20)',
    all(o['p'].get('doors') == list(range(0, 21)) for o in shafts),
    [o['p'].get('doors') for o in shafts],
)
check(
    'every shaft has the 1.5 m overrun above the deck',
    all(abs(float(o['p'].get('overrun') or 0) - S.OVERRUN) < 1e-9 for o in shafts),
    [o['p'].get('overrun') for o in shafts],
)
head = [o for o in da.objs if str(o.get('grp') or '').endswith('head house')]
check(
    'the head house stands on the deck (4 walls + roof + door)', len(head) == 6, [(o['kind'], o['grp']) for o in head]
)

# the defect this family exists to prevent, measured directly
sbb = [E.bbox_of(o) for o in stairs]
lbb = [E.bbox_of(o) for o in shafts]
zones = [z for o in stairs for z in S.approach_bboxes(o)]
check(
    'no stair record overlaps a shaft in plan',
    not any(S.plan_clash(a, b) for a in sbb for b in lbb),
    [(S.plan_overlap(a, b)) for a in sbb for b in lbb],
)
check(
    "no shaft stands in the 1.2 m at the stair's foot",
    not any(S.plan_clash(z, b) for z in zones for b in lbb),
    [S.plan_overlap(z, b) for z in zones for b in lbb],
)
check('the two shafts are clear of each other', not S.plan_clash(lbb[0], lbb[1]), S.plan_overlap(lbb[0], lbb[1]))
env_a = E.group_envelope(da, 'tower')
check(
    'the core is set back >= 1.0 m from the north facade',
    min(b[1] for b in sbb + lbb) - env_a['zmin'] >= M.SETBACK_M - 1e-6,
    min(b[1] for b in sbb + lbb) - env_a['zmin'],
)
check(
    'the strip keeps 0.6 m to both side facades',
    min(b[0] for b in sbb + lbb) - env_a['xmin'] >= M.SIDE_CLEAR_M - 1e-6
    and env_a['xmax'] - max(b[2] for b in sbb + lbb) >= M.SIDE_CLEAR_M - 1e-6,
    (min(b[0] for b in sbb + lbb) - env_a['xmin'], env_a['xmax'] - max(b[2] for b in sbb + lbb)),
)

# ── (f) clash_rules, when that family exists ─────────────────────────────────
cl = clash(da)
check(
    'clash_rules report no clash_core_* on the result' if CL is not None else 'clash_rules is not loaded yet (skipped)',
    CL is None or not [f for f in cl if str(f['code']).startswith('clash_core')],
    [f['text'] for f in cl if str(f['code']).startswith('clash_core')],
)

# ── (b) every position ───────────────────────────────────────────────────────
DOORS = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east', 'centre': 'south'}
for pos in M.POSITIONS:
    dp = tower()
    rp = A.call_tool(dp, 'add_core', dict(group='tower', position=pos, lifts=2))
    ok = 'refused' not in rp
    check(f'position={pos} places the core', ok, rp)
    if not ok:
        continue
    idp = [o['id'] for o in dp.objs if o['kind'] in C.STAIR_KINDS + (C.SHAFT_KIND,)]
    fp = circ(dp)
    check(
        f'position={pos}: 0 circulation errors on the core',
        not core_errors(dp, idp, fp),
        [f['text'] for f in core_errors(dp, idp, fp)],
    )
    check(f'position={pos}: check_envelope silent', not E.check_envelope(dp), [f['text'] for f in E.check_envelope(dp)])
    check(
        f'position={pos}: doors face {DOORS[pos]}',
        all(o['p'].get('door_side') == DOORS[pos] for o in dp.objs if o['kind'] == C.SHAFT_KIND),
        [o['p'].get('door_side') for o in dp.objs if o['kind'] == C.SHAFT_KIND],
    )
    check(
        f'position={pos}: 20 stair records and 2 shafts',
        len([o for o in dp.objs if o['kind'] in C.STAIR_KINDS]) == 20
        and len([o for o in dp.objs if o['kind'] == C.SHAFT_KIND]) == 2,
        len(idp),
    )

# ── (c) a plate too small refuses, with the size that would fit ──────────────
ds = tower(width=6, depth=6, name='small')
rs = A.call_tool(ds, 'add_core', dict(group='small', position='north'))
check('a 6 x 6 plate is refused', rs.startswith('refused:'), rs)
check('the refusal names the smallest plate that fits', re.search(r'at least [\d.]+ x [\d.]+ m', rs) is not None, rs)
check('the refusal names the plate it actually has', '6.0 x 6.0 m' in rs, rs)
check(
    'nothing was drawn on the refusal',
    not [o for o in ds.objs if o['kind'] in C.STAIR_KINDS + (C.SHAFT_KIND,)],
    [o['kind'] for o in ds.objs if o['kind'] in C.STAIR_KINDS + (C.SHAFT_KIND,)],
)

# ── (d) an inner refusal leaves nothing behind ───────────────────────────────
du = tower()
before_ids = [o['id'] for o in du.objs]
before_kinds = sorted(o['kind'] for o in du.objs)
_real_call = A.call_tool


def _fake_call(d, name, args):
    if name == 'add_stair':
        return 'refused: x'
    return _real_call(d, name, args)


A.call_tool = _fake_call
try:
    ru = A.call_tool(du, 'add_core', dict(group='tower', position='north', lifts=2))
finally:
    A.call_tool = _real_call
check('add_core is refused when add_stair refuses', ru.startswith('refused:'), ru)
check(
    'the refusal carries the inner reason and the cells tried',
    'cells tried:' in ru and 'refused: x'[len('refused:') :].strip() in ru,
    ru,
)
check(
    'no shaft record remains after the undo',
    not [o for o in du.objs if o['kind'] == C.SHAFT_KIND],
    [o['id'] for o in du.objs if o['kind'] == C.SHAFT_KIND],
)
check('no lift car remains after the undo', not [o for o in du.objs if o['kind'] == 'elevator_car'], len(du.objs))
check(
    'the drawing is byte-identical to what it was before the call',
    [o['id'] for o in du.objs] == before_ids and sorted(o['kind'] for o in du.objs) == before_kinds,
    (len(du.objs), len(before_ids)),
)
check('d.ext has no core entry after the undo', not (du.ext.get('core') or {}), du.ext.get('core'))

# ── (e) cell_of is the exact inverse of parse_cell ───────────────────────────
random.seed(20260916)
bad = []
for _ in range(20):
    c, r = random.randrange(0, A.GRID_N), random.randrange(0, A.GRID_N)
    want = A.cell_name(c, r)
    x, z = A.cell_centre(c, r)
    got = M.cell_of(x, z)
    if got != want or A.parse_cell(got) != (c, r):
        bad.append((want, got))
check('cell_of round-trips parse_cell for 20 random cells', not bad, bad)
edge = []
for name in ('A1', 'FH100', 'KN300', 'FD93', 'FJ93'):
    c, r = A.parse_cell(name)
    x0, z0, x1, z1 = A.block_bounds(name, name)
    if M.cell_of((x0 + x1) / 2, (z0 + z1) / 2) != name:
        edge.append(name)
check('cell_of agrees with block_bounds on named cells', not edge, edge)

# ── (g) the prompt budget ────────────────────────────────────────────────────
R = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_all.py')).read()
req = ast.literal_eval(re.search(r'TOWER_REQUEST = (\(.*?\))\n', R, re.S).group(1))
bare, tow = len(A.system_prompt(2.7)), len(A.system_prompt(2.7, req))
print(f'  prompt budget: PROMPT {len(M.PROMPT)} chars, bare {bare}, tower {tow}')
check('core_kit PROMPT is within its 220-char budget', len(M.PROMPT) <= 220, len(M.PROMPT))
check('the bare system prompt is under 90 000 chars', bare < 90000, bare)
check('the tower system prompt is under 45 000 chars', tow < 45000, tow)
check(
    'core_kit adds one tool and no kinds',
    [t[0]['name'] for t in M.TOOLS] == ['add_core'] and M.KINDS == {} and M.DESIGN_CHECKS == [],
    ([t[0]['name'] for t in M.TOOLS], M.KINDS, M.DESIGN_CHECKS),
)

finish()
