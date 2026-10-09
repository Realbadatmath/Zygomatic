# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.5 image QA: hand scoring, the typography post-pass and MediaPipe.

Every function here is a nested `def` of `stage_11c_flux_image_loop` in
`stages_37_54`, hoisted to module level with its body unchanged. A closure read
its stage's locals for free; a module-level function cannot, so each one takes
two carriers and re-binds the names it reads in a glue block at the top, in the
head/tail glue style the rest of this package uses:

* `fs` — `FluxLoopState` from `stages_37_54_flux_state`: the per-run FLUX loop
  state (the stats dicts the gates count into, the judge models, the enable
  flags). The dicts and lists are the very objects the stage holds, so a gate
  mutating one is seen by the loop exactly as before;
* `ctx` — the pipeline's `RunContext`: the run inputs and the prologue closures
  (`_log`, `_debug`, `_done`, `_stage_start`, `_gate_receipt`).

A call from one hoisted function to another was a bare closure call, so it is
re-bound as `functools.partial(<fn>, fs, ctx)` and every call site inside the
body is the line the monolith ran.
"""

import functools as _ft
import glob
import logging as _zyg_logging
import os

from zyg_workflows.scholarly import stages_37_54_flux_vlm_gates as _flux_vlm_gates

# The monolith's logger name, not `__name__`, so every debug line of one run
# stays under `zyg_workflows.pipeline_scholarly`.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')


def hand_qa_score(fs, ctx, image_path: str) -> tuple:
    """(score, issues). score None = UNAVAILABLE, never clean.

    A frame with no hands scores 1.0 from the detector, so
    this costs a cheap detect pass on landscapes and only
    pays for VLM crops where hands actually are.
    """
    _HAND_QC_ENABLED = fs._HAND_QC_ENABLED
    _hand_qc_stats = fs._hand_qc_stats
    if not _HAND_QC_ENABLED:
        return None, []
    # Same headroom guard as the typography gate. The judge is
    # an Ollama vision model (~6.6 GB); asking it to load while
    # FLUX holds the card either fails or spills to CPU, and a
    # slow judge inside the per-slot retry loop is what stalled
    # the Catherine run. Below the floor, report UNAVAILABLE —
    # which is the honest answer and never a silent pass.
    _hq_need = float(os.environ.get('ZYG_SCHOLARLY_HAND_QC_MIN_VRAM_GB', '8'))
    try:
        from zyg_workflows.vram_manager import _get_free_vram_gb as _fv_h

        _free_h = float(_fv_h())
    except Exception:
        _free_h = None
    if _free_h is not None and _free_h < _hq_need:
        _hand_qc_stats['unavailable'] += 1
        return None, [f'hand QC unavailable ({_free_h:.1f} GB free < {_hq_need:.0f} GB needed mid-render)']
    try:
        from zyg_workflows import hand_qc_service as _hqs_sch

        _sc, _iss = _hqs_sch.hand_quality(image_path)
    except Exception as _hq_e:
        _hand_qc_stats['unavailable'] += 1
        return None, [f'hand QC unavailable ({_hq_e!r})']
    if _sc is None:
        _hand_qc_stats['unavailable'] += 1
    else:
        _hand_qc_stats['checked'] += 1
        if _sc < 1.0:
            _hand_qc_stats['flagged'] += 1
    return _sc, _iss


def typography_post_pass(fs, ctx):
    """Re-run the typography judge once the card is free.

    The in-loop gate has two judges and, in production, neither
    of them can answer:

      * the local Qwen3-VL judge needs 14 GB and Stage 3.5 runs
        with FLUX resident — measured 5.9 GB free — so it
        declines and hands over (correctly: its cpu tier takes
        ~126 s a frame and once stalled a run for 2.5 h);
      * the Anthropic fallback then returned HTTP 400
        "credit balance is too low" on every frame.

    Result: `0 checked, 0 flagged, 3 unreadable`. Nothing was
    ever flagged, so the retry ladder never climbed — and the
    run reported "every slot cleared its gates" and a tidy
    100% convergence. That number was an artifact of a gate
    with no working judge, not evidence about the renders.

    After the FLUX section releases, 36 GB is free and the
    local judge runs at ~2 s a frame with a bbox on every flag
    and no API dependency at all. So the frames get judged
    here, honestly, even when the in-loop pass could not.

    This pass DETECTS and REPORTS; it does not re-render.
    Repair still belongs to the in-loop ladder, which needs a
    verdict at generation time to act on. Slots flagged here
    are named in the log and recorded in
    pipeline_state['typography_post_flags'] so the gap is
    visible rather than assumed away.
    """
    _OCR_TEXT_ENABLED = fs._OCR_TEXT_ENABLED
    _VLM_TEXT_ENABLED = fs._VLM_TEXT_ENABLED
    _debug = ctx._debug
    _done = ctx._done
    _flux_images_dir = fs._flux_images_dir
    _gate_receipt = ctx._gate_receipt
    _log = ctx._log
    _stage_start = ctx._stage_start
    _vlm_gate_stats = fs._vlm_gate_stats
    _vlm_text_boxes = fs._vlm_text_boxes
    _vlm_text_gate_qwen = _ft.partial(_flux_vlm_gates.vlm_text_gate_qwen, fs, ctx)
    pipeline_state = ctx.pipeline_state
    _tp = {'checked': 0, 'flagged': 0, 'unusable': 0}
    _flags: list = []
    # Snapshot BEFORE the sweep: _vlm_text_gate_qwen bumps
    # _vlm_gate_stats['text_checked'] itself, so reading it
    # afterwards would count this pass's own frames as
    # in-loop verdicts and hide the very gap being measured.
    _in_loop_checked = _vlm_gate_stats['text_checked']
    try:
        _paths = sorted(_g_tp for _g_tp in glob.glob(os.path.join(_flux_images_dir, 'flux_[0-9][0-9][0-9].jpg')))
        if not (_VLM_TEXT_ENABLED and _paths):
            return
        # With the OCR judge this costs ~0.6 s a frame on the
        # CPU, so it always runs: the in-loop gate judged each
        # ATTEMPT file, and this is the only check that looks
        # at the canonical winners that actually ship. Without
        # OCR it needs the GPU judge, and then it is only worth
        # doing if the in-loop pass left frames unreviewed.
        _have_ocr = False
        if _OCR_TEXT_ENABLED:
            try:
                from zyg_workflows import typography_ocr as _tocr_s

                _have_ocr = _tocr_s.available()
            except Exception:
                _have_ocr = False
        if not _have_ocr and _in_loop_checked >= len(_paths):
            return
        _stage_start('Stage 3.6: Typography sweep')
        try:
            import gc as _gc_tp
            import torch as _torch_tp

            _gc_tp.collect()
            if _torch_tp.cuda.is_available():
                _torch_tp.cuda.empty_cache()
                _debug(
                    'Stage 3.6',
                    f'VRAM before typography sweep: {_torch_tp.cuda.mem_get_info()[0] / 1024**3:.1f}GB free',
                )
        except Exception as _exc:  # noqa: BLE001 — torch raises its own RuntimeError tree from CUDA init
            _zyg_log.debug(
                'VRAM reclaim before the typography sweep failed — the sweep runs anyway: %s',
                _exc,
            )
        for _tpp in _paths:
            _v = None
            if _have_ocr:
                try:
                    _oj = _tocr_s.judge(_tpp)
                except Exception:
                    _oj = None
                if _oj is not None:
                    _v = (_oj[0], _oj[1])
                    if not _oj[0] and _oj[2]:
                        _vlm_text_boxes[os.path.basename(_tpp)] = _oj[2][0]
            if _v is None:
                _v = _vlm_text_gate_qwen(_tpp)
            if _v is None:
                _tp['unusable'] += 1
                continue
            _tp['checked'] += 1
            _ok_tp, _why_tp = _v
            if not _ok_tp:
                _tp['flagged'] += 1
                _flags.append({'image': os.path.basename(_tpp), 'reason': str(_why_tp)[:120]})
        _log(
            'INFO',
            'Stage 3.6',
            f'Typography sweep (post-render, local judge): '
            f'{_tp["checked"]} checked, {_tp["flagged"]} flagged, '
            f'{_tp["unusable"]} judge-unusable',
        )
        for _f_tp in _flags:
            _log('WARNING', 'Stage 3.6', f'{_f_tp["image"]}: {_f_tp["reason"]}')
        if _tp['flagged']:
            _log(
                'WARNING',
                'Stage 3.6',
                f'{_tp["flagged"]} canonical frame(s) still carry '
                f'readable lettering after the full retry ladder '
                f'— they shipped flagged. Boxes are recorded in '
                f'vlm_text_boxes for a region repair pass.',
            )
        if _tp['unusable'] and not _tp['checked']:
            _log(
                'WARNING',
                'Stage 3.6',
                'Typography sweep produced NO verdict either — '
                'lettering is unreviewed on this run. Check '
                'vlm_inspector and free VRAM.',
            )
        pipeline_state['typography_post_flags'] = _flags
        pipeline_state['typography_post_stats'] = dict(_tp)
        if _vlm_text_boxes:
            pipeline_state['vlm_text_boxes'] = dict(_vlm_text_boxes)
        _done('Stage 3.6: Typography sweep', {'checked': _tp['checked'], 'flagged': _tp['flagged']})
    except Exception as _tp_e:
        _log('WARNING', 'Stage 3.6', f'Typography sweep failed (non-fatal): {_tp_e!r}')
    # Supersede the in-loop receipt: this pass is the one that
    # actually reached the frames.
    _tot = _in_loop_checked + _tp['checked']
    _gate_receipt(
        'typography',
        bool(_tot),
        (
            ''
            if _tot
            else 'no judge could reach any frame: local '
            'judge needs 14 GB mid-render, API '
            'fallback returned a billing error'
        ),
        {
            'in_loop_checked': _in_loop_checked,
            'sweep_checked': _tp['checked'],
            'sweep_flagged': _tp['flagged'],
            'sweep_unusable': _tp['unusable'],
            'judge': _vlm_gate_stats.get('text_judge') or 'none',
        },
    )


def hand_qc_post_pass(fs, ctx):
    """Stage 3.7 — judge hands once the GPU is actually free.

    Runs AFTER the whole FLUX section, not inside it. Two
    earlier placements both produced zero coverage:

      * inside the per-slot loop, where FLUX holds the card
        and the headroom guard declined every frame
        (run 7033208f: 0 checked, 61 unavailable);
      * inside `if not _sch_fw_active:`, the per-pipeline
        unload branch, which ZYG_SCHOLARLY_FLUX_PERSISTENT=1
        makes permanently false — so it never ran at all.

    Hoisting it out of that branch made it run, and it then
    reported honestly: `0 checked, 4 unavailable, VRAM before
    hand QC: 6.5GB free (persistent worker: True)`. Honest,
    still useless — the persistent worker keeps FLUX resident
    and 6.5 GB will not hold a 6.6 GB vision model.

    The card only frees when the worker releases it, which it
    does at the end of Stage 3.5 (measured: 36.1 GB free).
    So the judge runs there. Hand QC is advisory — it flags,
    it does not repair — so nothing downstream needs it
    earlier, and Stage 6 has not started yet.
    """
    _HAND_QC_ENABLED = fs._HAND_QC_ENABLED
    _debug = ctx._debug
    _done = ctx._done
    _flux_images_dir = fs._flux_images_dir
    _gate_receipt = ctx._gate_receipt
    _hand_qa_score = _ft.partial(hand_qa_score, fs, ctx)
    _hand_qc_stats = fs._hand_qc_stats
    _log = ctx._log
    _sch_fw_active = fs._sch_fw_active
    _stage_start = ctx._stage_start
    pipeline_state = ctx.pipeline_state
    _hand_qc_ran = False
    _hand_qc_skip_reason = ''
    try:
        try:
            import gc as _gc_hq
            import torch as _torch_hq

            _gc_hq.collect()
            if _torch_hq.cuda.is_available():
                _torch_hq.cuda.empty_cache()
                _free_hq = _torch_hq.cuda.mem_get_info()[0] / 1024**3
                _debug(
                    'Stage 3.7',
                    f'VRAM before hand QC: {_free_hq:.1f}GB free (persistent worker was: {_sch_fw_active})',
                )
        except Exception as _exc:  # noqa: BLE001 — torch raises its own RuntimeError tree from CUDA init
            _zyg_log.debug('VRAM reclaim before hand QC failed — hand QC runs anyway: %s', _exc)
        _hand_post_paths = sorted(
            _g_hp for _g_hp in glob.glob(os.path.join(_flux_images_dir, 'flux_[0-9][0-9][0-9].jpg'))
        )
        if not _HAND_QC_ENABLED:
            _hand_qc_skip_reason = 'ZYG_SCHOLARLY_HAND_QC=0'
        elif not _hand_post_paths:
            _hand_qc_skip_reason = 'no flux_NNN.jpg frames on disk'
        else:
            _stage_start('Stage 3.7: Hand QC')
            _hand_flags: list = []
            for _hp in _hand_post_paths:
                _hs, _hi = _hand_qa_score(_hp)
                if _hs is not None and _hs < 1.0:
                    _hand_flags.append(
                        {
                            'image': os.path.basename(_hp),
                            'score': round(float(_hs), 2),
                            'issues': list(_hi)[:3],
                        }
                    )
            _log(
                'INFO',
                'Stage 3.7',
                f'Hand QC (post-render): '
                f'{_hand_qc_stats["checked"]} checked, '
                f'{_hand_qc_stats["flagged"]} flagged, '
                f'{_hand_qc_stats["unavailable"]} unavailable',
            )
            if _hand_qc_stats['unavailable'] and not _hand_qc_stats['checked']:
                _log(
                    'WARNING',
                    'Stage 3.7',
                    'Hand QC produced NO usable score on any '
                    'frame — hands shipped unreviewed. Check '
                    'the detector, ZYG_HAND_VLM_MODEL, and '
                    'free VRAM.',
                )
            for _hf in _hand_flags:
                _log(
                    'WARNING',
                    'Stage 3.7',
                    f'{_hf["image"]}: hand score {_hf["score"]} — {"; ".join(_hf["issues"])[:110]}',
                )
            pipeline_state['hand_qc_stats'] = dict(_hand_qc_stats)
            pipeline_state['hand_qc_flags'] = _hand_flags
            _hand_qc_ran = True
            _done(
                'Stage 3.7: Hand QC',
                {'checked': _hand_qc_stats['checked'], 'flagged': _hand_qc_stats['flagged']},
            )
    except Exception as _hq_post_e:
        _hand_qc_skip_reason = f'raised {_hq_post_e!r}'
        _log('WARNING', 'Stage 3.7', f'Hand QC post-pass failed (non-fatal): {_hq_post_e!r}')
    # A gate that does not run must SAY so. Silence is the bug.
    _gate_receipt('hand_qc', _hand_qc_ran, _hand_qc_skip_reason, dict(_hand_qc_stats))
    return _hand_qc_ran


# ── MediaPipe QA scorer ──────────────────────────────────────────────
# Analyzes a generated image for anatomy defects: extra fingers, fused
# hands, implausible arm geometry.  Returns (score, issues_list).
# score=1.0 = no detected issues.  score<0.65 triggers a retry.
# Fails gracefully if mediapipe/cv2 are unavailable (returns 1.0, []).
def mediapipe_qa_score(fs, ctx, image_path: str) -> tuple:
    try:
        import mediapipe as _mp_qa
        import cv2 as _cv2_qa

        _img_bgr = _cv2_qa.imread(image_path)
        if _img_bgr is None:
            return 1.0, []
        _img_rgb = _cv2_qa.cvtColor(_img_bgr, _cv2_qa.COLOR_BGR2RGB)
        _issues: list = []
        _penalty = 0.0
        _mp_h = _mp_qa.solutions.holistic
        with _mp_h.Holistic(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=0.5,
        ) as _hol:
            _res = _hol.process(_img_rgb)
            # ── Hand analysis ────────────────────────────────
            # Fingertip indices: thumb=4, index=8, middle=12, ring=16, pinky=20
            # Knuckle (MCP) indices: thumb=2, index=5, middle=9, ring=13, pinky=17
            for _side, _hand_lms in (
                ('left', _res.left_hand_landmarks),
                ('right', _res.right_hand_landmarks),
            ):
                if _hand_lms is None:
                    continue
                _lm = _hand_lms.landmark
                _tips = [4, 8, 12, 16, 20]
                _mcps = [2, 5, 9, 13, 17]
                # A finger is "extended" when its tip y-coord is above
                # its knuckle (lower y = higher in frame)
                _n_ext = sum(1 for t, k in zip(_tips, _mcps) if _lm[t].y < _lm[k].y)
                if _n_ext > 5:
                    _issues.append(f'{_side} hand: {_n_ext} extended segments (>5 — likely extra finger)')
                    _penalty += 0.35
                # Tightly clustered landmarks → fused/melted hand
                _xs = [_lm[i].x for i in range(21)]
                _ys = [_lm[i].y for i in range(21)]
                if (max(_xs) - min(_xs)) < 0.03 and (max(_ys) - min(_ys)) < 0.03:
                    _issues.append(f'{_side} hand: landmarks tightly clustered (possible fused hand)')
                    _penalty += 0.25
            # ── Pose analysis ────────────────────────────────
            if _res.pose_landmarks:
                _pose = _res.pose_landmarks.landmark
                _L_SH, _R_SH = 11, 12
                _L_EL, _R_EL = 13, 14
                _L_WR, _R_WR = 15, 16
                # Shoulder width sanity check
                _sh_w = abs(_pose[_L_SH].x - _pose[_R_SH].x)
                if _sh_w < 0.02:
                    _issues.append('shoulders too close (figure may be distorted)')
                    _penalty += 0.15
                # Elbow should sit between shoulder and wrist (y range)
                for _lbl, _sh, _el, _wr in (
                    ('left', _L_SH, _L_EL, _L_WR),
                    ('right', _R_SH, _R_EL, _R_WR),
                ):
                    _vis = [_pose[i].visibility for i in (_sh, _el, _wr)]
                    if all(v > 0.5 for v in _vis):
                        _ey = _pose[_el].y
                        _sy, _wy = _pose[_sh].y, _pose[_wr].y
                        if not (min(_sy, _wy) - 0.05 <= _ey <= max(_sy, _wy) + 0.05):
                            _issues.append(f'{_lbl} arm: elbow out of expected range (limb may be bent backward)')
                            _penalty += 0.15
        return max(0.0, 1.0 - min(_penalty, 1.0)), _issues
    except ImportError:
        return 1.0, []  # mediapipe not installed — QA skipped
    except Exception:
        return 1.0, []  # any failure → don't block generation
