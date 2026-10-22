# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sfx_merger.py — the SFX Merger behind the :8899 SFX Library tab (2026-08-25).

Layers sounds from the audio asset libraries on ONE timeline so they play at
the same time (or offset by an exact number of milliseconds), tweaks each layer
with a rack of knobs, and saves the result back into the library as a new
`merged` asset that carries a licence sidecar DERIVED from its sources plus the
full recipe, so any merge can be reopened and re-edited.

Design
    stem  = one source file after its tweak chain (ffmpeg -af …), 48 kHz stereo
            float32, cached on a hash of (file identity, tweak). Turning a knob
            re-renders ONE stem; a mix of untouched layers costs nothing.
    mix   = every stem delayed by its start (adelay in SAMPLES, so a typed
            "1.250 s" lands at sample 60000, not "about a frame later") summed
            with amix normalize=0 — a layer keeps the level the operator set —
            then peak-scaled once if the sum clips. Cached on the recipe hash.
    save  = the mix copied into data/asset_libraries/merged/<slug>.wav with a
            sidecar entry: licence = the STRICTEST of the sources (a CC-BY source
            keeps its credit; an unclean source fails the whole merge CLOSED —
            ambience_ingest.license_gate would refuse it at publish time), and
            `merge_recipe` so the tab can reopen it.

Everything is ffmpeg as an external tool (see feedback_licence_policy: copyleft
in a TOOL never taints assets); numpy/soundfile only read the finished wav to
measure its peak.
"""

import hashlib
import json
import logging as _zyg_logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from zyg_workflows.bin import exe
import time

from zyg_workflows.sfx_merger.constants import (
    _zyg_log,
    _HERE,
    _WORK,
    _SR,
    _MERGED_CAT,
    MAX_ITEMS,
    MAX_SLOTS,
    _FF_TIMEOUT,
    _MIX_TTL,
    _STEM_TTL,
    _BUDGET_BYTES,
    _SWEEP_EVERY,
    _SWEEP,
    _LOCKS,
    _LOCKS_GUARD,
    _MAX_LAYER_S,
    _MAX_MIX_S,
    _MAX_START_S,
    _RENDER_SEM,
    _REL_RE,
)
from zyg_workflows.sfx_merger.racks import (
    RACKS,
    _PARAMS,
    plugin_host,
    _PLUGIN_EFFECT_TYPES,
    sfx_fx,
    _FX_EFFECT_TYPES,
    EFFECT_TYPES,
    _EFFECT_BY_ID,
    _PARAMS_BY_TYPE,
    _params_for,
    defaults,
    spec,
    clean_tweak,
    _is_default,
    _slots_from_legacy,
    clean_slots,
)
from zyg_workflows.sfx_merger.render import (
    _als,
    source_path,
    probe,
    probe_duration,
    _run,
    _tweak_filters,
    _format_filters,
    _lock,
    _dirs,
    _file_ident,
    stem,
    _render_stem_chain,
    _clean_items,
    _peak_scale,
    render_mix,
    resolve_audio,
    _sweep,
)
from zyg_workflows.sfx_merger.saving import (
    _ALLOWED,
    _ATTRIB,
    _norm,
    _source_clean,
    derive_licence,
    _slug,
    save_mix,
    _REC_CAT,
    save_recording,
    recipe,
)
from zyg_workflows.sfx_merger.analysis import _ANALYSIS_TTL, _num, _stats_pass, _picture, analyze
from zyg_workflows.sfx_merger.export import _EXPORT_FORMATS, _DITHERS_OK, export_mix, _CTYPES, content_type

# Bound on only one branch in the single module, so an absent attribute there
# rather than a hard error: copied tolerantly, not imported strictly.
from zyg_workflows.sfx_merger import racks as _m_racks

if hasattr(_m_racks, '_e'):
    _e = _m_racks._e

#: The package IS the namespace sfx_merger.py had: every name above is re-exported.
__all__ = [
    'hashlib',
    'json',
    '_zyg_logging',
    'os',
    're',
    'shutil',
    'subprocess',
    'tempfile',
    'threading',
    'exe',
    'time',
    'MAX_ITEMS',
    'MAX_SLOTS',
    '_BUDGET_BYTES',
    '_FF_TIMEOUT',
    '_HERE',
    '_LOCKS',
    '_LOCKS_GUARD',
    '_MAX_LAYER_S',
    '_MAX_MIX_S',
    '_MAX_START_S',
    '_MERGED_CAT',
    '_MIX_TTL',
    '_REL_RE',
    '_RENDER_SEM',
    '_SR',
    '_STEM_TTL',
    '_SWEEP',
    '_SWEEP_EVERY',
    '_WORK',
    '_zyg_log',
    'EFFECT_TYPES',
    'RACKS',
    '_EFFECT_BY_ID',
    '_FX_EFFECT_TYPES',
    '_PARAMS',
    '_PARAMS_BY_TYPE',
    '_PLUGIN_EFFECT_TYPES',
    '_is_default',
    '_params_for',
    '_slots_from_legacy',
    'clean_slots',
    'clean_tweak',
    'defaults',
    'plugin_host',
    'sfx_fx',
    'spec',
    '_als',
    '_clean_items',
    '_dirs',
    '_file_ident',
    '_format_filters',
    '_lock',
    '_peak_scale',
    '_render_stem_chain',
    '_run',
    '_sweep',
    '_tweak_filters',
    'probe',
    'probe_duration',
    'render_mix',
    'resolve_audio',
    'source_path',
    'stem',
    '_ALLOWED',
    '_ATTRIB',
    '_REC_CAT',
    '_norm',
    '_slug',
    '_source_clean',
    'derive_licence',
    'recipe',
    'save_mix',
    'save_recording',
    '_ANALYSIS_TTL',
    '_num',
    '_picture',
    '_stats_pass',
    'analyze',
    '_CTYPES',
    '_DITHERS_OK',
    '_EXPORT_FORMATS',
    'content_type',
    'export_mix',
    '_m_racks',
]
