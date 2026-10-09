# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401,E402  - a re-export facade: the package API is what the old module bound.
"""audio_mix.py — Narration + ambience mixing/mastering chain (2026-07-30).

WHY this module exists
----------------------
The Second Ledger (1672 Dutch drama) needs a narration-over-ambience audio
stack that is safe for COMMERCIAL publication: every processing step here is
pure ffmpeg-as-a-subprocess-tool (no bundled codec/library code enters the
published audio), so no GPL/AGPL/NC component ever touches the deliverable.
No new Python deps; CPU-only (a GPU render may be running — nothing here may
touch CUDA, restart services, or kill processes).

Design decisions (learned the hard way):
  * loudnorm is ALWAYS two-pass.  Single-pass loudnorm runs a dynamic AGC
    that audibly pumps through the deliberate dramatic pauses in narration.
    Pass 1 measures (print_format=json, parsed from stderr), pass 2 applies
    linear gain with the measured values.  linear=true is a REQUEST, not a
    guarantee: ffmpeg silently reverts to dynamic AGC when measured LRA
    exceeds the target LRA or the linear gain would breach TP — so pass 2
    raises the LRA target above the measured value (linear-eligibility
    bound only), runs print_format=json at info loglevel, and reports the
    verified 'normalization_type' to the caller.
  * Ducking uses sidechaincompress with an asplit key tap; the final amix
    MUST carry normalize=0 (amix's default input scaling would re-lower the
    voice we just normalized) and duration=first (VO timeline is the program
    length; a long bed must not stretch the episode).
  * master() targets -14 LUFS / -1 dBTP: YouTube normalizes DOWN to ~-14
    but never boosts, so delivering quieter than -14 permanently loses
    loudness.  Mono masters are measured dual_mono=true so the dual-mono
    stereo upmix (pan c0->both) still lands on target (BS.1770 sums
    channels: naive mono->-14 then upmix would publish at ~-11).
  * Bed layers shorter than the program are looped with tail-to-head
    acrossfades (no clicks), by feeding the file N times as separate inputs
    (asplit fan-out into acrossfade can stall on unbalanced consumption).

All ffmpeg calls: -y -loglevel error with stderr captured for diagnostics
(exception: both loudnorm passes and ebur128 measurement need -loglevel
info, because those filters print their stats at info level).

Every public function returns out_path on success and None on failure
(loudnorm_two_pass returns {'out', 'measured', 'normalization_type',
'lra_eff'}); details go to log_fn.

CLI self-test:  python3 audio_mix.py --selftest <out_dir>
"""

from __future__ import annotations

import os
import logging as _zyg_logging

from zyg_workflows.bin import exe
from zyg_workflows.paths import ZYG_TMP_DIR

from zyg_workflows.audio_mix.chain import (
    _zyg_log,
    _log_noop,
    _run,
    _ffmpeg,
    _ok_output,
    probe_duration,
    _probe_audio_props,
    _ensure_48k_mono,
    measure_lufs,
    loudnorm_two_pass,
    _loop_layer_filter,
    prep_bed,
    duck_mix,
    _scratch_dir,
)

from zyg_workflows.audio_mix.mastering import (
    fade_out,
    master,
    _SILENT_LUFS,
    is_silent,
    level_to,
    mux_onto_video,
)

from zyg_workflows.audio_mix.cli import (
    _selftest,
    main,
)
