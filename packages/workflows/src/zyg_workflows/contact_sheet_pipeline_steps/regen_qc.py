# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The VLM judge and the drifted-tile regeneration loop.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 2520-2892).
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Callable
from zyg_workflows import contact_sheet_pipeline as _csp
from .sheet_finalize import scaled_budget, needs_regen

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_vlm_judge(
    char_id: str,
    tiles: list[dict],
    *,
    fail_class: tuple,
    qc_scale: float,
    progress_job: dict | None,
    halt_check: Callable[[], None] | None,
    log_fn: Callable[[str], None] | None,
) -> tuple[Any, str | None, list[dict] | None]:
    """VLM defect judge (2026-07-16).

    Tiered local->cloud visual review of every tile — the only gate that sees
    translucent ghost remnants (ArcFace, face detectors at det 0.22, and
    Laplacian texture were all measured-blind to them on the Kira Dunn run).
    Flag-only semantics: flags route tiles into the regen ladder and, if
    unrepaired, into fail-closed dataset exclusion below; a clean VLM verdict
    never overrides the identity/pose gates. Runs AFTER the circuit breaker so
    a doomed (broken-anchor) run never pays ~47 VLM calls first.

    Returns (vlm_module_or_None, vlm_anchor_cell_or_None, refreshed_to_fix) —
    the last is None when the judge did not run, exactly as the inline code
    only re-evaluated the regen set behind `if _vlm is not None`.
    """
    _vlm = None
    try:
        from zyg_workflows import cell_vlm_judge as _vlm_mod

        if _vlm_mod.enabled():
            _vlm = _vlm_mod
            _vlm_mod.reset_tier_errors()
    except Exception as _vlm_imp_exc:
        if log_fn:
            log_fn(f'VLM judge unavailable ({_vlm_imp_exc}) — skipping')
    _vlm_anchor_cell = _csp._anchor_cell_path(char_id)
    if not os.path.isfile(_vlm_anchor_cell):
        _vlm_anchor_cell = None
    if _vlm is None:
        return _vlm, _vlm_anchor_cell, None
    # Give the local vision model VRAM headroom for the batch — ComfyUI is
    # idle between the sheet and regen stages.
    try:
        from zyg_workflows import _comfy_client as _cc_vlm

        _cc_vlm.free_vram(unload_models=False, free_memory=True)
    except Exception as _exc:
        _zyg_log.debug('vram headroom request before the vlm batch skipped: %s', _exc)
    if progress_job is not None:
        progress_job['sheet_substage'] = 'vlm_judge'
    _vlm_flagged = 0
    # Suspicion-gated cloud escalation (2026-07-18): the cloud tier used to
    # confirm every clean tile (~45 paid calls/run). Tiles with a STRONG
    # ArcFace pass get the local screen only; anything weak, unscored or
    # non-pass keeps the full local→cloud path. ZYG_CELL_VLM_CLOUD_MODE=all
    # restores cloud-on-everything.
    _cloud_mode = (
        os.environ.get(
            'ZYG_CELL_VLM_CLOUD_MODE',
            'suspicion',
        )
        .strip()
        .lower()
    )
    _cloud_sim_floor = float(os.environ.get('ZYG_CELL_VLM_CLOUD_SIM', '0.50'))
    # Face-visible classes that ALWAYS get cloud eyes (2026-07-20): mottling
    # / hyperpigmentation lives on close, forward-facing skin and carries a
    # STRONG ArcFace score (identity survives it), so the identity-keyed
    # suspicion gate is structurally blind to it — the Ivy Rossi audit found
    # trained mottling on frontal/oblique tiles 01/09/11 that screened
    # locally. These are also the most-trained tiles, so the cloud cost is
    # well spent. Set ZYG_CELL_VLM_CLOUD_VIS='' to disable.
    _cloud_vis = tuple(
        v
        for v in os.environ.get(
            'ZYG_CELL_VLM_CLOUD_VIS',
            'frontal,oblique',
        )
        .lower()
        .replace(' ', '')
        .split(',')
        if v
    )
    _vlm_cloud_skipped = 0
    for t in tiles:
        if callable(halt_check):
            halt_check()
        try:
            if int(t.get('index', -1)) == 0:
                continue  # tile 0 is the human-approved anchor itself
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('tile index unparseable, not treated as the anchor tile: %s', _exc)
        _sc_v = t.get('identity_score')
        _allow_cloud = (
            _cloud_mode == 'all'
            or t.get('identity_verdict') != 'pass'
            or not isinstance(_sc_v, (int, float))
            or _sc_v < _cloud_sim_floor
            # Steep-pitch/crown/back tiles always get cloud eyes
            # (2026-07-19): Iris Weber's smeared high-angle faces carried
            # STRONG ArcFace scores — identity survives smearing, so an
            # identity-keyed suspicion gate can never catch this class.
            or _csp._is_steep_or_back_angle(t.get('angle') or '')
            # Frontal/oblique face-visible tiles: the mottling class (2026-07-20).
            or (t.get('identity_visibility') in _cloud_vis)
        )
        if not _allow_cloud:
            _vlm_cloud_skipped += 1
        _jr = _vlm.judge_cell(
            t['path'],
            anchor_path=_vlm_anchor_cell,
            angle=t.get('angle') or '',
            log_fn=log_fn,
            allow_cloud=_allow_cloud,
        )
        if _jr.get('flagged'):
            t['vlm_flag'] = True
            t['vlm_defect'] = _jr.get('defect') or ''
            t['vlm_tier'] = _jr.get('tier') or ''
            _vlm_flagged += 1
            if log_fn:
                log_fn(
                    f'VLM judge: tile {t.get("index")} flagged [{_jr.get("tier")}] — {(_jr.get("defect") or "")[:120]}',
                )
    # Attribute drift sampling (2026-07-16, WARN-ONLY): VLM-read the eye/
    # hair/skin attributes off a couple of passing frontal tiles and compare
    # to the bible — the embeddings are colour-blind by construction, so
    # this is the only per-sheet check that spec colours actually survived.
    # Never excludes or regens; it only surfaces the drift in the log.
    try:
        _n_attr = max(0, scaled_budget('ZYG_IDQC_ATTR_SAMPLES', 2, qc_scale))
    except ValueError:
        _n_attr = 2
    if _n_attr:
        try:
            from zyg_workflows import character_bible_service as _cbs_drift

            _ident_drift = (_cbs_drift.load(char_id) or {}).get('identity') or {}
            _spec_drift = {
                k: _ident_drift.get(k) for k in ('eye_color', 'hair_color', 'skin_tone') if _ident_drift.get(k)
            }
        except Exception:
            _spec_drift = {}
        if _spec_drift:
            _drift_tiles = [
                t
                for t in tiles
                if t.get('identity_verdict') == 'pass'
                and t.get('identity_visibility') == 'frontal'
                and not t.get('vlm_flag')
            ][:_n_attr]
            for t in _drift_tiles:
                _dv = _vlm.judge_attributes(t['path'], _spec_drift, log_fn=None)
                if _dv.get('mismatches') and log_fn:
                    log_fn(
                        f'Attribute drift (warn-only): tile {t.get("index")} — '
                        + ', '.join(
                            f"{a} looks '{v or '?'}' vs bible '{_spec_drift[a]}'" for a, v in _dv['mismatches'].items()
                        ),
                    )
    # Unload the local vision model before regen generations start — it
    # must never sit in VRAM alongside a ComfyUI qwen-edit job.
    _vlm.release()
    if log_fn:
        log_fn(
            f'VLM judge: {_vlm_flagged}/{len(tiles)} tile(s) flagged '
            f'({_vlm_cloud_skipped} strong-pass tiles screened locally only)',
        )
    # Re-evaluate the regen set now that VLM flags exist.
    return _vlm, _vlm_anchor_cell, [t for t in tiles if needs_regen(t, fail_class)]


def step_regen_drifted(
    char_id: str,
    params: dict,
    to_fix: list[dict],
    *,
    anchor: str,
    report: dict,
    fail_class: tuple,
    model_family: str,
    idqc_retries: int,
    idqc: Any,
    vlm: Any,
    vlm_anchor_cell: str | None,
    tiles: list[dict],
    allow_regen: bool,
    progress_job: dict | None,
    halt_check: Callable[[], None] | None,
    log_fn: Callable[[str], None] | None,
) -> int:
    """The regen ladder for drifted/flagged tiles. Returns the repair count."""
    regen_ok = 0
    if to_fix and allow_regen:
        comfy_ok, comfy_reason = _csp._comfy_availability()
        if not comfy_ok:
            if log_fn:
                log_fn(f'Identity QC: {len(to_fix)} drifted cells but no Comfy ({comfy_reason}) — flag only')
        else:
            if log_fn:
                log_fn(f'Identity QC: regenerating {len(to_fix)} drifted cell(s), max {idqc_retries} attempts each')
            for t in to_fix:
                if callable(halt_check):
                    halt_check()
                if progress_job is not None:
                    progress_job['sheet_substage'] = f'idqc_regen_{int(t.get("index", 0)):03d}'
                angle = t.get('angle') or ''
                # Content-corrupt originals (multi_face/face_cut) must always be
                # replaced by any structurally clean candidate, so their prior
                # cosine score does not compete against candidates.
                # 'no_face' counts as corrupt too: its cosine is untrusted, so it
                # must not out-rank a clean scored candidate.
                orig_corrupt = t.get('identity_verdict') in (
                    'multi_face',
                    'face_cut',
                    'mislabeled_angle',
                    'no_face',
                    'bad_orientation',
                )
                # A VLM-flagged original must always yield to a clean candidate,
                # and its identity score is beside the point. But when identity
                # was fine (verdict 'pass'), a replacement must ALSO be
                # identity-clean — dropping the score floor entirely would let a
                # different-person 0.05 'fail' candidate overwrite the tile.
                _orig_vlm_only = bool(t.get('vlm_flag')) and t.get('identity_verdict') == 'pass'
                if t.get('vlm_flag'):
                    orig_corrupt = True
                # Runway-style chaining reference for attempt 2+: the passing
                # cell nearest in view class — a smaller pose delta gives the
                # edit model less room to hallucinate than re-editing the
                # frontal anchor with the identical failing recipe. Full-body
                # tiles never chain: their reference must carry the complete
                # outfit (cell_00_body), which a head-and-shoulders cell lacks.
                _chain_ref = (
                    None
                    if _csp._is_full_body_angle(t.get('angle') or '')
                    else _csp._nearest_passing_reference(tiles, t)
                )
                best_score = (
                    t.get('identity_score')
                    if isinstance(t.get('identity_score'), (int, float)) and not orig_corrupt
                    else -1.0
                )
                best_path: str | None = None
                best_verdict: str | None = None
                best_result: dict | None = None
                for attempt in range(1, idqc_retries + 1):
                    cand = _csp._regenerate_tile_cell(
                        char_id,
                        params,
                        t,
                        anchor,
                        model_family=model_family,
                        attempt=attempt,
                        log_fn=log_fn,
                        chain_reference=_chain_ref if attempt >= 2 else None,
                    )
                    if not cand:
                        continue
                    cand_rep = idqc.score_images_against_anchor(
                        anchor,
                        [{'path': cand, 'angle': angle}],
                        profile_anchor_path=_csp.identity_profile_anchor_face_path(char_id),
                    )
                    cr = (cand_rep.get('results') or {}).get(cand) or {}
                    c_score = cr.get('score')
                    c_verdict = cr.get('verdict')
                    if log_fn:
                        log_fn(
                            f'Identity QC regen tile {t.get("index")} attempt {attempt}: score {c_score} ({c_verdict})',
                        )
                    # A candidate that is itself content-corrupt never replaces.
                    if c_verdict in fail_class and c_verdict != 'fail':
                        continue
                    # Weak detection => untrusted cosine; never accept blind.
                    if c_verdict == 'no_face':
                        continue
                    # A VLM-flagged-but-identity-pass original may only be
                    # replaced by an identity-CLEAN candidate — the vlm_flag
                    # zeroed best_score, so this is the remaining floor.
                    if _orig_vlm_only and c_verdict not in ('pass', 'no_face_expected'):
                        continue
                    # A VLM-flagged candidate never replaces — a repair that
                    # reintroduces a ghost is not a repair. Judged AFTER the
                    # free checks above (no paid call for doomed candidates);
                    # release immediately — a ComfyUI generation likely follows.
                    if vlm is not None and cand:
                        _cj = vlm.judge_cell(
                            cand,
                            anchor_path=vlm_anchor_cell,
                            angle=angle,
                            log_fn=log_fn,
                        )
                        vlm.release()
                        if _cj.get('flagged'):
                            if log_fn:
                                log_fn(
                                    f'Identity QC regen tile {t.get("index")} attempt {attempt}: '
                                    f'candidate VLM-flagged ({(_cj.get("defect") or "defect")[:80]}) — rejected',
                                )
                            continue
                    # Structurally clean back view (no detectable face) is the BEST
                    # possible outcome for a back-labeled tile — it has no score to
                    # rank, so accept it outright instead of discarding it.
                    if c_verdict == 'no_face_expected' and c_score is None:
                        best_score = -1.0
                        best_path = cand
                        best_verdict = c_verdict
                        best_result = cr
                        break
                    if isinstance(c_score, (int, float)) and c_score > (best_score if best_score is not None else -1.0):
                        best_score = c_score
                        best_path = cand
                        best_verdict = c_verdict
                        best_result = cr
                        # Only stop early on a STRONG pass — a barely-passing
                        # 0.32-ish repair should let the next attempt try for a
                        # better score instead of locking in a weak tile (fix F).
                        if c_verdict == 'no_face_expected' or (
                            c_verdict == 'pass' and c_score >= _csp.IDQC_REGEN_MIN_SCORE
                        ):
                            break
                # A sub-floor 'pass' replacement is usually a DIFFERENT person
                # (run ac97acfb: tile 47's 0.259 IP-Adapter replacement was a
                # visibly different woman shipped in the master sheet). Keep the
                # original tile in the sheet — it at least depicts the right
                # character — and keep the cell out of the LoRA dataset.
                _sheet_floor = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_SHEET_MIN', '0.30'))
                _too_dissimilar = (
                    best_path is not None
                    and best_verdict == 'pass'
                    and isinstance(best_score, (int, float))
                    and 0 <= best_score < _sheet_floor
                )
                if _too_dissimilar:
                    t['exclude_from_dataset'] = True
                    t['weak_identity'] = True
                    if log_fn:
                        log_fn(
                            f'Identity QC regen tile {t.get("index")}: best candidate '
                            f'similarity {best_score:.3f} < sheet floor {_sheet_floor:g} '
                            f'— likely a different person; keeping the original tile '
                            f'in the sheet, cell excluded from the LoRA dataset',
                        )
                elif best_path:
                    shutil.copy2(best_path, t['path'])
                    t['identity_score'] = (
                        round(float(best_score), 4) if best_score is not None and best_score >= 0 else None
                    )
                    t['identity_verdict'] = best_verdict or 'fail'
                    t['face_detected'] = best_verdict != 'no_face_expected'
                    t['regenerated'] = True
                    # The accepted candidate passed the VLM judge — clear flags.
                    t['vlm_flag'] = False
                    t.pop('vlm_defect', None)
                    # Refresh the report entry (incl. bbox) so the texture gate
                    # below scores the image that actually shipped, not the
                    # replaced original.
                    if best_result:
                        report['results'][t['path']] = dict(best_result)
                    regen_ok += 1
                    # A repaired-but-weak tile (below the regen floor) stays in the
                    # sheet but is kept OUT of the LoRA dataset (fix F).
                    if (
                        isinstance(best_score, (int, float))
                        and best_score >= 0
                        and best_score < _csp.IDQC_REGEN_MIN_SCORE
                        and best_verdict == 'pass'
                    ):
                        t['exclude_from_dataset'] = True
                        t['weak_identity'] = True
    return regen_ok
