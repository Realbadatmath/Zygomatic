# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for ``zyg_dashboard.bp_pipeline_api_steps.kanban_steps``.

Every step is a pure dict/list builder once its collaborators are supplied, so
the whole file runs offline: the callables the route injects (``runtime_payload``,
``card_times``, the reload/reconcile/refresh hooks) are plain fakes, the two
on-disk readers are pointed at ``tmp_path``, and the one environment switch the
module reads is driven with ``monkeypatch``.
"""

import json
import logging

import pytest

from zyg_dashboard.bp_pipeline_api_steps import kanban_steps as MOD

_LOGGER = 'zyg_dashboard.bp_pipeline_api_steps'
_LIVE = ('running', 'awaiting_review')
_CODE = {'Q': 'queued', 'R': 'running', 'D': 'done', 'E': 'error'}


def _cells(code, titles):
    """A compact board row (``'DDRQ'``) plus the card titles → the expected dict."""
    return dict(zip(titles, [_CODE[c] for c in code], strict=True))


def _ev(level='INFO', ts='T0', msg='m', stage='s'):
    return {'level': level, 'ts': ts, 'stage': stage, 'msg': msg}


def _runtime_payload(job, live):
    return {'runtime': f'{job.get("char_id", job.get("creature_id", "?"))}:{live}'}


def _card_times(job, cards):
    return {name: {'started': job.get('started')} for name in cards}


def _boom(*_a, **_kw):
    raise RuntimeError('collaborator exploded')


def _write_state(directory, name, payload):
    (directory / name).write_text(json.dumps(payload), encoding='utf-8')


def _reconcile(job):
    return dict(job, reconciled=True)


class _GuiState:
    _CHAR_GEN_RELOAD_DONE = _CREATURE_GEN_RELOAD_DONE = _CONTACT_SHEET_RELOAD_DONE = False


def _all_hydrated(state):
    return all(getattr(state, f'_{n}_RELOAD_DONE') for n in ('CHAR_GEN', 'CREATURE_GEN', 'CONTACT_SHEET'))


class _BlindJobs(dict):
    """A registry whose ``values()`` hides the live jobs from the first scan.

    The disk-adoption branch is only reachable when the live scan finds nothing
    while a live twin is still in the cache — this stages exactly that.
    """

    def values(self):
        return []


# ---- _step_debug_event_lines
@pytest.mark.parametrize(
    ('level', 'is_error'),
    [('INFO', False), ('debug', False), ('warn', True), ('WARNING', True), ('error', True), ('CRITICAL', True)],
)
def test_debug_event_lines_splits_by_level(level, is_error):
    errors, events = MOD._step_debug_event_lines([_ev(level, 'T1', 'hello', 's1')])
    assert (errors if is_error else events) == ['[T1] [s1] hello']
    assert (events if is_error else errors) == []


def test_debug_event_lines_defaults_and_truncation():
    errors, events = MOD._step_debug_event_lines([{}, {'msg': 'x' * 50}], msg_limit=10)
    assert errors == []
    assert events == ['[?] [?] ', '[?] [?] xxxxxxxxxx']


# ---- _step_hydrate_job_caches
def test_hydrate_job_caches_runs_each_reload_once():
    calls = []
    state = _GuiState()
    hooks = (lambda: calls.append('char'), lambda: calls.append('creature'), lambda: calls.append('sheet'))
    MOD._step_hydrate_job_caches(state, *hooks)
    assert calls == ['char', 'creature', 'sheet']
    assert _all_hydrated(state)
    calls.clear()
    MOD._step_hydrate_job_caches(state, *hooks)
    assert calls == []


def test_hydrate_job_caches_survives_every_failure(caplog):
    state = _GuiState()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        MOD._step_hydrate_job_caches(state, _boom, _boom, _boom)
    assert _all_hydrated(state)
    assert len([m for m in caplog.messages if 'hydrate from disk failed' in m]) == 3


# ---- _step_pick_contact_sheet_job
def test_pick_contact_sheet_job_prefers_newest_live():
    old = {'char_id': 'old', 'status': 'running', 'started': '2026-01-01'}
    new = {'char_id': 'new', 'status': 'running', 'started': '2026-02-01'}
    assert MOD._step_pick_contact_sheet_job({'old': old, 'new': new}, lambda cid: True) is new


@pytest.mark.parametrize(
    ('jobs', 'alive'),
    [
        ({'a': {'char_id': 'a', 'status': 'done', 'started': ''}}, lambda cid: True),
        ({'a': {'char_id': '  ', 'status': 'running'}}, lambda cid: True),
        ({'a': {'char_id': 'a', 'status': 'running'}}, lambda cid: False),
        ({}, lambda cid: True),
    ],
    ids=['not-running', 'no-char-id', 'worker-dead', 'empty'],
)
def test_pick_contact_sheet_job_returns_none(jobs, alive):
    assert MOD._step_pick_contact_sheet_job(jobs, alive) is None


# ---- _step_contact_sheet_payload
_CS_ENV = 'ZYG_CONTACT_SHEET_LORA_TRAINING'
_CS_ORDER = (
    'Contact Sheet Generation|Awaiting Approval|Tile Crop|Identity QC (ArcFace)|VLM Defect Judge|Caption Generation'
    '|SimpleTuner FLUX LoRA Training|Angle Expansion (LoRA v1)|LoRA Refine (v2)|QC Safety Valve'
).split('|')


@pytest.mark.parametrize(
    ('env', 'job', 'expected'),
    [
        # With the switch unset or off, the three training cards are pinned to
        # 'queued' unless the run is actually inside one of those stages.
        (None, {'stage': 'sheet_generate'}, 'RQQQQQQQQQ'),
        (None, {'stage': 'awaiting_approval'}, 'DRQQQQQQQQ'),
        (None, {'stage': 'awaiting_approval', 'approved': True}, 'DDQQQQQQQQ'),
        (None, {'stage': 'tile_crop'}, 'DDRQQQQQQQ'),
        (None, {'stage': 'unknown_stage'}, 'QQQQQQQQQQ'),
        ('1', {'stage': 'identity_qc', 'sheet_substage': 'vlm_judge'}, 'DDDRRQQQQQ'),
        ('1', {'stage': 'identity_qc', 'sheet_substage': 'idqc_regen_2'}, 'DDDRDQQQQQ'),
        ('1', {'stage': 'captions'}, 'DDDDDRQQQQ'),
        ('1', {'stage': 'captions', 'qc_safety_valve': {'verdict': 'pass'}}, 'DDDDDRQQQD'),
        ('1', {'stage': 'captions', 'sheet_substage': 'qc_safety_valve'}, 'DDDDDRQQQR'),
        ('on', {'stage': 'lora_training'}, 'DDDDDDRQQQ'),
        ('true', {'stage': 'angle_expansion'}, 'DDDDDDDRQQ'),
        ('yes', {'stage': 'lora_refine'}, 'DDDDDDDDRQ'),
        ('1', {'stage': 'lora_refine', 'status': 'done'}, 'DDDDDDDDDQ'),
        # The per-job flag disables the training cards even with the env on.
        ('1', {'stage': 'captions', 'lora_training_disabled': True}, 'DDDDDRQQQQ'),
    ],
)
def test_contact_sheet_payload_card_ladder(monkeypatch, env, job, expected):
    if env is None:
        monkeypatch.delenv(_CS_ENV, raising=False)
    else:
        monkeypatch.setenv(_CS_ENV, env)
    out = MOD._step_contact_sheet_payload(job, _runtime_payload, _card_times)
    assert out['cards'] == _cells(expected, _CS_ORDER)


def test_contact_sheet_payload_envelope(monkeypatch):
    monkeypatch.delenv(_CS_ENV, raising=False)
    job = {'char_id': 'ada', 'stage': 'tile_crop', 'status': 'running', 'started': 'T0'}
    out = MOD._step_contact_sheet_payload(job, _runtime_payload, _card_times)
    assert out['template'] == out['pipeline']['department'] == 'contact_sheet_creation'
    assert out['model_family'] == out['pipeline']['model_family'] == 'flux'
    assert out['pipeline']['current_stage'] == 'Tile Crop'
    assert out['pipeline']['job_id'] == 'ada'
    assert out['pipeline']['started'] == 'T0'
    assert out['pipeline']['runtime'] == 'ada:True'
    assert out['card_times']['Tile Crop'] == {'started': 'T0'}
    assert out['is_test'] is False


def test_contact_sheet_payload_sdxl_card_name_and_events(monkeypatch):
    monkeypatch.setenv(_CS_ENV, '1')
    events = [_ev('ERROR', 'T1', 'bad tile'), _ev('INFO', 'T2', 'ok tile')]
    job = {'stage': 'identity_qc', 'status': 'running', 'model_family': 'SDXL', 'debug_events': events}
    out = MOD._step_contact_sheet_payload(job, _runtime_payload, _card_times)
    assert out['cards']['SimpleTuner SDXL LoRA Training'] == 'queued'
    assert 'SimpleTuner FLUX LoRA Training' not in out['cards']
    assert out['model_family'] == 'sdxl'
    assert out['errors'] == ['[T1] [s] bad tile']
    assert out['events'] == ['[T2] [s] ok tile']


# ---- _step_pick_char_job
def test_pick_char_job_prefers_newest_live(tmp_path):
    old = {'char_id': 'old', 'status': 'running', 'started': '2026-01-01'}
    new = {'char_id': 'new', 'status': 'running', 'started': '2026-03-01'}
    out = MOD._step_pick_char_job({'old': old, 'new': new}, str(tmp_path), _reconcile)
    assert (out['char_id'], out['reconciled']) == ('new', True)
    assert 'reconciled' not in new  # the live dict itself is left alone


def test_pick_char_job_rekeys_a_live_job_filed_under_another_key(tmp_path):
    jobs = {'legacy-key': {'char_id': 'ada', 'status': 'running', 'started': '2026-01-01'}}
    out = MOD._step_pick_char_job(jobs, str(tmp_path), _reconcile)
    assert jobs['ada'] is out
    assert 'reconciled' not in jobs['legacy-key']


@pytest.mark.parametrize(('char_id', 'cached'), [('ada', True), ('   ', False)])
def test_pick_char_job_adopts_the_newest_running_state_file(tmp_path, char_id, cached):
    _write_state(tmp_path, 'char_gen_idle.json', {'char_id': 'idle', 'status': 'done'})
    _write_state(tmp_path, 'char_gen_live.json', {'char_id': char_id, 'status': 'running'})
    jobs = {}
    out = MOD._step_pick_char_job(jobs, str(tmp_path), _reconcile)
    assert out['char_id'] == char_id
    # A blank char_id is never cached, and without a key there is no reconcile
    # pass either; a real one is cached as the RAW snapshot, before reconcile.
    assert out.get('reconciled', False) is cached
    assert jobs == ({'ada': {'char_id': 'ada', 'status': 'running'}} if cached else {})


def test_pick_char_job_live_twin_wins_over_disk(tmp_path):
    _write_state(tmp_path, 'char_gen_ada.json', {'char_id': 'ada', 'status': 'running', 'from_disk': True})
    seen = {}
    jobs = _BlindJobs({'ada': {'char_id': 'ada', 'status': 'running', 'live': True}})
    out = MOD._step_pick_char_job(jobs, str(tmp_path), lambda j: (seen.setdefault('job', j), _reconcile(j))[1])
    assert seen['job']['live'] is True
    assert out['reconciled'] is True


def test_pick_char_job_skips_unreadable_state_file(tmp_path, caplog):
    (tmp_path / 'char_gen_broken.json').write_text('{not json', encoding='utf-8')
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert MOD._step_pick_char_job({}, str(tmp_path), _reconcile) is None
    assert any('character state file' in m and 'unreadable, skipped' in m for m in caplog.messages)


# ---- _step_char_payload
_CHAR_ORDER = (
    'Blender 4.3.2 Headless Render|FLUX Character Render|Caption Generation|SimpleTuner FLUX LoRA Training'
    '|FLUX LoRA Training (identity — required for SDXL path)|SimpleTuner SDXL LoRA Training'
    '|IPAdapter-Only Mode (LoRA timeout fallback)'
).split('|')


@pytest.fixture
def char_stage(monkeypatch):
    """Pin the derived stage + model family so the card ladder is the subject."""

    def _set(stage, family):
        monkeypatch.setattr(MOD, '_char_derive_pipeline_stage', lambda job: stage)
        monkeypatch.setattr(MOD, '_normalize_char_model_family', lambda mf, params, info: family)

    return _set


@pytest.mark.parametrize(
    ('stage', 'family', 'code', 'preview'),
    [
        ('blender_render', 'flux', 'RQQQ', None),
        ('flux_fallback', 'flux', 'QRQQ', None),
        ('captions', 'flux', 'DDRQ', None),
        ('lora_training', 'flux', 'DDDR', None),
        ('preview_render', 'flux', 'DDDD', None),
        ('done', 'flux', 'DDDD', None),
        # An off-ladder stage indexes at 0 but is still past render and captions.
        ('error', 'flux', 'DDDQ', None),
        # On the SDXL board the fallback card is inert and a preview card appears.
        ('flux_fallback', 'sdxl', 'QQQQ', 'Q'),
        ('preview_render', 'sdxl', 'DDDD', 'R'),
        ('done', 'sdxl', 'DDDD', 'D'),
    ],
)
def test_char_payload_card_ladder(char_stage, stage, family, code, preview):
    char_stage(stage, family)
    out = MOD._step_char_payload({'char_id': 'ada'}, _runtime_payload, _card_times)
    blender, flux_render, caption, trained = code
    # All four LoRA-training cards carry the same state, whatever the family.
    expected = _cells(f'{blender}{flux_render}{caption}' + trained * 3 + 'Q', _CHAR_ORDER)
    if preview:
        expected['SDXL Preview Render'] = _CODE[preview]
    assert out['cards'] == expected
    assert out['model_family'] == family


def test_char_payload_envelope_and_event_split(char_stage):
    char_stage('captions', 'flux')
    events = [_ev('WARN', 'T1', 'slow'), _ev('INFO', 'T2', 'fine')]
    job = {'char_id': 'ada', 'status': 'running', 'started': 'T0', 'ended': None, 'debug_events': events}
    out = MOD._step_char_payload(job, _runtime_payload, _card_times)
    assert out['errors'] == ['[T1] [s] slow']
    assert out['events'] == ['[T2] [s] fine']
    assert out['template'] == out['pipeline']['department'] == 'character_creation'
    assert out['pipeline']['current_stage'] == 'Captions'
    assert out['pipeline']['job_id'] == 'ada'
    assert out['pipeline']['runtime'] == 'ada:True'
    assert out['card_times']['Caption Generation'] == {'started': 'T0'}
    assert out['is_test'] is False


def test_char_payload_runs_with_the_real_stage_derivation():
    """No monkeypatch: the real derivation must still produce a board."""
    job = {'char_id': '', 'status': 'running', 'current_stage': '1c lora training'}
    out = MOD._step_char_payload(job, _runtime_payload, _card_times)
    assert out['cards']['SimpleTuner FLUX LoRA Training'] == 'running'
    assert out['pipeline']['current_stage'] == 'Lora Training'


# ---- _step_pick_creature_job
def test_pick_creature_job_live_first(tmp_path):
    a = {'creature_id': 'a', 'status': 'running', 'started': '2026-01-01'}
    b = {'creature_id': 'b', 'status': 'awaiting_review', 'started': '2026-04-01'}
    assert MOD._step_pick_creature_job({'a': a, 'b': b}, str(tmp_path), _LIVE) is b


@pytest.mark.parametrize(('creature_id', 'cached'), [('zoe', True), ('', False)])
def test_pick_creature_job_adopts_disk_state(tmp_path, creature_id, cached):
    _write_state(tmp_path, 'creature_gen_done.json', {'creature_id': 'done', 'status': 'completed'})
    _write_state(tmp_path, 'creature_gen_live.json', {'creature_id': creature_id, 'status': 'running'})
    jobs = {}
    out = MOD._step_pick_creature_job(jobs, str(tmp_path), _LIVE)
    assert out['creature_id'] == creature_id
    assert jobs == ({'zoe': out} if cached else {})


def test_pick_creature_job_disk_hit_returns_live_twin(tmp_path):
    _write_state(tmp_path, 'creature_gen_zoe.json', {'creature_id': 'zoe', 'status': 'running'})
    live = {'creature_id': 'zoe', 'status': 'running', 'live': True}
    assert MOD._step_pick_creature_job(_BlindJobs({'zoe': live}), str(tmp_path), _LIVE) is live


def test_pick_creature_job_skips_unreadable_and_returns_none(tmp_path, caplog):
    (tmp_path / 'creature_gen_broken.json').write_text('[[[', encoding='utf-8')
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert MOD._step_pick_creature_job({}, str(tmp_path), _LIVE) is None
    assert any('creature state file' in m for m in caplog.messages)


# ---- _step_creature_payload
def test_creature_payload_running():
    job = {'creature_id': 'zoe', 'status': 'running', 'started': 'T0', 'ended': None, 'directive': 'a' * 200}
    job.update(current_stage='sheet_qc', sheet_path='sheet.png', sheet_report={'ok': True}, train_family='sdxl')
    job['debug_events'] = [_ev('ERROR', 'T1', 'reject')]
    out = MOD._step_creature_payload(job, 'sheet', {'Sheet': 'running'}, _runtime_payload, _card_times)
    pipe = out['pipeline']
    assert pipe['status'] == 'running'
    assert pipe['current_stage'] == 'Sheet Qc'
    assert pipe['review_pending'] is False
    assert pipe['model_family'] == out['model_family'] == 'sdxl'
    assert len(pipe['topic']) == 120  # the directive is clipped
    assert pipe['runtime'] == 'zoe:True'
    assert (pipe['sheet_path'], pipe['sheet_report']) == ('sheet.png', {'ok': True})
    assert (out['errors'], out['events']) == (['[T1] [s] reject'], [])
    assert (out['cards'], out['template'], out['is_test']) == ({'Sheet': 'running'}, 'creature_creation', False)


def test_creature_payload_awaiting_review_defaults():
    job = {'creature_id': 'zoe', 'status': 'awaiting_review'}
    out = MOD._step_creature_payload(job, 'sheet_review', {}, _runtime_payload, _card_times)
    assert out['pipeline']['current_stage'] == 'Sheet Review — awaiting operator approval'
    assert out['pipeline']['review_pending'] is True
    assert out['pipeline']['status'] == 'awaiting_review'
    assert out['pipeline']['model_family'] == 'klein'
    assert out['pipeline']['runtime'] == 'zoe:False'
    assert out['pipeline']['topic'] == ''


# ---- _step_creature_stage_and_cards
_CR_ORDER = ['creature_brief', 'anchor', 'sheet', 'sheet_qc', 'captions', 'lora_training', 'done']
_CR_TABLE = [(key, key.replace('_', ' ').title()) for key in _CR_ORDER[:-1]]


@pytest.mark.parametrize(
    ('job', 'expected'),
    [
        ({'stage': 'sheet', 'status': 'running'}, 'DDRQQQ'),
        ({'stage': 'sheet_qc', 'status': 'failed'}, 'DDDDDD'),  # a failed run derives stage 'done'
        ({'stage': 'reference_gen', 'status': 'running'}, 'DDRQQQ'),  # legacy May-2026 state files
        ({'stage': 'lora_training', 'status': 'completed'}, 'DDDDDD'),
        ({'stage': 'done', 'status': 'running'}, 'DDDDDD'),
        ({'stage': 'unknown_stage', 'status': 'running'}, 'RQQQQQ'),
    ],
)
def test_creature_stage_and_cards(job, expected):
    seen = []
    out_job, stage, cards = MOD._step_creature_stage_and_cards(
        job, _CR_ORDER, _CR_TABLE, lambda j: (seen.append('refresh'), j)[1], lambda j: seen.append('stale')
    )
    assert seen == ['refresh', 'stale']
    assert out_job is job
    assert stage != 'reference_gen'
    assert cards == _cells(expected, [title for _key, title in _CR_TABLE])


# ---- _step_standalone_video_payload
@pytest.fixture
def video_payload(monkeypatch):
    """Replace the standalone VACE board's only collaborator."""
    import zyg_dashboard.kanban_video_status as kvs

    return lambda fn: monkeypatch.setattr(kvs, 'kanban_payload', fn)


def test_standalone_video_payload_fills_defaults(video_payload):
    video_payload(lambda: {'template': 'documentary', 'cards': {'A': 'running'}})
    out = MOD._step_standalone_video_payload()
    assert out == {'template': 'documentary', 'cards': {'A': 'running'}, 'errors': [], 'events': [], 'is_test': False}


@pytest.mark.parametrize('payload', [None, {}])
def test_standalone_video_payload_none_when_idle(video_payload, payload):
    video_payload(lambda: payload)
    assert MOD._step_standalone_video_payload() is None


def test_standalone_video_payload_swallows_errors(video_payload, caplog):
    video_payload(_boom)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert MOD._step_standalone_video_payload() is None
    assert any('standalone VACE board unavailable' in m for m in caplog.messages)


# ---- _normalize_timeline_status
def test_normalize_timeline_status():
    assert all(MOD._normalize_timeline_status(r) == 'done' for r in ('completed', 'success', 'done'))
    assert all(MOD._normalize_timeline_status(r) == 'error' for r in ('failed', 'error'))
    assert MOD._normalize_timeline_status('running') == 'running'
    assert all(MOD._normalize_timeline_status(r) == 'queued' for r in ('queued', None, 'pending'))


# ---- _step_timeline_lookup
def test_timeline_lookup_from_stage_timeline():
    rows = [{'name': 'Research', 'status': 'completed'}, {'name': 'Writing', 'status': 'running'}, {'name': 'Review'}]
    tl_map, tl_order, cur_idx = MOD._step_timeline_lookup({'stage_timeline': rows}, 'writing')
    assert tl_map == {'research': 'completed', 'writing': 'running', 'review': 'queued'}
    assert tl_order == ['research', 'writing', 'review']
    assert cur_idx == 1


@pytest.mark.parametrize(
    ('stages', 'expected'),
    [
        ({'Flat': {'status': 'completed'}}, 'completed'),
        ({'Nest': {'a': {'status': 'completed'}, 'b': {'status': 'running'}}}, 'running'),
        ({'Nest': {'a': {'status': 'failed'}, 'b': {'status': 'completed'}}}, 'failed'),
        ({'Nest': {'a': {'status': 'success'}, 'b': {'status': 'done'}}}, 'completed'),
        ({'Nest': {'a': {'status': 'queued'}}}, 'queued'),
        ({'Nest': {}}, None),
        ({'Nest': 'plain string'}, None),
    ],
)
def test_timeline_lookup_folds_the_stages_dict(stages, expected):
    key = next(iter(stages)).lower()
    tl_map, tl_order, cur_idx = MOD._step_timeline_lookup({'stages': stages}, '')
    assert tl_map.get(key) == expected
    assert (key in tl_order) is (expected is not None)
    assert cur_idx == -1


def test_timeline_lookup_stage_timeline_wins_over_the_stages_dict():
    rows = [{'name': 'Research', 'status': 'completed'}]
    job = {'stage_timeline': rows, 'stages': {'Research': {'status': 'queued'}}}
    tl_map, tl_order, cur_idx = MOD._step_timeline_lookup(job, 'research pass')
    assert (tl_map, tl_order, cur_idx) == ({'research': 'completed'}, ['research'], 0)


def test_timeline_lookup_empty_job_and_blank_stage():
    assert MOD._step_timeline_lookup({}, '') == ({}, [], -1)


# ---- _step_resolve_board_cards
def test_resolve_board_cards_matches_timeline_rows():
    stage_map = {'Research': ['research'], 'Writing': ['writing']}
    tl_map = {'research pass': 'completed', 'writing pass': 'running'}
    cards, card_keys = MOD._step_resolve_board_cards(stage_map, tl_map, list(tl_map), 1, 'running')
    assert cards == {'Research': 'done', 'Writing': 'running'}
    assert card_keys == {'Research': 'research pass', 'Writing': 'writing pass'}


def test_resolve_board_cards_queues_rows_absent_from_the_map():
    """A name listed in the order but missing from the map has not started yet."""
    cards, card_keys = MOD._step_resolve_board_cards({'Review': ['review']}, {}, ['review pass'], 0, 'running')
    assert (cards, card_keys) == ({'Review': 'queued'}, {'Review': 'review pass'})


@pytest.mark.parametrize(('pipeline_status', 'expected'), [('running', 'queued'), ('done', 'idle')])
def test_resolve_board_cards_unmatched_falls_back_to_status(pipeline_status, expected):
    args = ({'Ghost': ['ghost']}, {'research': 'completed'}, ['research'], 0, pipeline_status)
    cards, card_keys = MOD._step_resolve_board_cards(*args)
    assert (cards, card_keys) == ({'Ghost': expected}, {})


def test_resolve_board_cards_second_fragment_wins():
    args = ({'Edit': ['nowhere', 'edit']}, {'final edit': 'failed'}, ['final edit'], -1, 'running')
    cards, card_keys = MOD._step_resolve_board_cards(*args)
    assert (cards, card_keys) == ({'Edit': 'error'}, {'Edit': 'final edit'})


# ---- _step_peer_run
def test_peer_run_cells_from_timeline():
    peer = {'pipeline_id': 'pipe-1234', 'user_name': 'ada', 'scholarly_topic': 'moons', 'started': 'T0'}
    peer.update(current_stage='writing', status='running')
    peer['stage_timeline'] = [{'name': 'Research', 'status': 'completed'}, {'name': 'Writing', 'status': 'running'}]
    row = MOD._step_peer_run(peer, {'Research': ['research'], 'Writing': ['writing'], 'Ghost': ['ghost']})
    assert row['cards'] == {'Research': 'done', 'Writing': 'running', 'Ghost': 'queued'}
    assert (row['pipeline_id'], row['user_name'], row['topic']) == ('pipe-1234', 'ada', 'moons')
    assert row['started'] == 'T0'


def test_peer_run_idle_peer_defaults():
    row = MOD._step_peer_run({}, {'Research': ['research']})
    assert row == {'pipeline_id': '', 'user_name': '', 'topic': '', 'started': '', 'cards': {'Research': 'idle'}}


def test_peer_run_without_current_stage_match():
    peer = {'status': 'running', 'current_stage': 'nowhere', 'stage_timeline': [{'name': 'R', 'status': 'failed'}]}
    row = MOD._step_peer_run(peer, {'R': ['r'], 'Ghost': ['ghost']})
    assert row['cards'] == {'R': 'error', 'Ghost': 'queued'}


# ---- _step_live_tail
def test_live_tail_primary_has_no_prefix_and_peers_do():
    peer = {'pipeline_id': 'abcdefghij', 'debug_events': [_ev('ERROR', 'T1', 'bad')]}
    errors, events = MOD._step_live_tail({'debug_events': [_ev('INFO', 'T0', 'primary')]}, [peer])
    assert events == ['[T0] [s] primary']
    assert errors == ['[T1] [abcdef] [s] bad']


def test_live_tail_honours_cleared_index_and_caps_peers():
    active = {'errors_cleared_at_index': 2, 'debug_events': [_ev('INFO', f'T{i}', f'e{i}') for i in range(3)]}
    peers = [{'pipeline_id': f'peer{i:02d}', 'debug_events': [_ev('INFO', 'T', f'p{i}')]} for i in range(9)]
    errors, events = MOD._step_live_tail(active, peers)
    assert errors == []
    assert events[0] == '[T2] [s] e2'
    assert len(events) == 8
    assert all('p7' not in line and 'p8' not in line for line in events)


def test_live_tail_renders_a_malformed_event_instead_of_crashing():
    active = {'debug_events': ['a bare string', 42, _ev('WARN', 'T1', 'x' * 200)]}
    errors, events = MOD._step_live_tail(active, [])
    assert events == ['[?] [malformed event] a bare string', '[?] [malformed event] 42']
    assert errors == ['[T1] [s] ' + 'x' * 120]


def test_live_tail_malformed_event_from_a_peer_is_tagged():
    errors, events = MOD._step_live_tail({}, [{'pipeline_id': 'peerid1234', 'debug_events': ['oops']}])
    assert errors == []
    assert events == ['[?] [peerid] [malformed event] oops']


def test_live_tail_caps_at_thirty_errors_and_fifty_events():
    evs = [_ev('ERROR', f'E{i}', str(i)) for i in range(40)] + [_ev('INFO', f'I{i}', str(i)) for i in range(60)]
    errors, events = MOD._step_live_tail({'debug_events': evs}, [])
    assert (len(errors), len(events)) == (30, 50)
    assert errors[0].startswith('[E10]')
    assert events[0].startswith('[I10]')


# ---- _step_sports_video_status
def test_sports_video_status_reads_the_file(tmp_path, monkeypatch):
    path = tmp_path / 'status.json'
    path.write_text(json.dumps({'stage': 'encode'}), encoding='utf-8')
    monkeypatch.setattr(MOD, '_SPORTS_VIDEO_STATUS', str(path))
    assert MOD._step_sports_video_status() == {'stage': 'encode'}


def test_sports_video_status_absent_file(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(MOD, '_SPORTS_VIDEO_STATUS', str(tmp_path / 'nope.json'))
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert MOD._step_sports_video_status() == {}
    assert any('status file absent' in m for m in caplog.messages)


@pytest.mark.parametrize('kind', ['half-written', 'a-directory'])
def test_sports_video_status_unreadable(tmp_path, monkeypatch, caplog, kind):
    target = tmp_path
    if kind == 'half-written':
        target = tmp_path / 'status.json'
        target.write_text('{"stage": ', encoding='utf-8')
    monkeypatch.setattr(MOD, '_SPORTS_VIDEO_STATUS', str(target))
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert MOD._step_sports_video_status() == {}
    assert any('unreadable, reporting none' in m for m in caplog.messages)
