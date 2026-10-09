# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""arch_pack_ingest.provenance — the per-pack licence QUOTES and the PROVENANCE.json writer.

Moved verbatim out of arch_pack_ingest.py (lines 1583-1693) when that 2,019-line
module became this package; no logic was changed.
"""

from __future__ import annotations

import json
import os
import time


# ── provenance ──────────────────────────────────────────────────────────────

PROV = {
    'polyhaven_arch': {
        'source_summary': 'Poly Haven 3D models, architecture-relevant categories, glTF @2k',
        'license': 'CC0 1.0 Universal (public domain dedication)',
        'license_evidence_url': 'https://polyhaven.com/license',
        'license_quote': (
            'All assets on Poly Haven are licensed as CC0, which is '
            'effectively public domain. You can use them for any purpose, '
            'no attribution required.'
        ),
    },
    'kenney': {
        'source_summary': 'Kenney CC0 3D asset kits, whole published 3D catalogue',
        'license': 'CC0 1.0 Universal (public domain dedication)',
        'license_evidence_url': 'https://kenney.nl/assets',
        'license_quote': (
            'All assets are CC0 licensed, meaning you can use them '
            'for any purpose (including commercial) without having '
            'to give credit.'
        ),
    },
    'polyhaven_hdri': {
        'source_summary': 'Poly Haven HDRI environments, whole library, .hdr @2k',
        'license': 'CC0 1.0 Universal (public domain dedication)',
        'license_evidence_url': 'https://polyhaven.com/license',
        'license_quote': (
            'All assets on Poly Haven are licensed as CC0, which is '
            'effectively public domain. You can use them for any purpose, '
            'no attribution required.'
        ),
    },
    'polyhaven_tex': {
        'source_summary': 'Poly Haven PBR textures, whole library, JPG @2k',
        'license': 'CC0 1.0 Universal (public domain dedication)',
        'license_evidence_url': 'https://polyhaven.com/license',
        'license_quote': (
            'All assets on Poly Haven are licensed as CC0, which is '
            'effectively public domain. You can use them for any purpose, '
            'no attribution required.'
        ),
    },
    'ambientcg_decals': {
        'source_summary': ('ambientCG decals — single-placement overlays with an opacity map, 2K PNG'),
        'license': 'CC0 1.0 Universal (public domain dedication)',
        'license_evidence_url': 'https://ambientcg.com/license',
        'license_quote': (
            'All assets on ambientCG are available under the Creative '
            'Commons CC0 1.0 Universal License, they are free for any '
            'purpose including commercial use.'
        ),
    },
    'ambientcg_atlas': {
        'source_summary': ('ambientCG atlases — cut-out sheets (foliage and the like) with an opacity map, 2K PNG'),
        'license': 'CC0 1.0 Universal (public domain dedication)',
        'license_evidence_url': 'https://ambientcg.com/license',
        'license_quote': (
            'All assets on ambientCG are available under the Creative '
            'Commons CC0 1.0 Universal License, they are free for any '
            'purpose including commercial use.'
        ),
    },
    'smithsonian': {
        'source_summary': (
            'Smithsonian Open Access 3D — CC0 scans of real held objects across the museum units, low-resolution GLB'
        ),
        'license': 'CC0 (Smithsonian Open Access)',
        'license_evidence_url': (
            'https://api.si.edu/openaccess/api/v1.0/search?q=online_media_type%3A%223D+Models%22&api_key=DEMO_KEY'
        ),
        'license_quote': (
            'Every 3d_voyager media block in the 3D Models result set '
            'carries "usage": {"access": "CC0"} — measured across all '
            '1937 records, 3460/3460 media blocks, zero exceptions.'
        ),
    },
    'ambientcg': {
        'source_summary': 'ambientCG PBR materials, architectural surfaces, 2K JPG',
        'license': 'CC0 1.0 Universal (public domain dedication)',
        'license_evidence_url': 'https://ambientcg.com/license',
        'license_quote': (
            'All assets on ambientCG are available under the Creative '
            'Commons CC0 1.0 Universal License, they are free for any '
            'purpose including commercial use.'
        ),
    },
}


def write_provenance(pack: str, root: str, registry: dict, extra: dict | None = None):
    p = dict(PROV[pack])
    p.update(
        {
            'curated': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'tool': 'arch_pack_ingest.py',
            'item_count': len(registry),
            'byte_count': sum(
                sum(f['bytes'] for f in r.get('files', {}).values()) if 'files' in r else r.get('bytes', 0)
                for r in registry.values()
            ),
        }
    )
    if extra:
        p.update(extra)
    with open(os.path.join(root, 'PROVENANCE.json'), 'w') as f:
        json.dump(p, f, indent=1)
    with open(os.path.join(root, 'registry.json'), 'w') as f:
        json.dump(registry, f, indent=1)
