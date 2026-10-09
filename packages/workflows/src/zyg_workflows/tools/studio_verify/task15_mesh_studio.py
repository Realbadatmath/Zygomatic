#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof for task 15 — Mesh Studio's three bars, placeholder sheet, picker, stage.

Headless Chrome at the operator's 67% zoom viewport (2507x1567). Asserts the
186 registry options are all drawn and all marked as placeholders, that clicking
one opens a sheet that says so, that the picker opens a real mesh onto the stage,
and prints the overflow measurements the brief asks for.
"""

import json
import sys
from playwright.sync_api import sync_playwright
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

URL = paths.ZYG_KANBAN_URL + '/inspection.html#mesh'
SHOT = str(paths.ZYG_OUTPUT_ROOT / 'studio_verify' / 'task15_mesh_studio.png')
fails = []


def check(name, ok, detail=''):
    _zyg_log.info(('PASS  ' if ok else 'FAIL  ') + name + (('  ' + detail) if detail else ''))
    if not ok:
        fails.append(name)


with sync_playwright() as p:
    br = p.chromium.launch(
        executable_path='/usr/bin/google-chrome', args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
    )
    pg = br.new_page(viewport={'width': 2507, 'height': 1567})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(URL, wait_until='load', timeout=90000)
    pg.wait_for_function("document.querySelectorAll('.msh-tool').length > 0", timeout=60000)

    n_all = pg.eval_on_selector_all('.msh-tool', 'x => x.length')
    n_ph = pg.eval_on_selector_all('.msh-tool.ph', 'x => x.length')
    check('186 options drawn', n_all == 186, '.msh-tool = %d' % n_all)
    check('186 marked placeholder', n_ph == 186, '.msh-tool.ph = %d' % n_ph)

    tips = pg.evaluate("""() => Array.from(document.querySelectorAll('.msh-tool'))
        .filter(e => !/\\[placeholder/.test(e.title || '')).length""")
    check('every tooltip says [placeholder]', tips == 0, '%d without it' % tips)

    per_bar = pg.evaluate("""() => ({
        left: document.querySelectorAll('#msh-left .msh-tool').length,
        right: document.querySelectorAll('#msh-tools .msh-tool').length,
        foot: document.querySelectorAll('#msh-dock .msh-tool').length})""")
    _zyg_log.info('BARS  ' + json.dumps(per_bar))
    check('all three bars carry the whole registry', per_bar['left'] + per_bar['right'] + per_bar['foot'] == 186)

    # ── the placeholder sheet ───────────────────────────────────────────────
    pg.click('.msh-tool[data-msh="top_decimate"]')
    pg.wait_for_selector('#msh-panel.on', timeout=10000)
    body = pg.inner_text('#msh-panel-bd')
    title = pg.inner_text('#msh-panel-title')
    check('sheet opened on top_decimate', 'Decimate' in title, 'title=%r' % title)
    check("sheet says 'placeholder'", 'placeholder' in body.lower(), repr(body[:90]))
    knobs = pg.eval_on_selector_all('#msh-panel-bd .msh-knob', 'x => x.length')
    check('sheet draws the op knobs', knobs > 0, '%d knobs' % knobs)

    # ── the picker → a real mesh on the stage ───────────────────────────────
    pg.click('#msh-panel .hd button')
    pg.evaluate('mshOpenPicker()')
    pg.wait_for_selector('#msh-picker.on', timeout=10000)
    pg.wait_for_function("document.querySelectorAll('#msh-iboard .mesh-card').length > 0", timeout=30000)
    cards = pg.eval_on_selector_all('#msh-iboard .mesh-card', 'x => x.length')
    _zyg_log.info('PICKER %d cards' % cards)
    pg.eval_on_selector_all('#msh-iboard .mesh-card', 'x => x[0].click()')
    pg.click('#msh-igo')
    pg.wait_for_function('!!(window.MS && MS.rec)', timeout=20000)
    opened = pg.evaluate('MS.name')
    check('picker opened a mesh in the studio', bool(opened), 'MS.name=%r' % opened)
    check(
        'picker did NOT open the full-screen viewer',
        pg.evaluate("document.getElementById('mesh-viewer').style.display !== 'flex'"),
    )

    # the orbit rig: 33 MB of geometry over localhost, then a first frame
    try:
        pg.wait_for_function('!!(window.MSH3 && MSH3.loadedKey)', timeout=180000)
        rig = pg.evaluate("""() => ({key: MSH3.loadedKey, raf: !!MSH3.raf,
            mesh: !!MSH3.mesh, lines: !!MSH3.lines,
            canvas: !!document.querySelector('#msh-3d canvas')})""")
        check('3D rig built and running', rig['mesh'] and rig['raf'] and rig['canvas'], json.dumps(rig))
    except Exception as e:
        check('3D rig built and running', False, str(e)[:120])

    # the open-toast sits over the foot bar for 5.2 s — let it clear, or it
    # hides the very bar the screenshot has to show
    pg.wait_for_function("document.getElementById('msh-toast').style.display === 'none'", timeout=15000)
    pg.wait_for_timeout(600)
    sub = pg.inner_text('#msh-csub')
    _zyg_log.info('HEADER %s | %s' % (pg.inner_text('#msh-cname'), sub))
    check('header carries counts + chip', 'verts' in sub)

    # ── overflow measurements the brief asks for ────────────────────────────
    m = pg.evaluate("""() => {
      const d = document.getElementById('msh-dock');
      const r = document.getElementById('msh-tools');
      const l = document.getElementById('msh-left');
      return {foot_scrollW: d.scrollWidth, foot_clientW: d.clientWidth,
              right_scrollH: r.scrollHeight, right_clientH: r.clientHeight,
              left_scrollH: l.scrollHeight, left_clientH: l.clientHeight};
    }""")
    _zyg_log.info('MEASURE ' + json.dumps(m))
    _zyg_log.info(
        'MEASURE foot overflow = %d px (%.2f screens)'
        % (m['foot_scrollW'] - m['foot_clientW'], m['foot_scrollW'] / m['foot_clientW'])
    )
    _zyg_log.info(
        'MEASURE left rail = %.2f screens, right rail = %.2f screens'
        % (m['left_scrollH'] / max(m['left_clientH'], 1), m['right_scrollH'] / max(m['right_clientH'], 1))
    )
    check(
        'foot does not scroll sideways',
        m['foot_scrollW'] <= m['foot_clientW'] + 1,
        '%d > %d' % (m['foot_scrollW'], m['foot_clientW']),
    )
    check(
        'left rail within ~1.2 screens',
        m['left_scrollH'] / max(m['left_clientH'], 1) <= 1.2,
        '%.2f' % (m['left_scrollH'] / max(m['left_clientH'], 1)),
    )
    check(
        'right rail within ~1.2 screens',
        m['right_scrollH'] / max(m['right_clientH'], 1) <= 1.2,
        '%.2f' % (m['right_scrollH'] / max(m['right_clientH'], 1)),
    )

    bars = pg.evaluate("""() => ({
        left: document.getElementById('msh-leftcol').offsetHeight > 0,
        right: document.getElementById('msh-toolcol').offsetHeight > 0,
        foot: document.getElementById('msh-dock').offsetHeight > 0})""")
    check('all three bars visible for the shot', all(bars.values()), json.dumps(bars))

    pg.screenshot(path=SHOT)
    _zyg_log.info('SHOT  ' + SHOT)

    check('no page errors', not errs, '; '.join(errs[:3]))
    br.close()

_zyg_log.info(
    '\n%s — %d failure(s)%s'
    % ('FAILED' if fails else 'ALL CHECKS PASSED', len(fails), (': ' + ', '.join(fails)) if fails else '')
)
sys.exit(1 if fails else 0)
