#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Composite alpha VFX elements over footage from a *placement record*.

The placement record is the single source of truth: the draft the operator
approves and the final render read the SAME JSON, run the same maths, and
differ only in output resolution / fps / encoder preset.

Record shape::

    {
      "layers": [
        {
          "element": "<abs path to .mov | .webm | dir of RGBA PNGs>",
          "x": 0.62,                  # fraction of frame width
          "y": 0.50,                  # fraction of frame height
          "anchor": "bottom-center",  # | "center" | "top-left"
          "height": 0.10,             # element height / frame height, aspect kept
          "height_end": null,         # null = fixed size; else ramp to this
          "start_s": 0.0,
          "end_s": null,              # null = to the end of the base
          "element_offset_s": 0.0,    # seconds skipped at the head of the element
          "loop": true,
          "speed": 1.0,               # 1.0 = the element's own real-time speed
          "opacity": 1.0,
          "saturation": 1.0,          # 0 = grey, 1 = as shot, 2 = twice
          "blend": "normal",          # | "screen"
          "flip_h": false,
          "tint": [0.9, 0.7, 0.45],   # colorize by luma, optional; 0..1.6 each
          "warm": [1.0, 0.93, 0.80],  # per-channel multipliers, optional
          "blur": 0.0,                # gaussian sigma in output pixels
          "track": "none",            # | "horizon"
          "fps": 24                   # PNG-sequence elements only
        }
      ],
      "draft": {"width": 480, "fps": 12}
    }

Element fps is never assumed: video elements are read from the container,
PNG sequences from the layer's own ``fps`` key (default 24).

``tint`` is a COLORIZE, not a multiply: the element is reduced to its luma
(0.299R + 0.587G + 0.114B) and that single value is painted through the three
tint factors, so a grey dust element becomes sand-coloured whatever its own
hue was.  ``warm`` multiplies the channels it is given and therefore only
shifts a colour that is already there; ``tint`` replaces it.  Tint runs first,
alpha is never touched by either.

VP9/webm elements only carry their alpha through ffmpeg's *libvpx-vp9*
decoder -- the native vp9 decoder silently drops it and reports yuv420p --
so ``-c:v libvpx-vp9`` is placed before the corresponding ``-i``.

Licence: the bundled dust/tornado elements are CC0 (JangaFX).
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from fractions import Fraction

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

FFMPEG = shutil.which('ffmpeg') or 'ffmpeg'
FFPROBE = shutil.which('ffprobe') or 'ffprobe'

LAYER_DEFAULTS = {
    'x': 0.5,
    'y': 0.5,
    'anchor': 'bottom-center',
    'height': 0.25,
    'height_end': None,
    'start_s': 0.0,
    'end_s': None,
    'element_offset_s': 0.0,
    'loop': True,
    'speed': 1.0,
    'opacity': 1.0,
    'saturation': 1.0,
    'blend': 'normal',
    'flip_h': False,
    'tint': None,
    'warm': None,
    'blur': 0.0,
    'track': 'none',
    'fps': 24,
}

DRAFT_DEFAULTS = {'width': 480, 'fps': 12}

_SEQ_RE = re.compile(r'^(.*?)(\d+)\.png$', re.IGNORECASE)


# --------------------------------------------------------------------------
# probing
# --------------------------------------------------------------------------


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _probe_video(path):
    """Return {width,height,fps,duration,nb_frames,has_audio} for a media file.

    No decoder is forced: ffprobe rejects ``-c:v`` and geometry/rate/frame
    count are identical whichever vp9 decoder would be used.  Only ``pix_fmt``
    is unreliable for webm (the native decoder hides the alpha plane), and
    nothing here reads it.
    """
    cmd = [FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]
    out = _run(cmd)
    if out.returncode != 0:
        raise RuntimeError('ffprobe failed on %s: %s' % (path, out.stderr.strip()))
    data = json.loads(out.stdout)
    vs = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
    if not vs:
        raise RuntimeError('no video stream in %s' % path)
    v = vs[0]
    rate = Fraction(v.get('r_frame_rate') or '0/1')
    if rate == 0:
        rate = Fraction(v.get('avg_frame_rate') or '24/1')
    dur = v.get('duration') or data.get('format', {}).get('duration')
    try:
        dur = float(dur)
    except (TypeError, ValueError):
        dur = None
    try:
        nbf = int(v.get('nb_frames'))
    except (TypeError, ValueError):
        nbf = None
    if dur is None and nbf:
        dur = nbf / float(rate)
    return {
        'width': int(v['width']),
        'height': int(v['height']),
        'fps': rate,
        'duration': dur,
        'nb_frames': nbf,
        'has_audio': any(s.get('codec_type') == 'audio' for s in data.get('streams', [])),
        'pix_fmt': v.get('pix_fmt'),
    }


def _probe_png_dir(path, fps):
    """Return element facts for a directory of numbered RGBA PNGs."""
    pngs = sorted(glob.glob(os.path.join(path, '*.png')))
    if not pngs:
        raise RuntimeError('no PNGs in element dir %s' % path)
    m = _SEQ_RE.match(os.path.basename(pngs[0]))
    if not m:
        raise RuntimeError('PNGs in %s are not a numbered sequence' % path)
    stem, digits = m.group(1), m.group(2)
    pattern = os.path.join(path, '%s%%0%dd.png' % (stem, len(digits)))
    indices = []
    for p in pngs:
        mm = _SEQ_RE.match(os.path.basename(p))
        if mm and mm.group(1) == stem and len(mm.group(2)) == len(digits):
            indices.append(int(mm.group(2)))
    indices.sort()
    from PIL import Image  # local: PIL is only needed for sequence elements

    with Image.open(pngs[0]) as im:
        w, h = im.size
    return {
        'width': w,
        'height': h,
        'fps': Fraction(fps).limit_denominator(100000),
        'duration': len(indices) / float(fps),
        'nb_frames': len(indices),
        'pattern': pattern,
        'first_index': indices[0] if indices else 1,
        'has_audio': False,
    }


def _element_facts(path, layer_fps):
    """Element kind + geometry. kind in {'dir','webm','video'}."""
    if os.path.isdir(path):
        facts = _probe_png_dir(path, layer_fps)
        facts['kind'] = 'dir'
        return facts
    if not os.path.exists(path):
        raise RuntimeError('element not found: %s' % path)
    facts = _probe_video(path)
    facts['kind'] = 'webm' if path.lower().endswith('.webm') else 'video'
    return facts


# --------------------------------------------------------------------------
# horizon track
# --------------------------------------------------------------------------


def _horizon_track(video_in, log=None):
    """Per-frame 2D translation of the base, measured on a horizon band.

    Each frame's band (rows 0.35H..0.65H, downscaled to 320 px wide) is
    phase-correlated against frame 0's band, so the result is an *absolute*
    displacement relative to the first frame, in full-frame pixels.

    This is a 2D translation track only: it is meant for pinning a distant
    element (a dust plume on the skyline) under a pan or a slow drift.  It
    models no rotation, no zoom and no parallax, so it is wrong for anything
    close to camera.

    The sign is the content's own displacement -- pan the camera right and dx
    goes negative -- so an overlay locked to the scene sits at ``x + dx``.

    The band must be downscaled with INTER_AREA: the default bilinear resize
    aliases a 4x reduction badly enough to throw more than half the frames
    onto spurious correlation peaks.  Even so, the measurement needs real
    structure in the band; on high-frequency near-random texture the peak is
    unreliable at any filter setting.
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(video_in)
    if not cap.isOpened():
        raise RuntimeError('cv2 could not open %s' % video_in)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    ref = None
    win = None
    scale = 1.0
    track = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        band = cv2.cvtColor(frame[int(0.35 * h) : int(0.65 * h), :], cv2.COLOR_BGR2GRAY)
        sw = 320
        sh = max(8, int(round(band.shape[0] * sw / float(band.shape[1]))))
        g = cv2.resize(band, (sw, sh), interpolation=cv2.INTER_AREA).astype(np.float32)
        if ref is None:
            ref = g
            win = cv2.createHanningWindow((sw, sh), cv2.CV_32F)
            scale = w / float(sw)
            track.append((0.0, 0.0, 0.0))
        else:
            (dx, dy), _resp = cv2.phaseCorrelate(ref, g, win)
            track.append((idx / fps, dx * scale, dy * scale))
        idx += 1
    cap.release()
    if log:
        log('horizon track: %d frames, max |dx|=%.1f px' % (len(track), max([abs(t[1]) for t in track] or [0.0])))
    return track


# --------------------------------------------------------------------------
# placement maths
# --------------------------------------------------------------------------


def _anchor_xy(anchor, W, H, fx, fy, w, h):
    """Top-left pixel of the placed element for an anchor."""
    if anchor == 'top-left':
        return int(round(W * fx)), int(round(H * fy))
    if anchor == 'center':
        return int(round(W * fx - w / 2.0)), int(round(H * fy - h / 2.0))
    # default: bottom-center
    return int(round(W * fx - w / 2.0)), int(round(H * fy - h))


def _anchor_expr(anchor, fx, fy):
    """ffmpeg overlay x/y expressions matching _anchor_xy (W,H,w,h are overlay vars)."""
    if anchor == 'top-left':
        return 'W*%r' % fx, 'H*%r' % fy
    if anchor == 'center':
        return 'W*%r-w/2' % fx, 'H*%r-h/2' % fy
    return 'W*%r-w/2' % fx, 'H*%r-h' % fy


def _even(n):
    return int(round(n / 2.0)) * 2


def _esc(path):
    """Escape a path for use as a filter option value inside a filtergraph."""
    return path.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")


# --------------------------------------------------------------------------
# the compositor
# --------------------------------------------------------------------------


def composite(video_in, record, out_mp4, draft=False, log=None):
    """Burn every layer of ``record`` over ``video_in`` into ``out_mp4``.

    Returns a receipt dict.  ``draft=True`` renders the same placement at
    ``record['draft']['width']`` / ``['fps']`` with an ultrafast preset.
    """
    t0 = time.time()
    say = log if callable(log) else (lambda *_a, **_k: None)

    if isinstance(record, (str, bytes, os.PathLike)) and os.path.exists(record):
        with open(record, 'r', encoding='utf-8') as fh:
            record = json.load(fh)
    if not isinstance(record, dict):
        raise TypeError('record must be a dict or a path to a JSON file')

    base = _probe_video(video_in)
    draft_cfg = dict(DRAFT_DEFAULTS)
    draft_cfg.update(record.get('draft') or {})

    if draft:
        out_w = _even(int(draft_cfg['width']))
        out_h = _even(base['height'] * out_w / float(base['width']))
        tl_fps = Fraction(draft_cfg['fps']).limit_denominator(100000)
    else:
        out_w, out_h = base['width'], base['height']
        tl_fps = base['fps']
    tl_fps_f = float(tl_fps)
    duration = base['duration'] or 0.0

    layers = list(record.get('layers') or [])
    tracked = [i for i, L in enumerate(layers) if (L.get('track') or LAYER_DEFAULTS['track']) == 'horizon']

    track = _horizon_track(video_in, log=say) if tracked else None

    tmpdir = tempfile.mkdtemp(prefix='vov_')
    try:
        inputs = [['-i', video_in]]
        chains = []
        cmd_lines = {}  # t -> [command strings]
        receipt_layers = []

        # ---- base chain -------------------------------------------------
        base_chain = '[0:v]'
        if draft:
            base_chain += 'scale=%d:%d,' % (out_w, out_h)
        base_chain += 'fps=%s,format=rgba' % tl_fps
        if tracked:
            base_chain += ",sendcmd=f='%s'" % _esc(os.path.join(tmpdir, 'track.cmd'))
        base_chain += '[b0]'
        chains.append(base_chain)

        cur = 'b0'
        for i, raw in enumerate(layers):
            L = dict(LAYER_DEFAULTS)
            L.update({k: v for k, v in raw.items() if v is not None or k == 'end_s'})
            idx = i + 1
            elem = L['element']
            facts = _element_facts(elem, L['fps'])

            speed = float(L['speed']) or 1.0
            off = max(0.0, float(L['element_offset_s']))
            start_s = max(0.0, float(L['start_s']))
            end_s = duration if L.get('end_s') is None else float(L['end_s'])
            loop = bool(L['loop'])

            # ---- input args ---------------------------------------------
            args = []
            if facts['kind'] == 'webm':
                args += ['-c:v', 'libvpx-vp9']
            if facts['kind'] == 'dir':
                if loop:
                    args += ['-loop', '1']
                args += [
                    '-framerate',
                    str(facts['fps']),
                    '-start_number',
                    str(facts['first_index'] + int(round(off * float(facts['fps'])))),
                    '-i',
                    facts['pattern'],
                ]
            else:
                if loop:
                    args += ['-stream_loop', '-1']
                if off > 0:
                    args += ['-ss', '%.6f' % off]
                args += ['-i', elem]
            inputs.append(args)

            # ---- geometry -----------------------------------------------
            h_px = max(2, _even(out_h * float(L['height'])))
            w_px = max(2, _even(facts['width'] * h_px / float(facts['height'])))
            x_px, y_px = _anchor_xy(L['anchor'], out_w, out_h, float(L['x']), float(L['y']), w_px, h_px)
            # A height ramp needs a real window to ramp across.
            ramp_s = end_s - start_s
            ramp = L.get('height_end') is not None and ramp_s > 0
            h_px_end = max(2, _even(out_h * float(L['height_end']))) if ramp else h_px

            # ---- per-layer filter chain ---------------------------------
            f = ['format=rgba']
            if abs(speed - 1.0) > 1e-9:
                f.append('setpts=PTS/%r' % speed)
            f.append('fps=%s' % tl_fps)
            # These elements carry straight alpha with *undefined* RGB where
            # alpha is 0 (measured: it reaches 255), so a straight-alpha
            # downscale bleeds that garbage into the soft edges.  Scale the
            # premultiplied signal and undo it before the colour work.
            f.append('premultiply=inplace=1')
            f.append('scale=-2:%d' % max(h_px, h_px_end))
            f.append('unpremultiply=inplace=1')
            if L['flip_h']:
                f.append('hflip')
            sat = float(L['saturation'])
            if abs(sat - 1.0) > 1e-9:
                # Rec.709 luma, kept where it is and the colour difference
                # scaled around it.  Before the warm multiply, so "warm" still
                # means the same tint whatever the saturation.
                lr, lg, lb = 0.2126, 0.7152, 0.0722
                f.append(
                    'colorchannelmixer='
                    'rr=%r:rg=%r:rb=%r:gr=%r:gg=%r:gb=%r:br=%r:bg=%r:bb=%r'
                    % (
                        lr + sat * (1 - lr),
                        lg * (1 - sat),
                        lb * (1 - sat),
                        lr * (1 - sat),
                        lg + sat * (1 - lg),
                        lb * (1 - sat),
                        lr * (1 - sat),
                        lg * (1 - sat),
                        lb + sat * (1 - lb),
                    )
                )
            tint = L.get('tint')
            if tint:
                # Colorize by luma: every output channel is the SAME luma
                # value scaled by that channel's tint, so the element's own
                # hue is discarded.  Before warm/opacity, and aa is left
                # alone -- the alpha plane must survive a colorize.
                tr, tg, tb = (float(tint[0]), float(tint[1]), float(tint[2]))
                lr, lg, lb = 0.299, 0.587, 0.114
                f.append(
                    'colorchannelmixer='
                    'rr=%r:rg=%r:rb=%r:gr=%r:gg=%r:gb=%r:br=%r:bg=%r:bb=%r'
                    % (lr * tr, lg * tr, lb * tr, lr * tg, lg * tg, lb * tg, lr * tb, lg * tb, lb * tb)
                )
            warm = L['warm'] or [1.0, 1.0, 1.0]
            op = float(L['opacity'])
            if warm != [1.0, 1.0, 1.0] or abs(op - 1.0) > 1e-9:
                f.append(
                    'colorchannelmixer=rr=%r:gg=%r:bb=%r:aa=%r' % (float(warm[0]), float(warm[1]), float(warm[2]), op)
                )
            if float(L['blur']) > 0:
                f.append('gblur=sigma=%r' % float(L['blur']))

            use_screen = L['blend'] == 'screen'
            fits = 0 <= x_px and 0 <= y_px and x_px + w_px <= out_w and y_px + h_px <= out_h
            if use_screen and (not fits or ramp or idx in [t + 1 for t in tracked]):
                use_screen = False
                say(
                    'layer %d: screen blend needs a fixed-size element fully '
                    'inside an untracked frame - falling back to normal '
                    'overlay' % idx
                )

            enable = "enable='between(t,%r,%r)'" % (start_s, end_s)

            # A ramped layer is scaled twice: once premultiplied to the largest
            # size it will ever reach -- that is the pass that keeps the soft
            # edges clean -- and once more, per frame, down to the size this
            # frame wants.  The per-frame pass cannot be the premultiplied one:
            # unpremultiply does not reconfigure its link, so a scale=eval=frame
            # in front of it is silently cropped to the size of frame 0
            # (measured: a 0.1->0.3 ramp came out 0.82x instead of 2.5x).
            # overlay does reconfigure, so the ramp scale goes at the very end
            # of the chain -- after the start_s shift, hence timeline time --
            # and the anchor maths needs no help: overlay re-reads the overlaid
            # input's w/h every frame.
            tail = []
            if ramp:
                tail.append(
                    "scale=w='trunc(oh*a/2)*2':"
                    "h='trunc(max(2,%r+(%r)*clip((t-%r)/%r,0,1))/2)*2':eval=frame"
                    % (float(h_px), float(h_px_end - h_px), float(start_s), float(ramp_s))
                )

            if use_screen:
                f.append('pad=%d:%d:%d:%d:color=0x00000000' % (out_w, out_h, x_px, y_px))
                if start_s > 0:
                    f.append('setpts=PTS+%r/TB' % start_s)
                chains.append('[%d:v]%s[L%d]' % (idx, ','.join(f), idx))
                chains.append('[%s][L%d]blend@L%d=all_mode=screen:shortest=0:%s[b%d]' % (cur, idx, idx, enable, idx))
            else:
                if start_s > 0:
                    f.append('setpts=PTS+%r/TB' % start_s)
                f += tail
                chains.append('[%d:v]%s[L%d]' % (idx, ','.join(f), idx))
                xe, ye = _anchor_expr(L['anchor'], float(L['x']), float(L['y']))
                chains.append(
                    '[%s][L%d]overlay@L%d=x=%s:y=%s:format=auto:eof_action=pass:%s[b%d]'
                    % (cur, idx, idx, xe, ye, enable, idx)
                )
            cur = 'b%d' % idx

            # ---- sendcmd lines for a tracked layer ----------------------
            is_tracked = (i in tracked) and not use_screen
            if is_tracked and track:
                k = out_w / float(base['width'])
                for t, dx, dy in track:
                    cmd_lines.setdefault(round(t, 6), []).append('overlay@L%d x %.3f' % (idx, x_px + dx * k))
                    cmd_lines.setdefault(round(t, 6), []).append('overlay@L%d y %.3f' % (idx, y_px + dy * k))

            receipt_layers.append(
                {
                    'element': elem,
                    'placed_px': [x_px, y_px, w_px, h_px],
                    'height_px_end': h_px_end if ramp else None,
                    'visible': [start_s, end_s],
                    'tracked': bool(is_tracked),
                    'blend': 'screen' if use_screen else 'normal',
                    'element_fps': float(facts['fps']),
                }
            )

        if cmd_lines:
            with open(os.path.join(tmpdir, 'track.cmd'), 'w', encoding='utf-8') as fh:
                for t in sorted(cmd_lines):
                    fh.write('%.6f %s;\n' % (t, ', '.join(cmd_lines[t])))

        chains.append('[%s]format=yuv420p[vout]' % cur)
        graph = ';\n'.join(chains)
        gpath = os.path.join(tmpdir, 'graph.txt')
        with open(gpath, 'w', encoding='utf-8') as fh:
            fh.write(graph)
        say('filtergraph:\n%s' % graph)

        # ---- encode ------------------------------------------------------
        cmd = [FFMPEG, '-hide_banner', '-v', 'error', '-y']
        for a in inputs:
            cmd += a
        cmd += ['-filter_complex_script', gpath, '-map', '[vout]']
        if base['has_audio']:
            cmd += ['-map', '0:a', '-c:a', 'copy']
        else:
            cmd += ['-an']
        cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        cmd += ['-crf', '28', '-preset', 'ultrafast'] if draft else ['-crf', '14', '-preset', 'medium']
        # hard stop: looped elements are infinite streams
        cmd += ['-frames:v', str(int(math.ceil(duration * tl_fps_f)) + 2)]
        cmd += [out_mp4]

        proc = _run(cmd)
        if proc.returncode != 0:
            raise RuntimeError('ffmpeg failed:\n%s\n%s' % (' '.join(cmd), proc.stderr.strip()[-4000:]))

        got = _probe_video(out_mp4)
        receipt = {
            'width': got['width'],
            'height': got['height'],
            'fps': float(got['fps']),
            'frames': got['nb_frames'],
            'layers': receipt_layers,
            'seconds': round(time.time() - t0, 3),
            'draft': bool(draft),
            'out': os.path.abspath(out_mp4),
        }
        say('receipt: %s' % json.dumps(receipt))
        return receipt
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------

VFX = str(paths.ZYG_DATA_ROOT / 'asset_libraries' / 'vfx_volumes')
GRENADE_MOV = os.path.join(VFX, 'grenadedustimpactvdb_4k.mov')
GRENADE_WEBM = os.path.join(VFX, 'grenadedustimpactvdb_4k.webm')

# How much the placed box must change once the element is on screen.
# The grenade element is a grey dust plume over a 0x808080 base: its mean
# alpha over the whole placed box is 0.177 and its opaque core is close to
# mid-grey, so the mean absolute change peaks at ~6.3 and falls to 0.011 once
# the plume has dissipated.  8 (the value first proposed for this check) is
# above what the asset can produce; 5 sits far above the dissipated floor and
# the >8 case is instead covered by the exact numpy cross-check below.
MIN_BOX_DIFF = 5.0
# The render must match an independent numpy composite of the same element
# frame to within this fraction.  Measured agreement is ~0.6 %; the budget is
# for swscale-vs-INTER_AREA and a possible +/-1 element frame at the seek.
REF_TOL = 0.15


def _frame_at(video, t, png):
    p = _run([FFMPEG, '-hide_banner', '-v', 'error', '-y', '-ss', '%.3f' % t, '-i', video, '-frames:v', '1', png])
    if p.returncode != 0 or not os.path.exists(png):
        raise RuntimeError('frame extract failed at t=%s: %s' % (t, p.stderr.strip()))
    import numpy as np
    from PIL import Image

    with Image.open(png) as im:
        return np.asarray(im.convert('RGB')).astype('float32')


def _ref_box_diff(element, elem_t, box, base_level, warm, png):
    """Independent numpy composite of one element frame, for cross-checking.

    Decodes the element frame at ``elem_t`` straight from the source, resizes
    it premultiplied to the receipt's ``placed_px`` size, composites it over a
    flat ``base_level`` grey with ``warm``, and returns mean |result - base|.
    Nothing here goes through the filtergraph, so agreement with the rendered
    output proves the placement, the scale, the warm and the alpha maths.
    """
    import cv2
    import numpy as np
    from PIL import Image

    cmd = [FFMPEG, '-hide_banner', '-v', 'error', '-y']
    if element.lower().endswith('.webm'):
        cmd += ['-c:v', 'libvpx-vp9']
    cmd += ['-ss', '%.4f' % elem_t, '-i', element, '-frames:v', '1', '-pix_fmt', 'rgba', png]
    p = _run(cmd)
    if p.returncode != 0:
        raise RuntimeError('reference decode failed: %s' % p.stderr.strip())
    with Image.open(png) as im:
        a = np.asarray(im.convert('RGBA')).astype('float32')
    _x, _y, w, h = box
    al = a[..., 3:4] / 255.0
    pm = cv2.resize(a[..., :3] * al, (w, h), interpolation=cv2.INTER_AREA)
    als = cv2.resize(al[..., 0], (w, h), interpolation=cv2.INTER_AREA)[..., None]
    src = np.where(als > 0, pm / np.maximum(als, 1e-6), 0.0) * np.asarray(warm, 'float32')
    return float(np.abs((src - base_level) * als).mean())


# --------------------------------------------------------------------------


if __name__ == '__main__':  # the CLI lives in video_overlay_cli
    from zyg_workflows.video_overlay_cli import main as _cli_main

    raise SystemExit(_cli_main())
