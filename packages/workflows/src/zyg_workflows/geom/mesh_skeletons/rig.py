# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anny model loading, the rig cache and the cage build: _model(),
_rig_for(), _build_mesh(), morph support and the smoothstep band.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 426-731).
"""

import collections
import hashlib

import numpy as np

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_MODEL = None


def _bone_names(m):
    """anny exposes bone names as `bone_labels` on the local-changes build and `bones`
    on the default build — accept either, fail loudly on neither."""
    for attr in ('bone_labels', 'bones'):
        if hasattr(m, attr):
            return list(getattr(m, attr))
    raise AttributeError('anny model exposes neither bone_labels nor bones')


def _model():
    """One shared full-body model, built WITH the complete local-changes vocabulary."""
    global _MODEL
    if _MODEL is None:
        from anny import create_fullbody_model

        try:
            _MODEL = create_fullbody_model(local_changes='all')
        except Exception as e:  # noqa: BLE001
            # the vocabulary is an enhancement, not a dependency — the originals must
            # still build if the 'all' pack misbehaves. But NEVER silently: on the
            # bare model every local morph is silently ignored and issued bodies
            # would be wrong.
            _zyg_log.info(
                'WARNING: local_changes="all" model failed (%s) — FALLING BACK to '
                'the bare model; ALL local morphs will be ignored' % e
            )
            _MODEL = create_fullbody_model()
        # PATELLAR TRACKING, geom/patella_skin.py, ZYG_PATELLA_TRACKING, DEFAULT OFF.
        # Deferred import: patella_skin imports this module at module level.
        #
        # It redirects the patella patch's femur skinning weight to the shank so the
        # kneecap rides the tibial tuberosity, which is the anatomy (an inextensible
        # ligament) and which takes t5_patellar_ligament's drift from 10.2%/27.3%
        # (male/female) to 0.78%/1.13% at every tested angle on all five bodies. It is
        # free on the REST cage — weights do not enter _vert_sha, no character carries a
        # bone_scale, and the module's own verify_cage_unchanged() reproduces both
        # registry hashes with it on — which is why it can be wired in here at all.
        #
        # IT IS OFF BY DEFAULT FOR TWO REASONS, and neither is that the fix is wrong:
        #   1. SCOPE. It is a property of the shared model, not of a character, so
        #      turning it on changes POSED geometry for derived/abel and derived/cornelis
        #      too. This wave's brief is that those two must gate exactly as they do
        #      today; a flag that silently re-poses them does not qualify.
        #   2. The module's own MEASURED_COST says the trade is two-sided at the flexion
        #      angles our fitted pose libraries actually contain: at abel's maximum knee
        #      flexion (26 deg) it removes 9.9 mm of ligament error while moving 52.4 mm
        #      of anterior-knee skin, because geom.form.regions' `patella` patch is about
        #      twice the height of a patella and its suprapatellar half comes along.
        # The named fix with no cost is to tighten that patch. Until then this stays a
        # deliberate switch: ZYG_PATELLA_TRACKING=1.
        try:
            from zyg_workflows.geom import patella_skin as PS

            if PS.enabled():
                PS.apply_patellar_tracking(_MODEL)
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(
                'WARNING: ZYG_PATELLA_TRACKING is set but patellar tracking could not '
                'be applied (%s) — the model is UNCHANGED and every knee gate below '
                'measures the uncorrected rig' % e
            )
    return _MODEL


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _scale44(model, bone_scales):
    """(1,N,4,4) float64 identity transforms carrying per-bone SCALE.

    Substring match, case-insensitive, on anny's 163 rig bone names — which are
    MakeHuman/Blender names, not anatomical English: the leg is `upperleg01.L`,
    `upperleg02.L`, `lowerleg01.L`, `lowerleg02.L`, `foot.L`. So 'upperleg' hits both
    thighs, 'upperleg01.L' one segment of one side. Scale goes into the 3x3 block and the
    kinematic chain propagates it to children, which is what makes a longer upper leg also
    place the shin correctly.

    A KEY THAT MATCHES NO BONE IS AN ERROR, not a no-op (fixed 2026-08-05). The docs used
    to teach `--bone-scale thigh=1.15`; anny has no bone containing 'thigh', so the knob
    resolved to zero bones and was dropped in silence. `derive x --bone-scale
    thigh=1.15,head=0.95` then issued a body with only the head scaled, recorded the
    request verbatim in params.json, hashed it, gated it, and reported success — the
    partial match is what makes it convincing. Raising is the only honest answer: the
    operator asked for a body this is not.
    """
    import torch

    raw = [str(n) for n in _bone_names(model)]
    names = [n.lower() for n in raw]
    n = len(names)
    T = torch.eye(4, dtype=torch.float64).repeat(n, 1, 1)
    applied = {}
    for key, s in (bone_scales or {}).items():
        sv = [float(s)] * 3 if not isinstance(s, (list, tuple)) else [float(x) for x in s]
        for i, nm in enumerate(names):
            if key.lower() in nm:
                T[i, 0, 0] *= sv[0]
                T[i, 1, 1] *= sv[1]
                T[i, 2, 2] *= sv[2]
                applied.setdefault(key, []).append(nm)
        if key not in applied:
            raise ValueError(
                'bone scale %r matches none of the %d bones on this rig, so it would '
                'have been silently ignored and the issued body would not be the one '
                'that was asked for. %sThe full roster is params.json -> '
                'adjustable.bone_scale; the leg is upperleg01/upperleg02/lowerleg01/'
                'lowerleg02, not "thigh"/"shin".' % (key, n, _bone_hint(key, raw))
            )
    return T[None], applied


def _bone_stems(names):
    """The distinct vocabulary behind the 163 bone names: side suffixes (.L/.R) and
    segment numbers stripped, so 'upperleg01.L'..'upperleg02.R' collapse to 'upperleg'."""
    seen = []
    for nm in names:
        stem = str(nm).split('.')[0].rstrip('0123456789') or str(nm)
        if stem.lower() not in [s.lower() for s in seen]:
            seen.append(stem)
    return seen


def _bone_hint(key, names):
    """'Did you mean' for a bone key that matched nothing.

    A near-miss list is only offered when it is actually near — a fuzzy suggestion of
    'spine05' for 'shin' is worse than no suggestion. Otherwise the whole stem vocabulary
    is printed, which is short, always correct, and is the thing the operator needs.
    """
    import difflib

    k = str(key).lower().strip()
    stems = _bone_stems(names)
    near = difflib.get_close_matches(k.split('.')[0], [s.lower() for s in stems], n=4, cutoff=0.72)
    if near:
        return 'Did you mean: %s? ' % ', '.join(near)
    return 'The %d bone-name stems are: %s. ' % (len(stems), ', '.join(stems))


_RIG_CACHE = collections.OrderedDict()
_RIG_CACHE_MAX = 4


def _rig_key(v):
    return hashlib.sha256(np.ascontiguousarray(np.asarray(v)).tobytes()).hexdigest()


def _rig_for(v, phenotype=None, local_changes=None, bone_scales=None, params=None):
    """The bone frame + skinning weights belonging to a cage array.

    geom/relief.py anchors landmarks to bone positions, which depend on the recipe. The
    ~two dozen callers that do `_build_mesh(...)` then `_apply_anatomy(...)` hold the
    recipe but do not pass it, and editing all of them to thread a phenotype through
    would be a large diff across files this wave does not own. So _build_mesh RECORDS the
    rig for the exact array it just produced, keyed by the bytes of that array, and this
    looks it up — no second forward pass, no edit to any caller, and the rig cannot be
    matched to the wrong body because the key IS the body.

    Falls back to an explicit phenotype (one extra forward pass) and RAISES if it has
    neither. A wrong skeleton would sculpt a clavicle ridge onto a trapezius and nothing
    downstream would notice.
    """
    key = _rig_key(v)
    hit = _RIG_CACHE.get(key)
    if hit is not None:
        _RIG_CACHE.move_to_end(key)
        return hit
    if phenotype is None:
        raise ValueError(
            'no rig is known for this cage: it did not come from _build_mesh in this '
            'process and no phenotype= was passed, so geom/relief.py cannot be anchored. '
            'Pass phenotype= (and local_changes=/bone_scales=) to _apply_anatomy, or '
            'build the mesh with _build_mesh first.'
        )
    from zyg_workflows.geom import relief as RELIEF
    from zyg_workflows.geom.anthro import hand_correction as HC

    # The FALLBACK path builds its own skeleton, so it has to apply the same phalanx
    # correction _build_mesh applied to the cage it is being asked about. Without this
    # the relief layer would anchor landmarks to an uncorrected skeleton on a corrected
    # body — a bone frame that belongs to no mesh in the process.
    bone_scales, _hc = HC.effective_scales(phenotype, local_changes, bone_scales, params)
    _vv, _ff, bones, weights = RELIEF.bones_for(phenotype, local_changes, bone_scales)
    return _rig_record(v, phenotype, local_changes, bone_scales, bones, weights)


def _rig_record(v, phenotype, local_changes, bone_scales, bones, weights):
    rec = {
        'phenotype': dict(phenotype or {}),
        'local_changes': dict(local_changes or {}),
        'bone_scales': dict(bone_scales or {}),
        'bones': bones,
        'weights': weights,
        'bone_names': [str(n) for n in _bone_names(_model())],
    }
    _RIG_CACHE[_rig_key(v)] = rec
    while len(_RIG_CACHE) > _RIG_CACHE_MAX:
        _RIG_CACHE.popitem(last=False)
    return rec


def _build_mesh(phenotype, local_changes=None, bone_scales=None, params=None, apply_hand_correction=True):
    """vertices (V,3 float32), faces (F,4 int) for one parameter recipe.

    THE PHALANX CORRECTION IS APPLIED HERE, not at derive(), and that is deliberate.
    Roughly sixty call sites build a mesh; the ones that build a REGISTERED CHARACTER
    pass bone_scales out of params.json, but the ones that build a reference or
    calibration body pass nothing. Applying the correction only at issue time would give
    those two populations different hands: the HOUSE bands in geom.form would be
    calibrated on uncorrected fingers while every shipped body had corrected ones. Doing
    it at the single choke point every build goes through is what keeps one body in the
    process at a time.

    It cancels out of the difference-of-two-builds pattern that morph support and
    landmark placement use (`_build_mesh(phen, None)` vs `_build_mesh(phen, {label:1})`),
    because both sides get the same correction.

    `params` lets a REGISTERED body reuse the correction recorded in its params.json
    instead of re-solving, which is what makes a rebuild reproduce the issued hash. A
    body with no `hand_correction` key predates the fix and rebuilds UNCORRECTED.
    """
    import torch

    m = _model()
    kw = {'phenotype_kwargs': dict(phenotype)}
    if local_changes:
        kw['local_changes_kwargs'] = dict(local_changes)
    applied = {}
    if apply_hand_correction:
        from zyg_workflows.geom.anthro import hand_correction as HC

        bone_scales, _hc = HC.effective_scales(phenotype, local_changes, bone_scales, params)
    if bone_scales:
        pose, applied = _scale44(m, bone_scales)
        kw['pose_parameters'] = pose
    with torch.no_grad():
        out = m(**kw)
    v = out['vertices'][0].to(torch.float32).numpy()
    faces = m.faces.numpy() if hasattr(m.faces, 'numpy') else np.asarray(m.faces)
    try:
        from zyg_workflows.geom import relief as RELIEF

        _rig_record(v, phenotype, local_changes, bone_scales, RELIEF.bone_frame(m, out), RELIEF.bone_weights(m))
    except Exception as e:  # noqa: BLE001
        # the rig is an INPUT to one optional layer; a body that asks for no relief must
        # still build. Never silently, though: the failure is printed and _rig_for will
        # raise for anyone who actually needed it.
        _zyg_log.info(
            'WARNING: could not record the bone frame for this build (%s) — '
            'anatomy_layer["bony_relief"] will raise rather than guess' % e
        )
    return v, faces, applied


_MORPH_SUPPORT = {}


def _morph_support(label, thresh=0.0003):
    """Vertex support of one MakeHuman target (index set + weights).

    A morph target is a fixed per-vertex displacement table, so its support is
    topology-fixed — measured once per process at a fixed reference phenotype. These
    supports are what anchor our sculpted layer to MakeHuman's own anatomical regions
    instead of inventing placements.
    """
    key = (label, thresh)
    if key not in _MORPH_SUPPORT:
        ref = {'gender': 0.0, 'age': 0.5, 'muscle': 0.5, 'weight': 0.5, 'height': 0.5, 'proportions': 0.5}
        v0, _, _ = _build_mesh(ref, None)
        v1, _, _ = _build_mesh(ref, {label: 1.0})
        d = np.linalg.norm(v1.astype(np.float64) - v0.astype(np.float64), axis=1)
        idx = np.nonzero(d > thresh)[0]
        if not len(idx):
            raise RuntimeError(
                'morph target %r has EMPTY support — the local-changes vocabulary is '
                'not loaded (did _model() fall back to the bare model?)' % label
            )
        w = (d[idx] / max(d[idx].max(), 1e-9)) ** 0.5
        _MORPH_SUPPORT[key] = (idx, w)
    return _MORPH_SUPPORT[key]


def _vertex_normals(v, faces):
    n = np.zeros((len(v), 3), np.float64)
    e1 = v[faces[:, 1]].astype(np.float64) - v[faces[:, 0]]
    e2 = v[faces[:, 2]].astype(np.float64) - v[faces[:, 0]]
    fn = np.cross(e1, e2)
    for k in range(4):
        np.add.at(n, faces[:, k], fn)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return n


def _band(t, a, b, e=0.10):
    """smoothstep band mask: 0 outside [a,b], 1 inside, soft e-wide edges."""
    up = np.clip((t - a) / e, 0, 1)
    dn = np.clip((b - t) / e, 0, 1)
    return (up * up * (3 - 2 * up)) * (dn * dn * (3 - 2 * dn))
