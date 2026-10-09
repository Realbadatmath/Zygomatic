"""The run scaffold of the scholarly pipeline — what is left of the monolith.

The first three tasks of the split moved the nineteen `# ── Stage N …` markers of
`_run_scholarly_pipeline` into `stages_01_18`, `stages_19_36` and `stages_37_54`.
What stayed behind was not a stage: it was the **scaffold** the stages run
inside — the eleven nested helpers every stage calls through `ctx`, the
code-staleness gate, and the three exit paths of the `try/except/except/finally`
around the stage list. 623 lines of it, which is more than the 300-line ceiling
this file's gate puts on the monolith, so it moves here.

Nothing in this module is a `# ── Stage N …` block, and the stage numbers in the
names are positions in the run, not markers (there never were 73 of those — see
SPLIT_LOG.md, "The stage count is 19, not 73"). They are numbered 55-73 because
that is the module the brief chain names, and 55/56 run before stage 1 while
71/72/73 run after stage 19:

* `stage_55_run_glue` — the factory for the eleven helpers. It is a factory and
  not eleven module-level functions because they are **closures**: `_log` writes
  the job's `debug_events` ring, `_save` writes `state_file`, `_gate_receipt`
  writes `_gate_receipts` and calls `_log`. Building them inside one function
  keeps every one of those bindings the object it was in the monolith, which is
  what makes the move pure — a stage calls the very same `_log` it called before.
* `stage_56_staleness_gate` — the "this process imported the module before the
  edits" warning.
* `stage_71_on_user_stop` / `stage_72_on_error` / `stage_73_finalise` — the
  bodies of `except StopIteration:`, `except Exception:` and `finally:`.

The glue object is a `RunGlue`, not a `RunContext`: `RunContext` carries what
crosses a *stage* boundary, this carries what the scaffold and the monolith
share. The monolith unpacks it into the same plain locals the names had, so the
statements that stayed (the `RunContext(...)` construction, the stage list) read
exactly as they did.

See SPLIT_LOG.md, "Task 4 of 4".
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
from dataclasses import dataclass, field
from typing import Any

from zyg_workflows import gui_state
from zyg_workflows.net import safe_urlopen
from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL
from zyg_workflows.runtime import _agent_log, _ams_iso, _parse_iso_to_ams, _push_error_log
from zyg_workflows.subproc_registry import _update_marker
from zyg_workflows.vram_manager import _release_pipeline_vram

# Same logger name the statements had in pipeline_scholarly, so a run's
# diagnostics keep landing under one name.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')

# Every quality gate below must file a receipt saying whether it RAN and, when
# it did not, why. This exists because Stage 3.7 Hand QC spent an entire release
# cycle nested inside `if not _sch_fw_active:` — a branch that
# ZYG_SCHOLARLY_FLUX_PERSISTENT=1 makes permanently false — and so produced no
# stage, no log line and no state key. There was nothing to notice. A gate that
# reports "0 checked, 61 unavailable" is honest and monitorable; a gate that
# emits NOTHING is indistinguishable from a gate that passed, which is the
# failure mode this contract removes.
#
# The audit at the end of the run names any expected gate that filed no receipt
# at all, so an unreachable gate announces itself instead of having to be
# discovered by reading the source.
_GATES_EXPECTED = ('hand_qc', 'typography', 'retry_ladder', 'era')


@dataclass
class RunGlue:
    """The scaffold's eleven helpers and the two mutable registries they own."""

    job: dict[str, Any] = field(default_factory=dict)
    pipeline_state: dict[str, Any] = field(default_factory=dict)
    pipeline_id: str = ''
    state_file: str = ''
    _gate_receipts: dict[str, Any] = field(default_factory=dict)
    _stop_event_scholarly: Any = None
    _log: Any = None
    _save: Any = None
    _debug: Any = None
    _done: Any = None
    _stage_start: Any = None
    _should_stop: Any = None
    _assert_not_stopped: Any = None
    _gate_receipt: Any = None
    _flux_lever_guard: Any = None
    _gate_receipts_audit: Any = None


def _trim_events(events, cap):
    """Cap the shared debug_events ring WITHOUT dropping warnings.

    _log() and _debug() append to one list, and _debug() (per-slot murch,
    filmlook and xfade chatter — 200+ events on a 41-slot film) used to drive a
    plain del-events[0] trim. On the Sikh Empire run that evicted everything
    before 12:32, so Stage 3's fact-check WARNINGs — six unverifiable claims,
    one contradicting sources — were gone from the persisted state by the time
    the run finished, and the film looked warning-free. Evict the oldest DEBUG
    first, then the oldest INFO, and only start dropping warnings if the ring is
    somehow all warnings.
    """
    if len(events) <= cap:
        return
    _over = len(events) - cap
    _drop = set()
    # Oldest-first within each tier: DEBUG is sacrificed before INFO, and
    # warnings only once nothing else is left.
    for _lvls in (('DEBUG',), ('INFO',), None):
        for _i, _e in enumerate(events):
            if len(_drop) >= _over:
                break
            if _i in _drop:
                continue
            if _lvls is None or str(_e.get('level', '')).upper() in _lvls:
                _drop.add(_i)
        if len(_drop) >= _over:
            break
    events[:] = [_e for _i, _e in enumerate(events) if _i not in _drop]


def stage_55_run_glue(job, pipeline_state, pipeline_id, state_file):
    """Build the eleven helpers every stage reaches through `ctx`.

    One factory rather than eleven module-level functions, because they are
    closures over `job`, `pipeline_state`, `state_file` and the two registries —
    see the module docstring.
    """
    _gate_receipts: dict = {}
    _lever_guard_done: set = set()
    _stop_event_scholarly = job.get('stop_event')

    def _save():
        try:
            # Always persist current debug_events so live tail survives a restart
            pipeline_state['debug_events'] = job.get('debug_events', [])
            with open(state_file, 'w') as _f:
                json.dump(pipeline_state, _f, indent=2)
        except OSError as _exc:
            _zyg_log.warning('state file %s not written, the live tail will lag: %s', state_file, _exc)
        except TypeError as _exc:
            _zyg_log.warning('pipeline_state holds a value json cannot encode, state not saved: %s', _exc)

    def _log(level, stage, msg):
        from zoneinfo import ZoneInfo as _ZI

        _ams = _ZI('Europe/Amsterdam')
        # Keep the audit context in step with the stage the pipeline reports,
        # so every LLM call the SDK wrapper captures lands under the right
        # stage without each call site having to pass one.
        try:
            from zyg_workflows import llm_audit as _la_log

            _la_log.set_context(stage=stage)
        except Exception as _exc:  # noqa: BLE001 — the audit sink is optional
            _zyg_log.debug('llm_audit stage context not set, this call logs under the previous stage: %s', _exc)
        _zyg_log.info(f'[SCHOLARLY-{level}] {stage}: {msg}')
        _agent_log(level, 'SCHOLARLY-PIPELINE', pipeline_id, stage, msg)
        _push_error_log(level, stage, msg, pipeline_id)
        ev = {
            'ts': _ams_iso(),
            'level': level,
            'stage': stage,
            'msg': str(msg)[:400],
        }
        events = job.setdefault('debug_events', [])
        events.append(ev)
        _trim_events(events, 1000)

    def _done(stage, extra=None):
        now = _ams_iso()
        d = {'status': 'completed'}
        if extra:
            d.update(extra)
        job['stages'][stage] = d

        # ── Stage timeline tracking ───────────────────────────────────────
        tl = job.setdefault('stage_timeline', [])
        for entry in tl:
            if entry['name'] == stage and entry['status'] == 'running':
                entry['status'] = 'completed'
                entry['ended_at'] = now
                if entry.get('started_at'):
                    try:
                        _end_dt = _parse_iso_to_ams(now)
                        _start_dt = _parse_iso_to_ams(entry['started_at'])
                        if _end_dt and _start_dt:
                            entry['elapsed_s'] = round((_end_dt - _start_dt).total_seconds(), 1)
                    except (TypeError, ValueError) as _exc:
                        _zyg_log.debug('stage %s keeps no elapsed_s, its timestamps did not parse: %s', stage, _exc)
                if extra:
                    entry['extra'] = {k: v for k, v in extra.items() if not isinstance(v, (dict, list))}
                return
        tl.append(
            {
                'name': stage,
                'status': 'completed',
                'started_at': now,
                'ended_at': now,
                'elapsed_s': 0.0,
                'extra': {k: v for k, v in (extra or {}).items() if not isinstance(v, (dict, list))},
            }
        )

    def _stage_start(stage):
        """Record stage start time in the timeline (call before doing work)."""
        now = _ams_iso()
        tl = job.setdefault('stage_timeline', [])
        for entry in tl:
            if entry['name'] == stage:
                return
        tl.append(
            {
                'name': stage,
                'status': 'running',
                'started_at': now,
                'ended_at': None,
                'elapsed_s': None,
                'extra': {},
            }
        )

    def _debug(stage, msg, level='DEBUG'):
        """Record a traceable debug event (up to 500 per pipeline)."""
        ev = {
            'ts': _ams_iso(),
            'level': level,
            'stage': stage,
            'msg': str(msg)[:400],
        }
        events = job.setdefault('debug_events', [])
        events.append(ev)
        # Same ring as _log(); trim at the same ceiling so the chattier of the
        # two writers cannot evict the other's warnings (see _trim_events).
        _trim_events(events, 1000)
        _agent_log('DEBUG', 'SCHOLARLY-PIPELINE', pipeline_id, stage, msg)

    def _gate_receipt(name, ran, reason='', stats=None):
        """File a gate's run/skip receipt. Call it on EVERY exit path."""
        rec = {
            'gate': str(name),
            'ran': bool(ran),
            'reason': str(reason or '')[:200],
            'stats': dict(stats or {}),
            'ts': _ams_iso(),
        }
        _gate_receipts[str(name)] = rec
        pipeline_state['gate_receipts'] = dict(_gate_receipts)
        if ran:
            _log('INFO', 'Gates', f'{name}: RAN — {rec["stats"] or "no stats"}')
        else:
            _log('WARNING', 'Gates', f'{name}: DID NOT RUN — {rec["reason"] or "no reason given"}')
        return rec

    def _flux_lever_guard(pipe_obj, neg_prompt, scale, kwargs):
        """Warn once when a generation parameter will be silently discarded.

        Passing a parameter the model ignores looks exactly like passing one
        that works: same call, same log line, same absence of an error. The
        retry ladder spent its whole life raising guidance_scale to 3.5 and
        attaching a negative prompt, describing both as the active lever, while
        FLUX.1-schnell discarded both — guidance because the transformer config
        sets guidance_embeds=False, negatives because diffusers applies them
        only when true_cfg_scale > 1 and nothing ever passed it. Verified by
        rendering one seed four ways: three bit-identical PNGs, one different.

        This does not change behaviour. It just refuses to let the next such
        parameter go unnoticed.
        """
        try:
            _t_cfg = getattr(getattr(pipe_obj, 'transformer', None), 'config', None)
            _embeds = getattr(_t_cfg, 'guidance_embeds', None)
            if _embeds is False and float(scale or 0.0) > 0.01 and 'guidance' not in _lever_guard_done:
                _lever_guard_done.add('guidance')
                _log(
                    'WARNING',
                    'Stage 3.5',
                    f'INERT LEVER — guidance_scale={scale} is being passed to a '
                    f'model with guidance_embeds=False; diffusers discards it. '
                    f'Any retry rung that treats guidance as its remedy is a '
                    f'no-op. Use positive prompt phrasing instead.',
                )
            if neg_prompt and float(kwargs.get('true_cfg_scale', 1.0)) <= 1.0:
                # Drop it rather than pass it. diffusers would discard it anyway
                # (`do_true_cfg = true_cfg_scale > 1 and has_neg_prompt`), and a
                # kwarg that is accepted-then-ignored is precisely what made the
                # ladder's negatives look active for so long. Removing it keeps
                # the call honest: what is passed is what is used.
                kwargs.pop('negative_prompt', None)
                if 'negative' not in _lever_guard_done:
                    _lever_guard_done.add('negative')
                    _log(
                        'INFO',
                        'Stage 3.5',
                        f'negative_prompt dropped ({len(str(neg_prompt))} chars): '
                        f'diffusers applies it only at true_cfg_scale>1, which '
                        f'costs 2x compute and visibly degrades a 4-step '
                        f'distilled model. Suppression is done with positive '
                        f'phrasing in the prompt instead.',
                    )
        except (AttributeError, TypeError, ValueError) as _exc:
            # The guard inspects a third-party pipeline object; a diffusers
            # release that reshapes transformer.config must not fail the run.
            _zyg_log.debug('inert-lever guard could not inspect the pipeline, no warning filed: %s', _exc)

    def _gate_receipts_audit():
        """Name every expected gate that filed no receipt at all."""
        _missing = [_g for _g in _GATES_EXPECTED if _g not in _gate_receipts]
        _skipped = [_r['gate'] for _r in _gate_receipts.values() if not _r['ran']]
        pipeline_state['gate_audit'] = {
            'expected': list(_GATES_EXPECTED),
            'filed': sorted(_gate_receipts),
            'missing': _missing,
            'skipped': _skipped,
        }
        if _missing:
            _log(
                'WARNING',
                'Gates',
                f'GATE AUDIT — {len(_missing)} gate(s) filed NO receipt at all: '
                f'{", ".join(_missing)}. Pre-registration should make this '
                f'impossible, so it means the registry and the gates disagree — '
                f'a wiring defect, not a quality result.',
            )
        elif _skipped:
            _log(
                'WARNING',
                'Gates',
                f'GATE AUDIT — every gate reported in; {len(_skipped)} skipped: {", ".join(_skipped)}',
            )
        else:
            _log(
                'INFO',
                'Gates',
                f'GATE AUDIT — all {len(_GATES_EXPECTED)} gates ran: {", ".join(sorted(_gate_receipts))}',
            )
        return _missing

    def _should_stop():
        """Return True if a stop has been requested via flag or event."""
        if gui_state._pipeline_stop_flag:
            return True
        if _stop_event_scholarly and _stop_event_scholarly.is_set():
            return True
        return False

    def _assert_not_stopped(stage_name):
        """Raise StopIteration (caught by pipeline try/except) if stop was requested."""
        if _should_stop():
            _stop_flag_val = gui_state._pipeline_stop_flag
            _stop_ev_val = _stop_event_scholarly.is_set() if _stop_event_scholarly else False
            _log(
                'INFO',
                stage_name,
                f'⛔ Pipeline stopped by user request [stop_flag={_stop_flag_val}, stop_event={_stop_ev_val}]',
            )
            job['status'] = 'stopped'
            job['error'] = 'Stopped by user'
            raise StopIteration('user_stop')

    # Pre-register every expected gate as NOT RUN before anything can skip it.
    # Without this, a gate that is never reached files nothing, and "no receipt"
    # has to be distinguished from "no gate" by reading the source — which is
    # the exact archaeology that let Stage 3.7 sit unreachable for a release.
    # Pre-registered, the run always carries one line per gate, and a gate that
    # never executed says so in its own words.
    for _g_name in _GATES_EXPECTED:
        _gate_receipts[_g_name] = {
            'gate': _g_name,
            'ran': False,
            'reason': 'pipeline never reached this gate',
            'stats': {},
            'ts': _ams_iso(),
        }
    pipeline_state['gate_receipts'] = dict(_gate_receipts)

    return RunGlue(
        job=job,
        pipeline_state=pipeline_state,
        pipeline_id=pipeline_id,
        state_file=state_file,
        _gate_receipts=_gate_receipts,
        _stop_event_scholarly=_stop_event_scholarly,
        _log=_log,
        _save=_save,
        _debug=_debug,
        _done=_done,
        _stage_start=_stage_start,
        _should_stop=_should_stop,
        _assert_not_stopped=_assert_not_stopped,
        _gate_receipt=_gate_receipt,
        _flux_lever_guard=_flux_lever_guard,
        _gate_receipts_audit=_gate_receipts_audit,
    )


def stage_56_staleness_gate(glue, source_file, imported_at):
    """Say up front when this process is running pre-edit code.

    A running pipeline holds the module it imported at start, so edits made
    after the GUI booted are NOT in this run. That silently invalidated a whole
    validation round: the module loaded at 13:30, the fixes landed at 13:48, and
    the 14:00 run exercised the OLD ladder while appearing to test the new one.
    Compare the source's mtime on disk against the moment it was imported and
    say so, so a stale run is never mistaken for a passing one.
    """
    try:
        _src_mtime = os.path.getmtime(source_file)
        if _src_mtime > imported_at:
            glue._log(
                'WARNING',
                'Startup',
                f'STALE CODE — pipeline_scholarly.py was modified '
                f'{(_src_mtime - imported_at) / 60.0:.1f} min AFTER this '
                f'process imported it. This run executes the OLD module; restart '
                f'the GUI before treating its result as a test of the new code.',
            )
            glue.pipeline_state['stale_code'] = True
        else:
            glue.pipeline_state['stale_code'] = False
    except OSError as _exc:
        # The module file is gone or unreadable (an editor rename mid-run). The
        # run is fine; only the staleness verdict is unavailable, and recording
        # no verdict is the honest answer.
        _zyg_log.warning('staleness gate could not stat %s, this run files no verdict: %s', source_file, _exc)


def _evict_ollama_models(glue, why):
    """Free the VRAM every loaded Ollama model holds, synchronously.

    `/api/generate` with `keep_alive: 0` is the only synchronous eviction the
    API offers, and it needs a (blank) prompt field to be accepted.
    """
    try:
        _ps = json.loads(safe_urlopen(_OLLAMA_BASE_URL + '/api/ps', timeout=5).read())
        for _m in _ps.get('models', []):
            _mn = _m.get('name', '')
            if _mn:
                _mp = json.dumps({'model': _mn, 'prompt': ' ', 'keep_alive': 0, 'stream': False}).encode()
                safe_urlopen(_OLLAMA_BASE_URL + '/api/generate', data=_mp, timeout=30)
                glue._log('INFO', 'PIPELINE', f'Ollama evicted {_mn} on {why} — VRAM freed')
    except Exception as _exc:  # noqa: BLE001 — urllib, socket, json and Ollama's own errors
        glue._log(
            'WARNING',
            'Cleanup',
            f'Ollama eviction on {why} failed; its models keep their VRAM until the daemon times them out: {_exc!r}',
        )


def stage_71_on_user_stop(glue, pipeline_marker):
    """The body of `except StopIteration:` — a clean stop, not an error."""
    job = glue.job
    pipeline_state = glue.pipeline_state
    _log = glue._log
    job['status'] = 'stopped'
    job['ended'] = _ams_iso()
    job['error'] = 'Stopped by user'
    job['current_stage'] = None
    for entry in job.get('stage_timeline', []):
        if entry.get('status') == 'running':
            entry['status'] = 'stopped'
            entry['ended_at'] = job['ended']
    pipeline_state['stage_timeline'] = job.get('stage_timeline', [])
    pipeline_state['ended'] = job['ended']
    glue._save()
    gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
    _update_marker(pipeline_marker, status='stopped', label=f'⛔ Scholarly {glue.pipeline_id[:8]} — Stopped by user')
    _log('INFO', 'PIPELINE', 'Scholarly pipeline stopped by user request')
    _evict_ollama_models(glue, 'stop')


def stage_72_on_error(glue, pipeline_marker, exc):
    """The body of `except Exception as exc:` — record, mark, evict."""
    import traceback as _tb_sch

    job = glue.job
    pipeline_state = glue.pipeline_state
    _log = glue._log
    job['status'] = 'failed'
    job['ended'] = _ams_iso()
    job['error'] = str(exc)
    job['error_traceback'] = _tb_sch.format_exc()
    job['current_stage'] = None
    # Mark any running stage as failed in timeline
    for entry in job.get('stage_timeline', []):
        if entry.get('status') == 'running':
            entry['status'] = 'failed'
            entry['ended_at'] = job['ended']
    pipeline_state['stage_timeline'] = job.get('stage_timeline', [])
    pipeline_state['debug_events'] = job.get('debug_events', [])
    pipeline_state['ended'] = job['ended']
    glue._save()
    gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
    _update_marker(
        pipeline_marker, status='error', label=f'❌ Scholarly {glue.pipeline_id[:8]} — failed: {str(exc)[:60]}'
    )
    _log('ERROR', 'PIPELINE', f'Scholarly pipeline failed: {exc}\n{_tb_sch.format_exc()}')
    _evict_ollama_models(glue, 'error')


def stage_73_finalise(glue, pbank, preempt_token):
    """The body of `finally:` — preempt stats, the gate audit, the VRAM release.

    Runs on EVERY exit path, success or failure. A gate that never executed is a
    wiring defect and has to be visible in the same place a quality result would
    be, or the next run repeats it.
    """
    job = glue.job
    pipeline_state = glue.pipeline_state
    _log = glue._log
    if pbank is not None:
        try:
            _pctx_fin = pbank.current()
            if _pctx_fin:
                job['preempt_stats'] = {k: _pctx_fin.get(k) for k in ('hits', 'misses', 'live', 'refused', 'recorded')}
                pipeline_state['preempt_stats'] = job['preempt_stats']
            pbank.clear_context(preempt_token)
        except Exception as _exc:  # noqa: BLE001 — the bank is a dashboard feature
            _log('WARNING', 'PIPELINE', f'pre-emptive bank context not closed, this run files no bank stats: {_exc!r}')
    try:
        glue._gate_receipts_audit()
        pipeline_state['ladder_stats'] = dict(glue._gate_receipts.get('retry_ladder', {}).get('stats', {}))
        glue._save()
    except Exception as _ga_e:  # noqa: BLE001 — the audit must never mask the run's own error
        _log('WARNING', 'Gates', f'Gate audit failed: {_ga_e!r}')
    _release_pipeline_vram('post-pipeline', lambda m: _log('INFO', 'Cleanup', m))
