# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""BLENDER SIDE: rendering, image reads, NCC and the texture-lock verification."""

from zyg_workflows.geom.mv_render.blender_scene import _bl_place_camera
from zyg_workflows.geom.mv_render.constants import TRANSLATION_TOL_PX, math, os
from zyg_workflows.geom.mv_render import constants as _mv_constants

# Bound by ASSIGNMENT, not `from ... import`: an import-originated global compiles
# `_zyg_log.debug(...)` to a different (non method-form) call sequence.
_zyg_log = _mv_constants._zyg_log


def _bl_render(sc_path):
    import bpy

    bpy.context.scene.render.filepath = sc_path
    bpy.ops.render.render(write_still=True)


def _bl_read_rgb(path):
    """Read a PNG back inside Blender as an (H, W, 3) float array of 0..255 sRGB bytes.

    TRAP: Blender's bundled python has numpy but NO Pillow, so the images have to come
    back through bpy.data.images. A loaded PNG defaults to the sRGB colorspace and
    .pixels would then hand back scene-linear floats; forcing 'Non-Color' makes .pixels
    the raw stored values, which is what the byte thresholds below assume. Blender's
    pixel buffer is bottom-up, hence the flip.
    """
    import bpy
    import numpy as np

    img = bpy.data.images.load(path)
    img.colorspace_settings.name = 'Non-Color'
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    a = buf.reshape(h, w, 4)[::-1, :, :3] * 255.0
    bpy.data.images.remove(img)
    return a.astype(np.float64)


def _bl_gray(path):

    a = _bl_read_rgb(path)
    return a[:, :, 0] * 0.299 + a[:, :, 1] * 0.587 + a[:, :, 2] * 0.114


def _bl_ncc_shift(a, b, max_shift):
    """Best integer x-shift of b against a, by normalised cross-correlation.

    Returns (best_shift_px, best_ncc, ncc_at_zero). Both arrays are the SAME pixel
    crop of two frames, and the returned shift is signed so that POSITIVE means the
    content in b sits that many pixels to the RIGHT of where it sits in a. (The loop
    below slides a, so its own index runs the other way and is negated on return —
    the first version reported -75 for a +75 px move and looked like a failure.)
    """

    best = (0, -2.0)
    zero = None
    for s in range(-max_shift, max_shift + 1):
        if s >= 0:
            x = a[:, s:]
            y = b[:, : b.shape[1] - s] if s else b
        else:
            x = a[:, : a.shape[1] + s]
            y = b[:, -s:]
        x = x - x.mean()
        y = y - y.mean()
        d = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
        n = float((x * y).sum()) / d if d > 0 else 0.0
        if s == 0:
            zero = n
        if n > best[1]:
            best = (s, n)
    return -best[0], best[1], zero


def _bl_verify_texture_lock(obj, cam, frm, cfg, tmpdir, lock_struct):
    """Empirical half of the texture-lock proof: translation test + azimuth
    decorrelation. See the module docstring for why these two and not others.

    The crop is chosen from the SUBJECT MASK, not fixed: it is the tallest band of
    rows that is solid subject across x in [0.30, 0.70] in the az-0, the translated
    and the az-180 frames at once. That keeps the moving silhouette edge out of the
    correlation, so the peak is decided by the texture pattern itself and not by the
    outline. A hard-coded central crop was tried first and landed on background.
    """
    import numpy as np

    dx = 0.030
    target = frm['target_world']
    dist = frm['camera_distance_m']

    _bl_place_camera(cam, 0.0, cfg['elevation_deg'], target, dist)
    p0 = os.path.join(tmpdir, 'lock_az000.png')
    _bl_render(p0)

    obj.location = (dx, 0.0, 0.0)
    p1 = os.path.join(tmpdir, 'lock_shift.png')
    _bl_render(p1)
    obj.location = (0.0, 0.0, 0.0)

    _bl_place_camera(cam, 180.0, cfg['elevation_deg'], target, dist)
    p2 = os.path.join(tmpdir, 'lock_az180.png')
    _bl_render(p2)
    _bl_place_camera(cam, 0.0, cfg['elevation_deg'], target, dist)

    W, H = cfg['out_w'], cfg['out_h']
    x0, x1 = int(0.30 * W), int(0.70 * W)
    solid = np.ones(H, bool)
    for p in (p0, p1, p2):
        m, _ = _bl_subject_mask(_bl_read_rgb(p))
        solid &= m[:, x0:x1].all(axis=1)
    runs, s = [], None
    for y in range(H + 1):
        if y < H and solid[y]:
            s = y if s is None else s
        elif s is not None:
            runs.append((y - s, s, y))
            s = None
    if not runs or max(runs)[0] < 60:
        raise RuntimeError('no solid-subject band found for the texture-lock crop; framing or exposure is wrong')
    _, y0, y1 = max(runs)
    a = _bl_gray(p0)[y0:y1, x0:x1]
    b = _bl_gray(p1)[y0:y1, x0:x1]
    c = _bl_gray(p2)[y0:y1, x0:x1]

    # THE PREDICTED SHIFT IS A RANGE, NOT A NUMBER, AND THE FIRST VERSION OF THIS TEST
    # TREATED IT AS ONE.
    # dx * px_per_m_at_target is the projected shift AT THE CAMERA TARGET PLANE. The pixels
    # being correlated do not lie on that plane: they lie on the front of the torso, which
    # is nearer the camera, and a nearer surface projects a LARGER shift. On this mesh the
    # crop's front surface sits ~48 mm in front of the target plane, which is 74.7 px at
    # the plane against 78.1 px at the surface — outside a +/-3 px window centred on 74.7.
    # The delivered peak of 75 landed inside only because the NCC averages over a crop
    # whose sides recede toward the plane. That is zero real margin, and any re-centring,
    # different GLB or different framing would abort a perfectly surface-locked build.
    #
    # So the window is derived from the DEPTH SPAN of the surface actually inside the crop,
    # measured off the mesh, plus a tolerance for the integer NCC peak and the depth
    # weighting inside the crop. The physics is unchanged; what changes is that the
    # prediction is now stated over the geometry it is a prediction about.
    f_px = frm['px_per_m_at_target'] * dist  # focal length in pixels
    frame_h, frame_w = frm['frame_height_m'], frm['frame_width_m']
    z_hi = target[2] + 0.5 * frame_h - (y0 / float(H)) * frame_h  # crop top, world z
    z_lo = target[2] + 0.5 * frame_h - (y1 / float(H)) * frame_h
    xw0 = -0.5 * frame_w + (x0 / float(W)) * frame_w
    xw1 = -0.5 * frame_w + (x1 / float(W)) * frame_w
    ys = [v.co.y for v in obj.data.vertices if z_lo <= v.co.z <= z_hi and xw0 <= v.co.x <= xw1]
    if not ys:
        raise RuntimeError(
            'no mesh vertices inside the texture-lock crop band '
            '(z %.3f..%.3f, x %.3f..%.3f); the crop is not on the subject' % (z_lo, z_hi, xw0, xw1)
        )
    # az 0 puts the camera at y = -dist looking +Y, so depth = y + dist and only the FRONT
    # (smallest y) of the surface is visible. Depths run from the nearest vertex to the
    # target plane at the silhouette edges.
    z_near = dist + min(ys)
    pred_at_target = dx * f_px / dist
    pred_at_near = dx * f_px / z_near
    pred_lo, pred_hi = sorted((pred_at_target, pred_at_near))
    predicted = 0.5 * (pred_lo + pred_hi)
    s_t, n_t, n_t0 = _bl_ncc_shift(a, b, 100)
    s_a, n_a, _ = _bl_ncc_shift(a, c, 80)

    # Fail the BUILD, not the manifest. If the texture ever stops being surface-locked
    # the positive control silently becomes a fiction, and a fictitious ceiling is
    # worse than no ceiling. These are physics predictions, not quality thresholds:
    # the shift is where projection says the pattern must land, full stop. What a
    # screen-locked pattern does is peak at ZERO, which is 25 sigma from this window.
    if not (pred_lo - TRANSLATION_TOL_PX <= s_t <= pred_hi + TRANSLATION_TOL_PX):
        raise RuntimeError(
            'texture-lock TRANSLATION test failed: pattern moved %d px, '
            'projection predicts %.1f..%.1f px over the depth span of the '
            'correlated surface (%.4f..%.4f m from the camera), tolerance '
            '+/-%.0f px' % (s_t, pred_lo, pred_hi, z_near, dist, TRANSLATION_TOL_PX)
        )
    if n_t < 0.5 or n_t < 4.0 * max(n_t0, 1e-6):
        raise RuntimeError(
            'texture-lock TRANSLATION test inconclusive: ncc %.3f at the predicted shift vs %.3f at zero' % (n_t, n_t0)
        )
    if n_a > 0.5:
        raise RuntimeError(
            'texture-lock AZIMUTH test failed: az0 vs az180 ncc %.3f — the pattern is repeating across views' % n_a
        )

    out = dict(lock_struct)
    out.update(
        {
            'translation_test': {
                'object_shift_m': dx,
                'predicted_px': round(predicted, 2),
                'predicted_px_range': [round(pred_lo, 2), round(pred_hi, 2)],
                'predicted_px_at_target_plane': round(pred_at_target, 2),
                'predicted_px_at_nearest_surface': round(pred_at_near, 2),
                'crop_depth_span_m': [round(z_near, 4), round(dist, 4)],
                'tolerance_px': TRANSLATION_TOL_PX,
                'prediction_note': (
                    'the correlated pixels are on the front of the torso, not '
                    'on the camera target plane, and a nearer surface projects '
                    'a larger shift. The window is the span of the projection '
                    'over the depth actually inside the crop; a single number '
                    'taken at the target plane left ~0 px of margin.'
                ),
                'measured_peak_px': s_t,
                'ncc_at_peak': round(n_t, 4),
                'ncc_at_zero_shift': round(n_t0, 4),
                'reading': (
                    'peak at the predicted shift => the pattern moved WITH the '
                    'surface; a screen-locked pattern would have peaked at 0'
                ),
            },
            'azimuth_decorrelation_test': {
                'pair': 'az 0 vs az 180',
                'best_ncc': round(n_a, 4),
                'best_shift_px': s_a,
                'reading': ('a screen-locked pattern would repeat identically in every frame and score near 1.0 here'),
            },
            'crop_used': {'y': [y0, y1], 'x': [x0, x1]},
        }
    )
    for p in (p0, p1, p2):
        try:
            os.remove(p)
        except OSError as _exc:
            _zyg_log.debug('probe temp image cleanup skipped: %s', _exc)
    return out


def _bl_subject_mask(a, margin=12.0):
    """Exact subject mask. The background is a flat unlit world colour, so its byte
    value is read off the image itself and anything more than `margin` brighter is
    subject.

    Reading the background rather than hard-coding a threshold matters: the world is
    0.035 linear, which under the Standard transform is byte 55, not the ~9 a naive
    0.035*255 would suggest, and the first version of this function called the whole
    frame subject at every azimuth (coverage 1.000 x 48).

    Only the TOP two 16 px corners are sampled. The head vertex sits at 0.058 H = row
    67, so the first 16 rows are background at every azimuth; the BOTTOM corners are
    not safe, because at this framing the shoulders run off both bottom corners in
    several views and a median taken over a half-subject sample lands nowhere."""
    import numpy as np

    k = 16
    corners = np.concatenate([a[:k, :k].reshape(-1, 3), a[:k, -k:].reshape(-1, 3)])
    bg = float(np.median(corners.max(axis=1)))
    return a.max(axis=2) > bg + margin, bg


def _bl_coverage(path):
    """Subject coverage as a fraction of frame. Ground truth from the background mask,
    unlike the segmenter number quoted for the real cells (see difference D7)."""
    m, _ = _bl_subject_mask(_bl_read_rgb(path))
    return float(m.mean())
