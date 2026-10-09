# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""lipsync_service.py — audio-driven mouth for a character shot (2026-09-15).

Takes a rendered character clip (or the canon still) plus a speech wav and returns
an mp4 in which the mouth is driven by that audio, so a shot's dialogue or scream
has a face. InfiniteTalk (the audio-conditioning module for Wan2.1-I2V-14B-480P)
runs inside the ComfyUI-WanVideoWrapper; the graph is
``_comfy_workflows/infinitetalk_i2v.json`` and is submitted through _comfy_client.

FAIL-SAFE CONTRACT — the same one sam3d_body_service.py uses. Every failure mode
(ComfyUI down, missing wav, rejected graph, timeout, ffmpeg error) returns None and
logs; nothing raises out of :func:`lipsync`, so the caller degrades to the silent
take it already had.

FPS. InfiniteTalk generates at **25 fps** — that is baked into the wav2vec embedding
window, not a preference, so the graph always samples at 25. When the source is a
video whose own fps is something else (the house Wan clips are 17 fps), the result
is resampled to the source's fps with ffmpeg ``-filter:v fps=`` and the receipt
records both numbers. An image source has no fps of its own and keeps 25. The take
is also cut back to the wav's duration: InfiniteTalk pads the last sampling window
(a 3.00 s line returns 81 frames = 3.24 s), so without the trim the muxed video
would outrun the speech that drove it.

IMAGE MODE ONLY. The wrapper also ships a V2V InfiniteTalk example, but it is built
on VHS_LoadVideo / VHS_VideoCombine and ComfyUI-VideoHelperSuite is not installed on
this box (checked against /object_info). A video source is therefore handled by
extracting its first frame with ffmpeg and driving image mode from it: the mouth is
audio-driven, the body motion is re-generated rather than preserved.

LOADER CONSTRAINT — why the graph carries a LoRA node. The InfiniteTalk module on
disk is the fp8 *scaled* repack: its 120 audio_cross_attn weights are fp8 and each
carries a .scale_weight (mean 0.0865), so unscaled they are an order of magnitude
too large and the take comes back as pure noise — measured, take 1. The wrapper
applies those scales in exactly one place, ``custom_linear._replace_linear``, and
``nodes_model_loading.loadmodel`` reaches it only when the quantization string
contains "_scaled" **or** a LoRA is attached unmerged. "_scaled" is rejected up
front (the guard at nodes_model_loading.py:1222 inspects the base state dict, and
Wan2_1-I2V-14B-480P_fp8_e4m3fn is not a scaled file), and no scaled Wan2.1-I2V base
is on this box. So the graph attaches the character LoRA with merge_loras=false:
it is wanted anyway for identity, and it is what makes the audio cross-attention
weights arrive correctly scaled. Swap it per character via ``lora=``; drop it only
together with an unscaled InfiniteTalk module.

WEIGHTS / LICENCE. Base Wan2_1-I2V-14B-480P_fp8_e4m3fn (Apache-2.0, already in
model_licences.json), InfiniteTalk single fp8 scaled and wav2vec2-chinese-base fp16
(Apache-2.0 / MIT, pending ledger data/runtime/model_licences_pending/LIPSYNC.json).
Every submit is preceded by lora_attest.attest_submit and
licence_provenance.attest_licences on the effective graph; both are warn-only unless
ZYG_LORA_ATTEST=strict / ZYG_LICENCE_GATE=strict, in which case lipsync() returns
None rather than render.

Usage:
    from zyg_workflows import lipsync_service as LS
    mp4 = LS.lipsync('/abs/cell_00.png', '/abs/line.wav', '/abs/out_dir')
    # -> '/abs/out_dir/lipsync.mp4' or None
"""

from __future__ import annotations

import json
import os
import subprocess
from zyg_workflows.bin import exe

WORKFLOW_NAME = 'infinitetalk_i2v'

# InfiniteTalk's wav2vec window is fixed at 25 fps upstream.
NATIVE_FPS = 25.0

# Node ids of _comfy_workflows/infinitetalk_i2v.json.
NODE_LORA = '7'
NODE_IMAGE = '10'
NODE_RESIZE = '11'
NODE_AUDIO = '12'
NODE_EMBEDS = '13'
NODE_TEXT = '20'
NODE_MULTITALK = '25'
NODE_SAMPLER = '30'
NODE_VIDEO = '45'

_DEFAULT_STEPS = int(os.environ.get('ZYG_LIPSYNC_STEPS', '20'))
_DEFAULT_TIMEOUT_S = float(os.environ.get('ZYG_LIPSYNC_TIMEOUT_S', '3600'))

_VIDEO_EXT = ('.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v')


def _log_noop(_m):
    pass


def available() -> tuple[bool, str]:
    """Is every piece this service needs present? (weights, graph, ComfyUI)."""
    wf = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_comfy_workflows', f'{WORKFLOW_NAME}.json')
    if not os.path.isfile(wf):
        return False, f'workflow missing: {wf}'
    try:
        from zyg_workflows import _comfy_client as CC
    except Exception as exc:  # noqa: BLE001
        return False, f'_comfy_client unavailable: {exc}'
    if not CC.server_reachable():
        return False, f'ComfyUI not reachable on {CC.COMFY_HOST}:{CC.COMFY_PORT}'
    for cls in (
        'MultiTalkModelLoader',
        'Wav2VecModelLoader',
        'WanVideoImageToVideoMultiTalk',
        'MultiTalkWav2VecEmbeds',
    ):
        if not CC.has_node(cls):
            return False, f'ComfyUI node missing: {cls} (ComfyUI-WanVideoWrapper)'
    return True, 'ok'


# ---------------------------------------------------------------- media probes
def probe_duration_s(path: str) -> float | None:
    """Container duration in seconds, or None. Never raises."""
    return _ffprobe_float(['-show_entries', 'format=duration', '-of', 'csv=p=0', path])


def probe_fps(path: str) -> float | None:
    """Video stream fps as a float, or None (still images included). Never raises."""
    raw = _ffprobe_str(['-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate', '-of', 'csv=p=0', path])
    if not raw or '/' not in raw:
        return None
    try:
        num, den = raw.split('/', 1)
        den = float(den)
        return float(num) / den if den else None
    except (TypeError, ValueError):
        return None


def probe_frames(path: str) -> int | None:
    """Frame count of a video, counted rather than trusted. None on failure."""
    raw = _ffprobe_str(
        ['-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', path]
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _ffprobe_str(args: list[str]) -> str | None:
    try:
        r = subprocess.run([exe('ffprobe'), '-v', 'error', *args], capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    out = (r.stdout or '').strip().splitlines()
    return out[0].strip() if out else None


def _ffprobe_float(args: list[str]) -> float | None:
    raw = _ffprobe_str(args)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- graph
def build_graph(
    video_or_image: str,
    wav: str,
    width: int = 832,
    height: int = 480,
    frames: int = 81,
    steps: int = _DEFAULT_STEPS,
    seed: int = 7,
    prompt: str | None = None,
    lora: str | None = None,
    lora_strength: float | None = None,
) -> dict:
    """Return the effective InfiniteTalk graph for one take.

    ``video_or_image`` / ``wav`` are the names ComfyUI's input directory knows
    them by (what :func:`_comfy_client.stage_input_image` returns), not host
    paths — the LoadImage / LoadAudio nodes resolve basenames.

    ``lora`` swaps the character LoRA (a path under ComfyUI's loras/); the node
    itself is not optional — see the LOADER CONSTRAINT note in the module
    docstring — so passing None keeps the graph's own.
    """
    from zyg_workflows import _comfy_client as CC

    wf = CC.load_workflow(WORKFLOW_NAME)
    if lora:
        wf[NODE_LORA]['inputs']['lora'] = str(lora)
    if lora_strength is not None:
        wf[NODE_LORA]['inputs']['strength'] = float(lora_strength)
    wf[NODE_IMAGE]['inputs']['image'] = video_or_image
    wf[NODE_AUDIO]['inputs']['audio'] = wav
    wf[NODE_RESIZE]['inputs']['width'] = int(width)
    wf[NODE_RESIZE]['inputs']['height'] = int(height)
    wf[NODE_MULTITALK]['inputs']['width'] = int(width)
    wf[NODE_MULTITALK]['inputs']['height'] = int(height)
    wf[NODE_EMBEDS]['inputs']['num_frames'] = int(frames)
    wf[NODE_EMBEDS]['inputs']['fps'] = NATIVE_FPS
    wf[NODE_VIDEO]['inputs']['fps'] = NATIVE_FPS
    wf[NODE_SAMPLER]['inputs']['steps'] = int(steps)
    wf[NODE_SAMPLER]['inputs']['seed'] = int(seed)
    if prompt:
        wf[NODE_TEXT]['inputs']['positive_prompt'] = str(prompt)
    return wf


# ---------------------------------------------------------------- entry point
def lipsync(
    src_path: str,
    wav_path: str,
    out_dir: str,
    *,
    width: int = 832,
    height: int = 480,
    steps: int = _DEFAULT_STEPS,
    seed: int = 7,
    prompt: str | None = None,
    lora: str | None = None,
    lora_strength: float | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    log_fn=None,
) -> str | None:
    """Drive the mouth of ``src_path`` from ``wav_path``. mp4 path, or None.

    ``src_path`` may be a still or a video; a video contributes its first frame
    and its fps (the result is resampled from InfiniteTalk's 25 fps back to it).
    """
    log = log_fn or _log_noop
    try:
        return _lipsync(
            src_path, wav_path, out_dir, width, height, steps, seed, prompt, lora, lora_strength, timeout_s, log
        )
    except Exception as exc:  # noqa: BLE001
        log(f'[lipsync] {type(exc).__name__}: {exc}')
        return None


def _lipsync(
    src_path, wav_path, out_dir, width, height, steps, seed, prompt, lora, lora_strength, timeout_s, log
) -> str | None:
    if not (src_path and os.path.isfile(src_path)):
        log(f'[lipsync] source missing: {src_path}')
        return None
    if not (wav_path and os.path.isfile(wav_path)):
        log(f'[lipsync] wav missing: {wav_path}')
        return None
    ok, why = available()
    if not ok:
        log(f'[lipsync] unavailable — {why}')
        return None

    dur = probe_duration_s(wav_path)
    if not dur or dur <= 0:
        log(f'[lipsync] unreadable audio duration: {wav_path}')
        return None
    os.makedirs(out_dir, exist_ok=True)

    # A video source: first frame drives image mode, its fps is the target fps.
    src_fps = None
    still = src_path
    if src_path.lower().endswith(_VIDEO_EXT):
        src_fps = probe_fps(src_path)
        still = os.path.join(out_dir, 'src_frame0.png')
        if not _extract_first_frame(src_path, still):
            log(f'[lipsync] could not extract first frame of {src_path}')
            return None
        log(f'[lipsync] video source: image mode off frame 0, target fps {src_fps}')

    frames = max(int(round(dur * NATIVE_FPS)), 25)
    from zyg_workflows import _comfy_client as CC

    graph = build_graph(
        CC.stage_input_image(still),
        CC.stage_input_image(wav_path),
        width=width,
        height=height,
        frames=frames,
        steps=steps,
        seed=seed,
        prompt=prompt,
        lora=lora,
        lora_strength=lora_strength,
    )

    if not _attest(graph, log):
        return None

    log(f'[lipsync] submitting: {width}x{height}, {frames} frames @ {NATIVE_FPS} fps, {steps} steps, seed {seed}')
    try:
        outs = CC.submit(graph, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001
        log(f'[lipsync] submit failed: {exc}')
        return None
    produced = next((p for p in (outs or []) if os.path.isfile(p)), None)
    if not produced:
        log(f'[lipsync] no output file produced (got {outs!r})')
        return None

    out_mp4 = os.path.join(out_dir, 'lipsync.mp4')
    target_fps = src_fps if (src_fps and abs(src_fps - NATIVE_FPS) > 0.01) else None
    if not _deliver(produced, out_mp4, target_fps, dur):
        log(
            f'[lipsync] delivery (trim to {dur:.3f}s'
            + (f', resample -> {target_fps:.3f} fps' if target_fps else '')
            + ') failed'
        )
        return None
    if target_fps:
        log(f'[lipsync] resampled {NATIVE_FPS} fps -> {target_fps:.3f} fps (source rate)')
    log(f'[lipsync] trimmed to the speech duration {dur:.3f}s')
    return out_mp4 if os.path.isfile(out_mp4) else None


def _attest(graph: dict, log) -> bool:
    """Hash-attest and licence-check the graph's weights. False = do not render."""
    try:
        from zyg_workflows import lora_attest as _attest_mod
    except Exception as exc:  # noqa: BLE001
        log(f'[lipsync] lora_attest unavailable ({exc}) — proceeding unattested')
    else:
        try:
            _attest_mod.attest_submit(graph, tag='lipsync', log_fn=log)
        except _attest_mod.AttestationError as exc:
            log(f'[lipsync] BLOCKED before submit by model attestation (strict): {exc}')
            return False
    try:
        from zyg_workflows import licence_provenance as _lp

        res = _lp.attest_licences(graph, log_fn=log, tag='lipsync')
    except Exception as exc:  # noqa: BLE001
        log(f'[lipsync] licence check unavailable ({exc}) — proceeding')
        return True
    if res.get('violations'):
        log('[lipsync] BLOCKED — licence violation: ' + '; '.join(str(v.get('name')) for v in res['violations'][:4]))
        return False
    if res.get('ok') is None and _licence_strict():
        log(
            '[lipsync] BLOCKED — unknown licences under ZYG_LICENCE_GATE=strict: '
            + '; '.join(str(u.get('name')) for u in res.get('unknowns', [])[:4])
        )
        return False
    return True


def _licence_strict() -> bool:
    return os.environ.get('ZYG_LICENCE_GATE', '').strip().lower() == 'strict'


def _extract_first_frame(video: str, out_png: str) -> bool:
    try:
        r = subprocess.run(
            [exe('ffmpeg'), '-v', 'error', '-y', '-i', video, '-frames:v', '1', out_png],
            capture_output=True,
            timeout=300,
        )
    except Exception:  # noqa: BLE001
        return False
    return r.returncode == 0 and os.path.isfile(out_png)


def _deliver(src_mp4: str, out_mp4: str, fps: float | None, dur_s: float) -> bool:
    """Cut the take to the speech duration, optionally re-timing 25 fps -> ``fps``.

    InfiniteTalk samples in windows of ``frame_window_size`` and pads the last one,
    so a 3.00 s line comes back as 81 frames (3.24 s) and the mux would be out of
    step with its own audio. Trimming to the wav's duration is what makes the
    receipt's ffprobe video/audio agreement true rather than approximately true.
    """
    cmd = [exe('ffmpeg'), '-v', 'error', '-y', '-i', src_mp4]
    if fps:
        cmd += ['-filter:v', f'fps={fps:.6f}']
    cmd += ['-t', f'{dur_s:.6f}', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-c:a', 'copy', out_mp4]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=1800)
    except Exception:  # noqa: BLE001
        return False
    return r.returncode == 0 and os.path.isfile(out_mp4)


if __name__ == '__main__':  # pragma: no cover
    import sys

    print('available:', available())
    if len(sys.argv) > 3:
        print(
            json.dumps(
                {'mp4': lipsync(sys.argv[1], sys.argv[2], sys.argv[3], log_fn=lambda m: print(m, file=sys.stderr))}
            )
        )
