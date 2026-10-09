# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the section helpers `contract_fixture` was split into.

The fixture exists to drive the renderer over its awkward rows, so what these tests pin
is exactly that: which rows are present, in which order, and which awkward property each
one carries. Every one of them used to be reachable only through the 340-line literal.
"""

from zyg_workflows.geom.anthro.report import fixture as FX


def _ids(rows):
    return [r if isinstance(r, str) else r.get('id') for r in rows]


# ── the severity-calibration block ───────────────────────────────────────────


def test_the_calibration_ceiling_is_one_percent_and_the_policy_names_it():
    cal = FX._severity_calibration()
    assert cal['ceiling'] == 0.01
    assert "severity 'block'" in cal['policy']
    assert '1.0%' in cal['policy']


def test_exactly_the_downgraded_row_is_listed_as_downgraded():
    cal = FX._severity_calibration()
    flagged = [r['id'] for r in cal['rows'] if r['downgraded']]
    assert flagged == cal['downgraded'] == ['bideltoid_breadth_over_stature']


def test_each_calibration_basis_appears_exactly_once():
    rows = FX._severity_calibration()['rows']
    assert [r['basis'] for r in rows] == ['measured', 'measured', 'not_applicable']
    # the not-applicable row is the one with no rejection rate to report
    assert [r['id'] for r in rows if r['rejection_rate'] is None] == ['volume_height_index']


def test_both_sexes_declare_an_independent_band_admission_fraction():
    adm = FX._severity_calibration()['independent_bands_admission']
    assert set(adm) == {'male', 'female'}
    assert all(0.0 < adm[s]['admitted_fraction'] < 1.0 for s in adm)


def test_the_calibration_block_is_fresh_on_every_call():
    first = FX._severity_calibration()
    first['rows'][0]['effective'] = 'MUTATED'
    assert FX._severity_calibration()['rows'][0]['effective'] == 'block'


# ── the frame tier ───────────────────────────────────────────────────────────


def test_the_frame_tier_carries_the_per_gate_wall_clock_with_its_per_side_copies():
    stature = FX._frame_gates()[0]
    assert stature['id'] == 'stature_declared_vs_built'
    assert stature['detail']['ms'] == 0.417
    assert set(stature['detail']['per_side']) == {'L', 'R'}
    assert stature['detail']['per_side']['L']['ms'] == 0.19


def test_the_frame_tier_warns_rather_than_fails_between_p95_and_p99():
    mahal = FX._frame_gates()[1]
    assert mahal['status'] == 'warn'
    assert mahal['severity'] == 'critical'
    assert mahal['observed']['units'] == 'D^2'
    assert mahal['band']['width'] == 'empirical p99'


# ── the heights tier: both band shapes ───────────────────────────────────────


def test_the_heights_tier_ships_a_dict_band_and_a_list_band():
    crotch, acromial = FX._height_gates()
    assert isinstance(crotch['band'], dict)
    assert isinstance(acromial['band'], list) and len(acromial['band']) == 2


def test_only_the_failing_height_declares_the_population_caveat():
    rows = FX._height_gates()
    assert [r['id'] for r in rows if 'population' in r] == ['crotch_height_over_stature']
    assert [r['status'] for r in rows] == ['fail', 'pass']


# ── the breadths tier: calibrated severities and a contested band ────────────


def test_the_downgraded_breadth_keeps_its_declared_severity_beside_the_effective_one():
    bideltoid = FX._breadth_gates()[0]
    assert (bideltoid['severity'], bideltoid['severity_declared']) == ('warn', 'block')
    assert bideltoid['severity_calibrated'] is True
    assert bideltoid['reference_rejection_rate'] == 0.1197


def test_a_downgraded_blocking_gate_that_produced_no_verdict_is_in_the_tier():
    girths = next(g for g in FX._breadth_gates() if g['id'] == 'girths_wide_calibrated')
    assert girths['status'] == 'skipped'
    assert girths['severity_declared'] == 'block'
    assert girths['severity'] == 'warn'


def test_the_contested_breadth_has_a_one_sided_band_and_a_provenance_class():
    adonis = FX._breadth_gates()[2]
    assert adonis['band'] == {'lo': 1.618, 'hi': None}
    assert adonis['provenance_class'] == 'CONTESTED'


# ── the integrity tier: the two halves and their order ───────────────────────


def test_the_judged_half_holds_the_absent_status_and_the_undeclared_provenance():
    rows = FX._integrity_gates_judged()
    by_id = {r['id']: r for r in rows}
    assert by_id['watertight']['status'] is None
    assert 'source' not in by_id['gate_without_provenance']
    assert by_id['volume_height_index']['status'] == 'missing'
    assert by_id['volume_height_index']['band'] is None


def test_the_unrecognised_severity_still_carries_a_failing_status():
    sisect = next(r for r in FX._integrity_gates_judged() if r['id'] == 'no_self_intersection')
    assert sisect['severity'] == 'catastrophic'
    assert sisect['status'] == 'fail'


def test_the_disclosed_half_separates_the_crash_from_the_replaced_verdict():
    rows = FX._integrity_gates_disclosed()
    crashed = next(r for r in rows if r['id'] == 'shell_containment')
    replaced = next(r for r in rows if r['id'] == 'patellar_ligament_provenance')
    assert crashed['status'] == replaced['status'] == 'error'
    assert crashed['crashed'] is True
    assert replaced['crashed'] is False
    assert replaced['detail']['gate_ran_and_produced_a_verdict'] is True
    assert replaced['detail']['status_the_gate_would_have_returned'] == 'fail'


def test_the_disclosed_half_ends_with_the_entry_that_is_not_a_gate_at_all():
    rows = FX._integrity_gates_disclosed()
    assert isinstance(rows[-1], str)
    assert [r for r in rows if not isinstance(r, dict)] == ['this string is not a gate at all']


def test_the_unrun_blocking_gate_cannot_manufacture_a_failure():
    unrun = next(r for r in FX._integrity_gates_disclosed() if r['id'] == 'volume_plausibility')
    assert unrun['status'] == 'not_applicable'
    assert unrun['severity_declared'] == 'block'
    assert unrun['band'] is None


def test_the_integrity_tier_is_the_judged_rows_then_the_disclosed_rows():
    assert _ids(FX._integrity_gates()) == _ids(FX._integrity_gates_judged()) + _ids(FX._integrity_gates_disclosed())


# ── the orchestrator assembles exactly those sections ────────────────────────


def test_contract_fixture_is_labelled_synthetic_and_echoes_its_arguments():
    doc = FX.contract_fixture(character='abel', sex='female')
    assert doc['synthetic'] is True
    assert (doc['character'], doc['sex']) == ('abel', 'female')
    assert doc['generated']


def test_contract_fixture_tiers_are_the_section_helpers_verbatim():
    doc = FX.contract_fixture()
    assert list(doc['tiers']) == ['frame', 'heights', 'breadths', 'integrity']
    assert _ids(doc['tiers']['frame']) == _ids(FX._frame_gates())
    assert _ids(doc['tiers']['heights']) == _ids(FX._height_gates())
    assert _ids(doc['tiers']['breadths']) == _ids(FX._breadth_gates())
    assert _ids(doc['tiers']['integrity']) == _ids(FX._integrity_gates())
    assert doc['severity_calibration'] == FX._severity_calibration()


def test_every_gate_the_calibration_names_appears_in_a_tier():
    doc = FX.contract_fixture()
    in_tiers = {g['id'] for rows in doc['tiers'].values() for g in rows if isinstance(g, dict)}
    for row in doc['severity_calibration']['rows']:
        assert row['id'] in in_tiers
