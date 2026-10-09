# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small linear-algebra helpers shared by the placement solvers."""

import math

from mathutils import Matrix, Quaternion, Vector

from .constants import AXIS_SCALE_CLAMP

# --------------------------------------------------------------------------
# small linear-algebra helpers
# --------------------------------------------------------------------------


def _outer(v: Vector) -> Matrix:
    return Matrix([[v[i] * v[j] for j in range(3)] for i in range(3)])


def _affine(basis: Matrix, translation: Vector) -> Matrix:
    m = basis.to_4x4()
    m.translation = translation
    return m


def _rotation_between(a: Vector, b: Vector) -> Matrix:
    """Minimal rotation taking direction a onto direction b."""
    a = a.normalized()
    b = b.normalized()
    d = max(-1.0, min(1.0, a.dot(b)))
    if d > 1.0 - 1e-9:
        return Matrix.Identity(3)
    if d < -1.0 + 1e-9:
        axis = a.cross(Vector((0.0, 0.0, 1.0)))
        if axis.length < 1e-6:
            axis = a.cross(Vector((0.0, 1.0, 0.0)))
        return Quaternion(axis.normalized(), math.pi).to_matrix()
    axis = a.cross(b)
    return Quaternion(axis.normalized(), math.acos(d)).to_matrix()


def _frame(u: Vector, w: Vector):
    """Orthonormal basis with column 0 along u and column 1 nearest w."""
    x = u.normalized()
    y = w - x * w.dot(x)
    y = y.normalized() if y.length > 1e-9 else x.orthogonal().normalized()
    return Matrix((x, y, x.cross(y))).transposed()


def _segment_matrix(j_s: Vector, a_s: Vector, head_r: Vector, a_r: Vector, s: float, roll=None):
    """v' = head_r + R . (K . (s . (v - J_s))), K along the axis only.

    ``roll`` is an optional (w_s, w_r) pair of secondary directions.  A minimal
    rotation between two axes leaves the spin about them free, which is
    invisible on a long bone and glaring on a hand: without it the metacarpal
    fan lands edge-on and the thumb points the wrong way.  Given the pair, R is
    the full frame rotation instead.

    Returns (matrix, axis_scale_raw, axis_scale_used).
    """
    raw = a_r.length / max(1e-9, s * a_s.length)
    k = max(AXIS_SCALE_CLAMP[0], min(AXIS_SCALE_CLAMP[1], raw))
    axis = a_s.normalized()
    k_mat = Matrix.Identity(3) + _outer(axis) * (k - 1.0)
    if roll is None:
        rot = _rotation_between(a_s, a_r)
    else:
        rot = _frame(a_r, roll[1]) @ _frame(a_s, roll[0]).transposed()
    basis = rot @ k_mat @ (Matrix.Identity(3) * s)
    return _affine(basis, head_r - basis @ j_s), raw, k
