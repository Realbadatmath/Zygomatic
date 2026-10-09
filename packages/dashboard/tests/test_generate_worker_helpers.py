# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the character-generate worker stage helpers.

The helpers were bodies inside the 521-line `generate_worker._bg_generate`
closure until the 2026-10-09 function split, so this file is the first time any
of this logic is exercised in isolation. Nothing here touches the GPU, the
network or a service.

WHY THE MODULE IS LOADED BY PATH
--------------------------------
`zyg_dashboard.bp_storyteller.__init__` imports crewai_web_gui, which builds the
Flask app and starts ~19 production watcher threads at import time, and the api
harness must be the one that imports it (see tests/api/conftest.py: it suppresses
the threads and supplies FLASK_SECRET_KEY first — importing it here instead makes
every api test fail). The stage helpers only need those package names to EXIST,
so the module is loaded against stub globals and each test monkeypatches the
collaborator it cares about.
"""

import importlib.util
import pathlib
import sys
import types

_MOD_NAME = 'generate_worker_stages_under_test'
_MOD_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / 'src'
    / 'zyg_dashboard'
    / 'bp_storyteller'
    / 'generate_worker_stages.py'
)

_STUBBED_CALLABLES = (
    '_apply_gpu_power_limit',
    '_char_lora_train_families',
    '_char_mark_done',
    '_char_mark_error',
    '_char_render_style',
    '_char_stage_end',
    '_char_stage_start',
    '_char_train_lora_for_family',
    '_have_usable_char_preview',
    '_normalize_char_model_family',
    '_render_char_preview_images',
    '_resolve_char_model_family',
)


def _load_stages():
    """Load generate_worker_stages.py against stub package globals.

    Returns the loaded module. `sys.modules` is left exactly as it was found:
    the stubs exist only for the duration of the load, so no other test module
    can ever see them.
    """
    keys = (
        'zyg_dashboard',
        'zyg_dashboard.bp_storyteller',
        'zyg_dashboard.bp_storyteller.guards',
        _MOD_NAME,
    )
    saved = [(k, sys.modules.get(k, None), k in sys.modules) for k in keys]

    def _unused(*_a, **_kw):
        """Stand-in for a package collaborator no test monkeypatched."""
        raise AssertionError('the stage helper called an unstubbed collaborator')

    root = types.ModuleType('zyg_dashboard')
    root.__path__ = []
    pkg = types.ModuleType('zyg_dashboard.bp_storyteller')
    for name in _STUBBED_CALLABLES:
        setattr(pkg, name, _unused)
    pkg._char_gen_jobs = {}
    pkg._dsl = None
    pkg.gui_state = types.SimpleNamespace(_CALIBRATION={})
    guards = types.ModuleType('zyg_dashboard.bp_storyteller.guards')
    guards._CHARS_DATASET_ROOT = '/tmp/zyg-test-chars-dataset-root'
    sys.modules['zyg_dashboard'] = root
    sys.modules['zyg_dashboard.bp_storyteller'] = pkg
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


ST = _load_stages()


def _ctx(**kw):
    """Build a CharGenContext with harmless defaults and a recording emit."""
    log: list[tuple] = []
    base = {
        'info': {},
        'char_id': 'abcdef1234',
        'params': {},
        'kick_lora': True,
        'uploaded_image_paths': [],
        'photo_analysis': None,
        'emit': lambda m, **kws: log.append((m, kws.get('level'), kws.get('stage'))),
        'check_stop': lambda: None,
        'job': {},
    }
    base.update(kw)
    return ST.CharGenContext(**base), log


def test_template_captions_write_one_file_per_image_and_cycle_the_suffixes(tmp_path):
    paths = []
    for i in range(9):
        p = tmp_path / f'img_{i}.png'
        p.write_bytes(b'')
        paths.append(str(p))

    n = ST.write_template_captions(paths, {'gender': 'male', 'hair_color': 'black'}, 'zygchar0001')

    assert n == 9
    first = (tmp_path / 'img_0.txt').read_text(encoding='utf-8')
    assert first.startswith('zygchar0001 male, black hair, ')
    assert first.endswith(ST.CAPTION_SUFFIXES[0])
    # 7 suffixes, 9 images: the 8th image restarts the cycle.
    assert (tmp_path / 'img_7.txt').read_text(encoding='utf-8').endswith(ST.CAPTION_SUFFIXES[0])
    assert (tmp_path / 'img_8.txt').read_text(encoding='utf-8').endswith(ST.CAPTION_SUFFIXES[1])


def test_template_captions_fall_back_to_the_default_gender_and_hair(tmp_path):
    p = tmp_path / 'only.jpg'
    p.write_bytes(b'')

    ST.write_template_captions([str(p)], {}, 'tok')

    assert (tmp_path / 'only.txt').read_text(encoding='utf-8').startswith('tok female, brown hair, ')


def test_gate_face_image_prefers_the_first_candidate_that_exists(tmp_path):
    assert ST.find_gate_face_image(str(tmp_path)) == ''
    (tmp_path / 'preview_sdxl_front.png').write_bytes(b'')
    assert ST.find_gate_face_image(str(tmp_path)) == str(tmp_path / 'preview_sdxl_front.png')
    (tmp_path / 'preview_flux_face.png').write_bytes(b'')
    assert ST.find_gate_face_image(str(tmp_path)) == str(tmp_path / 'preview_flux_face.png')


def test_dedup_ceiling_is_pack_dependent_and_env_overridable(monkeypatch):
    monkeypatch.delenv('ZYG_ANCHOR_DEDUP_MAX_SIM', raising=False)
    monkeypatch.delenv('ZYG_IDQC_PACK', raising=False)
    assert ST.dedup_similarity_ceiling() == 0.45
    monkeypatch.setenv('ZYG_IDQC_PACK', ' auraface ')
    assert ST.dedup_similarity_ceiling() == 0.489
    monkeypatch.setenv('ZYG_ANCHOR_DEDUP_MAX_SIM', '0.6')
    assert ST.dedup_similarity_ceiling() == 0.6


def test_preview_quality_ok_accepts_a_skipped_render_with_files_on_disk():
    assert ST.preview_quality_ok({'preview_quality_ok': True}, False, True) is True
    assert ST.preview_quality_ok({'skipped': True}, True, True) is True
    assert ST.preview_quality_ok({'skipped': True}, False, True) is False
    # previews exist and no LoRA was asked for → good enough
    assert ST.preview_quality_ok({}, True, False) is True
    assert ST.preview_quality_ok({}, True, True) is False


def test_final_error_message_joins_lora_and_preview_failures():
    assert ST.final_error_message({}, {}) == 'no preview images produced'
    assert ST.final_error_message({'lora_failed': True}, {}) == 'LoRA: failed'
    assert (
        ST.final_error_message({'lora_failed': True, 'lora_error': 'oom'}, {'error': 'no face'})
        == 'LoRA: oom; preview: no face'
    )
    assert ST.final_error_message({}, {'error': 'no face'}) == 'preview: no face'


def test_dsl_scene_metadata_truncates_the_brief_and_falls_back_to_the_style():
    meta = ST.build_dsl_scene_metadata({'gender': 'female', 'name': 'Eva', 'style': 'photorealistic'})
    assert meta['subject'] == 'female character Eva'
    assert meta['setting'] == 'reference dataset for photorealistic style'
    assert meta['tags'] == ['character', 'photorealistic', 'female', '']
    assert meta['aspect_ratio'] == '2:3'

    long_meta = ST.build_dsl_scene_metadata({'character_brief_prose': 'x' * 400})
    assert long_meta['setting'] == 'x' * 200
    assert long_meta['subject'] == 'person character '
    assert long_meta['lighting_style'] == 'soft_studio'


def test_resolving_the_model_family_writes_it_everywhere_and_announces_the_route(monkeypatch):
    monkeypatch.setattr(ST, '_char_render_style', lambda params, info: 'photorealistic')
    monkeypatch.setattr(ST, '_resolve_char_model_family', lambda mf, params, info: 'flux')
    ctx, log = _ctx(job={'model_family': 'sdxl', 'render_mode': 'turbo'})

    assert ST.resolve_job_model_family(ctx, 'ignored-because-the-job-wins') == 'flux'

    assert ctx.model_family == 'flux'
    assert ctx.render_style == 'photorealistic'
    assert ctx.info['model_family'] == 'flux'
    assert ctx.info['render_mode'] == 'turbo'
    assert ctx.params['model_family'] == 'flux'
    assert ctx.job['model_family'] == 'flux'
    assert log[0] == (
        'Photorealistic style routed to FLUX LoRA + locked preview (Eva pipeline)',
        'INFO',
        'init',
    )
    assert log[1] == ('Character pipeline model_family=flux', None, 'init')


def test_finalizing_a_good_preview_marks_the_job_done(monkeypatch):
    job = {'kick_lora': True}
    monkeypatch.setattr(ST, '_char_gen_jobs', {'abcdef1234': job})
    monkeypatch.setattr(ST, '_have_usable_char_preview', lambda *a: True)
    marked: list[str] = []
    monkeypatch.setattr(ST, '_char_mark_done', marked.append)
    ctx, log = _ctx(info={'dataset_dir': '/tmp/does-not-need-to-exist'})

    ST.finalize_job(ctx, 'flux', {'preview_quality_ok': True, 'backends': ['flux'], 'preview_warning': ''})

    assert marked == ['abcdef1234']
    assert job['preview_quality_ok'] is True
    assert job['preview_backends'] == ['flux']
    assert ctx.job is job
    assert log == [('Character abcdef1234 generation complete', 'INFO', 'done')]


def test_finalizing_without_previews_reports_the_joined_failure(monkeypatch):
    job = {'kick_lora': True, 'lora_failed': True, 'lora_error': 'cuda oom'}
    monkeypatch.setattr(ST, '_char_gen_jobs', {'abcdef1234': job})
    monkeypatch.setattr(ST, '_have_usable_char_preview', lambda *a: False)
    errors: list[str] = []
    monkeypatch.setattr(ST, '_char_mark_error', lambda cid, err: errors.append(err))
    ctx, log = _ctx(info={'dataset_dir': '/tmp/does-not-need-to-exist'})

    ST.finalize_job(ctx, 'flux', {'error': 'render crashed'})

    assert errors == ['LoRA: cuda oom; preview: render crashed']
    assert log == [
        ('Character generation failed: LoRA: cuda oom; preview: render crashed', 'ERROR', 'error'),
    ]
