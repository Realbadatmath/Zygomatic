#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_common — CPU-only wiring tests (no GPU, no ComfyUI, no TTS).

    scripts/run_tests.sh tests/test_kids_series_common.py

What is asserted here is what would silently break all ten series at once: the
synthesised effects being the length and format the assembler assumes, the
instrument picker returning a CC0 file that really exists, the soundfont bed
landing on the requested duration, the cost stamp the checker reads, and the
video path (frames -> clip -> concat -> mix -> mux) producing a 1280x720 mp4
with audio on it.
"""

import os

import pytest

pytest.importorskip('soundfile')  # the audio extra; the CPU run skips this module without it

import soundfile as sf
from PIL import Image

from zyg_workflows import kids_series_common as K


@pytest.mark.parametrize('kind', K.SFX_KINDS)
def test_synth_sfx_every_kind(kind, tmp_path):
    out = str(tmp_path / f'{kind}.wav')
    want = 0.9
    assert K.synth_sfx(kind, out, seconds=want, seed=3), f'{kind} produced nothing'
    info = sf.info(out)
    assert info.samplerate == 48000, f'{kind}: {info.samplerate} Hz'
    assert info.channels == 1, f'{kind}: {info.channels} channels'
    assert abs(info.duration - want) <= want * 0.05, f'{kind}: {info.duration:.3f}s, wanted {want}s'


def test_synth_sfx_is_deterministic(tmp_path):
    a, b = str(tmp_path / 'a.wav'), str(tmp_path / 'b.wav')
    assert K.synth_sfx('pop', a, seconds=0.4, seed=11)
    assert K.synth_sfx('pop', b, seconds=0.4, seed=11)
    assert open(a, 'rb').read() == open(b, 'rb').read()


def test_synth_sfx_rejects_unknown_kind(tmp_path):
    assert K.synth_sfx('kazoo', str(tmp_path / 'x.wav'), seconds=0.3) is False


def test_instrument_shot_is_cc0_and_on_disk():
    from zyg_workflows import asset_library_service as A

    path = K.instrument_shot('piano', 'C4', seed=5)
    if not path:
        # The one-shot library is ~20 GB of samples in the asset tree, not in this
        # repository; the licence sidecar ships but the audio it points at does not.
        pytest.skip('the instrument one-shot library is not on this machine: %s' % A._audio_dir('instruments'))
    assert os.path.isfile(path), path

    root = A._audio_dir('instruments')
    by_file = {r['file']: r for r in A.load_assets('instruments')}
    rec = by_file[os.path.relpath(path, root)]
    assert 'piano' in str(rec['instrument']).lower(), rec['instrument']
    assert str(rec['pitch']).upper() == 'C4', rec['pitch']
    assert str(rec['license_id']).lower() in ('cc0', 'public-domain')
    assert not rec.get('no_ai_training')

    assert K.instrument_shot('piano', 'C4', seed=5) == path  # deterministic
    assert K.instrument_shot('definitely-not-an-instrument') is None


def test_music_bed_lands_on_the_requested_length(tmp_path):
    out = str(tmp_path / 'bed.wav')
    if not K.music_bed(out, seconds=8, mood='gentle', age_band='toddler', seed=2):
        # The bed is rendered through a soundfont, which is a licensed asset in the asset
        # tree rather than source. Without it there is no bed to measure the length of.
        pytest.skip('no soundfont on this machine — music_bed cannot render')
    d = K.probe(out)['duration']
    assert 7.5 <= d <= 8.5, f'{d:.3f}s'


def test_write_manifest_stamps_the_cost_fields(tmp_path):
    import json

    path = K.write_manifest(str(tmp_path), {'slug': 'demo', 'ok': True})
    assert path == str(tmp_path / 'manifest.json')
    m = json.load(open(path))
    assert m['slug'] == 'demo' and m['ok'] is True
    assert m['api_cost_usd'] == 0.0
    assert m['paid_api_calls'] == 0
    assert m['paid_sdk_imported'] is False
    assert m['local_only'] is True
    assert m['written']


def test_discover_never_raises():
    found = K.discover()
    assert isinstance(found, dict)
    assert isinstance(K.discover_errors(), list)


def _colour_clip(tmp_path, name, rgb, seconds):
    """Two dozen identical frames -> one clip, through frames_to_clip."""
    d = tmp_path / name
    d.mkdir()
    n = int(seconds * K.FPS)
    for i in range(n):
        Image.new('RGB', (640, 360), rgb).save(str(d / f'f_{i:04d}.png'))
    clip = str(tmp_path / f'{name}.mp4')
    assert K.frames_to_clip(str(d / 'f_%04d.png'), clip), name
    return clip


def test_video_path_frames_concat_mix_mux(tmp_path):
    seconds = 1.0
    clips = [
        _colour_clip(tmp_path, 'red', (220, 60, 60), seconds),
        _colour_clip(tmp_path, 'green', (60, 200, 90), seconds),
        _colour_clip(tmp_path, 'blue', (70, 110, 230), seconds),
    ]
    for c in clips:
        p = K.probe(c)
        assert (p['w'], p['h']) == (K.W, K.H), p

    joined = str(tmp_path / 'joined.mp4')
    assert K.concat_clips(clips, joined, xfade=0.0)
    total = seconds * len(clips)
    jp = K.probe(joined)
    assert (jp['w'], jp['h']) == (K.W, K.H), jp
    assert abs(jp['duration'] - total) <= 0.5, jp

    ding = str(tmp_path / 'ding.wav')
    pop = str(tmp_path / 'pop.wav')
    assert K.synth_sfx('ding', ding, seconds=0.8, seed=1)
    assert K.synth_sfx('pop', pop, seconds=0.4, seed=2)
    bed = str(tmp_path / 'bed.wav')
    assert K.mix_audio([(ding, 0.0, 0.0), (pop, 1.5, -3.0)], bed, total)

    out = str(tmp_path / 'episode.mp4')
    assert K.mux(joined, bed, out)
    op = K.probe(out)
    assert op['has_audio'] is True, op
    assert (op['w'], op['h']) == (K.W, K.H), op
    assert abs(op['duration'] - total) <= 0.5, op

    poster = str(tmp_path / 'poster.jpg')
    assert K.write_poster(out, poster)
    assert Image.open(poster).size == (K.W, K.H)


def test_concat_of_one_clip_is_the_normalised_copy(tmp_path):
    clip = _colour_clip(tmp_path, 'solo', (200, 200, 60), 0.5)
    out = str(tmp_path / 'one.mp4')
    assert K.concat_clips([clip], out)
    assert abs(K.probe(out)['duration'] - 0.5) <= 0.3


def test_mix_audio_with_no_tracks_is_silence_of_the_right_length(tmp_path):
    out = str(tmp_path / 'silence.wav')
    assert K.mix_audio([], out, 2.0)
    assert abs(K.probe(out)['duration'] - 2.0) <= 0.2
