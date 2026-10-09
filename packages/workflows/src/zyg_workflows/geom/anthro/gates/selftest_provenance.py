# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Self-tests over refusal, census buckets, the MEASURED bypass and module provenance.

Moved verbatim out of the old single-file gates.py (lines 8765-9344).
"""

from zyg_workflows.geom.anthro.gates.policy import (
    CANON,
    CONTESTED,
    EV_ANSUR_II,
    FAIL,
    HOUSE,
    MEASURED,
    NOT_IMPLEMENTABLE,
    PASS,
    verify_measured_evidence,
)
from zyg_workflows.geom.anthro.gates.bands import CAL_STRUCTURAL, GateConfigError, _printed_band, _structural
from zyg_workflows.geom.anthro.gates.gate import Gate, _result, check_module_provenance, validate_registry
from zyg_workflows.geom.anthro.gates.tier4 import MEASURED_CENSUS_BUCKETS, _census_bucket, t4_threshold_provenance
from zyg_workflows.geom.anthro.gates.registry import GATES
from zyg_workflows.geom.anthro.gates.selftest_runtime import _selftest_declared_claims


def _selftest_refusal():
    """The CONTESTED refusal has to be a code path, not a promise. Prove it."""
    out = []
    bad = Gate(
        't9_golden_ratio',
        2,
        'block',
        'navel divides stature at phi',
        1.618,
        CONTESTED,
        'debunked: measured attractor is nearer 5/3',
        lambda s: _result(PASS, 'never reached'),
        calibration=_structural('never reached'),
    )
    try:
        validate_registry(list(GATES) + [bad])
        out.append('REFUSAL FAILED: a CONTESTED threshold was accepted')
    except GateConfigError as e:
        out.append('CONTESTED threshold refused: %s' % str(e).split('.')[0])
    untagged = Gate(
        't9_untagged',
        2,
        'block',
        'no provenance',
        0.7,
        None,
        None,
        lambda s: _result(PASS, 'never reached'),
        calibration=_structural('never reached'),
    )
    try:
        validate_registry(list(GATES) + [untagged])
        out.append('REFUSAL FAILED: an untagged threshold was accepted')
    except GateConfigError as e:
        out.append('untagged threshold refused: %s' % str(e).split('.')[0])
    exempt = Gate(
        't9_unjustified_exemption',
        2,
        'block',
        'claims to be structural',
        1.0,
        HOUSE,
        'HOUSE',
        lambda s: _result(PASS, 'never reached'),
        calibration={'kind': CAL_STRUCTURAL},
    )
    try:
        validate_registry(list(GATES) + [exempt])
        out.append('REFUSAL FAILED: an unjustified structural exemption was accepted')
    except GateConfigError as e:
        out.append('unjustified severity exemption refused: %s' % str(e).split('.')[0])
    unknown = Gate(
        't9_no_calibration',
        2,
        'block',
        'no calibration kind',
        1.0,
        HOUSE,
        'HOUSE',
        lambda s: _result(PASS, 'never reached'),
        calibration={'kind': 'vibes'},
    )
    try:
        validate_registry(list(GATES) + [unknown])
        out.append('REFUSAL FAILED: an unknown calibration kind was accepted')
    except GateConfigError as e:
        out.append('unknown calibration kind refused: %s' % str(e).split('.')[0])

    # -- the CANON rule, proven as a code path rather than promised ------------------
    # This is the exact gate the plan warns about: AFS p.91-92 draws children with
    # relatively SHORTER legs (crotch height migrating downward with age) and NHANES III
    # on disk says the opposite. If that chart could ship at block severity it would fail
    # a 12-year-old for being correctly proportioned.
    canon_block = Gate(
        't9_afs_crotch_height',
        2,
        'block',
        'crotch height sits at 0.55 of stature in a child (AFS p.91-92)',
        {'crotch_over_stature': 0.55},
        CANON,
        'CANON — AFS p.91-92',
        lambda s: _result(PASS, 'never reached'),
        quantities=('crotch_height_over_stature',),
        calibration=_printed_band('never reached'),
    )
    try:
        validate_registry(list(GATES) + [canon_block])
        out.append('REFUSAL FAILED: a CANON threshold was allowed to BLOCK a quantity ANSUR II already measures')
    except GateConfigError as e:
        out.append('CANON block over a MEASURED quantity refused: %s' % str(e).split('.')[0])
    # ... and the same threshold at 'warn' is ACCEPTED, because the rule is about rank and
    # not about banning books. A refusal that refused everything would prove nothing.
    canon_warn = Gate(
        't9_afs_crotch_height_warn',
        2,
        'warn',
        'the same claim, at warn',
        {'crotch_over_stature': 0.55},
        CANON,
        'CANON — AFS p.91-92',
        lambda s: _result(PASS, 'never reached'),
        quantities=('crotch_height_over_stature',),
        calibration=_printed_band('never reached'),
    )
    try:
        validate_registry(list(GATES) + [canon_warn])
        out.append(
            'the same CANON threshold at warn severity: ACCEPTED (the rule ranks evidence, it does not ban books)'
        )
    except GateConfigError as e:
        out.append('WRONG: a CANON threshold at warn was refused: %s' % e)
    # ... and a CANON threshold on a quantity NO survey answers may block.
    canon_angle = Gate(
        't9_gonial_block',
        2,
        'block',
        'a gonial-angle band',
        {'lo': 100.0},
        CANON,
        'CANON — HeadNeck p.15',
        lambda s: _result(PASS, 'never reached'),
        quantities=('gonial_angle_deg',),
        calibration=_structural('never reached'),
    )
    try:
        validate_registry(list(GATES) + [canon_angle])
        out.append('a CANON threshold on a quantity no survey answers (gonial angle) at block severity: ACCEPTED')
    except GateConfigError as e:
        out.append('WRONG: a CANON angle threshold was refused: %s' % e)
    # ... and a CANON gate that will not say what it measures is refused outright.
    canon_mute = Gate(
        't9_canon_mute',
        2,
        'warn',
        'names no quantity',
        {'x': 1.0},
        CANON,
        'CANON — some page',
        lambda s: _result(PASS, 'never reached'),
        calibration=_printed_band('never reached'),
    )
    try:
        validate_registry(list(GATES) + [canon_mute])
        out.append('REFUSAL FAILED: a CANON gate with no declared quantity was accepted')
    except GateConfigError as e:
        out.append('CANON gate with no declared quantity refused: %s' % str(e).split('.')[0])
    out.extend(_selftest_measured_bypass())
    out.extend(_selftest_module_provenance())
    out.extend(_selftest_census_buckets())
    out.extend(_selftest_declared_claims())
    return out


def _selftest_census_buckets():
    """A NAME LIST MUST BELONG TO THE COUNT IT FOLLOWS (re-review NEW-3).

    The check that can SEE the defect is the third one: it rebuilds each clause FROM THE
    JSON DETAIL — the half that was already correct — and asserts the rebuilt clause is
    present verbatim in the sentence a human reads. NEW-3 was exactly a divergence between
    those two halves, so a self-test that only exercised the counts, or only the JSON,
    would have blessed it.
    """
    out, wrong = [], []

    def verdict(label, ok, wrong_txt):
        out.append('%s (%s)' % (label, 'correct' if ok else 'WRONG: ' + wrong_txt))
        if not ok:
            wrong.append(label)

    verdict(
        '1 empty bucket renders a bare count: %r' % _census_bucket([], 'THINGS'),
        _census_bucket([], 'THINGS') == '0 THINGS',
        'an empty bucket is printing names',
    )
    verdict(
        '2 a populated bucket renders count and names together: %r' % _census_bucket(['a', 'b'], 'THINGS'),
        _census_bucket(['a', 'b'], 'THINGS') == '2 THINGS: a, b',
        'the count and the names are computed separately again',
    )

    # 3. THE LIVE CROSS-CHECK. Rebuild every clause from the JSON buckets and require it
    #    verbatim in the explain string. This is the assertion the shipped sentence failed.
    r = t4_threshold_provenance(None)
    buckets = r['detail']['measured_census_buckets']
    for key, text in MEASURED_CENSUS_BUCKETS:
        clause = _census_bucket(buckets[key], text)
        verdict(
            '3.%-24s clause present verbatim in the sentence: %r'
            % (key, clause if len(clause) < 90 else clause[:87] + '...'),
            clause in r['explain'],
            'the JSON bucket %r and the sentence disagree — %d name(s) are being '
            "printed under a different bucket's count, which is NEW-3" % (key, len(buckets[key])),
        )

    # 4. And the buckets must partition the MEASURED gates: a name that is in no bucket,
    #    or in two, is a census that does not add up.
    n_measured = len([g for g in GATES if g.provenance == MEASURED])
    total = sum(len(v) for v in buckets.values())
    allnames = [n for v in buckets.values() for n in v]
    verdict(
        '4 buckets partition the MEASURED gates: %d in buckets vs %d MEASURED, '
        '%d duplicate(s)' % (total, n_measured, len(allnames) - len(set(allnames))),
        total == n_measured and len(allnames) == len(set(allnames)),
        'the census does not account for every MEASURED gate exactly once',
    )

    out.append(
        'census-bucket self-checks: all %d correct' % (len(out) - len(wrong))
        if not wrong
        else 'census-bucket self-checks: %d WRONG -> %s' % (len(wrong), '; '.join(wrong))
    )
    return out


def _selftest_measured_bypass():
    """THE MEASURED TAG IS VALIDATED AGAINST EVIDENCE, NOT AGAINST SPELLING (R2).

    The previous refusal matched a literal page marker beside the book name, so deleting
    "p." from the citation restored the whole CANON bypass; and the live half resolved the
    pack KEY without ever asking whether the pack answers the gate's QUANTITY. Both halves
    are exercised here, each with the control that proves it is not just refusing
    everything.
    """
    out = []

    def probe(gid, **kw):
        d = dict(
            id=gid,
            tier=5,
            severity='block',
            title='probe',
            threshold={'crotch_height_over_stature': 0.5},
            provenance=MEASURED,
            source='MEASURED - ANSUR II',
            fn=lambda s: _result(PASS, 'never reached'),
            calibration=_structural('never reached'),
            quantities=('crotch_height_over_stature',),
            evidence=EV_ANSUR_II,
        )
        d.update(kw)
        try:
            validate_registry([Gate(**d)])
            return None
        except GateConfigError as e:
            return str(e)

    # (a) the book test, with and without a page marker. Both must refuse.
    for label, src in (
        ('a page citation', 'MEASURED - AFS p.91-92'),
        ('a chart, no page', 'MEASURED - the Anatomy For Sculptors head-unit chart'),
        ('a chapter, no page', 'MEASURED - AFS chapter 4, the crotch chart'),
        ('a figure, no page', 'MEASURED - Anatomy For Sculptors, fig. 12'),
    ):
        e = probe('t9_book_%s' % abs(hash(src)), source=src)
        out.append(
            'MEASURED block citing a canon book (%s): %s'
            % (label, 'refused' if e else 'REFUSAL FAILED — the book test is still a page test')
        )
    # ... and the control: a MEASURED gate that cites a survey and no book is accepted.
    e = probe('t9_clean')
    out.append(
        'MEASURED block citing only ANSUR: %s'
        % (
            'ACCEPTED (control — the rule refuses books, not measurement)'
            if not e
            else 'WRONG, refused: %s' % e.split('.')[0]
        )
    )
    # (b) the coverage test: the pack must ANSWER the gate, not merely contain the key.
    e = probe('t9_gonial', threshold={'gonial_angle_deg': 125.0}, quantities=('gonial_angle_deg',))
    out.append(
        'MEASURED block over gonial_angle_deg with an ANSUR record: %s'
        % (
            'refused — ANSUR ships no gonial column'
            if e
            else 'REFUSAL FAILED — a resolved key was accepted as evidence about a quantity the pack does not measure'
        )
    )
    # (c) the withdrawn class cannot come back by being typed.
    e = probe(
        't9_own',
        source='MEASURED - our own meshes',
        evidence={'class': 'own_assets', 'citation': 'we looked', 'n': 4, 'population': 'ours'},
    )
    out.append(
        'MEASURED via the withdrawn own_assets class: %s' % ('refused' if e else 'REFUSAL FAILED — own_assets is back')
    )
    # (d) and the live half still reports an unverifiable coverage claim as unverified
    #     rather than as resolved.
    mute = Gate(
        't9_mute',
        5,
        'warn',
        'probe',
        {'x': 1.0},
        MEASURED,
        'MEASURED - ANSUR II',
        lambda s: _result(PASS, 'never reached'),
        calibration=_structural('never reached'),
        evidence=EV_ANSUR_II,
    )
    ok, rec = verify_measured_evidence(mute, live=True)
    out.append(
        'a MEASURED gate that names no quantity: verified=%r because=%r (%s)'
        % (
            ok,
            rec.get('unresolved_because'),
            'correct — unverifiable is not verified'
            if ok is None and rec.get('unresolved_because') == 'coverage_not_verifiable'
            else 'WRONG',
        )
    )
    return out


def _selftest_module_provenance():
    """A MODULE TAG THE REGISTRY WOULD REFUSE, OR ONE THAT OUTRANKS IT, IS AN ERROR (R4,
    re-review NEW-2).

    THE DEFECT THIS SUITE IS NAMED FOR, AND THE CASES THAT CAN SEE IT. The previous
    version of this self-test fed `module_provenance=` to `_result()` in every case — the
    ONE key the previous detector read. It therefore could not have told the difference
    between a detector that walks the result and a detector that reads a single key, which
    is exactly the difference NEW-2 was about: on the live path t5_subcostal_angle emits
    its CANON at `detail.evidence.band.provenance`, produced NO record on any of the five
    bodies, and the previous wave's proof script injected the key by hand so that its
    output read as though the live path had seen it. Cases 3, 4 and 5 below emit ONLY at
    nested paths — through a dict, through a list, and at depth 5 — so a detector narrowed
    back to a fixed key prints WRONG here rather than passing.
    """
    out, wrong = [], []

    def verdict(label, ok, right, wrong_txt):
        out.append('%s (%s)' % (label, right if ok else 'WRONG: ' + wrong_txt))
        if not ok:
            wrong.append(label)

    canon_gate = Gate(
        't9_mp',
        5,
        'block',
        'probe',
        {'phalanges': 14},
        CANON,
        'CANON — AFS p.179',
        lambda s: _result(PASS, 'x'),
        quantities=('phalanges_per_hand',),
        calibration=_structural('an integer count'),
    )
    house_gate = Gate(
        't9_mp2',
        5,
        'block',
        'probe',
        {'max_drift_frac': 0.02},
        HOUSE,
        'HOUSE, on a CANON claim',
        lambda s: _result(PASS, 'x'),
        quantities=('patella_tibial_tuberosity_distance_drift',),
        calibration=_structural('our own skinning solve'),
    )
    measured_gate = Gate(
        't9_mp3',
        2,
        'warn',
        'probe',
        {'crotch_height_over_stature': 0.5},
        MEASURED,
        'MEASURED - ANSUR II',
        lambda s: _result(PASS, 'x'),
        quantities=('crotch_height_over_stature',),
        calibration=_structural('a probe'),
        evidence=EV_ANSUR_II,
    )

    # 1. The live shape of R4: registry CANON, module still MEASURED, and MEASURED is not
    #    shippable for this gate (no evidence record, and a book citation).
    rec = check_module_provenance(canon_gate, _result(PASS, 'x', module_provenance=MEASURED))
    verdict(
        '1 module MEASURED where the registry says CANON: unsafe=%r' % (rec and rec['unsafe']),
        bool(rec and rec['unsafe'] and not rec['module_tag_shippable_for_this_gate']),
        'correct — an unshippable tag is an ERROR',
        'the half-done re-tag ships again',
    )

    # 2. THE REVERSAL (NEW-2). Registry HOUSE, module CANON. The tag WOULD be shippable
    #    here, which is why the previous wave recorded it and moved on — but it OUTRANKS
    #    the adjudicated tag, and that is the flattering direction. Now a POLICY_ERROR.
    #    This is the live t5_patellar_ligament / t5_subcostal_angle shape, VERIFIED against
    #    the artefacts on 5/5 bodies: registry HOUSE, module CANON, direction 'stronger'.
    rec2 = check_module_provenance(house_gate, _result(PASS, 'x', module_provenance=CANON))
    verdict(
        '2 module CANON where the registry ships the weaker HOUSE: unsafe=%r '
        'shippable=%r direction=%r'
        % (
            rec2 and rec2['unsafe'],
            rec2 and rec2['module_tag_shippable_for_this_gate'],
            rec2 and rec2['per_tag'][0]['direction'],
        ),
        bool(
            rec2
            and rec2['unsafe']
            and rec2['module_tag_shippable_for_this_gate']
            and rec2['per_tag'][0]['direction'] == 'stronger'
        ),
        'correct — shippable is not the same question as safe; outranking the adjudicated tag is an ERROR',
        'a module claiming stronger evidence than the registry is back to being a note a reviewer has to notice',
    )

    # 3. THE NEW-2 CASE ITSELF. No `module_provenance` key anywhere — the tag is emitted
    #    exactly where t5_subcostal_angle emits it, and NOWHERE else.
    subcostal_shape = _result(
        NOT_IMPLEMENTABLE,
        'unresolved on this rig',
        evidence={'band': {'provenance': CANON, 'source': 'AFS p.13', 'note': 'the width is ours'}, 'resolved': False},
    )
    rec3 = check_module_provenance(house_gate, subcostal_shape)
    verdict(
        '3 tag ONLY at detail.evidence.band.provenance (the live t5_subcostal_angle '
        'shape): record=%r paths=%r' % (bool(rec3), rec3 and rec3['module_provenance_paths'].get(CANON)),
        bool(
            rec3
            and rec3['unsafe']
            and rec3['module_provenance_paths'].get(CANON) == ['detail.evidence.band.provenance']
        ),
        'correct — the detector walks the result, it is not an opt-in key',
        'the detector is keyed on detail["module_provenance"] again and covers 9 of '
        '60 gates while claiming to need no allow-list',
    )

    # 4. Through a LIST, so case 3 cannot be satisfied by special-casing two dict levels.
    rec4 = check_module_provenance(
        house_gate, _result(PASS, 'x', claims=[{'id': 'a'}, {'id': 'b', 'provenance': CANON}])
    )
    verdict(
        '4 tag reached through a list index: paths=%r' % (rec4 and rec4['module_provenance_paths'].get(CANON)),
        bool(rec4 and rec4['module_provenance_paths'].get(CANON) == ['detail.claims[1].provenance']),
        'correct — lists are walked',
        'a tag inside a list is invisible',
    )

    # 5. Depth 5, under a key the detector has never heard of.
    rec5 = check_module_provenance(
        house_gate,
        _result(PASS, 'x', detail_from_module={'library': {'detail': {'scored': [{'whatever_provenance': CANON}]}}}),
    )
    verdict(
        '5 tag at depth 5 under an unknown key name: paths=%r' % (rec5 and rec5['module_provenance_paths'].get(CANON)),
        bool(
            rec5
            and rec5['module_provenance_paths'].get(CANON)
            == ['detail.detail_from_module.library.detail.scored[0].whatever_provenance']
        ),
        'correct — full depth, key matched on the substring, value on the vocabulary',
        'depth or key-name assumptions have crept back in',
    )

    # 6. THE CONTROL that stops this from being "refuse every disagreement": a tag that is
    #    WEAKER than the registry's is the safe direction. Live shape: t2_mahalanobis and
    #    t3_cast_diversity are MEASURED gates carrying per-component HOUSE provenances.
    rec6 = check_module_provenance(
        measured_gate,
        _result(
            PASS,
            'x',
            used_provenance={
                'cervicale_height_over_stature': {'provenance': HOUSE},
                'acromial_height_over_stature': {'provenance': MEASURED},
            },
        ),
    )
    verdict(
        '6 module HOUSE (weaker) under a MEASURED registry tag: record=%r unsafe=%r '
        'direction=%r' % (bool(rec6), rec6 and rec6['unsafe'], rec6 and rec6['per_tag'][0]['direction']),
        bool(rec6 and not rec6['unsafe'] and rec6['per_tag'][0]['direction'] == 'weaker'),
        'correct — recorded and carried, not refused',
        'the safe direction was turned into an error, which is refusing everything',
    )

    # 7. No disagreement anywhere -> no record at all.
    verdict(
        '7 registry CANON, module CANON at three different paths -> no record',
        check_module_provenance(
            canon_gate,
            _result(
                PASS,
                'x',
                module_provenance=CANON,
                per_side={'L': {'provenance': CANON}},
                evidence={'band': {'provenance': CANON}},
            ),
        )
        is None,
        'correct',
        'agreement is being reported as a disagreement',
    )

    # 8. A VALUE OUTSIDE THE VOCABULARY IS NOT SILENTLY DROPPED and is not read as a tag.
    #    Live shapes: t5_landmark_relief emits 'MEASURED-NULL', t5_neck_section 'GEOMETRY'.
    rec8 = check_module_provenance(canon_gate, _result(PASS, 'x', cuts={'ridge': {'provenance': 'MEASURED-NULL'}}))
    got = (rec8 or {}).get('unrecognised_provenance_values', [])
    verdict(
        '8 %r is listed as unrecognised, not read as MEASURED: values=%r tags=%r'
        % ('MEASURED-NULL', got, rec8 and rec8['module_provenance_tags']),
        bool(
            rec8
            and got == ["detail.cuts.ridge.provenance = 'MEASURED-NULL'"]
            and rec8['module_provenance_tags'] == []
            and not rec8['unsafe']
        ),
        'correct — a fourth vocabulary is visible, and it is not adjudicated',
        'an invented provenance token is either invisible or silently promoted to a real one',
    )

    # 9. Every path a tag was emitted at is reported, not just the first one found.
    rec9 = check_module_provenance(
        house_gate, _result(PASS, 'x', module_provenance=CANON, evidence={'band': {'provenance': CANON}})
    )
    verdict(
        '9 both emission sites reported: paths=%r' % (rec9 and rec9['module_provenance_paths'].get(CANON)),
        bool(
            rec9
            and rec9['module_provenance_paths'].get(CANON)
            == ['detail.evidence.band.provenance', 'detail.module_provenance']
        ),
        'correct',
        'the detector stops at the first hit and under-reports the spread',
    )

    # 10. THE AXIS SPLIT, safe side. `measurement_provenance` is the provenance of the
    #     MEASURED VALUE, not of the threshold — the live t2_heights_tight shape, which
    #     the first version of this detector turned into an ERROR on four bodies. It must
    #     NOT be adjudicated, and the fact that it would have outranked must still print.
    rec10 = check_module_provenance(
        house_gate, _result(FAIL, 'x', checks=[{'dim': 'acromial_height', 'measurement_provenance': MEASURED}])
    )
    verdict(
        '10 measurement_provenance=MEASURED under a HOUSE threshold tag: unsafe=%r '
        'tags=%r not_adjudicated=%d outranking=%r'
        % (
            rec10 and rec10['unsafe'],
            rec10 and rec10['module_provenance_tags'],
            len((rec10 or {}).get('not_adjudicated') or []),
            (rec10 or {}).get('not_adjudicated_outranking'),
        ),
        bool(
            rec10
            and not rec10['unsafe']
            and rec10['module_provenance_tags'] == []
            and len(rec10['not_adjudicated']) == 1
            and rec10['not_adjudicated_outranking'] == ['detail.checks[0].measurement_provenance']
        ),
        'correct — the VALUE axis is not compared to the THRESHOLD tag, and the '
        'exemption publishes what it did not compare',
        "a per-measurement provenance is being read as this gate's threshold tag, "
        'which is the category error that broke t2_heights_tight on four bodies — or '
        'the exemption is silent about a stronger claim',
    )

    # 11. THE AXIS SPLIT, fail-closed side. A key name nobody has exempted IS adjudicated,
    #     so the exemption table cannot become a hiding place by inventing a new name.
    rec11 = check_module_provenance(house_gate, _result(PASS, 'x', band_provenance=CANON))
    verdict(
        '11 an UNKNOWN provenance-named key (band_provenance) is adjudicated by '
        'default: unsafe=%r' % (rec11 and rec11['unsafe']),
        bool(rec11 and rec11['unsafe'] and rec11['module_provenance_paths'].get(CANON) == ['detail.band_provenance']),
        'correct — fail-closed: only names in NON_THRESHOLD_PROVENANCE_KEYS are '
        'exempt, and that table is names, not gates',
        'an unrecognised key name escapes adjudication, so any module can opt out by renaming its field',
    )

    # The summary line carries the word WRONG only when something IS wrong, so that a
    # grep for it over this output is not permanently self-triggering.
    out.append(
        'module-provenance self-checks: all 11 correct'
        if not wrong
        else 'module-provenance self-checks: %d of 11 WRONG -> %s' % (len(wrong), '; '.join(wrong))
    )
    return out
