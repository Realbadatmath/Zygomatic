# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The per-step helpers behind STAGE e (`stage_residual`), in the order the stage runs them.

Extracted from `residual.py` on 2026-10-09 so that the stage itself is an orchestrator
short enough to read and so that every step is reachable from a unit test. Nothing here
changes behaviour: the helpers hold the same lines, in the same order, with the same log
lines, the same raises and the same emitted keys as the single 400-line function did.

The umbrella operator and its self-calibration live next door in `residual_lowpass.py`.
"""

import math
import os
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from zyg_workflows.geom.scan_ingest.align import (
    _scan_points_m,
)
from zyg_workflows.geom.scan_ingest.constants import (
    CALIBRATION_TOL,
    LOWPASS_ALPHA,
    SCAN_BUTTERWORTH_ORDER,
    SCHEMA,
    SHRINKWRAP_MAX_FRAC,
    SHRINKWRAP_SUPPORT_FRAC,
    ScanIngestError,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _log,
    _stature_of,
)
from zyg_workflows.geom.scan_ingest.residual_lowpass import (
    _probe_response,
    _smooth,
)

# ==================================================================================
# The steps of stage_residual, in the order the stage runs them
# ==================================================================================


@dataclass
class ResidualSurface:
    """The subdivided cage surface the residual lives on, and the band it can carry."""

    sv: Any
    sf: Any
    normals: Any
    mean_edge: float
    nyquist: float
    stature: float
    lam_cut: float


@dataclass
class Shrinkwrap:
    """What the nearest-point shrinkwrap of the cage onto the scan produced."""

    backend: str
    d: Any
    support: Any
    covered: Any
    far: Any
    d_used: Any


@dataclass
class ProbeTarget:
    """Everything `_probe_active` needs to measure the filter that ACTUALLY ran."""

    kind: str
    sv: Any
    adjacency: Any
    iters: int
    cotan: Any = None
    k_c: float = 0.0


@dataclass
class Lowpass:
    """The low-pass output: the stacked solve, its provenance and its probe handle."""

    stacked: Any
    filter_used: dict
    probe_target: ProbeTarget


@dataclass
class ResidualFields:
    """The per-vertex fields the residual stage emits, plus the zero-fill audit."""

    low: Any
    resid: Any
    resid_zerofill: Any
    hole_delta: Any
    hd: Any


def _mean_edge_length(sv, sf):
    """Mean length of every (directed) polygon edge of the face array `sf` over vertices `sv`.

    In: an (n, 3) vertex array and an (f, k) face array of vertex indices. Out: the mean
    edge length as a float. The surface's Nyquist wavelength is twice this.
    """
    ne = []
    n = sf.shape[1]
    for i in range(n):
        ne.append(np.linalg.norm(sv[sf[:, i]] - sv[sf[:, (i + 1) % n]], axis=1))
    return float(np.concatenate(ne).mean())


def _prepare_surface(cage_v, cage_f, subdiv_level, cutoff_frac, *, verbose=True):
    """Subdivide the cage, take its Newell normals and derive the cutoff band.

    In: the target cage's vertices/faces, the subdivision level and the cutoff as a
    fraction of stature. Out: a ResidualSurface. Raises ScanIngestError when the requested
    cutoff wavelength is at or below the subdivided surface's Nyquist limit — nothing would
    be kept, so the only honest answer is to refuse rather than emit an empty residual.

    Normals come from relief.newell_vertex_normals: the cage's stored quads are NOT
    consistently ordered — 10,265 of 13,710 mirrored quads start at a different corner —
    and mesh_skeletons._vertex_normals takes each face normal from corners (0,1,2) only,
    giving a direction field that is not mirror-symmetric (max |n - mirror(n)| = 1.168).
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom import relief as RELIEF

    stature = _stature_of(cage_v)
    lam_cut = float(cutoff_frac) * stature

    _log(verbose, 'subdividing cage to level %d' % subdiv_level)
    if subdiv_level > 0:
        sv, sf, _cage_edges = MS._subdivide(cage_v, cage_f, subdiv_level)
        sv = np.asarray(sv, np.float64)
    else:
        sv, sf = cage_v, cage_f
    normals = RELIEF.newell_vertex_normals(sv, sf)

    # mean edge length of the surface the residual lives on -> Nyquist
    h = _mean_edge_length(sv, sf)
    nyquist = 2.0 * h
    if lam_cut <= nyquist:
        raise ScanIngestError(
            'cutoff wavelength %.1f mm is at or below the surface '
            'Nyquist limit %.1f mm (mean edge %.2f mm). Nothing would '
            'be kept. Raise subdiv_level.' % (1e3 * lam_cut, 1e3 * nyquist, 1e3 * h)
        )
    return ResidualSurface(
        sv=sv,
        sf=sf,
        normals=normals,
        mean_edge=h,
        nyquist=nyquist,
        stature=stature,
        lam_cut=lam_cut,
    )


def _scan_points_in_cage_frame(out_dir, dn, *, verbose=True):
    """The dense scan's points, moved into the cage frame by the align stage's transform.

    In: the run directory (which must hold `align_T.npy`) and the dense stage's document.
    Out: (points (n, 3) in the cage frame, the name of the source they came from).
    """
    T = np.load(os.path.join(out_dir, 'align_T.npy'))
    scan_pts, scan_src = _scan_points_m(dn, verbose=verbose)
    return scan_pts @ T[:3, :3].T + T[:3, 3], scan_src


def _shrinkwrap(surface, scan_pts, scan_src, *, verbose=True):
    """Project the cage onto the scan and measure the displacement along the cage normal.

    In: a ResidualSurface, the scan points in the cage frame and the source name. Out: a
    Shrinkwrap holding the signed normal displacement `d`, the nearest-neighbour distance
    `support`, the coverage and beyond-max masks and the coverage-masked `d_used`.

    trimesh's nearest-SURFACE-POINT query (the true Blender-style shrinkwrap) needs an
    r-tree index, and `rtree` is not installed in this venv, so what runs is
    nearest-NEIGHBOUR against the scan's own samples. With a Poisson mesh at 2.3 mm
    mean vertex spacing that is a close approximation; with a sparse cloud it is not,
    and the backend name in the report says which one was used.
    """
    from scipy.spatial import cKDTree

    sv, S = surface.sv, surface.stature
    backend = 'nearest_point/' + scan_src
    _log(verbose, 'shrinkwrap onto %s (%d pts) for %d verts' % (backend, len(scan_pts), len(sv)))
    tree = cKDTree(scan_pts)
    dist, idx = tree.query(sv, workers=-1)
    closest = scan_pts[idx]

    delta = closest - sv
    d = np.einsum('ij,ij->i', delta, surface.normals)  # signed, along the cage normal
    support = np.asarray(dist, np.float64)
    covered = support <= SHRINKWRAP_SUPPORT_FRAC * S
    far = np.abs(d) > SHRINKWRAP_MAX_FRAC * S
    return Shrinkwrap(
        backend=backend,
        d=d,
        support=support,
        covered=covered,
        far=far,
        d_used=np.where(covered, d, 0.0),
    )


def _resolve_filter_kind():
    """Which separator ZYG_SCAN_FILTER asks for, lower-cased and validated.

    In: the environment. Out: 'butterworth' (the default since 2026-08-08) or 'umbrella'
    (the legacy path, kept for A/B and rollback). Raises ScanIngestError on anything else
    rather than silently falling back — an artefact that does not say which of two
    separators scoring 1.14 and 10.25 produced it cannot be compared with any other.
    """
    kind = os.environ.get('ZYG_SCAN_FILTER', 'butterworth').strip().lower()
    if kind not in ('butterworth', 'umbrella'):
        raise ScanIngestError('ZYG_SCAN_FILTER must be "butterworth" or "umbrella", got %r' % kind)
    return kind


def _require_calibration_converged(cal, iters, lam_cut):
    """Refuse the stage when the low-pass never reached its stated cutoff on this mesh.

    In: the calibration report from `_calibrate_lowpass`, the iteration count it settled on
    and the cutoff wavelength in metres. Out: None. Raises ScanIngestError when
    `cal['converged']` is false.

    A FILTER THAT DID NOT REACH ITS CUTOFF MAY NOT BE REPORTED AS IF IT HAD. Everything
    downstream — the cutoff wavelength, the representable band, proportion_leakage — is
    stated in terms of a -6 dB response at lam_cut. If the calibration stopped short, none
    of those sentences is true and the correct answer is to refuse, not to emit them with
    a `converged: false` buried three levels down that nothing reads. This is the
    DEFAULT-LEVEL path: at subdiv 2 the old flat 4000-iteration guard stopped the
    calibration at response 0.6163 and the stage reported a 134.4 mm cutoff anyway.
    """
    if cal['converged']:
        return
    raise ScanIngestError(
        'the low-pass did not reach its stated cutoff on this mesh: after %d rounds it '
        'stopped at %d iterations with a measured response of %.4f at lambda_cut = '
        '%.1f mm, against a target of %.2f +/- %.2f%s. Every number this stage would '
        'emit — the cutoff wavelength, the representable detail band, proportion '
        'leakage — is stated in terms of that response, so none of them may be written. '
        'Raise LOWPASS_ITER_GUARD_MULT if the ceiling bound, or lower the subdivision '
        'level.'
        % (
            cal['calibration_rounds'],
            iters,
            cal['calibrated_response_at_cutoff'],
            1e3 * lam_cut,
            cal['target_response_at_cutoff'],
            CALIBRATION_TOL,
            ' (the ITERATION CEILING of %d bound it)' % cal['iteration_ceiling']
            if cal['hit_iteration_ceiling']
            else '',
        )
    )


def _apply_lowpass(kind, surface, adjacency, sw, iters, cal):
    """Low-pass the masked displacement AND the coverage mask through one operator.

    In: the filter kind, a ResidualSurface, the umbrella operator, the Shrinkwrap, the
    calibrated iteration count and the calibration report. Out: a Lowpass whose `stacked`
    is the (n, 2) [field, weight] result, whose `filter_used` is the provenance block the
    artefact carries, and whose `probe_target` measures THIS filter and no other.

    COVERAGE HOLES ARE EXCLUDED FROM THE OPERATOR, NOT SET TO ZERO.
    d_used zero-fills every uncovered vertex, and diffusing that field spreads the zeros
    h*sqrt(2*alpha*n) = 252 mm into covered territory at the level-1 calibration — a
    quarter of the body. Every hole then depresses `low` across its whole neighbourhood
    and `d_used - low` reads that depression as a rim of apparent relief: MEASURED at
    0.430 mm rms and 3.81 mm peak on the synthetic capture's 6.79 % of uncovered
    vertices, i.e. 11.8 % of the residual rms manufactured by the fill, on a body whose
    whole residual rms is 3.65 mm and whose cage relief null p99 is 4.13 mm. A real
    single-camera capture has far bigger holes than 6.79 % (53.9 % has been measured
    here), so this fabricates ridge-scale signal exactly where the scan saw nothing —
    the failure mode SHRINKWRAP_SUPPORT_FRAC exists to prevent.

    The fix is normalised (Knutsson-Westin) diffusion: smooth the masked field and the
    mask through the SAME operator and divide. Uncovered vertices then carry no weight
    instead of carrying the weight of a zero, and `low` at a covered vertex is the
    coverage-weighted mean of the data that exists near it.
    """
    sv, S = surface.sv, surface.stature
    w = sw.covered.astype(np.float64)
    if kind == 'butterworth':
        # SAME normalisation, different low-pass. The field and the mask go through ONE
        # operator and one factorisation (two right-hand sides in a single solve), so the
        # weight that divides `low_num` is smoothed by exactly the filter that produced it.
        # Using a different operator for the two would silently bias every hole rim.
        from zyg_workflows.geom import detail_filter as _DF

        _cot = _DF.cotan_operator(sv, surface.sf)
        _kc = math.sqrt(
            _DF.eig_from_wavelength(_DF.PROPORTION_EDGE_FRAC * S) * _DF.eig_from_wavelength(_DF.DETAIL_EDGE_FRAC * S)
        )
        stacked, _bwmeta = _DF.butterworth_lowpass(
            _cot, np.column_stack([sw.d_used, w]), k_c=_kc, order=SCAN_BUTTERWORTH_ORDER
        )
        _DF.clear_factor_cache(_cot)  # LU fill-in on a 219k complex system is GBs
        from zyg_workflows.geom import controls as _CTL

        filter_used = {
            'kind': 'butterworth',
            'order': SCAN_BUTTERWORTH_ORDER,
            'k_c': float(_kc),
            'operator': 'cotan Laplace-Beltrami',
            'lambda_c_m': _DF.wavelength_from_eig(_kc),
            'cotan_stats': _cot['stats'],
            'factor_s': _bwmeta.get('factor_s'),
            # Stamped INSIDE the branch that ran, per geom/controls.runtime_stamp:
            # a value copied from config describes intent, not behaviour, and
            # that distinction cost a week of benchmarking the wrong baseline.
            'runtime': _CTL.runtime_stamp(
                'detail_filter.butterworth_lowpass on a cotan operator',
                order=SCAN_BUTTERWORTH_ORDER,
                n_verts=int(len(sv)),
            ),
            'measured_selectivity_note': 'operating selectivity measured 10.06/10.24/10.25 at subdiv '
            '0/1/2 against 1.14 for the umbrella path it replaces; see '
            'geom/detail_filter_measure.py',
        }
        target = ProbeTarget(kind=kind, sv=sv, adjacency=adjacency, iters=iters, cotan=_cot, k_c=_kc)
    else:
        stacked = _smooth(adjacency, np.column_stack([sw.d_used, w]), iters)
        filter_used = {
            'kind': 'umbrella',
            'iters': int(iters),
            'operator': 'uniform umbrella (legacy)',
            'calibration': cal,
            'measured_selectivity_note': 'MEASURED operating selectivity 1.14 — barely separating. '
            'Retained for A/B and rollback only.',
        }
        target = ProbeTarget(kind=kind, sv=sv, adjacency=adjacency, iters=iters)
    return Lowpass(stacked=stacked, filter_used=filter_used, probe_target=target)


def _residual_fields(sw, stacked):
    """Divide out the smoothed coverage weight and subtract: the residual, plus its audit.

    In: the Shrinkwrap and the (n, 2) [field, weight] low-pass output. Out: a
    ResidualFields with the normalised low-pass `low`, the emitted `resid` (zeroed outside
    coverage), the `resid_zerofill` the rejected zero-fill path would have produced, their
    difference `hole_delta` and `hd`, that difference restricted to covered vertices.
    """
    covered = sw.covered
    low_num, low_w = stacked[:, 0], stacked[:, 1]
    # Guard the divide. A covered vertex always has weight 1 at iteration 0 and diffusion
    # only mixes in neighbours, so low_w is bounded below by a positive number in practice;
    # the floor is here so a pathological mesh cannot produce inf.
    low = np.where(low_w > 1e-9, low_num / np.maximum(low_w, 1e-9), 0.0)
    low_zerofill = low_num  # what the old path produced, for the audit
    resid = sw.d_used - low
    resid[~covered] = 0.0
    resid_zerofill = np.where(covered, sw.d_used - low_zerofill, 0.0)
    hole_delta = resid - resid_zerofill
    return ResidualFields(
        low=low,
        resid=resid,
        resid_zerofill=resid_zerofill,
        hole_delta=hole_delta,
        hd=hole_delta[covered],
    )


def _probe_active(target, lam):
    """Measure what the filter that ACTUALLY ran does to a wavelength-lam sinusoid.

    In: the ProbeTarget `_apply_lowpass` returned and a wavelength in metres. Out:
    (lowpass_amplitude_ratio, amplitude_kept_by_the_residual), both RMS ratios.

    THE PROBE MUST MEASURE THE FILTER THAT ACTUALLY RAN. This used to call
    _probe_response(A, ...) unconditionally, which measures the UMBRELLA path. With a
    second filter wired in, that would have reported the OLD filter's transfer function
    beside the NEW filter's residual — proportion_leakage would have been a number about
    code that did not execute. Caught before shipping; the probe now dispatches on the
    recorded kind, and a mismatch is impossible by construction because there is one
    branch and it is the same one that produced `low`.
    """
    if target.kind == 'butterworth':
        from zyg_workflows.geom import detail_filter as _DF2

        f = np.cos(2.0 * math.pi * target.sv[:, 2] / lam)
        lp, _m = _DF2.butterworth_lowpass(target.cotan, f.reshape(-1, 1), k_c=target.k_c, order=SCAN_BUTTERWORTH_ORDER)
        lp = lp[:, 0]
        f0, l0, r0 = f - f.mean(), lp - lp.mean(), (f - lp) - (f - lp).mean()
        den = math.sqrt(float((f0 * f0).mean())) or 1e-30
        return (math.sqrt(float((l0 * l0).mean())) / den, math.sqrt(float((r0 * r0).mean())) / den)
    r, _, res, _ = _probe_response(target.adjacency, target.sv, lam, target.iters)
    return r, res


def _probe_entry(lam, lowpass_ratio, residual_ratio):
    """One `measured_filter_response` entry: the measurement and the algebra beside it.

    In: the probe wavelength in metres and the two RMS ratios `_probe_active` returned.
    Out: the dict the artefact carries for that wavelength.
    """
    return {
        'wavelength_mm': 1e3 * lam,
        'lowpass_amplitude_ratio': lowpass_ratio,
        # MEASURED: RMS(f - smooth(f)) / RMS(f), the amplitude the emitted
        # residual really carries at this wavelength. NOT 1 - r; see
        # _probe_response.__doc__ for why that identity does not hold here
        # and by how much it understated the answer.
        'kept_by_residual': residual_ratio,
        'kept_by_residual_is': 'MEASURED RMS(f - lowpass(f)) / RMS(f)',
        'one_minus_lowpass_ratio': 1.0 - lowpass_ratio,
        'one_minus_lowpass_ratio_is': 'the ALGEBRAIC identity this module used to report as '
        'kept_by_residual. It is only equal to the measured value if the '
        'low-pass is a scalar multiple of its input, which it is not on '
        'an irregular mesh. Kept beside the measurement so the size of '
        'the error is visible (%.3f vs %.3f here) and so no reader of an '
        'older artefact compares like with unlike.' % (1.0 - lowpass_ratio, residual_ratio),
    }


def _probe_sweep(target, lam_cut):
    """The honest check: known-wavelength fields on this mesh, through the filter that ran.

    In: the ProbeTarget and the cutoff wavelength in metres. Out: the tag -> entry dict
    for a quarter, a half, one, two and four times the cutoff. z is the body axis, so
    cos(2*pi*z/lambda) is a clean spatial probe.
    """
    probe = {}
    for tag, lam in (
        ('quarter_cutoff', 0.25 * lam_cut),
        ('half_cutoff', 0.5 * lam_cut),
        ('at_cutoff', lam_cut),
        ('double_cutoff', 2.0 * lam_cut),
        ('quadruple_cutoff', 4.0 * lam_cut),
    ):
        r, res = _probe_active(target, lam)
        probe[tag] = _probe_entry(lam, r, res)
    return probe


def _save_residual_npz(out_dir, surface, sw, fields):
    """Write `residual.npz` — the residual, the normals it acts along and the audit fields.

    In: the run directory, a ResidualSurface, the Shrinkwrap and the ResidualFields.
    Out: the absolute path written.
    """
    npz = os.path.join(out_dir, 'residual.npz')
    np.savez_compressed(
        npz,
        residual_m=fields.resid.astype(np.float32),
        normal=surface.normals.astype(np.float32),
        covered=sw.covered,
        raw_displacement_m=sw.d.astype(np.float32),
        lowpass_m=fields.low.astype(np.float32),
    )
    return npz


def _proportion_leakage(probe):
    """THE NUMBER A CALLER MUST READ: how much proportion survives into the residual.

    In: the probe sweep. Out: the `proportion_leakage` block.

    The module docstring says proportions are discarded by construction; this measures how
    true that actually is on this mesh. It is the fraction of an unambiguously
    PROPORTION-scale feature (4x the cutoff wavelength) that survives into the residual. It
    is the MEASURED amplitude of f - lowpass(f), not the algebraic 1 - lowpass_ratio the
    first version of this stage emitted: on the female cage at level 1 that correction
    moves it from 0.295 to 0.549, i.e. the honesty number was itself 1.86x optimistic.
    There is no threshold here on purpose: it is reported, and it is not allowed to move.
    """
    return {
        'probe_wavelength_mm': probe['quadruple_cutoff']['wavelength_mm'],
        'fraction_surviving_into_residual': probe['quadruple_cutoff']['kept_by_residual'],
        'detail_probe_wavelength_mm': probe['quarter_cutoff']['wavelength_mm'],
        'detail_fraction_kept': probe['quarter_cutoff']['kept_by_residual'],
        'selectivity_detail_over_proportion': (
            probe['quarter_cutoff']['kept_by_residual'] / max(probe['quadruple_cutoff']['kept_by_residual'], 1e-12)
        ),
        'measured_not_algebraic': 'fraction_surviving_into_residual is RMS(f - '
        'lowpass(f)) / RMS(f), measured on this mesh. The '
        'algebraic 1 - lowpass_ratio is reported beside '
        'each probe as one_minus_lowpass_ratio and is '
        'smaller; it is not the amplitude the residual '
        'carries.',
        'note': 'the umbrella-Laplacian low-pass is BROAD. Long wavelength is '
        'attenuated, not removed. Read this before trusting a residual; '
        'see the measured sweep in the module docstring.',
    }


def _coverage_hole_report(mean_edge, iters, hd):
    """WHAT THE COVERAGE HOLES CONTRIBUTE, measured rather than assumed.

    In: the mean edge length in metres, the calibrated iteration count and `hd`, the
    covered-vertex difference between the emitted residual and the rejected zero-fill one.
    Out: the `coverage_hole_handling` block.

    `low` is built by coverage-normalised diffusion so holes carry no weight; this is the
    difference against the old zero-fill path, i.e. how much apparent relief the fill WOULD
    have manufactured on this capture.
    """
    return {
        'method': 'normalised diffusion: lowpass(d*covered) / lowpass(covered)',
        'rejected_method': 'zero-fill (d_used = where(covered, d, 0)) then diffuse',
        'diffusion_length_mm': 1e3 * mean_edge * math.sqrt(2.0 * LOWPASS_ALPHA * iters),
        'zerofill_would_have_added_rms_mm': float(1e3 * np.sqrt((hd**2).mean())) if len(hd) else 0.0,
        'zerofill_would_have_added_p99_mm': float(1e3 * np.percentile(np.abs(hd), 99)) if len(hd) else 0.0,
        'zerofill_would_have_added_max_mm': float(1e3 * np.abs(hd).max()) if len(hd) else 0.0,
        'note': 'a hole set to 0 is not an absence, it is a measurement of zero '
        'displacement, and the diffusion spreads it diffusion_length_mm '
        'into surrounding covered surface.',
    }


def _residual_document(
    surface,
    sw,
    fields,
    probe,
    filter_used,
    cal,
    iters,
    npz,
    *,
    target_character,
    subdiv_level,
    cutoff_frac,
    t0,
):
    """Assemble the `residual` stage document from the measurements made above.

    In: the ResidualSurface, the Shrinkwrap, the ResidualFields, the probe sweep, the
    filter provenance block, the calibration report, the iteration count, the npz path and
    the run's identifying arguments plus its start time. Out: the document dict, exactly
    the shape stage_residual has always written to `residual.json`.
    """
    covered, d, S, h = sw.covered, sw.d, surface.stature, surface.mean_edge
    rc = fields.resid[covered]
    return {
        'schema': SCHEMA,
        'stage': 'residual',
        'status': 'ok',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'target_character': target_character,
        'stature_m': S,
        'subdiv_level': int(subdiv_level),
        'surface_vertices': int(len(surface.sv)),
        'mean_edge_mm': 1e3 * h,
        'nyquist_wavelength_mm': 1e3 * surface.nyquist,
        'cutoff_frac_of_stature': float(cutoff_frac),
        'cutoff_wavelength_mm': 1e3 * surface.lam_cut,
        'representable_detail_band_mm': [1e3 * surface.nyquist, 1e3 * surface.lam_cut],
        # WHICH FILTER PRODUCED EVERY NUMBER BELOW. Recorded first and unconditionally:
        # two separators now exist, they score 1.14 and 10.25 on the same probe, and an
        # artefact that does not say which one ran cannot be compared with any other
        # artefact. `alpha` and `iterations` describe the UMBRELLA path only and are
        # meaningless when filter.kind is butterworth — kept for artefact compatibility,
        # not as a description of what happened.
        'filter': filter_used,
        'lowpass': {
            'alpha': LOWPASS_ALPHA,
            'iterations': iters,
            'iterations_applies_to': 'umbrella path only; see filter.kind',
            'calibration': cal,
            'measured_filter_response': probe,
            'measured_filter_response_is': 'MEASURED ON THE FILTER THAT ACTUALLY RAN (filter.kind), not on '
            'the umbrella path unconditionally as an earlier version did.',
            'note': 'iteration count is derived from the heat-kernel relation '
            'in _lowpass_iters, then the response is MEASURED on this '
            'mesh. Trust measured_filter_response, not the derivation.',
        },
        'proportion_leakage': _proportion_leakage(probe),
        'coverage_hole_handling': _coverage_hole_report(h, iters, fields.hd),
        'shrinkwrap': {
            'backend': sw.backend,
            'support_frac_of_stature': SHRINKWRAP_SUPPORT_FRAC,
            'max_frac_of_stature': SHRINKWRAP_MAX_FRAC,
            'coverage': float(covered.mean()),
            'vertices_uncovered': int((~covered).sum()),
            'vertices_beyond_max': int(sw.far.sum()),
        },
        'raw_displacement_mm': {
            'p50': float(1e3 * np.percentile(np.abs(d[covered]), 50)) if covered.any() else None,
            'p99': float(1e3 * np.percentile(np.abs(d[covered]), 99)) if covered.any() else None,
        },
        'residual_mm': {
            'rms': float(1e3 * np.sqrt((rc**2).mean())) if len(rc) else 0.0,
            'p99_abs': float(1e3 * np.percentile(np.abs(rc), 99)) if len(rc) else 0.0,
            'max_abs': float(1e3 * np.abs(rc).max()) if len(rc) else 0.0,
        },
        'relief_null_reference': {
            'cage_null_p99_frac_of_stature': 2.45e-3,
            'cage_null_p99_mm_at_S_1.686': 4.13,
            'note': 'the cage relief null MEASURED in geom/relief.py. '
            'A residual p99 below this is inside the noise '
            'the probes cannot see. It is reported, never '
            'used to move a threshold.',
        },
        'residual_npz': npz,
        'seconds': round(time.time() - t0, 1),
    }
