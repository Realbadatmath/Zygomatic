# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""a_shape.topology_transform — the Topology and Transform sections.

Moved verbatim from mesh_studio_ops/a_shape.py lines 360-813 (2026-10 split).
"""

from zyg_workflows.mesh_studio import b, e, f, i, s
from zyg_workflows.mesh_studio_ops.a_shape.library_import import _side

# ══ TOPOLOGY ════════════════════════════════════════════════════════════════
# How the surface is divided. Almost every downstream failure -- a rig that
# collapses at the elbow, a UV that cannot be unwrapped, a bake full of holes
# -- is a topology problem wearing another hat, which is why this is the
# largest section in the studio.

_side(
    'top_decimate',
    'Decimate',
    'Topology',
    'Reduce the triangle count by collapsing edges, cheapest error first. '
    'Fast and shape-preserving on dense scans, destructive on anything with '
    'a deliberate edge flow: decimate a scan, retopologise a model.',
    '<path d="M4.4 18.6L12 5.2l7.6 13.4z"/><path d="M12 5.2v13.4"/><path d="M8.2 11.9h7.6"/>',
    [
        e('mode', 'Mode', 'ratio', ('ratio', 'target triangles', 'max error')),
        f('ratio', 'Keep ratio', 0.5, 0.01, 1.0, 0.01),
        i('target', 'Target triangles', 20000, 100, 2000000, 100),
        b('preserve_border', 'Preserve open borders', True),
        b('preserve_uv', 'Preserve UV seams', True),
    ],
)

_side(
    'top_remesh_voxel',
    'Remesh (voxel)',
    'Topology',
    'Rebuild the surface by voxelising the volume and re-extracting it. '
    'Throws away every existing edge, UV and detail below the voxel size, '
    'and in exchange guarantees a single closed manifold — the reliable way '
    'to turn a self-intersecting mess into something watertight.',
    '<path d="M4.6 4.6h5v5h-5zM14.4 4.6h5v5h-5zM4.6 14.4h5v5h-5zM14.4 14.4h5v5h-5z"/>',
    [
        f('voxel', 'Voxel size (mm)', 4.0, 0.2, 50.0, 0.1),
        b('adaptive', 'Adaptive — finer where curvature is high', False),
        b('smooth_shade', 'Smooth shading after', True),
    ],
)

_side(
    'top_remesh_quad',
    'Remesh (quad)',
    'Topology',
    'Rebuild the surface as quads following the curvature field, with a '
    'target face count. Instant-meshes style: good enough edge flow for '
    'deformation without the hours a hand retopo costs, and the right '
    'default for anything that will be rigged.',
    '<path d="M4.6 6.4h14.8v11.2H4.6z"/><path d="M4.6 12h14.8"/><path d="M9.5 6.4v11.2M14.5 6.4v11.2"/>',
    [
        i('faces', 'Target quads', 8000, 200, 200000, 100),
        f('adaptivity', 'Adaptivity', 0.25, 0.0, 1.0, 0.01),
        b('symmetry', 'Enforce X symmetry', True),
        b('align_sharp', 'Align to sharp edges', True),
    ],
)

_side(
    'top_retopo',
    'Retopologise',
    'Topology',
    'Lay a new, deliberate edge flow over the existing surface — loops round '
    'the eyes and mouth, poles kept off the joints, spans that bend where a '
    'limb bends. The expensive, correct answer when the mesh has to deform, '
    'and the one op here whose output is judged by eye, not by a number.',
    '<path d="M12 4.4c4 0 7 3.4 7 7.6s-3 7.6-7 7.6-7-3.4-7-7.6 3-7.6 7-7.6z"/>'
    '<path d="M5.4 10.2c4.4 2.2 8.8 2.2 13.2 0M12 4.4v15.2"/>',
    [
        e('preset', 'Flow preset', 'humanoid', ('humanoid', 'quadruped', 'face', 'hand', 'prop', 'freeform')),
        i('faces', 'Target quads', 6000, 200, 120000, 100),
        b('keep_symmetry', 'Mirror the flow across X', True),
        b('project', 'Project back onto the original surface', True),
    ],
)

_side(
    'top_subdivide',
    'Subdivide',
    'Topology',
    'Split every face and, on Catmull-Clark, pull the result towards the '
    'limit surface. Each level multiplies the count by four, so this is a '
    'render-time decision on a cage, not a modelling habit: two levels on a '
    '20k cage is 320k triangles.',
    '<path d="M5 5h14v14H5z"/><path d="M12 5v14M5 12h14"/><path d="M8.5 5v14M15.5 5v14M5 8.5h14M5 15.5h14"/>',
    [
        i('levels', 'Levels', 1, 1, 4, 1),
        e('scheme', 'Scheme', 'catmull-clark', ('catmull-clark', 'simple', 'loop')),
        b('smooth_uv', 'Subdivide UVs smoothly', True),
        b('keep_creases', 'Respect edge creases', True),
    ],
)

_side(
    'top_triangulate',
    'Triangulate',
    'Topology',
    'Convert every quad and n-gon to triangles. What every renderer and '
    'every engine does anyway at load — doing it here makes the result '
    'visible and deterministic instead of leaving the diagonal choice to '
    'whatever opens the file.',
    '<path d="M4.6 18.8h14.8L12 5.4z"/><path d="M12 5.4v13.4M4.6 18.8L12 12"/>',
    [
        e(
            'quad_method',
            'Quad method',
            'shortest diagonal',
            ('shortest diagonal', 'beauty', 'fixed', 'fixed alternate'),
        ),
        e('ngon_method', 'N-gon method', 'beauty', ('beauty', 'clip')),
        b('keep_normals', 'Keep custom normals', True),
    ],
)

_side(
    'top_quadrangulate',
    'Quadrangulate',
    'Topology',
    'Merge adjacent triangles back into quads where the pair is close to '
    'planar and the result is not a sliver. Cosmetic for rendering, real for '
    'editing and for subdivision: a triangulated mesh cannot be subdivided '
    'cleanly.',
    '<path d="M4.8 5.6h14.4v12.8H4.8z"/><path d="M4.8 18.4L12 12l7.2 6.4"/><path d="M12 5.6V12"/>',
    [
        f('max_angle', 'Max face angle (deg)', 40.0, 0.0, 180.0, 1.0),
        b('compare_uv', 'Do not merge across UV seams', True),
        b('compare_material', 'Do not merge across materials', True),
    ],
)

_side(
    'top_lod',
    'LOD chain',
    'Topology',
    'Build the whole level-of-detail ladder in one pass — LOD0 as authored, '
    'then each rung decimated to its ratio, with UVs and skin weights '
    'carried down. Written as a set that ships together, because an LOD2 '
    'that was generated from a different LOD0 is how a model pops.',
    '<path d="M4.6 19.4h4.4v-4.4H4.6zM10.2 19.4h4.4V10h-4.4z"/><path d="M15.8 19.4h4.4V4.6h-4.4z"/>',
    [
        i('levels', 'Levels', 3, 1, 6, 1),
        f('falloff', 'Ratio per level', 0.45, 0.1, 0.9, 0.05),
        b('carry_weights', 'Carry skin weights down', True),
        b('carry_uv', 'Carry UVs down', True),
        b('screen_sizes', 'Write screen-size thresholds', True),
    ],
)

_side(
    'top_weld',
    'Weld',
    'Topology',
    'Merge vertices that sit within a distance of each other into one. The '
    'first thing to try when a mesh shades as if it were shattered: imported '
    'geometry is very often a pile of disconnected faces that only looks '
    'joined.',
    '<circle cx="8.2" cy="12" r="3.4"/><circle cx="15.8" cy="12" r="3.4"/><path d="M8.2 6.6v-2M15.8 6.6v-2"/>',
    [
        f('dist', 'Distance (mm)', 0.1, 0.0001, 10.0, 0.0001),
        b('only_selected', 'Only the selection', False),
        b('keep_seams', 'Do not weld across UV seams', True),
    ],
)

_side(
    'top_fill_holes',
    'Fill holes',
    'Topology',
    'Close boundary loops with new faces, smallest first, up to a size '
    'limit. The limit matters: an unbounded fill will happily cap the neck '
    'opening of a bust or the inside of a sleeve and call it repaired.',
    '<path d="M4.8 12a7.2 7.2 0 0114.4 0 7.2 7.2 0 01-14.4 0z"/>'
    '<path d="M9.4 12a2.6 2.6 0 015.2 0 2.6 2.6 0 01-5.2 0z"/>'
    '<path d="M12 4.8v2.6M12 16.6v2.6"/>',
    [
        i('max_edges', 'Max loop edges', 60, 3, 2000, 1),
        e('method', 'Method', 'smooth', ('flat', 'smooth', 'curvature-fit')),
        b('all', 'Fill every hole', True),
        b('report', 'List what was filled', True),
    ],
)

_side(
    'top_watertight',
    'Make watertight',
    'Topology',
    'Force a single closed manifold: fill the holes, drop the interior '
    'shells, resolve the self-intersections and flip whatever is inside out. '
    'Required before printing, before a boolean and before any volume '
    'measurement means anything.',
    '<path d="M12 3.8c3.6 3.2 5.6 6.2 5.6 9.2A5.6 5.6 0 0112 18.6 5.6 5.6 0 '
    '016.4 13c0-3 2-6 5.6-9.2z"/><path d="M9.8 13.4a2.2 2.2 0 004.4 0"/>',
    [
        b('drop_interior', 'Drop interior shells', True),
        b('resolve_self', 'Resolve self-intersections', True),
        b('orient', 'Orient all normals outward', True),
        f('tol', 'Tolerance (mm)', 0.05, 0.001, 5.0, 0.001),
    ],
)

_side(
    'top_normals_recalc',
    'Recompute normals',
    'Topology',
    'Recalculate face and vertex normals from the geometry, optionally '
    'splitting them at a shading angle. Fixes the mesh that is lit as if it '
    'were faceted, or as if the light were coming from inside it.',
    '<path d="M5.6 17.4l6.4-9.8 6.4 9.8z"/><path d="M12 7.6V3.4M12 3.4l-1.6 1.8M12 3.4l1.6 1.8"/>',
    [
        b('outward', 'Force outward', True),
        b('split_angle', 'Split at angle', True),
        f('angle', 'Shading angle (deg)', 30.0, 0.0, 180.0, 1.0),
        b('clear_custom', 'Clear custom normals', False),
    ],
)

_side(
    'top_normals_flip',
    'Flip normals',
    'Topology',
    'Invert the winding of every face, or of the selection. The blunt '
    'instrument for a surface that renders inside out — use Recompute first '
    'and this only when the mesh really is authored the wrong way round.',
    '<path d="M7.4 9.4h9.2l-2.6-2.6M16.6 14.6H7.4l2.6 2.6"/><path d="M4.4 4.4v15.2"/>',
    [b('selection_only', 'Selection only', False), b('then_recalc', 'Recompute afterwards', False)],
)

_side(
    'top_smooth',
    'Smooth',
    'Topology',
    'Relax vertex positions towards the average of their neighbours. '
    'Laplacian smoothing shrinks a mesh as it smooths it; the Taubin option '
    'alternates signs to keep the volume, which is what you want on anything '
    'measured.',
    '<path d="M4.2 15.4c2.6-6.4 5.2-6.4 7.8 0s5.2 6.4 7.8 0"/><path d="M4.2 19.2h15.6"/>',
    [
        i('iterations', 'Iterations', 4, 1, 60, 1),
        f('factor', 'Strength', 0.5, 0.0, 1.0, 0.01),
        e('method', 'Method', 'taubin', ('laplacian', 'taubin', 'hc')),
        b('pin_border', 'Pin open borders', True),
        b('pin_seams', 'Pin UV seams', True),
    ],
)

_side(
    'top_creases',
    'Sharpen creases',
    'Topology',
    'Mark edges as creased so subdivision and smooth shading keep them '
    'sharp, chosen by dihedral angle or by hand. The difference between a '
    'subdivided box and a subdivided pillow.',
    '<path d="M3.8 18.6L10 7.8l3.4 5.4 2.6-3.4 4.2 8.8z"/><path d="M10 7.8v-4"/>',
    [
        f('angle', 'Angle over (deg)', 45.0, 0.0, 180.0, 1.0),
        f('weight', 'Crease weight', 1.0, 0.0, 1.0, 0.01),
        b('mark_sharp', 'Also mark sharp for shading', True),
        b('clear_first', 'Clear existing creases', False),
    ],
)

_side(
    'top_remove_doubles',
    'Remove doubles',
    'Topology',
    'Delete the geometry that is present twice — coincident vertices, '
    'duplicate faces, zero-area slivers and loose edges left behind by an '
    'earlier boolean. Reports what it removed rather than quietly changing '
    'the count.',
    '<path d="M6.2 6.2h9v9h-9z"/><path d="M9.2 9.2h9v9h-9z"/><path d="M18.2 6.2l-2.4 2.4"/>',
    [
        f('dist', 'Coincident distance (mm)', 0.01, 0.0001, 5.0, 0.0001),
        b('faces', 'Duplicate faces', True),
        b('slivers', 'Zero-area faces', True),
        b('loose', 'Loose edges and vertices', True),
        b('report', 'Report the counts', True),
    ],
)


# ══ TRANSFORM ═══════════════════════════════════════════════════════════════
# Where the mesh sits and how big it is. Cheap to do, expensive to get wrong:
# every one of these silently invalidates a rig, a bake or a scene placement if
# it is applied after the thing that depended on it.

_side(
    'tr_scale_height',
    'Scale to height',
    'Transform',
    'Scale the mesh uniformly until its bounding box is exactly the height '
    'you name, in metres. The only honest way to make imports from five '
    'sources share a world: everything measured against the same ruler '
    'rather than against whatever unit its exporter felt like.',
    '<path d="M6.4 4.4v15.2"/><path d="M4.6 4.4h3.6M4.6 19.6h3.6"/><path d="M13 19.6V9.2l5.4 10.4z"/>',
    [
        f('height_m', 'Height (m)', 1.75, 0.01, 100.0, 0.01),
        e('axis', 'Measure along', 'Z', ('X', 'Y', 'Z', 'longest')),
        b('include_hair', 'Include hair and loose parts', False),
        b('uniform', 'Uniform on all axes', True),
    ],
)

_side(
    'tr_centre',
    'Centre',
    'Transform',
    'Move the mesh so its centre — of the bounding box, of mass, or of the '
    'selection — sits on the world origin. Bounding box and mass differ by a '
    'lot on anything asymmetric, which is exactly when it matters.',
    '<path d="M12 4.6v14.8M4.6 12h14.8"/><circle cx="12" cy="12" r="3.2"/>',
    [
        e('what', 'Centre on', 'bbox', ('bbox', 'mass', 'selection', 'origin of rig')),
        b('x', 'X', True),
        b('y', 'Y', True),
        b('z', 'Z', False),
    ],
)

_side(
    'tr_drop',
    'Drop to ground',
    'Transform',
    'Translate the mesh down (or up) until its lowest point rests on Z=0, '
    'with an optional tolerance so a stray vertex from a scan does not hang '
    'the whole model a centimetre in the air.',
    '<path d="M5.2 8.2h9.4v6.2H5.2z"/><path d="M3.4 19.4h17.2"/><path d="M18 7.6v8.2M18 15.8l-1.8-2M18 15.8l1.8-2"/>',
    [
        f('tolerance_mm', 'Ignore outliers below (mm)', 2.0, 0.0, 100.0, 0.5),
        b('use_feet', 'Use the foot bones if rigged', False),
        b('keep_xy', 'Do not move in X/Y', True),
    ],
)

_side(
    'tr_upaxis',
    'Up-axis fix (Z ↔ Y)',
    'Transform',
    'Rotate between the two conventions: Z-up (Blender, most DCC, this '
    'studio) and Y-up (glTF, engines, the web). Applied as a real rotation '
    'of the geometry, not as a flag on the export, so the mesh is unambiguous '
    'the moment it leaves here.',
    '<path d="M7 17.4V6.6M7 6.6l-2 2.2M7 6.6l2 2.2"/>'
    '<path d="M12.4 17.4h7.2M19.6 17.4l-2.2-2M19.6 17.4l-2.2 2"/>'
    '<path d="M7 17.4h3"/>',
    [
        e('to', 'Target', 'Z-up', ('Z-up', 'Y-up')),
        b('rotate_rig', 'Rotate the rig too', True),
        b('apply', 'Apply the rotation to the data', True),
    ],
)

_side(
    'tr_mirror_x',
    'Mirror X',
    'Transform',
    'Reflect the mesh across the YZ plane, optionally merging the halves '
    'into one symmetric mesh. Mirroring flips face winding, so the normals '
    'are recomputed after — a mirror that skips that step is the classic '
    'source of a left arm that renders black.',
    '<path d="M12 3.6v16.8"/><path d="M9.6 7.2L4.4 12l5.2 4.8z"/><path d="M14.4 7.2L19.6 12l-5.2 4.8z"/>',
    [
        e('mode', 'Mode', 'mirror', ('mirror', 'mirror and merge', 'copy +X to -X')),
        f('merge_dist', 'Merge distance (mm)', 0.1, 0.0, 10.0, 0.01),
        b('flip_uv', 'Flip UVs on the mirrored half', True),
        b('mirror_weights', 'Mirror skin weights', True),
    ],
)

_side(
    'tr_rotate',
    'Rotate',
    'Transform',
    'Rotate about the mesh origin by explicit degrees per axis, or snapped '
    'to 90-degree steps. Typed rather than dragged, because the fix for an '
    'import that came in on its side is exactly -90, not approximately.',
    '<path d="M18.6 12a6.6 6.6 0 11-2.4-5.1"/><path d="M18.9 4.6v3.6h-3.6"/><circle cx="12" cy="12" r="1.3"/>',
    [
        f('rx', 'X (deg)', 0.0, -360.0, 360.0, 0.5),
        f('ry', 'Y (deg)', 0.0, -360.0, 360.0, 0.5),
        f('rz', 'Z (deg)', 0.0, -360.0, 360.0, 0.5),
        b('snap90', 'Snap to 90°', False),
        e('pivot', 'Pivot', 'origin', ('origin', 'bbox centre', 'mass centre', 'cursor')),
    ],
)

_side(
    'tr_freeze',
    'Freeze transforms',
    'Transform',
    'Bake the object-level translation, rotation and scale into the vertex '
    'positions and reset the transform to identity. Everything exported '
    'afterwards carries the same numbers it shows here, which is what makes '
    'a measurement reproducible.',
    '<path d="M12 3.8v16.4M5 7.9l14 8.2M5 16.1l14-8.2"/><path d="M12 3.8l-1.8 1.9M12 3.8l1.8 1.9"/>',
    [
        b('loc', 'Location', True),
        b('rot', 'Rotation', True),
        b('scale', 'Scale', True),
        b('keep_origin', 'Keep the origin where it is', True),
    ],
)

_side(
    'tr_apply_scale',
    'Apply scale',
    'Transform',
    'Apply scale alone, leaving position and rotation as they are. Worth its '
    'own button because a non-uniform object scale is what breaks modifiers, '
    'physics radii, bevel widths and armature bone lengths — and it is '
    'invisible until one of them misbehaves.',
    '<path d="M5.4 18.6V5.4h13.2"/><path d="M8.6 18.6V8.6h10"/><path d="M5.4 5.4l3.2 3.2M15.4 5.4l3.2 3.2"/>',
    [
        b('uniform_only', 'Only if non-uniform', False),
        b('fix_bones', 'Rescale bone lengths to match', True),
        b('fix_shapekeys', 'Rescale shape keys to match', True),
    ],
)

_side(
    'tr_snap_grid',
    'Snap to grid',
    'Transform',
    'Round vertex positions to a grid step. Cleans up hand-modelled geometry '
    'that is a hundredth of a millimetre off square and makes coincident '
    'seams actually coincide — and it will happily destroy an organic '
    'surface, so the step is yours to choose.',
    '<path d="M4.6 4.6h14.8v14.8H4.6z"/>'
    '<path d="M9.5 4.6v14.8M14.5 4.6v14.8M4.6 9.5h14.8M4.6 14.5h14.8"/>'
    '<circle cx="14.5" cy="9.5" r="1.5"/>',
    [
        f('step_mm', 'Grid step (mm)', 1.0, 0.001, 100.0, 0.001),
        b('x', 'Snap X', True),
        b('y', 'Snap Y', True),
        b('z', 'Snap Z', True),
        b('selection_only', 'Selection only', False),
    ],
)

_side(
    'tr_align_ref',
    'Align to reference',
    'Transform',
    'Fit the mesh onto a reference mesh — coarse alignment from the principal '
    'axes, then iterative closest point. How a scan is put back into the same '
    'frame as the model it was scanned from, and the prerequisite for any '
    'deviation measurement being meaningful.',
    '<path d="M6.8 6.8h8.4v8.4H6.8z"/><path d="M9.6 9.6h8.4v8.4H9.6z"/><path d="M15.2 6.8l2.8 2.8M6.8 15.2l2.8 2.8"/>',
    [
        s('ref', 'Reference mesh', '', 'Library id or path'),
        e('method', 'Method', 'icp', ('icp', 'principal axes', 'three points', 'bbox')),
        i('iterations', 'ICP iterations', 50, 5, 500, 5),
        b('allow_scale', 'Allow uniform scale', False),
        b('report_rmse', 'Report the RMS error', True),
    ],
)
