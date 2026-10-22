# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.arch_server_ext.render_offline_blender`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.arch_server_ext.render_offline_blender` (and
`blender -b --python arch_server_ext/render_offline_blender.py`, through that module's
connector) still reaches it.

`_main()` is the old `main()` verbatim; `main()` is the old `if __name__` block, whose
try/except is the one-JSON-line contract render_offline.py reads back.
"""

import argparse
import json
import os
import sys
import traceback

from zyg_workflows.arch_server_ext.render_offline_blender import (
    HERE,
    _scene_bounds,
    _zyg_log,
    bpy,
    enable_gpu,
    make_world,
    place_camera,
    place_sun,
    set_look,
)


def _main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='render_offline_blender.py')
    ap.add_argument('--in', dest='inp', required=True, help='Architecture Studio drawing JSON')
    ap.add_argument('--out', required=True, help='output .png')
    ap.add_argument('--blend', default='', help='scratch .blend arch_blender_build.build() writes')
    ap.add_argument('--cam', default='', help='camera JSON {p,t,fov,ortho,top} in studio coordinates')
    ap.add_argument('--samples', type=int, default=64)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=720)
    ap.add_argument('--denoise', type=int, default=1)
    ap.add_argument('--cpu', type=int, default=0, help='force CPU (skip the GPU probe)')
    args = ap.parse_args(argv)

    sys.path.insert(0, HERE)
    from zyg_workflows import arch_blender_build as ABB  # noqa: N814  the same builder the studio uses

    with open(args.inp, 'r', encoding='utf-8') as fh:
        drawing = json.load(fh)
    blend = args.blend or (os.path.splitext(args.out)[0] + '.blend')
    info = ABB.build(drawing, blend, None)  # the --in/--out entry point, in-process

    sc = bpy.context.scene
    lo, hi, ctr, span = _scene_bounds(sc)
    cam_spec = json.loads(args.cam) if args.cam else {}
    cam, cd = place_camera(sc, cam_spec, span, ctr)
    sv = place_sun(sc, ctr, span)
    make_world(sc)
    transform = set_look(sc)

    sc.render.engine = 'CYCLES'
    device, backend = ('CPU', '') if args.cpu else enable_gpu(sc)
    cy = sc.cycles
    cy.samples = max(1, min(4096, int(args.samples)))
    cy.use_adaptive_sampling = True
    cy.use_denoising = bool(args.denoise)
    if cy.use_denoising:
        for dn in ('OPENIMAGEDENOISE', 'OPTIX'):
            try:
                cy.denoiser = dn
                break
            except TypeError as _exc:
                _zyg_log.debug('denoiser not accepted by this build: %s', _exc)
                continue
    sc.render.resolution_x = max(16, min(4096, int(args.width)))
    sc.render.resolution_y = max(16, min(4096, int(args.height)))
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.film_transparent = False
    sc.render.use_file_extension = False
    sc.render.filepath = os.path.abspath(args.out)

    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    png = os.path.abspath(args.out)
    print(
        json.dumps(
            {
                'ok': os.path.exists(png),
                'png': png,
                'bytes': os.path.getsize(png) if os.path.exists(png) else 0,
                'objects': info.get('objects'),
                'skipped': info.get('skipped'),
                'engine': 'CYCLES',
                'device': device,
                'backend': backend,
                'samples': cy.samples,
                'denoise': bool(cy.use_denoising),
                'cam': cd.type,
                'lens': round(cd.lens, 3),
                'ortho_scale': round(cd.ortho_scale, 3),
                'cam_loc': [round(c, 3) for c in cam.location],
                'sun_dir': [round(c, 4) for c in sv],
                'transform': transform,
                'width': sc.render.resolution_x,
                'height': sc.render.resolution_y,
                'lo': [round(c, 2) for c in lo],
                'hi': [round(c, 2) for c in hi],
            }
        ),
        flush=True,
    )


def main() -> int:
    try:
        _main()
    except Exception as e:  # noqa: BLE001 — one JSON line is the contract
        traceback.print_exc()
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
