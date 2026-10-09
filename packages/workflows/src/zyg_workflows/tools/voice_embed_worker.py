#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_embed_worker.py — TitaNet-large voice embeddings over a JSON contract.

Runs INSIDE models/diarization/.venv (NeMo 2.7.3, torch 2.13/cu130), invoked as a
subprocess by vocal_analysis.py — the same isolation diarize_sortformer.py uses,
so NeMo's pins never meet the production agents venv.

Model: nvidia titanet_large (speakerverification_en_titanet_large), CC-BY-4.0,
already in ~/.cache/torch/NeMo from the diarization install; no download. It was
trained on SPEECH (VoxCeleb, Fisher, Switchboard, LibriSpeech, SRE). On sung,
demucs-separated stems it is an instrument that must be calibrated before its
numbers mean anything — see tools/voice_analysis_calibrate.py.

Usage:  python voice_embed_worker.py IN.json OUT.json
  IN.json   {"items": [{"id": "...", "wav": "/abs/16k_mono.wav"}, ...]}
  OUT.json  {"ok": true, "model": "titanet_large", "dim": 192,
             "embeddings": {"<id>": [unit-norm floats]}, "errors": {"<id>": "..."}}
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
