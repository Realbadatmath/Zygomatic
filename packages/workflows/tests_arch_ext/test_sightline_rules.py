# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_sightline_rules.py — proof for the sightline check (2026-09-10).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_sightline_rules.py

Job 71ac02b0's plan test (design_rules.check_entrance) went quiet as soon as the
trees were moved 7-8 cells off the entrance axis. This family casts the real
line of sight instead — eye at 1.6 m, 30/15/8 m out, door at 1.1 m — so the
tests here are arithmetic on that segment, not on the plan strip.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
SR = A.EXT_MODULES.get('sightline_rules')
DR = A.EXT_MODULES['design_rules']

check('family loads', SR is not None)
check('no new kinds, no new tools', SR.KINDS == {} and SR.TOOLS == [])
check('PROMPT is one paragraph <= 500 chars', 0 < len(SR.PROMPT) <= 500, len(SR.PROMPT))
check('>= 2 examples, each with calls', len(SR.EXAMPLES) >= 2 and all(e.get('calls') for e in SR.EXAMPLES))
check(
    'check_sightline is contributed to the done gate',
    SR.check_sightline in DR.contributed(),
    [f.__name__ for f in DR.contributed()],
)


def tower():
    """20 x 20 m, 3 storeys, a double door in the middle of the south wall."""
    txt, d = assistant('draw_box', dict(centre='FH100', width=20, depth=20, storeys=3, roof='flat', name='tower'))
    A.call_tool(d, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.4, height=3))
    door = [o for o in d.objs if o['kind'] == 'double_door'][0]
    return d, door


def codes(f):
    return {x['code']: x for x in f}


# ── the geometry the whole check rests on ────────────────────────────────────
d, door = tower()
ax = DR._door_axis(d, door)
check(
    'the south door faces +Z (south), outward normal (0, 1)',
    ax is not None
    and abs(ax[0] - 13.0) < 1e-6
    and abs(ax[1] + 41.0) < 1e-6
    and abs(ax[2]) < 1e-6
    and abs(ax[3] - 1.0) < 1e-6,
    ax,
)
check(
    'an empty forecourt hides nothing (the host wall is not its own obstacle)',
    'sightline' not in codes(SR.check_sightline(d)),
    SR.check_sightline(d),
)
check(
    'a door on bare ground is a WARN',
    codes(SR.check_sightline(d)).get('approach', {}).get('sev') == 'warn',
    SR.check_sightline(d),
)

# ── (a) a tree standing ON the axis, crown down to eye level ─────────────────
d, door = tower()
t = d.new(
    'tree_deciduous',
    {'h': 6, 'r_can': 3.6, 'r_trunk': 0.3},
    13.0,
    -31.0,
    0.0,
    0.0,
    'mat_grass',
    name='Jacaranda 3',
    grp='trees',
)
f = SR.check_sightline(d)
e = codes(f).get('sightline')
check(
    'a low-crowned tree on the axis 10 m out is an ERROR that names it',
    e is not None
    and e['sev'] == 'error'
    and t['id'] in e['text']
    and 'crosses the sightline 10.0 m out' in e['text']
    and 'crown 7.2 m' in e['text'],
    e,
)
check('the finding says how to fix it', e is not None and '6 m off the axis' in e['text'], e)
check('an error suppresses the bare-ground warn (one finding per door)', len(f) == 1, f)

# ── (b) the SAME tree 8 m off the axis: the segment clears the sphere ────────
d, door = tower()
d.new(
    'tree_deciduous',
    {'h': 6, 'r_can': 3.6, 'r_trunk': 0.3},
    21.0,
    -31.0,
    0.0,
    0.0,
    'mat_grass',
    name='Jacaranda 3',
    grp='trees',
)
# arithmetic: eye (13, 1.6, -11) -> door (13, 1.1, -41); crown centre (21, 2.4, -31), r 3.6.
# The segment is the line x = 13, so the closest approach is >= 8 m in x alone.
eye, tgt, c, r = (13.0, 1.6, -11.0), (13.0, 1.1, -41.0), (21.0, 6 - 3.6, -31.0), 3.6
tt = ((c[0] - eye[0]) * 0 + (c[1] - eye[1]) * (tgt[1] - eye[1]) + (c[2] - eye[2]) * (tgt[2] - eye[2])) / (
    (tgt[1] - eye[1]) ** 2 + (tgt[2] - eye[2]) ** 2
)
near = math.dist((eye[0], eye[1] + tt * (tgt[1] - eye[1]), eye[2] + tt * (tgt[2] - eye[2])), c)
check(
    '8 m off the axis the closest approach is 8.08 m > the 3.6 m crown',
    abs(near - 8.08) < 0.02 and near > r and not SR.seg_sphere(eye, tgt, c, r),
    (near, tt),
)
check(
    '...so the sightline check is silent about it',
    'sightline' not in codes(SR.check_sightline(d)),
    SR.check_sightline(d),
)

# ── the 12 m tree of the brief: it clears the eye line, the PLAN test still has it ──
d, door = tower()
t12 = d.new(
    'tree_deciduous',
    {'h': 12, 'r_can': 3.6, 'r_trunk': 0.3},
    13.0,
    -31.0,
    0.0,
    0.0,
    'mat_grass',
    name='Jacaranda 3',
    grp='trees',
)
check(
    'a 12 m tree on the axis hangs OVER the sightline (crown bottom 12 - 2x3.6 = 4.8 m), no error',
    'sightline' not in codes(SR.check_sightline(d)),
    SR.check_sightline(d),
)
check(
    'the same tree is still named by the plan test (design_rules axis warn)',
    any(x['code'] == 'axis' and t12['id'] in x['text'] for x in DR.check_entrance(d)),
    DR.check_entrance(d),
)

# ── (c) a garden wall across the axis 5 m out ────────────────────────────────
d, door = tower()
w = d.new(
    'wall', {'len': 10.0, 'h': 2.5, 't': 0.24}, 13.0, -36.0, 0.0, 0.0, 'mat_concrete', name='garden wall', grp='fence'
)
e = codes(SR.check_sightline(d)).get('sightline')
check(
    'a 2.5 m wall across the axis 5 m out is an ERROR naming it',
    e is not None
    and e['sev'] == 'error'
    and w['id'] in e['text']
    and 'crosses the sightline 5.0 m out' in e['text']
    and '2.5 m tall' in e['text'],
    e,
)
d.objs[-1]['hidden'] = True
check('a hidden record is not an obstacle', 'sightline' not in codes(SR.check_sightline(d)))

# ── (e) a canopy over the door: soffit at 4 m is not an obstacle ─────────────
d, door = tower()
txt = A.call_tool(d, 'add_canopy', dict(group='tower', side='south', storey=0, width=8, depth=4, height=4, columns=0))
check('add_canopy put a 4 m soffit on the entrance', 'soffit at y 4' in txt, txt)
check(
    'the canopy soffit raises no sightline error',
    'sightline' not in codes(SR.check_sightline(d)),
    SR.check_sightline(d),
)

# ── (d) a drive up to the door clears the bare-ground warn ───────────────────
d, door = tower()
txt = A.call_tool(d, 'add_road', dict(cells=['FH120', 'FH103'], width=6))
check('add_road laid a carriageway on the axis', 'carriageway' in txt, txt)
check(
    'the bare-ground warn is gone, and the road is not itself an obstacle',
    SR.check_sightline(d) == [],
    SR.check_sightline(d),
)

# ── (f) no doors, and the done gate ──────────────────────────────────────────
txt, d0 = assistant('draw_box', dict(centre='FH100', width=20, depth=20, storeys=1, name='shed'))
check('a drawing with no door yields no findings', SR.check_sightline(d0) == [], SR.check_sightline(d0))

d, door = tower()
d.new(
    'tree_deciduous',
    {'h': 6, 'r_can': 3.6, 'r_trunk': 0.3},
    13.0,
    -31.0,
    0.0,
    0.0,
    'mat_grass',
    name='Jacaranda 3',
    grp='trees',
)
check(
    'run_checks() collects the sightline error',
    any(x['code'] == 'sightline' and x['sev'] == 'error' for x in DR.run_checks(d)),
    [x['code'] for x in DR.run_checks(d)],
)
job = {'log': [], '_gate': 0}
log = job['log'].append
_bp = A.EXT_MODULES.get('blender_power')
if _bp is not None and hasattr(_bp, 'present_sig'):
    d.ext['presented'] = {'sig': _bp.present_sig(d)}  # the present() gate comes first (2026-09-10)
r1 = A.design_gate(job, d, {'summary': 'x'}, log)
check(
    'done REFUSES while the entrance is hidden',
    r1.startswith('done REFUSED') and 'hidden from the drive' in r1,
    r1[:160],
)

# ── the two intersection routines on their own ──────────────────────────────
check(
    'seg_sphere: a sphere on the segment hits, one past its end does not',
    SR.seg_sphere((0, 0, 0), (10, 0, 0), (5, 0, 1.5), 2.0)
    and not SR.seg_sphere((0, 0, 0), (10, 0, 0), (5, 0, 1.5), 1.0)
    and not SR.seg_sphere((0, 0, 0), (10, 0, 0), (14, 0, 0), 3.0),
)
check(
    'seg_aabb: a segment through a box hits, one under it does not',
    SR.seg_aabb((-5, 1, 0), (5, 1, 0), (-1, 0, -1), (1, 2, 1))
    and not SR.seg_aabb((-5, 5, 0), (5, 5, 0), (-1, 0, -1), (1, 2, 1))
    and not SR.seg_aabb((-5, 1, 9), (5, 1, 9), (-1, 0, -1), (1, 2, 1)),
)

finish()
