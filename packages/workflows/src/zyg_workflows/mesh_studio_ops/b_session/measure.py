# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — MEASURE — numbers about the mesh, not changes to it.

Section ``MEASURE`` of the single-file ``b_session.py``, moved verbatim
(original lines 241-469); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _side, b, e, f, i

# ══ MEASURE ═════════════════════════════════════════════════════════════════
# Numbers about the mesh, not changes to it. Everything here is cls='pix': it
# reads, it reports, it never edits. The gates (anthropometric, identity,
# symmetry) are the ones the rest of the house already runs — declared here so
# a mesh can be held to them before it is handed on, not after.

_side(
    'ms_dimensions',
    'Dimensions',
    'Measure',
    'The bounding box in metres, its centre, and where the mesh sits '
    'relative to the origin and the ground plane. Scale is the single most '
    'common defect in an imported mesh and the one the viewport hides: a '
    'model that fills the frame looks right at 1.8 m and at 180 m.',
    '<path d="M4.6 17.8h14.8"/><path d="M4.6 15.8v4M19.4 15.8v4"/>'
    '<path d="M6.4 13.2V5.4h11.2v7.8z"/><path d="M6.4 9.2h11.2"/>',
    [
        e('units', 'Units', 'metres', ('metres', 'centimetres', 'inches')),
        b('world', 'Measure in world space, not local', True),
        b('show_box', 'Draw the box in the viewport', True),
    ],
    cls='pix',
)

_side(
    'ms_counts',
    'Triangle and vertex count',
    'Measure',
    'Triangles, vertices, edges, loose vertices, n-gons and the count per '
    "material slot, against the budget for the mesh's kind. A prop, a hero "
    'character and a background body have different budgets, and a mesh is '
    'over budget for a reason (a decimate that stopped early, an n-gon fan) '
    'that the breakdown names.',
    '<path d="M12 4.6l7 12.2H5z"/><path d="M12 10.4l3.4 6.4H8.6z"/>'
    '<circle cx="12" cy="4.6" r="1.1"/><circle cx="5" cy="16.8" r="1.1"/>'
    '<circle cx="19" cy="16.8" r="1.1"/>',
    [
        e('budget', 'Budget for', 'auto', ('auto', 'prop', 'hero', 'background', 'lod')),
        b('per_slot', 'Break down per material slot', True),
        b('warn_ngons', 'Flag n-gons', True),
    ],
    cls='pix',
)

_side(
    'ms_watertight',
    'Watertight check',
    'Measure',
    'Whether the mesh is a closed manifold: no boundary edges, no edge used '
    'by more than two faces, no inconsistent winding. Everything downstream '
    'that treats the mesh as a solid — volume, 3D print, shrinkwrap, boolean '
    'and most physics — is undefined on an open one, so this runs first.',
    '<path d="M12 3.8l6.6 3.6v7.2L12 20.2 5.4 14.6V7.4z"/><path d="M9 11.8l2.2 2.4 4-4.6"/>',
    [
        b('highlight', 'Highlight the holes in the viewport', True),
        b('count_boundary', 'Count boundary loops', True),
        i('max_report', 'Report at most', 50, 1, 500, 1),
    ],
    cls='pix',
)

_side(
    'ms_self_intersect',
    'Self-intersection',
    'Measure',
    'Faces that pass through other faces of the same mesh. Invisible from '
    'outside until something depends on the interior — a bake picks up the '
    'inner surface, a decimate welds across the crossing, a cloth sim '
    'explodes — and the usual cause is a shrinkwrap or a morph pushed past '
    'the geometry it was fitting to.',
    '<path d="M5 6.4l14 11.2M19 6.4L5 17.6"/><circle cx="12" cy="12" r="2.6"/>',
    [
        b('highlight', 'Select the intersecting faces', True),
        f('tolerance', 'Tolerance (mm)', 0.1, 0.0, 5.0, 0.01),
        b('include_touching', 'Count faces that merely touch', False),
    ],
    cls='pix',
)

_side(
    'ms_thin_parts',
    'Thin parts',
    'Measure',
    'Where the mesh is thinner than a threshold, measured by casting rays '
    'inward and taking the distance to the far wall. Thin parts are what '
    'break a 3D print, what disappear at the first LOD, and what a voxel '
    'remesh silently removes — knowing where they are decides whether the '
    'remesh resolution is high enough before it is run.',
    '<path d="M6.2 5.4c4 1.6 7.6 1.6 11.6 0v13.2c-4-1.6-7.6-1.6-11.6 0z"/>'
    '<path d="M8.4 12h7.2"/><path d="M8.4 10.6v2.8M15.6 10.6v2.8"/>',
    [
        f('threshold', 'Thinner than (mm)', 2.0, 0.1, 50.0, 0.1),
        i('rays', 'Rays per face', 8, 1, 64, 1),
        b('highlight', 'Paint the thin regions', True),
    ],
    cls='pix',
)

_side(
    'ms_gnm_head',
    'GNM head fit',
    'Measure',
    "Fit the GNM head model to the mesh's skull and report the residual — "
    'how far this head is from the parametric family, per landmark. A large '
    'residual at the jaw and a small one everywhere else is a sculpt; a '
    'large one everywhere is usually a scale or an orientation error rather '
    'than a face that is genuinely unusual.',
    '<path d="M8.6 20v-2.6c-2-1.2-3.2-3.4-3.2-6a6.6 6.6 0 0113.2 0c0 2-.8 3-2 3.6"/>'
    '<path d="M16.6 15v3.2h-2.2"/><circle cx="9.6" cy="10.6" r=".9"/>'
    '<circle cx="14" cy="10.6" r=".9"/>',
    [
        f('max_residual', 'Flag above (mm)', 4.0, 0.5, 30.0, 0.1),
        b('per_landmark', 'Report every landmark', True),
        b('draw_fit', 'Draw the fitted head over the mesh', True),
    ],
    cls='pix',
)

_side(
    'ms_anthro_gate',
    'Anthropometric gate',
    'Measure',
    'Run geom.anthro over the mesh: the proportion ratios a human body has '
    'to satisfy — head-to-height, shoulder width, limb segments, hand and '
    'foot length — each against its band. This is the gate that catches a '
    'morph which made a character taller by stretching the skull, and it '
    'answers with the failing ratio rather than with a verdict.',
    '<circle cx="12" cy="5.4" r="2.2"/><path d="M12 7.6v7.2"/>'
    '<path d="M7.4 10.4h9.2"/><path d="M12 14.8l-3 5.4M12 14.8l3 5.4"/>'
    '<path d="M3.6 4.6v14.8"/>',
    [
        e('band', 'Band', 'adult', ('adult', 'teen', 'child', 'toddler', 'stylised')),
        f('tolerance', 'Widen every band by', 0.0, 0.0, 0.5, 0.01),
        b('stop_on_fail', 'Refuse to hand the mesh on if it fails', True),
    ],
    cls='pix',
)

_side(
    'ms_identity_dino',
    'Identity vs anchor',
    'Measure',
    "Render the mesh from the anchor's camera set and score DINOv2 "
    "similarity against the character's anchor images. The number answers "
    'one question only — is this still the same person after the edit — and '
    'it is the number that decides whether a retopo or a morph may be '
    'promoted over the mesh it came from.',
    '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.4"/>'
    '<path d="M12 4v2.4M12 17.6V20M4 12h2.4M17.6 12H20"/>',
    [
        e('anchor', 'Anchor set', 'character', ('character', 'creature', 'custom')),
        i('views', 'Views to score', 8, 1, 48, 1),
        f('pass_at', 'Pass at', 0.82, 0.3, 0.99, 0.01),
    ],
    cls='pix',
    needs='gpu',
)

_side(
    'ms_symmetry',
    'Symmetry score',
    'Measure',
    'How symmetric the mesh is about a plane, as a distance distribution '
    'rather than a yes or no: the median mirror error, the worst region and '
    'where it is. Almost every asymmetry that matters is local — one ear, '
    'one hand, a scan with a droop — and a single score hides exactly that.',
    '<path d="M12 3.6v16.8"/><path d="M10 6.4L4.6 12 10 17.6z"/><path d="M14 6.4L19.4 12 14 17.6z"/>',
    [
        e('axis', 'Plane', 'X', ('X', 'Y', 'Z')),
        f('tolerance', 'Count as symmetric within (mm)', 1.0, 0.01, 20.0, 0.01),
        b('heatmap', 'Paint the error as a heat map', True),
    ],
    cls='pix',
)

_side(
    'ms_volume',
    'Volume',
    'Measure',
    'Enclosed volume in litres, plus mass for a chosen density. Only '
    'meaningful on a watertight mesh, which is why this refuses to answer '
    'on an open one instead of returning the signed sum and letting a '
    'negative volume pass for a number.',
    '<path d="M4.8 7.6l7.2-3.8 7.2 3.8v8.8L12 20.2l-7.2-3.8z"/>'
    '<path d="M4.8 7.6L12 11.4l7.2-3.8M12 11.4v8.8"/>'
    '<path d="M8 13.6c2.6 1.4 5.4 1.4 8 0"/>',
    [
        e('density', 'Density', 'water', ('water', 'flesh', 'wood', 'steel', 'custom')),
        f('custom_density', 'Custom (kg/m³)', 1000.0, 1.0, 22000.0, 1.0),
        b('per_shell', 'Report each shell separately', True),
    ],
    cls='pix',
)

_side(
    'ms_area',
    'Surface area',
    'Measure',
    'Total surface area, the area per material slot, and texel density — '
    'how many texels of the atlas fall on a centimetre of surface. Texel '
    'density is the number that decides whether a 2K atlas is generous or '
    'embarrassing on this particular mesh, and it is never uniform.',
    '<path d="M4.6 16.4l5-8.2 3.4 5 2.4-3.4 4 6.6z"/><path d="M4.6 19.4h14.8"/><path d="M7.4 13.8h6.2"/>',
    [
        e('units', 'Units', 'm²', ('m²', 'cm²')),
        b('per_slot', 'Per material slot', True),
        b('texel_density', 'Include texel density', True),
    ],
    cls='pix',
)

_side(
    'ms_report',
    'Measure report',
    'Measure',
    'Run every measurement in this section and write one report — numbers, '
    'verdicts, the gates that passed and the gates that did not — beside the '
    'mesh. The report is what travels with the mesh to the next studio; a '
    'measurement that only ever existed in a panel cannot be cited later.',
    '<path d="M6.4 3.8h8.2l4 4v12.4H6.4z"/><path d="M14.6 3.8v4h4"/><path d="M9 12.4h6M9 15.6h6M9 9.2h3"/>',
    [
        e('format', 'Format', 'json', ('json', 'markdown', 'both')),
        b('include_gates', 'Include the gate verdicts', True),
        b('attach', 'Attach it to the mesh record', True),
    ],
    cls='act',
)
