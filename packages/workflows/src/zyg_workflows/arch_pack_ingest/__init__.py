# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_pack_ingest.py — pull the CC0 architecture asset packs into mesh_packs.

Built 2026-09-01 for the Architecture Studio. The audio side of the house has
pack_ingest.py; this is the same discipline for GEOMETRY and SURFACES:

    masters land under data/assets/mesh_packs/<vendor>/<pack>/
    every file is hashed, every pack carries a PROVENANCE.json with the
    licence QUOTE and the URL it was read from, and nothing is installed
    that cannot show CC0 at FILE level.

Two sources are scripted here because both publish a real API:

    polyhaven_arch   glTF @ 2k for the architecture-relevant categories.
                     glTF and not .blend on purpose — ONE download serves
                     both consumers: Blender imports it for the asset
                     library, and the Architecture Studio's three.js
                     viewport loads the same bytes.
    ambientcg        PBR materials @ 2k, the surfaces the studio's
                     Materials section is currently faking with flat colour.

Kenney and Quaternius are NOT here: Kenney ships one zip per pack behind a
content-hashed URL that changes on every republish (resolve it from the asset
page, which `--kenney-urls` does), and Quaternius delivers through a Google
Drive folder that rate-limits scripted pulls after ~40 files. Both are
recorded in PROVENANCE by hand.

    python3 arch_pack_ingest.py --plan                 # sizes only, no writes
    python3 arch_pack_ingest.py --fetch polyhaven
    python3 arch_pack_ingest.py --fetch ambientcg --limit 300
    python3 arch_pack_ingest.py --report
"""

# ruff: noqa: F401  # this file exists to re-export the old module's namespace

# The original top import block, re-done verbatim so that attribute accesses
# on the old module (arch_pack_ingest.os, .cf, .urllib, ._zyg_logging) resolve
# exactly as they did before the split.
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import logging as _zyg_logging

# The sections, imported in the ORIGINAL section order so that module-level
# side effects (constant construction) run in the original sequence.
from . import common
from . import polyhaven
from . import ambientcg
from . import kenney
from . import prepare
from . import smithsonian
from . import provenance
from . import cli

# Every name the single-file module defined, public and underscore alike.
from .common import (
    _zyg_log,
    HERE,
    PACKS,
    PH_API,
    ACG_API,
    PH_CATEGORIES,
    WORKERS,
    UA,
    _checked_url,
    _get_json,
    _download,
    _digest,
    _md5,
    _sha256,
)
from .polyhaven import (
    ph_select,
    ph_plan,
    ph_fetch,
    ph_select_all,
    ph_hdri_plan,
    PH_TEX_MAPS,
    ph_tex_plan,
    ph_simple_fetch,
)
from .ambientcg import (
    ACG_CATEGORIES,
    _acg_downloads,
    acg_plan,
    acg_fetch,
    ACG_MAPS,
    WEB_RES,
    WEB_QUALITY,
    THUMB_RES,
    THUMB_QUALITY,
    acg_dimensions,
    acg_prepare,
)
from .kenney import (
    KENNEY_INDEX,
    KENNEY_PAGE,
    _K_ZIP,
    _K_CC0,
    _get_text,
    kenney_slugs,
    kenney_plan,
    kenney_fetch,
)
from .prepare import (
    ph_tex_prepare,
    ph_hdri_prepare,
    ACG_ALPHA_KINDS,
    acg_alpha_plan,
    ACG_ALPHA_MAPS,
    acg_alpha_prepare,
)
from .smithsonian import (
    SI_API,
    SI_QUERY,
    SI_PAGE,
    SI_CACHE,
    SI_CACHE_TTL,
    si_records,
    _si_records_live,
    _si_media,
    si_plan,
    SI_UNITS,
    si_slug,
    si_fetch,
    si_unit_provenance,
    SI_PLY_TARGET_TRIS,
    SI_PLY_UNITS,
    SI_PLY_CONVERT_JOBS,
    _SI_ELEMENT,
    _si_specimen_name,
    si_ply_plan,
    si_ply_fetch,
)
from .provenance import (
    PROV,
    write_provenance,
)
from .cli import (
    human,
    main,
)
