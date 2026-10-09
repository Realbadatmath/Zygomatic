# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The /api/pipeline/test component health probes and their task table.

Moved verbatim from ``bp_pipeline_api_steps.py`` lines 1101-1674 by the
2026-10-06 modularization split.
"""

import logging as _zyg_logging
import os

from zyg_workflows import paths
from zyg_workflows.bin import exe

from .stage_maps import (
    _COMFY_CHECKPOINTS_DIR,
    _FLUX_SCHNELL_DIR,
    _HF_HOME_DEFAULT,
    _HOME_DIR,
    _REALESRGAN_WEIGHTS,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api_steps')


# ── /api/pipeline/test — the non-destructive component health checks ─────────
# Every one of these was a closure inside api_pipeline_test. They are pure
# probes: each returns (status, detail) and raises nothing the caller does not
# already turn into ('fail', str(exc)). The four that read the GUI's own state
# take it as an argument instead of closing over it.


def _chk_anthropic():
    ak = os.environ.get('ANTHROPIC_API_KEY', '')
    if not ak:
        return 'fail', 'ANTHROPIC_API_KEY not set'
    try:
        import anthropic as _ant

        _c = _ant.Anthropic(api_key=ak)
        _r = _c.messages.create(model='claude-sonnet-4-6', max_tokens=5, messages=[{'role': 'user', 'content': 'hi'}])
        tokens = _r.usage.input_tokens + _r.usage.output_tokens
        return 'ok', (
            f'claude-sonnet-4-6 reachable — {tokens} tokens used (Stage 1: dual-prompt + music mood + scene planning)'
        )
    except Exception as _e:
        return 'fail', str(_e)


def _chk_anthropic_key_only():
    """Carried over unchanged, and unreferenced — ``pipeline_test_tasks`` names
    ``_chk_anthropic`` for that row, so nothing has ever called this. Kept
    because the quality pass moves code, it does not decide what to retire.
    """
    ak = os.environ.get('ANTHROPIC_API_KEY', '')
    if not ak:
        return 'fail', 'ANTHROPIC_API_KEY not set'
    return 'ok', f'Key present ({len(ak)} chars)'


def _chk_flux_weights():
    try:
        import glob as _glob

        # Check custom model path first (primary location)
        custom_path = _FLUX_SCHNELL_DIR
        if os.path.isdir(custom_path):
            hits = _glob.glob(os.path.join(custom_path, '**', '*.safetensors'), recursive=True) + [
                f for f in os.listdir(custom_path) if f.endswith('.safetensors')
            ]
            hits = list(set(hits))
            if hits:
                total_gb = sum(os.path.getsize(h) for h in hits if os.path.isfile(h)) / (1024**3)
                return 'ok', f'FLUX.1-schnell weights found at {custom_path} ({len(hits)} files, {total_gb:.0f}GB)'
        # Fall back to HF cache
        hf_home = os.environ.get('HF_HOME', _HF_HOME_DEFAULT)
        pattern = os.path.join(hf_home, 'hub', 'models--black-forest-labs--FLUX.1-schnell', '**', '*.safetensors')
        hits = _glob.glob(pattern, recursive=True)
        if hits:
            return 'ok', f'FLUX.1-schnell weights found in HF cache ({len(hits)} files)'
        return 'warn', 'FLUX.1-schnell weights not found — will download on first run'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_wan_service():
    # The probe used to put the zyg_dashboard directory on sys.path first; it holds
    # no ``wan_video_service`` module, so the lookup resolves the same without it.
    try:
        import importlib as _il

        spec = _il.util.find_spec('wan_video_service')
        if spec is None:
            return 'fail', 'wan_video_service.py not found'
        return 'ok', 'wan_video_service importable'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_tts():
    """IndexTTS-2 (primary) + Chatterbox (fallback) + the voice seed pool.

    Both engines run in their own venvs behind subprocess workers, so this
    checks files on disk rather than importing anything into the GUI.
    """
    try:
        from zyg_workflows import tts_service as _ts

        _missing = [
            _n
            for _n, _p in (
                ('indextts2 venv', _ts._INDEXTTS_PY),
                ('indextts2 worker', _ts._INDEXTTS_WORKER),
                ('chatterbox venv', _ts._CHATTERBOX_PY),
                ('chatterbox worker', _ts._CHATTERBOX_WORKER),
            )
            if not os.path.isfile(_p)
        ]
        _seeds = len(_ts._seed_pool())
        if not _seeds:
            return 'fail', f'no voice seeds in {_ts._SEED_POOL_DIR} — cloning cannot run'
        if 'indextts2 venv' in _missing or 'indextts2 worker' in _missing:
            return (
                'warn' if len(_missing) < 4 else 'fail',
                f'IndexTTS-2 unavailable ({", ".join(_missing)}); {_seeds} seed voices',
            )
        if _missing:
            return 'warn', f'fallback unavailable ({", ".join(_missing)}); {_seeds} seed voices'
        return 'ok', f'IndexTTS-2 + Chatterbox workers present, {_seeds} seed voices'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_mediapipe():
    try:
        import mediapipe as _mp  # noqa

        return 'ok', f'mediapipe {_mp.__version__} importable'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_ffmpeg():
    try:
        import subprocess as _sp

        out = _sp.check_output([exe('ffmpeg'), '-version'], stderr=_sp.STDOUT, timeout=5).decode()
        ver = out.split('\n')[0].replace('ffmpeg version', '').strip()
        return 'ok', f'ffmpeg {ver}'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_yolo():
    try:
        import ultralytics  # noqa

        return 'ok', f'ultralytics {ultralytics.__version__} importable'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_cv2():
    try:
        import cv2  # noqa

        return 'ok', f'cv2 {cv2.__version__} importable'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_diffusers():
    try:
        import diffusers  # noqa

        return 'ok', f'diffusers {diffusers.__version__} importable'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_cuda(gpu_scan_safe):
    if not gpu_scan_safe:
        return 'warn', 'Pipeline running — VRAM check skipped to avoid allocation race'
    try:
        import subprocess as _sp

        out = (
            _sp.check_output(
                [exe('nvidia-smi'), '--query-gpu=name,memory.total,memory.free', '--format=csv,noheader,nounits'],
                timeout=5,
            )
            .decode()
            .strip()
        )
        lines = [line.strip() for line in out.split('\n') if line.strip()]
        # Also show free VRAM vs WAN requirement
        try:
            import torch as _tc

            free_gb = _tc.cuda.mem_get_info()[0] / 1024**3
            wan_ok = '✓' if free_gb >= 28.0 else '⚠ WAN needs 28GB'
            return 'ok', '; '.join(lines) + f' | Free now: {free_gb:.1f}GB {wan_ok}'
        except Exception as _exc:
            # torch is optional here: nvidia-smi already answered the question.
            _zyg_log.debug('torch VRAM read skipped, reporting nvidia-smi only: %s', _exc)
            return 'ok', '; '.join(lines)
    except Exception as _exc:
        _zyg_log.warning('nvidia-smi probe failed, falling back to torch: %s', _exc)
    try:
        import torch

        if torch.cuda.is_available():
            vram = torch.cuda.get_device_properties(0).total_memory // (1024**3)
            free_gb = torch.cuda.mem_get_info()[0] / 1024**3
            wan_ok = '✓' if free_gb >= 28.0 else f'⚠ WAN needs 28GB free (only {free_gb:.1f}GB)'
            return 'ok', f'{torch.cuda.get_device_name(0)} — {vram}GB total | {free_gb:.1f}GB free {wan_ok}'
        # Diagnose driver/kernel mismatch
        import platform as _pl
        import subprocess as _sp

        kernel = _pl.release()
        try:
            dkms = _sp.check_output(
                [exe('dpkg'), '-l', f'linux-modules-nvidia-580-open-{kernel}'], stderr=_sp.DEVNULL, timeout=3
            ).decode()
            mod_installed = 'ii' in dkms
        except Exception as _exc:
            # No dpkg, or the package is simply not known here.
            _zyg_log.debug('kernel module query failed, assuming not installed: %s', _exc)
            mod_installed = False
        if not mod_installed:
            return 'warn', (
                f'CUDA not available — kernel {kernel} is missing NVIDIA module. '
                f'Fix: sudo apt install linux-modules-nvidia-580-open-{kernel}'
            )
        return 'warn', 'CUDA not available (CPU mode)'
    except Exception as _e:
        return 'warn', f'Cannot detect GPU: {_e}'


def _chk_character_bible():
    try:
        spec = __import__('importlib').util.find_spec('character_bible_service')
        if spec is None:
            return 'warn', 'character_bible_service.py not found'
        from zyg_workflows import character_bible_service as _cbs_h

        return 'ok', f'character_bible_service ready (bibles under {_cbs_h._DATASET_ROOT})'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_comfy_generation():
    try:
        spec = __import__('importlib').util.find_spec('comfy_generation_service')
        if spec is None:
            return 'warn', 'comfy_generation_service.py not found'
        from zyg_workflows import comfy_generation_service as _cgs_h

        if _cgs_h.is_primary_backend() and not _cgs_h.is_available():
            return 'warn', f'ZYG_COMFY_PRIMARY set but ComfyUI server not reachable at {paths.ZYG_COMFY_URL}'
        if _cgs_h.is_available():
            return 'ok', 'ComfyUI primary backend active and server reachable'
        return 'ok', 'comfy_generation_service ready (set ZYG_COMFY_PRIMARY=1 to route stills)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_consistency_qa():
    try:
        spec = __import__('importlib').util.find_spec('consistency_qa_service')
        if spec is None:
            return 'warn', 'consistency_qa_service.py not found'
        from zyg_workflows import consistency_qa_service as _cqa_h

        return 'ok', f'consistency_qa ready (backend={_cqa_h._embed_backend}, threshold={_cqa_h._DEFAULT_THRESHOLD})'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_flux_fill_service():
    try:
        spec = __import__('importlib').util.find_spec('flux_fill_service')
        if spec is None:
            return 'warn', 'flux_fill_service.py not found'
        return 'ok', 'flux_fill_service importable (Stage 3.6 documentary / Stage 2b video — Anatomy Repair ready)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_object_track_service():
    try:
        spec = __import__('importlib').util.find_spec('object_track_service')
        if spec is None:
            return 'warn', 'object_track_service.py not found'
        return (
            'ok',
            'object_track_service importable (Stage 4.1 documentary / Stage 4b video — Object Tracking ready)',
        )
    except Exception as _e:
        return 'warn', str(_e)


def _chk_rife_service():
    try:
        spec = __import__('importlib').util.find_spec('rife_service')
        if spec is None:
            return 'warn', 'rife_service.py not found'
        return 'ok', 'rife_service importable (Stage 4.2 ready)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_audio_service():
    try:
        import importlib.util as _ilu_a

        spec = _ilu_a.find_spec('audio_service')
        if spec is None:
            return 'warn', 'audio_service.py not found'
        from zyg_workflows import audio_service as _asvc_hc

        has_foley = hasattr(_asvc_hc, 'mix_foley_into_audio')
        has_bgm = hasattr(_asvc_hc, 'mix_bgm_into_video')
        has_mood = hasattr(_asvc_hc, 'get_music_for_topic') and 'music_mood' in (
            __import__('inspect').signature(_asvc_hc.get_music_for_topic).parameters
        )
        parts = ['audio_service importable']
        if has_foley:
            parts.append(
                'foley SFX ready (generative tier disabled 2026-08-09: AudioGen CC-BY-NC — Freesound/soundbible tiers active)'
            )
        if has_bgm:
            parts.append('BGM mixing ready (Stage 5b — ACE-Step 1.5, MIT)')
        if has_mood:
            parts.append('Claude music_mood override supported')
        status = 'ok' if (has_foley and has_bgm) else 'warn'
        return status, ' — '.join(parts)
    except Exception as _e:
        return 'warn', str(_e)


def _chk_musicgen_service():
    # Stage 5b engine is ACE-Step 1.5 (MIT) since 2026-08-09; MusicGen
    # (CC-BY-NC weights) is retired. Function name kept for TASKS stability.
    try:
        spec = __import__('importlib').util.find_spec('ace_step_service')
        if spec is None:
            return 'warn', 'ace_step_service.py not found'
        from zyg_workflows import ace_step_service as _ace

        if _ace.is_available():
            return 'ok', (
                f'ace_step_service ready — {_ace.model_id()} '
                f'(Claude selects mood; 8 moods: epic/battle/triumphant/mysterious/sad/peaceful/dark/adventure)'
            )
        _ckpt = os.path.join(_COMFY_CHECKPOINTS_DIR, _ace.CHECKPOINT)
        if not os.path.isfile(_ckpt):
            return 'warn', f'ACE-Step checkpoint missing: {_ckpt}'
        return 'warn', 'ACE-Step checkpoint present but ComfyUI server unreachable'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_output_dir(runtime_path, runtime_dir):
    try:
        test_dir = runtime_path('_test_write_check')
        os.makedirs(test_dir, exist_ok=True)
        test_file = os.path.join(test_dir, 'probe.tmp')
        with open(test_file, 'w') as _f:
            _f.write('ok')
        os.remove(test_file)
        os.rmdir(test_dir)
        return 'ok', f'Output directory writable: {runtime_dir}'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_lora_weights(lora_path, lora_scale):
    try:
        if not lora_path:
            return 'warn', 'LoRA disabled (_FLUX_LORA_PATH is None)'
        lora_sf = os.path.join(lora_path, 'pytorch_lora_weights.safetensors')
        if os.path.isfile(lora_sf):
            size_mb = os.path.getsize(lora_sf) / (1024**2)
            return 'ok', f'LoRA weights found at {lora_path} ({size_mb:.0f}MB, scale={lora_scale})'
        if os.path.isdir(lora_path):
            files = os.listdir(lora_path)
            return 'warn', f'LoRA dir exists but pytorch_lora_weights.safetensors missing — contents: {files}'
        return 'fail', f'LoRA path not found: {lora_path}'
    except Exception as _e:
        return 'fail', str(_e)


def _chk_wan_weights():
    try:
        import glob as _glob

        hf_home = os.environ.get('HF_HOME', _HF_HOME_DEFAULT)
        pattern = os.path.join(
            hf_home, 'hub', 'models--Wan-AI--Wan2.1-I2V-14B-480P-Diffusers', 'snapshots', '**', '*.safetensors'
        )
        hits = _glob.glob(pattern, recursive=True)
        if hits:
            total_gb = sum(os.path.getsize(h) for h in hits if os.path.isfile(h)) / (1024**3)
            return 'ok', f'Wan2.1-I2V-14B-480P weights found ({len(hits)} files, {total_gb:.0f}GB)'
        # Check if dir exists but is empty / only refs
        wan_dir = os.path.join(hf_home, 'hub', 'models--Wan-AI--Wan2.1-I2V-14B-480P-Diffusers')
        if os.path.isdir(wan_dir):
            return 'warn', 'Wan2.1-I2V-14B-480P dir exists but no .safetensors found — may still be downloading'
        return 'warn', 'Wan2.1-I2V-14B-480P not in HF cache — will download on first run (~30GB)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_vllm():
    try:
        import vllm  # noqa

        return 'ok', f'vLLM {vllm.__version__} importable (required by Orpheus TTS)'
    except ImportError:
        return 'warn', 'vLLM not installed — Orpheus TTS will not work. Install: pip install vllm'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_snac():
    try:
        import snac  # noqa

        return 'ok', 'SNAC importable (required by Orpheus TTS audio decoder)'
    except ImportError:
        return 'warn', 'SNAC not installed — Orpheus TTS will not work. Install: pip install snac'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_ipadapter_weights():
    try:
        import glob as _glob

        hf_home = os.environ.get('HF_HOME', _HF_HOME_DEFAULT)
        pattern = os.path.join(hf_home, 'hub', 'models--XLabs-AI--flux-ip-adapter', '**', 'ip_adapter.safetensors')
        hits = _glob.glob(pattern, recursive=True)
        if hits:
            return 'ok', 'IPAdapter weights cached (Stage 9 ready)'
        return 'warn', 'IPAdapter weights not cached — will download on first Stage 9 run'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_controlnet_weights():
    try:
        import glob as _glob

        hf_home = os.environ.get('HF_HOME', _HF_HOME_DEFAULT)
        pattern = os.path.join(
            hf_home,
            'hub',
            'models--InstantX--FLUX.1-dev-Controlnet-Union',
            '**',
            'diffusion_pytorch_model.safetensors',
        )
        hits = _glob.glob(pattern, recursive=True)
        if hits:
            return 'ok', 'ControlNet Union (pose mode 4) weights cached (Stage 10 ready)'
        return 'warn', 'ControlNet Union weights not cached — will download on first Stage 10 run (~3GB)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_disk_space():
    try:
        import shutil as _sh

        total, used, free = _sh.disk_usage(_HOME_DIR)
        free_gb = free / (1024**3)
        total_gb = total / (1024**3)
        used_pct = used / total * 100
        if free_gb < 50:
            return 'fail', f'Low disk space: {free_gb:.0f}GB free of {total_gb:.0f}GB ({used_pct:.0f}% used)'
        if free_gb < 150:
            return 'warn', f'Disk space: {free_gb:.0f}GB free of {total_gb:.0f}GB ({used_pct:.0f}% used)'
        return 'ok', f'{free_gb:.0f}GB free of {total_gb:.0f}GB ({used_pct:.0f}% used)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_ram():
    try:
        with open('/proc/meminfo') as _mf:
            lines = {line.split(':')[0]: line.split(':')[1].strip() for line in _mf if ':' in line}
        total_kb = int(lines.get('MemTotal', '0 kB').split()[0])
        avail_kb = int(lines.get('MemAvailable', '0 kB').split()[0])
        total_gb = total_kb / (1024**2)
        avail_gb = avail_kb / (1024**2)
        used_pct = (1 - avail_kb / total_kb) * 100
        if avail_gb < 8:
            return 'fail', f'Low RAM: {avail_gb:.0f}GB available of {total_gb:.0f}GB ({used_pct:.0f}% used)'
        if avail_gb < 20:
            return 'warn', f'RAM: {avail_gb:.0f}GB available of {total_gb:.0f}GB ({used_pct:.0f}% used)'
        return 'ok', f'{avail_gb:.0f}GB available of {total_gb:.0f}GB ({used_pct:.0f}% used)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_controlnet_service():
    try:
        spec = __import__('importlib').util.find_spec('controlnet_service')
        if not spec:
            return 'warn', 'controlnet_service.py not found'
        from zyg_workflows import controlnet_service as _cns

        if not os.path.isdir(_FLUX_SCHNELL_DIR):
            return 'warn', 'controlnet_service importable but FLUX base model missing'
        return 'ok', f'controlnet_service ready (VRAM threshold: {_cns._MIN_VRAM_GB} GB)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_ipadapter_service():
    try:
        spec = __import__('importlib').util.find_spec('ipadapter_service')
        if not spec:
            return 'warn', 'ipadapter_service.py not found'
        from zyg_workflows import ipadapter_service as _ipa

        return 'ok', f'ipadapter_service ready (VRAM threshold: {_ipa._MIN_VRAM_GB} GB)'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_esrgan_model():
    try:
        if os.path.exists(_REALESRGAN_WEIGHTS):
            size_mb = os.path.getsize(_REALESRGAN_WEIGHTS) / 1024 / 1024
            return 'ok', f'RealESRGAN_x4plus.pth present ({size_mb:.0f} MB) — Stage 2 4× upscale ready'
        return 'warn', f'RealESRGAN_x4plus.pth not found at {_REALESRGAN_WEIGHTS}'
    except Exception as _e:
        return 'warn', str(_e)


def _chk_soundfile():
    try:
        import soundfile as _sf

        return 'ok', f'soundfile {_sf.__version__} — audio WAV save backend ready'
    except ImportError:
        return 'fail', 'soundfile not installed — audio save will fail (run: pip install soundfile)'
    except Exception as _e:
        return 'warn', str(_e)


def pipeline_test_tasks(gpu_scan_safe, runtime_path, runtime_dir, lora_path, lora_scale):
    """The ``(label, probe)`` table /api/pipeline/test runs, in report order.

    The four probes that need GUI state are bound here so every entry is a
    plain zero-argument callable, exactly as the route's thread pool expects.
    """
    return [
        ('Anthropic API — claude-sonnet-4-6 (Stage 1: scene plan, dual-prompt, music mood)', _chk_anthropic),
        ('FLUX.1-schnell weights (Stage 2: image generation)', _chk_flux_weights),
        ('FLUX LoRA weights', lambda: _chk_lora_weights(lora_path, lora_scale)),
        ('WAN video service (Stage 4: I2V — wan_prompt + VRAM pre-check)', _chk_wan_service),
        ('WAN model weights (~30GB, Stage 4)', _chk_wan_weights),
        ('CUDA / GPU — free VRAM vs WAN 28GB requirement', lambda: _chk_cuda(gpu_scan_safe)),
        ('vLLM (Orpheus engine)', _chk_vllm),
        ('SNAC (Orpheus decoder)', _chk_snac),
        ('tts (indextts2+chatterbox)', _chk_tts),
        ('MediaPipe', _chk_mediapipe),
        ('ffmpeg', _chk_ffmpeg),
        ('YOLOv8 (ultralytics)', _chk_yolo),
        ('OpenCV (cv2)', _chk_cv2),
        ('diffusers', _chk_diffusers),
        ('character_bible_service (continuity packages)', _chk_character_bible),
        ('comfy_generation_service (ComfyUI primary stills)', _chk_comfy_generation),
        ('consistency_qa_service (identity drift detection)', _chk_consistency_qa),
        ('flux_fill_service (Stage 3.6 doc / Stage 2b video — Anatomy Repair)', _chk_flux_fill_service),
        ('object_track_service (Stage 4.1 doc / Stage 4b video — Object Tracking)', _chk_object_track_service),
        ('rife_service (Stage 4.2 doc / Stage 4c video — Temporal Repair)', _chk_rife_service),
        ('Real-ESRGAN model weights (Stage 2 video — 4× upscale)', _chk_esrgan_model),
        ('controlnet_service (Stage 2 video — pose conditioning)', _chk_controlnet_service),
        ('ipadapter_service (Stage 2 video — visual reference conditioning)', _chk_ipadapter_service),
        ('ControlNet Union weights (Stage 2 video — pose mode)', _chk_controlnet_weights),
        ('IPAdapter weights (Stage 2 video — visual reference)', _chk_ipadapter_weights),
        (
            'audio_service (Stage 4c video: library foley [generative tier disabled] + Stage 5b: BGM)',
            _chk_audio_service,
        ),
        ('soundfile (audio WAV save backend)', _chk_soundfile),
        ('ace_step_service (Stage 5b: AI BGM — ACE-Step 1.5 MIT, Claude-selected mood)', _chk_musicgen_service),
        ('Disk space', _chk_disk_space),
        ('RAM', _chk_ram),
        ('Output directory writable', lambda: _chk_output_dir(runtime_path, runtime_dir)),
    ]
