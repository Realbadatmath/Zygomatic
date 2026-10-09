# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kidsmusic_a2a_spike.py — ONE throwaway job: can ACE-Step follow the composed melody?

Not a design. A spike, in its own workflow file, so the live path is untouched
whatever the answer.

THE QUESTION. The two audio legs share a key, a tempo and a lyric and are
different tunes, because no note data reaches ACE-Step at all. The only route
that could change that is audio2audio: encode the score render to a latent and
start the sampler from it instead of from noise.

WHAT IS UNVERIFIED. EmptyAceStep1.5LatentAudio returns
{samples, type, downscale_ratio_temporal} while VAEEncodeAudio returns {samples}
alone — so the latent contract between them is unproven, and that is exactly the
kind of thing a spike is for.

ACCEPTANCE. The same chroma test that established the negative must clear the
cross-song null at z > 2. Anything less and the relabel ("ACE-Step variation —
same key and lyric, different tune") is the answer and this closes.

Usage: python kidsmusic_a2a_spike.py [--denoise 0.55] [--out DIR]
"""

import json
import os
import shutil
import subprocess
import sys
import time

from zyg_workflows import paths

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def main(argv):
    from zyg_workflows import kids_music_service as K
    from zyg_workflows import kids_music_theory as T

    denoise = 0.55
    if '--denoise' in argv:
        denoise = float(argv[argv.index('--denoise') + 1])
    out_dir = (
        argv[argv.index('--out') + 1] if '--out' in argv else str(paths.tmp_dir() / f'a2a_spike_{int(time.time())}')
    )
    os.makedirs(out_dir, exist_ok=True)
    log = lambda m: print(m, flush=True)  # noqa: E731

    # 1. Compose and render the score leg — this is the melody to condition on.
    brief = {
        'theme': 'a dinosaur who lost his socks',
        'age_band': 'preschool',
        'mood': 'happy',
        'seconds': 40,
        'sung': True,
        'singer': T.DEFAULT_SINGER,
    }
    plan = T.compose_best(T._normalise_brief(brief), candidates=12, log_fn=None)
    plan['lyrics_block'] = '[verse]\nBlue socks on my foot\nThey are lost in the zoo'
    json.dump(plan, open(os.path.join(out_dir, 'song.json'), 'w'), indent=1)
    midi = K.write_midi(plan, os.path.join(out_dir, 'melody.mid'), log_fn=log)
    wav = os.path.join(out_dir, 'melody.wav')
    if not K.render_soundfont(midi, wav, log_fn=log):
        log('spike: score render failed')
        return 2

    # 2. Stage it where ComfyUI's LoadAudio can see it.
    from zyg_workflows import _comfy_client as _cc

    comfy_in = str(paths.ZYG_COMFY_INPUT)
    staged = os.path.join(comfy_in, 'kidsmusic_melody.wav')
    shutil.run = None
    subprocess.run(
        ['ffmpeg', '-y', '-v', 'error', '-i', wav, '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', staged], check=False
    )
    log(f'spike: staged {staged}')

    # 3. Submit the spike graph.
    seconds = float(plan['seconds'])
    try:
        wf = _cc.load_workflow('ace_step_kidsong_a2a_spike')
        outputs = _cc.submit(
            wf,
            overrides={
                '1': {'ckpt_name': K.ACE_CHECKPOINT},
                '2': {
                    'tags': K.ace_prompt(plan),
                    'lyrics': plan['lyrics_block'],
                    'seed': 12345,
                    'bpm': int(plan['bpm']),
                    'duration': seconds,
                    'timesignature': str(plan['ts']),
                    'keyscale': plan['key']['ace_keyscale'],
                },
                '5': {'seed': 12345, 'denoise': denoise},
                '8': {'audio': 'kidsmusic_melody.wav'},
            },
            timeout_s=900,
        )
    except Exception as e:  # noqa: BLE001
        log(f'spike: SUBMIT FAILED — {type(e).__name__}: {e}')
        log('spike: the latent contract is the likely cause; this is the answer the spike existed to get.')
        return 1
    got = [p for p in outputs if p.lower().endswith(('.mp3', '.flac', '.wav'))]
    if not got:
        log('spike: job completed but produced no audio')
        return 1
    take = os.path.join(out_dir, 'a2a.mp3')
    shutil.copy2(got[0], take)
    log(f'spike: got {take}')

    # 4. ACCEPTANCE: the chroma test against the cross-song null.
    km = os.path.join(HERE, 'output', 'kidsmusic')
    nulls = [
        os.path.join(km, d, 'song.json')
        for d in sorted(os.listdir(km))
        if os.path.isfile(os.path.join(km, d, 'song.json'))
    ][:4]
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(HERE, 'scripts', 'kidsmusic_chroma_test.py'),
            take,
            os.path.join(out_dir, 'song.json'),
            '--null',
        ]
        + nulls,
        capture_output=True,
        text=True,
        timeout=900,
    )
    log(r.stdout.strip() or r.stderr[-400:])
    try:
        res = json.loads(r.stdout[r.stdout.find('{') :])
    except Exception:  # noqa: BLE001
        return 1
    ok = bool(res.get('z', 0) > 2.0)
    log('')
    log(
        f'SPIKE VERDICT: z = {res.get("z")} — '
        + (
            'FOLLOWS the composed melody: audio2audio is worth wiring'
            if ok
            else f'does NOT follow the composed melody at denoise {denoise}: the relabel stands and this closes'
        )
    )
    json.dump(
        {'denoise': denoise, 'chroma': res, 'follows': ok},
        open(os.path.join(out_dir, 'spike_result.json'), 'w'),
        indent=1,
    )
    return 0 if ok else 3


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
