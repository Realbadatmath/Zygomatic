# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Running one stage agent, and the preflight agent-activity markers."""

try:
    from crewai import Crew, Process, Task
except ImportError:  # crewai is optional: importing this module must never need it
    Crew = Process = Task = None
from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL
from zyg_workflows.runtime import _agent_log
from zyg_workflows.runtime import _ams_iso
from zyg_workflows.runtime import _ams_now
from zyg_workflows.runtime import _ollama_semaphore
from zyg_workflows.vram_manager import _wait_ollama_unload
from zyg_workflows.runtime import workflow_jobs as _workflow_jobs
from zyg_workflows import gui_state
from zyg_workflows import http_json
from zyg_workflows import runtime

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


def _run_stage_agent(agent_id: str, task_desc: str, pipeline_id: str, stage_name: str) -> dict:
    """Run a single agent as its own crew. Called from thread pool for parallel stages."""
    pass  # (global stmt removed: names moved to gui_state)
    if Crew is None or Process is None or Task is None:
        raise RuntimeError('crewai is not installed: _run_stage_agent needs crewai.Crew/Process/Task to run an agent')
    _t_start = _ams_now()
    _agent_log('INFO', agent_id, pipeline_id, stage_name, 'Agent awakened — checking gates')

    # Manual stop gate
    if gui_state._pipeline_stop_flag:
        _agent_log('WARNING', agent_id, pipeline_id, stage_name, 'Stopped by user before execution')
        job = _workflow_jobs.get(pipeline_id, {})
        job.get('stages', {}).setdefault(stage_name, {})[agent_id] = {
            'status': 'stopped',
            'reason': 'Manual stop by user',
        }
        return {'status': 'stopped', 'agent': agent_id, 'error': 'Stopped by user'}

    # Hardware safety gate — pause up to 120s waiting for recovery, then abort
    if gui_state._hw_block_active:
        _agent_log(
            'WARNING',
            agent_id,
            pipeline_id,
            stage_name,
            f'Hardware block active — waiting up to 120s: {gui_state._hw_block_reason}',
        )
        import time as _t

        waited = 0
        while gui_state._hw_block_active and waited < 120:
            _t.sleep(5)
            waited += 5
        if gui_state._hw_block_active:
            _agent_log(
                'ERROR',
                agent_id,
                pipeline_id,
                stage_name,
                f'Hardware block unresolved after 120s — agent aborted: {gui_state._hw_block_reason}',
            )
            return {
                'status': 'blocked',
                'agent': agent_id,
                'error': f'Hardware block — pipeline halted: {gui_state._hw_block_reason}',
            }
        _agent_log('INFO', agent_id, pipeline_id, stage_name, f'Hardware block lifted after {waited}s — proceeding')

    job = _workflow_jobs[pipeline_id]
    stage_status = job['stages'].setdefault(stage_name, {})
    stage_status[agent_id] = {'status': 'running', 'started': _t_start.isoformat(timespec='milliseconds')}

    try:
        # Read through the module: the dashboard registers the real controller at
        # boot, and a from-import would have bound the headless None for good.
        _controller = runtime.controller
        agent = _controller.agents.get(agent_id) if _controller is not None else None
        if agent is None or type(agent).__name__ == 'MockAgent':
            _agent_log(
                'WARNING', agent_id, pipeline_id, stage_name, 'Agent not available (missing or mock mode) — skipped'
            )
            stage_status[agent_id] = {'status': 'skipped', 'reason': 'agent not available'}
            return {'status': 'skipped', 'agent': agent_id}

        _agent_log('INFO', agent_id, pipeline_id, stage_name, 'Waiting for Ollama semaphore slot')
        task = Task(
            description=task_desc,
            agent=agent,
            expected_output=f'Completion report from {agent_id}: what was done, key outputs, any blockers.',
        )
        crew = Crew(agents=[agent], tasks=[task], verbose=True, process=Process.sequential)
        with _ollama_semaphore:
            _agent_log('INFO', agent_id, pipeline_id, stage_name, 'Semaphore acquired — calling LLM')
            result = crew.kickoff()
        _agent_log('INFO', agent_id, pipeline_id, stage_name, 'Semaphore released')
        _elapsed = round((_ams_now() - _t_start).total_seconds(), 1)
        result_snippet = str(result)[:300]
        stage_status[agent_id] = {'status': 'completed', 'result': result_snippet}
        _agent_log(
            'INFO', agent_id, pipeline_id, stage_name, f'Completed in {_elapsed}s', {'result_snippet': result_snippet}
        )

        # Release Ollama VRAM immediately after each agent finishes
        try:
            _ps = http_json.request_json(_OLLAMA_BASE_URL + '/api/ps', timeout=5)
            _unloaded = []
            for _loaded in _ps.get('models', []):
                _mname = _loaded.get('name', '')
                if not _mname:
                    continue
                http_json.post_json(
                    _OLLAMA_BASE_URL + '/api/generate',
                    {'model': _mname, 'prompt': ' ', 'keep_alive': 0, 'stream': False},
                    timeout=30,
                )
                _wait_ollama_unload(_mname, timeout=30)  # confirm evicted before releasing semaphore
                _unloaded.append(_mname)
            if _unloaded:
                _agent_log('INFO', agent_id, pipeline_id, stage_name, f'VRAM released — unloaded models: {_unloaded}')
        except Exception as _exc:
            _zyg_log.warning('ollama model eviction failed, vram may stay held: %s', _exc)

        return {'status': 'completed', 'agent': agent_id, 'result': result_snippet}

    except Exception as exc:
        _elapsed = round((_ams_now() - _t_start).total_seconds(), 1)
        import traceback as _tb

        _agent_log(
            'ERROR',
            agent_id,
            pipeline_id,
            stage_name,
            f'FAILED after {_elapsed}s: {exc}',
            {'traceback': _tb.format_exc()[-800:]},
        )
        stage_status[agent_id] = {'status': 'failed', 'error': str(exc)}
        return {'status': 'failed', 'agent': agent_id, 'error': str(exc)}


def _pf_agents_active(pipeline_id: str, stage_name: str, agent_ids: list):
    """Mark agents as 'running' in the workflow job so the chart overlay lights them up during preflight."""
    job = _workflow_jobs.get(pipeline_id)
    if not job:
        return
    stage = job['stages'].setdefault(stage_name, {})
    for aid in agent_ids:
        stage[aid] = {'status': 'running', 'started': _ams_iso()}


def _pf_agents_done(pipeline_id: str, stage_name: str, agent_ids: list):
    """Mark agents as 'completed' after preflight work finishes."""
    job = _workflow_jobs.get(pipeline_id)
    if not job:
        return
    stage = job['stages'].setdefault(stage_name, {})
    for aid in agent_ids:
        if aid in stage and isinstance(stage[aid], dict):
            stage[aid]['status'] = 'completed'
            stage[aid]['ended'] = _ams_iso()
