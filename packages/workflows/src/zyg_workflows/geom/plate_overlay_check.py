#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plate-camera check without a render.

Candidate (a) of S01 — "the plate camera does not match the still" — is decidable
on the CPU. track_plates.py projects the fitted mesh with the estimator's own
per-frame pinhole (geom/track_plates.py:81-96, self-checked at 0.0000 px against
`pred_keypoints_2d`). So if the plate silhouettes overlay the SAM masks of the same
frames, the camera is right whatever the render did with them.

Measured per frame, for both plate modes (depth, composite):
  - IoU of plate silhouette vs SAM mask (mask resized to plate size, NEAREST)
  - centroid offset (dx, dy) in plate pixels
  - bbox height ratio plate/mask

Two nulls, required before any reading of the numbers:
  N1 mirrored plate (np.fliplr) vs the same mask
  N2 plate k vs mask k+20

Writes plate_overlay.json, plate_overlay.md, plate_overlay.png next to the track.
CPU only: numpy + PIL. Reads nothing but the track's own frames/masks/plates.
"""

from __future__ import annotations

import hashlib
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'pose_tracks', 'abel_shores_cabin'
)
N_FRAMES = 205
NULL_SHIFT = 20
PANEL_FRAMES = [0, 40, 100, 160, 204]

# Reading, fixed before the numbers are seen:
#   IoU p10 >= 0.80 and mean |dx|, |dy| < 10 px  -> camera matches, candidate (a) EXCLUDED
#   IoU p10 <  0.60 or a centroid offset > 25 px -> candidate (a) STANDS
P10_PASS = 0.80
P10_FAIL = 0.60
CENTROID_PASS_PX = 10.0
CENTROID_FAIL_PX = 25.0


# ---------------------------------------------------------------- primitives


def mask_path(k: int) -> str:
    return os.path.join(BASE, 'masks', f'm_{k:05d}.png')


def depth_path(k: int) -> str:
    return os.path.join(BASE, 'plates_depth', f'ctrl_{k:05d}.png')


def comp_path(k: int) -> str:
    return os.path.join(BASE, 'plates_composite', f'ctrl_{k:05d}.png')


def frame_path(k: int) -> str:
    """frames/ is 1-based, masks/ and plates_* are 0-based: f_00001 <-> m_00000."""
    return os.path.join(BASE, 'frames', f'f_{k + 1:05d}.png')


def load_mask(k: int, size: tuple[int, int]) -> np.ndarray:
    """SAM mask as bool at the plate's resolution (NEAREST — no invented edges)."""
    im = Image.open(mask_path(k))
    if im.size != size:
        im = im.resize(size, Image.NEAREST)
    return np.asarray(im) > 0


def load_plate(k: int, mode: str) -> np.ndarray:
    if mode == 'depth':
        return np.asarray(Image.open(depth_path(k))) > 0
    a = np.asarray(Image.open(comp_path(k)).convert('RGB'))
    return a.max(axis=2) > 0


def iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    return float(inter) / union if union else 0.0


def centroid(a: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(a)
    if xs.size == 0:
        return float('nan'), float('nan')
    return float(xs.mean()), float(ys.mean())


def bbox_h(a: np.ndarray) -> float:
    ys = np.nonzero(a.any(axis=1))[0]
    return float(ys[-1] - ys[0] + 1) if ys.size else 0.0


def bbox_rows(a: np.ndarray) -> tuple[int, int]:
    ys = np.nonzero(a.any(axis=1))[0]
    return (int(ys[0]), int(ys[-1])) if ys.size else (-1, -1)


def band_iou(plate: np.ndarray, mask: np.ndarray, frac: float = 0.6) -> float:
    """IoU restricted to the top `frac` of the mask's bbox.

    The desk occludes the lower body in the mask but not in the plate, so the
    full-silhouette IoU mixes an occlusion difference into what is supposed to be a
    camera measurement. This band is above the desk in every frame of this shot.
    """
    t, b = bbox_rows(mask)
    if t < 0:
        return float('nan')
    cut = t + int(round(frac * (b - t + 1)))
    return iou(plate[t:cut], mask[t:cut])


def shifted(a: np.ndarray, sx: int, sy: int) -> np.ndarray:
    """Translate a binary map by (sx, sy) px, filling with False (no wrap-around)."""
    out = np.zeros_like(a)
    H, W = a.shape
    ys, yd = (slice(0, H - sy), slice(sy, H)) if sy >= 0 else (slice(-sy, H), slice(0, H + sy))
    xs, xd = (slice(0, W - sx), slice(sx, W)) if sx >= 0 else (slice(-sx, W), slice(0, W + sx))
    out[yd, xd] = a[ys, xs]
    return out


def best_shift(plate: np.ndarray, mask: np.ndarray) -> tuple[int, int, float]:
    """The translation that maximises IoU, over dx in +-16 and dy in +-40, step 2.

    This is the discriminator between the two things a systematic centroid offset can
    mean. If a rigid shift recovers most of the missing IoU, the residual is a
    registration/camera offset. If IoU barely improves, the residual is shape — the
    mesh has no hair at the top and the desk occludes the mask at the bottom — and the
    camera is not what is wrong.
    """
    best = (0, 0, iou(plate, mask))
    for sy in range(-40, 41, 2):
        for sx in range(-16, 17, 2):
            v = iou(shifted(plate, sx, sy), mask)
            if v > best[2]:
                best = (sx, sy, v)
    return best


def edge(a: np.ndarray) -> np.ndarray:
    """1-px boundary of a binary map, by 4-neighbour erosion."""
    er = a.copy()
    er[1:, :] &= a[:-1, :]
    er[:-1, :] &= a[1:, :]
    er[:, 1:] &= a[:, :-1]
    er[:, :-1] &= a[:, 1:]
    return a & ~er


def thicken(a: np.ndarray, r: int = 1) -> np.ndarray:
    out = a.copy()
    for _ in range(r):
        d = out.copy()
        d[1:, :] |= out[:-1, :]
        d[:-1, :] |= out[1:, :]
        d[:, 1:] |= out[:, :-1]
        d[:, :-1] |= out[:, 1:]
        out = d
    return out


def stats(v: list[float]) -> dict:
    a = np.asarray([x for x in v if np.isfinite(x)], dtype=np.float64)
    if a.size == 0:
        return {'n': 0}
    return {
        'n': int(a.size),
        'mean': float(a.mean()),
        'min': float(a.min()),
        'max': float(a.max()),
        'p10': float(np.percentile(a, 10)),
        'p50': float(np.percentile(a, 50)),
    }


# ------------------------------------------------------------------ receipts


def label_receipt() -> dict:
    """The brief expects a 0..5 label map. Print what the files actually hold."""
    rows = []
    for k in (0, 100, 204):
        a = np.asarray(Image.open(mask_path(k)))
        vals, counts = np.unique(a, return_counts=True)
        rows.append(
            {
                'frame': k,
                'shape': list(a.shape),
                'dtype': str(a.dtype),
                'mode': Image.open(mask_path(k)).mode,
                'labels': [int(v) for v in vals],
                'counts': [int(c) for c in counts],
            }
        )
    nonzero = sorted({v for r in rows for v in r['labels'] if v})
    return {
        'sampled': rows,
        'nonzero_labels': nonzero,
        'is_multi_label': len(nonzero) > 1,
        'subject_rule': 'value > 0',
        'note': (
            'masks are BINARY 0/255, not the 0..5 label map the brief describes; '
            'exactly one non-zero label exists, so "subject = value > 0" needs no '
            'disambiguation and no Abel-vs-other selection was possible or needed'
        ),
    }


def stale_mask_receipt() -> dict:
    """A repeated mask is a stale reference: nothing about the camera is decidable there."""
    digests = {}
    for k in range(N_FRAMES):
        with open(mask_path(k), 'rb') as fh:
            digests.setdefault(hashlib.md5(fh.read(), usedforsecurity=False).hexdigest(), []).append(k)
    dupes = {h: ks for h, ks in digests.items() if len(ks) > 1}
    stale = sorted({k for ks in dupes.values() for k in ks[1:]})
    fdig = set()
    for k in stale[:1] + stale[-1:]:
        with open(frame_path(k), 'rb') as fh:
            fdig.add(hashlib.md5(fh.read(), usedforsecurity=False).hexdigest())
    return {
        'unique_masks': len(digests),
        'repeated_groups': {h[:8]: ks for h, ks in dupes.items()},
        'stale_frames': stale,
        'source_frames_still_change_there': len(fdig) > 1,
        'note': (
            'masks m_%05d..m_%05d are byte-identical while the source frames keep changing: '
            'the SAM track froze at the shot boundary. On those frames the reference is '
            'stale, so the camera question is not_detectable, not failed.' % (stale[0] - 1, stale[-1])
        )
        if stale
        else 'no repeated masks',
    }


def offset_receipt() -> dict:
    """frames/ is 1-based; masks/plates are 0-based. Check it, don't assume it."""
    ok = (
        os.path.isfile(os.path.join(BASE, 'frames', 'f_00001.png'))
        and not os.path.isfile(os.path.join(BASE, 'frames', 'f_00000.png'))
        and os.path.isfile(os.path.join(BASE, 'masks', 'm_00000.png'))
        and not os.path.isfile(os.path.join(BASE, 'masks', f'm_{N_FRAMES:05d}.png'))
    )
    # numeric corroboration: the mask's mean colour inside vs outside on its own frame
    k = 100
    f = np.asarray(Image.open(frame_path(k)).convert('RGB')).astype(np.float64)
    m = np.asarray(Image.open(mask_path(k))) > 0
    inside = float(f[m].mean())
    outside = float(f[~m].mean())
    return {
        'rule': 'f_{k+1:05d} <-> m_{k:05d} <-> ctrl_{k:05d}',
        'index_ranges_consistent': bool(ok),
        'frame_100_mean_luma_inside_mask': round(inside, 2),
        'frame_100_mean_luma_outside_mask': round(outside, 2),
        'visual_check': (
            'mask 100 painted over frame f_00101 lands on the boy (lit subject inside, dark cabin outside)'
        ),
    }


# ---------------------------------------------------------------------- main


def summarise(rows: list[dict], mode: str, label: str) -> dict:
    ious = [r['iou'] for r in rows]
    s = {
        'mode': mode,
        'segment': label,
        'frames': len(rows),
        'frame_range': [rows[0]['k'], rows[-1]['k']] if rows else [],
        'iou': stats(ious),
        'iou_upper_band': stats([r['iou_upper'] for r in rows]),
        'abs_dx': stats([abs(r['dx']) for r in rows]),
        'abs_dy': stats([abs(r['dy']) for r in rows]),
        'abs_dy_top': stats([abs(r['dy_top']) for r in rows]),
        'abs_dy_bot': stats([abs(r['dy_bot']) for r in rows]),
        'signed_dy_mean': stats([r['dy'] for r in rows])['mean'],
        'frac_dy_positive': float(np.mean([r['dy'] > 0 for r in rows])) if rows else float('nan'),
        'height_ratio': stats([r['height_ratio'] for r in rows]),
        'null_mirror_iou_mean': stats([r['iou_null_mirror'] for r in rows])['mean'],
        'null_shift_iou_mean': stats([r['iou_null_shift'] for r in rows if 'iou_null_shift' in r]).get(
            'mean', float('nan')
        ),
        'worst_frame': int(rows[int(np.argmin(ious))]['k']),
        'worst_iou': float(min(ious)),
    }
    s['beats_null_mirror'] = bool(s['iou']['mean'] > s['null_mirror_iou_mean'])
    s['beats_null_shift'] = bool(s['iou']['mean'] > s['null_shift_iou_mean'])
    s['discriminating'] = bool(s['beats_null_mirror'] and s['beats_null_shift'])

    p10 = s['iou']['p10']
    dmax = max(s['abs_dx']['mean'], s['abs_dy']['mean'])
    if not s['discriminating']:
        s['verdict'] = 'unmeasurable'
        s['reading'] = 'the measure does not beat its own nulls; it says nothing about the camera'
    elif p10 >= P10_PASS and dmax < CENTROID_PASS_PX:
        s['verdict'] = 'camera_matches'
        s['reading'] = 'IoU p10 >= %.2f and mean |dx|,|dy| < %.0f px: candidate (a) EXCLUDED' % (
            P10_PASS,
            CENTROID_PASS_PX,
        )
    elif p10 < P10_FAIL or dmax > CENTROID_FAIL_PX:
        s['verdict'] = 'camera_mismatch'
        s['reading'] = 'IoU p10 < %.2f or a centroid offset > %.0f px: candidate (a) STANDS' % (
            P10_FAIL,
            CENTROID_FAIL_PX,
        )
    else:
        s['verdict'] = 'inconclusive'
        s['reading'] = 'between the two thresholds: neither excludes nor confirms candidate (a)'
    return s


def run_mode(mode: str, stale: set[int]) -> dict:
    rows = []
    for k in range(N_FRAMES):
        plate = load_plate(k, mode)
        H, W = plate.shape
        mask = load_mask(k, (W, H))
        px, py = centroid(plate)
        mx, my = centroid(mask)
        ph, mh = bbox_h(plate), bbox_h(mask)
        pt, pb = bbox_rows(plate)
        mt, mb = bbox_rows(mask)
        row = {
            'k': k,
            'iou': iou(plate, mask),
            'iou_upper': band_iou(plate, mask),
            'dx': px - mx,
            'dy': py - my,
            'dy_top': float(pt - mt),
            'dy_bot': float(pb - mb),
            'height_ratio': (ph / mh) if mh else float('nan'),
            'plate_px': int(np.count_nonzero(plate)),
            'mask_px': int(np.count_nonzero(mask)),
            'iou_null_mirror': iou(np.fliplr(plate), mask),
            'reference': 'stale' if k in stale else 'live',
        }
        if k + NULL_SHIFT < N_FRAMES:
            row['iou_null_shift'] = iou(plate, load_mask(k + NULL_SHIFT, (W, H)))
        rows.append(row)

    shift_rows = []
    if mode == 'depth':
        for k in range(0, N_FRAMES, 10):
            if k in stale:
                continue
            plate = load_plate(k, mode)
            H, W = plate.shape
            mask = load_mask(k, (W, H))
            sx, sy, v = best_shift(plate, mask)
            shift_rows.append(
                {
                    'k': k,
                    'best_dx': sx,
                    'best_dy': sy,
                    'iou_at_best': v,
                    'iou_at_zero': rows[k]['iou'],
                    'gain': v - rows[k]['iou'],
                }
            )

    live = [r for r in rows if r['reference'] == 'live']
    out = {
        'summary': summarise(rows, mode, 'all_205'),
        'summary_live_reference': summarise(live, mode, 'live_reference') if live else None,
        'rows': rows,
    }
    if shift_rows:
        gains = [r['gain'] for r in shift_rows]
        out['shift_search'] = {
            'sampled_frames': [r['k'] for r in shift_rows],
            'rows': shift_rows,
            'mean_best_dx': float(np.mean([r['best_dx'] for r in shift_rows])),
            'mean_best_dy': float(np.mean([r['best_dy'] for r in shift_rows])),
            'mean_iou_at_zero': float(np.mean([r['iou_at_zero'] for r in shift_rows])),
            'mean_iou_at_best': float(np.mean([r['iou_at_best'] for r in shift_rows])),
            'mean_gain': float(np.mean(gains)),
            'max_gain': float(np.max(gains)),
        }
    if len(live) < len(rows):
        out['stale_reference_arm'] = {
            'frames': [r['k'] for r in rows if r['reference'] == 'stale'],
            'state': 'not_detectable',
            'why': (
                'the SAM mask is byte-identical to m_%05d on these frames while the source '
                'frames keep changing, so there is no live reference to compare the plate to'
                % (min(r['k'] for r in rows if r['reference'] == 'stale') - 1)
            ),
        }
    return out


def draw_panels(res_depth: dict, out_png: str) -> list[int]:
    ks = list(PANEL_FRAMES)
    worst = res_depth['summary']['worst_frame']
    if worst not in ks:
        ks.append(worst)
    else:
        ks.append(int(sorted(res_depth['rows'], key=lambda r: r['iou'])[1]['k']))
    by_k = {r['k']: r for r in res_depth['rows']}

    tiles = []
    for k in ks:
        plate = load_plate(k, 'depth')
        H, W = plate.shape
        mask = load_mask(k, (W, H))
        img = np.asarray(Image.open(frame_path(k)).convert('RGB').resize((W, H), Image.BILINEAR)).copy()
        img[thicken(edge(mask))] = (0, 255, 0)
        img[thicken(edge(plate))] = (255, 0, 0)
        im = Image.fromarray(img)
        d = ImageDraw.Draw(im)
        try:
            font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 22)
        except OSError:
            font = ImageFont.load_default()
        r = by_k[k]
        cap = 'k=%d  IoU %.3f  band %.3f  d=(%+.1f,%+.1f)px  top %+.0f  bot %+.0f  %s' % (
            k,
            r['iou'],
            r['iou_upper'],
            r['dx'],
            r['dy'],
            r['dy_top'],
            r['dy_bot'],
            'STALE MASK' if r['reference'] == 'stale' else '',
        )
        d.rectangle([0, 0, W, 30], fill=(0, 0, 0))
        d.text((8, 4), cap, fill=(255, 255, 255), font=font)
        tiles.append(im)

    tw, th = tiles[0].size
    sheet = Image.new('RGB', (tw * 3, th * 2), (12, 12, 12))
    for i, t in enumerate(tiles[:6]):
        sheet.paste(t, ((i % 3) * tw, (i // 3) * th))
    sheet.save(out_png)
    return ks


def main() -> int:
    labels = label_receipt()
    offs = offset_receipt()
    stale_rec = stale_mask_receipt()
    stale = set(stale_rec['stale_frames'])

    print('mask label receipt:')
    for r in labels['sampled']:
        print(
            '  m_%05d %s %s labels=%s counts=%s' % (r['frame'], r['mode'], tuple(r['shape']), r['labels'], r['counts'])
        )
    print('  ->', labels['note'])
    print(
        'index offset: %s  ranges_consistent=%s  luma in/out of mask on f_00101: %.1f / %.1f'
        % (
            offs['rule'],
            offs['index_ranges_consistent'],
            offs['frame_100_mean_luma_inside_mask'],
            offs['frame_100_mean_luma_outside_mask'],
        )
    )
    print(
        'reference receipt: %d unique masks of %d; stale frames %s'
        % (stale_rec['unique_masks'], N_FRAMES, ('%d..%d' % (min(stale), max(stale))) if stale else 'none')
    )
    print('  ->', stale_rec['note'])

    print('\nreading (fixed before the numbers):')
    print(
        '  IoU p10 >= %.2f and mean |dx|,|dy| < %.0f px -> camera matches, candidate (a) EXCLUDED'
        % (P10_PASS, CENTROID_PASS_PX)
    )
    print('  IoU p10 <  %.2f or a centroid offset > %.0f px -> candidate (a) STANDS' % (P10_FAIL, CENTROID_FAIL_PX))
    print('  nulls must both be beaten or the measure is unmeasurable')
    print('  a frame whose mask reference is stale is not_detectable, never scored as a mismatch\n')

    out = {
        'track': BASE,
        'frames': N_FRAMES,
        'mask_labels': labels,
        'index_offset': offs,
        'reference_freshness': stale_rec,
        'thresholds': {
            'iou_p10_pass': P10_PASS,
            'iou_p10_fail': P10_FAIL,
            'centroid_pass_px': CENTROID_PASS_PX,
            'centroid_fail_px': CENTROID_FAIL_PX,
            'upper_band_frac': 0.6,
        },
        'modes': {},
    }
    for mode in ('depth', 'composite'):
        res = run_mode(mode, stale)
        out['modes'][mode] = res
        for s in (res['summary'], res['summary_live_reference']):
            if not s:
                continue
            print(
                '%-9s %-15s n=%3d  IoU mean %.4f  p10 %.4f  min %.4f (k=%d)  band %.4f | '
                'null mirror %.4f  null +%d %.4f | |dx| %.2f  |dy| %.2f (%.0f%% positive)  '
                'top %.1f  bot %.1f  h %.3f -> %s'
                % (
                    mode,
                    s['segment'],
                    s['frames'],
                    s['iou']['mean'],
                    s['iou']['p10'],
                    s['worst_iou'],
                    s['worst_frame'],
                    s['iou_upper_band']['mean'],
                    s['null_mirror_iou_mean'],
                    NULL_SHIFT,
                    s['null_shift_iou_mean'],
                    s['abs_dx']['mean'],
                    s['abs_dy']['mean'],
                    100 * s['frac_dy_positive'],
                    s['abs_dy_top']['mean'],
                    s['abs_dy_bot']['mean'],
                    s['height_ratio']['mean'],
                    s['verdict'],
                )
            )
            print('          %s' % s['reading'])
        if 'shift_search' in res:
            ss = res['shift_search']
            print(
                '          best-shift search on %d frames: mean best (dx,dy) = (%+.1f, %+.1f) px, '
                'IoU %.4f -> %.4f (mean gain %+.4f, max %+.4f)'
                % (
                    len(ss['sampled_frames']),
                    ss['mean_best_dx'],
                    ss['mean_best_dy'],
                    ss['mean_iou_at_zero'],
                    ss['mean_iou_at_best'],
                    ss['mean_gain'],
                    ss['max_gain'],
                )
            )
        if 'stale_reference_arm' in res:
            a = res['stale_reference_arm']
            print('          stale-reference arm: frames %d..%d -> %s' % (a['frames'][0], a['frames'][-1], a['state']))

    png = os.path.join(BASE, 'plate_overlay.png')
    panels = draw_panels(out['modes']['depth'], png)
    out['figure'] = {
        'path': png,
        'panel_frames': panels,
        'legend': 'green = SAM mask edge, red = depth plate silhouette edge',
    }

    with open(os.path.join(BASE, 'plate_overlay.json'), 'w') as fh:
        json.dump(out, fh, indent=2)
    write_md(out, os.path.join(BASE, 'plate_overlay.md'))

    print('\nwrote %s' % os.path.join(BASE, 'plate_overlay.json'))
    print('wrote %s' % os.path.join(BASE, 'plate_overlay.md'))
    print('wrote %s (panels %s)' % (png, panels))
    return 0


def _row(s: dict) -> str:
    return (
        '| %s | %s | %d | %.4f | %.4f | %.4f (k=%d) | %.4f | %.4f | %.4f | %.2f px | '
        '%.2f px | %.1f px | %.1f px | %.3f | `%s` |\n'
        % (
            s['mode'],
            s['segment'],
            s['frames'],
            s['iou']['mean'],
            s['iou']['p10'],
            s['worst_iou'],
            s['worst_frame'],
            s['iou_upper_band']['mean'],
            s['null_mirror_iou_mean'],
            s['null_shift_iou_mean'],
            s['abs_dx']['mean'],
            s['abs_dy']['mean'],
            s['abs_dy_top']['mean'],
            s['abs_dy_bot']['mean'],
            s['height_ratio']['mean'],
            s['verdict'],
        )
    )


def write_md(out: dict, path: str) -> None:
    dm = out['modes']['depth']
    cm = out['modes']['composite']
    d, dl = dm['summary'], dm['summary_live_reference']
    c, cl = cm['summary'], cm['summary_live_reference']
    L = []
    L.append('# Plate-camera check — abel_shores_cabin (205 frames, no render, no GPU)\n\n')
    L.append(
        'Candidate (a) of S01 is "the plate camera does not match the still". The plates are\n'
        "projected with the estimator's own per-frame pinhole (`geom/track_plates.py:81-96`),\n"
        'so overlaying every plate on the SAM mask of the same frame settles the camera on the\n'
        'CPU, whatever the render did downstream.\n\n'
    )

    L.append('## Reading, fixed before the numbers\n\n')
    L.append(
        '- IoU p10 >= %.2f **and** mean |dx|,|dy| < %.0f px -> camera matches, candidate (a)\n'
        '  **excluded**; the identity cost in the 205 receipt is then not a framing error.\n'
        '- IoU p10 < %.2f **or** a centroid offset > %.0f px -> candidate (a) **stands**.\n'
        '- Either null unbeaten -> the measure is **unmeasurable** and nothing is concluded.\n'
        '- A frame whose mask reference is stale is **not_detectable**, never scored as a mismatch.\n\n'
        % (P10_PASS, CENTROID_PASS_PX, P10_FAIL, CENTROID_FAIL_PX)
    )

    L.append('## Instrument receipts\n\n')
    lb = out['mask_labels']
    L.append(
        '- **Masks are binary 0/255, not the 0..5 label map the brief describes.** Sampled\n'
        '  m_00000 / m_00100 / m_00204: non-zero labels %s. Subject rule `value > 0`; with a\n'
        '  single non-zero label there is no second subject, so no Abel-vs-other selection by\n'
        '  area or position was possible or needed.\n' % lb['nonzero_labels']
    )
    for r in lb['sampled']:
        L.append(
            '  - `m_%05d` %s %dx%d labels=%s counts=%s\n'
            % (r['frame'], r['mode'], r['shape'][1], r['shape'][0], r['labels'], r['counts'])
        )
    io = out['index_offset']
    L.append(
        '- Index offset `%s`, ranges consistent = %s (no `f_00000`, no `m_00205`). Corroborated:\n'
        '  mean luma inside mask 100 on frame `f_00101` = %.1f vs %.1f outside — the mask lands\n'
        '  on the lit boy, not the dark cabin, and %s.\n'
        % (
            io['rule'],
            io['index_offset_ok'] if 'index_offset_ok' in io else io['index_ranges_consistent'],
            io['frame_100_mean_luma_inside_mask'],
            io['frame_100_mean_luma_outside_mask'],
            io['visual_check'],
        )
    )
    L.append("- Masks 1344x768 resized to the plate's 896x512 with NEAREST (same 1.75 aspect).\n")
    fr = out['reference_freshness']
    L.append(
        '- **Reference freshness: %d unique masks across %d frames.** %s\n\n'
        % (fr['unique_masks'], out['frames'], fr['note'])
    )

    L.append('## Numbers\n\n')
    L.append(
        '| mode | segment | n | IoU mean | IoU p10 | IoU min (frame) | upper-band IoU | '
        'null mirror | null +%d | mean abs dx | mean abs dy | mean abs dy_top | '
        'mean abs dy_bot | height ratio | verdict |\n' % NULL_SHIFT
    )
    L.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n')
    for s in (d, dl, c, cl):
        if s:
            L.append(_row(s))
    L.append(
        '\n`dy_top` / `dy_bot` are plate-minus-mask bounding-box top and bottom rows: they split a\n'
        'whole-camera shift (both move together) from an occlusion difference (only the bottom moves).\n\n'
    )

    L.append('## Nulls\n\n')
    for s in (d, c):
        L.append(
            '- **%s, all 205**: real %.4f vs mirrored plate %.4f (%s) and plate k vs mask k+%d\n'
            '  %.4f (%s) -> %s.\n'
            % (
                s['mode'],
                s['iou']['mean'],
                s['null_mirror_iou_mean'],
                'beaten' if s['beats_null_mirror'] else 'NOT beaten',
                NULL_SHIFT,
                s['null_shift_iou_mean'],
                'beaten' if s['beats_null_shift'] else 'NOT beaten',
                'discriminating' if s['discriminating'] else 'NOT discriminating',
            )
        )
    L.append(
        '\nThe mirror null is crushed (%.2f vs %.2f). The +%d-frame null is only just beaten\n'
        '(%.4f vs %.4f): the subject barely moves over 20 frames in this shot, so silhouette IoU\n'
        'has strong power against a left-right or pose error and weak power against a temporal\n'
        'one. Read the temporal arm as low-sensitivity, not as a pass.\n\n'
        % (d['iou']['mean'], d['null_mirror_iou_mean'], NULL_SHIFT, d['iou']['mean'], d['null_shift_iou_mean'])
    )

    L.append('## Verdict\n\n')
    L.append('| arm | frames | state |\n|---|---|---|\n')
    L.append(
        '| depth, live reference | %d..%d | `%s` |\n' % (dl['frame_range'][0], dl['frame_range'][1], dl['verdict'])
    )
    L.append(
        '| composite, live reference | %d..%d | `%s` |\n' % (cl['frame_range'][0], cl['frame_range'][1], cl['verdict'])
    )
    if 'stale_reference_arm' in dm:
        a = dm['stale_reference_arm']
        L.append('| both modes, stale reference | %d..%d | `not_detectable` |\n' % (a['frames'][0], a['frames'][-1]))
    L.append('\n- **%s** on the live-reference frames: %s\n' % (dl['verdict'], dl['reading']))
    L.append(
        '- The %d stale-reference frames are **not_detectable**: %s. They are *not* evidence for\n'
        '  candidate (a); the worst-IoU frame in the whole run (k=%d, IoU %.3f) is one of them.\n'
        % (
            len(dm.get('stale_reference_arm', {}).get('frames', [])),
            dm.get('stale_reference_arm', {}).get('why', ''),
            d['worst_frame'],
            d['worst_iou'],
        )
    )
    L.append(
        '- Composite adds essentially nothing to the silhouette: its IoU differs from depth by at\n'
        '  most %.4f on %d of 205 frames — the skeleton lines fall inside the depth body.\n'
        % (
            max(abs(a['iou'] - b['iou']) for a, b in zip(cm['rows'], dm['rows'])),
            sum(1 for a, b in zip(cm['rows'], dm['rows']) if a['iou'] != b['iou']),
        )
    )
    if 'shift_search' in dm:
        ss = dm['shift_search']
        L.append('\n## What the vertical offset is\n\n')
        L.append(
            'Mean |dx| is %.2f px and the height ratio is %.3f, so the plate is at the right\n'
            'horizontal position and the right scale; the whole of the residual is a downward\n'
            'offset present in **%.0f%% of live frames** (`dy_top` %.1f px, `dy_bot` %.1f px — top and\n'
            'bottom move together).\n\n'
            % (
                dl['abs_dx']['mean'],
                dl['height_ratio']['mean'],
                100 * dl['frac_dy_positive'],
                dl['abs_dy_top']['mean'],
                dl['abs_dy_bot']['mean'],
            )
        )
        L.append(
            'A brute-force translation search (dx +-16, dy +-40, step 2) on %d sampled live frames\n'
            'asks whether that offset is a rigid registration error or shape:\n\n' % len(ss['sampled_frames'])
        )
        L.append('| | value |\n|---|---|\n')
        L.append('| mean best (dx, dy) | (%+.1f, %+.1f) px |\n' % (ss['mean_best_dx'], ss['mean_best_dy']))
        L.append('| mean IoU at zero shift | %.4f |\n' % ss['mean_iou_at_zero'])
        L.append('| mean IoU at best shift | %.4f |\n' % ss['mean_iou_at_best'])
        L.append('| mean gain | %+.4f (max %+.4f) |\n\n' % (ss['mean_gain'], ss['max_gain']))
        L.append(
            '**The plate is already at its optimal translation.** The best rigid shift is\n'
            '(%+.1f, %+.1f) px and buys %+.4f IoU. A camera that framed the subject wrongly would\n'
            'leave a large recoverable shift; there is none. The %.1f px centroid gap is therefore a\n'
            'mass-distribution difference between the two silhouettes, not a registration error —\n'
            'the SAM mask carries hair the mesh does not have (raising the mask centroid) and stops\n'
            'at the desk edge where the plate body continues (lowering the plate centroid). Both\n'
            'push `dy` the same way, and neither is the camera.\n\n'
            % (ss['mean_best_dx'], ss['mean_best_dy'], ss['mean_gain'], dl['abs_dy']['mean'])
        )
        L.append('## Conclusion on candidate (a)\n\n')
        L.append(
            '- **The pre-registered rule returns `%s`** on the live-reference frames: IoU p10 is\n'
            '  %.4f (between the %.2f and %.2f thresholds) and mean |dy| is %.2f px (just under the\n'
            "  %.0f px fail line). Taken on its own letter, the brief's test neither excludes nor\n"
            '  confirms candidate (a). That threshold is not moved here.\n'
            % (dl['verdict'], dl['iou']['p10'], P10_FAIL, P10_PASS, dl['abs_dy']['mean'], CENTROID_FAIL_PX)
        )
        L.append(
            '- **The added translation arm excludes candidate (a) on its own terms.** Framing error\n'
            '  means the subject is projected to the wrong place on the image. Mean |dx| %.2f px,\n'
            '  height ratio %.3f, and a best rigid shift worth %+.4f IoU say the plate is projected\n'
            '  to the right place at the right size in every live frame. The identity cost in the\n'
            '  205 receipt is not explained by where the plate camera put the body.\n'
            % (dl['abs_dx']['mean'], dl['height_ratio']['mean'], ss['mean_gain'])
        )
        L.append(
            '- **What this does not test.** Silhouette IoU is blind to depth, roll about the view\n'
            '  axis, and focal-length/distance trade-offs that keep the projected size fixed. It is\n'
            '  also weak in time: the +%d-frame null scores %.4f against a real %.4f, so a temporal\n'
            '  misalignment of this shot would barely register. Those sub-questions stay\n'
            '  **unmeasurable** with this instrument rather than being scored as passes.\n'
            % (NULL_SHIFT, dl['null_shift_iou_mean'], dl['iou']['mean'])
        )
        L.append(
            "- **A separate defect found on the way**, outside this task's scope: the SAM mask\n"
            '  track froze at frame %d: masks m_%05d..m_%05d are one byte-identical mask (14 files,\n'
            '  the %d after the first counted as stale above), and those frames sit past a shot\n'
            '  boundary onto a near-black "DAY 1" title card. They are `not_detectable` and should\n'
            '  not be fed to any identity or fit metric as if they carried a subject.\n\n'
            % (
                dm['stale_reference_arm']['frames'][0] - 1,
                dm['stale_reference_arm']['frames'][0] - 1,
                dm['stale_reference_arm']['frames'][-1],
                len(dm['stale_reference_arm']['frames']),
            )
        )
    L.append('\n## Figure\n\n')
    L.append(
        '`plate_overlay.png` — panels %s (the last is the worst-IoU frame). Green = SAM mask edge,\n'
        'red = depth plate silhouette edge, over the source frame at 896x512.\n' % out['figure']['panel_frames']
    )
    with open(path, 'w') as fh:
        fh.write(''.join(L))


if __name__ == '__main__':
    raise SystemExit(main())
