# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GATES rows, tiers 3 and 4.

Moved verbatim out of the old single-file gates.py (lines 7591-7840).
"""

from zyg_workflows.geom.anthro import integrity as IG

from zyg_workflows.geom.anthro.gates.policy import (
    CANON_DEFINITION,
    DIURNAL_STATURE_RANGE_MM,
    EV_ANSUR_II,
    HOUSE,
    MEASURED,
    MIN_ANTHROPOMETRIC_STATURE_TOL_MM,
    PROVENANCE_RANK,
    VALID_PROVENANCE,
)
from zyg_workflows.geom.anthro.gates.bands import (
    CAL_EMPIRICAL_PERCENTILE,
    CANON_HEADS_TALL,
    CANON_SOURCE,
    CAST_PAIR_SOURCE,
    CAST_SAME_BODY_PERCENTILE,
    CAST_SIMILAR_PERCENTILE,
    DEPTH_RATIOS,
    REALISM_ASYMMETRY_BAND_MM,
    REALISM_ASYMMETRY_POP_MEAN_MM,
    STYLIZATION_AXIS,
    STYLIZATION_AXIS_NOTE,
    SYM_MORPH_TOL_SOURCE,
    _bands,
    _structural,
)
from zyg_workflows.geom.anthro.gates.gate import Gate
from zyg_workflows.geom.anthro.gates.tier3 import (
    t3_cast_diversity,
    t3_depths_wide,
    t3_morph_symmetry,
    t3_realism_asymmetry,
    t3_spine_curvature,
)
from zyg_workflows.geom.anthro.gates.tier4 import (
    REQUIRED_MEASUREMENT_FIELDS,
    t4_canon_and_percentiles,
    t4_measurement_provenance,
    t4_stylization_axis,
    t4_threshold_provenance,
    t4_tolerance_sanity,
)
from zyg_workflows.geom.anthro.gates.tier5_form import _FORM_MODULES
from zyg_workflows.geom.anthro.gates.tier5_capability import (
    _MVCONSIST_BAND,
    t4_form_modules_importable,
    t4_multiview_consistency,
    t4_sfm_capability,
)


GATES_TIERS_3_4 = (
    # -- Tier 3 ---------------------------------------------------------------
    Gate(
        't3_depths_wide',
        3,
        'block',
        'DEPTH-axis metrics banded like the widths',
        {'block': 'p1-p99', 'warn': 'p5-p95'},
        MEASURED,
        'MEASURED percentiles in ANSUR II. Depths are the least stature-predicted class '
        'in the pack (chest depth r=0.22), and a width-only metric set lets a solver dump '
        'its error into the unmeasured depth axis.',
        t3_depths_wide,
        calibration=_bands(DEPTH_RATIOS, policy='wide'),
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't3_morph_symmetry',
        3,
        'block',
        "MORPH-SPACE symmetry against anny's own measured morph-data floor",
        {'tol_mm': IG.SYM_MORPH_TOL_MM},
        HOUSE,
        SYM_MORPH_TOL_SOURCE,
        t3_morph_symmetry,
        calibration=_structural(
            'a CORRECTNESS check on our own build, not a tolerance on realism: a body '
            "out of a bilaterally symmetric morph space is symmetric up to the vendor's "
            'own non-bit-symmetric target data, and that floor is MEASURED (0.0632 mm '
            'over six bodies) rather than assumed. Real people are asymmetric, but real '
            'people are not what this gate measures — t3_realism_asymmetry is, and it '
            'only warns.'
        ),
    ),
    Gate(
        't3_realism_asymmetry',
        3,
        'warn',
        'DELIBERATELY INJECTED realism asymmetry — a different question entirely',
        {'band_mm': list(REALISM_ASYMMETRY_BAND_MM), 'population_mean_mm': REALISM_ASYMMETRY_POP_MEAN_MM},
        HOUSE,
        'HOUSE. Band and population mean taken from the research briefing. Runs ONLY '
        'when the pipeline declares asymmetry was injected, so it can never be used to '
        'excuse a morph-correctness failure.',
        t3_realism_asymmetry,
        calibration=_structural(
            'the band comes from a research briefing, not from a sample on disk; ANSUR '
            'publishes no left-right asymmetry column, so no rejection rate can be '
            'computed. It warns, which is what an ungrounded band is entitled to do.'
        ),
    ),
    Gate(
        't3_spine_curvature',
        3,
        'report',
        'spine curvature with DECLARED endpoints, or not at all',
        None,
        None,
        None,
        t3_spine_curvature,
        calibration=_structural('report-only; gates nothing'),
    ),
    Gate(
        't3_cast_diversity',
        3,
        'warn',
        'same-body syndrome across the registered cast',
        {'same_body_below_percentile': CAST_SAME_BODY_PERCENTILE, 'similar_below_percentile': CAST_SIMILAR_PERCENTILE},
        MEASURED,
        CAST_PAIR_SOURCE,
        t3_cast_diversity,
        calibration={
            'kind': CAL_EMPIRICAL_PERCENTILE,
            'percentile': 100.0 - CAST_SAME_BODY_PERCENTILE,
            'source': CAST_PAIR_SOURCE,
            'why': 'the threshold is the p%g of the distance between two RANDOM '
            'real same-sex subjects, so it flags %g%% of real pairs by '
            'construction. Note the unit is a PAIR, not a subject.'
            % (CAST_SAME_BODY_PERCENTILE, CAST_SAME_BODY_PERCENTILE),
        },
        evidence=EV_ANSUR_II,
    ),
    # -- Tier 4 ---------------------------------------------------------------
    Gate(
        't4_measurement_provenance',
        4,
        'block',
        'every measurement carries landmark + convention + provenance',
        {'required_fields': list(REQUIRED_MEASUREMENT_FIELDS)},
        HOUSE,
        'HOUSE: the pack states that a consumer who cannot state landmark, convention, '
        'population and date for its own measurement may not compare it to these bands.',
        t4_measurement_provenance,
        calibration=_structural(
            'a check on OUR measurement records. A real subject has no provenance field to be missing.'
        ),
    ),
    Gate(
        't4_threshold_provenance',
        4,
        'block',
        'every shipped threshold is tagged MEASURED, CANON or HOUSE, and no CANON threshold outranks a survey',
        {
            'valid': list(VALID_PROVENANCE),
            'rank': dict(PROVENANCE_RANK),
            'canon_may_not_block': 'any quantity in MEASURED_COVERED_QUANTITIES',
        },
        HOUSE,
        'HOUSE: the engine refuses to run on a CONTESTED or untagged threshold, and on a '
        'CANON threshold that claims block severity over a quantity ANSUR/CDC/NHANES '
        'already answers. This is what keeps the golden ratio, WHR 0.7 and the Adonis '
        "index out of the registry — and now also what keeps AFS p.91-93's head-unit "
        'charts from gating crotch height against NHANES III. ' + CANON_DEFINITION,
        t4_threshold_provenance,
        calibration=_structural('a check on the REGISTRY, not on the body. Its subject is this file.'),
    ),
    Gate(
        't4_stylization_axis',
        4,
        'warn',
        'the BodyProportions stylization axis is a recorded decision, not a default',
        {'axis': STYLIZATION_AXIS},
        HOUSE,
        STYLIZATION_AXIS_NOTE,
        t4_stylization_axis,
        calibration=_structural('asks whether a decision was RECORDED; no population declares a stylization axis'),
    ),
    Gate(
        't4_canon_and_percentiles',
        4,
        'report',
        'percentile placement and distance from the 8-head canon',
        {'canon_heads_tall': CANON_HEADS_TALL},
        HOUSE,
        CANON_SOURCE,
        t4_canon_and_percentiles,
        calibration=_structural(
            'report-only, and deliberately so: the 8-head canon is '
            'an art convention with no survey behind it and is never '
            'gated at any severity'
        ),
    ),
    # NEW 2026-08-08. A CAPABILITY gate, not a body gate. See the source note.
    Gate(
        't4_sfm_capability',
        4,
        'report',
        'can the photogrammetry stack still do what we believe it can (probed, not assumed)',
        None,
        HOUSE,
        'HOUSE, and there is no threshold at all — the field is None because this gate '
        'compares the MACHINE against its own recorded baseline '
        '(data/assets/sfm/capability_baseline.json), not a body against a survey. It is '
        'HOUSE for the same reason t4_multiview_consistency is: the subject is our own '
        'installation, and a census of our own state is a HOUSE fact. '
        'WHY A MACHINE CHECK LIVES IN A BODY REGISTRY: on 2026-08-08 we deferred building '
        'a CUDA COLMAP for good reasons (nothing to reconstruct yet; scan_ingest blocked '
        'behind an unsolved separation problem). The danger of that decision is not that '
        'it was wrong, it is that it gets forgotten — geom/scan_ingest.py degrades its '
        'dense stage to two-view cv2.StereoSGBM without failing, and a degraded run still '
        'emits a mesh, so the symptom surfaces months later as an unexplained soft surface '
        'that looks like a filter problem. This gate puts the absence in front of every '
        'suite run so that afternoon never happens. It also carries the driver-stack split '
        'check, which is the one failure that takes ComfyUI and every other GPU service '
        'down with it.',
        t4_sfm_capability,
        calibration=_structural(
            'report-only and structurally so. There is no population of human beings that '
            'this gate rejects a fraction of — its subject is an installation — so no '
            'rejection rate exists to calibrate against, and it must never block a body '
            'for a fact about a machine. It reports even when everything is AVAILABLE, '
            'because a capability check that goes silent on success is indistinguishable '
            'from one that has stopped running.'
        ),
    ),
    # NEW 2026-08-08. REPORTING ON FIRST INTRODUCTION — see the severity note below.
    Gate(
        't4_multiview_consistency',
        4,
        'report',
        'does the 48-cell contact sheet reconstruct as ONE 3D object (COLMAP SfM)',
        dict(_MVCONSIST_BAND),
        HOUSE,
        'HOUSE. The band is the midpoint of OUR OWN rendered controls — a textured '
        'positive, an untextured positive and a deliberately mixed negative, rendered by '
        'geom/mv_render.py and measured by geom/mvconsist.py at pycolmap 4.1.1 without '
        'CUDA. It is HOUSE and not MEASURED because MEASURED in this registry means a '
        'survey of PEOPLE (see MEASURED_EVIDENCE_CLASSES: reference_pack or '
        'published_series), and the class that would have covered this — own_assets — was '
        'WITHDRAWN on 2026-08-06 with the ruling "a census of our own output is a HOUSE '
        'fact, not a survey". A control we rendered is our own output. Tagging it MEASURED '
        'would re-open, two days later, the exact bypass that withdrawal closed. It is not '
        'CANON either: no number here came off a page. '
        'CONTAMINATION, MEASURED not assumed: the floor was built from cells belonging to '
        'the same characters the gate judges. Leave-one-out (data/assets/anthro_reports/'
        'mvconsist/FLOOR_CONTAMINATION.json) moved the thresholds to [0.53-0.56] x '
        '[5.09-5.50]; four of five characters keep their verdict everywhere in that '
        'envelope and e58b9137bdc5 does not, so its grade is borderline-and-contaminated '
        'rather than a clean fail. Only a held-out sheet fixes that, and six complete '
        'sheets is all that exists.',
        t4_multiview_consistency,
        calibration=_structural(
            'report-only, and new. The subject is OUR RENDERED IMAGES, not a person: there '
            'is no population of human beings that this band rejects a fraction of, so no '
            'rejection rate exists to calibrate against. It is registered at severity '
            '"report" because it has never been run against the full cast — a gate that '
            'has not been shown to behave on the bodies it will judge has not earned a '
            'blocking claim, whatever its band says.'
        ),
    ),
    Gate(
        't4_tolerance_sanity',
        4,
        'block',
        'refuse a sub-diurnal stature tolerance presented as anthropometric',
        {'min_anthropometric_tol_mm': MIN_ANTHROPOMETRIC_STATURE_TOL_MM},
        HOUSE,
        'HOUSE floor from the MEASURED diurnal stature range %.1f-%.1f mm.' % DIURNAL_STATURE_RANGE_MM,
        t4_tolerance_sanity,
        calibration=_structural(
            'judges the TOLERANCE the caller declared, not the body. It rejects a claim, and a claim is not a person.'
        ),
    ),
    Gate(
        't4_form_modules_importable',
        4,
        'block',
        'every tier-5 module imports as a package AND runs as a script',
        {'importable': len(_FORM_MODULES), 'with_script_bootstrap': len(_FORM_MODULES)},
        HOUSE,
        'HOUSE. A tier-5 module that will not import turns every gate that reads it into '
        "an ERROR row, and a module that will not run as a script turns a developer's "
        'first command into a ModuleNotFoundError. Both were MEASURED on 2026-08-06: '
        'geom/form/hands.py had no repo-root bootstrap and raised ModuleNotFoundError at '
        'hands.py:2791 from any cwd but the repo root. '
        'TEST CORRECTED 2026-08-06 (D4): the script-mode half tested for the SUBSTRING '
        '"sys.path.insert" in the source text, which passed a lesion module whose only '
        'occurrence of the string was inside a docstring while that module genuinely '
        'raised ModuleNotFoundError in script mode, and which would have false-FAILED a '
        'module bootstrapping with sys.path.append. It now RUNS each module the way '
        "`python <file>` runs it — sys.path[0] set to the file's own directory, a "
        'foreign cwd, -E -s and PYTHONPATH/PYTHONHOME scrubbed so an inherited path '
        'cannot mask the failure — and asks whether `geom` resolves afterwards. A probe '
        'that cannot be run is ERROR, never a pass.',
        t4_form_modules_importable,
        calibration=_structural(
            "the subject is this repository's import graph, not a "
            'body. No population has a rate for a missing sys.path '
            'entry.'
        ),
    ),
)
