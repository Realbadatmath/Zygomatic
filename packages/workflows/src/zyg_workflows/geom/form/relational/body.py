# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""relational/body.py — gluteal vs trochanteric, angle kappa, knee alignment, pelvis tilt and the whole-body call.

Moved verbatim out of relational.py (lines 501-1049).
"""

from zyg_workflows.geom.form.relational.constants import (
    BAND_HALF_FRAC,
    EYE_AXIS_AGREEMENT_MAX_DEG,
    EYE_SIMILARITY_MAX_ANISOTROPY,
    IG,
    LMK,
    ME,
    MS,
    SCHEMA,
    SIGN_CONVENTION,
    _CACHE,
    math,
    np,
    time,
)
from zyg_workflows.geom.form.relational.spine import (
    _context,
    _frame,
    _lm_frac,
    _unresolved,
    lumbar_curvature,
    posterior_midline_chain,
    segment_tilt_opposition,
)


# ---------------------------------------------------------------------------------
# (2) THE BUTT IS NEVER WIDER THAN THE HIPS
# ---------------------------------------------------------------------------------
def gluteal_vs_trochanteric(v, faces, landmarks=None, phenotype=None, local_changes=None):
    """Maximum coronal width over the gluteal band, against the trochanteric band.

    BAND DEFINITIONS, both resolved per mesh and both from geom/anthro/landmarks.py:
      trochanteric = resolved trochanterion +/- BAND_HALF_FRAC of stature. The trochanterion
        height comes from anny's own femoral-head joint centre and only its lateral
        projection is read off the surface, because the greater trochanter has no surface
        signature here (landmarks.py measured the lateral profile through the pelvis to be
        monotone).
      gluteal = resolved buttock landmark +/- BAND_HALF_FRAC. ISO buttock height is the
        height of the maximum posterior protrusion, which is the gluteal mass itself.

    The width is measure.py's torso-scoped x-extent scan, so the arms are excluded by
    topology and skinning rather than by an x window — over 0.52-0.70 of stature the
    unrestricted coronal silhouette of this A-posed cage is the forearm.

    TWO THINGS THIS RECORD SAYS THAT THE PASS/FAIL DOES NOT.
      * ON THIS CAGE THE BUTTOCK LANDMARK SITS ABOVE THE TROCHANTERION on all four issued
        characters (+0.0138 to +0.0196 of stature), which is the REVERSE of the ANSUR
        order, and the torso x-extent falls monotonically from just above the crotch to
        0.58 of stature (measured, and independently recorded in measure.py's hip_breadth
        note). So the inequality is partly structural here rather than a discovery about
        the body.
      * WHICH IS WHY THE FALSIFICATION SWEEP EXISTS. Driving buttocks-volume-incr past its
        design cap closes the margin monotonically: measured on the anny neutral, +10.78 mm
        at 0.0, +7.19 mm at +0.8 (the cap), +1.04 mm at +2.0, and at +4.0 the buttock
        landmark passes BELOW the trochanterion and the bands overlap, at which point this
        function refuses instead of comparing them. The gate has discriminating power; it
        simply does not fire inside the design range, and that is a measurement rather than
        an assumption. Run falsification_sweep() to reproduce it.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    but, why_b = _lm_frac(ctx, 'buttock')
    tro_l, why_l = _lm_frac(ctx, 'trochanterion_l')
    tro_r, why_r = _lm_frac(ctx, 'trochanterion_r')
    if but is None:
        return _unresolved('the gluteal band needs the buttock landmark: ' + why_b)
    if tro_l is None or tro_r is None:
        return _unresolved('the trochanteric band needs both trochanterions: %s' % (why_l or why_r))
    # Both sides, averaged, so a body whose two trochanterions disagree does not silently
    # get whichever side this function happened to name.
    tro = 0.5 * (tro_l + tro_r)
    sep = but - tro
    if abs(sep) < 2.0 * BAND_HALF_FRAC:
        return _unresolved(
            'the gluteal and trochanteric bands overlap: the buttock landmark is %.4f of '
            'stature from the trochanterion and each band is +/-%.4f wide, so the two '
            '"maxima" would be taken over shared planes and the comparison would be '
            'between a quantity and itself' % (sep, BAND_HALF_FRAC),
            buttock_frac_stature=but,
            trochanterion_frac_stature=tro,
            separation_frac_stature=sep,
            band_half_frac_stature=BAND_HALF_FRAC,
        )

    zmin, H = ctx['zmin'], ctx['H']
    out = {
        'resolved': True,
        'buttock_frac_stature': but,
        'trochanterion_frac_stature': tro,
        'trochanterion_frac_stature_lr': [tro_l, tro_r],
        'separation_frac_stature': sep,
        'band_half_frac_stature': BAND_HALF_FRAC,
        'buttock_above_trochanterion': bool(sep > 0),
    }
    for name, centre in (('gluteal', but), ('trochanteric', tro)):
        r = ME._extent_scan(
            v=ctx['v'],
            faces=ctx['faces'],
            zlo=zmin + (centre - BAND_HALF_FRAC) * H,
            zhi=zmin + (centre + BAND_HALF_FRAC) * H,
            step=ME.SCAN_STEP_FRAC * H,
            scope='torso',
            axis='x',
        )
        if r is None:
            return _unresolved(
                'no plane in the %s band yielded a torso cross-section, so there is no coronal width to compare' % name,
                band=[centre - BAND_HALF_FRAC, centre + BAND_HALF_FRAC],
            )
        out[name + '_width_mm'] = float(r['value_mm'])
        out[name + '_width_at_frac_stature'] = float((r['z'] - zmin) / H)
        out[name + '_planes_usable'] = int(r['n_planes_usable'])
        out[name + '_at_band_endpoint'] = bool(r['winner_index_among_usable'] in (0, r['n_planes_usable'] - 1))
    out['margin_mm'] = out['trochanteric_width_mm'] - out['gluteal_width_mm']
    out['margin_frac_stature'] = out['margin_mm'] / (H * 1000.0)
    out['passes'] = bool(out['margin_mm'] > 0.0)
    out['convention'] = (
        'maximum x-extent of the TORSO cross-section, measure.py '
        '_extent_scan at %g of stature per plane' % ME.SCAN_STEP_FRAC
    )

    # Whether the pass was informative. On this cage the coronal width falls monotonically
    # from just above the crotch to 0.58 of stature (measured here per body, and recorded
    # independently in measure.py's hip_breadth note), and with the buttock landmark ABOVE
    # the trochanterion that makes the inequality a consequence of the profile rather than
    # a statement about the gluteal mass. A caller who sees monotone=True and a fat margin
    # has learned nothing; monotone=False with a thin margin is the real signal.
    lo, hi = sorted((tro, but))
    span = ME._extent_scan(
        v=ctx['v'],
        faces=ctx['faces'],
        zlo=zmin + (lo - BAND_HALF_FRAC) * H,
        zhi=zmin + (hi + BAND_HALF_FRAC) * H,
        step=ME.SCAN_STEP_FRAC * H,
        scope='torso',
        axis='x',
    )
    prof = [w for _, w, _ in (span['profile'] if span else []) if w is not None]
    out['profile_between_bands_mm'] = prof
    out['profile_monotone_decreasing'] = bool(len(prof) > 1 and all(b <= a for a, b in zip(prof, prof[1:])))
    out['informative'] = not (out['profile_monotone_decreasing'] and out['buttock_above_trochanterion'])
    return out


# ---------------------------------------------------------------------------------
# (3) ANGLE KAPPA — the eyeball optical axes
# ---------------------------------------------------------------------------------
def _sphere_fit(P):
    """Algebraic sphere fit. |p|^2 = 2 c.p + (r^2 - |c|^2) is linear in (c, r^2 - |c|^2)."""
    A = np.hstack([2.0 * P, np.ones((len(P), 1))])
    sol, _, _, _ = np.linalg.lstsq(A, (P**2).sum(1), rcond=None)
    c = sol[:3]
    return c, float(np.sqrt(max(sol[3] + c @ c, 0.0)))


def _eye_components(v, faces):
    """{'left': idx, 'right': idx} for the two 72-vertex eyeball shells, or None.

    The shells are the ones integrity.py's inventory names 'eyeball (+x side)' and
    'eyeball (-x side)'; the labelling here is the same connected-component decomposition
    it runs, kept local only because the inventory does not publish vertex indices.
    """
    tris = IG.triangulate_quads(faces)
    ncomp, labels = IG._components(v, tris)
    sizes = np.bincount(labels, minlength=ncomp)
    want = next((s for s in IG.SHELL_SIGNATURES if s['name'] == 'eyeball'), None)
    if want is None:
        return None, 'integrity.SHELL_SIGNATURES carries no eyeball signature'
    eyes = [k for k in range(ncomp) if sizes[k] == want['vertices']]
    if len(eyes) != 2:
        return None, (
            'expected exactly two %d-vertex shells (integrity.py: %s); found %d'
            % (want['vertices'], want['provenance'], len(eyes))
        )
    out = {}
    for k in eyes:
        idx = np.nonzero(labels == k)[0]
        out['left' if v[idx, 0].mean() > 0 else 'right'] = idx
    if len(out) != 2:
        return None, 'both eyeball shells landed on the same side of the sagittal plane'
    return out, None


def _neutral_eye():
    """The +x eyeball of the anny neutral, as the reference shape the per-body similarity
    check is run against."""
    if 'neutral_eye' in _CACHE:
        return _CACHE['neutral_eye']
    v0, f0, _ = MS._build_mesh(LMK.REF_MALE, None)
    v0 = np.asarray(v0, np.float64)
    eyes, why = _eye_components(v0, f0)
    if eyes is None:
        raise RuntimeError('the anny neutral does not carry two eyeball shells: %s' % why)
    _CACHE['neutral_eye'] = (v0, f0, eyes['left'])
    return _CACHE['neutral_eye']


def _pole_axis(v, faces, idx, centre):
    """The eyeball shell's own construction axis, from its two antipodal pole patches.

    The shell is a quad sphere: 64 of its 72 vertices carry four faces and 8 carry three,
    and those 8 are the corners of the two pole quad patches (MEASURED: four of them within
    13 degrees of the anterior direction and four within 13 degrees of the posterior one).
    The axis is the anterior patch centroid minus the posterior one, so it is a chord of the
    shell rather than a single vertex and does not move with one vertex's tessellation
    error. 'antipodal_error_deg' is how far the two patches are from being opposite, which
    is the check that this is one axis and not two accidents.
    """
    sel = set(int(i) for i in idx)
    val = {}
    for q in np.asarray(faces):
        if int(q[0]) in sel:
            for a in q:
                val[int(a)] = val.get(int(a), 0) + 1
    poles = [i for i, k in val.items() if k != 4]
    if len(poles) != 8:
        return None, (
            'the eyeball shell has %d irregular-valence vertices, not the 8 that '
            'make its two pole patches, so it is not the quad sphere this reads '
            'an axis off' % len(poles)
        )
    ant = [p for p in poles if v[p, 1] < centre[1]]
    post = [p for p in poles if v[p, 1] >= centre[1]]
    if len(ant) != 4 or len(post) != 4:
        return None, ('the 8 pole vertices split %d anterior / %d posterior, not 4/4' % (len(ant), len(post)))
    ca = v[ant].mean(0) - centre
    cp = v[post].mean(0) - centre
    ax = ca - cp
    ax = ax / np.linalg.norm(ax)
    err = math.degrees(math.acos(float(np.clip(-(ca / np.linalg.norm(ca)) @ (cp / np.linalg.norm(cp)), -1.0, 1.0))))
    return {'axis': ax, 'antipodal_error_deg': err}, None


def eye_axes(v, faces):
    """Divergence between the two eyeballs' optical axes. Positive is OUTWARD bow.

    THE CORNEAL APEX DOES NOT EXIST ON THIS CAGE, and that has to be said before anything
    else, because the obvious construction — fit a sphere, take the vertex furthest from
    the centre, call it the cornea — RETURNS A VERTEX THAT DOES NOT POINT FORWARD ON ANY OF
    THE FOUR ISSUED CHARACTERS. Anterior is -y; the measured directions of that vertex are
    (+0.592, +0.748, +0.300) male, (+0.928, +0.005, +0.372) female, (-0.280, +0.952,
    +0.124) abel, (+0.578, +0.758, +0.303) cornelis — posterior or lateral, never anterior.
    MEASURED on the issued male's +x eye: fitted radius 18.2114 mm, per-vertex radius min
    17.6403 / max 18.5240 / sd 0.2261 mm, so the whole "protrusion" being maximised over is
    0.3126 mm. The radial profile against angle from anterior is FLAT and its minimum is the
    EQUATOR (mean radius 18.3556 mm over 0-20 degrees from anterior, 18.0399 over 60-90,
    18.3011 over 120-180): equal poles and a thin waist is the signature of a polyhedron
    inscribed in a sphere, not of a corneal bulge. This function therefore refuses the apex
    construction and reports the measurement that refutes it in 'corneal_apex'.

    WHAT IT USES INSTEAD is the shell's own construction axis (see _pole_axis), and it
    earns the right to read an orientation off it per body rather than by assertion: the
    least-squares affine map from the NEUTRAL eyeball shell to this one is decomposed, and
    the record carries its singular values, its anisotropy, its residual, and the angle
    between the measured axis and the neutral axis carried through the map's rotation. On
    the four issued characters the anisotropy is 1.0032-1.0403 and that angle is
    0.016-0.094 degrees, so the shell is a rigid-plus-uniform-scale copy and its axis is an
    orientation. A shell outside EYE_SIMILARITY_MAX_ANISOTROPY is REFUSED, because a
    squashed sphere's pole moves for reasons that have nothing to do with where it looks.

    CORROBORATION, offered as corroboration and not as proof: the anny NEUTRAL carries this
    axis 5.04 degrees outward per eye, against the ~5 degree angle kappa of the anatomical
    literature. A tessellation artefact would have no reason to land there.
    """
    v = np.asarray(v, np.float64)
    faces = np.asarray(faces)
    _frame(v, faces)
    eyes, why = _eye_components(v, faces)
    if eyes is None:
        return _unresolved('the eyeball shells did not resolve: ' + why)

    v0, f0, idx0 = _neutral_eye()
    c0, _ = _sphere_fit(v0[idx0])
    a0, why0 = _pole_axis(v0, f0, idx0, c0)
    if a0 is None:
        return _unresolved('the neutral eyeball shell has no construction axis: ' + why0)

    per = {}
    for side in ('left', 'right'):
        idx = eyes[side]
        P = v[idx]
        c, r = _sphere_fit(P)
        rad = np.linalg.norm(P - c, axis=1)
        u = (P - c) / rad[:, None]
        far = int(np.argmax(rad))
        ax, whya = _pole_axis(v, faces, idx, c)
        if ax is None:
            return _unresolved('the %s eyeball: %s' % (side, whya))
        # Similarity check against the neutral shell, on the SAME vertex indices — the
        # shells are the same component of the same cage, so the correspondence is exact
        # and no registration is involved.
        A = v0[idx0] - v0[idx0].mean(0)
        mirror = 1.0 if side == 'left' else -1.0
        B = P - P.mean(0)
        B = B * np.array([mirror, 1.0, 1.0])
        M, _, _, _ = np.linalg.lstsq(A, B, rcond=None)
        M = M.T
        U, s, Vt = np.linalg.svd(M)
        R = U @ Vt
        if np.linalg.det(R) < 0:
            U[:, -1] *= -1
            R = U @ Vt
        carried = R @ a0['axis']
        carried = carried / np.linalg.norm(carried)
        meas = ax['axis'] * np.array([mirror, 1.0, 1.0])
        agree = math.degrees(math.acos(float(np.clip(meas @ carried, -1.0, 1.0))))
        per[side] = {
            'sphere_centre_m': [float(x) for x in c],
            'sphere_radius_mm': r * 1000.0,
            'radius_min_mm': float(rad.min() * 1000.0),
            'radius_max_mm': float(rad.max() * 1000.0),
            'radius_sd_mm': float(rad.std() * 1000.0),
            'corneal_apex': {
                'refused': True,
                'furthest_vertex_direction': [float(x) for x in u[far]],
                'furthest_vertex_radius_mm': float(rad[far] * 1000.0),
                'points_anterior': bool(u[far][1] < 0),
                'why': 'the shell has no corneal protrusion: the maximum radial deviation '
                'from the fitted sphere is %.4f mm on a %.3f mm radius and it sits '
                'at direction %s. Anterior is -y. Taking this vertex as the corneal '
                'apex builds an optical axis out of the back of the skull.'
                % (float((rad.max() - r) * 1000.0), r * 1000.0, np.round(u[far], 3).tolist()),
            },
            'axis': [float(x) for x in ax['axis']],
            'antipodal_error_deg': ax['antipodal_error_deg'],
            'similarity_singular_values': [float(x) for x in s],
            'similarity_anisotropy': float(s.max() / s.min()),
            'similarity_residual_rms_mm': float(np.sqrt((((A @ M.T) - B) ** 2).sum(1).mean()) * 1000.0),
            'axis_vs_neutral_carried_deg': agree,
            'transverse_tilt_deg': float(math.degrees(math.atan2(ax['axis'][0] * mirror, -ax['axis'][1]))),
        }

    aniso = max(per[s]['similarity_anisotropy'] for s in per)
    agree = max(per[s]['axis_vs_neutral_carried_deg'] for s in per)
    if aniso > EYE_SIMILARITY_MAX_ANISOTROPY or agree > EYE_AXIS_AGREEMENT_MAX_DEG:
        return _unresolved(
            'the eyeball shell on this body is not a rigid-plus-uniform-scale copy of the '
            'neutral eye (anisotropy %.4f against a ceiling of %.2f; measured axis differs '
            'from the neutral axis carried through the fitted rotation by %.4f degrees '
            'against a ceiling of %.2f). Its pole is moving because the sphere is being '
            'deformed, not because the eye is turning, so no orientation may be read off '
            'it.' % (aniso, EYE_SIMILARITY_MAX_ANISOTROPY, agree, EYE_AXIS_AGREEMENT_MAX_DEG),
            per_eye=per,
        )

    al = np.asarray(per['left']['axis'])
    ar = np.asarray(per['right']['axis'])
    total = math.degrees(math.acos(float(np.clip(al @ ar, -1.0, 1.0))))
    hl = al[:2] / np.linalg.norm(al[:2])
    hr = ar[:2] / np.linalg.norm(ar[:2])
    transverse = math.degrees(math.acos(float(np.clip(hl @ hr, -1.0, 1.0))))
    outward = bool(al[0] > 0 and ar[0] < 0)
    return {
        'resolved': True,
        'divergence_total_deg': total,
        'divergence_transverse_deg': transverse,
        'half_angle_per_eye_deg': transverse / 2.0,
        'outward': outward,
        'parallel': bool(transverse < 1e-6),
        'anterior': bool(al[1] < 0 and ar[1] < 0),
        'per_eye': per,
        'anchor': "the eyeball shell's own construction axis (anterior pole patch "
        'centroid minus posterior pole patch centroid, about the fitted '
        'sphere centre)',
        'anchor_kind': "derived — NOT a corneal apex; this cage has none, see per_eye[*]['corneal_apex']",
        'sign_convention': 'positive divergence with outward=True means the two axes '
        'bow AWAY from the midline, which is the anatomical sense '
        'of angle kappa. parallel=True is the rig default and the '
        'known uncanny-valley failure.',
        'literature': 'angle kappa is about 5 degrees per eye; the anny NEUTRAL '
        'measures 5.036 degrees per eye on this anchor.',
    }


# ---------------------------------------------------------------------------------
# (4) KNEE ALIGNMENT AND THE Q ANGLE
# ---------------------------------------------------------------------------------
def q_angle(v, faces):
    """UNRESOLVED. The clinical Q angle needs three landmarks this cage does not have.

    Q angle is the angle at the patella centre between (ASIS -> patella centre) and
    (patella centre -> tibial tuberosity). MEASURED absences, each independently:
      * ASIS: there is no iliac crest and no anterior superior iliac spine. landmarks.py
        records the lateral half-breadth profile of the male original falling monotonically
        from 181.4 mm at 0.50 of stature to the waist minimum at 0.61 with no crest bulge,
        and reports iliocristale UNRESOLVED for that reason.
      * patella centre: landmarks.py reports patella_mid UNRESOLVED — the anterior profile
        of the lower limb rises monotonically through the knee, so there is no local
        anterior maximum to call mid-patella.
      * tibial tuberosity: MEASURED here — of the 256 labels in anny's local-change
        vocabulary, the substrings 'patell', 'asis', 'iliac', 'crest', 'spine', 'tuberos'
        and 'tibia' match ZERO targets. The only knee-region target of any kind is
        measure-knee-circ-incr, a girth ring.

    knee_alignment() below measures what this cage CAN carry — the coronal femorotibial
    angle from anny's own joint centres — and it is a different quantity that must not be
    reported under this name.
    """
    labels = _local_change_labels()
    hits = {
        kw: [n for n in labels if kw in n.lower()]
        for kw in ('patell', 'asis', 'iliac', 'crest', 'spine', 'tuberos', 'tibia', 'knee')
    }
    return _unresolved(
        'the Q angle needs ASIS, patella centre and tibial tuberosity; this cage carries none of the three',
        vocabulary_size=len(labels),
        vocabulary_matches={k: v for k, v in hits.items()},
        landmarks_py_says={
            'iliocristale': 'UNRESOLVED — no iliac crest on this cage',
            'patella_mid': 'UNRESOLVED — no patellar bulge on this cage',
        },
        substitute='knee_alignment(), which is the coronal femorotibial angle and NOT the Q angle',
    )


def _local_change_labels():
    if 'labels' in _CACHE:
        return _CACHE['labels']
    m = MS._model()
    for attr in ('local_change_labels', 'local_changes_labels', 'morph_labels'):
        if hasattr(m, attr):
            _CACHE['labels'] = [str(x) for x in getattr(m, attr)]
            return _CACHE['labels']
    raise AttributeError(
        'the anny model exposes no local-change label list under any of '
        'local_change_labels / local_changes_labels / morph_labels, so '
        'the absence of a target cannot be demonstrated rather than '
        'assumed'
    )


def knee_alignment(v, faces, phenotype=None, local_changes=None):
    """Coronal femorotibial angle and knee-centre deviation, from anny's joint centres.

    This is a RELATION — hip, knee and ankle centre against each other — and it is the one
    lower-limb alignment this cage supports. It is NOT the Q angle (see q_angle()).

    Sign: knee_deviation is POSITIVE when the knee centre lies LATERAL of the straight
    hip-to-ankle line, which is genu varum (bow-legged); negative is valgum (knock-kneed).
    The femorotibial angle is 180 degrees minus the hip-knee-ankle angle, so 0 is a
    straight limb.

    WHAT THE NUMBERS ARE AND WHAT THEY ARE NOT. These are COCO joint centres: a linear
    blend of surface vertices, which is anny's own regressor and not a femoral head. The
    measured angles on the four issued characters are 0.572-1.983 degrees over a limb about
    0.9 m long, so a 2 mm error in any one centre is worth about 0.3 degrees. Read the
    magnitude, not the third decimal. The record carries the deviation in mm alongside so
    the caller can see how small the lever arm is.
    """
    ctx = _context(v, faces, None, phenotype, local_changes)
    try:
        kp = LMK._coco(phenotype, local_changes)
    except Exception as e:  # noqa: BLE001
        return _unresolved("anny's joint-centre regressor could not be evaluated: %s" % e)
    H = ctx['H']
    out = {
        'resolved': True,
        'sides': {},
        'joint_centre_source': 'anny.keypoints COCO regressor, via landmarks._coco',
        'is_not': 'the Q angle — see q_angle() for why that is unresolvable here',
    }
    if phenotype is None:
        out['warning'] = "no phenotype was passed, so the joint centres are the NEUTRAL recipe's and not this body's"
    for side in ('left', 'right'):
        hip = np.asarray(kp[side + '_hip'], np.float64)
        knee = np.asarray(kp[side + '_knee'], np.float64)
        ank = np.asarray(kp[side + '_ankle'], np.float64)
        if abs(ank[2] - hip[2]) < 1e-6:
            return _unresolved(
                'the %s hip and ankle centres are at the same height, so '
                'there is no mechanical axis to deviate from' % side
            )
        f = hip - knee
        t = ank - knee
        f2 = np.array([f[0], f[2]])
        t2 = np.array([t[0], t[2]])
        f2 = f2 / np.linalg.norm(f2)
        t2 = t2 / np.linalg.norm(t2)
        fta = 180.0 - math.degrees(math.acos(float(np.clip(f2 @ t2, -1.0, 1.0))))
        x_on_axis = hip[0] + (ank[0] - hip[0]) * (knee[2] - hip[2]) / (ank[2] - hip[2])
        lateral = 1.0 if side == 'left' else -1.0
        dev = float((knee[0] - x_on_axis) * lateral)
        out['sides'][side] = {
            'femorotibial_angle_deg': float(fta),
            'knee_deviation_mm': dev * 1000.0,
            'knee_deviation_frac_stature': dev / H,
            'varum' if dev > 0 else 'valgum': True,
        }
    ls, rs = out['sides']['left'], out['sides']['right']
    out['asymmetry_deg'] = abs(ls['femorotibial_angle_deg'] - rs['femorotibial_angle_deg'])
    out['asymmetry_mm'] = abs(ls['knee_deviation_mm'] - rs['knee_deviation_mm'])
    return out


def pelvis_width_to_tilt(v, faces, landmarks=None, phenotype=None, local_changes=None):
    """UNRESOLVED. A wider pelvis is supposed to pair with a greater anterior tilt and a
    larger Q angle; on this cage two of those three quantities do not exist.

    The width half IS measurable and is reported, so that what is missing is visible rather
    than merely absent: pelvic tilt is unresolved (segment_tilt_opposition) and the Q angle
    is unresolved (q_angle), which leaves a width with nothing to relate to.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    g = gluteal_vs_trochanteric(v, faces, landmarks=ctx['lm'])
    tilt = segment_tilt_opposition(v, faces, landmarks=ctx['lm'])
    return _unresolved(
        'the relationship needs a pelvic TILT, which is unresolved on this cage, and a Q '
        'angle, which is unresolved on this cage. Only the width half exists.',
        trochanteric_width_mm=g.get('trochanteric_width_mm'),
        trochanteric_width_frac_stature=(
            None if g.get('trochanteric_width_mm') is None else g['trochanteric_width_mm'] / (ctx['H'] * 1000.0)
        ),
        pelvic_tilt=tilt.get('pelvic_tilt_deg'),
        pelvic_tilt_is='UNRESOLVED: ' + str(tilt.get('reason')),
        q_angle_is='UNRESOLVED: see q_angle()',
    )


# ---------------------------------------------------------------------------------
# one call for a whole body
# ---------------------------------------------------------------------------------
def measure_relations(v, faces, *, phenotype=None, local_changes=None, landmarks=None):
    """Every relational predicate on one body, resolved and unresolved alike."""
    t0 = time.time()
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    lm = ctx['lm']
    chain = posterior_midline_chain(v, faces, landmarks=lm)
    out = {
        'schema': SCHEMA,
        'stature_m': ctx['H'],
        'frame': {
            k: _frame(ctx['v'], ctx['faces'])[k]
            for k in ('convention', 'up_axis', 'anterior_axis', 'subject_left_axis')
        },
        'sign_convention': SIGN_CONVENTION,
        'posterior_midline_chain': chain,
        'lumbar_curvature': lumbar_curvature(v, faces, landmarks=lm, chain=chain),
        'segment_tilt_opposition': segment_tilt_opposition(v, faces, landmarks=lm),
        'gluteal_vs_trochanteric': gluteal_vs_trochanteric(v, faces, landmarks=lm),
        'eye_axes': eye_axes(v, faces),
        'knee_alignment': knee_alignment(v, faces, phenotype, local_changes),
        'q_angle': q_angle(v, faces),
        'pelvis_width_to_tilt': pelvis_width_to_tilt(v, faces, landmarks=lm),
    }
    out['unresolved'] = sorted(k for k, r in out.items() if isinstance(r, dict) and r.get('resolved') is False)
    out['elapsed_s'] = round(time.time() - t0, 3)
    return out


def scalars(rel):
    """The gateable scalars out of a measure_relations() record, None where unresolved."""
    lc = rel['lumbar_curvature']
    gv = rel['gluteal_vs_trochanteric']
    ea = rel['eye_axes']
    ka = rel['knee_alignment']
    g = lambda d, k: d.get(k) if d.get('resolved') else None
    return {
        'lordosis_index': g(lc, 'lordosis_index'),
        'lordosis_depth_mm': g(lc, 'lordosis_depth_mm'),
        'lumbar_curve_angle_deg': g(lc, 'curve_angle_deg'),
        'lower_chord_tilt_deg': g(lc, 'lower_chord_tilt_deg'),
        'upper_chord_tilt_deg': g(lc, 'upper_chord_tilt_deg'),
        'opposition_physiological': g(lc, 'opposition_physiological'),
        'trough_frac_stature': g(lc, 'trough_frac_stature'),
        'gluteal_margin_mm': g(gv, 'margin_mm'),
        'gluteal_margin_frac_stature': g(gv, 'margin_frac_stature'),
        'eye_divergence_transverse_deg': g(ea, 'divergence_transverse_deg'),
        'eye_outward': g(ea, 'outward'),
        'knee_fta_deg': (
            None if not ka.get('resolved') else max(s['femorotibial_angle_deg'] for s in ka['sides'].values())
        ),
        'knee_asymmetry_deg': g(ka, 'asymmetry_deg'),
    }
