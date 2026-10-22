# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""probe_arch_library_board.py — the Architecture card on the Library board.

    ~/zygomatics-zero/venv/bin/python probe_arch_library_board.py

(the venv the other Playwright tests here run under — it has playwright + the
chrome channel; the probe drawing it creates is trashed and the trash file
removed on the way out, so a run leaves the library exactly as it found it)

The Library tab's category board grew an Architecture tile (2026-09-02). What
is worth asserting is not "a card appeared" — three separate things can each
look fine and be wrong:

  * the TILE's glyph. Every other tile's icon is a character, and no emoji font
    resolves in this app's font stack, so a character glyph would draw a tofu
    box. This one is inline SVG: the test reads the rendered <svg>'s box, not
    the codepoint.
  * the BOARD's shape. Level 1 must hold one lane per library section that has
    content, with one card per group — and the counts on those cards have to
    be the counts the API actually returned, not a plausible number.
  * the PICTURES. They come from three different places for three different
    reasons (an asset's rendered PNG on disk, a surface's ingest thumb, and a
    parametric element rendered live from arGeom into a data: URL). Each can
    break alone, so each is opened and its natural size read.

A drawing is created through the save API before the browser runs and trashed
afterwards, because the Projects lane is the one part of the board that cannot
be tested against an empty library.
"""

import glob
import json
import os
import sys
from zyg_workflows import paths

from playwright.sync_api import sync_playwright

from zyg_workflows import http_json

BASE = paths.ZYG_KANBAN_URL
TRASH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'architecture', 'trash')
URL = BASE + '/inspection.html'
PROBE_NAME = 'ZZ library board probe'


def post(path, payload):
    return http_json.post_json(BASE + path, payload, timeout=30)


def make_probe_drawing():
    """A drawing with two kinds in it, so the Contents lane has something to
    group and the 'first object of each kind' picture rule is exercised."""
    doc = {
        'name': PROBE_NAME,
        'units': 'm',
        'schema': 1,
        'objects': [
            {
                'id': 'o1',
                'kind': 'wall',
                'name': 'Wall',
                'p': {'len': 9.0, 'h': 2.7, 't': 0.24},
                'x': 0,
                'y': 0,
                'z': 0,
                'mat': 'mat_brick',
            },
            {
                'id': 'o2',
                'kind': 'wall',
                'name': 'Wall',
                'p': {'len': 4.0, 'h': 2.7, 't': 0.24},
                'x': 4,
                'y': 0,
                'z': 0,
                'mat': 'mat_brick',
            },
            {
                'id': 'o3',
                'kind': 'roof_gable',
                'name': 'Gable roof',
                'p': {'w': 8.0, 'd': 6.0, 'h': 2.4, 'over': 0.4},
                'x': 0,
                'y': 2.7,
                'z': 0,
                'mat': 'mat_roof_tile',
            },
        ],
    }
    return post('/inspect/api/architecture/save', {'doc': doc, 'name': PROBE_NAME, 'id': ''})


SCRIPT = """
async (probeId) => {
  const out = {};
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const waitFor = async (fn, ms) => {
    for (let i = 0; i < ms / 50; i++) { if (fn()) return true; await sleep(50); }
    return false;
  };
  /* Every card picture is loading="lazy", so counting them straight after a
     render measures the fold, not the board: 107 images, 28 started. Scroll
     the whole board past the viewport first — that is also the only way a
     picture below the fold can be proved to exist at all. */
  const scrollSweep = async (el) => {
    const step = Math.max(200, el.clientHeight - 120);
    for (let y = 0; y <= el.scrollHeight; y += step) { el.scrollTop = y; await sleep(140); }
    el.scrollTop = 0; await sleep(140);
  };
  /* Wait for the pictures rather than sleeping a number that happens to be
     long enough — a thumbnail read too early reports naturalWidth 0 for a file
     the server is serving correctly. */
  const imgStats = async (scope) => {
    await scrollSweep(scope);
    const imgs = Array.prototype.slice.call(scope.querySelectorAll('img'));
    for (let i = 0; i < 120; i++) {
      if (imgs.every(im => im.complete)) break;
      await sleep(100);
    }
    return {n: imgs.length,
            loaded: imgs.filter(im => im.complete && im.naturalWidth > 0).length,
            broken: imgs.filter(im => im.complete && !im.naturalWidth)
                        .map(im => im.getAttribute('src')).slice(0, 5),
            unstarted: imgs.filter(im => !im.complete).length};
  };

  const lib = await (await fetch('/inspect/api/architecture')).json();
  out.api = {sections: (lib.sections || []).map(s => ({
    key: s.key, label: s.label,
    groups: (s.groups || []).length,
    items: (s.groups || []).reduce((n, g) => n + (g.items || []).length, 0)}))};

  // ── the tile ──────────────────────────────────────────────────────────
  switchView('inspections');
  libGoCats();
  const tile = document.getElementById('kcat-architecture');
  if (!tile) return {err: 'no Architecture tile on the category board'};
  const ico = tile.querySelector('.ico'), svg = tile.querySelector('.ico svg');
  const sbox = svg ? svg.getBoundingClientRect() : {width: 0, height: 0};
  out.tile = {
    label: (tile.querySelector('.lbl') || {}).textContent,
    hasSvg: !!svg,
    // a character glyph would leave text behind; markup leaves none
    iconText: ico ? ico.textContent.replace(/\\s/g, '') : 'NO-ICO',
    svgW: Math.round(sbox.width), svgH: Math.round(sbox.height),
    order: Array.prototype.map.call(document.querySelectorAll('.kcat-card'),
                                    c => c.id.replace('kcat-', ''))
  };

  // ── level 1 ───────────────────────────────────────────────────────────
  tile.click();
  const ok1 = await waitFor(() => document.querySelectorAll('#lib-board .klane').length > 0, 30000);
  if (!ok1) return {err: 'level 1 never rendered a lane', tile: out.tile};
  const board = document.getElementById('lib-board');
  out.level1 = {
    visible: board.style.display !== 'none',
    lanes: Array.prototype.map.call(board.querySelectorAll('.klane'), ln => ({
      // the header's first child is the collapse caret, not the name
      head: ln.querySelector('.klane-hd span').textContent.replace(/^[\u25be\u25b8\\s]+/, '').trim(),
      n: parseInt(ln.querySelector('.klane-hd .n').textContent, 10),
      cards: ln.querySelectorAll('.kcard').length,
      subs: Array.prototype.map.call(ln.querySelectorAll('.kc-sub'),
                                     e => e.textContent.trim()).slice(0, 3),
      noPic: ln.querySelectorAll('.kc-noimg').length
    })),
    crumbs: document.getElementById('lib-crumbs').textContent.replace(/\\s+/g, ' ').trim()
  };
  out.level1.pics = await imgStats(board);

  // ── level 2: an asset pack (a rendered PNG on disk) ───────────────────
  const si = (lib.sections || []).findIndex(s => s.key === 'assets');
  const gi = si >= 0 ? (lib.sections[si].groups || [])
      .findIndex(g => (g.items || []).some(i => i.pv)) : -1;
  if (si >= 0 && gi >= 0) {
    libOpenArchGroup(si, gi);
    const host = document.getElementById('lib-board-item');
    await waitFor(() => host.querySelectorAll('.kcard').length > 0, 15000);
    const st = await imgStats(host);
    const im = host.querySelector('img.kc-thumb');
    out.assets = {
      group: lib.sections[si].groups[gi].g,
      expected: (lib.sections[si].groups[gi].items || []).length,
      cards: host.querySelectorAll('.kcard').length,
      visible: host.style.display !== 'none',
      pics: st,
      srcKind: im ? (im.src.slice(0, 5) === 'data:' ? 'rendered' : 'file') : 'none',
      naturalW: im ? im.naturalWidth : 0,
      fit: im ? im.classList.contains('kc-fit') : false,
      crumbs: document.getElementById('lib-crumbs').textContent.replace(/\\s+/g, ' ').trim()
    };
  }

  // ── level 2: a parametric group (rendered live, never a file) ─────────
  libGoItems();
  await waitFor(() => document.querySelectorAll('#lib-board .klane').length > 0, 20000);
  const ei = (lib.sections || []).findIndex(s => s.key === 'elements');
  if (ei >= 0) {
    libOpenArchGroup(ei, 0);
    const host = document.getElementById('lib-board-item');
    await waitFor(() => host.querySelectorAll('.kcard').length > 0, 15000);
    const st = await imgStats(host);
    const im = host.querySelector('img.kc-thumb');
    out.elements = {
      group: lib.sections[ei].groups[0].g,
      expected: (lib.sections[ei].groups[0].items || []).length,
      cards: host.querySelectorAll('.kcard').length,
      pics: st,
      srcKind: im ? (im.src.slice(0, 5) === 'data:' ? 'rendered' : 'file') : 'none',
      naturalW: im ? im.naturalWidth : 0
    };
  }

  // ── level 2: a saved drawing ──────────────────────────────────────────
  libGoItems();
  await waitFor(() => document.querySelectorAll('#lib-board .klane').length > 0, 20000);
  const drawLane = Array.prototype.filter.call(
    document.querySelectorAll('#lib-board .klane'),
    ln => ln.querySelector('.klane-hd span').textContent.indexOf('Drawings') >= 0)[0];
  if (drawLane) {
    const card = Array.prototype.filter.call(drawLane.querySelectorAll('.kcard'),
      c => c.textContent.indexOf(%(probe)s) >= 0)[0];
    out.drawing = {laneCards: drawLane.querySelectorAll('.kcard').length, found: !!card};
    if (card) {
      card.click();
      const host = document.getElementById('lib-board-item');
      await waitFor(() => host.querySelectorAll('.kcard').length > 0, 15000);
      const st = await imgStats(host);
      const btn = host.querySelector('button.vc-dl');
      out.drawing.info = host.querySelector('.kc-sub').textContent.trim();
      out.drawing.kinds = Array.prototype.map.call(
        host.querySelectorAll('.klane'), ln =>
          ln.querySelector('.klane-hd').textContent.trim()).join(' | ');
      out.drawing.contentCards = Array.prototype.map.call(
        host.querySelectorAll('.klane')[1].querySelectorAll('.kcard'),
        c => c.querySelector('.kc-title').textContent.trim() + '=' +
             c.querySelector('.kc-sub').textContent.trim());
      out.drawing.pics = st;
      out.drawing.hasButton = !!btn;
      out.drawing.crumbs = document.getElementById('lib-crumbs')
        .textContent.replace(/\\s+/g, ' ').trim();
      if (btn) {
        btn.click();
        await waitFor(() => typeof AR !== 'undefined' && AR.doc && AR.doc.id === probeId, 20000);
        out.handoff = {
          view: document.getElementById('view-architecture').style.display,
          docId: AR.doc && AR.doc.id,
          docName: AR.doc && AR.doc.name,
          objects: AR.objs.length
        };
      }
    }
  }
  return out;
}
""" % {'probe': json.dumps(PROBE_NAME)}


def main():
    saved = make_probe_drawing()
    if not saved.get('ok'):
        print('could not create the probe drawing: ' + json.dumps(saved))
        return 1
    pid = saved['id']
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox']
            )
            page = browser.new_page(viewport={'width': 1600, 'height': 900})
            page.on('pageerror', lambda e: print(f'  [pageerror] {e}', file=sys.stderr))
            page.on('dialog', lambda d: d.accept())
            page.goto(URL, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_function('typeof libOpenCat === "function"', timeout=60000)
            r = page.evaluate(SCRIPT, pid)
            browser.close()
    finally:
        # delete() trashes rather than unlinks (a drawing is hand-made work),
        # which is right for a person and wrong for a probe — a run a day would
        # silt the trash up with copies of this one. Ours, so ours to remove.
        post('/inspect/api/architecture/delete', {'id': pid})
        for f in glob.glob(os.path.join(TRASH, pid + '.*.json')):
            os.remove(f)

    print(json.dumps(r, indent=1)[:4000])
    if r.get('err'):
        print('FAIL: ' + r['err'])
        return 1

    api = {s['key']: s for s in r['api']['sections']}
    t, l1 = r['tile'], r['level1']
    lanes = {ln['head']: ln for ln in l1['lanes']}
    a, e, d = r.get('assets') or {}, r.get('elements') or {}, r.get('drawing') or {}
    h = r.get('handoff') or {}

    def lane_matches(key, label):
        """The lane for a section carries one card per group and says so."""
        s = api.get(key)
        ln = lanes.get(label)
        return bool(s and ln and ln['cards'] == s['groups'] and ln['n'] == s['groups'])

    checks = [
        ('the tile is on the category board', t['label'].strip() == 'Architecture'),
        ('it sits next to Mesh', t['order'].index('architecture') == t['order'].index('mesh') + 1),
        ('its glyph is inline SVG, not a character', t['hasSvg'] and t['iconText'] == ''),
        ('the glyph is actually drawn (>=24px box)', t['svgW'] >= 24 and t['svgH'] >= 24),
        ('clicking it opens level 1', l1['visible'] and len(l1['lanes']) > 0),
        ('the crumbs read Library > Architecture', l1['crumbs'].replace(' ', '').endswith('LibraryArchitecture')),
        ('one lane per section, one card per group: elements', lane_matches('elements', 'Building elements')),
        ('  ... primitives', lane_matches('primitives', 'Primitives')),
        ('  ... materials', lane_matches('materials', 'Materials')),
        ('  ... assets', lane_matches('assets', 'Assets')),
        ('the probe drawing is a card on the Drawings lane', d.get('found')),
        ('every picture on level 1 loaded', l1['pics']['n'] > 0 and l1['pics']['loaded'] == l1['pics']['n']),
        ('an asset pack opens all of its items', a.get('cards') == a.get('expected') and (a.get('expected') or 0) > 0),
        (
            'an asset preview is a FILE that loaded',
            a.get('srcKind') == 'file' and a.get('pics', {}).get('loaded') == a.get('pics', {}).get('n'),
        ),
        ('an asset preview is at least 512 px', (a.get('naturalW') or 0) >= 512),
        ('a model is letterboxed, not cropped', a.get('fit')),
        (
            'a parametric group opens all of its items',
            e.get('cards') == e.get('expected') and (e.get('expected') or 0) > 0,
        ),
        ('a parametric preview is RENDERED, not a file', e.get('srcKind') == 'rendered'),
        ('the rendered preview has real pixels', (e.get('naturalW') or 0) >= 256),
        (
            'a drawing opens onto its own object count',
            '3 objects' in (d.get('info') or '') and '2 kinds' in (d.get('info') or ''),
        ),
        (
            'its contents are grouped by kind, counted',
            sorted(d.get('contentCards') or []) == ['Gable roof=1×', 'Wall=2×'],
        ),
        (
            'the drawing previews are rendered from ITS parameters',
            (d.get('pics') or {}).get('n', 0) >= 2 and d['pics']['loaded'] == d['pics']['n'],
        ),
        ('it offers a way into the Studio', d.get('hasButton')),
        (
            'that button really opens the drawing there',
            h.get('view') == 'flex' and h.get('docName') == PROBE_NAME and h.get('objects') == 3,
        ),
    ]
    bad = 0
    for name, ok in checks:
        print(f'{"PASS" if ok else "FAIL"}  {name}')
        bad += not ok
    print(f'\n{len(checks) - bad}/{len(checks)} passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
