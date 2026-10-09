# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""color_grade.py — the cinematic LUT grade every video pipeline finishes on.

``_apply_color_grade`` and its LUT table were module-level in
``zyg_dashboard.crewai_web_gui`` until 2026-10-05, from-imported by
``pipeline_video`` and ``pipeline_scholarly`` — the base library importing the
application above it. Nothing here touches the GUI: it is an ffmpeg call over a
``.cube`` file, so it moved down whole and the dashboard imports it back.

The ``.cube`` files live in this package's own ``assets/luts/`` directory, which
is where they already were; ``_LUT_DIR`` resolves against this file instead of
against the dashboard module.
"""

import os

from zyg_workflows.encode_utils import _ffmpeg_run_nvenc_first

_LUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'luts')

_STYLE_LUT_MAP = {
    'cinematic': 'cinematic.cube',
    'filmic': 'filmic.cube',
    'anime': 'anime.cube',
    'disney': 'anime.cube',
    'art': 'cinematic.cube',
    'realism': 'documentary.cube',
    'scenery': 'documentary.cube',
    '3d_render': 'cinematic.cube',
    'mjv6': 'orange_teal.cube',
    'manga': 'anime.cube',
}
# documentary visual_style falls through to the documentary pipeline; for video
# pipeline with no explicit style, default to cinematic.
_DEFAULT_LUT = 'cinematic.cube'


def _apply_color_grade(
    clip_path: str, visual_style: str, pipeline_id: str, log_fn=None, crf: int = 0, extra_vf: str = ''
) -> str:
    """
    Apply a cinematic LUT + mild unsharp to *clip_path* using ffmpeg.

    Returns the path to the graded clip on success, or the original clip_path
    if the LUT file is missing or ffmpeg fails (safe fallback).

    crf=0  → lossless intermediate (use when a compression pass follows, e.g. per-clip in video pipeline)
    crf=18 → final-quality output (use when this is the last encode step, e.g. scholarly pipeline)

    extra_vf appends filters AFTER the grade — for effects that must be the last
    thing applied, such as film grain, which any subsequent re-encode destroys.
    Empty by default, so callers that don't pass it are unaffected.
    """
    lut_name = _STYLE_LUT_MAP.get(visual_style, _DEFAULT_LUT)
    lut_path = os.path.join(_LUT_DIR, lut_name)
    if not os.path.exists(lut_path):
        if log_fn:
            log_fn(f'Color grade: LUT not found ({lut_name}) — skipping')
        return clip_path

    graded = clip_path.replace('.mp4', '_graded.mp4')
    if graded == clip_path:
        graded = clip_path + '.graded.mp4'

    # lut3d applies the creative grade; unsharp adds mild detail recovery
    # (WAN output tends to be slightly soft — 5×5 kernel, 0.5 luma, 0.15 chroma)
    vf = f'lut3d={lut_path},unsharp=5:5:0.5:3:3:0.15'
    if extra_vf:
        vf += ',' + extra_vf

    _preset = 'ultrafast' if crf == 0 else 'fast'
    _encode_args = ['-c:v', 'libx264', '-preset', _preset, '-crf', str(crf), '-pix_fmt', 'yuv420p']
    _base = ['ffmpeg', '-y', '-i', clip_path, '-vf', vf, '-c:a', 'copy']
    r = _ffmpeg_run_nvenc_first(
        _base + _encode_args + [graded],
        _base + _encode_args + [graded],
        timeout=600,
        log_fn=log_fn,
        label='Color grade',
    )
    if r.returncode == 0 and os.path.exists(graded) and os.path.getsize(graded) > 10_000:
        return graded
    err = (r.stderr or b'').decode('utf-8', errors='replace')[-200:]
    if log_fn:
        log_fn(f'Color grade failed for {os.path.basename(clip_path)}: {err}')
    return clip_path
