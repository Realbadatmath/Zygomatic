# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Melody following: does the take follow the composed tune, against a cross-song null.

Moved verbatim out of the old single-file kids_music_service.py (lines 2220-2321).
"""

from __future__ import annotations

import json
import os

from zyg_workflows.kids_music_service.base import (
    HERE,
    _log_noop,
    _zyg_log,
)

# ── Melody following ─────────────────────────────────────────────────────────


def _better_take(cand, best):
    """Is `cand` a better take than `best`? Lower severity wins, EXCEPT that a
    take which lost the composed melody can never beat one that kept it.

    The denoise ladder buys clarity with melody adherence, so without this a
    rung that scored well on severity could ship a song that no longer follows
    its own score — and `delivery.melody_followed` is a claim the GUI draws a
    piano roll on. `followed` is None when chroma could not be measured, which
    counts as kept: an unmeasured check must not silently demote a take.
    """
    if best is None:
        return True
    cf = cand.get('followed') is not False
    bf = best.get('followed') is not False
    if cf != bf:
        return cf
    return cand['sev'] < best['sev']


def chroma_follow(audio_path, plan, null_plans, log_fn=None):
    """Does this audio actually follow the COMPOSED melody? Measured, not asserted.

    `delivery.melody_followed` was going to be a hardcoded False — right today,
    but a constant is exactly the kind of claim this audit exists to catch, and
    it would have gone silently wrong the moment melody conditioning was wired.
    So it is measured, against a cross-song null, every run.

    Two pieces of tonal music in the same key correlate well above zero by
    construction, which is why the null is the whole test: z, not similarity.
    """
    log_fn = log_fn or _log_noop
    out = {'z': None, 'similarity': None, 'followed': None, 'nulls': 0}
    try:
        sys_path_added = False
        import sys as _sys

        sdir = os.path.join(HERE, 'scripts')
        if sdir not in _sys.path:
            _sys.path.insert(0, sdir)
            sys_path_added = True
        import kidsmusic_chroma_test as CT

        A = CT.audio_chroma(audio_path)
        n = A.shape[1]
        sim, lag = CT.similarity(A, CT.plan_chroma(plan, n))
        sims = []
        for np_ in null_plans:
            try:
                with open(np_, encoding='utf-8') as fh:
                    sims.append(CT.similarity(A, CT.plan_chroma(json.load(fh), n))[0])
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('null plan %s skipped in the similarity baseline: %s', np_, _exc)
                continue
        out.update({'similarity': round(sim, 4), 'lag_s': round(lag * CT.HOP / CT.SR, 2), 'nulls': len(sims)})
        if len(sims) >= 2:
            import statistics as _st

            mu = _st.fmean(sims)
            sd = _st.pstdev(sims) or 1e-9
            out['null_mean'] = round(mu, 4)
            out['z'] = round((sim - mu) / sd, 2)
            out['followed'] = bool(out['z'] > 2.0)
        if sys_path_added:
            _sys.path.remove(sdir)
    except Exception as e:  # noqa: BLE001 — a measurement
        out['error'] = f'{type(e).__name__}: {e}'[:160]
        log_fn(f'chroma: unmeasured ({type(e).__name__})')
    return out


def _null_plans(limit=8, exclude_dir=None):
    """OTHER songs' plans, for the cross-song null.

    `exclude_dir` matters and is not optional in practice: run() writes
    song.json before the ACE leg runs, so a naive glob puts the song's OWN plan
    into its own null. Measured consequence on job c363521cb5e0 — the self-plan
    scored like the real match, dragged the null mean up and the spread with it,
    and a take that had in fact followed the melody reported z 1.69 and
    "does NOT follow". A null contaminated with the signal is not a null.

    8 rather than 4, too: z is a ratio to the null's standard deviation, and an
    sd estimated from four points is noisy enough to move the verdict on its own.
    """
    root = os.path.join(HERE, 'output', 'kidsmusic')
    skip = os.path.realpath(exclude_dir) if exclude_dir else None
    out = []
    try:
        for d in sorted(os.listdir(root)):
            dd = os.path.realpath(os.path.join(root, d))
            if skip and dd == skip:
                continue
            p = os.path.join(dd, 'song.json')
            if os.path.isfile(p):
                out.append(p)
    except OSError as _exc:
        _zyg_log.debug('null corpus scan of %s skipped: %s', root, _exc)
    return out[:limit]
