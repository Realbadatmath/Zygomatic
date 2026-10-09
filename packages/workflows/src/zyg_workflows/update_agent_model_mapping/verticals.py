# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""BUSINESS_VERTICALS — the whole catalogue, reassembled from its three parts.

The single-file update_agent_model_mapping.py held this as ONE 853-line dict
literal (lines 17-869), over the 800-line ceiling a split may create.  Its four
top-level entries are therefore carried verbatim by three part modules and
spliced here IN THE ORIGINAL ORDER; `{**a, **b, **c}` preserves insertion order,
so both the value and the key order are the ones the single file built.
"""

from zyg_workflows.update_agent_model_mapping.verticals_children_2d import _PART_CHILDREN_2D
from zyg_workflows.update_agent_model_mapping.verticals_children_3d import _PART_CHILDREN_3D
from zyg_workflows.update_agent_model_mapping.verticals_marketing import _PART_MARKETING

# Business verticals data (from your provided JSON)
BUSINESS_VERTICALS = {**_PART_MARKETING, **_PART_CHILDREN_3D, **_PART_CHILDREN_2D}
