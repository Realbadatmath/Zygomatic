# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage tests for :mod:`zyg_workflows.animal_bible_service`.

The module's own ``_DATASET_ROOT`` / ``_OUTPUT_ROOT`` constants are redirected
into ``tmp_path``, so no tracked data directory is ever touched.
"""

from __future__ import annotations

import json
import os
import sys
import types
from datetime import datetime, timezone

import pytest

from zyg_workflows import animal_bible_service as mod


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Redirect the dataset and output roots into tmp_path."""
    ds = tmp_path / 'datasets'
    out = tmp_path / 'outputs'
    ds.mkdir()
    out.mkdir()
    monkeypatch.setattr(mod, '_DATASET_ROOT', str(ds))
    monkeypatch.setattr(mod, '_OUTPUT_ROOT', str(out))
    return types.SimpleNamespace(datasets=ds, outputs=out, tmp=tmp_path)


def _write_bible(roots, animal_id, package):
    p = roots.datasets / animal_id / mod._BIBLE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(package), encoding='utf-8')
    return p


def _big(path, size=20_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)
    return str(path)


_AUTOISH = [None, '', '  ', 'auto', 'AUTO', 'none-selected', 'default', '(auto)']


@pytest.mark.parametrize('value', _AUTOISH)
def test_is_auto_true(value):
    assert mod._is_auto(value) is True


@pytest.mark.parametrize('value', ['tabby', 0, 12, []])
def test_is_auto_false(value):
    assert mod._is_auto(value) is False


@pytest.mark.parametrize(
    'animal_id,expected',
    [('wolf', 'ZYG_ANIMAL_WOLF'), ('', 'ZYG_ANIMAL_'), (None, 'ZYG_ANIMAL_'), ('verylongname', 'ZYG_ANIMAL_VERYLO')],
)
def test_trigger_for(animal_id, expected):
    assert mod.trigger_for(animal_id) == expected


def test_bible_path(roots):
    assert mod.bible_path('wolf') == os.path.join(str(roots.datasets), 'wolf', 'animal_bible.json')


def test_utc_now_with_zone_is_iso_with_millis(monkeypatch):
    stamp = mod._utc_now()
    assert datetime.fromisoformat(stamp).tzinfo is not None and '.' in stamp
    monkeypatch.setattr(mod, '_AMS_TZ', None)
    assert datetime.fromisoformat(mod._utc_now()).utcoffset() == timezone.utc.utcoffset(None)


def test_utc_now_zone_failure_falls_back_to_utc(monkeypatch, caplog):
    monkeypatch.setattr(mod, '_AMS_TZ', 'not-a-timezone')
    with caplog.at_level('DEBUG', logger=mod.__name__):
        stamp = mod._utc_now()
    assert datetime.fromisoformat(stamp).utcoffset() == timezone.utc.utcoffset(None)
    assert 'Amsterdam timestamp unavailable' in caplog.text


_SIZES = [('tiny', 'tiny miniature-sized animal'), ('Large', 'large-sized animal'), ('huge', 'very large animal')]


@pytest.mark.parametrize('size,expected', [*_SIZES, ('weird', 'weird size'), ('', ''), (None, '')])
def test_size_text(size, expected):
    assert mod._size_text(size) == expected


@pytest.mark.parametrize(
    'ident,expected',
    [
        ({'species': 'dog', 'breed': 'collie'}, 'collie dog'),
        ({'breed': 'collie'}, 'collie'),
        ({'species': 'dog'}, 'dog'),
        ({'species': 'dog', 'breed': None}, 'dog'),
        ({}, 'animal'),
    ],
)
def test_species_noun(ident, expected):
    assert mod._species_noun(ident) == expected


@pytest.mark.parametrize(
    'color,pattern,expected',
    [
        ('black', 'brindle', 'black brindle coat'),
        ('black', '', 'black coat'),
        ('', 'tabby', 'tabby coat pattern'),
        ('none', 'n/a', ''),
        (None, None, ''),
    ],
)
def test_coat_phrase(color, pattern, expected):
    assert mod._coat_phrase(color, pattern) == expected


def test_pick_reference_images_priority_only(tmp_path):
    assert mod._pick_reference_images('') == []
    assert mod._pick_reference_images(str(tmp_path / 'nope')) == []
    d = tmp_path / 'ds'
    for name in ('preview_sdxl_front.png', 'preview_sdxl_side.png'):
        _big(d / name)
    got = mod._pick_reference_images(str(d), limit=2)
    assert [os.path.basename(p) for p in got] == ['preview_sdxl_front.png', 'preview_sdxl_side.png']


def test_pick_reference_images_falls_back_to_extras(tmp_path):
    d = tmp_path / 'ds'
    _big(d / 'preview_flux_front.png')
    _big(d / 'a_shot.png')
    _big(d / 'b_shot.JPG')
    _big(d / 'tiny.jpeg', size=10)  # below the size filter
    (d / 'notes.txt').write_text('ignored', encoding='utf-8')
    got = [os.path.basename(p) for p in mod._pick_reference_images(str(d))]
    assert got == ['preview_flux_front.png', 'a_shot.png', 'b_shot.JPG']
    assert len(mod._pick_reference_images(str(d), limit=2)) == 2


def _fake_trainer_module(**attrs):
    m = types.ModuleType('zyg_workflows.lora_trainer_service')
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _install_trainer(monkeypatch, module):
    import zyg_workflows

    monkeypatch.setitem(sys.modules, 'zyg_workflows.lora_trainer_service', module)
    monkeypatch.setattr(zyg_workflows, 'lora_trainer_service', module, raising=False)


def test_find_lora_path_via_trainer_service(monkeypatch, roots):
    trainer = types.SimpleNamespace(get_lora_path=lambda aid, model_family=None: f'/l/{aid}-{model_family}')
    _install_trainer(monkeypatch, _fake_trainer_module(get_trainer=lambda: trainer))
    monkeypatch.setattr(mod, '_OUTPUT_ROOT', str(roots.outputs))
    import importlib.util as ilu

    monkeypatch.setattr(ilu, 'find_spec', lambda name: object())
    assert mod._find_lora_path('wolf', 'FLUX') == '/l/wolf-flux'


def test_find_lora_path_checkpoint_fallback(monkeypatch, roots):
    import importlib.util as ilu

    monkeypatch.setattr(ilu, 'find_spec', lambda name: None)
    _install_trainer(
        monkeypatch,
        _fake_trainer_module(_find_latest_checkpoint=lambda out, model_family=None: f'{out}:{model_family}'),
    )
    got = mod._find_lora_path('wolf', 'sdxl')
    assert got == os.path.join(str(roots.outputs), 'wolf') + ':sdxl'


def test_find_lora_path_directory_walk(monkeypatch, roots):
    import importlib.util as ilu

    def _boom(name):
        raise RuntimeError('no importlib here')

    monkeypatch.setattr(ilu, 'find_spec', _boom)
    _install_trainer(
        monkeypatch,
        _fake_trainer_module(_find_latest_checkpoint=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('nope'))),
    )
    base = roots.outputs / 'wolf' / 'lora-weights-flux'
    _big(base / 'checkpoint-100' / 'a.safetensors')
    best = _big(base / 'checkpoint-900' / 'b.safetensors')
    _big(base / 'readme.txt')
    assert mod._find_lora_path('wolf', 'flux') == best


def test_find_lora_path_returns_none_when_nothing_on_disk(monkeypatch, roots):
    import importlib.util as ilu

    monkeypatch.setattr(ilu, 'find_spec', lambda name: None)
    _install_trainer(monkeypatch, _fake_trainer_module())
    assert mod._find_lora_path('ghost') is None


def test_default_package_shape():
    pkg = mod.default_package('wolf', display_name='Wolfie', species='wolf')
    assert pkg['schema_version'] == mod._SCHEMA_VERSION
    assert pkg['trigger_token'] == 'ZYG_ANIMAL_WOLF'
    assert pkg['display_name'] == 'Wolfie'
    assert pkg['identity']['species'] == 'wolf'
    assert pkg['identity']['quadruped'] is True
    assert pkg['conditioning']['instantid_enabled'] is False
    assert pkg['conditioning']['face_detail_pass'] is False
    assert pkg['style_profile']['render_style'] == 'photorealistic'
    assert pkg['generation_stats'] == {'total_stills': 0, 'drift_retries': 0}
    blank = mod.default_package('x')
    assert (blank['display_name'], blank['species'], blank['identity']['species']) == ('', '', '')


def test_identity_prompt_prefix_full():
    assert mod.identity_prompt_prefix(None) == ''
    assert mod.identity_prompt_prefix({}) == ''
    pkg = {
        'trigger_token': 'ZYG_ANIMAL_WOLF',
        'identity': {
            'species': 'wolf',
            'breed': 'arctic',
            'coat_color': 'white',
            'coat_pattern': 'solid',
            'body_type': 'lean',
            'size': 'large',
            'distinctive_marks': 'torn ear',
            'quadruped': True,
        },
        'style_profile': {'render_style': 'photorealistic'},
    }
    out = mod.identity_prompt_prefix(pkg)
    assert out.startswith('ZYG_ANIMAL_WOLF, arctic wolf, photorealistic')
    for frag in ('white solid coat', 'lean build', 'large-sized animal', 'torn ear', 'four-legged quadruped animal'):
        assert frag in out


def test_identity_prompt_prefix_minimal_and_non_quadruped():
    pkg = {
        'identity': {'body_type': 'stocky body', 'distinctive_marks': 'none', 'quadruped': False},
        'style_profile': {},
    }
    out = mod.identity_prompt_prefix(pkg)
    assert out == 'animal, stocky body, natural animal anatomy'


def test_presentation_from_package():
    assert mod._presentation_from_package(None) == {}
    assert mod._presentation_from_package({}) == {}
    pkg = {'default_presentation': {'pose': ' alert ', 'environment_hint': ''}}
    assert mod._presentation_from_package(pkg) == {'pose': 'alert'}
    assert mod.presentation_prompt_fragment(None) == ''


def test_presentation_prompt_fragment_variants():
    pkg = {
        'default_presentation': {'pose': 'standing', 'environment_hint': 'snowy forest'},
        'style_profile': {'lighting_profile': 'overcast daylight'},
    }
    assert mod.presentation_prompt_fragment(pkg) == 'standing, snowy forest'
    with_light = mod.presentation_prompt_fragment(pkg, include_lighting=True)
    assert with_light.endswith('overcast daylight')


def test_presentation_prompt_fragment_adds_pose_word_and_skips_none_env():
    pkg = {'default_presentation': {'pose': 'alert', 'environment_hint': 'none'}, 'style_profile': {}}
    assert mod.presentation_prompt_fragment(pkg, include_lighting=True) == 'alert pose'


@pytest.mark.parametrize(
    'fn',
    [
        lambda: mod.skin_tone_negatives('deep', 'any'),
        lambda: mod.hair_color_negatives('black'),
        lambda: mod.age_negatives(42),
        lambda: mod.preview_expression_boost({'a': 1}),
        lambda: mod.face_detail_wildcard_for_params(None),
    ],
)
def test_human_only_helpers_are_empty_strings(fn):
    assert fn() == ''


def test_negative_prompt_no_package():
    assert mod.storyteller_face_detail_enabled() is mod.storyteller_face_detail_enabled('closeup', 'joy') is False
    out = mod.negative_prompt_for_package(None)
    assert out.startswith('blurry, low quality, deformed')
    assert mod._SOLO_SUBJECT_NEG in out
    assert mod._ANIMAL_ANATOMY_NEG in out
    assert mod._ANTHRO_NEG in out
    assert mod._PREVIEW_SCENE_NEG not in out
    assert mod._PHOTOREAL_FUR_NEG not in out


def test_negative_prompt_default_base_with_studio_preview_and_photoreal():
    pkg = {'conditioning': {}, 'style_profile': {'render_style': 'Photorealistic'}}
    out = mod.negative_prompt_for_package(pkg, studio_preview=True)
    assert 'jpeg artifacts' in out
    assert mod._PREVIEW_SCENE_NEG in out
    assert mod._PHOTOREAL_FUR_NEG in out


def test_negative_prompt_custom_base_suppresses_duplicates():
    custom = 'multiple animals, office, desk, extra legs, anthropomorphic, plastic-looking fur'
    pkg = {'conditioning': {'negative_prompt': custom}, 'style_profile': {'render_style': 'photorealistic'}}
    assert mod.negative_prompt_for_package(pkg, studio_preview=True) == custom


def test_preview_studio_suffix():
    assert 'no furniture' in mod.preview_studio_suffix(None)
    out = mod.preview_studio_suffix({'style_profile': {'lighting_profile': 'rim light'}})
    assert out.endswith('rim light')


def test_quality_suffix_variants():
    assert mod.quality_suffix_for_package(None) == 'highly detailed, sharp focus, natural lighting'
    assert 'realistic wildlife photography' in mod.quality_suffix_for_package({'conditioning': {}})
    assert mod.quality_suffix_for_package({'conditioning': {'quality_suffix': ' crisp 8k '}}) == 'crisp 8k'
    assert mod.quality_suffix() == mod.quality_suffix_for_package(None)
    assert mod.quality_suffix({'conditioning': {'quality_suffix': 'x'}}) == 'x'


def test_indoor_style_suffix():
    assert mod.wants_visible_smile_package({'identity': {}}) is False
    assert mod.indoor_style_suffix(None).startswith('cinematic set')
    assert mod.indoor_style_suffix({'style_profile': {}}) == (
        'photorealistic, consistent animal identity, natural environment'
    )
    assert mod.indoor_style_suffix({'style_profile': {'lighting_profile': 'warm'}}).endswith('warm')


def test_get_master_reference(tmp_path):
    assert mod.get_master_reference(None) is mod.get_master_reference({'conditioning': {}}) is None
    ref = _big(tmp_path / 'ref.png')
    assert mod.get_master_reference({'conditioning': {'master_reference_image': ref}}) == ref
    pkg = {
        'conditioning': {
            'master_reference_image': str(tmp_path / 'gone.png'),
            'ipadapter_reference_images': ['', str(tmp_path / 'gone2.png'), ref],
        }
    }
    assert mod.get_master_reference(pkg) == ref


def test_migrate_package_fills_defaults():
    assert mod.migrate_package(None) is None
    pkg = mod.migrate_package({'animal_id': 'wolf'})
    assert pkg['identity']['quadruped'] is True
    assert pkg['style_profile'] == {'render_style': 'photorealistic', 'restyle': None}
    assert pkg['conditioning']['instantid_enabled'] is False
    assert pkg['conditioning']['model_family'] == 'flux'
    assert pkg['conditioning']['lora_scale'] == 0.85
    assert pkg['conditioning']['ipadapter_scale'] == 0.65
    assert pkg['scene_history'] == []
    assert pkg['schema_version'] == mod._SCHEMA_VERSION


def test_migrate_package_keeps_existing_values():
    pkg = mod.migrate_package({'conditioning': {'model_family': 'sdxl', 'lora_scale': 0.5}})
    assert (pkg['conditioning']['model_family'], pkg['conditioning']['lora_scale']) == ('sdxl', 0.5)


def test_load_missing_or_corrupt_returns_none(roots):
    assert mod.load('ghost') is None
    p = roots.datasets / 'wolf' / mod._BIBLE_FILENAME
    p.parent.mkdir(parents=True)
    p.write_text('{not json', encoding='utf-8')
    assert mod.load('wolf') is None


def test_load_repairs_animal_id_and_migrates(roots):
    _write_bible(roots, 'wolf', {'animal_id': 'stale'})
    pkg = mod.load('wolf')
    assert pkg['animal_id'] == 'wolf'
    assert pkg['identity']['quadruped'] is True


def test_save_round_trip(roots):
    with pytest.raises(ValueError, match='animal_id required'):
        mod.save({})
    pkg = mod.default_package('wolf', species='wolf')
    path = mod.save(pkg)
    assert path == mod.bible_path('wolf')
    assert json.loads(open(path, encoding='utf-8').read())['animal_id'] == 'wolf'
    assert pkg['updated_at']


def test_save_delivered_attributes_win_over_spec(roots):
    synced = {'attributes_synced_from_anchor': True, 'coat_color': 'grey', 'coat_pattern': ' '}
    _write_bible(roots, 'wolf', {'animal_id': 'wolf', 'identity': synced})
    incoming = {'animal_id': 'wolf', 'identity': {'coat_color': 'black', 'coat_pattern': 'brindle'}}
    mod.save(incoming)
    assert incoming['identity']['coat_color'] == 'grey'
    assert incoming['identity']['coat_pattern'] == 'brindle'
    assert incoming['identity']['attributes_synced_from_anchor'] is True


def test_save_sync_writer_is_not_overridden(roots):
    _write_bible(
        roots, 'wolf', {'animal_id': 'wolf', 'identity': {'attributes_synced_from_anchor': True, 'coat_color': 'grey'}}
    )
    incoming = {'animal_id': 'wolf', 'identity': {'attributes_synced_from_anchor': True, 'coat_color': 'black'}}
    mod.save(incoming)
    assert incoming['identity']['coat_color'] == 'black'


def test_save_survives_a_broken_load(roots, monkeypatch):
    def _boom(_aid):
        raise RuntimeError('unreadable')

    monkeypatch.setattr(mod, 'load', _boom)
    assert mod.save({'animal_id': 'wolf'}) == mod.bible_path('wolf')


def test_sync_delivered_attributes_without_bible(roots):
    assert mod.sync_delivered_attributes('ghost', {'coat_color': 'grey'}) is None


def test_sync_delivered_attributes_no_change(roots):
    _write_bible(roots, 'wolf', {'animal_id': 'wolf', 'identity': {'coat_color': 'grey'}})
    mod.sync_delivered_attributes(
        'wolf',
        {'coat_color': 'GREY', 'coat_pattern': 'unclear', 'size': 'large', 'breed': ''},
    )
    assert 'attributes_synced_from_anchor' not in mod.load('wolf')['identity']


def test_sync_delivered_attributes_writes_and_logs(roots):
    _write_bible(roots, 'wolf', {'animal_id': 'wolf', 'identity': {'coat_color': 'black'}})
    seen: list[str] = []
    mod.sync_delivered_attributes('wolf', {'coat_color': ' Grey ', 'coat_pattern': None}, log_fn=seen.append)
    stored = mod.load('wolf')['identity']
    assert stored['coat_color'] == 'grey'
    assert stored['attributes_synced_from_anchor'] is True
    assert "coat_color: 'black' -> 'grey'" in seen[0]


def _fake_comfy(monkeypatch):
    import zyg_workflows

    m = types.ModuleType('zyg_workflows.comfy_generation_service')
    m._SDXL_TRAIN_REPO_ID = 'repo/sdxl'
    m._SDXL_ALIGNED_CKPT = 'aligned.safetensors'
    m._SDXL_FALLBACK_CKPT = 'fallback.safetensors'
    m._SDXL_ANIMATED_CKPT = 'animated.safetensors'
    monkeypatch.setitem(sys.modules, 'zyg_workflows.comfy_generation_service', m)
    monkeypatch.setattr(zyg_workflows, 'comfy_generation_service', m, raising=False)
    return m


def test_update_lora_flux_leg(roots, tmp_path):
    lora = _big(tmp_path / 'wolf.safetensors')
    master = _big(tmp_path / 'master.png')
    seen: list[str] = []
    mod.update_lora(
        'wolf',
        'FLUX',
        lora,
        sdxl_checkpoint='ckpt.safetensors',
        sdxl_render_style='animated',
        master_reference_image=master,
        log_fn=seen.append,
    )
    cond = mod.load('wolf')['conditioning']
    assert cond['model_family'] == 'flux'
    assert cond['flux_lora_path'] == lora
    assert cond['lora_path'] == lora
    assert cond['sdxl_checkpoint'] == 'ckpt.safetensors'
    assert cond['sdxl_render_style'] == 'animated'
    assert cond['master_reference_image'] == master
    assert seen == [f'Animal bible: flux lora_path -> {lora}']


def test_update_lora_unknown_family_and_missing_file(roots):
    mod.update_lora('wolf', 'midjourney', '/does/not/exist.safetensors')
    cond = mod.load('wolf')['conditioning']
    assert cond['model_family'] == 'flux'
    assert cond['lora_path'] is None
    assert cond['flux_lora_path'] is None


def test_update_lora_sdxl_without_comfy_honours_explicit_args(roots, monkeypatch):
    import zyg_workflows

    monkeypatch.setitem(sys.modules, 'zyg_workflows.comfy_generation_service', None)
    monkeypatch.delattr(zyg_workflows, 'comfy_generation_service', raising=False)
    mod.update_lora('wolf', 'sdxl', None, sdxl_checkpoint='manual.safetensors', sdxl_render_style='')
    cond = mod.load('wolf')['conditioning']
    assert cond['model_family'] == 'sdxl'
    assert cond['sdxl_checkpoint'] == 'manual.safetensors'
    assert cond['sdxl_render_style'] == ''
    assert cond['lora_path'] is None


def test_update_lora_sdxl_defaults_to_the_animated_checkpoint(roots, monkeypatch, tmp_path):
    _fake_comfy(monkeypatch)
    monkeypatch.delenv('ZYG_SDXL_ANIMATED', raising=False)
    lora = _big(tmp_path / 'wolf_sdxl.safetensors')
    mod.update_lora('wolf', 'sdxl', lora)
    cond = mod.load('wolf')['conditioning']
    assert cond['sdxl_train_repo'] == 'repo/sdxl'
    assert cond['sdxl_lora_path'] == lora
    assert cond['sdxl_checkpoint'] == 'animated.safetensors'
    assert cond['sdxl_render_style'] == 'animated'
    assert cond['lora_path'] == lora


def test_update_lora_sdxl_overwrites_a_stale_photoreal_base(roots, monkeypatch):
    _fake_comfy(monkeypatch)
    _write_bible(
        roots,
        'wolf',
        {
            'animal_id': 'wolf',
            'conditioning': {'sdxl_checkpoint': 'fallback.safetensors', 'flux_lora_path': '/flux.safetensors'},
        },
    )
    mod.update_lora('wolf', 'sdxl', None)
    cond = mod.load('wolf')['conditioning']
    assert cond['sdxl_checkpoint'] == 'animated.safetensors'
    assert 'lora_path' not in cond  # FLUX stays primary, so the shared key is untouched
    assert cond['flux_lora_path'] == '/flux.safetensors'


def test_update_lora_sdxl_animated_disabled_uses_aligned(roots, monkeypatch):
    _fake_comfy(monkeypatch)
    monkeypatch.setenv('ZYG_SDXL_ANIMATED', '0')
    mod.update_lora('wolf', 'sdxl', None)
    cond = mod.load('wolf')['conditioning']
    assert cond['sdxl_checkpoint'] == 'aligned.safetensors'
    assert cond['sdxl_render_style'] == 'animated'


def test_update_lora_sdxl_restyle_uses_the_style_profile_checkpoint(roots, monkeypatch, tmp_path):
    _fake_comfy(monkeypatch)
    fake_pkg_dir = tmp_path / 'pkgdir'
    profiles = fake_pkg_dir / 'data' / 'runtime' / 'character_style_profiles.json'
    profiles.parent.mkdir(parents=True)
    profiles.write_text(
        json.dumps({'profiles': {'arcane_animation': {'render_checkpoint': 'realistic_base.safetensors'}}}),
        encoding='utf-8',
    )
    monkeypatch.setattr(mod, '__file__', str(fake_pkg_dir / 'animal_bible_service.py'))
    _write_bible(
        roots,
        'wolf',
        {
            'animal_id': 'wolf',
            'style_profile': {'restyle': 'arcane_animation'},
            'conditioning': {'sdxl_render_style': 'animated'},
        },
    )
    mod.update_lora('wolf', 'sdxl', None, sdxl_checkpoint='ignored.safetensors')
    cond = mod.load('wolf')['conditioning']
    assert cond['sdxl_checkpoint'] == 'realistic_base.safetensors'
    assert 'sdxl_render_style' not in cond


def test_update_lora_sdxl_restyle_without_profiles_file(roots, monkeypatch, tmp_path):
    _fake_comfy(monkeypatch)
    monkeypatch.setattr(mod, '__file__', str(tmp_path / 'absent' / 'animal_bible_service.py'))
    _write_bible(roots, 'wolf', {'animal_id': 'wolf', 'style_profile': {'restyle': 'arcane_animation'}})
    mod.update_lora('wolf', 'sdxl', None)
    assert mod.load('wolf')['conditioning']['sdxl_checkpoint'] == 'animated.safetensors'


def test_record_scene_shot_appends_and_counts(roots):
    assert mod.record_scene_shot('ghost', 's1', '/img.png') is None
    mod.save(mod.default_package('wolf'))
    mod.record_scene_shot('wolf', 's1', '/img.png', prompt='p' * 300, seed=7, drift_score=0.25)
    pkg = mod.load('wolf')
    entry = pkg['scene_history'][-1]
    assert entry['scene_id'] == 's1'
    assert entry['image_path'] == '/img.png'
    assert len(entry['prompt_snippet']) == 200
    assert entry['seed'] == 7
    assert entry['drift_score'] == 0.25
    assert pkg['generation_stats']['total_stills'] == 1
    mod.record_scene_shot('wolf', 's2', '/img2.png')
    assert mod.load('wolf')['generation_stats']['total_stills'] == 2


def test_record_scene_shot_history_is_capped(roots):
    pkg = mod.default_package('wolf')
    pkg['scene_history'] = [{'scene_id': f's{i}'} for i in range(250)]
    mod.save(pkg)
    mod.record_scene_shot('wolf', 'latest', '/img.png')
    history = mod.load('wolf')['scene_history']
    assert len(history) == 200
    assert history[-1]['scene_id'] == 'latest'
