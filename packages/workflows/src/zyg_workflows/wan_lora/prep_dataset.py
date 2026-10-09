#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""prep_dataset.py — build a musubi-tuner image dataset for a Wan character LoRA.

Usage: prep_dataset.py <char_id> <trigger_token>
Copies the character's 48-angle ARCANE cells (the research-recommended 25-40+ image set,
which doubles as a style anchor against Wan's photoreal pull), writes caption .txt files,
and emits dataset.toml. Output: ZYG_LORA_DATASETS/wan_chars/<char_id>/
"""

import json
import os
import shutil
import sys
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


CHARS_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
OUT_ROOT = str(paths.ZYG_LORA_DATASETS / 'wan_chars')


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
