# This file exists to re-export; the import block below is the original one,
# kept so attribute access like the old module had it works.

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
import os
import re
import time
import threading


from zyg_workflows import gui_state
from zyg_workflows.bin import exe
from zyg_workflows.runtime import _record_token_usage
from zyg_workflows.encode_utils import (
    _cq_for_crf,
    _kb_encode_wait_seconds,
    _nvenc_vcodec_args,
    _x264_vcodec_args,
)
from zyg_workflows.pipeline_common import (
    SMOKE_MARKER_FILE,
    is_test_pipeline_id,
    smoke_output_root,
)
from zyg_workflows.subproc_registry import _register_marker

# Local-LLM roster lives in murch_engine and is defined there ONCE. Importing the
# constant (rather than re-pinning a model name here) is what keeps Stage 3b's
# fallback and Stage 3.1's Ollama warm-up on the same model the engine will
# actually call — they had drifted onto gpt-oss:20b and qwen2.5:72b respectively.
# 2026-09-17: every Anthropic call in this pipeline runs on Claude Opus 5 through the
# operator's subscription (subscription_llm.py). _llm_key() gates the call sites the way
# ANTHROPIC_API_KEY used to, _llm_client() replaces anthropic.Anthropic(api_key=...), and
# _LLM_SMALL / _LLM_LARGE replace the Haiku / Sonnet names (both Opus 5 in subscription
# mode; ZYG_SCHOLARLY_LLM_BACKEND=api restores the old models on the key).
from zyg_workflows.subscription_llm import (
    MODEL_SMALL as _LLM_SMALL,
    anthropic_client as _llm_client,
    api_key_or_login as _llm_key,
)
from zyg_workflows.vram_manager import (
    _hw_monitor_loop,
)
from zyg_workflows import runtime
from zyg_workflows import pipeline_config as _pipeline_config
from zyg_workflows.pipeline_config import (
    _FORCE_CPU_POST_ENCODE,
    _RUNTIME_DIR,
    _SCHOLARLY_SMOKE_MAX_IMAGES,
)
from zyg_workflows.runtime import (
    _ams_iso,
    _NVENC_SEM,
    _runtime_path,
    workflow_jobs as _workflow_jobs,
)
from zyg_workflows import scholarly_motion as _scholarly_motion
import logging as _zyg_logging

# The sections of the original pipeline_scholarly.py, imported in their original order
# so module-level side effects still happen in that order, then every name the
# single-file module defined, re-exported so no importer anywhere changes.
from .constants import (
    _ANATOMY_Q_ORIGINAL,
    _ANATOMY_Q_SHIPPED,
    _INTENSITY_DEFAULT,
    _INTENSITY_MOOD_SUFFIX,
    _INTENSITY_RANK,
    _INTENSITY_STYLE_CTX,
    _MODULE_IMPORTED_AT,
    _PERSON_NOUN_RE,
    _SCHOLARLY_SEC_PER_WORD,
    _SEED_STOPWORDS,
    _research_title_matches_directive,
    _scholarly_duration_targets,
    _scholarly_image_intensity,
    _scholarly_n_images,
    _smoke_cap,
    _title_from_directive,
)
from .rewrites import (
    _ALL_BUCKETS,
    _BARE_CTX_STOP,
    _DROP_LEAD_RE,
    _DROP_TAIL_RE,
    _ERA_GATE_DEFAULT,
    _ERA_NEGATIVE,
    _GORE_NOUN_RES,
    _GORE_NOUN_TABLE,
    _HAIR_RE,
    _MODERN_PROMPT_TERMS,
    _MODERN_TERM_RE,
    _PEOPLE_RE,
    _PERIOD_DESCRIPTOR_RE,
    _PERIOD_NOUN_RES,
    _PERIOD_NOUN_TABLE,
    _bare_context,
    _period_bucket,
    _period_hair_backstop,
    _period_noun_rewrite,
    _render_safety_rewrite,
    _scan_modern_terms,
)
from .era import (
    _TEXT_FRAMING_FIX,
    _TEXT_SUBJECT_RE,
    _TEXT_SUBJECT_WORDS,
    _TEXT_SUBJ_WINDOW,
    _WRITTEN_NOUNS,
    _derive_episode_era,
    _strip_written_subject,
)
from .pipeline import (
    _run_scholarly_pipeline,
)
from .render_kb import (
    _render_kb_pil_shared,
)

# Below the section imports, so the original import order survives verbatim; every
# section builds its own `_zyg_log` and none reads this one back from the package.
_zyg_log = _zyg_logging.getLogger(__name__)

# Re-export surface: every name below is imported above and not used in this
# module. Nothing does ``import *`` from here, so __all__ changes no behaviour;
# it declares the inherited namespace public so ruff does not read it as dead.
__all__ = [
    'json',
    'os',
    're',
    'time',
    'threading',
    'gui_state',
    'exe',
    '_record_token_usage',
    '_cq_for_crf',
    '_kb_encode_wait_seconds',
    '_nvenc_vcodec_args',
    '_x264_vcodec_args',
    'SMOKE_MARKER_FILE',
    'is_test_pipeline_id',
    'smoke_output_root',
    '_register_marker',
    '_LLM_SMALL',
    '_llm_client',
    '_llm_key',
    '_hw_monitor_loop',
    'runtime',
    '_pipeline_config',
    '_FORCE_CPU_POST_ENCODE',
    '_RUNTIME_DIR',
    '_SCHOLARLY_SMOKE_MAX_IMAGES',
    '_ams_iso',
    '_NVENC_SEM',
    '_runtime_path',
    '_workflow_jobs',
    '_scholarly_motion',
    '_ANATOMY_Q_ORIGINAL',
    '_ANATOMY_Q_SHIPPED',
    '_INTENSITY_DEFAULT',
    '_INTENSITY_MOOD_SUFFIX',
    '_INTENSITY_RANK',
    '_INTENSITY_STYLE_CTX',
    '_MODULE_IMPORTED_AT',
    '_PERSON_NOUN_RE',
    '_SCHOLARLY_SEC_PER_WORD',
    '_SEED_STOPWORDS',
    '_research_title_matches_directive',
    '_scholarly_duration_targets',
    '_scholarly_image_intensity',
    '_scholarly_n_images',
    '_smoke_cap',
    '_title_from_directive',
    '_ALL_BUCKETS',
    '_BARE_CTX_STOP',
    '_DROP_LEAD_RE',
    '_DROP_TAIL_RE',
    '_ERA_GATE_DEFAULT',
    '_ERA_NEGATIVE',
    '_GORE_NOUN_RES',
    '_GORE_NOUN_TABLE',
    '_HAIR_RE',
    '_MODERN_PROMPT_TERMS',
    '_MODERN_TERM_RE',
    '_PEOPLE_RE',
    '_PERIOD_DESCRIPTOR_RE',
    '_PERIOD_NOUN_RES',
    '_PERIOD_NOUN_TABLE',
    '_bare_context',
    '_period_bucket',
    '_period_hair_backstop',
    '_period_noun_rewrite',
    '_render_safety_rewrite',
    '_scan_modern_terms',
    '_TEXT_FRAMING_FIX',
    '_TEXT_SUBJECT_RE',
    '_TEXT_SUBJECT_WORDS',
    '_TEXT_SUBJ_WINDOW',
    '_WRITTEN_NOUNS',
    '_derive_episode_era',
    '_strip_written_subject',
    '_run_scholarly_pipeline',
    '_render_kb_pil_shared',
]
