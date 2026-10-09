# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""arch_pack_ingest.cli — the command line: --plan, --fetch, --prepare, --report.

Moved verbatim out of arch_pack_ingest.py (lines 1694-2019) when that 2,019-line
module became this package; no logic was changed.
"""

from __future__ import annotations

import argparse
import json
import os
from .common import PACKS, PH_API, PH_CATEGORIES, _get_json
from .polyhaven import ph_select, ph_plan, ph_fetch, ph_select_all, ph_hdri_plan, ph_tex_plan, ph_simple_fetch
from .ambientcg import ACG_CATEGORIES, acg_plan, acg_fetch, acg_prepare
from .kenney import kenney_slugs, kenney_plan, kenney_fetch
from .prepare import ph_tex_prepare, ph_hdri_prepare, ACG_ALPHA_KINDS, acg_alpha_plan, acg_alpha_prepare
from .smithsonian import (
    si_records,
    si_plan,
    si_slug,
    si_fetch,
    si_unit_provenance,
    SI_PLY_TARGET_TRIS,
    si_ply_plan,
    si_ply_fetch,
)
from .provenance import write_provenance
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_pack_ingest')


# ── cli ─────────────────────────────────────────────────────────────────────


def human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.1f}{u}'
        n /= 1024
    return f'{n:.1f}TB'


def _build_parser():
    """Return the argument parser: the four modes (--plan/--fetch/--prepare/--report) and their knobs."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument(
        '--fetch',
        choices=[
            'polyhaven',
            'ambientcg',
            'kenney',
            'polyhaven-all',
            'polyhaven-hdri',
            'polyhaven-tex',
            'smithsonian',
            'smithsonian-mammals',
            'acg-decals',
            'acg-atlas',
        ],
    )
    ap.add_argument('--report', action='store_true')
    ap.add_argument(
        '--prepare',
        choices=['ambientcg', 'polyhaven-tex', 'polyhaven-hdri', 'acg-decals', 'acg-atlas'],
        help='unpack the material zips into web-servable 1K PBR sets',
    )
    ap.add_argument('--gapfill', action='store_true', help='top the material library up across the MISSING categories')
    ap.add_argument('--limit', type=int, default=300)
    ap.add_argument('--si-limit', type=int, default=0, help='cap the Smithsonian haul (0 = the whole plain-GLB set)')
    ap.add_argument('--res', default='2k')
    ap.add_argument('--all', action='store_true', help='re-take packs already on disk instead of only the new ones')
    return ap


def _held_dirs(root):
    """Return the names of root's sub-directories — an empty set when root does not exist."""
    return {d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))} if os.path.isdir(root) else set()


def _load_registry(root):
    """Return the pack registry held at <root>/registry.json, or {} when there is none yet."""
    p = os.path.join(root, 'registry.json')
    return json.load(open(p)) if os.path.isfile(p) else {}


def _merge_registry(root, reg):
    """Return the registry at <root>/registry.json updated with the freshly fetched rows reg."""
    keep = _load_registry(root)
    keep.update(reg)
    return keep


def _registry_totals(reg):
    """Return (item count, total bytes) of a pack registry, per-file rows and flat rows alike."""
    n = sum(1 for _ in reg)
    b = sum(
        sum(x['bytes'] for x in r.get('files', {}).values()) if 'files' in r else r.get('bytes', 0)
        for r in reg.values()
    )
    return n, b


def _run_polyhaven(a):
    """Plan the architecture-relevant Poly Haven models; with --fetch polyhaven, take them too."""
    meta = ph_select()
    print(f'poly haven: {len(meta)} architecture-relevant models')
    plan = ph_plan(sorted(meta), a.res)
    total = sum(e['size'] for f in plan.values() for e in f.values())
    print(f'  glTF@{a.res}: {len(plan)} models, {human(total)}')
    if a.fetch == 'polyhaven':
        root = os.path.join(PACKS, 'polyhaven_arch')
        reg = ph_fetch(plan, meta, root, a.res)
        write_provenance(
            'polyhaven_arch',
            root,
            reg,
            {'format': f'glTF separate + JPG textures @{a.res}', 'categories': sorted(PH_CATEGORIES)},
        )
        print(f'  wrote {len(reg)} models -> {root}')


def _run_ambientcg(a):
    """Plan the ambientCG material haul; with --fetch ambientcg, download the zips as well."""
    plan = acg_plan(a.limit)
    total = sum(x['size'] for x in plan)
    print(f'ambientcg: {len(plan)} materials, {human(total)}')
    if a.fetch == 'ambientcg':
        root = os.path.join(PACKS, 'ambientcg')
        reg = acg_fetch(plan, root)
        write_provenance(
            'ambientcg', root, reg, {'format': '2K JPG PBR zip per material', 'categories': ACG_CATEGORIES}
        )
        print(f'  wrote {len(reg)} materials -> {root}')


def _run_polyhaven_all(a):
    """Fetch every published Poly Haven model that is not on disk yet and extend the registry."""
    meta = ph_select_all()
    root = os.path.join(PACKS, 'polyhaven_arch')
    have = {d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and not d.startswith('_')}
    new = sorted(set(meta) - have)
    print(f'poly haven models: {len(meta)} published, {len(have)} held, {len(new)} new')
    plan = ph_plan(new, a.res)
    print(f'  glTF@{a.res}: {len(plan)}, {human(sum(e["size"] for f in plan.values() for e in f.values()))}')
    reg = ph_fetch(plan, meta, root, a.res)
    keep = _merge_registry(root, reg)
    write_provenance(
        'polyhaven_arch',
        root,
        keep,
        {
            'format': f'glTF separate + JPG textures @{a.res}',
            'selection': (
                'the WHOLE published model catalogue; the '
                'earlier category filter is superseded and '
                'recorded under categories_first_haul'
            ),
            'categories_first_haul': sorted(PH_CATEGORIES),
        },
    )
    print(f'  wrote {len(reg)} new, registry now {len(keep)} -> {root}')


def _run_polyhaven_hdri(a):
    """Fetch the Radiance HDRIs that are not held yet and extend the HDRI registry."""
    meta = _get_json(f'{PH_API}/assets?t=hdris')
    root = os.path.join(PACKS, 'polyhaven_hdri')
    have = _held_dirs(root)
    new = sorted(set(meta) - have)
    print(f'poly haven HDRIs: {len(meta)} published, {len(have)} held, {len(new)} new')
    plan = ph_hdri_plan(new, a.res)
    print(f'  hdr@{a.res}: {len(plan)}, {human(sum(e["size"] for f in plan.values() for e in f.values()))}')
    reg = ph_simple_fetch(plan, meta, root, 'hdri', a.res)
    keep = _merge_registry(root, reg)
    write_provenance('polyhaven_hdri', root, keep, {'format': f'Radiance .hdr @{a.res}'})
    print(f'  wrote {len(reg)} new, registry now {len(keep)} -> {root}')


def _run_polyhaven_tex(a):
    """Fetch the Poly Haven surface textures that are not held yet and extend their registry."""
    meta = _get_json(f'{PH_API}/assets?t=textures')
    root = os.path.join(PACKS, 'polyhaven_tex')
    have = _held_dirs(root)
    new = sorted(set(meta) - have)
    print(f'poly haven textures: {len(meta)} published, {len(have)} held, {len(new)} new')
    plan = ph_tex_plan(new, a.res)
    print(f'  jpg@{a.res}: {len(plan)}, {human(sum(e["size"] for f in plan.values() for e in f.values()))}')
    reg = ph_simple_fetch(plan, meta, root, 'tex', a.res)
    keep = _merge_registry(root, reg)
    write_provenance(
        'polyhaven_tex',
        root,
        keep,
        {
            'format': f'JPG PBR maps @{a.res}',
            'size_note': (
                'every asset carries a MEASURED physical size '
                'from the API dimensions field (mm), so no '
                'category median or 1 m assumption is used'
            ),
        },
    )
    print(f'  wrote {len(reg)} new, registry now {len(keep)} -> {root}')


def _run_smithsonian(a):
    """Fetch the plain-GLB Smithsonian records that are not in the registry yet."""
    root = os.path.join(PACKS, 'smithsonian')
    rows = si_records()
    plan, why = si_plan(rows)
    print(f'smithsonian: {len(rows)} 3D records, {len(plan)} with a plain GLB')
    print(f'  skipped: {why}')
    have = _load_registry(root)
    plan = [x for x in plan if x['id'] not in have]
    if a.si_limit:
        plan = plan[: a.si_limit]
    print(f'  fetching {len(plan)}, {human(sum(x["size"] for x in plan))}')
    reg = si_fetch(plan, root)
    have.update(reg)
    write_provenance(
        'smithsonian',
        root,
        have,
        {
            'format': 'low-resolution GLB (no draco), one per record',
            'units': sorted({r['unit_name'] for r in have.values()}),
        },
    )
    n_units = si_unit_provenance(root, have)
    print(f'  wrote {len(reg)} new across {n_units} museum units, registry now {len(have)} -> {root}')


def _name_mammal_plan(plan, have, root, sub):
    """Give every planned PLY record a collision-free stem and destination under <root>/<sub>.

    The names are assigned up front and seeded from what the Mammals directory already
    holds, so a resumed run can neither rename an existing file nor collide with one.
    Returns the rows whose destination does not exist yet.
    """
    taken = {
        os.path.splitext(os.path.basename(r['file']))[0].lower()
        for r in have.values()
        if os.path.dirname(r['file']) == sub
    }
    for x in plan:
        x['stem'] = si_slug(x['name'], x['id'], taken)
        x['dest'] = os.path.join(root, sub, x['stem'] + '.glb')
    return [x for x in plan if not os.path.isfile(x['dest'])]


def _run_smithsonian_mammals(a):
    """Convert the PLY-only Smithsonian mammal scans to decimated GLBs and record them."""
    root = os.path.join(PACKS, 'smithsonian')
    sub = 'Mammals'
    reg_path = os.path.join(root, 'registry.json')
    have = _load_registry(root)
    rows = si_records()
    plan = si_ply_plan(rows)
    print(f'smithsonian mammals: {len(plan)} PLY-only records')
    plan = [x for x in plan if x['id'] not in have]
    plan = _name_mammal_plan(plan, have, root, sub)
    if a.si_limit:
        plan = plan[: a.si_limit]
    print(f'  converting {len(plan)} (target {SI_PLY_TARGET_TRIS} faces, masters discarded)')
    staging = os.path.join(PACKS, '_ply_staging')
    reg = si_ply_fetch(plan, root, staging)
    have.update(reg)
    with open(reg_path, 'w') as f:
        json.dump(have, f, indent=1)
    n_units = si_unit_provenance(root, have)
    try:
        os.rmdir(staging)
    except OSError as _exc:
        _zyg_log.debug('ply staging dir not empty, left in place: %s', _exc)
    print(f'  wrote {len(reg)} mammal scans, registry now {len(have)} across {n_units} units')


def _run_acg_alpha(a):
    """Fetch and/or prepare the two ambientCG alpha packs (decals and atlases)."""
    for flag, kind in (('acg-decals', 'Decal'), ('acg-atlas', 'Atlas')):
        pack, group, human_name = ACG_ALPHA_KINDS[kind]
        root = os.path.join(PACKS, pack)
        if a.fetch == flag:
            plan = acg_alpha_plan(kind)
            have = _load_registry(root)
            plan = [x for x in plan if x['id'] not in have]
            print(f'{human_name}: {len(plan)} to fetch, {human(sum(x["size"] for x in plan))}')
            reg = acg_fetch(plan, root)
            have.update(reg)
            write_provenance(
                pack, root, have, {'format': '2K PNG (JPG where no PNG is published)', 'kind': kind, 'group': group}
            )
            print(f'  wrote {len(reg)} new, registry now {len(have)} -> {root}')
        if a.prepare == flag:
            r = acg_alpha_prepare(root, group)
            print(
                f'  prepared {r["prepared"]} {group.lower()} '
                f'({r["with_alpha"]} with an opacity map, '
                f'{r["measured"]} with a measured physical size), '
                f'{r["failed"]} failed'
            )


def _run_kenney(a):
    """Plan the Kenney 3D packs; with --fetch kenney, take them and extend the registry."""
    root = os.path.join(PACKS, 'kenney')
    slugs = kenney_slugs()
    have = _held_dirs(root)
    new = [s_ for s_ in slugs if s_ not in have]
    print(f'kenney: {len(slugs)} published 3D packs, {len(have & set(slugs))} held, {len(new)} new')
    plan = kenney_plan(new if not a.all else slugs)
    bad = [p_['id'] for p_ in plan if p_.get('error')]
    total = sum(p_.get('size', 0) for p_ in plan)
    print(
        f'  resolvable: {len(plan) - len(bad)}, {human(total)}' + (f'  (unresolved: {", ".join(bad)})' if bad else '')
    )
    if a.fetch == 'kenney':
        reg = kenney_fetch(plan, root)
        keep = _merge_registry(root, reg)
        # The first nine packs were curated by hand and their PROVENANCE
        # carries per-pack evidence this script cannot regenerate. Keep it.
        prior_p = os.path.join(root, 'PROVENANCE.json')
        prior = json.load(open(prior_p)) if os.path.isfile(prior_p) else {}
        prior = prior.get('curated_2026_08_05', prior) if prior else {}
        write_provenance(
            'kenney',
            root,
            keep,
            {
                'format': 'vendor zip, extracted; GLB/glTF + OBJ + FBX',
                'note': (
                    'zip URLs are content-hashed and change on every '
                    'republish, so they are resolved from the asset '
                    'page at ingest time, never stored'
                ),
                'packs': sorted(keep),
                'curated_2026_08_05': prior,
            },
        )
        print(f'  wrote {len(reg)} new packs, registry now {len(keep)} -> {root}')


def _run_prepare(a):
    """Unpack the HDRI, Poly Haven texture and ambientCG hauls into web-servable sets."""
    if a.prepare == 'polyhaven-hdri':
        r = ph_hdri_prepare(os.path.join(PACKS, 'polyhaven_hdri'))
        print(f'  {r["thumbs"]} HDRI thumbnails, {r["failed"]} without one')

    if a.prepare == 'polyhaven-tex':
        root = os.path.join(PACKS, 'polyhaven_tex')
        r = ph_tex_prepare(root)
        print(
            f'  prepared {r["prepared"]} surfaces '
            f'({r["measured"]} with a measured physical size), '
            f'{r["failed"]} failed, {human(r["web_bytes"])} of web textures'
        )

    if a.prepare == 'ambientcg':
        root = os.path.join(PACKS, 'ambientcg')
        r = acg_prepare(root)
        print(
            f'  prepared {r["prepared"]} materials '
            f'({r["measured"]} with a measured physical size), '
            f'{r["failed"]} failed, {human(r["web_bytes"])} of web textures'
        )


def _run_gapfill(a):
    """Top the ambientCG library up at 1K across the categories it is still missing."""
    root = os.path.join(PACKS, 'ambientcg')
    reg_path = os.path.join(root, 'registry.json')
    have = _load_registry(root)
    plan = acg_plan(a.limit, res='1K', skip=set(have))
    total = sum(x['size'] for x in plan)
    print(f'gapfill: {len(plan)} materials, {human(total)}')
    if not a.plan:
        reg = acg_fetch(plan, root)
        have.update(reg)
        with open(reg_path, 'w') as f:
            json.dump(have, f, indent=1)
        print(f'  registry now {len(have)} materials')


def _run_report():
    """Print the item count and on-disk size of each ingested pack."""
    for pack in ('polyhaven_arch', 'ambientcg'):
        f = os.path.join(PACKS, pack, 'registry.json')
        if not os.path.isfile(f):
            print(f'{pack}: not ingested')
            continue
        n, b = _registry_totals(json.load(open(f)))
        print(f'{pack}: {n} items, {human(b)}')


def main():
    """Parse the command line and run, in order, every action the flags select."""
    a = _build_parser().parse_args()

    if a.plan or a.fetch == 'polyhaven':
        _run_polyhaven(a)
    if a.plan or a.fetch == 'ambientcg':
        _run_ambientcg(a)
    if a.fetch == 'polyhaven-all':
        _run_polyhaven_all(a)
    if a.fetch == 'polyhaven-hdri':
        _run_polyhaven_hdri(a)
    if a.fetch == 'polyhaven-tex':
        _run_polyhaven_tex(a)
    if a.fetch == 'smithsonian':
        _run_smithsonian(a)
    if a.fetch == 'smithsonian-mammals':
        _run_smithsonian_mammals(a)
    _run_acg_alpha(a)
    if a.plan or a.fetch == 'kenney':
        _run_kenney(a)
    _run_prepare(a)
    if a.gapfill:
        _run_gapfill(a)
    if a.report:
        _run_report()


if __name__ == '__main__':
    main()
