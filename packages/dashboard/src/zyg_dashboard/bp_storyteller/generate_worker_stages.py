# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage helpers of the character-generate background worker.

2026-10-09 function split: `generate_worker._bg_generate` was a single 521-line
closure (over the 300-line function cap). Its stages live here as module-level
functions that take one `CharGenContext` — the dataclass holding exactly the
closure's free variables — so each stage can be exercised on its own. The
orchestrator in generate_worker.py calls them in the original order; every log
line, side effect and ordering is preserved.
"""

import importlib.util as _ilu
import logging as _zyg_logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from zyg_dashboard.bp_storyteller import (
    _apply_gpu_power_limit,
    _char_gen_jobs,
    _char_lora_train_families,
    _char_mark_done,
    _char_mark_error,
    _char_render_style,
    _char_stage_end,
    _char_stage_start,
    _char_train_lora_for_family,
    _dsl,
    _have_usable_char_preview,
    _normalize_char_model_family,
    _render_char_preview_images,
    _resolve_char_model_family,
    gui_state,
)
from zyg_dashboard.bp_storyteller.guards import _CHARS_DATASET_ROOT

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_storyteller')

_BIBLE_STAGE = 'Stage 1 — Character Bible'
_CAPTION_STAGE = 'Stage 1b — Caption Generation'
_PHOTO_STAGE = 'Stage 1a — Photo Import'
_RENDER_STAGE = 'Stage 1a — Character Render'
_PREVIEW_STAGE = 'Stage 1d — Preview Render'

#: Per-image caption tails used by the template fallback, cycled by index.
CAPTION_SUFFIXES = (
    'full body, front view',
    'portrait, facing camera',
    'three-quarter angle, natural light',
    'profile view, side angle',
    'upper body, candid',
    'close-up face',
    'full body, dynamic pose',
)

#: Preview stems the dedup/texture gate accepts as "the character's face", in order.
GATE_FACE_CANDIDATES = (
    'preview_flux_face.png',
    'preview_flux_front.png',
    'preview_sdxl_front.png',
)


@dataclass
class CharGenContext:
    """Mutable state the character-generate stages hand to one another.

    Holds exactly the free variables of the old `_bg_generate` closure: the job
    record, the request parameters, the uploaded photos and the emit/stop
    callbacks, plus `model_family` and `render_style` (resolved by the first
    stage) and `info`, which the dataset stages REBIND to a fresh dict.
    """

    info: dict
    char_id: str
    params: dict
    kick_lora: bool
    uploaded_image_paths: list
    photo_analysis: Any
    emit: Callable[..., Any]
    check_stop: Callable[[], Any]
    job: dict
    model_family: str = ''
    render_style: str = ''


def resolve_job_model_family(ctx, requested):
    """Resolve the job's model family, announce the routing and return it.

    `requested` is the family the route picked; the job record may override it.
    Writes the resolved family back into `ctx.info`, `ctx.job`, `ctx.params` and
    `ctx.model_family`, and records the render style on `ctx.render_style`.
    """
    mf_job = ctx.job.get('model_family') or requested
    ctx.info['model_family'] = mf_job
    ctx.info['render_mode'] = ctx.job.get('render_mode')
    ctx.render_style = _char_render_style(ctx.params, ctx.info)
    mf_job = _resolve_char_model_family(mf_job, ctx.params, ctx.info)
    ctx.job['model_family'] = mf_job
    ctx.info['model_family'] = mf_job
    ctx.params['model_family'] = mf_job
    ctx.model_family = mf_job
    if ctx.render_style == 'animated' and mf_job == 'flux':
        ctx.emit(
            'Animated style routed to FLUX (Eva-style photoreal stack)',
            level='INFO',
            stage='init',
        )
    elif ctx.render_style == 'photorealistic' and mf_job == 'flux':
        ctx.emit(
            'Photorealistic style routed to FLUX LoRA + locked preview (Eva pipeline)',
            level='INFO',
            stage='init',
        )
    ctx.emit(f'Character pipeline model_family={mf_job}', stage='init')
    if ctx.params.get('_hair_age_note'):
        ctx.emit(ctx.params['_hair_age_note'], level='WARN', stage='init')
    if ctx.params.get('character_brief_prose'):
        ctx.emit(
            f'Character brief (Sonnet): {ctx.params["character_brief_prose"][:220]}…'
            if len(ctx.params['character_brief_prose']) > 220
            else f'Character brief (Sonnet): {ctx.params["character_brief_prose"]}',
            stage='init',
        )
    return mf_job


def apply_power_limit(ctx):
    """Apply the same GPU power limit as all other pipelines and emit the outcome."""
    _pw_err = _apply_gpu_power_limit(gui_state._CALIBRATION.get('max_gpu_watts', 400.0))
    if _pw_err:
        ctx.emit(f'GPU power-limit note: {_pw_err}', level='WARN')
    else:
        ctx.emit(
            f'GPU power limit set to {int(gui_state._CALIBRATION.get("max_gpu_watts", 400))}W',
            level='INFO',
            stage='init',
        )


def write_template_captions(image_paths, params, trigger_token):
    """Write one sibling `.txt` caption per image from the parameter template.

    The fallback used when the vision captioner fails: cycles CAPTION_SUFFIXES
    for view variety and returns the number of captions written.
    """
    _gender_bg = params.get('gender', 'female')
    _style_bg = params.get('style', 'photorealistic')
    _hair_bg = params.get('hair_color', 'brown')
    try:
        from zyg_workflows import blender_character_service as _bcs_cap

        _style_cap = _bcs_cap.caption_style_description(_style_bg)
    except Exception:
        _style_cap = 'stylized realistic 3D render'
    for _ci, _img_path_bg in enumerate(image_paths):
        _suffix = CAPTION_SUFFIXES[_ci % len(CAPTION_SUFFIXES)]
        _cap_text = f'{trigger_token} {_gender_bg}, {_hair_bg} hair, {_style_cap}, {_suffix}'
        _cap_path = os.path.splitext(_img_path_bg)[0] + '.txt'
        with open(_cap_path, 'w', encoding='utf-8') as _cf:
            _cf.write(_cap_text)
    return len(image_paths)


def generate_photo_captions(ctx, trigger_token):
    """Caption the uploaded photos with vision, falling back to the template.

    Reuses an existing photo analysis when one is already known, otherwise runs
    the per-photo vision pass and stores a successful result back into
    `ctx.params['_photo_analysis']`. Returns the caption count.
    """
    _photo_an = ctx.params.get('_photo_analysis') or ctx.photo_analysis or ctx.info.get('photo_analysis') or {}
    try:
        from zyg_workflows import character_photo_analysis_service as _cpas_cap

        if not (_photo_an.get('ok') and _photo_an.get('image_captions')):
            ctx.emit('Stage 1b — running per-photo vision captions…', stage=_CAPTION_STAGE)
            _photo_an = _cpas_cap.analyze_photo_paths(
                ctx.uploaded_image_paths,
                log_fn=lambda m: ctx.emit(m, stage=_CAPTION_STAGE),
            )
            if _photo_an.get('ok'):
                ctx.params['_photo_analysis'] = _photo_an
        return _cpas_cap.write_training_captions(
            ctx.uploaded_image_paths,
            ctx.params,
            trigger_token,
            analysis=_photo_an if _photo_an.get('ok') else None,
            log_fn=lambda m: ctx.emit(m, stage=_CAPTION_STAGE),
        )
    except Exception as _cap_e:
        ctx.emit(
            f'Stage 1b — vision captions failed ({_cap_e}); using template fallback',
            level='WARN',
            stage=_CAPTION_STAGE,
        )
        return write_template_captions(ctx.uploaded_image_paths, ctx.params, trigger_token)


def run_photo_import_stage(ctx):
    """Import the operator's photos as the dataset and caption them (stages 1a/1b).

    Replaces the Blender render when photos were uploaded; returns the new `info`
    dict describing the dataset (the old closure rebound `info` here).
    """
    _char_stage_start(ctx.char_id, _PHOTO_STAGE)
    _dataset_dir_bg = os.path.dirname(ctx.uploaded_image_paths[0])
    _trigger_token_bg = f'zygchar{ctx.char_id[:8]}'
    ctx.emit(
        f'Stage 1a — {len(ctx.uploaded_image_paths)} uploaded photos found; skipping Blender 3D render',
        stage=_PHOTO_STAGE,
    )
    _char_stage_end(
        ctx.char_id,
        _PHOTO_STAGE,
        extra={
            'image_count': len(ctx.uploaded_image_paths),
            'source': 'uploaded_photos',
        },
    )
    ctx.job['stage'] = 'captions'
    _char_stage_start(ctx.char_id, _CAPTION_STAGE)
    _cap_n = generate_photo_captions(ctx, _trigger_token_bg)
    ctx.emit(
        f'Stage 1b — {_cap_n} captions written (trigger: {_trigger_token_bg})',
        stage=_CAPTION_STAGE,
    )
    _char_stage_end(
        ctx.char_id,
        _CAPTION_STAGE,
        extra={
            'caption_count': len(ctx.uploaded_image_paths),
        },
    )
    return {
        'dataset_dir': _dataset_dir_bg,
        'images': ctx.uploaded_image_paths,
        'trigger_token': _trigger_token_bg,
        'source': 'uploaded_photos',
        'model_family': ctx.model_family,
        'char_id': ctx.char_id,
        'photo_analysis': ctx.params.get('_photo_analysis') or ctx.photo_analysis,
    }


def run_blender_render_stage(ctx):
    """Render the reference dataset headlessly in Blender (stages 1a/1b).

    Returns the service's `info` dict. Raises RuntimeError when the service is
    not importable, and re-raises a render failure after closing stage 1a failed.
    """
    _spec = _ilu.find_spec('blender_character_service')
    if not _spec:
        raise RuntimeError('blender_character_service not found and no uploaded photos provided')
    from zyg_workflows import blender_character_service as _bcs

    svc = _bcs.get_service()
    ctx.job['stage'] = 'blender_render'
    _char_stage_start(ctx.char_id, _RENDER_STAGE)
    ctx.emit(
        f'Stage 1a — Blender headless render starting for char {ctx.char_id}',
        stage=_RENDER_STAGE,
    )
    try:
        info = svc.generate(ctx.char_id, ctx.params)
        n_imgs = len(info.get('images', []))
        ctx.emit(
            f'Stage 1a — Blender render complete: {n_imgs} images written to {info.get("dataset_dir", "")}',
            stage=_RENDER_STAGE,
        )
        _char_stage_end(
            ctx.char_id,
            _RENDER_STAGE,
            extra={
                'image_count': n_imgs,
                'source': 'blender',
            },
        )
    except Exception as _blender_e:
        _char_stage_end(
            ctx.char_id,
            _RENDER_STAGE,
            status='failed',
            extra={'error': str(_blender_e)[:200]},
        )
        raise

    ctx.job['stage'] = 'captions'
    _char_stage_start(ctx.char_id, _CAPTION_STAGE)
    ctx.emit(
        f'Stage 1b — Dataset captions written (trigger: {info.get("trigger_token", "")})',
        stage=_CAPTION_STAGE,
    )
    _char_stage_end(
        ctx.char_id,
        _CAPTION_STAGE,
        extra={
            'caption_count': len(info.get('images', [])),
        },
    )
    return info


def find_gate_face_image(dataset_dir):
    """Return the first existing GATE_FACE_CANDIDATES file in `dataset_dir`, else ''."""
    for _cand_gate in GATE_FACE_CANDIDATES:
        _p_gate = os.path.join(dataset_dir, _cand_gate)
        if os.path.isfile(_p_gate):
            return _p_gate
    return ''


def dedup_similarity_ceiling():
    """Return the anchor similarity above which the dedup gate warns.

    0.45 is glintr100-scale; 0.489 is the quantile-matched AuraFace equivalent
    (2026-08-09 calibration). ZYG_ANCHOR_DEDUP_MAX_SIM overrides both.
    """
    _dd_default = '0.489' if os.environ.get('ZYG_IDQC_PACK', '').strip() == 'auraface' else '0.45'
    return float(os.environ.get('ZYG_ANCHOR_DEDUP_MAX_SIM', _dd_default))


def warn_on_waxy_texture(ctx, face_path, probe):
    """Warn when a photoreal face falls below the waxy texture band.

    Texture warn (2026-07-18): photoreal renders below the waxy band get flagged
    here too — this flow has no contact-sheet texture gate. Probe failures are
    debug-logged and never raise.
    """
    try:
        if ctx.render_style == 'photorealistic' and probe.get('face_detected'):
            from zyg_workflows.contact_sheet_pipeline import _tile_texture_score as _tts_bl

            _tex_bl = _tts_bl(face_path, probe.get('bbox'))
            if _tex_bl is not None and _tex_bl < 45:
                ctx.emit(
                    f'Texture warn: face Laplacian variance '
                    f'{_tex_bl:.0f} < 45 (waxy/semi-render band) — '
                    'review the previews',
                    level='WARN',
                    stage=_BIBLE_STAGE,
                )
    except Exception as _exc:
        _zyg_log.debug('face texture probe skipped: %s', _exc)


def run_dedup_gate(ctx):
    """Compare the rendered face against the library anchors (warn-only).

    Blender/photo-flow dedup check (2026-07-18): this path has none of the
    contact-sheet gates, so a duplicate look shipped silently. Records the report
    on the job record and emits a warning above the calibrated ceiling.
    """
    try:
        from zyg_workflows import identity_qc_service as _idqc_bl

        _ds_gate = ctx.info.get('dataset_dir') or os.path.join(_CHARS_DATASET_ROOT, ctx.char_id)
        _face_gate = find_gate_face_image(_ds_gate)
        if _face_gate:
            _dd_bl = _idqc_bl.dedup_report(_face_gate, ctx.char_id)
            _j_dd = _char_gen_jobs.get(ctx.char_id)
            if _j_dd is not None and _dd_bl.get('max_sim') is not None:
                _j_dd['anchor_dedup'] = _dd_bl
            _dd_ceil_bl = dedup_similarity_ceiling()
            if _dd_bl.get('max_sim') is not None and _dd_bl['max_sim'] > _dd_ceil_bl:
                ctx.emit(
                    f'Dedup check: face is very similar to existing '
                    f'character {_dd_bl["vs"]} (ArcFace sim '
                    f'{_dd_bl["max_sim"]:.3f} > {_dd_ceil_bl:g}) — '
                    'review recommended',
                    level='WARN',
                    stage=_BIBLE_STAGE,
                )
            elif _dd_bl.get('max_sim') is not None:
                ctx.emit(
                    f'Dedup check OK (max sim {_dd_bl["max_sim"]:.3f} vs {_dd_bl["compared"]} existing characters)',
                    stage=_BIBLE_STAGE,
                )
            warn_on_waxy_texture(ctx, _face_gate, _dd_bl.get('probe') or {})
    except Exception as _dd_bl_e:
        ctx.emit(
            f'Dedup check skipped: {_dd_bl_e}',
            level='WARN',
            stage=_BIBLE_STAGE,
        )


def build_dsl_scene_metadata(params):
    """Build the DSL scene metadata dict from the character parameters."""
    return {
        'subject': (f'{params.get("gender", "person")} character {params.get("name", "")}'),
        'setting': (
            params.get('character_brief_prose', '')[:200] or f'reference dataset for {params.get("style", "")} style'
        ),
        'lighting_style': params.get('lighting_profile', 'soft_studio'),
        'color_palette': params.get('color_palette', ''),
        'aspect_ratio': '2:3',
        'composition': 'character reference, multi-angle',
        'tags': [
            'character',
            params.get('style', ''),
            params.get('gender', ''),
            params.get('genre', ''),
        ],
    }


def persist_dsl_scene(ctx):
    """Persist the character scene YAML beside the dataset when the DSL is on."""
    if _dsl is None or not _dsl.is_enabled('character'):
        return
    try:
        _ds_dir = ctx.info.get('dataset_dir') or os.path.join(_CHARS_DATASET_ROOT, ctx.char_id)
        _char_scene = _dsl.build_scene_from_metadata(
            build_dsl_scene_metadata(ctx.params),
            pipeline='character',
            scene_id=f'char_{ctx.char_id[:8]}',
        )
        _dsl_path = _dsl.persist_scene(
            _char_scene,
            _ds_dir,
            filename=f'character_{ctx.char_id[:8]}.scene.yaml',
        )
        if _dsl_path:
            ctx.emit(f'DSL scene saved → {_dsl_path}', stage=_BIBLE_STAGE)
    except Exception as _dsl_char_e:
        ctx.emit(f'DSL persist warning: {_dsl_char_e}', level='WARN', stage=_BIBLE_STAGE)


def run_character_bible_stage(ctx):
    """Build the character bible, run the dedup gate and persist the DSL scene.

    Stage 1 is warn-only: a failure is emitted and the stage closed as failed,
    but the pipeline carries on to LoRA training.
    """
    _char_stage_start(ctx.char_id, _BIBLE_STAGE)
    try:
        from zyg_workflows import character_bible_service as _cbs_cgen
        from zyg_workflows import consistency_qa_service as _cqa_cgen

        _cbs_cgen.build_from_character_generate(
            ctx.char_id,
            ctx.params,
            ctx.info,
            log_fn=lambda m: ctx.emit(m, stage=_BIBLE_STAGE),
        )
        _cqa_cgen.ensure_reference_from_bible(
            ctx.char_id,
            log_fn=lambda m: ctx.emit(m, stage=_BIBLE_STAGE),
        )
        run_dedup_gate(ctx)
        _char_stage_end(ctx.char_id, _BIBLE_STAGE)
        persist_dsl_scene(ctx)
    except Exception as _bible_cgen_e:
        ctx.emit(f'Character bible setup warning: {_bible_cgen_e}', level='WARN', stage=_BIBLE_STAGE)
        _char_stage_end(ctx.char_id, _BIBLE_STAGE, status='failed', extra={'error': str(_bible_cgen_e)[:200]})


def refresh_bible_after_training(ctx, train_mf, lora_fin):
    """Rebuild the character bible and record the LoRA a family just trained."""
    _stage_lora = 'Stage 1c — SDXL LoRA Training' if train_mf == 'sdxl' else 'Stage 1c — FLUX LoRA Training'
    try:
        from zyg_workflows import character_bible_service as _cbs_post_lora

        _cbs_post_lora.build_from_character_generate(
            ctx.char_id,
            ctx.params,
            ctx.info,
            log_fn=lambda m: ctx.emit(m, stage=_stage_lora),
        )
        if lora_fin.get('lora_path'):
            _cbs_post_lora.update_lora(
                ctx.char_id,
                lora_fin.get('lora_path'),
                model_family=train_mf,
                sdxl_checkpoint=lora_fin.get('sdxl_comfy_checkpoint'),
            )
            try:
                _pkg_refresh = _cbs_post_lora.load(ctx.char_id)
                if _pkg_refresh:
                    ctx.info['package'] = _pkg_refresh
            except Exception as _exc:
                _zyg_log.warning(
                    'character bible reload after training failed, the package stays stale: %s',
                    _exc,
                )
    except Exception as _bpl_e:
        ctx.emit(
            f'Character bible refresh warning: {_bpl_e}',
            level='WARN',
            stage='Stage 1c — LoRA Training',
        )


def run_lora_training_stage(ctx):
    """Train one LoRA per planned family, refreshing the bible after each.

    A no-op when the trainer service is not importable; stops after the first
    family that reports a failure.
    """
    _spec2 = _ilu.find_spec('lora_trainer_service')
    if not _spec2:
        return
    from zyg_workflows import lora_trainer_service as _lts

    trainer = _lts.get_trainer()
    ctx.job['stage'] = 'lora_training'
    _train_plan = _char_lora_train_families(ctx.model_family, ctx.params, ctx.info)
    if len(_train_plan) > 1:
        ctx.emit(
            'Photorealistic dual LoRA training: ' + ' → '.join(m.upper() for m in _train_plan),
            stage='Stage 1c — LoRA Training',
        )
    for _train_i, _train_mf in enumerate(_train_plan):
        _st_lora_fin = _char_train_lora_for_family(
            ctx.char_id,
            ctx.info,
            _train_mf,
            trainer,
            ctx.emit,
            ctx.job,
            unload_flux_vram=(_train_i == 0),
        )
        refresh_bible_after_training(ctx, _train_mf, _st_lora_fin)
        if _st_lora_fin.get('failed'):
            break


def resolve_preview_family(ctx):
    """Return the model family the stage 1d preview render must use."""
    return _normalize_char_model_family(
        ctx.job.get('model_family'),
        ctx.params,
        ctx.info,
    )


def run_preview_render_stage(ctx, char_mf):
    """Render the character preview images (stage 1d) and return the result dict.

    When previews were not requested the skipped default is returned; a render
    failure is non-fatal and comes back as the dict's 'error'.
    """
    if not ctx.kick_lora:
        ctx.emit(
            'Stage 1d skipped — kick_lora=false (dataset only, no preview render)',
            stage='preview_render',
        )
        return {
            'rendered': [],
            'error': None,
            'skipped': True,
            'preview_quality_ok': True,
            'preview_warning': '',
            'backends': [],
        }
    ctx.job['stage'] = 'preview_render'
    _char_stage_start(ctx.char_id, _PREVIEW_STAGE)
    _prev_res: dict = {'rendered': [], 'error': None}
    try:
        _prev_label = 'SDXL 1.0 (LoRA locked)' if char_mf == 'sdxl' else 'FLUX'
        ctx.emit(
            f'Stage 1d — Generating {_prev_label} character preview images…',
            stage=_PREVIEW_STAGE,
        )
        _prev_res = _render_char_preview_images(
            ctx.char_id,
            ctx.params,
            ctx.info,
            log_fn=lambda m: ctx.emit(m, stage=_PREVIEW_STAGE),
            force=False,
            model_family=char_mf,
        )
        if _prev_res.get('error') and not _prev_res.get('rendered'):
            ctx.emit(
                f'Stage 1d — preview render failed: {_prev_res["error"]}',
                level='WARN',
                stage=_PREVIEW_STAGE,
            )
            _char_stage_end(
                ctx.char_id,
                _PREVIEW_STAGE,
                status='failed',
                extra={'error': str(_prev_res.get('error'))[:200]},
            )
        else:
            _prev_paths = _prev_res.get('rendered') or _prev_res.get('images') or []
            _char_stage_end(
                ctx.char_id,
                _PREVIEW_STAGE,
                extra={
                    'rendered': bool(_prev_paths),
                    'images': len(_prev_paths),
                    'backend': str(_prev_res.get('backend') or char_mf),
                },
            )
    except Exception as _prev_e:
        ctx.emit(
            f'Stage 1d — preview skipped (non-fatal): {_prev_e}',
            level='WARN',
            stage=_PREVIEW_STAGE,
        )
        _char_stage_end(ctx.char_id, _PREVIEW_STAGE, status='failed', extra={'error': str(_prev_e)[:200]})
        _prev_res = {'rendered': [], 'error': str(_prev_e)[:200]}
    return _prev_res


def preview_quality_ok(prev_res, have_prev, lora_expected):
    """Whether the previews are good enough to call the job done.

    True when the render reported quality OK, when it was skipped but usable
    preview files exist, or when previews exist and no LoRA was expected.
    """
    return bool(
        bool(prev_res.get('preview_quality_ok'))
        or (prev_res.get('skipped') and have_prev)
        or (have_prev and not lora_expected)
    )


def final_error_message(job, prev_res):
    """Join the LoRA and preview failures into the job's final error string."""
    _err_bits: list[str] = []
    if job.get('lora_failed'):
        _err_bits.append(f'LoRA: {(job.get("lora_error") or "failed")[:160]}')
    if prev_res.get('error'):
        _err_bits.append(f'preview: {prev_res["error"]}')
    return '; '.join(_err_bits) or 'no preview images produced'


def finalize_job(ctx, char_mf, prev_res):
    """Record the preview verdict on the job and mark it done or errored.

    Rebinds `ctx.job` to the live job record (the old closure re-read it here)
    and emits exactly one terminal line.
    """
    ctx.job = _char_gen_jobs.get(ctx.char_id) or {}
    _job = ctx.job
    _job['preview_quality_ok'] = prev_res.get('preview_quality_ok', False)
    _job['preview_warning'] = (prev_res.get('preview_warning') or '')[:500]
    _job['preview_backends'] = prev_res.get('backends') or []
    _ds_fin = ctx.info.get('dataset_dir') or os.path.join(_CHARS_DATASET_ROOT, ctx.char_id)
    _have_prev = _have_usable_char_preview(_ds_fin, char_mf, ctx.params, ctx.info)
    _lora_expected = bool(_job.get('kick_lora', True))
    _quality_ok = preview_quality_ok(prev_res, _have_prev, _lora_expected)
    if not _lora_expected:
        ctx.emit(
            f'Character {ctx.char_id} dataset ready (LoRA/previews not requested)',
            level='INFO',
            stage='done',
        )
        _char_mark_done(ctx.char_id)
    elif _have_prev and _quality_ok:
        if _job.get('lora_failed'):
            ctx.emit(
                'Character pipeline finished — preview images saved (LoRA training failed; check preview quality)',
                level='WARN',
                stage='done',
            )
        else:
            ctx.emit(f'Character {ctx.char_id} generation complete', level='INFO', stage='done')
        _char_mark_done(ctx.char_id)
    elif _have_prev:
        _pwarn = _job.get('preview_warning') or 'Preview files exist but quality checks failed'
        ctx.emit(f'Character generation incomplete: {_pwarn}', level='ERROR', stage='error')
        _char_mark_error(ctx.char_id, _pwarn)
    else:
        _final_err = final_error_message(_job, prev_res)
        ctx.emit(f'Character generation failed: {_final_err}', level='ERROR', stage='error')
        _char_mark_error(ctx.char_id, _final_err)
