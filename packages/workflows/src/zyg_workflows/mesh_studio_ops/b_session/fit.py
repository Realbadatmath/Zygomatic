# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — FIT — making this mesh agree with something outside it.

Section ``FIT`` of the single-file ``b_session.py``, moved verbatim
(original lines 470-664); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _side, b, e, f, i, s

# ══ FIT ═════════════════════════════════════════════════════════════════════
# Making this mesh agree with something outside it — a reference body, a set of
# plates, a pose, a sheet cell, a scan. A fit is always proposed before it is
# applied: fit_accept and fit_reject are the two doors out, and nothing here
# writes over the source mesh until one of them is taken.

_side(
    'fit_proportions',
    'Fit proportions to reference',
    'Fit',
    "Run geom.fit_proportions: solve the mesh's limb, torso and head "
    'proportions towards a reference body while leaving surface detail '
    'alone. It moves the joints and lets the skin follow, which is why it '
    'can make a body taller without making its face longer — the failure '
    'mode of scaling the whole mesh.',
    '<circle cx="12" cy="5" r="2"/><path d="M12 7v6.4"/>'
    '<path d="M8 9.6h8M12 13.4l-2.6 5.8M12 13.4l2.6 5.8"/>'
    '<path d="M19.6 4.4v15.2M17.8 4.4h3.6M17.8 19.6h3.6"/>',
    [
        e('reference', 'Reference', 'character', ('character', 'MPFB base', 'anthro band', 'other mesh')),
        f('strength', 'Strength', 1.0, 0.0, 1.0, 0.01),
        b('lock_head', 'Do not change the head', True),
        b('lock_hands', 'Do not change hands and feet', True),
    ],
    needs='rig',
)

_side(
    'fit_plates',
    'Fit to plates',
    'Fit',
    'Fit the mesh to a set of rendered plates — depth, normal and silhouette '
    'from known cameras — by minimising the difference between what the mesh '
    'renders and what the plates hold. This is how a mesh is made to agree '
    'with imagery that was never 3D, and the residual per plate says which '
    'view is fighting the others.',
    '<path d="M3.8 6.6h6.4v6.4H3.8z"/><path d="M8 10.8h6.4v6.4H8z"/><path d="M12.2 5h7.8v9.4h-7.8z"/>',
    [
        i('iterations', 'Iterations', 40, 1, 400, 1),
        e('channels', 'Match on', 'depth+normal', ('silhouette', 'depth', 'depth+normal', 'all')),
        f('smooth', 'Regularise', 0.4, 0.0, 1.0, 0.01),
        b('per_plate_report', 'Report the residual per plate', True),
    ],
    needs='gpu',
)

_side(
    'fit_pose',
    'Pose fit',
    'Fit',
    'Estimate the pose in a photograph or a plate — SAM 3D Body for the '
    'body, geom.pose_track for a sequence — and drive the loaded rig into '
    'it. The mesh does not change shape; only the skeleton moves, so the '
    'result can be compared against the source image without the identity '
    'question and the pose question being tangled together.',
    '<circle cx="9.6" cy="4.8" r="1.8"/><path d="M9.6 6.6v5.2"/>'
    '<path d="M6 8.4l3.6-1 4.4 2.6M9.6 11.8l-2.4 7.4M9.6 11.8l4.6 3.2 1.6 4.4"/>'
    '<circle cx="18.4" cy="7.6" r="1.2"/>',
    [
        e('source', 'Source', 'image', ('image', 'plate set', 'video', 'pose json')),
        e('solver', 'Solver', 'sam3d_body', ('sam3d_body', 'pose_track', 'landmarks')),
        b('lock_root', 'Keep the root where it is', True),
        f('smooth_time', 'Temporal smoothing', 0.3, 0.0, 1.0, 0.01),
    ],
    needs='gpu',
)

_side(
    'fit_sheet_cell',
    'Align to sheet cell',
    'Fit',
    'Line the mesh up with one cell of a 48-angle sheet: solve the camera '
    'azimuth, elevation and distance that make the render match the picture. '
    'Getting this right once is what lets every other cell be used as a '
    'constraint rather than as a suggestion.',
    '<path d="M4.4 5h15.2v13.2H4.4z"/><path d="M9.5 5v13.2M14.6 5v13.2"/>'
    '<path d="M4.4 9.4h15.2M4.4 13.8h15.2"/><path d="M9.5 9.4h5.1v4.4H9.5z"/>',
    [
        i('cell', 'Cell', 1, 1, 48, 1),
        b('solve_camera', 'Solve the camera, not the mesh', True),
        f('search', 'Search range (°)', 20.0, 1.0, 180.0, 1.0),
        b('refine', 'Refine on the silhouette', True),
    ],
    cls='pix',
)

_side(
    'fit_height',
    'Scale to character height',
    'Fit',
    "Scale the mesh uniformly so it stands exactly at the character's "
    'recorded height_m, measured sole to crown in the rest pose rather than '
    'by the bounding box, so hair and heels do not eat the difference. The '
    'scale factor applied is written to the mesh record.',
    '<path d="M5.4 3.8v16.4"/><path d="M5.4 3.8h3.2M5.4 20.2h3.2"/>'
    '<path d="M5.4 8h2M5.4 12h2M5.4 16h2"/>'
    '<circle cx="15.4" cy="6.6" r="2"/><path d="M15.4 8.6v5.4l-2 6.2"/>'
    '<path d="M15.4 14l2 6.2"/>',
    [
        f('height_m', 'Height (m)', 1.75, 0.2, 4.0, 0.01),
        e('measure', 'Measure', 'sole to crown', ('sole to crown', 'bounding box', 'eye height')),
        b('from_record', 'Take the height from the character record', True),
        b('scale_rig', 'Scale the rig with it', True),
    ],
)

_side(
    'fit_shrinkwrap',
    'Shrinkwrap to scan',
    'Fit',
    'Pull the mesh onto a scan or a denser sibling along the normals, '
    "keeping this mesh's topology and taking that one's shape. The clean "
    'way to give a retopologised body the detail of the scan it was built '
    'from; the offset and the limit keep it from snapping through thin parts '
    'and turning the surface inside out.',
    '<path d="M4.6 12a7.4 7.4 0 0114.8 0"/>'
    '<path d="M6.8 12a5.2 5.2 0 0110.4 0"/>'
    '<path d="M7 15.4l1.6 2M12 16v2.6M17 15.4l-1.6 2"/>',
    [
        f('offset', 'Offset (mm)', 0.0, -20.0, 20.0, 0.01),
        f('limit', 'Maximum travel (mm)', 20.0, 0.1, 200.0, 0.1),
        e('mode', 'Direction', 'normal', ('normal', 'nearest surface', 'project axis')),
        b('keep_detail', "Keep this mesh's fine detail", False),
    ],
)

_side(
    'fit_landmarks',
    'Landmark pins',
    'Fit',
    'Pin named landmarks — inner eye corners, chin, acromion, wrist, ankle — '
    'on this mesh to their counterparts on the reference, and let every fit '
    'in this section honour the pins as hard constraints. Four good pins fix '
    'more error than a hundred iterations of an unconstrained solve.',
    '<path d="M12 3.8a4.2 4.2 0 014.2 4.2c0 3-4.2 8.2-4.2 8.2S7.8 11 7.8 8A4.2 '
    '4.2 0 0112 3.8z"/><circle cx="12" cy="8" r="1.5"/>'
    '<path d="M6.2 19.6h11.6"/>',
    [
        e('set', 'Landmark set', 'body', ('body', 'face', 'hand', 'custom')),
        i('count', 'Pins', 8, 1, 68, 1),
        b('hard', 'Treat pins as hard constraints', True),
        b('show', 'Draw the pins in the viewport', True),
    ],
    cls='pix',
)

_side(
    'fit_report',
    'Fit report',
    'Fit',
    'What the proposed fit would cost: per-vertex travel, the worst region, '
    'the change to every anthropometric ratio and the identity score before '
    'and after. Read before accepting — a fit that improves the silhouette '
    'and fails the identity gate is a different character, cheaply.',
    '<path d="M5.2 19.4V9.2M9.6 19.4V5.4M14 19.4v-8M18.4 19.4V7.6"/>'
    '<path d="M3.4 19.4h17.2"/><path d="M5.2 14.2l4.4-3 4.4 2.6 4.4-4"/>',
    [
        b('travel_map', 'Paint the per-vertex travel', True),
        b('ratios', 'Include the proportion ratios', True),
        b('identity', 'Score identity before and after', True),
    ],
    cls='pix',
)

_side(
    'fit_accept',
    'Accept fit',
    'Fit',
    'Apply the proposed fit as a derived mesh: a new mesh with this one as '
    'its parent and the fit and its parameters recorded in the lineage. The '
    'source is left exactly as it was, so accepting a fit is never the '
    'moment a good mesh is lost.',
    '<path d="M4.8 12.6l4.6 4.6 9.8-10.4"/><path d="M19.4 12.8v6.4H6.6"/>',
    [
        s('name', 'Name the derived mesh', ''),
        b('open_it', 'Open the result', True),
        b('keep_proposal', 'Keep the proposal for comparison', False),
    ],
    cls='act',
)

_side(
    'fit_reject',
    'Reject fit',
    'Fit',
    'Throw the proposed fit away and put the viewport back on the source '
    'mesh. The proposal, its parameters and its report can be kept in the '
    'session log even so: a fit that was tried and rejected is the cheapest '
    'thing to accidentally try again.',
    '<path d="M7.4 7.4l9.2 9.2M16.6 7.4l-9.2 9.2"/><path d="M4.6 12.8v6.4h13.2"/>',
    [b('log_it', 'Keep it in the session log', True), b('restore_camera', 'Restore the camera too', True)],
    cls='act',
)
