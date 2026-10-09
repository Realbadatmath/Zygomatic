# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Does the Warm Control voice land MALE on the FIRST take of a new song?

Warm Control is (stock male caption, seed 1669026733) on the a2a graph. On Red
Train that pair sang at 221 Hz; on the bumblebee song (job 19387e019f27) the
same pair sang 372 Hz and two re-seeds sang 331 and 415, so the song shipped as
the instrumental score render. The register is bimodal under a2a and the
melody the sampler starts from is written in a female tessitura (D4-B4), so the
seed is only weighting a coin.

This bench asks which CONDITIONING makes the first take male, holding caption,
seed, lyrics, bpm, key and denoise fixed. One seed per song x arm, seed
1669026733 only — the first take is the claim being tested.

  A  base     melody.mid rendered as the pipeline renders it today (the null)
  B  rb12     A pitch-shifted -12 st by rubberband, formants following
              (the Red Train fallback lever)
  C  mid12    every pitched MIDI track -12 st, rendered through the SoundFont
  D  lead12   the Melody track only -12 st; chords, bass, drums untouched

Every take records F0 (gate_singer_age), key/tempo survival (gate_audio) and
chroma_follow z against the cross-song null, because a male take that stopped
following the composed tune has not fixed anything.

Results: output/kidsmusic/_male_octave_bench/results.json (written after every
take; a rerun skips takes already on disk).
"""

import json
import logging as _zyg_logging
import os
import sys
import time
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
sys.path.insert(0, os.path.join(CREWS, 'tools'))
os.chdir(CREWS)
os.environ['ZYG_KIDSMUSIC_SINGER_ENFORCE'] = '0'

import mido  # noqa: E402

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
import rubberband_r3 as RB  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

SEED = 1669026733
OUT = os.path.join(CREWS, 'output/kidsmusic/_male_octave_bench')
SONGS = [
    '19387e019f27',  # bumblebee — failed 372/331/415 in the live run
    'c7284ed06145',  # yellow digger — passed 221.5 on this seed
    '1ba342d5cd75',  # red train — where Warm Control was picked
    '0fc29420eb5a',  # cow says moo, silly 123
    '1da0a2c6f257',  # snail, curious 106
    '36039a6c117a',  # first snow, gentle 94
    '37159301a13c',  # dinosaur socks, early silly 129 F
    '3f2b407846b0',  # bath time, toddler gentle 90 C
    '5e42a3574fd4',  # frog, playful 121
    'e2cd9a19ef90',  # sleepy moon, lullaby 67 C
    'dd194f224b94',  # marching to school 112
    '6e0a355deadf',  # five ducklings, toddler playful 127 C
]
ARMS = [a for a in os.environ.get('BENCH_ARMS', 'base,rb12,mid12,lead12').split(',') if a]
if os.environ.get('BENCH_SONGS'):
    SONGS = [s for s in os.environ['BENCH_SONGS'].split(',') if s]


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def transpose_midi(src, dst, st, *, lead_only):
    mid = mido.MidiFile(src)
    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == 'track_name'), '')
        if lead_only and name != 'Melody':
            continue
        for msg in tr:
            if msg.type in ('note_on', 'note_off') and msg.channel != 9:
                msg.note = max(0, min(127, msg.note + st))
    mid.save(dst)


def split_arm(arm):
    """'lead12@t0.5' -> ('lead12', 0.5). No '@t' = the workflow's own 0.85.
    A 'cover-' prefix names the conditioning file handed to cover_wav instead
    of melody_wav; split_arm strips it (see is_cover)."""
    arm = arm.split('+', 1)[0]
    cond, _, t = arm.partition('@t')
    if cond.startswith('cover-'):
        cond = cond[len('cover-') :]
    return cond, (float(t) if t else None)


def is_cover(arm):
    return arm.startswith('cover-')


def seed_of(arm):
    """'lead12+2' -> SEED + 2: the takes run()'s re-seed loop would render."""
    _, plus, k = arm.partition('+')
    return SEED + (int(k) if plus else 0)


def with_lm_temperature(temp):
    """ace_render loads the workflow itself and exposes no LM sampling knob, so
    the bench patches node 2 on the way out of load_workflow. Restored by the
    caller."""
    from zyg_workflows import _comfy_client as cc

    orig = cc.load_workflow

    def patched(name):
        wf = orig(name)
        if temp is not None and isinstance(wf.get('2'), dict):
            wf['2']['inputs']['temperature'] = float(temp)
        return wf

    cc.load_workflow = patched
    return lambda: setattr(cc, 'load_workflow', orig)


def conditioning(job, arm, wd):
    arm, _temp = split_arm(arm)
    base = os.path.join(wd, 'cond_base.wav')
    if not os.path.isfile(base):
        K.render_soundfont(os.path.join(job, 'melody.mid'), base, log_fn=None)
    if arm == 'base':
        return base
    dst = os.path.join(wd, f'cond_{arm}.wav')
    if os.path.isfile(dst):
        return dst
    if arm == 'rb12':
        y, sr = RB._decode(base)
        out, _ver = RB.shift(y, sr, semitones=-12.0, formant='follow')
        RB._encode(out, sr, dst)
    else:
        m = os.path.join(wd, f'cond_{arm}.mid')
        transpose_midi(os.path.join(job, 'melody.mid'), m, -12, lead_only=(arm == 'lead12'))
        K.render_soundfont(m, dst, log_fn=None)
    return dst


def main():
    os.makedirs(OUT, exist_ok=True)
    # Two bench processes must not share one results file: each rewrites the
    # whole list after every take.
    res_path = os.path.join(OUT, os.environ.get('BENCH_RESULTS', 'results.json'))
    rows = json.load(open(res_path)) if os.path.isfile(res_path) else []
    done = {(r['song'], r['arm']) for r in rows if r.get('f0') is not None}
    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable')
    lo, hi = T.SINGERS['adult_male']['band']
    for sid in SONGS:
        job = os.path.join(CREWS, 'output/kidsmusic', sid)
        wd = os.path.join(OUT, sid)
        os.makedirs(wd, exist_ok=True)
        plan = json.load(open(os.path.join(job, 'song.json')))
        plan['brief']['singer'] = 'adult_male'
        nulls = K._null_plans(exclude_dir=job)
        for arm in ARMS:
            if (sid, arm) in done:
                continue
            t0 = time.time()
            row = {
                'song': sid,
                'arm': arm,
                'seed': seed_of(arm),
                'theme': plan['brief'].get('theme'),
                'bpm': plan.get('bpm'),
                'key': plan['key'].get('ace_keyscale'),
            }
            try:
                cond = conditioning(job, arm, wd)
                take = os.path.join(wd, f'{arm}.mp3')
                rec = {}
                row['lm_temperature'] = split_arm(arm)[1] or 0.85
                if os.path.isfile(take) and os.path.getsize(take) > 10_000:
                    got = take
                else:
                    restore = with_lm_temperature(split_arm(arm)[1])
                    try:
                        if is_cover(arm):
                            got = K.ace_render(plan, take, seed=seed_of(arm), cover_wav=cond, log_fn=None, info=rec)
                        else:
                            got = K.ace_render(plan, take, seed=seed_of(arm), melody_wav=cond, log_fn=None, info=rec)
                    finally:
                        restore()
                if not got:
                    row['error'] = f'render failed: {rec.get("reason")}'
                    raise RuntimeError(row['error'])
                row['mode'] = rec.get('mode')
                row['render_s'] = round(time.time() - t0, 1)
                g = K.gate_singer_age(got, plan, log_fn=None)
                c = g.get('checks') or {}
                row.update(
                    {
                        'f0': c.get('f0_median_hz'),
                        'p10': c.get('f0_p10_hz'),
                        'p90': c.get('f0_p90_hz'),
                        'male': (c.get('f0_median_hz') is not None and lo <= c['f0_median_hz'] <= hi),
                        'sharpness': c.get('sharpness_acum'),
                        'no_vocal': 'no vocal present' in (g.get('detail') or ''),
                        'vocal_db': (c.get('separation') or {}).get('ratio_db'),
                    }
                )
                ga = K.gate_audio(got, plan, leg='produced', want_clap=False, log_fn=None)
                ca = ga.get('checks') or {}
                row.update(
                    {
                        'detected_key': ca.get('detected_key'),
                        'key_match': ca.get('key_match'),
                        'bpm_relation': ca.get('bpm_relation'),
                    }
                )
                fo = K.chroma_follow(got, plan, nulls, log_fn=None)
                row.update({'follow_z': fo.get('z'), 'followed': fo.get('followed')})
            except Exception as e:  # noqa: BLE001
                row.setdefault('error', f'{type(e).__name__}: {e}')
            row['total_s'] = round(time.time() - t0, 1)
            rows = [r for r in rows if (r['song'], r['arm']) != (sid, arm)] + [row]
            json.dump(rows, open(res_path, 'w'), indent=1)
            log(
                f'{sid} {arm:6s} f0={row.get("f0")} male={row.get("male")} '
                f'key={row.get("key_match")} z={row.get("follow_z")} '
                f'{row.get("error", "")} ({row["total_s"]}s)'
            )

    log('=== SUMMARY (first take, seed %d) ===' % SEED)
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm and r.get('f0') is not None]
        m = sum(1 for r in rs if r['male'])
        k = sum(1 for r in rs if r.get('key_match') in ('exact', 'relative'))
        f = sum(1 for r in rs if r.get('followed'))
        log(f'{arm:6s} male {m}/{len(rs)}  key held {k}/{len(rs)}  followed {f}/{len(rs)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
