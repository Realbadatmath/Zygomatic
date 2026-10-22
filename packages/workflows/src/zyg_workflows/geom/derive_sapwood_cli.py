# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.derive_sapwood`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.derive_sapwood` still reaches it.
"""

import sys

from zyg_workflows.geom.derive_sapwood import derive_weathered, ingest, manifest


def main():
    man = manifest.Manifest()

    fresh = ingest.polyhaven_texture('oak_veneer_01', res='2k', maps=('Diffuse', 'Displacement', 'nor_gl', 'Rough'))
    man.add(
        manifest.asset(
            'wood_sapwood_fresh',
            'material',
            refs=fresh['provenance'],
            material=fresh,
            world_span_m=0.30,
            notes='fresh hatchet cut interior — raw oak, longitudinal grain',
        )
    )

    weath = derive_weathered()
    man.add(
        manifest.asset(
            'wood_scar_weathered',
            'material',
            refs=weath['provenance'],
            material=weath,
            world_span_m=0.30,
            notes='old scar interior — cropped from the CC0 rubber-tapping cut panel; '
            'dark brown-grey with fine directional grain, which is what a weathered '
            'cut face actually looks like',
        )
    )
    man.save()

    print('fresh    : %s (%d maps)' % (fresh['asset_id'], len(fresh['maps'])))
    print('weathered: crop %s mean rgb %s' % (weath['crop_box'], weath['mean_rgb']))
    print('manifest : %s' % man.path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
