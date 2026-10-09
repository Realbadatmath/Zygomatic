# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""demucs_split.py — two-stem (vocals / accompaniment) separation, over stdout JSON.

Runs in the agents venv (which owns demucs + torch), NOT in the GUI process —
same subprocess+JSON contract voice_qc uses for Praat, and for the same reason:
importing torch into the dashboard would put a CUDA context in a process that
must stay light.

The demucs CLI is deliberately not used. Its writer goes through
torchaudio.save -> save_with_torchcodec, which raises ImportError on this box
(TorchCodec is not installed and installing it to write a wav would be a silly
dependency). The model API plus soundfile writes the same samples with nothing
extra installed.

Usage:  python demucs_split.py IN_AUDIO OUT_DIR [--device cuda|cpu]
Prints one JSON line: {'ok', 'vocals', 'rest', 'vocal_rms_db', 'rest_rms_db',
                       'ratio_db', 'seconds', 'device', 'error'}
"""

import json
import os
import sys
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


def main(argv):
    src, out_dir = argv[0], argv[1]
    device = 'cuda'
    if '--device' in argv:
        device = argv[argv.index('--device') + 1]
    out = {'ok': False, 'vocals': '', 'rest': '', 'error': ''}
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        if device == 'cuda' and not torch.cuda.is_available():
            device = 'cpu'
        model = get_model('htdemucs')
        model.eval()
        sr_model = model.samplerate  # 44100
        ch_model = model.audio_channels  # 2

        # Read via ffmpeg so mp3/flac/wav all work without torchaudio's decoder.
        import subprocess

        raw = subprocess.run(
            [exe('ffmpeg'), '-v', 'error', '-i', src, '-f', 'f32le', '-ac', str(ch_model), '-ar', str(sr_model), '-'],
            capture_output=True,
            timeout=600,
        )
        if raw.returncode != 0 or not raw.stdout:
            out['error'] = f'decode failed: {(raw.stderr or b"")[:200].decode("utf8", "replace")}'
            print(json.dumps(out))
            return 1
        wav = np.frombuffer(raw.stdout, dtype='<f4').reshape(-1, ch_model).T.copy()
        out['seconds'] = round(wav.shape[1] / sr_model, 2)

        ref = wav.mean(0)
        mean, std = float(ref.mean()), float(ref.std()) or 1.0
        x = torch.from_numpy((wav - mean) / std)[None]

        # CUDA FIRST, CPU ON OOM. ComfyUI holds most of the card between jobs
        # (measured: 45.4 of 47.4 GiB), so a separation started while a render is
        # resident dies with an OutOfMemoryError — and the singer gate correctly
        # fails CLOSED on it, which would cost a song its produced leg for a
        # reason that has nothing to do with the song. CPU is slower and always
        # available, and this measurement is not on a hot path.
        def _apply(dev):
            with torch.no_grad():
                return apply_model(model.to(dev), x.to(dev), device=dev, split=True, overlap=0.25, progress=False)[0]

        try:
            sources = _apply(device)
        except torch.cuda.OutOfMemoryError:
            out['oom_fallback'] = True
            try:
                torch.cuda.empty_cache()
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('cuda cache release skipped: %s', _exc)
            device = 'cpu'
            sources = _apply(device)
        sources = sources * std + mean
        names = list(model.sources)  # drums, bass, other, vocals
        vi = names.index('vocals')
        voc = sources[vi].cpu().numpy()
        rest = sum(sources[i].cpu().numpy() for i in range(len(names)) if i != vi)

        os.makedirs(out_dir, exist_ok=True)
        vp = os.path.join(out_dir, 'vocals.wav')
        rp = os.path.join(out_dir, 'no_vocals.wav')
        sf.write(vp, voc.T, sr_model, subtype='PCM_16')
        sf.write(rp, rest.T, sr_model, subtype='PCM_16')

        def _db(a):
            r = float(np.sqrt(np.mean(np.square(a.astype('float64')))))
            return round(20.0 * np.log10(max(r, 1e-12)), 2)

        out.update(
            {'ok': True, 'vocals': vp, 'rest': rp, 'device': device, 'vocal_rms_db': _db(voc), 'rest_rms_db': _db(rest)}
        )
        out['ratio_db'] = round(out['vocal_rms_db'] - out['rest_rms_db'], 2)
    except Exception as e:  # noqa: BLE001 — the caller gates on ok
        out['error'] = f'{type(e).__name__}: {e}'[:300]
    print(json.dumps(out))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
