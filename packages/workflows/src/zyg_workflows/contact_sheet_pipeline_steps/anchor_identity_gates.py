# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Anchor face extraction, style gate and skin-luminance gate.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 207-441).
"""

from __future__ import annotations

import os
import uuid
from zyg_workflows import contact_sheet_pipeline as _csp
from .anchor_ctx import AnchorCtx, _anchor_style_check

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_anchor_face(ctx: AnchorCtx) -> None:
    """Cell 00 is the anchor — take a face-DETECTED crop, never a geometric one."""
    import shutil as _sh

    from zyg_workflows import identity_qc_service as _idqc

    ctx.anchor_cell = ctx.cell_path
    # Face-DETECTED anchor — never a geometric crop (Rhea's geometric
    # anchor straddled two panels and weakened all downstream locking).
    try:
        ctx.anchor_face = _idqc.extract_anchor_face(
            ctx.cell_path,
            ctx.anchor_path,
            log_fn=ctx.log_fn,
        )
    except Exception as _a_exc:
        if ctx.log_fn:
            ctx.log_fn(f'Anchor detection failed ({_a_exc}) — using full cell 00')
        ctx.anchor_face = None
    ctx.anchor_face_detected = bool(ctx.anchor_face)
    if not ctx.anchor_face:
        _sh.copy2(ctx.cell_path, ctx.anchor_path)
        ctx.anchor_face = ctx.anchor_path


def step_style_gate(ctx: AnchorCtx) -> None:
    """Anchor style gate — the anchor seeds every cell and the LoRA.

    The anchor seeds every downstream cell + the LoRA, so a
    non-photographic anchor wastes the whole 4.5h run (2026-07-12).
    TWO checks, both required for photoreal characters:
      1. ArcFace face-detectable (full cartoon collapse is undetectable)
      2. cheek-band texture >= floor — the A/B proved semi-render dolls
         ARE detectable (det 0.90) but measure ~25 texture vs ~112 for
         true photos, so detectability alone lets dolls through.
    On failure: retry once with the realism LoRA cranked, then park via
    PipelinePaused (NOT pause()+return: a plain return became a
    RuntimeError -> status='error' (unresumable), and the persistent
    pause flag re-parked every future run of the char at cell 0).
    """
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import identity_qc_service as _idqc

    char_id = ctx.char_id
    cell_path = ctx.cell_path
    anchor_path = ctx.anchor_path
    log_fn = ctx.log_fn
    gen_kwargs = ctx.gen_kwargs
    prompt = ctx.prompt
    _cell0_reused = ctx.cell0_reused
    _anchor_family = ctx.anchor_family
    _realism_lora_path = ctx.realism_lora_path
    _realism_lora_scale = ctx.realism_lora_scale

    if ctx.photoreal and ctx.style_gate_on:
        ctx.sg_floor = float(os.environ.get('ZYG_ANCHOR_STYLE_GATE_LAPVAR', '50'))
        _sg_pass, _sg_why = _anchor_style_check(ctx)
        if not _sg_pass and _cell0_reused:
            # Verify-only on resume: the cells already cloned this
            # anchor — a regen or park helps nothing now. Record it.
            if log_fn:
                log_fn(
                    f'Style gate (verify-only, resume): anchor below floor ({_sg_why}) — noted',
                )
            _sg_pass = True
        if not _sg_pass:
            if log_fn:
                log_fn(f'Style gate: anchor failed ({_sg_why}) — retrying with stronger realism')
            _sg_kw = dict(gen_kwargs)
            _sg_kw['seed'] = int(uuid.uuid4().int % (2**31))
            _sg_scale = max(_realism_lora_scale, float(os.environ.get('ZYG_ANCHOR_STYLE_GATE_LORA_SCALE', '0.9')))
            # Realism LoRA is FLUX-arch — never on the qwen/klein anchor.
            if _anchor_family not in ('qwen', 'klein') and _realism_lora_path and os.path.isfile(_realism_lora_path):
                _sg_kw['style_lora_path'] = _realism_lora_path
                _sg_kw['style_lora_scale'] = _sg_scale
            _sg_ok, _sg_b = _cgs.generate_still(cell_path, prompt, **_sg_kw)
            if _sg_ok and os.path.isfile(cell_path):
                try:
                    ctx.anchor_face = _idqc.extract_anchor_face(cell_path, anchor_path, log_fn=log_fn)
                except Exception:
                    ctx.anchor_face = None
                ctx.anchor_face_detected = bool(ctx.anchor_face)
                if not ctx.anchor_face:
                    import shutil as _sh_sg

                    _sh_sg.copy2(cell_path, anchor_path)
                    ctx.anchor_face = anchor_path
            _sg_pass, _sg_why = _anchor_style_check(ctx)
        if not _sg_pass:
            if log_fn:
                log_fn(
                    f'Style gate FAILED after retry ({_sg_why}) — parking run '
                    f'(set ZYG_ANCHOR_STYLE_GATE=0 to override)',
                )
            from zyg_workflows import pipeline_control as _pc_sg

            raise _pc_sg.PipelinePaused(char_id, f'anchor style gate: {_sg_why}')
        elif log_fn:
            log_fn(f'Style gate OK ({_sg_why})')


def step_skin_luminance_gate(ctx: AnchorCtx) -> None:
    """Symmetric skin-tone luminance gate on the anchor face crop."""
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import identity_qc_service as _idqc

    cell_path = ctx.cell_path
    anchor_path = ctx.anchor_path
    log_fn = ctx.log_fn
    gen_kwargs = ctx.gen_kwargs
    prompt = ctx.prompt
    _cell0_reused = ctx.cell0_reused
    _anchor_skin = ctx.anchor_skin
    _anchor_cfg = ctx.anchor_cfg
    _dark_retry_cfg = ctx.dark_retry_cfg
    anchor_cell = ctx.anchor_cell
    anchor_face = ctx.anchor_face

    # Skin-tone luminance gate — SYMMETRIC (2026-07-21). Checks the mean
    # green-channel of the face crop (green tracks perceived skin
    # brightness without a full colour-space transform). Dark tones have
    # a CEILING (too fair → retry darker); light tones now also have a
    # FLOOR (too dark → retry lighter), so a fair/light request that the
    # heritage prior dragged brown is caught and re-rolled — before this
    # only the dark side was defended. Thresholds are 0-255 mean green.
    _lum_ceil = {'tan': 165, 'olive': 195, 'dark': 170, 'deep': 130}
    _lum_floor = {'fair': 150, 'light': 130, 'medium-light': 115, 'medium': 100}
    if (_anchor_skin in _lum_ceil or _anchor_skin in _lum_floor) and anchor_face and os.path.isfile(anchor_face):
        try:
            from PIL import Image as _PILImg
            import statistics as _stats

            # Measure SKIN luminance (central band), not the whole crop —
            # the crop's hair headroom would false-trip the fair floor.
            _mean_g = _csp._anchor_skin_luma(anchor_face)
            if _mean_g is None:
                _face_img = _PILImg.open(anchor_face).convert('RGB')
                _mean_g = _stats.mean([p[1] for p in _face_img.getdata()])
            _too_fair = _anchor_skin in _lum_ceil and _mean_g > _lum_ceil[_anchor_skin]
            _too_dark = _anchor_skin in _lum_floor and _mean_g < _lum_floor[_anchor_skin]
            _drift = _too_fair or _too_dark
            if _drift and _cell0_reused:
                if log_fn:
                    _bound = _lum_ceil.get(_anchor_skin) if _too_fair else _lum_floor.get(_anchor_skin)
                    log_fn(
                        f'Anchor skin-tone check (verify-only, resume): mean green '
                        f'{_mean_g:.1f} vs bound {_bound} ({"too fair" if _too_fair else "too dark"}) '
                        f'— noted, no retry',
                    )
            elif _drift:
                # Too-fair → push darker (boosted guidance); too-dark →
                # re-roll at base guidance (the symmetric anti-dark
                # negative + the fair-skin prompt clause do the
                # lightening; boosting guidance here would only invite
                # the waxy-skin regime).
                _retry_cfg = _dark_retry_cfg if _too_fair else _anchor_cfg
                if log_fn:
                    log_fn(
                        f'Anchor skin-tone check: mean green {_mean_g:.1f} '
                        f'{"exceeds ceiling" if _too_fair else "below floor"} for tone '
                        f'"{_anchor_skin}" — retrying anchor {"darker" if _too_fair else "lighter"} '
                        f'(cfg {_retry_cfg:g}, new seed)',
                    )
                # Back up the pre-retry anchor so a retry that did NOT
                # move in the desired direction can be reverted — the
                # floor can false-trigger when dark hair drags the crop's
                # mean green down on an otherwise-fine fair face, and a
                # blind replace would swap a good anchor for a worse one.
                import shutil as _sh2

                _lum_backup = cell_path + '.lumbak.png'
                try:
                    _sh2.copy2(cell_path, _lum_backup)
                except OSError:
                    _lum_backup = None
                _retry_kwargs = dict(gen_kwargs)
                _retry_kwargs['seed'] = int(uuid.uuid4().int % (2**31))
                _retry_kwargs['cfg'] = _retry_cfg
                _retry_kwargs['flux_guidance'] = _retry_cfg
                _ok2, _b2 = _cgs.generate_still(cell_path, prompt, **_retry_kwargs)
                if _ok2 and os.path.isfile(cell_path):
                    try:
                        _new_face = _idqc.extract_anchor_face(
                            cell_path,
                            anchor_path,
                            log_fn=log_fn,
                        )
                    except Exception:
                        _new_face = None
                    # Only KEEP the retry if it actually moved toward the
                    # target: darker (lower green) when too-fair, lighter
                    # (higher green) when too-dark. Otherwise revert.
                    _keep_retry = True
                    try:
                        _measure = _new_face if (_new_face and os.path.isfile(_new_face)) else cell_path
                        _new_g = _csp._anchor_skin_luma(_measure)
                        if _new_g is None:
                            _ni = _PILImg.open(_measure).convert('RGB')
                            _new_g = _stats.mean([px[1] for px in _ni.getdata()])
                        _keep_retry = (_new_g < _mean_g) if _too_fair else (_new_g > _mean_g)
                        _delta_txt = f'skin green {_mean_g:.1f} → {_new_g:.1f}'
                    except Exception:
                        _delta_txt = 'delta unknown'
                    if _keep_retry:
                        anchor_face = _new_face
                        if not anchor_face:
                            _sh2.copy2(cell_path, anchor_path)
                            anchor_face = anchor_path
                        anchor_cell = cell_path
                        if log_fn:
                            log_fn(f'Anchor retried ({_b2}, {_delta_txt}) — kept, proceeding')
                    else:
                        if _lum_backup and os.path.isfile(_lum_backup):
                            _sh2.copy2(_lum_backup, cell_path)
                            try:
                                anchor_face = _idqc.extract_anchor_face(cell_path, anchor_path, log_fn=None)
                            except Exception:
                                anchor_face = anchor_path
                        if log_fn:
                            log_fn(f'Anchor retry did not improve ({_delta_txt}) — reverted to original')
                if _lum_backup:
                    try:
                        os.remove(_lum_backup)
                    except OSError as _exc:
                        _zyg_log.debug('anchor luminance backup not removed: %s', _exc)
                else:
                    if log_fn:
                        log_fn('Anchor retry failed — continuing with original')
        except Exception as _lum_exc:
            if log_fn:
                log_fn(f'Anchor luminance check skipped ({_lum_exc})')
    ctx.anchor_cell = anchor_cell
    ctx.anchor_face = anchor_face
