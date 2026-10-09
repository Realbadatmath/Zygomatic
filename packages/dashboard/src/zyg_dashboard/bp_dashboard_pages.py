# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization — extracted from crewai_web_gui.py.
# Source lines: see crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md
# Contract: this module is imported at the BOTTOM of crewai_web_gui.py, after all
# of main's globals exist; `from crewai_web_gui import X` is therefore safe here.
import os
from flask import Blueprint, jsonify, redirect, request

bp = Blueprint('dashboard_pages', __name__)

from zyg_dashboard.crewai_web_gui import _render_dashboard_tab  # noqa: E402  (late import by design, see contract above)

# `controller` lives in gui/controller.py, but that module instantiates it at import
# time and reaches back into crewai_web_gui, so it must be imported only once
# crewai_web_gui is loaded (above) — never before it.
from zyg_dashboard.gui.controller import controller  # noqa: E402


@bp.route('/error_logs')
def dashboard_error_logs_page():
    """Error Logs tab as its own URL."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'error_logs', 'error_logs', agents=controller.agents)


@bp.route('/job_status')
def dashboard_job_status_page():
    """Job Status tab as its own URL."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'job_status', 'job_status', agents=controller.agents)


@bp.route('/monitoring_ui')
def dashboard_monitoring_ui_page():
    """Monitoring UI tab as its own URL."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'monitoring_ui', 'monitoring_ui', agents=controller.agents)


@bp.route('/parameter_control')
def dashboard_parameter_control_page():
    """Parameter Control tab as its own URL."""
    return _render_dashboard_tab(
        'enhanced_dashboard.html', 'parameter_control', 'parameter_control', agents=controller.agents
    )


@bp.route('/settings')
def dashboard_settings_page():
    """Settings tab as its own URL."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'settings', 'settings', agents=controller.agents)


@bp.route('/approval_queue')
def dashboard_approval_queue_page():
    """Approval Queue tab: pending schedule requests for admin."""
    return _render_dashboard_tab(
        'enhanced_dashboard.html', 'approval_queue', 'approval_queue', agents=controller.agents
    )


@bp.route('/audit')
def dashboard_audit_page():
    """Audit tab: who changed what (Admin only)."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'audit', 'audit', agents=controller.agents)


@bp.route('/integrity_gate')
def dashboard_integrity_gate_page():
    """Integrity Gate tab: checks passed/failed, blocked reason, force override (Admin)."""
    return _render_dashboard_tab(
        'enhanced_dashboard.html', 'integrity_gate', 'integrity_gate', agents=controller.agents
    )


@bp.route('/job_lifecycle')
def dashboard_job_lifecycle_page():
    """Job Lifecycle tab: specs and runs linked to schedule requests."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'job_lifecycle', 'job_lifecycle', agents=controller.agents)


@bp.route('/metrics')
def dashboard_metrics_page():
    """Metrics tab: performance, feedback loops, agent and workflow metrics."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'metrics', 'metrics', agents=controller.agents)


@bp.route('/mechanics')
def dashboard_mechanics_page():
    """Mechanics moved into Metrics (2026-09-30) as the subtab between Test Data and
    Capabilities. The old URL is kept so bookmarks and links still land on it."""
    return redirect('/metrics?view=mechanics')


# 2026-09-27: the Asset Manager tab was removed at the operator's request. The
# /api/asset_manager/* endpoints and /asset_manager/templates_board stay — other
# callers use them; only the tab, its route and its panel are gone.


@bp.route('/publics_zero')
def dashboard_publics_zero_page():
    """Publics Zero tab: submit prompts to the pipeline via the embedded Public Zero interface."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'publics_zero', 'publics_zero', agents=controller.agents)


@bp.route('/frequency')
def dashboard_frequency_page():
    """Frequency tab: FL Studio-style waveform view of all LLMs, tools and dependencies."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'frequency', 'frequency', agents=controller.agents)


@bp.route('/benchmark')
def dashboard_benchmark_page():
    """Benchmark tab: historical pipeline performance analytics and infrastructure health checks."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'benchmark', 'benchmark', agents=controller.agents)


@bp.route('/workflows')
def dashboard_workflows_page():
    """Workflows tab: live Clipfarm pipeline Kanban board with telemetry circles."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'workflows', 'workflows', agents=controller.agents)


@bp.route('/sandbox')
def dashboard_sandbox_page():
    """Sandbox tab: dedicated skill security scanner running on port 5555."""
    return _render_dashboard_tab('enhanced_dashboard.html', 'sandbox', 'sandbox', agents=controller.agents)


@bp.route('/api/zero-admin-url')
def zero_admin_url():
    """Return the admin-bypass URL for the Public Zero server (port 5001). Login required."""
    token = os.environ.get('ZERO_PUBLIC_TOKEN', '')
    host = request.host.split(':')[0]
    port = int(os.environ.get('ZERO_PUBLIC_PORT', 5001))
    url = f'http://{host}:{port}/admin-enter?t={token}'
    return jsonify({'url': url})
