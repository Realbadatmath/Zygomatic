# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_spec_seed.seeds — SEEDS, re-assembled from the three sheet groups.

The single file held all 36 seed sheets in one `SEEDS = [...]` literal. Each
sheet moved byte for byte into one of the three group modules; this joins
them back in the original order, so SEEDS is the same list of the same dicts.
"""

from __future__ import annotations

from zyg_workflows.arch_spec_seed.seeds_rooms import SEEDS_ROOMS
from zyg_workflows.arch_spec_seed.seeds_site import SEEDS_SITE
from zyg_workflows.arch_spec_seed.seeds_fabric import SEEDS_FABRIC

SEEDS = [
    *SEEDS_ROOMS,
    *SEEDS_SITE,
    *SEEDS_FABRIC,
]
