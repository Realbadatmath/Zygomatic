# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_service.py — Background music + foley SFX for Zygomatic video pipeline.

Manages downloading, caching, and mixing of royalty-free audio assets.

Foley SFX pipeline (priority order per scene):
  1. [DISABLED 2026-08-09] generative foley — AudioGen removed (CC-BY-NC
     weights); slot reserved for a licence-clean V2A engine (Foley-Omni, MIT)
  2. Freesound API — 530k+ CC recordings searched by keyword (needs API key)
  3. soundbible.com hardcoded catalog — CC0 fallback (IDs verified at build time)

Background music (priority order):
  1. ACE-Step 1.5 (local AI, MIT weights) — replaced CC-BY-NC MusicGen 2026-08-09
  2. yt-dlp from known royalty-free YouTube sources
  3. soundbible ambient loops as last-resort fallback

Main API
--------
  get_music_for_topic(topic, emotion, out_dir, duration_s)  → local path or None
  get_foley_for_scene(description)                          → [(path, volume), ...]
  mix_bgm_into_video(video_path, music_path, out_path, music_vol=0.12)  → bool
  mix_foley_into_audio(tts_path, foley_list, out_path, tts_dur)         → bool
"""

# ruff: noqa: F401  this __init__ is a pure re-export surface: it must bind every
# name the pre-split module defined, used here or not.

# The submodules, imported in the original section order so module-level side
# effects (the sys.path bootstrap, the makedirs, the catalog literals) run in
# exactly the pre-split sequence.
from zyg_workflows.audio_service import (  # noqa: E402
    catalogs,
    downloads,
    mixing,
)

from zyg_workflows.audio_service.catalogs import (
    annotations,
    os,
    re,
    json,
    subprocess,
    logging,
    urllib,
    _zyg_logging,
    paths,
    exe,
    _zyg_log,
    _log,
    _CREWS_DIR,
    _ASSETS_DIR,
    MUSIC_DIR,
    FOLEY_DIR,
    _YTDLP_LOCAL,
    _YTDLP,
    _MUSIC_CATALOG,
    _FOLEY_CATALOG,
    _AUDIOGEN_PROMPTS,
    _SCENE_FOLEY_KEYWORDS,
    _TOPIC_MOOD_MAP,
    _EMOTION_MOOD_MAP,
    _MUSICGEN_PROMPTS,
)
from zyg_workflows.audio_service.downloads import (
    _download_soundbible,
    _download_music_ytdlp,
    _download_music_soundbible_fallback,
    _FOLEY_STOP_WORDS,
    _extract_foley_query,
    _freesound_search,
)
from zyg_workflows.audio_service.mixing import (
    _pick_mood,
    _VALID_MOODS,
    get_music_for_topic,
    get_foley_for_scene,
    mix_foley_into_audio,
    mix_foley_into_video,
    mix_bgm_into_video,
)
