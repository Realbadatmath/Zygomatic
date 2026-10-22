# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The import block `stages_19_36.py` carried, kept in one place.

Every module of this package imports from here, so the names resolve to the
same objects the single file bound — including `_zyg_log`, whose logger name
is still `zyg_workflows.pipeline_scholarly`.
"""

import logging as _zyg_logging
import os
from urllib.parse import urlsplit as _urlsplit

import requests

from zyg_workflows import paths
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.bin import exe
from zyg_workflows import scholarly_motion as _scholarly_motion
from zyg_workflows.color_grade import _apply_color_grade
from zyg_workflows.encode_utils import (
    _cq_for_crf,
    _ffmpeg_popen_nvenc_first,
    _ffmpeg_run_nvenc_first,
    _kb_encode_wait_seconds,
    _nvenc_vcodec_args,
    _x264_vcodec_args,
)
from zyg_workflows.pipeline_common import (
    _cleanup_pipeline_output,
    _load_flux_seconds_per_image_estimate,
)
from zyg_workflows.pipeline_config import _FORCE_CPU_POST_ENCODE, _KB_THREAD_STAGGER_S, _OLLAMA_BASE_URL
from zyg_workflows.pipeline_scholarly import (
    _INTENSITY_MOOD_SUFFIX,
    _SCHOLARLY_SEC_PER_WORD,
    _SEED_STOPWORDS,
    _TEXT_FRAMING_FIX,
    _TEXT_SUBJECT_RE,
    _derive_episode_era,
    _scholarly_n_images,
    _smoke_cap,
)
from zyg_workflows.pipeline_video import _burn_subtitles, _make_book_intro
from zyg_workflows.runtime import (
    _NVENC_SEM,
    _ams_iso,
    _bench_replay_get,
    _bm_record_pipeline,
    _parse_iso_to_ams,
    _record_token_usage,
)
from zyg_workflows.scholarly.context import UNSET
from zyg_workflows.stage_runner import _log_prompt, _register_prompt, _scp_output_to_windows
from zyg_workflows.subproc_registry import _update_marker
from zyg_workflows.subscription_llm import (
    MODEL_SMALL as _LLM_SMALL,
    anthropic_client as _llm_client,
    api_key_or_login as _llm_key,
)
from zyg_workflows.vram_manager import _ensure_comfy_offload_env

# Same logger name the statements had in pipeline_scholarly, so the
# 'suppressed ...' debug lines of a run keep landing under one name.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')

#: This module IS the original import block: every name above is re-exported.
__all__ = [
    '_zyg_logging',
    'os',
    '_urlsplit',
    'requests',
    'paths',
    '_seal',
    'exe',
    '_scholarly_motion',
    '_apply_color_grade',
    '_cq_for_crf',
    '_ffmpeg_popen_nvenc_first',
    '_ffmpeg_run_nvenc_first',
    '_kb_encode_wait_seconds',
    '_nvenc_vcodec_args',
    '_x264_vcodec_args',
    '_cleanup_pipeline_output',
    '_load_flux_seconds_per_image_estimate',
    '_FORCE_CPU_POST_ENCODE',
    '_KB_THREAD_STAGGER_S',
    '_OLLAMA_BASE_URL',
    '_INTENSITY_MOOD_SUFFIX',
    '_SCHOLARLY_SEC_PER_WORD',
    '_SEED_STOPWORDS',
    '_TEXT_FRAMING_FIX',
    '_TEXT_SUBJECT_RE',
    '_derive_episode_era',
    '_scholarly_n_images',
    '_smoke_cap',
    '_burn_subtitles',
    '_make_book_intro',
    '_NVENC_SEM',
    '_ams_iso',
    '_bench_replay_get',
    '_bm_record_pipeline',
    '_parse_iso_to_ams',
    '_record_token_usage',
    'UNSET',
    '_log_prompt',
    '_register_prompt',
    '_scp_output_to_windows',
    '_update_marker',
    '_LLM_SMALL',
    '_llm_client',
    '_llm_key',
    '_ensure_comfy_offload_env',
    '_zyg_log',
]
