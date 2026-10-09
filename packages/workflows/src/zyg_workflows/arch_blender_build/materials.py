# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Materials — the flat presets, the texture-mapped library, glass and water.

Moved verbatim out of the old single-file arch_blender_build.py (lines 33-486).
"""

import os

import bpy
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_blender_build')


# ── materials ──────────────────────────────────────────────────────────────
# id-suffix -> (r, g, b, alpha, roughness, metallic)
MAT_COLOURS = {
    'concrete': (0.58, 0.58, 0.56, 1.0, 0.85, 0.0),
    'brick': (0.55, 0.26, 0.19, 1.0, 0.90, 0.0),
    'timber': (0.72, 0.52, 0.30, 1.0, 0.65, 0.0),
    'glass': (0.70, 0.85, 0.95, 0.35, 0.05, 0.0),
    'steel': (0.45, 0.50, 0.58, 1.0, 0.35, 0.8),
    'plaster': (0.92, 0.90, 0.85, 1.0, 0.80, 0.0),
    'grass': (0.30, 0.52, 0.20, 1.0, 0.95, 0.0),
    'asphalt': (0.16, 0.16, 0.17, 1.0, 0.90, 0.0),
    'stone': (0.55, 0.53, 0.50, 1.0, 0.85, 0.0),
    'roof_tile': (0.68, 0.33, 0.22, 1.0, 0.80, 0.0),
    'zinc': (0.55, 0.57, 0.60, 1.0, 0.45, 0.6),
    'water': (0.20, 0.45, 0.70, 0.7, 0.05, 0.0),
    'gravel': (0.60, 0.58, 0.54, 1.0, 0.95, 0.0),
    'paint_white': (0.95, 0.95, 0.94, 1.0, 0.50, 0.0),
    'paint_dark': (0.15, 0.15, 0.16, 1.0, 0.50, 0.0),
    'blockwork': (0.62, 0.62, 0.60, 1.0, 0.90, 0.0),
    # landscape (2026-09-07): rock, snow, sand, soil, foliage — same hexes as architecture_studio.MATERIALS
    'rock': (0.43, 0.42, 0.39, 1.0, 0.95, 0.0),
    'snow': (0.96, 0.96, 0.97, 1.0, 0.60, 0.0),
    'sand': (0.85, 0.77, 0.56, 1.0, 0.95, 0.0),
    'soil': (0.35, 0.27, 0.20, 1.0, 0.95, 0.0),
    'foliage': (0.25, 0.42, 0.18, 1.0, 0.95, 0.0),
}
MAT_FALLBACK = (0.55, 0.55, 0.55, 1.0, 0.8, 0.0)

# a record without `mat` still gets a plausible surface, by kind
KIND_DEFAULT_MAT = {
    'wall': 'mat_plaster',
    'partition': 'mat_plaster',
    'door': 'mat_timber',
    'double_door': 'mat_timber',
    'window': 'mat_glass',
    'road': 'mat_asphalt',
    'path': 'mat_gravel',
    'pad': 'mat_grass',
    'roof_flat': 'mat_zinc',
    'roof_gable': 'mat_roof_tile',
    'roof_hip': 'mat_roof_tile',
    'roof_shed': 'mat_zinc',
    'roof_vault': 'mat_zinc',
    'roof_dome': 'mat_zinc',
    'railing': 'mat_steel',
    'ladder': 'mat_steel',
    'truss': 'mat_steel',
    'bollard': 'mat_steel',
    'person': 'mat_paint_dark',
}

_MATERIALS = {}

# ── library materials: the real texture maps (2026-09-11) ──────────────────
# A record's `mat` is either one of the flat MAT_COLOURS presets above (mat_*)
# or a catalogue id from the studio's Materials rail (pht_*, acg_*). Every
# catalogue id used to fall through to MAT_FALLBACK, so a building whose every
# surface had been chosen still rendered as grey massing. The maps are on disk
# next to the mesh packs, and they carry the one number that makes them read as
# architecture: size_m, how many METRES of wall one tile covers.
_LIB_DEFS = None
_LIB_ROOT = ''
_LIB_SLOTS = ('map', 'roughnessMap', 'normalMap', 'aoMap')


def lib_def(mat_id):
    """(abs map paths, (sx, sy) tile size in metres) for a Materials-rail id, or
    None when the id is not catalogued or its albedo is missing from disk.
    architecture_materials is imported lazily, inside the function, so a missing
    catalogue degrades to the flat presets instead of breaking the import."""
    global _LIB_DEFS, _LIB_ROOT
    if _LIB_DEFS is None:
        _LIB_DEFS = {}
        try:
            from zyg_workflows import architecture_materials as AM

            _LIB_ROOT = AM.PACKS_ROOT
            _LIB_DEFS = (AM.catalogue() or {}).get('defs') or {}
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[arch_blender_build] material catalogue unavailable: {e!r}')
    d = _LIB_DEFS.get(mat_id)
    maps = (d or {}).get('maps') or {}
    out = {}
    for slot in _LIB_SLOTS:
        rel = maps.get(slot)
        if not rel:
            continue
        path = os.path.join(_LIB_ROOT, rel)
        if os.path.exists(path):
            out[slot] = path
    if 'map' not in out:
        return None
    sx, sy = ((d.get('size_m') or [1.0, 1.0]) + [1.0, 1.0])[:2]
    sx = float(sx or 1.0) or 1.0
    sy = float(sy or sx) or sx
    return out, (sx, sy)


def _tex_image(path, non_colour):
    """One image datablock per file, however many materials want it."""
    img = bpy.data.images.load(path, check_existing=True)
    if non_colour:
        try:
            img.colorspace_settings.name = 'Non-Color'
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('non-colour colorspace not settable on %s: %s', path, _exc)
    return img


def get_material_tex(mat_id, maps, size_m):
    """An image-texture material for one library surface. BOX projection on
    OBJECT coordinates scaled 1/size_m, so the tile keeps its published physical
    size on every face of a mesh that carries no UV map — which is every mesh
    this builder makes."""
    sx, sy = size_m
    m = bpy.data.materials.new(mat_id)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    if bsdf is None:
        raise RuntimeError('material has no Principled BSDF')
    bx, by = bsdf.location.x, bsdf.location.y
    tc = nt.nodes.new('ShaderNodeTexCoord')
    tc.location = (bx - 1240, by)
    mp = nt.nodes.new('ShaderNodeMapping')
    mp.location = (bx - 1040, by)
    mp.inputs['Scale'].default_value = (1.0 / sx, 1.0 / sy, 1.0 / sx)
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])

    def tex(slot, y, non_colour):
        n = nt.nodes.new('ShaderNodeTexImage')
        n.image = _tex_image(maps[slot], non_colour)
        n.projection = 'BOX'
        n.projection_blend = 0.25
        n.extension = 'REPEAT'
        n.location = (bx - 800, y)
        nt.links.new(mp.outputs['Vector'], n.inputs['Vector'])
        return n

    colour = tex('map', by + 340, False).outputs['Color']
    if 'aoMap' in maps:
        ao = tex('aoMap', by + 640, True)
        mix = nt.nodes.new('ShaderNodeMixRGB')
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Fac'].default_value = 1.0
        mix.location = (bx - 420, by + 340)
        nt.links.new(colour, mix.inputs['Color1'])
        nt.links.new(ao.outputs['Color'], mix.inputs['Color2'])
        colour = mix.outputs['Color']
    nt.links.new(colour, bsdf.inputs['Base Color'])
    if 'roughnessMap' in maps:
        nt.links.new(tex('roughnessMap', by, True).outputs['Color'], bsdf.inputs['Roughness'])
    else:
        bsdf.inputs['Roughness'].default_value = 0.85
    if 'normalMap' in maps:
        nmap = nt.nodes.new('ShaderNodeNormalMap')
        nmap.location = (bx - 300, by - 340)
        nt.links.new(tex('normalMap', by - 340, True).outputs['Color'], nmap.inputs['Color'])
        nt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
    # Workbench reads diffuse_color, so the object is never black in a solid view
    r, g, b, a, rough, metal = MAT_FALLBACK
    m.diffuse_color = (r, g, b, a)
    m.roughness = rough
    return m


# ── glass and water: the two surfaces a flat Principled cannot fake ─────────
# (2026-09-16) mat_glass used to be a Principled with alpha 0.35 in BLEND mode:
# no reflection, no refraction, nothing of the lobby behind it — every curtain
# wall, the canopy and the pool weir rendered MILKY WHITE, and the canopy threw
# an opaque shadow. Glass is now transmissive (Cycles refracts and reflects it;
# EEVEE Next raytraces the refraction), and the shadow ray is routed through a
# tinted Transparent BSDF so what stands under a glass canopy is lit, not black.
#
# look -> (base rgb, roughness, ior, eevee alpha, shadow tint factor)
#   ''      a real thickness of glass: a glass wall, a mirror, a glass beam
#   panel   a THIN pane — curtain wall, canopy, balustrade, the pool weir. It
#           has no depth to refract through, so EEVEE gets alpha instead of
#           raytraced refraction (the brief's 0.15) and the sky reflects off it.
#   clear   the entrance door: untinted, so the arrival reads as a way in.
GLASS_LOOKS = {
    '': ((0.92, 0.97, 1.00), 0.02, 1.50, 0.22, 0.80),
    'panel': ((0.85, 0.93, 0.95), 0.04, 1.50, 0.15, 0.82),
    'clear': ((0.96, 0.99, 1.00), 0.02, 1.50, 0.12, 0.88),
}
GLASS_PANEL_KINDS = frozenset(
    (
        'curtain_wall',
        'window',
        'canopy',
        'parapet',
        'parapet_cap',
        'balustrade',
        'glass_balustrade',
        'railing',
        'screen',
        'skylight',
        'pool',
        'shopfront',
    )
)
GLASS_CLEAR_KINDS = frozenset(('door', 'double_door', 'revolving_door', 'sliding_door'))
# the specular highlight EEVEE needs when the pane is faked with alpha
GLASS_EEVEE_SPEC = 0.5
WATER_EEVEE_ALPHA = 0.60


def glass_look(kind):
    """Which of GLASS_LOOKS a record of this kind wants."""
    k = str(kind or '')
    if k in GLASS_CLEAR_KINDS:
        return 'clear'
    if k in GLASS_PANEL_KINDS:
        return 'panel'
    return ''


def _sock(bsdf, names, value):
    """Set the first input socket that exists — the Principled's names moved
    between 3.x and 4.x ('Transmission' -> 'Transmission Weight')."""
    for n in names:
        s = bsdf.inputs.get(n)
        if s is not None:
            try:
                s.default_value = value
                return True
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('bsdf socket %s not settable: %s', n, _exc)
    return False


def _mat_flag(m, name, value):
    try:
        setattr(m, name, value)
        return True
    except Exception:  # noqa: BLE001
        return False


def _transparent_surface(m, alpha):
    """Mark a material as one the EEVEE pass may thin down (tune_glass_for_eevee)
    and give it the EEVEE-Next transparency settings that apply in both engines."""
    m['zyg_eevee_alpha'] = float(alpha)
    _mat_flag(m, 'use_backface_culling', False)
    _mat_flag(m, 'use_transparency_overlap', True)
    _mat_flag(m, 'use_transparent_shadow', True)
    # 4.2+ EEVEE-Next name first; the legacy names still exist in 4.3
    _mat_flag(m, 'use_raytrace_refraction', True)
    _mat_flag(m, 'use_screen_refraction', True)
    _mat_flag(m, 'refraction_depth', 0.0)


def get_material_glass(look=''):
    look = look if look in GLASS_LOOKS else ''
    key = 'mat_glass|' + look
    if key in _MATERIALS:
        return _MATERIALS[key]
    rgb, rough, ior, eevee_a, shadow = GLASS_LOOKS[look]
    m = bpy.data.materials.new('mat_glass' + ((' ' + look) if look else ''))
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    out = nt.nodes.get('Material Output')
    if bsdf is not None:
        bsdf.inputs['Base Color'].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Alpha'].default_value = 1.0
        _sock(bsdf, ('Transmission Weight', 'Transmission'), 1.0)
        _sock(bsdf, ('IOR',), ior)
        _sock(bsdf, ('Specular IOR Level', 'Specular'), 0.5)
    if bsdf is not None and out is not None:
        # Cycles blocks a shadow ray at a transmissive BSDF, so a glass canopy
        # would still cast a BLACK shadow. The shadow ray goes through a tinted
        # Transparent BSDF instead: what is under the canopy stays lit.
        tr = nt.nodes.new('ShaderNodeBsdfTransparent')
        tr.location = (bsdf.location.x, bsdf.location.y - 260)
        tr.inputs['Color'].default_value = (rgb[0] * shadow, rgb[1] * shadow, rgb[2] * shadow, 1.0)
        lp = nt.nodes.new('ShaderNodeLightPath')
        lp.location = (bsdf.location.x - 320, bsdf.location.y - 420)
        mix = nt.nodes.new('ShaderNodeMixShader')
        mix.location = (bsdf.location.x + 260, bsdf.location.y)
        nt.links.new(lp.outputs['Is Shadow Ray'], mix.inputs['Fac'])
        nt.links.new(bsdf.outputs['BSDF'], mix.inputs[1])
        nt.links.new(tr.outputs['BSDF'], mix.inputs[2])
        nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    _transparent_surface(m, eevee_a)
    m['zyg_glass'] = look or 'solid'
    # Workbench reads these: glass stays a pale sheet, never black
    m.diffuse_color = (rgb[0], rgb[1], rgb[2], 0.35)
    m.roughness = rough
    m.metallic = 0.0
    _MATERIALS[key] = m
    return m


def get_material_water():
    """Pool water: transmissive at IOR 1.33 over a noise-bump ripple, with a
    Volume Absorption so the tiled basin shows through and deepens (Cycles).
    EEVEE keeps the ripple and fakes the depth with alpha."""
    key = 'mat_water|'
    if key in _MATERIALS:
        return _MATERIALS[key]
    m = bpy.data.materials.new('mat_water')
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    out = nt.nodes.get('Material Output')
    if bsdf is not None:
        bsdf.inputs['Base Color'].default_value = (0.55, 0.85, 0.95, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.05
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Alpha'].default_value = 1.0
        _sock(bsdf, ('Transmission Weight', 'Transmission'), 1.0)
        _sock(bsdf, ('IOR',), 1.33)
        _sock(bsdf, ('Specular IOR Level', 'Specular'), 0.5)
        noise = nt.nodes.new('ShaderNodeTexNoise')
        noise.location = (bsdf.location.x - 760, bsdf.location.y - 300)
        noise.inputs['Scale'].default_value = 40.0
        noise.inputs['Detail'].default_value = 4.0
        bump = nt.nodes.new('ShaderNodeBump')
        bump.location = (bsdf.location.x - 320, bsdf.location.y - 300)
        bump.inputs['Strength'].default_value = 0.15
        nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    if out is not None:
        vol = nt.nodes.new('ShaderNodeVolumeAbsorption')
        vol.location = (bsdf.location.x if bsdf else 0, (bsdf.location.y if bsdf else 0) - 620)
        vol.inputs['Color'].default_value = (0.10, 0.35, 0.55, 1.0)
        vol.inputs['Density'].default_value = 0.08
        nt.links.new(vol.outputs['Volume'], out.inputs['Volume'])
    _transparent_surface(m, WATER_EEVEE_ALPHA)
    m['zyg_water'] = True
    r, g, b, a, rough, metal = MAT_COLOURS['water']
    m.diffuse_color = (r, g, b, a)
    m.roughness = rough
    m.metallic = metal
    _MATERIALS[key] = m
    return m


def tune_glass_for_eevee(scene=None):
    """Called from blender_power's EEVEE branch, inside the render pass.

    A thin pane has no thickness for EEVEE Next's screen-space refraction to
    bend light through, so the raytraced transmission renders as a dark sheet.
    Every material this builder marked (`zyg_eevee_alpha`) is switched to
    BLENDED alpha with a specular highlight, which is what reads as glass in
    EEVEE. Cycles never calls this. Returns how many materials were retuned."""
    n = 0
    for m in bpy.data.materials:
        try:
            alpha = m.get('zyg_eevee_alpha')
            if alpha is None or not m.use_nodes or m.node_tree is None:
                continue
            bsdf = m.node_tree.nodes.get('Principled BSDF')
            if bsdf is None:
                continue
            bsdf.inputs['Alpha'].default_value = float(alpha)
            _sock(bsdf, ('Specular IOR Level', 'Specular'), GLASS_EEVEE_SPEC)
            _mat_flag(m, 'surface_render_method', 'BLENDED')
            _mat_flag(m, 'blend_method', 'BLEND')
            _mat_flag(m, 'shadow_method', 'HASHED')
            n += 1
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[arch_blender_build] eevee glass tune failed on {m.name}: {e!r}')
    return n


def get_material(mat_id, kind=''):
    mat_id = mat_id or 'mat_concrete'
    if mat_id == 'mat_glass':
        return get_material_glass(glass_look(kind))
    if mat_id == 'mat_water':
        return get_material_water()
    if mat_id in _MATERIALS:
        return _MATERIALS[mat_id]
    if not mat_id.startswith('mat_'):
        found = lib_def(mat_id)
        if found is None:
            # a catalogue id with no maps on disk whose NAME says glass would
            # otherwise render as the grey fallback slab
            if 'glass' in mat_id.lower():
                return get_material_glass(glass_look(kind))
            _zyg_log.info(f'[arch_blender_build] no maps for {mat_id}')
        else:
            try:
                m = get_material_tex(mat_id, found[0], found[1])
                _MATERIALS[mat_id] = m
                return m
            except Exception as e:  # noqa: BLE001
                _zyg_log.info(f'[arch_blender_build] no maps for {mat_id}: {e!r}')
    key = mat_id[4:] if mat_id.startswith('mat_') else mat_id
    r, g, b, a, rough, metal = MAT_COLOURS.get(key, MAT_FALLBACK)
    m = bpy.data.materials.new(mat_id)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    if bsdf is not None:
        bsdf.inputs['Base Color'].default_value = (r, g, b, 1.0)
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Metallic'].default_value = metal
        bsdf.inputs['Alpha'].default_value = a
    m.diffuse_color = (r, g, b, a)
    m.roughness = rough
    m.metallic = metal
    if a < 1.0:
        # 4.2+ EEVEE-Next name first; the legacy property still exists in 4.3
        try:
            m.surface_render_method = 'BLENDED'
        except Exception as _exc:
            _zyg_log.debug('surface_render_method not settable: %s', _exc)
        try:
            m.blend_method = 'BLEND'
        except Exception as _exc:
            _zyg_log.debug('blend_method not settable: %s', _exc)
    _MATERIALS[mat_id] = m
    return m


VCOL_ATTR = 'Col'


def get_material_vc(mat_id):
    """The vertex-coloured twin of a preset (2026-09-07): the Principled Base
    Color is driven by the mesh's 'Col' colour attribute instead of one flat
    hex, so the v3 ground can be grass, rock, sand and snow in ONE mesh.
    Roughness and metalness stay the preset's. EEVEE and Cycles read the node;
    Workbench in MATERIAL colour mode shows `diffuse_color`, which is kept at
    the preset's hex so the object is never black there."""
    mat_id = mat_id or 'mat_concrete'
    key = mat_id + '|vc'
    if key in _MATERIALS:
        return _MATERIALS[key]
    base = mat_id[4:] if mat_id.startswith('mat_') else mat_id
    r, g, b, a, rough, metal = MAT_COLOURS.get(base, MAT_FALLBACK)
    m = bpy.data.materials.new(mat_id + ' vc')
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    if bsdf is not None:
        attr = nt.nodes.new('ShaderNodeAttribute')
        attr.attribute_name = VCOL_ATTR
        attr.location = (bsdf.location.x - 320, bsdf.location.y)
        nt.links.new(attr.outputs['Color'], bsdf.inputs['Base Color'])
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Metallic'].default_value = metal
    m.diffuse_color = (r, g, b, a)
    m.roughness = rough
    m.metallic = metal
    _MATERIALS[key] = m
    return m
