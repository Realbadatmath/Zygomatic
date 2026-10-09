# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""BLENDER SIDE: the worker entry point that runs inside Blender."""

from zyg_workflows.geom.mv_render.blender_scene import _bl_place_camera, _bl_scene
from zyg_workflows.geom.mv_render.blender_verify import _bl_coverage, _bl_render, _bl_verify_texture_lock
from zyg_workflows.geom.mv_render.constants import WORKER_STATUS, _now, json, os, shutil, sys, tempfile

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _bl_main(cfg_path):
    """Entry point INSIDE Blender.

    WRAPPED, BECAUSE BLENDER EXITS 0 ON AN UNCAUGHT PYTHON EXCEPTION. Every abort in this
    file — the surface-lock assertions, the orientation guard, the translation and azimuth
    tests — printed its traceback and then let the process report success. `sys.exit(1)`
    does not fix it either: Blender's `--python` runner catches SystemExit and carries on to
    its own clean shutdown. os._exit() is the only thing that reliably reaches the shell,
    and a status sentinel written last is the only thing that reliably reaches the caller.
    """
    try:
        _bl_main_inner(cfg_path)
    except BaseException:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(3)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def _bl_main_inner(cfg_path):
    with open(cfg_path) as fh:
        cfg = json.load(fh)
    textured = bool(cfg['textured'])
    outdir = cfg['outdir']
    os.makedirs(outdir, exist_ok=True)

    obj, cam, geom, frm, lock = _bl_scene(cfg, textured)

    tmpdir = tempfile.mkdtemp(prefix='mvclock_')
    if textured:
        lock = _bl_verify_texture_lock(obj, cam, frm, cfg, tmpdir, lock)
    shutil.rmtree(tmpdir, ignore_errors=True)

    images = []
    for i in range(cfg['n_views']):
        az = i * cfg['azimuth_step_deg']
        _bl_place_camera(cam, az, cfg['elevation_deg'], frm['target_world'], frm['camera_distance_m'])
        path = os.path.join(outdir, 'cell_%02d.png' % i)
        _bl_render(path)
        images.append(
            {
                'file': 'cell_%02d.png' % i,
                'azimuth_deg': round(az, 4),
                'elevation_deg': cfg['elevation_deg'],
                'focal_length_mm': cfg['lens_mm'],
                'sensor_mm_vertical': cfg['sensor_mm'],
                'camera_location_m': [round(v, 6) for v in cam.location],
                'camera_distance_m': round(frm['camera_distance_m'], 6),
                'width': cfg['out_w'],
                'height': cfg['out_h'],
                'subject_coverage': round(_bl_coverage(path), 4),
            }
        )
        _zyg_log.info('[mv_render] %s az=%.1f' % (path, az))

    cov = sorted(im['subject_coverage'] for im in images)
    manifest = {
        'set': cfg['set_name'],
        'generated': _now(),
        'generator': 'geom/mv_render.py (Blender %s)' % cfg['blender_version'],
        'role': cfg['role'],
        'source': {
            'kind': 'rendered',
            'mesh': cfg['glb_rel'],
            'mesh_stats': geom,
        },
        'resolution': [cfg['out_w'], cfg['out_h']],
        'n_images': len(images),
        'camera': {
            'projection': 'perspective',
            'focal_length_mm': cfg['lens_mm'],
            'sensor_fit': 'VERTICAL',
            'sensor_mm': cfg['sensor_mm'],
            'trajectory': 'turntable, %d azimuths %.4f deg apart, constant elevation'
            % (cfg['n_views'], cfg['azimuth_step_deg']),
            'elevation_deg': cfg['elevation_deg'],
            'azimuth_zero': 'camera at -Y looking +Y = front of the figure',
            'distance_m': round(frm['camera_distance_m'], 6),
            'target_world_m': [round(v, 6) for v in frm['target_world']],
        },
        'framing': {
            'frame_height_m': round(frm['frame_height_m'], 6),
            'frame_width_m': round(frm['frame_width_m'], 6),
            'frame_h_per_stature': cfg['frame_h_per_stature'],
            'head_top_margin_frac': cfg['head_top_margin'],
            'px_per_m_at_target': round(frm['px_per_m_at_target'], 3),
            'subject_coverage_median': cov[len(cov) // 2],
            'subject_coverage_min': cov[0],
            'subject_coverage_max': cov[-1],
            'coverage_method': (
                'exact background mask: background byte value read from '
                'the two top 16 px corners of each frame, subject = '
                'max(RGB) more than 12 above it'
            ),
        },
        'texture_treatment': cfg['texture_treatment'],
        'texture_lock_verification': lock,
        'render': {
            'engine': 'CYCLES',
            'device': 'CPU',
            'samples': cfg['samples'],
            'denoising': True,
            'lights': '4 AREA lights, world-fixed, ring at az 45/135/225/315, '
            'elevation +25 deg, r=3.0 m, energy %.0f W, size 2.0 m' % cfg['light_energy'],
            'world_background': [0.035, 0.035, 0.038],
            'material': 'Principled BSDF, roughness 1.0, specular 0, metallic 0',
        },
        'images': images,
    }
    if len(images) != cfg['n_views']:
        raise RuntimeError('rendered %d of %d views' % (len(images), cfg['n_views']))
    with open(os.path.join(outdir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    # LAST. A caller that finds this file knows every guard above was cleared and every
    # frame was written by THIS invocation.
    with open(os.path.join(outdir, WORKER_STATUS), 'w') as fh:
        json.dump(
            {
                'ok': True,
                'set': cfg['set_name'],
                'n_images': len(images),
                'generated': manifest['generated'],
                'blender': cfg['blender_version'],
            },
            fh,
            indent=1,
        )
    _zyg_log.info('[mv_render] wrote %s' % os.path.join(outdir, 'manifest.json'))
