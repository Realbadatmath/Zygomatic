# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_whichsound.py — "Which Instrument?", the guess-the-sound series.

A round is a game with two halves.  For nine seconds nothing is on screen but a
big friendly question mark, bobbing, while three notes of one instrument play
and a tick counts the seconds away.  Then a whoosh, and the instrument itself is
revealed as a picture-book still while the same three notes play again and a
voice names it.  Three rounds make a sixty-six second episode.

WHY INSTRUMENTS AND NOT SOUND EFFECTS.  The obvious version of this series uses
the sfx or foley libraries — and cannot ship.  Their only CC0 content is
screams, crowds and battle, and everything else on those shelves carries a 344
Audio EULA that forbids AI use.  The instruments library is the one shelf on
this box that is both kid-safe and licence-clean: 66,028 records in, ~44,000
cc0 / public-domain and AI-permitting records out.  So the game is "which
instrument made that sound", and every note in an episode is attributable.

THE QUESTION CARD IS DRAWN, NOT GENERATED.  House rule for this family is that
pictures never contain lettering — the voice says the words.  A guess-the-sound
show needs one glyph on screen, so that glyph is drawn with PIL from a font
file: it is typography, not a diffusion model's idea of a letter, and it is the
only place in the series where a character appears in the frame.

PITCHES ARE A REQUEST, NOT A GUARANTEE.  Half the instrument packs here carry
no pitch metadata at all, and ``instrument_shot`` answers a pitch it cannot
satisfy by handing back any note of the family.  Asking for three pitches that
do not exist therefore yields the SAME file three times — three identical
"notes" and a round that gives the game away.  So the pitch set is checked
against the library at plan time; a family that cannot honour it is demoted to
three distinct unpitched hits and the demotion is recorded in the manifest.

Everything that touches a model, a codec or the job board lives in
kids_series_common; this file owns the table and the shape of a round.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from zyg_workflows import kids_series_common as KS

SERIES = {
    'slug': 'whichsound',
    'title': 'Which Instrument?',
    'tagline': 'Three notes, one mystery instrument — listen, guess, and meet it.',
    'voice': True,
    'characters': False,
    'gpu': True,
    'age_band': 'preschool',
    'episode_seconds': 66,
    'episodes': 10,
    'agents': {
        'Episode Plan': 'fixed instrument table + library resolver',
        'Pick the Sounds': 'CC0 instrument one-shots + numpy effects',
        'Paint the Reveal': 'FLUX.2 klein-4B + PIL question card',
        'Name It Out Loud': 'IndexTTS-2 / Chatterbox',
        'Assemble & Deliver': 'ffmpeg',
    },
}

STAGES = [
    'Episode Plan',
    'Pick the Sounds',
    'Paint the Reveal',
    'Name It Out Loud',
    'Assemble & Deliver',
]

# name | asset-library family substring | three pitches (None = unpitched) | picture
INSTRUMENTS = (
    ('piano', 'Osiris_Piano', ('C4', 'E4', 'G4'), 'a shiny black upright piano with white keys'),
    ('drums', 'virtuosity_drums', None, 'a bright red drum kit with golden cymbals'),
    ('cello', 'bigcat.cello', ('C3', 'G3', 'C4'), 'a warm brown cello with a bow'),
    ('steel drum', 'SteelDrum', ('C4', 'E4', 'G4'), 'a silver steel drum with a wooden stand'),
    ('saxophone', 'bear-sax', ('D4', 'F4', 'A4'), 'a golden saxophone'),
    ('tuba', 'war-tuba', ('C2', 'G2', 'C3'), 'a big shiny brass tuba'),
    ('guitar', 'shinyguitar', ('E3', 'A3', 'D4'), 'a wooden acoustic guitar'),
    ('double bass', 'dsmolken.double-bass', ('E2', 'A2', 'D3'), 'a tall brown double bass'),
    ('zither', 'hungarian_zither', ('C4', 'E4', 'G4'), 'a flat wooden zither with many strings'),
    ('water glasses', 'glasses of water', None, 'a row of glasses of water on a table'),
)

# The round, in seconds.  The card and the reveal overlap by one crossfade, so
# CARD + REVEAL - XFADE must equal ROUND or every audio cue after the first
# round lands late.
CARD_SECONDS = 9.5
REVEAL_SECONDS = 13.0
XFADE = 0.5
ROUND_SECONDS = CARD_SECONDS + REVEAL_SECONDS - XFADE  # 22.0

NOTE_TIMES_HIDDEN = (1.5, 3.5, 5.5)
NOTE_TIMES_REVEAL = (10.5, 12.5, 14.5)
WHOOSH_AT = 9.0
SAY_AT = 16.0

BED_DB = -12.0
TICK_DB = -20.0
WHOOSH_DB = -6.0
NOTE_DB = 0.0

VOICE = 'm02_bright_tenor'
FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


# ── the question card ────────────────────────────────────────────────────────


def _sky(w, h):
    """A pale sky with two soft clouds, drawn once and reused for every frame."""
    img = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(img)
    top, bottom = (168, 212, 240), (228, 244, 253)
    for y in range(h):
        f = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[c] + (bottom[c] - top[c]) * f) for c in range(3)))
    for cx, cy, r in ((250, 150, 78), (325, 162, 96), (395, 152, 70), (960, 205, 62), (1030, 195, 84), (1098, 208, 58)):
        d.ellipse([cx - r, cy - r * 0.62, cx + r, cy + r * 0.62], fill=(255, 255, 255))
    return img


def _question_glyph(size):
    """The '?' as an RGBA sprite: white fill, dark outline, cropped to its ink.

    Rendered once and pasted per frame.  Re-running the text layout 228 times
    is the difference between a card that builds in a second and one that
    builds in a minute.
    """
    font = ImageFont.truetype(FONT_PATH, size)
    pad = size
    tmp = Image.new('RGBA', (size * 2, size * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    d.text(
        (pad, pad),
        '?',
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=max(6, size // 26),
        stroke_fill=(38, 50, 72, 255),
        anchor='mm',
    )
    return tmp.crop(tmp.getbbox())


def _build_card_frames(out_dir, seconds, should_abort):
    """Write the bobbing question card as a frame sequence; return the pattern."""
    os.makedirs(out_dir, exist_ok=True)
    sky = _sky(KS.W, KS.H)
    glyph = _question_glyph(430)
    gx = (KS.W - glyph.width) // 2
    gy = (KS.H - glyph.height) // 2 + 20
    n = max(1, int(round(float(seconds) * KS.FPS)))
    for i in range(n):
        if should_abort and i % 24 == 0 and should_abort():
            return None
        t = i / float(KS.FPS)
        bob = int(round(26.0 * math.sin(2.0 * math.pi * t / 2.2)))
        frame = sky.copy()
        frame.paste(glyph, (gx, gy + bob), glyph)
        frame.save(os.path.join(out_dir, f'card_{i:04d}.png'))
    return os.path.join(out_dir, 'card_%04d.png')


# ── the instrument table, resolved against the library ───────────────────────

_LICENCES = None


def _licence_of(path):
    """The library's licence_id for a one-shot we already picked."""
    global _LICENCES
    if _LICENCES is None:
        _LICENCES = {r['path']: r['license_id'] for r in KS._instruments()}
    return _LICENCES.get(path, 'cc0')


def _pitch_in_library(family_substr, pitch):
    fam = str(family_substr).lower()
    want = str(pitch).lower()
    return any(r['pitch'].lower() == want for r in KS._instruments() if fam in r['instrument'])


def _distinct_shots(family_substr, seed0, count=3):
    """`count` DIFFERENT one-shots from one family.

    instrument_shot is deterministic in its seed, so distinctness has to be
    walked for rather than hoped for; every family here has hundreds of files,
    so the walk ends within a few steps.
    """
    picked = []
    for seed in range(int(seed0), int(seed0) + 500):
        p = KS.instrument_shot(family_substr, None, seed=seed)
        if p and p not in picked:
            picked.append(p)
            if len(picked) >= count:
                break
    return picked


def _episode_rows(episode, test_mode):
    """(row_index, row) for this episode — one row in test mode, else three."""
    if test_mode:
        return [(0, INSTRUMENTS[0])]
    base = (max(1, int(episode)) - 1) * 3
    return [((base + i) % len(INSTRUMENTS), INSTRUMENTS[(base + i) % len(INSTRUMENTS)]) for i in range(3)]


def _plan_rounds(episode, test_mode, log):
    """Resolve every round's sound files before a single second is rendered."""
    rounds = []
    for i, (idx, (name, family, pitches, picture)) in enumerate(_episode_rows(episode, test_mode)):
        seed0 = 9000 + int(episode) * 10 + i
        wanted = list(pitches) if pitches else None
        fallback = ''
        if wanted:
            missing = [p for p in wanted if not _pitch_in_library(family, p)]
            if missing:
                # A pitch the pack does not carry is answered with any note of
                # the family, so asking for three of them yields one file three
                # times.  Demote the whole row rather than ship a round whose
                # "three notes" are identical.
                fallback = f'pitches not in the library: {", ".join(missing)}'
                log(f'plan: {name} — {fallback}; using three unpitched hits')
                wanted = None
        if wanted:
            files = [KS.instrument_shot(family, p, seed=seed0 + j) for j, p in enumerate(wanted)]
        else:
            files = _distinct_shots(family, seed0)
        files = [f for f in files if f]
        if len(files) < 3:
            return None, f'{name}: only {len(files)} usable one-shots in {family}'
        rounds.append(
            {
                'name': name,
                'family': family,
                'table_row': idx,
                'picture': picture,
                'pitches': wanted,
                'pitch_fallback': fallback,
                'seed': seed0,
                'files': [{'path': f, 'license_id': _licence_of(f)} for f in files[:3]],
                'still': '',
            }
        )
        log(f'plan: round {i + 1} = {name} ({family}), pitches={wanted or "any"}, {len(files[:3])} one-shots')
    return rounds, ''


# ── the episode ──────────────────────────────────────────────────────────────


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    log = log_fn or (lambda _m: None)
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    started = time.time()

    stills = os.path.join(out_dir, 'stills')
    clips = os.path.join(out_dir, 'clips')
    audio = os.path.join(out_dir, 'audio')
    for d in (stills, clips, audio):
        os.makedirs(d, exist_ok=True)

    unet, steps, cfg = KS.klein_settings()
    done = []
    manifest = {
        'slug': SERIES['slug'],
        'title': SERIES['title'],
        'episode': int(episode),
        'test_mode': bool(test_mode),
        'ok': False,
        'reason': '',
        'duration_s': 0.0,
        'files': {'episode': 'episode.mp4', 'poster': 'poster.jpg'},
        'stages_completed': done,
        'voice': {'engine': '', 'lines': []},
        'models_used': [
            f'FLUX.2 klein-4B ({unet}, {steps} steps, cfg {cfg}) — Apache-2.0',
            'MuseScore_General.sf3 via fluidsynth — MIT',
            'IndexTTS-2 / Chatterbox (local worker)',
        ],
        'licences': [
            'instrument one-shots: cc0 / public-domain only, no_ai_training excluded',
            'pictures: FLUX.2 klein-4B, Apache-2.0, licence-attested per submit',
            'music bed: MuseScore_General.sf3, MIT',
        ],
        'tables_used': [],
        'rounds': [],
    }

    def _bail(reason):
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - started, 2)
        log(f'FAILED: {reason}')
        KS.write_manifest(out_dir, manifest)
        return manifest

    # ── Episode Plan ─────────────────────────────────────────────────────────
    stage(STAGES[0])
    rounds, why = _plan_rounds(int(episode), bool(test_mode), log)
    if not rounds:
        return _bail(why or 'no rounds could be planned')
    manifest['rounds'] = rounds
    manifest['tables_used'] = [{'table': 'INSTRUMENTS', 'row': r['table_row'], 'name': r['name']} for r in rounds]
    total_s = ROUND_SECONDS * len(rounds)
    done.append(STAGES[0])
    if abort():
        return _bail('aborted after the plan')

    # ── Pick the Sounds ──────────────────────────────────────────────────────
    stage(STAGES[1])
    for i, rnd in enumerate(rounds):
        for j, f in enumerate(rnd['files']):
            local = os.path.join(audio, f'r{i}_note{j}.wav')
            shutil.copy(f['path'], local)
            f['wav'] = local
    tick = os.path.join(audio, 'tick.wav')
    whoosh = os.path.join(audio, 'whoosh.wav')
    if not KS.synth_sfx('tick', tick, seconds=0.15, seed=3):
        return _bail('the tick effect could not be synthesised')
    if not KS.synth_sfx('whoosh', whoosh, seconds=0.5, seed=5):
        return _bail('the whoosh effect could not be synthesised')
    bed = os.path.join(audio, 'bed.wav')
    if not KS.music_bed(
        bed, seconds=total_s, mood='playful', age_band=SERIES['age_band'], seed=int(episode) * 7, log_fn=log
    ):
        return _bail('the music bed could not be rendered')
    log(f'sounds: {len(rounds) * 3} one-shots, a tick, a whoosh and a {total_s:.0f}s bed')
    done.append(STAGES[1])
    if abort():
        return _bail('aborted after the sounds')

    # ── Paint the Reveal ─────────────────────────────────────────────────────
    stage(STAGES[2])
    round_clips = []
    for i, rnd in enumerate(rounds):
        card_dir = os.path.join(stills, f'card_r{i}')
        pattern = _build_card_frames(card_dir, CARD_SECONDS, abort)
        if not pattern:
            return _bail('aborted while drawing the question card')
        card_mp4 = os.path.join(clips, f'card_r{i}.mp4')
        if not KS.frames_to_clip(pattern, card_mp4):
            return _bail(f'round {i + 1}: the question card would not encode')

        png = os.path.join(stills, f'reveal_r{i}.png')
        if not KS.render_still(rnd['picture'], png, seed=rnd['seed'], log_fn=log):
            return _bail(f'round {i + 1}: no still for {rnd["name"]}')
        rnd['still'] = os.path.relpath(png, out_dir)
        reveal_mp4 = os.path.join(clips, f'reveal_r{i}.mp4')
        if not KS.zoompan_clip(png, reveal_mp4, REVEAL_SECONDS, direction='in'):
            return _bail(f'round {i + 1}: the reveal move would not encode')

        joined = os.path.join(clips, f'round_{i}.mp4')
        if not KS.concat_clips([card_mp4, reveal_mp4], joined, xfade=XFADE):
            return _bail(f'round {i + 1}: card and reveal would not join')
        got = KS.probe(joined)['duration']
        log(f'reveal: round {i + 1} ({rnd["name"]}) is {got:.2f}s')
        round_clips.append(joined)
        if abort():
            return _bail('aborted during the pictures')
    done.append(STAGES[2])

    # ── Name It Out Loud ─────────────────────────────────────────────────────
    stage(STAGES[3])
    engine = ''
    for i, rnd in enumerate(rounds):
        text = f'It is a {rnd["name"]}!'
        wav = os.path.join(audio, f'say_r{i}.wav')
        got = KS.say(text, wav, voice=VOICE, seed=7 + i, log_fn=log)
        if not got:
            return _bail(f'round {i + 1}: no speech engine would say "{text}"')
        engine = engine or got
        rnd['line'] = text
        manifest['voice']['lines'].append(
            {
                'text': text,
                'wav': os.path.relpath(wav, out_dir),
                'at_s': round(i * ROUND_SECONDS + SAY_AT, 2),
                'voice': VOICE,
            }
        )
        log(f'voice: {engine} said "{text}"')
    manifest['voice']['engine'] = engine
    done.append(STAGES[3])
    if abort():
        return _bail('aborted after the voice')

    # ── Assemble & Deliver ───────────────────────────────────────────────────
    stage(STAGES[4])
    tracks = [(bed, 0.0, BED_DB)]
    for i, rnd in enumerate(rounds):
        base = i * ROUND_SECONDS
        for k in range(9):  # one tick a second while hidden
            tracks.append((tick, base + k, TICK_DB))
        for j, at in enumerate(NOTE_TIMES_HIDDEN):
            tracks.append((rnd['files'][j]['wav'], base + at, NOTE_DB))
        tracks.append((whoosh, base + WHOOSH_AT, WHOOSH_DB))
        for j, at in enumerate(NOTE_TIMES_REVEAL):
            tracks.append((rnd['files'][j]['wav'], base + at, NOTE_DB))
        tracks.append((os.path.join(audio, f'say_r{i}.wav'), base + SAY_AT, 0.0))

    mixed = os.path.join(audio, 'mix.wav')
    if not KS.mix_audio(tracks, mixed, total_s):
        return _bail('the audio bed would not mix')

    silent = os.path.join(clips, 'episode_silent.mp4')
    # Hard cut between rounds: a crossfade here would eat half a second per
    # join and every cue after round one would drift off its mark.
    if not KS.concat_clips(round_clips, silent, xfade=0.0):
        return _bail('the rounds would not join')

    episode_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not KS.mux(silent, mixed, episode_mp4):
        return _bail('the episode would not mux')
    poster = os.path.join(out_dir, 'poster.jpg')
    if not KS.write_poster(episode_mp4, poster):
        return _bail('the poster frame could not be written')

    info = KS.probe(episode_mp4)
    manifest['duration_s'] = round(info['duration'], 2)
    if info['duration'] < 5.0 or not info['has_audio']:
        return _bail(f'the episode is {info["duration"]:.2f}s (audio={info["has_audio"]})')
    if (info['w'], info['h']) != (KS.W, KS.H):
        return _bail(f'the episode is {info["w"]}x{info["h"]}')
    done.append(STAGES[4])

    manifest['ok'] = True
    manifest['reason'] = ''
    log(f'delivered: {manifest["duration_s"]:.2f}s, {len(rounds)} round(s), voice {engine}')
    KS.write_manifest(out_dir, manifest)
    return manifest


if __name__ == '__main__':
    sys.exit(KS.run_cli(sys.modules[__name__]))
