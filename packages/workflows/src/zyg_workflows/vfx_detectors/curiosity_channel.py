# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math
import os

from zyg_workflows.vfx_detectors.core import (
    _EPS,
    _mean,
)

# ═══════════════════════════════════════════════════════════════════════════
# THE CURIOSITY CHANNEL
# ═══════════════════════════════════════════════════════════════════════════


def _iou(a, b):
    ax2, ay2 = a['x'] + a['w'], a['y'] + a['h']
    bx2, by2 = b['x'] + b['w'], b['y'] + b['h']
    ix = max(0.0, min(ax2, bx2) - max(a['x'], b['x']))
    iy = max(0.0, min(ay2, by2) - max(a['y'], b['y']))
    inter = ix * iy
    union = a['w'] * a['h'] + b['w'] * b['h'] - inter
    return inter / max(_EPS, union)


def curiosity(ctx, results, do_vlm=False):
    """Find moving things NOTHING in the taxonomy claimed, and try to name them.

    A region of residual (non-camera) motion is 'claimed' if it overlaps a
    detected subject (pose/face/hand box) or a bbox carried by a detector event
    on that frame. What is left over is, by construction, motion the analyzer
    noticed and could not account for — which is exactly the thing worth putting
    in a log. Unclaimed regions are linked into tracks across frames, cropped,
    and (with the VLM on) identified.

    This is where the taxonomy grows: an unknown that keeps recurring across
    clips is a missing entry, and the log is the evidence for adding it."""
    import cv2

    claimed_by_frame = {}
    for r in results:
        for ev in r.get('events') or []:
            bb = (ev.get('evidence') or {}).get('bbox')
            if isinstance(bb, list) and len(bb) == 4:
                claimed_by_frame.setdefault(ev['frame'], []).append(
                    {'x': bb[0], 'y': bb[1], 'w': bb[2], 'h': bb[3], 'src': ev['id']}
                )
    for i in range(ctx.n):
        for kind, getter in (('pose', ctx.pose_at), ('face', None), ('hand', None)):
            if kind == 'pose':
                p = getter(i)
                if p and p.get('bbox'):
                    claimed_by_frame.setdefault(i, []).append(dict(p['bbox'], src='pose'))
            elif kind == 'face':
                for f in ctx.faces_at(i):
                    claimed_by_frame.setdefault(i, []).append(dict(f['bbox'], src='face'))
            else:
                for h in ctx.hands_at(i):
                    claimed_by_frame.setdefault(i, []).append(dict(h['bbox'], src='hand'))

    # A camera move explains motion EVERYWHERE in its frame, and it carries no
    # bbox to say so. Without this the first thing the curiosity channel reports
    # on any panning shot is "unknown object occupying 93% of the frame".
    CAM_IDS = ('camera.pan', 'camera.tilt', 'camera.zoom', 'camera.roll', 'camera.handheld_shake')
    cam_frames = {ev['frame'] for r in results if r['id'] in CAM_IDS for ev in (r.get('events') or [])}

    min_area = ctx.T['unknown_min_area']
    max_area = ctx.T['unknown_max_area']
    claim_iou = ctx.T['unknown_claim_iou']
    tracks = []
    skipped_global = 0
    for f in sorted(ctx.pm):
        cam_moving = f in cam_frames
        fit_ok = bool(ctx.pm[f].get('cam_fit_ok'))
        for b in ctx.pm[f].get('motion_blobs') or []:
            if b['area_frac'] < min_area:
                continue
            # A blob spanning most of the frame is the frame moving, not a thing
            # in it. Doubly so when the affine fit FAILED, because then residual
            # motion still contains the whole camera move.
            if b['area_frac'] > max_area or (cam_moving and not fit_ok and b['area_frac'] > 0.25):
                skipped_global += 1
                continue
            box = {'x': b['x'], 'y': b['y'], 'w': b['w'], 'h': b['h']}
            claims = claimed_by_frame.get(f, [])
            best_claim = max((_iou(box, c) for c in claims), default=0.0)
            if best_claim >= claim_iou:
                continue
            placed = False
            for t in tracks:
                # IoU alone fragments fast movers: an object travelling its own
                # width per cel never overlaps itself, so one object became eight
                # tracks on the fixture. Fall back to centroid proximity scaled
                # by the object's own size, which is what "the same thing, moved"
                # actually looks like.
                bcx, bcy = box['x'] + box['w'] / 2, box['y'] + box['h'] / 2
                tcx, tcy = t['box']['x'] + t['box']['w'] / 2, t['box']['y'] + t['box']['h'] / 2
                span = max(_EPS, math.hypot(max(box['w'], t['box']['w']), max(box['h'], t['box']['h'])))
                near = math.hypot(bcx - tcx, bcy - tcy) <= 1.6 * span
                sized = 0.4 <= (box['w'] * box['h']) / max(_EPS, t['box']['w'] * t['box']['h']) <= 2.5
                if f - t['last_frame'] <= 3 and (_iou(box, t['box']) >= 0.15 or (near and sized)):
                    t['frames'].append(f)
                    t['boxes'].append(box)
                    t['last_frame'] = f
                    t['box'] = box
                    t['area_max'] = max(t['area_max'], b['area_frac'])
                    t['mag_max'] = max(t['mag_max'], b['mag_max'])
                    t['mags'].append(b['mag_mean'])
                    placed = True
                    break
            if not placed:
                tracks.append(
                    {
                        'frames': [f],
                        'boxes': [box],
                        'box': box,
                        'last_frame': f,
                        'area_max': b['area_frac'],
                        'mag_max': b['mag_max'],
                        'mags': [b['mag_mean']],
                    }
                )

    if skipped_global:
        ctx.log(
            f'  curiosity: ignored {skipped_global} region(s) larger than '
            f'{max_area:.0%} of frame — that is global/camera motion, not an object'
        )
    min_frames = int(ctx.T['unknown_min_frames'])
    out = []
    crops_dir = os.path.join(ctx.run_dir, 'crops')
    os.makedirs(crops_dir, exist_ok=True)
    for k, t in enumerate(sorted(tracks, key=lambda t: -t['area_max'])):
        if len(t['frames']) < min_frames:
            continue
        mid = t['frames'][len(t['frames']) // 2]
        box = t['boxes'][len(t['boxes']) // 2]
        rec = {
            'track': k,
            'frames': t['frames'][:100],
            'n_frames': len(t['frames']),
            'first_frame': t['frames'][0],
            'last_frame': t['frames'][-1],
            't_start_s': ctx.t_of(t['frames'][0]),
            't_end_s': ctx.t_of(t['frames'][-1]),
            'bbox': [round(box['x'], 4), round(box['y'], 4), round(box['w'], 4), round(box['h'], 4)],
            'area_max_frac': round(t['area_max'], 5),
            'motion_mag_max': round(t['mag_max'], 4),
            'motion_mag_mean': round(_mean(t['mags']), 4),
            'why_logged': 'residual motion not claimed by any subject box or detector event',
            'identity': 'UNIDENTIFIED',
            'vlm': None,
        }
        # THE CROP RULE: a small VLM answers about a tight crop and confabulates
        # about a full frame. Pad by 25% so the thing has context but the crop
        # is still ABOUT the thing.
        try:
            img = cv2.imread(os.path.join(ctx.frame_dir, ctx.names[mid]), cv2.IMREAD_COLOR)
            if img is not None:
                H, W = img.shape[:2]
                px, py = box['w'] * 0.25, box['h'] * 0.25
                x0 = max(0, int((box['x'] - px) * W))
                y0 = max(0, int((box['y'] - py) * H))
                x1 = min(W, int((box['x'] + box['w'] + px) * W))
                y1 = min(H, int((box['y'] + box['h'] + py) * H))
                if x1 > x0 + 8 and y1 > y0 + 8:
                    name = f'unknown_{k:03d}_f{mid:06d}.jpg'
                    cv2.imwrite(os.path.join(crops_dir, name), img[y0:y1, x0:x1])
                    rec['crop'] = name
                    rec['crop_frame'] = mid
        except (OSError, IndexError, ValueError) as e:
            rec['crop_error'] = f'{type(e).__name__}: {e}'
        out.append(rec)

    if do_vlm and out:
        from zyg_workflows import vfx_analyzer as VA

        cap = VA._vlm_available()
        if not cap.get('ok'):
            for rec in out:
                rec['vlm'] = {'ok': False, 'error': cap.get('note', 'VLM unavailable')}
            ctx.log(f'curiosity: VLM requested but unavailable — {cap.get("note")}')
        else:
            q = (
                'What single object or thing is in this image? '
                'Answer with a short noun phrase of at most five words, and nothing else.'
            )
            q2 = 'Is the main thing in this image moving or being acted on? Answer in at most eight words.'
            for rec in out:
                if not rec.get('crop'):
                    continue
                p = os.path.join(crops_dir, rec['crop'])
                a1 = VA.vlm_ask(p, q)
                a2 = VA.vlm_ask(p, q2)
                rec['vlm'] = {
                    'what': a1.get('answer', '') if a1.get('ok') else '',
                    'what_error': a1.get('error', ''),
                    'action': a2.get('answer', '') if a2.get('ok') else '',
                    'action_error': a2.get('error', ''),
                    'model': VA.VLM_MODEL,
                    'asked_on': 'crop',
                }
                if a1.get('ok') and a1.get('answer'):
                    rec['identity'] = a1['answer'][:120]
                ctx.log(f'  unknown track {rec["track"]} @f{rec.get("crop_frame")}: {rec["identity"]!r}')
    return out
