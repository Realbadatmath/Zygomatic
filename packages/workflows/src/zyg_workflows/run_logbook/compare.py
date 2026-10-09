# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""compare — a verbatim section of the pre-split run_logbook.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

from __future__ import annotations

import json  # noqa: F401
import os  # noqa: F401

from zyg_workflows.run_logbook.plumbing import (  # noqa: F401
    _log_noop,
    _now,
    resolve_run,
)
from zyg_workflows.run_logbook.reading import (  # noqa: F401
    load_run,
)


# ── the diff that matters ────────────────────────────────────────────────────


def flatten(obj, prefix='', out=None, _depth=0):
    """Nested dict → dotted-key flat dict. Lists of scalars become one JSON string;
    lists of dicts are indexed. Depth-capped so a pathological structure cannot hang."""
    if out is None:
        out = {}
    if _depth > 8:
        out[prefix.rstrip('.')] = json.dumps(obj, default=str)[:400]
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f'{prefix}{k}.', out, _depth + 1)
    elif isinstance(obj, (list, tuple)):
        if obj and all(isinstance(x, dict) for x in obj):
            for i, v in enumerate(obj):
                flatten(v, f'{prefix}{i}.', out, _depth + 1)
        else:
            out[prefix.rstrip('.')] = json.dumps(list(obj), default=str)[:400]
    else:
        out[prefix.rstrip('.')] = obj
    return out


_CONFIG_SKIP_SUFFIX = ('.text', '.mtime_iso', '.abs', '.note')


def _config_flat(view) -> dict:
    """The comparable surface of a config: env, resolved kwargs, beat shape, beat map,
    mask, refs, loras, driver, version. Beat TEXT is excluded (compared by sha12 + char
    count instead) — a 1200-char prompt in a diff table is unreadable and the sha is
    the honest answer to "did it change?"."""
    cfg = (view or {}).get('config') or {}
    flat = {}
    flat.update({f'env.{k}': v for k, v in (cfg.get('env') or {}).items()})
    flat.update({f'kwargs.{k}': v for k, v in flatten(cfg.get('render_kwargs') or {}).items()})
    for b in cfg.get('beats') or []:
        flat[f'beat[{b.get("index")}].chars'] = b.get('chars')
        flat[f'beat[{b.get("index")}].sha12'] = b.get('sha12')
    bm = cfg.get('beat_map') or {}
    for k in ('latents', 'section_size', 'mapping', 'windows', 'dead_beats', 'num_beats'):
        if k in bm:
            v = bm[k]
            flat[f'beat_map.{k}'] = json.dumps(v, default=str) if isinstance(v, (list, tuple)) else v
    m = cfg.get('mask') or {}
    for k in ('path', 'sha256', 'width', 'height', 'white_frac'):
        if k in m:
            flat[f'mask.{k}'] = m[k]
    for i, r in enumerate(cfg.get('ref_images') or []):
        flat[f'ref[{i}].path'] = r.get('path')
        flat[f'ref[{i}].sha256'] = r.get('sha256')
    for i, l in enumerate(cfg.get('loras') or []):
        flat[f'lora[{i}].name'] = l.get('name')
        flat[f'lora[{i}].strength'] = l.get('strength')
    d = cfg.get('driver') or (view or {}).get('driver') or {}
    if d:
        flat['driver.path'] = d.get('path')
        flat['driver.sha256'] = d.get('sha256')
    flat['version'] = cfg.get('version') or (view or {}).get('version')
    if cfg.get('final_name'):
        flat['final_name'] = cfg['final_name']
    for k, v in flatten(cfg.get('extra') or {}).items():
        flat[f'extra.{k}'] = v
    return {k: v for k, v in flat.items() if not k.endswith(_CONFIG_SKIP_SUFFIX)}


# Metric ranking tiers. Ranking a 115-row delta by raw |%| puts whatever internal
# counter is noisiest on top — the v11→v12 table led with gate.flicker_index +670%
# while the number the decision was actually made on (verified.face_alive.cornelis
# 0.70 → 0.33) sat at row 34. Operator-verified measurements outrank the delivered
# clip, which outranks auto-harvested internals; |%| ranks WITHIN a tier.
_METRIC_TIERS = (
    ('verified.', 0),
    ('final.', 1),
    ('raw.', 2),
    ('flow_raw.', 2),
    ('region.', 3),
    ('gate.', 3),
    ('verdict.', 2),
    ('timeline.', 2),
)


def _metric_tier(key):
    for pre, rank in _METRIC_TIERS:
        if str(key).startswith(pre):
            return rank
    return 4


def _fnum(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def compare_runs(run_a, run_b, log_fn=None) -> dict:
    """THE tool. What CHANGED (config) next to what MOVED (metrics), for two runs.

    This is the command that turns the v11→v12 postmortem from a day of re-reading
    code into one line: ZYG_VACE_DIFFDIFF 0 → 1, and every metric that answered it.

    Returns {'ok','a','b','config','metrics','gates','summary'}; config/metrics rows are
    {'key','a','b'} (+ 'delta','pct' for numerics), metrics sorted by |relative move|."""
    log = log_fn or _log_noop
    ha, hb = resolve_run(run_a), resolve_run(run_b)
    if ha is None or hb is None:
        missing = [str(r) for r, h in ((run_a, ha), (run_b, hb)) if h is None]
        return {'ok': False, 'error': f'unknown run(s): {missing}. Try: python3 run_logbook.py list'}
    va, vb = load_run(ha), load_run(hb)

    ca, cb = _config_flat(va), _config_flat(vb)
    config_rows = []
    for k in sorted(set(ca) | set(cb)):
        x, y = ca.get(k), cb.get(k)
        if x != y:
            config_rows.append(
                {
                    'key': k,
                    'a': x,
                    'b': y,
                    'kind': ('added' if k not in ca else 'removed' if k not in cb else 'changed'),
                }
            )

    ma, mb = va['metrics'], vb['metrics']
    metric_rows = []
    for k in sorted(set(ma) | set(mb)):
        x, y = ma.get(k), mb.get(k)
        if x == y:
            continue
        fx, fy = _fnum(x), _fnum(y)
        row = {
            'key': k,
            'a': x,
            'b': y,
            'delta': None,
            'pct': None,
            'source': va['metric_sources'].get(k) or vb['metric_sources'].get(k) or '',
        }
        if fx is not None and fy is not None:
            row['delta'] = round(fy - fx, 6)
            if abs(fx) > 1e-9:
                row['pct'] = round((fy - fx) / abs(fx) * 100.0, 1)
        metric_rows.append(row)
    metric_rows.sort(
        key=lambda r: (
            _metric_tier(r['key']),
            -abs(r['pct']) if r['pct'] is not None else 0,
            -abs(r['delta']) if r['delta'] is not None else 0,
            r['key'],
        )
    )

    gate_rows = []
    for k in sorted(set(va['gates']) | set(vb['gates'])):
        ga, gb = va['gates'].get(k, {}), vb['gates'].get(k, {})
        oa, ob = ga.get('ok'), gb.get('ok')
        sa, sb = ga.get('score'), gb.get('score')
        if oa != ob or sa != sb:
            gate_rows.append(
                {
                    'key': k,
                    'a_ok': oa,
                    'b_ok': ob,
                    'a': sa,
                    'b': sb,
                    'flip': ('PASS->FAIL' if oa and ob is False else 'FAIL->PASS' if oa is False and ob else ''),
                }
            )
    gate_rows.sort(key=lambda r: (r['flip'] != 'PASS->FAIL', r['key']))

    summary = []
    if not config_rows:
        summary.append(
            'NO config difference recorded — if the outputs differ, the '
            'difference is unrecorded (seed, code edit, or an uncaptured env var).'
        )
    else:
        summary.append(f'{len(config_rows)} config field(s) changed; {len(metric_rows)} metric(s) moved.')
        env_rows = [r for r in config_rows if r['key'].startswith('env.')]
        if env_rows:
            summary.append('env: ' + '; '.join(f'{r["key"][4:]} {r["a"]!r} -> {r["b"]!r}' for r in env_rows[:6]))
    if metric_rows:
        top = metric_rows[0]
        summary.append(
            f'biggest move: {top["key"]} {top["a"]} -> {top["b"]}'
            + (f' ({top["pct"]:+.1f}%)' if top.get('pct') is not None else '')
        )
    flips = [r for r in gate_rows if r['flip'] == 'PASS->FAIL']
    if flips:
        summary.append('gates regressed: ' + ', '.join(r['key'] for r in flips[:8]))
    for v, tag in ((va, 'A'), (vb, 'B')):
        for w in v.get('warnings') or []:
            summary.append(f'[{tag} {v["run_key"]}] WARNING: {w}')
        for r in ((v.get('config') or {}).get('config_gates') or {}).get('reasons', []):
            summary.append(f'[{tag} {v["run_key"]}] CONFIG GATE: {r}')

    log(
        f'[run_logbook] compare {va["run_key"]} vs {vb["run_key"]}: '
        f'{len(config_rows)} config, {len(metric_rows)} metric, {len(gate_rows)} gate rows'
    )
    return {
        'ok': True,
        'a': _run_meta(va),
        'b': _run_meta(vb),
        'config': config_rows,
        'metrics': metric_rows,
        'gates': gate_rows,
        'summary': summary,
        'generated': _now()[1],
    }


def _run_meta(v):
    return {
        'run_key': v['run_key'],
        'run_id': v.get('run_id'),
        'run_dir': v.get('run_dir'),
        'version': v.get('version'),
        'started': v.get('started'),
        'finished': v.get('finished'),
        'ok': v.get('ok'),
        'driver_sha256': (v.get('driver') or {}).get('sha256'),
        'final': (v.get('finish') or {}).get('final', {}).get('path'),
        'stages': len(v['stages']),
        'metrics': len(v['metrics']),
        'gates': len(v['gates']),
    }


def _cell(v, width=64):
    """Markdown-safe cell: pipes escaped, newlines flattened, long values truncated.

    Path-like values are truncated from the LEFT. Head-truncating two long paths that
    share a prefix renders them IDENTICAL in the diff table — a config delta that
    displays as no delta is worse than no table at all."""
    if v is None:
        return '_(unset)_'
    if isinstance(v, bool):
        return '`true`' if v else '`false`'
    s = v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)
    s = s.replace('\n', ' ').replace('|', '\\|').strip()
    if len(s) > width:
        if '/' in s and not s.startswith('['):
            s = '…' + s[-(width - 1) :]
        else:
            s = s[: width - 1] + '…'
    return f'`{s}`' if s else '_(empty)_'


def format_compare(cmp, limit=None) -> str:
    """Two-column markdown: run A and run B side by side, config delta first, metric
    delta second. Paste it into a report; read it in a terminal.

    limit truncates the metric table to the top N rows (already tier-ranked, so the
    operator-verified movers survive the cut); None prints the complete record."""
    if not cmp or not cmp.get('ok'):
        return f'compare FAILED: {(cmp or {}).get("error")}'
    a, b = cmp['a'], cmp['b']
    ka, kb = a['run_key'], b['run_key']
    L = [f'# RUN COMPARE — {ka}  →  {kb}', '', f'generated {cmp["generated"]}', '']
    L += ['| | ' + ka + ' | ' + kb + ' |', '|---|---|---|']
    for label, key in (
        ('run_id', 'run_id'),
        ('version', 'version'),
        ('run_dir', 'run_dir'),
        ('delivered file', 'final'),
        ('driver sha256', 'driver_sha256'),
        ('started', 'started'),
        ('finished', 'finished'),
        ('stages / metrics / gates', None),
    ):
        if key is None:
            L.append(
                f'| {label} | `{a["stages"]} / {a["metrics"]} / {a["gates"]}` '
                f'| `{b["stages"]} / {b["metrics"]} / {b["gates"]}` |'
            )
        else:
            av, bv = a.get(key), b.get(key)
            if key in ('run_dir', 'final'):
                av = os.path.basename(str(av)) if av else av
                bv = os.path.basename(str(bv)) if bv else bv
            if key == 'driver_sha256':
                av = str(av)[:12] if av else None
                bv = str(bv)[:12] if bv else None
            L.append(f'| {label} | {_cell(av)} | {_cell(bv)} |')
    L += ['', '## READ THIS FIRST', '']
    for s in cmp['summary'] or ['(nothing to report)']:
        L.append(f'- {s}')

    L += [
        '',
        f'## CONFIG DELTA — what changed ({len(cmp["config"])})',
        '',
        f'| config key | {ka} | {kb} |',
        '|---|---|---|',
    ]
    if not cmp['config']:
        L.append('| _(no recorded config difference)_ | | |')
    for r in cmp['config']:
        L.append(f'| `{r["key"]}` | {_cell(r["a"])} | {_cell(r["b"])} |')

    rows = cmp['metrics']
    shown = rows if not limit else rows[: int(limit)]
    L += [
        '',
        f'## METRIC DELTA — what moved ({len(rows)})' + (f' — top {len(shown)}' if len(shown) < len(rows) else ''),
        '',
        f'| metric | {ka} | {kb} | Δ | % |',
        '|---|---|---|---|---|',
    ]
    if not rows:
        L.append('| _(no recorded metric difference)_ | | | | |')
    for r in shown:
        d = '' if r['delta'] is None else f'{r["delta"]:+g}'
        p = '' if r['pct'] is None else f'{r["pct"]:+.1f}%'
        L.append(f'| `{r["key"]}` | {_cell(r["a"], 28)} | {_cell(r["b"], 28)} | {d} | {p} |')
    if len(shown) < len(rows):
        L.append(f'| _… {len(rows) - len(shown)} more (drop --top for the full record)_ | | | | |')

    if cmp['gates']:
        L += ['', f'## GATE DELTA ({len(cmp["gates"])})', '', f'| gate | {ka} | {kb} | flip |', '|---|---|---|---|']
        for r in cmp['gates']:
            av = f'{"PASS" if r["a_ok"] else "FAIL" if r["a_ok"] is False else "-"}'
            bv = f'{"PASS" if r["b_ok"] else "FAIL" if r["b_ok"] is False else "-"}'
            if r['a'] is not None:
                av += f' ({r["a"]})'
            if r['b'] is not None:
                bv += f' ({r["b"]})'
            L.append(f'| `{r["key"]}` | {av} | {bv} | {r["flip"]} |')
    return '\n'.join(L)
