# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for the /api/pipeline/test health probes.

Every probe in ``health_checks`` asks the machine a question — is a weight file
on disk, does a binary answer, is a service module importable. The CI runner can
answer none of them, so each probe is called directly with its one dependency
replaced, once answering yes and once answering no.
"""

import builtins
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import types

import pytest
import zyg_workflows

from zyg_dashboard.bp_pipeline_api_steps import health_checks as h

GB = 1024**3


def _mod(name='fake', **attrs):
    """A stand-in module object with the attributes a probe reads."""
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _install(monkeypatch, name, mod):
    # mod=None makes ``import <name>`` raise ImportError.
    monkeypatch.setitem(sys.modules, name, mod)


def _attach(monkeypatch, name, mod):
    # Makes ``from zyg_workflows import <name>`` yield mod.
    monkeypatch.setattr(zyg_workflows, name, mod, raising=False)


def _specs(monkeypatch, known=()):
    """Answer ``importlib.util.find_spec`` from a table instead of the disk."""

    def fake(name, package=None):
        return object() if name in known else None

    monkeypatch.setattr(importlib.util, 'find_spec', fake)


def _import_raises(monkeypatch, names, exc):
    """Make ``import <name>`` raise something other than ImportError."""
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name in names:
            raise exc
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, '__import__', fake)


def _fake_open(monkeypatch, path, text):
    real = builtins.open

    def opener(target, *a, **kw):
        if target == path:
            return io.StringIO(text)
        return real(target, *a, **kw)

    monkeypatch.setattr(builtins, 'open', opener)


def _touch(path, size=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)
    return path


# ── the Anthropic key probes ──────────────────────────────────────────────────


def test_anthropic_probes_need_a_key(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    assert h._chk_anthropic() == ('fail', 'ANTHROPIC_API_KEY not set')
    assert h._chk_anthropic_key_only() == ('fail', 'ANTHROPIC_API_KEY not set')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'abcd')
    assert h._chk_anthropic_key_only() == ('ok', 'Key present (4 chars)')


def test_anthropic_reports_the_tokens_the_ping_cost(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')
    reply = types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=7, output_tokens=3))
    client = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: reply))
    _install(monkeypatch, 'anthropic', _mod('anthropic', Anthropic=lambda api_key=None: client))
    status, detail = h._chk_anthropic()
    assert status == 'ok'
    assert '10 tokens used' in detail


def test_anthropic_turns_a_transport_error_into_fail(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')

    def explode(api_key=None):
        raise RuntimeError('connection refused')

    _install(monkeypatch, 'anthropic', _mod('anthropic', Anthropic=explode))
    assert h._chk_anthropic() == ('fail', 'connection refused')


# ── weight files on disk ──────────────────────────────────────────────────────


def test_flux_weights_prefer_the_custom_dir_then_the_hf_cache(monkeypatch, tmp_path):
    monkeypatch.setenv('HF_HOME', str(tmp_path / 'hf'))
    monkeypatch.setattr(h, '_FLUX_SCHNELL_DIR', str(tmp_path / 'flux'))
    assert h._chk_flux_weights()[0] == 'warn'
    _touch(tmp_path / 'hf' / 'hub' / 'models--black-forest-labs--FLUX.1-schnell' / 'a' / 'w.safetensors')
    assert h._chk_flux_weights() == ('ok', 'FLUX.1-schnell weights found in HF cache (1 files)')
    _touch(tmp_path / 'flux' / 'model.safetensors', size=2048)
    status, detail = h._chk_flux_weights()
    assert status == 'ok'
    assert 'weights found at' in detail


def test_wan_weights_cover_absent_then_empty_then_downloaded(monkeypatch, tmp_path):
    monkeypatch.setenv('HF_HOME', str(tmp_path / 'hf'))
    wan = tmp_path / 'hf' / 'hub' / 'models--Wan-AI--Wan2.1-I2V-14B-480P-Diffusers'
    assert 'will download on first run' in h._chk_wan_weights()[1]
    wan.mkdir(parents=True)
    assert 'may still be downloading' in h._chk_wan_weights()[1]
    _touch(wan / 'snapshots' / 'abc' / 'one.safetensors', size=4096)
    status, detail = h._chk_wan_weights()
    assert status == 'ok'
    assert '(1 files' in detail


_IPA_REL = 'hub/models--XLabs-AI--flux-ip-adapter/x/ip_adapter.safetensors'
_CNET_REL = 'hub/models--InstantX--FLUX.1-dev-Controlnet-Union/x/diffusion_pytorch_model.safetensors'


@pytest.mark.parametrize(
    ('probe', 'rel', 'found'),
    [
        (h._chk_ipadapter_weights, _IPA_REL, 'IPAdapter weights cached'),
        (h._chk_controlnet_weights, _CNET_REL, 'ControlNet Union'),
    ],
)
def test_hf_cache_probes_see_both_answers(monkeypatch, tmp_path, probe, rel, found):
    monkeypatch.setenv('HF_HOME', str(tmp_path / 'hf'))
    assert 'not cached' in probe()[1]
    _touch(tmp_path / 'hf' / rel)
    status, detail = probe()
    assert status == 'ok'
    assert found in detail


def test_esrgan_weights_both_ways(monkeypatch, tmp_path):
    monkeypatch.setattr(h, '_REALESRGAN_WEIGHTS', str(tmp_path / 'RealESRGAN_x4plus.pth'))
    assert h._chk_esrgan_model()[0] == 'warn'
    _touch(tmp_path / 'RealESRGAN_x4plus.pth', size=1024)
    status, detail = h._chk_esrgan_model()
    assert status == 'ok'
    assert 'present' in detail


@pytest.mark.parametrize(
    ('probe', 'target', 'attr', 'status'),
    [
        (h._chk_flux_weights, h.os.path, 'isdir', 'warn'),
        (h._chk_wan_weights, h.os.path, 'isdir', 'warn'),
        (h._chk_esrgan_model, h.os.path, 'exists', 'warn'),
        (lambda: h._chk_lora_weights('/x', 1.0), h.os.path, 'isfile', 'fail'),
        (h._chk_ipadapter_weights, h.os.environ, 'get', 'warn'),
        (h._chk_controlnet_weights, h.os.environ, 'get', 'warn'),
    ],
)
def test_disk_probes_survive_a_broken_filesystem(monkeypatch, probe, target, attr, status):
    monkeypatch.setattr(target, attr, lambda *a: (_ for _ in ()).throw(OSError('stale nfs')))
    assert probe() == (status, 'stale nfs')


def test_lora_weights_cover_disabled_missing_present_and_half_present(tmp_path):
    assert h._chk_lora_weights(None, 0.8)[0] == 'warn'
    assert h._chk_lora_weights(str(tmp_path / 'nope'), 1.0)[0] == 'fail'
    lora = tmp_path / 'lora'
    lora.mkdir()
    (lora / 'readme.txt').write_text('x')
    status, detail = h._chk_lora_weights(str(lora), 1.0)
    assert status == 'warn'
    assert 'readme.txt' in detail
    _touch(lora / 'pytorch_lora_weights.safetensors', size=2048)
    status, detail = h._chk_lora_weights(str(lora), 0.7)
    assert status == 'ok'
    assert 'scale=0.7' in detail


# ── importable-package probes ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('probe', 'name'),
    [
        (h._chk_mediapipe, 'mediapipe'),
        (h._chk_yolo, 'ultralytics'),
        (h._chk_cv2, 'cv2'),
        (h._chk_diffusers, 'diffusers'),
    ],
)
def test_version_probes_see_both_answers(monkeypatch, probe, name):
    _install(monkeypatch, name, _mod(name, __version__='9.9.9'))
    status, detail = probe()
    assert status == 'ok'
    assert '9.9.9' in detail
    _install(monkeypatch, name, None)
    assert probe()[0] == 'fail'


@pytest.mark.parametrize(('probe', 'name'), [(h._chk_vllm, 'vllm'), (h._chk_snac, 'snac')])
def test_orpheus_dependency_probes_see_three_answers(monkeypatch, probe, name):
    _install(monkeypatch, name, _mod(name, __version__='0.1'))
    assert probe()[0] == 'ok'
    _install(monkeypatch, name, None)
    assert probe()[0] == 'warn'
    _import_raises(monkeypatch, {name}, RuntimeError('abi mismatch'))
    assert probe() == ('warn', 'abi mismatch')


def test_soundfile_probe_sees_three_answers(monkeypatch):
    _install(monkeypatch, 'soundfile', _mod('soundfile', __version__='0.13'))
    assert h._chk_soundfile() == ('ok', 'soundfile 0.13 — audio WAV save backend ready')
    _install(monkeypatch, 'soundfile', None)
    assert h._chk_soundfile()[0] == 'fail'
    _import_raises(monkeypatch, {'soundfile'}, RuntimeError('libsndfile gone'))
    assert h._chk_soundfile() == ('warn', 'libsndfile gone')


def test_ffmpeg_probe_reads_the_banner_or_fails(monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **kw: b'ffmpeg version 6.1.1 built\nmore\n')
    assert h._chk_ffmpeg() == ('ok', 'ffmpeg 6.1.1 built')

    def explode(*a, **kw):
        raise FileNotFoundError('ffmpeg')

    monkeypatch.setattr(subprocess, 'check_output', explode)
    assert h._chk_ffmpeg()[0] == 'fail'


# ── service-module probes, answered from a find_spec table ────────────────────


@pytest.mark.parametrize(
    ('probe', 'name', 'fragment'),
    [
        (h._chk_wan_service, 'wan_video_service', 'wan_video_service importable'),
        (h._chk_flux_fill_service, 'flux_fill_service', 'flux_fill_service importable'),
        (h._chk_object_track_service, 'object_track_service', 'object_track_service importable'),
        (h._chk_rife_service, 'rife_service', 'rife_service importable (Stage 4.2 ready)'),
    ],
)
def test_spec_only_probes_see_both_answers(monkeypatch, probe, name, fragment):
    _specs(monkeypatch)
    assert f'{name}.py not found' in probe()[1]
    _specs(monkeypatch, known={name})
    assert fragment in probe()[1]


@pytest.mark.parametrize(
    'probe',
    [
        h._chk_wan_service,
        h._chk_flux_fill_service,
        h._chk_object_track_service,
        h._chk_rife_service,
        h._chk_character_bible,
        h._chk_comfy_generation,
        h._chk_consistency_qa,
        h._chk_musicgen_service,
        h._chk_audio_service,
        h._chk_controlnet_service,
        h._chk_ipadapter_service,
    ],
)
def test_service_probes_warn_when_the_spec_lookup_explodes(monkeypatch, probe):
    monkeypatch.setattr(
        importlib.util, 'find_spec', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('loader broken'))
    )
    assert probe() == ('warn', 'loader broken')


def test_character_bible_probe_both_ways(monkeypatch):
    _specs(monkeypatch)
    assert h._chk_character_bible()[0] == 'warn'
    _specs(monkeypatch, known={'character_bible_service'})
    _attach(monkeypatch, 'character_bible_service', _mod(_DATASET_ROOT='/tmp/bibles'))
    status, detail = h._chk_character_bible()
    assert status == 'ok'
    assert '/tmp/bibles' in detail


@pytest.mark.parametrize(
    ('primary', 'available', 'status', 'fragment'),
    [
        (True, False, 'warn', 'not reachable'),
        (True, True, 'ok', 'primary backend active'),
        (False, False, 'ok', 'set ZYG_COMFY_PRIMARY=1'),
    ],
)
def test_comfy_generation_probe_covers_the_backend_matrix(monkeypatch, primary, available, status, fragment):
    _specs(monkeypatch, known={'comfy_generation_service'})
    _attach(
        monkeypatch,
        'comfy_generation_service',
        _mod(is_primary_backend=lambda: primary, is_available=lambda: available),
    )
    got, detail = h._chk_comfy_generation()
    assert got == status
    assert fragment in detail


def test_consistency_qa_probe_both_ways(monkeypatch):
    _specs(monkeypatch)
    assert h._chk_consistency_qa()[0] == 'warn'
    _specs(monkeypatch, known={'consistency_qa_service'})
    _attach(monkeypatch, 'consistency_qa_service', _mod(_embed_backend='clip', _DEFAULT_THRESHOLD=0.8))
    status, detail = h._chk_consistency_qa()
    assert status == 'ok'
    assert 'backend=clip' in detail


@pytest.mark.parametrize(
    ('probe', 'name', 'attrs', 'fragment'),
    [
        (h._chk_controlnet_service, 'controlnet_service', {'_MIN_VRAM_GB': 12}, 'VRAM threshold: 12 GB'),
        (h._chk_ipadapter_service, 'ipadapter_service', {'_MIN_VRAM_GB': 8}, 'VRAM threshold: 8 GB'),
    ],
)
def test_vram_threshold_probes_both_ways(monkeypatch, tmp_path, probe, name, attrs, fragment):
    _specs(monkeypatch)
    assert f'{name}.py not found' in probe()[1]
    _specs(monkeypatch, known={name})
    _attach(monkeypatch, name, _mod(**attrs))
    monkeypatch.setattr(h, '_FLUX_SCHNELL_DIR', str(tmp_path))
    status, detail = probe()
    assert status == 'ok'
    assert fragment in detail


def test_controlnet_service_warns_without_the_flux_base(monkeypatch, tmp_path):
    _specs(monkeypatch, known={'controlnet_service'})
    _attach(monkeypatch, 'controlnet_service', _mod(_MIN_VRAM_GB=12))
    monkeypatch.setattr(h, '_FLUX_SCHNELL_DIR', str(tmp_path / 'absent'))
    assert h._chk_controlnet_service() == ('warn', 'controlnet_service importable but FLUX base model missing')


# ── audio probes ──────────────────────────────────────────────────────────────


def _audio_module(foley=True, bgm=True, mood=True):
    attrs = {}
    if foley:
        attrs['mix_foley_into_audio'] = lambda *a, **kw: None
    if bgm:
        attrs['mix_bgm_into_video'] = lambda *a, **kw: None
    if mood:
        attrs['get_music_for_topic'] = lambda topic, music_mood=None: None
    else:
        attrs['get_music_for_topic'] = lambda topic: None
    return _mod(**attrs)


def test_audio_and_ace_step_probes_warn_without_their_modules(monkeypatch):
    _specs(monkeypatch)
    assert h._chk_audio_service()[0] == 'warn'
    assert h._chk_musicgen_service()[0] == 'warn'
    assert h._chk_comfy_generation()[0] == 'warn'


def test_audio_service_probe_reports_every_feature(monkeypatch):
    _specs(monkeypatch, known={'audio_service'})
    _attach(monkeypatch, 'audio_service', _audio_module())
    status, detail = h._chk_audio_service()
    assert status == 'ok'
    assert 'foley SFX ready' in detail
    assert 'BGM mixing ready' in detail
    assert 'music_mood override supported' in detail


def test_audio_service_probe_warns_when_bgm_is_missing(monkeypatch):
    _specs(monkeypatch, known={'audio_service'})
    _attach(monkeypatch, 'audio_service', _audio_module(bgm=False, mood=False))
    status, detail = h._chk_audio_service()
    assert status == 'warn'
    assert 'BGM mixing ready' not in detail
    assert 'music_mood override supported' not in detail


def test_ace_step_probe_reports_the_model_when_reachable(monkeypatch):
    _specs(monkeypatch, known={'ace_step_service'})
    _attach(monkeypatch, 'ace_step_service', _mod(is_available=lambda: True, model_id=lambda: 'ace-step-1.5'))
    status, detail = h._chk_musicgen_service()
    assert status == 'ok'
    assert 'ace-step-1.5' in detail


def test_ace_step_probe_names_the_missing_checkpoint(monkeypatch, tmp_path):
    _specs(monkeypatch, known={'ace_step_service'})
    _attach(monkeypatch, 'ace_step_service', _mod(is_available=lambda: False, CHECKPOINT='ace.safetensors'))
    monkeypatch.setattr(h, '_COMFY_CHECKPOINTS_DIR', str(tmp_path))
    assert 'checkpoint missing' in h._chk_musicgen_service()[1]
    _touch(tmp_path / 'ace.safetensors')
    assert h._chk_musicgen_service() == ('warn', 'ACE-Step checkpoint present but ComfyUI server unreachable')


# ── TTS ───────────────────────────────────────────────────────────────────────


def _tts_module(tmp_path, present=('idx_py', 'idx_worker', 'cb_py', 'cb_worker'), seeds=2):
    files = {}
    for key in ('idx_py', 'idx_worker', 'cb_py', 'cb_worker'):
        p = tmp_path / key
        if key in present:
            _touch(p)
        files[key] = str(p)
    return _mod(
        _INDEXTTS_PY=files['idx_py'],
        _INDEXTTS_WORKER=files['idx_worker'],
        _CHATTERBOX_PY=files['cb_py'],
        _CHATTERBOX_WORKER=files['cb_worker'],
        _SEED_POOL_DIR=str(tmp_path / 'seeds'),
        _seed_pool=lambda: ['v%d' % i for i in range(seeds)],
    )


def test_tts_probe_ok_when_both_engines_are_installed(monkeypatch, tmp_path):
    _attach(monkeypatch, 'tts_service', _tts_module(tmp_path))
    assert h._chk_tts() == ('ok', 'IndexTTS-2 + Chatterbox workers present, 2 seed voices')


def test_tts_probe_fails_without_seed_voices(monkeypatch, tmp_path):
    _attach(monkeypatch, 'tts_service', _tts_module(tmp_path, seeds=0))
    assert 'cloning cannot run' in h._chk_tts()[1]


@pytest.mark.parametrize(
    ('present', 'status', 'fragment'),
    [
        (('cb_py', 'cb_worker'), 'warn', 'IndexTTS-2 unavailable'),
        ((), 'fail', 'IndexTTS-2 unavailable'),
        (('idx_py', 'idx_worker'), 'warn', 'fallback unavailable'),
    ],
)
def test_tts_probe_grades_the_missing_workers(monkeypatch, tmp_path, present, status, fragment):
    _attach(monkeypatch, 'tts_service', _tts_module(tmp_path, present=present))
    got, detail = h._chk_tts()
    assert got == status
    assert fragment in detail


def test_tts_probe_fails_when_the_service_module_is_broken(monkeypatch):
    _attach(monkeypatch, 'tts_service', _mod())
    assert h._chk_tts()[0] == 'fail'


# ── CUDA ──────────────────────────────────────────────────────────────────────

_SMI_LINE = 'NVIDIA RTX 6000, 49140, 45000\n'


def _torch(available=True, free_gb=40.0, name='NVIDIA RTX 6000', total_gb=48):
    return _mod(
        'torch',
        cuda=types.SimpleNamespace(
            is_available=lambda: available,
            mem_get_info=lambda: (int(free_gb * GB), 48 * GB),
            get_device_name=lambda i: name,
            get_device_properties=lambda i: types.SimpleNamespace(total_memory=total_gb * GB),
        ),
    )


def _smi(monkeypatch, smi_ok=True, dpkg=None):
    def check_output(argv, **kw):
        if 'nvidia-smi' in argv[0]:
            if not smi_ok:
                raise FileNotFoundError('nvidia-smi')
            return _SMI_LINE.encode()
        if dpkg is None:
            raise FileNotFoundError('dpkg')
        return dpkg.encode()

    monkeypatch.setattr(subprocess, 'check_output', check_output)


def test_cuda_probe_skipped_while_the_pipeline_runs():
    assert h._chk_cuda(False) == ('warn', 'Pipeline running — VRAM check skipped to avoid allocation race')


@pytest.mark.parametrize(('free_gb', 'fragment'), [(40.0, '✓'), (10.0, '⚠ WAN needs 28GB')])
def test_cuda_probe_adds_the_free_vram_from_torch(monkeypatch, free_gb, fragment):
    _smi(monkeypatch)
    _install(monkeypatch, 'torch', _torch(free_gb=free_gb))
    status, detail = h._chk_cuda(True)
    assert status == 'ok'
    assert 'NVIDIA RTX 6000' in detail
    assert fragment in detail


def test_cuda_probe_reports_nvidia_smi_alone_without_torch(monkeypatch):
    _smi(monkeypatch)
    _install(monkeypatch, 'torch', None)
    assert h._chk_cuda(True) == ('ok', 'NVIDIA RTX 6000, 49140, 45000')


def test_cuda_probe_falls_back_to_torch_or_gives_up(monkeypatch):
    _smi(monkeypatch, smi_ok=False)
    _install(monkeypatch, 'torch', _torch(free_gb=10.0))
    status, detail = h._chk_cuda(True)
    assert status == 'ok'
    assert 'only 10.0GB' in detail
    _install(monkeypatch, 'torch', None)
    status, detail = h._chk_cuda(True)
    assert status == 'warn'
    assert detail.startswith('Cannot detect GPU:')


@pytest.mark.parametrize(
    ('dpkg', 'fragment'),
    [(None, 'missing NVIDIA module'), ('ii  linux-modules-nvidia-580-open', 'CUDA not available (CPU mode)')],
)
def test_cuda_probe_diagnoses_a_cpu_only_machine(monkeypatch, dpkg, fragment):
    _smi(monkeypatch, smi_ok=False, dpkg=dpkg)
    _install(monkeypatch, 'torch', _torch(available=False))
    status, detail = h._chk_cuda(True)
    assert status == 'warn'
    assert fragment in detail


# ── machine resources and the output directory ────────────────────────────────


@pytest.mark.parametrize(
    ('free_gb', 'status'),
    [(30, 'fail'), (100, 'warn'), (500, 'ok')],
)
def test_disk_space_probe_covers_every_tier(monkeypatch, free_gb, status):
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: (1000 * GB, (1000 - free_gb) * GB, free_gb * GB))
    got, detail = h._chk_disk_space()
    assert got == status
    assert f'{free_gb}GB free' in detail


def test_disk_space_probe_survives_a_stat_failure(monkeypatch):
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: (_ for _ in ()).throw(OSError('no mount')))
    assert h._chk_disk_space() == ('warn', 'no mount')


@pytest.mark.parametrize(
    ('avail_kb', 'status'),
    [(4 * 1024**2, 'fail'), (15 * 1024**2, 'warn'), (40 * 1024**2, 'ok'), (0, 'warn')],
)
def test_ram_probe_covers_every_tier_and_an_empty_meminfo(monkeypatch, avail_kb, status):
    total_kb = 64 * 1024**2 if avail_kb else 0
    _fake_open(monkeypatch, '/proc/meminfo', f'MemTotal: {total_kb} kB\nMemAvailable: {avail_kb} kB\nnot a field\n')
    assert h._chk_ram()[0] == status


def test_output_dir_probe_writes_cleans_up_and_reports_a_read_only_tree(tmp_path):
    status, detail = h._chk_output_dir(lambda name: str(tmp_path / name), str(tmp_path))
    assert status == 'ok'
    assert str(tmp_path) in detail
    assert os.listdir(tmp_path) == []

    def explode(name):
        raise PermissionError('read-only filesystem')

    assert h._chk_output_dir(explode, '/nope') == ('fail', 'read-only filesystem')


# ── the task table ────────────────────────────────────────────────────────────


def test_pipeline_test_tasks_is_a_table_of_zero_argument_probes(monkeypatch, tmp_path):
    tasks = h.pipeline_test_tasks(False, lambda n: str(tmp_path / n), str(tmp_path), None, 0.8)
    assert len(tasks) == 31
    assert all(isinstance(label, str) and callable(probe) for label, probe in tasks)
    by_label = {label: probe for label, probe in tasks}
    assert by_label['FLUX LoRA weights']()[0] == 'warn'
    cuda = next(p for lab, p in tasks if lab.startswith('CUDA / GPU'))
    assert cuda() == ('warn', 'Pipeline running — VRAM check skipped to avoid allocation race')
    assert by_label['Output directory writable']()[0] == 'ok'
