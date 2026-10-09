# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_plane.py — "Peep the Little Plane", the object-only series.

The simplest of the ten: no characters, no voice, no story beats.  One small
round yellow propeller plane flies through one kind of weather per shot, and
the whole episode is fifteen of those shots joined by a soft crossfade.  A
toddler watches the plane, hears the propeller, and that is the programme.

WHY NO SPEECH.  A two-year-old tracks a moving object long before words carry
meaning; adding narration to this series would only add an engine, 20 GB of
VRAM and a failure mode.  The sound is propeller hum under the whole episode,
a whoosh on each cut, and a happy soundfont bed — all local, all cheap.

THE COST RULE.  Nothing here calls a paid API: the fifteen weathers come from
a fixed table in this file, the pictures from FLUX.2 klein-4B (Apache-2.0), the
motion from Wan2.2 I2V (Apache-2.0), the hum and the whoosh from numpy, the bed
from the MIT MuseScore soundfont.  ``kids_series_common.write_manifest`` stamps
that as a number and ``scripts/kids_series_check.py`` re-proves it from the
delivered files.

Test mode is ONE shot.  A Wan test clip is 33 frames at 17 fps — under two
seconds — so the single test shot is topped up with a gentle Ken Burns hold on
its own still, which needs no GPU and takes the deliverable past the five
seconds the checker demands.  The full episode never uses the hold.
"""

from __future__ import annotations

import os
import sys
import time

from zyg_workflows import kids_series_common as KS

SERIES = {
    'slug': 'plane',
    'title': 'Peep the Little Plane',
    'tagline': 'A little yellow plane flies through every kind of sky.',
    'voice': False,
    'characters': False,
    'gpu': True,
    'age_band': 'toddler',
    'episode_seconds': 72,
    'episodes': 12,
    'agents': {
        'Episode Plan': 'weather table',
        'Paint the Sky': 'FLUX.2 klein-4B',
        'Fly Through': 'Wan2.2 I2V A14B',
        'Propeller & Music': 'numpy SFX + MuseScore soundfont',
        'Assemble & Deliver': 'ffmpeg',
    },
}

STAGES = [
    'Episode Plan',
    'Paint the Sky',
    'Fly Through',
    'Propeller & Music',
    'Assemble & Deliver',
]

# The only content in the series.  Twelve skies, drawn in a rolling window so
# consecutive episodes overlap but never open on the same one; a fixed table is
# what makes an episode cost nothing to plan.
WEATHER = [
    'a sunny blue sky with two fluffy clouds',
    'above a rainbow',
    'through soft white clouds',
    'light rain with round raindrops and a cloud',
    'a warm orange sunset',
    'a starry night with a smiling moon',
    'gentle snowflakes falling',
    'a windy sky with three colourful kites',
    'over a calm blue sea with a boat',
    'over green mountains',
    'over a little town with round houses',
    'over a field of red tulips',
]

PLANE = 'a small round yellow cartoon propeller plane with a red nose and round windows flying through'
MOTION = 'the little yellow plane flies gently from left to right, propeller spinning, clouds drift slowly'

SHOTS_PER_EPISODE = 15
SHOT_SECONDS = 4.8
XFADE = 0.4
TEST_HOLD_SECONDS = 4.6  # the Ken Burns top-up, test mode only

MODELS_USED = ['FLUX.2-klein-4B', 'Wan2.2-I2V-A14B', 'MuseScore_General.sf3', 'numpy-synth']
LICENCES = {
    'FLUX.2-klein-4B': 'Apache-2.0',
    'Wan2.2-I2V-A14B': 'Apache-2.0',
    'MuseScore_General.sf3': 'MIT',
    'numpy-synth': 'none (generated)',
}


def _rows_for(episode, test_mode):
    """Which rows of WEATHER this episode draws — the manifest's tables_used."""
    if test_mode:
        return [0]
    start = (int(episode) - 1) * 3
    return [(start + i) % len(WEATHER) for i in range(SHOTS_PER_EPISODE)]


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    """Render one episode into out_dir and return (and write) its manifest."""
    log = log_fn or (lambda _m: None)
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    episode = int(episode or 1)
    t0 = time.time()

    stills_dir = os.path.join(out_dir, 'stills')
    clips_dir = os.path.join(out_dir, 'clips')
    audio_dir = os.path.join(out_dir, 'audio')
    for d in (stills_dir, clips_dir, audio_dir):
        os.makedirs(d, exist_ok=True)

    stages_completed = []
    shots = []
    manifest = {
        'slug': SERIES['slug'],
        'title': SERIES['title'],
        'tagline': SERIES['tagline'],
        'episode': episode,
        'test_mode': bool(test_mode),
        'ok': False,
        'reason': '',
        'duration_s': 0.0,
        'files': {'episode': 'episode.mp4', 'poster': 'poster.jpg'},
        'stages_completed': stages_completed,
        'voice': {'engine': '', 'lines': 0},
        'models_used': MODELS_USED,
        'licences': LICENCES,
        'tables_used': {},
        'weather': [],
        'shots': shots,
    }

    def _fail(reason):
        manifest['ok'] = False
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - t0, 2)
        log(f'plane: FAILED — {reason}')
        KS.write_manifest(out_dir, manifest)
        return manifest

    # ── Episode Plan ────────────────────────────────────────────────────────
    stage('Episode Plan')
    rows = _rows_for(episode, test_mode)
    weather = [WEATHER[r] for r in rows]
    manifest['weather'] = weather
    manifest['tables_used'] = {'WEATHER': rows}
    log(f'plane: episode {episode} — {len(rows)} shot(s), {"test" if test_mode else "full"} mode')
    for i, w in enumerate(weather):
        log(f'  shot {i:02d}: {w}')
    stages_completed.append('Episode Plan')

    # ── Paint the Sky ───────────────────────────────────────────────────────
    # A still that fails is retried once with a nudged seed: the sampler is the
    # flaky part, not the prompt, so a second seed is a real second chance.
    stage('Paint the Sky')
    for i, w in enumerate(weather):
        if abort():
            return _fail('aborted before shot %02d' % i)
        png = os.path.join(stills_dir, f'{i:02d}.png')
        seed = 2000 * episode + i
        prompt = f'{PLANE} {w}, side view'
        ok = KS.render_still(prompt, png, w=KS.W, h=KS.H, seed=seed, log_fn=log)
        if not ok:
            log(f'plane: still {i:02d} failed, retrying with seed+7')
            ok = KS.render_still(prompt, png, w=KS.W, h=KS.H, seed=seed + 7, log_fn=log)
        shots.append({'still': f'stills/{i:02d}.png', 'clip': f'clips/{i:02d}.mp4', 'ok': bool(ok)})
        if not ok:
            return _fail(f'still {i:02d} would not render')
        log(f'plane: still {i:02d} painted')
    stages_completed.append('Paint the Sky')

    # ── Fly Through ─────────────────────────────────────────────────────────
    stage('Fly Through')
    clips = []
    for i, _w in enumerate(weather):
        if abort():
            return _fail('aborted before clip %02d' % i)
        png = os.path.join(stills_dir, f'{i:02d}.png')
        mp4 = os.path.join(clips_dir, f'{i:02d}.mp4')
        seed = 2000 * episode + i
        ok = KS.render_i2v(png, MOTION, mp4, seconds=SHOT_SECONDS, seed=seed, test_mode=test_mode, log_fn=log)
        if not ok:
            log(f'plane: clip {i:02d} failed, retrying with seed+7')
            ok = KS.render_i2v(png, MOTION, mp4, seconds=SHOT_SECONDS, seed=seed + 7, test_mode=test_mode, log_fn=log)
        shots[i]['ok'] = bool(ok)
        if not ok:
            return _fail(f'clip {i:02d} would not render')
        clips.append(mp4)
        log(f'plane: clip {i:02d} flown')

    if test_mode:
        # One shot is under two seconds of Wan; the hold is the same picture,
        # drifting, and it costs no GPU at all.
        hold = os.path.join(clips_dir, '00_hold.mp4')
        if KS.zoompan_clip(os.path.join(stills_dir, '00.png'), hold, TEST_HOLD_SECONDS, direction='out'):
            clips.append(hold)
            log('plane: test hold appended')
        else:
            log('plane: test hold could not be made — episode may be short')
    stages_completed.append('Fly Through')

    # ── Propeller & Music ───────────────────────────────────────────────────
    # The sound is laid before the picture is joined, because the mix only
    # needs the LENGTHS of the clips, and xfade makes those arithmetic: each
    # crossfade overlaps its two neighbours, so the timeline is the sum of the
    # clips minus one crossfade per cut.  A boundary computed the naive way
    # puts every whoosh progressively later than its own cut.
    stage('Propeller & Music')
    lens = [float(KS.probe(c)['duration']) for c in clips]
    if any(d <= 0 for d in lens):
        return _fail('a rendered clip has no duration')
    total = sum(lens) - XFADE * (len(lens) - 1)
    cuts, off = [], 0.0
    for d in lens[:-1]:
        off += d - XFADE
        cuts.append(max(0.0, off))
    log(f'plane: timeline {total:.2f}s, {len(cuts)} cut(s)')

    tracks = []
    hum = os.path.join(audio_dir, 'propeller.wav')
    if KS.synth_sfx('plane', hum, seconds=total, seed=episode):
        tracks.append((hum, 0.0, -12.0))
    else:
        log('plane: propeller hum unavailable')
    whoosh = os.path.join(audio_dir, 'whoosh.wav')
    if cuts and KS.synth_sfx('whoosh', whoosh, seconds=1.2, seed=episode):
        for t in cuts:
            tracks.append((whoosh, max(0.0, t - 0.3), -16.0))
    bed = os.path.join(audio_dir, 'music.wav')
    if KS.music_bed(bed, seconds=total, mood='happy', age_band=SERIES['age_band'], seed=episode, log_fn=log):
        tracks.append((bed, 0.0, -4.0))
    else:
        log('plane: music bed unavailable')

    mixed = os.path.join(audio_dir, 'mix.wav')
    # A quarter-second of slack: mux runs -shortest, so a bed that lands a
    # frame under the picture would trim the last shot instead of the silence.
    if not KS.mix_audio(tracks, mixed, total + 0.25):
        return _fail('the sound would not mix')
    stages_completed.append('Propeller & Music')
    log(f'plane: {len(tracks)} track(s) mixed over {total:.2f}s')

    # ── Assemble & Deliver ──────────────────────────────────────────────────
    stage('Assemble & Deliver')
    silent = os.path.join(out_dir, 'video_silent.mp4')
    if not KS.concat_clips(clips, silent, xfade=XFADE):
        return _fail('the clips would not join')
    episode_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not KS.mux(silent, mixed, episode_mp4):
        return _fail('the episode would not mux')
    poster = os.path.join(out_dir, 'poster.jpg')
    if not KS.write_poster(episode_mp4, poster):
        return _fail('the poster would not render')

    info = KS.probe(episode_mp4)
    if not info['has_audio']:
        return _fail('the delivered episode has no audio stream')
    manifest['duration_s'] = round(float(info['duration']), 2)
    manifest['ok'] = True
    manifest['reason'] = ''
    stages_completed.append('Assemble & Deliver')
    KS.write_manifest(out_dir, manifest)
    log(f'plane: delivered {manifest["duration_s"]:.2f}s {info["w"]}x{info["h"]}')
    return manifest


if __name__ == '__main__':
    sys.exit(KS.run_cli(sys.modules[__name__]))
