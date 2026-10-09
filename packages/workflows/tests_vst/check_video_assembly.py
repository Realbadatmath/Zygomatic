#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Independent check of video_assembly: ramp maths + a two-shot assembly.

Deliberately does NOT call video_assembly._selftest -- it re-derives the
invariants from the outside so a broken selftest cannot pass itself.

    "$ZYG_SERVER_PYTHON" tests_vst/check_video_assembly.py
"""

import json
import os
import subprocess
import sys
import tempfile

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)

from zyg_workflows import video_assembly as VA  # noqa: E402


def check_ramp_map():
    n_total, n_tail, end_speed = 72, 19, 0.15
    idx = VA.ramp_index_map(n_total, n_tail, end_speed)
    assert idx == sorted(idx), 'index map is not monotonic'
    assert idx[0] == 0 and max(idx) <= n_total - 1, 'index map leaves the source'
    assert len(idx) > n_total, 'ramp produced no extra frames: %d vs %d' % (len(idx), n_total)
    head = idx[: n_total - n_tail]
    assert head == list(range(n_total - n_tail)), 'the head was resampled, it must pass through'
    assert idx[-1] == n_total - 1, 'the last source frame is not reached/held'
    held = sum(1 for a, b in zip(idx, idx[1:]) if a == b and a == n_total - 1)
    assert held >= 2, 'the last source frame is not held (%d repeats)' % held
    assert VA.ramp_index_map(48, 0, 0.5) == list(range(48)), 'no-tail ramp changed the clip'
    print(
        'ramp map: %d source -> %d output frames (+%d), last frame held %dx'
        % (n_total, len(idx), len(idx) - n_total, held + 1)
    )


def check_assembly():
    work = tempfile.mkdtemp(prefix='check_video_assembly_')
    fps, size, xf = 24, [320, 180], 0.25
    clips = []
    for name in ('red', 'blue'):
        p = os.path.join(work, '%s.mp4' % name)
        subprocess.run(
            [
                VA.FFMPEG,
                '-hide_banner',
                '-v',
                'error',
                '-y',
                '-f',
                'lavfi',
                '-i',
                'color=c=%s:s=%dx%d:r=%d' % (name, size[0], size[1], fps),
                '-t',
                '2',
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-an',
                p,
            ],
            check=True,
        )
        clips.append(p)
    out = os.path.join(work, 'out.mp4')
    receipt = VA.assemble(
        {
            'fps': fps,
            'size': size,
            'fade_in_s': 0.5,
            'fade_out_s': 0.5,
            'shots': [{'path': clips[0], 'trim': [0.5, 2.0], 'xfade_s': xf}, {'path': clips[1]}],
        },
        out,
    )
    for key in ('total_s', 'shots', 'fade_in_s', 'fade_out_s', 'audio'):
        assert key in receipt, 'receipt has no %r' % key
    for row in receipt['shots']:
        for key in ('src', 'dur_in', 'dur_out', 'ramp_added_frames', 'joined_at'):
            assert key in row, 'shot row has no %r' % key
    assert abs(receipt['shots'][0]['dur_out'] - 1.5) <= 0.05, (
        'trim [0.5, 2.0] gave %.3fs, expected 1.5s' % receipt['shots'][0]['dur_out']
    )
    expect = 1.5 + 2.0 - xf
    assert abs(receipt['total_s'] - expect) <= 0.1, 'total %.3fs, expected %.3fs' % (receipt['total_s'], expect)
    assert abs(receipt['shots'][1]['joined_at'] - (1.5 - xf)) <= 0.05, 'join at %.3fs, expected %.3fs' % (
        receipt['shots'][1]['joined_at'],
        1.5 - xf,
    )
    w, h, got_fps, dur, _ = VA._probe(out)
    assert [w, h] == size and abs(got_fps - fps) < 0.01, 'conform failed: %dx%d @%.3f' % (w, h, got_fps)
    assert receipt['audio'] is None, 'audio receipt on a silent list'
    print(
        'assembly: %s'
        % json.dumps(
            {
                'total_s': receipt['total_s'],
                'joined_at': [r['joined_at'] for r in receipt['shots']],
                'probe': [w, h, round(got_fps, 3), round(dur, 3)],
            }
        )
    )
    import shutil

    shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    check_ramp_map()
    check_assembly()
    print('CHECK OK')
