#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_manifest.py — write HAIR.json + PROVENANCE.json for one hair pack.

The catalogue (character_hair_assets.py) is FAIL-CLOSED: a pack with no
PROVENANCE.json it can read a permitted licence out of is invisible, not
"probably fine". This writes that evidence from what the converters measured
and from what the VENDOR shipped beside the bytes — the .mhclo header, the
.mhmat comment, the pack's own json — never from the download page alone."""

import json
import os
import shutil


def mh_pack(conv, src_hair, out_dir, pack_id, label, licence, credit, source_url, evidence, refused):
    """A MakeHuman hair-card pack."""
    items = []
    for r in conv['items']:
        if r['id'] in {x['id'] for x in refused}:
            continue
        items.append(
            {
                'id': r['id'],
                'file': r['file'],
                'kind': 'cards',
                'part': 'hair',
                'label': _pretty(r['id']),
                'author': r.get('author') or '',
                'tags': [t for t in r.get('tags', []) if t.lower() != 'makehuman™'],
                'verts': r['verts'],
                'tris': r['tris'],
                'texture': r.get('texture'),
                'normal_map': r.get('normal_map'),
                'licence_in_file': r.get('licence_mhclo') or '',
                'bbox': r['bbox_head_units'],
            }
        )
    man = {
        'label': label,
        'pack': pack_id,
        'credit': credit,
        'source_url': source_url,
        'fit': {
            'frame': 'head_width',
            'note': 'GLB is in HEAD UNITS: origin at the donor head centre '
            '(cx, yTop, zc), one unit = one head width. Place at the '
            'target head centre and scale by its measured head width.',
            'donor': conv['donor_head_frame'],
            'donor_mesh': 'MakeHuman hm08 base mesh, group "body" only '
            '(the helper cage measures 18 % wider than the head)',
        },
        'items': items,
        'refused': refused,
    }
    _write(out_dir, man, licence, credit, source_url, evidence, refused, len(items))
    # previews: MakeHuman ships a .thumb per style, which is a PNG
    pv = os.path.join(out_dir, '_previews')
    os.makedirs(pv, exist_ok=True)
    n = 0
    for it in items:
        for cand in (os.path.join(src_hair, it['id'], it['id'] + '.thumb'),):
            if os.path.isfile(cand):
                shutil.copyfile(cand, os.path.join(pv, os.path.splitext(it['file'])[0] + '.png'))
                n += 1
    return len(items), n


def groom_pack(lines, out_dir, pack_id, label, licence, credit, source_url, evidence, notes):
    """A Blender Studio strand-groom pack."""
    items = []
    for d in lines:
        for r in d['items']:
            items.append(
                {
                    'id': r['id'],
                    'file': r['file'],
                    'kind': 'strands',
                    'part': r['part'],
                    'label': _pretty(r['id']),
                    'character': r['character'],
                    'author': 'Blender Studio',
                    'tags': [r['character'], r['part']],
                    'verts': r['verts'],
                    'tris': r['tris'],
                    'strands_kept': r['strands_kept'],
                    'strands_total': r['strands_total'],
                    'samples': r['samples'],
                    'source_object': r['skull_surface'],
                    'note': notes.get(r['character'], ''),
                    'bbox': r['bbox_skull_units'],
                }
            )
    man = {
        'label': label,
        'pack': pack_id,
        'credit': credit,
        'source_url': source_url,
        'fit': {
            'frame': 'skull_radius',
            'note': 'GLB is in SKULL UNITS: origin at the centre of a '
            'least-squares sphere fitted to the scalp the hair grew '
            'on, one unit = that sphere radius. Fit the same sphere '
            'to the target skull and map one onto the other.',
            'donor_mesh': 'per groom: the scalp/emitter surface named in source_object',
        },
        'items': items,
    }
    _write(out_dir, man, licence, credit, source_url, evidence, [], len(items))
    return len(items), 0


def _pretty(stem):
    s = stem.replace('elvs_', '').replace('_hair', '').replace('_', ' ').strip()
    return (s[:1].upper() + s[1:]) if s else stem


def _write(out_dir, man, licence, credit, source_url, evidence, refused, n):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'HAIR.json'), 'w', encoding='utf-8') as fh:
        json.dump(man, fh, indent=1, ensure_ascii=False)
    prov = {
        'curated': '2026-09-23',
        'workflow': 'hair install session 2026-09-23 (licence read per FILE)',
        'license': licence,
        'license_quote': evidence.get('quote', ''),
        'license_evidence_url': evidence.get('url', ''),
        'packs': [
            {
                'name': man['label'],
                'source_url': source_url,
                'license': licence,
                'license_quote': evidence.get('quote', ''),
                'license_evidence_url': evidence.get('url', ''),
                'notes': evidence.get('notes', ''),
            }
        ],
        'credit': credit,
        'items': n,
        'refused': refused,
        'problems': evidence.get('problems', []),
    }
    with open(os.path.join(out_dir, 'PROVENANCE.json'), 'w', encoding='utf-8') as fh:
        json.dump(prov, fh, indent=1, ensure_ascii=False)


if __name__ == '__main__':  # the CLI lives in build_manifest_cli
    from zyg_workflows.tools.hair_assets.build_manifest_cli import main as _cli_main

    raise SystemExit(_cli_main())
