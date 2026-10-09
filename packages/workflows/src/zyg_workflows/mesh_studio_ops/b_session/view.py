# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — VIEW — what the viewport shows, live and free.

Section ``VIEW`` of the single-file ``b_session.py``, moved verbatim
(original lines 1307-1540); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _dock, b, c, e, f, i

# ══ VIEW ════════════════════════════════════════════════════════════════════
# What the viewport shows, live and free. Nothing here writes a file or changes
# the mesh — every one of them is cls='pix', most are tog=True toggles, and the
# state they hold is the session's, not the asset's. The look-alikes in Render
# are the same pictures made off-screen at a size worth keeping.

_dock(
    'v_2d',
    '2D renders',
    'View',
    'Put the viewport into the sheet: the rendered plates, cells and '
    'reference images for this mesh, laid out as pictures rather than as '
    'geometry. The half of the studio where you look at what the mesh '
    'produced instead of at the mesh.',
    '<path d="M3.8 5.4h7v6.2h-7zM13.2 5.4h7v6.2h-7z"/>'
    '<path d="M3.8 13.8h7V20h-7zM13.2 13.8h7V20h-7z"/>'
    '<path d="M5.4 10.2l1.8-2 1.8 2"/>',
    [
        e('set', 'Show', 'all', ('all', 'plates', 'sheet cells', 'references', 'renders')),
        i('columns', 'Columns', 6, 1, 12, 1),
        b('labels', 'Label each picture', True),
    ],
    cls='pix',
    needs='',
)

_dock(
    'v_3d',
    '3D',
    'View',
    'Put the viewport back on the mesh itself — the three.js scene with the '
    'orbit camera. The other half of the same switch as 2D renders, and the '
    'default the studio opens in.',
    '<path d="M12 3.4l7.8 4.4v8.4L12 20.6l-7.8-4.4V7.8z"/>'
    '<path d="M12 12l7.8-4.2M12 12v8.6M12 12L4.2 7.8"/>'
    '<circle cx="12" cy="12" r="1.3"/>',
    [
        b('restore_camera', 'Restore the camera you left', True),
        e('shading', 'Shading', 'matcap', ('matcap', 'flat', 'shaded', 'clay')),
    ],
    cls='pix',
    needs='',
)

_dock(
    'v_wire',
    'Wireframe',
    'View',
    'Draw the edges over the shaded surface in the viewport. On a dense mesh '
    'this costs frame rate and tells you more than any other toggle: edge '
    'flow, poles, n-gons and the density gradient are all invisible on a '
    'smooth-shaded surface.',
    '<path d="M4.6 15.4l4-9.2 7.4 2.2 3.4 9.4z"/><path d="M8.6 6.2l3.4 5.6 7.4-3.4M12 11.8l-7.4 3.6M12 11.8l7.4 6"/>',
    [
        f('opacity', 'Wire opacity', 0.55, 0.0, 1.0, 0.01),
        c('colour', 'Wire colour', '#8fe3d4'),
        b('only_selection', 'Only on the selection', False),
    ],
    cls='pix',
    tog=True,
)

_dock(
    'v_normals',
    'Normals',
    'View',
    'Draw the vertex or face normals as short lines, and colour back-facing '
    'polygons. An inverted normal is invisible under most shading and is the '
    'reason a bake comes out black in patches; this is where it is seen '
    'rather than deduced.',
    '<path d="M4.6 16.8h14.8"/><path d="M7.4 16.8v-5M12 16.8v-5M16.6 16.8v-5"/>'
    '<path d="M6.2 12.8l1.2-1.4 1.2 1.4M10.8 12.8l1.2-1.4 1.2 1.4"/>'
    '<path d="M15.4 12.8l1.2-1.4 1.2 1.4"/>',
    [
        e('what', 'Show', 'face', ('face', 'vertex', 'both')),
        f('length', 'Length (mm)', 8.0, 0.5, 100.0, 0.5),
        b('flag_backface', 'Colour back faces red', True),
    ],
    cls='pix',
    tog=True,
)

_dock(
    'v_xray',
    'X-ray',
    'View',
    'Make the surface translucent so what is inside it can be seen and '
    'selected — the skeleton, an interior shell, the second copy of a mesh '
    'somebody welded in. Selection passes through in this mode, which is '
    'what makes it a tool rather than an effect.',
    '<path d="M12 4.4a6 6 0 016 6v9.2H6V10.4a6 6 0 016-6z"/><path d="M8.6 12.4h6.8M8.6 15.2h6.8M12 9.8v9.8"/>',
    [
        f('opacity', 'Surface opacity', 0.3, 0.05, 1.0, 0.01),
        b('select_through', 'Select through the surface', True),
        b('show_skeleton', 'Show the skeleton', True),
    ],
    cls='pix',
    tog=True,
)

_dock(
    'v_ground',
    'Ground plane',
    'View',
    'Show a ground plane at Y=0 with a contact shadow. The single most '
    'useful reference in the viewport: it says whether the mesh is standing '
    'on the floor, floating above it or buried in it, which no amount of '
    'orbiting a mesh in a void will tell you.',
    '<path d="M2.8 17.2l9.2-4.4 9.2 4.4-9.2 4.4z"/><path d="M12 12.8V4.4M9.4 7l2.6-2.6L14.6 7"/>',
    [
        b('shadow', 'Contact shadow', True),
        f('size', 'Size (m)', 4.0, 0.2, 100.0, 0.1),
        c('colour', 'Plane colour', '#1a1e22'),
        b('reflect', 'Slight reflection', False),
    ],
    cls='pix',
    tog=True,
)

_dock(
    'v_grid',
    'Grid',
    'View',
    'A measured grid on the ground plane, one square per unit, with a bolder '
    'line every ten. Scale in the viewport is otherwise guesswork — the grid '
    'is what makes "this hand is too big" a measurement instead of an '
    'impression.',
    '<path d="M4.4 4.4h15.2v15.2H4.4z"/><path d="M9.5 4.4v15.2M14.5 4.4v15.2M4.4 9.5h15.2M4.4 14.5h15.2"/>',
    [
        f('spacing', 'Square (m)', 0.1, 0.001, 10.0, 0.001),
        i('major', 'Bolder line every', 10, 2, 100, 1),
        b('adaptive', 'Fade the grid with the camera distance', True),
    ],
    cls='pix',
    tog=True,
)

_dock(
    'v_axes',
    'Axes',
    'View',
    'Draw the world axes at the origin and a gizmo in the corner, X red, Y '
    'green, Z blue. Which way is up and which way the mesh faces are the two '
    'facts every import argues about, and this is where the argument is '
    'settled before an export repeats it.',
    '<path d="M12 12V4.6M12 12h7.4M12 12L5.2 17.4"/>'
    '<path d="M10.6 6l1.4-1.4L13.4 6M17.6 10.6l1.8 1.4-1.8 1.4"/>'
    '<circle cx="12" cy="12" r="1.2"/>',
    [
        f('size', 'Length (m)', 0.5, 0.01, 10.0, 0.01),
        b('gizmo', 'Corner gizmo', True),
        b('labels', 'Label X, Y and Z', True),
    ],
    cls='pix',
    tog=True,
)

_dock(
    'v_bg',
    'Background',
    'View',
    'Cycle the viewport background: dark, mid grey, light, gradient, '
    'checker. A silhouette that reads on dark can disappear on light, and a '
    'transparent-looking hole in the mesh is only visible against one of '
    'them, so this is a cycle rather than a preference.',
    '<circle cx="12" cy="12" r="7.8"/><path d="M12 4.2a7.8 7.8 0 000 15.6z"/><path d="M12 8.4v7.2"/>',
    [
        e('preset', 'Background', 'dark', ('dark', 'mid grey', 'light', 'gradient', 'checker')),
        c('colour', 'Custom colour', '#15181b'),
        b('cycle_on_click', 'Click cycles to the next one', True),
    ],
    cls='pix',
    needs='',
)

_dock(
    'v_pin_source',
    'Pin source',
    'View',
    'Pin a reference — a photograph, a plate, a sheet cell or another mesh — '
    'into the viewport and hold it there while you orbit: as a backdrop, as '
    'an overlay at reduced opacity, or side by side. The pin is what keeps a '
    'judgement honest across a hundred small edits.',
    '<path d="M14.4 3.8l5.8 5.8-2.2 2.2-1.6-.6-4.6 4.6.8 2.4-1.8 1.8-6.4-6.4 '
    '1.8-1.8 2.4.8 4.6-4.6-.6-1.6z"/><path d="M8.2 15.8l-3.6 4.4"/>',
    [
        e('kind', 'Source', 'image', ('image', 'plate', 'sheet cell', 'mesh')),
        e('how', 'Show as', 'overlay', ('backdrop', 'overlay', 'side by side')),
        f('opacity', 'Opacity', 0.45, 0.0, 1.0, 0.01),
        b('lock_camera', 'Lock the camera to the source', False),
    ],
    cls='pix',
    needs='',
)

_dock(
    'v_compare',
    'Compare A/B',
    'View',
    'Put two meshes — usually this one and its parent — in the same viewport '
    'and flip, wipe or overlay between them from one camera. Comparing '
    'before and after from two different angles is how a regression gets '
    'approved, so both sides share a camera here and cannot be moved apart.',
    '<path d="M4.4 5.6h15.2v12.8H4.4z"/><path d="M12 5.6v12.8"/>'
    '<path d="M6.8 12h3M14.2 12h3"/><path d="M9 9.6l1.8 2.4L9 14.4"/>'
    '<path d="M15 9.6l-1.8 2.4 1.8 2.4"/>',
    [
        e('mode', 'Mode', 'wipe', ('wipe', 'flip', 'overlay', 'side by side')),
        e('other', 'Against', 'parent', ('parent', 'last snapshot', 'pick a mesh')),
        f('position', 'Wipe position', 0.5, 0.0, 1.0, 0.01),
        b('difference', 'Tint the difference', False),
    ],
    cls='pix',
)

_dock(
    'v_reset_cam',
    'Reset camera',
    'View',
    'Frame the mesh from the default three-quarter view at a distance that '
    'fits its bounding box, with the pivot back on its centre. The way out '
    'of an orbit that has wandered inside the mesh or a pivot that is a '
    'kilometre away because of one stray vertex.',
    '<path d="M12 6.4a5.6 5.6 0 11-5.4 7.2"/><path d="M6.2 9.4l.4 4.2 4.2-.8"/>'
    '<path d="M4.4 19.6h15.2"/><circle cx="12" cy="12" r="1.2"/>',
    [
        b('fit', 'Fit the bounding box', True),
        e('view', 'To view', 'three-quarter', ('three-quarter', 'front', 'profile', 'top')),
        b('recentre_pivot', 'Put the pivot back on the centre', True),
    ],
    cls='pix',
)
