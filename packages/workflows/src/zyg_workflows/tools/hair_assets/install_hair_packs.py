#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""install_hair_packs.py — write the three hair packs' manifests and licence
evidence from what the converters measured.

    python3 install_hair_packs.py <scratch_dir> <packs_root>

scratch_dir holds the converter outputs (sys_hair.json, hair02.json,
grooms*.jsonl) and the extracted vendor trees under x/."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_manifest as bm  # noqa: E402

# One style in the CC-BY hair02 pack declares a licence its own pack manifest
# contradicts. The file beside the bytes wins, and AGPL3 is not a licence this
# project may embed in published output, so the style is not installed.
REFUSED = [
    {
        'id': 'elvs_witchy_lil_bob',
        'why': 'AGPL3 in its own .mhclo header ("# license AGPL3"), while '
        'packs/hair02.json calls the whole pack CC-BY. The file beside the '
        'bytes wins and AGPL3 may not be embedded in published output.',
        'author_in_file': 'Unknown',
    }
]

GROOM_NOTES = {
    'einar': 'Realistic adult male. Curves groom: 10,299 hair, 27,935 beard and 3,359 brow strands in the source.',
    'ellie': 'Stylised character; the groom is driven by an embedded rig script Blender will not auto-run.',
    'victoria': 'Stylised character.',
    'rex': 'Stylised character.',
    'phil': 'Stylised character.',
    'jay': 'Stylised character.',
}


def main():
    scratch, root = sys.argv[1], sys.argv[2]

    # ── CC0 MakeHuman system hair ───────────────────────────────────────────
    conv = json.load(open(os.path.join(scratch, 'sys_hair.json')))
    n, pv = bm.mh_pack(
        conv,
        os.path.join(scratch, 'x/sys/hair'),
        os.path.join(root, 'makehuman_system_hair_cc0'),
        'makehuman_system_hair_cc0',
        'MakeHuman system hair (CC0)',
        'CC0-1.0',
        'MakeHuman / Data Collection AB, Joel Palmius, Jonas Hauquier',
        'https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html',
        {
            'url': 'https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html',
            'quote': 'packs/makehuman_system_assets.json: every one of the 94 '
            'entries carries "license": "CC0". Each hair .mhmat repeats '
            'it in its own header: "This asset was explicitly released '
            'as CC0 in september 2020."',
            'notes': '10 hairstyles from the CC0 system asset pack. Hair-card '
            'meshes, placed on hm08 through their .mhclo barycentric '
            'binding (mhclo_fit.py) and stored in head units. Alpha mode '
            'rewritten to MASK/0.45 (glb_alpha.py) because Blender 4.3 '
            'exports BLEND whatever the material says, and hundreds of '
            'overlapping cards do not sort.',
            'problems': [
                'The 280 MB system asset pack also holds clothes, eyes, teeth and eyebrows; only hair/ was installed.'
            ],
        },
        [],
    )
    print(f'CC0 system hair: {n} items, {pv} previews')

    # ── CC-BY MakeHuman hair02 ──────────────────────────────────────────────
    conv = json.load(open(os.path.join(scratch, 'hair02.json')))
    n, pv = bm.mh_pack(
        conv,
        os.path.join(scratch, 'x/hair02/hair'),
        os.path.join(root, 'makehuman_hair02_ccby'),
        'makehuman_hair02_ccby',
        'MakeHuman hair02 by Elvaerwyn (CC-BY)',
        'CC-BY-4.0',
        'Elvaerwyn (MakeHuman Community) — CC-BY',
        'https://static.makehumancommunity.org/assets/assetpacks/hair02.html',
        {
            'url': 'https://static.makehumancommunity.org/assets/assetpacks/hair02.html',
            'quote': 'packs/hair02.json gives every entry "license": "CC-BY", '
            '"author": "Elvaerwyn". 12 of the 21 .mhclo files repeat '
            '"# license CC_by" in their own header; 8 carry no licence '
            'line and rest on the pack manifest; 1 contradicts it and '
            'was refused (see refused).',
            'notes': '20 of 21 hairstyles installed. ATTRIBUTION REQUIRED: credit '
            'Elvaerwyn / MakeHuman Community on anything shipped. Placed '
            'through .mhclo binding, stored in head units, alpha MASK.',
            'problems': [
                'The pack manifest calls all 21 styles CC-BY; reading '
                'the licence per FILE found one AGPL3. Never trust a '
                'pack-level licence for a pack of contributed assets.'
            ],
        },
        REFUSED,
    )
    print(f'CC-BY hair02: {n} items, {pv} previews')

    # ── CC-BY Blender Studio grooms ─────────────────────────────────────────
    lines = []
    for fn in ('grooms.jsonl', 'grooms2.jsonl'):
        fp = os.path.join(scratch, fn)
        if os.path.isfile(fp):
            lines.extend(json.loads(l) for l in open(fp) if l.strip())
    # keep only what is on disk (a re-run may have removed a character)
    gdir = os.path.join(root, 'blender_studio_grooms_ccby', 'glb')
    have = set(os.listdir(gdir)) if os.path.isdir(gdir) else set()
    for d in lines:
        d['items'] = [i for i in d['items'] if i['file'] in have]
    lines = [d for d in lines if d['items']]
    # a character converted twice keeps the LAST run
    seen, keep = set(), []
    for d in reversed(lines):
        if d['character'] in seen:
            continue
        seen.add(d['character'])
        keep.append(d)
    # Ellie's groom is driven by an embedded rig script that Blender will not
    # auto-run, and without it part of it evaluates displaced: her ponytail
    # renders standing straight up off the crown. Measured on the clay head and
    # refused rather than shipped and explained later.
    ELLIE_REFUSED = {'ellie_hair', 'ellie_hair_cut_hair'}
    for d in keep:
        d['items'] = [i for i in d['items'] if i['id'] not in ELLIE_REFUSED]
    keep = [d for d in keep if d['items']]
    n, _ = bm.groom_pack(
        list(reversed(keep)),
        os.path.join(root, 'blender_studio_grooms_ccby'),
        'blender_studio_grooms_ccby',
        'Blender Studio character grooms (CC-BY)',
        'CC-BY-4.0',
        'Blender Studio — CC-BY 4.0',
        'https://studio.blender.org/characters/',
        {
            'url': 'https://studio.blender.org/characters/rain/v3/',
            'quote': 'each Blender Studio character page links '
            'creativecommons.org/licenses/by/4.0/ (checked per character '
            'when the .blend files were installed on 2026-09-02)',
            'notes': 'Strand grooms baked out of the production .blend files. '
            'Legacy particle systems are converted through '
            'curves.convert_from_particle_system() so the CHILDREN are '
            'baked, not the 10-85 guides. Every strand is resampled and '
            'the set decimated to a triangle budget, then written as '
            'tapered ribbons in SKULL UNITS. No material: Character '
            'Studio colours them from its own hair-colour tool.',
            'problems': [
                'ATTRIBUTION REQUIRED — CC-BY, not CC0.',
                'ellie_hair and ellie_hair_cut_hair were converted and '
                'REFUSED: her groom is driven by an embedded rig script '
                'that --factory-startup will not auto-run, and the '
                'ponytail evaluates standing straight up off the crown.',
                'These are one-off production grooms, not a parametric library: each is the hair of one character.',
            ],
        },
        GROOM_NOTES,
    )
    print(f'CC-BY Blender Studio grooms: {n} items')


main()
