# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401, E402  # this module IS the re-export namespace of the pre-split kids_series_common.py.

"""kids_series_common.py — the shared floor under the ten children's series.

Ten runners (``pipeline_kids_<slug>.py``) sit on top of this module.  They own
their fixed tables and their episode structure; everything that touches a
model, a codec or the job registry lives here, once.

THE COST RULE IS THE REASON THIS FILE EXISTS.  An episode must cost under one
cent, and the only honest way to get there is zero paid calls: no anthropic /
openai / azure / google SDK, no ollama, no hosted anything.  Every generator
below is a local weight or a piece of arithmetic:

    pictures   FLUX.2 klein-4B          Apache-2.0   (_comfy_workflows/klein_txt2img.json)
    motion     Wan2.2 I2V A14B          Apache-2.0   (_comfy_workflows/wan22_i2v.json)
    music      MuseScore_General.sf3    MIT          (kids_music_theory + fluidsynth, CPU)
    speech     IndexTTS-2 / Chatterbox  local venvs  (voice_studio.synth)
    one-shots  CC0 instrument samples   cc0          (asset_library_service, 'instruments')
    effects    numpy                    —            (synth_sfx, no library at all)

The 'sfx' and 'foley' libraries are NEVER used here: their CC0 content is
screams, crowds and battle, and the rest ships a 344 Audio EULA that forbids
AI use.  ``write_manifest`` stamps the cost fields the checker reads, and
``scripts/kids_series_check.py`` re-proves them from the outside.

── PUBLIC API (a contract; the ten runners call exactly this) ────────────────

    W, H, FPS                 1280, 720, 24
    KID_STYLE, KID_NEGATIVE   the look, and what the look must never be
    CREWS, OUT_BASE           this directory, and <crews>/output

    discover()                -> {slug: module}   re-globbed on every call
    discover_errors()         -> [{'file', 'error'}]
    start_series(slug, episode=None, pipeline_options=None, test_mode=False)
                              -> job dict {job_id, status, department, out_dir}

    render_still(prompt, out_png, *, w=1280, h=720, seed=0, log_fn=None) -> bool
    render_i2v(png, prompt, out_mp4, *, seconds=4.8, seed=0, test_mode=False,
               log_fn=None) -> bool
    music_bed(out_wav, *, seconds, mood='happy', age_band='toddler', seed=0,
              log_fn=None) -> bool
    say(text, out_wav, *, voice='f01_warm_alto', seed=7, log_fn=None) -> str
    synth_sfx(kind, out_wav, *, seconds=1.0, seed=0, **kw) -> bool
    instrument_shot(family_substr, pitch=None, *, seed=0) -> path or None

    zoompan_clip(png, out_mp4, seconds, *, direction='in', fps=24) -> bool
    frames_to_clip(pattern, out_mp4, fps=24) -> bool
    concat_clips(clips, out_mp4, *, xfade=0.5) -> bool
    mix_audio(tracks, out_wav, total_s) -> bool      tracks: [(wav, start_s, gain_db)]
    mux(video_mp4, audio_wav, out_mp4) -> bool
    probe(path) -> {'duration', 'has_audio', 'w', 'h'}
    write_poster(mp4, jpg) -> bool
    write_manifest(out_dir, manifest) -> path
    run_cli(module) -> int

── SERIES MODULE CONTRACT (what a pipeline_kids_<slug>.py must expose) ───────

    SERIES = {'slug', 'title', 'tagline', 'voice': bool, 'characters': bool,
              'gpu': bool, 'age_band', 'episode_seconds', 'episodes': int,
              'agents': {stage: 'tool label'}}
    STAGES = [...]                    3-8 titles; the board columns are these
    run_episode(out_dir, episode, *, test_mode=False, log_fn=None,
                stage_fn=None, should_abort=None) -> manifest dict
    if __name__ == '__main__':
        sys.exit(kids_series_common.run_cli(sys.modules[__name__]))

``crewai_web_gui`` is NEVER imported at module scope anywhere in this family:
the GUI imports the runners, so a top-level import would be a cycle, and a
standalone ``python pipeline_kids_<slug>.py --test`` has no GUI at all.  The
registry is reached lazily through ``_jobs()``, with a process-local dict as
the standalone fallback — the same shape pipeline_kidsmusic.py uses.
"""

from __future__ import annotations

import argparse
import glob
import importlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import logging as _zyg_logging

from zyg_workflows import paths as _paths
from zyg_workflows import provenance_seal as _seal
from zyg_workflows import runtime as _runtime
from zyg_workflows.bin import exe
from zyg_workflows.runtime import ams_iso as _ams_iso, workflow_jobs as _workflow_jobs

from .constants import (
    _zyg_log,
    CREWS,
    OUT_BASE,
    W,
    H,
    FPS,
    KID_STYLE,
    KID_NEGATIVE,
    FFMPEG,
    FFPROBE,
    _COMFY_ROOT,
    _KLEIN_DISTILLED,
    _KLEIN_BASE,
    VOICE_POOL_DIR,
    VOICE_POOL,
    SFX_KINDS,
    SR,
    _log_noop,
)
from .ffmpeg import (
    _run,
    probe,
    _NORM_VF,
    frames_to_clip,
    zoompan_clip,
    _normalise_clip,
    concat_clips,
    mix_audio,
    mux,
    write_poster,
)
from .audio import (
    _lp_sweep,
    _sfx_wave,
    synth_sfx,
    _INSTRUMENTS,
    _INSTRUMENTS_LOCK,
    _instruments,
    instrument_shot,
    music_bed,
    _VRAM_RELEASED,
    _release_comfy_vram_once,
    say,
)
from .visuals import (
    _attest,
    klein_settings,
    _ltx_hidream,
    render_still,
    _LIGHTNING_HIGH,
    _LIGHTNING_LOW,
    lightning_default,
    render_i2v,
)
from .jobs import (
    _PAID_SDKS,
    write_manifest,
    _DISCOVER_ERRORS,
    discover,
    discover_errors,
    INFLIGHT_DIR,
    _jobs,
    _now_iso,
    _inflight_path,
    _inflight_begin,
    _inflight_beat,
    _inflight_end,
    _inflight_ticker,
    _WARN_WORDS,
    _log_for,
    _set_stage,
    _mk_job,
    _finish,
    start_series,
    run_cli,
)
