# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Structure compliance, the side-profile and full-body anchors, and the gate runner.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 1175-1619).
"""

from __future__ import annotations

import os
import uuid
from zyg_workflows import contact_sheet_pipeline as _csp
from .anchor_ctx import AnchorCtx, _reinstall_anchor
from .anchor_identity_gates import step_anchor_face, step_style_gate, step_skin_luminance_gate
from .anchor_dedup_gate import step_dedup_gate
from .anchor_attribute_gate import step_attribute_gate, step_dedup_recheck

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_structure_gate(ctx: AnchorCtx) -> None:
    """Face/eye shape + age band compliance (log-only) and the de-freckle fix."""
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import identity_qc_service as _idqc

    params = ctx.params
    cell_path = ctx.cell_path
    anchor_path = ctx.anchor_path
    log_fn = ctx.log_fn
    gen_kwargs = ctx.gen_kwargs
    _cell0_reused = ctx.cell0_reused
    anchor_face = ctx.anchor_face

    def _attr_reinstall_anchor() -> None:
        _reinstall_anchor(ctx)

    # Structure compliance (2026-07-18, log-only for shape/age): colours
    # are VLM-verified above, but face structure never was — FLUX
    # silently ignored 'monolid' and 'long face' on run 59f1f012 and
    # nothing recorded it. No retries for shape/age (weak FLUX levers).
    # EXCEPTION (2026-07-20): freckle_density acts — an unrequested
    # dense freckle field gets a one-shot targeted de-freckle edit
    # before 47 qwen tiles smear it into scar-like mottling.
    if ctx.photoreal:
        try:
            from zyg_workflows import cell_vlm_judge as _svj

            if _svj.enabled():
                _spec_struct = {
                    'face_shape': (params.get('face_shape') or '').strip().lower(),
                    'eye_shape': (params.get('eye_shape') or '').strip().lower(),
                    'age': params.get('age'),
                    'distinctive_marks': params.get('distinctive_marks'),
                }
                _struct = _svj.judge_structure(
                    anchor_face if (anchor_face and os.path.isfile(anchor_face)) else cell_path,
                    _spec_struct,
                    log_fn=log_fn,
                )
                params['_anchor_structure'] = _struct
                _sm = _struct.get('mismatches') or {}
                if _sm and log_fn:
                    log_fn(
                        'Structure check: anchor deviates from spec — '
                        + ', '.join(f"{k}: spec '{_spec_struct.get(k)}' got '{v}'" for k, v in _sm.items())
                        + ' (log-only)',
                    )
                # Record structure deltas (except freckle_density, which
                # is acted on below) for the review-card disclosure — the
                # operator sees "face: oval (you selected square)" before
                # committing 4h of tiles, since FLUX cannot reliably hit
                # face/eye shape and we ship the closest anchor.
                if _sm:
                    _sdeltas = params.setdefault('_attr_deltas', {})
                    for _sk, _sv in _sm.items():
                        if _sk == 'freckle_density':
                            continue
                        # age_band mismatch reports against a band label;
                        # the spec value is the numeric age the operator set.
                        _sel = params.get('age') if _sk == 'age_band' else _spec_struct.get(_sk)
                        _sdeltas.setdefault(
                            _sk,
                            {
                                'selected': _sel,
                                'delivered': _sv,
                                'advisory': True,
                            },
                        )
                elif _struct.get('checked') and log_fn:
                    log_fn('Structure check OK — anchor matches spec (face/eye shape, age band)')

                # De-freckle fix: unrequested dense freckle field on the
                # anchor (Iris Weber 0cc9541b) — every qwen angle edit
                # smears it into scar-like mottling on derived tiles.
                # A targeted edit preserves the identity/dedup/attribute
                # verdicts the anchor already earned, unlike a reroll.
                if not _cell0_reused and _sm.get('freckle_density') == 'heavy':
                    try:
                        _dfx_qwen = bool(_cgs.has_qwen_edit_angles())
                    except Exception:
                        _dfx_qwen = False
                    if _dfx_qwen:
                        if log_fn:
                            log_fn(
                                'Structure check: unrequested dense freckle field '
                                '(marks say none) — removing via targeted qwen edit',
                            )
                        import shutil as _sh_dfx

                        _dfx_path = cell_path + '.defreckle.png'
                        _dfx_kw = dict(gen_kwargs)
                        _dfx_kw['seed'] = int(uuid.uuid4().int % (2**31))
                        _dfx_kw['reference_image'] = cell_path
                        _dfx_kw['force_workflow'] = 'qwen_edit_angle'
                        _dfx_kw.pop('flux_guidance', None)
                        _dfx_kw['extra_negative'] = ', '.join(
                            x
                            for x in (
                                (_dfx_kw.get('extra_negative') or '').strip(', '),
                                'freckles, dense freckle field, mottled skin, dark spots, '
                                'airbrushed skin, smooth plastic skin, waxy skin, poreless skin',
                            )
                            if x
                        )
                        _dfx_prompt = (
                            "Remove the dense freckles and dark spots from the person's "
                            'face so the skin is evenly toned and clear, while KEEPING '
                            'real natural skin texture with visible pores and fine '
                            'detail — not airbrushed, not smoothed, not retouched. '
                            'Keep everything else exactly identical: the same face, the '
                            'same skin tone and complexion (do not lighten or change the '
                            'skin colour), the same hairstyle, clothing, pose, lighting '
                            'and plain studio background, and the exact same framing and '
                            'camera distance — do not zoom in or out'
                        )
                        _dfx_ok, _dfx_b = _cgs.generate_still(_dfx_path, _dfx_prompt, **_dfx_kw)
                        _dfx_accept = False
                        _dfx_density = None
                        _dfx_tex = None
                        if _dfx_ok and os.path.isfile(_dfx_path):
                            _dfx_re = _svj.judge_structure(_dfx_path, _spec_struct, log_fn=log_fn)
                            _dfx_density = (_dfx_re.get('observed') or {}).get('freckle_density')
                            # Accept only strict improvement: density
                            # dropped, no NEW shape/age mismatch, and
                            # texture above the anti-waxy floor (a
                            # de-freckle that smooths the skin would
                            # trade one defect for another).
                            _dfx_tex_ok = True
                            try:
                                _dfx_emb = _idqc.embed_images([_dfx_path], log_fn=None)
                                _dfx_bbox = (_dfx_emb.get(_dfx_path) or {}).get('bbox')
                                _dfx_tex = _csp._tile_texture_score(_dfx_path, _dfx_bbox)
                                if _dfx_tex is not None:
                                    _dfx_tex_ok = _dfx_tex >= float(
                                        os.environ.get('ZYG_ANCHOR_STYLE_GATE_LAPVAR', '50'),
                                    )
                            except Exception as _exc:
                                _zyg_log.warning(
                                    'de-freckle texture probe failed, accepting on the vlm verdict alone: %s', _exc
                                )
                            if (
                                _dfx_re.get('checked')
                                and _dfx_density in ('none', 'light')
                                and (set(_dfx_re.get('mismatches') or {}) - {'freckle_density'})
                                <= (set(_sm) - {'freckle_density'})
                                and _dfx_tex_ok
                            ):
                                _dfx_accept = True
                                _struct = _dfx_re
                        if _dfx_accept:
                            _sh_dfx.copy2(_dfx_path, cell_path)
                            if ctx.attr_reinstall_bound:
                                _attr_reinstall_anchor()
                                anchor_face = ctx.anchor_face
                                ctx.anchor_replaced = True
                            else:
                                # Attribute gate disabled — re-extract inline.
                                try:
                                    anchor_face = _idqc.extract_anchor_face(
                                        cell_path,
                                        anchor_path,
                                        log_fn=log_fn,
                                    )
                                except Exception:
                                    anchor_face = None
                            params['_anchor_structure'] = _struct
                            _sm = _struct.get('mismatches') or {}
                            if log_fn:
                                log_fn(
                                    f'Structure check: de-freckle edit accepted '
                                    f'(density now {_dfx_density}, texture '
                                    f'{"n/a" if _dfx_tex is None else round(_dfx_tex)}, {_dfx_b})',
                                )
                        elif log_fn:
                            log_fn(
                                'Structure check: de-freckle edit did not verify '
                                f'(density {_dfx_density}, texture '
                                f'{"n/a" if _dfx_tex is None else round(_dfx_tex)}) '
                                '— keeping original anchor (log-only)',
                            )
                        try:
                            os.remove(_dfx_path)
                        except OSError as _exc:
                            _zyg_log.debug('de-freckle scratch image not removed: %s', _exc)
        except Exception as _st_exc:
            if log_fn:
                log_fn(f'Structure check skipped ({str(_st_exc)[:100]})')
    ctx.anchor_face = anchor_face


def step_profile_anchor(ctx: AnchorCtx) -> None:
    """Second anchor: an exact side profile, so profile tiles score honestly."""
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import identity_qc_service as _idqc

    char_id = ctx.char_id
    cell_path = ctx.cell_path
    log_fn = ctx.log_fn
    gen_kwargs = ctx.gen_kwargs
    _cell0_reused = ctx.cell0_reused
    anchor_face = ctx.anchor_face

    # ── SECOND ANCHOR: side profile (2026-07-18) ────────────────────
    # ArcFace scores true profiles ~0.25 against a frontal crop, which
    # forced lenient profile floors — the sloppiest third of the sheet.
    # Rotate the approved frontal cell into an exact side profile once,
    # verify it is the same person, and every profile/oblique/back tile
    # then scores against the better of the two anchors.
    _pa_on = os.environ.get(
        'ZYG_PROFILE_ANCHOR',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    if _pa_on and ctx.photoreal:
        try:
            _pa_path = _csp.identity_profile_anchor_face_path(char_id)
            _pa_cell = os.path.join(_csp.contact_sheet_dir(char_id), 'profile_anchor_cell.png')
            if _cell0_reused and os.path.isfile(_pa_path):
                raise StopIteration('profile anchor reused (resume)')
            _pa_prompt = (
                'Turn the person a full 90 degrees to the left into an exact '
                'side profile view, only one side of the face visible, while '
                'keeping the exact same person with identical facial features, '
                'same hairstyle, same clothing, same lighting and the same '
                'plain studio background'
            )
            _pa_kw = dict(gen_kwargs)
            _pa_kw['seed'] = int(uuid.uuid4().int % (2**31))
            _pa_kw['reference_image'] = cell_path
            _pa_kw['force_workflow'] = 'qwen_edit_angle'
            _pa_kw.pop('flux_guidance', None)
            _pa_ok, _pa_b = _cgs.generate_still(_pa_cell, _pa_prompt, **_pa_kw)
            if _pa_ok and os.path.isfile(_pa_cell):
                _pa_face = _idqc.extract_anchor_face(_pa_cell, _pa_path, log_fn=log_fn)
                if _pa_face:
                    _pa_emb = _idqc.embed_images([_pa_face, anchor_face], log_fn=None)
                    _pa_me = (_pa_emb.get(_pa_face) or {}).get('embedding')
                    _pa_an = (_pa_emb.get(anchor_face) or {}).get('embedding')
                    _pa_sim = _idqc.cosine(_pa_me, _pa_an) if (_pa_me and _pa_an) else -1.0
                    _pa_floor = float(os.environ.get('ZYG_PROFILE_ANCHOR_MIN_SIM', '0.20'))
                    if _pa_sim >= _pa_floor:
                        if log_fn:
                            log_fn(
                                f'Profile anchor ready (sim {_pa_sim:.3f} vs frontal) → {os.path.basename(_pa_path)}',
                            )
                    else:
                        try:
                            os.remove(_pa_path)
                        except OSError as _exc:
                            _zyg_log.warning('rejected profile anchor not removed, a later run may adopt it: %s', _exc)
                        if log_fn:
                            log_fn(
                                f'Profile anchor rejected (sim {_pa_sim:.3f} < {_pa_floor:g}) — frontal-only scoring',
                            )
                elif log_fn:
                    log_fn('Profile anchor: no face detected in rotated view — skipped')
            elif log_fn:
                log_fn(f'Profile anchor generation failed ({_pa_b}) — skipped')
        except Exception as _pa_exc:
            if log_fn:
                log_fn(f'Profile anchor skipped ({str(_pa_exc)[:100]})')


def step_body_anchor(ctx: AnchorCtx) -> None:
    """Full-body outfit anchor — only full-body cells reference it."""
    from zyg_workflows import comfy_generation_service as _cgs

    log_fn = ctx.log_fn
    gen_kwargs = ctx.gen_kwargs
    pkg = ctx.pkg
    _cell0_reused = ctx.cell0_reused
    _anchor_family = ctx.anchor_family
    _anchor_cfg = ctx.anchor_cfg
    _skin_clause = ctx.skin_clause
    style_extra = ctx.style_extra
    trigger = ctx.trigger
    unet = ctx.unet
    base_seed = ctx.base_seed
    qwen_ok = ctx.qwen_ok
    anchor_cell = ctx.anchor_cell
    anchor_face = ctx.anchor_face
    _body_anchor_path = ctx.body_anchor_path
    anchor_cell_body = ctx.anchor_cell_body

    # Full-body outfit anchor — the portrait anchor (cell_00) is a
    # head-and-shoulders close-up and contains no shoes or lower body.
    # When Qwen edits generate full-body rotations from a headshot it
    # has to invent the lower half each time, which causes random shoes
    # and pants-colour drift across cells.  Generate a separate standing
    # full-body FLUX txt2img here (not part of the angle list); ONLY
    # full-body cells reference it (head cells keep the head anchor).
    # anchor_face (the face crop) still comes from cell_00 for QC.
    _body_scene = (
        f'{_skin_clause}standing full body A-pose, front view, '
        f'whole figure from head to feet inside frame, neutral '
        f'expression, single person, neutral '
        f'studio background, {style_extra}, {trigger}'
    )
    try:
        # Disk presence of cell_00_body.png must mean "generated this
        # run and passed identity QC" — resume/regen/expansion adopt it
        # by bare isfile, so clear any stale copy from a prior run of
        # this char_id before generating. EXCEPT on resume (2026-07-19):
        # the existing body anchor already seeded the generated
        # full-body cells — regenerating it now would drift their
        # outfit/shoes relative to the remaining cells.
        if os.path.isfile(_body_anchor_path):
            if _cell0_reused:
                anchor_cell_body = _body_anchor_path
                if log_fn:
                    log_fn('Body anchor reused (resume) — keeping existing cell_00_body.png')
                raise StopIteration('body anchor reused')
            try:
                os.remove(_body_anchor_path)
            except OSError as _exc:
                _zyg_log.warning('stale body anchor not removed, a prior-run copy may be adopted: %s', _exc)
        _body_kw = dict(gen_kwargs)
        _body_kw['width'] = 832
        _body_kw['height'] = 1216
        _body_kw['seed'] = base_seed + 1
        # Body anchor via QWEN EDIT of the portrait anchor (zoom out to
        # full body) instead of an independent txt2img. txt2img produced
        # a DIFFERENT person ~most of the time (2026-07-12: identity 0.161
        # → rejected → full-body cells fell back to the headshot and
        # invented legs/shoes). Editing the anchor preserves identity by
        # construction, the way the full-body rotation cells already do.
        if qwen_ok and anchor_cell and os.path.isfile(anchor_cell):
            _body_prompt = (
                'Zoom the camera out to a full-body standing A-pose showing the '
                'entire figure from head to feet inside the frame with margin on '
                'all sides, front view, arms relaxed at the sides, while keeping the '
                'exact same person with an identical face, identical skin tone and '
                'complexion (do not lighten or change the skin colour), identical '
                'hairstyle and identical clothing, against the same plain studio '
                'background. RAW candid photograph, natural uneven skin with visible '
                'pores and fine texture, unretouched — not airbrushed, not a 3D '
                'render, not an illustration'
            )
            _body_kw['reference_image'] = anchor_cell
            _body_kw['force_workflow'] = 'qwen_edit_angle'
            _body_kw.pop('force_unet', None)
        elif _anchor_family in ('qwen', 'klein'):
            # No qwen-edit available and FLUX txt2img is licence-paused
            # — full-body cells fall back to the head anchor rather
            # than silently submitting a paused FLUX graph.
            if log_fn:
                log_fn(
                    'Body anchor skipped — anchor_family=qwen and no '
                    'qwen edit path; full-body cells use the head anchor',
                )
            raise StopIteration('body anchor skipped (qwen, no edit path)')
        else:
            _body_prompt = _cgs.build_locked_prompt(_body_scene, pkg, studio_preview=True)
            _body_kw['cfg'] = _anchor_cfg
            _body_kw['flux_guidance'] = _anchor_cfg
            _body_kw['force_workflow'] = 'flux_txt2img'
            _body_kw['force_unet'] = unet
        _ok_body, _b_body = _cgs.generate_still(
            _body_anchor_path,
            _body_prompt,
            **_body_kw,
        )
        if _ok_body and os.path.isfile(_body_anchor_path):
            # Validate body anchor identity against portrait anchor face.
            # A-pose shots have a small face so ArcFace may not detect it;
            # no-detection is not a failure — use for outfit reference anyway.
            _body_valid = True
            try:
                from zyg_workflows import identity_qc_service as _idqc_ba_svc

                _idqc_ba_avail, _ = _idqc_ba_svc.available()
            except Exception:
                _idqc_ba_avail = False
            if _idqc_ba_avail and anchor_face and os.path.isfile(anchor_face):
                try:
                    from zyg_workflows import identity_qc_service as _idqc_ba

                    _ba_embeds = _idqc_ba.embed_images(
                        [_body_anchor_path, anchor_face],
                        log_fn=None,
                    )
                    _ba_entry = _ba_embeds.get(_body_anchor_path, {})
                    _af_entry = _ba_embeds.get(anchor_face, {})
                    _ba_emb = _ba_entry.get('embedding')
                    _af_emb = _af_entry.get('embedding')
                    if _ba_emb and _af_emb:
                        _ba_score = _idqc_ba.cosine(_ba_emb, _af_emb)
                        if _ba_score < 0.28:
                            _body_valid = False
                            if log_fn:
                                log_fn(
                                    f'Body anchor identity mismatch '
                                    f'(score {_ba_score:.3f}) — '
                                    f'falling back to portrait anchor',
                                )
                        elif log_fn:
                            log_fn(
                                f'Body anchor identity OK (score {_ba_score:.3f})',
                            )
                except Exception as _bv_exc:
                    if log_fn:
                        log_fn(f'Body anchor QC skipped ({_bv_exc})')
            if _body_valid:
                anchor_cell_body = _body_anchor_path
                if log_fn:
                    log_fn(
                        f'Body anchor ready ({_b_body}) — full-body '
                        f'Qwen edits use it; head cells keep the '
                        f'head-and-shoulders anchor',
                    )
            else:
                # Identity-rejected: remove it so resume/regen/expansion
                # (which check only isfile) can never adopt it.
                try:
                    os.remove(_body_anchor_path)
                except OSError as _exc:
                    _zyg_log.warning('identity-rejected body anchor not removed, resume may adopt it: %s', _exc)
        else:
            if log_fn:
                log_fn('Body anchor generation failed — falling back to portrait anchor')
    except Exception as _ba_exc:
        if log_fn:
            log_fn(f'Body anchor skipped ({_ba_exc}) — using portrait anchor')
    ctx.anchor_cell_body = anchor_cell_body


def run_anchor_gates(ctx: AnchorCtx) -> None:
    """Every cell-00 gate, in the order they ran inline."""
    step_anchor_face(ctx)
    ctx.photoreal = ctx.render_style in ('photorealistic', 'photoreal', 'photo')
    ctx.style_gate_on = os.environ.get('ZYG_ANCHOR_STYLE_GATE', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )
    step_style_gate(ctx)
    step_skin_luminance_gate(ctx)
    step_dedup_gate(ctx)
    step_attribute_gate(ctx)
    step_dedup_recheck(ctx)
    step_structure_gate(ctx)
    step_profile_anchor(ctx)
    step_body_anchor(ctx)
