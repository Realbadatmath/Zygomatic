# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Region masks and the per-landmark resolvers."""

from zyg_workflows.geom.anthro.landmarks.constants import (
    MS,
    REF_MALE,
    _CACHE,
    _anny_waist_ring,
    _check_topology,
    _support,
    _support_core,
    np,
)


# ---------------------------------------------------------------------------------
# region masks and resolvers
# ---------------------------------------------------------------------------------
def _context(v, faces):
    v = np.asarray(v, np.float64)
    _check_topology(v, faces)
    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    if H <= 0:
        raise ValueError('degenerate mesh: zero stature')
    return {
        'v': v,
        'faces': np.asarray(faces),
        'zmin': zmin,
        'H': H,
        'fz': (v[:, 2] - zmin) / H,
        'n': MS._vertex_normals(v, faces),
    }


def _mask(ctx, region, base=None):
    """Region masks are expressed in FRACTIONS OF STATURE so one table works on a 1.52m
    child and a 1.85m adult without retuning."""
    v, H, fz = ctx['v'], ctx['H'], ctx['fz']
    m = np.ones(len(v), bool) if base is None else base.copy()
    if 'fz' in region:
        lo, hi = region['fz']
        m &= (fz >= lo) & (fz <= hi)
    side = region.get('side')
    if side == 'l':
        m &= v[:, 0] > 0
    elif side == 'r':
        m &= v[:, 0] < 0
    if 'xabs' in region:
        lo, hi = region['xabs']
        a = np.abs(v[:, 0]) / H
        m &= (a >= lo) & (a <= hi)
    if 'y' in region:
        lo, hi = region['y']
        m &= (v[:, 1] / H >= lo) & (v[:, 1] / H <= hi)
    if 'normal_y_max' in region:
        m &= ctx['n'][:, 1] <= region['normal_y_max']
    return m


_AXIS = {'x': 0, 'y': 1, 'z': 2}


def _r_extreme(ctx, side, axis, sign, region):
    m = _mask(ctx, dict(region, side=side) if side else region)
    idx = np.nonzero(m)[0]
    if not len(idx):
        return None
    a = ctx['v'][idx, _AXIS[axis]] * sign
    return np.array([idx[int(np.argmax(a))]])


def _r_support(ctx, side, label, thresh=3e-4, ref='male', region=None):
    s = _support(label, thresh, ref)
    if s is None:
        return None
    idx = s[0]
    if side or region:
        m = np.zeros(len(ctx['v']), bool)
        m[idx] = True
        m = _mask(ctx, dict(region or {}, **({'side': side} if side else {})), m)
        idx = np.nonzero(m)[0]
    return idx if len(idx) else None


def _r_support_core(ctx, side, core_label, core=0.8, region=None):
    s = _support_core(core_label, core)
    if s is None:
        return None
    idx = s[0]
    if side or region:
        m = np.zeros(len(ctx['v']), bool)
        m[idx] = True
        m = _mask(ctx, dict(region or {}, **({'side': side} if side else {})), m)
        idx = np.nonzero(m)[0]
    return idx if len(idx) else None


def _r_support_extreme(ctx, side, label, axis, sign, thresh=3e-4, ref='male', region=None):
    idx = _r_support(ctx, side, label, thresh, ref, region)
    if idx is None:
        return None
    a = ctx['v'][idx, _AXIS[axis]] * sign
    return np.array([idx[int(np.argmax(a))]])


def _r_ring_const(ctx, side, which='anny_waist'):
    idx = _anny_waist_ring()
    if side:
        m = np.zeros(len(ctx['v']), bool)
        m[idx] = True
        idx = np.nonzero(_mask(ctx, {'side': side}, m))[0]
    return idx


def _coronal_profile(ctx, fz_lo, fz_hi, half=0.012, step=0.002, y=(-0.16, 0.06), xabs_max=None):
    """Upper envelope of the subject's LEFT coronal silhouette, as half-breadth in units
    of stature, sampled on a height grid — plus the vertex that produced each sample.

    A MOVING MAX over a +/-`half` window, not a thin slab. The cage's vertex rows are not
    horizontal, so a 0.004-stature slab often contains no vertex anywhere near the
    lateral extreme and reports a breadth 40% too small: measured on the neutral, the
    slab at 0.528 of stature returned 75.9mm against 159.0mm one slab below. Those
    holes are indistinguishable from a genuine waist and would have been reported as one
    (they were, before this was fixed: the neutral's "waist minimum" came out at 0.530).

    xabs_max exists because the A-posed arm crosses the torso's own height band: over
    0.52-0.70 of stature the unrestricted silhouette is the forearm, not the waist.
    """
    v, fz, H = ctx['v'], ctx['fz'], ctx['H']
    grid = np.arange(fz_lo, fz_hi + 1e-9, step)
    w = np.full(len(grid), np.nan)
    vi = np.full(len(grid), -1, np.int64)
    ok = (v[:, 1] / H >= y[0]) & (v[:, 1] / H <= y[1]) & (v[:, 0] > 0)
    if xabs_max is not None:
        ok &= v[:, 0] / H <= xabs_max
    sel = np.nonzero(ok)[0]
    if not len(sel):
        return grid[:0], w[:0], vi[:0]
    fzs, xs = fz[sel], v[sel, 0]
    for k, g in enumerate(grid):
        s = np.nonzero(np.abs(fzs - g) <= half)[0]
        if len(s):
            j = int(s[int(np.argmax(xs[s]))])
            w[k] = xs[j] / H
            vi[k] = sel[j]
    good = ~np.isnan(w)
    return grid[good], w[good], vi[good]


def _r_coronal_min(ctx, side, fz=(0.80, 0.92), y=(-0.16, 0.06), xabs_max=None, half=0.012):
    b, w, vi = _coronal_profile(ctx, fz[0], fz[1], half=half, y=y, xabs_max=xabs_max)
    if not len(b):
        return None
    g = float(b[int(np.argmin(w))])
    # The envelope's donor vertex can sit up to `half` away from the minimum, so it is
    # the wrong point to report: re-select the widest vertex AT the minimum's height.
    # Without this the reported height wandered by 0.028 of stature (52mm on the male)
    # purely with the smoothing window — measured.
    v, H, fzv = ctx['v'], ctx['H'], ctx['fz']
    ok = (v[:, 1] / H >= y[0]) & (v[:, 1] / H <= y[1]) & (v[:, 0] > 0)
    if xabs_max is not None:
        ok &= v[:, 0] / H <= xabs_max
    for tol in (0.004, 0.008, half):
        s = np.nonzero(ok & (np.abs(fzv - g) <= tol))[0]
        if len(s):
            break
    if not len(s):
        return None
    idx = int(s[int(np.argmax(v[s, 0]))])
    if side == 'r':
        idx = int(_mirror(ctx)[idx])
    return np.array([idx])


def _mirror(ctx):
    """Index map to the mirrored vertex. The cage is symmetric to 0.017mm (measured), so
    an L landmark's R twin is exact rather than re-searched — re-searching would let the
    two sides disagree by a vertex and manufacture asymmetry that is not in the mesh."""
    if 'mirror' in _CACHE:
        return _CACHE['mirror']
    from scipy.spatial import cKDTree

    v0, _, _ = MS._build_mesh(REF_MALE, None)
    mir = v0.astype(np.float64).copy()
    mir[:, 0] *= -1
    _, j = cKDTree(v0.astype(np.float64)).query(mir)
    _CACHE['mirror'] = j
    return j


def _r_suprasternale(ctx, side, fz=(0.74, 0.855)):
    """The jugular notch resolved by its own definition: on the anterior midline the
    surface runs forward into the chest below and forward into the throat above, so the
    notch is the unique LEAST-ANTERIOR point of that strip. Measured on the anny neutral:
    y = -178.1mm at 0.770 of stature, -141.8mm at 0.820, -155.0mm at 0.850 — a clean
    interior maximum at 0.820 against ANSUR suprasternale 0.8191."""
    m = _mask(ctx, {'fz': fz, 'xabs': (0.0, 0.006), 'normal_y_max': -0.2})
    idx = np.nonzero(m)[0]
    if not len(idx):
        return None
    return np.array([idx[int(np.argmax(ctx['v'][idx, 1]))]])


def _r_acromion(ctx, side, slab=0.015):
    """Top of the shoulder surface in a thin coronal slab through the glenohumeral centre.

    Why not the shoulder silhouette corner: in this A-pose the deltoid projects further
    laterally than the acromion, so the 45-degree tangent point of the coronal silhouette
    lands on the deltoid — measured 0.7933 of stature on the issued male against ANSUR
    0.8203, and it implies a 653mm biacromial breadth against a 416mm survey mean. That
    is the biacromial-vs-bideltoid definition trap producing a 237mm error.
    Why a slab and not a disc: the shoulder surface rises continuously toward the neck,
    so an unbounded max-z is pinned by whatever search radius you pick. The slab is
    centred on an anatomical point instead.
    THE X COORDINATE OF THIS LANDMARK IS THE SLAB CENTRE, NOT A BIACROMIAL SEMI-BREADTH.
    """
    kp = ctx.get('coco')
    if not kp:
        return None
    p = kp['left_shoulder' if side == 'l' else 'right_shoulder']
    v, H = ctx['v'], ctx['H']
    m = (np.abs(v[:, 0] - p[0]) < slab * H) & _mask(ctx, {'fz': (0.70, 0.92), 'y': (-0.18, 0.08)})
    idx = np.nonzero(m)[0]
    if not len(idx):
        return None
    return np.array([idx[int(np.argmax(v[idx, 2]))]])


def _r_trochanterion(ctx, side, band=0.012):
    """Lateral-most surface point at the height of the femoral-head centre.

    The greater trochanter has no surface signature on this cage — the lateral profile
    through the pelvis is monotone — so the height comes from anny's own hip joint centre
    (measured 0.5134 of stature on the neutral mesh against ANSUR trochanterion 0.5128)
    and only the lateral projection is read off the surface.
    """
    kp = ctx.get('coco')
    if not kp:
        return None
    p = kp['left_hip' if side == 'l' else 'right_hip']
    v, H = ctx['v'], ctx['H']
    m = (np.abs(v[:, 2] - p[2]) < band * H) & _mask(ctx, {'side': side, 'y': (-0.16, 0.06), 'xabs': (0.0, 0.20)})
    idx = np.nonzero(m)[0]
    if not len(idx):
        return None
    a = v[idx, 0] * (1 if side == 'l' else -1)
    return np.array([idx[int(np.argmax(a))]])


def _r_dactylion(ctx, side):
    """Fingertip: the hand vertex furthest from the wrist ring centroid. Direction-free,
    so it survives the A-pose without assuming which way the fingers point."""
    hand = _r_support(ctx, side, 'l-hand-fingers-length-incr' if side == 'l' else 'r-hand-fingers-length-incr')
    wrist = _r_support(ctx, side, 'measure-wrist-circ-incr', region={'side': side})
    if hand is None or wrist is None:
        return None
    c = ctx['v'][wrist].mean(0)
    d = np.linalg.norm(ctx['v'][hand] - c, axis=1)
    return np.array([hand[int(np.argmax(d))]])


def _r_unresolved(ctx, side, **kw):
    return None


_RESOLVERS = {
    'extreme': _r_extreme,
    'support': _r_support,
    'support_core': _r_support_core,
    'support_extreme': _r_support_extreme,
    'ring_const': _r_ring_const,
    'coronal_min': _r_coronal_min,
    'suprasternale': _r_suprasternale,
    'acromion': _r_acromion,
    'trochanterion': _r_trochanterion,
    'dactylion': _r_dactylion,
    'unresolved': _r_unresolved,
}
