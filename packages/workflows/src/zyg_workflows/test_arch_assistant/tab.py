# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sections 2 + 3 — the tab: the in-page script and test_tab."""

import json
from zyg_workflows.test_arch_assistant.drawer import URL, check

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ── 2 + 3. the tab ───────────────────────────────────────────────────────────
SCRIPT = r"""
async (canned) => {
  const out = {};
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  window.confirm = () => true; window.prompt = (q, d) => d || '1';
  const view = document.getElementById('view-architecture');
  if (view.getAnimations) { try { await Promise.all(view.getAnimations().map(a => a.finished)); } catch (e) {} }

  /* Shift+R paints labels; plain R still arms Room */
  arToolApply('select');
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'R', shiftKey: true, bubbles: true}));
  out.cellsOn = AR.cells.on; out.toolAfterShiftR = AR.tool;
  const cv = AR.cells.field.cv, px = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  let lit = 0; for (let i = 3; i < px.length; i += 4 * 97) if (px[i] > 40) lit++;
  out.cellsLit = lit; out.cellsVisible = AR.cells.field.mesh.visible; out.cellsScale = AR.cells.field.mesh.scale.x;
  const tg = AR.controls.target, fm = AR.cells.field.mesh;
  out.field = {span: fm.scale.x, dx: Math.abs(fm.position.x - tg.x), dz: Math.abs(fm.position.z - tg.z), near: AR.cells.near.mesh.visible, nearSpan: AR.cells.near.span};
  /* far away the near layer must switch off; close in it must be on and small */
  AR.cam.position.set(tg.x + 90, 120, tg.z + 90); AR.controls.update(); arCellsTick(true); out.farNear = AR.cells.near.mesh.visible;
  AR.cam.position.set(tg.x + 8, 10, tg.z + 8); AR.controls.update(); arCellsTick(true); out.closeNear = {on: AR.cells.near.mesh.visible, span: AR.cells.near.span};
  /* the header button opens the panel, Shift+A toggles it */
  document.getElementById('ar-assist-btn').click(); out.btnOpen = AR.assist.open && getComputedStyle(document.getElementById('ar-assist')).display !== 'none' && document.getElementById('ar-assist-btn').classList.contains('on');
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'A', shiftKey: true, bubbles: true})); out.shiftAClosed = !AR.assist.open;
  out.hud = document.getElementById('ar-hud').textContent;
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'r', bubbles: true}));
  out.toolAfterR = AR.tool; out.cellsStillOn = AR.cells.on;
  arToolApply('select');
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'R', shiftKey: true, bubbles: true}));
  out.cellsOff = !AR.cells.on && !AR.cells.field.mesh.visible;

  /* the section clip must NOT be on a fresh material while Section is off */
  AR.matCache={}; const mc=arMat('mat_concrete'); out.clipOff = !(mc.clippingPlanes && mc.clippingPlanes.length) && !AR.clipOn;
  /* walk: faces the drawing, W/S follow the pitch, the floor is the only limit */
  arNewObj('wall', {len: 4, h: 2.7, t: 0.24}, 0, 0, 0);
  arWalkEnter(); const W = AR.walk; const toModel = new THREE.Vector3(0, 0, 0).sub(W.pos); const fwd = new THREE.Vector3(-Math.sin(W.yaw), 0, -Math.cos(W.yaw));
  out.walkFaces = toModel.dot(fwd) > 0; out.walkY0 = W.pos.y;
  W.pitch = -1.0; W.keys['s'] = true; W.t = performance.now() - 40; arWalkStep(); W.keys['s'] = false; out.walkBackUp = W.pos.y - out.walkY0;
  W.pitch = 1.0; W.keys['w'] = true; W.t = performance.now() - 40; arWalkStep(); W.keys['w'] = false; out.walkUpFwd = W.pos.y;
  W.pitch = 0; W.pos.y = 0.3; W.keys['q'] = true; W.t = performance.now() - 40; arWalkStep(); W.keys['q'] = false; out.walkFloor = W.pos.y;
  arWalkLeave(); arNew();
  /* storey follows the drawing plane */
  arSetLevel(5.4); out.storeyHud = document.getElementById('ar-hud').textContent.indexOf('storey') >= 0 && arStorey() === 2;
  arSetLevel(0);

  /* the three new dock icons rasterise, distinct, non-blank (the dock
     probe's own recipe: paint what the browser paints, hash the pixels) */
  const hashes = {};
  for (const id of ['d_cells', 'c_assist', 'f_blend']) {
    const el = document.querySelector('#ar-dock .ar-tool[data-tool="' + id + '"]');
    if (!el || !el.querySelector('svg')) { hashes[id] = 'MISSING'; continue; }
    const svg = el.querySelector('svg').cloneNode(true);
    svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    svg.setAttribute('width', 48); svg.setAttribute('height', 48);
    svg.setAttribute('color', '#000'); svg.setAttribute('stroke', '#000');
    const url = 'data:image/svg+xml;base64,' + btoa(new XMLSerializer().serializeToString(svg));
    const img = new Image();
    try { await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; }); }
    catch (e) { hashes[id] = 'BROKEN'; continue; }
    const c = document.createElement('canvas'); c.width = c.height = 48;
    const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 48, 48); g.drawImage(img, 0, 0, 48, 48);
    const d = g.getImageData(0, 0, 48, 48).data; let ink = 0, h = 2166136261;
    for (let i = 0; i < d.length; i += 4) { if (d[i] < 200) ink++; h ^= d[i]; h = Math.imul(h, 16777619); }
    hashes[id] = ink ? (h >>> 0).toString(16) : 'BLANK';
  }
  out.icons = hashes;

  /* the ring: both phase texts, indeterminate then determinate */
  arRing('Drawing request, Injecting soon', null, 'x');
  const ring = document.getElementById('ar-ring');
  out.ring1 = {shown: getComputedStyle(ring).display !== 'none', text: ring.textContent, spin: !!ring.querySelector('svg.spin'),
               optsLeft: parseInt(getComputedStyle(document.getElementById('ar-opts')).left, 10)};
  arRing('Drawing done, Injecting now', 0.5, '');
  out.ring2 = {text: ring.textContent, spin: !!ring.querySelector('svg.spin'),
               offset: parseFloat(ring.querySelector('.fg').style.strokeDashoffset)};
  arRing(false); out.ringHidden = getComputedStyle(ring).display === 'none';

  /* injection: one undo step, shadow frustum grows, undo takes it all back */
  arNew(); const before = AR.objs.length, undoBefore = AR.undo.length;
  const sc0 = AR.sun.shadow.camera.right;
  const res = {doc: canned, added: canned.objects.map(o => o.id), removed: [], changed: [], summary: 's'};
  await new Promise(r => arAssistApply(res, r));
  const bb = arBounds(false);
  out.inject = {objs: AR.objs.length, undo: AR.undo.length - undoBefore, shadowR: AR.sun.shadow.camera.right, shadowR0: sc0,
                boundsR: bb.r, sunTargetY: AR.sun.target.position.y, boundsY: bb.c.y,
                ring: document.getElementById('ar-ring').textContent,
                holes: AR.objs.filter(o => o.kind === 'wall' && o.p.holes && o.p.holes.length).length,
                holeStoreys: [...new Set(AR.objs.filter(o => o.kind === 'wall' && o.p.holes && o.p.holes.length).map(o => Math.round(o.y / 2.7)))].sort((a, b) => a - b),
                holesPerWall: Math.max(...AR.objs.filter(o => o.kind === 'wall').map(o => (o.p.holes || []).length)),
                seq: AR.seq};
  arUndo();
  out.afterUndo = AR.objs.length;

  /* ghost preview: keeps as real materials, discards as undo */
  AR.assist.preview = true;
  await new Promise(r => arAssistApply({doc: canned, added: canned.objects.map(o => o.id), removed: [], changed: [], summary: 's'}, r));
  out.ghost = {ghosts: AR.objs.filter(o => o._ghost).length, flag: AR.assist.ghost};
  arAssistKeep();
  out.kept = {ghosts: AR.objs.filter(o => o._ghost).length, glassWalls: AR.objs.filter(o => o.kind === 'wall' && o.mat === 'mat_glass').length, objs: AR.objs.length};
  await new Promise(r => arAssistApply({doc: {objects: []}, added: [], removed: AR.objs.map(o => o.id), changed: [], summary: 's'}, r));
  out.cleared = AR.objs.length;
  AR.assist.preview = false;

  /* the round trip against the mocked server */
  AR.assist.open = true; arAssistRender();
  document.getElementById('ar-assist-in').value = 'build it';
  window.__posts = []; const undoTrip = AR.undo.length;
  arAssistSend();
  for (let i = 0; i < 200 && (AR.assist.job || document.getElementById('ar-ring').style.display !== 'none'); i++) await sleep(100);
  out.trip = {posts: window.__posts, objs: AR.objs.length, hist: AR.assist.hist.map(m => (m.role + ':' + (m.kind || '') + ':' + (m.text || '').slice(0, 40))),
              ringHidden: document.getElementById('ar-ring').style.display === 'none', undo: AR.undo.length - undoTrip};
  return out;
}
"""


def test_tab(canned):
    from playwright.sync_api import sync_playwright

    _zyg_log.info('tab')
    errs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1680, 'height': 1050})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda d: d.accept())

        # the mocked assistant server: start -> running -> need_client(look) -> done
        state = {'polls': 0, 'render': None}

        def route(r):
            req = r.request
            url = req.url
            if url.endswith('/assistant/start'):
                page.evaluate('window.__posts.push("start")')
                body = json.loads(req.post_data or '{}')
                state['start'] = {
                    'text': body.get('text'),
                    'shot': (body.get('screenshot') or '')[:22],
                    'objs': len((body.get('doc') or {}).get('objects') or []),
                }
                return r.fulfill(json={'ok': True, 'id': 'j1'})
            if url.endswith('/assistant/render'):
                body = json.loads(req.post_data or '{}')
                state['render'] = (body.get('image') or '')[:22]
                page.evaluate('window.__posts.push("render")')
                return r.fulfill(json={'ok': True})
            if '/assistant/job' in url:
                state['polls'] += 1
                if state['polls'] == 1:
                    return r.fulfill(
                        json={
                            'ok': True,
                            'status': 'running',
                            'phase': 'drawing',
                            'log': ['draw_box(...)'],
                            'steps': 1,
                            'backend': 'mock',
                        }
                    )
                if state['render'] is None:
                    return r.fulfill(
                        json={
                            'ok': True,
                            'status': 'need_client',
                            'phase': 'drawing',
                            'log': ['look'],
                            'steps': 2,
                            'backend': 'mock',
                            'need': {'kind': 'render', 'view': 'top', 'storey': 1, 'cells': True, 'doc': canned},
                        }
                    )
                return r.fulfill(
                    json={
                        'ok': True,
                        'status': 'done',
                        'phase': 'injecting',
                        'log': ['done'],
                        'steps': 3,
                        'backend': 'mock',
                        'usage': {'in': 1, 'out': 2},
                        'elapsed': 1.0,
                        'result': {
                            'doc': canned,
                            'added': [o['id'] for o in canned['objects']],
                            'removed': [],
                            'changed': [],
                            'summary': 'built the box',
                        },
                    }
                )
            return r.continue_()

        page.route('**/inspect/api/architecture/assistant/**', route)
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function('typeof goToView === "function"', timeout=60000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=60000)
        page.evaluate('AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false;')
        page.evaluate('localStorage.removeItem("ar.assist.hist"); AR.assist.hist=[];')
        r = page.evaluate(SCRIPT, canned)
        browser.close()

    check('no page errors', not errs, errs[:3])
    check('Shift+R paints labels', r['cellsOn'] and r['cellsVisible'] and r['cellsLit'] > 50, r)
    check('Shift+R did not arm Room', r['toolAfterShiftR'] == 'select', r['toolAfterShiftR'])
    check('plain R still arms Room', r['toolAfterR'] == 'room' and r['cellsStillOn'])
    check('Shift+R again hides them', r['cellsOff'])
    check(
        'field is 150x150 centred on the target',
        r['field']['span'] == 150 and r['field']['dx'] <= 1.5 and r['field']['dz'] <= 1.5,
        r['field'],
    )
    check(
        'near layer off when far, on and small when close',
        (not r['farNear']) and r['closeNear']['on'] and r['closeNear']['span'] <= 30,
        (r['farNear'], r['closeNear']),
    )
    check(
        'header button opens the panel; Shift+A closes it',
        r['btnOpen'] and r['shiftAClosed'],
        (r['btnOpen'], r['shiftAClosed']),
    )
    check('HUD names the storey', r['storeyHud'])
    check('fresh material is NOT clipped while Section is off', r['clipOff'])
    check(
        'walk faces the drawing, starts at eye height',
        r['walkFaces'] and abs(r['walkY0'] - 1.65) < 1e-6,
        (r['walkFaces'], r['walkY0']),
    )
    check(
        'walk: looking down + S rises; looking up + W rises; floor holds',
        r['walkBackUp'] > 0 and r['walkUpFwd'] > r['walkY0'] + r['walkBackUp'] and abs(r['walkFloor'] - 0.2) < 1e-6,
        (r['walkBackUp'], r['walkUpFwd'], r['walkFloor']),
    )
    ic = r['icons']
    check(
        'three new icons rasterise, distinct',
        all(v not in ('MISSING', 'BLANK', 'BROKEN') for v in ic.values()) and len(set(ic.values())) == 3,
        ic,
    )
    check(
        'ring phase 1 text + spin + opts moved',
        r['ring1']['shown']
        and 'Drawing request, Injecting soon' in r['ring1']['text']
        and r['ring1']['spin']
        and r['ring1']['optsLeft'] > 300,
        r['ring1'],
    )
    check(
        'ring phase 2 text, determinate',
        'Drawing done, Injecting now' in r['ring2']['text']
        and not r['ring2']['spin']
        and 40 < r['ring2']['offset'] < 50,
        r['ring2'],
    )
    check('ring hides', r['ringHidden'])
    n = len(canned['objects'])
    inj = r['inject']
    check(f'injects {n} objects as ONE undo step', inj['objs'] == n and inj['undo'] == 1, inj)
    check('walls got their window holes', inj['holes'] > 0, inj['holes'])
    check(
        'holes land on the even storeys, one window per wall',
        inj['holeStoreys'] == list(range(0, 20, 2)) and inj['holesPerWall'] <= 4,
        (inj['holeStoreys'], inj['holesPerWall']),
    )
    check(
        'shadow frustum covers the tower, aimed at it',
        inj['shadowR'] >= inj['boundsR'] and abs(inj['sunTargetY'] - inj['boundsY']) < 1e-3,
        inj,
    )
    check('seq advanced past the injected ids', inj['seq'] > n, inj['seq'])
    check('undo takes the whole injection back', r['afterUndo'] == 0, r['afterUndo'])
    check('ghost preview injects ghosts', r['ghost']['ghosts'] == n and r['ghost']['flag'], r['ghost'])
    check(
        'keep restores materials',
        r['kept']['ghosts'] == 0 and r['kept']['glassWalls'] == 0 and r['kept']['objs'] == n,
        r['kept'],
    )
    check('a removal-only result clears', r['cleared'] == 0, r['cleared'])
    t = r['trip']
    check('round trip posted start and answered the look', t['posts'] == ['start', 'render'], t['posts'])
    check(
        'start carried the request + a jpeg screenshot',
        state.get('start', {}).get('text') == 'build it' and state['start']['shot'].startswith('data:image/jpeg'),
        state.get('start'),
    )
    check('the look came back as a jpeg', (state['render'] or '').startswith('data:image/jpeg'), state['render'])
    check('done result injected, ring hidden', t['objs'] == n and t['ringHidden'], t)
    check(
        'history: user then assistant summary', t['hist'] == ['user::build it', 'assistant::built the box'], t['hist']
    )
    check('look left no undo entry behind', t['undo'] == 1, t['undo'])
