# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The module-level constants and the shared logger (vfx_fx.py lines 46-74).

HERE is the one line that could not move verbatim: the original vfx_fx.py sat
directly in zyg_workflows/, so `dirname(abspath(__file__))` WAS the package
directory that holds data/.  This file sits one level deeper, inside
vfx_fx/, so it takes one more dirname to name the same directory.  Every
path derived from it — DATA, LIBS, RUNTIME, PRESETS, LUTDIR, JOBLOG — is
therefore unchanged.  _zyg_log likewise asks for __package__ rather than
__name__ so the logger keeps its original name, 'zyg_workflows.vfx_fx'.
"""

from __future__ import annotations

import os
import shutil
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__ or 'zyg_workflows.vfx_fx')


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, 'data')
LIBS = os.path.join(DATA, 'asset_libraries')
RUNTIME = os.path.join(DATA, 'runtime')
PRESETS = os.path.join(RUNTIME, 'vfx_fx_presets.json')
LUTDIR = os.path.join(DATA, 'assets', 'luts')
JOBLOG = os.path.join(RUNTIME, 'vfx_fx_jobs')

FFMPEG = shutil.which('ffmpeg') or 'ffmpeg'
FFPROBE = shutil.which('ffprobe') or 'ffprobe'

# The derived rows all land in one pack so the rail groups them together and a
# licence read never has to guess which of 209 rows someone edited.
DERIVED_PACK = 'Derived — Studio edits'
