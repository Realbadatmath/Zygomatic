# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Imports, tunables, licence tables and the two log/ffmpeg helpers.

Moved verbatim out of the old single-file kids_music_service.py (lines 58-318).
"""

from __future__ import annotations

import os
import subprocess
import logging as _zyg_logging
from zyg_workflows.bin import exe


_zyg_log = _zyg_logging.getLogger(__name__)


# One dirname deeper than the old single-file module, so that HERE keeps the
# value it has always had — the zyg_workflows package directory. OUT_ROOT,
# CINEMATIC_OUT_ROOT, the default SOUNDFONT, _AGENTS_PY and _DEMUCS_TOOL are
# all anchored on it, and every one of them must still name the same path.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOUNDFONT = os.environ.get(
    'ZYG_KIDSMUSIC_SF2', os.path.join(HERE, 'data', 'assets', 'music', 'soundfonts', 'MuseScore_General.sf3')
)
OUT_ROOT = os.path.join(HERE, 'output', 'kidsmusic')
# The cinematic family's own output root. House rule: every workflow owns its
# output directory — a cue is not a children's song and does not live in its
# folder, and the two boards read the two trees.
CINEMATIC_OUT_ROOT = os.path.join(HERE, 'output', 'cinematic')
TICKS_PER_BEAT = 480
# The tune must sit at least this far above the bass. Measured on the six shipped
# songs the margin was -8.7 to -0.1 dB — i.e. the melody was UNDER the bass in
# five of six, and only the ocarina-lead song had it on top.
MIX_MARGIN_MIN_DB = float(os.environ.get('ZYG_KIDSMUSIC_MIX_MARGIN_DB', '4.0'))
SR = 48000

# ACE-Step checkpoint is read from the same env var ace_step_service uses, so the
# two never disagree about which file is on disk.
ACE_CHECKPOINT = os.environ.get('ZYG_ACE_STEP_CHECKPOINT', 'ace_step_1.5_turbo_aio.safetensors')
ACE_WORKFLOW = 'ace_step_kidsong'
# Same graph plus the crews node that forwards caption_negative to the audio-code
# LM. Used only when that node is actually loaded on the live server.
ACE_WORKFLOW_NEG = 'ace_step_kidsong_neg'
ACE_NEG_NODE = 'TextEncodeAceStepAudio1.5WithNegative'
# Melody conditioning: start the sampler from the SCORE RENDER's latent instead
# of from noise, so the ACE leg can follow the composed tune.
#
# Spiked 2026-08-29 and it WORKS — the latent contract between VAEEncodeAudio
# ({samples}) and EmptyAceStep1.5LatentAudio ({samples, type,
# downscale_ratio_temporal}) turned out to be tolerated. Measured across denoise,
# chroma z against a 4-song null, with vocal presence as the control:
#
#   denoise  chroma z   vocal vs mix   verdict
#     0.35     15.48       -27.1 dB    NO VOCAL — this is the score render with
#                                      noise on it. The high z is the input
#                                      barely changing, not ACE following.
#     0.45      7.35        -6.1 dB    a real sung take that follows the melody
#     0.55      3.15        -2.6 dB    follows, more loosely
#     0.65      2.37        -4.4 dB    marginal
#
# 0.45 is the setting. The 0.35 row is why the vocal-presence precondition in
# gate_singer_age is not optional: without it, the best-looking chroma number in
# the sweep came from a take with no singer in it at all.
#
# DEFAULT ON since 2026-08-29, by operator decision after the spike.
# The evidence behind it is one run per denoise setting on one brief, which is
# thin — so the safeguards are the point: delivery.melody_followed is MEASURED
# every run against a cross-song null, the singer gate still has to pass on the
# conditioned take, and ZYG_KIDSMUSIC_A2A=0 turns it off. If conditioning ever
# stops working, the manifest says so on the run it stops working, rather than
# this comment being the only thing anybody has to go on.
ACE_WORKFLOW_A2A = 'ace_step_kidsong_a2a_spike'
A2A_DENOISE = float(os.environ.get('ZYG_KIDSMUSIC_A2A_DENOISE', '0.45'))
# Sampler steps. 0 = leave the graph's own value (8 on every kidsong workflow).
# A knob rather than a graph edit because the three workflows have to move
# together and the sweep that sets it has to vary one thing at a time.
ACE_STEPS = int(os.environ.get('ZYG_KIDSMUSIC_ACE_STEPS', '0') or 0)
# THE DENOISE LADDER (2026-10-04). a2a denoise is the ARTICULATION lever, and it
# trades directly against melody conditioning — one knob buys both. Measured over
# 5 songs / 82 lines, fixed seed, unprompted ASR on the mix:
#
#   denoise   lines a listener can make out   songs still following the melody
#   0.45      41/82  (50 %)                   5 of 5
#   0.55      68/82  (83 %)                   3 of 5
#   0.60      74/82  (90 %)                   3 of 5
#
# Why: a2a starts the sampler from the SCORE RENDER's latent, which is
# instrumental — there is no voice in it. denoise 0.45 skips the high-noise part
# of the schedule, which is where structure (including "a clearly articulated
# voice") is decided, so the model inherits an instrumental bed and has only the
# low-noise end to grow a singer in. Steps do NOT fix it: 8->32 at d0.45 made it
# WORSE (8/12 -> 4/12 clear), because more steps only lock the instrumental
# source in harder. COVER mode is not the answer either — it re-performs the
# score render faithfully and so sings almost nothing (0/12 clear, severity 122).
#
# A blanket raise is wrong: the two songs that lost the melody at 0.55 were
# already clear at 0.45, and the songs that NEED the help kept their melody
# (858519988c05 0/34 -> 22/34 clear with z still 9.46). So the ladder is climbed
# per song, only when the take is measurably unclear, and a take that lost the
# tune can never beat one that kept it (see _better_take).
A2A_DENOISE_LADDER = [
    float(x) for x in os.environ.get('ZYG_KIDSMUSIC_A2A_LADDER', '0.45,0.55,0.65').split(',') if x.strip()
]
# A take is unclear enough to climb when under this share of its lines can be
# made out. 0.8 sits above every healthy take measured (0184f 11/12, c2fde 12/12,
# f74ad 10/12) and below every broken one (df012 8/12, 858519 0/34).
CLEAR_SHARE_MIN = float(os.environ.get('ZYG_KIDSMUSIC_CLEAR_SHARE_MIN', '0.8'))
# COVER mode — the lever a2a never pulled. a2a only swaps the sampler's STARTING
# latent, which constrains texture and timing while the DiT's melodic context
# still comes from the audio codes the LM invented from the caption. Feeding the
# same latent into ReferenceTimbreAudio instead sets is_covers=True in
# comfy/model_base.py, DROPS those LM codes, and tokenises the reference itself
# into the 5 Hz semantic codes that become the source context (see
# comfy/ldm/ace/ace_step15.py prepare_condition). That is ACE-Step's cover task:
# the source's melody, rhythm and chords are re-performed. ComfyUI exposes it at
# full strength only — no audio_cover_strength / cover_noise_strength dials.
# generate_audio_codes goes OFF with a reference (the node's own tooltip says so;
# the LM run would be thrown away).
ACE_WORKFLOW_COVER = 'ace_step_kidsong_cover'

# The soundfont files this workflow is allowed to render through, by sha256.
# ok_commercial is DERIVED from this table plus the presence of real audio — it
# used to be a hardcoded True, and a run pointed at a nonexistent soundfont still
# shipped a manifest reading "MuseScore_General.sf3 (MIT)", ok_commercial: true,
# with no audio rendered at all.
ALLOWED_SOUNDFONTS = {
    'MuseScore_General.sf3': {
        'licence': 'MIT',
        'attribution': (
            'FluidR3 by Frank Wen (c) 2000-02; FluidR3Mono conversion by Michael '
            'Cowgill (c) 2014-17; MuseScore_General adaptation by S. Christian '
            'Collins (c) 2018-19; Temple Blocks by Ethan Winer (c) 2002; '
            'Drumline Cymbals by Michael Schorsch (c) 2016.'
        ),
    },
}

# ACE-Step, stated at the precision the evidence supports.
#
# The CODE is MIT with a real LICENSE file. The WEIGHTS have no licence file in
# any of the four upstream repositories — "MIT" there is a model-card tag only,
# and the file installed on this box is byte-size-matched to a Comfy-Org repack
# distributed under an apache-2.0 tag. Both tags are on the permitted list, so
# nothing is known to be violated; but "ACE-Step 1.5 (MIT weights)" states more
# than is known and is not written into any manifest any more.
ACE_LICENCE = {
    'code': 'MIT (LICENSE file present upstream)',
    'weights': 'no licence file upstream; model-card tag only',
    'weights_tag_seen': 'apache-2.0 (Comfy-Org repack)',
    'weights_source': 'Comfy-Org ACE-Step 1.5 repack, size-matched',
    'representation_dated': '2026-08-29',
    'note': (
        'Card tags are a vendor REPRESENTATION, not a licence grant. Both '
        'tags seen (MIT, apache-2.0) are on the permitted list.'
    ),
}


# The picture leg.  klein 4B is the ONLY image family this workflow renders on,
# and the reason is a licence one rather than an aesthetic one: DynaVision XL
# (the animated SDXL checkpoint) and Juggernaut both classify UNKNOWN in the
# registry — Civitai per-model permission flags that were never read at source —
# and this channel is monetised.  klein's Apache-2.0 grant is on the BFL repo
# itself, not merely on a repack.  Named literally, because a `flux-2-klein-*`
# glob would also clear the 9B, which is non-commercial.
IMAGE_LICENCE = {
    'family': 'FLUX.2 [klein] 4B',
    'weights': 'flux-2-klein-base-4b.safetensors',
    'licence': 'Apache-2.0',
    'source': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B',
    'text_encoder': 'Qwen3-4B (Apache-2.0, bundled with klein)',
    'vae': 'flux2-vae.safetensors (Apache-2.0, from the Comfy-Org klein repo)',
    'note': (
        'Verified per render by licence_provenance.attest_licences on the '
        'submitted graph. The counting cards, and any fallback card drawn '
        'when the generator is unavailable, are original PIL vector art '
        'with no model involved — frames_drawn counts both.'
    ),
}


def _licence_note(sf_info, ace_used, video_used=False, video_drawn_only=False, sampler=None):
    """The shipped LICENSE.txt, built from what actually ran.

    `sampler` is melody_sampler's render record plus its credits(), and it is
    present only when the SAMPLED render is the one that shipped. Its
    attribution lines are not advisory: a cc-by-* sample in the score render
    means that credit must appear here, in the folder that goes out.
    """
    lines = [
        'Audio in this folder is rendered from a melody composed by '
        'kids_music_theory.py (original work, no training data, no model).',
        '',
    ]
    if sf_info.get('ok'):
        lines += [
            f'Score render SoundFont: {sf_info["basename"]} ({sf_info["licence"]}), sha256 {sf_info["sha256"][:16]}...',
            f'Required acknowledgement: {sf_info["attribution"]}',
            '',
        ]
    else:
        lines += [
            f'Score render SoundFont: {sf_info.get("basename") or "none"} — '
            f'NOT VERIFIED ({sf_info.get("reason") or "unknown"}).',
            '',
        ]
    if sampler:
        cred = sampler.get('credits') or {}
        lines.append('Sampled instruments (score render):')
        for role in ('lead', 'pad', 'bass'):
            info = (sampler.get('voices') or {}).get(role) or {}
            if not info:
                continue
            lic = ', '.join(sorted(info.get('licences') or {})) or 'unknown'
            lines.append(f'  {role:<5} {info.get("key", "?")} — {lic}')
        for a in cred.get('attributions') or []:
            lines.append(f'  credit: {a}')
        for v in cred.get('violations') or []:
            # license_gate's violations are dicts {'cat','id','reasons'}.
            lines.append(
                f'  VIOLATION: {v.get("id")} — {"; ".join(v.get("reasons") or [])}'
                if isinstance(v, dict)
                else f'  VIOLATION: {v}'
            )
        if not cred.get('ok', True):
            lines.append('  These samples are NOT cleared for commercial use.')
        lines.append('')
    if ace_used:
        lines += [
            'ACE-Step 1.5 variation leg:',
            f'  code:    {ACE_LICENCE["code"]}',
            f'  weights: {ACE_LICENCE["weights"]}',
            f'           tag seen: {ACE_LICENCE["weights_tag_seen"]} '
            f'({ACE_LICENCE["weights_source"]}), '
            f'recorded {ACE_LICENCE["representation_dated"]}',
            f'  {ACE_LICENCE["note"]}',
            '',
        ]
    if video_used:
        if video_drawn_only:
            lines += [
                'Picture leg: every frame was DRAWN by kids_video_service '
                '(original PIL vector art) — no image model ran.',
                '',
            ]
        else:
            lines += [
                'Picture leg:',
                f'  family:  {IMAGE_LICENCE["family"]} ({IMAGE_LICENCE["licence"]})',
                f'  weights: {IMAGE_LICENCE["weights"]}',
                f'  encoder: {IMAGE_LICENCE["text_encoder"]}',
                f'  vae:     {IMAGE_LICENCE["vae"]}',
                f'  source:  {IMAGE_LICENCE["source"]}',
                f'  {IMAGE_LICENCE["note"]}',
                '',
            ]
    lines += ['Commercial clearance for this folder is recorded in manifest.json under "licence".', '']
    return '\n'.join(lines)


def _log_noop(_m):
    pass


def _ff(args, log_fn=None):
    """ffmpeg, quiet, never raising across the module boundary."""
    cmd = [exe('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'error'] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 and log_fn:
            log_fn(f'ffmpeg failed: {(r.stderr or "")[:200]}')
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        if log_fn:
            log_fn(f'ffmpeg error: {e}')
        return False
