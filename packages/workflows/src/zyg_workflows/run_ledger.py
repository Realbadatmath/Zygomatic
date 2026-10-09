# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run_ledger.py — silent-degrade ledger, execution provenance, cross-run gate ledger.

2026-07-30. Born from the recurring "it shipped degraded for an unknown number of
runs" class of incident:

  * audio_mix.loudnorm_two_pass silently got ffmpeg's DYNAMIC AGC instead of the
    linear gain the chain promises (pause-pumping) — the caller had a verified
    'normalization_type' and nobody was writing it down.
  * zyg_whisper degrades cuda:large-v3 → cpu:base + greedy on VRAM pressure; the
    only trace was a stderr WARNING nobody diffed across runs.
  * 2026-07-26 Juggernaut→DynaVision checkpoint-pin clobber produced off-model
    characters; the run logs "looked fine".
  * the ghost-face audit found 17/49 defective cells trained into LoRAs while
    every individual per-run gate PASSED — no single run was alarming, the
    cross-run pass-rate was.

So this module is three ledgers in one Postgres database (via pgdb):

    stages     what ACTUALLY executed per stage (device / model_id /
               weights_sha256 / dtype / fallback_taken / wall_s / vram_peak_mb)
    fallbacks  every silent degrade, recorded at the site that degraded
    gates      every QC gate outcome of every run, so drift is queryable

Usage (all calls are fail-safe — a broken ledger must NEVER break generation):

    from zyg_workflows import run_ledger
    run_ledger.record_fallback('loudnorm', 'linear', 'dynamic', detail='...')
    run_ledger.record_gate(run_id, 'motion:abel', 'fail', score=0.07, tag='frozen-motion')
    run_ledger.record_stage('wan_render', device='cuda:0', model_id='wan2.1-vace-14b',
                            weights_sha256=run_ledger.sha256_file(ckpt), wall_s=5321.0)
    print(run_ledger.trends(days=14))

    python3 run_ledger.py --trends [--days 14]

run_id resolution everywhere: explicit arg → env ZYG_RUN_ID → 'adhoc'.  DebugRun
(pipeline_debug.py) exports ZYG_RUN_ID for the duration of a run, which is what
lets a record_fallback() call buried in audio_mix/zyg_whisper land in the right
run's 'degradations' manifest section without any signature plumbing.

Thread-safety: Postgres via the pgdb pool; one pooled connection per operation;
schema owned by alembic/.
"""

from __future__ import annotations

import json
import os
from zyg_workflows import pgdb
import sys
import threading
import time
from zyg_workflows.bin import exe
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.join(_CREWS, 'data', 'runtime')
_SHA_CACHE_PATH = os.environ.get('ZYG_SHA_CACHE') or os.path.join(_RUNTIME, 'sha256_cache.json')

_LOCK = threading.Lock()  # guards the sha256 cache file only


# ── plumbing ─────────────────────────────────────────────────────────────────


def db_path() -> str:
    """Active DSN (env ZYG_PG_DSN or pgdb.DEFAULT_DSN); was the sqlite path before 2026-10-02."""
    return pgdb.dsn()


def current_run_id(run_id=None) -> str:
    """Pinned contract: explicit → env ZYG_RUN_ID → 'adhoc'."""
    return str(run_id or os.environ.get('ZYG_RUN_ID') or 'adhoc')


def _insert(sql, args, log_fn=None) -> bool:
    """Fail-safe insert: True on success, False (logged) on any failure."""
    try:
        with pgdb.connect() as conn:
            conn.execute(sql, args)
        return True
    except Exception as e:  # never raise upward
        if log_fn:
            log_fn(f'[run_ledger] write failed (ignored): {e}')
        return False


def _now():
    t = time.time()
    return t, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))


def _num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ── recording API (pinned cross-module contract) ─────────────────────────────


def record_fallback(component, expected, actual, detail='', run_id=None, log_fn=None) -> bool:
    """Record ONE silent degrade at the site that degraded.

    component : 'loudnorm' | 'whisper' | 'indextts2' | 'sortformer' | 'handfixer' | ...
    expected  : what the config/contract promised ('linear', 'cuda:large-v3')
    actual    : what actually ran ('dynamic', 'cpu:base')
    detail    : free text (measured values, exception text, thresholds)
    run_id    : None → env ZYG_RUN_ID → 'adhoc'
    """
    ts, iso = _now()
    return _insert(
        'INSERT INTO fallbacks (component, expected, actual, detail, run_id, ts, ts_iso) VALUES (%s,%s,%s,%s,%s,%s,%s)',
        (
            str(component)[:80],
            str(expected)[:200],
            str(actual)[:200],
            str(detail or '')[:1000],
            current_run_id(run_id),
            ts,
            iso,
        ),
        log_fn,
    )


def record_gate(run_id, gate, outcome, score=None, tag='', log_fn=None) -> bool:
    """Record ONE QC gate outcome. outcome is normalized to 'pass'/'fail'/<other>.

    Booleans are accepted for convenience (True → 'pass')."""
    if outcome is True:
        outcome = 'pass'
    elif outcome is False:
        outcome = 'fail'
    ts, iso = _now()
    return _insert(
        'INSERT INTO gates (run_id, gate, outcome, score, tag, ts, ts_iso) VALUES (%s,%s,%s,%s,%s,%s,%s)',
        (current_run_id(run_id), str(gate)[:160], str(outcome).lower()[:16], _num(score), str(tag or '')[:80], ts, iso),
        log_fn,
    )


def record_stage(
    stage,
    run_id=None,
    device=None,
    model_id=None,
    weights_sha256=None,
    dtype=None,
    fallback_taken=None,
    wall_s=None,
    vram_peak_mb=None,
    log_fn=None,
) -> bool:
    """Record what a stage ACTUALLY executed with (execution provenance).

    fallback_taken: short marker string (or None). wall_s / vram_peak_mb are the
    cheap anomaly fingerprints — a stage that suddenly runs 6x slower at 1/3 the
    VRAM ran on the CPU path."""
    ts, iso = _now()
    return _insert(
        'INSERT INTO stages (run_id, stage, device, model_id, weights_sha256, dtype,'
        ' fallback_taken, wall_s, vram_peak_mb, ts, ts_iso) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (
            current_run_id(run_id),
            str(stage)[:120],
            None if device is None else str(device)[:60],
            None if model_id is None else str(model_id)[:200],
            None if weights_sha256 is None else str(weights_sha256)[:64],
            None if dtype is None else str(dtype)[:40],
            None if fallback_taken is None else str(fallback_taken)[:200],
            _num(wall_s),
            _num(vram_peak_mb),
            ts,
            iso,
        ),
        log_fn,
    )


# ── weight attestation ───────────────────────────────────────────────────────

_sha_cache = None


def _load_sha_cache():
    global _sha_cache
    if _sha_cache is None:
        try:
            with open(_SHA_CACHE_PATH, encoding='utf-8') as f:
                _sha_cache = json.load(f)
            if not isinstance(_sha_cache, dict):
                _sha_cache = {}
        except Exception:
            _sha_cache = {}
    return _sha_cache


def _save_sha_cache():
    try:
        os.makedirs(os.path.dirname(_SHA_CACHE_PATH), exist_ok=True)
        tmp = _SHA_CACHE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_sha_cache, f, indent=1)
        os.replace(tmp, _SHA_CACHE_PATH)
    except Exception as _exc:
        _zyg_log.debug('sha cache write skipped, hashes will be recomputed: %s', _exc)


def sha256_file(path, log_fn=None):
    """SHA256 of a file, cached on (size, mtime_ns) in a JSON sidecar.

    Hashing a 6GB checkpoint is seconds ONCE; every later run is a stat() away.
    The cache key includes size and mtime_ns, so an in-place clobber (the
    2026-07-26 checkpoint-pin incident shape) invalidates it automatically.
    Returns the hex digest, or None if the file is unreadable (fail-safe)."""
    try:
        import hashlib

        p = os.path.abspath(str(path))
        st = os.stat(p)
        key = p
        cache = _load_sha_cache()
        hit = cache.get(key)
        if (
            isinstance(hit, dict)
            and hit.get('size') == st.st_size
            and hit.get('mtime_ns') == st.st_mtime_ns
            and hit.get('sha256')
        ):
            return hit['sha256']
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
                h.update(chunk)
        digest = h.hexdigest()
        with _LOCK:
            cache[key] = {
                'size': st.st_size,
                'mtime_ns': st.st_mtime_ns,
                'sha256': digest,
                'hashed': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            _save_sha_cache()
        return digest
    except Exception as e:
        if log_fn:
            log_fn(f'[run_ledger] sha256_file({path}) failed (ignored): {e}')
        return None


# ── NVML (replaces the nvidia-smi shell-out; nvidia-ml-py, BSD) ──────────────

_nvml_state = {'mod': None, 'init': False, 'dead': False}


def _nvml():
    """Lazy NVML handle. Read-only driver queries — creates NO CUDA context and
    allocates NO VRAM, so it is safe to call while a render owns the GPU."""
    if _nvml_state['dead']:
        return None
    if _nvml_state['mod'] is None:
        try:
            import warnings

            with warnings.catch_warnings():
                # the deprecated `pynvml` shim redirects to nvidia-ml-py and warns
                warnings.simplefilter('ignore')
                import pynvml
            _nvml_state['mod'] = pynvml
        except Exception:
            _nvml_state['dead'] = True
            return None
    if not _nvml_state['init']:
        try:
            _nvml_state['mod'].nvmlInit()
            _nvml_state['init'] = True
            import atexit

            atexit.register(_nvml_shutdown)
        except Exception:
            _nvml_state['dead'] = True
            return None
    return _nvml_state['mod']


def _nvml_shutdown():
    try:
        if _nvml_state['init'] and _nvml_state['mod'] is not None:
            _nvml_state['mod'].nvmlShutdown()
            _nvml_state['init'] = False
    except Exception as _exc:
        _zyg_log.debug('nvml shutdown skipped: %s', _exc)


def _s(v):
    return v.decode('utf-8', 'replace') if isinstance(v, (bytes, bytearray)) else str(v)


def gpu_info():
    """{'source','driver','name','count','vram_used_mb','vram_total_mb','vram_free_mb'}
    via NVML, with a graceful nvidia-smi shell fallback and a final empty dict.
    Never raises."""
    nv = _nvml()
    if nv is not None:
        try:
            n = int(nv.nvmlDeviceGetCount())
            h = nv.nvmlDeviceGetHandleByIndex(0)
            mi = nv.nvmlDeviceGetMemoryInfo(h)
            return {
                'source': 'nvml',
                'driver': _s(nv.nvmlSystemGetDriverVersion()),
                'name': _s(nv.nvmlDeviceGetName(h)),
                'count': n,
                'vram_total_mb': int(mi.total // 1048576),
                'vram_used_mb': int(mi.used // 1048576),
                'vram_free_mb': int(mi.free // 1048576),
            }
        except Exception:
            _nvml_state['dead'] = True
    try:  # graceful fallback
        import subprocess

        r = subprocess.run(
            [
                exe('nvidia-smi'),
                '--query-gpu=driver_version,name,memory.total,memory.used',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        parts = [p.strip() for p in (r.stdout.strip().splitlines() or [''])[0].split(',')]
        if len(parts) >= 4:
            return {
                'source': 'nvidia-smi',
                'driver': parts[0],
                'name': parts[1],
                'count': len(r.stdout.strip().splitlines()),
                'vram_total_mb': int(float(parts[2])),
                'vram_used_mb': int(float(parts[3])),
                'vram_free_mb': int(float(parts[2])) - int(float(parts[3])),
            }
    except Exception as _exc:
        _zyg_log.warning('nvidia-smi gpu probe failed, continuing without gpu info: %s', _exc)
    return {'source': None}


def vram_used_mb():
    """Current device-0 VRAM usage in MB, or None. Microseconds via NVML."""
    v = gpu_info().get('vram_used_mb')
    return None if v is None else int(v)


# ── reads ────────────────────────────────────────────────────────────────────


def _rows(sql, args=()):
    try:
        return pgdb.rows(sql, args)
    except Exception:
        return []


def fallbacks_for_run(run_id=None):
    """Every silent degrade recorded under this run_id (oldest first).
    This is what pipeline_debug turns into the manifest's 'degradations' section."""
    return _rows(
        'SELECT component, expected, actual, detail, run_id, ts_iso FROM fallbacks WHERE run_id = %s ORDER BY id',
        (current_run_id(run_id),),
    )


def gates_for_run(run_id=None):
    return _rows(
        'SELECT gate, outcome, score, tag, ts_iso FROM gates WHERE run_id = %s ORDER BY id', (current_run_id(run_id),)
    )


def stages_for_run(run_id=None):
    return _rows(
        'SELECT stage, device, model_id, weights_sha256, dtype, fallback_taken,'
        ' wall_s, vram_peak_mb, ts_iso FROM stages WHERE run_id = %s ORDER BY id',
        (current_run_id(run_id),),
    )


# ── two-run reads (2026-08-01, for run_logbook.compare_runs) ─────────────────
#
# trends() answers "is the fleet drifting?".  The v11→v12 postmortem needed the other
# question — "what did THESE TWO runs do differently?" — and there was no read for it,
# so the answer was reconstructed by hand over a day.  These three are that read.


def known_runs(limit=50):
    """Most-recent-first run_ids seen in ANY table, with their span and row counts.
    The cheap 'which runs do I even have?' lookup that precedes any comparison."""
    rows = _rows(
        'SELECT run_id, MIN(ts) AS t0, MAX(ts) AS t1, COUNT(*) AS n, MAX(ts_iso) AS last_iso'
        ' FROM (SELECT run_id, ts, ts_iso FROM stages'
        '       UNION ALL SELECT run_id, ts, ts_iso FROM gates'
        '       UNION ALL SELECT run_id, ts, ts_iso FROM fallbacks) AS u'
        ' GROUP BY run_id ORDER BY t1 DESC LIMIT %s',
        (int(max(1, limit)),),
    )
    for r in rows:
        r['wall_s'] = round((r.get('t1') or 0) - (r.get('t0') or 0), 1)
    return rows


def gate_scores_for_run(run_id=None):
    """{gate: {'outcome','score','tag','ts_iso'}} — LAST outcome wins when a gate was
    recorded more than once in a run (a re-run of the gate supersedes its earlier try)."""
    out = {}
    for r in _rows(
        'SELECT gate, outcome, score, tag, ts_iso FROM gates WHERE run_id = %s ORDER BY id', (current_run_id(run_id),)
    ):
        out[r['gate']] = {'outcome': r['outcome'], 'score': r['score'], 'tag': r['tag'], 'ts_iso': r['ts_iso']}
    return out


def compare_gates(run_a, run_b):
    """Gate-level delta between two runs: what flipped, what only one of them ran.

    Returns {'a','b','changed':[{gate,a_outcome,b_outcome,a_score,b_score,flip,delta}],
             'a_only':[...], 'b_only':[...], 'regressions':[...]}.
    'regressions' is the subset that went pass → fail — the list to read first.
    Fail-safe: an unreadable ledger yields empty lists, never an exception."""
    try:
        ga, gb = gate_scores_for_run(run_a), gate_scores_for_run(run_b)
        changed, regressions = [], []
        for gate in sorted(set(ga) & set(gb)):
            a, b = ga[gate], gb[gate]
            if a['outcome'] == b['outcome'] and a['score'] == b['score']:
                continue
            flip = ''
            if a['outcome'] != b['outcome']:
                flip = f'{a["outcome"]}->{b["outcome"]}'
            d = None
            if a['score'] is not None and b['score'] is not None:
                d = round(b['score'] - a['score'], 6)
            rec = {
                'gate': gate,
                'a_outcome': a['outcome'],
                'b_outcome': b['outcome'],
                'a_score': a['score'],
                'b_score': b['score'],
                'flip': flip,
                'delta': d,
            }
            changed.append(rec)
            if a['outcome'] == 'pass' and b['outcome'] == 'fail':
                regressions.append(rec)
        return {
            'a': current_run_id(run_a),
            'b': current_run_id(run_b),
            'changed': changed,
            'regressions': regressions,
            'a_only': sorted(set(ga) - set(gb)),
            'b_only': sorted(set(gb) - set(ga)),
        }
    except Exception as e:
        return {
            'a': str(run_a),
            'b': str(run_b),
            'changed': [],
            'regressions': [],
            'a_only': [],
            'b_only': [],
            'error': str(e)[:200],
        }


# ── trends ───────────────────────────────────────────────────────────────────

_Z_FLAG = 2.0  # |z| >= 2.0 ≈ p<0.05 two-sided
_MIN_N = 5  # per half-window; below this a "shift" is noise


def _two_prop_z(k1, n1, k2, n2):
    """z of (recent pass rate) − (prior pass rate); None when underpowered."""
    if n1 < _MIN_N or n2 < _MIN_N:
        return None
    import math

    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se <= 1e-12:
        return None
    return (p1 - p2) / se


def trends(days=14):
    """Cross-run rolling view — the thing no single run can see.

    Returns {'ok', 'days', 'db', 'runs', 'gates': [...], 'tags': [...],
             'fallbacks': [...], 'alerts': [...]}.

    Per gate: n / pass_rate over the window, the same split into a RECENT half
    and a PRIOR half, a two-proportion z of the difference, and a 'shift' flag
    ('drop'/'rise') when |z| >= 2.0 with >= 5 samples each side — the
    ghost-face pattern (every run individually fine, the rate quietly sliding).
    Fail-safe: any error returns {'ok': False, 'error': ...}."""
    try:
        days = max(1, int(days))
        now = time.time()
        cutoff = now - days * 86400.0
        mid = now - (days / 2.0) * 86400.0

        g = _rows(
            'SELECT run_id, gate, outcome, tag, score, ts, ts_iso FROM gates WHERE ts >= %s ORDER BY ts', (cutoff,)
        )
        per = {}
        daily = {}
        tag_counts = {}
        for r in g:
            gate = r['gate']
            outcome = (r['outcome'] or '').lower()
            if outcome not in ('pass', 'fail'):
                continue
            d = per.setdefault(
                gate, {'n': 0, 'k': 0, 'rn': 0, 'rk': 0, 'pn': 0, 'pk': 0, 'scores': [], 'last': r['ts_iso']}
            )
            d['n'] += 1
            d['last'] = r['ts_iso']
            hit = 1 if outcome == 'pass' else 0
            d['k'] += hit
            if r['ts'] >= mid:
                d['rn'] += 1
                d['rk'] += hit
            else:
                d['pn'] += 1
                d['pk'] += hit
            if r['score'] is not None:
                d['scores'].append(float(r['score']))
            day = (r['ts_iso'] or '')[:10]
            dd = daily.setdefault(gate, {}).setdefault(day, [0, 0])
            dd[0] += 1
            dd[1] += hit
            if hit == 0 and (r['tag'] or ''):
                t = tag_counts.setdefault(r['tag'], {'tag': r['tag'], 'count': 0, 'runs': set()})
                t['count'] += 1
                t['runs'].add(r['run_id'])

        gates_out, alerts = [], []
        for gate, d in sorted(per.items()):
            z = _two_prop_z(d['rk'], d['rn'], d['pk'], d['pn'])
            shift = None
            if z is not None and abs(z) >= _Z_FLAG:
                shift = 'drop' if z < 0 else 'rise'
            rec = {
                'gate': gate,
                'n': d['n'],
                'passed': d['k'],
                'pass_rate': round(d['k'] / d['n'], 3) if d['n'] else None,
                'recent_n': d['rn'],
                'recent_pass_rate': round(d['rk'] / d['rn'], 3) if d['rn'] else None,
                'prior_n': d['pn'],
                'prior_pass_rate': round(d['pk'] / d['pn'], 3) if d['pn'] else None,
                'z': None if z is None else round(z, 2),
                'shift': shift,
                'mean_score': (round(sum(d['scores']) / len(d['scores']), 3) if d['scores'] else None),
                'last_seen': d['last'],
                'daily': [{'day': k, 'n': v[0], 'passed': v[1]} for k, v in sorted(daily.get(gate, {}).items())],
            }
            gates_out.append(rec)
            if shift == 'drop':
                alerts.append(
                    f"gate '{gate}' pass-rate {rec['prior_pass_rate']} → "
                    f'{rec["recent_pass_rate"]} (z={rec["z"]}, n={d["pn"]}/{d["rn"]}) — '
                    f'REGRESSION'
                )
            elif shift == 'rise':
                alerts.append(
                    f"gate '{gate}' pass-rate {rec['prior_pass_rate']} → "
                    f'{rec["recent_pass_rate"]} (z={rec["z"]}) — improved (confirm it was intended)'
                )

        fb = _rows(
            'SELECT component, expected, actual, run_id, ts_iso FROM fallbacks WHERE ts >= %s ORDER BY ts', (cutoff,)
        )
        fmap = {}
        for r in fb:
            k = (r['component'], r['expected'], r['actual'])
            e = fmap.setdefault(
                k,
                {
                    'component': r['component'],
                    'expected': r['expected'],
                    'actual': r['actual'],
                    'count': 0,
                    'runs': set(),
                    'last_seen': r['ts_iso'],
                },
            )
            e['count'] += 1
            e['runs'].add(r['run_id'])
            e['last_seen'] = r['ts_iso']
        fallbacks_out = sorted(({**v, 'runs': len(v['runs'])} for v in fmap.values()), key=lambda x: -x['count'])
        for f in fallbacks_out:
            alerts.append(
                f"silent degrade '{f['component']}': expected {f['expected']} "
                f'→ got {f["actual"]} in {f["runs"]} run(s), {f["count"]}x '
                f'(last {f["last_seen"]})'
            )

        tags_out = sorted(
            ({'tag': v['tag'], 'count': v['count'], 'runs': len(v['runs'])} for v in tag_counts.values()),
            key=lambda x: -x['count'],
        )

        run_ids = {r['run_id'] for r in g} | {r['run_id'] for r in fb}
        run_ids |= {r['run_id'] for r in _rows('SELECT DISTINCT run_id FROM stages WHERE ts >= %s', (cutoff,))}
        return {
            'ok': True,
            'days': days,
            'db': db_path(),
            'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
            'runs': len(run_ids),
            'gates': gates_out,
            'tags': tags_out,
            'fallbacks': fallbacks_out,
            'alerts': alerts,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300], 'days': days, 'db': db_path()}


def format_trends(t=None, days=14):
    """Readable fixed-width table of trends() — used by --trends and pasteable
    into a report."""
    t = t or trends(days)
    if not t.get('ok'):
        return f'run_ledger trends FAILED: {t.get("error")}'
    L = [f'run ledger — last {t["days"]}d   db={t["db"]}', f'generated {t["generated"]}   runs={t["runs"]}', '']
    hdr = f'{"gate":<34}{"n":>5}{"pass%":>8}{"prior%":>9}{"recent%":>9}{"z":>7}  flag'
    L += ['GATES', hdr, '-' * len(hdr)]
    if not t['gates']:
        L.append('  (no gate rows in window)')

    def _pct(v):
        return '   -  ' if v is None else '%5.1f%%' % (v * 100)

    for g in t['gates']:
        zs = '   -  ' if g['z'] is None else '%+.2f' % g['z']
        L.append(
            f'{g["gate"][:34]:<34}{g["n"]:>5}{_pct(g["pass_rate"]):>8}'
            f'{_pct(g["prior_pass_rate"]):>9}{_pct(g["recent_pass_rate"]):>9}'
            f'{zs:>7}  {g["shift"] or ""}'
        )
    L += ['', 'RECURRING FAILURE TAGS']
    if not t['tags']:
        L.append('  (none)')
    for x in t['tags']:
        L.append(f'  {x["tag"]:<24} {x["count"]:>4} failure(s) across {x["runs"]} run(s)')
    L += ['', 'SILENT DEGRADES (fallbacks)']
    if not t['fallbacks']:
        L.append('  (none)')
    for f in t['fallbacks']:
        L.append(
            f'  {f["component"]:<14} {f["expected"]:<20} -> {f["actual"]:<20}'
            f' {f["count"]:>4}x / {f["runs"]} run(s)  last {f["last_seen"]}'
        )
    L += ['', 'ALERTS']
    if not t['alerts']:
        L.append('  (none)')
    for a in t['alerts']:
        L.append(f'  ! {a}')
    return '\n'.join(L)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _main(argv):
    days = 14
    if '--days' in argv:
        try:
            days = int(argv[argv.index('--days') + 1])
        except (IndexError, ValueError) as _exc:
            _zyg_log.warning('--days value unusable, keeping %s: %s', days, _exc)
    if '--trends' in argv:
        print(format_trends(days=days))
        return 0
    if '--json' in argv:
        print(json.dumps(trends(days), indent=1))
        return 0
    if '--gpu' in argv:
        print(json.dumps(gpu_info(), indent=1))
        return 0
    if '--run' in argv:
        rid = argv[argv.index('--run') + 1]
        print(
            json.dumps(
                {'stages': stages_for_run(rid), 'gates': gates_for_run(rid), 'degradations': fallbacks_for_run(rid)},
                indent=1,
            )
        )
        return 0
    if '--runs' in argv:
        print(json.dumps(known_runs(), indent=1))
        return 0
    if '--compare' in argv:
        i = argv.index('--compare')
        if len(argv) < i + 3:
            print('usage: python3 run_ledger.py --compare <run_a> <run_b>')
            return 2
        print(json.dumps(compare_gates(argv[i + 1], argv[i + 2]), indent=1))
        return 0
    print(__doc__.strip().splitlines()[0])
    print(
        'usage: python3 run_ledger.py --trends [--days N] | --json | --gpu | '
        '--run <run_id> | --runs | --compare <a> <b>'
    )
    return 1


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
