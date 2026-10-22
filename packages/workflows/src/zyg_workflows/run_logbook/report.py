# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""report — a verbatim section of the pre-split run_logbook.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

from __future__ import annotations

import json  # noqa: F401
import logging as _zyg_logging  # noqa: F401
import os  # noqa: F401
import sys  # noqa: F401

from zyg_workflows.run_logbook.plumbing import (  # noqa: F401
    KNOWN_ZYG_KEYS,
    LOGBOOK_DIR,
    LOGBOOK_NAME,
    _CREWS,
    _atomic_write,
    _handle,
    _log_noop,
    _now,
    _read_json,
    _read_jsonl,
    resolve_run,
)
from zyg_workflows.run_logbook.recording import (  # noqa: F401
    finish_run,
    record_config,
    record_gates,
    record_metrics,
    record_stage,
    start_run,
)
from zyg_workflows.run_logbook.reading import (  # noqa: F401
    list_runs,
    load_run,
    record_checkpoint,
    resume_from,
)
from zyg_workflows.run_logbook.compare import (  # noqa: F401
    _cell,
    compare_runs,
    flatten,
    format_compare,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.run_logbook')


# ── human-readable LOGBOOK.md ────────────────────────────────────────────────


def write_logbook_md(run, log_fn=None) -> str:
    """Regenerate <run_dir>/LOGBOOK.md from the jsonl. Rendering, not state — safe to
    delete, safe to rebuild, never the source of truth."""
    log = log_fn or _log_noop
    try:
        h = _handle(run)
        if not h.get('run_dir') or not os.path.isdir(h['run_dir']):
            return ''
        v = load_run(h)
        cfg = v.get('config') or {}
        L = [
            f'# LOGBOOK — {v["run_key"]}',
            '',
            f'- run_id: `{v.get("run_id")}`',
            f'- version: `{v.get("version")}`',
            f'- run_dir: `{v.get("run_dir")}`',
            f'- started: {v.get("started")}   finished: {v.get("finished") or "(open)"}',
            f'- driver: `{(v.get("driver") or {}).get("path")}` '
            f'sha256 `{str((v.get("driver") or {}).get("sha256"))[:16]}`',
            f'- events: {v["events"]}' + (f' ({v["bad_lines"]} unreadable line(s))' if v['bad_lines'] else ''),
            f'- jsonl: `{v["jsonl"]}`',
            '',
        ]
        for w in v.get('warnings') or []:
            L.append(f'> **WARNING** {w}')
        cg = cfg.get('config_gates') or {}
        for r in cg.get('reasons') or []:
            L.append(f'> **CONFIG GATE** {r}')
        if v.get('warnings') or cg.get('reasons'):
            L.append('')

        env = cfg.get('env') or {}
        if env:
            L += ['## Config — environment', '', '| ZYG_* | value |', '|---|---|']
            for k in sorted(env):
                L.append(f'| `{k}` | {_cell(env[k], 48)} |')
            L.append('')
        kw = flatten(cfg.get('render_kwargs') or {})
        if kw:
            L += ['## Config — resolved render kwargs', '', '| kwarg | value |', '|---|---|']
            for k in sorted(kw):
                L.append(f'| `{k}` | {_cell(kw[k], 90)} |')
            L.append('')
        if cfg.get('mask') or cfg.get('ref_images') or cfg.get('loras'):
            L += ['## Config — assets', '', '| asset | value |', '|---|---|']
            m = cfg.get('mask') or {}
            if m:
                L.append(
                    f'| mask | `{m.get("path")}` — {m.get("width")}x{m.get("height")}, '
                    f'open {m.get("white_frac")}, sha `{str(m.get("sha256"))[:12]}` |'
                )
            for i, r in enumerate(cfg.get('ref_images') or []):
                L.append(
                    f'| ref[{i}] | `{r.get("path")}` sha `{str(r.get("sha256"))[:12]}`'
                    f'{"" if r.get("exists") else " **MISSING**"} |'
                )
            for i, l in enumerate(cfg.get('loras') or []):
                L.append(f'| lora[{i}] | `{l.get("name")}` @ {l.get("strength")} |')
            L.append('')
        beats = cfg.get('beats') or []
        if beats:
            bm = cfg.get('beat_map') or {}
            L += [
                '## Beats',
                '',
                f'mapping `{bm.get("mapping")}` · windows `{bm.get("windows")}` · '
                f'section_size `{bm.get("section_size")}` · dead `{bm.get("dead_beats")}`',
                '',
                '| # | chars | sha12 | window(s) | text |',
                '|---|---|---|---|---|',
            ]
            mapping = list(bm.get('mapping') or [])
            for b in beats:
                wins = [f'w{i}' for i, p in enumerate(mapping) if p == b['index']]
                flag = ' **OVER LIMIT**' if b.get('over_limit') else ''
                L.append(
                    f'| {b["index"]} | {b["chars"]}{flag} | `{b.get("sha12")}` | '
                    f'{",".join(wins) or "**DEAD**"} | {_cell(b.get("text"), 160)} |'
                )
            L.append('')
        if v['stages']:
            L += ['## Stage timeline', '', '| stage | at | wall_s | vram_mb | status |', '|---|---|---|---|---|']
            total = 0.0
            for s in v['stages']:
                total += float(s.get('wall_s') or 0.0)
                L.append(
                    f'| `{s["stage"]}` | {s.get("ts_iso")} | '
                    f'{s.get("wall_s")} | {s.get("vram_mb")} | {s.get("status")} |'
                )
            L += [f'| **total** | | **{round(total, 1)}** | | |', '']
        if v['metrics']:
            L += ['## Metrics', '', '| metric | value | source |', '|---|---|---|']
            for k in sorted(v['metrics']):
                L.append(f'| `{k}` | {_cell(v["metrics"][k], 40)} | {v["metric_sources"].get(k, "")} |')
            L.append('')
        if v['gates']:
            nfail = sum(1 for g in v['gates'].values() if not g.get('ok'))
            L += [
                f'## Gate verdicts — {len(v["gates"]) - nfail} pass / {nfail} fail',
                '',
                '| gate | verdict | score | threshold |',
                '|---|---|---|---|',
            ]
            for k in sorted(v['gates'], key=lambda x: (v['gates'][x].get('ok') is not False, x)):
                g = v['gates'][k]
                L.append(
                    f'| `{k}` | {"PASS" if g.get("ok") else "**FAIL**"} | {g.get("score")} | {g.get("threshold")} |'
                )
            L.append('')
        if v['checkpoints']:
            L += ['## Checkpoints', '', '| stage | artifact | at | size |', '|---|---|---|---|']
            for c in v['checkpoints']:
                f = c.get('file') or {}
                L.append(
                    f'| `{c.get("stage")}` | `{os.path.basename(str(c.get("artifact")))}` '
                    f'| {c.get("ts_iso")} | {f.get("size")} |'
                )
            L.append('')
        if v.get('verdict'):
            L += ['## Verdict', '', '```json', json.dumps(v['verdict'], indent=1, default=str)[:2000], '```', '']
        path = os.path.join(v['run_dir'], LOGBOOK_NAME)
        _atomic_write(path, '\n'.join(L) + '\n', log_fn=log)
        return path
    except Exception as e:
        log(f'[run_logbook] write_logbook_md failed (ignored): {e}')
        return ''


# ── retro ingest: build a logbook from a run that already happened ───────────


def _ingest_metrics(result, diagnosis) -> dict:
    """Harvest every number a finished run already wrote down. Namespaced so a later
    diff can tell a raw-render measurement from a delivered-clip one — they disagree
    routinely (the composite adds real motion) and conflating them wastes a day."""
    M = {}
    q = ((result.get('motion') or {}).get('quality') or {}).get('report') or {}
    for name, r in (q.get('regions') or {}).items():
        for k in (
            'flow_mean',
            'flow_median',
            'reversals_per_s',
            'net_path',
            'net_path_win',
            'flow_perpix',
            'mean_turn_deg',
        ):
            if r.get(k) is not None:
                M[f'raw.{name}.{k}'] = r[k]
    b = ((result.get('motion') or {}).get('balance') or {}).get('report') or {}
    for pair, r in (b.get('pairs') or {}).items():
        if r.get('ratio') is not None:
            M[f'raw.balance.{pair.replace("/", "_over_")}'] = r['ratio']
    fr = ((result.get('gates') or {}).get('flow_raw') or {}).get('regions') or {}
    for name, r in fr.items():
        for k in ('flow_mean', 'flow_p95', 'churn_mean', 'churn_p95'):
            if r.get(k) is not None:
                M[f'flow_raw.{name}.{k}'] = r[k]
    for name, g in ((diagnosis.get('signature') or {}).get('gates') or {}).items():
        if isinstance(g, dict) and g.get('score') is not None:
            M[f'gate.{name}'] = g['score']
    for name, r in ((diagnosis.get('signature') or {}).get('regions') or {}).items():
        if isinstance(r, dict):
            for k in ('flow_mean', 'flow_mean_px', 'churn_mean'):
                if r.get(k) is not None:
                    M[f'region.{name}.{k}'] = r[k]
    v = result.get('verdict') or {}
    for k in ('failed_checks', 'degradations'):
        if v.get(k) is not None:
            M[f'verdict.{k}'] = v[k]
    return M


def ingest_run_dir(
    run_dir, version=None, driver_file=None, measured=None, env_override=None, mirror=False, force=False, log_fn=None
) -> dict:
    """Retro-populate the logbook from a run that ALREADY happened.

    Reads result.json (params / arch_flags / beats / gates / verdict), diagnosis.json
    (signature gates + regions), shot_metadata.json (pins) and debug/report.json (the
    real stage timeline with wall_s and vram_mb), plus any `measured` metrics the
    caller took off the clips themselves.

    mirror defaults FALSE: pushing backdated gate rows into run_ledger's sqlite with
    today's timestamp would silently poison trends()' recent-vs-prior z-scores.

    The log is append-only, so ingesting the same run twice would double its stage and
    checkpoint rows; a run that already carries a 'finish' event is therefore refused
    unless force=True. Delete its jsonl to re-ingest cleanly.

    Returns the run handle. Fail-safe: partial inputs produce a partial logbook."""
    log = log_fn or _log_noop
    run_dir = os.path.abspath(str(run_dir))
    _h0 = _handle(run_dir)
    if not force:
        _prev, _ = _read_jsonl(_h0['jsonl'])
        if any(r.get('event') == 'finish' for r in _prev):
            log(
                f'[run_logbook] {_h0["run_key"]} already ingested '
                f'({len(_prev)} events) — refusing to duplicate; pass force=True or '
                f'delete {_h0["jsonl"]}'
            )
            return _h0
    result = _read_json(os.path.join(run_dir, 'result.json'), {}) or {}
    diagnosis = _read_json(os.path.join(run_dir, 'diagnosis.json'), {}) or {}
    shot = _read_json(os.path.join(run_dir, 'shot_metadata.json'), {}) or {}
    report = _read_json(os.path.join(run_dir, 'debug', 'report.json'), {}) or {}

    if not version:
        import re

        m = re.findall(r'v\d+', os.path.basename(run_dir))
        version = m[-1] if m else None
    run_id = report.get('run_id') or (result.get('verdict') or {}).get('run_id')
    h = start_run(
        run_dir,
        version=version,
        run_id=run_id,
        driver_file=driver_file,
        started=report.get('started'),
        notes=f'retro-ingested {_now()[1]} from result.json/diagnosis.json/shot_metadata.json/debug/report.json',
        log_fn=log,
    )

    params = dict(result.get('params') or {})
    arch = dict(result.get('arch_flags') or {})
    env = {k: v for k, v in arch.items() if str(k).startswith('ZYG_')}
    # non-ZYG architecture switches (set_embed, …) are config too — they just are not
    # environment variables, so they ride along in extra rather than faking an env key
    arch_other = {k: v for k, v in arch.items() if not str(k).startswith('ZYG_')}
    for k in KNOWN_ZYG_KEYS:
        env.setdefault(k, None)
    if env_override:
        env.update(env_override)

    beats_blk = result.get('beats') or {}
    beat_texts = list(beats_blk.get('text') or [])
    beat_map = {
        k: beats_blk.get(k)
        for k in ('num_beats', 'mapping', 'windows', 'window_times', 'spans', 'dead_beats', 'section_size', 'source')
        if k in beats_blk
    }

    def _plist(val):
        if isinstance(val, (list, tuple)):
            return list(val)
        try:
            import ast

            v = ast.literal_eval(str(val))
            return list(v) if isinstance(v, (list, tuple)) else []
        except Exception:
            return []

    refs = _plist(params.get('ref_images_paths'))
    loras = _plist(params.get('loras'))
    mask_path = params.get('mask_path')
    if mask_path and not os.path.isabs(mask_path):
        cand = os.path.join(_CREWS, mask_path)
        mask_path = cand if os.path.exists(cand) else mask_path
    final_path = result.get('final')

    kwargs = {k: v for k, v in params.items() if k not in ('ref_images_paths', 'loras', 'mask_path')}
    for k in ('context_windows', 'context_frames', 'context_overlap', 'context_stride'):
        if k in params:
            kwargs[k] = params[k]

    record_config(
        h,
        env=env,
        render_kwargs=kwargs,
        beats=beat_texts,
        beat_map=beat_map,
        mask_path=mask_path,
        ref_images=refs,
        loras=loras,
        driver_file=driver_file,
        version=version,
        final_name=os.path.basename(str(final_path)) if final_path else None,
        extra={
            'arch': arch_other,
            'shot_metadata': shot,
            'pipe_ref': result.get('pipe_ref'),
            'fx': result.get('fx'),
            'gate_notes': result.get('gate_notes'),
        },
        log_fn=log,
    )

    # debug/report.json stores each stage as a bare HH:MM:SS; re-date it from the run's
    # start and roll the day forward on a wrap, so an overnight render (22:13 -> 00:xx)
    # does not read as having finished before it began.
    day = str(report.get('started') or '')[:10]
    prev_t = None
    for s in report.get('stages') or []:
        at = None
        t = str(s.get('t') or '')
        if day and len(t) == 8:
            if prev_t and t < prev_t:
                try:
                    import datetime

                    day = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
                except (TypeError, ValueError) as _exc:
                    _zyg_log.debug('day rollover for %r skipped: %s', day, _exc)
            prev_t = t
            at = f'{day} {t}'
        record_stage(
            h,
            s.get('stage'),
            wall_s=s.get('wall_s'),
            vram_mb=s.get('vram_mb'),
            status='ok',
            at=at,
            params={
                k: v
                for k, v in (s.get('params') or {}).items()
                if k in ('frames', 'num_beats', 'beat_map', 'regions', 'motion_regions', 'floor_final')
            },
            mirror=mirror,
            log_fn=log,
        )

    M = _ingest_metrics(result, diagnosis)
    if M:
        record_metrics(h, M, source='result.json/diagnosis.json (on disk)', log_fn=log)
    total = sum(float(s.get('wall_s') or 0) for s in (report.get('stages') or []))
    if total:
        record_metrics(h, {'timeline.total_wall_s': round(total, 1)}, source='debug/report.json', log_fn=log)
    for group in (
        (measured or [])
        if isinstance(measured, list)
        else ([{'metrics': measured, 'source': 'measured'}] if measured else [])
    ):
        record_metrics(h, group.get('metrics') or {}, source=group.get('source') or 'measured', log_fn=log)

    gates = {}
    for name, g in ((diagnosis.get('signature') or {}).get('gates') or {}).items():
        if isinstance(g, dict):
            gates[name] = {'ok': bool(g.get('ok')), 'score': g.get('score'), 'threshold': g.get('threshold')}
    for c in report.get('qc') or []:
        if isinstance(c, dict) and c.get('check'):
            gates.setdefault(
                str(c['check']),
                {'ok': bool(c.get('ok')), 'score': c.get('score'), 'threshold': None, 'note': c.get('note') or ''},
            )
    record_gates(h, gates, verdict=result.get('verdict') or report.get('verdict'), mirror=mirror, log_fn=log)

    for stage, art in (
        ('render', 'vace_static.mp4'),
        ('smoke_fx', 'smoked17.mp4'),
        ('ink_fx', 'inked17.mp4'),
        ('interpolate', 'v11_17fps.mp4'),
        ('deliver', os.path.basename(str(final_path)) if final_path else None),
    ):
        if not art:
            continue
        p = os.path.join(run_dir, art)
        if os.path.exists(p):
            record_checkpoint(run_dir, stage, p, meta={'retro': True}, log_fn=log)

    finish_run(
        h,
        ok=bool(result.get('gates_ok')),
        final_path=final_path,
        finished=((result.get('verdict') or {}).get('finished') or diagnosis.get('when')),
        notes='retro-ingest',
        log_fn=log,
    )
    log(f'[run_logbook] ingested {run_dir} as {h["run_key"]} ({len(M)} metrics, {len(gates)} gates)')
    return h


# ── CLI ──────────────────────────────────────────────────────────────────────


def format_list(rows=None) -> str:
    rows = list_runs() if rows is None else rows
    hdr = (
        f'{"run_key":<26}{"ver":>6}{"finished":>21}{"ok":>5}'
        f'{"stg":>5}{"gate":>6}{"fail":>6}{"met":>6}{"ckpt":>6}  final'
    )
    L = [f'run logbook — {LOGBOOK_DIR}', '', hdr, '-' * len(hdr)]
    if not rows:
        L.append('  (no runs recorded — python3 run_logbook.py ingest <run_dir>)')
    for r in rows:
        L.append(
            f'{str(r["run_key"])[:26]:<26}{str(r.get("version") or "-"):>6}'
            f'{str(r.get("finished") or r.get("started") or "-"):>21}'
            f'{("yes" if r.get("ok") else "no" if r.get("ok") is False else "-"):>5}'
            f'{r.get("stages", 0):>5}{r.get("gates", 0):>6}'
            f'{r.get("gates_failed", 0):>6}{r.get("metrics", 0):>6}'
            f'{r.get("checkpoints", 0):>6}  '
            f'{os.path.basename(str(r.get("final") or "-"))}'
        )
    return '\n'.join(L)


def _main(*a, **k):
    """Kept as a delegate: the package __init__ re-exports this name. The body moved to report_cli."""
    from zyg_workflows.run_logbook.report_cli import _main as _m

    return _m(*a, **k)


if __name__ == '__main__':  # the CLI lives in report_cli
    from zyg_workflows.run_logbook.report_cli import _main as _cli_main

    raise SystemExit(_cli_main())
