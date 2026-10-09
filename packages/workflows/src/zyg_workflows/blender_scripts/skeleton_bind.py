# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Put the CC0 anatomical skeleton mesh inside a base-body actor.

Source: Blender Studio Human Base Meshes v1.4.1 (CC0), collection
"Skeleton - Realistic" -- 135 named MESH objects ``GEO-skeletion.*`` (sic).
Every object's ORIGIN sits on the joint it hangs from, which is what makes a
per-segment fit to the cmu_mb rig cheap and exact.

The 135 pieces are mapped onto the 31-bone cmu_mb rig, placed group by group
(one rigid transform for the trunk + head, a per-segment fit for every limb
bone), joined into ONE mesh named ``skeleton`` skinned rigidly -- every vertex
weight 1.0 in exactly one vertex group, named exactly as its rig bone.

Harness::

    /usr/local/bin/blender -b --factory-startup \\
        --python blender_scripts/skeleton_bind.py -- \\
        --rig male_realistic --out /tmp/claude-1000/skelfit

Always run Blender with ``-b --factory-startup``: the user profile's add-ons
crash and flood background mode.
"""

# This file is a SHIM.  The 1,614 lines it used to hold live in
# ``skeleton_bind_parts/``, cut at this file's own section banners, every section
# byte for byte.  The shim stays at the original path because Blender loads it BY
# PATH, outside any package context:
#
#     blender -b --factory-startup --python blender_scripts/skeleton_bind.py
#
# and because proxy_actor.py does a flat ``import skeleton_bind`` after putting
# this directory on sys.path.  Both modes work: the shim puts its OWN directory
# on sys.path before importing the parts as a top-level package, so no package
# context is needed either way.

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import skeleton_bind_parts as _parts  # noqa: E402
from skeleton_bind_parts.entry import main  # noqa: E402

# LAST_FIT is REBOUND by attach_skeleton (``global LAST_FIT``), so a by-value
# re-export here would freeze at the empty dict and proxy_actor's
# ``skeleton_bind.LAST_FIT['pieces']`` would raise.  It is deliberately NOT put
# in this module's dict; __getattr__ below resolves it in .entry on every access.
# Everything else is a function, a constant, or a list mutated in place
# (EXTRA_MESHES -- proxy_actor does ``del skeleton_bind.EXTRA_MESHES[:]``, which
# needs the same object, not a copy), so the plain re-export is exact.
_LIVE = ('LAST_FIT',)

for _name in _parts.__all__:
    if _name not in _LIVE:
        globals()[_name] = getattr(_parts, _name)
del _name


def __getattr__(name):
    """Resolve the rebound globals live in the module that owns them."""
    if name in _LIVE:
        return getattr(_parts.entry, name)
    raise AttributeError('module %r has no attribute %r' % (__name__, name))


if __name__ == '__main__':
    args = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    sys.exit(main(args))
