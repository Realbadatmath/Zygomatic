# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Module-wide constants, the work dir and the resource fences."""

import logging as _zyg_logging
import re
import threading

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.sfx_merger')

# _HERE was sfx_merger.py's own directory — the zyg_workflows package directory.
_HERE = str(paths.PKG_DIR)
_WORK = str(paths.DATA_DIR / 'runtime' / 'sfx_merger')
_SR = 48000
_MERGED_CAT = 'merged'
MAX_ITEMS = 40
MAX_SLOTS = 10  # per-layer effect chain — matches the mixer's slot list
_FF_TIMEOUT = 120
_MIX_TTL = 3 * 86400  # rendered mixes are re-creatable from the recipe
_STEM_TTL = 14 * 86400
# TTLs alone do not bound the work dir: one session laying 3-minute beds writes
# ~30 MB per stem and per mix (48 kHz stereo f32/s16), so a busy afternoon is
# gigabytes. Oldest-first eviction above this budget, on the same throttle.
_BUDGET_BYTES = 6 * 1024**3
_SWEEP_EVERY = 120.0
_SWEEP = {'ts': 0.0}
_LOCKS = {}  # render key -> Lock, so two clients cannot race one file
_LOCKS_GUARD = threading.Lock()
# Resource fences — this is an unauthenticated LAN server. A layer or a merge
# longer than ten minutes is not sound design, and the peak pass streams in
# blocks so a long merge never sits in RAM whole; at most three ffmpeg renders
# run at once.
_MAX_LAYER_S = 600.0
_MAX_MIX_S = 600.0
_MAX_START_S = 600.0
_RENDER_SEM = threading.BoundedSemaphore(3)
_REL_RE = re.compile(
    r'^(stems|mixes)/[a-f0-9]{16,40}\.wav$'
    r'|^analysis/[a-f0-9]{16,40}\.png$'
    r'|^exports/[a-f0-9]{16,40}\.(wav|flac|mp3|ogg|opus|aiff)$'
)
