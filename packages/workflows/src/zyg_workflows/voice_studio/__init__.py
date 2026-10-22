# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.py — the Voices tab's tweak engine + preset store (2026-08-11).

WHY THIS EXISTS
---------------
Abel's voice was tuned the hard way: hand-run ffmpeg transforms on a Maya1 take,
measured with Praat, judged by ear, then frozen (see
data/assets/voice_seeds/abel_narrator_seed.json — it records k=1.00 / m=1.45 and
the two REJECTED candidates whose vocal tract landed in adult-female territory).
That loop lived entirely in a terminal. This module puts the same loop behind a
knob panel so the operator can audition a change, SEE what it did to F0 and vocal
tract length, and keep the ones that work as named presets.

THE THREE PLACES A VOICE CAN BE TWEAKED — they are not interchangeable:

  1. SOURCE (seed shaping, `seed_k` / `seed_m`)
     Reshapes the reference wav BEFORE the cloner ever sees it, using the exact
     transform that built the frozen seed: asetrate/atempo k (moves pitch AND
     shrinks/grows the tract together) then rubberband pitch=m formant=preserved
     (moves pitch, leaves the tract). This changes WHO is speaking. The frozen
     seed on disk is never touched — shaping writes a scratch copy per render.

  2. ENGINE (per-engine knobs)
     Chatterbox: exaggeration / cfg_weight / temperature. IndexTTS-2: emo_alpha /
     emo_text. This changes HOW they deliver the line, not who they are.

  3. RENDER (everything after synthesis)
     Pitch, formant scale, tempo, EQ, de-ess, compression, room, loudness. This
     changes the TONE of the recording.

MEASUREMENT, NOT VIBES
----------------------
Every render is measured through voice_qc (Praat in its own venv) and reported
against the voice's age band. VTL is the number that matters: the seed metadata
records two takes rejected at 14.16 and 14.04 cm because a tract that short reads
FEMALE regardless of how right the pitch is. The UI shows the band so a knob move
that sounds fine but measures wrong is visible before it is saved.

Presets are INERT DATA. Nothing in the production narration path reads them at
all today — abel_voice.build_abel_narration still uses its own hard-coded engine
settings — so saving or activating a preset can never change a running episode.
`active_params()` + `engine_kwargs()` are the adoption path when the operator
decides a preset should go live; that wiring is deliberately not switched on
here, because a knob panel that silently re-tunes a shipping narrator is a
different and much riskier product than a knob panel.

License: ffmpeg (incl. GPL librubberband) is invoked as an external TOOL, never
distributed — same standing as narration_service.pitch_lift. Nothing here ships.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.bin import exe

from zyg_workflows.voice_studio.constants import _zyg_log

from zyg_workflows.voice_studio.constants import (
    annotations,
    _HERE,
    _SEED_DIR,
    PRESET_ROOT,
    RENDER_ROOT,
    _INDEXTTS_DIR,
    _INDEXTTS_PY,
    _INDEXTTS_WORKER,
    _CHATTERBOX_DIR,
    _CHATTERBOX_PY,
    _CHATTERBOX_WORKER,
    _TTS_CORES,
    _TTS_THREADS,
    MAX_PREVIEW_CHARS,
    _SR,
    _SEED_SR,
    DEFAULT_LINES,
    VOICES,
)
from zyg_workflows.voice_studio.benches import (
    _POOL_DIR,
    _POOL_MANIFEST,
    _POOL_EDITORIAL,
    _POOL_CAUTION,
    _POOL_LINES,
    _POOL_NOTE,
    _POOL_MEASURED,
    _load_pool_voices,
    _TEEN_DIR,
    _TEEN_MANIFEST,
    _BENCH_DIR,
    _TEEN_LINES,
    _load_teen_voices,
)
from zyg_workflows.voice_studio.policy import (
    SOURCE_LICENCES,
    voice_licence,
    _PUBLISH_EXCLUDED_SOURCES,
    _PUBLISH_EXCLUDED_AGE,
    publication_policy,
    ADULT_AGE_CLASSES,
    singable_voices,
    _load_bench_voices,
    _KYUTAI_DIR,
    _KYUTAI_MANIFEST,
    _KYUTAI_NOTE,
    _KYUTAI_EXCLUDED,
    _load_kyutai_voices,
    voice,
)
from zyg_workflows.voice_studio.params import (
    RACKS,
    _PARAMS,
    defaults,
    sanitize,
    is_default,
)
from zyg_workflows.voice_studio.synthesis import (
    _run,
    _resample_chain,
    seed_chain,
    render_chain,
    _apply,
    _last_json_line,
    _gpu_usable,
    _synth_timeout,
    synth,
    synth_batch,
    measure,
)
from zyg_workflows.voice_studio.presets import (
    _NAME_BAD,
    _SLUG_OK,
    _voice_preset_dir,
    _slugify,
    list_presets,
    _next_auto_name,
    save_preset,
    delete_preset,
    set_active,
    active_params,
    engine_kwargs,
)
from zyg_workflows.voice_studio.jobs import (
    _JOBS,
    _LATEST,
    _JOBS_LOCK,
    _RENDER_GATE,
    _JOB_KEEP,
    _RENDER_TTL_S,
    _GATE_WAITERS,
    _WAIT_LOCK,
    _gate_want,
    _yield_to_interactive,
    _job_set,
    _job_log,
    job,
    _prune_jobs,
    _SYNTH_KEYS_COMMON,
    _SYNTH_KEYS_ENGINE,
    _CACHE_KEEP,
    _RESYNTH_KEYS,
    _r,
    _p,
    _synth_key,
    _cache_dir,
    _TAKE_KEEP,
    _CACHE_TTL_S,
    _CACHE_DIRS,
    _TAKE_BUDGET_BYTES,
    _TAKE_LOCK,
    _SWEEP,
    _SWEEP_EVERY_S,
    _take_key,
    _take_dir,
    _take_index_path,
    _take_index,
    take_has,
    take_cached,
    _take_put,
    _sweep_take_budget,
    _cache_get,
    _cache_put,
    _sweep_old_renders,
    start_render,
    _produce_take,
    _finish_take,
    _render_worker,
)
from zyg_workflows.voice_studio.prerender import (
    _preset_text,
    prerender_state,
    start_prerender,
    cancel_job,
    _prerender_worker,
)
from zyg_workflows.voice_studio.bake import (
    _BAKE_STATE,
    _BAKE_BATCH,
    _BAKE_POST_WORKERS,
    _MAINT_FLAG,
    _BAKE_VRAM_FLOOR_GB,
    _bake_blocked,
    _BAKE,
    _BAKE_LOCK,
    bake_lines,
    bake_plan,
    _bake_read,
    _bake_write,
    _bake_log,
    bake_status,
    _LIB_CACHE,
    library_status,
    start_bake,
    stop_bake,
    bake_eta,
    _bake_stopping,
    _bake_wait_turn,
    _bake_tick,
    _bake_one,
    _bake_batch,
    _bake_worker,
    resume_bake_if_interrupted,
)
from zyg_workflows.voice_studio.state import (
    AUDIO_ROOTS,
    _AUDIO_REL_RE,
    resolve_audio,
    audio_rel,
    audition_clips,
    studio_state,
)

# The package's re-export surface: every name the pre-split single file exposed,
# in import order. Declared so the imports above need no file-level suppression.
__all__ = [
    'json',
    'os',
    're',
    'shutil',
    'subprocess',
    'threading',
    'time',
    '_zyg_logging',
    'paths',
    '_seal',
    'exe',
    '_zyg_log',
    'annotations',
    '_HERE',
    '_SEED_DIR',
    'PRESET_ROOT',
    'RENDER_ROOT',
    '_INDEXTTS_DIR',
    '_INDEXTTS_PY',
    '_INDEXTTS_WORKER',
    '_CHATTERBOX_DIR',
    '_CHATTERBOX_PY',
    '_CHATTERBOX_WORKER',
    '_TTS_CORES',
    '_TTS_THREADS',
    'MAX_PREVIEW_CHARS',
    '_SR',
    '_SEED_SR',
    'DEFAULT_LINES',
    'VOICES',
    '_POOL_DIR',
    '_POOL_MANIFEST',
    '_POOL_EDITORIAL',
    '_POOL_CAUTION',
    '_POOL_LINES',
    '_POOL_NOTE',
    '_POOL_MEASURED',
    '_load_pool_voices',
    '_TEEN_DIR',
    '_TEEN_MANIFEST',
    '_BENCH_DIR',
    '_TEEN_LINES',
    '_load_teen_voices',
    'SOURCE_LICENCES',
    'voice_licence',
    '_PUBLISH_EXCLUDED_SOURCES',
    '_PUBLISH_EXCLUDED_AGE',
    'publication_policy',
    'ADULT_AGE_CLASSES',
    'singable_voices',
    '_load_bench_voices',
    '_KYUTAI_DIR',
    '_KYUTAI_MANIFEST',
    '_KYUTAI_NOTE',
    '_KYUTAI_EXCLUDED',
    '_load_kyutai_voices',
    'voice',
    'RACKS',
    '_PARAMS',
    'defaults',
    'sanitize',
    'is_default',
    '_run',
    '_resample_chain',
    'seed_chain',
    'render_chain',
    '_apply',
    '_last_json_line',
    '_gpu_usable',
    '_synth_timeout',
    'synth',
    'synth_batch',
    'measure',
    '_NAME_BAD',
    '_SLUG_OK',
    '_voice_preset_dir',
    '_slugify',
    'list_presets',
    '_next_auto_name',
    'save_preset',
    'delete_preset',
    'set_active',
    'active_params',
    'engine_kwargs',
    '_JOBS',
    '_LATEST',
    '_JOBS_LOCK',
    '_RENDER_GATE',
    '_JOB_KEEP',
    '_RENDER_TTL_S',
    '_GATE_WAITERS',
    '_WAIT_LOCK',
    '_gate_want',
    '_yield_to_interactive',
    '_job_set',
    '_job_log',
    'job',
    '_prune_jobs',
    '_SYNTH_KEYS_COMMON',
    '_SYNTH_KEYS_ENGINE',
    '_CACHE_KEEP',
    '_RESYNTH_KEYS',
    '_r',
    '_p',
    '_synth_key',
    '_cache_dir',
    '_TAKE_KEEP',
    '_CACHE_TTL_S',
    '_CACHE_DIRS',
    '_TAKE_BUDGET_BYTES',
    '_TAKE_LOCK',
    '_SWEEP',
    '_SWEEP_EVERY_S',
    '_take_key',
    '_take_dir',
    '_take_index_path',
    '_take_index',
    'take_has',
    'take_cached',
    '_take_put',
    '_sweep_take_budget',
    '_cache_get',
    '_cache_put',
    '_sweep_old_renders',
    'start_render',
    '_produce_take',
    '_finish_take',
    '_render_worker',
    '_preset_text',
    'prerender_state',
    'start_prerender',
    'cancel_job',
    '_prerender_worker',
    '_BAKE_STATE',
    '_BAKE_BATCH',
    '_BAKE_POST_WORKERS',
    '_MAINT_FLAG',
    '_BAKE_VRAM_FLOOR_GB',
    '_bake_blocked',
    '_BAKE',
    '_BAKE_LOCK',
    'bake_lines',
    'bake_plan',
    '_bake_read',
    '_bake_write',
    '_bake_log',
    'bake_status',
    '_LIB_CACHE',
    'library_status',
    'start_bake',
    'stop_bake',
    'bake_eta',
    '_bake_stopping',
    '_bake_wait_turn',
    '_bake_tick',
    '_bake_one',
    '_bake_batch',
    '_bake_worker',
    'resume_bake_if_interrupted',
    'AUDIO_ROOTS',
    '_AUDIO_REL_RE',
    'resolve_audio',
    'audio_rel',
    'audition_clips',
    'studio_state',
]
