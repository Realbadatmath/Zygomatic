# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""plugin_host.py — real VST3 DSP plugins as SFX Merger mixer-slot effect types
(2026-08-30), sitting alongside sfx_merger.EFFECT_TYPES's 'Tweaker'.

Where these plugins came from: audioz.download (the site the operator first
pointed at) is a piracy site distributing cracked commercial plugins — that
request was declined outright. What's wired in here is only openly-licensed,
Linux-native software downloaded from each project's own GitHub releases, at
$ZYG_HOME/audio-plugins — see that directory for the full set and their
licences (Surge XT, Cardinal, Dexed, LSP Plugins, Airwindows, Odin2, all
GPL/LGPL/MIT). Only LSP Plugins ended up wired into the mixer:

  * Cardinal's VST3 segfaulted once and hung once during evaluation, both in
    a headless load ("Failed to create Pugl view") — not safe to load inside
    a long-lived server process that also serves Voice Studio and the
    Workflows GUI.
  * Airwindows' Linux build is VST2 (.so, no .vst3/.ttl bundle) — pedalboard
    only hosts VST3 (and AU on macOS), so these never scan.
  * Surge XT Effects is a single meta-plugin whose own parameter ranges
    depend on an internal effect-type selector with no discoverable choice
    list via pedalboard's introspection — not safely automatable generically.
  * Dexed, Odin2, and Surge XT's synth are instruments (MIDI in, audio out).
    A mixer slot processes an existing SFX/voice layer — audio in, audio
    out — so an instrument has no meaningful place in this chain at all.

LSP Plugins is a large (198-plugin) suite of exactly the audio-in/audio-out
processors a mixer slot expects. Ten self-contained ones (no external sample/
IR dependency, no sidechain routing this pipeline doesn't wire up) are
registered below.

Isolation: every plugin call — introspection AND render — runs in
plugin_worker.py under a hard subprocess timeout, never inside this process.
See plugin_worker.py's docstring for why: this is defensive because
third-party native code was directly observed to be unstable during
evaluation, not because these ten specific plugins are known to be unsafe.

Failure mode: if pedalboard is missing, the LSP file has moved, or the first
introspection subprocess fails for any reason, EFFECT_TYPES is simply []
— sfx_merger still serves 'Tweaker' on its own, exactly like a malformed
voice manifest can't take the Voices tab down (voice_studio._load_pool_voices).
"""

import hashlib
import json
import os
import select
import subprocess
import sys
import threading
from zyg_workflows import paths
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.path.join(_HERE, 'plugin_worker.py')
_CACHE = os.path.join(_HERE, 'data', 'runtime', 'sfx_merger', 'plugin_racks_cache.json')
_LSP_VST3 = str(
    paths.ZYG_HOME
    / 'audio-plugins'
    / 'extracted'
    / 'lsp-plugins'
    / 'lsp-plugins-1.2.35-Linux-x86_64'
    / 'VST3'
    / 'lsp-plugins.vst3'
)
_INTROSPECT_TIMEOUT = 60
_RENDER_TIMEOUT = 30


class _Worker:
    """One persistent plugin_worker.py subprocess, kept alive across calls so
    the ~8 s LSP module scan happens once per server run, not once per knob
    twist. A single lock serializes calls (plugin renders queue behind each
    other; the existing ffmpeg-only Tweaker path is unaffected and keeps its
    own 3-way concurrency in sfx_merger._RENDER_SEM). A timeout or a dead
    process is treated the same way: kill it, drop it, raise — the NEXT call
    pays one fresh 8 s warm-up, the kanban-server itself never sees a crash."""

    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()

    def _ensure(self):
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                [sys.executable, _WORKER],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

    def _kill(self):
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.kill()
                p.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired) as _exc:
                _zyg_log.debug('plugin worker kill/wait skipped: %s', _exc)

    def call(self, req, timeout):
        with self.lock:
            self._ensure()
            try:
                self.proc.stdin.write(json.dumps(req) + '\n')
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._kill()
                raise ValueError(f'plugin worker pipe broke: {e}') from e
            ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
            if not ready:
                self._kill()
                raise ValueError('plugin worker timed out')
            line = self.proc.stdout.readline()
            if not line:
                err = ''
                try:
                    err = self.proc.stderr.read(2000) or ''
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('plugin worker stderr unreadable: %s', _exc)
                self._kill()
                raise ValueError(f'plugin worker died: {err[-400:]}')
            try:
                return json.loads(line)
            except ValueError as exc:
                self._kill()
                raise ValueError(f'plugin worker gave bad JSON: {line[:200]}') from exc


_WORKER_PROC = _Worker()

# id: kept short and stable — it IS the slot's 'type' and the key namespace
# scope (see sfx_merger._params_for), so renaming one orphans any slot saved
# with the old id (clean_slots drops unknown types, so that slot just goes
# inert rather than erroring).
_LSP_PLUGINS = [
    {
        'id': 'lsp_compressor',
        'title': 'Compressor (LSP)',
        'plugin_name': 'Compressor Stereo',
        'sub': 'lsp-plug.in — Compressor Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_limiter',
        'title': 'Limiter (LSP)',
        'plugin_name': 'Limiter Stereo',
        'sub': 'lsp-plug.in — Limiter Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_gate',
        'title': 'Gate (LSP)',
        'plugin_name': 'Gate Stereo',
        'sub': 'lsp-plug.in — Gate Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_chorus',
        'title': 'Chorus (LSP)',
        'plugin_name': 'Chorus Stereo',
        'sub': 'lsp-plug.in — Chorus Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_flanger',
        'title': 'Flanger (LSP)',
        'plugin_name': 'Flanger Stereo',
        'sub': 'lsp-plug.in — Flanger Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_phaser',
        'title': 'Phaser (LSP)',
        'plugin_name': 'Phaser Stereo',
        'sub': 'lsp-plug.in — Phaser Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_deesser',
        'title': 'De-esser (LSP)',
        'plugin_name': 'Deesser Stereo',
        'sub': 'lsp-plug.in — Deesser Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_clipper',
        'title': 'Clipper (LSP)',
        'plugin_name': 'Clipper Stereo',
        'sub': 'lsp-plug.in — Clipper Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_autogain',
        'title': 'Autogain (LSP)',
        'plugin_name': 'Autogain Stereo',
        'sub': 'lsp-plug.in — Autogain Stereo, LGPL-3.0.',
    },
    {
        'id': 'lsp_slapdelay',
        'title': 'Slapback Delay (LSP)',
        'plugin_name': 'Slapback Delay Stereo',
        'sub': 'lsp-plug.in — Slapback Delay Stereo, LGPL-3.0.',
    },
]
_BY_ID = {p['id']: p for p in _LSP_PLUGINS}


def _run_worker(req, timeout):
    return _WORKER_PROC.call(req, timeout)


def _cache_key():
    try:
        st = os.stat(_LSP_VST3)
        ident = f'{_LSP_VST3}|{int(st.st_mtime)}|{st.st_size}'
    except OSError:
        return None
    ids = ','.join(sorted(_BY_ID))
    return hashlib.sha1(f'{ident}|{ids}'.encode('utf-8'), usedforsecurity=False).hexdigest()[:24]


def _load_cached():
    key = _cache_key()
    if not key:
        return None
    try:
        with open(_CACHE, 'r', encoding='utf-8') as fh:
            c = json.load(fh)
        if c.get('key') == key:
            return c.get('racks')
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('plugin rack cache unreadable, rebuilding: %s', _exc)
    return None


def _save_cache(racks):
    key = _cache_key()
    if not key:
        return
    try:
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        with open(_CACHE, 'w', encoding='utf-8') as fh:
            json.dump({'key': key, 'racks': racks}, fh)
    except OSError as _exc:
        _zyg_log.warning('plugin rack cache write failed, continuing without cache: %s', _exc)


def _build_effect_types():
    racks_by_id = _load_cached()
    if racks_by_id is None:
        req = {
            'mode': 'introspect',
            'vst3': _LSP_VST3,
            'plugins': [{'id': p['id'], 'plugin_name': p['plugin_name']} for p in _LSP_PLUGINS],
        }
        resp = _run_worker(req, _INTROSPECT_TIMEOUT)
        if not resp.get('ok'):
            raise ValueError(resp.get('error') or 'introspect failed')
        racks_by_id = resp['racks']
        _save_cache(racks_by_id)
    out = []
    for p in _LSP_PLUGINS:
        knobs = racks_by_id.get(p['id'])
        if not isinstance(knobs, list) or not knobs:
            continue  # this one plugin failed to scan; the rest still load
        out.append(
            {
                'id': p['id'],
                'title': p['title'],
                'racks': [{'id': 'main', 'title': p['title'].upper(), 'sub': p['sub'], 'params': knobs}],
            }
        )
    return out


try:
    EFFECT_TYPES = _build_effect_types()
except Exception:  # noqa: BLE001 — see module docstring: fail silent, not down
    EFFECT_TYPES = []
_EFFECT_BY_ID = {e['id']: e for e in EFFECT_TYPES}


def render(effect_id, params, in_wav, out_wav):
    """Process in_wav through one plugin slot, writing out_wav. Raises
    ValueError (same convention as sfx_merger._run) on any failure, including
    a timeout — the worker process is killed, this process is unaffected."""
    p = _BY_ID.get(effect_id)
    if not p or effect_id not in _EFFECT_BY_ID:
        raise ValueError(f'unknown plugin effect type {effect_id}')
    req = {
        'mode': 'render',
        'vst3': _LSP_VST3,
        'plugin_name': p['plugin_name'],
        'params': params or {},
        'in_wav': in_wav,
        'out_wav': out_wav,
    }
    resp = _run_worker(req, _RENDER_TIMEOUT)  # raises ValueError itself on timeout/death
    if not resp.get('ok'):
        raise ValueError(f'{p["title"]} failed: {resp.get("error") or "unknown error"}')
