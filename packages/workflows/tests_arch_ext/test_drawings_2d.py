# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_drawings_2d.py — proves the seven Drawings icons
(dc_plan, dc_elev, dc_sect, dc_scale, dc_dim, dc_hatch, dc_lw) are real: none
is a placeholder any more, and each one does what its tooltip promises on a
fixture building (a 6 x 4 room of four walls, a door, a window, a ground slab,
a first-floor slab, a straight stair and a column).

The fixture is placed so the room's OUTER faces sit exactly on x = 0..6 and
z = 0..4: the plan's overall dimensions are therefore exactly 6.00 x 4.00 m and
the paper size is arithmetic, not a guess.

Two headless-Chrome passes only: icon_state, then one batched browser_eval that
presses every icon and measures the SVGs it produced.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import assistant, browser_eval, check, finish, icon_state  # noqa: E402

IDS = ['dc_plan', 'dc_elev', 'dc_sect', 'dc_scale', 'dc_dim', 'dc_hatch', 'dc_lw']

W = {'h': 2.7, 't': 0.24}
DOC = {
    'objects': [
        {
            'id': 'o1',
            'kind': 'wall',
            'name': 'front',
            'p': dict(len=6, **W),
            'x': 3,
            'y': 0,
            'z': 0.12,
            'ry': 0,
            'mat': 'mat_brick',
        },
        {
            'id': 'o2',
            'kind': 'wall',
            'name': 'back',
            'p': dict(len=6, **W),
            'x': 3,
            'y': 0,
            'z': 3.88,
            'ry': 0,
            'mat': 'mat_brick',
        },
        {
            'id': 'o3',
            'kind': 'wall',
            'name': 'left',
            'p': dict(len=4, **W),
            'x': 0.12,
            'y': 0,
            'z': 2,
            'ry': math.pi / 2,
            'mat': 'mat_brick',
        },
        {
            'id': 'o4',
            'kind': 'wall',
            'name': 'right',
            'p': dict(len=4, **W),
            'x': 5.88,
            'y': 0,
            'z': 2,
            'ry': math.pi / 2,
            'mat': 'mat_brick',
        },
        {'id': 'o5', 'kind': 'door', 'name': 'door', 'p': {'w': 0.9, 'h': 2.1}, 'x': 1.5, 'y': 0, 'z': 0.12, 'ry': 0},
        {
            'id': 'o6',
            'kind': 'window',
            'name': 'window',
            'p': {'w': 1.2, 'h': 1.2, 'sill': 0.9},
            'x': 4.5,
            'y': 0,
            'z': 3.88,
            'ry': 0,
        },
        {
            'id': 'o7',
            'kind': 'slab',
            'name': 'floor',
            'p': {'w': 6, 'd': 4, 't': 0.2},
            'x': 3,
            'y': 0,
            'z': 2,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o8',
            'kind': 'slab',
            'name': 'first floor',
            'p': {'w': 6, 'd': 4, 't': 0.2},
            'x': 3,
            'y': 2.7,
            'z': 2,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o9',
            'kind': 'stair_straight',
            'name': 'stair',
            'p': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0},
            'x': 3,
            'y': 0,
            'z': 2,
            'mat': 'mat_concrete',
        },
        {
            'id': 'o10',
            'kind': 'column_rect',
            'name': 'column',
            'p': {'w': 0.3, 'd': 0.3, 'h': 2.7},
            'x': 4.8,
            'y': 0,
            'z': 1,
            'mat': 'mat_concrete',
        },
        # the annotation records of measure_annotations: a 3 m dimension, a right
        # angle and a note — a plan must draw them as they are, from their own
        # parameters (dim_linear p{x2, z2, off}, dim_angle p{x1, z1, x2, z2, r}).
        {
            'id': 'o11',
            'kind': 'dim_linear',
            'name': 'dim',
            'p': {'x2': 3, 'z2': 0, 'off': 0.4, 'txt': ''},
            'x': 1,
            'y': 0,
            'z': 2.5,
        },
        {
            'id': 'o12',
            'kind': 'dim_angle',
            'name': 'angle',
            'p': {'x1': 1, 'z1': 0, 'x2': 0, 'z2': -1, 'r': 0.8},
            'x': 2,
            'y': 0,
            'z': 3,
        },
        {
            'id': 'o13',
            'kind': 'label_text',
            'name': 'note',
            'p': {'txt': 'LIVING', 'size': 0.35},
            'x': 2,
            'y': 0,
            'z': 1.2,
        },
    ]
}

# ── 1. the icons are no longer placeholders ──────────────────────────────────
st = icon_state(IDS)
check(
    'all seven Drawings icons exist and are no longer placeholders '
    '(no stub flag, no dashed class, no [placeholder] tooltip)',
    all(
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)

# ── 2. one batched pass: press every icon on the fixture and measure ─────────
JS = r"""() => {
  const D = window.drawings2d, out = {};
  const dp = new DOMParser();
  const doc = (s) => dp.parseFromString(s, 'image/svg+xml');
  const sheetHtml = () => { const e = document.getElementById('ar-sheet'); return e ? e.innerHTML : ''; };
  const measure = (s) => {
    const x = doc(s), root = x.documentElement, err = x.getElementsByTagName('parsererror').length > 0;
    const vb = (root.getAttribute('viewBox') || '').split(/\s+/).map(Number);
    const cls = (c) => Array.from(x.querySelectorAll('polygon.' + c + ', path.' + c + ', polyline.' + c + ', circle.' + c));
    const cut = cls('cut');
    return {
      parsed: !err && root.nodeName === 'svg',
      vb_w: vb[2], vb_h: vb[3], width: root.getAttribute('width'),
      cut_shapes: x.querySelectorAll('polygon.cut, path.cut').length,
      cut_hatched: cut.filter(e => /d2hatch/.test(e.getAttribute('fill') || '')).length,
      cut_sw: cut.length ? cut[0].getAttribute('stroke-width') : null,
      patterns: x.querySelectorAll('pattern').length,
      dots: x.querySelectorAll('pattern circle').length,
      arcs: Array.from(x.querySelectorAll('path')).filter(e => /A/.test(e.getAttribute('d') || '')).length,
      door_arcs: Array.from(x.querySelectorAll('path[data-kind="door"]')).filter(e => /A/.test(e.getAttribute('d') || '')).length,
      windows: x.querySelectorAll('[data-kind="window"]').length,
      texts: Array.from(x.querySelectorAll('text')).map(e => e.textContent),
      north: x.querySelectorAll('[data-kind="north"]').length,
      treads: x.querySelectorAll('[data-kind="tread"]').length,
      levels: x.querySelectorAll('[data-kind="level"]').length,
      annos: {dim_linear: x.querySelectorAll('[data-kind="dim_linear"]').length,
              dim_angle: x.querySelectorAll('[data-kind="dim_angle"]').length,
              label_text: x.querySelectorAll('[data-kind="label_text"]').length},
      ground: x.querySelectorAll('[data-kind="ground"]').length,
      triangles: Array.from(x.querySelectorAll('path')).filter(e => /Z$/.test(e.getAttribute('d') || '')).length
    };
  };

  out.api = typeof D === 'object' && typeof D.svg === 'function' && typeof D.settings === 'function';
  const s0 = D.settings();
  out.defaults = {scale: s0.scale, hatch: s0.hatch, hatch_cut: s0.hatch_cut, cut_h: s0.cut_h, storey: s0.storey,
                  elev: s0.elev, lw: s0.lw, dim: s0.dim, section: s0.section};
  out.doc_ext = !!(AR.doc.ext && AR.doc.ext.drawings_2d);

  /* --- dc_plan (act returns the SVG string; the icon also opens a sheet) --- */
  const ret = AR_EXT.tools.dc_plan.act({storey: 0});
  out.plan_returns_svg = typeof ret === 'string' && ret.slice(0, 4) === '<svg';
  arSheetClose();
  arTool('dc_plan', {storey: 0});
  out.plan_sheet = /<svg/.test(sheetHtml()) && /Download SVG/.test(sheetHtml());
  out.plan = measure(D.last.svg);
  out.plan.title = D.last.title; out.plan.w_mm = D.last.w_mm; out.plan.h_mm = D.last.h_mm;
  out.plan.bounds = D.last.bounds;
  arSheetClose();

  /* --- dc_scale: 1:50 must double the paper --- */
  arTool('dc_scale', {scale: 50});
  out.scale_setting = D.settings().scale;
  out.plan50_vb_w = measure(D.svg('plan', {storey: 0}).svg).vb_w;
  arTool('dc_scale', {scale: 100});

  /* --- dc_dim: unit mm, no decimals --- */
  arTool('dc_dim', {text_mm: 3.5, arrow: 'arrow', unit: 'mm', decimals: 0});
  out.dim_setting = JSON.parse(JSON.stringify(D.settings().dim));
  out.plan_mm_texts = measure(D.svg('plan', {storey: 0}).svg).texts;
  arTool('dc_dim', {text_mm: 2.5, arrow: 'tick', unit: 'm', decimals: 2});

  /* --- dc_lw: a heavier cut pen --- */
  arTool('dc_lw', {cut: 0.7});
  out.lw_setting = JSON.parse(JSON.stringify(D.settings().lw));
  out.plan_lw = measure(D.svg('plan', {storey: 0}).svg).cut_sw;
  arTool('dc_lw', {cut: 0.5});

  /* --- dc_hatch: cycle, then explicit --- */
  const h0 = D.settings().hatch;
  arTool('dc_hatch');                      /* cycles ansi31 -> concrete */
  const h1 = D.settings().hatch;
  out.hatch_cycle = [h0, h1];
  out.plan_concrete_dots = measure(D.svg('plan', {storey: 0}).svg).dots;
  arTool('dc_hatch', {hatch: 'none'});
  out.hatch_none = D.settings().hatch;
  out.plan_none = measure(D.svg('plan', {storey: 0}).svg);
  arTool('dc_hatch', {hatch: 'ansi31'});
  out.hatch_back = D.settings().hatch;

  /* --- dc_elev --- */
  arTool('dc_elev', {elev: 'front'});
  out.elev_sheet = /<svg/.test(sheetHtml());
  out.elev = measure(D.last.svg);
  out.elev.title = D.last.title;
  arSheetClose();

  /* --- dc_sect at x = 3 --- */
  arTool('dc_sect', {dir: 'x', x: 3});
  out.sect_sheet = /<svg/.test(sheetHtml());
  out.sect = measure(D.last.svg);
  out.sect.title = D.last.title; out.sect.plane = D.last.plane;
  arSheetClose();

  /* --- the settings live with the document and survive a save --- */
  out.saved_ext = JSON.parse(JSON.stringify(arDocOut().ext.drawings_2d || {}));
  out.storey1_title = D.svg('plan', {storey: 1}).title;
  return out;
}"""

r = browser_eval(JS, doc=DOC)
v = r['value']
check('no page errors while pressing the seven icons', not r['errors'], r['errors'])
check('window.drawings2d exposes svg() and settings()', v['api'], v.get('api'))
d = v['defaults']
check(
    'settings default to the contract (1:100, ansi31, cut 1.2 m, pens .5/.25/.13/.13, tick/m/2 dp)',
    d['scale'] == 100
    and d['hatch'] == 'ansi31'
    and d['hatch_cut'] is True
    and d['cut_h'] == 1.2
    and d['storey'] == 0
    and d['elev'] == 'front'
    and d['lw'] == {'cut': 0.5, 'proj': 0.25, 'hidden': 0.13, 'thin': 0.13}
    and d['dim'] == {'text_mm': 2.5, 'arrow': 'tick', 'unit': 'm', 'decimals': 2}
    and d['section'] == {'x': None, 'z': None, 'dir': 'x'},
    d,
)
check(
    'the settings live in AR.doc.ext.drawings_2d and go out with the document',
    v['doc_ext'] and v['saved_ext'].get('scale') == 100,
    v['saved_ext'],
)

p = v['plan']
check(
    'dc_plan: act() returns the SVG string and the icon opens a sheet with a Download SVG button',
    v['plan_returns_svg'] and v['plan_sheet'],
    [v['plan_returns_svg'], v['plan_sheet']],
)
check(
    'dc_plan: the SVG parses and is titled for the storey and the scale',
    p['parsed'] and p['title'] == 'Plan \u2014 storey 0 \u2014 1:100',
    p['title'],
)
check(
    'dc_plan: at least four cut shapes (wall piers + the column), every one hatched',
    p['cut_shapes'] >= 4 and p['cut_hatched'] >= 4 and p['patterns'] == 1,
    {'cut': p['cut_shapes'], 'hatched': p['cut_hatched'], 'patterns': p['patterns']},
)
check('dc_plan: the door is drawn as a swing arc (a path with an A command)', p['door_arcs'] >= 1, p['door_arcs'])
check('dc_plan: the window is drawn as three thin lines across the wall', p['windows'] == 3, p['windows'])
check(
    'dc_plan: the stair shows its treads and the plan has a north arrow',
    p['treads'] >= 10 and p['north'] == 1,
    {'treads': p['treads'], 'north': p['north']},
)
check(
    'dc_plan: the overall extents are dimensioned 6.00 x 4.00 m',
    '6.00' in p['texts'] and '4.00' in p['texts'],
    p['texts'],
)
check(
    'dc_plan: the annotation records are drawn as they are — the 3 m dimension with its extension lines, '
    'the 90 degree angle with its arc and the label with its own text',
    p['annos']['dim_linear'] >= 3
    and p['annos']['dim_angle'] >= 3
    and p['annos']['label_text'] >= 2
    and '3 m' in p['texts']
    and '90\u00b0' in p['texts']
    and 'LIVING' in p['texts'],
    {'annos': p['annos'], 'texts': p['texts']},
)
check(
    'dc_plan: the model bounds really are 6 x 4 m',
    abs(p['bounds']['maxx'] - p['bounds']['minx'] - 6) < 0.01
    and abs(p['bounds']['maxy'] - p['bounds']['miny'] - 4) < 0.01,
    p['bounds'],
)
check(
    'dc_plan: at 1:100 the sheet is (6+4) x (4+4) m of paper = 100 x 80 mm',
    abs(p['vb_w'] - 100) < 0.01 and abs(p['vb_h'] - 80) < 0.01 and p['width'] == '100mm',
    [p['vb_w'], p['vb_h'], p['width']],
)

check(
    'dc_scale: 1:50 is stored and doubles the paper width to 200 mm',
    v['scale_setting'] == 50 and abs(v['plan50_vb_w'] - 200) < 0.02,
    [v['scale_setting'], v['plan50_vb_w']],
)

check(
    'dc_dim: the style is stored (3.5 mm text, arrowheads, mm, 0 dp)',
    v['dim_setting'] == {'text_mm': 3.5, 'arrow': 'arrow', 'unit': 'mm', 'decimals': 0},
    v['dim_setting'],
)
check(
    'dc_dim: in millimetres the same dimension reads 6000 and 4000',
    '6000' in v['plan_mm_texts'] and '4000' in v['plan_mm_texts'],
    v['plan_mm_texts'],
)

check(
    'dc_lw: a 0.7 mm cut pen is stored and becomes the cut stroke-width',
    v['lw_setting']['cut'] == 0.7 and abs(float(v['plan_lw']) - 0.7) < 1e-9,
    [v['lw_setting'], v['plan_lw']],
)

check(
    'dc_hatch: a bare press cycles ansi31 -> concrete, and concrete adds the dots',
    v['hatch_cycle'] == ['ansi31', 'concrete'] and v['plan_concrete_dots'] >= 1,
    [v['hatch_cycle'], v['plan_concrete_dots']],
)
check(
    "dc_hatch: 'none' removes the pattern and leaves the cut shapes unfilled, and it can be set back",
    v['hatch_none'] == 'none'
    and v['plan_none']['patterns'] == 0
    and v['plan_none']['cut_hatched'] == 0
    and v['plan_none']['cut_shapes'] >= 4
    and v['hatch_back'] == 'ansi31',
    [v['hatch_none'], v['plan_none']['patterns'], v['plan_none']['cut_shapes'], v['hatch_back']],
)

e = v['elev']
check(
    'dc_elev: a front elevation parses, opens a sheet and is titled',
    e['parsed'] and v['elev_sheet'] and e['title'] == 'Elevation \u2014 front \u2014 1:100',
    e['title'],
)
check(
    'dc_elev: the storey height 2.70 is dimensioned and the levels and the ground line are drawn',
    '2.70' in e['texts'] and '+2.70' in e['texts'] and e['levels'] >= 2 and e['ground'] == 1,
    {'texts': e['texts'][:12], 'levels': e['levels'], 'ground': e['ground']},
)
check('dc_elev: the window shows as its rectangle', e['windows'] >= 1, e['windows'])

sc = v['sect']
check(
    'dc_sect: a section at x = 3 parses, opens a sheet and names its plane',
    sc['parsed']
    and v['sect_sheet']
    and sc['plane'] == {'dir': 'x', 'at': 3}
    and sc['title'] == 'Section \u2014 x = 3.00 \u2014 1:100',
    [sc['title'], sc.get('plane')],
)
check(
    'dc_sect: the two walls and the two slabs it crosses are cut and hatched',
    sc['cut_shapes'] >= 4 and sc['cut_hatched'] >= 4,
    {'cut': sc['cut_shapes'], 'hatched': sc['cut_hatched']},
)
check(
    'dc_sect: the section carries level lines and storey dimensions',
    sc['levels'] >= 2 and '2.70' in sc['texts'],
    {'levels': sc['levels'], 'texts': sc['texts'][:12]},
)

check(
    'a plan of storey 1 is a different drawing',
    v['storey1_title'] == 'Plan \u2014 storey 1 \u2014 1:100',
    v['storey1_title'],
)

# ── 3. the assistant twins ───────────────────────────────────────────────────
from zyg_workflows import arch_assistant as A  # noqa: E402

check(
    'the assistant gained the drawing tools',
    {'drawing', 'drawing_settings'} <= {t['name'] for t in A.TOOL_DEFS},
    sorted(t['name'] for t in A.TOOL_DEFS)[:8],
)
check('all seven icons are declared pressable by the model', set(IDS) <= A.EXT_BUTTONS, sorted(A.EXT_BUTTONS)[:12])

txt, dr = assistant('drawing', {'kind': 'plan', 'storey': 1})
check(
    'drawing(plan) presses dc_plan in the tab with the storey as an argument',
    txt.startswith('requested') and dr.ui[-1] == {'cmd': 'tool', 'args': {'id': 'dc_plan', 'args': {'storey': 1}}},
    [txt, dr.ui],
)
txt, dr = assistant('drawing', {'kind': 'elevation', 'elev': 'left'}, drawing=dr)
check(
    'drawing(elevation) presses dc_elev with the side',
    dr.ui[-1]['args'] == {'id': 'dc_elev', 'args': {'elev': 'left'}},
    dr.ui[-1],
)
txt, dr = assistant('drawing', {'kind': 'section', 'axis': 'x', 'x': 3}, drawing=dr)
check(
    'drawing(section) presses dc_sect with the plane',
    dr.ui[-1]['args'] == {'id': 'dc_sect', 'args': {'dir': 'x', 'x': 3.0}},
    dr.ui[-1],
)
txt, _ = assistant('drawing', {'kind': 'axonometric'}, drawing=dr)
check('an unknown drawing kind is refused', txt.startswith('refused'), txt)

txt, dr2 = assistant('drawing_settings', {'scale': 50, 'hatch': 'concrete', 'unit': 'mm', 'decimals': 0, 'cut': 0.7})
s = dr2.ext['drawings_2d']
check(
    'drawing_settings writes AR.doc.ext.drawings_2d and it round-trips through the document',
    s['scale'] == 50
    and s['hatch'] == 'concrete'
    and s['dim']['unit'] == 'mm'
    and s['dim']['decimals'] == 0
    and s['lw']['cut'] == 0.7
    and dr2.to_doc()['ext']['drawings_2d']['scale'] == 50,
    [txt, s],
)
txt, dr2 = assistant('drawing_settings', {'section_axis': 'z', 'section_z': 2.5}, drawing=dr2)
check(
    'drawing_settings sets the default section plane',
    dr2.ext['drawings_2d']['section'] == {'x': None, 'z': 2.5, 'dir': 'z'},
    dr2.ext['drawings_2d']['section'],
)
txt, _ = assistant('drawing_settings', {}, drawing=dr2)
check(
    'drawing_settings with no arguments reads the settings back',
    '1:50' in txt and 'concrete' in txt and 'section along z at 2.50 m' in txt,
    txt,
)
txt, _ = assistant('drawing_settings', {'hatch': 'tartan'})
check('an unknown hatch is refused', txt.startswith('refused'), txt)
txt, _ = assistant('press_button', {'id': 'dc_hatch', 'args': {'hatch': 'none'}})
check('the model may press dc_hatch with arguments', txt.startswith('pressed'), txt)

finish()
