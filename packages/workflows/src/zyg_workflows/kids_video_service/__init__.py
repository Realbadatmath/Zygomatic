# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


# ruff: noqa: E402, F401

"""kids_video_service.py — the illustrated-video leg of the Children's Music workflow.

Turns a delivered children's song into a picture video: **one picture per motion
clip**, cut on the bar, joined with smooth transitions, and never photorealistic.

WHAT THIS MODULE CLAIMS, AND HOW IT PROVES IT
---------------------------------------------
Four properties were asked for.  Each one is a measurement in the storyboard
manifest, not an assertion in a comment:

1. **One picture per clip, and the clip length sets the rate.**  Every picture
   becomes an LTX-2.5 image-to-video clip, so a picture is worth exactly as many
   seconds of video as its clip runs: ``CLIP_S`` (5 s by default) is the only
   knob, and a 60 s song needs about ``60 / CLIP_S`` pictures — twelve, not
   fifty.  The slot ceiling is derived from it, so no slot can outrun the clip
   that has to cover it, and the delivered rate is measured anyway as the WORST
   rolling five-second window rather than the average.  An average hides a
   ten-second still; a rolling minimum cannot.
2. **Cut on the bar.**  Slot boundaries are laid out on the song's own beat grid
   (measured from the delivered audio with librosa, with the composed plan's bpm
   as the prior; the symbolic grid is the fallback when the measurement is not
   trustworthy), and a slot is always a whole number of bars (or a half, or a
   quarter) — see ``_unit_ladder``.  Reported as the median distance from each cut
   to its nearest measured beat, in milliseconds.
3. **Smooth transitions, faster where the music pushes.**  Every join is an
   ffmpeg ``xfade`` — there is no hard cut in the vocabulary at all.  Pace is
   driven by measured RMS energy per section plus the composed form: a chorus
   steps one rung down the ladder when that rung halves the base, and otherwise
   keeps the rate and reads through its faster transitions (``_double_unit``) —
   a quarter off a picture is not a pace change, it is a third more renders.
   A high-energy bar can also become a BURST —
   one picture per beat, where the counting motifs land ("boem ba boem" → one
   block, two blocks, three blocks) — but only at a clip length short enough for
   a flurry to read as one, which a 5 s clip is not (``_burst_unit``).
4. **Cartoon, never photorealistic; happy, never gloomy.**  Measured per image
   with CLIP as a contrast between competing captions, not as a bare similarity.
   Calibrated against a null: the five photoreal stills already on this box score
   0.0007–0.34 on the cartoon contrast, while klein cartoon renders score
   0.925–0.986.  The 0.75 threshold sits in the empty space between those two
   distributions.

WHERE THE PICTURES COME FROM
----------------------------
The song is the first source: each lyric line becomes one visual idea.  A song
rarely has enough words to fill a 30-picture video, and the deficit is filled
from a **motif deck** — counting runs, shape and colour parades, a toy box, an
animal parade, weather, dancing children, a seed growing into a flower, the
song's own hero travelling.  The counting motifs are deliberately placed on the
burst runs so the count advances with the beat.  Motifs are generated in code,
not by the model, so they are exactly reproducible and cannot fail.

Generation is **klein** (FLUX.2 [klein] 4B, Apache-2.0, ``cleared`` in the
licence registry) — not DynaVision XL and not Juggernaut, both of which classify
UNKNOWN and this channel is monetised.  When ComfyUI is down every slot still
gets a picture: ``_draw_card`` draws a flat cartoon card with PIL.  That mirrors
the audio side's design claim — the score render ships when the GPU is busy — so
a video always exists, and the manifest says how many of its frames were drawn
rather than generated instead of quietly implying they all came from the model.

Output (inside the song's own ``output/kidsmusic/<job>/``):
    video.mp4         the deliverable — pictures + the mastered audio
    poster.jpg        first frame, for the card
    storyboard.json   every slot, its timing, its source, and every measurement
    frames/f###.png   the pictures in the song
    frames/t###.jpg   480 px thumbnails for the inspection tab
    frames/excess/f###_c#.png   healthy candidates that were not used (2026-09-15)
    frames/rejected/f###_c#.jpg JPEG receipts of candidates the defect screen threw out
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import time

from zyg_workflows import kids_llm
from zyg_workflows import paths
from zyg_workflows import kids_music_theory as T
from zyg_workflows import provenance_seal as _seal
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


import sys as _sys
import types as _types

# RELOADING THIS PACKAGE RELOADS ITS SECTIONS.  The rate block below is read
# from the environment at import, and the suite reloads this module to re-read
# it (test_kidsvideo_clip_rate._reload).  ``importlib.reload`` on a package
# re-executes only this file, and the submodules would be served from
# sys.modules unchanged — the constants would not move.  Dropping them first
# makes the reload cascade, so a reload of the package is still a reload of
# every section, exactly as it was when all of this was one file.
for _stale in [_m for _m in _sys.modules if _m.startswith(f'{__name__}.')]:
    del _sys.modules[_stale]

# The sections of the old single file, imported in their original order so
# module-level side effects still run in that order.  Every name the old
# module defined — public and underscore — is re-exported below, so
# ``zyg_workflows.kids_video_service.X`` resolves exactly as it did.
from zyg_workflows.kids_video_service.constants import (
    HERE,
    RENDER_W,
    RENDER_H,
    OUT_W,
    OUT_H,
    FPS,
    CLIP_S_MAX,
    CLIP_S_MIN,
    _clip_s_asked,
    CLIP_S,
    XFADE_MAX_S,
    CLIP_HEADROOM_S,
    WINDOW_S,
    MAX_SLOT_S,
    MIN_SLOT_S,
    ABSORB_S,
    ABSORB_MAX_S,
    TARGET_PER_5S,
    MIN_STARTS_PER_5S,
    _RATE_NOTES,
    _FAST,
    _KLEIN_DISTILLED,
    _KLEIN_BASE,
    MODEL_FAMILY,
    _resolve_fast_unet,
    _FAST_UNET,
    _FAST_ACTIVE,
    STEPS,
    CFG,
    _ETA_PER_IMAGE,
    _SPEED_WARNINGS,
    speed_note,
    fast_unet,
    MAX_IMAGES,
    KB_ZOOM,
    PULSE_AMP,
    PULSE_S,
    CARTOON_MIN,
    JOY_MIN,
    OCR_MIN_AREA,
    _OLLAMA,
    _LLM,
    _log_noop,
)
from zyg_workflows.kids_video_service.motifs import (
    BASE_STYLE,
    MOOD_LOOK,
    NEGATIVE,
    look_for,
    style_for,
    build_prompt,
    _COUNT_WORDS,
    _COUNT_ITEMS,
    _COUNT_COLOURS,
    _COLOUR_RGB,
    _count_phrase,
    _SHAPES,
    _COLOURS,
    _TOYS,
    _ANIMALS,
    _WEATHER,
    _DANCE,
    _GROW,
    _JOURNEY,
    _count_run,
    _m_count_up,
    _m_count_down,
    _m_shapes,
    _HERO_COLOUR_RE,
    _m_colours,
    _m_toys,
    _m_animals,
    _m_weather,
    _m_dance,
    _m_grow,
    _m_journey,
    _m_peekaboo,
    MOTIFS,
    BURST_MOTIFS,
    FILL_MOTIFS,
    STYLE_MOTIF_EXCLUDED,
    motif_pools,
)
from zyg_workflows.kids_video_service.storyboard import (
    beat_grid,
    _duration,
    _snap,
    rms_envelope,
    _energy_between,
    _segments,
    _UNIT_BARS,
    _unit_ladder,
    _double_unit,
    _burst_unit,
    plan_slots,
    clip_plan,
    min_per_window,
    beat_alignment,
)
from zyg_workflows.kids_video_service.ideas import (
    _hero_phrase,
    IDEA_BATCH,
    idea_batch,
    llm_ideas,
    _IDEAS_SYSTEM,
    _ideas_prompt_opus,
    _llm_ideas_once,
    assign_ideas,
)
from zyg_workflows.kids_video_service.cards import (
    _PALETTE,
    _INK,
    _sky,
    _draw_balloon,
    _lighten,
    _draw_block,
    _draw_apple,
    _draw_ball,
    _draw_star,
    _draw_flower,
    _COUNT_DRAW,
    draw_count_card,
    _draw_card,
)
from zyg_workflows.kids_video_service.comfy import (
    _enable_comfy,
    release_ollama,
    release_comfy_vram,
    release_clip,
    _repair_frames,
)
from zyg_workflows.kids_video_service.screen import (
    CANDIDATES,
    SCREEN_ON,
    SCREEN_LLM,
    SCREEN_PX,
    SCREEN_CALIBRATION,
    _SCREEN_PROMPT,
    _PLURAL_RE,
    _NEGATED_RE,
    _COMPOSITION_RE,
    _FACED_OBJECT_RE,
    _PAIRED_PART,
    _PART_QUAL,
    _ONE_OF_PAIR_RE,
    _MISSING_ONE_RE,
    _ONE_MISSING_RE,
    is_one_of_pair_claim,
    _SCREEN_RANK,
    _VLM_FAILS,
    vlm_defects,
    judge,
    judge_description,
    describe_compact,
    screen_frame,
    _reject_thumb,
)
from zyg_workflows.kids_video_service.render import (
    _HiDreamGen,
    render_images,
    _pick_candidates,
    write_thumbs,
)
from zyg_workflows.kids_video_service.gates import (
    _CAPTION_BAIT,
    _NO_TEXT,
    reads_text,
    _CLIP,
    CARTOON_POS,
    CARTOON_NEG,
    JOY_POS,
    JOY_NEG,
    _clip,
    _LETTERS_RE,
    _ROUND_GLYPHS,
    _looks_like_lettering,
    gate_frames,
)
from zyg_workflows.kids_video_service.motion import (
    run_ffmpeg,
    _nvenc_args,
    _x264_args,
    _clip_to_slot,
    _render_motion,
    _LTX_WALL_PER_CLIP_S,
    _MOTION_HINTS,
    _MOTION_DEFAULT,
    motion_prompt,
    motion_clip_for,
    animate_frames,
)
from zyg_workflows.kids_video_service.transitions import (
    _SECTION_WIPES,
    transitions_for,
    _xfade_graph,
)
from zyg_workflows.kids_video_service.assembly import (
    build_video,
    verify_cuts,
)
from zyg_workflows.kids_video_service.run import (
    reassemble,
    run,
)
from zyg_workflows.kids_video_service.cli import (
    _main,
)

__all__ = [
    'HERE',
    'RENDER_W',
    'RENDER_H',
    'OUT_W',
    'OUT_H',
    'FPS',
    'CLIP_S_MAX',
    'CLIP_S_MIN',
    '_clip_s_asked',
    'CLIP_S',
    'XFADE_MAX_S',
    'CLIP_HEADROOM_S',
    'WINDOW_S',
    'MAX_SLOT_S',
    'MIN_SLOT_S',
    'ABSORB_S',
    'ABSORB_MAX_S',
    'TARGET_PER_5S',
    'MIN_STARTS_PER_5S',
    '_RATE_NOTES',
    '_FAST',
    '_KLEIN_DISTILLED',
    '_KLEIN_BASE',
    'MODEL_FAMILY',
    '_resolve_fast_unet',
    '_FAST_UNET',
    '_FAST_ACTIVE',
    'STEPS',
    'CFG',
    '_ETA_PER_IMAGE',
    '_SPEED_WARNINGS',
    'speed_note',
    'fast_unet',
    'MAX_IMAGES',
    'KB_ZOOM',
    'PULSE_AMP',
    'PULSE_S',
    'CARTOON_MIN',
    'JOY_MIN',
    'OCR_MIN_AREA',
    '_OLLAMA',
    '_LLM',
    '_log_noop',
    'BASE_STYLE',
    'MOOD_LOOK',
    'NEGATIVE',
    'look_for',
    'style_for',
    'build_prompt',
    '_COUNT_WORDS',
    '_COUNT_ITEMS',
    '_COUNT_COLOURS',
    '_COLOUR_RGB',
    '_count_phrase',
    '_SHAPES',
    '_COLOURS',
    '_TOYS',
    '_ANIMALS',
    '_WEATHER',
    '_DANCE',
    '_GROW',
    '_JOURNEY',
    '_count_run',
    '_m_count_up',
    '_m_count_down',
    '_m_shapes',
    '_HERO_COLOUR_RE',
    '_m_colours',
    '_m_toys',
    '_m_animals',
    '_m_weather',
    '_m_dance',
    '_m_grow',
    '_m_journey',
    '_m_peekaboo',
    'MOTIFS',
    'BURST_MOTIFS',
    'FILL_MOTIFS',
    'STYLE_MOTIF_EXCLUDED',
    'motif_pools',
    'beat_grid',
    '_duration',
    '_snap',
    'rms_envelope',
    '_energy_between',
    '_segments',
    '_UNIT_BARS',
    '_unit_ladder',
    '_double_unit',
    '_burst_unit',
    'plan_slots',
    'clip_plan',
    'min_per_window',
    'beat_alignment',
    '_hero_phrase',
    'IDEA_BATCH',
    'idea_batch',
    'llm_ideas',
    '_IDEAS_SYSTEM',
    '_ideas_prompt_opus',
    '_llm_ideas_once',
    'assign_ideas',
    '_PALETTE',
    '_INK',
    '_sky',
    '_draw_balloon',
    '_lighten',
    '_draw_block',
    '_draw_apple',
    '_draw_ball',
    '_draw_star',
    '_draw_flower',
    '_COUNT_DRAW',
    'draw_count_card',
    '_draw_card',
    '_enable_comfy',
    'release_ollama',
    'release_comfy_vram',
    'release_clip',
    '_repair_frames',
    'CANDIDATES',
    'SCREEN_ON',
    'SCREEN_LLM',
    'SCREEN_PX',
    'SCREEN_CALIBRATION',
    '_SCREEN_PROMPT',
    '_PLURAL_RE',
    '_NEGATED_RE',
    '_COMPOSITION_RE',
    '_FACED_OBJECT_RE',
    '_PAIRED_PART',
    '_PART_QUAL',
    '_ONE_OF_PAIR_RE',
    '_MISSING_ONE_RE',
    '_ONE_MISSING_RE',
    'is_one_of_pair_claim',
    '_SCREEN_RANK',
    '_VLM_FAILS',
    'vlm_defects',
    'judge',
    'judge_description',
    'describe_compact',
    'screen_frame',
    '_reject_thumb',
    '_HiDreamGen',
    'render_images',
    '_pick_candidates',
    'write_thumbs',
    '_CAPTION_BAIT',
    '_NO_TEXT',
    'reads_text',
    '_CLIP',
    'CARTOON_POS',
    'CARTOON_NEG',
    'JOY_POS',
    'JOY_NEG',
    '_clip',
    '_LETTERS_RE',
    '_ROUND_GLYPHS',
    '_looks_like_lettering',
    'gate_frames',
    'run_ffmpeg',
    '_nvenc_args',
    '_x264_args',
    '_clip_to_slot',
    '_render_motion',
    '_LTX_WALL_PER_CLIP_S',
    '_MOTION_HINTS',
    '_MOTION_DEFAULT',
    'motion_prompt',
    'motion_clip_for',
    'animate_frames',
    '_SECTION_WIPES',
    'transitions_for',
    '_xfade_graph',
    'build_video',
    'verify_cuts',
    'reassemble',
    'run',
    '_main',
]

from zyg_workflows.kids_video_service import (  # the section modules themselves
    constants as _s_constants,
    motifs as _s_motifs,
    storyboard as _s_storyboard,
    ideas as _s_ideas,
    cards as _s_cards,
    comfy as _s_comfy,
    screen as _s_screen,
    render as _s_render,
    gates as _s_gates,
    motion as _s_motion,
    transitions as _s_transitions,
    assembly as _s_assembly,
    run as _s_run,
    cli as _s_cli,
)

_SECTIONS = (
    _s_constants,
    _s_motifs,
    _s_storyboard,
    _s_ideas,
    _s_cards,
    _s_comfy,
    _s_screen,
    _s_render,
    _s_gates,
    _s_motion,
    _s_transitions,
    _s_assembly,
    _s_run,
    _s_cli,
)


class _OneNamespace(_types.ModuleType):
    """The package answers rebinding the way the single file did.

    The old module was one namespace: ``setattr(kids_video_service, name, x)``
    changed what every function in the file saw, and the suite leans on that
    (test_kidsvideo_candidate_pool patches ``screen_frame``, ``vlm_defects``,
    ``CANDIDATES``, ``MODEL_FAMILY`` … on the module and then calls
    ``render_images``).  Split across sections, each section holds its own
    binding, so a setattr on the package alone would be invisible to the code
    that reads the name.  Setting an attribute here therefore also rebinds it
    in every section that holds it — one namespace again, by delegation.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _mod in self.__dict__.get('_SECTIONS') or ():
            if name in _mod.__dict__:
                _mod.__dict__[name] = value

    def __delattr__(self, name):
        super().__delattr__(name)
        for _mod in self.__dict__.get('_SECTIONS') or ():
            _mod.__dict__.pop(name, None)


_sys.modules[__name__].__class__ = _OneNamespace
