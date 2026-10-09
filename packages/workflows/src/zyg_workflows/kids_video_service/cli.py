# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""kids_video_service.py — the illustrated-video leg of the Children's Music workflow.

The command line, moved verbatim out of the old single-file
kids_video_service.py (lines 4397-4456).  The first line of this docstring is
load-bearing: ``_main`` reads it as argparse's description, exactly as the
single file did.
"""

from __future__ import annotations

import json
import os

from zyg_workflows.kids_video_service.run import (
    reassemble,
    run,
)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _main(argv):
    """Rebuild the video for an existing song folder: ``python kids_video_service.py <dir>``."""
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('song_dir', help='an output/kidsmusic/<job> folder')
    ap.add_argument('--audio', default='', help='override the audio leg')
    ap.add_argument(
        '--reassemble',
        action='store_true',
        help='rebuild the video from the frames already on disk — no storyboard, no LLM, no image generation',
    )
    a = ap.parse_args(argv)
    d = os.path.abspath(a.song_dir)
    with open(os.path.join(d, 'song.json')) as fh:
        plan = json.load(fh)
    brief = dict(plan.get('brief') or {})
    try:
        with open(os.path.join(d, 'manifest.json')) as fh:
            m = json.load(fh)
        brief.update(m.get('brief') or {})
        brief['title'] = m.get('title') or brief.get('title')
        picked = (m.get('delivery') or {}).get('picked')
    except (OSError, ValueError):
        picked = None
    audio = a.audio or os.path.join(d, picked or 'master.mp3')
    _log = lambda s: print(f'  {s}', flush=True)  # noqa: E731
    rec = reassemble(d, audio, log_fn=_log) if a.reassemble else run(plan, brief, audio, d, log_fn=_log)
    # Fold the result back into the song's manifest, so a re-illustrated song
    # shows its video in the inspection tab exactly like one that was
    # illustrated in the pipeline. A CLI that leaves the manifest stale would
    # produce a video on disk that nothing in the UI can find.
    mp = os.path.join(d, 'manifest.json')
    try:
        with open(mp, encoding='utf-8') as fh:
            man = json.load(fh)
        man['video'] = rec
        man.setdefault('files', {}).update(
            {
                'video': rec.get('file'),
                'poster': rec.get('poster'),
                'storyboard': ('storyboard.json' if os.path.isfile(os.path.join(d, 'storyboard.json')) else None),
            }
        )
        with open(mp, 'w', encoding='utf-8') as fh:
            json.dump(man, fh, indent=1)
        print(f'  manifest updated: {mp}')
    except (OSError, ValueError) as e:
        print(f'  manifest NOT updated ({type(e).__name__}: {e}) — the video is on disk but the tab will not show it')
    print(json.dumps({k: v for k, v in rec.items() if k in ('ok', 'file', 'reason', 'pacing', 'elapsed_s')}, indent=1))
    return 0 if rec['ok'] else 1


if __name__ == '__main__':
    import sys

    raise SystemExit(_main(sys.argv[1:]))
