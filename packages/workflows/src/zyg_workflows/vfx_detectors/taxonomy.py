# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ═══════════════════════════════════════════════════════════════════════════
# TAXONOMY BINDING
# ═══════════════════════════════════════════════════════════════════════════
# The taxonomy is deliberately finer-grained than the detectors: it names
# side_kick and roundhouse_kick separately, while the pose tier can only see
# "an ankle moving fast with the knee extending". Rather than coarsen the
# taxonomy or overclaim in the detector, each detector BINDS to the entries it
# provides evidence for, and says whether it can tell them apart:
#
#   * where the detector already computes the distinction (pan left vs right is
#     the sign of dx; a white impact frame vs a black one is the sign of the
#     luminance spike) a DISCRIMINATOR routes each event to the right entry and
#     the finding is exact.
#   * where it cannot (a kick is a kick), every bound entry receives the same
#     events flagged discriminated=False, and the ledger says so. The finding is
#     "something in this family happened here", which is true, instead of
#     "a roundhouse kick happened here", which would not be.
#
# An unbound detector keeps its own id and shows up as an orphan in the run log.

BINDINGS = {
    'anime_2d.impact_frame': ('anime_2d.impact_frame_white', 'anime_2d.impact_frame_black'),
    'anime_2d.speedlines': ('anime_2d.speedlines_parallel', 'anime_2d.speedlines_radial'),
    'body_action.crouch': ('body_action.crouch_lower',),
    'body_action.fall': ('body_action.fall_uncontrolled',),
    'body_action.gait': ('body_action.gait_cadence', 'body_action.walk_cycle'),
    'body_action.jump': ('body_action.jump_takeoff', 'body_action.jump_apex'),
    'body_action.kick': (
        'body_action.front_kick',
        'body_action.side_kick',
        'body_action.roundhouse_kick',
        'body_action.snap_kick_high',
    ),
    'body_action.punch': ('body_action.punch_straight', 'body_action.punch_hook', 'body_action.punch_uppercut'),
    'body_action.slap': ('body_action.slap_open_hand',),
    'camera.handheld_shake': ('camera.motion_handheld_shake',),
    'camera.letterbox_bars': ('camera.letterbox_bars_horizontal', 'camera.pillarbox_bars_vertical'),
    'camera.locked_off': ('camera.motion_static_locked',),
    'camera.pan': ('camera.motion_pan_left', 'camera.motion_pan_right'),
    'camera.roll': ('camera.motion_roll_axis',),
    'camera.tilt': ('camera.motion_tilt_up', 'camera.motion_tilt_down'),
    'camera.zoom': ('camera.motion_zoom_in', 'camera.motion_zoom_out'),
    'editing_time.animation_cadence': (
        'editing_time.cadence_on_ones',
        'editing_time.cadence_on_twos',
        'editing_time.cadence_on_threes',
        'editing_time.cadence_on_fours_or_slower',
    ),
    'editing_time.fade_black': ('editing_time.fade_to_black', 'editing_time.fade_from_black'),
    'editing_time.flash_frame': ('editing_time.flash_frame_transition',),
    'editing_time.held_cel': ('editing_time.held_cel_static',),
    'face_head.blink': ('face_head.blink_rate', 'face_head.blink_slow', 'face_head.blink_double'),
    'face_head.eyes_closed': ('face_head.eyes_closed_sustained',),
    'face_head.lip_movement': ('face_head.lip_sync_offset',),
    'face_head.mouth_open': ('face_head.mouth_open_binary',),
    'fluids_fire.fire_flicker': ('fluids_fire.flame_flicker_rate',),
    'fluids_fire.water_boiling': ('fluids_fire.water_body_present',),
    'fluids_fire.water_moving': ('fluids_fire.water_flow_direction', 'fluids_fire.water_body_present'),
    'hand_object.hand_to_mouth': ('hand_object.hand_to_mouth_transport',),
    'hand_object.pointing': ('hand_object.gesture_point_deictic', 'hand_object.gesture_point_target_direction'),
    'hand_object.pinch_grasp': ('hand_object.grasp_tip_pinch', 'hand_object.grasp_precision_pad_pinch'),
    'hand_object.press_contact': ('hand_object.button_press_physical', 'hand_object.contact_onset'),
    'interaction_social.proximity': ('interaction_social.proxemic_zone_intimate',),
    'lighting.flicker': ('lighting.flicker_amplitude', 'lighting.flicker_frequency'),
    'lighting.silhouette': ('lighting.silhouette_full', 'lighting.partial_silhouette'),
    'post_fx.banding': ('post_fx.banding_contours',),
    'post_fx.bloom': ('post_fx.bloom_present', 'post_fx.bloom_intensity'),
    'post_fx.chromatic_aberration': ('post_fx.chromatic_aberration_lateral',),
    'post_fx.film_grain': ('post_fx.film_grain_present',),
    'post_fx.halation': ('post_fx.halation_red_fringe',),
    'post_fx.vignette': ('post_fx.vignette_present', 'post_fx.vignette_strength'),
    'weather_atmos.clouds_moving': ('weather_atmos.cloud_coverage_fraction',),
}


def _disc_sign(key, pos, neg, invert=False):
    """Route by the sign of one evidence value."""

    def f(ev):
        v = float((ev.get('evidence') or {}).get(key, 0.0) or 0.0)
        if invert:
            v = -v
        return pos if v > 0 else neg

    return f


DISCRIMINATORS = {
    # cam_dx is how the IMAGE moves, so a camera panning RIGHT drags the image
    # LEFT and dx goes negative. Inverting here keeps the taxonomy id meaning
    # what a viewer would say out loud.
    'camera.pan': _disc_sign('pan_norm', 'camera.motion_pan_right', 'camera.motion_pan_left', invert=True),
    'camera.tilt': _disc_sign('tilt_norm', 'camera.motion_tilt_down', 'camera.motion_tilt_up', invert=True),
    'camera.zoom': _disc_sign('zoom_delta', 'camera.motion_zoom_in', 'camera.motion_zoom_out'),
    'anime_2d.impact_frame': lambda ev: (
        'anime_2d.impact_frame_white'
        if (ev.get('evidence') or {}).get('polarity') == 'white'
        else 'anime_2d.impact_frame_black'
    ),
    # The cadence detector already measured the mean hold, so it can name the
    # exact cadence entry rather than claiming the whole family.
    'editing_time.animation_cadence': lambda ev: (
        'editing_time.cadence_on_ones'
        if float((ev.get('evidence') or {}).get('mean_hold', 1) or 1) < 1.5
        else 'editing_time.cadence_on_twos'
        if float((ev.get('evidence') or {}).get('mean_hold', 1) or 1) < 2.5
        else 'editing_time.cadence_on_threes'
        if float((ev.get('evidence') or {}).get('mean_hold', 1) or 1) < 3.5
        else 'editing_time.cadence_on_fours_or_slower'
    ),
    'camera.letterbox_bars': lambda ev: (
        'camera.letterbox_bars_horizontal'
        if (ev.get('evidence') or {}).get('letterboxed')
        else 'camera.pillarbox_bars_vertical'
    ),
}


def bind(tid, events):
    """Split one detector's results across the taxonomy entries it serves.

    Returns [(taxonomy_id, events, discriminated)]."""
    targets = BINDINGS.get(tid)
    if not targets:
        return [(tid, events, True)]
    disc = DISCRIMINATORS.get(tid)
    if disc and events:
        routed = {t: [] for t in targets}
        for e in events:
            try:
                t = disc(e)
            except (TypeError, ValueError, KeyError):
                t = targets[0]
            routed.setdefault(t, []).append(dict(e, id=t))
        return [(t, routed.get(t, []), True) for t in routed]
    # cannot tell the family members apart — every one gets the same evidence,
    # and the ledger is told the finding is undiscriminated
    return [(t, [dict(e, id=t) for e in events], len(targets) == 1) for t in targets]
