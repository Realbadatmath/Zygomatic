# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Movement Studio anatomy proof — ``run``: the eleven checks, in order."""

from . import run_ecorche as _ec
from . import run_skeleton as _sk
from .constants import _require


def run(pw, width, height, shoot):
    """Drive the eleven anatomy checks against one headless page, in order.

    *pw* is an open ``sync_playwright()``; *width* x *height* is the operator's
    67 %-zoom viewport; *shoot* writes the three screenshots. Raises
    AssertionError on the first check that fails, and returns the ready probe,
    the drawn counts, the skeleton probe and the écorché probe —
    ``(st, c, sk, p)``, which the CLI prints its PASS line from.
    """
    errs = []
    br, pg = _sk.open_page(pw, width, height, errs)

    # ── 1. it solved, off a measured body ────────────────────────────────
    st = _sk.check_measured_body(pg)

    # ── 2./2b. the joint set is no longer the rig's, and it is anatomical ─
    _sk.check_joint_cloud(pg, st)

    # ══ 3. THE SKELETON MESH ═════════════════════════════════════════════
    sk = _sk.check_skeleton_mesh(pg)

    # ══ 4. THE ÉCORCHÉ ═══════════════════════════════════════════════════
    p = _ec.check_ecorche(pg, shoot)

    # ── 5./6., 7., 8., 9. what is drawn, the skin, the clip, the cost ────
    c = _ec.check_drawn_and_tracking(pg, shoot)

    # ── 10./10b. THE VIEW MENU, AND THE HALVES HOLD ──────────────────────
    _ec.check_view_menu(pg)

    if shoot:
        _ec.shoot_hand(pg)

    # ── 11. no page error ────────────────────────────────────────────────
    _require(not errs, 'page errors:\n  ' + '\n  '.join(errs[:8]))
    br.close()
    return st, c, sk, p
