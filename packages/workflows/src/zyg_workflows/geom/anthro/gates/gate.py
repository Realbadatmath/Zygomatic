# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The declarative gate record, registry validation and the module-provenance check.

Moved verbatim out of the old single-file gates.py (lines 1305-2007).
"""

from zyg_workflows.geom.anthro.gates.policy import (
    CANON,
    CANON_DEFINITION,
    CANON_VS_MEASURED_CONFLICT,
    CONTESTED,
    HOUSE,
    MEASURED,
    MEASURED_COVERAGE_SOURCE,
    MEASURED_EVIDENCE_CLASSES,
    MEASURED_NOT_COVERED_NOTE,
    PROVENANCE_RANK,
    SEVERITIES,
    STATUSES,
    TIERS,
    VALID_PROVENANCE,
    canon_book_citations,
    declared_quantities,
    measured_covered,
)
from zyg_workflows.geom.anthro.gates.bands import (
    CALIBRATION_KINDS,
    CAL_DECLARED_BAND,
    CAL_STRUCTURAL,
    CAL_UNDECLARED,
    GateConfigError,
)


# ---------------------------------------------------------------------------------
# Declarative gate record
# ---------------------------------------------------------------------------------
class Gate(object):
    """One gate. `threshold` is whatever the check compares against; if it is not None,
    `provenance` must be MEASURED or HOUSE and `source` must be non-empty.

    `severity` is the DECLARED severity — what the registry asks for. What actually governs
    the verdict is the EFFECTIVE severity, resolved at run time by the calibration in
    `calibration`; see rule 6 in the module docstring. A gate that declares no calibration
    is not treated as harmless: it may warn but it may never block, because a gate that
    cannot state what fraction of real people it rejects has not earned a blocking claim.
    """

    __slots__ = (
        'id',
        'tier',
        'severity',
        'title',
        'threshold',
        'provenance',
        'source',
        'fn',
        'calibration',
        'quantities',
        'evidence',
    )

    def __init__(
        self,
        id,
        tier,
        severity,
        title,
        threshold,
        provenance,
        source,
        fn,
        calibration=None,
        quantities=None,
        evidence=None,
    ):
        self.id = id
        self.tier = tier
        self.severity = severity
        self.title = title
        self.threshold = threshold
        self.provenance = provenance
        self.source = source
        self.fn = fn
        self.calibration = dict(calibration) if calibration else {'kind': CAL_UNDECLARED}
        # WHAT the threshold is a threshold ON. Required of every CANON gate, because the
        # CANON refusal is "may not block a quantity a survey already answers" and that
        # sentence is unenforceable if the gate never names its quantity. Optional
        # elsewhere: a MEASURED or HOUSE threshold is not subject to the rule.
        self.quantities = tuple(quantities) if quantities is not None else None
        # WHAT MAKES A "MEASURED" TAG TRUE. Required of every MEASURED gate; see
        # MEASURED_EVIDENCE_CLASSES for the reason and validate_registry for the refusal.
        self.evidence = dict(evidence) if evidence else None

    def as_dict(self):
        return {
            'id': self.id,
            'tier': self.tier,
            'severity': self.severity,
            'severity_declared': self.severity,
            'title': self.title,
            'threshold': self.threshold,
            'threshold_provenance': self.provenance,
            'threshold_source': self.source,
            'threshold_quantities': (list(self.quantities) if self.quantities is not None else None),
            # Which of this gate's quantities a survey on disk ALREADY answers. Emitted
            # on every row so a reader of the artefact — and report.py's own alarm —
            # can apply the CANON rule without re-deriving the coverage list or
            # trusting another gate's payload. Empty list = a CANON threshold that
            # occupies genuinely silent ground, which is where a book is allowed to set
            # one.
            'threshold_measured_conflict': self.measured_conflict(),
            # The structured evidence behind a MEASURED tag, on the row, so a reader
            # of the artefact can apply the rule without trusting the word.
            'threshold_evidence': (dict(self.evidence) if self.evidence else None),
            'calibration_spec': dict(self.calibration),
        }

    def measured_conflict(self):
        if not self.quantities:
            return []
        covered, _how = measured_covered()
        return sorted(q for q in self.quantities if q in covered)

    def __repr__(self):
        return '<Gate %s tier=%d %s>' % (self.id, self.tier, self.severity)


# THE RECEIPT FLAG (re-review N3).
#
# geom.anthro.report.render_gate_table prints a row's explanation and evidence only when
# the row is NOT a clean pass (or sits off its declared band). That rule is right for a
# gate whose finding IS its verdict — nobody needs the arithmetic behind a pass — and it
# is exactly wrong for a gate whose finding IS THE NUMBERS. Two of this wave's own headline
# receipts were therefore reachable only by opening the JSON:
#
#   t4_threshold_provenance   the provenance census ("13 MEASURED gate(s): 11 resolved
#                             against the pack on disk, ... 0 NAMING A SURVEY THE PACK
#                             DOES NOT CONTAIN") — the receipt for the strongest refusal
#                             in this file, invisible in the text report because the
#                             refusal worked and the row passed.
#   t5_pose_stiffness         the five statistics AFS p.16/p.175/p.19 ask for.
#
# `grep -c "gates by threshold provenance" <text report>` returned 0.
#
# A gate declares itself a receipt by putting this key in its detail. It is a statement
# about the gate ("my numbers are the deliverable"), not about the verdict, so it is set
# in the registry-facing adapter and never conditioned on the status — a receipt that
# printed only when the news was bad would be the same defect wearing the other sign.
RECEIPT_KEY = 'evidence_is_the_finding'


def _result(status, explain, observed=None, band=None, source=None, **detail):
    if status not in STATUSES:
        raise GateConfigError('gate returned unknown status %r; valid: %s' % (status, ', '.join(STATUSES)))
    out = {'status': status, 'observed': observed, 'band': band, 'source': source, 'explain': explain}
    if detail:
        out['detail'] = detail
    return out


def validate_registry(gates):
    """Refuse to run against a registry that ships an untagged or contested threshold.

    This is the whole reason the provenance tag is a required field rather than a comment:
    the debunked constants (golden ratio, WHR 0.7, Adonis 1.618, Drillis & Contini) are
    kept out of the engine by a check that runs before any geometry is loaded.
    """
    seen = set()
    for g in gates:
        if not isinstance(g, Gate):
            raise GateConfigError('registry entry %r is not a Gate' % (g,))
        if g.id in seen:
            raise GateConfigError('duplicate gate id %r' % g.id)
        seen.add(g.id)
        if g.tier not in TIERS:
            raise GateConfigError('gate %r has tier %r; valid: %s' % (g.id, g.tier, list(TIERS)))
        if g.severity not in SEVERITIES:
            raise GateConfigError('gate %r has severity %r; valid: %s' % (g.id, g.severity, list(SEVERITIES)))
        if g.provenance == CONTESTED:
            raise GateConfigError(
                'gate %r ships a CONTESTED threshold (%r). Contested constants are not '
                'shippable at any severity: the pack lists golden ratio, WHR 0.7, the '
                '"Adonis" 1.618 shoulder-to-waist, symmetry-as-beauty, the Drillis & '
                'Contini segment constants and the nth-percentile person as debunked. '
                'Remove the gate or replace the threshold with a measured distribution.' % (g.id, g.threshold)
            )
        if g.threshold is not None:
            if g.provenance not in VALID_PROVENANCE:
                raise GateConfigError(
                    'gate %r has threshold %r but provenance %r. Every shipped threshold '
                    'must be tagged %s, %s or %s.' % (g.id, g.threshold, g.provenance, MEASURED, CANON, HOUSE)
                )
            if not g.source:
                raise GateConfigError('gate %r is tagged %s but carries no source line' % (g.id, g.provenance))
        # -- the MEASURED rule -------------------------------------------------------
        # The CANON refusal below is only worth what the word MEASURED is worth. A gate
        # does not get to claim survey evidence by typing the word: it has to produce the
        # survey. See MEASURED_EVIDENCE_CLASSES for the measured bypass this closes.
        if g.provenance == MEASURED:
            ev = g.evidence
            if not ev:
                raise GateConfigError(
                    'gate %r is tagged MEASURED but carries no `evidence` record. '
                    'MEASURED means a survey or a published series answered this '
                    'question, and that claim is checkable only if the gate names it. '
                    'Pass evidence={"class": <one of %s>, ...}, or tag the gate %s if the '
                    'number came off a page and %s if it is ours.'
                    % (g.id, ', '.join(sorted(MEASURED_EVIDENCE_CLASSES)), CANON, HOUSE)
                )
            spec = MEASURED_EVIDENCE_CLASSES.get(ev.get('class'))
            if spec is None:
                raise GateConfigError(
                    'gate %r declares MEASURED evidence class %r; valid: %s'
                    % (g.id, ev.get('class'), ', '.join(sorted(MEASURED_EVIDENCE_CLASSES)))
                )
            missing = [k for k in spec['requires'] if not ev.get(k)]
            if missing:
                raise GateConfigError(
                    'gate %r declares MEASURED evidence class %r, which requires %s; '
                    'missing %s. %s'
                    % (g.id, ev['class'], ', '.join(spec['requires']), ', '.join(missing), spec['what'])
                )
            n = ev.get('n')
            if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
                raise GateConfigError(
                    'gate %r declares MEASURED evidence with n=%r. A measurement has a '
                    'sample size and it is a positive integer; a tag without one is an '
                    'assertion.' % (g.id, n)
                )
            # (i) THE BOOK TEST. Not a page test: see canon_book_citations. A MEASURED
            # gate may not attribute its number to an art/anatomy reference at all.
            cites = (
                canon_book_citations(ev.get('citation'))
                + canon_book_citations(ev.get('pack_source'))
                + canon_book_citations(g.source)
            )
            if cites:
                raise GateConfigError(
                    'gate %r is tagged MEASURED but it CITES A BOOK (%s). A printed '
                    'reference is the definition of %s — it has no sample, no n and no '
                    'sampling frame — so this gate is CANON however the field is typed, '
                    'and whether or not a page number is printed beside the title. (Until '
                    '2026-08-06 this refusal required a literal page marker, so deleting '
                    '"p." from the citation restored the whole bypass; re-review R2.) '
                    'Re-tag it %s (and declare `quantities`), or cite the survey the '
                    'number actually came from. If the book is being mentioned rather '
                    'than cited, move the sentence out of `source` — that field names the '
                    'provenance of the number and nothing else. %s'
                    % (
                        g.id,
                        '; '.join(
                            '%s -> %r%s' % (b, frag, ' [page marker]' if paged else '') for b, frag, paged in cites
                        ),
                        CANON,
                        CANON,
                        CANON_DEFINITION,
                    )
                )
            # (ii) THE COVERAGE TEST (R2, hole b). A pack-backed record that names a
            # survey answering NONE of the quantities the gate thresholds is not evidence
            # about this gate, and at block severity it is refused outright — the same
            # rule, in the same place and for the same reason, as the CANON block refusal
            # below. Where the gate declares nothing this engine can read, it is NOT
            # refused (that would be a static claim about an unreadable gate) but it is
            # censused as coverage-unverified on every run by t4_threshold_provenance,
            # which is where an uncomputable claim belongs under rule 4.
            if spec.get('pack_backed') and g.severity == 'block':
                qs, how_q = declared_quantities(g)
                if qs is not None:
                    covered, _how = measured_covered()
                    if not any(q in covered for q in qs):
                        raise GateConfigError(
                            'gate %r claims block severity on a MEASURED threshold whose '
                            'evidence is the pack, but the pack answers NONE of the '
                            'quantities it names (%s, read from %s). Resolving a source '
                            'KEY is not evidence about a QUANTITY: until 2026-08-06 a gate '
                            'blocking gonial_angle_deg with an ANSUR record was reported '
                            '"resolved against the pack on disk", and ANSUR II ships no '
                            'gonial column. Name the quantities the pack does answer, cite '
                            'the series that does answer this one (class '
                            '"published_series"), or drop to a severity that does not '
                            'block. %s' % (g.id, ', '.join(qs) or 'none', how_q, MEASURED_NOT_COVERED_NOTE)
                        )
        # -- the CANON rule ----------------------------------------------------------
        # A book may set a threshold where no survey speaks. It may never outrank one that
        # does. Enforced here, before any geometry is loaded, for the same reason the
        # CONTESTED refusal is: reviewer attention is not a mechanism.
        if g.provenance == CANON:
            if not g.source:
                raise GateConfigError(
                    'gate %r is tagged CANON but carries no source line. A CANON threshold '
                    'without a book and a page is an opinion. %s' % (g.id, CANON_DEFINITION)
                )
            if g.quantities is None:
                raise GateConfigError(
                    'gate %r is tagged CANON but declares no `quantities`. The CANON rule '
                    'is "a book may not gate a quantity a survey already answers", and '
                    'that cannot be checked against a gate that will not say what it '
                    'measures. Pass quantities=() with the reason in the source line if '
                    'the quantity genuinely has no name in the pack.' % g.id
                )
            if g.severity == 'block':
                covered, _how = measured_covered()
                clash = sorted(q for q in g.quantities if q in covered)
                if clash:
                    raise GateConfigError(
                        'gate %r declares block severity on a CANON threshold for '
                        'quantit(y/ies) %s, for which a MEASURED source already exists '
                        '(%s). %s The gate may be registered at "warn" or "report", or '
                        'the threshold may be re-derived from the survey and re-tagged '
                        'MEASURED. %s'
                        % (
                            g.id,
                            ', '.join(clash),
                            MEASURED_COVERAGE_SOURCE,
                            CANON_DEFINITION,
                            CANON_VS_MEASURED_CONFLICT,
                        )
                    )
        kind = (g.calibration or {}).get('kind')
        if kind not in CALIBRATION_KINDS:
            raise GateConfigError(
                'gate %r declares calibration kind %r; valid: %s. A gate must say how its '
                'severity is to be justified against the reference sample, even if the '
                'answer is %r.' % (g.id, kind, ', '.join(CALIBRATION_KINDS), CAL_STRUCTURAL)
            )
        if kind in (CAL_STRUCTURAL, CAL_DECLARED_BAND) and not g.calibration.get('why'):
            raise GateConfigError(
                'gate %r claims calibration kind %r, which exempts it from the measured '
                'severity policy, but gives no reason. An exemption without a stated '
                'reason is how a statistical gate smuggles itself back to blocking.' % (g.id, kind)
            )
    return True


# ---------------------------------------------------------------------------------
# THE MODULE-VS-REGISTRY PROVENANCE CHECK (re-review R4).
#
# A tier-5 gate is an ADAPTER over a form module, and the module ships a provenance tag of
# its own that travels into the row and is PRINTED. Nothing compared the two. The wave
# re-tagged t5_digit_chains MEASURED -> CANON in the registry, because its only citation is
# two pages of an art-anatomy book and validate_registry now refuses exactly that; and
# geom/form/hands.py went on emitting `provenance=MEASURED` with `source='integer skeletal
# counts, AFS p.179 and p.188'`, which shipped in every row of every report:
#
#     per_side.L.predicate=digit_chains | per_side.L.provenance=MEASURED |
#     per_side.L.source=integer skeletal counts, AFS p.179 and p.188; ...
#
# So the re-tag was half done and the half that shipped was the wrong half.
#
# WHAT COUNTS AS THE UNSAFE DIRECTION. TWO INDEPENDENT TESTS, AND A ROW FAILS ON EITHER.
#
#   (1) A MODULE-EMITTED PROVENANCE MUST ITSELF BE SHIPPABLE FOR THIS GATE.
#       Run the registry's own refusals against the (gate, module-tag) pair. If the gate
#       were tagged with what the module says, would validate_registry accept it? For
#       digit_chains + MEASURED: no — no evidence record, and a citation that is a book.
#       This is the SAME rule the registry already enforces, applied to the tag that was
#       reaching the reader through a side channel, and it needs no allow-list.
#
#   (2) A MODULE MAY NOT CLAIM STRONGER EVIDENCE THAN THE ADJUDICATED TAG.
#       PROVENANCE_RANK is arithmetic (MEASURED 0 < CANON 1 < HOUSE 2). A module tag that
#       OUTRANKS the registry's tells the reader the number is better-evidenced than the
#       adjudication concluded, and that is the flattering direction.
#
# TEST (2) WAS ADDED 2026-08-06 (re-review NEW-2) AND IT REVERSES THE PREVIOUS WAVE'S
# JUDGEMENT, so the reasoning is recorded rather than replaced. That wave rejected the rank
# comparison because it flags t5_patellar_ligament and t5_subcostal_angle, whose registry
# entries deliberately ship the WEAKER composite tag HOUSE (calibration finding 7). It
# treated "shippable" as a proxy for "safe". It is not one, and the mismatch is structural:
#
#   * shippability answers "COULD this gate legitimately be tagged CANON?" — and for a
#     HOUSE gate that carries a source line, quantities and a non-clashing severity the
#     answer is essentially always YES. So for the whole DOWNGRADE shape — registry
#     deliberately weaker, module still shipping the stronger tag — test (1) cannot fire.
#     A test that cannot observe the class of defect it is placed to guard is the third
#     recurring failure shape in this package, and it was sitting inside the fix for the
#     first one.
#   * the reader's question is not "could it be CANON" but "is what I am reading backed by
#     what this row says backs it". t5_subcostal_angle is the exact case: the module ships
#     `band.provenance = CANON` on a band whose own adjacent `note` says the +/-12 deg
#     width came from our plan document. The centres are CANON; the band is not; the
#     registry adjudicated the composite to HOUSE; the module prints CANON anyway. That is
#     structurally the SAME half-done re-tag as digit_chains — registry corrected, module
#     still emitting the wrong half — and calling it "a difference of emphasis" was the
#     previous wave excusing the shape it had just fixed elsewhere.
#
# Cost of the reversal, measured and shipped rather than avoided: t5_patellar_ligament
# (block) and t5_subcostal_angle (warn) become POLICY_ERROR on all five bodies. The verdict
# each gate would have returned is NOT lost — it is computed, carried in the row AND named
# in the status text, because a replaced verdict that is only in the JSON is failure shape
# (b). VERIFIED DIRECTION, 5/5 bodies, both gates: registry HOUSE, module CANON,
# direction='stronger', shippable=True. HOUSE is the WEAKEST tag in PROVENANCE_RANK
# (MEASURED 0 < CANON 1 < HOUSE 2), so a module printing CANON over a registry HOUSE is
# the module claiming BETTER evidence than the adjudication reached — the unsafe direction,
# and the one this rule exists for. "The registry deliberately carries the weaker tag" and
# "the module claims the weaker tag" are opposite sentences and only the first is true
# here; reading the first as the second is how this refusal would get switched off.
#
# WHERE THE DETECTOR LOOKS (re-review NEW-2, the primary half). It used to read exactly
# one key, `detail['module_provenance']`, which 9 of 60 gates set — so the detector's
# coverage was an opt-in list while the rule it printed claimed to need no allow-list.
# Live consequence: t5_patellar_ligament produced a disagreement record and
# t5_subcostal_angle — the identical disagreement, emitted at
# `detail.evidence.band.provenance` instead — produced none, on all five bodies. (The
# previous wave's proof script injected `module_provenance=CANON` for t5_subcostal_angle
# by hand, so its output read as though the live path had seen it. It had not.)
# The detector now walks the WHOLE result tree and finds every key whose name contains
# "provenance", at any depth and through lists, with the path recorded. A value that is
# NOT one of the three tokens ('MEASURED-NULL', 'GEOMETRY', a prose paragraph) is not
# silently dropped: it is carried as `unrecognised_provenance_values` so that a module
# inventing a fourth vocabulary is visible rather than invisible. An emission on a
# DIFFERENT SUBJECT (see NON_THRESHOLD_PROVENANCE_KEYS) is carried as `not_adjudicated`,
# WITH the direction it would have had, so an exemption cannot hide a stronger claim
# without saying so.
#
# An unsafe module tag makes the gate POLICY_ERROR. That is severe on purpose: the row's
# printed provenance is the reader's basis for trusting its number, and a provenance the
# engine would refuse — or one that outranks the adjudicated tag — is not a smaller problem
# than a crash. It is a DIFFERENT problem from a crash, which is why it stopped sharing the
# ERROR token in W4-1: same severity, same blocking behaviour, different sentence. The gate
# ran and checked this body; what is refused is its paperwork, and the finding it produced
# is carried in the row rather than withdrawn.
# ---------------------------------------------------------------------------------
# Key names whose VALUE, if it is one of the three tokens, is a provenance claim. Kept as
# a substring test rather than an exact name so that `module_provenance`, `provenance`,
# `tol_provenance_from_integrity` and any name a module invents next are all in scope.
_PROVENANCE_KEY_TOKEN = 'provenance'  # noqa: S105  key-name substring, not a secret

# TWO SUBJECTS SHARE THE WORD "PROVENANCE" IN THIS PACKAGE, AND ONLY ONE OF THEM IS WHAT
# THE REGISTRY TAG IS ABOUT.
#
#   THE THRESHOLD AXIS — Gate.provenance. "Where does the NUMBER THIS GATE APPLIES come
#   from." This is what the module-vs-registry rule adjudicates.
#
#   THE VALUE AXIS — measure.py's per-measurement `provenance`. "Where does the number
#   MEASURED OFF THIS MESH come from." Its vocabulary is not even the same closed set: it
#   also emits UNMEASURABLE (measure.py:1881, 1913, 1922, 1953, 2076). t2_heights_tight
#   prints it per check as `measurement_provenance`, beside `observed_mm`, with its own
#   caveat line when it reads HOUSE.
#
# Comparing a VALUE-axis tag against the registry's THRESHOLD tag is a category error, and
# a live one: the first version of this detector turned t2_heights_tight into an ERROR on
# four bodies for emitting `measurement_provenance=MEASURED` under a HOUSE threshold tag —
# which says nothing whatever about the threshold. So the axis is decided by the KEY NAME,
# and the rule is FAIL-CLOSED: a provenance-named key is ADJUDICATED unless its name is in
# the exemption table below, which is a table of NAMES with reasons — not of gates. An
# invented `band_provenance` is adjudicated by default; only a name that demonstrably
# describes a different subject is exempt, and every exemption travels into the row so the
# reader can see what was NOT compared and why.
NON_THRESHOLD_PROVENANCE_KEYS = {
    'measurement_provenance': 'the VALUE axis: the provenance of the number measured off this mesh (measure.py '
    '_rec), not of the threshold this gate applies. Its vocabulary includes '
    'UNMEASURABLE, which is not a threshold tag at all.',
    'provenance_note': 'prose defining a provenance vocabulary for the reader, not a tag applied to anything.',
    'tol_provenance_from_integrity': 'the provenance of a tolerance imported from integrity.py, carried with its own '
    'prose; the registry tag for the gate is stated separately.',
    'arm_mask_provenance': 'the provenance of the arm skinning mask used to slice a measurement — the VALUE '
    'axis again, and normally a dict rather than a tag.',
    'claim_provenance': 'THE CLAIM AXIS: where the ASSERTION BEING TESTED comes from, as distinct from '
    'where the NUMBER APPLIED TO IT comes from. Added 2026-08-08 for the two gates '
    'the registry deliberately tags "HOUSE, on a CANON claim — and the split is the '
    'correction" (calibration finding 7): t5_patellar_ligament, whose invariance is '
    'printed at AFS p.208 but whose 2% operationalisation of the word "fixed" is '
    'ours, and t5_subcostal_angle, whose ~90/~60 deg centres are printed at AFS p.13 '
    'but whose +/-12 deg half-width is ours. Both modules used to emit that CANON on '
    "the THRESHOLD key, which outranks the registry's adjudicated HOUSE and made "
    'both gates POLICY_ERROR on every body — a refusal that hid two live anatomical '
    'findings behind a paperwork disagreement. The tag is still recorded and still '
    'carries the direction it would have had, so moving it here cannot bury a '
    'stronger claim; it only stops a claim about the SENTENCE being adjudicated as '
    'though it were a claim about the NUMBER.',
}


def scan_module_provenance(obj):
    """Walk a gate result and return every provenance-shaped emission it contains.

    Returns a list of records, each:
        {'path', 'key', 'value', 'in_vocabulary', 'adjudicated', 'not_adjudicated_because'}

    Full depth, through dicts AND lists, no allow-list of PATHS, cycle-safe. Nothing is
    filtered out: a prose note, an invented token and a real tag all appear, flagged.
    This is the function whose coverage NEW-2 was about — if it is ever narrowed back to
    a fixed key, `_selftest_module_provenance`'s nested cases print WRONG.
    """
    found, seen = [], set()

    def walk(o, path):
        if isinstance(o, dict):
            if id(o) in seen:
                return
            seen.add(id(o))
            for k in o:
                v = o[k]
                p = '%s.%s' % (path, k) if path else str(k)
                key = str(k)
                if isinstance(v, str) and _PROVENANCE_KEY_TOKEN in key.lower():
                    exempt = NON_THRESHOLD_PROVENANCE_KEYS.get(key.lower())
                    found.append(
                        {
                            'path': p,
                            'key': key,
                            'value': v if len(v) <= 140 else '%s … (truncated, %d chars)' % (v[:140], len(v)),
                            'in_vocabulary': v in VALID_PROVENANCE,
                            'adjudicated': exempt is None,
                            'not_adjudicated_because': exempt,
                        }
                    )
                walk(v, p)
        elif isinstance(o, (list, tuple)):
            if id(o) in seen:
                return
            seen.add(id(o))
            for i, v in enumerate(o):
                walk(v, '%s[%d]' % (path, i))

    walk(obj, '')
    return found


def provenance_direction(registry_tag, module_tag):
    """'stronger' | 'weaker' | 'same' | 'incomparable'. Arithmetic, not a comment."""
    if module_tag == registry_tag:
        return 'same'
    r = PROVENANCE_RANK.get(registry_tag)
    m = PROVENANCE_RANK.get(module_tag)
    if r is None or m is None:
        return 'incomparable'
    return 'stronger' if m < r else 'weaker'


def provenance_shippable(gate, provenance):
    """(ok, reason). Would validate_registry accept `gate` tagged `provenance`?

    Never raises: GateConfigError is the answer, not an accident.
    """
    if provenance is None or provenance == gate.provenance:
        return True, 'no disagreement'
    probe = Gate(
        gate.id,
        gate.tier,
        gate.severity,
        gate.title,
        gate.threshold,
        provenance,
        gate.source,
        gate.fn,
        calibration=gate.calibration,
        quantities=gate.quantities,
        evidence=gate.evidence,
    )
    try:
        validate_registry([probe])
    except GateConfigError as e:  # noqa: BLE001
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, (
            'the shippability probe itself raised %s: %s. An unanswerable '
            'question about provenance is not an answer of "fine".' % (type(e).__name__, e)
        )
    return True, (
        '%r would itself be shippable for this gate, so the disagreement is a '
        'difference of emphasis between the module and the registry and is '
        'recorded rather than refused.' % provenance
    )


MODULE_PROVENANCE_RULE = (
    'the registry tag is the adjudicated one — it has been through the CANON refusal and '
    'the MEASURED evidence rule. A module tag is UNSAFE, and therefore a blocking '
    'POLICY_ERROR rather than a note for a reviewer to catch — an error-class status that '
    'blocks exactly as a crash does, and that says explicitly the gate did NOT crash — on '
    'EITHER of two independent tests: (1) those '
    'same refusals would REJECT it for this gate, so it has bypassed adjudication and '
    'still reaches the reader; or (2) it OUTRANKS the registry tag under PROVENANCE_RANK, '
    'so the module is telling the reader the number is better-evidenced than the '
    'adjudication concluded. Test (2) exists because test (1) cannot fire on the '
    'downgrade shape at all: for a HOUSE gate with a source line, "would CANON be '
    'shippable here" is essentially always yes. A module tag that is WEAKER than the '
    'registry tag is the safe direction and is recorded and carried, not refused.'
)


def check_module_provenance(gate, result):
    """Compare every provenance the module emitted to the registry's. Record or None.

    The record always travels into the row. `unsafe` is True when ANY emitted tag either
    would be REFUSED for this gate or OUTRANKS the registry tag; that is the case
    run_gates turns into a POLICY_ERROR — blocking, and explicitly not a crash.

    DIRECTION, SO NOBODY HAS TO RE-DERIVE IT: PROVENANCE_RANK is MEASURED 0 < CANON 1 <
    HOUSE 2, lower is BETTER-EVIDENCED. `outranks_registry_tag` is True when the MODULE's
    tag ranks lower than the REGISTRY's, i.e. the module claims BETTER evidence than the
    adjudication concluded. A module claiming WEAKER-or-equal evidence is the safe
    direction: it is recorded, carried, and is not unsafe (self-test case 6).
    """
    emitted = scan_module_provenance(result)
    if not emitted:
        return None
    tags = {}
    for e in emitted:
        if e['in_vocabulary'] and e['adjudicated']:
            tags.setdefault(e['value'], []).append(e['path'])
    not_adjudicated = [e for e in emitted if not e['adjudicated']]
    unknown = [e for e in emitted if e['adjudicated'] and not e['in_vocabulary']]
    disagreeing = sorted((t for t in tags if t != gate.provenance), key=lambda t: PROVENANCE_RANK.get(t, 99))
    if not disagreeing and not unknown and not not_adjudicated:
        return None

    per_tag, unsafe_because = [], []
    for tag in disagreeing:
        ok, why = provenance_shippable(gate, tag)
        direction = provenance_direction(gate.provenance, tag)
        outranks = direction == 'stronger'
        rec = {
            'module_provenance': tag,
            'paths': sorted(tags[tag]),
            'shippable_for_this_gate': ok,
            'shippability_reason': why,
            'direction': direction,
            'outranks_registry_tag': outranks,
            'unsafe': bool(outranks or not ok),
        }
        if not ok:
            unsafe_because.append(
                '%s is NOT SHIPPABLE for this gate (emitted at %s): %s' % (tag, ', '.join(rec['paths']), why)
            )
        if outranks:
            unsafe_because.append(
                '%s OUTRANKS the registry tag %s (emitted at %s). The registry tag is the '
                'adjudicated one; a module that prints a stronger one is telling the '
                'reader this number is better-evidenced than the adjudication concluded.'
                % (tag, gate.provenance, ', '.join(rec['paths']))
            )
        per_tag.append(rec)

    # The strongest disagreeing tag is what a reader is most likely to be misled by, so it
    # is the one that keeps the singular key name every consumer already reads.
    worst = per_tag[0]['module_provenance'] if per_tag else None
    out = {
        'registry_provenance': gate.provenance,
        # False means "this record is an AUDIT, not a disagreement": the gate emitted
        # provenance-shaped values, none of them a threshold-axis tag that differs from
        # the registry's. The key it travels under is still `provenance_disagreement`
        # because that is what R4 established and what a reviewer greps for.
        'is_a_disagreement': bool(per_tag),
        'module_provenance': worst,
        'module_provenance_tags': [r['module_provenance'] for r in per_tag],
        'module_provenance_paths': {r['module_provenance']: r['paths'] for r in per_tag},
        # Flat, because `per_tag` is a list of dicts and the artefact writer collapses
        # those below depth 3 — the direction must survive into the file a human reads.
        'module_provenance_direction': {r['module_provenance']: r['direction'] for r in per_tag},
        'per_tag': per_tag,
        'module_tag_shippable_for_this_gate': all(r['shippable_for_this_gate'] for r in per_tag) if per_tag else True,
        'unsafe': bool(unsafe_because),
        'unsafe_because': unsafe_because,
        'why': ' | '.join(unsafe_because)
        if unsafe_because
        else (
            'no threshold-axis tag disagrees with the registry: the provenance-named '
            'values this module emits are either off the threshold axis or outside '
            'the three-token vocabulary, and both sets are listed below.'
            if not per_tag
            else 'every adjudicated tag is WEAKER than the registry tag %r and would itself '
            'be shippable here, so the disagreement is the safe direction and is '
            'recorded rather than refused.' % gate.provenance
        ),
        'detector': 'the WHOLE result tree is walked, at full depth and through lists, for '
        'any key whose name contains "provenance". It is not keyed on '
        'detail["module_provenance"]: that read covered 9 of 60 gates and '
        'missed t5_subcostal_angle, which emits at '
        'detail.evidence.band.provenance (re-review NEW-2). %d emission(s) '
        'found here: %d adjudicated against the registry tag, %d off the '
        'threshold axis, %d outside the %s vocabulary.'
        % (
            len(emitted),
            len(emitted) - len(not_adjudicated) - len(unknown),
            len(not_adjudicated),
            len(unknown),
            '/'.join(VALID_PROVENANCE),
        ),
        'rule': MODULE_PROVENANCE_RULE,
        'emissions_found': len(emitted),
    }
    # FLAT STRING LISTS, NOT LISTS OF DICTS. report.py's artefact writer collapses a
    # nested dict below depth 3 into "{6 keys: ...}" — measured: the structured version of
    # these two lists reached the JSON as that placeholder and the reader got nothing. A
    # disclosure that is computed and then rendered away is failure shape (b), so the
    # sentence the reader needs is built here, in the row, as a plain string.
    if unknown:
        out['unrecognised_provenance_values'] = [
            '%s = %r' % (e['path'], e['value']) for e in sorted(unknown, key=lambda r: r['path'])
        ]
        out['unrecognised_note'] = (
            'these keys are provenance-named, sit on the THRESHOLD axis and carry a string '
            'that is NOT one of the three tokens, so there is nothing to adjudicate — they '
            'are a different vocabulary (a null-model name such as MEASURED-NULL, a '
            'geometric identity, a prose note). They are listed rather than dropped: a '
            'module inventing a fourth provenance vocabulary must be visible, and silently '
            'discarding a value the detector does not understand is how a blind spot is '
            'built.'
        )
    if not_adjudicated:
        out['not_adjudicated'] = [
            '%s = %r — NOT compared to the registry tag %s (it would have been %s); %s'
            % (
                e['path'],
                e['value'],
                gate.provenance,
                provenance_direction(gate.provenance, e['value'])
                if e['in_vocabulary']
                else 'not a threshold tag at all',
                e['not_adjudicated_because'],
            )
            for e in sorted(not_adjudicated, key=lambda r: r['path'])
        ]
        out['not_adjudicated_paths'] = [e['path'] for e in sorted(not_adjudicated, key=lambda r: r['path'])]
        out['not_adjudicated_note'] = (
            'these emissions are on a DIFFERENT SUBJECT from Gate.provenance and are '
            'therefore compared to nothing — see NON_THRESHOLD_PROVENANCE_KEYS. The '
            'exemption is by KEY NAME and it is FAIL-CLOSED: any provenance-named key not '
            'in that table IS adjudicated. Each line above states the direction the tag '
            'WOULD have had, and `not_adjudicated_outranking` lists the exempt paths that '
            'outrank the registry tag, so an exemption cannot hide a stronger claim '
            'without saying so. Live case: t2_heights_tight emits '
            'measurement_provenance=MEASURED under a '
            'HOUSE threshold tag; that is the provenance of the MEASURED VALUE, not of the '
            'threshold, and reading it as the latter turned four bodies into ERROR before '
            'this split existed.'
        )
        out['not_adjudicated_outranking'] = [
            e['path']
            for e in not_adjudicated
            if e['in_vocabulary'] and provenance_direction(gate.provenance, e['value']) == 'stronger'
        ]
    return out
