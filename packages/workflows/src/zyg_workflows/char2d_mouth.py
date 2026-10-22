# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char2d_mouth.py - flat 2D "pakupaku" mouth overlays and Rhubarb-driven talking clips.

Three drawn shapes only (closed / mid / open), rendered as FULL-FRAME RGBA overlays
anchored on the mouth position measured by the char2d view pass, so compositing is a
plain alpha-over of overlay onto view.

Timing comes from Rhubarb (extended shapes A-H plus X), is collapsed to the three
shapes and then quantised onto a 24 fps timeline in 6-frame windows, which caps the
mouth at 4 changes per second - the anime "pakupaku" cadence rather than per-phoneme
lipsync.

Measured on output/storyteller/scene_second_ledger_intro/line_01_abel.wav
(6.25 s, 38 Rhubarb cues, 150 frames): 8 changes = 1.28 changes/s, minimum hold
6 frames, longest hold 60 frames of 'mid'.  The theoretical ceiling of the
6-frame windowing is fps/min_hold = 4.0 changes/s; a worst-case cue list that
flips every frame is pinned at that ceiling in tests/test_char2d_mouth.py.
See output/char2d/_bench_mika/talk/timing.json.

CLI
    python char2d_mouth.py sprites VIEWS_JSON OUT_DIR
    python char2d_mouth.py timing  WAV OUT_JSON
    python char2d_mouth.py clip    VIEW_PNG MOUTH_DIR WAV OUT_MP4

Runs in the GUI venv (PIL + numpy). No bpy.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import logging as _zyg_logging

from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

SHAPES = ('closed', 'mid', 'open')

SS = 4  # supersampling factor; every shape is drawn at SSx and lanczos-downscaled

INK = (26, 20, 18, 255)  # the Freestyle-ink tone the views are drawn with
MOUTH_DARK = (86, 44, 44, 255)  # mid-shape fill
MOUTH_INNER = (128, 72, 68, 255)  # 1 px lighter inner tone
THROAT = (52, 25, 27, 255)  # open-shape throat
TOOTH = (250, 247, 242, 255)  # tooth band

RHUBARB = Path('data/tools/rhubarb/rhubarb')

# Rhubarb extended shape -> drawn shape
COLLAPSE_MAP = {
    'X': 'closed',
    'A': 'closed',
    'B': 'mid',
    'C': 'mid',
    'E': 'mid',
    'F': 'mid',
    'G': 'mid',
    'H': 'mid',
    'D': 'open',
}

# mouth width as a fraction of head height (head_top -> chin), measured on the
# front view of the bench character; used when a view's projected mouth_w_px has
# collapsed to ~0 (profiles).
MOUTH_W_HEAD_RATIO = 0.17


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #


def view_kind(yaw: float) -> str:
    """front | front45 | profile | back for a camera yaw in degrees."""
    a = float(yaw) % 360.0
    d = min(a, 360.0 - a)
    if d <= 20.0:
        return 'front'
    if d >= 160.0:
        return 'back'
    if d >= 70.0:
        return 'profile'
    return 'front45'


def _visible_dir(anchor: dict) -> int:
    """+1 if the face turns toward image-right, -1 toward image-left, 0 head-on."""
    dx = float(anchor['mouth_px'][0]) - float(anchor['head_top_px'][0])
    if abs(dx) < 1.0:
        return 0
    return 1 if dx > 0 else -1


def effective_mouth_w(anchor: dict) -> float:
    """The projected mouth width, falling back to a head-height estimate.

    profileL/profileR report mouth_w_px ~0.8 because the mouth is edge-on; the
    drawn wedge still needs a real scale, so derive it from the head height.
    """
    raw = float(anchor.get('mouth_w_px') or 0.0)
    head_h = abs(float(anchor['chin_px'][1]) - float(anchor['head_top_px'][1]))
    if raw >= 4.0:
        return raw
    return max(8.0, MOUTH_W_HEAD_RATIO * head_h)


def sample_skin(view_img: Image.Image, anchor_xy, above_px: int = 12) -> tuple:
    """Median opaque, non-ink pixel colour `above_px` above the mouth anchor."""
    arr = np.asarray(view_img.convert('RGBA'), dtype=np.int16)
    h, w = arr.shape[:2]
    cx = int(round(anchor_xy[0]))
    cy = int(round(anchor_xy[1])) - int(above_px)
    r = 5
    y0, y1 = max(0, cy - r), min(h, cy + r + 1)
    x0, x1 = max(0, cx - r), min(w, cx + r + 1)
    box = arr[y0:y1, x0:x1].reshape(-1, 4)
    lum = box[:, :3].mean(axis=1)
    keep = box[(box[:, 3] > 200) & (lum > 90)]
    if keep.size == 0:
        keep = box[box[:, 3] > 0]
    if keep.size == 0:
        return (222, 200, 184, 255)
    med = np.median(keep[:, :3], axis=0).astype(int)
    return (int(med[0]), int(med[1]), int(med[2]), 255)


# --------------------------------------------------------------------------- #
# sprite drawing
# --------------------------------------------------------------------------- #


def _shape_transform(kind: str, mw: float, vdir: int):
    """(x-scale, x-shift px, clip) for a view kind.

    front45: shift 12% of the mouth width toward the visible side and squash the
    width to 80%.  profile: a wedge 45% wide, pushed inward from the face edge and
    clipped to the interior half-plane.
    """
    if kind == 'front45':
        return 0.80, 0.12 * mw * vdir, None
    if kind == 'profile':
        # half-shapes straddling the silhouette: drawn on the anchor, the outer
        # half clipped away, so the flat edge lands exactly on the lip line.
        inward = -vdir if vdir else 1
        return 0.45, 0.0, ('ge' if inward > 0 else 'le')
    return 1.0, 0.0, None


def _draw_shape_local(shape: str, kind: str, mw: float, vdir: int, style: dict):
    """Draw one mouth shape supersampled into a square RGBA tile.

    Returns (tile, anchor_xy_in_tile) at 1:1 output scale.
    """
    ink = tuple(style.get('ink', INK))
    dark = tuple(style.get('dark', MOUTH_DARK))
    inner = tuple(style.get('inner', MOUTH_INNER))
    throat = tuple(style.get('throat', THROAT))
    tooth = tuple(style.get('tooth', TOOTH))

    xs, dx, clip = _shape_transform(kind, mw, vdir)

    side = max(48.0, 3.4 * mw)
    n = int(round(side * SS))
    c = n / 2.0
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))

    def ex(x: float) -> float:
        return c + (x * xs + dx) * SS

    def ey(y: float) -> float:
        return c + y * SS

    lw = max(1.6, 0.05 * mw)  # ink line width in output px

    if shape == 'closed':
        # a slightly curved dark line, ends lifted
        half = 0.45 * mw
        lift = 0.10 * mw
        th = max(2.0, 0.045 * mw)  # spec thickness, floored so it stays visible
        pts = []
        for i in range(25):
            u = -half + (2.0 * half) * i / 24.0
            pts.append((ex(u), ey(-lift * (u / half) ** 2)))
        ImageDraw.Draw(img).line(pts, fill=ink, width=int(round(th * SS)), joint='curve')

    elif shape == 'mid':
        w, h = 0.70 * mw, 0.35 * mw
        bb = [ex(-w / 2), ey(-h / 2), ex(w / 2), ey(h / 2)]
        d = ImageDraw.Draw(img)
        d.ellipse(bb, fill=dark, outline=ink, width=int(round(lw * SS)))
        # 1 px lighter inner tone along the lower inside edge
        ins = 1.0 * SS + lw * SS
        d.arc(
            [bb[0] + ins, bb[1] + ins, bb[2] - ins, bb[3] - ins],
            start=10,
            end=170,
            fill=inner,
            width=int(round(1.0 * SS)),
        )

    elif shape == 'open':
        w, h = 0.80 * mw, 0.70 * mw
        bb = [ex(-w / 2), ey(-h / 2), ex(w / 2), ey(h / 2)]
        mask = Image.new('L', (n, n), 0)
        ImageDraw.Draw(mask).ellipse(bb, fill=255)
        body = Image.new('RGBA', (n, n), dark)
        bd = ImageDraw.Draw(body)
        # darker throat, low and central
        bd.ellipse([ex(-w * 0.32), ey(-h * 0.02), ex(w * 0.32), ey(h * 0.58)], fill=throat)
        # thin white tooth band just below the top edge, where the arc is wide
        band = max(1.5, 0.11 * h)
        top = bb[1] + 0.10 * h * SS
        bd.rectangle([bb[0], top, bb[2], top + band * SS], fill=tooth)
        img.paste(body, (0, 0), mask)
        ImageDraw.Draw(img).ellipse(bb, outline=ink, width=int(round(lw * SS)))

    else:  # pragma: no cover - guarded by callers
        raise ValueError(f'unknown mouth shape {shape!r}')

    if clip is not None:
        cm = Image.new('L', (n, n), 0)
        edge = int(round(c))
        if clip == 'ge':
            ImageDraw.Draw(cm).rectangle([edge, 0, n, n], fill=255)
        else:
            ImageDraw.Draw(cm).rectangle([0, 0, edge, n], fill=255)
        img.putalpha(
            Image.fromarray(
                (np.asarray(img.split()[3], dtype=np.uint16) * np.asarray(cm, dtype=np.uint16) // 255).astype(np.uint8)
            )
        )

    out = img.resize((int(round(side)), int(round(side))), Image.LANCZOS)
    return out, (out.size[0] / 2.0, out.size[1] / 2.0)


def _skin_patch(size, anchor_xy, mw_raw: float, colour) -> Image.Image:
    """A feathered skin-coloured ellipse that hides the rendered 3D mouth line."""
    w, h = size
    pw = max(10.0, 1.65 * mw_raw)
    ph = max(7.0, 0.95 * mw_raw)
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).ellipse(
        [anchor_xy[0] - pw / 2, anchor_xy[1] - ph / 2, anchor_xy[0] + pw / 2, anchor_xy[1] + ph / 2], fill=255
    )
    mask = mask.filter(ImageFilter.GaussianBlur(2.4))
    patch = Image.new('RGBA', (w, h), tuple(colour)[:3] + (0,))
    patch.putalpha(mask)
    return patch


def draw_mouth_set(view_png, anchor: dict, out_dir, style: dict | None = None) -> dict:
    """Write <view>_closed.png / _mid.png / _open.png full-frame RGBA overlays.

    `anchor` is one entry of views.json (mouth_px, mouth_w_px, chin_px,
    head_top_px, yaw).  `style` may override ink/dark/inner/throat/tooth colours
    and 'skin' (otherwise sampled 12 px above the anchor).
    Back views get fully transparent overlays - no mouth is visible from behind.
    """
    style = dict(style or {})
    view_png = Path(view_png)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = view_png.stem

    view = Image.open(view_png).convert('RGBA')
    W, H = view.size
    kind = view_kind(anchor.get('yaw', 0.0))
    written = {}

    if kind == 'back':
        for s in SHAPES:
            p = out_dir / f'{name}_{s}.png'
            Image.new('RGBA', (W, H), (0, 0, 0, 0)).save(p)
            written[s] = str(p)
        return {'view': name, 'kind': kind, 'files': written, 'mouth_w': 0.0}

    ax, ay = float(anchor['mouth_px'][0]), float(anchor['mouth_px'][1])
    mw_raw = float(anchor.get('mouth_w_px') or 0.0)
    mw = effective_mouth_w(anchor)
    vdir = _visible_dir(anchor)
    skin = style.get('skin') or sample_skin(view, (ax, ay))
    silhouette = view.split()[3]

    # the rendered 3D lip line runs wider than the projected mouth width on the
    # 3/4 views, so the patch always uses the head-height estimate as a floor.
    head_h = abs(float(anchor['chin_px'][1]) - float(anchor['head_top_px'][1]))
    patch_ref = max(mw_raw, MOUTH_W_HEAD_RATIO * head_h)
    patch = _skin_patch((W, H), (ax, ay), patch_ref, skin)

    for s in SHAPES:
        tile, (tcx, tcy) = _draw_shape_local(s, kind, mw, vdir, style)
        overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        overlay.alpha_composite(patch)
        overlay.alpha_composite(tile, dest=(int(round(ax - tcx)), int(round(ay - tcy))))
        # never let a drawn mouth spill off the character silhouette
        overlay.putalpha(
            Image.fromarray(
                (
                    np.asarray(overlay.split()[3], dtype=np.uint16) * np.asarray(silhouette, dtype=np.uint16) // 255
                ).astype(np.uint8)
            )
        )
        p = out_dir / f'{name}_{s}.png'
        overlay.save(p)
        written[s] = str(p)

    return {'view': name, 'kind': kind, 'files': written, 'mouth_w': mw, 'skin': list(skin), 'visible_dir': vdir}


def draw_all_views(views_json, out_dir, style: dict | None = None) -> list:
    """Draw a mouth set for every view in a char2d views.json."""
    views_json = Path(views_json)
    doc = json.loads(views_json.read_text())
    root = views_json.parent
    out = []
    for _name, anchor in doc['views'].items():
        png = root / anchor['file']
        out.append(draw_mouth_set(png, anchor, out_dir, style))
    return out


# --------------------------------------------------------------------------- #
# timing
# --------------------------------------------------------------------------- #


def _to_16k_mono(wav) -> str:
    """Rhubarb wants 16 kHz mono s16; convert into a temp file and return it."""
    fd, tmp = tempfile.mkstemp(suffix='_16k.wav')  # mkstemp already honours $TMPDIR
    os.close(fd)
    subprocess.run(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-i',
            str(wav),
            '-ac',
            '1',
            '-ar',
            '16000',
            '-sample_fmt',
            's16',
            tmp,
        ],
        check=True,
    )
    return tmp


def rhubarb_timing(wav, rhubarb=None) -> list:
    """Run Rhubarb on `wav` and return [(t_start, t_end, shape), ...] (A-H, X)."""
    exe = Path(rhubarb or RHUBARB)
    if not exe.exists():
        raise FileNotFoundError(f'rhubarb not found at {exe}')
    src = _to_16k_mono(wav)
    fd, out = tempfile.mkstemp(suffix='_rhubarb.json')  # mkstemp already honours $TMPDIR
    os.close(fd)
    try:
        subprocess.run(
            [
                str(exe),
                '-f',
                'json',
                '--extendedShapes',
                'GHX',
                '-r',
                'pocketSphinx',
                '--machineReadable',
                '-o',
                out,
                src,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        doc = json.loads(Path(out).read_text())
    finally:
        for p in (src, out):
            try:
                os.unlink(p)
            except OSError as _exc:
                _zyg_log.debug('temporary rhubarb file removal skipped: %s', _exc)
    return [(float(c['start']), float(c['end']), str(c['value'])) for c in doc['mouthCues']]


def collapse(cues) -> list:
    """Map Rhubarb shapes onto closed/mid/open and merge neighbours that agree."""
    out = []
    for t0, t1, v in cues:
        shape = COLLAPSE_MAP.get(str(v).upper(), 'mid')
        if out and out[-1][2] == shape and abs(out[-1][1] - t0) < 1e-6:
            out[-1] = (out[-1][0], t1, shape)
        else:
            out.append((float(t0), float(t1), shape))
    return [tuple(c) for c in out]


def _frames_from_cues(cues, fps: int, n_frames: int, default='closed') -> list:
    """Sample a cue list at every frame centre."""
    frames = [default] * n_frames
    if not cues:
        return frames
    i = 0
    for f in range(n_frames):
        t = (f + 0.5) / fps
        while i + 1 < len(cues) and t >= cues[i][1]:
            i += 1
        t0, t1, s = cues[i]
        frames[f] = s if t0 <= t < t1 else (s if t >= t1 and i == len(cues) - 1 else default)
    return frames


def speech_frames(raw_cues, fps: int, n_frames: int) -> list:
    """Per-frame 'speech is ongoing' flags: any Rhubarb cue that is not X."""
    flags = [False] * n_frames
    for t0, t1, v in raw_cues:
        if str(v).upper() == 'X':
            continue
        f0 = int(math.floor(t0 * fps))
        f1 = int(math.ceil(t1 * fps))
        for f in range(max(0, f0), min(n_frames, f1)):
            flags[f] = True
    return flags


def _runs(frames) -> list:
    out = []
    for s in frames:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return out


def _split_closed_run(length: int, min_hold: int, cap: int) -> list:
    """Split a too-long closed hold into alternating closed/mid blocks.

    min_hold is hard; the `cap` is honoured whenever a split exists that keeps
    every block >= min_hold (it does not for 11..12 frames at 6/10).
    """
    lo = int(math.ceil(length / cap))
    hi = length // min_hold
    n = lo if lo <= hi else max(1, hi)
    if n <= 1:
        return [length]
    base, rem = divmod(length, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def quantise(
    cues, fps: int = 24, min_hold: int = 6, speech=None, duration: float | None = None, closed_cap: int = 10
) -> list:
    """Collapsed cues -> a per-frame shape list with runs of at least `min_hold`.

    The timeline is binned into `min_hold`-frame windows and each window takes
    the majority shape, which caps the change rate at fps/min_hold (4.0/s at
    24 fps / 6 frames).  A 'closed' hold longer than `closed_cap` frames while
    `speech` says the line is still running is reopened with alternating 'mid'.
    """
    if duration is None:
        duration = max((c[1] for c in cues), default=0.0)
    n_frames = max(1, int(math.ceil(duration * fps - 1e-9)))
    raw = _frames_from_cues(cues, fps, n_frames)

    # majority shape per window; ties go to the more open shape, then to the
    # window's first frame, so the result is deterministic.
    prio = {'closed': 0, 'mid': 1, 'open': 2}
    frames = []
    for start in range(0, n_frames, min_hold):
        win = raw[start : start + min_hold]
        best = max(SHAPES, key=lambda s: (win.count(s), prio[s]))
        frames.extend([best] * len(win))

    # a short trailing window would break min_hold - fold it into its neighbour
    runs = _runs(frames)
    if len(runs) > 1 and runs[-1][1] < min_hold:
        runs[-2][1] += runs[-1][1]
        runs.pop()

    if speech is not None:
        out_runs = []
        pos = 0
        for shape, length in runs:
            seg_speech = any(speech[pos : pos + length])
            if shape == 'closed' and length > closed_cap and seg_speech:
                for i, blk in enumerate(_split_closed_run(length, min_hold, closed_cap)):
                    out_runs.append(['closed' if i % 2 == 0 else 'mid', blk])
            else:
                out_runs.append([shape, length])
            pos += length
        runs = out_runs

    frames = []
    for shape, length in runs:
        frames.extend([shape] * length)
    return frames


def change_rate(frames, fps: int = 24) -> float:
    """Mouth shape changes per second."""
    if len(frames) < 2:
        return 0.0
    changes = sum(1 for a, b in zip(frames, frames[1:]) if a != b)
    return changes * fps / float(len(frames))


def min_run(frames) -> int:
    return min((n for _, n in _runs(frames)), default=0)


def build_timing(wav, fps: int = 24, min_hold: int = 6, rhubarb=None) -> dict:
    """Full timing document: raw cues, collapsed cues, quantised frames, rate."""
    raw = rhubarb_timing(wav, rhubarb=rhubarb)
    col = collapse(raw)
    duration = max((c[1] for c in raw), default=0.0)
    n_frames = max(1, int(math.ceil(duration * fps - 1e-9)))
    sp = speech_frames(raw, fps, n_frames)
    frames = quantise(col, fps=fps, min_hold=min_hold, speech=sp, duration=duration)
    rate = change_rate(frames, fps)
    return {
        'wav': str(wav),
        'fps': fps,
        'min_hold': min_hold,
        'duration_s': round(duration, 4),
        'n_frames': len(frames),
        'raw_cues': [{'start': t0, 'end': t1, 'value': v} for t0, t1, v in raw],
        'collapsed': [{'start': t0, 'end': t1, 'shape': s} for t0, t1, s in col],
        'frames': frames,
        'runs': [{'shape': s, 'frames': n} for s, n in _runs(frames)],
        'min_run_frames': min_run(frames),
        'changes': sum(1 for a, b in zip(frames, frames[1:]) if a != b),
        'changes_per_s': round(rate, 4),
    }


# --------------------------------------------------------------------------- #
# clip
# --------------------------------------------------------------------------- #


def render_talking_clip(
    view_png, mouth_set_dir, wav, out_mp4, fps: int = 24, timing: dict | None = None, background=(255, 255, 255)
):
    """Composite view + per-frame mouth overlay into an h264/AAC clip.

    Only three distinct frames exist, so they are composited once and the raw
    bytes replayed into ffmpeg at `fps`.
    """
    view_png, mouth_set_dir, out_mp4 = Path(view_png), Path(mouth_set_dir), Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    name = view_png.stem

    view = Image.open(view_png).convert('RGBA')
    W, H = view.size
    base = Image.new('RGBA', (W, H), tuple(background) + (255,))
    base.alpha_composite(view)

    plates = {}
    for s in SHAPES:
        p = mouth_set_dir / f'{name}_{s}.png'
        frame = base.copy()
        if p.exists():
            frame.alpha_composite(Image.open(p).convert('RGBA'))
        plates[s] = frame.convert('RGB').tobytes()

    if timing is None:
        timing = build_timing(wav, fps=fps)
    frames = timing['frames']

    cmd = [
        'ffmpeg',
        '-y',
        '-loglevel',
        'error',
        '-f',
        'rawvideo',
        '-pix_fmt',
        'rgb24',
        '-s',
        f'{W}x{H}',
        '-r',
        str(fps),
        '-i',
        '-',
        '-i',
        str(wav),
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '18',
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-b:a',
        '128k',
        '-shortest',
        str(out_mp4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for s in frames:
            proc.stdin.write(plates[s])
    finally:
        proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f'ffmpeg failed with exit {rc}')
    return {'out': str(out_mp4), 'frames': len(frames), 'fps': fps, 'changes_per_s': timing.get('changes_per_s')}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


if __name__ == '__main__':  # the CLI lives in char2d_mouth_cli
    from zyg_workflows.char2d_mouth_cli import main as _cli_main

    raise SystemExit(_cli_main())
