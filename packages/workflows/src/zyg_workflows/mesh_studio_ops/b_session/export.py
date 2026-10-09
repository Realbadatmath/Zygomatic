# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — EXPORT — getting the mesh out, in the format the receiver reads.

Section ``EXPORT`` of the single-file ``b_session.py``, moved verbatim
(original lines 665-884); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _dock, b, e, i

# ══ EXPORT ══════════════════════════════════════════════════════════════════
# Getting the mesh out, in the format the receiver actually reads. Everything
# from here down is bar 'dock' — the session half. Each exporter states what it
# can and cannot carry, because a format that silently drops the rig is how a
# character arrives at the next studio as a statue.

_dock(
    'ex_glb',
    'GLB',
    'Export',
    'Write a single .glb: mesh, materials, UVs, textures, skeleton and skin '
    'weights in one binary file. The format to hand anything that has to '
    "load it over HTTP — the page's own viewer included — and the only one "
    'here that carries a rig without a per-application convention argument.',
    '<path d="M12 3.6l7.6 4.3v8.2L12 20.4 4.4 16.1V7.9z"/>'
    '<path d="M4.4 7.9L12 12.2l7.6-4.3M12 12.2v8.2"/><path d="M8.2 5.8l7.6 4.3"/>',
    [
        b('embed_textures', 'Embed the textures', True),
        b('draco', 'Draco-compress the geometry', False),
        b('rig', 'Include skeleton and weights', True),
        e('units', 'Units', 'metres', ('metres', 'centimetres')),
    ],
)

_dock(
    'ex_gltf',
    'glTF + bin',
    'Export',
    'Write .gltf as JSON with a .bin beside it and the textures loose. '
    'Bigger and more fragile to move than a .glb, and worth it exactly once: '
    'when you need to read or patch the scene graph by hand, because a .gltf '
    'is a text file and a .glb is not.',
    '<path d="M6.2 4.4h7l4.6 4.6v10.6H6.2z"/><path d="M13.2 4.4V9h4.6"/>'
    '<path d="M9 13.4l-1.8 1.8L9 17M15 13.4l1.8 1.8L15 17"/>',
    [
        b('pretty', 'Indent the JSON', True),
        b('separate_bin', 'Geometry to a separate .bin', True),
        b('rig', 'Include skeleton and weights', True),
    ],
)

_dock(
    'ex_obj',
    'OBJ',
    'Export',
    'Write a Wavefront .obj with its .mtl. Geometry, UVs and material names, '
    'nothing else — no rig, no animation, no units. Universal, ancient and '
    'honest about being a container for triangles; the up-axis is written '
    'explicitly rather than assumed.',
    '<path d="M4.6 6.4h14.8v11.2H4.6z"/><path d="M4.6 10.2h14.8M4.6 13.8h14.8"/><path d="M12 6.4v11.2"/>',
    [
        e('up', 'Up axis', 'Y', ('Y', 'Z')),
        b('mtl', 'Write the .mtl', True),
        b('triangulate', 'Triangulate', True),
        b('groups', 'Keep object groups', True),
    ],
)

_dock(
    'ex_fbx',
    'FBX',
    'Export',
    'Write .fbx — what most commercial DCCs and engines take a rigged mesh '
    'in. Carries the skeleton, the weights and the bind pose; carries them '
    'in units and axes that differ per application, which is why both are '
    'set here and written into the file rather than left to the importer.',
    '<path d="M5 5.6h14v12.8H5z"/><path d="M8.2 9h4.4M8.2 12h3.4M8.2 15h4.4"/>'
    '<path d="M15.4 9v6"/><circle cx="15.4" cy="16.6" r="1"/>',
    [
        e('units', 'Units', 'centimetres', ('metres', 'centimetres', 'inches')),
        e('up', 'Up axis', 'Y', ('Y', 'Z')),
        b('ascii', 'ASCII instead of binary', False),
        b('rig', 'Include skeleton and bind pose', True),
    ],
)

_dock(
    'ex_stl',
    'STL',
    'Export',
    'Write .stl: a bag of triangles with face normals and nothing else — no '
    'UVs, no colour, no rig. The format for 3D printing and for handing '
    'geometry to a mesh tool that has no opinion about materials. Refuses on '
    'a non-watertight mesh unless you say otherwise, because a printer will '
    'not.',
    '<path d="M12 4.2l6.8 3.9v7.8L12 19.8l-6.8-3.9V8.1z"/><path d="M12 4.2v7.8l6.8 3.9M12 12L5.2 15.9"/>',
    [
        b('binary', 'Binary STL', True),
        b('require_watertight', 'Refuse if not watertight', True),
        e('units', 'Units', 'millimetres', ('millimetres', 'centimetres', 'metres')),
    ],
)

_dock(
    'ex_usd',
    'USD',
    'Export',
    'Write .usd / .usdz — the format that composes: a mesh exported here can '
    'be layered over, referenced and overridden by a scene without being '
    'copied into it. The one to prefer when the mesh is a component of '
    'something assembled elsewhere rather than a delivery in itself.',
    '<path d="M4.8 8.4h14.4v8.8H4.8z"/><path d="M4.8 8.4l3.4-3h14.4v8.8l-3.4 3"/><path d="M19.2 8.4l3.4-3"/>',
    [
        e('flavour', 'Flavour', 'usdc', ('usda', 'usdc', 'usdz')),
        b('materials', 'Write UsdPreviewSurface materials', True),
        b('rig', 'Include the skeleton (UsdSkel)', True),
    ],
)

_dock(
    'ex_mesh3d',
    'mesh3d.bin (ZM3D)',
    'Export',
    "Write the page's own ZM3D mesh3d.bin — the packed float32 buffer the "
    'inspection viewer memory-maps and uploads straight to a three.js '
    'BufferGeometry with no parse step. The fastest thing the GUI can open, '
    'and the reason a 2-million-triangle mesh can be scrubbed in a browser '
    'tab at all.',
    '<path d="M4.4 6.8h15.2v10.4H4.4z"/><path d="M7.6 9.8h2.2v4.4H7.6z"/>'
    '<path d="M11.4 9.8h2.2v4.4h-2.2zM15.2 9.8h2.2v4.4h-2.2z"/>'
    '<path d="M4.4 12h3.2M17.4 12h2.2"/>',
    [
        b('normals', 'Include normals', True),
        b('uvs', 'Include UVs', True),
        b('colours', 'Include vertex colours', False),
        e('precision', 'Position precision', 'float32', ('float32', 'float16')),
    ],
)

_dock(
    'ex_plates48',
    '48-angle plate set',
    'Export',
    'Render and write the 48-camera plate set — depth, normal and lineart '
    'per angle — as the hand-off to every 2D leg in the house. These plates '
    'are what conditions a diffusion pass, what a sheet is assembled from '
    'and what fit_plates later measures against, so the camera ring is the '
    'same ring everywhere or none of it lines up.',
    '<path d="M12 12l6.6-6.6M12 12l6.6 6.6M12 12L5.4 5.4M12 12l-6.6 6.6"/>'
    '<circle cx="12" cy="12" r="2.4"/><circle cx="12" cy="12" r="8.6"/>',
    [
        i('angles', 'Angles', 48, 4, 96, 1),
        e('size', 'Plate size', '1024', ('512', '1024', '2048')),
        b('depth', 'Depth pass', True),
        b('normal', 'Normal pass', True),
        b('lineart', 'Lineart pass', True),
    ],
    needs='gpu',
)

_dock(
    'ex_turntable',
    'Turntable mp4',
    'Export',
    'Write the turntable as an mp4 — one revolution, fixed camera height, '
    'constant speed — for review threads and for the board. A still hides a '
    'dent that a rotation shows in a quarter turn, which is why the mesh '
    'record keeps a turntable and not only a thumbnail.',
    '<path d="M5.4 7.4h13.2v9.2H5.4z"/><path d="M10.6 10.2l4.4 2.2-4.4 2.2z"/>'
    '<path d="M4.2 19.6c3.4 1.4 12.2 1.4 15.6 0"/>',
    [
        i('seconds', 'Length (s)', 6, 2, 30, 1),
        i('fps', 'Frames per second', 25, 12, 60, 1),
        e('size', 'Size', '1080p', ('540p', '720p', '1080p')),
        b('reuse_render', 'Reuse the last turntable render if it is current', True),
    ],
    needs='gpu',
)

_dock(
    'ex_thumbsheet',
    'Thumbnail sheet',
    'Export',
    'One PNG with the mesh from a handful of canonical angles, the name, the '
    'triangle count and the date burnt into the corner. What the library '
    'grid draws, what a review post attaches and what makes two versions of '
    'the same asset distinguishable at 200 pixels wide.',
    '<path d="M4.6 5.4h6v6h-6zM13.4 5.4h6v6h-6z"/>'
    '<path d="M4.6 13.6h6v5h-6zM13.4 13.6h6v5h-6z"/>'
    '<path d="M15 16.2h3M15 17.4h2"/>',
    [
        i('tiles', 'Angles', 6, 2, 16, 1),
        e('layout', 'Layout', 'grid', ('grid', 'row', 'contact sheet')),
        b('stamp', 'Burn in name, tris and date', True),
        b('transparent', 'Transparent background', False),
    ],
)

_dock(
    'ex_copy_path',
    'Copy path',
    'Export',
    'Put the absolute path of the mesh — or of its last export — on the '
    'clipboard. Small, and the op that gets used more than any other in this '
    'section, because the next thing that needs it is usually a terminal or '
    'a brief rather than another panel.',
    '<path d="M8.4 7.6h9.2v11.8H8.4z"/><path d="M15.6 7.6V4.6H6.4v11.8h2"/>',
    [
        e('what', 'Which path', 'mesh', ('mesh', 'last export', 'folder', 'thumbnail')),
        b('quote', 'Quote it for a shell', False),
    ],
    needs='',
)

_dock(
    'ex_open_folder',
    'Open folder',
    'Export',
    'Open the folder the mesh and its exports live in, in the system file '
    'manager on the machine running the GUI. The escape hatch for everything '
    'the studio does not do: rename, zip, drag into another application.',
    '<path d="M3.8 6.6h6.2l1.8 2.2h8.4v9.6H3.8z"/><path d="M13.6 13.4h5.2M16.8 11.2l2.2 2.2-2.2 2.2"/>',
    [
        e('what', 'Which folder', 'mesh', ('mesh', 'exports', 'renders', 'textures')),
        b('select_file', 'Select the file inside it', True),
    ],
    needs='',
)
