# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_analyse_geometry.py — proof for the analyse_geometry
family: Clash (a_clash), Headroom (a_headroom), Guarding (a_guard) and Stair
rule (a_stair).

ONE FIXTURE, TWO LANGUAGES. The ten records below are built so every rule has
both a hit and a near miss that must NOT be a hit:

  o1 x o2  two walls crossing mid-length ............. the one clash
  o3 + o4  two walls meeting at a corner ............. excused, not a clash
  o5       a door in wall o1 ......................... an opening is never a clash
  o6       a slab at y 2.0 over a 2.7 m storey ....... 2.00 m headroom, under 2.3
  o7       a first-floor slab, top 2.92 .............. three unguarded edges
  o8       a 1.1 m wall on o7's north edge ........... that edge IS guarded
  o9       a railing with a 140 mm gap ............... fails the 100 mm sphere
  o10      a stair 16 x 0.175 / 0.28 ................. Blondel 0.63 ok, climbs 2.80

Expected findings: clash 1, headroom 1, guarding 8 (4 + 3 edges + 1 gap),
stair 1. The tab and the assistant must agree on all four, because the
arithmetic is written once in arch_ext/analyse_geometry.js and once in
arch_assistant_ext/analyse_geometry.py and nowhere else.

Two browser_eval calls: one presses all four icons and reads the registry, one
passes arguments the way the assistant does.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

ICONS = ['a_clash', 'a_headroom', 'a_guard', 'a_stair']


def rec(oid, kind, p, x, y, z, ry=0.0):
    return {
        'id': oid,
        'kind': kind,
        'name': kind,
        'p': p,
        'x': x,
        'y': y,
        'z': z,
        'rx': 0,
        'ry': ry,
        'rz': 0,
        's': 1,
        'mat': 'mat_concrete',
        'hidden': False,
        'grp': '',
    }


WALL = {'len': 6, 'h': 2.7, 't': 0.24}
DOC = {
    'objects': [
        rec('o1', 'wall', dict(WALL), 0, 0, 0),
        rec('o2', 'wall', dict(WALL), 0, 0, 0, math.pi / 2),
        rec('o3', 'wall', dict(WALL), 10, 0, 0),
        rec('o4', 'wall', dict(WALL), 13, 0, 3, math.pi / 2),
        rec('o5', 'door', {'w': 0.9, 'h': 2.1}, 1, 0, 0),
        rec('o6', 'slab', {'w': 4, 'd': 4, 't': 0.22}, 30, 2.0, 0),
        rec('o7', 'slab', {'w': 6, 'd': 6, 't': 0.22}, 60, 2.7, 0),
        rec('o8', 'wall', {'len': 6, 'h': 1.1, 't': 0.24}, 60, 2.92, -3),
        rec('o9', 'railing', {'len': 3, 'h': 1.0, 'posts': 5, 't': 0.04, 'gap': 0.14}, 80, 0, 0),
        rec('o10', 'stair_straight', {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0}, 100, 0, 0),
    ]
}
WANT = {'clash': 1, 'headroom': 1, 'guarding': 8, 'stair': 1}

# ── 1. the icons are no longer placeholders ─────────────────────────────────
st = icon_state(ICONS)
for i in ICONS:
    s = st.get(i) or {}
    check(
        '%s is a real icon in the dock: present, no stub flag, not dashed, no [placeholder] tip' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )
check(
    'all four sit in the Analyse section of the dock',
    all((st.get(i) or {}).get('section') == 'Analyse' for i in ICONS),
    {i: (st.get(i) or {}).get('section') for i in ICONS},
)

# ── 2. pressing all four in the live tab ────────────────────────────────────
JS1 = """() => {
  /* AR_EXT.analyses is SHARED: analyse_planning and analyse_performance push
     their own rules onto it too. Walk only the four this family registers. */
  const MINE = ['clash', 'headroom', 'guarding', 'stair'];
  const out = {undo0: AR.undo.length, objs0: AR.objs.length, presses: {}, direct: {}, reg: [], regAll: []};
  const A = {};
  AR_EXT.analyses.forEach(a => { out.regAll.push(a.id); if (MINE.indexOf(a.id) >= 0) A[a.id] = a; });
  MINE.forEach(id => { if (A[id]) out.reg.push(id); });
  MINE.forEach(id => { const r = A[id].run({}); out.direct[id] = {n: r.issues.length, ok: r.ok,
      rows: r.rows.length, ids: r.issues.map(i => i.ids.join('+')), sev: r.issues.map(i => i.severity),
      text: r.issues.map(i => i.text)}; });
  /* the registry's whole point: ANOTHER family's Code check runs our four */
  out.code = (typeof analyse_performance !== 'undefined' && analyse_performance.code)
    ? (function () {
        const c = analyse_performance.code({only: MINE});
        return {checks: c.checks.length,
                issues: c.checks.reduce((s, x) => s + x.issues.length, 0),
                errors: c.errors, warnings: c.warnings,
                broken: c.checks.filter(x => x.error).map(x => x.id + ': ' + x.error)};
      })()
    : null;
  for (const id of %s) {
    arTool(id);
    const sh = document.getElementById('ar-sheet');
    const body = sh ? sh.querySelector('.bd').innerHTML : '';
    out.presses[id] = {
      shown: !!(sh && sh.style.display === 'flex'),
      title: sh ? sh.querySelector('.hd span').textContent : '',
      rows: (body.match(/<tr>/g) || []).length,
      buttons: (body.match(/ANALYSE_GEOMETRY\\.pick\\(/g) || []).length,
      toast: document.getElementById('ar-toast').innerHTML,
      hl: ANALYSE_GEOMETRY._hl.length,
      hlInScene: ANALYSE_GEOMETRY._hl.filter(h => h.parent === AR.scene).length,
      stubLatch: AR.stubOn
    };
  }
  out.pick = (function () { arSelect([]); ANALYSE_GEOMETRY.pick(0); return AR.sel.slice(); })();
  out.hlBeforeClose = ANALYSE_GEOMETRY._hl.length;
  arSheetClose();
  out.hlAfterClose = ANALYSE_GEOMETRY._hl.length;
  out.undo1 = AR.undo.length; out.objs1 = AR.objs.length;
  out.doc = arDocOut().objects.length;
  return out;
}""" % json.dumps(ICONS)

r1 = browser_eval(JS1, doc=DOC)
v = r1['value']
check('no page errors while pressing all four icons', not r1['errors'], r1['errors'])
check(
    'the four rules are on the shared AR_EXT.analyses registry for Code check to walk',
    v['reg'] == ['clash', 'headroom', 'guarding', 'stair'],
    {'mine': v['reg'], 'whole_registry': v['regAll']},
)
check(
    "another family's Code check really runs all four through the registry, none of them broken",
    v['code'] is not None
    and v['code']['checks'] == 4
    and not v['code']['broken']
    and v['code']['issues'] == sum(WANT.values()),
    v['code'],
)
for key, want in WANT.items():
    check(
        'registry %s.run() finds exactly %d on the fixture' % (key, want),
        v['direct'][key]['n'] == want,
        v['direct'][key],
    )
check(
    'the clash is the crossing pair o1/o2 and nothing else',
    v['direct']['clash']['ids'] == ['o2+o1']
    and 'm3' not in v['direct']['clash']['text'][0]
    and '0.156' in v['direct']['clash']['text'][0],
    v['direct']['clash'],
)
check(
    'the corner joint o3/o4 and the door o5 are NOT reported as clashes',
    not any('o3' in s or 'o4' in s or 'o5' in s for s in v['direct']['clash']['ids']),
    v['direct']['clash']['ids'],
)
check(
    'headroom flags slab o6 at 2.00 m and skips the floor slab o7',
    v['direct']['headroom']['ids'] == ['o6'] and '2.00 m clear' in v['direct']['headroom']['text'][0],
    v['direct']['headroom'],
)
check(
    'guarding leaves o7 north edge alone (wall o8 guards it) and flags the other three',
    sum(1 for t in v['direct']['guarding']['text'] if 'Slab o7' in t) == 3
    and not any('o7 north' in t for t in v['direct']['guarding']['text']),
    v['direct']['guarding']['text'],
)
check(
    'the 140 mm railing gap is a warn, not an error',
    v['direct']['guarding']['sev'] == ['error'] * 7 + ['warn'],
    v['direct']['guarding']['sev'],
)
check(
    'the stair passes Blondel but is reported as 0.10 m over the storey',
    '2' not in v['direct']['stair']['text'][0].split('—')[0] and 'over by 0.10' in v['direct']['stair']['text'][0],
    v['direct']['stair'],
)

for i, key in zip(ICONS, ['clash', 'headroom', 'guarding', 'stair']):
    p = v['presses'][i]
    check('%s opens a sheet of findings with the numbers behind it' % i, p['shown'] and p['rows'] >= 5, p)
    check('%s gives every finding a select button' % i, p['buttons'] == WANT[key], p)
    check(
        '%s toasts the count and never latches the placeholder' % i,
        str(WANT[key]) in p['toast'] and p['stubLatch'] in (None, ''),
        p,
    )
check(
    'the sheet titles name the check',
    [v['presses'][i]['title'] for i in ICONS]
    == ['Clash detection', 'Headroom', 'Guarding and handrails', 'Stair rule'],
    [v['presses'][i]['title'] for i in ICONS],
)
check(
    'pressing draws red boxes round the offending records, in the scene',
    v['presses']['a_clash']['hl'] == 2 and v['presses']['a_clash']['hlInScene'] == 2 and v['hlBeforeClose'] == 1,
    {'clash': v['presses']['a_clash'], 'stair': v['hlBeforeClose']},
)
check('closing the sheet removes every highlight', v['hlAfterClose'] == 0, v)
check('the select button selects the records of its finding', v['pick'] == ['o10'], v['pick'])
check(
    'a read-only report pushes no undo step and adds no record',
    v['undo1'] == v['undo0'] and v['objs1'] == v['objs0'] == 10 and v['doc'] == 10,
    v,
)

# ── 3. the arguments the assistant passes ───────────────────────────────────
JS2 = """() => {
  const A = {}; AR_EXT.analyses.forEach(a => A[a.id] = a);
  arTool('a_headroom', {min: 2.0});
  const head20 = document.getElementById('ar-toast').innerHTML;
  arTool('a_guard', {min_h: 1.5, max_gap: 0.2});
  const guard15 = document.getElementById('ar-toast').innerHTML;
  arSelect(['o1']);
  return {
    head20: head20, guard15: guard15,
    head_2_0: A.headroom.run({min: 2.0}).issues.length,
    head_2_5: A.headroom.run({min: 2.5}).issues.length,
    guard_1_5: A.guarding.run({min_h: 1.5, max_gap: 0.2}).issues.length,
    /* the SAME drawing judged by a 200 mm sphere instead of a 100 mm one: o9's
       140 mm gap now passes, so the single 'warn' goes and the unguarded edges
       are all that is left. That isolates max_gap from the height rule. */
    gap_tight: (function () { const r = A.guarding.run({min_h: 1.0, max_gap: 0.1});
      return {n: r.issues.length, warns: r.issues.filter(i => i.severity === 'warn').length}; })(),
    gap_wide: (function () { const r = A.guarding.run({min_h: 1.0, max_gap: 0.2});
      return {n: r.issues.length, warns: r.issues.filter(i => i.severity === 'warn').length}; })(),
    stair_2_8: A.stair.run({storey_h: 2.8}).issues.length,
    clash_sel: A.clash.run({which: 'selection'}).issues.length,
    objs: AR.objs.length, undo: AR.undo.length
  };
}"""
r2 = browser_eval(JS2, doc=DOC)
w = r2['value']
check('no page errors while passing arguments', not r2['errors'], r2['errors'])
check('headroom at min 2.0 clears the 2.00 m slab, at 2.5 it still fails', w['head_2_0'] == 0 and w['head_2_5'] == 1, w)
check("a_headroom honours the assistant's min (2.0 -> passed)", 'passed' in w['head20'], w['head20'])
check('a taller guard requirement unguards o7 north as well (8 edges, no gap failure)', w['guard_1_5'] == 8, w)
check('a_guard honours min_h and max_gap from the assistant', '8 findings' in w['guard15'], w['guard15'])
check(
    'max_gap is a real dial: a 200 mm sphere clears the 140 mm railing, a 100 mm one does not',
    w['gap_tight'] == {'n': 8, 'warns': 1} and w['gap_wide'] == {'n': 7, 'warns': 0},
    {'tight': w['gap_tight'], 'wide': w['gap_wide']},
)
check('the stair lands exactly on a 2.8 m storey', w['stair_2_8'] == 0, w)
check('clash on the selection alone finds nothing (o1 has no partner in it)', w['clash_sel'] == 0, w)
check('the second pass still added nothing to the drawing', w['objs'] == 10, w)

# ── 4. the assistant twins agree, on the same fixture ───────────────────────
tx, d = assistant('clash_check', {'which': 'all'}, doc=DOC)
check(
    'clash_check reports the same single clash',
    tx.count('[error]') == 1 and 'o1' in tx and 'o2' in tx and 'pairs excused' in tx,
    tx,
)
check('clash_check changed nothing', len(d.objs) == 10 and not d.added, len(d.objs))
th, _ = assistant('headroom_check', {'min': 2.3}, doc=DOC)
check(
    'headroom_check reports the same single low ceiling',
    (th.count('[warn]') + th.count('[error]')) == 1 and '2.00 m clear' in th,
    th,
)
tg, _ = assistant('guarding_check', {'min_h': 1.0, 'max_gap': 0.1}, doc=DOC)
check(
    'guarding_check reports the same eight findings',
    (tg.count('[error]') + tg.count('[warn]')) == 8 and tg.count('[warn]') == 1,
    tg,
)
ts, _ = assistant('stair_check', {}, doc=DOC)
check(
    'stair_check reports the same single flight problem',
    (ts.count('[warn]') + ts.count('[error]')) == 1 and 'over by 0.10' in ts,
    ts,
)
check(
    'stair_check prints the numbers per flight, not just a verdict',
    '2R+G 0.630' in ts and 'climbs 2.80' in ts and 'every riser equal' in ts,
    ts,
)

td, _ = assistant('headroom_check', {}, doc=DOC)
check('headroom_check defaults to the Dutch 2.3 m new-build value', '2.3 m — the Dutch new-build value' in td, td)

# the twins and the tab quote the SAME counts — that is the whole point
py = {
    'clash': tx.count('[error]') + tx.count('[warn]'),
    'headroom': th.count('[error]') + th.count('[warn]'),
    'guarding': tg.count('[error]') + tg.count('[warn]'),
    'stair': ts.count('[error]') + ts.count('[warn]'),
}
js = {k: v['direct'][k]['n'] for k in py}
check('ONE ARITHMETIC: the Python twins and the tab agree on every count', py == js == WANT, (py, js))

# ── 5. the assistant may press the four icons ───────────────────────────────
for i in ICONS:
    txt, dd = assistant('press_button', {'id': i}, doc=DOC)
    check(
        'the assistant may press %s (declared in BUTTONS, assist:1 in the JS)' % i,
        txt.startswith('pressed') and dd.ui and dd.ui[-1]['args']['id'] == i,
        txt,
    )
tb, db = assistant('press_button', {'id': 'a_headroom', 'args': {'min': 2.0}}, doc=DOC)
check(
    "press_button carries the check's argument through to the tab", db.ui[-1]['args'].get('args') == {'min': 2.0}, db.ui
)

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
check(
    "the four tools are on the assistant's tool list",
    all(
        n in [t['name'] for t in A.TOOL_DEFS]
        for n in ('clash_check', 'headroom_check', 'guarding_check', 'stair_check')
    ),
    [t['name'] for t in A.TOOL_DEFS][-8:],
)
check(
    'the prompt paragraph explains all four checks',
    any(
        all(
            s in p
            for s in (
                'clash_check',
                'headroom_check',
                'guarding_check',
                'stair_check',
                'Blondel',
                '100 mm sphere',
                'never change the drawing',
            )
        )
        for p in A.EXT_PROMPTS
    ),
    [p[:80] for p in A.EXT_PROMPTS if 'clash_check' in p],
)

finish()
