# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RIDGE / STRIP / PIT relief — the curve primitive, and the honest re-probe it enables.

WHY THIS MODULE EXISTS
`curvature.region_relief` measures a PATCH against an ISOTROPIC collar taken all the way
round it. That is the right instrument for a knuckle and the wrong one for a bone. The
anatomy references this package is being built against say so explicitly:

  * AFS p.10 names clavicle, scapula, sternum and pelvis as WHOLE-BONE landmarks — curves,
    not points.
  * AFS p.171: the subcutaneous border of the ulna reads as a ridge OR AS A FURROW along
    its length. Continuity is the signal; polarity is not.
  * AFS p.206: the medial tibia is a flat STRIP running continuously into the medial
    malleolus — one feature, not two.
  * Sign is often NEGATIVE. PSIS is a pair of PITS (AFS p.11, p.56); the jugular notch is
    "the pit of the neck" (HeadNeck p.160); the tear trough is how the orbital rim reads
    (HeadNeck p.31); the greater trochanter becomes a DIMPLE at high bodyfat (AFS p.195).
    A bump test at those sites is wrong even on a perfect mesh.
  * HeadNeck p.80 splits its head landmarks into SOLID-line (a ridge — gate for relief) and
    DOTTED-line (a flat FACET — gate for the ABSENCE of curvature variance). Five of the
    eleven are facets, and a bump test on a facet is a category error.

THE MEASURED REASON AN ISOTROPIC COLLAR CANCELS A RIDGE, and it is not a theoretical worry.
`curvature.collar` selects the geodesic band [gap, gap+width] = [0.006, 0.020] of stature
around the group — 10 mm to 34 mm at the neutral's 1.686 m. A clavicle is roughly 10-15 mm
wide and 130 mm long. A collar taken round a patch ON that bone therefore runs ALONG the
bone at both ends of the patch, so the reference surface it fits already contains the
feature, and the feature is subtracted from itself. MEASURED on the anny neutral, same
window, same candidate curves, only the collar changed: the zygomatic arch goes from
+10.04 mm at contrast 4.07 over a 3-station run to +14.02 mm at CONTRAST 18.47 over a
6-station run, and regions.py's clavicle window goes from a best of -3.48 mm at contrast
-1.05 to +5.65 mm at contrast +3.45. The relief barely moves; the CONTRAST is transformed,
because its denominator was the feature leaking into its own reference surface.

WHAT THE RE-PROBE ACTUALLY FOUND — the honest headline, measured on all four issued
characters plus the anny-neutral control (run `python -m zyg_workflows.geom.form.ridge probe`):

  * THE BODY IS STILL EMPTY. Of the 20 regions in regions.REGION_SPEC, across 5 bodies =
    100 probes, the curve primitive resolves a ridge or a furrow 4 times — ulnar_head on the
    neutral, malleolus_lat on male, deltopectoral_triangle and patella on female — and NOT
    ONE of them reproduces on a second body. Nothing at all resolves on abel or cornelis.
    At the measured <=1% per-probe false-positive rate that is indistinguishable from noise,
    and the reproducibility test settles it: these groups are frozen skin and the macros are
    smooth, so a bone that is in the cage's vocabulary would appear on all five bodies. None
    does. The wrong-primitive hypothesis is REJECTED for the body: regions.py's "0 of 20"
    is not a probe artefact.
  * THE HEAD IS NOT EMPTY, AND THE ZYGOMATIC ARCH IS REAL. It resolves as a ridge on 5 of 5
    bodies (runs 6/3/2/4/3, weakest station of each run +5.7 to +9.9 mm at contrast 4.4 to
    7.8, arcs 6.9-18.7 mm). It resolves under BOTH primitives, so it is not a primitive
    artefact either — but the briefing's note that it "fails only the CONTRAST test, 2.35
    against a required 3.70" WAS a collar artefact: with a cross-curve collar the arch's
    stations run at contrast 5-23. nasal_bone reaches ridge on 2 of 5 (neutral, cornelis,
    arcs 11-12 mm) and orbital_margin on 2 of 5 (male, female) — and it CHANGES SIGN between
    them, a ridge on the male and a FURROW on the female, which is HeadNeck p.31's tear
    trough and which only polarity='either' can see. Read orbital_margin with care: its
    runs span 2.0 mm and 5.3 mm of arc, i.e. two adjacent vertices, so it is a point that
    happened to pass a run test, not a demonstrated whole-bone curve.
  * FIVE OF THE ELEVEN HEAD LANDMARKS WERE NEVER RELIEF QUESTIONS. HeadNeck p.80 draws them
    dotted, i.e. flat facets. superciliary_arch tests 'facet' on 5 of 5 bodies with a
    patch/collar curvedness ratio of 0.28-0.45 against a skin-null 1st percentile of 0.650 —
    flatter than 99% of ordinary skin, on every body. The bump test it "failed" was the
    wrong test.
  * FOUR OF THE 12 HEAD WINDOWS ARE NOT MEASURABLE BY ANY PRIMITIVE, and that is a
    window-authoring defect rather than a result. Eop and cervicale ask for y in
    [+0.020, +0.110] of stature while the ENTIRE CAGE spans y in [-0.2496, +0.018] — they
    are behind the back of the body. mastoid and temporal_fossa ask for |x| >= 0.045 at head
    heights where the head's own half-width is 0.0515-0.0524, and the surviving sliver is
    then cut by their y range. gonion (3 vertices) and temporal_line (7) are a tessellation
    limit: the window is a cluster, not a curve. Those six rows say nothing about relief.
  * ONE FINDING ABOUT OUR CHARACTERS. The sacral window that regions.py already flagged as a
    23-vertex tessellation limit collapses to ONE VERTEX on cornelis. A PSIS predicate is
    not merely unresolved on him, it is unmeasurable in principle.

WHAT "RESOLVES" MEANS, AND WHY THE ANSWER LIVES IN THIS FILE
A verdict is a name; whether it counts as finding a landmark is a CALIBRATION decision, and
calibration decisions belong beside the null they were measured against. RESOLVED_VERDICTS
is that decision and `resolves_relief` on every record is how a consumer reads it. Nothing
downstream may re-list verdict strings for itself.

The rule exists because the opposite already shipped. An adapter wrote its own list and
included 'point_only' — which this module defines as a qualifying run SHORTER than min_run,
and min_run is the null's p99 + 1, so point_only is the null's measured support by
construction. MEASURED with the shipped seed over the same 120 landmark-free skin pools:
33.3% of them produce a point_only-or-better reading in ridge mode, 6.7% in point mode,
37.8% under the two-mode union a probe is actually scored on. Counting it turned abel's
body result into "8 of 20 resolve" — 0.40 against a chance rate of 0.3778, z = 0.21, a
headline indistinguishable from pointing the instrument at blank skin. Under the contract
the same run reads 0 of 20, which is the pre-existing finding this module was built to
re-test and is the correct answer: the cage has no clavicle, no iliac crest, no trochanter
and no PSIS.

HEAD AND BODY ARE COUNTED SEPARATELY AND MAY NOT BE SUMMED. The head windows are scored at
a cut calibrated on TORSO AND LIMB skin, they are report-only for that reason, and the head
is genuinely a different regime — orbital margin +20.03 mm, nasal bone +16.93 mm,
superciliary arch +15.39 mm, zygomatic arch +10.79 mm against a best body landmark of
patella +8.90 mm. That result stands on its own and it is precisely why it must not be
pooled: one merged count would let a real zygomatic arch stand in for an absent clavicle.
probe_pools() therefore labels each set with a `_scope` it infers itself, summarises each
separately, and fat_invariant_report() refuses a head probe set outright.

THREE THINGS THE COUNTS THEMSELVES HAVE TO SAY, OR THEY MISLEAD EVEN WHEN THEY ARE RIGHT
  * A WINDOW THAT WAS NEVER PROBED IS NOT A FLAT READING. EMPTY_WINDOW means no vertex of
    this cage falls inside the window, so no primitive ran. On abel three of the twelve
    head windows — cervicale, external_occipital_protuberance, mastoid_process — are in
    that state, and the shipped prose said "4 of 12 resolve; unresolved: <5 names>" and
    named the other three nowhere. relief_summary()'s sentence names them every time, and
    says "[none]" when there are none, so silence is never ambiguous.
  * PROBE WINDOWS ARE NOT INDEPENDENT AND WERE NEVER CHECKED. MEASURED on abel:
    clavicle_shaft covers 84.5% of sternal_end, olecranon shares 60.6% of its vertices with
    epicondyle_lat, and malleolus_lat and malleolus_med return a bit-identical point-mode
    peak — one bump credited to two landmarks. pool_overlaps() reports the pairwise table,
    the number of separated regions of skin, and the largest pairwise-disjoint subset, so
    "n of 11" is never read as eleven independent observations.
  * A DENOMINATOR MAY NOT SHRINK QUIETLY. AFS p.63 names EIGHT fat-invariant regions and
    three of them — facial mask, nape, spine midline — have no body probe at all.
    AFS_P63_REGIONS carries all eight and names the unprobed three in every report, rather
    than quoting "the 11 fat-invariant probes" as though 11 were the page's list.

WHAT THIS MODULE DOES
  ridge_relief(polyline)   relief sampled at N stations along a curve, each against its own
                           LOCAL, CROSS-CURVE collar, returning the full PROFILE plus
                           continuity, run length and sign-change counts — never a single
                           patch mean.
  facet_flatness(patch)    curvature VARIANCE and a flatter-than-its-surround ordering test,
                           for the dotted-line landmarks where the correct assertion is
                           "this is a plane, not a bump".
  polarity='either'        scores |relief| and reports the sign, so a furrow scores exactly
                           as strongly as a ridge where the reference says either is
                           acceptable (AFS p.171).
  ridge_null()             the same primitive run over RANDOM curves on ordinary skin. This
                           is what a run length has to beat, and it exists as code so the
                           constants below can be re-derived rather than believed. ONE CALL
                           IS ONE DRAW: its run threshold is a 1% tail of a few hundred
                           integers and it moves with the seed.
  ridge_null_sweep()       the same null over a FIXED 24-seed panel, pooling the seed
                           histograms into one experiment. This is what derived the shipped
                           RIDGE_NULL_P99 and what `python -m zyg_workflows.geom.form.ridge sweep` re-runs.

HOW THE ANISOTROPIC COLLAR IS BUILT, AND WHY IT REUSES curvature.py RATHER THAN REPLACING IT
`curvature.region_relief` already takes a precomputed `distances` array and hands it to
`curvature.collar`, which selects the band [gap, gap+width] from it. So the whole
anisotropic construction is a choice of distance FIELD, and every piece of machinery below
it — the mixed Voronoi areas, the cotangent operators behind them, the tilt filter, the
collar PCA frame, the 6-coefficient quadric, the extrapolation-footprint guard — is
curvature.py's, unmodified. For station k of a polyline we pass

    d(x) = geodesic distance from x to THE WHOLE POLYLINE,  masked to +inf outside a band
           of +/- `along_stations` stations of arc around k

so the collar is the pair of flanking bands beside the curve and the curve's own
continuation is at distance ~0 and therefore excluded from it by construction. Nothing else
changes. Set ZYG_RIDGE_ANISOTROPIC_COLLAR=0 and every station reverts to exactly
regions.py's probe — a 0.012-of-stature geodesic ball with the default isotropic collar — so
the before/after in report_table() is the same stations measured two ways, not two
different experiments.

THE ARC-BAND, NOT A GEODESIC BALL, IS WHAT MAKES THE COLLAR EXIST AT ALL. The first version
of this masked the collar with `dist_to_station <= (gap+width)*S`. A vertex 25 mm to the
side of the curve is already 25 mm from the station, so that intersection is an annular
sliver: MEASURED on the clavicle window, 8 of 10 stations refused with "collar never
reached 14 vertices" (11, 9, 8, 3, 4, 4, 4, 5 found). Assigning every vertex to its NEAREST
station and admitting +/-2 stations of arc fixes it — 10 of 10 stations measured — because
the band is now unbounded in the cross direction, which is the direction the collar lives
in.

THRESHOLDS, AND THE ONE RULE THAT GOVERNS THEM
A station may only be called relief if it clears the cage's OWN relief null at p99 —
|relief| >= 2.45e-3 of stature AND |contrast| >= 3.7 (curvature.RELIEF_NULL_P99, measured,
not chosen). This module never lowers that. Where the anisotropic null measured below turns
out to be STRICTER than the published one, the stricter number is used; where it is looser
it is ignored. A CURVE claim needs more: a run of consecutive same-sign qualifying stations
longer than random curves on ordinary skin produce under the identical search. That run
length is the only genuinely new threshold here and it comes from ridge_null(), i.e. from a
false-positive rate on skin that carries no landmark — it can make a claim harder, never
easier. The book's amplitude targets (plan section 2, AFS/HeadNeck page-cited) are carried
in CANON_TARGETS and are REPORT-ONLY: provenance 'CANON' ranks below 'MEASURED' and may not
block-fail anything (plan section 1.3).

WHAT THIS MODULE CANNOT DO. It cannot find a feature the cage has no vertices to carry, and
it says so instead of interpolating one. It does not know what a clavicle is; it takes a
curve and returns a profile. And a polyline authored through the wrong skin returns a
confidently wrong profile, which is why every probe below carries the pool it searched, the
number of candidate curves it tried, and the multiplicity the null was measured at.
"""

import hashlib
import os
import sys

import numpy as np

# One os.path.dirname more than the old single-file ridge.py needed: this file sits one
# directory deeper, and the path inserted must stay the same — the zyg_workflows package dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from zyg_workflows.geom.form import curvature as CV  # noqa: E402
import logging as _zyg_logging

from zyg_workflows.geom.form.ridge.constants import (  # noqa: E402
    _zyg_log,
    _require,
    RIDGE_CORE_FRAC,
    RIDGE_GAP_FRAC,
    RIDGE_WIDTH_FRAC,
    RIDGE_ALONG_STATIONS,
    RIDGE_ALONG_WIDENING,
    RIDGE_N_STATIONS,
    RIDGE_MIN_STATIONS,
    POINT_PROBE_RADIUS_FRAC,
    SEARCH_N_DIRECTIONS,
    SEARCH_N_OFFSETS,
    STATION_MIN_FRAC_STATURE,
    STATION_MIN_CONTRAST,
    RIDGE_NULL_ALPHA,
    RIDGE_NULL_SEED_PANEL,
    RIDGE_NULL_PANEL_N_POOLS,
    RIDGE_NULL_P99,
    VERDICTS,
    RESOLVED_VERDICTS,
    BELOW_NULL_VERDICTS,
    NO_VERDICT_VERDICTS,
    VERDICT_CLASS,
    _VERDICT_MEANING,
    resolves_relief,
    CANON_TARGETS,
    AFS_P63_REGIONS,
    FAT_INVARIANT_PROBES,
    AFS_P63_UNPROBED_ON_BODY,
    AFS_P63_SOURCE,
)
from zyg_workflows.geom.form.ridge.primitive import (  # noqa: E402
    _GRAPH_CACHE,
    _mesh_key,
    build_graph,
    _station_distances,
    _group_distance,
    polyline_arc_length,
    _score_profile,
    _anisotropic_enabled,
    ridge_relief,
)
from zyg_workflows.geom.form.ridge.facet_search import (  # noqa: E402
    facet_flatness,
    _tangent_frame,
    curve_candidates,
    _score,
    ridge_search,
)
from zyg_workflows.geom.form.ridge.null import (  # noqa: E402
    _SHELL_CACHE,
    shell_mask,
    _skin_mask,
    _pool_of_size,
    _hist,
    merge_hists,
    _discrete_min_run,
    exceedance,
    ridge_null,
    ridge_null_sweep,
    facet_percentile,
    station_cut,
)
from zyg_workflows.geom.form.ridge.probes import (  # noqa: E402
    window_mask,
    _empty_window_evidence,
    HEAD_PROBES,
    BODY_POOL_BALL_FRAC,
    body_pools,
    head_pools,
    _resolution_contract,
    _max_disjoint,
    pool_overlaps,
    _shared_peak_vertices,
)
from zyg_workflows.geom.form.ridge.summary import (  # noqa: E402
    probe_pools,
    _infer_scope,
    _classify_probe,
    relief_summary,
    fat_invariant_report,
)
from zyg_workflows.geom.form.ridge.selftest import (  # noqa: E402
    _ridge_grid,
    self_test,
)
from zyg_workflows.geom.form.ridge.report import (  # noqa: E402
    _fmt_res,
    report_table,
    _n,
    _pct,
    main,
)

__all__ = [
    'ridge_relief',
    'facet_flatness',
    'ridge_null',
    'ridge_null_sweep',
    'merge_hists',
    'exceedance',
    'facet_percentile',
    'station_cut',
    'curve_candidates',
    'ridge_search',
    'build_graph',
    'polyline_arc_length',
    'window_mask',
    'shell_mask',
    'body_pools',
    'head_pools',
    'probe_pools',
    'report_table',
    'self_test',
    'resolves_relief',
    'relief_summary',
    'fat_invariant_report',
    'pool_overlaps',
    'RIDGE_CORE_FRAC',
    'RIDGE_GAP_FRAC',
    'RIDGE_WIDTH_FRAC',
    'RIDGE_ALONG_STATIONS',
    'RIDGE_N_STATIONS',
    'RIDGE_MIN_STATIONS',
    'SEARCH_N_DIRECTIONS',
    'SEARCH_N_OFFSETS',
    'STATION_MIN_FRAC_STATURE',
    'STATION_MIN_CONTRAST',
    'RIDGE_NULL_P99',
    'VERDICTS',
    'RIDGE_NULL_ALPHA',
    'RIDGE_NULL_SEED_PANEL',
    'RIDGE_NULL_PANEL_N_POOLS',
    'RESOLVED_VERDICTS',
    'BELOW_NULL_VERDICTS',
    'NO_VERDICT_VERDICTS',
    'VERDICT_CLASS',
    'POINT_PROBE_RADIUS_FRAC',
    'HEAD_PROBES',
    'CANON_TARGETS',
    'BODY_POOL_BALL_FRAC',
    'AFS_P63_REGIONS',
    'FAT_INVARIANT_PROBES',
    'AFS_P63_UNPROBED_ON_BODY',
    'AFS_P63_SOURCE',
    # the original top import block and the section modules' own names, re-exported
    # so `ridge.<name>` resolves exactly as it did before the split
    'hashlib',
    'np',
    'CV',
    '_zyg_logging',
    '_zyg_log',
    '_require',
    'RIDGE_ALONG_WIDENING',
    '_VERDICT_MEANING',
    '_GRAPH_CACHE',
    '_mesh_key',
    '_station_distances',
    '_group_distance',
    '_score_profile',
    '_anisotropic_enabled',
    '_tangent_frame',
    '_score',
    '_SHELL_CACHE',
    '_skin_mask',
    '_pool_of_size',
    '_hist',
    '_discrete_min_run',
    '_empty_window_evidence',
    '_resolution_contract',
    '_max_disjoint',
    '_shared_peak_vertices',
    '_infer_scope',
    '_classify_probe',
    '_ridge_grid',
    '_fmt_res',
    '_n',
    '_pct',
    'main',
]
