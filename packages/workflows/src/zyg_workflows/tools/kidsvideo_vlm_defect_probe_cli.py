# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.kidsvideo_vlm_defect_probe`, moved out of the library
module so that library code never prints; `python -m
zyg_workflows.tools.kidsvideo_vlm_defect_probe` still reaches it.
"""

import json
import os
import random
import sys

from zyg_workflows.tools.kidsvideo_vlm_defect_probe import MODEL, OUT, POS, PX, ask, find


def main():
    rows = json.load(open(os.path.join(OUT, 'scores.json')))
    rnd = random.Random(7).sample(rows, 36)
    neg = []
    for i, r in enumerate(rnd):
        key = f'{r["job"][:6]}/{os.path.basename(r["path"])[:-4]}'
        if i in (1, 12) or key in POS:  # 1 = peekaboo bush-face (ambiguous), 12 = frog-snail
            continue
        neg.append(key)
    extra = random.Random(11).sample(rows, 40)
    for r in extra:
        key = f'{r["job"][:6]}/{os.path.basename(r["path"])[:-4]}'
        if key not in POS and key not in neg and len(neg) < 50:
            neg.append(key)
    out = []
    ask(*find(neg[0]))  # warm the model; not scored
    for label, keys in (('defect', list(POS)), ('clean', neg)):
        for k in keys:
            p, idea = find(k)
            v, s = ask(p, idea)
            out.append({'key': k, 'label': label, 'idea': idea, 'vlm': v, 'seconds': s, 'truth': POS.get(k, '')})
            print(label, k, v, s, flush=True)
    tp = sum(1 for o in out if o['label'] == 'defect' and o['vlm'].get('defect') is True)
    fp = sum(1 for o in out if o['label'] == 'clean' and o['vlm'].get('defect') is True)
    npos = sum(1 for o in out if o['label'] == 'defect')
    nneg = len(out) - npos
    summ = {
        'model': MODEL,
        'px': PX,
        'hits': f'{tp}/{npos}',
        'false_alarms': f'{fp}/{nneg}',
        'median_s': sorted(o['seconds'] for o in out)[len(out) // 2],
    }
    print(summ)
    json.dump(
        {'summary': summ, 'rows': out},
        open(
            os.path.join(OUT, f'vlm_probe_v{os.environ.get("PROBE_VARIANT", "1")}_{MODEL.replace(":", "_")}_{PX}.json'),
            'w',
        ),
        indent=1,
    )


if __name__ == '__main__':
    sys.exit(main())
