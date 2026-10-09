#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""speaker_verify_worker -- ECAPA speaker embeddings, one process, JSON lines.

Runs in its OWN venv ($ZYG_MODELS_DIR/speaker_verify/.venv), not the
agents venv: speechbrain drags in a torch of its own and we want that torch to
be the CPU wheel. CPU on purpose -- one embedding of a 3 s clip costs ~150 ms
here and zero VRAM on the shared 4090.

Protocol, one JSON object per line on stdin, one per line on stdout:
    {"op": "ping"}                  -> {"ok": true, "loaded": bool}
    {"op": "embed", "wav": "/abs/path.wav"} -> {"ok": true, "emb": [192 floats], "ms": int}
    {"op": "quit"}                  -> {"ok": true} then exit
Anything unparseable or failing answers {"ok": false, "error": "..."} and the
loop continues -- the caller owns the decision to restart us.

The model loads once, on the first embed (not at start: a ping must be cheap).
After --idle seconds with no line on stdin the process exits, so an idle bridge
does not hold 30 MB of weights forever. ALL progress/warning noise stays on
stderr; stdout carries nothing but protocol lines.
"""

import argparse
import json
import os
import select
import sys
import time

MODEL_ID = 'speechbrain/spkrec-ecapa-voxceleb'
# This worker runs under its own venv, where zyg_workflows is not importable, so the
# ZYG_HOME / ZYG_MODELS_DIR roots are read here with the defaults paths.py uses.
_ZYG_HOME = os.environ.get('ZYG_HOME', '').strip() or os.path.expanduser('~')
_MODELS_DIR = os.environ.get('ZYG_MODELS_DIR', '').strip() or os.path.join(_ZYG_HOME, 'models')
_SV_ROOT = os.path.join(_MODELS_DIR, 'speaker_verify')
SAVEDIR = os.path.join(_SV_ROOT, 'ecapa')
HF_HOME = os.path.join(_SV_ROOT, 'hf')
EMB_DIM = 192

_model = None


def _load():
    """Import + load ECAPA. Kept out of module import so `ping` stays instant."""
    global _model
    if _model is not None:
        return _model
    os.environ.setdefault('HF_HOME', HF_HOME)
    # speechbrain and torch both like to write to stdout on first import; the
    # protocol lives there, so send anything they print to stderr instead.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier

        torch.set_num_threads(max(1, (os.cpu_count() or 4) // 4))
        _model = EncoderClassifier.from_hparams(source=MODEL_ID, savedir=SAVEDIR, run_opts={'device': 'cpu'})
    finally:
        sys.stdout = real_stdout
    return _model


def _embed(wav_path):
    if not wav_path or not os.path.exists(wav_path):
        raise ValueError('wav not found: %s' % wav_path)
    import soundfile as sf
    import torch

    model = _load()
    data, rate = sf.read(wav_path, dtype='float32', always_2d=True)
    if data.shape[1] > 1:  # mixdown; ECAPA wants mono
        data = data.mean(axis=1, keepdims=True)
    signal = torch.from_numpy(data[:, 0]).unsqueeze(0)
    if rate != 16000:
        import torchaudio

        signal = torchaudio.functional.resample(signal, rate, 16000)
    if signal.shape[1] < 1600:  # < 0.1 s is not a voice
        raise ValueError('audio too short: %d samples' % signal.shape[1])
    with torch.no_grad():
        emb = model.encode_batch(signal)
    return [float(x) for x in emb.reshape(-1).tolist()]


def _handle(req):
    op = (req.get('op') or '').strip().lower()
    if op == 'ping':
        return {'ok': True, 'loaded': _model is not None}
    if op == 'quit':
        return {'ok': True, 'bye': True}
    if op == 'embed':
        t0 = time.time()
        emb = _embed(req.get('wav'))
        if len(emb) != EMB_DIM:
            raise ValueError('unexpected embedding width %d' % len(emb))
        return {'ok': True, 'emb': emb, 'ms': int((time.time() - t0) * 1000)}
    raise ValueError('unknown op: %r' % op)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        '--idle', type=float, default=600.0, help='exit after this many seconds with no request (default 600)'
    )
    ap.add_argument('--warm', action='store_true', help='load the model before the first request')
    args = ap.parse_args(argv)

    if args.warm:
        try:
            _load()
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            sys.stderr.write('warm failed: %s\n' % exc)

    while True:
        ready, _, _ = select.select([sys.stdin], [], [], args.idle)
        if not ready:
            sys.stderr.write('idle %.0fs, exiting\n' % args.idle)
            return 0
        line = sys.stdin.readline()
        if not line:  # stdin closed: parent went away
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            resp = _handle(json.loads(line))
        except Exception as exc:  # noqa: BLE001 - protocol error channel
            resp = {'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}
        sys.stdout.write(json.dumps(resp) + '\n')
        sys.stdout.flush()
        if resp.get('bye'):
            return 0


if __name__ == '__main__':
    sys.exit(main())
