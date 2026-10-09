# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_ext/tts.py — the voice bridge's reply voice.

No GPU and no engine: voice_studio.synth is monkeypatched to write a tiny real
wav, so what is under test is the part that has to be right every time — the
cache key, the engine choice, the config merge and the long-text split.
"""

import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest

from tests import _tree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import voice_studio as VS  # noqa: E402
from zyg_workflows.voice_ext import tts as T  # noqa: E402


def _wav(path: str, secs: float = 0.4, sr: int = 24000):
    """A real, playable 16-bit mono wav of a 220 Hz tone — ffmpeg has to be able
    to read it, so a fake header will not do."""
    import math

    n = int(sr * secs)
    frames = b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * 220 * i / sr))) for i in range(n))
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + len(frames)) + b'WAVEfmt ')
        f.write(struct.pack('<IHHIIHH', 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b'data' + struct.pack('<I', len(frames)) + frames)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vbtts_')
        self._saved = (T.RUNTIME_DIR, T.SAY_DIR, T.CONFIG_PATH, T._GAP_WAV, VS.synth)

        # The registry's seeds are voice samples in the asset tree, not in this repository,
        # and say() refuses with 'no reference wav' before it reaches any of the logic
        # under test. So the registry is replaced for the duration by two entries whose
        # seeds are real (tiny) wavs: what these tests measure is the cache key, the engine
        # choice, the config merge and the long-text split, none of which depends on who
        # the voices are — only that there is more than one of them and that they resolve.
        self._voices = dict(VS.VOICES)
        VS.VOICES.clear()
        for vid, name in (('abel', 'Abel van Haren'), ('second_voice', 'Second Voice')):
            seed = os.path.join(self.tmp, vid + '_seed.wav')
            _wav(seed)
            row = dict(self._voices.get(vid) or {})
            row.update({'id': vid, 'name': name, 'role': row.get('role') or 'Test voice', 'seed': seed})
            VS.VOICES[vid] = row
        T.RUNTIME_DIR = self.tmp
        T.SAY_DIR = os.path.join(self.tmp, 'say')
        T.CONFIG_PATH = os.path.join(self.tmp, 'config.json')
        T._GAP_WAV = os.path.join(self.tmp, '_gap250.wav')
        os.makedirs(T.SAY_DIR, exist_ok=True)
        self.calls = []

        def fake_synth(text, ref_wav, out_wav, p, log):
            self.calls.append({'text': text, 'ref': ref_wav, 'engine': p['engine']})
            _wav(out_wav)
            return out_wav

        VS.synth = fake_synth

    def tearDown(self):
        (T.RUNTIME_DIR, T.SAY_DIR, T.CONFIG_PATH, T._GAP_WAV, VS.synth) = self._saved
        VS.VOICES.clear()
        VS.VOICES.update(self._voices)
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class TestRegistry(_Base):
    def test_ref_wav_for_resolves_every_source(self):
        """One resolver for all five registry sources: they all write 'seed'."""
        missing = [vid for vid, v in VS.VOICES.items() if not v.get('seed')]
        self.assertEqual(missing, [], 'a registry source used a key other than seed')
        vid = T.default_voice()
        self.assertTrue(vid, 'registry is empty')
        self.assertTrue(os.path.isfile(T.ref_wav_for(vid)))

    def test_ref_wav_for_unknown_voice_is_empty(self):
        self.assertEqual(T.ref_wav_for('no_such_voice_at_all'), '')

    def test_default_voice_is_abel_when_present(self):
        if 'abel' in VS.VOICES:
            self.assertEqual(T.default_voice(), 'abel')

    def test_voices_route_is_the_picker_list(self):
        res = T.ROUTES['voices']({}, 'GET')
        self.assertTrue(res['ok'])
        self.assertEqual(res['count'], len(VS.VOICES))
        self.assertGreater(res['count'], 1)
        row = res['voices'][0]
        self.assertEqual(sorted(row), ['has_active_preset', 'id', 'name', 'role'])
        self.assertIsInstance(row['has_active_preset'], bool)


class TestCacheKey(_Base):
    def test_key_is_stable_across_calls(self):
        p = {'engine': 'indextts2', 'cb_temperature': 0.8}
        a = T.say_key('abel', 'indextts2', p, 'Opening Video Studio')
        b = T.say_key('abel', 'indextts2', dict(p), 'Opening Video Studio')
        self.assertEqual(a, b)

    def test_key_ignores_param_insertion_order(self):
        a = T.say_key('abel', 'indextts2', {'a': 1, 'b': 2}, 'hello')
        b = T.say_key('abel', 'indextts2', {'b': 2, 'a': 1}, 'hello')
        self.assertEqual(a, b)

    def test_key_strips_surrounding_whitespace_only(self):
        a = T.say_key('abel', 'indextts2', {}, '  hello ')
        b = T.say_key('abel', 'indextts2', {}, 'hello')
        self.assertEqual(a, b)
        self.assertNotEqual(a, T.say_key('abel', 'indextts2', {}, 'hello there'))

    def test_key_moves_on_voice_engine_params_text(self):
        base = T.say_key('abel', 'indextts2', {'x': 1}, 'hello')
        self.assertNotEqual(base, T.say_key('other', 'indextts2', {'x': 1}, 'hello'))
        self.assertNotEqual(base, T.say_key('abel', 'chatterbox', {'x': 1}, 'hello'))
        self.assertNotEqual(base, T.say_key('abel', 'indextts2', {'x': 2}, 'hello'))
        self.assertNotEqual(base, T.say_key('abel', 'indextts2', {'x': 1}, 'goodbye'))

    def test_key_is_the_documented_sha1(self):
        p = {'engine': 'chatterbox'}
        blob = '|'.join(['abel', 'chatterbox', json.dumps(p, sort_keys=True, default=str), 'hello'])
        self.assertEqual(
            T.say_key('abel', 'chatterbox', p, ' hello '),
            hashlib.sha1(blob.encode('utf-8'), usedforsecurity=False).hexdigest(),
        )

    def test_cache_path_lands_in_the_say_dir(self):
        self.assertEqual(T.cache_path('deadbeef'), os.path.join(T.SAY_DIR, 'deadbeef.wav'))


class TestEngineChoice(_Base):
    def _vram(self, mb):
        T.free_vram_mb = lambda: float(mb)

    def setUp(self):
        super().setUp()
        self._real_vram = T.free_vram_mb

    def tearDown(self):
        T.free_vram_mb = self._real_vram
        super().tearDown()

    def test_min_vram_mirrors_the_worker_gate(self):
        self.assertEqual(T.MIN_VRAM_MB, int(os.environ.get('ZYG_INDEXTTS_MIN_VRAM_MB', '21000')))

    def test_auto_picks_indextts2_with_room(self):
        self._vram(46000)
        self.assertEqual(T.choose_engine('auto'), 'indextts2')

    def test_auto_picks_indextts2_exactly_at_the_line(self):
        self._vram(T.MIN_VRAM_MB)
        self.assertEqual(T.choose_engine('auto'), 'indextts2')

    def test_auto_falls_back_one_mb_below_the_line(self):
        self._vram(T.MIN_VRAM_MB - 1)
        self.assertEqual(T.choose_engine('auto'), 'chatterbox')

    def test_auto_falls_back_on_a_busy_gpu(self):
        self._vram(4200)
        self.assertEqual(T.choose_engine('auto'), 'chatterbox')

    def test_unknown_vram_falls_back_rather_than_gambling(self):
        self._vram(-1)
        self.assertEqual(T.choose_engine('auto'), 'chatterbox')

    def test_explicit_engine_is_honoured_against_the_vram(self):
        self._vram(1000)
        self.assertEqual(T.choose_engine('indextts2'), 'indextts2')
        self._vram(46000)
        self.assertEqual(T.choose_engine('chatterbox'), 'chatterbox')

    def test_garbage_engine_is_treated_as_auto(self):
        self._vram(46000)
        self.assertEqual(T.choose_engine('kokoro'), 'indextts2')

    def test_params_are_forced_onto_the_chosen_engine(self):
        p = T.params_for(T.default_voice(), 'chatterbox')
        self.assertEqual(p['engine'], 'chatterbox')
        self.assertEqual(set(p), set(VS.defaults()))


class TestConfig(_Base):
    def test_empty_config_defaults_to_abel_and_auto(self):
        cfg = T.load_config()
        self.assertEqual(cfg['voice_id'], T.default_voice())
        self.assertEqual(cfg['engine'], 'auto')

    def test_post_merges_and_does_not_replace(self):
        other = next(v for v in VS.VOICES if v != T.default_voice())
        T.save_config({'voice_id': other})
        T.save_config({'engine': 'chatterbox'})
        cfg = T.load_config()
        self.assertEqual(cfg['voice_id'], other, 'the engine POST dropped the voice')
        self.assertEqual(cfg['engine'], 'chatterbox')

    def test_merge_keeps_unrelated_keys_written_by_other_tasks(self):
        with open(T.CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump({'voice_id': T.default_voice(), 'engine': 'auto', 'driver': 'tab-7'}, f)
        T.save_config({'engine': 'indextts2'})
        with open(T.CONFIG_PATH, encoding='utf-8') as f:
            raw = json.load(f)
        self.assertEqual(raw['driver'], 'tab-7')
        self.assertEqual(raw['engine'], 'indextts2')

    def test_bad_values_are_rejected_not_stored(self):
        T.save_config({'voice_id': 'no_such_voice', 'engine': 'kokoro'})
        cfg = T.load_config()
        self.assertEqual(cfg['voice_id'], T.default_voice())
        self.assertEqual(cfg['engine'], 'auto')

    def test_config_route_get_and_post(self):
        res = T.ROUTES['config']({'engine': 'chatterbox'}, 'POST')
        self.assertTrue(res['ok'])
        self.assertEqual(res['engine'], 'chatterbox')
        self.assertEqual(res['resolved_engine'], 'chatterbox')
        self.assertEqual(res['engines'], ['auto', 'indextts2', 'chatterbox'])
        self.assertEqual(T.ROUTES['config']({}, 'GET')['engine'], 'chatterbox')

    def test_corrupt_config_is_survived(self):
        with open(T.CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write('{not json')
        self.assertEqual(T.load_config()['engine'], 'auto')


class TestSplit(_Base):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(T.split_text('Opening Video Studio'), ['Opening Video Studio'])

    def test_long_text_splits_on_sentence_ends(self):
        s = (
            'This is the first sentence and it runs on for a while. '
            'Here is the second sentence which also runs on for a while. '
            'And a third sentence that pushes the whole thing past the limit. '
            'A fourth, for good measure, so the split has real work to do.'
        )
        self.assertGreater(len(s), T.SPLIT_CHARS)
        parts = T.split_text(s)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= T.SPLIT_CHARS for p in parts), parts)
        self.assertEqual(' '.join(parts), s.strip())

    def test_one_overlong_sentence_is_left_whole(self):
        s = 'word ' * 80
        self.assertEqual(T.split_text(s), [s.strip()])

    def test_empty_text_is_no_chunks(self):
        self.assertEqual(T.split_text('   '), [])


class TestSay(_Base):
    def setUp(self):
        super().setUp()
        self._real_vram = T.free_vram_mb
        T.free_vram_mb = lambda: 46000.0

    def tearDown(self):
        T.free_vram_mb = self._real_vram
        super().tearDown()

    def test_miss_then_hit(self):
        a = T.say('Opening Video Studio')
        self.assertTrue(a['ok'], a)
        self.assertFalse(a['cached'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['engine'], 'indextts2')
        b = T.say('Opening Video Studio')
        self.assertTrue(b['ok'])
        self.assertTrue(b['cached'], 'second call re-synthesised')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(a['wav_path'], b['wav_path'])

    def test_engine_change_invalidates_the_cache(self):
        T.say('Done')
        T.save_config({'engine': 'chatterbox'})
        res = T.say('Done')
        self.assertFalse(res['cached'])
        self.assertEqual(self.calls[-1]['engine'], 'chatterbox')

    def test_long_text_caches_its_parts_too(self):
        s = (
            'This is the first sentence and it runs on for a while. '
            'Here is the second sentence which also runs on for a while. '
            'And a third sentence that pushes the whole thing past the limit. '
            'A fourth, for good measure, so the split has real work to do.'
        )
        self.assertGreater(len(s), T.SPLIT_CHARS)
        res = T.say(s)
        self.assertTrue(res['ok'], res)
        self.assertGreater(res['parts'], 1)
        wavs = [f for f in os.listdir(T.SAY_DIR) if f.endswith('.wav')]
        self.assertGreaterEqual(len(wavs), res['parts'] + 1, 'partial wavs were not kept in the cache')

    def test_empty_and_unknown_voice_are_refused(self):
        self.assertFalse(T.say('')['ok'])
        self.assertFalse(T.say('hello', voice_id='no_such_voice')['ok'])

    def test_say_route_post_returns_metadata_get_returns_bytes(self):
        post = T.ROUTES['say']({'text': 'Done'}, 'POST')
        self.assertTrue(post['ok'])
        self.assertTrue(post['wav_path'].endswith('.wav'))
        self.assertNotIn('log', post)
        get = T.ROUTES['say']({'text': 'Done'}, 'GET')
        self.assertIsInstance(get, tuple)
        self.assertEqual(len(get), 3)
        self.assertEqual(get[1:], ('audio/wav', 'say.wav'))
        self.assertEqual(get[0][:4], b'RIFF')

    def test_prerender_counts_rendered_then_cached(self):
        res = T.ROUTES['prerender']({'phrases': ['One', 'Two']}, 'POST')
        self.assertEqual((res['rendered'], res['cached'], res['failed']), (2, 0, 0))
        res = T.ROUTES['prerender']({'phrases': ['One', 'Two']}, 'POST')
        self.assertEqual((res['rendered'], res['cached'], res['failed']), (0, 2, 0))

    def test_prerender_reports_a_failure_honestly(self):
        VS.synth = lambda *a, **k: None
        res = T.ROUTES['prerender']({'phrases': ['Nope']}, 'POST')
        self.assertFalse(res['ok'])
        self.assertEqual(res['failed'], 1)

    def test_cache_route_counts_what_is_on_disk(self):
        T.say('Done')
        res = T.ROUTES['cache']({}, 'GET')
        self.assertGreaterEqual(res['count'], 1)
        self.assertGreater(res['bytes'], 44)
        self.assertEqual(res['dir'], T.SAY_DIR)


class TestContract(_Base):
    def test_routes_are_the_five_the_contract_names(self):
        self.assertEqual(sorted(T.ROUTES), ['cache', 'config', 'prerender', 'say', 'voices'])
        for name, fn in T.ROUTES.items():
            self.assertTrue(callable(fn), name)

    def test_kokoro_is_not_referenced(self):
        path = _tree.pkg('voice_ext', 'tts.py')
        with open(path, encoding='utf-8') as f:
            src = f.read().lower()
        # Named once in the module docstring as retired policy, and once in a
        # test fixture as a rejected engine value. Never imported or dispatched.
        self.assertNotIn('import kokoro', src)
        self.assertNotIn("'kokoro'", src)

    def test_reply_format_is_the_documented_one(self):
        self.assertEqual((T.LUFS, T.SR, T.GAP_MS), (-16.0, 24000, 250))


if __name__ == '__main__':
    unittest.main()
