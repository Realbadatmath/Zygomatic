# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_brain.py — the utterance -> actions planner of the voice bridge.

Three tiers, cheapest first, so the common case never touches a model:

  'grammar'  no model at all, well under 5 ms: the utterance is normalised and
             matched against the aliases the studios registered (VB.actions) plus
             a handful of built-in intents (navigation, stop, undo, "what can you
             do here"). Longest alias wins; a spoken number fills a single
             numeric argument.
  'arch'     in Architecture Studio a drawing verb that matched no alias is handed
             to the arch assistant untouched (ONE `architecture.assist` action).
             This module never runs, configures or alters that assistant.
  'llm'      anything left, resolved locally by qwen3.5:9b through
             `llm_audit.ollama_generate` (so the call is recorded). Never
             Anthropic, never a paid API. Whatever it returns is validated
             against the registry before it can reach the page.
  'none'     nothing safe to do — `say` explains why.

The single entry point is `plan(text, ctx)`; `PHRASES` lists every fixed
sentence the assistant can speak so the pre-render task can synthesise them all
ahead of time.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from zyg_workflows.bin import exe

try:  # cheap (0.06 s) and pure-stdlib inside
    from zyg_workflows import llm_audit
except Exception:  # pragma: no cover - llm tier degrades
    llm_audit = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# static tables
# --------------------------------------------------------------------------- #

RUNTIME_DIR = os.path.join('data', 'runtime', 'voice_bridge')
CONFIG_PATH = os.path.join(RUNTIME_DIR, 'config.json')

OLLAMA_MODEL = 'qwen3.5:9b'
MIN_FREE_VRAM_MB = 8 * 1024

#: view id -> the human name spoken back ("Opening Video Studio").
VIEW_NAMES = {
    'videos': 'Video Studio',
    'pictures': 'Picture Studio',
    'charstudio': 'Character Studio',
    'creatures': 'Creature Studio',
    'movement': 'Movement Studio',
    'voices1': 'Voice Studio',
    'musicstudio': 'Music Studio',
    'music': 'Melody Studio',
    'sfx': 'SFX Studio',
    'vfx': 'VFX Studio',
    'architecture': 'Architecture Studio',
    'mesh': 'Mesh',
    'inspections': 'Library',
    'settings': 'Settings',
    'home': 'Home',
}

#: what the operator SAYS -> the view id goToView() takes.
NAV_SPOKEN = {
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

NAV_VERBS = ('navigate to', 'take me to', 'show me', 'switch to', 'go to', 'open')

WAKE_PREFIXES = ('hey zero', 'zero', 'assistant')

ARCH_VERBS = ('build', 'draw', 'add', 'place', 'put', 'make', 'create', 'remove', 'delete', 'raise', 'extend', 'design')

STOP_UTTERANCES = ('stop', 'stop it', 'stop that', 'cancel', 'cancel that')
UNDO_UTTERANCES = ('undo', 'undo that', 'undo it')
HELP_UTTERANCES = ('what can you do here', 'what can you do', 'what can i do here', 'help')

SAY_DONE = 'Done'
SAY_ARCH = 'Drawing that now'
SAY_UNHEARD = 'I did not catch that'
SAY_BUSY = 'The local model is busy'
SAY_STRANGER = 'I only take commands from an enrolled voice'
SAY_STOPPED = 'Stopped'
SAY_UNDONE = 'Undone'
SAY_WHICH_VALUE = 'Which value?'
SAY_NO_CONTROL = 'That control is not on screen'
SAY_LISTENING = 'Listening'
SAY_MIC_OFF = 'Microphone off'
SAY_ENROLLED = 'Enrolled your voice'

#: every fixed sentence the assistant can speak — the pre-render task walks this.
PHRASES = ['Opening {}'.format(name) for name in VIEW_NAMES.values()] + [
    SAY_DONE,
    SAY_ARCH,
    SAY_UNHEARD,
    SAY_BUSY,
    SAY_STRANGER,
    SAY_STOPPED,
    SAY_UNDONE,
    SAY_WHICH_VALUE,
    SAY_NO_CONTROL,
    SAY_LISTENING,
    SAY_MIC_OFF,
    SAY_ENROLLED,
]

# --------------------------------------------------------------------------- #
# text normalisation and number words
# --------------------------------------------------------------------------- #

_KEEP_RE = re.compile(r'[^a-z0-9. ]+')
_LONE_DOT_RE = re.compile(r'(?<!\d)\.|\.(?!\d)')
_WS_RE = re.compile(r'\s+')
_LITERAL_NUM_RE = re.compile(r'^\d+(?:\.\d+)?$')

_UNITS = {
    'zero': 0,
    'one': 1,
    'two': 2,
    'three': 3,
    'four': 4,
    'five': 5,
    'six': 6,
    'seven': 7,
    'eight': 8,
    'nine': 9,
    'ten': 10,
    'eleven': 11,
    'twelve': 12,
    'thirteen': 13,
    'fourteen': 14,
    'fifteen': 15,
    'sixteen': 16,
    'seventeen': 17,
    'eighteen': 18,
    'nineteen': 19,
}
_TENS = {
    'twenty': 20,
    'thirty': 30,
    'forty': 40,
    'fifty': 50,
    'sixty': 60,
    'seventy': 70,
    'eighty': 80,
    'ninety': 90,
}
_FRACTIONS = {'half': 0.5, 'quarter': 0.25}


def normalise(text):
    """Lower-case, punctuation-stripped text. Digits (incl. 1.5) survive."""
    s = (text or '').lower().replace('\u2019', "'")
    s = _KEEP_RE.sub(' ', s)
    s = _LONE_DOT_RE.sub(' ', s)
    return _WS_RE.sub(' ', s).strip()


def strip_wake_prefix(norm):
    """-> (text without the wake word, True if one was there)."""
    for prefix in WAKE_PREFIXES:
        if norm == prefix:
            return '', True
        if norm.startswith(prefix + ' '):
            return norm[len(prefix) + 1 :].strip(), True
    return norm, False


def _tidy_number(value):
    return int(value) if float(value).is_integer() else float(value)


def parse_number(norm):
    """First number in the utterance: 1.5, 'seventy', 'seventy five', 'half'."""
    tokens = norm.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _LITERAL_NUM_RE.match(tok):
            return _tidy_number(float(tok))
        if tok in _FRACTIONS:
            return _FRACTIONS[tok]
        if tok in _TENS:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ''
            if nxt in _UNITS and 1 <= _UNITS[nxt] <= 9:
                return _TENS[tok] + _UNITS[nxt]
            return _TENS[tok]
        if tok in _UNITS:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ''
            if nxt == 'hundred' and _UNITS[tok] == 1:
                return 100
            return _UNITS[tok]
        if tok in ('a', 'one') and i + 1 < len(tokens):
            if tokens[i + 1] in _FRACTIONS:
                return _FRACTIONS[tokens[i + 1]]
            if tokens[i + 1] == 'hundred':
                return 100
        if tok == 'hundred':
            return 100
        i += 1
    return None


def _has_phrase(norm, phrase):
    """Whole-word containment, so 'melody' does not match inside 'melodyx'."""
    if not phrase:
        return False
    return re.search(r'(?:^| )' + re.escape(phrase) + r'(?:$| )', norm) is not None


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def load_config(path=None):
    """data/runtime/voice_bridge/config.json, or {} when it is not there yet."""
    try:
        with open(path or CONFIG_PATH, 'r', encoding='utf-8') as fh:
            cfg = json.load(fh)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# result helpers
# --------------------------------------------------------------------------- #


def _result(actions, say, tier):
    return {'actions': list(actions), 'say': say, 'tier': tier}


def _none(say=SAY_UNHEARD):
    return _result([], say, 'none')


def _registry_names(registry):
    return {str(e.get('name')) for e in registry if e.get('name')}


# --------------------------------------------------------------------------- #
# tier: grammar
# --------------------------------------------------------------------------- #


def _nav_intent(norm):
    """'go to the picture studio' -> ('nav.pictures', 'Opening Picture Studio')."""
    target = None
    for verb in NAV_VERBS:
        if norm == verb:
            return None
        if norm.startswith(verb + ' '):
            target = norm[len(verb) + 1 :].strip()
            break
    if target is None:
        return None
    if target.startswith('the '):
        target = target[4:].strip()
    best = None
    for spoken, view in NAV_SPOKEN.items():
        if _has_phrase(target, spoken) and (best is None or len(spoken) > len(best[0])):
            best = (spoken, view)
    if best is None:
        return None
    view = best[1]
    return _result([{'name': 'nav.' + view, 'args': {}}], 'Opening {}'.format(VIEW_NAMES[view]), 'grammar')


def _builtin_intent(norm, view, registry):
    if norm in STOP_UTTERANCES:
        return _result([{'name': 'core.stop', 'args': {}}], SAY_STOPPED, 'grammar')
    if norm in UNDO_UTTERANCES:
        name = '{}.undo'.format(view)
        if name in _registry_names(registry):
            return _result([{'name': name, 'args': {}}], SAY_UNDONE, 'grammar')
        return _result([], SAY_NO_CONTROL, 'grammar')
    if norm in HELP_UTTERANCES:
        here = [e for e in registry if e.get('view') == view]
        labels = [str(e.get('label') or e.get('name')) for e in here[:5]]
        if not here:
            return _result([], 'No actions here yet', 'grammar')
        say = '{} actions here: {}'.format(len(here), ', '.join(labels))
        return _result([], say, 'grammar')
    return _nav_intent(norm)


def _numeric_arg_key(spec):
    """The single argument a spoken number may fill, or None."""
    if not isinstance(spec, dict) or not spec:
        return None
    numeric = [k for k, v in spec.items() if re.search(r'number|float|int|percent|0\.\.|\d', str(v or ''), re.I)]
    if len(numeric) == 1:
        return numeric[0]
    if not numeric and len(spec) == 1:
        return list(spec.keys())[0]
    return None


def _grammar_intent(norm, view, registry):
    """Longest registered alias wins; the current view breaks ties."""
    best = None
    for entry in registry:
        if not isinstance(entry, dict) or not entry.get('name'):
            continue
        for alias in entry.get('aliases') or []:
            alias_n = normalise(alias)
            if not alias_n or not _has_phrase(norm, alias_n):
                continue
            rank = (len(alias_n), 1 if entry.get('view') == view else 0)
            if best is None or rank > best[0]:
                best = (rank, entry)
    if best is None:
        return None
    entry = best[1]
    args = {}
    key = _numeric_arg_key(entry.get('args'))
    if key:
        value = parse_number(norm)
        if value is None:
            return _result([], SAY_WHICH_VALUE, 'grammar')
        args[key] = value
    say = str(entry.get('say') or SAY_DONE)
    return _result([{'name': str(entry['name']), 'args': args}], say, 'grammar')


# --------------------------------------------------------------------------- #
# tier: llm (local only)
# --------------------------------------------------------------------------- #


def free_vram_mb():
    """Free VRAM in MB, or None when nvidia-smi cannot say."""
    try:
        out = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    line = (out.stdout or '').strip().splitlines()
    if out.returncode != 0 or not line:
        return None
    try:
        return int(float(line[0].strip()))
    except Exception:
        return None


def build_prompt(text, view, registry):
    lines = []
    for entry in registry:
        if entry.get('view') != view or not entry.get('name'):
            continue
        spec = entry.get('args') or {}
        lines.append(
            '- {} | {} | args: {}'.format(
                entry['name'], entry.get('label') or entry['name'], json.dumps(spec, sort_keys=True)
            )
        )
    nav_names = sorted({'nav.' + v for v in VIEW_NAMES})
    return (
        'You map one spoken command to actions in a media production GUI.\n'
        'Current view: {view} ({name}).\n'
        'Actions available in this view:\n{acts}\n'
        'Navigation actions (always available): {nav}\n'
        'Also available: core.stop\n'
        'The operator said: "{text}"\n'
        'Reply with JSON only, exactly this schema:\n'
        '{{"actions":[{{"name":"...","args":{{}}}}],"say":"..."}}\n'
        'Use only names from the lists above. If nothing fits, return '
        '{{"actions":[],"say":""}}. Keep "say" under 12 words and write numbers '
        'as digits.'
    ).format(
        view=view,
        name=VIEW_NAMES.get(view, view),
        acts='\n'.join(lines) or '- (none)',
        nav=', '.join(nav_names),
        text=text,
    )


def _parse_llm_json(raw):
    if isinstance(raw, dict):
        return raw
    text = (raw or '').strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as _exc:
        _zyg_log.debug('llm reply is not plain json, looking for an embedded object: %s', _exc)
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def validate_actions(actions, registry):
    """Keep only names the page can actually run: registry, nav.*, core.*."""
    known = _registry_names(registry)
    allowed_nav = {'nav.' + v for v in VIEW_NAMES}
    out = []
    for item in actions or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '')
        if not name:
            continue
        ok = name in known or name in allowed_nav or name.startswith('core.')
        if not ok:
            continue
        args = item.get('args')
        out.append({'name': name, 'args': args if isinstance(args, dict) else {}})
    return out


def _llm_intent(text, view, registry):
    if llm_audit is None:
        return _none(SAY_BUSY)
    free = free_vram_mb()
    if free is not None and free < MIN_FREE_VRAM_MB:
        return _none(SAY_BUSY)
    try:
        raw = llm_audit.ollama_generate(
            OLLAMA_MODEL,
            build_prompt(text, view, registry),
            fmt='json',
            keep_alive='30m',
            timeout=20,
            stage='voice_brain',
            options={'temperature': 0, 'num_predict': 256},
        )
    except Exception:
        return _none(SAY_BUSY)
    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return _none()
    actions = validate_actions(data.get('actions'), registry)
    if not actions:
        return _none()
    say = str(data.get('say') or '').strip() or SAY_DONE
    return _result(actions, say, 'llm')


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def plan(text, ctx=None):
    """Plan one utterance.

    ctx = {'view': '<view id>', 'registry': [{name, view, label, aliases, args}]}
    -> {'actions': [{'name', 'args'}], 'say': str, 'tier': str}
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    view = str(ctx.get('view') or 'home')
    registry = [e for e in (ctx.get('registry') or []) if isinstance(e, dict)]
    raw_text = (text or '').strip()

    norm, had_prefix = strip_wake_prefix(normalise(raw_text))
    if load_config().get('require_prefix', False) and not had_prefix:
        return _none()
    if not norm:
        return _none()

    hit = _builtin_intent(norm, view, registry)
    if hit is not None:
        return hit

    hit = _grammar_intent(norm, view, registry)
    if hit is not None:
        return hit

    if view == 'architecture' and norm.split()[0] in ARCH_VERBS:
        # Handed to the arch assistant verbatim; this module never changes it.
        return _result([{'name': 'architecture.assist', 'args': {'text': raw_text}}], SAY_ARCH, 'arch')

    if not registry:
        return _none()
    return _llm_intent(raw_text, view, registry)
