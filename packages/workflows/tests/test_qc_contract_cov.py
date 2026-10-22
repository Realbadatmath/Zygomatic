# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Coverage companion to tests/test_qc_contract.py.

The invariant tests next door state the rules; this file walks the code paths
they never reach — the on-disk ladder state (load_config/write_config/set_mode),
the admin views (mode_for_gate_name, registry_table), and the defensive
branches every public call in qc_contract promises ("importing this must never
be able to break a render").

Nothing here touches the real qc_gates.json: an autouse fixture redirects the
module's own _CONFIG_PATH into tmp_path and clears the mtime cache around every
test.

    python3 -m pytest tests/test_qc_contract_cov.py -q
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import qc_contract as qc  # noqa: E402


@pytest.fixture(autouse=True)
def _config_in_tmp(tmp_path, monkeypatch):
    """Every test in this file gets its own, initially absent, qc_gates.json."""
    monkeypatch.setattr(qc, '_CONFIG_PATH', str(tmp_path / 'runtime' / 'qc_gates.json'))
    monkeypatch.delenv('ZYG_QC_ENFORCE', raising=False)
    monkeypatch.delenv('ZYG_QC_STRICT_REGIME', raising=False)
    qc._cfg_cache['mtime'] = None
    qc._cfg_cache['data'] = None
    yield
    # Leave no cached view of the tmp file behind for the next test file.
    qc._cfg_cache['mtime'] = None
    qc._cfg_cache['data'] = None


def _write_raw(text):
    os.makedirs(os.path.dirname(qc._CONFIG_PATH), exist_ok=True)
    with open(qc._CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(text)


# ── QCBlocked: a control-flow signal that carries its evidence ──────────────
def test_qc_blocked_carries_the_verdict_and_the_gates():
    verdict = {'blocked': True, 'blocking_failures': ['region_flow:abel_hand']}
    exc = qc.QCBlocked('region_flow:abel_hand FAILED at mode=block', verdict, ['region_flow'])
    assert str(exc) == 'region_flow:abel_hand FAILED at mode=block'
    assert exc.verdict == verdict
    assert exc.gates == ['region_flow']
    # Derived from BaseException on purpose: a bare `except Exception` fail-safe
    # handler must not be able to turn a deliberate block back into a shrug.
    assert not isinstance(exc, Exception)
    with pytest.raises(qc.QCBlocked):
        raise exc


def test_qc_blocked_defaults_to_an_empty_verdict():
    exc = qc.QCBlocked('no detail')
    assert exc.verdict == {}
    assert exc.gates == []


# ── GateContract ────────────────────────────────────────────────────────────
def test_gate_contract_as_dict_exposes_every_slot():
    c = qc.GATE_CONTRACTS['region_flow:']
    d = c.as_dict()
    assert set(d) == set(qc.GateContract.__slots__)
    assert d['name'] == 'region_flow'
    assert d['detects'] == ['frozen-motion']
    assert d['blind_to'] == ['motion-jitter', 'prop-morph', 'identity-drift']
    assert d['regime'] == {'measured_on': 'pre-fx intermediate'}
    assert d['noise_floor'] == 0.06
    assert d['default_mode'] == qc.BLOCK
    # a copy, not the live tuple/dict
    d['detects'].append('audio-loss')
    d['regime']['measured_on'] = 'nonsense'
    assert c.detects == ('frozen-motion',)
    assert c.regime == {'measured_on': 'pre-fx intermediate'}


def test_a_bogus_default_mode_falls_back_to_shadow():
    assert qc.GateContract('x', default_mode='block').default_mode == qc.BLOCK
    assert qc.GateContract('x', default_mode='YOLO').default_mode == qc.SHADOW
    assert qc.GateContract('x', default_mode=None).default_mode == qc.SHADOW


# ── load_config: the ladder state on disk ───────────────────────────────────
def test_missing_config_is_the_default_config():
    assert not os.path.exists(qc._CONFIG_PATH)
    assert qc.load_config() == qc.DEFAULT_CONFIG


def test_load_config_merges_over_the_defaults_and_caches_on_mtime():
    _write_raw(json.dumps({'mode': qc.BLOCK, 'gates': {'region_churn': 'block'}}))
    cfg = qc.load_config(force=True)
    assert cfg['mode'] == qc.BLOCK
    assert cfg['gates'] == {'region_churn': 'block'}
    # keys absent from the file still come from DEFAULT_CONFIG
    assert cfg['enforce'] is True
    assert cfg['_comment'] == qc.DEFAULT_CONFIG['_comment']
    # second read is the cached object, not a re-parse
    assert qc.load_config() is cfg
    # a new mtime invalidates it
    qc._cfg_cache['mtime'] = None
    assert qc.load_config() is not cfg
    assert qc.load_config()['gates'] == {'region_churn': 'block'}


def test_a_missing_gates_key_still_yields_a_dict():
    _write_raw(json.dumps({'mode': qc.SHADOW, 'gates': None}))
    assert qc.load_config(force=True)['gates'] == {}


@pytest.mark.parametrize(
    'raw',
    [
        '[1, 2, 3]',  # valid JSON, wrong shape
        '"a string"',
        'null',
        '{not json at all',
        '',
    ],
    ids=['list', 'string', 'null', 'broken', 'empty'],
)
def test_an_unusable_config_file_never_raises(raw):
    """'importing this must never be able to break a render.'"""
    _write_raw(raw)
    assert qc.load_config(force=True) == qc.DEFAULT_CONFIG


def test_an_unreadable_config_path_is_the_default_config(tmp_path, monkeypatch):
    # a directory where a file is expected: os.stat succeeds, open() does not
    weird = tmp_path / 'a_directory.json'
    weird.mkdir()
    monkeypatch.setattr(qc, '_CONFIG_PATH', str(weird))
    assert qc.load_config(force=True) == qc.DEFAULT_CONFIG


# ── effective_check_name ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('check', 'expected'),
    [
        (None, ''),
        ('', ''),
        ('region_flow:abel_hand', 'region_flow:abel_hand'),
        (17, '17'),
    ],
)
def test_effective_check_name_tolerates_a_non_dict(check, expected):
    assert qc.effective_check_name(check) == expected


def test_a_nameless_check_dict_routes_nowhere():
    assert qc.effective_check_name({'ok': False}) == ''
    assert qc.contract_for({'ok': False}) is None


# ── mode_for: precedence of the ladder ──────────────────────────────────────
def test_an_explicit_entry_by_contract_name_wins_over_the_contract_default():
    _write_raw(json.dumps({'gates': {'region_flow': qc.WARN}}))
    qc.load_config(force=True)
    assert qc.GATE_CONTRACTS['region_flow:'].default_mode == qc.BLOCK
    assert qc.mode_for('region_flow:abel_hand') == qc.WARN


def test_a_garbage_mode_in_the_file_falls_back_to_the_contract_default():
    _write_raw(json.dumps({'gates': {'region_flow': 'LOUDLY'}}))
    qc.load_config(force=True)
    assert qc.mode_for('region_flow:abel_hand') == qc.BLOCK


def test_an_entry_keyed_by_raw_prefix_is_honoured_too():
    # 'motion:' is not a contract NAME (that is 'motion'), so this can only be
    # matched by the raw-prefix pass.
    _write_raw(json.dumps({'gates': {'motion:': qc.BLOCK, 'exposure:': 'nope'}}))
    qc.load_config(force=True)
    assert qc.mode_for('motion:global') == qc.BLOCK
    # an invalid mode on a prefix entry is ignored, not promoted
    assert qc.mode_for('exposure:clip') == qc.SHADOW


def test_the_global_default_cannot_promote_an_unregistered_gate():
    """No contract -> no authority: only a named entry can raise a gate with no
    contract, never the global default."""
    _write_raw(json.dumps({'mode': qc.BLOCK, 'gates': {'another_gate': qc.BLOCK}}))
    qc.load_config(force=True)
    assert qc.contract_for('brand_new:thing') is None
    assert qc.mode_for('brand_new:thing') == qc.SHADOW
    # an operator who names the gate explicitly is taken at their word
    assert qc.mode_for('another_gate:thing') == qc.BLOCK


# ── mode_for_gate_name: the admin view ──────────────────────────────────────
@pytest.mark.parametrize(
    ('gate', 'expected'),
    [
        ('region_flow', qc.BLOCK),
        ('region_churn', qc.WARN),
        ('region_flow_keep', qc.SHADOW),
        ('track_path', qc.SHADOW),
        ('no_such_gate', qc.SHADOW),
    ],
)
def test_mode_for_gate_name_reads_the_registry_default(gate, expected):
    assert qc.mode_for_gate_name(gate) == expected


def test_mode_for_gate_name_prefers_an_explicit_entry():
    _write_raw(json.dumps({'gates': {'track_path': qc.WARN, 'region_flow': 'SHOUT'}}))
    qc.load_config(force=True)
    assert qc.mode_for_gate_name('track_path') == qc.WARN
    # an unusable mode is not an entry: fall through to the contract default
    assert qc.mode_for_gate_name('region_flow') == qc.BLOCK


# ── classification / coverage defences ──────────────────────────────────────
@pytest.mark.parametrize('check', [None, 'region_flow:abel', 42, ['ok'], object()])
def test_classify_calls_a_non_dict_unknown(check):
    assert qc.classify(check) == qc.UNKNOWN


def test_split_checks_sorts_a_mixed_run():
    checks = [
        {'check': 'motion:a', 'ok': True},
        {'check': 'motion:b', 'ok': False},
        {'check': 'motion:c', 'ok': None},
        'not a check at all',
    ]
    passes, fails, unknowns = qc.split_checks(checks)
    assert [c['check'] for c in passes] == ['motion:a']
    assert [c['check'] for c in fails] == ['motion:b']
    assert len(unknowns) == 2


def test_coverage_skips_checks_from_unregistered_gates():
    cov = qc.coverage([{'check': 'brand_new:thing', 'ok': False}])
    assert set(cov) == set(qc.DEFECT_TAXONOMY)
    assert all(row['status'] == 'uncovered' for row in cov.values())
    assert all(row['gates'] == [] for row in cov.values())


def test_a_blind_gate_is_recorded_without_covering_the_class():
    cov = qc.coverage([{'check': 'hand_count', 'ok': True}])
    # hand_count detects AND is blind_to 'anatomy' — it says so in its contract.
    assert cov['anatomy']['gates'] == ['hand_count']
    assert cov['anatomy']['blind_gates'] == ['hand_count']
    # repeated checks from the same gate are not double-counted
    cov2 = qc.coverage([{'check': 'hand_count', 'ok': True}, {'check': 'hand_count', 'ok': False}])
    assert cov2['anatomy']['gates'] == ['hand_count']
    assert cov2['anatomy']['blind_gates'] == ['hand_count']


def test_unknown_classes_lists_the_gates_that_refused_to_decide():
    checks = [{'check': 'eye_openness', 'ok': True, 'note': 'skipped: no faces'}]
    assert qc.unknown_classes(checks) == ['eyelid-aperture']
    assert 'eyelid-aperture' not in qc.uncovered_classes(checks)


# ── enforcement ─────────────────────────────────────────────────────────────
def test_a_warn_gate_failure_warns_and_does_not_block():
    """prop_consistency is held at warn: its fixed 0.70 floor fails the final
    seam of every 20s clip, which is a property of the model, not a defect."""
    fail = {'check': 'prop_ncc:book', 'ok': False, 'value': 0.42}
    assert qc.mode_for(fail) == qc.WARN
    assert qc.warning_failures([fail]) == [fail]
    assert qc.blocking_failures([fail]) == []
    # a pass and an unknown from the same gate are neither
    assert qc.warning_failures([{'check': 'prop_ncc:book', 'ok': True}]) == []
    assert qc.warning_failures([{'check': 'prop_ncc:book', 'ok': None}]) == []


def test_evaluate_reports_warnings_blocks_and_a_coverage_score():
    checks = [
        {'check': 'region_flow:abel_hand', 'ok': False, 'fail_kind': 'frozen'},
        {'check': 'prop_ncc:book', 'ok': False},
        {'check': 'motion:global', 'ok': True},
        {'check': 'eye_openness', 'ok': None},
    ]
    v = qc.evaluate(checks)
    assert v['passed_checks'] == 1
    assert v['failed_checks'] == 2
    assert v['unknown_checks'] == 1
    assert v['blocking_failures'] == ['region_flow:abel_hand']
    assert v['warning_failures'] == ['prop_ncc:book']
    assert v['blocked'] is True
    assert v['enforcement'] is True
    assert v['coverage']['frozen-motion'] == 'covered'
    assert v['coverage']['eyelid-aperture'] == 'unknown'
    assert 'texture-collapse' in v['uncovered_classes']
    assert v['unknown_classes'] == ['eyelid-aperture']
    assert 0.0 < v['coverage_score'] < 1.0
    assert v['coverage_score'] == round(v['coverage_score'], 3)


def test_evaluate_of_an_empty_run_is_not_blocked_but_covers_nothing():
    v = qc.evaluate(None)
    assert v['passed_checks'] == v['failed_checks'] == v['unknown_checks'] == 0
    assert v['blocked'] is False
    assert v['coverage_score'] == 0.0
    assert 'qc-broken' not in v['uncovered_classes']


def test_the_file_can_disable_enforcement_without_touching_gate_modes():
    _write_raw(json.dumps({'enforce': False, 'gates': {}}))
    qc.load_config(force=True)
    assert qc.enforcement_enabled() is False
    v = qc.evaluate([{'check': 'region_flow:abel_hand', 'ok': False, 'fail_kind': 'frozen'}])
    assert v['blocking_failures'] == ['region_flow:abel_hand']
    assert v['blocked'] is False


# ── rule 3: regime parity ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('name', 'actual'),
    [
        ('brand_new:thing', {'context_windows': False}),  # unregistered: nothing to compare
        ('motion:global', {'context_windows': False}),  # registered, declares no regime
        ('region_flow:abel_hand', None),  # nothing measured
    ],
)
def test_assert_regime_passes_when_there_is_no_calibration_to_violate(name, actual):
    assert qc.assert_regime(name, actual) is True


def test_the_prose_regime_keys_are_documentation_not_assertions():
    """measured_on/requires describe the regime for a human; comparing a run's
    free text against them would raise on every real report."""
    actual = {'measured_on': 'the final clip', 'requires': 'nothing'}
    assert qc.assert_regime('prop_ncc:book', actual) is True


def test_a_regime_mismatch_can_be_reported_instead_of_raised(monkeypatch):
    monkeypatch.setitem(
        qc.GATE_CONTRACTS,
        '_cov_regime_probe:',
        qc.GateContract('_cov_regime_probe', regime={'context_windows': True, 'measured_on': 'probe'}),
    )
    msg = qc.assert_regime('_cov_regime_probe:x', {'context_windows': False}, strict=False)
    assert isinstance(msg, str)
    assert 'context_windows=False expected True' in msg
    assert 'TEST defect' in msg
    # strict=None consults the env, which defaults to strict
    monkeypatch.setenv('ZYG_QC_STRICT_REGIME', '0')
    assert isinstance(qc.assert_regime('_cov_regime_probe:x', {'context_windows': False}), str)
    monkeypatch.setenv('ZYG_QC_STRICT_REGIME', '1')
    with pytest.raises(qc.RegimeMismatch):
        qc.assert_regime('_cov_regime_probe:x', {'context_windows': False})
    # a key the run never recorded cannot mismatch
    assert qc.assert_regime('_cov_regime_probe:x', {'something_else': 1}) is True


def test_the_regime_probe_is_gone_after_its_test():
    assert '_cov_regime_probe:' not in qc.GATE_CONTRACTS


# ── rule 5: adjudication ────────────────────────────────────────────────────
def test_quorum_normalises_raw_truthiness_and_none():
    v = qc.quorum([True, 1, 'yes', None, 0])
    assert v['tally'] == {qc.PASS: 3, qc.FAIL: 1, qc.UNKNOWN: 1}
    assert v['verdict'] == qc.PASS
    assert v['confidence'] == 0.75
    assert v['low_confidence'] is True


@pytest.mark.parametrize('votes', [None, (), [None, None], [qc.UNKNOWN]])
def test_no_decided_witness_manufactures_no_verdict(votes):
    v = qc.quorum(votes)
    assert v['verdict'] == qc.UNKNOWN
    assert v['confidence'] == 0.0
    assert v['escalate'] is True
    assert 'low_confidence' not in v


def test_more_abstentions_than_votes_escalates_even_when_unanimous():
    v = qc.quorum([qc.FAIL, None, None])
    assert v['verdict'] == qc.FAIL
    assert v['confidence'] == 1.0
    assert v['low_confidence'] is False
    assert v['escalate'] is True


# ── rule 4: the control arm ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('prop', 'static', 'expected'),
    [
        (0.39, 0.305, 0.085),
        ('0.5', '0.25', 0.25),
        (0.3, 0.395, -0.095),
    ],
)
def test_background_referencing_is_a_difference_not_a_score(prop, static, expected):
    assert qc.background_referenced(prop, static) == expected


@pytest.mark.parametrize(('prop', 'static'), [(None, 0.3), (0.3, None), ('n/a', 0.3), ({}, [])])
def test_background_referencing_refuses_to_invent_a_number(prop, static):
    assert qc.background_referenced(prop, static) is None


@pytest.mark.parametrize(
    ('density', 'usable'),
    [
        (0.02, True),
        (0.09, True),
        ('0.5', True),
        (0.0165, False),  # bg_top: fake 'signal' from pure noise
        (0.0, False),
        (None, False),
        ('', False),
        ('lots', False),
    ],
)
def test_usable_control_box_needs_real_edges(density, usable):
    assert qc.usable_control_box(density) is usable


# ── admin helpers ───────────────────────────────────────────────────────────
def test_write_config_then_set_mode_round_trip_through_disk():
    assert not os.path.exists(qc._CONFIG_PATH)
    qc.write_config({'mode': qc.WARN, 'enforce': True, 'gates': {'track_path': qc.SHADOW}})
    assert os.path.exists(qc._CONFIG_PATH)
    # written atomically: the temp file does not survive
    assert not os.path.exists(qc._CONFIG_PATH + '.tmp')
    with open(qc._CONFIG_PATH, 'r', encoding='utf-8') as f:
        on_disk = json.load(f)
    assert on_disk == {'mode': qc.WARN, 'enforce': True, 'gates': {'track_path': qc.SHADOW}}

    cfg = qc.set_mode('region_churn', qc.BLOCK)
    assert cfg['gates'] == {'track_path': qc.SHADOW, 'region_churn': qc.BLOCK}
    # the cache was refreshed by the write, so the new mode is live at once
    assert qc.mode_for_gate_name('region_churn') == qc.BLOCK
    assert qc.mode_for('region_churn:bg') == qc.BLOCK
    assert qc.load_config()['gates']['region_churn'] == qc.BLOCK


def test_set_mode_promotes_a_gate_even_with_no_file_yet():
    qc.set_mode('region_flow_keep', qc.WARN)
    assert qc.load_config()['gates'] == {'region_flow_keep': qc.WARN}
    assert qc.load_config()['mode'] == qc.DEFAULT_CONFIG['mode']


@pytest.mark.parametrize('mode', ['', 'blocked', 'BLOCK', None, 1])
def test_set_mode_refuses_a_rung_that_is_not_on_the_ladder(mode):
    with pytest.raises(ValueError, match='mode must be one of'):
        qc.set_mode('region_flow', mode)
    assert not os.path.exists(qc._CONFIG_PATH)


def test_registry_table_lists_every_gate_sorted_by_name():
    rows = qc.registry_table()
    assert len(rows) == len(qc.GATE_CONTRACTS)
    assert [r['gate'] for r in rows] == sorted(r['gate'] for r in rows)
    assert set(rows[0]) == {'gate', 'prefix', 'mode', 'default', 'detects', 'blind_to', 'calibrated_on'}
    by_gate = {r['gate']: r for r in rows}
    flow = by_gate['region_flow']
    assert flow['prefix'] == 'region_flow:'
    assert flow['mode'] == qc.BLOCK
    assert flow['default'] == qc.BLOCK
    assert flow['detects'] == 'frozen-motion'
    assert flow['blind_to'] == 'motion-jitter, prop-morph, identity-drift'
    assert flow['calibrated_on'] == 3
    # a gate that detects nothing says so with a dash, not an empty string
    keep = by_gate['region_flow_keep']
    assert keep['detects'] == '-'
    assert keep['calibrated_on'] == 0


def test_registry_table_shows_the_live_mode_not_only_the_default():
    qc.set_mode('track_path', qc.BLOCK)
    by_gate = {r['gate']: r for r in qc.registry_table()}
    assert by_gate['track_path']['mode'] == qc.BLOCK
    assert by_gate['track_path']['default'] == qc.SHADOW


def test_gated_and_ungated_classes_partition_the_taxonomy():
    gated = qc.gated_classes()
    ungated = set(qc.ungated_classes())
    assert gated & ungated == set()
    assert ungated | (gated & set(qc.DEFECT_TAXONOMY)) == set(qc.DEFECT_TAXONOMY)
    assert {'texture-collapse', 'style-collapse', 'audio-loss'} <= ungated
    assert 'frozen-motion' in gated
