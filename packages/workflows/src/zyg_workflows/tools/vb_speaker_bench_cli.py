# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.vb_speaker_bench`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.vb_speaker_bench` still reaches it.
"""

import argparse
import json
import os
import sys
import tempfile

from zyg_workflows.tools import vb_speaker_bench as _mod
from zyg_workflows.tools.vb_speaker_bench import ABEL, MARGIN, POOL, _half
from zyg_workflows.voice_ext import speaker as S


def main(argv=None):
    ap = argparse.ArgumentParser(description=_mod.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
