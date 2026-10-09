#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bench one audio file through voice_stt.transcribe_utterance.

    python3 tools/vb_stt_bench.py data/assets/voice_seeds/abel_narrator_seed.wav
    python3 tools/vb_stt_bench.py /tmp/utterance.webm --warm

Prints device/model, the wall time, and the text. Exit 1 on empty text so it can
be used as a smoke check.
"""

import argparse
import mimetypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import voice_stt  # noqa: E402

_EXT_MIME = {
    '.webm': 'audio/webm',
    '.ogg': 'audio/ogg',
    '.opus': 'audio/ogg',
    '.wav': 'audio/wav',
    '.mp4': 'audio/mp4',
    '.m4a': 'audio/mp4',
    '.mp3': 'audio/mpeg',
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--language', default='en')
    ap.add_argument('--warm', action='store_true', help='load the model first and time it separately')
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f'no such file: {args.path}', file=sys.stderr)
        return 2
    ext = os.path.splitext(args.path)[1].lower()
    mime = _EXT_MIME.get(ext) or mimetypes.guess_type(args.path)[0] or 'audio/webm'

    if args.warm:
        w = voice_stt.warm()
        print(f'warm   : {w["model"]} on {w["device"]} in {w["ms"]} ms')

    with open(args.path, 'rb') as fh:
        data = fh.read()
    try:
        r = voice_stt.transcribe_utterance(data, mime=mime, language=args.language)
    except voice_stt.SttError as e:
        print(f'ERROR  : {e}', file=sys.stderr)
        return 1

    print(f'file   : {args.path} ({len(data)} bytes, mime={mime})')
    print(f'device : {r["device"]}  model={r["model"]}')
    print(f'audio  : {r["seconds"]:.2f} s   wall: {r["ms"]} ms')
    if r.get('reason'):
        print(f'reason : {r["reason"]}')
    print(f'text   : {r["text"]}')
    return 0 if r['text'] else 1


if __name__ == '__main__':
    sys.exit(main())
