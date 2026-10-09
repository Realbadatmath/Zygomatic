# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of ``measurement.measure``, one function each.

``measure`` used to be a 338-line triple loop — body, level, cut kind — with the
report whitelists, the determinism checks and the printed tables inline. The
stages were cut out of it unchanged and are called in the same order:

    prepare_cage_body    the delivered cage, its mirror map, the cage-level relief
    cage_body_record     the per-body report section
    level_meshes         base / cage2sub / sub at one subdivision level
    level_null_record    the ONE null every state at that level is scored against
    body_pools           the ridge pools of the untouched subdivided body
    cuts_record          the whitelisted cut record for one cut kind
    probe_all_states     the probe of every state at that cut
    print_cut_table      the per-landmark verdict table

``_row`` and ``_fmt`` moved here with ``probe_all_states`` and
``print_cut_table``, their only callers; ``measurement`` re-binds both, so
``relief_subdiv.__init__`` reaches them unchanged.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from zyg_workflows.geom.relief_subdiv.constants import (
    CAGE_FACES,
    CAGE_VERTS,
    SCHEMA,
    _module_provenance,
)
from zyg_workflows.geom.relief_subdiv.subdivision import (
    _verify_fast_mirror_map,
    subdivide,
    verify_index_preservation,
)
from zyg_workflows.geom.relief_subdiv.nulls import level_null, probe_at_cut
from zyg_workflows.geom.relief_subdiv.layer import apply_relief_at, mirror_audit

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# The keys of a level_null() result that go into the report verbatim.
_NULL_KEYS = (
    'level',
    'stature_m',
    'seed',
    'seeds',
    'target_sizes',
    'target_size_rule',
    'n_pools_per_size',
    'under_powered_vs_shipped_panel',
    'headline',
    'seconds',
    'point_null_is_one_draw',
)
# The keys of a cuts_for() mode that go into the report. `null_rate_measured_at` IS PART
# OF THE WHITELIST, not decoration: a chance rate is meaningless without the cut it was
# measured at, and this report used to print the rate and drop that. The whole defect
# cuts_for's level branch was rewritten for was a rate quoted beside a cut it had not
# been measured at.
_CUT_KEYS = (
    'min_frac_stature',
    'min_contrast',
    'min_run',
    'min_run_any_sign',
    'source',
    'null_rate_resolved',
    'null_rate_point_only_or_better',
    'null_rate_measured_at',
)
# The per-feature fields of a relief report that survive into the measurement report.
_FEATURE_KEYS = (
    'name',
    'claim',
    'status',
    'n_seeds_total',
    'n_vertices_touched',
    'delivered_amp_mm',
    'delivered_amp_frac_stature',
    'refused_anchor_points',
)


def _row(rec):
    """(verdict, run, peak_mm, contrast, resolves) from a probe record, or a stub."""
    if rec.get('status') != 'ok':
        return (rec.get('status') or 'EMPTY', 0, None, None, False)
    m = rec.get('resolution_mode')
    per = (rec.get('by_mode') or {}).get(m) or {}
    return (
        rec.get('resolution_verdict') or '?',
        per.get('longest_run') or 0,
        per.get('peak_relief_mm'),
        per.get('peak_contrast'),
        bool(rec.get('resolves_relief')),
    )


def _fmt(t):
    """One `_row` tuple as a fixed-width `verdict/run peak cPEAK_CONTRAST` cell."""
    return '%-11s/%d %8s c%-6s' % (
        t[0],
        t[1],
        ('%.2f' % t[2]) if t[2] is not None else '-',
        ('%.1f' % t[3]) if t[3] is not None else '-',
    )


@dataclass
class CageBody:
    """One registered body at cage level, with everything the level loop reuses.

    `v0`/`faces0` are the delivered cage and `stature_m` its Z extent; `mate0` is the
    mirror map at cage resolution, reused as the seed map at every level; `v0_relief` is
    the cage-level relief applied ONCE (the input to the cage2sub control) and
    `cage_report` is relief.apply_relief's own last report for it; `fast_mirror_check`
    holds the index-for-index comparison of the fast mirror map against
    relief.mirror_map, at cage level and at level 1.
    """

    who: str
    params: dict
    v0: Any
    faces0: Any
    bones: Any
    weights: Any
    stature_m: float
    mate0: Any
    v0_relief: Any
    cage_report: dict = field(default_factory=dict)
    fast_mirror_check: dict = field(default_factory=dict)


def report_header(scale, states, cut_kinds):
    """The report envelope: schema, date, the run's settings and the module provenance."""
    return {
        'schema': SCHEMA,
        'date': time.strftime('%Y-%m-%d %H:%M:%S'),
        'scale': float(scale),
        'states': list(states),
        'cut_kinds': list(cut_kinds),
        # WHICH BUILD OF THIS MODULE PRODUCED THE REPORT. Without it a report cannot be
        # told apart from one written by an earlier version, and that is not
        # hypothetical: the first delivered level-2 artefacts came from a build that
        # mirrored through the GEOMETRIC map and reported a fired Newell symmetry
        # warning the current default does not produce, and from a cuts_for that took
        # the level cut from ONE null draw. Both sat on disk looking current. A reader
        # who finds a source_sha256 that is not this file's is reading a stale artefact.
        'produced_by': _module_provenance(),
        'bodies': {},
    }


def prepare_cage_body(who, p, scale, bone_names, verbose):
    """Build one registered body's cage, its mirror map and its cage-level relief.

    `p` is the registry's `params` block for `who`. Refuses a cage that is not the
    authored CAGE_VERTS/CAGE_FACES, checks the fast mirror map index for index against
    the function it replaces, then applies the cage-level relief once. Returns a
    :class:`CageBody`.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom import relief as RL

    v0, faces0, bones, weights = RL.bones_for(
        p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None
    )
    v0 = np.asarray(MS._apply_anatomy(v0, faces0, p.get('anatomy_layer') or {}), np.float64)
    faces0 = np.asarray(faces0, np.int64)
    if len(v0) != CAGE_VERTS or len(faces0) != CAGE_FACES:
        raise ValueError(
            '%s is a %d-vertex / %d-quad cage, not the authored %d/%d'
            % (who, len(v0), len(faces0), CAGE_VERTS, CAGE_FACES)
        )
    S0 = float(v0[:, 2].max() - v0[:, 2].min())
    mate0, _ = RL.mirror_map(v0, RL.MIRROR_TOL_FRAC * S0)
    # The substitution used inside the layer at levels 2 and 3, checked index for index
    # against the function it replaces — at cage level, and at level 1 where the loop
    # version is still affordable. If these ever disagree, the fast path is wrong and
    # every mirrored seed above level 1 is suspect.
    v1, f1, _p1 = subdivide(v0, faces0, 1)
    fast_check = {
        'cage': _verify_fast_mirror_map(v0, RL.MIRROR_TOL_FRAC * S0),
        'level1': _verify_fast_mirror_map(v1, RL.MIRROR_TOL_FRAC * float(v1[:, 2].max() - v1[:, 2].min())),
    }
    del v1, f1
    if verbose:
        _zyg_log.info(
            '    fast_mirror_map vs relief.mirror_map: cage %s, level1 %s' % (fast_check['cage'], fast_check['level1'])
        )

    # the CAGE-level relief, once — it is the input to the cage2sub control
    v0_relief = np.asarray(
        RL.apply_relief(
            v0,
            faces0,
            {RL.ANATOMY_KEY: float(scale)},
            phenotype=p['phenotype'],
            bones=bones,
            weights=weights,
            bone_names=bone_names,
            stature_m=S0,
        ),
        np.float64,
    )
    return CageBody(
        who=who,
        params=p,
        v0=v0,
        faces0=faces0,
        bones=bones,
        weights=weights,
        stature_m=S0,
        mate0=mate0,
        v0_relief=v0_relief,
        cage_report=dict(RL.apply_relief.last_report or {}),
        fast_mirror_check=fast_check,
    )


def cage_body_record(cb):
    """The per-body report section: cage stature, the cage-level relief, the mirror check.

    `levels` starts empty; the level loop fills it, keyed by the level as a string.
    """
    cage_rep = cb.cage_report
    return {
        'stature_cage_m': cb.stature_m,
        'cage_relief_report': {
            'displaced_vertices': cage_rep.get('displaced_vertices'),
            'max_displacement_mm': cage_rep.get('max_displacement_mm'),
            'amplitude_audit': (cage_rep.get('amplitude_audit') or {}).get('below_null_by_amplitude'),
            'mirror': cage_rep.get('mirror'),
        },
        'fast_mirror_map_verification': cb.fast_mirror_check,
        'levels': {},
    }


def _relief_report(rep):
    """The whitelisted relief report for one subdivision level, features included."""
    return {
        'displaced_vertices': rep.get('displaced_vertices'),
        'max_displacement_mm': rep.get('max_displacement_mm'),
        'rms_displacement_mm': rep.get('rms_displacement_mm'),
        'mirror': rep.get('mirror'),
        'amplitude_audit': (rep.get('amplitude_audit') or {}).get('below_null_by_amplitude'),
        'bone_frame_cage_failures': rep.get('bone_frame_cage_failures'),
        'mirror_map_used': rep.get('mirror_map_used'),
        'features': [{k: r.get(k) for k in _FEATURE_KEYS} for r in rep.get('features', [])],
        'seconds': rep.get('seconds'),
    }


def _print_level_audits(lrec):
    """Print the index-preservation and mirror-audit headlines for one level."""
    ia = lrec['index_preservation']
    ma = lrec['mirror_audit']
    _zyg_log.info(
        '    index preservation: originals moved max %.2f mm, corner counts preserved=%s'
        % (ia['positional_moved_mm']['max'], ia['structural_corner_count_preserved'])
    )
    _zyg_log.info(
        '    mirror audit: geometric %d paired (residual %.4f mm), combinatorial %d paired (%.4f mm), disagreements %d'
        % (
            ma['geometric']['paired'],
            ma['geometric']['mesh_mirror_residual_mm'] or -1,
            ma['combinatorial']['paired'],
            ma['combinatorial']['mesh_mirror_residual_mm'] or -1,
            ma['disagreements_where_both_paired'],
        )
    )


def level_meshes(cb, lv, scale, bone_names, lrec, verbose):
    """The three states at subdivision level `lv`, and the faces they share.

    Returns ``({'base': …, 'cage2sub': …, 'sub': …}, faces)``. At level 0 all three are
    cage-resolution: `base` is the delivered cage and `sub` is relief.py's own result, so
    the published 0/20 is reproduced inside the same run rather than quoted. Above level
    0, `base` is the subdivided cage, `sub` is the relief evaluated AT subdivision level
    and `cage2sub` is the cage-level relief subdivided afterwards — the control that
    makes `sub` minus `cage2sub` attributable to the higher resolution alone. Fills
    `lrec` with the subdivision record, the relief report and, above level 0, the
    index-preservation check and the mirror audit, which it prints when `verbose`.
    """
    if lv == 0:
        lrec['subdivision'] = {'levels': 0, 'per_level': []}
        lrec['relief_report'] = {
            'displaced_vertices': cb.cage_report.get('displaced_vertices'),
            'max_displacement_mm': cb.cage_report.get('max_displacement_mm'),
            'mirror': cb.cage_report.get('mirror'),
        }
        return {'base': cb.v0, 'cage2sub': cb.v0_relief, 'sub': cb.v0_relief}, cb.faces0

    v_base, v_sub, faces_s, rep = apply_relief_at(
        cb.v0,
        cb.faces0,
        lv,
        cb.params['phenotype'],
        cb.bones,
        cb.weights,
        bone_names,
        scale=scale,
        mate_cage=cb.mate0,
        verbose=verbose,
    )
    v_c2s, _f2, _pv = subdivide(cb.v0_relief, cb.faces0, lv)
    lrec['subdivision'] = rep['subdivision']
    lrec['relief_report'] = _relief_report(rep)
    lrec['index_preservation'] = verify_index_preservation(cb.v0, v_base, cb.faces0, faces_s, lv)
    lrec['mirror_audit'] = mirror_audit(v_base, faces_s, cb.mate0, cb.faces0, lv)
    if verbose:
        _print_level_audits(lrec)
    return {'base': v_base, 'cage2sub': v_c2s, 'sub': v_sub}, faces_s


def level_null_record(v_base, faces_s, lv, stature_m, lrec, verbose):
    """Draw the ONE null for this level and record its whitelisted summary in `lrec`.

    The null is measured on the UNTOUCHED subdivided body and used for every state at
    this level: a before/after table whose columns were scored differently is not a
    comparison. Returns the full null dict, which `cuts_for` needs.

    The record carries THE SEED PANEL BEHIND THE LEVEL CUT in full — every seed's own
    station p99, the spread across them, the pooled run histogram scored AT the panel cut
    and the chance rate measured at that same cut. Anyone re-reading a level-cut
    resolution needs all four, and the first version of this report shipped none of them:
    it shipped one draw and a rate borrowed from a different cut.
    """
    nul = level_null(v_base, faces_s, lv, stature_m=stature_m, verbose=verbose)
    lrec['null'] = {k: nul[k] for k in _NULL_KEYS}
    lrec['null']['ridge_panel'] = nul['ridge_panel']
    lrec['null']['point_null_distribution'] = {
        k: nul['point_null'][k]
        for k in ('n', 'refused', 'pool', 'abs_relief_frac', 'abs_contrast', 'collar_fit_rms_mm')
    }
    lrec['null']['ridge_station_p99'] = {
        m: {
            'frac_stature': nul['ridge_null']['by_mode'][m]['abs_station_relief_frac']['p99'],
            'contrast': nul['ridge_null']['by_mode'][m]['abs_station_contrast']['p99'],
            'discrete_min_run': nul['ridge_null']['by_mode'][m]['discrete_min_run'],
            'n_stations_scored': nul['ridge_null']['by_mode'][m]['n_stations_scored'],
            'frac_pools_resolved': nul['ridge_null']['by_mode'][m]['frac_pools_resolved'],
        }
        for m in ('ridge', 'point')
    }
    return nul


def body_pools(v_base, faces_s, stature_m, doc, lrec):
    """The ridge pools of the UNTOUCHED subdivided body; records their sizes in `lrec`.

    Every state at this level is probed against these same pools, for the same reason
    the null is drawn once: a pool set that moved between columns is not a comparison.
    """
    from zyg_workflows.geom.form import curvature as CV
    from zyg_workflows.geom.form import ridge as RD

    nrm = CV.vertex_normals(v_base, faces_s)
    pools = RD.body_pools(v_base, faces_s, stature_m, nrm, doc)
    lrec['pool_sizes'] = {n: int(len(pl)) for n, _k, _p, pl, _pr, _e in pools}
    return pools


def cuts_record(cuts):
    """The whitelisted cut record for one cut kind, both resolution modes."""
    return {m: {k: cuts[m][k] for k in _CUT_KEYS if k in cuts[m]} for m in ('ridge', 'point')}


def probe_all_states(lrec, meshes, faces_s, pools, cuts, states, kind, stature_m, verbose):
    """Probe every state at this cut kind and record its per-landmark rows in `lrec`.

    Curvature, normals and mixed-Voronoi areas are recomputed per state — they are
    properties of that state's vertices, not of the shared topology — and the per-state
    record holds the resolved count, the wall time and one row per landmark pool.
    """
    from zyg_workflows.geom.form import curvature as CV

    names = [n for n, *_ in pools]
    for st in states:
        vv = meshes[st]
        t0 = time.time()
        ar = CV.mixed_voronoi_area(vv, faces_s)
        nv = CV.vertex_normals(vv, faces_s)
        cu = CV.curvature(vv, faces_s, stature_m=stature_m, normals=nv)
        recs = probe_at_cut(vv, faces_s, pools, cuts, stature_m=stature_m, areas=ar, normals=nv, curv=cu)
        dt = time.time() - t0
        rows = {n: _row(recs[n]) for n in names}
        nres = sum(1 for n in names if rows[n][4])
        lrec['states']['%s@%s' % (st, kind)] = {
            'resolved': nres,
            'of': len(names),
            'seconds': dt,
            'rows': {
                n: {
                    'verdict': rows[n][0],
                    'run': rows[n][1],
                    'peak_relief_mm': rows[n][2],
                    'peak_contrast': rows[n][3],
                    'resolves': rows[n][4],
                }
                for n in names
            },
        }
        if verbose:
            _zyg_log.info('    [%s cut] %-9s %2d/%d resolved  (%.0fs)' % (kind, st, nres, len(names), dt))


def print_cut_table(lrec, pools, states, kind, cuts):
    """Print the per-landmark verdict table for one cut kind, one column per state.

    The header quotes the ridge-mode cut the rows were scored at; the `RESOLVES` tail
    marks a landmark the LAST state resolves, which is the claim the table exists to
    support.
    """
    _zyg_log.info(
        '\n    per-landmark, %s cut  (min_frac_stature %.4e, contrast %.2f, min_run %d for mode ridge)'
        % (kind, cuts['ridge']['min_frac_stature'], cuts['ridge']['min_contrast'], cuts['ridge']['min_run'])
    )
    hdr = '      %-24s' % 'landmark'
    for st in states:
        hdr += ' %-26s' % st
    _zyg_log.info(hdr)
    for n, *_ in pools:
        line = '      %-24s' % n
        for st in states:
            r = lrec['states']['%s@%s' % (st, kind)]['rows'][n]
            line += ' %-26s' % _fmt((r['verdict'], r['run'], r['peak_relief_mm'], r['peak_contrast'], r['resolves']))
        tail = ' RESOLVES' if lrec['states']['%s@%s' % (states[-1], kind)]['rows'][n]['resolves'] else ''
        _zyg_log.info(line + tail)
