# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""The run — the whole leg, from the delivered song to video.mp4.

Moved verbatim out of the old single-file kids_video_service.py (lines 4068-4395).
"""

from __future__ import annotations

import json
import os
import time
from zyg_workflows import provenance_seal as _seal

from zyg_workflows.kids_video_service.assembly import (
    build_video,
    verify_cuts,
)
from zyg_workflows.kids_video_service.comfy import (
    release_clip,
    release_ollama,
)
from zyg_workflows.kids_video_service.constants import (
    ABSORB_MAX_S,
    CLIP_S,
    FPS,
    MAX_IMAGES,
    MAX_SLOT_S,
    MIN_SLOT_S,
    MIN_STARTS_PER_5S,
    OUT_H,
    OUT_W,
    TARGET_PER_5S,
    WINDOW_S,
    _ETA_PER_IMAGE,
    _SPEED_WARNINGS,
    _log_noop,
    speed_note,
)
from zyg_workflows.kids_video_service.gates import (
    gate_frames,
)
from zyg_workflows.kids_video_service.ideas import (
    assign_ideas,
)
from zyg_workflows.kids_video_service.motifs import (
    look_for,
    motif_pools,
    style_for,
)
from zyg_workflows.kids_video_service.motion import (
    _LTX_WALL_PER_CLIP_S,
    animate_frames,
)
from zyg_workflows.kids_video_service.render import (
    render_images,
    write_thumbs,
)
from zyg_workflows.kids_video_service.screen import (
    CANDIDATES,
    SCREEN_ON,
)
from zyg_workflows.kids_video_service.storyboard import (
    _duration,
    beat_alignment,
    beat_grid,
    clip_plan,
    min_per_window,
    plan_slots,
    rms_envelope,
)


# ── The run ──────────────────────────────────────────────────────────────────


def reassemble(out_dir, audio_path, *, log_fn=None, should_abort=None):
    """Rebuild the video from the frames and storyboard already on disk.

    The expensive half of this leg is the pictures, and there are real reasons to
    redo only the cheap half: a transition or encode setting changed, or some
    frames were repaired or replaced by hand.  Regenerating fifty pictures to
    re-cut a video nobody asked to change is thirteen minutes of GPU for nothing.

    Returns the same record shape ``run`` does, with ``reassembled: True``, so
    the manifest and the tab cannot tell the difference.
    """
    log_fn = log_fn or _log_noop
    t0 = time.time()
    rec = {'ok': False, 'reason': '', 'reassembled': True}
    sp = os.path.join(out_dir, 'storyboard.json')
    if not os.path.isfile(sp):
        rec['reason'] = 'no storyboard.json — nothing to reassemble from'
        return rec
    with open(sp, encoding='utf-8') as fh:
        board = json.load(fh)
    slots = board.get('slots') or []
    old = board.get('record') or {}
    paths = [os.path.join(out_dir, 'frames', f'f{s["i"]:03d}.png') for s in slots]
    have = sum(1 for p in paths if os.path.isfile(p))
    if not slots or not have:
        rec['reason'] = f'{len(slots)} slot(s), {have} frame(s) on disk'
        return rec
    log_fn(f'reassemble: {len(slots)} slots, {have} frames on disk')
    grid = {'beats': board.get('beats') or [], 'bar_beats': (old.get('storyboard') or {}).get('bar_beats', 4.0)}
    gate = gate_frames(paths, log_fn=log_fn)
    video, asm = build_video(slots, paths, audio_path, out_dir, log_fn=log_fn, grid=grid, should_abort=should_abort)
    # build_video seals what it writes; this is the belt that survives a refactor
    # of the assembly step, and costs one manifest read when the seal is already there.
    if video and os.path.isfile(video) and not _seal.is_sealed(video):
        _seal.seal(video, pipeline='kids_video', log_fn=log_fn)
    write_thumbs(paths, out_dir, log_fn=log_fn)
    pacing = dict(old.get('pacing') or {})
    if video and os.path.isfile(video):
        vdur = _duration(video)
        pacing['video_seconds'] = round(vdur, 2)
        pacing['pictures_shipped'] = asm['clips'] + asm['static']
        ver = verify_cuts(video, slots, asm.get('transitions') or [], log_fn=log_fn)
        pacing['cuts_visible'] = ver.get('cuts_visible')
        pacing['cuts_visible_pct'] = ver.get('visible_pct')
    else:
        ver = {}
    rec.update(
        {
            'ok': bool(video and os.path.isfile(video)),
            'file': os.path.basename(video) if video else None,
            'poster': ('poster.jpg' if os.path.isfile(os.path.join(out_dir, 'poster.jpg')) else None),
            'reason': asm.get('reason') or ('' if video else 'assembly produced no file'),
            'width': OUT_W,
            'height': OUT_H,
            'fps': FPS,
            'source_audio': os.path.basename(audio_path),
            'storyboard': old.get('storyboard') or {},
            'ideas': old.get('ideas') or {},
            'generation': old.get('generation') or {},
            'grid': old.get('grid') or {},
            'style': old.get('style') or '',
            'pacing': pacing,
            'gates': gate,
            'verify': ver,
            'assembly': {k: v for k, v in asm.items() if k != 'transitions'},
            'elapsed_s': round(time.time() - t0, 1),
        }
    )
    rec['vram'] = {'clip_released': release_clip(log_fn=log_fn)}
    board['record'] = rec
    board['transitions'] = asm.get('transitions') or []
    with open(sp, 'w', encoding='utf-8') as fh:
        json.dump(board, fh, indent=1)
    log_fn(
        f'reassemble: {"DELIVERED " + str(rec["file"]) if rec["ok"] else "FAILED — " + rec["reason"]}'
        f' in {rec["elapsed_s"]:.0f}s'
    )
    return rec


def run(plan, brief, audio_path, out_dir, *, log_fn=None, stage_fn=None, should_abort=None, opts=None):
    """Storyboard → pictures → measure → assemble.  Returns the video record.

    Never raises: a video that cannot be built is a video that is reported as not
    built, with the reason, and the song still ships.  ``ok`` is derived from
    whether an mp4 exists on disk, never from whether this function returned.
    """
    log_fn = log_fn or _log_noop
    stage = stage_fn or (lambda _s: None)
    abort = should_abort or (lambda: False)
    opts = dict(opts or {})
    t0 = time.time()
    rec = {'ok': False, 'reason': '', 'elapsed_s': 0.0}

    if not audio_path or not os.path.isfile(audio_path):
        rec['reason'] = 'no delivered audio to illustrate'
        log_fn(f'video: {rec["reason"]}')
        return rec

    # ── Storyboard
    stage('Storyboard')
    grid = beat_grid(audio_path, plan, log_fn=log_fn)
    media_s = grid['duration_s']
    if media_s < 3.0:
        rec['reason'] = f'delivered audio is only {media_s:.1f}s'
        log_fn(f'video: {rec["reason"]} — nothing to illustrate')
        return rec
    grid['bar_beats'] = float(plan.get('bar_beats') or 4.0)
    energy = rms_envelope(audio_path, log_fn=log_fn)
    seed = int(plan.get('seed') or 0)
    # No seed: the layout is fully determined by the song's own beat grid,
    # form and measured energy. Two runs of the same song cut in the same
    # places; only what the pictures SHOW is seeded.
    slots, sb = plan_slots(plan, grid, media_s, energy=energy, log_fn=log_fn)
    if not slots:
        rec['reason'] = 'the storyboard came out empty'
        return rec

    reuse = len(slots) > MAX_IMAGES
    if reuse:
        log_fn(
            f'storyboard: {len(slots)} slots exceeds the {MAX_IMAGES}-render '
            f'ceiling — repeated ideas will REUSE their picture (recorded '
            f'per slot in storyboard.json)'
        )
    _burst_pool, _fill_pool = motif_pools(brief)
    ideas = assign_ideas(slots, brief, plan, seed=seed, log_fn=log_fn)
    # The LLM is finished for this run; the GPU belongs to the pictures now.
    release_ollama(log_fn=log_fn)

    # The rate contract, measured on the plan before a single picture is made:
    # if this is already wrong there is no point spending eight minutes on it.
    starts = [s['start'] for s in slots]
    worst, at = min_per_window(starts, media_s)
    per5 = round(WINDOW_S * len(slots) / max(0.001, media_s), 3)
    _clip_each, _clip_total = clip_plan(slots, seed=seed)
    pacing = {
        'pictures': len(slots),
        'seconds': round(media_s, 2),
        'per_5s_mean': per5,
        'per_5s_worst_window': worst,
        'worst_window_at_s': at,
        'target_per_5s': TARGET_PER_5S,
        # The WORST window is a count of starts, so it is held to the integer
        # guarantee the ceiling actually makes — floor(5 / ceiling) — and not to
        # the fractional mean. Holding a count of 1 to a target of 1.18 failed a
        # layout that was exactly right, which is the kind of gate that teaches
        # an operator to ignore gates.
        'min_starts_per_5s': MIN_STARTS_PER_5S,
        'clip_s': CLIP_S,
        'max_slot_s': round(max(s['dur'] for s in slots), 3),
        'min_slot_s': round(min(s['dur'] for s in slots), 3),
        'slot_ceiling_s': MAX_SLOT_S,
        'slot_floor_s': MIN_SLOT_S,
        'slot_absorb_max_s': ABSORB_MAX_S,
        # Over the TARGET is normal and costs a second of clip; over what a clip
        # can COVER is a broken contract. Both are reported, only the second fails.
        'stretched': [s['i'] for s in slots if s['dur'] > MAX_SLOT_S + 1e-6],
        'over_ceiling': [s['i'] for s in slots if s['dur'] > ABSORB_MAX_S + 1e-6],
        # THE GPU BILL, from the plan. `clip_seconds_total / seconds` is the
        # number the 2026-10-02 rewrite exists to hold down: 54 two-second clips
        # covering a 57 s song rendered 1.8x the motion the song could use.
        'clip_seconds_each': _clip_each,
        'clip_seconds_total': _clip_total,
        'clip_overhead_x': round(_clip_total / max(0.001, media_s), 3),
        'image_renders': len(slots) * CANDIDATES,
        'ok': bool(
            per5 >= TARGET_PER_5S - 1e-3
            and (worst is None or worst >= MIN_STARTS_PER_5S)
            and not [s for s in slots if s['dur'] > ABSORB_MAX_S + 1e-6]
        ),
    }
    pacing['beat'] = beat_alignment(slots, grid['beats'])
    log_fn(
        f'pacing: {len(slots)} pictures over {media_s:.1f}s = {per5:.2f} per 5s '
        f'(worst 5s window: {worst}, floor {MIN_STARTS_PER_5S}) · longest picture '
        f'{pacing["max_slot_s"]:.2f}s against a {MAX_SLOT_S:.2f}s ceiling · '
        f'cuts land {pacing["beat"].get("median_ms", "?")} ms from a beat'
    )
    # What this layout costs, said before it is spent: one line an operator can
    # compare against the next song's.
    _hist = ', '.join(f'{_clip_each.count(c)}x{c}s' for c in sorted(set(_clip_each)))
    log_fn(
        f'pacing: the bill — {len(slots) * CANDIDATES} image render(s) and '
        f'{_clip_total}s of clip ({_hist}) for {media_s:.0f}s of song '
        f'({pacing["clip_overhead_x"]:.2f}x), roughly '
        f'{(_clip_total * _LTX_WALL_PER_CLIP_S) / 60.0:.0f} min of LTX'
    )
    if not pacing['ok']:
        log_fn(
            f'pacing: BELOW the {TARGET_PER_5S:.2f}-per-5s rate the '
            f'{MAX_SLOT_S:.2f}s ceiling implies — reported, not hidden'
        )

    # ── Pictures
    stage('Illustrate')
    # An estimate, said out loud before the eight minutes start rather than
    # after: the health probe stops deferring GUI restarts 45 minutes after a
    # run began, so an operator watching a long song should know what they are
    # committing to. The per-image figure is measured, and follows the model
    # actually in force: 2.2 s distilled, 13.5 s on the base.
    # Candidates double the renders; the screen (0.84 s median, measured) runs
    # beside them on its own worker, so it is counted once per candidate.
    _n_make = len(slots) if not reuse else min(len(slots), MAX_IMAGES)
    _per = _ETA_PER_IMAGE * CANDIDATES + (0.84 * CANDIDATES if SCREEN_ON and CANDIDATES > 1 else 0.0)
    _eta = _n_make * _per
    log_fn(
        f'images: {len(slots)} frame(s) to make'
        + (f', {CANDIDATES} candidates each, screened for defects' if CANDIDATES > 1 else '')
        + f' — roughly {_eta / 60.0:.0f} min '
        f'at the measured {_ETA_PER_IMAGE:.1f}s a render '
        f'({speed_note()})' + ('; the 45-minute in-flight ceiling is the limit to watch' if _eta > 1500 else '')
    )
    # Said out loud, in the run's own log, rather than only at import: a fast
    # run that silently fell back to the base model is the failure that looks
    # like nothing at all.
    for _w in _SPEED_WARNINGS:
        log_fn(f'images: {_w}')
    if abort():
        rec['reason'] = 'halted by operator before any picture was made'
        return rec
    paths, gen = render_images(slots, brief, out_dir, seed=seed, log_fn=log_fn, should_abort=should_abort, reuse=reuse)
    thumbs = write_thumbs(paths, out_dir, log_fn=log_fn)

    # ── Measure
    stage('Measure Frames')
    gate = gate_frames(paths, log_fn=log_fn)

    # ── Animate (every picture → an LTX-2.5 clip; the channel ships no stills)
    stage('Animate')
    anim = {'engine': 'ltx-2.5-distilled', 'clips': 0, 'failed': 0, 'reason': 'skipped'}
    if abort():
        rec['reason'] = 'halted by operator before the pictures were animated'
        return rec
    anim = animate_frames(slots, paths, out_dir, brief, seed=seed, log_fn=log_fn, should_abort=should_abort)
    log_fn(
        f'animate: {anim["clips"]}/{len(slots)} clip(s) in {anim.get("seconds", 0):.0f}s'
        + (f' — {anim["failed"]} slot(s) will ship as a still' if anim.get('failed') else '')
        + (f' — {anim["reason"]}' if anim.get('reason') else '')
    )

    # ── Assemble
    stage('Assemble Video')
    video, asm = build_video(
        slots, paths, audio_path, out_dir, seed=seed, log_fn=log_fn, grid=grid, should_abort=should_abort
    )

    # Re-measure the pacing on the FINISHED file: the assembly can drop a slot
    # whose frame never appeared, and the delivered rate is the one that counts.
    verify = {}
    if video and os.path.isfile(video):
        vdur = _duration(video)
        pacing['video_seconds'] = round(vdur, 2)
        pacing['audio_video_delta_s'] = round(vdur - media_s, 3)
        shipped = asm['clips'] + asm['static']
        pacing['pictures_shipped'] = shipped
        if vdur > 0:
            pacing['per_5s_shipped'] = round(WINDOW_S * shipped / vdur, 3)
        verify = verify_cuts(video, slots, asm.get('transitions') or [], log_fn=log_fn)
        pacing['cuts_visible'] = verify.get('cuts_visible')
        pacing['cuts_visible_pct'] = verify.get('visible_pct')

    rec.update(
        {
            'ok': bool(video and os.path.isfile(video)),
            'file': os.path.basename(video) if video else None,
            'poster': ('poster.jpg' if os.path.isfile(os.path.join(out_dir, 'poster.jpg')) else None),
            'reason': asm.get('reason') or ('' if video else 'assembly produced no file'),
            'width': OUT_W,
            'height': OUT_H,
            'fps': FPS,
            'source_audio': os.path.basename(audio_path),
            'storyboard': sb,
            'ideas': ideas,
            'generation': gen,
            'pacing': pacing,
            'gates': gate,
            'verify': verify,
            'animate': anim,
            'motion_coverage': asm.get('motion_coverage', 0.0),
            'kenburns': asm.get('kenburns', 0),
            'assembly': {k: v for k, v in asm.items() if k != 'transitions'},
            'grid': {k: v for k, v in grid.items() if k != 'beats'},
            'thumbnails': thumbs,
            # What the style decided, said out loud: the key, the colour clause it
            # contributed, and the two motif lists the storyboard was allowed to
            # draw from. Without these a styled video cannot be told from an
            # unstyled one after the fact.
            'style': brief.get('style'),
            'look': look_for(brief),
            'motif_pools': {'burst': list(_burst_pool), 'fill': list(_fill_pool)},
            'style_prompt': style_for(brief),
            'elapsed_s': round(time.time() - t0, 1),
        }
    )

    # Everything this leg put on the GPU comes off it before the leg returns:
    # ComfyUI's weights in render_images' finally, the CLIP scorer here. Recorded
    # rather than assumed — a run that could not free the card must say so.
    rec.setdefault('vram', {})
    rec['vram']['comfy'] = (gen or {}).get('vram') or {}
    rec['vram']['clip_released'] = release_clip(log_fn=log_fn)

    with open(os.path.join(out_dir, 'storyboard.json'), 'w') as fh:
        json.dump(
            {
                'kind': 'kidsvideo',
                'version': 1,
                'title': brief.get('title') or brief.get('theme'),
                'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'record': rec,
                'transitions': asm.get('transitions') or [],
                'beats': [round(b, 4) for b in grid['beats']],
                'slots': slots,
            },
            fh,
            indent=1,
        )

    log_fn(
        f'video: {"DELIVERED " + str(rec["file"]) if rec["ok"] else "NOT built — " + rec["reason"]}'
        f' in {rec["elapsed_s"]:.0f}s'
    )
    return rec
