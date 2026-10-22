# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.py — scripted multi-VOICE dialogue scenes.

Fills the gap the episode pipeline does not cover: pipeline_storyteller renders
a whole episode with ONE effective TTS voice (character_voice OR narrator_voice
— see _effective_tts_voice), so two characters cannot speak to each other. This
service builds a USER-AUTHORED scene from the same building blocks the episodes
use:

  stills   — solo:      comfy_generation_service.generate_still + the char's
                        bible package (arcane restyle hook runs post-save)
             multichar: arcane_multichar.generate_multichar_still (2-3 LoRA
                        characters, regional plate → arcane → per-face identity)
             scenery:   pipeline_environments.generate_scenery_2d(arcane=True)
  voices   — per-character Chatterbox refs (Abel: the frozen calibrated seed in
             abel_voice.ABEL_SEED_WAV; others: data/assets/voice_seeds/pool/*)
  sfx/bed  — the CC0 sfx library (data/asset_libraries/sfx) + audio_mix
             prep_bed/duck_mix/loudnorm_two_pass (-14 LUFS master)
  effects  — Ken Burns pan/zoom, candle flicker, pipeline_effects particle
             overlays (dust/embers/...), vignette, grain, warm grade, fades,
             black title cards.

A scene is a SPEC dict (see SECOND_LEDGER_INTRO at the bottom for the shape).
Entry point: build_scene(spec, out_dir=None) → dict of output paths.
Deterministic: fixed seeds throughout; no wall-clock in outputs.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import math
import os
import shutil
import subprocess
import time
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from zyg_workflows import paths
from zyg_workflows.bin import exe

from zyg_workflows.storyteller_scene_service import constants as _constants

from zyg_workflows.storyteller_scene_service.constants import (
    _zyg_log,
    _CREWS,
    _ROOT_ENV,
    _OUT_ROOT,
    _SFX_DIR,
    _VOCAL_DIR,
    _FOLEY_DIR,
    _MUSIC_DIR,
    _MERGED_DIR,
    _INSTR_DIR,
    _AUDIO_DIRS,
    _POOL_DIR,
    _FONT_PATH,
    _SR,
    _FPS,
    _HIRES_MIN,
    _ESRGAN_WEIGHTS,
    _log_noop,
)
from zyg_workflows.storyteller_scene_service.voice import (
    _training_ok,
    _resolve_voice_ref,
    _probe_sr,
    _pitch_shift,
    _probe_dur,
    _PACE_CLAMP,
    _pace_target,
    _time_stretch,
    _gain_limit,
    _level_to,
    _SHIFTER_REV,
    _PACER_REV,
    _tune_key,
    _take_key,
    _synth_line,
)
from zyg_workflows.storyteller_scene_service.audio import (
    _read_mono48k,
    _audio_asset,
    _audio_dur,
    _sfx_cut,
    _speech_islands,
    _ASR_PY,
    _transcribe,
    _verify_line_text,
    _pick_island,
)
from zyg_workflows.storyteller_scene_service.music import (
    _music_track,
    _music_segment,
)
from zyg_workflows.storyteller_scene_service.frame import (
    _zoom_frame,
    _zoom_box,
    _compose_overlays,
    _kb_zoom_at,
    _kb_keys_at,
    _kb_focus_at,
    _grade,
    _smoothstep,
    _route_context,
    _route_advance,
)
from zyg_workflows.storyteller_scene_service.fire import (
    _smoke_box,
    _draw_smoke,
    _flicker_factor,
    _flame_at,
    _flame_bend,
    _flame_apply,
)
from zyg_workflows.storyteller_scene_service.bird_wing import (
    _lerp_table,
    _bez,
    _catmull,
    _BIRD_TABLES,
    _bird_tables,
    _table_lookup,
    _bird_wing,
    _bird_wing_scripted,
)
from zyg_workflows.storyteller_scene_service.bird_flight import (
    _bird_pose,
    _bird_cam,
    _bird_world,
    _catmull3,
    _BIRD_ARC3,
    _BIRD_BANK3,
    _bird_bank_table,
    _BIRD_YAW3,
    _bird_yaw_table,
    _bird_arc3,
    _bird_fly3d,
    _closed_spline,
    _bird_wing_polys,
    _bird_box,
)
from zyg_workflows.storyteller_scene_service.bird_sprite import (
    _CANARY,
    _BIRD_SPRITES,
    _bird_sprite_set,
    _bird_sprite_set_at,
    _bird_phase,
    _bird_phase_at,
    _bird_wing_tile,
    _bird_view_blend,
    _draw_bird_sprite,
    _draw_bird,
)
from zyg_workflows.storyteller_scene_service.water import (
    _WATER_MASKS,
    _water_mask,
    _WATER_TRAINS,
    _water_field,
    _water_apply,
    _REVEAL_GRIDS,
    _reveal_light,
    _reveal_at,
    _title_card,
)
from zyg_workflows.storyteller_scene_service.stills import (
    _qwen_scene_edit,
    _prop_edit_region,
    _esrgan_resize,
    shot_by_id_spec,
    _base_scale_for,
    _hires_path,
    _env_overrides,
    _canon_lock,
    _render_shot_still,
)
from zyg_workflows.storyteller_scene_service.subtitles import (
    _SUB_CPL,
    _SUB_MIN_S,
    _SUB_WEAK_HEADS,
    _NUM_WORD,
    _NUM_SCALE,
    _sub_digits,
    _sub_wrap,
    _sub_split,
    _srt_t,
    _write_srt,
    _srt_to_vtt,
    _mp4_boxes,
    _mp4_find,
    _mp4_disable_subtitle_track,
    _mux_subs,
)
from zyg_workflows.storyteller_scene_service.scene import (
    _tail_z_at_black,
    build_scene,
)
from zyg_workflows.storyteller_scene_service.second_ledger import (
    ABEL,
    CORNELIS,
    SECOND_LEDGER_INTRO,
)

# The re-export surface, in the import order above: the pre-split
# storyteller_scene_service.py bound all of these at module level, and both the
# section modules and the callers reach them through this package.
__all__ = [
    'json',
    '_zyg_logging',
    'math',
    'os',
    'shutil',
    'subprocess',
    'time',
    'zlib',
    'np',
    'Image',
    'ImageDraw',
    'ImageFilter',
    'ImageFont',
    'ImageOps',
    'paths',
    'exe',
    '_zyg_log',
    '_CREWS',
    '_ROOT_ENV',
    '_OUT_ROOT',
    '_SFX_DIR',
    '_VOCAL_DIR',
    '_FOLEY_DIR',
    '_MUSIC_DIR',
    '_MERGED_DIR',
    '_INSTR_DIR',
    '_AUDIO_DIRS',
    '_POOL_DIR',
    '_FONT_PATH',
    '_SR',
    '_FPS',
    '_HIRES_MIN',
    '_ESRGAN_WEIGHTS',
    '_log_noop',
    '_training_ok',
    '_resolve_voice_ref',
    '_probe_sr',
    '_pitch_shift',
    '_probe_dur',
    '_PACE_CLAMP',
    '_pace_target',
    '_time_stretch',
    '_gain_limit',
    '_level_to',
    '_SHIFTER_REV',
    '_PACER_REV',
    '_tune_key',
    '_take_key',
    '_synth_line',
    '_read_mono48k',
    '_audio_asset',
    '_audio_dur',
    '_sfx_cut',
    '_speech_islands',
    '_ASR_PY',
    '_transcribe',
    '_verify_line_text',
    '_pick_island',
    '_music_track',
    '_music_segment',
    '_zoom_frame',
    '_zoom_box',
    '_compose_overlays',
    '_kb_zoom_at',
    '_kb_keys_at',
    '_kb_focus_at',
    '_grade',
    '_smoothstep',
    '_route_context',
    '_route_advance',
    '_smoke_box',
    '_draw_smoke',
    '_flicker_factor',
    '_flame_at',
    '_flame_bend',
    '_flame_apply',
    '_lerp_table',
    '_bez',
    '_catmull',
    '_BIRD_TABLES',
    '_bird_tables',
    '_table_lookup',
    '_bird_wing',
    '_bird_wing_scripted',
    '_bird_pose',
    '_bird_cam',
    '_bird_world',
    '_catmull3',
    '_BIRD_ARC3',
    '_BIRD_BANK3',
    '_bird_bank_table',
    '_BIRD_YAW3',
    '_bird_yaw_table',
    '_bird_arc3',
    '_bird_fly3d',
    '_closed_spline',
    '_bird_wing_polys',
    '_bird_box',
    '_CANARY',
    '_BIRD_SPRITES',
    '_bird_sprite_set',
    '_bird_sprite_set_at',
    '_bird_phase',
    '_bird_phase_at',
    '_bird_wing_tile',
    '_bird_view_blend',
    '_draw_bird_sprite',
    '_draw_bird',
    '_WATER_MASKS',
    '_water_mask',
    '_WATER_TRAINS',
    '_water_field',
    '_water_apply',
    '_REVEAL_GRIDS',
    '_reveal_light',
    '_reveal_at',
    '_title_card',
    '_qwen_scene_edit',
    '_prop_edit_region',
    '_esrgan_resize',
    'shot_by_id_spec',
    '_base_scale_for',
    '_hires_path',
    '_env_overrides',
    '_canon_lock',
    '_render_shot_still',
    '_SUB_CPL',
    '_SUB_MIN_S',
    '_SUB_WEAK_HEADS',
    '_NUM_WORD',
    '_NUM_SCALE',
    '_sub_digits',
    '_sub_wrap',
    '_sub_split',
    '_srt_t',
    '_write_srt',
    '_srt_to_vtt',
    '_mp4_boxes',
    '_mp4_find',
    '_mp4_disable_subtitle_track',
    '_mux_subs',
    '_tail_z_at_black',
    'build_scene',
    'ABEL',
    'CORNELIS',
    'SECOND_LEDGER_INTRO',
]

# dotenv is optional — constants.py guards its import, so mirror whichever way it went.
if hasattr(_constants, '_load_dotenv'):
    _load_dotenv = _constants._load_dotenv
