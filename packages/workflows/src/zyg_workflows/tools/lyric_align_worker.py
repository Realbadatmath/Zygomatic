# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""lyric_align_worker.py — what the singer actually sang, with word timestamps.

Runs in the agents venv as a SUBPROCESS (same contract as demucs_split.py): the
GUI process must not hold a CUDA context for a Whisper model.

Model: faster-whisper large-v3 (Systran CTranslate2 conversion of OpenAI
Whisper large-v3, MIT), already in the HF cache from the transcriber install.

HOW IT DECODES, AND THE TEST BEHIND IT (tools/lyric_asr_bench.py, 2026-09-15).
Whole-file decoding lost entire 30-second windows on sung stems (the digger take
heard 1 of 12 lines, ending on the hallucination "We'll see you next time.").
So the caller cuts the stem at silences into phrases of <= 12 s (`chunks`) and
each phrase is decoded alone, prompted with the song's own lyric text
(`prompt`). That found 10/12 lines on the digger, 9/12 on the bumblebee, 8/8 on
the farmyard song. The risk a prompt carries — "hearing" a line because it was
told to expect it — was tested directly: one fully sung line was replaced by
silence in four stems (red train, digger, bumblebee, farmyard) and the prompted
decode reported that line missing in 4/4, with no other line newly missing.
VAD is off — voice-activity filters tuned for speech clip held sung vowels.

Usage:  python lyric_align_worker.py VOCALS.wav OUT.json [--device cuda|cpu]
        python lyric_align_worker.py ITEMS.json OUT.json      (batch: one model load)
OUT.json (single): {"ok", "model", "language", "words": [{"w", "start", "end", "p"}], "error"}
ITEMS.json: {"items": [{"id", "wav", "chunks": [[s, e], ...]?, "prompt": str?}]}
            -> OUT.json {"ok", "model", "results": {id: <single>}}
"""

import json
import os
import sys


def _transcribe(model, wav, chunks=None, prompt=None):
    rec = {
        'ok': False,
        'language': 'en',
        'words': [],
        'error': '',
        'chunks': len(chunks) if chunks else 0,
        'prompted': bool(prompt),
    }
    try:
        import numpy as np
        import soundfile as sf

        audio, sr = sf.read(wav, dtype='float32', always_2d=True)
        audio = audio.mean(axis=1)
        if sr != 16000:
            import librosa

            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
            sr = 16000
        spans = chunks or [[0.0, len(audio) / sr]]
        for s, e in spans:
            seg = audio[int(max(0.0, s) * sr) : int(e * sr)]
            if seg.size < int(0.3 * sr):
                continue
            segments, _info = model.transcribe(
                np.ascontiguousarray(seg),
                language='en',
                word_timestamps=True,
                vad_filter=False,
                beam_size=5,
                condition_on_previous_text=False,
                temperature=0.0,
                initial_prompt=prompt or None,
            )
            for sg in segments:
                for w in sg.words or []:
                    rec['words'].append(
                        {
                            'w': w.word.strip(),
                            'start': round(float(w.start) + s, 2),
                            'end': round(float(w.end) + s, 2),
                            'p': round(float(w.probability), 3),
                        }
                    )
        rec['ok'] = True
    except Exception as e:  # noqa: BLE001
        rec['error'] = f'{type(e).__name__}: {e}'[:300]
    return rec


def main(argv):
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
