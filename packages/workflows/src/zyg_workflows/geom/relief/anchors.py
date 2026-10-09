# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anchors — a verbatim section of the pre-split relief.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

import numpy as np  # noqa: F401

from zyg_workflows.geom.relief.constants import (  # noqa: F401
    AMP,
    ASPECT_MIN_DOT,
    CLAVICLE_N_STATIONS,
    CLAVICLE_S_AMPLITUDE_FRAC,
    CLAVICLE_S_CROSSING,
    CREST_AZIMUTH_DEG,
    CREST_DROP_ANTERIOR_FRAC,
    CREST_DROP_POSTERIOR_FRAC,
    CREST_N_STATIONS,
    FACET_CAP_FRAC,
    FALLOFF_FRAC,
    MALLEOLUS_HEIGHT_OFFSET_FRAC,
    MALLEOLUS_LAT_POSTERIOR_FRAC,
    MIRROR_TOL_FRAC,
    NUCHAL_N_STATIONS,
    PERP_MAX_FRAC,
    PSIS_BELOW_CREST_FRAC,
    PSIS_HALF_SEPARATION_FRAC,
    STATION_SPACING_FRAC,
    TIBIAL_FACET_CURVATURE_TARGET_FRAC,
    TISSUE_MAX_FRAC,
    TISSUE_MIN_FRAC,
    ULNAR_BORDER_N_STATIONS,
)
from zyg_workflows.geom.relief.primitives import (  # noqa: F401
    mirror_map,
    newell_vertex_normals,
)


# ---------------------------------------------------------------------------------
# seeding — putting an anatomical anchor onto the actual surface
# ---------------------------------------------------------------------------------


class _Ctx(object):
    """Everything the anchor builders read. Assembled once."""

    def __init__(self, v, faces, bones, weights, bone_names, macros, stature_m=None):
        self.v = np.asarray(v, np.float64)
        self.faces = np.asarray(faces)
        self.bones = bones
        self.W, self.I = weights if weights is not None else (None, None)
        self.bone_names = list(bone_names)
        self.macros = dict(macros or {})
        self.S = float(self.v[:, 2].max() - self.v[:, 2].min()) if stature_m is None else float(stature_m)
        self.z0 = float(self.v[:, 2].min())
        self.n = newell_vertex_normals(self.v, self.faces)
        from zyg_workflows.geom.form import ridge as RD

        self.shell = RD.shell_mask(self.v, self.faces)
        self.mate, self.mdist = mirror_map(self.v, MIRROR_TOL_FRAC * self.S)

    def fz(self):
        return (self.v[:, 2] - self.z0) / self.S

    def bone(self, name):
        if name not in self.bones:
            raise KeyError('bone %r is not on this rig' % name)
        return self.bones[name]

    def sex(self):
        return 'female' if float(self.macros.get('gender', 0.0)) >= 0.5 else 'male'


def _unit(a):
    a = np.asarray(a, np.float64)
    n = float(np.linalg.norm(a))
    return a / n if n > 1e-12 else a


def _resample(points, aspect, S, spacing_frac=STATION_SPACING_FRAC):
    """Arc-length resample an anchor polyline (and its per-point aspects) to one station
    every spacing_frac of stature. See STATION_SPACING_FRAC for why this exists."""
    P = np.asarray(points, np.float64)
    if len(P) < 2:
        return P, aspect
    A = (
        np.asarray([_unit(a) for a in aspect], np.float64)
        if np.ndim(aspect) == 2
        else np.repeat(_unit(aspect)[None], len(P), 0)
    )
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    L = float(arc[-1])
    if L <= 0:
        return P, A
    n = max(2, int(round(L / (spacing_frac * S))) + 1)
    t = np.linspace(0.0, L, n)
    out = np.stack([np.interp(t, arc, P[:, k]) for k in range(3)], axis=1)
    oa = np.stack([np.interp(t, arc, A[:, k]) for k in range(3)], axis=1)
    oa = oa / np.maximum(np.linalg.norm(oa, axis=1, keepdims=True), 1e-12)
    return out, oa


def _curve(points, aspect, S):
    """A curve feature's (points, aspects), resampled to the station rule."""
    return _resample(points, aspect, S)


def _snap(ctx, points, aspect, region=None, min_dot=ASPECT_MIN_DOT):
    """Put a list of 3D anchor points onto the skin OVER them, by ray projection.

    For each anchor p with aspect a, a candidate vertex q is scored by decomposing q - p
    into a depth t along a and a sideways miss `perp` across it. A candidate qualifies
    when it is on the body shell, inside `region` if one is given, its own outward normal
    points along a (so it is the OUTSIDE of that aspect, not the far wall of the same
    limb), and its depth is inside [TISSUE_MIN_FRAC, TISSUE_MAX_FRAC] of stature. The
    winner is the SMALLEST SIDEWAYS MISS, which is the vertex the ray actually hits — not
    the nearest vertex in 3D, which for a 53 mm deep sternoclavicular joint is frequently
    a different structure.

    A miss over PERP_MAX_FRAC of stature is REFUSED and listed with its numbers. Refusing
    is the point: a silent long snap is how a clavicle predicate ends up on the trapezius.

    Returns (seed indices in first-seen order, per-point (perp, depth), refused points).
    """
    aspect = (
        np.asarray([_unit(a) for a in aspect], np.float64)
        if np.ndim(aspect) == 2
        else np.repeat(_unit(aspect)[None], len(points), 0)
    )
    base = ctx.shell.copy()
    if region is not None:
        base &= region
    normal_ok = None
    seeds, perps, depths, refused = [], [], [], []
    seen = set()
    pmax = PERP_MAX_FRAC * ctx.S
    tlo, thi = TISSUE_MIN_FRAC * ctx.S, TISSUE_MAX_FRAC * ctx.S
    for k, p in enumerate(points):
        a = aspect[k]
        rel = ctx.v - p
        t = rel.dot(a)
        perp = np.linalg.norm(rel - t[:, None] * a[None], axis=1)
        normal_ok = ctx.n.dot(a) >= min_dot
        ok = base & normal_ok & (t >= tlo) & (t <= thi)
        idx = np.nonzero(ok)[0]
        if not len(idx):
            refused.append(
                {
                    'point': [float(x) for x in p],
                    'n_on_aspect': int((base & normal_ok).sum()),
                    'why': 'no shell vertex whose normal is on this aspect '
                    '(dot >= %.2f) lies %.0f-%.0f mm along it' % (min_dot, 1e3 * tlo, 1e3 * thi),
                }
            )
            continue
        j = int(idx[int(np.argmin(perp[idx]))])
        pm, tm = float(perp[j]), float(t[j])
        if pm > pmax:
            refused.append(
                {
                    'point': [float(x) for x in p],
                    'perp_m': pm,
                    'depth_m': tm,
                    'why': 'the aspect ray misses the nearest qualifying vertex '
                    'by %.1f mm, over the %.1f mm limit' % (1e3 * pm, 1e3 * pmax),
                }
            )
            continue
        perps.append(pm)
        depths.append(tm)
        if j not in seen:
            seen.add(j)
            seeds.append(j)
    return (np.array(seeds, np.int64), np.array(perps, np.float64), np.array(depths, np.float64), refused)


def _mirror_seeds(ctx, seeds):
    """Right-side seeds are the mirror PARTNERS of the left-side ones, never an
    independently snapped set. That is what makes the two halves the same construction on
    the same numbers instead of two searches that can diverge."""
    if not len(seeds):
        return np.array([], np.int64), []
    m = ctx.mate[seeds]
    lost = [int(s) for s, mm in zip(seeds, m) if mm < 0]
    return np.unique(m[m >= 0]), lost


def _falloff(ctx, seeds, radius_frac=FALLOFF_FRAC):
    """Compactly supported raised-cosine weight over the graph geodesic distance from a
    seed set: 1 at the seed, 0 with zero slope at radius_frac of stature, exactly 0 beyond.

    Raised cosine rather than a Gaussian because a Gaussian has infinite support and would
    put a small but nonzero displacement under the probe's collar, which is precisely the
    thing FALLOFF_FRAC exists to prevent.
    """
    from zyg_workflows.geom.form import curvature as CV

    R = radius_frac * ctx.S
    d = CV.surface_distance(ctx.v, ctx.faces, np.sort(np.asarray(seeds, np.int64)), limit_m=R)
    w = np.zeros(len(ctx.v), np.float64)
    m = np.isfinite(d) & (d <= R)
    w[m] = 0.5 * (1.0 + np.cos(np.pi * np.clip(d[m] / R, 0.0, 1.0)))
    return w


# ---------------------------------------------------------------------------------
# the anchors
# ---------------------------------------------------------------------------------


def _clavicle_crest(ctx, side=+1.0):
    """The S-curved clavicular crest line, from the bone.

    AFS p.10: the clavicle is an S in the transverse plane — medial two thirds convex
    ANTERIORLY, lateral third concave anteriorly — so its crest deviates from the bone's
    own chord with exactly ONE anterior-posterior sign change. The chord is the rig's
    clavicle.L segment (sternoclavicular head -> acromial tail); the deviation is
    CLAVICLE_S_AMPLITUDE_FRAC of stature, crossing zero at CLAVICLE_S_CROSSING of the
    shaft.

    NOTE ON WHAT THE PROBE WILL SAY. ridge_relief reports `sign_changes` over the RELIEF
    profile, not over the crest's A-P position. A whole-bone ridge has 0 relief sign
    changes by definition; the geometric A-P sign change asserted here is measured
    separately and reported as `ap_sign_changes` in this module's own record.
    """
    h, t = ctx.bone('clavicle.L' if side > 0 else 'clavicle.R')
    u = _unit(t - h)
    L = float(np.linalg.norm(t - h))
    ap = _unit(np.array([0.0, -1.0, 0.0]) - u * float(np.dot([0.0, -1.0, 0.0], u)))
    ts = np.linspace(0.04, 0.98, CLAVICLE_N_STATIONS)
    c = CLAVICLE_S_CROSSING
    g = np.where(ts <= c, 0.5 * ts / c, 0.5 + 0.5 * (ts - c) / (1.0 - c))
    dev = CLAVICLE_S_AMPLITUDE_FRAC * ctx.S * np.sin(2.0 * np.pi * g)
    pts = h[None] + (ts * L)[:, None] * u[None] + dev[:, None] * ap[None]
    return pts, u, ap, dev, L


def _elbow_posterior(ctx):
    """The extensor side of the elbow, from the rig alone: the outside of the angle the
    upper arm and forearm make at it. Measured on originals/male this is
    (0.178, 0.908, -0.387) — dominantly posterior, and well conditioned because anny's
    A-pose carries a real carrying angle rather than a straight arm."""
    e = ctx.bone('lowerarm01.L')[0]
    p = ctx.bone('upperarm02.L')[0]
    w = ctx.bone('lowerarm01.L')[1]
    return _unit(-(_unit(p - e) + _unit(w - e)))


def _wrist_postero_ulnar(ctx):
    """The postero-ulnar corner of the wrist, from the rig alone.

    ULNAR IS MEASURED, NOT ASSUMED: anny's metacarpal4 is the bone whose tail is
    finger5-1's head, i.e. the fifth metacarpal, so metacarpal4_tail - metacarpal1_tail
    points from the radial side to the ulnar side of the hand. Its component along the
    forearm axis is removed, leaving a direction perpendicular to the forearm — which is
    where the head of the ulna is.
    """
    w0 = ctx.bone('lowerarm02.L')[0]
    w1 = ctx.bone('lowerarm02.L')[1]
    axis = _unit(w1 - w0)
    m4 = ctx.bone('metacarpal4.L')[1]
    m1 = ctx.bone('metacarpal1.L')[1]
    raw = m4 - m1
    return _unit(raw - axis * float(np.dot(raw, axis)))


def _pelvis_axis(ctx):
    """(centre, up) of the pelvis in the transverse plane: x = 0 midline, y from the
    pelvis.L bone head, z free. Used only as the origin of the iliac-crest azimuth
    sweep."""
    h = ctx.bone('pelvis.L')[0]
    return np.array([0.0, float(h[1]), 0.0])


def _crest_points(ctx):
    """The iliac crest arc on the LEFT, as surface-outermost points at a MEASURED height.

    HEIGHT IS MEASURED, ARC IS CONSTRUCTED. landmarks.REFERENCE_FRACTIONS carries
    iliocristale/stature from ANSUR II (male 0.6044 +/- 0.0128, female 0.6113 +/- 0.0129),
    so the crest's height is anthropometric rather than invented. The azimuth sweep, and
    the drops to the ASIS in front and the PSIS behind, are HOUSE. Every record built off
    this carries claim='constructed'.
    """
    from zyg_workflows.geom.anthro import landmarks as LM

    frac = LM.REFERENCE_FRACTIONS['iliocristale'][0 if ctx.sex() == 'male' else 1][0]
    zc = ctx.z0 + frac * ctx.S
    c = _pelvis_axis(ctx)
    a0, a1 = np.radians(CREST_AZIMUTH_DEG)
    phis = np.linspace(a0, a1, CREST_N_STATIONS)
    pts, dirs = [], []
    P = ctx.v
    fzv = ctx.fz()
    for phi in phis:
        d = np.array([np.sin(phi), -np.cos(phi), 0.0])
        drop = (
            CREST_DROP_ANTERIOR_FRAC * max(0.0, np.cos(phi)) + CREST_DROP_POSTERIOR_FRAC * max(0.0, -np.cos(phi))
        ) * ctx.S
        z = zc - drop
        band = ctx.shell & (np.abs(P[:, 2] - z) < 0.012 * ctx.S) & (P[:, 0] > 0.0)
        if not band.any():
            continue
        rel = P[band] - c
        rad = rel[:, :2].dot(d[:2])
        cross = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])
        near = cross < 0.030 * ctx.S
        if not near.any():
            continue
        idx = np.nonzero(band)[0][near]
        r = rad[near]
        j = int(idx[int(np.argmax(r))])
        p = P[j].copy()
        p[2] = z
        pts.append(p)
        dirs.append(d)
    return np.array(pts), np.array(dirs), frac, float(np.degrees(a0)), fzv


def _build_features(ctx):
    """Every feature, as an ordered list of records. One place, explicit, auditable.

    Each record: name, claim ('bone' | 'constructed'), anchor (prose, the thing a reader
    checks), op ('curve' | 'point' | 'pair' | 'facet' | 'control'), amp_frac (SIGNED, in
    fractions of stature), left-side seed points, and the aspect the anchor is
    subcutaneous on.

    The six regional builders live in anchors_features; they are concatenated here in
    the order the records were always appended, and the import is deferred because that
    module reads this one's own anchor primitives.
    """
    from zyg_workflows.geom.relief import anchors_features as AF

    F = []
    F.extend(AF.clavicle_records(ctx))
    F.extend(AF.acromion_records(ctx))
    F.extend(AF.arm_records(ctx))
    F.extend(AF.ankle_and_shank_records(ctx))
    F.extend(AF.pelvis_records(ctx))
    F.extend(AF.neck_records(ctx))
    return F
