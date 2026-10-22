# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage of the licence gate's edge paths: lineage walk, CLI, degraded registry.

tests/test_licence_provenance.py states the gate's invariants against the REAL
registry; this file drives the branches that registry never reaches — a missing or
malformed registry file, a LoRA whose base family nobody recorded, the walk up to
training_status_*.json, the ambiguous twins, the verdicts, the pause switch, the CLI.
Hermetic throughout: registries and weight trees live under tmp_path, the ledger
bridge and ComfyUI path resolution are monkeypatched, nothing reads a service or a GPU.
"""

import json
import os
import sys

import pytest

from zyg_workflows import licence_provenance as lp
from zyg_workflows import lora_attest
from zyg_workflows import paths
from zyg_workflows import run_ledger


# ── helpers ─────────────────────────────────────────────────────────────────


def _registry(tmp_path, **over):
    """Write a small but complete registry under tmp_path, return its path."""
    nc = {'licence': 'BFL-NC-2.0', 'commercial': False}
    apache = {'licence': 'Apache-2.0', 'commercial': True}
    reg = {
        'weights': [
            dict(nc, match=['flux1-dev*.safetensors'], source='ZYG_MODELS_ROOT/flux/LICENSE', note='at ZYG_FLUX_ROOT'),
            dict(apache, match=['qwen-image*.safetensors']),
            {'match': ['hunyuan*.safetensors'], 'licence': 'Tencent', 'commercial': True, 'territory_excluded': ['eu']},
        ],
        'families': {'flux': nc, 'qwen': apache, 'wan': apache, 'sdxl': {'licence': 'CreativeML-OpenRAIL-M'}},
        'lora_lineage': [
            {'match': ['wan_char_*.safetensors'], 'family': 'wan'},
            {'match': ['mystery_*.safetensors'], 'family': 'mystery'},
            {'match': ['nofamily_*.safetensors']},
            {'match': ['zygchar_*.safetensors'], 'family': 'flux'},
        ],
    }
    reg.update(over)
    p = tmp_path / 'model_licences.json'
    p.write_text(json.dumps(reg), encoding='utf-8')
    return str(p)


def _weights(tmp_path, sub, name='out.safetensors'):
    """An empty weights file at tmp_path/<sub>/<name> → (its directory, its path)."""
    d = tmp_path / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(b'')
    return d, str(d / name)


def _status_file(directory, family, lora_path=None, name=None):
    """Write one training_status_<family>.json the way lora_trainer_service does."""
    directory.mkdir(parents=True, exist_ok=True)
    body = {'char_id': 'aabbccddeeff'}
    if family is not None:
        body['model_family'] = family
    if lora_path is not None:
        body['lora_path'] = lora_path
    (directory / (name or f'training_status_{family}.json')).write_text(json.dumps(body), encoding='utf-8')


def _graph(*names):
    return {str(i): {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': n}} for i, n in enumerate(names)}


@pytest.fixture
def no_resolve(monkeypatch):
    """attest_licences must never walk the real ComfyUI model roots in a test."""
    monkeypatch.setattr(lora_attest, 'resolve_model_path', lambda name, folders=None: None)


@pytest.fixture
def no_ledger(monkeypatch):
    """Record every gate the module tries to write instead of reaching Postgres."""
    seen = []
    monkeypatch.setattr(run_ledger, 'record_gate', lambda *a, **k: seen.append((a, k)) or True)
    return seen


@pytest.fixture
def tmp_lora_roots(monkeypatch, tmp_path):
    """Point the char-id fallback at an empty tmp tree, never at the real disk."""
    root = tmp_path / 'lora-outputs'
    root.mkdir()
    monkeypatch.setattr(lp, '_LORA_OUTPUT_ROOTS', [str(root)])
    return root


def test_a_registry_that_cannot_be_read_loads_as_empty_and_never_raises(tmp_path):
    """Missing, not-an-object, or every section the wrong type: all read as empty."""
    (tmp_path / 'list.json').write_text('[1, 2, 3]', encoding='utf-8')
    wrong = {'weights': {}, 'families': [], 'lora_lineage': {}}
    (tmp_path / 'typed.json').write_text(json.dumps(wrong), encoding='utf-8')
    empty = {'weights': [], 'families': {}, 'lora_lineage': []}
    assert lp.load_registry('/nonexistent/zyg/model_licences.json') == empty
    assert lp.load_registry(str(tmp_path / 'list.json')) == {'weights': [], 'families': {}}
    assert lp.load_registry(str(tmp_path / 'typed.json')) == empty


def test_a_non_dict_weight_rule_survives_loading_and_is_skipped_when_matching(tmp_path):
    """_expand_roots passes junk through; _match_rule must step over it."""
    reg = lp.load_registry(
        _registry(tmp_path, weights=['not-a-rule', 42, {'match': ['qwen-image*.safetensors'], 'commercial': True}])
    )
    assert reg['weights'][:2] == ['not-a-rule', 42]
    assert lp.classify_weight('qwen-image-2.0.safetensors', registry=reg)['status'] == lp.CLEARED
    assert lp.classify_weight('unheard-of.safetensors', registry=reg)['status'] == lp.UNKNOWN


def test_provenance_prose_is_expanded_against_paths_and_plain_rules_pass_through(tmp_path):
    rule = lp.load_registry(_registry(tmp_path))['weights'][0]
    assert rule['source'] == str(paths.ZYG_MODELS_ROOT) + '/flux/LICENSE'
    assert rule['note'] == 'at ' + str(paths.ZYG_FLUX_ROOT)
    plain = {'match': ['a.safetensors'], 'licence': 'MIT', 'commercial': True}
    assert lp.load_registry(_registry(tmp_path, weights=[plain]))['weights'] == [plain]


@pytest.mark.parametrize(
    ('text', 'expected'),
    [('', ''), (None, ''), (0, ''), ('/srv/models/flux/LICENSE', '/srv/models/flux/LICENSE')],
)
def test_resolve_root_path_leaves_nothing_and_absolute_paths_alone(text, expected):
    assert lp.resolve_root_path(text) == expected


@pytest.mark.parametrize(
    ('rec', 'expected'),
    [
        (None, lp.UNKNOWN),
        ('BFL-NC-2.0', lp.UNKNOWN),
        ({'commercial': None}, lp.UNKNOWN),
        ({'commercial': False}, lp.NON_COMMERCIAL),
        ({'commercial': True, 'territory_excluded': None}, lp.CLEARED),
        ({'commercial': True, 'territory_excluded': ['CN']}, lp.CLEARED),
        ({'commercial': True, 'territory_excluded': ['eu']}, lp.TERRITORY_EXCLUDED),
        ({'commercial': False, 'territory_excluded': [' Eu ']}, lp.TERRITORY_EXCLUDED),
    ],
)
def test_record_status_maps_the_four_statuses(rec, expected):
    """Territory exclusion outranks a commercial grant: it bites without distribution."""
    assert lp._record_status(rec) == expected


# ── LoRA lineage: the walk up to training_status_*.json ─────────────────────


def test_a_lora_under_lora_weights_family_is_charged_by_its_directory(tmp_path):
    _d, w = _weights(tmp_path, 'lora-weights-flux', 'zygchar_aabbccddeeff.safetensors')
    assert lp.lora_base_families('zygchar_aabbccddeeff.safetensors', w) == (['flux'], 'weights-dir')
    assert lp.lora_base_family('zygchar_aabbccddeeff.safetensors', w) == 'flux'


def test_a_status_file_pointing_at_this_exact_file_wins(tmp_path):
    d, w = _weights(tmp_path, 'run')
    _status_file(d, 'sdxl', lora_path=w)
    assert lp.lora_base_families('out.safetensors', w) == (['sdxl'], 'lora_path-match')


def test_the_walk_climbs_three_directories_to_find_the_status_file(tmp_path):
    _d, w = _weights(tmp_path, 'top/a/b')
    _status_file(tmp_path / 'top', 'qwen', lora_path=str(tmp_path / 'top' / 'other.safetensors'))
    assert lp.lora_base_families('out.safetensors', w) == (['qwen'], 'status-dir')


def test_two_scoped_status_files_make_the_lineage_ambiguous(tmp_path):
    d, w = _weights(tmp_path, 'twins')
    _status_file(d, 'flux')
    _status_file(d, 'sdxl')
    assert lp.lora_base_families('out.safetensors', w) == (['flux', 'sdxl'], 'status-dir-ambiguous')


def test_a_status_file_with_an_unusable_lora_path_still_yields_its_family(tmp_path):
    """realpath() on a NUL-bearing path raises; _same_file must answer False, not crash."""
    d, w = _weights(tmp_path, 'nul')
    _status_file(d, 'wan', lora_path='/tmp/a\x00b.safetensors')
    assert lp.lora_base_families('out.safetensors', w) == (['wan'], 'status-dir')


def test_status_records_skips_junk_and_prefers_scoped_files_over_the_legacy_one(tmp_path):
    """training_status.json is written by whichever family trained LAST: read it last too."""
    d = tmp_path / 'legacy'
    _status_file(d, None, name='training_status_blank.json')
    (d / 'training_status_broken.json').write_text('{not json', encoding='utf-8')
    assert lp._status_records(str(d)) == []
    assert lp._status_records(str(tmp_path / 'never-made')) == []
    _status_file(d, 'flux', name='training_status.json')
    assert lp._status_records(str(d)) == [('flux', None)]
    _status_file(d, 'qwen')
    assert lp._status_records(str(d)) == [('qwen', None)]


@pytest.mark.parametrize('path', ['ghost/deeper/w.safetensors', '/w.safetensors'])
def test_a_path_with_no_status_file_anywhere_above_it_is_unresolved(tmp_path, tmp_lora_roots, path):
    """The climb must terminate on missing directories and at the filesystem root."""
    full = path if path.startswith('/') else str(tmp_path / path)
    assert lp.lora_base_families('w.safetensors', full) == ([], 'unresolved')


def test_a_registry_convention_names_the_base_but_only_when_it_names_a_family(tmp_path, tmp_lora_roots):
    """Order matters: wan_char_* must precede the broad flux rule or it is charged FLUX."""
    reg = lp.load_registry(_registry(tmp_path))
    assert lp.lora_base_families('wan_char_aabbccddeeff.safetensors', registry=reg) == (['wan'], 'registry-convention')
    assert lp.lora_base_families('nofamily_x.safetensors', registry=reg) == ([], 'unresolved')


def test_the_char_id_fallback_collects_every_family_trained_for_that_id(tmp_path, tmp_lora_roots):
    """char_id is not a lineage key: one character owns LoRAs on different bases."""
    reg = lp.load_registry(_registry(tmp_path, lora_lineage=[]))
    _status_file(tmp_lora_roots / 'aabbccddeeff', 'flux')
    assert lp.lora_base_families('zygchar_aabbccddeeff.safetensors', registry=reg) == (['flux'], 'charid')
    _status_file(tmp_lora_roots / 'aabbccddeeff', 'sdxl')
    assert lp.lora_base_families('zygchar_aabbccddeeff.safetensors', registry=reg) == (
        ['flux', 'sdxl'],
        'charid-ambiguous',
    )


def test_lora_base_family_is_none_when_lineage_cannot_be_established(tmp_lora_roots, monkeypatch):
    monkeypatch.setattr(lp, 'REGISTRY_PATH', '/nonexistent/zyg/model_licences.json')
    assert lp.lora_base_family('mystery.safetensors') is None


def test_a_lora_whose_base_family_has_no_registry_entry_is_unknown(tmp_path, tmp_lora_roots):
    """'mystery' is named by a lineage convention but nobody recorded its licence."""
    art = lp.classify_weight('mystery_abc.safetensors', kind='lora', registry=lp.load_registry(_registry(tmp_path)))
    assert (art['status'], art['base_family'], art['lineage']) == (lp.UNKNOWN, 'mystery', 'registry-convention')
    assert art['reason'] == "LoRA base family 'mystery' has no entry in registry families"


def test_an_ambiguous_lora_is_charged_with_the_worst_of_its_candidates(tmp_path):
    """ "It might be the Apache twin" is not clearance."""
    d, w = _weights(tmp_path, 'twins', 'zygchar_aabbccddeeff.safetensors')
    _status_file(d, 'flux')
    _status_file(d, 'qwen')
    reg = lp.load_registry(_registry(tmp_path))
    art = lp.classify_weight('zygchar_aabbccddeeff.safetensors', kind='lora', path=w, registry=reg)
    assert art['status'] == lp.NON_COMMERCIAL
    assert art['base_family'] == ['flux', 'qwen']
    assert 'ambiguous lineage' in art['reason'] and 'flux/qwen' in art['reason']


def test_an_unambiguous_lora_is_charged_with_exactly_its_base_family_record(tmp_path):
    """A family recorded without a commercial flag is UNKNOWN, never cleared."""
    reg = lp.load_registry(_registry(tmp_path))
    _d, ok = _weights(tmp_path, 'lora-weights-qwen', 'x.safetensors')
    art = lp.classify_weight('x.safetensors', kind='lora', path=ok, registry=reg)
    assert art['status'] == lp.CLEARED
    assert art['reason'] == 'LoRA fine-tuned from qwen base (Apache-2.0)'
    _d, silent = _weights(tmp_path, 'lora-weights-sdxl', 'x.safetensors')
    art = lp.classify_weight('x.safetensors', kind='lora', path=silent, registry=reg)
    assert (art['status'], art['licence']) == (lp.UNKNOWN, 'CreativeML-OpenRAIL-M')


def test_a_lora_with_no_lineage_falls_through_to_a_direct_rule(tmp_path, tmp_lora_roots):
    reg = lp.load_registry(_registry(tmp_path, lora_lineage=[]))
    art = lp.classify_weight('flux1-dev.safetensors', kind='LoRA', registry=reg)
    assert art['status'] == lp.NON_COMMERCIAL
    assert art['reason'] == 'at ' + str(paths.ZYG_FLUX_ROOT)
    bare = lp.classify_weight('nobody_knows.safetensors', kind='lora', registry=reg)
    assert bare['status'] == lp.UNKNOWN
    assert bare['reason'] == 'LoRA lineage unresolved (no training_status_*.json found)'


def test_a_territory_excluded_weight_fails_even_though_it_permits_commerce(tmp_path):
    reg = lp.load_registry(_registry(tmp_path))
    art = lp.classify_weight('hunyuan-video.safetensors', registry=reg)
    assert art['status'] == lp.TERRITORY_EXCLUDED
    assert art['reason'] == 'matched registry rule Tencent'
    assert lp.classify_weight('unet\\flux1-dev.safetensors', registry=reg)['status'] == lp.NON_COMMERCIAL


@pytest.mark.parametrize(
    ('statuses', 'expected'),
    [
        ([], None),
        ([lp.CLEARED], True),
        ([lp.CLEARED, lp.UNKNOWN], None),
        ([lp.CLEARED, lp.NON_COMMERCIAL], False),
        ([lp.UNKNOWN, lp.TERRITORY_EXCLUDED], False),
    ],
)
def test_fail_outranks_unknown_outranks_pass(statuses, expected):
    assert lp._verdict_from(statuses) is expected


# ── attest_licences ─────────────────────────────────────────────────────────


def test_an_unreadable_registry_is_reported_and_leaves_everything_unknown(no_resolve, no_ledger):
    logged = []
    res = lp.attest_licences(
        _graph('flux1-dev.safetensors'), log_fn=logged.append, registry_path='/nonexistent/zyg/m.json', tag='t'
    )
    assert res['ok'] is None
    assert 'licence registry empty or unreadable' in res['error']
    assert any('every weight will read UNKNOWN' in m for m in logged)


def test_a_graph_with_no_model_references_is_unknown(no_resolve, no_ledger, tmp_path):
    res = lp.attest_licences({'1': {'class_type': 'KSampler', 'inputs': {}}}, registry_path=_registry(tmp_path))
    assert res['ok'] is None
    assert res['error'] == 'no model references found in graph'


def test_a_broken_graph_walker_degrades_to_unknown(monkeypatch, no_ledger, tmp_path):
    """Enumeration is delegated to lora_attest; its breakage must not green the gate."""

    def boom(graph):
        raise TypeError('graph walker broke')

    monkeypatch.setattr(lora_attest, 'collect_model_refs', boom)
    logged = []
    res = lp.attest_licences(_graph('flux1-dev.safetensors'), log_fn=logged.append, registry_path=_registry(tmp_path))
    assert res['ok'] is None
    assert res['error'] == 'lora_attest unavailable: TypeError: graph walker broke'
    assert logged == ['[licence] lora_attest unavailable: TypeError: graph walker broke']
    assert res['artifacts'] == []


def test_a_path_resolver_that_raises_is_treated_as_an_unresolved_path(monkeypatch, no_ledger, tmp_path):
    def boom(name, folders=None):
        raise OSError('comfy root is gone')

    monkeypatch.setattr(lora_attest, 'resolve_model_path', boom)
    monkeypatch.setattr(lp, '_LORA_OUTPUT_ROOTS', [])
    graph = {'1': {'class_type': 'LoraLoader', 'inputs': {'lora_name': 'wan_char_aabbccddeeff.safetensors'}}}
    res = lp.attest_licences(graph, registry_path=_registry(tmp_path))
    assert res['ok'] is True
    assert res['artifacts'][0]['lineage'] == 'registry-convention'


def test_a_clean_graph_passes_and_says_so(no_resolve, no_ledger, tmp_path):
    logged = []
    res = lp.attest_licences(
        _graph('qwen-image.safetensors'), log_fn=logged.append, registry_path=_registry(tmp_path), tag='clean'
    )
    assert res['ok'] is True and res['violations'] == [] and res['unknowns'] == []
    assert res['territory'] == lp.TERRITORY
    assert any('clean: PASS' in m for m in logged)
    assert lp.attest_licences(_graph('qwen-image.safetensors'), registry_path=_registry(tmp_path))['ok'] is True


def test_a_violation_is_logged_per_weight_and_decides_the_whole_graph(no_resolve, no_ledger, tmp_path):
    logged = []
    res = lp.attest_licences(
        _graph('qwen-image.safetensors', 'flux1-dev.safetensors', 'flux1-dev.safetensors', 'hunyuan-x.safetensors'),
        log_fn=logged.append,
        registry_path=_registry(tmp_path),
    )
    assert res['ok'] is False
    assert [a['name'] for a in res['artifacts']] == [
        'qwen-image.safetensors',
        'flux1-dev.safetensors',
        'hunyuan-x.safetensors',
    ]
    assert {a['status'] for a in res['violations']} == {lp.NON_COMMERCIAL, lp.TERRITORY_EXCLUDED}
    assert any('graph: FAIL' in m for m in logged)
    assert sum(1 for m in logged if m.startswith('[licence]   ')) == 2


def test_unknown_weights_are_listed_but_only_the_first_eight_are_logged(no_resolve, no_ledger, tmp_path):
    logged = []
    res = lp.attest_licences(
        _graph(*[f'unheard{i}.safetensors' for i in range(10)]),
        log_fn=logged.append,
        registry_path=_registry(tmp_path),
    )
    assert res['ok'] is None and len(res['unknowns']) == 10
    assert any('UNKNOWN — 10 weight(s)' in m for m in logged)
    assert sum(1 for m in logged if m.startswith('[licence]   unknown: ')) == 8


def test_the_gate_records_its_outcome_on_the_run_ledger_unless_told_not_to(no_resolve, no_ledger, tmp_path):
    path = _registry(tmp_path)
    lp.attest_licences(_graph('flux1-dev.safetensors'), registry_path=path, run_id='r1', tag='rec')
    assert len(no_ledger) == 1, 'attest_licences(record=True) must reach run_ledger.record_gate'
    assert no_ledger[0] == (('r1', lp.GATE_NAME, 'FAIL'), {'score': 1.0, 'tag': 'rec'})
    lp.attest_licences(_graph('flux1-dev.safetensors'), registry_path=path, record=False)
    assert len(no_ledger) == 1


def test_an_internal_break_is_unknown_and_never_green(monkeypatch, no_ledger):
    def boom(*a, **k):
        raise ValueError('registry exploded')

    monkeypatch.setattr(lp, 'load_registry', boom)
    logged = []
    res = lp.attest_licences(_graph('qwen-image.safetensors'), log_fn=logged.append)
    assert res['ok'] is None
    assert res['error'] == 'ValueError: registry exploded'
    assert any('gate broke (treated as UNKNOWN, never green)' in m for m in logged)
    assert isinstance(res['elapsed_s'], float)


def test_the_ledger_bridge_resolves_the_run_id_and_survives_a_dead_ledger(no_ledger, monkeypatch):
    """The ledger is never a hard dependency: no Postgres must not break the gate."""
    monkeypatch.setenv('ZYG_RUN_ID', 'env-run')
    assert lp._record_gate(None, 'PASS', score=0.0, tag='t') is True
    assert no_ledger[0][0][0] == 'env-run'
    monkeypatch.delenv('ZYG_RUN_ID')
    assert lp._record_gate('', 'UNKNOWN') is True
    assert no_ledger[1][0][0] == 'adhoc'
    monkeypatch.setattr(run_ledger, 'record_gate', lambda *a, **k: 1 / 0)
    assert lp._record_gate('r', 'PASS') is False


@pytest.mark.parametrize(
    ('res', 'expected'),
    [
        ({'ok': True}, 'licence_provenance:cleared'),
        ({'ok': None}, 'licence_provenance:unknown'),
        ({'ok': False, 'violations': [{'status': lp.NON_COMMERCIAL}]}, 'licence_provenance:non_commercial'),
        ({'ok': False, 'violations': [{'status': lp.TERRITORY_EXCLUDED}]}, 'licence_provenance:territory_excluded'),
        ({'ok': False, 'violations': []}, 'licence_provenance:unknown'),
    ],
)
def test_check_name_emits_the_status_as_its_suffix(res, expected):
    assert lp.check_name(res) == expected


def test_publish_accepts_name_kind_pairs_from_a_delivery_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, '_LORA_OUTPUT_ROOTS', [])
    logged = []
    res = lp.publish_decision(
        [('wan_char_aabbccddeeff.safetensors', 'lora'), ['qwen-image.safetensors', None], 'qwen-image-vae.safetensors'],
        log_fn=logged.append,
        registry_path=_registry(tmp_path),
    )
    assert res['allowed'] is True and res['verdict'] == 'pass'
    assert res['reason'] == f'3 weight(s) cleared for {lp.TERRITORY}'
    assert logged == [f'[licence] publish PASS: 3 weight(s) cleared for {lp.TERRITORY}']


def test_publish_is_blocked_by_a_violation_by_silence_and_by_nothing_at_all(tmp_path):
    """For a monetised channel, "nobody recorded this licence" is not consent."""
    path = _registry(tmp_path)
    bad = lp.publish_decision(['flux1-dev.safetensors', 'qwen-image.safetensors'], registry_path=path)
    assert bad['allowed'] is False and bad['verdict'] == 'fail'
    assert bad['reason'] == 'flux1-dev.safetensors: non_commercial'
    unk = lp.publish_decision(['who-knows.safetensors'], registry_path=path)
    assert unk['allowed'] is False and unk['verdict'] == 'unknown'
    assert unk['reason'] == 'unrecorded licence for who-knows.safetensors'
    assert lp.publish_decision(None, registry_path=path)['verdict'] == 'unknown'


def test_a_cleared_family_is_approved_before_any_weight_exists(tmp_path):
    logged = []
    res = lp.family_decision(' QWEN ', log_fn=logged.append, registry_path=_registry(tmp_path))
    assert res == {
        'allowed': True,
        'verdict': 'pass',
        'family': 'qwen',
        'licence': 'Apache-2.0',
        'reason': 'qwen base is Apache-2.0',
    }
    assert logged == ['[licence] family qwen -> PASS: qwen base is Apache-2.0']


def test_the_pause_switch_outranks_a_clean_registry_entry(tmp_path, monkeypatch):
    """An operator may pause a family whose licence is fine — mid-migration, cost."""
    monkeypatch.setenv('ZYG_FLUX_RENDERS', 'paused')
    path = _registry(tmp_path, families={'flux': {'licence': 'BFL-Commercial', 'commercial': True}})
    res = lp.family_decision('flux', registry_path=path)
    assert res['allowed'] is False and res['verdict'] == 'fail'
    assert 'FLUX renders are paused' in res['reason']
    assert res['licence'] == 'BFL-Commercial'


def test_an_unpaused_non_commercial_or_unrecorded_family_is_never_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_FLUX_RENDERS', 'allowed')
    path = _registry(tmp_path)
    nc = lp.family_decision('flux', registry_path=path)
    assert nc['allowed'] is False and nc['verdict'] == 'fail'
    assert nc['reason'] == 'flux base is non_commercial: BFL-NC-2.0'
    res = lp.family_decision('made-up', registry_path=path)
    assert res['allowed'] is False and res['verdict'] == 'unknown' and res['licence'] is None
    assert res['reason'] == "no recorded licence for base family 'made-up'"
    assert lp.family_decision(None, registry_path=path)['family'] == ''


@pytest.mark.parametrize('raw', ['allowed', 'allow', 'on', '1', 'true', 'yes', ' ALLOWED ', 'Yes'])
def test_every_allow_word_opens_the_switch(monkeypatch, raw):
    monkeypatch.setenv('ZYG_FLUX_RENDERS', raw)
    assert lp.flux_state() == 'allowed'
    assert lp.flux_paused() is False
    assert lp.assert_flux_allowed('contact_sheet') is True


@pytest.mark.parametrize('raw', [None, 'paused', '', 'pasued', 'no', '0', 'maybe', 'allowedish'])
def test_anything_that_is_not_an_allow_word_reads_as_paused(monkeypatch, raw):
    """Unset is the 2026-08-09 default; a typo'd value must also stop new exposure."""
    monkeypatch.delenv('ZYG_FLUX_RENDERS', raising=False)
    if raw is not None:
        monkeypatch.setenv('ZYG_FLUX_RENDERS', raw)
    assert lp.flux_state() == 'paused'
    assert lp.flux_paused() is True


def test_assert_flux_allowed_names_the_site_and_the_way_out(monkeypatch):
    monkeypatch.setenv('ZYG_FLUX_RENDERS', 'paused')
    logged = []
    with pytest.raises(lp.FluxRendersPaused) as exc:
        lp.assert_flux_allowed('hand_fixer', log_fn=logged.append)
    assert 'PAUSED at hand_fixer' in str(exc.value)
    assert 'ZYG_FLUX_RENDERS=allowed' in str(exc.value)
    assert logged == ['[licence] ' + str(exc.value)]


def test_the_pause_is_catchable_by_a_graceful_caller(monkeypatch):
    """FluxRendersPaused is a RuntimeError, not a BaseException like QCBlocked, so a
    caller that catches Exception around a render can skip the FLUX path instead."""
    monkeypatch.setenv('ZYG_FLUX_RENDERS', 'paused')
    assert issubclass(lp.FluxRendersPaused, RuntimeError)
    with pytest.raises(Exception, match='FLUX renders are PAUSED —') as exc:
        lp.assert_flux_allowed()
    assert isinstance(exc.value, lp.FluxRendersPaused)


# ── the CLI ─────────────────────────────────────────────────────────────────


@pytest.fixture
def cli(monkeypatch, tmp_path, caplog):
    """Run _cli() with argv, a tmp registry and no ComfyUI path resolution."""
    monkeypatch.setattr(lp, 'REGISTRY_PATH', _registry(tmp_path))
    monkeypatch.setattr(lora_attest, 'resolve_model_path', lambda name, folders=None: None)
    monkeypatch.setattr(lp, '_LORA_OUTPUT_ROOTS', [])

    def run(*argv):
        monkeypatch.setattr(sys, 'argv', ['licence_provenance.py', *argv])
        caplog.clear()
        with caplog.at_level('INFO', logger=lp.__name__):
            rc = lp._cli()
        return rc, '\n'.join(caplog.messages)

    return run


def test_cli_without_a_known_subcommand_prints_the_module_docstring(cli):
    for argv in ((), ('explain-yourself',)):
        rc, out = cli(*argv)
        assert rc == 0
        assert 'is every weight in this graph cleared for commercial publication?' in out
        assert 'THE PAUSE SWITCH' in out


def test_cli_subcommands_without_their_argument_are_usage_errors(cli):
    assert cli('check') == (2, 'usage: licence_provenance.py check <graph.json>')
    assert cli('weight') == (2, 'usage: licence_provenance.py weight <name> [kind]')


@pytest.mark.parametrize(
    ('weight', 'rc', 'fragment'),
    [
        ('qwen-image.safetensors', 0, '"ok": true'),
        ('flux1-dev.safetensors', 1, '"ok": false'),
        ('nobody-recorded-this.safetensors', 1, '"ok": null'),
    ],
)
def test_cli_check_exits_zero_only_on_a_cleared_graph(cli, tmp_path, weight, rc, fragment):
    g = tmp_path / 'g.json'
    g.write_text(json.dumps(_graph(weight)), encoding='utf-8')
    got_rc, out = cli('check', str(g))
    assert got_rc == rc
    assert fragment in out
    assert f'"territory": "{lp.TERRITORY}"' in out


def test_cli_weight_prints_one_classification_and_takes_an_optional_kind(cli):
    rc, out = cli('weight', 'flux1-dev.safetensors')
    assert rc == 0
    assert json.loads(out)['status'] == lp.NON_COMMERCIAL
    rc, out = cli('weight', 'wan_char_aabbccddeeff.safetensors', 'lora')
    art = json.loads(out)
    assert (rc, art['kind'], art['base_family'], art['status']) == (0, 'lora', 'wan', lp.CLEARED)


def test_cli_state_reports_the_switch_the_territory_and_the_registry(cli, monkeypatch):
    monkeypatch.setenv('ZYG_FLUX_RENDERS', 'paused')
    rc, out = cli('state')
    state = json.loads(out)
    assert rc == 0
    assert state['flux_renders'] == 'paused'
    assert state['territory'] == lp.TERRITORY
    assert state['registry_loaded'] is True
    assert os.path.basename(state['registry']) == 'model_licences.json'
    monkeypatch.setattr(lp, 'REGISTRY_PATH', '/nonexistent/zyg/model_licences.json')
    assert json.loads(cli('state')[1])['registry_loaded'] is False
