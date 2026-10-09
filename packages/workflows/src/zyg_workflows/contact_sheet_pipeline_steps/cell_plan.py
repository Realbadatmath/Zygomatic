# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cell run state, the engine gate, the cell plan and cell conditioning.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 1620-1939).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from zyg_workflows import contact_sheet_pipeline as _csp

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


@dataclass
class CellRun:
    """Per-run conditioning the cell loop and its steps share.

    Built once by `step_cell_conditioning`; every field is the local of the
    same name that `_generate_per_cell_contact_sheet` carried inline. `cdir`
    and `resume_label_ok` are filled in by the caller once they exist, at the
    point in the run where they were computed before the split.
    """

    char_id: str
    params: dict
    log_fn: Callable[[str], None] | None
    progress_job: dict | None
    anchor_family: str
    pkg: dict
    gen_pkg: dict
    render_style: str
    skin_clause: str
    cell_neg: str
    steps: int
    cfg: float
    anchor_skin: str
    anchor_cfg: float
    dark_retry_cfg: float
    base_seed: int
    unet: str
    realism_lora_path: str
    realism_lora_scale: float
    style_extra: str
    trigger: str
    cdir: str = ''
    resume_label_ok: Callable[[int, str], bool] | None = None


def step_engine_gate(aset: str, anchor_family: str, log_fn: Callable[[str], None] | None) -> str:
    """Capability gate for the per-cell engine.

    Returns 'ok' to proceed, 'dual' when the caller must fall back to
    dual-canvas sheets, or 'abort' (the old `return None` sites).
    """
    from zyg_workflows import comfy_generation_service as _cgs

    if anchor_family in ('qwen', 'klein'):
        _qwen_stack_ok = False
        try:
            _t2i_ok = _cgs.has_klein_t2i() if anchor_family == 'klein' else _cgs.has_qwen_t2i()
            _qwen_stack_ok = bool(_cgs.has_qwen_edit_angles() and _t2i_ok)
        except Exception:
            _qwen_stack_ok = False
        if not _qwen_stack_ok:
            if log_fn:
                log_fn(
                    'Per-cell mode: anchor_family=qwen needs the qwen txt2img '
                    'graph + qwen-edit angles; refusing to fall back to a '
                    'licence-paused FLUX path — aborting',
                )
            return 'abort'
    elif not _cgs.has_flux_ipadapter():
        # Forced workflows bypass _pick_workflow's capability gate — without the
        # XLabs node every cell after 00 would be rejected by ComfyUI. Fall back
        # to dual-canvas, which gates its own IPA use. Corpus plans cannot be
        # expressed as dual-canvas sheets — abort instead.
        if aset in ('corpus', 'custom'):
            if log_fn:
                log_fn(
                    f'{aset} mode needs the per-cell engine (FLUX IP-Adapter or '
                    f'anchor_family=qwen) — dual-canvas sheets are fixed 6-cell '
                    f'pages and cannot express this plan; aborting',
                )
            return 'abort'
        if log_fn:
            log_fn(
                'Per-cell mode needs the FLUX IP-Adapter (LoadFluxIPAdapter node) — falling back to dual-canvas sheets',
            )
        return 'dual'
    return 'ok'


def step_build_cell_plan(
    char_id: str,
    aset: str,
    progress_job: dict | None,
    log_fn: Callable[[str], None] | None,
) -> tuple[list[str], dict, Callable[[int, str], bool]] | None:
    """The angle list, the plan record and the plan-versioned resume predicate.

    Returns None on the old `return None` site (angle_set=custom with no valid
    selection). The plan record is persisted as a sidecar later by
    `step_cells_dir` — a paused run has no manifest yet.
    """
    if aset == 'corpus':
        _corpus_detail = _csp.build_corpus_plan_detail(
            (progress_job or {}).get('corpus_cells'),
            log_fn=log_fn,
        )
        angles = list(_corpus_detail['labels'])
    elif aset == 'custom':
        # Operator-picked plan (2026-09-16). Refuse rather than quietly render
        # the 48-angle default: an empty selection here means the request lost
        # its angle list somewhere upstream, and a 4.5h run is the wrong place
        # to discover that.
        _corpus_detail = None
        angles = _csp.custom_angle_labels_for_job(progress_job)
        if not angles:
            if log_fn:
                log_fn(
                    'angle_set=custom but the job carries no valid angle selection (angle_ids/angle_labels) — aborting',
                )
            return None
    else:
        _corpus_detail = None
        angles = _csp.contact_sheet_angle_labels(aset)
    total = len(angles)
    # Plan record (all modes): labels + hash for plan-versioned resume; corpus
    # adds axes + per-cell source labels. Persisted as a sidecar NOW (a paused
    # run has no manifest yet) and into the manifest at completion.
    cell_plan: dict[str, Any] = {
        'angle_set': aset,
        'target': total,
        'hash': _csp._plan_hash(angles),
        'labels': angles,
        'built_at': _csp._ams_iso(),
    }
    if _corpus_detail is not None:
        cell_plan['cells'] = _corpus_detail['cells']
        cell_plan['derived_count'] = _corpus_detail['derived_count']
        cell_plan['derived_frac'] = _corpus_detail['derived_frac']
    # Plan-versioned resume (2026-08-09): a stored plan whose label at an index
    # differs from the fresh plan means cells/cell_NNN.png is NOT that cell —
    # index reuse would caption the wrong angle. Labels are compared per index.
    _stored_plan: dict = {}
    try:
        _stored_plan = (_csp.load_manifest(char_id) or {}).get('cell_plan') or {}
        if not _stored_plan:
            _plan_sidecar = os.path.join(
                _csp.contact_sheet_dir(char_id),
                'cells',
                'cell_plan.json',
            )
            if os.path.isfile(_plan_sidecar):
                with open(_plan_sidecar, encoding='utf-8') as _pf:
                    _stored_plan = json.load(_pf) or {}
    except Exception:
        _stored_plan = {}
    _stored_labels: list[str] = list(_stored_plan.get('labels') or [])
    if not _stored_labels:
        # Pre-upgrade runs stored cell_angles only at completion; a mid-run
        # pause left nothing. classic/extended label lists are deterministic,
        # so legacy resume-by-index stays valid there; corpus never is.
        _stored_labels = list((_csp.load_manifest(char_id) or {}).get('cell_angles') or [])
    _plan_hash_match = bool(_stored_plan) and _stored_plan.get('hash') == cell_plan['hash']

    def _resume_label_ok(idx: int, angle: str) -> bool:
        if _plan_hash_match:
            return True
        if _stored_labels:
            return idx < len(_stored_labels) and _stored_labels[idx] == angle
        return aset != 'corpus'

    return angles, cell_plan, _resume_label_ok


def step_cell_conditioning(
    char_id: str,
    params: dict,
    mf: str,
    anchor_family: str,
    progress_job: dict | None,
    log_fn: Callable[[str], None] | None,
) -> CellRun:
    """VRAM wait, character package, negative prompt, sampler and LoRA settings."""
    try:
        from zyg_workflows import _comfy_client as _cc

        _cc.wait_for_free_vram_gb(
            min_free_gb=22.0,
            timeout_s=int(os.environ.get('ZYG_CONTACT_SHEET_VRAM_WAIT_S', '45')),
            poll_s=5.0,
            try_evict=False,
            log_fn=log_fn,
        )
    except Exception as exc:
        if log_fn:
            log_fn(f'VRAM wait skipped ({exc})')

    import copy

    pkg = _csp._build_sheet_character_package(char_id, params, mf, log_fn=log_fn)
    gen_pkg = copy.deepcopy(pkg) if pkg else {}
    cond = gen_pkg.setdefault('conditioning', {})
    cond['hand_detail_pass'] = False
    cond['instantid_enabled'] = False
    try:
        cond['ipadapter_scale'] = float(
            os.environ.get('ZYG_CONTACT_SHEET_PER_CELL_IPA_SCALE', '0.85'),
        )
    except Exception:
        cond['ipadapter_scale'] = 0.85
    # For photorealistic style, run FaceDetailer with the pore-detail wildcard
    # (visible pores, skin microdetail, no beauty-filter) at denoise 0.52.
    _render_style = (params or {}).get('style', 'photorealistic').lower()
    if _render_style in ('photorealistic', 'photoreal', 'photo'):
        cond['skin_pore_pass'] = True

    trigger = _csp.trigger_token_for(char_id)
    style_extra = _csp.caption_style_description((params or {}).get('style', 'photorealistic'))
    # The anchor (cell_00) is the single skin-tone source for the whole sheet —
    # every Qwen edit inherits its complexion. Reinforce the tone here (in
    # addition to the identity prefix) so a dark selection actually renders and
    # then propagates, instead of drifting light on the anchor.
    try:
        from zyg_workflows import character_bible_service as _cbs_skin

        _skin_desc = _cbs_skin.describe_skin_tone(
            (params or {}).get('skin_tone', ''),
            (params or {}).get('ethnic_heritage', ''),
        )
    except Exception:
        _skin_desc = ''
    _skin_clause = f'{_skin_desc}, ' if _skin_desc else ''
    cell_neg = (
        'blurry, low quality, multiple people, two people, collage, grid of panels, '
        'split image, duplicate faces, inconsistent identity, deformed body, '
        'text, watermark, 3d render, cartoon, doll, illustration, anime, cgi, '
        # anti-illustration cluster: the 2026-07-12 anchor collapsed to
        # manhwa/webtoon dolls for fair-skinned pretty-female descriptors. These
        # terms + the negative now being LIVE (timestep_to_start_cfg fix) + the
        # realism LoRA at 0.80 pull it back to photography (A/B-verified).
        'manhwa, webtoon, korean webtoon, digital painting, concept art, '
        'stylized, cel shading, render, game character, vector art, '
        'airbrushed skin, smooth plastic skin, waxy skin, porcelain doll skin, '
        'poreless skin, silky smooth skin, overly smooth skin, retouched skin, '
        'oversized anime eyes, big eyes, beauty-filter face, '
        'shorts, mini skirt, changed outfit, different clothes, '
        'lingerie, underwear, bare midriff'
    )
    # Freckle governance (mirrors the bible-service anchor negative): unless
    # the character's marks explicitly include freckles, forbid freckle fields
    # — and the smeared-mottling failure mode qwen edits make of them.
    if 'freckle' not in str((params or {}).get('distinctive_marks') or '').lower():
        cell_neg += (
            ', heavy freckles, dense freckle field, freckled face, mottled skin, smeared freckles, scar-like blotches'
        )
    # Symmetric skin-tone defence on qwen cells too (2026-07-21): the anchor is
    # skin-defended at gen time, but qwen edits can still drift the tone (Noor
    # tiles rendered darker than the anchor) — pin the requested tone here.
    try:
        from zyg_workflows import character_bible_service as _cbs_skin

        _skin_neg_cell = _cbs_skin.skin_tone_negatives(
            (params or {}).get('skin_tone', ''),
            (params or {}).get('ethnic_heritage'),
        )
        if _skin_neg_cell:
            cell_neg += ', ' + _skin_neg_cell
        _hair_neg_cell = _cbs_skin.hair_color_negatives(
            (params or {}).get('hair_color', ''),
            (params or {}).get('ethnic_heritage'),
        )
        if _hair_neg_cell:
            cell_neg += ', ' + _hair_neg_cell
        _age_neg_cell = _cbs_skin.age_negatives((params or {}).get('age'))
        if _age_neg_cell:
            cell_neg += ', ' + _age_neg_cell
    except Exception as _exc:
        _zyg_log.warning('bible negatives unavailable, cell negative prompt keeps no skin/hair/age guard: %s', _exc)
    steps = int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '28'))
    cfg = float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5'))
    # Anchor guidance: FLUX-dev distilled guidance >=3.5 is the documented
    # plastic/waxy-skin regime; ~2.4-2.8 is the photoreal sweet spot. The old
    # dark-skin escalation to 4.5 (retry 5.0) airbrushed the one image whose
    # texture every Qwen cell and the LoRA inherit. Complexion is held by the
    # tripled skin-tone prompt clause + the luminance-gate retry below, NOT by
    # guidance; the retry may nudge guidance up but stays below the waxy zone.
    _anchor_skin = (params or {}).get('skin_tone', '').strip().lower()
    _dark_tones = ('olive', 'tan', 'dark', 'deep')
    _anchor_cfg = float(os.environ.get('ZYG_CONTACT_SHEET_ANCHOR_GUIDANCE', '2.6'))
    _dark_retry_cfg = _anchor_cfg
    if _anchor_skin in _dark_tones:
        _dark_retry_cfg = max(
            _anchor_cfg,
            float(os.environ.get('ZYG_CONTACT_SHEET_DARK_ANCHOR_CFG', '3.2')),
        )
    base_seed = int(uuid.uuid4().int % (2**31))
    unet = os.environ.get('ZYG_CONTACT_SHEET_UNET', 'flux1-dev.safetensors')
    # Optional photorealism style LoRA for the anchor cell (e.g. XLabs flux-RealismLora).
    # Set ZYG_CONTACT_SHEET_REALISM_LORA to the .safetensors path. Only applied to
    # the FLUX txt2img anchor and body anchor. NOTE: Qwen edit cells do NOT
    # pixel-inherit the anchor's texture — qwen_edit_angle re-synthesizes from an
    # empty latent at denoise 1.0, the anchor only steers via <=1MP reference
    # latents. The anchor sets identity/outfit; per-cell texture comes from the
    # Qwen sampler settings and the qwen-edit-skin LoRA (see comfy service).
    _realism_lora_path = os.environ.get('ZYG_CONTACT_SHEET_REALISM_LORA', '').strip()
    _realism_lora_scale = float(os.environ.get('ZYG_CONTACT_SHEET_REALISM_LORA_SCALE', '0.7'))
    return CellRun(
        char_id=char_id,
        params=params,
        log_fn=log_fn,
        progress_job=progress_job,
        anchor_family=anchor_family,
        pkg=pkg,
        gen_pkg=gen_pkg,
        render_style=_render_style,
        skin_clause=_skin_clause,
        cell_neg=cell_neg,
        steps=steps,
        cfg=cfg,
        anchor_skin=_anchor_skin,
        anchor_cfg=_anchor_cfg,
        dark_retry_cfg=_dark_retry_cfg,
        base_seed=base_seed,
        unet=unet,
        realism_lora_path=_realism_lora_path,
        realism_lora_scale=_realism_lora_scale,
        style_extra=style_extra,
        trigger=trigger,
    )
