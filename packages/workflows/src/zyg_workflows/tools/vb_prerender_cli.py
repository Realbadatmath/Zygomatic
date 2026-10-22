# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.vb_prerender`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.vb_prerender` still reaches it.
"""

import argparse
import glob
import os
import time

import zyg_workflows.voice_ext.tts as TTS
from zyg_workflows.tools import vb_prerender as _mod
from zyg_workflows.tools.vb_prerender import _CREWS, clear_cache, collect


def main() -> int:
    ap = argparse.ArgumentParser(description=_mod.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        '--clear', action='store_true', help='delete the cached wavs before rendering (after a voice change)'
    )
    ap.add_argument('--list', action='store_true', help='print the phrases and exit, render nothing')
    ap.add_argument('--limit', type=int, default=0, help='render only the first N phrases (a smoke run)')
    args = ap.parse_args()
    # No --voice/--engine: the route renders with whatever `config.json` says, and
    # a flag that silently did not reach it would warm the cache under keys the
    # running bridge never asks for. Change the voice in the config, then --clear.

    phrases = collect(_CREWS)
    if args.limit > 0:
        phrases = phrases[: args.limit]

    if args.list:
        for src, text in phrases:
            print(f'{src:24s} {text}')
        print(f'-- {len(phrases)} phrases')
        return 0

    cfg = TTS.load_config()
    voice = cfg['voice_id']
    engine = TTS.choose_engine(cfg['engine'])
    free = TTS.free_vram_mb()
    print(
        f'voice={voice}  engine={engine} (config asked {cfg["engine"]})  '
        f'free VRAM={free:.0f} MB  gate={TTS.MIN_VRAM_MB} MB'
    )
    print(f'cache dir: {TTS.SAY_DIR}')
    if args.clear:
        print(f'--clear: removed {clear_cache()} cached wavs')
    print(f'{len(phrases)} phrases\n')

    head = f'{"#":>4}  {"state":<9} {"ms":>7}  phrase'
    print(head)
    print('-' * max(len(head), 72))

    rendered = cached = failed = 0
    agg = {'rendered': 0, 'cached': 0, 'failed': 0}
    t_all = time.time()
    fails = []
    for i, (_src, text) in enumerate(phrases, 1):
        t0 = time.time()
        res = TTS.ROUTES['prerender']({'phrases': [text]}, 'POST')
        ms = int((time.time() - t0) * 1000)
        for k in agg:
            agg[k] += int(res.get(k) or 0)
        if not res.get('ok'):
            state, failed = 'FAILED', failed + 1
            fails.append((text, (res.get('errors') or [{}])[0].get('error') or 'failed'))
        elif res.get('cached'):
            state, cached = 'cached', cached + 1
        else:
            state, rendered = 'rendered', rendered + 1
        print(f'{i:>4}  {state:<9} {ms:>7}  {text}', flush=True)

    wall = time.time() - t_all
    n_wav = len(glob.glob(os.path.join(TTS.SAY_DIR, '*.wav')))
    print('-' * max(len(head), 72))
    print(f'{len(phrases)} phrases: {rendered} rendered, {cached} cached, {failed} failed  (route counters: {agg})')
    print(f'wall {wall:.1f}s  ({wall / max(1, len(phrases)):.1f}s per phrase)  engine={engine}  voice={voice}')
    print(f'cache now holds {n_wav} wavs in {TTS.SAY_DIR}')
    for text, err in fails[:10]:
        print(f'  FAILED: {text[:60]!r}: {err}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
