#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — ``stage_bake``'s exposure pass, extracted 2026-10-09.

One gain per channel per view, matched to the view it was rendered from over
the texels both see squarely; see :func:`match_view_gains` for why a mirror
pair shares one gain."""

from __future__ import annotations


import numpy as np

from zyg_workflows.char_photoreal.constants import (
    GAIN_MIN_SHARED,
    GAIN_MIN_SHARED_HAND,
    GAIN_OF,
    HAND_RADIUS,
)
from zyg_workflows.char_photoreal.atlas import (
    _partner,
)


def gain_ratio(vid, parent, refs, Pt, hand_c):
    """Median per-channel ratio parent/view over the texels both see squarely.

    Returns ``(ratio, n)``; ``ratio`` is None when fewer than
    GAIN_MIN_SHARED texels (GAIN_MIN_SHARED_HAND for a hand view) qualify.
    """
    col, w, cosang = refs[vid][:3]
    pcol, pw, pcos = refs[parent][:3]
    both = (w > 0) & (pw > 0) & (cosang > 0.5) & (pcos > 0.5)
    if vid in hand_c:
        # a hand photo is matched over the WRIST band (2026-09-22): the
        # texels it shares with the profile are mostly the thigh and the
        # forearm, and its gain must make the hand continuous with the
        # forearm where the two hand over, not with the thigh
        d = np.linalg.norm(Pt - hand_c[vid], axis=1)
        both &= (d > HAND_RADIUS[0] - 0.03) & (d < HAND_RADIUS[1] + 0.03)
    n = int(both.sum())
    if n < (GAIN_MIN_SHARED_HAND if vid in hand_c else GAIN_MIN_SHARED):
        return None, n
    r = np.clip(pcol[both] / np.maximum(col[both], 1.0), 0.3, 3.0)
    return np.median(r, axis=0), n


def match_view_gains(order, refs, per_view, geom, anchors, log) -> None:
    """Scale every view's colour by the gain that matches it to its parent.

    EXPOSURE, pass 2. One scalar per channel per view, matched to the view it
    was rendered from (GAIN_OF) over the texels both see squarely. Measured
    twice on 2026-09-20: against body_front alone the back family shares
    nothing (unmatched); chained view-by-view the two mirror chains DIVERGE
    (body_bl 0.5, body_br 2.0 — two near-identical photos), because the ratio
    between neighbours is mostly the photos' own image-left lighting, whose
    sign flips between the two sides of the body. So a mirror PAIR gets one
    gain: the geometric mean of the two chains' ratios, which cancels that
    bias to first order. A self-partner view (az 0/180, up/down) is matched to
    its parent AND the parent's mirror. Mutates ``refs`` and ``per_view``.
    """
    cams, Pt, hand_c = geom.cams, geom.Pt, anchors.hand_c
    done_gain = set()
    for vid in order:
        if vid in done_gain or vid not in refs:
            continue
        pvid = _partner(vid, cams['views'])
        group = [vid] if pvid == vid or pvid not in refs else [vid, pvid]
        if abs(((cams['views'][vid]['az'] + 180) % 360) - 180) <= 10:
            group = [vid]  # a straight-on view has no side bias to cancel
        logs, shared = [], 0
        for g in group:
            par = GAIN_OF.get(g)
            parents = [par] if par in refs else []
            if len(group) == 1 and par in refs:
                pp = _partner(par, cams['views'])
                if pp != par and pp in refs:
                    parents.append(pp)
            for par in parents:
                r, n = gain_ratio(g, par, refs, Pt, hand_c)
                if r is not None:
                    logs.append(np.log(r))
                    shared += n
        if logs:
            gain = np.exp(np.mean(logs, axis=0))
        else:
            # too little squarely-shared skin for a trustworthy ratio
            # (2026-09-22: head_back x head_left shared 11 785 texels once
            # the near-black shadow side of each photo was rejected, all of
            # them on the shadow's edge, and the ratio said 0.72): the view
            # was RENDERED from its parent as appearance reference, so it
            # inherits the parent's gain instead
            par = GAIN_OF.get(vid, '')
            gain = np.array(per_view.get(par, {}).get('gain', [1.0, 1.0, 1.0]), np.float64)
            log(f"[bake] gain {vid}: only {shared} shared texels, inheriting {par}'s gain")
        gain = np.clip(gain, 0.5, 2.0)
        for g in group:
            refs[g][0] = np.clip(refs[g][0] * gain.astype(np.float32), 0, 255)
            done_gain.add(g)
            per_view[g].update(
                {'gain': [round(float(x), 3) for x in gain], 'gain_parent': GAIN_OF.get(g, ''), 'shared': int(shared)}
            )
        log(f'[bake] gain {"+".join(group):23s} {np.round(gain, 3).tolist()}  shared {shared}')
    # NO local gain field (tried 2026-09-22, twice): a 50 mm parent/view
    # ratio field, even taken per mirror pair, compounds down the render
    # chain — each child is matched against a parent the field has already
    # moved — and darkened the atlas by 8 levels (head 128 -> 116, back
    # 152 -> 139). A diagonal view's rim-lit flank is left to the tone
    # blend and the mirror equalisation.
