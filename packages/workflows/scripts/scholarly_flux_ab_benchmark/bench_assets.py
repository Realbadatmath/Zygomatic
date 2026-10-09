# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Constants, environment preparation and the benchmark's input assets.

Moved verbatim out of scripts/scholarly_flux_ab_benchmark.py; this module
carries the pre-split file's top import block, so `__file__` and `__name__`
are re-anchored onto the pre-split script — `_CREWS` (and the sys.path insert
and every path derived from it) and the logger name depend on them.
"""

# ruff: noqa: F401  # the original top import block lives here; siblings re-import from it

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging as _zyg_logging

from zyg_workflows import paths

__file__ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scholarly_flux_ab_benchmark.py')
__name__ = 'scholarly_flux_ab_benchmark'

_zyg_log = _zyg_logging.getLogger(__name__)

_CREWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CREWS))

_FLUX_PATH = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
_OUT_ROOT = _CREWS / 'data' / 'runtime' / 'scholarly_flux_ab'
_STEPS = 20
_CFG = 3.5
_W, _H = 1280, 720
_PARITY = os.environ.get('ZYG_BENCH_PARITY', '').strip().lower() in ('1', 'true', 'yes', 'on')
_REALISTIC = os.environ.get('ZYG_BENCH_REALISTIC', '').strip().lower() in ('1', 'true', 'yes', 'on')
_PERSISTENT = os.environ.get('ZYG_BENCH_PERSISTENT', '').strip().lower() in ('1', 'true', 'yes', 'on')

# Realistic concurrent mode parameters — derived from benchmark_telemetry.json
# (12-pipeline production sample, Jun 2026).
_REALISTIC_N_PIPELINES = int(os.environ.get('ZYG_BENCH_N_PIPELINES', '6'))
_REALISTIC_STAGGER_S = float(os.environ.get('ZYG_BENCH_STAGGER_S', '30'))
_REALISTIC_IMAGES = int(os.environ.get('ZYG_BENCH_IMAGES_PER_PIPELINE', '28'))
# Pre-Stage-3.5 wall time: research(4s) + script(88s) + visual_tagging(21s) + emotion(5s)
_REALISTIC_PRE_FLUX_S = float(os.environ.get('ZYG_BENCH_PRE_FLUX_S', '118'))

# Shared subject key for pose cache (matches production per-subject CN caching).
_PARITY_SUBJ_KEY = 'scholarly_bench_subject'
# Confirmed on-disk bible + portrait dataset (see character_bible_service.bible_path).
_BENCH_DEFAULT_CHAR_ID = '1a2b6cfc0f93'
_BENCH_POSE_SKELETON_ASSET = _CREWS / 'data' / 'runtime' / 'bench_assets' / 'scholarly_parity_pose_skeleton.png'

BENCH_SLOTS: list[tuple[str, str]] = [
    ('portrait_01', 'medium shot portrait of a scholar in a dim archive, soft key light, photorealistic documentary'),
    ('portrait_02', 'close-up portrait of a woman reading by candlelight, five fingers visible on hands, cinematic'),
    ('figure_03', 'tight shot of a historian gesturing while lecturing, natural hands, documentary realism'),
    ('face_04', 'chest-up portrait of an elderly man with weathered face, symmetrical features, film grain'),
    ('person_05', 'medium shot of a student in university hall, correct human proportions, shallow depth of field'),
    ('portrait_06', 'portrait of a museum curator beside artifact case, relaxed natural hand pose'),
    ('figure_07', 'waist-up shot of a writer at wooden desk, visible hands on manuscript, photorealistic'),
    ('face_08', 'close portrait of a young researcher, clear facial structure, documentary lighting'),
    ('person_09', 'medium shot of a guide explaining exhibit, natural anatomy, 8k cinematic'),
    ('tight_10', 'tight crop on hands turning pages of ancient book, five fingers per hand, macro documentary'),
]


def _log(msg: str) -> None:
    print(f'[bench] {msg}', flush=True)


def _stop_flask_dashboards_for_benchmark() -> list[int]:
    if os.environ.get('ZYG_BENCH_KEEP_FLASK', '').strip().lower() in ('1', 'true', 'yes'):
        return []
    import signal
    import subprocess

    stopped: list[int] = []
    try:
        out = subprocess.check_output(
            ['pgrep', '-f', 'crewai_web_gui.py'],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            try:
                pid = int(line.strip().split()[0])
            except (ValueError, IndexError):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
            except (ProcessLookupError, PermissionError):
                pass
    except subprocess.CalledProcessError:
        pass
    if stopped:
        time.sleep(3)
        _log(f'Stopped Flask dashboard PID(s) for benchmark: {stopped}')
    return stopped


def _gpu_exclusivity_sweep() -> None:
    _log('GPU exclusivity sweep…')
    _stop_flask_dashboards_for_benchmark()
    try:
        from zyg_workflows import _comfy_client as cc

        if cc.server_reachable(timeout_s=2.0):
            cc.interrupt_execution()
            cc.free_vram()
            _log('ComfyUI interrupted + /free')
    except Exception as exc:
        _log(f'Comfy sweep: {exc}')
    try:
        from zyg_workflows import character_photo_analysis_service as cpas

        evicted = cpas.evict_all_ollama_models(log_fn=_log)
        if evicted:
            _log(f'Ollama evicted: {evicted}')
    except Exception as exc:
        _log(f'Ollama evict: {exc}')
    try:
        import gc
        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            free_gb = torch.cuda.mem_get_info(0)[0] / 1024**3
            _log(f'VRAM free: {free_gb:.1f} GB')
    except Exception as exc:
        _log(f'torch cache: {exc}')


_REF_IMAGE_NAMES = (
    'portrait_00_000deg.png',
    'preview_flux_front.png',
    'full_neutral_00_000deg.png',
    'full_neutral_000deg.png',
    'full_00_000deg.png',
    'preview_flux_face.png',
)


def _char_reference_image(char_id: str) -> str | None:
    root = paths.ZYG_LORA_DATASETS / 'storyteller_chars' / char_id
    for name in _REF_IMAGE_NAMES:
        p = root / name
        if p.is_file() and p.stat().st_size > 10_000:
            return str(p)
    return None


def _resolve_bench_char_id(pose_ref: str | None) -> str:
    """Pick a character id with a loadable bible package on disk."""
    from zyg_workflows import character_bible_service as cbs

    explicit = os.environ.get('ZYG_BENCH_CHAR_ID', '').strip()
    if explicit:
        if cbs.load(explicit):
            return explicit
        _log(f'WARN: ZYG_BENCH_CHAR_ID={explicit} has no bible — trying defaults')

    for cand in (_BENCH_DEFAULT_CHAR_ID,):
        if cbs.load(cand):
            return cand

    root = paths.ZYG_LORA_DATASETS / 'storyteller_chars'
    for d in sorted(root.iterdir()):
        if d.is_dir() and cbs.load(d.name):
            _log(f'Bench char fallback: {d.name}')
            return d.name
    return explicit or _BENCH_DEFAULT_CHAR_ID


def _find_bench_reference(char_id: str | None = None) -> str | None:
    env = os.environ.get('ZYG_BENCH_CHAR_REF', '').strip()
    if env and os.path.isfile(env):
        return env
    cid = (char_id or os.environ.get('ZYG_BENCH_CHAR_ID', '').strip() or _BENCH_DEFAULT_CHAR_ID).strip()
    if cid:
        ref = _char_reference_image(cid)
        if ref:
            return ref
    _chars = paths.ZYG_LORA_DATASETS / 'storyteller_chars'
    if not _chars.is_dir():
        return None
    for _cid in sorted(_chars.iterdir()):
        if not _cid.is_dir():
            continue
        ref = _char_reference_image(_cid.name)
        if ref:
            _log(f'Pose reference: {ref}')
            return ref
    return None


def _load_bench_bible(char_id: str) -> tuple[dict | None, str]:
    from zyg_workflows import character_bible_service as cbs

    cid = (char_id or '').strip()
    pkg = cbs.load(cid) if cid else None
    if pkg:
        pkg = copy.deepcopy(pkg)
        cbs.apply_scholarly_conditioning_defaults(pkg)
        _log(f'Character bible loaded: {cid}')
    elif cid:
        _log(f'WARN: no character bible at {cbs.bible_path(cid)}')
    return pkg, cid


def _ensure_bench_pose_skeleton_asset(path: Path) -> None:
    """Create a canonical OpenPose-style skeleton map (green on black) for ControlNet."""
    if path.is_file() and path.stat().st_size > 2000:
        return
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(f'opencv required to build bench pose asset: {exc}') from exc

    w, h = _W, _H
    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    def pt(nx: float, ny: float) -> tuple[int, int]:
        return int(nx * w), int(ny * h)

    # Normalized standing pose (head → feet), OpenPose-like connectivity.
    joints = {
        'nose': (0.50, 0.14),
        'neck': (0.50, 0.22),
        'r_sho': (0.58, 0.24),
        'l_sho': (0.42, 0.24),
        'r_elb': (0.64, 0.36),
        'l_elb': (0.36, 0.36),
        'r_wri': (0.66, 0.48),
        'l_wri': (0.34, 0.48),
        'r_hip': (0.54, 0.50),
        'l_hip': (0.46, 0.50),
        'r_kne': (0.54, 0.68),
        'l_kne': (0.46, 0.68),
        'r_ank': (0.54, 0.86),
        'l_ank': (0.46, 0.86),
    }
    bones = (
        ('nose', 'neck'),
        ('neck', 'r_sho'),
        ('r_sho', 'r_elb'),
        ('r_elb', 'r_wri'),
        ('neck', 'l_sho'),
        ('l_sho', 'l_elb'),
        ('l_elb', 'l_wri'),
        ('neck', 'r_hip'),
        ('neck', 'l_hip'),
        ('r_hip', 'l_hip'),
        ('r_hip', 'r_kne'),
        ('r_kne', 'r_ank'),
        ('l_hip', 'l_kne'),
        ('l_kne', 'l_ank'),
    )
    green = (0, 255, 0)
    orange = (0, 140, 255)
    for a, b in bones:
        cv2.line(canvas, pt(*joints[a]), pt(*joints[b]), green, 3, cv2.LINE_AA)
    for _name, xy in joints.items():
        cv2.circle(canvas, pt(*xy), 5, green, -1, cv2.LINE_AA)
    # Simple five-finger hand stubs (anatomy bench emphasis).
    for wx, wy, dx in ((0.66, 0.48, 0.02), (0.34, 0.48, -0.02)):
        base = pt(wx, wy)
        for i in range(5):
            tip = pt(wx + dx * (i + 1), wy + 0.06 + i * 0.01)
            cv2.line(canvas, base, tip, orange, 2, cv2.LINE_AA)

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), canvas)
    _log(f'Built bench pose skeleton asset: {path}')


def _stage_pose_image(pose_ref: str | None, staging_dir: Path) -> str | None:
    """Stage pre-compiled skeleton for parity CN — never depends on MediaPipe at bench time."""
    out = staging_dir / 'parity_pose_skeleton.png'
    env_sk = os.environ.get('ZYG_BENCH_POSE_SKELETON', '').strip()
    sources: list[Path] = []
    if env_sk:
        sources.append(Path(env_sk))
    sources.append(_BENCH_POSE_SKELETON_ASSET)

    try:
        _ensure_bench_pose_skeleton_asset(_BENCH_POSE_SKELETON_ASSET)
    except Exception as exc:
        _log(f'WARN: could not build bundled pose skeleton: {exc}')

    for src in sources:
        if src.is_file() and src.stat().st_size > 500:
            shutil.copy2(src, out)
            _log(f'Pose skeleton staged (precompiled): {out} ← {src}')
            return str(out)

    if pose_ref and os.path.isfile(pose_ref):
        try:
            from zyg_workflows import controlnet_service as cns_mod

            pil = cns_mod.extract_pose_image(pose_ref)
            if pil is not None:
                pil.save(out)
                _log(f'Pose skeleton staged (extracted): {out}')
                return str(out)
        except Exception as exc:
            _log(f'pose extract fallback failed: {exc}')

    _log('WARN: no pose skeleton available — CN will be inactive')
    return None


def _qa_score(image_path: str) -> tuple[float, list[str]]:
    try:
        import cv2
        import mediapipe as mp

        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            return 1.0, []
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        issues: list[str] = []
        penalty = 0.0
        with mp.solutions.holistic.Holistic(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=0.5,
        ) as hol:
            res = hol.process(img_rgb)
            for side, hand_lms in (('left', res.left_hand_landmarks), ('right', res.right_hand_landmarks)):
                if hand_lms is None:
                    continue
                lm = hand_lms.landmark
                tips, mcps = [4, 8, 12, 16, 20], [2, 5, 9, 13, 17]
                n_ext = sum(1 for t, k in zip(tips, mcps) if lm[t].y < lm[k].y)
                if n_ext > 5:
                    issues.append(f'{side} hand: {n_ext} extended (>5)')
                    penalty += 0.35
                xs = [lm[i].x for i in range(21)]
                ys = [lm[i].y for i in range(21)]
                if (max(xs) - min(xs)) < 0.03 and (max(ys) - min(ys)) < 0.03:
                    issues.append(f'{side} hand: clustered')
                    penalty += 0.25
        return max(0.0, 1.0 - min(penalty, 1.0)), issues
    except Exception:
        return 1.0, []
