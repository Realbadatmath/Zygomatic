# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""prop_camera.py — recover the shot camera from a known prop quad (2026-08-01).

WHY THIS EXISTS — THE HOMOGRAPHY ROUTE FAILED, AND IT FAILED INSTRUCTIVELY.

The first attempt rendered the book from a convenient viewpoint and then warped the plate
by the homography taking the rendered page's four corners onto the shot's `page_quad`.
That aligns the PAGE perfectly and everything else catastrophically: a homography fitted
between two quite different viewpoints diverges away from the fitted quad, so the rest of
the book (left page, text blocks) sheared into a wedge covering the left half of the
frame — 18.5% of the frame painted, for a book whose own box is 7.3%. Matching one quad
does not constrain the geometry around it unless the two cameras already agree.

So: don't fudge the projection, RECOVER it. The page is a planar quad of known object-space
dimensions and we know where it lands in the image, which is exactly a planar PnP problem.
Solving it gives the camera pose the original plate was (effectively) shot from, and
rendering the book from THAT camera puts every part of the book — not just the page — in
correct perspective, with no warp step at all.

The plate came out of a generator, so there is no true focal length to look up. f is
therefore a parameter, defaulted to 0.85*width (a normal-ish lens) and reported in the
result so a later caller can sweep it. What matters for our purpose is not metric truth
but that the book sits convincingly on the table where the page already is; reprojection
error against the four known corners is returned so that claim is checkable rather than
asserted.

COORDINATE CONVENTIONS — the classic trap. OpenCV cameras look down +Z with +Y DOWN;
Blender cameras look down -Z with +Y UP. The basis flip (diag(1,-1,-1)) is applied here,
once, so the Blender script receives a location and an XYZ Euler it can use directly.
"""

import math


def _log_noop(_m):
    pass


def solve_camera(page_quad_frac, size, page_pts_3d, focal_px=None, log_fn=None):
    """-> dict(location, rotation_euler_xyz, lens_mm, sensor_mm, reproj_px) or None.

    page_quad_frac : the shot's page_quad, 4 fractional (x,y), order TL,TR,BR,BL
    page_pts_3d    : the SAME four corners in the book's object space, same order
    """
    log = log_fn or _log_noop
    try:
        import cv2
        import numpy as np
    except Exception as e:
        log(f'[prop-cam] cv2/numpy unavailable ({e})')
        return None
    try:
        W, H = int(size[0]), int(size[1])
        img = np.array([[float(x) * W, float(y) * H] for x, y in page_quad_frac], dtype=np.float64)
        obj = np.array([[float(a) for a in p] for p in page_pts_3d], dtype=np.float64)
        if img.shape != (4, 2) or obj.shape != (4, 3):
            log('[prop-cam] need exactly 4 image points and 4 object points')
            return None
        f = float(focal_px) if focal_px else 0.85 * W
        K = np.array([[f, 0, W / 2.0], [0, f, H / 2.0], [0, 0, 1]], dtype=np.float64)
        dist = np.zeros((4, 1))
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_IPPE)
        if not ok:
            log('[prop-cam] solvePnP failed')
            return None
        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
        err = float(np.linalg.norm(proj.reshape(-1, 2) - img, axis=1).mean())

        R, _ = cv2.Rodrigues(rvec)
        # world->camera is (R, t); camera pose in world is (R^T, -R^T t)
        R_wc = R.T
        t_wc = (-R.T @ tvec).reshape(3)
        # OpenCV cam basis (+X right, +Y down, +Z fwd) -> Blender (+X right, +Y up, -Z fwd)
        flip = np.diag([1.0, -1.0, -1.0])
        R_bl = R_wc @ flip

        # XYZ Euler from the rotation matrix (Blender's default order)
        sy = math.sqrt(R_bl[0, 0] ** 2 + R_bl[1, 0] ** 2)
        if sy > 1e-6:
            rx = math.atan2(R_bl[2, 1], R_bl[2, 2])
            ry = math.atan2(-R_bl[2, 0], sy)
            rz = math.atan2(R_bl[1, 0], R_bl[0, 0])
        else:  # gimbal-locked
            rx = math.atan2(-R_bl[1, 2], R_bl[1, 1])
            ry = math.atan2(-R_bl[2, 0], sy)
            rz = 0.0
        sensor = 36.0
        out = {
            'location': [float(v) for v in t_wc],
            'rotation_euler_xyz': [rx, ry, rz],
            'lens_mm': float(f * sensor / W),
            'sensor_mm': sensor,
            'focal_px': f,
            'reproj_px': err,
            'size': [W, H],
        }
        log(
            f'[prop-cam] solved: loc=({t_wc[0]:.2f},{t_wc[1]:.2f},{t_wc[2]:.2f}) '
            f'rot=({math.degrees(rx):.1f}°,{math.degrees(ry):.1f}°,{math.degrees(rz):.1f}°) '
            f'lens={out["lens_mm"]:.1f}mm  mean reprojection error {err:.2f}px'
        )
        return out
    except Exception as e:
        log(f'[prop-cam] solve FAILED ({e})')
        return None


# The book's right-page corners in object space. MUST stay in step with
# prop_mesh/book_render.py's _page_top(+1) — same order: inner-far, outer-far,
# outer-near, inner-near, which is TL, TR, BR, BL as the shot sees it.
def book_page_points(page_w=0.95, page_l=0.66, thick=0.11, open_a=0.30):
    rise = page_w * math.sin(open_a)
    z0 = thick
    return [[0.0, +page_l, z0], [page_w, +page_l, z0 + rise], [page_w, -page_l, z0 + rise], [0.0, -page_l, z0]]


def solve_camera_auto(page_quad_frac, size, thick=0.11, open_a=0.30, page_w=0.95, focal_px=None, log_fn=None):
    """solve_camera, but SEARCHES the two things that were guessed and shouldn't be.

    A first hand-set attempt (page 0.95 x 1.32, corners assumed TL=inner-far) reprojected
    at 11.5px mean error on a 4-point planar fit that should be near-exact. Two unknowns
    caused it, and neither is knowable a priori from a generated plate:

      * the page's ASPECT — how long the page is along the spine relative to its width.
        A ledger is not square and the plate's page is seen at a grazing angle, so the
        wrong aspect forces the solver into an implausible pose to explain the quad.
      * which OBJECT corner is which IMAGE corner. The book's orientation on the table
        (spine toward camera, or across it) decides this, and the shot is a render, not
        a set we measured.

    So page length and focal are searched. THE CORNER CORRESPONDENCE IS NOT, and that
    distinction cost a debugging round: rotating the correspondence DOES lower reprojection
    error, but rotations 1-3 describe a book that is mirrored or laid across the table.
    object[0] and object[3] are the page's spine edge, so they must land on the shot quad's
    LEFT edge (TL/BL) — the right page's spine is to its left. A free search happily
    returned corner_rotation=2 at 6.42px: a lower error, and a book rendered back-to-front.
    Fixed at 0.

    Focal is genuinely unknown (the plate is generated, not shot) so it is swept, and the
    camera is required to sit ABOVE the table, which rejects the mirrored-through-the-floor
    poses that also fit four coplanar points.
    """
    log = log_fn or _log_noop
    best = None
    for i in range(29):
        page_l = 0.20 + i * 0.05
        for fmul in (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6):
            pts = book_page_points(page_w=page_w, page_l=page_l, thick=thick, open_a=open_a)
            r = solve_camera(page_quad_frac, size, pts, focal_px=(focal_px or fmul * float(size[0])), log_fn=None)
            if not r or r['location'][2] <= 0.2:
                continue
            if best is None or r['reproj_px'] < best['reproj_px']:
                best = dict(r, page_l=page_l, corner_rotation=0, page_w=page_w, focal_mult=fmul)
            if focal_px:
                break  # caller pinned f — do not sweep it
    if best is None:
        log('[prop-cam] auto-solve found no valid pose above the table')
        return None
    log(
        f'[prop-cam] AUTO best: page_l={best["page_l"]:.2f} (w={page_w}) '
        f'spine-left (corner_rotation fixed 0) -> reprojection {best["reproj_px"]:.2f}px '
        f'lens {best["lens_mm"]:.1f}mm'
    )
    return best


if __name__ == '__main__':  # the CLI lives in prop_camera_cli
    from zyg_workflows.prop_camera_cli import main as _cli_main

    raise SystemExit(_cli_main())
