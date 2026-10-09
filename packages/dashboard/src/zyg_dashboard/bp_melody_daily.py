# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_melody_daily.py — Melody daily auto-batcher.

2026-09-01: adds a "Melody" toggle to the Approval Queue board — the third
sibling of the Documentary auto-batcher (bp_zero.py) and the Storyteller daily
serial (bp_storyteller_daily.py). While the toggle is ON, FIVE children's songs
are composed per calendar day, one at a time.

Contract (same as bp_zero / bp_storyteller_daily): imported only at the BOTTOM of
crewai_web_gui.py, where all main globals exist and the running __main__ instance
is aliased as `crewai_web_gui` in sys.modules. Single Flask process +
use_reloader=False means the watcher daemon started at import runs exactly once.

Why five SEQUENTIAL runs rather than five at once: a song render holds the GPU
and — for the picture leg — ComfyUI's single submit lock, and
/api/internal/kidsmusic/start already refuses to start while any pipeline is
running. This batcher enforces that rule itself rather than firing five starts
into a 409. Five full runs measured 5-13 minutes each on this box, so a day is
not remotely tight; the batch simply advances a song per watcher tick.

Restart safety: the job registry `_workflow_jobs` is in-process, and the health
probe has restarted crewai-gui thirty-odd times since July — several times
mid-song. So an in-production entry whose pipeline id is NOT in the registry is
not "unknown, wait forever": this process never launched it, which means we were
restarted under it. Its verdict is read off DISK (the song folder's own
manifest), so a restart settles the entry instead of wedging the batch.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import timedelta as _timedelta

from flask import Blueprint, jsonify, request

from zyg_workflows.paths import ZYG_OLLAMA_URL
from zyg_workflows.pipeline_common import _resolve_pipeline_public_status
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso, _ams_now  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_audit_log  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('melody_daily', __name__)

# ── paths / config ───────────────────────────────────────────────────────────
_MEL_DAILY_PATH = os.path.join(_RUNTIME_DIR, 'melody_daily.json')
_MEL_BATCH_PATH = os.path.join(_RUNTIME_DIR, 'melody_daily_batch.json')
_MEL_HISTORY_PATH = os.path.join(_RUNTIME_DIR, 'melody_daily_history.json')

_MEL_OUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'kidsmusic')

_MEL_LOCK = threading.RLock()

# The ask: five melodies every day.
_MEL_PER_DAY = max(1, min(20, int(os.environ.get('ZYG_MELODY_PER_DAY', '5'))))

# Hour of the Amsterdam day the batch is built at, when the toggle is left on
# overnight. Flipping the toggle ON builds today's batch immediately regardless.
_MEL_HOUR = max(0, min(23, int(os.environ.get('ZYG_MELODY_HOUR', '9'))))

# Don't launch a heavy render if free RAM is below this — same gate the Zero
# batcher and the storyteller serial use.
_MEL_MIN_FREE_RAM_GB = float(
    os.environ.get('ZYG_MELODY_MIN_FREE_RAM_GB', os.environ.get('ZYG_BATCH_MIN_FREE_RAM_GB', '24'))
)

# A song with no manifest whose folder has not been touched for this long, and
# whose job is gone from the registry, is over — not still running.
_MEL_ORPHAN_STALE_S = 900

_MEL_OLLAMA = ZYG_OLLAMA_URL.rstrip('/')


# ── Approval Queue settings + Pre-Emptive song bank (2026-09-20) ─────────────
# per_day / hour / RAM gate are edited on the Melody card (approval_queue_settings.py);
# the env defaults above still apply until a value is saved. The song bank
# (preempt_bank.songs_*) holds briefs picked in advance so a day's batch needs no model.
def _aq_get(key: str, default):
    try:
        from zyg_dashboard import approval_queue_settings as _aqs

        return _aqs.get('melody', key)
    except Exception:  # noqa: BLE001
        return default


def _mel_per_day() -> int:
    return max(1, min(20, int(_aq_get('per_day', _MEL_PER_DAY))))


def _mel_hour() -> int:
    return max(0, min(23, int(_aq_get('hour', _MEL_HOUR))))


def _mel_min_ram() -> float:
    return float(_aq_get('min_free_ram_gb', _MEL_MIN_FREE_RAM_GB))


def _aq_bank():
    try:
        from zyg_dashboard import preempt_bank as _pb

        return _pb
    except Exception:  # noqa: BLE001
        return None


def _mel_stop_job(pid: str) -> bool:
    job = _workflow_jobs.get(pid or '')
    if not job:
        return False
    try:
        ev = job.get('stop_event')
        if ev is not None:
            ev.set()
        from zyg_workflows import pipeline_control as _pc

        _pc.request_halt('Aborted from the Approval Queue')
        return True
    except Exception:  # noqa: BLE001
        return False


def _mel_daily_set(enabled: bool) -> dict:
    """The Melody card's play (enable → today's batch now) / off."""
    daily = _mel_daily_load()
    daily['enabled'] = bool(enabled)
    daily['paused'] = False
    if enabled:
        daily['done_date'] = _mel_today()
        daily['last_run_at'] = _ams_iso()
        _mel_daily_save(daily)
        batch = _mel_batch_load()
        live = isinstance(batch, dict) and any(
            e.get('status') in ('scheduled', 'in_production') for e in (batch.get('songs') or [])
        )
        if not live:
            _mel_create_daily_batch()
        _mel_batch_tick()
        _zero_audit_log('melody_daily_enabled', {'date': daily['done_date']})
    else:
        _mel_daily_save(daily)
        _zero_audit_log('melody_daily_disabled', {})
    return _mel_daily_load()


def _mel_pause(paused: bool) -> dict:
    daily = _mel_daily_load()
    daily['paused'] = bool(paused)
    _mel_daily_save(daily)
    _zero_audit_log('melody_daily_paused' if paused else 'melody_daily_resumed', {})
    return _mel_daily_load()


def _mel_abort() -> dict:
    stopped = None
    with _MEL_LOCK:
        batch = _mel_batch_load()
        for e in (batch.get('songs') if isinstance(batch, dict) else None) or []:
            if e.get('status') == 'in_production' and e.get('pipeline_id'):
                if _mel_stop_job(e['pipeline_id']):
                    stopped = e['pipeline_id']
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
                _mel_bank_settle(e, 'failed')
            elif e.get('status') == 'scheduled':
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
                _mel_bank_settle(e, 'failed')
        if isinstance(batch, dict) and batch.get('songs'):
            _mel_batch_save(batch)
    daily = _mel_daily_load()
    daily['enabled'] = False
    daily['paused'] = False
    _mel_daily_save(daily)
    _zero_audit_log('melody_daily_aborted', {'stopped_pipeline': stopped})
    return _mel_daily_load()


def _mel_bank_settle(entry: dict, outcome: str) -> None:
    _pb = _aq_bank()
    if _pb is None or not entry.get('bank_id'):
        return
    try:
        _pb.songs_settle(entry['bank_id'], outcome, entry.get('pipeline_id'))
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('bank settle for %s failed, the bank entry stays unsettled: %s', entry['bank_id'], _exc)


_MEL_MODEL = os.environ.get('ZYG_KIDSMUSIC_LLM', 'qwen3.5:9b')

# Same gate the lyric writer applies to a line, applied to the topic itself.
_MEL_BANNED = re.compile(
    r'\b(kill|die|dead|death|blood|gun|hate|stupid|dumb|ugly|fat|drunk|drug|'
    r'sex|damn|hell)\b',
    re.IGNORECASE,
)

# The seed pool. Used when the LLM is down or its answer is unusable, and as the
# top-up when it returns fewer usable songs than asked for — so a day's batch is
# never short and never blocks on a model. Ordered (theme, mood, age_band); the
# moods and bands are spread deliberately so five in a row don't sound alike.
_MEL_SEED_POOL = [
    ('a little green frog who hops across the pond', 'playful', 'toddler'),
    ('counting five yellow ducklings by the water', 'happy', 'toddler'),
    ('a sleepy moon tucking the town in for the night', 'lullaby', 'toddler'),
    ('washing your hands with lots and lots of bubbles', 'happy', 'preschool'),
    ('a brave little tractor who pulls the hay up the hill', 'marching', 'preschool'),
    ('a cat who hides in a cardboard box all afternoon', 'silly', 'preschool'),
    ('putting on boots to splash in the puddles', 'playful', 'toddler'),
    ('a snail who carries his house on his back', 'curious', 'preschool'),
    ('the wind that turns the big white windmill', 'gentle', 'preschool'),
    ('a hungry caterpillar munching through the garden', 'curious', 'early'),
    ('stars coming out one by one over the roof', 'lullaby', 'preschool'),
    ('a puppy learning to sit and stay and wait', 'happy', 'preschool'),
    ('planting a tiny seed and waiting for it to grow', 'gentle', 'preschool'),
    ('a bus that goes round the whole town and comes back', 'marching', 'toddler'),
    ('a bear who cannot find where he put his honey', 'silly', 'early'),
    ('what the baker does before the sun comes up', 'curious', 'early'),
    ('a paper boat sailing down the rainy street', 'gentle', 'preschool'),
    ('brushing your teeth up and down and round about', 'playful', 'toddler'),
    ('a fox with cold paws looking for somewhere warm', 'gentle', 'early'),
    ('the noises a farm makes when the sun comes up', 'happy', 'toddler'),
    ('a kite that pulls and pulls against the string', 'playful', 'early'),
    ('a lighthouse keeping the little boats safe', 'gentle', 'early'),
    ('an owl who stays awake when everyone else sleeps', 'lullaby', 'preschool'),
    ('mixing flour and eggs to make a birthday cake', 'happy', 'preschool'),
    ('a train with a whistle that goes through the tunnel', 'marching', 'toddler'),
    ('a spider spinning a web between two branches', 'curious', 'early'),
    ('jumping in a pile of red and orange leaves', 'playful', 'preschool'),
    ('a mouse who is very quiet and very quick', 'silly', 'preschool'),
    ('the rain drumming on the window all morning', 'gentle', 'toddler'),
    ('a penguin who slides on his tummy down the snow', 'silly', 'toddler'),
    ('learning the names of all the colours in the paintbox', 'curious', 'preschool'),
    ('a scarecrow standing still in the wide field', 'gentle', 'early'),
    ('a bicycle bell ringing all the way to school', 'marching', 'preschool'),
    ('a whale singing far down in the deep blue sea', 'lullaby', 'early'),
    ('finding shells and smooth stones along the beach', 'curious', 'preschool'),
    ('a rooster who wakes the whole farm too early', 'silly', 'preschool'),
    ('tidying every toy back into the big wooden box', 'happy', 'toddler'),
    ('a hot air balloon floating over the fields', 'gentle', 'early'),
    ('a busy bee visiting every flower in the row', 'happy', 'preschool'),
    ('the first snow falling on the quiet garden', 'lullaby', 'preschool'),
]

_MEL_MOODS = ['happy', 'playful', 'marching', 'gentle', 'lullaby', 'silly', 'curious']
_MEL_AGE_BANDS = ['toddler', 'preschool', 'early']


# ── small json helpers ───────────────────────────────────────────────────────
def _mel_today() -> str:
    return _ams_now().strftime('%Y-%m-%d')


def _mel_load(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default() if callable(default) else default


def _mel_save(path, data) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('melody state write to %s failed, it is not persisted: %s', path, _exc)


def _mel_daily_load() -> dict:
    d = _mel_load(_MEL_DAILY_PATH, lambda: {'enabled': False, 'done_date': None, 'last_run_at': None})
    d['per_day'] = _mel_per_day()
    d['hour'] = _mel_hour()
    d['paused'] = bool(d.get('paused'))
    return d


def _mel_daily_save(d: dict) -> None:
    _mel_save(
        _MEL_DAILY_PATH,
        {
            'enabled': bool(d.get('enabled')),
            'paused': bool(d.get('paused')),
            'done_date': d.get('done_date'),
            'last_run_at': d.get('last_run_at'),
        },
    )


def _mel_batch_load() -> dict:
    return _mel_load(_MEL_BATCH_PATH, dict)


def _mel_batch_save(b: dict) -> None:
    _mel_save(_MEL_BATCH_PATH, b)


def _mel_history_load() -> list:
    h = _mel_load(_MEL_HISTORY_PATH, lambda: {'themes': []})
    return list(h.get('themes') or [])


def _mel_history_add(themes) -> None:
    h = _mel_history_load()
    for t in themes:
        t = str(t).strip()
        if t:
            h.append(t)
    _mel_save(_MEL_HISTORY_PATH, {'themes': h[-400:]})


# ── gates ────────────────────────────────────────────────────────────────────
def _mel_free_ram_gb() -> float:
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError) as _exc:
        _zyg_log.warning('/proc/meminfo unreadable, assuming RAM is free: %s', _exc)
    return 999.0


def _mel_pipeline_busy() -> str:
    """The id of any pipeline currently running, '' if the box is free.

    Any department counts, not just melodies: one render at a time is the rule
    the main dispatcher and bp_kidsmusic.km_start both enforce, so a melody that
    started next to a documentary would just lose the GPU race.
    """
    try:
        for pid, j in _workflow_jobs.items():
            if str(j.get('status') or '').lower() == 'running':
                return pid
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('running-job scan failed, treating the box as idle: %s', _exc)
    return ''


def _mel_disk_outcome(pid: str) -> str:
    """done | failed | running, read off the song folder alone.

    Consulted when the job is gone from the in-process registry, which means
    this process did not launch it — i.e. the GUI was restarted under a run.
    """
    d = os.path.join(_MEL_OUT_ROOT, pid or '')
    man = os.path.join(d, 'manifest.json')
    try:
        with open(man, 'r', encoding='utf-8') as f:
            m = json.load(f)
        return 'done' if m.get('ok', True) else 'failed'
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('melody manifest unreadable, falling back to directory inspection: %s', _exc)
    if not os.path.isdir(d):
        return 'failed'
    try:
        newest = max([os.path.getmtime(d)] + [os.path.getmtime(os.path.join(d, n)) for n in os.listdir(d)])
    except (OSError, ValueError):
        return 'failed'
    return 'running' if (time.time() - newest) < _MEL_ORPHAN_STALE_S else 'failed'


def _mel_pipeline_outcome(pid: str) -> str:
    """running | done | failed for a launched melody run."""
    if not pid:
        return 'failed'
    job = _workflow_jobs.get(pid)
    if not job:
        return _mel_disk_outcome(pid)
    st = str(job.get('status') or '').lower()
    if st in ('completed', 'complete', 'done', 'success', 'succeeded', 'finished'):
        return 'done'
    if st in ('failed', 'error', 'errored', 'cancelled', 'canceled', 'stopped', 'halted', 'rejected'):
        return 'failed'
    try:
        pub = str(_resolve_pipeline_public_status(job) or '').lower()
        if any(k in pub for k in ('complete', 'done', 'success', 'finished')):
            return 'done'
        if any(k in pub for k in ('fail', 'error', 'cancel', 'stop', 'halt')):
            return 'failed'
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('public pipeline status unavailable, reporting running: %s', _exc)
    return 'running'


# ── theme selection ──────────────────────────────────────────────────────────
def _mel_norm(theme: str) -> str:
    return re.sub(r'[^a-z0-9 ]+', '', str(theme or '').lower()).strip()


def _mel_produced_themes() -> set:
    """Every theme this box has already made a song about.

    Both sources matter: the manifests are the record of what was DELIVERED, and
    the history file records what was SCHEDULED — a run that died before writing
    a manifest still used up its theme, and repeating it would look like the
    batcher had no memory.
    """
    seen = set()
    try:
        for name in os.listdir(_MEL_OUT_ROOT):
            p = os.path.join(_MEL_OUT_ROOT, name, 'manifest.json')
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    m = json.load(f)
            except (OSError, ValueError) as _exc:
                _zyg_log.debug('skipping melody manifest that could not be read: %s', _exc)
                continue
            t = _mel_norm(((m.get('brief') or {}).get('theme')) or '')
            if t:
                seen.add(t)
    except OSError as _exc:
        _zyg_log.warning('melody output root unreadable, used themes may repeat: %s', _exc)
    for t in _mel_history_load():
        n = _mel_norm(t)
        if n:
            seen.add(n)
    return seen


def _mel_theme_ok(theme: str, avoid: set) -> bool:
    t = str(theme or '').strip()
    if not (8 <= len(t) <= 90):
        return False
    if _MEL_BANNED.search(t):
        return False
    return _mel_norm(t) not in avoid


def _mel_propose_briefs(n: int, avoid: set) -> list:
    """Ask the local model for n fresh song topics. [] if it cannot deliver."""
    recent = [t for t in _mel_history_load()[-24:]]
    prompt = (
        'You invent topics for short songs for young children. Reply with JSON only.\n'
        f'Invent {n} DIFFERENT song topics.\n'
        'Each topic is one short phrase naming a concrete thing and what it does — '
        'for example "a little red train that says toot toot" or "washing your hands '
        'with lots of bubbles". 4 to 12 words.\n'
        'Rules: everyday things a small child knows; nothing frightening; nothing '
        'about death, illness, violence or money; no brand names; no proper names of '
        'real people or places.\n'
        + (f'Do NOT repeat any of these recent topics: {"; ".join(recent)}\n' if recent else '')
        + 'Give each one a mood from: '
        + ', '.join(_MEL_MOODS)
        + '\n'
        'and an audience from: toddler, preschool, early\n'
        '{"songs": [{"theme": "...", "mood": "...", "age_band": "..."}]}'
    )
    payload = {
        'model': _MEL_MODEL,
        'prompt': prompt,
        'stream': False,
        'format': 'json',
        # qwen3.x are thinking models: without think:false the budget goes to
        # reasoning tokens and 'response' comes back empty. Non-thinking models
        # 500 on the key, so it is conditional — and gpt-oss + format:json
        # returns nothing at all, so do not swap the model for gpt-oss here.
        **({'think': False} if _MEL_MODEL.startswith('qwen3') else {}),
        'keep_alive': '2m',
        'options': {'temperature': 0.95, 'num_predict': 700, 'num_ctx': 4096},
    }
    data = None
    try:
        import urllib.request as _ur
        from zyg_workflows.net import safe_urlopen

        with safe_urlopen(f'{_MEL_OLLAMA}/api/version', timeout=3):
            pass
        try:
            from zyg_workflows import llm_audit as _la

            d = _la.ollama_post(f'{_MEL_OLLAMA}/api/generate', payload, timeout=120, stage='melody_daily_themes')
        except ImportError:
            # safe_urlopen() cannot carry the JSON Content-Type header this POST needs, so the
            # Request is built here; the scheme of _MEL_OLLAMA was validated by the safe_urlopen()
            # version probe a few lines above, which raises before we get here.
            req = _ur.Request(  # noqa: S310  scheme validated by the safe_urlopen probe above
                f'{_MEL_OLLAMA}/api/generate',
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with _ur.urlopen(req, timeout=120) as r:  # nosec B310  # noqa: S310  scheme validated by the safe_urlopen probe above
                d = json.loads(r.read().decode('utf-8'))
        raw = ((d.get('response') or '').strip() or (d.get('thinking') or '')).strip().strip('`')
        data = json.loads(raw[raw.find('{') : raw.rfind('}') + 1])
    except Exception:  # noqa: BLE001 — the pool covers it
        return []

    # Case-fold the keys: qwen returns {"Songs": [...]} a good fraction of the
    # time, and reading data['songs'] alone silently threw those answers away in
    # the lyric writer before the same fix went in there.
    if not isinstance(data, dict):
        return []
    low = {str(k).strip().lower(): v for k, v in data.items()}
    rows = low.get('songs') or low.get('topics') or low.get('themes') or []
    if isinstance(rows, str):
        rows = [rows]
    out, taken = [], set(avoid)
    for row in list(rows)[: n * 3]:
        if isinstance(row, str):
            row = {'theme': row}
        if not isinstance(row, dict):
            continue
        r = {str(k).strip().lower(): v for k, v in row.items()}
        theme = re.sub(r'\s+', ' ', str(r.get('theme') or r.get('topic') or '')).strip(' .,;:"\'')
        if not _mel_theme_ok(theme, taken):
            continue
        taken.add(_mel_norm(theme))
        mood = str(r.get('mood') or '').strip().lower()
        band = str(r.get('age_band') or r.get('audience') or '').strip().lower()
        out.append(
            {
                'theme': theme,
                'mood': mood if mood in _MEL_MOODS else _MEL_MOODS[len(out) % len(_MEL_MOODS)],
                'age_band': band if band in _MEL_AGE_BANDS else _MEL_AGE_BANDS[len(out) % 3],
                'source': 'llm',
            }
        )
        if len(out) >= n:
            break
    return out


def _mel_pool_briefs(n: int, avoid: set) -> list:
    """Top up from the seed pool, skipping anything already used."""
    out = []
    for theme, mood, band in _MEL_SEED_POOL:
        if len(out) >= n:
            break
        if _mel_norm(theme) in avoid:
            continue
        avoid.add(_mel_norm(theme))
        out.append({'theme': theme, 'mood': mood, 'age_band': band, 'source': 'pool'})
    if len(out) < n:
        # The pool is exhausted against history — reuse rather than deliver a
        # short batch, and say so in the record, so a repeated topic reads as a
        # known state and not as a batcher with no memory. Rotated by how much
        # history there is: without the offset, every day past exhaustion would
        # be the SAME five songs, which is the one failure that would look like
        # the batcher had stopped working rather than run out of new material.
        off = len(_mel_history_load())
        for i in range(len(_MEL_SEED_POOL)):
            if len(out) >= n:
                break
            theme, mood, band = _MEL_SEED_POOL[(off + i) % len(_MEL_SEED_POOL)]
            out.append({'theme': theme, 'mood': mood, 'age_band': band, 'source': 'pool-reused'})
    return out


def _mel_pick_briefs(n: int) -> list:
    avoid = _mel_produced_themes()
    briefs = []
    _pb = _aq_bank()
    if _pb is not None and _aq_get('use_bank_first', True):
        try:
            for r in _pb.songs_take(n):
                briefs.append(
                    {
                        'theme': r['theme'],
                        'mood': r.get('mood') or _MEL_MOODS[len(briefs) % len(_MEL_MOODS)],
                        'age_band': r.get('age_band') or _MEL_AGE_BANDS[len(briefs) % 3],
                        'source': 'bank',
                        'bank_id': r['id'],
                    }
                )
                avoid.add(_mel_norm(r['theme']))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('bank briefs unavailable, falling back to generated proposals: %s', _exc)
        if len(briefs) >= n:
            return briefs[:n]
    briefs += _mel_propose_briefs(n - len(briefs), avoid)
    for b in briefs:
        avoid.add(_mel_norm(b['theme']))
    if len(briefs) < n:
        briefs += _mel_pool_briefs(n - len(briefs), avoid)
    return briefs[:n]


# ── batch lifecycle ──────────────────────────────────────────────────────────
def _mel_create_daily_batch() -> dict:
    """Build today's batch: five songs, all 'scheduled'. The tick launches them
    one at a time."""
    with _MEL_LOCK:
        briefs = _mel_pick_briefs(_mel_per_day())
        songs = []
        for i, b in enumerate(briefs):
            songs.append(
                {
                    'id': i,
                    'theme': b['theme'],
                    'mood': b['mood'],
                    'age_band': b['age_band'],
                    'theme_source': b.get('source', 'pool'),
                    'bank_id': b.get('bank_id'),
                    'status': 'scheduled',
                    'pipeline_id': None,
                    'title': None,
                    'started_at': None,
                    'ended_at': None,
                    'error': None,
                }
            )
        batch = {
            'batch_date': _mel_today(),
            'created_at': _ams_iso(),
            'auto': True,
            'per_day': _mel_per_day(),
            'songs': songs,
        }
        _mel_batch_save(batch)
        _mel_history_add([s['theme'] for s in songs])
        _zero_audit_log(
            'melody_daily_batch_created',
            {
                'date': batch['batch_date'],
                'count': len(songs),
                'llm_themes': sum(1 for s in songs if s['theme_source'] == 'llm'),
            },
        )
        return batch


def _mel_start_song(entry: dict) -> None:
    """Launch one song through the Children's Music pipeline."""
    try:
        from zyg_workflows import kids_music_theory as _T
        from zyg_workflows import pipeline_kidsmusic as _km
    except Exception as e:  # noqa: BLE001
        entry['status'] = 'failed'
        entry['error'] = f'melody workflow unavailable: {type(e).__name__}'
        entry['ended_at'] = _ams_iso()
        return
    song = {
        'theme': entry['theme'],
        'age_band': entry['age_band'],
        'mood': entry['mood'],
        # The children's-song band (kids_music_theory.SONG_SECONDS, 130-210 s since
        # 2026-10-02), rotated by the song's place in the day's batch so five songs
        # are not five of the same length.
        'seconds': _T.song_seconds(entry.get('id') or 0),
        'sung': True,
        # Set explicitly rather than left to a default: bp_kidsmusic fills the
        # singer in on the HTTP path, and this is the direct call.
        'singer': _T.DEFAULT_SINGER,
        'want_ace': True,
        'want_video': True,
        'candidates': 48,
    }
    try:
        info = _km.start_kidsmusic(directive=entry['theme'], song=song)
    except Exception as e:  # noqa: BLE001
        info = {'error': f'{type(e).__name__}: {e}'}
    info = info if isinstance(info, dict) else {}
    pid = info.get('job_id') or info.get('pipeline_id')
    if pid and info.get('status') == 'running' and not info.get('error'):
        entry['status'] = 'in_production'
        entry['pipeline_id'] = pid
        entry['started_at'] = _ams_iso()
        _zero_audit_log('melody_daily_song_started', {'theme': entry['theme'][:200], 'pipeline_id': pid})
    else:
        entry['status'] = 'failed'
        entry['error'] = (info or {}).get('error') or 'start failed'
        entry['ended_at'] = _ams_iso()
        _zero_audit_log('melody_daily_song_start_failed', {'theme': entry['theme'][:200], 'error': entry['error']})


def _mel_song_title(pid: str) -> str:
    try:
        with open(os.path.join(_MEL_OUT_ROOT, pid, 'manifest.json'), 'r', encoding='utf-8') as f:
            return str(json.load(f).get('title') or '')[:120]
    except (OSError, ValueError):
        return ''


def _mel_batch_tick() -> None:
    """Advance today's batch: settle whatever is in production, then start the
    next scheduled song — only while the toggle is ON, the box is free and RAM
    allows."""
    with _MEL_LOCK:
        batch = _mel_batch_load()
        songs = batch.get('songs') if isinstance(batch, dict) else None
        if not songs:
            return
        changed = False

        # 1) settle in-production
        for e in songs:
            if e.get('status') == 'in_production':
                outcome = _mel_pipeline_outcome(e.get('pipeline_id'))
                if outcome == 'done':
                    e['status'] = 'done'
                    e['ended_at'] = _ams_iso()
                    e['title'] = _mel_song_title(e.get('pipeline_id') or '')
                    _mel_bank_settle(e, 'done')
                    changed = True
                elif outcome == 'failed':
                    e['status'] = 'failed'
                    e['ended_at'] = _ams_iso()
                    e['error'] = e.get('error') or 'pipeline failed'
                    _mel_bank_settle(e, 'failed')
                    changed = True
                break  # sequential: one at a time

        in_prod = any(e.get('status') == 'in_production' for e in songs)
        if changed:
            _mel_batch_save(batch)
        if in_prod:
            return

        # 2) start the next scheduled song
        _daily_now = _mel_daily_load()
        if not _daily_now.get('enabled') or _daily_now.get('paused'):
            return
        nxt = next((e for e in songs if e.get('status') == 'scheduled'), None)
        if not nxt:
            return
        if _mel_pipeline_busy():
            return  # another department has the GPU
        if _mel_free_ram_gb() < _mel_min_ram():
            return  # retry next tick
        _mel_start_song(nxt)
        _mel_batch_save(batch)


def _mel_scheduler_tick() -> None:
    """At most one new batch per calendar day, and never on top of a live one.

    Carry-over rather than replacement: if yesterday's five have not all settled
    (a long picture leg, a box that was busy all evening), they finish first. No
    song is abandoned to make room for a new day's batch.
    """
    daily = _mel_daily_load()
    if not daily.get('enabled'):
        return
    today = _mel_today()
    if daily.get('done_date') == today:
        return
    batch = _mel_batch_load()
    if isinstance(batch, dict) and batch.get('songs'):
        if any(e.get('status') in ('scheduled', 'in_production') for e in batch['songs']):
            return
    if _ams_now().hour < _mel_hour():
        return
    _mel_create_daily_batch()
    daily['done_date'] = today
    daily['last_run_at'] = _ams_iso()
    _mel_daily_save(daily)


def _mel_watcher() -> None:
    """Daemon: settle/advance the batch and fire the daily batch, every 30 s."""
    while True:
        time.sleep(30)
        try:
            _mel_scheduler_tick()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('melody scheduler tick failed, retrying in 30 s: %s', _exc)
        try:
            _mel_batch_tick()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('melody batch tick failed, retrying in 30 s: %s', _exc)


def _mel_next_run_label() -> str:
    """When the next batch is due, for the board. '' when nothing is armed."""
    daily = _mel_daily_load()
    if not daily.get('enabled'):
        return ''
    batch = _mel_batch_load()
    if isinstance(batch, dict) and batch.get('songs'):
        if any(e.get('status') in ('scheduled', 'in_production') for e in batch['songs']):
            return 'after current batch'
    now = _ams_now()
    today = now.strftime('%Y-%m-%d')
    due_today = now.hour < _mel_hour() and daily.get('done_date') != today
    day = today if due_today else (now + _timedelta(days=1)).strftime('%Y-%m-%d')
    return f'{day} {_mel_hour():02d}:00'


# ── HTTP endpoints ───────────────────────────────────────────────────────────
@bp.route('/api/melody/daily_mode', methods=['GET', 'POST'])
def api_melody_daily_mode():
    """GET or POST the Melody daily auto-mode toggle (POST {enabled: bool})."""
    if request.method == 'GET':
        return jsonify(_mel_daily_load())
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled'))
    try:
        _mel_daily_set(enabled)
    except Exception as e:  # noqa: BLE001
        return jsonify({'ok': False, 'error': f'batch create failed: {e}'}), 500
    return jsonify({'ok': True, 'enabled': enabled, 'state': _mel_daily_load()})


@bp.route('/api/melody/daily_batch')
def api_melody_daily_batch():
    """Current batch + toggle state, for the approval-queue UI."""
    batch = _mel_batch_load()
    return jsonify(
        {
            'batch': batch or None,
            'daily': _mel_daily_load(),
            'next_run': _mel_next_run_label(),
            'busy_with': _mel_pipeline_busy(),
        }
    )


# ── start the watcher daemon (single process, use_reloader=False → runs once) ──
threading.Thread(target=_mel_watcher, daemon=True, name='melody-daily-watcher').start()
