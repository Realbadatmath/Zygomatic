# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_reference.py — compile the anthropometric reference pack from primary microdata.

WHY THIS EXISTS: every downstream proportion check needs numbers, and the tempting way to
get them is to type a remembered ratio into a constant. That is how "golden ratio",
"WHR 0.7" and "shoulders 1.618x waist" get into production code. This builder refuses to
let a number exist in the pipeline unless it was computed here, from microdata that ships
in the repo, with its population, landmark, convention and licence recorded beside it.

THE FOUR TRAPS IT IS BUILT AROUND
  1. There is no measurable "ideal" proportion. Every statistic here describes what real
     people ARE, never what a body should be. A stylization delta is a separate, NAMED
     parameter recorded per character; it is not folded into these bands.
  2. Independent per-ratio bands lie. Ten independent 90% bands admit at most 0.9^10 of
     the population and also admit combinations no human has. This pack therefore ships a
     joint Mahalanobis model over a fixed 10-D ratio vector as the PRIMARY plausibility
     gate, with EMPIRICAL D^2 thresholds — the chi-square value is stored only as a
     reference point together with the pass rate it actually achieves on this sample.
  3. Ancestry is the largest single proportion effect in the data, so every ratio is also
     tabulated per DODRace group. A single-population leg-length gate is a bias, not a
     tolerance. Groups with n < 100 are dropped and the drop is recorded, because a band
     computed from 29 people is a number pretending to be evidence.
  4. Names are not definitions. "waist", "leg length" and "shoulder width" each denote
     several different measurements taken at different landmarks. Every dimension here
     carries its ANSUR II column, its landmark, its convention and its ISO class so a
     consumer can tell whether its own measurement is even the same quantity.

Re-runnable. Reads either the repo's own copy of the sources (default, so the pack is
reproducible from the repo alone) or a download directory via --source-dir.

RUN:
    python3 -m zyg_workflows.geom.anthro.build_reference [--source-dir DIR] [--out DIR]
"""

# Pattern A package: build_reference.py was cut at its own section banners into the modules below.
# The original top import block is re-done here so old attribute access (build_reference.os, ...)
# still resolves, the submodules are imported in the original section order, and every
# name the single module defined is re-exported.

import argparse
import csv
import hashlib
import json
import os
import shutil
import time

import numpy as np

from zyg_workflows import paths as _paths

from zyg_workflows.geom.anthro.build_reference.constants import (
    ROOT,
    SCHEMA_VERSION,
    IMPORT_DIR,
    SOURCE_FILES,
    DODRACE,
    MIN_GROUP_N,
    ISO_20685_1_TABLE4_MM,
    DIMENSIONS,
    INDICES,
    MAHALANOBIS_ORDER,
    CHI2_DF10,
    POLICY_MIN_R,
    POLICY_MAX_RMSE_MM,
    PERCENTILE_GRID,
    REPORT_PERCENTILES,
)
from zyg_workflows.geom.anthro.build_reference.stats import (
    _sha256,
    _atomic_json,
    _atomic_npz,
    _r6,
    _resolve_sources,
    _load_ansur,
    _load_lms,
    _summary,
    _ratio_values,
    _build_ratio_specs,
    _diagnostics,
    _mahalanobis,
)
from zyg_workflows.geom.anthro.build_reference.provenance import (
    _provenance,
    _conventions,
    AGEING_REFERENCE_AGES,
    AGEING_BIN_HALFWIDTH_Y,
    _ageing_deltas,
    _gaps,
)
from zyg_workflows.geom.anthro.build_reference.pipeline import (
    build,
    main,
)

__all__ = [
    'argparse',
    'csv',
    'hashlib',
    'json',
    'os',
    'shutil',
    'time',
    'np',
    '_paths',
    'ROOT',
    'SCHEMA_VERSION',
    'IMPORT_DIR',
    'SOURCE_FILES',
    'DODRACE',
    'MIN_GROUP_N',
    'ISO_20685_1_TABLE4_MM',
    'DIMENSIONS',
    'INDICES',
    'MAHALANOBIS_ORDER',
    'CHI2_DF10',
    'POLICY_MIN_R',
    'POLICY_MAX_RMSE_MM',
    'PERCENTILE_GRID',
    'REPORT_PERCENTILES',
    '_sha256',
    '_atomic_json',
    '_atomic_npz',
    '_r6',
    '_resolve_sources',
    '_load_ansur',
    '_load_lms',
    '_summary',
    '_ratio_values',
    '_build_ratio_specs',
    '_diagnostics',
    '_mahalanobis',
    '_provenance',
    '_conventions',
    'AGEING_REFERENCE_AGES',
    'AGEING_BIN_HALFWIDTH_Y',
    '_ageing_deltas',
    '_gaps',
    'build',
    'main',
]
