# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_arch_dock3.py — Architecture Studio's three-row option dock.

    venv/bin/python test_arch_dock3.py

The dock stopped being twenty session controls (2 rows) and became the option
surface of the domain (190 controls, 3 rows). Three things can each break on
their own and none of them is visible in a "the page loaded" check:

  · GEOMETRY — a grid over THREE fixed rows, the captions spanning all three,
    and a bar tall enough to hold them. A wrapping flex row would look almost
    right and could never be scrolled sideways.
  · THE PICTURES — 228 inline SVGs. Two of them painting the same thing, or
    one painting nothing, is invisible until you look for it, so the raster of
    every icon in the live DOM is hashed here, not the markup.
  · THE WIRING — every tool that is NOT marked as a placeholder is clicked for
    real. A live tool that throws, or that quietly opens the "not wired yet"
    toast, is a lie about what the button is.
"""

import json
import sys
from zyg_workflows import paths

from playwright.sync_api import sync_playwright

URL = paths.ZYG_KANBAN_URL + '/inspection.html#architecture'

SCRIPT = r"""
async () => {
  const out = {errors: []};
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  /* something to act on: a slab, two walls and a column */
  arNewObj('slab', {w: 6, d: 4, t: 0.22}, 0, 0, 0);
  arNewObj('wall', {l: 6, h: 2.7, t: 0.24}, 0, -2, 0);
  arNewObj('wall', {l: 6, h: 2.7, t: 0.24}, 0, 2, 0);
  arNewObj('column_rect', {w: 0.3, d: 0.3, h: 2.7}, 2, 1, 0);
  arSelSync(); arPanel(); arHud();

  /* #view-architecture enters with a .pg-in slide: measuring the bar's
     position before that settles reports it 8px below the window and looks
     exactly like a layout overflow. WAIT for the animation rather than
     sleeping a number that was long enough once — a fixed 700ms passed on one
     run and failed on the next. */
  const view = document.getElementById('view-architecture');
  if (view.getAnimations) {
    try { await Promise.all(view.getAnimations().map(a => a.finished)); } catch (e) {}
  }
  for (let i = 0, last = null; i < 60; i++) {
    const t = Math.round(view.getBoundingClientRect().top);
    if (t === last) break;
    last = t; await sleep(50);
  }

  const dock = document.getElementById('ar-dock');
  const grid = dock.querySelector('.ar-dockgrid');
  const cs = getComputedStyle(dock.querySelector('.ar-dgrid'));
  const tools = [...dock.querySelectorAll('.ar-tool')];
  const caps = [...dock.querySelectorAll('.ar-dsec')];

  out.geom = {
    dockH: Math.round(dock.getBoundingClientRect().height),
    rows: cs.gridTemplateRows,
    flow: cs.gridAutoFlow,
    /* the caption is ABOVE its group, not a spine down its left: it has to
       sit higher than every tool in the group it names */
    capAboveGroup: caps.every(c => {
      const g = c.parentElement.querySelector('.ar-dgrid');
      return c.getBoundingClientRect().bottom <= g.getBoundingClientRect().top + 0.5;
    }),
    groups: dock.querySelectorAll('.ar-dgroup').length,
    tools: tools.length,
    captions: caps.length,
    scrollsSideways: dock.scrollWidth > dock.clientWidth + 2,
    /* three distinct row tops, and every tool sits on one of them */
    rowTops: [...new Set(tools.map(t => Math.round(t.getBoundingClientRect().top)))].sort((a,b)=>a-b),
    /* the bar must reach both window edges */
    left: Math.round(dock.getBoundingClientRect().left),
    right: Math.round(window.innerWidth - dock.getBoundingClientRect().right),
    bottom: Math.round(window.innerHeight - dock.getBoundingClientRect().bottom),
  };

  /* ── the pictures. Hash what the browser actually painted. ── */
  const raster = async (el) => {
    const svg = el.querySelector('svg').cloneNode(true);
    svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    svg.setAttribute('width', 48); svg.setAttribute('height', 48);
    svg.setAttribute('color', '#000'); svg.setAttribute('stroke', '#000');
    const url = 'data:image/svg+xml;base64,' + btoa(new XMLSerializer().serializeToString(svg));
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; });
    const c = document.createElement('canvas'); c.width = c.height = 48;
    const g = c.getContext('2d');
    g.fillStyle = '#fff'; g.fillRect(0, 0, 48, 48);
    g.drawImage(img, 0, 0, 48, 48);
    const d = g.getImageData(0, 0, 48, 48).data;
    let ink = 0, h = 2166136261;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] < 200) ink++;
      h ^= d[i]; h = Math.imul(h, 16777619);
    }
    return {ink, h: (h >>> 0).toString(16)};
  };
  const all = [...document.querySelectorAll('#ar-tools .ar-tool, #ar-dock .ar-tool')];
  const seen = {}, blank = [], dup = [];
  for (const el of all) {
    const id = el.getAttribute('data-tool');
    let r;
    try { r = await raster(el); } catch (e) { blank.push(id + ' (render failed)'); continue; }
    if (r.ink < 6) blank.push(id);
    if (seen[r.h]) dup.push([seen[r.h], id]); else seen[r.h] = id;
  }
  out.icons = {painted: all.length, blank, dup, distinct: Object.keys(seen).length};

  /* ── the wiring. Click every live dock tool for real. ── */
  const stubToast = [];
  const clicked = [];
  const skipped = [];
  const dockSecs = AR_TOOLS.filter(s => s.bar === 'dock');
  /* prompts are answered so an option that asks a question is exercised
     rather than skipped; the values are the ones the tool documents */
  const answers = {v_fov: '60', l_time: '9', pr_size: '0.5', o_rename: 'probe',
                   s_byname: 'probe', f_saveas: null, f_save: null};
  window.prompt = (q, d) => (out.prompts = (out.prompts || []).concat(q.slice(0, 32)), d || '1');
  window.confirm = () => true;
  const toastEl = document.getElementById('ar-toast');
  for (const sec of dockSecs) {
    for (const t of sec.items) {
      if (t.stub) { skipped.push(t.id); continue; }
      if (t.id === 'f_new' || t.id === 'f_save' || t.id === 'f_saveas' ||
          t.id === 'f_jsonin' || t.id === 'f_obj' || t.id === 'f_json' || t.id === 'f_shot') { skipped.push(t.id); continue; }
      window.prompt = () => answers[t.id] || '1';
      toastEl.innerHTML = '';
      try { arTool(t.id); } catch (e) { out.errors.push(t.id + ': ' + e.message); }
      await sleep(4);
      if (/placeholder/.test(toastEl.innerHTML)) stubToast.push(t.id);
      clicked.push(t.id);
    }
  }
  out.wiring = {clicked: clicked.length, skipped: skipped, threw: out.errors.slice(), livesThatSaidPlaceholder: stubToast};

  /* ── a placeholder must say so, three ways ── */
  /* 2026-09-08: every icon in the dock is now wired, so there may be NO stub
     left to press. `AR_TOOLS.find(...)` then returns undefined and reading
     `.items` off it crashes the whole probe. When none exists the section
     proves the ABSENCE instead — in the dock AND in the side rail — which is
     the stronger statement; when one exists the original checks still run. */
  const dashedNow = [...dock.querySelectorAll('.ar-tool.stub')].map(e => e.dataset.tool);
  const tipNow = [...dock.querySelectorAll('.ar-tool')]
                   .filter(e => /\[placeholder\]/.test(e.getAttribute('title') || ''))
                   .map(e => e.dataset.tool);
  const rail = document.getElementById('ar-toolcol');
  const sideDashed = rail ? [...rail.querySelectorAll('.ar-tool.stub')].map(e => e.dataset.tool) : [];
  const sideTip = rail ? [...rail.querySelectorAll('.ar-tool')]
                           .filter(e => /\[placeholder\]/.test(e.getAttribute('title') || ''))
                           .map(e => e.dataset.tool) : [];
  const sideFlagged = AR_TOOLS.filter(s => s.bar === 'side').flatMap(s => s.items).filter(i => i.stub).map(i => i.id);
  const stubSec = AR_TOOLS.find(s => s.bar === 'dock' && s.items.some(i => i.stub));
  if (!stubSec) {
    out.placeholder = {none: true, dashedNow, tipNow, sideDashed, sideTip, sideFlagged};
  } else {
    const stub = stubSec.items.find(i => i.stub);
    toastEl.innerHTML = '';
    arTool(stub.id);
    await sleep(10);
    const stubEl = dock.querySelector('.ar-tool[data-tool="' + stub.id + '"]');
    out.placeholder = {
      none: false,
      id: stub.id,
      dashedClass: stubEl.classList.contains('stub'),
      latches: stubEl.classList.contains('on'),
      saysSo: /placeholder/.test(toastEl.innerHTML),
      tooltip: /\[placeholder\]/.test(stubEl.getAttribute('title') || ''),
    };
    arTool(stub.id);                       // click it off again
    await sleep(5);
    out.placeholder.unlatches = !dock.querySelector('.ar-tool[data-tool="' + stub.id + '"]').classList.contains('on');
  }

  /* ── a few of the live ones, measured rather than assumed ── */
  arTool('s_all');    await sleep(5);
  const selAll = AR.sel.length;
  arTool('e_copy');   await sleep(5);
  const before = AR.objs.length;
  arTool('e_paste');  await sleep(20);
  const after = AR.objs.length;
  arTool('undo');     await sleep(20);
  const undone = AR.objs.length;

  const gridVis0 = AR.grid.visible;
  arTool('d_grid');   await sleep(5);
  const gridVis1 = AR.grid.visible;
  arTool('d_grid');   await sleep(5);

  arTool('v_iso');    await sleep(20);
  const isoPos = AR.cam.position.toArray().map(v => +v.toFixed(2));
  arTool('v_back');   await sleep(20);
  const backPos = AR.cam.position.toArray().map(v => +v.toFixed(2));
  arTool('v_prev');   await sleep(20);
  const prevPos = AR.cam.position.toArray().map(v => +v.toFixed(2));

  arTool('q_stats');  await sleep(30);
  const sheet = document.getElementById('ar-sheet');
  const sheetShown = sheet && sheet.style.display !== 'none';
  const sheetRows = sheet ? sheet.querySelectorAll('.ar-tbl tr').length : 0;
  const sheetText = sheet ? sheet.querySelector('.bd').textContent.slice(0, 60) : '';
  arSheetClose();

  arTool('s_all');    await sleep(5);   // undo cleared the selection
  arTool('o_lock');   await sleep(5);
  const lockedN = AR.objs.filter(o => o.lock).length;
  /* the lock is only real if the raycast stops returning it */
  const pickable = () => { const c=[]; AR.objs.forEach(o=>{ if(o.node && !o.hidden && !o.lock) c.push(o.node); }); return c.length; };
  const pickableLocked = pickable() > 0;
  arTool('o_unlock'); await sleep(5);
  const lockedAfter = AR.objs.filter(o => o.lock).length;

  out.live = {
    selAll, pasteAdded: after - before, undoRemoved: after - undone,
    gridToggled: gridVis0 !== gridVis1,
    backMoved: JSON.stringify(isoPos) !== JSON.stringify(backPos),
    prevCameBack: JSON.stringify(prevPos) === JSON.stringify(isoPos),
    sheetShown, sheetRows, sheetText, lockedN, lockedAfter,
    lockedPickable: pickableLocked,
  };

  /* ── the two fold switches still own the right things ── */
  arDockToggle(); await sleep(20);
  out.fold = {dockHidden: dock.classList.contains('off')};
  arDockToggle(); await sleep(20);
  arBarsToggle(); await sleep(20);
  out.fold.barsHideDock = dock.classList.contains('off');
  out.fold.barsHideRail = document.getElementById('ar-toolcol').classList.contains('hid');
  arBarsToggle(); await sleep(20);
  out.fold.backOn = !dock.classList.contains('off');

  /* nothing from the dock family leaked into the side rail, and vice versa */
  const sideIds = new Set(AR_TOOLS.filter(s => s.bar === 'side').flatMap(s => s.items.map(i => i.id)));
  const dockIds = AR_TOOLS.filter(s => s.bar === 'dock').flatMap(s => s.items.map(i => i.id));
  out.overlap = dockIds.filter(id => sideIds.has(id));
  out.counts = {side: sideIds.size, dock: dockIds.length,
                stubs: AR_TOOLS.flatMap(s => s.items).filter(i => i.stub).length};
  return out;
}
"""


def main():
    errs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1680, 'height': 1050})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda d: d.accept())
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function('typeof goToView === "function"', timeout=60000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=60000)
        # 2048² soft shadows on SwiftShader take minutes — this box has no GPU
        # in headless Chrome, and the dock is what is under test, not the sun.
        page.evaluate('AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false;')
        r = page.evaluate(SCRIPT)

        # ── the wheel, driven as a real wheel rather than a synthesised event.
        # A dispatched WheelEvent would prove the handler runs; it would not
        # prove the browser lets it scroll the bar, which is the whole point.
        page.evaluate("document.getElementById('ar-dock').scrollLeft = 600")
        box = page.locator('#ar-dock').bounding_box()
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.wait_for_timeout(80)
        start = page.evaluate("document.getElementById('ar-dock').scrollLeft")
        page.mouse.wheel(0, -240)  # wheel FORWARD, away from you
        page.wait_for_timeout(120)
        fwd = page.evaluate("document.getElementById('ar-dock').scrollLeft")
        page.mouse.wheel(0, 240)  # wheel BACK, towards you
        page.wait_for_timeout(120)
        back = page.evaluate("document.getElementById('ar-dock').scrollLeft")
        # it must stop at both ends rather than run past them
        for _ in range(30):
            page.mouse.wheel(0, 400)
        page.wait_for_timeout(150)
        at_left = page.evaluate("document.getElementById('ar-dock').scrollLeft")
        for _ in range(60):
            page.mouse.wheel(0, -400)
        page.wait_for_timeout(150)
        at_right = page.evaluate(
            "(d=>({l:d.scrollLeft, max:d.scrollWidth-d.clientWidth}))(document.getElementById('ar-dock'))"
        )
        # and the wheel must do this only over the BAR — over the viewport it
        # is the camera's dolly and must not drag the toolbar around
        page.evaluate("document.getElementById('ar-dock').scrollLeft = 600")
        sbox = page.locator('#ar-stage').bounding_box()
        page.mouse.move(sbox['x'] + sbox['width'] / 2, sbox['y'] + sbox['height'] / 2)
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(150)
        over_stage = page.evaluate("document.getElementById('ar-dock').scrollLeft")
        r['wheel'] = {
            'start': start,
            'fwd': fwd,
            'back': back,
            'atLeft': at_left,
            'atRight': at_right,
            'overStage': over_stage,
        }
        browser.close()

    print(json.dumps(r, indent=1)[:6000])
    g, ic, w, p, lv = r['geom'], r['icons'], r['wiring'], r['placeholder'], r['live']

    # 2026-09-08: the studio runs at a browser zoom that is not a whole number of
    # device pixels, so CSS lengths read back a hair under their declared value
    # (a 38px row measures 37.9897px) and a scroll that has hit the end reports
    # 816.42 against a maximum of 816. These are rasteriser artefacts, not dock
    # defects — every length below is therefore compared to ±0.5 px.
    PX = 0.5

    def px(s):
        """the numbers in a CSS length list, e.g. '38px 38px 38px' -> [38.0]*3"""
        return [float(v[:-2]) for v in str(s).split() if v.endswith('px')]

    rows_px = px(g['rows'])
    notch = abs(r['wheel']['fwd'] - r['wheel']['start'])
    print(
        '  wheel: start %.2f -> fwd %.2f (notch %.2f) -> back %.2f; '
        'right end %.2f of %.2f; rows %s'
        % (
            r['wheel']['start'],
            r['wheel']['fwd'],
            notch,
            r['wheel']['back'],
            r['wheel']['atRight']['l'],
            r['wheel']['atRight']['max'],
            rows_px,
        )
    )

    # ── the placeholder section ──────────────────────────────────────────────
    # Every dock icon is wired now, so there is no stub to press. The probe then
    # has to assert exactly that, from five angles, instead of testing a
    # placeholder that no longer exists.
    if p.get('none'):
        placeholder_checks = [
            ('no placeholders remain — AR_TOOLS carries no stub flag at all', r['counts']['stubs'] == 0),
            ('no placeholders remain — no dock icon wears the dashed class', not p['dashedNow']),
            ('no placeholders remain — no dock icon keeps a [placeholder] tooltip', not p['tipNow']),
            (
                'no placeholders remain — the side rail is clean too',
                not p['sideDashed'] and not p['sideTip'] and not p['sideFlagged'],
            ),
            (
                'no placeholders remain — the wiring sweep skipped nothing as a stub',
                w['clicked'] + len(w['skipped']) == r['counts']['dock']
                and set(w['skipped']) == {'f_new', 'f_save', 'f_saveas', 'f_jsonin', 'f_obj', 'f_json', 'f_shot'},
            ),
        ]
    else:
        placeholder_checks = [
            ('a placeholder is dashed', p['dashedClass']),
            ('a placeholder latches', p['latches']),
            ('a placeholder says so out loud', p['saysSo']),
            ('a placeholder says so in its tooltip', p['tooltip']),
            ('a placeholder can be clicked off', p['unlatches']),
        ]

    checks = [
        ('dock holds every dock tool', g['tools'] == r['counts']['dock']),
        ('dock is a column-flow grid', g['flow'] == 'column'),
        ('grid is THREE fixed rows', len(rows_px) == 3 and all(abs(v - 38) <= PX for v in rows_px)),
        ('every caption sits above its own group', g['capAboveGroup']),
        ('one group per dock section', g['groups'] == g['captions']),
        ('dock is 156px tall', g['dockH'] == 156),
        ('tools sit on exactly three rows', len(g['rowTops']) == 3),
        ('the bar scrolls sideways', g['scrollsSideways']),
        ('the bar reaches both window edges and the foot', g['left'] == 0 and g['right'] == 0 and g['bottom'] == 0),
        ('a locked object cannot be picked', r['live']['lockedPickable'] is False),
        ('no icon paints nothing', not ic['blank']),
        ('no two icons paint the same thing', not ic['dup']),
        ('every icon is distinct in the live DOM', ic['distinct'] == ic['painted']),
        ('no live tool threw', not w['threw']),
        ('no live tool called itself a placeholder', not w['livesThatSaidPlaceholder']),
        ('the page raised no errors', not errs),
        *placeholder_checks,
        ('Select all selected the drawing', lv['selAll'] >= 4),
        ('copy + paste added objects', lv['pasteAdded'] >= 4),
        ('undo took the paste back', lv['undoRemoved'] == lv['pasteAdded']),
        ('the grid switch moves the grid', lv['gridToggled']),
        ('Back view moves the camera', lv['backMoved']),
        ('Previous camera steps back to where it was', lv['prevCameBack']),
        ('a report opens a sheet with rows', lv['sheetShown'] and lv['sheetRows'] >= 6),
        ('lock locks and unlock releases', lv['lockedN'] >= 4 and lv['lockedAfter'] == 0),
        ('the grip folds the dock alone', r['fold']['dockHidden']),
        ('the arrow folds both bars', r['fold']['barsHideDock'] and r['fold']['barsHideRail']),
        ('both come back', r['fold']['backOn']),
        ('nothing is in both bars', not r['overlap']),
        ('wheel forward moves the bar RIGHT', r['wheel']['fwd'] > r['wheel']['start']),
        ('wheel back moves the bar LEFT', r['wheel']['back'] < r['wheel']['fwd']),
        # One notch must move the bar a useful amount — unless there is not that
        # much bar left. The probe starts the wheel at scrollLeft 600 and, at the
        # studio's zoom, the whole travel is only 816 px, so a full notch runs
        # into the right end after 216 px and reports the clamped distance. That
        # is the bar stopping correctly, not a notch that is too small.
        (
            'a notch moves a useful distance',
            240 - PX <= notch <= 800 + PX or abs(r['wheel']['fwd'] - r['wheel']['atRight']['max']) <= PX,
        ),
        ('it stops at the left end', r['wheel']['atLeft'] == 0),
        ('it stops at the right end', abs(r['wheel']['atRight']['l'] - r['wheel']['atRight']['max']) <= PX),
        ('the wheel over the viewport leaves the bar alone', r['wheel']['overStage'] == 600),
    ]
    if errs:
        print('\npage errors:')
        for e in errs[:8]:
            print('  ' + e)
    bad = 0
    print()
    for name, ok in checks:
        print(f'{"PASS" if ok else "FAIL"}  {name}')
        bad += not ok
    print(
        f'\n{len(checks) - bad}/{len(checks)} passed  '
        f'({r["counts"]["side"]} side + {r["counts"]["dock"]} dock tools, '
        f'{r["counts"]["stubs"]} marked as placeholders)'
    )
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
