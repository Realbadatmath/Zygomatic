# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402,F401

"""
test_char_gen_smoke_fast.py — Fast Character Generation Smoke Test
===================================================================

Exercises the full character-generation stack in ~30 seconds by:
  • Blender rendered at 64 px (vs 768 px production) → ~5 s for all ~56 angles
  • Monkey-patching blender_character_service._try_blender() so the API
    flow reuses those pre-rendered images without re-running Blender
  • kick_lora=False — skips SimpleTuner training entirely

What it proves (identical guarantees to the full smoke test):
  ✅ Blender renders ~56 visible images (14 angles × 3 lights + wide + portrait + face)
       → 42 full-body (warm/neutral/cool) + 4 wide + 4 portrait + 6 face close-ups
  ✅ Caption .txt files written beside each image
  ✅ generate-character API returns 200 + char_id
  ✅ _char_gen_jobs entry tracked with correct stage progression
  ✅ GPU power limit applied at generation start
  ✅ Live-tail debug_events emitted (≥ 1 event)
  ✅ Manifest stores name + genre fields
  ✅ Manifest stores facial_hair + muscle_mass fields
  ✅ list-chars API includes genre field
  ✅ zero_public.html: _stCharParams override fixes wrong-character bug
  ✅ Genre selector (st-char-genre) present in frontend
  ✅ Facial hair picker (st-facial-hair) + muscle mass slider (st-muscle-mass) present
  ✅ crewai_web_gui.py extracts facial_hair + muscle_mass from API params
  ✅ stGenderChange() shows/hides facial hair section; facial hair modal HTML present
  ✅ stMuscleMassChange() SVG preview function present
  ✅ generate_character.py: bald/1mm-shave/short-afro sets + facial hair geometry + muscle scaling
  ✅ Character voice: seed-pool cloning pick, IndexTTS-2/Chatterbox chain, voice_mode param
  ✅ zero_public.html: narrator_voice + character_voice in submit payload
  ✅ zero_public_server.py: character_voice extracted and forwarded
  ✅ crewai_web_gui.py: character_voice param wired through pipeline
  ✅ /api/kanban/status returns template='character_creation' while running
  ✅ char-image PNG route serves a real image (HTTP 200, > 0 bytes)
  ✅ VRAM returns to baseline after completion (< 1.5 GB delta)
  ✅ Quality params: LoRA steps=200, rank=128, Blender res=768

Smoke vs production:
  Blender resolution : 64 px          (production: 768 px)
  LoRA training      : skipped        (production: 200 steps, ~10 min)
  Total runtime      : ~30 seconds    (production: 30–50 min)

Usage:
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  python3 scripts/test_char_gen_smoke_fast.py
"""

import sys
import os
import time
import subprocess
import threading
import json
from datetime import datetime
from pathlib import Path
import urllib.request as _ur
import uuid as _uuid
import logging as _zyg_logging

from zyg_workflows import paths

from . import steps_1_to_7b as _steps_1_to_7b
from . import steps_7c_to_results as _steps_7c_to_results

#: Every name the pre-split module bound at module level. The proof body
#: binds many of them inside ``if``/``for``/``try``, so a hard import would
#: turn a soft "attribute absent" into an ImportError: copy what exists.
_ORIGINAL_NAMES = (
    '_zyg_log',
    'SCRIPT_DIR',
    'CREWS_DIR',
    'BLENDER_BIN',
    'BLENDER_SCRIPT',
    'DATASET_ROOT',
    'SEP',
    'PASS',
    'FAIL',
    'WARN',
    'results',
    't_total',
    '_hdr',
    '_ts',
    '_assert',
    'SMOKE_CHAR_ID',
    'SMOKE_CHAR_DIR',
    't_blender',
    '_proc',
    'blender_elapsed',
    '_pngs',
    '_MIN_EXPECTED_IMAGES',
    '_visible',
    '_invisible_names',
    'np',
    '_PIL',
    '_p',
    '_img',
    '_arr',
    '_manifest_path',
    '_rendered_images',
    '_mf',
    '_manifest',
    '_bcs_ok',
    '_bcs',
    '_txts_before',
    '_caption_ok',
    '_svc',
    '_trigger',
    '_params',
    '_txts',
    '_caption_content_ok',
    '_sample_caption',
    '_trigger_check',
    '_orig_try_blender',
    '_fast_try_blender',
    't_imp',
    '_gui',
    '_MockFluxPipeline',
    '_mock_flux',
    '_lts_q',
    '_quick_steps',
    '_inspect_q',
    '_trainer_src',
    '_rank_ok',
    '_bcs_file_path',
    '_bcs_text',
    '_res_ok',
    '_wm',
    '_total_gb',
    '_vram_timeline',
    '_t0_vram',
    'torch',
    '_fi',
    '_vram_done',
    '_vram_monitor',
    '_max_w',
    'SMOKE_PARAMS',
    't_api',
    '_tc',
    '_s',
    '_resp',
    '_rdata',
    '_api_ok',
    '_MAX_WAIT',
    '_t_wait',
    '_final_stage',
    '_cj',
    '_st',
    '_sg',
    '_ds_dir2',
    '_missing_preview',
    '_base',
    '_t',
    '_ds_png_count',
    '_bible_path',
    '_bible_ok',
    '_events',
    '_ev',
    '_power_event',
    '_manifest_after',
    '_manifest_path_after',
    '_mf2',
    '_lc_genre',
    '_lcc',
    '_lcs',
    '_lcr',
    '_lcd',
    '_lc_chars',
    '_lc_entry',
    '_genre_in_code',
    '_html_path',
    '_html_text',
    '_override_fix',
    '_genre_selector',
    '_facial_hair_ui',
    '_muscle_mass_ui',
    '_facial_hair_be',
    '_muscle_mass_be',
    '_genderchange_fh',
    '_facial_modal_html',
    '_muscle_preview_js',
    '_gen_script',
    '_bald_in_script',
    '_shaved_in_script',
    '_safro_in_script',
    '_facial_blender',
    '_muscle_blender',
    '_gui_text',
    '_tts_text',
    '_seed_pick_present',
    '_engine_chain',
    '_voice_mode_param',
    '_voice_mode_tts',
    '_rgb_mode_ok',
    '_no_transparent',
    '_eevee_ok',
    '_cam_dist_ok',
    '_grey_bg_ok',
    '_voice_override_ok',
    '_narrator_voice_auto',
    '_wpm_ok',
    '_word_expansion_ok',
    '_haiku_retry_ok',
    '_haiku_sonnet_fallback',
    '_narrator_voice_ui',
    '_narrator_payload',
    '_character_voice_payload',
    '_server_char_voice',
    '_gui_char_voice',
    '_kanban_tmpl',
    '_kanban_events',
    '_kc',
    '_ks',
    '_kr',
    '_kd',
    '_was_char_active',
    '_img_url',
    '_img_ok',
    '_img_bytes',
    '_img_status',
    '_req',
    '_t2',
    '_fi3',
    '_vram_delta',
    'total_elapsed',
    'all_pass',
    'status',
    'title',
    'detail',
    '_peak',
    'n_fail',
)

for _n in _ORIGINAL_NAMES:
    for _m in (_steps_1_to_7b, _steps_7c_to_results):
        if hasattr(_m, _n):
            globals()[_n] = getattr(_m, _n)
