# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Movement Studio anatomy proof — checks 4 to 10b, and the hand shot.

The écorché, what is actually drawn, the translucent skin, the clip tracking,
the frame cost, the view menu and the split holding over a moving clip. Every
function here was a contiguous section of ``run`` before the 2026-10-09 split;
the assertions, the log lines, the screenshots and their order are unchanged.
"""

from .constants import BIND, EC_PROBE, PIXEL, SHOT, SHOT_HAND, SHOT_MUSCLE, _require, json, side_of

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

TICK_SPREAD = """() => {
      const t = [];
      for (let i = 0; i < 40; i++) {
        const a = performance.now(); MVA.tick(); t.push(performance.now() - a);
      }
      t.sort((x, y) => x - y);
      return {mean: t.reduce((s, v) => s + v, 0) / t.length,
              med: t[t.length >> 1], max: t[t.length - 1], n: t.length};
    }"""

DRAWN = """() => {
      const g = MVA.__gfx();
      return {cap: g.cap, count: {joint: g.joint.count, link: g.link.count},
              jointH: g.jointH.count};
    }"""

SKIN = """() => {
      let o = null;
      MVR.inner.traverse(m => {
        if (m.userData && m.userData.mvaLayer) return;
        if ((m.isMesh||m.isSkinnedMesh) && m.material && !o)
          o = {opacity: m.material.opacity, transparent: m.material.transparent,
               depthWrite: m.material.depthWrite, visible: m.visible};
      });
      return o;
    }"""

MOVE = """async () => {
      const A = window.MVA;
      MVR.paused = false; if (MVR.action) MVR.action.paused = false;
      const grab = () => A.__joints().slice(0, 240).map(j => j.p.clone());
      const t0 = MVR.mixer.time, a = grab();
      await new Promise(r => setTimeout(r, 900));
      const t1 = MVR.mixer.time, b = grab();
      let mx = 0;
      for (let i = 0; i < Math.min(a.length, b.length); i++)
        mx = Math.max(mx, a[i].distanceTo(b[i]));
      return {dt: +(t1 - t0).toFixed(3), moved: +mx.toFixed(4)};
    }"""

FRAME_COST = """() => {
      const A = window.MVA, t0 = performance.now();
      for (let i = 0; i < 20; i++) A.tick();
      return +((performance.now() - t0) / 20).toFixed(3);
    }"""

MENU = """() => ({
      open: !document.getElementById('mva-viewmenu').hidden,
      thumbs: Object.keys(MVA.__thumbs()).length,
      ms: MVA.thumbMs ? +MVA.thumbMs.toFixed(0) : 0,
      err: MVA.thumbErr || '',
      small: Object.values(MVA.__thumbs()).filter(u => !u || u.length < 2000).length})"""

HOVER_PREVIEW = """() => {
      const e = document.getElementById('mva-prev'), i = e && e.querySelector('img');
      return !!(e && e.classList.contains('on') && i && i.naturalWidth > 0);
    }"""

SPLIT = """async () => {
      const g = () => { const p = MVA.__clip();
        return p ? p.normal.toArray().concat([p.constant]) : null; };
      const a = g();
      MVR.paused = false; if (MVR.action) MVR.action.paused = false;
      await new Promise(r => setTimeout(r, 900));
      MVA.tick();
      const b = g();
      return {split: MVA.split, name: MVA.viewName(), hidden:
                document.getElementById('mva-viewmenu').hidden,
              moved: (a && b) ? +(Math.abs(a[3] - b[3]) + Math.abs(a[0] - b[0])).toFixed(5) : -1};
    }"""

HELD = """async () => {
      const g = MVA.__gfx(), sk = MVA.skel, ec = MVA.ec;
      const a0 = sk.geometry.attributes.aSide;
      const b0 = ec.geometry.attributes.aSide;
      const v0 = a0.version, w0 = b0.version;
      // joint / jointH / link are the only instanced passes there are: the
      // muscle, deep and sheet passes went with the procedural anatomy, so
      // reading them here would throw before a single frame was sampled.
      const snap = () => ({
        joint: g.joint.count, jointH: g.jointH.count, link: g.link.count,
        skelSide: sk.material.userData.__sideU.value,
        ecSide: ec.material.userData.__sideU.value,
        skelSideAttr: sk.geometry.attributes.aSide === a0 ? 1 : 0,
        ecSideAttr: ec.geometry.attributes.aSide === b0 ? 1 : 0,
        skelSideVer: sk.geometry.attributes.aSide.version - v0,
        ecSideVer: ec.geometry.attributes.aSide.version - w0
      });
      // MVR.paused stops the tab's own loop advancing the mixer, so the eight
      // frames are exactly the eight asked for. The ACTION must stay unpaused:
      // a paused AnimationAction has an effective timeScale of 0, so
      // mixer.setTime() retimes nothing and every sample is the same pose —
      // which is why `moved` below is asserted and not merely printed.
      MVR.paused = true; if (MVR.action) MVR.action.paused = false;
      const seen = [], hip = [];
      for (let f = 0; f < 8; f++) {
        MVR.mixer.setTime(0.28 * f);
        MVR.inner.updateMatrixWorld(true);
        MVA.tick();
        await new Promise(r => setTimeout(r, 40));
        seen.push(snap());
        const m = MVA.atlas.bones.LeftForeArm.matrixWorld.elements;
        hip.push([m[12], m[13], m[14]]);
      }
      let moved = 0;
      for (let i = 1; i < hip.length; i++) {
        const d = Math.hypot(hip[i][0] - hip[0][0], hip[i][1] - hip[0][1],
                             hip[i][2] - hip[0][2]);
        if (d > moved) moved = d;
      }
      const base = seen[0], bad = [];
      for (let i = 1; i < seen.length; i++)
        for (const k in base) if (base[k] !== seen[i][k])
          bad.push(k + ' f0=' + base[k] + ' f' + i + '=' + seen[i][k]);
      return {base: base, bad: bad, frames: seen.length, moved: +moved.toFixed(4)};
    }"""

HAND_FRAME = """() => {
          const z = parseFloat(
            getComputedStyle(document.documentElement).zoom || '1') || 1;
          const r = document.querySelector('#view-movement .cs-main')
                      .getBoundingClientRect();
          return {x: Math.round(r.left * z), y: Math.round(r.top * z),
                  width: Math.round(r.width * z),
                  height: Math.round(r.height * z)};
        }"""

HAND_CAMERA = """() => {
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


def check_ecorche(pg, shoot):
    """Check 4 (a-e): THE ÉCORCHÉ.

    Its identity and atlas, the Muscles switch, which half each layer keeps,
    the pixel probe that says the figure is RED, and the per-frame cost. When
    *shoot* is true the muscle screenshot is written. Returns the (4a) EC_PROBE
    dict, which the CLI prints and (4e) reads MVA.ms from.
    """
    # ══ 4. THE ÉCORCHÉ ═══════════════════════════════════════════════════
    p = _ecorche_probe(pg)
    _muscle_switch(pg)
    _layer_halves(pg)
    _ecorche_is_red(pg, shoot)
    _anatomy_frame_cost(pg, p)
    return p


def _ecorche_probe(pg):
    """(4a) it is the body, wearing the atlas — the body geometry, the
    8192x4096 remap, the albedo and bump, the shared skeleton, the panel.

    Returns the EC_PROBE dict.
    """
    p = pg.evaluate(EC_PROBE)
    _zyg_log.info(
        '(4a) %s  layer=%s  verts=%d (body %d)  aSide=%d  uvAtlas=%s (miss %s)'
        % (p['name'], p['layer'], p['verts'], p['bodyVerts'], p['aSide'], p['uvAtlas'], p['uvMiss'])
    )
    _zyg_log.info(
        '     albedo %dx%d  bump %d wide  bumpScale=%s  roughness=%s  '
        'renderOrder=%d  bindMode=%s(body %s)  sameSkeleton=%s  sibling=%s'
        % (
            p['mapW'],
            p['mapH'],
            p['bumpW'],
            p['bumpScale'],
            p['roughness'],
            p['renderOrder'],
            p['bindMode'],
            p['bodyBindMode'],
            p['sameSkeleton'],
            p['sibling'],
        )
    )
    _zyg_log.info('     panel: écorché %s %s   counts.muscle=%d' % (p['ecName'], p['ecSize'], p['countsMuscle']))
    _check_ecorche_probe(p)
    return p


def _check_ecorche_probe(p):
    """Assert the EC_PROBE dict *p*: the écorché is a SkinnedMesh named
    ``ecorche``, tagged muscle, on the body's own geometry and skeleton, with
    the manifest atlas loaded and named in the panel."""
    _require(p['isSkinned'], 'MVA.ec is not a SkinnedMesh')
    _require(p['name'] == 'ecorche', "MVA.ec is named %r, not 'ecorche'" % p['name'])
    _require(p['layer'] == 'muscle', 'userData.mvaLayer is %r' % p['layer'])
    _require(
        p['verts'] == p['bodyVerts'],
        'the écorché is not on the body geometry: %d vs %d'
        % (
            p['verts'],
            p['bodyVerts'],
        ),
    )
    _require(p['aSide'] == p['bodyVerts'], 'aSide is missing or short: %d of %d' % (p['aSide'], p['bodyVerts']))
    _require(p['uvAtlas'] == '8192x4096', 'remapUV did not stamp the atlas: %r' % p['uvAtlas'])
    _require(p['uvMiss'] == 0, '%s uv pairs fell outside the atlas tiles' % p['uvMiss'])
    _require(
        not p['bodyUvAtlas'], 'the CLAY body was remapped too (userData shared by reference): %r' % p['bodyUvAtlas']
    )
    _require(
        p['mapW'] == 8192 and p['mapH'] == 4096,
        'the albedo is %dx%d, not the manifest 8192x4096'
        % (
            p['mapW'],
            p['mapH'],
        ),
    )
    _require(p['bumpW'] == 8192, 'the bump map did not load (width %d)' % p['bumpW'])
    _require(p['sameSkeleton'], 'the écorché is bound to a different skeleton')
    _require(p['sibling'], 'the écorché is not a sibling of the body')
    _require(p['countsMuscle'] == 1, 'counts.muscle is %d' % p['countsMuscle'])
    _require(
        p['ecName'] and p['ecSize'] == '8192x4096',
        'the panel does not name the atlas: %r %r'
        % (
            p['ecName'],
            p['ecSize'],
        ),
    )
    _require(not p['ecNote'], 'MVA.ecNote: %s' % p['ecNote'])


def _muscle_switch(pg):
    """(4b) the Muscles switch owns the écorché; ``body: off`` does not — it
    must only hide the skin."""
    pg.evaluate("() => MVA.applyView('anat')")
    pg.wait_for_timeout(200)
    was = side_of(pg, 'ec')['vis']
    pg.evaluate("() => document.getElementById('mva-muscle').click()")
    pg.wait_for_timeout(200)
    ecoff = side_of(pg, 'ec')['vis']
    pg.evaluate("() => document.getElementById('mva-muscle').click()")
    pg.wait_for_timeout(200)
    econ = side_of(pg, 'ec')['vis']
    pg.evaluate("() => document.getElementById('mva-body-off').click()")
    pg.wait_for_timeout(200)
    ecbodyoff = side_of(pg, 'ec')['vis']
    _zyg_log.info(
        '(4b) muscles on=%s -> click=%s -> click=%s ; body:off -> ec visible=%s' % (was, ecoff, econ, ecbodyoff)
    )
    _require(was and not ecoff and econ, 'the Muscles switch does not drive the écorché')
    _require(ecbodyoff, '`body: off` hid the écorché — it must only hide the skin')


def _layer_halves(pg):
    """(4c) which half each layer keeps in halfbare, halfskin and skin."""
    rows = {}
    for view in ('halfbare', 'halfskin', 'skin'):
        pg.evaluate('(k) => MVA.applyView(k)', view)
        pg.wait_for_timeout(250)
        rows[view] = {
            'ec': side_of(pg, 'ec'),
            'skel': side_of(pg, 'skel'),
            'skin': side_of(pg, 'skin'),
            'mus': pg.evaluate('() => MVA.splitSide ? 1 : 0'),
        }
        r = rows[view]
        _zyg_log.info(
            '(4c) %-9s ec side=%s vis=%s | skeleton side=%s vis=%s | skin side=%s vis=%s'
            % (view, r['ec']['v'], r['ec']['vis'], r['skel']['v'], r['skel']['vis'], r['skin']['v'], r['skin']['vis'])
        )
    _check_layer_halves(rows)


def _check_layer_halves(rows):
    """Assert the per-view side routing in *rows* (view -> layer -> side_of).

    SK.mus is the actor's LEFT (0) unless the halves were swapped, and the
    skeleton always takes the other half.
    """
    musSide = 1 if rows['halfbare']['mus'] else 0
    skelSide = 0 if musSide else 1
    _require(
        rows['halfbare']['ec']['v'] == musSide,
        'halfbare: the écorché keeps side %s, not the muscle half %s'
        % (
            rows['halfbare']['ec']['v'],
            musSide,
        ),
    )
    _require(
        rows['halfbare']['skel']['v'] == skelSide,
        'halfbare: the skeleton keeps side %s, not %s'
        % (
            rows['halfbare']['skel']['v'],
            skelSide,
        ),
    )
    _require(not rows['halfbare']['skin']['vis'], 'halfbare still shows the skin')
    _require(
        rows['halfskin']['ec']['v'] == musSide,
        'halfskin: the écorché keeps side %s, not %s'
        % (
            rows['halfskin']['ec']['v'],
            musSide,
        ),
    )
    _require(rows['halfskin']['skin']['vis'], 'halfskin does not show the skin')
    _require(
        rows['halfskin']['skin']['v'] == skelSide,
        'halfskin: the skin keeps side %s, not the skeleton half %s'
        % (
            rows['halfskin']['skin']['v'],
            skelSide,
        ),
    )
    _require(not rows['skin']['ec']['vis'], "view 'skin' still shows the écorché")


def _ecorche_is_red(pg, shoot):
    """(4d) A PIXEL PROBE: at the bind pose in view 'anat' the figure is RED.

    Writes the muscle screenshot when *shoot* is true.
    """
    pg.evaluate("() => MVA.applyView('anat')")
    pg.evaluate(BIND)
    pg.wait_for_timeout(400)
    px = pg.evaluate(PIXEL)
    _zyg_log.info(
        '(4d) view anat, bind pose: %d lit pixels in box %s — mean RGB '
        '%.1f / %.1f / %.1f  (R - G = %+.1f, red pixels %.0f %%)'
        % (px['n'], px['box'], px['r'], px['g'], px['b'], px['r'] - px['g'], px['redFrac'] * 100)
    )
    _check_red(px)
    if shoot:
        pg.screenshot(path=SHOT_MUSCLE)


def _check_red(px):
    """Assert the PIXEL probe *px*: the figure is in the frame, and its mean
    red channel stands more than 25 above its green."""
    _require(px['n'] > 500, 'only %d lit pixels — the figure is not in the frame' % px['n'])
    _require(
        px['r'] > px['g'] + 25,
        'the écorché is not red: mean R %.1f, G %.1f (R - G = %+.1f, wanted > 25)'
        % (
            px['r'],
            px['g'],
            px['r'] - px['g'],
        ),
    )


def _anatomy_frame_cost(pg, p):
    """(4e) the per-frame anatomy cost over 40 MVA.tick() calls.

    MVA.ms (on the EC_PROBE dict *p*) is the ONE-TIME build cost — measure()
    walking every vertex, skelAdopt, pool allocation — and can never be under
    a few ms; what the budget is about is the per-frame cost.
    """
    tick = pg.evaluate(TICK_SPREAD)
    _zyg_log.info(
        '(4e) per frame over %d MVA.tick() calls: mean %.3f ms, median %.3f ms, '
        'worst %.3f ms  (one-time build MVA.ms = %.1f ms)'
        % (tick['n'], tick['mean'], tick['med'], tick['max'], p['ms'])
    )
    _require(tick['mean'] < 3.0, 'the anatomy costs %.3f ms a frame (wanted < 3)' % tick['mean'])


def check_drawn_and_tracking(pg, shoot):
    """Checks 5/6, 7, 8 and 9.

    Nothing clipped and what was solved is what is drawn; the actor went
    translucent; the solve tracks the playing clip (and the main screenshot is
    written when *shoot* is true); a frame's worth of work is a frame's worth.
    Returns the MVA.counts dict the CLI prints.
    """
    c = _nothing_clipped(pg)
    _skin_translucent(pg)
    _tracks_the_clip(pg, shoot)
    _frame_cost(pg)
    return c


def _nothing_clipped(pg):
    """(5./6.) nothing clipped, and what was solved is what is drawn.

    Joints and links are the two instanced passes left: the bone shafts are a
    mesh now and the bellies are an atlas, so there is nothing else here that a
    pool could overflow. Returns MVA.counts.
    """
    pg.evaluate("() => MVA.applyView('all')")
    pg.wait_for_timeout(400)
    c = pg.evaluate('() => MVA.counts')
    gfx2 = pg.evaluate(DRAWN)
    _check_drawn(c, gfx2)
    return c


def _check_drawn(c, gfx2):
    """Assert each instanced pass fits its buffer and drew exactly what was
    solved — *c* is MVA.counts, *gfx2* the DRAWN query."""
    for k in ('joint', 'link'):
        _require(c[k] <= gfx2['cap'][k], '%s clipped: solved %d, buffer holds %d' % (k, c[k], gfx2['cap'][k]))
        _require(gfx2['count'][k] == c[k], '%s: solved %d but drew %d' % (k, c[k], gfx2['count'][k]))
    _zyg_log.info('    drawn: %s (+%d head joints)  buffers %s' % (gfx2['count'], gfx2['jointH'], gfx2['cap']))


def _skin_translucent(pg):
    """(7.) the actor went translucent, or none of the above is visible."""
    skin = pg.evaluate(SKIN)
    _require(
        skin and skin['transparent'] and skin['opacity'] < 0.6,
        'the body is still opaque, so the anatomy is inside a solid: %s' % skin,
    )
    _zyg_log.info(
        '    skin: opacity %.2f, depthWrite %s, visible %s' % (skin['opacity'], skin['depthWrite'], skin['visible'])
    )


def _tracks_the_clip(pg, shoot):
    """(8.) it tracks the clip: the mixer advances and the joints move with it.

    Writes the main screenshot when *shoot* is true.
    """
    move = pg.evaluate(MOVE)
    _zyg_log.info('    tracking: mixer advanced %.3f s, furthest joint moved %.3f m' % (move['dt'], move['moved']))
    _require(move['dt'] > 0.2, 'the clip is not playing (%.3f s)' % move['dt'])
    _require(move['moved'] > 0.01, 'the anatomy is frozen while the clip plays (%.4f m)' % move['moved'])

    if shoot:
        pg.screenshot(path=SHOT)


def _frame_cost(pg):
    """(9.) a frame's worth of work.

    Two skinned meshes more than the procedural build had (the skeleton and the
    écorché both ride the body's skeleton), so the ceiling is 4 ms.
    """
    cost = pg.evaluate(FRAME_COST)
    _zyg_log.info('    solve + draw: %.2f ms a frame' % cost)
    _require(cost < 4.0, 'a frame of anatomy costs %.1f ms — that is a stall' % cost)


def check_view_menu(pg):
    """Checks 10 and 10b: THE VIEW MENU, and that the halves hold while the
    body moves.

    The icon opens the menu, every view previews from this actor, a hover shows
    the picture, a split view applies and closes the menu, the clip plane rides
    the body, the per-half membership never churns over 8 frames, and the icon
    says Custom once a switch is moved by hand. Leaves view 'all' applied.
    """
    _view_menu_previews(pg)
    _split_plane_tracks(pg)
    _split_holds(pg)
    _custom_after_manual_toggle(pg)


def _view_menu_previews(pg):
    """(10.) the view menu: one icon that names the half-dozen combinations of
    the four switches anyone actually wants, each row previewed from THIS actor.

    Driven the way a person drives it — the button is clicked, not
    MVA.applyView() — because the wiring between the panel's HTML and the state
    is the half that can rot. Returns the view keys.
    """
    views = pg.evaluate('() => (window.MVA.views || []).map(v => v.k)')
    _require(len(views) >= 6, 'the view menu offers %d views' % len(views))
    _require(pg.evaluate("() => !!document.getElementById('mva-view')"), 'the view icon is not in the panel')
    pg.click('#mva-view')
    pg.wait_for_timeout(1500)
    menu = pg.evaluate(MENU)
    _check_menu(menu, views)
    _zyg_log.info('    view menu: %d views, %d previews in %d ms' % (len(views), menu['thumbs'], menu['ms']))

    pg.hover('#mva-viewmenu .mva-vi[data-k="%s"]' % views[0])
    pg.wait_for_timeout(300)
    _require(pg.evaluate(HOVER_PREVIEW), 'hovering a view shows no preview image')
    return views


def _check_menu(menu, views):
    """Assert the MENU probe: it opened, and every view came back with a
    preview that is not blank.

    A preview is rendered to an offscreen target and sRGB-encoded by hand; a
    blank or near-blank data URL means that path broke, not that the view is
    empty — even "skin only" is a whole body.
    """
    _require(menu['open'], 'the view menu did not open on the icon')
    _require(
        menu['thumbs'] == len(views),
        'only %d of %d previews were built (%s)'
        % (
            menu['thumbs'],
            len(views),
            menu['err'],
        ),
    )
    _require(menu['small'] == 0, '%d previews came back blank' % menu['small'])


def _split_plane_tracks(pg):
    """The half-and-half views cut on a plane; it has to ride the BODY, or a
    clip that turns the actor walks it out of its own midline."""
    pg.click('#mva-viewmenu .mva-vi[data-k="halfbare"]')
    pg.wait_for_timeout(500)
    split = pg.evaluate(SPLIT)
    _require(
        split['split'] == 1 and split['hidden'], 'clicking a split view did not apply it and close the menu: %s' % split
    )
    _require(split['moved'] > 1e-4, 'the split plane does not follow the moving body (%s)' % split['moved'])
    _zyg_log.info('    split: %s, head plane tracks the pose (%.4f over 0.9 s)' % (split['name'], split['moved']))


def _split_holds(pg):
    """(10b.) AND THE HALVES HOLD WHILE THE BODY MOVES.

    (2026-09-23, operator: "the halfs dont stay perfectly aligned when moving,
    parts skeleton move into the other half and vice versa".) That came of
    deciding membership with ONE plane through the Hips: under a plane, which
    half a primitive lands in is a function of the POSE, so an arm swinging
    across the midline gets sliced and the counts churn every frame.
    """
    held = pg.evaluate(HELD)
    _zyg_log.info('    split over %d frames: LeftForeArm swung %.3f m' % (held['frames'], held['moved']))
    _check_held(held)
    _zyg_log.info('    split HELD: %s' % json.dumps(held['base']))


def _check_held(held):
    """Assert the HELD samples: the body really moved, nothing in the per-frame
    snapshot changed, and neither aSide attribute was replaced.

    Membership is an anatomical fact now, and since task 4/5 it is a fact in
    three different places, so all three are asserted over the same 8 frames of
    a moving clip:
      · the JOINT passes — per-half instance counts, identical every frame
      · the skeleton's and the écorché's uSideKeep uniforms — never touched
      · each mesh's aSide attribute — the SAME BufferAttribute object at the
        same .version, i.e. nobody is re-baking sides per frame
    """
    _require(
        held['moved'] > 0.02,
        'the body did not move over the 8 sampled frames (%.4f m) — the test would prove nothing' % held['moved'],
    )
    _require(
        not held['bad'],
        'the split moved while the body did — membership is still a function '
        'of the pose:\n      ' + '\n      '.join(held['bad'][:6]),
    )
    _require(
        held['base']['skelSideAttr'] == 1 and held['base']['ecSideAttr'] == 1,
        'the aSide attribute was replaced between frames: %s' % held['base'],
    )


def _custom_after_manual_toggle(pg):
    """The icon must not claim a preset once a switch is moved by hand; leaves
    view 'all' applied."""
    pg.evaluate("() => document.getElementById('mva-joint').click()")
    pg.wait_for_timeout(300)
    _require(
        pg.evaluate('() => MVA.viewName()') == 'Custom',
        'the icon still names a preset after a layer was toggled by hand',
    )
    pg.evaluate("() => MVA.applyView('all')")
    pg.wait_for_timeout(300)


def shoot_hand(pg):
    """Frame the left hand from its own measured frame and screenshot it.

    The hand is framed off the palm and a little down the fingers, so the shot
    is the same view whatever the clip happens to be doing with the arm. The
    GUI runs at html{zoom:.67}: getBoundingClientRect answers in CSS pixels
    INSIDE that zoom and screenshot clips are device pixels, so a rect handed
    over raw crops the wrong two thirds of the page.
    """
    pg.evaluate("() => MVA.applyView('bones')")
    pg.evaluate(BIND)
    pg.wait_for_timeout(400)
    frame = pg.evaluate(HAND_FRAME)
    pg.evaluate(HAND_CAMERA)
    pg.wait_for_timeout(600)
    pg.screenshot(path=SHOT_HAND, clip=frame)
