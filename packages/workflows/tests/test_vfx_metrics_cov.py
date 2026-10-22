# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage battery for zyg_workflows.vfx_metrics.

Every metric there is computed from pixels alone — no model, no network, no
GPU, no filesystem — so these tests build synthetic frames with numpy/cv2 and
assert on RANGES and ORDERINGS, never on exact floats: a noise frame reads
sharper than a flat one, a hash equals itself, letterbox finds its bars.
"""

import math

import cv2
import numpy as np
import pytest

from zyg_workflows import vfx_metrics as M

_CA_SCALES = (0.997, 0.998, 0.999, 1.0, 1.001, 1.002, 1.003)

# Six hashes at a mutual Hamming distance of at least 32 bits, so cadence_map
# can never read two different cels as one held drawing.
_CELS = (0x0, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF00000000, 0x0F0F0F0F0F0F0F0F, 0xF0F0F0F0F0F0F0F0)


def _flat(h=64, w=64, v=120):
    return np.full((h, w, 3), v, np.uint8)


def _noise(h=64, w=64, seed=0):
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def _gradient(h=64, w=64):
    row = np.linspace(0, 255, w, dtype=np.float32)
    return cv2.cvtColor(np.repeat(row[None, :], h, axis=0).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def _rect(h=64, w=64, bg=30, fg=250, box=(10, 10, 34, 34)):
    """Dark ground with one blown-out white box: edges, corners, highlights."""
    img = np.full((h, w, 3), bg, np.uint8)
    cv2.rectangle(img, box[:2], box[2:], (fg, fg, fg), -1)
    return img


def _barred(bar=8, vertical=False, h=64, w=64):
    img = _rect(h, w)
    if vertical:
        img[:, :bar] = img[:, w - bar :] = 0
    else:
        img[:bar] = img[h - bar :] = 0
    return img


def _colourful(h=64, w=64):
    """Saturated red subject on a saturated blue ground (BGR)."""
    img = np.zeros((h, w, 3), np.uint8)
    img[..., 0] = 220
    img[16:48, 16:48] = (0, 0, 220)
    return img


def _pan_pair(shift=4, size=128, seed=1):
    """A textured frame and the same frame panned — a fittable camera move."""
    a = _noise(size, size, seed)
    return a, np.roll(a, shift, axis=1)


def _mover_pair(size=96):
    """Static textured ground with one square that moves — residual motion."""
    a = _noise(size, size, 7)
    b = a.copy()
    cv2.rectangle(a, (10, 10), (34, 34), (250, 250, 250), -1)
    cv2.rectangle(b, (30, 10), (54, 34), (250, 250, 250), -1)
    return a, b


def _held(holds):
    """A hash list that holds cel n for holds[n] file frames."""
    out = []
    for n, hold in enumerate(holds):
        out += [_CELS[n % len(_CELS)]] * hold
    return out


def _boom(*_a, **_k):
    raise cv2.error('synthetic')


def _smaller(frame, size=(64, 48)):
    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


@pytest.mark.parametrize('raw', [None, 'not a number', float('nan'), float('inf'), float('-inf')])
def test_f_turns_everything_unserialisable_into_zero(raw):
    assert M._f(raw) == 0.0
    assert M._f(3) == 3.0
    assert M._f(np.float32(2.5)) == 2.5


def test_work_copy_downscales_only_what_is_wider_than_the_cap():
    frame = _flat(32, 48)
    img, scale = M.work_copy(frame)
    assert scale == 1.0
    assert img is frame
    img, scale = M.work_copy(_gradient(200, 1024), max_w=640)
    assert img.shape[1] == 640 and scale == pytest.approx(640 / 1024.0)
    assert img.shape[0] == round(200 * scale)
    # a one-pixel-tall frame must survive the division
    assert M.work_copy(_flat(1, 2000), max_w=64)[0].shape[:2] == (1, 64)


def test_intensity_reads_exposure_and_contrast_off_a_gradient():
    out = M.intensity(_gradient())
    assert 100.0 < out['luma_mean'] < 155.0
    assert out['luma_min'] == pytest.approx(0.0, abs=2.0)
    assert out['luma_max'] == pytest.approx(255.0, abs=2.0)
    assert out['luma_p1'] <= out['luma_p25'] <= out['luma_p50'] <= out['luma_p75'] <= out['luma_p99']
    assert out['luma_p5'] <= out['luma_p95']
    assert out['dynamic_range'] > 200.0
    assert 0.0 < out['rms_contrast'] < 1.0
    assert out['michelson_contrast'] == pytest.approx(1.0, abs=0.05)
    assert out['entropy_bits'] > 4.0
    assert out['is_near_black'] == out['is_near_white'] == 0.0


def test_intensity_flat_frame_has_no_contrast_and_no_entropy():
    out = M.intensity(_flat(v=128))
    assert out['luma_std'] == pytest.approx(0.0, abs=1e-6)
    assert out['rms_contrast'] == pytest.approx(0.0, abs=1e-6)
    assert out['dynamic_range'] == 0.0
    assert out['entropy_bits'] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize(
    ('value', 'near_black', 'near_white', 'black_clip', 'white_clip'),
    [(0, 1.0, 0.0, 1.0, 0.0), (255, 0.0, 1.0, 0.0, 1.0)],
)
def test_intensity_flags_crushed_and_blown_frames(value, near_black, near_white, black_clip, white_clip):
    out = M.intensity(_flat(v=value))
    assert (out['is_near_black'], out['is_near_white']) == (near_black, near_white)
    assert (out['black_clip_frac'], out['white_clip_frac']) == (black_clip, white_clip)


def test_colour_reads_a_saturated_frame_as_colourful():
    out = M.colour(_colourful())
    assert out['sat_mean'] > 200.0 and out['sat_p95'] > 200.0 and out['sat_std'] >= 0.0
    assert out['colourfulness'] > 20.0
    assert out['grey_frac'] == pytest.approx(0.0, abs=1e-6)
    assert 0.0 <= out['hue_circmean_deg'] <= 180.0
    assert 0.0 <= out['hue_concentration'] <= 1.0
    assert len(out['hue_hist12']) == 12
    assert sum(out['hue_hist12']) == pytest.approx(1.0, abs=1e-5)
    assert out['chan_mean_b'] > out['chan_mean_r']
    assert out['warm_cool_ratio'] < 1.0
    assert sum(d['frac'] for d in out['dominant_colours']) == pytest.approx(1.0, abs=1e-4)
    assert all(len(d['hex']) == 7 and d['hex'].startswith('#') for d in out['dominant_colours'])


def test_colour_reads_a_grey_frame_as_grey():
    out = M.colour(_flat(v=128))
    assert out['sat_mean'] == pytest.approx(0.0, abs=1e-6)
    assert out['grey_frac'] == 1.0
    assert out['colourfulness'] == pytest.approx(0.0, abs=1e-6)


def test_colour_subsamples_a_big_frame_and_survives_an_impossible_cluster_count():
    out = M.colour(_noise(200, 200))  # >20000 px: the k-means input is sampled
    assert out['dominant_colours']
    assert out['val_mean'] > 0.0
    assert M.colour(_flat(40, 40), k_dominant=0)['dominant_colours'] == []


def test_detail_ranks_a_noise_frame_sharper_than_a_flat_one():
    sharp, flat = M.detail(_noise()), M.detail(_flat())
    assert all(sharp[k] > flat[k] for k in ('lap_var', 'tenengrad', 'grad_mean', 'texture_energy'))
    assert sharp['edge_density'] >= flat['edge_density']
    assert sharp['grad_p95'] > 0.0


def test_detail_on_a_flat_frame_has_an_empty_orientation_histogram():
    out = M.detail(_flat())
    assert out['edge_orient_hist8'] == [0.0] * 8
    assert out['edge_orient_peak'] == out['edge_orient_entropy'] == out['corner_count'] == 0.0


def test_detail_finds_the_corners_and_edges_of_a_drawn_box():
    out = M.detail(_rect())
    assert out['corner_count'] > 0.0
    assert out['edge_density'] > 0.0
    assert out['lap_var'] > 0.0
    assert sum(out['edge_orient_hist8']) == pytest.approx(1.0, abs=1e-5)
    assert out['edge_orient_peak'] > 0.0
    assert out['edge_orient_entropy'] > 0.0


def test_detail_reports_no_corners_when_opencv_refuses_the_frame(monkeypatch):
    monkeypatch.setattr(M.cv2, 'goodFeaturesToTrack', _boom)
    assert M.detail(_rect())['corner_count'] == 0.0


def test_noise_sigma_ranks_noise_above_flat_and_refuses_a_tiny_frame():
    assert M.noise_sigma(_noise())['noise_sigma'] > M.noise_sigma(_flat())['noise_sigma']
    assert M.noise_sigma(_flat())['noise_sigma'] == pytest.approx(0.0, abs=1e-6)
    assert M.noise_sigma(_flat(2, 2)) == {'noise_sigma': 0.0}


def test_spectrum_ranks_high_frequency_energy_above_a_blurred_frame():
    sharp = M.spectrum(_noise(128, 128))
    blurred = M.spectrum(cv2.GaussianBlur(_noise(128, 128), (0, 0), 3.0))
    assert sharp['hf_energy_frac'] > blurred['hf_energy_frac']
    assert sharp['spectrum_slope'] > blurred['spectrum_slope']
    assert 0.0 <= sharp['banding_score'] <= 1.0


def test_spectrum_reads_a_flat_frame_as_banding_and_refuses_too_few_radial_bins():
    assert M.spectrum(_flat(128, 128))['banding_score'] == pytest.approx(1.0, abs=1e-5)
    assert M.spectrum(_flat(10, 10)) == {'spectrum_slope': 0.0, 'hf_energy_frac': 0.0, 'banding_score': 0.0}


def test_composition_puts_the_saliency_centroid_inside_the_frame():
    out = M.composition(_rect(64, 96))
    assert all(0.0 <= out[k] <= 1.0 for k in ('saliency_cx', 'saliency_cy', 'thirds_mass'))
    assert out['saliency_spread'] >= 0.0
    assert out['centre_bias'] <= 1.0


def test_composition_scores_a_mirrored_frame_as_symmetric():
    half = _rect(64, 64, box=(8, 8, 24, 24))[:, :32]
    out = M.composition(np.concatenate([half, half[:, ::-1]], axis=1))
    assert out['symmetry_h'] > M.composition(_gradient())['symmetry_h']
    assert 0.0 <= out['symmetry_v'] <= 1.0


@pytest.mark.parametrize('vertical', [False, True])
def test_letterbox_finds_the_matte_bars_it_was_given(vertical):
    out = M.letterbox(_barred(bar=8, vertical=vertical))
    if vertical:
        assert out['bar_left'] == out['bar_right'] == 8.0
        assert (out['pillarboxed'], out['letterboxed']) == (1.0, 0.0)
        assert out['active_aspect'] < out['file_aspect']
    else:
        assert out['bar_top'] == out['bar_bottom'] == 8.0
        assert (out['letterboxed'], out['pillarboxed']) == (1.0, 0.0)
        assert out['active_aspect'] > out['file_aspect']


@pytest.mark.parametrize('frame', [_flat(64, 128), np.zeros((64, 64, 3), np.uint8)])
def test_letterbox_reports_no_bars_without_them(frame):
    out = M.letterbox(frame)
    assert (out['bar_top'], out['bar_bottom'], out['bar_left'], out['bar_right']) == (0.0, 0.0, 0.0, 0.0)
    assert out['letterboxed'] == out['pillarboxed'] == 0.0
    assert out['active_aspect'] == pytest.approx(out['file_aspect'])


def test_postfx_reads_bloom_off_a_blown_highlight():
    frame = cv2.GaussianBlur(_rect(96, 96, bg=20, fg=255, box=(30, 30, 66, 66)), (0, 0), 3.0)
    out = M.postfx(frame)
    assert out['highlight_frac'] > 0.0
    assert out['bloom_lift'] > 0.0
    assert out['bloom_radius_px'] >= 0.0
    assert out['ca_scale_r'] in _CA_SCALES and out['ca_scale_b'] in _CA_SCALES
    assert out['ca_px'] >= 0.0
    assert 0.0 <= out['vignette_strength'] <= 1.0


@pytest.mark.parametrize(('value', 'highlight_frac'), [(40, 0.0), (255, 1.0)])
def test_postfx_finds_no_bloom_without_a_halo_ring(value, highlight_frac):
    """No highlight at all, and a frame blown edge to edge, both have no ring
    for light to spill into."""
    out = M.postfx(_flat(96, 96, v=value))
    assert out['highlight_frac'] == highlight_frac
    assert out['bloom_lift'] == out['bloom_radius_px'] == out['halation_red_lift'] == 0.0


def test_postfx_reads_a_vignette_as_a_radial_falloff():
    h = w = 96
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rr = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    g = (200.0 * np.clip(1.0 - 0.9 * rr, 0.0, 1.0)).astype(np.uint8)
    vignetted = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    assert M.postfx(vignetted)['vignette_strength'] > M.postfx(_flat(96, 96))['vignette_strength']


def test_postfx_reads_halation_when_red_spills_further_than_green():
    frame = _rect(96, 96, bg=20, fg=255, box=(36, 36, 60, 60))
    hi = (cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) > 235).astype(np.float32)
    spill = cv2.GaussianBlur(hi, (0, 0), 8.0) * 200.0
    frame[..., 2] = np.clip(frame[..., 2].astype(np.float32) + spill, 0, 255).astype(np.uint8)
    out = M.postfx(frame)
    assert out['halation_red_lift'] > 0.0
    assert out['bloom_radius_px'] > 0.0


def test_postfx_falls_back_to_unit_scales_when_the_ca_search_raises(monkeypatch):
    monkeypatch.setattr(M.cv2, 'warpAffine', _boom)
    out = M.postfx(_rect(96, 96))
    assert out['ca_scale_r'] == out['ca_scale_b'] == 1.0
    assert out['ca_px'] == 0.0


def test_phash_is_an_integer_identical_to_itself():
    frame = _rect()
    h = M.phash(frame)
    assert isinstance(h, int)
    assert 0 <= h < 1 << 63
    assert M.hamming(h, M.phash(frame.copy())) == 0
    assert 0 <= M.phash(frame, size=4) < 1 << 15


def test_phash_tolerates_codec_noise_and_not_a_different_picture():
    frame = _rect()
    brighter = np.clip(frame.astype(np.int16) + 3, 0, 255).astype(np.uint8)
    assert M.hamming(M.phash(frame), M.phash(brighter)) <= 4
    assert M.hamming(M.phash(frame), M.phash(_noise())) > 4


@pytest.mark.parametrize(('a', 'b', 'bits'), [(0, 0, 0), (0, 1, 1), (0b1010, 0b0101, 4), (255, 0, 8)])
def test_hamming_counts_differing_bits(a, b, bits):
    assert M.hamming(a, b) == bits


def test_pair_basic_reads_an_identical_pair_as_no_change():
    frame = _rect()
    out = M.pair_basic(frame, frame.copy())
    assert out['diff_mean'] == out['diff_frac_moved'] == out['diff_p95'] == 0.0
    assert out['hist_corr'] == pytest.approx(1.0, abs=1e-5)
    assert out['luma_delta'] == pytest.approx(0.0, abs=1e-5)


def test_pair_basic_reads_a_cut_as_a_large_change():
    out = M.pair_basic(_flat(64, 64, 10), _flat(64, 64, 240))
    assert out['diff_mean'] > 100.0 and out['luma_delta'] > 100.0
    assert out['diff_frac_moved'] == 1.0
    assert out['diff_p95'] >= out['diff_mean']


@pytest.mark.parametrize(
    ('fn', 'key'), [(M.pair_basic, 'diff_mean'), (M.global_motion, 'cam_zoom'), (M.flow, 'flow_ok')]
)
def test_a_pair_metric_resizes_a_mismatched_second_frame(fn, key):
    a = _noise(96, 96, 5)
    assert key in fn(a, _smaller(a))
    assert M.pair_basic(_flat(64, 64, 100), _flat(32, 48, 100))['diff_mean'] == pytest.approx(0.0, abs=1e-5)


def test_global_motion_fits_a_horizontal_pan():
    out = M.global_motion(*_pan_pair(shift=4))
    assert out['cam_fit_ok'] == 1.0
    assert out['cam_dx'] == pytest.approx(4.0, abs=1.0)
    assert abs(out['cam_dy']) < 1.0 and abs(out['cam_roll_deg']) < 2.0
    assert out['cam_zoom'] == pytest.approx(1.0, abs=0.05)
    assert out['cam_inliers'] >= 12.0
    assert out['cam_pan_norm'] > 0.0 and abs(out['cam_tilt_norm']) < 0.01


def _no_tracked_points(_ga, _gb, p0, _nxt, **_kw):
    return p0.copy(), np.zeros((len(p0), 1), np.uint8), None


@pytest.mark.parametrize(
    ('name', 'replacement'),
    [
        ('calcOpticalFlowPyrLK', lambda *a, **k: (None, None, None)),
        ('calcOpticalFlowPyrLK', _no_tracked_points),
        ('estimateAffinePartial2D', lambda *a, **k: (None, None)),
        ('goodFeaturesToTrack', _boom),
    ],
)
def test_global_motion_returns_the_blank_fit_when_a_stage_gives_up(monkeypatch, name, replacement):
    monkeypatch.setattr(M.cv2, name, replacement)
    blank = dict.fromkeys(
        ('cam_dx', 'cam_dy', 'cam_roll_deg', 'cam_inliers', 'cam_fit_ok', 'cam_pan_norm', 'cam_tilt_norm'), 0.0
    )
    blank['cam_zoom'] = 1.0
    assert M.global_motion(*_pan_pair()) == blank
    # a featureless pair reaches the same place without any monkeypatching
    assert M.global_motion(_flat(64, 64), _flat(64, 64, 121)) == blank


def test_flow_reports_raw_magnitude_on_a_pan_without_a_camera_fit():
    a, b = _pan_pair(shift=4)
    out = M.flow(a, b)
    assert out['flow_ok'] == 1.0
    assert out['flow_mag_mean'] > 0.5 and out['flow_mag_std'] >= 0.0
    assert out['flow_mag_max'] >= out['flow_mag_p95'] >= 0.0
    assert out['flow_moving_frac'] > 0.0
    assert sum(out['flow_dir_hist8']) == pytest.approx(1.0, abs=1e-5)
    assert out['flow_dir_peak'] > 0.0
    assert out['residual_mag_max'] >= out['residual_mag_p95'] >= 0.0
    assert out['_residual_field'][0].shape == a.shape[:2]


def test_flow_compensates_the_camera_so_a_pure_pan_has_little_residual():
    a, b = _pan_pair(shift=4)
    cam = M.global_motion(a, b)
    out = M.flow(a, b, cam)
    assert cam['cam_fit_ok'] == 1.0
    assert out['residual_mag_mean'] < out['flow_mag_mean']
    assert out['residual_moving_frac'] <= out['flow_moving_frac']
    assert math.isfinite(out['flow_divergence'])
    assert math.isfinite(out['flow_curl'])


def test_flow_ignores_a_camera_dict_whose_fit_failed():
    a, b = _pan_pair(shift=4)
    failed = {'cam_fit_ok': 0.0, 'cam_zoom': 2.0, 'cam_roll_deg': 90.0, 'cam_dx': 50.0, 'cam_dy': 50.0}
    assert M.flow(a, b, failed)['residual_mag_mean'] == pytest.approx(M.flow(a, b)['residual_mag_mean'])


def test_flow_has_an_empty_direction_histogram_on_a_still_pair():
    frame = _flat(64, 64)
    out = M.flow(frame, frame.copy())
    assert out['flow_dir_hist8'] == [0.0] * 8
    assert out['flow_dir_peak'] == out['flow_mag_mean'] == 0.0


def test_flow_reports_not_ok_when_farneback_raises(monkeypatch):
    monkeypatch.setattr(M.cv2, 'calcOpticalFlowFarneback', _boom)
    assert M.flow(*_pan_pair()) == {'flow_ok': 0.0}


def test_motion_blobs_finds_a_region_of_synthetic_residual_motion():
    h = w = 96
    fx, fy = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
    fx[20:60, 20:60] = 4.0
    fy[20:60, 20:60] = -2.0
    blobs = M.motion_blobs(fx, fy, (h, w))
    assert len(blobs) == 1
    b = blobs[0]
    assert (b['x'], b['y']) == pytest.approx((20 / 96, 20 / 96), abs=0.05)
    assert (b['w'], b['h']) == pytest.approx((40 / 96, 40 / 96), abs=0.1)
    assert (b['dx'], b['dy']) == pytest.approx((4.0, -2.0), abs=0.5)
    assert b['area_frac'] > 0.1
    assert b['mag_mean'] > 1.5
    assert b['mag_max'] == pytest.approx(b['mag_mean'], abs=1e-4)  # a uniform field
    assert 0.0 <= b['cx'] <= 1.0 and 0.0 <= b['cy'] <= 1.0


def test_motion_blobs_ignores_a_still_field_and_regions_below_the_area_floor():
    zeros = np.zeros((96, 96), np.float32)
    assert M.motion_blobs(zeros, zeros, (96, 96)) == []
    fx = zeros.copy()
    fx[40:48, 40:48] = 5.0
    assert M.motion_blobs(fx, zeros, (96, 96), min_area_frac=0.5) == []


def test_motion_blobs_sorts_by_area_and_caps_the_list_at_24():
    # 30 regions on a 52 px grid — too far apart for the closing kernel to
    # bridge them — each one wider than the last.
    fx, fy = np.zeros((320, 320), np.float32), np.zeros((320, 320), np.float32)
    for n in range(30):
        y, x = 52 * (n // 6), 52 * (n % 6)
        fx[y : y + 10, x : x + 10 + n] = 5.0
    blobs = M.motion_blobs(fx, fy, (320, 320))
    assert len(blobs) == 24
    assert blobs == sorted(blobs, key=lambda b: -b['area_frac'])


def test_change_blobs_catches_an_object_that_moved():
    blobs = M.change_blobs(*_mover_pair())
    assert blobs
    assert all(b['src'] == 'change' and b['dx'] == 0.0 and b['dy'] == 0.0 for b in blobs)
    assert max(b['area_frac'] for b in blobs) > 0.01
    assert all(b['mag_max'] >= b['mag_mean'] > 0.0 for b in blobs)
    assert blobs == sorted(blobs, key=lambda b: -b['area_frac'])


def test_change_blobs_warps_the_camera_out_before_differencing():
    a, b = _pan_pair(shift=5)
    cam = M.global_motion(a, b)
    assert cam['cam_fit_ok'] == 1.0
    compensated = sum(blob['area_frac'] for blob in M.change_blobs(a, b, cam))
    assert compensated < sum(blob['area_frac'] for blob in M.change_blobs(a, b))


def test_change_blobs_ignores_an_identical_pair_and_regions_below_the_floor():
    frame = _rect()
    assert M.change_blobs(frame, frame.copy()) == []
    a, b = _mover_pair()
    assert M.change_blobs(a, b, min_area_frac=0.9) == []
    assert isinstance(M.change_blobs(a, _smaller(b)), list)


def test_thumb_keeps_the_aspect_and_returns_float_colour():
    t = M.thumb(_rect(90, 180), w=64)
    assert t.shape == (32, 64, 3)
    assert t.dtype == np.float32
    assert M.thumb(_flat(2, 400), w=16).shape[0] >= 1  # never zero rows


def test_cadence_map_of_nothing_is_unknown():
    out = M.cadence_map([])
    assert out['cadence'] == 'unknown'
    assert out['unique_idx'] == out['holds'] == []
    assert out['hold_hist'] == {}
    assert out['unique_ratio'] == out['mean_hold'] == 0.0


@pytest.mark.parametrize(('hold', 'cadence'), [(1, 'ones'), (2, 'twos'), (3, 'threes'), (4, 'mixed')])
def test_cadence_map_classifies_a_regular_cadence_on_its_mode(hold, cadence):
    out = M.cadence_map(_held([hold] * 6))
    assert out['cadence'] == cadence
    assert out['holds'] == [hold] * 6
    assert out['unique_idx'] == [n * hold for n in range(6)]
    assert out['mean_hold'] == pytest.approx(float(hold))
    assert out['unique_ratio'] == pytest.approx(1.0 / hold)
    assert out['hold_hist'] == {str(hold): 6}


def test_cadence_map_calls_an_even_mix_of_holds_mixed_and_keeps_a_dominant_one():
    # three 1s, three 2s, three 3s: no hold length owns 60 % of the cels.
    even = M.cadence_map(_held([1, 2, 3, 1, 2, 3, 1, 2, 3]))
    assert even['cadence'] == 'mixed'
    assert even['hold_hist'] == {'1': 3, '2': 3, '3': 3}
    dominant = M.cadence_map(_held([2] * 9 + [1]))
    assert dominant['cadence'] == 'twos'
    assert dominant['hold_hist'] == {'2': 9, '1': 1}


def test_cadence_map_tolerates_codec_noise_inside_the_dup_bit_budget():
    assert M.cadence_map([0b0, 0b1, 0b11])['holds'] == [3]
    assert M.cadence_map([0b0, 0b1, 0b11], dup_bits=0)['holds'] == [1, 1, 1]


@pytest.mark.parametrize('shape', [(16, 16, 3), (16, 16)])
def test_cadence_map_lets_the_thumbnail_veto_an_identical_hash(shape):
    """A static background with one mover hashes identical; the changed-pixel
    fraction is the second signal that keeps those cels unique."""
    still = np.zeros(shape, np.float32)
    moved = still.copy()
    moved[4:12, 4:12] = 200.0
    assert M.cadence_map([7, 7], thumbs=[still, still.copy()])['holds'] == [2]
    assert M.cadence_map([7, 7], thumbs=[still, moved])['holds'] == [1, 1]


@pytest.mark.parametrize(
    'thumbs',
    [
        [np.zeros((16, 16, 3), np.float32), None],
        [None, np.zeros((16, 16, 3), np.float32)],
        [np.zeros((16, 16, 3), np.float32), np.zeros((8, 8, 3), np.float32)],
    ],
)
def test_cadence_map_falls_back_to_the_hash_when_the_thumbnails_cannot_be_compared(thumbs):
    assert M.cadence_map([7, 7], thumbs=thumbs)['holds'] == [2]


def test_frame_battery_collects_every_per_frame_key_and_the_frame_size():
    out = M.frame_battery(_rect(64, 96))
    assert (out['width'], out['height']) == (96.0, 64.0)
    expected = ('luma_mean', 'sat_mean', 'lap_var', 'noise_sigma', 'spectrum_slope', 'saliency_cx', 'bloom_lift')
    assert set(expected) <= set(out)


def test_frame_battery_survives_a_round_trip_through_a_png(tmp_path):
    png = tmp_path / 'frame.png'
    assert cv2.imwrite(str(png), _rect(64, 96))
    loaded = cv2.imread(str(png), cv2.IMREAD_COLOR)
    assert loaded is not None
    out = M.frame_battery(loaded)
    assert out['width'] == 96.0
    assert out['luma_mean'] == pytest.approx(M.frame_battery(_rect(64, 96))['luma_mean'])


def test_pair_battery_unions_the_flow_and_change_motion_channels():
    out = M.pair_battery(*_mover_pair())
    assert out['flow_ok'] == 1.0
    assert out['motion_blob_count'] >= 1.0
    assert out['motion_blob_count'] == len(out['motion_blobs'])
    assert out['change_blob_count'] >= 1.0
    assert '_residual_field' not in out
    assert {blob['src'] for blob in out['motion_blobs']} <= {'flow', 'change', 'both'}
    assert out['motion_blobs'] == sorted(out['motion_blobs'], key=lambda blob: -blob['area_frac'])


def test_pair_battery_of_an_identical_pair_finds_no_motion():
    frame = _rect(96, 96)
    out = M.pair_battery(frame, frame.copy())
    assert out['motion_blob_count'] == out['change_blob_count'] == out['diff_mean'] == 0.0


def test_pair_battery_tolerates_a_flow_stage_that_returned_no_field(monkeypatch):
    monkeypatch.setattr(M, 'flow', lambda *a, **k: {'flow_ok': 0.0})
    out = M.pair_battery(*_mover_pair())
    assert out['flow_ok'] == 0.0
    assert out['motion_blob_count'] >= 0.0


def test_describe_lists_every_emitted_key_and_caches_the_dictionary(monkeypatch):
    monkeypatch.setattr(M, 'METRIC_NAMES', None)
    first = M.describe()
    assert sorted(first) == ['frame', 'pair']
    assert first['frame'] == sorted(M.frame_battery(_rect(64, 96)))
    assert first['pair'] == sorted(first['pair'])
    assert 'flow_ok' in first['pair']
    assert '_residual_field' not in first['pair']
    assert M.describe() is first
