# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of _render_char_preview_slots, each with explicit parameters.

Extracted from char_state_service/render_slots.py by the 2026-10 function-size
split: the 336-line stage-1d renderer is now an orchestrator that calls these in
the same order, with the same log lines, the same sidecars and the same result
dict. Only generate_slot_image() reaches ComfyUI; the conditioning, the seed
budget, the refusals and the warnings are plain data transforms and are tested as
such.
"""

import copy
import os
from dataclasses import dataclass
from typing import Any

from zyg_workflows.char_state_service._common import (
    _preview_env_on,
    _zyg_log,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _char_effective_hybrid_preview,
    _char_family_lora_weights_exist,
    _char_is_photoreal_style,
    _char_preview_slot_lora_path,
    _char_render_style,
    _char_restyle_profile,
)
from zyg_workflows.char_state_service.preview_provenance import (
    _write_preview_provenance,
)
from zyg_workflows.char_state_service.preview_qa import (
    _generate_preview_slot_best_of_n,
)
from zyg_workflows.char_state_service.preview_reference import (
    _char_is_blender_dataset,
    _pick_char_preview_reference_for_slot,
    _preview_backend_tier,
)
from zyg_workflows.pipeline_config import (
    _CHAR_DRIFT_ANIMATED,
    _CHAR_DRIFT_MIN,
    _PREVIEW_FACE_SEED_CANDIDATES,
    _PREVIEW_SEED_CANDIDATES,
)


@dataclass
class SlotRun:
    """Everything a single preview run holds constant across its slots.

    pkg is the character package every slot deep-copies, render_lc the render
    style this run follows, slot_restyle the restyle name its sidecars record,
    front_slot the slot the seed budget and the drift reference belong to, and
    base_seed the per-character seed every slot offsets from.
    """

    char_id: str
    dataset_dir: str
    pkg: dict
    params: dict
    info: dict
    mf: str
    blender_ds: bool
    front_slot: str
    render_lc: str
    slot_restyle: str
    base_seed: int
    log_fn: Any


def early_preview_result(mf: str, *, skipped: bool, error, warning: str, quality_ok: bool) -> dict:
    """The result dict for a preview run that never rendered anything.

    Two callers: the preview already on disk (skipped, quality OK) and ComfyUI
    being unavailable (not skipped, an error and a warning). The shape is the
    same one a real run returns, so a consumer never has to special-case it.
    """
    return {
        'rendered': [],
        'skipped': skipped,
        'lora_used': False,
        'error': error,
        'backend': mf,
        'preview_quality_ok': quality_ok,
        'preview_warning': warning,
        'backends': [],
        'slot_meta': {},
    }


def load_bible_package(char_id: str, info: dict) -> None:
    """Put the character bible package into info['package'] when it is missing.

    A preview without the package renders without the character's conditioning,
    so this is tried once per run; a bible that will not load is a debug line,
    not a failure.
    """
    if not info.get('package'):
        try:
            from zyg_workflows import character_bible_service as _cbs_hp

            _pkg_hp = _cbs_hp.load(char_id)
            if _pkg_hp:
                info['package'] = _pkg_hp
        except Exception as _exc:
            _zyg_log.debug('bible package not loaded for the preview: %s', _exc)


def wait_for_preview_vram(log_fn) -> None:
    """Wait for enough free VRAM to render a preview, if the client can say.

    Best effort: a client that cannot be imported or cannot measure is a debug
    line — the render is attempted anyway, exactly as before.
    """
    try:
        from zyg_workflows import _comfy_client as _cc_prev

        _cc_prev.wait_for_free_vram_gb(
            min_free_gb=10.0,
            timeout_s=120,
            poll_s=5.0,
            try_evict=True,
            log_fn=log_fn,
        )
    except Exception as _exc:
        _zyg_log.debug('vram wait before the preview skipped: %s', _exc)


def preview_checkpoint_label(mf: str, hybrid: bool) -> str:
    """The checkpoint name the log line announces for this render."""
    return 'hybrid SDXL front + FLUX face' if hybrid else ('SDXL 1.0 base' if mf == 'sdxl' else 'FLUX')


def resolve_render_style(mf: str, params: dict, info: dict) -> str:
    """The render style THIS render must follow, as a lowercase word.

    2026-07-27: restyle (Arcane) chars keep render_style='photorealistic' in the
    bible but must NOT take the photoreal preview branches (pore pass, photoreal
    best-of-N reward). Resolve the sentinel locally — never mutate the shared info.
    SDXL-only: a restyle char also has a photoreal FLUX twin leg whose preview must
    stay photoreal — never arcane-ify the FLUX preview.
    """
    if mf == 'sdxl' and _char_restyle_profile(params, info):
        return 'restyle'
    return _char_render_style(params, info)


def preview_conditioning_state(char_id: str, params: dict, info: dict, dataset_dir: str, mf: str, job: dict) -> dict:
    """What the whole run needs to know before the first slot renders.

    Returns {'pkg', 'hybrid', 'has_lora', 'blender_ds', 'label'}. InstantID is
    turned off on the shared package here, as it always was, before any slot
    deep-copies it.
    """
    pkg = info.get('package') or {}
    cond = (pkg.get('conditioning') or {}) if isinstance(pkg, dict) else {}
    hybrid = mf == 'flux' and _char_effective_hybrid_preview(
        params,
        info,
        char_id=char_id,
        dataset_dir=dataset_dir,
    )
    has_lora = bool(
        _char_preview_slot_lora_path(cond, 'flux' if mf == 'flux' else 'sdxl', char_id, dataset_dir)
        or (hybrid and _char_preview_slot_lora_path(cond, 'sdxl', char_id, dataset_dir))
    )
    blender_ds = _char_is_blender_dataset(info, job)
    pkg.setdefault('conditioning', {})['instantid_enabled'] = False
    return {
        'pkg': pkg,
        'hybrid': hybrid,
        'has_lora': has_lora,
        'blender_ds': blender_ds,
        'label': preview_checkpoint_label(mf, hybrid),
    }


def slot_block_reason(
    char_id: str,
    dataset_dir: str,
    *,
    pslot: str,
    slot_mf: str,
    has_lora_slot: bool,
    ref_image,
    log_fn,
) -> str:
    """Why this slot must not be rendered, or '' when it may be.

    2026-07-31: same fail-closed rule as the in-process FLUX path — when trained
    weights for this family EXIST on disk but did not resolve, we must not degrade
    to an identity-free txt2img / img2img-from-reference render and file it under
    the character's name.  (Untrained characters keep the legitimate reference
    fallback: nothing was trained, so nothing is being misrepresented.)

    Returns the error code the run records ('lora_unresolved', 'no_reference_image')
    and logs the same line the tool used to log.
    """
    if (
        not has_lora_slot
        and _preview_env_on('ZYG_PREVIEW_REQUIRE_LORA')
        and _char_family_lora_weights_exist(char_id, dataset_dir, slot_mf)
    ):
        log_fn(
            f'ERROR: preview slot {pslot}: {slot_mf.upper()} LoRA weights exist on disk '
            f'but did not resolve — refusing to render {char_id[:8]} without its adapter',
        )
        return 'lora_unresolved'
    if not has_lora_slot and not ref_image:
        log_fn(f'Preview slot {pslot}: no reference and no LoRA ({slot_mf})')
        return 'no_reference_image'
    return ''


def slot_conditioning(pkg: dict, *, slot_mf: str, slot_lora, render_lc: str, params: dict) -> dict:
    """A per-slot deep copy of the character package, conditioned for this slot.

    The slot's own family and LoRA path go in, InstantID stays off, SDXL gets the
    hand detail pass and FLUX does not, a photorealistic render gets the skin pore
    pass, and a requested smile is locked with its face-detail wildcard.
    """
    slot_pkg = copy.deepcopy(pkg)
    _sc = slot_pkg.setdefault('conditioning', {})
    _sc['model_family'] = slot_mf
    _sc['instantid_enabled'] = False
    if slot_mf == 'sdxl':
        _sc['sdxl_lora_path'] = slot_lora
        if not _sc.get('flux_lora_path'):
            _sc['lora_path'] = slot_lora
        _sc['hand_detail_pass'] = True
        _sc.setdefault(
            'hand_detail_strength',
            float(os.environ.get('ZYG_PREVIEW_HAND_DETAIL_DENOISE', '0.42')),
        )
    else:
        _sc['lora_path'] = slot_lora
        _sc['hand_detail_pass'] = False
    if render_lc == 'photorealistic':
        _sc['skin_pore_pass'] = True
        _sc['face_detail_strength'] = float(
            os.environ.get('ZYG_PREVIEW_FACE_PORE_DENOISE_PHOTOREAL', '0.38'),
        )
    try:
        from zyg_workflows import character_bible_service as _cbs_sm_prev

        if _cbs_sm_prev.wants_visible_smile(params):
            _sc['smile_requested'] = True
            _sc['smile_locked'] = True
            _sc['face_detail_wildcard'] = _cbs_sm_prev.face_detail_wildcard_for_params(params)
    except Exception as _exc:
        _zyg_log.debug('smile conditioning not resolved from the bible: %s', _exc)
    return slot_pkg


def seed_candidate_count(*, has_lora_slot: bool, slot_mf: str, pslot: str, front_slot: str) -> int:
    """How many seeds to try for this slot before picking the best.

    Only a LoRA-locked slot earns a best-of-N: the front slot gets the full
    budget, a face slot a smaller one, everything else a single seed.
    """
    n_cand = 1
    if has_lora_slot and slot_mf == 'sdxl':
        if pslot == front_slot:
            n_cand = max(1, int(os.environ.get('ZYG_PREVIEW_SEED_CANDIDATES_SDXL', '5')))
        elif 'face' in pslot:
            n_cand = max(1, int(os.environ.get('ZYG_PREVIEW_FACE_SEED_CANDIDATES_SDXL', '2')))
    elif has_lora_slot and slot_mf == 'flux':
        if pslot == front_slot:
            n_cand = _PREVIEW_SEED_CANDIDATES
        elif 'face' in pslot:
            n_cand = _PREVIEW_FACE_SEED_CANDIDATES
    return n_cand


def generate_slot_image(
    cgs_mod,
    *,
    out_png: str,
    prompt: str,
    width: int,
    height: int,
    seed: int,
    n_cand: int,
    slot_pkg: dict,
    char_id: str,
    ref_image,
    slot_mf: str,
    blender_ds: bool,
    mf: str,
    params: dict,
    info: dict,
    pslot: str,
    front_slot: str,
    want_smile: bool,
    log_fn,
):
    """Render one preview slot, best-of-N when it has a seed budget.

    Returns (ok, backend, drift_ok, drift_score) either way.
    """
    if n_cand > 1:
        ok, backend, drift_ok, drift_sc, _used_seed = _generate_preview_slot_best_of_n(
            out_png=out_png,
            prompt=prompt,
            width=width,
            height=height,
            base_seed=seed,
            n_candidates=n_cand,
            character_package=slot_pkg,
            char_id=char_id,
            reference_image=ref_image,
            model_family=slot_mf,
            blender_dataset=blender_ds,
            log_fn=log_fn,
            cgs_mod=cgs_mod,
            check_hands=(slot_mf == 'sdxl' and pslot == front_slot),
            want_smile=want_smile,
            want_photoreal=(
                False
                if (mf == 'sdxl' and _char_restyle_profile(params, info))
                else _char_is_photoreal_style(params, info)
            ),
        )
        return ok, backend, drift_ok, drift_sc
    return cgs_mod.generate_character_preview_still(
        out_png,
        prompt.strip(),
        width=width,
        height=height,
        seed=seed,
        character_package=slot_pkg,
        char_id=char_id,
        reference_image=ref_image,
        model_family=slot_mf,
        log_fn=log_fn,
        blender_dataset=blender_ds,
    )


def write_slot_sidecars(
    out_png: str,
    *,
    pslot: str,
    slot_mf: str,
    prompt: str,
    backend,
    drift_ok,
    drift_sc,
    has_lora_slot: bool,
    slot_lora,
    pkg: dict,
    info: dict,
    char_id: str,
    mf: str,
    slot_restyle: str,
    ref_image,
    log_fn,
) -> None:
    """Write the prompt .txt and the provenance sidecar beside one preview PNG.

    2026-07-31 contract D: provenance sidecar beside every preview PNG.
    lora_used is the TRUTH for this slot: an adapter was resolved AND the
    backend reports a locked (LoRA) render — an img2img/InstantID fallback
    is not "LoRA trained — full character consistency".
    """
    with open(os.path.splitext(out_png)[0] + '.txt', 'w', encoding='utf-8') as _t:
        _t.write(prompt.strip() + '\n')
    _slot_locked = _preview_backend_tier(backend) == 'locked'
    _write_preview_provenance(
        out_png,
        slot=pslot,
        model_family=slot_mf,
        lora_used=bool(has_lora_slot and _slot_locked),
        lora_path=slot_lora if has_lora_slot else None,
        trigger_token=str(info.get('trigger_token') or pkg.get('trigger_token') or ''),
        restyle=slot_restyle,
        backend=str(backend or ''),
        extra={
            'renderer': 'comfy_slots',
            'render_family': mf,
            'tier': _preview_backend_tier(backend),
            'drift_ok': bool(drift_ok),
            'drift_score': float(drift_sc or 0.0),
            'reference_image': ref_image or None,
            'char_id': char_id,
        },
        log_fn=log_fn,
    )


def render_slot(
    run: SlotRun,
    cgs_mod,
    *,
    idx: int,
    slot: tuple,
    rendered: list[str],
    backends: list[str],
    slot_meta: dict,
) -> str:
    """Render ONE preview slot and record it, or say why it was not rendered.

    `slot` is a row of _build_char_preview_slots: (name, prompt, width, height,
    model family). On success the PNG, its backend and its drift land in
    rendered / backends / slot_meta and '' comes back; otherwise the returned
    string is the error the run records as its last_error.
    """
    pslot, pprompt, pw, ph, slot_mf = slot
    log_fn = run.log_fn
    out_png = os.path.join(run.dataset_dir, f'{pslot}.png')
    ref_image = _pick_char_preview_reference_for_slot(run.dataset_dir, run.info, pslot)
    slot_cond = (run.pkg.get('conditioning') or {}) if isinstance(run.pkg, dict) else {}
    slot_lora = _char_preview_slot_lora_path(slot_cond, slot_mf, run.char_id, run.dataset_dir)
    has_lora_slot = bool(slot_lora and os.path.isfile(slot_lora))
    blocked = slot_block_reason(
        run.char_id,
        run.dataset_dir,
        pslot=pslot,
        slot_mf=slot_mf,
        has_lora_slot=has_lora_slot,
        ref_image=ref_image,
        log_fn=log_fn,
    )
    if blocked:
        return blocked
    slot_pkg = slot_conditioning(
        run.pkg,
        slot_mf=slot_mf,
        slot_lora=slot_lora,
        render_lc=run.render_lc,
        params=run.params,
    )
    want_smile = bool((slot_pkg.get('conditioning') or {}).get('smile_requested'))
    try:
        ok, backend, drift_ok, drift_sc = generate_slot_image(
            cgs_mod,
            out_png=out_png,
            prompt=pprompt,
            width=pw,
            height=ph,
            seed=run.base_seed + idx,
            n_cand=seed_candidate_count(
                has_lora_slot=has_lora_slot,
                slot_mf=slot_mf,
                pslot=pslot,
                front_slot=run.front_slot,
            ),
            slot_pkg=slot_pkg,
            char_id=run.char_id,
            ref_image=ref_image,
            slot_mf=slot_mf,
            blender_ds=run.blender_ds,
            mf=run.mf,
            params=run.params,
            info=run.info,
            pslot=pslot,
            front_slot=run.front_slot,
            want_smile=want_smile,
            log_fn=log_fn,
        )
        if not ok:
            log_fn(f'Preview slot {pslot} failed ({backend})')
            return backend or 'preview_failed'
        write_slot_sidecars(
            out_png,
            pslot=pslot,
            slot_mf=slot_mf,
            prompt=pprompt,
            backend=backend,
            drift_ok=drift_ok,
            drift_sc=drift_sc,
            has_lora_slot=has_lora_slot,
            slot_lora=slot_lora,
            pkg=run.pkg,
            info=run.info,
            char_id=run.char_id,
            mf=run.mf,
            slot_restyle=run.slot_restyle,
            ref_image=ref_image,
            log_fn=log_fn,
        )
        rendered.append(out_png)
        backends.append(backend)
        slot_meta[pslot] = {
            'backend': backend,
            'tier': _preview_backend_tier(backend),
            'drift_ok': drift_ok,
            'drift_score': drift_sc,
        }
        log_fn(f'Saved {pslot}.png via {backend} (drift={drift_sc:.3f})')
    except Exception as _pe:
        log_fn(f'Preview slot {pslot} failed: {_pe}')
        return str(_pe)[:200]
    return ''


def register_front_reference(char_id: str, rendered: list[str], front_slot: str, slot_meta: dict, log_fn) -> None:
    """Register the LOCKED front preview as the character's drift reference.

    Only a locked render may become the reference: an img2img fallback would make
    the Blender mannequin the thing every later render is compared against.
    """
    if not (char_id and rendered):
        return
    front_png = next(
        (p for p in rendered if p.endswith(f'{front_slot}.png')),
        rendered[0],
    )
    locked_front = _preview_backend_tier((slot_meta.get(front_slot) or {}).get('backend', '')) == 'locked'
    if locked_front and front_png and os.path.isfile(front_png):
        try:
            from zyg_workflows import consistency_qa_service as _cqa_reg

            _cqa_reg.register_reference(char_id, front_png, log_fn=log_fn)
            log_fn('Consistency QA: preview registered as drift reference')
        except Exception as _cqa_e:
            log_fn(f'Consistency QA preview reference warning: {_cqa_e}')


def preview_warnings(
    mf: str,
    params: dict,
    info: dict,
    *,
    rendered: list[str],
    slot_meta: dict,
    front_slot: str,
    job: dict,
) -> tuple[bool, list[str]]:
    """Judge the front preview: (preview_quality_ok, warnings).

    A locked front render passes; its drift is reported, never used to fail it.
    An img2img or otherwise unlocked front render does not pass and says why.
    """
    front_meta = slot_meta.get(front_slot) or {}
    front_tier = front_meta.get('tier', 'other')
    front_drift_ok = bool(front_meta.get('drift_ok', False))
    front_drift_sc = float(front_meta.get('drift_score') or 0.0)
    render_lc = (
        (
            ((info.get('package') or {}).get('style_profile') or {}).get('render_style')
            or params.get('render_style')
            or params.get('style')
            or ''
        )
        .strip()
        .lower()
    )
    if mf == 'sdxl' and _char_restyle_profile(params, info):
        render_lc = 'restyle'
    # A painterly Arcane front render diverges more from the photoreal reference — use
    # the relaxed animated floor for the (informational) drift warning.
    drift_thr = _CHAR_DRIFT_ANIMATED if render_lc in ('animated', 'restyle') else _CHAR_DRIFT_MIN
    warnings: list[str] = []
    preview_quality_ok = False
    if rendered and front_tier == 'locked':
        preview_quality_ok = True
        if not front_drift_ok:
            # 2026-07-31: check_drift now reports an explicit "unknown" (-1.0)
            # when the character has no cached reference embedding, instead of
            # the old hardcoded pass. That is not drift — say so, rather than
            # printing "Identity drift -1.000 below 0.60".
            if front_drift_sc < 0:
                warnings.append(
                    'Identity NOT verified — no reference embedding for this '
                    'character (locked render OK — review preview)',
                )
            else:
                warnings.append(
                    f'Identity drift {front_drift_sc:.3f} below {drift_thr:.2f} (locked render OK — review preview)',
                )
    elif rendered:
        if front_tier == 'img2img':
            warnings.append(
                'Front preview used img2img fallback (may clone Blender mannequin — re-run with LoRA)',
            )
        elif front_tier != 'locked':
            warnings.append('Front preview did not use LoRA-locked txt2img')
    if job.get('lora_failed') and front_tier == 'img2img':
        warnings.append('LoRA training failed; only img2img fallback produced images')
    return preview_quality_ok, warnings
