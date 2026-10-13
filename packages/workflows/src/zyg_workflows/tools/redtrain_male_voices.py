# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Re-render "The Red Train to the Sea" with ten different MALE voices.

The male sibling of tools/farmyard_ref/voice_sweep.py, run on job 1ba342d5cd75
(shipped adult_female).  Everything the song IS is held fixed -- the plan, the
melody, the lyrics, D major, 117 bpm, the ukulele/glockenspiel arrangement and
the same a2a melody-conditioned graph at the same denoise that produced the
shipped master -- so the only thing that moves between takes is the singer
clause at the head of the ACE-Step caption plus that take's own seed.

A "voice" is therefore the PAIR (caption, seed) and both are recorded, so
whichever the operator picks can be reproduced exactly.

THE TEN CLAUSES MIRROR THE FEMALE SWEEP one for one (control / bright / rich /
soft / cartoon / folk / theatre / husky / teacher / pop) so the two benches are
comparable arm by arm, and every one keeps "adult male ... grown-up man" so the
caption cannot drift towards a child voice -- the one thing gate_singer_age
documents it CANNOT separate.

THE GATE RUNS BUT DOES NOT ENFORCE.  T.SINGERS['adult_male'] carries band
110-285 Hz drawn from n=6 takes on the PRAAT meter, and that meter was retired
2026-09-06 for censoring sung medians above its 550 Hz ceiling; the gate now
measures with RMVPE, which is a different instrument reading against a band that
was never set on it.  Comparing the two would be a category error, so
ZYG_KIDSMUSIC_SINGER_ENFORCE=0: every number is recorded, nothing is failed on
it, and this sweep is itself the 20-render male measurement the SINGERS comment
asks for before 285 stops being provisional.
"""

import json
import logging as _zyg_logging
import os
import sys
import time
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)
# Measure, do not judge -- see the module docstring.
os.environ['ZYG_KIDSMUSIC_SINGER_ENFORCE'] = '0'

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


JOB = os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75')
OUT = os.path.join(JOB, 'male_voices')

VOICES = [
    ('m01_warm_control', 'clear adult male lead vocal, warm friendly grown-up man singing'),
    ('m02_bright_tenor', 'bright adult male lead vocal, light tenor, crisp cheerful grown-up man singing'),
    ('m03_rich_baritone', 'rich adult male lead vocal, warm baritone, rounded lower register, grown-up man singing'),
    ('m04_soft_gentle', 'soft adult male lead vocal, gentle and breathy, grown-up man singing close to the microphone'),
    (
        'm05_playful_cartoon',
        'playful adult male lead vocal, animated cartoon character tone, grown-up man singing with a smile',
    ),
    (
        'm06_folk_storyteller',
        'clear adult male lead vocal, plain unaffected folk storyteller tone, grown-up man singing',
    ),
    (
        'm07_theatre_belt',
        'strong adult male lead vocal, musical theatre belt, projected and confident grown-up man singing',
    ),
    ('m08_husky_bass', 'husky adult male lead vocal, deep gravelly bass, slightly raspy grown-up man singing'),
    ('m09_nursery_teacher', 'sweet adult male lead vocal, kind nursery teacher tone, calm grown-up man singing'),
    ('m10_clean_pop', 'polished adult male lead vocal, clean modern pop tone, tight controlled grown-up man singing'),
]
# Fixed per take so the whole sweep is reproducible. 1669026733 is the seed the
# shipped (female) master was rendered with, kept on the control arm so the one
# variable against the delivered song is the singer clause.
SEEDS = [1669026733, 314159265, 271828182, 161803398, 141421356, 577215664, 662606957, 299792458, 602214076, 173205080]

WHY = {
    'm01_warm_control': 'The stock male caption, unchanged — the control.',
    'm02_bright_tenor': 'The lightest of the ten; closest in energy to the shipped female take.',
    'm03_rich_baritone': 'Rounded and low; the natural home of a male nursery song.',
    'm04_soft_gentle': 'Close-mic and quiet, for the bedtime end of a set.',
    'm05_playful_cartoon': 'Broad character tone — a train driver, not a singer.',
    'm06_folk_storyteller': 'Plain and unperformed; no studio sheen.',
    'm07_theatre_belt': 'Projected and confident; the loudest ask of the ten.',
    'm08_husky_bass': 'The darkest and grainiest ask of the ten.',
    'm09_nursery_teacher': 'Kind and calm — sung to the child, not at them.',
    'm10_clean_pop': 'Polished and tight; the most produced of the ten.',
}


def log(msg):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {msg}')


def main():
    os.makedirs(OUT, exist_ok=True)
    plan = json.load(open(os.path.join(JOB, 'song.json')))

    # The a2a leg needs a wav; the job kept the melody as mp3.
    melody_wav = os.path.join(OUT, '_melody.wav')
    if not os.path.isfile(melody_wav):
        if not K._ff(
            ['-i', os.path.join(JOB, 'melody.mp3'), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', melody_wav],
            log_fn=log,
        ):
            raise SystemExit('could not decode melody.mp3')
    log(f'melody staged: {melody_wav}')

    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable (ComfyUI down or checkpoint missing)')

    male = T.SINGERS['adult_male']
    band = male['band']
    results = []
    for i, ((key, caption), seed) in enumerate(zip(VOICES, SEEDS), 1):
        take = os.path.join(OUT, f'{key}.mp3')
        master = os.path.join(OUT, f'{key}_master.mp3')
        log(f'--- {i}/10  {key}  seed={seed}')
        log(f'    caption: {caption}')

        # Cast this take's caption as a singer the plan holds. ace_prompt and
        # gate_singer_age both read T.SINGERS, so one edit steers both; every
        # other field is the adult_male row unchanged.
        T.SINGERS[key] = dict(male, label=key, caption=caption)
        plan['brief']['singer'] = key

        rec = {}
        t0 = time.time()
        if os.path.isfile(take) and os.path.getsize(take) > 10_000:
            log('    take already on disk — reusing')
            got = take
            rec = {'ran': True, 'reason': 'reused existing file'}
        else:
            got = K.ace_render(
                plan, take, seed=seed, melody_wav=melody_wav, log_fn=log, info=rec, should_abort=lambda: False
            )
        row = {
            'key': key,
            'display': key.split('_', 1)[1].replace('_', ' ').title(),
            'why': WHY[key],
            'caption': caption,
            'seed': seed,
            'render_s': round(time.time() - t0, 1),
            'ace_tags': rec.get('ace_tags', ''),
            'workflow': rec.get('workflow', ''),
            'melody_conditioned': rec.get('melody_conditioned'),
            'a2a_denoise': rec.get('a2a_denoise'),
            'checkpoint': rec.get('checkpoint', ''),
            'ok': bool(got),
            'reason': rec.get('reason', ''),
        }

        if got:
            # Same master chain as the delivered song, so the ten compare at
            # equal loudness rather than by whichever came out loudest.
            fed, trimmed = K.trim_tail(got, os.path.join(OUT, '_trim.wav'), log_fn=log)
            pre = K.prelevel(fed, os.path.join(OUT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=log)
            norm = {}
            try:
                from zyg_workflows import audio_mix

                mw = os.path.join(OUT, '_master.wav')
                if audio_mix.master(pre, mw, i=-14.0, tp=-1.0, log_fn=log, result=norm):
                    K._mp3(mw, master, log_fn=log, br='256k')
            except Exception as e:  # noqa: BLE001
                log(f'    master failed: {type(e).__name__}: {e}')
            row['master'] = os.path.basename(master) if os.path.isfile(master) else ''
            row['loudnorm'] = norm.get('normalization_type')
            row['trimmed_s'] = trimmed

            g = K.gate_singer_age(master if os.path.isfile(master) else got, plan, log_fn=log)
            c = g.get('checks') or {}
            row['gate'] = {
                'status': g['status'],
                'detail': g['detail'],
                'enforced': g.get('enforced'),
                'f0_median_hz': c.get('f0_median_hz'),
                'f0_p10_hz': c.get('f0_p10_hz'),
                'f0_p90_hz': c.get('f0_p90_hz'),
                'sharpness_acum': c.get('sharpness_acum'),
                'hf_ratio_2k8k': c.get('hf_ratio_2k8k'),
                'agreement_cents': c.get('agreement_cents'),
                'tracker': c.get('tracker'),
                'vocal_over_mix_db': (c.get('separation') or {}).get('ratio_db'),
            }
            log(f'    F0 {row["gate"]["f0_median_hz"]} Hz  [{row["gate"]["status"]}]')
        else:
            log(f'    FAILED: {row["reason"]}')

        results.append(row)
        json.dump(
            {
                'song': 'The Red Train to the Sea',
                'job': '1ba342d5cd75',
                'cast': 'adult_male',
                'band_hz': list(band),
                'band_note': (
                    '110-285 Hz was set on PRAAT from n=6; the gate '
                    'now measures with RMVPE. Recorded, not enforced '
                    '— this sweep is the male re-measurement.'
                ),
                'held_fixed': ('plan, melody (a2a), lyrics, D major, 117 bpm, arrangement, master chain'),
                'shipped_female_seed': 1669026733,
                'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'takes': results,
            },
            open(os.path.join(OUT, 'index.json'), 'w'),
            indent=1,
        )

    for tmp in ('_trim.wav', '_pre.wav', '_master.wav'):
        try:
            os.remove(os.path.join(OUT, tmp))
        except OSError as _exc:
            _zyg_log.debug('intermediate take cleanup skipped: %s', _exc)
    try:
        os.remove(
            os.path.join(
                str(paths.ZYG_COMFY_INPUT),
                f'kidsmusic_melody_{os.getpid()}.wav',
            )
        )
    except OSError as _exc:
        _zyg_log.debug('staged melody cleanup skipped: %s', _exc)

    log('=== SUMMARY ===')
    for r in results:
        g = r.get('gate') or {}
        log(
            f'{r["key"]:22s} seed={r["seed"]:<11d} '
            f'{"OK " if r["ok"] else "FAIL"} '
            f'F0={g.get("f0_median_hz")} {g.get("status", "-")}'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
