# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kids_car.py — "Good Night, Little Car".

A six-picture bedtime story for toddlers about a small round cartoon car.  No
people, no plot to follow, one short spoken sentence per picture and a gentle
push-in/pull-back over each still.  The car changes colour from episode to
episode and nothing else does: the same six beats, the same six sentences, so a
child who has heard it once can say the next line along with it.

Everything the runner needs from a model, a codec or the job board comes from
``kids_series_common``; this file owns only the tables and the shape of an
episode.  That is also the cost rule in practice — the story is a constant in
the source, so an episode makes ZERO paid API calls and costs $0.00.

No Wan2.2 here on purpose.  A bedtime story wants stillness, and a Ken Burns
move over a klein still is both calmer and about forty times cheaper than
image-to-video on six shots.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from zyg_workflows import kids_series_common as K

SERIES = {
    'slug': 'car',
    'title': 'Good Night, Little Car',
    'tagline': 'A little car says good night, one picture at a time.',
    'voice': True,
    'characters': False,
    'gpu': True,
    'age_band': 'toddler',
    'episode_seconds': 72,
    'episodes': 6,
    'agents': {
        'Episode Plan': 'fixed story table',
        'Paint the Story': 'FLUX.2 klein-4B',
        'Tell the Story': 'IndexTTS-2 / Chatterbox',
        'Soft Camera': 'ffmpeg zoompan',
        'Assemble & Deliver': 'ffmpeg + MuseScore soundfont',
    },
}

STAGES = ['Episode Plan', 'Paint the Story', 'Tell the Story', 'Soft Camera', 'Assemble & Deliver']

# ── the fixed tables ─────────────────────────────────────────────────────────
#
# Episode k draws row (k-1) % 6.  Six colours against six pictures means the
# story is identical and the car is not, which is the whole variation budget
# this series has and all a two-year-old wants.

COLOURS = ['red', 'blue', 'yellow', 'green', 'orange', 'purple']

STORY = [
    (
        'a small round {colour} cartoon car waking up in a cosy garage, morning light',
        'Good morning, little {colour} car!',
    ),
    ('the little {colour} car driving slowly past a field of sunflowers', 'The little car drives past the sunflowers.'),
    ('the little {colour} car in a bubbly car wash with big soft brushes', 'Splish splash, the car gets clean.'),
    ('the little {colour} car parked by a friendly little petrol pump', 'The car has a little drink.'),
    (
        'the little {colour} car parked on a hill under a starry sky with a smiling moon',
        'The stars come out. It is getting late.',
    ),
    ('the little {colour} car asleep in its garage with a blanket, night', 'Good night, little car. Sleep tight.'),
]

VOICE = 'f04_elder_gentle'
VOICE_SEED = 11
PICTURE_SECONDS = 12.0  # 6 x 12 = 72 s = SERIES['episode_seconds']
XFADE = 0.5  # crossfade between pictures
SAY_OFFSET = 1.5  # the line lands 1.5 s into its picture
BED_GAIN_DB = -10.0
HORN_GAIN_DB = -18.0
SPLASH_GAIN_DB = -12.0
TAIL_FADE = 3.0  # fade to black + afade over the last 3 s
TEST_MIN_SECONDS = 8.0


def _picture_start(i):
    """Wall-clock start of picture i (0-based) in the concatenated video.

    Each crossfade overlaps its two neighbours, so every picture after the
    first begins XFADE earlier than its nominal slot.  Getting this wrong does
    not error — the voice simply drifts off its picture — so it is one
    function used by every sound this file places.
    """
    return i * (PICTURE_SECONDS - XFADE)


def _fade_tail(src, dst, total_s, *, audio=False):
    """Fade the last TAIL_FADE seconds of a video to black, or an audio out."""
    st = max(0.0, float(total_s) - TAIL_FADE)
    if audio:
        args = ['-af', f'afade=t=out:st={st:.3f}:d={TAIL_FADE:g}', '-c:a', 'pcm_s16le']
    else:
        args = [
            '-vf',
            f'fade=t=out:st={st:.3f}:d={TAIL_FADE:g}',
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
        ]
    cmd = [K.FFMPEG, '-y', '-i', src] + args + [dst]
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and os.path.isfile(dst)


def run_episode(out_dir, episode, *, test_mode=False, log_fn=None, stage_fn=None, should_abort=None):
    log = log_fn or (lambda _m: None)
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    started = time.time()

    os.makedirs(out_dir, exist_ok=True)
    stills_dir = os.path.join(out_dir, 'stills')
    clips_dir = os.path.join(out_dir, 'clips')
    audio_dir = os.path.join(out_dir, 'audio')
    for d in (stills_dir, clips_dir, audio_dir):
        os.makedirs(d, exist_ok=True)

    episode = max(1, int(episode or 1))
    colour_row = (episode - 1) % len(COLOURS)
    colour = COLOURS[colour_row]

    manifest = {
        'slug': SERIES['slug'],
        'title': SERIES['title'],
        'episode': episode,
        'test_mode': bool(test_mode),
        'ok': False,
        'reason': '',
        'duration_s': 0.0,
        'colour': colour,
        'story': [],
        'files': {'episode': 'episode.mp4', 'poster': 'poster.jpg'},
        'stages_completed': [],
        'voice': {'engine': '', 'lines': 0},
        'models_used': [],
        'licences': [],
        'tables_used': {},
    }

    def done(name):
        manifest['stages_completed'].append(name)

    def fail(reason):
        manifest['reason'] = reason
        manifest['duration_s'] = round(time.time() - started, 2)
        log(f'FAILED: {reason}')
        K.write_manifest(out_dir, manifest)
        return manifest

    # ── Episode Plan ─────────────────────────────────────────────────────────
    stage(STAGES[0])
    rows = list(range(1 if test_mode else len(STORY)))
    beats = []
    for i in rows:
        prompt, sentence = STORY[i]
        beats.append(
            {
                'row': i,
                'prompt': prompt.format(colour=colour),
                'sentence': sentence.format(colour=colour),
                'still': f'stills/{i + 1}.png',
                'say_file': f'audio/say_{i + 1}.wav',
                'seed': 5000 + episode * 10 + (i + 1),
                'direction': 'in' if i % 2 == 0 else 'out',
            }
        )
    manifest['tables_used'] = {
        'colours_row': colour_row,
        'colour': colour,
        'story_rows': [b['row'] for b in beats],
    }
    planned = len(beats) * PICTURE_SECONDS - max(0, len(beats) - 1) * XFADE
    log(f'plan: episode {episode}, {colour} car, {len(beats)} picture(s), ~{planned:.1f}s')
    done(STAGES[0])
    if abort():
        return fail('aborted')

    # ── Paint the Story ──────────────────────────────────────────────────────
    stage(STAGES[1])
    unet, steps, cfg = K.klein_settings()
    manifest['models_used'].append({'role': 'stills', 'model': f'FLUX.2 klein ({unet})', 'steps': steps, 'cfg': cfg})
    manifest['licences'].append({'model': 'FLUX.2 klein-4B', 'licence': 'Apache-2.0'})
    for b in beats:
        if abort():
            return fail('aborted')
        png = os.path.join(out_dir, b['still'])
        log(f'still {b["row"] + 1}/{len(STORY)}: {b["prompt"][:70]}')
        if not K.render_still(b['prompt'], png, w=K.W, h=K.H, seed=b['seed'], log_fn=log):
            return fail(f'still {b["row"] + 1} did not render')
    done(STAGES[1])

    # ── Tell the Story ───────────────────────────────────────────────────────
    #
    # Speech before the camera move: IndexTTS-2 wants ~20 GB and the stills
    # have just filled the card, so `say` releases ComfyUI's VRAM on its first
    # call.  Doing the CPU-only zoompan afterwards costs nothing extra.
    stage(STAGES[2])
    engines = []
    for b in beats:
        if abort():
            return fail('aborted')
        wav = os.path.join(out_dir, b['say_file'])
        engine = K.say(b['sentence'], wav, voice=VOICE, seed=VOICE_SEED, log_fn=log)
        if not engine:
            return fail(f'no speech for line {b["row"] + 1}: {b["sentence"][:60]!r}')
        engines.append(engine)
        log(f'voice[{engine}]: {b["sentence"]}')
    manifest['voice'] = {'engine': engines[0], 'lines': len(engines), 'reference': VOICE, 'engines': engines}
    manifest['models_used'].append({'role': 'speech', 'model': engines[0], 'voice': VOICE})
    manifest['licences'].append({'model': f'voice seed {VOICE} (Maya1)', 'licence': 'Apache-2.0'})
    done(STAGES[2])

    # ── Soft Camera ──────────────────────────────────────────────────────────
    stage(STAGES[3])
    clips = []
    for b in beats:
        if abort():
            return fail('aborted')
        png = os.path.join(out_dir, b['still'])
        clip = os.path.join(clips_dir, f'{b["row"] + 1}.mp4')
        if not K.zoompan_clip(png, clip, PICTURE_SECONDS, direction=b['direction'], fps=K.FPS):
            return fail(f'camera move {b["row"] + 1} failed')
        clips.append(clip)
    done(STAGES[3])

    # ── Assemble & Deliver ───────────────────────────────────────────────────
    stage(STAGES[4])
    silent = os.path.join(out_dir, 'silent.mp4')
    if not K.concat_clips(clips, silent, xfade=XFADE):
        return fail('concat failed')
    total = float(K.probe(silent)['duration'] or 0.0)
    if total <= 0.0:
        return fail('assembled video has no duration')
    log(f'assemble: {total:.2f}s of picture')

    tracks = []
    for b in beats:
        tracks.append((os.path.join(out_dir, b['say_file']), _picture_start(rows.index(b['row'])) + SAY_OFFSET, 0.0))

    horn = os.path.join(audio_dir, 'sfx_horn.wav')
    if K.synth_sfx('horn', horn, seconds=0.5, seed=episode):
        tracks.append((horn, _picture_start(0) + 0.4, HORN_GAIN_DB))
    if 2 in rows:
        splash = os.path.join(audio_dir, 'sfx_splash.wav')
        if K.synth_sfx('splash', splash, seconds=1.0, seed=episode + 1):
            tracks.append((splash, _picture_start(rows.index(2)) + 0.6, SPLASH_GAIN_DB))

    bed = os.path.join(audio_dir, 'bed.wav')
    if K.music_bed(bed, seconds=total, mood='gentle', age_band=SERIES['age_band'], seed=episode, log_fn=log):
        tracks.append((bed, 0.0, BED_GAIN_DB))
        manifest['models_used'].append({'role': 'music', 'model': 'MuseScore_General.sf3'})
        manifest['licences'].append({'model': 'MuseScore_General.sf3', 'licence': 'MIT'})
    else:
        log('music: no bed this run — the voice carries the episode')

    mixed = os.path.join(audio_dir, 'mix.wav')
    if not K.mix_audio(tracks, mixed, total):
        return fail('audio mix failed')

    faded_v = os.path.join(out_dir, 'faded.mp4')
    faded_a = os.path.join(audio_dir, 'mix_faded.wav')
    if not _fade_tail(silent, faded_v, total):
        return fail('video fade-out failed')
    if not _fade_tail(mixed, faded_a, total, audio=True):
        return fail('audio fade-out failed')

    episode_mp4 = os.path.join(out_dir, 'episode.mp4')
    if not K.mux(faded_v, faded_a, episode_mp4):
        return fail('mux failed')
    if not K.write_poster(episode_mp4, os.path.join(out_dir, 'poster.jpg')):
        return fail('poster failed')

    info = K.probe(episode_mp4)
    dur = float(info['duration'] or 0.0)
    manifest['duration_s'] = round(dur, 2)
    manifest['story'] = [
        {'prompt': b['prompt'], 'sentence': b['sentence'], 'still': b['still'], 'say_file': b['say_file']}
        for b in beats
    ]
    floor = TEST_MIN_SECONDS if test_mode else SERIES['episode_seconds'] * 0.8
    if dur < floor:
        return fail(f'episode is {dur:.2f}s, expected at least {floor:.1f}s')
    if not info['has_audio']:
        return fail('episode has no audio stream')
    if (info['w'], info['h']) != (K.W, K.H):
        return fail(f'episode is {info["w"]}x{info["h"]}, expected {K.W}x{K.H}')
    done(STAGES[4])

    manifest['ok'] = True
    manifest['reason'] = 'ok'
    log(f'delivered: {episode_mp4} ({dur:.2f}s)')
    K.write_manifest(out_dir, manifest)
    return manifest


if __name__ == '__main__':
    sys.exit(K.run_cli(sys.modules[__name__]))
