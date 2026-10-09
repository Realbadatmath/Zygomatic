#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof for the eagle/red-tailed-hawk SFX sourcing task.

Checks that the shortlist exists, that every wav it names is on disk as a
48 kHz mono 24-bit file, and that each one carries a commercially usable
licence in the sfx sidecar. Run from agents/crews with the crews venv.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
SFX = os.path.join(HERE, 'data', 'asset_libraries', 'sfx')
OK_LICENCES = ('cc0', 'cc-by-4.0', 'cc-by-3.0')


def probe(path):
    r = subprocess.run(
        [
            'ffprobe',
            '-v',
            'error',
            '-select_streams',
            'a:0',
            '-show_entries',
            'stream=sample_rate,channels,sample_fmt,duration',
            '-of',
            'json',
            path,
        ],
        capture_output=True,
        timeout=30,
    )
    return json.loads(r.stdout)['streams'][0]


def main():
    from zyg_workflows import asset_library_service as A

    with open(os.path.join(SFX, 'eagle_shortlist.json'), encoding='utf-8') as f:
        rows = json.load(f)
    assert len(rows) >= 2, f'shortlist too short: {len(rows)}'

    print(
        f'{"file":42s} {"license":9s} {"comm":5s} {"attr":5s} {"sr":>6s} {"ch":>3s} {"fmt":>9s} {"dur":>6s} glide slate'
    )
    good = 0
    for r in rows:
        p = os.path.join(SFX, r['file'])
        assert os.path.isfile(p), f'missing wav: {p}'
        st = probe(p)
        assert int(st['sample_rate']) == 48000, (r['file'], st['sample_rate'])
        assert int(st['channels']) == 1, (r['file'], st['channels'])
        assert st['sample_fmt'].startswith('s32'), (r['file'], st['sample_fmt'])

        m = A.get_audio_meta('sfx', r['file'])
        assert m.get('license_id') in OK_LICENCES, (r['file'], m.get('license_id'))
        assert m.get('commercial_ok') is True, r['file']
        assert m.get('source') == 'Freesound', r['file']
        assert m.get('source_url'), r['file']
        if m['license_id'] != 'cc0':
            assert m.get('attribution_required') is True, r['file']
            assert m.get('attribution'), r['file']
        good += 1
        print(
            f'{r["file"]:42s} {m["license_id"]:9s} '
            f'{str(m["commercial_ok"]):5s} {str(m.get("attribution_required")):5s} '
            f'{st["sample_rate"]:>6s} {st["channels"]:>3d} {st["sample_fmt"]:>9s} '
            f'{float(st["duration"]):6.2f} {str(r["glide"]):5s} {str(r["slate_suspect"]):5s}'
        )

    cc0 = sum(1 for r in rows if A.get_audio_meta('sfx', r['file'])['license_id'] == 'cc0')
    glide = sum(1 for r in rows if r['glide'])
    print(f'\nOK: {good} eagle/hawk files, {cc0} CC0, {glide} with a descending glide')
    return 0


if __name__ == '__main__':
    sys.exit(main())
