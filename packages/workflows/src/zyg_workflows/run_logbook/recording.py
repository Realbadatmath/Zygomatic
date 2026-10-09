# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""recording — a verbatim section of the pre-split run_logbook.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

from __future__ import annotations

import json  # noqa: F401
import logging as _zyg_logging  # noqa: F401
import os  # noqa: F401

from zyg_workflows.run_logbook.plumbing import (  # noqa: F401
    BEAT_CHAR_LIMIT,
    INDEX_PATH,
    KNOWN_ZYG_KEYS,
    LOGBOOK_DIR,
    SCHEMA,
    _append_jsonl,
    _file_facts,
    _handle,
    _log_noop,
    _now,
    _safe_key,
    jsonl_path,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.run_logbook')


# ── recording API ────────────────────────────────────────────────────────────


def _emit(h, event, payload, log_fn=None) -> bool:
    from zyg_workflows.run_logbook import report as _report  # function-local: report loads after recording

    ts, iso = _now()
    rec = {
        'schema': SCHEMA,
        'event': event,
        'run_key': h.get('run_key'),
        'run_dir': h.get('run_dir'),
        'ts': ts,
        'ts_iso': iso,
    }
    rec.update(payload or {})
    ok = _append_jsonl(h['jsonl'], rec, log_fn=log_fn)
    if ok and h.get('run_dir'):
        _report.write_logbook_md(h, log_fn=log_fn)
    return ok


def start_run(
    run_dir, version=None, run_name=None, run_id=None, driver_file=None, notes=None, started=None, log_fn=None
) -> dict:
    """Open a run. Returns the handle every later call takes.

    version/run_dir/run_key are deliberately derived from ONE input: if `version` is
    given it must appear in run_dir, otherwise the v12 shape (right directory, wrong
    filename constant) is already live and is flagged here rather than at delivery.

    `started` overrides the wall clock — retro-ingest MUST pass the original run's start
    time, or the logbook confidently reports the day it was written instead of the day
    the render happened, which is the exact failure mode it exists to prevent."""
    log = log_fn or _log_noop
    try:
        run_dir = os.path.abspath(str(run_dir))
        key = _safe_key(run_name or os.path.basename(run_dir))
        h = {'run_key': key, 'run_dir': run_dir, 'jsonl': jsonl_path(key), 'version': version, 'started': _now()[1]}
        try:
            from zyg_workflows import run_ledger

            h['run_id'] = run_ledger.current_run_id(run_id)
        except Exception:
            h['run_id'] = str(run_id or os.environ.get('ZYG_RUN_ID') or 'adhoc')
        os.makedirs(LOGBOOK_DIR, exist_ok=True)
        drv = (
            _file_facts(driver_file, log_fn=log_fn)
            if driver_file
            else {
                'path': None,
                'exists': False,
                'note': 'no driver file recorded — this run cannot be re-explained from source',
            }
        )
        warn = []
        if version and version not in os.path.basename(run_dir):
            warn.append(
                f"version '{version}' does not appear in run_dir "
                f"'{os.path.basename(run_dir)}' — derive both from one constant"
            )
        if not drv.get('exists'):
            warn.append('driver file missing/unrecorded — no sha256 attestation')
        _emit(
            h,
            'start',
            {
                'run_id': h['run_id'],
                'version': version,
                'driver': drv,
                'notes': notes,
                'warnings': warn,
                'started': started or h['started'],
            },
            log_fn=log,
        )
        for w in warn:
            log(f'[run_logbook] WARN {key}: {w}')
        log(f'[run_logbook] run {key} opened -> {h["jsonl"]}')
        return h
    except Exception as e:
        log(f'[run_logbook] start_run failed (ignored): {e}')
        return {
            'run_key': _safe_key(str(run_dir)),
            'run_dir': None,
            'jsonl': jsonl_path(str(run_dir)),
            'error': str(e)[:200],
        }


def snapshot_env(keys=None, extra=None) -> dict:
    """Every ZYG_* actually in the environment PLUS every KNOWN_ZYG_KEYS entry (null when
    unset). Unset-but-read is a real configuration state and must be on the record."""
    env = {}
    for k in keys or KNOWN_ZYG_KEYS:
        env[k] = os.environ.get(k)
    for k, v in os.environ.items():
        if k.startswith('ZYG_'):
            env[k] = v
    for k, v in (extra or {}).items():
        env[str(k)] = v
    return dict(sorted(env.items()))


def mask_stats(mask_path, log_fn=None) -> dict:
    """Size + open fraction of a VACE character mask. white_frac is the number the
    silhouette work (mask_v9, pole zone 0.0% vs v8's 76.4%) turns on, so it belongs in
    the config snapshot next to the path, not in a separate report."""
    out = _file_facts(mask_path, log_fn=log_fn)
    try:
        from PIL import Image
        import numpy as np

        with Image.open(str(mask_path)) as im:
            a = np.asarray(im.convert('L'), dtype='float32')
        out.update(
            {
                'width': int(a.shape[1]),
                'height': int(a.shape[0]),
                'white_frac': round(float((a >= 128).mean()), 4),
                'mean': round(float(a.mean() / 255.0), 4),
            }
        )
    except Exception as e:
        out['stats_error'] = str(e)[:160]
    return out


def _beat_records(beats):
    """[{'index','chars','over_limit','sha12','text'}] — char counts are first-class
    because the 1500-char clip silently drops the tail of any beat that exceeds it."""
    out = []
    for i, b in enumerate(list(beats or [])):
        t = b if isinstance(b, str) else json.dumps(b, default=str, ensure_ascii=False)
        try:
            import hashlib

            sha12 = hashlib.sha256(t.encode('utf-8')).hexdigest()[:12]
        except Exception:
            sha12 = None
        out.append({'index': i, 'chars': len(t), 'over_limit': len(t) > BEAT_CHAR_LIMIT, 'sha12': sha12, 'text': t})
    return out


def gate_version_consistency(version, run_dir=None, final_name=None) -> dict:
    """THE v12 GATE. version, directory and output filename must agree.

    2026-07-31: the v12 driver was copied from v11, its OUT dir was updated and its
    output FILENAME constant was not, so v12 wrote FINAL_scene20_v11.mp4 into
    scene20_v12/ and two files that were compared as v11-vs-v12 were labelled the same.
    Returns {'ok','checks','reasons'} — cheap, config-time, before the GPU is spent."""
    checks, reasons = [], []
    v = str(version or '').strip()
    if not v:
        return {'ok': True, 'checks': [], 'reasons': [], 'note': 'no version supplied — gate skipped (supply one)'}
    if run_dir:
        base = os.path.basename(os.path.abspath(str(run_dir)))
        ok = v in base
        checks.append({'check': 'version_in_run_dir', 'ok': ok, 'value': base})
        if not ok:
            reasons.append(f"run_dir '{base}' does not contain version '{v}'")
    if final_name:
        base = os.path.basename(str(final_name))
        ok = v in base
        checks.append({'check': 'version_in_output_filename', 'ok': ok, 'value': base})
        if not ok:
            reasons.append(
                f"output filename '{base}' does not contain version '{v}' — this is the "
                f'v12 incident shape: the file will be mislabelled and compared as the '
                f'wrong run. Derive the filename from the version constant.'
            )
    if run_dir and final_name:
        d = os.path.basename(os.path.abspath(str(run_dir)))
        f = os.path.basename(str(final_name))
        import re

        dv = re.findall(r'v\d+', d)
        fv = re.findall(r'v\d+', f)
        if dv and fv and dv[-1] != fv[-1]:
            checks.append({'check': 'dir_vs_filename_version', 'ok': False, 'value': f'{dv[-1]} != {fv[-1]}'})
            reasons.append(f'run_dir says {dv[-1]} but the output file says {fv[-1]}')
        else:
            checks.append(
                {'check': 'dir_vs_filename_version', 'ok': True, 'value': f'{(dv or ["-"])[-1]}/{(fv or ["-"])[-1]}'}
            )
    return {'ok': not reasons, 'checks': checks, 'reasons': reasons}


def _config_gates(cfg, log_fn=None) -> dict:
    """Config-time gates: the mistakes that are visible BEFORE the render starts.
    Cheap, non-blocking, and every one of them has cost a deliverable at least once."""
    reasons = []
    checks = []

    over = [b['index'] for b in cfg.get('beats', []) if b.get('over_limit')]
    checks.append(
        {'check': 'beat_char_limit', 'ok': not over, 'value': f'limit {BEAT_CHAR_LIMIT}, over: {over or "none"}'}
    )
    if over:
        reasons.append(f'beats {over} exceed {BEAT_CHAR_LIMIT} chars — their tails never render')

    bm = cfg.get('beat_map') or {}
    dead = list(bm.get('dead_beats') or [])
    if bm:
        checks.append({'check': 'no_dead_beats', 'ok': not dead, 'value': f'mapping {bm.get("mapping")}'})
        if dead:
            reasons.append(f'DEAD BEATS {dead} — that text is never rendered by any window')
        n_beats = len(cfg.get('beats') or [])
        n_mapped = len(set(bm.get('mapping') or []))
        if n_beats and n_mapped and n_mapped != n_beats:
            reasons.append(f'{n_beats} beat texts but only {n_mapped} distinct beats selected')

    m = cfg.get('mask') or {}
    if m:
        checks.append({'check': 'mask_present', 'ok': bool(m.get('exists')), 'value': m.get('path')})
        if not m.get('exists'):
            reasons.append(f'mask {m.get("path")} missing')
        elif m.get('white_frac') is not None:
            # single source of truth for the cap: wan_vace_service._default_max_white()
            # (ZYG_MASK_MAX_WHITE, 0.86) — the shipped silhouette masks legitimately run
            # ~0.82 open, so a locally-invented tighter bound here would cry wolf on a
            # PROVEN mask. The only thing this gate adds is the all-black floor.
            try:
                from zyg_workflows import wan_vace_service

                cap = float(wan_vace_service._default_max_white())
            except Exception:
                cap = float(os.environ.get('ZYG_MASK_MAX_WHITE') or 0.86)
            if not (0.005 <= m['white_frac'] <= cap):
                reasons.append(
                    f'mask open fraction {m["white_frac"]} outside 0.005-{cap} — mask generates nothing / pins nothing'
                )

    refs = cfg.get('ref_images') or []
    missing = [r.get('path') for r in refs if not r.get('exists')]
    if refs:
        checks.append({'check': 'ref_images_present', 'ok': not missing, 'value': f'{len(refs)} ref(s)'})
        if missing:
            reasons.append(f'reference images missing: {missing}')

    loras = cfg.get('loras') or []
    zeroed = [l.get('name') for l in loras if not l.get('strength')]
    if loras:
        checks.append(
            {
                'check': 'lora_strengths',
                'ok': not zeroed,
                'value': ', '.join(f'{l.get("name")}@{l.get("strength")}' for l in loras),
            }
        )
        if zeroed:
            reasons.append(f'LoRA(s) listed at strength 0 (loaded but inert): {zeroed}')

    vc = cfg.get('version_gate') or {}
    if vc.get('checks'):
        checks.extend(vc['checks'])
        reasons.extend(vc.get('reasons') or [])

    return {'ok': not reasons, 'checks': checks, 'reasons': reasons}


def record_config(
    run,
    env=None,
    render_kwargs=None,
    beats=None,
    beat_map=None,
    mask_path=None,
    ref_images=None,
    loras=None,
    driver_file=None,
    version=None,
    final_name=None,
    extra=None,
    log_fn=None,
) -> dict:
    """The git-less config snapshot: everything needed to explain the result later
    WITHOUT re-reading the code that produced it.

    env          : dict, or None → snapshot_env() (all ZYG_* + known-read keys as null)
    render_kwargs: the RESOLVED kwargs actually handed to the renderer, post-defaults
    beats        : list of per-beat prompt strings (char counts are computed here)
    beat_map     : wan_vace_service.beat_window_map() output verbatim
    mask_path    : the character mask — path, sha256 AND open fraction are recorded
    ref_images   : list of paths (each hashed; a swapped ref sheet is invisible otherwise)
    loras        : [(name, strength)] or [{'name','strength'}]
    final_name   : the intended output FILENAME — checked against version + run_dir

    ALIASES (added 2026-08-01, after a REAL miss). A careful caller wrote
        record_config(..., render_kw=RENDER_KW, refs=REF_LIST)
    and, because those are not the contract's names, both fell through to `extra`.
    The snapshot then read render_kwargs {} / ref_images [] / mask {} for a run that
    demonstrably used 25 steps, cfg 6.0, shift 5.0, seed 7, two LoRAs and three refs —
    and the failure was SILENT, so it was only found when the values were needed to
    build a probe and had to be read back out of the driver source instead. That is
    precisely the thing this module exists to prevent, so the boundary now accepts the
    obvious alternates and SAYS SO in the log rather than quietly dropping them.

    Returns the snapshot (also emitted to the jsonl). Fail-safe: returns {} on error."""
    log = log_fn or _log_noop
    try:
        h = _handle(run)
        # Pull aliased values out of `extra` when the first-class arg was not supplied.
        if isinstance(extra, dict) and extra:
            _alias = {
                'render_kw': 'render_kwargs',
                'render_kwds': 'render_kwargs',
                'refs': 'ref_images',
                'ref_paths': 'ref_images',
                'mask': 'mask_path',
                'mask_png': 'mask_path',
            }
            _cur = {'render_kwargs': render_kwargs, 'ref_images': ref_images, 'mask_path': mask_path}
            for _a, _canon in _alias.items():
                if _cur.get(_canon) or _a not in extra:
                    continue
                _v = extra.get(_a)
                if _canon == 'mask_path' and isinstance(_v, dict):
                    _v = _v.get('path')
                if not _v:
                    continue
                _cur[_canon] = _v
                log(f'[logbook] record_config: {_a!r} accepted as {_canon!r} — use the contract name to silence this')
            render_kwargs = render_kwargs or _cur['render_kwargs']
            ref_images = ref_images or _cur['ref_images']
            mask_path = mask_path or _cur['mask_path']
        version = version or (run.get('version') if isinstance(run, dict) else None)
        lo = []
        for l in list(loras or []):
            if isinstance(l, dict):
                lo.append({'name': l.get('name'), 'strength': l.get('strength')})
            elif isinstance(l, (list, tuple)) and len(l) >= 2:
                lo.append({'name': l[0], 'strength': l[1]})
            else:
                lo.append({'name': str(l), 'strength': None})
        cfg = {
            'version': version,
            'env': env if env is not None else snapshot_env(),
            'render_kwargs': dict(render_kwargs or {}),
            'beats': _beat_records(beats),
            'beat_map': beat_map or {},
            'mask': mask_stats(mask_path, log_fn=log) if mask_path else {},
            'ref_images': [_file_facts(p, log_fn=log) for p in (ref_images or [])],
            'loras': lo,
            'final_name': final_name,
            'version_gate': gate_version_consistency(version, h.get('run_dir'), final_name),
        }
        if driver_file:
            cfg['driver'] = _file_facts(driver_file, log_fn=log)
        if extra:
            cfg['extra'] = extra
        cfg['config_gates'] = _config_gates(cfg, log_fn=log)
        for r in cfg['config_gates']['reasons']:
            log(f'[run_logbook] CONFIG GATE {h["run_key"]}: {r}')
        _emit(h, 'config', {'config': cfg}, log_fn=log)
        return cfg
    except Exception as e:
        log(f'[run_logbook] record_config failed (ignored): {e}')
        return {}


def record_stage(
    run, stage, wall_s=None, vram_mb=None, status='ok', params=None, at=None, mirror=True, log_fn=None
) -> bool:
    """One entry in the stage timeline, with wall-clock. wall_s is the cheap anomaly
    fingerprint (a stage that suddenly runs 6x slower ran on a different path).

    `at` overrides the recording clock with the stage's real one — retro ingest must
    pass it, otherwise the timeline of a run that happened yesterday reads as if every
    stage ran in the same second today.

    mirror=True also writes run_ledger.record_stage so cross-run trends see it; retro
    ingest passes mirror=False — backdated rows stamped 'now' would poison trends()."""
    log = log_fn or _log_noop
    try:
        h = _handle(run)
        ok = _emit(
            h,
            'stage',
            {
                'stage': str(stage),
                'wall_s': wall_s,
                'vram_mb': vram_mb,
                'status': str(status),
                'at': at,
                'params': params or {},
            },
            log_fn=log,
        )
        if mirror:
            try:
                from zyg_workflows import run_ledger

                run_ledger.record_stage(
                    str(stage), run_id=h.get('run_id'), wall_s=wall_s, vram_peak_mb=vram_mb, log_fn=log
                )
            except Exception as _exc:
                _zyg_log.warning('ledger record_stage mirror failed, logbook entry kept: %s', _exc)
        return ok
    except Exception as e:
        log(f'[run_logbook] record_stage failed (ignored): {e}')
        return False


def record_metrics(run, metrics, source='', log_fn=None) -> bool:
    """Numbers that moved. Flat or nested dicts; nested keys are dotted on read.

    Namespaces are a convention, not a rule, but the useful one is: verified.* for
    session/operator measurements, final.* for the delivered clip, raw.* for the
    pre-composite render, gate.* for gate scores. compare_runs diffs whatever is here."""
    log = log_fn or _log_noop
    try:
        h = _handle(run)
        return _emit(h, 'metrics', {'metrics': metrics or {}, 'source': str(source or '')}, log_fn=log)
    except Exception as e:
        log(f'[run_logbook] record_metrics failed (ignored): {e}')
        return False


def record_gates(run, gates, verdict=None, mirror=True, log_fn=None) -> bool:
    """Final gate verdicts.

    gates: {name: bool} | {name: {'ok','score','threshold','note'}} | [ {...}, ... ]
    Normalised to {name: {'ok','score','threshold','note'}} so compare_runs can flip-detect."""
    log = log_fn or _log_noop
    try:
        h = _handle(run)
        norm = {}
        items = gates.items() if isinstance(gates, dict) else enumerate(list(gates or []))
        for k, v in items:
            if isinstance(v, dict):
                name = str(v.get('check') or v.get('gate') or v.get('name') or k)
                norm[name] = {
                    'ok': bool(v.get('ok')),
                    'score': v.get('score'),
                    'threshold': v.get('threshold'),
                    'note': v.get('note') or '',
                }
            else:
                norm[str(k)] = {'ok': bool(v), 'score': None, 'threshold': None, 'note': ''}
        ok = _emit(
            h,
            'gates',
            {'gates': norm, 'verdict': verdict or {}, 'n_fail': sum(1 for g in norm.values() if not g['ok'])},
            log_fn=log,
        )
        if mirror:
            try:
                from zyg_workflows import run_ledger

                for name, g in norm.items():
                    run_ledger.record_gate(h.get('run_id'), name, g['ok'], score=g['score'], log_fn=log)
            except Exception as _exc:
                _zyg_log.warning('ledger record_gate mirror failed, logbook entry kept: %s', _exc)
        return ok
    except Exception as e:
        log(f'[run_logbook] record_gates failed (ignored): {e}')
        return False


def finish_run(run, ok=None, final_path=None, notes=None, finished=None, log_fn=None) -> bool:
    """Close the run, hash the delivered file, append the index row.

    `finished` overrides the wall clock (see start_run) — retro-ingest passes the
    original run's completion time."""
    log = log_fn or _log_noop
    try:
        h = _handle(run)
        final = _file_facts(final_path, log_fn=log) if final_path else {}
        ts, iso = _now()
        good = _emit(
            h,
            'finish',
            {'ok': None if ok is None else bool(ok), 'final': final, 'notes': notes, 'finished': finished or iso},
            log_fn=log,
        )
        _append_jsonl(
            INDEX_PATH,
            {
                'schema': SCHEMA,
                'run_key': h.get('run_key'),
                'run_id': h.get('run_id'),
                'run_dir': h.get('run_dir'),
                'ok': None if ok is None else bool(ok),
                'final': final.get('path'),
                'ts': ts,
                'ts_iso': iso,
            },
            log_fn=log,
        )
        return good
    except Exception as e:
        log(f'[run_logbook] finish_run failed (ignored): {e}')
        return False
