# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""briefing_jobs.py — job scaffolding shared by pipeline_market and pipeline_sports.

This is the pipeline_remix.py:106-232 scaffolding with `department` lifted into a
parameter. Four departments (stocks / crypto / tokitoki / arena) run the exact
same job lifecycle, so keeping four copies of it would mean four places to forget
the same fix.

Contract (same as every other pipeline module here):
  * NO top-level import of crewai_web_gui — lazy accessors only.
  * Worker thread names are LOAD-BEARING: '<dept>-<pid>' must be in the
    _workflow_pipeline_worker_alive needles tuple in crewai_web_gui.py, or the
    Kanban board stamps running jobs 'Stale after restart'.
  * data/runtime/pipeline_<pid>_state.json carries `department`, which is what
    restore-on-restart and the documentary auto-uploader dept-gate read.
"""

from __future__ import annotations

import json
import os
import re as _re
import shutil
import threading
import time
import uuid
import logging as _zyg_logging

from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.join(_CREWS, 'data', 'runtime')
_OUTPUT = os.path.join(_CREWS, 'data', 'output')

DEPARTMENTS = ('stocks', 'crypto', 'tokitoki', 'arena')


def out_root(department: str, sub: str = '') -> str:
    """Every channel gets its OWN delivery folder (operator spec). Betting
    sub-channels nest one level deeper so TokiToki-Soccer and TokiToki-MMA never
    share a folder or a retention clock."""
    parts = [_OUTPUT, department] + ([sub] if sub else [])
    return os.path.join(*parts)


def _env_f(name, default):
    try:
        return float(os.environ.get(name, str(default)) or default)
    except ValueError:
        return float(default)


def _env_i(name, default):
    try:
        return int(os.environ.get(name, str(default)) or default)
    except ValueError:
        return int(default)


# ── lazy GUI accessors ──────────────────────────────────────────────────────


def jobs():
    from zyg_workflows.runtime import workflow_jobs as _workflow_jobs

    return _workflow_jobs


def now_iso():
    try:
        from zyg_workflows.runtime import ams_iso as _ams_iso

        return _ams_iso()
    except Exception:
        return time.strftime('%Y-%m-%dT%H:%M:%S')


def marker(label, pid):
    try:
        from zyg_workflows.subproc_registry import _register_marker

        return _register_marker(label, pipeline_id=pid, status='pipeline')
    except Exception:
        return None


def marker_update(mid, status=None, label=None):
    if mid is None:
        return
    try:
        from zyg_workflows.subproc_registry import _update_marker

        _update_marker(mid, status=status, label=label)
    except Exception as _exc:
        _zyg_log.debug('subprocess marker update skipped: %s', _exc)


def _save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    except (OSError, TypeError) as _exc:
        _zyg_log.warning('atomic json write failed, the file keeps its previous contents: %s', _exc)


# ── job lifecycle ───────────────────────────────────────────────────────────


def mk_job(department: str, mode: str, directive: str, params=None, sub: str = '') -> str:
    pid = uuid.uuid4().hex[:12]
    jobs()[pid] = {
        'job_id': pid,
        'pipeline_id': pid,
        'status': 'running',
        'department': department,
        'mode': mode,
        'sub_channel': sub,
        'stop_event': threading.Event(),
        'current_stage': None,
        'started': now_iso(),
        'directive': (directive or '').strip(),
        'params': params or {},
        'stages': {},
        'stage_timeline': [],
        'debug_events': [],
        'result': None,
        'error': None,
        'output_dir': os.path.join(out_root(department, sub), pid),
    }
    return pid


def log(pid, level, stage, msg, tag='BRIEF'):
    j = jobs().get(pid)
    entry = {'ts': now_iso(), 'level': level, 'stage': stage, 'msg': str(msg)[:400]}
    if j is not None:
        j.setdefault('debug_events', []).append(entry)
        if len(j['debug_events']) > 1000:
            j['debug_events'] = j['debug_events'][-700:]
    _zyg_log.info(f'[{tag}|{level}|{stage}] {msg}')


def update_stage(pid, stage, pct=None, tag='BRIEF'):
    j = jobs().get(pid)
    if j is None:
        return
    j['current_stage'] = stage
    if pct is not None:
        j['progress_pct'] = pct
    tl = j.setdefault('stage_timeline', [])
    for e in tl:
        if e.get('status') == 'running':
            e['status'] = 'completed'
            e.setdefault('ended_at', now_iso())
    existing = next((e for e in tl if e.get('name') == stage), None)
    if existing is not None:
        existing['status'] = 'running'
    else:
        tl.append({'name': stage, 'status': 'running', 'started_at': now_iso()})
    log(pid, 'INFO', stage, f'▶ {stage}', tag=tag)
    save_state(pid)


def finish(pid, ok, result=None, error=None):
    j = jobs().get(pid)
    if j is None:
        return
    for e in j.get('stage_timeline') or []:
        if e.get('status') == 'running':
            e['status'] = 'completed' if ok else 'failed'
            e.setdefault('ended_at', now_iso())
    j['status'] = 'completed' if ok else 'failed'
    j['ended'] = now_iso()
    j['current_stage'] = None
    j['result'] = result
    j['error'] = error
    save_state(pid)


def save_state(pid):
    j = jobs().get(pid)
    if j is None:
        return
    state = {k: v for k, v in j.items() if k != 'stop_event'}
    _save_json(os.path.join(_RUNTIME, f'pipeline_{pid}_state.json'), state)


class Stopped(Exception):
    pass


def stopped(pid) -> bool:
    j = jobs().get(pid) or {}
    ev = j.get('stop_event')
    if ev is not None and ev.is_set():
        return True
    try:
        from zyg_workflows import gui_state

        if getattr(gui_state, '_pipeline_stop_flag', False):
            return True
    except Exception as _exc:
        _zyg_log.debug('gui_state stop-flag probe unavailable: %s', _exc)
    try:
        from zyg_workflows import pipeline_control as _pc

        if _pc.halt_requested():
            return True
    except Exception as _exc:
        _zyg_log.debug('pipeline_control halt probe unavailable: %s', _exc)
    return False


def check_stop(pid):
    if stopped(pid):
        raise Stopped('Pipeline stopped by user')


def pipeline_busy() -> bool:
    try:
        return any(j.get('status') == 'running' for j in jobs().values())
    except Exception:
        return False


# ── disk gate (fail closed, same shape as pipeline_remix.disk_ok) ───────────


def tree_gb(root) -> float:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError as _exc:
                _zyg_log.debug('disk-usage scan skipped a file: %s', _exc)
    return total / 1e9


def disk_ok(department: str) -> 'tuple[bool, str]':
    free_gb = shutil.disk_usage('/').free / 1e9
    min_free = _env_f('ZYG_BRIEF_MIN_FREE_GB', 60)
    if free_gb < min_free:
        return False, f'free disk {free_gb:.0f} GB < floor {min_free:.0f} GB'
    max_gb = _env_f('ZYG_BRIEF_MAX_GB', 60)
    used = tree_gb(out_root(department))
    if used > max_gb:
        return False, f'{department} tree {used:.0f} GB > cap {max_gb:.0f} GB'
    return True, f'free {free_gb:.0f} GB, {department} tree {used:.1f} GB'


# ── local LLM (script writing only — never arithmetic) ──────────────────────

_OLLAMA = os.environ.get('OLLAMA_HOST_URL', paths.ZYG_OLLAMA_URL)


def llm_model() -> str:
    # qwen3.5:9b, not gpt-oss:20b: format:'json' returns an EMPTY response on
    # gpt-oss (harmony channels vs the format grammar, verified ollama 0.17.7);
    # murch_engine picked the same model for the same strict-JSON task shape.
    return os.environ.get('ZYG_BRIEF_LLM_MODEL', 'qwen3.5:9b')


def gpu_clear(min_free_gb: float) -> bool:
    """Never squeeze a render. Absence of nvidia-smi is treated as 'fine'."""
    try:
        import subprocess

        r = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=20,
        )
        free = min(float(x) for x in r.stdout.strip().splitlines() if x.strip())
        return (free / 1024.0) >= min_free_gb
    except Exception:
        return True


def ollama_json(prompt, timeout=240, num_predict=900, temperature=0.35):
    if not gpu_clear(9.0):
        return None
    from zyg_workflows.net import safe_urlopen

    try:
        with safe_urlopen(f'{_OLLAMA}/api/version', timeout=3):
            pass
    except Exception:
        return None
    model = llm_model()
    payload = json.dumps(
        {
            'model': model,
            'prompt': prompt,
            'stream': False,
            'format': 'json',
            'keep_alive': '2m',
            # qwen3.x are thinking models: without think=False the reasoning eats
            # num_predict and 'response' comes back empty; non-thinking models 500
            # on the think key, so it is added conditionally (2026-08-09 roster rule).
            **({'think': False} if model.startswith('qwen3') else {}),
            'options': {'temperature': temperature, 'num_predict': num_predict, 'num_ctx': 8192},
        }
    ).encode()
    try:
        from zyg_workflows import llm_audit as _la_bj

        _data = _la_bj.ollama_post(f'{_OLLAMA}/api/generate', json.loads(payload), timeout=timeout, stage='briefing')
        # thinking models can route output into 'thinking' even with
        # think:false (murch_engine._ollama_response_text pattern)
        raw = (_data.get('response') or '').strip() or (_data.get('thinking') or '')
        raw = raw.strip().strip('`')
        return json.loads(raw[raw.find('{') : raw.rfind('}') + 1])
    except Exception:
        return None


def ollama_release():
    import urllib.request as _ur
    from urllib.parse import urlsplit as _urlsplit

    try:
        # OLLAMA_HOST_URL is read from the environment, so its scheme is checked before the open;
        # a Request is needed here for the POST method and header, so safe_urlopen cannot carry it.
        if _urlsplit(_OLLAMA).scheme not in ('http', 'https'):
            raise ValueError(f'OLLAMA_HOST_URL must be http(s), got {_OLLAMA!r}')
        payload = json.dumps({'model': llm_model(), 'prompt': '', 'keep_alive': 0}).encode()
        req = _ur.Request(  # noqa: S310  scheme checked three lines above
            f'{_OLLAMA}/api/generate', data=payload, headers={'Content-Type': 'application/json'}, method='POST'
        )
        with _ur.urlopen(req, timeout=15):  # nosec B310  # noqa: S310  req holds the checked URL
            pass
    except Exception as _exc:
        _zyg_log.debug('ollama keep-alive release failed: %s', _exc)


# ── number-safety guard ─────────────────────────────────────────────────────


_NUM_RE = _re.compile(r'-?\d[\d,]*\.?\d*')


def numbers_in(text: str) -> set:
    """Every numeric token in a string, normalised for comparison."""
    out = set()
    for m in _NUM_RE.findall(text or ''):
        t = m.replace(',', '').rstrip('.')
        if not t or t in ('-',):
            continue
        try:
            out.add(f'{float(t):g}')
        except ValueError as _exc:
            _zyg_log.debug('non-numeric token skipped: %s', _exc)
            continue
    return out


def llm_invented_numbers(written: str, allowed_sources: list) -> set:
    """Numbers the model put on air that were not in the measured facts.

    The LLM is only ever asked to rephrase a driver list that was computed from
    the bars/odds. If it emits a price target or a percentage that appears in
    none of the source strings, that is a hallucinated figure on a finance or
    betting channel — the caller drops the written copy and speaks the measured
    facts verbatim instead. Small integers (1-31, dates, counts, list positions)
    are ignored, they are ordinary prose.
    """
    allowed = set()
    for s in allowed_sources or []:
        allowed |= numbers_in(s)
    bad = set()
    for n in numbers_in(written):
        if n in allowed:
            continue
        try:
            v = abs(float(n))
        except ValueError as _exc:
            _zyg_log.debug('non-numeric token skipped: %s', _exc)
            continue
        if v <= 31 and float(n).is_integer():
            continue
        bad.add(n)
    return bad


# ── claim-safety guard ──────────────────────────────────────────────────────
# The number guard alone shipped the 2026-08-08 TokiToki episode with "In the
# last 5 matches, Grêmio has drawn 2 times, while São Paulo has drawn 3" — pure
# fabrication, waved through because every integer was ≤ 31 — plus form claims
# ("recent performances", "solid defense") on all seven chapters that no data
# source ever measured. The LLM only ever receives odds-derived FACTS: any
# sentence about form, history, injuries or team quality is invented by
# construction, unless the same topic genuinely appears in the facts.

_CLAIM_PATTERNS = (
    (
        'injury',
        _re.compile(
            r'\b(injur\w+|suspend\w+|sidelined|ruled out|missing (?:key |several )?'
            r'(?:players|starters|men)|without their)\b',
            _re.I,
        ),
    ),
    (
        'form',
        _re.compile(
            r'\b(recent (?:form|matches|games|performances?|results)|current form|'
            r'in[- ]form|out of form|momentum|(?:winning|losing|unbeaten) (?:streak|run)|'
            r'last \d+ (?:matches|games)|has (?:won|drawn|lost|scored|conceded)|'
            r'building form|been performing|performing well)\b',
            _re.I,
        ),
    ),
    (
        'history',
        _re.compile(
            r'\b(head[- ]to[- ]head|h2h|historically|history suggests|'
            r'often surprises?|history between)\b',
            _re.I,
        ),
    ),
    ('invented-count', _re.compile(r'\b\d+\s+(?:times|matches|games|goals|wins|losses|draws|clean sheets)\b', _re.I)),
    (
        'team-quality',
        _re.compile(
            r'\b(?:solid|strong|leaky|shaky|weak|formidable) '
            r'(?:defen[cs]e|defending|attack|midfield|backline)|'
            r'tactical (?:discipline|adaptability|flexibility)|resilien\w+\b',
            _re.I,
        ),
    ),
)


def unsupported_claims(written: str, allowed_sources: list) -> list:
    """Claim categories the model asserted that appear in none of the facts.

    A category is only flagged when the written copy matches it AND no source
    fact matches it — so the day a real injury feed or form feed lands in the
    facts, mentioning it stays legal without touching this guard.
    """
    hay = ' '.join(s for s in (allowed_sources or []) if s)
    out = []
    for label, pat in _CLAIM_PATTERNS:
        m = pat.search(written or '')
        if m and not pat.search(hay):
            out.append(f'{label}: "{m.group(0)[:60]}"')
    return out
