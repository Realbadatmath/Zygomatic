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

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_EXT_MIME = {
    '.webm': 'audio/webm',
    '.ogg': 'audio/ogg',
    '.opus': 'audio/ogg',
    '.wav': 'audio/wav',
    '.mp4': 'audio/mp4',
    '.m4a': 'audio/mp4',
    '.mp3': 'audio/mpeg',
}


if __name__ == '__main__':  # the CLI lives in vb_stt_bench_cli
    from zyg_workflows.tools.vb_stt_bench_cli import main as _cli_main

    raise SystemExit(_cli_main())
