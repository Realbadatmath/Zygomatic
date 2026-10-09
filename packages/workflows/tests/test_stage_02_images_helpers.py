# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from `stage_02_image_prep`.

The stage used to be 534 lines, so none of this logic had ever been called with
inputs a test chose: the upload copy, the Comfy batch's break-on-QA-failure, the
DSL merge, the LoRA ladder, the ControlNet/IPAdapter conditioning and the three
teardowns were all reachable only by running a video job on the GPU. Everything
here runs on stubs — no torch, no diffusers, no ComfyUI, no network (`torch` and
`diffusers` are not even installed in this environment, which is exactly why the
split passes them in instead of importing them).
"""

import os
import sys
import types

import numpy as np
import pytest

from zyg_workflows import gui_state
from zyg_workflows.video_stages import stage_02_images as ST2
from zyg_workflows.video_stages import stage_02_images_flux as FX


class LogSpy:
    """Stand-in for the driver's `_log(level, stage, message)` closure."""

    def __init__(self):
        self.lines = []

    def __call__(self, level, stage, msg):
        self.lines.append((level, stage, msg))

    def msgs(self, level=None):
        return [m for lv, _st, m in self.lines if level is None or lv == level]


def make_run(**kw):
    """A `FluxStillRun` with harmless defaults; *kw* overrides any field."""
    fields = dict(
        log=LogSpy(),
        images_dir='/tmp/zyg-test-images',
        out_dir='/tmp/zyg-test-out',
        scenes=[],
        directive='a directive',
        visual_style='documentary',
        vscfg={},
        job={},
        n_scenes=1,
        scene_images=[],
    )
    fields.update(kw)
    return FX.FluxStillRun(**fields)


class FakeImages:
    """What a diffusers pipeline call returns: an object with `.images`."""

    def __init__(self, image):
        self.images = [image]


class FakePipeline:
    """A FLUX pipeline that records the kwargs it was called with."""

    def __init__(self, image='img'):
        self.image = image
        self.calls = []
        self.loaded_loras = []
        self.adapters = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return FakeImages(self.image)

    def load_lora_weights(self, arg):
        self.loaded_loras.append(arg)

    def set_adapters(self, names, adapter_weights=None):
        self.adapters.append((names, adapter_weights))


class FakeTorch:
    """`run.torch` with just the three members the helpers touch."""

    class _Gen:
        def __init__(self, device):
            self.device = device
            self.seed = None

        def manual_seed(self, seed):
            self.seed = seed
            return self

    def __init__(self):
        self.generators = []
        self.emptied = 0

    def Generator(self, device):  # noqa: N802 - mirrors torch.Generator
        gen = self._Gen(device)
        self.generators.append(gen)
        return gen

    @property
    def cuda(self):
        torch = self

        class _Cuda:
            @staticmethod
            def empty_cache():
                torch.emptied += 1

            @staticmethod
            def is_available():
                return False

        return _Cuda


# ── copy_uploaded_stills ──────────────────────────────────────────────────


def test_uploads_are_copied_in_order_and_renamed_per_scene(tmp_path):
    ups = []
    for i, ext in enumerate(('.JPG', '.png')):
        p = tmp_path / f'upload_{i}{ext}'
        p.write_bytes(b'x')
        ups.append(str(p))
    dest_dir = tmp_path / 'images'
    dest_dir.mkdir()

    out = FX.copy_uploaded_stills(ups, 4, str(dest_dir))

    assert [os.path.basename(p) for p in out] == ['scene_0000.jpg', 'scene_0001.png']
    assert all(os.path.exists(p) for p in out)


def test_only_the_first_n_scenes_uploads_are_taken(tmp_path):
    ups = []
    for i in range(3):
        p = tmp_path / f'u{i}.png'
        p.write_bytes(b'x')
        ups.append(str(p))

    out = FX.copy_uploaded_stills(ups, 2, str(tmp_path))

    assert len(out) == 2


def test_an_upload_whose_path_is_gone_is_skipped_without_raising(tmp_path):
    good = tmp_path / 'good.png'
    good.write_bytes(b'x')

    out = FX.copy_uploaded_stills([str(tmp_path / 'gone.png'), str(good)], 2, str(tmp_path))

    assert len(out) == 1
    # The surviving upload keeps its own index, not a renumbered one.
    assert out[0].endswith('scene_0001.png')


def test_an_extensionless_upload_becomes_a_jpg(tmp_path):
    up = tmp_path / 'plain'
    up.write_bytes(b'x')

    out = FX.copy_uploaded_stills([str(up)], 1, str(tmp_path))

    assert out == [str(tmp_path / 'scene_0000.jpg')]


# ── _dsl_scene_yaml ───────────────────────────────────────────────────────


def test_no_scene_yaml_when_the_dsl_is_absent(monkeypatch):
    monkeypatch.setattr(FX, '_dsl', None)

    assert FX._dsl_scene_yaml('/out', 3) is None


def test_no_scene_yaml_when_the_dsl_is_off_for_video(monkeypatch):
    monkeypatch.setattr(FX, '_dsl', types.SimpleNamespace(is_enabled=lambda kind: False))

    assert FX._dsl_scene_yaml('/out', 3) is None


def test_the_scene_yaml_is_resolved_under_the_runs_dsl_dir(monkeypatch, stub_module):
    monkeypatch.setattr(FX, '_dsl', types.SimpleNamespace(is_enabled=lambda kind: kind == 'video'))
    stub_module('dsl_runtime', types.SimpleNamespace(scene_yaml_path=lambda d, i: os.path.join(d, f's{i}.yaml')))

    assert FX._dsl_scene_yaml('/out', 3) == '/out/dsl/s3.yaml'


def test_a_failing_scene_yaml_lookup_is_logged_and_yields_none(monkeypatch, stub_module, caplog):
    monkeypatch.setattr(FX, '_dsl', types.SimpleNamespace(is_enabled=lambda kind: True))

    def boom(_d, _i):
        raise ValueError('no yaml here')

    stub_module('dsl_runtime', types.SimpleNamespace(scene_yaml_path=boom))

    with caplog.at_level('WARNING', logger='zyg_workflows.pipeline_video'):
        assert FX._dsl_scene_yaml('/out', 0) is None
    assert 'DSL scene yaml unavailable' in caplog.text


# ── comfy_still_batch ─────────────────────────────────────────────────────


def _comfy_services(stub_module, available=True, results=((True, 'flux'),)):
    """Stub `comfy_generation_service` + `video_flux_still_service`; returns the call log."""
    calls = []

    def generate_still_with_retries(dest, scene, directive, style, vscfg, **kw):
        calls.append(dict(dest=dest, scene=scene, directive=directive, style=style, vscfg=vscfg, **kw))
        return results[min(len(calls) - 1, len(results) - 1)]

    stub_module('comfy_generation_service', types.SimpleNamespace(is_available=lambda: available))
    stub_module(
        'video_flux_still_service',
        types.SimpleNamespace(generate_still_with_retries=generate_still_with_retries),
    )
    return calls


def test_the_comfy_batch_is_a_no_op_when_comfy_is_down(stub_module):
    calls = _comfy_services(stub_module, available=False)
    run = make_run(n_scenes=2)

    FX.comfy_still_batch(run, 2)

    assert calls == []
    assert run.scene_images == []
    assert run.log.lines == []


def test_the_comfy_batch_fills_every_missing_scene_and_says_flux_is_not_needed(monkeypatch, stub_module):
    monkeypatch.setattr(FX, '_dsl', None)
    calls = _comfy_services(stub_module, results=((True, 'flux'),))
    run = make_run(n_scenes=2, scenes=[{'description': 'a'}, {'description': 'b'}], job={'char_id': ''})

    FX.comfy_still_batch(run, 2)

    assert [os.path.basename(p) for p in run.scene_images] == ['scene_0000.png', 'scene_0001.png']
    assert [c['scene'] for c in calls] == [{'description': 'a'}, {'description': 'b'}]
    assert calls[0]['model_family'] == 'flux'
    assert calls[0]['dsl_yaml_path'] is None
    assert 'ComfyUI generated 2 still(s) — in-process FLUX not loaded' in run.log.msgs('INFO')


def test_the_comfy_batch_stops_at_the_first_scene_that_never_passes_qa(monkeypatch, stub_module):
    monkeypatch.setattr(FX, '_dsl', None)
    calls = _comfy_services(stub_module, results=((True, 'flux'), (False, 'blank')))
    run = make_run(n_scenes=3, scenes=[{}, {}, {}])

    FX.comfy_still_batch(run, 3)

    assert len(run.scene_images) == 1
    assert len(calls) == 2  # the third scene is never attempted
    assert run.log.msgs('WARNING') == ['Scene 1: still QA failed after all attempts (blank)']


def test_the_comfy_batch_appends_after_the_stills_already_copied_in(monkeypatch, stub_module):
    monkeypatch.setattr(FX, '_dsl', None)
    _comfy_services(stub_module)
    run = make_run(n_scenes=2, scenes=[{}, {}], scene_images=['/already/scene_0000.jpg'])

    FX.comfy_still_batch(run, 1)

    assert run.scene_images[1].endswith('scene_0001.png')


def test_the_comfy_batch_loads_the_character_bible_once_for_the_whole_batch(monkeypatch, stub_module):
    monkeypatch.setattr(FX, '_dsl', None)
    calls = _comfy_services(stub_module)
    loads = []
    stub_module('character_bible_service', types.SimpleNamespace(load=lambda cid: loads.append(cid) or {'id': cid}))
    run = make_run(n_scenes=2, scenes=[{}, {}], job={'char_id': 'nova', 'model_family': 'qwen'})

    FX.comfy_still_batch(run, 2)

    assert loads == ['nova']
    assert [c['char_pkg'] for c in calls] == [{'id': 'nova'}, {'id': 'nova'}]
    assert calls[0]['model_family'] == 'qwen'


# ── wait_for_flux_vram ────────────────────────────────────────────────────


def test_the_vram_wait_reports_what_it_got(stub_module):
    log = LogSpy()
    stub_module('_comfy_client', types.SimpleNamespace(wait_for_free_vram_gb=lambda **kw: (True, 31.25)))

    FX.wait_for_flux_vram(log)

    assert log.msgs('INFO') == ['Pre-FLUX VRAM wait: ok=True free=31.2 GB']


def test_a_failing_vram_wait_is_non_fatal(stub_module):
    log = LogSpy()

    def boom(**_kw):
        raise RuntimeError('nvml gone')

    stub_module('_comfy_client', types.SimpleNamespace(wait_for_free_vram_gb=boom))

    FX.wait_for_flux_vram(log)

    assert log.msgs('WARNING') == ['Pre-FLUX VRAM wait failed (non-fatal): nvml gone']


# ── the LoRA ladder ───────────────────────────────────────────────────────


def test_simpletuner_lora_keys_are_renamed_to_the_diffusers_convention():
    out = FX._normalise_lora_keys(
        {
            'transformer.blocks.0.attn.lora.down.weight': 1,
            'transformer.blocks.0.attn.lora.up.weight': 2,
            'transformer.blocks.0.attn.alpha': 3,
        }
    )

    assert out == {
        'transformer.blocks.0.attn.lora_A.weight': 1,
        'transformer.blocks.0.attn.lora_B.weight': 2,
        'transformer.blocks.0.attn.alpha': 3,
    }


def _fake_safetensors(monkeypatch, state):
    """Put a `safetensors.torch.load_file` returning *state* on sys.modules."""
    torch_mod = types.SimpleNamespace(load_file=lambda path: state)
    parent = types.ModuleType('safetensors')
    parent.torch = torch_mod
    monkeypatch.setitem(sys.modules, 'safetensors', parent)
    monkeypatch.setitem(sys.modules, 'safetensors.torch', torch_mod)


def test_a_style_lora_file_is_loaded_at_its_configured_scale(monkeypatch, tmp_path):
    (tmp_path / 'noir.safetensors').write_bytes(b'x')
    monkeypatch.setattr(FX, '_STYLE_LORA_DIR', str(tmp_path))
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    run = make_run(vscfg={'lora': 'noir.safetensors', 'scale': 0.8})

    assert FX._load_style_lora(run) is True
    assert pipe.loaded_loras == [str(tmp_path / 'noir.safetensors')]
    assert pipe.adapters == [(['default_0'], [0.8])]
    assert run.log.msgs('INFO') == ['Style LoRA loaded: noir.safetensors @ scale 0.8']


def test_a_missing_style_lora_file_is_a_warning_and_no_lora(monkeypatch, tmp_path):
    monkeypatch.setattr(FX, '_STYLE_LORA_DIR', str(tmp_path))
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    run = make_run(vscfg={'lora': 'absent.safetensors'})

    assert FX._load_style_lora(run) is False
    assert pipe.loaded_loras == []
    assert run.log.msgs('WARNING') == [f'Style LoRA file not found: {tmp_path / "absent.safetensors"}']


def test_a_failing_style_lora_load_leaves_the_run_without_one(monkeypatch, tmp_path):
    (tmp_path / 'noir.safetensors').write_bytes(b'x')
    monkeypatch.setattr(FX, '_STYLE_LORA_DIR', str(tmp_path))

    class Broken(FakePipeline):
        def load_lora_weights(self, arg):
            raise RuntimeError('bad keys')

    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', Broken())
    run = make_run(vscfg={'lora': 'noir.safetensors'})

    assert FX._load_style_lora(run) is False
    assert run.log.msgs('WARNING') == ['Style LoRA load failed (continuing without): bad keys']


def test_a_lora_dir_export_is_key_normalised_before_loading(monkeypatch, tmp_path):
    (tmp_path / 'pytorch_lora_weights.safetensors').write_bytes(b'x')
    _fake_safetensors(monkeypatch, {'a.lora.down.weight': 1})
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    run = make_run(vscfg={'lora_dir': str(tmp_path), 'lora_dir_scale': 0.5})

    assert FX._load_style_lora(run) is True
    assert pipe.loaded_loras == [{'a.lora_A.weight': 1}]
    assert pipe.adapters == [(['default_0'], [0.5])]


def test_a_lora_dir_without_its_safetensors_file_is_a_warning(monkeypatch, tmp_path):
    _fake_safetensors(monkeypatch, {})
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    run = make_run(vscfg={'lora_dir': str(tmp_path)})

    assert FX._load_style_lora(run) is False
    assert pipe.loaded_loras == []
    assert 'lora_dir LoRA file not found' in run.log.msgs('WARNING')[0]


def test_the_global_documentary_lora_is_the_last_resort(monkeypatch, tmp_path):
    _fake_safetensors(monkeypatch, {'a.lora.up.weight': 2})
    monkeypatch.setattr(FX, '_FLUX_LORA_PATH', str(tmp_path))
    monkeypatch.setattr(FX, '_FLUX_LORA_SCALE', 0.9)
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    run = make_run(vscfg={})

    assert FX._load_style_lora(run) is True
    assert pipe.loaded_loras == [{'a.lora_B.weight': 2}]
    assert pipe.adapters == [(['default_0'], [0.9])]


def test_no_lora_at_all_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(FX, '_FLUX_LORA_PATH', '')
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    run = make_run(vscfg={})

    assert FX._load_style_lora(run) is False
    assert pipe.loaded_loras == []
    assert run.log.lines == []


# ── load_flux_pipeline ───────────────────────────────────────────────────


def test_a_warm_cache_is_reused_and_no_lora_is_claimed_for_it(monkeypatch):
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    run = make_run(torch=FakeTorch(), gc=types.SimpleNamespace(collect=lambda: None))

    FX.load_flux_pipeline(run, '/models/flux', object())

    assert gui_state._FLUX_PIPELINE_CACHE is pipe
    assert run.log.msgs('INFO') == ['Using cached FLUX model']


def test_a_cold_cache_loads_flux_and_binds_the_cpu_t5_forward(monkeypatch):
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', None)
    pipe = FakePipeline()
    pipe.transformer = types.SimpleNamespace(to=lambda d: None)
    pipe.text_encoder = types.SimpleNamespace(to=lambda d: None)
    pipe.vae = types.SimpleNamespace(to=lambda d: None)
    seen = {}

    class Cls:
        @staticmethod
        def from_pretrained(path, torch_dtype=None, local_files_only=None):
            seen.update(path=path, dtype=torch_dtype, local=local_files_only)
            return pipe

    torch = FakeTorch()
    torch.bfloat16 = 'bf16'
    collected = []
    run = make_run(torch=torch, gc=types.SimpleNamespace(collect=lambda: collected.append(1)))

    FX.load_flux_pipeline(run, '/models/flux', Cls)

    assert seen == {'path': '/models/flux', 'dtype': 'bf16', 'local': True}
    assert gui_state._FLUX_PIPELINE_CACHE is pipe
    assert pipe._get_t5_prompt_embeds.__func__ is FX._t5_cpu_prompt_embeds
    assert torch.emptied == 1 and collected == [1]
    assert run.log.msgs('INFO')[0] == 'Loading FLUX.1-schnell…'
    assert 'T5-XXL on CPU' in run.log.msgs('INFO')[1]


# ── setup_quality_services ───────────────────────────────────────────────


def test_the_quality_services_record_the_controlnet_pipe_and_the_esrgan_path(monkeypatch, stub_module, tmp_path):
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    seen = {}

    def setup(p, log_fn=None):
        seen['pipe'] = p
        log_fn('controlnet says hello')
        return 'cn-pipe'

    stub_module('controlnet_service', types.SimpleNamespace(setup=setup))
    stub_module('ipadapter_service', types.SimpleNamespace())
    monkeypatch.setattr(FX.paths, 'ZYG_REALESRGAN_ROOT', tmp_path)
    (tmp_path / 'RealESRGAN_x4plus.pth').write_bytes(b'x')
    torch = FakeTorch()
    run = make_run(torch=torch, gc=types.SimpleNamespace(collect=lambda: None))

    FX.setup_quality_services(run)

    assert seen['pipe'] is pipe
    assert run.cn_pipe == 'cn-pipe'
    assert run.ipa_ready is False and run.subject_ref_path is None
    assert run.esrgan_up is None
    assert run.esrgan_model_path == str(tmp_path / 'RealESRGAN_x4plus.pth')
    assert run.esrgan_available is True
    assert torch.emptied == 1  # the allocator is defragmented before inference
    assert 'ControlNet pose conditioning loaded ✓' in run.log.msgs('INFO')[1]


def test_an_absent_controlnet_falls_back_to_base_flux_for_every_scene(monkeypatch, stub_module, tmp_path):
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', FakePipeline())
    stub_module('controlnet_service', types.SimpleNamespace(setup=lambda p, log_fn=None: None))
    stub_module('ipadapter_service', types.SimpleNamespace())
    monkeypatch.setattr(FX.paths, 'ZYG_REALESRGAN_ROOT', tmp_path)
    run = make_run(torch=FakeTorch(), gc=types.SimpleNamespace(collect=lambda: None))

    FX.setup_quality_services(run)

    assert run.cn_pipe is None
    assert run.esrgan_available is False  # no model file in tmp_path
    assert run.log.msgs('WARNING') == ['ControlNet unavailable — using base FLUX for all scenes']


def test_a_controlnet_load_that_raises_an_out_of_memory_error_is_survived(monkeypatch, stub_module, tmp_path):
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', FakePipeline())

    def oom(_p, log_fn=None):
        raise MemoryError('CUDA out of memory')

    stub_module('controlnet_service', types.SimpleNamespace(setup=oom))
    stub_module('ipadapter_service', types.SimpleNamespace())
    monkeypatch.setattr(FX.paths, 'ZYG_REALESRGAN_ROOT', tmp_path)
    run = make_run(torch=FakeTorch(), gc=types.SimpleNamespace(collect=lambda: None))

    FX.setup_quality_services(run)

    assert run.cn_pipe is None
    assert run.log.msgs('WARNING') == ['ControlNet load failed: CUDA out of memory']


# ── scene_render_plan ────────────────────────────────────────────────────


def _fake_vfs(prompt='a prompt', dims=(1360, 768, 'landscape'), portrait=False):
    return types.SimpleNamespace(
        build_flux_prompt=lambda sc, directive, vscfg: prompt,
        flux_dimensions=lambda sc: dims,
        is_portrait_shot=lambda sc: portrait,
    )


def test_a_scene_plan_takes_the_prompt_the_canvas_and_the_default_knobs(monkeypatch):
    monkeypatch.setattr(FX, '_dsl', None)
    monkeypatch.setattr(FX, '_random', types.SimpleNamespace(randint=lambda a, b: 4242))
    run = make_run()

    plan = FX.scene_render_plan(run, _fake_vfs(), {'description': 's'}, 0)

    assert (plan.prompt, plan.width, plan.height) == ('a prompt', 1360, 768)
    assert (plan.seed, plan.steps, plan.cfg) == (4242, 24, 3.5)
    assert run.log.lines == []


def test_the_scene_seed_is_drawn_from_the_full_32_bit_range(monkeypatch):
    monkeypatch.setattr(FX, '_dsl', None)
    seen = {}
    monkeypatch.setattr(FX, '_random', types.SimpleNamespace(randint=lambda a, b: seen.update(lo=a, hi=b) or 1))

    FX.scene_render_plan(make_run(), _fake_vfs(), {}, 0)

    assert seen == {'lo': 0, 'hi': 2**32 - 1}


def test_the_dsl_overrides_the_prompt_and_all_three_knobs(monkeypatch, stub_module):
    monkeypatch.setattr(FX, '_dsl', types.SimpleNamespace(is_enabled=lambda kind: kind == 'video'))
    monkeypatch.setattr(FX, '_random', types.SimpleNamespace(randint=lambda a, b: 7))
    seen = {}

    def merge(prompt, **kw):
        seen.update(prompt=prompt, **kw)
        return ('dsl prompt', 99, 30, 4.5)

    stub_module(
        'dsl_runtime',
        types.SimpleNamespace(merge_flux_generation_params=merge, scene_yaml_path=lambda d, i: f'{d}/{i}.yaml'),
    )
    run = make_run(out_dir='/out')

    plan = FX.scene_render_plan(run, _fake_vfs(portrait=True), {}, 2)

    assert (plan.prompt, plan.seed, plan.steps, plan.cfg) == ('dsl prompt', 99, 30, 4.5)
    assert seen['dsl_yaml_path'] == '/out/dsl/2.yaml'
    assert seen['is_schnell'] is False and seen['portrait_mode'] is True
    assert (seen['seed'], seen['steps'], seen['cfg']) == (7, 24, 3.5)


def test_a_failing_dsl_merge_leaves_the_defaults_standing(monkeypatch, stub_module):
    monkeypatch.setattr(FX, '_dsl', types.SimpleNamespace(is_enabled=lambda kind: True))
    monkeypatch.setattr(FX, '_random', types.SimpleNamespace(randint=lambda a, b: 7))

    def boom(_prompt, **_kw):
        raise ValueError('bad yaml')

    stub_module(
        'dsl_runtime',
        types.SimpleNamespace(merge_flux_generation_params=boom, scene_yaml_path=lambda d, i: 'y'),
    )
    run = make_run()

    plan = FX.scene_render_plan(run, _fake_vfs(), {}, 0)

    assert (plan.prompt, plan.seed, plan.steps, plan.cfg) == ('a prompt', 7, 24, 3.5)
    assert run.log.msgs('WARNING') == ['DSL FLUX merge skipped: bad yaml']


# ── _comfy_character_still ───────────────────────────────────────────────


A_PLAN = FX.ScenePlan(prompt='p', width=1360, height=768, seed=11, steps=24, cfg=3.5)


def test_a_job_without_a_character_never_asks_comfy(stub_module):
    stub_module('comfy_generation_service', types.SimpleNamespace(is_available=lambda: (_ for _ in ()).throw(OSError)))
    run = make_run(job={})

    assert FX._comfy_character_still(run, A_PLAN, 0, '/img/scene_0000.png') is False
    assert run.log.lines == []


def test_the_character_still_is_submitted_with_the_plans_knobs(stub_module):
    seen = {}

    def generate_still(dest, prompt, **kw):
        seen.update(dest=dest, prompt=prompt, **kw)
        return True, 'comfy-flux'

    stub_module(
        'comfy_generation_service',
        types.SimpleNamespace(is_available=lambda: True, generate_still=generate_still),
    )
    stub_module('character_bible_service', types.SimpleNamespace(load=lambda cid: {'id': cid}))
    run = make_run(job={'char_id': 'nova', 'model_family': 'qwen'})

    assert FX._comfy_character_still(run, A_PLAN, 3, '/img/scene_0003.png') is True
    assert run.scene_images == ['/img/scene_0003.png']
    assert seen['prompt'] == 'p' and seen['seed'] == 11 and seen['steps'] == 24 and seen['cfg'] == 3.5
    assert (seen['width'], seen['height']) == (1360, 768)
    assert seen['character_package'] == {'id': 'nova'} and seen['model_family'] == 'qwen'
    assert run.log.msgs('INFO') == ['Scene 3: ComfyGen (comfy-flux)']


def test_a_refused_character_still_sends_the_scene_to_diffusers(stub_module):
    stub_module(
        'comfy_generation_service',
        types.SimpleNamespace(is_available=lambda: True, generate_still=lambda *a, **k: (False, 'qa')),
    )
    stub_module('character_bible_service', types.SimpleNamespace(load=lambda cid: {}))
    run = make_run(job={'char_id': 'nova'})

    assert FX._comfy_character_still(run, A_PLAN, 0, '/img/x.png') is False
    assert run.scene_images == []


def test_a_raising_comfy_character_path_is_logged_and_falls_back(stub_module):
    def boom():
        raise RuntimeError('comfy 500')

    stub_module('comfy_generation_service', types.SimpleNamespace(is_available=boom))
    run = make_run(job={'char_id': 'nova'})

    assert FX._comfy_character_still(run, A_PLAN, 0, '/img/x.png') is False
    assert run.log.msgs('WARNING') == ['ComfyGen failed — diffusers fallback: comfy 500']


# ── _flux_generate_image ─────────────────────────────────────────────────


def test_the_base_pipeline_gets_the_plan_as_generation_kwargs(monkeypatch):
    pipe = FakePipeline(image='the-image')
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    torch = FakeTorch()
    run = make_run(torch=torch)

    out = FX._flux_generate_image(run, A_PLAN, 0)

    assert out == 'the-image'
    kw = pipe.calls[0]
    assert kw['prompt'] == 'p' and kw['guidance_scale'] == 3.5 and kw['num_inference_steps'] == 24
    assert (kw['width'], kw['height']) == (1360, 768)
    assert torch.generators[0].device == 'cuda' and torch.generators[0].seed == 11


def test_controlnet_takes_the_pose_of_the_previous_still_and_goes_back_to_the_cpu(monkeypatch):
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', FakePipeline(image='base'))
    cn_pipe = FakePipeline(image='posed')
    moves = []
    cn_svc = types.SimpleNamespace(
        get_pose_image=lambda tag, src: f'pose({tag},{src})',
        controlnet_to_cuda=lambda p: moves.append('cuda'),
        controlnet_to_cpu=lambda p: moves.append('cpu'),
    )
    run = make_run(torch=FakeTorch(), cn_svc=cn_svc, cn_pipe=cn_pipe, scene_images=['/img/scene_0000.png'])

    out = FX._flux_generate_image(run, A_PLAN, 1)

    assert out == 'posed'
    assert cn_pipe.calls[0]['control_image'] == 'pose(scene_1,/img/scene_0000.png)'
    assert moves == ['cuda', 'cpu']


def test_the_first_scene_has_no_previous_still_so_controlnet_stays_out(monkeypatch):
    base = FakePipeline(image='base')
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', base)
    cn_pipe = FakePipeline(image='posed')
    cn_svc = types.SimpleNamespace(
        get_pose_image=lambda tag, src: 'pose',
        controlnet_to_cuda=lambda p: None,
        controlnet_to_cpu=lambda p: None,
    )
    run = make_run(torch=FakeTorch(), cn_svc=cn_svc, cn_pipe=cn_pipe, scene_images=[])

    assert FX._flux_generate_image(run, A_PLAN, 0) == 'base'
    assert cn_pipe.calls == []


def test_a_failing_controlnet_generation_retries_on_the_base_pipeline(monkeypatch):
    base = FakePipeline(image='base')
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', base)

    class Broken(FakePipeline):
        def __call__(self, **kw):
            raise RuntimeError('controlnet blew up')

    moves = []
    cn_svc = types.SimpleNamespace(
        get_pose_image=lambda tag, src: 'pose',
        controlnet_to_cuda=lambda p: moves.append('cuda'),
        controlnet_to_cpu=lambda p: moves.append('cpu'),
    )
    run = make_run(torch=FakeTorch(), cn_svc=cn_svc, cn_pipe=Broken(), scene_images=['/img/prev.png'])

    assert FX._flux_generate_image(run, A_PLAN, 1) == 'base'
    assert base.calls[0]['prompt'] == 'p'
    assert moves == ['cuda', 'cpu']  # the ControlNet still goes back to the CPU
    assert run.log.msgs('WARNING') == ['ControlNet gen failed: controlnet blew up']


def test_a_pose_extraction_failure_only_drops_the_conditioning(monkeypatch):
    base = FakePipeline(image='base')
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', base)

    def boom(_tag, _src):
        raise RuntimeError('no pose')

    cn_svc = types.SimpleNamespace(
        get_pose_image=boom,
        controlnet_to_cuda=lambda p: None,
        controlnet_to_cpu=lambda p: None,
    )
    run = make_run(torch=FakeTorch(), cn_svc=cn_svc, cn_pipe=FakePipeline(), scene_images=['/img/prev.png'])

    assert FX._flux_generate_image(run, A_PLAN, 1) == 'base'
    assert run.log.msgs('WARNING') == []


def test_ipadapter_conditioning_is_applied_for_later_scenes_and_reset_after(monkeypatch):
    pipe = FakePipeline(image='base')
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    calls = []
    ipa = types.SimpleNamespace(
        condition_pipe=lambda p, tag, scale=None, log_fn=None: calls.append(('cond', tag, scale)) or True,
        reset_conditioning=lambda p: calls.append(('reset',)),
    )
    run = make_run(torch=FakeTorch(), ipa_svc=ipa, ipa_ready=True, subject_ref_path='/img/scene_0000.png')

    FX._flux_generate_image(run, A_PLAN, 2)

    assert calls == [('cond', 'scene_ref', 0.55), ('reset',)]


def test_without_a_registered_reference_ipadapter_is_not_conditioned(monkeypatch):
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', FakePipeline(image='base'))
    calls = []
    ipa = types.SimpleNamespace(
        condition_pipe=lambda *a, **k: calls.append('cond') or True,
        reset_conditioning=lambda p: calls.append('reset'),
    )
    run = make_run(torch=FakeTorch(), ipa_svc=ipa, ipa_ready=True, subject_ref_path=None)

    FX._flux_generate_image(run, A_PLAN, 2)

    assert calls == []


# ── _esrgan_upscale ──────────────────────────────────────────────────────


def test_the_upscale_writes_a_4x_sibling_and_returns_its_path(tmp_path):
    src = tmp_path / 'scene_0000.png'
    import cv2

    cv2.imwrite(str(src), np.zeros((8, 8, 3), dtype=np.uint8))
    seen = {}

    class Up:
        def enhance(self, img, outscale=None):
            seen.update(shape=img.shape, outscale=outscale)
            return np.zeros((img.shape[0] * 4, img.shape[1] * 4, 3), dtype=np.uint8), None

    run = make_run(torch=FakeTorch(), esrgan_up=Up(), esrgan_available=True)

    out = FX._esrgan_upscale(run, str(src), 0)

    assert out == str(tmp_path / 'scene_0000_4x.png')
    assert cv2.imread(out).shape == (32, 32, 3)
    assert seen == {'shape': (8, 8, 3), 'outscale': 4}
    assert run.log.msgs('INFO') == ['ESRGAN 4× applied: scene 1']


def test_a_failing_upscale_keeps_the_master_frame(tmp_path):
    src = tmp_path / 'scene_0000.png'
    import cv2

    cv2.imwrite(str(src), np.zeros((4, 4, 3), dtype=np.uint8))

    class Up:
        def enhance(self, img, outscale=None):
            raise RuntimeError('tile OOM')

    run = make_run(torch=FakeTorch(), esrgan_up=Up())

    assert FX._esrgan_upscale(run, str(src), 2) == str(src)
    assert run.log.msgs('WARNING') == ['ESRGAN failed: tile OOM']


# ── render_one_scene ─────────────────────────────────────────────────────


class FakeImage:
    """A PIL-like image that records where it was saved."""

    def __init__(self):
        self.saved = []

    def save(self, path):
        self.saved.append(path)


def test_a_comfy_character_still_short_circuits_the_whole_diffusers_path(monkeypatch):
    monkeypatch.setattr(FX, '_comfy_character_still', lambda *a: True)
    monkeypatch.setattr(FX, '_flux_generate_image', lambda *a: pytest.fail('FLUX must not run'))
    run = make_run(images_dir='/img')

    FX.render_one_scene(run, A_PLAN, 0)

    assert run.log.lines == []  # the helper did its own logging


def test_a_rendered_scene_is_saved_appended_and_announced(monkeypatch):
    img = FakeImage()
    monkeypatch.setattr(FX, '_comfy_character_still', lambda *a: False)
    monkeypatch.setattr(FX, '_flux_generate_image', lambda *a: img)
    run = make_run(images_dir='/img', n_scenes=3, visual_style='noir')

    FX.render_one_scene(run, A_PLAN, 1)

    assert img.saved == ['/img/scene_0001.png']
    assert run.scene_images == ['/img/scene_0001.png']
    assert run.log.msgs('INFO') == ['FLUX [noir] scene 2/3']


def test_scene_zero_becomes_the_ipadapter_reference(monkeypatch):
    monkeypatch.setattr(FX, '_comfy_character_still', lambda *a: False)
    monkeypatch.setattr(FX, '_flux_generate_image', lambda *a: FakeImage())
    refs = []
    run = make_run(
        images_dir='/img',
        ipa_ready=True,
        ipa_svc=types.SimpleNamespace(register_reference=lambda tag, p: refs.append((tag, p))),
    )

    FX.render_one_scene(run, A_PLAN, 0)

    assert refs == [('scene_ref', '/img/scene_0000.png')]
    assert run.subject_ref_path == '/img/scene_0000.png'


def test_a_later_scene_does_not_overwrite_the_reference(monkeypatch):
    monkeypatch.setattr(FX, '_comfy_character_still', lambda *a: False)
    monkeypatch.setattr(FX, '_flux_generate_image', lambda *a: FakeImage())
    refs = []
    run = make_run(
        images_dir='/img',
        ipa_ready=True,
        ipa_svc=types.SimpleNamespace(register_reference=lambda tag, p: refs.append(p)),
    )

    FX.render_one_scene(run, A_PLAN, 1)

    assert refs == [] and run.subject_ref_path is None


def test_the_upscaled_path_is_the_one_the_scene_list_keeps(monkeypatch):
    monkeypatch.setattr(FX, '_comfy_character_still', lambda *a: False)
    monkeypatch.setattr(FX, '_flux_generate_image', lambda *a: FakeImage())
    monkeypatch.setattr(FX, '_esrgan_upscale', lambda run, p, i: p.replace('.png', '_4x.png'))
    run = make_run(images_dir='/img', esrgan_available=True)

    FX.render_one_scene(run, A_PLAN, 0)

    assert run.scene_images == ['/img/scene_0000_4x.png']


def test_without_the_esrgan_weights_the_master_frame_is_kept(monkeypatch):
    monkeypatch.setattr(FX, '_comfy_character_still', lambda *a: False)
    monkeypatch.setattr(FX, '_flux_generate_image', lambda *a: FakeImage())
    monkeypatch.setattr(FX, '_esrgan_upscale', lambda *a: pytest.fail('ESRGAN must not run'))
    run = make_run(images_dir='/img', esrgan_available=False)

    FX.render_one_scene(run, A_PLAN, 0)

    assert run.scene_images == ['/img/scene_0000.png']


# ── teardown_image_services ──────────────────────────────────────────────


def test_every_service_is_torn_down_before_flux_is_unloaded(monkeypatch):
    pipe = FakePipeline()
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', pipe)
    order = []

    class Up:
        model = types.SimpleNamespace(cpu=lambda: order.append('esrgan-cpu'))

    run = make_run(
        cn_svc=types.SimpleNamespace(teardown=lambda p, log_fn=None: order.append(('cn', p))),
        ipa_svc=types.SimpleNamespace(teardown=lambda p, log_fn=None: order.append(('ipa', p))),
        cn_pipe='cn-pipe',
        ipa_ready=True,
        esrgan_up=Up(),
    )

    FX.teardown_image_services(run)

    assert order == [('cn', 'cn-pipe'), ('ipa', pipe), 'esrgan-cpu']
    assert run.cn_pipe is None and run.esrgan_up is None
    assert run.log.msgs('INFO') == ['Real-ESRGAN unloaded from VRAM']


def test_nothing_loaded_means_nothing_to_tear_down():
    run = make_run(cn_svc=None, ipa_svc=None)

    FX.teardown_image_services(run)

    assert run.log.lines == []


def test_a_failing_controlnet_teardown_does_not_stop_the_esrgan_release(monkeypatch, caplog):
    monkeypatch.setattr(gui_state, '_FLUX_PIPELINE_CACHE', FakePipeline())

    def boom(_p, log_fn=None):
        raise RuntimeError('hook stuck')

    class Up:
        model = types.SimpleNamespace(cpu=lambda: None)

    run = make_run(
        cn_svc=types.SimpleNamespace(teardown=boom),
        cn_pipe='cn-pipe',
        esrgan_up=Up(),
    )

    with caplog.at_level('WARNING', logger='zyg_workflows.pipeline_video'):
        FX.teardown_image_services(run)

    assert 'ControlNet teardown failed' in caplog.text
    assert run.esrgan_up is None
    assert run.cn_pipe == 'cn-pipe'  # the failed teardown leaves it as it was


# ── the orchestrator still wires to this module ──────────────────────────


def test_the_stage_module_reaches_its_helpers_through_one_name():
    assert ST2._st2_flux is FX
