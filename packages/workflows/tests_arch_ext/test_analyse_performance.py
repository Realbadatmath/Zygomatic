# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_analyse_performance.py — proof for the analyse_performance
family: Analyse ▸ Daylight, Energy, U-value, Structure, Code check.

Five icons (a_daylight, a_energy, a_uvalue, a_struct, a_code) that were
placeholders. Each is proved twice: the live tab (the icon is no longer a stub,
pressing it opens a sheet with the numbers the tooltip promises) and the
assistant's Python twin (the same arithmetic, as text).

The fixture is the one the brief names: a 6 x 4 m room of four centre-line walls
with ONE 1.2 x 1.4 m window, plus an 8 m timber beam 0.3 m deep. Hand
computation, same formula, centre-line room:

    Aw     = 1.2 * 1.4 * 0.8 (frame)                    = 1.344 m2
    Atotal = 2 * 24 (floor + ceiling) + 20 * 2.7 (walls) = 102.0 m2
    DF %   = (1.344 * 65 * 0.7) / (102 * (1 - 0.5^2))    = 0.799 %

The tab may resolve the room through window.analyse_planning.rooms() instead of
its own loop finder (inner faces rather than centre lines), which moves DF by
about 0.06 % — inside the +/- 0.5 % the brief allows, and the test says which
source was used.

Budget: exactly 2 browser_eval calls (icon_state is one of them).
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import assistant, browser_eval, check, finish, icon_state  # noqa: E402

import zyg_workflows.arch_assistant_ext.analyse_performance as AP  # noqa: E402

ICONS = ['a_daylight', 'a_energy', 'a_uvalue', 'a_struct', 'a_code']
H = 2.7

# ── the fixture ──────────────────────────────────────────────────────────────
HAND_DF = (1.2 * 1.4 * 0.8 * 65.0 * 0.7) / ((2 * 24.0 + 20.0 * H) * (1 - 0.5**2))


def _wall(i, x, z, ln, ry):
    return {
        'id': i,
        'kind': 'wall',
        'name': 'w',
        'p': {'len': ln, 'h': H, 't': 0.24},
        'x': x,
        'y': 0,
        'z': z,
        'ry': ry,
        'mat': 'mat_concrete',
    }


FIXTURE = [
    _wall('w1', 0, -2, 6, 0),
    _wall('w2', 0, 2, 6, 0),
    _wall('w3', -3, 0, 4, math.pi / 2),
    _wall('w4', 3, 0, 4, math.pi / 2),
    {
        'id': 'win1',
        'kind': 'window',
        'name': 'window',
        'p': {'w': 1.2, 'h': 1.4, 'sill': 0.9},
        'x': 0,
        'y': 0,
        'z': -2,
        'ry': 0,
        'mat': 'mat_glass',
    },
    {
        'id': 'b1',
        'kind': 'beam',
        'name': 'beam',
        'p': {'len': 8, 'h': 0.3, 'w': 0.2},
        'x': 0,
        'y': 2.7,
        'z': 0,
        'ry': 0,
        'mat': 'mat_timber',
    },
]
THICK = [
    {'name': 'plaster', 'd': 0.012, 'lambda': 0.51},
    {'name': 'insulation (mineral wool)', 'd': 0.20, 'lambda': 0.035},
    {'name': 'concrete', 'd': 0.24, 'lambda': 2.0},
]

# ── 1. the icons are real (browser_eval #1) ──────────────────────────────────
st = icon_state(ICONS)
check(
    'all five icons exist in the Analyse dock section',
    all(st[i].get('exists') and st[i].get('section') == 'Analyse' for i in ICONS),
    st,
)
check(
    'none is a placeholder any more (stub false, dashed false, tip_placeholder false)',
    all(not st[i].get('stub') and not st[i].get('dashed') and not st[i].get('tip_placeholder') for i in ICONS),
    st,
)

# ── 2. every icon DOES its job in the live tab (browser_eval #2) ─────────────
JS = """() => {
  const sheet = () => document.getElementById('ar-sheet');
  const title = () => { const e = sheet(); return (e && e.style.display !== 'none')
    ? e.querySelector('.hd span').textContent : ''; };
  const body  = () => { const e = sheet(); return e ? e.querySelector('.bd').innerHTML : ''; };
  const rows  = () => { const e = sheet(); return e ? e.querySelectorAll('.bd table tr').length : 0; };
  const out = {errors: []};
  AR.doc.ext = {};
  const undo0 = AR.undo ? AR.undo.length : null;

  /* the registry every analysis family writes to */
  out.registry = (AR_EXT.analyses || []).map(e => e.id);
  out.hasPlanning = !!(window.analyse_planning && typeof window.analyse_planning.rooms === 'function');

  /* --- a_daylight: sheet + numbers + the floor overlay --- */
  arTool('a_daylight', {target: 2.0});
  const dl = analyse_performance.daylight({target: 2.0});
  out.dl = {title: title(), rows: rows(), source: dl.source, n: dl.rows.length,
            df: dl.rows.length ? dl.rows[0].df : null, Aw: dl.rows.length ? dl.rows[0].Aw : null,
            theta: dl.rows.length ? dl.rows[0].theta : null,
            area: dl.rows.length ? dl.rows[0].room.area : null,
            target: dl.rows.length ? dl.rows[0].target : null,
            issues: dl.issues.length, issue0: dl.issues.length ? dl.issues[0].text : '',
            overlay: (analyse_performance._overlay || []).length,
            inScene: AR.scene.children.filter(m => m.userData && m.userData.apOverlay).length};
  arSheetClose();
  out.dl.overlayAfterClose = (analyse_performance._overlay || []).length;

  /* the default target really is 2 % living / 1 % other */
  out.dlDefault = analyse_performance.daylight({}).rows.map(r => r.target);

  /* --- a_energy --- */
  arTool('a_energy');
  const en = analyse_performance.energy({});
  out.en = {title: title(), rows: rows(), H: en.H, HA: en.HA, Hv: en.Hv, kwh: en.kwh,
            wallGross: en.wallGross, wallNet: en.wallNet, glass: en.glass,
            ratio: en.glazingRatio, volume: en.volume, dd: en.degree_days,
            orient: Object.keys(en.orient).map(k => [k, en.orient[k].wall, en.orient[k].glass]),
            parts: en.parts.map(p => [p.what, p.area, p.u, p.h]),
            issues: en.issues.map(i => i.text),
            hasRatioInSheet: /Glazing ratio, whole envelope/.test(body())
                          && /Glazing ratio by orientation/.test(body()),
            hasAssumptions: /Assumptions:/.test(body())};

  /* --- a_uvalue: default table, then the assistant's args edit a build-up --- */
  arTool('a_uvalue');
  const u0 = analyse_performance.uvalues({}).constructions;
  out.u0 = {title: title(), rows: rows(), wall: u0.mat_concrete.u, roof: u0.roof.u,
            floor: u0.floor.u, glass: u0.mat_glass.u, n: Object.keys(u0).length,
            edited: u0.mat_concrete.edited, inputs: sheet().querySelectorAll('.bd input.ap-in').length};
  arTool('a_uvalue', {set: {mat_concrete: {layers: __THICK__}}});
  const u1 = analyse_performance.uvalues({}).constructions;
  out.u1 = {wall: u1.mat_concrete.u, edited: u1.mat_concrete.edited,
            ext: !!(AR.doc.ext.analyse_performance || {}).constructions,
            extD: (((AR.doc.ext.analyse_performance || {}).constructions || {}).mat_concrete || {}).layers};
  /* a human editing one input field writes through the same seam */
  analyse_performance.setLayer('mat_concrete', 1, 'd', 0.30);
  out.u2 = {wall: analyse_performance.uvalues({}).constructions.mat_concrete.u,
            pushed: AR.undo ? AR.undo.length > undo0 : null};

  /* --- a_struct --- */
  arTool('a_struct');
  const sc = analyse_performance.structure();
  out.st = {title: title(), rows: rows(), members: sc.rows, issues: sc.issues.map(i => [i.severity, i.text, i.ids])};

  /* --- a_code: runs EVERY registered analysis, offers JSON + select --- */
  arSelect([]);
  arTool('a_code');
  const cd = analyse_performance.lastCode;
  out.cd = {title: title(),
            sections: cd.checks.map(c => [c.id, c.family, c.issues.length, c.error]),
            summary: cd.summary, errors: cd.errors, warnings: cd.warnings,
            offenders: cd.offenders, jsonLen: (analyse_performance.lastCodeJson || '').length,
            hasSelectBtn: /selectOffenders/.test(body()), hasDownloadBtn: /downloadCode/.test(body())};
  try { out.cdJson = JSON.parse(analyse_performance.lastCodeJson).checks.length; }
  catch (e) { out.errors.push('json ' + e.message); }
  analyse_performance.selectOffenders();
  out.cd.selected = AR.sel.slice();
  /* a foreign entry that throws must not stop the sweep */
  AR_EXT.analyses.push({id: 'ap_boom', name: 'Exploding check', family: 'test',
                        run: () => { throw new Error('boom'); }});
  const cd2 = analyse_performance.code({});
  out.cd2 = {n: cd2.checks.length, boom: (cd2.checks.filter(c => c.id === 'ap_boom')[0] || {}).error};
  const cd3 = analyse_performance.code({only: ['a_daylight']});
  out.cd3 = cd3.checks.map(c => c.id);
  AR_EXT.analyses.pop();
  return out;
}""".replace('__THICK__', json.dumps(THICK))

r = browser_eval(JS, doc={'objects': FIXTURE, 'ext': {}})
v = r['value']
check('no page errors while pressing the five icons', not r['errors'] and not v['errors'], (r['errors'], v['errors']))

check(
    'the four analyses register themselves on AR_EXT.analyses',
    all(i in v['registry'] for i in ICONS[:4]),
    v['registry'],
)

d = v['dl']
check(
    'a_daylight opens a Daylight sheet with a row per room',
    d['title'] == 'Daylight factor' and d['rows'] >= 2 and d['n'] == 1,
    d,
)
check(
    'tab DF %.3f is within 0.5 of the hand computation %.3f (rooms from %s)' % (d['df'] or -1, HAND_DF, d['source']),
    abs((d['df'] or -99) - HAND_DF) < 0.5,
    d,
)
check(
    'the BRE terms are the ones the formula names (Aw = w*h*0.8, theta = 65 with no obstruction)',
    abs(d['Aw'] - 1.344) < 1e-6 and abs(d['theta'] - 65.0) < 1e-6,
    d,
)
check(
    'the room is flagged against the 2 % target it was given, citing BRE 209',
    d['target'] == 2.0 and d['issues'] == 1 and 'BRE 209' in d['issue0'],
    d,
)
check('without a target the BRE defaults apply (1 % for a non-living room)', v['dlDefault'] == [1.0], v['dlDefault'])
check(
    'the sheet paints a translucent floor overlay, and closing it removes the overlay',
    d['overlay'] == 1 and d['inScene'] == 1 and d['overlayAfterClose'] == 0,
    d,
)

e = v['en']
check(
    'a_energy opens an Energy sheet showing the glazing ratio (overall and per orientation) and its assumptions',
    e['title'].startswith('Energy') and e['rows'] >= 3 and e['hasRatioInSheet'] and e['hasAssumptions'],
    e,
)
check(
    'the heated envelope is the 4 exterior walls: gross %.1f m2, glass %.2f m2, ratio %.1f %%'
    % (e['wallGross'], e['glass'], 100 * e['ratio']),
    abs(e['wallGross'] - 54.0) < 0.5 and abs(e['glass'] - 1.68) < 1e-6 and abs(e['ratio'] - 1.68 / 54.0) < 0.01,
    e,
)
check(
    'H = sum U.A + ventilation is positive and split into fabric + ventilation (H %.2f = %.2f + %.2f W/K)'
    % (e['H'], e['HA'], e['Hv']),
    e['H'] > 0 and e['HA'] > 0 and e['Hv'] > 0 and abs(e['H'] - e['HA'] - e['Hv']) < 1e-6,
    e,
)
check(
    'the annual estimate is H x 24 x 2800 / 1000 kWh',
    e['dd'] == 2800 and abs(e['kwh'] - e['H'] * 24 * 2800 / 1000) < 1e-6,
    e,
)
check('a facade under 10 %% glazing is flagged per orientation', any('below 10' in t for t in e['issues']), e['issues'])

u0, u1, u2 = v['u0'], v['u1'], v['u2']
check(
    'a_uvalue opens a construction table with editable layer inputs',
    u0['title'].startswith('U-value') and u0['inputs'] >= 6 and u0['n'] >= 6,
    u0,
)
check('the default wall U = %.4f is 0.26 +/- 0.03 W/m2K' % u0['wall'], abs(u0['wall'] - 0.26) <= 0.03, u0)
check(
    'the NL limits bite: roof %.3f, floor %.3f, glass %.3f' % (u0['roof'], u0['floor'], u0['glass']),
    u0['roof'] < 0.16 and u0['floor'] < 0.21 and abs(u0['glass'] - 1.1) < 0.05,
    u0,
)
check(
    'thickening the insulation to 0.20 m lowers U (%.4f -> %.4f) and stores it in AR.doc.ext'
    % (u0['wall'], u1['wall']),
    u1['wall'] < u0['wall'] - 0.05 and u1['edited'] and u1['ext'] and len(u1['extD']) == 3,
    u1,
)
check(
    'an inline layer edit (setLayer 0.30 m) lowers U again (%.4f) behind one arPush' % u2['wall'],
    u2['wall'] < u1['wall'] and u2['pushed'] is not False,
    u2,
)

s = v['st']
check(
    'a_struct opens a Structure sheet listing the members',
    s['title'] == 'Structure' and s['rows'] >= 1 and len(s['members']) == 1,
    s,
)
check(
    'the 8 m timber beam 0.3 m deep is flagged: span/depth 26.7 > 20',
    len(s['issues']) == 1
    and s['issues'][0][2] == ['b1']
    and '26.7' in s['issues'][0][1]
    and '20 rule of thumb' in s['issues'][0][1],
    s['issues'],
)

c = v['cd']
check(
    'a_code opens one sheet with a section per registered analysis (%d sections)' % len(c['sections']),
    c['title'] == 'Code check'
    and len(c['sections']) >= 4
    and all(i in [x[0] for x in c['sections']] for i in ICONS[:4]),
    c['sections'],
)
check(
    'every section ran without error and the summary counts them',
    not any(x[3] for x in c['sections'])
    and c['summary'] == '%d errors, %d warnings across %d checks' % (c['errors'], c['warnings'], len(c['sections'])),
    c,
)
check(
    'the sheet offers select-all-offenders and a JSON download, and the blob parses',
    c['hasSelectBtn'] and c['hasDownloadBtn'] and c['jsonLen'] > 200 and v['cdJson'] == len(c['sections']),
    c,
)
check(
    'select all offenders selects the objects the checks named',
    c['offenders'] and sorted(c['selected']) == sorted(c['offenders']),
    c,
)
check(
    'an analysis that throws is reported in its own section and the sweep continues',
    v['cd2']['n'] == len(c['sections']) + 1 and 'boom' in (v['cd2']['boom'] or ''),
    v['cd2'],
)
check('opt.only narrows the sweep to the ids asked for', v['cd3'] == ['a_daylight'], v['cd3'])

# ── 3. the assistant's Python twins: the same arithmetic, as text ────────────
doc = {'objects': FIXTURE, 'ext': {}}
txt, dr = assistant('daylight_check', {'target': 2.0}, doc=dict(doc))
pdf = AP.daylight(dr, 2.0)['rows'][0]['df']
check(
    'daylight_check returns the same DF %.3f as the hand computation %.3f (+/- 0.5)' % (pdf, HAND_DF),
    abs(pdf - HAND_DF) < 0.5 and 'DF %.2f' % pdf in txt and 'BRE 209' in txt,
    txt[:300],
)
check(
    'the Python twin agrees with the tab DF %.3f within 0.5' % (d['df'] or -1),
    abs(pdf - (d['df'] or -99)) < 0.5,
    (pdf, d['df']),
)

txt, dr = assistant('energy_summary', {}, doc=dict(doc))
pen = AP.energy(dr)
check(
    'energy_summary prints the glazing ratio and a positive H',
    'glazing ratio' in txt and pen['H'] > 0 and 'H total' in txt and abs(pen['H'] - e['H']) < 0.5,
    txt[:300],
)

txt, dr = assistant('u_values', {}, doc=dict(doc))
pu = AP.uvalues(dr)['constructions']['mat_concrete']['u']
check(
    'u_values gives the same default wall U %.4f as the tab and cites Bouwbesluit 2021' % pu,
    abs(pu - u0['wall']) < 1e-6 and 'Bouwbesluit 2021' in txt,
    txt[:300],
)
edited = AP.uvalues(
    type(dr)(
        {'objects': FIXTURE, 'ext': {'analyse_performance': {'constructions': {'mat_concrete': {'layers': THICK}}}}}
    )
)
check(
    'the Python twin reads an edited build-up from doc.ext too (%.4f)' % edited['constructions']['mat_concrete']['u'],
    abs(edited['constructions']['mat_concrete']['u'] - u1['wall']) < 1e-6,
    edited['constructions']['mat_concrete'],
)

txt, dr = assistant('structure_check', {}, doc=dict(doc))
check(
    'structure_check flags the same beam, as a rule of thumb',
    'b1' in txt and '26.7' in txt and 'rules of thumb' in txt,
    txt[:300],
)

txt, dr = assistant('code_check', {}, doc=dict(doc))
pc = AP.code(dr)
check(
    'code_check runs at least our own four analyses in one report (%d)' % len(pc['checks']),
    len(pc['checks']) >= 4
    and all(i in [x['id'] for x in pc['checks']] for i in ICONS[:4])
    and not any(x['error'] for x in pc['checks']),
    [x['id'] for x in pc['checks']],
)
check(
    'code_check accounts for every sibling family: contributed / imported-but-silent / not installed',
    'contributed a check' in txt
    and 'registering no server-side analysis' in txt
    and 'not installed' in txt
    and set(pc['available']) | set(pc['silent']) | set(pc['missing']) == set(AP.SIBLINGS)
    and not (set(pc['available']) & set(pc['silent'])),
    (pc['available'], pc['silent'], pc['missing']),
)
check(
    'code_check honours only=[ids]', [x['id'] for x in AP.code(dr, ['a_struct'])['checks']] == ['a_struct'], txt[:200]
)

check('the assistant may press all five icons (BUTTONS + assist:1)', AP.BUTTONS == ICONS, AP.BUTTONS)
for _id in ICONS:
    t, dd_ = assistant('press_button', {'id': _id, 'args': {}})
    if not check(
        'press_button("%s") reaches the tab' % _id, t.startswith('pressed') and dd_.ui[-1]['args']['id'] == _id, t
    ):
        break
check(
    'the prompt paragraph says what each button takes',
    all(i in AP.PROMPT for i in ICONS) and 'target' in AP.PROMPT and 'only' in AP.PROMPT,
    AP.PROMPT[:200],
)

finish()
