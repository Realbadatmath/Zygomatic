# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Provenance vocabulary, survey coverage, the MEASURED evidence contract and the status words.

Moved verbatim out of the old single-file gates.py (lines 160-750).
"""

import re
from zyg_workflows.geom.anthro.reference import reference
import logging as _zyg_logging


_zyg_log = _zyg_logging.getLogger(__name__)


SCHEMA = 'geom.anthro.gates/1'

# ---------------------------------------------------------------------------------
# Provenance vocabulary. The engine refuses to run on anything that is not one of the
# first three, which is how a contested constant is kept out of the registry by machinery
# rather than by reviewer attention.
# ---------------------------------------------------------------------------------
MEASURED = 'MEASURED'
CANON = 'CANON'
HOUSE = 'HOUSE'
CONTESTED = 'CONTESTED'
VALID_PROVENANCE = (MEASURED, CANON, HOUSE)

# CANON ranks BELOW MEASURED and the ranking is arithmetic, not a comment: see
# validate_registry(), which refuses `block` severity to a CANON threshold on any quantity
# a survey on disk already answers.
PROVENANCE_RANK = {MEASURED: 0, CANON: 1, HOUSE: 2}

CANON_DEFINITION = (
    'CANON = a number PRINTED IN AN ARTIST/ANATOMY REFERENCE. It is a drawing convention '
    'or a clinical rule of thumb, not a survey statistic: it has no sample, no n, no '
    'sampling frame and no dispersion. It ranks BELOW MEASURED and may set a threshold '
    'ONLY where ANSUR II / CDC / NHANES is silent — which is the angle, sign, curvature, '
    'relief and joint-range material, and NOT the height ratios.'
)

# THE CONFLICT THAT FORCED THE TIER. Recorded here rather than in a commit message because
# it is the evidence for the policy and it must stay next to the policy.
CANON_VS_MEASURED_CONFLICT = (
    'Anatomy For Sculptors p.91-93 (head-unit charts) is CANON and it is measurably wrong '
    "at our characters' ages, in two independent ways. (1) AFS p.91 puts ages 8-12 at "
    '6.0 head units. CDC 50th-percentile stature for a 12-year-old boy is ~149 cm and '
    'head height is ~21.5-22 cm, giving ~6.9 head units; this pipeline measures a total '
    'head count of 7.06-7.13 on a 12-year-old AND on three adults (spread 0.07), so AFS '
    'under-counts a child by nearly a whole head and asserts an age trend the meshes do '
    'not show. (2) AFS p.91-92 makes crotch height migrate DOWNWARD with age (children '
    'drawn with relatively SHORTER legs). The NHANES III cormic data already on this disk '
    'says the opposite: our 12-year-old measures cormic 0.5057 against the adult 0.5218, '
    'i.e. subischial length 49.4%% vs 47.8%% — relatively LONGER legs, the well-documented '
    'pre-pubertal leg-length peak that a smooth baby-to-adult artist interpolation misses. '
    'Both quantities are covered by MEASURED sources on disk, so under this policy AFS may '
    'REPORT them and may not gate them at any severity above report.'
)

# Tier 5 was added 2026-08-06: the form/angle/section/relief/pose gates. It is a separate
# tier and not an extension of tier 4 because its evidence class is different — tiers 1-4
# judge a body against survey microdata and our own policy, tier 5 judges it against
# printed anatomy references and parameter-free sign/invariance tests.
TIERS = (1, 2, 3, 4, 5)

# ---------------------------------------------------------------------------------
# WHICH QUANTITIES A SURVEY ON DISK ALREADY ANSWERS.
#
# This is the list the CANON refusal is computed against. It is a STATIC SNAPSHOT so that
# building the registry never requires the reference pack to be loadable (the same rule
# _bands() already follows), and it is CROSS-CHECKED against the live pack at run time by
# t4_threshold_provenance, which FAILS if the pack has grown a quantity this snapshot
# missed AND a CANON gate is gating it. Union, never intersection: if either the snapshot
# or the live pack says a quantity is surveyed, it is surveyed.
#
# Source of the 49 ratio names: geom/anthro/reference.py -> AnthroReference.ratios(), read
# from data/assets/anthro_reference on 2026-08-06 (ANSUR II 2012 public working databases,
# male n=4082, female n=1986). The three non-ratio entries are the other two surveys this
# package ships numbers from.
# ---------------------------------------------------------------------------------
MEASURED_COVERED_QUANTITIES = frozenset(
    (
        # -- ANSUR II ratio pack (49) --------------------------------------------------
        'abdominal_extension_depth_sitting_over_stature',
        'acromial_height_over_stature',
        'acromion_radiale_length_over_stature',
        'biacromial_breadth_over_stature',
        'biceps_circumference_flexed_over_stature',
        'bicristal_breadth_over_stature',
        'bideltoid_breadth_over_stature',
        'bideltoid_over_hipbreadth',
        'bmi',
        'buttock_circumference_over_stature',
        'buttock_depth_over_stature',
        'buttock_height_over_stature',
        'calf_circumference_over_stature',
        'cephalic_index',
        'cervicale_height_over_stature',
        'chest_breadth_over_stature',
        'chest_circumference_over_stature',
        'chest_depth_over_stature',
        'crotch_height_over_stature',
        'foot_length_over_stature',
        'foot_over_hand_length',
        'hand_length_over_stature',
        'head_breadth_over_stature',
        'head_circumference_over_stature',
        'head_length_over_stature',
        'hip_breadth_over_stature',
        'iliocristale_height_over_stature',
        'knee_height_midpatella_over_stature',
        'lateral_malleolus_height_over_stature',
        'neck_circumference_over_stature',
        'radiale_stylion_length_over_stature',
        'shoulder_circumference_over_stature',
        'shoulder_hip_skeletal',
        'shoulder_waist_circumference',
        'sitting_height_over_stature',
        'span_over_stature',
        'suprasternale_height_over_stature',
        'tenthrib_height_over_stature',
        'thigh_circumference_over_stature',
        'tibiale_height_over_stature',
        'trochanterion_height_over_stature',
        'upperarm_over_forearm',
        'waist_breadth_over_stature',
        'waist_circumference_omphalion_over_stature',
        'waist_height_omphalion_over_stature',
        'waist_hip_circumference',
        'waist_over_stature',
        'wrist_circumference_over_stature',
        'wrist_height_over_stature',
        # -- CDC 2000 LMS growth references, shipped in the pack as doc['cdc_lms'] --------
        'stature_for_age',
        'bmi_for_age',
        # -- NHANES III, shipped in this file as CHILD_CORMIC -----------------------------
        'cormic_index',
    )
)
MEASURED_COVERAGE_SOURCE = (
    'ANSUR II 2012 public working databases (male n=4082, female n=1986) as built into '
    'data/assets/anthro_reference; CDC 2000 LMS stature-for-age and BMI-for-age from the '
    'same pack; NHANES III cormic index as shipped in gates.CHILD_CORMIC. Snapshot taken '
    '2026-08-06 and cross-checked against the live pack on every run by '
    't4_threshold_provenance.'
)
# Named because the head-count charts are the case that forced the tier and a reader will
# look for it: head HEIGHT (vertex-to-menton) is NOT an ANSUR column, so head count is the
# one AFS quantity no survey on disk answers directly. It is still not gateable from AFS,
# because the CANON number is contradicted by a MEASURED derivation (CDC stature-for-age
# plus a head height) — see CANON_VS_MEASURED_CONFLICT and t5_canon_head_units, which is
# registered at 'report' and says so in its own record rather than in this comment.
MEASURED_NOT_COVERED_NOTE = (
    'head_height_vertex_menton is measured by this pipeline but by none of the three '
    'surveys on disk, so head COUNT is outside MEASURED_COVERED_QUANTITIES. That does not '
    'make the AFS chart gateable: its two derived claims (crotch height and the age trend) '
    'ARE covered, and the chart disagrees with both.'
)


def measured_covered(live=True):
    """(covered set, provenance note). Never raises: a pack that will not load degrades to
    the static snapshot AND SAYS SO, because a silent shrink of this set would silently
    hand a CANON threshold a blocking claim it is not entitled to."""
    covered = set(MEASURED_COVERED_QUANTITIES)
    how = 'static snapshot only'
    if live:
        try:
            ref = reference()
            live_keys = set(ref.ratios())
            # Only the DATA SERIES in cdc_lms are quantities; the block also carries scalar
            # metadata ('formula', 'coverage_agemos') which are not things a gate could
            # ever be about, and admitting them would put noise in the refusal list.
            live_keys |= {k for k, v in (ref.doc.get('cdc_lms') or {}).items() if isinstance(v, (dict, list))}
            missing = sorted(live_keys - covered)
            covered |= live_keys
            how = 'static snapshot UNION the live pack (%d live keys, %d of them absent from the snapshot: %s)' % (
                len(live_keys),
                len(missing),
                ', '.join(missing) or 'none',
            )
        except Exception as e:  # noqa: BLE001
            how = 'static snapshot only — the live pack could not be read (%s: %s), so the cross-check did not run' % (
                type(e).__name__,
                e,
            )
    return covered, how


# ---------------------------------------------------------------------------------
# WHAT A "MEASURED" TAG HAS TO PRODUCE.
#
# THE DEFECT THIS CLOSES (adversarial review, calibration finding 4). The CANON refusal
# above is the strongest rule in this file — a book may not gate a quantity a survey
# answers — and it was bypassable BY TYPING A DIFFERENT WORD. Measured, 2026-08-06:
#
#   CANON    block over crotch_height_over_stature, source 'AFS p.91-92'  -> REFUSED
#   MEASURED block over crotch_height_over_stature, source 'AFS p.91-92'  -> ACCEPTED
#
# Nothing validated the string. The provenance field was a self-assessment, and the wave
# shipped a live instance of it: t5_digit_chains was tagged MEASURED at block severity
# while its only citation was two pages of an art-anatomy book — i.e. CANON evidence
# wearing the MEASURED word, which is precisely what the CANON rule exists to stop.
#
# The tag is now validated against the EVIDENCE, in two places and in two different ways:
#
#   STATICALLY, in validate_registry(), before any mesh loads: a MEASURED threshold must
#   carry a structured `evidence` record naming one of the classes below, with the fields
#   that class requires and a positive integer n. And neither the evidence citation nor
#   the gate's own source line may be a BOOK PAGE: a page reference is the definition of
#   CANON (see CANON_DEFINITION), so a gate whose citation is a page has declared its own
#   provenance and the registry refuses the MEASURED tag outright.
#
#   LIVE, in t4_threshold_provenance(), on every run: a `reference_pack` evidence record
#   names a source key that must RESOLVE in the pack's own provenance document on disk
#   (data/assets/anthro_reference -> prov_doc['sources']). A named source that is not
#   there is a FAIL, not a shrug — and a pack that cannot be read at all makes the census
#   UNMEASURABLE, never a pass.
#
# The one class that is NOT pack-backed is not banned — a published radiographic series is
# real evidence and ANSUR ships no phalanx lengths — but it is CENSUSED as externally
# sourced in every report, so "MEASURED" never again means "somebody said so".
#
#   AND THE PACK MUST ANSWER THE GATE, not merely contain the key the gate typed. Added
#   2026-08-06 (re-review R2, hole b): the live check used to resolve `pack_source` against
#   prov_doc['sources'] and stop there, so a gate blocking `gonial_angle_deg` — for which
#   ANSUR ships no column at all — was reported as "resolved against the pack on disk".
#   Whichever quantities the gate names (its own `quantities`, else the ratio keys in its
#   calibration block) must intersect measured_covered(); a gate that names quantities the
#   pack does not answer is REFUSED at block severity and censused as unbacked otherwise,
#   and a gate that names none is censused as COVERAGE NOT VERIFIED rather than resolved.
# ---------------------------------------------------------------------------------
MEASURED_EVIDENCE_CLASSES = {
    'reference_pack': {
        'what': 'a survey built into data/assets/anthro_reference. The record names the '
        'pack source key and that key is resolved against the pack on disk on '
        'every run.',
        'requires': ('pack_source', 'n', 'population'),
        'pack_backed': True,
    },
    'published_series': {
        'what': 'a published measurement series that is NOT in the pack. Not verifiable '
        'from this disk, so the record must name authors, year and n, and every '
        'run censuses the gate as externally sourced.',
        'requires': ('citation', 'n', 'population'),
        'pack_backed': False,
    },
}

# WITHDRAWN 2026-08-06 (re-review R5): the class 'own_assets'.
#
# It was added by the previous remediation wave, and it was added for exactly one gate:
# t1_topology_identity, whose "measurement" is the vertex count of our own cage. Its own
# population string read "Not a population of people: a census of our own output" — i.e.
# the class documented, in its own words, that it was not the thing MEASURED means. That
# is the reviewers' pattern (a) in its purest form: the ENFORCED definition of MEASURED
# was widened until the DECLARED one no longer described it, and it was widened while
# fixing a defect of the same shape.
#
# The refusal three hundred lines below already said what to do, in these words: "tag the
# gate CANON if the number came off a page and HOUSE if it is ours." 13718 is ours. It is
# now HOUSE, the class is gone, and there is no defence of the class other than "this gate
# needed to pass", which is not one. Consequences, measured: the MEASURED census drops
# 13 -> 12, which is the survey-backed count, and PROVENANCE_RANK stops ranking a fact
# about our repository above every CANON page in the file.
WITHDRAWN_EVIDENCE_CLASSES = {
    'own_assets': 'WITHDRAWN 2026-08-06. A census of our own output is a HOUSE fact, not '
    'a survey. See t1_topology_identity, which is now tagged HOUSE.',
}

# The reference books this package quotes. A NUMBER OUT OF ONE OF THEM IS CANON BY
# DEFINITION — the book has no sample, no n and no sampling frame, whatever page it is on
# and whether or not a page is named at all — so naming one of them as the provenance of a
# MEASURED threshold is the refusal's trigger.
#
# WIDENED 2026-08-06 (re-review R2, hole a) FROM A PAGE TEST TO A BOOK TEST. The previous
# rule matched only a literal page marker beside the book name:
#
#     _PAGE_RE = re.compile(r'\b(?:p{1,2}\.\s*|pages?\s+)\d')
#
# so it tested THE SPELLING OF THE CITATION and not the evidence. Every one of the nine
# adversarial cases the previous wave certified against happened to contain "p."; deleting
# those two characters restored the whole bypass. Measured against the shipped code:
#
#   MEASURED block, source 'MEASURED - AFS p.91-92'                          -> REFUSED
#   MEASURED block, source 'the Anatomy For Sculptors head-unit chart, ...'  -> ACCEPTED
#   MEASURED block, source 'AFS chapter 4, the crotch chart'                 -> ACCEPTED
#   MEASURED block, source 'Anatomy For Sculptors, fig. 12'                  -> ACCEPTED
#
# The rule is now: a MEASURED gate may not name a canon book in its source line or in its
# evidence record AT ALL. This costs the prose case the old comment protected ("the AFS
# chart disagrees" in a MEASURED source line is now a refusal) and that cost is accepted:
# a MEASURED source line has one job, which is to name the survey, and a gate that wants
# to argue with a book can do it in its registry note, in its title, or in the calibration
# block's `why` — none of which are read as the provenance of the number.
#
# THIS IS STILL A STRING TEST AND STRING TESTS ARE LOSABLE. It is the second of two
# defences and deliberately not the load-bearing one: the load-bearing defence is that the
# evidence record must RESOLVE — a pack source that exists on disk and that answers the
# quantities the gate names (verify_measured_evidence + the coverage rule in
# validate_registry). A citation nobody can check is refused by that rule no matter how it
# is spelled.
CANON_BOOKS = (
    'Anatomy For Sculptors',
    'AFS',
    'Form of the Head and Neck',
    'HeadNeck',
    'FacialExpr',
    'Facial Expressions',
)
_PAGE_RE = re.compile(r'\b(?:p{1,2}\.\s*|pages?\s+)\d', re.I)


def canon_book_citations(text):
    """Every (book, quoted fragment, page_marker) in `text` that CITES a canon book.

    Non-empty means the text attributes its number to a printed art/anatomy reference,
    which is CANON and not MEASURED. `page_marker` records whether a page number happened
    to be printed beside the book name; it is reported, never required.
    """
    hits = []
    s = str(text or '')
    for book in CANON_BOOKS:
        for m in re.finditer(re.escape(book), s, re.I):
            tail = s[m.end() : m.end() + 40]
            hits.append((book, (s[m.start() : m.end() + 20]).strip(), bool(_PAGE_RE.search(tail))))
    return hits


def canon_book_pages(text):
    """Back-compatible view of canon_book_citations(): PAGE citations only.

    Kept because it names a real and narrower fact — "this text cites a page" — which the
    reports still print. It is NOT the refusal rule any more; see canon_book_citations.
    """
    return [(b, frag) for b, frag, paged in canon_book_citations(text) if paged]


def declared_quantities(gate):
    """(quantities, how) — what this gate says it is about, for the coverage rule.

    A gate's own `quantities` tuple is the declaration; where it declares none, the ratio
    keys in its calibration block are a machine-readable statement of the same fact and are
    used instead. `quantities` is None when neither exists, which is NOT treated as "no
    clash": it is treated as UNVERIFIABLE and said so, because "the gate would not say what
    it measures" must never read as "the pack answers it".
    """
    qs = gate.quantities
    if qs is not None:
        return tuple(qs), "the gate's own `quantities` declaration"
    cal = gate.calibration or {}
    # Two calibration blocks state the same fact in machine-readable form and are read
    # here rather than made to repeat themselves: `ratios` (a ratio-band gate names the
    # pack ratios it bands) and `components` (an empirical-percentile gate names the pack
    # ratios its distance is computed over). Prose in a `source` string is NOT read: a
    # sentence naming ANSUR is what the whole MEASURED rule exists to stop counting.
    for key, what in (
        ('ratios', "the ratio keys in the gate's calibration block"),
        ('components', "the component ratio keys in the gate's calibration block"),
    ):
        v = cal.get(key)
        if isinstance(v, (list, tuple)) and v and all(isinstance(x, str) for x in v):
            return tuple(v), '%s (it declares no `quantities`)' % what
    return None, (
        'the gate declares neither `quantities` nor calibration ratios or '
        'components, so what it is about cannot be read off the registry'
    )


def verify_measured_evidence(gate, live=True):
    """(ok, record). The LIVE half of the MEASURED rule; never raises.

    `ok` is None — not False — when the check could not be run at all, which is the state
    rule 4 exists for: an unresolvable check is reported as unresolved with its evidence,
    and t4_threshold_provenance turns it into UNMEASURABLE rather than into a pass.
    """
    ev = dict(gate.evidence or {})
    cls = ev.get('class')
    spec = MEASURED_EVIDENCE_CLASSES.get(cls) or {}
    qs, how_q = declared_quantities(gate)
    rec = {
        'gate': gate.id,
        'class': cls,
        'pack_backed': bool(spec.get('pack_backed')),
        'n': ev.get('n'),
        'population': ev.get('population'),
        'pack_source': ev.get('pack_source'),
        'citation': ev.get('citation'),
        'severity_declared': gate.severity,
        'quantities_declared': list(qs) if qs is not None else None,
        'quantities_read_from': how_q,
    }
    if not spec.get('pack_backed'):
        rec['verified'] = True
        rec['how'] = (
            'class %r is not pack-backed: %s This gate is censused as '
            'externally sourced and its citation is not resolvable from this '
            'disk.' % (cls, spec.get('what', ''))
        )
        return True, rec
    if not live:
        rec['verified'] = None
        rec['how'] = 'live check not requested'
        return None, rec
    try:
        sources = (reference().prov_doc or {}).get('sources') or {}
    except Exception as e:  # noqa: BLE001
        rec['verified'] = None
        rec['unresolved_because'] = 'pack_unreadable'
        rec['how'] = (
            'the reference pack could not be read (%s: %s), so the named source '
            '%r could NOT be resolved. This is unresolved, not verified.' % (type(e).__name__, e, ev.get('pack_source'))
        )
        return None, rec
    key = ev.get('pack_source')
    src = sources.get(key)
    if src is None:
        rec['verified'] = False
        rec['how'] = (
            'the pack on disk has no source %r. It ships: %s. A MEASURED tag '
            'naming a survey the pack does not contain is not evidence.'
            % (key, ', '.join(sorted(sources)) or 'nothing')
        )
        return False, rec
    rec['pack_source_n'] = src.get('n')
    rec['pack_source_population'] = str(src.get('population') or '')[:160]
    resolved = 'the source key resolves against data/assets/anthro_reference prov_doc["sources"][%r] (pack n=%s)' % (
        key,
        src.get('n'),
    )

    # -- DOES THE PACK ANSWER THIS GATE? (R2, hole b) ------------------------------
    # Resolving the KEY is not the same claim as "the survey answers the question this
    # gate thresholds", and until 2026-08-06 only the first was checked while the second
    # was what got printed. A gate blocking `gonial_angle_deg` with an ANSUR evidence
    # record read "resolved against the pack on disk"; ANSUR II has no gonial column.
    covered, how_cov = measured_covered()
    rec['pack_answers'] = None
    rec['coverage_how'] = how_cov
    if qs is None:
        rec['verified'] = None
        rec['coverage_verified'] = False
        rec['unresolved_because'] = 'coverage_not_verifiable'
        rec['how'] = (
            '%s, but %s, so whether the pack ANSWERS what this gate thresholds '
            'is NOT VERIFIED. A resolved key is evidence that the survey exists, '
            'not that it speaks to this quantity. To resolve it, give the gate a '
            '`quantities` tuple naming what it thresholds.' % (resolved, how_q)
        )
        return None, rec
    answered = sorted(q for q in qs if q in covered)
    unanswered = sorted(q for q in qs if q not in covered)
    rec['pack_answers'] = answered
    rec['pack_does_not_answer'] = unanswered
    if not answered:
        rec['verified'] = False
        rec['coverage_verified'] = False
        rec['how'] = (
            '%s — but the pack answers NONE of the quantities this gate names '
            '(%s; read from %s). Naming a survey that does not measure the '
            'quantity is not evidence about it. %s'
            % (resolved, ', '.join(qs) or 'none', how_q, MEASURED_NOT_COVERED_NOTE)
        )
        return False, rec
    rec['verified'] = True
    rec['coverage_verified'] = True
    rec['how'] = '%s and it answers %d of the %d quantit(y/ies) this gate names: %s%s' % (
        resolved,
        len(answered),
        len(qs),
        ', '.join(answered),
        '' if not unanswered else ' (NOT answered by the pack: %s)' % ', '.join(unanswered),
    )
    return True, rec


# The evidence records this registry actually uses. Written once so that a gate
# cannot quietly acquire a different population than the one its neighbours cite.
EV_ANSUR_II = {
    'class': 'reference_pack',
    'pack_source': 'ansur_ii_2012',
    'n': 6068,
    'population': 'ANSUR II 2012 public working databases — US Army personnel (Active '
    'Duty, National Guard and Reserve), ages 17-58; male n=4082, female '
    'n=1986. EXPLICITLY NOT a civilian sample.',
}
# EV_OWN_ISSUED_MESHES is GONE (re-review R5). It carried class 'own_assets', the class
# withdrawn above, and its only user was t1_topology_identity, which is now HOUSE. It is
# not replaced by a HOUSE-flavoured evidence record: HOUSE does not need one, because
# HOUSE claims nothing about a population and therefore has no population to produce.
EV_PHALANX_SERIES = {
    'class': 'published_series',
    'n': 263,
    'citation': 'Buryanov, A. & Kotiuk, V., 2010, "Proportions of Hand Segments", '
    'Int. J. Morphol. 28(3):755-758 (n=66); Hamilton, R. & Dunsmuir, R.A., '
    '2002, "Radiographic assessment of the relative lengths of the bones of '
    'the fingers of the human hand", J. Hand Surg. Br. 27(6):546-548 (n=197).',
    'population': 'adult hand radiograph series, two independent studies. ANSUR II ships '
    'no phalanx lengths at all, so the pack cannot answer this and the '
    'evidence is deliberately external and censused as such.',
}


SEVERITIES = ('block', 'warn', 'report')

# statuses a gate callable may return
PASS = 'pass'  # noqa: S105  gate status constant, not a secret
WARN = 'warn'
FAIL = 'fail'
REPORT = 'report'
UNMEASURABLE = 'unmeasurable'
NOT_APPLICABLE = 'not_applicable'
NOT_IMPLEMENTABLE = 'not_implementable'
MISSING = 'missing'
ERROR = 'error'
# ---------------------------------------------------------------------------------
# "THE CHECK DID NOT COMPLETE" AND "THE FINDING WAS REFUSED" ARE NOT THE SAME EVENT (W4-1)
# ---------------------------------------------------------------------------------
# ERROR — the check did not complete. Either the gate callable RAISED, or the gate's own
# machinery failed to produce a usable result (its form module would not import, returned
# no record, or returned a status this file has no mapping for). There is no finding.
#
# POLICY_ERROR — the gate RAN, reached its subject, and PRODUCED A FINDING; the ENGINE
# then refused that finding on a policy ground that is about the ROW rather than about the
# anatomy. Today there is exactly one such ground: check_module_provenance found a
# module-emitted provenance tag that outranks the registry's adjudicated tag, or that the
# registry would refuse for this gate. The measurement happened. What is wrong is the
# row's claim about where its number came from.
#
# WHY A SEPARATE TOKEN AND NOT A FLAG ON ERROR. Wave 4 emitted plain ERROR for the policy
# case, so every consumer that had been told "error means the gate crashed" became correct
# in code and false in fact: report.py printed "GATES THAT CRASHED (checked nothing):
# t5_patellar_ligament, t5_subcostal_angle" on all five bodies — while t5_patellar_ligament
# was at that moment carrying a live blocking anatomical finding (patella-to-tuberosity
# distance drifting -15.54% at 120 deg: the ligament is not modelled). A real defect had
# been refiled as an infrastructure crash, and the correction was a sentence buried inside
# the row rather than a fact a counter could read. Two events that need different sentences
# need different tokens.
#
# WHAT IT IS NOT. It is not a softer status. Both members of ERROR_CLASS_STATUSES are
# blocking on a block-severity gate, both are excluded from the measured-rejection
# calibration by _effective_severity, and neither can roll up better than a FAIL. A module
# claiming stronger evidence than the adjudicated tag is a real defect; naming it precisely
# is about being able to describe it, not about forgiving it.
POLICY_ERROR = 'policy_error'
STATUSES = (PASS, WARN, FAIL, REPORT, UNMEASURABLE, NOT_APPLICABLE, NOT_IMPLEMENTABLE, MISSING, ERROR, POLICY_ERROR)

# The error-class statuses. Exported rather than re-listed downstream: a renderer that
# keeps its own copy of "which statuses are error-class" is one edit away from rendering a
# status it has never heard of as a pass.
ERROR_CLASS_STATUSES = (ERROR, POLICY_ERROR)

# THE `crashed` CONTRACT, PRODUCER SIDE. Every row run_gates emits carries an explicit
# boolean `crashed`, and it is True on one condition only: THE GATE CALLABLE RAISED AND
# run_gates CAUGHT IT. It is never inferred from the status — not here and, by the shared
# W4-1 contract, not in report.py either, which READS this flag instead of re-deriving it.
# A status is not evidence about whether a callable raised: a gate can return ERROR after
# checking its subject perfectly well (its module returned no record), and a gate can be
# refused on provenance after producing a complete finding. Only the except branch knows.
CRASHED_KEY = 'crashed'
CRASHED_CONTRACT = (
    'row[%r] is set by the ENGINE, and is True if and only if the gate callable raised and '
    'run_gates caught it. It is never derived from the status. A gate that ran, checked its '
    'subject and produced a finding is %r=False even when its status is error-class — which '
    'is the whole of W4-1: t5_patellar_ligament produces a blocking anatomical finding and '
    'is then refused on provenance, and calling that "crashed (checked nothing)" is a '
    'falsehood about the most-read line of the report.' % (CRASHED_KEY, CRASHED_KEY)
)

# ---------------------------------------------------------------------------------
# Population coverage. Nothing ANSUR-derived is allowed to fire outside this window.
# ---------------------------------------------------------------------------------
ANSUR_AGE_MIN_Y = 17.0
ANSUR_AGE_MAX_Y = 58.0
ANSUR_COVERAGE_NOTE = (
    'ANSUR II covers ages %g-%g. The pack states plainly that NO ratio band in it applies '
    'to a child. The observed value and the adult band are still reported so the size of '
    'the mismatch is visible, but the gate does not fire.' % (ANSUR_AGE_MIN_Y, ANSUR_AGE_MAX_Y)
)

# ---------------------------------------------------------------------------------
# Tier-1 numeric policy
# ---------------------------------------------------------------------------------
# HOUSE. A build-target check, NOT an anthropometric-accuracy claim: it asks whether the
# height solver hit the number the recipe asked for. Real stature varies 14.4-19.3 mm over
# a single day, so +/-2 mm is meaningful ONLY against a declared build target.
BUILD_TARGET_STATURE_TOL_MM = 2.0

# HOUSE, task-specified. Morph coefficients are the +/-1 local-change target weights; the
# rule does not apply to the 0..1 macro sliders, where 0 and 1 are both legitimate
# endpoints in daily use (gender=0.0 is male, gender=1.0 is female).
MORPH_COEFF_ABS_MAX = 0.8

# HOUSE. Below this, a per-mesh stature tolerance presented as an ANTHROPOMETRIC accuracy
# claim is meaningless: a real person's own stature moves 14.4-19.3 mm between morning and
# night, so a 4 mm per-mesh claim is smaller than the subject's own diurnal noise.
DIURNAL_STATURE_RANGE_MM = (14.4, 19.3)
MIN_ANTHROPOMETRIC_STATURE_TOL_MM = 15.0

# HOUSE multiplier on a MEASURED residual. reference.predictability() ships
# stature_anchored_halfwidth_mm = 2 * rmse for exactly this use; the 2 is ours.
STATURE_ANCHOR_SIGMA = 2.0
