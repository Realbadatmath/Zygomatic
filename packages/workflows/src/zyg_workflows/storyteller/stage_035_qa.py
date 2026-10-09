# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3.5, part 2 — is this frame good enough to ship?

The three QA closures of the old `with _GPU_PIPELINE_LOCK:` block, hoisted:
``_st_mediapipe_hand_qa`` → :func:`mediapipe_hand_qa`, ``_st_scene_quality_ok``
→ :func:`scene_quality_ok`, ``_st_scene_quality_reason`` →
:func:`scene_quality_reason`. None of them rebound anything, so they needed no
``nonlocal``; what they closed over — ``_qc_style_st``, ``_st_lora_active``,
``_ssh_st`` and the one-shot ``_hand_qc_style_skip`` list — is read off ``ctx``
and ``st`` instead.

``_st_mediapipe_hand_qa`` was also *passed* to ``scene_still_helpers`` as
``hand_qa_fn=``. A two-extra-argument module function cannot be, so
``stage_035_image_generation`` binds it once with ``functools.partial`` and
parks the result on ``st._hand_qa_fn``; every call site — here, the scene loop
and Stage 3.6 — uses that single object, exactly as they all used the one
closure. See ``SPLIT_LOG.md``."""

from __future__ import annotations

import logging as _zyg_logging

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')


def mediapipe_hand_qa(ctx, st, image_path: str) -> tuple:
    """Hand QA — (score, issues). score=None means UNAVAILABLE.

    2026-07-24 rebuild: the old mediapipe-solutions body was
    dead code (API removed in mediapipe 0.10.35 → AttributeError
    → blanket except returned a PERFECT 1.0 for every frame of
    every run; 6278904c shipped 12 defective frames at
    'hand=1.00'). Now: YOLO hand crops judged by the local
    Ollama vision model (hand_qc_service); callers treat None
    as unknown, never as clean. Stylized (toon/anime) characters
    skip hand QC — the judge is calibrated on photoreal hands.
    """
    _animated_render = ctx._animated_render
    _restyle_render = ctx._restyle_render
    char_id = ctx.char_id
    _hand_qc_style_skip = st._hand_qc_style_skip
    if not _hand_qc_style_skip:
        _sk_hq = _animated_render or _restyle_render  # 3D-toon OR painterly arcane
        try:
            from zyg_workflows.char_state_service import _char_render_style as _crs_hq
            from zyg_workflows.char_state_service import _char_params_from_bible as _cpfb_hq

            _p_hq, _i_hq = _cpfb_hq(char_id)
            _rs_hq = (_crs_hq(_p_hq, _i_hq) or 'photorealistic').lower()
            _sk_hq = _sk_hq or any(
                t in _rs_hq for t in ('toon', 'anime', 'cartoon', 'animat', 'illustrat', 'comic', 'drawn')
            )
        except Exception as _exc:
            _zyg_log.warning('render-style lookup failed, the hand-QC style skip keeps its default: %s', _exc)
        _hand_qc_style_skip.append(_sk_hq)
    if _hand_qc_style_skip[0]:
        return None, ['hand QC skipped (stylized render)']
    try:
        from zyg_workflows import hand_qc_service as _hqs_st

        return _hqs_st.hand_quality(image_path)
    except Exception as _hq_e:
        return None, [f'hand QC unavailable ({_hq_e!r})']


def scene_quality_ok(ctx, st, img_path: str) -> bool:
    """Brightness + sharpness + MediaPipe hand anatomy thresholds."""
    _log = ctx._log
    _qc_style_st = st._qc_style_st
    _ssh_st = st._ssh_st
    _ok_q, _reason = _ssh_st.scene_quality_check(
        img_path,
        _qc_style_st,
        hand_qa_fn=st._hand_qa_fn,
        lora_active=st._st_lora_active,
    )
    if not _ok_q:
        _hand_s, _hand_iss = st._hand_qa_fn(img_path)
        _ssh_st.log_scene_qc_failure(
            lambda m: _log('INFO', 'Stage 3.5', m),
            img_path,
            _qc_style_st,
            _reason,
            hand_score=_hand_s,
            hand_issues=_hand_iss,
        )
    return _ok_q


def scene_quality_reason(ctx, st, img_path: str) -> str:
    _ok_q, _reason = st._ssh_st.scene_quality_check(
        img_path,
        st._qc_style_st,
        hand_qa_fn=st._hand_qa_fn,
        lora_active=st._st_lora_active,
    )
    return 'ok' if _ok_q else _reason
