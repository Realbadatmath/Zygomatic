# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Re-measure the PRODUCTION screen (kids_video_service.vlm_defects + judge_description)
on the calibration labels plus a live song's receipts. Writes screen_recheck_<tag>.json.
Live receipts are 320 px (the full frames were deleted) — upscaled, a harder read."""

import json
import os
import random
import sys
import time

from zyg_workflows import kids_video_service as KV
from zyg_workflows.tools import kidsvideo_vlm_defect_probe as P
from zyg_workflows import paths

# Both modules above now import as package modules, so the two sys.path inserts
# that used to precede them are gone; CREWS only names the frame/score data.
CREWS = str(paths.ZYG_CREWS_ROOT)

OUT = os.path.join(CREWS, 'output/kidsmusic/_frame_defect_bench')
LIVE = os.path.join(CREWS, 'output/kidsmusic/7a9514bf0b42/frames')
LIVE_POS = ['f012_c1', 'f042_c1']  # merged front wheels; "Hello" speech bubble
LIVE_NEG = ['f016_c0', 'f025_c1', 'f033_c1', 'f037_c0', 'f052_c0', 'f015_c0', 'f049_c0', 'f039_c1', 'f054_c1']


def main(tag):
    rows = json.load(open(os.path.join(OUT, 'scores.json')))
    rnd = random.Random(7).sample(rows, 36)
    neg = []
    for i, r in enumerate(rnd):
        k = f'{r["job"][:6]}/{os.path.basename(r["path"])[:-4]}'
        if i not in (1, 12) and k not in P.POS:
            neg.append(k)
    for r in random.Random(11).sample(rows, 40):
        k = f'{r["job"][:6]}/{os.path.basename(r["path"])[:-4]}'
        if k not in P.POS and k not in neg and len(neg) < 50:
            neg.append(k)
    items = [('cal', 'defect', P.find(k)[0], k) for k in P.POS] + [('cal', 'clean', P.find(k)[0], k) for k in neg]
    items += [('live', 'defect', os.path.join(LIVE, 'rejected', k + '.jpg'), k) for k in LIVE_POS]
    items += [('live', 'clean', os.path.join(LIVE, 'rejected', k + '.jpg'), k) for k in LIVE_NEG]
    xs = sorted(os.listdir(os.path.join(LIVE, 'excess')))[:20]
    items += [('live', 'clean', os.path.join(LIVE, 'excess', f), f[:-4]) for f in xs]
    out = []
    for grp, label, path, k in items:
        t0 = time.time()
        why, raw = KV.vlm_defects(path)
        out.append(
            {
                'group': grp,
                'label': label,
                'key': k,
                'flag': bool(why),
                'why': why,
                'seconds': round(time.time() - t0, 2),
            }
        )
        print(grp, label, k, bool(why), (why or '')[:2] if why else '', flush=True)
    summ = {}
    for grp in ('cal', 'live'):
        g = [o for o in out if o['group'] == grp]
        summ[grp] = {
            'hits': f'{sum(o["flag"] for o in g if o["label"] == "defect")}/{sum(o["label"] == "defect" for o in g)}',
            'false_alarms': f'{sum(o["flag"] for o in g if o["label"] == "clean")}/{sum(o["label"] == "clean" for o in g)}',
        }
    print(summ)
    json.dump({'summary': summ, 'rows': out}, open(os.path.join(OUT, f'screen_recheck_{tag}.json'), 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1])
