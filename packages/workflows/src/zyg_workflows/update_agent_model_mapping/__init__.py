# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401
import json
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# The sections of the single file this package replaces, imported in the original
# section order so every module-level side effect still runs when it used to.
from zyg_workflows.update_agent_model_mapping import constants
from zyg_workflows.update_agent_model_mapping import verticals_marketing
from zyg_workflows.update_agent_model_mapping import verticals_children_3d
from zyg_workflows.update_agent_model_mapping import verticals_children_2d
from zyg_workflows.update_agent_model_mapping import verticals
from zyg_workflows.update_agent_model_mapping import mapping

# Every name the single module defined, re-bound here so no importer and no
# attribute access anywhere has to change.
from zyg_workflows.update_agent_model_mapping.constants import (
    CPU_MODELS_FILE,
    GPU_MODELS_FILE,
    MAPPING_FILE,
)
from zyg_workflows.update_agent_model_mapping.verticals import (
    BUSINESS_VERTICALS,
)
from zyg_workflows.update_agent_model_mapping.mapping import (
    find_model_id,
    get_next_model_id,
    load_json_file,
    normalize_model_name,
    save_json_file,
    update_agent_mapping,
)
