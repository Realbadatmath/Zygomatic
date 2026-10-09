# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for voice_ext/speaker.py -- no model, no GPU, no worker process.

`speaker.embed_wav` is the seam: every test monkeypatches it with a deterministic
fake, so these run in the agents venv in under a second and never touch the CPU
venv that holds ECAPA. What is covered is the LOGIC the bench cannot prove:
the enrol-too-short refusal, and that with the gate off everyone is accepted
while the real score is still reported.

    ../.venv/bin/python -m unittest tests.test_voice_speaker
"""

import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_workflows.voice_ext import speaker as S  # noqa: E402


def _tone_wav(path, seconds, value=1000):
    """A 16 kHz mono wav of the right LENGTH. Content is irrelevant: embed_wav
    is faked, and only ffmpeg and the wave module ever look at these samples."""
    rate = 16000
    frames = int(seconds * rate)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack('<%dh' % frames, *([value, -value] * (frames // 2))))


class SpeakerTestCase(unittest.TestCase):
    """Redirects every runtime path into a temp dir so the real
    data/runtime/voice_bridge/ is never written by a test run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='test_vb_speaker_')
        self._saved = (S.RUNTIME, S.SPEAKERS_DIR, S.CONFIG_PATH, S.embed_wav)
        S.RUNTIME = os.path.join(self.tmp, 'voice_bridge')
        S.SPEAKERS_DIR = os.path.join(S.RUNTIME, 'speakers')
        S.CONFIG_PATH = os.path.join(S.RUNTIME, 'config.json')
        os.makedirs(S.SPEAKERS_DIR, exist_ok=True)

    def tearDown(self):
        S.RUNTIME, S.SPEAKERS_DIR, S.CONFIG_PATH, S.embed_wav = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_embed(self, vector):
        """Every window of every clip embeds to `vector`. Deterministic scores."""
        S.embed_wav = lambda path, _v=list(vector): list(_v)

    def wav(self, name, seconds):
        path = os.path.join(self.tmp, name)
        _tone_wav(path, seconds)
        return path


class TestEnrolTooShort(SpeakerTestCase):
    def test_refuses_audio_under_twenty_seconds(self):
        self.fake_embed([1.0] + [0.0] * 191)
        out = S.enrol({'name': 'Abel', 'wav': self.wav('short.wav', 12.0)})
        self.assertNotIn('ok', out)
        self.assertEqual(out['code'], 400)
        self.assertIn('at least 20 s', out['error'])
        self.assertAlmostEqual(out['seconds'], 12.0, places=1)
        self.assertEqual(os.listdir(S.SPEAKERS_DIR), [], 'a refused enrol must not leave a speaker file behind')

    def test_accepts_audio_over_twenty_seconds(self):
        self.fake_embed([1.0] + [0.0] * 191)
        out = S.enrol({'name': 'Abel', 'wav': self.wav('long.wav', 24.0)})
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(out['slug'], 'abel')
        self.assertEqual(out['n_windows'], 6)  # 24 s / 4 s windows
        with open(os.path.join(S.SPEAKERS_DIR, 'abel.json'), encoding='utf-8') as fh:
            rec = json.load(fh)
        self.assertEqual(len(rec['emb']), 192)
        self.assertAlmostEqual(sum(x * x for x in rec['emb']) ** 0.5, 1.0, places=6)

    def test_enrol_needs_a_name(self):
        self.fake_embed([1.0] + [0.0] * 191)
        out = S.enrol({'wav': self.wav('long2.wav', 24.0)})
        self.assertEqual(out['code'], 400)
        self.assertIn('name', out['error'])


class TestGateOff(SpeakerTestCase):
    def _enrol_abel(self):
        self.fake_embed([1.0] + [0.0] * 191)  # Abel points down axis 0
        out = S.enrol({'name': 'Abel', 'wav': self.wav('abel.wav', 24.0)})
        self.assertTrue(out.get('ok'), out)

    def test_gate_off_accepts_a_stranger_and_still_reports_the_score(self):
        self._enrol_abel()
        S.config({'speaker_gate': False}, 'POST')
        self.assertFalse(S.read_config()['speaker_gate'])

        self.fake_embed([0.0, 1.0] + [0.0] * 190)  # orthogonal: cosine 0
        out = S.verify({'wav': self.wav('stranger.wav', 5.0)})
        self.assertTrue(out.get('ok'), out)
        self.assertTrue(out['accepted'], 'gate off must accept everyone')
        self.assertFalse(out['gate'])
        self.assertAlmostEqual(out['score'], 0.0, places=3)
        self.assertLess(out['score'], out['threshold'], 'the score must still be the honest one, below threshold')
        self.assertEqual(out['name'], 'Abel')

    def test_gate_on_refuses_the_same_stranger(self):
        self._enrol_abel()
        S.config({'speaker_gate': True}, 'POST')
        self.fake_embed([0.0, 1.0] + [0.0] * 190)
        out = S.verify({'wav': self.wav('stranger2.wav', 5.0)})
        self.assertTrue(out.get('ok'), out)
        self.assertFalse(out['accepted'])
        self.assertTrue(out['gate'])

    def test_gate_on_accepts_the_enrolled_voice(self):
        self._enrol_abel()
        S.config({'speaker_gate': True, 'speaker_threshold': 0.55}, 'POST')
        self.fake_embed([1.0] + [0.0] * 191)
        out = S.verify({'wav': self.wav('abel2.wav', 5.0)})
        self.assertTrue(out['accepted'], out)
        self.assertAlmostEqual(out['score'], 1.0, places=3)

    def test_nobody_enrolled_follows_the_gate(self):
        S.config({'speaker_gate': True}, 'POST')
        out = S.verify({'wav': self.wav('anyone.wav', 5.0)})
        self.assertFalse(out['accepted'])
        self.assertEqual(out['reason'], 'nobody is enrolled')
        S.config({'speaker_gate': False}, 'POST')
        self.assertTrue(S.verify({'wav': self.wav('anyone2.wav', 5.0)})['accepted'])


class TestConfigAndList(SpeakerTestCase):
    def test_defaults_when_no_config_file_exists(self):
        cfg = S.config({}, 'GET')
        self.assertEqual(cfg['speaker_threshold'], 0.55)
        self.assertTrue(cfg['speaker_gate'])

    def test_threshold_must_be_a_cosine(self):
        self.assertEqual(S.config({'speaker_threshold': 4.0}, 'POST')['code'], 400)
        self.assertEqual(S.config({'speaker_threshold': 'loud'}, 'POST')['code'], 400)
        self.assertEqual(S.config({'speaker_threshold': 0.7}, 'POST')['speaker_threshold'], 0.7)

    def test_list_and_delete(self):
        self.fake_embed([1.0] + [0.0] * 191)
        S.enrol({'name': 'Abel', 'wav': self.wav('a.wav', 24.0)})
        self.assertEqual(S.list_({}, 'GET')['count'], 1)
        self.assertEqual(S.delete({'name': 'Abel'}, 'POST')['deleted'], 'abel')
        self.assertEqual(S.list_({}, 'GET')['count'], 0)
        self.assertEqual(S.delete({'name': 'Abel'}, 'POST')['code'], 404)

    def test_routes_are_the_five_the_contract_names(self):
        self.assertEqual(set(S.ROUTES), {'enrol', 'verify', 'list', 'delete', 'config'})


if __name__ == '__main__':
    unittest.main()
