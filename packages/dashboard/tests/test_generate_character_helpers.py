# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the helpers `api_internal_storyteller_generate_character` was split into.

Until the 2026-10-09 function split these were blocks inside a 370-line Flask
route (and two of them were closures over `char_id`), so the only way to reach
any of them was to POST the route and let it start Blender, a billed Sonnet
brief and a LoRA training thread. They are now module-level functions, and this
file is the first time the parameter normalisation, the muscle-mass coercion,
the photo-input merge, the park record, the job registration and the event trim
are exercised in isolation. Nothing here touches the GPU, the network or a
service: the collaborators are stubbed and the two request-reading helpers run
under a bare Flask test request context.

WHY THE MODULE IS LOADED BY PATH
--------------------------------
`zyg_dashboard.bp_storyteller.__init__` imports crewai_web_gui, which builds the
production Flask app and starts its watcher threads at import time, and the api
harness must be the one that imports it (tests/api/conftest.py suppresses those
threads and supplies FLASK_SECRET_KEY first — importing it here instead makes
every api test fail). The helpers only need those package names to EXIST, so the
module is loaded against stub globals, exactly as
tests/test_generate_worker_helpers.py does for its sibling module.
"""

import importlib.util
import json
import logging
import os
import pathlib
import re
import sys
import types

import pytest
from flask import Flask

_MOD_NAME = 'generate_character_under_test'
_MOD_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / 'src' / 'zyg_dashboard' / 'bp_storyteller' / 'generate_character.py'
)

_STUBBED_CALLABLES = (
    '_ams_iso',
    '_caveman_kw',
    '_char_save_state',
    '_record_token_usage',
    '_resolve_char_model_family',
    '_zero_audit_log',
    '_zpub_pending_load',
    '_zpub_pending_save',
)


def _load_route_module():
    """Load generate_character.py against stub package globals.

    Returns the loaded module. `sys.modules` is left exactly as it was found:
    the stubs exist only for the duration of the load, so no other test module
    can ever see them.
    """
    keys = (
        'zyg_dashboard',
        'zyg_dashboard.bp_storyteller',
        'zyg_dashboard.bp_storyteller.generate_worker',
        'zyg_dashboard.bp_storyteller.guards',
        _MOD_NAME,
    )
    saved = [(k, sys.modules.get(k, None), k in sys.modules) for k in keys]

    def _unused(*_a, **_kw):
        """Stand-in for a package collaborator no test monkeypatched."""
        raise AssertionError('the helper called an unstubbed collaborator')

    class _Bp:
        """Just enough of the storyteller blueprint for the route decorator."""

        def route(self, *_a, **_kw):
            """Return the identity decorator the real one returns a wrapper from."""
            return lambda fn: fn

    class _NullLock:
        """A stand-in for the pending-store lock (the protocol is looked up on the type)."""

        def __enter__(self):
            """Enter the critical section — there is nothing to serialise in a test."""
            return self

        def __exit__(self, *_exc):
            """Leave the critical section, never swallowing an exception."""
            return False

    root = types.ModuleType('zyg_dashboard')
    root.__path__ = []
    pkg = types.ModuleType('zyg_dashboard.bp_storyteller')
    pkg.__path__ = []
    for name in _STUBBED_CALLABLES:
        setattr(pkg, name, _unused)
    pkg._ZPUB_PENDING_LOCK = _NullLock()
    pkg._char_gen_jobs = {}
    pkg._main_mod = types.SimpleNamespace(app=None)
    pkg.bp = _Bp()
    pkg.gui_state = types.SimpleNamespace(_pipeline_stop_flag=False)
    pkg.limiter = types.SimpleNamespace(exempt=lambda fn: fn)
    worker = types.ModuleType('zyg_dashboard.bp_storyteller.generate_worker')
    worker._make_bg_generate = _unused
    guards = types.ModuleType('zyg_dashboard.bp_storyteller.guards')
    guards._CHAR_ID_RE = re.compile(r'^[0-9a-f]{12}$')
    guards._env_on = _unused
    guards._production_paused = _unused
    guards._restore_parked_char_photos = _unused
    guards._save_uploaded_char_photos = _unused
    sys.modules['zyg_dashboard'] = root
    sys.modules['zyg_dashboard.bp_storyteller'] = pkg
    sys.modules['zyg_dashboard.bp_storyteller.generate_worker'] = worker
    sys.modules['zyg_dashboard.bp_storyteller.guards'] = guards
    try:
        spec = importlib.util.spec_from_file_location(_MOD_NAME, _MOD_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_MOD_NAME] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for key, value, present in saved:
            if present:
                sys.modules[key] = value
            else:
                sys.modules.pop(key, None)


GC = _load_route_module()
_APP = Flask('generate_character_helper_tests')
_APP.secret_key = os.urandom(16)


def _pending_store(monkeypatch):
    """Stub the pending store with a list that records what was saved.

    Returns the list of saved snapshots: `_zpub_pending_load` always hands out a
    copy, so the rows the helper appended are visible only through the save.
    """
    saved: list = []
    monkeypatch.setattr(GC, '_zpub_pending_load', lambda: list(saved[-1]) if saved else [])
    monkeypatch.setattr(GC, '_zpub_pending_save', saved.append)
    return saved


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('auto', 20),  # the sentinel every neighbouring field accepts
        ('', 20),
        (None, 20),
        ('medium', 20),
        (0, 0),  # a legitimate zero, which `or 20` used to swallow
        ('35', 35),
        (101, 100),
        (-5, 0),
    ],
)
def test_muscle_mass_coercion_never_raises_and_clamps_to_the_band(raw, expected):
    assert GC._coerce_muscle_mass(raw) == expected


def test_character_params_defaults_every_identity_field_to_the_auto_sentinel():
    params = GC._character_params({})

    assert params['name'] == ''
    assert params['hair_color'] == 'brown'
    assert params['eye_color'] == 'brown'
    assert params['skin_tone'] == 'medium'
    assert params['gender'] == 'female'
    assert params['height'] == '1.70'
    assert params['age'] is None
    assert params['genre'] == 'general'
    assert params['facial_hair'] == 'none'
    assert params['muscle_mass'] == 20
    for field in (
        'style',
        'hair_style',
        'hair_length',
        'hair_texture',
        'eye_shape',
        'eyebrow_style',
        'face_shape',
        'nose_shape',
        'lip_shape',
        'distinctive_marks',
        'default_clothing',
        'accessories',
        'default_expression',
        'posture',
        'quality_suffix',
        'negative_prompt',
    ):
        assert params[field] == 'auto', field
    assert params['ethnic_heritage'] == ''
    # The two conditioning toggles keep 'auto' as a third state ("use the bible
    # default"); they are cast much later, in character_bible_service.
    for field in ('face_detail_pass', 'face_detail_strength', 'instantid_enabled', 'instantid_weight'):
        assert params[field] == 'auto', field


def test_character_params_strips_whitespace_and_lowercases_the_lookup_keys():
    params = GC._character_params(
        {
            'name': '  Mira  ',
            'hair_color': ' Auburn ',
            'genre': ' NOIR ',
            'facial_hair': ' Stubble ',
            'height': 1.82,
            'muscle_mass': 'auto',
            'extra_prompt': '  wet street  ',
            'face_detail_pass': False,
        }
    )

    assert params['name'] == 'Mira'
    assert params['hair_color'] == 'Auburn'
    assert params['genre'] == 'noir'
    assert params['facial_hair'] == 'stubble'
    assert params['height'] == '1.82'
    assert params['muscle_mass'] == 20
    assert params['extra_prompt'] == 'wet street'
    assert params['face_detail_pass'] is False


def test_request_payload_reads_a_json_body_and_offers_no_photos():
    with _APP.test_request_context('/x', method='POST', json={'name': 'Mira', 'kick_lora': False}):
        data, photos = GC._read_request_payload()

    assert data == {'name': 'Mira', 'kick_lora': False}
    assert photos == []


def test_request_payload_reads_the_multipart_params_field_and_the_family_override():
    body = {'params': json.dumps({'name': 'Mira', 'model_family': 'sdxl'}), 'model_family': ' FLUX '}
    with _APP.test_request_context(
        '/x',
        method='POST',
        data=body,
        content_type='multipart/form-data',
    ):
        data, photos = GC._read_request_payload()

    assert data['name'] == 'Mira'
    # A plain form field wins over the one inside the JSON params blob.
    assert data['model_family'] == 'flux'
    assert photos == []


def test_request_payload_ignores_an_unknown_multipart_family_override():
    body = {'params': json.dumps({'model_family': 'sdxl'}), 'model_family': 'midjourney'}
    with _APP.test_request_context('/x', method='POST', data=body, content_type='multipart/form-data'):
        data, _ = GC._read_request_payload()

    assert data['model_family'] == 'sdxl'


def test_photo_inputs_saves_the_uploads_and_normalises_the_locked_fields(monkeypatch):
    monkeypatch.setattr(GC, '_save_uploaded_char_photos', lambda cid, files: ['/d/%s/%s' % (cid, f) for f in files])
    data = {
        'photo_analysis': {'ok': True, 'fields': {'hair_color': 'auburn'}},
        'photo_locked_fields': [' Hair_Color ', '', 'EYE_COLOR'],
    }

    paths, analysis, locked = GC._photo_inputs(data, 'abcdef123456', ['a.png', 'b.png'])

    assert paths == ['/d/abcdef123456/a.png', '/d/abcdef123456/b.png']
    assert analysis == {'ok': True, 'fields': {'hair_color': 'auburn'}}
    assert locked == {'hair_color', 'eye_color'}


def test_photo_inputs_falls_back_to_the_photos_parked_on_disk(monkeypatch):
    seen = []

    def _restore(char_id, preserved):
        seen.append((char_id, preserved))
        return ['/parked/one.png']

    monkeypatch.setattr(GC, '_restore_parked_char_photos', _restore)

    paths, analysis, locked = GC._photo_inputs(
        {'_preserved_photo_paths': ['/parked/one.png'], 'photo_analysis': 'not a dict'},
        'abcdef123456',
        [],
    )

    # A replayed park has no multipart body, so the photos come off disk rather
    # than silently degrading to a Blender render.
    assert paths == ['/parked/one.png']
    assert seen == [('abcdef123456', ['/parked/one.png'])]
    assert analysis == {}
    assert locked == set()


def test_pending_prompt_names_every_descriptor_the_approval_queue_shows():
    params = {
        'gender': 'female',
        'hair_color': 'auburn',
        'eye_color': 'green',
        'skin_tone': 'fair',
        'style': 'noir',
    }

    assert GC._pending_prompt(params, 'Mira', 2) == (
        'Mira — female, auburn hair, green eyes, fair skin, noir; '
        '2 uploaded photo(s); character dataset + LoRA training'
    )


def test_parking_a_request_queues_a_snapshot_without_the_approval_flag(monkeypatch):
    saved = _pending_store(monkeypatch)
    audit = []
    monkeypatch.setattr(GC, '_zero_audit_log', lambda kind, payload: audit.append((kind, payload)))
    data = {'name': 'Mira', 'zero_approved': True, 'model_family': 'flux'}
    params = GC._character_params(data)

    with _APP.test_request_context('/x', method='POST', json=data):
        resp, status = GC._park_character_request(data, params, 'abcdef123456', ['/d/a.png'])
        body = resp.get_json()

    assert status == 202
    assert body['pending'] is True
    assert body['status'] == 'pending_approval'
    assert body['char_id'] == 'abcdef123456'
    assert body['pending_id'].startswith('preq_')

    (row,) = saved[-1]
    assert row['pipeline'] == 'character_generate'
    assert row['status'] == 'pending'
    assert row['label'] == 'Character generation — Mira'
    assert row['char_id'] == 'abcdef123456'
    assert row['body_snapshot']['char_id'] == 'abcdef123456'
    # The replay must go through the approval gate on its own merits.
    assert 'zero_approved' not in row['body_snapshot']
    assert row['body_snapshot']['_preserved_photo_paths'] == ['/d/a.png']
    assert audit == [
        (
            'character_generate_approval_requested',
            {'req_id': row['id'], 'char_id': 'abcdef123456', 'name': 'Mira', 'photos': 1},
        )
    ]


def test_an_unnamed_parked_request_is_labelled_by_its_char_id_prefix(monkeypatch):
    saved = _pending_store(monkeypatch)
    monkeypatch.setattr(GC, '_zero_audit_log', lambda kind, payload: None)
    data = {}

    with _APP.test_request_context('/x', method='POST', json=data):
        GC._park_character_request(data, GC._character_params(data), 'abcdef123456', [])

    (row,) = saved[-1]
    assert row['label'] == 'Character generation — abcdef12'
    assert row['prompt'].startswith('abcdef12 — female, ')
    assert '_preserved_photo_paths' not in row['body_snapshot']


def test_registering_a_job_records_the_render_mode_and_persists_it(monkeypatch):
    saved = []
    monkeypatch.setattr(GC, '_ams_iso', lambda: '2026-10-09T07:00:00+02:00')
    monkeypatch.setattr(GC, '_char_save_state', saved.append)
    monkeypatch.setattr(GC, '_char_gen_jobs', {})

    stop = GC._register_char_job('abcdef123456', {'name': 'Mira'}, 'flux', ['/d/a.png', '/d/b.png'], True)
    job = GC._char_gen_jobs['abcdef123456']

    assert saved == ['abcdef123456']
    assert job['status'] == 'running'
    assert job['stage'] == 'blender_render'
    assert job['current_stage'] == 'init'
    assert job['started'] == '2026-10-09T07:00:00+02:00'
    assert job['render_mode'] == 'uploaded_photos'
    assert job['image_count'] == 2
    assert job['kick_lora'] is True
    assert job['debug_events'] == []
    assert job['stage_timeline'] == []
    assert job['stop_event'] is stop
    assert not stop.is_set()


def test_a_job_without_uploads_renders_in_blender(monkeypatch):
    monkeypatch.setattr(GC, '_ams_iso', lambda: '2026-10-09T07:00:00+02:00')
    monkeypatch.setattr(GC, '_char_save_state', lambda _cid: None)
    monkeypatch.setattr(GC, '_char_gen_jobs', {})

    GC._register_char_job('abcdef123456', {}, 'sdxl', [], False)

    job = GC._char_gen_jobs['abcdef123456']
    assert job['render_mode'] == 'blender'
    assert job['image_count'] == 0
    assert job['kick_lora'] is False


def test_the_event_log_keeps_the_last_two_hundred_events_once_it_passes_three_hundred(monkeypatch):
    monkeypatch.setattr(GC, '_ams_iso', lambda: '2026-10-09T07:00:00+02:00')
    jobs = {'abcdef123456': {'stage': 'lora_train', 'debug_events': [{'msg': 'old %d' % i} for i in range(300)]}}
    monkeypatch.setattr(GC, '_char_gen_jobs', jobs)

    GC._char_emit_event('abcdef123456', 'the 301st event')

    evs = jobs['abcdef123456']['debug_events']
    assert len(evs) == 200
    assert evs[-1] == {
        'ts': '2026-10-09T07:00:00+02:00',
        'level': 'INFO',
        'stage': 'lora_train',  # inherited from the job when the caller gives none
        'msg': 'the 301st event',
    }
    assert evs[0]['msg'] == 'old 101'


def test_an_event_for_an_unknown_job_is_logged_and_dropped(monkeypatch, caplog):
    monkeypatch.setattr(GC, '_ams_iso', lambda: '2026-10-09T07:00:00+02:00')
    monkeypatch.setattr(GC, '_char_gen_jobs', {})

    with caplog.at_level(logging.INFO, logger=GC._zyg_log.name):
        GC._char_emit_event('nosuchjob', 'orphan event', level='WARN', stage='init')

    assert '[ST-CHAR] orphan event' in caplog.text


def test_operator_session_is_false_outside_a_request_context():
    assert GC._operator_session() is False


def test_operator_session_is_true_only_for_an_authenticated_role():
    with _APP.test_request_context('/x', method='POST'):
        assert GC._operator_session() is False
    with _APP.test_request_context('/x', method='POST'):
        from flask import session as _s

        _s['user_role'] = 'operator'
        assert GC._operator_session() is True
