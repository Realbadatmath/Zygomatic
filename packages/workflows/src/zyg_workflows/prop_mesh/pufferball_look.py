# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pufferball_look.py — the CANON LOOK layer for the Pufferball (2026-08-27).

WHAT THIS IS. Everything that makes the procedural creature in pufferball.py render
like its canon anchors (lora-datasets/creatures/d0e44ab002ad/contact_sheet/anchors/
anchor_full.png + anchor_side.png): the plush hair groom and hair shader, the eye
shader (amber iris, pupil, glints, socket ring), the face-plate/lip/teeth materials
and micro-texture, the re-shaped arms/feet/legs/tail tube, and the lighting rig,
backdrop, floor and lens per view. pufferball.py stays the geometry-and-invariants
module; this file is the look-dev on top of it.

HOW IT IS APPLIED. The same OVERLAY CONTRACT the fit harness (pbfit) used:
    PARAMS                           merged into PB.P before build
    pre_build(PB)                    monkeypatches PB.build_* / PB._hair
    post_build(scene, result, PB)    edits objects/materials/particles after build
    lighting(scene, centre, size, aim), world(scene), camera(cam, cam_data, view_id)
pufferball_sheet.py applies these when run with `--look canon`.

PROVENANCE. Three look-dev convergence runs against the anchors through the pbfit
harness — 68 agents in all. Phase 1 (25 agents) diverged on artefact metrics; phase 2
(31 agents, repaired harness, regression-guarded merge) produced round 4, ported
2026-08-27; phase 3 (12 agents, two coupled clusters FACE + COAT on that production
file) produced this file: its round 2, which the critic certified with ZERO major
differences from the anchors ("close"). The orchestrator's DINO floor wrongly reverted
it (DINO fell 0.02 while every view read closer by eye — the critic said so); it was
ported by hand on 2026-08-28 after a side-by-side with rounds 1 and 3.

The file is CUMULATIVE — later sections shadow earlier names on purpose, and every
section carries the measurements that justified it. Do not tidy it into "clean" code
without re-rendering against the anchors; the numbers are the spec. The previous
production file is kept as docs/look_history/pufferball_look.p2r4.py.

REMAINING (critic, phase 3 round 2 — all minor): mouth aperture smaller than the
anchor's open rounded mouth; pupils a little small off-profile; belly gold slightly
dull; tail bands lighter and the tail thinner; feet a row of spheres rather than two
three-toed pads; no chin V; plate reads flat plastic in close-up; white fur neutral
where the anchor's is mint-cream; arms saturated glossy teal vs matte light mint.
Harness note: side/close eye_frac now read high because the finder counts the tan
socket ring as iris — an artefact of the metric, not a defect of the eye.


r4_merge — round-4 merge on r3_merge: fur4 (head coverage, cap+mound fur, eye repel forces, TUFT4 tuft shape, mint
fur colour) + skin4 (solved teal face albedo, dew droplets, solved lips) + form4 (rounder lifted body, S-tail with
constricted bands, oblate sunk eyes under a hooded bezel, camera-aimed gaze). Sections are verbatim; the R4MERGE
section at the end resolves the combination conflicts (see its header).

Base docstring follows.
r3_merge — round-3 merge on r2_merge: form3 (egg body, low stance, pad+toe feet, hanging arms, J tail
with notch + tapered tip) + fur3 (60 mm undercoat + 2600x18 feathered tufts, face-repel force, beard wind,
7 ring tail bands + tube material, paler mint hair colour) + eyes3 (eye_r 0.053 / sep 0.074, EYE_PROUD 0.70,
flush ring bezel, orbital mound, re-laid iris bands, wet coat, iris emission) + skin3 (face_material: z-graded
sea-foam->teal albedo, coat sheen, mint SSS, emissive gold glitter, black cavity) + light3 (mint-white key
split general/fur, warm amber belly accent, eye-only white light, dim cyan rims, floor->backdrop blend).
R3MERGE marks merge-only edits; per-dimension edits keep their R3FORM/R3FUR/R3EYES/R3SKIN/R3LIGHT tags.

Composition order (one merged param dict `_P` feeds every dimension):
  PARAMS      form -> fur -> eyes -> skin, then the R2/R3 fur dict (later wins)
  pre_build   form (build_tail / build_arms / build_feet_r3 / build_legs_r3) then fur (PB._hair -> dispatcher)
  post_build  fur mat -> eyes_post -> skin_post (face_material) -> seat_eyes (ring + mound; copies pb_skin_face)
              -> _tail_post (form tip fade) -> _crown_len -> _fur3_post (rings, undercoat fur_len)
              -> light_post (bounds, bokeh, ground blend)  [light LAST: it measures the finished bounds]
  lighting / world / camera   from light3 (module-level LIGHTS.clear()/update in the R3 LIGHT section)

Conflicts resolved (see the report): EYE_HALO fur's; FUR_LEN_MIN + fringe aim fur's (skin untouched them);
IRIS_EMIT lowered because light3 adds an eye-only white light; face albedo kept at skin3's values under light3's rig.
"""

import math
import bpy
from mathutils import Vector
import random as _random7
import bmesh as _bmesh7
from mathutils import Quaternion as _Quat7, Matrix as _Mat7
import time as _time8
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# PARAMS
# ═════════════════════════════════════════════════════════════════════════════
FORM_PARAMS = {
    # R3FORM proportions. Measured on the anchors the FURRED ball is 650x715 px in front (w/h 0.91) and
    # 560x560 in profile (1.0); r2's furred ball was 678x425 (1.60) and 500x400 (1.25) — the silhouette
    # aspect only matched because a squat ball + 22% legs + a high tail tip added up to the same box.
    # The anchor fur is ~0.07-0.09 m all round, so its CORE is an upright egg (rz/rx ~1.2): "almost as
    # wide as it is tall" means slightly TALLER than wide, not wider. rz/rx here 1.2; the remaining
    # squatness is the fur's directional asymmetry (0.088 sideways vs 0.037 up / 0.027 down), the fur
    # dimension's lever (CROWN/UNDER length minima + wind droop), not a body radius.
    'body_rx': 0.138,
    'body_ry': 0.125,
    'body_rz': 0.175,  # run3: 1.27 (run2 1.20 gave a furred front ball of 1.18 w/h; the anchor's is 0.91)
    # R3FORM: the ball sits LOW. Measured on the anchors the fur hem clears the floor by ~9% of the
    # furred ball height (front 60/715 px, side 55/560); r2 (lift 0.222) showed 97 px of leg+foot under
    # a 435 px ball = 22%. lift = hem(0.031) + belly-fur droop below the core (0.013) + body_rz.
    'body_lift': 0.205,  # run4 (run3 showed 10.7% of feet)   # run3: the alpha sees only ~18 mm of belly fur below the core, so run2 showed 12% of feet; 8-9% wants the core bottom at 0.035
    'leg_r0': 0.030,
    'leg_r1': 0.024,
    # R3FORM feet: a flat pad + three separate toe capsules with bulbous tips (r2's 3 toes at r 0.019 in a
    # +-26 deg fan overlapped into one mitten). Anchor front: foot ~0.20 furred-ball-widths wide (~95 mm),
    # feet centred ~0.19 m apart; side: heel-to-toe ~90 mm, toes reach ~70 mm in front of the ball centre.
    'foot_r': 0.040,
    'foot_sep': 0.085,
    'foot_fwd': -0.030,
    'toe_r': 0.015,
    'toe_len': 0.032,
    'foot_len': 0.030,
    'foot_h': 0.014,
    'toe_fan': 24.0,
    'toe_gap': 0.027,
    # r2: arms a little further out / less vertical so the hands reach the fur edge like the anchor
    'arm_sh': (1.00, -0.55, -0.10),
    'arm_len': 0.105,
    'arm_r': 0.030,
    'arm_drop': 68.0,
    'arm_fwd': 5.0,
    # R3FORM arms: anchor forearms HANG at the fur edge (hands at 0.95-1.07 half-widths, ~0.9 of the ball
    # height down). run4's comment swallowed arm_r/drop/fwd (fell back to 58 deg / 18 deg fwd = arms held OUT).
    'finger_r': 0.012,
    'finger_len': 0.026,
    # r2 TAIL: traced off anchor_side (column ~0.38 ball-heights behind the rear fur edge, nearly vertical,
    # bowing toward the body mid-way, tip flicking back-up) and anchor_full (column entirely BESIDE the
    # ball on the creature's right). Column at (x -0.31, y 0.36); lower arm leaves the lower back-right;
    # tip at lift+0.225 = ~50 mm above the fur crown. Higher tips were simulated: every 30 mm of tip
    # costs ~5% on BOTH aspects, and the front anchor wants the tip AT the crown while the side anchor
    # wants it 0.24 ball-heights above -- irreconcilable for a rigid tail at equal elevations, so 50 mm
    # is the split that keeps both aspects inside tolerance.
    # R3FORM tail path (x, y, z-rel-lift, metres). Read off anchor_side (creature faces right there; +Y is
    # behind here): the tail leaves the LOWER back going backward with a shallow dip (a J), turns up into a
    # thick column ~0.3 m behind the centre, leans BACK as it rises (tip ~0.06 further back than the
    # column) and ends in a point ~0.16 h above the crown. anchor_full puts the column beside the ball on
    # the creature's right (-X), centre ~1.24 furred half-widths out, inner edge touching the fur.
    # The two anchors disagree on tip height by ~0.18 h (front: tip AT the crown; side: 0.22 h above);
    # this path favours the side anchor (the brief says raise tail_above) with the tip at +0.27.
    # run2: column 0.33 out / 0.35 back (anchor_side: column centre 0.79 ball-widths behind the centre,
    # front edge 0.06-0.11 m clear of the ball's rear fur at mid-height -> the NOTCH; anchor_full: column
    # centre ~0.17 ball-widths beyond the fur edge). Tip +0.285 over lift = ~0.09 above the crown.
    # run3: column 15 mm further back (run2 notch 35 mm vs anchor 55-110), tip +15 mm (side tail_above -33%)
    # run4, in ball-width units vs the anchors: tip 0.26 bw above the 55% row (anchor 0.31) -> +20 mm;
    # column rear edge 0.98 bw behind the centre (anchor 1.01) and front outer edge 1.59 half-widths
    # (anchor 1.65) -> 30 mm back, 17 mm out; the J-base underside sat 35 mm over the hem (anchor ~80)
    # and filled the concavity under the tail (side solidity +23%) -> raised 25 mm.
    # run7: anchor_full's column is a "(" — its outer edge bows OUT to 1.65 half-widths at the lower-mid
    # column and comes back to ~1.45 near the tip; run4's straight column sat at 1.55 all the way.
    # R3MERGE run4: top three knots lowered 15/30/30 mm. form3 favoured anchor_side's tip (0.31 bw above the crown);
    # in the merge that left BOTH aspects at -8%/-7% and front tail_above +126% (anchor_full's tip is ~0.03 bw above
    # the crown). form3's own estimate: ~5% of aspect per 30 mm of tip. Split between the two anchors.
    'tail_knots': [
        (0.000, 0.070, -0.040),
        (-0.100, 0.215, -0.060),
        (-0.240, 0.325, -0.055),
        (-0.345, 0.380, 0.010),
        (-0.372, 0.395, 0.100),
        (-0.362, 0.400, 0.165),
        (-0.340, 0.415, 0.230),
        (-0.320, 0.435, 0.290),
    ],
    # R3FORM profile: fattest in the lower half (anchor column ~0.11 m visible dia at mid-height, fatter
    # where it merges with the ball), then a REAL taper over the top 40% to a point (r2 kept 0.044 to
    # s=0.72 and ended in a tuft: the critic's bottle-brush).
    # run2: fattest at MID-column (anchor_side column r_vis 0.055 low -> 0.068 mid -> 0.048 -> 0.028 near
    # the tip; the fur adds ~0.012 to the core), slimmer J-base so it stops blobbing into the ball.
    'tail_profile': [
        (0.00, 0.038),
        (0.12, 0.046),
        (0.30, 0.052),
        (0.50, 0.062),
        (0.65, 0.054),
        (0.78, 0.040),
        (0.88, 0.026),
        (0.95, 0.016),
        (1.0, 0.010),
    ],  # run7: mid +4 mm (anchor_full column 0.31-0.35 bw at the bulge)   # run3: rounded tip (run2's 4 mm read as a spike)
    'tail_cap': 0.12,
    'tail_rings': 160,
    'tail_sides': 28,
    'tail_bands': 6.0,
    'tail_band_frac': 0.36,
    'tail_exit_s': 0.20,
    'tail_hair_len': 0.034,
    'tail_hair_count': 900,
    'tail_hair_child': 24,
}
FUR_PARAMS = {
    'hair_len': 0.068,
    'hair_count': 1000,
    'hair_child': 64,
    'hair_thick': 0.00055,
}
EYES_PARAMS = {
    # R3EYES: the harness's anchor eye_frac 0.303 is (396 px fur blob + 145 px eye)/2/892 — the honest
    # anchor eye is 145/892 = 0.16 of the silhouette and the r2 sphere already measured 134/796 = 0.17
    # per eye (r1_eyes/honest_eye.py). So the eye grows only +10% (the cup hid 18% of it; with a flush
    # ring the whole disc shows), the pupil goes to 0.58 of the visible disc (anchor 67/122 .. 85/145),
    # and the pair opens to the anchor's centre spacing (253/892 = 0.284 W).
    'eye_r': 0.053,
    'eye_sep': 0.074,
    'pupil_r': 0.027,
    'eye_out': 0.012,
    'glint_r': 0.010,
    'glint_out': 0.002,
}
SKIN_PARAMS = {
    # R3MERGE run3: face_r 0.098 -> 0.130. At 0.098 the cap's half-width at eye height was 0.093 while the 53 mm eyes at
    # sep 0.074 reach x 0.127, so each socket (orbital mound) hung past the cap, backed only by flank fur = goggles at 45 deg
    # (fur caveat c, eyes caveat C). Anchor mask spans ~0.7 furred-ball-widths and wraps past both eyes. FACE_YS 1.6 keeps
    # the cap's rim at the body (cy = -0.042 vs body -0.032 at x 0.130) with the pole at -0.171 (was -0.165).
    'face_r': 0.130,
    'face_z': 0.038,
    'face_bulge': 0.020,  # r2: mask pole at y=-0.158, close to the fur front (-0.18) so face + eyes are not recessed behind the cheek coat in profile
}
PARAMS = {}
for _d in (FORM_PARAMS, FUR_PARAMS, EYES_PARAMS, SKIN_PARAMS):
    PARAMS.update(_d)

_P = {}  # PB.P + PARAMS, filled in pre_build
_ORIG = {}  # original PB callables


def _ob(name):
    return bpy.data.objects.get(name)


# ═════════════════════════════════════════════════════════════════════════════
# FORM — swept-tube tail + forward arms (r1_form/form.py)
# ═════════════════════════════════════════════════════════════════════════════
def _catmull_rom(knots, per_seg=48):
    K = [Vector(k) for k in knots]
    K = [K[0]] + K + [K[-1]]
    pts = []
    for i in range(1, len(K) - 2):
        p0, p1, p2, p3 = K[i - 1], K[i], K[i + 1], K[i + 2]
        for j in range(per_seg):
            t = j / float(per_seg)
            pts.append(
                0.5
                * (
                    (2 * p1)
                    + (-p0 + p2) * t
                    + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t
                )
            )
    pts.append(K[-2])
    return pts


def _resample(pts, n):
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + (b - a).length)
    L = cum[-1]
    out = []
    k = 0
    for i in range(n):
        s = L * i / float(n - 1)
        while k < len(cum) - 2 and cum[k + 1] < s:
            k += 1
        seg = cum[k + 1] - cum[k]
        f = 0.0 if seg < 1e-9 else (s - cum[k]) / seg
        out.append(pts[k].lerp(pts[k + 1], f))
    return out, L


def _radius(s, p):
    prof = p['tail_profile']
    cap = p['tail_cap']
    r = prof[-1][1]
    for (s0, r0), (s1, r1) in zip(prof, prof[1:]):
        if s0 <= s <= s1:
            r = r0 + (r1 - r0) * (s - s0) / max(s1 - s0, 1e-9)
            break
    if s > 1.0 - cap:
        q = (s - (1.0 - cap)) / cap
        r *= math.sqrt(max(0.0, 1.0 - q * q))
    return r


def _phase(s, u, p):
    tv = (s - p['tail_exit_s']) / (1.0 - p['tail_exit_s'])
    return (tv * p['tail_bands'] - u) % 1.0


def _is_band(s, u, p):
    if s < p['tail_exit_s'] + 0.02 or s > 0.94:
        return False
    return _phase(s, u, p) < p['tail_band_frac']


def _density(s, u, p):
    if s < p['tail_exit_s'] + 0.02 or s > 0.94:
        return 1.0
    ph = _phase(s, u, p)
    bf = p['tail_band_frac']
    if ph < bf:
        return 0.0
    d = min(ph - bf, 1.0 - ph)
    return max(0.0, min(1.0, d / 0.06))


def build_tail_tube(mats, scene, p, PB):
    n, S = p['tail_rings'], p['tail_sides']
    lift = p['body_lift']
    knots = [(x, y, lift + z) for (x, y, z) in p['tail_knots']]
    dense = _catmull_rom(knots)
    C, L = _resample(dense, n)
    T = []
    for i in range(n):
        a = C[max(0, i - 1)]
        b = C[min(n - 1, i + 1)]
        T.append((b - a).normalized())
    N = []
    nrm = T[0].cross(Vector((1, 0, 0)))
    if nrm.length < 1e-3:
        nrm = T[0].cross(Vector((0, 1, 0)))
    nrm.normalize()
    for i in range(n):
        nrm = nrm - T[i] * nrm.dot(T[i])
        if nrm.length < 1e-6:
            nrm = T[i].orthogonal()
        nrm.normalize()
        N.append(nrm.copy())
    verts, faces, fmat, uvs = [], [], [], []
    ring_s = []
    verts.append(C[0] - T[0] * _radius(0.0, p) * 0.6)
    n_rings = n - 1
    for i in range(n_rings):
        s = i / float(n - 1)
        ring_s.append(s)
        r = max(_radius(s, p), 0.0015)
        B = T[i].cross(N[i]).normalized()
        for j in range(S):
            th = 2.0 * math.pi * j / S
            verts.append(C[i] + (N[i] * math.cos(th) + B * math.sin(th)) * r)
    verts.append(C[-1] + T[-1] * 0.001)
    tip = len(verts) - 1
    ring0 = 1
    for j in range(S):
        j2 = (j + 1) % S
        faces.append((0, ring0 + j2, ring0 + j))
        fmat.append(0)
        uvs.append(((j + 0.5) / S, 0.0))
    for i in range(n_rings - 1):
        a = ring0 + i * S
        b = a + S
        s = (ring_s[i] + ring_s[i + 1]) * 0.5
        for j in range(S):
            j2 = (j + 1) % S
            faces.append((a + j, b + j, b + j2, a + j2))
            u = (j + 0.5) / S
            fmat.append(1 if _is_band(s, u, p) else 0)
            uvs.append((u, s))
    last = ring0 + (n_rings - 1) * S
    for j in range(S):
        j2 = (j + 1) % S
        faces.append((tip, last + j, last + j2))
        fmat.append(0)
        uvs.append(((j + 0.5) / S, 1.0))
    me = bpy.data.meshes.new('pb_tail_00')
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.validate()
    me.materials.append(mats['fur'])
    me.materials.append(mats['band'])
    for k, poly in enumerate(me.polygons):
        poly.material_index = fmat[k]
        poly.use_smooth = True
    uvl = me.uv_layers.new(name='UVMap')
    for k, poly in enumerate(me.polygons):
        for li in poly.loop_indices:
            uvl.data[li].uv = uvs[k]
    PB._outward(me)
    ob = bpy.data.objects.new('pb_tail_00', me)
    ob.pass_index = PB.IDX['tail']
    scene.collection.objects.link(ob)
    vg_d = ob.vertex_groups.new(name='tail_density')
    vg_l = ob.vertex_groups.new(name='tail_len')
    vg_d.add([0], 1.0, 'REPLACE')
    vg_l.add([0], 1.0, 'REPLACE')
    for i in range(n_rings):
        s = ring_s[i]
        for j in range(S):
            vi = ring0 + i * S + j
            u = j / float(S)
            vg_d.add([vi], _density(s, u, p), 'REPLACE')
            vg_l.add([vi], 0.35 + 0.65 * (1.0 - s), 'REPLACE')
    vg_d.add([tip], 1.0, 'REPLACE')
    vg_l.add([tip], 0.35, 'REPLACE')
    # goes through the merged dispatcher -> _tail_tufts
    ps = PB._hair(
        ob,
        p['tail_hair_len'],
        p['tail_hair_count'],
        p['tail_hair_child'],
        seed=77,
        thick=p['hair_thick'] * 0.8,
        density_group='tail_density',
    )
    ps.vertex_group_length = 'tail_len'
    return [ob]


def build_feet_r3(mats, scene, p, PB):
    """R3FORM: flat pad + three SEPARATE toes with bulbous tips, front-facing (anchor: three
    rounded green bumps per foot, foot short and flat on the ground). Nothing sinks: the toe
    axis sits at z = toe_r so the ring's lowest vert is at +0.05 r."""
    out = []
    pw, pl, ph = p['foot_r'], p['foot_len'], p['foot_h']
    tr, tl, gap = p['toe_r'], p['toe_len'], p['toe_gap']
    fan = math.radians(p['toe_fan'])
    for sx in (-1, 1):
        side = 'l' if sx < 0 else 'r'
        cx, cy = sx * p['foot_sep'], p['foot_fwd']
        out.append(
            PB._sphere(
                'pb_foot_%s' % side, (cx, cy, ph), (pw, pl, ph), scene, mats['foot'], segs=24, rings=12, idx='foot'
            )
        )
        for k in range(3):
            a = fan * (k - 1)
            base = Vector((cx + gap * (k - 1), cy - pl * 0.55, tr))
            d = Vector((math.sin(a) * 0.6, -math.cos(a), 0.0)).normalized()
            tip = base + d * tl
            out.append(
                PB._capsule(
                    'pb_toe_%s%d' % (side, k),
                    base,
                    tip,
                    tr * 0.92,
                    tr * 0.80,
                    scene,
                    mats['foot'],
                    sides=12,
                    idx='foot',
                )
            )
            out.append(
                PB._sphere(
                    'pb_toe_%s%d_tip' % (side, k),
                    tuple(tip),
                    (tr, tr * 1.05, tr * 0.98),
                    scene,
                    mats['foot'],
                    segs=16,
                    rings=10,
                    idx='foot',
                )
            )
    return out


def build_legs_r3(mats, scene, p, PB):
    """R3FORM: stubs from inside the ball to the pad centre (the coat hides all but a sliver)."""
    out = []
    for sx in (-1, 1):
        side = 'l' if sx < 0 else 'r'
        hip = Vector((sx * p['foot_sep'], p['foot_fwd'] * 0.6, p['body_lift'] - p['body_rz'] * 0.55))
        # the capsule's domed end cap reaches 0.85 r1 past the ankle point: keep it above z=0
        ank = Vector((sx * p['foot_sep'], p['foot_fwd'], p['leg_r1'] * 0.90))
        out.append(
            PB._capsule(
                'pb_leg_%s' % side, hip, ank, p['leg_r0'], p['leg_r1'], scene, mats['foot'], sides=14, idx='leg'
            )
        )
    return out


def build_arms_fwd(mats, scene, p, PB):
    out = []
    drop = math.radians(p['arm_drop'])
    fwd = math.radians(p['arm_fwd'])
    sx_, sy_, sz_ = p['arm_sh']
    for sx in (-1, 1):
        side = 'l' if sx < 0 else 'r'
        sh = Vector((sx * p['body_rx'] * sx_, p['body_ry'] * sy_, p['body_lift'] + p['body_rz'] * sz_))
        d = Vector((sx * math.cos(drop) * math.cos(fwd), -math.cos(drop) * math.sin(fwd), -math.sin(drop)))
        wr = sh + d * p['arm_len']
        out.append(
            PB._capsule('pb_arm_%s' % side, sh, wr, p['arm_r'], p['arm_r'] * 0.72, scene, mats['skin'], idx='arm')
        )
        perp = Vector((1.0, 0.0, 0.0))
        for k in range(p['finger_n']):
            off = (k - (p['finger_n'] - 1) / 2.0) * p['finger_r'] * 1.6
            tip = wr + d * p['finger_len'] + perp * off
            out.append(
                PB._capsule(
                    'pb_fing_%s%d' % (side, k),
                    wr + perp * off * 0.5,
                    tip,
                    p['finger_r'],
                    p['finger_r'] * 0.72,
                    scene,
                    mats['skin'],
                    sides=10,
                    idx='arm',
                )
            )
    return out


# ═════════════════════════════════════════════════════════════════════════════
# FUR — tufts + undercoat + hair BSDF (r1_fur/fur_final.py) + tail tufts (merge)
# ═════════════════════════════════════════════════════════════════════════════
UNDERCOAT = {'len': 0.016, 'count': 3000, 'child': 16, 'thick': 0.00035}
HAIR_SHADER = {
    'color': (0.78, 0.95, 0.84),
    'roughness': 0.40,
    'radial': 0.35,
    'coat': 0.30,
    'random_color': 0.05,
    'random_rough': 0.2,
    'diffuse': (0.84, 0.96, 0.88),
    'diffuse_mix': 0.45,
}  # 0.30 in fur; the hair BSDF has no sheen, flank went L154 under light's rig
_HAIR_MAT = {}


def _hair_material():
    if 'm' in _HAIR_MAT:
        return _HAIR_MAT['m']
    H = HAIR_SHADER
    m = bpy.data.materials.new('pb_hair_bsdf')
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    h = nt.nodes.new('ShaderNodeBsdfHairPrincipled')
    try:
        h.model = 'CHIANG'
    except TypeError as _exc:
        _zyg_log.debug('hair BSDF CHIANG model unavailable on this blender build: %s', _exc)
    h.parametrization = 'COLOR'

    def put(name, val):
        if name in h.inputs:
            h.inputs[name].default_value = val

    put('Color', (*H['color'], 1.0))
    put('Roughness', H['roughness'])
    put('Radial Roughness', H['radial'])
    put('Coat', H['coat'])
    put('Random Color', H['random_color'])
    put('Random Roughness', H['random_rough'])
    d = nt.nodes.new('ShaderNodeBsdfDiffuse')
    d.inputs['Color'].default_value = (*H['diffuse'], 1.0)
    mix = nt.nodes.new('ShaderNodeMixShader')
    mix.inputs['Fac'].default_value = H['diffuse_mix']
    nt.links.new(h.outputs[0], mix.inputs[1])
    nt.links.new(d.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    _HAIR_MAT['m'] = m
    return m


def _use_hair_material(ob, s):
    m = _hair_material()
    if m.name not in [x.name for x in ob.data.materials if x]:
        ob.data.materials.append(m)
    s.material = [x.name if x else None for x in ob.data.materials].index(m.name) + 1


def _body_hair(ob, length, count, children, seed, thick, density_group):
    bpy.context.view_layer.objects.active = ob
    ob.modifiers.new('hair', 'PARTICLE_SYSTEM')
    ps = ob.particle_systems[-1]
    ps.name = 'pb_tufts'
    ps.seed = seed
    s = ps.settings
    s.type = 'HAIR'
    s.count = count
    s.hair_length = length
    s.hair_step = 5
    s.use_hair_bspline = True
    s.use_advanced_hair = True
    s.object_align_factor = (0.0, 0.0, 0.0)
    s.factor_random = 0.0
    s.length_random = 0.40
    s.child_type = 'SIMPLE'
    s.child_percent = children
    s.rendered_child_count = children
    s.child_length = 1.0
    s.child_radius = 0.012
    s.child_roundness = 0.6
    s.clump_factor = 0.90
    s.clump_shape = -0.15
    s.use_clump_noise = False
    s.roughness_1 = length * 0.12
    s.roughness_1_size = length * 1.5
    s.roughness_2 = length * 0.015
    s.roughness_2_size = 1.0
    s.roughness_2_threshold = 0.6
    s.roughness_endpoint = 0.0
    s.kink = 'WAVE'
    s.kink_amplitude = length * 0.05
    s.kink_amplitude_clump = 0.5
    s.kink_frequency = 1.0
    s.kink_shape = 0.2
    s.brownian_factor = 0.0
    s.render_type = 'PATH'
    if density_group:
        ps.vertex_group_density = density_group
    s.radius_scale = 1.0
    s.root_radius = thick
    s.tip_radius = thick * 0.30
    _use_hair_material(ob, s)
    return ps


def _undercoat(ob, density_group, seed=7):
    U = UNDERCOAT
    bpy.context.view_layer.objects.active = ob
    ob.modifiers.new('undercoat', 'PARTICLE_SYSTEM')
    ps = ob.particle_systems[-1]
    ps.seed = seed
    ps.name = (
        'pb_tail_under' if ob.name.startswith('pb_tail') else 'pb_undercoat'
    )  # R3FUR: named so _fur3_post can hand it the fur_len group
    s = ps.settings
    s.type = 'HAIR'
    s.count = U['count']
    s.hair_length = U['len']
    s.hair_step = 4
    s.use_hair_bspline = True
    s.use_advanced_hair = True
    s.length_random = 0.4
    s.child_type = 'INTERPOLATED'
    s.child_percent = U['child']
    s.rendered_child_count = U['child']
    s.clump_factor = 0.45
    s.clump_shape = 0.0
    s.roughness_1 = U['len'] * 0.15
    s.roughness_1_size = U['len'] * 1.0
    s.roughness_2 = U['len'] * 0.05
    s.roughness_endpoint = U['len'] * 0.10
    s.brownian_factor = 0.0
    s.render_type = 'PATH'
    if density_group:
        ps.vertex_group_density = density_group
    s.radius_scale = 1.0
    s.root_radius = U['thick']
    s.tip_radius = U['thick'] * 0.3
    _use_hair_material(ob, s)
    return ps


def _tail_tufts(ob, length, count, children, seed, thick, density_group):
    """Tufts sized for form's swept tube (fur's 30-tufts-per-bead does not scale
    to a 0.6 m tube). SIMPLE children in a 5 mm disc so they stay off the bare
    helical stripes that the density group carves; length taper comes from the
    tube's 'tail_len' group (set by the caller)."""
    bpy.context.view_layer.objects.active = ob
    ob.modifiers.new('hair', 'PARTICLE_SYSTEM')
    ps = ob.particle_systems[-1]
    ps.seed = seed
    s = ps.settings
    s.type = 'HAIR'
    s.count = count
    s.hair_length = length
    s.hair_step = 4
    s.use_hair_bspline = True
    s.use_advanced_hair = True
    s.object_align_factor = (0.0, 0.0, 0.0)
    s.length_random = 0.35
    s.child_type = 'SIMPLE'
    s.child_percent = children
    s.rendered_child_count = children
    s.child_length = 1.0
    s.child_radius = 0.005
    s.child_roundness = 0.6
    s.clump_factor = 0.85
    s.clump_shape = -0.15
    s.roughness_1 = length * 0.12
    s.roughness_1_size = length * 1.5
    s.roughness_2 = length * 0.02
    s.roughness_2_threshold = 0.6
    s.roughness_endpoint = 0.0
    s.kink = 'WAVE'
    s.kink_amplitude = length * 0.05
    s.kink_amplitude_clump = 0.5
    s.kink_frequency = 1.0
    s.kink_shape = 0.2
    s.brownian_factor = 0.0
    s.render_type = 'PATH'
    if density_group:
        ps.vertex_group_density = density_group
    s.radius_scale = 1.0
    s.root_radius = thick * 1.4
    s.tip_radius = thick * 0.4
    _use_hair_material(ob, s)
    return ps


def merged_hair(ob, length, count=1500, children=8, seed=0, thick=0.0018, density_group=None):
    if ob.name.startswith('pb_tail'):
        return _tail_tufts(ob, length, count, children, seed, thick, density_group)
    if density_group and density_group.startswith('face_fringe'):
        # skin's fringe: the stock interpolated system, skin overrides on top
        ps = _ORIG['hair'](ob, length, count, children, seed=seed, thick=thick, density_group=density_group)
        _use_hair_material(ob, ps.settings)
        return ps
    ps = _body_hair(ob, length, count, children, seed, thick, density_group)
    _undercoat(ob, density_group)
    return ps


# ═════════════════════════════════════════════════════════════════════════════
# EYES — painted sclera, pupil, glints (r1_eyes/eyes.py)
# ═════════════════════════════════════════════════════════════════════════════
def _ramp_elems(ramp, stops):
    cr = ramp.color_ramp
    cr.interpolation = 'LINEAR'
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    cr.elements[0].position = stops[0][0]
    cr.elements[0].color = (*stops[0][1], 1.0)
    for pos, rgb in stops[1:]:
        e = cr.elements.new(pos)
        e.color = (*rgb, 1.0)


def _math(nt, op, a=None, b=None, va=None, vb=None):
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    if a is not None:
        nt.links.new(a, n.inputs[0])
    elif va is not None:
        n.inputs[0].default_value = va
    if b is not None:
        nt.links.new(b, n.inputs[1])
    elif vb is not None:
        n.inputs[1].default_value = vb
    return n.outputs[0]


def _u(rho):
    return math.sqrt(max(0.0, 1.0 - rho * rho))


# R3EYES: the sphere now sits 0.62 r proud, so the skin/ring hides everything past rho 0.925.
# The painted tan lid (0.855-0.965) is gone — the bezel is a real flush ring now — and the iris
# runs out to a dark limbal ring at 0.87-0.92. Iris G/B lowered again (R:G ~3.5): the eyes are lit
# by the GREEN top light (0.32,1,0.6), and (0.88,0.375) x that light read a* -5 vs the anchor +20.
BANDS = [
    (0.00, (0.030, 0.014, 0.008)),
    (_u(0.960), (0.030, 0.014, 0.008)),
    (_u(0.930), (0.055, 0.024, 0.010)),  # limbal ring (cap edge at rho 0.954 for EYE_PROUD 0.70)
    (_u(0.890), (0.120, 0.032, 0.008)),
    (
        _u(0.820),
        (0.320, 0.060, 0.010),
    ),  # dark outer iris        (run3: G x0.65 again — run2 rendered R:G 1.2, anchor 1.6)
    (_u(0.730), (0.600, 0.115, 0.016)),
    (_u(0.630), (0.860, 0.190, 0.028)),
    (_u(0.550), (0.950, 0.230, 0.040)),  # bright collar round the pupil (cabochon 0.027/0.053 = rho 0.51)
    (_u(0.515), (0.060, 0.025, 0.010)),
    (_u(0.490), (0.012, 0.007, 0.006)),
    (1.00, (0.012, 0.007, 0.006)),
]
IRIS_MASK = [(_u(0.900), (0, 0, 0)), (_u(0.870), (1, 1, 1)), (_u(0.560), (1, 1, 1)), (_u(0.525), (0, 0, 0))]


IRIS_EMIT = 0.30  # R3MERGE: eyes3 had 0.45 under the green top light; light3 adds a 5 W white eye-only light, so the two would stack (eyes3 caveat F)   # R3EYES run3: emission = base colour x this, iris only


def eye_shader(mat):
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    bsdf = nodes['Principled BSDF']
    tc = nodes.new('ShaderNodeTexCoord')
    nrm = nodes.new('ShaderNodeVectorMath')
    nrm.operation = 'NORMALIZE'
    links.new(tc.outputs['Object'], nrm.inputs[0])
    sep = nodes.new('ShaderNodeSeparateXYZ')
    links.new(nrm.outputs['Vector'], sep.inputs[0])
    nx, ny, nz = sep.outputs['X'], sep.outputs['Y'], sep.outputs['Z']
    u = _math(nt, 'MULTIPLY', a=ny, vb=-1.0)

    ramp = nodes.new('ShaderNodeValToRGB')
    _ramp_elems(ramp, BANDS)
    links.new(u, ramp.inputs['Fac'])
    imask = nodes.new('ShaderNodeValToRGB')
    _ramp_elems(imask, IRIS_MASK)
    links.new(u, imask.inputs['Fac'])

    ang = _math(nt, 'ARCTAN2', a=nz, b=nx)
    stripe = _math(nt, 'SINE', a=_math(nt, 'MULTIPLY', a=ang, vb=56.0))  # R3EYES 48 -> 56 finer striations
    noise = nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 30.0
    noise.inputs['Detail'].default_value = 5.0
    noise.inputs['Roughness'].default_value = 0.6
    links.new(nrm.outputs['Vector'], noise.inputs['Vector'])
    nz_ = _math(nt, 'SUBTRACT', a=noise.outputs['Fac'], vb=0.5)
    mod = _math(
        nt,
        'ADD',
        a=_math(nt, 'MULTIPLY', a=stripe, vb=0.16),  # R3EYES 0.10 -> 0.16
        b=_math(nt, 'MULTIPLY', a=nz_, vb=0.18),
    )
    gain = _math(nt, 'ADD', a=_math(nt, 'MULTIPLY', a=mod, b=imask.outputs['Color']), vb=1.0)

    hood = nodes.new('ShaderNodeMapRange')
    hood.interpolation_type = 'SMOOTHSTEP'
    hood.inputs['From Min'].default_value = 0.30
    hood.inputs['From Max'].default_value = 0.85
    links.new(nz, hood.inputs['Value'])
    hood_g = _math(
        nt, 'SUBTRACT', va=1.0, b=_math(nt, 'MULTIPLY', a=hood.outputs['Result'], vb=0.40)
    )  # R3EYES 0.50 -> 0.40

    total = _math(nt, 'MULTIPLY', a=gain, b=hood_g)
    col = nodes.new('ShaderNodeVectorMath')
    col.operation = 'SCALE'
    links.new(ramp.outputs['Color'], col.inputs[0])
    links.new(total, col.inputs['Scale'])
    links.new(col.outputs['Vector'], bsdf.inputs['Base Color'])
    # R3EYES run3: the eyes sit under the GREEN top light, and no albedo turns that into the anchor's bright
    # orange (run2 median (175,145,52) vs anchor (209,131,41)). The anchor iris reads lit from within, so the
    # iris band gets a weak emission of its own colour (masked to the iris so the limbal ring stays dark).
    emis = nodes.new('ShaderNodeVectorMath')
    emis.operation = 'SCALE'
    links.new(col.outputs['Vector'], emis.inputs[0])
    links.new(_math(nt, 'MULTIPLY', a=imask.outputs['Color'], vb=IRIS_EMIT), emis.inputs['Scale'])
    links.new(emis.outputs['Vector'], bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value = 1.0

    bsdf.inputs['Roughness'].default_value = 0.35
    bsdf.inputs['Specular IOR Level'].default_value = 0.5
    # R3EYES: the wet cornea is the coat — full weight over the whole cap (was 0.55 iris / 0.20 rim)
    bsdf.inputs['Coat Weight'].default_value = 1.0
    bsdf.inputs['Coat Roughness'].default_value = 0.03
    bsdf.inputs['Coat IOR'].default_value = 1.40


def eyes_post(scene, result, PB, p):
    mats = result['mats']
    eye_shader(mats['sclera'])
    pup = mats['pupil'].node_tree.nodes['Principled BSDF']
    pup.inputs['Base Color'].default_value = (0.004, 0.003, 0.004, 1.0)
    pup.inputs['Roughness'].default_value = 0.45
    pup.inputs['Specular IOR Level'].default_value = 0.15
    pup.inputs[
        'Coat Weight'
    ].default_value = 1.0  # R3EYES 0.25 -> 1.0, coat rough 0.25 -> 0.03: the anchor pupil is a black mirror
    pup.inputs['Coat Roughness'].default_value = 0.03
    pup.inputs['Coat IOR'].default_value = 1.40
    gl = mats['glint'].node_tree.nodes['Principled BSDF']
    gl.inputs['Emission Color'].default_value = (1.0, 1.0, 1.0, 1.0)
    gl.inputs['Emission Strength'].default_value = 4.0
    gl.inputs['Roughness'].default_value = 0.05
    gd = Vector((-0.34, -0.87, 0.36)).normalized()
    for side in ('l', 'r'):
        eye = _ob('pb_eye_' + side)
        gli = _ob('pb_glint_' + side)
        if eye is None or gli is None:
            continue
        gli.location = Vector(eye.location) + gd * (p['eye_r'] - p['glint_r'] + p['glint_out'])


# ═════════════════════════════════════════════════════════════════════════════
# SKIN — face patch, skin material, fur density, fringe, beak (r1_skin/overlay.py)
# ═════════════════════════════════════════════════════════════════════════════
FACE_ZS = 0.75  # r2: 0.80 -> 0.75; top edge at z_rel 0.112 (eye tops 0.110) so the proud brow step is small and under the crown fur
# MERGE: the face ellipsoid (ry = 0.62 face_r) stood 75 mm proud at its top edge, a bald
# dome no hair could lie over. Scale it FACE_YS in Y about a centre moved back so the
# front pole is unchanged: the patch becomes a shallow cap whose top edge is ~26 mm
# proud. The build-time eye datum (unscaled) is then 17.6 mm in front of the real
# surface at the eye, so eye_out drops 0.034 -> 0.0165 to keep the eye 0.71 r proud.
FACE_YS = 1.6  # R3MERGE run3: 1.3 -> 1.6 with face_r 0.130 (see SKIN_PARAMS)   # r2: 2.0 -> 1.3. ry>r is a PROLATE bullet nose (recession at the eye 43 mm); 1.3 gives a shallow cap (28 mm) -- the top edge stands ~30 mm proud and relies on the crown fur to cover it
# R2SKIN: albedo fitted to the anchor face under the harness light (see r2_skin/_calib.py):
# skin's (0.004,0.095,0.130) had R so low the warm key could not lift the shaded cheek,
# which is why it read as a dark saturated teal ball (shade R/G 0.32 vs anchor 0.56).
SKIN_RGB = (
    0.022,
    0.190,
    0.200,
)  # R3MERGE run3: (0.009,0.125,0.150) was fitted under r2's 16 W green top; under light3's rig the arms rendered (73,122,86) (run1) / (86,138,105) (run2, key 14 W) vs the anchor's pale mint forearms   # arms / fingers (mats['skin'])
FACE_RGB = (
    0.100,
    0.205,
    0.230,
)  # R3SKIN run5: BROW albedo (pale sea-foam). run4 (0.120,0.220,0.240) with the gradient reaching the chin: lit (155,217,199) ok but mid (110,185,163) grey vs anchor (80,173,152) — run3's camera-Facing mix put the rim colour on the top of the dome (grazing to the camera) and the pale one on the jaw: lit unchanged, mid overshot (103,186,162). run2 flat (0.080,0.180,0.215) matched the mean (103,170,150 vs 94,172,149) but not the range: lit 147/214 vs 169/229, shade R 69 vs 41
FACE_CHIN_RGB = (
    0.030,
    0.155,
    0.210,
)  # R3SKIN run5: CHIN albedo (saturated teal) — the anchor is pale at the brow and saturated teal under the beak; the gradient is spatial, not view-dependent
FACE_GRAD_Z = (
    -0.060,
    0.040,
)  # face-LOCAL z (unscaled): chin colour at/below z0, brow colour at/above z1 (mouth -0.048, eyes +0.032). run5: narrowed so the cheeks beside the muzzle stay saturated (anchor band map)
GOLD_RGB = (0.95, 0.62, 0.12)
BEAK_RGB = (0.30, 0.135, 0.050)  # R2SKIN: peachier tan, the anchor upper lip is (215,160,100) not orange
CAVITY_RGB = (
    0.010,
    0.0025,
    0.002,
)  # R3SKIN: near-black (0.028 read as a red-brown pocket, anchor cavity is (40,25,20))  # R2SKIN: dark red-brown (0.045 read as a flat brown pocket in run4)
LOWLIP_R = (0.024, 0.007, 0.0055)  # R2SKIN: pouting lower lip under the opening
LOWLIP_DZ = -0.0115
LOWLIP_DY = 0.0076  # centre behind the bill pole so it stands ~2.5 mm proud of the bill surface there
LOWLIP_RGB = (0.30, 0.10, 0.030)
SKIN_SPEC = (
    0.50  # R2SKIN: only top (mint) + key (warm) are glossy-visible, so spec brightens the lit band the anchor way
)
SKIN_ROUGH = 0.45
SKIN_SSS = 0.25  # R2SKIN: 0.12 -> 0.25
SKIN_SSS_RADIUS = (1.0, 0.65, 0.45)
SKIN_SSS_SCALE = 0.008
TEETH_RGB = (0.92, 0.90, 0.84)
BEAK_OUT = 0.028  # R2FORM: +4 mm to offset the shallower face (was 0.024)
BEAK_R = (0.034, 0.015, 0.018)  # R2SKIN: 62x38 -> 68x36 mm, the anchor bill is a wide ~2:1 pill
CUT_R = (
    0.027,
    0.011,
    0.0100,
)  # R2SKIN: 48x16 -> 54x20 mm opening; the slit read as a line, the anchor shows a real cavity
CUT_DZ = -0.003  # R2SKIN: opening centre below the bill centre -> thick upper lip, thin lower lip (duck bill)
TEETH_N = 7
TOOTH_R = 0.0015  # R2SKIN: 1.7 -> 1.5 mm, the anchor teeth are tiny
TEETH_SPAN = 0.032
TEETH_DZ = 0.0045  # R2SKIN: teeth hang INSIDE the upper edge (edge is at +0.007)
TEETH_DY = 0.0035
TOOTH_TALL = 1.7  # R2SKIN: tooth = tall ellipsoid, not a bead
TONGUE_R = (0.012, 0.006, 0.0030)
TONGUE_DZ = -0.0105
TONGUE_RGB = (0.055, 0.011, 0.008)  # R3SKIN: darker, the tongue was the brightest thing in the cavity
R_UP = 0.056  # bald radius UPWARD (R2SKIN; shared with fur's _bald_signed so the brow band follows the hairline)
FUR_LEN_MIN = 0.30  # R3FUR: 0.45 -> the cheek tufts beside the mouth stood 47 mm forward across the cheek in profile
FUR_LEN_BAND = 0.100  # m outside the bald boundary over which the length recovers to 1.0
FRINGE_LEN = 0.040
FRINGE_COUNT = 230


def _face_centre_scaled(p, PB):
    ry = p['face_r'] * 0.62
    cy = PB._face_centre_y(p) + (FACE_YS - 1.0) * ry
    return cy, ry * FACE_YS


def _face_surf(x, z, p, PB):
    r = p['face_r']
    cy, ry = _face_centre_scaled(p, PB)
    cz = p['body_lift'] + p['face_z']
    t = (x / r) ** 2 + ((z - cz) / (r * FACE_ZS)) ** 2
    if t >= 1.0:
        return None
    return cy - ry * math.sqrt(1.0 - t)


def _principled_reset(m):
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    nt.links.new(b.outputs['BSDF'], out.inputs['Surface'])
    return nt, b


def skin_material(m):
    nt, b = _principled_reset(m)
    n, L = nt.nodes, nt.links
    b.inputs['Roughness'].default_value = SKIN_ROUGH
    b.inputs['Specular IOR Level'].default_value = SKIN_SPEC
    b.inputs['Subsurface Weight'].default_value = SKIN_SSS
    b.inputs['Subsurface Radius'].default_value = SKIN_SSS_RADIUS
    b.inputs['Subsurface Scale'].default_value = SKIN_SSS_SCALE
    b.subsurface_method = 'RANDOM_WALK'
    tc = n.new('ShaderNodeTexCoord')
    vor = n.new('ShaderNodeTexVoronoi')
    vor.voronoi_dimensions = '3D'
    vor.feature = 'F1'
    vor.inputs['Scale'].default_value = 260.0
    vor.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], vor.inputs['Vector'])
    noi = n.new('ShaderNodeTexNoise')
    noi.inputs['Scale'].default_value = 70.0  # R2SKIN 45: finer gate so the speckle is not one cheek's blob
    noi.inputs['Detail'].default_value = 2.0
    L.new(tc.outputs['Object'], noi.inputs['Vector'])
    lt = n.new('ShaderNodeMath')
    lt.operation = 'LESS_THAN'
    lt.inputs[1].default_value = 0.22  # R2SKIN 0.26
    L.new(vor.outputs['Distance'], lt.inputs[0])
    gt = n.new('ShaderNodeMath')
    gt.operation = 'GREATER_THAN'
    gt.inputs[1].default_value = 0.64  # R2SKIN 0.60
    L.new(noi.outputs['Fac'], gt.inputs[0])
    mul = n.new('ShaderNodeMath')
    mul.operation = 'MULTIPLY'
    L.new(lt.outputs[0], mul.inputs[0])
    L.new(gt.outputs[0], mul.inputs[1])
    mul2 = n.new('ShaderNodeMath')
    mul2.operation = 'MULTIPLY'
    mul2.inputs[1].default_value = 0.85
    L.new(mul.outputs[0], mul2.inputs[0])
    mix = n.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MIX'
    mix.inputs[6].default_value = (*SKIN_RGB, 1.0)
    mix.inputs[7].default_value = (*GOLD_RGB, 1.0)
    L.new(mul2.outputs[0], mix.inputs[0])
    L.new(mix.outputs[2], b.inputs['Base Color'])
    vb = n.new('ShaderNodeTexVoronoi')
    vb.voronoi_dimensions = '3D'
    vb.feature = 'SMOOTH_F1'
    vb.inputs['Scale'].default_value = 300.0
    vb.inputs['Smoothness'].default_value = 0.35
    L.new(tc.outputs['Object'], vb.inputs['Vector'])
    bump = n.new('ShaderNodeBump')
    bump.invert = True
    bump.inputs['Strength'].default_value = 0.30  # R2SKIN 0.22
    bump.inputs['Distance'].default_value = 0.0015
    L.new(vb.outputs['Distance'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


def beak_material(m):
    nt, b = _principled_reset(m)
    b.inputs['Base Color'].default_value = (*BEAK_RGB, 1.0)
    b.inputs['Roughness'].default_value = 0.38
    b.inputs['Specular IOR Level'].default_value = 0.5
    b.inputs['Subsurface Weight'].default_value = 0.20
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.45, 0.25)
    b.inputs['Subsurface Scale'].default_value = 0.005
    b.inputs['Coat Weight'].default_value = 0.20
    b.inputs['Coat Roughness'].default_value = 0.15
    b.subsurface_method = 'RANDOM_WALK'
    return m


def cavity_material(m):
    nt, b = _principled_reset(m)
    b.inputs['Base Color'].default_value = (*CAVITY_RGB, 1.0)
    b.inputs['Roughness'].default_value = 0.75
    b.inputs['Specular IOR Level'].default_value = 0.2
    return m


def teeth_material(m):
    nt, b = _principled_reset(m)
    b.inputs['Base Color'].default_value = (*TEETH_RGB, 1.0)
    b.inputs['Roughness'].default_value = 0.35
    b.inputs['Specular IOR Level'].default_value = 0.5
    b.inputs['Subsurface Weight'].default_value = 0.2
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.8, 0.6)
    b.inputs['Subsurface Scale'].default_value = 0.002
    return m


def fur_density(body, p):
    vg = body.vertex_groups.get('fur_density')
    if vg is None:
        vg = body.vertex_groups.new(name='fur_density')
    fz = p['face_z']
    R_c = 0.074
    R_up = R_UP  # R2SKIN: 0.063 -> 0.056, hairline ~7 mm lower so the fur meets the eye tops as in cell_11 (MERGE had 0.063)
    z_top, hw_top, z_chin = 0.010, 0.062, -0.056
    feather = 0.026
    frL = body.vertex_groups.get('face_fringe_l') or body.vertex_groups.new(name='face_fringe_l')
    frR = body.vertex_groups.get('face_fringe_r') or body.vertex_groups.new(name='face_fringe_r')
    vgl = body.vertex_groups.get('fur_len') or body.vertex_groups.new(name='fur_len')
    for v in body.data.vertices:
        x, y, z = v.co.x, v.co.y, v.co.z
        # MERGE: hair length factor — 1.0 everywhere except a 60 mm band outside the
        # bald boundary on the lower front (cheeks / chin), where it falls to FUR_LEN_MIN
        # at the boundary so the beak and cheek profile clear the coat from the side.
        lf = 1.0
        if y > 0.02:
            w = 1.0
            s = -1.0
        else:
            dz = (z - fz) * (R_c / R_up if z > fz else 1.0)
            d = math.sqrt(x * x + dz * dz)
            s_c = R_c - d
            if z >= z_top:
                hw = hw_top + 0.8 * (z - z_top)
            else:
                hw = max(0.0, hw_top * (z - z_chin) / (z_top - z_chin))
            s_v = hw - abs(x)
            s = min(s_c, s_v)
            w = min(1.0, max(0.0, 0.5 - s / feather))
            if s < 0.0 and y < -0.04 and z < fz + 0.055:
                near = max(0.0, 1.0 - (-s) / FUR_LEN_BAND)
                gate = min(1.0, (-y - 0.04) / 0.03) * min(1.0, (fz + 0.055 - z) / 0.03)
                lf = 1.0 - (1.0 - FUR_LEN_MIN) * near * gate
        vg.add([v.index], w, 'REPLACE')
        vgl.add([v.index], lf, 'REPLACE')
        if y < 0.0 and z < 0.040:
            f = max(0.0, 1.0 - abs(s - 0.012) / 0.016)
            f *= min(1.0, max(0.0, (0.040 - z) / 0.030))
            if z < 0.0:
                f *= min(1.0, max(0.0, (abs(x) - 0.018) / 0.012))
        else:
            f = 0.0
        frL.add([v.index], f if x < 0 else 0.0, 'REPLACE')
        frR.add([v.index], f if x >= 0 else 0.0, 'REPLACE')


def fringe_hair(body, p, PB):
    out = []
    for _side, grp, sx in (('l', 'face_fringe_l', 1.0), ('r', 'face_fringe_r', -1.0)):
        ps = PB._hair(
            body, FRINGE_LEN, FRINGE_COUNT, 10, seed=7 if sx > 0 else 8, thick=p['hair_thick'] * 1.4, density_group=grp
        )
        s = ps.settings
        # MERGE: skin's 0.0055 / (0.0040,-0.0025,-0.0075) x0.7 — the 48 mm fringe was the
        # front half of the fur wall hiding the beak from the side (ID pass, run3)
        s.normal_factor = 0.0030  # R3FUR: 0.0040
        s.object_align_factor = (
            sx * 0.0034,
            0.0003,
            -0.0052,
        )  # R3FUR: was (sx*0.0028, -0.00175, -0.00525): forward crossed the cheek in profile
        s.roughness_1 = FRINGE_LEN * 0.08
        s.roughness_1_size = FRINGE_LEN * 0.6
        s.roughness_endpoint = FRINGE_LEN * 0.12
        s.roughness_2 = FRINGE_LEN * 0.05
        s.roughness_2_size = FRINGE_LEN * 0.5
        s.child_radius = 0.010
        s.clump_factor = 0.55
        s.clump_shape = 0.15
        out.append(ps)
    return out


def build_mouth_beak(scene, result, PB, p):
    lip, mouth, teeth, muz = _ob('pb_lip'), _ob('pb_mouth'), _ob('pb_teeth'), _ob('pb_muzzle')
    mats = result['mats']
    for o in (teeth, muz):
        if o is not None:
            o.hide_render = True
            o.hide_viewport = True
    z_b = p['body_lift'] + p['mouth_z']
    surf = _face_surf(0.0, z_b, p, PB)
    y_bp = surf - BEAK_OUT
    br = (p['mouth_w'] * p['lip_scale'], 0.013, p['mouth_h'] * p['lip_scale'])
    lip.scale = (BEAK_R[0] / br[0], BEAK_R[1] / br[1], BEAK_R[2] / br[2])
    lip.location = (0.0, y_bp + BEAK_R[1], z_b)
    beak_material(mats['lip'])
    mr = (p['mouth_w'], 0.012, p['mouth_h'])
    cut_c = (0.0, y_bp - 0.002, z_b + CUT_DZ)  # R2SKIN
    mouth.scale = (CUT_R[0] / mr[0], CUT_R[1] / mr[1], CUT_R[2] / mr[2])
    mouth.location = cut_c
    mouth.display_type = 'WIRE'
    mouth.hide_render = True
    cavity_material(mats['mouth'])
    bm = lip.modifiers.new('cavity', 'BOOLEAN')
    bm.operation = 'DIFFERENCE'
    bm.solver = 'EXACT'
    bm.object = mouth
    bm.material_mode = 'TRANSFER'
    # R2SKIN: lower lip — a small tan-orange bulge under the opening
    lm = bpy.data.materials.new('pb_lowlip')
    lm.use_nodes = True
    beak_material(lm)
    lm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*LOWLIP_RGB, 1.0)
    ll = PB._sphere(
        'pb_lowlip', (0.0, y_bp + LOWLIP_DY, z_b + LOWLIP_DZ), LOWLIP_R, scene, lm, segs=24, rings=12, idx='mouth'
    )
    result['parts'].append(ll)
    tm = bpy.data.materials.new('pb_tongue')
    tm.use_nodes = True
    cavity_material(tm)
    tb = tm.node_tree.nodes['Principled BSDF']
    tb.inputs['Base Color'].default_value = (*TONGUE_RGB, 1.0)
    tb.inputs['Roughness'].default_value = 0.50
    tb.inputs['Specular IOR Level'].default_value = 0.5
    tg = PB._sphere(
        'pb_tongue', (0.0, y_bp + 0.0045, z_b + TONGUE_DZ), TONGUE_R, scene, tm, segs=20, rings=10, idx='mouth'
    )
    result['parts'].append(tg)
    teeth_material(mats['teeth'])
    z_t = z_b + TEETH_DZ  # R2SKIN: upper-jaw row
    y_t = y_bp + TEETH_DY
    span = TEETH_SPAN
    for k in range(TEETH_N):
        x = -span / 2 + span * k / (TEETH_N - 1)
        t = PB._sphere(
            'pb_tooth_%d' % k,
            (x, y_t, z_t),
            (TOOTH_R, TOOTH_R, TOOTH_R * TOOTH_TALL),
            scene,
            mats['teeth'],
            segs=12,
            rings=8,
            idx='teeth',
        )
        result['parts'].append(t)


# ═════════════════════════════════════════════════════════════════════════════
# R3SKIN — the face mask material (pb_face only; arms keep skin_material)
#   albedo FACE_RGB is fitted per run under the merge light rig (see probe.py bands);
#   glossy sheen rough 0.35 / spec 0.5; SSS small with a MINT radius (r2's warm radius
#   pulled the shade band to olive); gold glitter = Voronoi F1 dots x noise gate x
#   brow/cheek Z gate, EMISSIVE so they stay gold under the green top light (r2's
#   diffuse gold dots rendered olive and vanished); pebbled bump kept.
# ═════════════════════════════════════════════════════════════════════════════
FACE_ROUGH = 0.38
FACE_SPEC = 0.75
FACE_SSS = 0.08
FACE_SSS_RADIUS = (0.55, 1.0, 0.80)
FACE_SSS_SCALE = 0.006
FACE_COAT = 0.45  # clear-coat sheen: the anchor lit zone is a broad pale gloss (run1 0.25/0.15 was a narrow band)
FACE_COAT_ROUGH = 0.22
DOT_SCALE = 320.0  # Voronoi cells ~3.1 mm -> dots ~1.3 mm across at DOT_R
DOT_R = 0.20  # F1 distance threshold (dot radius as a fraction of the cell)
DOT_NOISE_SCALE = 55.0  # sparse gate
DOT_NOISE_GT = 0.60
DOT_Z0, DOT_Z1 = -0.034, -0.012  # face-LOCAL z (unscaled mesh space): 0 below the muzzle -> 1 on the cheeks/brow
DOT_RGB = (1.0, 0.78, 0.34)  # #E8C060-ish gold
DOT_EMIT = 1.6
BUMP_SCALE = 300.0
BUMP_STRENGTH = 0.26
BUMP_DIST = 0.0015


def face_material(m):
    nt, b = _principled_reset(m)
    n, L = nt.nodes, nt.links
    b.inputs['Roughness'].default_value = FACE_ROUGH
    b.inputs['Specular IOR Level'].default_value = FACE_SPEC
    b.inputs['Subsurface Weight'].default_value = FACE_SSS
    b.inputs['Subsurface Radius'].default_value = FACE_SSS_RADIUS
    b.inputs['Subsurface Scale'].default_value = FACE_SSS_SCALE
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Coat Weight'].default_value = FACE_COAT
    b.inputs['Coat Roughness'].default_value = FACE_COAT_ROUGH
    b.inputs['Coat IOR'].default_value = 1.45
    tc = n.new('ShaderNodeTexCoord')
    # glitter dots
    vor = n.new('ShaderNodeTexVoronoi')
    vor.voronoi_dimensions = '3D'
    vor.feature = 'F1'
    vor.inputs['Scale'].default_value = DOT_SCALE
    vor.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], vor.inputs['Vector'])
    lt = n.new('ShaderNodeMath')
    lt.operation = 'LESS_THAN'
    lt.inputs[1].default_value = DOT_R
    L.new(vor.outputs['Distance'], lt.inputs[0])
    noi = n.new('ShaderNodeTexNoise')
    noi.inputs['Scale'].default_value = DOT_NOISE_SCALE
    noi.inputs['Detail'].default_value = 2.0
    L.new(tc.outputs['Object'], noi.inputs['Vector'])
    gt = n.new('ShaderNodeMath')
    gt.operation = 'GREATER_THAN'
    gt.inputs[1].default_value = DOT_NOISE_GT
    L.new(noi.outputs['Fac'], gt.inputs[0])
    sep = n.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Object'], sep.inputs[0])
    zg = n.new('ShaderNodeMapRange')
    zg.interpolation_type = 'SMOOTHSTEP'
    zg.inputs['From Min'].default_value = DOT_Z0
    zg.inputs['From Max'].default_value = DOT_Z1
    L.new(sep.outputs['Z'], zg.inputs['Value'])
    m1 = n.new('ShaderNodeMath')
    m1.operation = 'MULTIPLY'
    L.new(lt.outputs[0], m1.inputs[0])
    L.new(gt.outputs[0], m1.inputs[1])
    dot = n.new('ShaderNodeMath')
    dot.operation = 'MULTIPLY'
    L.new(m1.outputs[0], dot.inputs[0])
    L.new(zg.outputs['Result'], dot.inputs[1])
    # z-graded albedo: saturated chin -> pale brow
    gz = n.new('ShaderNodeMapRange')
    gz.interpolation_type = 'SMOOTHSTEP'
    gz.inputs['From Min'].default_value = FACE_GRAD_Z[0]
    gz.inputs['From Max'].default_value = FACE_GRAD_Z[1]
    L.new(sep.outputs['Z'], gz.inputs['Value'])
    fmix = n.new('ShaderNodeMix')
    fmix.data_type = 'RGBA'
    fmix.blend_type = 'MIX'
    fmix.inputs[6].default_value = (*FACE_CHIN_RGB, 1.0)
    fmix.inputs[7].default_value = (*FACE_RGB, 1.0)
    L.new(gz.outputs['Result'], fmix.inputs[0])
    mix = n.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MIX'
    L.new(fmix.outputs[2], mix.inputs[6])
    mix.inputs[7].default_value = (*DOT_RGB, 1.0)
    L.new(dot.outputs[0], mix.inputs[0])
    L.new(mix.outputs[2], b.inputs['Base Color'])
    b.inputs['Emission Color'].default_value = (*DOT_RGB, 1.0)
    em = n.new('ShaderNodeMath')
    em.operation = 'MULTIPLY'
    em.inputs[1].default_value = DOT_EMIT
    L.new(dot.outputs[0], em.inputs[0])
    L.new(em.outputs[0], b.inputs['Emission Strength'])
    # pebbled micro-bump
    vb = n.new('ShaderNodeTexVoronoi')
    vb.voronoi_dimensions = '3D'
    vb.feature = 'SMOOTH_F1'
    vb.inputs['Scale'].default_value = BUMP_SCALE
    vb.inputs['Smoothness'].default_value = 0.35
    L.new(tc.outputs['Object'], vb.inputs['Vector'])
    bump = n.new('ShaderNodeBump')
    bump.invert = True
    bump.inputs['Strength'].default_value = BUMP_STRENGTH
    bump.inputs['Distance'].default_value = BUMP_DIST
    L.new(vb.outputs['Distance'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


def skin_post(scene, result, PB, p):
    face = _ob('pb_face')
    face.scale = (1.0, FACE_YS, FACE_ZS)
    face.location.y = _face_centre_scaled(p, PB)[0]
    skin_material(result['mats']['skin'])
    # R2MERGE: the face gets its own copy of the skin material with FACE_RGB
    fm = bpy.data.materials.new('pb_skin_face')
    fm.use_nodes = True  # R3SKIN
    face_material(fm)
    if face.data.materials:
        face.data.materials[0] = fm
    else:
        face.data.materials.append(fm)
    body = _ob('pb_body')
    fur_density(body, p)
    for ps in body.particle_systems:
        if ps.name == 'pb_tufts':
            ps.vertex_group_length = 'fur_len'
    fringe_hair(body, p, PB)
    build_mouth_beak(scene, result, PB, p)
    bpy.context.view_layer.update()


# ═════════════════════════════════════════════════════════════════════════════
# r2 FORM — eyes seated INTO the shallow mask + tan lid rims
# ═════════════════════════════════════════════════════════════════════════════
EYE_PROUD = 0.65  # R3MERGE run3: 0.70 -> 0.65, the broader cap is flatter at the eye so the nose-side cover that made the oval is smaller; sink 2.6 mm to keep it   # R3EYES 0.80 -> 0.70: front pole 0.70 r past the face surface point -> 65% of the sphere inside head+socket.
# Measured in the eye's own frame the face rises +0.45 r toward the bridge and falls -1.1..-1.8 r on the
# outer/upper sides, so NO depth shows a full disc: at 0.70 the nose side is covered to rho ~0.68, which
# gives the anchor's upright oval (1.63 x 1.92 r = 0.85; anchor 122x145 px = 0.84). 0.62 (run1) cut it at 0.55.
EYE_TOE_IN = 3.0  # deg, gaze axes converge forward (critic: within 10 deg of -Y). R2MERGE: 6 -> 3, the pupils read cross-eyed in run2
EYE_UP = 5.0  # deg
LID_INNER = 0.82  # x eye_r: inner radius of the bezel lip (eye emerges from it ~flush with the lip front)
LID_TUBE = 0.16  # x eye_r: radial half-width of the rounded lip -> ring is 0.32 r wide (16% of eye diameter)
LID_FRONT = 0.08  # x eye_r: lip front stands this far in front of the face surface point
LID_SKIRT = 0.35  # x eye_r: short skirt into the face. 1.0 r was a tan cylinder that hid the whole side of the eyeball in profile (run3 ID pass)
LID_RGB = (0.61, 0.43, 0.19)  # (unused by the R3EYES ring; kept for the cup code below)
# R3EYES ring bezel: a tube of minor radius RING_T x eye_r laid along the EXACT sphere/face intersection
# (solved per angle), thicker at the bottom like the anchor's lower-lid ledge. Colour: the critic's
# #D2AF78 = linear (0.64,0.43,0.19), but the eyes sit under the GREEN top light which turned r2's
# (0.61,0.43,0.19)+SSS cup pale yellow-green, so G/B are pulled down toward the beak's ratio, which
# DOES render caramel under this rig (run3 beak (230,150,80)).
RING_T_TOP, RING_T_BOT = (
    0.060,
    0.100,
)  # run1's 0.04/0.07 all but vanished, run2's 0.05/0.08 a hairline; anchor bezel is 6-8% of the eye diameter with a fat lower ledge
RING_RGB = (0.72, 0.36, 0.13)  # run3: a step lighter, run2's ring read as dark tan
RING_ROUGH = 0.25
RING_LIFT = 0.55  # x tube radius, along the eye axis, so the ring's front half is never buried
# R3EYES orbital mound: at eye_sep 0.072 the outer half of each eye hangs past the face patch (half-width
# 0.093 at eye height) with the body surface 40 mm behind it, i.e. a marble held by fur (r1 side view).
# The anchor wraps each eye in turquoise orbital skin, so each eye gets a face-coloured sphere of radius
# ORBIT_R x er whose centre sits d behind the eye centre such that the eye leaves it EXACTLY on the
# 0.62 r plane (two-sphere intersection: t = (er^2 - Ro^2 + d^2) / 2d). Its front pole is ~0.05 r
# behind the eye's, so nothing extrudes; the ring solver then runs on face U mound U body.
ORBIT_R = 1.15
ORBIT_B = 0.85  # run6: the mound is an OBLATE ellipsoid (ORBIT_R lateral, ORBIT_B along the gaze axis) placed so it
# still passes through the exit ring; the run5 sphere (2.3 r deep) read as a turquoise ball behind each eye at 45 deg


def _face_point_normal(x, z, p, PB):
    """Point on the SCALED face ellipsoid in front of (x, z) and its outward normal."""
    r = p['face_r']
    cy, ry = _face_centre_scaled(p, PB)
    cz = p['body_lift'] + p['face_z']
    rz = r * FACE_ZS
    t = (x / r) ** 2 + ((z - cz) / rz) ** 2
    if t >= 1.0:
        raise ValueError('eye at (%.3f, %.3f) is off the scaled face' % (x, z))
    y = cy - ry * math.sqrt(1.0 - t)
    n = Vector((x / r**2, (y - cy) / ry**2, (z - cz) / rz**2)).normalized()
    return Vector((x, y, z)), n


def _lid_material():
    m = bpy.data.materials.get('pb_lid')
    if m is None:
        m = bpy.data.materials.new('pb_lid')
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        b.inputs['Base Color'].default_value = (*LID_RGB, 1.0)
        b.inputs['Roughness'].default_value = 0.55
        if 'Specular IOR Level' in b.inputs:
            b.inputs['Specular IOR Level'].default_value = 0.4
        b.inputs['Subsurface Weight'].default_value = 0.10
        b.inputs['Subsurface Radius'].default_value = (1.0, 0.5, 0.3)
        b.inputs['Subsurface Scale'].default_value = 0.004
    return m


def _lid_bezel(name, origin, axis, er, scene, PB, s1=48):
    """Socket bezel: a closed (radial, axial) profile swept about `axis` through `origin`.
    Rounded lip at the front, straight skirt back into the head. Axial +ve = along axis (forward)."""
    ri = LID_INNER * er
    rt = LID_TUBE * er
    back = -LID_SKIRT * er
    prof = [(ri, back), (ri, -0.2 * er)]
    for k in range(9):  # lip arc, inner -> outer, bulging forward
        th = math.pi * (1.0 - k / 8.0)
        prof.append((ri + rt + rt * math.cos(th), -0.2 * er + (0.2 * er + LID_FRONT * er) * math.sin(th)))
    prof.append((ri + 2 * rt, back))
    e1 = axis.cross(Vector((0, 0, 1)))
    if e1.length < 1e-4:
        e1 = axis.cross(Vector((1, 0, 0)))
    e1.normalize()
    e2 = axis.cross(e1).normalized()
    n2 = len(prof)
    verts, faces = [], []
    for i in range(s1):
        u = 2 * math.pi * i / s1
        radial = e1 * math.cos(u) + e2 * math.sin(u)
        for rr, ax in prof:
            verts.append(tuple(origin + radial * rr + axis * ax))
    for i in range(s1):
        i2 = (i + 1) % s1
        for j in range(n2):
            j2 = (j + 1) % n2
            faces.append((i * n2 + j, i2 * n2 + j, i2 * n2 + j2, i * n2 + j2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    PB._outward(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_lid_material())
    ob = bpy.data.objects.new(name, me)
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    return ob


def _ring_material():
    m = bpy.data.materials.get('pb_ring')
    if m is None:
        m = bpy.data.materials.new('pb_ring')
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        b.inputs['Base Color'].default_value = (*RING_RGB, 1.0)
        b.inputs['Roughness'].default_value = RING_ROUGH
        if 'Specular IOR Level' in b.inputs:
            b.inputs['Specular IOR Level'].default_value = 0.5
        b.inputs['Coat Weight'].default_value = 0.3
        b.inputs['Coat Roughness'].default_value = 0.10
    return m


def _face_F(P, p, PB):
    r = p['face_r']
    cy, ry = _face_centre_scaled(p, PB)
    cz = p['body_lift'] + p['face_z']
    rz = r * FACE_ZS
    return (P.x / r) ** 2 + ((P.y - cy) / ry) ** 2 + ((P.z - cz) / rz) ** 2


def _body_F(P, p):
    return (P.x / p['body_rx']) ** 2 + (P.y / p['body_ry']) ** 2 + ((P.z - p['body_lift']) / p['body_rz']) ** 2


def _orbit_d(er):
    """Mound centre distance BEHIND the eye centre. With co = c - d*axis, |P-co|^2 on the eye sphere is
    er^2 + d^2 + 2 d er cos(phi), inside the mound for cos(phi) < (Ro^2-er^2-d^2)/(2 d er); setting that
    threshold to t/er (the exit plane) gives d^2 + 2 t d + er^2 - Ro^2 = 0. run1 had the sign of the
    linear term flipped and put the mound 1.1 r BEHIND the eye (a helmet, not a socket)."""
    Ro = ORBIT_R * er
    t = (1.0 - EYE_PROUD) * er
    return -t + math.sqrt(t * t + Ro * Ro - er * er)


def _mound_t0(er):
    """Axial offset (units er, from the eye centre, +ve forward) of the oblate mound's centre such that the
    ellipsoid (rho/A)^2 + ((t-t0)/B)^2 = 1 passes through the exit ring (t_e, rho_e)."""
    te = 1.0 - EYE_PROUD
    re = math.sqrt(1.0 - te * te)
    return te - ORBIT_B * math.sqrt(max(0.0, 1.0 - (re / ORBIT_R) ** 2))


def _mound_F(P, c, axis, er):
    d = P - c
    t = d.dot(axis) / er
    rho = (d - axis * (t * er)).length / er
    return (rho / ORBIT_R) ** 2 + ((t - _mound_t0(er)) / ORBIT_B) ** 2


def _head_F(P, c, axis, er, p, PB):
    """<1 inside the head = face ellipsoid U orbital mound U body."""
    return min(_face_F(P, p, PB), _mound_F(P, c, axis, er), _body_F(P, p))


ORBIT_AO_DIST = 0.022  # m; crease reach of the AO darkening on the socket (run4 0.014 was invisible)
ORBIT_AO_FLOOR = (
    0.30  # base colour x (floor + (1-floor)*AO): fully occluded skin at the eye contact is 30% of the face colour
)
ORBIT_TINT = 0.62  # socket skin darker than the face (run3/4: the socket's top-lit front read as a pale cup rim)


def _orbit_material(result):
    m = bpy.data.materials.get('pb_skin_orbit')
    if m is not None:
        return m
    src = bpy.data.materials.get('pb_skin_face') or result['mats']['skin']
    m = src.copy()
    m.name = 'pb_skin_orbit'
    nt = m.node_tree
    n, L = nt.nodes, nt.links
    b = next(x for x in n if x.type == 'BSDF_PRINCIPLED')
    lk = next((l for l in L if l.to_node == b and l.to_socket.name == 'Base Color'), None)
    if lk is None:
        return m
    src_out = lk.from_socket
    L.remove(lk)
    ao = n.new('ShaderNodeAmbientOcclusion')
    ao.inputs['Distance'].default_value = ORBIT_AO_DIST
    ao.samples = 8
    fac = n.new('ShaderNodeMath')
    fac.operation = 'MULTIPLY_ADD'
    fac.inputs[1].default_value = 1.0 - ORBIT_AO_FLOOR
    fac.inputs[2].default_value = ORBIT_AO_FLOOR
    L.new(ao.outputs['AO'], fac.inputs[0])
    tint = n.new('ShaderNodeMath')
    tint.operation = 'MULTIPLY'
    tint.inputs[1].default_value = ORBIT_TINT
    L.new(fac.outputs[0], tint.inputs[0])
    sc = n.new('ShaderNodeVectorMath')
    sc.operation = 'SCALE'
    L.new(src_out, sc.inputs[0])
    L.new(tint.outputs[0], sc.inputs['Scale'])
    L.new(sc.outputs['Vector'], b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = 0.55
    return m


def _orbit_mound(name, c, axis, q, er, scene, PB, result):
    t0 = _mound_t0(er)
    co = c + axis * (t0 * er)
    fm = _orbit_material(result)  # run4: AO-creased, darker copy of the face skin
    # radii baked into the vertices (PB._sphere), Y = the gaze axis after the eye's own rotation q
    ob = PB._sphere(
        name, tuple(co), (ORBIT_R * er, ORBIT_B * er, ORBIT_R * er), scene, fm, segs=48, rings=24, idx='face'
    )
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = q
    print(
        'R3EYES mound %s: oblate %.2f x %.2f r, centre %.3f r behind the eye centre, front pole %.3f r behind the eye pole, back %.2f r'
        % (name, ORBIT_R, ORBIT_B, -t0, 1.0 - (t0 + ORBIT_B), t0 - ORBIT_B)
    )
    return ob


def _lid_ring(name, sp, axis, c, er, scene, PB, p, s1=72, s2=12):
    """R3EYES flush bezel. For each angle about the eye axis, bisect along the sphere's meridian
    for the point where the sphere leaves the face ellipsoid, then sweep a small tube (radius
    RING_T x er, top->bottom) about that closed curve. Nothing extrudes: the tube is centred
    RING_LIFT tube-radii in front of the intersection and half of it is inside the head."""
    e1 = axis.cross(Vector((0, 0, 1)))
    if e1.length < 1e-4:
        e1 = axis.cross(Vector((1, 0, 0)))
    e1.normalize()
    e2 = axis.cross(e1).normalized()
    curve, rads = [], []
    for i in range(s1):
        u = 2 * math.pi * i / s1
        rd = e1 * math.cos(u) + e2 * math.sin(u)
        # sphere meridian: phi = angle from the front pole; F>1 outside the face at phi=0
        lo, hi = 0.0, math.pi
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            P = c + axis * (er * math.cos(mid)) + rd * (er * math.sin(mid))
            if _head_F(P, c, axis, er, p, PB) > 1.0:
                lo = mid
            else:
                hi = mid
        phi = 0.5 * (lo + hi)
        Q = c + axis * (er * math.cos(phi)) + rd * (er * math.sin(phi))
        vert = rd.z  # +1 top of the eye, -1 bottom
        rt = er * (RING_T_TOP + (RING_T_BOT - RING_T_TOP) * 0.5 * (1.0 - vert))
        curve.append((Q + axis * (RING_LIFT * rt), rd, rt))
        rads.append(rt)
    verts, faces = [], []
    for i in range(s1):
        Q, rd, rt = curve[i]
        for j in range(s2):
            v = 2 * math.pi * j / s2
            verts.append(tuple(Q + rd * (rt * math.cos(v)) + axis * (rt * math.sin(v))))
    for i in range(s1):
        i2 = (i + 1) % s1
        for j in range(s2):
            j2 = (j + 1) % s2
            faces.append((i * s2 + j, i2 * s2 + j, i2 * s2 + j2, i * s2 + j2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    PB._outward(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_ring_material())
    ob = bpy.data.objects.new(name, me)
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    phis = [math.degrees(math.acos(max(-1.0, min(1.0, (q - c).dot(axis) / er)))) for q, _, _ in curve]
    print(
        'R3EYES ring %s: exit angle from the front pole %.1f..%.1f deg (rho %.3f..%.3f)'
        % (name, min(phis), max(phis), math.sin(math.radians(min(phis))), math.sin(math.radians(max(phis))))
    )
    return ob


def seat_eyes(scene, result, PB, p):
    """Re-seat eye/pupil/glint on the SCALED face: gaze axis toed-in from -Y, eyeball front
    pole EYE_PROUD radii in front of the surface point, iris rotated onto the axis, and a
    tan socket bezel around each eye whose skirt reaches back into the head."""
    er = p['eye_r']
    pup_ry = p['pupil_r'] * 0.70
    z = p['body_lift'] + p['eye_z']
    ti, up = math.radians(EYE_TOE_IN), math.radians(EYE_UP)
    for side, sx in (('l', -1), ('r', 1)):
        x = sx * p['eye_sep']
        sp, n = _face_point_normal(x, z, p, PB)
        a = Vector((-sx * math.sin(ti), -math.cos(ti) * math.cos(up), math.sin(up))).normalized()
        c = sp + a * ((EYE_PROUD - 1.0) * er)
        q = Vector((0.0, -1.0, 0.0)).rotation_difference(a)
        eye, pup, gli = _ob('pb_eye_' + side), _ob('pb_pupil_' + side), _ob('pb_glint_' + side)
        for ob in (eye, pup):
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = q
        eye.location = c
        pup.location = c + a * (er - pup_ry + p['pupil_proud'])
        gd = (q @ Vector((-0.34, -0.87, 0.36))).normalized()
        gli.location = c + gd * (er - p['glint_r'] + p['glint_out'])
        gli.scale = (1.45, 1.0, 0.80)  # R3EYES: the anchor catchlight is a wide, short blob
        mound = _orbit_mound('pb_orbit_' + side, c, a, q, er, scene, PB, result)  # R3EYES: orbital skin
        result['parts'].append(mound)
        rim = _lid_ring('pb_lid_' + side, sp, a, c, er, scene, PB, p)  # R3EYES: flush ring, not the cup
        result['parts'].append(rim)
        print(
            'R2FORM eye_%s surf=(%.3f,%.3f,%.3f) facenormal=(%.2f,%.2f,%.2f) axis=(%.2f,%.2f,%.2f) centre=(%.3f,%.3f,%.3f) front_pole_y=%.3f'
            % (side, sp.x, sp.y, sp.z, n.x, n.y, n.z, a.x, a.y, a.z, c.x, c.y, c.z, (c + a * er).y)
        )


# ═════════════════════════════════════════════════════════════════════════════
# LIGHT — lights, backdrop, floor, bokeh, view transform (r2_light/look.py, run8)
#   r2 changes vs r1 (critic round 1), all inside the overlay hooks:
#   * warm key is a SATURATED amber (1.00,0.27,0.04) at 18 W raking in from the right
#     and slightly low (+0.95S,-0.55S,-0.12S), aimed at the right flank; light-linked to
#     the creature minus legs/feet/toes (the anchor keeps its feet in shadow) and minus the
#     floor (the anchor floor in front of the feet is near black).  A pale key such as
#     (1,0.72,0.38) can NOT reach the anchor's cream flank: Filmic desaturates it to
#     (242,234,193) at flank brightness, which is what r1 rendered (see probe numbers below).
#   * cool light comes from the upper-left-front (where the eye glints sit) and is SPLIT:
#     'top' 16 W for everything, 'furfill' 56 W light-linked to the fur carriers only
#     (pb_body, pb_tail*), so the fur takes ~+0.6 EV while the face/eyes stay at the r1
#     level (anchor face L 160).  Colour (0.32,1.00,0.60) lands the crown at the anchor's
#     mint (203,244,229) under Filmic.
#   * rims/fills are cyan (0.30-0.45,0.80-0.90,1.0) so the shadow flank reads hue 184 like
#     the anchor's; fillR trimmed 7 -> 2 W.
#   * DOF OFF on every view (both anchors are sharp tail-tip to toes); the render_pre
#     gate is gone.  Bokeh dots stay sharp, sit 0.2-0.4 S in front of centre (back-projected
#     from the anchor dots: within 30 px of the feet line), and each carries a soft
#     emissive glow shell standing in for the bloom halo the anchor dots have.
#   * floor: same near-black base, roughness 0.5 / spec 0.2 (the anchor reflection is faint).
# ═════════════════════════════════════════════════════════════════════════════
def _area(scene, name, loc, energy, size, aim, rgb, glossy=True, spread=None):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = size
    ld.color = rgb
    ld.shape = 'DISK'
    if spread is not None:
        ld.spread = math.radians(spread)
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    d = (Vector(aim) - Vector(loc)).normalized()
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = d.to_track_quat('-Z', 'Y')
    o.visible_glossy = glossy
    scene.collection.objects.link(o)
    return o


def _link_to_creature(scene, light_ob):
    """Light-link `light_ob` so it lights only the creature (pb_* minus pb_ground)."""
    coll = bpy.data.collections.get('pb_light_receivers')
    if coll is None:
        coll = bpy.data.collections.new('pb_light_receivers')
        for ob in scene.collection.objects:
            if (
                ob.type == 'MESH'
                and ob.name.startswith('pb_')
                and ob.name != 'pb_ground'
                and not ob.name.startswith(KEY_SHADOWED)
            ):
                coll.objects.link(ob)
    light_ob.light_linking.receiver_collection = coll
    print('R2LIGHT link %s -> %d receivers' % (light_ob.name, len(coll.objects)))


# Colours are chosen from a Filmic (Medium High Contrast) probe of light x fur reflectance:
#   key  (1.00,0.30,0.05) x4 -> sRGB (242,218,124)  vs anchor lit flank (249,222,132)
#   top  (0.32,1.00,0.60) x4 -> ~(210,245,232)      vs anchor crown     (203,244,229)
#   rim  (0.30,0.80,1.00) x0.5 -> hue 184           vs anchor shadow flank hue 184
# Pale keys such as (1,0.72,0.38) cannot reach the flank: Filmic desaturates them to
# (242,234,193) at the same brightness, which is exactly what r1 rendered.
def _link_prefix(scene, light_ob, cname, prefixes, exclude=()):
    coll = bpy.data.collections.get(cname)
    if coll is None:
        coll = bpy.data.collections.new(cname)
        for ob in scene.collection.objects:
            if ob.type == 'MESH' and ob.name.startswith(prefixes) and not ob.name.startswith(exclude):
                coll.objects.link(ob)
    light_ob.light_linking.receiver_collection = coll
    print('R2LIGHT link %s -> %d receivers (%s)' % (light_ob.name, len(coll.objects), cname))


def _link_to_fur(scene, light_ob):
    _link_prefix(scene, light_ob, 'pb_fur_receivers', FUR_CARRIERS)


def _link_to_tail(scene, light_ob):
    _link_prefix(scene, light_ob, 'pb_tail_receivers', ('pb_tail',))


def _link_no_tail(scene, light_ob):
    # R2MERGE: form's tail column stands at (-0.31, 0.36) = right under rimL; unlinked, the
    # cyan rims turned the whole tail plume cyan (run1 tail mint (168,239,224) vs anchor (103,177,176))
    _link_prefix(scene, light_ob, 'pb_rim_receivers', ('pb_',), exclude=('pb_tail',))


LIGHTS = {
    'key': dict(pos=(0.95, -0.55, -0.12), W=18.0, size=0.45, rgb=(1.00, 0.27, 0.04), aim='flankR'),
    # frontal cool light, upper-LEFT-front like the anchor (eye glints sit there); split so the
    # fur can take ~+0.6 EV while the face/eyes stay at the level r1 had (anchor face L 160)
    'top': dict(pos=(-0.50, -0.85, 1.30), W=16.0, size=0.90, rgb=(0.32, 1.00, 0.60), aim='upper'),
    'furfill': dict(
        pos=(-0.50, -0.85, 1.30), W=48.0, size=1.40, rgb=(0.32, 1.00, 0.60), aim='upper'
    ),  # R2MERGE 56 -> 48: crown (226,248,240) vs anchor (214,243,229)
    'tailfill': dict(
        pos=(-0.50, -0.85, 1.30), W=30.0, size=1.40, rgb=(0.95, 1.00, 0.88), aim='upper'
    ),  # R2MERGE: near-white light for the tail only (bands need a white light to read); run2 40 W (0.85,1,0.92) gave cream (217,239,232) vs anchor (206,226,207)
    'rimL': dict(pos=(-0.85, 0.95, 0.85), W=30.0, size=0.35, rgb=(0.40, 0.85, 1.00), aim='c', glossy=False),
    'rimR': dict(pos=(0.55, 1.15, 0.50), W=14.0, size=0.30, rgb=(0.40, 0.85, 1.00), aim='c', glossy=False),
    'fillR': dict(pos=(1.25, -0.30, 0.55), W=2.0, size=0.80, rgb=(0.45, 0.90, 0.90), aim='c', glossy=False),
    'fillL': dict(pos=(-1.20, -0.40, 0.30), W=3.0, size=0.60, rgb=(0.30, 0.80, 1.00), aim='c', glossy=False),
}
LINKED = ('key',)  # lights that must not touch the floor
FUR_ONLY = ('furfill',)  # lights that reach only the fur carriers
TAIL_ONLY = ('tailfill',)  # R2MERGE
NO_TAIL = ('rimL', 'rimR')  # R2MERGE: rims light everything except the tail
FUR_CARRIERS = ('pb_body',)  # R2MERGE: was ('pb_body','pb_tail'); the tail has its own neutral fill
KEY_SHADOWED = ('pb_leg', 'pb_foot', 'pb_toe')  # parts the anchor keeps out of the warm key


S_REF = 0.466  # R2MERGE: bbox size the light rig was tuned at (r2_light run8). Lamp positions and
# sizes scale with S, so irradiance falls as 1/S^2; form's tail grew S to ~0.60
# (-0.7 stop, form caveat 3) -> energies are scaled by (S/S_REF)^2 to keep the tuned look.


def lighting(scene, centre, size, aim):
    c = Vector(centre)
    S = float(size)
    ek = (S / S_REF) ** 2
    print('R2MERGE lighting S=%.3f energy scale=%.3f' % (S, ek))
    aims = {
        'belly': c + Vector((0, -0.25 * S, -0.30 * S)),
        'chest': c + Vector((0, -0.30 * S, -0.15 * S)),
        'low': c + Vector((0, -0.15 * S, -0.15 * S)),
        'upper': c + Vector((0, 0, 0.15 * S)),
        'flankR': c + Vector((0.30 * S, -0.10 * S, -0.15 * S)),
        'crown': c + Vector((0, 0, 0.30 * S)),
        'c': c,
    }
    for name, L in LIGHTS.items():
        o = _area(
            scene,
            name,
            c + Vector(L['pos']) * S,
            L['W'] * ek,
            L['size'] * S,
            aims[L['aim']],
            L['rgb'],
            glossy=L.get('glossy', True),
            spread=L.get('spread'),
        )
        if name in LINKED:
            _link_to_creature(scene, o)
        elif name in FUR_ONLY:
            _link_to_fur(scene, o)
        elif name in TAIL_ONLY:
            _link_to_tail(scene, o)
        elif name in NO_TAIL:
            _link_no_tail(scene, o)


def world(scene):
    w = scene.world
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_WORLD':
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_WORLD')
    bg = nt.nodes.new('ShaderNodeBackground')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    e = ramp.color_ramp.elements
    e[0].position = 0.00
    e[0].color = (0.0080, 0.0170, 0.0250, 1)
    e[1].position = 1.00
    e[1].color = (0.0025, 0.0065, 0.0095, 1)
    e.new(0.45).color = (0.0055, 0.0125, 0.0180, 1)
    powx = nt.nodes.new('ShaderNodeMath')
    powx.operation = 'POWER'
    powx.inputs[1].default_value = 3.0
    mulx = nt.nodes.new('ShaderNodeMath')
    mulx.operation = 'MULTIPLY'
    mulx.inputs[1].default_value = 0.8
    muly = nt.nodes.new('ShaderNodeMath')
    muly.operation = 'MULTIPLY'
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'ADD'
    mix.inputs['B'].default_value = (0.060, 0.050, 0.030, 1)
    nt.links.new(tc.outputs['Window'], sep.inputs['Vector'])
    nt.links.new(sep.outputs['Y'], ramp.inputs['Fac'])
    nt.links.new(sep.outputs['X'], powx.inputs[0])
    nt.links.new(powx.outputs[0], mulx.inputs[0])
    nt.links.new(mulx.outputs[0], muly.inputs[0])
    nt.links.new(sep.outputs['Y'], muly.inputs[1])
    nt.links.new(muly.outputs[0], mix.inputs['Factor'])
    nt.links.new(ramp.outputs['Color'], mix.inputs['A'])
    nt.links.new(mix.outputs['Result'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 1.0
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])


# (name, (right, fwd) in units of S, core radius m, rgb, emission, halo radius multiple)
BOKEH = [
    # floor positions back-projected from the anchor dots (85 mm lens, 6 deg elevation):
    # the anchor dots sit within 30 px of the feet line, i.e. 0.2-0.4 S in front of centre
    ('bokeh_a', (0.42, 0.38), 0.0055, (1.0, 0.80, 0.50), 8.0, 3.5),
    ('bokeh_b', (0.36, 0.19), 0.0030, (1.0, 0.75, 0.45), 6.0, 3.5),
    ('bokeh_c', (0.53, 0.36), 0.0022, (1.0, 0.70, 0.35), 5.0, 3.0),
    ('bokeh_d', (-0.07, 0.30), 0.0012, (1.0, 0.65, 0.30), 4.0, 2.5),
    ('bokeh_e', (-0.03, 0.30), 0.0010, (1.0, 0.65, 0.30), 4.0, 2.5),
]
HALO_STRENGTH = 0.8  # peak emission of the glow shell (falls off to 0 at its rim)
HALO_POWER = 3.0
GROUND = dict(
    rgb=(0.004, 0.0052, 0.0075), rough=0.55, spec=0.12
)  # R2MERGE: spec 0.2 -> 0.12 (green glossy pool under the fur in run1)
_STAGE = {}


def _emit_mat(name, rgb, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*rgb, 1)
    em.inputs['Strength'].default_value = strength
    return m, nt, em, out


def _sphere_ob(scene, name, r, mat):
    import bmesh

    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=r)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    o.pass_index = 0
    o.visible_shadow = False
    scene.collection.objects.link(o)
    return o


def _bokeh(scene, name, r, rgb, strength, halo):
    m, nt, em, out = _emit_mat(name, rgb, strength)
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    core = _sphere_ob(scene, name, r, m)
    # glow shell: emission * facing^p, transparent at the rim; only camera rays see it
    hm, hnt, hem, hout = _emit_mat(name + '_halo', rgb, HALO_STRENGTH)
    lw = hnt.nodes.new('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.5
    pw = hnt.nodes.new('ShaderNodeMath')
    pw.operation = 'POWER'
    pw.inputs[1].default_value = HALO_POWER
    inv = hnt.nodes.new('ShaderNodeMath')
    inv.operation = 'SUBTRACT'
    inv.inputs[0].default_value = 1.0
    hnt.links.new(lw.outputs['Facing'], inv.inputs[1])  # facing: 1 at rim -> 0 at centre; invert
    hnt.links.new(inv.outputs[0], pw.inputs[0])
    tr = hnt.nodes.new('ShaderNodeBsdfTransparent')
    mix = hnt.nodes.new('ShaderNodeMixShader')
    hnt.links.new(pw.outputs[0], mix.inputs['Fac'])
    hnt.links.new(tr.outputs[0], mix.inputs[1])
    hnt.links.new(hem.outputs[0], mix.inputs[2])
    hnt.links.new(mix.outputs[0], hout.inputs['Surface'])
    try:
        hm.blend_method = 'BLEND'
    except (AttributeError, TypeError) as _exc:
        _zyg_log.debug('halo material blend_method unavailable on this blender build: %s', _exc)
    shell = _sphere_ob(scene, name + '_halo', r * halo, hm)
    shell.visible_diffuse = False
    shell.visible_glossy = False
    shell.visible_transmission = False
    return core, shell


def light_post(scene, result, PB):
    lo, hi = PB.bounds(result['parts'])
    c = (lo + hi) / 2
    S = max(hi - lo)
    print('R2LIGHT bounds lo=%s hi=%s centre=%s size=%.3f' % (tuple(lo), tuple(hi), tuple(c), S))
    _STAGE.update(c=Vector(c), S=S, fz=lo.z + 0.004)
    g = _ob('pb_ground')
    if g is not None:
        m = bpy.data.materials.new('pb_ground_canon')
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        b.inputs['Base Color'].default_value = (*GROUND['rgb'], 1)
        b.inputs['Roughness'].default_value = GROUND['rough']
        if 'Specular IOR Level' in b.inputs:
            b.inputs['Specular IOR Level'].default_value = GROUND['spec']
        g.data.materials.clear()
        g.data.materials.append(m)
    bk = S / S_REF  # R2MERGE: camera distance scales with S; keep the dots' image size
    for name, _, r, rgb, strength, halo in BOKEH:
        _bokeh(scene, name, r * bk, rgb, strength, halo)
    pl = bpy.data.lights.new('bokeh_glow', 'POINT')
    pl.energy = 0.6
    pl.shadow_soft_size = 0.02
    pl.color = (1.0, 0.50, 0.18)
    o = bpy.data.objects.new('bokeh_glow', pl)
    scene.collection.objects.link(o)
    _place_bokeh(0.0)


def _place_bokeh(az):
    c, S, fz = _STAGE['c'], _STAGE['S'], _STAGE['fz']
    ca, sa = math.cos(az), math.sin(az)
    for name, (rt, fw), r, _, _, _halo in BOKEH:
        rx, ry = rt * S, -fw * S
        x, y = ca * rx - sa * ry, sa * rx + ca * ry
        o = _ob(name)
        if o:
            o.location = (c.x + x, c.y + y, fz)
        h = _ob(name + '_halo')
        if h:
            h.location = (c.x + x, c.y + y, fz + r * 0.5 * S / S_REF)
    a = _ob('bokeh_a')
    g = _ob('bokeh_glow')
    if a and g:
        g.location = (a.location.x, a.location.y, fz + 0.01)


VIEW_TRANSFORM = ('Filmic', 'Medium High Contrast')
EXPOSURE = 0.0


def camera(cam, cam_data, view_id):
    d = cam_data.dof
    d.use_dof = False  # r2: both anchors are sharp end to end
    if _STAGE:
        c = _STAGE['c']
        v = cam.location - c
        _place_bokeh(math.atan2(v.x, -v.y))
    vs = bpy.context.scene.view_settings
    vs.view_transform, vs.look = VIEW_TRANSFORM
    vs.exposure = EXPOSURE


# ═════════════════════════════════════════════════════════════════════════════
# COMPOSITION
# ═════════════════════════════════════════════════════════════════════════════
def pre_build(PB):
    _P.clear()
    _P.update(PB.P)
    _P.update(PARAMS)
    _ORIG['hair'] = PB._hair
    # form: geometry builders
    PB.build_tail = lambda mats, scene, p=PB.P: build_tail_tube(mats, scene, p, PB)
    PB.build_arms = lambda mats, scene, p=PB.P: build_arms_fwd(mats, scene, p, PB)
    PB.build_feet = lambda mats, scene, p=PB.P: build_feet_r3(mats, scene, p, PB)  # R3FORM
    PB.build_legs = lambda mats, scene, p=PB.P: build_legs_r3(mats, scene, p, PB)  # R3FORM
    # fur: hair dispatcher (body tufts+undercoat / fringe / tail tufts)
    PB._hair = merged_hair


def post_build(scene, result, PB):
    p = dict(_P)
    # merge decision: the body SURFACE under the hair was neutral (0.90,0.91,0.86);
    # light measured the anchor fur at a=117 (mint) and asked for a mint pb_fur.
    fb = result['mats']['fur'].node_tree.nodes['Principled BSDF']
    fb.inputs['Base Color'].default_value = (0.82, 0.92, 0.86, 1.0)
    eyes_post(scene, result, PB, p)
    skin_post(scene, result, PB, p)
    seat_eyes(scene, result, PB, p)  # form r2: needs the scaled face from skin_post
    _tail_post(p)  # fur r2: tail density 1.0 + band colour attribute
    _crown_len(p)  # fur r2: crown/belly/arm/eye-halo/brow length field (after skin's fur_density)
    _fur3_post(p)  # R3FUR: tail ring bands + tube material (overrides _tail_post's helical attribute)
    light_post(scene, result, PB)  # last: measures the finished bounds
    bpy.context.view_layer.update()


# ═════════════════════════════════════════════════════════════════════════════
# R2 FUR — overrides on top of r1_merge (everything above is the base, verbatim)
#
# What changed and why (measured, not guessed):
#  * hair_length is an alias for normal_factor*4 (raw path = 4 s of growth at
#    |velocity|), and effector_weights.gravity does NOTHING to static hair
#    (tested: 0/1/3 gave identical paths). A WIND force field DOES bend the path
#    at cache time (do_path_effectors), segment lengths preserved; effect_hair
#    sets the ramp exponent (100*effect_hair): 0 -> combed from the root,
#    0.01 -> linear ramp = a natural droop. Strength is absolute (vs segment
#    length L/steps): 0.20 on a 0.10 m hair tilts the equator 41 deg down.
#  * INTERPOLATED children clump to their nearest parent, so the coat stays
#    continuous between tufts while the tips converge (scallops, not dandelion).
#  * tail: density 1.0 everywhere (the mint bands are FUR), colour carried by a
#    CORNER byte-colour attribute the hair inherits from its emitter face.
# ═════════════════════════════════════════════════════════════════════════════
R2 = {
    'hair_len': 0.105,
    'hair_count': 2600,
    'hair_child': 18,
    'hair_thick': 0.0009,  # R3FUR: 900/80/0.00075 -> many fine spikes protruding from the undercoat (anchor: ~3-4 mm tufts ~7 mm apart; run1 1400x70 r0.011 = cotton, run2 800x40 r0.0065 = needles, run3 900x50 r0.008 = fat but few, rough -19%)
    'tail_hair_len': 0.042,
    'tail_hair_count': 1400,
    'tail_hair_child': 64,  # R3FUR: 0.055/900/48 -> short dense plush (0.4 x body)
}
PARAMS.update(R2)

WIND = {
    'strength': 0.08,
    'dir': (0.0, 0.30, -1.0),
    'effect_hair': 0.015,  # R3FUR: strength 0.12 -> 0.08 (run4: upper-flank spikes drooped; the anchor's point outward-up, the beard has its own wind); w_tail 0.20 -> 0.10, w_fringe 0 -> 0.3   # run3 0.20/0.01 combed flat; run5 dir 0.5 back laid the back tufts flat (side rough -30%)
    'w_body': 1.0,
    'w_tail': 0.10,
    'w_under': 0.3,
    'w_fringe': 0.3,
}
CROWN = {'z0': 0.035, 'z1': 0.115, 'min': 0.85}  # R3FUR: 0.78 -> crown spikes as long as the body tufts (anchor)
UNDER = {'z0': -0.020, 'z1': -0.095, 'min': 0.55}  # belly fur ends at leg mid-height; anchor shows legs+arms
FRINGE_R = {'root': 0.00050, 'tip': 0.15}  # skin's cheek fringe at 1.4x hair_thick streaked across the eye (run4)
# R3MERGE conflict: fur asked {'r0': 0.060, 'r1': 0.074, 'len_r': 0.110, 'len_min': 0.45} (zero density 12 mm past the
# 48 mm eye rim), eyes asked {'r0': 0.050, 'r1': 0.058, ...} (roots inside the 53 mm sphere grew through the cornea).
# Fur's wins: r0 0.060 >= the new eye_r 0.053 so nothing roots inside the eyeball, and the 1.15 r orbital mound
# (61 mm lateral) stays a bald socket instead of having body hair grow up through it.
EYE_HALO = {
    'r0': 0.050,
    'r1': 0.060,
    'len_r': 0.110,
    'len_min': 0.45,
}  # R3MERGE run2: r0/r1 back to eyes3's 0.050/0.060 -- run1 showed the bald orbital mound as a turquoise ball behind each eye at 45 deg and in profile (goggles); eyes3 rendered r0 0.050 with the 53 mm eye and nothing crossed the cornea. len_r/len_min stay fur's (short hair near the eye)
ARM_ZONE = {
    'x0': 0.075,
    'x1': 0.105,
    'z_top': 0.045,
    'z_lo': -0.10,
    'y_max': -0.03,
    'min': 0.55,
}  # run6: arms buried under drooping lower-flank fur; anchor hangs them outside the coat   # run5: tufts rooted behind the eye's outer half point at the camera and streak across the pupil     # length factor 1.0 -> 0.78 up the crown
UNDERCOAT2 = {
    'len': 0.060,
    'count': 5000,
    'child': 28,
    'thick': 0.00040,
}  # R3FUR: 0.024/3500/16 -> the dense inner coat the tufts stick out of (anchor: spikes protrude ~30% past a plush coat)
TAIL_UNDER = {'len': 0.016, 'count': 3000, 'child': 20, 'thick': 0.00035}  # R3FUR: 0.022/14
TIP_FADE_S = 0.97
TAIL_LEN = (0.45, 0.55)  # R3FORM: tip 0.45 (r2 0.55 left a tuft on a 4 mm core; run2 0.35 + fade 0.94 was a needle)
BROW = {'band': 0.06, 'min': 0.50}  # fur_len band outside the TOP of the bald edge
FUR_COL = {
    'root': (0.76, 0.95, 0.88),
    'tip': (
        0.96,
        0.995,
        0.97,
    ),  # R3FUR: root (0.50,0.88,0.76) was a saturated mint -> fur L 219 vs anchor 233; run2 (0.74,0.90,0.84) lost the mint (a 121/127 vs anchor 117/115)
    'band_root': (0.08, 0.55, 0.40),
    'band_tip': (
        0.18,
        0.72,
        0.55,
    ),  # R3FUR: short radial tail hair no longer blurs the band, so the band can be a real mint   # R2MERGE: was (0.30,0.82,0.64)/(0.52,0.92,0.78) -> run1 (168,239,224); (0.10,0.40,0.36)/(0.22,0.56,0.50) -> run2 (153,222,211); anchor band (103,177,176)
    'roughness': 0.35,
    'radial': 0.30,
    'coat': 0.25,
    'random_color': 0.04,  # R3FUR: 0.38
    'diffuse_mix': 0.60,
}  # R3FUR: 0.50 -> the diffuse half is what lifts L under the fills
_WIND = {}


def _wind_collection():
    """One WIND empty in its own collection; systems opt in via effector_weights."""
    if 'col' in _WIND:
        return _WIND['col']
    scene = bpy.context.scene
    col = bpy.data.collections.new('pb_wind')
    scene.collection.children.link(col)
    bpy.ops.object.effector_add(type='WIND', location=(0.0, 0.0, 1.0))
    f = bpy.context.active_object
    f.name = 'pb_wind'
    d = Vector(WIND['dir']).normalized()
    f.rotation_mode = 'QUATERNION'
    f.rotation_quaternion = d.to_track_quat('Z', 'Y')
    f.field.strength = WIND['strength']
    f.field.falloff_power = 0.0
    f.field.flow = 0.0
    f.field.noise = 0.0
    f.hide_render = True
    for c in list(f.users_collection):
        c.objects.unlink(f)
    col.objects.link(f)
    _WIND['col'] = col
    return col


def _bind_wind(s, weight, force=None):
    s.effector_weights.collection = _wind_collection()
    s.effector_weights.wind = weight
    s.effector_weights.force = FACE_FORCE['w_default'] if force is None else force  # R3FUR
    s.effector_weights.gravity = 0.0
    s.effect_hair = WIND['effect_hair']


def _grad_material(name, root, tip, band=None):
    """Principled Hair (Chiang) + diffuse mix; colour graded root->tip by Hair
    Info intercept; optional band mask from the emitter colour attribute."""
    H = FUR_COL
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    hi = nt.nodes.new('ShaderNodeHairInfo')
    mixc = nt.nodes.new('ShaderNodeMix')
    mixc.data_type = 'RGBA'
    mixc.blend_type = 'MIX'
    mixc.inputs[6].default_value = (*root, 1.0)
    mixc.inputs[7].default_value = (*tip, 1.0)
    nt.links.new(hi.outputs['Intercept'], mixc.inputs[0])
    col_out = mixc.outputs[2]
    if band is not None:
        b_root, b_tip = band
        mixb = nt.nodes.new('ShaderNodeMix')
        mixb.data_type = 'RGBA'
        mixb.blend_type = 'MIX'
        mixb.inputs[6].default_value = (*b_root, 1.0)
        mixb.inputs[7].default_value = (*b_tip, 1.0)
        nt.links.new(hi.outputs['Intercept'], mixb.inputs[0])
        attr = nt.nodes.new('ShaderNodeAttribute')
        attr.attribute_name = 'band_col'
        sel = nt.nodes.new('ShaderNodeMix')
        sel.data_type = 'RGBA'
        sel.blend_type = 'MIX'
        nt.links.new(attr.outputs['Fac'], sel.inputs[0])
        nt.links.new(col_out, sel.inputs[6])
        nt.links.new(mixb.outputs[2], sel.inputs[7])
        col_out = sel.outputs[2]
    h = nt.nodes.new('ShaderNodeBsdfHairPrincipled')
    try:
        h.model = 'CHIANG'
    except TypeError as _exc:
        _zyg_log.debug('hair BSDF CHIANG model unavailable on this blender build: %s', _exc)
    h.parametrization = 'COLOR'
    nt.links.new(col_out, h.inputs['Color'])
    for k, v in (
        ('Roughness', H['roughness']),
        ('Radial Roughness', H['radial']),
        ('Coat', H['coat']),
        ('Random Color', H['random_color']),
        ('Random Roughness', 0.2),
    ):
        if k in h.inputs:
            h.inputs[k].default_value = v
    d = nt.nodes.new('ShaderNodeBsdfDiffuse')
    nt.links.new(col_out, d.inputs['Color'])
    mix = nt.nodes.new('ShaderNodeMixShader')
    mix.inputs['Fac'].default_value = H['diffuse_mix']
    nt.links.new(h.outputs[0], mix.inputs[1])
    nt.links.new(d.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    return m


def _hair_material():  # body/fringe/undercoat: graded cream
    if 'm' in _HAIR_MAT:
        return _HAIR_MAT['m']
    _HAIR_MAT['m'] = _grad_material('pb_hair_bsdf', FUR_COL['root'], FUR_COL['tip'])
    return _HAIR_MAT['m']


def _tail_material():  # tail: same, with the band mask
    if 't' in _HAIR_MAT:
        return _HAIR_MAT['t']
    _HAIR_MAT['t'] = _grad_material(
        'pb_tail_hair', FUR_COL['root'], FUR_COL['tip'], band=(FUR_COL['band_root'], FUR_COL['band_tip'])
    )
    return _HAIR_MAT['t']


def _use_mat(ob, s, m):
    if m.name not in [x.name for x in ob.data.materials if x]:
        ob.data.materials.append(m)
    s.material = [x.name if x else None for x in ob.data.materials].index(m.name) + 1


def _tuft_settings(
    s, length, thick, clump=0.95, shape=0.20, radius=0.0045
):  # R3FUR FINAL: run6 0.25/0.0055 x24 fused the outline again (front rough -23%)   # R3FUR: 0.85/-0.05/0.010 -> feathered clump with a pointed tip (run1 0.92/0.35/0.011 overlapped into cotton; run2 0.25/0.0065 needles)
    s.hair_step = 5
    s.use_hair_bspline = True
    s.use_advanced_hair = True
    s.object_align_factor = (0.0, 0.0, 0.0)
    s.factor_random = 0.0
    s.length_random = 0.35  # R3FUR: 0.60 read as straggling single strands; every tuft must clear the 60 mm undercoat (0.35 x 0.105 = 68 mm min)
    s.child_type = 'SIMPLE'  # one discrete tuft per parent (run1: INTERPOLATED = cotton ball)
    s.child_length = 1.0
    s.child_radius = radius
    s.child_roundness = 0.5
    s.clump_factor = clump
    s.clump_shape = shape
    s.use_clump_noise = False
    s.roughness_1 = length * 0.04  # R3FUR: 0.08
    s.roughness_1_size = length * 1.5
    s.roughness_2 = length * 0.015  # R3FUR: 0.02
    s.roughness_2_size = 1.0
    s.roughness_2_threshold = 0.5
    s.roughness_endpoint = length * 0.02  # R3FUR: 0.03
    s.roughness_end_shape = 1.0
    s.kink = 'WAVE'
    s.kink_amplitude = length * 0.08  # R3FUR: 0.05
    s.kink_amplitude_clump = 0.8
    s.kink_frequency = 2.0  # R3FUR: 1.2
    s.kink_shape = 0.2
    s.brownian_factor = 0.0
    s.render_type = 'PATH'
    s.radius_scale = 1.0
    s.root_radius = thick
    s.tip_radius = thick * 0.35  # R3FUR: 0.25. run2: 0.05 wisps vanished from the alpha; the tuft must stay a body


def _body_hair(ob, length, count, children, seed, thick, density_group):
    bpy.context.view_layer.objects.active = ob
    ob.modifiers.new('hair', 'PARTICLE_SYSTEM')
    ps = ob.particle_systems[-1]
    ps.name = 'pb_tufts'
    ps.seed = seed
    s = ps.settings
    s.type = 'HAIR'
    s.count = count
    s.hair_length = length
    s.child_percent = children
    s.rendered_child_count = children
    _tuft_settings(s, length, thick)
    if density_group:
        ps.vertex_group_density = density_group
    _bind_wind(s, WIND['w_body'], FACE_FORCE['w_body'])  # R3FUR
    _use_mat(ob, s, _hair_material())
    return ps


def _undercoat(ob, density_group, seed=7, U=None):
    U = U or UNDERCOAT2
    bpy.context.view_layer.objects.active = ob
    ob.modifiers.new('undercoat', 'PARTICLE_SYSTEM')
    ps = ob.particle_systems[-1]
    ps.seed = seed
    ps.name = (
        'pb_tail_under' if ob.name.startswith('pb_tail') else 'pb_undercoat'
    )  # R3FUR: named so _fur3_post can hand it the fur_len group
    s = ps.settings
    s.type = 'HAIR'
    s.count = U['count']
    s.hair_length = U['len']
    s.hair_step = 4
    s.use_hair_bspline = True
    s.use_advanced_hair = True
    s.length_random = 0.4
    s.child_type = 'INTERPOLATED'
    s.child_percent = U['child']
    s.rendered_child_count = U['child']
    s.clump_factor = 0.6  # R3FUR: 0.5
    s.clump_shape = 0.2
    s.roughness_1 = U['len'] * 0.15
    s.roughness_1_size = U['len'] * 1.0
    s.roughness_2 = U['len'] * 0.05
    s.roughness_endpoint = U['len'] * 0.10
    s.brownian_factor = 0.0
    s.render_type = 'PATH'
    if density_group:
        ps.vertex_group_density = density_group
    s.radius_scale = 1.0
    s.root_radius = U['thick']
    s.tip_radius = U['thick'] * 0.2
    _bind_wind(s, WIND['w_under'], FACE_FORCE['w_under'])  # R3FUR
    _use_mat(ob, s, _tail_material() if ob.name.startswith('pb_tail') else _hair_material())
    return ps


def _tail_tufts(ob, length, count, children, seed, thick, density_group):
    bpy.context.view_layer.objects.active = ob
    ob.modifiers.new('hair', 'PARTICLE_SYSTEM')
    ps = ob.particle_systems[-1]
    ps.name = 'pb_tail_tufts'
    ps.seed = seed
    s = ps.settings
    s.type = 'HAIR'
    s.count = count
    s.hair_length = length
    s.child_percent = children
    s.rendered_child_count = children
    _tuft_settings(
        s, length, thick * 1.0, clump=0.60, shape=0.0, radius=0.005
    )  # R3FUR: 1.5/0.88/-0.10/0.007 -> a fine radial brush, not cotton blobs (run2)
    if density_group:
        ps.vertex_group_density = density_group
    _bind_wind(s, WIND['w_tail'], FACE_FORCE['w_tail'])  # R3FUR
    _use_mat(ob, s, _tail_material())
    _undercoat(ob, density_group, seed=seed + 1, U=TAIL_UNDER)
    return ps


def merged_hair(ob, length, count=1500, children=8, seed=0, thick=0.0018, density_group=None):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    if ob.name.startswith('pb_tail'):
        return _tail_tufts(ob, length, count, children, seed, thick, density_group)
    if density_group and density_group.startswith('face_fringe'):
        ps = _ORIG['hair'](ob, length, count, children, seed=seed, thick=thick, density_group=density_group)
        _bind_wind(ps.settings, WIND['w_fringe'], FACE_FORCE['w_fringe'])  # R3FUR
        ps.settings.root_radius = FRINGE_R['root']
        ps.settings.tip_radius = FRINGE_R['root'] * FRINGE_R['tip']
        _use_mat(ob, ps.settings, _hair_material())
        return ps
    ps = _body_hair(ob, length, count, children, seed, thick, density_group)
    _undercoat(ob, density_group)
    return ps


def _tail_post(p):
    """Tail: fur to the core. Density 1.0 on the bands too, the band read carried
    by a corner colour attribute the hair inherits; gentler length taper."""
    t = _ob('pb_tail_00')
    if t is None:
        return
    me = t.data
    vg_d = t.vertex_groups.get('tail_density')
    vg_l = t.vertex_groups.get('tail_len')
    a, b = TAIL_LEN
    for v in me.vertices:
        if vg_d is not None:
            vg_d.add([v.index], 1.0, 'REPLACE')
        if vg_l is not None:
            try:
                w_old = vg_l.weight(v.index)
            except RuntimeError:
                w_old = 1.0
            one_minus_s = max(0.0, min(1.0, (w_old - 0.35) / 0.65))
            vg_l.add([v.index], a + b * one_minus_s, 'REPLACE')
            # R3FORM: fur density fades out over the last 6% so the tip is a POINT, not a pom-pom
            s_ = 1.0 - one_minus_s
            if vg_d is not None and s_ > TIP_FADE_S:
                vg_d.add([v.index], max(0.0, 1.0 - (s_ - TIP_FADE_S) / (1.0 - TIP_FADE_S)), 'REPLACE')
    ca = me.color_attributes.get('band_col')
    if ca is None:
        ca = me.color_attributes.new(name='band_col', type='BYTE_COLOR', domain='CORNER')
    for poly in me.polygons:
        c = (1.0, 1.0, 1.0, 1.0) if poly.material_index == 1 else (0.0, 0.0, 0.0, 1.0)
        for li in poly.loop_indices:
            ca.data[li].color = c
    # the tube under the fur: mint on bands stays, cream elsewhere is fine (it is buried)


def _bald_signed(x, z, p):
    """skin's signed distance to the bald edge (>0 inside), same constants as fur_density."""
    fz = p['face_z']
    R_c = 0.074
    R_up = R_UP  # R2MERGE: was a hard-coded 0.063 (r1 hairline)
    z_top, hw_top, z_chin = 0.010, 0.062, -0.056
    dz = (z - fz) * (R_c / R_up if z > fz else 1.0)
    s_c = R_c - math.sqrt(x * x + dz * dz)
    hw = hw_top + 0.8 * (z - z_top) if z >= z_top else max(0.0, hw_top * (z - z_chin) / (z_top - z_chin))
    return min(s_c, hw - abs(x))


def _crown_len(p):
    """fur_len *= crown factor (1 -> CROWN.min up the crown) and *= brow factor (BROW.min
    at the top edge of the bald patch, recovering over BROW.band) so the drooping
    brow hair does not curtain the forehead (run1)."""
    body = _ob('pb_body')
    vgl = body.vertex_groups.get('fur_len')
    if vgl is None:
        return
    z0, z1, mn = CROWN['z0'], CROWN['z1'], CROWN['min']
    fz = p['face_z']
    vgd = body.vertex_groups.get('fur_density')
    ex, ez = p['eye_sep'], p['eye_z']
    H = EYE_HALO
    for v in body.data.vertices:
        x, y, z = v.co.x, v.co.y, v.co.z
        f = 1.0
        if y < -0.03 and vgd is not None:
            de = min(math.hypot(x - ex, z - ez), math.hypot(x + ex, z - ez))
            if de < H['len_r']:
                t = max(0.0, min(1.0, (de - H['r0']) / (H['r1'] - H['r0'])))
                try:
                    wd = vgd.weight(v.index)
                except RuntimeError:
                    wd = 1.0
                vgd.add([v.index], wd * t, 'REPLACE')
                tl = de / H['len_r']
                f *= H['len_min'] + (1.0 - H['len_min']) * tl
        if z > z0:
            t = min(1.0, (z - z0) / (z1 - z0))
            t = t * t * (3 - 2 * t)
            f *= 1.0 - (1.0 - mn) * t
        if z < UNDER['z0']:
            t = min(1.0, (UNDER['z0'] - z) / (UNDER['z0'] - UNDER['z1']))
            t = t * t * (3 - 2 * t)
            f *= 1.0 - (1.0 - UNDER['min']) * t
        A = ARM_ZONE
        if y < A['y_max'] and A['z_lo'] < z < A['z_top'] and abs(x) > A['x0']:
            tx = min(1.0, (abs(x) - A['x0']) / (A['x1'] - A['x0']))
            tz = min(1.0, (A['z_top'] - z) / 0.03)
            ty = min(1.0, (A['y_max'] - y) / 0.03)
            f *= 1.0 - (1.0 - A['min']) * tx * tz * ty
        if y < -0.02 and z > fz + 0.02:
            sd = _bald_signed(x, z, p)
            if sd < 0.0:
                near = max(0.0, 1.0 - (-sd) / BROW['band'])
                gate = min(1.0, (-y - 0.02) / 0.03)
                f *= 1.0 - (1.0 - BROW['min']) * near * gate
        if f >= 1.0:
            continue
        try:
            w = vgl.weight(v.index)
        except RuntimeError:
            w = 1.0
        vgl.add([v.index], w * f, 'REPLACE')


# R2MERGE: fur's post_build wrapper is folded into the COMPOSITION post_build above
# (order: fur mat -> eyes -> skin -> seat_eyes -> _tail_post -> _crown_len -> light_post).


# ═════════════════════════════════════════════════════════════════════════════
# R3 FUR — feathered clumps, face-repel sweep, ring-banded tail
#
# * TUFT SHAPE. clump_shape was -0.05 (children converge from the root: a thin spike
#   over most of the length). Positive shape keeps the children spread until near the
#   tip and pinches them there: a fat feather with a pointed tip, which is what every
#   tuft in the anchor is. More parents (1400) with fewer, thicker children (70 x 1.1 mm)
#   so the coat is made of ~12 mm-spaced clumps rather than 80-strand brooms.
# * DIRECTION. The anchor's tufts radiate AWAY FROM THE FACE in the image plane and
#   the crown spikes up; a body normal points at the camera on the front hemisphere
#   (tufts seen end-on) and the wind droop drags the crown over the forehead. A
#   repulsive POINT force at the face centre INSIDE the ball gives d = (p - c)/|p - c|:
#   on the cheek that is sideways, on the forehead up, on the chin down, and on the
#   flank/back it is the normal it already had. Hair deflection per segment is
#   strength * ramp / hair_length, so the same field bends short hair more: the
#   undercoat gets a small weight and the tail none.
# * TAIL BANDS. form's _is_band phases by the angle round the tube, i.e. a 6-turn
#   HELIX, and 55 mm hair on a ~100 mm tube blurred it to mottling. The bands are
#   re-written here as 7 RINGS along s with a soft edge, the hair is 42 mm and radial
#   (wind weight 0.10), and the tube under it takes the same attribute so nothing
#   helical shows through.
# ═════════════════════════════════════════════════════════════════════════════
FACE_FORCE = {
    'strength': 0.12,
    'centre': (
        0.0,
        -0.150,
        0.040,
    ),  # body-local; run1 (0,-0.06,0.04) sat BEHIND the cheek roots so it still pushed them forward -> the face pole
    'w_default': 0.0,
    'w_body': 1.0,
    'w_under': 0.3,
    'w_tail': 0.0,
    'w_fringe': 0.5,
}
BEARD_WIND = {
    'strength': 0.22,
    'centre': (0.0, -0.140, -0.060),
    'dir': (0.0, -0.15, -1.0),
    'dist': 0.16,
}  # body-local; a DOWN wind only the lower face / chest can feel: the anchor beard hangs from the jaw, run2's chest tufts pointed at the beak
TAIL_RINGS = {'n': 7, 's0': 0.22, 's1': 0.95, 'mint_frac': 0.42, 'edge': 0.08}
TAIL_TUBE = {'white': (0.82, 0.92, 0.86), 'mint': (0.14, 0.66, 0.50)}


def _wind_collection():
    """One WIND + one FORCE empty in the effector collection; systems opt in through
    effector_weights.wind / .force. (Overrides the r2 definition above.)"""
    if 'col' in _WIND:
        return _WIND['col']
    scene = bpy.context.scene
    col = bpy.data.collections.new('pb_wind')
    scene.collection.children.link(col)
    bpy.ops.object.effector_add(type='WIND', location=(0.0, 0.0, 1.0))
    f = bpy.context.active_object
    f.name = 'pb_wind'
    d = Vector(WIND['dir']).normalized()
    f.rotation_mode = 'QUATERNION'
    f.rotation_quaternion = d.to_track_quat('Z', 'Y')
    f.field.strength = WIND['strength']
    f.field.falloff_power = 0.0
    f.field.flow = 0.0
    f.field.noise = 0.0
    f.hide_render = True
    for c in list(f.users_collection):
        c.objects.unlink(f)
    col.objects.link(f)
    # R3FUR: face-repel point force
    body = _ob('pb_body')
    bc = Vector(body.location) if body is not None else Vector((0.0, 0.0, _P.get('body_lift', 0.2)))
    loc = bc + Vector(FACE_FORCE['centre'])
    bpy.ops.object.effector_add(type='FORCE', location=tuple(loc))
    g = bpy.context.active_object
    g.name = 'pb_face_repel'
    g.field.strength = FACE_FORCE['strength']
    g.field.falloff_power = 0.0
    g.field.use_max_distance = True
    g.field.distance_max = 0.45
    g.field.flow = 0.0
    g.field.noise = 0.0
    g.hide_render = True
    for c in list(g.users_collection):
        c.objects.unlink(g)
    col.objects.link(g)
    print('R3FUR force field at %s strength %.3f' % (tuple(round(v, 3) for v in loc), FACE_FORCE['strength']))
    # R3FUR: beard wind (shares effector_weights.wind with the global droop)
    B = BEARD_WIND
    bloc = bc + Vector(B['centre'])
    bpy.ops.object.effector_add(type='WIND', location=tuple(bloc))
    w = bpy.context.active_object
    w.name = 'pb_beard_wind'
    bd = Vector(B['dir']).normalized()
    w.rotation_mode = 'QUATERNION'
    w.rotation_quaternion = bd.to_track_quat('Z', 'Y')
    w.field.strength = B['strength']
    w.field.falloff_power = 0.0
    w.field.use_max_distance = True
    w.field.distance_max = B['dist']
    w.field.flow = 0.0
    w.field.noise = 0.0
    w.hide_render = True
    for c in list(w.users_collection):
        c.objects.unlink(w)
    col.objects.link(w)
    print(
        'R3FUR beard wind at %s strength %.3f reach %.3f' % (tuple(round(v, 3) for v in bloc), B['strength'], B['dist'])
    )
    _WIND['col'] = col
    return col


def _ring_band(s):
    """0 = white, 1 = mint, along the tail's s; TAIL_RINGS['n'] rings between s0 and s1
    with an edge blend of TAIL_RINGS['edge'] of a period."""
    R = TAIL_RINGS
    if s <= R['s0'] or s >= R['s1']:
        return 0.0
    tv = (s - R['s0']) / (R['s1'] - R['s0'])
    ph = (tv * R['n']) % 1.0
    lo = 0.5 - R['mint_frac'] / 2.0
    hi = 0.5 + R['mint_frac'] / 2.0
    e = R['edge']
    a = min(1.0, max(0.0, (ph - (lo - e / 2)) / e))
    b = min(1.0, max(0.0, ((hi + e / 2) - ph) / e))
    return min(a, b)


def _tube_material():
    m = bpy.data.materials.new('pb_tail_tube')
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    attr = nt.nodes.new('ShaderNodeAttribute')
    attr.attribute_name = 'band_col'
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MIX'
    mix.inputs[6].default_value = (*TAIL_TUBE['white'], 1.0)
    mix.inputs[7].default_value = (*TAIL_TUBE['mint'], 1.0)
    nt.links.new(attr.outputs['Fac'], mix.inputs[0])
    nt.links.new(mix.outputs[2], b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = 0.7
    return m


def _fur3_post(p):
    """Undercoat takes the fur_len field; tail: ring bands as the hair's emitter colour
    attribute + the tube's material."""
    body = _ob('pb_body')
    if body is not None:
        for ps in body.particle_systems:
            if ps.name == 'pb_undercoat':
                ps.vertex_group_length = 'fur_len'
                print(
                    'R3FUR undercoat -> fur_len (%d parents x %d, %.3f m)'
                    % (ps.settings.count, ps.settings.rendered_child_count, ps.settings.hair_length)
                )
    t = _ob('pb_tail_00')
    if t is None:
        return
    me = t.data
    n = p['tail_rings']
    S = p['tail_sides']
    n_rings = n - 1
    ring0 = 1

    def vert_s(vi):
        if vi < ring0:
            return 0.0
        i = (vi - ring0) // S
        if i >= n_rings:
            return 1.0
        return i / float(n - 1)

    ca = me.color_attributes.get('band_col')
    if ca is None:
        ca = me.color_attributes.new(name='band_col', type='BYTE_COLOR', domain='CORNER')
    hist = [0, 0]
    for poly in me.polygons:
        s = sum(vert_s(v) for v in poly.vertices) / float(len(poly.vertices))
        w = _ring_band(s)
        hist[1 if w > 0.5 else 0] += 1
        for li in poly.loop_indices:
            ca.data[li].color = (w, w, w, 1.0)
        poly.material_index = 0
    tm = _tube_material()
    if me.materials:
        me.materials[0] = tm
    else:
        me.materials.append(tm)
    print('R3FUR tail rings: %d white / %d mint faces' % tuple(hist))


# ═════════════════════════════════════════════════════════════════════════════
# R3 LIGHT — critic round 2: "the fur reads cyan-and-yellow, not white".
#   Cause: run3's two big lights were both SATURATED and both LARGE — top/furfill
#   (0.32,1.00,0.60) green-cyan flooding the whole upper-left (1.4 S disk) and the
#   amber key (1.00,0.27,0.04) at 18 W on the lower right.  Zone probe (probe2.py,
#   anchor vs r2_merge/run3, sRGB medians):
#     crown   anchor (229,250,234) L246   run3 (183,232,214) L225   -> too green, too dark
#     flankL  anchor ( 88,147,144) L146   run3 (181,234,216) L226   -> flooded cyan (anchor: teal SHADOW)
#     flankR  anchor (248,232,170) L235   run3 (234,219,152) L223   -> saturated yellow
#     chest   anchor (175,150,112) L162   run3 (169,188,145) L189   -> green
#   Colours were then CALIBRATED through Filmic Medium High Contrast (sweep.py: emissive
#   patches of light x fur albedo at 10 strengths), because Filmic desaturates toward
#   white in the shoulder and the eye cannot invert that:
#     * the critic's pale cream #FFE6C0 gives (242,241,231) at flank brightness and
#       (250,249,244) any brighter -- it can never be the anchor's cream.  The anchor
#       flank (248,232,170) is amber (1.0,0.35,0.08) at 5.6-8 x; the critic's chest
#       target (240,225,190) is (1.0,0.45,0.15) at 4 x.  WARM = (1.0,0.40,0.12): the
#       yellow-green of run3 came from that amber at LOW intensity (2.8 x -> (235,200,94))
#       on the mint fur roots, so the warm light is now brighter, lower and aimed at the
#       belly, and split general / fur-only like the key.
#     * a neutral 6500 K key gives the crown a 6-point mint spread (240,244,242);
#       the anchor has 21 (229,250,234), the critic's target 10 (235,245,232).
#       KEYC = (0.82,1.0,0.90) lands the target at ~3.5 x.
#     * the anchor's shadow flank is SATURATED cyan at 0.35 x ((0.40,0.85,1.0) ->
#       (101,153,157)), i.e. dim, not desaturated: the rims keep a cyan but drop to
#       4-6 W and move behind the body so the flank cosine falls from 0.41 to ~0.1.
#   The key is a small (0.40 S) disk high up (el 67 deg) so the left flank falls off
#   and the head shades the chest (anchor chest L162 under a L246 crown).
#   Floor: roughness 0.55 -> 0.35, spec 0.12 -> 0.25 for the anchor's soft reflection.
# ═════════════════════════════════════════════════════════════════════════════
KEYC = (
    0.74,
    1.00,
    0.86,
)  # mint-white key (Filmic-calibrated, see above); run7: 0.82 -> 0.74 R, fur median a 124 vs anchor 117 in BOTH views
WARM = (1.00, 0.40, 0.12)  # amber that Filmic renders as the anchor's cream at belly brightness
MINT = (0.73, 1.00, 0.84)  # run3's (0.32,1,0.6) desaturated 60 %
CYAN = (0.55, 0.88, 1.00)  # rims: 30 % desaturated (the shadow flank must stay teal)

LIGHTS.clear()
LIGHTS.update(
    {
        # key el ~60 deg: the front anchor wants it high (head shades the chest), the side anchor
        # wants it frontal (back in shadow); 7 W general for face/eyes, 52 W fur-only
        'key': dict(
            pos=(0.10, -0.75, 1.30), W=14.0, size=0.40, rgb=KEYC, aim='upper'
        ),  # R3MERGE: 7 -> 14 W. light3 tuned the general level against the harness lab_face (90% fur-covered face + bezels); the teal-gated face rendered L110/a115 vs anchor L139/a97 and the arms (73,122,86) vs r2's (113,155,109)
        'furkey': dict(pos=(0.10, -0.75, 1.30), W=64.0, size=0.40, rgb=KEYC, aim='upper'),
        # eye light: eyeballs/pupils/glints only, front upper-left where the anchor glints sit
        'eyelight': dict(pos=(-0.45, -1.00, 0.70), W=5.0, size=0.25, rgb=(1.0, 1.0, 1.0), aim='c'),
        # R3MERGE run3: face-only fill from the same upper-left-front spot (anchor face is lit from its left). The 60 mm
        # undercoat + 105 mm crown overhang the face under the 60-deg key: doubling the key (run2) lifted the arms but the
        # teal-gated face stayed at L112 vs the anchor face box L139.
        'facelight': dict(pos=(-0.45, -1.00, 0.70), W=7.0, size=0.35, rgb=KEYC, aim='c'),
        'mint': dict(pos=(-0.85, 0.70, 1.10), W=3.0, size=0.70, rgb=MINT, aim='crown'),
        # warm accent: low front-RIGHT (run4 at x 0.70 / 26 W yellowed the whole chest, fur b 152 vs 136)
        'warm': dict(
            pos=(0.80, -0.75, -0.30), W=7.0, size=0.45, rgb=WARM, aim='belly'
        ),  # R3MERGE: 5 -> 7 W (same reason)
        'warmfur': dict(pos=(0.80, -0.75, -0.30), W=13.0, size=0.45, rgb=WARM, aim='belly'),
        'tailfill': dict(pos=(-0.50, -0.85, 1.30), W=30.0, size=1.40, rgb=(1.0, 1.0, 1.0), aim='upper'),
        'rimL': dict(pos=(-0.45, 1.15, 0.70), W=6.0, size=0.35, rgb=CYAN, aim='c', glossy=False),
        'rimR': dict(pos=(0.45, 1.20, 0.50), W=4.0, size=0.30, rgb=CYAN, aim='c', glossy=False),
        'fillR': dict(pos=(1.25, -0.30, 0.55), W=0.6, size=0.80, rgb=(0.45, 0.90, 0.90), aim='c', glossy=False),
        'fillL': dict(pos=(-1.20, -0.40, 0.30), W=0.3, size=0.60, rgb=(0.40, 0.85, 1.00), aim='c', glossy=False),
    }
)
LINKED = ('warm',)  # creature minus legs/feet/toes, never the floor
FUR_ONLY = ('furkey', 'mint', 'warmfur')
TAIL_ONLY = ('tailfill',)
NO_TAIL = ('rimL', 'rimR')
EYE_ONLY = ('eyelight',)
FACE_ONLY = ('facelight',)  # R3MERGE
FACE_PARTS = ('pb_face', 'pb_orbit', 'pb_lid', 'pb_lip', 'pb_lowlip', 'pb_tooth', 'pb_tongue')
GROUND = dict(
    rgb=(0.013, 0.022, 0.030), rough=0.40, spec=0.20
)  # run6: anchor floor is a lit blue-grey (35,50,60), not black; run7/8: stepped down (row 700 (30,58,73) vs anchor (16,40,53))


def _link_to_eyes(scene, light_ob):
    _link_prefix(scene, light_ob, 'pb_eye_receivers', ('pb_eye', 'pb_pupil', 'pb_glint'))


def _link_to_face(scene, light_ob):  # R3MERGE
    _link_prefix(scene, light_ob, 'pb_face_receivers', FACE_PARTS)


def lighting(scene, centre, size, aim):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    """r2 rig builder + the EYE_ONLY class (everything else identical to the base)."""
    c = Vector(centre)
    S = float(size)
    ek = (S / S_REF) ** 2
    print('R3LIGHT lighting S=%.3f energy scale=%.3f' % (S, ek))
    aims = {
        'belly': c + Vector((0, -0.25 * S, -0.30 * S)),
        'chest': c + Vector((0, -0.30 * S, -0.15 * S)),
        'low': c + Vector((0, -0.15 * S, -0.15 * S)),
        'upper': c + Vector((0, 0, 0.15 * S)),
        'flankR': c + Vector((0.30 * S, -0.10 * S, -0.15 * S)),
        'crown': c + Vector((0, 0, 0.30 * S)),
        'c': c,
    }
    for name, L in LIGHTS.items():
        o = _area(
            scene,
            name,
            c + Vector(L['pos']) * S,
            L['W'] * ek,
            L['size'] * S,
            aims[L['aim']],
            L['rgb'],
            glossy=L.get('glossy', True),
            spread=L.get('spread'),
        )
        if name in LINKED:
            _link_to_creature(scene, o)
        elif name in FUR_ONLY:
            _link_to_fur(scene, o)
        elif name in TAIL_ONLY:
            _link_to_tail(scene, o)
        elif name in NO_TAIL:
            _link_no_tail(scene, o)
        elif name in EYE_ONLY:
            _link_to_eyes(scene, o)
        elif name in FACE_ONLY:
            _link_to_face(scene, o)  # R3MERGE


# ── floor -> backdrop blend (run6) ───────────────────────────────────────────
# The 6 m ground plane met the world gradient in a hard horizon line (row 469: world
# (10,21,28) over floor (3,5,7)); the anchor floor darkens smoothly into the backdrop.
# Beyond FLOOR_R0 the floor cross-fades to an EMISSION that evaluates the world's own
# Window-space gradient (same nodes as world()), so at the seam both sides are the same
# pixel colour; inside FLOOR_R0 the glossy floor keeps the creature's soft reflection.
FLOOR_R0, FLOOR_R1 = (
    0.70,
    1.80,
)  # m from the origin: floor ... fully backdrop (run8: fade starts nearer, the lit band behind the feet was too bright)
WORLD_RAMP = [(0.00, (0.0080, 0.0170, 0.0250)), (0.45, (0.0055, 0.0125, 0.0180)), (1.00, (0.0025, 0.0065, 0.0095))]
WORLD_WARM = (0.060, 0.050, 0.030)


def _backdrop_colour_nodes(nt):
    """Nodes reproducing world()'s colour from Window coordinates; returns the RGBA socket."""
    tc = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    e = ramp.color_ramp.elements
    e[0].position = WORLD_RAMP[0][0]
    e[0].color = (*WORLD_RAMP[0][1], 1)
    e[1].position = WORLD_RAMP[2][0]
    e[1].color = (*WORLD_RAMP[2][1], 1)
    e.new(WORLD_RAMP[1][0]).color = (*WORLD_RAMP[1][1], 1)
    powx = nt.nodes.new('ShaderNodeMath')
    powx.operation = 'POWER'
    powx.inputs[1].default_value = 3.0
    mulx = nt.nodes.new('ShaderNodeMath')
    mulx.operation = 'MULTIPLY'
    mulx.inputs[1].default_value = 0.8
    muly = nt.nodes.new('ShaderNodeMath')
    muly.operation = 'MULTIPLY'
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'ADD'
    mix.inputs['B'].default_value = (*WORLD_WARM, 1)
    nt.links.new(tc.outputs['Window'], sep.inputs['Vector'])
    nt.links.new(sep.outputs['Y'], ramp.inputs['Fac'])
    nt.links.new(sep.outputs['X'], powx.inputs[0])
    nt.links.new(powx.outputs[0], mulx.inputs[0])
    nt.links.new(mulx.outputs[0], muly.inputs[0])
    nt.links.new(sep.outputs['Y'], muly.inputs[1])
    nt.links.new(muly.outputs[0], mix.inputs['Factor'])
    nt.links.new(ramp.outputs['Color'], mix.inputs['A'])
    return mix.outputs['Result'], tc


def world(scene):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    """Same gradient as the r2 world, built from the shared node recipe."""
    w = scene.world
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_WORLD':
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_WORLD')
    bg = nt.nodes.new('ShaderNodeBackground')
    col, _ = _backdrop_colour_nodes(nt)
    nt.links.new(col, bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 1.0
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])


def _ground_material():
    m = bpy.data.materials.new('pb_ground_canon')
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    b.inputs['Base Color'].default_value = (*GROUND['rgb'], 1)
    b.inputs['Roughness'].default_value = GROUND['rough']
    if 'Specular IOR Level' in b.inputs:
        b.inputs['Specular IOR Level'].default_value = GROUND['spec']
    col, tc = _backdrop_colour_nodes(nt)
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 1.0
    nt.links.new(col, em.inputs['Color'])
    ln = nt.nodes.new('ShaderNodeVectorMath')
    ln.operation = 'LENGTH'
    nt.links.new(tc.outputs['Object'], ln.inputs[0])
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.interpolation_type = 'SMOOTHSTEP'
    mr.inputs['From Min'].default_value = FLOOR_R0
    mr.inputs['From Max'].default_value = FLOOR_R1
    nt.links.new(ln.outputs['Value'], mr.inputs['Value'])
    mix = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(mr.outputs['Result'], mix.inputs['Fac'])
    nt.links.new(b.outputs['BSDF'], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    return m


_light_post_r2 = light_post


def light_post(scene, result, PB):
    _light_post_r2(scene, result, PB)  # bounds, bokeh dots, glow point (unchanged)
    g = _ob('pb_ground')
    if g is not None:
        g.data.materials.clear()
        g.data.materials.append(_ground_material())


# ═════════════════════════════════════════════════════════════════════════════
# R4 FUR — head coverage (critic's flag), 3D eye exclusion, eye-repel forces
#
# WHY THE HEAD WAS BALD. skin's fur_density carved a circle (R_c 0.074) + a V, and
# _crown_len zeroed density within an (x,z) radius 0.050 of each eye CENTRE. But the eye
# centre sits 29 mm IN FRONT of the body surface and the head curves away behind it: a
# root on the temple at x 0.115 is 81 mm from the eye centre in 3D (the eyeball is 53 mm)
# yet only 40 mm away in (x,z), so it was zeroed. With eye_sep 0.075 + 0.050 = 0.125 and
# body_rx 0.138 that is the WHOLE side of the head at eye height. The exclusion is now
# a 3D distance from the eye centre (only roots that would actually grow out of the
# eyeball / socket are dropped) and the bald patch is the anchor's inverted triangle:
# forehead strip between the eyes, wide at eye height, apex under the mouth.
# ═════════════════════════════════════════════════════════════════════════════
R4F = {
    'eye_r0': 0.054,
    'eye_r1': 0.062,  # 3D distance from the eye centre: density 0 -> 1   # run3: 0.056/0.068 left a 10 mm teal band above/beside the eyeball
    'eye_len_r': 0.110,
    'eye_len_min': 0.50,  # hair length 0.5x at eye_r1, 1.0 at eye_len_r
    'feather': 0.014,  # ~10% of head radius: strands fringe onto the patch edge
    # bald patch as (z, half-width) knots, body-local metres, top -> chin. Eye rims span
    # x +-0.128 (sep 0.075 + r 0.053), eye tops at z 0.113, mouth at z ~0, beak bottom -0.016.
    'tri': [
        (0.150, 0.012),
        (0.113, 0.030),
        (0.060, 0.098),
        (0.010, 0.080),
        (-0.004, 0.050),
        (-0.036, 0.0),
    ],  # run3: narrower forehead strip (anchor: ~0.35 eye-r half-width at its top)
    'cheek_band': 0.050,
    'cheek_min': 0.50,  # short fur beside the mouth / under the eyes
    'brow_band': 0.060,
    'brow_min': 0.50,  # short fur along the forehead strip
    'eye_force': 0.10,
    'eye_force_dist': 0.13,  # repel point force at each eye centre
}


def _eye_centres_local(p, PB):
    """Body-local eye centres exactly as seat_eyes will place them (called before it runs)."""
    er = p['eye_r']
    z = p['body_lift'] + p['eye_z']
    ti, up = math.radians(EYE_TOE_IN), math.radians(EYE_UP)
    out = []
    for sx in (-1, 1):
        sp, n = _face_point_normal(sx * p['eye_sep'], z, p, PB)
        a = Vector((-sx * math.sin(ti), -math.cos(ti) * math.cos(up), math.sin(up))).normalized()
        c = sp + a * ((EYE_PROUD - 1.0) * er)
        out.append(Vector((c.x, c.y, c.z - p['body_lift'])))
    return out


def _tri_s(x, z):
    """Signed 'inside' measure of the bald triangle (>0 inside), horizontal distance to the edge."""
    T = R4F['tri']
    zt, ht = T[0]
    zb, hb = T[-1]
    if z > zt:
        return -(z - zt) - max(0.0, abs(x) - ht)
    if z < zb:
        return -(zb - z) - abs(x)
    for (z1, h1), (z0, h0) in zip(T, T[1:]):
        if z0 <= z <= z1:
            t = (z - z0) / (z1 - z0) if z1 > z0 else 0.0
            return h0 + (h1 - h0) * t - abs(x)
    return -1.0


_R4_EYES = {}


# R4FUR: replaces skin's circle+V mask
def fur_density(body, p):  # noqa: F811  cumulative look-dev file: later section shadows on purpose (see module docstring)
    PB = _R4_EYES.get('PB')
    eyes = _eye_centres_local(p, PB)
    _R4_EYES['c'] = eyes
    vg = body.vertex_groups.get('fur_density') or body.vertex_groups.new(name='fur_density')
    frL = body.vertex_groups.get('face_fringe_l') or body.vertex_groups.new(name='face_fringe_l')
    frR = body.vertex_groups.get('face_fringe_r') or body.vertex_groups.new(name='face_fringe_r')
    vgl = body.vertex_groups.get('fur_len') or body.vertex_groups.new(name='fur_len')
    F = R4F['feather']
    r0, r1 = R4F['eye_r0'], R4F['eye_r1']
    n_bald = 0
    for v in body.data.vertices:
        x, y, z = v.co.x, v.co.y, v.co.z
        if y > 0.02:
            s, w, we = -1.0, 1.0, 1.0
        else:
            s = _tri_s(x, z)
            w = min(1.0, max(0.0, 0.5 - s / F))
            d3 = _eye_dist(v.co, eyes)
            we = min(1.0, max(0.0, (d3 - r0) / (r1 - r0)))
            w *= we
        if w < 0.5:
            n_bald += 1
        vg.add([v.index], w, 'REPLACE')
        vgl.add([v.index], 1.0, 'REPLACE')  # the length field is written by _crown_len (R4)
        if y < 0.0 and z < 0.040:
            f = max(0.0, 1.0 - abs(s - 0.012) / 0.016)
            f *= min(1.0, max(0.0, (0.040 - z) / 0.030))
            if z < 0.0:
                f *= min(1.0, max(0.0, (abs(x) - 0.018) / 0.012))
            f *= we  # never root the fringe inside the eyeball
        else:
            f = 0.0
        frL.add([v.index], f if x < 0 else 0.0, 'REPLACE')
        frR.add([v.index], f if x >= 0 else 0.0, 'REPLACE')
    print(
        'R4FUR fur_density: %d / %d body verts bald; eyes body-local %s'
        % (n_bald, len(body.data.vertices), [tuple(round(a, 3) for a in c) for c in eyes])
    )


def _crown_len(p):  # R4FUR: replaces the r2 length field (same crown/under/arm terms)
    body = _ob('pb_body')
    vgl = body.vertex_groups.get('fur_len')
    if vgl is None:
        return
    eyes = _R4_EYES.get('c') or _eye_centres_local(p, _R4_EYES.get('PB'))
    z0, z1, mn = CROWN['z0'], CROWN['z1'], CROWN['min']
    r1, lr, lmin = R4F['eye_r1'], R4F['eye_len_r'], R4F['eye_len_min']
    for v in body.data.vertices:
        x, y, z = v.co.x, v.co.y, v.co.z
        f = 1.0
        if y < 0.0:
            d3 = _eye_dist(v.co, eyes)
            if d3 < lr:
                t = max(0.0, min(1.0, (d3 - r1) / (lr - r1)))
                f *= lmin + (1.0 - lmin) * t
        if y < -0.02:
            s = _tri_s(x, z)
            if s < 0.0:
                if z < 0.030:  # run2: was 0.060 -- the temple's body hair was cut to ~46 mm behind a 41 mm-proud cap
                    near = max(0.0, 1.0 + s / R4F['cheek_band'])
                    f *= 1.0 - (1.0 - R4F['cheek_min']) * near
                else:
                    near = max(0.0, 1.0 + s / R4F['brow_band'])
                    f *= 1.0 - (1.0 - R4F['brow_min']) * near
        if z > z0:
            t = min(1.0, (z - z0) / (z1 - z0))
            t = t * t * (3 - 2 * t)
            f *= 1.0 - (1.0 - mn) * t
        if z < UNDER['z0']:
            t = min(1.0, (UNDER['z0'] - z) / (UNDER['z0'] - UNDER['z1']))
            t = t * t * (3 - 2 * t)
            f *= 1.0 - (1.0 - UNDER['min']) * t
        A = ARM_ZONE
        if y < A['y_max'] and A['z_lo'] < z < A['z_top'] and abs(x) > A['x0']:
            tx = min(1.0, (abs(x) - A['x0']) / (A['x1'] - A['x0']))
            tz = min(1.0, (A['z_top'] - z) / 0.03)
            ty = min(1.0, (A['y_max'] - y) / 0.03)
            f *= 1.0 - (1.0 - A['min']) * tx * tz * ty
        if f >= 1.0:
            continue
        try:
            w = vgl.weight(v.index)
        except RuntimeError:
            w = 1.0
        vgl.add([v.index], w * f, 'REPLACE')


def _eye_forces(scene):
    """Repel point force at each eye centre: tufts around the socket radiate AWAY from the
    rim (the anchor's sunflower around each eye) instead of streaking across the cornea."""
    col = _WIND.get('col')
    if col is None:
        return
    for side in ('l', 'r'):
        eye = _ob('pb_eye_' + side)
        if eye is None:
            continue
        bpy.ops.object.effector_add(type='FORCE', location=tuple(eye.location))
        g = bpy.context.active_object
        g.name = 'pb_eye_repel_' + side
        g.field.strength = R4F['eye_force']
        g.field.falloff_power = 0.0
        g.field.use_max_distance = True
        g.field.distance_max = R4F['eye_force_dist']
        g.field.flow = 0.0
        g.field.noise = 0.0
        g.hide_render = True
        for c in list(g.users_collection):
            c.objects.unlink(g)
        col.objects.link(g)
    print('R4FUR eye repel forces strength %.3f reach %.3f' % (R4F['eye_force'], R4F['eye_force_dist']))


_R3_pre_build = pre_build
_R3_post_build = post_build


def pre_build(PB):
    _R4_EYES['PB'] = PB
    _R3_pre_build(PB)


def post_build(scene, result, PB):
    _R3_post_build(scene, result, PB)
    _eye_forces(scene)
    _cap_fur(scene, result, PB, dict(_P))
    _mound_fur(dict(_P))
    bpy.context.view_layer.update()


# ── run2: fur ROOTED ON THE FACE CAP ──────────────────────────────────────────
# The cap (pb_face, r 0.130 x (1, 1.6, 0.75)) stands 41 mm proud of the body at the temple
# and ~50 mm above the brow, so body-rooted hair shortened to 0.5x never reaches its
# surface: run1 fixed the density and the head stayed a bare teal balloon. The cap gets
# its own tufts + undercoat, masked by the same triangle + 3D eye exclusion.
CAP_HAIR = {
    'len': 0.065,
    'count': 2500,
    'child': 20,  # run3: 900 -> 2500, the mask keeps ~1/8 of the cap
    'len_edge': 0.60,
    'edge_band': 0.035,  # short at the patch edge, full 35 mm out
    'len_eye_r': 0.100,
    'len_eye_min': 0.70,  # short beside the socket
    'under': {'len': 0.035, 'count': 1600, 'child': 20, 'thick': 0.0004},
}


def _cap_fur(scene, result, PB, p):
    face = _ob('pb_face')
    body = _ob('pb_body')
    if face is None or body is None:
        return
    C = CAP_HAIR
    # bake the anisotropic object scale into the mesh so hair_length is metres in every direction
    sx, sy, sz = face.scale
    me = face.data
    for v in me.vertices:
        v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz))
    face.scale = (1.0, 1.0, 1.0)
    me.update()
    bpy.context.view_layer.update()
    eyes = _R4_EYES.get('c') or _eye_centres_local(p, PB)
    off = Vector(face.location) - Vector(body.location)  # cap centre, body-local
    vgd = face.vertex_groups.get('cap_density') or face.vertex_groups.new(name='cap_density')
    vgl = face.vertex_groups.get('cap_len') or face.vertex_groups.new(name='cap_len')
    rx, ry, rz = p['body_rx'], p['body_ry'], p['body_rz']
    F = R4F['feather']
    r0, r1 = R4F['eye_r0'], R4F['eye_r1']
    n_on = 0
    for v in me.vertices:
        q = off + v.co
        if (q.x / rx) ** 2 + (q.y / ry) ** 2 + (q.z / rz) ** 2 < 0.97:  # buried in the body
            vgd.add([v.index], 0.0, 'REPLACE')
            vgl.add([v.index], 1.0, 'REPLACE')
            continue
        s = _tri_s(q.x, q.z)
        w = min(1.0, max(0.0, 0.5 - s / F))
        d3 = _eye_dist(q, eyes)
        we = min(1.0, max(0.0, (d3 - r0) / (r1 - r0)))
        w *= we
        f = 1.0
        if d3 < C['len_eye_r']:
            f *= C['len_eye_min'] + (1.0 - C['len_eye_min']) * max(0.0, min(1.0, (d3 - r1) / (C['len_eye_r'] - r1)))
        if s < 0.0:
            f *= 1.0 - (1.0 - C['len_edge']) * max(0.0, 1.0 + s / C['edge_band'])
        vgd.add([v.index], w, 'REPLACE')
        vgl.add([v.index], f, 'REPLACE')
        if w > 0.5:
            n_on += 1
    ps = _body_hair(face, C['len'], C['count'], C['child'], 23, p['hair_thick'], 'cap_density')
    ps.name = 'pb_cap_tufts'
    ps.vertex_group_length = 'cap_len'
    nf = ps.settings.normal_factor
    ps.settings.object_align_factor = (
        0.0,
        C.get('align_back', 0.0) * nf,
        0.0,
    )  # run6: x normal_factor (velocity units; run5's raw 0.35 = a 1.4 m beam)
    print(
        'R4FUR cap tufts: hair_length %.4f normal_factor %.5f align %.5f'
        % (ps.settings.hair_length, nf, ps.settings.object_align_factor[1])
    )
    psu = _undercoat(face, 'cap_density', seed=24, U=C['under'])
    psu.name = 'pb_cap_under'
    psu.vertex_group_length = 'cap_len'
    print(
        'R4FUR cap fur: %d / %d cap verts furred; %d x %d tufts %.3f m + %d x %d undercoat %.3f m'
        % (
            n_on,
            len(me.vertices),
            C['count'],
            C['child'],
            C['len'],
            C['under']['count'],
            C['under']['child'],
            C['under']['len'],
        )
    )


# ── run3: fur ON THE ORBITAL MOUNDS ───────────────────────────────────────────
# pb_orbit_l/r are oblate skin ellipsoids (1.15 r lateral x 0.85 r deep) wrapped round each
# eye; their skirts are the teal cones seen behind the eye at 45 deg / in profile. The anchor
# has fur immediately behind the bezel, so the mound grows short tufts wherever it is more
# than MOUND_HAIR['rho0'] from the gaze axis (the eye leaves the mound at rho 0.94 r = 0.050).
MOUND_HAIR = {'rho0': 0.053, 'rho1': 0.058, 'len': 0.035, 'count': 700, 'child': 16}


def _mound_fur(p):
    M = MOUND_HAIR
    for side in ('l', 'r'):
        ob = _ob('pb_orbit_' + side)
        if ob is None:
            continue
        vg = ob.vertex_groups.get('orbit_density') or ob.vertex_groups.new(name='orbit_density')
        vgl = ob.vertex_groups.get('orbit_len') or ob.vertex_groups.new(name='orbit_len')
        sx = -1.0 if side == 'l' else 1.0  # outer (temporal) side of the socket
        n_on = 0
        for v in ob.data.vertices:
            rho = math.hypot(v.co.x, v.co.z)  # local Y is the gaze axis (PB._sphere, rotated by q)
            w = min(1.0, max(0.0, (rho - M['rho0']) / (M['rho1'] - M['rho0'])))
            vg.add([v.index], w, 'REPLACE')
            # run8: tufts on the OUTER half root just past the eye's lateral extreme and point at the profile
            # camera, hiding the eye in side view (anchor: the whole eye shows in profile) -> half length there
            outer = max(0.0, sx * v.co.x / rho) if rho > 1e-6 else 0.0
            vgl.add([v.index], 1.0 - M.get('outer_len_cut', 0.5) * outer, 'REPLACE')
            if w > 0.5:
                n_on += 1
        ps = _body_hair(
            ob, M['len'], M['count'], M['child'], 31 if side == 'l' else 32, p['hair_thick'], 'orbit_density'
        )
        ps.name = 'pb_orbit_tufts'
        ps.vertex_group_length = 'orbit_len'
        ps.settings.object_align_factor = (
            0.0,
            M.get('align_back', 0.0) * ps.settings.normal_factor,
            0.0,
        )  # local +Y = away from the gaze; velocity units (run6)
        print(
            'R4FUR mound fur %s: %d / %d verts furred, %d x %d tufts %.3f m'
            % (side, n_on, len(ob.data.vertices), M['count'], M['child'], M['len'])
        )


# ── run4: TUFT SHAPE — fat pointed feathers, not fuzz ──────────────────────────
# The anchor's coat is made of discrete clumps ~15-25 px wide at 1024 (11-16 mm), each a solid
# creamy body tapering to a point, with dark valleys between. r3's 2600 x 18 strands at a 4.5 mm
# child radius maximised the perimeter metric but reads as cotton/straw. Here: fewer parents,
# twice the children (thinner) in a 5.5 mm disc, clump 1.0 with a POSITIVE shape (children stay
# spread until near the tip, then pinch), a shorter undercoat so the tufts stand ~65 mm proud.
TUFT4 = {
    'clump': 1.0,
    'shape': 0.20,
    'radius': 0.0065,
    'len_random': 0.25,  # run7: midpoint -- run5 (0.10/5.5 mm) needles, front rough +26%; run6 (0.30/8.5 mm) fused cotton, -24%   # run6: 0.10/5.5 mm were solid but NEEDLES (3-4 mm visible); anchor feathers are 15-25 mm wide   # run5: shape 0.45 -> 0.10 (run4 tips were splayed brushes; the anchor's taper is ~linear to a point)
    'rough1': 0.025,
    'rough2': 0.005,
    'kink_amp': 0.03,
    'kink_freq': 1.5,
    'tip': 0.15,
}  # run5: half the wobble, no endpoint roughness -> no flyaways on the outline
R4_HAIR = {
    'hair_count': 1800,
    'hair_child': 80,
    'hair_thick': 0.00045,  # run6: 96 children fill the wider disc     # run5: 36 x 0.7 mm showed fibres inside every clump; 72 x 0.45 mm reads as a solid body
    'tail_hair_len': 0.050,
    'tail_hair_count': 1000,
    'tail_hair_child': 80,
}
PARAMS.update(R4_HAIR)
UNDERCOAT2.update({'len': 0.038})  # run5: 0.045 still filled the valleys between tufts
CAP_HAIR.update(
    {'child': 80, 'align_back': 0.15, 'len': 0.050}
)  # run8: still a faint ridge over the crown at 45 deg   # run7: the 65 mm cap tufts swept back stood up as a mohawk ridge over the crown (q45)   # run5: temple tufts sweep BACK along the head (profile: they pointed at the camera and fuzzed over the eye)
MOUND_HAIR.update({'child': 56, 'align_back': 0.70})

_R3_tuft_settings = _tuft_settings


def _tuft_settings(s, length, thick, clump=None, shape=None, radius=None):
    T = TUFT4
    _R3_tuft_settings(s, length, thick, T['clump'], T['shape'], T['radius'])
    s.length_random = T['len_random']
    s.roughness_1 = length * T['rough1']
    s.roughness_endpoint = 0.0
    s.roughness_2 = length * T['rough2']
    s.kink_amplitude = length * T['kink_amp']
    s.kink_frequency = T['kink_freq']
    s.tip_radius = thick * T['tip']


# run7: the anchor fur is MINT (Lab a 117 vs run6 127 at equal L); take red out of the tip and root
FUR_COL.update({'root': (0.70, 0.95, 0.87), 'tip': (0.86, 0.995, 0.955)})


# ═════════════════════════════════════════════════════════════════════════════
# R4SKIN — face patch, skin, mouth (critic round 3: face washed out to a pale grey-teal
# with a plastic sheen; lips pale beige).  Everything below OVERRIDES the R3SKIN names
# above: skin_post()/build_mouth_beak() look these up at call time.
#   * face albedo: ONE flat teal fitted to the between-eyes target sRGB (80,172,160) under
#     the harness rig (measured with probe.py after every run), a MILD z-gradient only
#     (brow x1.3, chin x0.8) — r3's pale sea-foam brow + 0.45 clearcoat + spec 0.75 + mint
#     SSS is what lifted the face to #BBD5CC.
#   * roughness 0.55, spec 0.30, coat 0, SSS 0.12 with a WARM radius (the anchor glow is
#     warm under the beak, not mint), goosebump bump kept.
#   * the dense emissive glitter is gone; ~8 dew droplets (2-3.5 mm = 1-1.3 % of the 260 mm
#     face) as glossy beads on the face surface (pass_index face, so the masks are unchanged).
#   * lips: albedo pulled DOWN and saturated so Filmic stops desaturating them to beige;
#     roughness 0.20, coat 0.
# ═════════════════════════════════════════════════════════════════════════════
FACE_MID = (
    0.012,
    0.068,
    0.077,
)  # run3: solved from run1/run2 (Filmic inverted per channel: rendered = A*E + S, E=(3.5,4.0,2.85), S=(0.105,0.14,0.12) = the WHITE sheen) with the sheen cut+tinted below
FACE_BROW_MUL = (1.35, 1.15, 1.10)  # run3: milder (run2 forehead #A5D6C8 vs between-eyes #7EC0B0)
FACE_CHIN_MUL = (
    0.82,
    0.92,
    0.97,
)  # run4: (0.70,0.85,0.95) left the cheeks under the beak a dull deep teal; cell_11 cheek #5CB0AA is lighter than the bridge
FACE_GRAD_Z = (-0.055, 0.075)  # face-LOCAL z: between-eyes (+0.024) sits at ~0.6
FACE_ROUGH = 0.55
FACE_SPEC_TINT = (0.30, 1.00, 0.90)  # run3: dielectric sheen colour
FACE_SPEC = 0.30  # run3: kept at 0.30 but the sheen is TINTED teal (FACE_SPEC_TINT): the white sheen alone (S_R 0.105 lin) exceeded the anchor R (0.0745 lin)
FACE_SSS = (
    0.15  # run4: 0.12 -> 0.15, the anchor mask has a soft glow (with the tinted sheen this no longer lifts it grey)
)
FACE_SSS_RADIUS = (1.0, 0.70, 0.50)
FACE_SSS_SCALE = 0.004
BUMP_SCALE = 300.0
BUMP_STRENGTH = 0.22
BUMP_DIST = 0.0015
# dew droplets: (x, z_rel_to_body_lift, radius) in metres, body space; all on bald skin, clear of
# the eye rings (>= 0.058 from an eye centre) and the beak (x +-0.034, z -0.016..+0.020)
DROPS = [
    (0.000, 0.068, 0.0038),
    (-0.006, 0.041, 0.0032),
    (0.009, 0.029, 0.0025),
    (-0.026, 0.098, 0.0035),
    (0.031, 0.094, 0.0028),
    (-0.040, -0.004, 0.0038),
    (0.041, -0.006, 0.0030),
    (0.006, -0.027, 0.0032),
]  # run4: x1.25 (water beads on dark teal read as specks at 2-3 mm)
DROP_RGB = (
    0.92,
    0.97,
    0.96,
)  # run3: water — transmissive beads refracting the skin (run1/2 opaque pale beads read as pimples)
DROP_SINK = 0.45  # fraction of the radius below the surface
BEAK_RGB = (
    0.121,
    0.021,
    0.003,
)  # run4: solved from run1/run2 (lip E=(3.6,5.0,5.2), S=(0.08,0.027,0.022)) for the target #B96E32; run2/3 (0.15,0.032,0.007) rendered #C28144
LOWLIP_RGB = (0.100, 0.017, 0.0025)  # run4: a step darker than the upper lip
LIP_ROUGH = 0.20
# run4: sparse gold flecks — cells ~12 mm (scale 80), dot radius 0.06 of a cell (~1.4 mm), a coarse noise gate keeping
# ~1/3 of the cells, only on the cheeks/brow (face-local z above -0.02); r3's 320-scale x 0.60-gate x 1.6 emission was glitter
FLECK = {
    'cell_scale': 80.0,
    'dot_r': 0.085,
    'noise_scale': 20.0,
    'noise_gt': 0.66,
    'z0': -0.030,
    'z1': -0.010,  # run5: dot_r 0.06 -> 0.085, emit 0.8 -> 1.1 (run4's 1.4 mm flecks were invisible at 1024 px)
    'rgb': (0.95, 0.62, 0.12),
    'emit': 1.1,
}
ORBIT_TINT = 0.85  # run4: 0.62 x the (now much darker) face albedo made the sockets a dull dark band under each eye
ORBIT_AO_FLOOR = 0.55  # run7: 0.30 -> 0.55 — MEASURED INERT (below-eyes probe (97,116,74) unchanged, run5 vs run7 crops identical): the dark band under each eye is fur/bezel shadow, not the mound's AO. Left as rendered in run7.
LIP_SPEC = 0.45
LIP_SSS = 0.10


def face_material(m):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    nt, b = _principled_reset(m)
    n, L = nt.nodes, nt.links
    b.inputs['Roughness'].default_value = FACE_ROUGH
    b.inputs['Specular IOR Level'].default_value = FACE_SPEC
    b.inputs['Subsurface Weight'].default_value = FACE_SSS
    b.inputs['Subsurface Radius'].default_value = FACE_SSS_RADIUS
    b.inputs['Subsurface Scale'].default_value = FACE_SSS_SCALE
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Coat Weight'].default_value = 0.0
    b.inputs['Sheen Weight'].default_value = 0.0
    b.inputs['Specular Tint'].default_value = (*FACE_SPEC_TINT, 1.0)  # run3: teal sheen, not white
    tc = n.new('ShaderNodeTexCoord')
    sep = n.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Object'], sep.inputs[0])
    gz = n.new('ShaderNodeMapRange')
    gz.interpolation_type = 'SMOOTHSTEP'
    gz.inputs['From Min'].default_value = FACE_GRAD_Z[0]
    gz.inputs['From Max'].default_value = FACE_GRAD_Z[1]
    L.new(sep.outputs['Z'], gz.inputs['Value'])
    chin = tuple(c * k for c, k in zip(FACE_MID, FACE_CHIN_MUL))
    brow = tuple(c * k for c, k in zip(FACE_MID, FACE_BROW_MUL))
    fmix = n.new('ShaderNodeMix')
    fmix.data_type = 'RGBA'
    fmix.blend_type = 'MIX'
    fmix.inputs[6].default_value = (*chin, 1.0)
    fmix.inputs[7].default_value = (*brow, 1.0)
    L.new(gz.outputs['Result'], fmix.inputs[0])
    L.new(fmix.outputs[2], b.inputs['Base Color'])
    # run4: SPARSE gold flecks (anchor temple/cheek speckle) — large cells, tiny dots, low emission
    fv = n.new('ShaderNodeTexVoronoi')
    fv.voronoi_dimensions = '3D'
    fv.feature = 'F1'
    fv.inputs['Scale'].default_value = FLECK['cell_scale']
    fv.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], fv.inputs['Vector'])
    flt = n.new('ShaderNodeMath')
    flt.operation = 'LESS_THAN'
    flt.inputs[1].default_value = FLECK['dot_r']
    L.new(fv.outputs['Distance'], flt.inputs[0])
    fn = n.new('ShaderNodeTexNoise')
    fn.inputs['Scale'].default_value = FLECK['noise_scale']
    fn.inputs['Detail'].default_value = 1.0
    L.new(tc.outputs['Object'], fn.inputs['Vector'])
    fgt = n.new('ShaderNodeMath')
    fgt.operation = 'GREATER_THAN'
    fgt.inputs[1].default_value = FLECK['noise_gt']
    L.new(fn.outputs['Fac'], fgt.inputs[0])
    fzg = n.new('ShaderNodeMapRange')
    fzg.interpolation_type = 'SMOOTHSTEP'
    fzg.inputs['From Min'].default_value = FLECK['z0']
    fzg.inputs['From Max'].default_value = FLECK['z1']
    L.new(sep.outputs['Z'], fzg.inputs['Value'])
    f1 = n.new('ShaderNodeMath')
    f1.operation = 'MULTIPLY'
    L.new(flt.outputs[0], f1.inputs[0])
    L.new(fgt.outputs[0], f1.inputs[1])
    fl = n.new('ShaderNodeMath')
    fl.operation = 'MULTIPLY'
    L.new(f1.outputs[0], fl.inputs[0])
    L.new(fzg.outputs['Result'], fl.inputs[1])
    gmix = n.new('ShaderNodeMix')
    gmix.data_type = 'RGBA'
    gmix.blend_type = 'MIX'
    L.new(fmix.outputs[2], gmix.inputs[6])
    gmix.inputs[7].default_value = (*FLECK['rgb'], 1.0)
    L.new(fl.outputs[0], gmix.inputs[0])
    for lk in [l for l in L if l.to_node == b and l.to_socket.name == 'Base Color']:
        L.remove(lk)
    L.new(gmix.outputs[2], b.inputs['Base Color'])
    b.inputs['Emission Color'].default_value = (*FLECK['rgb'], 1.0)
    fem = n.new('ShaderNodeMath')
    fem.operation = 'MULTIPLY'
    fem.inputs[1].default_value = FLECK['emit']
    L.new(fl.outputs[0], fem.inputs[0])
    L.new(fem.outputs[0], b.inputs['Emission Strength'])
    # goosebump micro-bump (kept from r3)
    vb = n.new('ShaderNodeTexVoronoi')
    vb.voronoi_dimensions = '3D'
    vb.feature = 'SMOOTH_F1'
    vb.inputs['Scale'].default_value = BUMP_SCALE
    vb.inputs['Smoothness'].default_value = 0.35
    L.new(tc.outputs['Object'], vb.inputs['Vector'])
    bump = n.new('ShaderNodeBump')
    bump.invert = True
    bump.inputs['Strength'].default_value = BUMP_STRENGTH
    bump.inputs['Distance'].default_value = BUMP_DIST
    L.new(vb.outputs['Distance'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    print(
        'R4SKIN face albedo mid=%s brow=%s chin=%s rough %.2f spec %.2f sss %.2f'
        % (
            FACE_MID,
            tuple(round(v, 3) for v in brow),
            tuple(round(v, 3) for v in chin),
            FACE_ROUGH,
            FACE_SPEC,
            FACE_SSS,
        )
    )
    return m


def beak_material(m):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    nt, b = _principled_reset(m)
    b.inputs['Base Color'].default_value = (*BEAK_RGB, 1.0)
    b.inputs['Roughness'].default_value = LIP_ROUGH
    b.inputs['Specular IOR Level'].default_value = LIP_SPEC
    b.inputs['Subsurface Weight'].default_value = LIP_SSS
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.40, 0.20)
    b.inputs['Subsurface Scale'].default_value = 0.004
    b.inputs['Coat Weight'].default_value = 0.0
    b.subsurface_method = 'RANDOM_WALK'
    return m


def _drop_material():
    m = bpy.data.materials.get('pb_drop')
    if m is None:
        m = bpy.data.materials.new('pb_drop')
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        b.inputs['Base Color'].default_value = (*DROP_RGB, 1.0)
        b.inputs['Roughness'].default_value = 0.02
        b.inputs['Specular IOR Level'].default_value = 0.5
        b.inputs['Transmission Weight'].default_value = 1.0  # run3: water bead
        b.inputs['IOR'].default_value = 1.33
        b.inputs['Coat Weight'].default_value = 0.0
    return m


def add_droplets(scene, result, PB, p):
    dm = _drop_material()
    for k, (x, zr, r) in enumerate(DROPS):
        z = p['body_lift'] + zr
        try:
            P_, n_ = _face_point_normal(x, z, p, PB)
        except ValueError as e:
            print('R4SKIN droplet %d skipped: %s' % (k, e))
            continue
        c = P_ + n_ * (r * (1.0 - DROP_SINK))
        ob = PB._sphere('pb_face_drop_%d' % k, tuple(c), (r, r * 0.85, r), scene, dm, segs=16, rings=8, idx='face')
        result['parts'].append(ob)
    print('R4SKIN %d dew droplets placed' % len(DROPS))


_post_build_fur4 = post_build


def post_build(scene, result, PB):
    _post_build_fur4(scene, result, PB)
    add_droplets(scene, result, PB, dict(_P))
    bpy.context.view_layer.update()


# ═════════════════════════════════════════════════════════════════════════════
# R4FORM — proportions + tail + eye seating (appended on top of r3_merge/merge.py; every
# name below shadows the base definition because pre_build/post_build look them up at call
# time).
#
# MEASURED FIRST (r4_form/_sil.py): the harness's anchor masks are Otsu on V, so they DROP
# the dark legs/feet and the shadowed lower tail — anchor h = tail tip .. lit fur hem (733 px
# of a 788/798 px tip-to-toe creature), while the mesh alpha is tip-to-toe. Any visible leg
# therefore costs aspect and tail_above against the anchor numbers. And tail_above counts
# the crown's own narrow rows: front body_top is 65 px under the crown top on the anchor,
# 104 px on run4 — the crown was domed and the tail thin beside it.
#
# * BODY: rounder (rz/rx 1.27 -> 1.16, ry 0.125 -> 0.145: the anchor's side ball is 560x560,
#   run4's was 490x590) and LIFTED 0.205 -> 0.240 so a sliver of green leg + the whole foot
#   show under the hem (anchor: 8% of the height under the lit hem in profile).
# * TAIL: the S of anchor_side — leaves the LOWER back going back and down (the base J left
#   at mid-height), lowest core point 0.11 above the floor, column at y 0.46 bulging out at
#   the lower-mid, bowing toward the body at 2/3 height, tip curling back out and up to
#   z_rel +0.36 (base +0.29). Fattest at 45% (r 0.066 core), real taper over the top 35%.
#   The bands CONSTRICT the tube (r x 0.85) and halve the tuft length, so the white segments
#   read as fat rings between them — the caterpillar look.
# * EYES (critic): sunk from 0.65 r to 0.55 r proud of the face point, 1.1x bigger, the
#   orbital mound enlarged (1.35 x 0.95 r) and shifted UP 0.28 r so it overhangs the top of
#   the eye like a brow and recedes under it; the bezel is an ellipse-tube that projects
#   FORWARD at the top (hood, 0.20 r axial) and is wide-but-flat at the bottom (ledge). The
#   eyeballs are aimed at the camera per view, clamped to 24 deg off the nominal gaze.
# ═════════════════════════════════════════════════════════════════════════════
R4 = {
    'body_rx': 0.156,
    'body_ry': 0.145,
    'body_rz': 0.165,  # run4: rx 0.156; run2: rx +0.010 (front w), lift 0.240 -> 0.228 (front h)
    'body_lift': 0.222,  # run3: -6 mm (front h)
    'leg_r0': 0.034,
    'leg_r1': 0.028,
    'foot_r': 0.040,
    'foot_sep': 0.082,
    'foot_fwd': -0.028,
    'toe_len': 0.040,
    'toe_r': 0.016,
    'toe_gap': 0.030,  # run5: longer toes (frog foot, not three balls)
    'arm_len': 0.110,
    'arm_drop': 58.0,  # run4: +5 mm / -2 deg   # run2: hands a little outside the fur edge (anchor 1.07 half-widths) -> front w
    # run2: tip 0.36 -> 0.32 (side tail_above +13% -> ~0), tighter J (lowest point 0.30 back, not 0.33)
    # run3: column 15 mm further out (-0.38, front w) and the J tighter/higher (the fat floor-hugging base
    # filled the notch: side solidity +16%); tip curls out a little more
    'tail_knots': [
        (0.000, 0.050, -0.070),
        (-0.085, 0.170, -0.115),
        (-0.205, 0.280, -0.120),
        (-0.320, 0.390, -0.075),
        (-0.375, 0.457, 0.020),
        (-0.380, 0.462, 0.115),  # run5: mid-column bows out 12 mm (anchor_side bulge; deeper notch)
        (-0.365, 0.430, 0.205),
        (-0.355, 0.450, 0.278),
        (-0.372, 0.492, 0.330),
    ],  # run4: tip +10 mm (side tail_above -5.6%)
    'tail_profile': [
        (0.00, 0.038),
        (0.15, 0.044),
        (0.30, 0.056),
        (0.45, 0.070),
        (0.60, 0.060),  # run4: J slimmer still (side solidity); run3: slimmer base
        (0.72, 0.046),
        (0.82, 0.034),
        (0.90, 0.022),
        (0.96, 0.012),
        (1.0, 0.006),
    ],
    'tail_cap': 0.10,
    'eye_r': 0.058,
    'pupil_r': 0.0295,
    'glint_r': 0.011,
    # ONLY for PB.build(check=True) with the stock bead tail: the Bezier scales with (body_ry, body_rz), so the
    # same 40 beads spread 30% further and the r 0.007 tip beads stop touching. The overlay's tube ignores it.
    'tail_segs': 56,
}
PARAMS.update(R4)

TAIL_CONSTRICT = 0.85  # tube radius factor on a mint band
TAIL_BAND_LEN = 0.55  # tuft length factor on a mint band
EYE_PROUD = 0.45  # front pole 0.45 r past the face surface point (was 0.65; run2 0.55, run3 0.50)
EYE_DEPTH = 0.62  # run4: the eyeball is OBLATE — this x eye_r along the gaze axis; the front disc is unchanged
EXIT_RHO = 0.93  # the mound passes through the eye at this rho (the limbal ring's outer edge)
ORBIT_R, ORBIT_B = (
    1.10,
    0.55,
)  # run5: B 0.55 so the lens reaches the eye's back pole (run4's 0.45 left the outer-bottom exit at 139 deg); run4: B 0.45 on the oblate eye; run3: a tight lens hugging the eye (run2's 1.20x0.70 still a dome in profile); run2: 1.35x0.95 was a second dome in profile; flatter lens, the up-shift makes the brow
MOUND_UP = 0.20  # x er: mound centre shifted toward the brow
HOOD_AX_TOP, HOOD_AX_BOT = (
    0.12,
    0.05,
)  # run2: 0.20 read as a thick tan band from the front (cell_11: thin top, fat ledge)      # bezel tube half-width ALONG the gaze axis (top / bottom)
HOOD_RAD_TOP, HOOD_RAD_BOT = 0.05, 0.13  # bezel tube half-width RADIAL (top / bottom)
HOOD_FWD = 0.55  # tube centre pushed forward by this x axial half-width
MAX_GAZE = 24.0  # deg the eyeball may swing from its nominal axis toward the camera
_EYES = {}


def build_tail_tube(mats, scene, p, PB):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    n, S = p['tail_rings'], p['tail_sides']
    lift = p['body_lift']
    knots = [(x, y, lift + z) for (x, y, z) in p['tail_knots']]
    dense = _catmull_rom(knots)
    C, L = _resample(dense, n)
    T = []
    for i in range(n):
        a = C[max(0, i - 1)]
        b = C[min(n - 1, i + 1)]
        T.append((b - a).normalized())
    N = []
    nrm = T[0].cross(Vector((1, 0, 0)))
    if nrm.length < 1e-3:
        nrm = T[0].cross(Vector((0, 1, 0)))
    nrm.normalize()
    for i in range(n):
        nrm = nrm - T[i] * nrm.dot(T[i])
        if nrm.length < 1e-6:
            nrm = T[i].orthogonal()
        nrm.normalize()
        N.append(nrm.copy())
    verts, faces, uvs = [], [], []
    ring_s = []
    verts.append(C[0] - T[0] * _radius(0.0, p) * 0.6)
    n_rings = n - 1
    zmin = 1e9
    for i in range(n_rings):
        s = i / float(n - 1)
        ring_s.append(s)
        r = max(_radius(s, p), 0.0015) * (1.0 - (1.0 - TAIL_CONSTRICT) * _ring_band(s))  # R4FORM
        B = T[i].cross(N[i]).normalized()
        for j in range(S):
            th = 2.0 * math.pi * j / S
            v = C[i] + (N[i] * math.cos(th) + B * math.sin(th)) * r
            zmin = min(zmin, v.z)
            verts.append(v)
    verts.append(C[-1] + T[-1] * 0.001)
    tip = len(verts) - 1
    ring0 = 1
    for j in range(S):
        j2 = (j + 1) % S
        faces.append((0, ring0 + j2, ring0 + j))
        uvs.append(((j + 0.5) / S, 0.0))
    for i in range(n_rings - 1):
        a = ring0 + i * S
        b = a + S
        s = (ring_s[i] + ring_s[i + 1]) * 0.5
        for j in range(S):
            j2 = (j + 1) % S
            faces.append((a + j, b + j, b + j2, a + j2))
            uvs.append(((j + 0.5) / S, s))
    last = ring0 + (n_rings - 1) * S
    for j in range(S):
        j2 = (j + 1) % S
        faces.append((tip, last + j, last + j2))
        uvs.append(((j + 0.5) / S, 1.0))
    me = bpy.data.meshes.new('pb_tail_00')
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.validate()
    me.materials.append(mats['fur'])
    me.materials.append(mats['band'])
    for _k, poly in enumerate(me.polygons):
        poly.material_index = 0
        poly.use_smooth = True
    uvl = me.uv_layers.new(name='UVMap')
    for k, poly in enumerate(me.polygons):
        for li in poly.loop_indices:
            uvl.data[li].uv = uvs[k]
    PB._outward(me)
    ob = bpy.data.objects.new('pb_tail_00', me)
    ob.pass_index = PB.IDX['tail']
    scene.collection.objects.link(ob)
    vg_d = ob.vertex_groups.new(name='tail_density')
    vg_l = ob.vertex_groups.new(name='tail_len')
    vg_d.add([0], 1.0, 'REPLACE')
    vg_l.add([0], 1.0, 'REPLACE')
    for i in range(n_rings):
        s = ring_s[i]
        for j in range(S):
            vi = ring0 + i * S + j
            vg_d.add([vi], 1.0, 'REPLACE')
            vg_l.add([vi], 0.35 + 0.65 * (1.0 - s), 'REPLACE')
    vg_d.add([tip], 1.0, 'REPLACE')
    vg_l.add([tip], 0.35, 'REPLACE')
    print(
        'R4FORM tail: length %.3f m, lowest core vertex z=%.3f, tip=%s' % (L, zmin, tuple(round(c, 3) for c in C[-1]))
    )
    ps = PB._hair(
        ob,
        p['tail_hair_len'],
        p['tail_hair_count'],
        p['tail_hair_child'],
        seed=77,
        thick=p['hair_thick'] * 0.8,
        density_group='tail_density',
    )
    ps.vertex_group_length = 'tail_len'
    return [ob]


def _tail_band_len(p):
    """After _tail_post/_fur3_post: shorten the tufts on the mint bands so the white segments
    stand out as rings (the base sets the length purely by s)."""
    t = _ob('pb_tail_00')
    if t is None:
        return
    n = p['tail_rings']
    S = p['tail_sides']
    vg_l = t.vertex_groups.get('tail_len')
    if vg_l is None:
        return
    for vi in range(1, 1 + (n - 1) * S):
        s = ((vi - 1) // S) / float(n - 1)
        b = _ring_band(s)
        if b <= 0.0:
            continue
        try:
            w = vg_l.weight(vi)
        except RuntimeError as _exc:
            _zyg_log.debug('vertex %s is not in the tail vertex group, skipped: %s', vi, _exc)
            continue
        vg_l.add([vi], w * (1.0 - (1.0 - TAIL_BAND_LEN) * b), 'REPLACE')


# ── eyes: sunk, hooded, camera-aimed ─────────────────────────────────────────
def _mound_t0(er):
    re = EXIT_RHO
    te = EYE_DEPTH * math.sqrt(1.0 - re * re)
    return te - ORBIT_B * math.sqrt(max(0.0, 1.0 - (re / ORBIT_R) ** 2))


def _mound_F(P, c, axis, er):
    up = _EYES.get('up_' + ('l' if c.x < 0 else 'r'), Vector((0, 0, 1)))
    co = c + axis * (_mound_t0(er) * er) + up * (MOUND_UP * er)
    d = P - co
    t = d.dot(axis) / er
    rho = (d - axis * (t * er)).length / er
    return (rho / ORBIT_R) ** 2 + (t / ORBIT_B) ** 2


def _orbit_mound(name, c, axis, q, er, scene, PB, result):
    up = q @ Vector((0.0, 0.0, 1.0))
    _EYES['up_' + name[-1]] = up
    co = c + axis * (_mound_t0(er) * er) + up * (MOUND_UP * er)
    fm = _orbit_material(result)
    ob = PB._sphere(
        name, tuple(co), (ORBIT_R * er, ORBIT_B * er, ORBIT_R * er), scene, fm, segs=48, rings=24, idx='face'
    )
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = q
    print(
        'R4FORM mound %s: %.2f x %.2f r, centre %.3f r behind / %.2f r above the eye centre'
        % (name, ORBIT_R, ORBIT_B, -_mound_t0(er), MOUND_UP)
    )
    return ob


def _lid_ring(name, sp, axis, c, er, scene, PB, p, s1=72, s2=14):
    """R4FORM hooded bezel: elliptical tube about the exit curve — long along the gaze axis
    at the top (a hood over the top third of the eye), wide radially at the bottom (ledge)."""
    e1 = axis.cross(Vector((0, 0, 1)))
    if e1.length < 1e-4:
        e1 = axis.cross(Vector((1, 0, 0)))
    e1.normalize()
    e2 = axis.cross(e1).normalized()
    curve = []
    for i in range(s1):
        u = 2 * math.pi * i / s1
        rd = e1 * math.cos(u) + e2 * math.sin(u)
        lo, hi = 0.0, math.pi
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            P = c + axis * (EYE_DEPTH * er * math.cos(mid)) + rd * (er * math.sin(mid))
            if _head_F(P, c, axis, er, p, PB) > 1.0:
                lo = mid
            else:
                hi = mid
        phi = 0.5 * (lo + hi)
        Q = c + axis * (EYE_DEPTH * er * math.cos(phi)) + rd * (er * math.sin(phi))
        vert = 0.5 * (1.0 + rd.z)  # 1 top of the eye, 0 bottom
        ra = er * (HOOD_AX_BOT + (HOOD_AX_TOP - HOOD_AX_BOT) * vert**1.5)
        rr = er * (HOOD_RAD_BOT + (HOOD_RAD_TOP - HOOD_RAD_BOT) * vert)
        curve.append((Q + axis * (HOOD_FWD * ra) - rd * (0.25 * rr), rd, rr, ra, phi))
    verts, faces = [], []
    for i in range(s1):
        Q, rd, rr, ra, _ = curve[i]
        for j in range(s2):
            v = 2 * math.pi * j / s2
            verts.append(tuple(Q + rd * (rr * math.cos(v)) + axis * (ra * math.sin(v))))
    for i in range(s1):
        i2 = (i + 1) % s1
        for j in range(s2):
            j2 = (j + 1) % s2
            faces.append((i * s2 + j, i2 * s2 + j, i2 * s2 + j2, i * s2 + j2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    PB._outward(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_ring_material())
    ob = bpy.data.objects.new(name, me)
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    phis = [math.degrees(ph) for *_, ph in curve]
    top = max(curve, key=lambda k: k[1].z)
    bot = min(curve, key=lambda k: k[1].z)
    print(
        'R4FORM ring %s: exit %.1f..%.1f deg from the pole; top exit rho %.3f, bottom exit rho %.3f; hood reaches t=%.2f r at the top'
        % (
            name,
            min(phis),
            max(phis),
            math.sin(top[4]),
            math.sin(bot[4]),
            math.cos(top[4]) + (HOOD_FWD + 1.0) * HOOD_AX_TOP,
        )
    )
    return ob


def seat_eyes(scene, result, PB, p):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    """R4FORM: the base's seating with an OBLATE eyeball (EYE_DEPTH x er along the gaze). The front
    pole sits EYE_PROUD x er ahead of the face point, so the equator is (EYE_DEPTH - EYE_PROUD) x er
    BEHIND it — the outer edge no longer hangs off the cap as a hemisphere. The pupil becomes a flat
    cabochon whose rim meets the flattened surface at rho = pupil_r/er, so the visible pupil disc is
    the designed radius without a bead standing proud."""
    er = p['eye_r']
    pr = p['pupil_r']
    z = p['body_lift'] + p['eye_z']
    ti, up_ = math.radians(EYE_TOE_IN), math.radians(EYE_UP)
    for side, sx in (('l', -1), ('r', 1)):
        x = sx * p['eye_sep']
        sp, n = _face_point_normal(x, z, p, PB)
        a = Vector((-sx * math.sin(ti), -math.cos(ti) * math.cos(up_), math.sin(up_))).normalized()
        c = sp + a * ((EYE_PROUD - EYE_DEPTH) * er)
        q = Vector((0.0, -1.0, 0.0)).rotation_difference(a)
        eye, pup, gli = _ob('pb_eye_' + side), _ob('pb_pupil_' + side), _ob('pb_glint_' + side)
        for ob in (eye, pup):
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = q
        eye.location = c
        eye.scale = (1.0, EYE_DEPTH, 1.0)
        # flat cabochon: baked ry is 0.70 pr; scale it to PUPIL_DEPTH pr and seat its equator on the
        # flattened eye surface at rho = pr/er
        pup_ry = pr * PUPIL_DEPTH
        pup.scale = (1.0, PUPIL_DEPTH / 0.70, 1.0)
        t_rim = EYE_DEPTH * er * math.sqrt(max(0.0, 1.0 - (pr / er) ** 2))
        pup.location = c + a * (t_rim + PUPIL_LIFT * er)
        # glint on the ellipsoid surface along gd, inset by (glint_r - glint_out)
        gd_l = Vector((-0.34, -0.87, 0.36)).normalized()
        sc = 1.0 / math.sqrt((gd_l.x / er) ** 2 + (gd_l.y / (EYE_DEPTH * er)) ** 2 + (gd_l.z / er) ** 2)
        gd = (q @ gd_l).normalized()
        gli.location = c + gd * (sc - p['glint_r'] + p['glint_out'])
        gli.scale = (1.45, 1.0, 0.80)
        mound = _orbit_mound('pb_orbit_' + side, c, a, q, er, scene, PB, result)
        result['parts'].append(mound)
        rim = _lid_ring('pb_lid_' + side, sp, a, c, er, scene, PB, p)
        result['parts'].append(rim)
        print(
            'R4FORM eye_%s surf=(%.3f,%.3f,%.3f) centre=(%.3f,%.3f,%.3f) front_pole_y=%.3f equator_y=%.3f pupil_front=%.3f'
            % (side, sp.x, sp.y, sp.z, c.x, c.y, c.z, (c + a * (EYE_DEPTH * er)).y, c.y, (pup.location + a * pup_ry).y)
        )
    bpy.context.view_layer.update()
    for side in ('l', 'r'):
        eye = _ob('pb_eye_' + side)
        _EYES['q_' + side] = eye.rotation_quaternion.copy()
        _EYES['c_' + side] = Vector(eye.location)
        for ch in (_ob('pb_pupil_' + side), _ob('pb_glint_' + side)):
            if ch is None:
                continue
            ch.parent = eye
            ch.matrix_parent_inverse = eye.matrix_world.inverted()


PUPIL_DEPTH = 0.36  # x pupil_r: the cabochon's half-depth
PUPIL_LIFT = 0.012  # x er: the pupil's equator this far in front of the eye surface at its rim (z-fight clearance)


def _aim_eyes(cam):
    """Swing each eyeball (with its pupil + glint) toward the camera, at most MAX_GAZE deg."""
    lim = math.radians(MAX_GAZE)
    for side in ('l', 'r'):
        eye = _ob('pb_eye_' + side)
        if eye is None or ('q_' + side) not in _EYES:
            continue
        q0 = _EYES['q_' + side]
        c = _EYES['c_' + side]
        a0 = q0 @ Vector((0.0, -1.0, 0.0))
        d = (Vector(cam.matrix_world.translation) - c).normalized()
        ang = a0.angle(d)
        if ang > lim:
            ax = a0.cross(d)
            if ax.length < 1e-6:
                continue
            from mathutils import Quaternion

            d = Quaternion(ax.normalized(), lim) @ a0
        a1 = d.normalized()
        rot = a0.rotation_difference(a1)
        eye.rotation_quaternion = rot @ q0
        print(
            'R4FORM gaze %s: %.1f deg toward the camera (asked %.1f)'
            % (side, math.degrees(min(ang, lim)), math.degrees(ang))
        )


_camera_r3 = camera


def camera(cam, cam_data, view_id):
    _camera_r3(cam, cam_data, view_id)
    bpy.context.view_layer.update()
    _aim_eyes(cam)
    bpy.context.view_layer.update()


_post_build_skin4 = post_build


def post_build(scene, result, PB):
    _post_build_skin4(scene, result, PB)
    _tail_band_len(dict(_P))
    lo, hi = PB.bounds(result['parts'])
    print('R4FORM bounds lo=%s hi=%s' % (tuple(round(v, 3) for v in lo), tuple(round(v, 3) for v in hi)))
    # geometry sanity, printed not asserted (the harness builds with check=False)
    for ob in result['parts']:
        if ob.name == 'pb_ground':
            continue
        zmin = min((ob.matrix_world @ Vector(v.co)).z for v in ob.data.vertices)
        if zmin < -1e-4:
            print('R4FORM WARNING %s sinks %.4f' % (ob.name, -zmin))


# ═════════════════════════════════════════════════════════════════════════════
# R4MERGE — composition fixes for fur4 + skin4 + form4 on r3_merge
#  * fur4's `R4` dict is renamed R4F above (form4 also defines R4; both are read at call time).
#  * skin4's and form4's post_build wrappers were BOTH named `_post_build_r3`: with the two
#    sections concatenated the last binding made skin4's wrapper call itself (infinite
#    recursion). Renamed _post_build_fur4 / _post_build_skin4 above, so the chain is
#    form4.post_build -> skin4 -> fur4 -> base (tail band lengths, then droplets, then eye
#    forces / cap fur / mound fur, then the base composition).
#  * fur4's eye exclusion assumed the base seating (a 53 mm SPHERE at EYE_PROUD-1) while
#    form4 seats an OBLATE 58 mm eye (EYE_DEPTH 0.62) at (EYE_PROUD - EYE_DEPTH): the old
#    formula put the exclusion centre 22 mm too deep. _eye_centres_local now uses form4's
#    formula, and every 3D-distance test in fur_density/_crown_len/_cap_fur goes through
#    _eye_dist(): the ellipsoid-normalised distance x 53 mm, so fur4's thresholds
#    (R4F eye_r0/r1/len_r, CAP_HAIR len_eye_r) keep their meaning as multiples of the eye
#    radius on the bigger, flatter eye.
#  * fur4's mound mask (rho from the MOUND's own axis > 53 mm) assumed a mound co-axial with
#    the eye; form4's lens is shifted 0.20 r toward the brow and 1.10 x 0.55 r, so that mask
#    would have rooted tufts inside the top of the eye. _mound_fur below masks in WORLD space
#    against the eyeball ellipsoid (density 0 inside 1.02 eye radii -> 1 at 1.12); the
#    temporal-half length cut and the swept-back alignment are fur4's.
#  * skin4 droplet (0.031, 0.094) sits 55.6 mm from the right eye centre; with form4's 58 mm
#    eye + hood that is inside the bezel -> moved to (0.022, 0.100), 68 mm out, still on the
#    bald forehead strip (half-width 47 mm there).
# ═════════════════════════════════════════════════════════════════════════════
_ER_REF = 0.053  # the eye radius fur4's metre thresholds were tuned on


def _eye_axes():
    ti, up = math.radians(EYE_TOE_IN), math.radians(EYE_UP)
    return [Vector((-sx * math.sin(ti), -math.cos(ti) * math.cos(up), math.sin(up))).normalized() for sx in (-1, 1)]


def _eye_centres_local(p, PB):
    """Body-local eye centres exactly as form4's seat_eyes places them (oblate eye, equator
    (EYE_DEPTH - EYE_PROUD) r behind the face point)."""
    er = p['eye_r']
    z = p['body_lift'] + p['eye_z']
    out = []
    for sx, a in zip((-1, 1), _eye_axes()):
        sp, n = _face_point_normal(sx * p['eye_sep'], z, p, PB)
        c = sp + a * ((EYE_PROUD - EYE_DEPTH) * er)
        out.append(Vector((c.x, c.y, c.z - p['body_lift'])))
    _R4_EYES['er'] = er
    return out


def _eye_dist(P, eyes):
    """Equivalent SPHERICAL distance from the nearest eye: ellipsoid-normalised distance
    (lateral / er, axial / (EYE_DEPTH er)) x the 53 mm reference eye."""
    er = _R4_EYES.get('er', 0.058)
    best = 1e9
    for c, a in zip(eyes, _eye_axes()):
        d = P - c
        t = d.dot(a)
        rho = (d - a * t).length
        n = math.sqrt((rho / er) ** 2 + (t / (EYE_DEPTH * er)) ** 2)
        best = min(best, n * _ER_REF)
    return best


MOUND_HAIR.update({'n0': 1.02, 'n1': 1.12})


def _mound_fur(p):
    """fur4's mound tufts, masked in world space against form4's oblate eyeball."""
    M = MOUND_HAIR
    er = p['eye_r']
    bpy.context.view_layer.update()
    for side in ('l', 'r'):
        ob = _ob('pb_orbit_' + side)
        eye = _ob('pb_eye_' + side)
        if ob is None or eye is None:
            continue
        c = _EYES.get('c_' + side) or Vector(eye.matrix_world.translation)
        q = _EYES.get('q_' + side) or eye.matrix_world.to_quaternion()
        a = (q @ Vector((0.0, -1.0, 0.0))).normalized()
        mw = ob.matrix_world
        vg = ob.vertex_groups.get('orbit_density') or ob.vertex_groups.new(name='orbit_density')
        vgl = ob.vertex_groups.get('orbit_len') or ob.vertex_groups.new(name='orbit_len')
        sx = -1.0 if side == 'l' else 1.0
        n_on = 0
        for v in ob.data.vertices:
            P = mw @ v.co
            d = P - c
            t = d.dot(a)
            rho = (d - a * t).length
            n = math.sqrt((rho / er) ** 2 + (t / (EYE_DEPTH * er)) ** 2)
            w = min(1.0, max(0.0, (n - M['n0']) / (M['n1'] - M['n0'])))
            vg.add([v.index], w, 'REPLACE')
            rl = math.hypot(v.co.x, v.co.z)
            outer = max(0.0, sx * v.co.x / rl) if rl > 1e-6 else 0.0
            vgl.add([v.index], 1.0 - M.get('outer_len_cut', 0.5) * outer, 'REPLACE')
            if w > 0.5:
                n_on += 1
        ps = _body_hair(
            ob, M['len'], M['count'], M['child'], 31 if side == 'l' else 32, p['hair_thick'], 'orbit_density'
        )
        ps.name = 'pb_orbit_tufts'
        ps.vertex_group_length = 'orbit_len'
        ps.settings.object_align_factor = (0.0, M.get('align_back', 0.0) * ps.settings.normal_factor, 0.0)
        print(
            'R4MERGE mound fur %s: %d / %d verts furred (world-space eye test n %.2f..%.2f), %d x %d tufts %.3f m'
            % (side, n_on, len(ob.data.vertices), M['n0'], M['n1'], M['count'], M['child'], M['len'])
        )


DROPS = [
    (0.000, 0.068, 0.0038),
    (-0.006, 0.041, 0.0032),
    (0.009, 0.029, 0.0025),
    (-0.026, 0.098, 0.0035),
    (0.022, 0.100, 0.0028),
    (-0.040, -0.004, 0.0038),
    (0.041, -0.006, 0.0030),
    (0.006, -0.027, 0.0032),
]  # R4MERGE: 5th droplet moved clear of the 58 mm eye


# ── R4MERGE run2: the profile eye was a sliver (side lab_eye 63 vs 21 in form4 / 31 in fur4) ──
# form4's oblate eye is flush with the cap, so tufts that used to sit behind fur4's bulging
# sphere now stand between the profile camera and the iris. Four targeted cuts, none of them
# touching the front-facing coat:
#  (a) mound tufts: none on the temporal half (density x (1-outer)^1.5), 0.6 length cut there,
#      swept back harder (align 1.0 x normal_factor), and masked by the bald triangle so the
#      nasal-side tufts stop closing the forehead strip between the eyes;
#  (b) cap tufts beside the socket: 0.7 -> 0.45 length at the exclusion edge, recovering by
#      d_eq 0.110; an extra 0.5x on roots lateral to the eye at eye height; cap roots on the
#      crown rim (z > 0.10) 0.5x so no lone spike stands over the crown in profile;
#  (c) body temple roots (x > 0.10, y < -0.07, at eye height): 0.5x — their normals lean ~40 deg
#      forward and a 105 mm tuft from y=-0.09 reached the eye's equator;
#  (d) tail tip 15 mm lower (side tail_above +8.2% -> ~+1%; fur4's tufts moved the widest row).
CAP_HAIR.update({'len_eye_min': 0.45, 'len_eye_r': 0.110})
MOUND_HAIR.update({'outer_len_cut': 0.6, 'align_back': 1.0, 'outer_den_pow': 1.5})
TEMPLE_CUT = {'x0': 0.090, 'x1': 0.110, 'y_max': -0.070, 'z_band': 1.3, 'f': 0.5}
CAP_SIDE_CUT = {
    'lat0': 0.30,
    'lat1': 0.60,
    'z_band': 1.1,
    'f': 0.5,
    'crown_z0': 0.100,
    'crown_z1': 0.135,
    'crown_f': 0.5,
}
PARAMS['tail_knots'] = [
    (0.000, 0.050, -0.070),
    (-0.085, 0.170, -0.115),
    (-0.205, 0.280, -0.120),
    (-0.320, 0.390, -0.075),
    (-0.375, 0.457, 0.020),
    (-0.380, 0.462, 0.115),
    (-0.365, 0.430, 0.205),
    (-0.355, 0.450, 0.268),
    (-0.372, 0.492, 0.315),
]


def _mound_fur(p):
    """fur4's mound tufts, masked in world space against form4's oblate eyeball, no tufts on the
    temporal half, and the bald triangle applied in body-local coords."""
    M = MOUND_HAIR
    er = p['eye_r']
    bpy.context.view_layer.update()
    body = _ob('pb_body')
    F = R4F['feather']
    for side in ('l', 'r'):
        ob = _ob('pb_orbit_' + side)
        eye = _ob('pb_eye_' + side)
        if ob is None or eye is None:
            continue
        c = _EYES.get('c_' + side) or Vector(eye.matrix_world.translation)
        q = _EYES.get('q_' + side) or eye.matrix_world.to_quaternion()
        a = (q @ Vector((0.0, -1.0, 0.0))).normalized()
        mw = ob.matrix_world
        vg = ob.vertex_groups.get('orbit_density') or ob.vertex_groups.new(name='orbit_density')
        vgl = ob.vertex_groups.get('orbit_len') or ob.vertex_groups.new(name='orbit_len')
        sx = -1.0 if side == 'l' else 1.0
        n_on = 0
        for v in ob.data.vertices:
            P = mw @ v.co
            d = P - c
            t = d.dot(a)
            rho = (d - a * t).length
            n = math.sqrt((rho / er) ** 2 + (t / (EYE_DEPTH * er)) ** 2)
            w = min(1.0, max(0.0, (n - M['n0']) / (M['n1'] - M['n0'])))
            rl = math.hypot(v.co.x, v.co.z)
            outer = max(0.0, sx * v.co.x / rl) if rl > 1e-6 else 0.0
            w *= (1.0 - outer) ** M['outer_den_pow']
            if body is not None:
                bl = P - Vector(body.location)
                s = _tri_s(bl.x, bl.z)
                w *= min(1.0, max(0.0, 0.5 - s / F))
            vg.add([v.index], w, 'REPLACE')
            vgl.add([v.index], 1.0 - M.get('outer_len_cut', 0.5) * outer, 'REPLACE')
            if w > 0.5:
                n_on += 1
        ps = _body_hair(
            ob, M['len'], M['count'], M['child'], 31 if side == 'l' else 32, p['hair_thick'], 'orbit_density'
        )
        ps.name = 'pb_orbit_tufts'
        ps.vertex_group_length = 'orbit_len'
        ps.settings.object_align_factor = (0.0, M.get('align_back', 0.0) * ps.settings.normal_factor, 0.0)
        print(
            'R4MERGE mound fur %s: %d / %d verts furred (eye n %.2f..%.2f, temporal half off, triangle), %d x %d tufts %.3f m'
            % (side, n_on, len(ob.data.vertices), M['n0'], M['n1'], M['count'], M['child'], M['len'])
        )


def _cap_len_post(p):
    """After _cap_fur: shorten cap tufts lateral to each eye at eye height, and on the crown rim."""
    face = _ob('pb_face')
    body = _ob('pb_body')
    if face is None or body is None:
        return
    vgl = face.vertex_groups.get('cap_len')
    if vgl is None:
        return
    eyes = _R4_EYES.get('c') or _eye_centres_local(p, _R4_EYES.get('PB'))
    er = p['eye_r']
    C = CAP_SIDE_CUT
    off = Vector(face.location) - Vector(body.location)
    n_side = n_crown = 0
    for v in face.data.vertices:
        q = off + v.co
        f = 1.0
        for c in eyes:
            sx = -1.0 if c.x < 0 else 1.0
            lat = sx * (q.x - c.x) / er
            if lat > C['lat0'] and abs(q.z - c.z) < C['z_band'] * er:
                tl = min(1.0, (lat - C['lat0']) / (C['lat1'] - C['lat0']))
                f *= 1.0 - (1.0 - C['f']) * tl
                n_side += 1
        if q.z > C['crown_z0']:
            tz = min(1.0, (q.z - C['crown_z0']) / (C['crown_z1'] - C['crown_z0']))
            f *= 1.0 - (1.0 - C['crown_f']) * tz
            n_crown += 1
        if f >= 1.0:
            continue
        try:
            w = vgl.weight(v.index)
        except RuntimeError:
            w = 1.0
        vgl.add([v.index], w * f, 'REPLACE')
    print('R4MERGE cap_len_post: %d side-of-eye verts, %d crown verts shortened' % (n_side, n_crown))


def _temple_len(p):
    """Body temple roots whose tufts lean forward over the eye in profile: fur_len x TEMPLE_CUT.f."""
    body = _ob('pb_body')
    vgl = body.vertex_groups.get('fur_len') if body is not None else None
    if vgl is None:
        return
    T = TEMPLE_CUT
    er = p['eye_r']
    ez = p['eye_z']
    n = 0
    for v in body.data.vertices:
        x, y, z = v.co.x, v.co.y, v.co.z
        if y >= T['y_max'] or abs(x) <= T['x0'] or abs(z - ez) >= T['z_band'] * er:
            continue
        tx = min(1.0, (abs(x) - T['x0']) / (T['x1'] - T['x0']))
        f = 1.0 - (1.0 - T['f']) * tx
        try:
            w = vgl.weight(v.index)
        except RuntimeError:
            w = 1.0
        vgl.add([v.index], w * f, 'REPLACE')
        n += 1
    print('R4MERGE temple_len: %d body verts shortened' % n)


_post_build_form4 = post_build


def post_build(scene, result, PB):
    _post_build_form4(scene, result, PB)  # form4 -> skin4 -> fur4 -> base
    p = dict(_P)
    _cap_len_post(p)
    _temple_len(p)
    bpy.context.view_layer.update()


# ── R4MERGE run3 (final): two lone 45 mm cap tufts stood over the crown-front in profile (cap roots at
# z 0.10-0.12 whose normals point up, sparse parents in the shorter brow-band coat) -> the cap's crown
# taper now starts at z 0.085 and ends at 0.4x on the rim; side tail_above +6.5% -> tip another 12 mm down.
CAP_SIDE_CUT.update({'crown_z0': 0.085, 'crown_z1': 0.135, 'crown_f': 0.4})
PARAMS['tail_knots'] = [
    (0.000, 0.050, -0.070),
    (-0.085, 0.170, -0.115),
    (-0.205, 0.280, -0.120),
    (-0.320, 0.390, -0.075),
    (-0.375, 0.457, 0.020),
    (-0.380, 0.462, 0.115),
    (-0.365, 0.430, 0.205),
    (-0.355, 0.450, 0.258),
    (-0.372, 0.492, 0.303),
]


# ═════════════════════════════════════════════════════════════════════════════
# R5FORM — lookdev2 round 1, proportions + part geometry (appended on r4_merge; every name
# below shadows the base definition because pre_build/post_build/build_mouth_beak look them
# up at call time).
#
# MEASURED FIRST (r1_form/measure.py, anchor vs r4_merge/run3, front):
#   eye dia / furred-head width   anchor 0.227   r4 0.231   (matched)
#   eye centre spacing / eye dia  anchor 1.67    r4 1.62    (matched)
#   eye centre from the crown     anchor 0.33 h  r4 0.42 h  (r4 eyes sit too LOW on the ball)
#   eye centre to the feet        anchor 3.4 dia r4 2.5 dia (same defect + eye too big vs h)
#   harness eye_frac (eye / whole-silhouette width, GATED): front +7.1 %, side +11.2 %
#   plate lateral to the eye: the cap's half-width at eye height is 0.126 m and the r4
#   eye's outer edge (sep 0.074 + r 0.058) is 0.132 m -> the eye overhangs the cap, so no
#   teal can show outside it whatever the fur mask does. Bringing the eye in + shrinking it
#   puts the outer edge at 0.121 m: a 5 mm sliver. Real plate outside the eye needs a wider
#   cap (face_r ~0.145 with FACE_YS ~1.9 to keep the rim inside the body) — NOT done here.
#
# * EYES: r 0.058 -> 0.053 (x0.91: critic 0.29 -> 0.26 of the head, harness +7/+11 %), sep
#   scaled with it (0.068) so the gap between the eyes stays ~0.65 dia (anchor 0.68), centre
#   raised 10 mm (eye_z 0.072) with the mouth following; pupil/glint scaled. The fur mask's
#   widest knot moves to eye height and out to 0.110 so roots do not sit on the sliver of
#   plate lateral to the eye. Two dew droplets that would now touch the bezel are moved.
# * ARMS: the r4 arm was one 110 mm rod at 58 deg with three finger stubs (critic: long thin
#   rods splayed 45 deg). Now upper arm 48 mm nearly vertical (6 deg out), forearm 40 mm bent
#   15 deg IN, root radius 36 mm (x1.2) tapering to 24 mm, a mitten paw (26x22x30 mm) with
#   three nubs <= 0.25 paw radius; shoulder at x 0.90 rx, y -0.50 ry, z -0.18 rz so the arm
#   leaves the coat at about mid-body and the paw ends ~20 mm above the toes (anchor: paw
#   bottom ~15 mm above the feet).
# * FEET: toe_r 0.016 -> 0.022 (x1.4), gap 0.030 so the three toes touch, fan 20 deg, tip
#   ellipsoid elongated 1.3x forward; pad a little wider/taller to carry them.
# * MOUTH: lip pad 82x44 mm standing 32 mm (0.3 eye-dia) proud of the plate with a deep
#   (24 mm) pillow body; aperture 0.4 of the pad height under a 0.35 upper lip; 7 upper-jaw
#   teeth; lower lip / tongue re-seated under the smaller aperture.
# * TAIL: knots TRACED off anchor_side (see R5_TAIL_KNOTS): column ~0.98 body-widths behind the body
#   centre (anchor 0.97; r4 1.09), underside 0.09 m above the floor (r4 on the floor), tip kept at +0.303.
#
# HARNESS FINDINGS (read the numbers with these):
#  * pbfit's DRIVER now frames on the BODY and the r4 tail left the side frame -> see R5CAM below. The
#    'before' for this round is base2/ (base overlay + R5CAM only); base/ is the cropped render.
#  * anchors.json side W (977) includes the floor-level BOKEH GLOW right of the feet: sil columns 960..1023
#    exist only at rows 901..948 while the face-side edge is x 932. The side aspect target 1.202 is
#    therefore ~9 % too wide (true ~1.09); the front target carries ~5 % of the same. A tail placed at the
#    anchor's distance reads side aspect ~-11 % against anchors.json and ~-2 % against the true anchor.
#  * side eye_frac: the amber bezel (RING_RGB, hue ~20) is inside the harness's eye gate, so once the lip pad
#    stands 32 mm proud its top meets the bezel's lower ledge in profile and eye+bezel+lip become ONE amber
#    blob (+36 %..+100 %). The front arrangement matches cell_11 (mouth top 0.18 eye-dia under the eye
#    bottoms vs 0.10), so the mouth was not lowered further to satisfy the rule. Also without any geometry
#    change the side eye_frac read +11 % (run3 framing) and -8 % (base2): a cheek tuft crossing the profile
#    eye moves it ~20 %.
#  * close_front: the DRIVER's head framing (face bounds x1.9, fill 0.95) is a looser crop than cell_11
#    (eyes 0.19 of the frame vs 0.24) -> CLOSE_ZOOM 0.77 in R5CAM matches the crop (eye_frac -23 % -> -5 %).
# ═════════════════════════════════════════════════════════════════════════════
R5_ON = {'eyes': True, 'arms': True, 'feet': True, 'mouth': True, 'tail': True}

R5_EYES = {
    'eye_r': 0.053,
    'pupil_r': 0.0270,
    'glint_r': 0.010,
    'eye_sep': 0.068,
    'eye_z': 0.072,
    'mouth_z': 0.000,  # run4: 0.010 put the lip top 20 mm above the eye bottoms (cell_11: mouth top BELOW the eyes) and the
    # proud pad merged with the profile eye in the harness's amber blob (side eye_frac +103 %); eye->mouth 72 mm = 0.68 dia (anchor 0.66)
}
R5_ARMS = {
    # run3: run2's shoulder (0.90 rx, -0.50 ry) hung the arm INSIDE the lower-flank coat in the front view
    # (the r4 arm was visible only because it stuck out sideways to x 0.214). Anchor: arms at the fur's
    # lateral edge, ~0.44 of the body depth from the face. Shoulder out to 1.02 rx at mid-depth, upper arm
    # 14 deg outward so the elbow reaches the fur edge, forearm 15 deg back in; root r 0.032 (anchor arm
    # ~0.08-0.13 body-widths wide = r 0.02-0.03).
    'arm_sh': (1.02, -0.32, -0.16),
    'arm_r': 0.032,
    'arm_upper': 0.048,
    'arm_fore': 0.040,
    'arm_out_deg': 14.0,
    'arm_in_deg': 15.0,
    'arm_fwd_deg': 4.0,
    'paw_r': (0.026, 0.022, 0.030),
    'paw_drop': 0.012,
    'nub_r': 0.0062,
    'nub_n': 3,
    'arm_len': 0.088,
    'arm_drop': 85.0,
    'arm_fwd': 4.0,  # stock builder only (PB.build check=True)
}
R5_FEET = {
    'toe_r': 0.022,
    'toe_gap': 0.030,
    'toe_fan': 20.0,
    'toe_len': 0.036,
    'toe_tip_fwd': 1.30,
    'foot_r': 0.044,
    'foot_h': 0.016,
}
# R5 tail knots TRACED off anchor_side (measure: per-row front/rear edge of the tail column, 0.77 mm/px, x0.92
# for our smaller ball; y behind the body centre, z relative to body_lift). Anchor column centre y 0.32-0.38
# (r4 0.43-0.49), underside lowest at z_floor ~0.13 (r4 on the floor), bow toward the body at z_floor ~0.50,
# tip leaning back. r4's side aspect +5 % and tail_above +9 % were both the far-back, floor-hugging J: a wider
# silhouette AND a higher 0.55-width threshold.
# Tip kept at r4's +0.303 (the FRONT aspect is gated too and every 20 mm of tip costs it ~3.5 %; the anchors
# disagree on the tip); column x -0.385 (run3 front aspect -4.7 %: the vertical arms no longer widen the front).
R5_TAIL_KNOTS = [
    (0.000, 0.050, -0.050),
    (-0.080, 0.150, -0.075),
    (-0.195, 0.245, -0.075),
    (-0.310, 0.300, -0.020),
    (-0.372, 0.340, 0.050),
    (-0.390, 0.352, 0.110),
    (-0.385, 0.330, 0.175),
    (-0.375, 0.318, 0.230),
    (-0.372, 0.335, 0.268),
    (-0.385, 0.375, 0.303),
]

if R5_ON['eyes']:
    PARAMS.update(R5_EYES)
    # widest bald knot at eye height, out to 0.110 (was (0.060, 0.098))
    R4F['tri'] = [(0.150, 0.012), (0.120, 0.030), (0.070, 0.110), (0.010, 0.080), (-0.004, 0.050), (-0.036, 0.0)]
    DROPS = [
        (0.000, 0.068, 0.0038),
        (-0.006, 0.041, 0.0032),
        (0.009, 0.029, 0.0025),
        (-0.020, 0.112, 0.0035),
        (0.016, 0.112, 0.0028),
        (-0.050, 0.004, 0.0038),
        (0.050, 0.004, 0.0030),
    ]  # R5: 4th/5th clear of the raised eye, 6th/7th clear of the wider lip pad; the chin drop (0.006,-0.027) removed (under the lowered lip)
if R5_ON['arms']:
    PARAMS.update(R5_ARMS)
    # the r2 arm-zone length cut, extended down the flank (z -0.10 -> -0.15) and deepened (0.55 -> 0.40x)
    # so the vertical arm hangs outside the coat as in the anchor; front half only (y < -0.02)
    ARM_ZONE.update({'x0': 0.090, 'x1': 0.120, 'z_top': 0.030, 'z_lo': -0.150, 'y_max': -0.02, 'min': 0.40})
if R5_ON['feet']:
    PARAMS.update(R5_FEET)
if R5_ON['tail']:
    PARAMS['tail_knots'] = R5_TAIL_KNOTS
if R5_ON['mouth']:
    BEAK_R = (0.041, 0.024, 0.022)  # R5: 68x36 -> 82x44 mm pad, 24 mm deep pillow (was 15)
    BEAK_OUT = 0.032  # R5: 0.028 -> 0.032 (0.3 eye-dia proud)
    CUT_R = (0.031, 0.012, 0.0088)  # R5: aperture 0.4 of the pad height (was 0.55)
    CUT_DZ = -0.002  # R5: upper lip 0.35 / aperture 0.40 / lower lip 0.25
    TEETH_DZ = 0.0040  # R5: teeth hang from the new upper edge (+0.0068)
    TEETH_SPAN = 0.036
    LOWLIP_R = (0.026, 0.008, 0.0060)
    LOWLIP_DZ = -0.014
    TONGUE_DZ = -0.0085
    TONGUE_R = (0.013, 0.006, 0.0030)


def build_arms_r5(mats, scene, p, PB):
    """R5FORM: two-segment hanging arm (upper nearly vertical, forearm bent inward) ending in
    a mitten paw with three small nubs. All parts pass_index 'arm'."""
    out = []
    sx_, sy_, sz_ = p['arm_sh']
    a_out = math.radians(p['arm_out_deg'])
    a_in = math.radians(p['arm_in_deg'])
    a_fwd = math.radians(p['arm_fwd_deg'])
    r0 = p['arm_r']
    r1 = r0 * 0.85
    r2 = r0 * 0.72
    pr = p['paw_r']
    for sx in (-1, 1):
        side = 'l' if sx < 0 else 'r'
        sh = Vector((sx * p['body_rx'] * sx_, p['body_ry'] * sy_, p['body_lift'] + p['body_rz'] * sz_))
        d1 = Vector((sx * math.sin(a_out), -math.sin(a_fwd), -math.cos(a_out))).normalized()
        el = sh + d1 * p['arm_upper']
        d2 = Vector((-sx * math.sin(a_in), -math.sin(a_fwd), -math.cos(a_in))).normalized()
        wr = el + d2 * p['arm_fore']
        out.append(PB._capsule('pb_arm_%s' % side, sh, el, r0, r1, scene, mats['skin'], idx='arm'))
        out.append(PB._sphere('pb_elbow_%s' % side, tuple(el), r1, scene, mats['skin'], segs=20, rings=10, idx='arm'))
        out.append(PB._capsule('pb_fore_%s' % side, el, wr, r1, r2, scene, mats['skin'], idx='arm'))
        pc = wr + d2 * p['paw_drop']
        out.append(PB._sphere('pb_paw_%s' % side, tuple(pc), pr, scene, mats['skin'], segs=24, rings=12, idx='arm'))
        for k in range(p['nub_n']):
            ang = math.radians(-30 + 30 * k)
            nd = Vector((sx * math.sin(ang) * 0.9, -math.cos(ang) * 0.70, -0.80)).normalized()
            nc = pc + Vector((nd.x * pr[0], nd.y * pr[1], nd.z * pr[2])) * 0.92
            out.append(
                PB._sphere(
                    'pb_nub_%s%d' % (side, k), tuple(nc), p['nub_r'], scene, mats['skin'], segs=12, rings=8, idx='arm'
                )
            )
        print(
            'R5FORM arm %s: shoulder %s elbow %s wrist %s paw centre %s (paw bottom z %.3f)'
            % (
                side,
                tuple(round(v, 3) for v in sh),
                tuple(round(v, 3) for v in el),
                tuple(round(v, 3) for v in wr),
                tuple(round(v, 3) for v in pc),
                pc.z - pr[2],
            )
        )
    return out


def build_feet_r5(mats, scene, p, PB):
    """R5FORM: r3's pad + three toes, with plump touching toes and a forward-elongated tip."""
    out = []
    pw, pl, ph = p['foot_r'], p['foot_len'], p['foot_h']
    tr, tl, gap = p['toe_r'], p['toe_len'], p['toe_gap']
    fan = math.radians(p['toe_fan'])
    fwd = p.get('toe_tip_fwd', 1.05)
    for sx in (-1, 1):
        side = 'l' if sx < 0 else 'r'
        cx, cy = sx * p['foot_sep'], p['foot_fwd']
        out.append(
            PB._sphere(
                'pb_foot_%s' % side, (cx, cy, ph), (pw, pl, ph), scene, mats['foot'], segs=24, rings=12, idx='foot'
            )
        )
        for k in range(3):
            a = fan * (k - 1)
            base = Vector((cx + gap * (k - 1), cy - pl * 0.55, tr))
            d = Vector((math.sin(a) * 0.6, -math.cos(a), 0.0)).normalized()
            tip = base + d * tl
            out.append(
                PB._capsule(
                    'pb_toe_%s%d' % (side, k),
                    base,
                    tip,
                    tr * 0.92,
                    tr * 0.80,
                    scene,
                    mats['foot'],
                    sides=12,
                    idx='foot',
                )
            )
            # elongated tip: bake the ellipsoid along the toe direction (rotate the sphere)
            ob = PB._sphere(
                'pb_toe_%s%d_tip' % (side, k),
                tuple(tip),
                (tr, tr * fwd, tr * 0.95),
                scene,
                mats['foot'],
                segs=16,
                rings=10,
                idx='foot',
            )
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = Vector((0.0, -1.0, 0.0)).rotation_difference(d)
            out.append(ob)
    return out


_R4_pre_build = pre_build


def pre_build(PB):
    _R4_pre_build(PB)
    if R5_ON['arms']:
        PB.build_arms = lambda mats, scene, p=PB.P: build_arms_r5(mats, scene, p, PB)
    if R5_ON['feet']:
        PB.build_feet = lambda mats, scene, p=PB.P: build_feet_r5(mats, scene, p, PB)
    print('R5FORM stages on: %s' % ', '.join(k for k, v in R5_ON.items() if v))


# ═════════════════════════════════════════════════════════════════════════════
# R5CAM — keep the whole creature in frame under the repaired harness.
# pbfit's DRIVER now frames on the BODY (fill 0.66, aimed at the body centre). With the r4 tail
# (column ~1.1 body-widths behind the centre, tip 0.53 m up) the side view CROPS the tail at the
# right edge: base run side w/h 737x665 vs 745x594 uncropped, side aspect -7.8 % / tail_above
# -27 % purely from the crop. The anchors are composed with the body off-centre and the tail
# inside the frame, so: after the harness places the camera, project the padded bounds of every
# pb_ part (bounding boxes carry no hair -> pad 0.07 m), shift the camera in its own image plane
# so the creature is centred, and only if it still does not fit pull straight back by the
# needed factor. Close-ups are left alone (they frame the face on purpose).
# ═════════════════════════════════════════════════════════════════════════════
CAM_FIT = {'margin': 0.035, 'pad': 0.07, 'iters': 3}


def _fit_camera(cam, cam_data, view_id):
    from bpy_extras.object_utils import world_to_camera_view as w2c

    scene = bpy.context.scene
    obs = [
        o for o in scene.collection.objects if o.type == 'MESH' and o.name.startswith('pb_') and o.name != 'pb_ground'
    ]
    corners = [o.matrix_world @ Vector(c) for o in obs for c in o.bound_box]
    R = cam.matrix_world.to_quaternion()
    right = R @ Vector((1, 0, 0))
    up = R @ Vector((0, 1, 0))
    fwd = R @ Vector((0, 0, -1))
    pad = CAM_FIT['pad']
    pts = [w + right * (sx * pad) + up * (sy * pad) for w in corners for sx in (-1, 1) for sy in (-1, 1)]
    fov = 2.0 * math.atan(0.5 * cam_data.sensor_width / cam_data.lens)
    avail = 1.0 - 2.0 * CAM_FIT['margin']
    d0 = None
    for _ in range(CAM_FIT['iters']):
        bpy.context.view_layer.update()
        ndc = [w2c(scene, cam, p) for p in pts]
        x0, x1 = min(n.x for n in ndc), max(n.x for n in ndc)
        y0, y1 = min(n.y for n in ndc), max(n.y for n in ndc)
        centre = sum(pts, Vector()) / len(pts)
        d = (centre - cam.location).dot(fwd)
        if d0 is None:
            d0 = d
        W = 2.0 * d * math.tan(fov / 2.0)
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        cam.location += right * ((cx - 0.5) * W) + up * ((cy - 0.5) * W)
        ext = max(x1 - x0, y1 - y0)
        if ext > avail:
            cam.location -= fwd * (d * (ext / avail - 1.0))
    bpy.context.view_layer.update()
    ndc = [w2c(scene, cam, p) for p in pts]
    print(
        'R5CAM %s: ndc x %.3f..%.3f y %.3f..%.3f, distance x%.3f'
        % (
            view_id,
            min(n.x for n in ndc),
            max(n.x for n in ndc),
            min(n.y for n in ndc),
            max(n.y for n in ndc),
            (centre - cam.location).dot(fwd) / d0,
        )
    )


_camera_r4m = camera  # R5MERGE: renamed (light also captured _camera_r4)


CLOSE_ZOOM = 0.77  # close-ups: the harness's head framing (face bounds x1.9 at fill 0.95) is a looser crop than cell_11
# (eyes 0.19 of the frame vs 0.24) -> move the camera 23 % of the way to its target


def camera(cam, cam_data, view_id):
    if view_id.startswith('close'):
        R = cam.matrix_world.to_quaternion()
        fwd = R @ Vector((0.0, 0.0, -1.0))
        dist = cam_data.dof.focus_distance  # the harness stores its placement distance here
        cam.location = cam.location + fwd * (dist * (1.0 - CLOSE_ZOOM))
        cam_data.dof.focus_distance = dist * CLOSE_ZOOM
        print('R5CAM %s: close-up distance x%.2f' % (view_id, CLOSE_ZOOM))
    else:
        _fit_camera(cam, cam_data, view_id)
    _camera_r4m(cam, cam_data, view_id)  # r2 look (DOF off, bokeh) + r4 gaze aim, on the final camera


# ═════════════════════════════════════════════════════════════════════════════
# R5 FUR-HAIR (lookdev2 / r1_fur_hair) — plush tapered wavy LOCKS instead of a bottle-brush
#
# Critic (phase-2 spec): the coat is a straight stiff uniform brush of ~1 mm strands; the
# anchor is soft plush of thick tapered wavy locks (~6-10 mm at the base) that clump into
# tufts with no per-strand specular.
#
# Base measurement (base/ run, front_full): the crown fur reaches 107 px ≈ 64 mm above the
# core on a nominal 0.105 x 0.85 = 0.089 m hair, i.e. the effective reach is ~0.7 of the
# nominal (wind droop, kink, roughness, length_random). The anchor's crown locks are ~0.4
# core radii (~60 mm), so the REACH was already right — the defect is the strand structure,
# not the length. run1 therefore keeps hair_len 0.105 and changes only how the strands are
# built and shaded:
#  * INTERPOLATED children (the coat stays continuous between parents) with clump 0.70 and a
#    POSITIVE clump_shape 0.20: children stay spread over their parent's cell at the root and
#    converge late, so each cell reads as a fat lock tapering to a point. 1000 parents x 72
#    children = 72k strands (base 1800 x 80 = 144k SIMPLE strands in 6.5 mm discs). With ~0.28 m²
#    of furred body that is one lock per ~2.8 cm², ~17 mm apart — the anchor's side locks are
#    11-19 mm wide at 1024 px (0.75 mm/px on a 560 px ball).
#  * root radius 0.60 mm tapering to 0.05 x: 72 strands x 0.6 mm = 43 mm of strand across a
#    17 mm cell, so a lock is a solid body, not a see-through broom.
#  * kink WAVE amplitude 8 mm (metres, not x length), frequency 1.8 — the anchor locks carry
#    ~1.5-2 gentle S-bends over their length. kink_amplitude_clump 0.6 so the wave fades toward
#    the clumped tip; render_step 4 (16 segments) so the wave is a curve, not a zigzag.
#  * endpoint roughness 0.05 x L (5 mm fray at the very tip), random roughness 0.02 x L on 40 %
#    of the children: the critic asked 0.25 / 0.10, but roughness is applied AFTER clumping in
#    Blender's child modifiers, so 0.25 x 0.105 = 26 mm of tip scatter would splay every lock
#    tip into a 50 mm brush — the very brush the spec is trying to remove. Small values keep
#    the lock's pointed tip and add only softness.
#  * Principled Hair (Chiang) roughness 0.35 -> 0.65, radial 0.30 -> 0.50, coat 0.25 -> 0.0:
#    no per-strand glints; the diffuse mix stays 0.60 (it is what carries the fur's Lab L).
# _tuft_settings is rebound at module level, exactly as R4 did, so pb_tufts, the cap tufts,
# the mound tufts and the tail tufts all pick it up (tail length/density/colour are run3).
# ═════════════════════════════════════════════════════════════════════════════
LOCK = {
    'child_type': 'INTERPOLATED',
    'clump': 0.70,
    'shape': 0.20,
    'len_random': 0.25,
    'rough1': 0.02,
    'rough2': 0.02,
    'rough2_thresh': 0.6,
    'rough_end': 0.05,
    'end_shape': 1.2,
    'kink': 'WAVE',
    'kink_amp': 0.008,
    'kink_freq': 1.8,
    'kink_amp_clump': 0.6,
    'kink_flat': 0.6,
    'kink_shape': 0.2,
    'root': 0.00060,
    'tip': 0.05,
    'render_step': 4,
}
R5_HAIR = {'hair_count': 1000, 'hair_child': 72, 'hair_thick': LOCK['root']}
PARAMS.update(R5_HAIR)
FUR_COL.update({'roughness': 0.65, 'radial': 0.50, 'coat': 0.0})

_R4_tuft_settings = _tuft_settings


def _tuft_settings(s, length, thick, clump=None, shape=None, radius=None):
    L = LOCK
    _R4_tuft_settings(s, length, thick)  # base plumbing (bspline, advanced, wind, render_type)
    s.child_type = L['child_type']
    s.clump_factor = L['clump']
    s.clump_shape = L['shape']
    s.use_clump_noise = False
    s.length_random = L['len_random']
    s.roughness_1 = length * L['rough1']
    s.roughness_1_size = length * 1.5
    s.roughness_2 = length * L['rough2']
    s.roughness_2_size = 1.0
    s.roughness_2_threshold = L['rough2_thresh']
    s.roughness_endpoint = length * L['rough_end']
    s.roughness_end_shape = L['end_shape']
    s.kink = L['kink']
    s.kink_amplitude = L['kink_amp']
    s.kink_amplitude_clump = L['kink_amp_clump']
    s.kink_flat = L['kink_flat']
    s.kink_frequency = L['kink_freq']
    s.kink_shape = L['kink_shape']
    s.render_step = L['render_step']
    s.radius_scale = 1.0
    s.root_radius = L['root']
    s.tip_radius = L['root'] * L['tip']


# ── run2: LOCK DEFINITION — fewer, fatter, flatter petals; the fine haze halved ──────────
# run1 crops next to the anchor (cmp_run1.png): the anchor's flank is broad flat overlapping
# petals ~17-22 mm wide lying TANGENTIALLY (combed away from the face), each with a dark valley
# under its edge; the chest is fat hanging locks ~25 mm wide with distinct valleys. run1's locks
# were thin radial bundles in a bright haze: 17 mm cells at clump 0.70 leave each lock a loose
# strand bundle, and the 140k-strand 38 mm undercoat fills every valley with fibre.
#  * 650 parents x 110 children (72k strands, unchanged total): ~21 mm cells -> anchor petal width.
#  * clump 0.70 -> 0.85, clump_shape 0.20 -> 0.40: children stay spread over the cell for most of
#    the length and pinch hard at the tip -> a fat petal with a point, and a real valley at the tips.
#  * root 0.60 -> 0.70 mm so a 110-strand lock is opaque (110 x 0.7 = 77 mm of strand per 21 mm cell).
#  * wave 8 -> 5 mm, 1.5 cycles, tip fray 0.05 -> 0.03 L: the anchor's petals are smooth bodies.
#  * face-repel 0.12 -> 0.16: the locks lean further along the surface (the anchor's flank
#    petals lie flat and point back; run1's stood off the body radially so each showed its
#    full length as a thin streak).
#  * undercoat 5000x28 -> 2500x24, 38 -> 30 mm (critic: halve the strand count): it stays a
#    soft base under the petals instead of a haze between them.
LOCK.update({'clump': 0.85, 'shape': 0.40, 'kink_amp': 0.005, 'kink_freq': 1.5, 'rough_end': 0.03, 'root': 0.00070})
R5_HAIR.update({'hair_count': 650, 'hair_child': 110, 'hair_thick': LOCK['root']})
PARAMS.update(R5_HAIR)
UNDERCOAT2.update({'count': 2500, 'child': 24, 'len': 0.030})
FACE_FORCE['strength'] = 0.16


# ── run3: TAIL — plush locks of equal length and density on EVERY band, no bare core ────────
# Critic: the tail is a pipe cleaner (thin core, short stiff bristles, mint bands read as bare
# core). Base: tail_len = 0.45 + 0.55(1-s) on a 50 mm hair, i.e. 50 mm at the BASE (1.3 core
# radii) shrinking to 22 mm at the tip regardless of the core, then x0.55 on the mint bands
# (_tail_band_len) over a core already constricted to 0.85 there — so the bands were short
# fuzz on a groove. Here the length follows the core: 0.6 x the UNCONSTRICTED radius _radius(s)
# at every ring (base r 0.038 -> 23 mm, bulge r 0.070 -> 42 mm, near the tip r 0.012 -> 7 mm),
# the same on mint and cream rings (the 0.85 constriction under a mint band becomes a subtle
# groove in a continuous plush, which is what the anchor shows), density 1.0 everywhere but the
# last 3 % (the tip stays a point). The tufts are the run1/run2 LOCK settings through
# _tuft_settings (same clump/wave as the body); parents 1000 -> 800, children 80 -> 70
# (56k strands, was 80k) on a 0.26 m² tube = ~18 mm cells, a little tighter than the body's.
# Colour is unchanged: the FUR_COL band root/tip pair was fitted against the anchor band
# (R3FUR) and the tail material already keys it off the ring attribute.
TAIL5 = {'len_per_r': 0.60, 'hair_len': 0.045, 'count': 800, 'child': 70, 'min_w': 0.06, 'tip_fade': 0.97}
PARAMS.update(
    {'tail_hair_len': TAIL5['hair_len'], 'tail_hair_count': TAIL5['count'], 'tail_hair_child': TAIL5['child']}
)


def _tail_len_r5(p):
    t = _ob('pb_tail_00')
    if t is None:
        return
    n, S = p['tail_rings'], p['tail_sides']
    vg_l = t.vertex_groups.get('tail_len')
    vg_d = t.vertex_groups.get('tail_density')
    if vg_l is None:
        return
    T = TAIL5
    lo = hi = None
    for i in range(n - 1):
        s = i / float(n - 1)
        w = max(T['min_w'], min(1.0, T['len_per_r'] * _radius(s, p) / p['tail_hair_len']))
        d = 1.0 if s <= T['tip_fade'] else max(0.0, 1.0 - (s - T['tip_fade']) / (1.0 - T['tip_fade']))
        lo = w if lo is None else min(lo, w)
        hi = w if hi is None else max(hi, w)
        for j in range(S):
            vi = 1 + i * S + j
            vg_l.add([vi], w, 'REPLACE')
            if vg_d is not None:
                vg_d.add([vi], d, 'REPLACE')
    vg_l.add([0], max(T['min_w'], min(1.0, T['len_per_r'] * _radius(0.0, p) / p['tail_hair_len'])), 'REPLACE')
    tip = 1 + (n - 1) * S
    if tip < len(t.data.vertices):
        vg_l.add([tip], T['min_w'], 'REPLACE')
        if vg_d is not None:
            vg_d.add([tip], 0.0, 'REPLACE')
    print(
        'R5 tail locks: %.0f%% of the core radius, hair %.3f m, len weights %.2f..%.2f, equal on every band'
        % (100 * T['len_per_r'], p['tail_hair_len'], lo, hi)
    )


_post_build_r4merge = post_build


def post_build(scene, result, PB):
    _post_build_r4merge(scene, result, PB)
    _tail_len_r5(dict(_P))
    bpy.context.view_layer.update()


# ── run4: HAIRLINE — no fur on the plate, a clean brow band, crest combed up/forward ────────
# Critic: fur grows over the forehead band and hangs into the eyes; the anchor hairline is a
# clean edge above the rims with the boundary fur combed up/outward.
# Probe (probe_cap.py on run3): the cap's proud top meets the body at z 0.134 body-local, only
# 14 mm (0.12 eye-dia) above the eye tops (0.120); its footprint on the body is |x| <= 0.09 at
# z 0.10-0.12 and |x| <= 0.127 at eye height. The R4 bald triangle is 0.030 half-wide at z 0.113,
# so body roots at |x| 0.03-0.09 under the cap grew THROUGH its brow, on top of the 2500 x 80
# cap tufts rooted on the plate itself. Two sources of the fur in the eyes; both go:
#  * the cap's two particle systems (pb_cap_tufts, pb_cap_under) are removed after the build
#    (zero density on the plate; _cap_len_post then finds nothing to shorten).
#  * _tri_s gains a rounded brow band (half-width 0.100, z 0.040 -> 0.138 = cap top + 4 mm,
#    corner 0.030) so no body root sits under the plate above the eyes; outside |x| 0.10 the
#    3D eye exclusion alone rules, as before (the anchor's fur does reach the outer-upper rims).
#  * feather 14 -> 6 mm (critic: 3-5 mm falloff); brow shortening 0.50 -> 0.90 so the roots on
#    the band's edge keep their length: they ARE the crest.
#  * a crest wind (forward-up, 0.16, reach 0.11 m from body-local (0, -0.05, 0.19)) combs the
#    crown-front locks up and slightly forward — the anchor's forward-swept crest — instead of
#    letting the face-repel push them back and the global droop lay them over the plate.
# A 0.5 eye-dia clean band is not reachable from the fur side: it would be bare BODY above the
# cap top (form/skin own the cap height). The hairline here is the cap edge, combed up.
BROW5 = {'hw': 0.100, 'z_lo': 0.040, 'z_top': 0.138, 'corner': 0.030}
CREST_WIND = {'strength': 0.16, 'centre': (0.0, -0.05, 0.19), 'dir': (0.0, -0.55, 0.835), 'dist': 0.11}
R4F.update({'feather': 0.006, 'brow_min': 0.90})


def _band_s(x, z):
    """Signed distance INTO the rounded brow band (>0 inside), metres."""
    B = BROW5
    cz = (B['z_top'] + B['z_lo']) / 2.0
    bx, bz = B['hw'] - B['corner'], (B['z_top'] - B['z_lo']) / 2.0 - B['corner']
    dx, dz = abs(x) - bx, abs(z - cz) - bz
    outside = math.hypot(max(dx, 0.0), max(dz, 0.0))
    inside = min(max(dx, dz), 0.0)
    return -(outside + inside - B['corner'])


_tri_s_r4 = _tri_s


def _tri_s(x, z):
    return max(_tri_s_r4(x, z), _band_s(x, z))


def _drop_cap_fur():
    face = _ob('pb_face')
    if face is None:
        return
    n = 0
    for md in [m for m in face.modifiers if m.type == 'PARTICLE_SYSTEM']:
        face.modifiers.remove(md)
        n += 1
    print('R5 hairline: removed %d particle systems from pb_face (no fur on the plate)' % n)


def _crest_wind():
    col = _WIND.get('col')
    body = _ob('pb_body')
    if col is None or body is None:
        return
    C = CREST_WIND
    loc = Vector(body.location) + Vector(C['centre'])
    bpy.ops.object.effector_add(type='WIND', location=tuple(loc))
    w = bpy.context.active_object
    w.name = 'pb_crest_wind'
    d = Vector(C['dir']).normalized()
    w.rotation_mode = 'QUATERNION'
    w.rotation_quaternion = d.to_track_quat('Z', 'Y')
    w.field.strength = C['strength']
    w.field.falloff_power = 0.0
    w.field.use_max_distance = True
    w.field.distance_max = C['dist']
    w.field.flow = 0.0
    w.field.noise = 0.0
    w.hide_render = True
    for c in list(w.users_collection):
        c.objects.unlink(w)
    col.objects.link(w)
    print('R5 crest wind at %s strength %.3f reach %.3f' % (tuple(round(v, 3) for v in loc), C['strength'], C['dist']))


_post_build_r5_run3 = post_build


def post_build(scene, result, PB):
    _post_build_r5_run3(scene, result, PB)
    _drop_cap_fur()
    _crest_wind()
    bpy.context.view_layer.update()


# ── run5: HAIRLINE correction — the band stays, the mound and temple cover come back ───────
# run4 read: the forehead is clean and the crest stands up (good), but with the cap systems
# deleted and the brow band also zeroing the mound tufts (they share _tri_s), the orbital
# mounds (pb_orbit_l/r, eyes' hooded bezel, tops level with the cap top at z ~0.137) stood out
# as two bare teal bumps at the hairline in front/close-up and as a teal lump behind the eye at
# 45 deg — worse at q45 than run3. Those skirts were hidden by the short swept-back mound tufts
# and the cap's temple tufts, not by the fur that hung into the eyes.
#  * the cap particle systems are kept: with the band inside _tri_s, _cap_fur's own mask now
#    zeroes the plate between/above the eyes by itself (cap roots there are inside the band),
#    leaving only the temple/cheek cap fur (|x| > 0.10 at eye height, cheeks below z 0.040)
#    that sweeps back over the mound skirts. The plate's brow is still fur-free.
#  * _mound_fur is exempt from the band (flag checked in _tri_s): its 35 mm swept-back tufts
#    cover the mound tops again, masked as before by R4's triangle + the world-space eyeball
#    test (density 0 inside 1.12 eye radii, nothing crosses the cornea).
# The hairline is therefore the mound/cap edge combed up (crest wind kept). The anchor's
# ~0.35 eye-dia of teal brow above the rims needs a taller plate / smaller eyes (form / eyes).
_BAND = {'on': True}


def _tri_s(x, z):
    s = _tri_s_r4(x, z)
    return max(s, _band_s(x, z)) if _BAND['on'] else s


_mound_fur_r4m = _mound_fur


def _mound_fur(p):
    _BAND['on'] = False
    try:
        _mound_fur_r4m(p)
    finally:
        _BAND['on'] = True


def _drop_cap_fur():  # run5: keep the cap systems (the band masks the plate's brow by itself)
    face = _ob('pb_face')
    if face is None:
        return
    n = sum(1 for ps in face.particle_systems)
    print('R5 hairline: cap systems kept (%d), plate brow masked by the band' % n)


# ── run6: LENGTH MAP — crown longest, back shorter, side wisps at eye level restored ────────
# Critic: the silhouette is a uniform compact halo; the anchor's longest fur is at the crown and
# in long horizontal wisps at eye level on the sides, with a forward-swept crest; back and belly
# shorter (crown 0.35 R, side wisps 0.35 R, back 0.25 R, belly 0.20 R -> ratios 1.0 / 1.0 /
# 0.71 / 0.57 of the crown).
# Base fur_len: crown 0.85 (CROWN min), flank 1.0, back 1.0, belly 0.55 (UNDER), temple roots at
# eye height x0.5 (TEMPLE_CUT, R4MERGE profile fix). The effective reach of the 0.105 m hair is
# ~0.7 nominal (base measurement), so the absolute is kept and only the distribution moves:
#  * CROWN min 0.85 -> 1.00: the crown locks are the longest, standing up in the crest wind.
#  * BACK: a new factor on body-local y > 0.03 (behind the equator) easing to 0.72 by y 0.11 —
#    the anchor's rear petals lie flat and short next to the crown spikes.
#  * TEMPLE_CUT f 0.50 -> 0.75: the eye-level side wisps come back to 3/4 length. With the
#    face-repel (0.16) and eye-repel forces they point sideways/back, not at the profile camera,
#    so the R4MERGE reason for halving them (a forward-leaning 105 mm tuft reaching the eye's
#    equator) no longer applies at this lean.
#  * belly: UNDER min 0.55 stays (0.57 asked).
CROWN.update({'min': 1.00})
BACK5 = {'y0': 0.03, 'y1': 0.11, 'min': 0.72}
TEMPLE_CUT.update({'f': 0.75})

_crown_len_r4 = _crown_len


def _crown_len(p):
    _crown_len_r4(p)
    body = _ob('pb_body')
    vgl = body.vertex_groups.get('fur_len') if body is not None else None
    if vgl is None:
        return
    B = BACK5
    n = 0
    for v in body.data.vertices:
        y = v.co.y
        if y <= B['y0']:
            continue
        t = min(1.0, (y - B['y0']) / (B['y1'] - B['y0']))
        t = t * t * (3 - 2 * t)
        f = 1.0 - (1.0 - B['min']) * t
        try:
            w = vgl.weight(v.index)
        except RuntimeError:
            w = 1.0
        vgl.add([v.index], w * f, 'REPLACE')
        n += 1
    print(
        'R5 length map: crown 1.00, back -> %.2f over y %.2f..%.2f (%d verts), temple cut %.2f'
        % (B['min'], B['y0'], B['y1'], n, TEMPLE_CUT['f'])
    )


# ═════════════════════════════════════════════════════════════════════════════
# R5EYES — phase-2 round-1 EYES (shader + recess), appended on r4_merge/merge.py.
# Every name below shadows the base definition (pre_build/post_build/camera look them up
# at call time): EYE_PROUD/EYE_DEPTH, _eye_axes, _eye_dist, seat_eyes, eyes_post, _aim_eyes.
#
# CRITIC (phase 2): the eyeballs protrude as hemispheres (cornea ~0.35 r proud of the plate
# in profile — a frog eye on a fur ball) inside a tan geometric bezel that reads as goggles;
# the anchor eye is a flat almond RECESSED into the face. Iris flat orange, pupil too small,
# hard small catchlight.
#
# MEASURED FIRST (harness find_eyes on the anchors): the front anchor eye is an upright
# oval 122x145 px (w/h 0.84) and the SIDE anchor eye is 82x125 px (w/h 0.66) — both are the
# projection of ONE flat lens whose axis points ~35 deg OUTWARD (cos 35 = 0.82 in front;
# in profile cos 55 + half the lens depth = 0.66). _face_point_normal at the eye point gives
# a face normal 36 deg out / 19 deg up: the anchor eye simply lies IN the face, tangent to
# it. r4 instead aimed a forward-facing eyeball at the camera per view (24 deg), which is
# exactly what lifts the near rim out of the socket in profile (the frog eye).
#
# WHAT CHANGES
#  * the eyeball is a LENS: oblate 0.34 x er along its axis (was 0.62), axis = the face
#    normal's azimuth at 8 deg elevation, sunk so the lens leaves the face point's tangent
#    plane at rho 0.95: the apex stands 0.23 r above the face point (was 0.45) and 0.21 r
#    above its own rim (was 0.39). The eyeball never rotates; the GAZE is the pupil, placed
#    on the lens where the world -Y line through the eye centre meets it (x PUPIL_CONVERGE),
#    so from the front the pupil sits centred/slightly nasal in the oval and in profile it
#    sits toward the front — both anchors.
#  * NO tan bezel (pb_lid_* gone). The orbital mound becomes a face-coloured COLLAR swept
#    about the lens axis: it hugs the lens at rho 0.95 (crest 1-5 mm above the lens edge,
#    a little higher at the top = brow hood), then falls smoothly (0.8 r over 0.55 r) until
#    it is inside the face cap / body — solved per angle — so the lens sits in a flush
#    teal socket. Named pb_orbit_l/r so fur4's mound tufts and the face light still find it.
#  * pupil = a conformal patch on the lens, 0.60 of the visible iris (pupil_r 0.032), lifted
#    0.7 mm (+1.2 mm dome) so nothing z-fights and nothing stands proud.
#  * iris shader: yellow-amber at the limbus -> dark umber collar round the pupil (anchor
#    #E8B12A -> #5A3208), 40 radial spokes about the PUPIL centre, thin dark limbal ring,
#    pupil disc painted in the shader at the same planar coordinate as the patch.
#  * catchlight: one large soft additive blob (transparent + emission x a radial weight
#    attribute) 45 x 24 mm at the viewer's upper-left of the pupil, on the lens.
# ═════════════════════════════════════════════════════════════════════════════
R5 = {
    'pupil_r': 0.0295,
    'glint_r': 0.014,
}  # run3: 0.60 x the visible radius 0.85 r   # run2: 0.028 at rim 0.80 (run1 0.032 at rim 0.95)
PARAMS.update(R5)

EYE_DEPTH = 0.34  # lens half-depth x er along the axis (was 0.62)
RIM_RHO = 0.85  # run3: 0.80 -> 0.85 (run2 front eye_frac -5.9%, run1 +16.2% -> linear in the visible radius)
# the lens leaves the face point's tangent plane at this rho. run2: 0.95 -> 0.80 -- run1's visible disc was 147 px tall
# (front eye_frac +16%, eye/ball 0.30 vs the anchor's 0.237): sink the lens another 0.10 r so the collar crosses it at
# rho 0.80; the apex now stands 0.136 r (7.9 mm) above the socket rim instead of 0.234 r (run1) / 0.45 r (r4)
EYE_PROUD = EYE_DEPTH * (1.0 - math.sqrt(1.0 - RIM_RHO**2))  # apex above the face point = 0.234 r
EYE_AXIS_UP = 8.0  # deg elevation of the lens axis (the face normal is ~19 deg up; 8 keeps the gaze level)
EYE_AXIS_AZ = 0.92  # run2: x the face normal's azimuth (35.7 -> 32.8 deg): run1's front oval was w/h 0.78, the anchor's 0.84 (cos 33 = 0.84)
EYE_DEPTH_FUR = (
    0.70  # axial normalisation of the fur exclusion: with D 0.34 a cap root 12 mm UNDER the rim counted as 'far'
)
PUPIL_LIFT = 0.012  # x er above the lens surface at the pupil edge
PUPIL_DOME = 0.020  # x er extra at the pupil centre
PUPIL_CONVERGE = (
    0.75  # fraction of the full front-camera compensation (1.0 = pupil apex exactly on the eye centre's -Y line)
)
PUPIL_RGB = (0.006, 0.004, 0.004)
COLLAR = {
    'rho_in': RIM_RHO - 0.09,
    'in_depth': 0.05,
    'lip_top': 0.08,
    'lip_bot': 0.03,  # run3: lip_bot 0.015 -> 0.03, a wider teal lower lip over the crease
    'H': 0.80,
    'W': 0.55,
    'rho_max': 1.60,
    'back': 0.15,
    'margin': 0.04,
    'seg': 72,
    'steps': 12,
}
GLINT = {
    'scale': (1.5, 1.0, 0.85),
    'off': 0.24,
    'dir': (-1.0, 0.0, 0.9),
    'emit': 1.8,
    'lift': 0.045,
    'rgb': (1.0, 0.98, 0.94),
    'pow': 2.5,
}  # run2: 5.0 -> 1.8, falloff ^2.5 -- run1's blob was an opaque white oval
SPOKES = 40
STRIPE_AMP = 0.14
NOISE_AMP = 0.12
FIBRE_AMP = 0.48
FIBRE_FREQ = (
    14.0,
    30.0,
)  # run3: longer, denser, stronger streaks (run2's were a faint mottle)   # run2: spokes 0.28 -> 0.16 (sunburst), + radially stretched noise fibres (anchor R p25/p75 141/236 vs run1 175/231)
UMBER = (0.055, 0.016, 0.002)
COLLAR_W = 0.08  # run3: 0.13 -> 0.08, the dark collar ate the amber band (anchor: a narrow dark ring at the pupil)
IRIS_EMIT = 0.15  # run3: 0.22 -> 0.15 (run2 median L 170 vs anchor 155)   # run2: 0.30 -> 0.22, run1 iris median L 179 vs anchor 155


# run2: bands are fractions of the VISIBLE radius RIM_RHO; G pulled down (run1 median sRGB (211,165,69) vs anchor (194,134,64))
def _rim_bands(rim):
    return [
        (0.00, (0.018, 0.009, 0.006)),
        (_u(rim * 1.03), (0.018, 0.009, 0.006)),
        (
            _u(rim * 0.975),
            (0.14, 0.050, 0.010),
        ),  # limbal ring, just inside the collar crossing (run3: lighter -- run2 read as eyeliner in the crease)
        # run4: the whole iris x0.62 -- AgX desaturates the bright albedo toward yellow-white; run3 amber median (209,162,67) L 178 vs
        # the anchor's (194,134,64) L 155: lowering G alone (run3) did nothing, the rendered hue follows the luminance
        (_u(rim * 0.93), (0.57, 0.155, 0.016)),  # yellow-amber limbus (anchor #E8B12A under the mint rig)
        (_u(rim * 0.80), (0.52, 0.118, 0.011)),
        (_u(rim * 0.66), (0.37, 0.075, 0.006)),
        (_u(rim * 0.55), (0.21, 0.040, 0.004)),
        (1.00, (0.15, 0.031, 0.003)),
    ]


BANDS5 = _rim_bands(RIM_RHO)
IRIS_MASK5 = [(_u(RIM_RHO * 1.0), (0, 0, 0)), (_u(RIM_RHO * 0.955), (1, 1, 1)), (1.0, (1, 1, 1))]


def _sstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def _lens_t(rho):
    return EYE_DEPTH * math.sqrt(max(0.0, 1.0 - rho * rho))


def _eye_axes():
    """Lens axes: the face normal's azimuth at the eye point, EYE_AXIS_UP deg elevation."""
    p = _P
    PB = _R4_EYES.get('PB')
    z = p['body_lift'] + p['eye_z']
    up = math.radians(EYE_AXIS_UP)
    out = []
    for sx in (-1, 1):
        sp, n = _face_point_normal(sx * p['eye_sep'], z, p, PB)
        az = EYE_AXIS_AZ * math.atan2(n.x, -n.y)
        out.append(Vector((math.sin(az) * math.cos(up), -math.cos(az) * math.cos(up), math.sin(up))).normalized())
    return out


def _eye_dist(P, eyes):
    er = _R4_EYES.get('er', 0.058)
    best = 1e9
    for c, a in zip(eyes, _eye_axes()):
        d = P - c
        t = d.dot(a)
        rho = (d - a * t).length
        n = math.sqrt((rho / er) ** 2 + (t / (EYE_DEPTH_FUR * er)) ** 2)
        best = min(best, n * _ER_REF)
    return best


def _head_F2(P, p, PB):
    return min(_face_F(P, p, PB), _body_F(P, p))


def _patch_on_lens(centre, A, B, er, lift, dome, segs, K, wname):
    """Conformal elliptical patch on the lens (eye-LOCAL metres: x lateral, -y forward, z up),
    centred at planar `centre` (er units), semi-axes A/B (er units), lifted along the local
    normal by lift + dome x (1 - r^2). Optional per-point float attribute (1 - r^2)^1.5."""
    D = EYE_DEPTH
    verts, ws = [], []

    def P(lat, w):
        l = lat.length
        if l > 0.92:
            lat = lat * (0.92 / l)
        t = _lens_t(lat.length)
        nrm = Vector((lat.x, -t / (D * D), lat.y)).normalized()
        pos = Vector((er * lat.x, -er * t, er * lat.y)) + nrm * (lift + dome * w)
        return tuple(pos)

    verts.append(P(centre, 1.0))
    ws.append(1.0)
    for k in range(1, K + 1):
        r = k / float(K)
        for j in range(segs):
            th = 2.0 * math.pi * j / segs
            lat = centre + Vector((A * r * math.cos(th), B * r * math.sin(th)))
            verts.append(P(lat, 1.0 - r * r))
            ws.append((1.0 - r * r) ** GLINT['pow'])
    faces = []
    for j in range(segs):
        faces.append((0, 1 + j, 1 + (j + 1) % segs))
    for k in range(K - 1):
        a0 = 1 + k * segs
        a1 = a0 + segs
        for j in range(segs):
            j2 = (j + 1) % segs
            faces.append((a0 + j, a1 + j, a1 + j2, a0 + j2))
    me = bpy.data.meshes.new('pb_patch')
    me.from_pydata(verts, [], faces)
    me.validate()
    for poly in me.polygons:
        poly.use_smooth = True
    if wname:
        at = me.attributes.new(name=wname, type='FLOAT', domain='POINT')
        for i, w in enumerate(ws):
            at.data[i].value = w
    return me


def _replace_mesh(ob, me):
    old = ob.data
    for m in old.materials:
        me.materials.append(m)
    ob.data = me
    bpy.data.meshes.remove(old)


def _collar(name, c, a, q, er, scene, PB, p, result):
    """Face-coloured socket collar swept about the lens axis (eye-LOCAL coords, object at c
    rotated by q): inside the lens at rho_in, crest at RIM_RHO (+lip), a smoothstep fall of
    H over W until the surface is inside the face cap / body (per angle), a short dive, and
    front/back poles so the shell is closed."""
    C = COLLAR
    s1 = C['seg']
    M = C['steps']
    rings, ends = [], []
    for i in range(s1):
        u = 2.0 * math.pi * i / s1
        vert = 0.5 * (1.0 + math.sin(u))
        lip = C['lip_bot'] + (C['lip_top'] - C['lip_bot']) * vert
        t_cr = _lens_t(RIM_RHO) + lip
        prof = [(C['rho_in'], _lens_t(C['rho_in']) - C['in_depth']), (RIM_RHO, t_cr)]
        rho_end = C['rho_max']
        for k in range(1, 81):
            rho = RIM_RHO + (C['rho_max'] - RIM_RHO) * k / 80.0
            t = t_cr - C['H'] * _sstep((rho - RIM_RHO) / C['W'])
            Pw = c + q @ Vector((er * rho * math.cos(u), -er * t, er * rho * math.sin(u)))
            if _head_F2(Pw, p, PB) < 1.0 - C['margin']:
                rho_end = rho
                break
        for k in range(1, M + 1):
            rho = RIM_RHO + (rho_end - RIM_RHO) * k / M
            prof.append((rho, t_cr - C['H'] * _sstep((rho - RIM_RHO) / C['W'])))
        r_e, t_e = prof[-1]
        prof.append((r_e, t_e - C['back']))
        rings.append(prof)
        ends.append(rho_end)
    n_r = len(rings[0])
    t_back = min(pr[-1][1] for pr in rings) - C['back']
    verts = [(0.0, -er * (_lens_t(0.0) - 0.10), 0.0)]
    for i in range(s1):
        u = 2.0 * math.pi * i / s1
        for rho, t in rings[i]:
            verts.append((er * rho * math.cos(u), -er * t, er * rho * math.sin(u)))
    back_i = len(verts)
    verts.append((0.0, -er * t_back, 0.0))
    faces = []
    for i in range(s1):
        i2 = (i + 1) % s1
        b0, b1 = 1 + i * n_r, 1 + i2 * n_r
        faces.append((0, b1, b0))
        for j in range(n_r - 1):
            faces.append((b0 + j, b1 + j, b1 + j + 1, b0 + j + 1))
        faces.append((b0 + n_r - 1, b1 + n_r - 1, back_i))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    PB._outward(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_orbit_material(result))
    ob = bpy.data.objects.new(name, me)
    ob.location = c
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = q
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    print(
        'R5EYES collar %s: meets the head at rho %.2f..%.2f r (top %.2f, bottom %.2f, nasal/temporal %.2f/%.2f); crest %.1f mm above the lens edge (top %.1f)'
        % (
            name,
            min(ends),
            max(ends),
            ends[s1 // 4],
            ends[3 * s1 // 4],
            ends[0],
            ends[s1 // 2],
            C['lip_bot'] * er * 1000,
            C['lip_top'] * er * 1000,
        )
    )
    return ob


def _orbit_material(result):
    """R5EYES run3: the socket collar wears the face skin itself (skin4's ORBIT_TINT 0.85 copy made the
    profile face median L 143 vs the anchor's 163 once the collar filled the eye ROI: side lab_face 21)."""
    m = bpy.data.materials.get('pb_skin_face')
    return m if m is not None else result['mats']['skin']


def _pupil_lat(q, D):
    """Planar lens coordinate (er units) of the pupil: where the world -Y line through the
    eye centre meets the lens, scaled by PUPIL_CONVERGE."""
    v_l = (q.inverted() @ Vector((0.0, -1.0, 0.0))).normalized()
    s = 1.0 / math.sqrt(v_l.x**2 + (v_l.y / D) ** 2 + v_l.z**2)
    return Vector((v_l.x, v_l.z)) * (s * PUPIL_CONVERGE)


def eye_shader5(mat, lp, Rp):
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    bsdf = nodes['Principled BSDF']
    tc = nodes.new('ShaderNodeTexCoord')
    nrm = nodes.new('ShaderNodeVectorMath')
    nrm.operation = 'NORMALIZE'
    links.new(tc.outputs['Object'], nrm.inputs[0])
    sep = nodes.new('ShaderNodeSeparateXYZ')
    links.new(nrm.outputs['Vector'], sep.inputs[0])
    nx, ny, nz = sep.outputs['X'], sep.outputs['Y'], sep.outputs['Z']
    u = _math(nt, 'MULTIPLY', a=ny, vb=-1.0)  # sqrt(1 - rho^2) about the axis
    ramp = nodes.new('ShaderNodeValToRGB')
    _ramp_elems(ramp, BANDS5)
    links.new(u, ramp.inputs['Fac'])
    imask = nodes.new('ShaderNodeValToRGB')
    _ramp_elems(imask, IRIS_MASK5)
    links.new(u, imask.inputs['Fac'])
    # planar distance from the pupil centre (same coordinate the pupil patch is built in)
    dx = _math(nt, 'SUBTRACT', a=nx, vb=lp.x)
    dz = _math(nt, 'SUBTRACT', a=nz, vb=lp.y)
    r2 = _math(nt, 'SQRT', a=_math(nt, 'ADD', a=_math(nt, 'MULTIPLY', a=dx, b=dx), b=_math(nt, 'MULTIPLY', a=dz, b=dz)))
    pm = nodes.new('ShaderNodeMapRange')
    pm.interpolation_type = 'SMOOTHSTEP'
    pm.inputs['From Min'].default_value = Rp - 0.012
    pm.inputs['From Max'].default_value = Rp + 0.012
    links.new(r2, pm.inputs['Value'])
    cm = nodes.new('ShaderNodeMapRange')
    cm.interpolation_type = 'SMOOTHSTEP'
    cm.inputs['From Min'].default_value = Rp
    cm.inputs['From Max'].default_value = Rp + COLLAR_W
    links.new(r2, cm.inputs['Value'])
    # radial fibres about the pupil + fine noise, iris only
    ang = _math(nt, 'ARCTAN2', a=dz, b=dx)
    stripe = _math(nt, 'SINE', a=_math(nt, 'MULTIPLY', a=ang, vb=float(SPOKES)))
    noise = nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 30.0
    noise.inputs['Detail'].default_value = 5.0
    noise.inputs['Roughness'].default_value = 0.6
    links.new(nrm.outputs['Vector'], noise.inputs['Vector'])
    nz_ = _math(nt, 'SUBTRACT', a=noise.outputs['Fac'], vb=0.5)
    # run2: fibres = noise sampled in (angle x 7, radius x 45): streaks stretched along the radius from the pupil
    fv = nodes.new('ShaderNodeCombineXYZ')
    links.new(_math(nt, 'MULTIPLY', a=ang, vb=FIBRE_FREQ[0]), fv.inputs['X'])
    links.new(_math(nt, 'MULTIPLY', a=r2, vb=FIBRE_FREQ[1]), fv.inputs['Y'])
    fib = nodes.new('ShaderNodeTexNoise')
    fib.inputs['Scale'].default_value = 1.0
    fib.inputs['Detail'].default_value = 4.0
    fib.inputs['Roughness'].default_value = 0.55
    links.new(fv.outputs['Vector'], fib.inputs['Vector'])
    fib_ = _math(nt, 'MULTIPLY', a=_math(nt, 'SUBTRACT', a=fib.outputs['Fac'], vb=0.5), vb=FIBRE_AMP)
    mod = _math(
        nt,
        'ADD',
        a=_math(
            nt, 'ADD', a=_math(nt, 'MULTIPLY', a=stripe, vb=STRIPE_AMP), b=_math(nt, 'MULTIPLY', a=nz_, vb=NOISE_AMP)
        ),
        b=fib_,
    )
    gain = _math(nt, 'ADD', a=_math(nt, 'MULTIPLY', a=mod, b=imask.outputs['Color']), vb=1.0)
    hood = nodes.new('ShaderNodeMapRange')
    hood.interpolation_type = 'SMOOTHSTEP'
    hood.inputs['From Min'].default_value = 0.30
    hood.inputs['From Max'].default_value = 0.85
    links.new(nz, hood.inputs['Value'])
    hood_g = _math(nt, 'SUBTRACT', va=1.0, b=_math(nt, 'MULTIPLY', a=hood.outputs['Result'], vb=0.40))
    total = _math(nt, 'MULTIPLY', a=gain, b=hood_g)
    # umber collar round the pupil -> limbus-centred gradient
    cmix = nodes.new('ShaderNodeMix')
    cmix.data_type = 'RGBA'
    cmix.blend_type = 'MIX'
    cmix.inputs[6].default_value = (*UMBER, 1.0)
    links.new(ramp.outputs['Color'], cmix.inputs[7])
    links.new(cm.outputs['Result'], cmix.inputs[0])
    col = nodes.new('ShaderNodeVectorMath')
    col.operation = 'SCALE'
    links.new(cmix.outputs[2], col.inputs[0])
    links.new(total, col.inputs['Scale'])
    pmix = nodes.new('ShaderNodeMix')
    pmix.data_type = 'RGBA'
    pmix.blend_type = 'MIX'
    pmix.inputs[6].default_value = (*PUPIL_RGB, 1.0)
    links.new(col.outputs['Vector'], pmix.inputs[7])
    links.new(pm.outputs['Result'], pmix.inputs[0])
    links.new(pmix.outputs[2], bsdf.inputs['Base Color'])
    emis = nodes.new('ShaderNodeVectorMath')
    emis.operation = 'SCALE'
    links.new(pmix.outputs[2], emis.inputs[0])
    links.new(
        _math(nt, 'MULTIPLY', a=_math(nt, 'MULTIPLY', a=imask.outputs['Color'], b=pm.outputs['Result']), vb=IRIS_EMIT),
        emis.inputs['Scale'],
    )
    links.new(emis.outputs['Vector'], bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value = 1.0
    bsdf.inputs['Roughness'].default_value = 0.35
    bsdf.inputs['Specular IOR Level'].default_value = 0.5
    bsdf.inputs['Coat Weight'].default_value = 1.0
    bsdf.inputs['Coat Roughness'].default_value = 0.03
    bsdf.inputs['Coat IOR'].default_value = 1.40


def _glint_material():
    gm = bpy.data.materials.get('pb_glint5')
    if gm is not None:
        return gm
    gm = bpy.data.materials.new('pb_glint5')
    gm.use_nodes = True
    nt = gm.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*GLINT['rgb'], 1.0)
    at = nt.nodes.new('ShaderNodeAttribute')
    at.attribute_name = 'glint_w'
    mul = nt.nodes.new('ShaderNodeMath')
    mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = GLINT['emit']
    nt.links.new(at.outputs['Fac'], mul.inputs[0])
    nt.links.new(mul.outputs[0], em.inputs['Strength'])
    add = nt.nodes.new('ShaderNodeAddShader')
    nt.links.new(tr.outputs[0], add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], out.inputs['Surface'])
    return gm


def eyes_post(scene, result, PB, p):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    mats = result['mats']
    D = EYE_DEPTH
    er = p['eye_r']
    for (side, _sx), a in zip((('l', -1), ('r', 1)), _eye_axes()):
        q = Vector((0.0, -1.0, 0.0)).rotation_difference(a)
        lp = _pupil_lat(q, D)
        m = mats['sclera'] if side == 'l' else mats['sclera'].copy()
        m.name = 'pb_sclera_' + side
        eye_shader5(m, lp, p['pupil_r'] / er)
        eye = _ob('pb_eye_' + side)
        eye.data.materials[0] = m
    pup = mats['pupil'].node_tree.nodes['Principled BSDF']
    pup.inputs['Base Color'].default_value = (0.004, 0.003, 0.004, 1.0)
    pup.inputs['Roughness'].default_value = 0.45
    pup.inputs['Specular IOR Level'].default_value = 0.15
    pup.inputs['Coat Weight'].default_value = 1.0
    pup.inputs['Coat Roughness'].default_value = 0.03
    pup.inputs['Coat IOR'].default_value = 1.40
    _glint_material()


def seat_eyes(scene, result, PB, p):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    """R5EYES: fixed lens in a flush collar; pupil + glint are conformal patches on it."""
    er = p['eye_r']
    pr = p['pupil_r']
    D = EYE_DEPTH
    z = p['body_lift'] + p['eye_z']
    for (side, sx), a in zip((('l', -1), ('r', 1)), _eye_axes()):
        x = sx * p['eye_sep']
        sp, n = _face_point_normal(x, z, p, PB)
        c = sp + a * ((EYE_PROUD - D) * er)
        q = Vector((0.0, -1.0, 0.0)).rotation_difference(a)
        eye, pup, gli = _ob('pb_eye_' + side), _ob('pb_pupil_' + side), _ob('pb_glint_' + side)
        for ob in (eye, pup, gli):
            ob.parent = None
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = q
            ob.location = c
            ob.scale = (1.0, 1.0, 1.0)
        eye.scale = (1.0, D, 1.0)
        lp = _pupil_lat(q, D)
        Rp = pr / er
        _replace_mesh(pup, _patch_on_lens(lp, Rp, Rp, er, PUPIL_LIFT * er, PUPIL_DOME * er, 32, 6, None))
        d_l = q.inverted() @ Vector(GLINT['dir']).normalized()
        e = Vector((d_l.x, d_l.z)).normalized()
        lg = lp + e * GLINT['off']
        A = p['glint_r'] * GLINT['scale'][0] / er
        B = p['glint_r'] * GLINT['scale'][2] / er
        _replace_mesh(gli, _patch_on_lens(lg, A, B, er, GLINT['lift'] * er, 0.0, 32, 8, 'glint_w'))
        gli.data.materials.clear()
        gli.data.materials.append(_glint_material())
        collar = _collar('pb_orbit_' + side, c, a, q, er, scene, PB, p, result)
        result['parts'].append(collar)
        _EYES['c_' + side] = Vector(c)
        _EYES['q_' + side] = q.copy()
        _EYES['up_' + side] = q @ Vector((0.0, 0.0, 1.0))
        print(
            'R5EYES eye_%s: face normal (%.2f,%.2f,%.2f) = %.1f deg out / %.1f deg up; axis (%.2f,%.2f,%.2f) = %.1f out / %.1f up; '
            'centre (%.3f,%.3f,%.3f); apex %.1f mm above the face point, %.1f mm above the rim; pupil at planar (%.3f,%.3f) r, R %.3f r; glint at (%.3f,%.3f)'
            % (
                side,
                n.x,
                n.y,
                n.z,
                math.degrees(math.atan2(abs(n.x), -n.y)),
                math.degrees(math.asin(n.z)),
                a.x,
                a.y,
                a.z,
                math.degrees(math.atan2(abs(a.x), -a.y)),
                math.degrees(math.asin(a.z)),
                c.x,
                c.y,
                c.z,
                EYE_PROUD * er * 1000,
                (D - _lens_t(RIM_RHO)) * er * 1000,
                lp.x,
                lp.y,
                Rp,
                lg.x,
                lg.y,
            )
        )
    bpy.context.view_layer.update()


def _aim_eyes(cam):
    """R5EYES: the eyeball is a lens in a socket and never rotates; the gaze is the pupil."""
    return None


# ═════════════════════════════════════════════════════════════════════════════
# R5SKIN (lookdev2 r1_skin) — face-plate material, lips, micro-texture. Appended on top of
# r4_merge/merge.py; every name below shadows the R4SKIN binding because skin_post() /
# build_mouth_beak() / face_material() read module globals at call time.
#
# MEASURED FIRST (probe.py on the anchors vs r4_merge/run3): the anchor's between-the-eyes
# skin is #7FC6A1 (Lab L75 a-30 b+12: a yellow-GREEN mint; cell_11 bridge #74BCAF b-1) while
# r4 renders #53AEA8 front / #61BBB4 close (L66-71, b-5: a BLUE teal). The harness face gate
# (OpenCV H 70-105) starts exactly at the anchor bridge's hue (74.5) and drops its greener
# pixels, which is why the gated lab_face median said "6" for a face that reads deep teal.
# So: albedo R up / B down (hue toward green), lightness up; white dielectric sheen instead
# of the teal-tinted one (the anchor's lit patches are pale mint-white, not cyan).
# ═════════════════════════════════════════════════════════════════════════════
FACE_MID = (0.030, 0.085, 0.062)  # run1: from (0.012,0.068,0.077) — R x2.5, B x0.8
FACE_BROW_MUL = (
    1.15,
    1.10,
    1.05,
)  # run1: milder than (1.35,1.15,1.10); the anchor's brow/chin difference is mostly LIGHT, not albedo
FACE_CHIN_MUL = (
    0.95,
    0.95,
    0.88,
)  # run1: chin a touch warmer (less blue) so the warm belly bounce grades it yellow-green
FACE_ROUGH = 0.45
FACE_SPEC = 0.35
FACE_SPEC_TINT = (1.0, 1.0, 1.0)  # run1: white sheen (r4 tinted it (0.30,1.0,0.90) to keep R down — now R is wanted)
FACE_SSS = 0.30
FACE_SSS_RADIUS = (1.0, 0.60, 0.40)
FACE_SSS_SCALE = 0.006

# ── run2: face albedo corrected from run1's probe (bridge #8EBEA8 L73 a-20 b+6 vs anchor #AAE4B2 L85 a-28 b+18:
# hue right, saturation and lightness short) -> G x1.35, B x1.3, R x1.1. LIPS: r4's BEAK_RGB (0.121,0.021,0.003)
# rendered a dark red-brown bean (mouth-ID median #A65D27) vs the anchor's peach-tan #C57535/#D4853C -> albedo up
# (R x1.75, G x2.4, B x3), a thin clear-coat for the wet gloss, and the cavity lifted from near-black to a red-brown
# (cell_11's mouth interior is #5A2A20-ish, not black).
FACE_MID = (0.033, 0.115, 0.080)
BEAK_RGB = (0.21, 0.050, 0.010)
LOWLIP_RGB = (0.19, 0.045, 0.009)  # cell_11: the lower lip is the same peach as the upper, not a darker step
CAVITY_RGB = (0.060, 0.012, 0.010)
TONGUE_RGB = (0.080, 0.016, 0.012)
LIP_ROUGH = 0.30
LIP_SPEC = 0.45
LIP_COAT = 0.20
LIP_COAT_ROUGH = 0.10


def beak_material(m):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    nt, b = _principled_reset(m)
    b.inputs['Base Color'].default_value = (*BEAK_RGB, 1.0)
    b.inputs['Roughness'].default_value = LIP_ROUGH
    b.inputs['Specular IOR Level'].default_value = LIP_SPEC
    b.inputs['Subsurface Weight'].default_value = LIP_SSS
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.40, 0.20)
    b.inputs['Subsurface Scale'].default_value = 0.004
    b.inputs['Coat Weight'].default_value = LIP_COAT
    b.inputs['Coat Roughness'].default_value = LIP_COAT_ROUGH
    b.inputs['Coat IOR'].default_value = 1.5
    b.subsurface_method = 'RANDOM_WALK'
    return m


def cavity_material(m):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    nt, b = _principled_reset(m)
    b.inputs['Base Color'].default_value = (*CAVITY_RGB, 1.0)
    b.inputs['Roughness'].default_value = 0.45
    b.inputs['Specular IOR Level'].default_value = 0.4
    return m


# ── run3: MICRO-TEXTURE. cell_11's plate is fine dense pebbling (~2.5 mm pitch, 3-4 per cm, each a rounded dome with
# a tiny highlight) plus faint high-frequency sparkle; r4 had 3.3 mm soft goosebumps AND eight 2.5-3.8 mm glass beads
# which read as blobs/pimples from every view -> beads removed (DROPS = []), pebbles finer (scale 300 -> 380) and
# crisper (smoothness 0.35 -> 0.25, distance 1.5 -> 0.6 mm at strength 0.6: about the same 0.35 mm effective height
# but sharper dome normals), and a sparkle layer: ~0.5 mm dots (Voronoi F1 scale 600, dist < 0.15, half the cells
# kept by a noise gate) where roughness drops to 0.10 and specular rises to 0.9 so the key light reads as specks.
DROPS = []
BUMP_SCALE = 380.0
BUMP_SMOOTH = 0.25
BUMP_STRENGTH = 0.60
BUMP_DIST = 0.0006
SPARK = {'scale': 600.0, 'dot_r': 0.15, 'noise_scale': 90.0, 'noise_gt': 0.50, 'rough': 0.10, 'spec': 0.90}


def face_material(m):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    nt, b = _principled_reset(m)
    n, L = nt.nodes, nt.links
    b.inputs['Roughness'].default_value = FACE_ROUGH
    b.inputs['Specular IOR Level'].default_value = FACE_SPEC
    b.inputs['Subsurface Weight'].default_value = FACE_SSS
    b.inputs['Subsurface Radius'].default_value = FACE_SSS_RADIUS
    b.inputs['Subsurface Scale'].default_value = FACE_SSS_SCALE
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Coat Weight'].default_value = 0.0
    b.inputs['Sheen Weight'].default_value = 0.0
    b.inputs['Specular Tint'].default_value = (*FACE_SPEC_TINT, 1.0)
    tc = n.new('ShaderNodeTexCoord')
    sep = n.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Object'], sep.inputs[0])
    gz = n.new('ShaderNodeMapRange')
    gz.interpolation_type = 'SMOOTHSTEP'
    gz.inputs['From Min'].default_value = FACE_GRAD_Z[0]
    gz.inputs['From Max'].default_value = FACE_GRAD_Z[1]
    L.new(sep.outputs['Z'], gz.inputs['Value'])
    chin = tuple(c * k for c, k in zip(FACE_MID, FACE_CHIN_MUL))
    brow = tuple(c * k for c, k in zip(FACE_MID, FACE_BROW_MUL))
    fmix = n.new('ShaderNodeMix')
    fmix.data_type = 'RGBA'
    fmix.blend_type = 'MIX'
    fmix.inputs[6].default_value = (*chin, 1.0)
    fmix.inputs[7].default_value = (*brow, 1.0)
    L.new(gz.outputs['Result'], fmix.inputs[0])
    # sparse gold flecks (r4): large cells, tiny dots, low emission
    fv = n.new('ShaderNodeTexVoronoi')
    fv.voronoi_dimensions = '3D'
    fv.feature = 'F1'
    fv.inputs['Scale'].default_value = FLECK['cell_scale']
    fv.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], fv.inputs['Vector'])
    flt = n.new('ShaderNodeMath')
    flt.operation = 'LESS_THAN'
    flt.inputs[1].default_value = FLECK['dot_r']
    L.new(fv.outputs['Distance'], flt.inputs[0])
    fn = n.new('ShaderNodeTexNoise')
    fn.inputs['Scale'].default_value = FLECK['noise_scale']
    fn.inputs['Detail'].default_value = 1.0
    L.new(tc.outputs['Object'], fn.inputs['Vector'])
    fgt = n.new('ShaderNodeMath')
    fgt.operation = 'GREATER_THAN'
    fgt.inputs[1].default_value = FLECK['noise_gt']
    L.new(fn.outputs['Fac'], fgt.inputs[0])
    fzg = n.new('ShaderNodeMapRange')
    fzg.interpolation_type = 'SMOOTHSTEP'
    fzg.inputs['From Min'].default_value = FLECK['z0']
    fzg.inputs['From Max'].default_value = FLECK['z1']
    L.new(sep.outputs['Z'], fzg.inputs['Value'])
    f1 = n.new('ShaderNodeMath')
    f1.operation = 'MULTIPLY'
    L.new(flt.outputs[0], f1.inputs[0])
    L.new(fgt.outputs[0], f1.inputs[1])
    fl = n.new('ShaderNodeMath')
    fl.operation = 'MULTIPLY'
    L.new(f1.outputs[0], fl.inputs[0])
    L.new(fzg.outputs['Result'], fl.inputs[1])
    gmix = n.new('ShaderNodeMix')
    gmix.data_type = 'RGBA'
    gmix.blend_type = 'MIX'
    L.new(fmix.outputs[2], gmix.inputs[6])
    gmix.inputs[7].default_value = (*FLECK['rgb'], 1.0)
    L.new(fl.outputs[0], gmix.inputs[0])
    L.new(gmix.outputs[2], b.inputs['Base Color'])
    b.inputs['Emission Color'].default_value = (*FLECK['rgb'], 1.0)
    fem = n.new('ShaderNodeMath')
    fem.operation = 'MULTIPLY'
    fem.inputs[1].default_value = FLECK['emit']
    L.new(fl.outputs[0], fem.inputs[0])
    L.new(fem.outputs[0], b.inputs['Emission Strength'])
    # R5SKIN pebbling: rounded domes ~2.6 mm pitch
    vb = n.new('ShaderNodeTexVoronoi')
    vb.voronoi_dimensions = '3D'
    vb.feature = 'SMOOTH_F1'
    vb.inputs['Scale'].default_value = BUMP_SCALE
    vb.inputs['Smoothness'].default_value = BUMP_SMOOTH
    vb.inputs['Randomness'].default_value = 0.9
    L.new(tc.outputs['Object'], vb.inputs['Vector'])
    bump = n.new('ShaderNodeBump')
    bump.invert = True
    bump.inputs['Strength'].default_value = BUMP_STRENGTH
    bump.inputs['Distance'].default_value = BUMP_DIST
    L.new(vb.outputs['Distance'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    # R5SKIN sparkle: sub-mm glossy specks
    sv = n.new('ShaderNodeTexVoronoi')
    sv.voronoi_dimensions = '3D'
    sv.feature = 'F1'
    sv.inputs['Scale'].default_value = SPARK['scale']
    sv.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], sv.inputs['Vector'])
    slt = n.new('ShaderNodeMath')
    slt.operation = 'LESS_THAN'
    slt.inputs[1].default_value = SPARK['dot_r']
    L.new(sv.outputs['Distance'], slt.inputs[0])
    sn = n.new('ShaderNodeTexNoise')
    sn.inputs['Scale'].default_value = SPARK['noise_scale']
    sn.inputs['Detail'].default_value = 1.0
    L.new(tc.outputs['Object'], sn.inputs['Vector'])
    sgt = n.new('ShaderNodeMath')
    sgt.operation = 'GREATER_THAN'
    sgt.inputs[1].default_value = SPARK['noise_gt']
    L.new(sn.outputs['Fac'], sgt.inputs[0])
    sp = n.new('ShaderNodeMath')
    sp.operation = 'MULTIPLY'
    L.new(slt.outputs[0], sp.inputs[0])
    L.new(sgt.outputs[0], sp.inputs[1])
    rmix = n.new('ShaderNodeMix')
    rmix.data_type = 'FLOAT'
    rmix.inputs[2].default_value = FACE_ROUGH
    rmix.inputs[3].default_value = SPARK['rough']
    L.new(sp.outputs[0], rmix.inputs[0])
    L.new(rmix.outputs[0], b.inputs['Roughness'])
    smix = n.new('ShaderNodeMix')
    smix.data_type = 'FLOAT'
    smix.inputs[2].default_value = FACE_SPEC
    smix.inputs[3].default_value = SPARK['spec']
    L.new(sp.outputs[0], smix.inputs[0])
    L.new(smix.outputs[0], b.inputs['Specular IOR Level'])
    print(
        'R5SKIN face albedo mid=%s brow=%s chin=%s rough %.2f spec %.2f sss %.2f pebble %.0f/%.1fmm sparkle %.0f'
        % (
            FACE_MID,
            tuple(round(v, 3) for v in brow),
            tuple(round(v, 3) for v in chin),
            FACE_ROUGH,
            FACE_SPEC,
            FACE_SSS,
            BUMP_SCALE,
            BUMP_DIST * 1000 * BUMP_STRENGTH,
            SPARK['scale'],
        )
    )
    return m


# ── run4: three nudges along directions runs 1-3 established. Face: run3 bridge #95CBB5 (L78 a-22 b+6) vs anchor
# #AAE4B2 (L85 a-28 b+18) -> G x1.10, B x1.07 (more green saturation, +3 L). Lips: run3 mouth-ID median #C18B48
# (L62 a+14 b+35) vs anchor #C57535 (L57 a+23 b+47): ochre, short of red -> G x0.8, B x0.6, R x1.14. Sparkle: run3's
# 0.5 mm specks were invisible at 1024 px -> dots 0.15 -> 0.20 of a 1.7 mm cell (~0.7 mm), roughness 0.10 -> 0.05.
FACE_MID = (0.033, 0.127, 0.086)
BEAK_RGB = (0.24, 0.040, 0.006)
LOWLIP_RGB = (0.215, 0.036, 0.0055)
SPARK.update({'dot_r': 0.20, 'rough': 0.05})


# ═════════════════════════════════════════════════════════════════════════════
# R5 LIGHT (lookdev2 / r1_light) — lights, backdrop, floor, LENS. Critic (phase-2 round 1):
#   crown fur clips to pure white (base: 43% of crown px have min(RGB) >= 250, anchor 0%),
#   belly fur flat pale, key sits top-left while the anchor keys from upper camera-right.
# Everything below OVERRIDES the R3 LIGHT names above (LIGHTS is read at lighting() time).
#
# run1 — LENS ONLY. The repaired harness frames the BODY (fill 0.66 @ 85 mm), so in
#   side_left the S-tail left the frame on the right (base: silhouette 287..1023, cut) and
#   'aspect' / 'tail_above' / 'eye_frac' were measured on a truncated matte (-7.8% / -26.7% /
#   +23%). The anchor side has the body at ~0.6 of the frame and the tail reaching the far
#   edge: 80 mm + shift_x +0.137 (frame slides toward the tail, same camera position, so no
#   perspective change). close_front: cell_11's eye is 286-300 px wide against the base's
#   212-223 (x1.35) and sits at 1/3 from the top with the mouth at the centre: 142 mm,
#   shift_y -0.144. front_full / q45 keep the harness framing (anchor body fill 0.68 vs 0.66).
# ═════════════════════════════════════════════════════════════════════════════
_camera_r5form = camera  # R5MERGE: renamed -> wraps form R5CAM (fit) which wraps r4
LENS = {'side_left': (80.0, 0.137, 0.0), 'close_front': (142.0, 0.0, -0.144)}  # view: (lens mm, shift_x, shift_y)


def camera(cam, cam_data, view_id):
    _camera_r5form(cam, cam_data, view_id)
    L = LENS.get(view_id)
    if L:
        cam_data.lens, cam_data.shift_x, cam_data.shift_y = L
    else:
        cam_data.shift_x = cam_data.shift_y = 0.0
    print(
        'R5LIGHT camera %s lens=%.1f shift=(%.3f,%.3f)' % (view_id, cam_data.lens, cam_data.shift_x, cam_data.shift_y)
    )
    bpy.context.view_layer.update()


# ── run2: KEY INTENSITY x0.6 ──────────────────────────────────────────────────
# base front crown: 43% of px min(RGB) >= 250, 82% >= 245, median (249,253,252) vs anchor
# (216,243,225) with 0% clipped. The key ('key' 14 W general + 'furkey' 64 W fur-only,
# el ~60 deg) is what burns the up-pointing crown tufts. x0.6 on both.
LIGHTS['key'].update(W=14.0 * 0.6)
LIGHTS['furkey'].update(W=64.0 * 0.6)


# ── run3: KEY POSITION az 40 deg camera-right, el 35 deg ─────────────────────
# run2 (x0.6) took the crown from 43% to 3.3% clipped (min RGB >= 250) but 51% of it is
# still >= 245 and the median (245,251,249) is white, not the anchor's mint (216,243,225):
# the key at el ~60 deg / az 8 deg looks straight down onto the up-pointing crown tufts.
# The anchor keys from upper camera-right: the right flank is cream, the crown is lit
# obliquely. Same distance (1.5 S) at az 40 / el 35: (0.79, -0.94, 0.86) S.
_KEY_POS = (
    1.5 * math.cos(math.radians(35)) * math.sin(math.radians(40)),
    -1.5 * math.cos(math.radians(35)) * math.cos(math.radians(40)),
    1.5 * math.sin(math.radians(35)),
)
LIGHTS['key'].update(pos=_KEY_POS)
LIGHTS['furkey'].update(pos=_KEY_POS)


# ── run4: KEY 3800 K + COOL FILL 7000 K at 25% of the key ────────────────────
# run3 (key at az 40 / el 35) put the crown at (237,246,244) and the right flank at
# (246,249,244) — WHITE. Anchor patches (anchor_full, 24 px medians): flankR mid
# (250,238,173) cream-yellow, flankR low (246,174,75) orange, crown top (222,252,244)
# mint-white, crown left (175,230,226) mint-cyan. So the key is WARM and the crown's mint
# comes from a cool light on the upper camera-LEFT. 3800 K on the Planck locus is linear
# sRGB (1.00,0.62,0.33); 7000 K is (0.91,0.89,1.00). The key is split general/fur-only
# (8.4 + 38.4 W): the cool fill copies the split at 25% (2.1 + 9.6 W) from the upper
# left front (-0.85,-0.55,1.15) S, el ~50 deg, a 0.9 S disk (soft). The R3 'mint' (3 W,
# upper-left-BACK, crown) stays.
K3800 = (1.00, 0.62, 0.33)
K7000 = (0.91, 0.89, 1.00)
LIGHTS['key'].update(rgb=K3800)
LIGHTS['furkey'].update(rgb=K3800)
LIGHTS['coolfill'] = dict(pos=(-0.85, -0.55, 1.15), W=14.0 * 0.6 * 0.25, size=0.90, rgb=K7000, aim='upper')
LIGHTS['coolfur'] = dict(pos=(-0.85, -0.55, 1.15), W=64.0 * 0.6 * 0.25, size=0.90, rgb=K7000, aim='upper')
FUR_ONLY = FUR_ONLY + ('coolfur',)


# ── run5: COOL FILL -> 60% of the key, aimed at the CROWN; WARM belly accent x2 ──────
# run4: crown clipping 0% (acceptance met) but the crown went yellow-white (245,245,239),
# a 127 / b 131, vs the anchor crown (213,245,234) a 115 / b 129: at 25% the 7000 K fill
# loses the crown to the 3800 K key. Anchor crown-left (175,230,226) is mint-CYAN, so the
# cool light is the crown's dominant light. Cool fill 60% of the key (5.0 + 23.0 W), moved
# up and further left (el 55 / az -50: (-0.66,-0.55,1.23) S) and aimed at the crown
# (c + 0.30 S up); the key keeps the right flank. Belly: anchor low-right flank
# (246,174,75) and low belly (150,91,33) are orange-caramel; ours (222,206,158) is pale.
# 'warm' (7 W, creature-linked) + 'warmfur' (13 W, fur-only) at low front-right x2.
_COOL_POS = (
    1.5 * math.cos(math.radians(55)) * math.sin(math.radians(-50)),
    -1.5 * math.cos(math.radians(55)) * math.cos(math.radians(-50)),
    1.5 * math.sin(math.radians(55)),
)
LIGHTS['coolfill'].update(pos=_COOL_POS, W=14.0 * 0.6 * 0.60, aim='crown')
LIGHTS['coolfur'].update(pos=_COOL_POS, W=64.0 * 0.6 * 0.60, aim='crown')
LIGHTS['warm'].update(W=7.0 * 2.0)
LIGHTS['warmfur'].update(W=13.0 * 2.0)


# ── run6: EXPOSURE RESTRUCTURE — the fur is flooded; the anchor is GRADED top->bottom ──
# run5 went the wrong way: the 7000 K fill at 60% did not tint the crown, it whitened it
# (crown (248,249,247), 62% >= 245) and the warm x2 made the belly PALER (233,220,177),
# because under Filmic any extra light on a near-white fur pushes it to white. Anchor
# zones: crown L 240-246 (mint), chest L 170 (tan), low belly L 95 (caramel-brown),
# flankR L 239 (cream-yellow). Ours: crown 250, chest 224, low belly 224. The lower body
# is ~1-1.5 stops too bright and the crown ~0.3. So:
#  * key 8.4 -> 6 W, furkey 38.4 -> 22 W (the key also stops lighting the floor: see below)
#  * the cool light becomes a MINT (0.62,1.0,0.82) at 35% of the key (2.5 + 14 W) — a
#    tinted light can colour a bright crown, a neutral one cannot (R3's Filmic sweep)
#  * warm accent back to 7 / 13 W (reverting run5's x2)
#  * KEY light-linked to the creature (all pb_* incl. feet, not the floor): the anchor floor
#    in front of the feet is (52,44,38), ours (104..136) — mostly the key on the floor
#  * floor: warm dark base (0.030,0.024,0.018), rough 0.45, spec 0.12 (anchor: faint warm
#    reflection, not a mirror pool)
MINT2 = (0.62, 1.00, 0.82)
LIGHTS['key'].update(W=6.0)
LIGHTS['furkey'].update(W=22.0)
LIGHTS['coolfill'].update(W=2.5, rgb=MINT2)
LIGHTS['coolfur'].update(W=14.0, rgb=MINT2)
LIGHTS['warm'].update(W=7.0)
LIGHTS['warmfur'].update(W=13.0)
GROUND.update(rgb=(0.030, 0.024, 0.018), rough=0.45, spec=0.12)
KEY_LINKED = ('key',)  # creature incl. legs/feet/toes, never the floor

_lighting_r3 = lighting


def lighting(scene, centre, size, aim):
    _lighting_r3(scene, centre, size, aim)
    for name in KEY_LINKED:
        o = bpy.data.objects.get(name)
        if o is not None:
            _link_prefix(scene, o, 'pb_key_receivers', ('pb_',), exclude=('pb_ground',))


# ── run7 (FINAL): general key back to KEYC; fur key/mint rebalanced ───────────────────
# The profile eye disappeared from the harness from run4 on: under a 3800 K GENERAL key the
# cream lid bezel (pb_lid) beside the iris passes the amber gate (S > 110) and merges with
# the iris+pupil blob (run3 85x102 px, dark 16% -> run6 105x133, dark 9.9% < the 10% pupil
# test) — an eye_frac inflated +29% even when found. Only the fur wants the warm key, so the
# general 'key' (face, lids, eyes, arms, feet) returns to the mint-white KEYC and only
# 'furkey' stays 3800 K. Crown: run6 (241,245,237) has a 4-point G-R spread vs the anchor's
# 32 (213,245,234): mint fur light 14 -> 20 W, fur key 22 -> 18 W (crown irradiance ~+10%,
# well under the run5 level that clipped; the right flank loses ~0.2 stop, which under
# Filmic also makes it yellower).
LIGHTS['key'].update(rgb=KEYC)
LIGHTS['furkey'].update(W=18.0)
LIGHTS['coolfur'].update(W=20.0)


# ═════════════════════════════════════════════════════════════════════════════
# R5MERGE — lookdev2 round-1 merge on r4_merge: form (R5FORM+R5CAM) + fur_hair (R5 FUR-HAIR, the
# chosen coat; fur_tuft's geometry locks are NOT in this file) + eyes (R5EYES) + skin (R5SKIN) +
# light (R5 LIGHT). Sections above are verbatim except two renames:
#  * form's and light's camera wrappers BOTH captured `_camera_r4 = camera`; concatenated, form's
#    camera would call itself. form's is `_camera_r4m`, light's `_camera_r5form`, so the chain is
#    light.camera (close-up LENS) -> form.camera (fit / close zoom) -> r4 (gaze aim, a no-op with
#    R5EYES) -> r3 (DOF off, bokeh, view transform).
# Conflicts resolved here:
#  1. CAMERA. form's R5CAM re-fits every body view on the padded bounds of all pb_ parts (generic:
#     it follows whatever tail the merge has); light's LENS fixed an 80 mm + shift_x for side_left
#     tuned to the r4 tail. Body views take form's fit (light's side_left entry removed); the head
#     close-up takes light's 142 mm + shift_y -0.144 (cell_11's crop: eyes at 1/3, mouth centred)
#     and form's CLOSE_ZOOM is 1.0 so the two zooms do not stack (0.77 x 1.35 = a 1.75x crop).
#  2. EYES. form: eye_r 0.058 -> 0.053, sep 0.068, eye_z +10 mm (the anchor eye line is higher and
#     the 0.058 eye overhung the cap). eyes: a recessed 0.34-deep lens whose visible disc is
#     RIM_RHO x er (0.85 x 0.058 = 0.0493 m passed front eye_frac at +0.9 %). Both are taken: the
#     smaller eye at form's position, and RIM_RHO 0.85 -> 0.92 so the VISIBLE disc stays 0.0488 m
#     (eye_frac is linear in it: 0.053 x 0.85 = 0.045 would read ~-8 %). The pupil keeps eyes'
#     0.60 of the visible radius (0.0293) and the glint its 0.28 (0.0135). Everything the eyes
#     section derives from RIM_RHO at import (EYE_PROUD, COLLAR rho_in, BANDS5, IRIS_MASK5) is
#     recomputed below. eyes' and form's pupil_r/glint_r for the other eye size are overridden.
#  3. DROPLETS. form moved two dew droplets clear of its raised eye; skin removed all of them
#     (they read as pimples from every view). skin wins: DROPS is [] (bound last, read at call time).
#  4. Everything else composes by construction: form's mouth GEOMETRY + skin's lip/cavity
#     MATERIALS; form's R4F['tri'] (widest bald knot at eye height) + fur_hair's brow band (a max
#     inside _tri_s); eyes' collar is named pb_orbit_* so fur_hair's mound tufts, R4MERGE's
#     temple/cap cuts and light's face-only light all find it; eyes' _orbit_material returns
#     pb_skin_face, i.e. skin's new plate material; light's KEY_LINKED links 'key' by the pb_
#     prefix, which covers every part the merge builds.
# ═════════════════════════════════════════════════════════════════════════════
LENS.pop('side_left', None)  # 1. body views: form's fit
CLOSE_ZOOM = 1.0  # 1. close-up: light's lens+shift only
PARAMS.update(
    {
        'eye_r': 0.053,
        'eye_sep': 0.068,
        'eye_z': 0.072,  # 2. form's eye size / position
        'pupil_r': 0.0293,
        'glint_r': 0.0135,
    }
)  # 2. eyes' fractions of the visible disc
RIM_RHO = 0.92  # 2. visible disc 0.92 x 0.053 = 0.0488 m
EYE_PROUD = EYE_DEPTH * (1.0 - math.sqrt(1.0 - RIM_RHO**2))  # apex 0.207 r = 11 mm above the face point
COLLAR['rho_in'] = RIM_RHO - 0.09
BANDS5 = _rim_bands(RIM_RHO)
IRIS_MASK5 = [(_u(RIM_RHO * 1.0), (0, 0, 0)), (_u(RIM_RHO * 0.955), (1, 1, 1)), (1.0, (1, 1, 1))]
print(
    'R5MERGE: eye_r %.3f sep %.3f z %.3f rim %.2f -> visible %.4f m, pupil %.4f, glint %.4f; close-up lens %s; CLOSE_ZOOM %.2f'
    % (
        PARAMS['eye_r'],
        PARAMS['eye_sep'],
        PARAMS['eye_z'],
        RIM_RHO,
        RIM_RHO * PARAMS['eye_r'],
        PARAMS['pupil_r'],
        PARAMS['glint_r'],
        LENS.get('close_front'),
        CLOSE_ZOOM,
    )
)


# ── R5MERGE run2 — three composition corrections read off run1 (each in its own region) ─────
# a) FACE too light. Every dimension lifted the plate a little (eyes' collar +9 L, skin +9, light
#    +3, fur_hair +3 on the gated median) and together the bridge rendered L193 (8-bit Lab) vs
#    cell_11's 168 and anchor_full's 145 (probed at the same spot); gated front lab_face 32 (base 6,
#    skin alone 14). Albedo x0.71 (the ~L ratio ^2.2) with B held up so the hue stops drifting
#    yellow (b 134 vs 129): FACE_MID (0.033,0.127,0.086) -> (0.023,0.090,0.072). Brow/chin
#    multipliers stay skin's.
# b) PROFILE EYE covered from ABOVE. R4MERGE's _mound_fur roots tufts where the world-space eye
#    test n is 1.02..1.12; on eyes' collar that is the crest right at the lens edge, so 35 mm
#    tufts sit ON the upper rims (the white eyebrows in front) and drape over the whole eye in
#    profile (run1 side: amber sliver, no pupil, eye_frac None). Roots pushed out to n 1.25..1.40
#    (the collar skirt, still teal skin as in the anchor) and the tufts shortened to 28 mm; the
#    temple wisps go from fur_hair's 0.75 back toward R4MERGE's 0.5 (0.60) because at 0.75 the
#    forward-leaning temple locks reach the profile eye again.
# c) TAIL NOTCH. Measured on the side silhouettes (tail column / ball width per row): the column
#    is already as thin as the anchor's (0.11/0.15/0.19 vs 0.16/0.17/0.21 at 0.12/0.20/0.30 h),
#    so fur_hair's 0.6 r tail fur stays. What is missing is the gap: the anchor's column stays
#    separate down to 0.50 h with a notch of 0.12 ball-widths; ours merges at 0.40-0.50 h with
#    0.04. form's column knots (index >= 3) move back +0.05 m in y (notch +~55 px), and the tip
#    rises 15 mm (side tail_above -15 % -> ~-7 %; costs the front aspect ~2.6 points of its 3.4).
FACE_MID = (0.023, 0.090, 0.072)
MOUND_HAIR.update({'n0': 1.25, 'n1': 1.40, 'len': 0.028})
TEMPLE_CUT.update({'f': 0.60})
_TK = list(R5_TAIL_KNOTS)
R5_TAIL_KNOTS = (
    _TK[:3] + [(x, y + 0.05, z) for (x, y, z) in _TK[3:-1]] + [(_TK[-1][0], _TK[-1][1] + 0.05, _TK[-1][2] + 0.015)]
)
PARAMS['tail_knots'] = R5_TAIL_KNOTS
print(
    'R5MERGE run2: FACE_MID %s; mound tufts n %.2f..%.2f len %.3f; temple cut %.2f; tail column +0.05 y, tip z %.3f'
    % (FACE_MID, MOUND_HAIR['n0'], MOUND_HAIR['n1'], MOUND_HAIR['len'], TEMPLE_CUT['f'], R5_TAIL_KNOTS[-1][2])
)


# ── R5MERGE run3 — face albedo step 2; profile eye shape ────────────────────────────────────
# a) run2 bridge rendered L182 (cell_11 168, anchor_full 145): AgX compresses this range, run2's
#    x0.71 bought only 11 L. Another x0.72: FACE_MID (0.023,0.090,0.072) -> (0.0166,0.065,0.052),
#    same hue ratios. Expected bridge ~L168; gated front lab_face 23 should fall toward the gate.
# b) PROFILE EYE: the ID pass (hair off) shows nothing occludes it — the recessed 0.34-deep lens at
#    31 deg out simply projects as a 45 x 107 px oval (w/h 0.42) and find_eyes rejects boxes under
#    0.6; the anchor's profile eye is 0.66 because it is a bulging ball (its front oval 0.84 and
#    profile 0.66 are only both possible with a real dome). Middle ground, not r4's frog eye
#    (0.62 deep, 0.45 proud, camera-aimed): EYE_DEPTH 0.34 -> 0.42 (apex 13.5 mm above the rim,
#    was 11; r4 23) and EYE_AXIS_AZ 0.92 -> 1.05 (31 -> 35.4 deg out = the face normal's own
#    azimuth the eyes section measured; front oval cos 35 = 0.82, anchor 0.84). EYE_PROUD and the
#    fur-exclusion depth follow. Pupil / glint / collar fractions unchanged.
FACE_MID = (0.0166, 0.065, 0.052)
EYE_DEPTH = 0.42
EYE_AXIS_AZ = 1.05
EYE_PROUD = EYE_DEPTH * (1.0 - math.sqrt(1.0 - RIM_RHO**2))
EYE_DEPTH_FUR = max(EYE_DEPTH_FUR, EYE_DEPTH)
print(
    'R5MERGE run3: FACE_MID %s; EYE_DEPTH %.2f (apex %.1f mm above rim) axis az x%.2f'
    % (FACE_MID, EYE_DEPTH, (EYE_DEPTH - EYE_DEPTH * math.sqrt(1 - RIM_RHO**2)) * PARAMS['eye_r'] * 1000, EYE_AXIS_AZ)
)


# ── R5MERGE run4 (FINAL) — close-up lens only ────────────────────────────────────────────────
# run3 passes every gated shape number in front_full and side_left; the one remaining 'ok'
# failure is close_front eye_frac +8.1 % (anchors.json 0.242): light tuned the 142 mm close-up
# on the r4 eye, and the merged eye (recessed lens, no bezel, form's position) fills 8 % more of
# the frame. Camera only: 142 -> 131 mm (x0.92), shift_y kept. Nothing else changes.
LENS['close_front'] = (131.0, 0.0, -0.144)
print('R5MERGE run4: close_front lens %s' % (LENS['close_front'],))


# ═════════════════════════════════════════════════════════════════════════════
# R6 FUR-HAIR (lookdev2 round 2 / r2_fur_hair) — PROFILE CHEEK CUT-OUT
#
# Critic (after round 1, [major]): in side_left only the eye and the lip pad show; the coat
# reaches the eye's rear rim and covers the whole cheek. The anchor side shows a bare pale-mint
# wedge from the brow crest through the eye down to the chin, ~0.6 eye-widths of bare cheek
# behind the eye and bare skin below it down to the lip.
#
# MEASURED FIRST (probe_side.py on the r1_merge base: every hair system's PARENT paths, world
# space; a strand 'occludes' when a key sits in front of the plate ellipsoid inside the wedge
# y < -0.075, z > -0.030 seen from the profile camera). The ID pass shows the plate itself
# already reaches ~0.7 eye-widths behind the eye's rear edge (y -0.132 -> -0.064 body-local at
# eye height) and down to the lip — the plate is NOT the problem, the roots on and under it are:
#     pb_cap_tufts   (plate, 50 mm x 80 children)  1066 / 2500 parents occlude
#     pb_cap_under   (plate, 35 mm)                  622 / 1600
#     pb_orbit_r     (collar-top 'eyebrow' tufts)    155 /  700   (the camera-side collar)
#     pb_undercoat   (body, 30 mm)                    90 / 2500
#     pb_tufts       (body, 105 mm x 110)             38 /  650   (~4000 child strands)
#     fringe                                            3
# The cap roots sit on the lower cheek (y -0.10..-0.16, z -0.02..+0.04, i.e. |x| 0.08-0.12 just
# outside the bald triangle's (0.010, 0.080) knot) and on the temple behind the eye; the body
# roots at (0.087, -0.12, -0.01) are INSIDE the plate ellipsoid (t 0.89) and grow out through
# its cheek surface. TEMPLE_CUT (body roots x > 0.09, y < -0.07 at eye height) only shortens
# locks that were never the cover — hence 'TEMPLE_CUT 0.60 alone is not enough'.
#
# THE CUT (one rule, applied to every system that roots on or under the plate):
#   wedge  = |x| > X_SIDE  and  Z_JAW < z < Z_TOP        (body-local metres)
#   * pb_face cap_density -> 0 in the wedge (6 mm feather). Every plate point with |x| > 0.082
#     has y < -0.08, so this is exactly the side-facing cheek + temple; the front-facing plate
#     (|x| < 0.082, the anchor front's bare V is +-0.078 at mouth level) keeps its cheek fur.
#   * pb_body fur_density -> 0 for roots inside the plate ellipsoid (t < 1.04, front half): a
#     root under the plate can only emerge THROUGH it. Also 0 in the wedge for y < Y_BACK.
#   * the mound/collar tufts go: with the R5EYES skin collar there is no bezel skirt left to
#     hide, and their only remaining job was eyebrows on the brow the anchor shows bare.
#   * fringe groups -> 0 in the wedge (3 occluders; consistency).
# The two anchors disagree here by construction (front: fur beside the mouth from |x| 0.078;
# side: bare cheek back to y -0.075); the critic chose the profile, so the front view gains a
# ~15-25 mm bare band beside the outer-lower eye where the plate's side face is seen obliquely.
# ═════════════════════════════════════════════════════════════════════════════
CHEEK6 = {
    'x_side': 0.082,
    'z_jaw': -0.030,
    'z_top': 0.150,
    'y_back': -0.075,
    'feather': 0.006,
    'plate_t': 1.04,
    'mound': 0.0,
}


def _wedge_w(x, y, z):
    """0 inside the bare cheek wedge -> 1 outside, feathered over CHEEK6['feather'] (body-local)."""
    C = CHEEK6
    s = min(abs(x) - C['x_side'], z - C['z_jaw'], C['z_top'] - z)  # >0 inside
    return min(1.0, max(0.0, 0.5 - s / C['feather']))


# ── run2: the cut is a SLAB IN Y behind the eye, not everything lateral ───────────────────
# run1 (|x| > 0.082 -> every plate root off, all buried body roots off, collar tufts off) bared
# the profile cheek, but overshot: the visible boundary fell back to the plate/body rim (y -0.064
# body-local, ~1.0 profile-eye-widths behind the eye's rear edge at -0.132) because the temple
# plate roots at x 0.110-0.122 (y -0.114..-0.064, the only plate roots outside the eye exclusion
# at eye height) were cut too; from the front and at 45 deg the plate then read as a bald teal
# helmet with a fur wall behind it, and the V-edge fur beside the mouth (chin body roots that
# grow through the plate's lower rim + cap roots at |x| 0.08-0.09) was gone.
# Geometry, plate at eye height: eye rear edge y -0.132; the 3D eye exclusion (R4F eye_r1) ends at
# x 0.110 / y -0.114; plate/body junction x 0.122 / y -0.064. Lower cheek (z 0): x 0.09 <-> y -0.139,
# junction x 0.113 <-> y -0.100. The anchor's 0.6 profile-eye-widths (eye 82 px wide of a 560 px
# ball; ours ~44 mm foreshortened) puts the wanted boundary at y ~ -0.105 at eye level, tapering
# to the eye's rear edge at the brow crest (anchor: the crest comes down to the eye line).
# So the plate cut is: |x| > 0.090 AND Y_BACK(z) > y, Y_BACK -0.105 at/below eye level -> -0.130
# at the brow; the V-edge roots (|x| < 0.090, in front of the eye's rear edge) and the plate's rear
# sliver (y > Y_BACK, lying back over the junction) stay. Body roots buried in the plate are cut
# only for |x| > 0.082 (the chin ones under the V are the beard's top and never reach the wedge).
CHEEK6.update(
    {'x_side': 0.090, 'x_body': 0.082, 'y_back_eye': -0.105, 'y_back_brow': -0.130, 'z_eye': 0.072, 'z_brow': 0.125}
)


def _y_back(z):
    C = CHEEK6
    t = min(1.0, max(0.0, (z - C['z_eye']) / (C['z_brow'] - C['z_eye'])))
    return C['y_back_eye'] + (C['y_back_brow'] - C['y_back_eye']) * t


def _wedge_w(x, y, z):
    """0 inside the bare cheek wedge (lateral of X_SIDE, in front of Y_BACK(z), between the jaw
    and the crest) -> 1 outside, feathered (body-local metres)."""
    C = CHEEK6
    s = min(abs(x) - C['x_side'], _y_back(z) - y, z - C['z_jaw'], C['z_top'] - z)  # >0 inside
    return min(1.0, max(0.0, 0.5 - s / C['feather']))


def _plate_t(q, p, PB):
    """Plate-ellipsoid test for a BODY-LOCAL point q (<1 inside the scaled pb_face)."""
    r = p['face_r']
    cy, ry = _face_centre_scaled(p, PB)
    cz = p['face_z']
    rz = r * FACE_ZS
    return (q.x / r) ** 2 + ((q.y - cy) / ry) ** 2 + ((q.z - cz) / rz) ** 2


def _cheek_cut_post(p):
    PB = _R4_EYES.get('PB')
    C = CHEEK6
    face = _ob('pb_face')
    body = _ob('pb_body')
    if face is None or body is None:
        return
    off = Vector(face.location) - Vector(body.location)
    # 1. the plate's own fur (cap tufts + cap undercoat share 'cap_density')
    vgd = face.vertex_groups.get('cap_density')
    n_cap = 0
    if vgd is not None:
        for v in face.data.vertices:
            q = off + v.co
            w = _wedge_w(q.x, q.y, q.z)
            if w >= 1.0:
                continue
            try:
                w0 = vgd.weight(v.index)
            except RuntimeError:
                w0 = 0.0
            if w0 > 0.0:
                vgd.add([v.index], w0 * w, 'REPLACE')
                n_cap += 1
    # 2. body roots buried inside the plate, and body roots in the wedge behind the plate rim
    vgb = body.vertex_groups.get('fur_density')
    n_in = n_wedge = 0
    if vgb is not None:
        for v in body.data.vertices:
            x, y, z = v.co.x, v.co.y, v.co.z
            if y > -0.02:
                continue
            f = 1.0
            if abs(x) > C.get('x_body', 0.0) and _plate_t(v.co, p, PB) < C['plate_t']:
                f = 0.0
                n_in += 1
            else:
                w = _wedge_w(x, y, z)
                if w < 1.0:
                    f = w
                    n_wedge += 1
            if f >= 1.0:
                continue
            try:
                w0 = vgb.weight(v.index)
            except RuntimeError:
                w0 = 0.0
            if w0 > 0.0:
                vgb.add([v.index], w0 * f, 'REPLACE')
        for gname in ('face_fringe_l', 'face_fringe_r'):
            vg = body.vertex_groups.get(gname)
            if vg is None:
                continue
            for v in body.data.vertices:
                w = _wedge_w(v.co.x, v.co.y, v.co.z)
                if w >= 1.0:
                    continue
                try:
                    w0 = vg.weight(v.index)
                except RuntimeError:
                    w0 = 0.0
                if w0 > 0.0:
                    vg.add([v.index], w0 * w, 'REPLACE')
    # 3. the collar tufts
    n_m = 0
    for side in ('l', 'r'):
        ob = _ob('pb_orbit_' + side)
        if ob is None:
            continue
        vg = ob.vertex_groups.get('orbit_density')
        if vg is None:
            continue
        for v in ob.data.vertices:
            try:
                w0 = vg.weight(v.index)
            except RuntimeError as _exc:
                _zyg_log.debug('vertex %s is not in the collar vertex group, skipped: %s', v.index, _exc)
                continue
            if w0 > 0.0:
                vg.add([v.index], w0 * C['mound'], 'REPLACE')
                n_m += 1
    print(
        'R6 cheek cut: wedge |x| > %.3f, z %.3f..%.3f; plate verts cut %d; body roots inside the plate %d, in the wedge %d; collar tufts x%.2f on %d verts'
        % (C['x_side'], C['z_jaw'], C['z_top'], n_cap, n_in, n_wedge, C['mound'], n_m)
    )


_post_build_r5merge = post_build


def post_build(scene, result, PB):
    _post_build_r5merge(scene, result, PB)
    _cheek_cut_post(dict(_P))
    bpy.context.view_layer.update()


# ── run3: LOWER CHEEK bare, TEMPLE tufts short + swept back ─────────────────────────────
# run2 (probe_side.py, wedge y < -0.105): nothing at eye height occludes any more — the
# 0.6-eye-width band behind the eye is there, but it is mostly the smooth skin collar, and it
# does not READ as bare cheek because (a) the V-edge cap fur (roots y -0.13..-0.17, z -0.03..0.02,
# |x| < 0.09: 596 tufts + 405 undercoat parents) follows the plate normal sideways past the
# narrowing lower plate and climbs the lower cheek up to the collar, and (b) the temple plate
# tufts at y > -0.105 (x 0.11-0.122) hang DOWN-forward as a curtain behind the collar instead
# of lying back along the head like the anchor's coat. (a) also bridged the eye and the amber
# lip pad into one blob for the harness (side eye_frac +27.7 % in run2, -1.8 % in run1).
#  * lower cheek: the lateral cut is |x| > 0.075 (the bald triangle's own edge) between the
#    mouth line (z -0.01) and the eye bottom (z 0.03); the chin band below z -0.01 keeps its
#    roots (they are the beard's top under the lip pad, which the anchor side does show).
#  * temple plate tufts lateral to the eye: CAP_SIDE_CUT f 0.5 -> 0.35 (11-13 mm), and the cap
#    align_back 0.15 -> 0.50 x normal_factor: the plate's rear-rim normal is (0.88,-0.22,0.42)
#    (out, a little forward, up); +0.5 y turns that ~15 deg back so the tufts lie over the
#    plate/body junction instead of leaning over the cheek.
CHEEK6.update({'x_side': 0.090, 'x_side_low': 0.075, 'z_low0': -0.010, 'z_low1': 0.030})
CAP_SIDE_CUT.update({'f': 0.35})
CAP_HAIR.update({'align_back': 0.50})


def _wedge_w(x, y, z):
    C = CHEEK6
    xs = C['x_side_low'] if C['z_low0'] <= z < C['z_low1'] else C['x_side']
    s = min(abs(x) - xs, _y_back(z) - y, z - C['z_jaw'], C['z_top'] - z)  # >0 inside
    return min(1.0, max(0.0, 0.5 - s / C['feather']))


# ── run4: SOFT EDGES on the cut — feather 6 -> 12 mm, temple tufts 0.35 -> 0.45 ─────────
# run3 reads right in structure (lower cheek bare down to the lip pad, temple coat lying back,
# 0.6 profile-eye-widths behind the eye once the skin collar is counted as the bare cheek it
# is), but both new edges are hard: at 45 deg the plate/body junction behind the eye is a step
# with a fur wall behind it, and from the front the bare band under the outer eyes (the same
# lower-cheek surface, seen at ~45 deg) has a crisp edge. The anchor's boundaries are soft —
# fur thins into the skin over ~10 mm. Same cut, twice the feather, temple tufts a little longer.
# HARNESS NOTE: side eye_frac (+27.7 % run2, +46.3 % run3, -1.8 % run1, None base) is NOT the
# eye: find_eyes returns a box at x 312-446 / y 677-800 (1024 px side render) — warm-lit belly
# fur beside the arm, whose shadow passes the >=10 % dark 'pupil' test — while the real profile
# eye (w/h ~0.42) fails the 0.6 roundness gate in every run, base included.
CHEEK6.update({'feather': 0.012})
CAP_SIDE_CUT.update({'f': 0.45})


# ── run5: collar tufts back on the BROW ARC only (side tail_above gate) ───────────────────
# Side tail_above went +0.9 % (base) -> +3.7 / +7.3 / +12.4 % (run1/3/4) with the TAIL NEVER
# MOVING: tip row 200 and widest row 547 are identical in every run. body_top is the first row
# wider than 0.55 x max (384 px) and rows 340-368 sit on a plateau at 378-393 px, so the crossing
# slides 16 rows on a 1 % width change. What changed there is the profile's FRONT edge at the
# crown-front level (row 344: base x 244, run1 266, run3/4 271-273) while the rear edge stayed
# at 831; the only cut common to runs 1-4 at that height is the collar tufts (zeroed whole), so
# their top arc — the brow tufts over the upper rims, which cell_11 does show — carried that
# edge. Restore the collar tufts on the brow arc only (lens-local up-cosine > 0.5); the temporal
# and lower arcs (the bare cheek) stay at zero.
CHEEK6.update({'mound_top': 1.0, 'mound_top_cos': 0.5})
_cheek_cut_post_run4 = _cheek_cut_post


def _cheek_cut_post(p):
    _cheek_cut_post_run4(p)
    C = CHEEK6
    n = 0
    for side in ('l', 'r'):
        ob = _ob('pb_orbit_' + side)
        vg = ob.vertex_groups.get('orbit_density') if ob is not None else None
        if vg is None:
            continue
        # _cheek_cut_post_run4 multiplied the whole group by C['mound'] (0): rebuild the brow arc from
        # the R4MERGE mask (world-space eye test + temporal thinning + bald triangle), top arc only
        M = MOUND_HAIR
        er = p['eye_r']
        c = _EYES.get('c_' + side)
        q = _EYES.get('q_' + side)
        a = (q @ Vector((0.0, -1.0, 0.0))).normalized()
        mw = ob.matrix_world
        body = _ob('pb_body')
        F = R4F['feather']
        sx = -1.0 if side == 'l' else 1.0
        for v in ob.data.vertices:
            rl = math.hypot(v.co.x, v.co.z)
            if rl < 1e-6 or v.co.z / rl <= C['mound_top_cos']:
                continue
            P = mw @ v.co
            d = P - c
            t = d.dot(a)
            rho = (d - a * t).length
            nn = math.sqrt((rho / er) ** 2 + (t / (EYE_DEPTH * er)) ** 2)
            w = min(1.0, max(0.0, (nn - M['n0']) / (M['n1'] - M['n0'])))
            outer = max(0.0, sx * v.co.x / rl)
            w *= (1.0 - outer) ** M['outer_den_pow']
            if body is not None:
                bl = P - Vector(body.location)
                w *= min(1.0, max(0.0, 0.5 - _tri_s_r4(bl.x, bl.z) / F))
            if w > 0.0:
                vg.add([v.index], w * C['mound_top'], 'REPLACE')
                n += 1
    print('R6 run5: collar brow-arc tufts restored on %d verts (up-cos > %.2f)' % (n, C['mound_top_cos']))


# ═════════════════════════════════════════════════════════════════════════════
# R6SKIN (lookdev2 r2_skin) — face-plate tone, socket cups, lips, micro-texture. Appended on
# top of lookdev2/r1_merge/merge.py (R5MERGE run4). Every name below shadows the earlier
# binding because skin_post() / face_material() / build_mouth_beak() / _orbit_material()
# read module globals at call time.
#
# MEASURED FIRST (probe3.py / darkmap.py on r1_merge/run4 = this round's base):
#   close_front face-ID L8 p10/p25/p50 = 134/156/181, 19 % of the plate below L150. The dark
#   zone is NOT the bridge (L168, anchor_full 218 / cell_11 179 — fine): it is the whole plate
#   BELOW the eye line — cheeks beside the lip L123-147 (#3E7D65..#5E9579), the muzzle strip
#   L139-147 — and the temporal half of each socket collar. Hue is already right (a -23..-27,
#   b +3..+10 vs the anchor bridge a-28 b+18 / cell_11 a-26 b-2); only L and the shadow spread
#   are wrong. Anchor teal-gate L8 p25/p50 = 126/150 (full) and 115/141 (cell_11) — so the
#   anchor plate also has shade, but its shade is a LIT pale mint (#82DBC5 under the eye).
# run1: FACE_MID (0.0166,0.065,0.052) -> (0.028,0.105,0.082): undo one of R5MERGE's two x0.71
#   steps (x1.66, hue ratios kept). Nothing else changes in this run.
# ═════════════════════════════════════════════════════════════════════════════
FACE_MID = (0.028, 0.105, 0.082)
print('R6SKIN run1: FACE_MID %s' % (FACE_MID,))


# ── run2: MINT SUBSURFACE + socket collar at the bridge's albedo ──────────────────────────
# run1 (albedo x1.66): plate below L150 19 % -> 8 %, bridge L168 -> 182 (cell_11 179) but the
# lower cheeks / muzzle strip stayed L147-168 and the temporal collar halves ~L150: the SPREAD
# between lit and shaded plate is what still reads as a mask. The gated lab_face went 14.5 ->
# 26.9 (front) because that median follows the lit bridge — the critic's caveat, noted; the
# spot targets (under-eye cheek L185-190, bridge <= 175, darkest >= 150) drive this round.
# SSS: r4/r5's radius (1.0,0.6,0.4) x 6 mm scatters R farthest, so the shade went olive/yellow
# (b +5..+10 vs the anchor's gated shade b -5). Mint radius (0.55,1.0,0.85) x 15 mm =
# (8, 15, 13) mm mean free path on a 260 mm plate, weight 0.30 -> 0.55: light entering the lit
# bridge/brow re-emerges in the socket recess and the lower cheeks, tinted mint.
# Collar: R5EYES' _orbit_material returned pb_skin_face itself, whose chin->brow gradient is
# evaluated in the COLLAR's object space (origin at the eye centre, +-0.074 m local z), so the
# socket floor wore the CHIN multiplier (0.95,0.95,0.88) and the hood the brow's (1.15,1.10,1.05).
# The collar now wears a copy with the gradient factor fixed at the bridge's value (0.66).
FACE_SSS = 0.55
FACE_SSS_RADIUS = (0.55, 1.0, 0.85)
FACE_SSS_SCALE = 0.015
ORBIT_GRAD_T = 0.66  # smoothstep((0.024 - (-0.055)) / 0.13): the between-the-eyes value of FACE_GRAD_Z


def _orbit_material(result):
    """R6SKIN run2: the socket collar wears the face skin at the BRIDGE's gradient value (a
    constant), not the chin->brow gradient evaluated in the collar's own object space."""
    m = bpy.data.materials.get('pb_skin_orbit')
    if m is not None:
        return m
    fm = bpy.data.materials.get('pb_skin_face')
    if fm is None:
        return result['mats']['skin']
    m = fm.copy()
    m.name = 'pb_skin_orbit'
    nt = m.node_tree
    fixed = 0
    for node in list(nt.nodes):
        if (
            node.type == 'MAP_RANGE'
            and abs(node.inputs['From Min'].default_value - FACE_GRAD_Z[0]) < 1e-6
            and abs(node.inputs['From Max'].default_value - FACE_GRAD_Z[1]) < 1e-6
        ):
            for lk in [l for l in nt.links if l.from_node == node]:
                sock = lk.to_socket
                nt.links.remove(lk)
                sock.default_value = ORBIT_GRAD_T
                fixed += 1
    print(
        'R6SKIN collar material: pb_skin_orbit, gradient factor fixed at %.2f (%d link(s) replaced)'
        % (ORBIT_GRAD_T, fixed)
    )
    return m


print(
    'R6SKIN run2: FACE_SSS %.2f radius %s scale %.3f (mfp mm %s); collar grad %.2f'
    % (
        FACE_SSS,
        FACE_SSS_RADIUS,
        FACE_SSS_SCALE,
        tuple(round(r * FACE_SSS_SCALE * 1000, 1) for r in FACE_SSS_RADIUS),
        ORBIT_GRAD_T,
    )
)


# ── run3: SSS REVERTED (measured inert); the plate's albedo gradient INVERTED to compensate the
# light fall-off. run2 (mint SSS 0.55 / 15 mm mfp + collar at the bridge albedo) changed nothing
# measurable: bridge L182 -> 180, lower cheeks 147 -> 143, plate < L150 8 % -> 8 %, hue b +4 -> +4.
# A 15 mm mean free path blurs features smaller than itself (bump, socket crease); the lit-to-
# shade fall-off across the plate is a ~100 mm feature of the key's geometry (upper camera-right,
# el 35: the plate below the eye line faces forward-DOWN and is grazed), so SSS cannot carry
# light into it. Vertical L profile of run1's close_front plate (centre column): brow 189, eye
# centre line 185-196, eye bottoms 162, just above the lip 149 (shade side 157-164). Face-LOCAL z
# (object coords, before the (1, 1.6, 0.75) scale; cz = body_lift 0.222 + face_z 0.038 = 0.260):
# eye centre (world 0.293) +0.044, eye bottoms -0.021, lip top ~ -0.060 (mouth centre -0.067).
# The anchor's plate is uniformly pale (under-eye #82DBC5 L208 even on its shade side), so the
# gradient the plate needs under THIS rig is chin > brow: brow multiplier 1.0 from z +0.030 up,
# smoothstep to x2.5 at z -0.060. FACE_MID = run1's effective bridge (0.030,0.111,0.081) x 0.8 so
# the bridge lands near the critic's <= L175 while the strip below the eyes gains ~1 stop.
FACE_SSS = 0.30  # base (r5) values back
FACE_SSS_RADIUS = (1.0, 0.60, 0.40)
FACE_SSS_SCALE = 0.006
FACE_MID = (0.024, 0.089, 0.066)
FACE_BROW_MUL = (1.0, 1.0, 1.0)
FACE_CHIN_MUL = (2.4, 2.5, 2.6)  # a touch bluer at the bottom: anchor under-eye a-31 b+3 vs bridge a-28 b+18
FACE_GRAD_Z = (-0.060, 0.030)
COLLAR_Z_OFF = -0.033  # collar object origin = eye centre (world z 0.293) vs face centre 0.260
COLLAR_Z_SCALE = 0.75  # the face object's z scale (FACE_ZS); the collar has scale 1


def _orbit_material(result):
    """R6SKIN run3: the socket collar wears a copy of the face skin whose gradient is re-based
    into the collar's own object space (origin at the eye centre, unscaled) so the chin->brow
    ramp is continuous across the collar/plate boundary."""
    m = bpy.data.materials.get('pb_skin_orbit')
    if m is not None:
        return m
    fm = bpy.data.materials.get('pb_skin_face')
    if fm is None:
        return result['mats']['skin']
    m = fm.copy()
    m.name = 'pb_skin_orbit'
    nt = m.node_tree
    fixed = 0
    for node in list(nt.nodes):
        if (
            node.type == 'MAP_RANGE'
            and abs(node.inputs['From Min'].default_value - FACE_GRAD_Z[0]) < 1e-6
            and abs(node.inputs['From Max'].default_value - FACE_GRAD_Z[1]) < 1e-6
        ):
            node.inputs['From Min'].default_value = FACE_GRAD_Z[0] * COLLAR_Z_SCALE + COLLAR_Z_OFF
            node.inputs['From Max'].default_value = FACE_GRAD_Z[1] * COLLAR_Z_SCALE + COLLAR_Z_OFF
            fixed += 1
    print(
        'R6SKIN collar material: pb_skin_orbit, gradient re-based to collar z %.3f..%.3f (%d node(s))'
        % (FACE_GRAD_Z[0] * COLLAR_Z_SCALE + COLLAR_Z_OFF, FACE_GRAD_Z[1] * COLLAR_Z_SCALE + COLLAR_Z_OFF, fixed)
    )
    return m


print(
    'R6SKIN run3: FACE_MID %s brow x%s chin x%s grad z %s; SSS back to %.2f'
    % (FACE_MID, FACE_BROW_MUL, FACE_CHIN_MUL, FACE_GRAD_Z, FACE_SSS)
)


# ── run4: lower plate x1.25 more + a bluer mid; LIPS ───────────────────────────────────────
# run3: bridge #7BB5A1 L177 a-24 b+4 (cell_11 bridge #6CB9B0 L179 a-26 b-2 — matched), plate
# below L150 8 % -> 4 %, no seam, q45/side clean. The strip under the eyes is L164-178 vs the
# critic's 185-190, so the ramp's bottom goes x2.5 -> x3.1 (the brow/bridge value is untouched);
# FACE_MID B +6 % (b +4 -> ~0) toward cell_11's hue.
# Lips: r1_merge mouth-ID median #C68242 (198,130,66) L8 154 a+20 b+40 vs the anchor's #D4853C /
# #C57535 (a+24..26, b+48..52): close, a touch brown-short of the peach. BEAK R x1.15 and G x1.1
# (the rendered lip hue follows luminance under AgX, so both go up), lower lip likewise; the
# cavity lifted from near-black (0.060,0.012,0.010) toward cell_11's #5A2A20 (lin ~0.10,0.023,0.014).
FACE_MID = (0.024, 0.089, 0.070)
FACE_CHIN_MUL = (3.0, 3.1, 3.2)
BEAK_RGB = (0.276, 0.044, 0.005)
LOWLIP_RGB = (0.247, 0.040, 0.005)
CAVITY_RGB = (0.100, 0.020, 0.015)
TONGUE_RGB = (0.110, 0.022, 0.016)
print(
    'R6SKIN run4: FACE_MID %s chin x%s; BEAK %s LOWLIP %s CAVITY %s'
    % (FACE_MID, FACE_CHIN_MUL, BEAK_RGB, LOWLIP_RGB, CAVITY_RGB)
)


# ── run5: MICRO-TEXTURE — discrete domes, not a cellular grain ──────────────────────────────
# run4: plate uniform L165-185 (3 % below L150; base 19 %), bridge L177, lips #CC8843 — kept.
# R5SKIN's relief is a SMOOTH_F1 Voronoi distance fed straight into the bump (scale 380, 0.36 mm):
# a continuous cellular grain that reads as leather / golf ball at the close-up. cell_11's plate
# is discrete rounded domes (~15-18 across the 57 mm bridge = ~3.5 mm pitch, ~2.5 mm across)
# with a tiny highlight each, over a SMOOTH plate. Domes = F1 distance -> smoothstep(1 - d/r)
# per cell (scale 290 = 3.4 mm cells, r 0.38 of a cell = 2.6 mm domes, ~35 % of the plate),
# bump NOT inverted (domes stand proud), 0.5 mm x 0.7 strength. Sparkle layer kept verbatim.
PEBBLE = {'scale': 290.0, 'rand': 0.85, 'dot_r': 0.38, 'edge': 0.06, 'dist': 0.0005, 'strength': 0.70}


def face_material(m):  # noqa: F811  cumulative look-dev file: later section shadows the earlier name on purpose (see module docstring)
    nt, b = _principled_reset(m)
    n, L = nt.nodes, nt.links
    b.inputs['Roughness'].default_value = FACE_ROUGH
    b.inputs['Specular IOR Level'].default_value = FACE_SPEC
    b.inputs['Subsurface Weight'].default_value = FACE_SSS
    b.inputs['Subsurface Radius'].default_value = FACE_SSS_RADIUS
    b.inputs['Subsurface Scale'].default_value = FACE_SSS_SCALE
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Coat Weight'].default_value = 0.0
    b.inputs['Sheen Weight'].default_value = 0.0
    b.inputs['Specular Tint'].default_value = (*FACE_SPEC_TINT, 1.0)
    tc = n.new('ShaderNodeTexCoord')
    sep = n.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Object'], sep.inputs[0])
    gz = n.new('ShaderNodeMapRange')
    gz.interpolation_type = 'SMOOTHSTEP'
    gz.inputs['From Min'].default_value = FACE_GRAD_Z[0]
    gz.inputs['From Max'].default_value = FACE_GRAD_Z[1]
    L.new(sep.outputs['Z'], gz.inputs['Value'])
    chin = tuple(c * k for c, k in zip(FACE_MID, FACE_CHIN_MUL))
    brow = tuple(c * k for c, k in zip(FACE_MID, FACE_BROW_MUL))
    fmix = n.new('ShaderNodeMix')
    fmix.data_type = 'RGBA'
    fmix.blend_type = 'MIX'
    fmix.inputs[6].default_value = (*chin, 1.0)
    fmix.inputs[7].default_value = (*brow, 1.0)
    L.new(gz.outputs['Result'], fmix.inputs[0])
    # sparse gold flecks (r4): large cells, tiny dots, low emission
    fv = n.new('ShaderNodeTexVoronoi')
    fv.voronoi_dimensions = '3D'
    fv.feature = 'F1'
    fv.inputs['Scale'].default_value = FLECK['cell_scale']
    fv.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], fv.inputs['Vector'])
    flt = n.new('ShaderNodeMath')
    flt.operation = 'LESS_THAN'
    flt.inputs[1].default_value = FLECK['dot_r']
    L.new(fv.outputs['Distance'], flt.inputs[0])
    fn = n.new('ShaderNodeTexNoise')
    fn.inputs['Scale'].default_value = FLECK['noise_scale']
    fn.inputs['Detail'].default_value = 1.0
    L.new(tc.outputs['Object'], fn.inputs['Vector'])
    fgt = n.new('ShaderNodeMath')
    fgt.operation = 'GREATER_THAN'
    fgt.inputs[1].default_value = FLECK['noise_gt']
    L.new(fn.outputs['Fac'], fgt.inputs[0])
    fzg = n.new('ShaderNodeMapRange')
    fzg.interpolation_type = 'SMOOTHSTEP'
    fzg.inputs['From Min'].default_value = FLECK['z0']
    fzg.inputs['From Max'].default_value = FLECK['z1']
    L.new(sep.outputs['Z'], fzg.inputs['Value'])
    f1 = n.new('ShaderNodeMath')
    f1.operation = 'MULTIPLY'
    L.new(flt.outputs[0], f1.inputs[0])
    L.new(fgt.outputs[0], f1.inputs[1])
    fl = n.new('ShaderNodeMath')
    fl.operation = 'MULTIPLY'
    L.new(f1.outputs[0], fl.inputs[0])
    L.new(fzg.outputs['Result'], fl.inputs[1])
    gmix = n.new('ShaderNodeMix')
    gmix.data_type = 'RGBA'
    gmix.blend_type = 'MIX'
    L.new(fmix.outputs[2], gmix.inputs[6])
    gmix.inputs[7].default_value = (*FLECK['rgb'], 1.0)
    L.new(fl.outputs[0], gmix.inputs[0])
    L.new(gmix.outputs[2], b.inputs['Base Color'])
    b.inputs['Emission Color'].default_value = (*FLECK['rgb'], 1.0)
    fem = n.new('ShaderNodeMath')
    fem.operation = 'MULTIPLY'
    fem.inputs[1].default_value = FLECK['emit']
    L.new(fl.outputs[0], fem.inputs[0])
    L.new(fem.outputs[0], b.inputs['Emission Strength'])
    # R6SKIN pebbling: one rounded dome per Voronoi cell on a smooth plate
    vb = n.new('ShaderNodeTexVoronoi')
    vb.voronoi_dimensions = '3D'
    vb.feature = 'F1'
    vb.inputs['Scale'].default_value = PEBBLE['scale']
    vb.inputs['Randomness'].default_value = PEBBLE['rand']
    L.new(tc.outputs['Object'], vb.inputs['Vector'])
    dome = n.new('ShaderNodeMapRange')
    dome.interpolation_type = 'SMOOTHSTEP'
    dome.inputs['From Min'].default_value = PEBBLE['dot_r']
    dome.inputs['From Max'].default_value = PEBBLE['edge']
    dome.inputs['To Min'].default_value = 0.0
    dome.inputs['To Max'].default_value = 1.0
    L.new(vb.outputs['Distance'], dome.inputs['Value'])
    bump = n.new('ShaderNodeBump')
    bump.invert = False
    bump.inputs['Strength'].default_value = PEBBLE['strength']
    bump.inputs['Distance'].default_value = PEBBLE['dist']
    L.new(dome.outputs['Result'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    # R5SKIN sparkle: sub-mm glossy specks (verbatim)
    sv = n.new('ShaderNodeTexVoronoi')
    sv.voronoi_dimensions = '3D'
    sv.feature = 'F1'
    sv.inputs['Scale'].default_value = SPARK['scale']
    sv.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], sv.inputs['Vector'])
    slt = n.new('ShaderNodeMath')
    slt.operation = 'LESS_THAN'
    slt.inputs[1].default_value = SPARK['dot_r']
    L.new(sv.outputs['Distance'], slt.inputs[0])
    sn = n.new('ShaderNodeTexNoise')
    sn.inputs['Scale'].default_value = SPARK['noise_scale']
    sn.inputs['Detail'].default_value = 1.0
    L.new(tc.outputs['Object'], sn.inputs['Vector'])
    sgt = n.new('ShaderNodeMath')
    sgt.operation = 'GREATER_THAN'
    sgt.inputs[1].default_value = SPARK['noise_gt']
    L.new(sn.outputs['Fac'], sgt.inputs[0])
    sp = n.new('ShaderNodeMath')
    sp.operation = 'MULTIPLY'
    L.new(slt.outputs[0], sp.inputs[0])
    L.new(sgt.outputs[0], sp.inputs[1])
    rmix = n.new('ShaderNodeMix')
    rmix.data_type = 'FLOAT'
    rmix.inputs[2].default_value = FACE_ROUGH
    rmix.inputs[3].default_value = SPARK['rough']
    L.new(sp.outputs[0], rmix.inputs[0])
    L.new(rmix.outputs[0], b.inputs['Roughness'])
    smix = n.new('ShaderNodeMix')
    smix.data_type = 'FLOAT'
    smix.inputs[2].default_value = FACE_SPEC
    smix.inputs[3].default_value = SPARK['spec']
    L.new(sp.outputs[0], smix.inputs[0])
    L.new(smix.outputs[0], b.inputs['Specular IOR Level'])
    print(
        'R6SKIN face albedo mid=%s brow=%s chin=%s rough %.2f spec %.2f sss %.2f domes %.0f/mm %.2f x %.2f mm r%.2f sparkle %.0f'
        % (
            FACE_MID,
            tuple(round(v, 3) for v in brow),
            tuple(round(v, 3) for v in chin),
            FACE_ROUGH,
            FACE_SPEC,
            FACE_SSS,
            PEBBLE['scale'],
            1000.0 / PEBBLE['scale'],
            PEBBLE['dist'] * 1000 * PEBBLE['strength'],
            PEBBLE['dot_r'],
            SPARK['scale'],
        )
    )
    return m


print('R6SKIN run5: domes %s' % (PEBBLE,))


# ── run6: domes TOUCHING (cobblestone), softer shoulder ─────────────────────────────────────
# run5 (r 0.38 of a 3.4 mm cell, hard shoulder 0.06): discrete 2.6 mm beads on a smooth plate —
# a dewy / goosebump look, closer to r4's "pimples" than to cell_11, whose pebbles are dense and
# touch each other (rounded cobbles with narrow valleys, each with a small highlight). r 0.55
# (domes reach the cell boundary, F1 distance there ~0.5), shoulder 0.06 -> 0.10, strength
# 0.70 -> 0.60 so the valleys shade softly; pitch unchanged (290 = 3.4 mm, ~3 per cm).
PEBBLE.update({'dot_r': 0.55, 'edge': 0.10, 'strength': 0.60})
print('R6SKIN run6: domes %s' % (PEBBLE,))


# ═════════════════════════════════════════════════════════════════════════════
# R6 LIGHT (lookdev2 / r2_light) — lights, backdrop, floor, lens. Critic (phase-2 round 2):
#   the coat is neutral white-to-cream everywhere: no top-to-bottom colour GRADE. Anchor
#   crown mint (221,248,237), mid-belly caramel (183,144,85), lower flank (249,227,150), side
#   low belly (103,83,46) in shadow; ours (235,242,236) / (206,205,182) / (245,243,229) /
#   (153,160,136). 19 % of crown px >= 235 vs 3.5 %.
# Zone probe (probe.py: body box from the largest inscribed circle, SAME patches on the
# anchor and the render, medians in sRGB / 8-bit Lab), base run vs anchor_full:
#   crown     (235,244,238) L243 a124   vs (218,245,225) L240 a116   45.9 % >= 235 vs 8.6 %
#   crownL    (233,244,239) L244        vs (138,204,201) L199 CYAN   <- the left is NOT a shadow side
#   crownR    (242,244,236)             vs (243,246,199) cream       <- the key's warmth is right/short
#   chest     (202,196,163) L202        vs (166,131,80)  L146 tan
#   midbelly  (233,222,183) L226        vs (111,83,43)   L 96 caramel   ~2.3 stops too bright
#   flankR    (238,228,185) L231        vs (201,127,59)  L152 orange
#   side rear (160,197,197) L197        vs (71,119,125)  L120 teal;  side lowbelly L153 vs L77
# So the anchor is keyed hard from the upper RIGHT (right flank + crown-right cream), its crown
# TOP is mint from a light above, its LEFT falls off into a dim cyan fill, and the whole lower
# body sits 1.5-2.5 stops down in a warm bounce. Ours has a 20 W mint disk (0.9 S, az -50 /
# el 55) flooding the entire front — every zone reads as one exposure. Under Filmic, adding
# the critic's warm fill on top of that flood would only push the belly whiter (R5 run5 did
# exactly that); the fix is to take the cool/neutral light OFF the lower body first.
# Everything below overrides the R5 LIGHT names above (LIGHTS is read at lighting() time).
# ═════════════════════════════════════════════════════════════════════════════
_L6 = {}


# ── run1: the cool fill becomes a TOP light ────────────────────────────────────────────
# az -50 / el 55 -> az -35 / el 75, same 1.5 S distance; disk 0.9 -> 0.6 S. The up-pointing
# crown tufts see it at 15 deg incidence instead of 35 (cos 0.97 vs 0.82), so 20 -> 17 W
# (fur) and 2.5 -> 2.1 W (general) keep the crown irradiance where it was; the belly, which
# faces forward-DOWN, drops out of it entirely and the crown-left gets only the falloff.
def _sph(az_deg, el_deg, dist=1.5):
    az, el = math.radians(az_deg), math.radians(el_deg)
    return (dist * math.cos(el) * math.sin(az), -dist * math.cos(el) * math.cos(az), dist * math.sin(el))


_TOP_POS = _sph(-35, 75)
LIGHTS['coolfill'].update(pos=_TOP_POS, W=2.1, size=0.60, aim='crown')
LIGHTS['coolfur'].update(pos=_TOP_POS, W=17.0, size=0.60, aim='crown')
print('R6LIGHT run1: cool light -> top %s' % (tuple(round(v, 3) for v in _TOP_POS),))


# ── run2: the WARM pair becomes a low SIDE light, half power ───────────────────────────
# run1 (top light) left the belly at L225: the belly's light is the amber pair itself —
# 7 + 13 W at ~0.9 S, front-right (az 47 / el -15), AIMED at the belly, i.e. a frontal
# belly flood that Filmic renders as cream. The anchor's lower body is lit from its RIGHT
# and low (flankR orange L152, bottom-right the brightest warm, front-centre caramel L96,
# left flank black): a side light the front-centre only grazes. az 75 / el -5 at 1.2 S,
# aimed 'low'; 7/13 -> 3.5/6.5 W (the belly is ~2.3 stops over; the side position buys
# ~1 stop on the front-centre, the power the rest). Colour stays WARM: linear WARM x fur
# root albedo = (0.70,0.38,0.10), R/G 1.84, R/B 6.7 — the anchor mid-belly (111,83,43)
# linearised is (0.159,0.087,0.024): R/G 1.83, R/B 6.6. Same hue; it was only too bright.
_WARM_POS = _sph(75, -5, 1.2)
LIGHTS['warm'].update(pos=_WARM_POS, W=3.5, aim='low')
LIGHTS['warmfur'].update(pos=_WARM_POS, W=6.5, aim='low')
print('R6LIGHT run2: warm pair -> side %s, 3.5 + 6.5 W' % (tuple(round(v, 3) for v in _WARM_POS),))


# ── run3: the KEY pair moves to az 60 / el 32 ───────────────────────────────────────────
# run2 took the belly from L226 to L182 but it is grey-cream (183,175,141): what is left
# on the front-centre is the NEUTRAL light — furkey (3800 K on mint fur = cream) + key at
# az 40 / el 35 hit the camera-facing belly at cos ~0.7. Anchor: crown-right and the right
# flank cream, front-centre caramel, left flank black — a key well to camera-right whose
# light only grazes the front. Same 1.5 S distance, az 40 -> 60, el 35 -> 32 (cos on a
# camera-facing surface 0.77 -> 0.50, on the right flank up). Power unchanged.
_KEY_POS6 = _sph(60, 32)
LIGHTS['key'].update(pos=_KEY_POS6)
LIGHTS['furkey'].update(pos=_KEY_POS6)
print('R6LIGHT run3: key pair -> %s' % (tuple(round(v, 3) for v in _KEY_POS6),))


# ── run4: KEY elevation 32 -> 48 deg ────────────────────────────────────────────────────
# run3 (key az 60): belly L147, but flankR (216,208,166) is still cream where the anchor's
# lower-right flank is ORANGE (201,127,59) L152 — the key at el 32 still lights the lower
# quarter of the ball; in the anchor the cream stops at eye level and the lower flank is
# warm-light only. Same az 60 / 1.5 S, el 48: the ball's own curvature takes the key off
# the lower flank and off the front-centre belly. Power unchanged.
_KEY_POS6 = _sph(60, 48)
LIGHTS['key'].update(pos=_KEY_POS6)
LIGHTS['furkey'].update(pos=_KEY_POS6)
print('R6LIGHT run4: key pair -> %s' % (tuple(round(v, 3) for v in _KEY_POS6),))


# ── run5: FILL LEVELS — cyan left fill up, warm side pair halved ────────────────────────
# run4 (key el 48): belly (126,109,68) L120 vs anchor (111,83,43) L96 — the grade is there.
# But (1) flankR (209,195,138) is still CREAM: it is now warm-light only (key cos 0.18 at
# el 48) and at 10 W the amber pair over-exposes it and Filmic desaturates; the anchor's
# (201,127,59) is that amber ~1 stop lower. (2) The whole lower-LEFT body is black (V<70,
# eye-gate mask), where the anchor's left is a CYAN shadow (crown-left (138,204,201) L199,
# only the very bottom (50,47,30)). That black also touches the amber belly and gives the
# harness's belly blob its 20 % dark pixels (anchor 2.4 %), which is why the eye finder
# ranks the belly above the eyes. So: fillL (cyan (0.40,0.85,1.0), upper-left-front)
# 0.3 -> 3.0 W, a little higher; warm/warmfur 3.5/6.5 -> 1.75/3.25 W (also -1 stop on the
# side view's rear-low belly, L175 vs anchor L77).
LIGHTS['fillL'].update(pos=(-1.15, -0.50, 0.60), W=3.0, size=0.70)
LIGHTS['warm'].update(W=1.75)
LIGHTS['warmfur'].update(W=3.25)
print('R6LIGHT run5: fillL 3.0 W, warm pair 1.75 + 3.25 W')


# ── run6 (final candidate): warm BOUNCE, crown light harder + more mint, rimR, fillL up ───
# run5: front mid-belly (108,103,71) L111 vs anchor (111,83,43) L96 — the grade is in; the
# left is the anchor's cyan shadow; flankR (189,175,121) matches the critic's lower-flank
# hue (249,227,150). Left over, each with its own lever:
#  * chest grey-green (106,135,121) vs the anchor's tan (166,131,80): under the chin only
#    the fur's mint root colour shows. The eye-gate mask shows the same zone's lock valleys
#    are the V<70 pixels that make the harness's amber belly blob 20 % dark (anchor 2.4 %)
#    and outrank the eyes. One light fixes both: the critic's floor bounce — a 1.0 S soft
#    warm disk low in front (el ~-25), aimed at the chest, dim (0.8 W general on the
#    creature, 2.0 W fur-only), colour (1.0,0.55,0.25): paler than WARM so the valleys lift
#    tan, not orange. Linked to the creature, never the floor.
#  * crown: median L243 vs anchor L240 — the LEVEL is right, the DISTRIBUTION is not: 47 %
#    of px >= 235 vs 8.6 % because ours has no valleys between locks. Harder light: top
#    disk 0.60 -> 0.35 S, key disk 0.40 -> 0.30 S; top light 17/2.1 -> 12/1.5 W (the key
#    at el 48 now reaches the crown-right, so the top carries less) and a more saturated
#    mint (0.50,1.00,0.84) so the tint survives Filmic's shoulder (a 124 vs anchor 116).
#  * side view rear (172,201,199) L202 vs anchor (71,119,125) L120: that is rimR (cyan,
#    behind-right, 4 W) on the +x flank the side camera faces. 4 -> 1.5 W.
#  * fillL a little higher (el ~40) so the cyan lands on the crown-left / mid-left (anchor
#    (138,204,201)) and less on the very bottom (anchor black there).
LIGHTS['bounce'] = dict(pos=(0.10, -0.85, -0.40), W=0.8, size=1.00, rgb=(1.00, 0.55, 0.25), aim='chest')
LIGHTS['bouncefur'] = dict(pos=(0.10, -0.85, -0.40), W=2.0, size=1.00, rgb=(1.00, 0.55, 0.25), aim='chest')
LINKED = LINKED + ('bounce',)
FUR_ONLY = FUR_ONLY + ('bouncefur',)
MINT6 = (0.50, 1.00, 0.84)
LIGHTS['coolfill'].update(W=1.5, size=0.35, rgb=MINT6)
LIGHTS['coolfur'].update(W=12.0, size=0.35, rgb=MINT6)
LIGHTS['key'].update(size=0.30)
LIGHTS['furkey'].update(size=0.30)
LIGHTS['rimR'].update(W=1.5)
LIGHTS['fillL'].update(pos=(-1.05, -0.45, 0.85))
print('R6LIGHT run6: bounce 0.8 + 2.0 W; top 1.5 + 12 W %s size 0.35; key size 0.30; rimR 1.5; fillL up' % (MINT6,))


# ── run7 (FINAL): bounce fur-only and dimmer; a face-only light for the profile cheek ────
# run6 passed every gate (eye_frac +0.6 % with both eyes found; DINO front 0.805, side
# 0.756, level with base) but two numbers overshot:
#  * mid-belly (153,140,97) L149 vs anchor L96 — the bounce at 0.8 + 2.0 W lifted the belly
#    38 L from run5's L111. The general 'bounce' also warmed the face from below. It goes
#    fur-only at 1.2 W: enough to keep the chest tan and the lock valleys above the eye
#    gate's V<70, not enough to flatten the belly again.
#  * side lab_face 20.6 (base 18.1 at the same sample count): the profile face is DARK and
#    yellow (L144 b132 vs anchor L163 b125). The one face-only light sits front-LEFT and
#    never reaches the right cheek the side camera (+x) faces; that cheek has been living
#    on the warm side pair, which run5 halved. 'faceR': KEYC (mint-white) 3 W face-only from
#    the upper right (0.85,-0.65,0.65) S — no fur receivers, so the coat is untouched.
LIGHTS.pop('bounce', None)
LINKED = tuple(n for n in LINKED if n != 'bounce')
LIGHTS['bouncefur'].update(W=1.2)
LIGHTS['faceR'] = dict(pos=(0.85, -0.65, 0.65), W=3.0, size=0.35, rgb=KEYC, aim='c')
FACE_ONLY = FACE_ONLY + ('faceR',)
print('R6LIGHT run7: bounce fur-only 1.2 W; faceR 3 W face-only')


# ═════════════════════════════════════════════════════════════════════════════
# R6MERGE — lookdev2 round-2 merge on r1_merge/merge.py (R5MERGE run4).
# Sections above, appended VERBATIM in this order on top of the r1_merge base:
#   R6 FUR-HAIR  (r2_fur_hair/overlay.py lines 4731-4997): the profile cheek cut-out — plate/body/collar
#                fur density zeroed in a y-slab wedge behind the eye, temple cap tufts shorter + swept back,
#                brow-arc collar tufts kept. Wraps post_build (its _post_build_r5merge captured the base chain).
#   R6SKIN       (r2_skin/skin.py 4731-4969): plate tone (FACE_MID as the brow value, chin x3.1 inverted
#                gradient), collar material re-based into collar coords, lips/cavity lifted, cobble domes.
#                Pure name shadowing (face_material / _orbit_material / FACE_* / BEAK_* / PEBBLE).
#   R6 LIGHT     (r2_light/light.py 4731-4882): top light, low warm side pair, key az 60 / el 48, cyan fillL,
#                fur-only warm bounce, faceR face-only light. Pure LIGHTS/LINKED/FUR_ONLY/FACE_ONLY updates,
#                read by lighting() at call time.
# The fourth round (r2_fur_tuft: geometry lock coat) is NOT in this file — see the report ('fur_winner').
# The three sections define disjoint top-level names (checked by AST below at merge time), so the order is
# only the conceptual one: fur (density groups, particle settings) -> skin (materials) -> light (rig).
# Composition order at run time is unchanged from R5MERGE: PARAMS -> pre_build (form builders, fur
# dispatcher) -> post_build chain (fur mat -> eyes -> skin_post/face_material -> seat_eyes/_collar ->
# tail -> length maps -> light_post floor/bokeh -> R4/R5 fur passes -> R6 cheek cut) -> lighting/world/
# camera from the light section.
# Conflict watch-list for the runs (each has its own knob if it shows):
#   * skin's inverted plate gradient (FACE_CHIN_MUL 3.0-3.2) was painted against the base key (az 40 /
#     el 35); light moved the key to az 60 / el 48 and added faceR (3 W face-only, upper right). If the
#     lower plate reads paler than the bridge: drop faceR first, then lower FACE_CHIN_MUL.
#   * light's eye finder margin: any darkening of the amber belly blob trips front eye_frac. fur_hair and
#     skin do not touch the belly.
#   * fur_hair's side tail_above knife edge (brow-arc collar tufts carry the crown-front edge at row 344).
# ═════════════════════════════════════════════════════════════════════════════
print('R6MERGE: fur_hair (cheek cut) + skin (plate tone, lips, cobbles) + light (graded rig) on r1_merge')


# ── R6MERGE run2 — the plate's vertical gradient under light's key ──────────────────────────
# run1 (all three sections verbatim) passed every gate; DINO side 0.785 (base 0.760), front 0.798
# (0.800). Its one composition defect is measured, not guessed (profile.py: plate = face-ID & teal
# gate, bands relative to the eye box, 8-bit Lab L medians, close_front):
#                 brow  bridge  under-eye  lower(beside the lip)
#   anchor_full   190    184      160        137      (chin 121)   <- both references DARKEN downward
#   cell_11       149    169      140        113      (chin  96)
#   base          177    168      148        189
#   light alone   182    156      175        181      <- under light's key the natural fall-off is mild
#   skin alone    184    180      181        189
#   run1          189    170      176        193      <- INVERTED: the lower plate is the palest band
# skin's FACE_CHIN_MUL (3.0,3.1,3.2) was painted to cancel the base key's ~40 L fall-off (az 40 /
# el 35, grazing the forward-down lower plate). light moved the key to az 60 / el 48 and added the
# cyan fillL + faceR, so that fall-off is gone and the x3 chin now stands proud. The brow/bridge
# already sit on the anchor (187/171 vs 190/184); only the lower half is ~55 L too pale. Chin
# multiplier x3.1 -> x1.45 (B a step higher, the anchor's chin is bluer: b -7..-9 vs ours +2):
# under-eye (t 0.42 on the smoothstep) goes from x2.2 to x1.26 albedo, the lower band from x2.9
# to x1.4 — expected under-eye ~L160, lower ~L155, i.e. the anchor's downward grade without
# re-creating the base's L117 shadow pits (skin's collar re-basing and the lifted FACE_MID stay).
FACE_CHIN_MUL = (1.40, 1.45, 1.55)
print('R6MERGE run2: FACE_CHIN_MUL %s (skin had (3.0,3.1,3.2) against the old key)' % (FACE_CHIN_MUL,))


# ── R6MERGE run3 — split the two face references ────────────────────────────────────────────
# run2 (chin x1.45) took front lab_face 18 -> 9 and close 28 -> 17, but the per-row plate profile
# (rows in eye-diameters below the eye bottom, plate = face-ID & teal gate, close_front) shows it
# over-shot against anchor_full: rows 0..+0.2 anchor_full L170-190, run1 166-178, run2 141-153.
# The run2 comment's 'lower' band (+0.45..+0.85) was mint FUR lying over the lower plate (L195-210
# in both runs, unchanged), not plate — the anchor's dark lower plate (L137 at +0.5) is a region
# our coat covers. cell_11 (the face reference) reads ~L140 in its under-eye band, anchor_full 160,
# anchor_side's gated face median is 163: the references disagree by ~20 L at the under-eye. Split
# them: chin x2.2 (under-eye albedo x1.7, between run1's x2.2 and run2's x1.26) -> expected
# under-eye rows ~L158-162, front lab_face ~12, side back toward run1's 150 (anchor 163).
FACE_CHIN_MUL = (2.10, 2.20, 2.35)
print('R6MERGE run3: FACE_CHIN_MUL %s (split anchor_full / cell_11 at the under-eye)' % (FACE_CHIN_MUL,))
# run3 = FINAL (render: lookdev2/r2_merge/run3, 48 spp, DINO). Per-row plate L (close_front, rows 0..+0.2
# eye-d below the eye bottom): run3 154-162 vs cell_11 ~150 / anchor_side ~158 / anchor_full ~180.
# front lab_face 18 -> 12, side 15.6 (base 16.3), close 22 (base 21.9); DINO front 0.797 / side 0.785 (base 0.800 / 0.760).


# ═════════════════════════════════════════════════════════════════════════════
# R7 MERGE (lookdev2 round 3 / r3_merge) — base = r2_merge/merge.py (everything above this line
# is that file verbatim). Appended below, in this order:
#   1. R7 FUR-TUFT  (r3_fur_tuft/tuft_run5.py, its run1..run5 sections)   — the coat as geometry
#   2. R7EYES       (r3_eyes/eyes.py, run1..run5 sections)                 — bone socket ring + iris
#
# FUR JUDGE — TUFT over HAIR. Both final renders were put next to anchor_full / anchor_side and the
# base (cmp_*.png, crop_*.png in this directory):
#   * front: the tuft coat is separate tapered feather-locks with a clean edge and a point, the
#     chest hangs as overlapping locks, the crown is spikes of unequal height — the anchor's
#     construction. The hair coat is bundles of parallel strands (striated, 'wet'), its crown a
#     radial brush.
#   * q45: the tuft ball is plush with the flank lying back in one direction; the hair coat at 45
#     is a bottle-brush mane of long striated spikes (the view where phase-1 changes broke).
#   * tail: the tuft round keeps the base's plush hair tail; the hair round re-structured the tail
#     to 1400 x 32 locks and it reads striated (crop_crownside.png).
#   * side: neither is the anchor's smooth shingled plush; the tuft profile is too WHITE (near-white
#     43 % of fur px vs anchor 17 %; side lab_fur 15.0 on the gate) with a spiky crown halo; the
#     hair profile is a swirl of wet striated petals. Tuft is the lesser departure.
#   * DINO agrees on every view: tuft 0.832 / 0.734 / 0.775 vs hair 0.803 / 0.704 / 0.690
#     (front / side / close), base 0.797 / 0.785 / 0.684.
#   The hair round's changes (LOCK / R5_HAIR / FUR_COL / WIND / _comb_guides) are DROPPED whole:
#   the tuft coat removes pb_tufts and pb_cap_tufts, so the comb has nothing to act on, and the
#   only thing the hair round would still change is the tail's lock structure, which looked worse.
#   tuft.py's runs 6-8 (darker tones / hem skirt) are NOT taken: every one re-tripped the eye finder
#   on the shadowed legs (that agent's own caveat); run5 is the last state that passes.
#
# ORDER / CONTRACT: the tuft section re-binds post_build (base -> + drop hair + build locks) and
# _fit_camera (skips the 'pb_body_locks' carrier; the base's camera() finds it by global name);
# the eyes section then re-binds post_build again (-> + pb_rim_l/r) and extends FACE_PARTS with
# 'pb_rim' (the lighting reads FACE_PARTS by global name at call time). The socket rings are built
# AFTER the locks: the lock eye-cull is on the eyeball (1.10 x eye_r), independent of the ring, and
# the plate's cap_density is already bald round the eyes, so no lock is placed under the ring.
#
# CONFLICTS: none on the same object/param. Shared surfaces, decided:
#   * lighting receivers — the ring takes the face-only light (FACE_PARTS) and the key/creature
#     receivers by its 'pb_' prefix; the lock carrier takes the fur-only lights by 'pb_body'. Kept both.
#   * COLLAR lip -0.02 (eyes) sinks the skin collar's lip under the lens; nothing in tuft touches
#     the collar. Kept.
#   * side aspect: the eyes run read -5.11 % (gate 5.0) on ONE tail-strand pixel column; the tuft
#     run read the base's -4.97 %. It is sampling noise on a gate the base already sits on.
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# R7 FUR-TUFT (lookdev2 round 3 / r3_fur_tuft) — the coat as GEOMETRY: soft feather locks
#
# Critic (round 2, [major]): the coat is fine cotton fluff; the anchor's locks are thick tapered
# feather-locks ~3-5 % of the body radius wide, tapering to a point, separating cleanly with
# mint-shadowed roots, spiking outward on the crown and combed back-and-down in ONE direction
# on the flank (ours has a radial whorl there). Root (185,235,215), tip (245,252,245).
#
# Two geometry coats were tried before (r1_fur_tuft: needles -> hedgehog -> durian; r2_fur_tuft:
# hard opaque blades, a sea urchin, DINO side 0.657) and both failed the same way: an opaque
# Principled shell with a hard outline reads as PLASTIC SPIKES whatever the lock's shape. What the
# anchor's locks have that a shell has not: soft translucent edges, a fibrous grain, a rounded base,
# and they LIE ALONG the coat as shingles with a valley of mint shadow between neighbours. So:
#  * LOCK MESH: a flat feather (half-width 0.06-0.13 L, thin axis 0.38 of the wide one, rounder
#    at the base), fullest at 0.3 L, convex taper to a point, an outward curl (0.15-0.35 L) plus a
#    ~1-cycle S-wave in the wide plane and a slight twist. 8 variants spanning the width/length
#    ratios; UNIFORM per-instance scale (r2's anisotropic scale squashed the curl).
#  * MATERIAL: Principled, root->tip gradient on the baked lock_u, roughness 0.85 / specular 0.15
#    (no glints), random-walk subsurface 0.6 at 8 mm (thin locks glow at the rim light), sheen
#    0.5; a fibre-streak noise in LOCK coordinates (fast across, slow along, offset per lock) as a
#    bump + faint albedo variation; SOFT EDGES: facing-angle transparency (Layer Weight^3 ->
#    Transparent) and a fading tip (lock_u > 0.85), so the outline is fuzzy at 1024 px and the
#    neighbour shows through the very edge. transparent_max_bounces 32 for the stack-up.
#  * ROOTS: Poisson-disk on pb_body (fur_density = every base cut: bald triangle, brow band, 3D eye
#    exclusion, R6 cheek wedge) and on pb_face (cap_density: temple + V-edge), sunk 3 mm; 9 mm
#    spacing (8 crown, 10 belly) -> ~3000 locks, ~5x shingle overlap. A lock whose centreline
#    passes within 1.10 eye radii of an eyeball is shortened to 0.6, then dropped.
#  * DIRECTION (the critic's comb): d = n + lambda * t, t = tangent part of a FLOW field. Crown:
#    near-radial (lambda 0.25) + a forward crest; flank: (0, 0.87, -0.5) = back and 30 deg down at
#    lambda 1.2 — one direction, no whorl (the face-repel fades out on the flank); back lies
#    down-back; belly hangs; beard hangs forward-down; the plate-rim band lies BACK (lambda 2,
#    never forward over the plate: the R6 profile cheek). Side wisps at eye level: lateral AND
#    back (lambda 0.7) so the front keeps its width while the profile still sees a combed flank.
#  * LENGTH — MEASURED on the base (alpha vs ID silhouettes, 1.19 px/mm): crown pad 98 mm, lateral
#    pad at the equator 79 mm. The gated aspect (front -4.1 % of a 5 % gate) and side tail_above
#    (+0.9 %) are set by those pads: the lateral reach must be kept, the crown may shrink a little.
#    crown L 100 mm (reach ~95), wisps 95 mm (lateral reach ~78), flank 60, back 55, belly 55,
#    beard 65, rim band 40, cap 45; +-20 % random; arm zone x0.6.
#  * The hair systems pb_tufts (body) and pb_cap_tufts (plate) are REMOVED. The undercoats (30 mm
#    body / 35 mm plate), the cheek fringe, the collar brow tufts and the whole hair TAIL stay: the
#    anchor's tail is a finer plush than the body's feather-locks, so the hair tail is the right
#    material for it and the R5/R6 tail geometry + colour are untouched.
#  * A Geometry Nodes modifier NAMED 'fur' instances the locks (Mesh to Points -> Instance on
#    Points -> Realize): the harness's ID pass (every 'fur' modifier off) stays hair-free; the
#    carrier 'pb_body_locks' takes the fur-only lights by the 'pb_body' prefix, pass_index body.
#    _fit_camera skips the lock carrier (the harness frames on hair-free bounds + its 0.07 m pad).
# ═════════════════════════════════════════════════════════════════════════════

TUFT7 = {
    'len': {
        'crown': 0.100,
        'wisp': 0.095,
        'flank': 0.060,
        'back': 0.055,
        'belly': 0.055,
        'beard': 0.065,
        'rim': 0.040,
        'cap': 0.045,
    },
    'len_rand': 0.20,
    'arm_len': 0.60,
    'w_per_L': 0.09,
    'w_min': 0.0045,
    'w_max': 0.0070,
    'w_rand': 0.20,  # half-width at the widest point (m)
    'ratio': (0.06, 0.13),  # half-width / length spanned by the variants
    'thick': 0.38,  # thin axis / wide axis
    'spacing': 0.0090,
    'spacing_crown': 0.0080,
    'spacing_belly': 0.0100,
    'spacing_cap': 0.0080,
    'oversample': 3.0,
    'sink': 0.003,
    'tilt_jitter': 10.0,
    'roll_jitter': 25.0,
    'lean': {'crown': 0.25, 'wisp': 0.70, 'flank': 1.20, 'back': 1.00, 'belly': 1.30, 'beard': 1.00, 'rim': 2.00},
    'rep_c': (0.0, -0.150, 0.040),  # body-local face centre the front-hemisphere locks radiate from
    'eye_clear': 1.10,  # x eye_r: the lock centreline stays outside this
    'variants': 8,
    'seed': 7,
    'rings': 12,
    'sides': 8,
    'curl_amt': (0.15, 0.35),
    'wave': (0.02, 0.06),
    'wave_freq': (0.8, 1.3),
    'twist': 35.0,
}
LOCK7_COL = {
    'root': (0.487, 0.822, 0.672),
    'tip': (0.913, 0.973, 0.913),  # critic: (185,235,215) -> (245,252,245) sRGB
    'tip_at': 0.75,
    'rough': 0.85,
    'spec': 0.15,
    'sheen': 0.5,
    'sheen_rough': 0.6,
    'sss': 0.6,
    'sss_radius': (1.0, 0.9, 0.8),
    'sss_scale': 0.008,
    'grain_across': 10.0,
    'grain_along': 1.5,
    'grain_bump': 0.35,
    'grain_dist': 0.0004,
    'grain_col': 0.10,
    'edge_pow': 3.0,
    'edge_max': 0.9,
    'tip_u0': 0.85,
    'tip_max': 0.7,
}
_L7 = {}


def _sm7(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


# ── lock mesh + material ─────────────────────────────────────────────────────
def _lock7_mesh(name, ratio, curl, wave, freq, twist, rng):
    """Unit feather: length 1 along +Z, wide axis Y (half-width ratio x profile), thin axis X, curls toward +X."""
    T = TUFT7
    rings, sides = T['rings'], T['sides']
    verts, faces, us, cs = [], [], [], []

    def prof(s):
        a = 0.55 + 0.45 * _sm7(s / 0.30)
        b = (1.0 - s**1.3) ** 0.9
        return a * b / 0.885

    def cl(s):
        return Vector((curl * s * s, wave * math.sin(2.0 * math.pi * freq * s) * s, s))

    for i in range(rings):
        s = i / float(rings)
        c = cl(s)
        w = ratio * prof(s)
        t = w * T['thick'] * (1.0 + 0.4 * (1.0 - s))
        ph = math.radians(twist) * s
        for j in range(sides):
            th = 2.0 * math.pi * j / sides
            ex, ey = t * math.cos(th), w * math.sin(th)
            x = ex * math.cos(ph) - ey * math.sin(ph)
            y = ex * math.sin(ph) + ey * math.cos(ph)
            verts.append((c.x + x, c.y + y, c.z))
            us.append(s)
            cs.append((math.cos(th), math.sin(th), s))
    tip = cl(1.0)
    verts.append((tip.x, tip.y, tip.z))
    us.append(1.0)
    cs.append((0.0, 0.0, 1.0))
    ti = len(verts) - 1
    verts.append((0.0, 0.0, -0.01))
    us.append(0.0)
    cs.append((0.0, 0.0, 0.0))
    bi = len(verts) - 1
    for i in range(rings - 1):
        a = i * sides
        b = a + sides
        for j in range(sides):
            j2 = (j + 1) % sides
            faces.append((a + j, b + j, b + j2, a + j2))
    last = (rings - 1) * sides
    for j in range(sides):
        j2 = (j + 1) % sides
        faces.append((last + j, ti, last + j2))
        faces.append((bi, j2, j))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    bm = _bmesh7.new()
    bm.from_mesh(me)
    _bmesh7.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    au = me.attributes.new(name='lock_u', type='FLOAT', domain='POINT')
    for k, u in enumerate(us):
        au.data[k].value = u
    ac = me.attributes.new(name='lock_c', type='FLOAT_VECTOR', domain='POINT')
    for k, c in enumerate(cs):
        ac.data[k].vector = c
    return me


def _lock7_material(name):
    C = LOCK7_COL
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    n, L = nt.nodes, nt.links
    b = n['Principled BSDF']
    out = n['Material Output']
    b.inputs['Roughness'].default_value = C['rough']
    b.inputs['Specular IOR Level'].default_value = C['spec']
    b.inputs['Subsurface Weight'].default_value = C['sss']
    b.inputs['Subsurface Radius'].default_value = C['sss_radius']
    b.inputs['Subsurface Scale'].default_value = C['sss_scale']
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Sheen Weight'].default_value = C['sheen']
    b.inputs['Sheen Roughness'].default_value = C['sheen_rough']
    b.inputs['Coat Weight'].default_value = 0.0
    au = n.new('ShaderNodeAttribute')
    au.attribute_name = 'lock_u'
    ac = n.new('ShaderNodeAttribute')
    ac.attribute_name = 'lock_c'
    ar = n.new('ShaderNodeAttribute')
    ar.attribute_name = 'lk_rnd'
    ramp = n.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (*C['root'], 1.0)
    ramp.color_ramp.elements[1].position = C['tip_at']
    ramp.color_ramp.elements[1].color = (*C['tip'], 1.0)
    L.new(au.outputs['Fac'], ramp.inputs['Fac'])
    # fibre streaks in lock coordinates: (cos, sin) x across, u x along, offset per lock
    sep = n.new('ShaderNodeSeparateXYZ')
    L.new(ac.outputs['Vector'], sep.inputs['Vector'])
    mx = n.new('ShaderNodeMath')
    mx.operation = 'MULTIPLY'
    mx.inputs[1].default_value = C['grain_across']
    my = n.new('ShaderNodeMath')
    my.operation = 'MULTIPLY'
    my.inputs[1].default_value = C['grain_across']
    mz = n.new('ShaderNodeMath')
    mz.operation = 'MULTIPLY_ADD'
    mz.inputs[1].default_value = C['grain_along']
    mr = n.new('ShaderNodeMath')
    mr.operation = 'MULTIPLY'
    mr.inputs[1].default_value = 37.0
    L.new(sep.outputs['X'], mx.inputs[0])
    L.new(sep.outputs['Y'], my.inputs[0])
    L.new(sep.outputs['Z'], mz.inputs[0])
    L.new(ar.outputs['Fac'], mr.inputs[0])
    L.new(mr.outputs[0], mz.inputs[2])
    comb = n.new('ShaderNodeCombineXYZ')
    L.new(mx.outputs[0], comb.inputs['X'])
    L.new(my.outputs[0], comb.inputs['Y'])
    L.new(mz.outputs[0], comb.inputs['Z'])
    noi = n.new('ShaderNodeTexNoise')
    noi.inputs['Scale'].default_value = 1.0
    noi.inputs['Detail'].default_value = 2.0
    noi.inputs['Roughness'].default_value = 0.5
    L.new(comb.outputs['Vector'], noi.inputs['Vector'])
    bump = n.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = C['grain_bump']
    bump.inputs['Distance'].default_value = C['grain_dist']
    L.new(noi.outputs['Fac'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    gm = n.new('ShaderNodeMath')
    gm.operation = 'MULTIPLY_ADD'
    gm.inputs[1].default_value = C['grain_col']
    gm.inputs[2].default_value = 1.0 - C['grain_col'] * 0.5
    L.new(noi.outputs['Fac'], gm.inputs[0])
    vs = n.new('ShaderNodeVectorMath')
    vs.operation = 'SCALE'
    L.new(ramp.outputs['Color'], vs.inputs[0])
    L.new(gm.outputs[0], vs.inputs['Scale'])
    L.new(vs.outputs[0], b.inputs['Base Color'])
    # soft edges: facing-angle transparency + tip fade
    lw = n.new('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.5
    pw = n.new('ShaderNodeMath')
    pw.operation = 'POWER'
    pw.inputs[1].default_value = C['edge_pow']
    em = n.new('ShaderNodeMath')
    em.operation = 'MULTIPLY'
    em.inputs[1].default_value = C['edge_max']
    L.new(lw.outputs['Facing'], pw.inputs[0])
    L.new(pw.outputs[0], em.inputs[0])
    tm = n.new('ShaderNodeMapRange')
    tm.interpolation_type = 'SMOOTHSTEP'
    tm.inputs['From Min'].default_value = C['tip_u0']
    tm.inputs['From Max'].default_value = 1.0
    tm.inputs['To Min'].default_value = 0.0
    tm.inputs['To Max'].default_value = C['tip_max']
    L.new(au.outputs['Fac'], tm.inputs['Value'])
    mxm = n.new('ShaderNodeMath')
    mxm.operation = 'MAXIMUM'
    L.new(em.outputs[0], mxm.inputs[0])
    L.new(tm.outputs['Result'], mxm.inputs[1])
    tr = n.new('ShaderNodeBsdfTransparent')
    ms = n.new('ShaderNodeMixShader')
    L.new(mxm.outputs[0], ms.inputs['Fac'])
    L.new(b.outputs[0], ms.inputs[1])
    L.new(tr.outputs[0], ms.inputs[2])
    L.new(ms.outputs[0], out.inputs['Surface'])
    return m


def _lock7_collection(scene, mat):
    if 'coll' in _L7:
        return _L7['coll']
    T = TUFT7
    rng = _random7.Random(T['seed'] + 1000)
    coll = bpy.data.collections.new('lock7_src')
    scene.collection.children.link(coll)
    r0, r1 = T['ratio']
    nv = T['variants']
    for k in range(nv):
        ratio = r0 + (r1 - r0) * k / float(nv - 1)
        me = _lock7_mesh(
            'lock7_%d' % k,
            ratio,
            curl=rng.uniform(*T['curl_amt']),
            wave=rng.uniform(*T['wave']) * rng.choice((-1.0, 1.0)),
            freq=rng.uniform(*T['wave_freq']),
            twist=T['twist'] * rng.uniform(-1.0, 1.0),
            rng=rng,
        )
        me.materials.append(mat)
        ob = bpy.data.objects.new('lock7_%d' % k, me)
        coll.objects.link(ob)
    lc = bpy.context.view_layer.layer_collection.children.get(coll.name)
    if lc is not None:
        lc.exclude = True
    _L7['coll'] = coll
    return coll


def _lock7_nodetree(coll):
    nt = bpy.data.node_groups.new('pb_lock7_gn', 'GeometryNodeTree')
    nt.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    nt.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    gi = nt.nodes.new('NodeGroupInput')
    go = nt.nodes.new('NodeGroupOutput')
    m2p = nt.nodes.new('GeometryNodeMeshToPoints')
    m2p.mode = 'VERTICES'
    ci = nt.nodes.new('GeometryNodeCollectionInfo')
    ci.transform_space = 'ORIGINAL'
    ci.inputs['Collection'].default_value = coll
    ci.inputs['Separate Children'].default_value = True
    ci.inputs['Reset Children'].default_value = True

    def named(nm, dt):
        a = nt.nodes.new('GeometryNodeInputNamedAttribute')
        a.data_type = dt
        a.inputs['Name'].default_value = nm
        return a

    rot = named('lk_rot', 'QUATERNION')
    scl = named('lk_scl', 'FLOAT_VECTOR')
    var = named('lk_var', 'INT')
    iop = nt.nodes.new('GeometryNodeInstanceOnPoints')
    iop.inputs['Pick Instance'].default_value = True
    ri = nt.nodes.new('GeometryNodeRealizeInstances')
    L = nt.links.new
    L(gi.outputs['Geometry'], m2p.inputs['Mesh'])
    L(m2p.outputs['Points'], iop.inputs['Points'])
    L(ci.outputs['Instances'], iop.inputs['Instance'])
    L(var.outputs['Attribute'], iop.inputs['Instance Index'])
    L(rot.outputs['Attribute'], iop.inputs['Rotation'])
    L(scl.outputs['Attribute'], iop.inputs['Scale'])
    L(iop.outputs['Instances'], ri.inputs['Geometry'])
    L(ri.outputs['Geometry'], go.inputs['Geometry'])
    return nt


def _lock7_object(scene, name, roots, coll, pass_index, location):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(r[0]) for r in roots], [], [])
    me.validate()
    for nm, ty in (('lk_rot', 'QUATERNION'), ('lk_scl', 'FLOAT_VECTOR'), ('lk_var', 'INT'), ('lk_rnd', 'FLOAT')):
        me.attributes.new(name=nm, type=ty, domain='POINT')
    a_rot, a_scl, a_var, a_rnd = (me.attributes[nm] for nm in ('lk_rot', 'lk_scl', 'lk_var', 'lk_rnd'))
    for i, (_pos, q, sc, var, rnd) in enumerate(roots):
        a_rot.data[i].value = (q.w, q.x, q.y, q.z)
        a_scl.data[i].vector = sc
        a_var.data[i].value = var
        a_rnd.data[i].value = rnd
    ob = bpy.data.objects.new(name, me)
    ob.pass_index = pass_index
    ob.location = location
    scene.collection.objects.link(ob)
    md = ob.modifiers.new('fur', 'NODES')
    md.node_group = _lock7_nodetree(coll)
    return ob


# ── root frames ──────────────────────────────────────────────────────────────
def _frame_quat7(d, x_ref, rng, roll_jit):
    """Rotation with local Z = d and local X = x_ref projected (the curl direction), +- roll jitter."""
    d = d.normalized()
    x = x_ref - d * x_ref.dot(d)
    if x.length < 0.2:
        h = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        x = h - d * h.dot(d)
        if x.length < 1e-4:
            x = d.orthogonal()
    x.normalize()
    x = (_Quat7(d, math.radians(rng.uniform(-roll_jit, roll_jit))) @ x).normalized()
    y = d.cross(x).normalized()
    return _Mat7((x, y, d)).transposed().to_quaternion()


def _jitter7(d, rng, deg):
    ax = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
    ax = ax - d * ax.dot(d)
    if ax.length < 1e-4:
        return d
    return (_Quat7(ax.normalized(), math.radians(rng.uniform(0.0, deg))) @ d).normalized()


class _Poisson7:
    def __init__(self, cell):
        self.cell = cell
        self.g = {}

    def key(self, P):
        return (int(math.floor(P.x / self.cell)), int(math.floor(P.y / self.cell)), int(math.floor(P.z / self.cell)))

    def ok(self, P, r):
        kx, ky, kz = self.key(P)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for k in (-1, 0, 1):
                    for Q in self.g.get((kx + i, ky + j, kz + k), ()):
                        if (Q - P).length < r:
                            return False
        return True

    def add(self, P):
        self.g.setdefault(self.key(P), []).append(P)


def _face_point7(me, poly, rng):
    vs = [me.vertices[i].co for i in poly.vertices]
    if len(vs) == 4:
        u, v = rng.random(), rng.random()
        return (vs[0] * (1 - u) + vs[1] * u) * (1 - v) + (vs[3] * (1 - u) + vs[2] * u) * v
    a, b = rng.random(), rng.random()
    if a + b > 1.0:
        a, b = 1 - a, 1 - b
    return vs[0] + (vs[1] - vs[0]) * a + (vs[2] - vs[0]) * b


def _vg7(ob, name):
    n = len(ob.data.vertices)
    vg = ob.vertex_groups.get(name)
    if vg is None:
        return [1.0] * n
    gi = vg.index
    out = [0.0] * n
    for v in ob.data.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


# ── the comb: zones -> flow / lean / length ──────────────────────────────────
def _zones7(x, y, z):
    """(crown, belly, back, front, beard, wisp, rim) weights at a body-local point."""
    ax = abs(x)
    wc = _sm7((z - 0.06) / 0.05)
    wb = _sm7((-0.04 - z) / 0.05)
    wk = _sm7((y - 0.03) / 0.07)
    wf = _sm7((-0.02 - y) / 0.06)
    wbd = wf * _sm7((0.0 - z) / 0.04) * (1.0 - _sm7((ax - 0.08) / 0.03))
    ww = (
        _sm7((ax - 0.095) / 0.02)
        * (1.0 - _sm7((abs(z - 0.04) - 0.05) / 0.03))
        * (1.0 - _sm7((y - 0.03) / 0.04))
        * (1.0 - _sm7((-0.03 - y) / 0.03))
    )
    wr = 1.0 if (ax > 0.085 and -0.11 < y < -0.02 and -0.03 < z < 0.125) else 0.0
    return wc, wb, wk, wf, wbd, ww, wr


def _flow7(P, Z):
    T = TUFT7
    wc, wb, wk, wf, wbd, ww, wr = Z
    F = Vector((0.0, 0.0, 0.0))
    if wf > 0.0:
        r = P - Vector(T['rep_c'])
        if r.length > 1e-6:
            F += r.normalized() * (wf * (1.0 - 0.6 * wc) * (1.0 - 0.5 * ww))
    wfl = _sm7((abs(P.x) - 0.07) / 0.03) * (1.0 - wc) * (1.0 - wb) * (1.0 - 0.6 * wf)
    F += Vector((0.0, 0.87, -0.5)) * wfl  # flank: back and 30 deg down
    F += Vector((0.0, 0.6, -0.8)).normalized() * (0.9 * wk)  # back: lies down-back
    F += Vector((0.0, 0.0, -1.0)) * wb  # belly: hangs
    F += Vector((0.0, -0.35, -1.0)).normalized() * wbd  # beard: forward-down
    F += Vector((0.0, -0.5, 0.85)).normalized() * (0.5 * wc * (1.0 - wk))  # crown: forward crest
    if wr > 0.0:
        F = Vector((0.25 * (1.0 if P.x > 0 else -1.0), 1.0, 0.05)).normalized()  # plate rim: back along the head
    return F


def _lean7(Z):
    LN = TUFT7['lean']
    wc, wb, wk, wf, wbd, ww, wr = Z
    lam = LN['flank']
    lam += (LN['back'] - lam) * wk
    lam += (LN['belly'] - lam) * wb
    lam += (LN['beard'] - lam) * wbd
    lam += (LN['wisp'] - lam) * ww
    lam += (LN['crown'] - lam) * wc
    if wr > 0.0:
        lam = LN['rim']
    return lam


def _len7(P, Z):
    LE = TUFT7['len']
    wc, wb, wk, wf, wbd, ww, wr = Z
    L = LE['flank']
    L += (LE['back'] - L) * wk
    L += (LE['belly'] - L) * wb
    L += (LE['beard'] - L) * wbd
    L = max(L, L + (LE['wisp'] - L) * ww)
    L += (LE['crown'] - L) * wc
    if wr > 0.0:
        L = min(L, LE['rim'])
    A = ARM_ZONE
    x, y, z = P.x, P.y, P.z
    if y < A['y_max'] and A['z_lo'] < z < A['z_top'] and abs(x) > A['x0']:
        tx = min(1.0, (abs(x) - A['x0']) / (A['x1'] - A['x0']))
        tz = min(1.0, (A['z_top'] - z) / 0.03)
        ty = min(1.0, (A['y_max'] - y) / 0.03)
        L *= 1.0 - (1.0 - TUFT7['arm_len']) * tx * tz * ty
    return L


def _dir7(P, n, Z, rng):
    F = _flow7(P, Z)
    t = F - n * F.dot(n)
    lam = _lean7(Z)
    if t.length > 1e-4:
        d = (Vector(n) + t.normalized() * (lam * min(1.0, t.length / 0.3))).normalized()
    else:
        d = Vector(n)
    if Z[6] > 0.0 and P.y < -0.04 and d.y < 0.0:  # rim band: never forward over the plate
        d.y = 0.0
        d.normalize()
    return _jitter7(d, rng, TUFT7['tilt_jitter'])


def _roots7_on(ob, kind, wts, p, rng, grid, eyes_w, body_loc, roots, stats):
    T = TUFT7
    me = ob.data
    mw = ob.matrix_world
    r3 = mw.to_3x3()
    rx, ry, rz = p['body_rx'], p['body_ry'], p['body_rz']
    er = p['eye_r']
    order = list(range(len(me.polygons)))
    rng.shuffle(order)
    sp0 = T['spacing'] if kind == 'body' else T['spacing_cap']
    for fi in order:
        poly = me.polygons[fi]
        wd = sum(wts[i] for i in poly.vertices) / float(len(poly.vertices))
        if wd <= 0.01:
            continue
        k = max(1, int(math.ceil(T['oversample'] * poly.area / (sp0 * sp0))))
        for _ in range(k):
            stats['cand'] += 1
            Pl = _face_point7(me, poly, rng)
            if rng.random() >= wd:
                continue
            Pw = mw @ Pl
            P = Pw - body_loc
            sp = sp0
            if kind == 'body':
                if P.z > 0.06:
                    sp = T['spacing_crown'] + (sp0 - T['spacing_crown']) * (1.0 - _sm7((P.z - 0.06) / 0.05))
                elif P.z < -0.02:
                    sp = sp0 + (T['spacing_belly'] - sp0) * _sm7((-0.02 - P.z) / 0.06)
            if not grid.ok(P, sp):
                continue
            if kind == 'body':
                n = Vector((P.x / (rx * rx), P.y / (ry * ry), P.z / (rz * rz))).normalized()
            else:
                n = (r3 @ poly.normal).normalized()
            Z = _zones7(P.x, P.y, P.z)
            d = _dir7(P, n, Z, rng)
            jl = 1.0 - T['len_rand'] / 2.0 + T['len_rand'] * rng.random()
            L = _len7(P, Z) * jl
            if kind == 'cap':
                L = min(L, T['len']['cap'] * jl)
            if P.y < 0.0 and eyes_w:
                ok = False
                for trial in (1.0, 0.6):
                    Lt = L * trial
                    clear = True
                    for tt in (0.3, 0.6, 0.9):
                        q = Pw + d * (Lt * tt)
                        if min((q - e).length for e in eyes_w) < T['eye_clear'] * er:
                            clear = False
                            break
                    if clear:
                        L = Lt
                        ok = True
                        break
                if not ok:
                    stats['eye'] += 1
                    continue
            grid.add(P)
            w0 = min(T['w_max'], max(T['w_min'], T['w_per_L'] * L)) * (
                1.0 - T['w_rand'] / 2.0 + T['w_rand'] * rng.random()
            )
            r0, r1 = T['ratio']
            nv = T['variants']
            kv = int(round((w0 / L - r0) / (r1 - r0) * (nv - 1))) + rng.choice((-1, 0, 0, 1))
            kv = min(nv - 1, max(0, kv))
            Y = n.cross(d)
            x_ref = d.cross(Y) if Y.length > 0.05 else Vector((0.0, 0.0, 1.0))
            q = _frame_quat7(d, x_ref, rng, T['roll_jitter'])
            roots.append((P - n * T['sink'], q, (L, L, L), kv, rng.random()))
            stats[kind] = stats.get(kind, 0) + 1


def _drop_hair7():
    for oname, psname in (('pb_body', 'pb_tufts'), ('pb_face', 'pb_cap_tufts')):
        ob = _ob(oname)
        if ob is None:
            continue
        for md in [m for m in ob.modifiers if m.type == 'PARTICLE_SYSTEM' and m.particle_system.name == psname]:
            ob.modifiers.remove(md)
            print('R7 removed hair system %s on %s' % (psname, oname))


def _build7(scene, result, PB, p):
    body = _ob('pb_body')
    face = _ob('pb_face')
    if body is None:
        return
    T = TUFT7
    rng = _random7.Random(T['seed'])
    body_loc = Vector(body.location)
    eyes_w = [body_loc + Vector(c) for c in (_R4_EYES.get('c') or [])]
    mat = _lock7_material('pb_lock7')
    coll = _lock7_collection(scene, mat)
    grid = _Poisson7(T['spacing_belly'])
    roots = []
    stats = {'cand': 0, 'eye': 0}
    _roots7_on(body, 'body', _vg7(body, 'fur_density'), p, rng, grid, eyes_w, body_loc, roots, stats)
    if face is not None and face.vertex_groups.get('cap_density') is not None:
        _roots7_on(face, 'cap', _vg7(face, 'cap_density'), p, rng, grid, eyes_w, body_loc, roots, stats)
    _lock7_object(scene, 'pb_body_locks', roots, coll, PB.IDX['body'], body_loc)
    Ls = sorted(r[2][2] for r in roots)
    print(
        'R7 locks: %d placed (%s) from %d candidates, %d dropped at an eye; L %.0f..%.0f mm (median %.0f); eyes %s'
        % (
            len(roots),
            {k: v for k, v in stats.items() if k in ('body', 'cap')},
            stats['cand'],
            stats['eye'],
            1000 * Ls[0],
            1000 * Ls[-1],
            1000 * Ls[len(Ls) // 2],
            [tuple(round(v, 3) for v in e) for e in eyes_w],
        )
    )


_post_build_r6merge_fur = post_build


def post_build(scene, result, PB):
    _post_build_r6merge_fur(scene, result, PB)
    p = dict(_P)
    _drop_hair7()
    _build7(scene, result, PB, p)
    scene.cycles.transparent_max_bounces = max(scene.cycles.transparent_max_bounces, 32)
    bpy.context.view_layer.update()


def _fit_camera(cam, cam_data, view_id):
    """R5CAM's fit, skipping the lock carrier (its realized bounds would double-count the fur pad)."""
    from bpy_extras.object_utils import world_to_camera_view as w2c

    scene = bpy.context.scene
    obs = [
        o
        for o in scene.collection.objects
        if o.type == 'MESH' and o.name.startswith('pb_') and o.name != 'pb_ground' and not o.name.endswith('_locks')
    ]
    corners = [o.matrix_world @ Vector(c) for o in obs for c in o.bound_box]
    R = cam.matrix_world.to_quaternion()
    right = R @ Vector((1, 0, 0))
    up = R @ Vector((0, 1, 0))
    fwd = R @ Vector((0, 0, -1))
    pad = CAM_FIT['pad']
    pts = [w + right * (sx * pad) + up * (sy * pad) for w in corners for sx in (-1, 1) for sy in (-1, 1)]
    fov = 2.0 * math.atan(0.5 * cam_data.sensor_width / cam_data.lens)
    avail = 1.0 - 2.0 * CAM_FIT['margin']
    d0 = None
    for _ in range(CAM_FIT['iters']):
        bpy.context.view_layer.update()
        ndc = [w2c(scene, cam, p) for p in pts]
        x0, x1 = min(n.x for n in ndc), max(n.x for n in ndc)
        y0, y1 = min(n.y for n in ndc), max(n.y for n in ndc)
        centre = sum(pts, Vector()) / len(pts)
        d = (centre - cam.location).dot(fwd)
        if d0 is None:
            d0 = d
        W = 2.0 * d * math.tan(fov / 2.0)
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        cam.location += right * ((cx - 0.5) * W) + up * ((cy - 0.5) * W)
        ext = max(x1 - x0, y1 - y0)
        if ext > avail:
            cam.location -= fwd * (d * (ext / avail - 1.0))
    bpy.context.view_layer.update()
    ndc = [w2c(scene, cam, p) for p in pts]
    print(
        'R7CAM %s (locks skipped): ndc x %.3f..%.3f y %.3f..%.3f, distance x%.3f'
        % (
            view_id,
            min(n.x for n in ndc),
            max(n.x for n in ndc),
            min(n.y for n in ndc),
            max(n.y for n in ndc),
            (centre - cam.location).dot(fwd) / d0,
        )
    )


# ── run2: LOCK DEFINITION — feathers, not needles ──────────────────────────────────────────
# run1 (1901 locks, half-width 0.06-0.13 L, 100 mm crown spikes, opaque shadows) read as a sea
# urchin from every view: at a half-width of 5-7 mm on 60-110 mm locks every lock is a NEEDLE,
# the Poisson at 9 mm left the 30 mm undercoat showing as cotton between them, and each lock
# cast a hard black shadow on its neighbour (the side eye finder took the warm-lit belly's black
# valleys for a pupil: box 163x156 px at x 329 / y 633, eye_frac +78 %). Measured on anchor_full:
# chest locks 25-35 px wide on 70-100 px of length (half-width 0.15-0.20 L), crown locks 15-20 px
# on 60-90 (0.10-0.12 L), and a lock's width tapers GRADUALLY from 0.3 L to the point.
#  * half-width 0.16 L, clamped 6..12 mm (crown 85 mm -> 12 mm = 0.14; flank 60 -> 9.6; rim 40 -> 6.4);
#    variants span 0.10..0.20; thin axis 0.30 (flatter); profile (1-s)^0.7 past the widest point
#    (run1's (1-s^1.3)^0.9 held the width to 0.7 L then snapped to a point = a thorn).
#  * spacing 9 -> 7.5 mm (crown 7, belly 8.5, plate 7): ~2800 locks, the shingle overlap that
#    hides the undercoat.
#  * SOFT SELF-SHADOW: hair lets light through; a shell does not. Shadow rays see the lock as 55 %
#    transparent (Light Path / Is Shadow Ray -> Transparent), so the valleys are mint half-shadow
#    like the anchor's, not black. Edge transparency to 1.0 at grazing (pow 2.5), tip fade from
#    0.75 L.
# Comb and crown length are unchanged here on purpose (run3) so the effect is attributable.
TUFT7.update(
    {
        'w_per_L': 0.16,
        'w_min': 0.0060,
        'w_max': 0.0120,
        'ratio': (0.10, 0.20),
        'thick': 0.30,
        'spacing': 0.0075,
        'spacing_crown': 0.0070,
        'spacing_belly': 0.0085,
        'spacing_cap': 0.0070,
        'curl_amt': (0.10, 0.30),
    }
)
LOCK7_COL.update({'edge_pow': 2.5, 'edge_max': 1.0, 'tip_u0': 0.75, 'shadow_tr': 0.55})


def _lock7_mesh(name, ratio, curl, wave, freq, twist, rng, _orig=_lock7_mesh):
    T = TUFT7
    rings, sides = T['rings'], T['sides']
    verts, faces, us, cs = [], [], [], []

    def prof(s):
        a = 0.55 + 0.45 * _sm7(s / 0.30)
        return a * ((1.0 - s) ** 0.7) / 0.78

    def cl(s):
        return Vector((curl * s * s, wave * math.sin(2.0 * math.pi * freq * s) * s, s))

    for i in range(rings):
        s = i / float(rings)
        c = cl(s)
        w = ratio * prof(s)
        t = w * T['thick'] * (1.0 + 0.5 * (1.0 - s))
        ph = math.radians(twist) * s
        for j in range(sides):
            th = 2.0 * math.pi * j / sides
            ex, ey = t * math.cos(th), w * math.sin(th)
            x = ex * math.cos(ph) - ey * math.sin(ph)
            y = ex * math.sin(ph) + ey * math.cos(ph)
            verts.append((c.x + x, c.y + y, c.z))
            us.append(s)
            cs.append((math.cos(th), math.sin(th), s))
    tip = cl(1.0)
    verts.append((tip.x, tip.y, tip.z))
    us.append(1.0)
    cs.append((0.0, 0.0, 1.0))
    ti = len(verts) - 1
    verts.append((0.0, 0.0, -0.01))
    us.append(0.0)
    cs.append((0.0, 0.0, 0.0))
    bi = len(verts) - 1
    for i in range(rings - 1):
        a = i * sides
        b = a + sides
        for j in range(sides):
            j2 = (j + 1) % sides
            faces.append((a + j, b + j, b + j2, a + j2))
    last = (rings - 1) * sides
    for j in range(sides):
        j2 = (j + 1) % sides
        faces.append((last + j, ti, last + j2))
        faces.append((bi, j2, j))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    bm = _bmesh7.new()
    bm.from_mesh(me)
    _bmesh7.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    au = me.attributes.new(name='lock_u', type='FLOAT', domain='POINT')
    for k, u in enumerate(us):
        au.data[k].value = u
    ac = me.attributes.new(name='lock_c', type='FLOAT_VECTOR', domain='POINT')
    for k, c in enumerate(cs):
        ac.data[k].vector = c
    return me


_lock7_material_run1 = _lock7_material


def _lock7_material(name):
    m = _lock7_material_run1(name)
    nt = m.node_tree
    n, L = nt.nodes, nt.links
    ms = next(x for x in n if x.type == 'MIX_SHADER')
    fac_in = ms.inputs['Fac'].links[0].from_socket
    lp = n.new('ShaderNodeLightPath')
    sh = n.new('ShaderNodeMath')
    sh.operation = 'MULTIPLY'
    sh.inputs[1].default_value = LOCK7_COL['shadow_tr']
    L.new(lp.outputs['Is Shadow Ray'], sh.inputs[0])
    mx = n.new('ShaderNodeMath')
    mx.operation = 'MAXIMUM'
    L.new(fac_in, mx.inputs[0])
    L.new(sh.outputs[0], mx.inputs[1])
    L.new(mx.outputs[0], ms.inputs['Fac'])
    return m


# ── run3: the COMB (one direction on the flank) + crown/beard lengths + per-lock variation ──
# run2 reads as a plush creature from the front (the locks are locks now), but:
#  * PROFILE WHORL: the middle of the flank still points at the side camera. Cause: the face-repel
#    term ran over the whole front hemisphere, and on the flank the repel direction IS the surface
#    normal (its tangent part ~0), so those locks stayed radial; the eye-level wisp band (lambda 0.7)
#    added more end-on locks. Now the repel is confined to the face's own neighbourhood
#    (|x| < 0.07: forehead up, chin down) and fades out where the flank comb takes over; flank
#    lambda 1.2 -> 1.6 (32 deg above the surface, x-component 0.53); wisps lambda 0.7 -> 0.9 with
#    L 95 -> 105 mm (lateral reach 105 x 0.74 = 78 mm = the base's pad; run2 measured 112 px vs 94).
#  * CROWN: 100 mm radial spikes put the side 0.55-width crossing at row 310 (base 340, gate +-0.08
#    of 0.221 = +-11 rows): crown L 100 -> 80 mm, no forward crest weight (0.5 -> 0.25), lambda 0.25
#    -> 0.20. Expected crown pad ~100 px (base 111).
#  * VARIATION: run2's beard was rows of identical petals (an artichoke). len_rand 0.20 -> 0.32,
#    tilt 10 -> 14 deg, roll 25 -> 40 deg, wave 0.02-0.06 -> 0.03-0.09 L; beard L 65 -> 75 mm.
TUFT7['len'].update({'crown': 0.080, 'wisp': 0.105, 'beard': 0.075})
TUFT7['lean'].update({'crown': 0.20, 'wisp': 0.90, 'flank': 1.60})
TUFT7.update(
    {
        'len_rand': 0.32,
        'tilt_jitter': 14.0,
        'roll_jitter': 40.0,
        'wave': (0.03, 0.09),
        'crest_w': 0.25,
        'rep_x': 0.07,
        'rep_fade': 0.03,
    }
)


def _flow7(P, Z):
    T = TUFT7
    wc, wb, wk, wf, wbd, ww, wr = Z
    F = Vector((0.0, 0.0, 0.0))
    wfl = _sm7((abs(P.x) - 0.07) / 0.03) * (1.0 - wc) * (1.0 - wb)  # the flank comb, front hemisphere included
    if wf > 0.0:
        near = 1.0 - _sm7((abs(P.x) - T['rep_x']) / T['rep_fade'])  # only beside the face's midline
        r = P - Vector(T['rep_c'])
        if r.length > 1e-6 and near > 0.0:
            F += r.normalized() * (wf * near * (1.0 - 0.6 * wc) * (1.0 - wfl))
    F += Vector((0.0, 0.87, -0.5)) * wfl  # flank: back and 30 deg down
    F += Vector((0.0, 0.6, -0.8)).normalized() * (0.9 * wk)  # back: lies down-back
    F += Vector((0.0, 0.0, -1.0)) * wb  # belly: hangs
    F += Vector((0.0, -0.35, -1.0)).normalized() * wbd  # beard: forward-down
    F += Vector((0.0, -0.5, 0.85)).normalized() * (T['crest_w'] * wc * (1.0 - wk))  # crown: forward crest
    if wr > 0.0:
        F = Vector((0.25 * (1.0 if P.x > 0 else -1.0), 1.0, 0.05)).normalized()  # plate rim: back along the head
    return F


# ── run4: ZONES FROM THE SURFACE NORMAL (the profile sunburst), crown FAN, softer self-shadow ─
# run3 side view: a radial sunburst in the upper-middle of the flank although the flank comb was
# in. Cause, read off _zones7: the crown weight was keyed on HEIGHT (z 0.06 -> 0.11), so the whole
# upper third of the ball — the upper flank included — faded the flank comb out ((1 - wc)) and went
# near-radial (lambda 0.2); seen from the side those locks point at the camera. Zones are now read
# off the surface NORMAL: crown = n.z 0.30 -> 0.70, belly = -n.z, back = n.y, flank comb = |n.x|
# 0.30 -> 0.60 (the eye-level wisps: |n.x| > 0.75). On the flank at z 0.08 the ellipsoid normal
# has n.z 0.29, so it stays combed; only the top of the dome is crown.
# CROWN FAN: the anchor's crown is a fan — the front locks curve up-forward over the brow, the
# back ones lie back over the nape — not a pincushion of radial spikes. Flow (0,-0.7,0.7) on the
# front half, (0,0.8,-0.2) on the back half, x0.5, lambda 0.20 -> 0.35; L 80 -> 75 mm so the
# side 0.55-width crossing (run3 row 334, gate rows 328..350) does not climb with the spread.
# SELF-SHADOW: the side eye finder took the lower chest for a pupil again (box 158 px, dark 6.2 %
# vs base 3.9 %); shadow-ray transparency 0.55 -> 0.75 (hair-like half-shadow valleys).
TUFT7['len'].update({'crown': 0.075})
TUFT7['lean'].update({'crown': 0.35})
TUFT7.update({'crown_fan': 0.5})
LOCK7_COL.update({'shadow_tr': 0.75})


def _zones7n(P, n):
    """(crown, belly, back, front, beard, wisp, rim) weights from the body-local point AND its normal."""
    x, y, z = P.x, P.y, P.z
    ax = abs(x)
    wc = _sm7((n.z - 0.30) / 0.40)
    wb = _sm7((-n.z - 0.30) / 0.40)
    wk = _sm7((n.y - 0.30) / 0.40) * (1.0 - wc)
    wf = _sm7((-0.02 - y) / 0.06)
    wbd = wf * _sm7((0.0 - z) / 0.04) * (1.0 - _sm7((ax - 0.08) / 0.03))
    ww = (
        _sm7((abs(n.x) - 0.75) / 0.15)
        * (1.0 - _sm7((abs(z - 0.04) - 0.05) / 0.03))
        * (1.0 - _sm7((y - 0.03) / 0.04))
        * (1.0 - _sm7((-0.03 - y) / 0.03))
    )
    wr = 1.0 if (ax > 0.085 and -0.11 < y < -0.02 and -0.03 < z < 0.125) else 0.0
    return wc, wb, wk, wf, wbd, ww, wr, _sm7((abs(n.x) - 0.30) / 0.30)


def _flow7(P, Z):
    T = TUFT7
    wc, wb, wk, wf, wbd, ww, wr, wx = Z
    F = Vector((0.0, 0.0, 0.0))
    wfl = wx * (1.0 - wc) * (1.0 - wb)  # the flank comb
    if wf > 0.0:
        near = 1.0 - _sm7((abs(P.x) - T['rep_x']) / T['rep_fade'])  # only beside the face's midline
        r = P - Vector(T['rep_c'])
        if r.length > 1e-6 and near > 0.0:
            F += r.normalized() * (wf * near * (1.0 - 0.6 * wc) * (1.0 - wfl))
    F += Vector((0.0, 0.87, -0.5)) * wfl  # flank: back and 30 deg down
    F += Vector((0.0, 0.6, -0.8)).normalized() * (0.9 * wk)  # back: lies down-back
    F += Vector((0.0, 0.0, -1.0)) * wb  # belly: hangs
    F += Vector((0.0, -0.35, -1.0)).normalized() * wbd  # beard: forward-down
    fan = Vector((0.0, -0.7, 0.7)) * _sm7((-P.y - 0.01) / 0.05) + Vector((0.0, 0.8, -0.2)).normalized() * _sm7(
        (P.y - 0.02) / 0.06
    )
    F += fan * (T['crown_fan'] * wc)  # crown: a front/back fan
    if wr > 0.0:
        F = Vector((0.25 * (1.0 if P.x > 0 else -1.0), 1.0, 0.05)).normalized()  # plate rim: back along the head
    return F


def _dir7(P, n, Z, rng):
    F = _flow7(P, Z)
    t = F - n * F.dot(n)
    lam = _lean7(Z[:7])
    if t.length > 1e-4:
        d = (Vector(n) + t.normalized() * (lam * min(1.0, t.length / 0.3))).normalized()
    else:
        d = Vector(n)
    if Z[6] > 0.0 and P.y < -0.04 and d.y < 0.0:  # rim band: never forward over the plate
        d.y = 0.0
        d.normalize()
    return _jitter7(d, rng, TUFT7['tilt_jitter'])


_roots7_on_run3 = _roots7_on


def _roots7_on(ob, kind, wts, p, rng, grid, eyes_w, body_loc, roots, stats):
    """run3's sampler with the normal-aware zones (same Poisson / length / eye rules)."""
    T = TUFT7
    me = ob.data
    mw = ob.matrix_world
    r3 = mw.to_3x3()
    rx, ry, rz = p['body_rx'], p['body_ry'], p['body_rz']
    er = p['eye_r']
    order = list(range(len(me.polygons)))
    rng.shuffle(order)
    sp0 = T['spacing'] if kind == 'body' else T['spacing_cap']
    for fi in order:
        poly = me.polygons[fi]
        wd = sum(wts[i] for i in poly.vertices) / float(len(poly.vertices))
        if wd <= 0.01:
            continue
        k = max(1, int(math.ceil(T['oversample'] * poly.area / (sp0 * sp0))))
        for _ in range(k):
            stats['cand'] += 1
            Pl = _face_point7(me, poly, rng)
            if rng.random() >= wd:
                continue
            Pw = mw @ Pl
            P = Pw - body_loc
            sp = sp0
            if kind == 'body':
                if P.z > 0.06:
                    sp = T['spacing_crown'] + (sp0 - T['spacing_crown']) * (1.0 - _sm7((P.z - 0.06) / 0.05))
                elif P.z < -0.02:
                    sp = sp0 + (T['spacing_belly'] - sp0) * _sm7((-0.02 - P.z) / 0.06)
            if not grid.ok(P, sp):
                continue
            if kind == 'body':
                n = Vector((P.x / (rx * rx), P.y / (ry * ry), P.z / (rz * rz))).normalized()
            else:
                n = (r3 @ poly.normal).normalized()
            Z = _zones7n(P, n)
            d = _dir7(P, n, Z, rng)
            jl = 1.0 - T['len_rand'] / 2.0 + T['len_rand'] * rng.random()
            L = _len7(P, Z[:7]) * jl
            if kind == 'cap':
                L = min(L, T['len']['cap'] * jl)
            if P.y < 0.0 and eyes_w:
                ok = False
                for trial in (1.0, 0.6):
                    Lt = L * trial
                    clear = True
                    for tt in (0.3, 0.6, 0.9):
                        q = Pw + d * (Lt * tt)
                        if min((q - e).length for e in eyes_w) < T['eye_clear'] * er:
                            clear = False
                            break
                    if clear:
                        L = Lt
                        ok = True
                        break
                if not ok:
                    stats['eye'] += 1
                    continue
            grid.add(P)
            w0 = min(T['w_max'], max(T['w_min'], T['w_per_L'] * L)) * (
                1.0 - T['w_rand'] / 2.0 + T['w_rand'] * rng.random()
            )
            r0, r1 = T['ratio']
            nv = T['variants']
            kv = int(round((w0 / L - r0) / (r1 - r0) * (nv - 1))) + rng.choice((-1, 0, 0, 1))
            kv = min(nv - 1, max(0, kv))
            Y = n.cross(d)
            x_ref = d.cross(Y) if Y.length > 0.05 else Vector((0.0, 0.0, 1.0))
            q = _frame_quat7(d, x_ref, rng, T['roll_jitter'])
            roots.append((P - n * T['sink'], q, (L, L, L), kv, rng.random()))
            stats[kind] = stats.get(kind, 0) + 1


# ── run5: the HEM and the side brightness ─────────────────────────────────────────────────
# run4 profile: the sunburst is gone (combed flank), gates pass, but (a) the eye finder still
# takes the lower chest for an eye: dissected, the base's own chest blob is w/h 1.66 with 9.4 %
# dark (a hair's breadth under the 10 % pupil test) while ours is rounder with 11-13 % dark, and
# the enlarged crops show WHERE: black gaps between the root bases of the hanging hem locks under
# the belly, where the hair coat is a soft warm gradient. (b) side lab_fur 18.5: the flank lit by
# the key renders L 234 vs the anchor's 223 (front 225 vs 227 is fine) — a diffuse+sheen shell
# facing the key reflects more than the 40 % Chiang hair mix did.
#  * hem: belly lambda 1.3 -> 1.8 (the hanging locks lie flatter and overlap), belly spacing
#    8.5 -> 7.5 mm; the base's 30 mm undercoat -> 36 mm with UNDER min 0.55 -> 0.80 (the fuzz
#    between the belly locks catches the warm bounce: the valleys read warm, not black);
#    shadow-ray transparency 0.75 -> 0.85.
#  * brightness: tip albedo (0.913,0.973,0.913) -> (0.80,0.90,0.82) — a shade darker and more
#    mint (crown a* 125 vs anchor 115: our crown is whiter than the anchor's mint); sheen 0.5 ->
#    0.3 (the sheen lobe is what lit the profile's grazing locks). Root unchanged.
TUFT7['lean'].update({'belly': 1.80})
TUFT7.update({'spacing_belly': 0.0075})
UNDERCOAT2.update({'len': 0.036})
UNDER.update({'min': 0.80})
LOCK7_COL.update({'shadow_tr': 0.85, 'tip': (0.80, 0.90, 0.82), 'sheen': 0.3})


# ═════════════════════════════════════════════════════════════════════════════
# R7EYES (lookdev2 round 3 / r3_eyes) — BONE SOCKET RING + OVERHANGING UPPER LID
#
# Critic (after round 2, [major]): the eyes have no bone-coloured socket rim and no overhanging
# upper lid. cell_11: each eye sits in a thick cream-tan ring ~22 % of the iris radius wide, with
# a 20-25 px dark crease under the top of the ring where it overhangs the iris; the opening is a
# rounded square with a flatter top edge. Ours: iris -> 5-12 px pale collar lip -> teal plate, a
# perfect circle, no crease.
#
# MEASURED FIRST (pbfit.find_eyes on the anchors, gate_boxes.png): the harness's amber gate
# (H 8-30, S > 110, V > 90) PASSES the anchor's lit ring — anchor_full row 445 x 598-604 is the
# tan rim at HSV (17-22, 125-135, 108-174) and the magenta gate mask covers the lower rim in
# both anchor_full and cell_11 — so the frozen front eye_frac 0.157 is iris + lit lower rim, and
# our base 0.156 is the bare iris. A ring at the critic's (225,185,130) (S 0.42-0.46) would join
# the blob and read +10..20 % (the R5 LIGHT run7 note saw exactly this with the old pb_lid: +29 %).
# So the ring is a BONE tone one step less saturated than the critic's probe, chosen to stay
# under the gate (sRGB ~(222,190,148), S 0.33): eye_frac unchanged, as the critic asked.
#
# WHAT IS BUILT (eye-LOCAL frame of the R5 lens: x lateral, -y forward, z up; object at c, rot q)
#  * pb_rim_l/r: a closed-profile bezel swept about the lens axis. Inner edge at rho 0.88 er —
#    where the skin collar's lip already crosses the lens (0.87-0.89), so the visible iris is the
#    same disc as before and the collar's pale lip disappears under the ring. Width 0.22 x R
#    (R = RIM_RHO er = the visible iris radius) = 0.20 er = 10.7 mm; the top stands 0.08 x R =
#    3.9 mm above the lens at the inner edge (a vertical inner wall -> the crease shadow), a flat
#    crown, a rounded outer fall onto the skin collar, both skirts buried (lens / collar).
#  * the UPPER ARC's z is scaled by 0.85 (the ring rides up the dome: its inner edge sits at
#    rho 0.75 at the top, covering the top 0.13 er of the lens — the flat top edge) and the
#    upper third is pushed forward another 0.05 x R, so the top edge cuts straight across and
#    hangs over the iris; the key (upper camera-right) casts the crease under it.
#  * material pb_rim: albedo (0.73,0.51,0.30) lin, roughness 0.35, coat 0.30. pass_index face.
#    Added to FACE_PARTS so the face-only light lights it like the plate; pb_ prefix -> key.
#  * nothing else moves: eye centre, lens depth, RIM_RHO, pupil, glint, collar, fur, lights.
# ═════════════════════════════════════════════════════════════════════════════
RING7 = {
    'rho_in': 0.88,  # er: inner edge on the sides/bottom (= where the collar lip crosses the lens)
    'width': 0.22 * RIM_RHO,  # 0.202 er = 10.7 mm (critic: 0.22 x iris radius)
    'proud': 0.08 * RIM_RHO,  # 0.074 er = 3.9 mm above the lens at the inner edge
    'crown': 0.018,  # er: extra height at the middle of the flat top
    'top_z': 0.85,  # z scale of the upper arc (flat top edge)
    'fwd': 0.05 * RIM_RHO,  # 0.046 er = 2.4 mm extra forward push of the upper third
    'fwd_s0': 0.33,
    'fwd_s1': 0.80,  # smoothstep in sin(u): 0 at the sides -> full at the top
    'bury_in': 0.12,
    'bury_out': 0.25,  # er: skirt depth into the lens / the collar+plate
    'seg': 96,
    'rgb': (0.73, 0.51, 0.30),
    'rough': 0.35,
    'coat': 0.30,
    'coat_rough': 0.12,
}


def _collar_t(rho, u):
    """The R5 skin collar's axial height (er units) at effective rho / angle u (crest + smoothstep fall)."""
    C = COLLAR
    vert = 0.5 * (1.0 + math.sin(u))
    lip = C['lip_bot'] + (C['lip_top'] - C['lip_bot']) * vert
    t_cr = _lens_t(RIM_RHO) + lip
    if rho <= RIM_RHO:
        return t_cr
    return t_cr - C['H'] * _sstep((rho - RIM_RHO) / C['W'])


def _rim_material():
    m = bpy.data.materials.get('pb_rim')
    if m is not None:
        return m
    m = bpy.data.materials.new('pb_rim')
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*RING7['rgb'], 1.0)
    b.inputs['Roughness'].default_value = RING7['rough']
    b.inputs['Specular IOR Level'].default_value = 0.5
    b.inputs['Coat Weight'].default_value = RING7['coat']
    b.inputs['Coat Roughness'].default_value = RING7['coat_rough']
    return m


def _socket_ring(name, c, q, er, scene, PB):
    R = RING7
    s1 = R['seg']
    W = R['width']
    ri0 = R['rho_in']
    ro0 = ri0 + W
    rings = []
    stats = {}
    for i in range(s1):
        u = 2.0 * math.pi * i / s1
        su = math.sin(u)
        cu = math.cos(u)
        zf = R['top_z'] if su > 0.0 else 1.0
        fwd = R['fwd'] * _sstep((su - R['fwd_s0']) / (R['fwd_s1'] - R['fwd_s0']))
        eff = lambda rho, cu=cu, su=su, zf=zf: (
            rho * math.sqrt(cu * cu + (su * zf) ** 2)
        )  # true radial distance after the z scale
        ri_e, ro_e = eff(ri0), eff(ro0)
        t_lens = _lens_t(ri_e)
        t_in = t_lens + R['proud'] + fwd  # inner top corner
        t_top = t_in + R['crown']
        t_out = _collar_t(ro_e, u) + 0.015  # where the outer fall lands on the collar
        prof = [
            (ri0, t_lens - R['bury_in']),  # buried in the lens
            (ri0, t_in),
            (ri0 + 0.10 * W, t_in + 0.012),
            (ri0 + 0.45 * W, t_top),
        ]
        for a in (0.25, 0.50, 0.72, 0.88, 1.00):
            ang = a * math.pi / 2.0
            prof.append((ri0 + 0.45 * W + 0.55 * W * math.sin(ang), t_out + (t_top - t_out) * math.cos(ang)))
        prof.append((ro0 + 0.03, _collar_t(eff(ro0 + 0.03), u) - R['bury_out']))  # buried in the collar / plate
        rings.append([(er * rho * cu, -er * t, er * rho * su * zf) for (rho, t) in prof])
        if i in (0, s1 // 4, s1 // 2, 3 * s1 // 4):
            stats[i] = (ri_e, t_in - t_lens, t_in, t_out)
    n_r = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces = []
    for i in range(s1):
        i2 = (i + 1) % s1
        b0, b1 = i * n_r, i2 * n_r
        for j in range(n_r - 1):
            faces.append((b0 + j, b0 + j + 1, b1 + j + 1, b1 + j))  # outward x tangent -> -y (forward)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_rim_material())
    ob = bpy.data.objects.new(name, me)
    ob.location = c
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = q
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    print(
        'R7EYES %s: inner edge rho %.3f (side) / %.3f (top); wall above the lens %.1f mm (side) / %.1f mm (top); '
        'top corner t %.3f/%.3f er, lands on the collar at t %.3f/%.3f er; width %.1f mm'
        % (
            name,
            stats[0][0],
            stats[s1 // 4][0],
            stats[0][1] * er * 1000,
            stats[s1 // 4][1] * er * 1000,
            stats[0][2],
            stats[s1 // 4][2],
            stats[0][3],
            stats[s1 // 4][3],
            W * er * 1000,
        )
    )
    return ob


FACE_PARTS = tuple(FACE_PARTS) + ('pb_rim',)
_post_build_r6_all = post_build


def post_build(scene, result, PB):
    _post_build_r6_all(scene, result, PB)
    p = dict(_P)
    for side in ('l', 'r'):
        c = _EYES.get('c_' + side)
        q = _EYES.get('q_' + side)
        if c is None or q is None:
            print('R7EYES: no eye frame for', side)
            continue
        result['parts'].append(_socket_ring('pb_rim_' + side, c, q, p['eye_r'], scene, PB))
    bpy.context.view_layer.update()


# ── run2: ring borders the LENS RIM; collar lip sunk; TAN albedo ─────────────────────────
# run1 (probe cmp_run1_close.png): the ring rendered near-white — lit top (228,227,207) S 0.09,
# shade (179,184,152) — for an albedo whose sRGB is (222,190,148) S 0.33: the mint-white key
# over-lights the up-facing crown (L ~90 vs the anchor rim's L77) and AgX's shoulder pulls it to
# white, and the rig's green tint puts rendered R below G. It read as ivory goggles at 45 deg.
# Front eye box 100x121 -> 97x112 (eye_frac -6.7 %): the 0.85 top flattening took 0.13 er off
# the top of the disc and the inner edge at 0.88 a little off the width.
#  * inner edge -> RIM_RHO (0.92): the ring now borders the lens's own rim; the skin collar's lip
#    (lip_top/bot 0.08/0.03 -> -0.02) sinks under the lens, so no pale collar lip shows inside
#    the ring and the visible disc is the full 0.92 er (width +4.5 %). Expected box ~101 x 117
#    -> max 117 vs 121 = -3.3 %, inside the gate; the flat top (0.85) stays.
#  * albedo (0.73,0.51,0.30) -> (0.50,0.28,0.13) lin (sRGB (188,145,100), S 0.47): darker so the
#    lit crown stays out of AgX's shoulder, and warm enough to survive the green rig. Target
#    rendered ~(215,180,135): the critic's tan, with S just under the harness amber gate (0.43).
COLLAR['lip_top'] = -0.02
COLLAR['lip_bot'] = -0.02
RING7['rho_in'] = RIM_RHO
RING7['rgb'] = (0.50, 0.28, 0.13)
print('R7EYES run2: rho_in %.2f, collar lip %.3f, rim albedo %s' % (RING7['rho_in'], COLLAR['lip_top'], RING7['rgb']))


# ── run3: ring MATERIAL — albedo in the plate's range, warm-biased against the green rig ────
# run2 probes (cmp_run2_close.png, col 330 / row 300): lit crown (231,226,196), sides (222,214,177),
# the shaded outer fall (168,162,121) — R ~= G everywhere for an albedo with R/G 1.8. Two things:
# the rig is hot enough that skin tuned the plate to FACE_MID G 0.105 (renders L ~180), so a 0.50
# albedo sits in AgX's shoulder and goes white; and the light is green-tinted (a neutral surface
# renders R/G ~0.58, R/B ~0.36 — read off the shaded fall). For the critic's rendered tan
# (225,185,130) the albedo must carry R/G ~2.1 and R/B ~4.8 at ~1/2 the plate's brightness in G:
# (0.24,0.115,0.05). Coat 0.30 -> 0.10 and specular 0.5 -> 0.3: the coat's white Fresnel off the
# big area lights was the other desaturator (the anchor rim is a matte bone, not a lacquer).
RING7['rgb'] = (0.24, 0.115, 0.05)
RING7['coat'] = 0.10
RING7['coat_rough'] = 0.25
_rim_material_r2 = _rim_material


def _rim_material():
    m = _rim_material_r2()
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*RING7['rgb'], 1.0)
    b.inputs['Specular IOR Level'].default_value = 0.3
    b.inputs['Coat Weight'].default_value = RING7['coat']
    b.inputs['Coat Roughness'].default_value = RING7['coat_rough']
    return m


print('R7EYES run3: rim albedo %s coat %.2f' % (RING7['rgb'], RING7['coat']))


# ── run4: ring one step LESS saturated — the harness amber gate is the ceiling ─────────────
# run3 rendered the critic's tone in L (crown (209,196,156) L78, sides (198,178,127) L73, shade
# (133,121,84); anchor rim L77 lit / L54 shade) but at S 0.28-0.37 the ring joined the amber blob
# (gate S > 0.43 on the boundary-mixed pixels + 7x7/9x9 closes) and the front eye box went
# 102x118 -> 128x129 (+6.5 %). run2's ivory (S 0.17-0.20) stayed out. The anchor's OWN box
# includes its lit rim (S 0.46), so on this rig a true tan can only pass eye_frac if the iris
# shrinks ~12 % — the form agent's number, and the critic said to keep it. Albedo B 0.05 -> 0.078:
# predicted (200,185,165) S ~0.18 H ~34 deg, a warm bone; the shade ~(133,121,100) S 0.25.
RING7['rgb'] = (0.24, 0.115, 0.078)
print('R7EYES run4: rim albedo %s' % (RING7['rgb'],))


# ── run5: ring S one more step down (gate margin) + IRIS GRADIENT (the [minor] item) ───────
# run4 ring: crown (209,195,172) L79, sides (196,180,156) L74, shade (133,122,98) L51 — the
# anchor rim's L (77 lit / 54 shade) and hue, at half its saturation (S 0.20-0.28 vs 0.46). Front
# eye box 110x123 (+4.04 %, the gate is 4.0): the left ring's inner wall, lit by the iris's own
# amber bounce, still tips over S 0.43 in a few px and the 9x9 close joins them. The profile eye
# was FOUND for the first time (60x100 px, w/h 0.60 exactly: the lit front lip widened it past
# the 0.6 roundness gate) and reads +9.3 % — the base's profile eye was 0.150 in the ID pass
# against the anchor's 0.128 all along; the harness only rejected it as too narrow.
#  * ring albedo (0.24,0.115,0.078) -> (0.24,0.120,0.095): rendered S ~0.15-0.20, hue kept
#    (H ~30 deg), so neither the front spill nor the profile lip passes the amber gate.
#  * iris (critic [minor]): yellow-amber limbus -> dark umber at the pupil. Bands re-laid on the
#    visible radius: limbus 0.93 brighter and with less B (the rig's green light put our amber at
#    (220,160,77) vs the anchor's (240,171,32)), the inner third darkened to umber, the dark
#    collar round the pupil 0.08 -> 0.11 er, fibres 0.48 -> 0.60, spokes 0.14 -> 0.20.
RING7['rgb'] = (0.24, 0.120, 0.095)
COLLAR_W = 0.11
FIBRE_AMP = 0.60
STRIPE_AMP = 0.20


def _rim_bands(rim):
    return [
        (0.00, (0.018, 0.009, 0.006)),
        (_u(rim * 1.03), (0.018, 0.009, 0.006)),
        (_u(rim * 0.975), (0.14, 0.050, 0.010)),  # limbal ring
        (_u(rim * 0.93), (0.64, 0.175, 0.010)),  # yellow-amber limbus
        (_u(rim * 0.85), (0.58, 0.145, 0.008)),
        (_u(rim * 0.76), (0.40, 0.085, 0.005)),
        (_u(rim * 0.68), (0.21, 0.040, 0.003)),
        (_u(rim * 0.60), (0.10, 0.021, 0.002)),  # umber at the pupil edge (pupil at 0.60 x rim)
        (1.00, (0.08, 0.018, 0.002)),
    ]


BANDS5 = _rim_bands(RIM_RHO)
print(
    'R7EYES run5: rim albedo %s; iris bands re-laid (collar %.2f, fibres %.2f, spokes %.2f)'
    % (RING7['rgb'], COLLAR_W, FIBRE_AMP, STRIPE_AMP)
)


print('R7 MERGE: tuft coat + socket rings assembled')


# ── R7 MERGE run2: the ring's flat top, one step less flat — front eye_frac gate ──────────────
# run1 (merge of tuft + eyes as delivered): front eye_frac -4.7 % (gate 4.0). The harness's front
# eye box went base 100x121 -> run1 102x118 and the silhouette 769 -> 789 px: the ring's 0.85 top
# flattening moved the box top DOWN 5 px (429 -> 434) while the sunk collar lip gave 2 px back at
# the bottom, and the tuft's longer temple wisps (105 mm, the front aspect -4.1 -> -1.6 %) widened
# the denominator 2.6 %. Each round passed alone (-2.2 %, -2.6 %); together they add. The width is
# now the anchor's, so the lever is the ring: top_z 0.85 -> 0.91 (inner edge at the top rho 0.782
# -> 0.837 er, +2 px of box height -> ~120/789 = -3.1 %). The overhang keeps its forward push
# (RING7 fwd) and the crease under it; the opening's top is a little rounder than the eyes round's.
RING7['top_z'] = 0.91
print('R7 MERGE run2: RING7 top_z %.2f' % RING7['top_z'])


# ── R7 MERGE run3: the lock TIP ramp, one step down — the profile is a white puffball ─────────
# run2 passes every gate the merge can reach (front eye_frac -1.4 %, close +1.2 %); the side
# aspect -5.1 % is a lone tail-strand pixel (base 716 px wide on one stray pixel at x 857, every
# ring run 715) on a gate the base sat on, and is left alone. What is left on the profile is the
# tuft round's own caveat: the flank faces both the side camera and the key, and a diffuse shell
# reflects that back where the Chiang hair scattered forward — near-white (L >= 235) 43 % of the
# fur px vs the anchor's 17 % (base 24 %), side lab_fur 15.0 on the gate; the front too is a
# little whiter than the anchor (37 % vs 31 %). tuft.py's runs 6-8 fixed the tones but every one
# also darkened the self-shadow (0.65) or built a skirt, and the eye finder then read the shadowed
# LEGS as a pupil. Only the albedo ramp is taken here, nothing on shadows or the hem:
#   * tip (0.80,0.90,0.82) -> (0.70,0.82,0.74) linear (sRGB ~(220,233,224), the anchor's lit lock
#     bodies read (225-240, 240-250, 225-238));
#   * the ramp reaches the tip colour at u 0.90 instead of 0.75, so the mid-lock is a mint blend
#     and only the points are cream (the anchor's locks are cream at the point, mint in the body).
# Root (185,235,215) sRGB, SSS 0.6, shadow transparency 0.85, sheen 0.3 unchanged.
LOCK7_COL.update({'tip': (0.70, 0.82, 0.74), 'tip_at': 0.90})
print('R7 MERGE run3: lock tip %s at u %.2f' % (LOCK7_COL['tip'], LOCK7_COL['tip_at']))


# ── R7 MERGE run4 (FINAL): run3 REVERTED — the tip ramp is back to the tuft round's run5 ─────
# run3 (tip (0.70,0.82,0.74) at u 0.90) failed a gate the merge had passed: the side eye finder
# found a 'profile eye' at +72.7 % — the warm-lit belly locks, a shade darker and more mint, now
# pass the harness's amber gate (H 8-30, S > 110) and the blob merges with the dark leg pixels
# into a pupil-bearing 'eye' (the tuft round's trap, reached through saturation instead of
# shadow). Side lab_fur 15 -> 19, lab_face 17 -> 25 (the face ROI now exists and lands on fur),
# and the harness's fur gate (S < 70) dropped from 182k to 101k px, so the near-white share of
# what remained ROSE (51 -> 59 %): a darker mint tip does not read as less white to this
# harness, it reads as 'not fur'. Measured on the anchors with the same gate: front near-white
# 44.6 % (ours 26 %), side 21.9 % (ours 51 %) — the front anchor is WHITER than ours, only the
# profile is over-lit, and a global albedo step is the wrong lever for a one-view problem (the
# profile's key/flank geometry; a light or shadow-transparency lever the leg artefact forbids).
# The overlay's state is run2's: tuft coat run5 + eyes run5 + RING7 top_z 0.91.
LOCK7_COL.update({'tip': (0.80, 0.90, 0.82), 'tip_at': 0.75})
print('R7 MERGE run4: tip ramp reverted to %s at u %.2f (= run2)' % (LOCK7_COL['tip'], LOCK7_COL['tip_at']))


# ═════════════════════════════════════════════════════════════════════════════
# R8 MERGE (lookdev2 round 4 / r4_merge) — base = r3_merge/merge.py (everything above this line
# verbatim). Appended in this order: R8 FUR-TUFT (r4_fur_tuft/tuft.py, the fur winner), R8EYES
# (r4_eyes/eyes.py), R8 LIGHT (r4_light/light.py), then the R8 MERGE fixes at the very end.
# r4_fur_hair/fur_hair.py is NOT merged (see the R8 MERGE notes at the end of the file).
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# R8 FUR-TUFT (lookdev2 round 4 / r4_fur_tuft) — soft, fibrous locks: material + a strand fringe
#
# Critic (after round 3, [major]): the locks are hard-edged opaque white petals with no fibre
# detail and no translucency — cut paper / plastic feathers at close range. cell_11's locks are
# soft-edged with fine fibres at the tips and warm, slightly translucent bases. Asked for: lock
# SSS 0.35 with radius (0.9,1.0,0.95), root mint (200,235,225) -> tip white, an alpha taper over
# the last 25 % of u, and a sparse child-strand layer (~150 strands per lock, 0.4 lock width,
# 1.1 lock length) on the outer 30 % of locks. tuft.py's runs 6-8 (the tonal pass) were dropped by
# the merge because darker tones/shadows put the shadowed LEGS under the belly into the harness's
# amber+dark eye finder; nothing here touches shadow transparency, the hem, the undercoat or the
# skirt — the material change is albedo/SSS/alpha only, and the strands are a separate object.
#
# run1 — LOCK MATERIAL ONLY (attributable; the strand layer is run2):
#  * root (185,235,215) -> (200,235,225) sRGB = (0.578,0.822,0.752) lin; tip (0.80,0.90,0.82)
#    -> (0.87,0.94,0.88) (sRGB ~(240,248,242): white-cream, not the R7 run1 (245,252,245) that
#    over-lit the profile), ramp reaching the tip at u 0.85 (was 0.75) so the mid-lock is mint.
#  * subsurface 0.6 -> 0.35, radius (1.0,0.9,0.8) -> (0.9,1.0,0.95) x 8 mm: the bases glow
#    mint-white instead of warm-pink (the anchor's warmth is the LIGHT, its translucency is mint).
#  * alpha taper: the tip fade runs u 0.75 -> 1.0 to FULL transparency (tip_max 0.7 -> 1.0), so
#    the last quarter of every lock dissolves instead of ending in a hard white point.
#  * fibre grain (from tuft run6, never merged): bump 0.35 -> 0.9 at 0.8 mm, 18 streaks across
#    (was 10), albedo variation 0.10 -> 0.22 — the parallel striations cell_11 shows on every lock.
# ═════════════════════════════════════════════════════════════════════════════
LOCK7_COL.update(
    {
        'root': (0.578, 0.822, 0.752),
        'tip': (0.87, 0.94, 0.88),
        'tip_at': 0.85,
        'sss': 0.35,
        'sss_radius': (0.9, 1.0, 0.95),
        'sss_scale': 0.008,
        'tip_u0': 0.75,
        'tip_max': 1.0,
        'grain_bump': 0.9,
        'grain_dist': 0.0008,
        'grain_across': 18.0,
        'grain_col': 0.22,
    }
)
print(
    'R8 TUFT run1: lock material root %s tip %s at u %.2f, sss %.2f %s, tip fade %.2f->1.0 max %.1f, grain bump %.1f x%.0f col %.2f'
    % (
        LOCK7_COL['root'],
        LOCK7_COL['tip'],
        LOCK7_COL['tip_at'],
        LOCK7_COL['sss'],
        LOCK7_COL['sss_radius'],
        LOCK7_COL['tip_u0'],
        LOCK7_COL['tip_max'],
        LOCK7_COL['grain_bump'],
        LOCK7_COL['grain_across'],
        LOCK7_COL['grain_col'],
    )
)


# ── run2: STRAND FRINGE — fine fibres on the outer locks ─────────────────────────────────────
# The critic's "sparse child-strand layer (~150 strands per lock, 0.4 lock width, 1.1 lock length)
# on the outer 30 % of locks". A lock is an instanced shell, so it has no particle children; the
# fibres are built here from the same root frames the locks were instanced with: for every lock in
# the top 30 % by tip reach (the tip's ellipsoid radius rho(tip) over the core — crown, wisps,
# beard: the silhouette-forming locks), 150 strands start ON the lock's surface at u 0.45-0.85,
# follow its centreline (curl + wave + twist, the very same functions as the lock mesh), and run
# past the tip by 3-15 % of L, flaring sideways by up to 0.06 L as the lock tapers to nothing, so
# each hard white point ends in a brush of fine fibres. Radius 0.22 mm root -> 0.02 mm tip.
# PLUMBING (measured in _test_curves4.py): Cycles 4.3 does NOT render curves that a Geometry
# Nodes tree outputs on a MESH object, but does render them on a CURVES object; and the harness
# hides fur in the ID pass by switching off every modifier named 'fur' on MESH objects only. So:
#   pb_wisp_locks  (MESH, the strand points + 'cid'/'srad' attributes, a GN modifier named 'fur':
#                   Mesh to Points -> Points to Curves -> Set Curve Radius)   -> toggled by the harness
#   pb_body_wisps  (CURVES, GN: Object Info(pb_wisp_locks) -> Set Material(_hair_material))
# With 'fur' off the carrier's evaluated geometry is a bare vertex cloud, so the Curves object
# outputs nothing and the ID pass stays hair-free (test: _t4_wb_off.png is empty). The name
# '..._locks' keeps the point cloud out of _fit_camera (it skips *_locks), and lighting() below
# links the Curves object into every light-linking collection the lock carrier is in.
# Material: the base's graded hair BSDF (_hair_material: FUR_COL root/tip on the strand intercept,
# Chiang + diffuse mix) — the same fibre the undercoat is made of, so the fringe matches it.

WISP8 = {
    'frac': 0.30,  # share of locks that carry strands (top by tip reach)
    'per_lock': 150,
    'u0': (0.45, 0.85),  # strand start along the lock (u)
    'ext': (0.03, 0.15),  # strand end past the lock tip, x L
    'hold': 0.35,  # the strand keeps >= this x its start half-width as the lock tapers
    'rho': (0.55, 1.0),  # start radius as a fraction of the local cross-section (on/just under the surface)
    'drift': 0.06,  # lateral flare at the end, x L
    'r_root': 0.00022,
    'r_tip': 0.00002,
    'pts': 6,
    'seed': 8,
}
_W8 = {}

_lock7_mesh_r7 = _lock7_mesh


def _lock7_mesh(name, ratio, curl, wave, freq, twist, rng):
    """Record each variant's shape parameters so the strands can follow the same centreline."""
    _L7.setdefault('vars', {})[name] = dict(ratio=ratio, curl_amt=curl, wave=wave, freq=freq, twist=twist)
    return _lock7_mesh_r7(name, ratio, curl, wave, freq, twist, rng)


_lock7_object_r7 = _lock7_object


def _lock7_object(scene, name, roots, coll, pass_index, location):
    _L7['roots'] = list(roots)
    _L7['body_loc'] = Vector(location)
    return _lock7_object_r7(scene, name, roots, coll, pass_index, location)


def _lock8_local(v, s):
    """Lock-local centreline point and cross-section half-axes (t, w) and twist angle at u = s (unit lock)."""
    T = TUFT7
    if s <= 1.0:
        c = Vector((v['curl_amt'] * s * s, v['wave'] * math.sin(2.0 * math.pi * v['freq'] * s) * s, s))
    else:
        c1 = Vector((v['curl_amt'], v['wave'] * math.sin(2.0 * math.pi * v['freq']), 1.0))
        s2 = 0.97
        c2 = Vector((v['curl_amt'] * s2 * s2, v['wave'] * math.sin(2.0 * math.pi * v['freq'] * s2) * s2, s2))
        c = c1 + (c1 - c2) * ((s - 1.0) / (1.0 - s2))
    sc = min(1.0, max(0.0, s))
    a = 0.55 + 0.45 * _sm7(sc / 0.30)
    prof = a * ((1.0 - sc) ** 0.7) / 0.78
    w = v['ratio'] * prof
    t = w * T['thick'] * (1.0 + 0.5 * (1.0 - sc))
    return c, t, w, math.radians(v['twist']) * sc


def _wisp8_curves_gn(name):
    g = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    g.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    g.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    gi = g.nodes.new('NodeGroupInput')
    go = g.nodes.new('NodeGroupOutput')
    m2p = g.nodes.new('GeometryNodeMeshToPoints')
    m2p.mode = 'VERTICES'
    p2c = g.nodes.new('GeometryNodePointsToCurves')
    na = g.nodes.new('GeometryNodeInputNamedAttribute')
    na.data_type = 'INT'
    na.inputs['Name'].default_value = 'cid'
    nr = g.nodes.new('GeometryNodeInputNamedAttribute')
    nr.data_type = 'FLOAT'
    nr.inputs['Name'].default_value = 'srad'
    idx = g.nodes.new('GeometryNodeInputIndex')
    scr = g.nodes.new('GeometryNodeSetCurveRadius')
    L = g.links.new
    L(gi.outputs['Geometry'], m2p.inputs['Mesh'])
    L(m2p.outputs['Points'], p2c.inputs['Points'])
    L(na.outputs['Attribute'], p2c.inputs['Curve Group ID'])
    L(idx.outputs['Index'], p2c.inputs['Weight'])
    L(p2c.outputs['Curves'], scr.inputs['Curve'])
    L(nr.outputs['Attribute'], scr.inputs['Radius'])
    L(scr.outputs['Curve'], go.inputs['Geometry'])
    return g


def _wisp8_carrier_gn(name, src, mat):
    g = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    g.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    g.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    g.nodes.new('NodeGroupInput')
    go = g.nodes.new('NodeGroupOutput')
    oi = g.nodes.new('GeometryNodeObjectInfo')
    oi.inputs['Object'].default_value = src
    oi.transform_space = 'RELATIVE'
    sm = g.nodes.new('GeometryNodeSetMaterial')
    sm.inputs['Material'].default_value = mat
    g.links.new(oi.outputs['Geometry'], sm.inputs['Geometry'])
    g.links.new(sm.outputs['Geometry'], go.inputs['Geometry'])
    return g


def _wisps8(scene, PB, p):
    W = WISP8
    roots = _L7.get('roots')
    vars_ = _L7.get('vars')
    if not roots or not vars_:
        print('R8 WISPS: no lock roots/variants recorded')
        return
    t0 = _time8.time()
    body_loc = _L7['body_loc']
    rng = _random7.Random(W['seed'])
    rx, ry, rz = p['body_rx'], p['body_ry'], p['body_rz']
    # rank the locks by tip reach over the core (ellipsoid radius of the tip)
    reach = []
    for i, (P, q, sc, kv, _rnd) in enumerate(roots):
        v = vars_['lock7_%d' % kv]
        tip = Vector(P) + q @ (_lock8_local(v, 1.0)[0] * sc[2])
        reach.append((math.sqrt((tip.x / rx) ** 2 + (tip.y / ry) ** 2 + (tip.z / rz) ** 2), i))
    reach.sort(reverse=True)
    sel = [i for _, i in reach[: int(round(W['frac'] * len(roots)))]]
    K = W['pts']
    verts = []
    cid = []
    rad = []
    n = 0
    rr, rt = W['r_root'], W['r_tip']
    for i in sel:
        P, q, sc, kv, rnd = roots[i]
        L = sc[2]
        v = vars_['lock7_%d' % kv]
        base = body_loc + Vector(P)
        for _ in range(W['per_lock']):
            s0 = rng.uniform(*W['u0'])
            s1 = 1.0 + rng.uniform(*W['ext'])
            th = rng.uniform(0.0, 2.0 * math.pi)
            rho = rng.uniform(*W['rho'])
            c0, t0w, w0, _ = _lock8_local(v, s0)
            dr = rng.uniform(0.0, W['drift'])
            dth = rng.uniform(0.0, 2.0 * math.pi)
            for j in range(K):
                f = j / float(K - 1)
                s = s0 + (s1 - s0) * f
                c, t, w, ph = _lock8_local(v, s)
                tt = max(t, W['hold'] * t0w) * rho
                ww = max(w, W['hold'] * w0) * rho
                ex, ey = tt * math.cos(th), ww * math.sin(th)
                fl = dr * f * f
                x = ex * math.cos(ph) - ey * math.sin(ph) + fl * math.cos(dth)
                y = ex * math.sin(ph) + ey * math.cos(ph) + fl * math.sin(dth)
                pw = base + q @ (Vector((c.x + x, c.y + y, c.z)) * L)
                verts.append((pw.x, pw.y, pw.z))
                cid.append(n)
                rad.append(rt + (rr - rt) * ((1.0 - f) ** 0.7))
            n += 1
    me = bpy.data.meshes.new('pb_wisp_locks')
    me.from_pydata(verts, [], [])
    me.validate()
    a = me.attributes.new('cid', 'INT', 'POINT')
    a.data.foreach_set('value', cid)
    r = me.attributes.new('srad', 'FLOAT', 'POINT')
    r.data.foreach_set('value', rad)
    src = bpy.data.objects.new('pb_wisp_locks', me)
    scene.collection.objects.link(src)
    src.pass_index = PB.IDX['body']
    md = src.modifiers.new('fur', 'NODES')
    md.node_group = _wisp8_curves_gn('pb_wisp8_src_gn')
    cv = bpy.data.hair_curves.new('pb_body_wisps')
    car = bpy.data.objects.new('pb_body_wisps', cv)
    scene.collection.objects.link(car)
    car.pass_index = PB.IDX['body']
    md2 = car.modifiers.new('wisps', 'NODES')
    md2.node_group = _wisp8_carrier_gn('pb_wisp8_gn', src, _hair_material())
    _W8['src'] = src
    _W8['car'] = car
    Ls = [roots[i][2][2] for i in sel]
    print(
        'R8 WISPS: %d strands x %d pts on %d of %d locks (L %.0f..%.0f mm, reach >= %.3f) in %.1fs'
        % (n, K, len(sel), len(roots), 1000 * min(Ls), 1000 * max(Ls), reach[len(sel) - 1][0], _time8.time() - t0)
    )


_post_build_r8_mat = post_build


def post_build(scene, result, PB):
    _post_build_r8_mat(scene, result, PB)
    _wisps8(scene, PB, dict(_P))
    bpy.context.view_layer.update()


_lighting_r8_base = lighting


def lighting(scene, centre, size, aim):
    _lighting_r8_base(scene, centre, size, aim)
    car = _W8.get('car')
    locks = _ob('pb_body_locks')
    if car is None or locks is None:
        return
    joined = []
    for coll in bpy.data.collections:
        if locks.name in coll.objects and car.name not in coll.objects:
            coll.objects.link(car)
            joined.append(coll.name)
    print('R8 WISPS: pb_body_wisps linked into %s' % (joined,))


# ── run3: the fringe as FINE TIP FIBRES, not a mop ─────────────────────────────────────────
# run2 (150 strands/lock at 0.22 mm root from u 0.45, full cross-section) covered the outer locks
# in yarn: close-up = a string mop of separate ropes, profile = a hanging curtain; fibres hung over
# the left bezel (front ID-gated eye box 130 -> 122 px tall) and the coat went grey (side L>=235
# 50 -> 35 %: the strands shadow the locks under them). The anchor's fibres are barely-visible
# hairs that splay from the last quarter of a lock and a little past its point. So: 60 strands per
# lock, root radius 0.09 mm -> 0.01 mm (0.1 px at 1024, ~0.3 px in the close-up), starting at
# u 0.62-0.95 on the outer 70-100 % of the cross-section, running 5-20 % past the tip with a
# 0.08 L flare; locks whose tip comes within 1.8 eye radii of an eye centre get none (the [minor]
# hairline item: nothing may hang into the eyes).
WISP8.update(
    {
        'per_lock': 60,
        'r_root': 0.00009,
        'r_tip': 0.00001,
        'u0': (0.62, 0.95),
        'ext': (0.05, 0.20),
        'hold': 0.5,
        'rho': (0.7, 1.0),
        'drift': 0.08,
        'eye_clear': 1.8,
    }
)


def _wisps8(scene, PB, p):
    W = WISP8
    roots = _L7.get('roots')
    vars_ = _L7.get('vars')
    if not roots or not vars_:
        print('R8 WISPS: no lock roots/variants recorded')
        return
    t0 = _time8.time()
    body_loc = _L7['body_loc']
    rng = _random7.Random(W['seed'])
    rx, ry, rz = p['body_rx'], p['body_ry'], p['body_rz']
    er = p['eye_r']
    eyes = [Vector(c) for c in (_R4_EYES.get('c') or [])]  # body-local eye centres
    reach = []
    near_eye = 0
    for i, (P, q, sc, kv, _rnd) in enumerate(roots):
        v = vars_['lock7_%d' % kv]
        tip = Vector(P) + q @ (_lock8_local(v, 1.0)[0] * sc[2])
        if eyes and min((tip - e).length for e in eyes) < W['eye_clear'] * er:
            near_eye += 1
            continue
        reach.append((math.sqrt((tip.x / rx) ** 2 + (tip.y / ry) ** 2 + (tip.z / rz) ** 2), i))
    reach.sort(reverse=True)
    sel = [i for _, i in reach[: int(round(W['frac'] * len(roots)))]]
    K = W['pts']
    verts = []
    cid = []
    rad = []
    n = 0
    rr, rt = W['r_root'], W['r_tip']
    for i in sel:
        P, q, sc, kv, rnd = roots[i]
        L = sc[2]
        v = vars_['lock7_%d' % kv]
        base = body_loc + Vector(P)
        for _ in range(W['per_lock']):
            s0 = rng.uniform(*W['u0'])
            s1 = 1.0 + rng.uniform(*W['ext'])
            th = rng.uniform(0.0, 2.0 * math.pi)
            rho = rng.uniform(*W['rho'])
            c0, t0w, w0, _ = _lock8_local(v, s0)
            dr = rng.uniform(0.0, W['drift'])
            dth = rng.uniform(0.0, 2.0 * math.pi)
            for j in range(K):
                f = j / float(K - 1)
                s = s0 + (s1 - s0) * f
                c, t, w, ph = _lock8_local(v, s)
                tt = max(t, W['hold'] * t0w) * rho
                ww = max(w, W['hold'] * w0) * rho
                ex, ey = tt * math.cos(th), ww * math.sin(th)
                fl = dr * f * f
                x = ex * math.cos(ph) - ey * math.sin(ph) + fl * math.cos(dth)
                y = ex * math.sin(ph) + ey * math.cos(ph) + fl * math.sin(dth)
                pw = base + q @ (Vector((c.x + x, c.y + y, c.z)) * L)
                verts.append((pw.x, pw.y, pw.z))
                cid.append(n)
                rad.append(rt + (rr - rt) * ((1.0 - f) ** 0.7))
            n += 1
    me = bpy.data.meshes.new('pb_wisp_locks')
    me.from_pydata(verts, [], [])
    me.validate()
    a = me.attributes.new('cid', 'INT', 'POINT')
    a.data.foreach_set('value', cid)
    r = me.attributes.new('srad', 'FLOAT', 'POINT')
    r.data.foreach_set('value', rad)
    src = bpy.data.objects.new('pb_wisp_locks', me)
    scene.collection.objects.link(src)
    src.pass_index = PB.IDX['body']
    md = src.modifiers.new('fur', 'NODES')
    md.node_group = _wisp8_curves_gn('pb_wisp8_src_gn')
    cv = bpy.data.hair_curves.new('pb_body_wisps')
    car = bpy.data.objects.new('pb_body_wisps', cv)
    scene.collection.objects.link(car)
    car.pass_index = PB.IDX['body']
    md2 = car.modifiers.new('wisps', 'NODES')
    md2.node_group = _wisp8_carrier_gn('pb_wisp8_gn', src, _hair_material())
    _W8['src'] = src
    _W8['car'] = car
    Ls = [roots[i][2][2] for i in sel]
    print(
        'R8 WISPS run3: %d strands x %d pts on %d of %d locks (%d skipped at the eyes; L %.0f..%.0f mm, reach >= %.3f) in %.1fs'
        % (
            n,
            K,
            len(sel),
            len(roots),
            near_eye,
            1000 * min(Ls),
            1000 * max(Ls),
            reach[len(sel) - 1][0],
            _time8.time() - t0,
        )
    )


print(
    'R8 TUFT run3: wisps %s'
    % ({k: WISP8[k] for k in ('per_lock', 'r_root', 'u0', 'ext', 'hold', 'rho', 'drift', 'eye_clear')},)
)


# ── run4: the fringe stays INSIDE the lock's reach ──────────────────────────────────────────
# run3's fibres are the right dose (soft tips, nothing over the eyes, close-up reads as hair) but
# strands running 5-20 % past the lock tips added 10-20 mm of alpha silhouette all round: the side
# 0.55-width crossing rose from row 340 (base) to 317 — side tail_above +0.9 % -> -15.7 % (gated)
# — and the front silhouette widened 789 -> 814 px. The silhouette belongs to the lock geometry
# (the form/hair rounds tuned it): the strands now splay along the last third of a lock and end
# 0-8 % past its point; the flare stays at 0.08 L.
WISP8.update({'ext': (0.0, 0.08)})
print('R8 TUFT run4: wisps ext %s' % (WISP8['ext'],))


# ── run5: shadow-ray transparency 0.85 -> 0.90 (the far leg under the hem) ─────────────────
# Since run1 the side eye finder reports a 'profile eye' at +64 %: box 150x137 at (328,650),
# 0 % on the eye ids, 23 % on the leg ids (_eyegate.py) — the warm-lit hem locks under the
# belly (H 20, S 125, V 178: the same 3.0-3.2k amber px in the base and every run) closed with
# the far leg's shadowed side (V < 70) into a pupil-bearing blob. The base escapes the 10 % pupil
# test by a few hundred pixels (dark-on-legs 354 vs 477 px); the true profile eye is not found
# in either (ID-gated eye_frac None, base and runs alike). One fur-only lever reaches that leg:
# the hem locks' shadow-ray transparency (5 shingle layers at 0.85 pass 44 % of the bounce, at
# 0.90 59 %). Valleys go half-shadow, which is what the anchor's are.
LOCK7_COL.update({'shadow_tr': 0.90})
print('R8 TUFT run5: lock shadow_tr %.2f' % LOCK7_COL['shadow_tr'])
# run5 REVERTED: the box stayed (150x125 at (328,662), 0 % eye / 26 % leg ids) and the profile went
# whiter (L>=235 43.8 -> 46.8 %, side lab_fur 17 -> 18). The trap is not reachable from the fur
# material; it needs the harness's ID-pass gate. Back to run4's state.
LOCK7_COL.update({'shadow_tr': 0.85})
print('R8 TUFT run5 reverted: shadow_tr %.2f' % LOCK7_COL['shadow_tr'])


# ── run6: WAVY locks (the critic's round-3 shape item) ──────────────────────────────────────
# The anchor's locks are S-curved plush (cell_11: every lock bends once or twice over its length,
# 6-10 mm of sway), ours are near-straight petals with a 2-9 mm (0.03-0.09 L) single sway at
# 0.8-1.3 cycles. Wave 0.07-0.13 L (5-13 mm on 75-100 mm locks) at 1.2-1.8 cycles, curl 0.15-0.35
# (was 0.10-0.30): the 8 variants are rebuilt from the same seed, roots/comb/lengths untouched.
TUFT7.update({'wave': (0.07, 0.13), 'wave_freq': (1.2, 1.8), 'curl_amt': (0.15, 0.35)})
print('R8 TUFT run6: lock wave %s freq %s curl %s' % (TUFT7['wave'], TUFT7['wave_freq'], TUFT7['curl_amt']))
# run6 REVERTED: the wavier variants cross and tangle rather than read as combed S-locks (chest crop),
# the crown gets shaggier, and the side 0.55-width crossing slipped to tail_above -8.5 % (gate 8).
# Back to run2's lock shape. FINAL state = run4: material run1 + tip fibres run3/run4.
TUFT7.update({'wave': (0.03, 0.09), 'wave_freq': (0.8, 1.3), 'curl_amt': (0.10, 0.30)})
print(
    'R8 TUFT run6 reverted: lock wave %s freq %s curl %s -- FINAL = run4 state'
    % (TUFT7['wave'], TUFT7['wave_freq'], TUFT7['curl_amt'])
)


# ═════════════════════════════════════════════════════════════════════════════
# R8EYES (lookdev2 round 4 / r4_eyes) — HOODED TAN LID SHELL instead of the bone goggle bezel
#
# Critic (after round 3, [major]): the ring is a uniform pale-bone goggle bezel (same width top
# and bottom, a perfect circle, sRGB ~(186,162,140) S 0.25). The anchor's lid is a hooded tan
# shell: thick hood on top with a crease, thin ledge at the bottom, a rounded-square opening whose
# outer-lower corner drops, and it casts a shadow onto the top of the iris; lit rim (208,155,84).
#
# MEASURED FIRST
#  * harness eye_frac_mesh splits the ID eye mask at the MEDIAN X — on the front views the median
#    lands inside one eye (base boxes 92 and 185 px wide; close 193 / 373), so its 0.194 / 0.303 are
#    artefacts. Per-eye connected components give 121/789 = 0.153 front (anchor 0.157, base RGB
#    0.155) and 248/1024 = 0.242 close (anchor 0.242). probe.py carries that measure ('id_cc').
#  * the lens is an oblate spheroid of radius er; the skin collar crests at RIM_RHO (0.92) and
#    overtakes the lens surface at rho 0.943 with the run2 lip -0.02. An opening wider than the
#    iris disc (dark sclera at the outer-lower corner, as in cell_11) needs the lens visible past
#    0.95, so the collar lip goes to -0.06 (overtake at 0.985; the collar is under the ring there
#    anyway). The opening's outermost point is kept <= 0.97 er.
#  * cell_11: the iris circle is inscribed in the opening — it touches the sides, the hood's lower
#    edge cuts a chord across its top, the lower ledge clips its bottom on the NASAL side and the
#    opening squares off past the limbus at the outer-lower corner (dark sclera there).
#
# WHAT IS BUILT (eye-LOCAL frame: x lateral, -y forward, z up; temporal = +x for the right eye,
# -x for the left — q is the minimal rotation of -y onto the outward lens axis)
#  * opening = a superellipse r(u) = (|cos u/a|^n + |sin u/b|^n)^(-1/n) with a = 0.92 (sides on the
#    iris rim), b_top 0.80 (hood 0.12 er over the iris — critic), b_bot 0.86 nasal -> 0.92 temporal
#    (the outer-lower corner sits 0.06 er lower than the inner-lower edge — the lens allows 0.06 of
#    the critic's 0.10; more puts the corner off the lens), exponents 2.6 top / 2.2 nasal-bottom /
#    2.35 temporal-bottom (corner reach 0.97 er).
#  * rim width by angle: 0.28 er top, 0.20 sides, 0.13 bottom (critic).
#  * the hood: the inner wall leans INWARD 0.04 er as it rises at the top (a visor, 0 at the
#    bottom) and the top stands 0.06 er further forward than the bottom (critic); wall 0.074 er
#    above the lens at the inner edge + 0.018 crown as before. The eye light and face light sit
#    front upper-left with only receiver collections linked, so the hood shadows the upper iris.
#  * material pb_rim: albedo (0.22,0.060,0.016) lin, rough 0.35, spec 0.5, NO coat. Solved from the
#    R7 probes for this rig (rendered ~= AgX(albedo x E) with E ~(5.2,7,6) and the r7 run3 point
#    (0.24,0.115,0.05) -> (198,178,127)): target rendered (205,150,85) needs scene radiance ~(1.1,
#    0.38,0.09) -> albedo (0.21,0.054,0.015). Coat removed (its white Fresnel was the desaturator).
#  * everything else unchanged: lens, RIM_RHO, iris bands, pupil 0.60, glint, fur, lights.
# ═════════════════════════════════════════════════════════════════════════════
RING8 = {
    'a_side': 0.92,  # er: opening half-width (the iris rim; sides touch)
    'b_top': 0.80,  # er: hood chord 0.12 er inside the iris rim
    'b_bot_nasal': 0.86,
    'b_bot_temporal': 0.92,  # er: the ledge clips the iris bottom nasally; the outer corner drops
    'n_top': 2.6,
    'n_bot_nasal': 2.2,
    'n_bot_temporal': 2.35,  # superellipse exponents
    'w_side': 0.20,
    'w_top': 0.28,
    'w_bot': 0.13,  # er: rim width (critic)
    'proud': 0.074,
    'crown': 0.018,  # er: wall above the lens at the inner edge; crown height
    'fwd': 0.06,
    'fwd_s0': 0.15,
    'fwd_s1': 0.85,  # er: the top's extra forward push (smoothstep in sin u)
    'lean': 0.04,  # er: inward lean of the hood's inner wall (visor), 0 at the bottom
    'bury_in': 0.12,
    'bury_out': 0.25,
    'seg': 120,
    'rgb': (0.22, 0.060, 0.016),
    'rough': 0.35,
    'spec': 0.5,
    'coat': 0.0,
    'coat_rough': 0.25,
    'rho_max': 0.975,  # er: assertion — the opening must stay on the visible lens
}
COLLAR['lip_top'] = -0.06
COLLAR['lip_bot'] = -0.06


def _lerp(a, b, w):
    return a + (b - a) * w


def _ring8_opening(u, tsign):
    """Inner-edge radius (er) and the local rim width (er) at angle u (0 = +x, pi/2 = up).
    tsign: +1 if temporal is +x (right eye), -1 (left eye)."""
    R = RING8
    cu, su = math.cos(u), math.sin(u)
    wt = 0.5 * (1.0 + tsign * cu)  # 0 nasal -> 1 temporal, smooth
    if su >= 0.0:
        b, n = R['b_top'], R['n_top']
        W = _lerp(R['w_side'], R['w_top'], su)
    else:
        b = _lerp(R['b_bot_nasal'], R['b_bot_temporal'], _sstep(wt))
        n = _lerp(R['n_bot_nasal'], R['n_bot_temporal'], _sstep(wt))
        W = _lerp(R['w_side'], R['w_bot'], -su)
    a = R['a_side']
    r = (abs(cu / a) ** n + abs(su / b) ** n) ** (-1.0 / n)
    return r, W


def _rim_material():
    m = bpy.data.materials.get('pb_rim')
    if m is not None:
        return m
    m = bpy.data.materials.new('pb_rim')
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*RING8['rgb'], 1.0)
    b.inputs['Roughness'].default_value = RING8['rough']
    b.inputs['Specular IOR Level'].default_value = RING8['spec']
    b.inputs['Coat Weight'].default_value = RING8['coat']
    b.inputs['Coat Roughness'].default_value = RING8['coat_rough']
    return m


def _socket_ring(name, c, q, er, scene, PB):
    R = RING8
    s1 = R['seg']
    tsign = 1.0 if name.endswith('_r') else -1.0
    rings = []
    stats = {}
    rmax = 0.0
    for i in range(s1):
        u = 2.0 * math.pi * i / s1
        su = math.sin(u)
        cu = math.cos(u)
        rin, W = _ring8_opening(u, tsign)
        rmax = max(rmax, rin)
        top_w = _sstep(su)  # 1 at the top, 0 at/below the sides
        fwd = R['fwd'] * _sstep((su - R['fwd_s0']) / (R['fwd_s1'] - R['fwd_s0']))
        lean = R['lean'] * top_w
        r_base = rin + lean  # where the wall meets the lens
        t_lens = _lens_t(rin)
        t_in = t_lens + R['proud'] + fwd  # inner top corner
        t_top = t_in + R['crown']
        ro = rin + W
        t_out = _collar_t(ro, u) + 0.015  # where the outer fall lands on the collar
        prof = [
            (r_base, _lens_t(r_base) - R['bury_in']),  # buried in the lens
            (rin, t_in),  # (leaning) inner wall -> top corner
            (rin + 0.10 * W, t_in + 0.012),
            (rin + 0.45 * W, t_top),
        ]
        for a_ in (0.25, 0.50, 0.72, 0.88, 1.00):
            ang = a_ * math.pi / 2.0
            prof.append((rin + 0.45 * W + 0.55 * W * math.sin(ang), t_out + (t_top - t_out) * math.cos(ang)))
        prof.append((ro + 0.03, _collar_t(ro + 0.03, u) - R['bury_out']))  # buried in the collar / plate
        rings.append([(er * rho * cu, -er * t, er * rho * su) for (rho, t) in prof])
        if i in (0, s1 // 4, s1 // 2, 3 * s1 // 4):
            stats[i] = (rin, W, t_in - t_lens, t_in)
    if rmax > R['rho_max']:
        raise ValueError(
            'R8EYES %s: opening reaches rho %.3f > %.3f (off the visible lens)' % (name, rmax, R['rho_max'])
        )
    n_r = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces = []
    for i in range(s1):
        i2 = (i + 1) % s1
        b0, b1 = i * n_r, i2 * n_r
        for j in range(n_r - 1):
            faces.append((b0 + j, b0 + j + 1, b1 + j + 1, b1 + j))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_rim_material())
    ob = bpy.data.objects.new(name, me)
    ob.location = c
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = q
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    k = (0, s1 // 4, s1 // 2, 3 * s1 // 4)
    lab = ('+x', 'top', '-x', 'bottom')
    print(
        'R8EYES %s (temporal %s): ' % (name, '+x' if tsign > 0 else '-x')
        + '; '.join(
            '%s: opening %.3f er, width %.1f mm, wall %.1f mm, corner t %.3f'
            % (lab[j], stats[k[j]][0], stats[k[j]][1] * er * 1000, stats[k[j]][2] * er * 1000, stats[k[j]][3])
            for j in range(4)
        )
        + '; opening max rho %.3f' % rmax
    )
    return ob


print(
    'R8EYES: hooded tan lid shell — opening a %.2f / top %.2f / bottom %.2f..%.2f, widths %.2f/%.2f/%.2f er, albedo %s, collar lip %.2f'
    % (
        RING8['a_side'],
        RING8['b_top'],
        RING8['b_bot_nasal'],
        RING8['b_bot_temporal'],
        RING8['w_top'],
        RING8['w_side'],
        RING8['w_bot'],
        RING8['rgb'],
        COLLAR['lip_top'],
    )
)


# ── run2: THIN SHELL — flat crown + steep outer wall, rounded-square OUTER outline, a painted
# crease under the hood ────────────────────────────────────────────────────────────────────
# run1 (probe_run1_close_front / side_left): the tan is in family (mid (195,149,86) H34 S0.56 =
# the critic's lit rim (208,155,84); crown (207,174,128), shade (159,106,51)), the hood chord and
# the recessed porthole in profile read — but the rim is still a FAT ROUNDED TUBE with a round
# outer outline (a quarter-circle outer fall over 0.55 W), so at 45 deg it is still goggles, and
# the hood casts no visible crease onto the iris (the eye light sits only 32 deg above the axis:
# a 7 mm wall shadows ~4 mm of lens, and the coat + iris emission fill it).
#  * profile: wall -> 0.06 W round -> FLAT crown to 0.72 W -> a steep outer wall (0.28 W, 0.16 W
#    round) -> buried. The cup-lip shell of cell_11 (a flat front face with a sharp outer edge).
#  * OUTER outline: its own superellipse (n 3.0) through the critic's widths on the axes (a 1.12,
#    b_top 1.08, b_bot 0.99..1.05) — a rounded square, the width becoming the difference.
#  * crease: the iris shader's hood term (nz smoothstep 0.30..0.85, x0.40) becomes a band under
#    the chord: z 0.50..0.78 (object space = er units on the unit sphere), x0.62 — cell_11's crease
#    is a 20-25 px dark band under the hood at this zoom (~0.2 er).
RING8.update(
    {
        'n_out': 3.0,
        'crown_flat': 0.72,  # x W: the flat crown spans from 0.06 W to here
        'crease_z': (0.50, 0.78),
        'crease_amt': 0.62,
    }
)


def _ring8_opening(u, tsign):
    """Inner-edge radius (er) and the local rim width (er) at angle u; the width is the gap to
    the OUTER superellipse."""
    R = RING8
    cu, su = math.cos(u), math.sin(u)
    wt = 0.5 * (1.0 + tsign * cu)
    if su >= 0.0:
        b, n = R['b_top'], R['n_top']
        bo = R['b_top'] + R['w_top']
    else:
        b = _lerp(R['b_bot_nasal'], R['b_bot_temporal'], _sstep(wt))
        n = _lerp(R['n_bot_nasal'], R['n_bot_temporal'], _sstep(wt))
        bo = b + R['w_bot']
    a = R['a_side']
    ao = a + R['w_side']
    no = R['n_out']
    r = (abs(cu / a) ** n + abs(su / b) ** n) ** (-1.0 / n)
    ro = (abs(cu / ao) ** no + abs(su / bo) ** no) ** (-1.0 / no)
    return r, max(ro - r, 0.06)


def _socket_ring(name, c, q, er, scene, PB):
    R = RING8
    s1 = R['seg']
    tsign = 1.0 if name.endswith('_r') else -1.0
    rings = []
    stats = {}
    rmax = 0.0
    for i in range(s1):
        u = 2.0 * math.pi * i / s1
        su = math.sin(u)
        cu = math.cos(u)
        rin, W = _ring8_opening(u, tsign)
        rmax = max(rmax, rin)
        top_w = _sstep(su)
        fwd = R['fwd'] * _sstep((su - R['fwd_s0']) / (R['fwd_s1'] - R['fwd_s0']))
        lean = R['lean'] * top_w
        r_base = rin + lean
        t_lens = _lens_t(rin)
        t_in = t_lens + R['proud'] + fwd
        t_top = t_in + R['crown']
        ro = rin + W
        t_out = _collar_t(ro, u) + 0.015
        cf = R['crown_flat']
        prof = [
            (r_base, _lens_t(r_base) - R['bury_in']),  # buried in the lens
            (rin, t_in),  # inner wall -> top corner
            (rin + 0.06 * W, t_in + 0.012),
            (rin + 0.18 * W, t_top),  # flat crown ...
            (rin + cf * W, t_top),
        ]
        rr = (1.0 - cf) * W  # outer round radius (the steep wall)
        for a_ in (0.35, 0.65, 0.85, 1.00):
            ang = a_ * math.pi / 2.0
            prof.append((rin + cf * W + rr * math.sin(ang), t_out + (t_top - t_out) * math.cos(ang)))
        prof.append((ro + 0.03, _collar_t(ro + 0.03, u) - R['bury_out']))  # buried in the collar / plate
        rings.append([(er * rho * cu, -er * t, er * rho * su) for (rho, t) in prof])
        if i in (0, s1 // 4, s1 // 2, 3 * s1 // 4):
            stats[i] = (rin, W, t_in - t_lens, t_in)
    if rmax > R['rho_max']:
        raise ValueError(
            'R8EYES %s: opening reaches rho %.3f > %.3f (off the visible lens)' % (name, rmax, R['rho_max'])
        )
    n_r = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces = []
    for i in range(s1):
        i2 = (i + 1) % s1
        b0, b1 = i * n_r, i2 * n_r
        for j in range(n_r - 1):
            faces.append((b0 + j, b0 + j + 1, b1 + j + 1, b1 + j))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_rim_material())
    ob = bpy.data.objects.new(name, me)
    ob.location = c
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = q
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    k = (0, s1 // 4, s1 // 2, 3 * s1 // 4)
    lab = ('+x', 'top', '-x', 'bottom')
    print(
        'R8EYES run2 %s (temporal %s): ' % (name, '+x' if tsign > 0 else '-x')
        + '; '.join(
            '%s: opening %.3f er, width %.1f mm, wall %.1f mm, corner t %.3f'
            % (lab[j], stats[k[j]][0], stats[k[j]][1] * er * 1000, stats[k[j]][2] * er * 1000, stats[k[j]][3])
            for j in range(4)
        )
        + '; opening max rho %.3f' % rmax
    )
    return ob


_eye_shader5_r7 = eye_shader5


def eye_shader5(mat, lp, Rp):
    """R8EYES run2: the R5 shader, then the hood term re-ranged to a crease band under the chord."""
    _eye_shader5_r7(mat, lp, Rp)
    nt = mat.node_tree
    hoods = [
        n
        for n in nt.nodes
        if n.type == 'MAP_RANGE'
        and abs(n.inputs['From Min'].default_value - 0.30) < 1e-6
        and abs(n.inputs['From Max'].default_value - 0.85) < 1e-6
    ]
    for h in hoods:
        h.inputs['From Min'].default_value = RING8['crease_z'][0]
        h.inputs['From Max'].default_value = RING8['crease_z'][1]
        # the multiply that scales the hood result (x0.40) feeds a SUBTRACT; find it via the link
        for lk in nt.links:
            if lk.from_node == h and lk.to_node.type == 'MATH' and lk.to_node.operation == 'MULTIPLY':
                lk.to_node.inputs[1].default_value = RING8['crease_amt']
    print(
        'R8EYES run2: iris crease band z %.2f..%.2f x%.2f (%d hood nodes re-ranged)'
        % (RING8['crease_z'][0], RING8['crease_z'][1], RING8['crease_amt'], len(hoods))
    )


print(
    'R8EYES run2: thin shell (flat crown to %.2f W, outer superellipse n %.1f), crease %s x%.2f'
    % (RING8['crown_flat'], RING8['n_out'], RING8['crease_z'], RING8['crease_amt'])
)

# run2 colour: anchor rim strips (cell_11 x780 hood: crown (251,236,203) -> lit wall (216,149,69); anchor_full hood
# (242,190,85), nasal wall (241,178,75), ledge (229,161,46)) are brighter and more golden than run1's mid (195,149,86)
# / crown (207,174,128): albedo x1.36 with B cut (rendered R/B 2.27 vs the anchor's 2.85).
RING8['rgb'] = (0.30, 0.082, 0.015)
print('R8EYES run2: rim albedo %s' % (RING8['rgb'],))


# ── run3: ROUNDED crown that blends into the plate; outer outline n 2.5; brighter gold ─────
# run2 (probe_run2_*): the shell reads — hood overhang in profile, rounded-square opening, crease on
# the upper iris, no more goggle at 45 deg — but the flat crown + sharp outer edge is a picture
# frame and n_out 3.0 a TV screen at 45 deg; cell_11's lip is a rounded band with the highlight
# along its middle and an outer edge that fades into the plate (only the INNER edge is sharp).
# Colour: run2 brightest quartile (208,161,92) L69 / mid (181,127,50) vs the anchor's lit walls
# (242,190,85) L80 and cream crown (250,235,200): still a step dark -> albedo x1.35 (AgX will
# pull the brightest crown toward the anchor's cream).
RING8.update({'n_out': 2.5, 'rgb': (0.40, 0.110, 0.020), 'crown_peak': (0.10, 0.35)})


def _ring8_profile(rin, W, t_in, t_top, t_out, r_base, u):
    """Radial (rho, t) profile: buried in the lens -> sharp inner wall -> rounded crown (flat between
    crown_peak) -> smoothstep fall that lands tangent on the collar -> buried in the collar."""
    R = RING8
    p0, p1 = R['crown_peak']
    prof = [(r_base, _lens_t(r_base) - R['bury_in']), (rin, t_in), (rin + p0 * W, t_top), (rin + p1 * W, t_top)]
    for a_ in (0.15, 0.35, 0.55, 0.75, 0.90, 1.00):
        rho = rin + (p1 + (1.0 - p1) * a_) * W
        prof.append((rho, t_out + (t_top - t_out) * (1.0 - _sstep(a_))))
    ro = rin + W
    prof.append((ro + 0.03, _collar_t(ro + 0.03, u) - R['bury_out']))
    return prof


def _socket_ring(name, c, q, er, scene, PB):
    R = RING8
    s1 = R['seg']
    tsign = 1.0 if name.endswith('_r') else -1.0
    rings = []
    stats = {}
    rmax = 0.0
    for i in range(s1):
        u = 2.0 * math.pi * i / s1
        su = math.sin(u)
        cu = math.cos(u)
        rin, W = _ring8_opening(u, tsign)
        rmax = max(rmax, rin)
        fwd = R['fwd'] * _sstep((su - R['fwd_s0']) / (R['fwd_s1'] - R['fwd_s0']))
        r_base = rin + R['lean'] * _sstep(su)
        t_lens = _lens_t(rin)
        t_in = t_lens + R['proud'] + fwd
        t_top = t_in + R['crown']
        t_out = _collar_t(rin + W, u) + 0.015
        prof = _ring8_profile(rin, W, t_in, t_top, t_out, r_base, u)
        rings.append([(er * rho * cu, -er * t, er * rho * su) for (rho, t) in prof])
        if i in (0, s1 // 4, s1 // 2, 3 * s1 // 4):
            stats[i] = (rin, W, t_in - t_lens, t_in)
    if rmax > R['rho_max']:
        raise ValueError(
            'R8EYES %s: opening reaches rho %.3f > %.3f (off the visible lens)' % (name, rmax, R['rho_max'])
        )
    n_r = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces = []
    for i in range(s1):
        i2 = (i + 1) % s1
        b0, b1 = i * n_r, i2 * n_r
        for j in range(n_r - 1):
            faces.append((b0 + j, b0 + j + 1, b1 + j + 1, b1 + j))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(_rim_material())
    ob = bpy.data.objects.new(name, me)
    ob.location = c
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = q
    ob.pass_index = PB.IDX['face']
    scene.collection.objects.link(ob)
    k = (0, s1 // 4, s1 // 2, 3 * s1 // 4)
    lab = ('+x', 'top', '-x', 'bottom')
    print(
        'R8EYES run3 %s (temporal %s): ' % (name, '+x' if tsign > 0 else '-x')
        + '; '.join(
            '%s: opening %.3f er, width %.1f mm, wall %.1f mm, corner t %.3f'
            % (lab[j], stats[k[j]][0], stats[k[j]][1] * er * 1000, stats[k[j]][2] * er * 1000, stats[k[j]][3])
            for j in range(4)
        )
        + '; opening max rho %.3f' % rmax
    )
    return ob


print(
    'R8EYES run3: rounded crown (peak %s W), outer n %.1f, albedo %s'
    % (RING8['crown_peak'], RING8['n_out'], RING8['rgb'])
)


# ── run4: rim +12 % and a tighter, darker crease ───────────────────────────────────────────
# run3 strips (strips.py, close_front right eye): nasal wall (215,175,89) S0.58, hood crown
# (228,222,199), ledge (226,197,143) vs the anchors' walls (211,163,96)..(242,190,85), hood crown
# (251,236,203), ledge (228,215,193) — one small step short of anchor_full's golden wall.
# The crease under the hood reads but is fainter and wider than cell_11's 20-25 px band (~0.22 er
# at that zoom): band 0.50..0.78 x0.62 -> 0.56..0.80 x0.72.
RING8.update({'rgb': (0.45, 0.123, 0.022), 'crease_z': (0.56, 0.80), 'crease_amt': 0.72})
print('R8EYES run4: rim albedo %s, crease %s x%.2f' % (RING8['rgb'], RING8['crease_z'], RING8['crease_amt']))


# ═════════════════════════════════════════════════════════════════════════════
# R8 LIGHT (lookdev2 / r4_light) — lights, backdrop, floor, lens. Critic (phase-2 round 3, [major]):
#   the lighting is flat and the profile over-lit: side near-white 45 % of fur px vs anchor 7 %
#   (the tuft round's gate: 51 vs 22); no warm-belly / cool-crown gradient on any view. Anchor:
#   mint-white upper-left crown -> gold-cream lower-right chest (front), cream with a warm
#   underside (side). Ours: one white everywhere with a faint warm patch at lower right.
# Measured first (probe4.py, SAME body-box zones on anchor and render, medians sRGB / 8-bit Lab):
#   front  crownUL  anchor (147,209,206) H178 S0.30 L204   base (218,239,233) L237   <- cyan SHADOW, ours lit
#          crown    anchor (218,245,225) L240 0 % >=250    base (232,242,236) L242   ok level, 32 % >=235 vs 8.6
#          crownUR  anchor (241,248,208) cream L246        base (246,247,239) L248   ok
#          chestLR  anchor (230,166, 83) H34 S0.64 L185    base (239,236,218) S0.09 L238   <- GOLD, ours white
#          midbelly anchor (111, 83, 43) L 96               base (208,200,170) L205   ~2.5 stops over
#          flankR   anchor (201,127, 59) orange L152       base (226,216,180) L220
#          flankL   anchor ( 50, 47, 30) black  L 49       base (114,147,130) L150
#   side   near-white 21.9 % / mid-tones 39 %             base 50.7 % / 23 %
#          flank    anchor (131,146,117) H92 S0.20 L149    base (240,240,224) L241   <- the +x flank is FLOODED
#          top_rear anchor (143,202,202) cyan L198         base (239,243,235) L243
#          front_lo anchor (207,151, 78) gold L170         base (244,241,225) L242
# Why: the R7 coat is a diffuse+SSS shell (tip albedo (0.80,0.90,0.82)) where the rig was tuned on a
# forward-scattering hair coat, so every fur light now lands ~1 stop hotter, and the key pair sits at
# az 60 / el 48 — it lights the +x flank the side camera faces at cos ~0.9 with a 3800 K fur key.
# The anchor's warm light is LOW and to the right (flankR/chestLR gold, midbelly caramel, flankL
# black, side front_lo gold), its crown light is a mint top light, and its left is a dim cyan fill.
# Geometry and the creature's materials are untouched (the coat's albedo is the tuft round's lever).
# Everything below overrides the R6 LIGHT names above (LIGHTS is read at lighting() time).
# ═════════════════════════════════════════════════════════════════════════════

# ── run1: the fur-only key on the flank, -45 % ────────────────────────────────────────────
# The critic's first lever alone, so its effect is separable: 'furkey' (3800 K, az 60 / el 48,
# fur-only, 18 W) -> 10 W. The general 'key' (6 W mint-white on face / arms / feet) is untouched.
LIGHTS['furkey'].update(W=10.0)
print('R8LIGHT run1: furkey 18 -> 10 W')


# ── run2: the anchor's rig — WARM LOW KEY from camera-right, cool mint fill halved ─────────
# run1 (furkey -45 %): side flank L241 -> L236, near-white 50.7 -> 44.9 %, front chestLR L238 ->
# L232 — the fur key is not what floods the profile; key + top + the warm side pair + bounce all
# land on the +x flank and add up, and it tripped the side eye finder (+61.8 %, the belly). So the
# critic's whole structure at once, then tune:
#  * LOW WARM KEY: a pair at az 55 / el -25 / 1.3 S, disk 0.45 S, aimed 'low' (front-centre,
#    below the equator). az 55 lights BOTH anchors' warm zones: front flankR/chestLR at cos ~0.9-1.0
#    (the anchor's gold), the side view's front_lo (chest, cos ~0.85) and its +x flank at cos 0.74;
#    the crown (cos < 0) and the left flank get nothing. General 'lowkey' 6 W = the critic's
#    (255,205,150) -> lin (1.0,0.61,0.31), creature-linked (never the floor: the anchor floor in
#    front of the feet is dark); fur-only 'lowkeyfur' 14 W at WARM (1.0,0.40,0.12): R3's Filmic
#    sweep — a pale light cannot reach the anchor's chestLR (230,166,83) S 0.64 (R/G 2.1 lin);
#    WARM x tip albedo gives R/G 2.2. The old warm side pair (az 75 / el -5) is removed.
#  * COOL MINT FILL at 0.5 x: coolfur 12 -> 8 W / coolfill 1.5 -> 1.0 W, the critic's (170,255,225)
#    -> lin (0.40,1.0,0.75); moved from the top (az -35 / el 75) to the upper-LEFT (az -45 / el 60)
#    so the crown reads mint from the left and the crown-right stays the fur key's cream.
#  * 'furkey' stays at run1's 10 W (crown-right cream, side upper flank).
LOWKEY_GEN = (1.00, 0.61, 0.31)  # critic's warm key, sRGB (255,205,150)
MINT8 = (0.40, 1.00, 0.75)  # critic's mint fill, sRGB (170,255,225)
_LOW_POS = _sph(55, -25, 1.3)
LIGHTS.pop('warm', None)
LIGHTS.pop('warmfur', None)
LINKED = tuple(n for n in LINKED if n != 'warm') + ('lowkey',)
FUR_ONLY = tuple(n for n in FUR_ONLY if n != 'warmfur') + ('lowkeyfur',)
LIGHTS['lowkey'] = dict(pos=_LOW_POS, W=6.0, size=0.45, rgb=LOWKEY_GEN, aim='low')
LIGHTS['lowkeyfur'] = dict(pos=_LOW_POS, W=14.0, size=0.45, rgb=WARM, aim='low')
_COOL8 = _sph(-45, 60)
LIGHTS['coolfill'].update(pos=_COOL8, W=1.0, rgb=MINT8)
LIGHTS['coolfur'].update(pos=_COOL8, W=8.0, rgb=MINT8)
print(
    'R8LIGHT run2: lowkey 6 + 14 W at %s; cool 1 + 8 W %s at %s; warm pair removed'
    % (tuple(round(v, 3) for v in _LOW_POS), MINT8, tuple(round(v, 3) for v in _COOL8))
)


# ── run3: the low key was UNDER THE FLOOR; cool light back on top; neutral light off the belly ──
# run2 measured: front chestLR (232,230,210) = run1's, side front_lo 238 -> 236 — the low key landed
# nowhere. _diag_lights.py: the harness's body centre is z 0.188 and the floor is at z ~0, so a lamp
# at el -25 / 1.3 S sits at z -0.047 with its 0.45 S disk spanning -0.135..0.041: the ground plane
# blocks it. And the cool fill at az -45 / el 60 lit the whole LEFT side cyan-white (flankL L150 ->
# 172, crownUL unchanged at L237): the anchor's crown is lit from the TOP and falls off to a dim cyan
# on the left, so that move is reverted (top position az -35 / el 75, run2's 1 + 8 W and colour kept).
#  * low key pair: az 55 / el -15 / 1.1 S, disk 0.35 S (centre z ~0.06, the disk just clears the
#    floor) AND the ground is taken out of the pair's shadow blockers, so nothing of the disk is lost;
#    the pair stays creature-linked (the floor never receives it). 4 + 10 W.
#  * the neutral light on the lower body steps down first (R6's lesson: under Filmic an amber added
#    onto a near-white belly only whitens it): key 6 -> 4 W, furkey 10 -> 7 W, bouncefur 1.2 -> 0.6 W.
_LOW_POS = _sph(55, -15, 1.1)
LIGHTS['lowkey'].update(pos=_LOW_POS, W=4.0, size=0.35)
LIGHTS['lowkeyfur'].update(pos=_LOW_POS, W=10.0, size=0.35)
_TOP8 = _sph(-35, 75)
LIGHTS['coolfill'].update(pos=_TOP8)
LIGHTS['coolfur'].update(pos=_TOP8)
LIGHTS['key'].update(W=4.0)
LIGHTS['furkey'].update(W=7.0)
LIGHTS['bouncefur'].update(W=0.6)
NO_FLOOR_SHADOW = ('lowkey', 'lowkeyfur')  # lights the ground plane must not shadow

_lighting_r6 = lighting


def lighting(scene, centre, size, aim):
    _lighting_r6(scene, centre, size, aim)
    coll = bpy.data.collections.get('pb_blockers_nofloor')
    if coll is None:
        coll = bpy.data.collections.new('pb_blockers_nofloor')
        for ob in scene.collection.objects:
            if ob.type == 'MESH' and ob.name != 'pb_ground':
                coll.objects.link(ob)
    for name in NO_FLOOR_SHADOW:
        o = bpy.data.objects.get(name)
        if o is not None:
            o.light_linking.blocker_collection = coll
            print('R8LIGHT %s: floor excluded from shadow blockers (%d blockers)' % (name, len(coll.objects)))


print(
    'R8LIGHT run3: low key 4 + 10 W at %s size 0.35 (no floor shadow); cool back on top %s; key 4 / furkey 7 / bouncefur 0.6 W'
    % (tuple(round(v, 3) for v in _LOW_POS), tuple(round(v, 3) for v in _TOP8))
)


# ── run4: the belly's light budget — the amber ALONE below the equator, 1.5 stops down ─────────
# run3 (low key landing at 4 + 10 W): front chestLR (245,239,218) L241, midbelly L231, flankR L241,
# side front_lo L247, q45 near-white 76 % — WHITER than run2 everywhere the low key reaches. R6's
# lesson holds on this coat with a vengeance: the lock shell (tip albedo (0.80,0.90,0.82), SSS 0.6,
# 85 % shadow transparency) is already near the Filmic shoulder under the neutral lights alone
# (run2, no working low key: chestLR L232, midbelly L216), so an amber on top can only push it to
# white. The anchor's gold chestLR (230,166,83) and caramel midbelly (111,83,43) are an amber at a
# LOW level with nothing neutral under it. So, one lever — the light budget below the crown:
#  * neutral/warm-white on the body: key 4 -> 2.5 W, furkey 7 -> 4 W (they keep the crown-right
#    cream and the side's upper flank); bouncefur (1.0 S disk, front-low, was the belly's own
#    neutral flood) removed.
#  * the amber pair: lowkey 4 -> 2 W, lowkeyfur 10 -> 4 W (-1.3 stops: run3's L241 with everything
#    else on top must land near the anchor's L152-185 with the amber alone), and a deeper orange
#    (1.0,0.28,0.06): Filmic MHC maps the anchor's (201,127,59) to scene ~(0.9,0.18,0.035), R/G 5,
#    which through the (0.8,0.9,0.82) tip needs a light of R/G ~5.6 — WARM's 2.5 renders as cream.
#  * the left side (anchor flankL black (50,47,30), chestLL (79,89,78); ours L173 / L202): fillL
#    3 -> 1.5 W, rimL 6 -> 4 W.
LIGHTS['key'].update(W=2.5)
LIGHTS['furkey'].update(W=4.0)
LIGHTS.pop('bouncefur', None)
FUR_ONLY = tuple(n for n in FUR_ONLY if n != 'bouncefur')
AMBER8 = (1.00, 0.28, 0.06)
LIGHTS['lowkey'].update(W=2.0)
LIGHTS['lowkeyfur'].update(W=4.0, rgb=AMBER8)
LIGHTS['fillL'].update(W=1.5)
LIGHTS['rimL'].update(W=4.0)
print('R8LIGHT run4: key 2.5 / furkey 4; bouncefur removed; low key 2 + 4 W %s; fillL 1.5; rimL 4' % (AMBER8,))


# ── run5: the amber pair -1.7 stops; the crown's top light +0.3 stop ────────────────────────
# run4: side near-white 20.7 % (anchor 21.9 %) — the profile gate is met; front chestLR (231,221,190)
# L225 S0.18, midbelly L202, flankR L222, flankL L126, side flank L226 / front_lo L234. Still ~1.5
# stops over below the equator and still pale: the 6 W amber pair is the belly's dominant light
# (~5:1 over the key pair's cos-0.3 spill) and Filmic's shoulder both flattens and desaturates it —
# run3 -> run4 (-1.2 stops on the pair) moved chestLR only 241 -> 225. The anchor's belly is DARK
# (midbelly L96, flankR L152, chestLR L185 the brightest): lowkeyfur 4 -> 1.2 W, lowkey 2 -> 0.6 W.
# Crown (disjoint zone, no amber reaches it): front L233 vs anchor 240, 0.1 % >= 235 vs 8.6 %, side
# L236 vs 234: coolfur 8 -> 10 W (the top light only).
LIGHTS['lowkey'].update(W=0.6)
LIGHTS['lowkeyfur'].update(W=1.2)
LIGHTS['coolfur'].update(W=10.0)
print('R8LIGHT run5: low key 0.6 + 1.2 W; coolfur 10 W')


# ── run6: the key goes FRONTAL (az 30 / el 55); the top light close-in; amber -1 stop ──────────
# run5: front chest L151 (anchor 146), near-white 20 % (45 %), flankL L110 (49); side near-white
# 14.5 % (21.9 %), crown L235 (234). Left: side flank (208,212,189) L214 vs anchor (131,146,117) L149
# — ~2.7 stops through Filmic MHC — and the belly zones 1.3-2.8 stops over (chestLR L210/185,
# midbelly L171/96, flankR L197/152); crownUR lost its cream (H114 vs anchor H70) when furkey fell.
# Read off anchor_side: its ball is lit from the FRONT-top (face side): front cream, flank centre
# mid-tone, rear teal, bottom dark. Our key pair sits at az 60, i.e. pointed at the side camera —
# the camera-facing flank is front-lit (cos 0.58) and flat. So:
#  * key pair -> az 30 / el 55 / 1.5 S: +x flank cos 0.58 -> 0.29 (-1 stop), front chestLR spill
#    cos 0.30 -> ~0 (the amber owns the belly), crown-right cos 0.96 (cream back): key 2.5 -> 3 W,
#    furkey 4 -> 6 W.
#  * the crown's top light moves in from 1.5 S to 0.9 S (0.385 m; the crown top is 0.2 m above the
#    centre): the crown sits at 0.19 m from it, the equator flank at 0.44 m — 2.5 stops of
#    inverse-square falloff crown -> flank where 1.5 S gave 1.2. Power for the same crown
#    irradiance: (0.19/0.44)^2 x 10 W -> coolfur 2.5 W, coolfill 0.3 W.
#  * amber pair -1 stop: lowkey 0.3 W, lowkeyfur 0.6 W.
_KEY8 = _sph(30, 55, 1.5)
LIGHTS['key'].update(pos=_KEY8, W=3.0)
LIGHTS['furkey'].update(pos=_KEY8, W=6.0)
_TOP8 = _sph(-35, 75, 0.9)
LIGHTS['coolfill'].update(pos=_TOP8, W=0.3)
LIGHTS['coolfur'].update(pos=_TOP8, W=2.5)
LIGHTS['lowkey'].update(W=0.3)
LIGHTS['lowkeyfur'].update(W=0.6)
print(
    'R8LIGHT run6: key pair %s 3 + 6 W; top %s 0.3 + 2.5 W; low key 0.3 + 0.6 W'
    % (tuple(round(v, 3) for v in _KEY8), tuple(round(v, 3) for v in _TOP8))
)


# ── run7: the key leaves the belly (el 70); top light closer; deeper amber; rimR; eyelight ─────
# run6: side flank L214 -> 201, near-white 14.5 -> 6.0 % (anchor 21.9), crown front L237 (240);
# chest L138 (146). But chestLR (214,211,186) L215 and side front_lo L211 did not move when the
# amber pair went to 0.9 W: the belly's light is NOT the amber. chestLR sits just under the
# equator (normal ~(0.6,-0.75,-0.25)) and the key pair at az 30 / el 55 still reaches it at
# cos 0.35 — 2.1 W/m^2 of 3800 K cream over 1.0 W/m^2 of amber (S 0.13). The eyes lost the
# general key too (lab_eye 4 -> 23 / 26; iris L 152 -> 141). One lever per zone:
#  * key pair el 55 -> 70 (same az 30, 1.5 S): chestLR cos 0.35 -> 0.09, crown-right cos 0.93;
#    furkey 6 -> 8 W so the upper-right flank / crownUR gets its cream back (anchor (241,248,208)
#    L246, ours L234 H90 = mint-grey).
#  * amber pair: the belly must now be amber-only, so it may be brighter and it must be deeper —
#    Filmic MHC is per-channel and the anchor flankR (201,127,59) is a scene R/G of ~8; AMBER8 x
#    tip albedo gave 3.2 and read (192,172,127). (1.0,0.18,0.03) -> R/G ~5; 0.5 + 1.0 W.
#  * the crown's top light 0.9 -> 0.75 S (0.13 m over the crown; equator flank 0.385 m: 3.3 stops
#    of falloff instead of 2.5), disk 0.35 -> 0.25 S; coolfur 2.5 -> 1.2 W (side crown L227 vs
#    anchor 234 was a shade under), coolfill 0.3 -> 0.15.
#  * side rear (164,195,191) L196 vs anchor teal (71,119,125) L120: rimR 1.5 -> 0.6 W.
#  * eyelight (eye-only, white) 5 -> 9 W for the irises.
_KEY8 = _sph(30, 70, 1.5)
LIGHTS['key'].update(pos=_KEY8)
LIGHTS['furkey'].update(pos=_KEY8, W=8.0)
AMBER8 = (1.00, 0.18, 0.03)
LIGHTS['lowkey'].update(W=0.5)
LIGHTS['lowkeyfur'].update(W=1.0, rgb=AMBER8)
_TOP8 = _sph(-35, 75, 0.75)
LIGHTS['coolfill'].update(pos=_TOP8, W=0.15, size=0.25)
LIGHTS['coolfur'].update(pos=_TOP8, W=1.2, size=0.25)
LIGHTS['rimR'].update(W=0.6)
LIGHTS['eyelight'].update(W=9.0)
print(
    'R8LIGHT run7: key pair %s 3 + 8 W; amber %s 0.5 + 1.0 W; top %s 0.15 + 1.2 W size 0.25; rimR 0.6; eyelight 9'
    % (tuple(round(v, 3) for v in _KEY8), AMBER8, tuple(round(v, 3) for v in _TOP8))
)


# ── run8 (FINAL): the upper body's whites back up — only the lights that cannot reach the belly ──
# run7: front chest L146 (anchor 146), chestLR (200,182,146) L190 S0.27 (anchor L185 S0.64),
# flankR L175 S0.44 (152 / 0.71), midbelly L149 (96), flankL L112 (49); side flank L189 (149),
# lowbelly L133 (77), rear L178 (120), near-white 7.2 % (21.9); lab_eye 23 -> 13. The grade is in.
# The cost: with nothing neutral below the equator the UPPER body reads a shade dull — front
# near-white 17.7 % vs the anchor's 45 %, crownUR (224,228,212) L230 vs (241,248,208) L246, side crown
# L228 vs 234. Both lights that own the upper body sit where their spill under the equator is
# ~cos 0.1: furkey 8 -> 12 W (az 30 / el 70, 3800 K: the crown-right / upper-right flank cream),
# coolfur 1.2 -> 1.6 W (the 0.75 S top light, mint: crown apex). Nothing else moves.
LIGHTS['furkey'].update(W=12.0)
LIGHTS['coolfur'].update(W=1.6)
print('R8LIGHT run8: furkey 12 W, coolfur 1.6 W')


# ═════════════════════════════════════════════════════════════════════════════
# R8 MERGE (lookdev2 round 4 / r4_merge) — composition of tuft + eyes + light on r3_merge.
#
# FUR JUDGE: fur_tuft over fur_hair. Looked at front_full / side_left / q45 / close_front of both
# next to anchor_full / anchor_side / cell_11 (cmp_fur.png in this directory): the tuft round's
# lock material (mint root -> cream tip at u 0.85, SSS 0.35 mint radius, the last quarter of every
# lock dissolving to alpha 0) plus its fine tip-strand fringe give plush, TAPERED locks whose points
# fade instead of ending in a hard white spike, in every view; the hair round's fibre layer keeps the
# opaque petal bodies and in profile its outer fibres stand off the ball as bristles (a bottle-brush
# again at 45 and 90 deg), which is exactly what the judge's rule rejects. The hair round's close-up
# chest grain is the one thing it does better; the tuft's bump grain (18 streaks, 0.9) carries a
# fainter version of it. Not merged: everything in r4_fur_hair/fur_hair.py (its render_pre handler,
# its _link_prefix wrappers, its Curves carrier, FIB8).
#
# CONFLICTS and how they are settled
#  1. lighting() is wrapped three times — call order at render time: R8 MERGE -> R8 LIGHT (nofloor
#     shadow blockers for the amber pair) -> R8 TUFT (links the CURVES fringe carrier pb_body_wisps
#     into every receiver collection pb_body_locks is in) -> R5/R2 (lights, collections). The tuft
#     wrapper scans collections AFTER the base built them, so the fringe also receives the light
#     round's new 'lowkey' / 'lowkeyfur' lights (they use the same pb_light_receivers /
#     pb_fur_receivers collections). Verified by the 'R8 WISPS: pb_body_wisps linked into [...]'
#     line in the Blender log.
#  2. The light round's 'pb_blockers_nofloor' collection is built from MESH objects only, so the
#     fringe carrier (a CURVES object) would cast no shadow for the two amber lights while the locks
#     do. The wrapper below adds pb_body_wisps to that collection (parity with the lock coat).
#  3. LOCK7_COL['tip']: the tuft round raises it to (0.87,0.94,0.88) and the light round tuned its
#     rig on the base's (0.80,0.90,0.82); the tuft value stands (+0.1 stop on the coat, the light
#     round's own caveat says the upper body was UNDER the anchor's whites). Checked visually in run1.
#  4. The eyes round's rim albedo (0.45,0.123,0.022) was solved under the base rig (general key
#     6 W az 60/el 48); the light round's key is 3 W at az 30/el 70. The ring receives key /
#     creature / rim lights only (it is not in FACE_PARTS nor the eye receivers), so it renders a
#     step darker here than in the eyes round. Judged by eye in run1 against anchor_full's lid.
#  5. eyelight 5 -> 9 W (light) and the eyes round's painted crease (iris hood MapRange) — no
#     conflict: eyelight links only pb_eye / pb_pupil / pb_glint and the crease is albedo.
#  6. COLLAR lip -0.06 (eyes) vs nothing in tuft/light: no conflict.
# ═════════════════════════════════════════════════════════════════════════════
_lighting_r8_light = lighting


def lighting(scene, centre, size, aim):
    _lighting_r8_light(scene, centre, size, aim)
    coll = bpy.data.collections.get('pb_blockers_nofloor')
    car = _W8.get('car')
    if coll is not None and car is not None and car.name not in coll.objects:
        coll.objects.link(car)
        print('R8 MERGE: %s added to pb_blockers_nofloor (%d blockers)' % (car.name, len(coll.objects)))


print('R8 MERGE run1: tuft (material + tip fringe) + eyes (hooded tan lid) + light (R8 rig) assembled')


# ── R8 MERGE run2: the upper body's whites back up for the TUFT coat ─────────────────────────
# run1 (tuft + eyes + light as delivered; probe4 zones): the belly grade is in — front chestLR
# (202,184,152) L193 vs anchor L185, midbelly L123 (96), flankR L167 (152), side front_lo L203 (170),
# lowbelly L131 (77) — but the upper body sits under the anchor's whites: front near-white 19.8 %
# (anchor 45 %; light round alone 23.6 %), crown L236 with 13 % >= 235 (anchor 240), crownUR L228
# (246); side crown L225 (234) with 0 % >= 235, side near-white 6.3 % (21.9 %), side L_med 206 (220).
# Cause: the light round tuned its rig on the base coat (SSS 0.6, opaque tips); the tuft coat's
# SSS 0.35 + the last quarter of every lock dissolving to alpha 0 reflects ~0.3-0.4 stop less. The
# light round's own run8 lever, one step further: only the two lights whose spill under the equator
# is ~cos 0.1 — furkey 12 -> 16 W (az 30 / el 70, 3800 K: crown-right / upper-right flank cream) and
# coolfur 1.6 -> 2.2 W (the 0.75 S top light, mint: crown apex). The amber pair, key, fills, rims,
# face and eye lights are untouched, so the belly and the face do not move.
LIGHTS['furkey'].update(W=16.0)
LIGHTS['coolfur'].update(W=2.2)
print('R8 MERGE run2: furkey 16 W, coolfur 2.2 W (upper-body whites for the tuft coat)')


# ── R8 MERGE run3: the profile cheek — faceR 3 -> 6 W ────────────────────────────────────────
# run2 kept (front near-white 19.8 -> 23.9 %, crown 13 -> 21 % >= 235, crownUR L228 -> 232, side
# crown L225 -> 229; belly zones within 4 L of run1). The light round's own recorded regression
# stands in the merge: the profile cheek is darker than the base (side lab_face measured WITHOUT the
# bogus belly ROI: 31.9 vs the base's 17.3) because the general key left az 60 for az 30 / el 70 and
# fell 6 -> 3 W, so the +x cheek the side camera faces lives on 'faceR' (3 W, face-only, upper
# right). The light round's unrendered recommendation: faceR 3 -> 6 W. FACE_PARTS = plate, orbits,
# lids, lips, teeth, tongue — no fur receiver and not the lid ring (pb_rim_*), so the coat and the
# ring do not move.
LIGHTS['faceR'].update(W=6.0)
print('R8 MERGE run3: faceR 6 W (profile cheek)')


# ── R8 MERGE FINAL = run3 (comments only below this line; the render is run3's) ──────────────
# run3 kept: the plate patch beside the profile eye went base L204 -> run2 L184 -> run3 L202 and the
# brow 240 -> 230 -> 239 (the visible cheek is back at the base's level); front lab_face 9 -> 6 with
# the front face median L154 vs the anchor's 152, so faceR cannot go further without lifting the
# front face past the anchor. The harness's side lab_face (47) is measured inside a face ROI built
# around the belly blob (see below); recomputed with no ROI (the base's own condition) it is 31.7
# vs the base's 17.3 — what is left dark is the LOWER plate under the beard, which no face-only
# light reaches without also lighting the front face; left for the light/skin dimension.
#
# Fourth run not spent: no remaining one-knob change had a clearer payoff than its risk (front
# near-white 23 % vs 45 % needs ~1.5 stops the crown cannot take; side flank L195 vs 149 is the
# flat-lit profile the light round already diagnosed as geometry; eyelight +3 W would move front
# lab_eye 12 -> ~8 but the irises read right by eye).
#
# HARNESS CAVEATS for the gated numbers on this file (all present in the delivered dimension runs):
#  * front eye_frac +8.0 % (gate 4 %): the RGB finder merges the TAN lid ring (H 42 deg, S 0.58 —
#    inside the amber gate, as the anchor's own lit rim is) into the iris blob on BOTH eyes, where the
#    anchor's 0.157 includes its rim on one eye only. Per-eye ID components (_idcc.py, the eyes
#    round's rule): front 0.148 vs anchor 0.157 = -5.5 % — the opening is slightly SMALLER than the
#    anchor's, not larger. Passing the RGB gate would need a bone/desaturated ring, which is the
#    look the critic rejected. Not done.
#  * side eye_frac +57 % (gated): the warm-lit hem locks under the belly closed with the far leg's
#    shadow into a pupil-bearing blob (the tuft/light rounds' _eyegate finding; 0 % of it is on the
#    eye ids). The base escapes it by ~120 dark pixels. Not reachable from the overlay; needs the
#    ID-pass / head-confined finder in pbfit (patch supplied by the light round, not applied — the
#    harness is outside every agent's write scope).
#  * side lab_face 47 and close_front lab_fur 19 are consequences of the same wrong ROI / of the
#    warm chest pixels leaving the S<70 fur gate (the light round's caveat 4).
#  * close_front eye_frac -75 %: the finder rejects the rim+iris blob (the eyes round's caveat 2).
#  * side aspect -5.1 %: the base's own lone tail-strand column (715 px), untouched here.


# ── visibility-check exemptions (port, 2026-08-27) ─────────────────────────────────
# pufferball_sheet's assert_parts_visible counts IndexOB pixels per part. The R8 eyes
# rebuilt pb_glint_* as a flat 41 mm reflection card at the EYE CENTRE, inside the
# corneal shell: it is visible in beauty through the glass and invisible to the
# first-hit index pass by construction (measured: dims 41x2.5x23 mm at 0.0000 m from
# the eye centre, eye radius 53 mm). Exempt, with the reason — not a loosened check.
VISIBLE_EXEMPT = {'glint': 'reflection card inside the corneal shell; seen only by refraction'}


# ═════════════════════════════════════════════════════════════════════════════
# R9 MERGE (lookdev3 round 1 / r1_merge) — base + R9 FACE (r1_face/run6) + R9 COAT (r1_coat/r9)
# in that order, each appended verbatim. Name overlap between the two sections (checked by
# script): none assigned/defined twice; both .update() PARAMS (face: pupil_r; coat: tail_hair_*)
# and LIGHTS (face: eyelight W; coat: furkey — set and then reverted to the production
# K3800 / 16 W in its own final run) with DISJOINT keys, so the order does not matter.
# COAT's pre_build / post_build / lighting wrappers capture the base's functions (FACE
# defines none), so both apply.
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# R9 FACE (lookdev3 round 1 / r1_face) — the face as ONE cluster: eye protrusion, plate
# extent + fur receiver, hairline curtain, plate hue, snout. Appended on the production
# pufferball_look.py; every name below shadows the earlier binding (post_build / seat_eyes /
# _socket_ring / face_material / build_mouth_beak read module globals at call time).
#
# run1 — EYE PROTRUSION: the eyeball becomes a SPHERE in the same socket.
# Critic: "profile eye is small and recessed (ID 0.080 W vs anchor 0.128 W); anchor_side's
# eye bulges out of the plate as a full amber hemisphere -> move each eye centre outward
# along the socket normal by ~+0.35 er and reduce the socket dish depth by the same".
# Geometry of the R5 lens: the visible disc is rho <= RIM_RHO (0.92) of an oblate spheroid
# (1, EYE_DEPTH, 1) x er; apex = EYE_DEPTH x (1 - sqrt(1 - 0.92^2)) = 0.608 x EYE_DEPTH er
# above the face point; the collar crest and the lid ring's inner wall sit at
# _lens_t(0.92) (+lip / +proud) from the CENTRE, and the centre at (EYE_PROUD - D) er from
# the face point, so both stay at the same place relative to the face point for ANY D.
# EYE_DEPTH 0.42 -> 1.00: apex 0.255 -> 0.608 er (+0.353 er = the critic's +0.35), the
# dome above the ring's wall 0.24 -> 0.53 er, socket / ring / collar / front disc unchanged
# (front eye_frac is linear in RIM_RHO x er, both kept). In profile (eye axis 35 deg out,
# side camera 55 deg off-axis) the sphere's front-most point (rho 0.574) projects 1.00 er
# in front of the eye centre vs the ring wall's 0.91 er: the amber now stands past the ring.
# EYE_DEPTH_FUR follows (the 3D fur exclusion becomes a sphere of eye_r0..r1 about a
# centre that is now 0.39 er (21 mm) behind the face point, was 0.165 er).
# ═════════════════════════════════════════════════════════════════════════════
EYE_DEPTH = 1.00
EYE_PROUD = EYE_DEPTH * (1.0 - math.sqrt(1.0 - RIM_RHO**2))
EYE_DEPTH_FUR = max(EYE_DEPTH_FUR, EYE_DEPTH)
print(
    'R9FACE run1: EYE_DEPTH %.2f -> apex %.3f er (%.1f mm) above the face point, %.1f mm above the ring wall; fur depth %.2f'
    % (
        EYE_DEPTH,
        EYE_PROUD,
        EYE_PROUD * PARAMS['eye_r'] * 1000,
        (EYE_DEPTH - _lens_t(RIM_RHO) - RING8['proud']) * PARAMS['eye_r'] * 1000,
        EYE_DEPTH_FUR,
    )
)


# ── run2: the PUPIL and IRIS re-seated on the sphere ─────────────────────────────────────
# run1 (probe.py): profile eye w/h 0.519 -> 0.667 (anchor 0.66), 85 % of the profile eye's ID
# pixels now stand in front of the plate (base 0 %), front/close eye_frac_id unchanged (0.147 ->
# 0.148 / 0.236 -> 0.237). Two consequences of the sphere on the front views:
#  * the pupil is placed where the world -Y line meets the lens (x PUPIL_CONVERGE): on the
#    oblate lens that was rho 0.286 x 0.75 = 0.214 r nasal of the axis; on the sphere the line
#    meets at sin 35.4 = 0.574 -> 0.43 r, so the pupil slid 0.22 r nasal and a conformal patch
#    of radius 0.553 r on a sphere facing the camera projects nearly un-foreshortened: pupil
#    ID area / (iris + pupil) 0.356 -> 0.456 (cell_11: pupil 0.55 of the iris WIDTH, centre
#    ~0.10 iris-widths nasal). pupil_r 0.0293 -> 0.024 (0.45 r, 0.49 of the visible disc) and
#    PUPIL_CONVERGE 0.75 -> 0.45 (centre 0.26 r nasal).
#  * the iris darkened: front iris-ID median L 147 -> 134 (lab_eye 12 -> 17; anchor L 155): the
#    curved iris turns away from the front-upper-left eye light. That light links pb_eye /
#    pb_pupil / pb_glint only (EYE_ONLY), so it is the one lever that touches nothing else:
#    eyelight 9 -> 13 W.
PARAMS.update({'pupil_r': 0.024})
PUPIL_CONVERGE = 0.45
LIGHTS['eyelight'].update(W=13.0)
print(
    'R9FACE run2: pupil_r %.4f (%.2f r), PUPIL_CONVERGE %.2f, eyelight %.0f W'
    % (PARAMS['pupil_r'], PARAMS['pupil_r'] / PARAMS['eye_r'], PUPIL_CONVERGE, LIGHTS['eyelight']['W'])
)


# ── run3: the PROFILE CHEEK — a teardrop of bare plate, feathered locks behind it ─────────
# run2 (probe.py side_left): bare plate behind the profile eye 1.14 eye-widths (base 1.49; the
# anchor_side ~0.4). Read off the ID pass + the R6 geometry: the lid ring's rear edge is at
# y ~ -0.120 (body-local) at eye height and the R6 wedge lets roots start at y > -0.105, i.e.
# 15 mm (~0.3 ew) behind the ring — the wedge is NOT what bares the temple. What does:
#  * the plate's rear-sliver roots (x 0.11-0.122, y -0.105..-0.064) are the R7 'rim' zone: 40 mm
#    locks at lean 2.0 (63 deg off the normal, lying flat) with flow (0.25, 1.0, 0.05) = back
#    and a little UP, so they cover nothing in front of their own roots and in profile they
#    read as a vertical wall of tips pointing at the camera behind ~60 mm of bare plate;
#  * the body roots at the plate/body junction (y -0.064..-0.04) are cut by the R6 rule
#    'inside the plate ellipsoid' (t < 1.04), so the first body lock stands ~25 mm further back.
# anchor_side: the fur behind the eye lies BACK AND DOWN along the head (~30 deg below the
# horizontal), its roots ~0.4 ew behind the lid, and the bare cheek is a teardrop tapering
# from the eye down toward the chin.
#  * TUFT7 rim zone: lean 2.0 -> 0.9 (~42 deg off the normal: the lock now hides the plate
#    under it), length 40 -> 50 mm, flow (0.25, 1.0, 0.05) -> (0.2, 0.85, -0.45) back-and-down.
#    _dir7's 'never forward over the plate' clamp (d.y >= 0) is kept, so nothing reaches the eye.
#  * CHEEK6 plate_t 1.04 -> 0.98: only body roots that are genuinely under the plate are cut;
#    the junction roots (t 0.98-1.04, within ~3 mm of the plate surface) stay and feather it.
#  * CHEEK6 y_back_eye -0.105 -> -0.112: first plate roots 8 mm (~0.15 ew) behind the ring;
#    y_back_brow (-0.130) unchanged — the brow is the hairline run's business.
CHEEK6.update({'y_back_eye': -0.112, 'plate_t': 0.98})
TUFT7['lean'].update({'rim': 0.9})
TUFT7['len'].update({'rim': 0.050})
TUFT7['rim_flow'] = (0.2, 0.85, -0.45)
_flow7_r8 = _flow7


def _flow7(P, Z):
    F = _flow7_r8(P, Z)
    if Z[6] > 0.0:
        rf = TUFT7['rim_flow']
        F = Vector(
            (rf[0] * (1.0 if P.x > 0 else -1.0), rf[1], rf[2])
        ).normalized()  # plate rim: back and DOWN along the head
    return F


print(
    'R9FACE run3: rim locks lean %.2f len %.3f flow %s; cheek y_back_eye %.3f plate_t %.2f'
    % (TUFT7['lean']['rim'], TUFT7['len']['rim'], TUFT7['rim_flow'], CHEEK6['y_back_eye'], CHEEK6['plate_t'])
)


# ── run4: the HAIRLINE as a forward-pitched fringe; rim lean ramped back above the eye ──────
# run3 (cmp_spike_side.png / cmp_finder_front.png): the profile temple is covered by locks lying
# back-and-down, bare band ~0.3 ew behind the ring — kept. Two things to correct:
#  * one rim-zone lock at the TOP of the zone (z ~0.12, an up-facing normal) now stands up at
#    lean 0.9 where it lay flat at 2.0: a lone antenna at the top-front in profile. The lean is
#    ramped: 0.9 below z 0.09 -> 2.0 at z 0.12 (blend of the two directions, no extra rng draws).
#  * front eye_frac +48.8 % is the harness's chest blob (box (547,639) 238x206, 0 % on the eye
#    ids; ID eye_frac 0.148 unchanged): the coat re-samples whenever a root count changes.
# HAIRLINE (critic [major][fur]): the plate top is a hard hairline with upright blades and stray
# tips; anchor_side's crown-front sweeps FORWARD and down over the brow, anchor_full/cell_11's
# plate top is a soft feathered edge. Geometry: the plate top (z 0.1345) meets the body 7 mm in
# front of it, but the plate's brow bulges 40 mm in front of the body at z 0.12 — so the
# forehead locks must ride FORWARD over the plate's up-facing top and hang their tips in front
# of its brow. Band = body-local z 0.108..0.205 (full 0.122..0.185), |x| < 0.105 (-> 0 at
# 0.125), y < -0.02: the crown-front body roots (z > 0.135, y -0.08..-0.03) and the plate's own
# brow roots (cap kind). Direction: n + 3.0 x tangent of (0, -0.9, -0.44) (a lock ~15 deg below
# the horizontal, forward), blended in by the band weight over run3's direction (the jitter draw
# is untouched); length 70 mm in the band (crown 75 / cap 45). Brow roots whose lock would pass
# within 1.10 er of an eye are dropped by the R7 eye test as before, so nothing hangs into the
# eyes and the lid tops stay bare (cell_11).
HAIR9 = {
    'z': (0.108, 0.122, 0.185, 0.205),
    'x': (0.105, 0.125),
    'y': (-0.035, -0.02),
    'flow': (0.0, -0.9, -0.44),
    'lean': 3.0,
    'len': 0.070,
    'rim_z': (0.09, 0.12),
    'rim_lean_top': 2.0,
}


def _hair9_w(P):
    H = HAIR9
    z0, z1, z2, z3 = H['z']
    x0, x1 = H['x']
    y0, y1 = H['y']
    wz = _sm7((P.z - z0) / (z1 - z0)) * (1.0 - _sm7((P.z - z2) / (z3 - z2)))
    wx = 1.0 - _sm7((abs(P.x) - x0) / (x1 - x0))
    wy = 1.0 - _sm7((P.y - y0) / (y1 - y0))
    return wz * wx * wy


_dir7_r9run3 = _dir7
_len7_r9run3 = _len7


def _dir7(P, n, Z, rng):
    d0 = _dir7_r9run3(P, n, Z, rng)  # run3's direction, jitter drawn exactly as before
    if Z[6] > 0.0 and P.z > HAIR9['rim_z'][0]:  # rim zone above the eye: back toward lying flat
        F = _flow7(P, Z)
        t = F - n * F.dot(n)
        if t.length > 1e-4:
            wr = _sm7((P.z - HAIR9['rim_z'][0]) / (HAIR9['rim_z'][1] - HAIR9['rim_z'][0]))
            df = (Vector(n) + t.normalized() * (HAIR9['rim_lean_top'] * min(1.0, t.length / 0.3))).normalized()
            if P.y < -0.04 and df.y < 0.0:
                df.y = 0.0
                df.normalize()
            d0 = (d0 * (1.0 - wr) + df * wr).normalized()
    w = _hair9_w(P)
    if w <= 0.0:
        return d0
    F = Vector(HAIR9['flow']).normalized()
    t = F - n * F.dot(n)
    dh = (Vector(n) + t.normalized() * HAIR9['lean']).normalized() if t.length > 1e-4 else Vector(n)
    return (d0 * (1.0 - w) + dh * w).normalized()


def _len7(P, Z):
    L = _len7_r9run3(P, Z)
    w = _hair9_w(P)
    return L * (1.0 - w) + HAIR9['len'] * w if w > 0.0 else L


print(
    'R9FACE run4: hairline band z %s x %s flow %s lean %.1f len %.3f; rim lean ramp z %s -> %.1f'
    % (HAIR9['z'], HAIR9['x'], HAIR9['flow'], HAIR9['lean'], HAIR9['len'], HAIR9['rim_z'], HAIR9['rim_lean_top'])
)


# ── run5: the SNOUT — salmon lip pad, upper lip proud of the lower, open dark interior ────
# run4 kept (profile: the crown-front sweeps forward-down over the brow; the antenna is gone;
# side tail_above -3.8 -> +1.3 %; close-up plate top overhung by pitched tips). The side eye
# finder returned NO box in run4, so the harness's side fur/face ROIs changed basis (lab_fur 10
# -> 17 is that flip: measured on one basis base and run4 agree — see the report).
# Critic [minor][skin]: "lips burnt orange and flat (oval with a slit); anchor is a small salmon
# snout, upper lip protruding over the lower, high gloss, open dark interior, tiny upper teeth ->
# lip #E0975A-ish, clear-coat gloss 0.2, interior #7A2A28, upper-lip pad proud ~0.3 eye-dia."
# Measured (probe.py, mouth ID): ours renders sRGB (187,125,64) Lab (148,+17,+39); cell_11's
# lip (179,111,51) Lab (136,+21,+43); #E0975A = (224,151,90) is its lit top. Our albedo
# (0.276,0.044,0.005) has R/B 55 (a pure orange); #E0975A linear is (0.745,0.305,0.10), R/B 7.5,
# R/G 2.4 -> G x1.6, B x4.4, R x1.2 (the render follows luminance under AgX, so R goes up too).
#  * BEAK (0.33,0.070,0.022), LOWLIP (0.30,0.064,0.020), CAVITY (0.100,0.020,0.015) ->
#    (0.17,0.028,0.026) (#7A2A28 lin (0.195,0.023,0.021)), tongue (0.16,0.030,0.024);
#    LIP_ROUGH 0.30 -> 0.25, coat 0.20 kept, coat roughness 0.10 -> 0.05 (the wet gloss).
#  * shape (R5 pad 82x44 mm, 32 mm = 0.3 eye-dia proud — kept): the aperture cut centre drops
#    2 -> 6 mm below the pad centre and grows 8.8 -> 9.5 mm tall, so the upper lip is a thick
#    pad (0.45 of the height) over a taller opening and a thin lower band; the lower-lip bulge
#    goes 7.6 -> 12 mm behind the pad pole (its front 4 mm behind the upper lip's: the upper
#    lip overhangs it), the teeth hang 1 mm under the new upper edge (cavity top at the tooth
#    depth +2.4 mm -> TEETH_DZ 0.0008), the tongue follows the lowered floor.
BEAK_RGB = (0.33, 0.070, 0.022)
LOWLIP_RGB = (0.30, 0.064, 0.020)
CAVITY_RGB = (0.17, 0.028, 0.026)
TONGUE_RGB = (0.16, 0.030, 0.024)
LIP_ROUGH = 0.25
LIP_COAT_ROUGH = 0.05
CUT_DZ = -0.006
CUT_R = (0.030, 0.012, 0.0095)
LOWLIP_DY = 0.012
LOWLIP_DZ = -0.016
TEETH_DZ = 0.0008
TONGUE_DZ = -0.0105
print(
    'R9FACE run5: BEAK %s LOWLIP %s CAVITY %s rough %.2f coat %.2f/%.2f; cut dz %.4f r %s; lowlip dy %.4f dz %.4f; teeth dz %.4f tongue dz %.4f'
    % (
        BEAK_RGB,
        LOWLIP_RGB,
        CAVITY_RGB,
        LIP_ROUGH,
        LIP_COAT,
        LIP_COAT_ROUGH,
        CUT_DZ,
        CUT_R,
        LOWLIP_DY,
        LOWLIP_DZ,
        TEETH_DZ,
        TONGUE_DZ,
    )
)


# ── run6: PLATE HUE — pale aqua-mint between the eyes ───────────────────────────────────
# run5 kept (mouth-ID median sRGB (187,125,64) -> (198,147,91), Lab (148,+17,+39) -> (165,+14,+35);
# cell_11's lip (179,111,51), the critic's #E0975A (224,151,90); the upper lip now overhangs).
# Critic [minor][skin]: "plate hue leans green; anchor plate is aqua-mint (front b* -5 vs ours 0);
# must read pale mint between the eyes like cell_11". Measured (run3-5): harness front face
# median Lab (148,-23,+2) vs the anchor's (152,-22,-5) (lab_face 8); bridge (face ID between
# the eyes, ring excluded) (173,-25,+3) vs cell_11's bridge (188,-24,-1) and anchor_full's
# (210,-28,+17). So the hue is 5-7 b* too yellow and the plate 4-15 L too dark. FACE_MID
# (0.024,0.089,0.070) -> (0.0255,0.094,0.088): B x1.26 (B/G 0.79 -> 0.94: toward cyan), R/G
# x1.06 overall (+~4 L under AgX); the chin multiplier (3.0,3.1,3.2) and the gradient stay, so
# the lower plate keeps its relative lift. The collar (pb_skin_orbit) is a copy of pb_skin_face
# made at build time, so it follows.
FACE_MID = (0.0255, 0.094, 0.088)
print('R9FACE run6: FACE_MID %s' % (FACE_MID,))


# ═════════════════════════════════════════════════════════════════════════════
# R9 COAT (lookdev3 round 1 / r1_coat) — everything outside the face: arms, feet, tail fluff,
# the coat's colour grade under the rig. Base = the production pufferball_look.py (R8 MERGE run3).
# Each run below is ONE change, measured against the base render in this directory (base/):
#   base: front arm sRGB(33,84,65) L83 / anchor shade arm (9,101,97) L98, lit arm (154,168,81) L169;
#         front foot (69,90,55) L95 / anchor feet green (61,71,20)..lime (137,148,59);
#         tail front L219 side L157; front flankR (228,224,206) b+10 / anchor (249,223,139) b+43;
#         crown clip >= 250: 0.07 %.
# ═════════════════════════════════════════════════════════════════════════════

# ── run1: ARMS — one swept, smoothly tapered limb per side + a glossy mint arm material ──────
# Critic: arms darker/duller than the anchor's glossy mint; a stepped ring at the elbow (cracked
# joint) — anchor arm is one smooth tapered limb with a soft bend. Cause of the ring: R5's arm is
# two 2-ring _capsules (a single side-wall quad strip whose smooth normals pinch to the cap vertex)
# meeting an elbow sphere: three separate skins with discontinuous normals at the joint. Here the
# same knots (shoulder -> elbow -> wrist -> paw, R5_ARMS geometry untouched) are swept as ONE tube
# along a Catmull-Rom curve with parallel-transported frames: 48 rings x 28 sides, the radius
# graded r0 -> 0.86 r0 (elbow) -> 0.72 r0 (wrist) -> 0.80 r0 (paw) -> a dome, the root buried 25 mm
# inside the body. Nubs stay (R5's three, same positions).
# Material: the base skin albedo (0.022,0.19,0.20) has almost no R and renders (33,84,65) under the
# rig; the anchor arm is a MID mint-green (side (25,118,102) shaded, (154,168,81) lime where the
# warm key lands — an albedo with real R, ~ sRGB (85,175,155)) with a wet-plastic sheen. Arm-only
# material (a copy of skin_material's speckle + bump): albedo (0.075,0.40,0.32), roughness 0.30,
# coat 0.40 / 0.12. pb_skin (face fallback, nubs elsewhere) is untouched; only pass_index 'arm'
# objects get it.
ARM9 = {
    'sides': 28,
    'rings': 48,
    'dome_rings': 7,
    'root_in': 0.025,
    'r_el': 0.86,
    'r_wr': 0.72,
    'r_paw': 0.80,
    'paw_ext': 0.012,
    'dome': 0.55,
}
ARM9_RGB = (0.075, 0.40, 0.32)
ARM9_ROUGH = 0.30
ARM9_SPEC = 0.50
ARM9_COAT = 0.40
ARM9_COAT_ROUGH = 0.12
ARM9_SSS = 0.25


def _cr9(P, t):
    """Catmull-Rom through the list P (Vectors or floats) at t in [0, len(P)-1]."""
    n = len(P)
    i = max(0, min(n - 2, int(math.floor(t))))
    u = t - i
    p0 = P[max(0, i - 1)]
    p1 = P[i]
    p2 = P[i + 1]
    p3 = P[min(n - 1, i + 2)]
    return 0.5 * (
        (2 * p1)
        + (-p0 + p2) * u
        + (2 * p0 - 5 * p1 + 4 * p2 - p3) * (u * u)
        + (-p0 + 3 * p1 - 3 * p2 + p3) * (u * u * u)
    )


def _sweep9(name, knots, radii, scene, mat, PB, idx='arm'):
    """One closed tube swept along knots (world coords) with radius radii[i] at knot i;
    fan-capped at the start (buried), domed at the end."""
    A = ARM9
    S, R = A['sides'], A['rings']
    nk = len(knots)
    cs, rs = [], []
    for i in range(R + 1):
        t = (nk - 1) * i / float(R)
        cs.append(_cr9(knots, t))
        rs.append(max(0.002, _cr9(radii, t)))
    # tangents + parallel-transport frames
    Ts = []
    for i in range(R + 1):
        a = cs[max(0, i - 1)]
        b = cs[min(R, i + 1)]
        Ts.append((b - a).normalized())
    N = Ts[0].cross(Vector((1.0, 0.0, 0.0)))
    if N.length < 1e-4:
        N = Ts[0].cross(Vector((0.0, 1.0, 0.0)))
    N.normalize()
    verts, faces = [], []
    frames = []
    for i in range(R + 1):
        T = Ts[i]
        N = (N - T * N.dot(T)).normalized()
        B = T.cross(N).normalized()
        frames.append((N, B))
        for j in range(S):
            th = 2.0 * math.pi * j / S
            verts.append(tuple(cs[i] + N * (rs[i] * math.cos(th)) + B * (rs[i] * math.sin(th))))
    for i in range(R):
        a = i * S
        b = a + S
        for j in range(S):
            j2 = (j + 1) % S
            faces.append((a + j, b + j, b + j2, a + j2))
    # start cap: fan to a centre vertex pulled back along the tangent (inside the body)
    c0 = len(verts)
    verts.append(tuple(cs[0] - Ts[0] * (rs[0] * 0.5)))
    for j in range(S):
        j2 = (j + 1) % S
        faces.append((c0, j2, j))
    # end dome: rings shrinking as cos(phi), advancing sin(phi) * dome_len along the tangent
    D = A['dome_rings']
    r_end = rs[-1]
    dome_len = r_end * A['dome'] / 0.55 * 0.55 if False else rs[-1] * 1.0
    dome_len = r_end * 0.95
    N, B = frames[-1]
    T = Ts[-1]
    prev = R * S
    for k in range(1, D + 1):
        phi = 0.5 * math.pi * k / float(D + 1)
        rr = r_end * math.cos(phi)
        c = cs[-1] + T * (dome_len * math.sin(phi))
        base = len(verts)
        for j in range(S):
            th = 2.0 * math.pi * j / S
            verts.append(tuple(c + N * (rr * math.cos(th)) + B * (rr * math.sin(th))))
        for j in range(S):
            j2 = (j + 1) % S
            faces.append((prev + j, base + j, base + j2, prev + j2))
        prev = base
    tip = len(verts)
    verts.append(tuple(cs[-1] + T * dome_len))
    for j in range(S):
        j2 = (j + 1) % S
        faces.append((prev + j, tip, prev + j2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    PB._cylindrical_uv(me)
    PB._outward(me)
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    ob.pass_index = PB.IDX[idx]
    return PB._link(ob, scene)


def build_arms_r9(mats, scene, p, PB):
    """R9: R5's knots (shoulder / elbow / wrist / paw) as one swept limb + R5's nubs."""
    out = []
    A = ARM9
    sx_, sy_, sz_ = p['arm_sh']
    a_out = math.radians(p['arm_out_deg'])
    a_in = math.radians(p['arm_in_deg'])
    a_fwd = math.radians(p['arm_fwd_deg'])
    r0 = p['arm_r']
    pr = p['paw_r']
    for sx in (-1, 1):
        side = 'l' if sx < 0 else 'r'
        sh = Vector((sx * p['body_rx'] * sx_, p['body_ry'] * sy_, p['body_lift'] + p['body_rz'] * sz_))
        d1 = Vector((sx * math.sin(a_out), -math.sin(a_fwd), -math.cos(a_out))).normalized()
        el = sh + d1 * p['arm_upper']
        d2 = Vector((-sx * math.sin(a_in), -math.sin(a_fwd), -math.cos(a_in))).normalized()
        wr = el + d2 * p['arm_fore']
        pc = wr + d2 * p['paw_drop']
        pe = pc + d2 * A['paw_ext']
        sh_in = sh - d1 * A['root_in']
        knots = [sh_in, sh, el, wr, pc, pe]
        radii = [r0, r0, r0 * A['r_el'], r0 * A['r_wr'], r0 * A['r_paw'], r0 * A['dome']]
        out.append(_sweep9('pb_arm_%s' % side, knots, radii, scene, mats['skin'], PB, idx='arm'))
        for k in range(p['nub_n']):
            ang = math.radians(-30 + 30 * k)
            nd = Vector((sx * math.sin(ang) * 0.9, -math.cos(ang) * 0.70, -0.80)).normalized()
            nc = pc + Vector((nd.x * pr[0], nd.y * pr[1], nd.z * pr[2])) * 0.92
            out.append(
                PB._sphere(
                    'pb_nub_%s%d' % (side, k), tuple(nc), p['nub_r'], scene, mats['skin'], segs=12, rings=8, idx='arm'
                )
            )
        print(
            'R9 arm %s: swept limb sh %s el %s wr %s paw %s (tip z %.3f)'
            % (
                side,
                tuple(round(v, 3) for v in sh),
                tuple(round(v, 3) for v in el),
                tuple(round(v, 3) for v in wr),
                tuple(round(v, 3) for v in pc),
                (pe + d2 * (r0 * A['dome'] * 0.95)).z,
            )
        )
    return out


def arm_material9(m):
    """skin_material's speckle + bump on a mid mint-green with a coat."""
    nt, b = _principled_reset(m)
    n, L = nt.nodes, nt.links
    b.inputs['Roughness'].default_value = ARM9_ROUGH
    b.inputs['Specular IOR Level'].default_value = ARM9_SPEC
    b.inputs['Subsurface Weight'].default_value = ARM9_SSS
    b.inputs['Subsurface Radius'].default_value = SKIN_SSS_RADIUS
    b.inputs['Subsurface Scale'].default_value = SKIN_SSS_SCALE
    b.subsurface_method = 'RANDOM_WALK'
    b.inputs['Coat Weight'].default_value = ARM9_COAT
    b.inputs['Coat Roughness'].default_value = ARM9_COAT_ROUGH
    tc = n.new('ShaderNodeTexCoord')
    vor = n.new('ShaderNodeTexVoronoi')
    vor.voronoi_dimensions = '3D'
    vor.feature = 'F1'
    vor.inputs['Scale'].default_value = 260.0
    vor.inputs['Randomness'].default_value = 1.0
    L.new(tc.outputs['Object'], vor.inputs['Vector'])
    noi = n.new('ShaderNodeTexNoise')
    noi.inputs['Scale'].default_value = 70.0
    noi.inputs['Detail'].default_value = 2.0
    L.new(tc.outputs['Object'], noi.inputs['Vector'])
    lt = n.new('ShaderNodeMath')
    lt.operation = 'LESS_THAN'
    lt.inputs[1].default_value = 0.22
    L.new(vor.outputs['Distance'], lt.inputs[0])
    gt = n.new('ShaderNodeMath')
    gt.operation = 'GREATER_THAN'
    gt.inputs[1].default_value = 0.64
    L.new(noi.outputs['Fac'], gt.inputs[0])
    mul = n.new('ShaderNodeMath')
    mul.operation = 'MULTIPLY'
    L.new(lt.outputs[0], mul.inputs[0])
    L.new(gt.outputs[0], mul.inputs[1])
    mul2 = n.new('ShaderNodeMath')
    mul2.operation = 'MULTIPLY'
    mul2.inputs[1].default_value = 0.85
    L.new(mul.outputs[0], mul2.inputs[0])
    mix = n.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MIX'
    mix.inputs[6].default_value = (*ARM9_RGB, 1.0)
    mix.inputs[7].default_value = (*GOLD_RGB, 1.0)
    L.new(mul2.outputs[0], mix.inputs[0])
    L.new(mix.outputs[2], b.inputs['Base Color'])
    vb = n.new('ShaderNodeTexVoronoi')
    vb.voronoi_dimensions = '3D'
    vb.feature = 'SMOOTH_F1'
    vb.inputs['Scale'].default_value = 300.0
    vb.inputs['Smoothness'].default_value = 0.35
    L.new(tc.outputs['Object'], vb.inputs['Vector'])
    bump = n.new('ShaderNodeBump')
    bump.invert = True
    bump.inputs['Strength'].default_value = 0.30
    bump.inputs['Distance'].default_value = 0.0015
    L.new(vb.outputs['Distance'], bump.inputs['Height'])
    L.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


def _arm_mat_post9(scene, PB):
    m = bpy.data.materials.get('pb_skin_arm')
    if m is None:
        m = bpy.data.materials.new('pb_skin_arm')
        m.use_nodes = True
        arm_material9(m)
    n = 0
    for ob in scene.collection.objects:
        if ob.type == 'MESH' and ob.pass_index == PB.IDX['arm']:
            if ob.data.materials:
                ob.data.materials[0] = m
            else:
                ob.data.materials.append(m)
            n += 1
    print('R9 run1: pb_skin_arm %s rough %.2f coat %.2f on %d arm objects' % (ARM9_RGB, ARM9_ROUGH, ARM9_COAT, n))


_pre_build_r8final = pre_build


def pre_build(PB):
    _pre_build_r8final(PB)
    PB.build_arms = lambda mats, scene, p=PB.P: build_arms_r9(mats, scene, p, PB)
    print('R9 run1: build_arms -> swept limb')


_post_build_r8final = post_build


def post_build(scene, result, PB):
    _post_build_r8final(scene, result, PB)
    _arm_mat_post9(scene, PB)
    bpy.context.view_layer.update()


# ── run2: FEET — olive yellow-green, glossy ──────────────────────────────────────────────────
# run1 kept: front arm (33,84,65) L83 -> (57,122,87) L119, side (32,77,63) L76 -> (48,115,88) L112
# (anchor side arm (25,118,102) L114); the elbow ring is gone in q45/side; gated numbers unmoved
# (front lab_fur 7 -> 8, side 9 -> 9).
# Critic: feet pale mint toe-balls; anchor feet olive yellow-green (~(0.55,0.65,0.25) sRGB). Measured
# on the anchors (green-gated foot boxes): front (61,71,20) L72 shade .. (137,148,59) L98 lit, hue
# ~75 deg S 0.7; ours (72,91,55) L96 hue ~95 deg S 0.5 — PB's default mats['foot'] (0.33,0.66,0.42)
# rough 0.44, a plain green with no yellow. Foot + leg objects (pass_index 'foot' / 'leg') get their
# own material: albedo (0.26,0.40,0.055) = sRGB ~(143,170,68), rough 0.30, coat 0.35 / 0.12 (the
# anchor toes carry one soft highlight each), the skin speckle at a third of the arm's gold weight.
FOOT9_RGB = (0.26, 0.40, 0.055)
FOOT9_ROUGH = 0.30
FOOT9_COAT = 0.35
FOOT9_SPECKLE = 0.30


def limb_material9(m, rgb, rough, coat, speckle):
    arm_material9(m)
    nt = m.node_tree
    n = nt.nodes
    b = next(x for x in n if x.type == 'BSDF_PRINCIPLED')
    b.inputs['Roughness'].default_value = rough
    b.inputs['Coat Weight'].default_value = coat
    mix = next(x for x in n if x.type == 'MIX' and x.data_type == 'RGBA')
    mix.inputs[6].default_value = (*rgb, 1.0)
    mul2 = [
        x
        for x in n
        if x.type == 'MATH'
        and x.operation == 'MULTIPLY'
        and not x.inputs[1].is_linked
        and abs(x.inputs[1].default_value - 0.85) < 1e-6
    ]
    if mul2:
        mul2[0].inputs[1].default_value = speckle
    return m


def _foot_mat_post9(scene, PB):
    m = bpy.data.materials.get('pb_foot9')
    if m is None:
        m = bpy.data.materials.new('pb_foot9')
        m.use_nodes = True
        limb_material9(m, FOOT9_RGB, FOOT9_ROUGH, FOOT9_COAT, FOOT9_SPECKLE)
    n = 0
    for ob in scene.collection.objects:
        if ob.type == 'MESH' and ob.pass_index in (PB.IDX['foot'], PB.IDX['leg']):
            if ob.data.materials:
                ob.data.materials[0] = m
            else:
                ob.data.materials.append(m)
            n += 1
    print('R9 run2: pb_foot9 %s rough %.2f coat %.2f on %d foot/leg objects' % (FOOT9_RGB, FOOT9_ROUGH, FOOT9_COAT, n))


_post_build_r9_run1 = post_build


def post_build(scene, result, PB):
    _post_build_r9_run1(scene, result, PB)
    _foot_mat_post9(scene, PB)
    bpy.context.view_layer.update()


# ── run3: LIMB LIGHT — the anchor's front-right warm key, on the arms and feet only ──────────
# run2: feet (72,91,55) L96 -> (66,73,21) L77 b+26 (anchor shade (61,71,20)); by eye the toes are the
# anchor's olive. But front eye_frac +7 -> +115 %: dbg_eyes_run12.png shows the warm belly hem is
# amber-gated in every run, and the olive feet's shaded halves (V<70) now touch it, so the hem blob
# passes the finder's 10 % pupil test and outranks the eyes (run1's sage feet were neither amber
# nor dark). The anchor's feet are not that dark because they are LIT: a highlight on every toe
# from the front-right, and the creature's left arm goes lime (154,168,81) under the same light.
# Ours get nothing warm there: 'lowkey' (0.5 W) is linked to the creature MINUS legs/feet/toes, and
# 'key' (mint-white, el 70) is shadowed by the coat. Two small warm disks at lowkey's position
# (az 55 / el -15 / 1.1 S), each light-linked to limbs only, floor out of their blockers:
#  * armkey  (1.0,0.30,0.08) 1.5 W -> pb_arm / pb_nub: the mint albedo (0.075,0.40,0.32) needs a
#    light of R/G ~4 to read lime (anchor lit arm R/G 0.92 sRGB).
#  * footkey (1.0,0.72,0.40) 2.0 W -> pb_foot / pb_toe / pb_leg: the olive albedo under an amber
#    would go orange; a warm cream keeps it yellow-green (anchor lit toe (137,148,59)).
LIMB9 = {
    'armkey': dict(
        pos=(0.87, -0.609, -0.285), W=1.5, size=0.35, rgb=(1.00, 0.30, 0.08), aim='c', prefixes=('pb_arm', 'pb_nub')
    ),
    'footkey': dict(
        pos=(0.87, -0.609, -0.285),
        W=2.0,
        size=0.35,
        rgb=(1.00, 0.72, 0.40),
        aim='low',
        prefixes=('pb_foot', 'pb_toe', 'pb_leg'),
    ),
}


def _limb_lights9(scene, centre, size):
    c = Vector(centre)
    S = float(size)
    ek = (S / S_REF) ** 2
    aims = {'low': c + Vector((0, -0.15 * S, -0.15 * S)), 'c': c}
    blockers = bpy.data.collections.get('pb_blockers_nofloor')
    for name, L in LIMB9.items():
        if bpy.data.objects.get(name) is not None:
            continue
        o = _area(
            scene, name, c + Vector(L['pos']) * S, L['W'] * ek, L['size'] * S, aims[L['aim']], L['rgb'], glossy=True
        )
        _link_prefix(scene, o, 'pb_limb9_%s' % name, L['prefixes'])
        if blockers is not None:
            o.light_linking.blocker_collection = blockers
        print(
            'R9 run3: %s %.2f W x %.2f at %s rgb %s -> %s'
            % (name, L['W'], ek, tuple(round(v, 3) for v in o.location), L['rgb'], L['prefixes'])
        )


_lighting_r8final = lighting


def lighting(scene, centre, size, aim):
    _lighting_r8final(scene, centre, size, aim)
    _limb_lights9(scene, centre, size)


# ── run4: footkey -0.7 stop, legs out of it ─────────────────────────────────────────────────
# run3 kept: front eye_frac back to +7.3 % (the real eyes; the hem blob lost its dark 'pupil'),
# lit arm lime (q45 arm (109,148,106) b+18), front feet (95,95,30) L99 b+32 inside the anchor's
# (61,71,20)..(137,148,59). Overshoot in profile / q45: side foot (119,122,32) L127 b+42 vs the
# anchor's lit toe (73,95,40) L95 b+29, and the LEGS under the hem lit up as yellow stalks
# (side leg L56 -> L107) where the anchor keeps its ankles dark (0,62,60). footkey 2.0 -> 1.2 W,
# receivers pb_foot / pb_toe only (legs keep the general rig).
# Side eye_frac is now None (no box): the base's +47.6 % was the bogus belly blob (its 'pupil' was
# the unlit far leg), which run3 dissolved; the real profile eye was never found by the RGB finder
# (it merges with the lip into a tall blob). With no box, lab_medians_rgb drops its face ROI, so the
# side lab_fur reads 16 where the base read 9: under the same no-ROI condition base = 14.9 and this
# file = 15.8 (the glossy arm highlights entering the pale gate).
LIMB9['footkey'].update(W=1.2, prefixes=('pb_foot', 'pb_toe'))
print('R9 run4: footkey %.1f W -> %s' % (LIMB9['footkey']['W'], LIMB9['footkey']['prefixes']))


# ── run5: footkey back to 2.0 W (feet only); arm speckle 0.85 -> 0.30; nubs 6.2 -> 8.0 mm ────
# run4: footkey 1.2 W put the front feet's shaded halves back under the finder's V<70 (front foot
# (84,87,27) V87 median) and the hem blob regained its 'pupil' (front eye_frac +118.6 %); the legs
# out of footkey did what was wanted (side leg L107 -> L36, anchor ankle L58). So: footkey at run3's
# verified 2.0 W, receivers feet/toes only (the front feet keep run3's level; the profile foot stays
# ~1 stop over the anchor's lit toe — the price of the harness's dark gate).
# Two limb-only tunes seen on the run1/run3 crops: the gold Voronoi speckle (skin_material's 0.85)
# reads as glitter dust on the brighter arm -> 0.30 (the anchor arm has a fine dotted grain, no
# gold); the paw nubs (6.2 mm on a 26 mm paw) barely peek out -> 8.0 mm at the paw surface
# (anchor: three short toes hanging from the mitten).
LIMB9['footkey'].update(W=2.0, prefixes=('pb_foot', 'pb_toe'))
ARM9_SPECKLE = 0.30
ARM9['nub_r'] = 0.0080
ARM9['nub_out'] = 1.00


def _arm_mat_post9(scene, PB):
    m = bpy.data.materials.get('pb_skin_arm')
    if m is None:
        m = bpy.data.materials.new('pb_skin_arm')
        m.use_nodes = True
        limb_material9(m, ARM9_RGB, ARM9_ROUGH, ARM9_COAT, ARM9_SPECKLE)
    n = 0
    for ob in scene.collection.objects:
        if ob.type == 'MESH' and ob.pass_index == PB.IDX['arm']:
            if ob.data.materials:
                ob.data.materials[0] = m
            else:
                ob.data.materials.append(m)
            n += 1
    print(
        'R9 run5: pb_skin_arm %s rough %.2f coat %.2f speckle %.2f on %d arm objects'
        % (ARM9_RGB, ARM9_ROUGH, ARM9_COAT, ARM9_SPECKLE, n)
    )


_build_arms_r9_run1 = build_arms_r9


def build_arms_r9(mats, scene, p, PB):
    p = dict(p)
    p['nub_r'] = ARM9['nub_r']
    out = _build_arms_r9_run1(mats, scene, p, PB)
    # push the nubs to the paw surface (run1 placed them at 0.92 of the paw radii)
    pr = p['paw_r']
    for ob in out:
        if ob.name.startswith('pb_nub_'):
            side = ob.name[7]
            sx = -1 if side == 'l' else 1
            k = int(ob.name[8])
            ang = math.radians(-30 + 30 * k)
            nd = Vector((sx * math.sin(ang) * 0.9, -math.cos(ang) * 0.70, -0.80)).normalized()
            pc = Vector(ob.location) - Vector((nd.x * pr[0], nd.y * pr[1], nd.z * pr[2])) * 0.92
            ob.location = pc + Vector((nd.x * pr[0], nd.y * pr[1], nd.z * pr[2])) * ARM9['nub_out']
    print('R9 run5: nubs r %.4f at %.2f of the paw radii' % (ARM9['nub_r'], ARM9['nub_out']))
    return out


def pre_build(PB):
    _pre_build_r8final(PB)
    PB.build_arms = lambda mats, scene, p=PB.P: build_arms_r9(mats, scene, p, PB)
    print('R9 run5: build_arms -> swept limb (nubs %.4f)' % ARM9['nub_r'])


# ── run6: TAIL — as plush as the body, mint bands bleeding through the fur ───────────────────
# run5 kept (front eye_frac +7.3 %, side numbers back at the base's structure; nubs read as three
# short toes, the glitter is gone). Critic: tail reads as a striped tube with a thin hair layer;
# anchor tail is as fluffy as the body with the mint bands bleeding softly through fur. Measured
# on the side views: the anchor's column is ~0.23 ball-widths of airy fur at mid-height, ours
# ~0.16 — TAIL5 gives 0.6 x the core radius (23 mm at the base, 37 at the bulge, capped by a 45 mm
# hair) in LOCK's fat petals (clump 0.85 / shape 0.40), and TAIL_RINGS' 8 %-of-a-period edge cuts
# the mint on and off like tape. One change, four knobs on the tail alone (nothing on pb_body):
#  * length 1.0 x the core radius (hair_len 0.065 so the bulge's 62 mm is not capped; tip 12 mm,
#    density fade at s > 0.97 unchanged so the tip stays a point);
#  * band edge 0.08 -> 0.30 of a period (mint_frac 0.42 unchanged): the ring attribute the hair
#    inherits grades over ~a third of each segment, so white strands cross into the mint;
#  * the tail's own particle system: clump 0.60 / shape 0.20, 1000 parents x 60 children (the
#    body's lock coat is a mesh instance layer and is untouched);
#  * undercoat 16 -> 24 mm.
# Side aspect (-5.1 %, the width is short) and tail_above (-5.5 %) both move toward the anchor when
# the column widens; checked on the run.
TAIL5.update({'len_per_r': 1.00, 'hair_len': 0.065, 'count': 1000, 'child': 60})
PARAMS.update(
    {'tail_hair_len': TAIL5['hair_len'], 'tail_hair_count': TAIL5['count'], 'tail_hair_child': TAIL5['child']}
)
TAIL_RINGS.update({'edge': 0.30})
TAIL_UNDER.update({'len': 0.024})
TAIL9 = {'clump': 0.60, 'shape': 0.20}


def _tail_plush9():
    t = _ob('pb_tail_00')
    if t is None:
        return
    for ps in t.particle_systems:
        s = ps.settings
        if ps.name == 'pb_tail_tufts':
            s.clump_factor = TAIL9['clump']
            s.clump_shape = TAIL9['shape']
            print(
                'R9 run6: %s %d x %d, hair %.3f, clump %.2f shape %.2f'
                % (ps.name, s.count, s.rendered_child_count, s.hair_length, s.clump_factor, s.clump_shape)
            )
        elif ps.name == 'pb_tail_under':
            print('R9 run6: %s %d x %d, hair %.3f' % (ps.name, s.count, s.rendered_child_count, s.hair_length))


_post_build_r9_run2 = post_build


def post_build(scene, result, PB):
    _post_build_r9_run2(scene, result, PB)
    _tail_plush9()
    bpy.context.view_layer.update()


print(
    'R9 run6: tail len_per_r %.2f hair %.3f, %d x %d, band edge %.2f, under %.3f'
    % (TAIL5['len_per_r'], TAIL5['hair_len'], TAIL5['count'], TAIL5['child'], TAIL_RINGS['edge'], TAIL_UNDER['len'])
)


# ── run7: tail length TAPERED along s; furkey a deeper amber ────────────────────────────────
# run6 by eye: the tail is plush and the bands bleed — kept. Harness: side aspect -5.1 -> -2.7 %
# (passes), front eye_frac +5.2 %, but side tail_above 0.209 -> 0.199 (gate floor 0.203): measured on
# the side alphas, the tail column at the 0.55-width crossing rows (the UPPER column, s > 0.8) went
# 91 -> 117 px wide and pulled the crossing up 6 rows; h +2. The anchor's upper column tapers to a
# point with short fur; its bulge is the plush part. So the length factor follows s: 1.0 x r up to
# s 0.55, linear to 0.60 x r (run5's value) from s 0.85 on — the bulge keeps run6's 62 mm, the top
# 15 % returns to run5's silhouette.
# Coat, lit side (critic [minor][light]): front flankR (228,224,206) b+10 vs anchor (249,223,139)
# b+43 at the same L. furkey (fur-only, az 30 / el 70) is 3800 K (1.0,0.62,0.33): on the (0.87,0.94,
# 0.88) tip Filmic's shoulder flattens R/G 1.5 to a display 1.02. Deeper amber (1.0,0.48,0.18) with
# W 16 -> 19 so G (the luminance carrier) stays: scene R/G 1.9, R/B 5.1. Only furkey moves; the
# crown apex is coolfur's (mint), the shadow side fillL/rimL's. Crown clipping checked.
TAIL9.update({'taper_s0': 0.55, 'taper_s1': 0.85, 'len_hi': 1.00, 'len_lo': 0.60})


def _tail_len_r5(p):
    t = _ob('pb_tail_00')
    if t is None:
        return
    n, S = p['tail_rings'], p['tail_sides']
    vg_l = t.vertex_groups.get('tail_len')
    vg_d = t.vertex_groups.get('tail_density')
    if vg_l is None:
        return
    T = TAIL5
    Q = TAIL9

    def lpr(s):
        u = (s - Q['taper_s0']) / (Q['taper_s1'] - Q['taper_s0'])
        u = min(1.0, max(0.0, u))
        return Q['len_hi'] + (Q['len_lo'] - Q['len_hi']) * u

    lo = hi = None
    for i in range(n - 1):
        s = i / float(n - 1)
        w = max(T['min_w'], min(1.0, lpr(s) * _radius(s, p) / p['tail_hair_len']))
        d = 1.0 if s <= T['tip_fade'] else max(0.0, 1.0 - (s - T['tip_fade']) / (1.0 - T['tip_fade']))
        lo = w if lo is None else min(lo, w)
        hi = w if hi is None else max(hi, w)
        for j in range(S):
            vi = 1 + i * S + j
            vg_l.add([vi], w, 'REPLACE')
            if vg_d is not None:
                vg_d.add([vi], d, 'REPLACE')
    vg_l.add([0], max(T['min_w'], min(1.0, lpr(0.0) * _radius(0.0, p) / p['tail_hair_len'])), 'REPLACE')
    tip = 1 + (n - 1) * S
    if tip < len(t.data.vertices):
        vg_l.add([tip], T['min_w'], 'REPLACE')
        if vg_d is not None:
            vg_d.add([tip], 0.0, 'REPLACE')
    print(
        'R9 run7 tail locks: %.2f x r to s %.2f -> %.2f x r from s %.2f, hair %.3f m, len weights %.2f..%.2f'
        % (Q['len_hi'], Q['taper_s0'], Q['len_lo'], Q['taper_s1'], p['tail_hair_len'], lo, hi)
    )


AMBER9 = (1.00, 0.48, 0.18)
LIGHTS['furkey'].update(rgb=AMBER9, W=19.0)
print('R9 run7: furkey %s %.1f W' % (AMBER9, LIGHTS['furkey']['W']))


# ── run8 (FINAL): furkey REVERTED to the production 3800 K / 16 W; tail taper kept ────────────
# run7: side tail_above 0.199 -> 0.211 (-4.3 %, passes; base -4.9 %), side aspect -3.3 % (passes;
# the base failed at -5.1 %), front eye_frac +6.4 % (base +8.0 %): the taper did its job and the
# tail stays plush in every view. The amber furkey did not: front flankR b* +10 -> +13 only (the
# anchor's +43 sits past Filmic's shoulder), and the PROFILE coat — which the side anchor keeps
# pale mint-white — went yellower (side fur median, body pixels only, same gate: base 11.4, run6
# 12.0, run7 13.9 from the anchor). The two anchors disagree about that flank; the light round
# already met this wall. Reverted; nothing else in the coat's lighting is touched by this file.
# Fur-gate bookkeeping (body pixels only, ROI-free): front 7.3 (base) -> 7.5, side 11.4 -> 12.0 —
# the 0.6 in profile is the glossy arm's highlights entering the pale gate, not the coat.
LIGHTS['furkey'].update(rgb=K3800, W=16.0)
print(
    'R9 FINAL: furkey back to %s %.1f W; arms (swept limb + pb_skin_arm), feet (pb_foot9), limb lights, plush tapered tail'
    % (K3800, LIGHTS['furkey']['W'])
)


print('R9 MERGE run1: face(run6) + coat(r9) composed; no merge-only edits')


# ── R9 MERGE run2: TAILSIDE — a white tail-only light from the profile-camera side ──────────
# run1 (base + face + coat, no merge edits) is a coherent picture in all four views and both
# gated side shape numbers now pass (aspect -3.1 %, tail_above +2.5 %), but the side fur gate
# moved the wrong way on a STABLE basis (harness fur gate, no ROI, split by the tail ID):
#   side  all 14.9 -> 19.0 from the anchor, body 11.4 -> 12.7, tail 32.2 -> 36.1 (tail L 191 -> 187)
#   front all  7.1 ->  7.3,                 body  7.3 ->  8.1, tail 11.2 -> 13.7
# i.e. the coat's plusher tail exposes more of the tail's SHADED hair to the gate. The anchor's
# profile tail is L221 white; ours is lit by 'tailfill' alone (upper-left-FRONT, 30 W): the
# side camera at +x sees its unlit face. The coat round's recorded next lever (untried there):
# a tail-only white disk from +x. Placed high and slightly BEHIND the centre so the body does not
# shadow the tail column (which stands at ~(-0.3, +0.4) S): pos (1.0, 0.8, 0.9) S, aimed at the
# tail's own bbox centre, 14 W x ek, disk 0.7 S, white, receivers pb_tail* only (the existing
# 'pb_tail_receivers' collection), blockers = 'pb_blockers_nofloor' like the coat's limb lights.
# In the front view it lights the tail's inner (+x) face only. Nothing else receives it.
TAILSIDE9 = dict(pos=(1.0, 0.8, 0.9), W=14.0, size=0.70, rgb=(1.0, 1.0, 1.0))


def _tailside9(scene, centre, size):
    if bpy.data.objects.get('tailside') is not None:
        return
    c = Vector(centre)
    S = float(size)
    ek = (S / S_REF) ** 2
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    n = 0
    for ob in scene.collection.objects:
        if ob.type == 'MESH' and ob.name.startswith('pb_tail'):
            for v in ob.bound_box:
                w = ob.matrix_world @ Vector(v)
                lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
                hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
            n += 1
    aim = (lo + hi) / 2 if n else c
    T = TAILSIDE9
    o = _area(scene, 'tailside', c + Vector(T['pos']) * S, T['W'] * ek, T['size'] * S, aim, T['rgb'], glossy=True)
    _link_prefix(scene, o, 'pb_tail_receivers', ('pb_tail',))
    blockers = bpy.data.collections.get('pb_blockers_nofloor')
    if blockers is not None:
        o.light_linking.blocker_collection = blockers
    print(
        'R9 MERGE run2: tailside %.1f W x %.2f at %s aimed at tail centre %s (%d tail objects)'
        % (T['W'], ek, tuple(round(v, 3) for v in o.location), tuple(round(v, 3) for v in aim), n)
    )


_lighting_r9_merge1 = lighting


def lighting(scene, centre, size, aim):
    _lighting_r9_merge1(scene, centre, size, aim)
    _tailside9(scene, centre, size)


print('R9 MERGE run2: tailside light %s' % (TAILSIDE9,))


# ═════════════════════════════════════════════════════════════════════════════
# R10 FACE (lookdev3 round 2 / r2_face) — the face cluster on r1_merge/merge2.py (R9 MERGE run2).
# Every name below shadows the earlier binding; the hook wrappers capture the R9 functions.
#
# run1 — PER-VIEW GAZE: the pupil (and its catchlight) face the active camera.
# Critic ([major], supersedes): "profile pupil reads as an edge-on sliver; the anchor shows a broad
# dark pupil facing the camera in the side cell (its gaze tracks the camera in every cell). Keep
# EYE_DEPTH 1.00 and pupil_r; before each render rotate each pupil cap so its axis points at the
# active camera position."
# Measured on the base (r1_face probe, ID pass): the pupil is a conformal patch at planar
# (0.258, -0.063) r = 15 deg nasal of the lens axis (PUPIL_CONVERGE 0.45 of the world -Y line);
# the side camera (az 90, el 6) sits 57 deg temporal of the right eye's axis (35.4 out / 8 up), so
# it sees that patch 72 deg off its own axis: a sliver 0.95 er toward the front limb. Geometry of
# the sphere seen from 57 deg: the R8 ring's inner wall (rho 0.92 = polar 67 deg) hides polar
# > 67, so the visible cap spans image positions -0.17 er (behind the sphere's disc centre, the
# ring edge) .. +1.0 er (the front limb): the camera-facing point is at the REAR of the bulge —
# which is where anchor_side keeps its pupil (dark disc rear/top, amber crescent front-bottom).
# WHAT CHANGES (camera hook, once per view, before the beauty/alpha/ID renders of that view):
#  * pupil = a spherical cap of angular radius asin(Rp) = 26.9 deg (Rp 0.453 r: the front pupil
#    width is unchanged, the cap seen face-on projects 2 Rp er) about the unit direction u from the
#    eye centre to the camera, in eye-local coords; u is clamped to GAZE_MAX 42 deg from the lens
#    axis (42 + 27 = 69 ~ the ring's 67: the cap never dives under the lid, and in profile the
#    clamp is what keeps the whole cap in the visible region: at 57 deg the cap would lose its
#    rear third under the ring wall). Per view: front 35 deg (no clamp: the pupil sits at the
#    sphere's disc centre = 0.56 er from the nasal wall, ~0.1 iris-widths nasal of the aperture
#    centre — cell_11's 0.10); side 57 -> 42 (pupil 15 deg in front of the camera-facing point,
#    image -0.17..+0.67 er of the visible -0.17..+1.0); q45 near eye 12 deg, far eye 78 -> 42.
#  * the iris shader's pupil centre follows: r2 (planar distance from a fixed planar centre) is
#    replaced by sin(angle to u) = sqrt(1 - (n.u)^2), which equals the planar radius for a pupil on
#    the axis (so the painted disc, the umber collar and the fibres keep their sizes) — three
#    named Value nodes ('gaze_x/y/z') per eye material that the hook sets; the spoke angle's
#    planar offsets (dx, dz) take the same u.
#  * catchlight: the R5 glint patch (lp + 0.24 er toward the viewer's upper-left, 1.5 x 0.85
#    glint_r) becomes a cap 13.9 deg (asin 0.24) from u toward the CAMERA's upper-left, long axis
#    along camera-right, same lift / weight attribute / material — the one big soft upper-left
#    reflection stays on the pupil in every view.
# Nothing else moves: lens, ring, collar, iris bands, eyelight, fur, mouth, plate.
# ═════════════════════════════════════════════════════════════════════════════
GAZE9 = {
    'max_deg': 42.0,
    'glint_off': GLINT['off'],
    'glint_ul': (-1.0, 0.9),
}  # glint_ul = (right, up) in the camera frame


def _cap_on_sphere(u, alpha, er, lift, dome, segs, K, wname, e1=None, A=1.0, B=1.0):
    """Elliptical spherical cap about the unit direction u (eye-LOCAL), angular semi-axes
    alpha x A along e1 and alpha x B along u x e1; lifted along the normal by lift + dome x (1 - r^2).
    Optional per-point float attribute (1 - r^2)^GLINT['pow'] (same as _patch_on_lens)."""
    u = Vector(u).normalized()
    if e1 is None:
        e1 = Vector((0.0, 0.0, 1.0)).cross(u)
        if e1.length < 1e-4:
            e1 = Vector((1.0, 0.0, 0.0)).cross(u)
    e1 = Vector(e1) - u * Vector(e1).dot(u)
    e1 = e1.normalized() if e1.length > 1e-6 else Vector((1.0, 0.0, 0.0)).cross(u).normalized()
    e2 = u.cross(e1).normalized()
    verts, ws = [], []

    def P(r, th, w):
        a = alpha * r * A * math.cos(th)
        b = alpha * r * B * math.sin(th)
        ang = math.sqrt(a * a + b * b)
        n = u if ang < 1e-9 else (u * math.cos(ang) + ((e1 * a + e2 * b) / ang) * math.sin(ang))
        return tuple(n * (er + lift + dome * w))

    verts.append(P(0.0, 0.0, 1.0))
    ws.append(1.0)
    for k in range(1, K + 1):
        r = k / float(K)
        for j in range(segs):
            th = 2.0 * math.pi * j / segs
            verts.append(P(r, th, 1.0 - r * r))
            ws.append((1.0 - r * r) ** GLINT['pow'])
    faces = []
    for j in range(segs):
        faces.append((0, 1 + j, 1 + (j + 1) % segs))
    for k in range(K - 1):
        a0 = 1 + k * segs
        a1 = a0 + segs
        for j in range(segs):
            j2 = (j + 1) % segs
            faces.append((a0 + j, a1 + j, a1 + j2, a0 + j2))
    me = bpy.data.meshes.new('pb_cap')
    me.from_pydata(verts, [], faces)
    me.validate()
    for poly in me.polygons:
        poly.use_smooth = True
    if wname:
        at = me.attributes.new(name=wname, type='FLOAT', domain='POINT')
        for i, w in enumerate(ws):
            at.data[i].value = w
    return me


_eye_shader5_r9 = eye_shader5


def eye_shader5(mat, lp, Rp):
    """R10 run1: the R8 shader, then the pupil metric re-based on a gaze direction (Value nodes)."""
    # the right eye's material is a COPY of the left's (R5 eyes_post) with the left graph left
    # dangling inside it: work only on the nodes this call adds, and drop copied gaze nodes.
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    for nm in ('gaze_x', 'gaze_y', 'gaze_z'):
        stale = nodes.get(nm)
        if stale is not None:
            nodes.remove(stale)
    before = set(n.name for n in nodes)
    _eye_shader5_r9(mat, lp, Rp)
    fresh = [n for n in nodes if n.name not in before]
    sq = [n for n in fresh if n.type == 'MATH' and n.operation == 'SQRT']
    sep = [n for n in fresh if n.type == 'SEPXYZ']
    if not (len(sq) == 1 and len(sep) == 1):
        raise RuntimeError(f'R10 gaze: eye graph shape {len(sq)} {len(sep)}')
    sq, sep = sq[0], sep[0]
    nx, ny, nz = sep.outputs['X'], sep.outputs['Y'], sep.outputs['Z']
    u0 = Vector((lp.x, -math.sqrt(max(0.0, 1.0 - lp.x**2 - lp.y**2)), lp.y)).normalized()
    vals = []
    for nm, v in (('gaze_x', u0.x), ('gaze_y', u0.y), ('gaze_z', u0.z)):
        vn = nodes.new('ShaderNodeValue')
        vn.name = nm
        vn.label = nm
        vn.outputs[0].default_value = v
        vals.append(vn.outputs[0])
    dot = _math(
        nt,
        'ADD',
        a=_math(nt, 'ADD', a=_math(nt, 'MULTIPLY', a=nx, b=vals[0]), b=_math(nt, 'MULTIPLY', a=ny, b=vals[1])),
        b=_math(nt, 'MULTIPLY', a=nz, b=vals[2]),
    )
    r_ang = _math(
        nt,
        'SQRT',
        a=_math(nt, 'MAXIMUM', a=_math(nt, 'SUBTRACT', va=1.0, b=_math(nt, 'MULTIPLY', a=dot, b=dot)), vb=0.0),
    )
    n_re = 0
    for lk in [l for l in links if l.from_node == sq]:
        links.new(r_ang, lk.to_socket)
        n_re += 1
    # the spoke-angle offsets: SUBTRACT nodes fed by the normal's X / Z with a constant second input
    n_sub = 0
    for n in fresh:
        if (
            n.type == 'MATH'
            and n.operation == 'SUBTRACT'
            and n.inputs[0].is_linked
            and n.inputs[0].links[0].from_node == sep
            and not n.inputs[1].is_linked
        ):
            src = n.inputs[0].links[0].from_socket
            if src == nx:
                links.new(vals[0], n.inputs[1])
                n_sub += 1
            elif src == nz:
                links.new(vals[2], n.inputs[1])
                n_sub += 1
    print(
        'R10 gaze shader %s: pupil metric -> sin(angle to gaze) (%d links re-routed, %d offsets), gaze0 (%.3f,%.3f,%.3f)'
        % (mat.name, n_re, n_sub, u0.x, u0.y, u0.z)
    )


def _gaze9(cam, view_id):
    p = _P
    er = p['eye_r']
    Rp = p['pupil_r'] / er
    alpha = math.asin(min(0.999, Rp))
    gmax = math.radians(GAZE9['max_deg'])
    M = cam.matrix_world
    cam_pos = M.translation
    R_cam = (M.to_3x3() @ Vector((1.0, 0.0, 0.0))).normalized()
    U_cam = (M.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    ul = GAZE9['glint_ul']
    e_w = (R_cam * ul[0] + U_cam * ul[1]).normalized()
    axis_l = Vector((0.0, -1.0, 0.0))
    for side in ('l', 'r'):
        c = _EYES.get('c_' + side)
        q = _EYES.get('q_' + side)
        pup, gli, eye = _ob('pb_pupil_' + side), _ob('pb_glint_' + side), _ob('pb_eye_' + side)
        if c is None or q is None or pup is None or eye is None:
            continue
        qi = q.inverted()
        v = (qi @ (cam_pos - c)).normalized()
        cphi = max(-1.0, min(1.0, v.dot(axis_l)))
        phi = math.acos(cphi)
        if phi > gmax:
            t = v - axis_l * cphi
            t = t.normalized() if t.length > 1e-6 else Vector((1.0, 0.0, 0.0))
            u = (axis_l * math.cos(gmax) + t * math.sin(gmax)).normalized()
        else:
            u = v
        _replace_mesh(pup, _cap_on_sphere(u, alpha, er, PUPIL_LIFT * er, PUPIL_DOME * er, 32, 6, None))
        # catchlight toward the camera's upper-left of the pupil, long axis along camera-right
        e_l = qi @ e_w
        e_p = e_l - u * e_l.dot(u)
        e_p = e_p.normalized() if e_p.length > 1e-6 else Vector((0.0, 0.0, 1.0)).cross(u).normalized()
        beta = math.asin(min(0.999, GAZE9['glint_off']))
        ug = (u * math.cos(beta) + e_p * math.sin(beta)).normalized()
        A = math.asin(min(0.999, p['glint_r'] * GLINT['scale'][0] / er))
        B = math.asin(min(0.999, p['glint_r'] * GLINT['scale'][2] / er))
        if gli is not None:
            _replace_mesh(
                gli, _cap_on_sphere(ug, 1.0, er, GLINT['lift'] * er, 0.0, 32, 8, 'glint_w', e1=qi @ R_cam, A=A, B=B)
            )
        nt = eye.data.materials[0].node_tree
        for nm, val in (('gaze_x', u.x), ('gaze_y', u.y), ('gaze_z', u.z)):
            n = nt.nodes.get(nm)
            if n is not None:
                n.outputs[0].default_value = val
        print(
            'R10 gaze %s eye_%s: camera %.1f deg off the lens axis -> pupil at %.1f deg (%.2f,%.2f,%.2f local), %.1f deg from the camera line; glint %.1f deg toward upper-left'
            % (
                view_id,
                side,
                math.degrees(phi),
                math.degrees(math.acos(max(-1.0, min(1.0, u.dot(axis_l))))),
                u.x,
                u.y,
                u.z,
                math.degrees(math.acos(max(-1.0, min(1.0, u.dot(v))))),
                math.degrees(beta),
            )
        )
    bpy.context.view_layer.update()


_camera_r9merge = camera


def camera(cam, cam_data, view_id):
    _camera_r9merge(cam, cam_data, view_id)
    _gaze9(cam, view_id)


print(
    'R10FACE run1: per-view gaze, cap %.1f deg, clamp %.0f deg, glint off %.2f'
    % (math.degrees(math.asin(PARAMS['pupil_r'] / PARAMS['eye_r'])), GAZE9['max_deg'], GAZE9['glint_off'])
)


# ── run2: CONVERGENCE 0.82 — the pupil turns 82 % of the way from its rest axis to the camera ──
# run1 (probe, ID pass): profile pupil/(iris+pupil) 0.097 -> 0.335, the dark disc faces the side
# camera with the catchlight on its upper-left; q45's far eye shows a real pupil at the nasal
# ring edge. Front: the pupils moved from 0.02-0.05 eye-widths TEMPORAL of the aperture centre to
# 0.146 / 0.177 NASAL (close-up 0.168 / 0.173); cell_11 reads ~0.10 (R9 run2's measure). The
# shift per degree of gaze rotation measured on the run: 0.165 / sin 18.5 = 0.52 and 0.228 /
# sin 25 = 0.54 eye-widths per er, so 0.10 needs the front pupils 5-8 deg short of the camera
# line = 0.82 x the 33.5 / 40.4 deg offsets (close-up 37.8 -> 31 deg: 0.17 - 0.53 sin 6.8 = 0.11).
# The side (61 deg) and q45's far eye (85 deg) still hit the 42 deg clamp, the q45 near eye goes
# 12.9 -> 10.6 deg — the profile pupil is untouched by this.
GAZE9['converge'] = 0.82
_gaze9_run1 = _gaze9


def _gaze9(cam, view_id):
    """run2: same as run1, the gaze angle scaled by GAZE9['converge'] before the clamp."""
    p = _P
    er = p['eye_r']
    Rp = p['pupil_r'] / er
    alpha = math.asin(min(0.999, Rp))
    gmax = math.radians(GAZE9['max_deg'])
    cv = GAZE9.get('converge', 1.0)
    M = cam.matrix_world
    cam_pos = M.translation
    R_cam = (M.to_3x3() @ Vector((1.0, 0.0, 0.0))).normalized()
    U_cam = (M.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    ul = GAZE9['glint_ul']
    e_w = (R_cam * ul[0] + U_cam * ul[1]).normalized()
    axis_l = Vector((0.0, -1.0, 0.0))
    for side in ('l', 'r'):
        c = _EYES.get('c_' + side)
        q = _EYES.get('q_' + side)
        pup, gli, eye = _ob('pb_pupil_' + side), _ob('pb_glint_' + side), _ob('pb_eye_' + side)
        if c is None or q is None or pup is None or eye is None:
            continue
        qi = q.inverted()
        v = (qi @ (cam_pos - c)).normalized()
        cphi = max(-1.0, min(1.0, v.dot(axis_l)))
        phi = math.acos(cphi)
        t = v - axis_l * cphi
        t = t.normalized() if t.length > 1e-6 else Vector((1.0, 0.0, 0.0))
        ang = min(gmax, phi * cv)
        u = (axis_l * math.cos(ang) + t * math.sin(ang)).normalized()
        _replace_mesh(pup, _cap_on_sphere(u, alpha, er, PUPIL_LIFT * er, PUPIL_DOME * er, 32, 6, None))
        e_l = qi @ e_w
        e_p = e_l - u * e_l.dot(u)
        e_p = e_p.normalized() if e_p.length > 1e-6 else Vector((0.0, 0.0, 1.0)).cross(u).normalized()
        beta = math.asin(min(0.999, GAZE9['glint_off']))
        ug = (u * math.cos(beta) + e_p * math.sin(beta)).normalized()
        A = math.asin(min(0.999, p['glint_r'] * GLINT['scale'][0] / er))
        B = math.asin(min(0.999, p['glint_r'] * GLINT['scale'][2] / er))
        if gli is not None:
            _replace_mesh(
                gli, _cap_on_sphere(ug, 1.0, er, GLINT['lift'] * er, 0.0, 32, 8, 'glint_w', e1=qi @ R_cam, A=A, B=B)
            )
        nt = eye.data.materials[0].node_tree
        for nm, val in (('gaze_x', u.x), ('gaze_y', u.y), ('gaze_z', u.z)):
            n = nt.nodes.get(nm)
            if n is not None:
                n.outputs[0].default_value = val
        print(
            'R10 gaze %s eye_%s: camera %.1f deg off the lens axis -> pupil at %.1f deg (x%.2f, clamp %.0f), %.1f deg from the camera line'
            % (
                view_id,
                side,
                math.degrees(phi),
                math.degrees(ang),
                cv,
                GAZE9['max_deg'],
                math.degrees(math.acos(max(-1.0, min(1.0, u.dot(v))))),
            )
        )
    bpy.context.view_layer.update()


print('R10FACE run2: gaze convergence %.2f (clamp %.0f deg)' % (GAZE9['converge'], GAZE9['max_deg']))


# ── run3: the SNOUT — a small forward-pointing bill, not a ball ────────────────────────────
# run2 kept (front pupils 0.085 / 0.116 eye-widths nasal, close-up 0.101 / 0.103; profile pupil
# fraction 0.335; q45 near eye 2.3 deg off the camera line).
# Critic [minor][skin]: "anchor is a SMALL salmon snout, upper lip protruding over the lower".
# Measured (ID pass, run2): in profile the mouth (pad + lower lip) is 0.70 eye-widths long and
# 0.74 tall — a ball under the eye (anchor_side: a bill ~0.4 ew long, ~0.45 ew tall at the base,
# tapering to a tip that points forward and a little down); in front it is 1.02 eye-widths wide
# and 0.57 tall against anchor_full's 0.67 / 0.45 and cell_11's 0.79 / 0.52. Cause: the R5 pad is an
# 82 x 48 x 44 mm ellipsoid whose profile is a circle.
#  * BEAK_R (0.041, 0.024, 0.022) -> (0.030, 0.024, 0.019): 60 mm wide (0.75 of the visible eye),
#    38 tall, the 24 mm half-depth and the 32 mm protrusion (BEAK_OUT) kept — the bill's length.
#  * the pad mesh is deformed in its normalized frame (x/y/z over the baked radii): for frontness
#    f = max(0, -y) the half-height goes h = 1 - 0.65 f^1.5 (tip 0.35 x 19 = 6.7 mm) and the whole
#    section drops 0.50 f^2 (9.5 mm at the tip): the top surface slopes down to a thin tip, the
#    profile is a wedge. Vertex edit on pb_lip before the cavity boolean evaluates.
#  * aperture cut follows: CUT_R (0.030, 0.012, 0.0095) -> (0.023, 0.012, 0.0075), CUT_DZ -0.006 ->
#    -0.004 (ceiling stays at +3.5 mm, so TEETH_DZ 0.0008 is unchanged); TEETH_SPAN 0.036 -> 0.028;
#    lower lip (0.026, 0.008, 0.006) -> (0.020, 0.007, 0.005) at dy 0.008 / dz -0.012 so it fills the
#    floor of the opening 1-8 mm behind the upper lip's tip; tongue (0.010, 0.005, 0.0025) at dz
#    -0.0075 on the cavity floor.
SNOUT10 = {'taper': 0.65, 'taper_pow': 1.5, 'droop': 0.50}
BEAK_R = (0.030, 0.024, 0.019)
CUT_R = (0.023, 0.012, 0.0075)
CUT_DZ = -0.004
TEETH_SPAN = 0.028
LOWLIP_R = (0.020, 0.007, 0.005)
LOWLIP_DY = 0.008
LOWLIP_DZ = -0.012
TONGUE_R = (0.010, 0.005, 0.0025)
TONGUE_DZ = -0.0075


def _snout10(scene, result, PB):
    lip = _ob('pb_lip')
    if lip is None:
        return
    me = lip.data
    bx = max(abs(v.co.x) for v in me.vertices)
    by = max(abs(v.co.y) for v in me.vertices)
    bz = max(abs(v.co.z) for v in me.vertices)
    S = SNOUT10
    zmin = 1e9
    zmax = -1e9
    for v in me.vertices:
        n = Vector((v.co.x / bx, v.co.y / by, v.co.z / bz))
        f = max(0.0, min(1.0, -n.y))
        h = 1.0 - S['taper'] * (f ** S['taper_pow'])
        z = n.z * h - S['droop'] * f * f
        v.co.z = z * bz
        if f > 0.98:
            zmin = min(zmin, z)
            zmax = max(zmax, z)
    me.update()
    print(
        'R10FACE run3 snout: pad %s (mm %.0f x %.0f x %.0f), tip half-height %.1f mm (z %.1f..%.1f mm), droop %.1f mm; cut %s dz %.4f; lowlip %s dy %.3f dz %.3f'
        % (
            BEAK_R,
            BEAK_R[0] * 2000,
            BEAK_R[1] * 2000,
            BEAK_R[2] * 2000,
            (1.0 - S['taper']) * BEAK_R[2] * 1000,
            zmin * BEAK_R[2] * 1000,
            zmax * BEAK_R[2] * 1000,
            S['droop'] * BEAK_R[2] * 1000,
            CUT_R,
            CUT_DZ,
            LOWLIP_R,
            LOWLIP_DY,
            LOWLIP_DZ,
        )
    )


_post_build_r9merge = post_build


def post_build(scene, result, PB):
    _post_build_r9merge(scene, result, PB)
    _snout10(scene, result, PB)
    bpy.context.view_layer.update()


print('R10FACE run3: snout %s, BEAK_R %s CUT_R %s' % (SNOUT10, BEAK_R, CUT_R))


# ── run4 / run5 (REJECTED, kept in face_run5_rejected.py): a taller aperture (cut z 10 mm, ceiling
# held) with the lower lip dropped to a ledge, then the tongue hidden and the ledge thinned. The
# dark interior stayed 8-12 % of the mouth's pixels (anchors 53-68 %): the cavity is 12 mm deep and
# front-lit, and the opening is bounded by the tooth row and the lower lip, so the visible dark band
# is ~8 mm whatever the cut; the lower lip hung 3-8 mm under the tapered pad as a second bump (run4)
# and, moved forward and thinned, floated detached under the snout in every view (run5). A wide-open
# anchor mouth needs a dropped lower jaw built as its own part — not a knob tweak. Final = run3.
print(
    'R10FACE FINAL: per-view gaze (clamp %.0f deg, convergence %.2f) + snout %s BEAK_R %s'
    % (GAZE9['max_deg'], GAZE9['converge'], SNOUT10, BEAK_R)
)


# ═════════════════════════════════════════════════════════════════════════════
# R10 COAT (lookdev3 round 2 / r2_coat) — the coat's colour temperature and the tail's bands.
# Base = lookdev3/r1_merge/merge2.py (R9 face + coat + tailside). Base measurements (probe4 zones,
# sRGB / HSV of the zone median; the anchor in brackets):
#   front flankR (173,148,88) S0.49 [(201,127,59) S0.71]; chestLR (184,157,119) S0.35 [(230,166,83) S0.64]
#   front crown (237,245,240) S0.03, 0.7 % >=250, 54.5 % >=235 [(218,245,225) S0.11 H136, 0 % / 8.6 %]
#   front crownUL (229,240,231) L239 [(147,209,206) L204 — the anchor's shadow side is a dim teal]
#   side flank (189,183,154) L190 [(131,146,117) L149]; rear L188 [L120]; front_lo S0.33 [S0.62]
#   tail (probe_tail.py, geodesic bins, side view): S 0.07-0.16 along the whole tail, one peak 0.36 at
#   the tip [anchor: 7-8 S oscillations 0.15 <-> 0.45-0.56 root to tip]
# Filmic MHC probe (filmic_probe.py): flank gold (204,134,53) S0.74 <- scene-linear (0.8,0.20,0.04),
# i.e. a light of R/G ~4 on the near-neutral lock tip (0.87,0.94,0.88) with NOTHING neutral under
# it; the crown (219,244,237) S0.10 <- (1.2,3.6,2.4). The 3800 K furkey (1.0,0.62,0.33) at az 30 /
# el 70 lights BOTH flanks at cos ~0.3 with R/G 1.6 — that spill is what keeps the flank cream.
# ═════════════════════════════════════════════════════════════════════════════

# ── run1: GOLDKEY — a fur-only deep-amber key low right-front; furkey -0.8 stop; coolfur up ──
# The critic's structure (warm key from lower-right-front, mint fill from the top-left) as three
# coupled moves on FUR-ONLY lights (the face's lights — key / facelight / faceR / eyelight — and the
# rims are untouched, so the face agent's zones do not move):
#  * 'goldkey' NEW: az 32 / el 20 / 1.5 S (R8 run6's argument: az 30 lights the front's flankR /
#    chestLR at cos ~0.55-0.7 and the side's front_lo at ~0.7 while the side camera's +x flank gets
#    cos ~0.45 — the side anchor keeps that flank a mid grey-green), disk 0.40 S, 14 W, (1.0,0.26,0.06)
#    = R/G 3.8 / R/B 17 (between the anchor's flankR R/G 4 and chestLR 3.2 in scene-linear).
#  * furkey 16 -> 9 W: keeps the crown-right cream (anchor crownUR (241,248,208)) but its cos-0.3
#    spill on the flank falls under the gold (12.6 vs 2.7 W-eq: lin R/G ~3.2 on the flank).
#  * coolfur 2.2 -> 3.5 W and greener (0.42,1.0,0.64): the crown loses ~40 % of its light with
#    furkey; the top light replaces it in mint (anchor crown H136 — MINT8's B 0.75 gave H164).
GOLD10 = (1.00, 0.26, 0.06)
MINT10 = (0.42, 1.00, 0.64)
_GOLD_POS = _sph(32, 20, 1.5)
LIGHTS['goldkey'] = dict(pos=_GOLD_POS, W=14.0, size=0.40, rgb=GOLD10, aim='low')
FUR_ONLY = tuple(FUR_ONLY) + ('goldkey',)
LIGHTS['furkey'].update(W=9.0)
LIGHTS['coolfur'].update(W=3.5, rgb=MINT10)
print(
    'R10 run1: goldkey %s %.1f W at %s (fur-only); furkey %.1f W; coolfur %.1f W %s'
    % (
        GOLD10,
        LIGHTS['goldkey']['W'],
        tuple(round(v, 3) for v in _GOLD_POS),
        LIGHTS['furkey']['W'],
        LIGHTS['coolfur']['W'],
        MINT10,
    )
)


# ── run2: goldkey -2 stops, CLOSE and LOW; furkey 5 W; coolfur 4.5 W ────────────────────────
# run1 (goldkey 14 W / 1.5 S / el 20): the structure works at thumbnail — front lab_fur 14 -> 7,
# front near-white 30 -> 33 %, q45 near-white 36 -> 43 % (anchor 45), crown clip250 0.7 -> 0.0 %,
# >=235 54 -> 45 %, crownUR (242,238,220) H50 (cream, anchor H70) — but 14 W puts the whole lower
# body into the Filmic shoulder: chestLR (242,218,162) L224 S0.33 (anchor L185 S0.64), flankR L192
# S0.48 (152 / 0.71), midbelly L188 (96), and it reaches the LEFT chest (205,173,135) L186 (anchor
# (79,89,78) L94) and the side crown (H48 cream; anchor mint H150). The anchor's belly is DARK and
# its gold falls off fast from the lower-right. So the gold becomes a close, low lamp:
#  * goldkey 14 -> 3.5 W at 1.1 S / el 14 (irradiance x1.86 for the distance: ~6.5 W-eq at 1.5 S,
#    -1.1 stop on the flank; the inverse-square from 0.44 m puts the left chest ~-2 stops and the
#    crown top out of its half-space), colour (1.0,0.20,0.04) = R/G 5 (run1's R/G 3.8 read S0.48
#    on top of the spill).
#  * furkey 9 -> 5 W: the top 3800 K light is the flank's neutral floor (the lock shell passes 85 %
#    of shadow rays, so a top light reaches the lower locks).
#  * coolfur 3.5 -> 4.5 W (MINT10): the crown's light budget, now mint.
GOLD10 = (1.00, 0.20, 0.04)
_GOLD_POS = _sph(32, 14, 1.1)
LIGHTS['goldkey'].update(pos=_GOLD_POS, W=3.5, rgb=GOLD10)
LIGHTS['furkey'].update(W=5.0)
LIGHTS['coolfur'].update(W=4.5)
print(
    'R10 run2: goldkey %s %.1f W at %s; furkey %.1f W; coolfur %.1f W'
    % (
        GOLD10,
        LIGHTS['goldkey']['W'],
        tuple(round(v, 3) for v in _GOLD_POS),
        LIGHTS['furkey']['W'],
        LIGHTS['coolfur']['W'],
    )
)


# ── run3: the COOL budget — 'mint' 3 -> 1 W, coolfur 6 W, furkey 7 W with less blue ───────────
# run2: front chestLR (231,193,134) S0.42 L204, flankR (201,161,95) S0.53 L174, midbelly S0.53 L159
# (base S0.35/0.49/0.38; anchor S0.64/0.71/0.61) — the gold now falls off toward the belly and the
# crown clips 0.2 % (base 0.7 %). Costs: front near-white 30 -> 27 %, q45 36 -> 26 % (anchor 45),
# q45 crownUR L230 -> 220 (anchor 246), side crown L230 -> 219 H76 (anchor L234 H150), side rear
# unchanged at L188 (anchor 120). The flank's pale floor is cool light SCATTERED through the lock
# shell (shadow_tr 0.85), and the cool budget (B-weighted watts) is: rimL 4, coolfur 2.9, key 2.6,
# 'mint' 2.5, furkey 1.65, fillL 1.5 — the gold's own B is 0.26. Of those, 'mint' (3 W from
# behind-left-top, fur-only, R3) lights exactly the two zones the anchor keeps DARK: the front's
# crownUL (ours L238 vs 204) and the side's rear (L188 vs 120). So:
#  * mint 3 -> 1 W;
#  * coolfur 4.5 -> 6 W (the crown's own light, from the top; the side crown wants L234 and mint);
#  * furkey 5 -> 7 W with the blue cut, (1.0,0.60,0.22): the crown-right / upper-right cream the
#    anchor has at b* +17 (ours +7), with a third less blue scattering into the flank.
K10 = (1.00, 0.60, 0.22)
LIGHTS['mint'].update(W=1.0)
LIGHTS['coolfur'].update(W=6.0)
LIGHTS['furkey'].update(W=7.0, rgb=K10)
print(
    'R10 run3: mint %.1f W; coolfur %.1f W; furkey %.1f W %s'
    % (LIGHTS['mint']['W'], LIGHTS['coolfur']['W'], LIGHTS['furkey']['W'], K10)
)


# ── run4: rig settled at run2's crown budget + TAIL BANDS (disjoint region, tail-only material) ──
# run3: coolfur 6 W over-drove the crown apex — front crown clip250 0.2 -> 7.0 % (base 0.7 %; the
# anchor 0 %), q45 3.1 % — while 'mint' 3 -> 1 W did NOT move the side rear (L188 -> 187), so that
# light was not the rear's. Settle: coolfur back to 4.5 W (run2: clip 0.2 %, >=235 45 %, L244),
# furkey 6 W at K10 (run2's 5 W lost the q45 crownUR: L230 -> 220), mint stays 1 W (crownUL front
# L238 in run2 vs the base's 239 — it costs nothing and its scatter is gone).
LIGHTS['coolfur'].update(W=4.5)
LIGHTS['furkey'].update(W=6.0)
# TAIL (critic [major]: 'tail_banded' is a body-plan lock; ours shows 2 bands at the tip and reads
# as a white plume below). probe_tail.py (geodesic bins along the tail, side view): anchor 6 S-peaks
# root->tip at 0.10/0.25/0.38/0.55/0.75/0.88, peak S 0.30-0.56, gaps (181,214,202) S0.15; ours S
# 0.07-0.16 everywhere with one peak 0.36 at 0.82 — where the R9 taper makes the fur SHORT. So the
# band colour is right where it shows (S0.36 vs 0.46) and the lower bands are lost in the plush:
# TAIL_RINGS edge 0.30 of a period (R9 run6, 'so white strands cross into the mint') leaves a solid
# mint core of only 0.12 of a period under 65 mm hair. Tail-only changes (the tail hair material is
# its own node tree, 'pb_tail_hair'; the body's fringe/undercoat keep FUR_COL):
#  * edge 0.30 -> 0.12, mint_frac 0.42 -> 0.45 (n 7 over s 0.22..0.95 = 7 bands root to tip);
#  * band hair colour one step deeper so a band under 65 mm of mixed strands still reads: root
#    (0.08,0.55,0.40) -> (0.06,0.45,0.32), tip (0.18,0.72,0.55) -> (0.12,0.62,0.46) (a pure band
#    rendered S0.36 at the tip; Filmic gives S0.34 for lin (0.15,0.45,0.30));
#  * between-band hair a shade warmer than the body's mint-white: tip (0.86,0.995,0.955) ->
#    (0.93,0.965,0.86) (anchor gap b* +9..+14, ours +2); the tube under it follows.
TAIL10_COL = {
    'root': (0.72, 0.90, 0.80),
    'tip': (0.93, 0.965, 0.86),
    'band_root': (0.06, 0.45, 0.32),
    'band_tip': (0.12, 0.62, 0.46),
}
TAIL_RINGS.update({'edge': 0.12, 'mint_frac': 0.45})
TAIL_TUBE.update({'white': (0.85, 0.90, 0.80), 'mint': (0.10, 0.55, 0.40)})


def _tail_material():  # R10: the tail's own colour table (FUR_COL stays for the body/fringe)
    if 't' in _HAIR_MAT:
        return _HAIR_MAT['t']
    _HAIR_MAT['t'] = _grad_material(
        'pb_tail_hair', TAIL10_COL['root'], TAIL10_COL['tip'], band=(TAIL10_COL['band_root'], TAIL10_COL['band_tip'])
    )
    print(
        'R10 run4: pb_tail_hair %s -> %s, band %s -> %s'
        % (TAIL10_COL['root'], TAIL10_COL['tip'], TAIL10_COL['band_root'], TAIL10_COL['band_tip'])
    )
    return _HAIR_MAT['t']


print(
    'R10 run4: coolfur %.1f W, furkey %.1f W; tail rings %s, tube %s'
    % (LIGHTS['coolfur']['W'], LIGHTS['furkey']['W'], TAIL_RINGS, TAIL_TUBE)
)


# ── run5: TAIL GROOVES (band hair 0.55 x) + the lock shell's shadow transparency 0.85 -> 0.72 ──
# run4 (rig settled; tail colours + edge 0.12): front crown clip250 0.7 % (= base), >=235 49 %;
# body zones = run2's. Tail: the tip bands sharpened (peak S 0.36 -> 0.45 at 0.82, a second peak
# 0.27 at 0.65) but the profile is still S 0.05-0.11 from the root to s ~0.6 — where the R9 plush
# is 1.0 x r (up to 65 mm): a hair rooted on a 45 mm band lies over the next gap and vice versa, so
# the lower bands average out. Both anchors show the tail as fluffy white PILLOWS with the mint at
# the constrictions between them (anchor_side: 6 scallops), not a uniform plume with paint on it.
# R4 had exactly that (TAIL_CONSTRICT 0.85 tube + TAIL_BAND_LEN 0.55 hair) and R5 flattened the
# hair to 'equal on every band'. Back on, tail-only: the tail_len weight x (1 - 0.45 x band(s)), so
# a band's own (mint) hair is 55 % as long as the pillows' and the pillows overhang it a little.
# BODY (disjoint region — the lock shell only; the tail and the face fringe are particle hair with
# their own materials): the flank's pale floor is cool light scattered through the lock shell
# (shadow_tr 0.85 = 85 % of every shadow ray passes a lock). R7 raised it 0.75 -> 0.85 because the
# hem valleys under the belly read black under a rig with nothing warm below the equator; the
# goldkey now fills the hem from below-right. 0.85 -> 0.72: the top lights stop in the upper
# locks (the anchor's midbelly is L96, ours 160), the flank's floor drops, the coat gets the
# root-shadow depth the anchor's fur has. Checked against lab_face (the fringe over the plate
# is particle hair, unaffected) and the side eye finder's dark-blob trap.
TAIL10_BAND_LEN = 0.55
_tail_len_r9 = _tail_len_r5


def _tail_len_r5(p):
    _tail_len_r9(p)
    t = _ob('pb_tail_00')
    if t is None:
        return
    n, S = p['tail_rings'], p['tail_sides']
    vg_l = t.vertex_groups.get('tail_len')
    if vg_l is None:
        return
    T = TAIL5
    Q = TAIL9

    def lpr(s):
        u = (s - Q['taper_s0']) / (Q['taper_s1'] - Q['taper_s0'])
        u = min(1.0, max(0.0, u))
        return Q['len_hi'] + (Q['len_lo'] - Q['len_hi']) * u

    nb = 0
    for i in range(n - 1):
        s = i / float(n - 1)
        b = _ring_band(s)
        if b <= 0.0:
            continue
        w = max(T['min_w'], min(1.0, lpr(s) * _radius(s, p) / p['tail_hair_len']))
        w2 = max(T['min_w'], w * (1.0 - (1.0 - TAIL10_BAND_LEN) * b))
        for j in range(S):
            vg_l.add([1 + i * S + j], w2, 'REPLACE')
        nb += 1
    print('R10 run5 tail grooves: band hair x %.2f on %d of %d rings' % (TAIL10_BAND_LEN, nb, n - 1))


LOCK7_COL.update({'shadow_tr': 0.72})
print('R10 run5: lock shadow_tr %.2f; tail band hair x %.2f' % (LOCK7_COL['shadow_tr'], TAIL10_BAND_LEN))


# ── run6: BARE glossy bands (band hair 0.15 x, constriction 0.78, tube rough 0.35 + coat); the
#          crown's top light as a 0.6 S disk at 7 W ──────────────────────────────────────────────
# run5: the grooves scalloped the tail outline (side rough +10 -> +17 %) but the side S profile did
# not move (0.04-0.07 root..0.6). tail_zoom_run5.png (anchor_side x2 next to ours): the anchor's
# bands are BARE, glossy mint tube skin at the constrictions between short-furred white pillows;
# ours are 65 mm hair leaning tip-ward over a groove that is still 36 mm deep in hair. Where our
# fur IS short (front tail, s > 0.85) the bands already read exactly like the anchor's — glossy
# tube between fur. So the band becomes what the anchor shows: band hair x 0.15 (floor min_w
# 0.06 = 4 mm), tube radius x 0.78 on a band (R4's 0.85), and the tube itself glossy (roughness
# 0.7 -> 0.35, coat 0.25: the anchor's band carries one soft highlight). Pillow hair length /
# count / child and the tailside light are untouched (critic).
# Body (disjoint — the crown's top light only): every run since run1 slid the upper-body whites
# down (front near-white 30 -> 25.5 %, q45 36 -> 24 %; anchor 45 %) because the el-70 furkey that
# used to make them also floods the flank, and coolfur is a 0.25 S disk 0.1 m over the apex (run3:
# 6 W there clipped 7 %). Same light as a 0.6 S disk at 7 W: at the apex (a^2 + d^2: 0.0125 ->
# 0.0244 m^2) that is ~3.6 W-eq of the old disk — under run2's 4.5 — while the upper flanks, which
# the small disk never reached, get its skirt. Mint, not cream: the side crown (H70) moves toward
# the anchor's H150.
TAIL10_BAND_LEN = 0.15
TAIL_CONSTRICT = 0.78
TAIL10_TUBE = {'rough': 0.35, 'coat': 0.25, 'coat_rough': 0.15}
_tube_material_r3 = _tube_material


def _tube_material():
    m = _tube_material_r3()
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value = TAIL10_TUBE['rough']
    b.inputs['Coat Weight'].default_value = TAIL10_TUBE['coat']
    b.inputs['Coat Roughness'].default_value = TAIL10_TUBE['coat_rough']
    print('R10 run6: pb_tail_tube rough %.2f coat %.2f' % (TAIL10_TUBE['rough'], TAIL10_TUBE['coat']))
    return m


LIGHTS['coolfur'].update(W=7.0, size=0.60)
print(
    'R10 run6: band hair x %.2f, constrict %.2f; coolfur %.1f W size %.2f S'
    % (TAIL10_BAND_LEN, TAIL_CONSTRICT, LIGHTS['coolfur']['W'], LIGHTS['coolfur']['size'])
)


# ── run7 (FINAL candidate): the band as a FIELD of position — every tail hair point takes the band
#    value of the tube station it hangs over; band hair 0.40 x, constriction 0.80 ─────────────────
# run6 (bare bands 0.15 x, glossy tube): front/q45 tails show 5 crisp bands root to tip and the
# front near-white is back to the base's (30.1 %, crown clip 0.9 % vs base 0.7), but the SIDE tail
# is unchanged (S 0.04-0.05 root..0.6; tail_zoom_run6.png): the 65 mm pillow hairs lean tip-ward
# and curtain every bare band from the side camera, and each strand carries its ROOT's band value
# (the 'band_col' attribute) along its whole length, so a strand over a band stays white. Point
# Density (vertex colour from the tube) renders zero in this Blender (pd_test.py, all spaces /
# radii); a cubic polynomial s(x,y,z) fitted around the centreline misses by 0.13 in s at the
# J-bend (more than a band period). What works exactly: project the shading point onto the tube's
# own centreline POLYLINE (every 12th ring centre, 14 stations from the built mesh), take the
# nearest segment's s, and evaluate _ring_band(s) in nodes — the same ramp the tube uses. The
# strand's colour then follows the tail's stations root to tip, view-independent. With the colour
# no longer depending on bareness the bands take some plush back (band hair 0.15 -> 0.40 x,
# constriction 0.78 -> 0.80): run6's scallops put side rough at +27 % (base +6 %).
TAIL10_BAND_LEN = 0.40
TAIL_CONSTRICT = 0.80
TAIL10_FIELD = {'step': 12}


def _tail_band_field10(scene, p):
    t = _ob('pb_tail_00')
    m = bpy.data.materials.get('pb_tail_hair')
    if t is None or m is None:
        print('R10 run7: no tail / tail hair material')
        return
    me = t.data
    n, S = p['tail_rings'], p['tail_sides']
    rings = list(range(0, n - 1, TAIL10_FIELD['step']))
    if rings[-1] != n - 2:
        rings.append(n - 2)
    P = []
    SS = []
    for i in rings:
        c = Vector((0.0, 0.0, 0.0))
        for j in range(S):
            c += me.vertices[1 + i * S + j].co
        P.append(c / float(S))
        SS.append(i / float(n - 1))

    # python twin of the node field, for a self-check against the tube's own attribute
    def field(x):
        best = (1e9, 0.0)
        for k in range(len(P) - 1):
            A, B = P[k], P[k + 1]
            d = B - A
            l2 = max(d.length_squared, 1e-9)
            tt = min(1.0, max(0.0, (x - A).dot(d) / l2))
            q = A + d * tt
            dd = (x - q).length
            if dd < best[0]:
                best = (dd, SS[k] + (SS[k + 1] - SS[k]) * tt)
        return best[1]

    err = []
    err_out = []
    for i in range(0, n - 1, 5):
        s = i / float(n - 1)
        for j in range(0, S, 7):
            v = me.vertices[1 + i * S + j]
            err.append(abs(_ring_band(field(v.co)) - _ring_band(s)))
            err_out.append(abs(_ring_band(field(v.co + v.normal * 0.05)) - _ring_band(s)))
    print(
        'R10 run7 band field: %d stations; band error on the tube mean %.3f max %.3f, 50 mm out mean %.3f max %.3f'
        % (len(P), sum(err) / len(err), max(err), sum(err_out) / len(err_out), max(err_out))
    )
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    attr = next((x for x in N if x.type == 'ATTRIBUTE' and x.attribute_name == 'band_col'), None)
    if attr is None or not attr.outputs['Fac'].links:
        print('R10 run7: band attribute node not found in pb_tail_hair')
        return
    sel_sock = attr.outputs['Fac'].links[0].to_socket
    tc = N.new('ShaderNodeTexCoord')
    pos = tc.outputs['Object']

    def vm(op, a, b=None, scale=None):
        x = N.new('ShaderNodeVectorMath')
        x.operation = op
        if isinstance(a, tuple):
            x.inputs[0].default_value = a
        else:
            L.new(a, x.inputs[0])
        if b is not None:
            if isinstance(b, tuple):
                x.inputs[1].default_value = b
            else:
                L.new(b, x.inputs[1])
        if scale is not None:
            if isinstance(scale, float):
                x.inputs['Scale'].default_value = scale
            else:
                L.new(scale, x.inputs['Scale'])
        return x

    def mm(op, a, b=None, c=None):
        x = N.new('ShaderNodeMath')
        x.operation = op
        x.use_clamp = False
        for k, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                x.inputs[k].default_value = float(v)
            else:
                L.new(v, x.inputs[k])
        return x.outputs[0]

    def clamp01(a):
        x = N.new('ShaderNodeClamp')
        L.new(a, x.inputs['Value'])
        x.inputs['Min'].default_value = 0.0
        x.inputs['Max'].default_value = 1.0
        return x.outputs[0]

    best_d = best_s = None
    for k in range(len(P) - 1):
        A, B = P[k], P[k + 1]
        d = B - A
        l2 = max(d.length_squared, 1e-9)
        sub = vm('SUBTRACT', pos, (A.x, A.y, A.z))
        dot = vm('DOT_PRODUCT', sub.outputs['Vector'], (d.x, d.y, d.z)).outputs['Value']
        tt = clamp01(mm('DIVIDE', dot, l2))
        q = vm('ADD', vm('SCALE', (d.x, d.y, d.z), scale=tt).outputs['Vector'], (A.x, A.y, A.z))
        dist = vm('DISTANCE', pos, q.outputs['Vector']).outputs['Value']
        sk = mm('MULTIPLY_ADD', tt, SS[k + 1] - SS[k], SS[k])
        if best_d is None:
            best_d, best_s = dist, sk
        else:
            lt = mm('LESS_THAN', dist, best_d)
            mx = N.new('ShaderNodeMix')
            mx.data_type = 'FLOAT'
            L.new(lt, mx.inputs[0])
            L.new(best_s, mx.inputs[2])
            L.new(sk, mx.inputs[3])
            best_s = mx.outputs[0]
            best_d = mm('MINIMUM', best_d, dist)
    R = TAIL_RINGS
    span = R['s1'] - R['s0']
    lo = 0.5 - R['mint_frac'] / 2.0
    hi = 0.5 + R['mint_frac'] / 2.0
    e = R['edge']
    tv = mm('MULTIPLY_ADD', best_s, 1.0 / span, -R['s0'] / span)
    ph = mm('FRACT', mm('MULTIPLY', tv, float(R['n'])))
    a = clamp01(mm('MULTIPLY_ADD', ph, 1.0 / e, -(lo - e / 2.0) / e))
    b = clamp01(mm('MULTIPLY_ADD', ph, -1.0 / e, (hi + e / 2.0) / e))
    band = mm('MINIMUM', a, b)
    inside = mm('MULTIPLY', mm('GREATER_THAN', best_s, R['s0']), mm('LESS_THAN', best_s, R['s1']))
    out = mm('MULTIPLY', band, inside)
    for l in list(attr.outputs['Fac'].links):
        L.remove(l)
    L.new(out, sel_sock)
    print('R10 run7: pb_tail_hair band <- centreline field (%d segments, %d nodes)' % (len(P) - 1, len(N)))


_post_build_r10_run6 = post_build


def post_build(scene, result, PB):
    _post_build_r10_run6(scene, result, PB)
    _tail_band_field10(scene, dict(_P))
    bpy.context.view_layer.update()


print('R10 run7: band field on the tail hair; band hair x %.2f, constrict %.2f' % (TAIL10_BAND_LEN, TAIL_CONSTRICT))


# ── run8 (FINAL): the band field's polyline twice as dense (every 6th ring, 27 segments) ─────────
# run7: the field works — side tail S ripples 0.10-0.18 along the plush lower tail with peaks 0.34
# (s 0.65) / 0.44 (0.82) where the base was flat 0.05; front/q45 tails carry 6 bands root to tip
# (tail_zoom_run7.png). Self-check on the 14-station polyline: band error on the tube mean 0.015,
# 50 mm out mean 0.19 — the stray white strands inside a band and mint strands beside it. Only
# the station spacing changes (12 -> 6 rings, ~330 nodes); nothing else moves.
TAIL10_FIELD['step'] = 6
print('R10 FINAL: band field step %d rings' % TAIL10_FIELD['step'])


# ═════════════════════════════════════════════════════════════════════════════
# R10 MERGE (lookdev3 round 2 / r2_merge) — base = r1_merge/merge2.py (everything above the
# R10 FACE header) + R10 FACE (r2_face/face.py: per-view gaze, convergence 0.82, tapered snout)
# + R10 COAT (r2_coat/coat.py: goldkey / furkey / coolfur / mint re-budget, lock shadow_tr 0.72,
# tail colour table + band field + grooves + glossy tube), in that order. Both sections are
# verbatim. Composition: the coat's `_post_build_r10_run6 = post_build` now captures the FACE's
# post_build (R9 merge chain + _snout10), so the merged chain is r9merge -> snout -> tail band
# field; the camera hook is the face's (R9 merge camera + _gaze9); no name is bound by both
# sections. The coat's lights are all in FUR_ONLY or on the tail, so the gaze / snout sit under
# the R9 face rig unchanged.
# ═════════════════════════════════════════════════════════════════════════════
print(
    'R10 MERGE run1: face (gaze clamp %.0f deg, converge %.2f, BEAK_R %s) + coat (goldkey %.1f W %s, furkey %.1f W, coolfur %.1f W, shadow_tr %.2f, tail field step %d)'
    % (
        GAZE9['max_deg'],
        GAZE9['converge'],
        BEAK_R,
        LIGHTS['goldkey']['W'],
        GOLD10,
        LIGHTS['furkey']['W'],
        LIGHTS['coolfur']['W'],
        LOCK7_COL['shadow_tr'],
        TAIL10_FIELD['step'],
    )
)


# ═════════════════════════════════════════════════════════════════════════════
# MICRO — TRUE DISPLACEMENT, 2026-08-28
#
# WHY. Grepping this file for `displacement_method`, `use_adaptive_subdivision`,
# `ShaderNodeDisplacement`, `dicing_rate` and `feature_set` returned ZERO hits across all
# 9,183 lines, and pufferball.py's `_fur()` is a DISPLACE modifier on a body of 4,751
# vertices. A displace modifier can only move vertices that already exist, so on a 0.63 m
# body meshed at 96x48 the finest surface feature the geometry can represent is about
# 2 cm across. Everything below that — the anchor's pebbled plate, its pores, the grain
# where light rakes across the snout — is not merely absent from the render, it is
# unrepresentable by the mesh. PEBBLE carries `dist: 0.0005`, i.e. a 0.5 mm BUMP: it
# perturbs the shading normal and leaves the surface flat, so it produces no silhouette
# break, no self-shadowing and no parallax. That is the literal sense in which the light
# has nothing to break over.
#
# WHAT THIS DOES. Subdivides the named parts and displaces real vertices through a mesh
# DISPLACE modifier, driven by the same Voronoi cell field PEBBLE already uses for its
# bump, so the two agree instead of arguing. The existing bump is scaled down by
# `bump_keep`, because keeping both at full strength counts the same pebbles twice and
# reads as plastic shrink-wrap.
#
# NOT Cycles adaptive-subdivision displacement, which this section used first. Measured:
# with it on, two renders of an identical patch differ by mean|d| 0.002031 (19.1% of
# pixels); with it off, 0.000000. A 2000x rise in the render noise floor makes
# prop_mesh/pbopt.py's lever probe useless, because that probe decides a parameter is
# live by whether it moved the picture further than the noise. Cost of the change:
# nothing measurable — the whole section adds about 1 s to an 18 s two-view render.
#
# SCOPE. The face plate and the lip only, by default. The body is under 30 mm of fur and
# would pay subdivision cost for a surface nothing can see; the eyes are glass. MICRO['on'] = 0
# reverts the whole section, which is also how prop_mesh/pbopt.py is able to put "should
# this exist at all" into the search rather than into an argument.
# ═════════════════════════════════════════════════════════════════════════════
MICRO = {
    'on': 1.0,  # <= 0 disables the whole section (revert in one number)
    'levels': 2,  # subsurf levels on the adaptive cage
    'parts': ('pb_face', 'pb_snout', 'pb_lip'),
    'scale': 290.0,  # cell frequency; PEBBLE['scale'] is 290.0 — kept in step
    'rand': 0.85,  # Voronoi randomness; PEBBLE['rand'] is 0.85
    'height': 0.0016,  # metres of TRUE displacement, peak to trough
    'mid': 0.45,  # ramp midpoint: below it the cell centres sink, above they rise
    'bump_keep': 0.35,  # PEBBLE's bump is scaled to this once displacement carries it
}


def _micro_texture(m):
    """A legacy VORONOI texture for a mesh DISPLACE modifier.

    Deliberately NOT Cycles' adaptive-subdivision displacement, which the first version of
    this section used. MEASURED 2026-08-28: with adaptive subdivision on, two renders of
    an identical patch differ by mean|d| 0.002031 with 19.1% of pixels moving, against
    0.000000 with it off. Cycles dices non-deterministically across processes, and a
    2000x rise in the render noise floor blinds prop_mesh/pbopt.py: its probe decides
    whether a parameter is live by whether it moved the picture further than that floor,
    so a noisy renderer makes every dead lever look alive.

    A DISPLACE modifier moves real vertices on a subdivided cage instead. Same geometry,
    same self-shadowing and silhouette break, fully reproducible, and it does not need the
    EXPERIMENTAL feature set. `noise_scale` is a feature SIZE in local units, so the cell
    frequency MICRO['scale'] (cells per metre) inverts into it — the same conversion, and
    the same trap, as pufferball.py's `_fur()`, which shipped 1/9 straight through as a
    noise_scale and got features a third of the body wide.
    """
    tex = bpy.data.textures.new('pb_micro', 'VORONOI')
    tex.distance_metric = 'DISTANCE'
    tex.noise_scale = 1.0 / max(float(m['scale']), 1e-6)
    tex.noise_intensity = float(m['rand'])
    tex.contrast = 1.6
    return tex


def _micro_damp_bump(mat, keep):
    """Scale PEBBLE's existing bump so the pebbles are not counted twice.

    Identified by VALUE, not by name: the bump node this file builds is unnamed and the
    graph is assembled across several cumulative sections, so a name match would silently
    find nothing. PEBBLE['dist'] is 0.0005, so any Bump whose Distance is within a factor
    of four of that is the one.
    """
    n_hit = 0
    for n in mat.node_tree.nodes:
        if n.type != 'BUMP':
            continue
        d = n.inputs['Distance'].default_value
        if 0.000125 <= d <= 0.002:
            n.inputs['Distance'].default_value = d * keep
            n_hit += 1
    return n_hit


_post_build_before_micro = post_build


def post_build(scene, result, PB):
    _post_build_before_micro(scene, result, PB)
    m = MICRO
    if m.get('on', 0) <= 0:
        print('MICRO off')
        return
    tex = _micro_texture(m)
    done, damped = [], 0
    for name in m['parts']:
        ob = _ob(name)
        if ob is None or ob.type != 'MESH':
            continue
        if any(x.name == 'micro_disp' for x in ob.modifiers):
            continue
        # A DISPLACE modifier can only move vertices that already exist, so the cage is
        # subdivided first. pufferball.py's `_fur()` displaces the 4,751-vertex body and
        # therefore cannot represent anything finer than about 2 cm; the face plate at
        # 859 vertices is worse. Two Catmull-Clark levels take the plate to roughly 14k,
        # which resolves ~290 cells/m across a 0.13 m plate with several vertices per cell.
        sub = next((x for x in ob.modifiers if x.type == 'SUBSURF'), None)
        if sub is None:
            sub = ob.modifiers.new('micro_subsurf', 'SUBSURF')
        sub.subdivision_type = 'CATMULL_CLARK'
        sub.levels = int(m['levels'])
        sub.render_levels = int(m['levels'])
        d = ob.modifiers.new('micro_disp', 'DISPLACE')
        d.texture = tex
        d.texture_coords = 'LOCAL'
        d.direction = 'NORMAL'
        d.mid_level = float(m['mid'])
        d.strength = float(m['height'])
        for slot in ob.material_slots:
            if slot.material:
                damped += _micro_damp_bump(slot.material, m['bump_keep'])
        done.append(name)
    print(
        'MICRO on: %s displaced by mesh DISPLACE (height %.4f m, cells %.0f/m, '
        'subsurf %d); %d existing bump node(s) scaled to %.2f'
        % (done or 'nothing', m['height'], m['scale'], m['levels'], damped, m['bump_keep'])
    )


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 4 — FRAMING. Baked 2026-08-29 from the CMA-ES fit (prop_mesh/pbopt.py).
#
# TWO NUMBERS OUT OF TWENTY. The fit searched a 20-parameter vector; only the camera
# survived review, and this block is deliberately the smallest part of that result.
#
# WHAT THE CAMERA IS WORTH, at 1024 px against the two operator anchors:
#
#                     production   this block   full fit   anchor
#   composite loss      0.7438       0.5216      0.5005      0
#   ink (frame cover)    0.325        0.471       0.471    0.475
#   height in frame      0.646        0.796       0.793    0.799
#
# 91 per cent of the entire measured gain is the camera. Nothing in three look-dev runs
# and 68 agents had ever measured framing: they argued about fur while the creature sat
# 17.6 per cent off the bottom of its own frame at 32.5 per cent cover against 48.9.
#
# ── WHY THE OTHER EIGHTEEN PARAMETERS ARE NOT HERE ──────────────────────────
#
# The fitted groom RENDERS A BALD FLANK. Measured by ablation, 1024 px, both anchors:
#
#   variant                                     loss     coat
#   production                                 0.7438    fur
#   framing only (this block)                  0.5216    fur
#   fitted, lock shape + undercoat reverted    0.4677    fur
#   fitted, lock shape reverted                0.4376    BALD
#   fitted, as searched                        0.5005    BALD + flat petals
#
# The two BEST-SCORING variants are the two broken ones. The cause is the `fill` term in
# pbmetrics.py — coverage inside the subject's own bounding box — added because "the coat
# lets the backdrop through between locks". A BALD BODY MAXIMISES IT: skin has no gaps.
# Scaled, dense fur scores 1.158-1.556 on that term and a smooth shell scores 0.255-0.386,
# so the objective pays roughly four times more for deleting the coat than for grooming
# it. The anchor reaches fill 0.675 WITH dense plush; the bald variant reaches 0.664
# WITHOUT it, and no term in the stack can tell those two apart.
#
# The bald shell is specifically the UNDERCOAT (len 0.0763 against 0.036, 6217 strands x
# 34 children against 2500 x 24): it buries the locks in a smooth mass. Reverting lock
# shape alone does NOT fix it; reverting the undercoat does. The flat petals are a second,
# separate defect from the lock shape pinning at the corner of its box.
#
# SEVEN OF TWENTY PARAMETERS FINISHED PINNED TO A BOUND, four of them the coat's:
# w_per_L at its CEILING, spacing at its CEILING, thick at its FLOOR, lean.flank and
# lean.wisp at their FLOORS. Widest, flattest, sparsest, laid flattest — that is a
# description of petals on a shell, not of fur, and it is what a search does when the
# objective's cheapest win is to stop growing hair.
#
# So the groom half of this fit is not conservative-but-unproven, it is MEASURED WRONG,
# and none of it is baked. Fix `fill` first — score coverage against a fur-aware mask, or
# add a strand-density term that a bald body cannot satisfy — then the search is worth
# re-running. Until then the groom above this line is the operator-approved one.
#
# MICRO['parts'] is the one other change, and it is a hand-correction, not a fit result:
# the plate only, because the anchor's lip and snout are smooth orange. The objective
# actively VOTES AGAINST it (composite +0.0265, through iso_fine and iso_mid) while
# `detail` — the term that exists to watch surface relief — does not move at all
# (0.256 both). It is kept because it is right, not because it scores.
#
# NOISE FLOOR, measured 2026-08-29: two renders of an identical configuration differ by
# 0.011 composite. front_full is bit-identical; side_left is NOT, and it is
# ORDER-DEPENDENT — a 2-view render and a 16-view render of the same parameters disagree
# by 0.022 on that view. The search rendered 2 views and production renders 16, so the
# search was never minimising quite the number production reports. Run 1 vs run 2 differed
# by 0.011: exactly the noise floor. That comparison never had the resolution to decide
# anything, which is why the plate was adopted on the eyes.
#
# REVERT: prop_mesh/pufferball_look.py.bak-20260829-prebake, or delete this block.
# ═════════════════════════════════════════════════════════════════════════════

CAM_FIT.update({'margin': -0.02, 'pad': 0.02628590283059161})
MICRO.update({'parts': ('pb_face',)})

print(
    'PB LOOK phase-4 FRAMING baked: cam margin %.4f pad %.4f | micro parts %s '
    '(groom unchanged from phase-3 r2 — the fitted groom went bald, see block comment)'
    % (CAM_FIT['margin'], CAM_FIT['pad'], MICRO['parts'])
)


# ═════════════════════════════════════════════════════════════════════════════
# COAT INVARIANT — the undercoat must stay UNDER the coat. Added 2026-08-29.
#
# WHAT WENT WRONG. A 400-evaluation CMA-ES fit chose UNDERCOAT2['len'] = 0.0763 m. The
# locks it sits beneath are 0.045 m (cap), 0.050 (rim), 0.055 (back, belly), 0.060 (flank)
# — so in SEVEN OF EIGHT REGIONS the undercoat was longer than the coat, and it swallowed
# it. The flank rendered as a smooth bare shell with a few flat locks lying on it. The
# operator-approved value is 0.036 m, which is 0.80 of the shortest lock.
#
# WHY THIS IS A BUILD-TIME ASSERT AND NOT A METRIC. Every one of the nine image terms in
# prop_mesh/pbmetrics.py ranked that bald render BETTER than the furry production render:
# the anchors are generated images with soft low-contrast fur, ours is a sharp Cycles
# render, and on every image statistic LESS FUR MEANS CLOSER TO THE ANCHOR. Three
# replacement terms were built and measured before one worked. But an image metric can
# only ever PENALISE this after paying to render it, and can be outvoted — as it was, by
# a framing term worth ten times more. A parameter contradiction should be unreachable,
# not expensive: this costs nothing, needs no render, and cannot be outvoted.
#
# It is deliberately a floor on the RATIO rather than on the metre value, so it survives
# any future change to lock length.
# ═════════════════════════════════════════════════════════════════════════════

COAT_CLEARANCE = 0.93  # undercoat length, as a fraction of the SHORTEST lock.
# Production sits at 0.036/0.045 = 0.80.


def assert_coat_stands_proud(u=None, t=None, clearance=None):
    """Raise unless every region's locks stand proud of the undercoat.

    Returns (undercoat_len, shortest_lock, region) so a caller can log the margin.
    """
    U = UNDERCOAT2 if u is None else u
    T = TUFT7 if t is None else t
    c = COAT_CLEARANCE if clearance is None else clearance
    lens = {k: float(v) for k, v in T['len'].items()}
    region = min(lens, key=lens.get)
    shortest = lens[region]
    ulen = float(U['len'])
    if ulen >= shortest * c:
        buried = sorted(k for k, v in lens.items() if ulen >= v * c)
        raise SystemExit(
            'COAT INVARIANT VIOLATED: undercoat len %.4f m is not under the coat.\n'
            '  shortest lock is %r at %.4f m; the bar is %.0f%% of it (%.4f m).\n'
            '  buried regions (%d of %d): %s\n'
            '  This is the 2026-08-29 bald-flank failure: an undercoat longer than the\n'
            '  locks it sits beneath swallows them and the body renders BARE. Every image\n'
            '  metric in pbmetrics.py scored that render BETTER than the furry one, so\n'
            '  nothing downstream will catch it for you.'
            % (ulen, region, shortest, 100.0 * c, shortest * c, len(buried), len(lens), ', '.join(buried))
        )
    return ulen, shortest, region


_ulen, _slock, _sregion = assert_coat_stands_proud()
print(
    'PB LOOK coat invariant OK: undercoat %.4f m under shortest lock %r %.4f m (%.0f%%)'
    % (_ulen, _sregion, _slock, 100.0 * _ulen / _slock)
)


# ═════════════════════════════════════════════════════════════════════════════
# R11MOUTH (2026-09-05) — reconcile the two anchors as an OPEN SHORT BILL
# ═════════════════════════════════════════════════════════════════════════════
# The anchors disagreed about the mouth: the front lock shows a small OPEN rounded
# mouth, the side lock a CLOSED protruding two-lobe bill. Operator decision (creator,
# 2026-09-03): reconcile as an open short bill — the side anchor governs the PROFILE
# (length past the face plate, thick upper / thin lower), the front anchor governs the
# APERTURE (rounded opening, dark cavity, tiny upper teeth, visible lip ring).
#
# WHAT THE ANCHORS ACTUALLY MEASURE — two figures in the brief did not survive contact
# with them, so the numbers below are the anchors', not the brief's:
#   * front aperture is 2.20:1 wide:tall (91 x 41 px at an inter-pupil 245.5), NOT the
#     1.4:1 the brief quotes. Read off a coordinate grid by eye at 2.22:1 as a check.
#   * the registered render's aperture was ALREADY 2.22:1 — not a 3:1 slit. The mouth
#     was not the wrong SHAPE, it was the wrong SIZE: 0.250 of inter-pupil wide against
#     the anchor's 0.371, and 0.113 tall against 0.167. Both short by ~1.48x.
#   * the side bill protrudes 0.18 eye-diameters past the face plate, NOT "about one".
#   * teeth filled 81% of the opening's height against the anchor's 37%.
#
# ADOPTED (candidate d3 of five rendered at 1024/48, chosen by eye with the metrics as
# tie-breaker, which is this project's rule after DINO and the composite both voted for
# corrections that were wrong):
#            metric                anchor   before    d3      d5(rejected)
#   front    aperture ratio         2.20     2.39     1.97     1.69
#            aperture w / ipd       0.358    0.267    0.296    0.441
#            aperture h / ipd       0.163    0.112    0.150    0.262
#   side     protrusion / eye-dia   0.1825   0.1288   0.1818   0.1818
#   both     pbopt composite          -      0.4822   0.4584   0.4812
#   d5 opened the mouth too far in both axes; d3 lands nearest on every front term and
#   reproduces the side protrusion to three decimals. Composite IMPROVES by 0.024.
#
# THE LEVERS, and why each moved:
#  * BEAK_OUT 0.032 -> 0.037. NOTE it was 0.032, not the 0.028 at :735 — :3515 rebinds
#    it inside `if R5_ON['mouth']:`, which is module-level, so it wins. Fitted: 0.040
#    overshot to 0.2197 protrusion, 0.032 gave 0.1288, target 0.1825.
#  * SNOUT10 droop 0.50 -> 0.28, taper 0.65 -> 0.45. At droop 0.50 the pad's front top
#    fell to 9.5 mm while the cut ceiling stood at 7 mm, leaving a 2.5 mm upper lip that
#    rendered as a V-NOTCH in the middle of the mouth. Less droop keeps the lip thick.
#  * CUT_R (0.023,0.012,0.0075) -> (0.030,0.013,0.0105). Width is capped by BEAK_R[0]:
#    a cut wider than the pad slices it into two halves. CUT_R[1] 0.013 punches the
#    front pole so the bill reads OPEN in profile rather than as a closed nub.
#  * CUT_DZ -0.004 -> -0.0035, LOWLIP down to (0.020,0.008,0.0045) at dz -0.0145: thick
#    upper mandible, thin lower, per the side anchor.
#  * teeth 7 -> 9, TOOTH_R 0.0015 -> 0.0009, TOOTH_TALL 1.7 -> 1.35, span 0.028 -> 0.033.
#    Tooth height over aperture height falls 0.402 -> 0.149 (anchor 0.366 of the visible
#    opening); the anchor's teeth are a row of tiny beads, not a full row of tombstones.
BEAK_OUT = 0.037
BEAK_R = (0.030, 0.024, 0.019)
CUT_R = (0.030, 0.013, 0.0105)
CUT_DZ = -0.0035
SNOUT10 = {'taper': 0.45, 'taper_pow': 1.5, 'droop': 0.28}
TOOTH_R = 0.0009
TOOTH_TALL = 1.35
TEETH_N = 9
TEETH_SPAN = 0.033
LOWLIP_R = (0.020, 0.008, 0.0045)
LOWLIP_DY = 0.010
LOWLIP_DZ = -0.0145
TONGUE_R = (0.011, 0.005, 0.0028)
TONGUE_DZ = -0.0095
print(
    'R11MOUTH: beak_out %.3f beak_r %s cut_r %s dz %.4f snout %s; teeth %d r %.4f tall %.2f span %.3f'
    % (BEAK_OUT, BEAK_R, CUT_R, CUT_DZ, SNOUT10, TEETH_N, TOOTH_R, TOOTH_TALL, TEETH_SPAN)
)
