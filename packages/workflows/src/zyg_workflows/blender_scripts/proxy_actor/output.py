# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math
import os
import tempfile

import bpy

from zyg_workflows.blender_scripts.proxy_actor.args_scene import evaluated_bbox
from zyg_workflows.blender_scripts.proxy_actor.constants import GROUND_TOL, STRIP_H, STRIP_W, TRACK_TOL
from zyg_workflows.blender_scripts.proxy_actor.motion import per_frame_stats, track_vertex_indices

# -------------------------------------------------------------------- output


def make_collection(name, objects):
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    for obj in objects:
        for old in list(obj.users_collection):
            old.objects.unlink(obj)
        coll.objects.link(obj)
    return coll


def render_strip(body, arm, frames, out_path, height):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    if hasattr(scene, 'cycles'):
        scene.cycles.device = 'CPU'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'SINGLE'
    scene.display.shading.single_color = (0.55, 0.52, 0.5)
    scene.display.shading.show_shadows = False
    scene.render.resolution_x = STRIP_W
    scene.render.resolution_y = STRIP_H
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'

    cam_data = bpy.data.cameras.new('strip_cam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = height * 1.25
    cam = bpy.data.objects.new('strip_cam', cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    scene.camera = cam

    tiles = []
    for index, frame in enumerate(frames):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        lo, hi = evaluated_bbox(body)
        centre = (lo + hi) * 0.5
        cam.location = (centre.x, centre.y - 6.0, centre.z)
        fd, tile = tempfile.mkstemp(prefix='proxy_strip_%d_' % index, suffix='.png')
        os.close(fd)
        scene.render.filepath = tile
        bpy.ops.render.render(write_still=True)
        tiles.append(tile)

    stitch(tiles, out_path)
    for tile in tiles:
        if os.path.exists(tile):
            os.remove(tile)
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.cameras.remove(cam_data)


def stitch(tiles, out_path):
    import numpy as np

    strip = np.zeros((STRIP_H, STRIP_W * len(tiles), 4), dtype=np.float32)
    for index, tile in enumerate(tiles):
        img = bpy.data.images.load(tile)
        img.colorspace_settings.name = 'Non-Color'
        buf = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(buf)
        strip[:, index * STRIP_W : (index + 1) * STRIP_W, :] = buf.reshape(img.size[1], img.size[0], 4)
        bpy.data.images.remove(img)
    out = bpy.data.images.new('actor_strip', width=STRIP_W * len(tiles), height=STRIP_H, alpha=True)
    out.colorspace_settings.name = 'Non-Color'
    out.pixels.foreach_set(strip.ravel())
    out.filepath_raw = out_path
    out.file_format = 'PNG'
    out.save()
    bpy.data.images.remove(out)


# --------------------------------------------------------------------- checks


def run_checks(body, arm, frame_count):
    mid = max(1, frame_count // 2)
    track_indices = track_vertex_indices(body)
    rows = per_frame_stats(body, arm, range(1, frame_count + 1), track_indices=track_indices)
    scene = bpy.context.scene

    def foot(frame):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        return arm.matrix_world @ arm.pose.bones['LeftFoot'].head

    walk = (foot(mid) - foot(1)).length
    ground_dev = max(abs(r[1]) for r in rows)
    bbox_track = max((r[2] - r[3]).length for r in rows)
    torso_track = max((r[4] - r[3]).length for r in rows) if track_indices else bbox_track
    return {
        'frames': frame_count,
        'mid_frame': mid,
        'leftfoot_travel_frame1_to_mid_m': round(walk, 4),
        'leftfoot_travel_ok': bool(walk > 0.2),
        'mesh_min_z_max_abs_dev_m': round(ground_dev, 4),
        'feet_on_ground_ok': bool(ground_dev <= GROUND_TOL),
        'mesh_bbox_centre_to_hips_max_m': round(bbox_track, 4),
        'mesh_torso_centroid_to_hips_max_m': round(torso_track, 4),
        'mesh_track_vertices': len(track_indices),
        'mesh_tracks_rig_ok': bool(torso_track <= TRACK_TOL),
    }
