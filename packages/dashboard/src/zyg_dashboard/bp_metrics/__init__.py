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
from flask import (
    Blueprint,
    jsonify,
    request,
)
from zyg_workflows import gui_state

bp = Blueprint('metrics', __name__)
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    _METRICS_PIPELINE_LABELS,
    _char_reload_jobs_from_disk,
    _char_state_path,
    limiter,
)
from zyg_dashboard.gui.controller import controller  # noqa: E402
from zyg_dashboard.gui.runtime_state import _runtime_path, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.telemetry import _read_local_telemetry  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso, _parse_iso_to_ams  # noqa: E402
from zyg_dashboard import crewai_web_gui as _main_mod  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first

_zyg_log = _zyg_logging.getLogger(__name__)


# runtime-conditional names (bound in main inside try/except — tolerant binding,
# matching the original graceful-degradation semantics):
_dsl = getattr(_main_mod, '_dsl', None)


# P-03 (2026-08-25): cost / wattage / VRAM aggregation ingested smoke and
# gatecheck states (3 stills, silent narration) as production samples. The
# shared filter lives in pipeline_common; lazy import keeps blueprint order.
def _recent_state_files(pattern, limit=0):
    from zyg_workflows.pipeline_common import recent_state_files

    return recent_state_files(pattern, limit=limit)


# ruff: noqa: F401  (this module re-does the original top import block so that every
# old `bp_metrics.<name>` attribute access still resolves, and re-exports every name
# the single file defined; none of it is used here.)

# 2026-10-07 modularization: the 1,319-line bp_metrics.py became this package. The
# header, the import block and `bp` stay here, at the top, BEFORE the sections are
# imported: crewai_web_gui does `from zyg_dashboard.bp_metrics import bp` at its own
# bottom, so when this package is what pulls crewai_web_gui in, `bp` has to already be
# an attribute of a half-initialised zyg_dashboard.bp_metrics — exactly the ordering
# the single file had.
from zyg_dashboard.bp_metrics import routes as _routes  # noqa: E402,F401
from zyg_dashboard.bp_metrics.routes import (  # noqa: E402,F401
    _METRICS_HUB,
    _metrics_hub_module,
    api_character_quality_metrics,
    api_metrics_analytics_config,
    api_metrics_hub,
    get_metrics_all,
    get_metrics_dashboard,
    get_metrics_summary,
)
from zyg_dashboard.bp_metrics.aggregate import (  # noqa: E402,F401
    _backfill_char_gen_states_from_bibles,
    _metrics_fmt_duration,
    _metrics_normalize_stage,
)
from zyg_dashboard.bp_metrics.dashboard_collect import (  # noqa: E402,F401
    _collect_flux_perf,
    _collect_pipeline_state,
    _collect_token_cost,
    _collect_vram,
    _collect_wattage,
)
from zyg_dashboard.bp_metrics.dashboard_char import (  # noqa: E402,F401
    _aggregate_caveman,
    _aggregate_char_gen,
    _build_pipelines_out,
)
from zyg_dashboard.bp_metrics.dashboard import _compute_metrics_dashboard  # noqa: E402,F401
