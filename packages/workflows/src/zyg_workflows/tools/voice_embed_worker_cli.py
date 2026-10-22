# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.voice_embed_worker`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.voice_embed_worker` still reaches it.

This file imports nothing from `zyg_workflows` on purpose: `vocal_analysis.EMBED_WORKER`
runs the library module by absolute path with the NeMo venv's python, where the package is
not importable, and its connector reaches this sibling by directory instead.
"""

import json
import os
import sys


def main(argv):
    src, dst = argv[0], argv[1]
    out = {
        'ok': False,
        'model': os.environ.get('ZYG_TITANET_MODEL', 'titanet_large'),
        'dim': None,
        'embeddings': {},
        'errors': {},
        'error': '',
    }
    try:
        import numpy as np
        import torch
        from nemo.collections.asr.models import EncDecSpeakerLabelModel

        items = json.load(open(src)).get('items') or []
        model = EncDecSpeakerLabelModel.from_pretrained(out['model'])
        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()
        for it in items:
            try:
                with torch.no_grad():
                    v = model.get_embedding(it['wav']).detach().cpu().numpy().reshape(-1)
                v = v.astype('float64')
                n = float(np.linalg.norm(v)) or 1.0
                out['embeddings'][it['id']] = [round(float(x), 6) for x in (v / n)]
                out['dim'] = int(v.size)
            except Exception as e:  # noqa: BLE001 — per item
                out['errors'][it['id']] = f'{type(e).__name__}: {e}'[:200]
        out['ok'] = bool(out['embeddings'])
    except Exception as e:  # noqa: BLE001
        out['error'] = f'{type(e).__name__}: {e}'[:300]
    with open(dst, 'w') as fh:
        json.dump(out, fh)
    print(
        json.dumps({'ok': out['ok'], 'n': len(out['embeddings']), 'errors': len(out['errors']), 'error': out['error']})
    )
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
