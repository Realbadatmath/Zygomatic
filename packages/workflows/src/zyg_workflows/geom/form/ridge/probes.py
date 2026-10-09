# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The probes — 12 head/neck windows, 20 body regions — and their overlap census.

Moved verbatim out of the old single-file ridge.py (lines 2225-2644).
"""

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge.constants import (
    BELOW_NULL_VERDICTS,
    CANON_TARGETS,
    NO_VERDICT_VERDICTS,
    RESOLVED_VERDICTS,
)
from zyg_workflows.geom.form.ridge.null import shell_mask


# ---------------------------------------------------------------------------------
# the probes: 20 body regions + 12 head/neck windows
# ---------------------------------------------------------------------------------
def window_mask(v, faces, w, stature_m=None, normals=None):
    """regions._window_mask's spec format, evaluated on ANY body.

    regions.py's copy is bound to the frozen neutral context by design. This one takes the
    mesh, because probe pools are authored on the neutral and then MEASURED on abel and
    cornelis, and the diagnostics for an empty window have to be able to say what the cage
    actually holds at that height on THAT body.
    """
    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    nrm = CV.vertex_normals(v, faces) if normals is None else np.asarray(normals)
    fz = (v[:, 2] - v[:, 2].min()) / S
    m = np.ones(len(v), bool)
    if 'fz' in w:
        m &= (fz >= w['fz'][0]) & (fz <= w['fz'][1])
    if 'x' in w:
        m &= (v[:, 0] / S >= w['x'][0]) & (v[:, 0] / S <= w['x'][1])
    if 'y' in w:
        m &= (v[:, 1] / S >= w['y'][0]) & (v[:, 1] / S <= w['y'][1])
    if 'normal_y_min' in w:
        m &= nrm[:, 1] >= w['normal_y_min']
    if 'normal_y_max' in w:
        m &= nrm[:, 1] <= w['normal_y_max']
    if 'normal_z_min' in w:
        m &= nrm[:, 2] >= w['normal_z_min']
    return m


def _empty_window_evidence(v, faces, w, stature_m, normals):
    """Why a window is empty, per constraint — the honest form of "no result".

    An empty window is NOT a statement about relief, and reporting it as "no landmark" would
    be a lie by omission. It is either a tessellation limit or a window authored off the
    mesh, and which one it is can be decided by dropping the constraints one at a time and
    printing the cage's actual extent inside the survivors.
    """
    v = np.asarray(v, np.float64)
    S = stature_m
    fz = (v[:, 2] - v[:, 2].min()) / S
    ev = {'n_total': int(len(v))}
    keys = [k for k in ('fz', 'x', 'y', 'normal_y_min', 'normal_y_max', 'normal_z_min') if k in w]
    for k in keys:
        ev['n_passing_' + k] = int(window_mask(v, faces, {k: w[k]}, S, normals).sum())
    if 'fz' in w:
        band = (fz >= w['fz'][0]) & (fz <= w['fz'][1])
        ev['n_in_fz_band'] = int(band.sum())
        if band.any():
            ev['cage_x_frac_in_band'] = [round(float(v[band, 0].min() / S), 4), round(float(v[band, 0].max() / S), 4)]
            ev['cage_y_frac_in_band'] = [round(float(v[band, 1].min() / S), 4), round(float(v[band, 1].max() / S), 4)]
            ev['window_x_frac'] = list(w.get('x', ('-', '-')))
            ev['window_y_frac'] = list(w.get('y', ('-', '-')))
    return ev


# The 12 head/neck windows of the wave's probe_head.py, verbatim, plus the two things that
# script had no way to carry: HeadNeck p.80's SOLID (ridge) vs DOTTED (flat facet)
# classification, and therefore which primitive is the right one to test each with.
# 'kind': 'ridge' -> ridge_relief;  'facet' -> facet_flatness;  'point' -> neither, the
# reference describes a single prominence and the curve primitive has nothing to add.
HEAD_PROBES = (
    (
        'superciliary_arch',
        'facet',
        'either',
        dict(fz=(0.940, 0.962), x=(0.000, 0.050), y=(-0.130, -0.055), normal_y_max=-0.10),
        'HeadNeck p.80 DOTTED (glabella/superciliary arch) = flat facet, not a bump',
    ),
    (
        'zygomatic_arch',
        'ridge',
        'protrusion',
        dict(fz=(0.910, 0.940), x=(0.040, 0.085), y=(-0.110, -0.010)),
        'HeadNeck p.80 SOLID; the one place on the face where bone is a surface landmark',
    ),
    (
        'orbital_margin',
        'ridge',
        'either',
        dict(fz=(0.930, 0.955), x=(0.015, 0.055), y=(-0.120, -0.050)),
        'HeadNeck p.80 SOLID; p.31 says the rim reads as the TEAR TROUGH, i.e. as a furrow, so polarity is either',
    ),
    (
        'mastoid_process',
        'facet',
        'either',
        dict(fz=(0.895, 0.925), x=(0.045, 0.080), y=(-0.020, 0.060)),
        'HeadNeck p.80 DOTTED',
    ),
    (
        'external_occipital_protuberance',
        'point',
        'protrusion',
        dict(fz=(0.915, 0.950), x=(0.000, 0.030), y=(0.020, 0.110)),
        'HeadNeck p.103: Eop must sit level with the orbital floor. A single prominence.',
    ),
    (
        'gonion',
        'ridge',
        'protrusion',
        dict(fz=(0.872, 0.902), x=(0.035, 0.078), y=(-0.070, 0.030)),
        'HeadNeck p.80 SOLID lower border of mandible — a whole-bone edge',
    ),
    (
        'mental_protuberance',
        'point',
        'protrusion',
        dict(fz=(0.858, 0.880), x=(0.000, 0.030), y=(-0.120, -0.045)),
        'chin; not in the p.80 solid/dotted set',
    ),
    (
        'nasal_bone',
        'ridge',
        'protrusion',
        dict(fz=(0.930, 0.952), x=(0.000, 0.016), y=(-0.140, -0.080)),
        'HeadNeck p.80 SOLID — the dorsum is a ridge by definition',
    ),
    (
        'temporal_line',
        'ridge',
        'either',
        dict(fz=(0.950, 0.978), x=(0.040, 0.072), y=(-0.070, 0.040)),
        'HeadNeck p.80 SOLID',
    ),
    (
        'temporal_fossa',
        'ridge',
        'depression',
        dict(fz=(0.935, 0.962), x=(0.045, 0.075), y=(-0.060, 0.020)),
        'the temple hollow — a furrow, searched as one',
    ),
    (
        'suprasternal_notch',
        'ridge',
        'depression',
        dict(fz=(0.800, 0.830), x=(0.000, 0.020), y=(-0.130, -0.040)),
        'HeadNeck p.160 "the pit of the neck"',
    ),
    (
        'cervicale',
        'ridge',
        'protrusion',
        dict(fz=(0.815, 0.855), x=(0.000, 0.025), y=(0.020, 0.100)),
        'C7; HeadNeck p.168-169 makes it POSE-conditional, so a null here is not final',
    ),
)

# How the 20 body regions become pools. feature_search regions already carry a window;
# every other region carries an authored PATCH, and a whole-bone feature extends past it, so
# the pool is that patch grown by a geodesic ball. 0.030 of stature = 50.6 mm at the neutral
# — enough arc for 14 stations without leaving the aspect the patch sits on.
BODY_POOL_BALL_FRAC = 0.030


def body_pools(v, faces, stature_m=None, normals=None, doc=None):
    """The 20 REGION_SPEC regions as (name, kind, polarity, pool, provenance).

    Pools are resolved on whatever mesh is passed, from the NEUTRAL-authored anchors:
    windows are the spec's own fraction-of-stature boxes and patches are regions.json's
    frozen vertex lists. That is regions.py's rule — "groups are authored once, on the
    neutral, and frozen" — and it is what makes the same skin comparable across abel,
    cornelis and the control.
    """
    from zyg_workflows.geom.form import regions as RG  # lazy: see module docstring

    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    nrm = CV.vertex_normals(v, faces) if normals is None else np.asarray(normals)
    if doc is None:
        doc = RG.load_regions(len(v))
    out = []
    for spec in RG.REGION_SPEC:
        name = spec['name']
        tgt = CANON_TARGETS.get(name, {})
        pol = {1: 'protrusion', -1: 'depression'}.get(tgt.get('sign'), 'either')
        if spec['how'] == 'feature_search':
            w = spec['args']['window']
            # regions.py fixes polarity per window; honour it unless the books say either.
            pol = spec['args'].get('polarity', pol)
            if tgt.get('kind') in ('strip', 'sign_variable'):
                pol = 'either'
            m = window_mask(v, faces, w, S, nrm)
            n_raw = int(m.sum())
            m &= shell_mask(v, faces)
            pool = np.nonzero(m)[0]
            prov = 'regions.REGION_SPEC window %s (%d of %d window verts on the body shell)' % (w, len(pool), n_raw)
            ev = None if len(pool) else _empty_window_evidence(v, faces, w, S, nrm)
        else:
            rec = doc['regions'][name]
            g = np.array(rec.get('vertex_idx_l') or [], np.int64)
            if not len(g):
                out.append(
                    (name, 'ridge', pol, np.array([], np.int64), 'regions.json has no group for %s' % name, None)
                )
                continue
            pool = CV.geodesic_ball(v, faces, g, BODY_POOL_BALL_FRAC, S)
            prov = 'regions.json %s (%d verts, claim=%s) grown by a %.3f-stature geodesic ball' % (
                name,
                len(g),
                rec.get('claim'),
                BODY_POOL_BALL_FRAC,
            )
            ev = None
        out.append((name, 'ridge', pol, pool, prov, ev))
    return out


def head_pools(v, faces, stature_m=None, normals=None):
    """The 12 head/neck windows as (name, kind, polarity, pool, provenance, empty_evidence)."""
    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    nrm = CV.vertex_normals(v, faces) if normals is None else np.asarray(normals)
    out = []
    for name, kind, pol, w, src in HEAD_PROBES:
        m = window_mask(v, faces, w, S, nrm)
        n_raw = int(m.sum())
        m &= shell_mask(v, faces)
        pool = np.nonzero(m)[0]
        ev = None if len(pool) else _empty_window_evidence(v, faces, w, S, nrm)
        out.append(
            (
                name,
                kind,
                pol,
                pool,
                'probe_head window %s (%d of %d window verts on the body shell; the '
                'rest are eyeball/tongue components) | %s' % (w, len(pool), n_raw, src),
                ev,
            )
        )
    return out


def _resolution_contract(cuts, modes):
    """The union false-positive rate of the criterion a probe is actually scored on.

    A probe is run under BOTH primitives and counted resolved if EITHER resolves, so the
    rate that governs the claim is not one mode's rate — it is the union over the modes
    tried. Estimated as 1 - prod(1 - r) i.e. under independence, which for a union of
    positively-correlated events is an UPPER bound: the honest direction for a false-positive
    rate. Quoted beside every count so nobody has to reconstruct the multiplicity.
    """

    def _union(key):
        p = 1.0
        seen = False
        for m in modes:
            r = (cuts.get(m) or {}).get(key)
            if r is None:
                continue
            seen = True
            p *= 1.0 - float(r)
        return (1.0 - p) if seen else None

    return {
        'resolved_verdicts': sorted(RESOLVED_VERDICTS),
        'below_null_verdicts': sorted(BELOW_NULL_VERDICTS),
        'no_verdict_verdicts': sorted(NO_VERDICT_VERDICTS),
        'modes_tried': list(modes),
        'null_rate_resolved_either_mode': _union('null_rate_resolved'),
        'null_rate_point_only_or_better_either_mode': _union('null_rate_point_only_or_better'),
        'rule': (
            'read `resolves_relief` off the record. point_only and flat are INSIDE '
            'the measured null and resolve nothing; EMPTY_WINDOW was never probed at '
            'all and is not a flat reading. Do not re-list verdict names in a '
            'consumer.'
        ),
    }


def _max_disjoint(adj, nodes):
    """Largest set of probes that share no vertex with each other — exact.

    Exact rather than greedy because this number is quoted as "the independent count" and a
    greedy answer would be a lower bound presented as a fact. n is 11-20 here, so exactness
    costs nothing.
    """
    best = []

    def rec(cands, chosen):
        if len(chosen) + len(cands) <= len(best):
            return
        if not cands:
            if len(chosen) > len(best):
                best[:] = list(chosen)
            return
        pivot = max(cands, key=lambda n: (len(adj[n] & cands), n))
        rec(cands - {pivot} - adj[pivot], chosen + [pivot])  # take it
        rec(cands - {pivot}, chosen)  # leave it

    rec(set(nodes), [])
    return sorted(best)


def pool_overlaps(pools, subset=None):
    """Do these probe windows measure independent patches of skin? Measured, not assumed.

    A count of "n probes resolved" is only a count of n INDEPENDENT observations if the
    windows are disjoint, and these are not: MEASURED on abel, clavicle_shaft covers 84.5%
    of sternal_end, olecranon shares 60.6% of its vertices with epicondyle_lat, and
    malleolus_lat and malleolus_med return a bit-identical point-mode peak — one bump
    credited to two landmarks. None of that was checked or reported anywhere until now.

    Returns the pairwise overlap table plus TWO independent counts, because they answer
    different questions and neither alone is the honest one:
      n_disjoint_clusters    connected components of the shares-a-vertex graph — how many
                             separated regions of skin the set actually covers.
      max_disjoint_windows   the largest subset that is pairwise disjoint — how many of
                             these probes could be treated as independent observations.

    BOTH COUNTS ARE TAKEN OVER NON-EMPTY WINDOWS ONLY. An empty window is trivially
    disjoint from everything, so counting it would inflate the independence figure with
    windows that carry no observation at all — the opposite of what the number is for. The
    empty ones are listed separately and never folded in.

    `subset` restricts the analysis to named probes (e.g. the fat-invariant roster).
    """
    idx, empty = {}, []
    for name, _k, _p, pool, _prov, _ev in pools:
        if subset is not None and name not in subset:
            continue
        u = np.unique(np.asarray(pool, np.int64).ravel())
        if not len(u):
            empty.append(name)
            continue
        idx[name] = u
    names = sorted(idx)
    adj = {n: set() for n in names}
    pairs = []
    for a_i, a in enumerate(names):
        for b in names[a_i + 1 :]:
            A, B = idx[a], idx[b]
            n_shared = int(np.intersect1d(A, B, assume_unique=True).size)
            if not n_shared:
                continue
            adj[a].add(b)
            adj[b].add(a)
            pairs.append(
                {
                    'a': a,
                    'b': b,
                    'n_shared': n_shared,
                    'n_a': int(len(A)),
                    'n_b': int(len(B)),
                    'frac_of_smaller': round(n_shared / float(min(len(A), len(B))), 4),
                }
            )
    seen, clusters = set(), []
    for n in names:
        if n in seen:
            continue
        stack, comp = [n], []
        seen.add(n)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        clusters.append(sorted(comp))
    mis = _max_disjoint(adj, names)
    pairs.sort(key=lambda d: -d['frac_of_smaller'])
    n_all = len(names) + len(empty)
    return {
        'n_windows': n_all,
        'n_nonempty_windows': len(names),
        'windows': names,
        'n_overlapping_pairs': len(pairs),
        'pairs': pairs,
        'n_disjoint_clusters': len(clusters),
        'clusters': sorted(clusters, key=lambda c: (-len(c), c[0])),
        'max_disjoint_windows': len(mis),
        'max_disjoint_set': mis,
        'empty_windows': sorted(empty),
        'note': (
            '%d windows, %d of them holding any vertex at all%s; those cover %d '
            'separated regions of skin and at most %d of them are pairwise disjoint. '
            'A count out of %d is NOT %d independent observations.'
            % (
                n_all,
                len(names),
                (' (empty: %s)' % ', '.join(sorted(empty))) if empty else '',
                len(clusters),
                len(mis),
                n_all,
                n_all,
            )
        ),
    }


def _shared_peak_vertices(recs, modes=('ridge', 'point')):
    """Probes whose winning candidate peaks on the SAME vertex — one bump, two landmarks.

    The overlap table says two windows share skin; this says they credited the same
    measurement. Measured on abel, malleolus_lat and malleolus_med return an identical
    point-mode peak of 3.440681001927102 mm from the same vertex.
    """
    by = {}
    for name, r in recs.items():
        if name.startswith('_') or not isinstance(r, dict) or r.get('status') != 'ok':
            continue
        for m in modes:
            s = r.get(m) or {}
            if s.get('status') != 'ok':
                continue
            pv = (s.get('result') or {}).get('peak_vertex')
            if pv is None:
                continue
            by.setdefault((m, int(pv)), []).append(name)
    out = []
    for (m, pv), who in sorted(by.items()):
        if len(who) > 1:
            out.append({'mode': m, 'vertex': pv, 'probes': sorted(who)})
    return out
