# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Storyteller daily-serial engine.
# 2026-07-25: adds a "Storyteller" auto-mode toggle (sibling of the Zero/Documentary
# auto-batcher in bp_zero.py) that generates ONE episode per template per calendar day,
# with full serialization (arc schedule + running per-series state).
#
# Contract (same as bp_zero / bp_storyteller): imported only at the BOTTOM of
# crewai_web_gui.py, where all main globals exist and the running __main__ instance is
# aliased as `crewai_web_gui` in sys.modules. Single Flask process + use_reloader=False
# means the watcher daemon started at import runs exactly once.
#
# Safety default: a template only GENERATES if it has a linked+trained character LoRA,
# OR env ZYG_STORYTELLER_ALLOW_UNLOCKED=1 is set. Otherwise it is queued as "blocked:
# awaiting character LoRA" and nothing heavy runs. Flip either to go live.
import json
import os
import threading
import time

from flask import Blueprint, jsonify, request

from zyg_workflows.paths import ZYG_LORA_OUTPUTS
from zyg_workflows.pipeline_common import _resolve_pipeline_public_status
from zyg_dashboard.crewai_web_gui import _start_storyteller_pipeline_internal  # noqa: E402
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso, _ams_now  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_audit_log  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('storyteller_daily', __name__)

# ── paths / config ───────────────────────────────────────────────────────────
_STD_TEMPLATES_PATH = os.path.join(_RUNTIME_DIR, 'storyteller_templates.json')
_STD_SERIAL_PATH = os.path.join(_RUNTIME_DIR, 'storyteller_serial_state.json')
_STD_DAILY_PATH = os.path.join(_RUNTIME_DIR, 'storyteller_daily.json')
_STD_BATCH_PATH = os.path.join(_RUNTIME_DIR, 'storyteller_daily_batch.json')

_STD_LOCK = threading.RLock()

# Don't launch a heavy pipeline if free RAM is below this (mirror the Zero batch gate).
_STD_MIN_FREE_RAM_GB = float(
    os.environ.get('ZYG_STORYTELLER_MIN_FREE_RAM_GB', os.environ.get('ZYG_BATCH_MIN_FREE_RAM_GB', '24'))
)

_STD_RECENT_RECAPS = 8  # how many prior-episode recaps to feed forward


# ── Approval Queue settings + controls (2026-09-20) ──────────────────────────
def _aq_get(key: str, default):
    try:
        from zyg_dashboard import approval_queue_settings as _aqs

        return _aqs.get('storyteller', key)
    except Exception:  # noqa: BLE001
        return default


def _std_min_ram() -> float:
    return float(_aq_get('min_free_ram_gb', _STD_MIN_FREE_RAM_GB))


def _std_max_per_day() -> int:
    return max(1, min(22, int(_aq_get('max_per_day', 22))))


def _std_stop_job(pid: str) -> bool:
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


def _std_daily_set(enabled: bool) -> dict:
    """The Storyteller card's play (enable → today's batch now) / off."""
    daily = _std_daily_load()
    daily['enabled'] = bool(enabled)
    daily['paused'] = False
    if enabled:
        daily['done_date'] = _std_today()
        daily['last_run_at'] = _ams_iso()
        _std_daily_save(daily)
        batch = _std_batch_load()
        live = isinstance(batch, dict) and any(
            e.get('status') in ('scheduled', 'in_production') for e in (batch.get('episodes') or [])
        )
        if not live:
            _std_create_daily_batch()
        _std_batch_tick()
        _zero_audit_log('storyteller_daily_enabled', {'date': daily['done_date']})
    else:
        _std_daily_save(daily)
        _zero_audit_log('storyteller_daily_disabled', {})
    return _std_daily_load()


def _std_pause(paused: bool) -> dict:
    daily = _std_daily_load()
    daily['paused'] = bool(paused)
    _std_daily_save(daily)
    _zero_audit_log('storyteller_daily_paused' if paused else 'storyteller_daily_resumed', {})
    return _std_daily_load()


def _std_abort() -> dict:
    stopped = None
    with _STD_LOCK:
        batch = _std_batch_load()
        for e in (batch.get('episodes') if isinstance(batch, dict) else None) or []:
            if e.get('status') == 'in_production' and e.get('pipeline_id'):
                if _std_stop_job(e['pipeline_id']):
                    stopped = e['pipeline_id']
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
            elif e.get('status') == 'scheduled':
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
        if isinstance(batch, dict) and batch.get('episodes'):
            _std_batch_save(batch)
    daily = _std_daily_load()
    daily['enabled'] = False
    daily['paused'] = False
    _std_daily_save(daily)
    _zero_audit_log('storyteller_daily_aborted', {'stopped_pipeline': stopped})
    return _std_daily_load()


_STD_MODEL_FAMILY = 'sdxl'


# ── small json helpers ───────────────────────────────────────────────────────
def _std_today() -> str:
    return _ams_now().strftime('%Y-%m-%d')


def _std_load(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default() if callable(default) else default


def _std_save(path, data) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as _exc:
        _zyg_log.warning('storyteller state write to %s failed, it is not persisted: %s', path, _exc)


def _std_templates() -> list:
    store = _std_load(_STD_TEMPLATES_PATH, lambda: {'templates': []})
    tpls = [t for t in store.get('templates', []) if t.get('enabled', True)]
    return sorted(tpls, key=lambda t: t.get('order', 999))


def _std_templates_by_id() -> dict:
    store = _std_load(_STD_TEMPLATES_PATH, lambda: {'templates': []})
    return {t['id']: t for t in store.get('templates', [])}


def _std_serial_load() -> dict:
    return _std_load(_STD_SERIAL_PATH, dict)


def _std_serial_save(state: dict) -> None:
    _std_save(_STD_SERIAL_PATH, state)


def _std_serial_for(state: dict, tid: str) -> dict:
    s = state.get(tid)
    if not isinstance(s, dict):
        s = {
            'episode_no': 0,
            'current_arc': None,
            'countdown_day': 0,
            'story_so_far': '',
            'recent_recaps': [],
            'recurring_cast_state': {},
            'used_beats': [],
            'used_layers': [],
            'used_eras': [],
            'last_episode_at': None,
            'last_pipeline_id': None,
            'last_status': None,
        }
        state[tid] = s
    return s


def _std_daily_load() -> dict:
    return _std_load(_STD_DAILY_PATH, lambda: {'enabled': False, 'done_date': None, 'last_run_at': None})


def _std_daily_save(d: dict) -> None:
    _std_save(_STD_DAILY_PATH, d)


def _std_batch_load() -> dict:
    return _std_load(_STD_BATCH_PATH, dict)


def _std_batch_save(b: dict) -> None:
    _std_save(_STD_BATCH_PATH, b)


# ── readiness gate ───────────────────────────────────────────────────────────
def _std_allow_unlocked() -> bool:
    return os.environ.get('ZYG_STORYTELLER_ALLOW_UNLOCKED', '0').strip().lower() in ('1', 'true', 'yes', 'on')


def _std_template_ready(t: dict):
    """Return (ready: bool, reason: str|None). Ready only if a trained LoRA is linked
    (or the unlock flag is set)."""
    char = t.get('character') or {}
    cid = char.get('char_id')
    if cid:
        try:
            from zyg_workflows import character_lora_family as _clf

            lora_dir = os.path.join(str(ZYG_LORA_OUTPUTS / 'storyteller_chars'), cid)
            fams = _clf.char_lora_families_for_dir(lora_dir)
            if fams:
                # 2026-07-31: weights on disk are not consent — training runs
                # before the QC valve and before the operator's Allow/Decline,
                # so a declined, QC-failed character still had adapters here.
                _usable_fn = getattr(_clf, 'char_lora_usable', None)
                if _usable_fn is not None:
                    _ok_u, _why_u = _usable_fn(cid)
                    if not _ok_u:
                        return False, f'character LoRA not usable: {_why_u}'
                return True, None
            return False, 'awaiting character LoRA (char_id linked, no trained weights found)'
        except Exception as e:
            return False, f'LoRA check failed: {e}'
    if _std_allow_unlocked():
        return True, None
    return False, 'awaiting character LoRA (no char_id linked)'


def _std_free_ram_gb() -> float:
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError) as _exc:
        _zyg_log.warning('/proc/meminfo unreadable, assuming RAM is free: %s', _exc)
    return 999.0


def _std_pipeline_outcome(pid: str) -> str:
    """running | done | failed | unknown for a launched storyteller pipeline."""
    if not pid:
        return 'unknown'
    job = _workflow_jobs.get(pid)
    if not job:
        return 'unknown'
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
    except Exception as _exc:
        _zyg_log.debug('public pipeline status unavailable, reporting running: %s', _exc)
    return 'running'


# ── beat selection (full-serialization variety enforcement) ──────────────────
def _std_pick_beat(t: dict, state: dict) -> dict:
    """Pre-select today's beat so continuity is exact and repeats are avoided.
    Returns {'directive': str, 'record': dict} where record is applied to serial
    state ONLY when the episode completes."""
    engine = t.get('engine') or {}
    bank = engine.get('beat_bank') or {}
    n = int(state.get('episode_no', 0)) + 1

    # Second Ledger: question seed + episode type wheel
    if bank.get('question_seeds'):
        qs = bank['question_seeds']
        types = bank.get('episode_types') or ['—']
        used = state.get('used_beats', [])
        recent_q = {b.get('q') for b in used[-len(qs) // 2 :]} if used else set()
        recent_t = [b.get('type') for b in used[-3:]] if used else []
        q = next((x for x in (qs[(n + i) % len(qs)] for i in range(len(qs))) if x not in recent_q), qs[n % len(qs)])
        typ = next(
            (x for x in (types[(n + i) % len(types)] for i in range(len(types))) if x not in recent_t),
            types[n % len(types)],
        )
        directive = (
            f'Write the QUESTION Abel puts at the top of the page this morning: '
            f'"{q}"  ·  Episode type from the wheel: "{typ}" '
            f'(never the same type twice in three days).'
        )
        return {'directive': directive, 'record': {'used_beats': {'q': q, 'type': typ}}}

    # Conflict serials: A-layer + a different complication-layer + a story thread
    if engine.get('pressure_layers'):
        layers = engine['pressure_layers']
        threads = engine.get('story_threads') or []
        recent = state.get('used_layers', [])[-2:]
        a = next(
            (x for x in (layers[(n + i) % len(layers)] for i in range(len(layers))) if x not in recent),
            layers[n % len(layers)],
        )
        b = next(
            (x for x in (layers[(n + 1 + i) % len(layers)] for i in range(len(layers))) if x != a),
            layers[(n + 1) % len(layers)],
        )
        thread = threads[n % len(threads)] if threads else ''
        directive = (
            f'A-STORY drawn from pressure layer: "{a}". COMPLICATION drawn from a '
            f'different layer: "{b}". Advance this story thread: {thread} '
            f'(vary the episode SHAPE, not the misery; no three consecutive same-layer).'
        )
        return {'directive': directive, 'record': {'used_layers': a}}

    # Farnah: the question chooses the era, and the era must jump
    if bank.get('eras'):
        eras = bank['eras']
        used = state.get('used_eras', [])
        last = used[-1] if used else None
        window = used[-20:]

        def ok(e):
            return e != last and window.count(e) < 4

        era = next((x for x in (eras[(n + i) % len(eras)] for i in range(len(eras))) if ok(x)), eras[n % len(eras)])
        directive = (
            f"The traveller's question makes today's nested tale land in this era: "
            f'"{era}". It MUST differ from the previous episode\'s era (the century jumps).'
        )
        return {'directive': directive, 'record': {'used_eras': era}}

    return {'directive': 'Write the next self-contained episode, advancing the series.', 'record': {}}


def _std_current_arc(t: dict, episode_no: int):
    arcs = ((t.get('serialization') or {}).get('arcs')) or []
    for arc in arcs:
        rng = str(arc.get('eps', ''))
        if '-' in rng:
            try:
                lo, hi = (int(x) for x in rng.split('-', 1))
                if lo <= episode_no <= hi:
                    return arc
            except ValueError as _exc:
                _zyg_log.debug('skipping arc with an unparseable episode range %r: %s', rng, _exc)
                continue
    return arcs[0] if arcs else None


def _std_duration_min(t: dict, episode_no: int) -> float:
    rng = (t.get('settings') or {}).get('duration_min_range') or [12, 18]
    lo, hi = float(rng[0]), float(rng[-1])
    span = max(1.0, hi - lo)
    return round(lo + (episode_no * 3) % (int(span) + 1), 1)


# ── prompt + character params ────────────────────────────────────────────────
def _std_character_params(t: dict) -> dict:
    c = t.get('character') or {}
    extra = (
        f'{c.get("one_line", "")} Distinctive: {c.get("distinctive_marks", "none")}. '
        f'Wardrobe: {c.get("default_clothing", "")}. '
        f'Render as realistic animated illustration (2D cel / rotoscoped realism), NOT 3D Pixar/toon.'
    )
    return {
        'name': c.get('name', ''),
        'gender': c.get('gender', ''),
        'age': c.get('age'),
        'ethnic_heritage': c.get('ethnic_heritage', ''),
        'skin_tone': c.get('skin_tone', ''),
        'hair_color': c.get('hair_color', ''),
        'hair_style': c.get('hair_style', ''),
        'eye_color': c.get('eye_color', ''),
        'body_build': c.get('body_build', ''),
        'facial_hair': c.get('facial_hair', 'none'),
        'distinctive_marks': c.get('distinctive_marks', 'none'),
        'default_clothing': c.get('default_clothing', ''),
        'default_expression': c.get('default_expression', ''),
        'style': 'animated',
        'render_style': 'animated',
        'genre': t.get('genre', 'general'),
        'extra_prompt': extra,
    }


def _std_build_story_prompt(t: dict, state: dict, beat: dict, episode_no: int, duration_min: float) -> str:
    engine = t.get('engine') or {}
    ser = t.get('serialization') or {}
    c = t.get('character') or {}
    arc = _std_current_arc(t, episode_no)
    recaps = state.get('recent_recaps') or []
    rules = engine.get('rules') or []
    parts = []
    parts.append(f'[{t.get("series_title", "")} — Episode {episode_no}] ({t.get("setting", "")})')
    parts.append('')
    parts.append(
        f'Write EPISODE {episode_no} of the daily serial "{t.get("series_title", "")}": a '
        f'self-contained ~{duration_min:.0f}-minute animated episode with a complete beginning, '
        f'middle and end that resolves within this one episode, while honouring the running '
        f'continuity below.'
    )
    parts.append('')
    parts.append(f'PROTAGONIST: {c.get("one_line", c.get("name", ""))}')
    parts.append(f'SETTING: {t.get("setting", "")}')
    parts.append('')
    parts.append('PREMISE / ENGINE:')
    parts.append(engine.get('premise', ''))
    if engine.get('episode_format'):
        parts.append('')
        parts.append('EPISODE FORMAT:')
        parts.append(engine['episode_format'])
    parts.append('')
    parts.append("TODAY'S BEAT (use exactly this):")
    parts.append(beat.get('directive', ''))
    if rules:
        parts.append('')
        parts.append('SERIES RULES (do not break):')
        for r in rules:
            parts.append(f'- {r}')
    parts.append('')
    parts.append('CONTINUITY — STORY SO FAR:')
    parts.append(state.get('story_so_far') or "This is early in the series; establish, don't recap.")
    if recaps:
        parts.append('RECENT EPISODES:')
        for rc in recaps[-_STD_RECENT_RECAPS:]:
            parts.append(f'- {rc}')
    if arc:
        parts.append('')
        parts.append(f'CURRENT ARC: {arc.get("name", "")} — {arc.get("spine", "")}')
    if ser.get('countdown'):
        parts.append(f'COUNTDOWN: {ser["countdown"]}')
    parts.append('')
    parts.append(
        'VISUAL STYLE: realistic animated illustration (2D hand-drawn / cel or rotoscoped '
        'photoreal-adjacent animation) — NOT 3D Pixar/toon.'
    )
    parts.append('')
    parts.append(
        'Write the episode now as a scene-by-scene narrated script. On the final line, output '
        "a one-sentence RECAP for continuity, prefixed with 'RECAP:'."
    )
    return '\n'.join(parts)


# ── recap harvesting (for full serialization) ────────────────────────────────
def _std_recap_for(pid: str, entry: dict) -> str:
    title, synopsis = '', ''
    try:
        sp = os.path.join(_RUNTIME_DIR, f'storyteller_{pid}_state.json')
        d = json.load(open(sp, encoding='utf-8'))
        title = (d.get('story_title') or '').strip()
        script = d.get('script') or []
        if isinstance(script, list) and script:
            first = script[0]
            if isinstance(first, dict):
                synopsis = first.get('narration') or first.get('text') or first.get('description') or ''
            elif isinstance(first, str):
                synopsis = first
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('episode state unreadable, labelling it from the beat instead: %s', _exc)
    core = title or synopsis[:140] or (entry.get('beat') or '')[:140] or 'episode generated'
    return f'Ep {entry.get("episode_no")}: {core}'.strip()[:240]


def _std_apply_completion(entry: dict, serial: dict, templates_by_id: dict) -> None:
    tid = entry.get('template_id')
    t = templates_by_id.get(tid) or {}
    s = _std_serial_for(serial, tid)
    n = int(entry.get('episode_no') or (int(s.get('episode_no', 0)) + 1))
    s['episode_no'] = n
    # recap
    recap = _std_recap_for(entry.get('pipeline_id'), entry)
    recaps = list(s.get('recent_recaps') or [])
    recaps.append(recap)
    s['recent_recaps'] = recaps[-_STD_RECENT_RECAPS:]
    s['story_so_far'] = '\n'.join(s['recent_recaps'])
    # beat record
    rec = entry.get('_beat_record') or {}
    if 'used_beats' in rec:
        s['used_beats'] = (s.get('used_beats') or [])[-40:] + [rec['used_beats']]
    if 'used_layers' in rec:
        s['used_layers'] = (s.get('used_layers') or [])[-40:] + [rec['used_layers']]
    if 'used_eras' in rec:
        s['used_eras'] = (s.get('used_eras') or [])[-20:] + [rec['used_eras']]
    arc = _std_current_arc(t, n)
    s['current_arc'] = arc.get('name') if arc else s.get('current_arc')
    s['last_episode_at'] = _ams_iso()
    s['last_pipeline_id'] = entry.get('pipeline_id')
    s['last_status'] = 'done'


# ── batch lifecycle ──────────────────────────────────────────────────────────
def _std_create_daily_batch() -> dict:
    """Build today's batch: one episode entry per enabled template. Ready templates are
    'scheduled' (the tick launches them one at a time); the rest are 'blocked'."""
    with _STD_LOCK:
        serial = _std_serial_load()
        episodes = []
        for t in _std_templates():
            tid = t['id']
            s = _std_serial_for(serial, tid)
            next_no = int(s.get('episode_no', 0)) + 1
            ready, reason = _std_template_ready(t)
            episodes.append(
                {
                    'template_id': tid,
                    'series_title': t.get('series_title', ''),
                    'character': (t.get('character') or {}).get('name', ''),
                    'episode_no': next_no,
                    'status': 'scheduled' if ready else 'blocked',
                    'blocked_reason': None if ready else reason,
                    'pipeline_id': None,
                    'beat': None,
                    '_beat_record': None,
                    'started_at': None,
                    'ended_at': None,
                    'error': None,
                }
            )
        # Daily cap from the Storyteller card: scheduled episodes past the cap wait
        # for another day (blocked, with the reason on the card).
        _cap = _std_max_per_day()
        _n_sched = 0
        for e in episodes:
            if e['status'] == 'scheduled':
                _n_sched += 1
                if _n_sched > _cap:
                    e['status'] = 'blocked'
                    e['blocked_reason'] = f'over the daily cap of {_cap}'
        _std_serial_save(serial)  # persist any freshly-initialised series
        batch = {
            'batch_date': _std_today(),
            'created_at': _ams_iso(),
            'auto': True,
            'episodes': episodes,
        }
        _std_batch_save(batch)
        _zero_audit_log(
            'storyteller_daily_batch_created',
            {
                'date': batch['batch_date'],
                'scheduled': sum(1 for e in episodes if e['status'] == 'scheduled'),
                'blocked': sum(1 for e in episodes if e['status'] == 'blocked'),
            },
        )
        return batch


def _std_start_episode(entry: dict, templates_by_id: dict, serial: dict) -> None:
    t = templates_by_id.get(entry['template_id']) or {}
    s = _std_serial_for(serial, entry['template_id'])
    episode_no = int(entry.get('episode_no') or (int(s.get('episode_no', 0)) + 1))
    beat = _std_pick_beat(t, s)
    duration = _std_duration_min(t, episode_no)
    story_prompt = _std_build_story_prompt(t, s, beat, episode_no, duration)
    char = t.get('character') or {}
    res = _start_storyteller_pipeline_internal(
        directive=story_prompt,
        char_id=(char.get('char_id') or ''),
        character_params=_std_character_params(t),
        voice_style=(t.get('settings') or {}).get('voice_style', 'narration'),
        clip_duration_minutes=duration,
        camera_mode=(t.get('settings') or {}).get('camera_mode', 'automatic'),
        story_prompt=story_prompt,
        visual_style=(t.get('settings') or {}).get('visual_style', 'cinematic'),
        narration_enabled=True,
        user_name='storyteller-daily',
        model_family=_STD_MODEL_FAMILY,
    )
    entry['beat'] = beat.get('directive')
    entry['_beat_record'] = beat.get('record') or {}
    if isinstance(res, dict) and res.get('status') == 'running' and res.get('job_id'):
        entry['status'] = 'in_production'
        entry['pipeline_id'] = res['job_id']
        entry['started_at'] = _ams_iso()
        _zero_audit_log(
            'storyteller_daily_episode_started',
            {'template_id': entry['template_id'], 'episode_no': episode_no, 'pipeline_id': res['job_id']},
        )
    else:
        entry['status'] = 'failed'
        entry['error'] = (res or {}).get('error', 'start failed') if isinstance(res, dict) else 'start failed'
        entry['ended_at'] = _ams_iso()


def _std_batch_tick() -> None:
    """Advance the current batch sequentially: settle any in-production episode, then
    launch the next scheduled one (only while the toggle is ON and RAM allows)."""
    with _STD_LOCK:
        batch = _std_batch_load()
        eps = batch.get('episodes') if isinstance(batch, dict) else None
        if not eps:
            return
        serial = _std_serial_load()
        tbid = _std_templates_by_id()
        changed = False

        # 1) settle in-production
        for e in eps:
            if e.get('status') == 'in_production':
                outcome = _std_pipeline_outcome(e.get('pipeline_id'))
                if outcome == 'done':
                    e['status'] = 'done'
                    e['ended_at'] = _ams_iso()
                    _std_apply_completion(e, serial, tbid)
                    changed = True
                elif outcome == 'failed':
                    e['status'] = 'failed'
                    e['ended_at'] = _ams_iso()
                    e['error'] = e.get('error') or 'pipeline failed'
                    changed = True
                # 'running'/'unknown' -> leave it; sequential (one at a time)
                break

        # if something is still in production, don't start another
        in_prod = any(e.get('status') == 'in_production' for e in eps)
        if changed:
            _std_batch_save(batch)
            _std_serial_save(serial)
        if in_prod:
            return

        # 2) start the next scheduled episode — only while enabled, not paused, RAM ok
        _daily_now = _std_daily_load()
        if not _daily_now.get('enabled') or _daily_now.get('paused'):
            return
        nxt = next((e for e in eps if e.get('status') == 'scheduled'), None)
        if not nxt:
            return
        if _std_free_ram_gb() < _std_min_ram():
            return  # retry next tick
        _std_start_episode(nxt, tbid, serial)
        _std_batch_save(batch)
        _std_serial_save(serial)


def _std_scheduler_tick() -> None:
    """At most one new batch per calendar day. If the previous day's batch is still
    unfinished (22 heavy episodes may not fit in 24h), let it CARRY OVER rather than
    replacing it — no series' work is abandoned."""
    daily = _std_daily_load()
    if not daily.get('enabled'):
        return
    today = _std_today()
    batch = _std_batch_load()
    # carry-over: an active (unsettled) batch finishes before a new one is made
    if isinstance(batch, dict) and batch.get('episodes'):
        active = any(e.get('status') in ('scheduled', 'in_production') for e in batch['episodes'])
        if active:
            return
        if batch.get('batch_date') == today and daily.get('done_date') == today:
            return  # today's batch already made and fully settled
    if daily.get('done_date') == today:
        return
    _std_create_daily_batch()
    daily['done_date'] = today
    daily['last_run_at'] = _ams_iso()
    _std_daily_save(daily)


def _std_watcher() -> None:
    """Daemon: settle/advance the batch and fire the daily batch, every 30 s."""
    while True:
        time.sleep(30)
        try:
            _std_scheduler_tick()
        except Exception as _exc:
            _zyg_log.warning('storyteller scheduler tick failed, retrying in 30 s: %s', _exc)
        try:
            _std_batch_tick()
        except Exception as _exc:
            _zyg_log.warning('storyteller batch tick failed, retrying in 30 s: %s', _exc)


# ── display helper ───────────────────────────────────────────────────────────
def _std_templates_display() -> list:
    serial = _std_serial_load()
    out = []
    for t in _std_templates():
        c = t.get('character') or {}
        s = serial.get(t['id'], {})
        ser = t.get('serialization') or {}
        settings = t.get('settings') or {}
        ready, reason = _std_template_ready(t)
        out.append(
            {
                'id': t['id'],
                'order': t.get('order'),
                'series_title': t.get('series_title', ''),
                'logline': t.get('logline', ''),
                'setting': t.get('setting', ''),
                'genre': t.get('genre', ''),
                'character': c.get('name', ''),
                'age': c.get('age'),
                'gender': c.get('gender', ''),
                'heritage': c.get('ethnic_heritage', ''),
                'char_id': c.get('char_id'),
                'lora_status': c.get('lora_status', 'pending'),
                'ready': ready,
                'status_reason': reason,
                'model_family': settings.get('model_family', 'sdxl'),
                'render_style': settings.get('render_style', ''),
                'duration_range': settings.get('duration_min_range', [12, 18]),
                'episode_no': int(s.get('episode_no', 0)),
                'current_arc': s.get('current_arc'),
                'total_episodes': ser.get('total_episodes'),
                'source_doc': t.get('source_doc', ''),
            }
        )
    return out


# ── HTTP endpoints ───────────────────────────────────────────────────────────
@bp.route('/api/storyteller/daily_mode', methods=['GET', 'POST'])
def api_storyteller_daily_mode():
    """GET or POST the Storyteller daily-serial auto-mode toggle."""
    if request.method == 'GET':
        return jsonify(_std_daily_load())
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled'))
    try:
        _std_daily_set(enabled)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'batch create failed: {e}'}), 500
    return jsonify({'ok': True, 'enabled': enabled, 'state': _std_daily_load()})


@bp.route('/api/storyteller/daily_batch')
def api_storyteller_daily_batch():
    """Current batch + toggle state, for the approval-queue UI."""
    batch = _std_batch_load()
    return jsonify({'batch': batch or None, 'daily': _std_daily_load()})


@bp.route('/api/storyteller/templates/list')
def api_storyteller_templates_list():
    """The 22 series templates, display-shaped, for the Asset Manager Templates tab."""
    tpls = _std_templates_display()
    return jsonify(
        {
            'templates': tpls,
            'count': len(tpls),
            'daily': _std_daily_load(),
            'allow_unlocked': _std_allow_unlocked(),
        }
    )


@bp.route('/api/storyteller/templates/<tid>')
def api_storyteller_template_detail(tid):
    t = _std_templates_by_id().get(tid)
    if not t:
        return jsonify({'error': 'not found'}), 404
    return jsonify(t)


# ── start the watcher daemon (single process, use_reloader=False → runs once) ──
threading.Thread(target=_std_watcher, daemon=True, name='storyteller-daily-watcher').start()
