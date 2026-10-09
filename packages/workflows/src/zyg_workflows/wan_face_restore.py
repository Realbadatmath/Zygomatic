# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_face_restore.py — "video face detailer": re-canonize faces in a FINISHED clip.

Post-side repair from the 2026-07-29 identity research: run the clip back through VACE
masked inpainting with ONLY the face regions masked white — inside the mask the model
re-synthesizes conditioned on the CANON portrait refs + the character Wan-LoRAs; outside,
the original frames are the per-frame control (kept). Then composite ONLY the masked
regions back over the untouched original frames (feathered) so motion, set and grade
never take a VAE roundtrip.

    restore_faces(clip_path, char_ids, out_path, face_boxes=None, ...) -> out_path|None

face_boxes: [(fx0,fy0,fx1,fy1) fractions] per char, on the CLIP's geometry. None → one
face per equal column detected on the first frame (locked-camera assumption: faces barely
translate, so a dilated static box covers the motion envelope).

2026-09-02 — THIS TOOL NOW SCORES ITSELF. Re-synthesising a face is the single most
identity-destructive thing in the pipeline, and until today it ran with no identity
measurement before OR after: the only evidence a restore had helped was that it had
finished. `restore_faces` now measures per-frame identity on the INPUT clip and on the
candidate OUTPUT, writes both plus the delta to `<out_path>.identity.json`, and with
ZYG_FACE_RESTORE_REQUIRE_GAIN=1 refuses to publish an output whose identity FELL (the
candidate is written to a staging path and deleted, so the caller keeps its input).
Default is measure-and-report; the refusal is opt-in until the instrument has more than
one day of bench behind it.
"""

import glob
import json
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


def _log_noop(_m):
    pass


_LORA_ROOT = str(paths.ZYG_COMFY_ROOT / 'models' / 'loras')
IDENTITY_STRIDE = int(os.environ.get('ZYG_FACE_RESTORE_ID_STRIDE', '8'))
IDENTITY_MAX_FRAMES = int(os.environ.get('ZYG_FACE_RESTORE_ID_MAXFRAMES', '96'))


def _require_gain():
    return os.environ.get('ZYG_FACE_RESTORE_REQUIRE_GAIN', '0').strip().lower() in ('1', 'true', 'yes', 'on')


def score_identity_delta(clip_in, clip_out, char_ids, rois=None, style='arcane', stride=None, log_fn=None):
    """Per-frame identity on the input and on the candidate output — {char: {...}}.

    Fail-safe: an unmeasurable character (no bank, no face anywhere) reports
    delta=None and is EXCLUDED from any gain decision. A restore is never blocked
    by a number we could not take.
    """
    log = log_fn or _log_noop
    out = {'ok': None, 'chars': {}, 'stride': stride or IDENTITY_STRIDE}
    try:
        from zyg_workflows import identity_bank as ib
    except Exception as e:
        out['error'] = f'identity_bank unavailable: {e}'
        return out
    if not ib.enabled():
        out['error'] = 'disabled (ZYG_IDENTITY_CLIP=0)'
        return out
    n = max(1, len(char_ids or []))
    for i, cid in enumerate(char_ids or []):
        roi = None
        if rois and i < len(rois) and rois[i]:
            roi = tuple(rois[i])
        elif n > 1:
            roi = (i / n, 0.0, (i + 1) / n, 1.0)
        rec = {'roi': list(roi) if roi else None}
        for key, clip in (('before', clip_in), ('after', clip_out)):
            r = ib.check_clip(
                cid,
                style,
                clip,
                roi=roi,
                stride=stride or IDENTITY_STRIDE,
                max_frames=IDENTITY_MAX_FRAMES,
                record=False,
                tag='face_restore:' + key,
                log_fn=None,
            )
            rec[key] = {
                k: r.get(k)
                for k in (
                    'ok',
                    'cosine',
                    'cosine_min',
                    'cosine_p10',
                    'cosine_median',
                    'cosine_max',
                    'spread',
                    'pass_frac',
                    'found',
                    'sampled',
                    'ledger',
                    'backend',
                    'floor',
                    'reason',
                )
            }
        b, af = rec['before'].get('cosine'), rec['after'].get('cosine')
        rec['delta'] = None if (b is None or af is None) else round(af - b, 4)
        bp, ap = rec['before'].get('cosine_p10'), rec['after'].get('cosine_p10')
        rec['delta_p10'] = None if (bp is None or ap is None) else round(ap - bp, 4)
        rec['measurable'] = rec['delta'] is not None
        out['chars'][cid] = rec
        log(f'[face-restore][identity] {cid}: before={b} after={af} delta={rec["delta"]} (p10 {rec["delta_p10"]})')
    deltas = [c['delta'] for c in out['chars'].values() if c['delta'] is not None]
    out['measured'] = len(deltas)
    out['delta_mean'] = None if not deltas else round(sum(deltas) / len(deltas), 4)
    out['delta_min'] = None if not deltas else round(min(deltas), 4)
    out['ok'] = None if not deltas else bool(min(deltas) >= 0.0)
    return out


def _detect_face_boxes(frame_path, n, log):
    try:
        from zyg_workflows import identity_qc_service as IQ

        im = Image.open(frame_path).convert('RGB')
        W, H = im.size
        boxes = []
        for i in range(n):
            x0 = (W // n) * i
            x1 = W if i == n - 1 else (W // n) * (i + 1)
            crop = im.crop((x0, 0, x1, H))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                crop.save(tf.name)
                v = IQ.embed_images([tf.name], log_fn=_log_noop).get(tf.name) or {}
            os.unlink(tf.name)
            if v.get('face_detected') and v.get('bbox'):
                bx0, by0, bx1, by1 = v['bbox']
                sx = (x1 - x0) / (v.get('img_w') or 1)
                sy = H / (v.get('img_h') or 1)
                fw = (bx1 - bx0) * sx
                cx = x0 + (bx0 + bx1) / 2 * sx
                cy = (by0 + by1) / 2 * sy
                side = fw * 2.1  # face + hair + jaw, dilated for the motion envelope
                boxes.append(
                    (
                        max(0, (cx - side / 2) / W),
                        max(0, (cy - side * 0.62) / H),
                        min(1, (cx + side / 2) / W),
                        min(1, (cy + side * 0.58) / H),
                    )
                )
            else:
                boxes.append(None)
                log(f'[face-restore] no face in column {i}')
        return boxes
    except Exception as e:
        log(f'[face-restore] detector unavailable ({e})')
        return [None] * n


def restore_faces(
    clip_path,
    char_ids,
    out_path,
    face_boxes=None,
    steps=25,
    cfg=6.0,
    shift=5.0,
    seed=11,
    vace_strength=0.9,
    lora_strength=0.9,
    extra_prompt='',
    log_fn=None,
):
    """Re-render ONLY the face regions toward canon; composite back; re-encode. The heavy
    identity channel (VACE refs) carries the canon portraits, the char LoRAs run strong."""
    log = log_fn or _log_noop
    from zyg_workflows import canon_service as CS
    from zyg_workflows import wan_vace_service as V

    tmp = tempfile.mkdtemp(prefix='facerestore_')
    try:
        # 1) explode
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-i',
                clip_path,
                '-vsync',
                '0',
                os.path.join(tmp, 'f_%05d.png'),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log('[face-restore] extract failed')
            return None
        frames = sorted(glob.glob(os.path.join(tmp, 'f_*.png')))
        if len(frames) < 8:
            return None
        first = Image.open(frames[0]).convert('RGB')
        W, H = first.size
        n = len(char_ids)
        boxes = face_boxes or _detect_face_boxes(frames[0], n, log)

        # 2) face mask (white = re-render)
        mask = Image.new('L', (W, H), 0)
        d = ImageDraw.Draw(mask)
        got = 0
        for b in boxes:
            if not b:
                continue
            fx0, fy0, fx1, fy1 = b
            d.rectangle([int(W * fx0), int(H * fy0), int(W * fx1), int(H * fy1)], fill=255)
            got += 1
        if not got:
            log('[face-restore] no faces to restore')
            return None
        mask = mask.filter(ImageFilter.GaussianBlur(8))
        mask_path = os.path.join(tmp, 'facemask.png')
        mask.save(mask_path)

        # 3) VACE masked re-render: control = ORIGINAL frames (identity of the set and
        #    bodies preserved per frame), mask = faces, refs = canon portraits, LoRAs strong
        num_frames = len(frames) if len(frames) % 4 == 1 else (len(frames) // 4) * 4 + 1
        frames_use = frames[:num_frames]
        refs = [CS.build_vace_ref(c) for c in char_ids]
        refs = [p for p in refs if p]
        loras = []
        for c in char_ids:
            lp = f'wan_chars/wan_char_{c}_t2v.safetensors'
            if os.path.isfile(os.path.join(_LORA_ROOT, lp)):
                loras.append((lp, lora_strength))
            else:
                loras.append((f'wan_chars/wan_char_{c}.safetensors', lora_strength))
        binding = '. '.join(CS.canon_prompt_binding(c) for c in char_ids)
        prompt = (
            f'{binding}. The faces stay sharp, consistent and true to the reference '
            f'portraits, natural subtle facial motion. {extra_prompt}'
        )

        # stage originals as a control-video folder → VACE via per-frame input_frames
        ctrl_dir = os.path.join(tmp, 'ctrl')
        os.makedirs(ctrl_dir, exist_ok=True)
        for i, fp in enumerate(frames_use):
            shutil.copy2(fp, os.path.join(ctrl_dir, f'c_{i:05d}.png'))
        clipseg = V.generate_vace_clip_from_frames(
            ctrl_dir,
            mask_path,
            prompt,
            os.path.join(tmp, 'out'),
            num_frames=num_frames,
            width=W,
            height=H,
            steps=steps,
            cfg=cfg,
            shift=shift,
            seed=seed,
            vace_strength=vace_strength,
            vace_end_percent=1.0,
            ref_images_paths=refs,
            loras=loras,
            log_fn=log,
        )
        if not clipseg:
            log('[face-restore] VACE re-render failed')
            return None

        # 4) composite ONLY the masked region back over the originals
        rr = subprocess.run(
            [exe('ffmpeg'), '-y', '-loglevel', 'error', '-i', clipseg, '-vsync', '0', os.path.join(tmp, 'r_%05d.png')],
            capture_output=True,
            text=True,
        )
        if rr.returncode != 0:
            return None
        rendered = sorted(glob.glob(os.path.join(tmp, 'r_*.png')))
        matte = np.asarray(mask, dtype=np.float32)[:, :, None] / 255.0
        outdir = os.path.join(tmp, 'comp')
        os.makedirs(outdir, exist_ok=True)
        for i, fp in enumerate(frames_use):
            orig = np.asarray(Image.open(fp).convert('RGB'), dtype=np.float32)
            if i < len(rendered):
                ren = np.asarray(Image.open(rendered[i]).convert('RGB').resize((W, H)), dtype=np.float32)
                comp = orig * (1.0 - matte) + ren * matte
            else:
                comp = orig
            Image.fromarray(np.clip(comp, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))
        # Encode to a STAGING path first. out_path may be the caller's only copy of
        # the clip, and a restore that lost identity must never land on it.
        stage = out_path + '.stage.mp4'
        enc = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-framerate',
                '24',
                '-i',
                os.path.join(outdir, 'o_%05d.png'),
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-crf',
                '17',
                stage,
            ],
            capture_output=True,
            text=True,
        )
        if enc.returncode != 0 or not os.path.isfile(stage):
            try:
                os.remove(stage)
            except OSError as _exc:
                _zyg_log.debug('failed encode %s left behind: %s', stage, _exc)
            return None

        # ── did the re-synthesis actually help? (2026-09-02) ──────────────────
        idr = score_identity_delta(clip_path, stage, char_ids, rois=boxes, log_fn=log)
        try:
            with open(out_path + '.identity.json', 'w') as fh:
                json.dump(
                    {
                        'clip_in': clip_path,
                        'clip_out': out_path,
                        'char_ids': list(char_ids),
                        'boxes': [list(b) if b else None for b in boxes],
                        'require_gain': _require_gain(),
                        'identity': idr,
                    },
                    fh,
                    indent=2,
                    default=str,
                )
        except Exception as e:
            log(f'[face-restore] identity sidecar not written ({e})')
        if _require_gain() and idr.get('ok') is False:
            log(
                f'[face-restore] REFUSED: identity fell (delta_min '
                f'{idr.get("delta_min")}, mean {idr.get("delta_mean")}) — '
                f'ZYG_FACE_RESTORE_REQUIRE_GAIN=1, keeping the original clip'
            )
            try:
                os.remove(stage)
            except OSError as _exc:
                _zyg_log.debug('refused restore %s left behind: %s', stage, _exc)
            return None
        if idr.get('ok') is None:
            log(
                '[face-restore] identity delta UNMEASURABLE — publishing anyway '
                '(a number we could not take is not a verdict)'
            )
        os.replace(stage, out_path)
        log(f'[face-restore] → {os.path.basename(out_path)} ({got} face(s), identity delta {idr.get("delta_mean")})')
        return out_path
    except Exception as e:
        log(f'[face-restore] failed ({e})')
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
