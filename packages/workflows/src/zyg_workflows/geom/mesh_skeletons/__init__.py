# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mesh_skeletons.py — the ORIGINAL mesh skeletons and every character base (2026-08-05).

RUN:
    python3 -m zyg_workflows.geom.mesh_skeletons build-originals
    python3 -m zyg_workflows.geom.mesh_skeletons derive <char_id> --base male \\
        [--phenotype age=0.23,height=0.97,...] [--bone-scale upperleg=1.1,head=0.95] \\
        [--local key=value,...] [--note "..."]
    python3 -m zyg_workflows.geom.mesh_skeletons verify
    python3 -m zyg_workflows.geom.mesh_skeletons list
    python3 -m zyg_workflows.geom.mesh_skeletons gate [name ...]    # (re-)run the anthropometric gates

THE CONTRACT, exactly as specified:
  * TWO ORIGINALS — one male, one female — are the templates for every character body
    this production will ever make. They are built once, hashed, written read-only, and
    NEVER modified: derive() re-verifies their hashes before every derivation and refuses
    to work from a tampered original.
  * EVERY PART IS ADJUSTABLE, through three stacked mechanisms:
      1. phenotype macros — six continuous axes (gender, age, muscle, weight, height,
         proportions), each 0..1: fat, skinny, tall, tiny, child, elder, and everything
         between, in one dict.
      2. local changes — the model is built with local_changes='all', loading the full
         per-part MakeHuman morph vocabulary (CC0 data); every label is enumerated into
         the originals' params.json so the GUI can show what is adjustable.
      3. per-bone scaling — a scale on any of the 163 named bones, applied through the
         kinematic chain, so 'upperleg01.L=1.15' genuinely lengthens/thickens the upper
         half of the left thigh and everything below it follows. This is the guaranteed
         fully-general knob: it needs nothing from the data, only the rig. The keys are
         anny's RIG names, matched as case-insensitive substrings — 'upperleg' hits both
         thighs, 'upperleg.L' one side, 'head' the head. They are NOT anatomical English:
         there is no bone called 'thigh' or 'shin', and a key matching no bone is now a
         hard error rather than a silently-dropped request (it was the latter until
         2026-08-05, which issued unmodified bodies under a recorded recipe that said
         otherwise). The full roster ships in each original's params.json under
         adjustable.bone_scale.
  * DERIVED MESHES ARE THE CHARACTER'S BASE. derive() writes a new, self-contained
    directory per character — mesh, previews, full parameter recipe, and the parent
    original's hash — and registers it. The original is untouched by construction and
    verified untouched by hash.

  * EVERY ISSUED BODY IS GATED AGAINST REAL ANTHROPOMETRY, and the verdict ships with it.
    geom/anthro/ answers "how unusual is this body, against which population, on which
    measurement convention" — it encodes no aesthetic ideal, because there is no
    measurable "perfect" proportion. The gate is a RECORD, not a veto: a body that lands
    outside a band is unusual by a stated amount, and the deliberate part of that belongs
    in the character's recorded stylization delta. So the gate run is FAIL-SAFE by
    construction — an exception in the engine records status 'gate-error' and the
    character is still issued, because refusing to deliver a mesh because a measurement
    tool broke would be the tool making an art decision. ZYG_ANTHRO_GATES=0 skips it.

  * THE COMPACT ANTHRO SUMMARY (params.json['anthro'] / registry.json entry ['anthro'])
    IS THE THING EVERY OTHER SURFACE READS — the CLI lines here, and the Mesh tab's chip
    and drawer. Its shape changed on 2026-08-05 and consumers should know what moved:
        blocking            EVERY blocking-severity gate that is not satisfied, i.e.
                            failed OR never ran. It used to be failures only, so a body
                            whose blocking gates had not run read as "0 blocking".
        blocking_failed     the subset that was measured and landed outside its band
        blocking_unrun      the subset with NO verdict — status missing/unknown/error —
                            as records {id, status, status_raw, severity, severity_class,
                            why}. A check that did not run is never a pass.
        blocking_unrun_ids  the same, ids only, for a display that wants a short list
        warnings            unchanged
        informational       report-only rows (measured, never gated)
        not_run_non_blocking   skipped rows on gates that were never allowed to block
        unaccounted         rows whose effective_status this module did not recognise.
                            NON-EMPTY IS ITSELF THE ALARM: the status vocabulary grew and
                            nobody taught this triage about it. Never silently dropped.
        buckets_total       must equal n_gates; if it does not, the census is incomplete
        reference_population / reference_population_damaged
                            the pack provenance the character was scored against, and
                            True when that record was lost at issue (see
                            _reference_population)
    A renderer that only knows the old shape still reads `blocking` and now stops
    under-reporting; one that wants "failed vs never ran" apart has the two lists.

LICENCE: Anny — Apache-2.0 code, CC0 MakeHuman-derived model data (verified from licence
text, 2026-08-04). Exports are our own work product.

Storage: data/assets/mesh_skeletons/{originals/{male,female}, derived/<char_id>}/ with
registry.json at the root — which is exactly what the GUI's Mesh tab reads.
"""

# The original top import block plus the section re-exports; every name this package
# re-exports is declared in __all__ at the foot of the file.
import argparse
import collections
import glob
import hashlib
import json
import os
import stat
import sys
import time
import traceback

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from zyg_workflows.geom.mesh_skeletons.spec import (
    ROOT,
    REGISTRY,
    ORIGINAL_SPEC,
    TARGET_HEIGHT_M,
    ORIGINAL_PHEN,
    ORIGINAL_LOCALS,
    ABS_PATTERN_V1,
    ABS_PATTERN_V2,
    ABS_PATTERN_KEY,
    ABS_PATTERNS,
    ORIGINAL_ANATOMY,
    DISPLAY_SUBDIV,
    MESH3D_SUBDIV,
    ANTHRO_REPORT_FILE,
    AUX_NOT_REGENERATED_BY_REFRESH,
    AUX_REGENERATED_BY_GATE,
)
from zyg_workflows.geom.mesh_skeletons.rig import (
    _MODEL,
    _bone_names,
    _model,
    _sha256,
    _scale44,
    _bone_stems,
    _bone_hint,
    _RIG_CACHE,
    _RIG_CACHE_MAX,
    _rig_key,
    _rig_for,
    _rig_record,
    _build_mesh,
    _MORPH_SUPPORT,
    _morph_support,
    _vertex_normals,
    _band,
)
from zyg_workflows.geom.mesh_skeletons.abs_definition import (
    _ABS_V2_W_ZN,
    _ABS_V2_W,
    _ABS_V2_ARC,
    _ABS_V2_ARC_XN_CLAMP,
    _ABS_V2_COSTAL_A,
    _ABS_V2_COSTAL_U0,
    _ABS_V2_COSTAL_CLAMP,
    _abs_pattern,
    _abs_v2_sheath_width,
    _abs_v2_costal_drop,
    _apply_abs_definition,
)
from zyg_workflows.geom.mesh_skeletons.anatomy import (
    TOE_DECLASH_KEY,
    _TOE_GROUPS,
    LIP_DECLASH_KEY,
    LIP_DECLASH_PASSES,
    _LIP_GROUP,
    _ADJ,
    _vertex_adjacency,
    _lip_weight_group,
    _apply_lip_declash,
    _toe_weight_groups,
    _apply_toe_declash,
    _apply_anatomy,
    _relief_requested,
    _bony_relief_enabled,
    _apply_bony_relief,
    _subdivide,
)
from zyg_workflows.geom.mesh_skeletons.artifacts import (
    _BG_BGR,
    _CLAY_BGR,
    _EDGE_BGR,
    _paint,
    _edge_mask,
    _shaded_views,
    _export_mesh3d,
    _emit_visuals,
    _export_glb,
    _measure,
    _vert_sha,
    _registry,
    _save_registry,
    _write_protect,
    _write_enable,
    _imwrite,
    _atomic_json,
    _aux_hashes,
    _aux_assert_unrewritten_intact,
)
from zyg_workflows.geom.mesh_skeletons.anthro import (
    ANTHRO_SPEC_SCHEMA,
    STYLIZATION_AXIS,
    ORIGINAL_STYLIZATION_INTENT,
    _anthro_enabled,
    _reference_population,
    _reference_population_damaged,
    _stylization,
    _character_spec,
    _apply_spec,
    _anthro_spec,
    _ensure_repo_importable,
    _ANTHRO_PASS,
    _ANTHRO_WARN,
    _ANTHRO_INFORMATIONAL,
    _ANTHRO_KNOWN_STATUSES,
    _ANTHRO_LOW_SEVERITIES,
    _anthro_row_blocks,
    _anthro_buckets,
    _anthro_run,
    _anthro_gate,
    _rebuild_from_params,
    _backfill_spec,
)
from zyg_workflows.geom.mesh_skeletons.originals import (
    gate_registered,
    _calibrate_height,
    build_originals,
    _gate_rebuild,
    refresh_previews,
    verify_originals,
)
from zyg_workflows.geom.mesh_skeletons.derive import reissue, derive
from zyg_workflows.geom.mesh_skeletons.cli import _parse_kv, main

# The re-export surface of the split package: the original top import block plus every
# name the section modules define, so `mesh_skeletons.<name>` and
# `from ... import <name>` resolve exactly as they did before the split.
__all__ = [
    'argparse',
    'collections',
    'glob',
    'hashlib',
    'json',
    'os',
    'stat',
    'sys',
    'time',
    'traceback',
    'np',
    'ROOT',
    'REGISTRY',
    'ORIGINAL_SPEC',
    'TARGET_HEIGHT_M',
    'ORIGINAL_PHEN',
    'ORIGINAL_LOCALS',
    'ABS_PATTERN_V1',
    'ABS_PATTERN_V2',
    'ABS_PATTERN_KEY',
    'ABS_PATTERNS',
    'ORIGINAL_ANATOMY',
    'DISPLAY_SUBDIV',
    'MESH3D_SUBDIV',
    'ANTHRO_REPORT_FILE',
    'AUX_NOT_REGENERATED_BY_REFRESH',
    'AUX_REGENERATED_BY_GATE',
    '_MODEL',
    '_bone_names',
    '_model',
    '_sha256',
    '_scale44',
    '_bone_stems',
    '_bone_hint',
    '_RIG_CACHE',
    '_RIG_CACHE_MAX',
    '_rig_key',
    '_rig_for',
    '_rig_record',
    '_build_mesh',
    '_MORPH_SUPPORT',
    '_morph_support',
    '_vertex_normals',
    '_band',
    '_ABS_V2_W_ZN',
    '_ABS_V2_W',
    '_ABS_V2_ARC',
    '_ABS_V2_ARC_XN_CLAMP',
    '_ABS_V2_COSTAL_A',
    '_ABS_V2_COSTAL_U0',
    '_ABS_V2_COSTAL_CLAMP',
    '_abs_pattern',
    '_abs_v2_sheath_width',
    '_abs_v2_costal_drop',
    '_apply_abs_definition',
    'TOE_DECLASH_KEY',
    '_TOE_GROUPS',
    'LIP_DECLASH_KEY',
    'LIP_DECLASH_PASSES',
    '_LIP_GROUP',
    '_ADJ',
    '_vertex_adjacency',
    '_lip_weight_group',
    '_apply_lip_declash',
    '_toe_weight_groups',
    '_apply_toe_declash',
    '_apply_anatomy',
    '_relief_requested',
    '_bony_relief_enabled',
    '_apply_bony_relief',
    '_subdivide',
    '_BG_BGR',
    '_CLAY_BGR',
    '_EDGE_BGR',
    '_paint',
    '_edge_mask',
    '_shaded_views',
    '_export_mesh3d',
    '_emit_visuals',
    '_export_glb',
    '_measure',
    '_vert_sha',
    '_registry',
    '_save_registry',
    '_write_protect',
    '_write_enable',
    '_imwrite',
    '_atomic_json',
    '_aux_hashes',
    '_aux_assert_unrewritten_intact',
    'ANTHRO_SPEC_SCHEMA',
    'STYLIZATION_AXIS',
    'ORIGINAL_STYLIZATION_INTENT',
    '_anthro_enabled',
    '_reference_population',
    '_reference_population_damaged',
    '_stylization',
    '_character_spec',
    '_apply_spec',
    '_anthro_spec',
    '_ensure_repo_importable',
    '_ANTHRO_PASS',
    '_ANTHRO_WARN',
    '_ANTHRO_INFORMATIONAL',
    '_ANTHRO_KNOWN_STATUSES',
    '_ANTHRO_LOW_SEVERITIES',
    '_anthro_row_blocks',
    '_anthro_buckets',
    '_anthro_run',
    '_anthro_gate',
    '_rebuild_from_params',
    '_backfill_spec',
    'gate_registered',
    '_calibrate_height',
    'build_originals',
    '_gate_rebuild',
    'refresh_previews',
    'verify_originals',
    'reissue',
    'derive',
    '_parse_kv',
    'main',
]
