# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STAGE e — THE IMPORTANT ONE. KEEP ONLY THE HIGH-FREQUENCY RESIDUAL.

Moved verbatim out of the old single-file scan_ingest.py (lines 1514-2073).

The filter primitives and the stage's individual steps live in `residual_steps.py`
(extracted 2026-10-09 so the stage is readable and each step is unit-testable); they are
re-exported below so every existing importer of this module resolves unchanged.
"""

import time

from zyg_workflows.geom.scan_ingest.constants import (
    DEFAULT_SUBDIV_LEVEL,
    RESIDUAL_CUTOFF_FRAC,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _atomic_json,
    _log,
    _read_json,
    _stage_path,
    _target_cage,
)
from zyg_workflows.geom.scan_ingest import residual_lowpass as _residual_lowpass
from zyg_workflows.geom.scan_ingest.residual_lowpass import (
    _adjacency,
    _calibrate_lowpass,
)
from zyg_workflows.geom.scan_ingest.residual_steps import (
    _apply_lowpass,
    _prepare_surface,
    _probe_sweep,
    _require_calibration_converged,
    _residual_document,
    _residual_fields,
    _resolve_filter_kind,
    _save_residual_npz,
    _scan_points_in_cage_frame,
    _shrinkwrap,
)

# The five primitives this orchestrator does not itself call, re-exported for
# `zyg_workflows.geom.scan_ingest`'s import block and for anything else that has reached
# them through this module. Bound by ASSIGNMENT rather than `from … import`, so the
# re-export needs no F401 suppression.
_lowpass_iters = _residual_lowpass._lowpass_iters
_iter_ceiling = _residual_lowpass._iter_ceiling
_smooth = _residual_lowpass._smooth
_rms0 = _residual_lowpass._rms0
_probe_response = _residual_lowpass._probe_response


# ==================================================================================
# STAGE e — THE IMPORTANT ONE. KEEP ONLY THE HIGH-FREQUENCY RESIDUAL.
# ==================================================================================
def stage_residual(
    out_dir, target_character, *, subdiv_level=DEFAULT_SUBDIV_LEVEL, cutoff_frac=RESIDUAL_CUTOFF_FRAC, verbose=True
):
    """Shrinkwrap the cage to the scan, low-pass the displacement, KEEP THE DIFFERENCE.

    This is the stage that makes a single-body scan safe to use. The full shrinkwrap
    displacement field contains BOTH the scan's proportions (long wavelength: this person's
    legs are longer than our cage's) and the scan's surface detail (short wavelength: this
    person has a clavicle and our cage does not). Low-passing at cutoff_frac * stature and
    subtracting removes the first and keeps the second. The proportions are discarded by
    construction — there is no code path by which they reach the output.

    Displacement is measured ALONG THE CAGE NORMAL (nearest-surface-point shrinkwrap, the
    same mode as Blender's SHRINKWRAP 'NEAREST_SURFACEPOINT'), so what is emitted is a
    scalar field over cage vertices plus the normals it acts along.

    Normals come from relief.newell_vertex_normals: the cage's stored quads are NOT
    consistently ordered — 10,265 of 13,710 mirrored quads start at a different corner —
    and mesh_skeletons._vertex_normals takes each face normal from corners (0,1,2) only,
    giving a direction field that is not mirror-symmetric (max |n - mirror(n)| = 1.168).
    That trap has already cost this codebase one rebuild.
    """
    dn = _read_json(_stage_path(out_dir, 'dense'), 'dense')
    _read_json(_stage_path(out_dir, 'align'), 'align')  # presence check: raises when the align stage is missing

    t0 = time.time()

    cage_v, cage_f = _target_cage(target_character)
    surface = _prepare_surface(cage_v, cage_f, subdiv_level, cutoff_frac, verbose=verbose)

    # scan, in the cage frame
    scan_pts, scan_src = _scan_points_in_cage_frame(out_dir, dn, verbose=verbose)
    sw = _shrinkwrap(surface, scan_pts, scan_src, verbose=verbose)

    # --- low-pass, and MEASURE the filter we actually got -----------------------
    #
    # WHICH FILTER, AND WHY THE DEFAULT CHANGED (2026-08-08).
    # The umbrella-diffusion low-pass was MEASURED, at the real operating edges this
    # module publishes (reject at 0.18 S = upper arm, pass at 0.05 S = zygomatic arch), to
    # be barely separating at all: leakage 0.8648, passage 0.9874, selectivity 1.14 on the
    # level-1 female cage — and 1.00 means NO separation. Three independent faults, all in
    # geom/detail_filter.py's docstring: the operator carries no lengths or areas so its
    # effective cutoff varies across the body; the diffusion family has no steepness
    # parameter (pin the cutoff and N vanishes from the normalised response); and the whole
    # separation has to happen inside a factor of 3.6, which no smooth filter manages.
    #
    # The replacement is a cotan Laplace-Beltrami operator with a Butterworth RATIONAL
    # filter, order 2. Measured on the same probe: selectivity 10.06 / 10.24 / 10.25 at
    # subdivision levels 0 / 1 / 2 — level-independent — at 0.67 s per application on
    # 219,368 vertices. Order 2 and not 4 or 8 deliberately: sharper scores BETTER on
    # sinusoids and WORSE on real fields (mid-scale leakage 0.1374 -> 0.1440 -> 0.1523),
    # so the sweep alone would have picked the wrong order.
    #
    # IT DOES NOT SOLVE THE PROBLEM, and nothing here should be read as claiming it does.
    # 13.7% of a mid-scale proportion still survives into the residual. That is roughly half
    # the old leakage, not zero, and this module remains unfit for a real subject until the
    # separation is done in the model rather than in frequency. See proportion_leakage in
    # the emitted report, which measures rather than assumes it.
    #
    # ZYG_SCAN_FILTER=umbrella restores the old path exactly, for A/B and for rollback.
    A = _adjacency(len(surface.sv), surface.sf)
    filter_kind = _resolve_filter_kind()
    iters, cal = _calibrate_lowpass(A, surface.sv, surface.mean_edge, surface.lam_cut)
    _log(
        verbose,
        'low-pass: lambda_cut %.1f mm, mean edge %.2f mm, %d iters '
        '(analytic %d gave %.3f, calibrated gives %.3f)'
        % (
            1e3 * surface.lam_cut,
            1e3 * surface.mean_edge,
            iters,
            cal['analytic_iterations'],
            cal['analytic_response_at_cutoff'],
            cal['calibrated_response_at_cutoff'],
        ),
    )
    _require_calibration_converged(cal, iters, surface.lam_cut)

    lp = _apply_lowpass(filter_kind, surface, A, sw, iters, cal)
    fields = _residual_fields(sw, lp.stacked)
    probe = _probe_sweep(lp.probe_target, surface.lam_cut)

    npz = _save_residual_npz(out_dir, surface, sw, fields)
    doc = _residual_document(
        surface,
        sw,
        fields,
        probe,
        lp.filter_used,
        cal,
        iters,
        npz,
        target_character=target_character,
        subdiv_level=subdiv_level,
        cutoff_frac=cutoff_frac,
        t0=t0,
    )
    _atomic_json(_stage_path(out_dir, 'residual'), doc)
    _log(
        verbose,
        'residual: coverage %.1f%%, rms %.3f mm, p99 %.3f mm (null p99 %.2f mm)'
        % (
            100 * sw.covered.mean(),
            doc['residual_mm']['rms'],
            doc['residual_mm']['p99_abs'],
            2.45e-3 * surface.stature * 1e3,
        ),
    )
    return doc
