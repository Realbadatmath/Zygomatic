# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_train.py — "Tiny Train Colours", one of the ten kids series.

A toy train rolls across one painted landscape.  Every seven seconds another
wagon comes in from the left and a warm voice says its colour.  No characters,
no story, no reading: a toddler learns eight colour words by watching objects.

WHY THE TRAIN IS DRAWN AND NOT GENERATED.  The whole lesson is "the third
wagon is green".  A diffusion model cannot be trusted to put a specific colour
in a specific place — ask for six wagons in a named order and you get five
wagons in a different order, differently every seed.  So the LAND comes from
FLUX.2 klein (one still, once per episode) and the TRAIN is drawn with PIL on
top of it, from a fixed RGB table.  The teaching content is arithmetic; only
the scenery is generative.  That split is also why an episode costs nothing:
one still, no video model, no LLM, no paid call anywhere.

Timing (SLOT_S = 7 s per wagon, SPEED_PX_S = 120 px/s on the track at y=560):

    t = 7*i      wagon i rolls in from the left and couples on (1.52 s of roll,
                 then the train stands still for the rest of its slot)
    t = 7*i + 1  the voice says that wagon's colour
    t = 7*n      the roll-out: the parked train is held long enough for the
                 whole line-up to be seen, then rolls off to the right

The geometry is chosen so the finished train exactly fills the frame: engine
180 px + six wagons of 170 px coupled 12 px apart = 1272 px against a 1280 px
picture.  Change WAGON_W or GAP_PX and the last wagon falls off the edge.

test_mode = the engine and ONE wagon, everything else identical (12 s).
"""

from __future__ import annotations

import os
import sys
import time

from zyg_workflows import kids_series_common as K

SERIES = {
    'slug': 'train',
    'title': 'Tiny Train Colours',
    'tagline': 'A little train rolls by and every wagon has a colour to say.',
    'voice': True,
    'characters': False,
    'gpu': True,
    'age_band': 'toddler',
    'episode_seconds': 60,
    'episodes': 8,
    'agents': {
        'Episode Plan': 'fixed landscape + colour tables',
        'Paint the Land': 'FLUX.2 klein-4B still',
        'Roll the Train': 'PIL frame painter + ffmpeg',
        'Say the Colours': 'IndexTTS-2 voice + numpy sfx + soundfont bed',
        'Assemble & Deliver': 'ffmpeg mix, mux, poster',
    },
}

STAGES = ['Episode Plan', 'Paint the Land', 'Roll the Train', 'Say the Colours', 'Assemble & Deliver']

# ── the fixed tables ─────────────────────────────────────────────────────────
#
# Eight landscapes and eight colours, so a run of eight episodes never repeats
# a picture and every colour is taught four times.  Episode k takes landscape
# row (k-1) % 8 and six colours starting at ((k-1)*2) % 8, wrapping — a two-row
# stride, so consecutive episodes share four colours and swap two.

LANDSCAPES = [
    'a green meadow with a distant blue hill and a big round sun',
    'a seaside with a small lighthouse on the rocks',
    'snowy hills with rounded pine trees',
    'a wide field of tall sunflowers',
    'gentle desert dunes with one round cactus',
    'a little farm with a red barn',
    'a calm lake with a small wooden pier',
    'an orchard of round leafy trees',
]

# (spoken name, body RGB).  Storybook-flat, high contrast against the dark
# outline, and light enough for the white highlight stripe to read.
COLOURS = [
    ('red', (228, 62, 62)),
    ('yellow', (247, 198, 46)),
    ('blue', (58, 122, 214)),
    ('green', (74, 176, 94)),
    ('orange', (243, 140, 48)),
    ('purple', (150, 96, 196)),
    ('pink', (238, 130, 176)),
    ('brown', (150, 100, 62)),
]

WAGONS_PER_EPISODE = 6
SLOT_S = 7.0  # one wagon enters every SLOT_S seconds
SPEED_PX_S = 120.0  # the train's rolling speed
ROLL_OUT_S = 5.0  # the minimum tail (and exactly what --test gets)
SAY_OFFSET_S = 1.0  # the voice names a wagon one second after it lands
VOICE = 'f01_warm_alto'

# ── the drawing ──────────────────────────────────────────────────────────────

TRACK_Y = 560
WHEEL_R = 22
WHEEL_CY = TRACK_Y - WHEEL_R
BODY_BOTTOM = WHEEL_CY - 4

ENGINE_W, ENGINE_H = 180, 124
WAGON_W, WAGON_H = 170, 96
GAP_PX = 12
UNIT = WAGON_W + GAP_PX  # 182: head-to-head spacing of the wagons

ENGINE_RGB = (28, 52, 110)  # dark blue
INK = (26, 26, 32)  # the one dark outline colour, everywhere
RAIL = (92, 84, 78)
WHEEL = (24, 24, 28)
OUTLINE_W = 5


# Distance from the front of the engine back to wagon i's right edge, and the
# head position at which wagon i is exactly fully on screen (left edge at 0).
def _wagon_offset(i):
    return ENGINE_W + GAP_PX + i * UNIT


def _head_parked(i):
    return float(_wagon_offset(i) + WAGON_W)


ROLL_DUR_S = UNIT / SPEED_PX_S  # 1.5167 s to bring one wagon in
CLEAR_S = K.W / SPEED_PX_S  # 10.667 s for a parked train to leave


def head_x(t, n_wagons, slot_end, pause_s):
    """The x of the front of the engine at time t.  The whole animation."""
    t = float(t)
    if t < slot_end:
        i = min(int(t // SLOT_S), n_wagons - 1)
        return _head_parked(i) - UNIT + SPEED_PX_S * min(t - SLOT_S * i, ROLL_DUR_S)
    parked = _head_parked(n_wagons - 1)
    dt = t - slot_end
    if dt <= pause_s:
        return parked
    return parked + SPEED_PX_S * (dt - pause_s)


def _wheel(draw, cx, cy, r, roll_px):
    """A black wheel with one spoke, rotated by how far the train has rolled."""
    import math

    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHEEL, outline=INK, width=3)
    a = roll_px / float(r)  # rolling without slipping
    for k in (0, 1):
        ang = a + k * math.pi / 2.0
        draw.line(
            [
                cx + math.cos(ang) * (r - 5),
                cy + math.sin(ang) * (r - 5),
                cx - math.cos(ang) * (r - 5),
                cy - math.sin(ang) * (r - 5),
            ],
            fill=(226, 226, 232),
            width=3,
        )
    draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(226, 226, 232))


def _smoke(base, fx, fy, t):
    """Three white puffs leaving the funnel and drifting up and back."""
    from PIL import Image, ImageDraw

    x0, y0 = int(fx) - 150, int(fy) - 210
    layer = Image.new('RGBA', (260, 230), (255, 255, 255, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = int(fx) - x0, int(fy) - y0
    for j in range(3):
        u = ((t * 0.75) + j / 3.0) % 1.0  # 0 at the funnel, 1 faded out
        r = 13.0 + 26.0 * u
        px = cx - 46.0 * u
        py = cy - 18.0 - 155.0 * u
        a = int(225 * (1.0 - u) ** 0.7)
        if a <= 2:
            continue
        d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 255, 255, a))
    base.paste(layer, (x0, y0), layer)


def _draw_track(draw):
    """Sleepers are nailed to the ground: they must NOT move with the train."""
    for x in range(-10, K.W + 60, 62):
        draw.rounded_rectangle([x, TRACK_Y + 4, x + 40, TRACK_Y + 18], 5, fill=(126, 100, 74), outline=INK, width=3)
    draw.rounded_rectangle([-8, TRACK_Y - 6, K.W + 8, TRACK_Y + 6], 6, fill=RAIL, outline=INK, width=3)


def draw_frame(land, t, colours, n_visible, slot_end, pause_s):
    """One finished 1280x720 frame: the still, the track, the train."""
    from PIL import ImageDraw

    img = land.copy()
    draw = ImageDraw.Draw(img)
    _draw_track(draw)

    hx = head_x(t, len(colours), slot_end, pause_s)

    # Wagons first, back to front, so the engine overlaps its own coupling.
    for i in range(len(colours) - 1, -1, -1):
        if i >= n_visible or t < SLOT_S * i:
            continue  # not in the film yet
        right = hx - _wagon_offset(i)
        left = right - WAGON_W
        if right < -40 or left > K.W + 40:
            continue
        rgb = colours[i][1]
        draw.rounded_rectangle(
            [left, BODY_BOTTOM - WAGON_H, right, BODY_BOTTOM], 18, fill=rgb, outline=INK, width=OUTLINE_W
        )
        draw.rounded_rectangle(
            [left + 16, BODY_BOTTOM - WAGON_H + 14, right - 16, BODY_BOTTOM - WAGON_H + 30],
            8,
            fill=tuple(min(255, c + 46) for c in rgb),
        )
        draw.line([right, BODY_BOTTOM - 26, right + GAP_PX, BODY_BOTTOM - 26], fill=INK, width=7)
        for wx in (left + 40, right - 40):
            _wheel(draw, wx, WHEEL_CY, WHEEL_R, hx)

    # The engine.
    e_right, e_left = hx, hx - ENGINE_W
    if e_right > -60 and e_left < K.W + 60:
        top = BODY_BOTTOM - ENGINE_H
        draw.rounded_rectangle([e_left, top, e_right, BODY_BOTTOM], 20, fill=ENGINE_RGB, outline=INK, width=OUTLINE_W)
        draw.rounded_rectangle(
            [e_left + 18, top + 18, e_left + 84, top + 74], 10, fill=(196, 224, 246), outline=INK, width=4
        )
        draw.rounded_rectangle(
            [e_right - 66, BODY_BOTTOM - 46, e_right - 12, BODY_BOTTOM - 12],
            8,
            fill=(214, 74, 74),
            outline=INK,
            width=4,
        )
        fx, fy = e_right - 40, top
        draw.rounded_rectangle([fx - 19, fy - 56, fx + 19, fy + 6], 8, fill=ENGINE_RGB, outline=INK, width=OUTLINE_W)
        draw.rounded_rectangle([fx - 26, fy - 68, fx + 26, fy - 48], 8, fill=(214, 74, 74), outline=INK, width=4)
        for wx in (e_left + 40, e_left + ENGINE_W // 2, e_right - 34):
            _wheel(draw, wx, WHEEL_CY, WHEEL_R, hx)
        _smoke(img, fx, fy - 68, t)
    return img


# ── the episode ──────────────────────────────────────────────────────────────


def _plan(episode, test_mode):
    """Which table rows this episode draws, and when everything happens."""
    ep = max(1, int(episode))
    land_row = (ep - 1) % len(LANDSCAPES)
    start = ((ep - 1) * 2) % len(COLOURS)
    n = 1 if test_mode else WAGONS_PER_EPISODE
    rows = [(start + j) % len(COLOURS) for j in range(n)]
    colours = [COLOURS[r] for r in rows]

    slot_end = SLOT_S * n
    if test_mode:
        roll_out = ROLL_OUT_S
    else:
        roll_out = max(ROLL_OUT_S, float(SERIES['episode_seconds']) - slot_end)
    total = slot_end + roll_out
    return {
        'episode': ep,
        'land_row': land_row,
        'landscape': LANDSCAPES[land_row],
        'colour_rows': rows,
        'colours': colours,
        'n_wagons': n,
        'slot_end': slot_end,
        'roll_out_s': roll_out,
        # Hold the finished train still until only the time it needs to leave
        # is left, so the roll-out ends on the last frame instead of leaving
        # seconds of empty landscape.
        'pause_s': max(0.0, roll_out - CLEAR_S),
        'total_s': total,
        'seed': 3000 + ep,
    }


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    log = log_fn or (lambda _m: None)
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    started = time.time()

    stills = os.path.join(out_dir, 'stills')
    clips = os.path.join(out_dir, 'clips')
    audio = os.path.join(out_dir, 'audio')
    frames = os.path.join(clips, 'frames')
    for d in (stills, clips, audio, frames):
        os.makedirs(d, exist_ok=True)

    done = []
    p = _plan(episode, test_mode)
    manifest = {
        'slug': SERIES['slug'],
        'title': SERIES['title'],
        'episode': p['episode'],
        'test_mode': bool(test_mode),
        'ok': False,
        'reason': '',
        'duration_s': 0.0,
        'files': {'episode': 'episode.mp4', 'poster': 'poster.jpg'},
        'stages_completed': done,
        'landscape': p['landscape'],
        'wagon_colours': [c[0] for c in p['colours']],
        'voice': {'engine': '', 'lines': []},
        'models_used': [],
        'licences': {
            'stills': 'FLUX.2 klein-4B — Apache-2.0',
            'speech': 'IndexTTS-2 / Chatterbox — local weights, synthetic Maya1 reference voices (Apache-2.0)',
            'music': 'MuseScore_General.sf3 — MIT',
            'effects': 'synthesised with numpy — no sample library',
        },
        'tables_used': {
            'landscape_row': p['land_row'],
            'landscape': p['landscape'],
            'colour_rows': p['colour_rows'],
            'wagon_colours': [c[0] for c in p['colours']],
        },
        'timing': {
            'slot_s': SLOT_S,
            'speed_px_s': SPEED_PX_S,
            'track_y': TRACK_Y,
            'wagon_entries_s': [SLOT_S * i for i in range(p['n_wagons'])],
            'roll_out_s': p['roll_out_s'],
            'total_s': p['total_s'],
        },
    }

    def finish(reason):
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - started, 2)
        K.write_manifest(out_dir, manifest)
        log(f'episode failed: {reason}')
        return manifest

    # ── Episode Plan ─────────────────────────────────────────────────────────
    stage(STAGES[0])
    log(f'episode {p["episode"]}: {p["landscape"]}')
    log('wagons: ' + ', '.join(c[0] for c in p['colours']))
    log(f'{p["total_s"]:.1f}s total — {p["n_wagons"]} wagon(s), {p["roll_out_s"]:.1f}s roll-out')
    done.append(STAGES[0])
    if abort():
        return finish('aborted')

    # ── Paint the Land ───────────────────────────────────────────────────────
    stage(STAGES[1])
    land_png = os.path.join(stills, 'land.png')
    prompt = f'{p["landscape"]}, a long flat empty path across the lower third for a toy train, wide view'
    if not K.render_still(prompt, land_png, seed=p['seed'], log_fn=log):
        return finish('the landscape still did not render')
    manifest['models_used'].append('FLUX.2 klein-4B (still)')
    done.append(STAGES[1])
    if abort():
        return finish('aborted')

    # ── Roll the Train ───────────────────────────────────────────────────────
    stage(STAGES[2])
    try:
        from PIL import Image
    except Exception as e:  # noqa: BLE001
        return finish(f'PIL unavailable: {type(e).__name__}: {e}')
    land = Image.open(land_png).convert('RGB')
    if land.size != (K.W, K.H):
        land = land.resize((K.W, K.H), Image.LANCZOS)

    n_frames = int(round(p['total_s'] * K.FPS))
    total_s = n_frames / float(K.FPS)
    for f in range(n_frames):
        if f % 120 == 0 and abort():
            return finish('aborted')
        t = f / float(K.FPS)
        img = draw_frame(land, t, p['colours'], p['n_wagons'], p['slot_end'], p['pause_s'])
        img.save(os.path.join(frames, f'f{f:05d}.png'))
        if f % 240 == 0:
            log(f'frames {f}/{n_frames}')
    silent = os.path.join(clips, 'train.mp4')
    if not K.frames_to_clip(os.path.join(frames, 'f%05d.png'), silent, fps=K.FPS):
        return finish('the frame sequence would not encode')
    log(f'video: {n_frames} frames, {total_s:.2f}s')
    manifest['models_used'].append('PIL frame painter (train, no model)')
    done.append(STAGES[2])
    if abort():
        return finish('aborted')

    # ── Say the Colours ──────────────────────────────────────────────────────
    stage(STAGES[3])
    tracks = []

    chug = os.path.join(audio, 'train.wav')
    if K.synth_sfx('train', chug, seconds=total_s, seed=p['seed']):
        tracks.append((chug, 0.0, -12.0))
    else:
        log('sfx: the chug did not synthesise — continuing without it')

    horn = os.path.join(audio, 'horn.wav')
    if K.synth_sfx('horn', horn, seconds=0.6, seed=p['seed'] + 1):
        tracks.append((horn, 0.5, -6.0))
        tracks.append((horn, p['slot_end'], -6.0))
    else:
        log('sfx: the horn did not synthesise — continuing without it')

    # The voice is not optional: without the colour words this is a train
    # rolling past, not a lesson.  A missing line fails the episode.
    engine = ''
    lines = []
    for i, (name, _rgb) in enumerate(p['colours']):
        if abort():
            return finish('aborted')
        wav = os.path.join(audio, f'say_{i:02d}_{name}.wav')
        got = K.say(name, wav, voice=VOICE, seed=p['seed'] + 10 + i, log_fn=log)
        if not got:
            manifest['voice'] = {'engine': engine, 'lines': lines}
            return finish(f'the voice produced no line for "{name}"')
        engine = engine or got
        at = SLOT_S * i + SAY_OFFSET_S
        lines.append({'wagon': i, 'text': name, 'at_s': at, 'engine': got})
        tracks.append((wav, at, 0.0))
    manifest['voice'] = {'engine': engine, 'lines': lines}
    manifest['models_used'].append(f'{engine} (speech, {VOICE})')
    log(f'voice: {len(lines)} line(s) through {engine}')

    bed = os.path.join(audio, 'music.wav')
    if K.music_bed(bed, seconds=total_s, mood='marching', age_band=SERIES['age_band'], seed=p['seed'], log_fn=log):
        tracks.append((bed, 0.0, -8.0))
        manifest['models_used'].append('MuseScore_General.sf3 (music bed)')
    else:
        log('music: no bed this episode — continuing without it')
    done.append(STAGES[3])
    if abort():
        return finish('aborted')

    # ── Assemble & Deliver ───────────────────────────────────────────────────
    stage(STAGES[4])
    mixed = os.path.join(audio, 'mix.wav')
    if not K.mix_audio(tracks, mixed, total_s):
        return finish('the audio mix failed')
    ep_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not K.mux(silent, mixed, ep_mp4):
        return finish('the mux failed')
    poster = os.path.join(out_dir, 'poster.jpg')
    if not K.write_poster(ep_mp4, poster):
        return finish('the poster could not be taken')

    info = K.probe(ep_mp4)
    if info['duration'] < 5.0 or not info['has_audio']:
        return finish(f'the delivered mp4 is wrong: {info}')
    done.append(STAGES[4])

    manifest['ok'] = True
    manifest['reason'] = 'delivered'
    manifest['duration_s'] = round(info['duration'], 2)
    manifest['build_s'] = round(time.time() - started, 2)
    manifest['probe'] = info
    K.write_manifest(out_dir, manifest)
    log(f'delivered {ep_mp4} ({info["duration"]:.2f}s, {info["w"]}x{info["h"]})')
    return manifest


if __name__ == '__main__':
    sys.exit(K.run_cli(sys.modules[__name__]))
