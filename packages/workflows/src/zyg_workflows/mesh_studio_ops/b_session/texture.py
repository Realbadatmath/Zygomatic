# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — TEXTURE — the surface as pixels rather than as shader constants.

Section ``TEXTURE`` of the single-file ``b_session.py``, moved verbatim
(original lines 46-240); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _side, b, c, e, f, i

# ══ TEXTURE ═════════════════════════════════════════════════════════════════
# The surface as pixels rather than as shader constants: where the image comes
# from, how it gets onto the UVs, and what it costs to ship. Material (part A)
# says what the surface is made of; Texture says what it looks like.

_side(
    'tex_project_image',
    'Project from image',
    'Texture',
    'Project a single photograph or concept image onto the mesh from the '
    'current camera and bake what it covers into the UV atlas. The camera '
    'that projects is the camera you are looking through, so the framing you '
    'judge the fit by is the framing that is baked — and faces turned more '
    'than 70° from it are left to the next projection rather than smeared.',
    '<path d="M4.4 5.6h9.2v8.2H4.4z"/><path d="M14.4 7.4l5.2-2.4v11l-5.2-2.4"/>'
    '<circle cx="8.2" cy="9.4" r="1.9"/><path d="M6 19.4h12"/>',
    [
        f('angle_limit', 'Drop faces beyond (°)', 70.0, 20.0, 89.0, 1.0),
        f('blend', 'Edge blend', 0.25, 0.0, 1.0, 0.01),
        b('occlusion', 'Skip faces the camera cannot see', True),
        e('space', 'Colour space', 'sRGB', ('sRGB', 'linear', 'raw')),
    ],
)

_side(
    'tex_project_sheet',
    'Project from 48-angle sheet',
    'Texture',
    'Project the whole 48-angle contact sheet at once — every cell with its '
    'own camera — and resolve the overlaps by facing angle, so each texel '
    'takes its colour from the view that saw it most squarely. This is the '
    'op that turns a character sheet back into a textured mesh instead of a '
    'set of pictures of one.',
    '<path d="M4.2 4.8h5.4v5.4H4.2zM9.6 4.8H15v5.4H9.6zM15 4.8h4.8v5.4H15z"/>'
    '<path d="M4.2 10.2h5.4v5.4H4.2zM9.6 10.2H15v5.4H9.6zM15 10.2h4.8v5.4H15z"/>'
    '<path d="M7 18.6h10l-2.6 2.4H9.6z"/>',
    [
        i('cells', 'Cells to use', 48, 4, 48, 1),
        e('weight', 'Resolve overlaps by', 'facing', ('facing', 'sharpest', 'median', 'first')),
        f('feather', 'Feather between cells', 0.3, 0.0, 1.0, 0.01),
        b('fill_holes', 'Fill texels no cell saw', True),
    ],
    needs='gpu',
)

_side(
    'tex_bake_atlas',
    'Bake sheet to atlas',
    'Texture',
    'Bake the projected result down to one flat texture set — base colour, '
    "normal, roughness and ambient occlusion — on the mesh's own UVs. The "
    'bake is the point where a stack of projections stops being a live '
    'computation and becomes four PNGs a renderer can load in a millisecond.',
    '<path d="M5 18.6h14v2H5z"/><path d="M6.6 18.6V9.4h10.8v9.2"/>'
    '<path d="M9 6.6c0-1.4 1.6-1.6 1.6-3M13 6.6c0-1.4 1.6-1.6 1.6-3"/>',
    [
        e('size', 'Atlas size', '2048', ('1024', '2048', '4096', '8192')),
        i('samples', 'Samples per texel', 16, 1, 256, 1),
        i('padding', 'Padding (px)', 16, 0, 64, 1),
        b('bake_normal', 'Bake normal map', True),
        b('bake_ao', 'Bake ambient occlusion', True),
        b('bake_rough', 'Bake roughness', True),
    ],
    needs='gpu',
)

_side(
    'tex_resize_atlas',
    'Resize atlas',
    'Texture',
    'Resample every map on the mesh to a new resolution with one filter and '
    'one rule, so colour, normal and data maps stay the same size as each '
    'other. Normals are renormalised after the resample rather than merely '
    'scaled — a bilinear shrink of a normal map denormalises every texel it '
    'touches, and the shading error looks like faceting.',
    '<path d="M4.6 4.6h9v9h-9z"/><path d="M13.6 13.6h5.8v5.8h-5.8z"/><path d="M11 6.8l6.4 6.4M14.4 6.8h3v3"/>',
    [
        e('size', 'New size', '2048', ('512', '1024', '2048', '4096')),
        e('filter', 'Filter', 'lanczos', ('nearest', 'bilinear', 'lanczos', 'mitchell')),
        b('renormalise', 'Renormalise normal maps', True),
        b('keep_original', 'Keep the original beside it', True),
    ],
)

_side(
    'tex_ktx2',
    'KTX2 compress',
    'Texture',
    'Compress the texture set to KTX2 / Basis Universal — the GPU-resident '
    "format the page's three.js viewer can upload without decoding to RGBA "
    'first. A 4096 colour map goes from 64 MB of VRAM to about 5 MB, which '
    'is the difference between four meshes open at once and one.',
    '<path d="M5.4 6.2h13.2v11.6H5.4z"/><path d="M8.8 9.6h6.4v4.8H8.8z"/>'
    '<path d="M5.4 12h3.4M15.2 12h3.4M12 6.2v3.4M12 14.4v3.4"/>',
    [
        e('mode', 'Mode', 'UASTC', ('ETC1S', 'UASTC')),
        i('quality', 'Quality', 128, 1, 255, 1),
        b('mipmaps', 'Generate mipmaps', True),
        b('srgb_colour', 'Tag colour maps as sRGB', True),
    ],
)

_side(
    'tex_denoise',
    'Denoise',
    'Texture',
    'Denoise the baked maps. A projection from photographs carries the '
    "camera's sensor noise and a path-traced AO bake carries its own; both "
    'read as grain that the normal map then turns into shading. Denoising '
    'after the bake and before the compress is the only place it is cheap.',
    '<path d="M4.8 15.4c2.2-5.6 4.4 2.4 6.6-3.2s4.4 1.6 6.6-3"/>'
    '<path d="M4.8 19.2h14.4"/><circle cx="18.4" cy="6.4" r="1.4"/>'
    '<circle cx="7.6" cy="6.2" r="1"/><circle cx="12.6" cy="8" r="1"/>',
    [
        e('what', 'Which maps', 'all', ('all', 'colour', 'ao', 'normal')),
        f('strength', 'Strength', 0.5, 0.0, 1.0, 0.01),
        f('detail', 'Keep detail above', 0.3, 0.0, 1.0, 0.01),
        b('albedo_guide', 'Guide with the albedo map', True),
    ],
)

_side(
    'tex_seam_fix',
    'Seam fix',
    'Texture',
    'Find the UV seams and make the texels on both sides agree. A seam is '
    'two edges of the atlas that are one edge of the mesh, and any op that '
    'treats the atlas as a picture — denoise, resize, compress, paint — '
    'breaks that agreement and draws a visible line down the model.',
    '<path d="M12 3.8v16.4"/><path d="M8.6 5.6l3.4 3.4 3.4-3.4"/>'
    '<path d="M8.6 12l3.4 3.4 3.4-3.4"/><path d="M5.4 3.8h3.2M15.4 3.8h3.2"/>',
    [
        i('width', 'Blend width (px)', 4, 1, 32, 1),
        b('match_colour', 'Match colour across the seam', True),
        b('match_normal', 'Match normals across the seam', True),
        b('report_only', 'Report the seams without changing them', False),
    ],
    cls='pix',
)

_side(
    'tex_colour',
    'Colour correct',
    'Texture',
    'Exposure, white balance, saturation and gamma on the colour map only — '
    'never on the normal, roughness or AO maps, which are data and not '
    'pictures. Projections from different photographs land at different '
    'exposures; this is where they are made one surface.',
    '<circle cx="9.8" cy="9.8" r="5"/><circle cx="14.6" cy="9.8" r="5"/><circle cx="12.2" cy="14.4" r="5"/>',
    [
        f('exposure', 'Exposure (stops)', 0.0, -4.0, 4.0, 0.05),
        f('temperature', 'Temperature', 0.0, -1.0, 1.0, 0.01),
        f('saturation', 'Saturation', 1.0, 0.0, 2.0, 0.01),
        f('gamma', 'Gamma', 1.0, 0.2, 3.0, 0.01),
        c('tint', 'Tint', '#ffffff'),
    ],
)

_side(
    'tex_preview',
    'Texture preview',
    'Texture',
    'Show the atlas itself beside the viewport with the UV shells drawn over '
    'it, so a texel that lands in the wrong island is seen on the sheet '
    'rather than hunted for on the model. Clicking a shell selects its faces '
    'in the 3D view and the other way round.',
    '<path d="M4.4 6h15.2v12H4.4z"/><path d="M4.4 15l4.2-4.2 3 3 3.4-3.6 4.6 4.8"/><circle cx="8.4" cy="9.2" r="1.3"/>',
    [
        e('map', 'Show map', 'colour', ('colour', 'normal', 'roughness', 'ao', 'uv layout')),
        b('overlay_uv', 'Draw the UV shells over it', True),
        b('checker', 'Checker instead of the map', False),
        f('zoom', 'Zoom', 1.0, 0.25, 8.0, 0.05),
    ],
    cls='pix',
)

_side(
    'tex_export',
    'Texture export',
    'Texture',
    'Write the texture set out as loose files beside the mesh, named by map '
    'and by mesh id, with a sidecar that records which projection and which '
    'bake produced them. Loose maps are what an external DCC, a game engine '
    'and a diff all want; embedded maps are what a .glb wants.',
    '<path d="M12 4.2v9.6"/><path d="M8.4 10.4l3.6 3.4 3.6-3.4"/>'
    '<path d="M4.8 15.6v3.8h14.4v-3.8"/><path d="M7.6 6.4H4.8M19.2 6.4h-2.8"/>',
    [
        e('format', 'Format', 'png', ('png', 'jpg', 'exr', 'ktx2')),
        e('which', 'Which maps', 'all', ('all', 'colour', 'data only')),
        i('jpg_quality', 'JPEG quality', 92, 40, 100, 1),
        b('sidecar', 'Write the provenance sidecar', True),
    ],
)
