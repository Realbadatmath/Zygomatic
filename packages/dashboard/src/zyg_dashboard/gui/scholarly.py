#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Scholarly / crime pipeline launch seam.

Moved verbatim out of crewai_web_gui.py (2026-10-06 round-2 split). The five
collaborators the body reaches for still live on crewai_web_gui — it is the
shared namespace of the circular blueprint contract — so they are imported
inside the function, where the module is fully loaded by the time it runs.
"""

import threading
import uuid

from zyg_workflows.runtime import ams_iso as _ams_iso
from zyg_workflows.runtime import workflow_jobs as _workflow_jobs


def _start_scholarly_pipeline_internal(
    directive: str = None,
    topic: str = 'crime',
    narration_enabled: bool = True,
    visual_style: str = 'cinematic',
    user_name: str = '',
    url: str = '',
    char_id: str = '',
    model_family: str = 'sdxl',
    pipeline_options: dict | None = None,
) -> dict:
    """Start the Scholarly pipeline in a background thread. Returns job info."""
    from zyg_dashboard.crewai_web_gui import (
        _VALID_VISUAL_STYLES,
        _clear_pipeline_halt,
        _normalize_pipeline_options,
        _parse_pipeline_model_family,
        _run_scholarly_pipeline,
    )

    _clear_pipeline_halt()
    pipeline_id = str(uuid.uuid4())
    _stop_event = threading.Event()
    if visual_style not in _VALID_VISUAL_STYLES:
        visual_style = 'cinematic'
    _workflow_jobs[pipeline_id] = {
        'status': 'running',
        'pipeline_id': pipeline_id,
        'department': 'crime' if topic == 'crime' else 'scholarly',
        'scholarly_topic': topic,
        'user_name': user_name,
        'url': url,
        'started': _ams_iso(),
        'current_stage': None,
        'stages': {},
        'result': None,
        'error': None,
        'stop_event': _stop_event,
        'narration_enabled': narration_enabled,
        'visual_style': visual_style,
        'char_id': (char_id or '').strip(),
        'model_family': _parse_pipeline_model_family(model_family),
        'pipeline_options': _normalize_pipeline_options(pipeline_options),
    }
    threading.Thread(
        target=_run_scholarly_pipeline,
        args=(pipeline_id, topic, directive, narration_enabled, visual_style),
        daemon=True,
        name=f'scholarly-pipeline-{pipeline_id[:8]}',
    ).start()
    return {'job_id': pipeline_id, 'status': 'running'}


# Crime pipeline is the same as scholarly — alias so the dispatcher never gets a NameError.
_start_crime_pipeline_internal = _start_scholarly_pipeline_internal
