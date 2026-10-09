# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Documentary stills → LTX-2.5 motion clips, and the picture count that follows from them.

Why this module exists (2026-10-02)
-----------------------------------
Stage 6 used to animate every still with a PIL Ken Burns move: a bicubic pan/zoom
over a dead photograph.  LTX-2.5 on :8189 can instead render the slot as real
video, so the picture moves the way a filmed shot moves.  Two things follow from
that, and they are both in here:

1. **The picture count is now DERIVED, not hardcoded.**  The old rule was
   ``max(10, int(duration / 20))`` written out twice in pipeline_scholarly.  One
   picture now becomes exactly one clip, so the count is whatever covers the
   narration at the clip length — no surplus, and no 10-picture floor on a
   two-minute episode (that floor was handing a 60 s run ten pictures of 6 s).

2. **The clip length is bounded by VRAM, and the bound is measured.**  On the
   4090 at 1280x704 (16:9, 0.9 MP) peak VRAM was 43.5 GB at 10 s, 46.1 GB at
   15 s and **47.9 GB of 49.1 GB at 20 s** — so 20 s is the ceiling, not a taste
   setting.  Wall time was 68.3 / 91.1 / 132.7 s, i.e. ~6.5 s of wall per second
   of clip.  ``ZYG_SCHOLARLY_CLIP_S`` moves the target slot; it is clamped to
   that ceiling because exceeding it OOMs mid-episode.

The prompt matters more than the length, and the camera must not be in it
---------------------------------------------------------------------------
A loose motion prompt does not merely drift — it INVENTS.  Measured on a real
documentary still of two men shouting nose to nose: with a generic "the scene is
alive with subtle natural motion" prompt, LTX had them kissing by second four and
held it for the rest of the clip.

Asking LTX for the camera move does not work either, and this was measured twice.
On a crowd still, a prompt that said "a slow steady push toward the centre"
pulled the camera BACK instead and filled the revealed area with dozens of
invented, deformed faces.  Restating it as "the framing grows TIGHTER ... NEVER
pulls back, NEVER widens, NEVER zooms out" failed in exactly the same direction —
at CFG 1 there is no negative prompt and bare negations carry almost no weight.

So the two jobs are split, and that is the whole design:

  * **LTX is asked for a LOCKED-OFF camera** and nothing else — breathing, hair,
    cloth, dust, a flicker in the light.  Measured on the same crowd still that
    broke both push-in attempts, the locked prompt held all 20 s: same framing,
    same man, same crowd, nothing invented.
  * **The camera move is added afterwards by ffmpeg** (``render_move``), as a
    crop into pixels that already exist.  A crop cannot hallucinate, it is
    deterministic, it costs ~2.4 s a clip, and it is the same Ken Burns grammar
    Stage 6 used to apply to a dead still — only now the picture underneath it
    is alive.

See [[project-ltx25-instance]] for the engine, [[project-documentary-runtime-profile]]
for what Stage 3.5/6 cost before this.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from zyg_workflows.bin import exe
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── The slot/clip contract ───────────────────────────────────────────────────
# CLIP_S is the SCREEN TIME one picture holds.  The rendered clip is a little
# longer (TRANSITION_S) because Stage 6's xfade eats its overlap out of the
# timeline, so a clip cut exactly to the slot would come up short and loop.
CLIP_MAX_S = 20.0  # measured VRAM ceiling at 1280x704 — see the docstring
CLIP_MIN_S = 4.0
TRANSITION_S = 1.0  # xfade headroom the clip must carry on top of its slot
MIN_IMAGES = 3

# Measured 2026-10-02 over 10/15/20 s clips: 68.3/91.1/132.7 s wall.
WALL_PER_CLIP_SECOND = 6.5

OUT_W, OUT_H, OUT_FPS = 1920, 1080, 30
LTX_ASPECT = '16:9 (Widescreen)'
LTX_MEGAPIXELS = 0.9  # 1280x704 — the largest that fits a 20 s clip

MANIFEST_REL = os.path.join('ltx_clips', 'ltx_manifest.json')


def _log_noop(_m):
    return None


def enabled() -> bool:
    """LTX motion is on unless the operator turns it off for a run."""
    return os.environ.get('ZYG_SCHOLARLY_LTX', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def clip_target_s() -> float:
    """Seconds of screen time one picture holds, clamped to what LTX can render."""
    try:
        v = float(os.environ.get('ZYG_SCHOLARLY_CLIP_S', str(CLIP_MAX_S)))
    except (TypeError, ValueError):
        v = CLIP_MAX_S
    return max(CLIP_MIN_S, min(CLIP_MAX_S, v))


def n_images_for(duration_s: float) -> int:
    """How many pictures an episode of ``duration_s`` actually needs.

    One picture = one clip, so this is just "how many clip-length slots fit".
    ``ceil`` not ``int``: rounding down makes the last slot longer than the clip
    ceiling, which is exactly the case that OOMs.
    """
    try:
        d = float(duration_s)
    except (TypeError, ValueError):
        d = 0.0
    if d <= 0:
        return MIN_IMAGES
    return max(MIN_IMAGES, int(math.ceil(d / clip_target_s())))


def clip_seconds(slot_s: float) -> int:
    """Whole seconds to render so a clip covers its slot plus the xfade overlap."""
    try:
        s = float(slot_s)
    except (TypeError, ValueError):
        s = clip_target_s()
    return max(2, min(int(CLIP_MAX_S), int(math.ceil(s + TRANSITION_S))))


# ── The prompt ───────────────────────────────────────────────────────────────
# Nothing in here asks for a camera move; see the module docstring for the two
# measurements that took it out.  Everything is stated POSITIVELY — the distilled
# graph runs at CFG 1, so a negation is nearly free for the model to ignore.
_HOLD = (
    'The scene is held exactly as photographed: every person keeps the same pose, '
    'the same expression and the same position, nobody moves toward or away from '
    'anyone else, nobody turns, and no new action of any kind begins or ends.'
)
_LOCKED = (
    'The camera is locked off on a tripod and does not move at all: the framing, '
    'the crop and the perspective are identical in every single frame, exactly as '
    'in the first frame. Nothing enters or leaves the frame. No extra people, no '
    'extra faces, no extra hands and no extra objects appear anywhere at any point.'
)
_ALIVE = (
    'The only life in the frame is the faintest: shallow breathing, a few strands '
    'of hair and folds of cloth stirring, dust, smoke and haze moving slowly '
    'through the light.'
)
_KEEP = (
    'Identical photographic style, identical colours, identical lighting and '
    'identical faces from the first frame to the last. One continuous take. '
    'No cut, no text, no caption, no watermark.'
)


def motion_prompt(entry: dict) -> str:
    """The LTX prompt for one documentary slot: a locked-off hold, not a re-staging.

    The camera is deliberately absent from this prompt. ``render_move`` puts it
    back afterwards, where it cannot invent anything.
    """
    subject = str((entry or {}).get('subject') or '').strip().rstrip('.,')
    of = f' of {subject}' if subject else ''
    return (
        f'Use the provided image as the first frame of an archival documentary '
        f'shot{of}. {_HOLD} {_LOCKED} {_ALIVE} {_KEEP}'
    )


# ── Encoders ─────────────────────────────────────────────────────────────────


def _nvenc_args():
    try:
        from zyg_workflows.encode_utils import _cq_for_crf, _nvenc_vcodec_args  # noqa: PLC0415

        return _nvenc_vcodec_args(_cq_for_crf(17), 'p4')
    except Exception:  # noqa: BLE001
        return ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '21']


def _x264_args():
    try:
        from zyg_workflows.encode_utils import _x264_vcodec_args  # noqa: PLC0415

        return _x264_vcodec_args(17, 'veryfast')
    except Exception:  # noqa: BLE001
        return ['-c:v', 'libx264', '-crf', '17', '-preset', 'veryfast']


# ── The camera move, added where it cannot invent ────────────────────────────
# A Ken Burns grammar over the LTX clip: zoom is a CROP into pixels that already
# exist, so unlike a prompted camera move it can only ever show less, never make
# something up.  Direction alternates so a 50-shot episode does not push in fifty
# times, and the centre is biased toward the slot's focal zone exactly as the PIL
# renderer it replaces did.
ZOOM = 0.10  # 10 % travel over the clip — a documentary creep
_WORK_W, _WORK_H = 2560, 1408  # zoompan rounds its crop offsets to whole pixels;
# working at 2x keeps the creep from stepping

_FOCAL_X = {'left': 0.38, 'center': 0.5, 'centre': 0.5, 'right': 0.62}


def move_for(index: int, focal_zone: str = 'center') -> tuple:
    """(z_start, z_end, x_fraction) for one slot's camera move."""
    fx = _FOCAL_X.get(str(focal_zone or 'center').strip().lower(), 0.5)
    if index % 2:
        return (1.0 + ZOOM, 1.0, fx)  # pull out
    return (1.0, 1.0 + ZOOM, fx)  # push in


def _zoompan_vf(seconds: float, index: int, focal_zone: str, *, w=OUT_W, h=OUT_H, fps=OUT_FPS) -> str:
    z0, z1, fx = move_for(index, focal_zone)
    frames = max(1, int(round(float(seconds) * fps)))
    # 'on' is the output frame number; clamp so the last frames never overshoot.
    z = f'{z0:.4f}+({z1 - z0:.4f})*min(on/{frames},1)'
    return (
        f'fps={fps},scale={_WORK_W}:{_WORK_H}:flags=lanczos,'
        f"zoompan=z='{z}':d=1:"
        f"x='(iw-iw/zoom)*{fx:.3f}':y='(ih-ih/zoom)/2':"
        f's={w}x{h}:fps={fps},setsar=1'
    )


def render_move(
    src: str, dst: str, *, seconds: float, index: int = 0, focal_zone: str = 'center', w=OUT_W, h=OUT_H, fps=OUT_FPS
) -> bool:
    """LTX clip → the frame Stage 6 assembles, with the camera move baked in.

    LTX ships 1280x704 at 24 fps with an audio track; Stage 6 xfades 1920x1080
    video at 30 fps.  This resamples, applies the move, and drops the audio (the
    narration is the audio).  Measured 2.4 s for a 20 s clip.
    """
    vf = _zoompan_vf(seconds, index, focal_zone, w=w, h=h, fps=fps)
    base = [exe('ffmpeg'), '-y', '-v', 'error', '-i', src, '-vf', vf, '-an']
    for args in (_nvenc_args(), _x264_args()):
        try:
            r = subprocess.run(base + args + [dst], capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
            if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 10_000:
                return True
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('motion render command failed, trying the next variant: %s', _exc)
    return False


# ── The stage ────────────────────────────────────────────────────────────────


def animate_stills(images, out_dir, *, durations=None, total_s=0.0, seed=0, log_fn=None, should_abort=None):
    """One LTX-2.5 clip per picture → ``ltx_clips/`` + a manifest Stage 6 reads.

    ``images`` is the Stage 6 slide order: dicts carrying at least ``path``, and
    ideally ``subject``/``shot_type`` for the prompt.  ``durations`` is the slot
    length per picture when the caller knows it (Stage 6's inflated grid);
    otherwise the narration is split evenly.

    A failed clip is retried once with a fresh seed.  A picture that still has no
    clip keeps its Ken Burns move in Stage 6 and is COUNTED — ``kenburns`` in the
    record is the number the operator reads, never hidden.
    """
    log_fn = log_fn or _log_noop
    abort = should_abort or (lambda: False)
    n = len(images or [])
    rec = {
        'engine': 'ltx-2.5-distilled',
        'available': False,
        'reason': '',
        'pictures': n,
        'clips': 0,
        'failed': 0,
        'retries': 0,
        'skipped': 0,
        'kenburns': 0,
        'motion_coverage': 0.0,
        'clip_seconds_total': 0,
        'seconds': 0.0,
        'aborted': False,
        'manifest': '',
    }
    if not n:
        rec['reason'] = 'no pictures to animate'
        return rec
    if not enabled():
        rec['reason'] = 'ZYG_SCHOLARLY_LTX=0 — Ken Burns kept'
        rec['kenburns'] = n
        log_fn(f'motion: disabled by env — {n} picture(s) stay Ken Burns')
        return rec
    try:
        from zyg_workflows import ltx_hidream_service as LH  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        rec['reason'] = f'ltx_hidream_service unavailable ({type(e).__name__}: {e})'
        rec['kenburns'] = n
        log_fn(f'motion: {rec["reason"]} — Ken Burns kept')
        return rec
    if not LH.ensure_up(log_fn=log_fn):
        rec['reason'] = 'ComfyUI :8189 unavailable'
        rec['kenburns'] = n
        log_fn('motion: the LTX server is down — Ken Burns kept')
        return rec
    rec['available'] = True

    if durations and len(durations) == n:
        slots = [float(d) for d in durations]
    else:
        per = (float(total_s) / n) if total_s else clip_target_s()
        slots = [per] * n

    cdir = os.path.join(out_dir, 'ltx_clips')
    os.makedirs(cdir, exist_ok=True)
    manifest_path = os.path.join(out_dir, MANIFEST_REL)
    rec['manifest'] = manifest_path

    budget = sum(clip_seconds(s) for s in slots)
    log_fn(
        f'motion: {n} picture(s) → {budget}s of LTX-2.5 video, roughly '
        f'{budget * WALL_PER_CLIP_SECOND / 60.0:.0f} min at the measured '
        f'{WALL_PER_CLIP_SECOND:.1f}s of wall per second of clip'
    )

    entries = []
    t0 = time.time()
    with LH.gpu_lease(abort, log_fn=log_fn):
        for i, img in enumerate(images):
            if abort():
                rec['aborted'] = True
                log_fn(f'motion: halt requested after {rec["clips"]} clip(s)')
                break
            src = (img or {}).get('path') or ''
            if not src or not os.path.isfile(src):
                rec['skipped'] += 1
                continue
            secs = clip_seconds(slots[i])
            raw = os.path.join(cdir, f'raw_{i:03d}.mp4')
            dst = os.path.join(cdir, f'clip_{i:03d}.mp4')
            prompt = motion_prompt(img)
            base_seed = (int(seed) * 7919 + i * 104729 + 11) & 0xFFFFFFFF
            ok = False
            for attempt in range(2):
                sd = base_seed + attempt * 1000003
                tc = time.time()
                ok = LH.ltx_i2v(
                    src,
                    prompt,
                    raw,
                    seconds=secs,
                    seed=sd,
                    aspect=LTX_ASPECT,
                    megapixels=LTX_MEGAPIXELS,
                    log_fn=log_fn,
                    should_abort=abort,
                    timeout_s=max(900.0, secs * 40.0),
                )
                if ok and render_move(
                    raw, dst, seconds=secs, index=i, focal_zone=(img or {}).get('focal_zone', 'center')
                ):
                    entries.append(
                        {
                            'path': dst,
                            'source_image': src,
                            'index': i,
                            'seconds': secs,
                            'slot_s': round(slots[i], 2),
                            'seed': sd,
                            'engine': rec['engine'],
                            'attempt': attempt + 1,
                            'wall_s': round(time.time() - tc, 1),
                        }
                    )
                    rec['clips'] += 1
                    rec['clip_seconds_total'] += secs
                    ok = True
                    break
                ok = False
                rec['retries'] += 1
                log_fn(f'motion: picture {i} clip failed (attempt {attempt + 1})')
            try:
                if os.path.exists(raw):
                    os.remove(raw)
            except OSError as _exc:
                _zyg_log.debug('raw clip %s cleanup skipped: %s', raw, _exc)
            if not ok:
                rec['failed'] += 1
            if (i + 1) % 5 == 0 or i + 1 == n:
                log_fn(
                    f'motion: {i + 1}/{n} done ({rec["clips"]} clips, '
                    f'{rec["failed"]} failed) in {time.time() - t0:.0f}s'
                )

    rec['kenburns'] = n - rec['clips']
    rec['motion_coverage'] = round(rec['clips'] / float(n), 4) if n else 0.0
    rec['seconds'] = round(time.time() - t0, 1)
    try:
        with open(manifest_path, 'w', encoding='utf-8') as fh:
            json.dump(entries, fh, indent=2)
    except OSError as e:
        log_fn(f'motion: manifest write failed: {e}')
    log_fn(
        f'motion: {rec["clips"]}/{n} pictures animated '
        f'(coverage {rec["motion_coverage"]:.2f}, {rec["kenburns"]} Ken Burns) '
        f'in {rec["seconds"] / 60.0:.1f} min'
    )
    return rec
