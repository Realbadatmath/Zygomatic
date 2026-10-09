# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GATE 4 t5_scapula_static, GATE 5 t5_elbow_owner, GATE 6 t5_patellar_ligament.

Moved verbatim out of the old single-file pose_limits.py (lines 2655-3239).
"""

from zyg_workflows.geom.pose_limits.base import CANON, FAIL, HOUSE, MS, PASS, REPORT, UNRESOLVED, np
from zyg_workflows.geom.pose_limits.printed import (
    ELBOW_HUMERAL_CONTROL_PATCHES,
    ELBOW_OWNER_SOURCE,
    PATELLAR_LIGAMENT_MAX_DRIFT,
    PATELLAR_SOURCE,
    SCAPULA_SOURCE,
    SCAPULA_STATIC_BELOW_DEG,
)
from zyg_workflows.geom.pose_limits.rig import (
    _model_index,
    anatomical_frame,
    bone_index,
    bone_roster,
    local_axis,
    pose_from_local,
    rig_numerical_floor,
    rig_state,
    rot_angle_deg,
    unit,
)
from zyg_workflows.geom.pose_limits.rom import _res


# ---------------------------------------------------------------------------------
# GATE 4 — t5_scapula_static
# ---------------------------------------------------------------------------------
def t5_scapula_static(phenotype, local_changes=None, side='l', abduction_deg=(0, 30, 60, 90, 120, 150)):
    """UNRESOLVED as written, plus the measurable complement.

    The gate asks whether the scapula rotates below 90 degrees of humeral abduction. This
    rig has no scapula bone — rig_report() proves it by name search over all 163 — and
    geom.form.regions independently reports scapular_spine, scapula_medial_border and
    scapula_inferior_angle UNRESOLVED, having found nothing but the vertical trapezius
    ridge over the whole posterior shoulder. So there is neither a bone to rotate nor a
    surface patch to watch it, and no amount of measurement will produce the number.

    What IS measured, and is the useful half: the rotation of every shoulder-girdle bone as
    the humerus is abducted through and past 90 degrees. Because no girdle bone is a child
    of the humerus, that rotation is identically zero at EVERY angle. Below 90 that is what
    AFS p.90 asks for; above 90 the same page asks for the opposite, and the rig cannot
    supply it. Reported as a two-sided finding.
    """
    S = 'L' if side.lower() == 'l' else 'R'
    rest = rig_state(phenotype, local_changes, None)
    af = anatomical_frame(rest)
    # abduction = raising the humerus in the coronal plane, i.e. rotation about the
    # anterior-posterior axis. Sign chosen by measurement: whichever sign RAISES the elbow.
    hum = 'upperarm01.%s' % S
    ax_world = af['anterior']
    probe = {}
    for sgn in (+1.0, -1.0):
        aa = pose_from_local({hum: local_axis(rest, hum, ax_world) * np.radians(30.0) * sgn})
        st = rig_state(phenotype, local_changes, aa)
        probe[sgn] = float(
            (st['heads'][bone_index('lowerarm01.%s' % S)] - rest['heads'][bone_index('lowerarm01.%s' % S)])
            @ af['superior']
        )
    sgn = 1.0 if probe[1.0] > probe[-1.0] else -1.0

    rows = []
    girdle = [b for b in ('clavicle.%s' % S, 'shoulder01.%s' % S, 'spine01') if b in _model_index()]
    for deg in abduction_deg:
        aa = pose_from_local({hum: local_axis(rest, hum, ax_world) * np.radians(float(deg)) * sgn})
        st = rig_state(phenotype, local_changes, aa)
        # achieved abduction, measured from the humerus direction rather than assumed
        h0 = unit(rest['heads'][bone_index('lowerarm01.%s' % S)] - rest['heads'][bone_index(hum)])
        h1 = unit(st['heads'][bone_index('lowerarm01.%s' % S)] - st['heads'][bone_index(hum)])
        rows.append(
            {
                'requested_deg': float(deg),
                'achieved_humeral_deg': round(float(np.degrees(np.arccos(np.clip(h0 @ h1, -1, 1)))), 3),
                'girdle_rotation_deg': {
                    b: round(rot_angle_deg(st['R'][bone_index(b)] @ rest['R'][bone_index(b)].T), 12) for b in girdle
                },
            }
        )
    below = [r for r in rows if r['requested_deg'] <= SCAPULA_STATIC_BELOW_DEG]
    above = [r for r in rows if r['requested_deg'] > SCAPULA_STATIC_BELOW_DEG]
    max_below = max((v for r in below for v in r['girdle_rotation_deg'].values()), default=0.0)
    max_above = max((v for r in above for v in r['girdle_rotation_deg'].values()), default=0.0)
    nfloor = rig_numerical_floor(phenotype, local_changes)['reproducibility_deg']
    try:
        from zyg_workflows.geom.form import regions as RG

        doc = RG.load_regions()
        scap = {
            k: doc['regions'][k]['status']
            for k in ('scapular_spine', 'scapula_medial_border', 'scapula_inferior_angle')
            if k in doc['regions']
        }
    except Exception as e:  # noqa: BLE001
        scap = {'error': str(e)}
    return _res(
        't5_scapula_static',
        UNRESOLVED,
        'this rig has no scapula bone, so scapular rotation cannot be measured at any abduction angle',
        observed={'max_girdle_rotation_below_90_deg': max_below, 'max_girdle_rotation_above_90_deg': max_above},
        band={'scapula_rotation_below_deg': 0.0, 'abduction_threshold_deg': SCAPULA_STATIC_BELOW_DEG},
        source=SCAPULA_SOURCE,
        provenance=CANON,
        bone_search={
            'scapula': [b for b in bone_roster()[0] if 'scapula' in b.lower()],
            'n_bones_searched': len(bone_roster()[0]),
        },
        regions_py_says=scap,
        numerical_floor_deg=nfloor,
        complement_finding=(
            'shoulder-girdle rotation is %.3g deg below 90 deg of abduction and '
            "%.3g deg above it, against this body's measured numerical floor of "
            '%.3g deg — i.e. ZERO at every angle, because no girdle bone is a '
            'descendant of the humerus. Below 90 that satisfies AFS p.90. Above 90 '
            'the same page requires the scapula to begin rotating and its borders '
            'to become surface-readable, and this rig cannot produce either — so '
            'every scapular border a render shows above 90 deg of abduction was '
            'invented by the image model, not carried by the geometry.' % (max_below, max_above, nfloor)
        ),
        sweep=rows,
        side=S,
    )


# ---------------------------------------------------------------------------------
# GATE 5 — t5_elbow_owner
# ---------------------------------------------------------------------------------
def _region_group(name, side):
    """A frozen vertex group from geom.form.regions, or None with the reason."""
    try:
        from zyg_workflows.geom.form import regions as RG

        doc = RG.load_regions()
    except Exception as e:  # noqa: BLE001
        return None, 'geom.form.regions could not be read: %s' % e
    rec = doc['regions'].get(name)
    if rec is None:
        return None, 'geom.form.regions publishes no region named %r' % name
    if rec.get('status') != 'resolved':
        return None, ('region %r is %s in geom.form.regions: %s' % (name, rec.get('status'), rec.get('note', '')[:200]))
    idx = rec['vertex_idx_l' if side.lower() == 'l' else 'vertex_idx_r']
    if not idx:
        return None, 'region %r has no vertices on the %s side' % (name, side)
    return np.asarray(idx, np.int64), rec


def _patch_ownership(idx):
    """What the rig's own skinning says drives a patch. Evidence, never a selector."""
    m = MS._model()
    vbi = m.vertex_bone_indices.numpy()[idx]
    vbw = m.vertex_bone_weights.numpy()[idx]
    names, _ = bone_roster()
    tot = {}
    for c in range(vbi.shape[1]):
        for b, w in zip(vbi[:, c], vbw[:, c]):
            if w > 0:
                tot[names[b]] = tot.get(names[b], 0.0) + float(w)
    s = sum(tot.values()) or 1.0
    return {k: round(v / s, 4) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])[:6]}


def _frame_residuals(rest, st, P, bones, Q):
    """RMS residual of a point set under each candidate bone's own rigid transform.

    `Q` is where those points ended up. Passing a SYNTHETIC Q is how the negative control
    is built: a patch deliberately carried by one bone must come back owned by that bone.
    """
    out = {}
    for b in bones:
        T = st['R'][bone_index(b)] @ rest['R'][bone_index(b)].T
        pred = (P - rest['heads'][bone_index(b)]) @ T.T + st['heads'][bone_index(b)]
        out[b] = float(np.sqrt(((pred - Q) ** 2).sum(1).mean()))
    return out


def _rigid_carry(rest, st, P, bone):
    """Where a patch would be if it were skinned 100% to `bone`."""
    T = st['R'][bone_index(bone)] @ rest['R'][bone_index(bone)].T
    return (P - rest['heads'][bone_index(bone)]) @ T.T + st['heads'][bone_index(bone)]


def _elbow_owner_rows(rest, phenotype, local_changes, S, hum, fore, flexion_deg, groups):
    """Drive the elbow once and answer the ownership question for every supplied patch.

    `groups` is {label: vertex_index_array}. One flexion sweep serves the subject patch,
    the humeral control patches and the two synthetic controls, so the control costs a
    residual and not a second rig solve.
    """
    uh = unit(rest['heads'][bone_index(fore)] - rest['heads'][bone_index('upperarm01.%s' % S)])
    uf = unit(rest['heads'][bone_index('wrist.%s' % S)] - rest['heads'][bone_index(fore)])
    ax = unit(np.cross(uh, uf))  # measured: this sign FLEXES (verified)
    out = {k: [] for k in groups}
    synth = {hum: [], fore: []}
    for deg in flexion_deg:
        aa = pose_from_local({fore: local_axis(rest, fore, ax) * np.radians(float(deg))})
        st = rig_state(phenotype, local_changes, aa)
        a0 = np.degrees(
            np.arccos(
                np.clip(
                    unit(rest['heads'][bone_index('upperarm01.%s' % S)] - rest['heads'][bone_index(fore)])
                    @ unit(rest['heads'][bone_index('wrist.%s' % S)] - rest['heads'][bone_index(fore)]),
                    -1,
                    1,
                )
            )
        )
        a1 = np.degrees(
            np.arccos(
                np.clip(
                    unit(st['heads'][bone_index('upperarm01.%s' % S)] - st['heads'][bone_index(fore)])
                    @ unit(st['heads'][bone_index('wrist.%s' % S)] - st['heads'][bone_index(fore)]),
                    -1,
                    1,
                )
            )
        )
        for label, idx in groups.items():
            P = rest['v'][idx]
            resid = _frame_residuals(rest, st, P, (hum, fore), st['v'][idx])
            out[label].append(
                {
                    'drive_deg': float(deg),
                    'elbow_included_deg_rest': round(float(a0), 2),
                    'elbow_included_deg_posed': round(float(a1), 2),
                    'residual_mm': {b: round(1000.0 * r, 4) for b, r in resid.items()},
                    'owner': min(resid, key=resid.get),
                    'ratio_forearm_over_upperarm': round(resid[fore] / max(resid[hum], 1e-12), 6),
                }
            )
        # THE SYNTHETIC CONTROLS. Take the subject patch and move it as if it were skinned
        # 100% to one bone, then ask the same comparator who owns it. It must name that
        # bone. This is the "a deliberately humerus-skinned patch must FAIL" control: if
        # the humeral synthetic still came back 'forearm', the comparator would be answering
        # 'forearm' unconditionally and every PASS it has ever produced would be worthless.
        P0 = rest['v'][groups['subject']]
        for carrier in (hum, fore):
            r = _frame_residuals(rest, st, P0, (hum, fore), _rigid_carry(rest, st, P0, carrier))
            synth[carrier].append(
                {
                    'drive_deg': float(deg),
                    'carried_by': carrier,
                    'owner_named': min(r, key=r.get),
                    'residual_mm': {b: round(1000.0 * v, 6) for b, v in r.items()},
                }
            )
    return out, synth


def t5_elbow_owner(phenotype, local_changes=None, side='l', flexion_deg=(30.0, 60.0, 90.0), patch='olecranon'):
    """Is the olecranon patch rigid in the FOREARM frame or the upper-arm frame?

    A COMPARATIVE residual, so there is nothing to tune: pose the elbow, then ask how well
    each candidate bone's rigid transform explains where the patch went. The forearm must
    win. If it does not, the skinning has given the point of the elbow to the humerus and
    every flexed render will slide it up the arm.

    THE PASS IS NOW CONDITIONED ON A NEGATIVE CONTROL, and on this rig that withdraws it
    (D7, 2026-08-06). The finding this fix answers: handed patch='epicondyle_lat' — an
    unambiguously HUMERAL landmark, a prominence of the distal humerus that cannot travel
    with the forearm — the identical comparator answered `lowerarm01.L` and returned PASS,
    residual 54.75 mm in the humerus frame against 0.0 mm in the forearm frame. It answered
    "forearm" on BOTH sides of the joint, so its PASS on the olecranon would have been
    produced whether or not the olecranon were modelled on the ulna, and a PASS that occurs
    regardless of the truth of its claim is worse than no gate. Two controls now run inside
    the gate on every call:

      SYNTHETIC (validity of the comparator). The subject patch is moved as though it were
      skinned 100% to the humerus, and separately 100% to the forearm, and the comparator
      must name the carrying bone both times. This proves the machinery CAN return
      'humerus' and is not wired to answer 'forearm'. It passes.

      ANATOMICAL (resolving power at THIS joint). The same comparator is run on the medial
      and lateral epicondyle patches, which are humeral by definition. If it does not call
      them humerus-owned, it has no resolving power where the claim is made, and the
      subject's result is withdrawn to UNRESOLVED with every number attached rather than
      shipped as a PASS. On this cage it does not: geom.form.regions builds all three
      patches as sectors of the same elbow joint-line ring in the FOREARM's frame, and the
      rig skins that whole ring to lowerarm01.

    A FAIL is NOT withdrawn by a blind control. A FAIL means the humerus frame explained
    the patch better, which is the comparator discriminating in the direction that matters;
    the control governs only whether a 'forearm' answer is informative.

    The patch is geom.form.regions' frozen `olecranon` group — the posterior 90-degree
    sector of the elbow JOINT LINE in the forearm's own frame, which that module publishes
    with claim='surface_aspect' and the explicit warning that this cage carries no
    olecranon PROMINENCE (it measures -2.07 mm there, a shallow depression). This gate does
    not need a prominence. It needs the right piece of skin, and the joint-line sector is
    exactly that.
    """
    S = 'L' if side.lower() == 'l' else 'R'
    hum, fore = 'upperarm02.%s' % S, 'lowerarm01.%s' % S
    idx, rec = _region_group(patch, side)
    if idx is None:
        return _res('t5_elbow_owner', UNRESOLVED, rec, source=ELBOW_OWNER_SOURCE, provenance=None, patch=patch, side=S)
    rest = rig_state(phenotype, local_changes, None)
    if len(rest['v']) <= int(idx.max()):
        return _res(
            't5_elbow_owner',
            UNRESOLVED,
            'the frozen group indexes a %d-vertex cage; this mesh has %d' % (int(idx.max()) + 1, len(rest['v'])),
            source=ELBOW_OWNER_SOURCE,
            patch=patch,
            side=S,
        )

    # The humeral control patches, minus the subject if the caller handed us one of them.
    groups, ctrl_unavailable = {'subject': idx}, {}
    for name in ELBOW_HUMERAL_CONTROL_PATCHES:
        if name == patch:
            continue
        cidx, crec = _region_group(name, side)
        if cidx is None or len(rest['v']) <= int(cidx.max()):
            ctrl_unavailable[name] = crec if cidx is None else 'the frozen group indexes a larger cage than this mesh'
            continue
        groups[name] = cidx

    rows_by_group, synth = _elbow_owner_rows(rest, phenotype, local_changes, S, hum, fore, flexion_deg, groups)
    rows = rows_by_group['subject']
    owners = {r['owner'] for r in rows}
    subject_ok = owners == {fore}

    synthetic = {}
    for carrier, srows in synth.items():
        synthetic[carrier] = {
            'must_name': carrier,
            'named': sorted({r['owner_named'] for r in srows}),
            'ok': all(r['owner_named'] == carrier for r in srows),
            'rows': srows,
        }
    synth_ok = all(v['ok'] for v in synthetic.values())

    controls = {}
    for name in ELBOW_HUMERAL_CONTROL_PATCHES:
        if name not in groups:
            continue
        crows = rows_by_group[name]
        controls[name] = {
            'landmark_is': 'a prominence of the DISTAL HUMERUS',
            'must_be_owned_by': hum,
            'owner_per_angle': {str(r['drive_deg']): r['owner'] for r in crows},
            'ok': all(r['owner'] == hum for r in crows),
            'skin_ownership': _patch_ownership(groups[name]),
            'median_ratio_forearm_over_upperarm': float(np.median([r['ratio_forearm_over_upperarm'] for r in crows])),
            'rows': crows,
        }
    blind = [n for n, c in controls.items() if not c['ok']]
    discriminates = bool(controls) and not blind

    obs = {
        'owner_per_angle': {str(r['drive_deg']): r['owner'] for r in rows},
        'median_ratio_forearm_over_upperarm': float(np.median([r['ratio_forearm_over_upperarm'] for r in rows])),
        'subject_owned_by_forearm_at_every_angle': subject_ok,
        'synthetic_controls_ok': synth_ok,
        'humeral_control_patches': sorted(controls),
        'humeral_controls_owned_by_humerus': (None if not controls else discriminates),
        'humeral_controls_answering_forearm': blind,
        'comparator_discriminates_at_this_joint': discriminates,
    }

    # ---- VERDICT. Ordered so that no branch can produce a PASS the controls do not carry.
    if patch in ELBOW_HUMERAL_CONTROL_PATCHES:
        status = UNRESOLVED
        explain = (
            '%r is a HUMERAL landmark, so "belongs to the ulna and travels with the '
            'forearm" is not a claim about it and this gate makes none. Measured '
            'anyway: the comparator names %s at every tested angle, and the rig '
            'skins the patch %s.' % (patch, sorted(owners), list(_patch_ownership(idx).items())[:2])
        )
    elif not synth_ok:
        bad = [c for c, v in synthetic.items() if not v['ok']]
        status = UNRESOLVED
        explain = (
            'the comparator failed its own synthetic control: a copy of the %r patch '
            'carried rigidly by %s was not attributed to %s, so this comparison '
            'cannot support any verdict about which frame owns the patch'
            % (patch, ' and '.join(bad), ' and '.join(bad))
        )
    elif not subject_ok:
        status = FAIL
        explain = (
            'the %s patch is better explained by the UPPER-ARM frame at %d of %d '
            'tested angles: the point of the elbow is skinned to the humerus'
            % (patch, sum(1 for r in rows if r['owner'] != fore), len(rows))
        )
    elif not controls:
        status = UNRESOLVED
        explain = (
            'the %s patch is rigid in the FOREARM frame at every tested angle, but '
            'no humeral control patch is available on this cage (%s), so that '
            'answer cannot be separated from a comparator that says "forearm" for '
            'every patch at this joint'
            % (
                patch,
                '; '.join('%s: %s' % (k, str(v)[:80]) for k, v in sorted(ctrl_unavailable.items())) or 'none declared',
            )
        )
    elif blind:
        status = UNRESOLVED
        explain = (
            'WITHDRAWN, not passed: the %s patch is rigid in the FOREARM frame at '
            'every tested angle, but so %s %s — %s of the DISTAL HUMERUS that '
            'cannot travel with the forearm. The comparator answers "forearm" on '
            'both sides of this joint, so this result would be produced whether or '
            'not the olecranon is modelled on the ulna. What it does confirm is '
            'that the rig skins the whole elbow joint-line ring to %s (%s), which '
            'is a finding about the rig, not evidence for AFS p.156.'
            % (
                patch,
                'is' if len(blind) == 1 else 'are',
                ', '.join(sorted(blind)),
                'a landmark' if len(blind) == 1 else 'landmarks',
                fore,
                '; '.join(
                    '%s -> %s' % (n, sorted(set(controls[n]['owner_per_angle'].values()))) for n in sorted(blind)
                ),
            )
        )
    else:
        status = PASS
        explain = (
            'the %s patch is rigid in the FOREARM frame at every tested flexion '
            'angle, and the comparator discriminates here: the humeral control '
            'patch(es) %s came back owned by %s' % (patch, ', '.join(sorted(controls)), hum)
        )
    return _res(
        't5_elbow_owner',
        status,
        explain,
        observed=obs,
        band={
            'required_owner': fore,
            'humeral_control_required_owner': hum,
            'synthetic_control_must_name_its_carrier': True,
        },
        source=ELBOW_OWNER_SOURCE,
        provenance=None,
        patch=patch,
        patch_n_vertices=int(len(idx)),
        side=S,
        patch_claim=rec.get('claim'),
        patch_confidence=rec.get('confidence'),
        patch_skin_ownership=_patch_ownership(idx),
        negative_control_synthetic=synthetic,
        negative_control_humeral=controls,
        negative_control_unavailable=ctrl_unavailable,
        control_note=(
            'A PASS here is only evidence for AFS p.156 if the same '
            'comparator can say "humerus" — mechanically (synthetic '
            'control) AND about a landmark that really is humeral '
            '(epicondyle control). Before 2026-08-06 neither ran and the '
            'gate returned PASS for the lateral epicondyle itself (D7).'
        ),
        rows=rows,
    )


# ---------------------------------------------------------------------------------
# GATE 6 — t5_patellar_ligament
# ---------------------------------------------------------------------------------
def t5_patellar_ligament(phenotype, local_changes=None, side='l', flexion_deg=(0, 15, 30, 45, 60, 75, 90, 105, 120)):
    """dist(patella, tibial tuberosity) must be invariant to within 2% through the range.

    The cleanest gate in the corpus: no anatomy to invent, no window to choose, one printed
    percentage and an invariance.

    THE VACUITY CHECK IS PART OF THE RESULT. If both patches were driven by the same bone
    the distance would be invariant by construction and a pass would mean nothing. MEASURED
    on this rig they are not: the patella patch is dominated by upperleg02 (the femur) and
    the tuberosity patch by lowerleg01 (the tibia). `trivially_invariant` reports that
    every run, and when it is True the status is downgraded to `report` because the gate
    has not tested anything.

    THIS GATE CANNOT RETURN PASS IN ANY CONFIGURATION OF THIS RIG. Measured 2026-08-08 on
    originals/male, and the two halves are exhaustive:

        extensor correction OFF  patella rides upperleg02, tuberosity rides lowerleg01,
                                 drift 9.67-29.34 % across the five bodies  ->  FAIL
        extensor correction ON   both ride lowerleg01, drift 0.67-1.20 %, and the vacuity
                                 check above therefore fires                ->  REPORT

    and there is no third option, because geom.patella_skin derives from the algebra of
    linear blend skinning that mean femur weight over the patch must fall to ~0.03 from
    0.82 for the drift to come inside tolerance — i.e. the ONLY admissible fix is the one
    that makes both patches share a bone. The vacuity rule is right in general and reaches
    the wrong conclusion here in particular: for THIS anatomy, both patches riding the
    tibia is not a trick that guarantees the answer, it IS the answer — the patella is a
    sesamoid tethered to the tuberosity by an inextensible ligament, so its position
    genuinely tracks the tibia.

    What the gate is really reporting in the ON state is "the extensor mechanism is now
    modelled, and I can no longer detect it regressing". That is worth saying explicitly
    rather than as the same `report` an accidental gluing would produce, and the evidence
    to tell them apart is available and cheap (patella_skin.is_applied). NOT DONE HERE,
    because the correction is default-OFF on its own measured cost and the ON state does
    not currently ship — building the distinction now would be writing semantics for a
    configuration nothing uses. Recorded so the next reader does not spend a day
    rediscovering that a blocking gate has no passing state.
    """
    S = 'L' if side.lower() == 'l' else 'R'
    pat, prec = _region_group('patella', side)
    tub, trec = _region_group('tibial_tuberosity', side)
    if pat is None or tub is None:
        return _res(
            't5_patellar_ligament',
            UNRESOLVED,
            prec if pat is None else trec,
            source=PATELLAR_SOURCE,
            provenance=HOUSE,
            claim_provenance=CANON,
            side=S,
        )
    rest = rig_state(phenotype, local_changes, None)
    own_p, own_t = _patch_ownership(pat), _patch_ownership(tub)
    top_p, top_t = next(iter(own_p)), next(iter(own_t))
    trivial = bool(top_p == top_t)

    shin = 'lowerleg01.%s' % S
    uh = unit(rest['heads'][bone_index(shin)] - rest['heads'][bone_index('upperleg01.%s' % S)])
    ul = unit(rest['heads'][bone_index('foot.%s' % S)] - rest['heads'][bone_index(shin)])
    ax = unit(np.cross(uh, ul))

    # sign measured, not assumed: knee flexion DECREASES the included hip-knee-ankle angle
    def included(st):
        a = unit(st['heads'][bone_index('upperleg01.%s' % S)] - st['heads'][bone_index(shin)])
        b = unit(st['heads'][bone_index('foot.%s' % S)] - st['heads'][bone_index(shin)])
        return float(np.degrees(np.arccos(np.clip(a @ b, -1, 1))))

    probe = {}
    for sgn in (+1.0, -1.0):
        st = rig_state(
            phenotype, local_changes, pose_from_local({shin: local_axis(rest, shin, ax) * np.radians(20.0) * sgn})
        )
        probe[sgn] = included(st)
    sgn = 1.0 if probe[1.0] < probe[-1.0] else -1.0

    d0 = float(np.linalg.norm(rest['v'][pat].mean(0) - rest['v'][tub].mean(0)))
    rows = []
    for deg in flexion_deg:
        st = (
            rest
            if deg == 0
            else rig_state(
                phenotype,
                local_changes,
                pose_from_local({shin: local_axis(rest, shin, ax) * np.radians(float(deg)) * sgn}),
            )
        )
        d = float(np.linalg.norm(st['v'][pat].mean(0) - st['v'][tub].mean(0)))
        rows.append(
            {
                'drive_deg': float(deg),
                'knee_included_deg': round(included(st), 2),
                'distance_mm': round(1000.0 * d, 4),
                'drift': round((d - d0) / d0, 6),
            }
        )
    worst = max(rows, key=lambda r: abs(r['drift']))
    ok = abs(worst['drift']) <= PATELLAR_LIGAMENT_MAX_DRIFT
    status = REPORT if trivial else (PASS if ok else FAIL)
    return _res(
        't5_patellar_ligament',
        status,
        (
            '%s: patella-to-tuberosity distance drifts %.2f%% at %.0f deg of drive '
            '(limit %.0f%%)'
            % (
                'vacuous — both patches ride the same bone'
                if trivial
                else ('within tolerance' if ok else 'THE LIGAMENT IS NOT MODELLED'),
                100.0 * worst['drift'],
                worst['drive_deg'],
                100.0 * PATELLAR_LIGAMENT_MAX_DRIFT,
            )
        ),
        observed={
            'rest_distance_mm': round(1000.0 * d0, 3),
            'max_abs_drift': abs(worst['drift']),
            'at_drive_deg': worst['drive_deg'],
        },
        band={'max_abs_drift': PATELLAR_LIGAMENT_MAX_DRIFT},
        # provenance=HOUSE, claim_provenance=CANON. AFS p.208 prints the
        # INVARIANCE and no tolerance; PATELLAR_LIGAMENT_MAX_DRIFT = 0.02 is OUR
        # operationalisation of the word "fixed", so the number this gate APPLIES
        # is HOUSE and only the SENTENCE it tests is CANON. This used to emit
        # CANON on the threshold key, which outranks the registry's adjudicated
        # HOUSE and made the gate POLICY_ERROR on all five bodies — so the real
        # finding below (the ligament is not modelled, 10.17-27.32% drift) was
        # never reported, only the paperwork disagreement was. Corrected
        # 2026-08-08; the registry tag was right all along.
        source=PATELLAR_SOURCE,
        provenance=HOUSE,
        claim_provenance=CANON,
        trivially_invariant=trivial,
        patella_skin_ownership=own_p,
        tuberosity_skin_ownership=own_t,
        patella_claim=prec.get('claim'),
        tuberosity_claim=trec.get('claim'),
        patch_caveat=(
            'both groups are geom.form.regions surface_aspect patches, '
            'not bony landmarks: that module measures the anterior knee '
            'at +8.90 mm relief (contrast 3.06, real) and the tuberosity '
            "sector at +1.49 mm (contrast 0.58, below the cage's own "
            'null). The gate measures how the SKIN of the extensor '
            'mechanism moves, which is what a render shows.'
        ),
        rows=rows,
        side=S,
    )
