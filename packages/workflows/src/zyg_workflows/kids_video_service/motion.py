# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Motion: the Ken Burns pass and the LTX-2.5 clip per picture (2026-10-02).

Moved verbatim out of the old single-file kids_video_service.py (lines 3333-3689).
"""

from __future__ import annotations

import os
import subprocess
import time
from zyg_workflows.bin import exe

from zyg_workflows.kids_video_service.constants import (
    FPS,
    KB_ZOOM,
    OUT_H,
    OUT_W,
    PULSE_AMP,
    PULSE_S,
    _log_noop,
    _zyg_log,
)
from zyg_workflows.kids_video_service.motifs import (
    BASE_STYLE,
    style_for,
)
from zyg_workflows.kids_video_service.transitions import (
    _xfade_graph,
    transitions_for,
)


# ── Motion ───────────────────────────────────────────────────────────────────


def run_ffmpeg(cmd, timeout, should_abort=None, poll=0.5):
    """ffmpeg that a halt can actually stop.

    ``subprocess.run`` cannot be interrupted: the slideshow pass over fifty-odd
    1080p inputs carries a 30-minute timeout, so an operator pressing stop during
    assembly would have left an ffmpeg chewing the box for up to half an hour
    after the job card went red — a leftover process by any reasonable
    definition.  This polls the halt flag while it waits and terminates the child
    (SIGTERM, then SIGKILL) when one arrives.

    Deliberately NOT wired to ``subproc_registry``: that module imports
    crewai_web_gui and cannot be imported outside the GUI, and this module has a
    CLI.  The property that matters — a halted run leaves nothing running — is
    provided here without that dependency.

    Returns the CompletedProcess-ish tuple (returncode, stderr_bytes).
    """
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    abort = should_abort or (lambda: False)
    deadline = time.time() + float(timeout)
    try:
        while True:
            try:
                p.wait(timeout=poll)
                break
            except subprocess.TimeoutExpired as _exc:
                _zyg_log.debug('child still running after the %ss poll window: %s', poll, _exc)
            if abort() or time.time() > deadline:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=10)
                return -1, (b'halted' if abort() else b'timed out')
    except Exception:  # noqa: BLE001
        try:
            p.kill()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('child kill during cleanup skipped: %s', _exc)
        raise
    return p.returncode, (p.stderr.read() if p.stderr else b'')


def _nvenc_args(cq=18, preset='p4'):
    # cq 18 on the INTERMEDIATE motion clips, not 20: they are re-encoded by the
    # xfade pass, and noise introduced here is noise the final encoder then
    # spends bits preserving.
    return ['-c:v', 'h264_nvenc', '-preset', preset, '-rc', 'vbr', '-cq', str(cq), '-b:v', '0', '-pix_fmt', 'yuv420p']


def _x264_args(crf=21, preset='medium', tune='animation'):
    """``-tune animation`` is not decoration: flat cartoon is exactly what it is
    for (stronger deblocking, more reference frames for large flat areas).

    Measured on the first illustrated song, 50 s at 1080p24: crf 19 untuned came
    out at 70 MB, crf 21 tuned at 60 MB, and preset slow bought only 3 MB more
    for twice the CPU.  The remaining bitrate is inherent — a slow zoom over a
    large smooth sky gradient changes every pixel of every frame — so this is
    where the curve flattens, not a number picked for the sake of it.
    """
    a = ['-c:v', 'libx264', '-preset', preset, '-crf', str(crf)]
    if tune:
        a += ['-tune', tune]
    return a + ['-pix_fmt', 'yuv420p']


def _clip_to_slot(clip_path, out_path, dur, *, w=OUT_W, h=OUT_H, fps=FPS):
    """Cut an LTX motion clip to the slot: scale/crop to the frame, hold the last
    frame if the clip is shorter, drop its audio (the song is the audio)."""
    vf = (
        f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},'
        f'fps={fps},tpad=stop_mode=clone:stop_duration={dur:.3f}'
    )
    base = [exe('ffmpeg'), '-y', '-i', clip_path, '-vf', vf, '-t', f'{dur:.3f}', '-an']
    for args in (
        (_nvenc_args(),) if os.environ.get('ZYG_KIDSVIDEO_CPU_ENCODE', '').strip() not in ('1', 'true', 'yes') else ()
    ) + (_x264_args(crf=17, preset='veryfast', tune=None),):
        try:
            r = subprocess.run(
                base + args + [out_path],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=max(60, int(dur * 20) + 60),
            )
            if r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return True
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('ffmpeg encode attempt failed, falling through to the next variant: %s', _exc)
    return False


def _render_motion(img_path, out_path, slot, pulses, *, w=OUT_W, h=OUT_H, fps=FPS, clip_path=None):
    """One slot as a short clip.  Returns 'ltx' when the slot's LTX-2.5 motion clip
    was used, 'kenburns' for the still-with-a-move fallback, False on failure.

    Since 2026-10-02 every picture is animated by LTX-2.5 first (``animate_frames``);
    the Ken Burns move below only ships when a slot has no usable clip, and the
    assembly record says how many did.

    Ken Burns: a gentle move plus a beat pulse.

    The pulse is a 1.5 % zoom bump that decays over 220 ms from each bar
    downbeat.  It is what makes a still picture feel like it is listening: on a
    burst run the CUT already carries the beat, and everywhere else this does.
    """
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        img = Image.open(img_path).convert('RGB')
    except Exception:  # noqa: BLE001
        return False
    IW, IH = img.size
    dur = max(0.05, float(slot['dur']))
    if clip_path and os.path.isfile(clip_path):
        if _clip_to_slot(clip_path, out_path, dur, w=w, h=h, fps=fps):
            return 'ltx'
    n = max(2, int(round(dur * fps)))
    idx = int(slot.get('i', 0))

    # Move: alternate push-in / pull-out / drift so consecutive pictures do not
    # all breathe the same way. A burst slot is too short to move — it holds.
    if slot.get('burst'):
        motion, amp = 'hold', 0.0
    else:
        motion = ('push_in', 'pan_r', 'pull_out', 'pan_l')[idx % 4]
        amp = KB_ZOOM * (0.7 if slot.get('pace') == 'double' else 1.0)
    z_base = 1.0 + amp

    try:
        EXTENT = Image.Transform.EXTENT
        BIC = Image.Resampling.BICUBIC
    except AttributeError:  # Pillow < 9
        EXTENT = Image.EXTENT  # type: ignore[attr-defined]
        BIC = Image.BICUBIC  # type: ignore[attr-defined]

    pre = [exe('ffmpeg'), '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}', '-r', str(fps), '-i', 'pipe:0']
    cmd_gpu = pre + _nvenc_args() + [out_path]
    # The motion clip is an INTERMEDIATE: fast and near-lossless beats small,
    # because the xfade pass re-encodes it anyway.
    cmd_cpu = pre + _x264_args(crf=17, preset='veryfast', tune=None) + [out_path]

    def _pulse(t_abs):
        if PULSE_AMP <= 0 or not pulses:
            return 0.0
        best = 0.0
        for b in pulses:
            d = t_abs - b
            if 0.0 <= d <= PULSE_S:
                e = 1.0 - (d / PULSE_S)
                best = max(best, e * e)
            elif b > t_abs:
                break
        return best * PULSE_AMP

    def _run(cmd):
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for k in range(n):
                prog = k / (n - 1) if n > 1 else 0.0
                if motion == 'push_in':
                    z = 1.0 + amp * prog
                elif motion == 'pull_out':
                    z = z_base - amp * prog
                else:
                    z = z_base
                z *= 1.0 + _pulse(float(slot['start']) + prog * dur)
                z = max(1.0, z)
                vw, vh = IW / z, IH / z
                if motion == 'pan_r':
                    cx = vw / 2 + (IW - vw) * prog
                elif motion == 'pan_l':
                    cx = IW - vw / 2 - (IW - vw) * prog
                else:
                    cx = IW / 2
                cy = IH / 2
                left = max(0.0, min(cx - vw / 2, IW - vw))
                top = max(0.0, min(cy - vh / 2, IH - vh))
                frame = img.transform((w, h), EXTENT, (left, top, left + vw, top + vh), resample=BIC)
                p.stdin.write(frame.tobytes())
            p.stdin.close()
            p.wait(timeout=max(60, int(dur * 20) + 30))
            return p.returncode == 0
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('ffmpeg kill after timeout skipped: %s', _exc)
            return False

    if os.environ.get('ZYG_KIDSVIDEO_CPU_ENCODE', '').strip() in ('1', 'true', 'yes'):
        return 'kenburns' if _run(cmd_cpu) else False
    return 'kenburns' if (_run(cmd_gpu) or _run(cmd_cpu)) else False


# ── Motion: every picture becomes an LTX-2.5 clip (2026-10-02) ───────────────
#
# The channel ships no stills.  After the frames are measured, each one is the
# first frame of a short LTX-2.5 image-to-video run on the second ComfyUI
# (:8189); the assembly cuts that clip to the slot instead of moving a still.
# Measured 2026-10-02: a 3 s clip at 1280x704 is ~15 s on the 4090, so a
# 50-picture song is ~13 minutes of motion.  The clip keeps the first frame
# pixel-exact, which is why drawn counting cards can go through it too.

# Wall seconds per second of rendered clip, measured on this 4090 at 0.9 MP. Not a
# per-clip figure: a 10 s clip is one render, not five. Receipt — job
# f28b3396cfdb, a 59.9 s song: 54 clips, 119 clip-seconds, 709.2 s of animate
# (5.96 s per clip-second). The standalone runs agree: 5 s = 43 s, 10 s = 57 s.
_LTX_WALL_PER_CLIP_S = float(os.environ.get('ZYG_KIDSVIDEO_LTX_ETA_S', '5.96'))

_MOTION_HINTS = {
    'count_up': 'the objects bob gently up and down in place, nothing is added or removed',
    'count_down': 'the objects bob gently up and down in place, nothing is added or removed',
    'shapes': 'the shapes bob and turn slowly in place',
    'colours': 'everything sways gently in place',
    'toys': 'the toy wobbles playfully and bounces once',
    'animals': 'the animal blinks, wags and takes one small hop',
    'weather': 'the clouds drift slowly and the sun rays twinkle',
    'dance': 'the characters bounce and clap to the beat',
    'grow': 'the plant sways gently in a light breeze',
    'journey': 'moves slowly across the scene from left to right',
    'peekaboo': 'the character peeks out and waves',
}
_MOTION_DEFAULT = 'gentle playful motion, the main character moves a little and smiles'


def motion_prompt(brief, slot):
    """The LTX prompt for one slot: keep the first frame's style and contents, add
    a small motion that suits the motif, camera still so the cut stays on the beat."""
    style = style_for(brief) if brief is not None else BASE_STYLE
    style = str(style).strip().rstrip('.,')
    idea = str(slot.get('idea') or '').strip().rstrip('.,')
    hint = _MOTION_HINTS.get(str(slot.get('motif') or ''), _MOTION_DEFAULT)
    if slot.get('draw') and (slot['draw'] or {}).get('kind') == 'count':
        hint = _MOTION_HINTS['count_up']
    return (
        f'Use the provided start image as the first frame. {style}. {idea}. {hint}. '
        f'The camera stays still. Keep the exact flat cartoon style, colours, outlines '
        f'and every object of the first frame; nothing is added or removed. No text.'
    )


def motion_clip_for(slot, out_dir):
    """The slot's LTX clip on disk, or None (then the assembly moves the still)."""
    m = slot.get('motion') or {}
    cands = []
    if m.get('file'):
        cands.append(os.path.join(out_dir, m['file']))
    try:
        cands.append(os.path.join(out_dir, 'frames', f'v{int(slot.get("i", -1)):03d}.mp4'))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('slot index not numeric, motion-clip candidate skipped: %s', _exc)
    for c in cands:
        if os.path.isfile(c) and os.path.getsize(c) > 0:
            return c
    return None


def animate_frames(slots, paths, out_dir, brief, *, seed=0, log_fn=None, should_abort=None, trans=None):
    """One LTX-2.5 clip per frame → frames/v###.mp4.  Returns the stage record.

    A failed clip is retried once with a new seed.  A slot that still has no
    clip is left to the assembly's Ken Burns fallback and COUNTED — the record's
    ``kenburns`` is the number the operator reads.
    """
    log_fn = log_fn or _log_noop
    abort = should_abort or (lambda: False)
    info = {
        'engine': 'ltx-2.5-distilled',
        'clips': 0,
        'failed': 0,
        'retries': 0,
        'skipped': 0,
        'seconds': 0.0,
        'clip_seconds_total': 0,
        'aborted': False,
        'available': False,
        'reason': '',
    }
    try:
        from zyg_workflows import ltx_hidream_service as LH
    except Exception as e:  # noqa: BLE001
        info['reason'] = f'ltx_hidream_service unavailable ({type(e).__name__}: {e})'
        log_fn(f'animate: {info["reason"]} — pictures stay stills')
        return info
    if not LH.ensure_up(log_fn=log_fn):
        info['reason'] = 'ComfyUI :8189 unavailable'
        log_fn('animate: the LTX server is down — pictures stay stills')
        return info
    info['available'] = True
    trans = trans if trans is not None else transitions_for(slots, seed=seed)
    try:
        _graph, lens = _xfade_graph(slots, trans, len(slots))
    except Exception:  # noqa: BLE001
        lens = [float(s.get('dur') or 1.0) for s in slots]
    fdir = os.path.join(out_dir, 'frames')
    os.makedirs(fdir, exist_ok=True)
    t0 = time.time()
    n = len(slots)
    est = sum(LH.clip_seconds(ln) for ln in lens)
    # MEASURED, not a per-clip constant: wall time tracks the clip's LENGTH, so an
    # estimate built on "15 s a clip" was wrong by 3x the moment the clips grew.
    # See _LTX_WALL_PER_CLIP_S for the receipt it is taken from.
    eta = est * _LTX_WALL_PER_CLIP_S
    log_fn(
        f'animate: {n} clip(s), {est} s of motion to make — roughly '
        f'{eta / 60.0:.0f} min at the measured {_LTX_WALL_PER_CLIP_S:.1f} s of wall '
        f'per second of clip'
    )
    with LH.gpu_lease(abort, log_fn=log_fn):
        for k, (s, p) in enumerate(zip(slots, paths)):
            if abort():
                info['aborted'] = True
                log_fn(f'animate: halt requested after {info["clips"]} clip(s)')
                break
            if not p or not os.path.isfile(p):
                info['skipped'] += 1
                continue
            out = os.path.join(fdir, f'v{int(s.get("i", k)):03d}.mp4')
            secs = LH.clip_seconds(lens[k] if k < len(lens) else float(s.get('dur') or 1.0))
            prompt = motion_prompt(brief, s)
            base_seed = (int(seed) * 7919 + int(s.get('i', k)) * 104729 + 11) & 0xFFFFFFFF
            ok = False
            for attempt in range(2):
                sd = base_seed + attempt * 1000003
                tc = time.time()
                ok = LH.ltx_i2v(p, prompt, out, seconds=secs, seed=sd, log_fn=log_fn, should_abort=abort)
                if ok:
                    s['motion'] = {
                        'file': os.path.relpath(out, out_dir),
                        'seconds': secs,
                        'seed': sd,
                        'engine': info['engine'],
                        'wall_s': round(time.time() - tc, 1),
                        'attempt': attempt + 1,
                    }
                    info['clips'] += 1
                    info['clip_seconds_total'] += secs
                    break
                info['retries'] += 1
                log_fn(f'animate: slot {s.get("i", k)} clip failed (attempt {attempt + 1})')
            if not ok:
                info['failed'] += 1
            if (k + 1) % 10 == 0 or k + 1 == n:
                log_fn(
                    f'animate: {k + 1}/{n} done ({info["clips"]} clips, '
                    f'{info["failed"]} failed) in {time.time() - t0:.0f}s'
                )
    info['seconds'] = round(time.time() - t0, 1)
    return info
