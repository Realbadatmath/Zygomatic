# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""passes_io.py — read a Blender pass set into numpy. Pure python; no bpy (2026-08-04).

A "pass set" is one directory written by prop_mesh/pass_lib.render_set():

    <dir>/rgb.png      beauty, RGBA, colour-managed
    <dir>/depth.exr    camera-space depth in metres, 32-bit float
    <dir>/normal.exr   surface normal, 32-bit float, components in [-1, 1]
    <dir>/index.exr    object pass_index as a float, 0 where nothing was hit

THE ONE TRAP: Blender writes background depth as ~1e10, not 0 or NaN. A single unmasked
background pixel takes any mean, max or percentile to infinity — silently, because the
number is finite. `load_set` builds `valid` once here so no caller has to remember, and
every statistic in gate.py is taken over `valid` only.

cv2 reads OpenEXR losslessly (verified round-trip, max abs error 0.0) but only when
OPENCV_IO_ENABLE_OPENEXR is set BEFORE cv2 is imported, so it is set at module import
time, above the cv2 import, and not left to the caller's environment.
"""

import os

os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# anything at or beyond this is sky/background, not a surface
DEPTH_SKY = 1e9


class PassSet:
    """One rendered configuration: beauty + the three data passes, already masked."""

    def __init__(self, path, rgb, depth, normal, index):
        self.path = path
        self.rgb = rgb  # (H,W,4) uint8 or None
        self.depth = depth  # (H,W) float32 metres, sky already set to nan
        self.normal = normal  # (H,W,3) float32 or None
        self.index = index  # (H,W) int32
        self.valid = np.isfinite(depth)
        self.h, self.w = depth.shape

    @property
    def size(self):
        return self.w, self.h

    def mask(self, idx):
        """Boolean mask of one object index — surfaces only, never background."""
        return (self.index == int(idx)) & self.valid

    def depth_mm(self):
        return self.depth * 1000.0

    def __repr__(self):
        ids = sorted(int(v) for v in np.unique(self.index) if v > 0)
        return '<PassSet %s %dx%d ids=%s>' % (os.path.basename(self.path), self.w, self.h, ids)


def _exr(path, channels=1):
    if not os.path.exists(path):
        return None
    a = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if a is None:
        return None
    a = a.astype(np.float32)
    if a.ndim == 3 and channels == 1:
        a = a[:, :, 0]
    return a


def load_paths(depth_path, index_path=None, normal_path=None, rgb_path=None, label=None):
    """Load a pass set from EXPLICIT file paths.

    load_set() assumes pass_lib.render_set()'s directory layout (depth.exr / normal.exr /
    index.exr in one folder per view). prop_mesh/*_sheet.py writes a DIFFERENT layout —
    one flat passes/ folder holding <view>_<kind>_0001.exr for every view — so a sheet's
    passes were unreadable through this module even though the files are identical in
    kind. Splitting the naming convention out from the loading logic lets both layouts
    use the same masking discipline instead of one of them re-implementing it and
    forgetting the 1e10 sky sentinel."""
    depth = _exr(depth_path)
    if depth is None:
        raise FileNotFoundError('no depth EXR at %s' % depth_path)
    depth = depth.copy()
    depth[depth >= DEPTH_SKY] = np.nan

    index = _exr(index_path) if index_path else None
    index = np.zeros_like(depth, dtype=np.int32) if index is None else np.rint(index).astype(np.int32)

    # A 2-D normal plane means the EXR carried X/Y/Z-named channels and cv2 could only
    # resolve one of them; that is unusable rather than wrong, so the normal checks are
    # dropped and the depth checks still run. Never silently treat one component as three.
    nrm = None
    if normal_path and os.path.exists(normal_path):
        nrm = cv2.imread(normal_path, cv2.IMREAD_UNCHANGED)
        if nrm is not None and nrm.ndim == 3 and nrm.shape[2] >= 3:
            nrm = nrm.astype(np.float32)[:, :, :3][:, :, ::-1]  # cv2 gives BGR
        else:
            nrm = None

    rgb = None
    if rgb_path and os.path.exists(rgb_path):
        rgb = cv2.imread(rgb_path, cv2.IMREAD_UNCHANGED)
        if rgb is not None and rgb.ndim == 3:
            rgb = rgb[:, :, [2, 1, 0] + ([3] if rgb.shape[2] == 4 else [])]

    return PassSet(label or os.path.dirname(depth_path), rgb, depth, nrm, index)


def load_set(path):
    """Load a pass-set directory. Raises if depth is missing — nothing works without it."""
    return load_paths(
        os.path.join(path, 'depth.exr'),
        os.path.join(path, 'index.exr'),
        os.path.join(path, 'normal.exr'),
        os.path.join(path, 'rgb.png'),
        label=path,
    )
