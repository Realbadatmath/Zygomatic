# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""integrity.shells_containment — the stages `_check_shell_components` is assembled from.

`shells._check_shell_components` was 402 lines holding five distinct jobs: the component
inventory, the per-shell measurement pass, the state ladder that reads those measurements,
the payload that reports them, and the whole-check verdict. Each is a function here and
the orchestrator left in `shells.py` is the sequence of calls. No measurement, no payload
key, no state name and no ordering changed; the only statements that moved earlier are
pure derivations (`shells`, `analysed`) with no observable effect.

Three carriers hold what the stages hand each other — `ShellInventory` (what the shells
ARE), `BodyProbes` (the body geometry every shell is measured against) and `ShellMeasure`
(one shell's numbers). The measurement loop read sixteen enclosing locals, and a
sixteen-argument positional call is a silent bug waiting for the next edit.

The import direction is one-way and load-bearing: this module imports the geometry
primitives from `shells` at module level, and `shells` imports this module lazily inside
`_check_shell_components`. Every name `integrity/__init__.py` re-exports therefore still
lives in `shells`, and neither import order can deadlock.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.spatial import cKDTree
from zyg_workflows.geom.anthro.integrity.constants import (
    BODY_DOMINANCE_MIN_RATIO,
    ENVELOPE_ESCAPE_MAX_FRACTION,
    HULL_MARGIN_EPS_M,
    MAX_CONTAINMENT_PROBE_VERTICES,
    MAX_SHELLS_ANALYSED,
    PARITY_DIRECTIONS,
    SKY_DIRECTIONS,
    SKY_PROBE_VERTICES,
    WINDING_GUARD,
    WINDING_INSIDE,
)
from zyg_workflows.geom.anthro.integrity.mesh_checks import _stride, _tri_spheres
from zyg_workflows.geom.anthro.integrity.self_intersection import _face_components
from zyg_workflows.geom.anthro.integrity.shells import (
    _DEFECT_STATES,
    _STATE_MEANING,
    _convex_envelope,
    _envelope_margin,
    _fibonacci_directions,
    _name_shell,
    _ray_crossings,
    _winding_numbers,
)


@dataclass
class ShellInventory:
    """What the cage IS: every connected component, named, ordered biggest first.

    `inv` is the `inventory` list the payload reports; `shells` is the non-body,
    non-loose subset the measurement pass walks. `vsort`/`vstart`/`vend` are the one
    stable argsort that gives any component's vertex slab in O(1) — the obvious
    `comp_labels == k` inside the loop is an hour at 13,718 components.
    """

    sizes: Any
    fsizes: Any
    vsort: Any
    vstart: Any
    vend: Any
    diag: Any
    body: int
    loose: list
    second: float
    ratio: float
    ambiguous: bool
    stature_m: float
    stature_scale: float
    euler_by_component: dict
    inv: list
    shells: list


@dataclass
class BodyProbes:
    """The body geometry every shell is measured against, built once per check.

    `env` is the body's verified convex envelope, or None when no shell is going to be
    analysed (building a hull nobody reads is the one expensive thing here).
    """

    v: Any
    body: int
    body_tris: Any
    dirs: Any
    pdirs: Any
    spheres: Any
    body_pts: Any
    body_tree: Any
    env: Any


@dataclass
class ShellMeasure:
    """One shell's numbers: containment, ray parity, envelope membership and escape.

    Everything the state ladder and the payload read, and nothing else. `env_reason`
    carries the envelope's own explanation of why it is unavailable so that
    `select_shell_state` needs no access to the hull itself.
    """

    component: int
    pts: Any
    pts_all: Any
    w: Any
    inside: Any
    ambig: Any
    wp: Any
    agree: int
    n_probes: int
    crossing: Any
    marg: Any
    out_env: Any
    sky: Any
    sky_env: Any
    far_m: Any
    near_m: float
    n_in: int
    n_out: int
    consistent: Any
    env_reason: Any


def build_shell_inventory(v, faces, comp_labels, ncomp, euler_per_component) -> ShellInventory:
    """Inventory every connected component: extent, position, role and name.

    In: the mesh (`v`, `faces`), the per-vertex component labels, the component count and
    the per-component Euler records. Out: a `ShellInventory` — the reported inventory, the
    component chosen as the body, the loose-vertex components, the body-dominance ratio
    and the vertex-slab index the measurement pass reads.
    """
    sizes = np.bincount(comp_labels, minlength=ncomp)
    fcomp = _face_components(faces, comp_labels)
    fsizes = np.bincount(fcomp, minlength=ncomp)

    # One sort gives every component's vertex list. The obvious `comp_labels == k` inside
    # the loop is O(components x vertices), which is invisible at 4 components and an hour
    # at 13,718 of them — and a cage that has shattered into a component per vertex is
    # exactly when an operator needs this report to come back.
    vsort = np.argsort(comp_labels, kind='stable')
    slab = comp_labels[vsort]
    ks = np.arange(ncomp)
    vstart = np.searchsorted(slab, ks, 'left')
    vend = np.searchsorted(slab, ks, 'right')

    lo = np.full((ncomp, 3), np.inf)
    hi = np.full((ncomp, 3), -np.inf)
    np.minimum.at(lo, comp_labels, v)
    np.maximum.at(hi, comp_labels, v)
    diag = np.where(sizes > 0, np.linalg.norm(hi - lo, axis=1), 0.0)
    # biggest first, ties broken by vertex count so the order is total and deterministic
    order = np.lexsort((-sizes, -diag))
    body = int(order[0])
    # An UNREFERENCED vertex is its own connected component of one point and no faces.
    # It is a real defect and degenerate_geometry already gates it; what matters here is
    # that it must not be dressed up as a "shell" and containment-tested, because a point
    # is not a surface and every number this check produces for it would be noise.
    loose = [int(k) for k in order.tolist() if k != body and fsizes[k] == 0]
    rival = next((int(k) for k in order.tolist() if k != body and fsizes[k] > 0), None)
    second = float(diag[rival]) if rival is not None else 0.0
    ratio = (diag[body] / second) if second > 0 else float('inf')
    ambiguous = ratio < BODY_DOMINANCE_MIN_RATIO

    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    Hs = H if H > 0 else 1.0
    eul = {e['component']: e for e in (euler_per_component or [])}

    inv = []
    for k in order.tolist():
        vv = v[vsort[vstart[k] : vend[k]]]
        e = eul.get(k, {})
        inv.append(
            {
                'component': int(k),
                'role': ('body' if k == body else ('loose_vertices' if fsizes[k] == 0 else 'shell')),
                'vertices': int(sizes[k]),
                'faces': int(fsizes[k]),
                'euler_chi': e.get('euler_chi'),
                'closed': e.get('closed'),
                'genus': e.get('genus'),
                'z_min_m': round(float(vv[:, 2].min()), 6),
                'z_max_m': round(float(vv[:, 2].max()), 6),
                'z_frac_min': round(float((vv[:, 2].min() - zmin) / Hs), 4),
                'z_frac_max': round(float((vv[:, 2].max() - zmin) / Hs), 4),
                'centroid_m': [round(float(x), 6) for x in vv.mean(axis=0)],
                'bbox_min_m': [round(float(x), 6) for x in vv.min(axis=0)],
                'bbox_max_m': [round(float(x), 6) for x in vv.max(axis=0)],
            }
        )
    for e in inv:
        e['name'], e['name_basis'], e['name_confidence'] = _name_shell(e, Hs, inv)

    return ShellInventory(
        sizes=sizes,
        fsizes=fsizes,
        vsort=vsort,
        vstart=vstart,
        vend=vend,
        diag=diag,
        body=body,
        loose=loose,
        second=second,
        ratio=ratio,
        ambiguous=bool(ambiguous),
        stature_m=H,
        stature_scale=Hs,
        euler_by_component=eul,
        inv=inv,
        shells=[e for e in inv if e['role'] == 'shell'],
    )


def body_probe_set(v, tris, comp_labels, sh, want_envelope) -> BodyProbes:
    """Build the body-side geometry: its triangles, the probe directions and the envelope.

    In: the mesh, the component labels, the inventory and whether any shell is going to be
    analysed. Out: a `BodyProbes`. `want_envelope` is False when `analysed` is empty, which
    is the only thing that keeps a convex hull from being built for nobody.
    """
    body = sh.body
    body_tris = tris[comp_labels[tris[:, 0]] == body]
    dirs = _fibonacci_directions(SKY_DIRECTIONS)
    pdirs = _fibonacci_directions(PARITY_DIRECTIONS)
    spheres = _tri_spheres(v, body_tris)
    body_pts = v[sh.vsort[sh.vstart[body] : sh.vend[body]]]
    body_tree = cKDTree(body_pts)
    return BodyProbes(
        v=v,
        body=body,
        body_tris=body_tris,
        dirs=dirs,
        pdirs=pdirs,
        spheres=spheres,
        body_pts=body_pts,
        body_tree=body_tree,
        env=_convex_envelope(body_pts) if want_envelope else None,
    )


def shell_measurements(probes, sh, entry, delivered_pairs_by_component) -> ShellMeasure:
    """Measure one shell against the body solid, its envelope and the open sky.

    In: the body geometry, the inventory (for the vertex slab), the shell's inventory entry
    and the delivered face-pair counts (None when the self-intersection pass was switched
    off). Out: a `ShellMeasure`; nothing is decided here and nothing is mutated.
    """
    v = probes.v
    body_tris = probes.body_tris
    dirs = probes.dirs
    pdirs = probes.pdirs
    spheres = probes.spheres
    body_tree = probes.body_tree
    env = probes.env
    body = probes.body
    vsort, vstart, vend = sh.vsort, sh.vstart, sh.vend

    k = entry['component']
    pts_all = v[vsort[vstart[k] : vend[k]]]
    sel = _stride(len(pts_all), MAX_CONTAINMENT_PROBE_VERTICES)
    pts = pts_all[sel]
    w = _winding_numbers(v, body_tris, pts)
    inside = w > WINDING_INSIDE
    ambig = (np.abs(w) > WINDING_GUARD) & (np.abs(w - 1.0) > WINDING_GUARD)

    # independent cross-check: ray parity from the centroid and a few sampled vertices
    probe_pts = np.vstack([pts_all.mean(axis=0)[None, :], pts_all[_stride(len(pts_all), SKY_PROBE_VERTICES)]])
    wp = _winding_numbers(v, body_tris, probe_pts)
    par = np.zeros(len(probe_pts), bool)
    for i, p in enumerate(probe_pts):
        cnt = _ray_crossings(v, body_tris, p, pdirs, spheres)
        # majority over an ODD number of directions: a single ray can graze an edge or
        # hit a vertex and return the wrong parity, and one bad ray must not be able to
        # overturn a cross-check. A tie is impossible by construction.
        par[i] = bool((cnt % 2 == 1).sum() * 2 > len(pdirs))
    agree = int((par == (wp > WINDING_INSIDE)).sum())

    pairkey = '%d|%d' % (min(k, body), max(k, body))
    crossing = None
    if delivered_pairs_by_component is not None:
        crossing = int(delivered_pairs_by_component.get(pairkey, 0))

    # THE ENVELOPE TEST, on every vertex of the shell (exact, and cheap enough that
    # there is no reason to subsample it the way the winding number has to be).
    marg = out_env = None
    if env is not None and env['available']:
        marg = _envelope_margin(pts_all, env['A'], env['b'])
        out_env = int((marg > HULL_MARGIN_EPS_M).sum())

    out_pts = pts[~inside]
    sky = None
    if len(out_pts):
        sub = out_pts[_stride(len(out_pts), SKY_PROBE_VERTICES)]
        frac = []
        for p in sub:
            cnt = _ray_crossings(v, body_tris, p, dirs, spheres)
            frac.append(float((cnt == 0).mean()))
        sky = {
            'mean': round(float(np.mean(frac)), 4),
            'min': round(float(np.min(frac)), 4),
            'max': round(float(np.max(frac)), 4),
            'sample_points': int(len(sub)),
            'directions': int(len(dirs)),
        }
        dd, _ = body_tree.query(out_pts)
        far_m = round(float(dd.max()), 6)
    else:
        far_m = None
    near_m = round(float(body_tree.query(pts_all)[0].min()), 6)

    # The escape fraction measured WHERE THE THEOREM APPLIES: at the vertices that are
    # furthest outside the envelope. Those points must escape in more than half of all
    # directions; measuring the strided outside-of-SOLID sample instead would test the
    # bound at points it says nothing about.
    sky_env = None
    if marg is not None and out_env:
        far_idx = np.argsort(-marg)[:SKY_PROBE_VERTICES]
        fe = [float((_ray_crossings(v, body_tris, p, dirs, spheres) == 0).mean()) for p in pts_all[far_idx]]
        sky_env = {
            'mean': round(float(np.mean(fe)), 4),
            'min': round(float(np.min(fe)), 4),
            'max': round(float(np.max(fe)), 4),
            'sample_points': int(len(fe)),
            'directions': int(len(dirs)),
            'measured_at': 'the %d vertices furthest OUTSIDE the convex envelope' % len(fe),
        }

    n_in, n_out = int(inside.sum()), int((~inside).sum())
    # Does the sampled escape fraction support what the exact envelope test says?
    # Outside the envelope it is the proof direction (every such point MUST exceed the
    # bound); inside it is the policy direction (a shell that sees sky in more than
    # half of all directions is not in a pocket). Only ever recorded, and only ever
    # allowed to make a benign call worse — see the state selection below.
    consistent = None
    if sky is not None and out_env is not None:
        if out_env == 0:
            consistent = bool(sky['max'] <= ENVELOPE_ESCAPE_MAX_FRACTION)
        elif sky_env is not None:
            consistent = bool(sky_env['min'] > ENVELOPE_ESCAPE_MAX_FRACTION)

    return ShellMeasure(
        component=k,
        pts=pts,
        pts_all=pts_all,
        w=w,
        inside=inside,
        ambig=ambig,
        wp=wp,
        agree=agree,
        n_probes=len(probe_pts),
        crossing=crossing,
        marg=marg,
        out_env=out_env,
        sky=sky,
        sky_env=sky_env,
        far_m=far_m,
        near_m=near_m,
        n_in=n_in,
        n_out=n_out,
        consistent=consistent,
        env_reason=(env or {}).get('reason'),
    )


def select_shell_state(m) -> tuple:
    """Decide where a measured shell sits, and say why when it cannot be decided.

    In: one `ShellMeasure`. Out: `(state, unresolved_because)` — a key of `_STATE_MEANING`
    and, only for the unresolved states, the sentence that explains which of the two
    independent position measurements was missing or disagreed. The escape fraction is
    never allowed to promote a verdict back to benign: the envelope test is exact and the
    escape fraction is a ray sample.
    """
    ambig = m.ambig
    crossing = m.crossing
    n_in, n_out = m.n_in, m.n_out
    out_env = m.out_env
    sky = m.sky
    consistent = m.consistent

    unresolved_because = None
    if ambig.any():
        state = 'indeterminate'
    elif crossing is None:
        # self_intersection was switched off, so whether this shell's faces cross the
        # body was never measured. Every remaining state depends on that, and calling
        # a shell 'enclosed' on evidence nobody gathered is the exact failure this file
        # exists to prevent — so the state says what is missing instead.
        state = 'crossing_not_tested'
    elif n_out == 0:
        state = 'enclosed_but_crossing' if crossing else 'enclosed'
    elif n_in == 0:
        if crossing:
            state = 'protrudes_through_body_surface'
        elif out_env is None:
            state = 'outside_body_position_unresolved'
            unresolved_because = m.env_reason or (
                'the convex envelope was not available, so whether this shell is '
                "inside the body's outline could not be decided"
            )
        elif out_env > 0:
            # It has left the body's envelope. A disagreeing escape fraction is
            # recorded but NEVER promotes this back to benign: the envelope test is
            # exact and the escape fraction is a 32-ray sample.
            state = 'detached_in_open_air'
        elif sky is None:
            state = 'outside_body_position_unresolved'
            unresolved_because = 'no outside-of-solid probe point was available for the escape cross-check'
        elif consistent is False:
            state = 'outside_body_position_unresolved'
            unresolved_because = (
                "every vertex is inside the body's convex envelope, yet a probe point "
                'reaches open sky in %.3f of directions, above the %.2f this file '
                'requires before calling a shell "in a pocket of the body". The '
                'envelope contains it and nothing encloses it, so neither verdict is '
                'supported' % (sky['max'], ENVELOPE_ESCAPE_MAX_FRACTION)
            )
        elif sky['max'] == 0.0:
            state = 'in_sealed_body_cavity'
        else:
            state = 'in_open_body_cavity'
    else:
        state = 'protrudes_through_body_surface' if crossing else 'straddles_without_crossing'
    return state, unresolved_because


def containment_payload(m, state, unresolved_because) -> dict:
    """The `containment` dict reported for one shell.

    In: the shell's `ShellMeasure` and the state `select_shell_state` chose for it. Out:
    the payload, including the `envelope_escape_disagreement` line that is said out loud
    whenever a prediction that cannot fail on correct inputs just failed.
    """
    w = m.w
    sky = m.sky
    marg = m.marg
    out_env = m.out_env
    crossing = m.crossing
    consistent = m.consistent

    out = {
        'vertices_probed': int(len(m.pts)),
        'subsampled': bool(len(m.pts) < len(m.pts_all)),
        'vertices_inside_body': m.n_in,
        'vertices_outside_body': m.n_out,
        'winding_min': round(float(w.min()), 6),
        'winding_max': round(float(w.max()), 6),
        'winding_indeterminate_vertices': int(m.ambig.sum()),
        'centroid_winding': round(float(m.wp[0]), 6),
        'ray_parity_probes_agreeing': '%d/%d' % (m.agree, m.n_probes),
        'delivered_face_pairs_with_body': crossing,
        'face_pairs_with_body_note': 'contacts with the body in the triangulation that SHIPS, not the '
        'diagonal-agreeing subset — the same population t1_self_intersection '
        'gates on',
        'surface_crosses_body': None if crossing is None else bool(crossing > 0),
        'envelope_vertices_tested': None if marg is None else int(len(marg)),
        'envelope_vertices_outside': out_env,
        'envelope_margin_max_mm': (None if marg is None else round(float(marg.max()) * 1000.0, 4)),
        'envelope_margin_min_mm': (None if marg is None else round(float(marg.min()) * 1000.0, 4)),
        'envelope_margin_note': "signed distance to the body's convex envelope in mm: NEGATIVE is inside "
        "it (a pocket of the body), POSITIVE is outside it (gone from the body's "
        'outline). None means the envelope was unavailable, which is not zero',
        'open_sky_from_outside_vertices': sky,
        'open_sky_from_outside_envelope_vertices': m.sky_env,
        'escape_consistent_with_envelope': consistent,
        'escape_bound': ENVELOPE_ESCAPE_MAX_FRACTION,
        'escape_bound_note': 'outside the envelope the bound is DERIVED (a point outside a convex set '
        'must escape in more than half of all directions, so a False here means '
        'the ray sample and the hull disagree — recorded, never allowed to clear '
        'the defect); inside the envelope it is HOUSE POLICY (a shell that reaches '
        'open sky in more than half of all directions is not in a pocket, so a '
        'False downgrades a benign call to unresolved). None means one of the two '
        'inputs was not available',
        'max_outside_vertex_to_body_vertex_m': m.far_m,
        'max_outside_vertex_note': 'distance to the nearest BODY VERTEX, which is an upper bound on the '
        'distance to the body SURFACE — it says nothing is far away, it does not '
        'measure protrusion depth',
        'min_shell_vertex_to_body_vertex_m': m.near_m,
        'state': state,
        'state_meaning': _STATE_MEANING[state],
        'defect': bool(state in _DEFECT_STATES),
    }
    if unresolved_because:
        out['unresolved_because'] = unresolved_because
    if out_env and consistent is False:
        # The defect call stands (the envelope test is exact) but a prediction that
        # cannot fail on correct inputs just failed, so it is said out loud.
        out['envelope_escape_disagreement'] = (
            '%d vertices lie outside the convex envelope, where escape MUST exceed '
            '%.2f, yet the furthest-out probes escape as little as %.4f. The defect '
            'call stands on the exact envelope test; this says the %d-ray sample and '
            'the hull disagree and one of them is unreliable on this geometry.'
            % (out_env, ENVELOPE_ESCAPE_MAX_FRACTION, (m.sky_env or {}).get('min', float('nan')), SKY_DIRECTIONS)
        )
    return out


def build_shell_report(sh, ncomp, containment, probe_agree, probe_total, env) -> dict:
    """Roll the per-shell states up into the check's `detail` payload and its verdict.

    In: the inventory (every shell already carries its `containment` dict), the component
    count, the caller's `containment` flag, the ray-parity tallies and the convex envelope.
    Out: `{'pass': bool, 'detail': dict}`; the caller adds `ms`. A pass means the question
    was asked and answered for every shell — see `asserted_note` in the payload.
    """
    shells = sh.shells
    body = sh.body
    sizes = sh.sizes
    diag = sh.diag
    second = sh.second
    ratio = sh.ratio
    ambiguous = sh.ambiguous
    H = sh.stature_m

    st = {e['component']: e['containment']['state'] for e in shells}
    defects = sorted(k for k, s in st.items() if s in _DEFECT_STATES)
    protruding = sorted(k for k, s in st.items() if s == 'protrudes_through_body_surface')
    untested = sorted(k for k, s in st.items() if s == 'not_tested')
    unasserted = sorted(k for k, s in st.items() if s == 'crossing_not_tested')
    unresolved = sorted(k for k, s in st.items() if s == 'outside_body_position_unresolved')
    body_rec = sh.euler_by_component.get(body, {})

    detail = {
        'components': int(ncomp),
        'body_component': body,
        'body_component_vertices': int(sizes[body]),
        'body_component_bbox_diagonal_m': round(float(diag[body]), 6),
        'body_component_selected_by': 'largest bounding-box diagonal (%.4f m, %d v; next surface component %.4f m, '
        'ratio %s)' % (diag[body], sizes[body], second, ('inf' if ratio == float('inf') else round(ratio, 2))),
        'body_component_ambiguous': bool(ambiguous),
        'body_euler_chi': body_rec.get('euler_chi'),
        'body_closed': body_rec.get('closed'),
        'body_genus': body_rec.get('genus'),
        'body_genus_note': 'genus of the BODY COMPONENT ALONE. The whole-mesh Euler characteristic is a '
        "sum over all %d shells and is not the body's genus." % ncomp,
        'stature_m': round(H, 6),
        'shells': int(len(shells)),
        'loose_vertex_components': sh.loose,
        'inventory': sh.inv,
        # None, not False, when a shell was never tested: 'not enclosed' and 'not looked
        # at' are different answers and only one of them is a measurement
        'all_shells_enclosed': (
            None
            if any(
                s in ('not_tested', 'crossing_not_tested', 'indeterminate', 'outside_body_position_unresolved')
                for s in st.values()
            )
            else bool(all(s == 'enclosed' for s in st.values()))
        ),
        'shells_protruding': protruding,
        'shells_defective': defects,
        'shells_not_tested': untested,
        'shells_nothing_asserted': unasserted,
        'shells_position_unresolved': unresolved,
        'ray_parity_agreement': '%d/%d probes' % (probe_agree, probe_total),
        'convex_envelope': (
            None
            if env is None
            else {
                k: env[k]
                for k in ('available', 'verified', 'facets', 'body_vertices_max_margin_m', 'reason', 'method')
                if k in env
            }
        ),
        'method': 'containment by generalised winding number (Van Oosterom & Strackee solid '
        'angle) against the body component alone, cross-checked by ray parity over %d '
        'Fibonacci directions; escape ("open sky") fraction by the same rays from up '
        'to %d vertices; position of a non-touching shell by exact membership of the '
        "body's verified convex envelope, cross-checked against the derived %.2f "
        'escape bound. Deterministic, no RNG.' % (SKY_DIRECTIONS, SKY_PROBE_VERTICES, ENVELOPE_ESCAPE_MAX_FRACTION),
        'note': 'An INVAGINATION IS OUTSIDE. The mouth and the eye sockets are pockets in the '
        'body shell, so a tongue sitting in the mouth is correctly modelled and still '
        'scores winding 0 everywhere. `all_shells_enclosed` is therefore False on a '
        'perfectly good anny cage and is reported, not gated: the states are what '
        'carry the meaning.',
    }
    detail['containment_tested'] = bool(containment)
    if not containment or unasserted:
        # Deliberate opt-out by the caller. Follows _check_topology_identity's precedent:
        # a question that was never asked is not a failure, but the payload must say out
        # loud that nothing was asserted so a pass cannot be misread as a verification.
        detail['nothing_asserted'] = True
        detail['note_containment'] = (
            'shells were inventoried but enclosure was NOT established: %s. This check '
            'asserted nothing about where they sit.'
            % (
                'containment=False'
                if not containment
                else 'the self-intersection pass was switched off, so face crossings are unmeasured'
            )
        )
    if ambiguous:
        detail['containment_skipped_because'] = (
            'the biggest component is only %.2fx the next by bounding-box diagonal, below '
            'the %.1fx this check requires to call it "the body". Refusing to guess which '
            'shell is the person.' % (ratio, BODY_DOMINANCE_MIN_RATIO)
        )
    truncated = bool(containment and not ambiguous and untested)
    if truncated:
        detail['containment_cap'] = (
            'MAX_SHELLS_ANALYSED=%d bound: %d shell(s) inventoried but not containment-'
            'tested' % (MAX_SHELLS_ANALYSED, len(untested))
        )
    # WHAT THIS CHECK ACTUALLY ASSERTED. A pass here has to mean the question was asked
    # and answered for every shell; `containment=False` is the one case where it means
    # "you told me not to ask", and it is flagged rather than dressed up as a result.
    asserted = bool(containment and not ambiguous and not untested and not unasserted)
    detail['asserted'] = asserted
    detail['asserted_note'] = (
        'True only when enclosure was established for EVERY shell. When it is False the '
        'pass flag is not a verification: containment=False is an explicit opt-out (pass '
        'is left alone, exactly as _check_topology_identity does with an undeclared '
        'scope), and every other way of not establishing it — an ambiguous body '
        'component, the MAX_SHELLS_ANALYSED cap, or self_intersection switched off so '
        'face crossings are unmeasured — FAILS this check rather than passing it '
        'silently.'
    )
    not_established = bool(containment and (unasserted or truncated))
    ok = (
        (not defects) and (not ambiguous) and (not not_established) and (probe_total == 0 or probe_agree == probe_total)
    )
    return {'pass': bool(ok), 'detail': detail}
