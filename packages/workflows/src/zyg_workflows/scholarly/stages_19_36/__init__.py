# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stages 10 and 12-19 of the scholarly pipeline — FLUX setup through the burn-in.

A pure move out of `_run_scholarly_pipeline` in `zyg_workflows.pipeline_scholarly`:
the statements, their order and their side effects are the ones the monolith ran.
Unlike `stages_01_18`, which rewrote a crossing local to `ctx.<name>`, these
stages keep the body **byte-identical** and carry the crossings in glue lines
around it::

    def stage_nn_slug(ctx):
        job = ctx.job             # what crosses in
        <the range, verbatim>
        ctx.final_video_path = …  # what crosses out

That style is not a preference: these ranges define twenty nested `def`s (the
Ken-Burns renderer, the music bed, the prompt builder), and a closure cannot
capture an attribute, so a `ctx.`-rewritten range with closures comes out
half-rewritten. With plain locals every name — top level or nested — resolves
to the same object it resolved to before.

`UNSET` is for the one crossing whose local may legitimately be unbound:
Stage 3.7 calls `_sch_typography_pass()` / `_sch_hand_qc_pass()` inside
`except NameError:` to detect "the FLUX stage never ran". A field defaulting to
`None` would turn that `NameError` into a `TypeError`, so the glue only binds
the local when the field was actually written.

Marker 11 (the 4,904-line "Stage 3.5 Pre-generation" block) is still inline in
the monolith between `stage_10_flux_image_generation` and `stage_12_hand_qc`,
which is why the numbering skips 11.

See SPLIT_LOG.md for the stage→marker map and the full list of non-mechanical spots.
"""

import sys as _sys
from types import ModuleType as _ModuleType

# The import block the single file carried, so `stages_19_36.os`,
# `stages_19_36.requests`, `stages_19_36._zyg_log` … still resolve.
from ._common import (
    UNSET,
    _FORCE_CPU_POST_ENCODE,
    _INTENSITY_MOOD_SUFFIX,
    _KB_THREAD_STAGGER_S,
    _LLM_SMALL,
    _NVENC_SEM,
    _OLLAMA_BASE_URL,
    _SCHOLARLY_SEC_PER_WORD,
    _SEED_STOPWORDS,
    _TEXT_FRAMING_FIX,
    _TEXT_SUBJECT_RE,
    _ams_iso,
    _apply_color_grade,
    _bench_replay_get,
    _bm_record_pipeline,
    _burn_subtitles,
    _cleanup_pipeline_output,
    _cq_for_crf,
    _derive_episode_era,
    _ensure_comfy_offload_env,
    _ffmpeg_popen_nvenc_first,
    _ffmpeg_run_nvenc_first,
    _kb_encode_wait_seconds,
    _llm_client,
    _llm_key,
    _load_flux_seconds_per_image_estimate,
    _log_prompt,
    _make_book_intro,
    _nvenc_vcodec_args,
    _parse_iso_to_ams,
    _record_token_usage,
    _register_prompt,
    _scholarly_motion,
    _scholarly_n_images,
    _scp_output_to_windows,
    _seal,
    _smoke_cap,
    _update_marker,
    _urlsplit,
    _x264_vcodec_args,
    _zyg_log,
    _zyg_logging,
    exe,
    os,
    paths,
    requests,
)

# The stage functions, imported in the single file's own section order.
from . import _common
from . import prompt_helpers
from . import prompt_builder
from . import flux_image_generation
from .flux_image_generation import stage_10_flux_image_generation
from . import qc_and_motion
from .qc_and_motion import (
    stage_12_hand_qc,
    stage_13_tts_rhythm_refresh,
    stage_14_ltx_motion,
)
from . import image_durations
from . import video_assembly
from .video_assembly import stage_15_video_assembly
from . import music_bed
from .music_bed import stage_16_music_bed
from . import finishing
from .finishing import (
    stage_17_colour_grade,
    stage_18_book_intro,
    stage_19_burn_subtitles,
)

__all__ = [
    'UNSET',
    '_FORCE_CPU_POST_ENCODE',
    '_INTENSITY_MOOD_SUFFIX',
    '_KB_THREAD_STAGGER_S',
    '_LLM_SMALL',
    '_NVENC_SEM',
    '_OLLAMA_BASE_URL',
    '_SCHOLARLY_SEC_PER_WORD',
    '_SEED_STOPWORDS',
    '_TEXT_FRAMING_FIX',
    '_TEXT_SUBJECT_RE',
    '_ams_iso',
    '_apply_color_grade',
    '_bench_replay_get',
    '_bm_record_pipeline',
    '_burn_subtitles',
    '_cleanup_pipeline_output',
    '_cq_for_crf',
    '_derive_episode_era',
    '_ensure_comfy_offload_env',
    '_ffmpeg_popen_nvenc_first',
    '_ffmpeg_run_nvenc_first',
    '_kb_encode_wait_seconds',
    '_llm_client',
    '_llm_key',
    '_load_flux_seconds_per_image_estimate',
    '_log_prompt',
    '_make_book_intro',
    '_nvenc_vcodec_args',
    '_parse_iso_to_ams',
    '_record_token_usage',
    '_register_prompt',
    '_scholarly_motion',
    '_scholarly_n_images',
    '_scp_output_to_windows',
    '_seal',
    '_smoke_cap',
    '_update_marker',
    '_urlsplit',
    '_x264_vcodec_args',
    '_zyg_log',
    '_zyg_logging',
    'exe',
    'os',
    'paths',
    'requests',
    'stage_10_flux_image_generation',
    'stage_12_hand_qc',
    'stage_13_tts_rhythm_refresh',
    'stage_14_ltx_motion',
    'stage_15_video_assembly',
    'stage_16_music_bed',
    'stage_17_colour_grade',
    'stage_18_book_intro',
    'stage_19_burn_subtitles',
]

#: Every module a stage body reads its globals from, in import order.
_SECTIONS = (
    _common,
    prompt_helpers,
    prompt_builder,
    flux_image_generation,
    qc_and_motion,
    image_durations,
    video_assembly,
    music_bed,
    finishing,
)


class _StagesModule(_ModuleType):
    """Keep `setattr(stages_19_36, name, value)` reaching the stage bodies.

    The single file had one namespace, so patching `_scp_output_to_windows` on it
    rebound the name `stage_19_burn_subtitles` actually reads — which is what
    `packages/workflows/tests/test_egress_seal.py` does with `monkeypatch`. The
    bodies now read their own module globals, so a write to the package attribute
    has to be written through to every section module that holds the name.
    """

    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _section in self.__dict__.get('_SECTIONS') or ():
            if name in _section.__dict__:
                _section.__dict__[name] = value

    def __delattr__(self, name):
        _ModuleType.__delattr__(self, name)
        for _section in self.__dict__.get('_SECTIONS') or ():
            _section.__dict__.pop(name, None)


# Last statement: from here on the write-through above is live.
_sys.modules[__name__].__class__ = _StagesModule
