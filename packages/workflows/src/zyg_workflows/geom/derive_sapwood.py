# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""derive_sapwood.py — cut-interior materials for the scars (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.derive_sapwood

A hatchet scar has two ages and they do not share a surface, so they do not share a
texture. Eleven attempts to generate either of them failed; both are taken from CC0
photography instead.

FRESH — pale sapwood, exposed this season.
    Poly Haven `oak_veneer_01`, CC0. Raw oak, natural wood grain, the correct species and
    the correct surface: a hatchet biting along a trunk exposes LONGITUDINAL grain, not
    the end grain that every inpaint attempt produced ("pale raw timber" is the model's
    strongest cue for a felled log's cut face, which is why it kept drawing tree rings).

WEATHERED — cut years ago, oxidised, re-cut.
    Cropped from the CC0 rubber-tapping photograph. This is what the reference actually
    shows, and it is worth stating plainly: the tapping refs are NOT pale sapwood. The cut
    faces in them are dark brown-grey with fine directional grain, because a rubber tapping
    panel is re-cut continually and has weathered. Using them for fresh cuts would have
    been wrong; using them for old ones is what they are evidence of.

The crop box is fixed and recorded rather than chosen at runtime, so the derived texture is
byte-reproducible and can be re-derived from the same public source by anyone.

NO TILING, AND THAT IS DELIBERATE. The first version mirrored the crop into a 2x2 block to
make it seamless, and the result was unusable: a patch of pale lichen clipped at the box
edge mirrored into a symmetric four-fold blob that read as a kaleidoscope rather than as
wood. Mirroring cannot introduce a seam but it does introduce symmetry, and symmetry is
the more visible artefact at this scale. It is also unnecessary — the texture covers 300mm
and a scar is 30-60mm, so no single scar ever sees the texture repeat. Seamlessness buys
nothing here and costs the whole look.
"""

import os

os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from . import ingest, manifest  # noqa: E402

REFS = os.path.join(ingest.ASSET_ROOT, 'wounds', '_refs')
OUT = os.path.join(ingest.ASSET_ROOT, 'materials')

# Source: "Latex collection in Kampung Bukit Jagung, Pendang", CC0, 3120x4160.
# Inside the dark reddish-brown tapping panel: above the white latex line that runs the
# lower-left rim, left of the pale lichen patch around x2300-2600/y2200-2700, and clear of
# the background foliage. The first box (1500,900)-(2400,2400) clipped that lichen at its
# corner, which is what produced the blob.
WEATHERED_SRC = 'Latex_collection_in_Kampung_Bukit_Jagung__Pendang_20250918_143241.jpg'
WEATHERED_BOX = (1100, 700, 2100, 2000)  # x0, y0, x1, y1


def _square(patch, size=1024):
    """Centre-crop to square and resize. No mirroring — see the module docstring."""
    h, w = patch.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    return cv2.resize(patch[y0 : y0 + s, x0 : x0 + s], (size, size), interpolation=cv2.INTER_AREA)


def _height_from_luma(rgb, blur=3):
    """A grain height map from luminance. On a cut face the dark lines ARE the grooves,
    so luminance is a direct (if approximate) stand-in for depth — and it only has to
    carry sub-millimetre grain, since the millimetre-scale shape is the boolean's job."""
    g = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    g = cv2.GaussianBlur(g, (blur | 1, blur | 1), 0)
    lo, hi = np.percentile(g, 2), np.percentile(g, 98)
    return np.clip((g - lo) / max(hi - lo, 1e-6), 0, 1)


def derive_weathered(size=1024):
    src = os.path.join(REFS, WEATHERED_SRC)
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    img = cv2.imread(src)
    x0, y0, x1, y1 = WEATHERED_BOX
    patch = img[y0:y1, x0:x1]
    if patch.size == 0:
        raise RuntimeError('crop box %s is outside %s' % (WEATHERED_BOX, img.shape))

    d = os.path.join(OUT, 'scar_weathered')
    os.makedirs(d, exist_ok=True)
    diffuse = _square(patch, size)
    height = (_square(_height_from_luma(patch), size) * 255).astype(np.uint8)
    cv2.imwrite(os.path.join(d, 'diffuse.png'), diffuse)
    cv2.imwrite(os.path.join(d, 'displacement.png'), height)
    cv2.imwrite(
        os.path.join(d, '_source_crop.png'), cv2.resize(patch, (512, int(512 * patch.shape[0] / patch.shape[1])))
    )

    mean = diffuse.reshape(-1, 3).mean(0)[::-1]  # BGR -> RGB
    return {
        'maps': {'diffuse': os.path.join(d, 'diffuse.png'), 'displacement': os.path.join(d, 'displacement.png')},
        'texture_px': size,
        'licence': 'CC0-1.0',
        'source': 'wikimedia-commons',
        'url': 'https://commons.wikimedia.org/wiki/File:' + WEATHERED_SRC,
        'crop_box': list(WEATHERED_BOX),
        'mean_rgb': [round(float(v), 1) for v in mean],
        'provenance': [
            manifest.provenance(
                os.path.join(d, 'diffuse.png'),
                'CC0',
                'wikimedia-commons',
                'https://commons.wikimedia.org/wiki/File:' + WEATHERED_SRC,
                extra={'derived_from': WEATHERED_SRC, 'crop_box': list(WEATHERED_BOX)},
            )
        ],
    }


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
    raise SystemExit(main())
