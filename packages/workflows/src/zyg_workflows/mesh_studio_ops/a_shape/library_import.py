# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  # the original top import block is kept verbatim here; its
# names are re-exported from __init__ so a_shape.c and friends still resolve.
#
# Moved verbatim from mesh_studio_ops/a_shape.py lines 5-358 (2026-10 split):
# the module docstring below, the import block, `_side`, and the Library and
# Import sections. This module is first in the package's import order, so its
# ops are first in mesh_studio.OPS -- which is the order the rail draws.

"""Mesh Studio ops, part A — what the mesh IS.

Sections: Library, Import, Topology, Transform, Shape, Rig, Weights, UV,
Material. All on bar 'side' (the left rail). Part B (b_session.py, task 5)
adds Texture..Session.

EVERY op here is ph=True: declared, described, iconned and knobbed, but not
implemented. The tooltip says what it WILL do when it is built, in the present
tense of the finished thing, because that is the contract the build is held to
-- not a promise that it works today. The page draws these dashed.
"""

from zyg_workflows.mesh_studio import _op, f, i, b, e, c, s


def _side(id_, lb, sec, tip, svg, params=(), cls='edit', needs='mesh'):
    return _op(id_, lb, sec, 'side', tip, svg, params, cls=cls, needs=needs, ph=True)


# ══ LIBRARY ═════════════════════════════════════════════════════════════════
# Where a mesh comes from before anything is done to it. Nothing here needs a
# mesh loaded -- these are the ops that load one.

_side(
    'lib_open_original',
    'Open original',
    'Library',
    'Open an original mesh — one built here from scratch or scanned in, the '
    'authoritative copy nothing has been derived from. Opening an original '
    'is read-only until you fork it: the first edit writes a derived mesh '
    'and leaves the original on disk untouched.',
    '<path d="M4 7.2h6l1.8 2.2H20v9.4H4z"/><path d="M4 7.2V5.2h5.2"/><circle cx="12" cy="14" r="2.1"/>',
    [
        e('kind', 'Kind', 'any', ('any', 'character', 'creature', 'prop', 'scan')),
        b('readonly', 'Open read-only', True, 'Fork on first edit'),
    ],
    cls='act',
    needs='',
)

_side(
    'lib_open_derived',
    'Open derived',
    'Library',
    'Open a derived mesh — a decimated, retopologised, rigged or morphed '
    'child of an original. The lineage panel shows which original it came '
    'from and every op that was applied on the way, so a derived mesh can '
    'always be rebuilt rather than merely copied.',
    '<path d="M6.6 5.4v4.2m0 0a3 3 0 003 3h7.8m-7.8-3a3 3 0 01-3 3v3.6"/>'
    '<circle cx="5" cy="4.4" r="1.9"/><circle cx="19" cy="12.6" r="1.9"/>'
    '<circle cx="5" cy="19.6" r="1.9"/>',
    [
        e('sort', 'Sort by', 'recent', ('recent', 'name', 'lineage', 'tris')),
        b('same_origin', 'Only children of the open mesh', False),
    ],
    cls='act',
    needs='',
)

_side(
    'lib_open_prop',
    'Open prop',
    'Library',
    'Open a prop from the prop-mesh library — the procedurally built objects '
    '(pufferball, hurlbat and the rest) that carry their own build script. A '
    'prop opened here keeps the link to its generator, so its parameters can '
    'be re-run instead of its geometry re-cut.',
    '<path d="M12 3.6l7.4 4.2v8.4L12 20.4 4.6 16.2V7.8z"/><path d="M4.6 7.8L12 12l7.4-4.2M12 12v8.4"/>',
    [
        e('family', 'Family', 'all', ('all', 'pufferball', 'hurlbat', 'tree', 'misc')),
        b('with_params', 'Load generator parameters', True),
    ],
    cls='act',
    needs='',
)

_side(
    'lib_open_pack',
    'Open pack asset',
    'Library',
    'Open an asset from an ingested third-party pack — Kenney, Quaternius, '
    'Poly Haven, Smithsonian 3D or the Blender human bases. The licence of '
    'the pack rides with the mesh and is shown before it opens: a CC0 pack '
    'and a non-commercial scan are not interchangeable, and the studio will '
    'not let you find that out at delivery.',
    '<path d="M4.4 8.6h15.2v10.8H4.4z"/><path d="M4.4 8.6L7 4.8h10l2.6 3.8"/><path d="M12 4.8v3.8M9.6 12.6h4.8"/>',
    [
        e('pack', 'Pack', 'kenney', ('kenney', 'quaternius', 'polyhaven', 'smithsonian', 'blender_human_base')),
        s('q', 'Filter', '', 'Substring of the asset name'),
        b('cc0_only', 'CC0 / commercial-safe only', True),
    ],
    cls='act',
    needs='',
)

_side(
    'lib_open_character',
    'Open character body',
    'Library',
    'Open the body mesh of a character from the character bible — the MPFB '
    'base with its identity macros already applied. This is the door between '
    'Character Studio and Mesh Studio: the body arrives with its proportion '
    'lock, and an edit that breaks the lock is flagged rather than silently '
    'shipped as the same character.',
    '<circle cx="12" cy="6.4" r="2.9"/>'
    '<path d="M6.4 20.4v-3.2a5.6 5.6 0 0111.2 0v3.2"/>'
    '<path d="M9.4 20.4v-3M14.6 20.4v-3"/>',
    [e('slot', 'Body slot', 'base', ('base', 'fitted', 'proxy', 'lod')), b('with_rig', 'Include rig if present', True)],
    cls='act',
    needs='',
)

_side(
    'lib_recent',
    'Recent',
    'Library',
    'The last meshes opened in this studio, newest first, with the thumbnail '
    'and triangle count each had when it was closed. Re-opening from here '
    'restores the viewport camera and the op stack as they were left.',
    '<circle cx="12" cy="12" r="8.2"/><path d="M12 7.4V12l3.2 2"/>',
    [i('n', 'How many', 12, 4, 40, 1), b('thumbs', 'Show thumbnails', True)],
    cls='act',
    needs='',
)

_side(
    'lib_search',
    'Search',
    'Library',
    'Search every mesh the studio can reach — originals, derived, props, '
    'packs and character bodies — by name, tag, triangle count, whether it '
    'is rigged and whether its licence allows commercial use. Results are '
    'the union of the libraries above, not a sixth library.',
    '<circle cx="10.6" cy="10.6" r="5.8"/><path d="M14.9 14.9l4.6 4.6"/>',
    [
        s('q', 'Query', '', 'Name, tag or id'),
        e('scope', 'Scope', 'all', ('all', 'original', 'derived', 'prop', 'pack', 'character')),
        b('rigged_only', 'Rigged only', False),
        b('commercial_only', 'Commercial licence only', False),
    ],
    cls='act',
    needs='',
)

_side(
    'lib_favourites',
    'Favourites',
    'Library',
    'The meshes you pinned — bases you start from, references you measure '
    'against, the one retopo that came out right. Favourites survive a '
    'library rescan; they are stored against the mesh id, not its path, so '
    'moving a file does not lose the pin.',
    '<path d="M12 4.2l2.5 5.1 5.6.8-4 3.9 1 5.6-5.1-2.7-5.1 2.7 1-5.6-4-3.9 5.6-.8z"/>',
    [
        b('only_rigged', 'Only rigged favourites', False),
        e('sort', 'Sort by', 'pinned', ('pinned', 'name', 'last opened')),
    ],
    cls='act',
    needs='',
)


# ══ IMPORT ══════════════════════════════════════════════════════════════════
# Bringing geometry in from outside. The four image->mesh entries and the
# photogrammetry set are the only ops in this part file that load a model onto
# the GPU, hence needs='gpu': the page greys them when the card is busy.

_side(
    'imp_glb',
    'GLB / glTF',
    'Import',
    'Import a .glb or .gltf — the format that carries mesh, materials, UVs, '
    'skeleton and skin weights in one file, so it is the one to prefer when '
    'there is a choice. Embedded textures are unpacked beside the mesh so '
    'they can be replaced without re-exporting.',
    '<path d="M12 3.4l7.6 4.3v8.6L12 20.6l-7.6-4.3V7.7z"/>'
    '<path d="M15.6 10.4a4 4 0 100 3.2"/><path d="M15.6 12h-2.4"/>',
    [
        b('embed_tex', 'Unpack embedded textures', True),
        b('keep_rig', 'Keep skeleton and weights', True),
        e('units', 'Units', 'metres', ('metres', 'centimetres', 'inches', 'auto')),
    ],
    needs='',
)

_side(
    'imp_obj',
    'OBJ',
    'Import',
    'Import a Wavefront .obj with its .mtl. No rig, no animation, no scene '
    'units — an OBJ is geometry, UVs and material names, which is why it is '
    'imported with an explicit up-axis and scale rather than a guess that '
    'lands the mesh at 100x or lying on its face.',
    '<path d="M5 6.8h14v10.4H5z"/><path d="M9.2 6.8v10.4M14.8 6.8v10.4"/><path d="M5 12h14"/>',
    [
        e('up', 'Up axis', 'Y', ('Y', 'Z', '-Y', '-Z')),
        f('scale', 'Scale', 1.0, 0.001, 1000.0, 0.001),
        b('split_groups', 'Split by group', False),
        b('load_mtl', 'Load .mtl if present', True),
    ],
    needs='',
)

_side(
    'imp_fbx',
    'FBX',
    'Import',
    'Import an .fbx — the format most rigged and animated assets arrive in. '
    'Its unit and axis conventions are the usual source of a model that is '
    'the wrong size or rotated 90 degrees, so both are shown and overridable '
    'at import rather than fixed afterwards with a transform.',
    '<path d="M4.6 7.4l7.4-3.8 7.4 3.8v9.2L12 20.4l-7.4-3.8z"/><path d="M8.6 14.6V9.4h3.6M8.6 12.4h3"/>',
    [
        b('keep_rig', 'Keep skeleton and weights', True),
        b('keep_anim', 'Keep animation takes', False, 'Movement Studio owns motion; off by default'),
        e('up', 'Up axis', 'auto', ('auto', 'Y', 'Z')),
        f('scale', 'Scale', 1.0, 0.001, 1000.0, 0.001),
    ],
    needs='',
)

_side(
    'imp_ply',
    'PLY',
    'Import',
    'Import a .ply — the scan and point-cloud format. Per-vertex colour is '
    'read into a colour layer rather than discarded, which is usually the '
    'only surface information a raw scan has before it is baked to a map.',
    '<circle cx="7.2" cy="8.4" r="1.5"/><circle cx="12" cy="6.2" r="1.5"/>'
    '<circle cx="16.8" cy="9.6" r="1.5"/><circle cx="9" cy="15.4" r="1.5"/>'
    '<circle cx="15.2" cy="16.6" r="1.5"/>',
    [
        b('vcol', 'Read vertex colours', True),
        b('as_points', 'Keep as point cloud', False),
        f('scale', 'Scale', 1.0, 0.001, 1000.0, 0.001),
    ],
    needs='',
)

_side(
    'imp_stl',
    'STL',
    'Import',
    'Import an .stl — triangle soup, no UVs, no materials, usually from CAD '
    'or a printer. Vertices are welded on the way in because an STL repeats '
    'every corner three times, and the un-welded version breaks every '
    'topology op downstream.',
    '<path d="M12 4.2l8 13.8H4z"/><path d="M8.6 12h6.8M10.3 15h3.4"/>',
    [
        b('weld', 'Weld duplicate vertices', True),
        f('weld_dist', 'Weld distance (mm)', 0.01, 0.0001, 1.0, 0.0001),
        e('units', 'Units', 'millimetres', ('millimetres', 'centimetres', 'metres', 'inches')),
    ],
    needs='',
)

_side(
    'imp_usd',
    'USD / USDZ',
    'Import',
    'Import a .usd, .usda, .usdc or .usdz. USD is a scene description, not a '
    'mesh: the import lists what is inside and brings in the prim you pick, '
    'so a 40-object set does not arrive as one merged blob.',
    '<path d="M5.4 5.4h5.2v5.2H5.4zM13.4 5.4h5.2v5.2h-5.2z"/>'
    '<path d="M5.4 13.4h5.2v5.2H5.4z"/><path d="M16 13.4v5.2M13.4 16h5.2"/>',
    [
        s('prim', 'Prim path', '', 'e.g. /Root/Body — blank lists them'),
        b('flatten', 'Flatten instances', False),
        b('materials', 'Import materials', True),
    ],
    needs='',
)

_side(
    'imp_trellis',
    'Image → mesh (TRELLIS.2)',
    'Import',
    'Generate a mesh from one image with TRELLIS.2 — the structured-latent '
    'model, the best of the three for a clean, closed, UV-able result on '
    'props and characters with a clear silhouette. Slowest of the three and '
    'the one that most rewards a cut-out subject on plain background.',
    '<path d="M3.8 5.6h7.2v7.2H3.8z"/><path d="M6.2 16.4l3.4-3.6 2.6 2.6"/>'
    '<path d="M14.2 8.2l6 3.4v6l-6 3.4-2.4-1.4"/>',
    [
        s('image', 'Source image', '', 'Path under output/ or the library'),
        i('steps', 'Sampling steps', 24, 8, 64, 1),
        f('guidance', 'Guidance', 7.5, 1.0, 20.0, 0.1),
        i('target_tris', 'Target triangles', 40000, 2000, 400000, 1000),
        b('textured', 'Bake the generated texture', True),
        i('seed', 'Seed', 0, 0, 2147483647, 1),
    ],
    needs='gpu',
)

_side(
    'imp_instantmesh',
    'Image → mesh (InstantMesh)',
    'Import',
    'Generate a mesh from one image with InstantMesh — multi-view diffusion '
    'then a large reconstruction model. Fast, forgiving of a busy photo, and '
    'the one to reach for when the subject is a character seen from the '
    'front; its backs are invented and should be treated as such.',
    '<path d="M4.2 6.2h6.4v6.4H4.2z"/><path d="M7.4 15.4v4.4"/>'
    '<path d="M13.2 6.6l6.6 2.8v7l-6.6 2.8z"/><path d="M13.2 13.4l6.6-2.8"/>',
    [
        s('image', 'Source image', ''),
        i('views', 'Multi-view count', 6, 4, 12, 1),
        i('target_tris', 'Target triangles', 30000, 2000, 300000, 1000),
        b('remove_bg', 'Cut out the background first', True),
        i('seed', 'Seed', 0, 0, 2147483647, 1),
    ],
    needs='gpu',
)

_side(
    'imp_triposr',
    'Image → mesh (TripoSR)',
    'Import',
    'Generate a mesh from one image with TripoSR — a single forward pass, a '
    'few seconds, no diffusion. The roughest of the three and by far the '
    'cheapest: the right tool for blocking out a shape or for deciding '
    'whether an image is worth the slower models at all.',
    '<path d="M4.6 6.6h5.8v5.8H4.6z"/><path d="M12.8 9.5h6.6"/>'
    '<path d="M17 7.1l2.4 2.4-2.4 2.4"/>'
    '<path d="M12.4 14.2l4 2.3v4.6l-4 2.3-4-2.3v-4.6z"/>',
    [
        s('image', 'Source image', ''),
        f('mc_resolution', 'Marching-cubes resolution', 256, 64, 512, 32),
        f('fov', 'Assumed field of view', 30.0, 10.0, 90.0, 1.0),
        b('remove_bg', 'Cut out the background first', True),
    ],
    needs='gpu',
)

_side(
    'imp_colmap',
    'Photogrammetry set (COLMAP)',
    'Import',
    'Reconstruct a mesh from a folder of photographs with COLMAP — feature '
    'matching, sparse then dense reconstruction, then a Poisson surface. The '
    'only import here that produces measured geometry rather than invented '
    'geometry, and the only one where the answer to a bad result is more '
    'photographs rather than another seed.',
    '<path d="M4 8.4h3.2l1.4-2h6.8l1.4 2H20v9.2H4z"/><circle cx="12" cy="13" r="3.1"/><path d="M17.4 10.4h.8"/>',
    [
        s('folder', 'Photo folder', ''),
        e('quality', 'Quality', 'medium', ('low', 'medium', 'high', 'extreme')),
        b('dense', 'Dense reconstruction', True),
        i('poisson_depth', 'Poisson depth', 9, 6, 13, 1),
        b('mask_bg', 'Use background masks if present', False),
    ],
    needs='gpu',
)
