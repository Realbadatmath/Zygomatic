# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_music_service.py — renders, gates and deliverables for the Children's
Music workflow.

Two audio legs from ONE symbolic plan (kids_music_theory):

  A. SCORE RENDER  — the composed arrangement played by libfluidsynth through
     MuseScore_General.sf3 (MIT).  Deterministic, CPU-only, needs no GPU and no
     model: the notes you hear are exactly the notes that were scored.  This leg
     always runs, so the workflow delivers usable audio even when ComfyUI is
     busy with a video render.

  B. ACE-STEP VARIATION — ACE-Step 1.5 given the SAME bpm, time signature, key
     and lyrics as the plan.  It is NOT the same tune.  No note data reaches
     ACE-Step — only tags, lyrics, seed, bpm, duration, time signature and a
     pitch-class keyscale — and a chroma test against the plan confirms it:
     similarity 0.279 versus a 0.252 cross-song null (z = +0.65, i.e. nothing),
     while the same test on the score render scores 0.827 (z = +2.84) and
     recovers zero lag in 6 of 6.  The method has power; this is a real negative.
     So the two legs share a key, a tempo and a lyric, and are different tunes.
     `delivery.melody_followed` records that, and the tab must not draw the
     composed piano roll above leg B's player.

Leg B is then MEASURED against what it CAN be held to (tempo, key, loudness,
duration, a CLAP semantic check, and — when it is sung — the age and sex of the
voice that actually came out).  A generative model is free to ignore the
conditioning it was given; this is how we find out whether it did.

WHO SINGS: the songs are FOR children and are sung BY adults.  The caption is
ACE-Step's only steering lever and it was measured, not assumed — see
kids_music_theory.SINGERS.  Every sung render is verified by gate_singer_age,
because within-caption seed spread is ~100 Hz and casting without a gate is a
wish rather than a control.

Nothing here mutates an existing pipeline: it uses ace_step_service's checkpoint
through its own workflow template, calls audio_mix/audio_qc read-only, and
writes only under its own output directory.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time

from zyg_workflows import kids_llm
from zyg_workflows import paths
from zyg_workflows import kids_music_theory as T
from zyg_workflows import provenance_seal as _seal
import logging as _zyg_logging
from zyg_workflows.bin import exe
import sys as _sys
import types as _types

# The old module computed HERE from its own __file__. This package sits one
# directory deeper, so the same expression would move every path anchored on it
# (OUT_ROOT, CINEMATIC_OUT_ROOT, SOUNDFONT, _AGENTS_PY, _DEMUCS_TOOL) into the
# package. base.py therefore strips the extra level; nothing else about HERE,
# and no value derived from it, changed.
from zyg_workflows.kids_music_service.base import (
    _zyg_log,
    HERE,
    SOUNDFONT,
    OUT_ROOT,
    CINEMATIC_OUT_ROOT,
    TICKS_PER_BEAT,
    MIX_MARGIN_MIN_DB,
    SR,
    ACE_CHECKPOINT,
    ACE_WORKFLOW,
    ACE_WORKFLOW_NEG,
    ACE_NEG_NODE,
    ACE_WORKFLOW_A2A,
    A2A_DENOISE,
    ACE_STEPS,
    A2A_DENOISE_LADDER,
    CLEAR_SHARE_MIN,
    ACE_WORKFLOW_COVER,
    ALLOWED_SOUNDFONTS,
    ACE_LICENCE,
    IMAGE_LICENCE,
    _licence_note,
    _log_noop,
    _ff,
)
from zyg_workflows.kids_music_service.midi import (
    write_midi,
)
from zyg_workflows.kids_music_service.soundfont import (
    render_soundfont,
    lowered_lead_wav,
)
from zyg_workflows.kids_music_service.ace import (
    ace_available,
    _family_of,
    ace_prompt,
    ace_negative,
    _attest,
    ace_render,
    _stage_comfy_audio,
    _negative_node_available,
    _submit_abort_kw,
)
from zyg_workflows.kids_music_service.repaint import (
    ACE_WORKFLOW_REPAINT,
    REPAINT_MASK_NODE,
    REPAINT_DENOISE,
    _ACE_LATENT_HZ,
    _comfy_has_node,
    ace_repaint,
    _decode_stereo,
    splice_window,
    repair_take,
)
from zyg_workflows.kids_music_service.lyrics import (
    _OLLAMA,
    _LYRIC_MODEL,
    _BANNED,
    _fallback_lyrics,
    _fallback_facts_lyrics,
    _DANGLING,
    _STOPWORDS,
    _theme_phrase,
    _LYRIC_SYSTEM,
    _LYRIC_BANNED_WORDS,
    _section_map,
    _lyric_prompt_opus,
    write_lyrics,
    lyrics_block,
)
from zyg_workflows.kids_music_service.measure import (
    _KK_MAJOR,
    _KK_MINOR,
    _corr,
    detect_key,
    detect_tempo,
    _peak_dbfs,
    _duration,
    _TAIL_FLOOR_DB,
    DEAD_TAIL_WARN_S,
    music_end,
    trim_tail,
    gate_audio,
)
from zyg_workflows.kids_music_service.melody import (
    _better_take,
    chroma_follow,
    _null_plans,
)
from zyg_workflows.kids_music_service.singer import (
    _AGENTS_PY,
    _DEMUCS_TOOL,
    VOCAL_PRESENT_DB,
    VTL_TRUSTWORTHY_MAX_F0,
    FEMALE_HIGH_REGISTER_F0,
    separate_vocal,
    gate_singer_age,
    _gate_singer_age,
)
from zyg_workflows.kids_music_service.roll import (
    write_roll_svg,
)
from zyg_workflows.kids_music_service.mixdown import (
    _mp3,
    mix_balance,
    percussion_wav,
    prelevel,
    soundfont_info,
    _merge_voice_licences,
    _write_state,
)
from zyg_workflows.kids_music_service.master import (
    master_audio,
    STEM_FILES,
    save_stems,
    remix_stems,
    remux_video,
    convert_voice,
    _update_voice_report,
    remix_job,
)
from zyg_workflows.kids_music_service.run_ace import (
    stage_ace,
)
from zyg_workflows.kids_music_service.run_deliver import (
    stage_deliver,
)
from zyg_workflows.kids_music_service.run import (
    run,
)
from zyg_workflows.kids_music_service.cli import (
    _main,
)

__all__ = [
    # The original top import block, kept here and re-exported: this package is the
    # pre-split kids_music_service.py seen from outside, and its namespace is where
    # the siblings and the callers read these names.
    'json',
    'os',
    're',
    'subprocess',
    'time',
    'kids_llm',
    'paths',
    'T',
    '_seal',
    '_zyg_logging',
    'exe',
    '_zyg_log',
    'HERE',
    'SOUNDFONT',
    'OUT_ROOT',
    'CINEMATIC_OUT_ROOT',
    'TICKS_PER_BEAT',
    'MIX_MARGIN_MIN_DB',
    'SR',
    'ACE_CHECKPOINT',
    'ACE_WORKFLOW',
    'ACE_WORKFLOW_NEG',
    'ACE_NEG_NODE',
    'ACE_WORKFLOW_A2A',
    'A2A_DENOISE',
    'ACE_STEPS',
    'A2A_DENOISE_LADDER',
    'CLEAR_SHARE_MIN',
    'ACE_WORKFLOW_COVER',
    'ALLOWED_SOUNDFONTS',
    'ACE_LICENCE',
    'IMAGE_LICENCE',
    '_licence_note',
    '_log_noop',
    '_ff',
    'write_midi',
    'render_soundfont',
    'lowered_lead_wav',
    'ace_available',
    '_family_of',
    'ace_prompt',
    'ace_negative',
    '_attest',
    'ace_render',
    '_stage_comfy_audio',
    '_negative_node_available',
    '_submit_abort_kw',
    'ACE_WORKFLOW_REPAINT',
    'REPAINT_MASK_NODE',
    'REPAINT_DENOISE',
    '_ACE_LATENT_HZ',
    '_comfy_has_node',
    'ace_repaint',
    '_decode_stereo',
    'splice_window',
    'repair_take',
    '_OLLAMA',
    '_LYRIC_MODEL',
    '_BANNED',
    '_fallback_lyrics',
    '_fallback_facts_lyrics',
    '_DANGLING',
    '_STOPWORDS',
    '_theme_phrase',
    '_LYRIC_SYSTEM',
    '_LYRIC_BANNED_WORDS',
    '_section_map',
    '_lyric_prompt_opus',
    'write_lyrics',
    'lyrics_block',
    '_KK_MAJOR',
    '_KK_MINOR',
    '_corr',
    'detect_key',
    'detect_tempo',
    '_peak_dbfs',
    '_duration',
    '_TAIL_FLOOR_DB',
    'DEAD_TAIL_WARN_S',
    'music_end',
    'trim_tail',
    'gate_audio',
    '_better_take',
    'chroma_follow',
    '_null_plans',
    '_AGENTS_PY',
    '_DEMUCS_TOOL',
    'VOCAL_PRESENT_DB',
    'VTL_TRUSTWORTHY_MAX_F0',
    'FEMALE_HIGH_REGISTER_F0',
    'separate_vocal',
    'gate_singer_age',
    '_gate_singer_age',
    'write_roll_svg',
    '_mp3',
    'mix_balance',
    'percussion_wav',
    'prelevel',
    'soundfont_info',
    '_merge_voice_licences',
    '_write_state',
    'master_audio',
    'STEM_FILES',
    'save_stems',
    'remix_stems',
    'remux_video',
    'convert_voice',
    '_update_voice_report',
    'remix_job',
    'stage_ace',
    'stage_deliver',
    'run',
    '_main',
]

# WHY THIS CLASS EXISTS. kids_music_service used to be one module, so a caller
# that reassigned one of its names — every test that stubs out render_soundfont,
# ace_render, gate_singer_age, write_lyrics, master_audio, chroma_follow,
# repair_take or remux_video — changed the name run() itself would look up at
# call time. Split across modules, each submodule holds its own binding, and a
# patch on the package would be invisible to the code that runs. This forwards
# an attribute assignment on the package to every submodule that holds the same
# name, which is exactly what one shared namespace did.
_SUBMODULES = tuple(
    _sys.modules[__name__ + '.' + _n]
    for _n in (
        'base',
        'midi',
        'soundfont',
        'ace',
        'repaint',
        'lyrics',
        'measure',
        'melody',
        'singer',
        'roll',
        'mixdown',
        'master',
        'run_ace',
        'run_deliver',
        'run',
        'cli',
    )
)


class _SharedNamespace(_types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _m in _SUBMODULES:
            if name in _m.__dict__:
                _m.__dict__[name] = value


_sys.modules[__name__].__class__ = _SharedNamespace
