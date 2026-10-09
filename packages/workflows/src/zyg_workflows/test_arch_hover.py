# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_arch_hover.py — the library rail's hover preview.

    venv/bin/python test_arch_hover.py

Three kinds of row get their picture from three different places, and each can
break on its own, so each is hovered for real (a synthesised mouseover through
the same delegated listener the browser uses) and inspected:

    asset      a rendered PNG on disk
    material   the ingest's 128 px thumbnail
    element    NOTHING on disk — rendered live from arGeom() into an offscreen
               canvas, which is also the only one that can never go stale

The geometry is asserted too, because "a card appeared" is not the request:
the card has to sit AGAINST the rail's right border, and stay inside the
viewport when the row it belongs to is near the bottom of the screen.
"""

import json
import sys
from zyg_workflows import paths

from playwright.sync_api import sync_playwright

URL = paths.ZYG_KANBAN_URL + '/inspection.html#architecture'

SCRIPT = """
async () => {
  const out = {};
  const rail = document.getElementById('ar-rail');
  if (!rail) return {err: 'no rail'};

  // Open every section and group so rows of each kind exist in the DOM.
  AR.sections.forEach(s => {
    AR.open['s:' + s.key] = true;
    s.groups.forEach(g => { AR.open[s.key + '|' + g.g] = true; });
  });
  arRailRender();
  await new Promise(r => setTimeout(r, 60));

  const hoverAndRead = async (sel) => {
    const row = document.querySelector(sel);
    if (!row) return {err: 'no row for ' + sel};
    // A person cannot hover a row scrolled out of the rail, so neither may
    // the test — the card is deliberately suppressed for one.
    row.scrollIntoView({block: 'center'});
    await new Promise(r => setTimeout(r, 60));
    row.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    // give an <img> a moment to lay out so offsetHeight is real
    await new Promise(r => setTimeout(r, 350));
    const el = document.getElementById('ar-hoverpv');
    if (!el) return {err: 'no card'};
    let img = el.querySelector('img.pv-img');
    // WAIT for the picture rather than sleeping a number that happened to be
    // long enough. A fixed 350 ms was fine when the rail held 1,500 rows; at
    // 8,800 the first image fetch had not finished decoding and the test
    // reported naturalWidth 0 for a file the server was serving correctly at
    // 200/185 KB. The assertion below is unchanged — this only stops the probe
    // reading it too early, and still gives up so a genuinely broken preview
    // fails instead of hanging.
    for (let i = 0; i < 60 && img && !(img.complete && img.naturalWidth > 0); i++) {
      await new Promise(r => setTimeout(r, 100));
      img = el.querySelector('img.pv-img');
    }
    const sw = el.querySelector('.pv-swatch');
    const cb = el.getBoundingClientRect(), rb = rail.getBoundingClientRect();
    return {
      shown: el.classList.contains('on'),
      hasImg: !!img,
      hasSwatch: !!sw,
      srcKind: img ? (img.src.startsWith('data:') ? 'rendered' : 'file') : null,
      imgLoaded: img ? (img.complete && img.naturalWidth > 0) : null,
      naturalW: img ? img.naturalWidth : null,
      name: (el.querySelector('.pv-n') || {}).textContent || '',
      sub: (el.querySelector('.pv-sub') || {}).textContent || '',
      // the whole point: flush against the rail's right rule
      gap: +(cb.left - rb.right).toFixed(1),
      inViewport: cb.top >= 0 && cb.bottom <= window.innerHeight + 0.5,
      rowLabel: (row.querySelector('.lb') || {}).textContent || '',
    };
  };

  const secRow = (key) => `#ar-rail .ar-item[data-sec="${key}"]`;
  out.asset = await hoverAndRead(secRow('assets'));
  out.material_textured = await (async () => {
    // find a material row whose item carries maps
    const rows = [...document.querySelectorAll(secRow('materials'))];
    const hit = rows.find(r => {
      const f = arRailItem(r.getAttribute('data-id'));
      return f && f.it.p && f.it.p.maps && f.it.p.maps.map;
    });
    if (!hit) return {err: 'no textured material row'};
    hit.scrollIntoView({block: 'center'});
    await new Promise(r => setTimeout(r, 60));
    hit.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    await new Promise(r => setTimeout(r, 350));
    const el = document.getElementById('ar-hoverpv');
    const img = el.querySelector('img.pv-img');
    return {shown: el.classList.contains('on'), hasImg: !!img,
            imgLoaded: img ? (img.complete && img.naturalWidth > 0) : null,
            naturalW: img ? img.naturalWidth : null,
            name: (el.querySelector('.pv-n')||{}).textContent || ''};
  })();
  out.element = await hoverAndRead(secRow('elements'));

  // hiding
  const row = document.querySelector(secRow('elements'));
  row.dispatchEvent(new MouseEvent('mouseout', {bubbles: true, relatedTarget: document.body}));
  await new Promise(r => setTimeout(r, 120));
  out.hidesOnLeave = !document.getElementById('ar-hoverpv').classList.contains('on');

  // A row scrolled out of the rail must NOT get a card — and must not get an
  // unpositioned one parked in the corner, which is what used to happen.
  {
    const rows2 = [...document.querySelectorAll(secRow('assets'))];
    rail.scrollTop = 0;
    await new Promise(r => setTimeout(r, 60));
    const far = rows2[rows2.length - 1];
    far.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    await new Promise(r => setTimeout(r, 150));
    out.offscreenSuppressed = !document.getElementById('ar-hoverpv').classList.contains('on');
  }

  // a row near the very bottom must still produce a card inside the viewport
  const rows = [...document.querySelectorAll(secRow('assets'))];
  const last = rows[rows.length - 1];
  if (last) {
    last.scrollIntoView({block: 'end'});
    await new Promise(r => setTimeout(r, 80));
    last.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
    await new Promise(r => setTimeout(r, 300));
    const el = document.getElementById('ar-hoverpv');
    const cb = el.getBoundingClientRect();
    out.bottomRow = {inViewport: cb.top >= 0 && cb.bottom <= window.innerHeight + 0.5,
                     top: Math.round(cb.top), bottom: Math.round(cb.bottom),
                     vh: window.innerHeight};
  }
  return out;
}
"""


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1600, 'height': 900})
        page.on('pageerror', lambda e: print(f'  [pageerror] {e}', file=sys.stderr))
        page.on('dialog', lambda d: d.accept())
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function('typeof goToView === "function"', timeout=60000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.sections && AR.sections.length > 0', timeout=60000)
        r = page.evaluate(SCRIPT)
        browser.close()

    print(json.dumps(r, indent=1))
    if r.get('err'):
        print('FAIL: ' + r['err'])
        return 1

    a, m, e = r['asset'], r['material_textured'], r['element']
    checks = [
        ('asset row shows a card', a.get('shown')),
        ('asset preview is a file that loaded', a.get('srcKind') == 'file' and a.get('imgLoaded')),
        ('material row shows a loaded thumbnail', m.get('shown') and m.get('imgLoaded')),
        ('element preview is RENDERED, not a file', e.get('srcKind') == 'rendered'),
        ('element preview has real pixels', bool(e.get('naturalW'))),
        # Resolution is the point of the quality pass, so it is asserted
        # rather than eyeballed. The card is 248 CSS px wide; anything at or
        # under that is being upscaled on a 2x display. Kenney's own shipped
        # previews are 64 px, which is what this guards against creeping back.
        ('asset preview is at least 512 px', (a.get('naturalW') or 0) >= 512),
        ('material thumb is at least 320 px', (m.get('naturalW') or 0) >= 320),
        ('rendered element preview is at least 512 px', (e.get('naturalW') or 0) >= 512),
        ('card sits on the rail border (gap < 2px)', abs(a.get('gap', 99)) < 2),
        ('card stays in the viewport', a.get('inViewport')),
        ('bottom row card stays in the viewport', (r.get('bottomRow') or {}).get('inViewport')),
        ('card hides when the pointer leaves', r.get('hidesOnLeave')),
        ('a row scrolled out of the rail gets no card', r.get('offscreenSuppressed')),
    ]
    bad = 0
    for name, ok in checks:
        print(f'{"PASS" if ok else "FAIL"}  {name}')
        bad += not ok
    print(f'\n{len(checks) - bad}/{len(checks)} passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
