# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_view_camera.py — proves the four camera/animation icons
of arch_ext/view_camera.js are real:

  v_2pt        the projection really keeps verticals vertical (equal NDC x for
               the top and the bottom of a vertical edge) while the camera is
               pitched 30 degrees down, and the original target stays framed
  v_turntable  a 1 s / 10 fps / 640 px orbit comes back as a WebM Blob
  v_walkpath   record -> stop -> play: keys land in AR.doc.ext.view_camera.path
               and the camera ends on the last key
  r_anim       a 3-key path renders to one WebM at 320 px and the settings are
               remembered in AR.doc.ext.view_camera.anim

Three browser_eval calls (icon_state is the first), no Blender, no GPU.
Run: "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_view_camera.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['v_2pt', 'v_turntable', 'v_walkpath', 'r_anim']

# ── 1. the placeholder mark is gone in the live tab ──────────────────────────
st = icon_state(IDS)
for _id in IDS:
    s = st.get(_id) or {}
    check(
        '%s is wired: exists, no stub flag, no dashed border, no [placeholder] tip' % _id,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. two-point perspective + the walk path (one page) ──────────────────────
r1 = browser_eval("""async () => {
  const out = {};
  const M = () => new THREE.Matrix4().multiplyMatrices(AR.cam.projectionMatrix, AR.cam.matrixWorldInverse);
  const ndc = (m, x, y, z) => { const v = new THREE.Vector3(x, y, z); v.applyMatrix4(m); return [v.x, v.y]; };

  // camera 30 degrees down: horizontal run 10 m, drop 10*tan30 = 5.7735 m
  const place = () => { AR.controls.target.set(0, 0, 0); AR.cam.position.set(6, 5.7735026919, 8);
                        AR.controls.update(); arTick(); };

  AR_EXT.tools.v_2pt.act({on: false}); place();
  let m = M();
  out.off = {edge0: [ndc(m, 0, 0, 0)[0], ndc(m, 0, 10, 0)[0]],
             edge7: [ndc(m, 7, 0, 0)[0], ndc(m, 7, 10, 0)[0]],
             rotx: AR.cam.rotation.x, e9: AR.cam.projectionMatrix.elements[9]};

  arTool('v_2pt');                       // pressed like a person presses it
  place();
  m = M();
  out.on = {edge0: [ndc(m, 0, 0, 0)[0], ndc(m, 0, 10, 0)[0]],
            edge7: [ndc(m, 7, 0, 0)[0], ndc(m, 7, 10, 0)[0]],
            tgtY: ndc(m, 0, 0, 0)[1],
            rotx: AR.cam.rotation.x, e9: AR.cam.projectionMatrix.elements[9],
            latched: !!AR_EXT.tools.v_2pt.on()};
  arTool('v_2pt');                       // and off again
  out.offAgain = !AR_EXT.tools.v_2pt.on();

  // ── walk path: record, two hand-driven keys, stop, play ──
  const W = AR_EXT.tools.v_walkpath;
  W.act({mode: 'clear'});
  W.act({mode: 'record'});
  out.recLatched = !!W.on();
  AR.cam.position.set(6, 5.8, 8);   AR.controls.target.set(0, 0, 0); W._step();
  AR.cam.position.set(0, 6.5, 12);  AR.controls.target.set(0, 1, 0); W._step();
  AR.cam.position.set(-6, 5.8, 8);  AR.controls.target.set(0, 0, 0); W._step();
  const stopped = W.act({mode: 'stop'});
  const path = AR.doc.ext.view_camera.path;
  out.walk = {stopped: stopped, keys: path.length, latched: !!W.on(),
              first: path[0].p, last: path[path.length - 1].p,
              toast: document.getElementById('ar-toast').innerHTML};
  AR.cam.position.set(30, 30, 30);       // somewhere else entirely
  const played = await W.act({mode: 'play'});
  out.walk.played = played;
  out.walk.endPos = AR.cam.position.toArray();
  out.walk.endTgt = AR.controls.target.toArray();
  return out;
}""")
v = r1['value']
check('no page errors while proving two-point and the walk path', not r1['errors'], r1['errors'])

off, on = v['off'], v['on']
check(
    'with two-point OFF the camera is really pitched (rotation.x = %.4f rad) and the lens is not shifted' % off['rotx'],
    abs(off['rotx']) > 0.3 and abs(off['e9']) < 1e-12,
    off,
)
check(
    'with two-point OFF an off-centre vertical edge converges: ndc x %.4f at the foot vs %.4f at the top'
    % (off['edge7'][0], off['edge7'][1]),
    abs(off['edge7'][0] - off['edge7'][1]) > 0.05,
    off,
)
check(
    'with two-point ON the camera is levelled (rotation.x = %.2e) and the lens is shifted (e[9] = %.4f)'
    % (on['rotx'], on['e9']),
    abs(on['rotx']) < 1e-9 and abs(on['e9']) > 0.1,
    on,
)
check(
    'with two-point ON the vertical edge (0,0,0)-(0,10,0) stays vertical: equal ndc x within 1e-6 (%.3e)'
    % abs(on['edge0'][0] - on['edge0'][1]),
    abs(on['edge0'][0] - on['edge0'][1]) < 1e-6,
    on,
)
check(
    'with two-point ON the off-centre vertical edge (7,0,0)-(7,10,0) stays vertical too (%.3e)'
    % abs(on['edge7'][0] - on['edge7'][1]),
    abs(on['edge7'][0] - on['edge7'][1]) < 1e-6,
    on,
)
check(
    'the lens shift keeps the orbit target framed: its ndc y is still 0 (%.3e)' % abs(on['tgtY']),
    abs(on['tgtY']) < 1e-6,
    on,
)
check('v_2pt latches on and off like a switch', on['latched'] and v['offAgain'], v)

w = v['walk']
check('recording latches the icon on and stopping latches it off', v['recLatched'] and not w['latched'], w)
check(
    'the recorded keys are in AR.doc.ext.view_camera.path (%d keys, cap 600)' % w['keys'],
    w['keys'] >= 2 and w['keys'] <= 600 and w['stopped'] == w['keys'],
    w,
)
check(
    'the keys hold the camera positions that were set (first %s, last %s)' % (w['first'], w['last']),
    abs(w['first'][0] - 6) < 1e-6 and abs(w['last'][0] + 6) < 1e-6,
    w,
)
check('stopping toasts the key count', 'key' in w['toast'] and str(w['keys']) in w['toast'], w['toast'])
check(
    'playing resolves with the key count and lands the camera on the last key %s (got %s)' % (w['last'], w['endPos']),
    w['played'] == w['keys'] and max(abs(a - b) for a, b in zip(w['endPos'], w['last'])) < 0.05,
    w,
)
check(
    'playing also drives the look-at target along the path (%s)' % (w['endTgt'],),
    abs(w['endTgt'][1]) < 0.05 and abs(w['endTgt'][0]) < 0.05,
    w,
)

# ── 3. the two recorders, on a page with something to look at ────────────────
DOC = {
    'objects': [
        {
            'id': 'w1',
            'kind': 'wall',
            'name': 'w1',
            'p': {'len': 8, 'h': 2.7, 't': 0.24, 'holes': []},
            'x': 0,
            'y': 0,
            'z': -4,
            'ry': 0,
            'mat': 'mat_brick',
        },
        {
            'id': 'w2',
            'kind': 'wall',
            'name': 'w2',
            'p': {'len': 8, 'h': 2.7, 't': 0.24, 'holes': []},
            'x': 0,
            'y': 0,
            'z': 4,
            'ry': 0,
            'mat': 'mat_plaster',
        },
        {
            'id': 'w3',
            'kind': 'wall',
            'name': 'w3',
            'p': {'len': 8, 'h': 2.7, 't': 0.24, 'holes': []},
            'x': -4,
            'y': 0,
            'z': 0,
            'ry': 1.5707963,
            'mat': 'mat_concrete',
        },
        {
            'id': 's1',
            'kind': 'slab',
            'name': 's1',
            'p': {'w': 8.5, 'd': 8.5, 't': 0.25},
            'x': 0,
            'y': 2.7,
            'z': 0,
            'mat': 'mat_concrete',
        },
    ]
}
r2 = browser_eval(
    """async () => {
  const out = {};
  arView('iso'); arZoomFit(false); arTick();

  const b = await AR_EXT.tools.v_turntable.act({seconds: 1, fps: 10, res: 640});
  out.tt = {size: b.size, type: b.type, mime: AR_VIEW_CAMERA.lastMime,
            busy: AR_VIEW_CAMERA.busy,
            canvas: [AR.renderer.domElement.width, AR.renderer.domElement.height]};

  // r_anim over a 3-key path
  const W = AR_EXT.tools.v_walkpath;
  W.act({mode: 'clear'});
  W.act({mode: 'record'});
  AR.cam.position.set(14, 8, 14);  AR.controls.target.set(0, 1.2, 0); W._step();
  AR.cam.position.set(0, 6, 18);   AR.controls.target.set(0, 1.2, 0); W._step();
  AR.cam.position.set(-14, 8, 14); AR.controls.target.set(0, 1.2, 0); W._step();
  W.act({mode: 'stop'});
  const keys = AR.doc.ext.view_camera.path.length;

  const b2 = await AR_EXT.tools.r_anim.act({res: 320, fps: 10, mode: 'path'});
  out.anim = {size: b2.size, type: b2.type, keys: keys,
              settings: AR.doc.ext.view_camera.anim,
              busy: AR_VIEW_CAMERA.busy,
              hour: AR.sunHour};
  out.toast = document.getElementById('ar-toast').innerHTML;

  // the other half of r_anim: no path -> a 06:00 to 20:00 sun sweep
  W.act({mode: 'clear'});
  const hourBefore = AR.sunHour;
  const b3 = await AR_EXT.tools.r_anim.act({res: 320, fps: 10, seconds: 1});
  out.sun = {size: b3.size, type: b3.type, settings: AR.doc.ext.view_camera.anim,
             hourBefore: hourBefore, hourAfter: AR.sunHour,
             path: (AR.doc.ext.view_camera.path || []).length};
  return out;
}""",
    doc=DOC,
)
check('no page errors while recording the two videos', not r2['errors'], r2['errors'])
tt = r2['value']['tt']
check(
    'the turntable returns a WebM Blob of %d bytes (codec %s)' % (tt['size'], tt['mime']),
    tt['size'] > 1000 and tt['type'].startswith('video/webm'),
    tt,
)
check(
    'the turntable gave the viewport its size back and cleared its busy latch',
    not tt['busy'] and tt['canvas'][0] != 640,
    tt,
)
an = r2['value']['anim']
check(
    'r_anim rendered the %d-key walk path to a WebM of %d bytes' % (an['keys'], an['size']),
    an['keys'] >= 3 and an['size'] > 1000 and an['type'].startswith('video/webm'),
    an,
)
check(
    'r_anim stored its settings in AR.doc.ext.view_camera.anim (%s)' % (an['settings'],),
    an['settings'] == {'res': 320, 'fps': 10, 'seconds': 8, 'mode': 'path'},
    an,
)
check('r_anim toasted what it wrote', 'WebM' in r2['value']['toast'], r2['value']['toast'])
sn = r2['value']['sun']
check(
    'without a walk path r_anim sweeps the sun 06:00->20:00 into a WebM of %d bytes' % sn['size'],
    sn['path'] == 0 and sn['size'] > 1000 and sn['type'].startswith('video/webm') and sn['settings']['mode'] == 'sun',
    sn,
)
check(
    'the sun sweep puts the hour back where it found it (%s -> %s)' % (sn['hourBefore'], sn['hourAfter']),
    sn['hourAfter'] == (14 if sn['hourBefore'] is None else sn['hourBefore']),
    sn,
)

# ── 4. the assistant may press all four, with arguments ──────────────────────
for _id, _args in (
    ('v_2pt', {'on': True}),
    ('v_turntable', {'seconds': 4, 'fps': 12, 'res': 800}),
    ('v_walkpath', {'mode': 'record'}),
    ('r_anim', {'res': 1920, 'mode': 'sun'}),
):
    txt, d = assistant('press_button', {'id': _id, 'args': _args})
    check(
        'the assistant may press %s with %s' % (_id, _args),
        txt.startswith('pressed') and d.ui[-1]['args']['id'] == _id and d.ui[-1]['args'].get('args') == _args,
        txt,
    )

finish()
