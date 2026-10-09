#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Archive (or restore) storyteller characters — reversible move, no deletion.

Moves a character's dataset dir and LoRA output dir into `_archived/`
subfolders. Archived characters disappear from the library UI but REMAIN in
the dedup comparison set (the gates scan `_archived/` too), so a new run can
never silently recreate an archived face.

Usage:
    archive_character.py <char_id> [<char_id> ...]
    archive_character.py --restore <char_id> [...]
"""

import os
import shutil
import sys

from zyg_workflows import paths

DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars')


def _move(src: str, dst: str) -> bool:
    if not os.path.isdir(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        print(f'  SKIP {src} → {dst} (destination exists)')
        return False
    shutil.move(src, dst)
    print(f'  moved {src} → {dst}')
    return True


def main() -> None:
    args = [a for a in sys.argv[1:] if a != '--restore']
    restore = '--restore' in sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    for cid in args:
        cid = cid.strip()
        print(f'{"Restoring" if restore else "Archiving"} {cid}:')
        moved = 0
        for root in (DATASET_ROOT, OUTPUT_ROOT):
            live = os.path.join(root, cid)
            arch = os.path.join(root, '_archived', cid)
            src, dst = (arch, live) if restore else (live, arch)
            if _move(src, dst):
                moved += 1
        if not moved:
            print('  nothing to move (already done, or unknown char_id)')


if __name__ == '__main__':
    main()
