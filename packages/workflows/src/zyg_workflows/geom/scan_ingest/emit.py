# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STAGE f — EMIT.

Moved verbatim out of the old single-file scan_ingest.py (lines 2074-2306).
"""

import os
import time
import numpy as np

from zyg_workflows.geom.scan_ingest.constants import (
    CONSENT_MIN_FIELD_CHARS,
    CONSENT_REQUIRED_KEYS,
    PERM_MATCH_TOL_M,
    SCHEMA,
    SOFTWARE_LICENCES,
    ScanIngestError,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _atomic_json,
    _log,
    _read_json,
    _stage_path,
    _target_cage,
)


# ==================================================================================
# STAGE f — EMIT
# ==================================================================================
def _validate_consent(consent):
    if not isinstance(consent, dict):
        raise ScanIngestError(
            "no consent record. A scan of a real person IS that person's likeness and "
            'needs explicit written permission for commercial use, recorded in '
            'PROVENANCE.json like any other asset licence. See '
            'docs/photogrammetry_capture.md §5. Required keys: %s' % ', '.join(CONSENT_REQUIRED_KEYS)
        )
    # THE OLD CHECK WAS `not str(consent.get(k, '')).strip()`, AND str(None) IS 'None'.
    # A record whose every value was null, 0 or False therefore passed, and stage_emit wrote
    # `licence: null / licence_evidence: null` into PROVENANCE.json next to
    # `is_a_likeness: true` — a validated grant, on the one gate that guards a real person's
    # likeness. Six of six deliberately empty records were accepted; only literal empty
    # strings and absent keys were refused. Each key is now typed and checked for what it is
    # actually supposed to carry.
    bad = []
    for k in CONSENT_REQUIRED_KEYS:
        if k not in consent:
            bad.append('%s: absent' % k)
            continue
        val = consent[k]
        if k == 'recognisable_likeness_permitted':
            # A real, explicit boolean. Not a truthy string, not 1, not None. Either the
            # subject permitted a recognisable likeness or they did not, and 'we do not
            # know' is not one of the two answers.
            if not isinstance(val, bool):
                bad.append('%s: must be a JSON true/false, got %r' % (k, val))
            continue
        # everything else is prose a human wrote and a human can be shown
        if isinstance(val, bool) or not isinstance(val, str):
            bad.append('%s: must be a non-empty string, got %r' % (k, val))
        elif not val.strip():
            bad.append('%s: is blank' % k)
        elif len(val.strip()) < CONSENT_MIN_FIELD_CHARS:
            bad.append(
                '%s: %r is too short to be a record of anything (< %d characters)' % (k, val, CONSENT_MIN_FIELD_CHARS)
            )
    if bad:
        raise ScanIngestError(
            'consent record is not usable: %s. Required keys: %s. A scan of a real person '
            "IS that person's likeness; a record that carries nulls or placeholders is not "
            'a permission, and this gate will not turn one into a PROVENANCE entry that '
            'reads like one. See docs/photogrammetry_capture.md §5.'
            % ('; '.join(bad), ', '.join(CONSENT_REQUIRED_KEYS))
        )
    # LICENCE EVIDENCE, under the same house rule as every other asset: a licence name is a
    # claim, evidence is a URL or a quoted document. Refuse a bare name.
    ev = consent['licence_evidence'].strip()
    if not (any(tok in ev for tok in ('http://', 'https://', 'file://', '/')) or '"' in ev or "'" in ev):
        raise ScanIngestError(
            'consent licence_evidence %r carries no locator and no quotation. House rule: '
            'every licence needs EVIDENCE — a URL, a path to the signed document, or the '
            'exact wording of the grant — not just its name (%r). ' % (ev, consent['licence'])
        )
    return dict(consent)


def _relief_subdiv_permutation(character, level, n_expect):
    """Map mesh_skeletons._subdivide vertex order -> relief_subdiv.subdivide vertex order.

    Returns (perm or None, doc). See the index trap in stage_emit.__doc__. This FAILS SOFT:
    any disagreement in vertex count, a non-bijective match, or a worst distance above
    PERM_MATCH_TOL_M returns None with a stated reason, because emitting a wrong
    permutation would silently scatter the residual across the body.
    """
    doc = {
        'from': 'geom.mesh_skeletons._subdivide',
        'to': 'geom.relief_subdiv.subdivide',
        'tolerance_m': PERM_MATCH_TOL_M,
        'apply': 'off_rs = np.zeros_like(offset_m); off_rs[to_relief_subdiv_index] = offset_m',
    }
    try:
        from scipy.spatial import cKDTree
        from zyg_workflows.geom import mesh_skeletons as MS
        from zyg_workflows.geom import relief_subdiv as RS

        cage_v, cage_f = _target_cage(character)
        a_v = np.asarray(MS._subdivide(cage_v, cage_f, level)[0], np.float64)
        b_v = np.asarray(RS.subdivide(cage_v, cage_f, level)[0], np.float64)
    except Exception as e:  # noqa: BLE001 — fail soft
        doc['status'] = 'unavailable: %s: %s' % (type(e).__name__, e)
        return None, doc
    if len(a_v) != n_expect or len(b_v) != len(a_v):
        doc['status'] = 'vertex-count disagreement: residual %d, _subdivide %d, relief_subdiv %d' % (
            n_expect,
            len(a_v),
            len(b_v),
        )
        return None, doc
    d, idx = cKDTree(b_v).query(a_v, workers=-1)
    doc['max_match_distance_m'] = float(d.max())
    if len(np.unique(idx)) != len(idx):
        doc['status'] = 'match is not bijective — no permutation emitted'
        return None, doc
    if float(d.max()) > PERM_MATCH_TOL_M:
        doc['status'] = (
            'worst match %.3e m exceeds PERM_MATCH_TOL_M %.1e m — the two '
            'subdividers are not producing the same surface here' % (d.max(), PERM_MATCH_TOL_M)
        )
        return None, doc
    doc['status'] = 'ok'
    doc['is_identity'] = bool(np.array_equal(idx, np.arange(len(idx))))
    return idx.astype(np.int64), doc


def stage_emit(out_dir, *, consent, verbose=True):
    """Write the offsets geom/relief_subdiv.py can consume, plus PROVENANCE.json.

    THE FORMAT. A displacement TEXTURE would need a UV parameterisation of the cage; the
    cage carries none that this module can see, so what is emitted is the vertex-offset
    form: a per-vertex scalar along a per-vertex normal, at a stated subdivision level,
    keyed to the target character. That is the same shape relief.apply_relief already
    produces internally (a displacement field D added to the vertex array), so a consumer
    that can apply one can apply the other. If a UV set ever exists, baking this to a
    texture is a rasterisation away — nothing here has to change.

    THE INDEX TRAP, MEASURED. There are TWO subdividers in this repo and they do NOT agree
    on vertex ORDER. stage_residual works in mesh_skeletons._subdivide order; the intended
    consumer geom/relief_subdiv.py works in its own relief_subdiv.subdivide (Catmull-Clark)
    order. Measured on the female cage at level 1, both produce 54,848 vertices and the
    SAME limit surface — nearest-neighbour distance between the two vertex sets maxes at
    3.4e-8 m — but the orderings differ: taken index-for-index the two arrays disagree by
    up to 1.663 m (p50 0.073 m), and the map between them is a genuine permutation that is
    not the identity. Handing this field to relief_subdiv without reindexing would scatter
    every ridge to a random place on the body, and it would look like noise rather than
    like a bug.

    So this stage emits `to_relief_subdiv_index`: the permutation P with
    relief_subdiv_order[P[k]] == mesh_skeletons_order[k]. A consumer in relief_subdiv order
    does `off_rs = np.zeros_like(offset_m); off_rs[P] = offset_m`. It is computed by
    nearest-neighbour matching between the two vertex sets and is written ONLY if that
    match is bijective and its worst distance is below PERM_MATCH_TOL_M — otherwise the
    field is emitted without a permutation and `index_permutation.status` says why, because
    a wrong permutation is worse than no permutation.
    """
    rs = _read_json(_stage_path(out_dir, 'residual'), 'residual')
    al = _read_json(_stage_path(out_dir, 'align'), 'align')
    dn = _read_json(_stage_path(out_dir, 'dense'), 'dense')
    sc = _read_json(_stage_path(out_dir, 'scale'), 'scale')
    sfm = _read_json(_stage_path(out_dir, 'sfm'), 'sfm')
    consent = _validate_consent(consent)

    z = np.load(rs['residual_npz'])
    resid, nrm, cov = z['residual_m'], z['normal'], z['covered']
    offsets = (resid[:, None] * nrm).astype(np.float32)

    perm, perm_doc = _relief_subdiv_permutation(al['target_character'], int(rs['subdiv_level']), len(resid))
    out = os.path.join(out_dir, 'scan_residual.npz')
    arrays = dict(
        offset_m=offsets,
        residual_m=resid,
        normal=nrm,
        covered=cov,
        subdiv_level=np.int64(rs['subdiv_level']),
        stature_m=np.float64(rs['stature_m']),
        cutoff_frac_of_stature=np.float64(rs['cutoff_frac_of_stature']),
    )
    if perm is not None:
        arrays['to_relief_subdiv_index'] = perm
    np.savez_compressed(out, **arrays)
    _log(verbose, 'emit: index permutation %s' % perm_doc['status'])

    prov = {
        'schema': SCHEMA,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'what': 'High-frequency surface residual harvested from a photogrammetric scan of '
        'a consenting human subject, expressed as per-vertex normal offsets on the '
        "subdivided cage of character %r. The scan's PROPORTIONS are not present: "
        'they are removed by construction in stage "residual" (low-pass at %.3f of '
        'stature, difference kept).' % (al['target_character'], rs['cutoff_frac_of_stature']),
        'subject_likeness': {
            'is_a_likeness': True,
            'subject': consent.get('subject'),
            'granted_by': consent.get('granted_by'),
            'date': consent.get('date'),
            'licence': consent.get('licence'),
            'licence_evidence': consent.get('licence_evidence'),
            'document': consent.get('document'),
            'recognisable_likeness_permitted': consent.get('recognisable_likeness_permitted'),
            'scope': consent.get('scope'),
            'note': 'This pipeline uses the ANONYMOUS SURFACE DETAIL grant, not the '
            'recognisable-likeness grant: only wavelengths below %.1f mm survive, '
            'so the emitted asset carries no proportions and no identity. If '
            'recognisable_likeness_permitted is false, that is consistent with use '
            'here; it is NOT a licence to use the scan mesh itself.' % rs['cutoff_wavelength_mm'],
        },
        'software': SOFTWARE_LICENCES,
        'derivation': {
            'images': sfm['images_found'],
            'images_registered': sfm['images_registered'],
            'scale': {
                'kind': sc['kind'],
                'declared_value': sc['declared_value'],
                'source': sc['declared_source'],
                'note': 'DECLARED, never inferred — SfM solves only up to a similarity',
            },
            'dense_method': dn['method'],
            'patchmatch_available': dn['patchmatch_available'],
            'align_icp_rms_mm': 1e3 * al['icp_rms_m'],
            'align_icp_rms_is': al['icp_rms_is'],
            'align_icp_rms_trimmed_mm': 1e3 * al['icp_rms_trimmed_m'],
            'coverage': rs['shrinkwrap']['coverage'],
            'residual_rms_mm': rs['residual_mm']['rms'],
            'proportion_leakage_measured': rs['proportion_leakage']['fraction_surviving_into_residual'],
            'lowpass_converged': rs['lowpass']['calibration']['converged'],
        },
        'consumer': 'geom/relief_subdiv.py — offset_m is (V,3) metres, indexed by the '
        'vertex order of geom.mesh_skeletons._subdivide(cage_v, cage_f, %d) '
        'for character %r. relief_subdiv.subdivide uses a DIFFERENT vertex '
        'order over the same surface; reindex with to_relief_subdiv_index '
        'before consuming there.' % (rs['subdiv_level'], al['target_character']),
        'index_permutation': perm_doc,
    }
    _atomic_json(os.path.join(out_dir, 'PROVENANCE.json'), prov)

    doc = {
        'schema': SCHEMA,
        'stage': 'emit',
        'status': 'ok',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'offsets_npz': out,
        'vertices': int(len(resid)),
        'covered_vertices': int(cov.sum()),
        'provenance': os.path.join(out_dir, 'PROVENANCE.json'),
    }
    _atomic_json(_stage_path(out_dir, 'emit'), doc)
    _log(verbose, 'emit: %s (%d verts, %d covered)' % (out, len(resid), int(cov.sum())))
    return doc
