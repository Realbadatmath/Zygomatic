# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.build_library`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.build_library` still reaches it.
"""

import argparse
import sys

from zyg_workflows.geom import ingest, manifest
from zyg_workflows.geom.build_library import MATERIALS, REFS, _register_existing_wound_refs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--res', default='4k')
    ap.add_argument('--refs', type=int, default=0, help='override per-query ref count')
    ap.add_argument('--skip-materials', action='store_true')
    args = ap.parse_args(argv)

    man = manifest.Manifest()
    added, failed = [], []

    for aid, phid, span, note in [] if args.skip_materials else MATERIALS:
        try:
            mat = ingest.polyhaven_texture(phid, res=args.res)
            # a material's own reference IS its diffuse map: a CC0 photoscan of the real
            # surface, which is exactly what the rule asks for
            man.add(
                manifest.asset(aid, 'material', refs=mat['provenance'], material=mat, world_span_m=span, notes=note)
            )
            added.append('%s <- polyhaven/%s (%d maps)' % (aid, phid, len(mat['maps'])))
        except Exception as e:
            failed.append('%s: %s' % (aid, e))

    for aid, query, n in REFS:
        try:
            refs = ingest.openverse_refs(query, count=(args.refs or n), name_hint=aid)
            if not refs:
                failed.append('%s: no CC0 results >=900px for %r' % (aid, query))
                continue
            man.add(manifest.asset(aid, 'ref', refs=refs, notes='openverse cc0: %r' % query))
            added.append('%s <- openverse %r (%d images)' % (aid, query, len(refs)))
        except Exception as e:
            failed.append('%s: %s' % (aid, e))

    try:
        if _register_existing_wound_refs(man):
            added.append('ref_bark_wounds <- existing wound library provenance')
    except Exception as e:
        failed.append('ref_bark_wounds: %s' % e)

    man.save()

    print('── Phase 1 library ' + '─' * 40)
    for a in added:
        print('  OK   %s' % a)
    for f in failed:
        print('  FAIL %s' % f)
    audit = man.audit()
    print('  %d assets registered, %d rule violations' % (len(man.doc['assets']), len(audit)))
    for aid, probs in audit.items():
        print('    %s: %s' % (aid, '; '.join(probs)))
    print('  manifest: %s' % man.path)
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
