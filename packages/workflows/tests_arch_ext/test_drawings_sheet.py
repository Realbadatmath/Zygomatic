# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_drawings_sheet.py — proves the five sheet icons
(dc_sheet, dc_title, dc_rev, dc_pdf, dc_print) are real: none is a placeholder
any more, and each one does what its tooltip promises on the same 6 x 4 m room
that drawings_2d's test uses (built inline here).

Two headless-Chrome passes only: icon_state, then ONE batched browser_eval that
fills the title block, adds a revision, composes an A3 sheet, exports the PDF
through the server extension and runs both print paths. The composed
PDF-ready page comes back out of that pass so the server route can be proved
over plain HTTP without a third browser.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import assistant, browser_eval, check, finish, icon_state, server_ext  # noqa: E402

IDS = ['dc_sheet', 'dc_title', 'dc_rev', 'dc_pdf', 'dc_print']

# the fixture: a 6 x 4 m room whose OUTER faces sit on x = 0..6 and z = 0..4,
# so the plan is exactly 6.00 x 4.00 m and the paper arithmetic is not a guess
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
            'kind': 'column_rect',
            'name': 'column',
            'p': {'w': 0.3, 'd': 0.3, 'h': 2.7},
            'x': 4.8,
            'y': 0,
            'z': 1,
            'mat': 'mat_concrete',
        },
    ]
}

# ── 1. the icons are no longer placeholders ──────────────────────────────────
st = icon_state(IDS)
check(
    'all five sheet icons exist and are no longer placeholders '
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
JS = r"""async () => {
  const SH = window.drawings_sheet, out = {};
  const dp = new DOMParser();
  const sheetHtml = () => { const e = document.getElementById('ar-sheet'); return e ? e.innerHTML : ''; };
  const measure = (s) => {
    const x = dp.parseFromString(s, 'image/svg+xml'), root = x.documentElement;
    const nested = Array.from(x.querySelectorAll('svg > svg'));
    return {
      parsed: x.getElementsByTagName('parsererror').length === 0 && root.nodeName === 'svg',
      width: root.getAttribute('width'), height: root.getAttribute('height'),
      viewBox: root.getAttribute('viewBox'),
      nested: nested.length,
      nested_boxes: nested.map(e => [e.getAttribute('x'), e.getAttribute('y'),
                                     e.getAttribute('width'), e.getAttribute('height'),
                                     e.getAttribute('viewBox')]),
      nested_content: nested.map(e => e.querySelectorAll('polygon, path, polyline, text').length),
      texts: Array.from(x.querySelectorAll('text')).map(e => e.textContent),
      groups: x.querySelectorAll('svg > g[data-view]').length,
      clips: x.querySelectorAll('clipPath').length,
      clipped_lines: Array.from(x.querySelectorAll('g[clip-path] path')).length,
      pattern_fills: Array.from(x.querySelectorAll('[fill^="url(#"]')).length
    };
  };

  out.api = typeof SH === 'object' && typeof SH.compose === 'function' && typeof SH.settings === 'function';
  out.depends_on_drawings2d = !!(window.drawings2d && typeof drawings2d.svg === 'function');
  out.letters = [SH.revLetter(0), SH.revLetter(1), SH.revLetter(25), SH.revLetter(26)];

  /* --- dc_title: the title block content ------------------------------- */
  arTool('dc_title', {project: 'Test', client: 'Board of Works', drawn: 'ZZ', checked: 'QQ',
                      number: 'ZY-1001', notes: 'do not scale'});
  out.title = JSON.parse(JSON.stringify(SH.settings().title));
  arTool('dc_title');                                     /* a person gets the form */
  out.title_form = /PROJECT|project/.test(sheetHtml()) && /<input/.test(sheetHtml());
  arSheetClose();

  /* --- dc_rev: the revision table, letters incrementing ---------------- */
  arTool('dc_rev', {add: {note: 'first', by: 'ZZ'}});
  out.rev_list_sheet = /ds-rev-del/.test(sheetHtml()) && /first/.test(sheetHtml());
  arTool('dc_rev', {add: {note: 'second', by: 'QQ'}});
  out.revs = JSON.parse(JSON.stringify(SH.settings().revisions));
  SH.delRev(1);                                           /* the list sheet's Delete button */
  out.revs_after_delete = SH.settings().revisions.map(r => r.rev + ':' + r.note);
  arSheetClose();

  /* --- dc_sheet: compose an A3 landscape page with two drawings -------- */
  const composed = AR_EXT.tools.dc_sheet.act({size: 'A3', orient: 'landscape',
      views: [{kind: 'plan', storey: 0}, {kind: 'elevation', elev: 'front'}]});
  out.sheet_return = composed;
  out.sheet_preview = /<svg/.test(sheetHtml()) && /Download SVG/.test(sheetHtml());
  const res = SH.last;
  out.page = measure(res.svg);
  out.page_pdf = measure(res.pdf);
  out.res = {w_mm: res.w_mm, h_mm: res.h_mm, size: res.size, orient: res.orient,
             title_line: res.title_line, scales: res.scales, rev: res.rev,
             views: res.views, name: res.name};
  arSheetClose();
  arTool('dc_sheet');                                     /* a person gets the checkbox form */
  out.sheet_form = (document.querySelectorAll('input.ds-view').length >= 6)
                && !!document.getElementById('ds-size');
  arSheetClose();

  /* the setup lives with the document and goes out with it */
  out.doc_ext = !!(AR.doc.ext && AR.doc.ext.drawings_sheet);
  out.saved_ext = JSON.parse(JSON.stringify(arDocOut().ext.drawings_sheet || {}));

  /* --- a 1:20 detail on A4 portrait does not fit, so it is halved ------ */
  const d2s = drawings2d.settings();
  const wasScale = d2s.scale;
  d2s.scale = 20;                    /* 1:20 -> the 6x4 room is 500 x 400 mm */
  const small = SH.compose({size: 'A4', orient: 'portrait',
                            views: [{kind: 'plan', storey: 0}, {kind: 'elevation', elev: 'front'}]});
  out.a4 = {w_mm: small.w_mm, h_mm: small.h_mm, width: measure(small.svg).width,
            reduced: small.views.filter(v => v.reduced).length, effs: small.views.map(v => v.eff),
            asked: small.views.map(v => v.scale),
            note: (small.svg.match(/halved \d+. to fit the sheet/g) || []).length,
            fits: small.views.every(v => v.x_mm + v.w_mm <= small.w_mm - 10
                                      && v.y_mm + v.h_mm <= small.h_mm - 10)};
  d2s.scale = wasScale;
  /* back to the A3 page for the PDF and the print */
  SH.compose({size: 'A3', orient: 'landscape',
              views: [{kind: 'plan', storey: 0}, {kind: 'elevation', elev: 'front'}]});
  arSheetClose();

  /* --- dc_pdf: act() returns the Promise of the blob ------------------- */
  const blob = await AR_EXT.tools.dc_pdf.act();
  out.pdf = {type: blob.type, size: blob.size, isBlob: blob instanceof Blob};
  out.pdf_toast = document.getElementById('ar-toast').innerHTML;

  /* --- dc_print: the window path (spied), then the iframe fallback ----- */
  const realOpen = window.open;
  let written = '';
  window.open = () => ({document: {open(){}, write(h){ written += h; }, close(){}, readyState: 'complete'},
                        focus(){}, print(){ written += '<!--printed-->'; }});
  const rw = AR_EXT.tools.dc_print.act();
  out.print_window = {path: rw && rw.path, w_mm: rw && rw.w_mm,
                      has_svg: /<svg[^>]*width="420mm"/.test(written),
                      page_css: /@page\s*\{\s*size:\s*420mm 297mm/.test(written)};
  out.print_window_toast = document.getElementById('ar-toast').innerHTML;

  window.open = () => null;                               /* popup blocked */
  const ri = AR_EXT.tools.dc_print.act();
  const fr = document.querySelector('#ar-stage iframe.ds-print');
  const fsvg = fr && fr.contentDocument ? fr.contentDocument.querySelector('svg') : null;
  out.print_iframe = {path: ri && ri.path, exists: !!fr, paper: fr && fr.getAttribute('data-paper'),
                      svg_w: fsvg && fsvg.getAttribute('width'), svg_h: fsvg && fsvg.getAttribute('height')};
  out.print_iframe_toast = document.getElementById('ar-toast').innerHTML;
  window.open = realOpen;

  out.pdf_body = SH.last.pdf;                             /* for the server-side proof */
  return out;
}"""

r = browser_eval(JS, doc=DOC)
v = r['value']
check('no page errors while pressing the five icons', not r['errors'], r['errors'])
check(
    'window.drawings_sheet exposes compose() and settings(), and drawings_2d is under it',
    v['api'] and v['depends_on_drawings2d'],
    [v.get('api'), v.get('depends_on_drawings2d')],
)

# dc_title
check(
    'dc_title: the fields are stored in the title block',
    v['title']['project'] == 'Test'
    and v['title']['client'] == 'Board of Works'
    and v['title']['drawn'] == 'ZZ'
    and v['title']['checked'] == 'QQ'
    and v['title']['number'] == 'ZY-1001'
    and len(v['title']['date']) == 10,
    v['title'],
)
check('dc_title: a person gets a form of the title fields', v['title_form'], v['title_form'])

# dc_rev
check(
    'dc_rev: revision letters increment A, B and carry the note, the date and the initials',
    [x['rev'] for x in v['revs']] == ['A', 'B']
    and v['revs'][0]['note'] == 'first'
    and v['revs'][0]['by'] == 'ZZ'
    and len(v['revs'][0]['date']) == 10,
    v['revs'],
)
check(
    'dc_rev: it opens a list sheet with a Delete button per revision, and deleting renumbers',
    v['rev_list_sheet'] and v['revs_after_delete'] == ['A:first'],
    [v['rev_list_sheet'], v['revs_after_delete']],
)
check('revision letters carry past Z (A, B, Z, AA)', v['letters'] == ['A', 'B', 'Z', 'AA'], v['letters'])

# dc_sheet
p, res = v['page'], v['res']
check(
    'dc_sheet: the composed page parses and is a true A3 landscape sheet, 420 x 297 mm',
    p['parsed']
    and p['width'] == '420mm'
    and p['height'] == '297mm'
    and p['viewBox'] == '0 0 420 297'
    and res['w_mm'] == 420
    and res['h_mm'] == 297,
    [p['width'], p['height'], p['viewBox']],
)
check(
    'dc_sheet: the two drawings are placed as two nested <svg> viewports, each with real content',
    p['nested'] == 2 and all(n > 20 for n in p['nested_content']),
    {'nested': p['nested'], 'content': p['nested_content'], 'boxes': p['nested_boxes']},
)
check(
    'dc_sheet: at 1:100 both views are on the page at 1:1 mm (the plan viewport is 100 x 80 mm, unreduced)',
    [b[2] for b in p['nested_boxes']][0] == '100'
    and [b[3] for b in p['nested_boxes']][0] == '80'
    and res['views'][0]['eff'] == 100
    and not res['views'][0]['reduced'],
    p['nested_boxes'],
)
check(
    'dc_sheet: the largest drawing is placed first, left to right, inside the 10 mm border',
    float(p['nested_boxes'][0][0]) >= 10
    and float(p['nested_boxes'][1][0]) > float(p['nested_boxes'][0][0])
    and float(p['nested_boxes'][1][0]) + float(p['nested_boxes'][1][2]) <= 410,
    p['nested_boxes'],
)
check(
    'dc_sheet: the title block carries the project, the drawing number, the scale and the date',
    'Test' in p['texts']
    and 'ZY-1001' in p['texts']
    and '1:100' in p['texts']
    and 'ZYGOMATIC' in p['texts']
    and 'DRAWING No' in p['texts'],
    p['texts'][-24:],
)
check(
    'dc_sheet: the revision table is drawn with the current revision letter, and the block shows it',
    'REV' in p['texts']
    and 'DESCRIPTION' in p['texts']
    and 'first' in p['texts']
    and p['texts'].count('A') >= 2
    and res['rev'] == 'A',
    [res['rev'], p['texts'][:20]],
)
check(
    'dc_sheet: the drawing title comes from the views it composed',
    'Plan' in res['title_line'] and 'Elevation' in res['title_line'],
    res['title_line'],
)
check(
    'dc_sheet: act() reports the page it made and the icon opens a preview with a Download SVG button',
    v['sheet_return']
    and v['sheet_return']['size'] == 'A3'
    and len(v['sheet_return']['views']) == 2
    and v['sheet_preview'],
    [v['sheet_return'], v['sheet_preview']],
)
check('dc_sheet: a person gets a sheet of checkboxes and a paper-size picker', v['sheet_form'], v['sheet_form'])
check(
    'dc_sheet: the setup lives in AR.doc.ext.drawings_sheet and goes out with the document',
    v['doc_ext']
    and v['saved_ext'].get('size') == 'A3'
    and len(v['saved_ext'].get('views') or []) == 2
    and v['saved_ext']['title']['project'] == 'Test'
    and len(v['saved_ext'].get('revisions') or []) == 1,
    v['saved_ext'],
)
a4 = v['a4']
check(
    'dc_sheet: a 1:20 drawing too big for an A4 portrait page is halved until it fits, '
    'the note under it says so, and it still lands inside the border',
    a4['w_mm'] == 210
    and a4['h_mm'] == 297
    and a4['width'] == '210mm'
    and a4['reduced'] >= 1
    and a4['asked'] == [20, 20]
    and min(a4['effs']) > 20
    and a4['note'] == a4['reduced']
    and a4['fits'],
    a4,
)

# the PDF-ready body
g = v['page_pdf']
check(
    'dc_sheet: the PDF body is the same page with the viewports flattened to <g transform> '
    'and every pattern hatch expanded into clipped lines (svglib supports neither)',
    g['groups'] == 2 and g['nested'] == 0 and g['clips'] >= 4 and g['clipped_lines'] >= 20 and g['pattern_fills'] == 0,
    {
        'groups': g['groups'],
        'nested': g['nested'],
        'clips': g['clips'],
        'lines': g['clipped_lines'],
        'pattern_fills': g['pattern_fills'],
    },
)

# dc_pdf
check(
    'dc_pdf: act() returns the Promise of an application/pdf blob and toasts its size',
    v['pdf']['isBlob']
    and v['pdf']['type'] == 'application/pdf'
    and v['pdf']['size'] > 5000
    and 'PDF' in v['pdf_toast'],
    [v['pdf'], v['pdf_toast'][:160]],
)

# dc_print
pw = v['print_window']
check(
    'dc_print: the window path writes the sheet inline with an @page of the paper size and calls print()',
    pw['path'] == 'window' and pw['w_mm'] == 420 and pw['has_svg'] and pw['page_css'],
    pw,
)
check(
    'dc_print: the window path says so in a toast',
    'new window' in v['print_window_toast'],
    v['print_window_toast'][:160],
)
pi = v['print_iframe']
check(
    'dc_print: when the window is blocked it falls back to an iframe on the stage carrying the same '
    'A3 sheet SVG, and says which path ran',
    pi['path'] == 'iframe'
    and pi['exists']
    and pi['paper'] == '420x297'
    and pi['svg_w'] == '420mm'
    and pi['svg_h'] == '297mm'
    and 'embedded frame' in v['print_iframe_toast'],
    [pi, v['print_iframe_toast'][:160]],
)

# ── 3. the server extension really writes a PDF ──────────────────────────────
body = v['pdf_body']
out = server_ext('drawings_sheet', 'pdf', {'svg': body, 'w_mm': 420, 'h_mm': 297, 'name': 'zy-1001-a3'})
data = out.get('bytes') or b''
check(
    'server_ext pdf: the composed A3 sheet comes back as a real, non-trivial PDF download',
    data[:4] == b'%PDF'
    and len(data) > 5000
    and b'/Contents' in data
    and out.get('mime') == 'application/pdf'
    and out.get('filename') == 'zy-1001-a3.pdf',
    {
        'head': data[:8],
        'len': len(data),
        'mime': out.get('mime'),
        'filename': out.get('filename'),
        'error': out.get('error'),
    },
)
bad = server_ext('drawings_sheet', 'pdf', {'svg': 'not an svg'})
check(
    'server_ext pdf: a payload that is not an SVG is refused, not crashed',
    bad.get('code') == 400 or 'error' in bad,
    bad,
)
sizes = server_ext('drawings_sheet', 'paper', {})
check(
    'server_ext paper: the ISO sizes agree with the tab (A3 = 297 x 420 portrait)',
    sizes.get('sizes', {}).get('A3') == [297, 420],
    sizes,
)

# ── 4. the assistant twins ───────────────────────────────────────────────────
from zyg_workflows import arch_assistant as A  # noqa: E402

check(
    'the assistant gained the sheet tools',
    {'compose_sheet', 'set_title_block', 'add_revision', 'export_pdf'} <= {t['name'] for t in A.TOOL_DEFS},
    sorted(t['name'] for t in A.TOOL_DEFS)[:8],
)
check('all five icons are declared pressable by the model', set(IDS) <= A.EXT_BUTTONS, sorted(A.EXT_BUTTONS)[:12])

txt, d = assistant('set_title_block', {'project': 'Test', 'number': '1001', 'drawn': 'AB'})
s = d.ext['drawings_sheet']
check(
    'set_title_block writes AR.doc.ext.drawings_sheet.title and it round-trips through the document',
    s['title']['project'] == 'Test'
    and s['title']['number'] == '1001'
    and s['title']['drawn'] == 'AB'
    and d.to_doc()['ext']['drawings_sheet']['title']['project'] == 'Test',
    [txt, s['title']],
)

txt, d = assistant('add_revision', {'note': 'first', 'by': 'ZZ'}, drawing=d)
txt2, d = assistant('add_revision', {'note': 'second', 'by': 'ZZ'}, drawing=d)
check(
    'add_revision appends the next letter with a date and the initials',
    [r['rev'] for r in d.ext['drawings_sheet']['revisions']] == ['A', 'B']
    and d.ext['drawings_sheet']['revisions'][0]['note'] == 'first'
    and 'B' in txt2,
    [txt, txt2, d.ext['drawings_sheet']['revisions']],
)

txt, d = assistant(
    'compose_sheet',
    {'size': 'A3', 'views': [{'kind': 'plan', 'storey': 0}, {'kind': 'elevation', 'elev': 'front'}]},
    drawing=d,
)
check(
    'compose_sheet presses dc_sheet in the tab with the page and the views',
    txt.startswith('requested')
    and d.ui[-1]
    == {
        'cmd': 'tool',
        'args': {
            'id': 'dc_sheet',
            'args': {'size': 'A3', 'views': [{'kind': 'plan', 'storey': 0}, {'kind': 'elevation', 'elev': 'front'}]},
        },
    },
    [txt, d.ui[-1]],
)
txt, d = assistant('export_pdf', {'name': 'ZY-1001'}, drawing=d)
check(
    'export_pdf presses dc_pdf and files the sheet under the drawing number',
    d.ui[-1]['args']['id'] == 'dc_pdf' and d.ext['drawings_sheet']['title']['number'] == 'ZY-1001',
    [txt, d.ui[-1]],
)
txt, _ = assistant('compose_sheet', {'size': 'A9'})
check('an unknown paper size is refused', txt.startswith('refused'), txt)
txt, _ = assistant('compose_sheet', {'views': [{'kind': 'axonometric'}]})
check('an unknown view kind is refused', txt.startswith('refused'), txt)
txt, _ = assistant('press_button', {'id': 'dc_print'})
check('the model may press dc_print', txt.startswith('pressed'), txt)

finish()
