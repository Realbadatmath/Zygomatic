# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_assign.py — "Assign a voice": which characters and workflows a Voices-tab
voice is attached to.

WHAT THIS IS
------------
One durable registry (data/assets/voice_assignments.json) mapping a TARGET — a
character id, or a workflow/channel/series key from the Kanban board picker — to
one voice studio voice. A target has exactly ONE voice: a character does not
speak with two, and reassigning is a move, not an add.

TWO KINDS OF CONNECTION, AND WHY THEY ARE DRAWN DIFFERENTLY
-----------------------------------------------------------
The panel shows a green check for a connection and a link glyph beside it for a
LIVE one, because those are genuinely different claims:

  saved (check)          this registry says so. Nothing in the narration path
                         reads it yet — same standing as the preset store, whose
                         inertness voice_studio's docstring promises. It is a
                         record of intent and the seam production would read.

  live  (check + link)   production config ALREADY routes this voice there, and
                         we can prove it by reading that config:
                           · a character bible's voice_profile.character_voice,
                             resolved through the real seed pick (voice_pool —
                             the same function tts_service calls, not a copy);
                           · the briefing channels' seed names in
                             market_ingest / sports_ingest settings;
                           · a scene/series that names a seed wav outright.

Collapsing the two would be the lie that matters here: a checkbox that looks
like it re-voiced a running channel, when in fact it wrote a line to a JSON file
nobody reads. So the check means "connected", the link means "connected AND the
pipeline already does it", and a row whose live voice differs from the saved one
says so out loud rather than picking a winner.

WHAT SAVING DOES NOT DO
-----------------------
It does not edit character bibles, market_settings.json or sports_settings.json.
Re-voicing a running channel from a checkbox is an outward-facing change to
published output, and the adoption seam (assigned_for) is deliberately left for a
caller to opt into — exactly as active_params() is.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_CHARS_ROOT = os.path.realpath(paths.ZYG_STORYTELLER_CHARS)
_KANBAN_HTML = os.path.join(_HERE, 'kanban.html')
_SERIES_JSON = os.path.join(_HERE, 'data', 'runtime', 'storyteller_templates.json')

ASSIGN_PATH = os.path.join(_HERE, 'data', 'assets', 'voice_assignments.json')

# Character ids are the same shape kanban_server validates: they become dict keys
# in a file we rewrite, so anything unexpected is dropped rather than sanitised.
_CID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_WFK_RE = re.compile(r'^[a-z0-9][a-z0-9_]{0,63}$')

_LOCK = threading.Lock()
_CACHE: dict = {'wf': None, 'wf_ts': 0.0, 'chars': None, 'chars_ts': 0.0}


# ─────────────────────────────────────────────────────────────── the registry
def _empty() -> dict:
    return {'schema': 1, 'characters': {}, 'workflows': {}}


def load() -> dict:
    """The registry, always in the full shape. Never raises: a corrupt file costs
    the assignments, not the tab."""
    try:
        with open(ASSIGN_PATH, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(doc, dict):
        return _empty()
    out = _empty()
    for kind in ('characters', 'workflows'):
        rows = doc.get(kind)
        if not isinstance(rows, dict):
            continue
        for key, rec in rows.items():
            if isinstance(rec, dict) and rec.get('voice'):
                out[kind][str(key)] = {
                    'voice': str(rec.get('voice') or ''),
                    'preset': str(rec.get('preset') or ''),
                    'updated': str(rec.get('updated') or ''),
                }
    return out


def _write(doc: dict) -> None:
    os.makedirs(os.path.dirname(ASSIGN_PATH), exist_ok=True)
    tmp = ASSIGN_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    os.replace(tmp, ASSIGN_PATH)


def assigned_for(kind: str, key: str) -> dict:
    """The adoption seam. {'voice': …, 'preset': …} for one target, or {}.

    No production caller reads this yet — see the module docstring. It is the one
    function a pipeline would call to honour an assignment."""
    if kind not in ('characters', 'workflows'):
        return {}
    return dict(load()[kind].get(str(key)) or {})


# ──────────────────────────────────────────────────────── the target catalogue
def characters() -> list:
    """Every CREATED character: an id directory carrying a character_bible.json.

    Bible-gated, not contact-sheet-gated (which is what the Inspection tab lists):
    a character exists as soon as it has a bible, and a voice is a property of the
    character, not of whether its sheet finished rendering."""
    now = time.monotonic()
    if _CACHE['chars'] is not None and now - _CACHE['chars_ts'] < 20.0:
        return _CACHE['chars']
    out = []
    try:
        entries = sorted(os.listdir(_CHARS_ROOT))
    except OSError:
        entries = []
    for cid in entries:
        if not _CID_RE.match(cid):
            continue
        bible = os.path.join(_CHARS_ROOT, cid, 'character_bible.json')
        try:
            with open(bible, encoding='utf-8') as f:
                b = json.load(f)
        except FileNotFoundError as _exc:
            _zyg_log.debug('no character bible for %s, skipping: %s', cid, _exc)
            continue
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('character bible %s unreadable, continuing without that character: %s', bible, _exc)
            continue
        ident = b.get('identity') or {}
        vp = b.get('voice_profile') or {}
        name = str(b.get('display_name') or ident.get('name') or '').strip()
        out.append(
            {
                'key': cid,
                # 10 bibles carry no display_name at all; the id is what the rest of
                # the GUI falls back to, so do the same rather than inventing one.
                'name': name or cid,
                'sub': ', '.join(
                    x
                    for x in (
                        str(ident.get('age') or '').strip(),
                        str(ident.get('sex') or ident.get('gender') or '').strip(),
                        str(ident.get('heritage') or '').strip(),
                    )
                    if x
                )
                or cid,
                'voice_id': str(vp.get('character_voice') or '').strip(),
                'updated': str(b.get('updated_at') or b.get('created_at') or ''),
            }
        )
    out.sort(key=lambda r: (r['name'] == r['key'], r['name'].lower()))
    _CACHE['chars'], _CACHE['chars_ts'] = out, now
    return out


# The board picker in kanban.html IS the operator's list of workflows, so parse
# it rather than keeping a second list that drifts the day a channel is added.
# The markup is ours and its shape is stable; a parse failure falls back to the
# pipelines below, which is a short list rather than an empty panel.
_WF_FALLBACK = [
    ('documentary', 'Documentary', 'Pipelines'),
    ('video', 'Video', 'Pipelines'),
    ('storyteller', 'Storyteller', 'Pipelines'),
    ('remix', 'Remix', 'Pipelines'),
    ('manga', 'Manga', 'Pipelines'),
    ('intro', 'Intro', 'Pipelines'),
]
# One pass, two alternatives: a section heading (which changes the current group)
# or an item carrying a data-key. Matching them together is what keeps items under
# the heading they were authored below.
_MENU_RE = re.compile(
    r'<div class="kb-ch-section">([^<]*)</div>|'
    r'<(?:div|span)\b([^>]*\bdata-key="[^"]+"[^>]*)>([^<]*)<'
)
_KEY_RE = re.compile(r'data-key="([^"]+)"')


def workflows() -> list:
    """[{key,name,group,sub}] — the pipelines, channels and prepared series."""
    now = time.monotonic()
    if _CACHE['wf'] is not None and now - _CACHE['wf_ts'] < 20.0:
        return _CACHE['wf']
    out, seen = [], set()
    try:
        with open(_KANBAN_HTML, encoding='utf-8') as f:
            doc = f.read()
        menu = doc.split('id="kb-ch-menu"', 1)[1].split('<!-- Flyout', 1)[0]
        group = 'Pipelines'
        for m in _MENU_RE.finditer(menu):
            if m.group(1) is not None:
                group = html.unescape(m.group(1)).strip() or group
                continue
            attrs, label = m.group(2), html.unescape(m.group(3) or '').strip()
            key = _KEY_RE.search(attrs).group(1)
            if key in seen or not _WFK_RE.match(key):
                continue
            seen.add(key)
            out.append(
                {'key': key, 'name': label or key, 'group': group, 'sub': 'sub-channel' if 'kb-ch-sub' in attrs else ''}
            )
    except Exception:  # noqa: BLE001 — a parse slip must not empty the panel
        out = [{'key': k, 'name': n, 'group': g, 'sub': ''} for k, n, g in _WF_FALLBACK]
        seen = {r['key'] for r in out}
    # The Video group's children are the prepared series, loaded into the picker
    # from an API rather than authored into the markup — so they have to be added
    # here or the flagship (The Second Ledger) would be missing from the panel.
    try:
        with open(_SERIES_JSON, encoding='utf-8') as f:
            for t in json.load(f).get('templates') or []:
                sid = str((t or {}).get('id') or '').strip()
                if not sid or sid in seen or not _WFK_RE.match(sid):
                    continue
                seen.add(sid)
                out.append(
                    {
                        'key': sid,
                        'name': str(t.get('series_title') or sid),
                        'group': 'Series',
                        'sub': '' if t.get('enabled', True) else 'disabled',
                    }
                )
    except (OSError, ValueError) as _exc:
        _zyg_log.warning(
            'series template list %s unreadable, continuing without the Series group: %s', _SERIES_JSON, _exc
        )
    _CACHE['wf'], _CACHE['wf_ts'] = out, now
    return out


# ─────────────────────────────────────────────────── live production routing
# Only entries whose voice can be READ OUT of live config belong here. A guess
# would print as a link glyph, which is the one thing that glyph must never be.
_BRIEFING_VOICE_KEY = {
    'ch_fin_stockmarket': ('market', 'stocks_voice'),
    'ch_fin_crypto': ('market', 'crypto_voice'),
    'ch_tokitoki': ('sports', 'tokitoki_voice'),
    'ch_arena': ('sports', 'arena_voice'),
}
# The sport sub-channels are the same department pipeline (pipeline_sports runs
# one THEMES row per channel), so they speak with their parent's seed.
for _p in ('soccer', 'nba', 'ufc', 'tennis', 'nfl'):
    _BRIEFING_VOICE_KEY[f'ch_tokitoki_{_p}'] = ('sports', 'tokitoki_voice')
    _BRIEFING_VOICE_KEY[f'ch_arena_{_p}'] = ('sports', 'arena_voice')


def _briefing_settings(which: str) -> dict:
    """Effective settings for a briefing department. Imported lazily and guarded:
    both modules only need `requests`, but a missing dependency must cost the link
    glyph, not the panel."""
    try:
        if which == 'market':
            from zyg_workflows import market_ingest

            return market_ingest.settings() or {}
        from zyg_workflows import sports_ingest

        return sports_ingest.settings() or {}
    except Exception:  # noqa: BLE001
        return {}


def _abel_seed_path() -> str:
    """Read the path rather than asserting the voice id: if abel_voice's seed ever
    moves, this reports the move instead of a stale claim."""
    try:
        from zyg_workflows import abel_voice

        return os.path.realpath(abel_voice.ABEL_SEED_WAV)
    except Exception:  # noqa: BLE001
        return ''


# Scenes/series that name a reference wav outright rather than routing through a
# voice id. storyteller_scene_service.SECOND_LEDGER_INTRO pins Abel's frozen seed
# ('ref': 'abel_seed'); importing that module here would pull the whole render
# stack into the web server, so the SEED PATH is resolved and matched instead.
_SEED_PINNED = {
    'st_second_ledger': ("storyteller_scene_service.SECOND_LEDGER_INTRO pins voices.abel.ref = 'abel_seed'"),
}


def _live_map(voice_seed_paths: dict) -> dict:
    """{workflow key: (voice_id, why)} for every workflow whose live voice can be
    read out of config. `voice_seed_paths` is {realpath: voice id} from the studio
    registry, so a match is on the actual FILE, not on a name that looks alike."""
    out = {}
    cache = {}
    for key, (which, skey) in _BRIEFING_VOICE_KEY.items():
        if which not in cache:
            cache[which] = _briefing_settings(which)
        seed_name = str(cache[which].get(skey) or '').strip()
        if not seed_name:
            continue
        # The briefing settings hold a POOL seed name; the studio's voice id for a
        # pool seed is that same name (voice_studio._load_pool_voices).
        out[key] = (seed_name, f'{which}_settings.{skey} = {seed_name}')
    abel = _abel_seed_path()
    if abel:
        vid = voice_seed_paths.get(abel, '')
        if vid:
            for key, why in _SEED_PINNED.items():
                out[key] = (vid, why)
    return out


def _char_live_voice(voice_id: str) -> str:
    """Which studio voice a character's stored voice id actually clones today.

    voice_pool.seed_name_for is the SAME pick tts_service makes — see that
    module's docstring for why this is an import and not a reimplementation."""
    if not voice_id:
        return ''
    try:
        from zyg_workflows import voice_pool

        return voice_pool.seed_name_for(voice_id)
    except Exception:  # noqa: BLE001
        return ''


# ────────────────────────────────────────────────────────────────── the view
def view(vid: str, voices: dict) -> dict:
    """Everything the Assign panel needs for one voice.

    `voices` is voice_studio.VOICES — used for the seed paths behind the live
    match and to name the voice a row is already connected to."""
    reg = load()
    names = {k: (v.get('name') or k) for k, v in (voices or {}).items()}
    seed_paths = {}
    for k, v in (voices or {}).items():
        try:
            seed_paths[os.path.realpath(v['seed'])] = k
        except (KeyError, TypeError) as _exc:
            _zyg_log.debug('voice %s has no usable seed path, not matched live: %s', k, _exc)
            continue
    live_wf = _live_map(seed_paths)

    def _decorate(row, kind, live_voice, live_why):
        key = row['key']
        rec = reg[kind].get(key) or {}
        saved_voice = rec.get('voice') or ''
        out = dict(row)
        out['saved'] = saved_voice == vid
        out['live'] = bool(live_voice) and live_voice == vid
        out['live_why'] = live_why if out['live'] else ''
        # A row already spoken for by ANOTHER voice is shown, not hidden: ticking
        # it is a re-voice, and the operator should see what they are replacing.
        other = ''
        other_how = ''
        if saved_voice and saved_voice != vid:
            other, other_how = saved_voice, 'assigned'
        elif live_voice and live_voice != vid:
            other, other_how = live_voice, 'live'
        out['other'] = other
        out['other_name'] = names.get(other, other)
        out['other_how'] = other_how
        out['preset'] = rec.get('preset', '') if out['saved'] else ''
        return out

    chars = [
        _decorate(c, 'characters', _char_live_voice(c['voice_id']), f'voice_profile.character_voice = {c["voice_id"]}')
        for c in characters()
    ]
    wfs = []
    for w in workflows():
        lv, why = live_wf.get(w['key'], ('', ''))
        wfs.append(_decorate(w, 'workflows', lv, why))
    return {
        'voice': vid,
        'characters': chars,
        'workflows': wfs,
        'counts': {
            'characters': sum(1 for r in chars if r['saved'] or r['live']),
            'workflows': sum(1 for r in wfs if r['saved'] or r['live']),
            'characters_total': len(chars),
            'workflows_total': len(wfs),
        },
    }


def save(vid: str, character_keys, workflow_keys, preset: str = '') -> dict:
    """The checked set becomes the truth FOR THIS VOICE.

    Unticking a row that this voice owned clears it; ticking a row owned by
    another voice moves it, because a target speaks with one voice. Rows this
    voice never owned and did not gain are untouched — saving Abel cannot disturb
    an assignment made under Warm Baritone.

    Unknown keys are rejected rather than written: the registry keys are read back
    as character ids and board keys, so an arbitrary string in there is a fact
    nothing can resolve."""
    if not vid:
        raise ValueError('no voice')
    known_c = {c['key'] for c in characters()}
    known_w = {w['key'] for w in workflows()}
    want_c = {str(k) for k in (character_keys or [])}
    want_w = {str(k) for k in (workflow_keys or [])}
    bad = (want_c - known_c) | (want_w - known_w)
    if bad:
        raise ValueError('unknown target: ' + ', '.join(sorted(bad)[:5]))
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    with _LOCK:
        doc = load()
        for kind, want in (('characters', want_c), ('workflows', want_w)):
            for key in [k for k, r in doc[kind].items() if r.get('voice') == vid and k not in want]:
                doc[kind].pop(key, None)
            for key in want:
                doc[kind][key] = {'voice': vid, 'preset': str(preset or ''), 'updated': now}
        _write(doc)
    return view(vid, _voices_for_view())


def _voices_for_view() -> dict:
    try:
        from zyg_workflows import voice_studio

        return voice_studio.VOICES
    except Exception:  # noqa: BLE001
        return {}


if __name__ == '__main__':  # the CLI lives in voice_assign_cli
    from zyg_workflows.voice_assign_cli import main as _cli_main

    raise SystemExit(_cli_main())
