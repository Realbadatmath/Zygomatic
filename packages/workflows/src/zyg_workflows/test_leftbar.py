# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_leftbar.py — the third strip in Video Studio and Creature Studio.

    ~/zygomatics-zero/venv/bin/python test_leftbar.py

(launched with channel='chrome' — the system google-chrome — because the
playwright browser bundle in that venv is a version behind its own client.)

A left rail can render, be full of icons, and still be wrong in three ways a
"page loads" check never sees: it can sit under the bottom bar instead of
beside it, it can duplicate icons that are still drawn in another strip, and
its popover can open on top of the rail it came from.  All three are measured.
"""

import json
import sys
from zyg_workflows import paths
from playwright.sync_api import sync_playwright

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

BASE = paths.ZYG_KANBAN_URL + '/inspection.html'

VIDEO = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = {errors: []};
  for (let i = 0; i < 100; i++) {
    if (document.querySelectorAll('#vst-left .vst-ic').length) break;
    await sleep(100);
  }
  const view = document.getElementById('view-videos');
  if (view.getAnimations) { try { await Promise.all(view.getAnimations().map(a=>a.finished)); } catch(e){} }
  await sleep(300);

  const R = id => document.getElementById(id).getBoundingClientRect();
  const cnt = sel => document.querySelectorAll(sel).length;
  const left = R('vst-left'), rail = R('vst-rail'), bar = R('vst-bar');
  const body = document.querySelector('.vst-body').getBoundingClientRect();
  const main = document.querySelector('#view-videos .cs-mainwrap').getBoundingClientRect();

  out.counts = {left: cnt('#vst-left .vst-ic'), rail: cnt('#vst-rail .vst-ic'),
                bar: cnt('#vst-bar .vst-ic')};
  out.geom = {
    leftX: Math.round(left.left), leftW: Math.round(left.width), leftH: Math.round(left.height),
    railX: Math.round(rail.left), railW: Math.round(rail.width), railH: Math.round(rail.height),
    bodyH: Math.round(body.height), barH: Math.round(bar.height),
    bodyBottom: Math.round(body.bottom), leftBottom: Math.round(left.bottom),
    railBottom: Math.round(rail.bottom),
    barX: Math.round(bar.left), barR: Math.round(bar.right),
    previewW: Math.round(main.width), win: window.innerWidth,
    leftCols: getComputedStyle(document.getElementById('vst-left')).gridTemplateColumns,
    leftScroll: document.getElementById('vst-left').scrollHeight,
    leftClient: document.getElementById('vst-left').clientHeight,
    barScrollW: document.getElementById('vst-bar').scrollWidth,
    barClientW: document.getElementById('vst-bar').clientWidth,
  };
  if (left.left > 4) out.errors.push('left rail is not at the window edge: x=' + left.left);
  if (Math.round(left.height) !== Math.round(rail.height))
    out.errors.push('rails are different heights: ' + left.height + ' vs ' + rail.height);
  if (left.right > main.left + 1) out.errors.push('left rail overlaps the preview');

  /* 2026-09-05: the dock sits BETWEEN the rails, so both rails reach the
     bottom of the pane. A rail that stops above the dock is the defect this
     replaced — measure the gap, don't trust the screenshot. */
  if (Math.round(left.bottom) < Math.round(body.bottom) - 1)
    out.errors.push('left rail stops ' + Math.round(body.bottom - left.bottom) + 'px short of the bottom');
  if (Math.round(rail.bottom) < Math.round(body.bottom) - 1)
    out.errors.push('right rail stops ' + Math.round(body.bottom - rail.bottom) + 'px short of the bottom');
  if (bar.left < left.right - 1) out.errors.push('dock runs under the left rail');
  if (bar.right > rail.left + 1) out.errors.push('dock runs under the right rail');
  /* the fourth column on the left rail */
  const lcols = getComputedStyle(document.getElementById('vst-left'))
                  .gridTemplateColumns.trim().split(/\s+/).length;
  out.geom.leftColCount = lcols;
  if (lcols !== 5) out.errors.push('left rail has ' + lcols + ' columns, want 5');
  const drows = getComputedStyle(document.querySelector('#vst-bar .vst-dgrid'))
                  .gridTemplateRows.trim().split(/\s+/).length;
  out.geom.dockRowCount = drows;
  out.geom.dockRows = getComputedStyle(document.querySelector('#vst-bar .vst-dgrid')).gridTemplateRows;
  if (drows !== 4) out.errors.push('dock has ' + drows + ' rows, want 4');

  /* no icon may be drawn in two strips */
  const ids = {};
  ['vst-left','vst-rail','vst-bar'].forEach(s => {
    document.querySelectorAll('#'+s+' .vst-ic').forEach(el => {
      (ids[el.id] = ids[el.id] || []).push(s); });
  });
  out.dupes = Object.keys(ids).filter(k => ids[k].length > 1);
  if (out.dupes.length) out.errors.push('icons in two strips: ' + out.dupes.slice(0,5));

  /* 2026-09-05: EXPERIMENTAL belongs to the dock now, and to its FAR RIGHT.
     "in the bar somewhere" is not the ask — measure that it is the last group
     and that its right edge is the dock's own scroll end. */
  out.groups = {left: [...document.querySelectorAll('#vst-left .vst-grp')].map(e=>e.textContent),
                bar: [...document.querySelectorAll('#vst-bar .vst-dsec')].map(e=>e.textContent)};
  if (out.groups.left.indexOf('EXPERIMENTAL') >= 0)
    out.errors.push('EXPERIMENTAL is still in the left rail');
  if (out.groups.bar[out.groups.bar.length-1] !== 'EXPERIMENTAL')
    out.errors.push('EXPERIMENTAL is not the last dock group: ' + out.groups.bar.join(','));
  const groups = [...document.querySelectorAll('#vst-bar .vst-dgroup')];
  const last = groups[groups.length-1];
  const dockEnd = bar.left - document.getElementById('vst-bar').scrollLeft
                + document.getElementById('vst-bar').scrollWidth;
  out.expRight = Math.round(last.getBoundingClientRect().right);
  out.dockEnd = Math.round(dockEnd);
  if (Math.abs(out.expRight - out.dockEnd) > 16)
    out.errors.push('last dock group is not at the dock end: ' + out.expRight + ' vs ' + out.dockEnd);

  /* the captions in the dock must read as headers, not spines */
  const sec = document.querySelector('#vst-bar .vst-dsec');
  const grp = sec ? sec.parentElement.getBoundingClientRect() : null;
  const sr = sec ? sec.getBoundingClientRect() : null;
  out.caption = sr ? {w: Math.round(sr.width), h: Math.round(sr.height),
                      grpBottom: Math.round(grp.bottom), dockBottom: Math.round(bar.bottom)} : null;
  if (sr && sr.height >= sr.width) out.errors.push('dock caption is a vertical spine');
  if (grp && grp.bottom > bar.bottom + 1) out.errors.push('dock group overflows the dock');

  /* a popover opened from the LEFT rail must open to its RIGHT */
  const ic = document.querySelector('#vst-left .vst-ic:not(.act)');
  ic.click(); await sleep(120);
  const pop = document.getElementById('vst-pop').getBoundingClientRect();
  const icr = ic.getBoundingClientRect();
  out.pop = {icRight: Math.round(icr.right), popLeft: Math.round(pop.left)};
  if (pop.left < icr.right) out.errors.push('left-rail popover opens over its own rail');
  document.getElementById('vst-pop').classList.remove('on');
  return out;
}
"""

CREATURE = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = {errors: []};
  for (let i = 0; i < 150; i++) {
    if (document.querySelectorAll('#crst-left .crst-tool').length) break;
    await sleep(100);
  }
  const view = document.getElementById('view-creatures');
  if (view.getAnimations) { try { await Promise.all(view.getAnimations().map(a=>a.finished)); } catch(e){} }
  await sleep(300);

  const R = id => document.getElementById(id).getBoundingClientRect();
  const cnt = sel => document.querySelectorAll(sel).length;
  const lcol = R('crst-leftcol'), rcol = R('crst-toolcol'), dock = R('crst-dock');
  const main = document.querySelector('#view-creatures .cs-mainwrap').getBoundingClientRect();

  out.counts = {left: cnt('#crst-left .crst-tool'), rail: cnt('#crst-tools .crst-tool'),
                dock: cnt('#crst-dock .crst-tool')};
  out.groups = {
    left: [...document.querySelectorAll('#crst-left .crst-grp')].map(e => e.textContent),
    rail: [...document.querySelectorAll('#crst-tools .crst-grp')].map(e => e.textContent),
    dock: [...document.querySelectorAll('#crst-dock .crst-bsec')].map(e => e.textContent),
  };
  out.geom = {
    leftX: Math.round(lcol.left), leftW: Math.round(lcol.width), leftH: Math.round(lcol.height),
    railX: Math.round(rcol.left), railW: Math.round(rcol.width), railH: Math.round(rcol.height),
    dockX: Math.round(dock.left), dockR: Math.round(dock.right), dockH: Math.round(dock.height),
    previewW: Math.round(main.width), win: window.innerWidth,
    leftCols: getComputedStyle(document.getElementById('crst-left')).gridTemplateColumns,
    dockRows: getComputedStyle(document.querySelector('#crst-dock .crst-bgrid')).gridTemplateRows,
    dockScrollW: document.getElementById('crst-dock').scrollWidth,
    dockClientW: document.getElementById('crst-dock').clientWidth,
    leftScroll: document.getElementById('crst-left').scrollHeight,
    leftClient: document.getElementById('crst-left').clientHeight,
  };
  if (lcol.left > 4) out.errors.push('left column is not at the window edge');
  if (Math.round(lcol.height) !== Math.round(rcol.height))
    out.errors.push('columns are different heights: ' + lcol.height + ' vs ' + rcol.height);
  if (dock.left < lcol.right - 1) out.errors.push('dock runs under the left column');
  if (dock.right > rcol.left + 1) out.errors.push('dock runs under the right column');

  const ids = {};
  ['crst-left','crst-tools','crst-dock'].forEach(s => {
    document.querySelectorAll('#'+s+' .crst-tool').forEach(el => {
      const k = el.getAttribute('data-ct'); (ids[k] = ids[k] || []).push(s); });
  });
  out.dupes = Object.keys(ids).filter(k => ids[k].length > 1);
  if (out.dupes.length) out.errors.push('tools in two bars: ' + out.dupes.slice(0,5));

  /* the one arrow must fold all THREE bars, and bring them all back */
  ctBarsToggle(); await sleep(150);
  const hidden = {left: document.getElementById('crst-leftcol').getBoundingClientRect().width,
                  dockOff: document.getElementById('crst-dock').classList.contains('off'),
                  railW: Math.round(document.getElementById('crst-toolcol').getBoundingClientRect().width)};
  out.folded = hidden;
  if (hidden.left !== 0) out.errors.push('arrow left the left column showing');
  if (!hidden.dockOff) out.errors.push('arrow left the dock showing');
  ctBarsToggle(); await sleep(150);
  out.restored = {left: Math.round(document.getElementById('crst-leftcol').getBoundingClientRect().width),
                  tools: document.querySelectorAll('#crst-left .crst-tool').length};
  if (out.restored.left === 0) out.errors.push('the arrow could not bring the left column back');
  return out;
}
"""


def run(page, name, hashname, script):
    page.goto(BASE + '#' + hashname, wait_until='domcontentloaded')
    page.wait_for_timeout(1200)
    res = page.evaluate(script)
    _zyg_log.info(' '.join(str(a) for a in ('══', name, '══')))
    _zyg_log.info(json.dumps(res, indent=2, sort_keys=True))
    return res['errors']


with sync_playwright() as pw:
    b = pw.chromium.launch(channel='chrome', args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1680, 'height': 1050})
    logs = []
    pg.on('pageerror', lambda e: logs.append('PAGEERROR ' + str(e)))
    pg.on('console', lambda m: logs.append('CONSOLE ' + m.type + ' ' + m.text) if m.type == 'error' else None)
    errs = []
    errs += run(pg, 'VIDEO STUDIO', 'videos', VIDEO)
    errs += run(pg, 'CREATURE STUDIO', 'creatures', CREATURE)
    b.close()

_zyg_log.info('\n══ console ══')
for l in logs[:20]:
    _zyg_log.info(' '.join(str(a) for a in (' ', l)))
_zyg_log.info('\n══ verdict ══')
if errs:
    for e in errs:
        _zyg_log.info(' '.join(str(a) for a in ('  FAIL', e)))
    sys.exit(1)
_zyg_log.info('  all geometry checks passed')
