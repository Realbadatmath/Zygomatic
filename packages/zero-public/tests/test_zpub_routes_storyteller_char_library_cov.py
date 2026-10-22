# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline unit coverage for ``zyg_zero.zpub_routes_storyteller.char_library``.

Nothing here touches the network, the GPU or the repository's ``data/`` tree:

* every root the module derives (``_CHAR_DATASET_ROOT``, ``_DATASET_ROOT``,
  ``_LORA_OUTPUT_ROOT``, ``_CHAR_RUNTIME_DIR``, ``_LOG_DIR``) is a module global
  read at call time, so the autouse ``paths`` fixture repoints all five at
  ``tmp_path`` — no reload needed — and ``_zpub_log`` (which appends to
  ``data/runtime/zpub_user_log.jsonl``) becomes a list recorder;
* the ``zyg_workflows`` helpers the bodies import lazily are faked *on the
  ``zyg_workflows`` package*, because ``from pkg import name`` resolves the
  package attribute first — the only hook a function-local import honours
  (``_install(..., name=None)`` makes that import fail instead);
* the two routes run on a bare Flask app with the package blueprint registered;
  Flask-Limiter is never ``init_app``-ed there, so ``@limiter.limit`` is inert,
  and the gate ``_zpub_story_gate`` is a module global, stubbed per test.
"""

import json
import os
import sys
import types

import flask
import pytest
import zyg_workflows
from zyg_zero.zpub_routes_storyteller import char_library as MOD

pytestmark = pytest.mark.timeout(60)

CID_A = 'aaaaaaaaaaaa'
CID_B = 'bbbbbbbbbbbb'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 16


def _boom(*_a, **_kw):
    raise RuntimeError('helper down')


def _fakemod(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(f'zyg_workflows.{name}')
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _install(monkeypatch, **mods) -> None:  # install, or with None break, zyg_workflows.<name>
    for name, mod in mods.items():
        if mod is None:
            monkeypatch.delattr(zyg_workflows, name, raising=False)
            monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', None)
        else:
            monkeypatch.setattr(zyg_workflows, name, mod, raising=False)
            monkeypatch.setitem(sys.modules, f'zyg_workflows.{name}', mod)


def _clf(monkeypatch, ok=True, reason='', families=None, ready=True, **over):
    """Install a ``character_lora_family`` fake with the three helpers used."""
    attrs = {
        'char_lora_usable': lambda cid, fam, runtime: (ok, reason),
        'char_lora_families_for_dir': lambda d: list(families or []),
        'char_lora_ready_for_family': lambda d, fam: ready,
    }
    attrs.update(over)
    _install(monkeypatch, character_lora_family=_fakemod('character_lora_family', **attrs))


def _bare(monkeypatch) -> None:  # no bible service, no sheet pipeline, no char-state service
    _install(monkeypatch, character_bible_service=None, contact_sheet_pipeline=None, char_state_service=None)


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


class _OsListdirRaises:
    """Stand-in for the module's ``os`` global whose ``listdir`` always fails."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, key):
        return getattr(self._real, key)

    def listdir(self, path):
        raise OSError(f'refused: {path}')


class _Resp:
    """Minimal ``requests.Response`` stand-in for the main-app proxy hop."""

    def __init__(self, *, ok=True, ctype='application/json', payload=None, status=200):
        self.ok = ok
        self.status_code = status
        self.headers = {'content-type': ctype}
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def paths(tmp_path, monkeypatch):
    """Repoint every root the module reads and silence its audit log."""
    ds, lo, rt = tmp_path / 'datasets', tmp_path / 'loras', tmp_path / 'runtime'
    for part in (ds, lo, rt):
        part.mkdir()
    monkeypatch.setattr(MOD, '_CHAR_DATASET_ROOT', str(ds))
    monkeypatch.setattr(MOD, '_DATASET_ROOT', str(ds))
    monkeypatch.setattr(MOD, '_LORA_OUTPUT_ROOT', str(lo))
    monkeypatch.setattr(MOD, '_CHAR_RUNTIME_DIR', str(rt))
    monkeypatch.setattr(MOD, '_LOG_DIR', str(rt))
    logged: list = []
    monkeypatch.setattr(MOD, '_zpub_log', lambda event, **kw: logged.append((event, kw)))
    monkeypatch.setattr(MOD, '_bible_name_index', {'built_at': 0.0, 'mtime': None, 'index': {}})
    monkeypatch.setattr(MOD, '_lora_unusable_logged', set())
    return types.SimpleNamespace(ds=ds, lo=lo, rt=rt, logged=logged)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(MOD, '_zpub_story_gate', lambda: None)
    app = flask.Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='char-library-cov')
    app.register_blueprint(MOD.bp)
    return app.test_client()


# ------------------------------------------------------------ slug + name index
SLUGS = [('', ''), ('Nolan Sullivan', 'nolan_sullivan'), ('  Héloïse  Dupré ', 'heloise_dupre'), ('Zoë!', 'zoe')]


@pytest.mark.parametrize(('raw', 'expected'), SLUGS)
def test_slugify_for_filename_table(raw, expected):
    assert MOD._slugify_for_filename(raw) == expected
    assert MOD._slugify_for_filename('a' * 40, max_len=8) == 'a' * 8


def test_build_bible_name_index_skips_unreadable_and_nameless(monkeypatch, paths, tmp_path):
    monkeypatch.setattr(MOD, '_CHAR_DATASET_ROOT', str(tmp_path / 'nope'))
    assert MOD._build_bible_name_index() == {}

    monkeypatch.setattr(MOD, '_CHAR_DATASET_ROOT', str(paths.ds))
    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': 'Hazel', 'identity': {'gender': 'f'}})
    (paths.ds / CID_B).mkdir()
    (paths.ds / CID_B / 'character_bible.json').write_text('{not json', encoding='utf-8')
    _write_json(paths.ds / 'cccccccccccc' / 'character_bible.json', {'display_name': '  '})
    (paths.ds / 'dddddddddddd').mkdir()  # no bible at all

    index = MOD._build_bible_name_index()
    assert list(index) == ['hazel']
    assert index['hazel'][0][0] == CID_A
    assert index['hazel'][0][1]['identity'] == dict.fromkeys(('hair_style', 'hair_color', 'body_build')) | {
        'gender': 'f'
    }


def test_bible_name_lookup_without_ttl_bypasses_the_cache(monkeypatch, paths):
    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': 'Hazel'})
    monkeypatch.setattr(MOD, '_ZPUB_NAME_INDEX_TTL', 0.0)
    assert len(MOD._bible_name_lookup('hazel')) == 1
    assert MOD._bible_name_index['index'] == {}


def test_bible_name_lookup_caches_then_serves_from_memory(monkeypatch, paths):
    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': 'Hazel'})
    calls = []
    real_build = MOD._build_bible_name_index
    monkeypatch.setattr(MOD, '_build_bible_name_index', lambda: calls.append(1) or real_build())
    first = MOD._bible_name_lookup('hazel')
    assert first == MOD._bible_name_lookup('hazel') and len(first) == 1
    assert len(calls) == 1, 'the second lookup must be served from the cache'

    # a root that cannot be stat-ed yields mtime None, which invalidates the cache
    monkeypatch.setattr(MOD, '_CHAR_DATASET_ROOT', str(paths.ds / 'gone'))
    assert MOD._bible_name_lookup('hazel') == []
    assert MOD._bible_name_index['mtime'] is None


def test_list_same_name_bibles_empty_name_self_exclusion_and_failure(monkeypatch, paths):
    assert MOD._list_same_name_bibles(CID_A, '') == []
    for cid in (CID_A, CID_B):
        _write_json(paths.ds / cid / 'character_bible.json', {'display_name': 'Hazel Long'})
    assert [row[0] for row in MOD._list_same_name_bibles(CID_A, ' Hazel Long ')] == [CID_B]

    monkeypatch.setattr(MOD, '_bible_name_lookup', _boom)
    assert MOD._list_same_name_bibles(CID_A, 'Hazel') == []


# -------------------------------------------------------- download-name helpers
def test_display_name_for_download_prefers_bible_then_state_then_empty(paths):
    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': ' Nolan Sullivan '})
    assert MOD._char_display_name_for_download(CID_A) == 'Nolan Sullivan'

    (paths.ds / CID_A / 'character_bible.json').write_text('{broken', encoding='utf-8')
    _write_json(paths.rt / f'char_gen_{CID_A}.json', {'params': {'name': 'Hazel Long'}})
    assert MOD._char_display_name_for_download(CID_A) == 'Hazel Long'

    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': ''})
    (paths.rt / f'char_gen_{CID_A}.json').write_text('{broken', encoding='utf-8')
    assert MOD._char_display_name_for_download(CID_A) == ''


def test_download_name_keeps_the_disk_filename_without_a_usable_name(paths):
    assert MOD._compute_char_download_name(CID_A, 'face_00.png') == 'face_00.png'
    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': '***'})
    assert MOD._compute_char_download_name(CID_A, 'face_00.png') == 'face_00.png'

    # a resolvable name with no sibling is the bare slug, and a missing extension becomes .png
    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': 'Nolan Sullivan'})
    assert MOD._compute_char_download_name(CID_A, 'face_00') == 'nolan_sullivan.png'


def test_download_name_appends_a_discriminator_that_actually_differs(paths):
    ident = {'hair_style': 'Bob', 'hair_color': 'Auburn Red'}
    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': 'Hazel Long', 'identity': ident})
    sibling = {'display_name': 'Hazel Long', 'identity': {'hair_style': 'Bob', 'hair_color': 'auto'}}
    _write_json(paths.ds / CID_B / 'character_bible.json', sibling)
    # hair_style matches the sibling → skipped; hair_color is the first that differs.
    assert MOD._compute_char_download_name(CID_A, 'face_00.jpg') == 'hazel_long_auburn_red.jpg'


def test_download_name_falls_back_to_the_char_id_slice(paths):
    (paths.ds / CID_A).mkdir()
    (paths.ds / CID_A / 'character_bible.json').write_text('{broken', encoding='utf-8')
    _write_json(paths.rt / f'char_gen_{CID_A}.json', {'params': {'name': 'Hazel Long'}})
    _write_json(paths.ds / CID_B / 'character_bible.json', {'display_name': 'Hazel Long'})
    assert MOD._compute_char_download_name(CID_A, 'face_00.png') == f'hazel_long_{CID_A[:6]}.png'


# ------------------------------------------------------------------- char-image
BAD_IMAGES = [('short', 'f.png'), ('AAAAAAAAAAAA', 'f.png'), (CID_A, 'f 0.png'), (CID_A, 'f.gif'), (CID_A, 'ab.png')]


@pytest.mark.parametrize(('cid', 'filename'), BAD_IMAGES)
def test_char_image_404s_on_bad_ids_names_and_missing_files(client, cid, filename):
    assert client.get(f'/api/storyteller/char-image/{cid}/{filename}').status_code == 404


def test_char_image_serves_png_and_jpeg_and_a_friendly_download_name(client, paths):
    (paths.ds / CID_A).mkdir()
    (paths.ds / CID_A / 'face_00.png').write_bytes(PNG)
    (paths.ds / CID_A / 'face_01.jpg').write_bytes(PNG)

    png = client.get(f'/api/storyteller/char-image/{CID_A}/face_00.png')
    assert (png.status_code, png.mimetype, png.data) == (200, 'image/png', PNG)
    jpg = client.get(f'/api/storyteller/char-image/{CID_A}/face_01.jpg')
    assert (jpg.status_code, jpg.mimetype) == (200, 'image/jpeg')

    _write_json(paths.ds / CID_A / 'character_bible.json', {'display_name': 'Nolan Sullivan'})
    resp = client.get(f'/api/storyteller/char-image/{CID_A}/face_00.png?download=yes')
    assert resp.status_code == 200
    assert 'attachment' in resp.headers['Content-Disposition']
    assert 'nolan_sullivan.png' in resp.headers['Content-Disposition']


# ---------------------------------------------------------------- LoRA readiness
@pytest.mark.parametrize('sub', ['', 'lora-weights', 'lora-weights-flux', 'lora-weights-sdxl'])
def test_lora_ready_finds_safetensors_in_every_layout(tmp_path, sub):
    base = tmp_path / sub if sub else tmp_path
    base.mkdir(parents=True, exist_ok=True)
    (base / 'adapter.safetensors').write_bytes(b'x')
    assert MOD._zpub_char_lora_ready(str(tmp_path)) is True


def test_lora_ready_rejects_empty_absent_barren_and_unlistable_dirs(monkeypatch, tmp_path):
    assert MOD._zpub_char_lora_ready('') is False
    assert MOD._zpub_char_lora_ready(str(tmp_path / 'absent')) is False
    (tmp_path / 'checkpoint-1').mkdir()  # an empty checkpoint is not a LoRA
    (tmp_path / 'README.md').write_text('x', encoding='utf-8')
    assert MOD._zpub_char_lora_ready(str(tmp_path)) is False

    ckpt = tmp_path / 'lora-weights' / 'checkpoint-400'  # a populated one is
    ckpt.mkdir(parents=True)
    (ckpt / 'pytorch_lora_weights.safetensors').write_bytes(b'x')
    assert MOD._zpub_char_lora_ready(str(tmp_path)) is True

    monkeypatch.setattr(MOD, 'os', _OsListdirRaises(os))
    assert MOD._zpub_char_lora_ready(str(tmp_path)) is False


@pytest.mark.parametrize('exc', [ValueError, RuntimeError])
def test_lora_usable_falls_back_to_the_disk_check_when_the_helper_fails(monkeypatch, tmp_path, exc):
    def _raise(cid, fam, runtime):
        raise exc('refused')

    _clf(monkeypatch, char_lora_usable=_raise)
    (tmp_path / 'adapter.safetensors').write_bytes(b'x')
    assert MOD._zpub_char_lora_usable(CID_A, str(tmp_path)) == (True, '')


def test_lora_usable_delegates_then_falls_back_without_a_helper_or_gate(monkeypatch, tmp_path):
    _clf(monkeypatch, ok=False, reason='identity QC 0.194')
    assert MOD._zpub_char_lora_usable(CID_A, str(tmp_path), 'flux') == (False, 'identity QC 0.194')

    _clf(monkeypatch, char_lora_usable=None)  # not callable → fall through
    assert MOD._zpub_char_lora_usable(CID_A, str(tmp_path)) == (False, '')
    monkeypatch.setattr(MOD, '_ZPUB_LORA_USABLE_GATE', False)
    assert MOD._zpub_char_lora_usable(CID_A, str(tmp_path)) == (False, '')


# -------------------------------------------------------------- medusa + fields
def test_char_is_medusa_respects_the_flag_and_the_helper(monkeypatch):
    monkeypatch.setattr(MOD, '_ZPUB_LIST_CHARS_MEDUSA_FILTER', False)
    assert MOD._zpub_char_is_medusa(CID_A) is False

    monkeypatch.setattr(MOD, '_ZPUB_LIST_CHARS_MEDUSA_FILTER', True)
    monkeypatch.setattr(MOD, 'is_medusa_char', lambda cid: True)
    assert MOD._zpub_char_is_medusa(CID_A) is True

    monkeypatch.setattr(MOD, 'is_medusa_char', _boom)
    assert MOD._zpub_char_is_medusa(CID_A) is False


def test_identity_fields_defaults_then_presentation_over_style_profile():
    fields = MOD._zpub_identity_fields_from_bible({})
    assert len(fields) == 23
    assert (fields['height'], fields['skin_tone'], fields['facial_hair']) == (1.70, 'medium', 'none')
    assert (fields['muscle_mass'], fields['age'], fields['default_clothing']) == (20, None, '')

    bible = {
        'identity': {'age': 12, 'height_m': 1.52, 'body_build': 'slim', 'hair_color': 'auburn'},
        'style_profile': {'posture': 'slouched', 'accessories': 'satchel'},
        'default_presentation': {'posture': 'upright', 'default_clothing': 'raincoat'},
    }
    fields = MOD._zpub_identity_fields_from_bible(bible)
    assert (fields['age'], fields['height'], fields['muscle_mass'], fields['body_build']) == (12, 1.52, 'slim', 'slim')
    assert (fields['posture'], fields['accessories'], fields['default_clothing']) == ('upright', 'satchel', 'raincoat')


# ---------------------------------------------------------------- preview file
def test_preview_file_delegates_to_the_pipeline_helper(monkeypatch, tmp_path):
    _install(monkeypatch, contact_sheet_pipeline=_fakemod('cs', preview_file_for_library=lambda c, d, m: 'part_01.png'))
    assert MOD._zpub_char_preview_file(CID_A, str(tmp_path)) == 'part_01.png'

    # no delegate but a master sheet on disk: the candidate walk is skipped entirely
    _install(monkeypatch, contact_sheet_pipeline=_fakemod('cs', master_sheet_exists=lambda cid: True))
    assert MOD._zpub_char_preview_file(CID_A, str(tmp_path)) is None


def test_preview_file_walks_the_candidate_order_then_any_png(monkeypatch, tmp_path):
    _install(monkeypatch, contact_sheet_pipeline=_fakemod('cs', master_sheet_exists=lambda cid: False))
    (tmp_path / 'contactsheet_00.png').write_bytes(PNG)
    (tmp_path / 'preview_flux_face.png').write_bytes(PNG)
    assert MOD._zpub_char_preview_file(CID_A, str(tmp_path)) == 'preview_flux_face.png'

    (tmp_path / 'preview_flux_face.png').unlink()
    (tmp_path / 'contactsheet_00.png').unlink()
    (tmp_path / 'zz_other.png').write_bytes(PNG)
    assert MOD._zpub_char_preview_file(CID_A, str(tmp_path)) == 'zz_other.png'

    (tmp_path / 'zz_other.png').unlink()
    _install(monkeypatch, contact_sheet_pipeline=_fakemod('cs', master_sheet_exists=_boom))
    assert MOD._zpub_char_preview_file(CID_A, str(tmp_path)) is None

    _install(monkeypatch, contact_sheet_pipeline=None)
    monkeypatch.setattr(MOD, 'os', _OsListdirRaises(os))
    assert MOD._zpub_char_preview_file(CID_A, str(tmp_path)) is None


# ------------------------------------------------------------------- trained_at
def test_trained_at_prefers_the_state_service_then_walks_the_fallback_chain(monkeypatch, paths, tmp_path):
    _install(monkeypatch, char_state_service=_fakemod('css', _char_library_trained_at=lambda cid: '2026-07-31T10:00'))
    assert MOD._zpub_char_trained_at(CID_A, str(tmp_path)) == '2026-07-31T10:00'

    _install(monkeypatch, char_state_service=_fakemod('css'))  # no _char_library_trained_at
    _write_json(paths.rt / f'char_gen_{CID_A}.json', {'started': '2026-01-01', 'ended': '2026-02-02'})
    assert MOD._zpub_char_trained_at(CID_A, str(tmp_path)) == '2026-02-02'

    _install(monkeypatch, char_state_service=_fakemod('css', _char_library_trained_at=_boom))
    (paths.rt / f'char_gen_{CID_A}.json').write_text('{broken', encoding='utf-8')
    _write_json(tmp_path / 'training_status.json', {'completed_at': '2026-03-03'})
    assert MOD._zpub_char_trained_at(CID_A, str(tmp_path)) == '2026-03-03'

    _install(monkeypatch, char_state_service=_fakemod('css', _char_library_trained_at=lambda cid: ''))
    (tmp_path / 'training_status.json').write_text('{broken', encoding='utf-8')
    assert MOD._zpub_char_trained_at(CID_A, str(tmp_path)) == ''


# -------------------------------------------------------------- entry_from_disk
def test_entry_from_disk_rejects_slug_ids_and_medusa_and_missing_datasets(monkeypatch, paths):
    assert MOD._zpub_char_entry_from_disk('abel_van_haren') is None
    monkeypatch.setattr(MOD, '_zpub_char_is_medusa', lambda cid: True)
    assert MOD._zpub_char_entry_from_disk(CID_A) is None
    monkeypatch.setattr(MOD, '_zpub_char_is_medusa', lambda cid: False)
    assert MOD._zpub_char_entry_from_disk(CID_A) is None  # no dataset dir


def test_entry_from_disk_logs_an_unusable_lora_once(monkeypatch, paths):
    (paths.ds / CID_A).mkdir()
    _clf(monkeypatch, ok=False, reason='declined by the operator')
    assert MOD._zpub_char_entry_from_disk(CID_A) is None
    assert MOD._zpub_char_entry_from_disk(CID_A) is None
    assert [event for event, _ in paths.logged] == ['char_lora_unusable']


@pytest.mark.parametrize(
    ('families', 'ready', 'probe'),
    [(['sdxl'], True, None), ([], False, None), ([], True, _boom)],
)
def test_entry_from_disk_filters_by_model_family(monkeypatch, paths, families, ready, probe):
    (paths.ds / CID_A).mkdir()
    over = {'char_lora_ready_for_family': probe} if probe else {}
    _clf(monkeypatch, families=families, ready=ready, **over)
    assert MOD._zpub_char_entry_from_disk(CID_A, 'flux') is None


def test_entry_from_disk_builds_a_full_card(monkeypatch, paths):
    (paths.ds / CID_A).mkdir()
    _write_json(paths.ds / CID_A / 'manifest.json', {'source': 'contact_sheet', 'render_mode': 'contact_sheet'})
    _clf(monkeypatch, families=['flux', 'sdxl'])
    bible = {
        'display_name': 'Nolan Sullivan',
        'trigger_token': 'ZYG_NOLAN',
        'identity': {'gender': 'male', 'age': 12},
        'style_profile': {'render_style': 'anime', 'genre': 'adventure'},
    }
    _install(
        monkeypatch,
        character_bible_service=_fakemod('cbs', load=lambda cid: bible, format_library_label=lambda n: f'[{n}]'),
        contact_sheet_pipeline=_fakemod(
            'cs',
            library_preview_urls=lambda cid, d, meta: {
                'preview_url': f'/i/{cid}/sheet.png',
                'contact_sheet_url': '/i/cs.png',
            },
            is_contact_sheet_char=lambda cid, meta: True,
        ),
        char_state_service=_fakemod('css', _char_library_trained_at=lambda cid: '2026-07-31'),
    )

    entry = MOD._zpub_char_entry_from_disk(CID_A, 'flux')
    assert entry['char_id'] == CID_A and entry['lora_ready'] is True
    assert (entry['name'], entry['library_label']) == ('Nolan Sullivan', '[Nolan Sullivan]')
    assert (entry['trigger_token'], entry['gender'], entry['model_family']) == ('ZYG_NOLAN', 'male', 'flux')
    assert (entry['preview_url'], entry['contact_sheet_url']) == (f'/i/{CID_A}/sheet.png', '/i/cs.png')
    assert (entry['lora_families'], entry['trained_at'], entry['age']) == (['flux', 'sdxl'], '2026-07-31', 12)
    assert entry['creation_pipeline'] == 'multi_angle_contact_sheet'
    assert (entry['source'], entry['render_mode']) == ('contact_sheet', 'contact_sheet')
    assert (entry['style'], entry['genre']) == ('anime', 'adventure')


def test_entry_from_disk_without_a_bible_service_uses_the_disk_fallbacks(monkeypatch, paths):
    (paths.ds / CID_A).mkdir()
    (paths.ds / CID_A / 'preview_sdxl_front.png').write_bytes(PNG)
    _write_json(paths.rt / f'char_gen_{CID_A}.json', {'params': {'name': 'Hazel Long'}})
    _clf(monkeypatch)
    _bare(monkeypatch)

    entry = MOD._zpub_char_entry_from_disk(CID_A)
    assert (entry['name'], entry['library_label']) == ('Hazel Long', 'Hazel Long')
    assert entry['trigger_token'] == f'ZYG_CHAR_{CID_A[:6].upper()}'
    assert entry['preview_url'] == f'/api/storyteller/char-image/{CID_A}/preview_sdxl_front.png'
    assert (entry['contact_sheet_url'], entry['gender'], entry['model_family']) == (None, 'unknown', 'flux')
    assert (entry['source'], entry['creation_pipeline']) == ('character', 'character_creation')


def test_entry_from_disk_recovers_when_preview_urls_are_blank(monkeypatch, paths):
    (paths.ds / CID_A).mkdir()
    (paths.ds / CID_A / 'face_00_000deg.png').write_bytes(PNG)
    _clf(monkeypatch)
    _install(
        monkeypatch,
        character_bible_service=None,
        char_state_service=None,
        contact_sheet_pipeline=_fakemod(
            'cs',
            library_preview_urls=lambda cid, d, meta: {'preview_url': None, 'contact_sheet_url': None},
            preview_file_for_library=lambda cid, d, meta: 'face_00_000deg.png',
            is_contact_sheet_char=_boom,
        ),
    )
    assert MOD._zpub_char_entry_from_disk(CID_A)['preview_url'].endswith('/face_00_000deg.png')


def test_entry_from_disk_logs_an_identity_merge_failure(monkeypatch, paths):
    (paths.ds / CID_A).mkdir()
    # a corrupt char_gen state and a family probe that raises are both survivable
    (paths.rt / f'char_gen_{CID_A}.json').write_text('{broken', encoding='utf-8')
    _clf(monkeypatch, char_lora_families_for_dir=_boom)
    _bare(monkeypatch)
    monkeypatch.setattr(MOD, '_zpub_identity_fields_from_bible', _boom)

    entry = MOD._zpub_char_entry_from_disk(CID_A)
    assert 'age' not in entry
    assert [event for event, _ in paths.logged] == ['char_identity_fields_fail']


# ------------------------------------------------------------------ list / merge
def test_list_chars_local_is_empty_without_any_root_or_a_readable_one(monkeypatch, tmp_path):
    monkeypatch.setattr(MOD, 'os', _OsListdirRaises(os))  # the roots exist but cannot be listed
    assert MOD._zpub_list_chars_local('flux') == []
    assert MOD._zpub_supplement_list_chars([]) == []

    monkeypatch.setattr(MOD, '_DATASET_ROOT', str(tmp_path / 'a'))
    monkeypatch.setattr(MOD, '_LORA_OUTPUT_ROOT', str(tmp_path / 'b'))
    assert MOD._zpub_list_chars_local() == []


def test_list_chars_local_sorts_newest_first_and_skips_slugs(monkeypatch, paths):
    for cid in (CID_A, CID_B):
        (paths.ds / cid).mkdir()
        (paths.lo / cid).mkdir()
    (paths.ds / 'abel_van_haren').mkdir()
    _clf(monkeypatch)
    _install(monkeypatch, character_bible_service=None, contact_sheet_pipeline=None)
    _install(
        monkeypatch,
        char_state_service=_fakemod(
            'css', _char_library_trained_at=lambda cid: '2026-02-02' if cid == CID_B else '2026-01-01'
        ),
    )
    assert [c['char_id'] for c in MOD._zpub_list_chars_local()] == [CID_B, CID_A]

    merged = MOD._zpub_supplement_list_chars([{'char_id': CID_A, 'trained_at': '2026-09-09'}])
    assert [c['char_id'] for c in merged] == [CID_A, CID_B]  # CID_A is known, only CID_B is added


# -------------------------------------------------------------- list-chars route
def _route_stubs(monkeypatch, resp=None, exc=None):
    monkeypatch.setattr(MOD, '_int_headers', lambda: {'X-Internal': 'test'})

    def _get(url, headers=None, params=None, timeout=None):
        if exc is not None:
            raise exc
        return resp

    monkeypatch.setattr(MOD, '_requests', types.SimpleNamespace(get=_get))


@pytest.mark.parametrize('path', ['/api/storyteller/list-chars', f'/api/storyteller/char-image/{CID_A}/face_00.png'])
def test_both_routes_are_session_gated(client, monkeypatch, path):
    monkeypatch.setattr(MOD, '_zpub_story_gate', lambda: ('nope', 403))
    assert client.get(path).status_code == 403


def test_list_chars_merges_the_main_app_rows(client, monkeypatch, paths):
    (paths.ds / CID_B).mkdir()
    _clf(monkeypatch)
    _bare(monkeypatch)
    rows = [{'char_id': CID_A, 'trained_at': '2026-09-09', 'name': 'Main row'}]
    _route_stubs(monkeypatch, resp=_Resp(payload={'chars': rows}))

    body = client.get('/api/storyteller/list-chars?model_family=flux').get_json()
    assert body['source'] == 'main+local'
    assert body['count'] == 2
    assert sorted(c['char_id'] for c in body['chars']) == sorted([CID_A, CID_B])


def test_list_chars_drops_non_hex_rows_and_unusable_loras(client, monkeypatch, paths):
    _bare(monkeypatch)
    _clf(monkeypatch, ok=False, reason='declined')
    rows = [{'char_id': CID_A, 'trained_at': '2026-09-09'}, {'char_id': 'abel_van_haren', 'trained_at': '2026-08-08'}]
    _route_stubs(monkeypatch, resp=_Resp(payload={'chars': rows}))

    body = client.get('/api/storyteller/list-chars?model_family=bogus').get_json()
    assert body == {'chars': [], 'count': 0, 'source': 'main+local'}
    assert [event for event, _ in paths.logged] == ['char_lora_unusable']


def test_list_chars_logs_a_non_json_proxy_answer_and_uses_disk(client, monkeypatch, paths):
    (paths.ds / CID_A).mkdir()
    _clf(monkeypatch)
    _bare(monkeypatch)
    _route_stubs(monkeypatch, resp=_Resp(ok=False, ctype='text/html', status=502))

    body = client.get('/api/storyteller/list-chars').get_json()
    assert body['source'] == 'local'
    assert [c['char_id'] for c in body['chars']] == [CID_A]
    assert paths.logged[0] == ('list_chars_non_json', {'status': 502, 'ctype': 'text/html'})


def test_list_chars_logs_a_proxy_exception_and_falls_back_to_an_empty_disk(client, monkeypatch, paths):
    _clf(monkeypatch)
    _route_stubs(monkeypatch, exc=OSError('connection refused'))

    body = client.get('/api/storyteller/list-chars').get_json()
    assert body == {'chars': [], 'count': 0, 'source': 'local'}
    assert paths.logged[0][0] == 'list_chars_proxy_fail'
    assert 'connection refused' in paths.logged[0][1]['error']


def test_list_chars_medusa_filter_failure_is_fail_safe(client, monkeypatch, paths):
    monkeypatch.setattr(MOD, '_ZPUB_LORA_USABLE_GATE', False)
    monkeypatch.setattr(MOD, 'filter_out_medusa', _boom)
    _route_stubs(monkeypatch, resp=_Resp(payload={'chars': [{'char_id': CID_A, 'trained_at': '2026-09-09'}]}))

    body = client.get('/api/storyteller/list-chars').get_json()
    assert [c['char_id'] for c in body['chars']] == [CID_A]
