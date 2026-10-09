#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Backfill the trained alpha into already-exported character LoRAs.

WHY: SimpleTuner's export carries no `.alpha` entries, so ComfyUI
(comfy/weight_adapter/lora.py) uses `scale = 1.0` instead of `alpha/rank` and
applies the adapter at 2x its trained strength. See
lora_trainer_service.stamp_lora_alpha for the full account and the measurement.

READ THIS BEFORE USING --apply ON THE EXISTING CAST
    Stamping CHANGES HOW AN EXISTING LoRA RENDERS. Today an unstamped LoRA at
    lora_scale 0.85 lands at an effective 0.85. Once stamped it lands at
    0.85 x (alpha/rank) = 0.425 — half. That is the correct strength, but it is
    not the strength the existing characters were reviewed and approved at.
    New LoRAs are stamped at export by the trainer, so they are unaffected.

    Safe: --root .../medusa_training (not wired to any render path).
    Needs a deliberate decision: storyteller_chars, creatures, wan_chars.

Usage:
    stamp_lora_alphas.py                      # dry run over every root
    stamp_lora_alphas.py --root <dir>         # dry run, one tree
    stamp_lora_alphas.py --root <dir> --apply # stamp for real
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from zyg_workflows import paths

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows.lora_trainer_service import _read_trained_scale, stamp_lora_alpha  # noqa: E402

DEFAULT_ROOT = str(paths.ZYG_LORA_OUTPUTS)


def scan(root: str) -> list[str]:
    return sorted(glob.glob(os.path.join(root, '**', '*.safetensors'), recursive=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=DEFAULT_ROOT)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    from safetensors import safe_open

    stamped = already = no_cfg = failed = 0
    for p in scan(args.root):
        try:
            with safe_open(p, 'pt') as fh:
                if any(k.endswith('.alpha') for k in fh.keys()):
                    already += 1
                    continue
        except Exception as exc:
            print(f'  UNREADABLE {p}: {exc}')
            failed += 1
            continue

        ra = _read_trained_scale(os.path.dirname(p))
        if not ra:
            no_cfg += 1
            print(f'  no rank/alpha  {os.path.relpath(p, args.root)}')
            continue
        rank, alpha = ra
        rel = os.path.relpath(p, args.root)
        if not args.apply:
            print(f'  would stamp    alpha={alpha:g} rank={rank} scale={alpha / rank:g}  {rel}')
            stamped += 1
            continue
        if stamp_lora_alpha(p):
            print(f'  STAMPED        scale={alpha / rank:g}  {rel}')
            stamped += 1
        else:
            failed += 1

    verb = 'stamped' if args.apply else 'would stamp'
    print(f'\n{verb}: {stamped}   already stamped: {already}   no rank/alpha recorded: {no_cfg}   failed: {failed}')
    if not args.apply and stamped:
        print(
            'dry run — re-run with --apply to write. Read the module '
            'docstring first: stamping changes how an existing LoRA renders.'
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
