# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_precision_snaps.py — proves the seven Precision snap
icons (pr_end, pr_mid, pr_cen, pr_int, pr_perp, pr_tan, pr_near) stopped being
placeholders AND actually snap.

Two page loads only: icon_state for the dock state, then ONE browser_eval that
builds a small drawing and calls arExtSnap directly — which is exactly what
arClick and arDraftMove do with the pointer's ground point, so no pointer is
needed. The rest is the assistant side, in-process.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['pr_end', 'pr_mid', 'pr_cen', 'pr_int', 'pr_perp', 'pr_tan', 'pr_near']

# ── 1. the dock ───────────────────────────────────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s is a real icon (exists, no stub flag, no dashed border, no [placeholder] tip)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )
check(
    'all seven live in the Precision section of the dock',
    all((st.get(i) or {}).get('section') == 'Precision' for i in IDS),
    {i: (st.get(i) or {}).get('section') for i in IDS},
)

# ── 2. the snapping itself ────────────────────────────────────────────────────
JS = r"""() => {
  const out = {};
  const IDS = ['pr_end','pr_mid','pr_cen','pr_int','pr_perp','pr_tan','pr_near'];
  out.radius = arPrecisionSnapsRadius(0.3);          /* 12 px would be camera-dependent */
  const set = (list) => IDS.forEach(id => arTool(id, {on: list.indexOf(id) >= 0}));
  const mk = (kind, p, x, z, ry) => { const r = arNewObj(kind, p, x, z, 0); r.ry = ry || 0; arApplyTransform(r); return r; };
  const S = (P) => arExtSnap(P, {x: P.x, y: 0, z: P.z}, {});

  mk('wall', {len:4, h:2.7, t:0.2}, 2, 0, 0);            /* W1: (0,0) -> (4,0) */
  mk('column_round', {r:0.2, h:2.7}, 6, 6, 0);           /* a column at (6,6) */
  mk('wall', {len:4, h:2.7, t:0.2}, 2, 2, 0);            /* WA: (0,2) -> (4,2) */
  mk('wall', {len:4, h:2.7, t:0.2}, 2, 2, -Math.PI/2);   /* WB: (2,0) -> (2,4), crosses WA at (2,2) */
  mk('guide_circle', {r:1}, 10, 0, 0);                   /* a guide circle r=1 at (10,0) */
  mk('wall', {len:0.4, h:2.7, t:0.2}, 20.2, 0, 0);       /* WS: (20,0) -> (20.4,0), endpoint and midpoint equally near */

  AR.draft = null;
  set(['pr_end']);  out.end = S({x:3.9,  z:0.05, y:0});
  set(['pr_mid']);  out.mid = S({x:2.05, z:0.1,  y:0});
  set(['pr_cen']);  out.cen = S({x:6.1,  z:5.95, y:0});
  set(['pr_int']);  out.int = S({x:2.1,  z:1.9,  y:0});

  AR.draft = {tool:'wall', a:{x:2, z:3, y:0}, chain:0};
  set(['pr_perp']); out.perp = S({x:2.05, z:0.08, y:0});
  AR.draft = {tool:'wall', a:{x:10, z:-5, y:0}, chain:0};
  set(['pr_tan']);  out.tan = S({x:10.95, z:-0.15, y:0});
  const A = AR.draft.a, C = {x:10, z:0};
  out.tanR = Math.hypot(out.tan.x - C.x, out.tan.z - C.z);
  out.tanDot = (out.tan.x - A.x) * (out.tan.x - C.x) + (out.tan.z - A.z) * (out.tan.z - C.z);

  AR.draft = null;
  set(['pr_near']); out.near = S({x:1.3, z:0.12, y:0});
  set([]);          out.off  = S({x:3.9, z:0.05, y:0});
  set(['pr_end','pr_mid']); out.prio = S({x:20.1, z:0.02, y:0});

  /* the switches latch, persist and mirror into the document */
  set(['pr_end','pr_int']);
  out.latch = IDS.map(id => arToolOn(arToolDef(id)));
  out.ls = JSON.parse(localStorage.getItem('ar.precision_snaps'));
  out.docext = AR.doc.ext.precision_snaps;

  /* the marker and the hint suffix */
  set(['pr_end']);
  arHint('<b>2.000 m</b>');
  arPrecisionSnapMove({x:3.92, z:0.04}, {});
  out.markOn = AR._prMark.visible;
  out.markCol = AR._prMark.material.color.getHex();
  out.markPos = [Math.round(AR._prMark.position.x*1e3)/1e3, Math.round(AR._prMark.position.z*1e3)/1e3];
  out.hint1 = document.getElementById('ar-hint').innerHTML;
  arPrecisionSnapMove({x:3.92, z:0.04}, {});
  arPrecisionSnapMove({x:3.92, z:0.04}, {});
  out.hint3 = document.getElementById('ar-hint').innerHTML;
  arDraftMove({x:3.92, z:0.04}, {});                    /* the studio's own move path is wrapped */
  out.markViaDraftMove = AR._prMark.visible;
  arPrecisionSnapMove({x:50, z:50}, {});
  out.markOff = AR._prMark.visible;
  out.hintOff = document.getElementById('ar-hint').innerHTML;

  /* the index follows the document, and stops at the storey band */
  set(['pr_end']);
  out.idxBefore = S({x:30.05, z:0.05, y:0});
  mk('wall', {len:2, h:2.7, t:0.2}, 31, 0, 0);          /* (30,0) -> (32,0) */
  out.idxAfter = S({x:30.05, z:0.05, y:0});
  const up = mk('wall', {len:4, h:2.7, t:0.2}, 40, 0, 0);
  up.y = 5.4; arApplyTransform(up);                     /* two storeys up: out of the band */
  out.band = S({x:38.05, z:0.05, y:0});
  return out;
}"""

r = browser_eval(JS)
v = r['value']


def near(p, x, z, snap):
    return bool(p) and abs(p['x'] - x) < 1e-4 and abs(p['z'] - z) < 1e-4 and p.get('snap') == snap


check('no page errors while snapping', not r['errors'], r['errors'])
check('the radius setter took (0.3 m stands in for 12 px)', v['radius'] == 0.3, v['radius'])
check('pr_end snaps (3.9, 0.05) to the wall endpoint (4, 0)', near(v['end'], 4, 0, 'endpoint'), v['end'])
check('pr_mid snaps (2.05, 0.1) to the wall midpoint (2, 0)', near(v['mid'], 2, 0, 'midpoint'), v['mid'])
check('pr_cen snaps (6.1, 5.95) to the column centre (6, 6)', near(v['cen'], 6, 6, 'centre'), v['cen'])
check('pr_int snaps (2.1, 1.9) to where the two walls cross (2, 2)', near(v['int'], 2, 2, 'intersection'), v['int'])
check(
    'pr_perp snaps to the foot (2, 0) of the perpendicular from the draft point (2, 3)',
    near(v['perp'], 2, 0, 'perpendicular'),
    v['perp'],
)
check(
    'pr_tan snaps to a tangent point of the r=1 circle at (10, 0) from the draft point (10, -5)',
    v['tan'].get('snap') == 'tangent' and abs(v['tanR'] - 1.0) < 1e-3 and abs(v['tanDot']) < 1e-3,
    {'tan': v['tan'], 'r': v['tanR'], 'dot': v['tanDot']},
)
check('pr_near snaps (1.3, 0.12) onto the wall at (1.3, 0)', near(v['near'], 1.3, 0, 'nearest'), v['near'])
check(
    'with every snap off the point comes back unchanged',
    abs(v['off']['x'] - 3.9) < 1e-9 and abs(v['off']['z'] - 0.05) < 1e-9 and not v['off'].get('snap'),
    v['off'],
)
check(
    'priority: a point equally near an endpoint and a midpoint takes the endpoint (20, 0)',
    near(v['prio'], 20, 0, 'endpoint'),
    v['prio'],
)

check(
    'the switches latch exactly as pressed (pr_end + pr_int on, the rest off)',
    v['latch'] == [True, False, False, True, False, False, False],
    v['latch'],
)
check(
    "the state persists in localStorage 'ar.precision_snaps'",
    v['ls']
    == {
        'pr_end': True,
        'pr_mid': False,
        'pr_cen': False,
        'pr_int': True,
        'pr_perp': False,
        'pr_tan': False,
        'pr_near': False,
    },
    v['ls'],
)
check('and is mirrored in AR.doc.ext.precision_snaps', v['docext'] == v['ls'], v['docext'])

check(
    'the feedback marker shows at the snapped point in the endpoint colour',
    v['markOn'] and v['markPos'] == [4.0, 0.0] and v['markCol'] == 0x00E5FF,
    {'on': v['markOn'], 'pos': v['markPos'], 'col': hex(v['markCol'])},
)
check('the snap name is appended to the hint', '\u00b7 endpoint' in v['hint1'] and '2.000 m' in v['hint1'], v['hint1'])
check('three moves do not stack three names', v['hint3'] == v['hint1'] and v['hint3'].count('pr-snap') == 1, v['hint3'])
check("the studio's own arDraftMove drives the marker too", v['markViaDraftMove'], v['markViaDraftMove'])
check(
    'the marker hides and the name is dropped when nothing snaps',
    not v['markOff'] and 'pr-snap' not in v['hintOff'],
    {'on': v['markOff'], 'hint': v['hintOff']},
)

check('the candidate index is empty there before the wall is drawn', not v['idxBefore'].get('snap'), v['idxBefore'])
check(
    'the index rebuilds when the document changes: the new endpoint (30, 0) snaps',
    near(v['idxAfter'], 30, 0, 'endpoint'),
    v['idxAfter'],
)
check(
    'a record two storeys up is outside the drawing plane band and does not snap',
    not v['band'].get('snap') and abs(v['band']['x'] - 38.05) < 1e-9,
    v['band'],
)

# ── 3. the assistant may press all seven, with {"on": ...} ────────────────────
from zyg_workflows import arch_assistant as A  # noqa: E402

check(
    'all seven ids are pressable by the model (EXT_BUTTONS)',
    [i for i in IDS if i not in A.EXT_BUTTONS] == [],
    sorted(A.EXT_BUTTONS)[:20],
)
txt, d = assistant('press_button', {'id': 'pr_end', 'args': {'on': True}})
check(
    'press_button("pr_end", {"on": true}) is accepted and carries its args',
    txt.startswith('pressed') and d.ui[-1]['args']['id'] == 'pr_end' and d.ui[-1]['args'].get('args') == {'on': True},
    (txt, d.ui[-1:]),
)
txt2, d2 = assistant('press_button', {'id': 'pr_tan', 'args': {'on': False}})
check(
    'and switching one off travels the same way',
    d2.ui[-1]['args']['id'] == 'pr_tan' and d2.ui[-1]['args'].get('args') == {'on': False},
    d2.ui[-1:],
)

import zyg_workflows.arch_assistant_ext.precision_snaps as PS  # noqa: E402

check('the prompt paragraph names all seven buttons', all(('"%s"' % i) in PS.PROMPT for i in IDS), PS.PROMPT[:200])
check(
    'the prompt paragraph reached the assistant (EXT_PROMPTS)',
    any('pr_perp' in p for p in A.EXT_PROMPTS),
    len(A.EXT_PROMPTS),
)

finish()
