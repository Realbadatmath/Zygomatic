# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers `_selftest_digest` was split into.

`_selftest_digest` used to be one 335-line body, so a failure told you only that "the
digest self-test failed" and the individual assertion families had never been exercised
on their own. Each family now lives in
`zyg_workflows.geom.anthro.report.selftest_rules_digest`; these tests pin the pure parts
(the gate-row builders, the clock vocabulary, the stripper/alarm invariants) with plain
inputs, and run each family that does not need the anthropometric reference pack.
"""

from __future__ import annotations

import os

import pytest

from zyg_workflows.geom.anthro.report import selftest_rules_digest as DG
from zyg_workflows.geom.anthro.report.constants import (
    _CLOCK_RESIDUE_CONTENT_KEYS,
    _COUNT_KEYS,
    _INSTRUMENTATION_KEYS,
    _NO_VERDICT,
    _VERDICT_STATUSES,
)
from zyg_workflows.geom.anthro.report.digest import (
    _digest_residue,
    _is_instrumentation_key,
    _looks_like_a_clock_key,
    _volatile_content,
    stable_sha,
)
from zyg_workflows.geom.anthro.report.document import build
from zyg_workflows.geom.anthro.report.fixture import contract_fixture
from zyg_workflows.geom.anthro.report.selftest_rules import _selftest_digest

_REFERENCE_PACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(DG.__file__))),
    'data',
    'assets',
    'anthro_reference',
    'reference.json',
)
_needs_pack = pytest.mark.skipif(
    not os.path.exists(_REFERENCE_PACK),
    reason='anthropometric reference pack absent; the percentile strip alarm costs the PASS',
)


@pytest.fixture(scope='module')
def fx():
    """The contract fixture dict the self-test is written against."""
    return contract_fixture()


@pytest.fixture(scope='module')
def doc(fx):
    """The built report document, exactly as `selftest_core` builds it."""
    return build(fx, None, name='fixture', sex='male')


# ── the gate-row builders (were inline literals inside the 335-line body) ───────────


def test_sneaky_gate_carries_both_undeclared_clock_names():
    row = DG.sneaky_gate()
    assert row['detail'] == {'probe_walltime_of_run': 0.42, 'checked_on': '2026-08-06T13:21:52'}
    assert (row['id'], row['severity'], row['status']) == ('g_clock', 'block', 'pass')


def test_sneaky_gate_returns_a_fresh_row_each_call():
    # The original handed ONE dict to two assertion families so the second saw whatever
    # `build` left behind; each call must still be independent of the last.
    a, b = DG.sneaky_gate(), DG.sneaky_gate()
    assert a == b and a is not b
    a['detail']['probe_walltime_of_run'] = 0.0
    assert DG.sneaky_gate()['detail']['probe_walltime_of_run'] == 0.42


def test_nonce_gate_slugifies_the_name_into_the_gate_id():
    assert DG.nonce_gate('created_at', 1.0)['id'] == 'g_created_at'
    assert DG.nonce_gate('elapsed ms', 1.0)['id'] == 'g_elapsed_ms'
    assert DG.nonce_gate('time-of-probe', 1.0)['id'] == 'g_time_of_probe'


def test_nonce_gate_id_is_truncated_to_twenty_slug_characters():
    row = DG.nonce_gate('gate_evaluation_wall_clock_in_milliseconds', 4.2)
    assert row['id'] == 'g_' + 'gate_evaluation_wall'
    assert len(row['id']) == 22


def test_nonce_gate_carries_the_nonce_beside_a_content_field():
    # The content field is what makes the row a sample of "a per-run value smuggled into
    # a real gate" rather than a sample of "any extra field".
    row = DG.nonce_gate('run_uuid', 'x')
    assert row['detail'] == {'run_uuid': 'x', 'n_vertices': 226}
    assert (row['observed'], row['band']) == (0.5, [0.0, 1.0])


# ── the nonce table ────────────────────────────────────────────────────────────────


def test_every_silent_before_entry_is_now_caught_by_the_residue_detector():
    # The point of the class fix: each of these used to survive the strip, raise nothing
    # and move the sha. One escapee here is one silent nonce back in the wild.
    escaped = [nm for nm, val in DG.SILENT_BEFORE if not _digest_residue({nm: val})]
    assert escaped == []


def test_three_silent_before_entries_are_caught_by_their_value_and_not_their_name():
    # "the last two need no name at all": a per-run value under a name nobody has ever
    # thought of, and a UUID. `at` is the third — a bare preposition is not a clock name,
    # so only the epoch-shaped value gives it away.
    by_value_only = sorted(nm for nm, _ in DG.SILENT_BEFORE if not _looks_like_a_clock_key(nm))
    assert by_value_only == ['at', 'marker', 'probe_ref']
    assert all(_digest_residue({nm: val}) for nm, val in DG.SILENT_BEFORE if nm in by_value_only)


def test_the_silent_before_table_still_holds_all_twenty_one_names():
    assert len(DG.SILENT_BEFORE) == 21
    assert len({nm for nm, _ in DG.SILENT_BEFORE}) == 21
    assert ('pid', 48213) in DG.SILENT_BEFORE


# ── the clock vocabulary: the live false positives it must stay quiet on ───────────


def test_content_keys_with_an_at_segment_are_not_clocks():
    # Widening the alarm to catch `created_at` by segment made it fire on English
    # prepositions inside ordinary field names — thirteen of them on every live body.
    for key in (
        'at_drive_deg',
        'max_fans_at_a_vertex',
        'gradient_max_at_wrist',
        'columella_at_+0.8962',
        'monotonic_chain_helper',
    ):
        assert not _looks_like_a_clock_key(key), key


def test_a_long_identifier_is_not_exempted_by_the_length_bail():
    # The bail is about prose (a whole citation), not about long field names.
    assert _looks_like_a_clock_key('gate_evaluation_wall_clock_in_milliseconds')
    assert not _looks_like_a_clock_key('waist_circumference_omphalion_over_stature')


def test_the_one_declared_content_clock_is_exempt_and_its_control_is_not():
    assert _looks_like_a_clock_key('first_invalidated_at')
    assert _digest_residue({'first_invalidated_at': '2026-08-06T13:21:52'}) == []
    assert _digest_residue({'second_invalidated_at': '2026-08-06T13:21:52'})


# ── volatile is the one block the digest cannot see into ───────────────────────────


def test_volatile_content_names_a_smuggled_measurement_and_ignores_clocks(doc):
    assert _volatile_content(doc['volatile']) == []
    assert _volatile_content({'ms': 1.0, 'generated': 'x'}) == []
    assert _volatile_content({'stature_m': 1.85}) == ['volatile.stature_m']


# ── the structural invariants (pure set algebra, no build) ─────────────────────────


def test_the_stripper_and_the_alarm_vocabularies_are_disjoint():
    # A key that is both stripped from the hash and exempt from the residue alarm would
    # be an invisible per-run nonce by construction.
    assert not (_INSTRUMENTATION_KEYS & _CLOCK_RESIDUE_CONTENT_KEYS)
    assert all(_is_instrumentation_key(k) for k in _INSTRUMENTATION_KEYS)
    assert not any(_is_instrumentation_key(k) for k in _CLOCK_RESIDUE_CONTENT_KEYS)


def test_the_stripper_does_not_eat_content_fields():
    for k in ('status', 'observed', 'band', 'severity', 'stature_m', 'explanation'):
        assert not _is_instrumentation_key(k), k


def test_every_status_is_either_a_verdict_or_not_one():
    assert set(_COUNT_KEYS) == set(_VERDICT_STATUSES) | set(_NO_VERDICT)


def test_assert_structural_invariants_passes_as_a_whole():
    DG.assert_structural_invariants()


# ── the fixture is armed, and the digest ignores the clock ────────────────────────


def test_the_fixture_still_carries_a_nested_wall_clock_field(doc):
    by = {g['id']: g for g in doc['gates']}
    ev = by['stature_declared_vs_built']['evidence']
    assert ev['ms'] is not None
    assert ev['per_side']['L']['ms'] is not None
    assert doc['stable_sha256'] == stable_sha(doc)
    DG.assert_fixture_is_armed(doc)


def test_the_digest_moves_with_content_and_not_with_the_clock(doc, fx):
    DG.assert_digest_ignores_the_clock(doc, fx)


def test_an_unknown_clock_name_is_reported_as_a_defect():
    DG.assert_unknown_clock_name_is_a_defect(DG.sneaky_gate())


def test_the_silent_nonce_sweep_catches_every_name():
    DG.assert_silent_nonces_are_caught()


def test_the_clock_vocabulary_stage_passes_as_a_whole():
    DG.assert_the_clock_vocabulary()


def test_the_declared_content_clock_stage_passes_as_a_whole():
    DG.assert_declared_content_clocks(DG.sneaky_gate())


# ── the stages that need the shipped reference pack ───────────────────────────────


@_needs_pack
def test_volatile_is_outside_the_digest_stage_passes_as_a_whole(doc):
    DG.assert_volatile_is_outside_the_digest(doc)


@_needs_pack
def test_the_whole_digest_selftest_still_passes(doc, fx):
    _selftest_digest(doc, fx)
