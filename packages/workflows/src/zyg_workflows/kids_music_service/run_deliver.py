# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stages 6b and 7 of run(): the illustrated video, the licence block and the manifest.

Moved verbatim out of the old single-file kids_music_service.py (lines 4024-4386).

`stage_deliver` is the orchestrator; the helpers below it are the six phases it runs,
in this order: the picture leg, LICENSE.txt, the licence record, the melody-follow
measurement, the manifest and the `_takes` prune. The first four stay in THIS module
because `kids_music_service/__init__.py`'s `_SharedNamespace.__setattr__` forwards a
patch on the package only into the hardcoded `_SUBMODULES` tuple, which names
`run_deliver` — a new sibling would never see a monkeypatch on `chroma_follow`,
`_licence_note` or `_merge_voice_licences`. The manifest builders read no patchable
name at all, so they live in `run_deliver_manifest.py` to keep both files in the
300-600 line band.
"""

from __future__ import annotations

import json
import os

from zyg_workflows.kids_music_service import run_deliver_manifest as _MF
from zyg_workflows.kids_music_service.base import (
    ACE_LICENCE,
    IMAGE_LICENCE,
    _licence_note,
    _zyg_log,
)
from zyg_workflows.kids_music_service.melody import (
    _null_plans,
    chroma_follow,
)
from zyg_workflows.kids_music_service.mixdown import _merge_voice_licences


def stage_deliver(
    *,
    abort,
    ace_info,
    ace_mode,
    ace_mp3,
    ace_takes,
    attempts,
    brief,
    cinematic,
    fallback_safe,
    family,
    gates,
    log_fn,
    lyric_info,
    lyric_src,
    master,
    midi,
    n_takes,
    out_dir,
    pick,
    picked_leg,
    picked_take,
    plan,
    produced_status,
    render_engine,
    render_mp3,
    sampler_credits,
    sampler_fallback,
    sampler_res,
    sc,
    sf_info,
    should_abort,
    singer,
    stage,
    t0,
    trimmed_s,
    voice,
    why,
):
    """Stages 6b and 7 of run().

    Old kids_music_service.py lines 4024-4386: the illustrated video leg, the licence
    block, the measured melody-following figure and the manifest. Split out for
    the same reason as stage_ace; the block's text is unchanged, and the names
    below are exactly the locals that crossed the cut.

    Returns `(manifest, ok, video, want_video, why)`.
    """
    video, want_video = run_video_leg(
        abort=abort,
        brief=brief,
        cinematic=cinematic,
        log_fn=log_fn,
        master=master,
        out_dir=out_dir,
        pick=pick,
        plan=plan,
        should_abort=should_abort,
        stage=stage,
    )
    # Only when the SAMPLED render is the one on disk: a fallback to the
    # SoundFont means no sample was played and there is nothing to credit.
    sampler_block = dict(sampler_res, credits=sampler_credits) if render_engine == 'sampler' else None
    write_licence_file(
        out_dir=out_dir,
        sf_info=sf_info,
        ace_mp3=ace_mp3,
        video=video,
        sampler_block=sampler_block,
        voice=voice,
    )
    licence = build_licence_block(
        ace_info=ace_info,
        ace_mp3=ace_mp3,
        master=master,
        pick=pick,
        sampler_block=sampler_block,
        sampler_credits=sampler_credits,
        sampler_res=sampler_res,
        sf_info=sf_info,
        video=video,
        voice=voice,
    )
    follow = measure_melody_follow(out_dir=out_dir, pick=pick, plan=plan, log_fn=log_fn)

    ok = bool(master or pick)
    if not ok and not why:
        why = 'run produced no audio'

    manifest = _MF.build_manifest(
        ace_info=ace_info,
        ace_mode=ace_mode,
        ace_mp3=ace_mp3,
        ace_takes=ace_takes,
        attempts=attempts,
        brief=brief,
        cinematic=cinematic,
        fallback_safe=fallback_safe,
        family=family,
        follow=follow,
        gates=gates,
        licence=licence,
        lyric_info=lyric_info,
        lyric_src=lyric_src,
        master=master,
        midi=midi,
        n_takes=n_takes,
        ok=ok,
        out_dir=out_dir,
        pick=pick,
        picked_leg=picked_leg,
        picked_take=picked_take,
        plan=plan,
        produced_status=produced_status,
        render_engine=render_engine,
        render_mp3=render_mp3,
        sampler_fallback=sampler_fallback,
        sampler_res=sampler_res,
        sc=sc,
        singer=singer,
        t0=t0,
        trimmed_s=trimmed_s,
        video=video,
        voice=voice,
        why=why,
    )
    with open(os.path.join(out_dir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    prune_takes(out_dir)

    return (
        manifest,
        ok,
        video,
        want_video,
        why,
    )


def run_video_leg(*, abort, brief, cinematic, log_fn, master, out_dir, pick, plan, should_abort, stage):
    """Stage 6b: illustrate the delivered song, or say why there is no video.

    Returns `(video, want_video)` — the `video` record kids_video_service returned (or a
    `{'ok': False, 'reason': …}` refusal), and whether a video was wanted at all.
    """
    # ── 6b. Illustrated video.  Runs only when there is a delivered song to
    #      illustrate, and only AFTER the audio is finished: the picture leg and
    #      ACE-Step share one GPU and one ComfyUI submit lock, so overlapping
    #      them would just make both slower.  A failed video is a failed video —
    #      it never takes the song down with it.
    video = {}
    # A cue is audio. The cinematic styles carry no `look` and no motif pools —
    # kids_video_service has nothing to draw from — so the leg is not attempted
    # and says why, rather than failing its way to the same place.
    want_video = bool(brief.get('want_video', True)) and not cinematic
    if cinematic:
        video = {'ok': False, 'reason': 'not applicable — cinematic melodies carry no pictures'}
    if want_video and (master or pick) and not abort():
        try:
            from zyg_workflows import kids_video_service as KV

            video = KV.run(
                plan,
                brief,
                master or pick,
                out_dir,
                log_fn=log_fn,
                stage_fn=stage,
                should_abort=should_abort,
                opts=brief.get('video_options'),
            )
        except Exception as e:  # noqa: BLE001 — a song ships without
            video = {
                'ok': False,  # its pictures rather than not at all
                'reason': f'{type(e).__name__}: {e}'[:200],
            }
            log_fn(f'video: leg failed — {video["reason"]}')
            # The picture leg frees the GPU on its own success path. A leg that
            # died between generating and measuring did not get there, and it
            # is exactly the run most likely to have left weights resident.
            try:
                from zyg_workflows import kids_video_service as _KV

                _KV.release_clip(log_fn=log_fn)
                _KV.release_comfy_vram(log_fn=log_fn)
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('video-leg VRAM release skipped: %s', _exc)
    elif want_video and not (master or pick):
        video = {'ok': False, 'reason': 'no delivered audio to illustrate'}
    elif want_video:
        video = {'ok': False, 'reason': 'halted by operator'}
    elif not cinematic:
        video = {'ok': False, 'reason': 'not requested'}
    return video, want_video


def write_licence_file(*, out_dir, sf_info, ace_mp3, video, sampler_block, voice):
    """Write `LICENSE.txt` into `out_dir`: the standard note, plus the voice-clone line.

    Takes the picture leg's record (to decide whether any frame was generated rather
    than drawn) and the sampler credit block; writes nothing else and returns nothing.
    """
    _vgen = video.get('generation') or {}
    with open(os.path.join(out_dir, 'LICENSE.txt'), 'w') as fh:
        fh.write(
            _licence_note(
                sf_info,
                bool(ace_mp3),
                video_used=bool(video.get('ok')),
                video_drawn_only=bool(video.get('ok') and not _vgen.get('generated')),
                sampler=sampler_block,
            )
        )
        if (voice.get('conversion') or {}).get('shipped'):
            from zyg_workflows import voice_conversion as _VCL

            fh.write(
                '\nVoice conversion: the sung voice was converted to the trained '
                f'"{voice["conversion"].get("model")}" voice with {_VCL.LICENCE["engine"]}. '
                f'{_VCL.LICENCE["attribution"]} Evidence: {_VCL.PROVENANCE}.\n'
            )


def build_licence_block(
    *, ace_info, ace_mp3, master, pick, sampler_block, sampler_credits, sampler_res, sf_info, video, voice
):
    """Assemble the manifest's `licence` record from what actually rendered.

    Every commercial blocker (an unverified soundfont, a sample-licence violation, a
    failed ACE-Step attestation) clears `ok_commercial`; the key insertion order is the
    record's published shape and is preserved.
    """
    _vgen = video.get('generation') or {}
    # ok_commercial is DERIVED: a verified soundfont on the allow-list AND audio
    # that actually exists. It cannot be true for a run that rendered nothing.
    ok_commercial = bool(sf_info['ok'] and (master or pick))
    licence = {
        'ok_commercial': ok_commercial,
        'soundfont': {
            'basename': sf_info['basename'],
            'licence': sf_info['licence'],
            'sha256': sf_info['sha256'],
            'verified': sf_info['ok'],
            'reason': sf_info['reason'],
            'attribution': sf_info['attribution'],
        },
        'melody': 'composed by kids_music_theory.py — original, no model',
    }
    if sampler_block:
        # The publish fence over the samples that were actually played. A
        # violation here is a commercial blocker exactly like an ACE-Step
        # attestation failure, and is treated as one.
        licence['instruments'] = {
            'ok': sampler_credits.get('ok'),
            'violations': sampler_credits.get('violations') or [],
            'attributions': sampler_credits.get('attributions') or [],
            'licences': _merge_voice_licences(sampler_res.get('voices') or {}),
        }
        if sampler_credits.get('ok') is False:
            licence['ok_commercial'] = False
    if (voice.get('conversion') or {}).get('shipped'):
        from zyg_workflows import voice_conversion as _VCL

        licence['voice_conversion'] = dict(_VCL.LICENCE, weights=voice['conversion'].get('weights'))
    if ace_mp3:
        licence['generator'] = dict(
            ACE_LICENCE, checkpoint=ace_info.get('checkpoint'), attestation=ace_info.get('licence_attestation')
        )
        if (ace_info.get('licence_attestation') or {}).get('ok') is False:
            licence['ok_commercial'] = False
    if video.get('ok'):
        licence['pictures'] = _picture_licence(_vgen)
    return licence


def _picture_licence(_vgen):
    """The `licence.pictures` record for a video that assembled, from its own counters."""
    # Recorded from what ACTUALLY rendered, not from a constant: a video whose
    # frames were all drawn used no image model at all, and saying otherwise
    # would put a weight in the manifest that never loaded.
    return (
        dict(
            IMAGE_LICENCE,
            frames_generated=_vgen.get('generated', 0),
            # BOTH drawing counters: the counting cards are drawn by design
            # and the fallback cards because the generator was down, and a
            # licence record that showed only one of them would understate
            # how much of the video is original PIL art.
            frames_drawn=(_vgen.get('drawn', 0) + _vgen.get('drawn_count', 0) + _vgen.get('drawn_screen', 0)),
            frames_reused=_vgen.get('reused', 0),
        )
        if _vgen.get('generated')
        else {
            'family': 'none — every frame drawn by kids_video_service',
            'licence': 'original work',
            'frames_drawn': (_vgen.get('drawn', 0) + _vgen.get('drawn_count', 0) + _vgen.get('drawn_screen', 0)),
        }
    )


def measure_melody_follow(*, out_dir, pick, plan, log_fn):
    """Measure whether the SHIPPED produced take follows the composed melody.

    Returns `chroma_follow`'s record for `pick`, or `{}` when no produced take shipped;
    logs the one-line verdict when a z-score came back.
    """
    # Does the SHIPPED leg follow the composed melody? The score render does by
    # construction; the ACE leg is the open question and is what this measures.
    follow = {}
    if pick:
        follow = chroma_follow(pick, plan, _null_plans(exclude_dir=out_dir), log_fn=log_fn)
        if follow.get('z') is not None:
            log_fn(
                f'melody: chroma z {follow["z"]:+.2f} vs a {follow["nulls"]}-song '
                f'null → {"follows" if follow.get("followed") else "does NOT follow"} '
                f'the composed tune'
            )
    return follow


def prune_takes(out_dir):
    """Delete `out_dir/_takes` unless ZYG_KIDSMUSIC_KEEP_TAKES asks for it to stay."""
    # The per-take work (copies, stems, repaints, reviews) is ~40 MB a take; the
    # shipped take's stems are already kept as FLAC and its review is in
    # voice_report.json, so nothing here is the only copy of anything.
    if os.environ.get('ZYG_KIDSMUSIC_KEEP_TAKES', '').strip() not in ('1', 'true', 'yes'):
        import shutil as _sh

        _sh.rmtree(os.path.join(out_dir, '_takes'), ignore_errors=True)
