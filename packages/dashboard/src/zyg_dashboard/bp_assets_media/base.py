# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import logging as _zyg_logging
import json
import os
import re
import subprocess
import time
import threading
from datetime import datetime, timezone
from flask import (
    Blueprint,
    jsonify,
    request,
    send_file,
    send_from_directory,
)
from zyg_workflows.bin import exe
from zyg_dashboard import paths
from zyg_dashboard.cors import apply_cors

# ruff: noqa: E402,F401  this module inherits the original top import block; its names are
# imported by the sibling section modules, so ruff must not prune them.

bp = Blueprint('assets_media', __name__)
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _runtime_path  # noqa: E402
from zyg_dashboard.gui.timeutil import _AMS_TZ, _ams_now  # noqa: E402
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    _ASSETS_REACTION_DIR,
    _ASSETS_SFX_DIR,
    _CLIPS_OUTPUT_DIR,
    _SV_STATUS_FILE,
    _TSTORE_FILE,
    _YT_TOKEN_FILE,
    _YT_UPLOAD_SCRIPT,
    _YT_VENV_PYTHON,
    _agent_log,
    _register_prompt,
    _zero_claim_batch_slot,
    limiter,
)
from zyg_dashboard import crewai_web_gui as _main_mod  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_assets_media')  # channel kept from the pre-split module


# runtime-conditional names (bound in main inside try/except — tolerant binding,
# matching the original graceful-degradation semantics):
_CDR_OK = getattr(_main_mod, '_CDR_OK', None)
_cdr = getattr(_main_mod, '_cdr', None)
_cdr_e_str = getattr(_main_mod, '_cdr_e_str', None)

# Flask resolves root_path from the import_name, which is now this sub-package; pin it to
# the directory bp_assets_media.py lived in, the value the Blueprint had before the split.
bp.root_path = str(paths.PKG_DIR)
