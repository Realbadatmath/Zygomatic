# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_sheet_render.py — the sheet contract, checked on real registered assets.

    /usr/bin/python3.12 prop_mesh/test_sheet_render.py [asset_id ...]

WHAT THIS TESTS AND WHY IT IS NOT A UNIT TEST.
The failure this file exists to catch is not a wrong number in a function — it is a
sheet that LOOKS registered and is unusable downstream: normal EXRs whose channels are
named X/Y/Z (16 of those shipped once), a missing `cam_r` that leaves every normal map
in world space, an `idx` with no `ground` entry so the floor sets the depth range, a
view with no depth pass. Every one of those passes `verify()` — the hashes are fine,
the files are all there — and each one is only visible by opening the actual bytes.

So this runs against REGISTERED ASSETS on disk, not against fixtures. It needs no GPU
and no Blender. With no arguments it checks every asset in the registry that names
prop_mesh/sheet_render.py as its renderer, plus whatever ids are passed explicitly.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

FAILS = []
CHECKS = [0]


def ck(cond, msg):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(msg)
    return bool(cond)


def check_licence_resolution():
    import zyg_workflows.prop_mesh.sheet_register as SR

    packs = os.path.join(_ROOT, 'data', 'assets', 'mesh_packs')
    ck(
        SR.pack_licence('/etc/hostname') is None,
        'pack_licence must return None for a file outside every pack — a guessed licence must never reach a record',
    )
    for rel, want_key in (
        ('smithsonian/Mammals/Gorilla_gorilla_gorilla_Cranium_12.glb', 'source_sha256'),
        ('kenney/survival-kit/Models/GLB format/workbench.glb', 'source_pack_sha256'),
    ):
        p = os.path.join(packs, rel)
        if not os.path.isfile(p):
            continue
        m = SR.pack_licence(p)
        if not ck(m is not None, 'pack_licence found no pack for %s' % rel):
            continue
        ck(
            m['licence']['spdx'].upper().startswith('CC0'),
            '%s: expected a CC0 spdx, got %r' % (rel, m['licence']['spdx']),
        )
        ck(bool(m['licence']['evidence_url']), '%s: no licence evidence url' % rel)
        ck(bool(m['licence']['evidence_quote']), '%s: no licence evidence quote' % rel)
        ck(len(m['provenance'].get('source_file_sha256') or '') == 64, "%s: the FILE's own sha256 is missing" % rel)
        # A pack-level hash and a file-level hash must never be readable as each other.
        ck(want_key in m['provenance'], '%s: expected the pack hash under %r' % (rel, want_key))


def check_asset(aid):
    from zyg_workflows import prop_mesh_library as PML
    from zyg_workflows import mesh_control as MC

    rec = PML.get(aid)
    if not ck(rec is not None, '%s is not registered' % aid):
        return
    sh = PML.sheet(aid)
    if not ck(sh is not None, '%s: no readable sheet.json' % aid):
        return

    # ── the vocabulary ──────────────────────────────────────────────────────
    idx = sh.get('idx') or {}
    ck(
        'ground' in idx,
        "%s: sheet idx has no 'ground' — mesh_control's default exclude is that NAME, so "
        'the floor would set the depth range' % aid,
    )
    ck(len(set(idx.values())) == len(idx), '%s: idx has duplicate indices' % aid)
    ck(isinstance(sh.get('size_m'), (int, float)) and sh['size_m'] > 0, '%s: sheet has no positive size_m' % aid)

    # ── every view, every file ──────────────────────────────────────────────
    ids = PML.view_ids(aid)
    ck(len(ids) >= 3, '%s: only %d views' % (aid, len(ids)))
    for v in sh.get('views') or []:
        vid = v.get('id')
        for k in ('azimuth', 'elevation', 'framing', 'distance_m'):
            ck(v.get(k) is not None, '%s/%s: sheet row has no %s' % (aid, vid, k))
        r = v.get('cam_r')
        ck(
            isinstance(r, list) and len(r) == 3 and all(len(x) == 3 for x in r),
            '%s/%s: no 3x3 cam_r — every normal map from this view is WORLD space and '
            'not valid ControlNet input' % (aid, vid),
        )
        ck(PML.beauty_path(aid, vid) is not None, '%s/%s: no beauty render' % (aid, vid))
        for kind in ('depth', 'normal', 'index'):
            ck(PML.pass_path(aid, vid, kind) is not None, '%s/%s: no %s EXR' % (aid, vid, kind))

    # ── the one that shipped broken: normal channel naming ──────────────────
    import cv2

    for vid in ids[:4]:
        p = PML.pass_path(aid, vid, 'normal')
        if not p:
            continue
        n = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        ck(
            n is not None and n.ndim == 3 and n.shape[2] >= 3,
            '%s/%s: normal EXR reads back as %s — the compositor wired the VECTOR socket '
            'straight through, so the channels are named X/Y/Z and cv2 resolves one of '
            'them. Re-render through pass_lib.rgb_named_socket.' % (aid, vid, None if n is None else n.shape),
        )

    # ── visibility: every part owns pixels somewhere ────────────────────────
    if sh.get('visible_px') is not None:
        dead = sorted(k for k, n in (sh['visible_px'] or {}).items() if not n)
        ck(not dead, '%s: parts visible in NO view: %s' % (aid, ', '.join(dead)))

    # ── the control build ───────────────────────────────────────────────────
    cd = MC.control_dir(aid)
    cp = os.path.join(cd, MC.MANIFEST) if cd else ''
    if ck(cp and os.path.isfile(cp), '%s: no control.json — mesh_control never ran' % aid):
        with open(cp, encoding='utf-8') as fh:
            man = json.load(fh)
        ck(not man.get('skipped'), '%s: control build SKIPPED views %s' % (aid, man.get('skipped')))
        ck(
            len(man.get('views') or {}) == len(ids),
            '%s: control has %d views for %d sheet views' % (aid, len(man.get('views') or {}), len(ids)),
        )
        ck(
            'ground' in (man.get('excluded_indices') or {}),
            '%s: control build excluded nothing — the floor is in the depth range' % aid,
        )
        for vid, e in (man.get('views') or {}).items():
            ck(
                0.0 < (e.get('coverage') or 0) < 1.0,
                '%s/%s: subject coverage %s is not a fraction of the frame' % (aid, vid, e.get('coverage')),
            )
            ck(
                e.get('normal_space') in (None, 'camera'),
                '%s/%s: normal map is %s space' % (aid, vid, e.get('normal_space')),
            )


def check_creature_op():
    """The Creature Studio mesh op is registered, generative, and honest about reach."""
    from zyg_workflows import creature_fx as C

    o = C.OP_BY_ID.get('cm_mesh')
    if not ck(o is not None, 'creature_fx has no cm_mesh op'):
        return
    ck(
        o['cls'] == 'edit',
        "cm_mesh must be cls='edit' — that is what gives it the ~ pip and the "
        '[generative] tooltip the page draws from the registry',
    )
    ck(o['sec'] == 'Camera' and o['bar'] == 'side', 'cm_mesh is on the wrong bar/section')
    ck(bool(o['fn']), 'cm_mesh has no clause function')
    ck(o['fn']({'v': 'top_down'}, {}).strip() != '', 'cm_mesh clause is empty')
    p, why = C._mesh_control_depth('definitely-not-a-creature', 'top_down')
    ck(
        p is None and 'no registered mesh' in why,
        'a creature with no mesh must be refused with a reason, got %r' % (why,),
    )


if __name__ == '__main__':  # the CLI lives in test_sheet_render_cli
    from zyg_workflows.prop_mesh.test_sheet_render_cli import main as _cli_main

    raise SystemExit(_cli_main())
