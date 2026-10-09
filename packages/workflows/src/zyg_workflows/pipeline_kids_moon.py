# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_moon.py — "Sleepy Moon", the wordless one.

The other nine series in this family talk.  This one deliberately does not:
no voice, no characters, no story beats — a lullaby.  Three painted night
skies, each drifting for twenty-five seconds under a slow Ken Burns move,
over a bed of music that is CONSTRUCTED rather than sampled.  That is the
whole point of the series: ``kids_music_theory`` writes a real tune under the
toddler constraints (small steps, few durations, every bar on a downbeat) and
the MIT SoundFont plays it, so the music is as local, as free and as
deterministic as the pictures.

Everything an episode contains comes from the fixed SKIES table below and from
arithmetic.  There is no language model in the loop and no hosted call of any
kind, which is how an episode costs nothing: see the cost rule in
``kids_series_common``'s docstring, and ``scripts/kids_series_check.py``, which
re-proves it from the delivered files.

    python pipeline_kids_moon.py --test --out output/kids_moon/test_x
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from zyg_workflows import kids_series_common as K

SERIES = {
    'slug': 'moon',
    'title': 'Sleepy Moon',
    'tagline': 'A wordless lullaby: three night skies and a tune built for sleep.',
    'voice': False,
    'characters': False,
    'gpu': True,
    'age_band': 'toddler',
    'episode_seconds': 75,
    'episodes': 12,
    'agents': {
        'Episode Plan': 'fixed SKIES table + kids_music_theory',
        'Paint the Night': 'FLUX.2 klein-4B (klein_txt2img)',
        'Compose Lullaby': 'kids_music_theory + MuseScore_General.sf3',
        'Slow Camera': 'ffmpeg zoompan',
        'Assemble & Deliver': 'ffmpeg concat / mix / mux',
    },
}

STAGES = ['Episode Plan', 'Paint the Night', 'Compose Lullaby', 'Slow Camera', 'Assemble & Deliver']

# The twelve night skies.  A fixed table, not a generator: it is the only
# content in the series, so it is reviewable in one screen and identical on
# every run.  Episode k draws rows (k-1)*3 .. +2, wrapping, so consecutive
# episodes never repeat a sky and the twelfth still lands on the table.
SKIES = (
    'a big smiling crescent moon over soft rolling hills',
    'the moon over a calm sea with a tiny sailing boat',
    'the moon above sleepy village rooftops with warm windows',
    'the moon over a snowy forest',
    'the moon behind thin clouds over a meadow',
    'the moon reflected in a quiet lake',
    'the moon over sand dunes',
    'the moon above a lighthouse',
    'the moon over a field of sleeping sheep',
    'the moon above a cosy farmhouse',
    'the moon over a mountain lake',
    'the moon above a sleeping city of soft towers',
)

SHOTS = 3  # stills per full episode
SHOT_SECONDS = 25.0  # each one's screen time
XFADE = 0.5  # the crossfade OVERLAPS, so it shortens the total
TEST_SECONDS = 8.0  # one still, still a real deliverable (>= 5 s)

BELL_EVERY = 8.0  # seconds between twinkles
BELL_SECONDS = 1.5
BELL_GAIN_DB = -16.0
MUSIC_GAIN_DB = -3.0
# A falling pitch table, cycled: each twinkle sits a little lower than the one
# before it.  Descent is the oldest trick in a lullaby and it costs four floats.
BELL_F0 = (1320.0, 1188.0, 1056.0, 990.0)

VIDEO_FADE_S = 3.0  # to black
AUDIO_FADE_S = 4.0  # under it, and longer, so the picture goes first

MOOD = 'gentle'
AGE_BAND = 'toddler'

_STILL_TAIL = 'deep blue night sky with a few soft stars, everything calm and sleepy'


def _skies_for(episode, test_mode):
    """The rows this episode draws.  -> [(index, prompt), ...]"""
    if test_mode:
        return [(0, SKIES[0])]
    start = (max(1, int(episode)) - 1) * SHOTS
    return [((start + i) % len(SKIES), SKIES[(start + i) % len(SKIES)]) for i in range(SHOTS)]


def _lullaby_meta(seconds, seed):
    """{bpm, key, seconds} for the manifest.

    ``music_bed`` renders the tune but does not hand back the plan, so the same
    brief and the same seed are composed again here for the record.  The
    composer is deterministic in its seed, so this describes the bed that was
    actually rendered rather than a second, different one.
    """
    meta = {'bpm': None, 'key': '', 'seconds': round(float(seconds), 2), 'mood': MOOD, 'age_band': AGE_BAND}
    try:
        from zyg_workflows import kids_music_theory as T

        plan = T.compose_best(
            {'theme': MOOD, 'age_band': AGE_BAND, 'mood': MOOD, 'seconds': int(round(seconds)), 'sung': False},
            candidates=16,
            seed0=int(seed),
        )
        if isinstance(plan, tuple):
            plan = plan[0]
        if plan:
            meta['bpm'] = plan.get('bpm')
            key = plan.get('tonic') or plan.get('key') or ''
            meta['key'] = key.get('label') if isinstance(key, dict) else str(key)
    except Exception as e:  # noqa: BLE001 — metadata only
        meta['error'] = f'{type(e).__name__}: {e}'[:160]
    return meta


def _ff(args, timeout=900):
    """One ffmpeg run.  The shared module keeps its own private helper; the two
    fades below are this series' own and do not belong in the common floor."""
    try:
        r = subprocess.run([K.FFMPEG] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _fade_video(src, dst, total_s):
    """Fade the picture to black over the last VIDEO_FADE_S seconds."""
    d = min(VIDEO_FADE_S, max(0.5, total_s * 0.4))
    st = max(0.0, total_s - d)
    return _ff(
        [
            '-y',
            '-i',
            src,
            '-vf',
            f'fade=t=out:st={st:.3f}:d={d:.3f}',
            '-r',
            str(K.FPS),
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-an',
            dst,
        ]
    )


def _fade_audio(src, dst, total_s):
    """And the sound after it, over AUDIO_FADE_S — longer on purpose."""
    d = min(AUDIO_FADE_S, max(0.5, total_s * 0.5))
    st = max(0.0, total_s - d)
    return _ff(
        ['-y', '-i', src, '-af', f'afade=t=out:st={st:.3f}:d={d:.3f}', '-c:a', 'pcm_s16le', '-ar', str(K.SR), dst]
    )


def _bell_times(total_s):
    """Twinkles every BELL_EVERY seconds, none in the fade-out."""
    out, t = [], 0.0
    while t <= max(0.0, total_s - 2.0) + 1e-6:
        out.append(round(t, 3))
        t += BELL_EVERY
    return out


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    """One episode of Sleepy Moon.  Returns the manifest it wrote."""
    log = log_fn or (lambda _m: None)
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    t0 = time.time()
    episode = max(1, int(episode or 1))

    os.makedirs(out_dir, exist_ok=True)
    stills_dir = os.path.join(out_dir, 'stills')
    clips_dir = os.path.join(out_dir, 'clips')
    audio_dir = os.path.join(out_dir, 'audio')
    for d in (stills_dir, clips_dir, audio_dir):
        os.makedirs(d, exist_ok=True)

    unet, steps, cfg = K.klein_settings()
    done = []
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
        'voice': {'engine': '', 'lines': 0},  # by design: this one is wordless
        'models_used': [
            f'FLUX.2 klein ({unet}, {steps} steps, cfg {cfg})',
            'kids_music_theory + MuseScore_General.sf3 (fluidsynth)',
            'synth_sfx bell (numpy)',
        ],
        'licences': {
            'flux2-klein-4b': 'Apache-2.0',
            'MuseScore_General.sf3': 'MIT',
            'bells': 'synthesised (numpy), no sample library',
        },
        'tables_used': {},
    }

    def _bail(reason):
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - t0, 2)
        log(f'moon: {reason}')
        K.write_manifest(out_dir, manifest)
        return manifest

    # ── Episode Plan ─────────────────────────────────────────────────────────
    stage(STAGES[0])
    rows = _skies_for(episode, test_mode)
    shot_s = TEST_SECONDS if test_mode else SHOT_SECONDS
    total_s = len(rows) * shot_s - max(0, len(rows) - 1) * XFADE
    bells = _bell_times(total_s)
    manifest['tables_used'] = {'skies': [i for i, _p in rows]}
    manifest['skies'] = [p for _i, p in rows]
    manifest['camera'] = [
        {'shot': n, 'sky_row': i, 'seconds': shot_s, 'move': 'in' if n % 2 == 0 else 'out'}
        for n, (i, _p) in enumerate(rows)
    ]
    manifest['bells'] = {'count': len(bells), 'every_s': BELL_EVERY, 'at_s': bells, 'f0_hz': list(BELL_F0)}
    log(
        f'plan: {len(rows)} sk{"y" if len(rows) == 1 else "ies"}, '
        f'{shot_s:g}s each, {total_s:g}s total, {len(bells)} twinkles'
    )
    done.append(STAGES[0])
    if abort():
        return _bail('aborted before painting')

    # ── Paint the Night ──────────────────────────────────────────────────────
    stage(STAGES[1])
    stills = []
    for n, (row, sky) in enumerate(rows):
        if abort():
            return _bail('aborted while painting')
        png = os.path.join(stills_dir, f'{n:02d}.png')
        seed = 7000 + episode * 10 + n
        log(f'still {n + 1}/{len(rows)} (row {row}, seed {seed}): {sky}')
        if not K.render_still(f'{sky}, {_STILL_TAIL}', png, w=K.W, h=K.H, seed=seed, log_fn=log):
            return _bail(f'the night sky for shot {n + 1} did not render')
        stills.append(png)
    done.append(STAGES[1])

    # ── Compose Lullaby ──────────────────────────────────────────────────────
    stage(STAGES[2])
    lullaby = os.path.join(audio_dir, 'lullaby.wav')
    if not K.music_bed(lullaby, seconds=total_s, mood=MOOD, age_band=AGE_BAND, seed=episode, log_fn=log):
        return _bail('the lullaby did not render')
    manifest['lullaby'] = _lullaby_meta(total_s, episode)
    log(f'lullaby: {manifest["lullaby"].get("bpm")} bpm, key {manifest["lullaby"].get("key") or "?"}')
    bell_wavs = []
    for n, at in enumerate(bells):
        w = os.path.join(audio_dir, f'bell_{n:02d}.wav')
        if K.synth_sfx('bell', w, seconds=BELL_SECONDS, seed=episode * 100 + n, f0=BELL_F0[n % len(BELL_F0)]):
            bell_wavs.append((w, at, BELL_GAIN_DB))
    log(f'twinkles: {len(bell_wavs)}/{len(bells)} synthesised')
    done.append(STAGES[2])
    if abort():
        return _bail('aborted before the camera move')

    # ── Slow Camera ──────────────────────────────────────────────────────────
    stage(STAGES[3])
    clips = []
    for n, png in enumerate(stills):
        if abort():
            return _bail('aborted during the camera move')
        mp4 = os.path.join(clips_dir, f'{n:02d}.mp4')
        move = 'in' if n % 2 == 0 else 'out'
        if not K.zoompan_clip(png, mp4, shot_s, direction=move, fps=K.FPS):
            return _bail(f'the camera move for shot {n + 1} failed')
        clips.append(mp4)
        log(f'clip {n + 1}/{len(stills)}: {shot_s:g}s drifting {move}')
    done.append(STAGES[3])

    # ── Assemble & Deliver ───────────────────────────────────────────────────
    stage(STAGES[4])
    silent = os.path.join(out_dir, 'video_silent.mp4')
    if not K.concat_clips(clips, silent, xfade=XFADE):
        return _bail('the clips would not join')
    real_s = K.probe(silent)['duration'] or total_s

    faded = os.path.join(out_dir, 'video_faded.mp4')
    if not _fade_video(silent, faded, real_s):
        log('fade: the video fade-out failed; delivering the unfaded cut')
        faded = silent

    bed = os.path.join(audio_dir, 'bed.wav')
    if not K.mix_audio([(lullaby, 0.0, MUSIC_GAIN_DB)] + bell_wavs, bed, real_s):
        return _bail('the audio bed would not mix')
    bed_faded = os.path.join(audio_dir, 'bed_faded.wav')
    if not _fade_audio(bed, bed_faded, real_s):
        log('fade: the audio fade-out failed; delivering the unfaded bed')
        bed_faded = bed

    ep_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not K.mux(faded, bed_faded, ep_mp4):
        return _bail('the episode would not mux')
    info = K.probe(ep_mp4)
    if info['duration'] < 5.0:
        return _bail(f'the episode is only {info["duration"]:.2f}s long')
    if not info['has_audio']:
        return _bail('the episode came out silent')
    if not K.write_poster(ep_mp4, os.path.join(out_dir, 'poster.jpg')):
        return _bail('the poster frame could not be written')
    done.append(STAGES[4])

    manifest['ok'] = True
    manifest['reason'] = ''
    manifest['duration_s'] = round(info['duration'], 2)
    manifest['video'] = {'w': info['w'], 'h': info['h'], 'fps': K.FPS}
    log(f'delivered: {info["duration"]:.2f}s, {info["w"]}x{info["h"]}, {len(clips)} shot(s), {len(bell_wavs)} twinkles')
    K.write_manifest(out_dir, manifest)
    return manifest


if __name__ == '__main__':
    sys.exit(K.run_cli(sys.modules[__name__]))
