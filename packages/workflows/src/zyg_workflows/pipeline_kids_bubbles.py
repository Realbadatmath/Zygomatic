# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_bubbles.py — "Bubble Pop", the CPU-only children's series.

Translucent bubbles rise across a pale sky and pop.  Every pop plays a synth
pop plus one CC0 piano one-shot, and because the note is chosen by WHERE the
bubble pops — left is low, right is high — the bubbles write a little
pentatonic tune as they go.  A pentatonic scale has no wrong notes, which is
the whole reason this series can be deterministic and still sound musical.

This is the only series in the family that touches NO model at all: no
picture from a diffusion graph, no voice, no soundfont bed.  Pillow draws
every frame, numpy makes every effect, and the notes are files on disk.  That
makes it the tree's integration smoke unit — if this one cannot produce an
mp4, the fault is in the shared floor (ffmpeg, the mixer, the manifest), not
in a model.  It is held to well under 90 s for a full episode for exactly
that reason, so keep the per-frame work cheap: the bubble sprites are drawn
once per radius and pasted, never redrawn per frame.

Everything the episode needs comes from the fixed tables below, so an episode
costs nothing and episode N is always the same episode N.
"""

from __future__ import annotations

import math
import os
import random
import sys
import time

from zyg_workflows import kids_series_common as K

SERIES = {
    'slug': 'bubbles',
    'title': 'Bubble Pop',
    'tagline': 'Bubbles float up, and every pop sings a note.',
    'voice': False,
    'characters': False,
    'gpu': False,
    'age_band': 'toddler',
    'episode_seconds': 60,
    'episodes': 12,
    'agents': {
        'Episode Plan': 'python random (seeded by episode)',
        'Blow Bubbles': 'Pillow RGBA + ffmpeg',
        'Pop Notes': 'numpy synth + CC0 piano one-shots',
        'Assemble & Deliver': 'ffmpeg mix + mux',
    },
}

STAGES = ['Episode Plan', 'Blow Bubbles', 'Pop Notes', 'Assemble & Deliver']

# ── fixed tables ─────────────────────────────────────────────────────────────
#
# A major pentatonic run.  Left of frame is low, right is high, so the tune an
# episode plays is a readable picture of where its bubbles drifted.

SCALE = ['C4', 'D4', 'E4', 'G4', 'A4', 'C5', 'D5', 'E5']

# Hz for the last-resort synthesised note, when neither the piano nor the
# steel drum has a sample at that pitch.
SCALE_HZ = {
    'C4': 261.63,
    'D4': 293.66,
    'E4': 329.63,
    'G4': 392.00,
    'A4': 440.00,
    'C5': 523.25,
    'D5': 587.33,
    'E5': 659.25,
}

# One tint per episode, so the twelve episodes are not twelve of the same film.
TINTS = [
    ('shell pink', (255, 225, 240)),
    ('sea glass', (215, 250, 245)),
    ('lemon drop', (255, 248, 205)),
    ('lilac', (232, 225, 255)),
    ('mint', (222, 252, 228)),
    ('peach', (255, 235, 215)),
]

SKY_TOP = (200, 240, 255)  # pale cyan at the top of frame
SKY_BOTTOM = (240, 250, 255)  # almost white at the horizon
GROUND = (146, 205, 140)  # the low green band the bubbles rise from
GROUND_H = 74

BUBBLES_FULL = 28
BUBBLES_TEST = 5
TEST_SECONDS = 8.0

POP_FRAMES = 6  # how long a burst is on screen
POP_DROPLETS = 10  # radial droplets per burst

SPAWN_Y = 800.0  # below the frame: bubbles enter from there
SPEED_MIN, SPEED_MAX = 90.0, 160.0
POP_Y_MIN, POP_Y_MAX = 120.0, 400.0


# ── episode plan ─────────────────────────────────────────────────────────────


def _plan(episode, seconds, count):
    """The whole episode as data: one dict per bubble, pops already in time.

    POP TIMES ARE SCHEDULED FIRST and the rise is derived backwards from them.
    Doing it the other way round (spawn, then see when it pops) is what leaves
    dead air: with 5 bubbles in 8 s the pops all pile into the last second.
    Here the pops are spread evenly, each bubble's speed is solved so that it
    is already on screen 0.4 s before its predecessor bursts, and a bubble
    whose rise wants to begin before t=0 simply starts off-frame at a negative
    time — it is mid-climb when the film opens, which is what you want anyway.
    """
    rng = random.Random(int(episode))
    count = max(1, int(count))

    first_pop = min(1.6, max(0.8, seconds * 0.2))
    last_pop = seconds - 0.5
    step = (last_pop - first_pop) / max(1, count - 1) if count > 1 else 0.0
    jitter = step * 0.18

    pops_t = []
    for i in range(count):
        t = first_pop + i * step
        if step:
            t += rng.uniform(-jitter, jitter)
        t = min(last_pop, max(first_pop - jitter, t))
        if pops_t:
            t = max(t, pops_t[-1] + 0.25)  # never two notes on one frame
        pops_t.append(min(last_pop, t))

    bubbles = []
    for i, pop_t in enumerate(pops_t):
        radius = rng.uniform(40.0, 130.0)
        pop_y = rng.uniform(POP_Y_MIN, POP_Y_MAX)
        travel = SPAWN_Y - pop_y  # 400 .. 680 px

        # The latest moment this bubble may leave the ground and still be in
        # the air before the previous one pops.
        latest_start = (pops_t[i - 1] - 0.4) if i else (pop_t - travel / SPEED_MAX)
        lifetime = max(pop_t - latest_start, travel / SPEED_MAX)
        speed = min(SPEED_MAX, max(SPEED_MIN, travel / lifetime))
        lifetime = travel / speed

        bubbles.append(
            {
                'i': i,
                'radius': radius,
                'x0': rng.uniform(100.0, 1180.0),
                'speed': speed,
                'pop_y': SPAWN_Y - speed * lifetime,
                'start': pop_t - lifetime,
                'pop_t': pop_t,
                'wob_amp': rng.uniform(8.0, 40.0),
                'wob_hz': rng.uniform(0.15, 0.50),
                'wob_phase': rng.uniform(0.0, 2.0 * math.pi),
                'spin': rng.uniform(0.0, 2.0 * math.pi),  # droplet phase
            }
        )

    for b in bubbles:
        b['x_pop'] = _bubble_x(b, b['pop_t'])
        b['pitch'] = SCALE[_pitch_index(b['x_pop'])]
    return bubbles


def _bubble_x(b, t):
    return b['x0'] + b['wob_amp'] * math.sin(2.0 * math.pi * b['wob_hz'] * (t - b['start']) + b['wob_phase'])


def _bubble_y(b, t):
    return SPAWN_Y - b['speed'] * (t - b['start'])


def _pitch_index(x):
    """Screen position -> scale degree.  Left of frame is the low note."""
    u = (min(1180.0, max(100.0, float(x))) - 100.0) / 1080.0
    return min(len(SCALE) - 1, max(0, int(u * len(SCALE))))


# ── drawing ──────────────────────────────────────────────────────────────────


def _sky(Image, ImageDraw):
    """The background, built once and copied per frame."""
    img = Image.new('RGB', (K.W, K.H), SKY_BOTTOM)
    d = ImageDraw.Draw(img)
    span = K.H - GROUND_H
    for y in range(span):
        u = y / max(1, span - 1)
        d.line(
            [(0, y), (K.W, y)], fill=tuple(int(round(SKY_TOP[c] + (SKY_BOTTOM[c] - SKY_TOP[c]) * u)) for c in range(3))
        )
    d.rectangle([0, span, K.W, K.H], fill=GROUND)
    d.rectangle([0, span, K.W, span + 5], fill=tuple(min(255, c + 26) for c in GROUND))
    return img


def _bubble_tile(Image, ImageDraw, radius, tint):
    """One bubble sprite: faint fill, soft ring, a highlight arc, a sparkle.

    Cached per radius by the caller — redrawing this for every bubble on every
    one of 1440 frames is the difference between 40 s and ten minutes.
    """
    r = max(6, int(round(radius)))
    pad = 6
    size = 2 * r + 2 * pad
    tile = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    c = size / 2.0
    box = [c - r, c - r, c + r, c + r]

    d.ellipse(box, fill=(tint[0], tint[1], tint[2], 40))
    d.ellipse(box, outline=(255, 255, 255, 160), width=max(2, int(r * 0.07)))

    hb = [c - r * 0.72, c - r * 0.72, c + r * 0.72, c + r * 0.72]
    d.arc(hb, start=196, end=262, fill=(255, 255, 255, 195), width=max(2, int(r * 0.09)))

    sr = max(2.0, r * 0.09)
    sx = c + r * 0.52 * math.cos(math.radians(238))
    sy = c + r * 0.52 * math.sin(math.radians(238))
    d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 255, 255, 230))
    return tile


def _draw_pop(Image, ImageDraw, img, b, k, tint):
    """Frame k (0..5) of a burst: ten droplets flung outward, fading."""
    r = b['radius']
    spread = r * (1.0 + 0.24 * k)
    dr = max(2.0, r * 0.13 * (1.0 - k / float(POP_FRAMES + 2)))
    alpha = int(215 * (1.0 - k / float(POP_FRAMES)))
    if alpha <= 4:
        return
    reach = int(math.ceil(spread + dr)) + 4
    size = 2 * reach
    tile = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    for j in range(POP_DROPLETS):
        a = b['spin'] + 2.0 * math.pi * j / POP_DROPLETS
        dx = reach + spread * math.cos(a)
        dy = reach + spread * math.sin(a)
        d.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill=(tint[0], tint[1], tint[2], alpha))
        d.ellipse(
            [dx - dr, dy - dr, dx + dr, dy + dr],
            outline=(255, 255, 255, min(255, alpha + 30)),
            width=max(1, int(dr * 0.35)),
        )
    img.paste(tile, (int(round(b['x_pop'] - reach)), int(round(b['pop_y'] - reach))), tile)


def _render_frames(bubbles, seconds, tint, stills_dir, log, abort):
    """Every frame of the episode as a PNG.  Returns the printf pattern."""
    from PIL import Image, ImageDraw

    base = _sky(Image, ImageDraw)
    tiles = {}
    total = max(1, int(round(seconds * K.FPS)))
    pop_span = POP_FRAMES / float(K.FPS)
    pattern = os.path.join(stills_dir, 'f%05d.png')

    for fi in range(total):
        if fi % 48 == 0 and abort():
            return None
        t = fi / float(K.FPS)
        img = base.copy()
        for b in bubbles:
            if b['start'] <= t < b['pop_t']:
                r = int(round(b['radius']))
                tile = tiles.get(r)
                if tile is None:
                    tile = tiles[r] = _bubble_tile(Image, ImageDraw, r, tint)
                half = tile.size[0] / 2.0
                img.paste(tile, (int(round(_bubble_x(b, t) - half)), int(round(_bubble_y(b, t) - half))), tile)
            elif b['pop_t'] <= t < b['pop_t'] + pop_span:
                _draw_pop(Image, ImageDraw, img, b, int(round((t - b['pop_t']) * K.FPS)), tint)
        img.save(pattern % fi, compress_level=1)
        if fi and fi % 240 == 0:
            log(f'  frames {fi}/{total}')
    log(f'  frames {total}/{total}')
    return pattern


# ── the note under each pop ──────────────────────────────────────────────────


def _note_for(b, audio_dir, seed):
    """The CC0 one-shot for this pop, or a synthesised bell as last resort.

    Returns (path, license_id, source) — the manifest records all three,
    because 'which file played' is the licence evidence for this series.
    """
    pitch = b['pitch']
    for family in ('Osiris_Piano', 'SteelDrum'):
        path = K.instrument_shot(family, pitch, seed=seed)
        if path:
            return path, 'cc0', family
    out = os.path.join(audio_dir, f'note_{b["i"]:02d}.wav')
    if K.synth_sfx('ding', out, seconds=1.4, seed=seed, f0=SCALE_HZ.get(pitch, 440.0)):
        return out, 'generated', 'synth:ding'
    return None, '', ''


# ── the episode ──────────────────────────────────────────────────────────────


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    t_start = time.time()
    log = log_fn or (lambda _m: None)
    abort = should_abort or (lambda: False)
    done = []

    def stage(name):
        done.append(name)
        if stage_fn:
            stage_fn(name)
        log(f'[{SERIES["slug"]}] {name}')

    episode = int(episode or 1)
    seconds = TEST_SECONDS if test_mode else float(SERIES['episode_seconds'])
    count = BUBBLES_TEST if test_mode else BUBBLES_FULL
    tint_name, tint = TINTS[(episode - 1) % len(TINTS)]

    stills = os.path.join(out_dir, 'stills')
    clips = os.path.join(out_dir, 'clips')
    audio = os.path.join(out_dir, 'audio')
    for d in (stills, clips, audio):
        os.makedirs(d, exist_ok=True)

    manifest = {
        'slug': SERIES['slug'],
        'title': SERIES['title'],
        'episode': episode,
        'test_mode': bool(test_mode),
        'ok': False,
        'reason': '',
        'duration_s': 0.0,
        'files': {'episode': 'episode.mp4', 'poster': 'poster.jpg'},
        'stages_completed': done,
        'voice': {'engine': '', 'lines': 0},
        'models_used': [],
        'licences': [],
        'tables_used': {},
        'bubbles': 0,
        'pops': [],
        'gpu_used': False,
    }

    def fail(reason):
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - t_start, 2)
        log(f'[{SERIES["slug"]}] FAILED: {reason}')
        K.write_manifest(out_dir, manifest)
        return manifest

    # ── 1. Episode Plan ──────────────────────────────────────────────────
    stage(STAGES[0])
    bubbles = _plan(episode, seconds, count)
    manifest['bubbles'] = len(bubbles)
    manifest['tables_used'] = {
        'scale': sorted({b['pitch'] for b in bubbles}, key=lambda p: SCALE.index(p)),
        'tint': tint_name,
        'tune': [b['pitch'] for b in bubbles],
    }
    log(f'  {len(bubbles)} bubbles over {seconds:g}s, tint {tint_name}, tune {" ".join(b["pitch"] for b in bubbles)}')
    if abort():
        return fail('aborted')

    # ── 2. Blow Bubbles ──────────────────────────────────────────────────
    stage(STAGES[1])
    pattern = _render_frames(bubbles, seconds, tint, stills, log, abort)
    if pattern is None:
        return fail('aborted')
    silent = os.path.join(clips, 'bubbles.mp4')
    if not K.frames_to_clip(pattern, silent, fps=K.FPS):
        return fail('ffmpeg could not turn the frames into a clip')
    if abort():
        return fail('aborted')

    # ── 3. Pop Notes ─────────────────────────────────────────────────────
    stage(STAGES[2])
    tracks, pops, families = [], [], set()
    for b in bubbles:
        seed = episode * 1000 + b['i']
        pop_wav = os.path.join(audio, f'pop_{b["i"]:02d}.wav')
        if K.synth_sfx('pop', pop_wav, seconds=0.35, seed=seed):
            tracks.append((pop_wav, max(0.0, b['pop_t']), -8.0))
        note, lic, source = _note_for(b, audio, seed)
        if note:
            tracks.append((note, max(0.0, b['pop_t']), -6.0))
            families.add(source)
        pops.append(
            {
                't': round(b['pop_t'], 3),
                'pitch': b['pitch'],
                'file': os.path.basename(note) if note else '',
                'license_id': lic,
                'source': source,
                'x': round(b['x_pop'], 1),
            }
        )
    manifest['pops'] = pops

    # The 'breath' between the notes: one soft sweep every six seconds, well
    # under the pops.  There is no music bed — the pops ARE the tune.
    breath = os.path.join(audio, 'breath.wav')
    if K.synth_sfx('whoosh', breath, seconds=1.5, seed=episode):
        t = 0.0
        while t < seconds - 1.5:
            tracks.append((breath, t, -24.0))
            t += 6.0

    mixed = os.path.join(audio, 'mix.wav')
    if not K.mix_audio(tracks, mixed, seconds):
        return fail('the mixer produced no bed')
    if abort():
        return fail('aborted')

    # ── 4. Assemble & Deliver ────────────────────────────────────────────
    stage(STAGES[3])
    episode_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not K.mux(silent, mixed, episode_mp4):
        return fail('mux failed')
    poster = os.path.join(out_dir, 'poster.jpg')
    if not K.write_poster(episode_mp4, poster):
        return fail('poster failed')

    info = K.probe(episode_mp4)
    if info['duration'] < 5.0 or not info['has_audio']:
        return fail(f'episode is {info["duration"]:.2f}s (audio={info["has_audio"]})')
    if (info['w'], info['h']) != (K.W, K.H):
        return fail(f'episode is {info["w"]}x{info["h"]}')

    manifest['licences'] = [
        {'asset': 'Osiris_Piano / SteelDrum one-shots', 'license_id': 'cc0', 'used': sorted(families)},
        {'asset': 'synth_sfx (numpy, generated in-process)', 'license_id': 'generated'},
    ]
    manifest['ok'] = True
    manifest['reason'] = ''
    manifest['duration_s'] = round(info['duration'], 2)
    manifest['wall_s'] = round(time.time() - t_start, 2)
    K.write_manifest(out_dir, manifest)
    log(f'[{SERIES["slug"]}] episode.mp4 {info["duration"]:.2f}s in {manifest["wall_s"]:.1f}s wall')
    return manifest


if __name__ == '__main__':
    sys.exit(K.run_cli(sys.modules[__name__]))
