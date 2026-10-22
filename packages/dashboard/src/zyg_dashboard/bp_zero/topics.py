# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bp_zero — topic discovery and filtering, the approval-queue bank and the batch launch helpers.

Moved verbatim out of bp_zero.py (original lines 746-1231) by the 2026-10-06
modularization wave; zero logic edits.
"""

from zyg_dashboard.bp_zero.constants import (
    _AMS_TZ,
    _RUNTIME_DIR,
    _SPORTS_KEYWORD_BLOCKLIST,
    _ZERO_KANBAN_LOCK,
    _ZERO_POOL_LABELS,
    _ZERO_POOL_PICK_COUNT,
    _ZERO_PUB_TIMES,
    _ZERO_TOPICS_PENDING,
    _ZERO_TOPICS_PENDING_PATH,
    _ZERO_TOPICS_TTL,
    _ZERO_TOPIC_POOLS_PATH,
    _ams_iso,
    _ams_now,
    _record_token_usage,
    _workflow_jobs,
    _zero_audit_log,
    _zyg_log,
    _zyg_pkg_dir,
    jsonify,
    os,
    re,
)

# ── re-export surface ────────────────────────────────────────────────────────
# This module inherits the pre-split top import block. `_zyg_pkg_dir` is the
# only name in it this file does not read itself; it is kept here because the
# package's modules re-import the block off each other. Declaring it is what
# makes the re-export deliberate rather than an unused import; nothing does
# ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    '_zyg_pkg_dir',
]


def _zero_pending_save() -> None:
    """Persist _ZERO_TOPICS_PENDING to disk so it survives Flask restarts."""
    try:
        import json as _jp

        with open(_ZERO_TOPICS_PENDING_PATH, 'w', encoding='utf-8') as _f:
            _jp.dump(_ZERO_TOPICS_PENDING, _f)
    except Exception as _exc:
        _zyg_log.warning('pending topics not persisted, they are lost on restart: %s', _exc)


def _zero_pending_load(client_ip: str) -> dict:
    """Load pending entry for client_ip from disk (fallback when not in memory)."""
    try:
        import json as _jp

        with open(_ZERO_TOPICS_PENDING_PATH, 'r', encoding='utf-8') as _f:
            _data = _jp.load(_f)
        entry = _data.get(client_ip, {})
        if entry:
            _ZERO_TOPICS_PENDING[client_ip] = entry
        return entry
    except Exception:
        return {}


def _zero_fetch_trending_raw() -> list:
    """Fetch ~100 raw trending topics by hitting 10 English-speaking country RSS feeds in parallel."""
    # defusedxml, not xml.etree: the RSS below comes off the network, so entity-expansion
    # and external-entity attacks have to be refused by the parser rather than trusted away.
    from defusedxml import ElementTree as _ET
    import requests as _req_gt
    import threading as _thr_gt
    import re as _re_gt

    _GEO_CODES = ['US', 'GB', 'CA', 'AU', 'IN', 'IE', 'NZ', 'ZA', 'SG', 'NG']
    _ns = {'ht': 'https://trends.google.com/trending/rss'}
    _headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
    _lock = _thr_gt.Lock()
    _raw = []  # [(vol, title)]

    def _fetch_geo(geo):
        try:
            _r = _req_gt.get(f'https://trends.google.com/trending/rss?geo={geo}', headers=_headers, timeout=10)
            if _r.status_code != 200:
                return
            _root = _ET.fromstring(_r.text)
            for _item in _root.findall('.//item'):
                _title = (_item.findtext('title') or '').strip()
                _traffic = (_item.findtext('ht:approx_traffic', namespaces=_ns) or '0+').rstrip('+').replace(',', '')
                try:
                    _vol = int(_traffic)
                except ValueError:
                    _vol = 0
                # Keep only ASCII/Latin titles (skip Hindi, Arabic, etc.)
                if _title and _re_gt.match(r'^[\x20-\x7EÀ-ɏ]+$', _title):
                    with _lock:
                        _raw.append((_vol, _title))
        except Exception as _exc:
            _zyg_log.debug('trends fetch for %s failed, its titles are missing from the pool: %s', geo, _exc)

    _threads = [_thr_gt.Thread(target=_fetch_geo, args=(g,), daemon=True) for g in _GEO_CODES]
    for _t in _threads:
        _t.start()
    for _t in _threads:
        _t.join(timeout=14)

    # Deduplicate by lowercase title, keep highest traffic value
    _seen = {}
    for _vol, _title in _raw:
        _k = _title.lower()
        if _k not in _seen or _vol > _seen[_k][0]:
            _seen[_k] = (_vol, _title)

    _sorted = sorted(_seen.values(), key=lambda x: x[0], reverse=True)
    return [_t for _, _t in _sorted[:120]]


def _sports_pre_filter(topics: list) -> list:
    """Remove topics that contain sports-specific keywords before the Haiku call."""
    _filtered = []
    for _t in topics:
        _tl = _t.lower()
        if not any(_kw in _tl for _kw in _SPORTS_KEYWORD_BLOCKLIST):
            _filtered.append(_t)
    return _filtered


def _zero_filter_documentary_topics(raw_topics: list) -> list:
    """Pre-filter sports keywords, then single Haiku call to rank 10 documentary-worthy topics."""
    import anthropic as _anth_ft
    import re as _re_ft

    _api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not _api_key or not raw_topics:
        return raw_topics[:10]

    # Layer 1: deterministic keyword blocklist (fast, free)
    _pre_filtered = _sports_pre_filter(raw_topics)
    # If blocklist wiped almost everything, fall back to full raw list for Haiku
    _pool = _pre_filtered if len(_pre_filtered) >= 15 else raw_topics

    _numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(_pool[:100]))

    _prompt = (
        'Below is a list of current trending Google searches from around the world.\n'
        'Select exactly 10 that have genuine depth for a 10-15 minute narrated documentary.\n\n'
        'INCLUDE topics with:\n'
        '- Historical context or precedent\n'
        '- Social, political, or geopolitical significance\n'
        '- Scientific, environmental, or public-health importance\n'
        '- Cultural phenomena with real-world impact\n'
        '- Infrastructure, aviation, or public-safety events\n'
        '- International conflicts, elections, or diplomatic events\n\n'
        'EXCLUDE without exception — do NOT include ANY of the following, even if they have political side-stories:\n'
        '- Any sports tournament, league, cup, or championship (e.g. World Cup, Wimbledon, Grand Prix, T20, NBA playoffs)\n'
        '- Individual athlete or sports player names (e.g. "Jrue Holiday", "Tsitsipas", "Ronaldo")\n'
        '- Sports match scores, brackets, exits, or standings\n'
        '- Topics where the PRIMARY subject is a sporting event or competition, even if a politician reacts to it\n'
        '- Stock tickers, company earnings, or financial results\n'
        '- Weather or traffic queries\n'
        '- Individual TV show episodes or character names\n'
        '- Local crime incidents with no broader social significance\n'
        '- Celebrity gossip or relationship news with no broader context\n\n'
        f'Trending topics:\n{_numbered}\n\n'  # nosec B608  # prose for the LLM, not SQL: no database is touched here
        'Output a numbered list of exactly 10 topic titles copied EXACTLY from the list above, '
        'ranked by documentary potential (best first). No explanations, no commentary. '
        'If there are fewer than 10 non-sports topics, output as many as exist.'
    )

    try:
        _client = _anth_ft.Anthropic(api_key=_api_key)
        _resp = _client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            temperature=0.0,
            messages=[{'role': 'user', 'content': _prompt}],
        )
        _record_token_usage(
            model='claude-haiku-4-5-20251001',
            prompt_tokens=_resp.usage.input_tokens,
            completion_tokens=_resp.usage.output_tokens,
            stage='zero_find_topics_filter',
            pipeline_type='agent_zero',
        )
        _raw_out = _resp.content[0].text.strip()
        _titles = _re_ft.findall(r'^\d+\.\s+(.+)$', _raw_out, _re_ft.MULTILINE)

        # Validate: only accept titles that actually exist in _pool
        _pool_lower = {t.lower(): t for t in _pool}
        _valid = []
        for _t in _titles:
            _tc = _t.strip()
            if _tc in _pool:
                _valid.append(_tc)
            elif _tc.lower() in _pool_lower:
                _valid.append(_pool_lower[_tc.lower()])
            if len(_valid) == 10:
                break

        # Final safety pass: strip any that slipped through the blocklist
        _valid = [t for t in _valid if not any(kw in t.lower() for kw in _SPORTS_KEYWORD_BLOCKLIST)]

        if len(_valid) >= 4:
            return _valid[:10]
    except Exception as _exc:
        _zyg_log.warning('topic ranking failed, falling back to the pre-filtered list: %s', _exc)

    # Fallback: pre-filtered list without Haiku, highest traffic first
    return (_pre_filtered if len(_pre_filtered) >= 4 else raw_topics)[:10]


def _zero_produced_topics() -> set:
    """Topics that already have a scholarly run on disk, normalised for compare."""
    import glob as _glob_pt
    import json as _json_pt

    _made = set()
    try:
        for _p in _glob_pt.glob(os.path.join(_RUNTIME_DIR, 'pipeline_*_state.json')):
            try:
                with open(_p, 'r', encoding='utf-8') as _f:
                    _d = _json_pt.load(_f)
            except Exception as _exc:
                _zyg_log.debug('pipeline state %s unreadable, skipped: %s', _p, _exc)
                continue
            if _d.get('department') != 'scholarly':
                continue
            for _k in ('scholarly_topic', 'essay_title'):
                _t = str(_d.get(_k) or '').strip().lower()
                # 'history'/'general' are department placeholders, not topics
                if _t and _t not in ('history', 'general', 'unknown'):
                    _made.add(re.sub(r'[^a-z0-9 ]', '', _t).strip())
    except Exception as _exc:
        _zyg_log.warning('produced-topic scan failed, topics may be picked twice: %s', _exc)
    return _made


# ── Approval Queue settings + Pre-Emptive bank glue (2026-09-20) ────────────
# The cadence used to be module constants (6 topics, +2 days @ 09:00, 24 GB); the
# rebuilt Approval Queue board edits them per card (approval_queue_settings.py).
# Bank: topics whose Claude calls were recorded in advance (preempt_bank.py) are
# used before the pools when `use_bank_first` is on; the run then replays them.
def _aq_get(key: str, default):
    try:
        from zyg_dashboard import approval_queue_settings as _aqs

        return _aqs.get('documentary', key)
    except Exception:  # noqa: BLE001
        return default


def _aq_topics_per_batch() -> int:
    return max(1, min(12, int(_aq_get('topics_per_batch', _ZERO_POOL_PICK_COUNT))))


def _aq_bank():
    try:
        from zyg_dashboard import preempt_bank as _pb

        return _pb
    except Exception:  # noqa: BLE001
        return None


def _zero_next_batch_topics() -> list:
    """The next batch's topics: [{'topic', 'bank_id', 'label'}]. Pre-built bank entries
    first (claimed here), the rest drawn from the pools."""
    n = _aq_topics_per_batch()
    out = []
    _pb = _aq_bank()
    if _pb is not None and _aq_get('use_bank_first', True):
        try:
            for e in _pb.take_ready(n):
                out.append({'topic': e['topic'], 'bank_id': e['id'], 'label': e.get('pool') or 'bank'})
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('bank take_ready failed, the batch is filled from the pools only: %s', _exc)
    if len(out) < n:
        _have = {re.sub(r'[^a-z0-9 ]', '', t['topic'].lower()).strip() for t in out}
        for _label, _topic in _zero_fetch_pool_topics():
            if len(out) >= n:
                break
            if re.sub(r'[^a-z0-9 ]', '', str(_topic).lower()).strip() in _have:
                continue
            out.append({'topic': _topic, 'bank_id': None, 'label': _label})
    return out[:n]


def _zero_pipeline_options_for(entry: dict) -> dict | None:
    if entry.get('bank_id'):
        return {'preempt': {'mode': 'replay', 'entry': entry['bank_id']}}
    return None


def _zero_bank_settle(entry: dict, outcome: str) -> None:
    _pb = _aq_bank()
    if _pb is None or not entry.get('bank_id'):
        return
    try:
        _stats = (_workflow_jobs.get(entry.get('pipeline_id') or '') or {}).get('preempt_stats')
        _pb.settle(entry['bank_id'], outcome, _stats)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('bank entry %s not settled as %s: %s', entry.get('bank_id'), outcome, _exc)


def _zero_stop_job(pid: str) -> bool:
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


def _zero_auto_mode_set(enabled: bool) -> dict:
    """The Documentary card's play (enable → today's batch starts now) / off."""
    # function-local: keeps the blueprint registration order chat -> topics -> kanban
    from zyg_dashboard.bp_zero import kanban as _kanban

    state = _kanban._zero_auto_mode_load()
    state['enabled'] = bool(enabled)
    state['paused'] = False
    if enabled:
        state['next_run_utc'] = None
        _kanban._zero_auto_mode_save(state)
        picks = _zero_next_batch_topics()
        _kanban._zero_kanban_create_batch(picks, auto_triggered=True)
        _zero_audit_log(
            'auto_mode_enabled',
            {'topics': [t['topic'] for t in picks], 'from_bank': sum(1 for t in picks if t.get('bank_id'))},
        )
    else:
        _kanban._zero_auto_mode_save(state)
        _zero_audit_log('auto_mode_disabled', {})
    return _kanban._zero_auto_mode_load()


def _zero_pause(paused: bool) -> dict:
    # function-local: keeps the blueprint registration order chat -> topics -> kanban
    from zyg_dashboard.bp_zero import kanban as _kanban

    state = _kanban._zero_auto_mode_load()
    state['paused'] = bool(paused)
    _kanban._zero_auto_mode_save(state)
    _zero_audit_log('auto_mode_paused' if paused else 'auto_mode_resumed', {})
    return state


def _zero_abort() -> dict:
    """Stop the running episode, mark the rest of the batch aborted, switch off."""
    # function-local: keeps the blueprint registration order chat -> topics -> kanban
    from zyg_dashboard.bp_zero import kanban as _kanban

    stopped = None
    with _ZERO_KANBAN_LOCK:
        batch = _kanban._zero_kanban_load()
        for e in (batch or {}).get('topics', []):
            if e.get('status') == 'in_production' and e.get('pipeline_id'):
                if _zero_stop_job(e['pipeline_id']):
                    stopped = e['pipeline_id']
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
                _zero_bank_settle(e, 'failed')
            elif e.get('status') == 'scheduled':
                e['status'] = 'failed'
                e['error'] = 'aborted by operator'
                e['ended_at'] = _ams_iso()
                _pb = _aq_bank()
                if _pb is not None and e.get('bank_id'):
                    try:
                        _pb.release(e['bank_id'])
                    except Exception as _exc:  # noqa: BLE001
                        _zyg_log.warning('bank entry %s not released, it stays claimed: %s', e.get('bank_id'), _exc)
        if batch:
            _kanban._zero_kanban_save(batch)
    state = _kanban._zero_auto_mode_load()
    state['enabled'] = False
    state['paused'] = False
    state['next_run_utc'] = None
    _kanban._zero_auto_mode_save(state)
    _zero_audit_log('auto_mode_aborted', {'stopped_pipeline': stopped})
    return state


def _zero_fetch_pool_topics() -> list:
    """Randomly pick 6 pools from 12, then 1 topic from each. Returns list of (label, topic).

    Skips topics already produced. Nothing checked this before, so a batch could
    re-make an episode that is already on the channel: 1283 pool topics against
    ~92 already produced puts the odds of at least one repeat per batch of 6 at
    roughly one in three. Falls back to picking anyway when a pool is exhausted
    — a repeat beats an empty slot, and it is logged.
    """
    import json as _json_pt
    import random as _rand_pt

    with open(_ZERO_TOPIC_POOLS_PATH, 'r', encoding='utf-8') as _f:
        _pools = _json_pt.load(_f)
    _made = _zero_produced_topics()

    def _norm(_t):
        return re.sub(r'[^a-z0-9 ]', '', str(_t or '').strip().lower()).strip()

    _all = list(_ZERO_POOL_LABELS)
    _rand_pt.shuffle(_all)
    _selected = _all[: _aq_topics_per_batch()]
    _picks, _chosen, _repeats = [], set(), []
    for _key, _label in _selected:
        _pool = _pools.get(_key, [])
        if not _pool:
            continue
        _fresh = [_t for _t in _pool if _norm(_t) not in _made and _norm(_t) not in _chosen]
        if _fresh:
            _pick = _rand_pt.choice(_fresh)
        else:
            # Pool exhausted against history — take any unused one this batch.
            _unused = [_t for _t in _pool if _norm(_t) not in _chosen] or _pool
            _pick = _rand_pt.choice(_unused)
            _repeats.append(_pick)
        _chosen.add(_norm(_pick))
        _picks.append((_label, _pick))
    if _repeats:
        _zyg_log.info(f'[ZERO] Topic dedup: {len(_repeats)} pool(s) exhausted, re-using {_repeats[:3]}')
    return _picks  # list of (label, topic_title)


def _zero_find_topics_handler(client_ip: str):
    """Pick 1 topic from each curated historical pool and present 6 documentary-ready topics."""
    import time as _time_tp

    try:
        _picks = _zero_fetch_pool_topics()
    except Exception as _e:
        return jsonify(
            {
                'response': f'Could not load topic pools ({_e}). Check zero_topic_pools.json.',
                'directive_executed': True,
            }
        )
    if not _picks:
        return jsonify(
            {
                'response': 'Topic pool is empty — check zero_topic_pools.json.',
                'directive_executed': True,
            }
        )

    topics = [_t for _, _t in _picks]
    _ZERO_TOPICS_PENDING[client_ip] = {'topics': topics, 'ts': _time_tp.time()}
    _zero_pending_save()

    lines = []
    for i, (_label, _topic) in enumerate(_picks, 1):
        lines.append(f' {i:2d}. ★ {_topic}  [{_label}]')
    body = '\n'.join(lines)
    response = (
        f'Here are 6 documentary topics drawn from curated historical sources:\n\n{body}\n\n'
        f'All 6 are selected (★). Type yes to launch all 6 pipelines, '
        f'or tell me which topics to swap.'
    )
    _zero_audit_log('find_topics', {'source': 'pools', 'topics': topics})
    return jsonify({'response': response, 'directive_executed': True})


def _zero_compute_batch_publish_slots(n: int = 6) -> list:
    """Return next n publish slots at 08:00/14:00/20:00 AMS, at least 2 h from now.
    Each entry: {publish_at, upload_at (1 h before), claimed_by}.
    """
    from datetime import datetime as _dt2, timedelta

    _now = _ams_now()
    _floor = _now + timedelta(hours=2)
    _slots, _day_offset = [], 0
    while len(_slots) < n:
        _day = (_now + timedelta(days=_day_offset)).date()
        for _t in _ZERO_PUB_TIMES:
            _h, _m = map(int, _t.split(':'))
            _pub = _dt2(_day.year, _day.month, _day.day, _h, _m, 0, tzinfo=_AMS_TZ)
            if _pub <= _floor:
                continue
            _slots.append(
                {
                    'publish_at': _pub.isoformat(timespec='seconds'),
                    'upload_at': (_pub - timedelta(hours=1)).isoformat(timespec='seconds'),
                    'claimed_by': None,
                }
            )
            if len(_slots) == n:
                break
        _day_offset += 1
    return _slots


def _zero_launch_topic_documentaries(client_ip: str):
    """Queue 6 scholarly topics; they run ONE AT A TIME.

    Not concurrent — the docstring said so for a long time and it was wrong.
    _zero_kanban_tick starts the next topic only when nothing is in_production,
    and holds behind a RAM gate between items. At the measured 28-43 min per
    episode a batch of 6 is roughly 3.5-4.5 hours, not one episode's wall clock.
    """
    import time as _time_tp

    # function-local: keeps the blueprint registration order chat -> topics -> kanban
    from zyg_dashboard.bp_zero import kanban as _kanban

    pending = _ZERO_TOPICS_PENDING.pop(client_ip, None) or _zero_pending_load(client_ip)
    _ZERO_TOPICS_PENDING.pop(client_ip, None)  # ensure removed from memory
    _zero_pending_save()  # persist removal to disk
    if not pending or (_time_tp.time() - pending['ts']) > _ZERO_TOPICS_TTL:
        return jsonify(
            {
                'response': "I don't have a pending topic list — type find topics to search again.",
                'directive_executed': True,
            }
        )
    topics = pending['topics']
    _kanban._zero_kanban_create_batch(topics[:6])
    _zero_audit_log('launch_topic_documentaries', {'topics': topics[:6]})

    bullet_lines = '\n'.join(f'  {i + 1}. {t}' for i, t in enumerate(topics[:6]))
    response = (
        f'Queued 6 documentary topics in the production kanban:\n\n'
        f'{bullet_lines}\n\n'
        f'Pipeline 1 is starting now. Each remaining topic will begin automatically '
        f'once the previous pipeline completes. Track progress in the Approval Queue tab.'
    )
    return jsonify({'response': response, 'directive_executed': True})
