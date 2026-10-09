# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Texture QC, dataset exclusions, the drift gate and the QC summary.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 2893-3244).
"""

from __future__ import annotations

import os
from typing import Any, Callable
from zyg_workflows import contact_sheet_pipeline as _csp
from .sheet_finalize import scaled_budget


def step_texture_qc(tiles: list[dict], report: dict, log_fn: Callable[[str], None] | None) -> None:
    """Texture QC gate.

    ArcFace alone cannot see texture and structurally favors smooth
    beauty-filter faces (they resemble the smooth anchor crop), so waxy tiles
    sailed through QC into LoRA training. Runs AFTER the regen loop so it
    scores the images that actually ship (regen entries are refreshed into
    report['results']). Scores a cheek band, not the whole bbox — eyes/brows/
    lips dominate full-bbox variance and invert the metric on small faces
    (calibrated on run e58b9137bdc5: waxy cheeks 20-33, anchor cheek ~122,
    mannequin ~4).
    """
    if os.environ.get('ZYG_TEXTURE_QC', '1').strip().lower() not in ('0', 'false', 'no', 'off'):
        # Calibrated 2026-07-15 against A/B renders: true photographic cheeks
        # measure ~110-120, waxy/semi-render ~24-26, mannequin ~4. Warn at 45
        # now meaningfully flags the waxy/render band; exclude stays at 12
        # (excluding the whole waxy band would gut the training set — warn-only).
        _tex_floor = float(os.environ.get('ZYG_TEXTURE_QC_EXCLUDE_LAPVAR', '12'))
        _tex_warn = float(os.environ.get('ZYG_TEXTURE_QC_WARN_LAPVAR', '45'))
        # Training floor sits between mannequin-exclude and warn: calibrated
        # waxy/semi-render cheeks measure ~24-26, true photos ~110-120, so 30
        # drops the waxy band from the dataset without gutting borderline tiles.
        _tex_train_floor = float(os.environ.get('ZYG_TEXTURE_QC_TRAIN_LAPVAR', '30'))
        _tex_scores: list[float] = []
        _tex_excluded = 0
        _tex_train_excluded = 0
        _tex_low = 0
        for t in tiles:
            r = report['results'].get(t.get('path') or '')
            if not r or not r.get('face_detected'):
                continue
            _ts = _csp._tile_texture_score(t['path'], r.get('bbox'))
            if _ts is None:
                continue
            t['texture_score'] = round(_ts, 1)
            _tex_scores.append(_ts)
            if _ts < _tex_floor:
                t['exclude_from_dataset'] = True
                t['texture_verdict'] = 'mannequin'
                _tex_excluded += 1
            elif _ts < _tex_train_floor:
                # Waxy band (2026-07-17): sheet-worthy but NOT train-worthy —
                # a 13-variance cheek is exactly the waxy-skin failure the LoRA
                # must never learn. Kept in the sheet, dropped from the dataset.
                t['texture_verdict'] = 'low_texture'
                t['exclude_from_dataset'] = True
                t['low_texture_excluded'] = True
                _tex_train_excluded += 1
                _tex_low += 1
            elif _ts < _tex_warn:
                t['texture_verdict'] = 'low_texture'
                _tex_low += 1
        if log_fn and _tex_scores:
            log_fn(
                f'Texture QC: cheek-band Laplacian-variance '
                f'mean {sum(_tex_scores) / len(_tex_scores):.0f}, '
                f'min {min(_tex_scores):.0f}, max {max(_tex_scores):.0f} '
                f'(exclude<{_tex_floor:g}, train-exclude<{_tex_train_floor:g}, '
                f'warn<{_tex_warn:g}) — {_tex_excluded} excluded, '
                f'{_tex_train_excluded} waxy kept-in-sheet-only, {_tex_low} low-texture',
            )


def step_dataset_exclusions(
    tiles: list[dict],
    *,
    fail_class: tuple,
    train_floor: float,
    log_fn: Callable[[str], None] | None,
) -> tuple[int, int, int]:
    """Separate "good enough to show" from "good enough to TRAIN on".

    Profiles pass at a lenient 0.25, but an ultra-weak 0.27 profile pollutes
    the LoRA; keep it in the sheet, exclude it from the training dataset.
    Returns (excluded, weak_train, mislabel_kept).
    """
    excluded = 0
    weak_train = 0
    mislabel_kept = 0
    for t in tiles:
        _v = t.get('identity_verdict')
        _s = t.get('identity_score')
        # VLM-flagged and unrepaired → fail-closed exclusion. Flag-only gate:
        # flags can only remove a tile from the dataset, never approve one, and
        # they outrank the mislabel-keep path below (a strong-identity tile
        # with a ghost is still a ghost).
        if _csp.IDQC_EXCLUDE_FAILED and t.get('vlm_flag'):
            t['exclude_from_dataset'] = True
            excluded += 1
            if log_fn:
                log_fn(
                    f'Identity QC: tile {t.get("index")} dropped from dataset '
                    f'(VLM: {(t.get("vlm_defect") or "defect")[:80]})',
                )
            continue
        # C: a mislabeled_angle tile with strong identity is a good photo of the
        # person at the wrong angle — keep it for training but strip the (wrong)
        # angle from its caption so it never teaches the LoRA a bad pose.
        if _v == 'mislabeled_angle' and isinstance(_s, (int, float)) and _s >= _csp.IDQC_MISLABEL_KEEP_SCORE:
            t['angle_neutral'] = True
            mislabel_kept += 1
            continue
        # A back-labeled tile that produced a NUMERIC identity score has a
        # scoreable, visible face — it is not a back view no matter what the
        # label says (run ac97acfb: tile 40 trained a full 90° profile under a
        # '120° back three-quarter' caption; yaw ~90 passes the back-label yaw
        # check so assess_tile still said no_face_expected). Strong identity →
        # keep with an angle-neutral caption; weak → wrong angle AND weak
        # identity is pure caption poison, drop it from the dataset.
        if _v == 'no_face_expected' and isinstance(_s, (int, float)):
            if _s >= _csp.IDQC_MISLABEL_KEEP_SCORE:
                t['angle_neutral'] = True
                mislabel_kept += 1
            else:
                t['exclude_from_dataset'] = True
                t['weak_identity'] = True
                weak_train += 1
                if log_fn:
                    log_fn(
                        f'Identity QC: tile {t.get("index")} dropped from dataset '
                        f'(back-labeled but face visible, similarity {_s:.3f} < '
                        f'{_csp.IDQC_MISLABEL_KEEP_SCORE:g})',
                    )
            continue
        # Fail-closed: no_face on a face-expected tile is excluded exactly like
        # a fail-class verdict. A successful regen rewrites the verdict to
        # pass/no_face_expected above, so only unrepaired tiles are dropped —
        # dropping a cell always beats training on a broken one (2026-07-16).
        if _csp.IDQC_EXCLUDE_FAILED and (
            _v in fail_class or (_v == 'no_face' and t.get('identity_visibility') != 'back')
        ):
            t['exclude_from_dataset'] = True
            excluded += 1
            if log_fn and not t.get('regenerated'):
                log_fn(
                    f'Identity QC: tile {t.get("index")} dropped from dataset '
                    f'({_v}, regen did not produce a usable replacement)',
                )
            continue
        _sc = t.get('identity_score')
        if (
            _csp.IDQC_EXCLUDE_FAILED
            and isinstance(_sc, (int, float))
            and _sc < train_floor
            and t.get('identity_verdict') == 'pass'
        ):
            t['exclude_from_dataset'] = True
            t['weak_identity'] = True
            weak_train += 1
    if weak_train and log_fn:
        log_fn(
            f'Identity QC: {weak_train} passing-but-weak tile(s) below train floor '
            f'{train_floor} excluded from LoRA dataset (kept in sheet)',
        )
    if mislabel_kept and log_fn:
        log_fn(
            f'Identity QC: {mislabel_kept} strong-identity mislabeled-angle tile(s) '
            f'kept in dataset with angle-neutral captions (fix C)',
        )
    return excluded, weak_train, mislabel_kept


def step_drift_gate(
    tiles: list[dict],
    *,
    report: dict,
    vlm: Any,
    vlm_anchor_cell: str | None,
    allow_regen: bool,
    train_floor: float,
    qc_scale: float,
    halt_check: Callable[[], None] | None,
    log_fn: Callable[[str], None] | None,
) -> int:
    """DRIFT GATE (2026-07-20): catch tiles that PASS ArcFace but are the wrong face.

    ArcFace is nearly blind to brow/lip/face-shape drift, so it accepts (a)
    tiles far from the SET's own centroid — sibling-inconsistent (S6,
    embedding) — and (b) weak-band passers just over the train floor (S4).
    Both are only CANDIDATES; a cloud VLM same-person check confirms before we
    exclude, so embedding noise or a healthy tight set prunes nothing. Union ->
    VLM-confirm -> exclude. Ivy Rossi audit: tile 16.
    """
    _drift_gate_on = os.environ.get(
        'ZYG_IDQC_DRIFT_GATE',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    _drift_dropped = 0
    if _drift_gate_on and allow_regen and vlm is not None and vlm_anchor_cell and os.path.isfile(vlm_anchor_cell):
        try:
            _weak_ceil = float(os.environ.get('ZYG_IDQC_DRIFT_WEAK_CEIL', '0.48'))
            _drift_max = max(1, scaled_budget('ZYG_IDQC_DRIFT_MAX', 10, qc_scale))
            # (a) embedding outliers from the intra-set scan.
            _outlier_paths = {
                o.get('path')
                for o in (((report.get('summary') or {}).get('intra_set_outliers') or {}).get('outliers') or [])
            }
            # (b) weak-band frontal/oblique passers.
            _cands: list[dict] = []
            _seen_p: set = set()
            for t in tiles:
                _p = t.get('path')
                if not _p or _p in _seen_p:
                    continue
                if t.get('exclude_from_dataset'):
                    continue  # already out — no need to pay for a VLM call
                _sc = t.get('identity_score')
                _is_outlier = _p in _outlier_paths
                _is_weak = (
                    t.get('identity_verdict') == 'pass'
                    and t.get('identity_visibility') in ('frontal', 'oblique')
                    and isinstance(_sc, (int, float))
                    and train_floor <= _sc < _weak_ceil
                )
                if _is_outlier or _is_weak:
                    _cands.append(t)
                    _seen_p.add(_p)
            # Worst-first so the budget covers the most suspicious tiles.
            _cands.sort(
                key=lambda t: t.get('identity_score') if isinstance(t.get('identity_score'), (int, float)) else 0.0
            )
            _cands = _cands[:_drift_max]
            if _cands and log_fn:
                log_fn(
                    f'Identity QC drift gate: VLM-confirming {len(_cands)} candidate '
                    f'tile(s) (embedding outliers + weak-band passers)',
                )
            for t in _cands:
                if callable(halt_check):
                    halt_check()
                _im = vlm.judge_identity_match(
                    t['path'],
                    vlm_anchor_cell,
                    angle=t.get('angle') or '',
                    log_fn=log_fn,
                )
                if _im.get('checked') and not _im.get('same_person') and _im.get('confidence') == 'high':
                    t['exclude_from_dataset'] = True
                    t['identity_drift'] = True
                    t['drift_features'] = _im.get('drifted_features') or ''
                    _drift_dropped += 1
                    if log_fn:
                        _why = 'embedding outlier' if t['path'] in _outlier_paths else 'weak-band'
                        log_fn(
                            f'Identity QC drift gate: tile {t.get("index")} dropped from '
                            f'dataset — VLM says different person [{_why}, '
                            f'score {t.get("identity_score")}] ({(_im.get("drifted_features") or "")[:80]})',
                        )
            vlm.release()
            if _drift_dropped and log_fn:
                log_fn(f'Identity QC drift gate: {_drift_dropped} tile(s) excluded as identity drift')
        except (RuntimeError, KeyboardInterrupt, SystemExit):
            # halt_check()'s hard-halt raises a plain RuntimeError; it must
            # unwind, not be swallowed as a "gate skipped". (PipelinePaused is
            # BaseException and already escapes the except below.)
            raise
        except Exception as _drift_exc:
            if log_fn:
                log_fn(f'Identity QC drift gate skipped ({str(_drift_exc)[:100]})')
    return _drift_dropped


def step_qc_summary(
    char_id: str,
    tiles: list[dict],
    *,
    anchor: str,
    report: dict,
    fail_class: tuple,
    regen_ok: int,
    excluded: int,
    weak_train: int,
    drift_dropped: int,
    progress_job: dict | None,
    log_fn: Callable[[str], None] | None,
) -> dict:
    """Build the identity-QC summary and write it into the manifest."""
    counts: dict[str, int] = {}
    scored = [
        t['identity_score']
        for t in tiles
        if isinstance(t.get('identity_score'), (int, float)) and t.get('identity_verdict') in ('pass', 'fail')
    ]
    for t in tiles:
        v = t.get('identity_verdict') or 'unscored'
        counts[v] = counts.get(v, 0) + 1
    # Report the TRUE exclusion count straight from the tile flags. The old
    # `excluded` counter only tallied fail_class drops and missed weak_identity
    # tiles and the regen-only IDQC_REGEN_MIN_SCORE floor — the summary said
    # "6 excluded" while 7 tiles actually had no dataset_path (2026-07-12 audit).
    _total_excluded = sum(1 for t in tiles if t.get('exclude_from_dataset'))
    summary = {
        'backend': 'arcface_antelopev2',
        'anchor_path': anchor,
        'total': len(tiles),
        'counts': counts,
        'regenerated': regen_ok,
        'vlm_flagged': sum(1 for t in tiles if t.get('vlm_flag')),
        'excluded_from_dataset': _total_excluded,
        'excluded_fail_class': excluded,
        'excluded_weak_identity': weak_train,
        'excluded_identity_drift': drift_dropped,
        'intra_set_outliers': ((report.get('summary') or {}).get('intra_set_outliers') or {}),
        'mean_score': round(sum(scored) / len(scored), 4) if scored else None,
        'min_score': round(min(scored), 4) if scored else None,
        'checked_at': _csp._ams_iso(),
    }

    m = _csp.load_manifest(char_id) or {}
    extra = {
        k: m[k]
        for k in m
        if k
        not in (
            'char_id',
            'pipeline',
            'rows',
            'cols',
            'gutter_px',
            'cell_width',
            'cell_height',
            'sheet_path',
            'approved',
            'approved_at',
            'tiles',
            'updated_at',
        )
    }
    extra['identity_qc'] = summary
    _csp.write_manifest(
        char_id,
        rows=int(m.get('rows') or _csp.DEFAULT_ROWS),
        cols=int(m.get('cols') or _csp.DEFAULT_COLS),
        gutter=int(m.get('gutter_px') or _csp.DEFAULT_GUTTER),
        cell_w=int(m.get('cell_width') or _csp.DEFAULT_CELL_W),
        cell_h=int(m.get('cell_height') or _csp.DEFAULT_CELL_H),
        sheet_path=m.get('sheet_path') or _csp.master_sheet_path(char_id),
        approved=bool(m.get('approved')),
        tiles=tiles,
        extra=extra,
    )
    if progress_job is not None:
        progress_job['identity_qc'] = summary
    if log_fn:
        fail_total = sum(counts.get(v, 0) for v in fail_class)
        log_fn(
            f'Identity QC complete — {counts.get("pass", 0)} pass, '
            f'{fail_total} fail-class ({regen_ok} repaired, {excluded} excluded)',
        )
    return summary
