# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.lyric_align_worker`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.lyric_align_worker` still reaches it.
"""

import json
import os
import sys

from zyg_workflows.tools.lyric_align_worker import _transcribe


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    src, dst = argv[0], argv[1]
    device = argv[argv.index('--device') + 1] if '--device' in argv else 'cuda'
    model_name = os.environ.get('ZYG_LYRIC_ASR_MODEL', 'large-v3')
    out = {'ok': False, 'model': model_name, 'error': ''}
    try:
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(model_name, device=device, compute_type='float16' if device == 'cuda' else 'int8')
        except Exception:  # noqa: BLE001 — no GPU room
            model = WhisperModel(model_name, device='cpu', compute_type='int8')
        if src.endswith('.json'):
            items = json.load(open(src)).get('items') or []
            out['results'] = {
                it['id']: _transcribe(model, it['wav'], it.get('chunks'), it.get('prompt')) for it in items
            }
            out['ok'] = any(r['ok'] for r in out['results'].values())
        else:
            out.update(_transcribe(model, src))
    except Exception as e:  # noqa: BLE001
        out['error'] = f'{type(e).__name__}: {e}'[:300]
    with open(dst, 'w') as fh:
        json.dump(out, fh)
    print(
        json.dumps(
            {
                'ok': out['ok'],
                'words': len(out.get('words') or []),
                'items': len(out.get('results') or {}),
                'error': out['error'],
            }
        )
    )
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
