#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio assembly leg: a shot list becomes one finished mp4.

This is the last stage of a Video Studio still/clip workflow.  It generates
nothing: every shot already exists as a clip on disk or as a still, and the
overlay / audio work is delegated to `video_overlay.composite` and
`video_audio.build_track` + `video_audio.mux`.  What lives here is the
timeline: conform, trim, speed ramps, stills, the xfade joins, the
top-and-tail fades and the final encode.

THE SHOT LIST
-------------
    {
      'fps': 24,
      'size': [1920, 1080],
      'shots': [
        {'path': 'a.mp4',
         'trim': [0, None],                 # seconds into the source; None = to its end
         'dive_zoom': {'zoom_end': 2.0,     # or None; applied BEFORE speed_ramp
                       'focus': [0.5, 0.78],
                       'ease': 'in-out',
                       'blur': True,
                       'start_s': 0.0},
         'speed_ramp': {'tail_s': 0.8,      # or None
                        'end_speed': 0.12},
         'overlay': <placement record dict or path to its json>,   # or None
         'overlay_draft': False,            # draft-resolution overlay for this shot
         'xfade_s': 0.18},                  # join to the shot on its RIGHT
        {'still': 'title.png', 'hold_s': 5.0, 'overlay': None},
        {'path': 'swirl.mp4'},
      ],
      'fade_in_s': 4.0,
      'fade_out_s': 3.0,
      'fade_color': 'black',
      'audio': <video_audio spec>,          # or None
    }

    receipt = assemble(shotlist, out_mp4)
    # {'total_s': ..., 'fade_in_s': ..., 'fade_out_s': ...,
    #  'shots': [{'src', 'dur_in', 'dur_out', 'ramp_added_frames', 'joined_at'}],
    #  'audio': <video_audio receipt or None>}

THE SPEED RAMP IS RESAMPLING, NOT setpts
----------------------------------------
`speed_ramp` slows the last `tail_s` *source* seconds of a shot by building a
new output-frame -> source-frame map: playback speed eases from 1.0 to
`end_speed` across the tail on a smoothstep, so the deceleration has no kink
at either end and the last source frame is naturally held for the last few
frames.  Because the tail plays slower, the tail yields MORE output frames
than it had source frames -- `ramp_added_frames` in the receipt is that
surplus, and it is what makes the shot (and the programme) longer than the
arithmetic of the trims.  `setpts` cannot do this: it would stretch the whole
clip by one constant factor and leave the fps of the result a lie.

THE DIVE ZOOM IS A CROP WINDOW, NOT A ZOOMPAN
---------------------------------------------
`dive_zoom` pushes the view in toward a focus point without touching the frame
count: every source frame yields exactly one output frame, cropped to
(W/z, H/z) and resized back to WxH.  The window is centred on the focus point
but CLAMPED inside the frame, so at z=1 it is the whole frame and the centre
can only drift toward the focus as the window shrinks -- which is what makes a
focus low in the frame read as a plunge toward the ground rather than a jump
cut.  `blur` adds a vertical smear over the lower part of the frame whose
length tracks dz/dt, so the fast middle of the ease reads as speed.  The
receipt's `s_measured` is the ORB + estimateAffinePartial2D scale between the
dive's first and last OUTPUT frame at 320 px wide: a deterministic check that
the push-in really happened.

THE XFADE OFFSET
----------------
Joins are a chain of `xfade=transition=fade`, one per gap.  Each join takes
its `duration` from the LEFT shot's `xfade_s`, and its `offset` is the
cumulative duration of everything joined so far MINUS that duration -- the
moment the right-hand shot starts contributing.  Every join therefore eats
`xfade_s` from the programme: total = sum(shot durations) - sum(xfade_s used).
An offset computed from the raw sum instead would place the transition past
the end of the left input and xfade would emit a frozen frame.

CLI
---
    python3 video_assembly.py --list shots.json --out final.mp4 [--draft]
    python3 video_assembly.py --selftest

Licence: this module only copies pixels that are already on disk.  Every
model that can feed it on this path (Wan2.2, Qwen-Image-2512,
Qwen-Image-Edit-2511, RealESRGAN, RIFE) is Apache-2.0/BSD and the bundled
dust elements are CC0 (JangaFX).
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import time

import cv2
import numpy as np

from zyg_workflows import provenance_seal as _seal
from zyg_workflows import video_audio
from zyg_workflows import video_overlay
from zyg_workflows.bin import exe
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


FFMPEG = exe('ffmpeg', required=False) or 'ffmpeg'  # resolve lazily: importing must not need ffmpeg
FFPROBE = shutil.which('ffprobe') or 'ffprobe'

SHOT_DEFAULTS = {
    'trim': None,
    'dive_zoom': None,
    'speed_ramp': None,
    'overlay': None,
    'overlay_draft': False,
    'xfade_s': 0.0,
    'hold_s': 5.0,
}

LIST_DEFAULTS = {
    'fps': 24,
    'size': [1920, 1080],
    'fade_in_s': 0.0,
    'fade_out_s': 0.0,
    'fade_color': 'black',
    'audio': None,
}


def _log_noop(msg):
    pass


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _ffmpeg(cmd, out_path, what, log):
    """Run ffmpeg and insist that it produced a non-empty `out_path`."""
    full = [FFMPEG, '-hide_banner', '-v', 'error', '-y'] + cmd
    log('ffmpeg %s: %s' % (what, ' '.join(full)))
    proc = _run(full)
    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
        raise RuntimeError('ffmpeg %s failed:\n%s\n%s' % (what, ' '.join(full), proc.stderr.strip()[-4000:]))
    return out_path


def _probe(path):
    """(width, height, fps, duration_s, nb_frames) of a video's first stream."""
    proc = _run(
        [FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-show_format', '-of', 'json', path]
    )
    if proc.returncode != 0:
        raise RuntimeError('ffprobe failed on %s:\n%s' % (path, proc.stderr.strip()[-2000:]))
    data = json.loads(proc.stdout or '{}')
    streams = data.get('streams') or []
    if not streams:
        raise RuntimeError('no video stream in %s' % path)
    st = streams[0]
    num, _, den = (st.get('avg_frame_rate') or '0/1').partition('/')
    fps = float(num) / float(den) if float(den or 0) else 0.0
    dur = st.get('duration') or (data.get('format') or {}).get('duration') or 0.0
    nb = int(st.get('nb_frames') or 0)
    dur = float(dur)
    if not nb and fps and dur:
        nb = int(round(dur * fps))
    if not dur and nb and fps:
        dur = nb / fps
    return int(st['width']), int(st['height']), fps, dur, nb


def _conform_chain(size, fps):
    """scale-to-fit + pad + square pixels + constant fps, as one filter chain."""
    w, h = int(size[0]), int(size[1])
    return (
        'scale=%d:%d:force_original_aspect_ratio=decrease:flags=bicubic,'
        'pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=%s' % (w, h, w, h, _fps_arg(fps))
    )


def _fps_arg(fps):
    return ('%d' % int(round(fps))) if abs(fps - round(fps)) < 1e-6 else ('%.6f' % fps)


def _x264(draft):
    if draft:
        return ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '26', '-preset', 'ultrafast']
    return ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '16', '-preset', 'medium']


def _conform_clip(src, out, size, fps, trim, draft, log):
    """Trim `src` and conform it to `size`/`fps`.  Returns `out`."""
    pre = []
    post = []
    if trim:
        start = float(trim[0] or 0.0)
        end = trim[1]
        if start > 0:
            pre += ['-ss', '%.6f' % start]
        if end is not None:
            post += ['-t', '%.6f' % max(0.0, float(end) - start)]
    cmd = pre + ['-i', src] + post + ['-vf', _conform_chain(size, fps), '-an'] + _x264(draft) + [out]
    return _ffmpeg(cmd, out, 'conform %s' % os.path.basename(src), log)


def _still_clip(img, out, size, fps, hold_s, draft, log):
    """`hold_s` seconds of `img` at `size`/`fps`.  Returns `out`."""
    cmd = (
        [
            '-loop',
            '1',
            '-framerate',
            _fps_arg(fps),
            '-i',
            img,
            '-t',
            '%.6f' % float(hold_s),
            '-vf',
            _conform_chain(size, fps),
            '-an',
        ]
        + _x264(draft)
        + [out]
    )
    return _ffmpeg(cmd, out, 'still %s' % os.path.basename(img), log)


def _smoothstep(p):
    p = 0.0 if p < 0.0 else (1.0 if p > 1.0 else p)
    return p * p * (3.0 - 2.0 * p)


def ramp_index_map(n_total, n_tail, end_speed):
    """Output-frame -> source-frame indices for a decelerating tail.

    The head passes through untouched; across the tail the playback speed
    eases 1.0 -> `end_speed` on a smoothstep of the progress through the
    SOURCE tail, so output frames accumulate until the source tail is spent.
    Monotonic non-decreasing, which is what lets the encoder stream the
    source once instead of buffering it.
    """
    n_tail = max(0, min(int(n_tail), int(n_total)))
    n_head = int(n_total) - n_tail
    idx = list(range(n_head))
    if n_tail <= 0:
        return idx
    end_speed = max(1e-3, float(end_speed))
    pos = 0.0  # frames consumed inside the tail
    guard = int(n_tail / end_speed) + n_tail + 16
    while pos < n_tail - 1e-9 and len(idx) - n_head < guard:
        src = n_head + int(pos)
        idx.append(min(src, int(n_total) - 1))
        pos += 1.0 + (end_speed - 1.0) * _smoothstep(pos / float(n_tail))
    return idx


def _speed_ramp(src, out, size, fps, tail_s, end_speed, draft, log):
    """Resample the last `tail_s` of `src`.  Returns (out, added_frames)."""
    w, h = int(size[0]), int(size[1])
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError('cv2 cannot open %s' % src)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n_total <= 0:
        n_total = _probe(src)[4]
    n_tail = min(n_total, int(round(float(tail_s) * fps)))
    idx = ramp_index_map(n_total, n_tail, end_speed)
    added = len(idx) - n_total
    log('ramp: %d source frames, tail %d -> %d output frames (+%d)' % (n_total, n_tail, len(idx), added))

    cmd = (
        [
            FFMPEG,
            '-hide_banner',
            '-v',
            'error',
            '-y',
            '-f',
            'rawvideo',
            '-pix_fmt',
            'bgr24',
            '-s',
            '%dx%d' % (w, h),
            '-framerate',
            _fps_arg(fps),
            '-i',
            '-',
            '-an',
        ]
        + _x264(draft)
        + [out]
    )
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    cur = -1
    frame = None
    try:
        for want in idx:
            while cur < want:
                ok, nxt = cap.read()
                if not ok:
                    break
                cur += 1
                frame = nxt
            if frame is None:
                raise RuntimeError('cv2 read nothing from %s' % src)
            if frame.shape[1] != w or frame.shape[0] != h:
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError) as _exc:
            _zyg_log.debug('ffmpeg stdin close skipped: %s', _exc)
        proc.stdout.read()
        err = proc.stderr.read()
        proc.wait()
    if proc.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 1024:
        raise RuntimeError(
            'ramp encode failed:\n%s\n%s' % (' '.join(cmd), (err or b'').decode('utf-8', 'replace')[-4000:])
        )
    return out, added


DIVE_DEFAULTS = {
    'zoom_end': 2.0,
    'focus': [0.5, 0.78],
    'ease': 'in-out',
    'blur': True,
    'start_s': 0.0,
}

_DIVE_BLUR_TOP = 0.30  # blur covers the lower 70 % of the frame
_DIVE_BLUR_SOFT = 0.12  # ...with this much of the height as a soft top edge


def _ease_at(u, ease):
    """Eased progress 0..1."""
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    if ease == 'linear':
        return u
    if ease == 'in':
        return u * u
    if ease == 'out':
        return 1.0 - (1.0 - u) * (1.0 - u)
    return _smoothstep(u)


def _ease_rate(u, ease):
    """d(ease)/du, normalised so its peak over 0..1 is 1.0."""
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    if ease == 'linear':
        return 1.0
    if ease == 'in':
        return u
    if ease == 'out':
        return 1.0 - u
    return 4.0 * u * (1.0 - u)  # 6u(1-u) / 1.5


def _dive_crop(frame, z, fx, fy, w, h):
    """Crop (W/z, H/z) around the focus point, clamped inside, resized to WxH."""
    z = max(1.0, float(z))
    cw = int(round(max(8.0, w / z)))
    ch = int(round(max(8.0, h / z)))
    cw, ch = min(cw, w), min(ch, h)
    if cw == w and ch == h:
        return frame
    x0 = int(round(min(max(fx * w - cw / 2.0, 0.0), w - cw)))
    y0 = int(round(min(max(fy * h - ch / 2.0, 0.0), h - ch)))
    win = frame[y0 : y0 + ch, x0 : x0 + cw]
    return cv2.resize(win, (w, h), interpolation=cv2.INTER_LANCZOS4)


def _dive_blur_alpha(h):
    """Column of weights: 0 above the soft edge, 1 over the lower 70 %."""
    top = _DIVE_BLUR_TOP * h
    soft = max(1.0, _DIVE_BLUR_SOFT * h)
    ys = np.arange(h, dtype=np.float32)
    a = (ys - (top - soft)) / soft
    np.clip(a, 0.0, 1.0, out=a)
    return a.reshape(h, 1, 1)


def _dive_blur(frame, k, alpha):
    """Vertical motion blur of length `k` px over the lower part of the frame."""
    k = int(k)
    if k < 3:
        return frame
    kern = np.full((k, 1), 1.0 / k, np.float32)
    smear = cv2.filter2D(frame, -1, kern, borderType=cv2.BORDER_REPLICATE)
    out = frame.astype(np.float32) * (1.0 - alpha) + smear.astype(np.float32) * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def orb_scale(frame_a, frame_b, width=320):
    """ORB + estimateAffinePartial2D scale taking `frame_a` onto `frame_b`.

    Both frames are reduced to `width` px first, so the estimate is cheap and
    -- ORB being deterministic -- repeatable.  Returns None when the pair
    cannot be matched.
    """

    def prep(img):
        sc = float(width) / float(img.shape[1])
        small = cv2.resize(img, (int(width), max(2, int(round(img.shape[0] * sc)))), interpolation=cv2.INTER_AREA)
        if small.ndim == 3:
            small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return small

    orb = cv2.ORB_create(nfeatures=4000)
    ka, da = orb.detectAndCompute(prep(frame_a), None)
    kb, db = orb.detectAndCompute(prep(frame_b), None)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    matches = sorted(matches, key=lambda m: m.distance)[:400]
    if len(matches) < 8:
        return None
    src = np.float32([ka[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    mat, _ = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0, maxIters=5000, confidence=0.995
    )
    if mat is None:
        return None
    return float(math.hypot(float(mat[0, 0]), float(mat[1, 0])))


def _dive_zoom(src, out, size, fps, opts, draft, log):
    """Push the view in toward a focus point.  Returns (out, info dict)."""
    w, h = int(size[0]), int(size[1])
    cfg = dict(DIVE_DEFAULTS)
    cfg.update(opts or {})
    zoom_end = max(1.0, float(cfg.get('zoom_end') or 1.0))
    focus = cfg.get('focus') or [0.5, 0.5]
    fx = min(max(float(focus[0]), 0.0), 1.0)
    fy = min(max(float(focus[1]), 0.0), 1.0)
    ease = str(cfg.get('ease') or 'in-out')
    want_blur = bool(cfg.get('blur', True))
    start_s = max(0.0, float(cfg.get('start_s') or 0.0))

    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError('cv2 cannot open %s' % src)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n_total <= 0:
        n_total = _probe(src)[4]
    i_start = min(max(0, int(round(start_s * fps))), max(0, n_total - 1))
    span = max(1, (n_total - 1) - i_start)
    alpha = _dive_blur_alpha(h)
    blur_scale = min(1.0, max(0.0, zoom_end - 1.0))
    log('dive: %d frames, zoom 1.0 -> %.3f from frame %d (%s)' % (n_total, zoom_end, i_start, ease))

    cmd = (
        [
            FFMPEG,
            '-hide_banner',
            '-v',
            'error',
            '-y',
            '-f',
            'rawvideo',
            '-pix_fmt',
            'bgr24',
            '-s',
            '%dx%d' % (w, h),
            '-framerate',
            _fps_arg(fps),
            '-i',
            '-',
            '-an',
        ]
        + _x264(draft)
        + [out]
    )
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    first_dive = last_dive = None
    n_written = n_dive = 0
    try:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[1] != w or frame.shape[0] != h:
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            if i >= i_start:
                u = (i - i_start) / float(span)
                z = 1.0 + (zoom_end - 1.0) * _ease_at(u, ease)
                frame = _dive_crop(frame, z, fx, fy, w, h)
                if want_blur:
                    k = int(round(3.0 + 12.0 * _ease_rate(u, ease) * blur_scale))
                    if k % 2 == 0:
                        k += 1
                    frame = _dive_blur(frame, min(15, max(3, k)), alpha)
                if first_dive is None:
                    first_dive = frame.copy()
                last_dive = frame
                n_dive += 1
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            n_written += 1
            i += 1
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError) as _exc:
            _zyg_log.debug('ffmpeg stdin close skipped: %s', _exc)
        proc.stdout.read()
        err = proc.stderr.read()
        proc.wait()
    if proc.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 1024:
        raise RuntimeError(
            'dive encode failed:\n%s\n%s' % (' '.join(cmd), (err or b'').decode('utf-8', 'replace')[-4000:])
        )
    if not n_written:
        raise RuntimeError('cv2 read nothing from %s' % src)

    s_measured = None
    if first_dive is not None and last_dive is not None and n_dive > 1:
        s_measured = orb_scale(first_dive, last_dive)
    info = {
        'zoom_end': round(zoom_end, 4),
        'frames': int(n_dive),
        's_measured': None if s_measured is None else round(s_measured, 4),
    }
    log('dive: %d output frames, s_measured %s' % (n_written, info['s_measured']))
    return out, info


def _load_record(overlay):
    if isinstance(overlay, str):
        with open(overlay, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    return overlay


def _join_and_fade(parts, durations, xfades, out, size, fps, fade_in_s, fade_out_s, fade_color, draft, log):
    """Chain-xfade `parts`, top and tail the result, encode to `out`.

    Returns (total_s, [start second of each part in the programme]).
    """
    starts = [0.0]
    chains = []
    cur = None
    acc = float(durations[0])
    for i in range(len(parts)):
        chains.append('[%d:v]settb=AVTB,setpts=PTS-STARTPTS,fps=%s,format=yuv420p[c%d]' % (i, _fps_arg(fps), i))
    cur = 'c0'
    for i in range(1, len(parts)):
        d = float(xfades[i - 1])
        d = max(0.0, min(d, durations[i - 1], durations[i]))
        offset = acc - d
        starts.append(offset)
        chains.append('[%s][c%d]xfade=transition=fade:duration=%.6f:offset=%.6f[x%d]' % (cur, i, d, offset, i))
        cur = 'x%d' % i
        acc = acc + float(durations[i]) - d
    total = acc

    tail = []
    if fade_in_s and fade_in_s > 0:
        tail.append('fade=t=in:st=0:d=%.6f:color=%s' % (float(fade_in_s), fade_color))
    if fade_out_s and fade_out_s > 0:
        tail.append(
            'fade=t=out:st=%.6f:d=%.6f:color=%s' % (max(0.0, total - float(fade_out_s)), float(fade_out_s), fade_color)
        )
    tail.append('format=yuv420p')
    chains.append('[%s]%s[vout]' % (cur, ','.join(tail)))

    graph = ';\n'.join(chains)
    tmpdir = os.path.dirname(os.path.abspath(out))
    gpath = os.path.join(tmpdir, 'join_graph.txt')
    with open(gpath, 'w', encoding='utf-8') as fh:
        fh.write(graph)
    log('join filtergraph:\n%s' % graph)

    cmd = []
    for part in parts:
        cmd += ['-i', part]
    cmd += ['-filter_complex_script', gpath, '-map', '[vout]', '-an']
    cmd += _x264(draft)
    cmd += ['-movflags', '+faststart', '-r', _fps_arg(fps), out]
    _ffmpeg(cmd, out, 'join', log)
    return total, starts


def assemble(shotlist, out_mp4, log=None, draft=False):
    """Build `out_mp4` from `shotlist`.  Returns the receipt dict."""
    log = log or _log_noop
    t0 = time.time()
    sl = dict(LIST_DEFAULTS)
    sl.update(shotlist or {})
    fps = float(sl['fps'])
    size = [int(sl['size'][0]), int(sl['size'][1])]
    shots = list(sl.get('shots') or [])
    if not shots:
        raise ValueError('shot list has no shots')
    out_mp4 = os.path.abspath(out_mp4)
    os.makedirs(os.path.dirname(out_mp4) or '.', exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix='video_assembly_', dir=video_audio._scratch())
    try:
        parts, durations, xfades, rows = [], [], [], []
        for i, raw in enumerate(shots):
            shot = dict(SHOT_DEFAULTS)
            shot.update(raw or {})
            stage = os.path.join(tmpdir, 'shot%02d.mp4' % i)
            if shot.get('still'):
                src = os.path.abspath(shot['still'])
                if not os.path.exists(src):
                    raise ValueError('shot %d: still not found: %s' % (i, src))
                _still_clip(src, stage, size, fps, shot.get('hold_s'), draft, log)
                dur_in = float(shot.get('hold_s'))
            else:
                src = os.path.abspath(shot['path'])
                if not os.path.exists(src):
                    raise ValueError('shot %d: clip not found: %s' % (i, src))
                _conform_clip(src, stage, size, fps, shot.get('trim'), draft, log)
                dur_in = _probe(stage)[3]

            dive_info = None
            dive = shot.get('dive_zoom')
            if dive:
                dived = os.path.join(tmpdir, 'shot%02d_dive.mp4' % i)
                _, dive_info = _dive_zoom(stage, dived, size, fps, dive, draft, log)
                stage = dived

            added = 0
            ramp = shot.get('speed_ramp')
            if ramp:
                ramped = os.path.join(tmpdir, 'shot%02d_ramp.mp4' % i)
                _, added = _speed_ramp(
                    stage,
                    ramped,
                    size,
                    fps,
                    float(ramp.get('tail_s') or 0.0),
                    float(ramp.get('end_speed') or 1.0),
                    draft,
                    log,
                )
                stage = ramped

            record = _load_record(shot.get('overlay'))
            if record:
                over = os.path.join(tmpdir, 'shot%02d_over.mp4' % i)
                video_overlay.composite(stage, record, over, draft=bool(draft or shot.get('overlay_draft')), log=log)
                stage = over

            n_out = _probe(stage)[4]
            dur_out = n_out / fps if n_out else _probe(stage)[3]
            parts.append(stage)
            durations.append(dur_out)
            xfades.append(float(shot.get('xfade_s') or 0.0))
            row = {
                'src': src,
                'dur_in': round(dur_in, 4),
                'dur_out': round(dur_out, 4),
                'ramp_added_frames': int(added),
                'joined_at': 0.0,
            }
            if dive_info is not None:
                row['dive_zoom'] = dive_info
            rows.append(row)
            log(
                'shot %d: %s  %.3fs in -> %.3fs out (+%d ramp frames)'
                % (i, os.path.basename(src), dur_in, dur_out, added)
            )

        joined = os.path.join(tmpdir, 'joined.mp4')
        total, starts = _join_and_fade(
            parts,
            durations,
            xfades,
            joined,
            size,
            fps,
            sl.get('fade_in_s'),
            sl.get('fade_out_s'),
            sl.get('fade_color') or 'black',
            draft,
            log,
        )
        for row, start in zip(rows, starts):
            row['joined_at'] = round(start, 4)

        audio_receipt = None
        spec = sl.get('audio')
        if spec:
            wav = os.path.join(tmpdir, 'track.wav')
            audio_receipt = video_audio.build_track(spec, total, wav, log=log)
            if not video_audio.mux(joined, wav, out_mp4, log=log):
                raise RuntimeError('audio mux produced nothing')
        else:
            shutil.move(joined, out_mp4)

        # The programme is the deliverable: seal it before anybody reads it.
        _seal.seal(out_mp4, pipeline='video_assembly', log_fn=log)

        got = _probe(out_mp4)
        receipt = {
            'total_s': round(got[3] or total, 4),
            'shots': rows,
            'fade_in_s': float(sl.get('fade_in_s') or 0.0),
            'fade_out_s': float(sl.get('fade_out_s') or 0.0),
            'audio': audio_receipt,
            'out': out_mp4,
            'fps': fps,
            'size': size,
            'draft': bool(draft),
            'seconds': round(time.time() - t0, 3),
        }
        log('receipt: %s' % json.dumps(receipt))
        return receipt
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------


def _frames(path):
    cap = cv2.VideoCapture(path)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            yield frame
    finally:
        cap.release()


def _luma(frame):
    b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    return float(np.mean(0.299 * r.astype(np.float64) + 0.587 * g.astype(np.float64) + 0.114 * b.astype(np.float64)))


if __name__ == '__main__':  # the CLI lives in video_assembly_cli
    from zyg_workflows.video_assembly_cli import main as _cli_main

    raise SystemExit(_cli_main())
