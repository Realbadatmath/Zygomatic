#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Licence gate check for video_audio.resolve_library_file (no GPU, no render).

Run:  "$ZYG_SERVER_PYTHON" \
        tests_vst/check_video_audio_licence.py
Exits 0 when every case behaves, non-zero with a message otherwise.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import video_audio as VA  # noqa: E402

fails = []


def expect_ok(ref):
    try:
        path, meta = VA.resolve_library_file(ref)
    except Exception as e:  # noqa: BLE001
        fails.append(f'{ref}: refused but should pass ({e})')
        return
    if not os.path.exists(path):
        fails.append(f'{ref}: resolved to a missing path {path}')
        return
    print(
        f'OK   {ref} -> {os.path.basename(path)} '
        f'licence={meta.get("license_id")!r} '
        f'commercial_ok={meta.get("commercial_ok")} '
        f'no_ai_training={meta.get("no_ai_training")}'
    )


def expect_refused(ref, why):
    try:
        VA.resolve_library_file(ref)
    except ValueError as e:
        print(f'OK   {ref} refused ({why}): {e}')
        return
    except Exception as e:  # noqa: BLE001
        fails.append(f'{ref}: raised {type(e).__name__}, wanted ValueError ({e})')
        return
    fails.append(f'{ref}: accepted but should be refused ({why})')


# The two known-good intro beds (commercial_ok True, no_ai_training True).
expect_ok('foley/xyl_ambience_sand_storm.wav')
expect_ok('sfx/uh_ambdsgn_heavy_gusts_of_wind.wav')

# An absolute path bypasses the sidecar and carries no meta.
this = os.path.abspath(__file__)
p, m = VA.resolve_library_file(this)
if p != this or m != {}:
    fails.append(f'absolute path: got ({p}, {m})')
else:
    print('OK   absolute path passes through with empty meta')

expect_refused('sfx/does_not_exist_xyzzy.wav', 'missing file')
expect_refused('nosuchcat/whatever.wav', 'unknown category')
expect_refused('just_a_filename.wav', 'malformed reference')

# A synthetic refusal: monkeypatch the sidecar reader so a real file comes
# back not cleared for commercial use.
from zyg_workflows import asset_library_service as A  # noqa: E402

_real = A.get_audio_meta
A.get_audio_meta = lambda cat, fid: {'license_id': 'x', 'commercial_ok': False}
expect_refused('foley/xyl_ambience_sand_storm.wav', 'commercial_ok False')
A.get_audio_meta = lambda cat, fid: {'license_id': 'x', 'deleted': True}
expect_refused('foley/xyl_ambience_sand_storm.wav', 'deleted')
A.get_audio_meta = _real

if fails:
    print('\nFAIL:')
    for f in fails:
        print(f'  - {f}')
    sys.exit(1)
print('\nLICENCE CHECK OK')
