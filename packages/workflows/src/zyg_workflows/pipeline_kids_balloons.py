# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_balloons.py — "Colour Balloons", one of the ten kids series.

The simplest thing that can still teach something: a single big balloon of one
colour floats up a pale sky, a warm voice names the colour as it passes the
middle of the frame, and at the top it pops into a little burst of confetti.
Six balloons, ten seconds each, sixty seconds an episode.

WHY THERE IS NO IMAGE MODEL HERE.  A toddler colour lesson has exactly one
requirement a diffusion model cannot be trusted to meet: the red balloon must
be *that* red, frame after frame, episode after episode.  A flat balloon is
four PIL primitives, so the picture side of this series is arithmetic — no
ComfyUI, no klein, no wan, nothing queued behind another executor's render.
The only weight this runner ever loads is the speech engine, because the
spoken word is the entire point of the series (see ``run_episode``: a silent
episode is a FAILED episode, not a degraded one).

Everything that touches a codec, the speech engine, the soundfont or the job
registry lives in ``kids_series_common``; this file owns the colour table and
the ten seconds of choreography around each balloon, and nothing else.

Cost per episode: zero paid calls.  No hosted SDK is imported anywhere in this
family, the pictures are numpy-free arithmetic, the music is a local MIT
soundfont and the voice is a local worker.  ``kids_series_common.write_manifest``
stamps that record and ``scripts/kids_series_check.py`` re-proves it from the
delivered files.
"""

from __future__ import annotations

import math
import os
import random
import sys
import time

from PIL import Image, ImageDraw

from zyg_workflows import kids_series_common as K

SERIES = {
    'slug': 'balloons',
    'title': 'Colour Balloons',
    'tagline': 'A balloon floats up, we say its colour, and it pops into confetti.',
    'voice': True,
    'characters': False,
    # The PICTURES are CPU-only PIL.  This flag is still True because the
    # speech engine loads onto the GPU, and the board schedules on this flag —
    # a series that says False and then takes 20 GB of VRAM would break the
    # queue for every other runner.
    'gpu': True,
    'age_band': 'toddler',
    'episode_seconds': 60,
    'episodes': 10,
    'agents': {
        'Episode Plan': 'colour table',
        'Draw Balloons': 'PIL',
        'Say the Colours': 'IndexTTS-2 / Chatterbox',
        'Pops & Music': 'synth_sfx + MuseScore soundfont',
        'Assemble & Deliver': 'ffmpeg',
    },
}

STAGES = ['Episode Plan', 'Draw Balloons', 'Say the Colours', 'Pops & Music', 'Assemble & Deliver']

# ── the fixed table ──────────────────────────────────────────────────────────
#
# Ten colours, in the order a toddler meets them.  Fixed, because "which colour
# comes next" is the one decision in this series that must never be a model's:
# episode k is reproducible from k alone.

COLOURS = [
    ('red', (230, 57, 70)),
    ('yellow', (255, 209, 102)),
    ('blue', (69, 123, 157)),
    ('green', (106, 199, 126)),
    ('orange', (255, 140, 66)),
    ('purple', (155, 93, 229)),
    ('pink', (255, 143, 177)),
    ('brown', (150, 105, 70)),
    ('black', (40, 40, 48)),
    ('white', (245, 245, 245)),
]

BALLOONS_PER_EPISODE = 6

# ── choreography (seconds inside one 10 s balloon unit) ──────────────────────

UNIT_SECONDS = 10.0
RISE_SECONDS = 8.0  # y 760 -> 120, ease-in-out
SAY_AT = 4.0  # the balloon is crossing the middle of the frame
POP_AT = 8.0
SHARD_FRAMES = 6  # the burst itself: a quarter of a second
CONFETTI_SECONDS = 2.0  # 8.0 -> 10.0, the fall

Y_START, Y_END = 760.0, 120.0
X_CENTRE, X_DRIFT = 640.0, 40.0
BALLOON_R = 150.0

# ── the look ─────────────────────────────────────────────────────────────────

INK = (34, 34, 40)
# Black's outline is drawn in this instead: a (40,40,48) balloon with a
# (34,34,40) outline is a black disc with no shape in it at all.
INK_LIGHT = (120, 120, 136)
GROUND_FRAC = 0.72
GROUND_RGB = (126, 214, 96)

SKY_TOP, SKY_BOTTOM = (176, 226, 255), (230, 245, 255)
# The white balloon needs somewhere to be white AGAINST, so its ten seconds get
# a deeper sky.  Same picture, one shade down.
SKY_TOP_DEEP, SKY_BOTTOM_DEEP = (146, 202, 240), (196, 226, 246)

CONFETTI_RGB = [(255, 209, 102), (255, 143, 177), (106, 199, 126), (155, 93, 229), (255, 140, 66), (69, 123, 157)]

_BG_CACHE = {}


def _lighten(col, f=0.42):
    return tuple(int(c + (255 - c) * f) for c in col)


def _background(deep):
    """The sky+ground plate for a unit, drawn once and copied per frame.

    518 gradient lines per frame times 1440 frames is a minute of CPU spent
    redrawing an identical picture; there are two plates in the whole series.
    """
    key = bool(deep)
    if key in _BG_CACHE:
        return _BG_CACHE[key]
    top, bot = (SKY_TOP_DEEP, SKY_BOTTOM_DEEP) if deep else (SKY_TOP, SKY_BOTTOM)
    img = Image.new('RGB', (K.W, K.H), bot)
    d = ImageDraw.Draw(img)
    gy = int(K.H * GROUND_FRAC)
    for y in range(gy):
        f = y / max(1.0, gy - 1)
        d.line([(0, y), (K.W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * f) for i in range(3)))
    d.rectangle([0, gy, K.W, K.H], fill=GROUND_RGB)
    d.line([(0, gy), (K.W, gy)], fill=INK, width=5)
    _BG_CACHE[key] = img
    return img


def _draw_balloon(d, cx, cy, r, col, outline, t):
    """Ellipse, knot, highlight and a string that sways with t.

    The shape is kids_video_service._draw_balloon; the sway is the difference —
    a still string on a rising balloon reads as a stick.
    """
    d.ellipse([cx - r, cy - r * 1.18, cx + r, cy + r * 1.18], fill=col, outline=outline, width=7)
    d.polygon(
        [(cx - r * 0.16, cy + r * 1.12), (cx + r * 0.16, cy + r * 1.12), (cx, cy + r * 1.36)], fill=col, outline=outline
    )
    d.ellipse([cx - r * 0.62, cy - r * 0.86, cx - r * 0.26, cy - r * 0.26], fill=_lighten(col))
    pts = []
    for k in range(24):
        f = k / 23.0
        pts.append((cx + math.sin(f * 5.2 + t * 2.0) * r * 0.24, cy + r * (1.36 + f * 1.5)))
    d.line(pts, fill=outline, width=4, joint='curve')


def _draw_shards(d, cx, cy, r, col, outline, prog):
    """Eight radial slivers flying off the pop, for six frames."""
    spread = r * (0.35 + 1.60 * prog)
    size = r * 0.30 * (1.0 - 0.45 * prog)
    for k in range(8):
        a = k * math.pi / 4.0 + 0.20
        px, py = cx + math.cos(a) * spread, cy + math.sin(a) * spread
        d.polygon(
            [
                (px + math.cos(a) * size, py + math.sin(a) * size),
                (px + math.cos(a + 2.2) * size * 0.7, py + math.sin(a + 2.2) * size * 0.7),
                (px + math.cos(a - 2.2) * size * 0.7, py + math.sin(a - 2.2) * size * 0.7),
            ],
            fill=col,
            outline=outline,
        )


def _confetti(seed):
    """20 dots: angle, speed and colour, fixed for the unit."""
    rng = random.Random(int(seed) ^ 0x1005)
    out = []
    for i in range(20):
        a = -math.pi / 2.0 + rng.uniform(-1.15, 1.15)
        sp = rng.uniform(200.0, 470.0)
        out.append(
            {
                'vx': math.cos(a) * sp,
                'vy': math.sin(a) * sp,
                'rgb': CONFETTI_RGB[i % len(CONFETTI_RGB)],
                'rad': rng.uniform(6.0, 11.0),
            }
        )
    return out


def _draw_confetti(d, cx, cy, dots, dt):
    """dt seconds after the pop.  Straight ballistics, 900 px/s/s of gravity."""
    for c in dots:
        x = cx + c['vx'] * dt
        y = cy + c['vy'] * dt + 0.5 * 900.0 * dt * dt
        if y > K.H + 20 or x < -20 or x > K.W + 20:
            continue
        r = c['rad']
        d.ellipse([x - r, y - r, x + r, y + r], fill=c['rgb'], outline=INK, width=2)


def _render_unit(frames_dir, stills_dir, first_index, index, name, rgb, log_fn, should_abort):
    """Draw one 10 s balloon.  Returns (frames_written, still_path)."""
    n = int(round(UNIT_SECONDS * K.FPS))
    deep = name == 'white'
    outline = INK_LIGHT if name == 'black' else INK
    bg = _background(deep)
    dots = _confetti(first_index + index)
    phase = (index * 1.7) % (2.0 * math.pi)
    still = ''
    for f in range(n):
        if should_abort and should_abort():
            return f, still
        t = f / float(K.FPS)
        img = bg.copy()
        d = ImageDraw.Draw(img)
        u = min(1.0, t / RISE_SECONDS)
        ease = 0.5 - 0.5 * math.cos(math.pi * u)  # ease-in-out
        cy = Y_START + (Y_END - Y_START) * ease
        cx = X_CENTRE + X_DRIFT * math.sin(2.0 * math.pi * t / 6.5 + phase)
        if t < POP_AT:
            _draw_balloon(d, cx, cy, BALLOON_R, rgb, outline, t)
        else:
            dt = t - POP_AT
            shard_f = int(round(dt * K.FPS))
            if shard_f < SHARD_FRAMES:
                _draw_shards(d, cx, Y_END, BALLOON_R, rgb, outline, shard_f / float(SHARD_FRAMES))
            if dt <= CONFETTI_SECONDS:
                _draw_confetti(d, cx, Y_END, dots, dt)
        img.save(os.path.join(frames_dir, f'{first_index + f:04d}.png'))
        if abs(t - SAY_AT) < 0.5 / K.FPS:
            still = os.path.join(stills_dir, f'balloon_{index + 1:02d}_{name}.png')
            img.save(still)
    log_fn(f'drew {n} frames for the {name} balloon')
    return n, still


def _episode_rows(episode, test_mode):
    """Which rows of COLOURS this episode draws.

    Episode k starts two rows further down the table and wraps, so consecutive
    episodes overlap by four colours — a toddler meets a colour again before it
    has gone.  The test unit is always row 0 (red), so a --test run is
    comparable between machines and between days.
    """
    if test_mode:
        return [0]
    start = ((int(episode) - 1) * 2) % len(COLOURS)
    return [(start + i) % len(COLOURS) for i in range(BALLOONS_PER_EPISODE)]


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    log_fn = log_fn or (lambda _m: None)
    stage_fn = stage_fn or (lambda _s: None)
    should_abort = should_abort or (lambda: False)
    t0 = time.time()

    frames_dir = os.path.join(out_dir, 'frames')
    stills_dir = os.path.join(out_dir, 'stills')
    clips_dir = os.path.join(out_dir, 'clips')
    audio_dir = os.path.join(out_dir, 'audio')
    for p in (frames_dir, stills_dir, clips_dir, audio_dir):
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
        'colours': [],
        'timings': [],
        'voice': {'engine': '', 'lines': []},
        'models_used': [],
        'licences': [],
        'tables_used': {},
    }

    # A stage is recorded when the NEXT one starts, so `stages_completed` on a
    # failed run names what actually finished and not the stage that broke.
    current = [None]

    def _stage(name):
        if current[0]:
            manifest['stages_completed'].append(current[0])
        current[0] = name
        stage_fn(name)

    def _fail(reason):
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - t0, 2)
        log_fn(f'FAILED: {reason}')
        K.write_manifest(out_dir, manifest)
        return manifest

    # ── 1. plan ──────────────────────────────────────────────────────────────
    _stage('Episode Plan')
    rows = _episode_rows(episode, test_mode)
    units = [COLOURS[r] for r in rows]
    total_s = len(units) * UNIT_SECONDS
    manifest['colours'] = [n for n, _ in units]
    manifest['tables_used'] = {'COLOURS': [{'row': r, 'name': COLOURS[r][0], 'rgb': list(COLOURS[r][1])} for r in rows]}
    for i, (name, _rgb) in enumerate(units):
        base = i * UNIT_SECONDS
        manifest['timings'].append(
            {
                'colour': name,
                'start_s': base,
                'rise_s': [base, base + RISE_SECONDS],
                'say_s': base + SAY_AT,
                'pop_s': base + POP_AT,
                'confetti_s': [base + POP_AT, base + POP_AT + CONFETTI_SECONDS],
            }
        )
    log_fn(f'episode {episode}: {", ".join(manifest["colours"])} ({total_s:.0f} s)')

    # ── 2. pictures ──────────────────────────────────────────────────────────
    _stage('Draw Balloons')
    written = 0
    for i, (name, rgb) in enumerate(units):
        if should_abort():
            return _fail('aborted while drawing')
        n, _still = _render_unit(frames_dir, stills_dir, written, i, name, rgb, log_fn, should_abort)
        written += n
    if written < int(round(total_s * K.FPS)):
        return _fail(f'only {written} frames were drawn')

    silent = os.path.join(clips_dir, 'silent.mp4')
    if not K.frames_to_clip(os.path.join(frames_dir, '%04d.png'), silent):
        return _fail('the frame sequence would not encode')

    # ── 3. speech — the point of the series ──────────────────────────────────
    _stage('Say the Colours')
    tracks, engines = [], []
    for i, (name, _rgb) in enumerate(units):
        if should_abort():
            return _fail('aborted while speaking')
        wav = os.path.join(audio_dir, f'say_{i + 1:02d}.wav')
        engine = K.say(name, wav, voice='f01_warm_alto', seed=7 + i, log_fn=log_fn)
        if not engine:
            return _fail(
                f'the voice produced nothing for "{name}" — a Colour '
                'Balloons episode that does not say the colour is not '
                'an episode'
            )
        engines.append(engine)
        manifest['voice']['lines'].append(name)
        tracks.append((wav, i * UNIT_SECONDS + SAY_AT, 0.0))
    manifest['voice']['engine'] = engines[0] if len(set(engines)) == 1 else '+'.join(sorted(set(engines)))
    log_fn(f'voice: {manifest["voice"]["engine"]} said {len(manifest["voice"]["lines"])} colour(s)')

    # ── 4. pops and music ────────────────────────────────────────────────────
    _stage('Pops & Music')
    for i, (_name, _rgb) in enumerate(units):
        base = i * UNIT_SECONDS
        pop = os.path.join(audio_dir, f'pop_{i + 1:02d}.wav')
        if K.synth_sfx('pop', pop, seconds=0.6, seed=100 + i):
            tracks.append((pop, base + POP_AT, -2.0))
        rise = os.path.join(audio_dir, f'whoosh_{i + 1:02d}.wav')
        if K.synth_sfx('whoosh', rise, seconds=1.2, seed=200 + i):
            tracks.append((rise, base + 0.3, -14.0))

    bed = os.path.join(audio_dir, 'bed.wav')
    if K.music_bed(bed, seconds=total_s, mood='playful', age_band='toddler', seed=int(episode), log_fn=log_fn):
        tracks.append((bed, 0.0, -8.0))
        manifest['models_used'].append('MuseScore_General.sf3 (fluidsynth, CPU)')
    else:
        log_fn('music: no bed this run — the voice and the pops still carry it')

    mixed = os.path.join(audio_dir, 'mix.wav')
    if not K.mix_audio(tracks, mixed, total_s):
        return _fail('the audio would not mix')

    # ── 5. deliver ───────────────────────────────────────────────────────────
    _stage('Assemble & Deliver')
    episode_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not K.mux(silent, mixed, episode_mp4):
        return _fail('the mux produced no episode.mp4')
    info = K.probe(episode_mp4)
    if info['duration'] < 5.0 or not info['has_audio']:
        return _fail(f'the delivered file is {info["duration"]:.2f} s, audio={info["has_audio"]}')
    if not K.write_poster(episode_mp4, os.path.join(out_dir, 'poster.jpg')):
        return _fail('no poster could be taken from the episode')

    manifest['models_used'] = [
        f'{manifest["voice"]["engine"]} (local speech worker)',
        'PIL (no image model — the balloons are drawn)',
    ] + manifest['models_used']
    manifest['licences'] = [
        {'name': 'MuseScore_General.sf3', 'licence': 'MIT'},
        {'name': 'voice seed pool (Maya1-synthetic)', 'licence': 'Apache-2.0'},
        {'name': 'balloon artwork', 'licence': 'generated here, no third party'},
    ]
    manifest['stages_completed'].append(current[0])
    manifest['duration_s'] = round(info['duration'], 2)
    manifest['frames'] = written
    manifest['ok'] = True
    manifest['reason'] = ''
    K.write_manifest(out_dir, manifest)
    log_fn(f'delivered {episode_mp4} — {manifest["duration_s"]:.2f} s, {info["w"]}x{info["h"]}')
    return manifest


if __name__ == '__main__':
    sys.exit(K.run_cli(sys.modules[__name__]))
