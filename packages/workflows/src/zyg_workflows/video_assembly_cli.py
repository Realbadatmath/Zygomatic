# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line and self-test of `zyg_workflows.video_assembly`, moved out of the library module.

The library file sits above the brand line (800 lines); its logic stays there and
only connects to this entry point, which `python -m zyg_workflows.video_assembly` still reaches.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile

import numpy as np

from zyg_workflows import video_audio
from zyg_workflows.video_assembly import (
    FFMPEG,
    _ffmpeg,
    _frames,
    _luma,
    _probe,
    _run,
    _zyg_log,
    assemble,
)


def _selftest():
    """Synthetic end-to-end: 3 colour clips + a still, ramp, joins, fades, audio."""
    log = print
    fps = 24
    size = [640, 360]
    work = tempfile.mkdtemp(prefix='video_assembly_selftest_', dir=video_audio._scratch())
    log('video_assembly selftest: %s' % work)

    clips = {}
    for name in ('red', 'green', 'blue'):
        path = os.path.join(work, '%s.mp4' % name)
        _ffmpeg(
            [
                '-f',
                'lavfi',
                '-i',
                'color=c=%s:s=%dx%d:r=%d' % (name, size[0], size[1], fps),
                '-t',
                '3',
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-an',
                path,
            ],
            path,
            'synth %s' % name,
            log,
        )
        clips[name] = path
    still = os.path.join(work, 'yellow.png')
    proc = _run(
        [
            FFMPEG,
            '-hide_banner',
            '-v',
            'error',
            '-y',
            '-f',
            'lavfi',
            '-i',
            'color=c=yellow:s=%dx%d' % (size[0], size[1]),
            '-frames:v',
            '1',
            still,
        ]
    )
    if not (proc.returncode == 0 and os.path.exists(still)):
        raise RuntimeError('synth still: %s' % proc.stderr)

    xf = 0.18
    shots = [
        {'path': clips['red'], 'xfade_s': xf},
        {'path': clips['green'], 'speed_ramp': {'tail_s': 0.8, 'end_speed': 0.15}, 'xfade_s': xf},
        {'still': still, 'hold_s': 2.0, 'xfade_s': xf},
        {'path': clips['blue']},
    ]
    shotlist = {
        'fps': fps,
        'size': size,
        'shots': shots,
        'fade_in_s': 1.0,
        'fade_out_s': 1.0,
        'fade_color': 'black',
        'audio': None,
    }

    out = os.path.join(work, 'final.mp4')
    receipt = assemble(shotlist, out, log=log)
    _zyg_log.info(json.dumps(receipt, indent=2, sort_keys=True))

    added = receipt['shots'][1]['ramp_added_frames']
    if added <= 0:
        raise RuntimeError('ramp added no frames: %r' % added)
    expect = 3 + 3 + 3 + 2 - 3 * xf + added / float(fps)
    if abs(receipt['total_s'] - expect) > 0.1:
        raise RuntimeError(
            'total %.3fs, expected %.3fs (off by %+.3f)'
            % (
                receipt['total_s'],
                expect,
                receipt['total_s'] - expect,
            )
        )
    _zyg_log.info('total %.3fs vs expected %.3fs (ramp added %d frames)' % (receipt['total_s'], expect, added))

    frames = list(_frames(out))
    if not frames:
        raise RuntimeError('no frames decoded from %s' % out)
    first, last = _luma(frames[0]), _luma(frames[-1])
    if first >= 8:
        raise RuntimeError('first frame luma %.2f, expected < 8 (fade in)' % first)
    if last >= 8:
        raise RuntimeError('last frame luma %.2f, expected < 8 (fade out)' % last)
    _zyg_log.info('fades: first frame luma %.2f, last frame luma %.2f' % (first, last))

    mid = frames[int(round(1.5 * fps))]
    b, g, r = (float(np.mean(mid[:, :, c])) for c in (0, 1, 2))
    if not (r > 150 and g < 60):
        raise RuntimeError('t=1.5s not red-dominant: R %.1f G %.1f B %.1f' % (r, g, b))
    _zyg_log.info('t=1.5s: R %.1f G %.1f B %.1f' % (r, g, b))

    sine = os.path.join(work, 'cue.wav')
    proc = _run(
        [
            FFMPEG,
            '-hide_banner',
            '-v',
            'error',
            '-y',
            '-f',
            'lavfi',
            '-i',
            'sine=frequency=1000:r=48000',
            '-t',
            '0.3',
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            sine,
        ]
    )
    if not (proc.returncode == 0 and os.path.exists(sine)):
        raise RuntimeError('synth cue: %s' % proc.stderr)

    shotlist_a = dict(shotlist)
    shotlist_a['audio'] = {
        'bed': None,
        'cues': [{'file': sine, 'at_s': 1.0, 'gain_db': 0, 'fade_s': 0.05}],
        'duck': None,
        'target_lufs': -14.0,
        'true_peak_db': -1.0,
    }
    out_a = os.path.join(work, 'final_audio.mp4')
    receipt_a = assemble(shotlist_a, out_a, log=log)
    _zyg_log.info(json.dumps(receipt_a['audio'], indent=2, sort_keys=True))

    a_dur = video_audio._stream_duration(out_a, 'a')
    if a_dur is None:
        raise RuntimeError('no audio stream in %s' % out_a)
    onset = receipt_a['audio']['cues'][0]['measured_onset_s']
    if onset is None:
        raise RuntimeError('cue never detected in the master')
    if abs(onset - 1.0) > 0.05:
        raise RuntimeError('cue measured at %.3fs, asked for 1.0s' % onset)
    _zyg_log.info('audio: %.3fs stream, cue onset %.3fs' % (a_dur, onset))

    # --- dive_zoom on a synthetic textured clip -------------------------
    tex = os.path.join(work, 'tex.mp4')
    _ffmpeg(
        [
            '-f',
            'lavfi',
            '-i',
            'testsrc2=s=%dx%d:r=%d' % (size[0], size[1], fps),
            '-t',
            '3',
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-an',
            tex,
        ],
        tex,
        'synth texture',
        log,
    )
    n_tex = _probe(tex)[4]
    out_d = os.path.join(work, 'final_dive.mp4')
    receipt_d = assemble(
        {
            'fps': fps,
            'size': size,
            'audio': None,
            'shots': [
                {
                    'path': tex,
                    'dive_zoom': {
                        'zoom_end': 2.0,
                        'focus': [0.5, 0.78],
                        'ease': 'in-out',
                        'blur': True,
                        'start_s': 0.0,
                    },
                }
            ],
        },
        out_d,
        log=log,
    )
    dive = receipt_d['shots'][0].get('dive_zoom')
    if not dive:
        raise RuntimeError('no dive_zoom receipt: %r' % receipt_d['shots'][0])
    s = dive['s_measured']
    if s is None:
        raise RuntimeError('dive_zoom measured no scale')
    if not (1.6 <= s <= 2.4):
        raise RuntimeError('s_measured %.4f outside [1.6, 2.4] for zoom_end 2.0' % s)
    n_dive = _probe(out_d)[4]
    if n_dive != n_tex:
        raise RuntimeError('dive changed the frame count: %d -> %d' % (n_tex, n_dive))
    if dive['frames'] != n_tex:
        raise RuntimeError('dive frames %d, clip has %d' % (dive['frames'], n_tex))
    _zyg_log.info(
        'dive: %d frames in -> %d out, s_measured %.4f (zoom_end %.2f)' % (n_tex, n_dive, s, dive['zoom_end'])
    )

    shutil.rmtree(work, ignore_errors=True)
    _zyg_log.info('SELFTEST OK')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='Assemble a Video Studio shot list into one mp4.')
    ap.add_argument('--list', dest='shotlist', help='shot list json')
    ap.add_argument('--out', dest='out', help='output mp4')
    ap.add_argument('--draft', action='store_true', help='draft resolution overlays, fast encode')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.shotlist or not args.out:
        ap.error('--list and --out are required (or --selftest)')
    with open(args.shotlist, 'r', encoding='utf-8') as fh:
        shotlist = json.load(fh)
    receipt = assemble(shotlist, args.out, log=print, draft=args.draft)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
