# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Creature Studio server extension — the 3D base-model seam.

Two ops behind /inspect/api/studio/creature/:

  glb?id=<12hex>   stream the creature's OWN mesh. The creature's GLB lives
                   either in its lora-dataset dir (the TRELLIS reconstruction,
                   34 MB) or in the prop-mesh library — both OUTSIDE the
                   mesh_packs root that /inspect/arch-asset/ fences, so they
                   need their own route and their own fence.
  bases            the fallback creatures of the zyg_creatures pack, for the
                   page to show when a creature has no mesh of its own. Those
                   ARE under mesh_packs, so their urls go to arch-asset.

The fence is creature_fx.mesh_glb_path: id must match ^[a-f0-9]{12}$ and the
manifest's path must realpath inside that creature's dataset dir or inside
data/assets/prop_meshes/. A manifest is operator-written data — it states a
request, it does not grant permission.
"""


def _glb(payload, method):  # noqa: ARG001 — GET and POST answer alike
    from zyg_workflows import creature_fx as cfx

    cid = str(payload.get('id') or '').strip().lower()
    fp = cfx.mesh_glb_path(cid)
    if not fp:
        return {'error': 'no mesh', 'code': 404}
    try:
        with open(fp, 'rb') as fh:
            blob = fh.read()
    except OSError:
        return {'error': 'no mesh', 'code': 404}
    return blob, 'model/gltf-binary', f'{cid}.glb'


def _bases(payload, method):  # noqa: ARG001
    from zyg_workflows import creature_fx as cfx

    return {'ok': True, 'bases': cfx.BASE_CREATURES}


ROUTES = {'glb': _glb, 'bases': _bases}
