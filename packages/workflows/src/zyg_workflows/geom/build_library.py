# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_library.py — Phase 1: populate the register for the forest scene (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.build_library [--res 4k] [--refs 4]

Admits exactly what the axe-in-the-forest scene needs, and nothing speculative:

  materials   bark_brown_02   the trunk. Chosen over bark_platanus (smooth, pale, plane)
                              and bark_willow (fine vertical fissure) because its tags are
                              bark/tree/forest/knots/tree trunk and its fissure depth is
                              what an oak reads as. Ships Displacement at 4k, which is the
                              map that gives the trunk real relief instead of painted-on
                              normals — and real relief is what the gate measures.
              forest_ground   the floor under the tree.

  refs        oak bark, oak leaf, forest floor, hatchet — the photoreal reference the
              rules demand for every object, pulled CC0 from Openverse.

  wounds      the 15 licence-verified references already in data/assets/wounds/_refs are
              re-registered here rather than re-fetched, so the whole library sits behind
              one policy check instead of two conventions.

Every admission runs through manifest.provenance(), so a licence outside the allow list
stops the build rather than logging a warning.
"""

import json
import os

from . import ingest, manifest

WOUND_REFS = os.path.join(ingest.ASSET_ROOT, 'wounds', '_refs')

# (asset id, poly haven id, kind, world span in metres, note)
MATERIALS = [
    (
        'bark_oak',
        'bark_brown_02',
        1.2,
        'trunk surface; tagged bark/tree/forest/knots/tree trunk, ships 4k Displacement',
    ),
    ('ground_forest', 'forest_ground_04', 4.0, 'floor under the tree'),
]

# (asset id, queries tried in order, count) — the photoreal reference every object must
# carry. Multiple queries because the CC0 corpus is sparsely tagged: 'hatchet axe wood
# handle' returns zero, 'axe in tree stump' returns seven above 900px.
REFS = [
    ('ref_oak_bark', ['oak tree bark texture', 'oak bark', 'tree bark closeup'], 4),
    ('ref_oak_leaf', ['oak leaf', 'oak leaves', 'quercus leaf'], 4),
    ('ref_forest_floor', ['forest floor leaves ground', 'forest floor', 'woodland floor', 'fallen leaves ground'], 3),
    ('ref_hatchet', ['axe in tree stump', 'felling axe', 'axe', 'hatchet'], 4),
]


def _register_existing_wound_refs(man):
    """The wound library's own PROVENANCE.json, re-checked under the manifest's policy."""
    p = os.path.join(WOUND_REFS, 'PROVENANCE.json')
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        doc = json.load(f)
    entries = doc if isinstance(doc, list) else (doc.get('items') or doc.get('files') or doc.get('refs') or [])
    refs, refused = [], []
    for e in entries:
        if not isinstance(e, dict):
            continue
        fn = e.get('file') or e.get('filename') or e.get('name')
        lic = e.get('licence') or e.get('license')
        if not fn:
            continue
        path = fn if os.path.isabs(fn) else os.path.join(WOUND_REFS, os.path.basename(fn))
        if not os.path.exists(path):
            continue
        try:
            refs.append(
                manifest.provenance(
                    path,
                    lic,
                    e.get('source', 'wikimedia'),
                    e.get('url', ''),
                    extra={'title': e.get('title'), 'category': e.get('category')},
                )
            )
        except manifest.LicenceRefused as exc:
            refused.append(str(exc))
    if refused:
        raise manifest.LicenceRefused('wound refs failed policy:\n  ' + '\n  '.join(refused))
    if not refs:
        return None
    return man.add(
        manifest.asset(
            'ref_bark_wounds',
            'ref',
            refs=refs,
            notes='cuts through bark to sapwood: rim, exposed wood, torn fibre. The 3 rubber/'
            'latex tapping close-ups are the usable ones; the rest are context.',
        )
    )


if __name__ == '__main__':  # the CLI lives in build_library_cli
    from zyg_workflows.geom.build_library_cli import main as _cli_main

    raise SystemExit(_cli_main())
