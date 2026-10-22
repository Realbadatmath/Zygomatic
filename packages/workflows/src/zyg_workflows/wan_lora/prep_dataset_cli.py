# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.wan_lora.prep_dataset`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.wan_lora.prep_dataset` still reaches it.
"""

import json
import os
import shutil
import sys

from zyg_workflows.wan_lora.prep_dataset import (
    CHARS_ROOT,
    OUT_ROOT,
    _zyg_log,
)


def main():
    cid, trigger = sys.argv[1], sys.argv[2]
    src = os.path.join(CHARS_ROOT, cid, 'arcane_instantid')
    cells = sorted(f for f in os.listdir(src) if f.startswith('cell_') and f.endswith('.png'))
    if len(cells) < 10:
        raise SystemExit(f'only {len(cells)} cells — not enough')
    # identity phrase from the bible
    desc = ''
    try:
        with open(os.path.join(CHARS_ROOT, cid, 'character_bible.json'), encoding='utf-8') as f:
            b = json.load(f)
        ident = b.get('identity') or {}
        age = ident.get('age')
        sex = str(ident.get('sex') or ident.get('gender') or 'male').lower()
        noun = 'man' if sex.startswith('m') else 'woman'
        try:
            if age and int(age) < 18:
                noun = 'teenage boy' if noun == 'man' else 'teenage girl'
        except (TypeError, ValueError) as _exc:
            _zyg_log.warning('age %r is not a number, captioning %s as an adult: %s', age, cid, _exc)
        desc = f'a {age} year old {noun}' if age else f'a {noun}'
    except Exception:
        desc = 'a person'
    dst = os.path.join(OUT_ROOT, cid, 'images')
    os.makedirs(dst, exist_ok=True)
    cap = f'{trigger}, {desc}, 17th century attire, arcane oil painting style, painterly'
    for c in cells:
        shutil.copy2(os.path.join(src, c), os.path.join(dst, c))
        with open(os.path.join(dst, c.replace('.png', '.txt')), 'w', encoding='utf-8') as f:
            f.write(cap)
    toml = os.path.join(OUT_ROOT, cid, 'dataset.toml')
    with open(toml, 'w', encoding='utf-8') as f:
        f.write(f'''[general]
resolution = [960, 960]
caption_extension = ".txt"
batch_size = 1
enable_bucket = true
bucket_no_upscale = false

[[datasets]]
image_directory = "{dst}"
cache_directory = "{os.path.join(OUT_ROOT, cid, 'cache')}"
num_repeats = 1
''')
    print(f'dataset ready: {len(cells)} images, caption="{cap}"')
    print(f'toml: {toml}')


if __name__ == '__main__':
    main()
