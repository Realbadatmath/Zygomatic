# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_stt: the browser-blob -> text leg of the voice bridge.

The first two cases are pure plumbing (no model). The third loads large-v3 and
is skipped, loudly, when zyg_whisper cannot bring a model up at all.
"""

import os
import subprocess
import tempfile
import unittest

import pytest

from tests import _tree

# voice_stt still reaches its backend with a flat ``import zyg_whisper``, which only
# resolves when the old production tree is on sys.path — the module is now a sibling,
# zyg_workflows.zyg_whisper. Importing it here therefore succeeded or failed depending
# on whether some earlier test file had inserted the production tree on sys.path first,
# which made this file's collection order-dependent. Asked for by name, the result is
# the same either way: a skip that says what is missing.
voice_stt = pytest.importorskip(
    'zyg_workflows.voice_stt', reason='voice_stt cannot import its backend (zyg_whisper) in this checkout'
)

# The narrator seed is a licensed voice recording in the asset tree, not in this repository.
SEED = os.path.join(str(_tree.DATA), 'assets', 'voice_seeds', 'abel_narrator_seed.wav')


class TestSuffix(unittest.TestCase):
    def test_mime_to_suffix(self):
        self.assertEqual(voice_stt._suffix_for('audio/webm;codecs=opus'), '.webm')
        self.assertEqual(voice_stt._suffix_for('audio/wav'), '.wav')
        self.assertEqual(voice_stt._suffix_for('audio/mp4'), '.mp4')
        self.assertEqual(voice_stt._suffix_for('audio/ogg'), '.ogg')
        # unknown -> what the browser actually sends
        self.assertEqual(voice_stt._suffix_for('application/octet-stream'), '.webm')


class TestTooShort(unittest.TestCase):
    def test_empty_bytes(self):
        r = voice_stt.transcribe_utterance(b'', mime='audio/webm')
        self.assertEqual(r['text'], '')
        self.assertEqual(r['reason'], 'too_short')
        self.assertIn(r['device'], ('cuda', 'cpu'))

    def test_sub_quarter_second_wav(self):
        """A real, decodable 0.1 s wav is rejected before the model is touched."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'blip.wav')
            subprocess.run(
                [
                    'ffmpeg',
                    '-y',
                    '-hide_banner',
                    '-loglevel',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=r=16000:cl=mono',
                    '-t',
                    '0.1',
                    path,
                ],
                check=True,
            )
            with open(path, 'rb') as fh:
                data = fh.read()
        r = voice_stt.transcribe_utterance(data, mime='audio/wav')
        self.assertEqual(r['text'], '')
        self.assertEqual(r['reason'], 'too_short')
        self.assertLess(r['seconds'], voice_stt.MIN_SECONDS)


class TestFfmpegFailure(unittest.TestCase):
    def test_garbage_bytes_raise_clean_error(self):
        with self.assertRaises(voice_stt.SttError) as cm:
            voice_stt.transcribe_utterance(b'not audio, just bytes' * 64, mime='audio/webm')
        msg = str(cm.exception)
        self.assertIn('ffmpeg', msg.lower())
        self.assertLess(len(msg), 600, 'error must be a readable line, not a dump')


def _model_available():
    try:
        voice_stt.warm()
        return True, ''
    except Exception as e:  # noqa: BLE001 - reported as the skip reason
        return False, f'{type(e).__name__}: {str(e)[:200]}'


@pytest.mark.gpu
class TestRealTranscription(unittest.TestCase):
    """Loads whisper large-v3 and transcribes for real — a CUDA device and the seed wav."""

    def test_abel_seed(self):
        if not os.path.exists(SEED):
            self.skipTest(f'seed audio missing: {SEED}')
        ok, why = _model_available()
        if not ok:
            self.skipTest(f'zyg_whisper could not load a model — {why}')
        with open(SEED, 'rb') as fh:
            data = fh.read()
        r = voice_stt.transcribe_utterance(data, mime='audio/wav')
        self.assertGreater(len(r['text']), 20, f'transcript too short: {r!r}')
        self.assertGreater(r['seconds'], 1.0)
        self.assertIn(r['device'], ('cuda', 'cpu'))
        self.assertNotIn('  ', r['text'], 'spaces must be collapsed')
        self.assertEqual(r['text'], r['text'].strip())


if __name__ == '__main__':
    unittest.main()
