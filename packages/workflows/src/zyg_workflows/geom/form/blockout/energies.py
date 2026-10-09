# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blockout — Per-band energies, the waxy constructor, the block-out render and the JSON report."""

from zyg_workflows.geom.form.blockout.spectral import (
    BANDS,
    BAND_MEANING,
    CV,
    LAMBDA_LOW,
    LAMBDA_MID,
    MSTAT,
    PREDICATES,
    WAVELENGTH_LOW_FRAC,
    WAVELENGTH_MID_FRAC,
    __version__,
    _body_quads,
    decompose,
    json,
    np,
    os,
    shell_split,
    sp,
    spectral_basis,
    spl,
    time,
)
from zyg_workflows.geom.form.blockout.regions import (
    region_map,
)


# ---------------------------------------------------------------------------------
# energies
# ---------------------------------------------------------------------------------
def _rms(field, mass, mask, H, centre=True):
    """M-weighted RMS of a per-vertex vector field over a region, in millistature.

    The region mean is removed first. Without that, the LOW band's energy is dominated by
    where the region SITS rather than how big it is — the constant mode reconstructs the
    centroid, so a body translated one metre would report a different block-out energy.
    """
    m = mass[mask]
    tot = float(m.sum())
    if tot <= 0:
        raise ValueError('region has zero surface area, so its RMS is undefined')
    d = field[mask]
    if centre:
        d = d - (m[:, None] * d).sum(0) / tot
    return float(np.sqrt((m * (d * d).sum(1)).sum() / tot)) / H * MSTAT


def band_energies(basis, dec, regions):
    """region -> band -> {rms_mstat, rms_mm, share}.

    rms_mstat is the comparable number (millistature); rms_mm is the same figure at this
    subject's own scale, for arguing about anatomy. `share` is the band's fraction of the
    region's total band energy (sum of squares), which is scale-free twice over — it does
    not move when the body is scaled OR when the region is simply bigger.
    """
    H, mass = basis['stature_m'], basis['mass']
    out = {}
    for name, mask in regions.items():
        if not mask.any():
            continue
        e = {b: _rms(dec[b], mass, mask, H) for b in BANDS}
        tot = sum(x * x for x in e.values())
        out[name] = {
            b: {
                'rms_mstat': round(e[b], 4),
                'rms_mm': round(e[b] * H, 4),
                'share': round(e[b] * e[b] / tot, 6) if tot > 0 else 0.0,
            }
            for b in BANDS
        }
        out[name]['vertices'] = int(mask.sum())
        out[name]['area_m2'] = round(float(mass[mask].sum()), 6)
    return out


def delta_bands(basis, v_a, v_b, regions):
    """Per-band, per-region RMS of the DISPLACEMENT FIELD between two bodies.

    ONE basis is used for both, and that is the point. Band projection is linear, so
    band(a) - band(b) == band(a - b) exactly when both are projected in the same basis;
    decomposing each body in its own basis would mix a change of shape with a change of
    coordinates and the difference would no longer be a band decomposition of anything.
    The basis used is recorded in the result.

    READ THE `total` COLUMN FIRST. LOW and MID are projections onto GLOBAL eigenfunctions,
    so a change confined to the chest still shows up in the low band of the head — MEASURED
    on the pectoral demo: the head region moves by 0.00 mm and still reports 0.63
    millistature of LOW, against 8.14 in the pectoral region. Worse, in a region where the
    change is nearly absent the bands are large and CANCEL (the abdomen reports low 2.62,
    mid 2.35, total 0.69). This is a property of a global basis, not a bug, and there is no
    honest way to localise a band; the defence is to read `total` and `max_mm` to find
    where the change actually is, and only then to read its band split there.
    `band_sum_over_total` makes the cancellation visible per region: a value far above 1
    means that region's band figures are leakage, not signal. HIGH and MICRO come from a
    local operator and do not have this problem.
    """
    a = np.asarray(v_a, np.float64)
    b = np.asarray(v_b, np.float64)
    if a.shape != b.shape:
        raise ValueError('the two bodies must share topology; got %r and %r' % (a.shape, b.shape))
    vid = basis['shells']['vid']
    d = decompose(basis, a[vid] - b[vid])
    H, mass = basis['stature_m'], basis['mass']
    out = {}
    for name, mask in regions.items():
        if not mask.any():
            continue
        # No centring here: this field IS a displacement, and its mean over a region is a
        # real translation of that region, which is exactly the kind of level-1 change the
        # predicate is looking for.
        e = {bnd: _rms(d[bnd], mass, mask, H, centre=False) for bnd in BANDS}
        tot_v = _rms(d['x'], mass, mask, H, centre=False)
        out[name] = {bnd: {'rms_mstat': round(e[bnd], 4), 'rms_mm': round(e[bnd] * H, 4)} for bnd in BANDS}
        out[name]['total'] = {'rms_mstat': round(tot_v, 4), 'rms_mm': round(tot_v * H, 4)}
        out[name]['max_mm'] = round(float(np.linalg.norm(d['x'][mask], axis=1).max()) * 1000.0, 4)
        out[name]['band_sum_over_total'] = (
            round(float(np.sqrt(sum(x * x for x in e.values())) / tot_v), 3) if tot_v > 1e-9 else None
        )
    return {
        'basis': basis.get('name'),
        'stature_m': round(H, 4),
        'regions': out,
        'note': 'low/mid are projections onto GLOBAL eigenfunctions and do not '
        'localise; band_sum_over_total far above 1 marks a region whose band '
        'figures are leakage that cancels. Read total/max_mm first.',
    }


# ---------------------------------------------------------------------------------
# the waxy constructor
# ---------------------------------------------------------------------------------
def smooth(v, faces, sigma_frac, vid=None):
    """One implicit (backward-Euler) Laplacian smoothing step, (M + t L) x' = M x,
    with t = (sigma_frac * stature)^2. Returns a full-cage copy with only the body
    shell moved.

    This is a CONSTRUCTOR for the waxy defect, not a measurement. t is quoted through a
    diffusion LENGTH in fractions of stature so the same call does the same thing to a
    child and to an adult, and the caller is expected to keep sigma_frac small: at
    sigma_frac ~ 0.06 the flow displaces a forearm by more than its own radius (see the
    module docstring), which is not waxy skin, it is amputation.
    """
    v = np.asarray(v, np.float64)
    shells = shell_split(v, faces) if vid is None else None
    vid = shells['vid'] if vid is None else vid
    H = float(v[:, 2].max() - v[:, 2].min())
    W = CV.cotangent_weights(v, faces)[vid][:, vid].tocsr()
    m = CV.mixed_voronoi_area(v, faces)[vid]
    L = (sp.diags(np.asarray(W.sum(axis=1)).ravel()) - W).tocsc()
    M = sp.diags(m).tocsc()
    t = (sigma_frac * H) ** 2
    A = (M + t * L).tocsc()
    lu = spl.splu(A)
    out = v.copy()
    out[vid] = np.column_stack([lu.solve(m * v[vid, k]) for k in range(3)])
    return out


# ---------------------------------------------------------------------------------
# the block-out render
# ---------------------------------------------------------------------------------
def render_blockout(
    v, faces, out_dir, basis=None, band='low', yaws=(0, 45), height_px=1200, ss=2, prefix='blockout', subdiv=None
):
    """Level-1 block-out PNGs — the LOW band alone, rendered as a body.

    A downstream VLM judge is markedly more reliable on a block-out than on a full mesh
    (measured elsewhere in this project: the judge answers surface questions about crops
    and shape questions about simplified forms), and the block-out is also the only image
    in which a level-1 error is the ONLY thing on screen.

    Conventions are mesh_skeletons': orthographic, z-up, camera along +y, the same raking
    key light through mesh_skeletons._paint, Catmull-Clark subdivision with the cage grid
    overlaid, the same 0.62 aspect and 6% margin as a full-body preview. ONE deliberate
    departure: the framing window is computed from the ORIGINAL mesh, not from the band,
    so the block-out lands in the same frame as view_000.png and the two can be blinked
    against each other. Only the body shell is drawn — the eyeballs and the tongue are
    separate shells with no low band of their own (module docstring).
    """
    from zyg_workflows.geom import mesh_skeletons as MS

    if MS.cv2 is None:
        raise RuntimeError(
            'cv2 is not importable, so no preview can be written. '
            'mesh_skeletons._paint is the renderer and it is a cv2 '
            'rasteriser.'
        )
    allowed = ('low', 'lowmid', 'full') + BANDS
    if band not in allowed:
        raise ValueError('band must be one of %s, got %r' % ('/'.join(allowed), band))

    v = np.asarray(v, np.float64)
    if basis is None:
        basis = spectral_basis(v, faces)
    vid = basis['shells']['vid']
    dec = decompose(basis, v[vid])
    if band == 'full':
        pb = dec['x']
    elif band == 'lowmid':
        pb = dec['low'] + dec['mid']
    elif band == 'low':
        pb = dec['low']
    else:
        # MID and HIGH are residual fields with a zero mean; drawn alone they are not a
        # body. Adding them back onto the LOW band shows what that band CONTRIBUTES.
        pb = dec['low'] + dec[band]

    quads, _ = _body_quads(faces, vid, len(v))
    os.makedirs(out_dir, exist_ok=True)

    sub_b = MS._subdivide(pb, quads, MS.DISPLAY_SUBDIV)
    sub_r = subdiv if subdiv is not None else MS._subdivide(v[vid], quads, MS.DISPLAY_SUBDIV)
    emask = MS._edge_mask(sub_b[1], sub_b[2])
    centre = sub_r[0].mean(axis=0)

    paths = []
    for yaw in yaws:
        a = np.radians(yaw)
        R = np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1]], np.float64)
        p = (sub_b[0] - centre) @ R.T
        ref = (sub_r[0] - centre) @ R.T
        x0, x1 = float(ref[:, 0].min()), float(ref[:, 0].max())
        z0, z1 = float(ref[:, 2].min()), float(ref[:, 2].max())
        dx, dz = x1 - x0, z1 - z0
        win = (x0 - dx * 0.06, x1 + dx * 0.06, z0 - dz * 0.06, z1 + dz * 0.06)
        W = int(round(height_px * 0.62))
        img = MS._paint(p, sub_b[1], win, (W, height_px), ss, emask)
        path = os.path.join(out_dir, '%s_%s_%03d.png' % (prefix, band, yaw))
        tmp = path + '.tmp.png'
        MS._imwrite(tmp, img)
        os.replace(tmp, path)
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------------
def report(name, v, faces, basis=None, regions=None):
    """Everything this module can honestly say about one body, JSON-safe."""
    v = np.asarray(v, np.float64)
    t0 = time.time()
    if basis is None:
        basis = spectral_basis(v, faces, name=name)
    rm = region_map(v, faces, basis['shells']['vid']) if regions is None else regions
    dec = decompose(basis, v[basis['shells']['vid']])
    energies = band_energies(basis, dec, rm['regions'])
    sh = basis['shells']
    return {
        'schema': 'geom.form.blockout/report/%s' % __version__,
        'name': name,
        'stature_m': round(basis['stature_m'], 4),
        'body_area_m2': round(basis['area_m2'], 5),
        'shells': {
            'n': sh['n_shells'],
            'body_vertices': sh['body_vertices'],
            'excluded': sh['excluded'],
            'why': 'bands and renders cover the body shell only; a Laplacian over '
            'all four shells is block-diagonal and would give each shell '
            'its own constant mode, collapsing the 72-vertex eyeballs to '
            'points in the LOW band',
        },
        'ladder': {
            'bands': list(BANDS),
            'meaning': BAND_MEANING,
            'wavelength_frac_stature': {'low_mid': WAVELENGTH_LOW_FRAC, 'mid_high': WAVELENGTH_MID_FRAC},
            'lambda_norm_cutoffs': {'low_mid': round(LAMBDA_LOW, 2), 'mid_high': round(LAMBDA_MID, 2)},
            'micro_sigma_frac_stature': basis['micro_sigma_frac'],
            'micro_sigma_mm': round(basis['micro_sigma_frac'] * basis['stature_m'] * 1000, 3),
            'k_solved': basis['k'],
            'n_modes': basis['n_modes'],
            'lambda_norm_max': round(float(basis['lambda_norm'].max()), 1),
            'attempts': basis['attempts'],
            'operators': {
                'low': 'manifold-harmonic projection (GLOBAL — a '
                'localised change appears in this band all over '
                'the body; see delta_bands)',
                'mid': 'manifold-harmonic projection (GLOBAL)',
                'high': 'implicit-smoothing low-pass of the spectral residual (LOCAL)',
                'micro': 'implicit-smoothing high-pass of the spectral residual (LOCAL)',
            },
        },
        'regions': {'source': rm['source'], 'counts': rm['counts'], 'notes': rm['notes']},
        'energies': energies,
        'timing_s': dict(basis['timing_s'], total=round(time.time() - t0, 3)),
        'units': {
            'rms_mstat': "1 millistature = 0.001 of this subject's stature = %.3f mm here" % (basis['stature_m']),
            'comparable_across_statures': ['rms_mstat', 'share', 'lambda_norm_cutoffs'],
        },
        'predicates': list(PREDICATES),
    }


def _json_safe(o):
    if isinstance(o, dict):
        return {str(k): _json_safe(x) for k, x in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(x) for x in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return _json_safe(o.tolist())
    return o


def write_json(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(_json_safe(doc), f, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return path
