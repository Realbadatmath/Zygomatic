# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof — the Bones layer of Movement Studio IS the skeleton, not a drawing of one.

The actor GLB carries the Blender Studio CC0 anatomical skeleton as a second
SkinnedMesh named 'skeleton', 135 pieces fitted bone by bone to this actor and
skinned to the very same 31 joints as the flesh. This asserts that the tab now
shows THAT, and that the lathe shafts, the cranial volumes and the eye sockets
it replaces are not merely hidden but gone.

What it proves, in order:

  a. MVA.skel is the GLB's own SkinnedMesh — named 'skeleton', tagged
     userData.mvaLayer='bone', > 50 000 vertices, and sharing the body's
     31 Bone OBJECTS (identity, not just a matching count: a second copy of
     the skeleton would track the clip and still drift off the flesh)
  b. the Bones switch drives it, and `body: off` does not — the skin goes,
     the skeleton stays
  c. GFX.bone / solid / socket are not created at all; the joints are
     untouched; MVA.counts.bone is the mesh's piece count
  d. the split routes it: aSide carries {left, right, axis}, the axial
     vertices are the column and are kept WHOLE, and the uniform is the
     skeleton's half in a split view and -1 in a whole one
  e. it is still a frame's worth of work with the clip running, and it
     actually moves with the clip
  f. no page error, and six bind-pose screenshots to look at

Run:  <venv>/bin/python \
        tools/studio_verify/check_movement_skeleton_mesh.py
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
URL = paths.ZYG_KANBAN_URL + '/inspection.html#movementstudio'
READY_TIMEOUT_MS = 240_000
RIG_CHANNELS = 31
SIDE_L, SIDE_R, SIDE_AXIS = 0, 1, 3

SHOTS = [
    # name,            az,   el,   d,     ty
    ('front', 0.0, 0.0, 2.00, 0.00),
    ('back', 180.0, 0.0, 2.00, 0.00),
    ('head', 20.0, 5.0, 0.45, 0.42),
    ('chest', 0.0, 0.0, 0.70, 0.25),
    ('pelvis', 0.0, -5.0, 0.55, 0.00),
]

PROBE = """() => {
  const M = window.MVR, A = window.MVA;
  if (!M) return {ready:false, why:'no MVR'};
  if (!A) return {ready:false, why:'no MVA — the anatomy file did not load'};
  return {
    ready: !!M.loaded && !!A.ready,
    why: A.note || M.error || '',
    actor: M.actor || '',
    rig: (M.skeleton && M.skeleton.bones) ? M.skeleton.bones.length : 0,
    counts: A.counts,
    on: A.on,
    body: A.body,
    split: A.split, splitSide: A.splitSide,
    ms: A.ms || 0,
    vert: A.atlas ? A.atlas.vert : 0,
    stature: A.atlas ? +A.atlas.stature.toFixed(4) : 0,
    meta: (M.meta && M.meta.skeleton) || null
  };
}"""

# the skeleton mesh, the skin mesh, and whether they are the same rig
SKEL = """() => {
  const A = window.MVA, M = window.MVR;
  const sk = A.skel;
  if (!sk) return {found:false, note:A.note || ''};
  let skin = null;
  M.inner.traverse(o => {
    if (!skin && o.isSkinnedMesh && !(o.userData && o.userData.mvaLayer)) skin = o;
  });
  const sb = sk.skeleton ? sk.skeleton.bones : [];
  const kb = (skin && skin.skeleton) ? skin.skeleton.bones : [];
  let same = sb.length > 0 && sb.length === kb.length;
  for (let i = 0; same && i < sb.length; i++) if (sb[i] !== kb[i]) same = false;
  const g = sk.geometry, side = g.attributes.aSide;
  const hist = {};
  if (side) for (let i = 0; i < side.count; i++) {
    const v = side.getX(i); hist[v] = (hist[v] || 0) + 1;
  }
  const u = sk.material && sk.material.userData && sk.material.userData.__sideU;
  return {
    found: true,
    name: sk.name,
    isSkinnedMesh: !!sk.isSkinnedMesh,
    layer: (sk.userData && sk.userData.mvaLayer) || '',
    vertices: g.attributes.position.count,
    tris: g.index ? g.index.count / 3 : g.attributes.position.count / 3,
    bones: sb.length,
    sameRigAsSkin: same,
    skinName: skin ? skin.name : '',
    skinVisible: skin ? skin.visible : null,
    skinSideU: (skin && skin.material && skin.material.userData
                && skin.material.userData.__sideU)
               ? skin.material.userData.__sideU.value : null,
    visible: sk.visible,
    renderOrder: sk.renderOrder,
    frustumCulled: sk.frustumCulled,
    castShadow: sk.castShadow,
    colour: sk.material ? '#' + sk.material.color.getHexString() : '',
    roughness: sk.material ? sk.material.roughness : null,
    hasSide: !!side,
    sideHist: hist,
    sideU: u ? u.value : null
  };
}"""

GFXQ = """() => {
  const g = MVA.__gfx();
  if (!g) return {none:true};
  const one = k => (g[k] === undefined ? 'undefined' : (g[k] ? g[k].count : 'null'));
  return {bone: one('bone'), solid: one('solid'), socket: one('socket'),
          boneH: one('boneH'), solidH: one('solidH'), socketH: one('socketH'),
          joint: one('joint'), link: one('link'), jointH: one('jointH')};
}"""

# the operator's A-pose: the plates were drawn in it, and mixer.setTime(0) is
# NOT it — the first frame of a mocap clip is a stride, not a rest pose.
BIND = """() => {
  MVR.paused = true;
  if (MVR.action) MVR.action.paused = true;
  MVR.inner.traverse(o => { if (o.isSkinnedMesh) o.skeleton.pose(); });
  MVR.inner.updateMatrixWorld(true);
  MVA.tick();
}"""

LOOK = """([az, el, d, ty]) => {
  const A = MVA.atlas;
  const R = Math.PI / 180, a = az * R, e = el * R;
  const ctr = new THREE.Vector3().setFromMatrixPosition(A.bones.Hips.matrixWorld)
                .addScaledVector(A.up, ty * A.stature);
  const dir = A.ant.clone().multiplyScalar(Math.cos(a) * Math.cos(e))
                .addScaledVector(A.lat, Math.sin(a) * Math.cos(e))
                .addScaledVector(A.up, Math.sin(e)).normalize();
  MVST3.controls.target.copy(ctr);
  MVST3.camera.position.copy(ctr).addScaledVector(dir, d * A.stature);
  MVST3.controls.update();
  MVA.tick();
}"""


def wait_ready(pg):
    waited = 0
    st = None
    while waited < READY_TIMEOUT_MS:
        st = pg.evaluate(PROBE)
        if st.get('ready'):
            return st, waited
        if st.get('why') and 'not a cmu_mb' in st['why']:
            raise AssertionError('anatomy refused: %s' % st['why'])
        pg.wait_for_timeout(1000)
        waited += 1000
    raise AssertionError('no anatomy after %d s: %s' % (READY_TIMEOUT_MS // 1000, json.dumps(st)))


def run(pw, shoot):
    errs = []
    br = pw.chromium.launch(
        executable_path='/usr/bin/google-chrome',
        args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required'],
    )
    ctx = br.new_context(viewport={'width': 2507, 'height': 1567})
    pg = ctx.new_page()
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.on('console', lambda m: errs.append('console.error: ' + m.text) if m.type == 'error' else None)
    pg.goto(URL, wait_until='load', timeout=120_000)

    st, waited = wait_ready(pg)
    _zyg_log.info(
        'ready in %ds  actor=%s  stature=%.3f m  skin measured off %d vertices '
        'in %.0f ms' % (waited // 1000, st['actor'], st['stature'], st['vert'], st['ms'])
    )
    if st['rig'] != RIG_CHANNELS:
        raise RuntimeError('the rig is not cmu_mb any more: %d' % st['rig'])
    _zyg_log.info('    actor sidecar skeleton: %s' % json.dumps(st['meta']))

    # ── (a) it is the GLB's own skeleton, on the body's own rig ──────────
    # everything up: the bones layer must be on for the rest of the run
    pg.evaluate("() => MVA.applyView('anat')")
    pg.wait_for_timeout(300)
    sk = pg.evaluate(SKEL)
    if not sk['found']:
        raise RuntimeError('there is no MVA.skel — the Bones layer is empty. %s' % sk.get('note', ''))
    _zyg_log.info(
        '    MVA.skel: name=%r skinned=%s layer=%r %d vertices / %d tris, '
        '%d bones, colour %s rough %.2f renderOrder %s frustumCulled %s '
        'castShadow %s'
        % (
            sk['name'],
            sk['isSkinnedMesh'],
            sk['layer'],
            sk['vertices'],
            int(sk['tris']),
            sk['bones'],
            sk['colour'],
            sk['roughness'],
            sk['renderOrder'],
            sk['frustumCulled'],
            sk['castShadow'],
        )
    )
    if sk['name'] != 'skeleton':
        raise RuntimeError('MVA.skel is named %r' % sk['name'])
    if not sk['isSkinnedMesh']:
        raise RuntimeError('MVA.skel is not a SkinnedMesh — it cannot follow the clip')
    if sk['layer'] != 'bone':
        raise RuntimeError("MVA.skel is tagged %r, not 'bone'" % sk['layer'])
    if sk['vertices'] <= 50_000:
        raise RuntimeError('only %d vertices — that is not the anatomical skeleton' % sk['vertices'])
    if sk['bones'] != RIG_CHANNELS:
        raise RuntimeError('the skeleton is skinned to %d bones, not %d' % (sk['bones'], RIG_CHANNELS))
    if not sk['sameRigAsSkin']:
        raise RuntimeError(
            'the skeleton is skinned to a DIFFERENT set of Bone objects than the '
            'skin (%r) — it would drift off the body' % sk['skinName']
        )
    if not (sk['castShadow'] is False and sk['frustumCulled'] is False):
        raise RuntimeError(
            'shadow/cull flags: castShadow=%s frustumCulled=%s' % (sk['castShadow'], sk['frustumCulled'])
        )
    if sk['renderOrder'] != 5:
        raise RuntimeError('renderOrder is %s' % sk['renderOrder'])

    # ── (b) the Bones switch owns it; `body: off` does not ───────────────
    pg.evaluate("() => document.getElementById('mva-bone').click()")
    pg.wait_for_timeout(250)
    off = pg.evaluate(SKEL)
    pg.evaluate("() => document.getElementById('mva-bone').click()")
    pg.wait_for_timeout(250)
    on = pg.evaluate(SKEL)
    _zyg_log.info('    #mva-bone: off -> skel.visible=%s   on -> skel.visible=%s' % (off['visible'], on['visible']))
    if off['visible'] is not False:
        raise RuntimeError('the Bones switch did not hide the skeleton')
    if on['visible'] is not True:
        raise RuntimeError('the Bones switch did not bring it back')

    pg.evaluate("() => document.getElementById('mva-body-off').click()")
    pg.wait_for_timeout(250)
    bo = pg.evaluate(SKEL)
    _zyg_log.info(
        '    #mva-body-off: skel.visible=%s   skin %r visible=%s' % (bo['visible'], bo['skinName'], bo['skinVisible'])
    )
    if bo['visible'] is not True:
        raise RuntimeError('`body: off` hid the skeleton — it hides the SKIN, never the layers')
    if bo['skinVisible'] is not False:
        raise RuntimeError('`body: off` left the skin on screen')

    # ── (c) the procedural bone passes are gone, the joints are not ──────
    gfx = pg.evaluate(GFXQ)
    _zyg_log.info('    GFX counts: %s' % json.dumps(gfx))
    for k in ('bone', 'solid', 'socket', 'boneH', 'solidH', 'socketH'):
        v = gfx.get(k)
        if v not in ('undefined', 'null', 0):
            raise RuntimeError('GFX.%s still draws %s instances' % (k, v))
    c = pg.evaluate('() => MVA.counts')
    _zyg_log.info('    MVA.counts: %s' % json.dumps(c))
    if c['joint'] <= 150:
        raise RuntimeError('the joints were disturbed: %d' % c['joint'])
    if c['bone'] != 135:
        raise RuntimeError('MVA.counts.bone is %s, not the 135 pieces of the fitted skeleton' % c['bone'])
    if not (c['solid'] == 0 and c['socket'] == 0):
        raise RuntimeError('solid/socket counts are %s/%s' % (c['solid'], c['socket']))
    if not (gfx['joint'] not in ('undefined', 'null') and gfx['joint'] > 0):
        raise RuntimeError('the joint mesh stopped drawing: %s' % gfx['joint'])

    # ── (d) the split routes it by side, and keeps the column whole ──────
    pg.evaluate("() => MVA.applyView('halfbare')")
    pg.wait_for_timeout(400)
    hb = pg.evaluate(SKEL)
    stv = pg.evaluate(PROBE)
    want = SIDE_L if stv['splitSide'] else SIDE_R  # SK.skel
    other = SIDE_R if stv['splitSide'] else SIDE_L
    hist = {int(float(k)): v for k, v in hb['sideHist'].items()}
    _zyg_log.info(
        '    halfbare: aSide histogram %s  (L=%d R=%d AXIS=%d)'
        % (
            json.dumps({str(k): v for k, v in sorted(hist.items())}),
            hist.get(SIDE_L, 0),
            hist.get(SIDE_R, 0),
            hist.get(SIDE_AXIS, 0),
        )
    )
    _zyg_log.info(
        '    halfbare: skel uSideKeep=%s  skin uSideKeep=%s  '
        'SK.skel=%d SK.mus=%d' % (hb['sideU'], hb['skinSideU'], want, other)
    )
    if not hb['hasSide']:
        raise RuntimeError('the skeleton geometry has no aSide attribute')
    for s, nm in ((SIDE_L, 'left'), (SIDE_R, 'right'), (SIDE_AXIS, 'axis')):
        if hist.get(s, 0) <= 0:
            raise RuntimeError('no %s (aSide=%d) vertices on the skeleton: %s' % (nm, s, hist))
    if hb['sideU'] != want:
        raise RuntimeError('the skeleton is cut to side %s but the skeleton half is %d' % (hb['sideU'], want))
    # the axial vertices are the column, and the shader keeps them on whichever
    # half the bone is drawn on — a half spine reads as a broken spine
    if hist[SIDE_AXIS] <= 3000:
        raise RuntimeError('only %d axial vertices — the column is not being marked' % hist[SIDE_AXIS])

    pg.evaluate("() => MVA.applyView('anat')")
    pg.wait_for_timeout(300)
    an = pg.evaluate(SKEL)
    _zyg_log.info('    anat: skel uSideKeep=%s (whole)' % an['sideU'])
    if an['sideU'] != -1:
        raise RuntimeError('a whole view still cuts the skeleton: uSideKeep=%s' % an['sideU'])

    # ── (e) it costs a frame and it moves with the clip ──────────────────
    pg.evaluate('() => { MVR.paused = false; if (MVR.action) MVR.action.paused = false; }')
    pg.wait_for_timeout(200)
    samp = """() => {
      const t0 = performance.now();
      MVA.tick();
      const ms = performance.now() - t0;
      const m = MVA.atlas.bones.LeftForeArm.matrixWorld.elements;
      return {ms: ms, p: [m[12], m[13], m[14]]};
    }"""
    s1 = pg.evaluate(samp)
    pg.wait_for_timeout(500)
    s2 = pg.evaluate(samp)
    move = sum((a - b) ** 2 for a, b in zip(s1['p'], s2['p'])) ** 0.5
    _zyg_log.info(
        '    tick cost %.2f ms then %.2f ms;  LeftForeArm moved %.4f m in 0.5 s '
        '(MVA.ms, the build measure, was %.0f ms)' % (s1['ms'], s2['ms'], move, stv['ms'])
    )
    if s2['ms'] >= 3.0:
        raise RuntimeError('a tick costs %.2f ms' % s2['ms'])
    if move <= 1e-4:
        raise RuntimeError('LeftForeArm did not move in half a second — the clip is not driving the rig')

    # ── (f) look at it ───────────────────────────────────────────────────
    made = []
    if shoot:
        pg.evaluate("() => MVA.applyView('bones')")
        pg.evaluate("() => { MVA.body = 'off'; }")
        pg.evaluate(BIND)
        pg.wait_for_timeout(400)
        frame = pg.evaluate("""() => {
          const z = parseFloat(
            getComputedStyle(document.documentElement).zoom || '1') || 1;
          const r = document.querySelector('#view-movement .cs-main')
                      .getBoundingClientRect();
          return {x: Math.round(r.left * z), y: Math.round(r.top * z),
                  width: Math.round(r.width * z),
                  height: Math.round(r.height * z)};
        }""")
        for name, az, el, d, ty in SHOTS:
            pg.evaluate(LOOK, [az, el, d, ty])
            pg.wait_for_timeout(600)
            p = os.path.join(HERE, 'movement_skeleton_%s.png' % name)
            pg.screenshot(path=p, clip=frame)
            made.append(p)
        # the hand off its own measured frame, so the shot is the same view
        # whatever the pose has done with the arm
        pg.evaluate("""() => {
          const at = MVA.atlas, H = at.hand[0], b = at.bones.LeftHand;
          const M = b.matrixWorld;
          const R = new THREE.Matrix4().extractRotation(M);
          const o = new THREE.Vector3().setFromMatrixPosition(M);
          const dist = H.dist.clone().applyMatrix4(R).normalize();
          const palm = H.palm.clone().applyMatrix4(R).normalize();
          const ctr = o.clone().addScaledVector(dist, H.len * 0.45);
          MVST3.controls.target.copy(ctr);
          MVST3.camera.position.copy(ctr)
            .addScaledVector(palm, H.len * 1.5)
            .addScaledVector(dist, -H.len * 0.35);
          MVST3.controls.update();
          MVA.tick();
        }""")
        pg.wait_for_timeout(600)
        p = os.path.join(HERE, 'movement_skeleton_hand.png')
        pg.screenshot(path=p, clip=frame)
        made.append(p)
        # and the cut itself. The split adds a `discard` to the skeleton's
        # shader, and a shader that fails to compile does not throw — it
        # renders black. This is the only way to know the column really is
        # kept whole down the seam.
        pg.evaluate("() => MVA.applyView('halfbare')")
        pg.evaluate(BIND)
        pg.evaluate(LOOK, [0.0, 0.0, 2.00, 0.00])
        pg.wait_for_timeout(600)
        p = os.path.join(HERE, 'movement_skeleton_halfbare.png')
        pg.screenshot(path=p, clip=frame)
        made.append(p)

    if errs:
        raise RuntimeError('page errors:\n  ' + '\n  '.join(errs[:8]))
    br.close()
    return sk, c, made


def main():
    shoot = '--no-shot' not in sys.argv
    with sync_playwright() as pw:
        sk, c, made = run(pw, shoot)
    print(
        "\nPASS — the Bones layer is the actor's own skeleton: %d pieces, "
        "%d vertices, skinned to the body's %d joints; %d rig joints still drawn"
        % (c['bone'], sk['vertices'], sk['bones'], c['joint'])
    )
    for p in made:
        print('      %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
