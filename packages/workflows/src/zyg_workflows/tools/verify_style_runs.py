#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify that real style runs landed on disk and on the library board.

One line per style. Exit non-zero if any style FAILs.

    ../.venv/bin/python tools/verify_style_runs.py --family cinematic cheerful heroic

Each family owns its own output root (the same split the library API reports as
`roots`), so the family flag picks both where to look and which expectations
apply: a cinematic cue is instrumental, has the sampler's fourth `extra` layer
and carries no pictures, none of which is true of a children's song.
"""

import argparse
import json
import logging as _zyg_logging
import os
import subprocess
import sys

from zyg_workflows import paths
from zyg_workflows.net import safe_urlopen
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAMILY_ROOTS = {'children': 'kidsmusic', 'cinematic': 'cinematic'}
LIBRARY_URL = paths.ZYG_KANBAN_URL + '/inspect/api/kidsmusic?force=1'

MASTER_LUFS_TARGET = -14.0
MASTER_LUFS_TOL = 1.5
VIDEO_SYNC_TOL_S = 1.5
CARTOON_MEAN_MIN = 0.85


def probe_duration(path):
    """Seconds of a media file, or None if ffprobe cannot read it."""
    try:
        out = subprocess.run(
            [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        return float(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def newest_per_style(root, styles):
    """Newest manifest for each style, by manifest mtime."""
    best = {}
    base = os.path.join(HERE, 'output', root)
    for name in os.listdir(base) if os.path.isdir(base) else []:
        path = os.path.join(base, name, 'manifest.json')
        if not os.path.isfile(path):
            continue
        try:
            man = json.load(open(path))
        except (ValueError, OSError) as _exc:
            _zyg_log.debug('manifest unreadable, run skipped: %s', _exc)
            continue
        style = man.get('style')
        if style not in styles:
            continue
        mtime = os.path.getmtime(path)
        if style not in best or mtime > best[style][0]:
            best[style] = (mtime, os.path.join(base, name), man)
    return {s: (d, m) for s, (_t, d, m) in best.items()}


def fetch_library():
    with safe_urlopen(LIBRARY_URL, timeout=60) as r:
        return json.load(r)


def check(style, family, out_dir, man, songs):
    """Return the list of failure strings for one style (empty == PASS)."""
    fails = []

    def want(cond, msg):
        if not cond:
            fails.append(msg)

    want(man.get('ok') is True, f'manifest ok={man.get("ok")!r}')
    want(man.get('family') == family, f'family={man.get("family")!r} want {family!r}')

    render = man.get('render') or {}
    want(render.get('engine') == 'sampler', f'render.engine={render.get("engine")!r}')
    layers = render.get('layers') or {}
    if family == 'cinematic':
        want(len(layers) == 4, f'render.layers has {len(layers)} roles, want 4: {sorted(layers)}')
        want(all(layers.values()), f'render.layers has an empty voice: {layers}')

    delivery = man.get('delivery') or {}
    picked = delivery.get('picked')
    want(picked == 'master.mp3', f'delivery.picked={picked!r}')
    if picked:
        want(os.path.isfile(os.path.join(out_dir, picked)), f'{picked} missing on disk')

    gates = man.get('gates') or {}
    lufs = ((gates.get('master') or {}).get('checks') or {}).get('lufs')
    want(
        isinstance(lufs, (int, float)) and abs(lufs - MASTER_LUFS_TARGET) <= MASTER_LUFS_TOL,
        f'master LUFS={lufs!r} want {MASTER_LUFS_TARGET}±{MASTER_LUFS_TOL}',
    )

    clap = ((gates.get('render') or {}).get('checks') or {}).get('clap') or {}
    want(
        clap.get('ok') is True,
        f'gates.render.checks.clap.ok={clap.get("ok")!r} ({clap.get("reason") or clap.get("positive_prob")})',
    )

    video = man.get('video') or {}
    if family == 'cinematic':
        want(not os.path.exists(os.path.join(out_dir, 'lyrics.txt')), 'lyrics.txt exists on an instrumental cue')
        reason = video.get('reason') or ''
        want('not applicable' in reason, f'video.reason={reason[:60]!r}')
    else:
        want(video.get('ok') is True, f'video.ok={video.get("ok")!r} ({video.get("reason")})')
        mp4 = os.path.join(out_dir, video.get('file') or 'video.mp4')
        if not os.path.isfile(mp4):
            fails.append(f'{os.path.basename(mp4)} missing on disk')
        elif picked:
            v_s = probe_duration(mp4)
            a_s = probe_duration(os.path.join(out_dir, picked))
            want(
                v_s is not None and a_s is not None and abs(v_s - a_s) <= VIDEO_SYNC_TOL_S,
                f'video {v_s}s vs master {a_s}s (tol {VIDEO_SYNC_TOL_S}s)',
            )
        vchecks = (video.get('gates') or {}).get('checks') or {}
        cartoon = (vchecks.get('cartoon') or {}).get('mean')
        want(
            isinstance(cartoon, (int, float)) and cartoon >= CARTOON_MEAN_MIN,
            f'video cartoon mean={cartoon!r} want >= {CARTOON_MEAN_MIN}',
        )
        lettered = (vchecks.get('lettering') or {}).get('frames_with_text')
        want(lettered == 0, f'video frames_with_text={lettered!r} want 0')

    licence = man.get('licence') or {}
    want(licence.get('ok_commercial') is True, f'licence.ok_commercial={licence.get("ok_commercial")!r}')
    instruments = licence.get('instruments') or {}
    want(
        instruments.get('ok') is True,
        f'licence.instruments.ok={instruments.get("ok")!r} {instruments.get("violations")}',
    )

    shelf_path = os.path.join(out_dir, 'shelf.json')
    if not os.path.isfile(shelf_path):
        fails.append('shelf.json missing')
    else:
        shelf = json.load(open(shelf_path))
        want(shelf.get('family') == family, f'shelf.json family={shelf.get("family")!r}')
        want(shelf.get('shelf') == style, f'shelf.json shelf={shelf.get("shelf")!r} want {style!r}')

    jid = os.path.basename(out_dir)
    row = next((s for s in songs if s.get('id') == jid), None)
    if row is None:
        fails.append(f'library does not list {jid}')
    else:
        want(row.get('root') == family, f'library root={row.get("root")!r} want {family!r}')
        want(
            (row.get('shelf') or {}).get('shelf') == style,
            f'library shelf.shelf={(row.get("shelf") or {}).get("shelf")!r} want {style!r}',
        )
        want(row.get('style') == style, f'library style={row.get("style")!r} want {style!r}')
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        '--family',
        default='children',
        choices=sorted(FAMILY_ROOTS),
        help='which style family (and output root) to verify',
    )
    ap.add_argument('styles', nargs='+', help='style keys to verify')
    a = ap.parse_args()

    root = FAMILY_ROOTS[a.family]
    found = newest_per_style(root, set(a.styles))
    try:
        songs = fetch_library().get('songs') or []
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f'FAIL library {LIBRARY_URL}: {exc}')
        return 2

    bad = 0
    for style in a.styles:
        if style not in found:
            print(f'FAIL {style:12s} no manifest under output/{root}/*/')
            bad += 1
            continue
        out_dir, man = found[style]
        fails = check(style, a.family, out_dir, man, songs)
        jid = os.path.basename(out_dir)
        if fails:
            bad += 1
            print(f'FAIL {style:12s} {jid}  ' + '; '.join(fails))
        else:
            clap = man['gates']['render']['checks']['clap']['positive_prob']
            lufs = man['gates']['master']['checks']['lufs']
            extra = ''
            if a.family != 'cinematic':
                vc = man['video']['gates']['checks']
                extra = (
                    f'video={vc["frames"]} pictures '
                    f'cartoon={vc["cartoon"]["mean"]} lettered='
                    f'{vc["lettering"]["frames_with_text"]} '
                )
            print(
                f'PASS {style:12s} {jid}  engine=sampler '
                f'layers={len(man["render"]["layers"])} '
                f'picked={man["delivery"]["picked"]}'
                f'({man["delivery"]["picked_leg"]}) '
                f'master={lufs} LUFS clap={clap} {extra}'
                f'shelf={a.family}/{style} elapsed={man.get("elapsed_s")}s'
            )
    print(f'{len(a.styles) - bad}/{len(a.styles)} styles pass in family {a.family!r}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
