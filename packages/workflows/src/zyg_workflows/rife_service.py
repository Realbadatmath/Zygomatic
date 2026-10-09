# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4.2 — RIFE temporal repair (frame interpolation).

Smooths temporal artefacts and stuttering in WAN-generated clips by running
2× frame interpolation.

Implementation strategy
-----------------------
Uses FFmpeg's ``minterpolate`` filter (motion-vector-based interpolation).
This is:
  - Available on any system with ffmpeg ≥ 4.x (our ffmpeg is 6.1)
  - GPU-accelerated optionally but works on CPU
  - Motion-compensated — handles objects in motion properly
  - No extra Python dependencies

``minterpolate`` doubles the frame rate using motion vector estimation.
We then re-export at the original frame rate (dropping alternate frames is
not the goal — we want the interpolation to fill gaps and smooth motion).

Actually the correct use here is:
  1. Export at 2× frame rate (interpolated)
  2. This doubles temporal resolution → smoother motion

Or alternatively: keep original frame count but smooth frame transitions
using ``minterpolate`` in ``blend`` mode which blends consecutive frames.

We use the ``blend`` mode for shorter clips (< 200 frames) to avoid bloating
file sizes, and ``2× fps interpolation`` for longer clips.

Usage
-----
    from zyg_workflows import rife_service as rs
    updated_clips = rs.interpolate_clips(
        wan_clips,        # list[dict] — Stage 4.1 output
        out_dir,          # pipeline run output directory
        log_fn=lambda m: print(m),
    )
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from zyg_workflows import paths
from zyg_workflows.bin import exe
from typing import Callable


# ── Constants ─────────────────────────────────────────────────────────────────
_SHORT_CLIP_FRAMES = 200  # below this → blend mode; above → 2× interp
_OUTPUT_CRF = 18  # libx264 quality (lower = better)
_BLEND_FRAMES = 2  # minterpolate blur: blend across N frames

# RIFE neural interpolation (rife-ncnn-vulkan binary)
_RIFE_BINARY = os.path.expanduser('~/.local/bin/rife-ncnn-vulkan')
_RIFE_MODEL_DIR = str(paths.ZYG_MODELS_ROOT / 'rife-ncnn-vulkan' / 'rife-v4.6')

# minterpolate parameters (fallback when RIFE binary is unavailable)
# deflicker=mode=am:size=3 cleans up per-frame brightness flicker after interpolation
_MI_PARAMS_BLEND = 'minterpolate=fps={fps}:mi_mode=blend,deflicker=mode=am:size=3'
_MI_PARAMS_INTERP = 'minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,deflicker=mode=am:size=3'


# ── Public API ────────────────────────────────────────────────────────────────


def interpolate_clips(
    wan_clips: list[dict],
    out_dir: str,
    log_fn: Callable[[str], None] | None = None,
) -> list[dict]:
    """Run temporal interpolation on all WAN clips.

    Parameters
    ----------
    wan_clips : list[dict]
        Each entry must have a ``path`` key.  Entries without valid paths
        are passed through unchanged.
    out_dir : str
        Pipeline run output directory.
    log_fn : callable | None

    Returns
    -------
    list[dict]  Updated clips list.  ``path`` updated if interpolation
    succeeded.  ``rife_pass`` field added (``'2x_interp'`` or ``'blend'``).
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not wan_clips:
        _log('Stage 4.2: no clips — temporal repair skipped')
        return wan_clips

    _log(f'Stage 4.2: temporal interpolation on {len(wan_clips)} clip(s)')

    results: list[dict] = []
    for clip_meta in wan_clips:
        clip_path = clip_meta.get('path', '')
        if not clip_path or not os.path.exists(clip_path):
            results.append(clip_meta)
            continue

        out_path, method = _interpolate_one(clip_path, _log)
        updated = dict(clip_meta)
        if out_path and os.path.exists(out_path):
            updated['path'] = out_path
            updated['rife_pass'] = method
            _log(f'Stage 4.2: clip {clip_meta.get("index", "?")} → {os.path.basename(out_path)} ({method})')
        else:
            updated['rife_pass'] = 'skipped'  # noqa: S105  which RIFE pass ran, not a secret
        results.append(updated)

    _log('Stage 4.2: temporal repair complete')
    return results


# ── Per-clip interpolation ────────────────────────────────────────────────────


def _interpolate_one(
    clip_path: str,
    log_fn: Callable[[str], None],
) -> tuple[str | None, str]:
    """Try RIFE neural interpolation first, fall back to minterpolate."""
    # Try rife-ncnn-vulkan (neural, artifact-free)
    if os.path.exists(_RIFE_BINARY) and os.path.isdir(_RIFE_MODEL_DIR):
        log_fn(f'Stage 4.2: RIFE neural interpolation — {os.path.basename(clip_path)}')
        result, method = _interpolate_one_rife(clip_path, log_fn)
        if result and os.path.exists(result):
            log_fn(f'Stage 4.2: RIFE succeeded ({method}) — {os.path.basename(clip_path)}')
            return result, method
        log_fn(f'Stage 4.2: RIFE failed ({method}) — falling back to minterpolate')
    else:
        log_fn('Stage 4.2: RIFE binary/model not found — using minterpolate fallback')

    # FFmpeg minterpolate fallback
    return _interpolate_one_minterpolate(clip_path, log_fn)


def _interpolate_one_rife(
    clip_path: str,
    log_fn: Callable[[str], None],
) -> tuple[str | None, str]:
    """2× frame interpolation via rife-ncnn-vulkan (neural, no motion ghost artefacts)."""
    try:
        fps, n_frames = _probe_clip(clip_path)
        if fps <= 0:
            return None, 'rife_probe_failed'

        base = os.path.splitext(clip_path)[0]
        out_path = f'{base}_rife.mp4'

        with (
            tempfile.TemporaryDirectory(prefix='rife_in_') as frames_in,
            tempfile.TemporaryDirectory(prefix='rife_out_') as frames_out,
        ):
            # Extract frames
            extract_r = subprocess.run(
                [exe('ffmpeg'), '-y', '-i', clip_path, '-vf', f'fps={fps}', os.path.join(frames_in, '%08d.png')],
                capture_output=True,
                timeout=180,
            )
            if extract_r.returncode != 0:
                return None, 'rife_extract_failed'

            # Run RIFE: -n sets the *total* output frame count (not frames to insert).
            # Target = n_frames * 2 for 2× temporal resolution.
            _rife_target_frames = n_frames * 2
            rife_r = subprocess.run(
                [
                    _RIFE_BINARY,
                    '-i',
                    frames_in,
                    '-o',
                    frames_out,
                    '-m',
                    _RIFE_MODEL_DIR,
                    '-n',
                    str(_rife_target_frames),  # total output frames = 2× input
                    '-j',
                    '1:2:1',  # thread counts: decode/process/encode
                ],
                capture_output=True,
                timeout=600,
            )
            if rife_r.returncode != 0:
                err = rife_r.stderr.decode(errors='replace')[-300:]
                log_fn(f'Stage 4.2: rife-ncnn-vulkan error: {err}')
                return None, 'rife_exec_failed'

            # Encode interpolated frames back to video at 2× fps + deflicker
            new_fps = int(fps * 2)
            encode_r = subprocess.run(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-framerate',
                    str(new_fps),
                    '-i',
                    os.path.join(frames_out, '%08d.png'),
                    '-vf',
                    'deflicker=mode=am:size=3',
                    '-c:v',
                    'libx264',
                    '-preset',
                    'fast',
                    '-crf',
                    str(_OUTPUT_CRF),
                    '-pix_fmt',
                    'yuv420p',
                    '-an',
                    out_path,
                ],
                capture_output=True,
                timeout=300,
            )
            if encode_r.returncode != 0:
                return None, 'rife_encode_failed'

        return out_path, 'rife_2x_neural'

    except subprocess.TimeoutExpired:
        log_fn(f'Stage 4.2: RIFE timed out for {os.path.basename(clip_path)}')
        return None, 'rife_timeout'
    except Exception as e:
        log_fn(f'Stage 4.2: RIFE error — {e}')
        return None, 'rife_error'


def _interpolate_one_minterpolate(
    clip_path: str,
    log_fn: Callable[[str], None],
) -> tuple[str | None, str]:
    """FFmpeg minterpolate fallback with deflicker post-pass."""
    try:
        # Probe: get fps + frame count
        fps, n_frames = _probe_clip(clip_path)
        if fps <= 0:
            log_fn(f'Stage 4.2: could not probe {os.path.basename(clip_path)} — skipping')
            return None, 'skipped'

        base, ext = os.path.splitext(clip_path)
        out_path = f'{base}_rife.mp4'
        target_fps = fps

        if n_frames < _SHORT_CLIP_FRAMES:
            # Blend mode — smooth transitions without frame count change
            vf = _MI_PARAMS_BLEND.format(fps=int(fps))
            method = 'blend'
        else:
            # 2× interpolation — double temporal resolution
            target_fps = fps * 2
            vf = _MI_PARAMS_INTERP.format(fps=int(target_fps))
            method = '2x_interp'

        cmd = [
            exe('ffmpeg'),
            '-y',
            '-i',
            clip_path,
            '-vf',
            vf,
            '-r',
            str(int(target_fps)),
            '-c:v',
            'libx264',
            '-preset',
            'fast',
            '-crf',
            str(_OUTPUT_CRF),
            '-an',  # no audio — WAN clips are silent
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            err = result.stderr.decode(errors='replace')[-300:]
            log_fn(f'Stage 4.2: ffmpeg failed — {err}')
            return None, method

        return out_path, method

    except subprocess.TimeoutExpired:
        log_fn(f'Stage 4.2: ffmpeg timed out for {os.path.basename(clip_path)}')
        return None, 'timeout'
    except Exception as e:
        log_fn(f'Stage 4.2: interpolation error — {e}')
        return None, 'error'


# ── FFprobe helper ────────────────────────────────────────────────────────────


def _probe_clip(clip_path: str) -> tuple[float, int]:
    """Return (fps, frame_count) for *clip_path* using ffprobe."""
    try:
        probe_cmd = [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=r_frame_rate,nb_frames',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            clip_path,
        ]
        out = subprocess.check_output(probe_cmd, stderr=subprocess.DEVNULL, timeout=10)
        lines = out.decode().strip().splitlines()
        if len(lines) < 2:
            return 0.0, 0
        # r_frame_rate is like "17/1" or "30000/1001"
        r_str = lines[0].strip()
        if '/' in r_str:
            num, den = r_str.split('/')
            fps = float(num) / float(den)
        else:
            fps = float(r_str)
        n_frames = int(lines[1]) if lines[1].isdigit() else 0
        if n_frames == 0:
            # nb_frames not always available — estimate from duration
            dur_cmd = [
                exe('ffprobe'),
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                clip_path,
            ]
            dur_out = subprocess.check_output(dur_cmd, stderr=subprocess.DEVNULL, timeout=10)
            dur = float(dur_out.decode().strip() or '0')
            n_frames = int(dur * fps)
        return fps, n_frames
    except Exception:
        return 0.0, 0
