# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""a_shape.weights_uv_material — the Weights, UV and Material sections.

Moved verbatim from mesh_studio_ops/a_shape.py lines 1304-1804 (2026-10 split).
"""

from zyg_workflows.mesh_studio import b, c, e, f, i, s
from zyg_workflows.mesh_studio_ops.a_shape.library_import import _side

# ══ WEIGHTS ═════════════════════════════════════════════════════════════════
# Which bone moves which vertex, and by how much. Every op here needs a rig.
# The section exists because auto-weights is right about 90% of a body and
# wrong about exactly the parts an audience watches: shoulders, hips, jaw.

_side(
    'wt_paint',
    'Paint weights',
    'Weights',
    'Paint influence for one bone directly onto the surface with a brush — '
    'add, subtract, blur or set to a value. The manual fix for the shoulder '
    'the automatic bind tore, and the only op in this section that needs the '
    'viewport rather than a number.',
    '<path d="M6.2 17.8c-1.4 1.4-3.2 1-3.2 1s.4-2 1.6-3.2z"/>'
    '<path d="M5.4 14.6l8.8-8.8a2.2 2.2 0 013.2 0l1.2 1.2a2.2 2.2 0 010 3.2'
    'l-8.8 8.8z"/>',
    [
        s('bone', 'Bone', ''),
        e('mode', 'Brush', 'add', ('add', 'subtract', 'blur', 'set')),
        f('strength', 'Strength', 0.5, 0.0, 1.0, 0.01),
        f('radius_mm', 'Radius (mm)', 30.0, 1.0, 300.0, 1.0),
        b('mirror', 'Mirror to the other side', True),
    ],
    needs='rig',
)

_side(
    'wt_smooth',
    'Smooth weights',
    'Weights',
    'Blur the weight map across neighbouring vertices so influence falls off '
    'gradually instead of in a hard edge. The single most effective fix for '
    'a joint that creases like folded paper.',
    '<path d="M3.8 16.4c3.2 0 3.2-8.8 6.4-8.8s3.2 8.8 6.4 8.8 3.6-4.4 3.6-4.4"/><path d="M3.8 19.8h16.4"/>',
    [
        i('iterations', 'Iterations', 3, 1, 40, 1),
        f('factor', 'Strength', 0.5, 0.0, 1.0, 0.01),
        b('selected_bones', 'Selected bones only', False),
        b('keep_total', 'Renormalise after each pass', True),
    ],
    needs='rig',
)

_side(
    'wt_prune',
    'Prune weights',
    'Weights',
    'Delete influences below a threshold. The tiny weights a heat-map bind '
    'sprays everywhere cost memory, break the four-influence limit engines '
    'impose, and move nothing you can see.',
    '<path d="M4.6 19.4L12 12"/><path d="M12 12c0-4 2.6-7.4 7.4-8.4'
    '.8 5.2-2.4 8.4-7.4 8.4z"/><path d="M9.6 14.4l-4.2-4.2"/>',
    [
        f('threshold', 'Remove below', 0.01, 0.0001, 0.2, 0.0001),
        b('renormalise', 'Renormalise afterwards', True),
        b('report', 'Report how many were removed', True),
    ],
    needs='rig',
)

_side(
    'wt_normalise',
    'Normalise weights',
    'Weights',
    "Make every vertex's influences sum to exactly one. A mesh whose weights "
    'sum to 0.8 shrinks towards the origin when posed, and one that sums to '
    '1.2 inflates — both look like a broken rig and neither is.',
    '<path d="M4.4 12h15.2"/><path d="M8 8.6h8M8 15.4h8"/><circle cx="12" cy="12" r="8.2"/>',
    [
        b('active_only', 'Only bones in the deform set', True),
        b('fix_zero', 'Give unweighted vertices to the nearest bone', True),
        b('report', 'List vertices that were off', True),
    ],
    needs='rig',
)

_side(
    'wt_copy_nearest',
    'Copy from nearest',
    'Weights',
    'Transfer weights from another mesh by nearest surface point — how a new '
    'garment, a fitted body or a decimated LOD inherits a bind that already '
    'works instead of being re-solved from nothing.',
    '<path d="M4.4 7.6a4 3.2 0 018 0v8.8a4 3.2 0 01-8 0z"/>'
    '<path d="M4.4 7.6a4 3.2 0 008 0"/>'
    '<path d="M14.4 12h5.2M19.6 12l-2.2-2.2M19.6 12l-2.2 2.2"/>',
    [
        s('source', 'Source mesh', '', 'Library id or path'),
        e('method', 'Match by', 'nearest surface', ('nearest surface', 'nearest vertex', 'projected', 'uv')),
        f('max_dist_mm', 'Max distance (mm)', 20.0, 0.1, 500.0, 0.1),
        b('only_missing', 'Only vertices with no weights', False),
    ],
    needs='rig',
)

_side(
    'wt_mirror',
    'Mirror weights',
    'Weights',
    'Copy weights across the X axis, matching .L to .R by bone name and '
    'vertex position. Only as good as the naming: bones called arm1 and arm2 '
    'cannot be mirrored and the op will say so rather than guess.',
    '<path d="M12 3.8v16.4"/>'
    '<path d="M4.6 8.2h5.2v7.6H4.6z"/><path d="M14.2 8.2h5.2v7.6h-5.2z"/>'
    '<path d="M7.2 11.2v1.6M16.8 11.2v1.6"/>',
    [
        e('direction', 'Direction', '+X to -X', ('+X to -X', '-X to +X')),
        f('tolerance_mm', 'Match tolerance (mm)', 0.5, 0.001, 20.0, 0.001),
        b('by_name', 'Match bones by .L/.R suffix', True),
        b('by_topology', 'Fall back to topology match', True),
    ],
    needs='rig',
)

_side(
    'wt_limit',
    'Limit per vertex',
    'Weights',
    'Cap how many bones may influence one vertex and renormalise what '
    'survives. Engines impose four; ignoring the cap means the runtime '
    'silently drops whichever influences it likes least, which is rarely the '
    'ones you would have dropped.',
    '<path d="M12 4.6v5.4"/><path d="M12 10l-5 3.4M12 10l5 3.4"/>'
    '<path d="M12 10v3.4"/><circle cx="12" cy="3.4" r="1.4"/>'
    '<path d="M4.6 17.4h14.8"/>',
    [
        i('max', 'Max influences', 4, 1, 12, 1),
        b('renormalise', 'Renormalise after capping', True),
        b('report_worst', 'Report the worst vertices first', True),
    ],
    needs='rig',
)

_side(
    'wt_heatmap',
    'Heat-map view',
    'Weights',
    'Colour the surface by the influence of one bone, by the number of '
    'influences per vertex, or by where the weights do not sum to one. A '
    'view, not an edit — and the fastest way to see a bad bind before it is '
    'posed.',
    '<path d="M12 4.2a7.6 7.6 0 017.6 7.6c0 4.2-3.4 8-7.6 8s-7.6-3.8-7.6-8'
    'A7.6 7.6 0 0112 4.2z"/><path d="M12 8.6a3.2 3.2 0 100 6.4"/>'
    '<path d="M12 8.6v6.4"/>',
    [
        e('show', 'Show', 'one bone', ('one bone', 'influence count', 'unweighted', 'sum error')),
        s('bone', 'Bone', ''),
        e('ramp', 'Colour ramp', 'cool→warm', ('cool→warm', 'greyscale', 'viridis')),
        b('wire', 'Overlay the wireframe', False),
    ],
    cls='pix',
    needs='rig',
)


# ══ UV ══════════════════════════════════════════════════════════════════════
# How the surface is flattened into the square every texture and every bake
# lands in. Nothing in Texture or Bake (part B) can be trusted before this
# section is right: a bake is only ever as good as the layout it lands in.

_side(
    'uv_unwrap_smart',
    'Unwrap (smart)',
    'UV',
    'Cut the mesh into islands automatically at an angle threshold and pack '
    'them. No thought required and no control either: correct for props, '
    'bakes and anything nobody will hand-paint, wrong for a face.',
    '<path d="M4.6 4.6h14.8v14.8H4.6z"/><path d="M4.6 11.4h6.8v8M11.4 4.6v6.8h8"/>',
    [
        f('angle', 'Island angle (deg)', 66.0, 1.0, 89.0, 1.0),
        f('margin', 'Island margin', 0.02, 0.0, 0.2, 0.001),
        b('area_weight', 'Weight by area', True),
        b('rotate', 'Allow island rotation', True),
    ],
)

_side(
    'uv_unwrap_seams',
    'Unwrap (seams)',
    'UV',
    'Unwrap along seams you marked — the hairline, the inside of the arm, '
    'the back of the leg, where a real garment has a seam. Slower and the '
    'only way to get a layout a human can paint on.',
    '<path d="M5.2 19a9 9 0 0113.6 0"/><path d="M12 4.2v9.6"/><path d="M9.4 6.6l2.6-2.6 2.6 2.6M10.2 10.4h3.6"/>',
    [
        e('method', 'Solver', 'angle based', ('angle based', 'conformal', 'slim')),
        b('fill_holes', 'Fill holes before solving', True),
        b('correct_aspect', 'Correct aspect', True),
        f('margin', 'Island margin', 0.02, 0.0, 0.2, 0.001),
    ],
)

_side(
    'uv_atlas_pack',
    'Atlas pack',
    'UV',
    'Repack every island into the square as tightly as it will go, at a '
    'chosen texel density. Density is the point: islands packed to fit look '
    'fine in the layout and give you a face at 200 px and a boot at 900.',
    '<path d="M4.4 4.4h6.4v6.4H4.4zM12.2 4.4h7.4v3.8h-7.4z"/>'
    '<path d="M12.2 9.6h3.4v9.8h-3.4zM17 9.6h2.6v5.2H17z"/>'
    '<path d="M4.4 12.4h6.4v7h-6.4z"/>',
    [
        i('size', 'Texture size', 2048, 256, 8192, 256),
        f('density', 'Texels per cm', 10.0, 0.5, 100.0, 0.5),
        f('margin', 'Margin (px)', 8.0, 0.0, 64.0, 1.0),
        b('equal_density', 'Force equal density on all islands', True),
        b('rotate', 'Allow rotation', True),
    ],
)

_side(
    'uv_checker',
    'Checker view',
    'UV',
    'Put a numbered checker on the surface so distortion and density are '
    'visible: squares that stretch are a bad unwrap, squares of different '
    'sizes are a bad pack. A view, not an edit, and the fastest honest test '
    'of both.',
    '<path d="M4.6 4.6h14.8v14.8H4.6z"/>'
    '<path d="M4.6 4.6h4.9v4.9H4.6zM14.5 4.6h4.9v4.9h-4.9z"/>'
    '<path d="M9.5 9.5h5v5h-5zM4.6 14.5h4.9v4.9H4.6z"/>'
    '<path d="M14.5 14.5h4.9v4.9h-4.9z"/>',
    [
        e('pattern', 'Pattern', 'numbered', ('numbered', 'plain', 'colour grid', 'uv gradient')),
        i('squares', 'Squares across', 32, 4, 256, 1),
        b('show_seams', 'Draw the seams', True),
    ],
    cls='pix',
)

_side(
    'uv_scale_islands',
    'Scale islands',
    'UV',
    'Resize selected islands — by hand, or to equalise texel density across '
    'all of them, or to give the face and hands more of the square than the '
    'soles of the feet. Deliberate unevenness is often right; accidental '
    'unevenness never is.',
    '<path d="M4.6 4.6h14.8v14.8H4.6z"/>'
    '<path d="M7.2 7.2h4.2v4.2H7.2z"/><path d="M13.4 12.6h4.2v4.2h-4.2z"/>'
    '<path d="M11.4 11.4l2 1.2"/>',
    [
        f('scale', 'Scale', 1.0, 0.05, 20.0, 0.01),
        e('mode', 'Mode', 'selected', ('selected', 'equalise all', 'by material', 'by named group')),
        b('keep_centre', 'Scale about each island centre', True),
        b('repack', 'Repack afterwards', True),
    ],
)

_side(
    'uv_straighten',
    'Straighten',
    'UV',
    'Force a chosen edge loop to a straight line in UV space and relax the '
    'island around it. What makes a sleeve, a strap or a tiled trim texture '
    'line up instead of wobbling along a hand-cut island.',
    '<path d="M4.4 15.6c3.4-1.2 5.4 1.6 8.2-.4s4.2-4.2 7-4.6"/>'
    '<path d="M4.4 19.6h15.2"/>'
    '<path d="M17.2 8.4l2.4 2.2-2.4 2.2"/>',
    [
        e('target', 'Straighten to', 'auto', ('auto', 'horizontal', 'vertical')),
        f('relax', 'Relax the rest', 0.6, 0.0, 1.0, 0.01),
        b('pin_ends', 'Pin the end vertices', True),
    ],
)

_side(
    'uv_stitch',
    'Stitch',
    'UV',
    'Sew two island borders back together where they were cut, welding the '
    'UVs so the seam stops showing as a hard line in every texture and every '
    'bake. The inverse of marking a seam, applied in the layout.',
    '<path d="M4.4 9.4h15.2M4.4 14.6h15.2"/><path d="M6.6 9.4l2.6 5.2M11.4 9.4l2.6 5.2M16.2 9.4l2.6 5.2"/>',
    [
        f('limit', 'Max UV distance', 0.02, 0.0, 0.5, 0.001),
        b('snap_to_target', 'Move the smaller island', True),
        b('clear_seam', 'Clear the seam mark too', True),
    ],
)

_side(
    'uv_export_layout',
    'Export layout',
    'UV',
    'Write the UV layout out as PNG or SVG at texture resolution — the '
    'template a texture artist paints over, or the overlay used to check a '
    'bake landed where it should.',
    '<path d="M5.4 4.6h13.2v10.4H5.4z"/>'
    '<path d="M5.4 9.4h6.6v5.6M12 4.6v4.8h6.6"/>'
    '<path d="M12 17.2v4M9.6 19l2.4 2.2 2.4-2.2"/>',
    [
        e('fmt', 'Format', 'png', ('png', 'svg', 'eps')),
        i('size', 'Size (px)', 2048, 256, 8192, 256),
        f('opacity', 'Fill opacity', 0.25, 0.0, 1.0, 0.01),
        b('modified_only', 'Only modified islands', False),
    ],
    cls='act',
)


# ══ MATERIAL ════════════════════════════════════════════════════════════════
# What the surface is made of. The three bakes here are the ops that turn
# geometry into texture and are the reason the UV section above exists. Part B
# (Texture, Bake) handles the maps themselves; this section handles the slots,
# the shader and the properties the maps plug into.

_side(
    'mat_clay',
    'Clay',
    'Material',
    'Replace everything with one matte clay shader. The neutral surface for '
    'judging form — colour and texture hide a bad silhouette, and a model '
    'that reads well in clay reads well in anything.',
    '<path d="M6.2 19.4c0-4.4 2.6-7.6 5.8-7.6s5.8 3.2 5.8 7.6z"/>'
    '<path d="M8.6 11.4c1-2.4 5.8-2.4 6.8 0"/>'
    '<circle cx="12" cy="6.2" r="2.6"/>',
    [
        c('colour', 'Clay colour', '#c9c3b8'),
        f('roughness', 'Roughness', 0.72, 0.0, 1.0, 0.01),
        b('keep_vcol', 'Keep vertex colours', False),
        b('show_wire', 'Overlay the wireframe', False),
    ],
)

_side(
    'mat_pbr_set',
    'PBR set',
    'Material',
    'Assign a full physically-based set — base colour, roughness, metalness, '
    'normal, AO — from a library material or from maps on disk, with the '
    'tiling and the colour space stated rather than guessed. A normal map '
    'read as sRGB is the classic silent wrongness.',
    '<circle cx="12" cy="12" r="7.6"/>'
    '<path d="M12 4.4v15.2"/><path d="M4.4 12h15.2"/>'
    '<path d="M6.6 6.6l10.8 10.8M17.4 6.6L6.6 17.4"/>',
    [
        s('material', 'Library material', ''),
        f('tiling', 'Tiling', 1.0, 0.05, 64.0, 0.05),
        b('srgb_basecolor', 'Base colour is sRGB', True),
        b('linear_data', 'Data maps are linear', True),
        e('normal_kind', 'Normal convention', 'OpenGL (+Y)', ('OpenGL (+Y)', 'DirectX (-Y)')),
    ],
)

_side(
    'mat_vcol_bake',
    'Vertex colour bake',
    'Material',
    'Bake per-vertex colour — what a scan or a photogrammetry import usually '
    'carries instead of a texture — into a proper base-colour map in the UV '
    'layout. The step that turns a scan into something a renderer can light '
    'at any resolution.',
    '<path d="M12 3.8l6.2 3.6v7.2L12 18.2l-6.2-3.6V7.4z"/>'
    '<circle cx="12" cy="7.6" r="1.3"/><circle cx="8.6" cy="13" r="1.3"/>'
    '<circle cx="15.4" cy="13" r="1.3"/>',
    [
        i('size', 'Map size', 2048, 256, 8192, 256),
        i('layer', 'Colour layer', 0, 0, 8, 1),
        i('dilate', 'Edge dilation (px)', 8, 0, 64, 1),
        b('srgb', 'Write as sRGB', True),
    ],
    needs='gpu',
)

_side(
    'mat_ao_bake',
    'AO bake',
    'Material',
    'Bake ambient occlusion — how much of the sky each point can see — into '
    'a map. Cheap contact shadow in the creases that survives any lighting, '
    'and the map most likely to be wrong if the mesh is not watertight.',
    '<circle cx="12" cy="12" r="7.4"/>'
    '<path d="M12 4.6a7.4 7.4 0 000 14.8 4.6 7.4 0 000-14.8z"/>'
    '<path d="M6.8 6.8l-2 -2M17.2 6.8l2-2"/>',
    [
        i('size', 'Map size', 2048, 256, 8192, 256),
        i('samples', 'Samples', 128, 8, 2048, 8),
        f('distance_mm', 'Ray distance (mm)', 200.0, 1.0, 5000.0, 1.0),
        b('local_only', 'Occlude against this mesh only', True),
        i('dilate', 'Edge dilation (px)', 8, 0, 64, 1),
    ],
    needs='gpu',
)

_side(
    'mat_normal_bake',
    'Normal bake',
    'Material',
    'Bake the detail of a high-resolution mesh into a tangent-space normal '
    'map on the low-resolution one. The whole point of keeping both: the LOD '
    'carries the sculpt without carrying its triangles. Cage distance is the '
    'knob that decides whether it works.',
    '<path d="M4.6 17.4l5-8 3.2 4.2 2.4-3 4.2 6.8z"/>'
    '<path d="M9.6 9.4V5.6M9.6 5.6l-1.6 1.8M9.6 5.6l1.6 1.8"/>'
    '<path d="M4.6 20.6h14.8"/>',
    [
        s('high', 'High-resolution mesh', ''),
        i('size', 'Map size', 2048, 256, 8192, 256),
        f('cage_mm', 'Cage distance (mm)', 5.0, 0.1, 200.0, 0.1),
        e('space', 'Space', 'tangent', ('tangent', 'object', 'world')),
        e('convention', 'Convention', 'OpenGL (+Y)', ('OpenGL (+Y)', 'DirectX (-Y)')),
    ],
    needs='gpu',
)

_side(
    'mat_roughness',
    'Roughness',
    'Material',
    'How scattered the reflection is — the difference between wet skin and '
    'chalk, polished steel and brushed. Set as a constant or driven by a '
    'map; it is the property that carries more of "what is this made of" '
    'than base colour does.',
    '<circle cx="12" cy="12" r="7.6"/>'
    '<path d="M8.4 9.2c1.4 1.4 2.8-1 4.2.4s2.8 3.2 3.4 2"/>'
    '<path d="M7.6 13.4c1.8 1.6 3.6-.8 5.4.8s2.6 1.2 3.4.6"/>',
    [
        f('value', 'Roughness', 0.5, 0.0, 1.0, 0.01),
        s('map', 'Roughness map', ''),
        b('invert_map', 'Map is glossiness (invert)', False),
        b('linear', 'Read the map as linear data', True),
    ],
)

_side(
    'mat_metalness',
    'Metalness',
    'Material',
    'Whether the surface is a conductor. Almost binary in reality — a '
    'material is metal or it is not, and values in the middle are a texture '
    'boundary, not a half-metal. Metal has no diffuse colour, which is why '
    'this and base colour have to be set together.',
    '<path d="M4.6 8.2l7.4-4 7.4 4-7.4 4z"/><path d="M4.6 12.4l7.4 4 7.4-4"/><path d="M4.6 16.4l7.4 4 7.4-4"/>',
    [
        f('value', 'Metalness', 0.0, 0.0, 1.0, 0.01),
        s('map', 'Metalness map', ''),
        b('warn_mid', 'Warn on values between 0.1 and 0.9', True),
    ],
)

_side(
    'mat_subsurface',
    'Subsurface',
    'Material',
    'Light entering the surface, scattering and leaving somewhere else — the '
    'reason skin, wax, marble and leaves do not look like painted plastic. '
    'The radius is per-channel and red travels furthest, which is what makes '
    'ears and fingers glow.',
    '<path d="M12 4.4a7.6 7.6 0 017.6 7.6c0 4-3.4 7.6-7.6 7.6"/>'
    '<path d="M12 4.4a7.6 7.6 0 00-7.6 7.6c0 4 3.4 7.6 7.6 7.6"/>'
    '<path d="M8.6 9.6c2.4 1.6 4.4 3 6.8 5.6"/>'
    '<path d="M9.4 14.8c1.8-1.6 3.4-2.8 5.2-4"/>',
    [
        f('weight', 'Amount', 0.2, 0.0, 1.0, 0.01),
        f('radius_r', 'Radius R (mm)', 3.2, 0.0, 50.0, 0.1),
        f('radius_g', 'Radius G (mm)', 1.4, 0.0, 50.0, 0.1),
        f('radius_b', 'Radius B (mm)', 0.9, 0.0, 50.0, 0.1),
        c('tint', 'Scatter tint', '#e8b6a2'),
    ],
)

_side(
    'mat_two_sided',
    'Two-sided',
    'Material',
    'Render back faces instead of culling them, and decide whether their '
    'normals are flipped to face the camera. Needed for leaves, cloth, hair '
    'cards and anything with no thickness; wasteful and shadow-acne prone on '
    'a closed solid.',
    '<path d="M4.4 12h15.2"/><path d="M8 6.4h11.6v5.6H8z"/><path d="M4.4 12h11.6v5.6H4.4z"/>',
    [
        b('double_sided', 'Render back faces', True),
        b('flip_backface_normals', 'Flip normals on back faces', True),
        b('shadow_both', 'Cast shadows from both sides', False),
    ],
)

_side(
    'mat_slots',
    'Material slots',
    'Material',
    'The list of materials on this mesh and which faces belong to each — '
    'add, remove, rename, merge duplicates, assign a selection. A mesh that '
    'arrives with fourteen slots that are all the same grey is the usual '
    'reason a simple prop draws in fourteen passes.',
    '<path d="M4.6 5.8h14.8v3.6H4.6z"/><path d="M4.6 10.2h14.8v3.6H4.6z"/>'
    '<path d="M4.6 14.6h14.8v3.6H4.6z"/><path d="M7.4 7.6h.1M7.4 12h.1"/>',
    [
        e(
            'action',
            'Action',
            'list',
            ('list', 'add', 'remove unused', 'merge duplicates', 'assign selection', 'rename'),
        ),
        s('name', 'Slot name', ''),
        b('report_faces', 'Show the face count per slot', True),
    ],
    cls='act',
)
