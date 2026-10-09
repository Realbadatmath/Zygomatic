#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the QC authority layer.

These do not depend on any run: they are the rules themselves. Every one of them
encodes a failure that already cost GPU time or shipped a bad render.

    python3 -m pytest tests/test_qc_contract.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import qc_contract as qc  # noqa: E402


# ── rule 1: three verdicts, not two ─────────────────────────────────────────
def test_none_is_unknown_not_fail():
    assert qc.classify({'check': 'x', 'ok': None}) == qc.UNKNOWN


def test_skipped_check_is_unknown_even_when_ok_is_true():
    """pipeline_debug.py:520 recorded a crashed tracker as {'ok': True,
    'note': 'skipped: ...'} — a gate that could not look reporting green."""
    c = {'check': 'track', 'ok': True, 'note': 'skipped: boom'}
    assert qc.classify(c) == qc.UNKNOWN


def test_explicit_no_coverage_is_unknown():
    """'An ink PASS means no-coverage (measured 0/7 recall), not clean.'"""
    assert qc.classify({'check': 'ink', 'ok': True, 'measured': False}) == qc.UNKNOWN
    assert qc.classify({'check': 'ink', 'ok': True, 'coverage': 0}) == qc.UNKNOWN


def test_real_pass_and_fail_still_work():
    assert qc.classify({'check': 'x', 'ok': True}) == qc.PASS
    assert qc.classify({'check': 'x', 'ok': False}) == qc.FAIL


def test_unknown_never_counts_as_a_blocking_failure():
    checks = [{'check': 'region_flow:a_hand', 'ok': None, 'note': 'skipped: no clip'}]
    assert qc.blocking_failures(checks) == []


# ── the ladder ──────────────────────────────────────────────────────────────
def test_unregistered_gate_enters_at_shadow():
    """A gate nobody has written a contract for has not earned authority.
    This is what makes 'new gates enter at shadow' automatic rather than a
    convention someone has to remember."""
    assert qc.mode_for('some_brand_new_gate:thing') == qc.SHADOW


def test_keep_region_can_never_block():
    """A keep/pin region is STATIC BY DESIGN. Measuring it for aliveness failed
    in 10 of 14 recorded runs including known-good ones."""
    assert qc.mode_for('region_flow:keep:mask_pin2') == qc.SHADOW
    c = {'check': 'region_flow:keep:mask_pin2', 'ok': False, 'flow_mean': 0.01}
    assert qc.blocking_failures([c]) == []


def test_frozen_half_blocks_churn_half_does_not():
    """qc_region_flow emits ONE name for TWO defect classes with different
    calibration maturity. The frozen half separates 4.5x across its threshold;
    the churn half fires at 0.553 against a 0.55 floor."""
    frozen = {'check': 'region_flow:a_hand', 'ok': False, 'fail_kind': 'frozen', 'flow_mean': 0.08}
    churn = {'check': 'region_flow:pipe', 'ok': False, 'fail_kind': 'churn', 'flow_mean': 0.936, 'churn_p95': 0.553}
    assert qc.mode_for(frozen) == qc.BLOCK
    assert qc.mode_for(churn) == qc.WARN
    assert [c['check'] for c in qc.blocking_failures([frozen, churn])] == ['region_flow:a_hand']


def test_frozen_churn_split_works_on_historical_records_without_fail_kind():
    """The 56 reports already on disk predate fail_kind; routing must fall back
    to the note text or the corpus replays wrong."""
    churn = {
        'check': 'region_flow:pipe',
        'ok': False,
        'churn_p95': 0.553,
        'note': 'edge churn p95 0.55 > 0.55 — structure re-drawn (morph/boil)',
    }
    assert qc.effective_check_name(churn).startswith('region_churn:')
    frozen = {
        'check': 'region_flow:a_hand',
        'ok': False,
        'flow_mean': 0.08,
        'note': 'flow 0.08 px/sample < 0.12 — region FROZEN',
    }
    assert qc.effective_check_name(frozen).startswith('region_flow:')


def test_enforcement_kill_switch(monkeypatch):
    """The one switch to pull in an incident."""
    c = {'check': 'region_flow:a_hand', 'ok': False, 'fail_kind': 'frozen'}
    monkeypatch.setenv('ZYG_QC_ENFORCE', '0')
    assert qc.enforcement_enabled() is False
    assert qc.evaluate([c])['blocked'] is False
    monkeypatch.setenv('ZYG_QC_ENFORCE', '1')
    assert qc.evaluate([c])['blocked'] is True


# ── rule 2: coverage is part of the verdict ─────────────────────────────────
def test_a_run_with_no_checks_covers_nothing():
    cov = qc.coverage([])
    assert all(v['status'] == 'uncovered' for v in cov.values())
    assert qc.evaluate([])['coverage_score'] == 0.0


def test_uncovered_class_is_reported_not_silently_green():
    """'eyelid-aperture' sat uncovered for six renders while every gate measured
    motion — which is ANTI-CORRELATED with it."""
    checks = [{'check': 'region_flow:a_hand', 'ok': True, 'flow_mean': 0.3}]
    ev = qc.evaluate(checks)
    assert ev['failed_checks'] == 0
    assert 'eyelid-aperture' in ev['uncovered_classes']


def test_a_gate_that_ran_but_could_not_decide_is_unknown_coverage():
    checks = [{'check': 'eye_openness:abel', 'ok': None, 'note': 'no faces found'}]
    assert 'eyelid-aperture' in qc.unknown_classes(checks)
    assert 'eyelid-aperture' not in qc.uncovered_classes(checks)


def test_permanently_ungated_classes_are_declared():
    """Honesty check: these have NO gate anywhere. If someone adds one, this
    test fails and forces the list to be updated rather than quietly forgotten."""
    assert set(qc.ungated_classes()) == {'texture-collapse', 'style-collapse', 'audio-loss'}


def test_identity_gate_declares_its_provenance_blindness():
    """The blindness that hid 65/67 wrong characters: identity QC scores a render
    against ITS OWN anchor, so a wrong-but-consistent asset is green."""
    c = qc.contract_for('identity:abel')
    assert 'identity-provenance' in c.blind_to
    checks = [{'check': 'identity:abel', 'ok': True, 'sim': 0.9}]
    assert 'identity-provenance' in qc.uncovered_classes(checks)


# ── rule 3: regime parity ───────────────────────────────────────────────────
def test_regime_mismatch_raises_as_a_test_error():
    """generate_vace_with_probe forced context_windows=False, measured itself
    instead of the subject, and blocked two good renders (32 min lost)."""
    qc.GATE_CONTRACTS['_regime_probe:'] = qc.GateContract(
        '_regime_probe', detects=('frozen-motion',), regime={'context_windows': True}
    )
    try:
        with pytest.raises(qc.RegimeMismatch):
            qc.assert_regime('_regime_probe:x', {'context_windows': False})
        assert qc.assert_regime('_regime_probe:x', {'context_windows': True}) is True
    finally:
        qc.GATE_CONTRACTS.pop('_regime_probe:', None)


# ── rule 4: control arm ─────────────────────────────────────────────────────
def test_background_referencing_flips_a_flattering_raw_number():
    """A wall that CANNOT MOVE scored 0.305-0.395 — at or above the book on every
    clip. Background-referenced, the plate-ON book is WORSE, not better."""
    assert qc.background_referenced(0.258, 0.395) < 0
    assert qc.background_referenced(0.317, 0.305) > 0


def test_low_edge_density_boxes_are_refused():
    """bg_l at 2.5% and bg_top at 1.65% both produced fake 'signal'."""
    assert qc.usable_control_box(0.025) is True
    assert qc.usable_control_box(0.0165) is False


# ── rule 5: adjudication ────────────────────────────────────────────────────
def test_split_witnesses_escalate_instead_of_resolving():
    r = qc.quorum([qc.PASS, qc.FAIL])
    assert r['verdict'] == qc.UNKNOWN and r['escalate'] is True


def test_majority_wins_but_is_flagged_low_confidence():
    r = qc.quorum([qc.PASS, qc.PASS, qc.FAIL])
    assert r['verdict'] == qc.PASS
    assert r['low_confidence'] is True and r['escalate'] is True


def test_unanimous_is_confident_and_final():
    r = qc.quorum([qc.FAIL, qc.FAIL, qc.FAIL])
    assert r['verdict'] == qc.FAIL and r['confidence'] == 1.0
    assert r['escalate'] is False


def test_all_unknown_witnesses_do_not_manufacture_a_verdict():
    r = qc.quorum([qc.UNKNOWN, qc.UNKNOWN, qc.UNKNOWN])
    assert r['verdict'] == qc.UNKNOWN and r['escalate'] is True
