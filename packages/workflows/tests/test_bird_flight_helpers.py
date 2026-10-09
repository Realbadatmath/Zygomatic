# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the checks extracted out of ``_bird_flies_away``.

Every helper exercised here used to be a block inside one 369-line function,
so each of these is the first time that statement about the flight has been
checked on its own. All of them are pure: plain dicts and numpy arrays in, a
verdict and printed ``[verify]`` lines out — no GPU, no network, no services.
"""

import sys
import types

import numpy as np
import pytest


def _import_checks():
    """Import the v27 check helpers behind a temporary ``soundfile`` stub.

    The v27 package's shared import block pulls in ``soundfile``, which is not
    installed in this environment and which none of the checks below touch.
    The stub is withdrawn again straight away: left in ``sys.modules`` it
    makes every other test module's ``importorskip('soundfile')`` succeed and
    then fail on the stub.
    """
    stub = types.ModuleType('soundfile')
    had = 'soundfile' in sys.modules
    if not had:
        sys.modules['soundfile'] = stub
    try:
        from zyg_workflows.run_scene_shores_v27 import bird_flight_checks

        return bird_flight_checks
    finally:
        if not had and sys.modules.get('soundfile') is stub:
            del sys.modules['soundfile']


_checks = _import_checks()
BirdFlightSamples = _checks.BirdFlightSamples
check_authoring = _checks.check_authoring
check_bank_clamp_run = _checks.check_bank_clamp_run
check_same_camera = _checks.check_same_camera
check_trajectory = _checks.check_trajectory
check_yaw_blend = _checks.check_yaw_blend


def _samples(xs, ys=None, scale=None, poses=None):
    """Build a :class:`BirdFlightSamples` from screen-space arrays."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.zeros_like(xs) if ys is None else np.asarray(ys, dtype=np.float64)
    scale = np.ones_like(xs) if scale is None else np.asarray(scale, dtype=np.float64)
    return BirdFlightSamples(
        poses=poses if poses is not None else [],
        xs=xs,
        ys=ys,
        scale=scale,
        inv_scale=[s and 1.0 / s for s in scale],
    )


def _good_flight():
    """A 241-sample flight that passes every positional check."""
    k = np.arange(241)
    # Enters right of frame, passes SHIP_AT (0.628, 0.470) mid-flight, and
    # exits off the left edge well before the end.
    xs = 1.10 - 1.30 * k / 240.0
    ys = 0.470 + 0.0 * k
    # A projected recession, so the size is already tiny by the time the
    # bird crosses back over x=0.40.
    scale = 1.0 / (1.0 + 9.0 * k / 240.0)
    return _samples(xs, ys, scale)


class TestCheckAuthoring:
    """Screen time, authoring space and sprite set."""

    def test_a_three_dimensional_eleven_second_flight_passes(self):
        cfg = {'path3d': [[0, 0, 0]], 'sprites': '/tmp/sprites'}
        assert check_authoring(cfg, 11.0) is True

    @pytest.mark.parametrize('dur', [4.0, 8.9, 13.1, 20.0])
    def test_screen_time_outside_the_nine_to_thirteen_band_fails(self, dur):
        cfg = {'path3d': [[0, 0, 0]], 'sprites': '/tmp/sprites'}
        assert check_authoring(cfg, dur) is False

    def test_a_flight_authored_in_image_space_fails(self):
        assert check_authoring({'sprites': '/tmp/sprites'}, 11.0) is False

    def test_the_drawn_bird_without_a_sprite_set_fails(self):
        assert check_authoring({'path3d': [[0, 0, 0]]}, 11.0) is False


class TestCheckSameCamera:
    """The invariant that makes the 3D honest."""

    def test_the_bird_camera_matching_the_water_camera_passes(self):
        fx = {'water': {'horizon': 0.41, 'vp_x': 0.52}}
        cfg = {'cam': {'horizon': 0.41, 'vp_x': 0.52}}
        assert check_same_camera(cfg, fx) is True

    def test_a_different_horizon_fails(self):
        fx = {'water': {'horizon': 0.41, 'vp_x': 0.52}}
        cfg = {'cam': {'horizon': 0.38, 'vp_x': 0.52}}
        assert check_same_camera(cfg, fx) is False

    def test_a_different_vanishing_point_fails(self):
        fx = {'water': {'horizon': 0.41, 'vp_x': 0.52}}
        cfg = {'cam': {'horizon': 0.41, 'vp_x': 0.60}}
        assert check_same_camera(cfg, fx) is False

    def test_no_bird_camera_at_all_fails(self):
        fx = {'water': {'horizon': 0.41, 'vp_x': 0.52}}
        assert check_same_camera({}, fx) is False


class TestCheckTrajectory:
    """Entry, the ship pass, the recession and the exit."""

    def test_the_reference_shaped_flight_passes(self):
        assert check_trajectory(_good_flight(), 11.0) is True

    def test_a_bird_that_starts_in_frame_does_not_enter(self):
        s = _good_flight()
        shifted = _samples(s.xs - 0.2, s.ys, s.scale)
        assert check_trajectory(shifted, 11.0) is False

    def test_a_flight_that_misses_the_boat_fails(self):
        s = _good_flight()
        away = _samples(s.xs, s.ys + 0.30, s.scale)
        assert check_trajectory(away, 11.0) is False

    def test_a_bird_that_grows_fails(self):
        s = _good_flight()
        growing = _samples(s.xs, s.ys, s.scale[::-1])
        assert check_trajectory(growing, 11.0) is False

    def test_a_bird_that_barely_shrinks_fails(self):
        s = _good_flight()
        flat = _samples(s.xs, s.ys, 1.0 - 0.10 * np.arange(241) / 240.0)
        assert check_trajectory(flat, 11.0) is False

    def test_a_near_size_frame_crossing_is_a_foreground_sweep(self):
        k = np.arange(241)
        # Crosses x=0.40 in the first fifth of the flight, still near-size.
        xs = 1.10 - 1.30 * (k / 240.0) ** 0.25
        ys = 0.470 + 0.0 * k
        scale = 1.0 - 0.85 * k / 240.0
        assert check_trajectory(_samples(xs, ys, scale), 11.0) is False

    def test_a_bird_that_never_exits_fails(self):
        k = np.arange(241)
        xs = 1.10 - 0.50 * k / 240.0
        ys = 0.470 + 0.0 * k
        scale = 1.0 - 0.85 * k / 240.0
        assert check_trajectory(_samples(xs, ys, scale), 11.0) is False

    def test_a_bird_that_comes_back_on_screen_fails(self):
        s = _good_flight()
        back = s.xs.copy()
        back[-1] = 0.20
        assert check_trajectory(_samples(back, s.ys, s.scale), 11.0) is False

    def test_grazing_the_edge_for_under_a_second_fails(self):
        k = np.arange(241)
        # Only the last ~0.4s sits past x=-0.02.
        xs = 1.10 - 1.13 * k / 240.0
        ys = 0.470 + 0.0 * k
        scale = 1.0 - 0.85 * k / 240.0
        assert check_trajectory(_samples(xs, ys, scale), 11.0) is False


class TestCheckBankClampRun:
    """The v27 check: the longest CONTINUOUS run pinned at the clamp."""

    def test_a_bank_that_never_reaches_the_clamp_passes(self):
        bank = np.full(241, -40.8)
        assert check_bank_clamp_run(bank, 11.0, 48.0) is True

    def test_the_v26_defect_one_point_one_continuous_seconds_fails(self):
        # v26: bit-identical -48.00 for 21 straight samples at 20 Hz, dead on
        # the ship pass. At 241 samples over 11 s that is 24 samples.
        bank = np.full(241, -40.0)
        bank[72:96] = -48.0
        assert check_bank_clamp_run(bank, 11.0, 48.0) is False

    def test_scattered_clip_instants_under_the_floor_pass(self):
        # Ten independent single-sample clips: `at_lim` sees 4% of the
        # flight, and the continuous run is 0.05 s — under the 0.15 s floor.
        bank = np.full(241, -40.0)
        bank[::24] = -48.0
        assert check_bank_clamp_run(bank, 11.0, 48.0) is True

    def test_the_longest_run_is_measured_not_the_last_one(self):
        bank = np.full(241, -40.0)
        bank[10:50] = -48.0
        bank[200:202] = -48.0
        assert check_bank_clamp_run(bank, 11.0, 48.0) is False


class TestCheckYawBlend:
    """The yaw / side-view blend."""

    @staticmethod
    def _poses(yaws):
        return [{'yaw': y} for y in yaws]

    def _cfg(self, tmp_path):
        side = tmp_path / 'side'
        side.mkdir()
        return {'sprites_side': str(side)}

    def _samples_for(self, yaws):
        return BirdFlightSamples(
            poses=self._poses(yaws),
            xs=np.zeros(len(yaws)),
            ys=np.zeros(len(yaws)),
            scale=np.ones(len(yaws)),
            inv_scale=[1.0] * len(yaws),
        )

    def test_a_flight_with_both_a_rear_and_a_side_window_passes(self, tmp_path):
        yaws = [5.0] * 60 + [45.0] * 60 + [75.0] * 121
        assert check_yaw_blend(self._cfg(tmp_path), self._samples_for(yaws)) is True

    def test_no_sprites_side_configured_fails(self):
        yaws = [5.0] * 60 + [45.0] * 60 + [75.0] * 121
        assert check_yaw_blend({}, self._samples_for(yaws)) is False

    def test_a_sprites_side_path_that_does_not_exist_fails(self, tmp_path):
        cfg = {'sprites_side': str(tmp_path / 'missing')}
        yaws = [5.0] * 60 + [45.0] * 60 + [75.0] * 121
        assert check_yaw_blend(cfg, self._samples_for(yaws)) is False

    def test_a_side_view_that_never_fully_engages_fails(self, tmp_path):
        yaws = [5.0] * 120 + [40.0] * 121
        assert check_yaw_blend(self._cfg(tmp_path), self._samples_for(yaws)) is False

    def test_a_rear_view_without_a_clean_window_fails(self, tmp_path):
        yaws = [40.0] * 120 + [75.0] * 121
        assert check_yaw_blend(self._cfg(tmp_path), self._samples_for(yaws)) is False
