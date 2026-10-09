# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_merger.py — the Voice Merger behind the :8899 Voices tab (2026-08-31).

Independent sibling of sfx_merger.py — same lane-board mechanic (layer sources
on one timeline, tweak each with a knob rack, save the result back into a
library as a new asset), rebuilt for voice TAKES instead of SFX library files.
Kept as its own module rather than a generalisation of sfx_merger so the two
UIs can diverge freely; the two are kept in sync by hand where the mechanic is
genuinely the same (the tweak rack, the adelay/amix mix math, the peak-scale
pass), not by sharing code.

Design (identical shape to sfx_merger.py, see that module for the fuller
rationale)
    stem  = one layer after its slot chain (ffmpeg -af … / a plugin pass),
            48 kHz stereo float32, cached on (source identity, slots).
    mix   = every stem delayed by its start (adelay in SAMPLES) summed with
            amix normalize=0, then peak-scaled once if the sum clips.
    save  = the mix copied into data/asset_libraries/voice_mix/<slug>.wav with
            a sidecar licence DERIVED FROM THE SOURCE VOICES — not from a file
            licence, because a take has none of its own. A layer that is a
            rendered TAKE is cleared through voice_studio.publication_policy()
            (the same "avoid the Kyutai-descended voices, and the excluded age
            bands, for published audio" standing decision the rest of the
            studio already enforces); a layer that is a PREVIOUS voice mix or
            recording is cleared through its own already-derived sidecar. One
            unclear source fails the whole merge closed, same contract as SFX.

Three source kinds, chosen by `cat`:
    'take'                — a rendered line: `f` is "<voice id>|<take key>",
                             resolved through voice_studio's own take cache
                             (voice_studio.resolve_audio), never a raw path.
    'clip'                — a voice's own audition clip on disk (its seed wav,
                             or a bench row's declared extra): `f` is
                             "<voice id>|seed/<relpath>", accepted only when that
                             rel is one voice_studio.audition_clips() names for
                             THAT voice. Added 2026-09-10 for the bench voices,
                             which have no baked take and never will — without
                             it their Voice Studio rows had nothing to merge.
                             Licensed exactly like a take: the voice's policy.
    'voice_mix'/'voice_recorded' — a previously saved merge or mic recording,
                             resolved like any other asset_library_service
                             audio category — so a merge can be re-opened as a
                             layer inside a bigger one, same as SFX's 'merged'.

Everything is ffmpeg as an external tool; numpy/soundfile only read the
finished wav to measure its peak. See feedback_licence_policy: copyleft in a
TOOL never taints assets.
"""

# ruff: noqa: E402,F401  # the original top import block and the re-export block are deliberate

import hashlib
import json
import logging as _zyg_logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from zyg_workflows.bin import exe

from zyg_workflows.voice_merger.rack import (
    _HERE,
    _WORK,
    _SR,
    _MERGED_CAT,
    _REC_CAT,
    _LIB_CATS,
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
    _TAKE_FN_RE,
    _CLIP_FN_RE,
    RACKS,
    _PARAMS,
    _zyg_log,
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

try:
    from zyg_workflows.voice_merger.rack import plugin_host
except ImportError:
    pass
try:
    from zyg_workflows.voice_merger.rack import _PLUGIN_EFFECT_TYPES
except ImportError:
    pass
from zyg_workflows.voice_merger.render import (
    _vs,
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
from zyg_workflows.voice_merger.library import (
    _source_info,
    _source_ok,
    derive_licence,
    _slug,
    save_mix,
    save_recording,
    recipe,
    check_sources,
    take_ref,
    voice_ref,
)
