# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — character loading, building, measuring and name resolution.

Moved verbatim from geom/anthro/__main__.py (lines 114-217) when that 1,757-line
file became the __main__ shim over this package. No logic was changed.
"""


# ---------------------------------------------------------------------------------
# character loading
# ---------------------------------------------------------------------------------
def _characters():
    """{name: record} over both registry sections, with the section recorded.

    The stock anny body is added as a CONTROL. Without it there is no way to tell a
    property of the base cage from a property of a character's morphs — measured, wrist
    circumference is ~4 SD below the ANSUR mean on the stock body and stays there on every
    character, so that is anny's wrist and not a defect of the character.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro import landmarks as LMK

    out = {}
    reg = MS._registry()
    for sec in ('originals', 'derived'):
        for k in reg.get(sec, {}) or {}:
            p = reg[sec][k].get('params') or {}
            phen = p.get('phenotype') or {}
            sex = p.get('sex') or ('female' if phen.get('gender', 0) > 0.5 else 'male')
            out[k] = {
                'name': k,
                'section': sec,
                'phenotype': phen,
                'local_changes': p.get('local_changes'),
                'anatomy': p.get('anatomy_layer'),
                'sex': sex,
                'ancestry': p.get('ancestry'),
                'age_frac': phen.get('age'),
                'params': p,
            }
    out['anny-neutral'] = {
        'name': 'anny-neutral',
        'section': 'control',
        'phenotype': dict(LMK.REF_MALE),
        'local_changes': None,
        'anatomy': None,
        'sex': 'male',
        'ancestry': None,
        'age_frac': LMK.REF_MALE.get('age'),
        'params': {},
    }
    return out


def _build(rec):
    """(vertices float64, faces) for one character record."""
    import numpy as np
    from zyg_workflows.geom import mesh_skeletons as MS

    v, f, _applied = MS._build_mesh(rec['phenotype'], rec['local_changes'])
    if rec.get('anatomy'):
        v = MS._apply_anatomy(v, f, rec['anatomy'])
    return np.asarray(v, np.float64), f


def _measure(rec, name=None):
    from zyg_workflows.geom.anthro import measure as MEAS

    v, f = _build(rec)
    out = MEAS.measure_mesh(
        v, f, sex=rec['sex'], phenotype=rec['phenotype'], local_changes=rec['local_changes'], name=name or rec['name']
    )
    return out, v, f


def _age_years(rec):
    """MakeHuman's macro age parameter in years, via measure.py's verified mapping.
    Needed because the reference bands are adult soldiers and a child scored against them
    is a category error, not an outlier."""
    if rec.get('age_frac') is None:
        return None
    from zyg_workflows.geom.anthro import measure as MEAS

    return MEAS._age_years(rec['age_frac'])


def _validate_ancestry(sex, ancestry):
    """Fail loudly on an ancestry the pack does not carry, ONCE, before any work.

    Without this the per-ratio lookups each raise, each get caught, and the run produces a
    report with 34 silently unbanded rows — which is precisely the silent-fallback bias
    the reference pack raises exceptions to prevent. reference.band() writes a better
    message than anything reconstructable here (it distinguishes 'unknown group' from
    'exists in ANSUR but below the n floor'), so let its own text through.
    """
    if ancestry is None:
        return
    from zyg_workflows.geom.anthro.reference import reference

    ref = reference()
    probe = ref.doc['mahalanobis']['order'][0]
    try:
        ref.band(probe, sex, ancestry)
    except KeyError as e:
        raise SystemExit(str(e).strip('"\'')) from e


def _resolve(name):
    chars = _characters()
    if name in chars:
        return chars[name]
    raise SystemExit('unknown character %r. Known: %s' % (name, ', '.join(sorted(chars))))
