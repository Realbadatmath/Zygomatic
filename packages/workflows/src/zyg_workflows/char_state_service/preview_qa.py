# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Preview QA: face/hand YOLO, attempt ranking, best-of-N slot generation.

Moved verbatim out of the old single-file char_state_service.py (lines 2245-2542).
"""

import os
from zyg_workflows import gui_state
from zyg_workflows import paths
from zyg_workflows.pipeline_config import (
    _PHOTOREAL_CLIP_NEG,
    _PHOTOREAL_CLIP_POS,
)
from zyg_workflows.char_state_service._common import (
    _zyg_log,
)
from zyg_workflows.char_state_service.preview_reference import (
    _preview_backend_tier,
)


def _preview_face_yolo_count(img_path: str) -> int:
    """Count faces in preview still (1 = solo OK)."""
    pass  # (global stmt removed: names moved to gui_state)
    try:
        from ultralytics import YOLO

        _path = os.environ.get(
            'ZYG_FACE_YOLO_PATH',
            str(paths.ZYG_COMFY_ROOT / 'models' / 'ultralytics' / 'bbox' / 'face_yolov8m.pt'),
        )
        if not os.path.isfile(_path):
            return 1
        if gui_state._PREVIEW_FACE_YOLO is None:
            gui_state._PREVIEW_FACE_YOLO = YOLO(_path)
        _res = gui_state._PREVIEW_FACE_YOLO.predict(img_path, conf=0.4, verbose=False)[0]
        return len(_res.boxes) if _res.boxes is not None else 0
    except Exception:
        return 1


def _preview_hand_yolo_score(img_path: str) -> tuple[float, int, list[str]]:
    """Score visible hands via ADetailer hand_yolov8s (2 boxes = best)."""
    pass  # (global stmt removed: names moved to gui_state)
    _issues: list[str] = []
    try:
        from ultralytics import YOLO

        _yolo_path = os.environ.get(
            'ZYG_HAND_YOLO_PATH',
            str(paths.ZYG_COMFY_ROOT / 'models' / 'ultralytics' / 'bbox' / 'hand_yolov8s.pt'),
        )
        if not os.path.isfile(_yolo_path):
            return 0.5, 0, ['hand yolo weights missing']
        if gui_state._PREVIEW_HAND_YOLO is None:
            gui_state._PREVIEW_HAND_YOLO = YOLO(_yolo_path)
        _res = gui_state._PREVIEW_HAND_YOLO.predict(img_path, conf=0.35, verbose=False)[0]
        _n = len(_res.boxes) if _res.boxes is not None else 0
        if _n == 2:
            _confs = [float(b.conf) for b in _res.boxes]
            _score = 0.75 + 0.25 * min(_confs)
            return min(1.0, _score), _n, _issues
        if _n > 2:
            _issues.append(f'{_n} hand boxes (extra detections)')
            return 0.35, _n, _issues
        if _n == 1:
            _issues.append('only one hand detected')
            return 0.4, _n, _issues
        _issues.append('no hands detected')
        return 0.0, 0, _issues
    except Exception as _yolo_e:
        return 0.5, -1, [f'yolo check skipped: {_yolo_e}']


def _preview_hand_qa(img_path: str) -> tuple[float, list[str]]:
    """MediaPipe hand check for preview stills. score 1.0 = no hand defects detected."""
    try:
        import cv2 as _cv_hand
        import mediapipe as _mp_hand

        _hol_mod = getattr(getattr(_mp_hand, 'solutions', None), 'holistic', None)
        if _hol_mod is None:
            return 1.0, []
        _Holistic = _hol_mod.Holistic

        _img_bgr = _cv_hand.imread(img_path)
        if _img_bgr is None:
            return 1.0, []
        _img_rgb = _cv_hand.cvtColor(_img_bgr, _cv_hand.COLOR_BGR2RGB)
        _issues: list[str] = []
        _penalty = 0.0
        _tips = [4, 8, 12, 16, 20]
        _mcps = [2, 5, 9, 13, 17]
        with _Holistic(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=0.5,
        ) as _hol:
            _res = _hol.process(_img_rgb)
            for _side, _hand_lms in (
                ('left', _res.left_hand_landmarks),
                ('right', _res.right_hand_landmarks),
            ):
                if _hand_lms is None:
                    continue
                _lm = _hand_lms.landmark
                _n_ext = sum(1 for _t, _k in zip(_tips, _mcps) if _lm[_t].y < _lm[_k].y)
                _xs = [_lm[i].x for i in range(21)]
                _ys = [_lm[i].y for i in range(21)]
                _spread = (max(_xs) - min(_xs)) + (max(_ys) - min(_ys))
                if _spread < 0.05:
                    _issues.append(f'{_side} hand: landmarks clustered (fused)')
                    _penalty += 0.30
                elif _n_ext > 5:
                    _issues.append(f'{_side} hand: {_n_ext} extended (>5)')
                    _penalty += 0.35
                elif _n_ext < 4:
                    _issues.append(
                        f'{_side} hand: {_n_ext} extended (<4 — missing/extra fingers)',
                    )
                    _penalty += 0.45
        return max(0.0, 1.0 - min(1.0, _penalty)), _issues
    except Exception:
        return 1.0, []


def _preview_attempt_rank(
    tier: str,
    drift_ok: bool,
    drift_sc: float,
    *,
    hand_qa: float = 1.0,
    hand_yolo_sc: float = 0.5,
    hand_count: int = 0,
    face_count: int = 1,
    smile_score: float = 0.0,
    want_smile: bool = False,
    photoreal_score: float = 0.0,
    want_photoreal: bool = False,
    blender_dataset: bool = False,
) -> float:
    """Higher is better — prefer LoRA locked, drift pass, photoreal look, good hands."""
    _tier_w = {'locked': 3000.0, 'instantid': 2000.0, 'img2img': 500.0, 'other': 0.0}
    rank = _tier_w.get(tier, 0.0)
    _drift_w = 40.0 if (want_photoreal and blender_dataset) else 100.0
    if drift_ok:
        rank += 200.0
    rank += (1.0 - min(1.0, max(0.0, float(drift_sc)))) * _drift_w
    _hand_blend = 0.35 * min(1.0, max(0.0, float(hand_qa))) + 0.65 * min(1.0, max(0.0, float(hand_yolo_sc)))
    rank += _hand_blend * 220.0
    rank += min(2, max(0, int(hand_count))) * 40.0
    if int(face_count) == 1:
        rank += 80.0
    elif int(face_count) > 1:
        rank -= 500.0
    if want_smile:
        rank += min(1.0, max(0.0, float(smile_score))) * 180.0
    if want_photoreal:
        rank += min(1.0, max(0.0, float(photoreal_score))) * 250.0
    return rank


def _generate_preview_slot_best_of_n(
    *,
    out_png: str,
    prompt: str,
    width: int,
    height: int,
    base_seed: int,
    n_candidates: int,
    character_package: dict,
    char_id: str,
    reference_image: str | None,
    model_family: str,
    blender_dataset: bool,
    log_fn,
    cgs_mod,
    check_hands: bool = False,
    want_smile: bool = False,
    want_photoreal: bool = False,
) -> tuple[bool, str, bool, float, int]:
    """Try *n_candidates* seeds; keep the best locked preview (by QA rank)."""
    import shutil as _sh_cand
    import tempfile as _tmp_prev

    n_candidates = max(1, n_candidates)
    best: dict | None = None
    tmp_dir = _tmp_prev.mkdtemp(prefix='zyg_prev_')
    _smile_clip_text = 'person smiling with visible teeth, warm open smile, cheerful expression' if want_smile else ''

    try:
        from zyg_workflows import consistency_qa_service as _cqa_pr
    except Exception:
        _cqa_pr = None

    try:
        for _ci in range(n_candidates):
            _seed = base_seed + _ci * 7919
            _cand_path = os.path.join(tmp_dir, f'cand_{_ci}.png')
            ok, backend, drift_ok, drift_sc = cgs_mod.generate_character_preview_still(
                _cand_path,
                prompt.strip(),
                width=width,
                height=height,
                seed=_seed,
                character_package=character_package,
                char_id=char_id,
                reference_image=reference_image,
                model_family=model_family,
                log_fn=log_fn,
                blender_dataset=blender_dataset,
            )
            if not ok:
                log_fn(f'Preview candidate {_ci + 1}/{n_candidates} failed ({backend})')
                continue
            tier = _preview_backend_tier(backend)
            _hand_sc, _hand_iss = (1.0, [])
            _yolo_sc, _hand_n, _yolo_iss = (0.5, 0, [])
            _face_n = 1
            if check_hands:
                try:
                    _hand_sc, _hand_iss = _preview_hand_qa(_cand_path)
                except Exception:
                    _hand_sc, _hand_iss = 1.0, []
                _yolo_sc, _hand_n, _yolo_iss = _preview_hand_yolo_score(_cand_path)
                _hand_iss = _hand_iss + _yolo_iss
                _face_n = _preview_face_yolo_count(_cand_path)
                if _face_n != 1:
                    _hand_iss.append(f'{_face_n} faces detected (want 1)')
            _smile_sc = 0.0
            if want_smile and _smile_clip_text and _cqa_pr:
                try:
                    _smile_sc = _cqa_pr.score_text_match(_cand_path, _smile_clip_text)
                except Exception:
                    _smile_sc = 0.0
            _photoreal_sc = 0.0
            if want_photoreal and _cqa_pr:
                try:
                    _pos = _cqa_pr.score_text_match(_cand_path, _PHOTOREAL_CLIP_POS)
                    _neg = _cqa_pr.score_text_match(_cand_path, _PHOTOREAL_CLIP_NEG)
                    _photoreal_sc = max(0.0, min(1.0, _pos - _neg * 0.55))
                except Exception:
                    _photoreal_sc = 0.0
            rank = _preview_attempt_rank(
                tier,
                drift_ok,
                drift_sc,
                hand_qa=_hand_sc,
                hand_yolo_sc=_yolo_sc,
                hand_count=_hand_n,
                face_count=_face_n,
                smile_score=_smile_sc,
                want_smile=want_smile,
                photoreal_score=_photoreal_sc,
                want_photoreal=want_photoreal,
                blender_dataset=blender_dataset,
            )
            _hand_note = (
                f' faces={_face_n} hands={_hand_n} yolo={_yolo_sc:.2f} mp={_hand_sc:.2f}'
                + (f' smile={_smile_sc:.2f}' if want_smile else '')
                + (f' photoreal={_photoreal_sc:.2f}' if want_photoreal else '')
                + (f' ({"; ".join(_hand_iss)})' if _hand_iss else '')
                if check_hands
                else (f' photoreal={_photoreal_sc:.2f}' if want_photoreal else '')
            )
            log_fn(
                f'Preview candidate {_ci + 1}/{n_candidates}: seed={_seed} '
                f'tier={tier} drift={drift_sc:.3f} rank={rank:.0f}{_hand_note}',
            )
            row = {
                'path': _cand_path,
                'backend': backend,
                'tier': tier,
                'drift_ok': drift_ok,
                'drift_sc': drift_sc,
                'hand_qa': _hand_sc,
                'hand_yolo_sc': _yolo_sc,
                'hand_count': _hand_n,
                'face_count': _face_n,
                'hand_issues': _hand_iss,
                'seed': _seed,
                'rank': rank,
            }
            if best is None or row['rank'] > best['rank']:
                best = row
        if best:
            # Keep the winner before the scratch directory goes: best['path'] is inside it.
            _sh_cand.copy2(best['path'], out_png)
    except Exception as _exc:
        # The sweep used to run under try/finally with the failure `return` in the finally
        # block, which swallowed whatever went wrong. Same answer to the caller, logged now.
        _zyg_log.debug('preview best-of-n aborted: %s: %s', type(_exc).__name__, _exc)
        best = None
    finally:
        try:
            import shutil as _sh_rm

            _sh_rm.rmtree(tmp_dir, ignore_errors=True)
        except Exception as _exc:
            _zyg_log.debug('temporary preview directory removal skipped: %s', _exc)

    if not best:
        return False, 'preview_all_candidates_failed', False, 0.0, base_seed

    _best_hand = ''
    if check_hands and 'hand_yolo_sc' in best:
        _best_hand = f' hands={best.get("hand_count", 0)} yolo={best.get("hand_yolo_sc", 0):.2f}'
    log_fn(
        f'Preview best-of-{n_candidates}: seed={best["seed"]} '
        f'via {best["backend"]} (drift={best["drift_sc"]:.3f}{_best_hand})',
    )
    return (
        True,
        best['backend'],
        bool(best['drift_ok']),
        float(best['drift_sc']),
        int(best['seed']),
    )
