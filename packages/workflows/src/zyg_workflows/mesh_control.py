# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mesh_control.py — a REGISTERED MESH's views as diffusion conditioning maps.

WHAT THIS ADDS, AND WHAT IT DELIBERATELY DOES NOT.
`geom/conditioning.py` already owns the pixel conventions — near-white depth, the
(n*0.5+0.5) normal encoding, geometric lineart, IndexOB segmentation — and it has owned
them since 2026-08-04. This module does NOT re-implement any of that; duplicating a
convention is how two surfaces end up disagreeing about which way round a depth map goes.
It adds the two things `conditioning` has no way to know:

  1. WHICH FILES. conditioning.build() takes pass_lib.render_set()'s one-directory-per-view
     layout. A prop_mesh SHEET writes one flat passes/ folder holding
     <view>_<kind>_0001.exr for all 16 views, and the files are addressed through
     prop_mesh_library by asset id and view id. This module bridges the two.

  2. WHICH PIXELS ARE THE SUBJECT. Every map in conditioning normalises over its subject,
     so whatever counts as the subject sets the scale — and on a turntable sheet the
     GROUND PLANE is a rendered surface. Measured on the Pufferball's front_full view: the
     creature spans 1.236-1.608 m, the floor spans 1.004-4.429 m. Normalising over every
     rendered pixel therefore spends 89% of the range on floor and leaves the creature 27
     of 255 levels to describe its entire form. The IndexOB pass exists so this is a
     lookup rather than a heuristic — and the lookup is BY NAME, through the asset's own
     `sheet['idx']` vocabulary, because the integer differs per creature.

FAIL CLOSED ON AN EMPTY SUBJECT. A view whose mask selects nothing is SKIPPED and named in
the manifest, never written as a black PNG. A black control map is not a weak signal — it
is a confident instruction to put every surface at infinity, and it looks like a
successful run in every log.

NORMALISATION SCOPE. `normalize='view'` (default) gives each still its own full contrast.
`normalize='asset'` shares one depth range across every view, which is what a TURNTABLE
needs: per-view scaling makes the depth breathe as the creature rotates and a video model
reads that as the object changing size. The manifest records which was used.

THE NORMAL PASS on sheets rendered before 2026-08-26 is unusable — Blender's Normal socket
is a VECTOR, so wired straight to a File Output it writes EXR channels named X/Y/Z, cv2
resolves only one of them, and passes_io correctly refuses to treat one component as
three. Fixed in prop_mesh/pufferball_sheet.py via pass_lib.rgb_named_socket(); a sheet
rendered before that reports `normal: null` here with the reason, rather than a fabricated
map.

CLI:
    python3 mesh_control.py pufferball
    python3 mesh_control.py pufferball --views top_down back --normalize asset --force
"""

import json
import os

from zyg_workflows.geom import conditioning as _cond  # noqa: E402
from zyg_workflows.geom import passes_io as _pio  # noqa: E402

import numpy as np  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS = ('depth', 'normal', 'lineart', 'segment', 'matte')
DEFAULT_KINDS = ('depth', 'matte')
DEFAULT_EXCLUDE = ('ground',)
MANIFEST = 'control.json'


def _log(fn):
    return fn or (lambda _m: None)


def subject_mask(ps, idx_map=None, exclude=DEFAULT_EXCLUDE):
    """Surfaces that ARE the subject: rendered geometry, minus background, minus the
    parts named in `exclude` — resolved through the asset's own index vocabulary so the
    caller never writes a bare integer."""
    m = ps.valid & (ps.index > 0)
    for name in exclude or ():
        if idx_map and name in idx_map:
            m &= ps.index != int(idx_map[name])
    return m


def matte_map(mask):
    """The subject's silhouette, white on black — a compositing / inpaint alpha.

    Not in conditioning.py because it is not a conditioning map: no ControlNet consumes
    it. It exists so a caller can composite the rendered creature onto a plate, or hand
    an edit model an explicit region."""
    return mask.astype(np.uint8) * 255


# ── library-facing resolution ────────────────────────────────────────────────
def control_dir(asset_id):
    from zyg_workflows import prop_mesh_library as PML

    rec = PML.get(asset_id)
    return os.path.join(PML.ROOT, rec['dir'], 'control') if rec else None


def path_for(asset_id, view_id, kind):
    d = control_dir(asset_id)
    return os.path.join(d, '%s_%s.png' % (view_id, kind)) if d else None


def load_view(asset_id, view_id):
    """A PassSet for one registered view, or None when its depth pass is missing."""
    from zyg_workflows import prop_mesh_library as PML

    dp = PML.pass_path(asset_id, view_id, 'depth')
    if not dp:
        return None
    return _pio.load_paths(
        dp,
        PML.pass_path(asset_id, view_id, 'index'),
        PML.pass_path(asset_id, view_id, 'normal'),
        PML.beauty_path(asset_id, view_id),
        label='%s/%s' % (asset_id, view_id),
    )


def index_map(asset_id):
    from zyg_workflows import prop_mesh_library as PML

    return (PML.sheet(asset_id) or {}).get('idx') or {}


def cam_rotation(asset_id, view_id):
    """The view's 3x3 camera world rotation from sheet.json, or None.

    Blender's Normal AOV is WORLD-space. A ControlNet normal checkpoint wants
    CAMERA space — a surface facing the viewer at (128,128,255) in every view.
    With this the conversion is exact; without it the map is a rotated signal and
    the camera-facing channel swings view by view (measured on this sheet: front
    G=27, back G=235, side_left R=232, side_right R=22, top_down B=233).

    Sheets rendered before 2026-08-27 have no `cam_r` and return None, which keeps
    the old world-space output rather than inventing a camera for them. Re-render
    the sheet to get camera-space normals."""
    from zyg_workflows import prop_mesh_library as PML

    for v in (PML.sheet(asset_id) or {}).get('views') or []:
        if v.get('id') == view_id:
            return v.get('cam_r')
    return None


def asset_depth_range(asset_id, view_ids=None, *, exclude=DEFAULT_EXCLUDE):
    """(near, far) in metres across the given views — the range a turntable must share.

    Scoped to `view_ids` rather than the whole sheet on purpose. A sheet mixes body
    framings with a `detail` macro (0.59 m) and a `wide` establisher (2.44 m); taking the
    range over all sixteen makes it 0.59-2.44 m and squeezes every body view into the
    middle sixth of it. The shared range has to span the sequence being RENDERED, not
    every view that happens to be registered."""
    from zyg_workflows import prop_mesh_library as PML

    idx = index_map(asset_id)
    near = far = None
    for vid in view_ids or PML.view_ids(asset_id):
        ps = load_view(asset_id, vid)
        if ps is None:
            continue
        m = subject_mask(ps, idx, exclude)
        if not m.any():
            continue
        sub = ps.depth[m]
        lo, hi = float(np.nanmin(sub)), float(np.nanmax(sub))
        near = lo if near is None else min(near, lo)
        far = hi if far is None else max(far, hi)
    return near, far


# ── build ────────────────────────────────────────────────────────────────────
def build(
    asset_id, view_ids=None, *, exclude=DEFAULT_EXCLUDE, normalize='view', kinds=DEFAULT_KINDS, log_fn=None, force=False
):
    """Write conditioning maps for a registered asset. Returns the manifest dict."""
    from zyg_workflows import prop_mesh_library as PML

    log = _log(log_fn)
    rec = PML.get(asset_id)
    if not rec:
        raise ValueError('not registered: %r' % asset_id)
    if normalize not in ('view', 'asset'):
        raise ValueError("normalize must be 'view' or 'asset'")
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise ValueError('unknown kinds %s (have %s)' % (bad, list(KINDS)))

    idx = index_map(asset_id)
    if exclude and not any(n in idx for n in exclude):
        log(
            "[mesh-control] WARNING: none of exclude=%s is in this asset's index map %s "
            '— NOTHING will be excluded and the depth range may be set by the floor' % (list(exclude), sorted(idx))
        )
    vids = list(view_ids or PML.view_ids(asset_id))
    d = control_dir(asset_id)
    os.makedirs(d, exist_ok=True)

    lo = hi = None
    if normalize == 'asset':
        lo, hi = asset_depth_range(asset_id, vids, exclude=exclude)
        log('[mesh-control] asset-wide depth range %.4f..%.4f m' % (lo or 0.0, hi or 0.0))

    views, skipped = {}, {}
    for vid in vids:
        ps = load_view(asset_id, vid)
        if ps is None:
            skipped[vid] = 'no depth pass'
            continue
        m = subject_mask(ps, idx, exclude)
        if not m.any():
            # Never a black PNG — a view where the subject is genuinely off-frame is a
            # BUILD problem, and a valid-looking file defers the discovery to whatever
            # renders from it.
            skipped[vid] = 'empty subject mask'
            log('[mesh-control] %s: empty subject mask — skipped' % vid)
            continue

        want = [k for k in kinds if k != 'matte']
        maps = {}
        if want:
            # subject_floor=1 keeps 0 exclusively for background, so the depth map's
            # silhouette and the matte describe the SAME pixels — see conditioning.
            allm = _cond.maps_for(ps, mask=m, lo=lo, hi=hi, subject_floor=1, cam=cam_rotation(asset_id, vid))
            maps = {k: allm.get(k) for k in want}
        if 'matte' in kinds:
            maps['matte'] = matte_map(m)

        entry, missing = {}, {}
        for k, v in maps.items():
            p = os.path.join(d, '%s_%s.png' % (vid, k))
            if v is None:
                entry[k] = None
                missing[k] = (
                    'pass unusable — for `normal`, the EXR carries X/Y/Z-named '
                    'channels; re-render with pass_lib.rgb_named_socket wiring'
                )
                continue
            if k == 'normal':
                # Record which space the bytes are actually in. A normal map is not
                # self-describing and world-space is not valid ControlNet input, so
                # a consumer must be able to tell without re-deriving it.
                if cam_rotation(asset_id, vid) is None:
                    entry['normal_space'] = 'world'
                    log(
                        '[mesh-control] %s: no cam_r in sheet.json — normal map is '
                        'WORLD-space and is not valid ControlNet input; re-render '
                        'the sheet to fix' % vid
                    )
                else:
                    entry['normal_space'] = 'camera'
            if force or not os.path.exists(p):
                _cond.write_maps({k: v}, d, stem='%s_' % vid)
            entry[k] = os.path.basename(p)
        sub = ps.depth[m]
        entry.update(
            {
                'near_m': round(float(np.nanmin(sub)), 5),
                'far_m': round(float(np.nanmax(sub)), 5),
                'pixels': int(m.sum()),
                'coverage': round(float(m.sum()) / m.size, 5),
            }
        )
        if missing:
            entry['unavailable'] = missing
        views[vid] = entry

    man = {
        'asset_id': asset_id,
        'kinds': list(kinds),
        'normalize': normalize,
        'exclude': list(exclude or ()),
        'excluded_indices': {n: idx[n] for n in (exclude or ()) if n in idx},
        'polarity': 'depth: near=white (inverse depth), background=black',
        'normal_convention': ('camera-space (n*0.5+0.5), viewer-facing = (128,128,255), background = (128,128,255)'),
        'shared_range_m': ([round(lo, 5), round(hi, 5)] if normalize == 'asset' and lo is not None else None),
        'views': views,
        'skipped': skipped,
    }
    with open(os.path.join(d, MANIFEST), 'w', encoding='utf-8') as fh:
        json.dump(man, fh, indent=2)
        fh.write('\n')
    log('[mesh-control] %s: %d views written, %d skipped -> %s' % (asset_id, len(views), len(skipped), d))
    return man


def ensure(asset_id, **kw):
    """Return the existing manifest, or build one."""
    d = control_dir(asset_id)
    p = os.path.join(d, MANIFEST) if d else None
    if p and os.path.isfile(p):
        try:
            with open(p, encoding='utf-8') as fh:
                return json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('mesh cache %s unreadable, rebuilding: %s', p, _exc)
    return build(asset_id, **kw)


if __name__ == '__main__':  # the CLI lives in mesh_control_cli
    from zyg_workflows.mesh_control_cli import _main as _cli_main

    raise SystemExit(_cli_main())
