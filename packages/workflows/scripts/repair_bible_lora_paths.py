#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One-shot repair (2026-07-18): re-point character bibles at LoRA weights
that actually exist on disk.

Background: training recorded checkpoint-XXXX paths chosen mid-run; the
post-training cleanup (and the 2026-07-16 509 GB manual sweep) deleted those
checkpoint dirs while keeping the root end-of-run export — leaving every
trained character's ``conditioning.lora_path`` dangling, so ComfyGen silently
rendered without the LoRA. The trainer now records the surviving root export
(lora_trainer_service 2026-07-18 fix); this script heals the already-written
bibles. Idempotent — safe to re-run.
"""

import json
import os
import sys

from zyg_workflows import paths

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import character_bible_service as cbs  # noqa: E402
from zyg_workflows import character_lora_family as clf  # noqa: E402

DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

KEYS = {
    'flux': ('flux_lora_path', 'lora_path'),
    'sdxl': ('sdxl_lora_path',),
}


def main() -> None:
    repaired, cleared, ok, no_bible = 0, 0, 0, 0
    for cid in sorted(os.listdir(DATASET_ROOT)):
        bible_path = os.path.join(DATASET_ROOT, cid, 'character_bible.json')
        if not os.path.isfile(bible_path):
            no_bible += 1
            continue
        try:
            with open(bible_path, encoding='utf-8') as fh:
                cond = json.load(fh).get('conditioning') or {}
        except Exception as exc:
            print(f'{cid}: unreadable bible ({exc})')
            continue
        # SDXL first — update_lora keeps FLUX primary for the shared lora_path.
        for fam in ('sdxl', 'flux'):
            recorded = ''
            for key in KEYS[fam]:
                recorded = str(cond.get(key) or '').strip()
                if recorded:
                    break
            dangling = bool(recorded) and not os.path.isfile(recorded)
            resolved = clf.resolve_char_lora_path(
                cid,
                fam,
                preferred_path=recorded or None,
            )
            if resolved and os.path.isfile(resolved):
                if resolved != recorded:
                    cbs.update_lora(cid, resolved, model_family=fam)
                    print(f'{cid} [{fam}]: {"DANGLING" if dangling else "stale"} → {resolved}')
                    repaired += 1
                else:
                    ok += 1
            elif dangling:
                # Nothing on disk at all — null the reference so consumers
                # stop trusting a deleted file.
                cbs.update_lora(cid, None, model_family=fam)
                print(f'{cid} [{fam}]: DANGLING, no weights on disk → cleared')
                cleared += 1
    print(f'\nDone: {repaired} repaired, {cleared} cleared, {ok} already OK, {no_bible} dirs without bible')


if __name__ == '__main__':
    main()
