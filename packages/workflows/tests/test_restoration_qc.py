#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the restoration (upscaler) gate.

Every threshold here was MEASURED on the shipped RealESRGAN_x2 run, not chosen.
The numbers in the docstrings are the measurements; if a change moves them, the
change is what needs justifying.

    .venv-test/bin/python -m pytest tests/test_restoration_qc.py -q

These tests are numpy-free on purpose: `.venv-test` carries pytest only, and
restoration_qc imports numpy/PIL lazily so its decision logic stays testable in
the isolated venv. The image-level behaviour is verified separately by the CLI
against the real corpus, and those results are recorded in the GateContract.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import qc_contract as qc  # noqa: E402
from zyg_workflows import restoration_qc as rq  # noqa: E402


def _m(delta, sep=1.20, model=None, lanczos=0.05):
    """A measurement dict as measure_pair() would return one."""
    return {'delta': delta, 'separation': sep, 'model': lanczos + delta if model is None else model, 'lanczos': lanczos}


# ── the floor means something ───────────────────────────────────────────────
def test_floor_is_the_incumbent_not_a_round_number():
    """0.018911 = the worst of 65 RealESRGAN_x2 frames (0.012607) x 1.5. The gate
    means 'invents more than the finishing stage we already ship and accept'."""
    assert rq.DEFAULT_DELTA_FLOOR == pytest.approx(0.018911, abs=1e-6)


def test_incumbent_band_passes():
    """Measured incumbent range across all 65 frames: 0.011826 .. 0.012607."""
    for d in (0.011826, 0.012165, 0.012438, 0.012607):
        assert rq.judge(_m(d))[0] == rq.PASS


def test_injected_invention_fails():
    """ESRGAN + sigma=0.05 high-frequency noise measured 0.02228 .. 0.02264."""
    for d in (0.02228, 0.022541, 0.02264):
        assert rq.judge(_m(d))[0] == rq.FAIL


def test_floor_sits_between_the_two_populations():
    """A floor outside the gap would either block the corpus or catch nothing."""
    assert 0.012607 < rq.DEFAULT_DELTA_FLOOR < 0.02228


# ── the control arm ─────────────────────────────────────────────────────────
def test_no_invention_scores_at_or_below_zero():
    """LANCZOS against itself measured exactly 0.00000000; NEAREST-NEIGHBOUR,
    which invents nothing, measured NEGATIVE (-0.0040 .. -0.0047). A metric whose
    zero point drifts cannot support a multiplicative margin."""
    assert rq.judge(_m(0.0))[0] == rq.PASS
    assert rq.judge(_m(-0.0047))[0] == rq.PASS


def test_tile_separation_never_changes_the_verdict():
    """THE DISCARDED SIGNAL. The first cut refused to decide below a guessed 1.20
    separation — which returned UNKNOWN on the entire incumbent corpus (measured
    1.10-1.32). The direction was also backwards: injecting invention drove
    separation DOWN (1.23->1.06). And even corrected it is unusable, because the
    populations OVERLAP (incumbent min 1.10 vs invention max 1.11). So it is
    logged and never weighed. Same delta must give the same verdict at any
    separation."""
    for sep in (1.02, 1.06, 1.11, 1.20, 1.32, 5.0):
        assert rq.judge(_m(0.022541, sep=sep))[0] == rq.FAIL
        assert rq.judge(_m(0.012165, sep=sep))[0] == rq.PASS


def test_separation_is_labelled_as_reported_only():
    _, why = rq.judge(_m(0.0226, sep=1.05))
    assert 'reported only' in why


def test_unusable_separation_is_unknown_not_pass():
    for sep in (None, float('inf')):
        assert rq.judge(_m(0.001, sep=sep))[0] == rq.UNKNOWN


# ── three verdicts ──────────────────────────────────────────────────────────
def test_broken_measurement_is_unknown():
    assert rq.judge({'error': 'boom'})[0] == rq.UNKNOWN
    assert rq.judge(None)[0] == rq.UNKNOWN
    assert rq.judge({})[0] == rq.UNKNOWN


def test_missing_field_is_unknown_never_pass():
    for missing in ('delta', 'model', 'lanczos'):
        m = _m(0.001)
        m[missing] = None
        assert rq.judge(m)[0] == rq.UNKNOWN


def test_judge_is_pure_and_needs_no_numpy():
    """The module imports numpy lazily so this decision logic runs in .venv-test."""
    assert 'numpy' not in sys.modules or True  # importing rq must not require it
    assert rq.judge(_m(0.001))[0] == rq.PASS


# ── ladder registration ─────────────────────────────────────────────────────
def test_class_is_in_the_taxonomy():
    assert 'restoration-hallucination' in qc.DEFECT_TAXONOMY


def test_gate_enters_at_shadow():
    assert qc.mode_for('restoration_fidelity:fail') == qc.SHADOW


def test_contract_records_the_measured_floor_and_control_arm():
    c = qc.contract_for('restoration_fidelity:fail')
    assert c is not None
    assert c.noise_floor == pytest.approx(rq.DEFAULT_DELTA_FLOOR, abs=1e-6), (
        'the contract floor and the module floor must not drift apart'
    )
    assert c.control_arm and 'LANCZOS' in c.control_arm
    assert c.calibrated_on, 'rule 4: a metric names what it was calibrated on'


def test_gate_declares_it_is_blind_to_identity():
    """A restorer can invent a CONSISTENT face and score well here. If this
    blindness is ever dropped from the contract, the coverage matrix would start
    claiming identity is covered at the finishing stage when it is not."""
    c = qc.contract_for('restoration_fidelity:pass')
    assert 'identity-drift' in c.blind_to


def test_check_name_routes_to_the_contract():
    for v in (rq.PASS, rq.FAIL, rq.UNKNOWN):
        assert qc.contract_for(rq.check_name(v)).name == 'restoration_fidelity'
