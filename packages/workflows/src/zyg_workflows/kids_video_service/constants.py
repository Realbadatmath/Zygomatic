# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Geometry, rate and generation speed — every tunable of the picture video.

Moved verbatim out of the old single-file kids_video_service.py (lines 94-344).
"""

from __future__ import annotations

import os
from zyg_workflows import paths
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.kids_video_service')


# zyg_workflows/, where the single-file kids_video_service.py lived: every data path built on
# HERE was written against that directory, and this package sits one level deeper.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Geometry and rate ────────────────────────────────────────────────────────
# Render 16:9 at 1.33 MP and finish at 1080p: the Ken Burns pass crops INTO the
# render, so the effective upscale at full zoom is ~1.37x.  Flat cartoon art
# carries almost no high-frequency detail, which is exactly the content that
# survives that scale factor.
RENDER_W = int(os.environ.get('ZYG_KIDSVIDEO_W', '1536'))
RENDER_H = int(os.environ.get('ZYG_KIDSVIDEO_H', '864'))
OUT_W, OUT_H = 1920, 1080
FPS = int(os.environ.get('ZYG_KIDSVIDEO_FPS', '24'))

# THE PICTURE RATE IS THE CLIP LENGTH (2026-10-02).
#
# Every picture becomes an LTX-2.5 image-to-video clip, so one picture is worth
# exactly as many seconds of finished video as its clip runs.  Those two numbers
# used to be set independently, and they disagreed by a factor of five: the slot
# walk cut on the bar (2.05 s at 117 bpm, under a 2.45 s ceiling) while the
# SHORTEST clip LTX will render is 2 s.  Measured on job 81fb01e85934 — a 57.4 s
# song — that produced 54 picture slots, 104 image renders (the candidate pool
# doubles them), 54 clips, and threw away roughly half of every clip it paid the
# GPU for.
#
# CLIP_S is now the single knob and the slot ceiling is derived FROM it, not the
# other way round.  One picture per clip means a 60 s song needs 60/CLIP_S
# pictures: ~12 at 5 s, ~6 at 10 s.
#
# WHY 5 s IS THE DEFAULT AND 10 s IS THE CEILING.  Measured on this 4090 at
# 0.9 MP: 5 s = 43 s wall, 10 s = 57 s, 30 s = 246-263 s, and 30 s does not fit
# (48217 of 49140 MiB).  VRAM is not the binding limit, DRIFT is: a free-running
# 30 s clip loses its subject by 15 s and never recovers it, while 10 s holds.
# Past 10 s the last frame has to be pinned (LTXVAddGuide at frame_idx=-1, which
# this leg does not do), so a longer clip is refused rather than shipped drifting.
CLIP_S_MAX = 10.0
CLIP_S_MIN = 2.0  # LTX needs 8n+1 frames; 49 @ 24 fps
_clip_s_asked = float(os.environ.get('ZYG_KIDSVIDEO_CLIP_S', '5'))
CLIP_S = max(CLIP_S_MIN, min(CLIP_S_MAX, _clip_s_asked))
# Headroom between the longest slot and the clip that has to cover it: the xfade
# compensation this slot gives away to its neighbours (up to one full 0.45 s
# transition, see _xfade_graph) plus clip_seconds' own 0.3 s margin.  Subtracting
# it is what keeps the requested clip at CLIP_S whole seconds instead of CLIP_S+1.
XFADE_MAX_S = 0.45
CLIP_HEADROOM_S = XFADE_MAX_S + 0.3
WINDOW_S = 5.0
MAX_SLOT_S = float(os.environ.get('ZYG_KIDSVIDEO_MAX_SLOT_S', str(round(CLIP_S - CLIP_HEADROOM_S, 4))))
# A picture on screen for a small fraction of its own clip is rendered motion
# thrown away, so the floor travels with the ceiling.  0.35 s is kept as the
# absolute floor because a picture shorter than that is invisible and wrecks its
# own transitions.
MIN_SLOT_S = float(os.environ.get('ZYG_KIDSVIDEO_MIN_SLOT_S', str(round(max(0.35, 0.3 * MAX_SLOT_S), 4))))
if MIN_SLOT_S > 0.9 * MAX_SLOT_S:  # a bad env pair must not deadlock the walk
    MIN_SLOT_S = 0.9 * MAX_SLOT_S
# A LEFTOVER MAY STRETCH A PICTURE INSTEAD OF SPLITTING IT.  The ceiling above is
# a TARGET, and what follows is the hard limit: a picture may run this much past
# it, which costs one extra second of clip and never an extra picture.
#
# Why it has to exist.  Measured on job 7d67da47b424, a 59.9 s song: every one of
# its six sections is 8.55 s, which is 2.09 base units, leaving a 0.37 s tail. A
# tail that small cannot be its own picture, so it was handed to the picture
# before it — 4.10 + 0.37 = 4.47 s, which broke a 4.25 s ceiling by 22 ms and was
# therefore SPLIT IN HALF. Every section shipped 4.10 + 2.24 + 2.24 instead of
# 4.10 + 4.45: three pictures where two would do, and a 2 s picture beside a 4 s
# one. The song laid out 20 pictures where 14 cover it.
#
# The arithmetic of the choice: absorbing makes that slot's clip 6 s instead of 5
# (one clip-second, ~6 s of GPU), splitting adds a whole picture — two image
# renders with the candidate pool, plus a 3 s clip. Absorbing is cheaper on both
# counts and it keeps the only cut inside the section on a bar line.
#
# ZYG_KIDSVIDEO_ABSORB_S=0 restores a hard ceiling, which is what the
# pre-2026-10-02 cadence needs (its 2-per-5s floor IS the ceiling).
ABSORB_S = float(os.environ.get('ZYG_KIDSVIDEO_ABSORB_S', '1.0'))
ABSORB_MAX_S = MAX_SLOT_S + max(0.0, ABSORB_S)
# DERIVED, not asserted.  The rate is whatever the ceiling implies: every slot is
# at most MAX_SLOT_S, so the mean cannot fall below WINDOW_S / MAX_SLOT_S, and
# any rolling window holds at least floor(WINDOW_S / MAX_SLOT_S) picture starts —
# which is 1 at a 5 s clip and 0 at a 10 s one, because a 10 s picture genuinely
# can fill a 5 s window on its own.  Both are reported; neither is hoped for.
# ZYG_KIDSVIDEO_PER_5S still pins the mean target by hand.
TARGET_PER_5S = float(os.environ.get('ZYG_KIDSVIDEO_PER_5S', str(round(WINDOW_S / ABSORB_MAX_S, 4))))
MIN_STARTS_PER_5S = int(WINDOW_S // ABSORB_MAX_S)
# The pre-2026-10-02 cadence (one picture a bar, beat bursts, 2 s clips covering
# 1 s slots) is still reachable, and reachable only on purpose:
#     ZYG_KIDSVIDEO_MAX_SLOT_S=2.45 ZYG_KIDSVIDEO_MIN_SLOT_S=0.35 \
#     ZYG_KIDSVIDEO_ABSORB_S=0
_RATE_NOTES = []
if _clip_s_asked != CLIP_S:
    _RATE_NOTES.append(
        f'ZYG_KIDSVIDEO_CLIP_S={_clip_s_asked:g} clamped to {CLIP_S:g}s '
        f'({CLIP_S_MIN:g}-{CLIP_S_MAX:g}s: below that LTX has no clean frame '
        f'count, above it a free-running clip drifts off its first frame)'
    )

# ── Generation speed ─────────────────────────────────────────────────────────
#
# FAST MODE IS THE DEFAULT, and it is worth 6x.  Measured on this box over the
# 49 real prompts of one song, same prompts, same resolution:
#
#     klein BASE, 18 steps, cfg 4.0   13.5 s an image   659 s for the song
#     klein DISTILLED, 4 steps, cfg 1  2.2 s an image   109 s for the song
#
# Two multiplications, not one.  Fewer steps is the obvious half; the other half
# is that **cfg 1.0 stops the negative branch running**, so the transformer does
# one forward pass per step instead of two.  The numbers say so cleanly: the
# base costs 0.647 s per step (18→12 steps saved 3.88 s) and the distilled
# 0.335 s (4→6 steps cost 0.67 s) — exactly half, which is the second pass
# disappearing.  Base 18 steps at cfg>1 is 36 forward passes; distilled 4 steps
# at cfg 1 is 4.
#
# QUALITY WAS MEASURED, NOT ASSUMED.  Over those same 49 prompts: cartoon 0.961
# mean against 0.965, joy 0.989 against 0.992, and mean pairwise CLIP similarity
# 0.7633 against 0.7773 — the distilled set is marginally MORE varied, so the
# usual step-distillation worry (mode collapse) does not show here.  The one
# real difference was a single frame that fell under the cartoon threshold, and
# looking at it settled what that meant: a flat cartoon seed on a mound of soil,
# scored 0.676 because a near-empty frame gives CLIP little picture-book to
# read.  That is the GATE's weak spot, not the model's — the same frame from the
# base model scored 0.906, also low.  The answer is the retry pass below, which
# a 2 s render makes affordable in a way a 13 s one did not.
#
# ZYG_KIDSVIDEO_FAST=0 puts the undistilled base back (slower, no measured
# quality gain here — it is the right choice for LoRA training, not for this).
_FAST = os.environ.get('ZYG_KIDSVIDEO_FAST', '1').strip().lower() not in ('0', 'false', 'no', 'off')
_KLEIN_DISTILLED = 'flux-2-klein-4b.safetensors'
_KLEIN_BASE = 'flux-2-klein-base-4b.safetensors'
# 'hidream' (default since 2026-10-02): HiDream-O1-Image-Dev on the :8189 ComfyUI,
# MIT, 28 steps, ~5 s a 1536x864 picture measured. 'klein' is the FLUX.2 klein path
# on :8188 and remains the fallback when :8189 cannot be reached.
MODEL_FAMILY = os.environ.get('ZYG_KIDSVIDEO_FAMILY', 'hidream').strip().lower()


def _resolve_fast_unet():
    """The distilled checkpoint if it is REALLY on disk, else None.

    Resolved ONCE, at import, because everything below is derived from it.
    """
    if not _FAST or MODEL_FAMILY != 'klein':
        return None
    p = os.path.join(
        str(paths.ZYG_COMFY_ROOT),
        'models',
        'diffusion_models',
        _KLEIN_DISTILLED,
    )
    return _KLEIN_DISTILLED if os.path.isfile(p) else None


# THE CHECKPOINT DECIDES THE SAMPLER SETTINGS, NOT THE FLAG.  These two used to
# be bound to different things — steps/cfg to ZYG_KIDSVIDEO_FAST, the checkpoint
# to an isfile() check — and they could come apart in BOTH directions:
#
#   * checkpoint moved or renamed → fast_unet() returns None and the resolver
#     hands back the BASE model, but steps/cfg stayed 4/1.0. A 4-step cfg-1.0
#     base render is the FLUX-schnell mistake inverted, and it is silent: the
#     pictures just quietly get worse.
#   * ZYG_KIDSVIDEO_CFG=4 with fast left on → the DISTILLED model at cfg 4,
#     which is the schnell mistake the right way round.
#
# How much of a net comfy_generation_service provides was CHECKED, not assumed,
# and it is exactly half a net:
#   * cfg IS caught — `_sampler_cfg = 1.0 if klein_is_distilled(unet) else cfg`
#     (comfy_generation_service.py:2250) has no force_unet guard, so a distilled
#     checkpoint samples at cfg 1.0 whatever this module asks for.
#   * steps are NOT — the clamp at :2090 is written `and not force_unet`, and
#     force_unet is the very thing this module passes, so a 4-step count would
#     ride onto a BASE model with nothing to stop it.
# The first bullet above is therefore already defended below us; the second is
# not, and it is the silent one (the pictures just quietly get worse). So the
# pairing is made HERE, and _FAST_ACTIVE — did a distilled checkpoint really
# resolve? — is what the defaults and the log line read, rather than _FAST,
# which only says whether fast mode was asked for.
_FAST_UNET = _resolve_fast_unet()
_FAST_ACTIVE = _FAST_UNET is not None

STEPS = int(os.environ.get('ZYG_KIDSVIDEO_STEPS', '4' if _FAST_ACTIVE else '18'))
CFG = float(os.environ.get('ZYG_KIDSVIDEO_CFG', '1.0' if _FAST_ACTIVE else '4.0'))
# Measured seconds per image, used only for the ETA line.
_ETA_PER_IMAGE = float(
    os.environ.get('ZYG_KIDSVIDEO_ETA_S', '5.5' if MODEL_FAMILY == 'hidream' else ('2.5' if _FAST_ACTIVE else '14.0'))
)

# An explicit override is still allowed, but it may not put the pair into the
# state above. Guidance is BAKED INTO the distilled model; real CFG on top of it
# degrades the sample, so cfg is clamped and the reason is carried in
# _SPEED_WARNINGS for the run log rather than being swallowed at import.
_SPEED_WARNINGS = []
if _FAST_ACTIVE and CFG != 1.0:
    _SPEED_WARNINGS.append(
        f'ZYG_KIDSVIDEO_CFG={CFG:g} ignored: the distilled klein bakes its guidance in, so cfg is clamped to 1.0'
    )
    CFG = 1.0
if _FAST_ACTIVE and STEPS > 8:
    _SPEED_WARNINGS.append(
        f'ZYG_KIDSVIDEO_STEPS={STEPS} is a base-model step count on a distilled checkpoint — clamped to 4'
    )
    STEPS = 4
if _FAST and not _FAST_ACTIVE and MODEL_FAMILY == 'klein':
    _SPEED_WARNINGS.append(
        f'fast mode was asked for but {_KLEIN_DISTILLED} is not on disk — '
        f'falling back to the BASE model at {STEPS} steps/cfg {CFG:g} '
        f'(slower, not worse)'
    )


def speed_note():
    """One line naming the model and settings actually in force."""
    if _FAST_ACTIVE:
        return f'fast: distilled klein, {STEPS} steps, cfg {CFG:g}'
    return f'base klein, {STEPS} steps, cfg {CFG:g}'


def fast_unet():
    """The distilled klein checkpoint, or None to let the resolver decide.

    Passed as ``force_unet`` rather than by setting ZYG_KLEIN_DISTILLED, which is
    a PROCESS-WIDE switch: the GUI is one process and the creature sheets, the
    storyteller and the contact-sheet generator all resolve klein through the
    same function.  Speeding this workflow up must not quietly re-point theirs at
    a distilled model.
    """
    return _FAST_UNET


# A ceiling on renders per song, not on pictures per second: past it the chorus
# repeats reuse their pictures (a children's-video device anyway) and the
# manifest says so.  180 s at a fast tempo asks for ~100 pictures.
MAX_IMAGES = int(os.environ.get('ZYG_KIDSVIDEO_MAX_IMAGES', '120'))

# Motion.  Deliberately gentle — this is a slideshow for small children, not a
# trailer.  The pulse is a 1.5 % zoom bump on the bar downbeat, which reads as
# the picture breathing with the music rather than as movement.
KB_ZOOM = float(os.environ.get('ZYG_KIDSVIDEO_ZOOM', '0.07'))
PULSE_AMP = float(os.environ.get('ZYG_KIDSVIDEO_PULSE', '0.015'))
PULSE_S = 0.22

# Gates.  See the module docstring for the null these thresholds sit against.
CARTOON_MIN = float(os.environ.get('ZYG_KIDSVIDEO_CARTOON_MIN', '0.75'))
JOY_MIN = float(os.environ.get('ZYG_KIDSVIDEO_JOY_MIN', '0.60'))
# OCR fires on flecks of line-art at the default 0.1 % area threshold (the sample
# train's coupling rod read as '0'), so lettering is only counted from 0.4 % of
# the frame up — big enough to be lettering someone can actually read.
OCR_MIN_AREA = float(os.environ.get('ZYG_KIDSVIDEO_OCR_AREA', '0.004'))

_OLLAMA = paths.ZYG_OLLAMA_URL.rstrip('/')
_LLM = os.environ.get('ZYG_KIDSMUSIC_LLM', 'qwen3.5:9b')


def _log_noop(_m):
    pass
