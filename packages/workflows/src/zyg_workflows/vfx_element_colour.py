#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Colour passes of an already-rendered volume ELEMENT — encode only.

A JangaFX dust/smoke pack has no emission: every pixel is light x albedo, so a
per-channel multiply on the finished RGBA frames and a re-light of the volume
are the same operation. That makes a recolour a 19-second encode instead of a
69-minute render pass (measured, Dust Shockwave, 155 f) — but ONLY for hue and
level. Camera angle, light DIRECTION and shadow are baked into the frames and
no multiply recovers them.

The gains are SOLVED, not typed. A colour is declared as the ratios you want on
the OUTPUT mean — (R/G, B/G) — and the anchor channel's gain; the master's own
mean is measured and the other two channels are pulled DOWN to hit the ratios.
That direction is not a style choice:

  * the master's mean is 164/164/170, i.e. no headroom upward, and
  * `CLIP_MAX` in vfx_volume_element tests for PURE WHITE (all three channels),
    so it cannot see ONE blown channel. A warm grade at R x1.30 flattens 17.1%
    of pixels' red at 255 and the gate still reads 0.00%.

So `anchor` is capped at 1.0 and every solved gain is <= it. Adding a colour is
one line in COLOURS.

Outputs land beside the pack's own element as `<slug>_4k_<colour>.webm|.mov`
and are recorded on the sidecar as `element_variants`, which is what puts the
colour chips in the VFX Studio pane. The pack's shipped `element` is never
touched — a variant is an addition, not a rebuild.

Usage
    python3 vfx_element_colour.py --pack DustShockwaveVDB.zip
    python3 vfx_element_colour.py --pack Dust --colours pink,blue
    python3 vfx_element_colour.py --pack Dust --frames /path/to/rgba/pngs
"""

from __future__ import annotations

import argparse
import logging as _zyg_logging
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_workflows import vfx_ingest as VI  # noqa: E402
from zyg_workflows import vfx_volume_preview as PV  # noqa: E402
from zyg_workflows import vfx_volume_element as EL  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

# The RGBA png masters are under the PROJECT's output/, not crews/output/ —
# where `--keep-frames` was pointed when the elements were built. Without them
# a recolour costs a full render, which is the whole reason they are kept.
FRAMES_ROOT = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'output', 'vfx_elements')

# name -> (R/G on the output mean, B/G on the output mean, anchor gain <= 1.0)
COLOURS = {
    'pink': (1.72, 1.40, 1.00),
    'blue': (0.68, 1.62, 1.00),
    'black': (1.00, 1.00, 0.10),  # neutral: the ratios flatten the master's
    # own cool cast (B/G 1.036) to exactly 1.00
    'golden': (1.32, 0.42, 1.00),
}
PROBE_FRAMES = 5


def log(m):
    _zyg_log.info(m)


def master_mean(pngs: list, probes=PROBE_FRAMES) -> tuple:
    """Mean RGB of the ELEMENT's own pixels, alpha >= 40.

    Sampled across the run, not off one frame: a shockwave's colour is not
    constant over its life and a single probe would tune the grade to whichever
    frame was picked. Background pixels are excluded by the same alpha floor the
    clip check uses — including them would drag every mean toward 0 and the
    solved ratios with it."""
    from PIL import Image

    step = max(1, len(pngs) // (probes + 1))
    idx = [i for i in range(step, len(pngs) - 1, step)][:probes]
    acc = [0.0, 0.0, 0.0]
    n = 0
    for i in idx:
        with Image.open(pngs[i]) as im:
            im = im.convert('RGBA')
            px = im.load()
            w, h = im.size
            for y in range(0, h, 4):
                for x in range(0, w, 4):
                    r, g, b, a = px[x, y]
                    if a < 40:
                        continue
                    acc[0] += r
                    acc[1] += g
                    acc[2] += b
                    n += 1
    if n < 5000:
        raise RuntimeError(f'only {n} element pixel(s) sampled — cannot solve a grade against that')
    return tuple(c / n for c in acc), n


def solve(mean: tuple, rg: float, bg: float, anchor: float) -> tuple:
    """Gains that land the output mean on (rg, bg), scaled so the largest is
    `anchor`. Capped at 1.0 per channel — see the module docstring."""
    g = [rg / mean[0] * mean[1], 1.0, bg / mean[2] * mean[1]]
    g = [x * min(anchor, 1.0) / max(g) for x in g]
    return tuple(round(x, 4) for x in g)


def build(pack: str, colours=None, frames_dir=None, prores=True, force=False) -> dict:
    meta = VI.load_sidecar()
    key = f'{EL.CAT}/{pack}'
    if key not in meta:
        cand = [k for k in meta if k.startswith(EL.CAT + '/') and pack.lower() in k.lower()]
        if len(cand) != 1:
            raise SystemExit(f'no single volume pack matches {pack!r} (candidates: {cand or "none"})')
        key = cand[0]
    rec = dict(meta[key])
    if not rec.get('element'):
        raise SystemExit(
            f'{rec.get("name") or pack} has no element yet — run '
            f'vfx_volume_element.py first; a colour pass regrades '
            f'a render, it does not replace one'
        )
    slug = PV._slug(os.path.splitext(rec['file'])[0]) + '_4k'
    frames_dir = frames_dir or os.path.join(FRAMES_ROOT, slug)
    if not os.path.isdir(frames_dir):
        raise SystemExit(
            f'no RGBA master in {frames_dir} — a colour pass needs '
            f'the kept png sequence (--keep-frames on the build), '
            f'or it is a {EL.SAMPLES}-sample re-render per colour'
        )

    want = [c.strip() for c in (colours or sorted(COLOURS)) if c.strip()]
    bad = [c for c in want if c not in COLOURS]
    if bad:
        raise SystemExit(f'unknown colour(s) {bad} (have: {sorted(COLOURS)})')

    fps = EL.pack_fps(rec)
    pngs = EL.frame_list(frames_dir)
    w, h = EL.frame_shape(pngs[0])
    log(f'{rec["name"]}: {len(pngs)} frame(s) at {w}x{h} RGBA, {fps} fps')
    mean, n = master_mean(pngs)
    log(
        f'  master mean R{mean[0]:.1f} G{mean[1]:.1f} B{mean[2]:.1f} '
        f'({n} px, {PROBE_FRAMES} frames) — R/G {mean[0] / mean[1]:.3f} '
        f'B/G {mean[2] / mean[1]:.3f}'
    )

    out_dir = os.path.join(EL.LIBS, EL.CAT)
    variants = {v['name']: v for v in (rec.get('element_variants') or [])}
    for name in want:
        rg, bg, anchor = COLOURS[name]
        gains = solve(mean, rg, bg, anchor)
        fw = f'{slug}_{name}.webm'
        fm = f'{slug}_{name}.mov'
        pw = os.path.join(out_dir, fw)
        pm = os.path.join(out_dir, fm)
        if name in variants and os.path.exists(pw) and not force:
            log(f'  {name}: already built — skipping')
            continue
        t0 = time.time()
        log(f'  {name}: R x{gains[0]:.4f} G x{gains[1]:.4f} B x{gains[2]:.4f}')
        EL.encode_webm(pngs, pw, fps, gains)
        v = EL.verify_alpha(pw)
        log(
            f'   webm {v["w"]}x{v["h"]} {v["dur"]:.2f}s  alpha {v["alpha_min"]}-'
            f'{v["alpha_max"]}  clear {v["clear"]}%  clipped {v["clipped"]}%  '
            f'{EL.PV_size(os.path.getsize(pw))}'
        )
        mb = 0
        if prores:
            EL.encode_prores(pngs, pm, fps, gains)
            m = EL.verify_alpha(pm)
            mb = os.path.getsize(pm)
            log(
                f'   mov  {m["w"]}x{m["h"]}  alpha {m["alpha_min"]}-{m["alpha_max"]}'
                f'  clipped {m["clipped"]}%  {EL.PV_size(mb)}'
            )
        variants[name] = {
            'name': name,
            'element': fw,
            'master': fm if mb else '',
            'gains': list(gains),
            'bytes': os.path.getsize(pw),
            'master_bytes': mb,
            'w': int(v['w'] or w),
            'h': int(v['h'] or h),
            'frames': len(pngs),
        }
        log(f'   {time.time() - t0:.1f}s')

    # Written back through PV.commit — re-read, one key, save. A colour pass is
    # a minute per variant and the sidecar has other writers.
    order = list(COLOURS)
    rec['element_variants'] = [variants[k] for k in order if k in variants] + [
        v for k, v in variants.items() if k not in order
    ]
    PV.commit(key, rec)
    log(
        f'  committed {len(rec["element_variants"])} variant(s): '
        + ', '.join(v['name'] for v in rec['element_variants'])
    )
    return {'ok': True, 'variants': rec['element_variants']}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--pack', required=True, help='archive name or a unique fragment of it')
    ap.add_argument('--colours', default='', help=f'comma list; default all ({",".join(sorted(COLOURS))})')
    ap.add_argument('--frames', default=None, help='RGBA png master (default output/vfx_elements/<slug>)')
    ap.add_argument('--no-prores', action='store_true')
    ap.add_argument('--force', action='store_true', help='re-encode variants that already exist')
    a = ap.parse_args(argv)
    build(
        a.pack,
        colours=[c for c in a.colours.split(',') if c] or None,
        frames_dir=a.frames,
        prores=not a.no_prores,
        force=a.force,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
