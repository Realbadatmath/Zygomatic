# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared — the bank every 3D step runs identically. 2026-09-30.

What this bank is
-----------------
`capability_tests/<step>.py` for mesh_gen, mesh_qc, grooms, arch, render3d and rigging says
`'include_shared': 'geometry'`. This module answers, ONCE and identically for all of them, the
questions that are not about the step's own domain:

  Builds: *            132 subjects a 3D row is asked to BUILD — not depict. "A broken window"
                       is a frame with missing panes and shards as SEPARATE geometry, never a
                       texture. Every subject has one verbatim prompt (< 40 words) and one
                       fixture image for the image-in rows, both stored here.
  Capacity             ladders whose answer is a COUNT: separate objects before they fuse,
                       named people before faces blur, triangles before detail collapses,
                       letters before lettering stops reading.
  Space & relation     measured in the BUILD's own frame from bounding boxes (`bbox_relation`),
                       not from a picture of it.
  Attributes           colour from the exported material base colour, material from material
                       NAMES plus PBR values, size from the real-world bbox in metres.
  Prompt: *            53 columns: the 49 shared prompt-damage/clarity/limits/steering columns
                       plus four geometry extras — pd_part_names, pd_count_words,
                       pd_dimension_words, pd_spatial_words.
  the universal 27     licence/cost/reliability/operability.

Nothing here executes. These are inputs, conditions, checks and thresholds.

The export contract (identical for every row, every seed)
---------------------------------------------------------
One GLB per build, at REAL SCALE in metres, +Y up with the subject standing
(`project_body_plates_gltf_upaxis` — a GLB that comes out Z-up fails `glb_up_axis` and the
build is a `no`, however good the mesh is). Seeds [11, 12, 13]; the row's production
resolution / steps / sampler are whatever the step ships with and are copied VERBATIM into the
trial, so two models are only ever compared inside one sheet, never across sheets whose
settings differ. Every build also produces a 4-view turntable sheet (0/90/180/270 degrees,
same lens, same lighting, `blender_scripts/render_asset_previews.py`) — that sheet, and only
that sheet, is what the operator sees.

What this bank cannot decide by machine
---------------------------------------
No local VLM judges geometric defects reliably. The defect-judge bench of 2026-09-27 scored
34/40 on a global "is this right" question but 2/8 on fused fingers, 2/8 on extra digits and
2/8 on a second feather — the exact failures a mesh generator makes. So "is this a usable
<subject>" is an OPERATOR blind yes/no on the turntable sheet, with a mechanical check beside
it wherever a detector exists (trimesh manifold / self-intersection / shell count, bbox in
metres, MediaPipe hand_landmarker for fingers, ArcFace cosine for identity, tesseract OCR for
lettering and clock faces, a person detector for counts). Where both run, `state_note` says
which decides: the MECHANICAL check is a veto — it can only make a build fail — and the
operator's yes is required on top of it.

Self-intersection is a first-class check, not a nicety: the Abel finding was a mesh that
passed every visual review and was unusable downstream because the limbs intersected the
trunk. `mesh_no_self_intersection` runs on every build.

Contents
--------
CHECK_KINDS     the geometry check vocabulary this bank adds to `capability_tests.__init__`
COND_BUILD      the one fixed build condition (seeds, repeats, export, sheet)
SUBJECTS        132 rows: column id -> (label, prompt, shells, size, extras)
PROBES          one probe per column this bank owns
DERIVE/LOOKUP/WIRING/NA/TRANSPORT_NA   the universal 27 and the per-transport exemptions
SHARED          what `capabilities_tests.py` merges into a step's TEST
"""

from __future__ import annotations

# ruff: noqa: F401

from . import constants  # noqa: E402
from . import subjects_people_body  # noqa: E402
from . import subjects_food_damage  # noqa: E402
from . import subjects_text_objects  # noqa: E402
from . import subjects_animals_nature  # noqa: E402
from . import builds_capacity  # noqa: E402
from . import space  # noqa: E402
from . import attributes  # noqa: E402
from . import prompt_variants  # noqa: E402
from . import prompt_clarity  # noqa: E402
from . import prompt_limits  # noqa: E402
from . import prompt_steering  # noqa: E402
from . import universal  # noqa: E402

from .constants import (  # noqa: E402
    CHECK_KINDS,
    CONDITIONS_NOTE,
    COND_BUILD,
    COND_NOTE,
    FIXED_SETTINGS,
    OPERATOR_PROTOCOL,
    _hands,
    _maps,
    _mat,
    _ocr,
    _ocr_has,
    _people,
)
from .subjects_people_body import (  # noqa: E402
    SUBJECTS,
)
from .builds_capacity import (  # noqa: E402
    BUILD_STATE_NOTE,
    BUILD_STATE_RULE,
    CAP_NOTE,
    PROBES,
    _op,
    _probe,
)
from .space import (  # noqa: E402
    SPACE_NOTE,
    _space,
)
from .attributes import (  # noqa: E402
    ATTR_NOTE,
    _attr,
)
from .prompt_variants import (  # noqa: E402
    BASE_KEY,
    BASE_KEY_NOTE,
    BASE_TASK,
    VARIANTS,
)
from .prompt_clarity import (  # noqa: E402
    CART_KEY,
    CLARITY_LADDER,
    CLARITY_NOTE,
)
from .prompt_limits import (  # noqa: E402
    LENGTH_LADDER_NOTE,
)
from .universal import (  # noqa: E402
    DERIVE,
    FIXTURES,
    LOOKUP,
    NA,
    SHARED,
    TRANSPORT_NA,
    WIRING,
    _LIB_NO_PROMPT,
    _NO_PROMPT,
    _PD_ALL,
    _PD_SCRIPTED,
)
