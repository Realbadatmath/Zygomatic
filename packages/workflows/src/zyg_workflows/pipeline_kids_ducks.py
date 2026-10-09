# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_ducks.py — "Counting Ducks", the counting series.

One klein-painted pond per episode; N rubber ducks drop into it one at a time,
each with a steel-drum note and a spoken number, and at the end the whole raft
bobs while the voice names the total.  N = min(3 + episode, 10); a --test run
is ONE duck, which is the smallest thing that still proves every stage.

WHY THE DUCKS ARE DRAWN AND NOT GENERATED.  A counting programme is only worth
watching if the thing on screen at "four" is the thing that was there at
"three" plus exactly one more.  An image model re-rolls the whole picture when
the prompt changes — the first counting runs in this house produced a yellow
duck, then three quite different birds — so the ducks here are PIL: a fixed
10-slot grid, one deterministic shape, composited over a single generated
background.  The model paints the pond, arithmetic paints the ducks.

LONG EPISODES ARE ROUNDS.  The single-pond episode is 10 + 5*N seconds, 60 s
at most, because ten is where the count words and the duck slots stop.  A
2-3 minute episode is therefore several ROUNDS — a new pond, a new count —
joined by a short dissolve: ``ZYG_KIDS_DUCKS_ROUNDS=5,7,10`` (or
``run_episode(..., rounds=[5, 7, 10])``) gives 35 + 45 + 60 = 140 s.  Every
round re-uses the same drawn duck, the same slots and the same spoken words,
so a repeated number is synthesised once and placed many times.

COST: zero paid calls.  klein-4B for the pond (Apache-2.0), CC0 steel-drum
one-shots for the notes, the MIT soundfont for the bed, the local speech
workers for the numbers.  Everything spoken or shown comes from the fixed
tables below.
"""

from __future__ import annotations

import math
import os
import sys
import time

from zyg_workflows import kids_series_common as KC

# ── the series card the board reads ──────────────────────────────────────────

SERIES = {
    'slug': 'ducks',
    'title': 'Counting Ducks',
    'tagline': 'One duck, two ducks — every number lands with a splash.',
    'voice': True,
    'characters': True,  # ducks are characters; drawn, not generated
    'gpu': True,  # one klein still per episode
    'age_band': 'preschool',
    'episode_seconds': 60,  # the full run, N=10: 10 + 5*N
    'episodes': 10,
    'agents': {
        'Episode Plan': 'fixed tables',
        'Paint the Pond': 'FLUX.2 klein-4B',
        'Ducks Arrive': 'PIL compositor',
        'Count Out Loud': 'IndexTTS-2 + CC0 steel drum',
        'Assemble & Deliver': 'ffmpeg',
    },
}

STAGES = ['Episode Plan', 'Paint the Pond', 'Ducks Arrive', 'Count Out Loud', 'Assemble & Deliver']

# ── fixed tables ─────────────────────────────────────────────────────────────

# The pond.  One prompt, one seed per episode: the same water every time the
# same episode is rebuilt, and no lettering (the voice says the numbers).
POND_PROMPT = (
    'a calm blue pond with lily pads and reeds, green grass banks, big friendly sun, empty pond with room in the middle'
)

# Copied from kids_video_service._COUNT_WORDS (line 303) rather than imported:
# that module resolves a checkpoint at import time and this one must stay
# importable on a CPU-only box.
COUNT_WORDS = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

# A pentatonic climb, so any prefix of it is consonant — episode 4 stops at
# 'G4' and still sounds finished.
NOTE_PITCHES = ['C4', 'D4', 'E4', 'G4', 'A4', 'C5', 'D5', 'E5', 'G5', 'A5']

# Ten landing places across the pond's middle band (y 380-520), left to right
# so the raft reads in counting order, with the row staggered so no duck sits
# squarely behind its neighbour.  (x, y) is the centre of the body.
#
# The grid stops well short of the frame edges and leans to the lower half of
# the band because the generated pond is an ellipse: its water is widest across
# the middle, and a slot in the top corners lands a duck on the grass bank.
DUCK_SLOTS = [
    (280, 470),
    (375, 505),
    (470, 420),
    (565, 495),
    (660, 445),
    (755, 515),
    (850, 425),
    (945, 490),
    (1040, 440),
    (1135, 500),
]

# ── shape and timing ─────────────────────────────────────────────────────────

BODY_COLOUR = '#FFD23F'
BEAK_COLOUR = '#F58A07'
EYE_COLOUR = '#1A1A1A'
OUTLINE = '#2B2B2B'
OUTLINE_W = 4

# The intro is short on purpose: write_poster takes the thumbnail at 1.0 s, so
# duck one must already be falling by then or the series' own picture is an
# empty pond.  Intro + outro stay at 10 s together, so the episode is 10 + 5*N.
INTRO_S = 0.6  # empty pond before the first duck
PER_DUCK_S = 5.0  # drop, note, number, breathe
OUTRO_S = 9.4  # the whole raft bobbing, then the total
DROP_S = 0.6  # the fall
BOUNCE_S = 0.35  # the little rebound after landing
DROP_HEIGHT = 320  # px above the slot the duck starts at
BOB_PX = 6.0  # idle bob amplitude

NOTE_DB = -6.0
SPLASH_DB = -12.0
BED_DB = -10.0
VOICE_DELAY_S = 0.4  # the number lands just after the note

VOICE = 'f01_warm_alto'

# Round-to-round variety without touching the count: the pond's time of day.
# Only used when an episode has more than one round.
ROUND_SKIES = [
    'early morning, soft pink and gold sky',
    'bright midday, clear blue sky',
    'golden evening light, warm orange sky',
    'late afternoon, a few fluffy white clouds',
]
DISSOLVE_S = 0.6  # the pond-to-pond blend at the start of a later round
CLOSER_LINE = 'Well done!'
CLOSER_AT = 5.0  # seconds into the LAST outro, after the last total


def round_seconds(n):
    return INTRO_S + PER_DUCK_S * int(n) + OUTRO_S


def rounds_for(episode, test_mode=False):
    """The counts this episode plays, in order.  One round unless the env says
    otherwise; a test is always one duck in one pond."""
    if test_mode:
        return [1]
    env = os.environ.get('ZYG_KIDS_DUCKS_ROUNDS', '').strip()
    if env:
        vals = [max(1, min(len(COUNT_WORDS), int(x))) for x in env.replace(';', ',').split(',') if x.strip().isdigit()]
        if vals:
            return vals
    return [episode_count(episode)]


def episode_count(episode, test_mode=False):
    """How many ducks this episode counts to.  A test is one duck."""
    if test_mode:
        return 1
    return max(1, min(3 + int(episode), 10))


def _draw_duck(draw, cx, cy):
    """One rubber duck, 120 px wide, anchored on the centre of its body."""
    # Beak first so the head circle covers where it joins.
    draw.polygon([(cx + 44, cy - 28), (cx + 68, cy - 21), (cx + 44, cy - 12)], fill=BEAK_COLOUR, outline=OUTLINE)
    draw.ellipse([cx - 52, cy - 18, cx + 34, cy + 34], fill=BODY_COLOUR, outline=OUTLINE, width=OUTLINE_W)
    draw.ellipse([cx + 8, cy - 46, cx + 56, cy + 2], fill=BODY_COLOUR, outline=OUTLINE, width=OUTLINE_W)
    draw.ellipse([cx + 36, cy - 36, cx + 44, cy - 28], fill=EYE_COLOUR)


def _duck_offset(t, enter_t, slot):
    """Vertical offset of duck `slot` at time `t`, or None if it is not in yet.

    Three regimes, in order: the fall (accelerating, from DROP_HEIGHT up), a
    damped rebound, then the idle bob every duck shares for the rest of the
    episode.
    """
    if t < enter_t:
        return None
    u = (t - enter_t) / DROP_S
    if u < 1.0:
        return -DROP_HEIGHT * (1.0 - u) ** 2
    v = (t - enter_t - DROP_S) / BOUNCE_S
    if v < 1.0:
        return -22.0 * math.sin(math.pi * v) * math.exp(-1.8 * v)
    return BOB_PX * math.sin(t + slot)


_LICENCES = None


def _licence_for(path):
    """The library's licence_id for a one-shot we already know is CC0."""
    global _LICENCES
    if _LICENCES is None:
        try:
            _LICENCES = {r['path']: r['license_id'] for r in KC._instruments()}
        except Exception:  # noqa: BLE001
            _LICENCES = {}
    return _LICENCES.get(path, 'cc0')


def _note_for(index, seed):
    """The steel-drum one-shot for duck `index`, or a piano note if that pitch
    is not in the CC0 slice.  Returns (path, pitch, family) or (None, .., '')."""
    pitch = NOTE_PITCHES[index % len(NOTE_PITCHES)]
    path = KC.instrument_shot('SteelDrum', pitch, seed=seed)
    if path:
        return path, pitch, 'steeldrum'
    path = KC.instrument_shot('piano', pitch, seed=seed)
    if path:
        return path, pitch, 'piano'
    return None, pitch, ''


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None, rounds=None):
    """Build one episode of Counting Ducks into `out_dir`.

    ``rounds`` is a list of counts, one pond each; None means ``rounds_for``.
    """
    log = log_fn or (lambda _m: None)
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    t_start = time.time()

    stills = os.path.join(out_dir, 'stills')
    clips = os.path.join(out_dir, 'clips')
    audio = os.path.join(out_dir, 'audio')
    frames = os.path.join(clips, 'frames')
    for d in (stills, clips, audio, frames):
        os.makedirs(d, exist_ok=True)

    episode = int(episode)
    counts = [max(1, min(len(COUNT_WORDS), int(c))) for c in (rounds or rounds_for(episode, test_mode))]
    multi = len(counts) > 1
    seed = 4000 + episode
    done = []

    plan = []
    t = 0.0
    for i, n in enumerate(counts):
        secs = round_seconds(n)
        plan.append(
            {
                'index': i,
                'count': n,
                'start_s': round(t, 3),
                'seconds': round(secs, 3),
                'outro_at': INTRO_S + PER_DUCK_S * n,
                'seed': seed + 100 * i,
                'sky': ROUND_SKIES[i % len(ROUND_SKIES)] if multi else '',
                'pond': os.path.join(stills, f'pond_{i + 1:02d}.png'),
            }
        )
        t += secs
    total_s = t
    n_max = max(counts)
    words = COUNT_WORDS[:n_max]

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
        'voice': {'engine': '', 'lines': 0, 'placements': 0},
        'models_used': [],
        'licences': {},
        'tables_used': {},
        'count': n_max,
        'rounds': [{k: v for k, v in r.items() if k != 'pond'} for r in plan],
        'number_words': words,
        'note_files': [],
    }

    def fail(reason):
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - t_start, 2)
        log(f'ducks: FAILED — {reason}')
        KC.write_manifest(out_dir, manifest)
        return manifest

    # ── Episode Plan ─────────────────────────────────────────────────────────
    stage('Episode Plan')
    manifest['tables_used'] = {
        'pond_prompt': POND_PROMPT,
        'round_skies': [r['sky'] for r in plan],
        'count_words': words,
        'note_pitches': NOTE_PITCHES[:n_max],
        'duck_slots': DUCK_SLOTS[:n_max],
    }
    log(
        f'ducks: episode {episode}{" (test)" if test_mode else ""} — '
        f'{len(counts)} round(s) {counts}, {total_s:.1f}s, seed {seed}'
    )
    done.append('Episode Plan')
    if abort():
        return fail('aborted before the pond was painted')

    # ── Paint the Pond ───────────────────────────────────────────────────────
    stage('Paint the Pond')
    for r in plan:
        prompt = POND_PROMPT + (f', {r["sky"]}' if r['sky'] else '')
        if not KC.render_still(prompt, r['pond'], w=KC.W, h=KC.H, seed=r['seed'], log_fn=log):
            return fail(f'pond {r["index"] + 1} did not render')
        log(f'ducks: pond {r["index"] + 1} painted -> {os.path.relpath(r["pond"], out_dir)}')
        if abort():
            return fail('aborted while the ponds were painted')
    manifest['models_used'].append('FLUX.2 klein-4B')
    manifest['licences']['picture'] = 'Apache-2.0 (FLUX.2 klein-4B)'
    done.append('Paint the Pond')

    # ── Ducks Arrive ─────────────────────────────────────────────────────────
    #
    # Every frame is one round's background with its ducks drawn over it, so
    # the pond never flickers and the only thing that moves is the count.  A
    # later round opens on a short blend from the previous round's last frame.
    stage('Ducks Arrive')
    try:
        from PIL import Image, ImageDraw
    except Exception as e:  # noqa: BLE001
        return fail(f'PIL unavailable ({type(e).__name__}: {e})')

    bgs = []
    for r in plan:
        bg = Image.open(r['pond']).convert('RGB')
        if bg.size != (KC.W, KC.H):
            bg = bg.resize((KC.W, KC.H), Image.LANCZOS)
        bgs.append(bg)

    n_frames = int(round(total_s * KC.FPS))
    cur = 0
    prev_last = None
    last_img = None
    for f in range(n_frames):
        if f % (KC.FPS * 5) == 0 and abort():
            return fail('aborted while the ducks were arriving')
        t = f / float(KC.FPS)
        while cur + 1 < len(plan) and t >= plan[cur]['start_s'] + plan[cur]['seconds']:
            cur += 1
            prev_last = last_img
        r = plan[cur]
        tl = t - r['start_s']
        img = bgs[cur].copy()
        draw = ImageDraw.Draw(img)
        for k in range(r['count']):
            off = _duck_offset(tl, INTRO_S + k * PER_DUCK_S, k)
            if off is None:
                continue
            cx, cy = DUCK_SLOTS[k]
            _draw_duck(draw, cx, int(round(cy + off)))
        if prev_last is not None and cur > 0 and tl < DISSOLVE_S:
            img = Image.blend(prev_last, img, max(0.0, min(1.0, tl / DISSOLVE_S)))
        img.save(os.path.join(frames, f'f_{f:05d}.jpg'), quality=88)
        last_img = img
    log(f'ducks: {n_frames} frames composited over {len(plan)} pond(s)')

    silent_mp4 = os.path.join(clips, 'ducks_silent.mp4')
    if not KC.frames_to_clip(os.path.join(frames, 'f_%05d.jpg'), silent_mp4, fps=KC.FPS):
        return fail('the frame sequence would not encode')
    done.append('Ducks Arrive')
    if abort():
        return fail('aborted before the counting')

    # ── Count Out Loud ───────────────────────────────────────────────────────
    stage('Count Out Loud')
    tracks = []
    engine = ''
    lines = 0
    placements = 0
    spoken = {}  # text -> wav, said once

    def say_once(text, name, seed_):
        nonlocal engine, lines
        if text in spoken:
            return spoken[text]
        wav = os.path.join(audio, name)
        got = KC.say(text, wav, voice=VOICE, seed=seed_, log_fn=log)
        if not got:
            return None
        engine = engine or got
        lines += 1
        spoken[text] = wav
        return wav

    for r in plan:
        rs = r['start_s']
        n = r['count']
        bed_wav = os.path.join(audio, f'bed_{r["index"] + 1:02d}.wav')
        if KC.music_bed(
            bed_wav, seconds=r['seconds'], mood='playful', age_band=SERIES['age_band'], seed=r['seed'], log_fn=log
        ):
            tracks.append((bed_wav, rs, BED_DB))
            if 'MuseScore_General.sf3 soundfont' not in manifest['models_used']:
                manifest['models_used'].append('MuseScore_General.sf3 soundfont')
            manifest['licences']['music'] = 'MIT (MuseScore_General.sf3)'
        else:
            log(f'ducks: no music bed for round {r["index"] + 1}')

        for k in range(n):
            land = rs + INTRO_S + k * PER_DUCK_S + DROP_S
            splash = os.path.join(audio, f'splash_{r["index"] + 1:02d}_{k + 1:02d}.wav')
            if KC.synth_sfx('splash', splash, seconds=0.9, seed=r['seed'] + k):
                tracks.append((splash, land, SPLASH_DB))
            note, pitch, family = _note_for(k, r['seed'] + k)
            if note:
                tracks.append((note, land, NOTE_DB))
                manifest['note_files'].append(
                    {
                        'round': r['index'] + 1,
                        'pitch': pitch,
                        'family': family,
                        'path': note,
                        'license_id': _licence_for(note),
                    }
                )
            else:
                log(f'ducks: no CC0 one-shot for {pitch} — duck {k + 1} lands dry')
            wav = say_once(COUNT_WORDS[k], f'say_{k + 1:02d}.wav', 7 + k)
            if not wav:
                return fail(f'the voice would not say "{COUNT_WORDS[k]}"')
            tracks.append((wav, land + VOICE_DELAY_S, 0.0))
            placements += 1

        # "one duck!", not "one ducks!" — a counting programme that cannot
        # count its own plurals teaches the wrong lesson.
        total_line = f'{COUNT_WORDS[n - 1]} duck{"" if n == 1 else "s"}!'
        wav = say_once(total_line, f'say_total_{n:02d}.wav', 7 + n)
        if not wav:
            return fail(f'the voice would not say "{total_line}"')
        tracks.append((wav, rs + r['outro_at'] + 1.0, 0.0))
        placements += 1

    if multi:
        last = plan[-1]
        wav = say_once(CLOSER_LINE, 'say_closer.wav', 99)
        if wav:
            tracks.append((wav, last['start_s'] + last['outro_at'] + CLOSER_AT, 0.0))
            placements += 1

    manifest['voice'] = {'engine': engine, 'lines': lines, 'placements': placements}
    manifest['models_used'].append(f'speech: {engine}')
    manifest['licences']['voice'] = 'local worker, Apache-2.0 voice seeds'
    manifest['licences']['notes'] = 'CC0 / public-domain instrument one-shots'
    log(f'ducks: {lines} line(s) synthesised via {engine}, {placements} placed')
    done.append('Count Out Loud')
    if abort():
        return fail('aborted before assembly')

    # ── Assemble & Deliver ───────────────────────────────────────────────────
    stage('Assemble & Deliver')
    mix_wav = os.path.join(audio, 'mix.wav')
    if not KC.mix_audio(tracks, mix_wav, total_s):
        return fail('the audio mix failed')

    episode_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not KC.mux(silent_mp4, mix_wav, episode_mp4):
        return fail('the mux of picture and sound failed')

    poster_jpg = os.path.join(out_dir, 'poster.jpg')
    if not KC.write_poster(episode_mp4, poster_jpg):
        return fail('the poster frame could not be taken')

    info = KC.probe(episode_mp4)
    manifest['duration_s'] = round(info['duration'], 2)
    manifest['wall_s'] = round(time.time() - t_start, 1)
    if not info['has_audio']:
        return fail('the delivered episode has no audio stream')
    if (info['w'], info['h']) != (KC.W, KC.H):
        return fail(f'the delivered episode is {info["w"]}x{info["h"]}, not {KC.W}x{KC.H}')
    if info['duration'] < 5.0:
        return fail(f'the delivered episode is only {info["duration"]:.2f}s')
    if abs(info['duration'] - total_s) > 1.0:
        return fail(f'the delivered episode is {info["duration"]:.2f}s, planned {total_s:.2f}s')

    done.append('Assemble & Deliver')
    manifest['ok'] = True
    manifest['reason'] = ''
    log(f'ducks: delivered {info["duration"]:.2f}s, rounds {counts}')
    KC.write_manifest(out_dir, manifest)
    return manifest


if __name__ == '__main__':
    sys.exit(KC.run_cli(sys.modules[__name__]))
