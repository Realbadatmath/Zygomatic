# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background worker thread body of the character-generate route.

Moved from bp_storyteller.py:1385-1905 (2026-10-06 split): the single route
function api_internal_storyteller_generate_character was 879 lines — over the
800-line module ceiling on its own — so its nested `_bg_generate` closure was
lifted into this factory. The nine parameters are exactly the closure's free
variables (symtable-derived).

2026-10-09 function split: the closure itself was 521 lines, over the 300-line
function cap. Its stages now live in generate_worker_stages.py and `_bg_generate`
is the orchestrator that calls them in the original order; the stage state the
closure kept in locals travels in one `CharGenContext`.
"""

from zyg_dashboard.bp_storyteller import (  # noqa: E402  the package __init__ binds these before it imports this module
    _char_gen_jobs,
    _char_mark_error,
    _char_save_state,
)
from zyg_dashboard.bp_storyteller import generate_worker_stages as _ST


def _make_bg_generate(
    info,
    char_id,
    params,
    model_family,
    kick_lora,
    _uploaded_image_paths,
    _photo_analysis,
    _char_emit,
    _check_char_stop,
):
    """Return the character-generate worker closure for one job."""

    def _bg_generate():
        ctx = _ST.CharGenContext(
            info=info,
            char_id=char_id,
            params=params,
            kick_lora=kick_lora,
            uploaded_image_paths=_uploaded_image_paths,
            photo_analysis=_photo_analysis,
            emit=_char_emit,
            check_stop=_check_char_stop,
            job=_char_gen_jobs.get(char_id, {}),
        )
        try:
            _check_char_stop()
            _ST.resolve_job_model_family(ctx, model_family)
            _ST.apply_power_limit(ctx)

            # ── Stage 1a: Render characters (Blender 3D or uploaded photos) ───
            if _uploaded_image_paths:
                ctx.info = _ST.run_photo_import_stage(ctx)
            else:
                ctx.info = _ST.run_blender_render_stage(ctx)

            ctx.info['model_family'] = ctx.model_family
            ctx.info['char_id'] = char_id

            _ST.run_character_bible_stage(ctx)

            if kick_lora:
                _ST.run_lora_training_stage(ctx)

            # ── Stage 1d — character preview render (FLUX or SDXL) ────────
            _char_mf = _ST.resolve_preview_family(ctx)
            _prev_res = _ST.run_preview_render_stage(ctx, _char_mf)
            _ST.finalize_job(ctx, _char_mf, _prev_res)
        except RuntimeError as _e_stop:
            if 'stopped by user' in str(_e_stop).lower():
                _j = _char_gen_jobs.get(char_id, {})
                _j['status'] = 'stopped'
                _j['error'] = str(_e_stop)
                _char_save_state(char_id)
                _char_emit(str(_e_stop), level='WARN', stage='stopped')
                return
            raise
        except Exception as _e:
            _char_emit(f'Character generation failed: {_e}', level='ERROR', stage=ctx.job.get('stage', ''))
            _char_mark_error(char_id, str(_e))

    return _bg_generate
