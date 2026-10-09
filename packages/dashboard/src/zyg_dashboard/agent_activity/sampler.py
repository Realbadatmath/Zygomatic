# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_dashboard.agent_activity.tunables import (
    _CPU_ACTIVE_PCT,
    _EVAL_RE,
    _EVAL_RE2,
    _EVENT_CAP,
    _ICONS,
    _KIND_PATTERNS,
    _LEDGER_FILE,
    _NCPU,
    _NVIDIA_S,
    _OPEN_FLUSH_S,
    _OPEN_SPANS_FILE,
    _RAM_ACTIVE_MB,
    _REDACT_RE,
    _SAMPLE_S,
    _SELF_RE,
    _SESS_DIR,
    _SESS_EVENT_CAP,
    _SPAN_GRACE_S,
    _SPAN_MIN_S,
    _UID,
    _VRAM_ACTIVE_MB,
    _iso,
    _now_iso,
)
import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__)


# ── State ───────────────────────────────────────────────────────────────────
_lock = threading.RLock()
_started = False
_thread = None

_tracked: dict[int, dict] = {}  # pid -> tracked agent-owned process record
_ignored: dict[int, float] = {}  # pid -> create_time, "checked, not an agent proc"
_sessions: dict[str, dict] = {}  # sid -> durable per-session record
_events: deque = deque(maxlen=_EVENT_CAP)
_seq = 0
_gpu = {'total_mb': 0.0, 'used_mb': 0.0, 'util_pct': 0.0, 'agent_mb': 0.0, 'other_mb': 0.0, 'at': 0.0, 'ok': False}
_gpu_pids: dict[int, float] = {}
_last_sample = 0.0
_sampler_error = ''
_transcripts: dict[str, dict] = {}  # sid -> {'path','size','mtime','items'}
_spans: dict[tuple, dict] = {}  # (sid, device) -> open activity span
_open_flushed = 0.0
_open_dirty = False


def _emit(sid: str, kind: str, text: str, level: str = 'info') -> None:
    """Append one event to the global feed and to the session's own feed.

    Called with ``_lock`` held.  The global feed is what the Live Tail's main
    Pipeline Log pane consumes (so agent work shows up next to pipeline work);
    the per-session feed is what a session's own subtab shows.
    """
    global _seq
    _seq += 1
    ev = {
        'seq': _seq,
        'ts': _now_iso(),
        'sid': sid,
        'short': (sid or '')[:8],
        'kind': kind,
        'level': level,
        'text': text,
    }
    _events.append(ev)
    s = _sessions.get(sid)
    if s is not None:
        s['events'].append(ev)


# ── Session registry ────────────────────────────────────────────────────────
def _proc_start_ticks(pid: int):
    """Field 22 of /proc/<pid>/stat — the only pid-reuse-proof identity we get.

    Parsed from the LAST ``)`` rather than by splitting on spaces: field 2 is
    the executable name in parentheses and may itself contain spaces.
    """
    try:
        with open(f'/proc/{pid}/stat', 'rb') as fh:
            raw = fh.read().decode('utf-8', 'replace')
        return raw.rsplit(')', 1)[1].split()[19]
    except Exception:
        return None


def _live_sessions() -> dict[str, dict]:
    """Read ~/.claude/sessions/<pid>.json and keep the entries still running."""
    out: dict[str, dict] = {}
    try:
        files = os.listdir(_SESS_DIR)
    except OSError:
        return out
    for fn in files:
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(_SESS_DIR, fn), 'r', encoding='utf-8') as fh:
                d = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('skipping unreadable session file %s: %s', fn, _exc)
            continue
        pid, sid = d.get('pid'), d.get('sessionId')
        if not isinstance(pid, int) or not sid:
            continue
        want = str(d.get('procStart') or '')
        have = _proc_start_ticks(pid)
        if have is None or (want and want != str(have)):
            continue  # dead, or the pid was recycled by something else
        cwd = d.get('cwd') or ''
        out[sid] = {
            'id': sid,
            'short': sid[:8],
            'pid': pid,
            'name': d.get('name') or sid[:8],
            'cwd': cwd,
            'project': os.path.basename(cwd.rstrip('/')) or cwd,
            'kind': d.get('kind') or '',
            'entrypoint': d.get('entrypoint') or '',
            'started': _iso((d.get('startedAt') or 0) / 1000.0) if d.get('startedAt') else '',
            'started_ms': d.get('startedAt') or 0,
        }
    return out


# ── GPU ─────────────────────────────────────────────────────────────────────
_NVML = {'mod': None, 'handles': None, 'tried': False}


def _nvml():
    """NVML handles, or None.

    The installed pynvml is the deprecated shim and prints a FutureWarning on
    import, so the import is wrapped — a warning in the kanban log every restart
    is noise, and the numbers are identical to nvidia-smi's (verified against it
    on the same processes).
    """
    if _NVML['tried']:
        return _NVML['mod']
    _NVML['tried'] = True
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            import pynvml
        pynvml.nvmlInit()
        _NVML['handles'] = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
        _NVML['mod'] = pynvml
    except Exception:
        _NVML['mod'] = None
    return _NVML['mod']


def _nvidia_refresh() -> None:
    """Per-PID VRAM + whole-card totals.

    NVML first (0.36 ms for processes + memory + utilisation), nvidia-smi as the
    fallback when NVML is unavailable.  Compute apps owned by other users (the
    `ollama` runner is the common case) are unreadable and stay in `other_mb` —
    never attributed to an agent.
    """
    now = time.time()
    if _NVIDIA_S and now - _gpu['at'] < _NVIDIA_S:
        return
    _gpu['at'] = now

    nv = _nvml()
    if nv is not None:
        try:
            total = used = util = 0.0
            fresh: dict[int, float] = {}
            for h in _NVML['handles'] or []:
                mem = nv.nvmlDeviceGetMemoryInfo(h)
                total += mem.total / 1048576.0
                used += mem.used / 1048576.0
                try:
                    util = max(util, float(nv.nvmlDeviceGetUtilizationRates(h).gpu))
                except Exception as _exc:
                    _zyg_log.debug('gpu utilization query skipped: %s', _exc)
                for pr in nv.nvmlDeviceGetComputeRunningProcesses(h):
                    if pr.usedGpuMemory:
                        fresh[int(pr.pid)] = fresh.get(int(pr.pid), 0.0) + pr.usedGpuMemory / 1048576.0
            _gpu['total_mb'], _gpu['used_mb'], _gpu['util_pct'] = total, used, util
            _gpu_pids.clear()
            _gpu_pids.update(fresh)
            _gpu['ok'] = True
            return
        except Exception:
            _NVML['mod'] = None  # fall through to nvidia-smi from now on

    exe = shutil.which('nvidia-smi')
    if not exe:
        _gpu['ok'] = False
        return
    try:
        r = subprocess.run(
            [exe, '--query-gpu=memory.total,memory.used,utilization.gpu', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=6,
        )
        line = (r.stdout or '').strip().splitlines()
        if line:
            parts = [p.strip() for p in line[0].split(',')]
            _gpu['total_mb'] = float(parts[0]) if parts[0].isdigit() else 0.0
            _gpu['used_mb'] = float(parts[1]) if parts[1].isdigit() else 0.0
            _gpu['util_pct'] = float(parts[2]) if parts[2].isdigit() else 0.0
        r2 = subprocess.run(
            [exe, '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=6,
        )
        fresh: dict[int, float] = {}
        for ln in (r2.stdout or '').splitlines():
            bits = [b.strip() for b in ln.split(',')]
            if len(bits) >= 2 and bits[0].isdigit():
                try:
                    fresh[int(bits[0])] = float(bits[1])
                except ValueError as _exc:
                    _zyg_log.debug('skipping unparseable nvidia-smi compute-apps row: %s', _exc)
                    continue
        _gpu_pids.clear()
        _gpu_pids.update(fresh)
        _gpu['ok'] = True
    except (OSError, subprocess.SubprocessError, ValueError):
        _gpu['ok'] = False


# ── Process classification ──────────────────────────────────────────────────
def _read_env(pid: int) -> dict:
    """CLAUDE_* markers out of /proc/<pid>/environ, or {}.

    Only the three keys are kept: the rest of an environment block routinely
    carries credentials, and none of it is needed here.
    """
    try:
        with open(f'/proc/{pid}/environ', 'rb') as fh:
            raw = fh.read(262_144)
    except (OSError, PermissionError):
        return {}
    out = {}
    for chunk in raw.split(b'\0'):
        if not chunk.startswith(b'CLAUDE'):
            continue
        try:
            k, _, v = chunk.decode('utf-8', 'replace').partition('=')
        except Exception as _exc:
            _zyg_log.debug('skipping undecodable /proc environ entry: %s', _exc)
            continue
        if k in ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_PID', 'CLAUDE_CODE_ENTRYPOINT'):
            out[k] = v
    return out


def _clean_cmd(cmdline: list[str]) -> str:
    """The command a human would recognise, unwrapped and redacted."""
    s = ' '.join(cmdline or []).strip()
    m = _EVAL_RE.search(s) or _EVAL_RE2.search(s)
    if m:
        s = m.group(1).strip()
    s = ' '.join(s.split())
    s = _REDACT_RE.sub(lambda mo: mo.group(1) + '***', s)
    return s[:400]


def _kind_of(cmd: str) -> str:
    low = cmd.lower()
    for kind, rx in _KIND_PATTERNS:
        if rx.search(low):
            return kind
    return 'proc'


def _is_detached(proc, claude_pid: int) -> bool:
    """True when the process has left its session's tree (setsid/nohup/reparent).

    Walked with a hard depth cap; a race where a parent dies mid-walk just
    reports detached, which is what it is by then anyway.
    """
    if not claude_pid:
        return True
    try:
        p = proc
        for _ in range(24):
            ppid = p.ppid()
            if ppid == claude_pid:
                return False
            if ppid <= 1:
                return True
            p = psutil.Process(ppid)
        return True
    except Exception:
        return True


# ── Sampler ─────────────────────────────────────────────────────────────────
def _sample() -> None:
    """One measurement pass.  Cheap enough to run every couple of seconds."""
    global _last_sample, _sampler_error
    if psutil is None:
        _sampler_error = 'psutil unavailable'
        return
    _nvidia_refresh()
    live = _live_sessions()
    seen: set[int] = set()
    now = time.time()

    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'uids']):
        try:
            info = proc.info
            pid = info['pid']
            if pid == os.getpid():
                continue
            uids = info.get('uids')
            if uids is not None and uids.real != _UID:
                continue  # another user's environ is unreadable anyway
            ct = info.get('create_time') or 0.0

            rec = _tracked.get(pid)
            if rec is not None and abs(rec['create_time'] - ct) > 1.0:
                rec = None  # pid reused — re-classify from scratch
                _tracked.pop(pid, None)

            if rec is None:
                if _ignored.get(pid) == ct:
                    continue
                env = _read_env(pid)
                sid = env.get('CLAUDE_CODE_SESSION_ID', '')
                cmd = _clean_cmd(info.get('cmdline'))
                if not sid or _SELF_RE.search(' '.join(info.get('cmdline') or [])):
                    _ignored[pid] = ct
                    continue
                try:
                    cpid = int(env.get('CLAUDE_PID') or 0)
                except ValueError:
                    cpid = 0
                rec = {
                    'pid': pid,
                    'sid': sid,
                    'claude_pid': cpid,
                    'name': info.get('name') or '',
                    'cmd': cmd,
                    'kind': _kind_of(cmd),
                    'create_time': ct,
                    'proc': proc,
                    'cpu_pct': 0.0,
                    'rss_mb': 0.0,
                    'vram_mb': 0.0,
                    'peak_cpu': 0.0,
                    'peak_vram': 0.0,
                    'detached': False,
                    'announced': False,
                    'last_seen': now,
                }
                _tracked[pid] = rec
                proc.cpu_percent(None)  # prime the delta
            rec['last_seen'] = now
            seen.add(pid)

            # cpu_percent() with no interval is the delta since the previous
            # call on THIS Process object — which is why the objects are kept.
            try:
                rec['cpu_pct'] = round(proc.cpu_percent(None), 1)
                rec['rss_mb'] = round(proc.memory_info().rss / 1048576.0, 1)
            except Exception as _exc:
                _zyg_log.debug('process cpu/memory sample skipped, keeping previous values: %s', _exc)
            rec['vram_mb'] = round(_gpu_pids.get(pid, 0.0), 1)
            rec['peak_cpu'] = max(rec['peak_cpu'], rec['cpu_pct'])
            rec['peak_vram'] = max(rec['peak_vram'], rec['vram_mb'])
            rec['detached'] = _is_detached(proc, rec['claude_pid'])
            rec['elapsed'] = int(max(0, now - ct))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as _exc:
            _zyg_log.debug('process disappeared while sampling: %s', _exc)
            continue
        except Exception as _exc:
            _zyg_log.warning('unexpected failure sampling a process, skipping it: %s', _exc)
            continue

    with _lock:
        # Fold the live registry in first, so an event can find its session.
        for sid, meta in live.items():
            s = _sessions.get(sid)
            if s is None:
                s = dict(meta)
                s.update({'events': deque(maxlen=_SESS_EVENT_CAP), 'active': False, 'first_seen': _now_iso()})
                _sessions[sid] = s
                _emit(sid, 'session', f'agent session {meta["name"]} ({sid[:8]}) attached · {meta["project"]}')
            else:
                s.update({k: v for k, v in meta.items() if k != 'events'})
            s['alive'] = True
            s['orphan'] = False

        # Gone processes: report what they cost before dropping them.
        for pid in [p for p in _tracked if p not in seen]:
            rec = _tracked.pop(pid)
            if rec.get('announced'):
                dur = int(max(0, now - rec['create_time']))
                peak = ''
                if rec['peak_vram'] >= 1:
                    peak = f' · peak {_fmt_cores(rec["peak_cpu"])}, {rec["peak_vram"]:.0f} MiB VRAM'
                elif rec['peak_cpu'] >= 10:
                    peak = f' · peak {_fmt_cores(rec["peak_cpu"])}'
                _emit(
                    rec['sid'],
                    'proc_end',
                    f'{_ICONS.get(rec["kind"], "▸")} finished after {_fmt_dur(dur)}{peak} — {rec["cmd"][:160]}',
                )

        # Aggregate per session.
        agg: dict[str, dict] = {}
        for rec in _tracked.values():
            a = agg.setdefault(rec['sid'], {'cpu': 0.0, 'ram': 0.0, 'vram': 0.0, 'procs': [], 'kinds': set()})
            a['cpu'] += rec['cpu_pct']
            a['ram'] += rec['rss_mb']
            a['vram'] += rec['vram_mb']
            a['kinds'].add(rec['kind'])
            a['procs'].append(rec)

        # A process is worth announcing once it is measurably doing something —
        # not the instant it appears.  A `grep` that lives 200 ms would
        # otherwise flood the tail and bury the render it is looking for.
        for rec in _tracked.values():
            if rec['announced']:
                continue
            if not _proc_is_busy(rec):
                continue
            rec['announced'] = True
            det = ' (detached)' if rec['detached'] else ''
            load = []
            if rec['cpu_pct'] >= 10:
                load.append(_fmt_cores(rec['cpu_pct']))
            if rec['vram_mb'] >= 1:
                load.append(f'{rec["vram_mb"]:.0f} MiB VRAM')
            _emit(
                rec['sid'],
                'proc_start',
                f'{_ICONS.get(rec["kind"], "▸")} {rec["kind"]}{det} · '
                f'{", ".join(load) or "started"} — {rec["cmd"][:160]}',
                level='ok',
            )

        for sid, s in _sessions.items():
            a = agg.get(sid)
            # cpu_pct is psutil's raw "percent of ONE core" reading, kept for
            # anything that wants the raw number; cpu_cores is what every
            # surface shows, and cpu_share_pct is that as a share of the box.
            s['cpu_pct'] = round(a['cpu'], 1) if a else 0.0
            s['cpu_cores'] = round(s['cpu_pct'] / 100.0, 2)
            s['cpu_share_pct'] = round(s['cpu_pct'] / (100.0 * _NCPU) * 100.0, 1)
            # RSS, summed across the session's processes — see _RAM_ACTIVE_MB.
            s['ram_mb'] = round(a['ram'], 1) if a else 0.0
            s['ram_metric'] = 'rss'
            s['vram_mb'] = round(a['vram'], 1) if a else 0.0
            s['proc_count'] = len(a['procs']) if a else 0
            s['kinds'] = sorted(a['kinds']) if a else []
            # Busy first, then everything else: a session's tool-call shell and
            # its `sleep` are real processes but they are not the story, and a
            # render buried under them is.
            s['procs'] = (
                [
                    {k: rec[k] for k in ('pid', 'name', 'cmd', 'kind', 'cpu_pct', 'rss_mb', 'vram_mb', 'detached')}
                    | {
                        'elapsed': rec.get('elapsed', 0),
                        'busy': _proc_is_busy(rec),
                        'cpu_cores': round(rec['cpu_pct'] / 100.0, 2),
                    }
                    for rec in sorted(a['procs'], key=lambda r: (not _proc_is_busy(r), -r['vram_mb'], -r['cpu_pct']))[
                        :12
                    ]
                ]
                if a
                else []
            )
            was = s.get('active', False)
            s['active'] = bool(a) and any(_proc_is_busy(r) for r in a['procs'])
            s['reason'] = (
                'gpu'
                if s['vram_mb'] >= _VRAM_ACTIVE_MB
                else 'cpu'
                if s['cpu_pct'] >= _CPU_ACTIVE_PCT
                else 'ram'
                if s['ram_mb'] >= _RAM_ACTIVE_MB
                else ''
            )
            if s['active'] and not was:
                _load = _fmt_cores(s['cpu_pct'])
                if s['vram_mb'] >= 1:
                    _load += f', {s["vram_mb"]:.0f} MiB VRAM'
                _emit(sid, 'hw_on', f'▶ using the hardware — {_load}', level='ok')
            elif was and not s['active']:
                _emit(sid, 'hw_off', '■ hardware idle')
            s['updated'] = _now_iso()

        # Sessions whose claude process is gone but whose processes are not.
        # They still hold the card, so they are reported — just never counted
        # as an "active agent session", because nobody is driving them.
        for sid in list(_sessions):
            if sid in live:
                continue
            s = _sessions[sid]
            if s.get('proc_count'):
                if s.get('alive', True):
                    _emit(sid, 'session', f'session ended, {s["proc_count"]} process(es) left running', level='warn')
                s['alive'] = False
                s['orphan'] = True
            else:
                _sessions.pop(sid, None)

        _track_spans(now)
        _flush_open_spans(now)

        _gpu['agent_mb'] = round(sum(r['vram_mb'] for r in _tracked.values()), 1)
        _gpu['other_mb'] = round(max(0.0, _gpu['used_mb'] - _gpu['agent_mb']), 1)

        # Bound the negative cache: pids are recycled, and this must not grow
        # for the lifetime of the server.
        if len(_ignored) > 6000:
            _ignored.clear()

    _last_sample = now
    _sampler_error = ''


def _proc_is_busy(rec: dict) -> bool:
    return rec['vram_mb'] >= _VRAM_ACTIVE_MB or rec['cpu_pct'] >= _CPU_ACTIVE_PCT or rec['rss_mb'] >= _RAM_ACTIVE_MB


# ── Activity spans → ledger ─────────────────────────────────────────────────
def _session_devices(s: dict) -> dict[str, bool]:
    """Which device scopes this session is measurably on right now."""
    return {
        'gpu': (s.get('vram_mb') or 0.0) >= _VRAM_ACTIVE_MB,
        'cpu': ((s.get('cpu_pct') or 0.0) >= _CPU_ACTIVE_PCT or (s.get('ram_mb') or 0.0) >= _RAM_ACTIVE_MB),
    }


def _span_record(span: dict, end_ts: float) -> dict:
    return {
        'sid': span['sid'],
        'short': span['sid'][:8],
        'name': span.get('name') or span['sid'][:8],
        'project': span.get('project') or '',
        'cwd': span.get('cwd') or '',
        'entrypoint': span.get('entrypoint') or '',
        'session_kind': span.get('session_kind') or '',
        'device': span['device'],
        'start': _iso(span['start_ts']),
        'end': _iso(end_ts),
        'start_ts': round(span['start_ts'], 1),
        'end_ts': round(end_ts, 1),
        'duration_s': int(max(0, end_ts - span['start_ts'])),
        'peak_vram_mb': round(span.get('peak_vram', 0.0), 1),
        'peak_cpu_cores': round(span.get('peak_cpu', 0.0) / 100.0, 2),
        'peak_ram_mb': round(span.get('peak_ram', 0.0), 1),
        'kinds': sorted(span.get('kinds') or []),
        'cmds': list(span.get('cmds') or [])[:5],
        'samples': int(span.get('samples', 0)),
    }


def _ledger_append(rec: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_LEDGER_FILE), exist_ok=True)
        with open(_LEDGER_FILE, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except OSError as _exc:
        _zyg_log.warning('agent span ledger append failed, the span is not recorded: %s', _exc)


def _close_span(key: tuple, end_ts: float) -> None:
    """Called with ``_lock`` held."""
    global _open_dirty
    span = _spans.pop(key, None)
    if span is None:
        return
    _open_dirty = True
    end_ts = max(end_ts, span['start_ts'])
    if end_ts - span['start_ts'] < _SPAN_MIN_S:
        return
    rec = _span_record(span, end_ts)
    _ledger_append(rec)
    _emit(
        span['sid'],
        'span_end',
        f'⏱ {span["device"].upper()} span logged — {_fmt_dur(rec["duration_s"])}'
        + (
            f', peak {rec["peak_vram_mb"]:.0f} MiB VRAM'
            if span['device'] == 'gpu'
            else f', peak {_fmt_cores(span.get("peak_cpu", 0.0))}'
        ),
    )


def _track_spans(now: float) -> None:
    """Open/refresh/close one span per (session, device).  ``_lock`` held."""
    global _open_dirty
    for sid, s in _sessions.items():
        busy = _session_devices(s) if s.get('alive', True) else {'gpu': False, 'cpu': False}
        busy_procs = [p for p in (s.get('procs') or []) if p.get('busy')]
        for dev, on in busy.items():
            key = (sid, dev)
            span = _spans.get(key)
            if on:
                if span is None:
                    span = {
                        'sid': sid,
                        'device': dev,
                        'start_ts': now,
                        'last_busy': now,
                        'name': s.get('name'),
                        'project': s.get('project'),
                        'cwd': s.get('cwd'),
                        'entrypoint': s.get('entrypoint'),
                        'session_kind': s.get('kind'),
                        'peak_vram': 0.0,
                        'peak_cpu': 0.0,
                        'peak_ram': 0.0,
                        'kinds': set(),
                        'cmds': [],
                        'samples': 0,
                    }
                    _spans[key] = span
                    _open_dirty = True
                span['last_busy'] = now
                span['samples'] += 1
                span['peak_vram'] = max(span['peak_vram'], s.get('vram_mb') or 0.0)
                span['peak_cpu'] = max(span['peak_cpu'], s.get('cpu_pct') or 0.0)
                span['peak_ram'] = max(span['peak_ram'], s.get('ram_mb') or 0.0)
                for p in busy_procs:
                    if dev == 'gpu' and (p.get('vram_mb') or 0.0) < _VRAM_ACTIVE_MB:
                        continue
                    span['kinds'].add(p.get('kind') or 'proc')
                    cmd = (p.get('cmd') or '')[:160]
                    if cmd and cmd not in span['cmds'] and len(span['cmds']) < 5:
                        span['cmds'].append(cmd)
            elif span is not None and now - span['last_busy'] > _SPAN_GRACE_S:
                _close_span(key, span['last_busy'])
    # sessions that vanished entirely
    for key in [k for k in _spans if k[0] not in _sessions]:
        _close_span(key, _spans[key]['last_busy'])


def _flush_open_spans(now: float, force: bool = False) -> None:
    """Mirror open spans to disk (cheap; only when changed or every 30 s)."""
    global _open_flushed, _open_dirty
    if not force and not _open_dirty and now - _open_flushed < _OPEN_FLUSH_S:
        return
    _open_flushed = now
    _open_dirty = False
    out = []
    for span in _spans.values():
        rec = _span_record(span, span['last_busy'])
        rec['open'] = True
        out.append(rec)
    try:
        os.makedirs(os.path.dirname(_OPEN_SPANS_FILE), exist_ok=True)
        tmp = f'{_OPEN_SPANS_FILE}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'as_of': _iso(now), 'spans': out}, fh)
        os.replace(tmp, _OPEN_SPANS_FILE)
    except OSError as _exc:
        _zyg_log.warning('open-span snapshot write failed, crash recovery data is stale: %s', _exc)


def _recover_open_spans() -> None:
    """A previous server life left spans open: close them at their last busy
    sample so the work they measured is not lost (they cannot be resumed —
    the sampler has no continuity across a restart)."""
    try:
        with open(_OPEN_SPANS_FILE, 'r', encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return
    n = 0
    for rec in d.get('spans') or []:
        try:
            if float(rec.get('end_ts', 0)) - float(rec.get('start_ts', 0)) < _SPAN_MIN_S:
                continue
            rec = dict(rec)
            rec.pop('open', None)
            rec['recovered'] = True
            _ledger_append(rec)
            n += 1
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('skipping malformed recovered span: %s', _exc)
            continue
    _flush_open_spans(time.time(), force=True)
    if n:
        with _lock:
            _emit('', 'ledger', f'recovered {n} open agent span(s) from the previous run')


def ledger_spans(since_ts: float = 0.0, device: str = '') -> list[dict]:
    """Closed spans from the ledger (+ open ones, flagged), newest last."""
    out: list[dict] = []
    try:
        with open(_LEDGER_FILE, 'r', encoding='utf-8') as fh:
            for ln in fh:
                try:
                    rec = json.loads(ln)
                except ValueError as _exc:
                    _zyg_log.debug('skipping unparseable ledger line: %s', _exc)
                    continue
                if device and rec.get('device') != device:
                    continue
                if since_ts and float(rec.get('end_ts', 0)) < since_ts:
                    continue
                out.append(rec)
    except OSError as _exc:
        _zyg_log.warning('span ledger read failed, returning open spans only: %s', _exc)
    with _lock:
        for span in _spans.values():
            if device and span['device'] != device:
                continue
            rec = _span_record(span, span['last_busy'])
            rec['open'] = True
            out.append(rec)
    return out


def _fmt_cores(pct: float) -> str:
    """psutil per-core-percent → the unit a human reads: cores."""
    c = (pct or 0.0) / 100.0
    if c < 0.05:
        return 'idle'
    if c < 1.0:
        return f'{c:.2f} cores'
    return f'{c:.1f} core' + ('' if 0.95 <= c < 1.05 else 's')


def _fmt_dur(sec: int) -> str:
    sec = int(max(0, sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return f'{h}h {m:02d}m'
    if m:
        return f'{m}m {s:02d}s'
    return f'{s}s'


def _loop() -> None:
    global _sampler_error
    while True:
        try:
            _sample()
        except Exception as e:  # noqa: BLE001
            _sampler_error = f'{type(e).__name__}: {e}'
        time.sleep(_SAMPLE_S)


def start() -> None:
    """Start the background sampler once.  Safe to call repeatedly."""
    global _started, _thread
    with _lock:
        if _started:
            return
        _started = True
    try:
        _recover_open_spans()
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('open-span recovery failed, continuing without recovered spans: %s', _exc)
    _thread = threading.Thread(target=_loop, name='agent-activity', daemon=True)
    _thread.start()
