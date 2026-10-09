#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Find the camera DIRECTION that matches a pack's own vendor render.

Run as `blender -b -P vfx_volume_camsearch.py -- <json cfg>`.

An element's colour can be regraded after the fact — it is a multiply on a
non-emissive volume — but the camera cannot. Angle, and the shadowing that
follows from it, are baked at render time, so matching the vendor's viewpoint
has to happen BEFORE the 70-minute pass, not after.

The match is measured, not eyeballed. One frame of the simulation is rendered
from a grid of directions and each result is compared, as a SILHOUETTE, to the
vendor's own frame at the same point in the clip:

  * silhouette, not colour — the vendor lit their sim their way and we light it
    ours, so brightness says nothing about viewpoint. Alpha coverage does.
  * normalised to its own bounding box before comparison, so the score reflects
    the SHAPE the viewpoint produces and not how tightly either render happens
    to frame it. Without this the score just measures zoom.
  * the sphere fit is kept here (no `fit: element`) precisely so every candidate
    is framed by the same rule and only the angle varies.

Everything is rendered inside ONE blender session: the sequence and its bounds
cost more to load than all the candidate renders put together, so the grid is
nearly free once the session is up.

cfg: {seq, n, frame, out, dirs: [[x,y,z], …], res, samples}
Writes out/dir_%02d.png plus out/dirs.json describing what each index was.
"""

import json
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_workflows import vfx_volume_render as R  # noqa: E402


def _centre_radius(lo, hi):
    centre = (lo + hi) * 0.5
    return centre, max((hi - lo).length * 0.5, 1e-3)


def main():
    cfg = json.loads(sys.argv[sys.argv.index('--') + 1])
    n = int(cfg['n'])
    frame = int(cfg.get('frame', max(1, n * 3 // 4)))
    res = int(cfg.get('res', 480))
    out = cfg['out']
    os.makedirs(out, exist_ok=True)

    R.clear_scene()
    ob = R.import_sequence(cfg['seq'], n)
    grids = R.grid_names(ob)
    wiring = R.build_material(ob, grids)
    print(f'[cam] grids: {grids}  density={wiring["density"]!r}')

    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.film_transparent = True
    sc.cycles.samples = int(cfg.get('samples', 16))
    sc.cycles.use_denoising = True
    sc.cycles.volume_max_steps = 128
    sc.cycles.max_bounces = 2
    sc.cycles.volume_bounces = 1
    R._set_view_transform(sc, 'Standard')
    R._enable_gpu(sc)

    lo, hi = R.sequence_bounds(ob, n)
    print(f'[cam] bounds {tuple(round(v, 1) for v in lo)} → {tuple(round(v, 1) for v in hi)}')

    # EXPOSURE PROBE. The right exposure is a property of the PACK, not a
    # constant: how much light reaches the camera depends on the sim's density
    # and its physical scale, and the rig's power is tied to the domain radius.
    # Dust Shockwave measured 59.3% of pixels blown out at exposure 0 and
    # needed -1.5; nothing about that number transfers to a thinner, differently
    # sized dust cloud, so each pack is measured rather than assumed. Note the
    # direction grid above lights NOTHING on purpose -- it scores alpha
    # silhouettes, which are independent of lighting -- so this branch has to
    # build the rig itself before any of these numbers mean anything.
    exposures = cfg.get('exposures')
    if exposures:
        d = cfg['dirs'][0]
        R.setup_camera(lo, hi, res, res, d)
        R.setup_lights(*_centre_radius(lo, hi), emissive=bool(wiring['temperature']))
        R.setup_world()
        meta = []
        for i, ev in enumerate(exposures):
            sc.view_settings.exposure = float(ev)
            sc.frame_set(frame)
            sc.render.filepath = os.path.join(out, 'ev_%02d' % i)
            bpy.ops.render.render(write_still=True)
            meta.append({'i': i, 'exposure': ev})
            print(f'[cam] ev {ev:+.2f} -> ev_{i:02d}.png', flush=True)
        with open(os.path.join(out, 'exposures.json'), 'w') as f:
            json.dump(meta, f, indent=1)
        print(f'[cam] done: {len(exposures)} exposure(s)')
        return

    dirs = cfg['dirs']
    meta = []
    for i, d in enumerate(dirs):
        # Rebuild the camera per candidate: setup_camera also derives the clip
        # range from the framing distance, and a stale clip_end renders the
        # volume away to nothing without erroring.
        for o in [o for o in sc.objects if o.type in ('CAMERA', 'EMPTY')]:
            bpy.data.objects.remove(o, do_unlink=True)
        R.setup_camera(lo, hi, res, res, d)
        sc.frame_set(frame)
        sc.render.filepath = os.path.join(out, 'dir_%02d' % i)
        bpy.ops.render.render(write_still=True)
        el = math.degrees(math.asin(d[2] / math.sqrt(sum(c * c for c in d))))
        az = math.degrees(math.atan2(d[0], -d[1]))
        meta.append({'i': i, 'dir': d, 'elev': round(el, 1), 'azim': round(az, 1)})
        print(f'[cam] {i:02d}  elev {el:5.1f}  azim {az:6.1f}', flush=True)

    with open(os.path.join(out, 'dirs.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    print(f'[cam] done: {len(dirs)} candidate(s) at frame {frame}')


if __name__ == '__main__':
    main()
