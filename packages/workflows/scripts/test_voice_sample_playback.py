#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify storyteller voice sample API returns playable MP3."""

from __future__ import annotations

import subprocess
import sys

from zyg_workflows import paths
from zyg_workflows.net import safe_urlopen

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5001'
VOICE = 'en-US-AriaNeural'


def main() -> int:
    health_url = f'{BASE}/api/storyteller/voice-samples-health'
    v1_url = f'{BASE}/api/storyteller/voice-sample/{VOICE}/v1'

    with safe_urlopen(health_url, timeout=10) as r:
        import json

        health = json.loads(r.read().decode())
    print('health:', health)
    if not health.get('ok'):
        print('FAIL: no samples on server')
        return 1

    with safe_urlopen(v1_url, timeout=30) as r:
        data = r.read()
        ctype = r.headers.get('Content-Type', '')
    print(f'v1: {len(data)} bytes, type={ctype}')
    if r.status != 200 if hasattr(r, 'status') else True:
        pass
    if len(data) < 1000:
        print('FAIL: response too small')
        return 1
    if 'mpeg' not in ctype and 'octet' not in ctype:
        print('WARN: unexpected content-type', ctype)

    tmp = str(paths.tmp_dir('voice_sample_playback') / 'voice_sample_test.mp3')
    with open(tmp, 'wb') as f:
        f.write(data)
    proc = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', tmp, '-f', 'null', '-'],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print('FAIL: ffmpeg decode error:', proc.stderr[:300])
        return 1
    print('OK: sample downloads and decodes as valid MP3')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
