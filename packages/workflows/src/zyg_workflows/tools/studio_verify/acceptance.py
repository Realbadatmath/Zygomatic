#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Acceptance pass over the four studios at the operator's zoom.

One headless Chrome (SwiftShader, viewport 2507x1567 = the GUI at 67 % browser
zoom) walks Character Studio, Creature Studio, Movement Studio and Mesh Studio,
asserts what the tree promised, screenshots each into
    output/studio_verify/final2_<studio>.png
and writes every measurement to
    output/studio_verify/acceptance.json
with a top-level "pass".

Verification only: this script changes nothing in any studio. Staged character
edits are reverted with cstRevertAll() before it leaves.

Second-tree additions (third-party base creature / filled masks / sampled skin):
  * creatures  — the DEFAULT hint must credit a third-party CC0 pack
                 (Quaternius / Kenney / Smithsonian) and must NOT say
                 'Pufferball'; base_creatures >= 4 with no pufferball in any
                 field; [data-ct="v_base"] in the bars; and injecting
                 d0e44ab002ad must switch the pane to that creature's OWN mesh.
  * movement   — the newest done track must have masks > 0 and a control_dir
                 holding at least one png.
  * charstudio — forehead and hand 40x40 patches on the screenshot must read as
                 skin (no channel mean > 245, R > B), i.e. the r144 linear-vs-
                 sRGB washout is gone.

Run:  ../.venv/bin/python tools/studio_verify/acceptance.py
"""

import glob
import json
import logging as _zyg_logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from zyg_workflows import paths

from PIL import Image
from playwright.sync_api import sync_playwright

from zyg_workflows.bin import exe
from zyg_workflows.net import safe_urlopen

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
CREWS = os.path.dirname(TOOLS)
OUT = os.path.join(CREWS, 'output', 'studio_verify')
URL = paths.ZYG_KANBAN_URL + '/inspection.html'
VW, VH = 2507, 1567

EXPECTED_EXT = [
    'char_checks',
    'char_dress',
    'char_file',
    'char_hair',
    'char_run',
    'creature_3d',
    'mesh_studio',
    'movement_track',
]

RES = {'viewport': [VW, VH], 'url': URL, 'when': time.strftime('%Y-%m-%d %H:%M:%S'), 'sections': {}, 'failures': []}


def sect(name):
    RES['sections'].setdefault(name, {'checks': [], 'measured': {}})
    return RES['sections'][name]


def check(section, name, ok, measured=None):
    s = sect(section)
    s['checks'].append({'name': name, 'ok': bool(ok), 'measured': measured})
    line = '%s  %-10s %s' % ('PASS' if ok else 'FAIL', section, name)
    if measured is not None:
        line += '   ' + json.dumps(measured)[:220]
    _zyg_log.info(line)
    if not ok:
        RES['failures'].append('%s: %s = %s' % (section, name, json.dumps(measured)[:220]))
    return bool(ok)


def measure(section, key, value):
    sect(section)['measured'][key] = value


def sh(argv):
    """Run a fixed argv in the crews tree. No shell, so no call site can grow a
    metacharacter: the one call that needed a pipeline reads the bundle over HTTP instead."""
    p = subprocess.run(argv, cwd=CREWS, capture_output=True, text=True, check=False)
    return p.returncode, (p.stdout + p.stderr).strip()


def api_json(path, timeout=60):
    """GET an :8899 route and parse it, raising nothing — errors come back as a
    dict so the check that wanted the payload is the thing that fails."""
    url = paths.ZYG_KANBAN_URL + path
    try:
        with safe_urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}


def mean_rgb(png, cx, cy, hw, hh):
    """Mean RGB of a box on a screenshot, in device pixels."""
    im = Image.open(png).convert('RGB')
    x0, y0 = max(0, int(cx - hw)), max(0, int(cy - hh))
    x1, y1 = min(im.width, int(cx + hw)), min(im.height, int(cy + hh))
    if x1 <= x0 or y1 <= y0:
        return None, [x0, y0, x1, y1]
    crop = im.crop((x0, y0, x1, y1))
    n = crop.width * crop.height
    raw = crop.tobytes()
    r = sum(raw[0::3])
    g = sum(raw[1::3])
    b = sum(raw[2::3])
    return [round(r / n, 2), round(g / n, 2), round(b / n, 2)], [x0, y0, x1, y1]


# ══ page-level checks that need no browser ═══════════════════════════════════
def page_offline_checks():
    rc, out = sh([sys.executable, 'tools/studio_verify/check_inspection_js.py'])
    check('page', 'check_inspection_js.py exit 0', rc == 0, {'exit': rc, 'out': out[-300:]})

    try:
        with safe_urlopen(paths.ZYG_KANBAN_URL + '/studio_ext/bundle.js', timeout=30) as r:
            bundle = r.read().decode('utf-8', 'replace')
    except Exception as e:  # noqa: BLE001
        check('page', 'GET /studio_ext/bundle.js', False, str(e))
        bundle = ''
    got = sorted(set(re.findall('\u2500\u2500 ([a-z_0-9]+)\\.js', bundle)))
    measure('page', 'bundle_modules', got)
    missing = [m for m in EXPECTED_EXT if m not in got]
    check('page', 'bundle serves all eight studio_ext modules', not missing, {'missing': missing, 'listed': got})

    rc3, out3 = sh([exe('node'), 'tools/studio_verify/check_cst_placeholders.js'])
    check('charstudio', 'check_cst_placeholders.js exit 0', rc3 == 0, {'exit': rc3, 'out': out3[-300:]})

    # movement: the spec must carry no placeholder / S08 wording
    try:
        with safe_urlopen(paths.ZYG_KANBAN_URL + '/inspect/api/movement/spec', timeout=30) as r:
            spec = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        check('movement', 'GET /inspect/api/movement/spec', False, str(e))
        spec = {}
    hits = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + '.' + str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, '%s[%d]' % (path, i))
        elif isinstance(node, str):
            low = node.lower()
            if 'placeholder' in low or 's08' in low:
                hits.append({'path': path, 'text': node[:120]})

    walk(spec, 'spec')
    measure('movement', 'spec_actions', len((spec.get('actions') or [])))
    measure('movement', 'spec_keys', sorted(spec.keys()))
    check('movement', "spec has no 'placeholder'/'S08' wording", not hits, hits[:6])

    # the driver endpoint must answer JSON, not an HTML error page
    driver_url = paths.ZYG_KANBAN_URL + '/inspect/api/movement/driver?job=nonexistent'
    code, ctype, body = 0, '', ''
    try:
        with safe_urlopen(driver_url, timeout=30) as r:
            code, ctype, body = r.status, r.headers.get('Content-Type', ''), r.read().decode()
    except urllib.error.HTTPError as e:
        code, ctype, body = e.code, e.headers.get('Content-Type', ''), e.read().decode()
    except Exception as e:  # noqa: BLE001
        body = str(e)
    ok_json = True
    try:
        json.loads(body)
    except Exception:  # noqa: BLE001
        ok_json = False
    measure('movement', 'driver_404', {'code': code, 'ctype': ctype, 'body': body[:200]})
    check(
        'movement',
        'driver?job=nonexistent answers JSON 4xx',
        ok_json and 400 <= code < 500 and 'json' in ctype.lower(),
        {'code': code, 'ctype': ctype, 'parses': ok_json},
    )

    base_creature_checks()
    movement_track_checks()


def base_creature_checks():
    """The base creatures behind the 3D pane are third-party CC0 stand-ins; our
    own pufferball must not be among them (it is only ever ONE creature's own
    mesh). Checked on the served payload, not on the source, because that is
    what the browser reads."""
    ops = api_json('/inspect/api/creature/fx/ops')
    bases = ops.get('base_creatures') or []
    ids = [b.get('id') for b in bases]
    measure('creatures', 'base_creatures_n', len(bases))
    measure('creatures', 'base_creature_ids', ids)
    measure('creatures', 'base_creature_labels', [b.get('lb') for b in bases])
    check(
        'creatures',
        '/inspect/api/creature/fx/ops lists >= 4 base creatures',
        len(bases) >= 4,
        {'n': len(bases), 'error': ops.get('error')},
    )

    ours = []
    for b in bases:
        blob = json.dumps(b).lower()
        if 'pufferball' in blob:
            ours.append(b.get('id'))
    check('creatures', 'no base creature mentions pufferball', not ours, {'offenders': ours})

    packs = sorted(set(str(b.get('pack') or '') for b in bases))
    measure('creatures', 'base_creature_packs', packs)
    third = [p for p in packs if any(t in p.lower() for t in ('quaternius', 'kenney', 'smithsonian'))]
    check('creatures', 'the bases come from third-party CC0 packs', bool(third), {'packs': packs, 'third_party': third})


def newest_done_track():
    """The newest output/movement/_tracks/*/job.json whose status is done."""
    rows = []
    for p in glob.glob(os.path.join(CREWS, 'output', 'movement', '_tracks', '*', 'job.json')):
        try:
            with open(p) as f:
                j = json.load(f)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('run json unreadable, skipped: %s', _exc)
            continue
        if str(j.get('status')) != 'done':
            continue
        rows.append((j.get('ended') or j.get('updated') or os.path.getmtime(p), p, j))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows[0] if rows else (None, None, None)


def movement_track_checks():
    """The run task 3 made: a done track with a real subject mask sequence AND a
    control-plate directory, not an empty-mask fallback."""
    when, path, job = newest_done_track()
    if not job:
        check('movement', 'a done movement track exists', False, {'searched': 'output/movement/_tracks/*/job.json'})
        return
    ctrl = job.get('control_dir') or ''
    pngs = sorted(glob.glob(os.path.join(ctrl, '*.png'))) if ctrl else []
    mdir = job.get('mask_dir') or ''
    mpngs = sorted(glob.glob(os.path.join(mdir, '*.png'))) if mdir else []
    info = {
        'job_id': job.get('job_id'),
        'job_json': path,
        'ended': when,
        'masks': job.get('masks'),
        'frames': job.get('frames'),
        'subject': job.get('subject'),
        'mask_reason': job.get('mask_reason'),
        'mask_dir': mdir,
        'mask_pngs': len(mpngs),
        'control_dir': ctrl,
        'control_pngs': len(pngs),
        'control_first': (os.path.basename(pngs[0]) if pngs else ''),
        'plate_audit_ok': job.get('plate_audit_ok'),
        'plate_audit': job.get('plate_audit'),
    }
    measure('movement', 'newest_done_track', info)
    check(
        'movement',
        'newest done track has masks > 0',
        int(job.get('masks') or 0) > 0,
        {'masks': job.get('masks'), 'mask_dir': mdir, 'mask_pngs': len(mpngs), 'mask_reason': job.get('mask_reason')},
    )
    check(
        'movement',
        'newest done track has a control_dir with >= 1 png',
        bool(ctrl) and len(pngs) >= 1,
        {'control_dir': ctrl, 'pngs': len(pngs)},
    )


# ══ in-page probes ═══════════════════════════════════════════════════════════
STAGE_JS = r"""
(args) => {
  const path = args.path, val = args.val;
  let tool = null, idx = -1;
  CS_TOOLS.forEach(s => (s.items || []).forEach(t => {
    if (t.f === path) { tool = t; idx = -1; }
    else if (t.fs && t.fs.indexOf(path) >= 0) { tool = t; idx = t.fs.indexOf(path); }
  }));
  if (!tool) return {ok: false, why: 'no tool owns ' + path};
  if (idx < 0) cstFieldPanel(tool); else cstMultiPanel(tool);
  const eid = idx < 0 ? 'cst-in' : ('cst-in-' + idx);
  const el = document.getElementById(eid);
  if (!el) return {ok: false, why: 'no editor #' + eid + ' for ' + path};
  el.value = val;
  if (el.getAttribute('data-empty') !== null) el.setAttribute('data-empty', '0');
  cstStageField(path, idx < 0 ? null : eid, true);
  return {ok: CST.dirty[path] === val, tool: tool.id, eid: eid,
          staged: CST.dirty[path], wanted: val};
}
"""

CS_PROBE = r"""
() => {
  const bb = o => { const b = new THREE.Box3().setFromObject(o);
                    return {minY: b.min.y, maxY: b.max.y, minX: b.min.x, maxX: b.max.x}; };
  const r = {
    modelLoaded: !!(CS3 && CS3.model),
    modelType: CS3.model ? CS3.model.type : null,
    modelId: CS3.modelId || null,
    height: CS3.height,
    hairExists: !!CS3.hair,
    hairChildren: CS3.hair ? CS3.hair.children.length : -1,
    dressExists: CS3.dress !== undefined && CS3.dress !== null,
    dressChildren: CS3.dress ? CS3.dress.children.length : -1,
    shoulderY: (CS3.hairInfo && CS3.hairInfo.shoulderY) != null
                 ? CS3.hairInfo.shoulderY : null,
    hairLength: (CS3.hairInfo && CS3.hairInfo.length) || null,
    credit: (document.getElementById('cs-credit') || {}).textContent || '',
    stubs: document.querySelectorAll('.cst-tool.stub').length,
    tools: document.querySelectorAll('.cst-tool').length,
    charId: (window.CS && CS.charId) || null
  };
  if (CS3.hair) r.hairBox = bb(CS3.hair);
  let verts = 0;
  if (CS3.model) CS3.model.traverse(o => {
    if (o.isMesh && o.geometry && o.geometry.attributes.position)
      verts += o.geometry.attributes.position.count; });
  r.modelVerts = verts;
  // where the torso lands on the screenshot (device px); html{zoom:.67}
  const cv = CS3.renderer && CS3.renderer.domElement;
  if (cv) {
    const rect = cv.getBoundingClientRect();
    const k = VWPX / window.innerWidth;
    const P = (x, y) => { const v = new THREE.Vector3(x, y, 0).project(CS3.camera);
      return [rect.left + (v.x * .5 + .5) * rect.width,
              rect.top + (-v.y * .5 + .5) * rect.height]; };
    const h = CS3.height, c = P(0, h * .62), e = P(h * .085, h * .62);
    r.zoom = k;
    r.torso = {cx: c[0] * k, cy: c[1] * k, hw: Math.abs(e[0] - c[0]) * k};
    r.canvasVisible = rect.width > 10 && rect.height > 10;
  }
  return r;
}
"""

# Where the forehead and a hand land on the screenshot, in device pixels.
# The body is ONE big vertex-coloured mesh (GEO-body_*), so the landmarks are
# found geometrically rather than by node name: the extreme +x vertex is the
# right hand in the A-pose (measured: x = 0.441, y = 0.772 on a 1.69 m body) and
# the front-most vertex just under the crown is the forehead.
CS_SKIN = r"""
() => {
  let body = null;
  CS3.model.traverse(o => {
    if (o.isMesh && o.geometry && o.geometry.attributes.position &&
        (!body || o.geometry.attributes.position.count >
                  body.geometry.attributes.position.count)) body = o; });
  if (!body) return null;
  body.updateMatrixWorld(true);
  const pos = body.geometry.attributes.position, v = new THREE.Vector3();
  const box = new THREE.Box3().setFromObject(CS3.model);
  let maxX = -1e9;
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).applyMatrix4(body.matrixWorld);
    if (v.x > maxX) maxX = v.x;
  }
  let hx = 0, hy = 0, hz = 0, hn = 0, fore = null;
  const yTop = box.max.y;
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).applyMatrix4(body.matrixWorld);
    if (v.x > maxX - 0.06) { hx += v.x; hy += v.y; hz += v.z; hn++; }
    if (v.y < yTop - 0.05 && v.y > yTop - 0.20 && Math.abs(v.x) < 0.04 &&
        (!fore || v.z > fore.z)) fore = {x: v.x, y: v.y, z: v.z};
  }
  const hand = hn ? {x: hx / hn, y: hy / hn, z: hz / hn} : null;
  const cv = CS3.renderer && CS3.renderer.domElement;
  if (!cv) return {hand: hand, forehead: fore, px: null, why: 'no canvas'};
  const rect = cv.getBoundingClientRect(), k = VWPX / window.innerWidth;
  const P = p => { const w = new THREE.Vector3(p.x, p.y, p.z).project(CS3.camera);
    return [(rect.left + (w.x * .5 + .5) * rect.width) * k,
            (rect.top + (-w.y * .5 + .5) * rect.height) * k]; };
  // the mesh's own vertex colours at those two places, for the record
  const ca = body.geometry.attributes.color;
  const vc = (pred) => { if (!ca) return null;
    let r = 0, g = 0, b = 0, n = 0;
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(body.matrixWorld);
      if (!pred(v)) continue;
      r += ca.getX(i); g += ca.getY(i); b += ca.getZ(i); n++; }
    return n ? {r: +(r / n).toFixed(4), g: +(g / n).toFixed(4),
                b: +(b / n).toFixed(4), n: n} : null; };
  return {
    height: CS3.height, zoom: k, maxX: maxX, handVerts: hn,
    hand: hand, forehead: fore,
    px: {hand: hand ? P(hand) : null, forehead: fore ? P(fore) : null},
    vcol: {hand: vc(p => p.x > maxX - 0.06),
           forehead: vc(p => p.y < yTop - 0.05 && p.y > yTop - 0.20 &&
                             Math.abs(p.x) < 0.04 && p.z > 0.08)},
    canvas: {l: rect.left, t: rect.top, w: rect.width, h: rect.height}};
}
"""

CRST_PROBE = r"""
() => {
  const M = (window.CRST3 && CRST3.model) || (window.CRST3X && CRST3X.model) || null;
  const which = (window.CRST3 && CRST3.model) ? 'CRST3.model'
              : ((window.CRST3X && CRST3X.model) ? 'CRST3X.model' : null);
  if (!M) return {ready: false, global: which, hasCRST3X: !!window.CRST3X};
  let meshes = 0, verts = 0, maxMesh = 0, withCol = 0;
  M.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.position) {
    meshes++; const n = o.geometry.attributes.position.count; verts += n;
    if (n > maxMesh) maxMesh = n;
    if (o.geometry.attributes.color) withCol++; } });
  return {ready: meshes > 0 && maxMesh > 1000, global: which, type: M.type,
          isGroup: M.type === 'Group' || !!M.isGroup, meshes, verts,
          biggestMeshVerts: maxMesh, meshesWithColour: withCol,
          url: (window.CRST3X || {}).url || '', label: (window.CRST3X || {}).label || '',
          hint: (document.getElementById('crst-hint') || {}).textContent || '',
          legend: (document.getElementById('crst-3dleg') || {}).textContent || '',
          glbUrl: (CT.facts && CT.facts.mesh && CT.facts.mesh.glb_url) || '',
          meshSource: (CT.facts && CT.facts.mesh && CT.facts.mesh.source) || '',
          crstId: (window.CRST && CRST.id) || '',
          bar3d: document.querySelectorAll('[data-ct="v_3d"]').length,
          barPin: document.querySelectorAll('[data-ct="v_pin"]').length,
          barBase: document.querySelectorAll('[data-ct="v_base"]').length};
}
"""

# inject one named creature the way crstInjectApply() does, from the real list
CRST_INJECT = r"""
async (wantId) => {
  const r = await fetch('/inspect/api/creatures', {cache: 'no-store'});
  const d = await r.json();
  const list = d.creatures || [];
  const c = list.find(x => x.id === wantId);
  if (!c) return {ok: false, why: 'no creature ' + wantId, total: list.length};
  if (window.CRST) CRST.inject.list = list;
  crstLoadCreature(c);
  return {ok: true, id: c.id, name: c.name, total: list.length};
}
"""

CRST_MEAN = r"""
() => {
  const M = (window.CRST3X && CRST3X.model) || (window.CRST3 && CRST3.model);
  if (!M) return null;
  let r = 0, g = 0, b = 0, n = 0;
  M.traverse(o => { if (o.isMesh && o.geometry && o.geometry.attributes.color) {
    const a = o.geometry.attributes.color;
    for (let i = 0; i < a.count; i++) { r += a.getX(i); g += a.getY(i); b += a.getZ(i); n++; } } });
  return n ? {r: r / n, g: g / n, b: b / n, n} : null;
}
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    page_offline_checks()

    console_errors = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome', args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
        )
        pg = br.new_page(viewport={'width': VW, 'height': VH})
        pg.on('console', lambda m: console_errors.append('console.error: ' + m.text) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: console_errors.append('pageerror: ' + str(e)))
        pg.goto(URL, wait_until='load', timeout=120000)
        pg.wait_for_function('typeof CS_TOOLS !== "undefined" && typeof CT !== "undefined"', timeout=60000)
        pg.wait_for_timeout(1500)

        loaded = pg.evaluate('() => !!(window.SX && SX.ready)')
        measure('page', 'SX_present', bool(loaded))

        # ── 1. CHARACTER STUDIO ──────────────────────────────────────────────
        charstudio(pg)
        # ── 2. CREATURE STUDIO ───────────────────────────────────────────────
        creatures(pg)
        # ── 3. MOVEMENT STUDIO ───────────────────────────────────────────────
        movement(pg)
        # ── 4. MESH STUDIO ───────────────────────────────────────────────────
        mesh(pg)

        ext_errors = [e for e in console_errors if 'studio_ext' in e]
        measure('page', 'console_errors', console_errors[:25])
        measure('page', 'console_errors_total', len(console_errors))
        check('page', "no console error mentions 'studio_ext'", not ext_errors, ext_errors[:5])
        br.close()

    RES['pass'] = not RES['failures']
    path = os.path.join(OUT, 'acceptance.json')
    with open(path, 'w') as f:
        json.dump(RES, f, indent=2, sort_keys=False)
    print('\nwrote ' + path)
    print('RESULT %s — %d failure(s)' % ('PASS' if RES['pass'] else 'FAIL', len(RES['failures'])))
    for f_ in RES['failures']:
        print('   ! ' + f_)
    return 0 if RES['pass'] else 1


# ── studio 1: Character Studio ───────────────────────────────────────────────
def charstudio(pg):
    pg.evaluate("() => { location.hash='charstudio'; switchView('charstudio'); }")
    pg.wait_for_function('!!(window.CS3 && CS3.model && CS3.hair)', timeout=120000)
    pg.wait_for_timeout(2500)

    a = pg.evaluate(CS_PROBE.replace('VWPX', str(VW)))
    measure('charstudio', 'default', a)
    check('charstudio', '.cst-tool.stub count == 0', a['stubs'] == 0, {'stub': a['stubs'], 'tools': a['tools']})
    check(
        'charstudio',
        "#cs-credit does not say 'inject a character'",
        'inject a character' not in (a['credit'] or '').lower(),
        {'credit': (a['credit'] or '')[:160]},
    )
    check(
        'charstudio',
        'CS3.model loaded',
        a['modelLoaded'] and a['modelVerts'] > 1000,
        {'type': a['modelType'], 'verts': a['modelVerts'], 'id': a['modelId']},
    )
    check(
        'charstudio',
        'CS3.hair exists with >= 1 child',
        a['hairExists'] and a['hairChildren'] >= 1,
        {'hair': a['hairExists'], 'children': a['hairChildren'], 'length': a['hairLength']},
    )
    check('charstudio', 'CS3.dress exists', a['dressExists'], {'children': a['dressChildren']})

    # the jaw tool opens its own field panel
    pg.click('[data-cstool="jaw"]')
    pg.wait_for_selector('#cst-panel.on', timeout=15000)
    pg.wait_for_timeout(400)
    jaw = pg.evaluate("""() => ({
        on: document.getElementById('cst-panel').classList.contains('on'),
        title: (document.getElementById('cst-panel-title')||{}).textContent||'',
        body: (document.getElementById('cst-panel')||{}).textContent||''})""")
    measure('charstudio', 'jaw_panel', {'title': jaw['title'], 'body_head': jaw['body'][:180]})
    check(
        'charstudio',
        "jaw tool opens #cst-panel.on with 'appearance.jaw'",
        jaw['on'] and 'appearance.jaw' in jaw['body'],
        {'on': jaw['on'], 'has_path': 'appearance.jaw' in jaw['body']},
    )

    # the wardrobe-colour tool is three colour editors behind one icon
    pg.click('[data-cstool="wardrobecol"]')
    pg.wait_for_selector('#cst-panel.on', timeout=15000)
    pg.wait_for_timeout(400)
    cols = pg.evaluate("""() => ({
        colour: document.querySelectorAll('#cst-panel input[type=color]').length,
        paths: Array.from(document.querySelectorAll('#cst-panel .cst-path'))
                    .map(e => e.textContent)})""")
    measure('charstudio', 'wardrobecol', cols)
    check('charstudio', 'wardrobe colour tool draws three colour inputs', cols['colour'] == 3, cols)

    # inject the first character of the library
    inj = pg.evaluate("""async () => {
      const r = await fetch('/inspect/api/list', {cache: 'no-store'});
      const d = await r.json();
      const s = (d.sheets || [])[0];
      if (!s) throw new Error('/inspect/api/list has no sheets');
      if (window.STATE && Array.isArray(STATE.list) && !STATE.list.length)
        STATE.list = d.sheets;
      csLoadChar(s);
      return {id: s.id, name: s.name, total: (d.sheets || []).length};
    }""")
    measure('charstudio', 'injected', inj)
    pg.wait_for_function('() => !!(window.CS && CS.charId)', timeout=60000)
    pg.wait_for_timeout(3000)
    check('charstudio', 'first library character injected', bool(inj['id']), inj)

    skin_checks(pg)

    # stage the three fields through the real cstStageField path
    staged = []
    for path, val in (
        ('identity.hair_length', 'long'),
        ('wardrobe.headwear', 'hat'),
        ('wardrobe.colour_top', '#aa2222'),
    ):
        staged.append(pg.evaluate(STAGE_JS, {'path': path, 'val': val}))
    measure('charstudio', 'staged', staged)
    check('charstudio', 'all three fields staged via cstStageField', all(s.get('ok') for s in staged), staged)
    pg.evaluate('() => { cstPanelClose && cstPanelClose(); }')
    pg.wait_for_timeout(3000)

    b = pg.evaluate(CS_PROBE.replace('VWPX', str(VW)))
    measure('charstudio', 'staged_state', b)
    shot = os.path.join(OUT, 'final2_charstudio.png')
    pg.screenshot(path=shot)
    measure('charstudio', 'screenshot', shot)
    _zyg_log.info('SHOT  ' + shot)

    below = (b.get('hairBox') or {}).get('minY')
    sh_y = b.get('shoulderY')
    check(
        'charstudio',
        'long hair reaches below the shoulder',
        below is not None and sh_y is not None and below < sh_y,
        {'hair_minY': below, 'shoulderY': sh_y, 'length': b.get('hairLength')},
    )
    check(
        'charstudio',
        'CS3.dress has >= 2 children with a hat + top staged',
        b['dressChildren'] >= 2,
        {'children': b['dressChildren'], 'before': None},
    )

    if b.get('torso'):
        rgb, box = mean_rgb(shot, b['torso']['cx'], b['torso']['cy'], b['torso']['hw'], b['torso']['hw'])
        redness = None if not rgb else round(rgb[0] - (rgb[1] + rgb[2]) / 2, 2)
        measure('charstudio', 'torso_mean_rgb', {'rgb': rgb, 'box': box, 'redness': redness})
        check(
            'charstudio',
            'torso mean colour is red-dominant',
            bool(rgb) and rgb[0] > rgb[1] and rgb[0] > rgb[2],
            {'rgb': rgb, 'redness': redness},
        )
    else:
        check('charstudio', 'torso mean colour is red-dominant', False, 'no renderer canvas to project the torso onto')

    rev = pg.evaluate('() => { cstRevertAll(); return Object.keys(CST.dirty).length; }')
    pg.wait_for_timeout(1500)
    measure('charstudio', 'reverted_dirty_keys', rev)
    check('charstudio', 'cstRevertAll() dropped every staged edit', rev == 0, rev)


# ── the skin sample: the r144 washout showed up as white hands ───────────────
def skin_checks(pg):
    """Forehead and hand, 40x40 device-pixel patches on the injected character.
    A washed-out (linear hex written straight onto a vertex colour) body reads
    near-white, so the two tests are: no channel mean above 245, and R > B."""
    lm = pg.evaluate(CS_SKIN.replace('VWPX', str(VW)))
    measure('charstudio', 'skin_landmarks', lm)
    shot = os.path.join(OUT, 'final2_charstudio_skin.png')
    pg.screenshot(path=shot)
    measure('charstudio', 'skin_screenshot', shot)
    _zyg_log.info('SHOT  ' + shot)

    px = (lm or {}).get('px') or {}
    for name in ('forehead', 'hand'):
        p = px.get(name)
        if not p:
            check(
                'charstudio',
                '%s 40x40 patch reads as skin' % name,
                False,
                {'why': 'no projection for ' + name, 'landmarks': lm},
            )
            continue
        rgb, box = mean_rgb(shot, p[0], p[1], 20, 20)
        meas = {
            'rgb': rgb,
            'box': box,
            'centre': [round(p[0], 1), round(p[1], 1)],
            'max_channel': (max(rgb) if rgb else None),
            'r_minus_b': (round(rgb[0] - rgb[2], 2) if rgb else None),
        }
        measure('charstudio', 'skin_%s' % name, meas)
        check('charstudio', '%s 40x40 patch: no channel mean above 245' % name, bool(rgb) and max(rgb) <= 245, meas)
        check('charstudio', '%s 40x40 patch: R > B (skin, not white/grey)' % name, bool(rgb) and rgb[0] > rgb[2], meas)


# ── studio 2: Creature Studio ────────────────────────────────────────────────
def creatures(pg):
    pg.evaluate("() => { location.hash='creatures'; switchView('creatures'); }")
    st = None
    for _ in range(80):
        st = pg.evaluate(CRST_PROBE)
        if st.get('ready'):
            break
        pg.wait_for_timeout(500)
    measure('creatures', 'default', st)
    check(
        'creatures',
        'base creature is a Group with a mesh > 1000 vertices',
        bool(st and st.get('ready') and st.get('isGroup')),
        {
            'global': st.get('global'),
            'type': st.get('type'),
            'meshes': st.get('meshes'),
            'biggest': st.get('biggestMeshVerts'),
            'verts': st.get('verts'),
        },
    )
    # the DEFAULT pane (nothing injected) must be a third-party CC0 stand-in
    hint = st.get('hint', '') if st else ''
    low = hint.lower()
    credits = [w for w in ('quaternius', 'kenney', 'smithsonian') if w in low]
    measure('creatures', 'default_hint', hint[:240])
    check(
        'creatures',
        '#crst-hint credits Quaternius / Kenney / Smithsonian',
        bool(credits),
        {'hint': hint[:200], 'credits': credits},
    )
    check(
        'creatures', "the default #crst-hint does not say 'Pufferball'", 'pufferball' not in low, {'hint': hint[:200]}
    )
    check(
        'creatures',
        'v_3d, v_pin and v_base all in the bars',
        st.get('bar3d', 0) >= 1 and st.get('barPin', 0) >= 1 and st.get('barBase', 0) >= 1,
        {'v_3d': st.get('bar3d'), 'v_pin': st.get('barPin'), 'v_base': st.get('barBase')},
    )

    before = pg.evaluate(CRST_MEAN)
    pg.evaluate("() => { ctAdd('cc_base'); ctSet(0, 'col', '#0044ff', false); }")
    pg.wait_for_timeout(2000)
    after = pg.evaluate(CRST_MEAN)
    measure('creatures', 'colour_mean_before', before)
    measure('creatures', 'colour_mean_after_blue', after)
    check(
        'creatures',
        'cc_base #0044ff makes the mesh colour blue-dominant',
        bool(after) and after['b'] > after['r'] and after['b'] > after['g'],
        after,
    )

    shot = os.path.join(OUT, 'final2_creatures.png')
    pg.screenshot(path=shot)
    measure('creatures', 'screenshot', shot)
    _zyg_log.info('SHOT  ' + shot)
    pg.evaluate('() => { try { ctClear(); } catch (e) {} }')
    pg.wait_for_timeout(600)

    # ── injecting our own creature must switch to ITS mesh, not the base ──────
    inj = pg.evaluate(CRST_INJECT, 'd0e44ab002ad')
    measure('creatures', 'injected', inj)
    check('creatures', 'd0e44ab002ad is in /inspect/api/creatures', bool(inj.get('ok')), inj)
    own = {}
    if inj.get('ok'):
        for _ in range(80):
            own = pg.evaluate(CRST_PROBE)
            if own.get('glbUrl') and 'own mesh' in (own.get('hint') or '').lower():
                break
            pg.wait_for_timeout(500)
        measure('creatures', 'own_mesh', own)
        check(
            'creatures',
            'the injected creature carries its own glb_url',
            bool(own.get('glbUrl')),
            {'glb_url': own.get('glbUrl'), 'source': own.get('meshSource'), 'crst_id': own.get('crstId')},
        )
        check(
            'creatures',
            "#crst-hint says 'Own mesh' once d0e44ab002ad is in",
            'own mesh' in (own.get('hint') or '').lower(),
            {'hint': (own.get('hint') or '')[:200]},
        )
        check(
            'creatures',
            'the own mesh really loaded (a mesh > 1000 verts)',
            bool(own.get('ready')),
            {'meshes': own.get('meshes'), 'biggest': own.get('biggestMeshVerts'), 'url': own.get('url')},
        )
        shot2 = os.path.join(OUT, 'final2_creatures_own.png')
        pg.screenshot(path=shot2)
        measure('creatures', 'screenshot_own', shot2)
        _zyg_log.info('SHOT  ' + shot2)


# ── studio 3: Movement Studio ────────────────────────────────────────────────
def movement(pg):
    pg.evaluate("() => { location.hash='movement'; switchView('movement'); }")
    pg.wait_for_timeout(4000)
    mv = pg.evaluate("""() => ({
        extract: typeof moTrackExtract,
        visible: (() => { const v = document.getElementById('view-movement');
                          return v ? getComputedStyle(v).display : 'missing'; })(),
        tools: document.querySelectorAll('[data-mo]').length})""")
    measure('movement', 'page', mv)
    check('movement', "typeof moTrackExtract === 'function'", mv['extract'] == 'function', mv)
    shot = os.path.join(OUT, 'final2_movement.png')
    pg.screenshot(path=shot)
    measure('movement', 'screenshot', shot)
    _zyg_log.info('SHOT  ' + shot)


# ── studio 4: Mesh Studio ────────────────────────────────────────────────────
def mesh(pg):
    nav = pg.evaluate("""() => (document.querySelector('[data-view="mesh"]')||{}).textContent||''""")
    measure('mesh', 'nav_label', nav)
    check('mesh', "the nav button says 'Mesh Studio'", 'Mesh Studio' in nav, {'label': nav.strip()})

    pg.evaluate("() => { location.hash='mesh'; switchView('mesh'); }")
    pg.wait_for_function("document.querySelectorAll('.msh-tool').length > 0", timeout=60000)
    pg.wait_for_timeout(1200)
    counts = pg.evaluate("""() => ({
        all: document.querySelectorAll('.msh-tool').length,
        ph: document.querySelectorAll('.msh-tool.ph').length,
        foot_scrollW: document.getElementById('msh-dock').scrollWidth,
        foot_clientW: document.getElementById('msh-dock').clientWidth})""")
    measure('mesh', 'tools', counts)
    check('mesh', '.msh-tool count == 186', counts['all'] == 186, counts['all'])
    check('mesh', '.msh-tool.ph count == 186', counts['ph'] == 186, counts['ph'])
    check(
        'mesh',
        'foot dock does not scroll sideways',
        counts['foot_scrollW'] <= counts['foot_clientW'] + 2,
        {
            'scrollW': counts['foot_scrollW'],
            'clientW': counts['foot_clientW'],
            'overflow': counts['foot_scrollW'] - counts['foot_clientW'],
        },
    )

    # picker → first mesh onto the studio stage
    pg.evaluate('mshOpenPicker()')
    pg.wait_for_selector('#msh-picker.on', timeout=20000)
    pg.wait_for_function("document.querySelectorAll('#msh-iboard .mesh-card').length > 0", timeout=60000)
    cards = pg.eval_on_selector_all('#msh-iboard .mesh-card', 'x => x.length')
    pg.eval_on_selector_all('#msh-iboard .mesh-card', 'x => x[0].click()')
    pg.click('#msh-igo')
    pg.wait_for_function('!!(window.MS && MS.rec)', timeout=60000)
    pg.wait_for_timeout(2500)
    opened = pg.evaluate("""() => ({
        cards: document.querySelectorAll('#msh-iboard .mesh-card').length,
        rec: !!MS.rec, name: MS.name || '', mode: MS.mode || '',
        d3: getComputedStyle(document.getElementById('msh-3d')).display,
        viewer: document.getElementById('mesh-viewer').style.display})""")
    opened['picker_cards'] = cards
    measure('mesh', 'opened', opened)
    check('mesh', 'picker opens a mesh: MS.rec set', opened['rec'], {'name': opened['name'], 'cards': cards})
    check(
        'mesh',
        '#msh-3d displayed for the opened mesh',
        opened['d3'] != 'none',
        {'display': opened['d3'], 'mode': opened['mode']},
    )

    # let the open-toast clear so the shot shows the bars, then shoot
    try:
        pg.wait_for_function("document.getElementById('msh-toast').style.display === 'none'", timeout=20000)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('mesh toast did not clear in time, shooting anyway: %s', _exc)
    pg.wait_for_timeout(800)
    shot = os.path.join(OUT, 'final2_mesh.png')
    pg.screenshot(path=shot)
    measure('mesh', 'screenshot', shot)
    _zyg_log.info('SHOT  ' + shot)

    # the Library tab's mesh card still opens the full-screen viewer
    pg.evaluate("() => { location.hash='library'; switchView('inspections'); }")
    pg.wait_for_timeout(1500)
    pg.evaluate("() => libOpenCat('mesh')")
    lib = {'cards': 0, 'viewer': 'none'}
    try:
        pg.wait_for_function("document.querySelectorAll('#lib-board .mesh-card').length > 0", timeout=60000)
        lib['cards'] = pg.eval_on_selector_all('#lib-board .mesh-card', 'x => x.length')
        pg.eval_on_selector_all('#lib-board .mesh-card', 'x => x[0].click()')
        pg.wait_for_timeout(1500)
        lib['viewer'] = pg.evaluate("() => document.getElementById('mesh-viewer').style.display")
    except Exception as e:  # noqa: BLE001
        lib['error'] = str(e)[:200]
    measure('mesh', 'library_card', lib)
    check('mesh', "the Library tab's mesh card still opens #mesh-viewer", lib['viewer'] == 'flex', lib)
    pg.evaluate('() => { try { mvClose(); } catch (e) {} }')


if __name__ == '__main__':
    sys.exit(main())
