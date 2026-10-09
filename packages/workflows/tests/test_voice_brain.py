# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for voice_brain.plan — grammar / arch / llm / none tiers.

No GPU, no model, no network: the llm tier is reached only with
`voice_brain.llm_audit` and `voice_brain.free_vram_mb` monkeypatched.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import voice_brain as VB  # noqa: E402


def registry():
    """A small but representative VB.actions registry."""
    return [
        {
            'name': 'videos.rate',
            'view': 'videos',
            'label': 'Playback rate',
            'aliases': ['set rate to', 'set rate', 'playback rate'],
            'args': {'value': 'number 0.25..4'},
            'say': 'Rate set',
        },
        {'name': 'videos.play', 'view': 'videos', 'label': 'Play', 'aliases': ['play'], 'args': None, 'say': 'Playing'},
        {
            'name': 'videos.play_all',
            'view': 'videos',
            'label': 'Play all',
            'aliases': ['play all'],
            'args': None,
            'say': 'Playing all',
        },
        {'name': 'videos.undo', 'view': 'videos', 'label': 'Undo', 'aliases': ['undo last'], 'args': None},
        {
            'name': 'videos.render',
            'view': 'videos',
            'label': 'Render clip',
            'aliases': ['render the clip'],
            'args': None,
        },
        {'name': 'videos.trim', 'view': 'videos', 'label': 'Trim', 'aliases': ['trim'], 'args': None},
        {'name': 'videos.export', 'view': 'videos', 'label': 'Export', 'aliases': ['export'], 'args': None},
        {'name': 'videos.loop', 'view': 'videos', 'label': 'Loop', 'aliases': ['loop it'], 'args': None},
        {
            'name': 'pictures.opacity',
            'view': 'pictures',
            'label': 'Opacity',
            'aliases': ['set opacity to'],
            'args': {'value': 'number 0..1'},
        },
        {
            'name': 'musicstudio.volume',
            'view': 'musicstudio',
            'label': 'Volume',
            'aliases': ['set volume to'],
            'args': {'value': 'percent 0..100'},
        },
    ]


class Base(unittest.TestCase):
    """Keeps a real data/runtime/voice_bridge/config.json out of the tests."""

    def setUp(self):
        self._cfg = VB.CONFIG_PATH
        VB.CONFIG_PATH = os.path.join(tempfile.gettempdir(), 'voice_brain_no_such_config.json')

    def tearDown(self):
        VB.CONFIG_PATH = self._cfg


class TestGrammar(Base):
    def test_alias_no_args(self):
        got = VB.plan('render the clip', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['tier'], 'grammar')
        self.assertEqual(got['actions'], [{'name': 'videos.render', 'args': {}}])

    def test_say_falls_back_to_done(self):
        got = VB.plan('trim', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['say'], VB.SAY_DONE)

    def test_entry_say_is_used(self):
        got = VB.plan('play', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['say'], 'Playing')

    def test_longest_alias_wins(self):
        got = VB.plan('play all', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['actions'][0]['name'], 'videos.play_all')

    def test_decimal_number_fills_arg(self):
        got = VB.plan('set rate to 1.5', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['tier'], 'grammar')
        self.assertEqual(got['actions'], [{'name': 'videos.rate', 'args': {'value': 1.5}}])

    def test_spelled_tens_number(self):
        got = VB.plan('set volume to seventy percent', {'view': 'musicstudio', 'registry': registry()})
        self.assertEqual(got['actions'], [{'name': 'musicstudio.volume', 'args': {'value': 70}}])

    def test_spelled_compound_number(self):
        got = VB.plan('set volume to seventy five', {'view': 'musicstudio', 'registry': registry()})
        self.assertEqual(got['actions'][0]['args'], {'value': 75})

    def test_spelled_fraction_half(self):
        got = VB.plan('set opacity to half', {'view': 'pictures', 'registry': registry()})
        self.assertEqual(got['actions'][0]['args'], {'value': 0.5})

    def test_spelled_fraction_quarter(self):
        got = VB.plan('set opacity to a quarter', {'view': 'pictures', 'registry': registry()})
        self.assertEqual(got['actions'][0]['args'], {'value': 0.25})

    def test_missing_number_asks_which_value(self):
        got = VB.plan('set rate', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['tier'], 'grammar')
        self.assertEqual(got['actions'], [])
        self.assertEqual(got['say'], VB.SAY_WHICH_VALUE)

    def test_punctuation_and_case_are_ignored(self):
        got = VB.plan('Render the clip, please!', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['actions'][0]['name'], 'videos.render')

    def test_wake_prefix_hey_zero(self):
        got = VB.plan('hey zero, play all', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['actions'][0]['name'], 'videos.play_all')

    def test_wake_prefix_zero(self):
        got = VB.plan('zero stop', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['actions'], [{'name': 'core.stop', 'args': {}}])
        self.assertEqual(got['say'], VB.SAY_STOPPED)

    def test_wake_prefix_assistant(self):
        got = VB.plan('assistant export', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['actions'][0]['name'], 'videos.export')

    def test_require_prefix_rejects_bare_utterance(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
            json.dump({'require_prefix': True}, fh)
            path = fh.name
        VB.CONFIG_PATH = path
        try:
            bare = VB.plan('export', {'view': 'videos', 'registry': registry()})
            waked = VB.plan('zero export', {'view': 'videos', 'registry': registry()})
        finally:
            os.unlink(path)
        self.assertEqual(bare['tier'], 'none')
        self.assertEqual(bare['say'], VB.SAY_UNHEARD)
        self.assertEqual(waked['actions'][0]['name'], 'videos.export')

    def test_cancel_stops(self):
        got = VB.plan('cancel', {'view': 'pictures', 'registry': registry()})
        self.assertEqual(got['actions'], [{'name': 'core.stop', 'args': {}}])

    def test_undo_when_registered(self):
        got = VB.plan('undo', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['actions'], [{'name': 'videos.undo', 'args': {}}])
        self.assertEqual(got['say'], VB.SAY_UNDONE)

    def test_undo_when_not_registered(self):
        got = VB.plan('undo', {'view': 'pictures', 'registry': registry()})
        self.assertEqual(got['actions'], [])
        self.assertEqual(got['say'], VB.SAY_NO_CONTROL)

    def test_what_can_you_do_here(self):
        got = VB.plan('what can you do here', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['tier'], 'grammar')
        self.assertEqual(got['actions'], [])
        self.assertTrue(got['say'].startswith('8 actions here: '))
        self.assertEqual(len(got['say'].split(': ', 1)[1].split(', ')), 5)

    def test_empty_utterance(self):
        got = VB.plan('   ', {'view': 'videos', 'registry': registry()})
        self.assertEqual(got['tier'], 'none')


class TestNavigation(Base):
    CASES = {
        'video studio': 'videos',
        'videos': 'videos',
        'picture studio': 'pictures',
        'pictures': 'pictures',
        'character studio': 'charstudio',
        'creature studio': 'creatures',
        'creatures': 'creatures',
        'movement studio': 'movement',
        'voice studio': 'voices1',
        'voices': 'voices1',
        'music studio': 'musicstudio',
        'melody studio': 'music',
        'melody': 'music',
        'sfx studio': 'sfx',
        'sound effects': 'sfx',
        'vfx studio': 'vfx',
        'effects': 'vfx',
        'architecture studio': 'architecture',
        'architecture': 'architecture',
        'mesh': 'mesh',
        'library': 'inspections',
        'settings': 'settings',
        'home': 'home',
    }

    def test_every_spoken_name(self):
        for spoken, view in self.CASES.items():
            with self.subTest(spoken=spoken):
                got = VB.plan('go to the ' + spoken, {'view': 'home', 'registry': registry()})
                self.assertEqual(got['tier'], 'grammar')
                self.assertEqual(got['actions'], [{'name': 'nav.' + view, 'args': {}}])
                self.assertEqual(got['say'], 'Opening ' + VB.VIEW_NAMES[view])

    def test_every_view_id_is_reachable(self):
        self.assertEqual(set(self.CASES.values()), set(VB.VIEW_NAMES))

    def test_all_nav_verbs(self):
        for verb in ('go to', 'open', 'navigate to', 'show me'):
            with self.subTest(verb=verb):
                got = VB.plan(verb + ' the picture studio', {'view': 'home', 'registry': registry()})
                self.assertEqual(got['actions'][0]['name'], 'nav.pictures')

    def test_sound_effects_beats_effects(self):
        got = VB.plan('open sound effects', {'view': 'home', 'registry': registry()})
        self.assertEqual(got['actions'][0]['name'], 'nav.sfx')


class TestArch(Base):
    def test_drawing_verb_hands_off(self):
        got = VB.plan('build a two storey tower on the north corner', {'view': 'architecture', 'registry': registry()})
        self.assertEqual(got['tier'], 'arch')
        self.assertEqual(got['say'], VB.SAY_ARCH)
        self.assertEqual(
            got['actions'],
            [{'name': 'architecture.assist', 'args': {'text': 'build a two storey tower on the north corner'}}],
        )

    def test_every_drawing_verb(self):
        for verb in VB.ARCH_VERBS:
            with self.subTest(verb=verb):
                got = VB.plan(verb + ' a low stone wall', {'view': 'architecture', 'registry': registry()})
                self.assertEqual(got['tier'], 'arch')

    def test_not_arch_outside_architecture_view(self):
        calls = []

        class FakeAudit:
            @staticmethod
            def ollama_generate(*a, **k):
                calls.append(a)
                return '{"actions": [], "say": ""}'

        real_audit, real_vram = VB.llm_audit, VB.free_vram_mb
        VB.llm_audit, VB.free_vram_mb = FakeAudit, (lambda: 24000)
        try:
            got = VB.plan('build a low stone wall', {'view': 'videos', 'registry': registry()})
        finally:
            VB.llm_audit, VB.free_vram_mb = real_audit, real_vram
        self.assertEqual(got['tier'], 'none')
        self.assertEqual(len(calls), 1)

    def test_grammar_wins_over_arch(self):
        reg = registry() + [
            {
                'name': 'architecture.undo_last',
                'view': 'architecture',
                'label': 'Remove last',
                'aliases': ['remove the last box'],
                'args': None,
            }
        ]
        got = VB.plan('remove the last box', {'view': 'architecture', 'registry': reg})
        self.assertEqual(got['tier'], 'grammar')
        self.assertEqual(got['actions'][0]['name'], 'architecture.undo_last')


class FakeAudit:
    """Stands in for llm_audit.ollama_generate."""

    def __init__(self, reply=None, raises=None):
        self.reply, self.raises, self.kwargs = reply, raises, None

    def ollama_generate(self, model, prompt, **kwargs):
        self.model, self.prompt, self.kwargs = model, prompt, kwargs
        if self.raises:
            raise self.raises
        return self.reply


class TestLlm(Base):
    def _plan(self, text, fake, vram=24000, view='videos'):
        real_audit, real_vram = VB.llm_audit, VB.free_vram_mb
        VB.llm_audit, VB.free_vram_mb = fake, (lambda: vram)
        try:
            return VB.plan(text, {'view': view, 'registry': registry()})
        finally:
            VB.llm_audit, VB.free_vram_mb = real_audit, real_vram

    def test_valid_reply(self):
        fake = FakeAudit('{"actions":[{"name":"videos.export","args":{}}],"say":"Exporting"}')
        got = self._plan('put that on disk for me', fake)
        self.assertEqual(got['tier'], 'llm')
        self.assertEqual(got['actions'], [{'name': 'videos.export', 'args': {}}])
        self.assertEqual(got['say'], 'Exporting')
        self.assertEqual(fake.model, 'qwen3.5:9b')
        self.assertEqual(fake.kwargs['fmt'], 'json')
        self.assertEqual(fake.kwargs['keep_alive'], '30m')
        self.assertEqual(fake.kwargs['timeout'], 20)
        self.assertEqual(fake.kwargs['stage'], 'voice_brain')
        self.assertEqual(fake.kwargs['options'], {'temperature': 0, 'num_predict': 256})

    def test_prompt_only_carries_the_current_view(self):
        fake = FakeAudit('{"actions":[],"say":""}')
        self._plan('do the thing with the stuff', fake)
        self.assertIn('videos.export', fake.prompt)
        self.assertNotIn('pictures.opacity', fake.prompt)
        self.assertIn('nav.pictures', fake.prompt)

    def test_unknown_name_is_dropped(self):
        fake = FakeAudit('{"actions":[{"name":"videos.teleport","args":{}}],"say":"Teleporting"}')
        got = self._plan('teleport the clip sideways', fake)
        self.assertEqual(got['tier'], 'none')
        self.assertEqual(got['actions'], [])
        self.assertEqual(got['say'], VB.SAY_UNHEARD)

    def test_unknown_name_dropped_known_kept(self):
        fake = FakeAudit(
            '{"actions":[{"name":"videos.teleport","args":{}},{"name":"nav.pictures","args":{}}],"say":"Going"}'
        )
        got = self._plan('teleport then the other place', fake)
        self.assertEqual(got['tier'], 'llm')
        self.assertEqual(got['actions'], [{'name': 'nav.pictures', 'args': {}}])

    def test_ollama_down_is_none_and_busy(self):
        fake = FakeAudit(raises=OSError('connection refused'))
        got = self._plan('do the thing with the stuff', fake)
        self.assertEqual(got['tier'], 'none')
        self.assertEqual(got['actions'], [])
        self.assertEqual(got['say'], VB.SAY_BUSY)

    def test_low_vram_skips_the_tier(self):
        fake = FakeAudit('{"actions":[{"name":"videos.export","args":{}}],"say":"x"}')
        got = self._plan('do the thing with the stuff', fake, vram=4096)
        self.assertEqual(got['tier'], 'none')
        self.assertEqual(got['say'], VB.SAY_BUSY)
        self.assertIsNone(fake.kwargs)

    def test_junk_reply(self):
        got = self._plan('do the thing', FakeAudit('I am afraid I cannot'))
        self.assertEqual(got['tier'], 'none')

    def test_json_wrapped_in_prose(self):
        fake = FakeAudit('sure: {"actions":[{"name":"core.stop","args":{}}],"say":"Stopped"} ok')
        got = self._plan('kill whatever is running', fake)
        self.assertEqual(got['actions'], [{'name': 'core.stop', 'args': {}}])

    def test_empty_registry_never_calls_the_model(self):
        fake = FakeAudit('{"actions":[],"say":""}')
        real_audit, real_vram = VB.llm_audit, VB.free_vram_mb
        VB.llm_audit, VB.free_vram_mb = fake, (lambda: 24000)
        try:
            got = VB.plan('do the thing', {'view': 'videos', 'registry': []})
        finally:
            VB.llm_audit, VB.free_vram_mb = real_audit, real_vram
        self.assertEqual(got['tier'], 'none')
        self.assertIsNone(fake.kwargs)


class TestPhrases(Base):
    def test_every_view_has_an_opening_phrase(self):
        for view, name in VB.VIEW_NAMES.items():
            with self.subTest(view=view):
                self.assertIn('Opening ' + name, VB.PHRASES)

    def test_fixed_sentences_present(self):
        for phrase in (
            'Done',
            'Drawing that now',
            'I did not catch that',
            'The local model is busy',
            'I only take commands from an enrolled voice',
            'Stopped',
            'Undone',
            'Which value?',
            'That control is not on screen',
            'Listening',
            'Microphone off',
            'Enrolled your voice',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, VB.PHRASES)

    def test_no_duplicates_and_all_strings(self):
        self.assertEqual(len(VB.PHRASES), len(set(VB.PHRASES)))
        self.assertTrue(all(isinstance(p, str) and p for p in VB.PHRASES))


class TestShape(Base):
    def test_result_shape_is_stable(self):
        for text, view in (
            ('play', 'videos'),
            ('go to home', 'home'),
            ('build a wall', 'architecture'),
            ('', 'videos'),
        ):
            with self.subTest(text=text):
                got = VB.plan(text, {'view': view, 'registry': registry()})
                self.assertEqual(set(got), {'actions', 'say', 'tier'})
                self.assertIn(got['tier'], ('grammar', 'llm', 'arch', 'none'))
                self.assertIsInstance(got['say'], str)
                for act in got['actions']:
                    self.assertEqual(set(act), {'name', 'args'})
                    self.assertIsInstance(act['args'], dict)

    def test_missing_ctx_does_not_raise(self):
        self.assertEqual(VB.plan('play')['tier'], 'none')


if __name__ == '__main__':
    unittest.main()
