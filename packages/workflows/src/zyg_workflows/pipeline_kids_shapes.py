# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_shapes.py — "Shapes Parade", the shape-naming series.

One big friendly shape at a time marches across the screen to a drum beat,
the voice names it when it reaches the middle, it hops once and marches off.
Ten shapes in a fixed table, six of them per episode.

WHY THERE IS NO IMAGE MODEL HERE.  Every other series in this family asks
FLUX for a picture.  A circle does not need one: a circle drawn with PIL is
exactly a circle, every frame, forever, and the toddler this is for is being
taught the *name of that shape*.  A diffusion model would give a different
circle each frame, which is the one thing this series must not do.  So the
pictures are arithmetic — ``gpu: False``, zero VRAM, zero seconds of model
load — and the whole per-episode cost is the one spoken word per shape.

The drums are not decoration either.  There is no soundfont bed in this
series: the march IS the music, built from CC0 one-shots placed on a 120 bpm
grid, so the beat the shape walks to and the beat you hear are the same
arithmetic and cannot drift apart.

Contract, tables and motion are all in this file; everything that touches a
codec, the voice worker or the job registry is in kids_series_common.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from zyg_workflows import kids_series_common as ks

# ── the contract ─────────────────────────────────────────────────────────────

SERIES = {
    'slug': 'shapes',
    'title': 'Shapes Parade',
    'tagline': 'Big friendly shapes march past, one name at a time.',
    'voice': True,
    'characters': False,
    'gpu': False,
    'age_band': 'toddler',
    'episode_seconds': 60,
    # (k-1)*2 mod 10 over a ten-row table repeats after five, so five episodes
    # is the honest count: episode 6 would be episode 1 again.
    'episodes': 5,
    'agents': {
        'Episode Plan': 'shape table',
        'Draw the Parade': 'PIL frame renderer',
        'Say the Shapes': 'IndexTTS-2 / Chatterbox',
        'Drums': 'CC0 drum one-shots',
        'Assemble & Deliver': 'ffmpeg',
    },
}

STAGES = ['Episode Plan', 'Draw the Parade', 'Say the Shapes', 'Drums', 'Assemble & Deliver']

# ── the picture ──────────────────────────────────────────────────────────────

W, H, FPS = ks.W, ks.H, ks.FPS

UNIT_SECONDS = 10.0  # one shape: march in, be named, hop, march off
SHAPES_PER_EPISODE = 6  # 6 x 10 s = SERIES['episode_seconds']
SHAPE_PX = 260  # the nominal size every draw function works to
SPRITE = 460  # the transparent square a shape is drawn into,
# big enough that a +-6 deg rotation cannot clip
_INK = (34, 34, 40)
_GROUND = (126, 214, 96)

X_FROM, X_TO = -300.0, 1580.0  # off the left edge to off the right edge
Y_BASE = 420.0  # the shape's centre when both feet are down
BOB_PX = 22.0  # how far the march lifts it
BOB_HZ = 2.0  # two steps a second
TILT_DEG = 6.0
HOP_PX = 90.0
HOP_AT = UNIT_SECONDS / 2.0  # t=5 s, which is also where x lands on 640
HOP_LEN = 0.5
SAY_AT = 5.2  # the voice arrives just after the hop starts

BPM = 120.0
BEAT = 60.0 / BPM  # 0.5 s
BAR = BEAT * 4  # 2 s
DRUM_FAMILY = 'virtuosity_drums'
VOICE = 'f06_young_light'


def _lighten(col, f=0.42):
    return tuple(int(c + (255 - c) * f) for c in col)


# Every draw function takes the whole RGBA sprite and the sprite's own
# centre: two of the ten shapes are silhouettes rather than strokes and need
# the alpha channel, and one signature for all ten keeps the table honest.
# Nothing below knows where on the screen the shape is — that is the paste.


def _d_circle(layer, cx, cy, s, col):
    r = s / 2
    ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=_INK, width=7)


def _d_square(layer, cx, cy, s, col):
    r = s / 2
    ImageDraw.Draw(layer).rounded_rectangle(
        [cx - r, cy - r, cx + r, cy + r], radius=s * 0.06, fill=col, outline=_INK, width=7
    )


def _d_triangle(layer, cx, cy, s, col):
    _polygon(layer, cx, cy, s / 2, 3, col, rotate=-90.0)


def _d_star(layer, cx, cy, s, col):
    # The five-point construction from kids_video_service._draw_star: ten
    # vertices, every other one pulled in to 0.44 of the radius.
    r = s / 2
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rad = r if k % 2 == 0 else r * 0.44
        pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=col)
    d.line(pts + [pts[0]], fill=_INK, width=7, joint='curve')


def _d_heart(layer, cx, cy, s, col):
    """Two lobes and a point, outlined from the SILHOUETTE, not per piece.

    Stroking the three primitives individually draws the seams where they
    overlap — two arcs straight through the middle of the heart.  So the
    pieces are merged into one mask first and the ink comes from the edge of
    that mask (grown minus shrunk), which by construction has no inside.
    """
    r = s * 0.32
    top = cy - s * 0.13
    mask = Image.new('L', layer.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([cx - r * 1.05, top - r, cx + r * 0.05, top + r], fill=255)
    md.ellipse([cx - r * 0.05, top - r, cx + r * 1.05, top + r], fill=255)
    md.polygon([(cx - r * 1.03, top + r * 0.08), (cx + r * 1.03, top + r * 0.08), (cx, cy + s * 0.42)], fill=255)
    _fill_and_ink(layer, mask, col)


def _fill_and_ink(layer, mask, col):
    """Paint a silhouette and ring it in ink, both through one mask."""
    ring = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(9)), mask.filter(ImageFilter.MinFilter(7)))
    layer.paste(tuple(col) + (255,), (0, 0), mask)
    layer.paste(_INK + (255,), (0, 0), ring)


def _d_rectangle(layer, cx, cy, s, col):
    w, h = s / 2, s / 4  # 2:1
    ImageDraw.Draw(layer).rounded_rectangle(
        [cx - w, cy - h, cx + w, cy + h], radius=s * 0.05, fill=col, outline=_INK, width=7
    )


def _d_oval(layer, cx, cy, s, col):
    w, h = s / 2, s / 2 / 1.6  # 1.6:1
    ImageDraw.Draw(layer).ellipse([cx - w, cy - h, cx + w, cy + h], fill=col, outline=_INK, width=7)


def _d_diamond(layer, cx, cy, s, col):
    _polygon(layer, cx, cy, s / 2, 4, col, rotate=-90.0)


def _d_hexagon(layer, cx, cy, s, col):
    _polygon(layer, cx, cy, s / 2, 6, col, rotate=-90.0)


def _polygon(layer, cx, cy, r, n, col, rotate=0.0):
    a0 = math.radians(rotate)
    pts = [(cx + math.cos(a0 + k * 2 * math.pi / n) * r, cy + math.sin(a0 + k * 2 * math.pi / n) * r) for k in range(n)]
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=col)
    d.line(pts + [pts[0]], fill=_INK, width=7, joint='curve')


def _d_crescent(layer, cx, cy, s, col):
    """A circle with a smaller circle taken OUT of it — alpha, not paint.

    Painting the bite in the background colour would work only until the
    shape walked over the horizon line, so the bite is punched out of the
    sprite's alpha and the inner rim is drawn on a separate layer clipped to
    the disc.
    """
    r = s / 2
    bite_r = r * 0.86
    bx = cx + r * 0.52
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=_INK, width=7)

    punch = Image.new('L', layer.size, 0)
    ImageDraw.Draw(punch).ellipse([bx - bite_r, cy - bite_r, bx + bite_r, cy + bite_r], fill=255)
    layer.putalpha(ImageChops.subtract(layer.getchannel('A'), punch))

    rim = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(rim).ellipse([bx - bite_r, cy - bite_r, bx + bite_r, cy + bite_r], outline=_INK, width=7)
    disc = Image.new('L', layer.size, 0)
    ImageDraw.Draw(disc).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    rim.putalpha(ImageChops.multiply(rim.getchannel('A'), disc))
    layer.alpha_composite(rim)


# THE TABLE.  Ten rows, fixed, no generator anywhere near it — this is the
# whole content of the series and it is reviewable at a glance.
# fx/fy nudge the face onto the thick part of the shape; fs scales it down
# where the shape is short (a rectangle cannot hold a full-size smile).
SHAPES = [
    {'name': 'circle', 'draw': _d_circle, 'colour': (230, 57, 70), 'fx': 0.00, 'fy': -0.02, 'fs': 1.00},
    {'name': 'square', 'draw': _d_square, 'colour': (69, 123, 157), 'fx': 0.00, 'fy': -0.02, 'fs': 1.00},
    # The triangle's face sits barely below centre and small: any lower and
    # the smile crosses the base, which reads as a crack, not a mouth.
    {'name': 'triangle', 'draw': _d_triangle, 'colour': (255, 209, 102), 'fx': 0.00, 'fy': 0.02, 'fs': 0.78},
    {'name': 'star', 'draw': _d_star, 'colour': (255, 140, 66), 'fx': 0.00, 'fy': 0.02, 'fs': 0.74},
    {'name': 'heart', 'draw': _d_heart, 'colour': (255, 143, 177), 'fx': 0.00, 'fy': -0.04, 'fs': 0.92},
    {'name': 'rectangle', 'draw': _d_rectangle, 'colour': (106, 199, 126), 'fx': 0.00, 'fy': 0.00, 'fs': 0.62},
    {'name': 'oval', 'draw': _d_oval, 'colour': (155, 93, 229), 'fx': 0.00, 'fy': 0.00, 'fs': 0.80},
    {'name': 'diamond', 'draw': _d_diamond, 'colour': (80, 200, 220), 'fx': 0.00, 'fy': 0.02, 'fs': 0.78},
    {'name': 'hexagon', 'draw': _d_hexagon, 'colour': (150, 105, 70), 'fx': 0.00, 'fy': 0.00, 'fs': 0.92},
    {'name': 'crescent', 'draw': _d_crescent, 'colour': (255, 240, 150), 'fx': -0.20, 'fy': 0.00, 'fs': 0.72},
]


def _face(d, cx, cy, s):
    """Two dot eyes with a highlight, and an arc for a smile."""
    e = s * 0.055
    dx = s * 0.125
    ey = cy - s * 0.070
    for sx in (-1, 1):
        ex = cx + sx * dx
        d.ellipse([ex - e, ey - e, ex + e, ey + e], fill=_INK)
        hr = e * 0.34
        hx, hy = ex - e * 0.30, ey - e * 0.34
        d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255))
    d.arc(
        [cx - s * 0.17, cy - s * 0.01, cx + s * 0.17, cy + s * 0.20], 20, 160, fill=_INK, width=max(4, int(s * 0.030))
    )


def _sprite(shape):
    """One shape + its face, drawn once into a transparent square.

    Drawn once per unit and then only rotated and pasted: a 240-frame march
    that redrew the polygon every frame would be doing the same arithmetic
    240 times for an identical result.
    """
    img = Image.new('RGBA', (SPRITE, SPRITE), (0, 0, 0, 0))
    c = SPRITE / 2.0
    shape['draw'](img, c, c, SHAPE_PX, shape['colour'])
    _face(ImageDraw.Draw(img), c + shape['fx'] * SHAPE_PX, c + shape['fy'] * SHAPE_PX, SHAPE_PX * shape['fs'])
    return img


def _background():
    """Sky gradient, ground band, horizon line — kids_video_service._sky.

    Copied rather than imported, for the reason kids_series_common gives for
    copying KID_STYLE: that module resolves a checkpoint at import time and
    this series must stay a CPU-only, GPU-free import.
    """
    img = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    gy = int(H * 0.72)
    for y in range(gy):
        f = y / max(1.0, gy)
        d.line([(0, y), (W, y)], fill=(int(170 + 66 * f), int(220 + 28 * f), int(255 - 8 * f)))
    d.rectangle([0, gy, W, H], fill=_GROUND)
    d.line([(0, gy), (W, gy)], fill=_INK, width=5)
    return img


def _pose(t):
    """(x, y, tilt) of the shape centre at t seconds into the unit."""
    f = min(1.0, max(0.0, t / UNIT_SECONDS))
    x = X_FROM + (X_TO - X_FROM) * f
    swing = math.sin(2 * math.pi * BOB_HZ * t)
    y = Y_BASE - BOB_PX * abs(swing)
    if HOP_AT <= t <= HOP_AT + HOP_LEN:
        y -= HOP_PX * math.sin(math.pi * (t - HOP_AT) / HOP_LEN)
    return x, y, TILT_DEG * swing


def _render_unit(shape, frames_dir, still_png, log, should_abort):
    """One shape's ten seconds, as frames/NNNN.png."""
    os.makedirs(frames_dir, exist_ok=True)
    base = _background()
    sprite = _sprite(shape)
    n = int(round(UNIT_SECONDS * FPS))
    mid = int(round(HOP_AT * FPS))
    for i in range(n):
        if should_abort and i % FPS == 0 and should_abort():
            return 0
        x, y, tilt = _pose(i / float(FPS))
        rot = sprite.rotate(tilt, resample=Image.BICUBIC, expand=False)
        frame = base.copy()
        frame.paste(rot, (int(round(x - SPRITE / 2)), int(round(y - SPRITE / 2))), rot)
        path = os.path.join(frames_dir, f'{i:04d}.png')
        frame.save(path, compress_level=1)
        if i == mid and still_png:
            os.makedirs(os.path.dirname(still_png), exist_ok=True)
            frame.save(still_png)
    log(f'draw: {shape["name"]} — {n} frames')
    return n


# ── the drums ────────────────────────────────────────────────────────────────


def _drum_pool(seeds=256):
    """Distinct CC0 one-shot paths from the drum family.

    instrument_shot picks one file per seed and exposes no listing, so the
    pool is sampled: 256 seeds over ~4,900 usable files gives ~240 distinct
    paths in well under two seconds, which is plenty to find a kick and a
    snare by name.
    """
    out = []
    seen = set()
    for s in range(int(seeds)):
        p = ks.instrument_shot(DRUM_FAMILY, seed=s)
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return sorted(out)


def _pick_drums(log):
    """(kick, snare) — chosen by descriptor, with named fallbacks.

    The file names read <mic>_<piece>_<articulation>, so 'kickmic_kick' is a
    kick drum on the kick mic and 'kickmic_snare' is a SNARE on the kick mic.
    Preferring the matching mic first is the difference between a beat and a
    pair of distant thuds.
    """
    pool = _drum_pool()
    names = {p: os.path.basename(p).lower() for p in pool}

    def first(*needles):
        for needle in needles:
            for p in pool:
                if needle in names[p]:
                    return p
        return None

    kick = first('kickmic_kick', 'mid_kick', '_kick_', 'kick', 'bass')
    snare = first('snaremic_snare_', 'mid_snare_', '_snare_', 'snare')
    if snare == kick:
        snare = None
    if not (kick and snare):  # the brief's last resort
        spare = [p for p in pool if p not in (kick, snare)]
        kick = kick or (spare.pop(0) if spare else None)
        snare = snare or (spare.pop(0) if spare else None)
    log(f'drums: kick={os.path.basename(kick) if kick else "-"} snare={os.path.basename(snare) if snare else "-"}')
    return kick, snare


def _drum_bar(kick, snare, tick, out_wav):
    """One 2 s bar of 4/4 at 120 bpm, mixed once and then looped.

    Placing every hit of a 60 s episode individually would hand ffmpeg 400+
    inputs for one amix; a bar is the same beat and thirty of them is a mix
    ffmpeg can actually run.
    """
    tracks = []
    for b in range(4):
        at = b * BEAT
        if kick:
            tracks.append((kick, at, -8.0))
        if snare and b in (1, 3):
            tracks.append((snare, at, -12.0))
    if tick:
        for e in range(8):
            tracks.append((tick, e * BEAT / 2.0, -22.0))
    return ks.mix_audio(tracks, out_wav, BAR)


# ── the episode ──────────────────────────────────────────────────────────────


def _rows(episode, test_mode):
    """Six table rows for episode k, or row 0 alone for a --test run."""
    if test_mode:
        return [0]
    start = ((int(episode) - 1) * 2) % len(SHAPES)
    return [(start + i) % len(SHAPES) for i in range(SHAPES_PER_EPISODE)]


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    t0 = time.time()
    log = log_fn or (lambda _m: None)
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    os.makedirs(out_dir, exist_ok=True)
    stills = os.path.join(out_dir, 'stills')
    clips_d = os.path.join(out_dir, 'clips')
    audio_d = os.path.join(out_dir, 'audio')
    for p in (stills, clips_d, audio_d):
        os.makedirs(p, exist_ok=True)

    manifest = {
        'slug': SERIES['slug'],
        'title': SERIES['title'],
        'episode': int(episode),
        'test_mode': bool(test_mode),
        'ok': False,
        'reason': '',
        'duration_s': 0.0,
        'files': {'episode': 'episode.mp4', 'poster': 'poster.jpg'},
        'stages_completed': [],
        'shapes': [],
        'drum_files': [],
        'voice': {'engine': '', 'lines': []},
        'models_used': [],
        'licences': [],
        'tables_used': [],
    }

    def done(name):
        manifest['stages_completed'].append(name)

    def fail(reason):
        manifest['reason'] = reason
        log(f'FAILED: {reason}')
        ks.write_manifest(out_dir, manifest)
        return manifest

    # ── Episode Plan ─────────────────────────────────────────────────────────
    stage(STAGES[0])
    rows = _rows(episode, test_mode)
    plan = [SHAPES[i] for i in rows]
    total_s = len(plan) * UNIT_SECONDS
    manifest['shapes'] = [s['name'] for s in plan]
    manifest['tables_used'] = [{'table': 'SHAPES', 'row': i, 'name': SHAPES[i]['name']} for i in rows]
    log(f'plan: episode {episode} — {", ".join(manifest["shapes"])} ({total_s:.0f}s)')
    done(STAGES[0])

    # ── Draw the Parade ──────────────────────────────────────────────────────
    stage(STAGES[1])
    clips = []
    for n, shape in enumerate(plan, 1):
        if abort():
            return fail('aborted while drawing')
        frames_dir = os.path.join(out_dir, 'frames', f'u{n:02d}')
        still = os.path.join(stills, f'{n:02d}_{shape["name"]}.png')
        if not _render_unit(shape, frames_dir, still, log, abort):
            return fail(f'no frames rendered for {shape["name"]}')
        clip = os.path.join(clips_d, f'u{n:02d}_{shape["name"]}.mp4')
        if not ks.frames_to_clip(os.path.join(frames_dir, '%04d.png'), clip):
            return fail(f'frames_to_clip failed for {shape["name"]}')
        clips.append(clip)
        shutil.rmtree(frames_dir, ignore_errors=True)  # ~60 MB per unit
    done(STAGES[1])

    # ── Say the Shapes ───────────────────────────────────────────────────────
    stage(STAGES[2])
    voices, engine = [], ''
    for n, shape in enumerate(plan, 1):
        if abort():
            return fail('aborted before speech')
        wav = os.path.join(audio_d, f'say_{n:02d}_{shape["name"]}.wav')
        got = ks.say(shape['name'], wav, voice=VOICE, seed=7 + n, log_fn=log)
        if not got:
            # The series is a naming series.  Silent pictures of shapes are
            # not a degraded episode, they are a different and useless one.
            return fail(f'voice failed for "{shape["name"]}" — no engine produced a line')
        engine = engine or got
        voices.append(
            {
                'text': shape['name'],
                'wav': os.path.relpath(wav, out_dir),
                'at_s': (n - 1) * UNIT_SECONDS + SAY_AT,
                'engine': got,
            }
        )
        log(f'voice: "{shape["name"]}" via {got}')
    manifest['voice'] = {'engine': engine, 'lines': voices}
    done(STAGES[2])

    # ── Drums ────────────────────────────────────────────────────────────────
    stage(STAGES[3])
    if abort():
        return fail('aborted before the drums')
    kick, snare = _pick_drums(log)
    if not (kick and snare):
        return fail('no CC0 drum one-shots available')
    manifest['drum_files'] = [
        {'role': 'kick', 'path': kick, 'license_id': 'cc0'},
        {'role': 'snare', 'path': snare, 'license_id': 'cc0'},
    ]
    tick = os.path.join(audio_d, 'hat_tick.wav')
    if not ks.synth_sfx('tick', tick, seconds=0.10, seed=3):
        tick = None
        log('drums: no hat tick (synth_sfx unavailable) — kick and snare only')
    bar = os.path.join(audio_d, 'bar_120bpm.wav')
    if not _drum_bar(kick, snare, tick, bar):
        return fail('the drum bar would not mix')
    done(STAGES[3])

    # ── Assemble & Deliver ───────────────────────────────────────────────────
    stage(STAGES[4])
    if abort():
        return fail('aborted before assembly')

    ding = os.path.join(audio_d, 'hop_ding.wav')
    if not ks.synth_sfx('ding', ding, seconds=0.9, seed=11):
        ding = None

    # The bar loops the whole way; the dings and the words land on the unit
    # grid.  Everything is one amix so the balance is decided once.
    tracks = [(bar, i * BAR, -5.0) for i in range(int(math.ceil(total_s / BAR)))]
    for n, line in enumerate(voices, 1):
        base = (n - 1) * UNIT_SECONDS
        if ding:
            tracks.append((ding, base + HOP_AT, -4.0))
        tracks.append((os.path.join(out_dir, line['wav']), base + SAY_AT, 2.0))
    bed = os.path.join(audio_d, 'bed.wav')
    if not ks.mix_audio(tracks, bed, total_s):
        return fail('the audio bed would not mix')

    silent = os.path.join(out_dir, 'parade_silent.mp4')
    # xfade=0: a crossfade would both shorten the video and slide every hop
    # off the beat it was drawn on.
    if not ks.concat_clips(clips, silent, xfade=0):
        return fail('concat_clips failed')

    mp4 = os.path.join(out_dir, 'episode.mp4')
    if not ks.mux(silent, bed, mp4):
        return fail('mux failed')
    jpg = os.path.join(out_dir, 'poster.jpg')
    if not ks.write_poster(mp4, jpg):
        return fail('poster failed')

    info = ks.probe(mp4)
    manifest['duration_s'] = round(info['duration'], 2)
    manifest['probe'] = info
    if info['duration'] < 5.0 or not info['has_audio']:
        return fail(f'delivered file is not an episode: {info}')
    done(STAGES[4])

    manifest['models_used'] = [
        {'what': 'pictures', 'model': 'none — PIL vector drawing on the CPU'},
        {'what': 'speech', 'model': engine},
        {'what': 'music', 'model': 'none — CC0 one-shots on a 120 bpm grid'},
    ]
    manifest['licences'] = [
        {
            'component': 'drum one-shots',
            'licence': 'cc0',
            'note': 'kids_series_common.instrument_shot serves cc0/public-domain '
            'records only and excludes no_ai_training packs',
        },
        {'component': 'voice references', 'licence': 'Apache-2.0', 'note': 'synthetic Maya1 seed voices'},
        {'component': 'pictures', 'licence': 'n/a — generated by this file'},
    ]
    manifest['ok'] = True
    manifest['reason'] = 'ok'
    manifest['wall_s'] = round(time.time() - t0, 1)
    ks.write_manifest(out_dir, manifest)
    log(f'delivered {manifest["duration_s"]}s in {manifest["wall_s"]}s')
    return manifest


if __name__ == '__main__':
    sys.exit(ks.run_cli(sys.modules[__name__]))
