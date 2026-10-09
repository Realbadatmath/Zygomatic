# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_view_scene_ops.py — the viewport-tool family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_view_scene_ops.py

The family adds no kinds, so there is no Blender or geometry leg: what has to
be proven is that every tool appends exactly ONE well-formed entry to d.ui, that
bad input is refused without touching the channel, and that the channel really
does something in the tab (one Playwright step through arAssistUi).
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from zyg_workflows.arch_ext_harness import check, finish, assistant, rail_has, tool_names, URL  # noqa: E402

TOOLS = (
    'set_view',
    'focus',
    'select',
    'show_cells',
    'show_grid',
    'set_storey_plane',
    'set_sun',
    'section',
    'hide_objects',
    'show_all',
    'save_drawing',
    'press_button',
    'say',
)


def step(tool, args, d=None):
    """Run one tool; return (text, drawing, the ui entries it appended)."""
    n = len(d.ui) if d is not None else 0
    txt, d = assistant(tool, args, drawing=d)
    return txt, d, d.ui[n:]


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('all 13 tools registered', all(t in names for t in TOOLS), [t for t in TOOLS if t not in names])

from zyg_workflows import arch_assistant as A  # noqa: E402

V = A.EXT_MODULES['view_scene_ops']  # the module the assistant actually loaded
check('family adds no kinds', V.KINDS == {} and V.OPENINGS == [], (V.KINDS, V.OPENINGS))
check('PROMPT is one paragraph <= 900 chars', 0 < len(V.PROMPT) <= 900 and '\n' not in V.PROMPT, len(V.PROMPT))
check(
    '3-6 worked examples, all naming this family or draw_box',
    3 <= len(V.EXAMPLES) <= 6 and all(c['tool'] in TOOLS + ('draw_box',) for e in V.EXAMPLES for c in e['calls']),
    [c['tool'] for e in V.EXAMPLES for c in e['calls']],
)

# a small drawing to aim the tools at: a Dutch terraced house, 10 x 10 m, 2 storeys
txt, d = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 2, 'roof': 'gable', 'name': 'woonhuis'})
check('fixture drawn (8 walls, 2 slabs, a gable roof)', len(d.objs) == 11 and not d.ui, (len(d.objs), d.ui))

txt, d, u = step('set_view', {'view': 'top'}, d)
check('set_view appends one view command', u == [{'cmd': 'view', 'args': {'view': 'top'}}], (txt, u))
txt, d, u = step('set_view', {'view': 'sideways'}, d)
check('set_view refuses an unknown view, channel untouched', txt.startswith('refused') and u == [], (txt, u))

txt, d, u = step('focus', {'which': 'woonhuis'}, d)
check(
    'focus frames the group by id', len(u) == 1 and u[0]['cmd'] == 'focus' and len(u[0]['args']['ids']) == 11, (txt, u)
)
txt, d, u = step('focus', {'which': 'schuurtje'}, d)
check('focus refuses an unknown group', txt.startswith('refused') and u == [], (txt, u))

txt, d, u = step('select', {'which': 'wall'}, d)
check(
    'select highlights the 8 walls and sets d.selected',
    len(u) == 1 and u[0]['cmd'] == 'select' and len(u[0]['args']['ids']) == 8 and d.selected == u[0]['args']['ids'],
    (txt, u),
)
txt, d, u = step('select', {'which': 'trampoline'}, d)
check('select refuses when nothing matches', txt.startswith('refused') and u == [], (txt, u))

txt, d, u = step('show_cells', {'on': True}, d)
check('show_cells on', u == [{'cmd': 'cells', 'args': {'on': True}}], (txt, u))
txt, d, u = step('show_grid', {'on': False}, d)
check('show_grid off', u == [{'cmd': 'grid', 'args': {'on': False}}], (txt, u))

txt, d, u = step('set_storey_plane', {'storey': 1}, d)
check('set_storey_plane 1', u == [{'cmd': 'storey', 'args': {'storey': 1}}] and '2.7 m' in txt, (txt, u))
txt, d, u = step('set_storey_plane', {'storey': -2}, d)
check('set_storey_plane refuses a negative storey', txt.startswith('refused') and u == [], (txt, u))
txt, d, u = step('set_storey_plane', {'storey': 'top'}, d)
check('set_storey_plane refuses a non-numeric storey (not silently 0)', txt.startswith('refused') and u == [], (txt, u))

txt, d, u = step('set_sun', {'hour': 14}, d)
check('set_sun 14 -> {cmd sun, hour 14}', u == [{'cmd': 'sun', 'args': {'hour': 14}}], (txt, u))
txt, d, u = step('set_sun', {'hour': 30}, d)
check('set_sun refuses hour 30', txt.startswith('refused') and u == [], (txt, u))

txt, d, u = step('section', {'storey': 2}, d)
check('section(2) cuts at storey 2', u == [{'cmd': 'section', 'args': {'storey': 2}}], (txt, u))
txt, d, u = step('section', {'storey': None}, d)
check('section(None) switches it off', u == [{'cmd': 'section', 'args': {'storey': None}}], (txt, u))
txt, d, u = step('section', {}, d)
check('section() with no argument switches it off too', u == [{'cmd': 'section', 'args': {'storey': None}}], (txt, u))
txt, d, u = step('section', {'storey': 'ground'}, d)
check('section refuses a non-numeric storey (not silently 0)', txt.startswith('refused') and u == [], (txt, u))

txt, d, u = step('hide_objects', {'which': 'roof_gable', 'hidden': True}, d)
check(
    'hide_objects hides the one roof',
    len(u) == 1 and u[0]['cmd'] == 'hide' and u[0]['args']['hidden'] is True and len(u[0]['args']['ids']) == 1,
    (txt, u),
)
txt, d, u = step('hide_objects', {'which': 'kelder'}, d)
check('hide_objects refuses an unknown selector', txt.startswith('refused') and u == [], (txt, u))
txt, d, u = step('show_all', {}, d)
check(
    'show_all unhides everything',
    len(u) == 1 and u[0]['cmd'] == 'hide' and u[0]['args']['hidden'] is False and len(u[0]['args']['ids']) == 11,
    (txt, u),
)

txt, d, u = step('save_drawing', {'name': 'Hoofdstraat 12'}, d)
check('save_drawing carries the name', u == [{'cmd': 'save', 'args': {'name': 'Hoofdstraat 12'}}], (txt, u))

txt, d, u = step('press_button', {'id': 'v_top'}, d)
check("press_button('v_top') ok", u == [{'cmd': 'tool', 'args': {'id': 'v_top'}}], (txt, u))
txt, d, u = step('press_button', {'id': 'f_saveas'}, d)
check("press_button('f_saveas') refused", txt.startswith('refused') and u == [], (txt, u))

# BUTTONS is a hand-kept copy of the tab's allow-list; if inspection.html gains or
# loses a button the two drift in silence, so pin them to each other.
_src = open(os.path.join(ROOT, 'inspection.html'), encoding='utf-8', errors='replace').read()
_m = re.search(r'var AR_ASSIST_TOOLS\s*=\s*\{(.*?)\}\s*;', _src, re.S)
_allowed = set(re.findall(r'(\w+)\s*:\s*1', _m.group(1))) if _m else set()
check(
    "BUTTONS is exactly the tab's AR_ASSIST_TOOLS keys",
    _m is not None and _allowed and set(V.BUTTONS) == _allowed,
    sorted(_allowed ^ set(V.BUTTONS)) or len(_allowed),
)
_bad = [
    b for b in sorted(_allowed) if not step('press_button', {'id': b}, d)[2] == [{'cmd': 'tool', 'args': {'id': b}}]
]
check(f'press_button accepts every one of the {len(_allowed)} real button ids', _bad == [], _bad)

txt, d, u = step('say', {'text': 'Klaar — de kap staat erop.'}, d)
check('say appends a toast', u == [{'cmd': 'toast', 'args': {'text': 'Klaar — de kap staat erop.'}}], (txt, u))
txt, d, u = step('say', {'text': '  '}, d)
check('say refuses empty text', txt.startswith('refused') and u == [], (txt, u))

check(
    'no records were created or removed by the viewport tools',
    len(d.objs) == 11 and d.removed == [],
    (len(d.objs), d.removed),
)

# the rail: the family declares no kinds, so it adds no leaves — but its JSON
# must still merge cleanly into the live catalogue.
check('rail lists the kinds (none)', rail_has([]) == [], rail_has([]))
import json  # noqa: E402

rail = json.load(
    open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'arch_ext', 'view_scene_ops.json'),
        encoding='utf-8',
    )
)
check(
    'view_scene_ops.json is an empty elements section', rail['section_key'] == 'elements' and rail['groups'] == [], rail
)
from zyg_workflows import architecture_studio as _st  # noqa: E402

check('the library still builds with the empty section', len(_st.library()['sections']) > 0)

# ── the tab: the d.ui channel, end to end ─────────────────────────────────────
print('tab')
_SCRIPT = r"""
(cmds) => {
  window.confirm = () => true; window.prompt = (q, d) => d || '1';
  const r = {before: {}, after: {}, err: ''};
  try {
    r.before = {cam: AR.cam.position.toArray(), cells: !!(AR.cells && AR.cells.on)};
    for (const u of cmds) arAssistUi(u);
    r.after = {cam: AR.cam.position.toArray(), cells: !!(AR.cells && AR.cells.on)};
  } catch (e) { r.err = String(e && e.message || e); }
  return r;
}
"""


def ui_probe(cmds, timeout_s=120):
    from playwright.sync_api import sync_playwright

    errs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda dlg: dlg.accept())
        page.goto(URL, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=timeout_s * 1000)
        page.evaluate('AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false;')
        out = page.evaluate(_SCRIPT, cmds)
        browser.close()
    out['page_errors'] = errs[:3]
    return out


r = ui_probe([{'cmd': 'view', 'args': {'view': 'top'}}, {'cmd': 'tool', 'args': {'id': 'd_cells'}}])
check('no page errors', not r['page_errors'] and not r['err'], (r.get('err'), r.get('page_errors')))
check(
    'cells were off and the d_cells button turned them on',
    r['before']['cells'] is False and r['after']['cells'] is True,
    (r['before'], r['after']),
)
moved = max(abs(a - b) for a, b in zip(r['after']['cam'], r['before']['cam']))
cam = r['after']['cam']
check(
    'the view command moved the camera, and it now looks straight down',
    moved > 1.0 and cam[1] > abs(cam[0]) and cam[1] > abs(cam[2]),
    (r['before']['cam'], cam, moved),
)

finish()
