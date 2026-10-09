# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Voice QUALITY (texture) measurement — how ROUGH a voice is, not how big.

`voice_qc` / `voice_metrics` answer "whose body is this?" (F0, vocal-tract
length, age band). Neither answers "does this voice sound worn?", which is a
different axis entirely: a 60-year-old captain and a 25-year-old announcer can
measure identically on pitch and tract and sound nothing alike.

Four Praat measures, each pointing the same way when a voice is rough:
    HNR      harmonics-to-noise, dB      LOW  = breathy / noisy phonation
    jitter   cycle-to-cycle period, %    HIGH = unstable pitch
    shimmer  cycle-to-cycle amplitude, % HIGH = unstable loudness
    CPPS     cepstral peak prominence    LOW  = weak periodic structure

`wear` is the z-sum of those four against a population, signed so that HIGHER
means rougher.

THE NOISE-FLOOR GUARD IS NOT OPTIONAL. A hissy room depresses HNR and CPPS in
exactly the same direction a rough voice does, so a ranking without it returns
the worst MICROPHONES in a bank rather than the roughest people — 8 of 101
donations were excluded on this in the teen-bench build. `floor_db` is the RMS of
the quietest 5 % of frames against the overall RMS; a recording whose floor sits
close to its speech is a noisy capture, whatever its HNR says.

Praat lives in an isolated venv, so measurement is a subprocess + JSON, the same
shape voice_qc uses.

    python3 voice_texture.py a.wav b.wav ...          # measure and rank
"""

import json
import os
import subprocess
from zyg_workflows import paths

_PRAAT_PY = str(paths.ZYG_MODELS_DIR / 'voice_analysis' / '.venv' / 'bin' / 'python')

# Population reference from the 2026-08-12 donation-bank scan, kept so a single
# voice can be scored without re-measuring a whole bank.
POP = {'hnr': 11.76, 'shimmer': 10.41, 'jitter': 2.34, 'cpps': 10.27}
POP_SD = {'hnr': 3.60, 'shimmer': 3.20, 'jitter': 0.95, 'cpps': 2.40}

_PRAAT_SRC = r"""
import json, sys
import parselmouth
from parselmouth.praat import call

out = []
for path in sys.argv[1:]:
    try:
        snd = parselmouth.Sound(path)
        pitch = snd.to_pitch(time_step=0.01, pitch_floor=55.0, pitch_ceiling=350.0)
        f0v = [v for v in pitch.selected_array['frequency'] if v > 0]
        pp = call([snd, pitch], 'To PointProcess (cc)')
        jit = call(pp, 'Get jitter (local)', 0, 0, 1e-4, 0.02, 1.3) * 100.0
        shim = call([snd, pp], 'Get shimmer (local)', 0, 0, 1e-4, 0.02, 1.3, 1.6) * 100.0
        harm = call(snd, 'To Harmonicity (cc)', 0.01, 55.0, 0.1, 1.0)
        hnr = call(harm, 'Get mean', 0, 0)
        pcs = call(snd, 'To PowerCepstrogram', 60.0, 0.002, 5000.0, 50.0)
        cpps = call(pcs, 'Get CPPS', 'no', 0.01, 0.001, 60.0, 330.0, 0.05,
                    'Parabolic', 0.001, 0.05, 'Straight', 'Robust')
        # noise floor: quietest 5 % of 20 ms frames vs overall
        import numpy as np
        d = snd.values[0]
        sr = int(snd.sampling_frequency)
        w = max(1, int(0.02 * sr))
        n = len(d) // w
        fr = np.sqrt((d[:n * w].reshape(n, w) ** 2).mean(axis=1) + 1e-12)
        q = float(np.quantile(fr, 0.05))
        overall = float(np.sqrt((d ** 2).mean() + 1e-12))
        floor_db = 20.0 * np.log10(max(q, 1e-9) / max(overall, 1e-9))
        out.append({'path': path, 'ok': True,
                    'f0': float(sum(f0v) / len(f0v)) if f0v else 0.0,
                    'voiced_frames': len(f0v),
                    'jitter': float(jit), 'shimmer': float(shim),
                    'hnr': float(hnr), 'cpps': float(cpps),
                    'floor_db': float(floor_db),
                    'dur': float(snd.get_total_duration())})
    except Exception as exc:
        out.append({'path': path, 'ok': False, 'error': str(exc)})
print(json.dumps(out))
"""


def measure(paths, log_fn=None) -> list[dict]:
    """Praat metrics for each wav. Returns rows (ok=False on failure)."""
    log = log_fn or (lambda m: None)
    if not os.path.isfile(_PRAAT_PY):
        log('[texture] no praat interpreter')
        return [{'path': p, 'ok': False, 'error': 'no praat venv'} for p in paths]
    rows: list[dict] = []
    for i in range(0, len(paths), 40):  # keep argv sane
        chunk = list(paths[i : i + 40])
        r = subprocess.run([_PRAAT_PY, '-c', _PRAAT_SRC, *chunk], capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            log(f'[texture] praat failed: {r.stderr.strip()[-300:]}')
            rows += [{'path': p, 'ok': False, 'error': 'praat failed'} for p in chunk]
            continue
        try:
            rows += json.loads(r.stdout.strip().splitlines()[-1])
        except Exception as exc:
            log(f'[texture] unparseable praat output ({exc})')
            rows += [{'path': p, 'ok': False, 'error': 'unparseable'} for p in chunk]
    return rows


def wear(row: dict, pop: dict = None, sd: dict = None) -> float:
    """Signed z-sum: higher is rougher. HNR and CPPS are inverted because a rough
    voice scores LOW on both."""
    pop, sd = pop or POP, sd or POP_SD
    return (
        ((pop['hnr'] - row['hnr']) / sd['hnr'])
        + ((row['shimmer'] - pop['shimmer']) / sd['shimmer'])
        + ((row['jitter'] - pop['jitter']) / sd['jitter'])
        + ((pop['cpps'] - row['cpps']) / sd['cpps'])
    )


def scan(paths, floor_min_db: float = -26.0, min_voiced: int = 120, log_fn=None) -> list[dict]:
    """Measure, score, and REJECT noisy captures. Sorted roughest first.

    `floor_min_db` rejects a recording whose quiet frames sit within 26 dB of its
    speech — that is a noisy room, and it depresses HNR/CPPS exactly the way a
    rough voice does. Rejected rows are returned with `rejected` set rather than
    dropped, so a bank scan can say what it threw away.
    """
    rows = [r for r in measure(paths, log_fn=log_fn) if r.get('ok')]
    for r in rows:
        r['wear'] = wear(r)
        if r['voiced_frames'] < min_voiced:
            r['rejected'] = f'only {r["voiced_frames"]} voiced frames'
        elif r['floor_db'] > floor_min_db:
            r['rejected'] = f'noisy capture (floor {r["floor_db"]:.1f} dB)'
        else:
            r['rejected'] = None
    rows.sort(key=lambda r: -r['wear'])
    return rows


if __name__ == '__main__':
    import sys

    rows = scan(sys.argv[1:], log_fn=print)
    print(f'{"voice":34s} {"wear":>6s} {"F0":>6s} {"HNR":>6s} {"jit%":>5s} {"shim%":>6s} {"CPPS":>6s} {"floor":>6s}')
    for r in rows:
        tag = '  REJECTED: ' + r['rejected'] if r['rejected'] else ''
        print(
            f'{os.path.basename(r["path"])[:34]:34s} {r["wear"]:6.2f} '
            f'{r["f0"]:6.1f} {r["hnr"]:6.2f} {r["jitter"]:5.2f} '
            f'{r["shimmer"]:6.2f} {r["cpps"]:6.2f} {r["floor_db"]:6.1f}{tag}'
        )
