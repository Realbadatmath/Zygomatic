# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Imports, env helpers and the shared module constants (original lines 1-107).

Split out of wan_vace_service.py; `_zyg_log`'s name and `_HERE`'s depth are
re-anchored to the original module path so both are unchanged by the split.
"""

# ruff: noqa: F401  -- this module IS the original top import block: the sibling
#   modules and the package __init__ re-import os/math/shutil/Image/ImageDraw/
#   ImageFilter/exe from here, so none of them is unused.

import os
import math
import shutil

from PIL import Image, ImageDraw, ImageFilter
from zyg_workflows.bin import exe

# ── QC block signal (fail-safe import) ───────────────────────────────────────
# qc_contract.QCBlocked derives from BaseException on purpose so that the
# fail-safe `except Exception` handlers in this file cannot silently convert a
# deliberate mode=block stop into a shrug. The fallback below is a private class
# that nothing raises, so behaviour is unchanged if qc_contract is unavailable.
try:
    from zyg_workflows.qc_contract import QCBlocked as _QCBlocked
except Exception:  # pragma: no cover

    class _QCBlocked(BaseException):
        pass


import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.wan_vace_service')


_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_T2V_MODEL = os.environ.get('ZYG_WAN_T2V_MODEL', 'Wan2_1-T2V-14B_fp8_e4m3fn.safetensors')
_VACE_MODULE = os.environ.get('ZYG_WAN_VACE_MODULE', 'Wan2_1-VACE_module_14B_fp8_e4m3fn.safetensors')


# curated static-shot negative lives in wan_video_service — reuse it
def _static_neg():
    """2026-07-31 — ZYG_NEG_ALLOW_FACE_MOTION=1 strips 'changing face' (and its Chinese
    equivalent) from the static negative. The operator's note on v6-vs-v9 was that the
    characters look lifeless with their eyes shut: a BLINK IS BY DEFINITION A CHANGING
    FACE, so this term suppresses exactly the micro-performance that made v6 feel alive
    (measured: Abel's face region moved 0.810 in v6 vs 0.180 in v9). Identity is already
    carried by the character LoRAs and the VACE refs, so dropping it here is cheap; the
    rest of the static negative (camera moves, morphing background, extra limbs) stays."""
    try:
        from zyg_workflows import wan_video_service as W

        neg = W._STATIC_SHOT_NEG
        if os.environ.get('ZYG_NEG_ALLOW_FACE_MOTION', '0') == '1':
            for term in ('changing face, ', 'changing face', '变脸, ', '变脸'):
                neg = neg.replace(term, '')
            neg = neg.replace(', ,', ',').strip().strip(',')
        return neg
    except Exception:
        return (
            'camera movement, camera pan, camera zoom, push in, morphing background, '
            'warping, objects changing, flickering, changing face, photorealistic'
        )


def _log_noop(_m):
    pass


def _env_flag(name, default='0'):
    return str(os.environ.get(name, default)).strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name, default):
    try:
        return int(float(str(os.environ.get(name, '') or default)))
    except (TypeError, ValueError):
        return int(default)


def _env_float(name, default):
    try:
        return float(str(os.environ.get(name, '') or default))
    except (TypeError, ValueError):
        return float(default)
