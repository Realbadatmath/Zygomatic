# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_hair.py — Character Studio's hair-groom catalogue, server side.

    GET /inspect/api/studio/char_hair/assets   -> {ok, packs, items, refused}

One op, and deliberately only one. The GLBs and their previews are served by
the existing /inspect/arch-asset/ route — the packs sit under mesh_packs/_hair,
which that route resolves and the Architecture Studio's catalogue skips — so
nothing here streams bytes and nothing here needs a fence of its own.

The licence gate lives in character_hair_assets.py and is the mesh-pack gate,
imported rather than restated: CC0 free to embed, CC-BY admitted with attrib
carried to the client, anything else invisible."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
if CREWS not in sys.path:
    sys.path.insert(0, CREWS)


def _assets(payload, method):  # noqa: ARG001
    try:
        from zyg_workflows import character_hair_assets as cha
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': f'hair catalogue unavailable: {e}', 'code': 503}
    try:
        cat = cha.catalogue()
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': str(e)[:300], 'code': 500}
    # The asset route is path-based; the client joins this to each item's `u`.
    return dict(cat, base='/inspect/arch-asset/')


ROUTES = {'assets': _assets}
