# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The registry: the three row blocks joined, then validated as the old module did.

The old gates.py held all 62 rows in ONE tuple literal 1,256 lines long — over the
1,000-line hard cap on its own. It is cut at its own `# -- Tier N` markers into three
row blocks and joined here; concatenating tuples in declaration order yields the same
rows in the same order the single literal produced. `validate_registry(GATES)` runs at
import exactly where the old module ran it (gates.py line 8405).
"""

from zyg_workflows.geom.anthro.gates.gate import validate_registry
from zyg_workflows.geom.anthro.gates.registry_tiers_1_2 import GATES_TIERS_1_2
from zyg_workflows.geom.anthro.gates.registry_tiers_3_4 import GATES_TIERS_3_4
from zyg_workflows.geom.anthro.gates.registry_tier5 import GATES_TIER_5


GATES = GATES_TIERS_1_2 + GATES_TIERS_3_4 + GATES_TIER_5

validate_registry(GATES)
