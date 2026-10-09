#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The voice bridge seam: hello, utterance, ack, ext dispatch, client bundle.

    ../.venv/bin/python -m unittest tests.test_voice_bridge -v

No server, no microphone, no Whisper, no GPU: voice_stt and voice_brain are
replaced in sys.modules before the bridge's lazy imports reach them, and the
ledger is redirected to a temp file so a test run never writes into
data/runtime/voice_bridge/.
"""

import base64
import json
import os
import queue
import shutil
import sys
import tempfile
import time
import types
import unittest

import zyg_workflows
from tests import _tree
from zyg_workflows import voice_bridge as VB

_MISSING = object()

AUDIO_B64 = base64.b64encode(b'not really opus, and never decoded').decode()


def fake_stt(text='go to pictures', seconds=1.4):
    m = types.ModuleType('voice_stt')
    m.transcribe_utterance = lambda audio, mime='audio/webm', language='en': {
        'text': text,
        'seconds': seconds,
        'ms': 120,
        'device': 'cpu',
        'model': 'base',
    }
    return m


def fake_brain(actions, say='Pictures', tier='grammar'):
    m = types.ModuleType('voice_brain')
    m.seen = []

    def plan(text, ctx):
        m.seen.append((text, ctx))
        return {'actions': list(actions), 'say': say, 'tier': tier}

    m.plan = plan
    return m


class VoiceBridgeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vb_test_')
        self._ledger, VB.LEDGER_PATH = VB.LEDGER_PATH, os.path.join(self.tmp, 'ledger.jsonl')
        self._extdir, VB.EXT_DIR = VB.EXT_DIR, os.path.join(self.tmp, 'voice_ext')
        os.makedirs(VB.EXT_DIR, exist_ok=True)
        self._stubbed = []
        with VB._LOCK:
            VB._DRIVERS.clear()
            VB._LEDGER.clear()
            VB._BY_ACTION.clear()
            VB._TRANSCRIPTS.clear()
        VB._EXT_MODS.clear()

    def tearDown(self):
        VB.LEDGER_PATH = self._ledger
        VB.EXT_DIR = self._extdir
        for name, had_mod, mod, had_attr, attr in reversed(self._stubbed):
            if had_mod:
                sys.modules['zyg_workflows.' + name] = mod
            else:
                sys.modules.pop('zyg_workflows.' + name, None)
            if had_attr:
                setattr(zyg_workflows, name, attr)
            else:
                delattr_if = getattr(zyg_workflows, name, _MISSING)
                if delattr_if is not _MISSING:
                    delattr(zyg_workflows, name)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stub(self, name, obj):
        """Swap ``zyg_workflows.<name>`` for *obj* until tearDown; ``None`` -> ImportError.

        Both the sys.modules entry AND the package attribute are replaced. The attribute is
        the one that matters: once a submodule has been imported anywhere in the process,
        ``from zyg_workflows import voice_stt`` reads it off the package and never looks at
        sys.modules — so patching sys.modules alone made these tests pass on their own and
        fail in a full run, depending on what had already imported voice_stt.
        """
        dotted = 'zyg_workflows.' + name
        had_attr = hasattr(zyg_workflows, name)
        self._stubbed.append(
            (name, dotted in sys.modules, sys.modules.get(dotted), had_attr, getattr(zyg_workflows, name, None))
        )
        sys.modules[dotted] = obj
        if obj is None:
            if had_attr:
                delattr(zyg_workflows, name)
        else:
            setattr(zyg_workflows, name, obj)

    def ledger_lines(self):
        if not os.path.exists(VB.LEDGER_PATH):
            return []
        with open(VB.LEDGER_PATH, encoding='utf-8') as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]

    # ── hello ──────────────────────────────────────────────────────────────
    def test_hello_stores_the_registry(self):
        reg = [
            {
                'name': 'pictures.open',
                'view': 'pictures',
                'label': 'Open pictures',
                'aliases': ['open pictures', 'show me the pictures'],
                'args': None,
            },
            {
                'name': 'videos.rate',
                'view': 'videos',
                'label': 'Playback rate',
                'aliases': ['set the rate'],
                'args': {'value': 'number 0..1'},
            },
        ]
        out, code = VB.handle_post('/inspect/api/voice/hello', {'driver': 'tok-1', 'registry': reg, 'view': 'home'})
        self.assertEqual(code, 200)
        self.assertTrue(out['ok'])
        self.assertEqual(out['actions'], 2)
        self.assertIn('driver=tok-1', out['events'])

        stored = VB._driver('tok-1')['registry']
        self.assertEqual([r['name'] for r in stored], ['pictures.open', 'videos.rate'])
        self.assertEqual(stored[1]['args'], {'value': 'number 0..1'})
        self.assertEqual(stored[0]['aliases'], ['open pictures', 'show me the pictures'])

        state, code = VB.handle_get('/inspect/api/voice/state', {})
        self.assertEqual(code, 200)
        self.assertEqual([d['driver'] for d in state['drivers']], ['tok-1'])
        self.assertEqual(state['drivers'][0]['view'], 'home')

    def test_hello_refuses_a_bad_token(self):
        out, code = VB.handle_post('/inspect/api/voice/hello', {'driver': 'tok 1/../x'})
        self.assertEqual(code, 400)
        self.assertFalse(out['ok'])

    # ── utterance ──────────────────────────────────────────────────────────
    def test_utterance_returns_actions_and_pushes_them_to_the_queue(self):
        VB.handle_post(
            '/inspect/api/voice/hello',
            {
                'driver': 'tok-2',
                'view': 'home',
                'registry': [
                    {'name': 'pictures.open', 'view': 'pictures', 'label': 'Open pictures', 'aliases': ['pictures']}
                ],
            },
        )
        self.stub('voice_stt', fake_stt('go to pictures'))
        brain = fake_brain([{'name': 'pictures.open', 'args': None}], say='Pictures')
        self.stub('voice_brain', brain)

        out, code = VB.handle_post(
            '/inspect/api/voice/utterance',
            {'driver': 'tok-2', 'audio_b64': AUDIO_B64, 'mime': 'audio/webm', 'view': 'home'},
        )
        self.assertEqual(code, 200)
        self.assertTrue(out['ok'])
        self.assertEqual(out['text'], 'go to pictures')
        self.assertEqual(out['tier'], 'grammar')
        self.assertIsNone(out['speaker'])  # no speaker ext -> gate not armed
        self.assertEqual(len(out['actions']), 1)
        aid = out['actions'][0]['id']
        self.assertEqual(len(aid), 12)
        self.assertEqual(out['say']['text'], 'Pictures')
        self.assertEqual(out['say']['wav'], '/inspect/api/voice/ext/tts/say?text=Pictures')

        # the brain saw the driver's cached registry and the current view
        text, ctx = brain.seen[0]
        self.assertEqual(text, 'go to pictures')
        self.assertEqual(ctx['view'], 'home')
        self.assertEqual([r['name'] for r in ctx['registry']], ['pictures.open'])

        # ...and the same action is waiting on the driver's SSE queue, then the say
        q = VB._driver('tok-2')['queue']
        ev, data = q.get_nowait()
        self.assertEqual(ev, 'action')
        self.assertEqual(data['id'], aid)
        self.assertEqual(data['name'], 'pictures.open')
        ev2, data2 = q.get_nowait()
        self.assertEqual(ev2, 'say')
        self.assertEqual(data2['text'], 'Pictures')
        self.assertRaises(queue.Empty, q.get_nowait)

    def test_utterance_without_stt_is_503(self):
        real = _tree.pkg('voice_stt.py')
        self.stub('voice_stt', None)  # import -> ImportError
        out, code = VB.handle_post('/inspect/api/voice/utterance', {'driver': 'tok-3', 'audio_b64': AUDIO_B64})
        self.assertTrue(os.path.exists(real))  # the module the seam names
        self.assertEqual(code, 503)
        self.assertEqual(out['error'], 'stt unavailable')

    def test_utterance_without_a_brain_is_tier_none(self):
        self.stub('voice_stt', fake_stt('do something clever'))
        self.stub('voice_brain', None)  # import -> ImportError
        out, code = VB.handle_post('/inspect/api/voice/utterance', {'driver': 'tok-4', 'audio_b64': AUDIO_B64})
        self.assertEqual(code, 200)
        self.assertEqual(out['tier'], 'none')
        self.assertEqual(out['actions'], [])
        self.assertTrue(out['brain_error'])

    def test_an_unaccepted_speaker_gets_no_actions(self):
        with open(os.path.join(VB.EXT_DIR, 'speaker.py'), 'w', encoding='utf-8') as fh:
            fh.write(
                'ROUTES = {\n'
                " 'list': lambda p, m: {'ok': True, 'speakers': ['adriaan']},\n"
                " 'verify': lambda p, m: {'name': 'stranger', 'score': 0.11,\n"
                "                         'accepted': False},\n"
                '}\n'
            )
        self.stub('voice_stt', fake_stt('delete every render'))
        self.stub('voice_brain', fake_brain([{'name': 'pictures.open'}]))
        out, code = VB.handle_post('/inspect/api/voice/utterance', {'driver': 'tok-5', 'audio_b64': AUDIO_B64})
        self.assertEqual(code, 200)
        self.assertEqual(out['actions'], [])
        self.assertEqual(out['tier'], 'none')
        self.assertEqual(out['speaker'], {'name': 'stranger', 'score': 0.11, 'accepted': False})
        self.assertEqual(out['say']['text'], 'I only take commands from an enrolled voice')

    # ── ack ────────────────────────────────────────────────────────────────
    def test_ack_lands_in_the_ledger(self):
        self.stub('voice_stt', fake_stt('go to pictures'))
        self.stub('voice_brain', fake_brain([{'name': 'pictures.open'}]))
        out, _ = VB.handle_post('/inspect/api/voice/utterance', {'driver': 'tok-6', 'audio_b64': AUDIO_B64})
        aid = out['actions'][0]['id']

        ack, code = VB.handle_post(
            '/inspect/api/voice/ack',
            {'driver': 'tok-6', 'id': aid, 'ok': True, 'detail': 'view is pictures', 'view': 'pictures'},
        )
        self.assertEqual(code, 200)
        self.assertTrue(ack['matched'])

        # in memory: the utterance entry now carries the ack
        entries, code = VB.handle_get('/inspect/api/voice/ledger', {'n': '50'})
        self.assertEqual(code, 200)
        utt = [e for e in entries['entries'] if e['kind'] == 'utterance'][-1]
        self.assertEqual(utt['driver'], 'tok-6')
        self.assertEqual(utt['text'], 'go to pictures')
        self.assertEqual(len(utt['acks']), 1)
        self.assertEqual(utt['acks'][0]['id'], aid)
        self.assertTrue(utt['acks'][0]['ok'])

        # on disk: two lines, the utterance and the ack's own line
        lines = self.ledger_lines()
        self.assertEqual([ln['kind'] for ln in lines], ['utterance', 'ack'])
        self.assertEqual(lines[1]['acks'][0]['detail'], 'view is pictures')

    def test_ack_for_an_unknown_id_still_logs(self):
        ack, code = VB.handle_post(
            '/inspect/api/voice/ack', {'driver': 'tok-7', 'id': 'deadbeefcafe', 'ok': False, 'error': 'no such control'}
        )
        self.assertEqual(code, 200)
        self.assertFalse(ack['matched'])
        self.assertEqual(self.ledger_lines()[0]['acks'][0]['error'], 'no such control')

    # ── say / action by hand ───────────────────────────────────────────────
    def test_say_and_action_queue_events(self):
        out, code = VB.handle_post('/inspect/api/voice/say', {'driver': 'tok-8', 'text': 'rate is 1.5'})
        self.assertEqual(code, 200)
        self.assertTrue(out['queued'])
        self.assertEqual(out['wav'], '/inspect/api/voice/ext/tts/say?text=rate%20is%201.5')
        act, code = VB.handle_post(
            '/inspect/api/voice/action',
            {'driver': 'tok-8', 'name': 'videos.rate', 'args': {'value': 1.5}, 'say': 'done'},
        )
        self.assertEqual(code, 200)
        q = VB._driver('tok-8')['queue']
        self.assertEqual(q.get_nowait()[0], 'say')
        ev, data = q.get_nowait()
        self.assertEqual((ev, data['name'], data['args']), ('action', 'videos.rate', {'value': 1.5}))
        self.assertEqual(q.get_nowait()[0], 'say')
        state, _ = VB.handle_get('/inspect/api/voice/state', {})
        self.assertEqual(state['queue_depth'], 0)
        self.assertEqual(act['name'], 'videos.rate')

    # ── ext dispatch ───────────────────────────────────────────────────────
    def test_ext_dispatch_loads_and_reloads_on_mtime(self):
        path = os.path.join(VB.EXT_DIR, 'tts.py')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write("ROUTES = {'say': lambda p, m: {'ok': True, 'v': 1, 'text': p.get('text', ''), 'method': m}}\n")
        out, code = VB.handle_get('/inspect/api/voice/ext/tts/say', {'text': 'hello'})
        self.assertEqual(code, 200)
        self.assertEqual((out['v'], out['text'], out['method']), (1, 'hello', 'GET'))

        # same file, new content, moved mtime -> the module is re-imported
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write("ROUTES = {'say': lambda p, m: {'ok': True, 'v': 2, 'text': p.get('text', ''), 'method': m}}\n")
        os.utime(path, (time.time() + 2, time.time() + 2))
        out, code = VB.handle_post('/inspect/api/voice/ext/tts/say', {'text': 'again'})
        self.assertEqual(code, 200)
        self.assertEqual((out['v'], out['text'], out['method']), (2, 'again', 'POST'))

        listing, code = VB.handle_get('/inspect/api/voice/ext', {})
        self.assertEqual(code, 200)
        self.assertEqual(listing['ext'], {'tts': ['say']})

    def test_ext_can_return_bytes(self):
        with open(os.path.join(VB.EXT_DIR, 'tts.py'), 'w', encoding='utf-8') as fh:
            fh.write("ROUTES = {'say': lambda p, m: (b'RIFFxxxx', 'audio/wav', 'say.wav')}\n")
        res = VB.handle_get('/inspect/api/voice/ext/tts/say', {'text': 'x'})
        self.assertEqual(res, (b'RIFFxxxx', 'audio/wav', 'say.wav'))

    def test_unknown_ext_is_404(self):
        out, code = VB.handle_get('/inspect/api/voice/ext/nope/say', {})
        self.assertEqual(code, 404)
        out, code = VB.handle_post('/inspect/api/voice/nonsense', {})
        self.assertEqual(code, 404)

    # ── client bundle ──────────────────────────────────────────────────────
    def test_bundle_starts_with_window_vb(self):
        with open(os.path.join(VB.EXT_DIR, 'b_two.js'), 'w', encoding='utf-8') as fh:
            fh.write("VB.actions['videos.rate'] = {};\n")
        with open(os.path.join(VB.EXT_DIR, 'a_one.js'), 'w', encoding='utf-8') as fh:
            fh.write("VB.actions['pictures.open'] = {};\n")
        js = VB.bundle_js()
        self.assertTrue(js.startswith('window.VB'), js[:80])
        self.assertIn('window.VB = window.VB || {actions:{}, aliases:{}, ready:[], views:{}};', js)
        self.assertLess(js.index('a_one.js'), js.index('b_two.js'))  # name order
        self.assertEqual(js.count('try {'), 2)
        self.assertIn('catch (e)', js)

    def test_bundle_of_an_empty_dir_is_just_the_preamble(self):
        js = VB.bundle_js()
        self.assertTrue(js.startswith('window.VB'))
        self.assertNotIn('try {', js)


if __name__ == '__main__':
    unittest.main()
