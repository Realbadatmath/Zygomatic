#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vb_speaker_bench -- does ECAPA actually tell one voice from another here?

The proof behind voice_ext/speaker.py's threshold. Takes the Abel narrator seed,
cuts it in HALF (two different sentences, same speaker), and takes one seed from
the reference pool (a different speaker entirely), then prints three cosines:

    same   abel_A  vs abel_B        -- must be high
    cross  abel_A  vs other         -- must be low
    cross  abel_B  vs other

PASS requires  same - max(cross) >= MARGIN (0.15). That margin is the whole
claim: anything above it means a threshold exists that admits the operator and
refuses everyone else. It says nothing about recordings of the operator -- see
docs/voice_bridge_speaker.md.

Run from ZYG_CREWS_ROOT (the legacy production tree) with its own venv, ZYG_LEGACY_VENV_PY:
    ../.venv/bin/python tools/vb_speaker_bench.py
    ../.venv/bin/python tools/vb_speaker_bench.py --other f01_warm_alto
"""

import argparse
import json
import os
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from zyg_workflows.voice_ext import speaker as S  # noqa: E402

ABEL = os.path.join(HERE, 'data', 'assets', 'voice_seeds', 'abel_narrator_seed.wav')
POOL = os.path.join(HERE, 'data', 'assets', 'voice_seeds', 'pool')
MARGIN = 0.15


def _half(src, dst, which):
    """Write the first or second half of a wav to dst."""
    with wave.open(src, 'rb') as w:
        total = w.getnframes()
        half = total // 2
        if which == 1:
            w.setpos(half)
            frames = w.readframes(total - half)
        else:
            frames = w.readframes(half)
        params = w.getparams()
    with wave.open(dst, 'wb') as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(params.framerate)
        out.writeframes(frames)
    return (total - half if which == 1 else half) / float(params.framerate)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        '--other',
        default='m01_warm_baritone',
        help='pool seed name to use as the cross-voice (default m01_warm_baritone)',
    )
    ap.add_argument('--margin', type=float, default=MARGIN)
    args = ap.parse_args(argv)

    other_wav = os.path.join(POOL, args.other + '.wav')
    for path in (ABEL, other_wav):
        if not os.path.exists(path):
            print('MISSING %s' % path)
            return 2

    manifest = os.path.join(POOL, 'manifest.json')
    other_desc = args.other
    if os.path.exists(manifest):
        with open(manifest, 'r', encoding='utf-8') as fh:
            voices = (json.load(fh) or {}).get('voices') or []
        for v in voices:
            if v.get('name') == args.other:
                other_desc = '%s (%s)' % (args.other, (v.get('description') or '')[:48])
                break

    tmpdir = tempfile.mkdtemp(prefix='vb_spk_bench_')
    try:
        a = os.path.join(tmpdir, 'abel_a.wav')
        b = os.path.join(tmpdir, 'abel_b.wav')
        sec_a = _half(ABEL, a, 0)
        sec_b = _half(ABEL, b, 1)

        print('abel half A   %5.2f s  %s' % (sec_a, os.path.basename(ABEL)))
        print('abel half B   %5.2f s  %s' % (sec_b, os.path.basename(ABEL)))
        print('other voice          %s' % other_desc)
        print('')

        ea = S._l2(S.embed_wav(a))
        eb = S._l2(S.embed_wav(b))
        eo = S._l2(S.embed_wav(other_wav))

        same = S._cosine(ea, eb)
        cross_a = S._cosine(ea, eo)
        cross_b = S._cosine(eb, eo)
        worst_cross = max(cross_a, cross_b)
        margin = same - worst_cross

        print('same  abel_A  vs abel_B   cosine  %+.4f' % same)
        print('cross abel_A  vs other    cosine  %+.4f' % cross_a)
        print('cross abel_B  vs other    cosine  %+.4f' % cross_b)
        print('')
        print('margin = same - worst cross = %+.4f  (need >= %.2f)' % (margin, args.margin))
        cfg = S.read_config()
        print('config: speaker_threshold=%.2f speaker_gate=%s' % (cfg['speaker_threshold'], cfg['speaker_gate']))
        ok = margin >= args.margin
        print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
        return 0 if ok else 1
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
