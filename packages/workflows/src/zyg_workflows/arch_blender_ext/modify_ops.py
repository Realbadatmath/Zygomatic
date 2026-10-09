# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""modify_ops — Blender geometry for the `sweep` kind that Follow me creates.

Local frame (arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. `p.pts` is a list of studio-local [x, z] metres, so a path point
(x, z) sits at Blender (x, -z). One box per leg, w across the path and h up,
butt-jointed — the same arithmetic as AR_EXT.geom.sweep in arch_ext/modify_ops.js.
"""

from __future__ import annotations

import math
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _pts(v):
    out = []
    if isinstance(v, (list, tuple)):
        for a in v:
            if isinstance(a, (list, tuple)) and len(a) >= 2:
                try:
                    x, z = float(a[0]), float(a[1])
                except (TypeError, ValueError) as _exc:
                    _zyg_log.debug('non-numeric point %r skipped: %s', a, _exc)
                    continue
                if math.isfinite(x) and math.isfinite(z):
                    out.append((x, z))
    return out if len(out) >= 2 else [(0.0, 0.0), (1.0, 0.0)]


def _leg(bm, a, b, w, h):
    """One box of section w x h from studio point a to studio point b."""
    ax, ay = a[0], -a[1]  # studio (x, z) -> blender (x, y)
    bx, by = b[0], -b[1]
    dx, dy = bx - ax, by - ay
    ln = math.hypot(dx, dy)
    if ln < 1e-4:
        return False
    ux, uy = dx / ln, dy / ln
    nx, ny = -uy * w / 2.0, ux * w / 2.0  # left normal, half width
    base = [(ax + nx, ay + ny), (ax - nx, ay - ny), (bx - nx, by - ny), (bx + nx, by + ny)]
    vs = [bm.verts.new((px, py, 0.0)) for px, py in base]
    vs += [bm.verts.new((px, py, h)) for px, py in base]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([vs[i] for i in idx])
    return True


def build_sweep(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    pts = _pts(p.get('pts'))
    w, h = max(0.005, abs(N('w', 0.3))), max(0.005, abs(N('h', 0.3)))
    closed = bool(p.get('closed'))
    n = len(pts)
    made = 0
    for i in range(n if closed else n - 1):
        if _leg(bm, pts[i], pts[(i + 1) % n], w, h):
            made += 1
    if not made:
        _leg(bm, (0.0, 0.0), (0.05, 0.0), w, h)
    bm.normal_update()
    return ('', [])


BUILDERS = {'sweep': build_sweep}
