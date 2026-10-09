# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Movement Studio anatomy proof — checks 1, 2, 2b and 3.

The page, the measured body, the joint cloud and the skeleton mesh. Every
function here was a contiguous section of ``run`` before the 2026-10-09 split;
the assertions, the log lines and their order are unchanged. The stages take
the Playwright page as their first argument and nothing else from the
orchestrator, which is what makes them testable against a recording stub.
"""

from .constants import EC_READY, EC_TIMEOUT_MS, GFXQ, PROBE, READY_TIMEOUT_MS, RIG_CHANNELS, SIDE_AXIS, SIDE_L
from .constants import SIDE_R, SKEL, SKEL_PIECES, URL, _require, json, wait_for

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

FINGERS = """() => {
      const A = window.MVA, at = A.atlas;
      A.tick();                       // sample one instant, not two
      const T = A.__tips(), out = [];
      for (let s = 0; s < 2; s++) {
        const H = at.hand[s], t = T[s];
        if (!H || !t) { out.push(null); continue; }
        const o = t.wrist, ax = t.dist;
        const reach = p => p ? +p.clone().sub(o).dot(ax).toFixed(4) : null;
        const b = at.bones[s ? 'RightHand' : 'LeftHand'];
        const w = new THREE.Vector3().setFromMatrixPosition(b.matrixWorld);
        let near = 0;
        for (const j of A.__joints()) if (j.p.distanceTo(w) < H.len * 1.25) near++;
        // the solve must be of the SAME frame the bones are in: a lag shows up
        // here as a wrist that is not where its own bone is
        out.push({near: near, len: +H.len.toFixed(4), lag: +o.distanceTo(w).toFixed(6),
                  index: reach(t.index), middle: reach(t.middle),
                  ring: reach(t.ring), little: reach(t.little),
                  thumb: reach(t.thumb)});
      }
      return out;
    }"""

COLUMN = """() => {
      const A = window.MVA;
      const lv = A.__levels();
      const names = lv.map(l => l.n), ys = lv.map(l => +l.p.y.toFixed(4));
      let mono = true;
      for (let i = 1; i < ys.length; i++) if (ys[i] < ys[i-1] - 1e-4) mono = false;
      A.tick();
      const at = A.atlas, J = [];
      for (const k in at.bones) J.push(
        new THREE.Vector3().setFromMatrixPosition(at.bones[k].matrixWorld));
      let worst = 0, wp = null, n = 0;
      for (const j of A.__joints()) {
        let d = 1e9;
        for (const q of J) { const e = j.p.distanceTo(q); if (e < d) d = e; }
        n++;
        if (d > worst) { worst = d; wp = j.p.clone(); }
      }
      return {levels: names.length, names: names, mono: mono,
              lo: ys[0], hi: ys[ys.length-1], total: n,
              worst: +worst.toFixed(4), at: wp.toArray().map(x => +x.toFixed(3)),
              stature: at.stature};
    }"""

SKEL_TICK = """() => {
      const t0 = performance.now();
      MVA.tick();
      const ms = performance.now() - t0;
      const m = MVA.atlas.bones.LeftForeArm.matrixWorld.elements;
      return {ms: ms, p: [m[12], m[13], m[14]]};
    }"""


def open_page(pw, width, height, errs):
    """Launch headless Chrome through SwiftShader, open the inspection tab at
    *width* x *height* and route every pageerror / console.error into *errs*.

    Returns ``(browser, page)``; the browser is the orchestrator's to close.
    """
    br = pw.chromium.launch(
        executable_path='/usr/bin/google-chrome',
        args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required'],
    )
    ctx = br.new_context(viewport={'width': width, 'height': height})
    pg = ctx.new_page()
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.on('console', lambda m: errs.append('console.error: ' + m.text) if m.type == 'error' else None)
    pg.goto(URL, wait_until='load', timeout=120_000)
    return br, pg


def check_measured_body(pg):
    """Check 1: the anatomy solved, off a body whose measurements are a body's.

    Waits for MVA.ready and for the écorché atlas to decode, then asserts the
    rig channel count, the three layer switches, the vertex and torso-band
    counts, and the stature / hand / foot / ankle proportions. Returns the
    ready probe dict, which every later check reads.
    """
    # ── 1. it solved, off a measured body ────────────────────────────────
    st, waited = wait_for(pg, PROBE, READY_TIMEOUT_MS, 'the anatomy')
    _zyg_log.info(
        'ready in %ds  actor=%s  base=%s  stature=%.3f m  measured %d vertices '
        'in %.0f ms' % (waited // 1000, st['actor'], st['base'], st['stature'], st['vert'], st['ms'])
    )
    _zyg_log.info('    actor sidecar skeleton: %s' % json.dumps(st['meta']))
    _require(st['rig'] == RIG_CHANNELS, 'the rig is not cmu_mb any more: %d' % st['rig'])
    _require(
        st['on']['bone'] and st['on']['joint'] and st['on']['muscle'],
        'the tab did not open with all three layers up: %s — muscles were '
        'asked for, they should not need finding' % st['on'],
    )
    _require(st['vert'] > 2000, 'the body was not measured: %d vertices' % st['vert'])
    _require(st['torso'] >= 20, 'only %d torso bands measured' % st['torso'])

    ecst, ecw = wait_for(pg, EC_READY, EC_TIMEOUT_MS, 'the écorché atlas', 'on')
    _zyg_log.info('    écorché atlas decoded %ds after that' % (ecw // 1000))
    _check_proportions(st)
    return st


def _check_proportions(st):
    """Assert the measurements are a BODY's.

    A skinning path that is subtly wrong does not throw, it reports a 250 m
    head, and every size downstream is quietly built on it.
    """
    h, f, S = st['hand'], st['foot'], st['stature']
    _zyg_log.info(
        '    measured: hand %.3f x %.3f x %.3f m, foot %.3f x %.3f m, stature %.3f m'
        % (h['len'], h['width'], h['thick'], f['len'], f['width'], S)
    )
    _require(1.2 < S < 2.3, 'stature came out %.2f m' % S)
    _require(0.055 * S < h['len'] < 0.155 * S, 'the hand measures %.3f m on a %.2f m body' % (h['len'], S))
    _require(0.04 * S < h['width'] < 0.14 * S, 'the hand is %.3f m across on a %.2f m body' % (h['width'], S))
    _require(
        0.06 * S < f['len'] < 0.19 * S,
        'the foot measures %.3f m forward of the ankle on a %.2f m body'
        % (
            f['len'],
            S,
        ),
    )
    _require(
        st['ankleIn'],
        'the ankle joint is not inside its own foot — the rig and the mesh are '
        'in different places, so every measurement above is suspect',
    )


def check_joint_cloud(pg, st):
    """Checks 2 and 2b: the joint set is no longer the rig's, and it is an
    anatomy's.

    The counts off *st*, then five named finger rays per hand, then the 30
    column levels and how far the furthest solved joint stands from the rig.
    """
    _check_counts(st['counts'])
    _check_fingers(pg)
    _check_column(pg)


def _check_counts(c):
    """Assert the solved joint and link counts — the point of this was that the
    rig's 31 joints are not enough."""
    # ── 2. the joint set is no longer the rig's ──────────────────────────
    _zyg_log.info(
        '    joints %d   links %d   skeleton pieces %d   écorché %d' % (c['joint'], c['link'], c['bone'], c['muscle'])
    )
    _require(c['joint'] > 150, 'only %d joints — the point of this was that 31 is not enough' % c['joint'])
    _require(c['link'] > 120, 'only %d joint links' % c['link'])


def _check_fingers(pg):
    """Sample both hands' ray tips in one instant and check each hand.

    Reach is measured along the hand's own distal axis, which is what the hand
    was measured along — a curled fingertip is further from the wrist in a
    straight line than it is down the hand.
    """
    # fingers: five NAMED rays per hand, each reaching where that finger
    # reaches.
    fing = pg.evaluate(FINGERS)
    for s, fh in enumerate(fing):
        _check_hand(s, fh)


def _check_hand(s, fh):
    """Assert one hand's five rays: present, in order, and of that hand's own
    measured proportions; and that the solve is of the bones' own frame.

    *s* is 0 for the left hand and 1 for the right; *fh* is its FINGERS row.
    """
    side = 'left' if s == 0 else 'right'
    _require(fh, 'no hand solved on the %s' % side)
    _zyg_log.info(
        '    %-5s hand: %d joints past the wrist \u2014 index %.3f middle %.3f '
        'ring %.3f little %.3f thumb %.3f (hand %.3f m)'
        % (side, fh['near'], fh['index'], fh['middle'], fh['ring'], fh['little'], fh['thumb'], fh['len'])
    )
    for ray in ('index', 'middle', 'ring', 'little', 'thumb'):
        _require(fh[ray] is not None, 'the %s hand has no %s' % (side, ray))
    _require(fh['near'] >= 19, 'the %s hand has %d joints past the wrist; a hand has 19' % (side, fh['near']))
    _require(
        fh['lag'] < 1e-5,
        'the %s hand is solved %.4f m from its own wrist bone — the anatomy '
        'is a frame behind the actor' % (side, fh['lag']),
    )
    # a hand's own proportions, not a table's. The rest curl costs the
    # middle ray about 7 % of its axial reach, which is what a relaxed
    # hand does — a straight finger would come out at 1.00.
    _require(
        0.88 * fh['len'] <= fh['middle'] <= 1.04 * fh['len'],
        'the %s middle finger reaches %.3f down a hand measured at %.3f' % (side, fh['middle'], fh['len']),
    )
    _require(
        fh['middle'] > fh['index'] > fh['little'],
        'the %s rays are out of order: index %.3f middle %.3f little %.3f'
        % (side, fh['index'], fh['middle'], fh['little']),
    )
    _require(
        fh['middle'] > fh['ring'] > fh['little'],
        'the %s ring finger is not between the middle and the little' % side,
    )
    _require(
        0.64 * fh['len'] < fh['little'] < 0.86 * fh['len'],
        'the %s little finger reaches %.3f'
        % (
            side,
            fh['little'],
        ),
    )
    _require(
        fh['thumb'] < fh['little'],
        'the %s thumb reaches %.3f, past the little finger at %.3f'
        % (
            side,
            fh['thumb'],
            fh['little'],
        ),
    )


def _check_column(pg):
    """Check 2b: the joint cloud is an anatomy's, and it sits ON the rig.

    The bone solvers still run — they are what EMITS the joints — so the
    column they lay out is still the thing to ask about. Box3.setFromObject is
    no use as the reference: for a SkinnedMesh it returns the bind-pose box at
    the mesh transform, not where the posed body actually is. The test is
    against the 31 live rig joints, which are exactly where the clip put them.
    """
    struct = pg.evaluate(COLUMN)
    _zyg_log.info(
        '    column: %d levels %s .. %s, y %.3f -> %.3f'
        % (struct['levels'], struct['names'][0], struct['names'][-1], struct['lo'], struct['hi'])
    )
    _zyg_log.info(
        '    fit: %d solved joints, furthest from any rig joint %.3f m at %s'
        % (struct['total'], struct['worst'], struct['at'])
    )
    # 24 presacral vertebrae + 5 sacral segments + the coccyx
    _require(struct['levels'] == 30, 'the column has %d levels, not 30' % struct['levels'])
    _require(struct['mono'], 'the column is not ordered bottom to top: %s' % struct['names'])
    _require(
        struct['names'][0] == 'Co' and struct['names'][-1] == 'C1',
        'the column runs %s .. %s'
        % (
            struct['names'][0],
            struct['names'][-1],
        ),
    )
    _require(
        struct['worst'] < 0.15 * struct['stature'],
        'a solved joint stands %.3f m from the nearest rig joint on a %.2f m '
        'body — that is not on the skeleton any more' % (struct['worst'], struct['stature']),
    )


def check_skeleton_mesh(pg):
    """Check 3 (a-e): THE SKELETON MESH.

    Its identity and rig, the Bones switch, the absence of the procedural
    passes, the baked-side routing, and that a tick costs a frame and moves
    with the clip. Returns the (3a) SKEL probe, which the CLI prints.
    """
    # ══ 3. THE SKELETON MESH ═════════════════════════════════════════════
    sk = _skeleton_identity(pg)
    _bones_switch(pg)
    _procedural_passes_gone(pg)
    _skeleton_side_routing(pg)
    _skeleton_tick(pg)
    return sk


def _skeleton_identity(pg):
    """(3a) it is the GLB's own skeleton, on the body's own rig — name, layer
    tag, vertex count, the 31 shared Bone objects, and the draw flags.

    Returns the SKEL probe dict.
    """
    pg.evaluate("() => MVA.applyView('anat')")
    pg.wait_for_timeout(300)
    sk = pg.evaluate(SKEL)
    _require(sk['found'], 'there is no MVA.skel — the Bones layer is empty. %s' % sk.get('note', ''))
    _zyg_log.info(
        '(3a) MVA.skel: name=%r skinned=%s layer=%r %d vertices / %d tris, '
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
    _require(sk['name'] == 'skeleton', 'MVA.skel is named %r' % sk['name'])
    _require(sk['isSkinnedMesh'], 'MVA.skel is not a SkinnedMesh — it cannot follow the clip')
    _require(sk['layer'] == 'bone', "MVA.skel is tagged %r, not 'bone'" % sk['layer'])
    _require(sk['vertices'] > 50_000, 'only %d vertices — that is not the anatomical skeleton' % sk['vertices'])
    _require(sk['bones'] == RIG_CHANNELS, 'the skeleton is skinned to %d bones, not %d' % (sk['bones'], RIG_CHANNELS))
    _require(
        sk['sameRigAsSkin'],
        'the skeleton is skinned to a DIFFERENT set of Bone objects than the '
        'skin (%r) — it would drift off the body' % sk['skinName'],
    )
    _require(
        sk['castShadow'] is False and sk['frustumCulled'] is False,
        'shadow/cull flags: castShadow=%s frustumCulled=%s' % (sk['castShadow'], sk['frustumCulled']),
    )
    _require(sk['renderOrder'] == 5, 'renderOrder is %s' % sk['renderOrder'])
    return sk


def _bones_switch(pg):
    """(3b) the Bones switch owns the skeleton; ``body: off`` does not — it
    hides the SKIN, never the layers."""
    pg.evaluate("() => document.getElementById('mva-bone').click()")
    pg.wait_for_timeout(250)
    off = pg.evaluate(SKEL)
    pg.evaluate("() => document.getElementById('mva-bone').click()")
    pg.wait_for_timeout(250)
    on = pg.evaluate(SKEL)
    pg.evaluate("() => document.getElementById('mva-body-off').click()")
    pg.wait_for_timeout(250)
    bo = pg.evaluate(SKEL)
    _zyg_log.info(
        '(3b) #mva-bone: off -> skel.visible=%s   on -> skel.visible=%s   '
        '#mva-body-off: skel.visible=%s   skin %r visible=%s'
        % (off['visible'], on['visible'], bo['visible'], bo['skinName'], bo['skinVisible'])
    )
    _require(off['visible'] is False, 'the Bones switch did not hide the skeleton')
    _require(on['visible'] is True, 'the Bones switch did not bring it back')
    _require(bo['visible'] is True, '`body: off` hid the skeleton — it hides the SKIN, never the layers')
    _require(bo['skinVisible'] is False, '`body: off` left the skin on screen')


def _procedural_passes_gone(pg):
    """(3c) the procedural bone/solid/socket passes are not created at all, the
    joints are untouched, and counts.bone is the fitted mesh's 135 pieces."""
    gfx = pg.evaluate(GFXQ)
    _zyg_log.info('(3c) GFX passes: %s' % json.dumps(gfx))
    for k in ('bone', 'solid', 'socket', 'boneH', 'solidH', 'socketH'):
        v = gfx.get(k)
        _require(v in ('undefined', 'null', 0), 'GFX.%s still draws %s instances' % (k, v))
    c = pg.evaluate('() => MVA.counts')
    _zyg_log.info('     MVA.counts: %s' % json.dumps(c))
    _check_pass_counts(c, gfx)


def _check_pass_counts(c, gfx):
    """Assert MVA.counts and the GFX query agree that only the joint and link
    passes are left, with the skeleton's own piece count on ``bone``."""
    _require(c['joint'] > 150, 'the joints were disturbed: %d' % c['joint'])
    _require(
        c['bone'] == SKEL_PIECES,
        'MVA.counts.bone is %s, not the %d pieces of the fitted skeleton'
        % (
            c['bone'],
            SKEL_PIECES,
        ),
    )
    # absent is the strongest form of zero: the solid/socket pools went with
    # the procedural bones, so MVA.counts has no key for them at all.
    _require(
        c.get('solid', 0) == 0 and c.get('socket', 0) == 0,
        'solid/socket counts are %s/%s'
        % (
            c.get('solid'),
            c.get('socket'),
        ),
    )
    _require(
        gfx['joint'] not in ('undefined', 'null') and gfx['joint'] > 0,
        'the joint mesh stopped drawing: %s' % gfx['joint'],
    )


def _skeleton_side_routing(pg):
    """(3d) the split routes the skeleton by baked side, and keeps the column
    whole; a whole view cuts nothing."""
    pg.evaluate("() => MVA.applyView('halfbare')")
    pg.wait_for_timeout(400)
    hb = pg.evaluate(SKEL)
    stv = pg.evaluate(PROBE)
    _check_side_histogram(hb, stv)
    pg.evaluate("() => MVA.applyView('anat')")
    pg.wait_for_timeout(300)
    an = pg.evaluate(SKEL)
    _zyg_log.info('     anat: skel uSideKeep=%s (whole)' % an['sideU'])
    _require(an['sideU'] == -1, 'a whole view still cuts the skeleton: uSideKeep=%s' % an['sideU'])


def _check_side_histogram(hb, stv):
    """Assert the halfbare aSide histogram: both halves and the axis present,
    the skeleton cut to the skeleton half, and the column marked whole.

    *hb* is the SKEL probe in view halfbare, *stv* the ready probe beside it.
    """
    want = SIDE_L if stv['splitSide'] else SIDE_R  # SK.skel
    other = SIDE_R if stv['splitSide'] else SIDE_L
    hist = {int(float(k)): v for k, v in hb['sideHist'].items()}
    _zyg_log.info(
        '(3d) halfbare: aSide histogram %s  (L=%d R=%d AXIS=%d)'
        % (
            json.dumps({str(k): v for k, v in sorted(hist.items())}),
            hist.get(SIDE_L, 0),
            hist.get(SIDE_R, 0),
            hist.get(SIDE_AXIS, 0),
        )
    )
    _zyg_log.info(
        '     halfbare: skel uSideKeep=%s  skin uSideKeep=%s  '
        'SK.skel=%d SK.mus=%d' % (hb['sideU'], hb['skinSideU'], want, other)
    )
    _require(hb['hasSide'], 'the skeleton geometry has no aSide attribute')
    for s, nm in ((SIDE_L, 'left'), (SIDE_R, 'right'), (SIDE_AXIS, 'axis')):
        _require(hist.get(s, 0) > 0, 'no %s (aSide=%d) vertices on the skeleton: %s' % (nm, s, hist))
    _require(hb['sideU'] == want, 'the skeleton is cut to side %s but the skeleton half is %d' % (hb['sideU'], want))
    # the axial vertices are the column, and the shader keeps them on whichever
    # half the bone is drawn on — a half spine reads as a broken spine
    _require(hist[SIDE_AXIS] > 3000, 'only %d axial vertices — the column is not being marked' % hist[SIDE_AXIS])


def _skeleton_tick(pg):
    """(3e) a tick costs a frame and the skeleton moves with the clip."""
    pg.evaluate('() => { MVR.paused = false; if (MVR.action) MVR.action.paused = false; }')
    pg.wait_for_timeout(200)
    s1 = pg.evaluate(SKEL_TICK)
    pg.wait_for_timeout(500)
    s2 = pg.evaluate(SKEL_TICK)
    skel_move = _tick_drift(s1, s2)
    _zyg_log.info(
        '(3e) tick cost %.2f ms then %.2f ms;  LeftForeArm moved %.4f m in 0.5 s' % (s1['ms'], s2['ms'], skel_move)
    )
    _require(s2['ms'] < 4.0, 'a tick costs %.2f ms' % s2['ms'])
    _require(skel_move > 1e-4, 'LeftForeArm did not move in half a second — the clip is not driving the rig')


def _tick_drift(s1, s2):
    """How far the sampled bone moved between two SKEL_TICK samples, in metres."""
    return sum((a - b) ** 2 for a, b in zip(s1['p'], s2['p'])) ** 0.5
