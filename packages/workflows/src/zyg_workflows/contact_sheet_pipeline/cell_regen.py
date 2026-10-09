# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-cell regeneration and best-of-N candidate selection.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 3805-4083).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    IDQC_REGEN_IPA_SCALE,
    SHEET_B_I2I_DENOISE,
    _INSTANTID_REGEN_ENABLED,
    _zyg_log,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _anchor_cell_path,
    _angle_label,
    _body_anchor_path_for,
    tiles_dir,
    trigger_token_for,
)
from zyg_workflows.contact_sheet_pipeline.angle_edit import (
    _cell_size_for_angle,
    _closeup_crop_from,
    _is_closeup_zoom_angle,
    _is_full_body_angle,
    _is_relight_angle,
    _lighting_grade_kind,
    _qwen_angle_instruction,
    _strip_detailer_for_steep,
)
from zyg_workflows.contact_sheet_pipeline.sheet_prep import (
    _build_sheet_character_package,
    caption_style_description,
)


def _regenerate_tile_cell(
    char_id: str,
    params: dict,
    tile: dict,
    anchor_face: str,
    *,
    model_family: str = 'flux',
    attempt: int = 1,
    log_fn: Callable[[str], None] | None = None,
    chain_reference: str | None = None,
) -> str | None:
    """One per-cell regen at export size with IP-Adapter face lock. Returns candidate path."""
    import copy

    from zyg_workflows import comfy_generation_service as _cgs

    mf = (model_family or 'flux').strip().lower()
    if mf not in ('flux', 'sdxl', 'qwen', 'klein'):
        mf = 'flux'
    pkg = _build_sheet_character_package(char_id, params, mf, log_fn=log_fn)
    gen_pkg = copy.deepcopy(pkg) if pkg else {}
    cond = gen_pkg.setdefault('conditioning', {})
    cond['hand_detail_pass'] = False
    cond['instantid_enabled'] = False
    cond['ipadapter_scale'] = IDQC_REGEN_IPA_SCALE

    trigger = trigger_token_for(char_id)
    style_extra = caption_style_description((params or {}).get('style', 'photorealistic'))
    angle = tile.get('angle') or _angle_label(int(tile.get('index', 0)))
    scene = (
        f'{angle}, single person, exact same person as reference, neutral studio background, {style_extra}, {trigger}'
    )
    prompt = _cgs.build_locked_prompt(scene, pkg, studio_preview=True)
    out = os.path.join(
        tiles_dir(char_id),
        f'regen_{int(tile.get("index", 0)):03d}_{attempt}.png',
    )
    cell_w, cell_h = _cell_size_for_angle(angle)
    # Close-up regen by CROP (2026-07-21): a close-up regen through Qwen would
    # re-introduce the zoom double-exposure (both Bianca tile-11 regens failed
    # this way). Crop the head from the anchor cell instead — no scale change,
    # no ghost; the caller scores it and a crop of the anchor passes identity.
    if os.environ.get('ZYG_CLOSEUP_CROP', '1').strip().lower() not in ('0', 'false', 'no', 'off') and (
        _is_closeup_zoom_angle(angle) or _is_relight_angle(angle)
    ):
        _cu_anchor = _anchor_cell_path(char_id)
        _cu_relight = _is_relight_angle(angle)
        _cu_light = _lighting_grade_kind(angle)
        _cu_tight = (not _cu_relight) and any(k in angle.lower() for k in ('fill frame', 'extreme close'))
        if os.path.isfile(_cu_anchor) and _closeup_crop_from(
            _cu_anchor,
            cell_w,
            cell_h,
            out,
            tight=_cu_tight,
            lighting=_cu_light,
            log_fn=log_fn,
        ):
            if log_fn:
                _why = f'relight ({_cu_light}) by CROP+grade' if _cu_relight else 'close-up by CROP'
                log_fn(
                    f'Identity QC regen tile {tile.get("index")}: {_why} from anchor (no Qwen re-synthesis, no ghost)',
                )
            return out
    gen_kwargs: dict[str, Any] = {
        'width': cell_w,
        'height': cell_h,
        'steps': int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '28')),
        'cfg': float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5')),
        'seed': int(uuid.uuid4().int % (2**31)),
        'character_package': gen_pkg,
        'char_id': char_id,
        'model_family': mf,
        'log_fn': log_fn,
        'skip_qa': True,
        'studio_preview': True,
        'prompt_finalized': True,
        'extra_negative': ('blurry, low quality, different person, inconsistent identity, deformed face'),
    }
    if mf == 'flux':
        gen_kwargs['force_unet'] = os.environ.get('ZYG_CONTACT_SHEET_UNET', 'flux1-dev.safetensors')
        gen_kwargs['flux_guidance'] = gen_kwargs['cfg']
    # Repair strategy = the same engine the main sheet uses. The old attempt-2
    # escalation to `flux_character_instantid` submitted a 400 "outputs failed
    # validation" on this box and never actually ran, so drifted tiles just got
    # excluded. Instead re-edit the photographic anchor CELL (not the face crop)
    # with Qwen — the proven path that produced every clean rotation/back cell.
    _instruction = _qwen_angle_instruction(angle, params)
    _anchor_cell = _anchor_cell_path(char_id)
    # Full-body regens reference the body anchor (outfit + shoes); head cells
    # keep the head anchor so the face reaches the edit model at full size.
    _body_anchor = _body_anchor_path_for(char_id)
    if _is_full_body_angle(angle) and os.path.isfile(_body_anchor):
        _anchor_cell = _body_anchor
    try:
        _qwen_ok = bool(_cgs.has_qwen_edit_angles())
    except Exception:
        _qwen_ok = False
    _use_instantid = (
        _INSTANTID_REGEN_ENABLED
        and attempt >= 2
        and mf == 'flux'
        and _cgs.has_instantid()
        and tile.get('identity_visibility') != 'back'
    )
    # Escalation ladder (2026-07-16): attempt 1 re-rolls the proven qwen
    # anchor-edit with a fresh seed; attempt 2 CHANGES CONDITIONING — chain
    # from the nearest passing cell when one exists (smaller pose delta),
    # else switch METHOD to the FLUX IP-Adapter identity path. The same qwen
    # recipe failing twice is systematic (the Kira Dunn run returned no_face
    # on both identical qwen retries for four tiles), not seed luck.
    _chain_ok = bool(chain_reference and os.path.isfile(chain_reference) and _qwen_ok and _instruction)
    try:
        _ipa_switch = (
            attempt >= 2
            and mf == 'flux'
            and tile.get('identity_visibility') != 'back'
            and not _use_instantid
            and not _chain_ok
            and bool(_cgs.has_flux_ipadapter())
        )
    except Exception:
        _ipa_switch = False
    if _chain_ok:
        # Chained regen: the source is no longer the frontal anchor, so the
        # relative rotation instruction would land at the wrong angle — use an
        # absolute description of the target view instead. A wrong-angle
        # result is caught by the yaw/pose gates before it can replace.
        prompt = (
            f'Change the camera view to: {angle}, while keeping the exact same '
            'person with an identical face, identical skin tone and complexion '
            '(do not lighten or change the skin colour), identical skin texture '
            '— do not add, exaggerate or redistribute freckles, spots or '
            'blemishes — identical hairstyle '
            'and clothing, against the same plain studio background. RAW candid '
            'photograph, natural uneven skin with visible pores and fine '
            'texture, subtle film grain, unretouched'
        )
        gen_kwargs['reference_image'] = chain_reference
        gen_kwargs['force_workflow'] = 'qwen_edit_angle'
        _strip_detailer_for_steep(gen_kwargs, angle)
        gen_kwargs.pop('flux_guidance', None)
        if log_fn:
            log_fn(
                f'Identity QC regen tile {tile.get("index")} attempt {attempt}: '
                f'chaining from nearest passing cell '
                f'({os.path.basename(chain_reference)})',
            )
    elif _qwen_ok and _instruction and os.path.isfile(_anchor_cell) and not _ipa_switch and not _use_instantid:
        prompt = _instruction
        gen_kwargs['reference_image'] = _anchor_cell
        gen_kwargs['force_workflow'] = 'qwen_edit_angle'
        _strip_detailer_for_steep(gen_kwargs, angle)
        # qwen_edit_angle originals run at the workflow's default guidance
        # (1.0); passing cfg (3.5) through as flux_guidance pushed every regen
        # into the waxy/render band the 2026-07-09 postmortem flagged. Let the
        # workflow default win so repairs match the cells they replace.
        gen_kwargs.pop('flux_guidance', None)
        if log_fn:
            log_fn(
                f'Identity QC regen tile {tile.get("index")} attempt {attempt}: '
                f're-editing anchor with Qwen (fresh seed)',
            )
    elif _use_instantid:
        cond['instantid_enabled'] = True
        gen_kwargs['reference_image'] = anchor_face
        gen_kwargs['force_workflow'] = 'flux_character_instantid'
        if log_fn:
            log_fn(f'Identity QC regen attempt {attempt}: escalating to InstantID')
    elif mf in ('qwen', 'klein'):
        # Anchor-family qwen/klein: every fallback below is a FLUX graph
        # (IP-Adapter, img2img) — refusing beats silently submitting a
        # licence-paused workflow; the caller's fail-closed exclusion handles
        # the tile (2026-08-09; klein joined 2026-08-23). For klein the reason
        # is identity rather than licence — a FLUX graph cannot carry a klein
        # character — but the correct action is the same: exclude, do not
        # substitute a different model for this person.
        if log_fn:
            log_fn(
                f'Identity QC regen tile {tile.get("index")} attempt {attempt}: '
                f'no {mf} edit path available and model_family={mf} forbids the '
                f'FLUX fallback — tile stays excluded',
            )
        return None
    elif mf == 'flux' and _cgs.has_flux_ipadapter():
        gen_kwargs['reference_image'] = anchor_face
        gen_kwargs['force_workflow'] = 'flux_character_ipadapter'
        if log_fn and _ipa_switch:
            log_fn(
                f'Identity QC regen tile {tile.get("index")} attempt {attempt}: '
                f'switching method to FLUX IP-Adapter (qwen re-edit failed attempt 1)',
            )
    else:
        gen_kwargs['init_image'] = anchor_face
        gen_kwargs['reference_image'] = anchor_face
        gen_kwargs['denoise'] = SHEET_B_I2I_DENOISE
        gen_kwargs['force_workflow'] = 'flux_img2img' if mf == 'flux' else 'sdxl_img2img'

    ok, backend = _cgs.generate_still(out, prompt, **gen_kwargs)
    if not ok or not os.path.isfile(out):
        if log_fn:
            log_fn(f'Identity QC regen attempt {attempt} failed ({backend})')
        return None
    return out


def _generate_cell_best_of(
    cell_path: str,
    prompt: str,
    gen_kwargs: dict,
    n: int,
    anchor_face: str | None,
    angle: str,
    log_fn=None,
    profile_anchor_path: str | None = None,
) -> tuple[bool, str]:
    """Best-of-N first-pass generation (2026-07-16): n fresh-seed candidates,
    keep the one with the best ArcFace verdict/score vs the anchor. Verdict-
    aware ranking: pass/clean-back outranks fail outranks corrupt. Falls back
    to a single generation when identity scoring is unavailable."""
    # Function-local import like every other generation site in this module —
    # this function was dead code (BEST_OF defaulted to 1) until 2026-07-19,
    # and its missing _cgs import killed run d835e071 at cell 2 on first use.
    from zyg_workflows import comfy_generation_service as _cgs

    if n <= 1 or not anchor_face or not os.path.isfile(anchor_face):
        return _cgs.generate_still(cell_path, prompt, **gen_kwargs)
    try:
        from zyg_workflows import identity_qc_service as _idqc

        _ok, _ = _idqc.available()
    except Exception:
        _ok = False
    if not _ok:
        return _cgs.generate_still(cell_path, prompt, **gen_kwargs)
    import shutil as _sh

    best_key: tuple | None = None
    best_path: str | None = None
    last_backend = ''
    cands: list[str] = []
    for k in range(n):
        cand = f'{cell_path}.cand{k}.png'
        kw = dict(gen_kwargs)
        kw['seed'] = int(uuid.uuid4().int % (2**31))
        ok, last_backend = _cgs.generate_still(cand, prompt, **kw)
        if not ok or not os.path.isfile(cand):
            continue
        cands.append(cand)
        try:
            rep = _idqc.score_images_against_anchor(
                anchor_face,
                [{'path': cand, 'angle': angle}],
                profile_anchor_path=profile_anchor_path,
            )
            cr = (rep.get('results') or {}).get(cand) or {}
        except Exception:
            cr = {}
        v = cr.get('verdict')
        s = cr.get('score')
        rank = 2 if v in ('pass', 'no_face_expected') else (1 if v == 'fail' else 0)
        key = (rank, s if isinstance(s, (int, float)) else -1.0)
        if best_key is None or key > best_key:
            best_key = key
            best_path = cand
    if best_path:
        _sh.copy2(best_path, cell_path)
        if log_fn and len(cands) > 1:
            log_fn(
                f'Best-of-{n}: kept candidate rank={best_key[0]} score={best_key[1] if best_key[1] >= 0 else "n/a"}',
            )
    for cand in cands:
        try:
            os.remove(cand)
        except OSError as _exc:
            _zyg_log.debug('best-of candidate %s not removed: %s', cand, _exc)
    return (best_path is not None), last_backend
