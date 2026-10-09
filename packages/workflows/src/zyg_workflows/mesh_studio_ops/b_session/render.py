# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — RENDER — pictures of the mesh, made off-screen.

Section ``RENDER`` of the single-file ``b_session.py``, moved verbatim
(original lines 885-1123); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _dock, b, c, e, f, i

# ══ RENDER ══════════════════════════════════════════════════════════════════
# Pictures of the mesh, made off-screen at a size and a quality the viewport
# cannot give. The view modes here are RENDERS (they write files); the ones in
# View are the same looks applied live to the viewport and write nothing.

_dock(
    'rd_turntable',
    'Render turntable',
    'Render',
    'Render one revolution at the chosen quality and keep the frames as well '
    'as the movie, so a single bad angle can be re-rendered without redoing '
    'the orbit. The camera height and the distance are held constant, which '
    'is what makes two turntables of two versions comparable.',
    '<circle cx="12" cy="13.4" r="6.4"/><path d="M5.6 13.4c0 1.6 2.9 2.9 6.4 2.9"/>'
    '<path d="M15.2 4.6l2.8 2-2.8 2"/><path d="M8.4 6.6h9.6"/>',
    [
        i('frames', 'Frames', 150, 24, 720, 1),
        f('elevation', 'Camera elevation (°)', 12.0, -80.0, 80.0, 1.0),
        e('quality', 'Quality', 'preview', ('draft', 'preview', 'final')),
        b('keep_frames', 'Keep the frames', True),
    ],
    needs='gpu',
)

_dock(
    'rd_sheet48',
    'Render 48-angle sheet',
    'Render',
    'Render the full 48-camera ring as one contact sheet — the same ring the '
    'plate export uses, so a sheet and a plate set of the same mesh are the '
    'same cameras. This is the picture a diffusion leg is conditioned on and '
    'the picture fit_sheet_cell aligns against.',
    '<path d="M4.2 4.4h4.6v4.6H4.2zM9.7 4.4h4.6v4.6H9.7zM15.2 4.4h4.6v4.6h-4.6z"/>'
    '<path d="M4.2 9.9h4.6v4.6H4.2zM9.7 9.9h4.6v4.6H9.7zM15.2 9.9h4.6v4.6h-4.6z"/>'
    '<path d="M4.2 15.4h4.6v4.6H4.2zM9.7 15.4h4.6v4.6H9.7z"/>'
    '<path d="M17.5 17.7h2.3"/>',
    [
        i('angles', 'Angles', 48, 4, 96, 1),
        e('cell', 'Cell size', '512', ('256', '512', '1024')),
        f('elevation', 'Elevation (°)', 0.0, -80.0, 80.0, 1.0),
        b('label_cells', 'Number the cells', True),
    ],
    needs='gpu',
)

_dock(
    'rd_clay',
    'Clay render',
    'Render',
    'Render with every material replaced by one matte grey. Removes colour, '
    'texture and shader from the judgement and leaves form, silhouette and '
    'shading — which is the only way to see that a shape is wrong rather '
    'than that a texture is distracting.',
    '<path d="M6.4 19.4c0-4.4 1.6-7.2 5.6-7.2s5.6 2.8 5.6 7.2z"/>'
    '<circle cx="12" cy="7.8" r="3.4"/><path d="M4.4 19.4h15.2"/>',
    [
        c('colour', 'Clay colour', '#b9b2a6'),
        f('roughness', 'Roughness', 0.7, 0.0, 1.0, 0.01),
        b('keep_transparency', 'Keep transparent materials transparent', False),
        e('size', 'Size', '1080p', ('540p', '720p', '1080p', '2160p')),
    ],
    needs='gpu',
)

_dock(
    'rd_wire',
    'Wire render',
    'Render',
    'Render the wireframe over the shaded surface at a resolution the '
    'viewport cannot reach, so edge flow can be read on a dense mesh instead '
    'of turning into a grey smear. The width is in pixels of the output, not '
    'in world units, which keeps it legible at any size.',
    '<path d="M12 3.8l7.4 4.6-2.8 8.4H7.4L4.6 8.4z"/><path d="M4.6 8.4h14.8M12 3.8v12.8M7.4 16.8L12 8.4l4.6 8.4"/>',
    [
        f('width', 'Line width (px)', 1.2, 0.2, 6.0, 0.1),
        c('colour', 'Wire colour', '#1b1b1b'),
        f('shade', 'Surface behind it', 0.6, 0.0, 1.0, 0.01),
        b('hide_back', 'Hide back-facing wires', True),
    ],
    needs='gpu',
)

_dock(
    'rd_normal',
    'Normal render',
    'Render',
    'Render the surface normal per pixel as an RGB image in the chosen '
    'space. World space to check orientation, camera space to feed a '
    'conditioning leg — they look similar and are not interchangeable, so '
    'the space is written into the filename.',
    '<path d="M4.8 17.6l6.4-9.4 3.2 4.6"/>'
    '<path d="M11.2 8.2l3.6-2.6M14.8 5.6l.9 2.4M14.8 5.6l-2.4.7"/>'
    '<path d="M4.8 19.8h14.4"/>',
    [
        e('space', 'Space', 'camera', ('camera', 'world', 'object')),
        b('flip_green', 'Flip the green channel (DirectX)', False),
        e('size', 'Size', '1024', ('512', '1024', '2048')),
    ],
    needs='gpu',
)

_dock(
    'rd_depth',
    'Depth render',
    'Render',
    'Render distance from the camera, with the near and far planes either '
    'fitted to the mesh or pinned. Fitted depth looks better and is not '
    'comparable between meshes; pinned depth is the one to use when the map '
    'is going to condition something or be differenced against a plate.',
    '<path d="M4.6 5.6h14.8v12.8H4.6z"/><path d="M7.4 8.4h9.2v7.2H7.4zM9.8 10.6h4.4v2.8H9.8z"/>',
    [
        e('range', 'Range', 'fit to mesh', ('fit to mesh', 'pinned', 'from camera')),
        f('near', 'Near (m)', 0.1, 0.001, 100.0, 0.01),
        f('far', 'Far (m)', 10.0, 0.01, 1000.0, 0.01),
        b('invert', 'Near is white', True),
    ],
    needs='gpu',
)

_dock(
    'rd_matcap',
    'Matcap render',
    'Render',
    'Shade the mesh with a captured material sphere: no lights, no shadows, '
    'entirely determined by the normal facing the camera. The cheapest '
    'reliable way to read surface quality — a matcap shows a dent, a pinch '
    'and a shading seam that a lit render flatters away.',
    '<circle cx="12" cy="12" r="7.6"/><path d="M8.4 8.4a5 5 0 016.4-.6"/><circle cx="9.4" cy="9.4" r="1.6"/>',
    [
        e('matcap', 'Matcap', 'pearl', ('pearl', 'clay', 'chrome', 'red wax', 'jade', 'basic dark')),
        b('outline', 'Draw a silhouette outline', False),
        e('size', 'Size', '1080p', ('540p', '720p', '1080p')),
    ],
    needs='gpu',
)

_dock(
    'rd_hdri',
    'HDRI lighting',
    'Render',
    'Light the render with an HDRI from the Poly Haven set — real-world '
    'illumination with its own colour and direction, which is what makes a '
    'material read as a material. Rotating the environment changes the key '
    'light without moving a lamp, and both the map and the rotation are '
    'recorded so a render can be reproduced.',
    '<circle cx="12" cy="12" r="7.8"/>'
    '<path d="M4.2 12h15.6M12 4.2c2.6 2.6 2.6 12.2 0 15.6M12 4.2c-2.6 2.6-2.6 '
    '12.2 0 15.6"/>',
    [
        e(
            'hdri',
            'Environment',
            'studio_small',
            ('studio_small', 'sunset', 'overcast', 'courtyard', 'night', 'forest'),
        ),
        f('rotation', 'Rotation (°)', 0.0, 0.0, 360.0, 1.0),
        f('strength', 'Strength', 1.0, 0.0, 10.0, 0.01),
        b('show_background', 'Show the environment behind the mesh', False),
    ],
    needs='gpu',
)

_dock(
    'rd_camera',
    'Camera preset',
    'Render',
    'Pick the camera the render uses: the named views (front, three-quarter, '
    'profile, top) or the viewport camera as it stands. The named ones are '
    'the ones worth keeping — a comparison between two versions only means '
    'something if both were shot from the same place.',
    '<path d="M4.6 8.2h4l1.6-2.2h3.6l1.6 2.2h4v9.6H4.6z"/><circle cx="12" cy="12.8" r="3"/>',
    [
        e(
            'preset',
            'Preset',
            'three-quarter',
            ('viewport', 'front', 'three-quarter', 'profile', 'back', 'top', 'hero'),
        ),
        f('focal', 'Focal length (mm)', 50.0, 12.0, 300.0, 1.0),
        b('frame_mesh', 'Frame the mesh automatically', True),
    ],
    cls='pix',
)

_dock(
    'rd_resolution',
    'Resolution',
    'Render',
    'The output size and sampling every render in this section uses, set '
    'once rather than per op. Supersampling renders large and downsamples, '
    'which fixes aliasing on a wire or a lineart pass that no amount of '
    'anti-aliasing at final size will.',
    '<path d="M4.4 6.2h15.2v11.6H4.4z"/><path d="M4.4 12h15.2M12 6.2v11.6"/><path d="M17.2 15v2.8h-2.8"/>',
    [
        e('size', 'Size', '1080p', ('540p', '720p', '1080p', '1440p', '2160p')),
        i('supersample', 'Supersample', 2, 1, 4, 1),
        i('samples', 'Samples per pixel', 64, 1, 1024, 1),
        b('transparent', 'Transparent background', False),
    ],
    cls='pix',
)

_dock(
    'rd_background',
    'Background',
    'Render',
    'What is behind the mesh in a render: flat colour, gradient, checker or '
    'transparent. Transparent is the default worth keeping for anything '
    'going into a sheet or a composite; a flat mid-grey is the one to judge '
    'a silhouette against.',
    '<path d="M4.8 5.8h14.4v12.4H4.8z"/><path d="M4.8 5.8h4.8v4.1H4.8zM9.6 9.9h4.8V14H9.6zM14.4 14h4.8v4.2h-4.8z"/>',
    [
        e('kind', 'Kind', 'transparent', ('transparent', 'flat', 'gradient', 'checker', 'environment')),
        c('colour', 'Colour', '#2a2f34'),
        c('colour2', 'Second colour', '#0f1114'),
    ],
    cls='pix',
)

_dock(
    'rd_queue',
    'Render queue',
    'Render',
    'The queue every render in this section goes onto, and the only place '
    'that decides what has the GPU. One card, one job at a time: a queue '
    'that holds the turntable until the plate set is done is the difference '
    'between two renders finishing and both of them failing on VRAM.',
    '<path d="M4.6 6h10.8M4.6 12h10.8M4.6 18h6.4"/>'
    '<circle cx="18.4" cy="6" r="1.5"/><circle cx="18.4" cy="12" r="1.5"/>'
    '<path d="M17 17h2.8M18.4 15.6v2.8"/>',
    [
        e('action', 'Action', 'show', ('show', 'pause', 'resume', 'clear finished', 'cancel current')),
        i('vram_reserve_gb', 'Keep VRAM free (GB)', 2, 0, 24, 1),
        b('notify', 'Note each finished render in the session log', True),
    ],
    needs='',
)
