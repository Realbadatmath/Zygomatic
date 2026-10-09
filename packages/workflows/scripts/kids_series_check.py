#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_check.py — the outside verifier for one children's series.

    scripts/kids_series_check.py <slug> [--full]

It re-proves, from the delivered files alone, the two claims the series make:
that an episode was actually produced, and that it cost nothing.  A manifest
that says `ok` is not evidence; ffprobe on the mp4 beside it is.

Deliberately cheap and GPU-free (stdlib + one ffprobe per run, well under 20 s)
because the job board runs it on every `done`.  stdlib only — a checker that
needs the project's own imports to work cannot check the project.

Checks:
  * newest output/kids_<slug>/*/manifest.json parses
  * ok is True, api_cost_usd == 0, paid_api_calls == 0, paid_sdk_imported False
  * episode.mp4 exists beside it
  * ffprobe: duration >= 5 s (>= 30 s with --full), one 1280x720 video stream,
    one audio stream
  * poster.jpg exists
  * pipeline_kids_<slug>.py contains no paid-SDK / ollama reference at all

Exit 0 only if every line says PASS.
"""

import argparse
import json
import os
import re
import subprocess
import sys

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFPROBE = '/usr/bin/ffprobe'

# The cost rule, as a regex.  These series draw from fixed tables and local
# weights; a single hit here means an episode could have cost money.
BANNED = re.compile(r'(anthropic|openai|google\.generativeai|azure|litellm|11434|ollama)', re.IGNORECASE)

_fails = []


def check(name, ok, value=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}: {value}')
    if not ok:
        _fails.append(name)
    return ok


def newest_manifest(slug):
    root = os.path.join(CREWS, 'output', f'kids_{slug}')
    best, best_mt = None, -1.0
    if not os.path.isdir(root):
        return None
    for entry in os.listdir(root):
        p = os.path.join(root, entry, 'manifest.json')
        if os.path.isfile(p):
            mt = os.path.getmtime(p)
            if mt > best_mt:
                best, best_mt = p, mt
    return best


def ffprobe(path):
    r = subprocess.run(
        [FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    return json.loads(r.stdout.decode() or '{}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('slug')
    ap.add_argument('--full', action='store_true', help='require a full episode (>= 30 s), not a --test unit')
    args = ap.parse_args()
    slug = args.slug
    min_dur = 30.0 if args.full else 5.0

    mpath = newest_manifest(slug)
    if not check('manifest found', bool(mpath), mpath or f'no output/kids_{slug}/*/manifest.json'):
        print('FAILED: ' + ', '.join(_fails))
        return 1
    try:
        with open(mpath) as fh:
            m = json.load(fh)
    except (OSError, ValueError) as e:
        check('manifest parses', False, str(e))
        print('FAILED: ' + ', '.join(_fails))
        return 1
    check('manifest parses', True, os.path.relpath(mpath, CREWS))

    check('manifest ok', m.get('ok') is True, repr(m.get('ok')))
    check('api_cost_usd == 0', float(m.get('api_cost_usd', -1)) == 0.0, repr(m.get('api_cost_usd')))
    check('paid_api_calls == 0', int(m.get('paid_api_calls', -1)) == 0, repr(m.get('paid_api_calls')))
    check('paid_sdk_imported is False', m.get('paid_sdk_imported') is False, repr(m.get('paid_sdk_imported')))

    out_dir = os.path.dirname(mpath)
    mp4 = os.path.join(out_dir, 'episode.mp4')
    jpg = os.path.join(out_dir, 'poster.jpg')
    has_mp4 = check(
        'episode.mp4 exists', os.path.isfile(mp4), f'{os.path.getsize(mp4)} bytes' if os.path.isfile(mp4) else mp4
    )
    check('poster.jpg exists', os.path.isfile(jpg), f'{os.path.getsize(jpg)} bytes' if os.path.isfile(jpg) else jpg)

    if has_mp4:
        try:
            info = ffprobe(mp4)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            info = {}
            check('ffprobe reads episode.mp4', False, str(e))
        streams = info.get('streams') or []
        vids = [s for s in streams if s.get('codec_type') == 'video']
        auds = [s for s in streams if s.get('codec_type') == 'audio']
        try:
            dur = float((info.get('format') or {}).get('duration') or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        check(f'duration >= {min_dur:g}s', dur >= min_dur, f'{dur:.2f}s')
        check('one video stream', len(vids) == 1, str(len(vids)))
        check('one audio stream', len(auds) == 1, str(len(auds)))
        if vids:
            w, h = int(vids[0].get('width') or 0), int(vids[0].get('height') or 0)
            check('video is 1280x720', (w, h) == (1280, 720), f'{w}x{h}')

    src = os.path.join(CREWS, f'pipeline_kids_{slug}.py')
    if os.path.isfile(src):
        with open(src, errors='replace') as fh:
            hits = sorted({mm.group(0).lower() for mm in BANNED.finditer(fh.read())})
        check('no paid-API / ollama reference in the runner', not hits, ', '.join(hits) if hits else 'clean')
    else:
        check('runner source exists', False, src)

    if _fails:
        print('FAILED: ' + ', '.join(_fails))
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
