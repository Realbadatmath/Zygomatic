# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SHADOW gates must not flip verdict.ok (2026-09-03).

qc_contract puts every unregistered gate in shadow — 'measure, record, never
surface as a blocker' — but DebugRun.finish() used to count every FAIL, so a
shadow gate's failure still set verdict['ok'] = False. That is why the identity
gate was kept out of out['checks'] entirely. These tests pin the split.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import pipeline_debug  # noqa: E402
from zyg_workflows import qc_contract  # noqa: E402


@pytest.fixture()
def keep_run_id_env():
    """DebugRun.__init__ exports ZYG_RUN_ID into os.environ (pipeline_debug.py:139-147)."""
    prev = os.environ.get('ZYG_RUN_ID')
    yield
    if prev is None:
        os.environ.pop('ZYG_RUN_ID', None)
    else:
        os.environ['ZYG_RUN_ID'] = prev


def _run_with(tmp_path, checks, name='t'):
    run = pipeline_debug.DebugRun(str(tmp_path), name=name)
    run.doc['qc'].append({'checks': list(checks)})
    return run


def test_shadow_fail_does_not_flip_ok(tmp_path, keep_run_id_env):
    """identity_clip is unregistered -> shadow -> recorded, never a blocker."""
    chk = {'check': 'identity_clip', 'ok': False, 'cosine': 0.1}
    assert qc_contract.classify(chk) == qc_contract.FAIL
    assert qc_contract.mode_for('identity_clip') == qc_contract.SHADOW

    verdict = _run_with(tmp_path, [chk]).finish()
    assert verdict['ok'] is True
    assert verdict['shadow_failed'] == 1
    assert verdict['shadow_failed_checks'] == ['identity_clip']
    assert verdict['failed_checks'] == 0


def test_non_shadow_fail_still_flips_ok(tmp_path, keep_run_id_env):
    """A FAIL on a gate above shadow keeps its authority."""
    name = next((p for p in qc_contract.GATE_CONTRACTS if qc_contract.mode_for(p) == qc_contract.WARN), None)
    assert name is not None, 'no warn-mode gate in the registry'
    chk = {'check': name, 'ok': False}
    assert qc_contract.classify(chk) == qc_contract.FAIL

    verdict = _run_with(tmp_path, [chk]).finish()
    assert verdict['ok'] is False
    assert verdict['failed_checks'] == 1
    assert verdict['shadow_failed'] == 0


def test_block_mode_fail_still_raises(tmp_path, keep_run_id_env):
    """The block ladder rung is untouched by the split."""
    name = next((p for p in qc_contract.GATE_CONTRACTS if qc_contract.mode_for(p) == qc_contract.BLOCK), None)
    if name is None or not qc_contract.enforcement_enabled():
        pytest.skip('no block-mode gate enabled in this config')
    run = _run_with(tmp_path, [{'check': name, 'ok': False}])
    with pytest.raises(qc_contract.QCBlocked):
        run.finish()
    assert run.doc['verdict']['ok'] is False


def test_legacy_path_unchanged(tmp_path, keep_run_id_env, monkeypatch):
    """qc_contract unavailable -> the old two-verdict behaviour: any FAIL is a fail."""
    monkeypatch.setitem(pipeline_debug._CONTRACT, 'tried', True)
    monkeypatch.setitem(pipeline_debug._CONTRACT, 'mod', None)
    verdict = _run_with(tmp_path, [{'check': 'identity_clip', 'ok': False}]).finish()
    assert verdict['ok'] is False
    assert verdict['failed_checks'] == 1
    assert verdict['shadow_failed'] == 0


def test_identity_check_promotion():
    """_identity_check turns the slim result into one shadow-bound check."""
    f = pipeline_debug.DebugRun._identity_check
    assert f(None) is None
    assert f({'ok': None, 'measured': False, 'reason': 'no chars'}) is None

    one = f(
        {
            'ok': False,
            'measured': True,
            'per_char': {'abel': {'ok': False, 'cosine': 0.21, 'cosine_p10': 0.11, 'pass_frac': 0.3, 'floor': 0.35}},
        }
    )
    assert one['check'] == 'identity_clip'
    assert one['ok'] is False and one['cosine'] == 0.21 and one['floor'] == 0.35
    assert qc_contract.classify(one) == qc_contract.FAIL, 'note must not read as a skip'
    assert qc_contract.mode_for(one['check']) == qc_contract.SHADOW

    two = f({'ok': True, 'measured': True, 'per_char': {'abel': {'cosine': 0.5}, 'cornelis': {'cosine': 0.6}}})
    assert two['ok'] is True
    assert two['chars'] == {'abel': 0.5, 'cornelis': 0.6}
    assert two['cosine'] is None


@pytest.mark.service  # gate_scores_for_run reads the run ledger, which is Postgres
def test_record_gates_marks_shadow_fail(tmp_path, keep_run_id_env, monkeypatch):
    """A shadow FAIL lands in run_ledger.gates as 'shadow_fail', not 'fail'.

    The trend loop (run_ledger.py:495-515) counts only 'pass'/'fail', so a gate
    that is merely being MEASURED no longer drags the cross-run pass-rate down.
    """
    from zyg_dashboard import run_ledger

    warn = next((p for p in qc_contract.GATE_CONTRACTS if qc_contract.mode_for(p) == qc_contract.WARN), None)
    assert warn is not None, 'no warn-mode gate in the registry'
    shadow = {'check': 'identity_clip', 'ok': False, 'cosine': 0.1}
    assert qc_contract.mode_for(shadow['check']) == qc_contract.SHADOW

    run = _run_with(tmp_path, [shadow, {'check': warn, 'ok': False}], name='gates')
    run.finish()

    gates = run_ledger.gate_scores_for_run(run.run_id)
    assert gates['identity_clip']['outcome'] == 'shadow_fail'
    assert gates[warn]['outcome'] == 'fail'
