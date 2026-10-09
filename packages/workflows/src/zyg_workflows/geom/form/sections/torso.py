# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.torso — t5_torso_sections — AFS p.24.

Moved verbatim from geom/form/sections.py; no logic, numbers or comments changed.
"""

import numpy as np

from .constants import (
    CANON,
    FAIL,
    PASS,
    RELIEF_NULL_FRAC,
    REPORT,
    SRC_NULL,
    SRC_TORSO,
    UNMEASURABLE,
)

from .primitives import (
    _frame,
    _hull_gaps,
    _res,
    _rollup,
    _section,
    _split_front_back,
    _torso_section_valid,
)

# =================================================================================
# t5_torso_sections — AFS p.24
# =================================================================================
# The five levels. Four are resolved ANSUR/ISO landmarks that landmarks.py places from
# MakeHuman's own morph supports; one is CONSTRUCTED as the midpoint of two of them and
# says so, because this cage HAS no tenth rib and no costal margin (landmarks.py resolves
# neither) and inventing a rib level would be exactly the fabrication that file refuses.
TORSO_LEVELS = (
    dict(name='suprasternale', kind='landmark', landmark='suprasternale', about='upper thorax / manubrium'),
    dict(name='thelion', kind='landmark', landmark='thelion_r', about='mid thorax, bustpoint level'),
    dict(
        name='lower_thorax',
        kind='midpoint',
        between=('thelion_r', 'omphalion'),
        about='CONSTRUCTED: midway between the bustpoint and the navel. This is the '
        'costal-margin region, and it is constructed rather than resolved because '
        'landmarks.py reports the tenth rib UNRESOLVED on this cage — there is no '
        'costal margin to anchor to.',
    ),
    dict(name='omphalion', kind='landmark', landmark='omphalion', about='navel; the ANSUR II waist site'),
    dict(
        name='gluteal',
        kind='landmark',
        landmark='buttock',
        about='maximum posterior protrusion; the level AFS p.24 shows the gluteal cleft at',
    ),
)


def t5_torso_sections(v, faces, lm, stature_m=None, zmin=None):
    """Sign and count tests on five horizontal torso sections. AFS p.24.

    THREE CLAIMS, and they are of three different kinds:
      width > depth                 a SIGN test, per level.
      front flatter than back       an ORDERING test, per level, on the median normalised
                                    curvature of the two arcs (see _split_front_back for
                                    why that reading and not the other two, which are
                                    reported beside it).
      >= 1 concavity at the gluteal an INTEGER COUNT, with the count's floor set by the
      slice                         cage's measured relief null and by nothing else.

    This is the gate the linear engine cannot have. A tube of the right circumference passes
    every girth band; it fails "width > depth" only if it is round, and it fails the gluteal
    concavity count always, because a tube has no cleft.
    """
    if stature_m is None or zmin is None:
        zmin, stature_m = _frame(v)
    floor = RELIEF_NULL_FRAC * stature_m
    levels = []
    for spec in TORSO_LEVELS:
        rec = {'level': spec['name'], 'about': spec['about'], 'kind': spec['kind']}
        if spec['kind'] == 'landmark':
            r = lm.get(spec['landmark']) or {}
            fr = r.get('frac_stature')
            rec['anchor'] = spec['landmark']
            rec['anchor_confidence'] = r.get('confidence')
        else:
            fs = [(lm.get(n) or {}).get('frac_stature') for n in spec['between']]
            fr = None if any(x is None for x in fs) else 0.5 * (fs[0] + fs[1])
            rec['anchor'] = 'midpoint(%s)' % ', '.join(spec['between'])
            rec['anchor_confidence'] = 'constructed'
        if fr is None:
            rec.update(
                status=UNMEASURABLE,
                why='the anchoring landmark is UNRESOLVED on this mesh, so there is '
                'no defensible height for this level. landmarks.py refuses to '
                'approximate it and so does this.',
            )
            levels.append(rec)
            continue
        rec['frac_stature'] = float(fr)
        sec, err = _section(
            v,
            faces,
            np.array([0.0, 0.0, zmin + fr * stature_m]),
            np.array([0.0, 0.0, 1.0]),
            np.array([1.0, 0.0, 0.0]),
            select='largest',
        )
        if sec is None:
            rec.update(status=UNMEASURABLE, why=err['reason'])
            levels.append(rec)
            continue
        ok, why = _torso_section_valid(sec)
        rec['loops_found'] = sec['loops_found']
        rec['arm_loops_present'] = sec['arm_loops_present']
        rec['arm_points_dropped'] = sec['arm_points_dropped']
        # Descriptive, derived, no threshold. A plane that cuts both arms as loops of their
        # own is passing through the thorax beside the arms; a plane that cuts no arm
        # surface at all is either above the shoulder joint or below the fingertips, and
        # WHICH of those is settled by an ordering against the resolved thelion landmark —
        # no free parameter. It matters: the female original's suprasternale level sits
        # above the shoulder joint and sections the shoulder yoke, 241 x 116 mm against
        # 322 x 239 mm one level lower, so a reader has to be able to see what kind of
        # section produced a number before comparing it to the level below.
        thel = (lm.get('thelion_r') or {}).get('frac_stature')
        if sec['arm_loops_present'] >= 2:
            kind = 'thoracic: both arms cut as loops of their own'
        elif sec['arm_triangles_in_loop']:
            kind = 'mixed: arm surface inside the loop'
        elif thel is not None and fr > thel:
            kind = (
                'above the shoulder joint — no arm surface at this plane, so this is a '
                'SHOULDER-YOKE section, not a thoracic one'
            )
        else:
            kind = 'no arm surface at this plane (below the fingertips)'
        rec['section_kind'] = kind
        if not ok:
            rec.update(status=UNMEASURABLE, why='REFUSED: ' + why)
            levels.append(rec)
            continue
        xy = sec['xy']
        width = float(xy[:, 0].max() - xy[:, 0].min())
        depth = float(xy[:, 1].max() - xy[:, 1].min())
        rec['width_mm'] = width * 1000
        rec['depth_mm'] = depth * 1000
        rec['width_over_depth'] = width / depth if depth > 0 else None
        rec['width_gt_depth'] = bool(width > depth)
        fb = _split_front_back(xy)
        if fb is None:
            rec['front_flatter'] = None
            rec['front_flatter_why'] = 'the section has no distinct widest pair'
        else:
            f, b = fb['front'], fb['back']
            rec['front_median_curv'] = f['median_norm_curvature']
            rec['back_median_curv'] = b['median_norm_curvature']
            rec['front_camber'] = f['camber']
            rec['back_camber'] = b['camber']
            rec['front_fullness'] = f['fullness']
            rec['back_fullness'] = b['fullness']
            if f['median_norm_curvature'] is None or b['median_norm_curvature'] is None:
                rec['front_flatter'] = None
            else:
                rec['front_flatter'] = bool(f['median_norm_curvature'] < b['median_norm_curvature'])
            rec['front_flatter_by_camber'] = bool(f['camber'] < b['camber'])
            rec['front_flatter_by_fullness'] = bool(f['fullness'] > b['fullness'])
            rec['readings_agree'] = bool(
                rec['front_flatter'] == rec['front_flatter_by_camber'] == rec['front_flatter_by_fullness']
            )
        gaps, gerr = _hull_gaps(xy, floor)
        if gaps is None:
            rec['concavities'] = None
            rec['concavity_error'] = gerr
        else:
            rec['concavities_resolved'] = gaps['n_resolved']
            rec['concavities_all'] = gaps['n_all']
            rec['deepest_concavity_mm'] = gaps['all'][0]['depth_m'] * 1000 if gaps['all'] else 0.0
            if gaps['resolved']:
                apex = gaps['resolved'][0]['apex_uw']
                cen = xy.mean(axis=0)
                rec['deepest_concavity_posterior'] = bool(apex[1] > cen[1])
                rec['deepest_concavity_offset_from_midline_mm'] = abs(apex[0]) * 1000
        rec['status'] = REPORT
        levels.append(rec)

    resolved = [r for r in levels if r.get('status') != UNMEASURABLE]
    out = {}

    # --- claim 1: width > depth --------------------------------------------------
    got = [r for r in resolved if r.get('width_gt_depth') is not None]
    bad = [r['level'] for r in got if not r['width_gt_depth']]
    out['width_gt_depth'] = _res(
        UNMEASURABLE if not got else (FAIL if bad else PASS),
        'at every torso level the medio-lateral width exceeds the antero-posterior depth',
        SRC_TORSO,
        CANON,
        (
            'no torso level resolved on this mesh'
            if not got
            else (
                'width <= depth at %s' % ', '.join(bad) if bad else 'width > depth at all %d resolved levels' % len(got)
            )
        ),
        levels_resolved=len(got),
        levels_declared=len(TORSO_LEVELS),
        failed=bad,
        ratio_by_level={r['level']: r['width_over_depth'] for r in got},
    )

    # --- claim 2: the front contour is flatter than the back ---------------------
    got2 = [r for r in resolved if r.get('front_flatter') is not None]
    bad2 = [r['level'] for r in got2 if not r['front_flatter']]
    dis = [r['level'] for r in got2 if not r.get('readings_agree')]
    out['front_flatter_than_back'] = _res(
        UNMEASURABLE if not got2 else (FAIL if bad2 else PASS),
        'the anterior arc of each torso section is flatter than the posterior arc',
        SRC_TORSO,
        CANON,
        (
            'no torso level resolved on this mesh'
            if not got2
            else (
                'the anterior arc is NOT flatter at %s (verdict on median normalised curvature; '
                'the camber and fullness readings are reported per level and disagree at %s)'
                % (', '.join(bad2), ', '.join(dis) or 'no level')
                if bad2
                else 'the anterior arc is flatter at all %d resolved levels' % len(got2)
            )
        ),
        verdict_reading='median normalised Menger curvature of each arc, semicircle = 1.0',
        why_this_reading=(
            'AFS p.24 makes a claim about the CONTOUR. Camber (sagitta over '
            'chord) answers a depth question instead and is dominated by '
            'breast and buttock projection; fullness answers a bounding-box '
            'question and cannot separate a flat arc with rounded shoulders '
            'from a shallow round one. All three are reported.'
        ),
        failed=bad2,
        readings_disagree_at=dis,
        by_level={
            r['level']: {
                'front': r['front_median_curv'],
                'back': r['back_median_curv'],
                'camber_front_lt_back': r['front_flatter_by_camber'],
                'fullness_front_gt_back': r['front_flatter_by_fullness'],
            }
            for r in got2
        },
    )

    # --- claim 3: at least one concavity at the gluteal slice --------------------
    glut = next((r for r in levels if r['level'] == 'gluteal'), None)
    if glut is None or glut.get('concavities_resolved') is None:
        out['gluteal_concavity'] = _res(
            UNMEASURABLE,
            'the gluteal section carries at least one concavity',
            SRC_TORSO,
            CANON,
            'the gluteal level did not resolve: %s' % (glut or {}).get('why', 'no level'),
        )
    else:
        n = glut['concavities_resolved']
        out['gluteal_concavity'] = _res(
            PASS if n >= 1 else FAIL,
            "the gluteal section carries at least one concavity deeper than the cage's own relief null",
            SRC_TORSO + ' + ' + SRC_NULL,
            CANON,
            (
                '%d concavit%s deeper than %.2f mm; deepest %.2f mm%s'
                % (
                    n,
                    'y' if n == 1 else 'ies',
                    floor * 1000,
                    glut['deepest_concavity_mm'],
                    (
                        ', posterior'
                        if glut.get('deepest_concavity_posterior')
                        else ', ANTERIOR — a posterior cleft was expected'
                    )
                    if 'deepest_concavity_posterior' in glut
                    else '',
                )
                if n
                else 'no concavity deeper than the %.2f mm relief null; the deepest dip is %.2f mm, '
                "i.e. this section is convex to within the cage's own measurement noise — a "
                'tube' % (floor * 1000, glut['deepest_concavity_mm'])
            ),
            count=n,
            floor_mm=floor * 1000,
            deepest_mm=glut['deepest_concavity_mm'],
            deepest_is_posterior=glut.get('deepest_concavity_posterior'),
            deepest_offset_from_midline_mm=glut.get('deepest_concavity_offset_from_midline_mm'),
            unresolved_dips=glut['concavities_all'] - n,
        )

    return {
        'gate': 't5_torso_sections',
        'source': SRC_TORSO,
        'provenance': CANON,
        'levels': levels,
        'claims': out,
        'status': _rollup(out),
    }
