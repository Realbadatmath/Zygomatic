# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 5 of run(): the ACE-Step leg, takes, repair and the voice leg.

Moved verbatim out of the old single-file kids_music_service.py (lines 3502-3923).
The leg's stages live in ``run_ace_takes``; this module keeps the orchestrator,
every ``ZYG_KIDSMUSIC_*`` read (``zyg_workflows.settings`` attributes those
flags to this file by name) and the bindings the package's shared namespace
patches.
"""

from __future__ import annotations

import os

from zyg_workflows.kids_music_service import ace as _ace
from zyg_workflows.kids_music_service import base as _base
from zyg_workflows.kids_music_service import master as _master
from zyg_workflows.kids_music_service import measure as _measure
from zyg_workflows.kids_music_service import melody as _melody
from zyg_workflows.kids_music_service import mixdown as _mixdown
from zyg_workflows.kids_music_service import repaint as _repaint
from zyg_workflows.kids_music_service import singer as _singer
from zyg_workflows.kids_music_service import soundfont as _soundfont

# Bound by ASSIGNMENT, not `from … import`, for two reasons: the package's
# _SharedNamespace forwards a patch (K.ace_render = stub) into every submodule
# that HOLDS the name, so run_ace_takes can read them back off this module and
# still see the stub; and ruff cannot prune an assignment the way it prunes an
# import this module no longer calls itself.
A2A_DENOISE_LADDER = _base.A2A_DENOISE_LADDER
CLEAR_SHARE_MIN = _base.CLEAR_SHARE_MIN
_zyg_log = _base._zyg_log
lowered_lead_wav = _soundfont.lowered_lead_wav
ace_render = _ace.ace_render
repair_take = _repaint.repair_take
gate_audio = _measure.gate_audio
_better_take = _melody._better_take
_null_plans = _melody._null_plans
chroma_follow = _melody.chroma_follow
gate_singer_age = _singer.gate_singer_age
_mp3 = _mixdown._mp3
save_stems = _master.save_stems


def _ace_mode(log_fn):
    """The ACE conditioning mode this run was asked for.

    '' or 'auto' (the default) keeps today's rule, spelled out rather than
    changed: melody conditioning when `want_a2a` and a SoundFont render exists,
    plain text-to-music otherwise. 'text' forces the LM to invent the audio
    codes even when conditioning is available; 'a2a' forces the melody latent;
    'cover' hands the SoundFont render to ReferenceTimbreAudio so the composed
    tune is RE-PERFORMED (the keyscale is already the plan's). An unknown name
    is logged and falls back to the default.
    """
    mode = os.environ.get('ZYG_KIDSMUSIC_ACE_MODE', '').strip().lower() or 'auto'
    if mode not in ('auto', 'text', 'a2a', 'cover'):
        log_fn(f'ace: unknown ACE mode {mode!r} — running the default')
        mode = 'auto'
    return mode


def _take_count():
    """How many takes to render. 1 (the default) is today: one take, re-seeded
    while the singer gate fails. N > 1 renders N takes at base_seed+k, gates
    EVERY one of them and keeps the least shrill passer by rank_score."""
    try:
        return max(1, int(os.environ.get('ZYG_KIDSMUSIC_TAKES', '1')))
    except ValueError:
        return 1


def _conditioning(ace_mode, want_a2a, render_wav_kept, soundfont_wav, log_fn):
    """What this run hands to ace_render: ``(cond_melody, cond_cover)``.

    `auto` is the shipped expression; the other three modes are the opt-in
    levers, off unless the environment says otherwise.
    """
    cond_melody = render_wav_kept if want_a2a else None
    cond_cover = None
    if ace_mode == 'text':
        cond_melody = None
    elif ace_mode == 'a2a':
        cond_melody = soundfont_wav
    elif ace_mode == 'cover':
        cond_melody, cond_cover = None, soundfont_wav
        if not soundfont_wav:
            log_fn('ace: cover mode asked for, but there is no score render to cover — falling back to text-to-music')
    return cond_melody, cond_cover


def _singer_retries(singer):
    """The re-seed budget: the environment wins when it says anything;
    otherwise the singer carries its own (adult_male: 6, one per seed x
    conditioning)."""
    _env_try = os.environ.get('ZYG_KIDSMUSIC_SINGER_RETRIES', '').strip()
    return int(_env_try) if _env_try else int(singer.get('singer_retries') or 3)


def _voice_review_on():
    """Whether a passing take is reviewed on its own separated vocal."""
    return os.environ.get('ZYG_KIDSMUSIC_VOICE_REVIEW', '1').strip() not in ('0', 'false', 'no', 'off')


def _repair_on():
    """Whether the voice review may repaint the lines it finds problems in."""
    return os.environ.get('ZYG_KIDSMUSIC_REPAIR', '1').strip() not in ('0', 'false', 'no', 'off')


def _voice_budget_s():
    """Seconds of work the whole voice leg may spend chasing a better take."""
    return float(os.environ.get('ZYG_KIDSMUSIC_VOICE_BUDGET_S', '900'))


def _repair_budget_s():
    """Seconds one repaint pass may spend, before the leg's remaining budget."""
    return float(os.environ.get('ZYG_KIDSMUSIC_REPAIR_BUDGET_S', '360'))


def _apply_gates(leg, gates):
    """Measure the produced track and fold the singer gate's verdict into it."""
    gates['produced'] = gate_audio(leg.ace_mp3, leg.plan, leg='produced', log_fn=leg.log_fn)
    if leg.singer_gate is not None:
        gates['singer'] = leg.singer_gate
        if not leg.singer_gate.get('ok') and leg.singer_gate['status'] != 'skipped':
            gates['produced']['fails'].append(f'singer gate: {leg.singer_gate.get("detail")}')
            gates['produced']['ok'] = False


def stage_ace(
    *,
    abort,
    cinematic,
    gates,
    log_fn,
    midi,
    out_dir,
    plan,
    render_wav_kept,
    should_abort,
    singer,
    soundfont_wav,
    stage,
    want_a2a,
    want_ace,
):
    """Stage 5 of run().

    The ACE-Step leg is a straight-line block of run() with its own section
    banner (old kids_music_service.py lines 3502-3923). It lives in its own
    module because run() is 1,116 lines and the house ceiling for a module is
    800; the names below are exactly the locals that crossed the cut — read on
    the way in, read again by run() on the way out.

    The leg itself is a bounded re-seed loop (a failing gate used to leave a red
    mark on a track that shipped anyway, because run() had no re-render path)
    with two opt-in levers, both off unless the environment says otherwise, so
    an unconfigured run renders exactly what it rendered yesterday:
    ZYG_KIDSMUSIC_ACE_MODE (see ``_ace_mode``) and ZYG_KIDSMUSIC_TAKES (see
    ``_take_count``). Its stages are in ``run_ace_takes``.
    """
    from zyg_workflows.kids_music_service import run_ace_takes as _takes

    ace_mode = _ace_mode(log_fn)
    n_takes = _take_count()
    cond_melody, cond_cover = _conditioning(ace_mode, want_a2a, render_wav_kept, soundfont_wav, log_fn)
    leg = _takes.AceLeg(
        plan=plan,
        singer=singer,
        midi=midi,
        out_dir=out_dir,
        cinematic=cinematic,
        log_fn=log_fn,
        should_abort=should_abort,
        abort=abort,
        stage=stage,
        ace_mode=ace_mode,
        cond_melody=cond_melody,
        cond_cover=cond_cover,
        n_takes=n_takes,
    )
    if want_ace and not abort():
        stage('Produced Track (ACE-Step)')
        _takes.open_leg(leg)
        _takes.run_take_loop(leg)
        if leg.best_voice is not None:
            _takes.ship_reviewed_take(leg)
        if leg.ace_takes:
            _takes.pick_ranked_take(leg)
        if leg.ace_mp3:
            _apply_gates(leg, gates)
    elif want_ace:
        leg.produced_status = 'skipped_by_operator'
        log_fn('ace: skipped (halt requested)')
    else:
        leg.produced_status = 'not_requested'

    return (
        leg.ace_info,
        ace_mode,
        leg.ace_mp3,
        leg.ace_takes,
        leg.attempts,
        cond_cover,
        cond_melody,
        n_takes,
        leg.picked_take,
        leg.produced_status,
        leg.voice,
    )
