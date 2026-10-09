# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The rectus abdominis definition layer — AFS p.30 patterns v1 and v2.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 734-1170).
"""

import os

import numpy as np

from zyg_workflows.geom.mesh_skeletons.spec import ABS_PATTERNS, ABS_PATTERN_KEY, ABS_PATTERN_V1, ABS_PATTERN_V2

from zyg_workflows.geom.mesh_skeletons.rig import _band, _morph_support, _vertex_normals

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ---------------------------------------------------------------------------------
# RECTUS ABDOMINIS PATTERN v2 — Anatomy for Sculptors p.30 (CANON)
# ---------------------------------------------------------------------------------
# AFS p.30, "IS A 'SIX-PACK' REALLY AN 'EIGHT-PACK'?", prints two schematics of the
# rectus sheath side by side: a red-X one and a green-check one. The red-X diagram is
# four rows of EQUAL RECTANGLES separated by STRAIGHT HORIZONTAL creases under a FLAT
# top edge. That is, line for line, what the v1 pattern below computed: creases as
# exp(-((zn-zi)/0.06)**2) with no x term, over a rectus mask of constant width at every
# height. We shipped the diagram the book prints as wrong.
#
# The green-check diagram — and the anatomical render in the same page's info panel —
# differ in three measurable ways, all of which v2 implements:
#   (a) the tendinous inscriptions are ARCHED, apex on the linea alba, ends running
#       down-and-out to the linea semilunaris;
#   (b) the sheath's half-width is not constant: it converges toward the pubis below
#       the navel, plateaus through the mid-abdomen, flares widest where the muscle
#       reaches the 5th-7th costal cartilages, then narrows hard at the very top;
#   (c) the top boundary is the CURVED COSTAL MARGIN — a dome per side with a notch on
#       the midline at the xiphoid — not a straight line.
# The one thing v1 already had right, and v2 keeps unchanged: the segment below the
# navel is the longest and carries no inscription (AFS p.30, and the four-pairs-above-
# the-navel count on the same page — v1's four creases with the lowest at zn=0.30, just
# above the navel at zn=0.241, already give four tabbed pairs plus the long lower one).
#
# PROVENANCE / CALIBRATION. Every number below was DIGITISED from the green-check
# diagram itself (AFS p.30, PDF page 30 of the Exonicus edition, rendered at 300 dpi and
# traced by neutral-ink threshold), not tuned until our own meshes looked right. Rule 3
# of the calibration policy: our morph-space sample may set severity, never the number.
# Provenance tag CANON (artist canon; ranks below MEASURED survey data). Nothing here
# block-fails any quantity — it is a sculpt shape, not a gate.
#
# The diagram is mapped into the code's own normalised coordinates by the three
# landmarks that BOTH representations contain explicitly, the three inscriptions:
# a least-squares fit of diagram row against the code's crease heights 0.30/0.52/0.74
# gives row = 1372.0 - 960.5*zn with residuals [+6.4, -12.7, +6.4] px, i.e. one crease
# line-width. Laterally, the code places the linea semilunaris at |xn| = 0.58, so the
# diagram's mid-abdominal half-width (224.5 px, the plateau median) IS |xn| = 0.58 and
# 1 xn unit = 387.1 px.

# (b) Sheath half-width relative to its mid-abdominal plateau, sampled every 0.05 zn.
# Traced as (leftmost, rightmost) neutral ink per row, averaged about the midline,
# smoothed over 21 rows, then passed through a 3-point median: the raw trace dips at the
# three crease rows, where the salmon inscription overlay and the navel circle eat into
# the boundary, and those dips are drawing artefacts, not the muscle.
#
# READ THE SHAPE BEFORE CHANGING IT. The brief for this fix said "the segments narrow
# toward the top". The diagram says that ONLY above zn ~ 0.91: from the navel up to
# zn = 0.90 the sheath gets 48% WIDER (0.769 -> 1.139), because the rectus originates on
# the 5th-7th costal cartilages, which are far wider apart than the pubic crest it
# inserts on. Implementing a monotone superior taper would have inverted the anatomy
# over three quarters of the band. The measured profile is used verbatim.
_ABS_V2_W_ZN = (
    0.00,
    0.05,
    0.10,
    0.15,
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
    0.45,
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.95,
    1.00,
)
_ABS_V2_W = (
    0.769,
    0.833,
    0.889,
    0.934,
    0.964,
    0.964,
    0.988,
    1.027,
    1.027,
    1.000,
    1.000,
    1.000,
    1.000,
    1.000,
    1.013,
    1.027,
    1.058,
    1.139,
    1.139,
    0.946,
    0.586,
)

# (a) Inscription arc. Each crease drops by arc*|xn|**2 below its midline height. The
# amplitudes are the least-squares a of row = y0 + a*|xn|**2 on 360-372 traced columns
# per crease, converted at 960.5 px per zn unit:
#   crease zn 0.30 (navel level)  a =   -0.32 px  ->  0.0000/zn   rms 5.51 px  FLAT
#   crease zn 0.52                a = +164.92 px  ->  0.1717/zn   rms 3.48 px
#   crease zn 0.74                a = +340.46 px  ->  0.3545/zn   rms 8.56 px
# The navel-level inscription measures flat: its coefficient is 17x smaller than the
# trace's own 5.5 px noise floor, so it is recorded as exactly zero rather than as a
# 0.0003 arc we cannot distinguish from ink width. The arc therefore GROWS with height,
# which is the diagram's most conspicuous feature after the arcing itself.
#
# Exponent: |xn|**1 fits crease 0.74 slightly better (rms 5.71 px vs 8.56) and |xn|**3
# fits crease 0.52 better (2.54 vs 3.48), i.e. the true profile is flat-topped then
# nearly straight. **2 is used for all three because it is even in x BY CONSTRUCTION
# with a continuous derivative on the midline — a |xn|**1 arc would put a crease kink
# exactly on the linea alba, which is where the symmetry gate is most sensitive — and
# its worst-case error, 8.56 px, is 0.0089 zn, 4% of one segment height.
_ABS_V2_ARC = (0.0000, 0.1717, 0.3545)  # for creases 0.30, 0.52, 0.74
# The trace only reaches |xn| = 0.55 (past that the crease merges with the semilunaris),
# so the arc is HELD at its |xn| = 0.58 value further out instead of extrapolating a
# parabola into data we do not have. Unclamped it would reach 0.27 zn at the pattern's
# lateral fade — more than a whole segment — on the strength of nothing.
_ABS_V2_ARC_XN_CLAMP = 0.58

# (c) Costal margin. Top-boundary row per column, both sides, |xn| <= 0.67, n = 247,
# least-squares quadratic row = 793.872*u**2 - 456.977*u + 467.423, rms 14.85 px against
# a drawn line ~12 px thick. Rewritten as a drop below the apex: A*(|xn| - u0)**2 with
# A = 793.872/960.5 = 0.8265 zn and the apex at u0 = 0.2878. The apex sits OFF the
# midline, and the midline itself is 0.0685 zn lower — that notch is the xiphoid, and
# it is why the boundary is a pair of domes rather than one arch. Held constant beyond
# |xn| = 0.67, again the edge of the traced data.
_ABS_V2_COSTAL_A = 0.8265
_ABS_V2_COSTAL_U0 = 0.2878
_ABS_V2_COSTAL_CLAMP = 0.67


def _abs_pattern(anatomy):
    """Which AFS p.30 rectus pattern this CHARACTER carries. Returns (pattern, source).

    THE PATTERN IS PER-CHARACTER DATA, NOT PROCESS STATE (changed 2026-08-06). It used
    to be a bare env flag defaulting to off, and the reason given for the default was
    exact and still true: v2 moves 151 cage vertices on originals/male and 148 on
    derived/cornelis, so flipping one global switch makes BOTH stop matching the
    cage_vert_sha256 the registry recorded, and _rebuild_from_params / Subject.from_registry
    then refuse to gate either of them. One process-wide boolean cannot say "the body
    that is being re-issued gets the corrected pattern and the body that is not, does
    not" — so it forced a choice between shipping a known-wrong pattern and switching the
    gate engine off for a character nobody was re-issuing.

    Recording the pattern in the character's own anatomy_layer removes the choice. The
    key travels in params.json, so a rebuild reproduces whatever that body was issued
    with, forever, and two characters can legitimately differ. originals/male is being
    re-issued this wave and carries %r; derived/cornelis is NOT in scope, carries no key,
    and therefore keeps v1 and keeps its hash and its gate.

    ZYG_ABS_PATTERN_V2 survives as a THREE-STATE OVERRIDE for audit and rollback:
      unset  -> the character's own anatomy_layer decides (absent key = v1)
      =1     -> force v2 on every body in the process
      =0     -> force v1 on every body in the process. This is the rollback lever: with
                it set, every cage in the repo is byte-identical to the pre-2026-08-06
                geometry regardless of what any anatomy_layer says.
    """ % ABS_PATTERN_V2
    env = os.environ.get('ZYG_ABS_PATTERN_V2', '').strip().lower()
    if env in ('1', 'true', 'yes', 'on'):
        return ABS_PATTERN_V2, 'ZYG_ABS_PATTERN_V2=1 (process override)'
    if env in ('0', 'false', 'no', 'off'):
        return ABS_PATTERN_V1, 'ZYG_ABS_PATTERN_V2=0 (process override)'
    want = (anatomy or {}).get(ABS_PATTERN_KEY)
    if want is None:
        return ABS_PATTERN_V1, 'anatomy_layer carries no %r' % ABS_PATTERN_KEY
    want = str(want)
    if want not in ABS_PATTERNS:
        # a typo here would silently ship the wrong belly on a hashed, immutable body
        raise ValueError(
            'anatomy_layer[%r] = %r is not one of %s' % (ABS_PATTERN_KEY, want, ', '.join(map(repr, ABS_PATTERNS)))
        )
    return want, 'anatomy_layer'


def _abs_v2_sheath_width(zn):
    """Rectus-sheath half-width at height zn, relative to the mid-abdominal plateau."""
    return np.interp(zn, _ABS_V2_W_ZN, _ABS_V2_W)


def _abs_v2_costal_drop(ax):
    """How far below the costal margin's apex the margin sits at |xn| = ax, in zn.

    ax must already be |xn|: the caller passes np.abs(xn) so the curve is even in x by
    construction and the two halves of the pattern cannot drift apart.
    """
    u = np.minimum(ax, _ABS_V2_COSTAL_CLAMP)
    return _ABS_V2_COSTAL_A * (u - _ABS_V2_COSTAL_U0) ** 2


def _apply_abs_definition(v, faces, anatomy):
    """Sculpted definition layer on the CAGE, after morphs, before export/subdivision.

    abs_definition: rectus abdominis relief — linea alba groove, transverse tendinous
    intersections, linea semilunaris borders, bellies bulging between them. The region
    is anchored between two MEASURED MakeHuman landmarks: the navel ring
    (stomach-navel-out support) at the bottom and the pectoral target's lower edge at
    the top — the stomach-tone support alone is belly-centric and stops at the navel,
    which is why a tone-anchored pattern cannot produce upper abs.

    PATTERN v2 (2026-08-06), selected PER CHARACTER by anatomy_layer['abs_pattern'] —
    see _abs_pattern() for why it is data and not a process flag. The pattern this
    function shipped with is the diagram Anatomy for Sculptors p.30 prints under a red X:
    flat horizontal creases, constant-width segments, straight top edge. v2 replaces it
    with the green-check one — arched inscriptions, a height-varying sheath width, and a
    top boundary on the costal margin — from constants digitised off that page (see the
    _ABS_V2_* block above for the traces, fits and residuals). A body whose anatomy_layer
    does not name a pattern gets v1 byte for byte; nothing else in this function branches
    on it. Choosing v2 CHANGES THE CAGE HASH, so a body that already shipped and is not
    being re-issued must not be given the key — it would be REFUSED by the
    cage_vert_sha256 check in _rebuild_from_params / gates.Subject.from_registry, and
    that refusal is the design working, not a regression.

    SYMMETRIC BY CONSTRUCTION (2026-08-05). This layer used to break the cage's mirror
    symmetry: the male original measured 0.0632 mm max mirror deviation BEFORE it and
    3.7648 mm after, which is what t3_morph_symmetry was blocking on. The cause was
    measured, not guessed, and it was NOT the selection: of the 228 selected verts,
    exactly 0 had a mirror partner that fell outside the selection, and the scalar
    amplitude field (even in x by construction) differed between mirror partners by at
    most 0.0500 mm. It was the VERTEX NORMALS — and structurally, not as float noise.
    anny's quad set is a perfect mirror image of itself (13710 of 13710 quads present
    with reversed winding, 0 missing), but 10265 of those mirrored quads are STORED
    STARTING AT A DIFFERENT CORNER, and _vertex_normals takes each face normal from a
    triangle over corners (0,1,2) only. On a non-planar quad — median warp 0.33 mm,
    max 11.1 mm on this cage — a different starting corner is a different triangle, so
    a quad and its mirror contribute different directions AND different areas. Measured
    max |n - mirror(n_partner)|: 1.168 over the whole cage, 0.225 over this selection;
    a Newell all-four-corner normal (cyclic-invariant) drops it to 2.4e-3, which is the
    confirmation. _vertex_normals is deliberately NOT changed here: it is shared,
    hash-pinned geometry with its own callers.

    So the DISPLACEMENT FIELD is symmetrised instead, which is exact against both
    candidate mechanisms at once. The mirror pairing is established once by exact
    nearest-neighbour against the x-negated cage, kept only where it is MUTUAL
    (i->j->i), and each vertex's displacement becomes the mean of its own and its
    partner's x-negated one. Midline verts pair with themselves, so this drives their
    x-displacement to exactly zero — they stay on the midline. Verts with no partner
    inside the tolerance keep their own displacement and are REPORTED (loudly, and in
    _apply_abs_definition.last_symmetry); they are never silently dropped.

    Determinism: cage_vert_sha256 must not depend on torch's thread count. There are no
    unordered reductions here — the pairing is a stable z-sort plus np.argmin (lowest
    index wins ties), `have`/`write` come from np.nonzero/np.unique (sorted), and the
    average is one elementwise expression. Verified byte-identical at 1 and 16 threads.
    v2 adds only elementwise arithmetic plus np.interp and np.minimum, so it introduces
    no reduction whose order a thread count could change.
    """
    s = float((anatomy or {}).get('abs_definition') or 0.0)
    if s <= 0.0:
        # cleared, not left stale: last_symmetry is a module attribute, so a body with no
        # abs layer used to leave the PREVIOUS body's record standing for anyone who read
        # it afterwards. Same convention as relief.apply_relief.last_report.
        _apply_abs_definition.last_symmetry = {
            'abs_definition': 0.0,
            'status': 'absent',
            'reason': "anatomy carries no 'abs_definition'",
        }
        return v
    P64 = v.astype(np.float64)
    nav_idx, _ = _morph_support('stomach-navel-out', 0.0002)
    pec_idx, _ = _morph_support('torso-muscle-pectoral-incr', 0.0002)
    tone_idx, _ = _morph_support('stomach-tone-incr')
    navel_z = float(P64[nav_idx, 2].mean())
    pec_lo_z = float(np.percentile(P64[pec_idx, 2], 12))
    # p97, NOT max: the support's extreme |x| verts sit within one float32 quantum of
    # the membership threshold — a max would let a 5e-9 numerical wobble move the whole
    # pattern by millimetres; a high percentile is continuous under such flips
    xh = max(float(np.percentile(np.abs(P64[tone_idx, 0]), 97.0)), 1e-6)
    z_lo = navel_z - 0.35 * (pec_lo_z - navel_z)
    z_hi = pec_lo_z + 0.10 * (pec_lo_z - navel_z)
    # front-of-torso verts inside the rectus box (front = smaller y in anny's frame)
    y_mid = float(np.median(P64[tone_idx, 1]))
    sel = np.nonzero(
        (P64[:, 2] >= z_lo) & (P64[:, 2] <= z_hi) & (np.abs(P64[:, 0]) <= xh * 0.95) & (P64[:, 1] <= y_mid + 0.02)
    )[0]
    if not len(sel):
        return v
    P = P64[sel]
    n = _vertex_normals(v, faces)[sel]
    xn = P[:, 0] / xh
    zn = (P[:, 2] - z_lo) / max(z_hi - z_lo, 1e-6)
    pattern, pattern_source = _abs_pattern(anatomy)
    use_v2 = pattern == ABS_PATTERN_V2  # named, not inlined: the branch is read twice
    if use_v2:
        # AFS p.30. Everything lateral is built from |xn| so the two halves of the
        # pattern are the same expression evaluated on the same numbers — the field is
        # even in x BY CONSTRUCTION, before the displacement symmetriser below ever
        # runs. See the constants block for the digitised numbers and their fits.
        ax = np.abs(xn)
        # (b) one lateral coordinate, scaled by the sheath's half-width at this height,
        # carries the taper into the belly mask, the semilunaris groove and the lateral
        # fade at once. The linea alba groove is deliberately NOT scaled: the diagram
        # draws it as two parallel lines of constant separation, so scaling it would be
        # inventing a number the reference does not contain.
        xw = ax / _abs_v2_sheath_width(zn)
        costal = _abs_v2_costal_drop(ax)
        # (c) the top of the pattern fades out along the costal margin instead of along
        # a horizontal line. Same smoothstep as _band(zn, 0.06, 0.97), with the upper
        # edge alone evaluated on the warped height; the lower edge is the pubic end and
        # is untouched. costal == 0 reproduces _band exactly.
        up = np.clip((zn - 0.06) / 0.10, 0, 1)
        dn = np.clip((0.97 - (zn + costal)) / 0.10, 0, 1)
        edge = (up * up * (3 - 2 * up)) * (dn * dn * (3 - 2 * dn)) * _band(xw, -1.0, 0.88, 0.15)
        rectus = np.exp(-((xw / 0.46) ** 2))
        # (a) each inscription is pulled down by arc*|xn|^2 as it runs outward, by an
        # amount that grows with height; the topmost "crease" is the costal margin
        # itself, so it takes the margin's shape rather than a parabola.
        acl = np.minimum(ax, _ABS_V2_ARC_XN_CLAMP) ** 2
        cr = np.zeros_like(xn)
        for zi, arc in zip((0.30, 0.52, 0.74), _ABS_V2_ARC):
            cr += np.exp(-(((zn - (zi - arc * acl)) / 0.06) ** 2))
        cr += np.exp(-(((zn - (0.94 - costal)) / 0.06) ** 2))
        cr = np.clip(cr, 0, 1)
        semi = -0.0050 * np.exp(-(((xw - 0.58) / 0.09) ** 2))
    else:
        edge = _band(zn, 0.06, 0.97) * _band(np.abs(xn), -1.0, 0.88, 0.15)
        rectus = np.exp(-((xn / 0.46) ** 2))
        cr = np.zeros_like(xn)
        for zi in (0.30, 0.52, 0.74, 0.94):
            cr += np.exp(-(((zn - zi) / 0.06) ** 2))
        cr = np.clip(cr, 0, 1)
        semi = -0.0050 * np.exp(-(((np.abs(xn) - 0.58) / 0.09) ** 2))
    mid = -0.0070 * np.exp(-((xn / 0.13) ** 2))
    crease = -0.0050 * cr * rectus
    # the bellies BETWEEN the creases are what makes the six-pack read — the bulge
    # carries more of the relief than the grooves do
    belly = 0.0060 * rectus * (1.0 - cr)
    # amplitudes are tuned on the adult male original (band ~0.29m navel->pec);
    # scale with the actual band so a child body gets proportional relief, not
    # adult-depth 20mm gouges on a small torso
    ascale = min(1.25, max(0.30, (z_hi - z_lo) / 0.29))
    disp = (mid + semi + crease + belly) * edge * s * ascale

    # ---- symmetrise the displacement field (see the docstring for the measured cause)
    D = np.zeros_like(P64)
    D[sel] = n * disp[:, None]

    stature = max(float(P64[:, 2].max() - P64[:, 2].min()), 1e-6)
    # 1.0 mm on a 1.85 m body. The worst REAL mirror residual measured on the issued
    # male cage is 0.0632 mm (anny's skinning is not bit-symmetric), and the closest two
    # distinct cage verts anywhere are 0.2517 mm apart — so this tolerance sits ~16x
    # above the noise it must accept and the mutual-pair test below catches the rest.
    tol = 5.4e-4 * stature
    win = 20.0 * tol  # z-slab half-width for the pruned search
    zorder = np.argsort(P64[:, 2], kind='stable')
    zs = P64[zorder, 2]

    def _mirror_of(idx):
        """Exact nearest cage vertex to each P64[idx] reflected through x=0.

        z-slab pruned and still exact where it matters: a winner found at distance <=
        win IS the global nearest (everything outside the slab is further than win by
        construction), and a winner further than win is further than `tol` too, so it
        is rejected as unpaired either way. Deterministic — stable sort, np.argmin
        (lowest index on ties), fixed loop order.
        """
        q = P64[idx].copy()
        q[:, 0] *= -1.0
        lo = np.searchsorted(zs, q[:, 2] - win, 'left')
        hi = np.searchsorted(zs, q[:, 2] + win, 'right')
        mate = np.full(len(idx), -1, np.int64)
        dist = np.full(len(idx), np.inf)
        for k in range(len(idx)):
            a, b = int(lo[k]), int(hi[k])
            if b <= a:
                continue
            d2 = ((P64[zorder[a:b]] - q[k]) ** 2).sum(axis=1)
            j = int(np.argmin(d2))
            mate[k] = zorder[a + j]
            dist[k] = float(np.sqrt(d2[j]))
        return mate, dist

    mate_s, dist_s = _mirror_of(sel)
    ok = dist_s <= tol
    # a pair is usable only if it is MUTUAL (i -> j -> i). A one-way match would
    # symmetrise i against j while j symmetrises against somebody else, which is not a
    # symmetry at all — better to report it than to average the wrong two verts.
    if ok.any():
        back, _ = _mirror_of(mate_s[ok])
        ok[np.nonzero(ok)[0][back != sel[ok]]] = False
    mate = np.full(len(P64), -1, np.int64)
    mate[sel[ok]] = mate_s[ok]
    mate[mate_s[ok]] = sel[ok]  # partners outside `sel` take their half too

    Dsym = D.copy()
    have = np.nonzero(mate >= 0)[0]
    if len(have):
        M = D[mate[have]].copy()
        M[:, 0] *= -1.0
        Dsym[have] = 0.5 * (D[have] + M)

    lost = sel[~ok]
    if len(lost):
        _zyg_log.info(
            '  WARNING: abs_definition — %d of %d selected verts have NO mutual '
            'mirror partner within %.4f mm (indices %s%s). Their displacement is '
            'kept UNSYMMETRISED, so the abs layer is asymmetric for them; the cage '
            'itself is not mirror-symmetric there.'
            % (len(lost), len(sel), tol * 1000, [int(i) for i in lost[:12]], ' …' if len(lost) > 12 else '')
        )

    write = np.unique(np.concatenate([sel, have]))
    out = v.copy()
    out[write] = (P64[write] + Dsym[write]).astype(v.dtype)

    # measured on the WRITTEN cage, not on Dsym: sub-float32-quantum displacements do
    # not survive the cast, and the number an operator reads should be the number of
    # cage verts that actually moved
    moved = np.linalg.norm(out.astype(np.float64) - P64, axis=1)
    resid = 0.0
    if len(have):
        R = Dsym[mate[have]].copy()
        R[:, 0] *= -1.0
        resid = float(np.abs(Dsym[have] - R).max())
    _apply_abs_definition.last_symmetry = {
        'abs_definition': s,
        # which of the two AFS p.30 diagrams this cage carries. Recorded because the
        # cage hash differs between them and an operator holding a mesh needs to be able
        # to tell which pattern produced it without re-running the build.
        'abs_pattern': pattern,
        'abs_pattern_source': pattern_source,
        'selected': int(len(sel)),
        'paired': int(len(have)),
        'self_paired': int((mate[have] == have).sum()),
        'unpaired': [int(i) for i in lost],
        'pair_tolerance_m': tol,
        'max_pair_residual_m': (float(dist_s[ok].max()) if ok.any() else None),
        'displaced': int((moved > 1e-9).sum()),
        'max_displacement_m': float(moved.max()),
        'field_residual_m': resid,
    }
    return out


_apply_abs_definition.last_symmetry = None
