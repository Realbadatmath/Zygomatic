# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""layer — a verbatim section of the pre-split relief.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

import numpy as np  # noqa: F401

from zyg_workflows.geom.relief.constants import (  # noqa: F401
    ANATOMY_KEY,
    ASPECT_MIN_DOT,
    CONDITIONALS,
    FACET_CAP_FRAC,
    MIRROR_TOL_FRAC,
    NEWELL_MIRROR_MAX,
    SCHEMA,
    cond_none,
)
from zyg_workflows.geom.relief.primitives import (  # noqa: F401
    _check_falloff_inside_collar,
    bone_frame,
    bone_weights,
    bones_for,
    field_mirror_residual_m,
    symmetrise_field,
    verify_bone_frame,
)
from zyg_workflows.geom.relief.anchors import (  # noqa: F401
    _Ctx,
    _build_features,
    _falloff,
    _mirror_seeds,
    _snap,
    _unit,
)


# ---------------------------------------------------------------------------------
# the layer
# ---------------------------------------------------------------------------------


def _facet_project(ctx, P, w, seed_pos, seed_aspect, seed_arc):
    """Pull a strip onto a RULED LEAST-SQUARES PLANE in its own (arc, aspect) frame.

    Each vertex is assigned to its nearest station; h is its offset from that station
    along the station's aspect, and `arc` is the station's position along the strip. Over
    the whole weighted strip h is fitted as h = alpha + beta*arc, i.e. a plane that is
    allowed to taper along the limb (a tibial surface does), and each vertex is moved by
    w * (fit - h) along the aspect, capped at FACET_CAP_FRAC of stature.

    Symmetric by construction: the right-hand stations are the mirror partners of the
    left-hand ones with x-negated aspects and IDENTICAL arc coordinates, so both halves
    enter the same regression with the same weights and receive the same correction.
    """
    idx = np.nonzero(w > 0)[0]
    D = np.zeros_like(P)
    if len(idx) < 4 or len(seed_pos) < 2:
        return D
    d2 = ((P[idx][:, None, :] - seed_pos[None, :, :]) ** 2).sum(axis=2)
    j = np.argmin(d2, axis=1)
    a = seed_aspect[j]
    q = seed_pos[j]
    arc = seed_arc[j]
    h = ((P[idx] - q) * a).sum(axis=1)
    ww = w[idx]
    A = np.stack([np.ones_like(arc), arc], axis=1)
    WA = A * ww[:, None]
    try:
        coef = np.linalg.lstsq(WA.T.dot(A), WA.T.dot(h), rcond=None)[0]
    except np.linalg.LinAlgError:  # pragma: no cover
        return D
    cap = FACET_CAP_FRAC * ctx.S
    corr = np.clip(A.dot(coef) - h, -cap, cap)
    D[idx] = (ww * corr)[:, None] * a
    return D


def relief_field(v, faces, scale, bones, weights, bone_names, macros, stature_m=None, include=None):
    """Build the displacement field and the evidence for it. Returns (D, facet_D, report).

    D is the ADDITIVE field (metres, one row per cage vertex), already symmetrised.
    facet_D is the flattening field, computed on v+D and symmetrised separately.

    `include` restricts the layer to a set of feature names. It exists for DECOMPOSITION,
    not for configuration: a landmark's measured relief is partly its own displacement and
    partly the fossae its neighbours cut inside its collar, and the only honest way to say
    how much is which is to build the crest alone and measure that too.
    """
    ctx = _Ctx(v, faces, bones, weights, bone_names, macros, stature_m)
    S = ctx.S
    feats = _build_features(ctx)
    if include is not None:
        keep = set(include)
        feats = [f for f in feats if f['name'] in keep]
    used_bones = [
        'clavicle.L',
        'clavicle.R',
        'lowerarm01.L',
        'lowerarm02.L',
        'metacarpal1.L',
        'metacarpal4.L',
        'upperarm02.L',
        'foot.L',
        'lowerleg01.L',
        'pelvis.L',
        'spine01',
        'head',
    ]
    frame = verify_bone_frame(ctx.v, ctx.bones, (ctx.W, ctx.I), ctx.bone_names, S, used_bones)
    bad = {k: r for k, r in frame.items() if not r.get('ok')}

    D = np.zeros((len(ctx.v), 3), np.float64)
    facet_w = np.zeros(len(ctx.v), np.float64)
    facet_jobs = []
    records = []
    for f in feats:
        cond = CONDITIONALS.get(f['name'], cond_none)
        cscale, cprov = cond(ctx.macros)
        amp = f['amp_frac'] * cscale * float(scale)
        seedsL, perp, depth, refused = _snap(ctx, f['points'], f['aspect'], min_dot=f.get('min_dot', ASPECT_MIN_DOT))
        if f.get('midline'):
            seeds, lost = seedsL, []
        else:
            seedsR, lost = _mirror_seeds(ctx, seedsL)
            seeds = np.unique(np.concatenate([seedsL, seedsR])) if len(seedsL) else seedsL
        rec = {
            'name': f['name'],
            'claim': f['claim'],
            'op': f['op'],
            'anchor': f['anchor'],
            'amp_frac_stature': f['amp_frac'],
            'conditional_scale': cscale,
            'conditional_provenance': cprov,
            'delivered_amp_frac_stature': (
                f['amp_frac'] * cscale * float(scale) if f['op'] not in ('facet', 'control') else None
            ),
            'delivered_amp_mm': (1e3 * amp * S if f['op'] not in ('facet', 'control') else None),
            'clears_null_by_amplitude': (
                abs(f['amp_frac'] * cscale * float(scale)) >= 2.45e-3 if f['op'] not in ('facet', 'control') else None
            ),
            'n_anchor_points': int(len(f['points'])),
            'n_seeds_left': int(len(seedsL)),
            'n_seeds_total': int(len(seeds)),
            'seed_vertices': [int(i) for i in seeds[:40]],
            'ray_miss_mm': {
                'max': float(1e3 * perp.max()) if len(perp) else None,
                'median': (float(1e3 * np.median(perp)) if len(perp) else None),
            },
            'tissue_depth_mm': {
                'max': float(1e3 * depth.max()) if len(depth) else None,
                'median': (float(1e3 * np.median(depth)) if len(depth) else None),
            },
            'refused_anchor_points': refused,
            'seeds_without_mirror_partner': lost,
            'probes_targeted': list(f.get('probes', ())),
            'seed_frac_stature': (
                [round(float(x), 4) for x in np.sort((ctx.v[seeds, 2] - ctx.z0) / S)[[0, -1]]] if len(seeds) else None
            ),
        }
        rec.update(f.get('extra') or {})
        if not len(seeds):
            rec['status'] = 'no_seed'
            records.append(rec)
            continue
        w = _falloff(ctx, seeds)
        rec['n_vertices_touched'] = int((w > 0).sum())
        if f['op'] == 'control':
            rec['status'] = 'negative_control'
            rec['control_vertices'] = [int(i) for i in np.nonzero(w > 0)[0]]
            records.append(rec)
            continue
        if f['op'] == 'facet':
            asp = (
                np.asarray(f['aspect'], np.float64)
                if np.ndim(f['aspect']) == 2
                else np.repeat(_unit(f['aspect'])[None], len(f['points']), 0)
            )
            # one station per surviving LEFT seed, in seed order, plus its mirror twin
            kL = [int(np.argmin(np.linalg.norm(f['points'] - ctx.v[i], axis=1))) for i in seedsL]
            sp = [ctx.v[i] for i in seedsL]
            sa = [asp[k] for k in kL]
            sc = [float(k) for k in kL]
            for i, k in zip(seedsL, kL):
                m = ctx.mate[i]
                if m >= 0:
                    sp.append(ctx.v[m])
                    aa = asp[k].copy()
                    aa[0] *= -1.0
                    sa.append(aa)
                    sc.append(float(k))
            facet_jobs.append((rec['name'], w, np.array(sp), np.array(sa), np.array(sc)))
            facet_w = np.maximum(facet_w, w)
            rec['status'] = 'ok'
            records.append(rec)
            continue
        D += (amp * S) * w[:, None] * ctx.n
        rec['status'] = 'ok'
        records.append(rec)

    raw_resid = field_mirror_residual_m(D, ctx.mate)
    Dsym, have = symmetrise_field(D, ctx.mate)
    sym_resid = field_mirror_residual_m(Dsym, ctx.mate)

    # facet flattening runs on the ALREADY-DISPLACED cage: the anteromedial strip has to
    # be planar in the body that ships, not in an intermediate one.
    facet_D = np.zeros_like(D)
    if facet_jobs:
        P1 = ctx.v + Dsym
        for _nm, w, sp, sa, sc in facet_jobs:
            fw = 0.5 * (w + np.where(ctx.mate >= 0, w[ctx.mate], w))
            facet_D += _facet_project(ctx, P1, fw, sp, sa, sc)
        facet_D, _ = symmetrise_field(facet_D, ctx.mate)

    nrm_res = None
    hv = np.nonzero(ctx.mate >= 0)[0]
    if len(hv):
        M = ctx.n[ctx.mate[hv]].copy()
        M[:, 0] *= -1.0
        nrm_res = float(np.abs(ctx.n[hv] - M).max())

    report = {
        'schema': SCHEMA,
        'scale': float(scale),
        'stature_m': S,
        'macros': dict(ctx.macros),
        'falloff': _check_falloff_inside_collar(),
        'bone_frame_verified': frame,
        'bone_frame_failures': bad,
        'mirror': {
            'paired_vertices': int(len(have)),
            'unpaired_vertices': int(len(ctx.v) - len(have)),
            'pair_tolerance_mm': 1e3 * MIRROR_TOL_FRAC * S,
            'newell_normal_mirror_residual': nrm_res,
            'newell_guard': NEWELL_MIRROR_MAX,
            'field_residual_before_symmetrise_mm': None if raw_resid is None else 1e3 * raw_resid,
            'field_residual_after_symmetrise_mm': None if sym_resid is None else 1e3 * sym_resid,
        },
        'features': records,
        # The arithmetic check that comes BEFORE any probe: an amplitude at or below the
        # cage's own relief p99 cannot resolve at any placement, however well anchored.
        # Listed here so a reader sees it without having to run the probe suite.
        'amplitude_audit': {
            'null_min_frac_stature': 2.45e-3,
            'below_null_by_amplitude': [
                {
                    'name': r['name'],
                    'delivered_frac_stature': r['delivered_amp_frac_stature'],
                    'delivered_mm': r['delivered_amp_mm'],
                    'shortfall_x': (
                        abs(r['delivered_amp_frac_stature']) / 2.45e-3 if r['delivered_amp_frac_stature'] else 0.0
                    ),
                }
                for r in records
                if r['delivered_amp_frac_stature'] is not None and abs(r['delivered_amp_frac_stature']) < 2.45e-3
            ],
        },
    }
    if nrm_res is not None and nrm_res > NEWELL_MIRROR_MAX:
        report['mirror']['WARNING'] = (
            'the Newell normal field is not mirror-symmetric on this cage (%.4f > %.4f). '
            'The displacement field is still symmetrised, but the cage itself is not a '
            'mirror image of itself and that is a finding about the cage.' % (nrm_res, NEWELL_MIRROR_MAX)
        )
    return Dsym, facet_D, report


def apply_relief(
    v,
    faces,
    anatomy,
    phenotype=None,
    bones=None,
    weights=None,
    bone_names=None,
    stature_m=None,
    model=None,
    model_out=None,
    include=None,
):
    """THE ENTRY POINT. Same shape as mesh_skeletons._apply_anatomy.

        v = relief.apply_relief(v, faces, anatomy, phenotype=phen,
                                bones=bones, weights=weights, bone_names=names)

    `anatomy` is a character's anatomy dict. The key read is ANATOMY_KEY ('bony_relief'),
    a float scale. Absent or <= 0 -> the returned array is the INPUT ARRAY UNCHANGED and
    the cage hash is untouched, so wiring this in is safe before any body is re-issued.

    The rig can be supplied three ways, in order of preference:
      * bones=/weights=/bone_names= directly (a caller that already has the anny output
        should build them with bone_frame(model, out) and bone_weights(model) — no second
        forward pass);
      * model=/model_out= (this builds them);
      * nothing, in which case `phenotype` is required and one extra forward pass is run.

    The report is left on apply_relief.last_report, exactly as _apply_anatomy leaves
    last_symmetry, and it carries the evidence for every feature: which bone it was
    anchored to, whether that bone's frame verified, what the conditional did to the
    amplitude, how far each anchor had to snap, and the mirror residual in mm.
    """
    s = float((anatomy or {}).get(ANATOMY_KEY) or 0.0)
    if s <= 0.0:
        apply_relief.last_report = {
            'schema': SCHEMA,
            'status': 'absent',
            'reason': 'anatomy carries no %r' % ANATOMY_KEY,
        }
        return v
    if bones is None:
        if model is not None and model_out is not None:
            bones = bone_frame(model, model_out)
            weights = bone_weights(model)
            from zyg_workflows.geom import mesh_skeletons as MS

            bone_names = [str(n) for n in MS._bone_names(model)]
        else:
            if phenotype is None:
                raise ValueError(
                    'apply_relief needs the rig: pass bones=/weights=/bone_names=, or '
                    'model=/model_out=, or a phenotype it can rebuild from. It will not '
                    'guess a skeleton.'
                )
            _, _, bones, weights = bones_for(phenotype)
            from zyg_workflows.geom import mesh_skeletons as MS

            bone_names = [str(n) for n in MS._bone_names(MS._model())]
    if bone_names is None:
        from zyg_workflows.geom import mesh_skeletons as MS

        bone_names = [str(n) for n in MS._bone_names(MS._model())]

    P64 = np.asarray(v, np.float64)
    D, Dfacet, report = relief_field(
        P64, faces, s, bones, weights, bone_names, phenotype or {}, stature_m, include=include
    )
    out = np.asarray(v).copy()
    total = D + Dfacet
    out[:] = (P64 + total).astype(np.asarray(v).dtype)

    moved = np.linalg.norm(out.astype(np.float64) - P64, axis=1)
    report['status'] = 'applied'
    report['include'] = None if include is None else sorted(include)
    report['displaced_vertices'] = int((moved > 1e-9).sum())
    report['max_displacement_mm'] = float(1e3 * moved.max())
    report['rms_displacement_mm'] = float(1e3 * np.sqrt((moved**2).mean()))
    # the negative control, measured on the DELIVERED cage
    for r in report['features']:
        if r.get('status') == 'negative_control':
            cv = np.array(r.get('control_vertices') or [], np.int64)
            r['max_displacement_mm'] = float(1e3 * moved[cv].max()) if len(cv) else 0.0
            r['holds'] = bool(not len(cv) or moved[cv].max() <= 1e-9)
    apply_relief.last_report = report
    return out


apply_relief.last_report = None


def relief_regions(v, faces, anatomy, **kw):
    """The vertex groups this layer sculpts, as {name: sorted vertex indices}.

    For a caller that wants to PROBE what was built rather than trust it: these are the
    groups the seeds and their falloff actually touched, so region_relief / facet_flatness
    can be pointed straight at them.
    """
    s = float((anatomy or {}).get(ANATOMY_KEY) or 0.0)
    if s <= 0.0:
        return {}
    apply_relief(v, faces, anatomy, **kw)
    rep = apply_relief.last_report or {}
    return {r['name']: list(r.get('seed_vertices') or []) for r in rep.get('features', [])}
