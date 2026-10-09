// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* movement_rig_anatomy.js — the body under the clip, not a stick figure (2026-09-23, pruned
   2026-09-24).

   WHY THIS EXISTS. Movement Studio drew MVR.skeleton, a stock THREE.SkeletonHelper over the
   cmu_mb rig: 31 GL lines, `linewidth: 2` (which WebGL ignores on every desktop driver, so
   always exactly one pixel), and no hand past the wrist — cmu_mb carries LeftHand,
   LeftFingerBase, LeftHandIndex1 and LThumb, so a whole hand was three segments. A body has far
   more joints than that, and bones and muscles too.

   THE RIG IS NOT THE BODY, AND IT NEVER WILL BE. cmu_mb has 31 joints because CMU's optical
   capture had 31 markers, and every clip in the library is authored against those channels —
   adding real joints to the rig would orphan the whole motion library. So the rig stays as it
   is, and this file SOLVES the articulations on top of it every frame: 262 joints and 192
   links, off those 31 live transforms plus one measurement of the mesh.

   THREE LAYERS, AND ONLY ONE OF THEM IS SOLVED HERE:
     JOINTS   this file's own work — every articulation a real body has and the
              rig does not, as a sphere, plus the thin chain that links them.
              The one thing no mesh can give you: connectivity is not a surface.
     BONES    the actor's OWN fitted anatomical skeleton, 135 CC0 pieces, a real
              SkinnedMesh weighted to the same 31 joints, shipped in the GLB and
              adopted by skelAdopt(). Not drawn in code at all.
     MUSCLES  the écorché — the body's own geometry re-bound to the body
              skeleton, inset 1.5 mm, wearing the male_ecorche atlas. Also a
              mesh, also not drawn in code.

   WHAT WAS DELETED, AND WHY IT HAD TO BE. The first cut solved the bones and the muscles
   procedurally too: ~570 lathed shafts and sections, ~25 ellipsoid plates, ~96 spindle bellies
   over a deep sleeve, a table of named muscles with origins and insertions, seven sheets for a
   face. Careful work, and a COPY — once the real skeleton mesh and the real écorché were fitted
   to this body it was a worse copy of geometry already on screen: no shaft built out of
   capsules beats a scanned femur, no spindle beats a painted deltoid. All gone, with its pools,
   caps, materials and draw passes. What the solvers keep is the part that was never duplicated:
   WHERE THE JOINTS ARE. solveColumn / solveRibs / solvePelvis / solveGirdle / solveSkull /
   solveLimbs / solveHand / solveFoot now read as "emit the articulations the rig has no channel
   for" — both ends of every rib, the sternal angle, the sacro-iliac joint and the pubic
   symphysis, the acromioclavicular joint, the temporomandibular hinge, every metacarpal,
   metatarsal and phalangeal joint. Nothing that placed a joint was touched, so the count is
   unchanged.

   MEASURED, NOT GUESSED. At load (before the mixer has ticked once, so the pose is still the
   bind pose) measure() buckets every vertex onto the bone that owns it, giving in each bone's
   own local frame: the hand's three axes and its length, breadth and palm thickness; the foot's
   length, breadth and height; the skull box; a banded width/depth profile up the torso; a
   radius profile along every limb. The fingers, ribcage and pelvis are sized from those, so a
   fitted Abel and the CC0 base body get different hands — they have them.

   FOUR THINGS THAT COST A DAY EACH AND STILL APPLY. (1) At the bind pose there is no skinning
   to do, so a bind-world vertex is matrixWorld · bindMatrixInverse · bindMatrix · v, one matrix
   and no weights; SkinnedMesh.boneTransform is the trap, because this GLB's bindMode is
   'attached' and three rebuilds bindMatrixInverse from matrixWorld on every updateMatrixWorld —
   sizes came back as 250 m heads. (2) Read a BufferAttribute with getX/getY/getZ, never
   getComponent: it does not exist on an InterleavedBufferAttribute, which is what a glTF hands
   you. (3) updateMatrixWorld() the actor BEFORE solving, or every frame is placed from the
   previous pose. (4) A render target in r147 does not get outputEncoding applied, so the
   thumbnails need the sRGB transfer by hand.

   WHAT IS HONESTLY NOT ANIMATED. No clip carries finger or toe channels, because cmu_mb has
   none. The digits are solved in the hand's and the foot's own frame and ride those bones
   rigidly — they follow a punch, they do not close into a fist, and the panel says so.
   Everything proximal to the wrist and the ankle IS driven by the clip, ribcage and column
   included.

   THE SPLIT IS A BAKED TAG, NOT A PLANE. An arm swings across the midline and a turned head
   leaves any fixed plane, so the half a part belongs to is decided when it is SOLVED — `SD`,
   and per-vertex `aSide` for the meshes — and a lateral part is drawn whole wherever the pose
   has carried it. Only the head is really cut, and it carries the one real plane. See WHICH
   HALF, below.

   QUALITY IS GEOMETRY, NOT linewidth: a joint is a real sphere and a link a real capsule,
   instanced, depth-tested normally. And THE ACTOR STAYS VISIBLE — the clay goes translucent
   with an emissive floor so it is still a body you look THROUGH, or its own wireframe, or off.
   The VIEW menu is the shortcut through all of it, one row per way of looking at a body, each
   with a thumbnail rendered from THIS actor in THIS pose.

   SEAM. movement_rig.js calls MVA.build / MVA.drop / MVA.tick / MVA.controls / MVA.wire and
   nothing else; with this file absent the tab is exactly what it was. The bundle is
   concatenated in name order and 'movement_rig.js' < 'movement_rig_anatomy.js', so MVR is
   already up here. */
(function () {
  if (typeof THREE === 'undefined' || typeof MVST3 === 'undefined' || !window.MVR) return;

  var MVA = window.MVA = {
    on: { bone: true, joint: true, muscle: true },
    skin: 0.45,          // clay opacity while any layer is up
    body: 'solid',       // 'solid' | 'mesh' | 'off' — how the actor is drawn
    atlas: null,         // the measured body, or null
    skel: null,          // the actor's own fitted skeleton mesh — the Bones layer
    ec: null,            // the écorché skin on the body's own geometry — the Muscles layer
    ecName: '',          // which atlas it is wearing ('male_ecorche')
    ecSize: '',          // that atlas's size ('8192x4096')
    ecNote: '',          // why the Muscles layer is empty, when it is
    counts: { joint: 0, link: 0, bone: 0, muscle: 0 },
    note: '',            // what measure() could not reach
    ready: false
  };

  function lsGet(k, d) { try { var v = localStorage.getItem('mva.' + k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem('mva.' + k, String(v)); } catch (e) {} }
  MVA.on.bone   = lsGet('bone', '1') === '1';
  MVA.on.joint  = lsGet('joint', '1') === '1';
  MVA.on.muscle = lsGet('muscle', '1') === '1';
  MVA.skin = Math.min(1, Math.max(0, parseFloat(lsGet('skin', '0.45'))));
  if (!isFinite(MVA.skin)) MVA.skin = 0.45;
  MVA.body = ({ solid: 1, mesh: 1, off: 1 }[lsGet('body', 'solid')]) ? lsGet('body', 'solid') : 'solid';

  /* Same conversion movement_rig.js does: with legacy colour management a material.color handed
     in raw sRGB is gamma-encoded twice on the way out. */
  function srgb(hex) {
    var c = new THREE.Color(hex);
    if (MVST3.renderer && THREE.sRGBEncoding !== undefined
        && MVST3.renderer.outputEncoding === THREE.sRGBEncoding && c.convertSRGBToLinear)
      c.convertSRGBToLinear();
    return c;
  }

  /* ── the rig's names ─────────────────────────────────────────────────────
     side 0 = the character's LEFT (cmu_mb spells it Left... and L..., side 1 the right. Every
     structure below is written once and run for both. */
  var SIDED = {
    Shoulder:   ['LeftShoulder', 'RightShoulder'],
    Arm:        ['LeftArm', 'RightArm'],
    ForeArm:    ['LeftForeArm', 'RightForeArm'],
    Hand:       ['LeftHand', 'RightHand'],
    FingerBase: ['LeftFingerBase', 'RightFingerBase'],
    HandIndex:  ['LeftHandIndex1', 'RightHandIndex1'],
    Thumb:      ['LThumb', 'RThumb'],
    HipJoint:   ['LHipJoint', 'RHipJoint'],
    UpLeg:      ['LeftUpLeg', 'RightUpLeg'],
    Leg:        ['LeftLeg', 'RightLeg'],
    Foot:       ['LeftFoot', 'RightFoot'],
    ToeBase:    ['LeftToeBase', 'RightToeBase']
  };
  var AXIAL = ['Hips', 'LowerBack', 'Spine', 'Spine1', 'Neck', 'Neck1', 'Head'];
  function bn(side, key) { return SIDED[key][side]; }

  /* ── scratch ─────────────────────────────────────────────────────────────
     Everything below runs 60 times a second. Vectors come from these, never from `new`, and
     every pool grows once and is then reused. */
  var V = [], VN = 0;
  function v3() { var v = V[VN] || (V[VN] = new THREE.Vector3()); VN++; return v; }
  function vset(x, y, z) { return v3().set(x, y, z); }
  function vcp(a) { return v3().copy(a); }
  /* a + b*s */
  function vma(a, b, s) { return v3().copy(a).addScaledVector(b, s); }
  function vlerp(a, b, t) { return v3().copy(a).lerp(b, t); }
  function vsub(a, b) { return v3().subVectors(a, b); }
  function vcross(a, b) { return v3().crossVectors(a, b); }
  /* b with any component along the unit vector `ax` removed, normalised */
  function vperp(b, ax) {
    var o = vcp(b);
    return o.addScaledVector(ax, -o.dot(ax)).normalize();
  }

  var _m4 = new THREE.Matrix4(), _q = new THREE.Quaternion(), _s = new THREE.Vector3();
  var UPY = new THREE.Vector3(0, 1, 0), IDQ = new THREE.Quaternion();

  /* ── the per-frame result pools ──────────────────────────────────────────
     solve() resets the cursors and refills; nothing is allocated after the first frame. A joint
     is {p, r, sd}; a link is a pair of joint indices. */
  var P = { joint: [], link: [] };
  var C = { joint: 0, link: 0 };
  /* landmarks one solver leaves behind for the next: solveLimbs has to hang the arm off the
     acromion solveGirdle placed, and the digits ride the wrist and the ankle. Refilled every
     frame; the vectors are scratch and live until the next solve. */
  var AN = { lvl: {}, tip: [], skull: null, stern: [], acr: [], jacr: [], scapMed: [], scapInf: [], rib: [],
             crest: [], hip: [], si: [], symph: null };

  /* ── WHICH HALF OF THE BODY THIS BELONGS TO ──────────────────────────────
     (2026-09-23, operator: the halves of a split view did not stay put while the clip
     played — "parts skeleton move into the other half and vice versa".) The first cut
     tested one clipping plane through the Hips, and a plane cannot know what a limb IS.
     Membership is an anatomical fact now, fixed when the part is SOLVED; `SD` is the
     side the emitting solver is on and every primitive records it:

         0  the actor's left      2  on the head's midline (the one thing
         1  the actor's right        that really is cut, see below)
         3  on the body's axis

     The reference plate settles what happens to each. Its lateral structures — ribs,
     ilium, the whole arm — belong wholly to one side and are drawn whole. Its vertebral
     column is drawn WHOLE on the bone side, down the seam, because a half-spine reads as
     a broken spine. Only its head is genuinely cut, so the head keeps a real plane built
     from the HEAD's own frame, and a turn of the neck turns the cut with it. */
  var SD = 3;
  var SIDE_L = 0, SIDE_R = 1, SIDE_HEAD = 2, SIDE_AXIS = 3;

  function joint(p, r) {
    var o = P.joint[C.joint] || (P.joint[C.joint] = { p: new THREE.Vector3(), r: 0, sd: 3 });
    o.p.copy(p); o.r = r; o.sd = SD; C.joint++;
    return C.joint - 1;
  }
  function link(i, j) {
    var o = P.link[C.link] || (P.link[C.link] = { i: 0, j: 0, sd: 3 });
    o.i = i; o.j = j; o.sd = SD; C.link++;
  }
  /* ── measuring the body ──────────────────────────────────────────────────
     Once per model, at the bind pose; every number the solver needs about THIS body is taken
     here and the mesh is never read again. */

  /* the bone sets a vertex can be charged to, and the frame each group is measured in */
  function groupSpec(side) {
    return [
      ['hand' + side, [bn(side, 'Hand'), bn(side, 'FingerBase'), bn(side, 'HandIndex'), bn(side, 'Thumb')], bn(side, 'Hand')],
      ['foot' + side, [bn(side, 'Foot'), bn(side, 'ToeBase')], bn(side, 'Foot')],
      ['arm' + side, [bn(side, 'Arm')], bn(side, 'Arm')],
      ['fore' + side, [bn(side, 'ForeArm')], bn(side, 'ForeArm')],
      ['upleg' + side, [bn(side, 'UpLeg')], bn(side, 'UpLeg')],
      ['leg' + side, [bn(side, 'Leg')], bn(side, 'Leg')]
    ];
  }

  /* a limb's thickness along its own bone: mean distance of its vertices from the bone axis, in
     NBANDS bands from bone head to child. Every joint radius in a limb is a fraction of this,
     so it is THIS body's flesh. */
  var NBANDS = 8;
  function limbProfile(pts, head, tail) {
    var ax = vsub(tail, head), len = ax.length();
    if (len < 1e-6) return null;
    ax.multiplyScalar(1 / len);
    var sum = new Float64Array(NBANDS), n = new Float64Array(NBANDS), i, k;
    var d = new THREE.Vector3();
    for (i = 0; i < pts.length; i += 3) {
      d.set(pts[i], pts[i + 1], pts[i + 2]).sub(head);
      var t = d.dot(ax) / len;
      if (t < -0.15 || t > 1.15) continue;
      k = Math.max(0, Math.min(NBANDS - 1, Math.floor(t * NBANDS)));
      sum[k] += d.addScaledVector(ax, -t * len).length(); n[k]++;
    }
    var r = [], last = 0;
    for (k = 0; k < NBANDS; k++) { r.push(n[k] > 6 ? sum[k] / n[k] : 0); }
    for (k = 0; k < NBANDS; k++) { if (r[k] > 0) last = r[k]; else r[k] = last; }
    for (k = NBANDS - 1; k >= 0; k--) { if (r[k] > 0) last = r[k]; else r[k] = last; }
    return { len: len, r: r };
  }
  function profAt(prof, t) {
    if (!prof) return 0.04;
    var x = Math.max(0, Math.min(0.999, t)) * NBANDS - 0.5;
    var i = Math.floor(x), f = x - i;
    if (i < 0) return prof.r[0];
    if (i >= NBANDS - 1) return prof.r[NBANDS - 1];
    return prof.r[i] * (1 - f) + prof.r[i + 1] * f;
  }

  /* principal axes of a point cloud — a 3x3 Jacobi on its covariance. Hand and foot are
     measured this way because neither the rig nor the glTF says which way a palm faces: the
     cloud does. Longest axis along, shortest through. */
  function principal(pts) {
    var n = pts.length / 3, i, a, b;
    if (n < 24) return null;
    var c = [0, 0, 0];
    for (i = 0; i < pts.length; i += 3) { c[0] += pts[i]; c[1] += pts[i + 1]; c[2] += pts[i + 2]; }
    c[0] /= n; c[1] /= n; c[2] /= n;
    var M = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    for (i = 0; i < pts.length; i += 3) {
      var d0 = pts[i] - c[0], d1 = pts[i + 1] - c[1], d2 = pts[i + 2] - c[2], d = [d0, d1, d2];
      for (a = 0; a < 3; a++) for (b = 0; b < 3; b++) M[a][b] += d[a] * d[b];
    }
    for (a = 0; a < 3; a++) for (b = 0; b < 3; b++) M[a][b] /= n;
    var Vv = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
    for (var it = 0; it < 48; it++) {
      var p = 0, q = 1, best = 0;
      for (a = 0; a < 3; a++) for (b = a + 1; b < 3; b++)
        if (Math.abs(M[a][b]) > best) { best = Math.abs(M[a][b]); p = a; q = b; }
      if (best < 1e-16) break;
      var th = (M[q][q] === M[p][p]) ? Math.PI / 4
             : 0.5 * Math.atan2(2 * M[p][q], M[q][q] - M[p][p]);
      var ct = Math.cos(th), st = Math.sin(th), k;
      for (k = 0; k < 3; k++) { var kp = M[k][p], kq = M[k][q]; M[k][p] = ct * kp - st * kq; M[k][q] = st * kp + ct * kq; }
      for (k = 0; k < 3; k++) { var pk = M[p][k], qk = M[q][k]; M[p][k] = ct * pk - st * qk; M[q][k] = st * pk + ct * qk; }
      for (k = 0; k < 3; k++) { var vp = Vv[k][p], vq = Vv[k][q]; Vv[k][p] = ct * vp - st * vq; Vv[k][q] = st * vp + ct * vq; }
    }
    var out = [];
    for (a = 0; a < 3; a++) out.push({ ev: M[a][a], v: new THREE.Vector3(Vv[0][a], Vv[1][a], Vv[2][a]).normalize() });
    out.sort(function (x, y) { return y.ev - x.ev; });
    var res = { c: new THREE.Vector3(c[0], c[1], c[2]), ax: [out[0].v, out[1].v, out[2].v], span: [], lo: [], hi: [] };
    for (a = 0; a < 3; a++) {
      var mn = 1e9, mx = -1e9;
      for (i = 0; i < pts.length; i += 3) {
        var pr = (pts[i] - c[0]) * res.ax[a].x + (pts[i + 1] - c[1]) * res.ax[a].y + (pts[i + 2] - c[2]) * res.ax[a].z;
        if (pr < mn) mn = pr; if (pr > mx) mx = pr;
      }
      res.lo.push(mn); res.hi.push(mx); res.span.push(mx - mn);
    }
    return res;
  }

  /* the hand's own frame: distal (toward the knuckles), radial (toward index and thumb), palmar
     (out of the palm). Signs come from where the rig's own index and thumb stubs are, so each
     hand gets its own answer, not a mirror. */
  function handFrame(pts, Bm, side) {
    var pc = principal(pts);
    if (!pc) return null;
    var hand = Bm[bn(side, 'Hand')], fb = Bm[bn(side, 'FingerBase')];
    var idx = Bm[bn(side, 'HandIndex')], th = Bm[bn(side, 'Thumb')];
    if (!hand || !fb || !idx || !th) return null;
    var inv = _m4.copy(hand.matrixWorld).invert();
    var pFb = fb.matrixWorld ? vcp(_s.setFromMatrixPosition(fb.matrixWorld)).applyMatrix4(inv) : null;
    var pIdx = vcp(_s.setFromMatrixPosition(idx.matrixWorld)).applyMatrix4(inv);
    var pTh = vcp(_s.setFromMatrixPosition(th.matrixWorld)).applyMatrix4(inv);
    /* distal = the principal axis that agrees with wrist -> finger base */
    var want = vcp(pFb).normalize(), dist = null, dist0 = null, bestd = -1, i;
    for (i = 0; i < 3; i++) {
      var d = Math.abs(pc.ax[i].dot(want));
      if (d > bestd) { bestd = d; dist = pc.ax[i]; dist0 = pc.ax[i]; }
    }
    dist = vcp(dist); if (dist.dot(want) < 0) dist.negate();
    /* THE ROLL COMES FROM THE HAND, THE SIGNS COME FROM THE RIG. Deriving the knuckle axis from
       the LeftHandIndex1 stub looks reasonable and is wrong by 30-40 degrees: that stub droops
       palmar, the way a relaxed index finger does, so the hand ends up drawn across its own
       fingers. The cloud knows better — a palm is much wider than it is thick, so of the two
       axes left after `dist` the broad one IS the knuckle line and the narrow one IS the palm
       normal. The stubs are then only asked which way round. */
    var rest = [], i2;
    for (i2 = 0; i2 < 3; i2++) if (pc.ax[i2] !== dist0) rest.push(i2);
    var broad = (pc.span[rest[0]] >= pc.span[rest[1]]) ? rest[0] : rest[1];
    var thin = (broad === rest[0]) ? rest[1] : rest[0];
    var rad = vperp(pc.ax[broad], dist);
    var palm = vperp(pc.ax[thin], dist);
    var idxP = vperp(vsub(pIdx, pFb), dist);
    if (rad.dot(idxP) < 0) rad.negate();            /* + is the index side */
    var thP = vperp(pTh, dist);
    if (palm.dot(thP) < 0) palm.negate();           /* + is out of the palm */
    /* and square palm against rad, keeping its sign */
    palm.addScaledVector(rad, -palm.dot(rad)).normalize();
    /* extents along our own frame, measured from the wrist joint (local 0) */
    var lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9], ax = [dist, rad, palm];
    for (i = 0; i < pts.length; i += 3) {
      for (var a = 0; a < 3; a++) {
        var pr = pts[i] * ax[a].x + pts[i + 1] * ax[a].y + pts[i + 2] * ax[a].z;
        if (pr < lo[a]) lo[a] = pr; if (pr > hi[a]) hi[a] = pr;
      }
    }
    /* HOW WIDE THE HAND IS WHERE IT MATTERS. One overall breadth includes the thumb, so the
       knuckles come out too narrow, and says nothing about splay. Two bands — knuckles and
       fingertips — land the rays where they end. */
    function bandW(t0, t1) {
      var blo = 1e9, bhi = -1e9, L = hi[0] || 1, j;
      for (j = 0; j < pts.length; j += 3) {
        var t = (pts[j] * dist.x + pts[j + 1] * dist.y + pts[j + 2] * dist.z) / L;
        if (t < t0 || t > t1) continue;
        var w = pts[j] * rad.x + pts[j + 1] * rad.y + pts[j + 2] * rad.z;
        if (w < blo) blo = w; if (w > bhi) bhi = w;
      }
      return bhi > blo ? bhi - blo : 0;
    }
    var mcpW = bandW(0.40, 0.56), tipW = bandW(0.84, 1.0);
    /* .clone(): these live in the atlas for the life of the model, and the vectors they were
       built from are scratch that solve() recycles every frame. Handing the pool out is how a
       hand frame turns into a rib. */
    return {
      dist: dist.clone(), rad: rad.clone(), palm: palm.clone(),
      len: hi[0],                       /* wrist to fingertip */
      width: hi[1] - lo[1],             /* the whole hand, thumb included */
      thick: hi[2] - lo[2],             /* through the palm */
      mcpW: mcpW || (hi[1] - lo[1]) * 0.62,
      tipW: tipW || (hi[1] - lo[1]) * 0.66
    };
  }

  /* the foot's frame: forward (toe), up (toward the leg), medial (big-toe side). Forward and up
     come from the rig, breadth from the cloud. */
  function footFrame(pts, Bm, side) {
    var foot = Bm[bn(side, 'Foot')], toe = Bm[bn(side, 'ToeBase')], leg = Bm[bn(side, 'Leg')];
    if (!foot || !toe || !leg) return null;
    var inv = _m4.copy(foot.matrixWorld).invert();
    var pToe = vcp(_s.setFromMatrixPosition(toe.matrixWorld)).applyMatrix4(inv);
    var pLeg = vcp(_s.setFromMatrixPosition(leg.matrixWorld)).applyMatrix4(inv);
    var fwd = vcp(pToe).normalize();
    var up = vperp(pLeg, fwd);
    var med = vcross(up, fwd).normalize();      /* sign fixed against the body below */
    var lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9], ax = [fwd, med, up], i, a;
    for (i = 0; i < pts.length; i += 3) {
      for (a = 0; a < 3; a++) {
        var pr = pts[i] * ax[a].x + pts[i + 1] * ax[a].y + pts[i + 2] * ax[a].z;
        if (pr < lo[a]) lo[a] = pr; if (pr > hi[a]) hi[a] = pr;
      }
    }
    return { fwd: fwd.clone(), up: up.clone(), med: med.clone(),
             len: hi[0], width: hi[1] - lo[1],
             half: [lo[1], hi[1]], sole: lo[2], top: hi[2] };
  }

  /* the torso, banded: NTORSO horizontal slabs between hip joint and neck, each keeping a
     half-width, a half-depth and a centre, so ribs and pelvis are sized from the body they sit
     in rather than a table. Each band is stored in the nearest spine bone's local frame, so the
     cage bends when the spine bends instead of riding a rigid box. */
  var NTORSO = 22;
  function torsoBands(pts, Bm, lat, ant) {
    var hips = Bm.Hips, neck = Bm.Neck;
    if (!hips || !neck) return null;
    var p0 = vcp(_s.setFromMatrixPosition(hips.matrixWorld));
    var p1 = vcp(_s.setFromMatrixPosition(neck.matrixWorld));
    var up = vsub(p1, p0), H = up.length();
    if (H < 1e-4) return null;
    up.multiplyScalar(1 / H);
    var bl = [], k;
    for (k = 0; k < NTORSO; k++) bl.push({ w: [], d: [], cl: 0, cd: 0, n: 0 });
    var d = new THREE.Vector3();
    for (var i = 0; i < pts.length; i += 3) {
      d.set(pts[i], pts[i + 1], pts[i + 2]).sub(p0);
      var t = d.dot(up) / H;
      if (t < 0 || t >= 1) continue;
      k = Math.floor(t * NTORSO);
      var b = bl[k];
      b.w.push(d.dot(lat)); b.d.push(d.dot(ant)); b.n++;
    }
    /* a trimmed half-extent: the 4th and 96th percentile, so one stray vertex on a fingertip
       that drifted into the slab cannot inflate the cage */
    function half(a) {
      if (a.length < 8) return null;
      a.sort(function (x, y) { return x - y; });
      var lo = a[Math.floor(a.length * 0.04)], hi = a[Math.floor(a.length * 0.96)];
      return { c: (lo + hi) / 2, h: (hi - lo) / 2 };
    }
    var spine = ['Hips', 'LowerBack', 'Spine', 'Spine1', 'Neck'].filter(function (n) { return !!Bm[n]; });
    var out = [];
    for (k = 0; k < NTORSO; k++) {
      var hw = half(bl[k].w), hd = half(bl[k].d);
      if (!hw || !hd) { out.push(null); continue; }
      var t = (k + 0.5) / NTORSO;
      var ctr = vma(p0, up, t * H).addScaledVector(lat, hw.c).addScaledVector(ant, hd.c);
      /* whichever spine bone is nearest owns this band */
      var host = spine[0], bd = 1e9;
      spine.forEach(function (nm) {
        var q = _s.setFromMatrixPosition(Bm[nm].matrixWorld).distanceTo(ctr);
        if (q < bd) { bd = q; host = nm; }
      });
      var inv = new THREE.Matrix4().copy(Bm[host].matrixWorld).invert();
      var rot = new THREE.Matrix4().extractRotation(inv);
      out.push({
        t: t, host: host,
        c: vcp(ctr).applyMatrix4(inv).clone(),
        lat: vcp(lat).applyMatrix4(rot).normalize().clone(),
        ant: vcp(ant).applyMatrix4(rot).normalize().clone(),
        hw: hw.h, hd: hd.h
      });
    }
    /* fill any band the mesh did not populate from its neighbours */
    for (k = 0; k < NTORSO; k++) if (!out[k]) {
      var a = k, b = k;
      while (a >= 0 && !out[a]) a--;
      while (b < NTORSO && !out[b]) b++;
      out[k] = out[a >= 0 ? a : b] || out[b < NTORSO ? b : 0];
    }
    return out;
  }

  /* band lookup by height fraction along the hip -> neck axis */
  function bandAt(atlas, t) {
    if (!atlas.torso) return null;
    var k = Math.max(0, Math.min(NTORSO - 1, Math.round(t * NTORSO - 0.5)));
    return atlas.torso[k];
  }

  function measure(inner, boneList) {
    var Bm = {}, i;
    boneList.forEach(function (b) { if (b && b.name) Bm[b.name] = b; });
    var missing = AXIAL.concat(
      [0, 1].reduce(function (a, s) {
        return a.concat(Object.keys(SIDED).map(function (k) { return bn(s, k); }));
      }, [])).filter(function (n) { return !Bm[n]; });
    if (missing.length > 4) { MVA.note = 'not a cmu_mb rig (' + missing.length + ' joints missing)'; return null; }

    inner.updateMatrixWorld(true);
    var skins = [];
    var Bb = Bm;                       /* the bind-pose stand-in, filled below */
    /* THE SKIN ONLY. The actor carries a second skinned mesh — the fitted skeleton — whose 100
       000 vertices would be charged to the same groups as the flesh, and every radius, band and
       hand frame below would then be measured off bone. A mesh tagged as an MVA layer is never
       a measure. */
    inner.traverse(function (o) {
      if (o.userData && o.userData.mvaLayer) return;
      if (o.isSkinnedMesh && o.geometry && o.geometry.attributes.skinIndex) skins.push(o);
    });
    if (!skins.length) { MVA.note = 'the GLB has no skinned mesh to measure'; return null; }

    /* MEASURE AT THE BIND POSE, WHOEVER CALLS US. The skeleton's own boneInverses ARE the bind
       pose: inverse(boneInverses[i]) is bone i's matrix when the mesh was bound. Reading those,
       not the live bone.matrixWorld, makes measure() right from adopt() before the first tick
       and still right mid-stride. Bb shims every bone with its bind matrix; nothing downstream
       reads anything but .matrixWorld. */
    var sk0 = skins[0].skeleton;
    if (sk0 && sk0.boneInverses && sk0.boneInverses.length === sk0.bones.length) {
      Bb = {};
      sk0.bones.forEach(function (b, i2) {
        if (!b || !b.name) return;
        Bb[b.name] = { matrixWorld: new THREE.Matrix4().copy(sk0.boneInverses[i2]).invert() };
      });
      AXIAL.concat(Object.keys(SIDED).map(function (k) { return SIDED[k][0]; }))
        .forEach(function (n) { if (!Bb[n] && Bm[n]) Bb[n] = Bm[n]; });
      Object.keys(Bm).forEach(function (n) { if (!Bb[n]) Bb[n] = Bm[n]; });
    }

    /* body axes: forward from the toes (they are the one part of a rig whose direction is never
       ambiguous), sideways from the shoulders, up from the spine */
    function wp(n) { return Bb[n] ? vcp(_s.setFromMatrixPosition(Bb[n].matrixWorld)) : null; }
    var ant = vsub(wp(bn(0, 'ToeBase')), wp(bn(0, 'Foot'))).add(
              vsub(wp(bn(1, 'ToeBase')), wp(bn(1, 'Foot'))));
    var lat = vsub(wp(bn(0, 'Arm')), wp(bn(1, 'Arm')));       /* -> the body's left */
    var up = vsub(wp('Neck'), wp('Hips')).normalize();
    lat = vperp(lat, up); ant = vperp(ant, up);
    if (vcross(lat, ant).dot(up) < 0) { /* keep lat x ant pointing up */ }

    /* one pass over every vertex, charged to whichever group holds most of its weight, and
       placed by the bind transform above. */
    var groups = {};
    var want = {};                                   /* bone name -> group key */
    var specs = groupSpec(0).concat(groupSpec(1));
    specs.forEach(function (g) {
      groups[g[0]] = [];
      g[1].forEach(function (n) { (want[n] = want[n] || []).push(g[0]); });
    });
    groups.head = []; groups.torso = []; groups.neck = [];
    ['Head'].forEach(function (n) { (want[n] = want[n] || []).push('head'); });
    /* the jaw belongs to Neck as far as the skinning is concerned — the head cloud stops at the
       jawline — so the neck is collected separately and the two are read together to find the
       chin */
    ['Neck', 'Neck1'].forEach(function (n) { (want[n] = want[n] || []).push('neck'); });
    ['Hips', 'LHipJoint', 'RHipJoint', 'LowerBack', 'Spine', 'Spine1'].forEach(function (n) {
      (want[n] = want[n] || []).push('torso');
    });

    /* getX/getY/getZ/getW, not getComponent: GLTFLoader hands back an
       InterleavedBufferAttribute whenever the accessor shares a buffer view, and in r147 that
       class has no getComponent at all. */
    var COMP = [function (a, i2) { return a.getX(i2); }, function (a, i2) { return a.getY(i2); },
                function (a, i2) { return a.getZ(i2); }, function (a, i2) { return a.getW(i2); }];
    var tmp = new THREE.Vector3(), acc = {}, nvert = 0;
    var bindW = new THREE.Matrix4();
    skins.forEach(function (mesh) {
      var g = mesh.geometry, pos = g.attributes.position;
      var si = g.attributes.skinIndex, sw = g.attributes.skinWeight;
      var names = (mesh.skeleton && mesh.skeleton.bones) || [];
      var n = pos.count;
      bindW.multiplyMatrices(mesh.matrixWorld, mesh.bindMatrixInverse).multiply(mesh.bindMatrix);
      nvert += n;
      for (var v = 0; v < n; v++) {
        var k;
        for (k in acc) acc[k] = 0;
        var any = false;
        for (var c = 0; c < 4; c++) {
          var w = COMP[c](sw, v);
          if (w <= 0.001) continue;
          var b = names[COMP[c](si, v)];
          var keys = b && want[b.name];
          if (!keys) continue;
          for (var q = 0; q < keys.length; q++) {
            acc[keys[q]] = (acc[keys[q]] || 0) + w; any = true;
          }
        }
        if (!any) continue;
        var bestk = null, bestw = 0.5;
        for (k in acc) if (acc[k] > bestw) { bestw = acc[k]; bestk = k; }
        if (!bestk) continue;
        tmp.fromBufferAttribute(pos, v).applyMatrix4(bindW);
        groups[bestk].push(tmp.x, tmp.y, tmp.z);
      }
    });

    /* into each group's own frame */
    function localise(key, frameBone) {
      var pts = groups[key], b = Bb[frameBone];
      if (!b || !pts.length) return [];
      var inv = new THREE.Matrix4().copy(b.matrixWorld).invert();
      var out = new Array(pts.length), t = new THREE.Vector3();
      for (var i2 = 0; i2 < pts.length; i2 += 3) {
        t.set(pts[i2], pts[i2 + 1], pts[i2 + 2]).applyMatrix4(inv);
        out[i2] = t.x; out[i2 + 1] = t.y; out[i2 + 2] = t.z;
      }
      return out;
    }

    /* ── WHICH SIDE EVERY VERTEX OF THE ACTOR IS ON ──────────────────────
       The same defect as the anatomy's and the same fix: a plane cut the raised arm in half
       along with everything else. So each vertex is told once, HERE, at the bind pose, which
       half it belongs to, and carries that for life. The answer comes from the bone that owns
       it — a vertex weighted to LeftForeArm is on the left however the clip throws that arm
       about — and only the axial bones, with no side in the name, fall back to which side of
       the midline the vertex sits at the BIND pose. Bind, not live: it is a fact about the
       body, not about the frame. Baked as an attribute rather than tested in the shader because
       a vertex's side cannot change, and interpolating it across a triangle whose corners
       disagree and discarding at 0.5 puts the seam exactly on the midline. */
    var midC = wp('Hips') || vset(0, 0, 0);
    var sideOfName = function (nm) {
      if (!nm) return -1;
      if (nm.indexOf('Left') === 0 || /^L(Hip|Thumb)/.test(nm)) return 0;
      if (nm.indexOf('Right') === 0 || /^R(Hip|Thumb)/.test(nm)) return 1;
      return -1;                                   /* axial: no side in the name */
    };
    (function bakeSides() {
      var t2 = new THREE.Vector3(), bw = new THREE.Matrix4();
      inner.traverse(function (mesh) {
        if ((!mesh.isMesh && !mesh.isSkinnedMesh) || !mesh.geometry) return;
        if (mesh.userData && mesh.userData.mvaLayer) return;   /* the skeleton bakes its own */
        var g = mesh.geometry, pos = g.attributes.position;
        if (!pos || g.attributes.aSide) return;
        var si = g.attributes.skinIndex, sw = g.attributes.skinWeight;
        var names = (mesh.skeleton && mesh.skeleton.bones) || [];
        if (mesh.isSkinnedMesh && mesh.bindMatrixInverse)
          bw.multiplyMatrices(mesh.matrixWorld, mesh.bindMatrixInverse).multiply(mesh.bindMatrix);
        else bw.copy(mesh.matrixWorld);
        var arr = new Float32Array(pos.count);
        for (var v = 0; v < pos.count; v++) {
          var sd = -1;
          if (si && sw && names.length) {
            var bestW = 0, bi = -1;
            for (var c = 0; c < 4; c++) {
              var w = COMP[c](sw, v);
              if (w > bestW) { bestW = w; bi = COMP[c](si, v); }
            }
            if (bi >= 0 && names[bi]) sd = sideOfName(names[bi].name);
          }
          if (sd < 0) {
            t2.fromBufferAttribute(pos, v).applyMatrix4(bw).sub(midC);
            sd = t2.dot(lat) > 0 ? 0 : 1;
          }
          arr[v] = sd;
        }
        g.setAttribute('aSide', new THREE.BufferAttribute(arr, 1));
      });
    })();

    /* ── AND THE SKELETON'S OWN SIDES ────────────────────────────────────
       Same attribute name, same dominant-bone rule, one difference the reference plate insists
       on: A HALF SPINE READS AS A BROKEN SPINE. Skin is a closed surface, so an axial vertex
       can take a side off the midline and the seam lands where it should. A column is not a
       surface — cut it and the plate shows a body with no back. So every axial bone (vertebrae,
       sacrum, neck) is marked SIDE_AXIS and drawn WHOLE down the seam. The skull genuinely IS
       cut down the face, so its vertices are sided by the Head bone's own lateral axis at the
       bind pose, not by its name. */
    (function bakeSkelSides() {
      var t2 = new THREE.Vector3(), bw = new THREE.Matrix4();
      var hb = Bb.Head && Bb.Head.matrixWorld;
      var hc = hb ? new THREE.Vector3().setFromMatrixPosition(hb) : midC;
      inner.traverse(function (mesh) {
        if (!mesh.userData || mesh.userData.mvaLayer !== 'bone') return;
        var g = mesh.geometry, pos = g && g.attributes && g.attributes.position;
        if (!pos || g.attributes.aSide) return;
        var si = g.attributes.skinIndex, sw = g.attributes.skinWeight;
        var names = (mesh.skeleton && mesh.skeleton.bones) || [];
        if (mesh.isSkinnedMesh && mesh.bindMatrixInverse)
          bw.multiplyMatrices(mesh.matrixWorld, mesh.bindMatrixInverse).multiply(mesh.bindMatrix);
        else bw.copy(mesh.matrixWorld);
        var arr = new Float32Array(pos.count);
        for (var v = 0; v < pos.count; v++) {
          var nm = '', sd;
          if (si && sw && names.length) {
            var bestW = 0, bi = -1;
            for (var c = 0; c < 4; c++) {
              var w = COMP[c](sw, v);
              if (w > bestW) { bestW = w; bi = COMP[c](si, v); }
            }
            if (bi >= 0 && names[bi]) nm = names[bi].name || '';
          }
          sd = sideOfName(nm);
          if (sd < 0) {
            if (nm === 'Head') {
              t2.fromBufferAttribute(pos, v).applyMatrix4(bw).sub(hc);
              sd = t2.dot(lat) > 0 ? SIDE_L : SIDE_R;
            } else sd = SIDE_AXIS;          /* the column, drawn whole */
          }
          arr[v] = sd;
        }
        g.setAttribute('aSide', new THREE.BufferAttribute(arr, 1));
      });
    })();

    var A = { bones: Bm, lat: lat.clone(), ant: ant.clone(), up: up.clone(),
              hand: [], foot: [], limb: {}, frame: {}, groupN: {} };
    Object.keys(groups).forEach(function (k) { A.groupN[k] = groups[k].length / 3; });

    /* freeze the body's anterior and lateral axes into every bone's own local frame, once, at
       the bind pose. boneAxes() reads them back out through the live matrix, which is what lets
       a muscle stay in front of its bone through any rotation the clip asks for. */
    Object.keys(Bb).forEach(function (nm) {
      var r = new THREE.Matrix4().extractRotation(Bb[nm].matrixWorld).invert();
      A.frame[nm] = { ant: vcp(ant).applyMatrix4(r).normalize().clone(),
                      lat: vcp(lat).applyMatrix4(r).normalize().clone(),
                      up: vcp(up).applyMatrix4(r).normalize().clone() };
    });

    [0, 1].forEach(function (s) {
      A.hand[s] = handFrame(localise('hand' + s, bn(s, 'Hand')), Bb, s);
      A.foot[s] = footFrame(localise('foot' + s, bn(s, 'Foot')), Bb, s);
      /* the foot's medial axis has to point at the OTHER foot */
      if (A.foot[s]) {
        var rot = new THREE.Matrix4().extractRotation(Bb[bn(s, 'Foot')].matrixWorld);
        var w = vcp(A.foot[s].med).applyMatrix4(rot);
        if (w.dot(lat) * (s === 0 ? -1 : 1) < 0) A.foot[s].med.negate();
      }
      [['arm', 'Arm', 'ForeArm'], ['fore', 'ForeArm', 'Hand'],
       ['upleg', 'UpLeg', 'Leg'], ['leg', 'Leg', 'Foot']].forEach(function (L) {
        var head = Bb[bn(s, L[1])], tail = Bb[bn(s, L[2])];
        if (!head || !tail) return;
        var hinv = new THREE.Matrix4().copy(head.matrixWorld).invert();
        A.limb[L[0] + s] = limbProfile(localise(L[0] + s, bn(s, L[1])),
          new THREE.Vector3(0, 0, 0),
          vcp(_s.setFromMatrixPosition(tail.matrixWorld)).applyMatrix4(hinv));
      });
    });

    A.torso = torsoBands(groups.torso, Bb, lat, ant);

    /* THE HEAD, IN THE HEAD'S OWN FRAME. Measuring along the BODY axes looks right and is not:
       the bind pose is not a T-pose and the head is tilted, so "how far forward" picks up part
       of how far UP — 23 cm deep, 16 tall. The Head bone is rigid with the head, so take the
       box along ITS local axes and name them by which body axis each points along. */
    function axisPick(v) {
      var ax = Math.abs(v.x), ay = Math.abs(v.y), az = Math.abs(v.z);
      if (ax >= ay && ax >= az) return new THREE.Vector3(v.x >= 0 ? 1 : -1, 0, 0);
      if (ay >= az) return new THREE.Vector3(0, v.y >= 0 ? 1 : -1, 0);
      return new THREE.Vector3(0, 0, v.z >= 0 ? 1 : -1);
    }
    var hp = localise('head', 'Head');
    if (hp.length > 72 && A.frame.Head) {
      var hlo = [1e9, 1e9, 1e9], hhi = [-1e9, -1e9, -1e9], ai;
      for (i = 0; i < hp.length; i += 3)
        for (ai = 0; ai < 3; ai++) {
          var hq = hp[i + ai];
          if (hq < hlo[ai]) hlo[ai] = hq;
          if (hq > hhi[ai]) hhi[ai] = hq;
        }
      var fh = A.frame.Head;
      var U = axisPick(fh.up), Aa = axisPick(fh.ant), L = axisPick(fh.lat);
      function idxOf(v) { return v.x ? 0 : (v.y ? 1 : 2); }
      function sgnOf(v) { return v.x || v.y || v.z; }
      /* three distinct axes, or the pick is degenerate and not worth using */
      if (idxOf(U) !== idxOf(Aa) && idxOf(U) !== idxOf(L) && idxOf(Aa) !== idxOf(L)) {
        function span(v) {
          var k4 = idxOf(v);
          return sgnOf(v) > 0 ? { hi: hhi[k4], lo: hlo[k4] } : { hi: -hlo[k4], lo: -hhi[k4] };
        }
        var su = span(U), sa = span(Aa), sl = span(L);
        A.head = {
          U: U, A: Aa, L: L,
          hup: su.hi, hdn: -su.lo,
          hf: sa.hi, hb: -sa.lo,
          hw: Math.max(sl.hi, -sl.lo)
        };
        /* WHERE THE CHIN IS, MEASURED. Not "the forward-most point below the joint": the Head
           joint sits at nose height, so it IS that point and the search answers zero. The chin
           is where the face STOPS reaching forward — the lowest band still reaching most of the
           way out, below which the throat falls away sharply. */
        var nk = localise('neck', 'Head'), src = [hp, nk], si2, i5;
        var NB = 28, reach = new Float64Array(NB), uax = U, aax = Aa, cu, cf, bi;
        for (bi = 0; bi < NB; bi++) reach[bi] = -1e9;
        for (si2 = 0; si2 < 2; si2++) {
          var arr = src[si2];
          for (i5 = 0; i5 < arr.length; i5 += 3) {
            cu = arr[i5] * uax.x + arr[i5 + 1] * uax.y + arr[i5 + 2] * uax.z;
            if (cu > 0 || cu < -A.head.hup) continue;
            bi = Math.min(NB - 1, Math.floor((-cu / A.head.hup) * NB));
            cf = arr[i5] * aax.x + arr[i5 + 1] * aax.y + arr[i5 + 2] * aax.z;
            if (cf > reach[bi]) reach[bi] = cf;
          }
        }
        var top = -1e9;
        for (bi = 0; bi < NB; bi++) if (reach[bi] > top) top = reach[bi];
        var chinU = -A.head.hup * 0.40, chinFm = A.head.hf * 0.78;
        if (top > -1e8) {
          for (bi = NB - 1; bi >= 0; bi--) {
            if (reach[bi] > -1e8 && reach[bi] >= top * 0.72) {
              chinU = -((bi + 1) / NB) * A.head.hup;
              chinFm = reach[bi];
              break;
            }
          }
        }
        A.head.chinUp = chinU;
        A.head.chinF = chinFm;
      }
    }

    /* stature, and the residual between the mesh and the rig — the one number that says whether
       the skeleton is drawn where the body actually is */
    var lo9 = 1e9, hi9 = -1e9;
    Object.keys(groups).forEach(function (k) {
      var a3 = groups[k];
      for (var i3 = 1; i3 < a3.length; i3 += 3) {
        if (a3[i3] < lo9) lo9 = a3[i3];
        if (a3[i3] > hi9) hi9 = a3[i3];
      }
    });
    A.stature = (hi9 > lo9) ? Math.max(0.4, hi9 - lo9) : 1.7;
    /* DIAGNOSTIC, not a correction, measured at the ankle because the foot cloud brackets it
       tightly. */
    /* THE ONE CHECK THAT SAYS THE RIG IS IN ITS OWN BODY: the ankle joint has to fall between
       the sole and the top of the foot it drives. If not, mesh and skeleton were bound in
       different places — a build defect in proxy_actor, which the panel reports rather than
       dialling out. */
    A.ankleIn = !!(A.foot[0] && A.foot[0].sole < 0 && A.foot[0].top > 0);
    A.vert = nvert;
    MVA.note = '';
    return A;
  }

  /* ── the solver ──────────────────────────────────────────────────────────
     Runs every frame off the 31 live rig transforms plus the atlas and emits ONE kind of
     primitive: an articulation. chain() is a joint sphere plus the thin link back to the
     previous joint — connectivity, the thing no mesh can tell you. The bone between two joints
     is not drawn here: that is the actor's own fitted CC0 skeleton mesh. `br` is the old shaft
     radius, still taken so the hundred-odd call sites read as anatomy, and ignored. */
  function chain(prev, p, jr, br) {
    var i = joint(p, jr);
    if (prev >= 0) link(prev, i);
    return i;
  }

  /* levels down the vertebral column, as a fraction of the curve Hips -> LowerBack -> Spine ->
     Spine1 -> Neck -> Neck1 -> Head. Hips sits at the hip centre and Head at ear height, so the
     column occupies the MIDDLE of that curve: coccyx 0.02, L5 0.16, T1 0.73, C1 0.90. Checked
     against the base body — L5 at y 0.94, C1 at 1.42 on a 1.69 m actor. */
  var LEVELS = (function () {
    var L = [], i;
    for (i = 0; i < 5; i++) L.push({ n: 'S' + (i + 1), t: 0.145 - i * 0.022, k: 'sacral' });
    L.push({ n: 'Co', t: 0.030, k: 'sacral' });
    for (i = 0; i < 5; i++) L.push({ n: 'L' + (5 - i), t: 0.160 + i * 0.055, k: 'lumbar' });
    for (i = 0; i < 12; i++) L.push({ n: 'T' + (12 - i), t: 0.390 + i * 0.0309, k: 'thoracic' });
    for (i = 0; i < 7; i++) L.push({ n: 'C' + (7 - i), t: 0.745 + i * 0.0258, k: 'cervical' });
    return L;
  })();
  var VR = { sacral: 0.0175, lumbar: 0.0155, thoracic: 0.0118, cervical: 0.0086 };

  var _curve = null, _cpt = [];
  function column(Bm) {
    if (!_curve) {
      for (var i = 0; i < AXIAL.length; i++) _cpt.push(new THREE.Vector3());
      _curve = new THREE.CatmullRomCurve3(_cpt, false, 'catmullrom', 0.5);
    }
    for (var k = 0; k < AXIAL.length; k++) {
      var b = Bm[AXIAL[k]];
      if (b) _cpt[k].setFromMatrixPosition(b.matrixWorld);
    }
    return _curve;
  }

  /* the frame carried by a torso band: its centre and its two body axes, pushed through
     whichever spine bone owns it, so it bends with the spine */
  function bandFrame(A, band) {
    var host = A.bones[band.host];
    if (!host) return null;
    var M = host.matrixWorld;
    _m4.extractRotation(M);
    return {
      c: vcp(band.c).applyMatrix4(M),
      lat: vcp(band.lat).applyMatrix4(_m4).normalize(),
      ant: vcp(band.ant).applyMatrix4(_m4).normalize(),
      hw: band.hw, hd: band.hd
    };
  }

  /* A limb's frame must ROTATE WITH THE LIMB: "in front of the humerus" is a fact about the
     bone, not the room. So the body's anterior and lateral axes are frozen into every bone's
     local frame at measure() time and read back through its live matrix here. It also removes
     the T-pose degeneracy: an arm straight out sideways has a limb axis parallel to the body's
     lateral. */
  function boneAxes(A, name, side) {
    var b = A.bones[name], f = A.frame && A.frame[name];
    if (!b || !f) return null;
    _m4.extractRotation(b.matrixWorld);
    var ant = vcp(f.ant).applyMatrix4(_m4).normalize();
    var lat = vcp(f.lat).applyMatrix4(_m4).normalize();
    if (side === 1) lat.negate();               /* + is always away from the midline */
    return { ant: ant, lat: lat };
  }

  /* a bone segment plus that frame: everything a muscle needs to be placed */
  function segFrame(A, headName, tailName, side) {
    var h = A.bones[headName], t = A.bones[tailName];
    if (!h || !t) return null;
    var a = vcp(_s.setFromMatrixPosition(h.matrixWorld));
    var b = vcp(_s.setFromMatrixPosition(t.matrixWorld));
    var ax = vsub(b, a), L = ax.length();
    if (L < 1e-6) return null;
    ax.multiplyScalar(1 / L);
    var f = boneAxes(A, headName, side);
    if (!f) return null;
    return { a: a, b: b, ax: ax, L: L, ant: f.ant, lat: f.lat };
  }

  /* ── axial: the column ───────────────────────────────────────────────────
     26 vertebral levels on the live spine curve, each with a body, a spinous process and a pair
     of transverse processes. The rig gives that curve four control points between hips and
     neck, so the column bends and twists with the clip. Returns the level list the ribs and
     girdles hang from. */
  function solveColumn(A, out) {
    var cur = column(A.bones), i;
    var prev = -1;
    SD = SIDE_AXIS;          /* the column is the axis: it is drawn whole */
    /* nearest band gives each level its lateral/anterior frame and its girth */
    for (i = LEVELS.length - 1; i >= 0; i--) {          /* top (C1) downwards */
      var Lv = LEVELS[i];
      var p = cur.getPoint(Lv.t, v3());
      var tan = cur.getTangent(Lv.t, v3()).normalize();
      var band = bandAt(A, Lv.t);
      var bf = band ? bandFrame(A, band) : null;
      var lat = bf ? vperp(bf.lat, tan) : vperp(A.lat, tan);
      var ant = vcross(lat, tan).normalize();
      if (bf && ant.dot(bf.ant) < 0) { ant.negate(); lat.negate(); }
      var r = VR[Lv.k] * A.stature;
      /* WHICH WAY `lat` CAME OUT. Nothing above guarantees it points to the actor's left: it is
         whatever vperp handed back. Everything sided that hangs off this level must agree with
         the rig's own Left/Right, so the sign is resolved once here against the host bone's own
         left axis. */
      var lf = boneAxes(A, band ? band.host : 'Spine', 0);
      var ls = (lf && lat.dot(lf.lat) < 0) ? -1 : 1;
      /* the vertebral BODY sits anterior of the curve, the canal behind it */
      var c = vma(p, ant, r * 0.35);
      out.push({ n: Lv.n, k: Lv.k, t: Lv.t, p: c, tan: tan, lat: lat, ant: ant, r: r,
                 bf: bf, ls: ls });
    }
    /* LEVELS is written in anatomical groups, not in order up the spine, and the chain that
       follows has to run coccyx -> C1 or it will draw a bone from the tailbone straight up to
       L5 */
    out.sort(function (a, b) { return a.t - b.t; });
    for (i = 0; i < out.length; i++) {
      var L = out[i];
      L.idx = chain(prev, L.p, L.r * 0.52, L.r * 0.72);
      AN.lvl[L.n] = L;
      prev = L.idx;
    }
    return out;
  }

  /* ── axial: the ribcage ──────────────────────────────────────────────────
     12 pairs swept round the thoracic levels, sized from the measured torso bands inset by
     RIB_INSET for the soft tissue, so the arcs are THIS chest's. Only the costovertebral and
     costochondral ends are emitted — real articulations; the shaft between them is the skeleton
     mesh's. */
  var RIB_INSET = 0.80, RIB_SEG = 10;
  function solveRibs(A, levels) {
    var th = levels.filter(function (L) { return L.k === 'thoracic'; });
    if (th.length < 12) return;
    th.sort(function (a, b) { return b.t - a.t; });      /* T1 first */
    var s, i, k;
    var sternum = [];
    for (i = 0; i < 12; i++) {
      var L = th[i];
      var band = L.bf;
      var W = (band ? band.hw : 0.14) * RIB_INSET;
      var D = (band ? band.hd : 0.10) * RIB_INSET;
      /* the bottom four ribs tuck in fast, the first one is a tight hoop */
      var shrink = i === 0 ? 0.62 : (i === 1 ? 0.84 : 1.0);
      if (i >= 8) shrink = 1.0 - (i - 7) * 0.10;
      W *= shrink; D *= shrink;
      var sweep = (i >= 10) ? 1.45 : (i === 0 ? 2.45 : 2.62);     /* radians */
      /* A RIB RUNS DOWNHILL, and that slope is most of what makes a ribcage look like one: a
         middle rib's front end sits two vertebral levels below its back end. The first cut used
         a third of that and got a barrel of level hoops. Rib 1 is nearly flat, ribs 6-10
         steepest. */
      var slope = (i === 0 ? 0.30 : (i === 1 ? 0.70 : Math.min(1.85, 0.95 + i * 0.13)));
      var drop = slope * L.r * 3.2;
      /* THE CAGE IS NOT CENTRED ON THE SPINE. cmu_mb runs its spine joints down the MIDDLE of
         the torso; a real column sits at the back, so a rib swept round the rig's point stands
         out through the back. Take only the anterior component of the measured band centre, so
         the cage still rides the smooth spine curve vertically and laterally. */
      var fwd = band ? vsub(band.c, L.p).dot(L.ant) : D * 0.55;
      var Cc = vma(L.p, L.ant, fwd);
      for (s = 0; s < 2; s++) {
        var sg = s === 0 ? 1 : -1;
        /* the rib is drawn on the side `lat * sg` actually points to */
        SD = (sg * L.ls > 0) ? SIDE_L : SIDE_R;
        var pts = [], last = null;
        for (k = 0; k <= RIB_SEG; k++) {
          var a2 = sweep * k / RIB_SEG;
          var p = vcp(Cc);
          p.addScaledVector(L.lat, sg * W * Math.sin(a2));
          p.addScaledVector(L.ant, -D * 0.88 * Math.cos(a2));
          p.addScaledVector(L.tan, -drop * (k / RIB_SEG) * (k / RIB_SEG));
          pts.push(p); last = p;
        }
        /* the costovertebral joint and the costochondral joint are real articulations; the
           shaft between them is bone with no joints in it */
        var jr = 0.0026 * A.stature;    /* the ball, not the blade: a rib end
                                           is a knuckle, and sizing it off the
                                           blade's new depth puts a marble at
                                           both ends of all 24 of them */
        var j0 = joint(pts[0], jr * 1.5);
        link(L.idx, j0);
        var j1 = joint(last, jr * 1.4);
        if (i === 4 || i === 7) AN.rib[s * 2 + (i === 4 ? 0 : 1)] = pts[Math.floor(RIB_SEG * 0.55)];
        if (i < 7) {
          /* true rib: CARTILAGE RUNS UPHILL. The rib has just fallen the whole of `drop`; its
             cartilage angles back UP and in to the breastbone, which is why the costal margin
             makes a V. A sternal end LOWER than the rib end (the first cut) stretches the
             sternum to the navel. */
          var st = vma(vma(Cc, L.ant, D * 0.84), L.tan, -drop * 0.24);
          if (s === 0) sternum.push(st);
          var jc = joint(st, jr * 1.1);
          link(j1, jc);
        }
      }
    }
    /* the sternum's own articulations down the midline: the jugular notch, the sternal angle
       you count ribs from, and the xiphoid tip */
    SD = SIDE_AXIS;
    if (sternum.length >= 7) {
      var sw = 0.0112 * A.stature;
      AN.stern = sternum;
      joint(sternum[0], sw * 0.42);                      /* jugular notch */
      joint(sternum[1], sw * 0.36);                      /* sternal angle */
      joint(vlerp(sternum[6], sternum[5], -0.55), sw * 0.26);   /* xiphoid */
    }
  }

  /* ── axial: the pelvis ───────────────────────────────────────────────────
     Sacrum, both iliac crests, the acetabula at the rig's own hip joints and the pubic rami
     meeting at the symphysis. Width comes from the torso band at hip height, so a wide body
     gets a wide pelvis. */
  function solvePelvis(A, levels) {
    var Bm = A.bones;
    var hips = Bm.Hips, ul = [Bm[bn(0, 'UpLeg')], Bm[bn(1, 'UpLeg')]];
    if (!hips || !ul[0] || !ul[1]) return;
    var H = vcp(_s.setFromMatrixPosition(hips.matrixWorld));
    var A0 = vcp(_s.setFromMatrixPosition(ul[0].matrixWorld));
    var A1 = vcp(_s.setFromMatrixPosition(ul[1].matrixWorld));
    var lat = vsub(A0, A1).normalize();
    var sac = levels.filter(function (L) { return L.k === 'sacral'; });
    var top = sac.length ? sac[sac.length - 1] : levels[levels.length - 1];
    var up = vcp(top.tan);
    var ant = vcross(lat, up).normalize();
    if (ant.dot(top.ant) < 0) ant.negate();
    var band = bandAt(A, 0.10), bf = band ? bandFrame(A, band) : null;
    var W = (bf ? bf.hw : vsub(A0, A1).length() * 0.9) * 0.93;
    var D = bf ? bf.hd : W * 0.72;
    var r = 0.0085 * A.stature;
    var symph = vma(vma(H, ant, D * 0.86), up, -0.055 * A.stature);
    SD = SIDE_AXIS;
    var jsym = joint(symph, r * 1.1);
    AN.symph = symph;
    for (var s = 0; s < 2; s++) {
      /* `lat` runs from the right hip to the left, so s 0 IS the left */
      SD = s === 0 ? SIDE_L : SIDE_R;
      var sg = s === 0 ? 1 : -1, hip = s === 0 ? A0 : A1;
      var jac = joint(hip, r * 1.7);                     /* the acetabulum */
      /* sacro-iliac joint, high and behind */
      var si = vma(vma(vma(H, lat, sg * W * 0.28), up, 0.030 * A.stature), ant, -D * 0.55);
      var jsi = joint(si, r * 1.1);
      link(top.idx, jsi);
      /* THE CREST SITS AT 0.61 OF STATURE, AND IT WAS AT 0.67 — measured, not eyeballed. Hips
         is at 0.954 m on this 1.69 m body; the old `0.105 * stature` lifted the crest to 1.131
         m, above LowerBack at 1.040, so the pelvis reached past L1. A real crest is 0.61 of
         standing height = 1.031 m = 0.046 stature above Hips; the bowl keys off it. */
      var CREST_UP = 0.048 * A.stature;
      var crest = [];
      for (var k = 0; k <= 5; k++) {
        var a2 = k / 5;
        crest.push(vma(vma(vma(H, lat, sg * W * (0.42 + 0.58 * Math.sin(a2 * 1.9))),
                            up, CREST_UP * (0.35 + 0.65 * Math.sin(a2 * 2.6))),
                        ant, D * (-0.62 + 1.5 * a2)));
      }
      AN.crest[s] = crest[2]; AN.hip[s] = hip; AN.si[s] = si;
      joint(crest[5], r * 0.8);                          /* anterior superior spine */
      /* the ischium — the tuberosity you sit on — closing the ring down to the symphysis with
         the two pubic rami */
      var isch = vma(vma(hip, up, -0.052 * A.stature), ant, -D * 0.42);
      joint(isch, r * 1.0);
      link(jac, jsym); link(jac, jsi);
    }
    SD = SIDE_AXIS;
  }

  /* ── axial: the skull ────────────────────────────────────────────────────
     Four articulations and one measurement; the mesh draws the rest. The scale is still earned
     here, because AN.skull is what the checker and the clip read: every feature is a fraction
     of HEAD HEIGHT, crown to chin — `hup + drop`, not `hup`. Eye line 0.50 up from the chin,
     skull base 0.42, hinge 0.47, gonion 0.155, all off this body's own vertices. */
  function solveSkull(A, levels) {
    var head = A.bones.Head, H = A.head;
    if (!head || !H) return;
    var M = head.matrixWorld;
    _m4.extractRotation(M);
    var up = vcp(H.U).applyMatrix4(_m4).normalize();
    var ant = vcp(H.A).applyMatrix4(_m4).normalize();
    var lat = vcp(H.L).applyMatrix4(_m4).normalize();
    var o = vcp(_s.setFromMatrixPosition(M));
    var r = 0.0026 * A.stature, k, a2, s2;
    /* THE HEAD IS THE ONE THING THAT IS REALLY CUT. The midline points here are tagged for the
       head's own plane, rebuilt from the Head bone every tick. The paired features below take a
       side like anything else, and `hsign` aligns this head's measured lateral axis with the
       rig's. */
    SD = SIDE_HEAD;
    var hlf = boneAxes(A, 'Head', 0);
    var hsign = (hlf && lat.dot(hlf.lat) < 0) ? -1 : 1;

    /* the chin, as measured: the forward-most point of the lower face. Head owns the head only
       down to the jawline — below that the weights go to Neck — so H.hdn stops ~2 cm under the
       joint and a face hung off it ends up inside the mouth. */
    var drop = Math.max(0.15 * H.hup, -(H.chinUp || -H.hup * 0.5));
    var chinF = (H.chinF || H.hf * 0.7);
    var Hh = H.hup + drop;                       /* crown to chin */
    /* y of a fraction of the way up the face, 0 = chin, 1 = crown */
    function fy(f) { return -drop + f * Hh; }
    var fA = H.hf * 0.82, bA = H.hb * 0.96;      /* how far the face and the
                                                    back of the head reach */
    var rL = 0.86 * H.hw;

    /* THE NEUROCRANIUM, as three half-axes. The skeleton mesh draws it now, but the head's
       clipping plane and the checker both read AN.skull, so the numbers must be the SKULL's:
       ear-level base (0.42 up the face) to crown, NARROWER than the head because the widest
       thing on a head is the ears, longer than wide — 15 cm across by 14 tall by 18 deep. */
    var vTop = H.hup, vBot = fy(0.42);
    var rU = (vTop - vBot) / 2;
    rL = 0.665 * H.hw;              /* a skull is narrower than a head: ears */
    var rA = (fA * 0.62 + bA * 1.16) / 2;
    var cc = vma(vma(o, up, vBot + rU), ant, (fA * 0.62 - bA * 1.16) / 2);
    joint(vma(cc, up, rU), r * 1.6);             /* bregma, at the crown */
    /* where the column meets the skull */
    var occ = vma(vma(o, up, fy(0.54)), ant, -bA * 0.42);
    var jo = joint(occ, r * 2.0);
    var c1 = levels[levels.length - 1];
    if (c1) link(c1.idx, jo);

    /* the orbit, for AN.skull's record: wider than it is tall, nearer four to three than
       square, which is the ratio the checker asserts */
    var eyeY = fy(0.50);
    var orbW = 0.086 * Hh, orbV = 0.066 * Hh, orbL = 0.136 * Hh;
    for (s2 = 0; s2 < 2; s2++) {
      var sg = s2 === 0 ? 1 : -1;
      SD = (sg * hsign > 0) ? SIDE_L : SIDE_R;
      /* the temporomandibular hinge, out at the ear, and the angle of the jaw under it: the two
         articulations of the mandible the rig has no channel for and the only points here that
         are joints at all */
      var tmj = vma(vma(vma(o, lat, sg * rL * 1.00), ant, -bA * 0.10), up, fy(0.47));
      var jt = joint(tmj, r * 1.7);               /* temporomandibular */
      link(jo, jt);
      joint(vma(vma(vma(o, lat, sg * rL * 0.94), ant, -bA * 0.02), up, fy(0.155)),
            r * 1.2);                             /* gonion */
    }
    SD = SIDE_HEAD;

    AN.skull = { c: cc, up: up, ant: ant, lat: lat, rU: rU, rA: rA, rL: rL,
                 o: o, hU: H.hup, hA: (H.hf + H.hb) / 2, hL: H.hw,
                 Hh: Hh, orbit: { w: orbW, v: orbV, lat: orbL, y: eyeY } };
  }

  /* ── appendicular: the shoulder girdle ───────────────────────────────────
     cmu_mb's LeftShoulder is one offset joint between Spine1 and the upper arm; a real girdle
     has a sternoclavicular joint, an acromioclavicular joint and a scapula with two free
     corners you can feel through the skin. All placed off the rig's own shoulder point, so the
     arm hangs where the clip puts. */
  function solveGirdle(A, levels) {
    var Bm = A.bones, t1 = null;
    for (var q = 0; q < levels.length; q++) if (levels[q].n === 'T2') t1 = levels[q];
    if (!t1) return;
    var r = 0.0068 * A.stature;
    /* the top of the sternum, found the same way solveRibs finds the rest of it: forward to the
       measured centre of the chest, then out to the front */
    var fwd1 = t1.bf ? vsub(t1.bf.c, t1.p).dot(t1.ant) : 0.05;
    var man = vma(t1.p, t1.ant, fwd1 + (t1.bf ? t1.bf.hd : 0.1) * RIB_INSET * 0.84);
    for (var s = 0; s < 2; s++) {
      SD = s === 0 ? SIDE_L : SIDE_R;
      var arm = Bm[bn(s, 'Arm')];
      if (!arm) continue;
      var P1 = vcp(_s.setFromMatrixPosition(arm.matrixWorld));
      var sc = vma(man, vsub(P1, man), 0.12);
      var jsc = joint(sc, r * 1.1);                       /* sternoclavicular */
      var ac = vlerp(P1, sc, 0.16);
      var jac = joint(ac, r * 1.2);                       /* acromioclavicular */
      var lat = vperp(vsub(P1, man), t1.tan);
      var back = vcp(t1.ant).negate();
      var blade = vsub(P1, sc).length();
      /* the clavicle's own bend, kept because the point on it is an articulation of the
         collarbone the rig does not carry */
      var cBow = blade * 0.085;
      joint(vma(vlerp(sc, ac, 0.72), t1.ant, -cBow * 0.45), r * 0.7);
      link(jsc, jac);
      /* the scapula's two free corners — the medial border and the inferior angle — which is
         where the blade is felt through the skin */
      var med = vma(vma(ac, lat, -blade * 0.52), back, (t1.bf ? t1.bf.hd : 0.1) * 0.70);
      var infa = vma(vma(med, t1.tan, -0.085 * A.stature), lat, blade * 0.20);
      AN.acr[s] = ac; AN.jacr[s] = jac; AN.scapMed[s] = med; AN.scapInf[s] = infa;
      joint(med, r * 0.8); joint(infa, r * 0.8);
    }
  }

  /* ── appendicular: the paired bones ──────────────────────────────────────
     Forearm and lower leg are PAIRS — radius/ulna, tibia/fibula — and each of the four ends is
     its own articulation: radial head and tibial plateau up top, styloids and malleoli below.
     The rig has one channel there, so they go either side of the segment axis at the measured
     flesh radius. */
  function pairBones(sg, prof, r0, r1, sep, joint0, joint1) {
    var d0 = vcp(sg.lat), d1 = vcp(sg.lat).negate();
    var Ra = profAt(prof, 0.12), Rb = profAt(prof, 0.88);
    var a0 = vma(sg.a, d0, Ra * sep), b0 = vma(sg.b, d0, Rb * sep * 0.45);
    var a1 = vma(sg.a, d1, Ra * sep * 0.7), b1 = vma(sg.b, d1, Rb * sep * 0.85);
    joint(a0, r0 * 1.15); joint(a1, r1 * 1.15);
    joint(b0, r0 * 1.1); joint(b1, r1 * 1.1);
    /* the interosseous membrane's two ends are real articulations */
    link(joint0, joint1);
  }

  function solveLimbs(A) {
    for (var s = 0; s < 2; s++) {
      SD = s === 0 ? SIDE_L : SIDE_R;
      var prof, sg;
      /* humerus */
      sg = segFrame(A, bn(s, 'Arm'), bn(s, 'ForeArm'), s);
      prof = A.limb['arm' + s];
      if (sg) {
        var hr = profAt(prof, 0.5) * 0.30;
        var jsh = joint(sg.a, hr * 1.25), jel = joint(sg.b, hr * 1.15);
        link(jsh, jel);
        /* the arm hangs off the acromion, not off the neck — without this the joint chain has a
           hole exactly where a shoulder is */
        if (AN.jacr[s] !== undefined) link(AN.jacr[s], jsh);
      }
      /* radius + ulna */
      var sg2 = segFrame(A, bn(s, 'ForeArm'), bn(s, 'Hand'), s);
      var prof2 = A.limb['fore' + s];
      if (sg2) {
        var fr = profAt(prof2, 0.5) * 0.19;
        pairBones(sg2, prof2, fr, fr * 0.86, 0.34,
                  joint(sg2.a, fr * 1.2), joint(sg2.b, fr * 1.1));
      }
      /* femur */
      sg = segFrame(A, bn(s, 'UpLeg'), bn(s, 'Leg'), s);
      prof = A.limb['upleg' + s];
      if (sg) {
        var fmr = profAt(prof, 0.5) * 0.28;
        joint(sg.a, fmr * 1.2); joint(sg.b, fmr * 1.12);
      }
      /* tibia + fibula */
      var sg3 = segFrame(A, bn(s, 'Leg'), bn(s, 'Foot'), s);
      var prof3 = A.limb['leg' + s];
      if (sg3) {
        var tr = profAt(prof3, 0.5) * 0.26;
        pairBones(sg3, prof3, tr, tr * 0.52, 0.30,
                  joint(sg3.a, tr * 1.3), joint(sg3.b, tr * 1.2));
      }
    }
  }

  /* ── appendicular: the hand ──────────────────────────────────────────────
     THE POINT OF THE WHOLE FILE. cmu_mb ends the arm in three stubs; a hand has 27 bones and 19
     joints past the wrist, every one placed here in the hand's own measured frame (distal,
     radial, palmar) at fractions of its own measured length. Honest about what it is: no clip
     carries finger channels, so the digits sit in a relaxed rest curl and ride the wrist
     rigidly — they follow a punch, they do not make a fist. */
  var RAYS = [
    /* mcp: how far down the hand the knuckle sits, as a fraction of measured hand length. sp:
       where the ray sits ACROSS it, -1 (little) to +1 (index), scaled by the measured knuckle
       and fingertip breadths so a splayed hand gets splayed rays. pp/mp/dp: the phalanges,
       again as fractions — with mcp they sum to 0.94 / 1.00 / 0.95 / 0.80, the real four-finger
       ratio. */
    { n: 'index',  mcp: 0.455, sp:  1.00, pp: 0.245, mp: 0.145, dp: 0.098, curl: 1.00 },
    { n: 'middle', mcp: 0.475, sp:  0.33, pp: 0.265, mp: 0.165, dp: 0.102, curl: 1.05 },
    { n: 'ring',   mcp: 0.450, sp: -0.33, pp: 0.245, mp: 0.155, dp: 0.100, curl: 1.15 },
    { n: 'little', mcp: 0.405, sp: -1.00, pp: 0.195, mp: 0.110, dp: 0.090, curl: 1.30 }
  ];
  /* rest curl at each knuckle, in radians, toward the palm */
  var CURL = [0.20, 0.40, 0.26];

  function solveHand(A, s) {
    SD = s === 0 ? SIDE_L : SIDE_R;
    var H = A.hand[s], hand = A.bones[bn(s, 'Hand')];
    if (!H || !hand) return;
    var M = hand.matrixWorld;
    _m4.extractRotation(M);
    var o = vcp(_s.setFromMatrixPosition(M));
    var dist = vcp(H.dist).applyMatrix4(_m4).normalize();
    var rad = vcp(H.rad).applyMatrix4(_m4).normalize();
    var palm = vcp(H.palm).applyMatrix4(_m4).normalize();
    var HL = H.len, r = HL * 0.038;          /* a phalanx is ~12 mm across */
    var tips = AN.tip[s] = { wrist: o, dist: dist };

    var wrist = joint(o, r * 1.5);
    /* the carpus: two rows of small bones between the wrist and the palm */
    var carp = vma(vma(o, dist, HL * 0.085), palm, HL * 0.012);
    var jc = chain(wrist, carp, r * 1.2, r * 1.5);
    var mid = vma(vma(o, dist, HL * 0.185), palm, HL * 0.018);
    var jm = chain(jc, mid, r * 1.1, r * 1.4);
    /* the transverse arch — the palm is a vault, not a plate */
    var Wk = H.mcpW * 0.5, Wt = H.tipW * 0.5;
    for (var i = 0; i < RAYS.length; i++) {
      var R = RAYS[i];
      var arch = Math.abs(R.sp) * Math.abs(R.sp) * 0.055;       /* edges drop palmar */
      var base = vma(vma(mid, rad, Wk * R.sp * 0.72), palm, HL * arch * 0.5);
      var mcp = vma(vma(vma(o, dist, HL * R.mcp), rad, Wk * R.sp * 0.90), palm, HL * arch);
      var jb = joint(base, r * 0.75);
      link(jm, jb);
      var jmcp = chain(jb, mcp, r * 0.95, r * 0.80);             /* metacarpal */
      /* aim the ray so its TIP lands on the measured fingertip breadth: that is the splay, and
         it is this hand's, not a table's */
      var fl = (R.pp + R.mp + R.dp) * HL;
      var drift = (Wt * R.sp * 0.92 - Wk * R.sp * 0.90) / (fl || 1);
      var prev = jmcp, p = mcp, k, ax;
      var conv = vma(vcp(dist), rad, drift).normalize();
      var lens = [R.pp, R.mp, R.dp];
      for (k = 0; k < 3; k++) {
        ax = vcross(conv, palm).normalize();                     /* the knuckle axis */
        conv = vcp(conv).applyAxisAngle(ax, -CURL[k] * R.curl).normalize();
        p = vma(p, conv, HL * lens[k]);
        prev = chain(prev, p, r * (0.78 - k * 0.12), r * (0.66 - k * 0.10));
      }
      tips[R.n] = p;
    }
    /* the thumb: its own ray, set well back on the palm and rotated out of the plane of the
       other four — the one joint that makes a hand a hand */
    var tb = vma(vma(vma(o, dist, HL * 0.115), rad, Wk * 0.80), palm, HL * 0.045);
    var jtb = joint(tb, r * 0.9);
    link(jm, jtb);
    var tdir = vcp(dist).addScaledVector(rad, 0.62).addScaledVector(palm, 0.30).normalize();
    var tmc = vma(tb, tdir, HL * 0.255);
    var jt1 = chain(jtb, tmc, r * 0.95, r * 0.82);
    var tax = vcross(tdir, vcp(palm).addScaledVector(rad, -0.5)).normalize();
    tdir = vcp(tdir).applyAxisAngle(tax, -0.22).normalize();
    var tpp = vma(tmc, tdir, HL * 0.165);
    var jt2 = chain(jt1, tpp, r * 0.80, r * 0.70);
    tdir = vcp(tdir).applyAxisAngle(tax, -0.30).normalize();
    tips.thumb = vma(tpp, tdir, HL * 0.120);
    chain(jt2, tips.thumb, r * 0.68, r * 0.60);
  }

  /* ── appendicular: the foot ──────────────────────────────────────────────
     Same problem, same answer: cmu_mb ends the leg at ToeBase. Calcaneus, talus, midfoot, five
     metatarsals and fourteen phalanges in the foot's measured frame — hallux two phalanges, the
     other four three, which is the difference you notice when a foot rolls. */
  var TOES = [
    { sp:  0.34, mt: 0.98, pp: 0.115, mp: 0.000, dp: 0.055 },   /* hallux */
    { sp:  0.13, mt: 1.00, pp: 0.105, mp: 0.048, dp: 0.036 },
    { sp: -0.05, mt: 0.99, pp: 0.098, mp: 0.046, dp: 0.034 },
    { sp: -0.22, mt: 0.95, pp: 0.086, mp: 0.040, dp: 0.032 },
    { sp: -0.38, mt: 0.88, pp: 0.068, mp: 0.032, dp: 0.028 }
  ];
  function solveFoot(A, s) {
    SD = s === 0 ? SIDE_L : SIDE_R;
    var F = A.foot[s], foot = A.bones[bn(s, 'Foot')];
    if (!F || !foot) return;
    var M = foot.matrixWorld;
    _m4.extractRotation(M);
    var o = vcp(_s.setFromMatrixPosition(M));
    var fwd = vcp(F.fwd).applyMatrix4(_m4).normalize();
    var up = vcp(F.up).applyMatrix4(_m4).normalize();
    var med = vcp(F.med).applyMatrix4(_m4).normalize();
    var FL = F.len, W = F.width, r = FL * 0.034;
    var sole = F.sole;                                   /* negative: below the ankle */

    var ank = joint(o, r * 1.6);                         /* the talus, = the rig ankle */
    var heel = vma(vma(o, fwd, -FL * 0.205), up, sole * 0.45);
    var jh = chain(ank, heel, r * 1.5, r * 1.5);
    /* navicular on the inside, cuboid on the outside — the two paths the arch's load actually
       takes */
    var nav = vma(vma(vma(o, fwd, FL * 0.16), med, W * 0.16), up, sole * 0.30);
    var cub = vma(vma(vma(o, fwd, FL * 0.11), med, -W * 0.24), up, sole * 0.52);
    var jn = chain(ank, nav, r * 1.1, r * 1.2);
    var jcb = chain(jh, cub, r * 1.1, r * 1.2);
    for (var i = 0; i < TOES.length; i++) {
      var T = TOES[i];
      var from = i < 3 ? nav : cub, jf = i < 3 ? jn : jcb;
      var arch = (1 - Math.abs(T.sp) * 1.4);
      var mtp = vma(vma(vma(o, fwd, FL * 0.50 * T.mt + FL * 0.06),
                         med, W * T.sp * 0.5), up, sole * (0.86 - 0.10 * arch));
      var jb = joint(vlerp(from, mtp, 0.12), r * 0.7);
      link(jf, jb);
      var jmt = chain(jb, mtp, r * 0.9, r * 0.75);       /* the metatarsal */
      var dir = vcp(fwd).addScaledVector(med, T.sp * 0.10).normalize();
      var p = mtp, prev = jmt, lens = T.mp > 0 ? [T.pp, T.mp, T.dp] : [T.pp, T.dp], k;
      for (k = 0; k < lens.length; k++) {
        dir = vcp(dir).applyAxisAngle(vcross(dir, up).normalize(), k === 0 ? 0.10 : 0.18).normalize();
        p = vma(p, dir, FL * lens[k]);
        prev = chain(prev, p, r * (0.70 - k * 0.09), r * (0.60 - k * 0.08));
      }
    }
  }

  /* ── one frame ───────────────────────────────────────────────────────────
     Order matters: column first (everything hangs off it), then cage and girdles, then limbs —
     solveLimbs links the arm to solveGirdle's acromion, and the digits ride the wrist and ankle
     solveLimbs placed. */
  var _lv = [];
  function solve() {
    var A = MVA.atlas;
    if (!A) return;
    VN = 0; C.joint = 0; C.link = 0;
    SD = SIDE_AXIS;
    AN.lvl = {}; AN.tip = []; AN.skull = null; AN.stern = [];
    AN.acr = []; AN.jacr = []; AN.scapMed = []; AN.scapInf = [];
    AN.rib = []; AN.crest = []; AN.hip = []; AN.si = []; AN.symph = null;
    _lv.length = 0;
    var levels = solveColumn(A, _lv);
    solveRibs(A, levels);
    solvePelvis(A, levels);
    solveGirdle(A, levels);
    solveSkull(A, levels);
    solveLimbs(A);
    solveHand(A, 0); solveHand(A, 1);
    solveFoot(A, 0); solveFoot(A, 1);
    MVA.counts.joint = C.joint; MVA.counts.link = C.link;
    /* the Bones layer is a mesh, so its count is the mesh's: the number of anatomical pieces
       the actor build fitted, not a pool length */
    MVA.counts.bone = (MVR.meta && MVR.meta.skeleton && MVR.meta.skeleton.pieces) || 0;
    /* one écorché skin, or none — the Muscles layer is a mesh too */
    MVA.counts.muscle = MVA.ec ? 1 : 0;
  }

  /* ── drawing it ──────────────────────────────────────────────────────────
     Two InstancedMeshes plus the head's clipped copy of the joints — three draw calls,
     per-instance matrices rebuilt from the solved pools every frame. The old helper's
     `linewidth: 2` was never honoured by any desktop GL driver: a GL_LINE is one pixel wide
     whatever you ask, at any zoom. A capsule is geometry — thickness in metres, it shades, it
     occludes, and it thins as the camera pulls back. */
  var GFX = null;
  var _a = new THREE.Vector3(), _d = new THREE.Vector3();

  function ensureGfx(cap) {
    if (GFX) return GFX;
    function mk(geo, mat, n, order) {
      var m = new THREE.InstancedMesh(geo, mat, n);
      m.frustumCulled = false;            /* the pose leaves the rest bbox */
      m.renderOrder = order;
      m.count = 0;
      MVST3.scene.add(m);
      return m;
    }
    /* NO LATHE BONES ANY MORE: the Bones layer is the actor's own fitted skeleton mesh, so the
       instanced shafts, cranial volumes and eye sockets have no consumer and are not created.
       Joint and link are untouched — they are the articulation, not the bone, and nothing
       replaces them. */
    GFX = {
      joint: mk(new THREE.SphereGeometry(1, 14, 10),
        new THREE.MeshStandardMaterial({ color: srgb(0x7fe3ff), emissive: srgb(0x12586f),
          roughness: 0.30, metalness: 0.05 }), cap.joint, 3),
      link: mk(new THREE.CylinderGeometry(1, 1, 1, 6, 1, true),
        new THREE.MeshStandardMaterial({ color: srgb(0x2ec6e0), emissive: srgb(0x0d4353),
          roughness: 0.40, metalness: 0.0 }), cap.link, 3),
      cap: cap
    };
    /* THE HEAD'S OWN MESH. The head really is cut, dead down the face, so the joints inside
       the skull live in this clone and only it is clipped. */
    GFX.jointH = mk(GFX.joint.geometry, GFX.joint.material.clone(), cap.jointH, 3);
    return GFX;
  }

  /* one round tube from a to b, which is every link there is. A zero radius or a zero length
     gets a zero matrix rather than a sliver or a NaN. */
  function put(mesh, i, a, b, r) {
    _d.subVectors(b, a);
    var len = _d.length();
    if (len < 1e-7 || !(r > 0)) { _m4.makeScale(0, 0, 0); mesh.setMatrixAt(i, _m4); return; }
    _d.multiplyScalar(1 / len);
    _a.copy(a).addScaledVector(_d, len / 2);
    _q.setFromUnitVectors(UPY, _d);
    _s.set(r, len, r);
    _m4.compose(_a, _q, _s);
    mesh.setMatrixAt(i, _m4);
  }
  function putBall(mesh, i, p, r) {
    _s.set(r, r, r);
    _m4.compose(p, IDQ, _s);
    mesh.setMatrixAt(i, _m4);
  }

  /* WHAT GOES IN WHICH HALF. Once per primitive per frame, pure bookkeeping — no
     geometry, no distances, no plane, because membership was decided when the part was
     solved and cannot change because the actor moved.
       · lateral: its own half, whole, wherever the pose has carried it
       · axial (column, sternum, sacrum): the SKELETON half, whole, down the seam, the
         way the reference plate draws its spine
       · head: the clipped mesh, and only there */
  function bin(sd, half) {
    if (!MVA.split) return 1;                    /* 1 = the plain mesh */
    if (sd === SIDE_HEAD) return 2;              /* 2 = the head's cut mesh */
    if (sd === SIDE_AXIS) return half === SK.skel ? 1 : 0;
    return sd === half ? 1 : 0;                  /* 0 = not drawn at all */
  }
  var SK = { skel: 1, mus: 0 };

  function draw() {
    if (!GFX) return;
    var i, n, o, b, g, gh, nb, nh;
    skelSkin();                    /* the Bones layer, and SK with it */

    g = GFX.joint; gh = GFX.jointH; nb = 0; nh = 0;
    n = MVA.on.joint ? Math.min(C.joint, GFX.cap.joint) : 0;
    for (i = 0; i < n; i++) {
      o = P.joint[i]; b = bin(o.sd, SK.skel);
      if (b === 1) putBall(g, nb++, o.p, o.r);
      else if (b === 2 && nh < GFX.cap.jointH) putBall(gh, nh++, o.p, o.r);
    }
    g.count = nb; if (nb) g.instanceMatrix.needsUpdate = true;
    gh.count = nh; if (nh) gh.instanceMatrix.needsUpdate = true;

    /* the thin chain between joints. A link inside the skull is a single hair-thin line across
       the midline and is not worth a fifth cut mesh — it rides the plain one. */
    g = GFX.link; nb = 0;
    n = MVA.on.joint ? Math.min(C.link, GFX.cap.link) : 0;
    var lr = 0.0020 * (MVA.atlas ? MVA.atlas.stature : 1.7);
    for (i = 0; i < n; i++) {
      o = P.link[i]; b = bin(o.sd, SK.skel);
      if (b) put(g, nb++, P.joint[o.i].p, P.joint[o.j].p, lr);
    }
    g.count = nb; if (nb) g.instanceMatrix.needsUpdate = true;
  }

  /* ── the clay goes to glass ──────────────────────────────────────────────
     Solid geometry inside a solid body is invisible. The old helper dodged that with
     depthTest:false, drawing the rig flat on top, near and far alike. The body goes translucent
     instead and everything depth-tests normally. */
  function applySkin() {
    if (!MVR.inner) return;
    var any = MVA.on.bone || MVA.on.joint || MVA.on.muscle;
    var v = any ? Math.max(0.06, Math.min(1, MVA.skin)) : 1;
    /* THE ACTOR STAYS AN ACTOR. A lit clay surface at low alpha over a dark stage loses its
       form: the shading it reads by is multiplied away with it. An emissive floor that grows as
       the alpha falls puts it back, so the shoulder and the jaw are shapes you see THROUGH. */
    var lift = (1 - v) * 0.5;
    /* MESH MODE (the operator's suggestion, and right for a crowded frame): the actor as its
       own wireframe. No interior to hide behind, so the anatomy reads at full contrast and the
       body is still a body. It wants more alpha: a wire covers a fraction of the pixels a face
       does. */
    var wire = MVA.body === 'mesh';
    MVR.inner.traverse(function (o) {
      if ((!o.isMesh && !o.isSkinnedMesh) || !o.material) return;
      /* `body: off` hides the SKIN. The skeleton lives in the same GLB and would be switched
         off with it — which is the one thing every bare view needs on. A tagged mesh is a layer
         of ours and is driven by its own switch, never by the body's. */
      if (o.userData && o.userData.mvaLayer) return;
      var m = o.material;
      o.visible = MVA.body !== 'off';
      m.wireframe = wire;
      var a = wire ? Math.min(1, 0.22 + v * 0.55) : v;
      m.transparent = a < 0.999;
      m.opacity = a;
      m.depthWrite = !wire && a > 0.999;
      if (m.emissive) {
        if (!m.userData.__base) m.userData.__base = m.color.clone();
        m.emissive.copy(m.userData.__base).multiplyScalar(wire ? 0.55 : lift);
      }
      /* THE SKIN TAKES THE SKELETON'S HALF, by the side each vertex was told it belongs to
         rather than by any cut through space. */
      sidePatch(m);
      if (m.userData.__sideU)
        m.userData.__sideU.value = (MVA.split && o.geometry && o.geometry.attributes.aSide)
          ? (MVA.splitSide ? SIDE_L : SIDE_R) : -1;
      m.needsUpdate = true;
      o.renderOrder = 6;
    });
    skelSkin();          /* the body switches never speak for the skeleton */
  }

  /* One extra varying and one `discard`. `uSideKeep` < 0 keeps everything — every view but the
     two split ones — for one comparison against a uniform. The attribute is baked in measure();
     a mesh without one stays at -1 and is drawn whole, which is the safe way to be wrong. */
  function sidePatch(m) {
    if (!m || m.userData.__sideU) return;
    m.userData.__sideU = { value: -1 };
    var prev = m.onBeforeCompile;
    m.onBeforeCompile = function (sh, r) {
      if (prev) prev.call(this, sh, r);
      sh.uniforms.uSideKeep = m.userData.__sideU;
      sh.vertexShader = 'attribute float aSide;\nvarying float vSide;\n'
        + sh.vertexShader.replace('#include <begin_vertex>',
            '#include <begin_vertex>\n\tvSide = aSide;');
      sh.fragmentShader = 'uniform float uSideKeep;\nvarying float vSide;\n'
        + sh.fragmentShader.replace('#include <clipping_planes_fragment>',
            '#include <clipping_planes_fragment>\n'
            + '\tif (uSideKeep >= 0.0 && abs(vSide - uSideKeep) > 0.5) discard;');
    };
    m.needsUpdate = true;
  }

  /* THE SAME PATCH, WITH THE COLUMN SPARED. The skin's test discards every vertex whose side is
     not the kept one, and SIDE_AXIS (3) is no side — so it would throw away spine, sacrum and
     neck, and a skeleton with no column is a pile of limbs. `vSide < 2.5` lets the axial
     vertices through. */
  function skelPatch(m) {
    if (!m || m.userData.__sideU) return;
    m.userData.__sideU = { value: -1 };
    var prev = m.onBeforeCompile;
    m.onBeforeCompile = function (sh, r) {
      if (prev) prev.call(this, sh, r);
      sh.uniforms.uSideKeep = m.userData.__sideU;
      sh.vertexShader = 'attribute float aSide;\nvarying float vSide;\n'
        + sh.vertexShader.replace('#include <begin_vertex>',
            '#include <begin_vertex>\n\tvSide = aSide;');
      sh.fragmentShader = 'uniform float uSideKeep;\nvarying float vSide;\n'
        + sh.fragmentShader.replace('#include <clipping_planes_fragment>',
            '#include <clipping_planes_fragment>\n'
            + '\tif (uSideKeep >= 0.0 && vSide < 2.5'
            + ' && abs(vSide - uSideKeep) > 0.5) discard;');
    };
    m.needsUpdate = true;
  }

  /* ── THE BONES LAYER ─────────────────────────────────────────────────────
     Not a drawing of a skeleton — the skeleton. The actor GLB carries the Blender Studio CC0
     anatomical skeleton as a second SkinnedMesh over the same 31 joints, fitted piece by piece
     to THIS body, so it bends with the clip for free and costs one draw call; everything the
     lathe passes used to approximate is simply there. Warm ivory, matte, no per-instance hash
     (no instances to vary, and the mesh has its own form to read by), no shadows (one key
     light, and a bone would shadow the body from within). */
  function skelAdopt(inner) {
    var sk = inner && inner.getObjectByName('skeleton');
    if (!sk || !sk.isSkinnedMesh) {
      MVA.skel = null;
      /* and NO fallback to the cylinders: a lathe skeleton is what this layer was replaced for.
         An empty layer says so honestly. */
      MVA.note = 'actor built without a skeleton mesh — rebuild the actor';
      return;
    }
    sk.userData.mvaLayer = 'bone';
    var m = new THREE.MeshStandardMaterial({ color: srgb(0xe9dfc8),
                                             roughness: 0.62, metalness: 0 });
    skelPatch(m);
    if (sk.material && sk.material.dispose) sk.material.dispose();
    sk.material = m;
    MVA.__skelMat = m;
    sk.frustumCulled = false;            /* a posed skin leaves its rest bbox */
    sk.castShadow = false; sk.receiveShadow = false;
    sk.renderOrder = 5;
    MVA.skel = sk;
  }

  /* the layer's per-frame state: on with the Bones switch, and cut to the skeleton's own half —
     never the muscle's — when the view is split. It owns SK as well, because every caller of
     either needs both and the two must never disagree about which half is whose. */
  function skelSkin() {
    SK.mus = MVA.splitSide ? SIDE_R : SIDE_L;
    SK.skel = MVA.splitSide ? SIDE_L : SIDE_R;
    ecSkin();                /* and the Muscles layer, cut to the other half */
    var sk = MVA.skel;
    if (!sk) return;
    sk.visible = !!MVA.on.bone;
    var u = sk.material && sk.material.userData && sk.material.userData.__sideU;
    if (u)
      u.value = (MVA.split && sk.geometry && sk.geometry.attributes.aSide)
        ? SK.skel : -1;
  }

  /* ── THE MUSCLES LAYER ───────────────────────────────────────────────────
     An ÉCORCHÉ, not a table of bellies: the plate the operator works from is a body with the
     skin taken off — ONE body-shaped surface with the muscles painted and grooved onto it. So
     this is a second SkinnedMesh on the body's OWN geometry, sharing the body's skeleton so it
     bends with the clip for free and costs one draw call, wearing the écorché atlas
     char_photoreal baked from klein RefControl (Apache-2.0).

     ONE AND A HALF MILLIMETRES UNDER THE CLAY, because two surfaces on identical geometry
     z-fight everywhere and a 45 %-opaque skin over that is a shimmering mess. It is pushed in
     along its own normals in the vertex shader, not on disk, so the geometry stays the body's.

     AND IT GOES IN ALONG `normal`, NOT objectNormal. By <begin_vertex>, <skinnormal_vertex> has
     already multiplied objectNormal by the composed skin matrix, while `transformed` is still
     in bind space and <skinning_vertex> is about to multiply IT by that same matrix. Offsetting
     along objectNormal rotates the offset twice: on a swung arm the 1.5 mm can end up pointing
     outward — the very z-fight the inset exists to prevent. `normal` is the raw bind-space
     attribute. */
  var EC = { man: {}, tok: 0 };
  var EC_INSET = 0.0015;

  /* the SKIN: the biggest skinned mesh that is not one of our own layers */
  function bodyMesh(inner) {
    var best = null, n = -1;
    if (!inner) return null;
    inner.traverse(function (o) {
      if (!o.isSkinnedMesh || !o.geometry || !o.geometry.attributes.position) return;
      if (o.userData && o.userData.mvaLayer) return;
      var c = o.geometry.attributes.position.count;
      if (c > n) { n = c; best = o; }
    });
    return best;
  }

  /* PER VERTEX: WHICH UDIM TILE -> WHICH ATLAS CELL. Same rule and reason as
     char_photoreal.js's remapUV (lines 78-102): the body's uv is the Blender UDIM layout the
     bake came from and the atlas is those tiles packed into a grid. Faces never straddle tiles
     here, so a vertex's own tile is its face's. glTF v = 1 - Blender v, the only flip in here. */
  function remapUV(geom, atlas) {
    var uv = geom.attributes.uv;
    if (!uv) return false;
    if (!geom.userData.uv0) geom.userData.uv0 = uv.array.slice(0);
    var src = geom.userData.uv0, out = new Float32Array(src.length);
    /* cells: [tu, tv, x0, y0, size] in pixels, or the older [tu, tv, col, row] */
    var lut = {}, W = atlas.width, Hh = atlas.height, T = atlas.tile || 1024, i;
    for (i = 0; i < atlas.tiles.length; i++) {
      var t = atlas.tiles[i];
      lut[t[0] + ',' + t[1]] = (t.length >= 5) ? [t[2], t[3], t[4]] : [t[2] * T, t[3] * T, T];
    }
    var miss = 0;
    for (var k = 0; k < src.length; k += 2) {
      var u = src[k], vb = 1.0 - src[k + 1];              /* glTF v -> Blender v */
      var tu = Math.floor(u), tv = Math.floor(vb);
      var cell = lut[tu + ',' + tv];
      if (!cell) { miss++; out[k] = 0; out[k + 1] = 0; continue; }
      out[k] = (cell[0] + (u - tu) * cell[2]) / W;
      out[k + 1] = (cell[1] + (1.0 - (vb - tv)) * cell[2]) / Hh;  /* glTF v: 0 at the top */
    }
    geom.setAttribute('uv', new THREE.BufferAttribute(out, 2));
    geom.attributes.uv.needsUpdate = true;
    geom.userData.uvAtlas = atlas.width + 'x' + atlas.height;
    geom.userData.uvMiss = miss;
    return true;
  }

  function ecTex(url, isColour, cb) {
    new THREE.TextureLoader().load(url, function (t) {
      t.flipY = false;                                  /* glTF UV origin: top-left */
      if (isColour) {
        if ('colorSpace' in t && THREE.SRGBColorSpace) t.colorSpace = THREE.SRGBColorSpace;
        else if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
      }
      t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
      t.generateMipmaps = true;
      t.minFilter = THREE.LinearMipmapLinearFilter;
      try { t.anisotropy = MVST3.renderer.capabilities.getMaxAnisotropy(); } catch (e) {}
      cb(t);
    }, undefined, function () { cb(null); });
  }

  function ecNote(why) {
    MVA.ecNote = why || '';
    if (why && !MVA.note) MVA.note = why;
    if (typeof MVR.panelRender === 'function') MVR.panelRender();
  }

  function ecMat(map, bump) {
    var mat = new THREE.MeshStandardMaterial({
      map: map, bumpMap: bump, bumpScale: EC_INSET, roughness: 0.55, metalness: 0
    });
    mat.onBeforeCompile = function (sh) {
      sh.vertexShader = sh.vertexShader.replace('#include <begin_vertex>',
        '#include <begin_vertex>\n\ttransformed -= normal * ' + EC_INSET.toFixed(6) + ';');
    };
    /* sidePatch CHAINS onto whatever onBeforeCompile is already installed, so the inset has to
       go on first — and the écorché takes the MUSCLE half */
    sidePatch(mat);
    return mat;
  }

  function ecBuild(body, man, map, bump) {
    var geo = body.geometry.clone();
    /* BufferGeometry.copy() assigns userData BY REFERENCE in r147, so without this the clone's
       uv0 and uvAtlas would be written into the body's own record and the clay would claim to
       be wearing an atlas. */
    geo.userData = {};
    if (!geo.attributes.aSide) {
      geo.dispose();
      return ecNote('the body carries no aSide attribute — measure() ran after the clone');
    }
    if (!remapUV(geo, man.atlas)) {
      geo.dispose();
      return ecNote('the body has no uv attribute to remap onto the atlas');
    }
    var ec = new THREE.SkinnedMesh(geo, ecMat(map, bump));
    ec.name = 'ecorche';
    ec.userData.mvaLayer = 'muscle';
    ec.bindMode = body.bindMode;
    /* A SIBLING WITH THE BODY'S OWN TRANSFORM. Skinning happens in bind space and the result is
       taken to the world by the mesh's matrixWorld, so the écorché's has to be the body's to
       the last bit. */
    ec.position.copy(body.position);
    ec.quaternion.copy(body.quaternion);
    ec.scale.copy(body.scale);
    (body.parent || MVR.inner).add(ec);
    ec.updateMatrixWorld(true);
    ec.bind(body.skeleton, body.bindMatrix);
    ec.frustumCulled = false;            /* a posed skin leaves its rest bbox */
    ec.castShadow = false; ec.receiveShadow = false;
    ec.renderOrder = 5;
    MVA.ec = ec;
    MVA.ecName = man.body || '';
    MVA.ecSize = man.atlas.width + 'x' + man.atlas.height;
    MVA.ecNote = '';
    MVA.counts.muscle = 1;
    /* THE PREVIEWS WERE BUILT WITHOUT IT. The atlas is 8 MB of JPEG and lands whole seconds
       after the menu could have been opened, so every cached thumbnail showing a bare skeleton
       where the muscle half belongs is now wrong. Throw them away; the next open re-renders six
       frames. */
    TH.cache = {}; TH.key = '';
    applySkin();
    if (MVA.ready) { updateClip(); applyClip(); draw(); }
    if (typeof MVR.panelRender === 'function') MVR.panelRender();
  }

  /* the atlas for THIS body, with the male plate as the fallback while the female bake is still
     to come */
  function ecFetch(body, cb) {
    if (EC.man[body] !== undefined) return cb(EC.man[body]);
    fetch('/inspect/api/studio/movement_rig/ecorche?body=' + encodeURIComponent(body),
          { cache: 'no-cache' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        EC.man[body] = (j && j.ok && j.atlas && j.atlas.tiles && j.atlas.tiles.length) ? j : null;
        cb(EC.man[body]);
      })
      .catch(function () { EC.man[body] = null; cb(null); });
  }

  function ensureEcorche(inner) {
    var body = bodyMesh(inner);
    if (!body) return ecNote('no body mesh to drape the écorché on');
    var base = String((MVR.meta && MVR.meta.base_body_id) || '');
    var want = (base.indexOf('female') === 0 ? 'female' : 'male') + '_ecorche';
    var tok = ++EC.tok;
    function got(man) {
      if (tok !== EC.tok) return;                  /* a newer actor is loading */
      if (!man && want !== 'male_ecorche')
        return ecFetch('male_ecorche', function (m2) {
          if (tok !== EC.tok) return;
          if (!m2) return ecNote('no écorché atlas published — bake one in Character Studio');
          drape(m2);
        });
      if (!man) return ecNote('no écorché atlas published — bake one in Character Studio');
      drape(man);
    }
    function drape(man) {
      ecTex(man.albedo_url + '?v=' + Math.round(man.albedo_mtime || 0), true, function (map) {
        if (tok !== EC.tok) { if (map) map.dispose(); return; }
        if (!map) return ecNote('the écorché albedo would not load');
        ecTex(man.bump_url + '?v=' + Math.round(man.bump_mtime || 0), false, function (bump) {
          if (tok !== EC.tok) { map.dispose(); if (bump) bump.dispose(); return; }
          ecBuild(body, man, map, bump);
        });
      });
    }
    ecFetch(want, got);
  }

  /* the layer's per-frame state: on with the Muscles switch, and cut to the MUSCLE half — never
     the skeleton's — when the view is split. The head needs no plane: aSide for a Head-dominant
     vertex was baked by bind lateral, so the face is cut down the middle, the mirror of the
     skull's. */
  function ecSkin() {
    var ec = MVA.ec;
    if (!ec) return;
    ec.visible = !!(MVA.on.muscle && MVA.ready);
    var u = ec.material && ec.material.userData && ec.material.userData.__sideU;
    if (u)
      u.value = (MVA.split && ec.geometry.attributes.aSide) ? SK.mus : -1;
  }

  function ecDrop() {
    var ec = MVA.ec;
    EC.tok++;                      /* anything in flight is for a dead actor */
    MVA.ec = null; MVA.ecName = ''; MVA.ecSize = ''; MVA.ecNote = '';
    if (!ec) return;
    if (ec.parent) ec.parent.remove(ec);
    if (ec.geometry) ec.geometry.dispose();
    var m = ec.material;
    if (m) {
      if (m.map) m.map.dispose();
      if (m.bumpMap) m.bumpMap.dispose();
      m.dispose();
    }
  }

  /* ── the seam movement_rig.js calls ──────────────────────────────────── */
  MVA.build = function (inner, helper) {
    MVA.drop(true);
    MVA.ready = false;
    var t0 = (window.performance && performance.now) ? performance.now() : 0;
    MVA.atlas = measure(inner, (helper && helper.bones) || []);
    if (!MVA.atlas) return;
    skelAdopt(inner);                    /* the Bones layer, before the first solve */
    /* the Muscles layer. It finishes asynchronously — 8 MB of atlas — and puts itself on screen
       when it lands; nothing below waits for it. */
    ensureEcorche(inner);
    solve();                                         /* once, to size the pools */
    var cap = {
      joint: Math.ceil(C.joint * 1.08) + 32,
      link: Math.ceil(C.link * 1.08) + 32,
      /* the joints inside the skull are a small, fixed set */
      jointH: 32
    };
    ensureGfx(cap);
    MVA.ms = ((window.performance && performance.now) ? performance.now() : 0) - t0;
    MVA.ready = true;
    if (helper) helper.visible = MVR.bones;
    /* a new body is a new set of previews; the old actor's are worthless */
    TH.cache = {}; TH.key = ''; MVA.thumbErr = '';
    ensureClip();
    /* restore the chosen view, so the tab opens the way it was left rather than on whatever the
       three switches were last persisted as */
    var want = lsGet('view', '');
    if (want && viewByKey(want)) MVA.applyView(want, true);
    applySkin();
    updateClip();
    applyClip();
    draw();
  };

  MVA.drop = function (quiet) {
    MVA.ready = false; MVA.atlas = null;
    /* the skeleton is the GLB's own mesh and leaves with dropModel(); only the material put on
       it here is ours to dispose */
    if (MVA.__skelMat && MVA.__skelMat.dispose) MVA.__skelMat.dispose();
    MVA.__skelMat = null; MVA.skel = null;
    /* the écorché IS ours, geometry and textures both */
    ecDrop();
    if (GFX) {
      ['joint', 'link', 'jointH'].forEach(function (k) {
        var m = GFX[k];
        if (!m) return;
        MVST3.scene.remove(m);
        if (m.geometry) m.geometry.dispose();
        if (m.material) m.material.dispose();
        if (m.dispose) m.dispose();
      });
      GFX = null;
    }
    if (!quiet) MVA.counts = { joint: 0, link: 0, bone: 0, muscle: 0 };
  };

  MVA.tick = function () {
    if (!MVA.ready) return;
    /* ONE FRAME OF LAG, OTHERWISE. mixer.update() writes bone .position and .quaternion;
       nothing recomputes .matrixWorld until the renderer walks the scene, AFTER this. Solving
       first places the anatomy from the previous pose — fine at 60 fps, 30 cm of trail at
       headless SwiftShader's 3. */
    if (MVR.inner) MVR.inner.updateMatrixWorld(true);
    solve();
    updateClip();          /* the midline follows the pose, not the room */
    draw();
  };

  /* ── THE VIEW MENU ───────────────────────────────────────────────────────
     (2026-09-23, operator: "icon with dropdown list to change view of the body".) Three
     independent switches plus a body mode is four controls and sixteen states, and the
     half-dozen combinations anyone actually wants are buried in them. This is one icon that
     names those combinations.

     A NOTE ON THE LIST AS ASKED FOR. Two of the six were the same set — "Skeleton + muscles +
     joints, no skin" and "Muscle packs + skeleton + joints, no skin" — so the second slot holds
     SKELETON ONLY instead, the view every labelled plate in Documents is drawn in and the one
     combination the others could not reach. Say the word and it goes back.

     The half-and-half views are the pose of the reference plate: muscle on one side, bone and
     joints and skin on the other. Which side a part is on is the baked `SD` / `aSide` tag, not
     a plane — see WHICH HALF, above. */
  var VIEWS = [
    { k: 'skin', n: 'Skin only',
      d: 'The actor as it renders — no skeleton, no muscles, no joints',
      on: { bone: false, joint: false, muscle: false }, body: 'solid', split: 0 },
    { k: 'anat', n: 'Skeleton + muscles + joints',
      d: 'The whole anatomy, with the actor out of the way',
      on: { bone: true, joint: true, muscle: true }, body: 'off', split: 0 },
    { k: 'halfskin', n: 'Half muscle · half skin + skeleton',
      d: 'Split on the midline: muscle packs one side, skin over skeleton and joints the other',
      on: { bone: true, joint: true, muscle: true }, body: 'solid', split: 1 },
    { k: 'halfbare', n: 'Half muscle · half skeleton',
      d: 'The reference plate: muscle packs one side, bare skeleton and joints the other',
      on: { bone: true, joint: true, muscle: true }, body: 'off', split: 1 },
    { k: 'bones', n: 'Skeleton only',
      d: 'Bone alone — no muscles, no joints, no skin',
      on: { bone: true, joint: false, muscle: false }, body: 'off', split: 0 },
    { k: 'all', n: 'Skin + muscles + skeleton + joints',
      d: 'Everything at once, the actor translucent in front of it',
      on: { bone: true, joint: true, muscle: true }, body: 'solid', split: 0 }
  ];
  MVA.views = VIEWS;
  MVA.split = parseInt(lsGet('split', '0'), 10) ? 1 : 0;
  /* 0 = muscle on the actor's LEFT, the way the reference plate is drawn */
  MVA.splitSide = parseInt(lsGet('splitside', '0'), 10) ? 1 : 0;

  /* a body cut down the middle: the left half filled, the right half ribs. It is the feature
     drawn as its own glyph, which beats any stock icon at saying what the menu behind it does. */
  var VIEW_ICON =
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">'
    + '<path d="M8 1.4a1.5 1.5 0 0 1 0 3 1.5 1.5 0 0 1 0-3z" fill="currentColor"/>'
    + '<path d="M8 5h-2.2L4 9.2l1.3.6L6.2 8v6.6h1.8" fill="none" stroke="currentColor"'
    + ' stroke-width="1.25" stroke-linejoin="round" stroke-linecap="round"/>'
    + '<path d="M8 5h2.2L12 9.2l-1.3.6L9.8 8v6.6H8" fill="currentColor" opacity=".55"/>'
    + '<path d="M8 .8v14.4" stroke="currentColor" stroke-width=".9" opacity=".5"/>'
    + '</svg>';

  function injectViewCss() {
    if (document.getElementById('mva-css')) return;
    var st = document.createElement('style');
    st.id = 'mva-css';
    st.textContent =
      '.mva-viewrow{margin-bottom:1px;}'
      + '#mvr-panel button.mva-viewbtn{display:flex;align-items:center;gap:6px;width:100%;'
      + 'flex:1 1 auto;justify-content:flex-start;padding:4px 7px;background:#121a25;}'
      + '#mvr-panel button.mva-viewbtn svg{flex:0 0 auto;color:#8fd4ff;}'
      + '#mvr-panel button.mva-viewbtn span{flex:1 1 auto;text-align:left;overflow:hidden;'
      + 'text-overflow:ellipsis;white-space:nowrap;}'
      + '.mva-caret{font-style:normal;color:var(--muted,#8b939e);flex:0 0 auto;}'
      + '.mva-menu{display:flex;flex-direction:column;gap:1px;padding:2px 0 3px;}'
      + '.mva-menu[hidden]{display:none;}'
      + '#mvr-panel button.mva-vi{display:flex;flex-direction:column;align-items:flex-start;'
      + 'gap:1px;width:100%;flex:1 1 auto;text-align:left;padding:4px 8px;background:transparent;'
      + 'border-color:transparent;}'
      + '#mvr-panel button.mva-vi:hover{background:#1a212c;border-color:var(--line,#242a33);}'
      + '#mvr-panel button.mva-vi.on{background:#1d2d3d;color:#8fd4ff;}'
      + '.mva-vi b{font-weight:600;font-size:.66rem;}'
      + '.mva-vi em{font-style:normal;color:var(--muted,#8b939e);font-size:.58rem;line-height:1.3;'
      + 'white-space:normal;}'
      /* the preview rides OUTSIDE the panel, over the empty stage to its left, because the
         panel is 266 px wide and a thumbnail inside it would be a postage stamp */
      + '#mva-prev{position:absolute;z-index:7;display:none;padding:6px;border-radius:9px;'
      + 'background:rgba(12,15,20,.95);border:1px solid var(--line,#242a33);'
      + 'box-shadow:0 8px 28px rgba(0,0,0,.6);pointer-events:none;}'
      + '#mva-prev.on{display:block;}'
      + '#mva-prev img{display:block;width:' + TH_W + 'px;height:' + TH_H + 'px;border-radius:5px;'
      + 'background:#0a0d12;}'
      + '#mva-prev div{color:var(--muted,#8b939e);font-size:.58rem;margin-top:4px;max-width:'
      + TH_W + 'px;line-height:1.3;}';
    document.head.appendChild(st);
  }

  function viewByKey(k) {
    for (var i = 0; i < VIEWS.length; i++) if (VIEWS[i].k === k) return VIEWS[i];
    return null;
  }
  /* which preset the switches are currently sitting on, or 'custom' — the three buttons still
     work on their own and the icon must not lie about what is on screen when they do */
  function matchView() {
    for (var i = 0; i < VIEWS.length; i++) {
      var v = VIEWS[i];
      if (v.on.bone === MVA.on.bone && v.on.joint === MVA.on.joint
          && v.on.muscle === MVA.on.muscle && v.body === MVA.body
          && (v.split ? 1 : 0) === (MVA.split ? 1 : 0)) return v.k;
    }
    return 'custom';
  }
  MVA.viewName = function () {
    var k = matchView();
    var v = viewByKey(k);
    return v ? v.n : 'Custom';
  };

  MVA.applyView = function (k, quiet) {
    var v = viewByKey(k);
    if (!v) return;
    MVA.on.bone = v.on.bone; MVA.on.joint = v.on.joint; MVA.on.muscle = v.on.muscle;
    MVA.body = v.body;
    MVA.split = v.split ? 1 : 0;
    if (!quiet) {
      lsSet('bone', v.on.bone ? '1' : '0');
      lsSet('joint', v.on.joint ? '1' : '0');
      lsSet('muscle', v.on.muscle ? '1' : '0');
      lsSet('body', v.body);
      lsSet('split', MVA.split ? '1' : '0');
      lsSet('view', k);
    }
    applySkin();
    if (MVA.ready) { solve(); applyClip(); draw(); }
  };

  /* ── the midline, as a clipping plane ────────────────────────────────── */
  var CLIP = { head: null, c: null };
  function ensureClip() {
    if (!CLIP.head && typeof THREE.Plane === 'function') {
      CLIP.head = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
      CLIP.c = new THREE.Vector3();
    }
    /* off by default in three, and a material's clippingPlanes is ignored without it — the
       split would silently do nothing */
    if (MVST3.renderer) MVST3.renderer.localClippingEnabled = true;
  }
  /* THE HEAD'S OWN MIDLINE, AND NOTHING ELSE'S. The first cut put this plane on the HIPS and
     used it for the whole body — the defect the operator reported, because a pelvis cannot say
     where a raised arm's midline is. Only the skull keeps a plane, built from the HEAD bone, so
     the cut runs down the face through any turn of the neck. */
  function updateClip() {
    var A = MVA.atlas;
    if (!CLIP.head || !A) return;
    var b = A.bones.Head, f = boneAxes(A, 'Head', 0);
    if (!b || !f) return;
    CLIP.c.setFromMatrixPosition(b.matrixWorld);
    /* keep the skeleton side: away from whichever half the muscle is on */
    var keepLeft = (MVA.splitSide ? SIDE_L : SIDE_R) === SIDE_L;
    CLIP.head.normal.copy(f.lat);
    if (!keepLeft) CLIP.head.normal.negate();
    CLIP.head.constant = -CLIP.head.normal.dot(CLIP.c);
  }
  function clipFor() {
    if (!MVA.split || !CLIP.head) return null;
    return [CLIP.head];
  }
  /* swapping clippingPlanes between null and an array changes the shader, so the material has
     to be recompiled — but only on the frames it changes */
  function setClip(m, planes) {
    if (!m) return;
    var had = !!(m.clippingPlanes && m.clippingPlanes.length);
    var want = !!(planes && planes.length);
    if (had !== want) m.needsUpdate = true;
    m.clippingPlanes = want ? planes : null;
  }
  function applyClip() {
    ensureClip();
    if (!GFX) return;
    /* the skull's own copy of the joints is the only clipped mesh left */
    if (GFX.jointH) setClip(GFX.jointH.material, clipFor('head'));
  }

  /* ── the preview beside each row ─────────────────────────────────────────
     Every row is rendered from THIS actor in THIS pose: the menu answers "what will that look
     like", and a canned thumbnail of somebody else's body does not. RENDERED TO A TARGET, NOT
     SCRAPED OFF THE CANVAS — renderer.domElement.toDataURL() only works while the drawing
     buffer has not been swapped, and this context has no preserveDrawingBuffer, so it is
     undefined behaviour that happens to work until it does not. An offscreen WebGLRenderTarget
     is deterministic and never touches the operator's frame. THE COLOUR HAS TO BE PUT BACK BY
     HAND: in r147 `outputEncoding` is applied only to the default framebuffer, a render target
     is always written LINEAR, and bytes read straight into an <img> come out muddy and dark.
     The table below is the sRGB transfer, once per channel VALUE, not per pixel. */
  var TH = { rt: null, cv: null, ctx: null, cam: null, buf: null,
             cache: {}, key: '', lut: null };
  var TH_W = 150, TH_H = 200;

  function srgbLut() {
    if (TH.lut) return TH.lut;
    var t = new Uint8Array(256), i, c;
    for (i = 0; i < 256; i++) {
      c = i / 255;
      c = c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
      t[i] = Math.max(0, Math.min(255, Math.round(c * 255)));
    }
    TH.lut = t;
    return t;
  }

  function thumbKey() {
    var A = MVA.atlas;
    return A ? (A.vert || 0) + 'x' + A.stature.toFixed(4) : '';
  }

  function buildThumbs() {
    var A = MVA.atlas, R = MVST3 && MVST3.renderer;
    if (!A || !R || !MVA.ready) return false;
    var key = thumbKey();
    if (TH.key === key && TH.cache[VIEWS[VIEWS.length - 1].k]) return true;
    var t0 = (window.performance && performance.now) ? performance.now() : 0;
    try {
      if (!TH.rt) {
        TH.rt = new THREE.WebGLRenderTarget(TH_W, TH_H, { samples: 4 });
        TH.cv = document.createElement('canvas');
        TH.cv.width = TH_W; TH.cv.height = TH_H;
        TH.ctx = TH.cv.getContext('2d');
        TH.buf = new Uint8Array(TH_W * TH_H * 4);
        TH.cam = new THREE.PerspectiveCamera(30, TH_W / TH_H, 0.01, 60);
      }
      /* straight on, the way the reference plates are drawn, and far enough back to hold the
         whole figure however the clip has posed it */
      var hips = new THREE.Vector3().setFromMatrixPosition(A.bones.Hips.matrixWorld);
      var ctr = hips.clone().addScaledVector(A.up, 0.02 * A.stature);
      var dir = A.ant.clone().multiplyScalar(0.97).addScaledVector(A.lat, 0.24).normalize();
      var d = (A.stature * 0.60) / Math.tan(TH.cam.fov * Math.PI / 360);
      TH.cam.position.copy(ctr).addScaledVector(dir, d).addScaledVector(A.up, 0.03 * A.stature);
      TH.cam.lookAt(ctr);
      TH.cam.updateMatrixWorld(true);

      var keep = { bone: MVA.on.bone, joint: MVA.on.joint, muscle: MVA.on.muscle,
                   body: MVA.body, split: MVA.split };
      var lut = srgbLut(), img = TH.ctx.createImageData(TH_W, TH_H);
      var prevTarget = R.getRenderTarget();
      for (var i = 0; i < VIEWS.length; i++) {
        var v = VIEWS[i];
        MVA.on.bone = v.on.bone; MVA.on.joint = v.on.joint; MVA.on.muscle = v.on.muscle;
        MVA.body = v.body; MVA.split = v.split ? 1 : 0;
        applySkin();
        if (MVR.inner) MVR.inner.updateMatrixWorld(true);
        solve(); updateClip(); applyClip(); draw();
        R.setRenderTarget(TH.rt);
        R.render(MVST3.scene, TH.cam);
        R.readRenderTargetPixels(TH.rt, 0, 0, TH_W, TH_H, TH.buf);
        /* GL hands rows back bottom-up; ImageData is top-down */
        for (var y = 0; y < TH_H; y++) {
          var s = (TH_H - 1 - y) * TH_W * 4, dst = y * TH_W * 4;
          for (var x = 0; x < TH_W * 4; x += 4) {
            img.data[dst + x] = lut[TH.buf[s + x]];
            img.data[dst + x + 1] = lut[TH.buf[s + x + 1]];
            img.data[dst + x + 2] = lut[TH.buf[s + x + 2]];
            img.data[dst + x + 3] = TH.buf[s + x + 3];
          }
        }
        TH.ctx.putImageData(img, 0, 0);
        TH.cache[v.k] = TH.cv.toDataURL('image/png');
      }
      R.setRenderTarget(prevTarget);
      MVA.on.bone = keep.bone; MVA.on.joint = keep.joint; MVA.on.muscle = keep.muscle;
      MVA.body = keep.body; MVA.split = keep.split;
      applySkin();
      if (MVR.inner) MVR.inner.updateMatrixWorld(true);
      solve(); updateClip(); applyClip(); draw();
      TH.key = key;
      MVA.thumbMs = ((window.performance && performance.now) ? performance.now() : 0) - t0;
      return true;
    } catch (e) {
      /* a preview is a convenience; losing it must not cost the menu */
      MVA.thumbErr = String(e && e.message || e);
      try { R.setRenderTarget(null); } catch (e2) {}
      return false;
    }
  }
  MVA.__thumbs = function () { return TH.cache; };

  /* ── the switches ────────────────────────────────────────────────────────
     Three layers, three buttons, and one slider for how much of the actor is left in front of
     them. Rendered into movement_rig.js's TRANSPORT section and re-wired with it, because the
     panel is redrawn wholesale. */
  MVA.controls = function () {
    function b(id, lab, on, tip) {
      return '<button id="mva-' + id + '" class="' + (on ? 'on' : '')
           + '" title="' + tip + '">' + lab + '</button>';
    }
    var c = MVA.counts;
    /* THE ICON FIRST. It is the control that drives the other four, so it reads above them; the
       three switches stay, because "nearly that view but without the joints" is a real thing to
       want and the icon falls back to Custom rather than pretending otherwise. */
    var cur = matchView(), curV = viewByKey(cur);
    var h = '<div class="mvr-row mva-viewrow">'
      + '<button id="mva-view" class="mva-viewbtn" type="button" aria-haspopup="true"'
      + ' title="Change what is drawn of the body — skin, skeleton, muscles, joints, or the half-and-half plate">'
      + VIEW_ICON
      + '<span id="mva-viewname">' + (curV ? curV.n : 'Custom') + '</span>'
      + '<i class="mva-caret">▾</i></button></div>'
      + '<div id="mva-viewmenu" class="mva-menu" hidden>'
      + VIEWS.map(function (v) {
          return '<button type="button" class="mva-vi' + (v.k === cur ? ' on' : '')
            + '" data-k="' + v.k + '"><b>' + v.n + '</b><em>' + v.d + '</em></button>';
        }).join('')
      + '</div>';
    h += '<div class="mvr-row">'
      + b('bone', 'Bones', MVA.on.bone,
          'The skeleton: the CC0 Blender Studio anatomical skeleton (135 bones \u2014 skull, 24 vertebrae, sacrum, ribcage, both girdles, every phalanx), fitted bone by bone to this actor\u2019s rig')
      + b('joint', 'Joints', MVA.on.joint,
          'Every articulation, and the chain that links them — the stick figure, with the joints the 31-channel rig does not carry')
      + b('muscle', 'Muscles', MVA.on.muscle,
          'The muscular system as an \u00e9corch\u00e9: the reference plate\u2019s muscles painted onto this body\u2019s own surface (klein RefControl, Apache-2.0), 1.5 mm under the skin, cut down the midline against the skeleton')
      + '</div>';
    h += '<div class="mvr-row"><label>skin</label>'
      + '<input id="mva-skin" type="range" min="0" max="1" step="0.01" value="' + MVA.skin + '">'
      + '<span class="mvr-note" id="mva-skinv">' + Math.round(MVA.skin * 100) + '%</span></div>';
    h += '<div class="mvr-row"><label>body</label>'
      + ['solid', 'mesh', 'off'].map(function (k) {
          return '<button id="mva-body-' + k + '" class="' + (MVA.body === k ? 'on' : '')
               + '" title="' + { solid: 'The actor as a translucent surface',
                                 mesh: 'The actor as its own wireframe \u2014 still a body, nothing hidden behind it',
                                 off: 'The actor out of the way, skeleton only' }[k]
               + '">' + k + '</button>';
        }).join('') + '</div>';
    if (!MVA.ready) {
      h += '<div class="mvr-note' + (MVA.note ? ' err' : '') + '">'
         + (MVA.note ? MVA.note : 'anatomy not solved for this subject') + '</div>';
      return h;
    }
    var skm = (MVR.meta && MVR.meta.skeleton) || null;
    h += '<div class="mvr-note">' + c.joint + ' joints &middot; '
      + (skm ? 'skeleton of ' + (skm.pieces || 0) + ' bones ('
               + (skm.vertices || 0) + ' vertices) fitted to the rig'
             : 'no skeleton mesh in this actor')
      + (MVA.ecName ? ' &middot; \u00e9corch\u00e9 ' + MVA.ecName + ' ' + MVA.ecSize : '')
      + (MVA.ms ? ' &mdash; measured off ' + (MVA.atlas.vert || 0) + ' vertices in '
                  + MVA.ms.toFixed(0) + ' ms' : '') + '</div>';
    if (MVA.ecNote)
      h += '<div class="mvr-note err">Muscles: ' + MVA.ecNote + '</div>';
    h += '<div class="mvr-note">Fingers and toes ride the wrist and the ankle: no clip in the '
      + 'library carries digit channels, because cmu_mb has none. Everything above them is '
      + 'driven by the clip, the ribcage and the column included.</div>';
    if (MVA.atlas && MVA.atlas.ankleIn === false)
      h += '<div class="mvr-note err">the rig does not sit inside its own mesh — the ankle '
        + 'joint is outside the foot. The overlay follows the rig, so it is offset with it; '
        + 'that is a build defect, not a drawing one.</div>';
    return h;
  };

  /* the floating thumbnail. It lives in .cs-mainwrap beside the panel rather than inside it, so
     it is positioned the same way panelPlace() positions the panel itself — offsets within the
     wrap, never client rects, which the page's html{zoom:.67} would otherwise have to be undone
     from. */
  function prevEl() {
    var el = document.getElementById('mva-prev');
    if (el) return el;
    var wrap = document.querySelector('#view-movement .cs-mainwrap');
    if (!wrap) return null;
    el = document.createElement('div');
    el.id = 'mva-prev';
    el.innerHTML = '<img alt=""><div></div>';
    wrap.appendChild(el);
    return el;
  }
  function prevShow(v, row) {
    var el = prevEl(), panel = document.getElementById('mvr-panel');
    if (!el || !panel) return;
    var url = TH.cache[v.k];
    el.querySelector('img').src = url || '';
    el.querySelector('div').textContent = url ? v.d
      : (MVA.thumbErr ? 'preview unavailable — ' + MVA.thumbErr : v.d);
    /* to the LEFT of the panel, and vertically level with the row it belongs to, clamped so a
       row near the bottom does not push it off the stage */
    var w = TH_W + 14;
    el.style.left = Math.max(4, panel.offsetLeft - w - 10) + 'px';
    var want = panel.offsetTop + row.offsetTop - 6;
    var maxTop = panel.offsetTop + panel.offsetHeight - (TH_H + 40);
    el.style.top = Math.max(panel.offsetTop, Math.min(want, Math.max(0, maxTop))) + 'px';
    el.classList.add('on');
  }
  function prevHide() {
    var el = document.getElementById('mva-prev');
    if (el) el.classList.remove('on');
  }
  function menuOpen(on) {
    var m = document.getElementById('mva-viewmenu');
    if (!m) return;
    if (on) {
      /* built on first open, not at load: six solves and six renders is not work to do for a
         menu nobody has asked for yet */
      buildThumbs();
      m.hidden = false;
    } else { m.hidden = true; prevHide(); }
    var btn = document.getElementById('mva-view');
    if (btn) btn.classList.toggle('on', !!on);
  }

  MVA.wire = function () {
    injectViewCss();
    ensureClip();
    var vb = document.getElementById('mva-view');
    if (vb) vb.onclick = function (e) {
      e.stopPropagation();
      var m = document.getElementById('mva-viewmenu');
      menuOpen(!!(m && m.hidden));
    };
    Array.prototype.forEach.call(
      document.querySelectorAll('#mva-viewmenu .mva-vi'), function (el) {
        var v = viewByKey(el.getAttribute('data-k'));
        if (!v) return;
        el.onmouseenter = function () { prevShow(v, el); };
        el.onfocus = function () { prevShow(v, el); };
        el.onmouseleave = prevHide;
        el.onclick = function (e) {
          e.stopPropagation();
          MVA.applyView(v.k);
          menuOpen(false);
          if (typeof MVR.panelRender === 'function') MVR.panelRender();
        };
      });
    if (!MVA.__docClose) {
      MVA.__docClose = true;
      document.addEventListener('click', function () { menuOpen(false); });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') menuOpen(false);
      });
    }
    ['bone', 'joint', 'muscle'].forEach(function (k) {
      var el = document.getElementById('mva-' + k);
      if (!el) return;
      el.onclick = function () {
        MVA.on[k] = !MVA.on[k];
        lsSet(k, MVA.on[k] ? '1' : '0');
        applySkin();
        if (MVA.ready) { solve(); draw(); }
        if (typeof MVR.panelRender === 'function') MVR.panelRender();
      };
    });
    ['solid', 'mesh', 'off'].forEach(function (k) {
      var el = document.getElementById('mva-body-' + k);
      if (!el) return;
      el.onclick = function () {
        MVA.body = k; lsSet('body', k);
        applySkin();
        if (typeof MVR.panelRender === 'function') MVR.panelRender();
      };
    });
    var sk = document.getElementById('mva-skin');
    if (sk) sk.oninput = function () {
      MVA.skin = Math.min(1, Math.max(0, parseFloat(sk.value) || 0));
      lsSet('skin', MVA.skin);
      var lab = document.getElementById('mva-skinv');
      if (lab) lab.textContent = Math.round(MVA.skin * 100) + '%';
      applySkin();
    };
  };

  /* ── what the proof reads ────────────────────────────────────────────────
     tools/studio_verify/check_movement_anatomy.py asserts against the solved arrays, not a
     screenshot: five separable ray tips per hand at the measured hand length, 26 column levels
     ordered coccyx to C1, nothing clipped by its instance buffer. These hand the live pools
     out, sliced to C. */
  MVA.__joints = function () { return P.joint.slice(0, C.joint); };
  MVA.__links = function () { return P.link.slice(0, C.link); };
  MVA.__levels = function () { return _lv.slice(); };
  /* the five ray tips of each hand, by name, with the wrist and the distal axis they were
     measured along — a checker asking "does this hand have fingers" should not have to guess
     which solved points are fingertips */
  MVA.__tips = function () { return AN.tip; };
  /* the cranium as solved: its centre, its three radii, and the head box they were taken from —
     so a proof can ask whether the skull fits the head rather than guessing which points are
     skull */
  MVA.__skull = function () { return AN.skull; };
  MVA.__gfx = function () { return GFX; };
  /* the midline the half-and-half views cut on, so a check can ask whether it actually rides
     the body rather than trusting the picture */
  MVA.__clip = function () { return MVA.split ? CLIP.head : null; };

  window.SX = window.SX || {};
  (window.SX.ready = window.SX.ready || []).push('movement_rig_anatomy');
})();
