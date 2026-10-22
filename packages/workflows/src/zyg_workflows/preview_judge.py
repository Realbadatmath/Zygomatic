# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""preview_judge.py — tier-0 VLM triage of live TAESD previews (2026-07-30).

comfy_preview_watcher.py writes <run_dir>/preview_latest.jpg while a render is
in flight.  This process reads that file every --interval seconds and asks a
SMALL local VLM the 'catastrophic_preview' checklist — the only early look we
get at the later context windows of an uninterruptible ~90-minute render (the
13.2 s pipe morph lived exactly where the 81-frame probe cannot see).

HARD RULES (do not soften these):
  * CPU BY DEFAULT.  The render owns the GPU (~33 GB, uninterruptible).  The
    worker is launched with CUDA_VISIBLE_DEVICES='' so it physically cannot
    take VRAM.  ZYG_PREVIEW_JUDGE_GPU=1 opts into GPU residency — only sane
    once the resident tier has been measured against the VAE-decode spike.
  * ADVISORY ONLY.  On a critical failure this writes <run_dir>/PREVIEW_ALERT
    and keeps going.  It NEVER interrupts, kills or /free's anything: judging
    blurry partial-denoise previews is unvalidated territory (blur is the worst
    documented VLM corruption class) and a false positive would destroy
    unrecoverable render progress.  Drivers/operators poll the alert file.
  * --alert-streak consecutive critical ticks are required before the alert is
    written, because one bad blurry tick is noise, not evidence.

Usage (from a driver, best-effort, alongside comfy_preview_watcher.py):
    subprocess.Popen([sys.executable, 'preview_judge.py', out_dir,
                      '--interval', '180'], start_new_session=True)
Standalone: python preview_judge.py <run_dir> [--interval 180] [--tier cpu]

Output: <run_dir>/preview_judge.jsonl (one verdict record per tick),
        <run_dir>/preview_judge/ (the judged preview copies),
        <run_dir>/PREVIEW_ALERT   (written once, on a critical streak).
Stops on --max-minutes, on <run_dir>/PREVIEW_JUDGE_STOP, or after
--max-unavailable consecutive ticks with no judge installed.
"""

import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)


def _default_tier():
    return 'resident' if os.environ.get('ZYG_PREVIEW_JUDGE_GPU', '0') == '1' else 'cpu'


if __name__ == '__main__':  # the CLI lives in preview_judge_cli
    from zyg_workflows.preview_judge_cli import main as _cli_main

    raise SystemExit(_cli_main())
