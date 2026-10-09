# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.remixai_analyze.frames — verbatim from remixai_analyze.py lines 175-334.

section 1 — frame sampling, ffprobe duration/geometry and the VLM
frame descriptions that become the visual style contract
"""

from __future__ import annotations

import base64
from zyg_workflows.bin import exe
import json
import os
import logging as _zyg_logging
from zyg_workflows.remixai_analyze import llm as _zyg_llm

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file remixai_analyze.py.
_llm = _zyg_llm._llm
_ollama_json = _zyg_llm._ollama_json
_run = _zyg_llm._run

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.remixai_analyze')


# ── 1. frames ───────────────────────────────────────────────────────────────


def sample_frames(video_path: str, out_dir: str, n: int = 8, log=None) -> list:
    """Sample n frames spread across the source, skipping the first and last 5%
    (intro cards and end screens describe the channel, not the content)."""
    os.makedirs(out_dir, exist_ok=True)
    dur = probe_duration(video_path)
    if dur <= 0:
        return []
    lo, hi = dur * 0.05, dur * 0.95
    step = (hi - lo) / max(1, n)
    frames = []
    for i in range(n):
        t = lo + step * (i + 0.5)
        fp = os.path.join(out_dir, f'src_frame_{i:02d}.jpg')
        rc, _o, _e = _run(
            [
                exe('ffmpeg'),
                '-y',
                '-ss',
                f'{t:.2f}',
                '-i',
                video_path,
                '-frames:v',
                '1',
                '-q:v',
                '3',
                '-vf',
                'scale=768:-2',
                fp,
            ],
            timeout=120,
        )
        if rc == 0 and os.path.isfile(fp):
            frames.append({'path': fp, 't': round(t, 2)})
    if log:
        log(f'sampled {len(frames)}/{n} frame(s)')
    return frames


def probe_duration(path: str) -> float:
    rc, out, _e = _run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-show_entries',
            'format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            path,
        ],
        timeout=60,
    )
    try:
        return float((out or '0').strip())
    except ValueError:
        return 0.0


def probe_video(path: str) -> dict:
    rc, out, _e = _run(
        [exe('ffprobe'), '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', path], timeout=60
    )
    try:
        info = json.loads(out)
    except Exception:
        return {}
    v = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    a = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), {})
    w, h = int(v.get('width') or 0), int(v.get('height') or 0)
    try:
        dur = float((info.get('format') or {}).get('duration') or 0)
    except (TypeError, ValueError):
        dur = 0.0
    fps = 30.0
    try:
        num, den = (v.get('r_frame_rate') or '30/1').split('/')
        fps = float(num) / max(1.0, float(den))
    except (AttributeError, TypeError, ValueError) as _exc:
        _zyg_log.debug('r_frame_rate unparsable, keeping fps 30.0: %s', _exc)
    return {
        'width': w,
        'height': h,
        'duration': dur,
        'fps': round(fps, 3),
        'aspect': round(w / h, 4) if (w and h) else 0.0,
        'has_audio': bool(a),
        'vcodec': v.get('codec_name', ''),
        'acodec': a.get('codec_name', ''),
    }


_FRAME_PROMPT = """You are describing one frame of a video so that a text-to-image
model can generate a NEW image with the same visual treatment.

Describe what you SEE, concretely:
- subject and action
- shot type (wide / medium / close-up) and camera angle
- lighting (direction, hardness, colour temperature)
- colour palette (name 3-4 dominant colours)
- setting and time of day
- overall aesthetic (photoreal / stylised / 3D render / painterly / anime / etc.)

Return JSON exactly:
{"subject": "...", "shot": "...", "lighting": "...", "palette": "...",
 "setting": "...", "aesthetic": "...", "prompt": "a single 40-60 word image
 generation prompt that would produce a frame with this treatment"}"""


def describe_frames(frames: list, log=None) -> list:
    """One VLM pass per frame → a generation-ready visual brief.

    Per THE CROP RULE (vlm_inspector): a VLM answers about what fills the frame.
    These are full frames because the question is about overall TREATMENT, not
    about a defect — the crop rule governs defect-finding, not style reading."""
    out = []
    for i, fr in enumerate(frames):
        try:
            with open(fr['path'], 'rb') as f:
                b64 = base64.b64encode(f.read()).decode()
        except OSError as _exc:
            _zyg_log.warning('frame %s unreadable, skipped: %s', fr['path'], _exc)
            continue
        res = _ollama_json(_FRAME_PROMPT, images=[b64], num_predict=700, stage='remixai-frame')
        if not res:
            continue
        res['t'] = fr['t']
        res['src_frame'] = fr['path']
        out.append(res)
        if log:
            log(f'frame {i + 1}/{len(frames)} @ {fr["t"]:.1f}s: {(res.get("subject") or "")[:60]}')
    return out


def visual_style_summary(descs: list, log=None) -> dict:
    """Fuse the per-frame briefs into ONE style contract every generated image
    obeys, so the output reads as a single piece rather than N unrelated stills."""
    if not descs:
        return {}
    payload = json.dumps(
        [{k: d.get(k, '') for k in ('aesthetic', 'lighting', 'palette', 'setting', 'shot')} for d in descs],
        ensure_ascii=False,
    )[:4000]
    prompt = (
        'These are per-frame visual descriptions from one video.\n'
        f'{payload}\n\n'
        'Identify the CONSISTENT visual treatment across them.\n'
        'Return JSON exactly:\n'
        '{"aesthetic": "...", "lighting": "...", "palette": "...",\n'
        ' "camera": "...", "style_suffix": "a 25-40 word clause to append to every\n'
        ' image prompt so all images share this treatment"}'
    )
    res, src = _llm(prompt, num_predict=600, stage='remixai-style')
    if log and res:
        log(f'style contract ({src}): {(res.get("aesthetic") or "")[:70]}')
    return res or {}
