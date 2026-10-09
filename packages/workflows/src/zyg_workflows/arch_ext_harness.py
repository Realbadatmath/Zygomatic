# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_ext_harness.py — the shared proof kit for Architecture Studio extension
families (2026-09-06). Every tests_arch_ext/test_<family>.py imports this and
checks three things that can each be right while the others are wrong:

  · THE ASSISTANT (Python, no model): its tools produce the records claimed.
  · THE TAB (headless Chrome, SwiftShader): every new kind builds real
    geometry through arGeom, sized as the parameters say, and shows in the
    library rail.
  · BLENDER (headless): every new kind builds a mesh with faces.

Use:
    from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_kinds, blender_kinds, rail_has
    ...
    finish()            # prints ALL GREEN / N FAILED and exits accordingly

The GUI on :8899 must be running for browser_kinds/rail_has (it always is —
kanban-server.service). Blender is /usr/local/bin/blender.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import logging as _zyg_logging

from zyg_workflows.paths import BLENDER_BIN, ZYG_KANBAN_URL, ZYG_TMP_DIR, tmp_dir

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_KANBAN_BASE = ZYG_KANBAN_URL.rstrip('/')
URL = f'{_KANBAN_BASE}/inspection.html#architecture'
BLENDER = str(BLENDER_BIN)
FAILS: list[str] = []
_N = [0]


def check(name: str, ok, detail='') -> bool:
    _N[0] += 1
    ok = bool(ok)
    _zyg_log.info(('  ok   ' if ok else '  FAIL ') + name + (('  — ' + str(detail)[:400]) if detail and not ok else ''))
    if not ok:
        FAILS.append(name)
    return ok


def finish():
    _zyg_log.info(
        ('\nALL GREEN (%d checks)' % _N[0]) if not FAILS else ('\n%d FAILED: ' % len(FAILS) + ', '.join(FAILS))
    )
    sys.exit(1 if FAILS else 0)


# ── the assistant ─────────────────────────────────────────────────────────────
def assistant(tool: str, args: dict, doc: dict | None = None, drawing=None):
    """Run ONE assistant tool. Returns (result_text, Drawing). Pass `drawing`
    back in to chain calls on the same document."""
    from zyg_workflows import arch_assistant as A

    d = drawing if drawing is not None else A.Drawing(doc or {'objects': []})
    return A.call_tool(d, tool, args), d


def kinds_of(d) -> dict:
    out: dict = {}
    for o in d.objs:
        out[o['kind']] = out.get(o['kind'], 0) + 1
    return out


def tool_names() -> list:
    from zyg_workflows import arch_assistant as A

    return [t['name'] for t in A.TOOL_DEFS]


# ── the rail ──────────────────────────────────────────────────────────────────
def rail_has(kinds: list) -> list:
    """Kinds from `kinds` that the library rail does NOT list (via the live
    catalogue merge, no server round trip)."""
    from zyg_workflows import architecture_studio as st

    have = set()
    for sec in st.library()['sections']:
        for g in sec.get('groups') or []:
            for it in g.get('items') or []:
                have.add(it.get('kind'))
    return [k for k in kinds if k not in have]


# ── the tab ───────────────────────────────────────────────────────────────────
_BROWSER_SCRIPT = r"""
(cases) => {
  window.confirm = () => true; window.prompt = (q, d) => d || '1';
  const out = [];
  for (const c of cases) {
    const r = {kind: c.kind, ok: false, size: null, tris: 0, parts: 0, err: '', label: '', vcolors: false, registered: !!(window.AR_EXT && AR_EXT.geom[c.kind])};
    const extra = [];
    try {
      /* 2026-09-07 (v3): a case may carry `others` — full record dicts injected
         BEFORE the case record and removed after. A `ground` record's geometry is
         a function of the sculpts around it, so it cannot be tested alone. */
      for (const o of (c.others || [])) {
        const e = arNewObj(o.kind, o.p || {}, o.x || 0, o.z || 0, o.y || 0);
        e.rx = o.rx || 0; e.ry = o.ry || 0; e.rz = o.rz || 0; e.s = o.s || 1;
        if (o.mat) e.mat = o.mat;
        arApplyTransform(e);
        extra.push(e);
      }
      const rec = arNewObj(c.kind, c.p || {}, 0, 0, 0);
      if (c.rx || c.ry || c.rz) {            /* 2026-09-07: a case may carry a record rotation */
        rec.rx = c.rx || 0; rec.ry = c.ry || 0; rec.rz = c.rz || 0;
        rec.node.rotation.set(rec.rx, rec.ry, rec.rz); rec.node.updateMatrixWorld(true);
      }
      const box = new THREE.Box3().expandByObject(rec.node);
      const s = box.getSize(new THREE.Vector3());
      let tris = 0, parts = 0, vcol = false;
      rec.node.traverse(m => { if (m.isMesh && m.geometry) { parts++; const g = m.geometry; if (g.attributes && g.attributes.color) vcol = true; tris += g.index ? g.index.count / 3 : (g.attributes.position ? g.attributes.position.count / 3 : 0); } });
      r.size = [s.x, s.y, s.z].map(v => Math.round(v * 1000) / 1000);
      r.min = [box.min.x, box.min.y, box.min.z].map(v => Math.round(v * 1000) / 1000);
      r.tris = tris; r.parts = parts; r.label = arKindLabel(c.kind); r.vcolors = vcol;
      /* the unknown-kind marker is a 0.5 m cube with 12 triangles: that is NOT geometry for the kind */
      r.ok = tris > 0 && !(parts === 1 && tris === 12 && Math.abs(s.x - 0.5) < 1e-6 && Math.abs(s.y - 0.5) < 1e-6 && Math.abs(s.z - 0.5) < 1e-6 && !r.registered);
      arRemove(rec);
    } catch (e) { r.err = String(e && e.message || e); }
    for (const e of extra) { try { arRemove(e); } catch (x) {} }
    out.push(r);
  }
  arSelSync(); arHud();
  return out;
}
"""


def browser_kinds(cases: list, timeout_s: int = 120) -> list:
    """cases: [{'kind': 'wall_arc', 'p': {...}}, ...] -> per case:
    {kind, ok, size:[x,y,z], min:[x,y,z], tris, parts, label, registered, err}.
    Geometry is built through arGeom exactly as the studio does it."""
    from playwright.sync_api import sync_playwright

    errs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda d: d.accept())
        page.goto(URL, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=timeout_s * 1000)
        page.evaluate('AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false;')
        out = page.evaluate(_BROWSER_SCRIPT, cases)
        browser.close()
    for r in out:
        if errs:
            r['page_errors'] = errs[:3]
    return out


# ── Blender ───────────────────────────────────────────────────────────────────
_POLY_EXPR = (
    'import bpy,json\n'
    'def bb(o):\n'
    '    pts=[o.matrix_world @ v.co for v in o.data.vertices]\n'
    '    if not pts: return [0,0,0], 0\n'
    '    xs=[p.x for p in pts]; ys=[p.y for p in pts]; zs=[p.z for p in pts]\n'
    '    # blender (x, y, z) = (studio x, -studio z, studio y): report studio [sx, sy_up, sz], min studio y\n'
    '    return [round(max(xs)-min(xs),4), round(max(zs)-min(zs),4), round(max(ys)-min(ys),4)], round(min(zs)-o.location.z,4)\n'
    'out={}\n'
    'for o in bpy.data.objects:\n'
    "    if o.type=='MESH':\n"
    '        s,m=bb(o)\n'
    "        vc=bool(getattr(o.data,'color_attributes',None) and len(o.data.color_attributes))\n"
    "        out[o.get('studio_id', o.name)]=[len(o.data.polygons), len(o.data.vertices), s, m, vc]\n"
    "print('POLYS ' + json.dumps(out))"
)


class _BlenderLock:
    """Blender runs are SERIALISED across processes. Twenty-four family tests
    finishing at once each launched two headless Blenders; under that load the
    Bonsai extension's import crashed with SIGBUS and four green families were
    marked failed by the board's verify. One at a time is a few seconds each."""

    # Every holder of this lock derives the path the same way, so they still meet in one file;
    # tmp_dir() creates the directory owner-only instead of the old world-writable /tmp path.
    PATH = str(ZYG_TMP_DIR / 'arch_ext_blender.lock')

    def __enter__(self):
        import fcntl

        tmp_dir()
        self.fh = open(self.PATH, 'w')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        import fcntl

        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def _blender(cmd, timeout_s):
    with _BlenderLock():
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)


def blender_kinds(cases: list, timeout_s: int = 600) -> dict:
    """cases: [{'kind','p'}] -> {kind: {'polys': n, 'verts': n, 'name': ...}} after a
    real headless build through arch_blender_build.py. Missing kind = it did
    not build. Records are laid out 20 m apart so nothing overlaps."""
    objs = []
    for i, c in enumerate(cases):
        cx, cz = (i % 10) * 20.0, (i // 10) * 20.0
        # `others` (2026-09-07, v3): extra records that go into the doc with the
        # case, placed RELATIVE to it — a `ground` record is a function of the
        # sculpts around it and cannot be built alone. They are reported like any
        # other object under their own id, never under the case's kind.
        for j, o in enumerate(c.get('others') or []):
            objs.append(
                {
                    'id': f'o{i + 1}x{j + 1}',
                    'kind': o['kind'],
                    'name': o['kind'],
                    'p': o.get('p') or {},
                    'x': cx + float(o.get('x') or 0),
                    'y': float(o.get('y') or 0),
                    'z': cz + float(o.get('z') or 0),
                    'rx': o.get('rx', 0),
                    'ry': o.get('ry', 0),
                    'rz': o.get('rz', 0),
                    's': o.get('s', 1),
                    'mat': o.get('mat') or 'mat_concrete',
                    'hidden': bool(o.get('hidden')),
                    'grp': '',
                }
            )
        objs.append(
            {
                'id': f'o{i + 1}',
                'kind': c['kind'],
                'name': c['kind'],
                'p': c.get('p') or {},
                'x': cx,
                'y': 0.0,
                'z': cz,
                'rx': c.get('rx', 0),
                'ry': c.get('ry', 0),
                'rz': c.get('rz', 0),
                's': 1,
                'mat': c.get('mat') or 'mat_concrete',
                'hidden': False,
                'grp': '',
            }
        )
    tmp = tempfile.mkdtemp(prefix='arch_ext_')
    src, blend = os.path.join(tmp, 'in.json'), os.path.join(tmp, 'out.blend')
    with open(src, 'w', encoding='utf-8') as fh:
        json.dump({'name': 'ext test', 'units': 'm', 'objects': objs}, fh)
    p = _blender(
        [
            BLENDER,
            '-b',
            '--python',
            os.path.join(HERE, 'arch_blender_build', '__main__.py'),
            '--',
            '--in',
            src,
            '--out',
            blend,
        ],
        timeout_s,
    )
    last = [l for l in (p.stdout or '').splitlines() if l.startswith('{')]
    info = json.loads(last[-1]) if last else {}
    if p.returncode != 0 or not info.get('ok'):
        raise RuntimeError('blender build failed: ' + (info.get('error') or (p.stderr or p.stdout)[-400:]))
    q = _blender([BLENDER, '-b', blend, '--python-expr', _POLY_EXPR], timeout_s)
    line = [l for l in (q.stdout or '').splitlines() if l.startswith('POLYS ')]
    polys = json.loads(line[-1][6:]) if line else {}
    out = {}
    for i, c in enumerate(cases):
        sid = f'o{i + 1}'
        pv = polys.get(sid)
        if pv:
            # bbox = WORLD-space size [x, y_up, z] and min y (studio frame), rotation applied
            out[c['kind']] = {
                'polys': pv[0],
                'verts': pv[1],
                'id': sid,
                'size': pv[2] if len(pv) > 2 else None,
                'min_y': pv[3] if len(pv) > 3 else None,
                'vcol': bool(pv[4]) if len(pv) > 4 else False,
            }
    out['_info'] = info
    return out


def save_render(d, path: str, view: str = 'iso', engine: str = 'eevee', width: int = 1600, height: int = 900) -> str:
    """Render a Drawing through the assistant's blender_render tool and write the PNG to
    `path`. Returns the tool's text. For visual QA and the operator's gallery."""
    import base64
    from zyg_workflows import arch_assistant as A

    r = A.call_tool(d, 'blender_render', {'view': view, 'engine': engine, 'width': width, 'height': height})
    txt = r[0] if isinstance(r, tuple) else r
    if not d.images:
        raise RuntimeError('no render: ' + str(txt)[:300])
    url = d.images[-1]['data_url']
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(base64.b64decode(url.split(',', 1)[1]))
    return str(txt)


def blender_doc(doc: dict, timeout_s: int = 600) -> dict:
    """Build a whole drawing; returns the builder's JSON line ({ok, objects, skipped, ...})."""
    tmp = tempfile.mkdtemp(prefix='arch_ext_')
    src, blend = os.path.join(tmp, 'in.json'), os.path.join(tmp, 'out.blend')
    with open(src, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)
    p = _blender(
        [
            BLENDER,
            '-b',
            '--python',
            os.path.join(HERE, 'arch_blender_build', '__main__.py'),
            '--',
            '--in',
            src,
            '--out',
            blend,
        ],
        timeout_s,
    )
    last = [l for l in (p.stdout or '').splitlines() if l.startswith('{')]
    info = json.loads(last[-1]) if last else {'ok': False, 'error': (p.stderr or p.stdout)[-400:]}
    info['blend'] = blend
    return info


# ── the icon seam (2026-09-07): press icons, run tab code, call server ops ──
def browser_eval(js: str, doc: dict | None = None, timeout_s: int = 120, shots: bool = False):
    """Open the live tab headless, optionally inject `doc` ({'objects': [...]},
    quietly, no undo step), then run `js` — the SOURCE of a function that takes
    no argument, e.g. "() => { arTool('e_align'); return AR.sel.length; }" — and
    return {'value': <its JSON-able result>, 'errors': [page errors], 'console': [error lines],
    'http_errors': ['<status> <METHOD> <url>' for every response with status >= 400]}.
    window.prompt returns its default (or '1'), window.confirm true, so an icon
    that asks a question still runs; pass an `args` object to an extension icon
    with arTool(id, {...}) to answer it exactly. Shadows are off (software GL).
    A dialog-free `arShot(640)` returns a jpeg data-url if you need to LOOK."""
    from playwright.sync_api import sync_playwright

    errs: list = []
    cons: list = []
    https: list = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('console', lambda m: cons.append(m.text) if m.type == 'error' else None)
        page.on('dialog', lambda d: d.accept())
        page.on(
            'response',
            lambda r: https.append('%s %s %s' % (r.status, r.request.method, r.url)) if r.status >= 400 else None,
        )
        page.goto(URL, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=timeout_s * 1000)
        page.evaluate(
            'AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false; '
            'window.confirm = () => true; window.prompt = (q, d) => (d === undefined || d === null) ? "1" : String(d);'
        )
        # let the tab's enter animation settle so layout measurements are honest
        try:
            page.wait_for_function('document.getAnimations().every(a => a.playState !== "running")', timeout=5000)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('animation settle wait timed out: %s', _exc)
        if doc is not None:
            page.evaluate(
                '(d) => { AR._quiet = true; arInjectDoc(d.objects || [], {sync: true}); '
                'if (d.ext) AR.doc.ext = d.ext; AR._quiet = false; arSelSync(); arOutliner(); arPanel(); arHud(); }',
                doc,
            )
        value = page.evaluate('(src) => { const f = (0, eval)(src); return Promise.resolve(f()); }', js)
        browser.close()
    return {'value': value, 'errors': errs, 'console': cons, 'http_errors': https}


def icon_state(ids: list) -> dict:
    """{id: {'exists', 'stub', 'on', 'section', 'bar'}} straight from the live tab's
    AR_TOOLS after arToolsRender — the proof that an icon stopped being a placeholder."""
    r = browser_eval(
        '() => { arToolsRender(); const out = {}; for (const id of %s) { '
        'let f = null, sec = null; for (const s of AR_TOOLS) for (const t of s.items) if (t.id === id) { f = t; sec = s; } '
        'const el = document.querySelector(".ar-tool[data-tool=\\"" + id + "\\"]"); '
        'out[id] = f ? {exists: true, stub: !!f.stub, on: !!arToolOn(f), section: sec.sec, bar: sec.bar, '
        'dashed: !!(el && el.classList.contains("stub")), tip_placeholder: /\\[placeholder\\]/.test(el ? el.getAttribute("title") || "" : "")} '
        ': {exists: false}; } return out; }' % json.dumps(list(ids))
    )
    return r['value']


def server_ext(family: str, op: str, payload: dict | None = None, method: str = 'POST', timeout_s: int = 120):
    """Call /inspect/api/architecture/ext/<family>/<op> on the live server.
    Returns the parsed JSON for a JSON reply, or {'bytes': b'..', 'mime': .., 'filename': ..}
    for a download."""
    import urllib.request
    import urllib.parse

    # ZYG_KANBAN_URL comes from the environment, so its scheme is checked here; family/op only
    # ever land in the path, so no input can turn these three calls into a custom-scheme open.
    if not _KANBAN_BASE.startswith(('http://', 'https://')):
        raise ValueError(f'ZYG_KANBAN_URL must be http(s): {_KANBAN_BASE!r}')
    base = '%s/inspect/api/architecture/ext/%s/%s' % (_KANBAN_BASE, family, op)
    if method == 'GET':
        url = base + ('?' + urllib.parse.urlencode(payload) if payload else '')
        req = urllib.request.Request(url)  # noqa: S310  http(s) base checked just above
    else:
        req = urllib.request.Request(  # noqa: S310  http(s) base checked just above
            base,
            data=json.dumps(payload or {}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:  # nosec B310  # noqa: S310  req holds that literal URL
            data = r.read()
            ct = r.headers.get('Content-Type', '')
            cd = r.headers.get('Content-Disposition', '')
    except urllib.error.HTTPError as e:
        data = e.read()
        ct = e.headers.get('Content-Type', '')
        cd = ''
        try:
            out = json.loads(data.decode('utf-8'))
        except Exception:  # noqa: BLE001
            out = {'error': data[:200].decode('utf-8', 'replace')}
        out.setdefault('code', e.code)
        return out
    if 'json' in ct:
        return json.loads(data.decode('utf-8'))
    fname = ''
    if 'filename=' in cd:
        fname = cd.split('filename=', 1)[1].strip().strip('"')
    return {'bytes': data, 'mime': ct, 'filename': fname}
