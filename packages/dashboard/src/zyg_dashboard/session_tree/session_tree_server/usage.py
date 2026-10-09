# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Claude usage meter and the auto-spawn hold it arms.

Moved verbatim from session_tree_server.py lines 784-1166.
"""

from ._base import DATA, LOCK, _zyg_log, datetime, json, os, re, threading, time
from .storage import CFG, audit, iso, list_trees, now, save_tree
from .spawner_state import _spawn_stats

# Resolved on first call, not on import: spawner.kick_spawner is defined after this
# section in the original file, so importing it here would close a cycle.


def kick_spawner(*args, **kwargs):
    from .spawner import kick_spawner as _impl

    return _impl(*args, **kwargs)


# ───────────────────────────── Claude usage timer ─────────────────────────────
# Measured 2026-09-08 00:09→01:52: the login's 5-hour usage window was exhausted, every
# spawned executor printed "You've hit your limit · resets 2am (Europe/Amsterdam)" and
# exited, and the board pushed 123 spawns through the 10-min brake cycle until the
# window reset by itself. The board now reads the same meter the CLI's `/usage` and the
# VS Code status show (GET /api/oauth/usage with the login's OAuth token): utilization %
# and resets_at per window (5-hour session, 7-day, per-model weekly). A window at/above
# usage_hold_pct — or an executor that exits with the limit message — puts auto-spawn on
# HOLD until that window's resets_at (+ margin). The usage thread re-reads the meter at
# that moment and releases the hold when the % has dropped, otherwise extends it to the
# next reset. Tasks stay todo, no brake is counted, no retry is consumed: the tree
# simply resumes when Claude refreshes the window.
USAGE_URL = os.environ.get('SESSION_TREE_USAGE_URL') or 'https://api.anthropic.com/api/oauth/usage'
CRED_PATH = os.environ.get('SESSION_TREE_CREDENTIALS') or os.path.expanduser('~/.claude/.credentials.json')
USAGE_STATE = os.path.join(DATA, 'usage.json')
LIMIT_RE = re.compile(r'hit your (usage )?limit|usage limit (reached|exceeded)|out of extra usage|rate.?limited', re.I)
# 2026-09-22: 762 spawns over two days all died with "Your organization does not have access to Claude. Please
# login again" and nobody was told; the brake only paced them. An auth failure is a HOLD with a status line.
AUTH_RE = re.compile(
    r'does not have access to Claude|Please login again|not logged in|Invalid API key|'
    r'authentication_error|OAuth token has expired|Failed to authenticate',
    re.I,
)
_usage_evt = threading.Event()
_usage = {
    'ts': 0,
    'ok': False,
    'error': '',
    'windows': [],
    'polls': 0,
    'next_poll': 0,
    'want_poll': False,
    'hold_until': 0,
    'hold_since': 0,
    'hold_reason': '',
    'hold_source': '',
    'holds': 0,
    'last_resume': 0,
    'last_resume_note': '',
}
_USAGE_PERSIST = ('hold_until', 'hold_since', 'hold_reason', 'hold_source', 'holds', 'last_resume', 'last_resume_note')


def _usage_save():
    try:
        tmp = USAGE_STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({k: _usage[k] for k in _USAGE_PERSIST}, f)
        os.replace(tmp, USAGE_STATE)
    except Exception as e:
        _zyg_log.info(f'[session-tree] usage state not saved: {e!r}')


def _usage_load():
    try:
        with open(USAGE_STATE) as f:
            d = json.load(f)
        for k in _USAGE_PERSIST:
            if k in d:
                _usage[k] = d[k]
    except FileNotFoundError as _exc:
        _zyg_log.debug('no persisted usage state yet at %s: %s', USAGE_STATE, _exc)
    except Exception as e:
        _zyg_log.info(f'[session-tree] usage state unreadable: {e!r}')


def _iso_ts(v):
    """'2026-09-20T01:00:00.074185+00:00' → epoch; None when absent/unparseable."""
    if not v:
        return None
    try:
        if isinstance(v, (int, float)):
            return float(v)
        return datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp()
    except Exception:
        return None


def fetch_claude_usage(timeout=10.0):
    """Raw payload of /api/oauth/usage for this login (the token is never refreshed here;
    an expired one is reported — any interactive claude turn refreshes it)."""
    import urllib.request
    import urllib.error
    from urllib.parse import urlsplit

    try:
        with open(CRED_PATH, encoding='utf-8') as fh:
            cred = (json.load(fh) or {}).get('claudeAiOauth') or {}
    except (OSError, ValueError) as e:
        raise RuntimeError('no Claude login credentials at %s (%s)' % (CRED_PATH, type(e).__name__)) from e
    if not cred.get('accessToken'):
        raise RuntimeError('the Claude login has no OAuth access token')
    exp = cred.get('expiresAt')
    if exp and float(exp) / 1000.0 < now():
        raise RuntimeError(
            'the OAuth token expired at %s; an interactive claude turn refreshes it' % iso(float(exp) / 1000.0)
        )
    # USAGE_URL is overridable from the environment, so the scheme is checked before the
    # OAuth bearer token is attached to it: file:// or a custom handler would otherwise
    # see the token. safe_urlopen cannot be used here — it takes a URL, not a Request,
    # and this module is stdlib-only so that it runs under /usr/bin/python3.
    scheme = urlsplit(USAGE_URL).scheme.lower()
    if scheme not in ('http', 'https'):
        raise RuntimeError('refusing to send the OAuth token to a %s URL: %s' % (scheme or 'scheme-less', USAGE_URL))
    req = urllib.request.Request(  # nosec B310  # noqa: S310  scheme checked on the line above
        USAGE_URL,
        headers={
            'Authorization': 'Bearer %s' % cred['accessToken'],
            'anthropic-beta': 'oauth-2025-04-20',
            'Content-Type': 'application/json',
            'User-Agent': 'zygomatic-session-tree/1',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310  # noqa: S310  scheme checked above
            return json.loads(resp.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        raise RuntimeError('usage endpoint answered HTTP %s' % e.code) from e
    except Exception as e:
        raise RuntimeError(('usage endpoint unreachable: %s: %s' % (type(e).__name__, e))[:200]) from e


def parse_claude_usage(payload):
    """→ [{key, name, pct, resets_at, locked}] — the 5-hour session window, the 7-day
    window, then every scoped limit in limits[] (per model family / surface)."""
    out = []
    for key, name in (('five_hour', 'session (5 h)'), ('seven_day', 'week (7 d)')):
        w = payload.get(key) or {}
        u = w.get('utilization')
        out.append(
            {
                'key': key,
                'name': name,
                'pct': float(u) if isinstance(u, (int, float)) else None,
                'resets_at': _iso_ts(w.get('resets_at')),
                'locked': bool(w.get('locked_reason')),
            }
        )
    for lim in payload.get('limits') or []:
        if not isinstance(lim, dict) or lim.get('kind') in ('session', 'weekly_all'):
            continue
        scope = lim.get('scope') or {}
        model = (scope.get('model') or {}) if isinstance(scope, dict) else {}
        name = (
            model.get('display_name')
            or model.get('id')
            or (scope.get('surface') if isinstance(scope, dict) else None)
            or lim.get('kind')
            or 'scoped'
        )
        p = lim.get('percent')
        out.append(
            {
                'key': 'scoped:%s' % name,
                'name': '%s (weekly)' % name,
                'pct': float(p) if isinstance(p, (int, float)) else None,
                'resets_at': _iso_ts(lim.get('resets_at')),
                'locked': False,
            }
        )
    return out


def usage_hold_active():
    return now() < (_usage.get('hold_until') or 0)


def _usage_set_hold(until, reason, source, t=None):
    """Arm (or move) the hold. Audited when it is new or moves by more than a minute."""
    t = t or now()
    prev = _usage.get('hold_until') or 0
    new = prev <= t
    if new:
        _usage['hold_since'] = t
        _usage['holds'] = int(_usage.get('holds') or 0) + 1
    _usage.update(hold_until=until, hold_reason=reason[:300], hold_source=source)
    _usage_save()
    if new or abs(until - prev) > 60:
        audit(
            {
                'cmd': 'usage:hold',
                'ok': False,
                'role': 'spawner',
                'model': CFG['executor_model'],
                'error': 'auto-spawn on HOLD until %s (%s) — %s' % (iso(until), source, reason[:200]),
            }
        )
    return new


def _usage_release(note, t=None):
    """Drop the hold: clear the per-task cooldowns the limit exits left behind, forget the
    brake, wake the spawner. Tasks were never touched, so the tree just continues."""
    t = t or now()
    if not _usage.get('hold_until'):
        return
    held_s = int(t - (_usage.get('hold_since') or t))
    _usage.update(hold_until=0, hold_reason='', hold_source='', last_resume=t, last_resume_note=note[:200])
    _usage_save()
    _spawn_stats['brake_until'] = 0
    _spawn_stats['noclaim_streak'] = 0
    with LOCK:
        for tree in list_trees():
            ch = False
            for task in tree['tasks']:
                if task['status'] == 'todo' and (task.get('spawn_cooldown_until') or 0) > t:
                    task['spawn_cooldown_until'] = 0
                    ch = True
            if ch:
                save_tree(tree)
    audit(
        {
            'cmd': 'usage:resume',
            'ok': True,
            'role': 'spawner',
            'model': CFG['executor_model'],
            'error': 'auto-spawn resumes after %d s on hold — %s' % (held_s, note[:200]),
        }
    )
    kick_spawner()


def _hold_from_message(line, t=None):
    """An executor exited with the limit message. Hold now — before the next sweep can
    spawn another — using the reset time in the message ("resets 2am", "resets 14:30")
    as the provisional end; the usage thread is kicked to replace it with the meter's
    exact resets_at. Fallback when nothing parses: 10 minutes, re-read then."""
    t = t or now()
    until = None
    m = re.search(r'resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', line, re.I)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or '').lower()
        if ap == 'pm' and h < 12:
            h += 12
        if ap == 'am' and h == 12:
            h = 0
        if 0 <= h < 24 and 0 <= mi < 60:
            lt = time.localtime(t)
            cand = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, mi, 0, 0, 0, -1))
            if cand <= t:
                cand += 86400
            until = cand
    if until is None:
        until = t + 600
    until += CFG['usage_hold_margin_s']
    if until > (_usage.get('hold_until') or 0):
        _usage_set_hold(until, 'executor exit: ' + line.strip(), 'executor', t)
    _usage['want_poll'] = True
    _usage_evt.set()


def _auth_fail_in_log(logp):
    """The login-failure line in a spawned executor's log tail, or None."""
    try:
        with open(logp, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            tail = f.read().decode('utf-8', 'replace')
    except Exception:
        return None
    for ln in reversed(tail.splitlines()):
        if AUTH_RE.search(ln):
            return ln.strip()[:300]
    return None


def auth_hold_active():
    a = _spawn_stats
    return bool(a.get('auth_broken_since')) and now() - (a.get('auth_last_try') or 0) < CFG.get(
        'spawn_auth_retry_s', 900
    )


def _limit_hit_in_log(logp):
    """The limit line in a spawned executor's log tail, or None."""
    try:
        with open(logp, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            tail = f.read().decode('utf-8', 'replace')
    except Exception:
        return None
    for ln in reversed(tail.splitlines()):
        if LIMIT_RE.search(ln):
            return ln.strip()[:300]
    return None


def usage_poll(why='timer'):
    """Read the meter once and apply it. Network call outside the lock."""
    t = now()
    _usage['polls'] = int(_usage.get('polls') or 0) + 1
    _usage['want_poll'] = False
    _usage['next_poll'] = t + (CFG['usage_poll_s'] or 3600)
    try:
        windows = parse_claude_usage(fetch_claude_usage())
        _usage.update(ts=t, ok=True, error='', windows=windows)
    except Exception as e:
        _usage.update(ts=t, ok=False, error=str(e)[:200])
        if _usage.get('hold_until') and t >= _usage['hold_until']:
            # the timer ran out and the meter cannot confirm: resume; a limit still in
            # force comes back through the executors' own exits and re-arms the hold
            _usage_release('hold timer ran out; meter unreadable (%s)' % str(e)[:120], t)
        return
    over = [w for w in windows if (w['pct'] is not None and w['pct'] >= CFG['usage_hold_pct']) or w['locked']]
    if over:
        ends = [w['resets_at'] for w in over if w['resets_at']]
        until = (max(ends) if ends else t + 600) + CFG['usage_hold_margin_s']
        reason = 'meter: ' + ', '.join(
            '%s %s%%%s' % (w['name'], '?' if w['pct'] is None else int(w['pct']), ' locked' if w['locked'] else '')
            for w in over
        )
        if until > t and until > (_usage.get('hold_until') or 0) - 1:
            _usage_set_hold(until, reason, 'meter', t)
        elif until > t and _usage.get('hold_source') == 'executor':
            # the executor's parsed clock was later than the meter's resets_at — trust the meter
            _usage_set_hold(until, reason, 'meter', t)
        elif until <= t and _usage.get('hold_until') and t >= _usage['hold_until']:
            # the meter still says exhausted but its own resets_at is in the past (stale read):
            # the timer has run out, resume; a real limit re-arms through the executors' exits
            _usage_release('hold timer ran out; meter stale (%s, reset was due %s)' % (reason, iso(until)), t)
        return
    if _usage.get('hold_until'):
        if _usage.get('hold_source') == 'executor' and t < _usage['hold_until']:
            # executors are the ground truth for their own model's limit; the meter may
            # not show it (it reports per window, and the % is rounded). Keep the timer.
            return
        _usage_release(
            'meter read %s (%s)'
            % (', '.join('%s %s%%' % (w['name'], '?' if w['pct'] is None else int(w['pct'])) for w in windows), why),
            t,
        )


def usage_state():
    t = now()
    return {
        'ts': _usage.get('ts') or 0,
        'ok': bool(_usage.get('ok')),
        'error': _usage.get('error') or '',
        'windows': _usage.get('windows') or [],
        'polls': _usage.get('polls') or 0,
        'poll_s': CFG['usage_poll_s'],
        'hold_pct': CFG['usage_hold_pct'],
        'next_poll': _usage.get('next_poll') or 0,
        'url': USAGE_URL,
        'hold': t < (_usage.get('hold_until') or 0),
        'hold_until': _usage.get('hold_until') or 0,
        'hold_since': _usage.get('hold_since') or 0,
        'hold_reason': _usage.get('hold_reason') or '',
        'hold_source': _usage.get('hold_source') or '',
        'holds': _usage.get('holds') or 0,
        'last_resume': _usage.get('last_resume') or 0,
        'last_resume_note': _usage.get('last_resume_note') or '',
    }


def usage_thread():
    """The timer. Sleeps until the next poll or the hold's end, whichever is first, and
    is woken early by _usage_evt (an executor reported the limit / operator re-check)."""
    while True:
        t = now()
        waits = []
        if CFG['usage_poll_s']:
            waits.append(max(1.0, (_usage.get('next_poll') or 0) - t))
        hu = _usage.get('hold_until') or 0
        if hu:
            waits.append(max(1.0, hu - t))
        _usage_evt.wait(min(waits) if waits else 3600)
        _usage_evt.clear()
        t = now()
        due = (
            _usage.get('want_poll') or (CFG['usage_poll_s'] and t >= (_usage.get('next_poll') or 0)) or (hu and t >= hu)
        )
        if not due:
            continue
        try:
            usage_poll('hold timer' if (hu and t >= hu) else 'timer')
        except Exception as e:
            _zyg_log.info(f'[session-tree] usage poll error: {e!r}')
            _usage['next_poll'] = now() + 60
