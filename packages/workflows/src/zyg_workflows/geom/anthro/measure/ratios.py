# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The ratio vector the reference pack compares against.

Moved verbatim out of the old single-file measure.py (lines 3123-3342).
"""

from zyg_workflows.geom.anthro.measure.record import HULL_CONVENTION


def _ratios(M, H):
    """Stature-relative ratios and the dimensionless indices, keyed to reference-pack
    ratio names WHERE AND ONLY WHERE the definition genuinely matches."""

    def val(k, field='value_mm'):
        r = M.get(k)
        if not r:
            return None
        x = r.get(field)
        return None if x is None else float(x)

    out = {}
    Hmm = H * 1000.0

    def put(key, num_key, use_horizontal=False):
        r = M.get(num_key)
        if not r:
            return
        x = r.get('horizontal_mm') if use_horizontal else r.get('value_mm')
        if x is None:
            return
        out[key] = {
            'value': x / Hmm,
            'numerator_mm': x,
            'from': num_key,
            'convention': ('ANSUR horizontal-tape variant' if use_horizontal else r.get('convention')),
            'landmark': r.get('landmark'),
            'iso_class': r.get('iso_class'),
            'survey_comparable': r.get('survey_comparable', True),
            'survey_not_comparable_because': r.get('survey_not_comparable_because'),
        }
        # The window caveat travels with the ratio, because the ratio is what a band gate
        # reads. A number that is a property of its search window rather than of the body
        # must not arrive at a gate stripped of that fact. For the horizontal-tape ratios
        # the relevant scan is the HORIZONTAL one — the perpendicular record's flags
        # describe a plane this ratio was not built from.
        if use_horizontal:
            ew, sc = r.get('horizontal_endpoint_warning'), r.get('horizontal_scan')
        else:
            ew, sc = r.get('endpoint_warning'), r.get('scan')
        if ew:
            out[key]['endpoint_warning'] = ew
            # report.py copies a ratio record's 'note' into the persisted row, and the
            # measurements block is NOT persisted at all — so 'note' is the only channel
            # by which this caveat reaches the shipped anthro_report.json instead of dying
            # in a live dict.
            out[key]['note'] = (
                (out[key].get('note') + ' || ') if out[key].get('note') else ''
            ) + 'WINDOW CAVEAT on the numerator: %s' % ew
        at = r.get('at_window_endpoint') if not use_horizontal and sc is None else (sc or {}).get('at_window_endpoint')
        if at is not None:
            out[key]['at_window_endpoint'] = bool(at)
        # The pose bias travels with the ratio, in BOTH units, so a band check can widen
        # by it instead of throwing the check away. Absent for the horizontal-tape
        # variants, whose numerator is a different plane from the one the bias was
        # measured on.
        if not use_horizontal and r.get('a_pose_bias_mm') is not None:
            out[key]['a_pose_bias_mm'] = r['a_pose_bias_mm']
            out[key]['a_pose_bias_ratio'] = r['a_pose_bias_mm'] / Hmm
            out[key]['a_pose_bias_note'] = r.get('a_pose_bias_note')
        if r.get('arm_mask') is not None:
            am = r['arm_mask']
            out[key]['arm_mask'] = {
                'applied': am.get('applied'),
                'contour_points_dropped': am.get('contour_points_dropped'),
                'max_arm_weight_on_section': am.get('max_arm_weight_on_section'),
                'changed_the_value': am.get('changed_the_value'),
            }

    for k, src in (
        ('acromial_height_over_stature', 'acromial_height'),
        ('suprasternale_height_over_stature', 'suprasternale_height'),
        ('waist_height_omphalion_over_stature', 'waist_height_omphalion'),
        ('trochanterion_height_over_stature', 'trochanterion_height'),
        ('buttock_height_over_stature', 'buttock_height'),
        ('crotch_height_over_stature', 'crotch_height'),
        ('tibiale_height_over_stature', 'tibiale_height'),
        ('cervicale_height_over_stature', 'cervicale_height_house'),
        ('hand_length_over_stature', 'hand_length'),
        ('foot_length_over_stature', 'foot_length'),
        ('neck_circumference_over_stature', 'neck_circumference'),
        ('shoulder_circumference_over_stature', 'shoulder_circumference'),
        ('chest_circumference_over_stature', 'chest_circumference'),
        ('waist_circumference_omphalion_over_stature', 'waist_circumference_omphalion'),
        ('buttock_circumference_over_stature', 'buttock_circumference'),
        ('head_circumference_over_stature', 'head_circumference'),
        ('bideltoid_breadth_over_stature', 'bideltoid_breadth'),
        ('chest_breadth_over_stature', 'chest_breadth'),
        ('waist_breadth_over_stature', 'waist_breadth_omphalion'),
        ('hip_breadth_over_stature', 'hip_breadth'),
        ('head_breadth_over_stature', 'head_breadth'),
        ('chest_depth_over_stature', 'chest_depth'),
        ('buttock_depth_over_stature', 'buttock_depth'),
        ('head_length_over_stature', 'head_length'),
    ):
        put(k, src)
    for k, src in (
        ('thigh_circumference_over_stature', 'thigh_circumference_r'),
        ('calf_circumference_over_stature', 'calf_circumference_r'),
        ('wrist_circumference_over_stature', 'wrist_circumference_r'),
    ):
        put(k, src, use_horizontal=(k != 'wrist_circumference_over_stature'))

    def index_bias(rec, num_key, den_key):
        """Carry the A-pose bias through a ratio of two measurements.

        A ratio of two A-posed numbers is not rescued by being a ratio: both the numerator
        and the denominator move. This shifts each by its own measured bias and reports
        what the index becomes, rather than leaving the caller to assume the pose cancels.
        """
        n, d = M.get(num_key) or {}, M.get(den_key) or {}
        bn, bd = n.get('a_pose_bias_mm'), d.get('a_pose_bias_mm')
        if bn is None or bd is None or not n.get('value_mm') or not d.get('value_mm'):
            return
        if bn == 0.0 and bd == 0.0:
            rec['a_pose_bias_value'] = 0.0
            rec['a_pose_bias_note'] = 'exactly zero: neither section carries any arm skinning weight'
            return
        shifted = (n['value_mm'] + bn) / (d['value_mm'] + bd)
        rec['arms_down_value'] = shifted
        rec['a_pose_bias_value'] = shifted - rec['value']
        rec['a_pose_bias_note'] = (
            'both components shifted by their own measured lower-bound pose bias '
            '(%s %+.2f mm, %s %+.2f mm). Reported, not applied.' % (num_key, bn, den_key, bd)
        )

    def flags(*keys):
        """An index inherits every survey caveat of the measurements it is built from —
        a ratio of two pose-invalid numbers is not rescued by being a ratio."""
        bad = [
            (k, M[k].get('survey_not_comparable_because'))
            for k in keys
            if M.get(k) and M[k].get('survey_comparable') is False
        ]
        if not bad:
            return {'survey_comparable': True, 'survey_not_comparable_because': None}
        return {
            'survey_comparable': False,
            'survey_not_comparable_because': '; '.join('%s: %s' % (k, r) for k, r in bad),
        }

    waist = val('waist_circumference_omphalion')
    butt = val('buttock_circumference')
    if waist and butt:
        out['waist_hip_circumference'] = {
            'value': waist / butt,
            'from': 'waist(omphalion)/buttock circumference',
            'convention': HULL_CONVENTION,
            'landmark': 'omphalion over maximum buttock protrusion',
            **flags('waist_circumference_omphalion', 'buttock_circumference'),
            'note': 'WHR at the ANSUR site. The reference pack ships this DISTRIBUTION '
            'only; the "0.7 ideal" sits near the 0.5th percentile of real women '
            'and is not a target.',
        }
        index_bias(out['waist_hip_circumference'], 'waist_circumference_omphalion', 'buttock_circumference')
    if waist:
        out['waist_over_stature'] = {
            'value': waist / Hmm,
            'from': 'waist(omphalion)/stature',
            'convention': HULL_CONVENTION,
            'landmark': 'omphalion',
            **flags('waist_circumference_omphalion'),
        }
    sh = val('shoulder_circumference')
    if sh and waist:
        out['shoulder_waist_circumference'] = {
            'value': sh / waist,
            'from': 'shoulder/waist(omphalion) circumference',
            'convention': HULL_CONVENTION,
            'landmark': 'deltoids over omphalion',
            **flags('shoulder_circumference', 'waist_circumference_omphalion'),
            'note': 'Reported as a measured distribution position ONLY. The "Adonis 1.618" '
            'has no primary source and is not a target.',
        }
        index_bias(out['shoulder_waist_circumference'], 'shoulder_circumference', 'waist_circumference_omphalion')
    bd, hb = val('bideltoid_breadth'), val('hip_breadth')
    if bd and hb:
        out['bideltoid_over_hipbreadth'] = {
            'value': bd / hb,
            'from': 'bideltoid/hip breadth',
            'convention': 'cross-section extents',
            'landmark': 'deltoid over hip',
            **flags('bideltoid_breadth', 'hip_breadth'),
        }
        index_bias(out['bideltoid_over_hipbreadth'], 'bideltoid_breadth', 'hip_breadth')
    hl, hbr = val('head_length'), val('head_breadth')
    if hl and hbr:
        out['cephalic_index'] = {
            'value': 100.0 * hbr / hl,
            'units': 'x100',
            'from': 'head breadth/length x100',
            'convention': 'cross-section extents on a BALD cage',
            'landmark': 'cranium above the ears',
            **flags('head_length', 'head_breadth'),
            'note': 'ANSUR measures head dimensions OVER HAIR, so this is not directly comparable to the pack band.',
        }
    fl, hnd = val('foot_length'), val('hand_length')
    if fl and hnd:
        out['foot_over_hand_length'] = {
            'value': fl / hnd,
            'from': 'foot/hand length',
            'convention': 'landmark chords',
            'landmark': 'pternion-acropodion over wrist ring-dactylion',
            **flags('foot_length', 'hand_length'),
            'note': 'Growth is distal-to-proximal, so this index is one of the few that '
            'separates a child from a scaled-down adult.',
        }
    bmi = M.get('derived_bmi', {}).get('value')
    if bmi is not None:
        out['bmi'] = {
            'value': bmi,
            'units': 'kg/m^2',
            'from': 'assumed-density mass',
            'convention': 'DERIVED WITH A DENSITY ASSUMPTION',
            'landmark': None,
            'note': 'not comparable like-for-like to the pack BMI, which comes from weighed subjects',
        }
    return out
