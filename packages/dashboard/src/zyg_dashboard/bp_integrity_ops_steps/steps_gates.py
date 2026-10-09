# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Check functions for the vision tools, the QC gates and the licence
tripwires (verbatim from bp_integrity_ops_steps.py)."""

from zyg_dashboard.bp_integrity_ops_steps.constants import (
    _FLUX_DEV_GLOBS,
    _FLUX_DEV_HF_REPOS,
    _HF_HUB,
    _STYLE_LORA_DIR,
    _env_on,
    _g,
    _hf_weight_files,
    _main_mod,
    paths,
)


import os

from zyg_dashboard import paths as _dash_paths


# ── Vision tools ─────────────────────────────────────────────────────────────
def _step_sam3():
    from zyg_workflows import sam3_service as _s3

    _ok, _why = _s3.available()
    if not _ok:
        return 'warn', f'{_why} — prop-persistence sweep skipped'
    return (
        'pass',
        'SAM 3 worker + weights | phrase segmentation for the prop-persistence sweep (advisory) | SAM License, internal tool',
    )


def _step_sam3d_body():
    from zyg_workflows import sam3d_body_service as _sb

    _ok, _why = _sb.available()
    if not _ok:
        return 'warn', _why
    return 'pass', 'SAM 3D Body worker + MHR assets (isolated body_venv) | SAM License, internal tool'


def _step_object_tracking():
    from zyg_workflows import object_track_service as _ots

    try:
        import ultralytics as _ul
    except Exception as _e:
        return 'warn', f'ultralytics not importable ({_e}) — object tracking skipped'
    _w = _ots._YOLO_MODEL
    _have = any(os.path.isfile(p) for p in (os.path.join(str(_dash_paths.PKG_DIR), _w), _w))
    return 'pass', (
        f'{_w} via ultralytics {_ul.__version__} | weights {"present" if _have else "auto-download on first use"}'
    )


def _step_bg_remove():
    from zyg_workflows import bg_remove_service as _bg

    _d = _bg.status_detail()
    return ('pass' if _d.endswith('ready') else 'warn'), _d + ' | CPU'


def _step_mediapipe_pkg():
    try:
        import mediapipe as _mp

        return 'pass', f'mediapipe {_mp.__version__} — hand landmarker (hand QC), pose (Wan-Animate driver)'
    except Exception as _e:
        return 'fail', str(_e)


def _step_cv2_pkg():
    try:
        import cv2

        return 'pass', f'cv2 {cv2.__version__} — frame extraction, TELEA inpaint, image processing'
    except Exception as _e:
        return 'fail', str(_e)


# ── QC gates ─────────────────────────────────────────────────────────────────
def _step_licence_gate():
    from zyg_workflows import licence_provenance as _lp
    from zyg_workflows import qc_contract as _qc

    _reg = _lp.load_registry()
    if not _reg['weights']:
        return (
            'fail',
            f'licence registry empty or unreadable ({_lp.REGISTRY_PATH}) — every weight classifies UNKNOWN',
        )
    _state = _lp.flux_state()
    _detail = (
        f'{len(_reg["weights"])} weight rules, {len(_reg["families"])} families, '
        f'{len(_reg.get("lora_lineage") or [])} LoRA lineage rules | mode: '
        f'{_qc.mode_for("licence_provenance:")} | FLUX.1-dev renders: {_state}'
    )
    if _state != 'paused':
        return 'warn', _detail + ' — ZYG_FLUX_RENDERS lets non-commercial FLUX output through'
    return 'pass', _detail


def _step_vlm_judge():
    from zyg_workflows import vlm_inspector as _vi

    if not _vi._enabled():
        return 'warn', 'ZYG_VLM=0 — local Qwen3-VL judge disabled'
    if not _vi.available():
        return 'warn', f'judge venv or worker missing under {_vi.VLM_HOME}'
    return 'pass', (
        f'{_vi.RESIDENT_MODEL.split("/")[-1]} resident / {_vi.BOUNDARY_MODEL.split("/")[-1]} '
        f'boundary | isolated venv worker | refuses GPU while ComfyUI samples'
    )


def _step_typography_gate():
    from zyg_workflows import typography_ocr as _to

    if not _to.available():
        return 'warn', 'RapidOCR engine failed to load — the typography gate cannot read lettering'
    return 'pass', 'RapidOCR (PP-OCR, CPU) | flags gibberish lettering | no VRAM, no API cost | Apache-2.0'


def _step_era_gate_chk():
    from zyg_workflows import era_gate as _eg  # noqa: F401

    return 'pass', 'era_gate loads | per-slot anachronism checks | resident VLM tier, claude-haiku-4-5 API fallback'


def _step_hand_qc():
    from zyg_workflows import anatomy_qc as _aq
    from zyg_workflows import hand_qc_service as _hq

    _ok, _why = _aq.hands_available()
    _chosen, _vlm = _hq._BACKEND, _hq._VLM_MODEL
    if _chosen in ('yolo', 'mediapipe-unavailable'):
        return (
            'warn',
            f'this process locked onto backend "{_chosen}" (YOLO is AGPL-3.0, development only) | VLM {_vlm}',
        )
    if not _ok:
        return 'warn', f'MediaPipe hand landmarker unavailable ({_why}) — auto mode falls back to YOLO | VLM {_vlm}'
    return 'pass', (
        f'MediaPipe hand_landmarker (Apache-2.0) + VLM {_vlm} | backend in this process: {_chosen or "not chosen yet"}'
    )


def _step_identity_qc():
    from zyg_workflows import identity_qc_service as _iq

    _ok, _why = _iq.available()
    if not _ok:
        return 'warn', f'{_why} — identity scoring skipped'
    return 'pass', (
        f'{_iq._PACK} pack via insightface worker | yaw-bucketed thresholds'
        f'{" | Apache-2.0" if _iq._PACK == "auraface" else ""}'
    )


def _step_restoration_qc_chk():
    from zyg_workflows import restoration_qc as _rq

    return (
        'pass',
        f'delta floor {_rq.DEFAULT_DELTA_FLOOR} vs a LANCZOS control | calibrated on RealESRGAN_x2 output',
    )


# ── Licence tripwires ────────────────────────────────────────────────────────
# PASS = ABSENT. Each weight here was removed on licence grounds; a warn
# means something brought it back (a re-download, a restore, a script).
def _step_flux_dev_absent():
    _hits = []
    for _pat in _FLUX_DEV_GLOBS:
        _hits += [os.path.basename(h) for h in _g.glob(_pat)]
    for _repo in _FLUX_DEV_HF_REPOS:
        if _hf_weight_files(_repo):
            _hits.append('HF ' + _repo[len('models--') :].replace('--', '/'))
    if _hits:
        return 'warn', (
            f'NON-COMMERCIAL FLUX.1-dev weights present: {", ".join(_hits)[:220]} — the family was deleted 2026-08-25'
        )
    return 'pass', (
        'FLUX.1-dev, Fill-dev and dev ControlNet-Union absent (deleted 2026-08-25) — '
        'controlnet_service and flux_fill_service find no cache and stay inert'
    )


def _step_ipadapter_weights():
    _pat = os.path.join(_HF_HUB, 'models--XLabs-AI--flux-ip-adapter', '**', 'ip_adapter.safetensors')
    _hits = _g.glob(_pat, recursive=True)
    # DELETED 2026-08-26 on licence grounds: the XLabs adapter is published
    # under flux-1-dev-non-commercial-license and the channel is monetised.
    # Present is the anomaly, because /api/hf/download now refuses this repo.
    if _hits:
        _sz = sum(os.path.getsize(h) for h in _hits if os.path.isfile(h)) / 1024**2
        return 'warn', (
            f'XLabs-AI/flux-ip-adapter present again ({_sz:.0f} MB) — '
            f'NON-COMMERCIAL weight, removed 2026-08-26. Investigate how '
            f'it returned before any monetised render.'
        )
    return 'pass', 'XLabs IP-Adapter absent (removed 2026-08-26) — ipadapter_service finds no cache and stays inert'


def _step_style_loras_absent():
    from zyg_workflows import licence_provenance as _lp

    _dir = _STYLE_LORA_DIR
    _files = sorted(f for f in os.listdir(_dir) if f.endswith('.safetensors')) if os.path.isdir(_dir) else []
    _reg = _lp.load_registry()
    _bad = [f for f in _files if _lp.classify_weight(f, registry=_reg).get('status') != 'cleared']
    _parts = []
    if _bad:
        _parts.append(f'{len(_bad)} uncleared file(s) in {_dir}: {", ".join(_bad)[:140]}')
    # 3d_render_lora's source repo: tagged apache-2.0, but the file header
    # says flux-1-dev/lora, so it was treated as non-commercial with the rest.
    _stray = _hf_weight_files('models--goofyai--3D_Render_for_flux')
    if _stray:
        _mb = sum(os.path.getsize(f) for f in _stray) / 1024**2
        _parts.append(
            f'HF cache still holds goofyai/3D_Render_for_flux ({_mb:.0f} MB, FLUX-dev LoRA) '
            f'— nothing loads it, but it was not deleted with the rest'
        )
    if _parts:
        return 'warn', ' | '.join(_parts) + ' — style LoRAs were removed 2026-08-27 on licence grounds'
    _state = f'{len(_files)} cleared replacement(s)' if _files else 'directory empty'
    return 'pass', f'{_state} — FLUX-dev style LoRAs removed 2026-08-27; styles render from prompt text'


def _step_cinematic_lora():
    _sf = os.path.join(
        getattr(
            _main_mod,
            '_FLUX_LORA_DIR',
            os.path.join(str(paths.ZYG_LORA_OUTPUTS), 'documentary-cinematic', 'lora-weights'),
        ),
        'pytorch_lora_weights.safetensors',
    )
    if not os.path.isfile(_sf):
        return 'pass', 'documentary-cinematic LoRA absent (FLUX.1-dev-derived, non-commercial)'
    _sz = os.path.getsize(_sf) / 1024**2
    if _env_on('ZYG_FLUX_STYLE_LORA', '0'):
        return 'warn', (
            f'cinematic LoRA ENABLED ({_sz:.0f} MB) — FLUX.1-dev-derived, non-commercial; '
            f'do not publish this output on a monetised channel'
        )
    return 'pass', f'cinematic LoRA on disk ({_sz:.0f} MB) but OFF by licence policy (ZYG_FLUX_STYLE_LORA unset)'


def _step_antelopev2_absent():
    from zyg_workflows import identity_qc_service as _iq

    _hits = [
        p
        for p in (
            os.path.join(_iq._insightface_root(), 'models', 'antelopev2'),
            os.path.join(str(paths.ZYG_HOME), '.insightface', 'models', 'antelopev2'),
        )
        if os.path.isdir(p) and os.listdir(p)
    ]
    if _hits:
        return 'warn', f'antelopev2 (non-commercial insightface pack) present again: {", ".join(_hits)}'
    return 'pass', f'antelopev2 absent (non-commercial, removed 2026-08-26) — identity QC runs the {_iq._PACK} pack'


def _step_audiogen_absent():
    # Generative foley DISABLED 2026-08-09: AudioGen weights are CC-BY-NC.
    # 'pass' means the disabled state is intact (no ag_* cache files left to
    # short-circuit); library tiers (Freesound/soundbible) cover foley.
    from zyg_workflows import audio_service as _asvc

    _stale = [f for f in os.listdir(_asvc.FOLEY_DIR) if f.startswith('ag_')]
    if _stale:
        return (
            'warn',
            f'{len(_stale)} stale AudioGen ag_*.mp3 cache file(s) present — NC audio could ship; purge to vault',
        )
    return (
        'pass',
        'generative foley disabled (AudioGen / MusicGen CC-BY-NC, retired 2026-08-09) — library tiers active',
    )
