# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""phenotype.py — lock a character's declared build into the parametric body (2026-08-04).

The character bible DECLARES Abel: 12 years old, 1.52m. The fitter should not be allowed
to "discover" a different body — monocular keypoints cannot tell a short adult from a
child at the same image scale, so left free, the optimiser will happily explain a boy
with a shrunken man. Declared phenotype is therefore an INPUT, held fixed, never fitted.

Anny's phenotype axes are normalised 0..1 (MakeHuman convention), and its Anthropometry
module MEASURES a built mesh rather than inverting measurements. So the lock is a
calibration:

  age     MakeHuman maps 0.0->1y, 0.5->25y linearly (then 25..90 over the upper half),
          so 12y = (12-1)/24 * 0.5 ~ 0.229. Used as the seed, kept fixed.
  height  binary-searched until Anthropometry reports the declared stature, because the
          height parameter is a relative slider whose metre value also depends on age.

calibrate() returns the phenotype kwargs plus the MEASURED height/BMI of the result, so
the lock is verified, not assumed.
"""

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CACHE = {}


def age_to_param(age_years):
    a = float(age_years)
    if a <= 25.0:
        return max(0.0, (a - 1.0) / 24.0 * 0.5)
    return min(1.0, 0.5 + (a - 25.0) / 65.0 * 0.5)


def calibrate(model, age_years, height_m, gender=None, iters=18, log=print):
    """Find phenotype kwargs hitting the declared height at the declared age."""
    import torch
    from anny import Anthropometry

    key = (round(float(age_years), 2), round(float(height_m), 3), gender)
    if key in _CACHE:
        return _CACHE[key]
    anth = Anthropometry(model)

    base = {'age': age_to_param(age_years)}
    if gender is not None:
        base['gender'] = float(gender)

    def measure(hp):
        kw = dict(base)
        kw['height'] = float(hp)
        with torch.no_grad():
            out = model(phenotype_kwargs=kw)
            # height() measures the phenotyped rest mesh it is handed
            h = anth.height(out['rest_vertices'])
        return float(h if not hasattr(h, 'item') else h.item()), kw

    lo, hi = 0.0, 1.0
    h_lo, _ = measure(lo)
    h_hi, _ = measure(hi)
    if not (min(h_lo, h_hi) - 0.05 <= height_m <= max(h_lo, h_hi) + 0.05):
        log(
            '  phenotype: %.2fm outside reachable [%.2f, %.2f] at age %s — clamping'
            % (height_m, min(h_lo, h_hi), max(h_lo, h_hi), age_years)
        )
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        h, kw = measure(mid)
        if (h < height_m) == (h_lo < h_hi):
            lo = mid
        else:
            hi = mid
    h, kw = measure((lo + hi) / 2.0)
    out = {
        'phenotype_kwargs': kw,
        'measured_height_m': round(h, 4),
        'target_height_m': float(height_m),
        'age_years': float(age_years),
    }
    log(
        '  phenotype lock: age %.0fy -> %.3f, height param %.4f -> measured %.3fm '
        '(target %.2fm)' % (age_years, kw['age'], kw['height'], h, height_m)
    )
    _CACHE[key] = out
    return out


def target_for_char(char_asset_id):
    """Declared build from the manifest character entry, or None."""
    from . import manifest

    man = manifest.Manifest()
    a = man.get(char_asset_id)
    t = (((a or {}).get('mesh') or {}).get('phenotype_target')) or None
    return t


# =====================================================================================
# THE REGISTERED BODY (2026-09-02, session S02).
#
# THE SPLIT-BRAIN THIS CLOSES. calibrate() above solves ONE axis — height, for a declared
# age — and returns a phenotype of three numbers. Everything downstream of it (anny_fit,
# anny_animate, body_grid) built its body from exactly that, so the registry's body —
# the one that was issued, hashed, gated and shipped — never reached a fit or a control
# plate. Measured before this file changed: 9 of 44 abel fits and 6 of 43 cornelis fits
# carried any phenotype at all, and the ones that did carried gender 1.0 (female in
# anny's convention, where 0.0 is male) and height 0.9702, against the registered abel's
# gender 0.0 / height 0.8873. The 41-frame VACE track carried the same wrong body.
#
# A REGISTERED BODY IS FOUR THINGS, not one:
#   phenotype       the macro axes                    -> phenotype_kwargs
#   local_changes   the ~30 MakeHuman local morphs    -> local_changes_kwargs
#   bone_scales     per-bone scale, INCLUDING the recorded phalanx correction
#                                                     -> pose_parameters (scale block)
#   anatomy_layer   a rest-space vertex layer (declash, relief) applied AFTER the
#                   forward pass; see ANATOMY_LAYER_NOTE — it is not carried through a
#                   posed forward and this module says so rather than pretending.
#
# Two of those four are invisible to the bare anny model: local morphs are silently
# ignored unless the model was built with local_changes='all'. So a registry body is
# always driven through geom.mesh_skeletons._model(), the same model that built the
# cage whose hash is on record — which is what lets build_registry_cage() reproduce
# cage_vert_sha256 exactly, and why a mismatch is refused rather than warned about.
# =====================================================================================

ANATOMY_LAYER_NOTE = (
    'anatomy_layer is a rest-space vertex displacement applied after the model forward '
    'pass (geom.mesh_skeletons._apply_anatomy). It is verified on the rest cage by '
    'build_registry_cage() and is NOT re-applied to posed frames, because its relief '
    'layer is expressed in the REST bone frame and would be applied in the wrong frame '
    'once the body is posed. Measured 2026-09-02 on the rest cage: abel max vertex '
    'displacement 0.68 mm over 2548/13718 verts, cornelis 21.26 mm over 150/13718 '
    '(abs_definition). Both are below the depth-render pixel at the scales these plates '
    'are drawn at; the omission is recorded here rather than hidden.'
)

# char_id (the hex the output tree is keyed by) and asset name -> registry name.
# The link is manifest assets.<asset>.mesh.summary.char_id; this table is the cached
# answer and resolve_body_name() falls back to reading the manifest for anything not in
# it, so a new character needs no edit here.
BODY_ALIASES = {
    'c3345deb5bde': 'abel',
    'char_abel': 'abel',
    'abel': 'abel',
    '0015c8a3f2e3': 'cornelis',
    'char_cornelis': 'cornelis',
    'cornelis': 'cornelis',
}


def resolve_body_name(ident):
    """char_id / asset name / registry name -> registry name, or None."""
    if not ident:
        return None
    s = str(ident)
    if s in BODY_ALIASES:
        return BODY_ALIASES[s]
    try:
        from zyg_workflows.geom import mesh_skeletons as MS

        reg = MS._registry()
        for section in ('originals', 'derived'):
            if s in reg.get(section, {}):
                return s
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('registry name lookup failed, trying the char_id match: %s', _exc)
    # last resort: the manifest links an asset to a char_id, and a registry entry
    # records char_id in its params
    try:
        from zyg_workflows.geom import mesh_skeletons as MS

        reg = MS._registry()
        for section in ('originals', 'derived'):
            for nm, rec in reg.get(section, {}).items():
                if str((rec.get('params') or {}).get('char_id')) == s:
                    return nm
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('registry char_id lookup failed, the body name stays unresolved: %s', _exc)
    return None


def _registry_record(name):
    from zyg_workflows.geom import mesh_skeletons as MS

    reg = MS._registry()
    for section in ('originals', 'derived'):
        if name in reg.get(section, {}):
            return section, reg[section][name]
    known = sorted(list(reg.get('originals', {})) + list(reg.get('derived', {})))
    raise ValueError('no registered body %r. Known: %s' % (name, ', '.join(known)))


def build_registry_cage(name, verify_hash=True, log=print):
    """Rebuild a registered body's REST cage and check it against the recorded hash.

    Same sequence as geom.anthro.gates.Subject.from_registry — _build_mesh(params=) then
    _apply_anatomy — deliberately, so the body a fit uses is byte-for-byte the body the
    gates adjudicate. Returns (vertices float64, faces, spec). Raises on a hash mismatch:
    a fit against a body that is not the one that shipped is worse than no fit.
    """
    import numpy as np
    from zyg_workflows.geom import mesh_skeletons as MS

    section, rec = _registry_record(name)
    p = rec['params']
    phen = dict(p['phenotype'])
    locs = p.get('local_changes') or None
    bones = p.get('bone_scales') or None
    anat = p.get('anatomy_layer') or None
    v, faces, applied = MS._build_mesh(phen, locs, bones, params=p)
    v = MS._apply_anatomy(v, faces, anat, phenotype=phen, local_changes=locs, bone_scales=bones, params=p).astype(
        np.float64
    )
    expect = p.get('cage_vert_sha256')
    got = MS._vert_sha(v)
    if verify_hash and expect and got != expect:
        raise ValueError(
            'rebuilt cage for %r hashes %s but the registry recorded %s — the recipe no '
            'longer reproduces the issued mesh. Refusing to fit against a body that is '
            'not the one that shipped.' % (name, got[:16], expect[:16])
        )
    # the EFFECTIVE scales are what the forward pass must carry: the recorded phalanx
    # correction is folded in here exactly as _build_mesh folds it in, so a posed
    # forward driven from this spec has the registered body's hands.
    from zyg_workflows.geom.anthro import hand_correction as HC

    eff_scales, hc = HC.effective_scales(phen, locs, bones, p)
    spec = {
        'source': 'registry',
        'name': name,
        'section': section,
        'phenotype_kwargs': phen,
        'local_changes': dict(locs or {}),
        'bone_scales_recorded': dict(bones or {}),
        'bone_scales_effective': dict(eff_scales or {}),
        'anatomy_layer': dict(anat or {}),
        'hand_correction_version': (hc or {}).get('version') if isinstance(hc, dict) else None,
        'cage_vert_sha256_recorded': expect,
        'cage_vert_sha256_rebuilt': got,
        'hash_verified': bool(expect) and got == expect,
        'char_id': p.get('char_id'),
        'anatomy_layer_note': ANATOMY_LAYER_NOTE,
    }
    if log:
        log(
            '  body %r from registry/%s: cage sha %s %s | phenotype %s | %d local '
            'morphs | %d effective bone scales'
            % (
                name,
                section,
                got[:16],
                'VERIFIED against the recorded hash' if spec['hash_verified'] else '(NOT verified: no hash on record)',
                {k: round(float(x), 4) for k, x in phen.items()},
                len(spec['local_changes']),
                len(spec['bone_scales_effective']),
            )
        )
    return v, faces, spec


def registry_body(name, verify_hash=True, log=print):
    """The spec only (the cage is rebuilt to check the hash, then dropped)."""
    _v, _f, spec = build_registry_cage(name, verify_hash=verify_hash, log=log)
    return spec


def legacy_spec(phenotype_kwargs, why='--legacy-phenotype'):
    """Wrap the old phenotype-only path in the same shape, so call sites have one type."""
    return {
        'source': 'legacy_phenotype',
        'name': None,
        'phenotype_kwargs': dict(phenotype_kwargs or {}),
        'local_changes': {},
        'bone_scales_recorded': {},
        'bone_scales_effective': {},
        'anatomy_layer': {},
        'hash_verified': False,
        'why': why,
    }


def body_model(spec):
    """The model a spec must be driven through.

    A registry body goes through geom.mesh_skeletons._model() — built with
    local_changes='all'. On the bare model every local morph is silently ignored, which
    for cornelis (30 local morphs) would build a body that is not his and say nothing.
    """
    if (spec or {}).get('source') == 'registry':
        from zyg_workflows.geom import mesh_skeletons as MS

        return MS._model()
    from .anny_fit import _model

    return _model()


_SCALE44_CACHE = {}


def bone_scale_matrix(spec, model):
    """The (1,N,4,4) bone-SCALE block for a spec, memoised per (model, scales).

    Built once per fit rather than once per optimiser step: _scale44 walks all 163 bone
    names for every key, and the fit calls the forward pass 650 times.
    """
    scales = (spec or {}).get('bone_scales_effective') or None
    if not scales:
        return None
    key = (
        id(model),
        tuple(sorted((k, tuple(v) if isinstance(v, (list, tuple)) else (float(v),) * 3) for k, v in scales.items())),
    )
    if key not in _SCALE44_CACHE:
        from zyg_workflows.geom import mesh_skeletons as MS

        S, _applied = MS._scale44(model, scales)
        _SCALE44_CACHE[key] = S
    return _SCALE44_CACHE[key]


def forward_kwargs(spec, pose_aa=None, model=None, scale44=None):
    """kwargs for one model(...) call: phenotype, local morphs, and the pose matrix with
    the body's bone SCALES folded in.

    anny takes one (1,N,4,4) `pose_parameters` block per bone, and both the pose rotation
    and the bone scale want it. They compose: M = R @ S — scale the bone in its own local
    frame, then rotate it. The two degenerate cases are the proof this is the right
    composition rather than a choice: with no pose (R = I) M is exactly the scale matrix
    _build_mesh passes, so a rest forward reproduces the registered cage bit-for-bit
    (verified: max vertex delta 0.000e+00 m on both abel and cornelis); with no bone
    scales (S = I) M is exactly the rotation the fitter has always passed, so the legacy
    path is unchanged.

    The composition is written with cat rather than an in-place slice assignment because
    `pose_aa` is the fit's free parameter and must stay differentiable.
    """
    import torch
    from .anny_fit import _pose44

    spec = spec or {}
    kw = {'phenotype_kwargs': dict(spec.get('phenotype_kwargs') or {})}
    if spec.get('local_changes'):
        kw['local_changes_kwargs'] = dict(spec['local_changes'])
    if scale44 is None:
        m = model if model is not None else body_model(spec)
        scale44 = bone_scale_matrix(spec, m)
    S = scale44
    if pose_aa is None:
        if S is not None:
            kw['pose_parameters'] = S
        return kw
    R = _pose44(pose_aa)  # (1,N,4,4) float64
    if S is None:
        kw['pose_parameters'] = R
        return kw
    RS = R[..., :3, :3] @ S[..., :3, :3].to(R.dtype)
    top = torch.cat([RS, R[..., :3, 3:4]], dim=-1)
    kw['pose_parameters'] = torch.cat([top, R[..., 3:4, :]], dim=-2)
    return kw


def describe(spec):
    """One line naming the body actually in use — for logs and reports."""
    spec = spec or {}
    ph = {k: round(float(v), 4) for k, v in (spec.get('phenotype_kwargs') or {}).items()}
    if spec.get('source') == 'registry':
        return 'registry:%s sha %s %s phenotype %s locals %d bone_scales %d' % (
            spec.get('name'),
            (spec.get('cage_vert_sha256_rebuilt') or '')[:12],
            'HASH-OK' if spec.get('hash_verified') else 'HASH-UNVERIFIED',
            ph,
            len(spec.get('local_changes') or {}),
            len(spec.get('bone_scales_effective') or {}),
        )
    return 'legacy_phenotype phenotype %s (no locals, no bone scales, no anatomy)' % ph


def spec_for(body=None, char_asset=None, model=None, verify_hash=True, log=print):
    """The one resolver every caller uses.

    `body` (a registry name / char_id / asset name) wins; otherwise the declared-build
    calibration of `char_asset`; otherwise None, meaning the anny default body.
    """
    if body:
        name = resolve_body_name(body)
        if not name:
            raise ValueError('%r does not resolve to a registered body' % body)
        return registry_body(name, verify_hash=verify_hash, log=log)
    if char_asset:
        tgt = target_for_char(char_asset)
        if tgt:
            m = model
            if m is None:
                from .anny_fit import _model

                m = _model()
            cal = calibrate(m, tgt['age_years'], tgt['height_m'], tgt.get('gender'), log=log or (lambda *_: None))
            s = legacy_spec(cal['phenotype_kwargs'], why='declared build of %s' % char_asset)
            s['measured_height_m'] = cal.get('measured_height_m')
            s['target_height_m'] = cal.get('target_height_m')
            return s
    return None
