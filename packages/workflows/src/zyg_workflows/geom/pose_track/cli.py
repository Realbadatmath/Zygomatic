# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pose_track.py — a per-shot POSE TRACK for the VACE control channel (2026-09-02).

Section 8: the command line. ``main`` reads ``__doc__.split()[0]`` for the
argparse description, so the first line above is load-bearing.
"""

from __future__ import annotations

from .constants import FOUND, argparse, json, os
from .probes import gate_against_2d, soma_registration_probe
from .track import build_track


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('clip', nargs='?', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--subject', default='')
    ap.add_argument('--fps', type=int, default=17)
    ap.add_argument('--max-frames', type=int, default=0)
    ap.add_argument('--smooth', default='savgol', choices=('savgol', 'oneeuro', 'none'))
    ap.add_argument('--window', type=int, default=9)
    ap.add_argument('--threshold', type=float, default=0.4)
    ap.add_argument('--gate', action='store_true', help='also run the MediaPipe 2D gate (needs the crews venv)')
    ap.add_argument('--soma-probe', action='store_true', help='measure the SOMA-X Anny<->MHR registration and exit')
    a = ap.parse_args(argv)

    if a.soma_probe:
        r = soma_registration_probe()
        print(json.dumps(r, indent=1))
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, 'soma_registration.json'), 'w', encoding='utf-8') as fh:
            json.dump(r, fh, indent=1)
        return 0 if r.get('state') == FOUND else 2

    tr = build_track(
        a.clip,
        a.out,
        subject=a.subject,
        fps=a.fps,
        max_frames=a.max_frames,
        smooth=a.smooth,
        window=a.window,
        threshold=a.threshold,
    )
    print('  ledger: %s' % tr['ledger'])
    print(
        '  jitter mm raw %.2f -> smoothed %.2f' % (tr['metrics']['jitter_mm_raw'], tr['metrics']['jitter_mm_smoothed'])
    )
    print(
        '  nulls: held %.1f mm, lerp %.1f mm (track motion %.1f mm)'
        % (
            tr['metrics']['null_held_first_frame']['joint_err_mm'],
            tr['metrics']['null_two_pose_lerp']['joint_err_mm'],
            tr['metrics']['motion_mm_total'],
        )
    )
    print('  projection self-check: %.4f px' % tr['projection']['verified_reproj_px'])
    if a.gate:
        g = gate_against_2d(os.path.join(a.out, 'track.json'))
        print('  gate 2D: %s' % json.dumps({k: v for k, v in g.items() if k not in ('per_frame',)}))
    return 0
