# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The preflight entry point: shared state/log helpers and the stage dispatch."""

import json
from zyg_workflows.runtime import _agent_log
from zyg_workflows.stage_runner.stage1 import _pf_stage_1
from zyg_workflows.stage_runner.stage3 import _pf_stage_3
from zyg_workflows.stage_runner.stage4a import _pf_stage_4a
from zyg_workflows.stage_runner.stage4b import _pf_stage_4b

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _stage_preflight(stage_name: str, state_file: str, state: dict):
    """
    Run critical tools directly in Python BEFORE the LLM agent executes.
    This guarantees real data (video URLs, downloaded file paths) is written
    to the state file so the agent reasons over actual results, not hallucinations.
    """

    def _save(s):
        try:
            with open(state_file, 'w') as _f:
                json.dump(s, _f, indent=2)
        except Exception as _se:
            _zyg_log.info(f'[PREFLIGHT _save ERROR] {state_file}: {_se}')
            _agent_log(
                'ERROR', 'PREFLIGHT', state.get('pipeline_id', 'unknown'), 'state_save', f'Failed to save state: {_se}'
            )

    pipeline_id = state.get('pipeline_id', 'unknown')

    def _log_err(stage, err):
        msg = f'[PREFLIGHT ERROR] {stage}: {err}'
        _zyg_log.info(msg)
        state.setdefault('preflight_errors', []).append(msg)
        _save(state)
        _agent_log('ERROR', 'PREFLIGHT', pipeline_id, stage_name, msg)

    def _log_warn(msg):
        _zyg_log.info(f'[PREFLIGHT WARN] {stage_name}: {msg}')
        _agent_log('WARNING', 'PREFLIGHT', pipeline_id, stage_name, msg)

    def _log_info(msg):
        _zyg_log.info(f'[PREFLIGHT] {stage_name}: {msg}')
        _agent_log('INFO', 'PREFLIGHT', pipeline_id, stage_name, msg)

    if 'Stage 1' in stage_name:
        _pf_stage_1(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info)
    elif 'Stage 3' in stage_name:
        _pf_stage_3(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info)
    elif 'Stage 4a' in stage_name:
        _pf_stage_4a(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info)
    elif 'Stage 4b' in stage_name:
        _pf_stage_4b(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info)
