# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  the single file's own top import block, re-exported to the submodules
"""The top import block, the schema, the provenance stamp and every calibration constant.

Moved verbatim out of the old single-file relief_subdiv.py (lines 262-372).
"""

import json
import os
import resource
import sys
import time

import numpy as np
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.relief_subdiv')


SCHEMA = 'geom.relief_subdiv/1'


def _module_provenance():
    """Identify the exact build of this module and of ridge.py that wrote a report.

    A report that does not say which code produced it cannot be told apart from one an
    older build produced, and this module has already shipped level-2 artefacts that looked
    current and were not. Cheap, and it makes staleness detectable by grep."""
    import hashlib

    out = {}
    # ridge and relief became packages in the 2026-10 modularization (form/ridge/, relief/),
    # as did this module: a directory is fingerprinted as its modules, sorted, concatenated.
    geom = paths.PKG_DIR / 'geom'
    for tag, mod in (
        ('relief_subdiv', str(geom / 'relief_subdiv')),
        ('ridge', str(geom / 'form' / 'ridge')),
        ('relief', str(geom / 'relief')),
    ):
        try:
            if os.path.isdir(mod):
                raw = b''.join(
                    open(os.path.join(mod, n), 'rb').read() for n in sorted(os.listdir(mod)) if n.endswith('.py')
                )
            else:
                with open(mod, 'rb') as fh:
                    raw = fh.read()
            out[tag] = {
                'path': os.path.relpath(mod, paths.PKG_DIR),
                'sha256': hashlib.sha256(raw).hexdigest()[:16],
                'bytes': len(raw),
                'mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(mod))),
            }
        except OSError as e:  # noqa: BLE001
            out[tag] = {'unavailable': str(e)}
    out['level_null_seed_panel'] = list(LEVEL_NULL_SEED_PANEL)
    out['note'] = (
        'sha256 is the first 16 hex of the file as it stood when the report was '
        'written. If it does not match the module you are reading, the report '
        "predates it and its numbers are not this code's numbers."
    )
    return out


# The two levels the pipeline actually renders from. Named rather than passed as bare
# integers so a caller cannot quietly probe level 1 and report it as the stills level.
SUBDIV_STILLS = 2  # 219,368 vertices — the level the contact-sheet stills bake at
SUBDIV_3D = 3  # 877,448 vertices — the level the 3D export carries

# Vertex count of the authored cage. Everything in geom/form/regions.py indexes it, and
# the index-preservation guarantee below is what makes those groups usable after
# subdivision. Checked, never assumed.
CAGE_VERTS = 13718
CAGE_FACES = 13710

# Null pool target sizes at cage level, from ridge.RIDGE_NULL_P99['target_sizes']. Scaled
# by 4**level so the null is measured on pools of the same PHYSICAL size as the probe
# pools at that level. See the module docstring for why vertex-count matching is the wrong
# rule across resolutions.
CAGE_NULL_TARGET_SIZES = (30, 100, 300)

# How many random pools per target size the ridge null draws at each level. These are
# UNDER-POWERED at levels 2 and 3 relative to the 320-pool panel that derived the shipped
# constant, and that is stated in the report rather than hidden: one pool at level 3 costs
# about 250 s of wall clock. The per-station p99 is fine at these counts (each pool yields
# ~590 stations, so 24 pools is ~14,000 stations and the 1% tail holds ~140 of them); the
# RUN-LENGTH threshold is not, which is exactly why min_run is floored at the shipped
# panel value and may only be raised by a level measurement, never lowered by one.
NULL_POOLS_BY_LEVEL = {0: 40, 1: 24, 2: 8, 3: 4}

# Patches for the isotropic (point-mode) relief null — curvature.relief_null's own n. This
# is the estimator that produced the standing figure "cage relief null p99 = 2.45e-3 of
# stature, contrast floor 3.66", so it is the one the headline number has to come from.
POINT_NULL_N_BY_LEVEL = {0: 300, 1: 300, 2: 300, 3: 150}

# Any level-cut station floor below this is refused outright. 1.0e-4 of stature is 0.17 mm
# at 1.68 m — under the mesh's own mirror residual on the male cage (0.0599 mm) by only a
# factor of three, and below any displacement a depth pass can carry. A null that measures
# lower than this has not measured a null, it has measured a bug, and the correct response
# is to say so rather than to score a landmark against it.
LEVEL_CUT_ABSOLUTE_FLOOR_FRAC = 1.0e-4

# The SAME refusal, on the other axis. A station must clear BOTH |relief| >=
# min_frac_stature AND |contrast| >= min_contrast, so a level cut whose CONTRAST p99 has
# collapsed gates on relief alone — half the test — while still reporting itself as
# MEASURED-NULL. The lowest contrast p99 ever measured on any level of either body is
# 2.148 (male, level 2, point mode); 0.5 is 4.3x below that, so no smooth surface can
# reach it and anything that does is a broken estimator (a degenerate collar fit, an
# all-but-planar sample), not a quiet mesh. Refuse rather than score against it.
LEVEL_CUT_ABSOLUTE_FLOOR_CONTRAST = 0.5

# THE SEEDS THE LEVEL NULL IS DRAWN OVER. Six, not one, and this is the whole reason:
# ridge.py's own header records that the seed which shipped, 20260806, is the UNIQUE seed
# of its 24-seed panel returning min_run 2 and carries the second-lowest station cut of the
# 24 — "a threshold that is 1-of-24 permissive is indistinguishable from one tuned until our
# own bodies passed". A level cut taken as ONE draw at that seed inherits exactly that
# objection, and it is not academic: re-drawing the identical female level-2 null at these
# six seeds moves the station cut from 1.8122e-3 to 2.5522e-3 of stature, a 41% spread that
# straddles the 2.45e-3 cage constant the "the null halves at level 2" claim is measured
# against. So the level cut is the panel UPPER BOUND (the most conservative seed, never the
# median and never the draw that happens to be lowest), the run threshold comes from the
# POOLED histogram over all six seeds, and the false-positive rate is measured by re-scoring
# all six seeds' pools AT THAT CUT. Every seed is a member of ridge.RIDGE_NULL_SEED_PANEL,
# and the seed that shipped is inside the panel rather than replaced by it, so the old draw
# stays visible next to the bound that supersedes it.
LEVEL_NULL_SEED_PANEL = (42, 777, 123456, 987654, 20260805, 20260806)
