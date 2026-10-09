# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""BLENDER SIDE: orientation, materials, scene build, camera placement."""

from zyg_workflows.geom.mv_render.constants import math

# ===========================================================================
# BLENDER SIDE
# ===========================================================================


def _bl_orient(obj):
    """Put the imported GLB into the repo's internal frame: +Z up, figure facing -Y.

    TRAP, measured 2026-08-07, and it bites TWICE.

    (a) The file is NOT Y-up. Read straight out of the .glb with trimesh, the vertex
        data has its 1.6800 m stature on axis 2 (z: -0.8837..0.7963, head at max) and
        the 0.4408 m body depth on axis 1 — i.e. our exporter wrote the repo's own
        Z-up frame into a format that is specified as Y-up.
    (b) Blender's glTF importer therefore "corrects" a frame that was already correct:
        it applies gltf(x,y,z) -> blender(x,-z,y), so in Blender the stature lands on
        +Y and, because of the minus sign, the head lands at the MINIMUM. The probe
        bounds (y -0.7963..0.8837) look plausible and are upside down.

    A -90 deg rotation about X maps blender(x,y,z) -> (x, z, -y), which undoes exactly
    that and lands back on the repo's internal frame: +Z up with the head at max, +Y
    depth, figure facing -Y (geom/mesh_skeletons.py _paint culls nrm[:,1] < 0 for a
    camera looking along +y, so the front normals point -y). The FIRST version of this
    function used +90 and rendered 48 immaculate pictures of a pair of legs.

    Do NOT do this with bpy.ops.object.transform_apply — it silently no-ops in a
    background context with no proper active-object state (verified: the bounds came
    back unchanged). Transform the mesh DATA directly.
    """
    import mathutils

    obj.parent = None
    obj.matrix_world = mathutils.Matrix.Identity(4)
    obj.data.transform(mathutils.Matrix.Rotation(math.radians(-90), 4, 'X'))
    co = [v.co for v in obj.data.vertices]
    zmin = min(c.z for c in co)
    xmid = 0.5 * (min(c.x for c in co) + max(c.x for c in co))
    ymid = 0.5 * (min(c.y for c in co) + max(c.y for c in co))
    obj.data.transform(mathutils.Matrix.Translation((-xmid, -ymid, -zmin)))
    obj.data.update()
    co = [v.co for v in obj.data.vertices]

    # Upside-down guard, so the legs render can never come back silently. The top 6 %
    # of stature is one head (measured x-spread 0.160 m on this mesh); the bottom 6 %
    # is two feet standing apart (0.458 m). If the narrow end is at the bottom the
    # orientation is inverted.
    S = float(max(c.z for c in co))

    def _xspread(lo, hi):
        s = [c.x for c in co if lo * S <= c.z <= hi * S]
        return (max(s) - min(s)) if s else 0.0

    top, bot = _xspread(0.94, 1.0), _xspread(0.0, 0.06)
    if not top < bot:
        raise RuntimeError('mesh looks inverted: x-spread top %.3f m >= bottom %.3f m' % (top, bot))
    return {
        'stature_m': S,
        'xspread_top6pct_m': round(top, 4),
        'xspread_bottom6pct_m': round(bot, 4),
        'width_m': float(max(c.x for c in co) - min(c.x for c in co)),
        'depth_m': float(max(c.y for c in co) - min(c.y for c in co)),
        'n_verts': len(obj.data.vertices),
        'n_tris': len(obj.data.polygons),
    }


def _bl_texture_material(name):
    """High-frequency procedural albedo locked to OBJECT space.

    Voronoi F1 COLOUR (scale 110 in object units = 9.1 mm cells on this 1.68 m body,
    22.6 px at this framing) gives a mosaic of randomly-valued cells: dense,
    high-contrast, aperiodic blobs, which is exactly what a DoG blob detector wants.
    The first attempt used the Voronoi *Distance* output through a hard ramp and
    produced a nearly white surface with sparse dark dots — almost no features. The
    mosaic is mixed with a detailed noise at scale 38 (26 mm) so there is structure at
    two scales rather than one.

    Both read Texture Coordinate -> OBJECT. Nothing in this graph can see the camera,
    and _bl_assert_surface_locked walks the tree afterwards to prove it.

    Fully diffuse on purpose: roughness 1.0 and Specular IOR Level 0 remove every
    view-dependent highlight, so the only thing that changes between frames is
    geometry and world-fixed shading. A specular lobe would be a second uncontrolled
    variable in a set whose whole job is to be the clean ceiling.
    """
    import bpy

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    vor = nt.nodes.new('ShaderNodeTexVoronoi')
    noi = nt.nodes.new('ShaderNodeTexNoise')
    bw = nt.nodes.new('ShaderNodeRGBToBW')
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    mix = nt.nodes.new('ShaderNodeMixRGB')

    vor.feature = 'F1'
    vor.distance = 'EUCLIDEAN'
    vor.inputs['Scale'].default_value = 110.0
    vor.inputs['Randomness'].default_value = 1.0
    noi.inputs['Scale'].default_value = 38.0
    noi.inputs['Detail'].default_value = 8.0
    noi.inputs['Roughness'].default_value = 0.55

    # Stretch the mosaic to the full 0.06..0.94 albedo range. The stops sit at 0.30 and
    # 0.70, NOT 0.10/0.90, because the input is the LUMA of a random RGB per cell and
    # luma is a weighted sum of three uniforms: it is not uniform on [0,1], it clusters
    # around 0.5 with sd 0.193. Ramping 0.10..0.90 used barely a third of the available
    # albedo range and measured only 18.8/255 of pixel sd on the subject.
    ramp.color_ramp.elements[0].position = 0.30
    ramp.color_ramp.elements[0].color = (0.06, 0.06, 0.06, 1.0)
    ramp.color_ramp.elements[1].position = 0.70
    ramp.color_ramp.elements[1].color = (0.94, 0.94, 0.94, 1.0)

    mix.blend_type = 'MIX'
    mix.inputs['Fac'].default_value = 0.45

    nt.links.new(tc.outputs['Object'], vor.inputs['Vector'])
    nt.links.new(tc.outputs['Object'], noi.inputs['Vector'])
    nt.links.new(vor.outputs['Color'], bw.inputs['Color'])
    nt.links.new(bw.outputs['Val'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], mix.inputs['Color1'])
    nt.links.new(noi.outputs['Fac'], mix.inputs['Color2'])
    nt.links.new(mix.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Metallic'].default_value = 0.0
    for key in ('Specular IOR Level', 'Specular'):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.0
            break
    return mat


def _bl_grey_material(name):
    """Plain matte grey. Identical shading model, zero albedo variation."""
    import bpy

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (0.55, 0.55, 0.55, 1.0)
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Metallic'].default_value = 0.0
    for key in ('Specular IOR Level', 'Specular'):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.0
            break
    return mat


_SCREEN_SPACE_SOCKETS = ('Window', 'Camera', 'Reflection', 'Normal')


def _bl_assert_surface_locked(mat):
    """Structural half of the texture-lock proof. Raises rather than warns.

    In Blender the ONLY way to make a procedural texture follow the screen instead of
    the surface is to feed a texture node's Vector from Texture Coordinate's Window,
    Camera, Reflection or Normal output (or from a Geometry node's Incoming). If none
    of those is linked and 'Object' is, the pattern is nailed to the object's local
    space and a camera move cannot touch it.
    """
    nt = mat.node_tree
    tcs = [n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexCoord']
    geos = [n for n in nt.nodes if n.bl_idname == 'ShaderNodeNewGeometry']
    if len(tcs) != 1:
        raise RuntimeError('expected exactly 1 Texture Coordinate node, got %d' % len(tcs))
    linked = sorted(s.name for s in tcs[0].outputs if s.is_linked)
    bad = [s for s in linked if s in _SCREEN_SPACE_SOCKETS]
    if bad:
        raise RuntimeError('SCREEN-SPACE texture coordinate in use: %r' % bad)
    if 'Object' not in linked:
        raise RuntimeError('texture is not driven from Object coordinates: %r' % linked)
    for g in geos:
        if any(s.is_linked and s.name == 'Incoming' for s in g.outputs):
            raise RuntimeError('Geometry->Incoming (view vector) feeds the shader')
    return {
        'texcoord_outputs_linked': linked,
        'screen_space_sockets_linked': bad,
        'geometry_nodes': len(geos),
        'verdict': 'surface_locked',
    }


def _bl_scene(cfg, textured):
    """Build the whole scene from scratch and return (mesh_obj, camera_obj, geom, frm)."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    bpy.ops.import_scene.gltf(filepath=cfg['glb'])
    obj = [o for o in bpy.data.objects if o.type == 'MESH'][0]
    for o in list(bpy.data.objects):
        if o.type == 'EMPTY':
            bpy.data.objects.remove(o, do_unlink=True)
    geom = _bl_orient(obj)

    for p in obj.data.polygons:
        p.use_smooth = True

    mat = _bl_texture_material('mvc_tex') if textured else _bl_grey_material('mvc_grey')
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    lock = _bl_assert_surface_locked(mat) if textured else {'verdict': 'n/a_untextured'}

    # --- framing -----------------------------------------------------------
    S = geom['stature_m']
    frame_h = cfg['frame_h_per_stature'] * S
    frame_w = frame_h * cfg['out_w'] / cfg['out_h']
    dist = cfg['lens_mm'] * frame_h / cfg['sensor_mm']
    frame_top_z = S + cfg['head_top_margin'] * frame_h
    target_z = frame_top_z - 0.5 * frame_h
    frm = {
        'stature_m': S,
        'frame_height_m': frame_h,
        'frame_width_m': frame_w,
        'camera_distance_m': dist,
        'target_world': [0.0, 0.0, target_z],
        'px_per_m_at_target': cfg['out_h'] / frame_h,
    }

    cam_d = bpy.data.cameras.new('mvc_cam')
    cam_d.type = 'PERSP'
    cam_d.sensor_fit = 'VERTICAL'
    cam_d.sensor_height = cfg['sensor_mm']
    cam_d.lens = cfg['lens_mm']
    cam_d.clip_start = 0.05
    cam_d.clip_end = 50.0
    cam = bpy.data.objects.new('mvc_cam', cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam

    # --- world-fixed lighting ---------------------------------------------
    # four area lights on a ring 90 deg apart at +25 deg elevation: enough directional
    # shading that the UNTEXTURED control still has a gradient to work with, even
    # enough around 360 deg that no azimuth is underexposed. Fixed in WORLD space —
    # parenting them to the camera would have made every frame identically lit, which
    # is a subtler cheat than a screen-space texture but a cheat all the same.
    import mathutils

    for i, az in enumerate((45.0, 135.0, 225.0, 315.0)):
        ld = bpy.data.lights.new('key%d' % i, 'AREA')
        ld.energy = cfg['light_energy']
        ld.size = 2.0
        lo = bpy.data.objects.new('key%d' % i, ld)
        sc.collection.objects.link(lo)
        a = math.radians(az)
        e = math.radians(25.0)
        r = 3.0
        lo.location = (r * math.cos(e) * math.sin(a), -r * math.cos(e) * math.cos(a), target_z + r * math.sin(e))
        d = mathutils.Vector((0.0, 0.0, target_z)) - lo.location
        lo.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

    world = bpy.data.worlds.new('mvc_world')
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (0.035, 0.035, 0.038, 1.0)
    bg.inputs['Strength'].default_value = 1.0

    # --- render settings ---------------------------------------------------
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = cfg['samples']
    sc.cycles.use_denoising = True
    sc.render.resolution_x = cfg['out_w']
    sc.render.resolution_y = cfg['out_h']
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.image_settings.color_depth = '8'
    # Standard, NOT the 4.x default AgX. AgX is a filmic tone map with a long shoulder;
    # it compresses exactly the highlight range the mosaic texture lives in and cost
    # about half the albedo contrast in the first calibration render. A control set
    # wants the flattest, most predictable transfer available.
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    return obj, cam, geom, frm, lock


def _bl_place_camera(cam, az_deg, el_deg, target, dist):
    """Turntable position. az 0 = camera at -Y looking toward +Y, i.e. the FRONT of
    the figure (the cage faces -Y in this frame; verified by eye on cell_00 of the
    positive set, which shows the face). az increases toward +X."""
    import mathutils

    a = math.radians(az_deg)
    e = math.radians(el_deg)
    t = mathutils.Vector(target)
    cam.location = t + mathutils.Vector(
        (dist * math.cos(e) * math.sin(a), -dist * math.cos(e) * math.cos(a), dist * math.sin(e))
    )
    cam.rotation_euler = (t - cam.location).to_track_quat('-Z', 'Y').to_euler()
