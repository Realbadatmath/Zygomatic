#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Does every VFX library asset actually PLAY? — measure it, do not assume it.

The VFX Studio preview pane draws three kinds and every one of them can fail
silently in a way that still looks like a working page:

  * a plate whose transcode produced a container the browser cannot decode
  * a sprite whose PNG is fully transparent, so the pane shows a checkerboard
    and nothing else
  * a volume whose preview clip is 116 frames of the backdrop, because the
    render put the camera past its own clip plane and Cycles obligingly
    rendered nothing. That one is not hypothetical: it is what the first pass
    of vfx_volume_preview produced for every density-only pack, and it wrote
    "→ dust_devil.mp4 render 0.0 MB" and exited 0 while doing it.

So the check is not "is there a file" — it is "does the file hold a picture".
Every clip is decoded and every frame sampled for content ABOVE ITS OWN
BACKGROUND, and every sprite for non-transparent pixels. A row only passes if
something is actually visible in it.

    python3 vfx_preview_check.py            # every category
    python3 vfx_preview_check.py --cat vfx_volumes
    python3 vfx_preview_check.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from zyg_workflows import vfx_ingest as VI
from zyg_workflows.bin import exe

# A frame counts as holding something when its brightest pixel is this far
# above its own darkest — enough to rule out a flat backdrop, low enough not to
# reject a genuinely subtle element.
CONTRAST = 20
SAMPLE_FRAMES = 12  # per clip, spread across it
PROBE_W, PROBE_H = 160, 90


def vxdur(sec):
    sec = sec or 0
    if sec < 60:
        return f'{sec:.1f}s'
    return f'{int(sec // 60)}:{int(round(sec % 60)):02d}'


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def clip_content(path: str) -> dict:
    """Decode the clip small and grey and report how much of it holds a picture.

    Decoding is the point — a file ffprobe describes happily can still fail to
    decode a single frame — but decoding ALL of it is not: the DOE plates are
    25-minute films, and reading every frame of four of them to answer "is
    there a picture in this" takes longer than the render did. So the decode is
    thinned with an fps filter to land near SAMPLE_FRAMES frames however long
    the clip is, and a short preview clip is simply read at its own rate."""
    dur = float((VI.probe(path) or {}).get('dur') or 0)
    vf = f'scale={PROBE_W}:{PROBE_H}'
    if dur > 8:
        vf = f'fps={max(0.05, SAMPLE_FRAMES / dur):.4f},' + vf
    r = _run([exe('ffmpeg'), '-v', 'error', '-i', path, '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
    n = PROBE_W * PROBE_H
    data = r.stdout or b''
    frames = len(data) // n
    if not frames:
        return {'ok': False, 'why': 'decoded 0 frames', 'stderr': (r.stderr or b'').decode('utf8', 'replace')[-160:]}
    step = max(1, frames // SAMPLE_FRAMES)
    lit = seen = 0
    peak = 0
    for i in range(0, frames, step):
        f = data[i * n : (i + 1) * n]
        span = max(f) - min(f)
        peak = max(peak, span)
        seen += 1
        if span >= CONTRAST:
            lit += 1
    return {
        'ok': lit > 0,
        'frames': frames,
        'sampled': seen,
        'lit': lit,
        'dur': round(dur, 1),
        'peak_contrast': peak,
        'why': '' if lit else f'every sampled frame is flat (peak span {peak})',
    }


def sprite_content(path: str) -> dict:
    """A sprite passes when it has pixels that are both opaque enough to show
    and not identical to every other pixel."""
    try:
        from PIL import Image
    except ImportError:
        return {'ok': False, 'why': 'Pillow missing'}
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'why': f'unreadable: {type(e).__name__}'}
    rgba = im.convert('RGBA')
    alpha = rgba.getchannel('A')
    a_lo, a_hi = alpha.getextrema()
    grey = rgba.convert('L')
    g_lo, g_hi = grey.getextrema()
    ok = a_hi > 8 and (g_hi - g_lo) > 4
    why = ''
    if a_hi <= 8:
        why = 'fully transparent'
    elif (g_hi - g_lo) <= 4:
        why = 'flat — no visible detail'
    return {'ok': ok, 'w': im.width, 'h': im.height, 'alpha_max': a_hi, 'luma_span': g_hi - g_lo, 'why': why}


def check(cat_filter=None) -> dict:
    meta = VI.load_sidecar()
    rows = []
    for key, rec in sorted(meta.items()):
        cat = rec.get('cat') or ''
        if cat not in VI.CATEGORIES:
            continue
        if cat_filter and cat != cat_filter:
            continue
        kind = rec.get('kind') or ''
        name = rec.get('name') or rec.get('file') or key
        libdir = os.path.join(VI.LIBS, cat)
        if kind == 'video':
            fp = os.path.join(libdir, rec.get('file') or '')
            res = clip_content(fp) if os.path.isfile(fp) else {'ok': False, 'why': 'working copy missing'}
            plays = 'the plate itself'
        elif kind == 'image':
            fp = os.path.join(libdir, rec.get('file') or '')
            res = sprite_content(fp) if os.path.isfile(fp) else {'ok': False, 'why': 'file missing'}
            plays = 'the sprite'
        else:
            pv = rec.get('preview') or ''
            fp = os.path.join(libdir, pv)
            if not pv:
                res = {'ok': False, 'why': rec.get('preview_error') or 'no preview clip built'}
            elif not os.path.isfile(fp):
                res = {'ok': False, 'why': f'preview clip missing on disk: {pv}'}
            else:
                res = clip_content(fp)
            plays = 'preview clip (%s)' % (rec.get('preview_src') or '—')
        rows.append({'cat': cat, 'kind': kind, 'name': name, 'file': rec.get('file') or '', 'plays': plays, **res})
    return {'rows': rows, 'pass': sum(1 for r in rows if r['ok']), 'fail': sum(1 for r in rows if not r['ok'])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cat', choices=sorted(VI.CATEGORIES), default=None)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--quiet', action='store_true', help='print only the failures and the totals')
    a = ap.parse_args(argv)

    out = check(a.cat)
    if a.json:
        print(json.dumps(out, indent=1))
        return 0 if out['fail'] == 0 else 1

    by_cat = {}
    for r in out['rows']:
        by_cat.setdefault(r['cat'], []).append(r)
    for cat, rows in by_cat.items():
        bad = [r for r in rows if not r['ok']]
        print(f'\n{VI.CATEGORIES[cat]["label"]}  ({cat})  {len(rows) - len(bad)}/{len(rows)} play')
        for r in rows:
            if a.quiet and r['ok']:
                continue
            mark = 'ok  ' if r['ok'] else 'FAIL'
            detail = ''
            if r['kind'] in ('video', 'volume') and r.get('frames'):
                detail = (
                    f'{vxdur(r.get("dur")):>7}  {r["lit"]}/{r["sampled"]} sampled '
                    f'frames hold a picture  peak span {r["peak_contrast"]}'
                )
            elif r['kind'] == 'image' and r.get('w'):
                detail = f'{r["w"]}x{r["h"]}  alpha max {r["alpha_max"]}  luma span {r["luma_span"]}'
            print(f'  {mark} {r["name"][:34]:34s} {detail}' + (f'   <- {r["why"]}' if r.get('why') else ''))
    print(f'\nTOTAL {out["pass"]} play, {out["fail"]} do not')
    return 0 if out['fail'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
