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

import os
import sys

if __name__ == '__main__':  # the CLI lives in voice_embed_worker_cli
    if __package__:
        from zyg_workflows.tools.voice_embed_worker_cli import main as _cli_main
    else:
        # vocal_analysis.EMBED_WORKER runs this file by absolute path with the NeMo
        # venv's python, where zyg_workflows is not importable; the sibling is.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from voice_embed_worker_cli import main as _cli_main

    raise SystemExit(_cli_main(sys.argv[1:]))
