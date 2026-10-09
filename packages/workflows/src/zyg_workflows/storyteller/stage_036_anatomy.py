# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3.6 of the storyteller pipeline — anatomy repair (hand inpainting).

The ``if _st_image_meta:`` block that followed the Stage 3.5 scene loop, moved
as it stands into :func:`stage_036_anatomy_repair`. It is a *stage* in the
sense the split cares about — it has its own ``_update_stage('Stage 3.6 …')``
call and its own log channel — but not a ``stage_<nn>(ctx)`` one: everything it
reads (the image-meta list it rewrites in place, the hand-QA callable, the
``scene_still_helpers`` handle) belongs to Stage 3.5's
:class:`~zyg_workflows.storyteller.context.ImageGenState`, so it takes ``st``
too and the driver never sees it — ``stage_035_image_generation`` calls it from
inside the same ``with _GPU_PIPELINE_LOCK:`` / ``try:`` it always ran in.

See ``SPLIT_LOG.md``."""

from __future__ import annotations

import logging as _zyg_logging
import os

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')


def stage_036_anatomy_repair(ctx, st) -> None:
    """Give every below-threshold hand one more ComfyUI HandFixer attempt."""
    _check_stop = ctx._check_stop
    _log = ctx._log
    _update_stage = ctx._update_stage
    pipeline_state = ctx.pipeline_state
    _ssh_st = st._ssh_st
    _st_image_meta = st._st_image_meta

    # ── Stage 3.6: Anatomy Repair (hand inpainting, 2nd chance) ─────
    # 2026-07-24 r4 rebuild: routed through the rebuilt ComfyUI
    # HandFixer (verified masks + harm-revert) instead of
    # flux_fill_service — that path used the removed mediapipe
    # solutions API for masks and loaded a second 20GB fill model
    # in-process mid-pipeline. Scenes whose hand score stayed
    # below threshold after the generation loop get ONE more
    # fixer attempt with a different seed, then are re-scored.
    if _st_image_meta:
        try:
            _update_stage('Stage 3.6 — Anatomy Repair', 58)
            from zyg_workflows import comfy_generation_service as _cgs_ar

            # Fallback/tinted frames are not repair candidates —
            # inpainting a brightness-tinted reference still is
            # wasted GPU time (r4 review finding).
            _fb_set_ar = set(pipeline_state.get('_st_fallback_scenes') or [])
            _ar_cands = [
                _am
                for _am in _st_image_meta
                if _am.get('qa_score') is not None
                and _am['qa_score'] < 0.65
                and (_am.get('index', -1) + 1) not in _fb_set_ar
                and _am.get('path')
                and os.path.isfile(_am['path'])
            ]
            if not _ar_cands:
                _log('INFO', 'Stage 3.6', 'Anatomy repair: no scenes below hand-QC threshold')
            _n_repaired_st = 0
            for _am in _ar_cands:
                _check_stop()
                _ar_ok = _cgs_ar.apply_hand_fixer_pass(
                    _am['path'],
                    _am.get('prompt', ''),
                    seed=int(
                        _ssh_st.scene_generation_seed(
                            _am['path'],
                            scene_index=_am.get('index', 0),
                            attempt=7,
                        )
                    ),
                    log_fn=lambda m: _log('INFO', 'Stage 3.6', m),
                    character_package=pipeline_state.get('character_bible'),
                )
                if _ar_ok:
                    _new_s, _new_iss = st._hand_qa_fn(_am['path'])
                    if _new_s is not None:
                        _log(
                            'INFO',
                            'Stage 3.6',
                            f'Scene {_am.get("index", -1) + 1}: hand score {_am["qa_score"]:.2f} → {_new_s:.2f}',
                        )
                        _am['qa_score'] = round(_new_s, 3)
                        _am['qa_issues'] = _new_iss
                    _am['repair_pass'] = 'comfy_hand_fixer'  # noqa: S105  which repair stage touched the scene, not a secret
                    _n_repaired_st += 1
            if _ar_cands:
                _log(
                    'INFO',
                    'Stage 3.6',
                    f'Anatomy repair complete — {_n_repaired_st}/{len(_ar_cands)} low-scoring scene(s) re-fixed',
                )
            # Informational registry: scenes whose FINAL hand score
            # stays flagged (<0.65). Surfaces in degraded reasons
            # and episode badges but does NOT count toward the
            # failure threshold (single imperfect hands are normal
            # for AI video; blobs already fail strict QC upstream).
            _hand_flagged = sorted(
                _am.get('index', -1) + 1
                for _am in _st_image_meta
                if _am.get('qa_score') is not None and _am['qa_score'] < 0.65
            )
            if _hand_flagged:
                pipeline_state['_st_hand_flagged_scenes'] = _hand_flagged
        except Exception as _ffs_st_e:
            # r4 review fix: the user-halt RuntimeError from
            # _check_stop must not be swallowed as a repair error.
            if 'stopped by user' in str(_ffs_st_e).lower():
                raise
            _log('WARNING', 'Stage 3.6', f'Anatomy repair failed (non-fatal): {_ffs_st_e}')
