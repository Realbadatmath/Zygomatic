# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_light_studies.py — proves the three sun icons are real.

The scene is the smallest thing that can tell a sun study from a toast: a 12 m
long, 8 m tall wall standing 2 m SOUTH of a 2 x 2 m slab (the studio's +Z is
south and the sun sits on that side all day, so the slab is overshadowed from
morning to evening), and an identical slab 40 m away in the open.

  l_solar     the map: the free slab's average direct-sun hours must beat the
              overshadowed one's, a vertex-coloured clone must exist for every
              record, the originals must be hidden while it is on, and pressing
              it again must put them back.
  l_study     the sweep: act() resolves with a PNG blob over 5 kB, the sheet
              shows it as an <img>, and the operator's sun hour comes back.
  a_sunhours  the report: a sheet table with a row and numbers for both slabs,
              and no paint left behind.

Two browser_eval calls in total (icon_state is one of them), so the whole file
stays well inside the board's 175 s.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state, tool_names  # noqa: E402

IDS = ['l_study', 'l_solar', 'a_sunhours']

# ── 1. the icons stopped being placeholders ─────────────────────────────────
st = icon_state(IDS)
check(
    'all three icons exist, with no stub flag, no dashed class and no [placeholder] tooltip',
    all(
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)
check(
    'l_study is in Light, l_solar is in Light, a_sunhours is in Analyse',
    st['l_study']['section'] == 'Light'
    and st['l_solar']['section'] == 'Light'
    and st['a_sunhours']['section'] == 'Analyse',
    {i: st[i].get('section') for i in IDS},
)

# ── 2. all three doing their job, in one page ───────────────────────────────
r = browser_eval("""() => {
  const T = AR_EXT.tools, out = {};
  /* +Z is south: a tall wall 2 m south of a low slab overshadows it all day */
  const wall   = arNewObj('wall', {len: 12, h: 8, t: 0.24}, 0,  2, 0);
  const shaded = arNewObj('slab', {w: 2, d: 2, t: 0.2},     0,  0, 0);
  const free   = arNewObj('slab', {w: 2, d: 2, t: 0.2},    40,  0, 0);
  const clones = () => AR.scene.children.filter(o => o.userData && o.userData.lsClone).length;
  const sun0 = AR.sunHour;
  out.ids = {wall: wall.id, shaded: shaded.id, free: free.id};
  /* the horizon test the sweep uses, measured on the studio's own sun */
  out.sunY = {};
  [0, 3, 8, 10, 12, 14, 16, 18].forEach(h => {
    arSunSet(h); out.sunY[h] = +AR.sun.position.clone().normalize().y.toFixed(4);
  });
  arSunSet(sun0);

  return T.l_solar.act({from: 8, to: 18, step: 2}).then(res => {
    const by = {}; (res.rows || []).forEach(x => by[x.id] = x);
    out.solar = {rows: res.rows, sun_hours: res.sun_hours, max: res.max, coarse: res.coarse};
    out.avgFree = (by[free.id] || {}).avg;
    out.avgShaded = (by[shaded.id] || {}).avg;
    out.maxFree = (by[free.id] || {}).max;
    out.onClones = clones();
    out.onVisible = [wall, shaded, free].map(o => o.node.visible);
    out.onLatched = !!T.l_solar.on();
    out.legend = !!(document.getElementById('ls-legend') || {}).innerHTML;
    out.ext = JSON.parse(JSON.stringify((AR.doc.ext || {}).light_studies || {}));
    out.mapSheet = document.querySelectorAll('#ar-sheet table tr').length;
    return T.l_solar.act();                       /* the switch, pressed again */
  }).then(() => {
    out.offClones = clones();
    out.offVisible = [wall, shaded, free].map(o => o.node.visible);
    out.offLatched = !!T.l_solar.on();
    out.offLegend = (document.getElementById('ls-legend') || {}).style.display;
    arZoomFit(false);
    return T.l_study.act({from: 8, to: 16, step: 4, res: 320});
  }).then(blob => {
    out.studyBytes = blob ? blob.size : 0;
    out.studyType = blob ? blob.type : '';
    const img = document.querySelector('#ar-sheet .bd img');
    out.studyImg = !!img;
    out.studyImgSrc = img ? img.src.slice(0, 15) : '';
    out.sunRestored = AR.sunHour === sun0;
    arSelect([]);
    return T.a_sunhours.act({which: 'all', from: 8, to: 18, step: 2});
  }).then(res => {
    out.report = {rows: res.rows, sun_hours: res.sun_hours};
    out.reportIds = res.rows.map(x => x.id);
    out.reportSheetRows = document.querySelectorAll('#ar-sheet table tr').length;
    out.reportSheetText = (document.querySelector('#ar-sheet .bd') || {}).textContent || '';
    out.reportClones = clones();
    out.repFree = (res.rows.find(x => x.id === free.id) || {}).avg;
    out.repShaded = (res.rows.find(x => x.id === shaded.id) || {}).avg;
    out.objs = AR.objs.length;
    /* a map asked for ONE record must paint that one and leave the rest of the
       drawing on screen, not blank the model */
    return T.l_solar.act({from: 10, to: 14, step: 2, ids: [free.id]});
  }).then(res => {
    out.subsetIds = (res.rows || []).map(x => x.id);
    out.subsetVisible = [wall, shaded, free].map(o => o.node.visible);
    return T.l_solar.act();
  }).then(() => {
    out.subsetOffVisible = [wall, shaded, free].map(o => o.node.visible);
    return out;
  });
}""")
v = r['value'] or {}
check('no page errors while the three icons ran', not r['errors'], r['errors'])

# l_solar --------------------------------------------------------------------
# Which of 8..18 count is a property of whatever solar model the studio has at the
# time (the built-in arc, or the light_sun family's NOAA sun once that is installed),
# so the expected set is MEASURED off the tab's own sun rather than written down here.
SUN_Y = v.get('sunY') or {}
UP = [h for h in (8, 10, 12, 14, 16, 18) if SUN_Y.get(str(h), -1) > 0.08]
check(
    "l_solar swept 8-18 and kept exactly the hours the tab's own sun puts above the horizon (%s)" % (UP,),
    bool(UP) and v.get('solar', {}).get('sun_hours') == UP and v['solar']['max'] == len(UP),
    {'solar': v.get('solar'), 'sunY': SUN_Y},
)
check(
    'l_solar measured per triangle, not per bounding box (under the 60k cap)',
    v.get('solar', {}).get('coarse') is False,
    v.get('solar'),
)
check(
    'the free slab gets more direct sun than the overshadowed one (%s h vs %s h)'
    % (v.get('avgFree'), v.get('avgShaded')),
    isinstance(v.get('avgFree'), (int, float))
    and isinstance(v.get('avgShaded'), (int, float))
    and v['avgFree'] > v['avgShaded'],
    {'free': v.get('avgFree'), 'shaded': v.get('avgShaded')},
)
check(
    'the free slab actually reaches the top of the sweep (max %s of %s h)'
    % (v.get('maxFree'), v.get('solar', {}).get('max')),
    v.get('maxFree') == v.get('solar', {}).get('max'),
    {'free': v.get('maxFree'), 'max': v.get('solar', {}).get('max')},
)
check(
    'the map built a vertex-coloured clone for every record and hid the originals',
    v.get('onClones', 0) >= 3 and v.get('onVisible') == [False, False, False],
    {'clones': v.get('onClones'), 'visible': v.get('onVisible')},
)
check(
    'the switch is latched on, with a legend and a per-record table',
    v.get('onLatched') and v.get('legend') and v.get('mapSheet', 0) >= 4,
    {'on': v.get('onLatched'), 'legend': v.get('legend'), 'rows': v.get('mapSheet')},
)
check(
    'the per-record hours are published on AR.doc.ext.light_studies.last',
    set((v.get('ext') or {}).get('last', {}).get('hours', {}).keys()) == set((v.get('ids') or {}).values()),
    v.get('ext'),
)
check(
    'pressing l_solar again removes every clone, unlatches and shows the model again',
    v.get('offClones') == 0
    and v.get('offVisible') == [True, True, True]
    and v.get('offLatched') is False
    and v.get('offLegend') == 'none',
    {
        'clones': v.get('offClones'),
        'visible': v.get('offVisible'),
        'on': v.get('offLatched'),
        'legend': v.get('offLegend'),
    },
)

# l_study --------------------------------------------------------------------
check(
    'l_study resolves with a real PNG contact sheet (%s bytes)' % (v.get('studyBytes'),),
    v.get('studyBytes', 0) > 5120 and v.get('studyType') == 'image/png',
    {'bytes': v.get('studyBytes'), 'type': v.get('studyType')},
)
check(
    'the contact sheet is opened in a sheet as an <img>',
    v.get('studyImg') and v.get('studyImgSrc', '').startswith('data:image/'),
    v.get('studyImgSrc'),
)
check("l_study put the operator's sun hour back after the sweep", v.get('sunRestored') is True, v.get('sunRestored'))

# a_sunhours -----------------------------------------------------------------
check(
    'a_sunhours reports every record of the drawing',
    sorted(v.get('reportIds') or []) == sorted((v.get('ids') or {}).values()),
    v.get('reportIds'),
)
check(
    'the report sheet has a row per record with numbers for both slabs',
    v.get('reportSheetRows', 0) >= 4
    and (v.get('ids') or {}).get('shaded', 'x') in v.get('reportSheetText', '')
    and (v.get('ids') or {}).get('free', 'x') in v.get('reportSheetText', '')
    and isinstance(v.get('repFree'), (int, float))
    and isinstance(v.get('repShaded'), (int, float)),
    {'rows': v.get('reportSheetRows'), 'free': v.get('repFree'), 'shaded': v.get('repShaded')},
)
check(
    'the report ranks them the same way the map did, and paints nothing',
    v.get('repFree') > v.get('repShaded') and v.get('reportClones') == 0,
    {'free': v.get('repFree'), 'shaded': v.get('repShaded'), 'clones': v.get('reportClones')},
)
check('nothing was added to or removed from the drawing by three read-only icons', v.get('objs') == 3, v.get('objs'))
check(
    'a map scoped to one record paints that record and leaves the rest of the model on screen',
    v.get('subsetIds') == [(v.get('ids') or {}).get('free')]
    and v.get('subsetVisible') == [True, True, False]
    and v.get('subsetOffVisible') == [True, True, True],
    {'ids': v.get('subsetIds'), 'on': v.get('subsetVisible'), 'off': v.get('subsetOffVisible')},
)

# ── 3. the assistant: the buttons and the server-side twin ──────────────────
DOC = {
    'objects': [
        {'id': 'w1', 'kind': 'wall', 'name': 'south wall', 'p': {'len': 12, 'h': 8, 't': 0.24}, 'x': 0, 'y': 0, 'z': 2},
        {'id': 's1', 'kind': 'slab', 'name': 'shaded slab', 'p': {'w': 2, 'd': 2, 't': 0.2}, 'x': 0, 'y': 0, 'z': 0},
        {'id': 's2', 'kind': 'slab', 'name': 'free slab', 'p': {'w': 2, 'd': 2, 't': 0.2}, 'x': 40, 'y': 0, 'z': 0},
    ]
}


def col(txt, rid, i=-3):
    for ln in txt.splitlines():
        p = ln.split()
        if p and p[0] == rid and len(p) >= 4:
            try:
                return float(p[i])
            except ValueError:
                return None
    return None


check('the assistant has the server-side twin sun_hours', 'sun_hours' in tool_names(), tool_names()[-6:])
txt, _d = assistant('sun_hours', {'which': 'all'}, doc=DOC)
check('sun_hours answers with a row for every record', all(col(txt, i) is not None for i in ('w1', 's1', 's2')), txt)
check(
    'the Python twin agrees on the ORDER: the free slab beats the overshadowed one (%s vs %s)'
    % (col(txt, 's2'), col(txt, 's1')),
    col(txt, 's2') > col(txt, 's1'),
    txt,
)
check('sun_hours states its coarseness in the answer', 'estimate:' in txt and 'bounding-box' in txt, txt[-220:])
txt2, _d2 = assistant('sun_hours', {'which': ['s1']}, doc=DOC)
check('sun_hours honours a chosen record set', col(txt2, 's1') is not None and col(txt2, 's2') is None, txt2)
txt3, _d3 = assistant('sun_hours', {'which': 'all'}, doc={'objects': []})
check('an empty drawing is refused, not invented', txt3.startswith('refused'), txt3)

for icon, args in (
    ('l_study', {'from': 8, 'to': 16, 'step': 4}),
    ('l_solar', {'from': 8, 'to': 18, 'step': 2}),
    ('a_sunhours', {'which': 'all'}),
):
    t, dd = assistant('press_button', {'id': icon, 'args': args})
    check(
        'the assistant may press %s and its args reach the tab' % icon,
        t.startswith('pressed') and dd.ui[-1]['args']['id'] == icon and dd.ui[-1]['args'].get('args') == args,
        (t, dd.ui[-1] if dd.ui else None),
    )

finish()
