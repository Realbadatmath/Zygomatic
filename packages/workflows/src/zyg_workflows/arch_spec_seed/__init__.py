# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_spec_seed.py — write the SEED object specs (2026-09-08).

These are the sheets the assistant starts from: conventional building practice
for the objects a building checklist actually touches, in the vocabulary of
THIS studio (real tool names, real record kinds, real arguments).  Every one is
marked `source: "seeded"` — conventional, not code-verified.  The offline
researcher (arch_spec_research.py) upgrades a sheet to `researched` when it can
cite where the numbers come from; nothing here pretends to be a citation.

Run:  python3 arch_spec_seed.py [--force]      (skips keys already researched)
"""

# Pattern A split (2026-10-07): the 1,179-line arch_spec_seed.py became this
# package. The 36 seed sheets moved byte for byte into three group modules,
# main() into cli.py; this __init__ re-exports every name the single file
# defined, so `from zyg_workflows import arch_spec_seed` resolves as before.
# ruff: noqa: F401

from __future__ import annotations

# the submodules, in the original section order (constants carries the top
# block the others import from, so it comes first)
from zyg_workflows.arch_spec_seed import constants
from zyg_workflows.arch_spec_seed import seeds_rooms
from zyg_workflows.arch_spec_seed import seeds_site
from zyg_workflows.arch_spec_seed import seeds_fabric
from zyg_workflows.arch_spec_seed import seeds
from zyg_workflows.arch_spec_seed import cli

from zyg_workflows.arch_spec_seed.constants import (
    json,
    os,
    sys,
    HERE,
)
from zyg_workflows.arch_spec_seed.seeds_rooms import (
    SEEDS_ROOMS,
)
from zyg_workflows.arch_spec_seed.seeds_site import (
    SEEDS_SITE,
)
from zyg_workflows.arch_spec_seed.seeds_fabric import (
    SEEDS_FABRIC,
)
from zyg_workflows.arch_spec_seed.seeds import (
    SEEDS,
)
from zyg_workflows.arch_spec_seed.cli import (
    main,
)
