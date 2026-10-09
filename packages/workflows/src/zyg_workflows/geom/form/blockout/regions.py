# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blockout — Anatomical regions: the z-slab fallback, the sibling-group split and the morph-anchored map."""

from zyg_workflows.geom.form.blockout.spectral import (
    np,
    shell_split,
)

# ---------------------------------------------------------------------------------
# regions
# ---------------------------------------------------------------------------------
# Fallback anatomical banding, used only when geom.form.regions is absent or does not
# expose a map this module recognises. Boundaries are ANSUR II landmark heights as
# fractions of stature, taken from geom.anthro.landmarks.REFERENCE_FRACTIONS (male mean),
# so they are measured levels rather than invented ones — but the BAND BETWEEN two levels
# is still a horizontal slab, which is not what a thorax is. Recorded as a fallback for
# that reason.
FALLBACK_BANDS = (
    ('head', 0.870, 1.001, 'above cervicale (ANSUR male mean 0.8639)'),
    ('neck', 0.820, 0.870, 'suprasternale 0.8191 / acromion 0.8203 to cervicale'),
    ('thorax', 0.700, 0.820, 'suprasternale down past thelion 0.7351'),
    ('abdomen', 0.620, 0.700, 'below the tenth rib 0.6380, above omphalion 0.6014'),
    ('pelvis', 0.481, 0.620, 'iliocristale 0.6044 to crotch 0.4815'),
    ('thigh', 0.278, 0.481, 'crotch to mid-patella 0.2780'),
    ('shank', 0.042, 0.278, 'mid-patella to lateral malleolus 0.0415'),
    ('foot', -0.001, 0.042, 'below the lateral malleolus'),
)

# Arm/hand morph targets whose support is subtracted from every axial band. In the A-pose
# the arms hang beside the thorax and the abdomen, so a pure z-slab "thorax" is roughly a
# third arm by vertex count and a pectoral signal measured in it is diluted by that much.
# The support of a morph target is topology-fixed (it is a fixed displacement table), so
# this is an anchor, not a guess.
ARM_TARGETS = (
    'l-upperarm-scale-horiz-incr',
    'r-upperarm-scale-horiz-incr',
    'l-lowerarm-scale-horiz-incr',
    'r-lowerarm-scale-horiz-incr',
    'l-hand-scale-incr',
    'r-hand-scale-incr',
)

# Morph-anchored diagnostic regions: MakeHuman's OWN vertex support for the named target.
# These are the regions the defects actually live in, and unlike a z-slab they are the
# anatomy the morph itself addresses.
#
# Taken as the CORE of the support, not the support. Several targets translate everything
# below them, so their plain 0.3 mm support is the whole body — measured here:
# buttocks-volume-incr displaces 13,717 of 13,718 vertices above that threshold, which is
# not a region, it is a body. Its 0.35-core is 178 vertices. (landmarks.py records the
# same trap for measure-hips-circ-incr.) HOUSE: 0.35 is the loosest core at which
# buttocks-volume-incr stops being the whole body — at 0.20 it is still 13,637 vertices —
# and it leaves the well-behaved targets recognisable: pectoral 436 -> 251, dorsi 430 ->
# 138, stomach-tone 161 -> 95, shoulder muscle 158 -> 82.
MORPH_REGION_CORE = 0.35
MORPH_REGIONS = {
    'pectoral': 'torso-muscle-pectoral-incr',
    'dorsi': 'torso-muscle-dorsi-incr',
    'buttocks': 'buttocks-volume-incr',
    'stomach': 'stomach-tone-incr',
    'shoulder_cap': 'l-upperarm-shoulder-muscle-incr',
}

CAGE_VERTS = 13718


def _to_mask(sel, pos, nb):
    """A sibling's idea of "these vertices" -> a body-shell mask, or None if it is not a
    vertex selection at all. Never coerces: a dict, a record, a string returns None."""
    if isinstance(sel, dict) or isinstance(sel, str):
        return None
    a = np.asarray(sel)
    if a.dtype == bool:
        idx = np.nonzero(a.ravel())[0]
    elif np.issubdtype(a.dtype, np.integer):
        idx = a.ravel()
    else:
        return None
    local = pos[idx[(idx >= 0) & (idx < len(pos))]]
    local = local[local >= 0]
    if not len(local):
        return None
    m = np.zeros(nb, bool)
    m[local] = True
    return m


def _sibling_groups(v, faces, vid):
    """The authored groups from a sibling geom.form.regions, if it has any for this cage.

    These are ADDED to the coarse banding below, never substituted for it: what that
    module authors are small landmark PATCHES (a deltopectoral triangle, a PSIS dimple),
    which is the right anchor for a landmark-visibility predicate and the wrong one for a
    partition of the body. A band energy needs both — the patch to say "here", and the
    slab to say "compared with the rest of the trunk".

    Returns (dict name -> mask, provenance) or (None, why-not). It never raises: an
    unavailable sibling is a recorded degradation, not a crash.
    """
    try:
        try:
            from zyg_workflows.geom.form import regions as RG
        except ImportError:
            import regions as RG  # inside geom/form
    except ImportError as e:  # noqa: BLE001
        return None, 'geom.form.regions is not importable (%s)' % e
    except Exception as e:  # noqa: BLE001
        return None, 'importing geom.form.regions raised %s: %s' % (type(e).__name__, e)

    nb = len(vid)
    pos = np.full(len(v), -1, np.int64)
    pos[vid] = np.arange(nb)
    out, skipped = {}, 0

    load = getattr(RG, 'load_regions', None)
    if callable(load):
        try:
            doc = load(len(v))
        except Exception as e:  # noqa: BLE001
            return None, 'geom.form.regions.load_regions raised %s: %s' % (type(e).__name__, e)
        for name, rec in (doc.get('regions') or {}).items():
            if not isinstance(rec, dict):
                continue
            if rec.get('status') != 'resolved':
                skipped += 1
                continue
            for side in ('l', 'r'):
                key = '%s_%s' % (name, side)
                m = _to_mask(rec.get('vertex_idx_' + side), pos, nb)
                if m is not None:
                    out['rg_' + key] = m
        if out:
            return out, (
                'geom.form.regions.load_regions (%d resolved groups added, %d '
                'unresolved groups skipped)' % (len(out), skipped)
            )
        return None, (
            'geom.form.regions.load_regions returned no RESOLVED group with a '
            'vertex on the body shell (%d unresolved)' % skipped
        )

    for fname in ('region_map', 'vertex_regions', 'regions'):
        fn = getattr(RG, fname, None)
        if not callable(fn):
            continue
        try:
            got = fn(v, faces)
        except Exception as e:  # noqa: BLE001
            return None, 'geom.form.regions.%s(v, faces) raised %s: %s' % (fname, type(e).__name__, e)
        if isinstance(got, dict):
            items = list(got.items())
        elif isinstance(got, np.ndarray) and got.shape == (len(v),):
            items = [(str(u), np.nonzero(got == u)[0]) for u in np.unique(got)]
        else:
            return None, (
                'geom.form.regions.%s returned %s, which this adapter does not '
                'recognise (want a dict of name -> vertex indices/mask, or a '
                '(V,) label array)' % (fname, type(got).__name__)
            )
        for key, sel in items:
            m = _to_mask(sel, pos, nb)
            if m is not None:
                out['rg_' + str(key)] = m
        if out:
            return out, 'geom.form.regions.%s (%d groups)' % (fname, len(out))
        return None, ('geom.form.regions.%s returned nothing this adapter could read as a vertex selection' % fname)
    return None, ('geom.form.regions imported but exposes neither load_regions nor region_map/vertex_regions/regions')


def region_map(v, faces, vid=None, sibling_groups=True, morph_anchored=True):
    """name -> boolean mask over BODY-SHELL vertices, plus where the map came from.

    Three layers, all recorded, none substituting for another:
      the z-fraction BANDING (always) — a partition of the axial body at measured ANSUR
        landmark heights, with the arm morph support subtracted;
      the MORPH-ANCHORED regions (anny cage only) — MakeHuman's own support for the
        targets the known defects live in, prefix 'morph_';
      the SIBLING groups from geom.form.regions (if authored) — small landmark patches,
        prefix 'rg_'.
    """
    v = np.asarray(v, np.float64)
    if vid is None:
        vid = shell_split(v, faces)['vid']
    nb = len(vid)
    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    fz = (v[vid, 2] - zmin) / H

    notes = []
    out = {'body': np.ones(nb, bool)}
    sources = []

    arm = np.zeros(nb, bool)
    arm_note = None
    if len(v) == CAGE_VERTS:
        try:
            from zyg_workflows.geom.anthro import landmarks as LMK

            pos = np.full(len(v), -1, np.int64)
            pos[vid] = np.arange(nb)
            got = 0
            for label in ARM_TARGETS:
                s = LMK._support(label)
                if s is None:
                    continue
                got += 1
                local = pos[s[0]]
                arm[local[local >= 0]] = True
            if not got:
                arm_note = 'none of %d arm targets resolved a support' % len(ARM_TARGETS)
        except Exception as e:  # noqa: BLE001
            arm_note = '%s: %s' % (type(e).__name__, e)
    else:
        arm_note = 'mesh is not the %d-vertex anny cage (%d vertices), so the arm morph supports do not index it' % (
            CAGE_VERTS,
            len(v),
        )
    if arm_note:
        arm[:] = False
        notes.append(
            'ARM MASK UNRESOLVED (%s) — the axial bands below still contain the '
            'arms and any energy attributed to them is contaminated by arm '
            'surface' % arm_note
        )
    else:
        out['arm'] = arm
    for nm, lo, hi, why_band in FALLBACK_BANDS:
        m = (fz >= lo) & (fz < hi) & ~arm
        if not m.any():
            raise RuntimeError(
                'band %r (z-fraction %.3f-%.3f: %s) is EMPTY on this mesh. An empty '
                'region is a broken map, not a small one — every energy reported for it '
                'would be a division by zero mass.' % (nm, lo, hi, why_band)
            )
        out[nm] = m
    sources.append('zfraction_bands(ANSUR II male landmark heights)' + ('' if arm_note else ' minus arm morph support'))

    if sibling_groups:
        got, why = _sibling_groups(v, faces, vid)
        if got:
            out.update(got)
            sources.append(why)
        else:
            notes.append('sibling landmark groups not added: %s' % why)

    if morph_anchored:
        if len(v) != CAGE_VERTS:
            notes.append(
                'morph-anchored regions UNRESOLVED: mesh is not the %d-vertex '
                'anny cage (%d vertices)' % (CAGE_VERTS, len(v))
            )
        else:
            try:
                from zyg_workflows.geom.anthro import landmarks as LMK

                pos = np.full(len(v), -1, np.int64)
                pos[vid] = np.arange(nb)
                for nm, label in MORPH_REGIONS.items():
                    s = LMK._support_core(label, MORPH_REGION_CORE)
                    if s is None:
                        notes.append(
                            'morph region %r UNRESOLVED: target %r has empty '
                            'support at the male reference' % (nm, label)
                        )
                        continue
                    local = pos[s[0]]
                    local = local[local >= 0]
                    if not len(local):
                        notes.append('morph region %r UNRESOLVED: its support has no vertex on the body shell' % nm)
                        continue
                    mask = np.zeros(nb, bool)
                    mask[local] = True
                    out['morph_' + nm] = mask
                sources.append('morph_support_cores@%.2f(%s)' % (MORPH_REGION_CORE, ','.join(sorted(MORPH_REGIONS))))
            except Exception as e:  # noqa: BLE001
                notes.append('morph-anchored regions UNRESOLVED: %s: %s' % (type(e).__name__, e))

    return {
        'regions': out,
        'source': ' + '.join(sources),
        'sources': sources,
        'notes': notes,
        'counts': {k: int(m.sum()) for k, m in out.items()},
    }
