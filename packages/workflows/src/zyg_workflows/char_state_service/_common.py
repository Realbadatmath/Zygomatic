# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import os
from zyg_workflows import gui_state

from zyg_workflows import paths
from zyg_workflows import runtime as _runtime
from zyg_workflows.vram_manager import _release_pipeline_vram
from zyg_workflows.pipeline_config import (
    _ANIMATED_USE_FLUX,
    _CHAR_DEFAULT_MODEL_FAMILY,
    _CHAR_DRIFT_ANIMATED,
    _CHAR_DRIFT_MIN,
    _CHAR_DUAL_LORA_PHOTOREAL,
    _CHAR_PHOTOREAL_HYBRID_PREVIEW,
    _CHAR_STATE_FILENAME_FMT,
    _CONTACT_SHEET_STATE_FMT,
    _PHOTOREAL_CLIP_NEG,
    _PHOTOREAL_CLIP_POS,
    _PREVIEW_FACE_SEED_CANDIDATES,
    _PREVIEW_LORA_WAIT_S,
    _PREVIEW_SEED_CANDIDATES,
)
from zyg_workflows.runtime import (
    _ams_iso,
    _ams_now,
    _char_gen_jobs,
    _contact_sheet_jobs,
    _contact_sheet_push_review_pending,
    _creature_gen_jobs,
    _parse_iso_to_ams,
    _runtime_path,
)
import logging as _zyg_logging

# ── re-export surface ────────────────────────────────────────────────────────
# The original module's globals, pulled in by the verbatim move so that
# ``_common.<name>`` resolves the way ``crewai_web_gui.<name>`` did. The siblings
# take only this file's own _CHARS_* / _preview_env_on / _zyg_log, but these are
# the private names of the pre-split contract above, so they stay declared
# rather than deleted. The four stdlib names that came with them (json, time,
# threading, datetime) had no reader at all and are gone. Nothing does
# ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    'gui_state',
    '_runtime',
    '_release_pipeline_vram',
    '_ANIMATED_USE_FLUX',
    '_CHAR_DEFAULT_MODEL_FAMILY',
    '_CHAR_DRIFT_ANIMATED',
    '_CHAR_DRIFT_MIN',
    '_CHAR_DUAL_LORA_PHOTOREAL',
    '_CHAR_PHOTOREAL_HYBRID_PREVIEW',
    '_CHAR_STATE_FILENAME_FMT',
    '_CONTACT_SHEET_STATE_FMT',
    '_PHOTOREAL_CLIP_NEG',
    '_PHOTOREAL_CLIP_POS',
    '_PREVIEW_FACE_SEED_CANDIDATES',
    '_PREVIEW_LORA_WAIT_S',
    '_PREVIEW_SEED_CANDIDATES',
    '_ams_iso',
    '_ams_now',
    '_char_gen_jobs',
    '_contact_sheet_jobs',
    '_contact_sheet_push_review_pending',
    '_creature_gen_jobs',
    '_parse_iso_to_ams',
    '_runtime_path',
]

_zyg_log = _zyg_logging.getLogger(__name__)

#: Per-character dataset / LoRA-output roots, resolved once at import.
_CHARS_DATASETS = paths.ZYG_LORA_DATASETS / 'storyteller_chars'
_CHARS_OUTPUTS = paths.ZYG_LORA_OUTPUTS / 'storyteller_chars'


# 2026-07-31: env gates for the identity-audit fixes below.  Read at CALL time (not
# import time) so an operator can roll a behaviour back without restarting the GUI.
# Every flag defaults to the NEW (safe) behaviour; set to 0 for the old one.
def _preview_env_on(name: str, default: str = '1') -> bool:
    return (os.environ.get(name, default) or '').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
        '',
    )
