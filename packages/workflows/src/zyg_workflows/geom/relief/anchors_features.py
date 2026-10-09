# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anchors_features — the six regional record builders `anchors._build_features`
is made of (2026-10-09).

`_build_features` was one 356-line list-of-records function. It is now an
orchestrator that concatenates these six builders in the order the records were
always appended: clavicle, acromion, arm, ankle-and-shank, pelvis, neck. Each
builder returns its own records as a list; nothing was retuned, renamed or
reordered, and the prose in every `anchor=` string is the one that was there.

Every builder reads the same `_Ctx` the old closure read — `ctx.S`, `ctx.z0`,
`ctx.v`, `ctx.shell`, `ctx.bone()`, `ctx.sex()` — so each one can be exercised
on a stub context, which is what tests/test_anchors_helpers.py does.
"""

import numpy as np

from zyg_workflows.geom.relief.anchors import (
    _clavicle_crest,
    _crest_points,
    _curve,
    _elbow_posterior,
    _unit,
    _wrist_postero_ulnar,
)
from zyg_workflows.geom.relief.constants import (
    AMP,
    CLAVICLE_S_AMPLITUDE_FRAC,
    CLAVICLE_S_CROSSING,
    CREST_AZIMUTH_DEG,
    CREST_DROP_ANTERIOR_FRAC,
    FACET_CAP_FRAC,
    MALLEOLUS_HEIGHT_OFFSET_FRAC,
    MALLEOLUS_LAT_POSTERIOR_FRAC,
    NUCHAL_N_STATIONS,
    PSIS_BELOW_CREST_FRAC,
    PSIS_HALF_SEPARATION_FRAC,
    TIBIAL_FACET_CURVATURE_TARGET_FRAC,
    ULNAR_BORDER_N_STATIONS,
)


def clavicle_records(ctx):
    """The four clavicular records, in append order: clavicle_ridge (the S-curved
    crest off the bone), infraclavicular_fossa, jugular_notch and
    supraclavicular_fossa. All four are positioned off the one crest polyline
    `_clavicle_crest` returns, which is why they are built together."""
    F = []
    S = ctx.S

    # ---- 1  clavicle -------------------------------------------------------------
    pts, u, ap, dev, L = _clavicle_crest(ctx)
    asup = _unit(np.array([0.0, -0.55, 0.84]))
    cpt, casp = _curve(pts, asup, S)
    F.append(
        dict(
            name='clavicle_ridge',
            claim='bone',
            op='curve',
            amp_frac=AMP['clavicle_ridge'],
            points=cpt,
            aspect=casp,
            min_dot=0.10,
            anchor='clavicle.L/R bone polyline, sternoclavicular head to acromial '
            'tail (%.1f mm on this body), crest deviated %.1f mm from the '
            'chord with one A-P sign change at %.2f of the shaft'
            % (1e3 * L, 1e3 * CLAVICLE_S_AMPLITUDE_FRAC * S, CLAVICLE_S_CROSSING),
            extra={
                'ap_deviation_mm': [float(1e3 * d) for d in dev],
                'ap_sign_changes': int((np.diff(np.sign(dev)) != 0).sum()),
                'bone_length_frac_stature': L / S,
            },
            probes=('clavicle_shaft', 'sternal_end', 'deltopectoral_triangle'),
        )
    )

    # 1b infraclavicular fossa — inferolateral to the lateral third
    lat = pts[int(0.55 * (len(pts) - 1)) :]
    fossa, fasp = _curve(lat + np.array([0.0, -0.004, -0.022]) * S, _unit(np.array([0.15, -0.97, 0.19])), S)
    F.append(
        dict(
            name='infraclavicular_fossa',
            claim='constructed',
            op='curve',
            amp_frac=AMP['infraclavicular_fossa'],
            points=fossa,
            aspect=fasp,
            min_dot=0.15,
            anchor='0.022 of stature inferior and 0.004 anterior of the lateral '
            '45%% of the clavicle crest. CONSTRUCTED: the rig has no bone '
            'here and no morph support names the fossa.',
            probes=('deltopectoral_triangle',),
        )
    )

    # 1c jugular notch (midline) and supraclavicular fossa
    hL = ctx.bone('clavicle.L')[0]
    notch = np.array([[0.0, hL[1], hL[2] + 0.004 * S]])
    F.append(
        dict(
            name='jugular_notch',
            claim='constructed',
            op='point',
            amp_frac=AMP['jugular_notch'],
            points=notch,
            midline=True,
            aspect=_unit(np.array([0.0, -1.0, 0.10])),
            min_dot=0.20,
            anchor='midline at the height of the sternoclavicular joints '
            '(clavicle bone heads) + 0.004 of stature. CONSTRUCTED: the rig '
            'has no sternum bone.',
            probes=('sternal_end',),
        )
    )
    mid = pts[int(0.15 * (len(pts) - 1)) : int(0.55 * (len(pts) - 1)) + 1]
    supra, sasp = _curve(mid + np.array([0.0, 0.002, 0.017]) * S, _unit(np.array([0.0, -0.30, 0.95])), S)
    F.append(
        dict(
            name='supraclavicular_fossa',
            claim='constructed',
            op='curve',
            amp_frac=AMP['supraclavicular_fossa'],
            points=supra,
            aspect=sasp,
            min_dot=0.15,
            anchor='0.017 of stature superior to the MEDIAL HALF (arc 0.15-0.55) '
            "of the clavicle crest. CONSTRUCTED. This is A4S's "
            '"L-triangle", the second of the two clavicular regions they say '
            'stay visible at any build. It is deliberately kept off the '
            'lateral third: extended to arc 0.72 it reached into the '
            "acromion probe's own patch and inverted that probe's sign on "
            'the female original (+5.52 mm -> -4.12 mm). Measured, then '
            'shortened to the anatomy.',
            probes=('l_triangle',),
        )
    )
    return F


def acromion_records(ctx):
    """The acromion / AC corner: the clavicle bone TAIL nudged superolaterally."""
    S = ctx.S
    # ---- 7  acromion / AC corner -------------------------------------------------
    acr = ctx.bone('clavicle.L')[1]
    return [
        dict(
            name='acromion',
            claim='bone',
            op='point',
            amp_frac=AMP['acromion'],
            points=np.array([acr + np.array([0.004, 0.0, 0.004]) * S]),
            aspect=_unit(np.array([0.45, -0.20, 0.87])),
            min_dot=0.15,
            anchor='clavicle.L/R bone TAIL = shoulder01 head, i.e. the acromial end '
            'of the clavicle, nudged 0.004 of stature superolaterally',
            probes=('acromion',),
        )
    ]


def arm_records(ctx):
    """The elbow and forearm records: olecranon, ulnar_head and the ulnar_border
    curve between them, on aspects derived from the rig alone."""
    F = []
    S = ctx.S

    # ---- 2  elbow and forearm ----------------------------------------------------
    post = _elbow_posterior(ctx)
    ole = ctx.bone('lowerarm01.L')[0]
    F.append(
        dict(
            name='olecranon',
            claim='bone',
            op='point',
            amp_frac=AMP['olecranon'],
            points=np.array([ole]),
            aspect=post,
            min_dot=0.20,
            anchor='lowerarm01.L/R bone HEAD (the elbow joint centre), on the '
            'extensor aspect derived from the rig as the outside of the '
            'upperarm-forearm angle: (%.3f, %.3f, %.3f)' % tuple(post),
            probes=('olecranon',),
        )
    )
    pu = _wrist_postero_ulnar(ctx)
    uh = ctx.bone('lowerarm02.L')[1]
    F.append(
        dict(
            name='ulnar_head',
            claim='bone',
            op='point',
            amp_frac=AMP['ulnar_head'],
            points=np.array([uh]),
            aspect=pu,
            min_dot=0.15,
            anchor='lowerarm02.L/R bone TAIL (the distal forearm), on the '
            'postero-ulnar aspect derived from the rig as metacarpal4_tail '
            '- metacarpal1_tail with the forearm axis removed: '
            '(%.3f, %.3f, %.3f). metacarpal4 is the FIFTH metacarpal on this '
            "rig — its tail is finger5-1's head — so the direction is ulnar "
            'by measurement, not by assumption.' % tuple(pu),
            probes=('ulnar_head',),
        )
    )
    ts = np.linspace(0.06, 0.94, ULNAR_BORDER_N_STATIONS)[:, None]
    border = ole[None] * (1 - ts) + uh[None] * ts
    baspect = np.array([_unit(post * (1 - float(t)) + pu * float(t)) for t in ts])
    border, baspect = _curve(border, baspect, S)
    F.append(
        dict(
            name='ulnar_border',
            claim='bone',
            op='curve',
            amp_frac=AMP['ulnar_border'],
            points=border,
            aspect=baspect,
            min_dot=0.15,
            anchor='the segment from the olecranon (lowerarm01 head) to the head of '
            'the ulna (lowerarm02 tail), on an aspect interpolated between '
            'the two. CONTINUITY IS THE GATE and polarity is not — the '
            'reference says this border reads as a ridge OR a furrow '
            'depending on rotation, so it is probed with polarity=either.',
            probes=('ulnar_head', 'olecranon'),
        )
    )
    return F


def ankle_and_shank_records(ctx):
    """The two malleoli, the anteromedial tibial facet and the fibula-shaft
    negative control. One builder because the facet strip runs from the knee to
    the medial malleolus anchor this function places."""
    F = []
    S = ctx.S

    # ---- 3  ankle ----------------------------------------------------------------
    ank = ctx.bone('foot.L')[0]
    med = ank + np.array([0.0, 0.0, +0.5 * MALLEOLUS_HEIGHT_OFFSET_FRAC * S])
    latp = ank + np.array([0.0, MALLEOLUS_LAT_POSTERIOR_FRAC * S, -0.5 * MALLEOLUS_HEIGHT_OFFSET_FRAC * S])
    F.append(
        dict(
            name='malleolus_med',
            claim='bone',
            op='point',
            amp_frac=AMP['malleolus_med'],
            points=np.array([med]),
            aspect=np.array([-1.0, 0.0, 0.0]),
            min_dot=0.20,
            anchor='foot.L/R bone HEAD = the ankle joint centre, 0.003 of stature '
            'ABOVE it, on the medial aspect. The bone head sits at %.4f of '
            'stature; ANSUR II puts the lateral malleolus at 0.0415 (male) / '
            '0.0385 (female), so the anchor is anthropometrically consistent '
            'without being fitted to it.' % ((ank[2] - ctx.z0) / S),
            extra={'apex_above_lateral_frac': MALLEOLUS_HEIGHT_OFFSET_FRAC},
            probes=('malleolus_med',),
        )
    )
    F.append(
        dict(
            name='malleolus_lat',
            claim='bone',
            op='point',
            amp_frac=AMP['malleolus_lat'],
            points=np.array([latp]),
            aspect=np.array([+1.0, 0.0, 0.0]),
            min_dot=0.20,
            anchor='foot.L/R bone HEAD, 0.003 of stature BELOW it and %.3f of '
            'stature posterior, on the lateral aspect' % MALLEOLUS_LAT_POSTERIOR_FRAC,
            probes=('malleolus_lat',),
        )
    )

    # 3c anteromedial tibial facet + the fibula-shaft negative control
    knee = ctx.bone('lowerleg01.L')[0]
    tibs = np.linspace(0.10, 0.92, 60)[:, None]
    tib = knee[None] * (1 - tibs) + med[None] * tibs
    tib, tasp = _curve(tib, _unit(np.array([-0.50, -0.86, 0.0])), S)
    F.append(
        dict(
            name='tibial_facet',
            claim='bone',
            op='facet',
            amp_frac=0.0,
            points=tib,
            aspect=tasp,
            min_dot=0.20,
            anchor='the anteromedial strip of the shank, from lowerleg01.L/R head '
            '(the knee joint centre) to the medial malleolus anchor. A '
            'FACET, NOT A RIDGE: the subcutaneous medial surface of the '
            'tibia is a plane, so this feature PROJECTS the strip onto a '
            'ruled least-squares plane in its own (arc, aspect) frame, '
            'capped at %.4f of stature, instead of displacing.' % FACET_CAP_FRAC,
            extra={'curvature_target_frac_stature': TIBIAL_FACET_CURVATURE_TARGET_FRAC},
            probes=('tibial_tuberosity',),
        )
    )
    F.append(
        dict(
            name='fibula_control',
            claim='bone',
            op='control',
            amp_frac=0.0,
            points=tib.copy(),
            aspect=np.repeat(np.array([[+1.0, 0.0, 0.0]]), len(tib), 0),
            min_dot=0.20,
            anchor='the LATERAL strip of the same shank stations — the fibula '
            'shaft. NEGATIVE CONTROL: this layer must displace it by exactly '
            'zero. A relief change here would mean the tibial facet leaked '
            'around the leg.',
            probes=(),
        )
    )
    return F


def pelvis_records(ctx):
    """ASIS, the iliac crest curve and the PSIS pair — all three off the one
    azimuth sweep `_crest_points` returns, so an empty sweep yields NO pelvic
    records at all, exactly as the old `if len(cpts):` guard did."""
    F = []
    S = ctx.S

    # ---- 4  ASIS and the iliac crest ---------------------------------------------
    cpts, cdirs, cfrac, a0deg, _ = _crest_points(ctx)
    if len(cpts):
        F.append(
            dict(
                name='asis',
                claim='constructed',
                op='point',
                amp_frac=AMP['asis'],
                points=cpts[:1],
                aspect=_unit(cdirs[0] + np.array([0.0, -0.5, 0.0])),
                min_dot=0.15,
                anchor='the ANTERIOR TERMINUS of the iliac crest arc (azimuth '
                '%.0f deg from anterior), which is what the anterior '
                'superior iliac spine anatomically IS. Height from ANSUR II '
                'iliocristale/stature = %.4f (%s) minus a HOUSE anterior '
                'drop of %.3f. CONSTRUCTED: this rig has no pelvic bone '
                'beyond pelvis.L/R, which is the hip joint.' % (a0deg, cfrac, ctx.sex(), CREST_DROP_ANTERIOR_FRAC),
                probes=('asis',),
            )
        )
        icp, ica = _curve(cpts, np.array([_unit(d + np.array([0.0, 0.0, 0.6])) for d in cdirs]), S)
        F.append(
            dict(
                name='iliac_crest',
                claim='constructed',
                op='curve',
                amp_frac=AMP['iliac_crest'],
                points=icp,
                aspect=ica,
                min_dot=0.10,
                anchor='%d stations swept in azimuth %.0f-%.0f deg about the pelvic '
                'axis at the ANSUR II iliocristale height (%.4f of stature, '
                '%s), each taken as the outermost surface point in that '
                'direction. CONSTRUCTED arc, MEASURED height.'
                % (len(icp), CREST_AZIMUTH_DEG[0], CREST_AZIMUTH_DEG[1], cfrac, ctx.sex()),
                probes=('asis',),
            )
        )
        # ---- 5  PSIS: a PAIR OF PITS, sign matters -------------------------------
        zp = ctx.z0 + (cfrac - PSIS_BELOW_CREST_FRAC) * S
        yb = ctx.v[ctx.shell & (np.abs(ctx.v[:, 2] - zp) < 0.010 * S) & (np.abs(ctx.v[:, 0]) < 0.06 * S), 1]
        ypsis = float(yb.max()) if len(yb) else float(ctx.bone('pelvis.L')[0][1])
        F.append(
            dict(
                name='psis',
                claim='constructed',
                op='point',
                amp_frac=AMP['psis'],
                points=np.array([[PSIS_HALF_SEPARATION_FRAC * S, ypsis, zp]]),
                aspect=_unit(np.array([0.25, 1.0, 0.0])),
                min_dot=0.15,
                anchor='+/-%.3f of stature from the midline, %.3f of stature below '
                'the ANSUR iliocristale height, on the posterior aspect. '
                'A PAIR OF PITS: sign matters, a bump test at PSIS is wrong '
                'even on a perfect body. CONSTRUCTED, and the sacral window '
                'of this cage is known to hold about 5 vertices — the report '
                'says whether the tessellation can carry it.' % (PSIS_HALF_SEPARATION_FRAC, PSIS_BELOW_CREST_FRAC),
                probes=('psis',),
            )
        )
    return F


def neck_records(ctx):
    """The cervicothoracic junction point the rig HAS (c7) and the midline
    nuchal furrow running down to it from the occipital protuberance."""
    F = []
    S = ctx.S

    # ---- 6  C7 and the nuchal furrow ---------------------------------------------
    c7 = ctx.bone('spine01')[1]
    F.append(
        dict(
            name='c7',
            claim='bone',
            op='point',
            midline=True,
            amp_frac=AMP['c7'],
            points=np.array([[0.0, float(c7[1]), float(c7[2])]]),
            aspect=_unit(np.array([0.0, 1.0, 0.15])),
            min_dot=0.20,
            anchor='spine01 TAIL = neck01 head, i.e. the cervicothoracic junction, '
            'on the midline posterior aspect. The rig has 4 cervical joints, '
            "not C3-C7's 5, so this is the junction the rig HAS, not C7 by "
            'name.',
            probes=(),
        )
    )
    eop = ctx.bone('head')[0] + np.array([0.0, 0.0, 0.030 * S])
    nt = np.linspace(0.08, 0.94, NUCHAL_N_STATIONS)[:, None]
    nuch = np.array([[0.0, 0.0, 0.0]]) + eop[None] * (1 - nt) + np.array([[0.0, float(c7[1]), float(c7[2])]]) * nt
    nuch[:, 0] = 0.0
    nuch, nasp = _curve(nuch, _unit(np.array([0.0, 1.0, 0.05])), S)
    F.append(
        dict(
            name='nuchal_furrow',
            claim='constructed',
            op='curve',
            midline=True,
            amp_frac=AMP['nuchal_furrow'],
            points=nuch,
            aspect=nasp,
            min_dot=0.20,
            anchor='midline channel from the external occipital protuberance '
            '(head bone head + 0.030 of stature) down to the C7 anchor. '
            'CONSTRUCTED: the rig has no occiput bone.',
            probes=(),
        )
    )
    return F
