# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.plate_overlay_check`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.geom.plate_overlay_check` still reaches it.
"""

import json
import os
import sys

from zyg_workflows.geom.plate_overlay_check import (
    BASE,
    CENTROID_FAIL_PX,
    CENTROID_PASS_PX,
    N_FRAMES,
    NULL_SHIFT,
    P10_FAIL,
    P10_PASS,
    draw_panels,
    label_receipt,
    offset_receipt,
    run_mode,
    stale_mask_receipt,
    write_md,
)


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


if __name__ == '__main__':
    sys.exit(main())
