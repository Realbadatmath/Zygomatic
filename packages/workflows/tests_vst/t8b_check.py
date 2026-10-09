#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Task 8b verifier — the live page's contract, not a re-run of the browser.

Checks, against the RUNNING kanban-server on :8899:
  * /video/api/spec carries the four params the new racks put on the page
    (audio_bed, upscale, overlay_record, shot_list) and the 'assemble' action
    the bar wires to /video/api/assemble;
  * /video/api/stills answers at all (it 404'd before the restart) and lists
    at least one still, so the picker's Stills tab has something to draw;
  * both screenshots from tests_vst/t8b_browser.py exist and are real frames
    (> 50 KB), i.e. the proof was actually taken.
"""

import json
import os
import sys
import urllib.request

BASE = 'http://127.0.0.1:8899'
KEYS = ('audio_bed', 'upscale', 'overlay_record', 'shot_list')
WIRE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'video_studio', '_wire')
SHOTS = ('t8b_racks.png', 't8b_dryrun.png')


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:  # nosec B310  # noqa: S310  BASE is a literal http:// constant, the scheme cannot vary
        return json.loads(r.read().decode('utf-8'))


def main() -> int:
    bad = []

    spec = get('/video/api/spec')
    params = {p['key']: p for r in spec['racks'] for p in r['params']}
    for k in KEYS:
        if k in params:
            print(f'spec param {k}: {params[k]["type"]} icon {params[k].get("icon", "")}')
        else:
            bad.append(f'spec is missing param {k}')
    acts = {a['id'] for a in spec.get('actions', [])}
    if 'assemble' in acts:
        print('spec action assemble: present')
    else:
        bad.append('spec is missing the assemble action')

    stills = get('/video/api/stills').get('stills', [])
    print(f'stills listed: {len(stills)}')
    if not stills:
        bad.append('/video/api/stills is empty')

    for name in SHOTS:
        fp = os.path.join(WIRE, name)
        size = os.path.getsize(fp) if os.path.isfile(fp) else 0
        print(f'{fp} {size} bytes')
        if size <= 50 * 1024:
            bad.append(f'{name} missing or under 50 KB ({size} bytes)')

    if bad:
        for b in bad:
            print('FAIL: ' + b)
        return 1
    print('T8B OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
