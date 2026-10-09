# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_animate_service.py — Wan2.2-Animate-14B as a SECOND video engine (S06, 2026-09-02).

Why this exists
---------------
The live identity-through-video path is VACE with ONE static skeleton painted into the
control channel for the whole clip (geom/char_vace.py). Its stated limitation is in its
own docstring: a static geometry statement is wrong guidance the moment the character
moves. Wan2.2-Animate-14B is the leading open model that takes the other shape — a
reference still plus a PER-FRAME 2D skeleton and per-frame face crops. Its authors chose
a 2D skeleton over a body model "for better generality, particularly for non-humanoid
characters", which is also why it fits this house: our creatures are not SMPL-shaped and
the SMPL family is banned here anyway.

Licence: Apache-2.0 (Wan-AI/Wan2.2-Animate-14B card + Wan2.2 README, verified 2026-09-02).
Weights pinned in data/runtime/model_licences_pending/S06.json.

THE INPUTS ARE OURS. Two traps are recorded at source and neither is wired here:
  * the ComfyUI tutorial preprocesses the driver with DWPose — banned (dataset is
    non-commercial). We draw the skeleton with MediaPipe through geom/keypoints.detect,
    in the same OpenPose colour convention geom/char_vace already paints into VACE
    (_POSE_COLOURS / _BONES imported from there, so the two engines cannot drift apart).
  * the official retarget uses FLUX.1-Kontext-dev — non-commercial, and the FLUX.1-dev
    family is deleted from this box. If proportions ever need retargeting the reference
    is rendered from the character's registered body instead (S05 geom/body_plates.py).
When S08's per-frame track lands (output/pose_tracks/<id>/track.json) build_pose_frames
reads it instead of running MediaPipe; until then MediaPipe per frame is the source.

Graph: _comfy_workflows/wan22_animate.json, built from the native ComfyUI tutorial
(docs.comfy.org/tutorials/video/wan/wan2-2-animate), node ids:

     1 UNETLoader              Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors
     2 CLIPLoader              umt5_xxl_fp8_e4m3fn_scaled.safetensors, type "wan"
     3 VAELoader               wan_2.1_vae.safetensors
     4 CLIPVisionLoader        clip_vision_h.safetensors
     5 LoraLoaderModelOnly     inserted by this module ONLY when lora= is passed
     6 ModelSamplingSD3        flow shift
    10 LoadImage               the reference still (the identity)
    11 LoadImagesFromFolderKJ  OUR pose frames, full sequence (the node slices it)
    12 LoadImagesFromFolderKJ  OUR face crops, full sequence
    13 LoadImagesFromFolderKJ  continue_motion frames — inserted for chunks >= 1 only
    14 CLIPVisionEncode        reference still
    15 LoadImagesFromFolderKJ  background plate — inserted ONLY for background_dir=
    16 LoadImagesFromFolderKJ  character matte — inserted ONLY for mask_dir=
    17 ImageToMask             matte (red channel) -> node 30's character_mask
    20/21 CLIPTextEncode       positive / negative
    30 WanAnimateToVideo       the engine
    40 KSampler
    41 TrimVideoLatent         drops the reference latents (trim_latent, output 3)
    50 VAEDecode
    51 ImageFromBatch          drops the re-rendered overlap (trim_image, output 4)
    60 SaveImage               lossless PNG frames

Chunking arithmetic, read off comfy_extras/nodes_wan.py rather than assumed:
WanAnimateToVideo slices pose_video/face_video at video_frame_offset, and with
continue_motion it first does ``offset -= len(continue_motion)`` — so chunk k re-renders
the overlap and node 51 drops it. With continue_motion_max_frames=5 the node returns
trim_image=5, so chunk 0 yields 81 new frames and every later chunk yields 76. The seams
therefore land at output frames 81 and 157 for a three-chunk render — NOT at 81/162,
which is what naive non-overlapping chunking would give. generate_animate_clips() returns
the real seam indices so a receipt never has to guess them.

Call shape mirrors wan_video_service._submit_wan_clip: one function per submission taking
the reference still, the control folders, mode, frames, seed and an optional LoRA.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import uuid

import numpy as np
from zyg_workflows.bin import exe

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from zyg_workflows import _comfy_client as _comfy

_WORKFLOW = 'wan22_animate'

# The engine's own defaults. Chunk length is the Wan family's 4n+1 convention.
CHUNK_FRAMES = 81
CONTINUE_MOTION_MAX_FRAMES = 5
DEFAULT_FPS = 17.0
DEFAULT_STEPS = 20
DEFAULT_CFG = 1.0
DEFAULT_SHIFT = 5.0
FACE_CROP_PX = 512

# Wan's stock video negative, same one wan_video_service's template carries.
DEFAULT_NEGATIVE = (
    '色调艳丽, 过曝, 静态, 细节模糊不清, 字幕, 风格, 作品, 画作, 画面, 静止, 整体发灰, '
    '最差质量, 低质量, JPEG压缩残留, 丑陋的, 残缺的, 多余的手指, 画得不好的手部, '
    '画得不好的脸部, 畸形的, 毁容的, 形态畸形的肢体, 手指融合, 静止不动的画面, '
    '杂乱的背景, 三条腿, 背景人很多, 倒着走'
)


def _log_to(log_fn):
    return log_fn or (lambda m: None)


# ---------------------------------------------------------------- our control inputs


def extract_driver_frames(
    driver_video: str,
    out_dir: str,
    crop: tuple | None = None,
    size: tuple | None = None,
    max_frames: int = 0,
    log_fn=None,
) -> int:
    """Decode the driver to PNG frames (optionally cropped/scaled). Returns the count.

    ``crop`` is (x, y, w, h) in the driver's own pixels — used to isolate ONE character
    in a two-character shot so the per-frame detector and the identity scorer are both
    looking at the same person.
    """
    log = _log_to(log_fn)
    os.makedirs(out_dir, exist_ok=True)
    vf = []
    if crop:
        vf.append('crop=%d:%d:%d:%d' % (crop[2], crop[3], crop[0], crop[1]))
    if size:
        vf.append('scale=%d:%d' % (size[0], size[1]))
    cmd = [exe('ffmpeg'), '-v', 'error', '-i', driver_video]
    if vf:
        cmd += ['-vf', ','.join(vf)]
    if max_frames:
        cmd += ['-frames:v', str(int(max_frames))]
    cmd += ['-start_number', '0', os.path.join(out_dir, 'drv_%05d.png'), '-y']
    subprocess.run(cmd, check=True, capture_output=True)
    n = len([f for f in os.listdir(out_dir) if f.startswith('drv_')])
    log('[animate] driver: %d frames -> %s' % (n, out_dir))
    return n


def _pose_track_path(char_id: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'pose_tracks', str(char_id), 'track.json')


def _track_frame_pts(track, i, w, h):
    """One frame of S08's pose track as MediaPipe-ordered [x, y, visibility] pixels.

    S08 owns output/pose_tracks/**; its schema is not fixed at the time this was
    written, so this reads defensively and returns None — which falls the caller back
    to MediaPipe — for anything it does not recognise. It never raises and it never
    invents joints: a track whose joints are not the 33 MediaPipe names is refused.
    """
    if not track:
        return None
    from zyg_workflows.geom import keypoints as K

    frames = track.get('frames') if isinstance(track, dict) else None
    if not isinstance(frames, list) or i >= len(frames):
        return None
    fr = frames[i]
    joints = fr.get('joints') if isinstance(fr, dict) else fr
    if isinstance(joints, dict):
        out = np.zeros((len(K.P), 3), np.float32)
        seen = 0
        for name, idx in K.P.items():
            v = joints.get(name)
            if not v or len(v) < 2:
                continue
            out[idx] = [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 1.0]
            seen += 1
        return out if seen >= 8 else None
    if isinstance(joints, list) and len(joints) == len(K.P):
        out = np.zeros((len(K.P), 3), np.float32)
        for idx, v in enumerate(joints):
            if not v or len(v) < 2:
                continue
            out[idx] = [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 1.0]
        return out
    return None


def build_pose_frames(frames_dir: str, out_dir: str, char_id: str | None = None, log_fn=None) -> dict:
    """Draw one OpenPose-coloured skeleton per driver frame onto black.

    Source of the joints, in order: S08's ``output/pose_tracks/<char_id>/track.json``
    when it exists, else MediaPipe per frame via geom.keypoints.detect. The colour and
    bone conventions are imported from geom.char_vace so this engine and the VACE
    control channel cannot describe the same body two different ways.

    Returns a four-state ledger: {n, found, not_found, unmeasurable, source, dir}.
    """
    log = _log_to(log_fn)
    from zyg_workflows.geom.char_vace import _BONES, _POSE_COLOURS
    from zyg_workflows.geom import keypoints as K

    os.makedirs(out_dir, exist_ok=True)
    names = sorted(f for f in os.listdir(frames_dir) if f.endswith('.png'))
    ledger = {
        'n': len(names),
        'found': 0,
        'not_found': 0,
        'unmeasurable': 0,
        'source': 'mediapipe',
        'dir': out_dir,
        'per_frame': [],
    }

    track = None
    if char_id:
        tp = _pose_track_path(char_id)
        if os.path.isfile(tp):
            try:
                track = json.load(open(tp))
                ledger['source'] = 'pose_track:%s' % tp
                log('[animate] pose source: S08 track %s' % tp)
            except Exception as exc:  # noqa: BLE001
                log('[animate] S08 track unreadable (%s) — falling back to MediaPipe' % exc)
                track = None
    if track is None:
        log('[animate] pose source: MediaPipe per frame (S08 track absent)')

    for i, name in enumerate(names):
        src = os.path.join(frames_dir, name)
        bgr = cv2.imread(src)
        if bgr is None:
            ledger['unmeasurable'] += 1
            ledger['per_frame'].append('unmeasurable')
            continue
        h, w = bgr.shape[:2]
        canvas = np.zeros((h, w, 3), np.uint8)
        pts = _track_frame_pts(track, i, w, h)
        if pts is None:
            try:
                det = K.detect(src)
                if det.body.ok:
                    pts = det.body.pts
            except Exception as exc:  # noqa: BLE001
                log('[animate] frame %d detect failed: %s' % (i, exc))
                ledger['unmeasurable'] += 1
                ledger['per_frame'].append('unmeasurable')
                cv2.imwrite(os.path.join(out_dir, 'pose_%05d.png' % i), canvas)
                continue
        if pts is None:
            ledger['not_found'] += 1
            ledger['per_frame'].append('not_found')
            cv2.imwrite(os.path.join(out_dir, 'pose_%05d.png' % i), canvas)
            continue
        th = max(3, h // 160)
        drawn = 0
        for j, (a, c) in enumerate(_BONES):
            pa, pc = pts[K.P[a]], pts[K.P[c]]
            if pa[2] < 0.4 or pc[2] < 0.4:
                continue
            cv2.line(
                canvas,
                (int(pa[0]), int(pa[1])),
                (int(pc[0]), int(pc[1])),
                _POSE_COLOURS[j % len(_POSE_COLOURS)],
                th,
                cv2.LINE_AA,
            )
            drawn += 1
        for nm in (
            'nose',
            'left_eye',
            'right_eye',
            'left_ear',
            'right_ear',
            'left_wrist',
            'right_wrist',
            'left_ankle',
            'right_ankle',
        ):
            p = pts[K.P[nm]]
            if p[2] >= 0.4:
                cv2.circle(canvas, (int(p[0]), int(p[1])), max(2, th), (255, 255, 255), -1)
        cv2.imwrite(os.path.join(out_dir, 'pose_%05d.png' % i), canvas)
        if drawn:
            ledger['found'] += 1
            ledger['per_frame'].append('found')
        else:
            ledger['not_found'] += 1
            ledger['per_frame'].append('not_found')
    log(
        '[animate] pose frames: %d found / %d not_found / %d unmeasurable of %d'
        % (ledger['found'], ledger['not_found'], ledger['unmeasurable'], ledger['n'])
    )
    return ledger


def build_face_frames(frames_dir: str, out_dir: str, px: int = FACE_CROP_PX, log_fn=None) -> dict:
    """Cut one face crop per driver frame with the SAME detector as the pose.

    Animate's face branch drives expression, not identity; identity comes from the
    reference still. A frame with no detectable head keeps the previous crop (the model
    wants a continuous sequence), and that substitution is counted, not hidden.
    """
    log = _log_to(log_fn)
    from zyg_workflows.geom import keypoints as K

    os.makedirs(out_dir, exist_ok=True)
    names = sorted(f for f in os.listdir(frames_dir) if f.endswith('.png'))
    ledger = {'n': len(names), 'found': 0, 'not_found': 0, 'unmeasurable': 0, 'held_over': 0, 'dir': out_dir}
    last = None
    for i, name in enumerate(names):
        src = os.path.join(frames_dir, name)
        bgr = cv2.imread(src)
        if bgr is None:
            ledger['unmeasurable'] += 1
            crop = last if last is not None else np.zeros((px, px, 3), np.uint8)
            cv2.imwrite(os.path.join(out_dir, 'face_%05d.png' % i), crop)
            continue
        h, w = bgr.shape[:2]
        box = None
        try:
            det = K.detect(src)
            if det.body.ok:
                box = K._head_crop(det.body.pts, w, h)
        except Exception as exc:  # noqa: BLE001
            log('[animate] frame %d face detect failed: %s' % (i, exc))
            ledger['unmeasurable'] += 1
        if box:
            x0, y0, x1, y1 = box
            crop = cv2.resize(bgr[y0:y1, x0:x1], (px, px), interpolation=cv2.INTER_CUBIC)
            last = crop
            ledger['found'] += 1
        else:
            if last is None:
                crop = np.zeros((px, px, 3), np.uint8)
                ledger['not_found'] += 1
            else:
                crop = last
                ledger['held_over'] += 1
        cv2.imwrite(os.path.join(out_dir, 'face_%05d.png' % i), crop)
    log(
        '[animate] face crops: %d found / %d held_over / %d not_found / %d unmeasurable'
        % (ledger['found'], ledger['held_over'], ledger['not_found'], ledger['unmeasurable'])
    )
    return ledger


# ---------------------------------------------------------------- the engine


def submit_animate_chunk(
    reference_image: str,
    pose_dir: str,
    face_dir: str,
    out_dir: str,
    *,
    width: int,
    height: int,
    frames: int = CHUNK_FRAMES,
    seed: int = 0,
    steps: int = DEFAULT_STEPS,
    cfg: float = DEFAULT_CFG,
    shift: float = DEFAULT_SHIFT,
    prompt: str = '',
    negative: str | None = None,
    video_frame_offset: int = 0,
    continue_motion_dir: str | None = None,
    background_dir: str | None = None,
    mask_dir: str | None = None,
    lora: str | None = None,
    lora_strength: float = 1.0,
    timeout_s: int = 3600,
    log_fn=None,
) -> list:
    """ONE WanAnimateToVideo submission. Returns the decoded PNG frame paths, copied
    into ``out_dir``. Mirrors wan_video_service._submit_wan_clip's shape.

    ``background_dir`` + ``mask_dir`` switch the node into REPLACEMENT mode: instead of
    generating the whole frame, the model keeps the background plate and regenerates only
    what the character mask covers. Both are optional and independent of each other; with
    neither the built graph is byte-identical to the generation-mode graph.
    """
    log = _log_to(log_fn)
    wf = copy.deepcopy(_comfy.load_workflow(_WORKFLOW))
    ref_name = _comfy.stage_input_image(reference_image)
    # LoadImagesFromFolderKJ resolves a RELATIVE folder against ComfyUI's own base
    # directory, not ours. A caller that passes output/... gets 'Folder cannot be found'
    # from inside the graph, which is a confusing place to learn it. Absolutise here so
    # every caller may use repo-relative paths like the rest of this codebase does.
    pose_dir = os.path.abspath(pose_dir)
    face_dir = os.path.abspath(face_dir)
    if continue_motion_dir:
        continue_motion_dir = os.path.abspath(continue_motion_dir)

    # Chunking: the native node seeks background_video and character_mask with the SAME
    # video_frame_offset it applies to pose/face — comfy_extras/nodes_wan.py L1211-1213
    # (background_video = background_video[video_frame_offset:]) and L1223-1227
    # (character_mask = character_mask[video_frame_offset:], unless it is a single frame,
    # which is repeated to `length`). So the full sequences go in exactly like the pose
    # sequence does and NO per-chunk pre-slicing is needed.
    if background_dir:
        background_dir = os.path.abspath(background_dir)
        wf['15'] = {
            'class_type': 'LoadImagesFromFolderKJ',
            '_meta': {'title': 'S06 node 15 - background video (the plate)'},
            'inputs': {
                'folder': background_dir,
                'width': width,
                'height': height,
                'keep_aspect_ratio': 'stretch',
                'image_load_cap': 0,
                'start_index': 0,
                'include_subfolders': False,
            },
        }
        wf['30']['inputs']['background_video'] = ['15', 0]
    if mask_dir:
        mask_dir = os.path.abspath(mask_dir)
        wf['16'] = {
            'class_type': 'LoadImagesFromFolderKJ',
            '_meta': {'title': 'S06 node 16 - character matte frames'},
            'inputs': {
                'folder': mask_dir,
                'width': width,
                'height': height,
                'keep_aspect_ratio': 'stretch',
                'image_load_cap': 0,
                'start_index': 0,
                'include_subfolders': False,
            },
        }
        # The mattes are written as single-channel 0/255 PNGs; loaded as an IMAGE all
        # three channels carry the same value, so the red channel IS the matte.
        wf['17'] = {
            'class_type': 'ImageToMask',
            '_meta': {'title': 'S06 node 17 - matte -> character_mask'},
            'inputs': {'image': ['16', 0], 'channel': 'red'},
        }
        wf['30']['inputs']['character_mask'] = ['17', 0]

    if lora:
        wf['5'] = {
            'class_type': 'LoraLoaderModelOnly',
            '_meta': {'title': 'S06 node 5 - character LoRA'},
            'inputs': {'model': ['1', 0], 'lora_name': lora, 'strength_model': float(lora_strength)},
        }
        wf['6']['inputs']['model'] = ['5', 0]

    if continue_motion_dir:
        wf['13'] = {
            'class_type': 'LoadImagesFromFolderKJ',
            '_meta': {'title': 'S06 node 13 - continue_motion tail'},
            'inputs': {
                'folder': continue_motion_dir,
                'width': width,
                'height': height,
                'keep_aspect_ratio': 'stretch',
                'image_load_cap': 0,
                'start_index': 0,
                'include_subfolders': False,
            },
        }
        wf['30']['inputs']['continue_motion'] = ['13', 0]

    overrides = {
        '10': {'image': ref_name},
        '11': {'folder': pose_dir, 'width': width, 'height': height},
        '12': {'folder': face_dir},
        '20': {'text': prompt},
        '21': {'text': negative if negative is not None else DEFAULT_NEGATIVE},
        '30': {
            'width': width,
            'height': height,
            'length': int(frames),
            'continue_motion_max_frames': CONTINUE_MOTION_MAX_FRAMES,
            'video_frame_offset': int(video_frame_offset),
        },
        '40': {'seed': int(seed), 'steps': int(steps), 'cfg': float(cfg)},
        '6': {'shift': float(shift)},
        '51': {'length': int(frames)},
        '60': {'filename_prefix': 'ZygAnimate/%s' % uuid.uuid4().hex[:8]},
    }
    log(
        '[animate] submit: offset=%d frames=%d %dx%d seed=%d%s%s%s%s'
        % (
            video_frame_offset,
            frames,
            width,
            height,
            seed,
            ' lora=%s@%.2f' % (lora, lora_strength) if lora else '',
            ' +continue_motion' if continue_motion_dir else '',
            ' +background' if background_dir else '',
            ' +character_mask' if mask_dir else '',
        )
    )
    outs = _comfy.submit(wf, overrides=overrides, timeout_s=timeout_s)
    outs = [p for p in outs if p.lower().endswith('.png')]
    if not outs:
        raise RuntimeError('WanAnimate: ComfyUI returned no frames')
    os.makedirs(out_dir, exist_ok=True)
    kept = []
    for i, p in enumerate(sorted(outs)):
        dst = os.path.join(out_dir, 'f_%05d.png' % i)
        shutil.copy2(p, dst)
        kept.append(dst)
    log('[animate] chunk done: %d frames -> %s' % (len(kept), out_dir))
    return kept


def generate_animate_clips(
    reference_image: str,
    pose_dir: str,
    face_dir: str,
    out_dir: str,
    *,
    width: int,
    height: int,
    n_chunks: int = 1,
    frames: int = CHUNK_FRAMES,
    seed: int = 0,
    prompt: str = '',
    background_dir: str | None = None,
    mask_dir: str | None = None,
    lora: str | None = None,
    lora_strength: float = 1.0,
    fps: float = DEFAULT_FPS,
    log_fn=None,
    **kw,
) -> dict:
    """Chained long render. Returns {frames: [...], seams: [...], mp4, chunks: [...]}.

    ``seams`` are the OUTPUT frame indices where one chunk hands over to the next,
    computed from the node's own arithmetic (see the module docstring), not assumed.

    ``background_dir`` / ``mask_dir`` (replacement mode) are the FULL sequences, handed
    to every chunk unsliced — the node seeks them with the same video_frame_offset it
    uses for pose and face.
    """
    log = _log_to(log_fn)
    os.makedirs(out_dir, exist_ok=True)
    all_frames, seams, chunks = [], [], []
    offset = 0
    tail_dir, n_tail = None, 0
    for k in range(n_chunks):
        cdir = os.path.join(out_dir, 'chunk_%02d' % k)
        got = submit_animate_chunk(
            reference_image,
            pose_dir,
            face_dir,
            cdir,
            width=width,
            height=height,
            frames=frames,
            seed=seed,
            prompt=prompt,
            video_frame_offset=offset,
            continue_motion_dir=tail_dir,
            background_dir=background_dir,
            mask_dir=mask_dir,
            lora=lora,
            lora_strength=lora_strength,
            log_fn=log_fn,
            **kw,
        )
        if k:
            seams.append(len(all_frames))
        all_frames.extend(got)
        chunks.append({'k': k, 'offset_in': offset, 'n': len(got), 'dir': cdir})
        # WanAnimateToVideo does ``offset -= len(continue_motion)`` before slicing the
        # pose/face sequences and returns ``that + length``. Mirrored exactly here so a
        # chunk never re-reads or skips driver frames.
        m = 0 if tail_dir is None else min(CONTINUE_MOTION_MAX_FRAMES, n_tail)
        offset = max(0, offset - m) + frames
        tail_dir = os.path.join(out_dir, 'tail_%02d' % k)
        os.makedirs(tail_dir, exist_ok=True)
        for f in os.listdir(tail_dir):
            os.remove(os.path.join(tail_dir, f))
        tail = got[-CONTINUE_MOTION_MAX_FRAMES:]
        for i, p in enumerate(tail):
            shutil.copy2(p, os.path.join(tail_dir, 't_%05d.png' % i))
        n_tail = len(tail)

    strip = os.path.join(out_dir, 'frames')
    os.makedirs(strip, exist_ok=True)
    for i, p in enumerate(all_frames):
        shutil.copy2(p, os.path.join(strip, 'a_%05d.png' % i))
    mp4 = os.path.join(out_dir, 'animate.mp4')
    subprocess.run(
        [
            exe('ffmpeg'),
            '-v',
            'error',
            '-framerate',
            str(fps),
            '-i',
            os.path.join(strip, 'a_%05d.png'),
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-crf',
            '16',
            mp4,
            '-y',
        ],
        check=True,
        capture_output=True,
    )
    log('[animate] %d frames, seams at %s -> %s' % (len(all_frames), seams, mp4))
    return {
        'frames': [os.path.join(strip, 'a_%05d.png' % i) for i in range(len(all_frames))],
        'seams': seams,
        'mp4': mp4,
        'chunks': chunks,
    }


# ---------------------------------------------------------------- the plate-set entry


def _plateset_path(shot_dir: str) -> str:
    for cand in (os.path.join(shot_dir, 'plates', 'plateset.json'), os.path.join(shot_dir, 'plateset.json')):
        if os.path.isfile(cand):
            return cand
    raise FileNotFoundError('no plateset.json under %s' % shot_dir)


def _stage_sequence(plates_dir: str, pattern: str, n: int, dst: str) -> int:
    """One prefix of the plate set into a folder of its own.

    scene_plates.build writes bg_/ctrl_/pose_/m_/face_/depth_ side by side in ONE
    directory, but LoadImagesFromFolderKJ takes a whole folder — pointed at plates/ it
    would load every prefix interleaved. So each sequence gets its own directory of
    symlinks (a copy only where the filesystem refuses one; this box is at 98 % disk).
    Returns the number of frames staged.
    """
    os.makedirs(dst, exist_ok=True)
    k = 0
    for i in range(1, n + 1):
        src = os.path.join(plates_dir, pattern % i)
        if not os.path.isfile(src):
            break
        link = os.path.join(dst, '%05d.png' % i)
        if os.path.lexists(link):
            os.remove(link)
        try:
            os.symlink(os.path.abspath(src), link)
        except OSError:
            shutil.copy2(src, link)
        k += 1
    return k


def _next_take_dir(shot_dir: str) -> str:
    base = os.path.join(shot_dir, 'video')
    os.makedirs(base, exist_ok=True)
    n = 1
    while os.path.exists(os.path.join(base, 'animate_take%d' % n)):
        n += 1
    d = os.path.join(base, 'animate_take%d' % n)
    os.makedirs(d)
    return d


def animate_from_plateset(
    shot_dir: str,
    char_id: str,
    *,
    width: int = 0,
    height: int = 0,
    seed: int = 0,
    prompt: str = '',
    lora: str | None = None,
    log_fn=None,
    reference: str | None = None,
    plateset_dir: str | None = None,
    **kw,
) -> dict:
    """Blender plate set -> one Wan-Animate REPLACEMENT render.

    Everything the native node's replacement mode wants already exists in the plate set
    scene_plates.build writes: ``bg_`` is the beauty plate with the proxy actor painted
    out, ``m_`` is the dilated actor matte, ``pose_`` is the rig's own skeleton (no
    detector in the loop at all) and ``face_`` is the canon face crop. The identity comes
    from canon_service.canon_portrait — the same still the LoRA was trained on.

    Writes ``<shot_dir>/video/animate_take<N>/animate.mp4``. Returns the
    generate_animate_clips dict plus {take_dir, plateset, reference, n_chunks, inputs}.
    """
    import math

    from zyg_workflows.canon_service import canon_portrait

    log = _log_to(log_fn)
    shot_dir = os.path.abspath(shot_dir)
    ps_path = os.path.join(os.path.abspath(plateset_dir), 'plateset.json') if plateset_dir else _plateset_path(shot_dir)
    with open(ps_path, 'r', encoding='utf-8') as fh:
        ps = json.load(fh)
    plates_dir = os.path.dirname(ps_path)

    n = int(ps['frames'])
    width = int(width or ps['width'])
    height = int(height or ps['height'])

    reference = os.path.abspath(reference) if reference else canon_portrait(char_id)
    if not reference or not os.path.isfile(reference):
        raise FileNotFoundError('no canon portrait for character %r' % char_id)

    take = _next_take_dir(shot_dir)
    stage = os.path.join(take, 'in')
    dirs, counts = {}, {}
    for key, default in (
        ('pose', 'pose_%05d.png'),
        ('face', 'face_%05d.png'),
        ('bg', 'bg_%05d.png'),
        ('mask', 'm_%05d.png'),
    ):
        d = os.path.join(stage, key)
        counts[key] = _stage_sequence(plates_dir, ps.get(key) or default, n, d)
        dirs[key] = d
    if counts['pose'] != n:
        raise ValueError('pose frames: %d staged, plateset says %d' % (counts['pose'], n))
    # face_ is only written when the shot had a canon face (plateset face_source).
    face_dir = dirs['face'] if counts['face'] == n else dirs['pose']
    if counts['face'] != n:
        log('[animate] plate set has no face sequence (face_source=%s) — face branch off' % ps.get('face_source'))

    n_chunks = max(1, int(math.ceil(n / float(CHUNK_FRAMES))))
    log(
        '[animate] plate set %s: %d frames %dx%d, %d chunk(s), ref=%s'
        % (ps.get('shot') or shot_dir, n, width, height, n_chunks, reference)
    )

    out = generate_animate_clips(
        reference,
        dirs['pose'],
        face_dir,
        take,
        width=width,
        height=height,
        n_chunks=n_chunks,
        seed=seed,
        prompt=prompt,
        background_dir=dirs['bg'] if counts['bg'] == n else None,
        mask_dir=dirs['mask'] if counts['mask'] == n else None,
        lora=lora,
        fps=float(ps.get('fps') or DEFAULT_FPS),
        log_fn=log_fn,
        **kw,
    )
    out.update(
        {
            'take_dir': take,
            'plateset': ps_path,
            'reference': reference,
            'n_chunks': n_chunks,
            'inputs': dirs,
            'staged': counts,
        }
    )
    return out
