# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_tractor.py — "Little Red Tractor", the object-only series.

The simplest shape in the family: no voice, no characters, no story beats.  A
small round red cartoon tractor putt-putts through one farm place per shot, and
the whole soundtrack is an engine and a happy soundfont bed.  A toddler needs a
thing that moves and a sound that goes with it; everything else is decoration
this series deliberately does not buy.

Every choice below is a fixed table or arithmetic, so an episode costs nothing:
pictures come from FLUX.2 klein-4B, motion from Wan2.2 I2V, music from the MIT
soundfont, and the engine is numpy.  Nothing here reaches a hosted model — see
the cost rule in kids_series_common's docstring, which this module obeys by
calling that module for every generator and inventing none of its own.
"""

from __future__ import annotations

import os
import sys
import time

from zyg_workflows import kids_series_common as K

# ── the series ───────────────────────────────────────────────────────────────

SERIES = {
    'slug': 'tractor',
    'title': 'Little Red Tractor',
    'tagline': 'A little red tractor putt-putts around the farm.',
    'voice': False,  # no narration at all — engine and music carry it
    'characters': False,  # the tractor is a shape, not a cast member
    'gpu': True,
    'age_band': 'toddler',
    'episode_seconds': 72,  # 15 shots x 4.8 s
    'episodes': 12,
    'agents': {
        'Episode Plan': 'fixed places table',
        'Paint Places': 'FLUX.2 klein-4B',
        'Drive Through': 'Wan2.2 I2V A14B',
        'Engine & Music': 'numpy engine + MuseScore soundfont',
        'Assemble & Deliver': 'ffmpeg',
    },
}

# The board's columns are built from this list, and stage_fn must be handed
# these exact strings — a near-miss creates a column nobody watches.
STAGES = ['Episode Plan', 'Paint Places', 'Drive Through', 'Engine & Music', 'Assemble & Deliver']

# One farm place per shot.  Twelve rows, all of them bright, none of them
# containing a person, an animal in danger or anything to read: the picture is
# a place and a tractor, and that is the entire vocabulary of the series.
PLACES = [
    'a red barn on green grass',
    'a duck pond with lily pads',
    'a gentle green hill under a big sun',
    'an apple orchard with round red apples',
    'a hay field with round hay bales',
    'a shiny muddy puddle',
    'a little wooden bridge over a stream',
    'a white windmill',
    'a field of tall sunflowers',
    'a pumpkin patch',
    'a snowy field with a snowman',
    'a shallow river ford with smooth stones',
]

SHOTS = 15  # 15 x 4.8 s = the 72 s episode
SHOT_SECONDS = 4.8
XFADE = 0.4
STRIDE = 3  # episode k starts 3 rows further round the table

# Wan's test path renders 33 frames at 17 fps — 1.9 s, under the 5 s floor the
# deliverable has to clear.  The test unit is therefore the real clip plus a
# slow push on its own still, which keeps the one-shot rule while producing a
# file that can actually be checked.
TEST_UNIT_SECONDS = 6.0

MOTION = (
    'the little red tractor drives slowly from left to right, wheels turning, tiny puffs of smoke, everything else calm'
)

MODELS_USED = [
    'FLUX.2 klein-4B (klein_txt2img)',
    'Wan2.2 I2V A14B (wan22_i2v)',
    'MuseScore_General.sf3 via fluidsynth',
    'numpy (synth_sfx engine)',
]

LICENCES = {
    'FLUX.2 klein-4B': 'Apache-2.0',
    'Wan2.2 I2V A14B': 'Apache-2.0',
    'MuseScore_General.sf3': 'MIT',
    'engine sound': 'synthesised in numpy — no sample library',
}


def _places_for(episode, test_mode):
    """The rows this episode draws, as (index, place) pairs.

    Episode k starts STRIDE rows further round the table and wraps, so
    consecutive episodes share most of the farm but never open on the same
    place.  The test always takes row 0 — a fixed unit is what makes two test
    runs comparable.
    """
    if test_mode:
        return [(0, PLACES[0])]
    start = (max(1, int(episode)) - 1) * STRIDE
    return [((start + i) % len(PLACES), PLACES[(start + i) % len(PLACES)]) for i in range(SHOTS)]


def _seed_for(episode, idx):
    return 1000 * int(episode) + int(idx)


def _paint(shot, episode, log):
    """The still for one shot, with a single seed+7 retry.

    A shot that will not render is a failure, not a gap: the caller stops the
    run rather than delivering an episode that is quietly short.
    """
    prompt = f'a small round red cartoon tractor with big black wheels driving past {shot["place"]}, side view'
    for attempt, s in enumerate((_seed_for(episode, shot['n']), _seed_for(episode, shot['n']) + 7)):
        if attempt:
            log(f'shot {shot["nn"]}: still failed, retrying at seed {s}')
        if K.render_still(prompt, shot['still'], seed=s, log_fn=log):
            return True
    return False


def _drive(shot, episode, test_mode, log):
    """The clip for one shot, with a single seed+7 retry."""
    for attempt, s in enumerate((_seed_for(episode, shot['n']), _seed_for(episode, shot['n']) + 7)):
        if attempt:
            log(f'shot {shot["nn"]}: clip failed, retrying at seed {s}')
        if K.render_i2v(
            shot['still'], MOTION, shot['clip'], seconds=SHOT_SECONDS, seed=s, test_mode=test_mode, log_fn=log
        ):
            return True
    return False


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    """Produce one episode into out_dir and return its manifest.

    The manifest is the verdict — never the fact that this function returned.
    ``ok`` is only set once the delivered mp4 has been probed off the disk.
    """
    log = log_fn or K._log_noop
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    started = time.time()
    episode = max(1, int(episode or 1))
    os.makedirs(out_dir, exist_ok=True)
    audio_dir = os.path.join(out_dir, 'audio')

    manifest = {
        'slug': SERIES['slug'],
        'title': SERIES['title'],
        'episode': episode,
        'test_mode': bool(test_mode),
        'ok': False,
        'reason': '',
        'duration_s': 0.0,
        'files': {'episode': 'episode.mp4', 'poster': 'poster.jpg'},
        'stages_completed': [],
        'voice': {'engine': '', 'lines': 0},  # this series has none, by design
        'models_used': list(MODELS_USED),
        'licences': dict(LICENCES),
        'tables_used': {},
        'places': [],
        'shots': [],
    }

    def _fail(reason):
        manifest['reason'] = reason
        manifest['wall_s'] = round(time.time() - started, 1)
        log(f'FAILED: {reason}')
        K.write_manifest(out_dir, manifest)
        return manifest

    # ── Episode Plan ─────────────────────────────────────────────────────────
    stage('Episode Plan')
    rows = _places_for(episode, test_mode)
    shots = [
        {
            'n': n,
            'nn': f'{n:02d}',
            'place': place,
            'still': os.path.join(out_dir, 'stills', f'{n:02d}.png'),
            'clip': os.path.join(out_dir, 'clips', f'{n:02d}.mp4'),
            'ok': False,
        }
        for n, (_row, place) in enumerate(rows, start=1)
    ]
    manifest['places'] = [p for _i, p in rows]
    manifest['tables_used'] = {'PLACES': [i for i, _p in rows]}
    manifest['shots'] = [{k: s[k] for k in ('still', 'clip', 'ok')} for s in shots]
    log(f'episode {episode}: {len(rows)} shot(s) — ' + '; '.join(manifest['places']))
    manifest['stages_completed'].append('Episode Plan')

    def _publish():
        manifest['shots'] = [{k: s[k] for k in ('still', 'clip', 'ok')} for s in shots]

    # ── Paint Places ─────────────────────────────────────────────────────────
    stage('Paint Places')
    for shot in shots:
        if abort():
            return _fail(f'aborted before painting shot {shot["nn"]}')
        if not _paint(shot, episode, log):
            return _fail(f'shot {shot["nn"]}: no still after a retry')
        log(f'painted {shot["nn"]}: {shot["place"]}')
    manifest['stages_completed'].append('Paint Places')

    # ── Drive Through ────────────────────────────────────────────────────────
    stage('Drive Through')
    for shot in shots:
        if abort():
            _publish()
            return _fail(f'aborted before driving shot {shot["nn"]}')
        if not _drive(shot, episode, test_mode, log):
            _publish()
            return _fail(f'shot {shot["nn"]}: no clip after a retry')
        shot['ok'] = True
        log(f'drove {shot["nn"]}: {K.probe(shot["clip"])["duration"]:.2f} s')
    _publish()
    manifest['stages_completed'].append('Drive Through')

    clips = [s['clip'] for s in shots]
    if test_mode:
        # The one-shot unit, stretched over the 5 s floor by a slow push on its
        # own still.  Same picture, same motion — only the tail is added.
        held = os.path.join(out_dir, 'clips', 'hold.mp4')
        have = K.probe(clips[0])['duration']
        tail = max(1.0, TEST_UNIT_SECONDS - have + XFADE)
        if K.zoompan_clip(shots[0]['still'], held, tail, direction='in'):
            clips = [clips[0], held]
            log(f'test unit: {have:.2f} s clip + {tail:.2f} s hold')
        else:
            log('test unit: hold render failed — delivering the clip alone')

    lens = [K.probe(c)['duration'] for c in clips]
    if min(lens) <= 0:
        return _fail('a rendered clip has no duration')
    total = sum(lens) - XFADE * (len(clips) - 1) if len(clips) > 1 else lens[0]

    # ── Engine & Music ───────────────────────────────────────────────────────
    stage('Engine & Music')
    if abort():
        return _fail('aborted before the soundtrack')
    engine = os.path.join(audio_dir, 'engine.wav')
    bed = os.path.join(audio_dir, 'bed.wav')
    tracks = []
    if K.synth_sfx('engine', engine, seconds=total, rate_hz=24):
        tracks.append((engine, 0.0, -10.0))
    else:
        log('engine: synth failed — the episode will run on music alone')
    if K.music_bed(bed, seconds=total, mood='happy', age_band=SERIES['age_band'], seed=episode, log_fn=log):
        tracks.append((bed, 0.0, -4.0))
    else:
        log('music: bed unavailable — the episode will run on the engine alone')
    if not tracks:
        return _fail('no soundtrack: neither the engine nor the music bed rendered')
    manifest['stages_completed'].append('Engine & Music')

    # ── Assemble & Deliver ───────────────────────────────────────────────────
    stage('Assemble & Deliver')
    if abort():
        return _fail('aborted before assembly')
    silent = os.path.join(out_dir, 'silent.mp4')
    if not K.concat_clips(clips, silent, xfade=XFADE):
        return _fail('the clips would not join')
    total = K.probe(silent)['duration'] or total

    mix = os.path.join(audio_dir, 'mix.wav')
    if not K.mix_audio(tracks, mix, total):
        return _fail('the soundtrack would not mix')

    ep_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not K.mux(silent, mix, ep_mp4):
        return _fail('the picture and the sound would not mux')
    K.write_poster(ep_mp4, os.path.join(out_dir, 'poster.jpg'))

    # The verdict, read back off the disk rather than assumed.
    info = K.probe(ep_mp4)
    floor = 5.0 if test_mode else 60.0
    manifest['duration_s'] = round(info['duration'], 2)
    if info['duration'] < floor:
        return _fail(f'episode.mp4 is {info["duration"]:.2f} s, under the {floor:g} s floor')
    if not info['has_audio']:
        return _fail('episode.mp4 has no audio stream')
    if (info['w'], info['h']) != (K.W, K.H):
        return _fail(f'episode.mp4 is {info["w"]}x{info["h"]}, not {K.W}x{K.H}')

    manifest['stages_completed'].append('Assemble & Deliver')
    manifest['ok'] = True
    manifest['reason'] = ''
    manifest['wall_s'] = round(time.time() - started, 1)
    log(f'delivered {info["duration"]:.2f} s in {manifest["wall_s"]:.0f} s wall')
    K.write_manifest(out_dir, manifest)
    return manifest


if __name__ == '__main__':
    sys.exit(K.run_cli(sys.modules[__name__]))
