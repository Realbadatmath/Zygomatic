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

import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


CHARS_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
OUT_ROOT = str(paths.ZYG_LORA_DATASETS / 'wan_chars')


if __name__ == '__main__':  # the CLI lives in prep_dataset_cli
    from zyg_workflows.wan_lora.prep_dataset_cli import main as _cli_main

    raise SystemExit(_cli_main())
