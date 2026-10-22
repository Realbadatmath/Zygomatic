# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio finishing passes: RIFE 2x interpolation and RealESRGAN upscale.

Two clip-level operations, both licence-clean (RIFE v4.6 + RealESRGAN are
Apache-2.0/BSD):

``rife_2x(src, dst, out_fps=None)``
    Doubles the temporal resolution with rife-ncnn-vulkan, then optionally
    conforms to a delivery frame rate.  Wan renders at 17 fps, RIFE makes 34,
    delivery is 24 — ``out_fps=24`` drops frames evenly to get there.

``esrgan_clip(src, dst, scale=2)``
    Upscales every frame through ComfyUI's ImageUpscaleWithModel in batches,
    then re-encodes at the source frame rate.  Frames go through the KJNodes
    folder loader in chunks so a long clip never loads whole into VRAM.

CLI::

    python video_finish.py --rife in.mp4 out.mp4 [--fps 24]
    python video_finish.py --esrgan in.mp4 out.mp4 [--scale 2]
    python video_finish.py --selftest
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Callable
from zyg_workflows import paths
from zyg_workflows.bin import exe

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# RIFE (same binary/model the Stage 4.2 service uses — see rife_service.py)
RIFE_BINARY = os.path.expanduser('~/.local/bin/rife-ncnn-vulkan')
RIFE_MODEL_DIR = str(paths.ZYG_MODELS_ROOT / 'rife-ncnn-vulkan' / 'rife-v4.6')

# RealESRGAN weights available to ComfyUI (BSD-3)
ESRGAN_MODELS = {2: 'RealESRGAN_x2.pth', 4: 'RealESRGAN_x4plus.pth'}

CRF = 12  # libx264 quality for both finishing passes
CHUNK_FRAMES = 33  # frames per ComfyUI batch — keeps VRAM flat on long clips

_TAIL = 2000  # chars of stderr kept in a RuntimeError


def _noop(_msg: str) -> None:
    pass


def _run(cmd: list[str], timeout: int, what: str) -> subprocess.CompletedProcess:
    """Run *cmd*; raise RuntimeError carrying the stderr tail when it fails."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'{what} timed out after {timeout}s: {" ".join(cmd[:4])}') from exc
    if r.returncode != 0:
        tail = r.stderr.decode(errors='replace')[-_TAIL:]
        raise RuntimeError(f'{what} failed (exit {r.returncode}):\n{tail}')
    return r


# ── ffprobe helpers ───────────────────────────────────────────────────────────


def probe(path: str) -> dict:
    """Return {'fps', 'frames', 'width', 'height', 'has_audio'} for *path*."""
    cmd = [
        exe('ffprobe'),
        '-v',
        'error',
        '-count_frames',
        '-select_streams',
        'v:0',
        '-show_entries',
        'stream=r_frame_rate,nb_read_frames,width,height',
        '-of',
        'json',
        path,
    ]
    out = _run(cmd, 300, 'ffprobe').stdout.decode(errors='replace')
    streams = json.loads(out).get('streams') or []
    if not streams:
        raise RuntimeError(f'ffprobe found no video stream in {path}')
    s = streams[0]
    r = str(s.get('r_frame_rate') or '0/1')
    num, _, den = r.partition('/')
    fps = float(num) / float(den or 1)
    frames = int(s.get('nb_read_frames') or 0)

    a = subprocess.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'a:0',
            '-show_entries',
            'stream=codec_type',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            path,
        ],
        capture_output=True,
        timeout=30,
    )
    has_audio = a.returncode == 0 and b'audio' in a.stdout

    return {
        'fps': fps,
        'frames': frames,
        'width': int(s.get('width') or 0),
        'height': int(s.get('height') or 0),
        'has_audio': has_audio,
    }


def _fps_str(fps: float) -> str:
    """Frame rate as an exact string ffmpeg accepts (no float drift)."""
    if abs(fps - round(fps)) < 1e-6:
        return str(int(round(fps)))
    return f'{fps:.6f}'


def _encode_frames(
    frames_dir: str, dst: str, in_fps: float, out_fps: float | None, audio_from: str | None, timeout: int
) -> None:
    """Encode ``frames_dir/%08d.png`` to *dst* at *in_fps*, conformed to *out_fps*."""
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or '.', exist_ok=True)
    cmd = [exe('ffmpeg'), '-y', '-framerate', _fps_str(in_fps), '-i', os.path.join(frames_dir, '%08d.png')]
    if audio_from:
        cmd += ['-i', audio_from]
    if out_fps:
        cmd += ['-vf', f'fps={_fps_str(out_fps)}']
    cmd += ['-c:v', 'libx264', '-preset', 'slow', '-crf', str(CRF), '-pix_fmt', 'yuv420p']
    if audio_from:
        cmd += ['-map', '0:v:0', '-map', '1:a:0', '-c:a', 'copy', '-shortest']
    else:
        cmd += ['-an']
    cmd += [dst]
    _run(cmd, timeout, 'ffmpeg encode')


# ── RIFE 2x ───────────────────────────────────────────────────────────────────


def rife_2x(src_mp4: str, dst_mp4: str, out_fps: float | None = None, log: Callable[[str], None] | None = None) -> dict:
    """Double *src_mp4*'s frame rate with RIFE, optionally conforming to *out_fps*.

    Returns a receipt: {'fps_in', 'fps_out', 'frames_in', 'frames_out', 'seconds'}.
    """
    log = log or _noop
    t0 = time.time()
    if not os.path.exists(src_mp4):
        raise RuntimeError(f'rife_2x: source not found — {src_mp4}')
    if not os.path.exists(RIFE_BINARY):
        raise RuntimeError(f'rife_2x: rife-ncnn-vulkan not found at {RIFE_BINARY}')
    if not os.path.isdir(RIFE_MODEL_DIR):
        raise RuntimeError(f'rife_2x: RIFE model dir not found at {RIFE_MODEL_DIR}')

    info = probe(src_mp4)
    fps_in, frames_in = info['fps'], info['frames']
    if fps_in <= 0 or frames_in <= 0:
        raise RuntimeError(f'rife_2x: bad probe for {src_mp4} — fps={fps_in} frames={frames_in}')

    fps_2x = fps_in * 2
    target = frames_in * 2
    log(f'rife_2x: {os.path.basename(src_mp4)} {frames_in}f @ {fps_in:g} → {target}f @ {fps_2x:g}')

    with (
        tempfile.TemporaryDirectory(prefix='vfin_rife_in_') as f_in,
        tempfile.TemporaryDirectory(prefix='vfin_rife_out_') as f_out,
    ):
        _run(
            [exe('ffmpeg'), '-y', '-i', src_mp4, '-vf', f'fps={_fps_str(fps_in)}', os.path.join(f_in, '%08d.png')],
            max(300, frames_in * 4),
            'ffmpeg frame extract',
        )

        # -n is the TOTAL output frame count, not the number of frames inserted.
        _run(
            [RIFE_BINARY, '-i', f_in, '-o', f_out, '-m', RIFE_MODEL_DIR, '-n', str(target), '-j', '1:2:1'],
            max(600, frames_in * 10),
            'rife-ncnn-vulkan',
        )

        made = len([n for n in os.listdir(f_out) if n.lower().endswith('.png')])
        if made < target:
            raise RuntimeError(f'rife_2x: RIFE produced {made} frames, expected {target}')

        _encode_frames(f_out, dst_mp4, fps_2x, out_fps, src_mp4 if info['has_audio'] else None, max(600, target * 4))

    if not os.path.exists(dst_mp4):
        raise RuntimeError(f'rife_2x: encode produced nothing at {dst_mp4}')
    done = probe(dst_mp4)
    receipt = {
        'fps_in': round(fps_in, 3),
        'fps_out': round(done['fps'], 3),
        'frames_in': frames_in,
        'frames_out': done['frames'],
        'seconds': round(time.time() - t0, 2),
    }
    log(f'rife_2x: wrote {dst_mp4} — {receipt}')
    return receipt


# ── RealESRGAN clip upscale ───────────────────────────────────────────────────


def _esrgan_graph(folder: str, width: int, height: int, cap: int, start: int, model_name: str, prefix: str) -> dict:
    """API-format graph: folder batch → ImageUpscaleWithModel → SaveImage."""
    return {
        '13': {
            'class_type': 'LoadImagesFromFolderKJ',
            'inputs': {
                'folder': os.path.abspath(folder),
                'width': int(width),
                'height': int(height),
                'keep_aspect_ratio': 'stretch',
                'image_load_cap': int(cap),
                'start_index': int(start),
            },
        },
        '11': {'class_type': 'UpscaleModelLoader', 'inputs': {'model_name': model_name}},
        '12': {'class_type': 'ImageUpscaleWithModel', 'inputs': {'upscale_model': ['11', 0], 'image': ['13', 0]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'filename_prefix': prefix, 'images': ['12', 0]}},
    }


def esrgan_clip(src_mp4: str, dst_mp4: str, scale: int = 2, log: Callable[[str], None] | None = None) -> dict:
    """Upscale every frame of *src_mp4* with RealESRGAN and re-encode to *dst_mp4*.

    Returns a receipt: {'w_in', 'h_in', 'w_out', 'h_out', 'frames', 'seconds'}.
    """
    log = log or _noop
    t0 = time.time()
    if not os.path.exists(src_mp4):
        raise RuntimeError(f'esrgan_clip: source not found — {src_mp4}')
    model_name = ESRGAN_MODELS.get(int(scale))
    if not model_name:
        raise RuntimeError(f'esrgan_clip: unsupported scale {scale} (have {sorted(ESRGAN_MODELS)})')

    from zyg_workflows import _comfy_client as _comfy

    if not _comfy.server_reachable():
        raise RuntimeError(f'esrgan_clip: ComfyUI is not reachable at {paths.ZYG_COMFY_URL}')

    info = probe(src_mp4)
    fps, frames_in = info['fps'], info['frames']
    w_in, h_in = info['width'], info['height']
    if fps <= 0 or frames_in <= 0 or w_in <= 0:
        raise RuntimeError(f'esrgan_clip: bad probe for {src_mp4} — {info}')

    token = uuid.uuid4().hex[:8]
    log(
        f'esrgan_clip: {os.path.basename(src_mp4)} {frames_in}f {w_in}x{h_in} '
        f'→ x{scale} ({model_name}) in chunks of {CHUNK_FRAMES}'
    )

    with (
        tempfile.TemporaryDirectory(prefix='vfin_esr_in_') as f_in,
        tempfile.TemporaryDirectory(prefix='vfin_esr_out_') as f_out,
    ):
        _run(
            [exe('ffmpeg'), '-y', '-i', src_mp4, '-vf', f'fps={_fps_str(fps)}', os.path.join(f_in, '%08d.png')],
            max(300, frames_in * 4),
            'ffmpeg frame extract',
        )

        n_src = len([n for n in os.listdir(f_in) if n.lower().endswith('.png')])
        if n_src == 0:
            raise RuntimeError(f'esrgan_clip: no frames extracted from {src_mp4}')

        written = 0
        for start in range(0, n_src, CHUNK_FRAMES):
            cap = min(CHUNK_FRAMES, n_src - start)
            graph = _esrgan_graph(
                f_in, w_in, h_in, cap, start, model_name, f'ZygVideoFinish_{token}_c{start // CHUNK_FRAMES:04d}'
            )
            try:
                outs = _comfy.submit(graph, timeout_s=max(300.0, cap * 30.0))
            except Exception as exc:
                raise RuntimeError(f'esrgan_clip: ComfyUI chunk at frame {start} failed — {exc}') from exc
            outs = sorted(p for p in outs if p.lower().endswith('.png'))
            if len(outs) != cap:
                raise RuntimeError(f'esrgan_clip: chunk at frame {start} returned {len(outs)} images, expected {cap}')
            for p in outs:
                written += 1
                shutil.copyfile(p, os.path.join(f_out, f'{written:08d}.png'))
            log(f'esrgan_clip: {written}/{n_src} frames upscaled')

        if written != n_src:
            raise RuntimeError(f'esrgan_clip: upscaled {written} frames, expected {n_src}')

        _encode_frames(f_out, dst_mp4, fps, None, src_mp4 if info['has_audio'] else None, max(600, written * 6))

    if not os.path.exists(dst_mp4):
        raise RuntimeError(f'esrgan_clip: encode produced nothing at {dst_mp4}')
    done = probe(dst_mp4)
    receipt = {
        'w_in': w_in,
        'h_in': h_in,
        'w_out': done['width'],
        'h_out': done['height'],
        'frames': done['frames'],
        'seconds': round(time.time() - t0, 2),
    }
    log(f'esrgan_clip: wrote {dst_mp4} — {receipt}')
    return receipt


# ── selftest ──────────────────────────────────────────────────────────────────


def _expect(label: str, got, want) -> None:
    if got != want:
        raise SystemExit(f'SELFTEST FAIL: {label} = {got!r}, expected {want!r}')
    _zyg_log.info(f'  ok  {label} = {got!r}')


if __name__ == '__main__':  # the CLI lives in video_finish_cli
    from zyg_workflows.video_finish_cli import main as _cli_main

    raise SystemExit(_cli_main())
