# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Control-flow coverage for the three stage functions of `stage_02_images`.

The helpers are tested next door in `test_stage_02_images_helpers.py`; what was
never exercised is the flow — the ComfyUI-primary skip, the GPU-lock dance round
the in-process FLUX load, the error teardown, the gate's verdicts, the anatomy
pass. All on stubs: `_st2_flux` becomes a recording namespace, `torch`/
`diffusers`/`mediapipe`/`cv2` are fakes on `sys.modules` (the first two are not
installed here), and every derived path lands under `tmp_path`.
"""

import os
import sys
import types

import pytest

from zyg_workflows.video_stages import context as CTX
from zyg_workflows.video_stages import stage_02_images as ST2


class LogSpy:
    """The driver's four prologue closures, recording instead of reporting."""

    def __init__(self):
        self.lines = []
        self.stages = []
        self.completed = []
        self.failed = []

    def __call__(self, level, stage, msg):
        self.lines.append((level, stage, msg))

    def msgs(self, level=None):
        return [m for lv, _st, m in self.lines if level is None or lv == level]


def make_ctx(tmp_path, n_scenes=2, scenes=None, image_paths=None, **kw):
    """A `VideoContext` with the Stage-2 inputs filled and nothing on the GPU."""
    log = LogSpy()
    ctx = CTX.VideoContext(
        directive='a directive',
        image_paths=list(image_paths or []),
        visual_style='documentary',
        job={},
        out_dir=str(tmp_path / 'run'),
        n_scenes=n_scenes,
        scenes=[{} for _ in range(n_scenes)] if scenes is None else scenes,
        _vscfg={},
        _log=log,
        _set_stage=lambda name: log.stages.append(name),
        _complete_stage=lambda name: log.completed.append(name),
        _fail_stage=lambda name, msg: log.failed.append((name, msg)),
        **kw,
    )
    ctx.spy = log
    return ctx


def make_flux(uploaded=0, comfy_fill=0, comfy_exc=None, load_exc=None, render_exc_at=(), render_fill=True):
    """A stand-in for the `stage_02_images_flux` module, as `ST2._st2_flux`."""
    ns = types.SimpleNamespace(events=[], run=None)

    def copy_uploaded_stills(image_paths, n_scenes, images_dir):
        ns.events.append(('copy', len(image_paths), n_scenes))
        ns.images_dir = images_dir
        return [os.path.join(images_dir, f'up_{i:04d}.png') for i in range(uploaded)]

    def flux_still_run(**kw):
        ns.run = types.SimpleNamespace(**kw)
        return ns.run

    def comfy_still_batch(run, n_missing):
        ns.events.append(('comfy', n_missing))
        if comfy_exc is not None:
            raise comfy_exc
        for i in range(comfy_fill):
            run.scene_images.append(os.path.join(run.images_dir, f'comfy_{i:04d}.png'))

    def wait_for_flux_vram(log):
        ns.events.append('vram-wait')

    def load_flux_pipeline(run, model_path, cls):
        ns.events.append(('load', model_path))
        if load_exc is not None:
            raise load_exc

    def setup_quality_services(run):
        ns.events.append('services')

    def scene_render_plan(run, vfs, sc_data, scene_idx):
        ns.events.append(('plan', scene_idx, sc_data))
        return f'plan-{scene_idx}'

    def render_one_scene(run, plan, scene_idx):
        ns.events.append(('render', plan, scene_idx))
        if scene_idx in render_exc_at:
            raise RuntimeError(f'scene {scene_idx} exploded')
        if render_fill:
            run.scene_images.append(os.path.join(run.images_dir, f'flux_{scene_idx:04d}.png'))

    def teardown_image_services(run):
        ns.events.append('teardown')

    ns.copy_uploaded_stills = copy_uploaded_stills
    ns.FluxStillRun = flux_still_run
    ns.comfy_still_batch = comfy_still_batch
    ns.wait_for_flux_vram = wait_for_flux_vram
    ns.load_flux_pipeline = load_flux_pipeline
    ns.setup_quality_services = setup_quality_services
    ns.scene_render_plan = scene_render_plan
    ns.render_one_scene = render_one_scene
    ns.teardown_image_services = teardown_image_services
    return ns


class FakeLock:
    """`_GPU_PIPELINE_LOCK` without a GPU behind it."""

    def __init__(self, acquired=True):
        self.acquired = acquired
        self.calls = []

    def acquire(self, blocking=True, timeout=None):
        self.calls.append(('acquire', blocking, timeout))
        return self.acquired

    def release(self):
        self.calls.append('release')


@pytest.fixture
def stage2(monkeypatch, tmp_path):
    """Neutralise everything Stage 2 reaches outside its own module.

    Yields `flux` (set by `use_flux`), `lock`, `vram` (the VRAM calls in order)
    and `flux_root` — the dir probed for `flux1-schnell`, under tmp_path, empty.
    """
    env = types.SimpleNamespace(vram=[], lock=FakeLock(), flux=None)

    def release(tag, log_fn):
        env.vram.append(('release', tag))
        log_fn('vram released')

    def deep_unload(log_fn=None):
        env.vram.append('deep-unload')
        if log_fn is not None:
            log_fn('flux cache dropped')

    monkeypatch.setattr(ST2, '_release_pipeline_vram', release)
    monkeypatch.setattr(ST2, '_deep_unload_flux_pipeline_cache', deep_unload)
    monkeypatch.setattr(ST2, '_GPU_PIPELINE_LOCK', env.lock)
    env.flux_root = tmp_path / 'flux-root'
    env.flux_root.mkdir()
    monkeypatch.setattr(ST2.paths, 'ZYG_FLUX_ROOT', env.flux_root)
    monkeypatch.delenv('ZYG_FORCE_FLUX_LOCAL', raising=False)

    def use_flux(**kw):
        env.flux = make_flux(**kw)
        monkeypatch.setattr(ST2, '_st2_flux', env.flux)
        return env.flux

    env.use_flux = use_flux
    env.have_model = lambda: (env.flux_root / 'flux1-schnell').mkdir()
    return env


def local_flux(stage2, stub_module, monkeypatch, comfy=False, **flux_kw):
    """Put `torch`/`diffusers` (neither installed) and the model on disk.

    `comfy` = what `is_available()` answers; None = the probe's import fails."""
    monkeypatch.setitem(sys.modules, 'torch', types.ModuleType('torch'))
    diffusers = types.ModuleType('diffusers')
    diffusers.FluxPipeline = type('FluxPipeline', (), {})
    monkeypatch.setitem(sys.modules, 'diffusers', diffusers)
    probe = None if comfy is None else types.SimpleNamespace(is_available=lambda: comfy)
    stub_module('comfy_generation_service', probe)
    stub_module('video_flux_still_service', types.SimpleNamespace())
    stage2.have_model()
    return stage2.use_flux(**flux_kw)


# ── stage_02_image_prep: the paths that never load FLUX ───────────────────


def test_uploads_covering_every_scene_publish_the_images_dir_and_skip_generation(stage2, tmp_path):
    flux = stage2.use_flux(uploaded=2)
    ctx = make_ctx(tmp_path, n_scenes=2, image_paths=['a.png', 'b.png'])

    assert ST2.stage_02_image_prep(ctx) is None
    assert ctx.images_dir == os.path.join(str(tmp_path / 'run'), 'images')
    assert os.path.isdir(ctx.images_dir) and len(ctx.scene_images) == 2
    assert ctx.spy.stages == ['AI Image Generation']
    assert ctx.spy.msgs('INFO')[0] == 'Preparing images: 2 uploaded, need 2'
    # Nothing beyond the copy was asked for.
    assert [e[0] for e in flux.events] == ['copy']
    assert flux.run.directive == 'a directive' and flux.run.visual_style == 'documentary'


def test_comfyui_filling_every_gap_means_flux_is_never_touched(stage2, stub_module, tmp_path):
    stub_module('comfy_generation_service', types.SimpleNamespace(is_available=lambda: True))
    flux = stage2.use_flux(uploaded=0, comfy_fill=3)
    ctx = make_ctx(tmp_path, n_scenes=3)

    assert ST2.stage_02_image_prep(ctx) is None
    assert len(ctx.scene_images) == 3
    assert ('comfy', 3) in flux.events
    assert 'vram-wait' not in flux.events
    assert stage2.lock.calls == []
    assert 'Generating 3 images with FLUX Dev (hero stills) — style: documentary' in ctx.spy.msgs('INFO')


def test_a_raising_comfy_batch_is_a_warning_and_an_empty_run_fails_the_stage(stage2, stub_module, tmp_path):
    stub_module('comfy_generation_service', None)
    stage2.use_flux(uploaded=0, comfy_exc=RuntimeError('comfy 502'))
    ctx = make_ctx(tmp_path, n_scenes=2)

    out = ST2.stage_02_image_prep(ctx)

    assert isinstance(out, CTX.StageExit)
    assert 'ComfyUI still path failed — diffusers fallback: comfy 502' in ctx.spy.msgs('WARNING')
    assert ctx.spy.failed == [
        (
            'AI Image Generation',
            'Only 0/2 still(s) generated — Comfy/FLUX failed; blank fallback disabled.',
        )
    ]
    assert ctx.job['status'] == 'failed'
    assert ctx.job['error'] == 'Image generation incomplete (0/2 scenes)'
    # The failed stage never publishes its products.
    assert ctx.images_dir is None and ctx.scene_images is None


def test_comfy_primary_active_skips_the_in_process_flux_load_and_says_how_to_override(stage2, stub_module, tmp_path):
    stub_module('comfy_generation_service', types.SimpleNamespace(is_available=lambda: True))
    stage2.have_model()
    flux = stage2.use_flux(uploaded=0, comfy_fill=1)
    ctx = make_ctx(tmp_path, n_scenes=2)

    assert isinstance(ST2.stage_02_image_prep(ctx), CTX.StageExit)
    assert 'load' not in [e[0] for e in flux.events if isinstance(e, tuple)]
    assert stage2.lock.calls == []
    warning = ctx.spy.msgs('WARNING')[0]
    assert warning.startswith('1 still(s) missing but ComfyUI primary is active')
    assert 'ZYG_FORCE_FLUX_LOCAL=1' in warning


# ── stage_02_image_prep: the in-process FLUX path ─────────────────────────


def test_the_local_flux_path_renders_every_missing_scene_under_the_gpu_lock(stage2, stub_module, monkeypatch, tmp_path):
    flux = local_flux(stage2, stub_module, monkeypatch, uploaded=1)
    ctx = make_ctx(tmp_path, n_scenes=3, scenes=[{'description': 'a'}, {'description': 'b'}])

    assert ST2.stage_02_image_prep(ctx) is None
    assert len(ctx.scene_images) == 3
    assert stage2.vram == [('release', 'pre-FLUX'), 'deep-unload']
    assert stage2.lock.calls == [('acquire', True, 600), 'release']
    assert ctx._flux_gpu_acq_v is False
    assert ('load', str(stage2.flux_root / 'flux1-schnell')) in flux.events
    # Scene 2 is past the end of `scenes`, so the plan is built from an empty dict.
    assert [e for e in flux.events if e[0] == 'plan'] == [
        ('plan', 1, {'description': 'b'}),
        ('plan', 2, {}),
    ]
    assert 'teardown' in flux.events
    assert 'FLUX unloaded — VRAM freed for WAN' in ctx.spy.msgs('INFO')
    assert 'GPU lock released' in ctx.spy.msgs('INFO')
    assert flux.run.torch is sys.modules['torch']


def test_force_flux_local_overrides_an_available_comfyui(stage2, stub_module, monkeypatch, tmp_path):
    monkeypatch.setenv('ZYG_FORCE_FLUX_LOCAL', ' YES ')
    flux = local_flux(stage2, stub_module, monkeypatch, comfy=True, uploaded=0)
    ctx = make_ctx(tmp_path, n_scenes=1)

    assert ST2.stage_02_image_prep(ctx) is None
    assert ('load', str(stage2.flux_root / 'flux1-schnell')) in flux.events
    assert ctx.scene_images == [os.path.join(ctx.images_dir, 'flux_0000.png')]


def test_a_gpu_lock_timeout_proceeds_without_the_lock_and_releases_nothing(stage2, stub_module, monkeypatch, tmp_path):
    stage2.lock.acquired = False
    local_flux(stage2, stub_module, monkeypatch, uploaded=0)
    ctx = make_ctx(tmp_path, n_scenes=1)

    assert ST2.stage_02_image_prep(ctx) is None
    assert stage2.lock.calls == [('acquire', True, 600)]
    assert 'GPU lock timeout — proceeding without lock' in ctx.spy.msgs('INFO')


def test_one_scene_that_fails_to_render_is_a_warning_and_the_rest_still_run(stage2, stub_module, monkeypatch, tmp_path):
    flux = local_flux(stage2, stub_module, monkeypatch, uploaded=0, render_exc_at={0})
    ctx = make_ctx(tmp_path, n_scenes=2)

    assert isinstance(ST2.stage_02_image_prep(ctx), CTX.StageExit)
    assert 'FLUX scene 0 failed: scene 0 exploded' in ctx.spy.msgs('WARNING')
    assert [e[2] for e in flux.events if e[0] == 'render'] == [0, 1]
    assert ctx.job['error'] == 'Image generation incomplete (1/2 scenes)'


def test_a_failing_flux_load_is_cleaned_up_and_the_lock_given_back(stage2, stub_module, monkeypatch, tmp_path):
    flux = local_flux(stage2, stub_module, monkeypatch, uploaded=0, load_exc=RuntimeError('no bf16 kernel'))
    ctx = make_ctx(tmp_path, n_scenes=1)

    assert isinstance(ST2.stage_02_image_prep(ctx), CTX.StageExit)
    assert 'FLUX pipeline failed (no bf16 kernel) — using blank frames' in ctx.spy.msgs('WARNING')
    assert 'FLUX cleaned up after error' in ctx.spy.msgs('INFO')
    assert stage2.vram == [('release', 'pre-FLUX'), 'deep-unload']
    assert stage2.lock.calls == [('acquire', True, 600), 'release']
    assert ctx._flux_gpu_acq_v is False
    assert 'teardown' not in flux.events


def test_a_cleanup_that_also_fails_is_logged_and_still_leaves_the_stage_failed(
    stage2, stub_module, monkeypatch, tmp_path, caplog
):
    local_flux(stage2, stub_module, monkeypatch, uploaded=0, load_exc=RuntimeError('oom'))

    def unload_boom(log_fn=None):
        raise RuntimeError('nvml detached')

    monkeypatch.setattr(ST2, '_deep_unload_flux_pipeline_cache', unload_boom)
    ctx = make_ctx(tmp_path, n_scenes=1)

    with caplog.at_level('WARNING', logger='zyg_workflows.pipeline_video'):
        assert isinstance(ST2.stage_02_image_prep(ctx), CTX.StageExit)

    assert 'FLUX cleanup after the error failed' in caplog.text
    # The lock was not released on this path, so the driver's finally must.
    assert ctx._flux_gpu_acq_v is True
    assert stage2.lock.calls == [('acquire', True, 600)]


def test_the_import_of_the_comfy_probe_failing_keeps_the_local_flux_path(
    stage2, stub_module, monkeypatch, tmp_path, caplog
):
    flux = local_flux(stage2, stub_module, monkeypatch, comfy=None, uploaded=0)
    ctx = make_ctx(tmp_path, n_scenes=1)

    with caplog.at_level('DEBUG', logger='zyg_workflows.pipeline_video'):
        assert ST2.stage_02_image_prep(ctx) is None

    assert 'comfy_generation_service unavailable' in caplog.text
    assert ('load', str(stage2.flux_root / 'flux1-schnell')) in flux.events


# ── stage_02c_still_gate ──────────────────────────────────────────────────


def qa_service(ok=True, reason='sharp', blank=False, seen=None):
    """A `video_still_qa_service` whose two verdicts the test chooses."""

    def check_still_complete(path, directive, hint, scene, log_fn=None):
        if seen is not None:
            seen.append((path, hint))
        if log_fn is not None:
            log_fn(f'inspecting {os.path.basename(path)}')
        verdict = ok(path) if callable(ok) else ok
        return verdict, 0.9 if verdict else 0.1, reason

    return types.SimpleNamespace(
        check_still_complete=check_still_complete,
        is_blank_still=lambda p: blank,
    )


def with_stills(tmp_path, images=('a.png', 'b.png'), scenes=None):
    """A context already carrying Stage-2's products, for the later stages."""
    ctx = make_ctx(tmp_path, n_scenes=len(images), scenes=scenes)
    ctx.scene_images = [str(tmp_path / n) for n in images]
    return ctx


def test_every_still_passing_the_gate_completes_the_stage(stub_module, tmp_path):
    stub_module('video_still_qa_service', qa_service())
    ctx = with_stills(tmp_path)

    assert ST2.stage_02c_still_gate(ctx) is None
    assert ctx.spy.completed == ['AI Image Generation']
    assert ctx.job['scene_images'] == ctx.scene_images
    assert 'Scene 1: still gate pass (sharp)' in ctx.spy.msgs('INFO')
    assert 'Image prep complete: 2 images ready' in ctx.spy.msgs('INFO')


@pytest.mark.parametrize(
    ('scene', 'expected_hint'),
    [
        ({'flux_prompt': 'a lit room', 'description': 'ignored'}, 'a lit room'),
        ({'description': 'a dark room'}, 'a dark room'),
        ({}, 'a directive'),
    ],
)
def test_the_gate_hint_falls_back_from_flux_prompt_to_description_to_the_directive(
    stub_module, tmp_path, scene, expected_hint
):
    seen = []
    stub_module('video_still_qa_service', qa_service(seen=seen))
    ctx = with_stills(tmp_path, images=('a.png',), scenes=[scene])

    assert ST2.stage_02c_still_gate(ctx) is None
    assert seen == [(str(tmp_path / 'a.png'), expected_hint)]


def test_a_still_without_a_scene_of_its_own_is_gated_against_the_directive(stub_module, tmp_path):
    seen = []
    stub_module('video_still_qa_service', qa_service(seen=seen))
    ctx = with_stills(tmp_path, images=('a.png', 'b.png'), scenes=[{'description': 'only one'}])

    assert ST2.stage_02c_still_gate(ctx) is None
    assert [h for _p, h in seen] == ['only one', 'a directive']


@pytest.mark.parametrize(
    ('qa', 'why', 'warning'),
    [
        # One still rejected by QA: the reason names the 1-based scene number.
        (
            dict(ok=lambda p: p.endswith('a.png'), reason='half-drawn hand'),
            'still QA failed for scene(s): [2]',
            'Scene 2: still gate fail — half-drawn hand',
        ),
        # Every still passes QA yet all of them are blank frames.
        (dict(blank=True), 'all stills blank', None),
    ],
    ids=['qa-reject', 'all-blank'],
)
def test_the_gate_aborts_wan_and_fails_the_job(stub_module, tmp_path, qa, why, warning):
    stub_module('video_still_qa_service', qa_service(**qa))
    ctx = with_stills(tmp_path)

    assert isinstance(ST2.stage_02c_still_gate(ctx), CTX.StageExit)
    assert ctx.spy.failed == [('AI Image Generation', f'FLUX still gate failed — {why}. WAN aborted.')]
    assert ctx.job['status'] == 'failed'
    assert ctx.job['error'] == f'Image generation QA failed: {why}'
    assert ctx.spy.completed == []
    if warning is not None:
        assert warning in ctx.spy.msgs('WARNING')


def test_a_gate_that_cannot_even_be_imported_fails_the_job_without_a_stage_error(stub_module, tmp_path):
    stub_module('video_still_qa_service', None)
    ctx = with_stills(tmp_path)

    assert isinstance(ST2.stage_02c_still_gate(ctx), CTX.StageExit)
    assert ctx.spy.msgs('WARNING')[0].startswith('Still gate error:')
    assert ctx.job['status'] == 'failed'
    assert ctx.job['error'].startswith('Still QA gate error:')
    # The gate failed open on an import, so no stage was marked failed.
    assert ctx.spy.failed == []


# ── stage_02b_anatomy_repair ──────────────────────────────────────────────


def landmarks(xs, ys):
    """21 MediaPipe hand landmarks from two coordinate sequences."""
    return types.SimpleNamespace(landmark=[types.SimpleNamespace(x=x, y=y) for x, y in zip(xs, ys)])


CLUSTERED = ([0.5] * 21, [0.5] * 21)
SPREAD = ([i / 21 for i in range(21)], [i / 21 for i in range(21)])


def fake_anatomy_stack(monkeypatch, image=None, left=None, right=None, cvt_exc=None):
    """`mediapipe` + `cv2` as the anatomy pass sees them, with no model behind."""

    class Holistic:
        def __init__(self, **kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def process(self, img):
            return types.SimpleNamespace(left_hand_landmarks=left, right_hand_landmarks=right)

    mediapipe = types.ModuleType('mediapipe')
    mediapipe.solutions = types.SimpleNamespace(holistic=types.SimpleNamespace(Holistic=Holistic))
    monkeypatch.setitem(sys.modules, 'mediapipe', mediapipe)

    def cvt_color(img, code):
        if cvt_exc is not None:
            raise cvt_exc
        return img

    cv2 = types.ModuleType('cv2')
    cv2.imread = lambda path: image
    cv2.cvtColor = cvt_color
    cv2.COLOR_BGR2RGB = 4
    monkeypatch.setitem(sys.modules, 'cv2', cv2)


def fill_service(repaired=(), exc=None, seen=None):
    def repair_batch(meta, qa_threshold=None, use_flux_fill=None, log_fn=None):
        if seen is not None:
            seen.append(dict(meta=meta, qa_threshold=qa_threshold, use_flux_fill=use_flux_fill))
        if log_fn is not None:
            log_fn('flux-fill warm')
        if exc is not None:
            raise exc
        return list(repaired) if repaired else meta

    return types.SimpleNamespace(repair_batch=repair_batch)


def test_anatomy_repair_is_skipped_when_mediapipe_is_not_installed(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'mediapipe', None)
    ctx = with_stills(tmp_path)

    assert ST2.stage_02b_anatomy_repair(ctx) is None
    assert ctx.spy.stages == ['Anatomy Repair']
    assert ctx.spy.completed == ['Anatomy Repair']
    assert ctx.spy.msgs('WARNING')[0].startswith('Anatomy repair unavailable (')


def test_an_unreadable_still_scores_a_clean_one_and_its_repair_is_adopted(monkeypatch, stub_module, tmp_path):
    fake_anatomy_stack(monkeypatch, image=None)
    seen = []
    repaired = str(tmp_path / 'a_fixed.png')
    fixed = [{'index': 0, 'path': repaired, 'repair_pass': True}]
    stub_module('flux_fill_service', fill_service(repaired=fixed, seen=seen))
    ctx = with_stills(tmp_path, images=('a.png',), scenes=[{'description': 'x' * 80}])

    assert ST2.stage_02b_anatomy_repair(ctx) is None
    assert ctx.scene_images == [repaired]
    assert 'Anatomy repair complete: 1/1 image(s) repaired' in ctx.spy.msgs('INFO')
    assert 'Scene 0: QA=1.00 ✓' in ctx.spy.msgs('INFO')
    assert seen[0]['qa_threshold'] == 0.65 and seen[0]['use_flux_fill'] is True
    assert len(seen[0]['meta'][0]['subject']) == 60
    assert seen[0]['meta'][0]['prompt'] == 'x' * 80
    assert ctx.spy.completed == ['Anatomy Repair']


@pytest.mark.parametrize(
    ('stack', 'qa_score', 'issues'),
    [
        # Both hands bunched into one point: the fused-hand penalty, twice.
        (
            dict(image=[[0]], left=landmarks(*CLUSTERED), right=landmarks(*CLUSTERED)),
            0.4,
            [
                'left hand: landmarks clustered (fused hand)',
                'right hand: landmarks clustered (fused hand)',
            ],
        ),
        # One well-spread hand, one absent — nothing to report.
        (dict(image=[[0]], left=landmarks(*SPREAD), right=None), 1.0, []),
        # OpenCV raising mid-pass leaves the still scored clean.
        (dict(image=[[0]], cvt_exc=RuntimeError('bad colour code')), 1.0, []),
        # An unreadable file never reaches MediaPipe at all.
        (dict(image=None), 1.0, []),
    ],
    ids=['fused-hands', 'spread-and-missing', 'opencv-raises', 'unreadable'],
)
def test_the_anatomy_pass_scores_each_still_from_its_hand_landmarks(
    monkeypatch, stub_module, tmp_path, stack, qa_score, issues
):
    fake_anatomy_stack(monkeypatch, **stack)
    seen = []
    stub_module('flux_fill_service', fill_service(seen=seen))
    ctx = with_stills(tmp_path, images=('a.png',), scenes=[])

    assert ST2.stage_02b_anatomy_repair(ctx) is None
    meta = seen[0]['meta'][0]
    assert meta['qa_score'] == qa_score
    assert meta['qa_issues'] == issues
    # No scene of its own, so the repair prompt is empty either way.
    assert meta['subject'] == '' and meta['prompt'] == ''
    assert ctx.spy.msgs('WARNING') == []
    # `repair_batch` returned the metadata untouched, so nothing is swapped in.
    assert ctx.scene_images == [str(tmp_path / 'a.png')]
    assert 'Anatomy repair complete: 0/1 image(s) repaired' in ctx.spy.msgs('INFO')


def test_a_repair_whose_index_is_out_of_range_is_ignored(monkeypatch, stub_module, tmp_path):
    fake_anatomy_stack(monkeypatch, image=None)
    out_of_range = [{'index': 7, 'path': '/nope.png', 'repair_pass': True}, {}]
    stub_module('flux_fill_service', fill_service(repaired=out_of_range))
    ctx = with_stills(tmp_path, images=('a.png',))

    assert ST2.stage_02b_anatomy_repair(ctx) is None
    assert ctx.scene_images == [str(tmp_path / 'a.png')]
    assert 'Anatomy repair complete: 0/1 image(s) repaired' in ctx.spy.msgs('INFO')


def test_a_failing_repair_batch_is_non_fatal_and_the_stage_still_completes(monkeypatch, stub_module, tmp_path):
    fake_anatomy_stack(monkeypatch, image=None)
    stub_module('flux_fill_service', fill_service(exc=RuntimeError('flux-fill weights gone')))
    ctx = with_stills(tmp_path)

    assert ST2.stage_02b_anatomy_repair(ctx) is None
    assert 'Anatomy repair failed (non-fatal): flux-fill weights gone' in ctx.spy.msgs('WARNING')
    assert ctx.spy.completed == ['Anatomy Repair']
