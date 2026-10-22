# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remixai.py — the Remix Ai department (2026-08-29).

Studies a popular AI-generated video and produces an ORIGINAL video in the same
format: same visual treatment, same structural shape, same genre of soundtrack —
new images, new script, new title, different track.

  Sweep → Download → analyse (frames / transcript / soundtrack / title)
        → regenerate (script, title, images) → narrate → animate → assemble
        → replace soundtrack → subtitle → deliver

WHAT IS COPIED AND WHAT IS NOT
------------------------------
Copied: the AESTHETIC (a style is not ownable) and the STRUCTURE (a beat shape,
a hook type, a title pattern — formats are not ownable either).
Not copied: the pictures, the sentences, the title, the music. Every one of those
is regenerated or replaced. remixai_analyze enforces the text half structurally —
`regenerate_script()` takes an abstract brief and has no parameter through which
source wording could reach it.

The source video is DELETED as soon as analysis finishes (Stage 5). Nothing this
department delivers contains a frame, a waveform or a sentence of it.

Contract (pipeline_envfx_runner shape):
  * NO top-level import of crewai_web_gui — lazy accessors only.
  * Worker thread name 'remixai-<pid>' is LOAD-BEARING: it is in the
    _workflow_pipeline_worker_alive needles tuple in crewai_web_gui.py.
    Renaming it makes kanban stamp running jobs 'Stale after restart'.
  * State file data/runtime/pipeline_<pid>_state.json carries department='remix_ai'.
  * Stage names must keep the KANBAN_STAGE_MAP_REMIXAI fragments in
    bp_pipeline_api.py — the board joins cards by EXACT title.
"""

from __future__ import annotations

from .core import (
    os,
    random,
    re,
    shutil,
    subprocess,
    threading,
    time,
    traceback,
    uuid,
    RA,
    RD,
    _seal,
    RI,
    runtime,
    exe,
    _zyg_logging,
    _zyg_log,
    _CREWS,
    _RUNTIME,
    _OUT_ROOT,
    _FONT,
    _AUDIO_ARGS,
    DEPARTMENT,
    STAGES,
    _env_f,
    _env_i,
    _jobs,
    _now_iso,
    _marker,
    _marker_update,
    _mk_job,
    _LAST_FLUSH,
    _FLUSH_EVERY_S,
    _log,
    _update_stage,
    _finish,
    _save_state,
    _stopped,
    _Stopped,
    _check_stop,
    disk_ok,
    _tree_gb,
    _run,
    _duration,
)
from .media import (
    output_geometry,
    target_seconds,
    _model_family,
    _gen_still,
    _build_image_prompt,
    _tts_line,
    _ken_burns_segment,
    _concat,
    _srt_ts,
    _NUM_UNITS,
    _NUM_TENS,
    _NUM_SCALES,
    _NUM_ANY,
    _NUM_TOKEN_RE,
    _compose_number_words,
    _subtitle_digits,
    _sub_helpers,
    _write_srt,
    _write_vtt,
    _SUB_STYLE_ABEL,
    _burn_subs,
)
from .pipeline import _run_pipeline
from .stage_helpers import (
    _gpu_holders,
    _free_comfy_vram,
    _flag,
    _slug,
    _asr,
    _delete_source,
    _backfill_images,
    _too_similar,
    _replace_soundtrack,
    _write_description,
)
from .entry import _gpu_busy, start_remix_ai, stop_remix_ai, retention_sweep, _pid_running

# Re-export surface: every name below is imported above and not used in this
# module. Nothing does ``import *`` from here, so __all__ changes no behaviour;
# it declares the inherited namespace public so ruff does not read it as dead.
__all__ = [
    'os',
    'random',
    're',
    'shutil',
    'subprocess',
    'threading',
    'time',
    'traceback',
    'uuid',
    'RA',
    'RD',
    '_seal',
    'RI',
    'runtime',
    'exe',
    '_zyg_logging',
    '_zyg_log',
    '_CREWS',
    '_RUNTIME',
    '_OUT_ROOT',
    '_FONT',
    '_AUDIO_ARGS',
    'DEPARTMENT',
    'STAGES',
    '_env_f',
    '_env_i',
    '_jobs',
    '_now_iso',
    '_marker',
    '_marker_update',
    '_mk_job',
    '_LAST_FLUSH',
    '_FLUSH_EVERY_S',
    '_log',
    '_update_stage',
    '_finish',
    '_save_state',
    '_stopped',
    '_Stopped',
    '_check_stop',
    'disk_ok',
    '_tree_gb',
    '_run',
    '_duration',
    'output_geometry',
    'target_seconds',
    '_model_family',
    '_gen_still',
    '_build_image_prompt',
    '_tts_line',
    '_ken_burns_segment',
    '_concat',
    '_srt_ts',
    '_NUM_UNITS',
    '_NUM_TENS',
    '_NUM_SCALES',
    '_NUM_ANY',
    '_NUM_TOKEN_RE',
    '_compose_number_words',
    '_subtitle_digits',
    '_sub_helpers',
    '_write_srt',
    '_write_vtt',
    '_SUB_STYLE_ABEL',
    '_burn_subs',
    '_run_pipeline',
    '_gpu_holders',
    '_free_comfy_vram',
    '_flag',
    '_slug',
    '_asr',
    '_delete_source',
    '_backfill_images',
    '_too_similar',
    '_replace_soundtrack',
    '_write_description',
    '_gpu_busy',
    'start_remix_ai',
    'stop_remix_ai',
    'retention_sweep',
    '_pid_running',
]
