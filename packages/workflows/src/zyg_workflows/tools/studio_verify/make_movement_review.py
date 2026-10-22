# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The REVIEW PORTFOLIO — 17 pictures of Movement Studio's anatomy for the
creator to hold against the operator's reference plate
('perfect skeleton and muscl e packs.jpg': anatomical A-pose, front, one half
skeleton, the other half muscle, the face cut down the middle).

Not a proof — check_movement_anatomy.py is the proof. This only takes the
pictures, at the operator's own viewport (2507x1567, the 67 % zoom), in the
BIND POSE the plates are drawn in, from cameras named in the body's own frame
so the same shot comes out of any actor.

Output: tools/studio_verify/movement_review/*.png + README.txt

Run:  <venv>/bin/python \
        tools/studio_verify/make_movement_review.py
"""

import os

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'movement_review')
URL = paths.ZYG_KANBAN_URL + '/inspection.html#movementstudio'
READY_TIMEOUT_MS = 240_000
EC_TIMEOUT_MS = 90_000
MIN_BYTES = 40 * 1024

READY = """() => {
  const M = window.MVR, A = window.MVA;
  if (!M) return {ready:false, why:'no MVR'};
  if (!A) return {ready:false, why:'no MVA'};
  return {ready: !!M.loaded && !!A.ready, why: A.note || M.error || '',
          actor: M.actor || '', base: (M.meta && M.meta.base_body_id) || ''};
}"""

EC_READY = """() => {
  const A = window.MVA;
  if (!A) return {on:false, why:'no MVA'};
  if (!A.ec) return {on:false, why:A.ecNote || 'no MVA.ec yet'};
  const m = A.ec.material;
  return {on: !!(m && m.map && m.map.image && m.map.image.width),
          why: A.ecNote || 'atlas still decoding'};
}"""

# the A-pose the reference plates are drawn in. mixer.setTime(0) is NOT a rest
# pose — frame 0 of qa_sword is mid-guard.
BIND = """() => {
  MVR.paused = true;
  if (MVR.action) MVR.action.paused = true;
  MVR.inner.traverse(o => { if (o.isSkinnedMesh) o.skeleton.pose(); });
  MVR.inner.updateMatrixWorld(true);
  MVA.tick();
}"""

# az 0 = in front of the face, 180 = behind. d and ty are in statures.
LOOK = """([az, el, d, ty]) => {
  const A = MVA.atlas;
  const c = new THREE.Vector3().setFromMatrixPosition(A.bones.Hips.matrixWorld)
    .addScaledVector(A.up, ty * A.stature);
  const a = az * Math.PI / 180, e = el * Math.PI / 180;
  const dir = A.ant.clone().multiplyScalar(Math.cos(a) * Math.cos(e))
    .addScaledVector(A.lat, Math.sin(a) * Math.cos(e))
    .addScaledVector(A.up, Math.sin(e)).normalize();
  MVST3.camera.position.copy(c).addScaledVector(dir, d * A.stature);
  MVST3.controls.target.copy(c);
  MVST3.controls.update();
  MVA.tick();
}"""

# the left hand off its own measured frame, so the framing is the same shot
# whatever the pose has done with the arm
HAND = """() => {
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
}"""

# 17: the clip itself. The action must stay UNPAUSED for setTime to retime it
# (a paused AnimationAction has an effective timeScale of 0 and setTime moves
# nothing); MVR.paused only stops the tab's loop advancing past the frame.
MOVING = """(t) => {
  MVR.paused = true;
  if (MVR.action) MVR.action.paused = false;
  MVR.mixer.setTime(t);
  MVR.inner.updateMatrixWorld(true);
  MVA.tick();
}"""

# name, view, az, el, d, ty, what it is
MALE = [
    ('01_halfbare_front', 'halfbare', 0, 0, 2.00, 0.00),
    ('02_halfbare_back', 'halfbare', 180, 0, 2.00, 0.00),
    ('03_halfbare_left', 'halfbare', 90, 0, 2.00, 0.00),
    ('04_halfskin_front', 'halfskin', 0, 0, 2.00, 0.00),
    ('05_bones_front', 'bones', 0, 0, 2.00, 0.00),
    ('06_bones_back', 'bones', 180, 0, 2.00, 0.00),
    ('07_bones_head', 'bones', 20, 5, 0.45, 0.42),
    ('08_bones_chest', 'bones', 0, 0, 0.70, 0.25),
    ('09_bones_pelvis', 'bones', 0, -5, 0.55, 0.00),
    # 10 is the hand, framed from the hand's own axes
    ('11_halfbare_head', 'halfbare', 15, 5, 0.45, 0.42),
    ('12_anat_front', 'anat', 0, 0, 2.00, 0.00),
    ('13_all_front', 'all', 0, 0, 2.00, 0.00),
    ('14_skin_front', 'skin', 0, 0, 2.00, 0.00),
]

FEMALE = [
    ('15_female_halfbare_front', 'halfbare', 0, 0, 2.00, 0.00),
    ('16_female_bones_front', 'bones', 0, 0, 2.00, 0.00),
]

README = """movement_review — 17 pictures of Movement Studio's anatomy, to be held
against the operator's plate 'perfect skeleton and muscl e packs.jpg'
(anatomical A-pose, front, half skeleton / half muscle, face cut down the
middle). Every shot is the BIND POSE except 17, at the operator's own
2507x1567 viewport, clipped to the studio canvas.

01_halfbare_front.png       THE PLATE ITSELF: half muscle, half bare skeleton,
                            front. Compare limb for limb with the plate — the
                            midline seam, the face cut, whether the muscle half
                            reads as muscle and the bone half as bone.
02_halfbare_back.png        The same split from behind. The plate has no back
                            view; compare the seam's continuity round the body.
03_halfbare_left.png        The split in profile, from the actor's left (the
                            muscle side). Compare the depth of the muscle
                            surface against the skeleton's.
04_halfskin_front.png       Half muscle, half SKIN over the skeleton — the
                            plate's variant with the intact body on one side.
05_bones_front.png          The skeleton alone, front. Compare against the
                            plate's bone half: rib count, pelvis, the column.
06_bones_back.png           The skeleton alone from behind — scapulae, sacrum.
07_bones_head.png           The skull, close, three-quarter. Compare the
                            cranium, orbits, mandible and teeth with the
                            plate's head.
08_bones_chest.png          The rib cage and sternum, close and frontal.
09_bones_pelvis.png         The pelvis and sacrum from slightly below.
10_bones_hand.png           The left hand's bones, framed from the hand's own
                            palm and distal axes. Compare carpals, metacarpals
                            and the three phalanges per finger.
11_halfbare_head.png        The head SPLIT: skull on one side, muscle face on
                            the other. This is the plate's signature detail —
                            the face cut down the middle.
12_anat_front.png           Skeleton + écorché + joints, whole, no skin. What
                            the anatomy is when nothing is cut away.
13_all_front.png            Everything, with the translucent clay actor in
                            front of it. Shows the layers really sit inside
                            the body.
14_skin_front.png           The plain clay actor, no anatomy — the control
                            picture: this is the surface everything above is
                            claimed to fit inside.
15_female_halfbare_front.png The plate shot on the FEMALE base body (Character
                            Studio's pin, localStorage cs.basebody). Compare
                            the pelvis, rib cage and shoulder against 01.
16_female_bones_front.png   The female skeleton alone, front.
17_moving_halfbare.png      The split at t = 1.2 s of the qa_sword clip, from
                            az 30 — a turned, swinging body. The seam must
                            still run down the body's own midline: this is the
                            picture that shows the halves are an anatomical
                            fact and not a plane through space.
"""


def wait_for(pg, js, timeout_ms, label, key):
    waited, st = 0, None
    while waited < timeout_ms:
        st = pg.evaluate(js)
        if st.get(key):
            return st, waited
        pg.wait_for_timeout(1000)
        waited += 1000
    raise AssertionError('%s never happened in %d s: %s' % (label, timeout_ms // 1000, st))


def frame_of(pg):
    """The studio canvas in DEVICE pixels. The GUI runs at html{zoom:.67}, so
    getBoundingClientRect answers inside that zoom while a screenshot clip is
    device pixels — a rect handed over raw crops the wrong two thirds."""
    return pg.evaluate("""() => {
      const z = parseFloat(
        getComputedStyle(document.documentElement).zoom || '1') || 1;
      const r = document.querySelector('#view-movement .cs-main')
                  .getBoundingClientRect();
      return {x: Math.round(r.left * z), y: Math.round(r.top * z),
              width: Math.round(r.width * z), height: Math.round(r.height * z)};
    }""")


def open_tab(br, basebody):
    ctx = br.new_context(viewport={'width': 2507, 'height': 1567})
    if basebody:
        ctx.add_init_script("try { localStorage.setItem('cs.basebody', %r); } catch (e) {}" % basebody)
    pg = ctx.new_page()
    errs = []
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.goto(URL, wait_until='load', timeout=120_000)
    st, waited = wait_for(pg, READY, READY_TIMEOUT_MS, 'the anatomy', 'ready')
    _zyg_log.info('  ready in %ds  actor=%s  base=%s' % (waited // 1000, st['actor'], st['base']))
    _, ecw = wait_for(pg, EC_READY, EC_TIMEOUT_MS, 'the écorché atlas', 'on')
    _zyg_log.info('  écorché atlas decoded %ds after that' % (ecw // 1000))
    return pg, errs, st


def shoot(pg, frame, name, view, az, el, d, ty):
    pg.evaluate('(k) => MVA.applyView(k)', view)
    pg.evaluate(BIND)
    pg.evaluate(LOOK, [az, el, d, ty])
    pg.wait_for_timeout(700)
    path = os.path.join(OUT, name + '.png')
    pg.screenshot(path=path, clip=frame)
    _zyg_log.info('  %-28s %-9s az=%-4s el=%-3s d=%-5s ty=%-5s' % (name, view, az, el, d, ty))
    return path


if __name__ == '__main__':  # the CLI lives in make_movement_review_cli
    from zyg_workflows.tools.studio_verify.make_movement_review_cli import main as _cli_main

    raise SystemExit(_cli_main())
