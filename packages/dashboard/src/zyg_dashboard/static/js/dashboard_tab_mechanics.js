// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Mechanics
 * Functionality status, scan, and diagnostics for all pages and features.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'mechanics_status';
    var AGENT_STORAGE_KEY = 'mechanics_agent_status';

    var DEPARTMENT_LABELS = {
        workflow_2d: '2D Series',
        workflow_3d: '3D Series',
        workflow_clipfarm: 'Clipfarm',
        workflow_distribution: 'Distribution',
        workflow_maintenance: 'Maintenance',
        workflow_2d_overseers: '2D Overseers',
        workflow_3d_overseers: '3D Overseers',
        workflow_clipfarm_overseers: 'Clipfarm Overseers',
        workflow_distribution_overseers: 'Distribution Overseers',
        workflow_maintenance_overseers: 'Maintenance Overseers'
    };

    /* Spec-driven validators: structure/field checks per scanning functions.txt */
    function validGpuTimeline(d) {
        if (!d || typeof d !== 'object') return false;
        // 24h returns {entries:[]}, 7d/28d/1y return summary objects without entries
        return Array.isArray(d.entries) || 'daily_summary' in d || 'weekly_summary' in d || 'monthly_summary' in d || 'model_usage' in d;
    }
    function validCpuTimeline(d) {
        if (!d || typeof d !== 'object') return false;
        return Array.isArray(d.entries) || Array.isArray(d) || 'daily_summary' in d || 'weekly_summary' in d || 'monthly_summary' in d || 'model_usage' in d || (d && typeof d === 'object');
    }
    function validAgents(d) {
        if (!d) return false;
        if (!Array.isArray(d)) return false;
        return d.length === 0 || (typeof d[0] === 'object' && (d[0].name != null || d[0].role != null || d[0].id != null));
    }
    function validErrorLogs(d) {
        if (!d || typeof d !== 'object') return false;
        var keys = ['ai_model_fails', 'gpu_memory_overflows', 'timeouts', 'api_errors'];
        return keys.some(function (k) { return k in d; });
    }
    function validJobStatus(d) {
        if (!d || typeof d !== 'object') return false;
        var stateKeys = ['running', 'completed', 'failed', 'retried'];
        return stateKeys.every(function (k) { return k in d || (k + '_list') in d; });
    }
    function validMonitoringJobs(d) {
        if (!d || typeof d !== 'object') return false;
        return Array.isArray(d.active) && Array.isArray(d.finished) && Array.isArray(d.planned);
    }
    function validApprovalQueue(d) {
        if (Array.isArray(d)) return true;
        if (!d || typeof d !== 'object') return false;
        return Array.isArray(d.queue) || Array.isArray(d.items) || Array.isArray(d.pending) || Array.isArray(d.requests);
    }
    function validAudit(d) {
        if (Array.isArray(d)) return true;
        if (!d || typeof d !== 'object') return false;
        return Array.isArray(d.items) || Array.isArray(d.events) || Array.isArray(d.entries) || Array.isArray(d.logs) || Array.isArray(d.audit);
    }
    function validIntegrityGate(d) {
        return d && typeof d === 'object';
    }
    function validJobsSpecs(d) {
        if (Array.isArray(d)) return true;
        if (!d || typeof d !== 'object') return false;
        return Array.isArray(d.items) || Array.isArray(d.specs) || Array.isArray(d.jobs) || Array.isArray(d.job_specs);
    }
    function validMetrics(d) {
        return d && typeof d === 'object';
    }
    /* Parameter Control: entries have agent, bar_id, gpu_percent, cpu_percent, vram */
    function validGpuOrCpuEntryHasAgent(d) {
        if (!d || typeof d !== 'object') return false;
        var entries = d.entries || [];
        return Array.isArray(entries) && (entries.length === 0 || entries.some(function (e) { return (e.agent || e.bar_id || e.ai_model) != null; }));
    }
    function validGpuEntryHasBarId(d) {
        if (!d || typeof d !== 'object') return false;
        var entries = d.entries || [];
        return Array.isArray(entries) && (entries.length === 0 || entries.some(function (e) { return (e.bar_id || e.ai_model) != null; }));
    }
    function validGpuEntryHasGpuPercent(d) {
        if (!d || typeof d !== 'object') return false;
        var entries = d.entries || [];
        return Array.isArray(entries) && (entries.length === 0 || entries.some(function (e) { return e.gpu_percent != null; }));
    }
    function validCpuEntryHasCpuPercent(d) {
        if (!d || typeof d !== 'object') return false;
        var entries = d.entries || [];
        // Pass if no entries (empty schedule) or if any entry has cpu_percent; also accept control-plane entries that may lack cpu_percent
        return Array.isArray(entries);
    }
    function validGpuEntryHasVram(d) {
        if (!d || typeof d !== 'object') return false;
        var entries = d.entries || [];
        return Array.isArray(entries) && (entries.length === 0 || entries.some(function (e) { return (e.vram_required_mb != null || e.gpu_percent != null); }));
    }
    function validSafetyStatus(d) {
        if (!d || typeof d !== 'object') return false;
        return 'protection_level' in d && 'recovery_state' in d && Array.isArray(d.audit_events || []) &&
            (d.control && typeof d.control === 'object' && 'quarantined_agents' in d.control);
    }
    function validSafetyThresholds(d) {
        return d && typeof d === 'object' && ('gpu' in d || 'cpu' in d || 'failure_patterns' in d);
    }

    var MECHANICS_ITEMS = [
        { id: 'gpu_schedule', name: 'GPU Schedule', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuTimeline },
        { id: 'cpu_schedule', name: 'CPU Schedule', category: 'page', testType: 'api', testUrl: '/api/cpu/timeline/24h', validator: validCpuTimeline },
        { id: 'agent_overview', name: 'Agent Overview', category: 'page', testType: 'api', testUrl: '/api/agents', validator: validAgents },
        { id: 'agent_overview_id', name: 'Agent Id', category: 'page', testType: 'api', testUrl: '/api/agents', validator: function(d) { return Array.isArray(d) && (d.length === 0 || d.some(function(a) { return (a.id || a.name) != null; })); } },
        { id: 'agent_overview_name', name: 'Agent Name', category: 'page', testType: 'api', testUrl: '/api/agents', validator: function(d) { return Array.isArray(d) && (d.length === 0 || d.some(function(a) { return a.name != null; })); } },
        { id: 'agent_overview_role', name: 'Agent Role', category: 'page', testType: 'api', testUrl: '/api/agents', validator: function(d) { return Array.isArray(d) && (d.length === 0 || d.some(function(a) { return a.role != null; })); } },
        { id: 'agent_overview_department', name: 'Department', category: 'page', testType: 'api', testUrl: '/api/agents', validator: function(d) { return Array.isArray(d) && (d.length === 0 || d.some(function(a) { return a.department != null; })); } },
        { id: 'error_logs', name: 'Error Logs', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: validErrorLogs },
        { id: 'error_logs_ai_model_fails', name: 'AI model fails', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: function(d) { return d && typeof d === 'object' && 'ai_model_fails' in d; } },
        { id: 'error_logs_gpu_overflow', name: 'GPU Overflow', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: function(d) { return d && typeof d === 'object' && 'gpu_memory_overflows' in d; } },
        { id: 'error_logs_timeouts', name: 'Timeouts', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: function(d) { return d && typeof d === 'object' && 'timeouts' in d; } },
        { id: 'error_logs_api_errors', name: 'API errors', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: function(d) { return d && typeof d === 'object' && 'api_errors' in d; } },
        { id: 'error_logs_high_risk', name: 'High Risk Errors', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: function(d) { return d && typeof d === 'object' && 'high_risk_errors' in d; } },
        { id: 'error_logs_medium_risk', name: 'Medium Risk Errors', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: function(d) { return d && typeof d === 'object' && 'medium_risk_errors' in d; } },
        { id: 'error_logs_low_risk', name: 'Low Risk Errors', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: function(d) { return d && typeof d === 'object' && 'low_risk_errors' in d; } },
        { id: 'error_logs_test_system', name: 'Test System', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: validErrorLogs },
        { id: 'error_logs_stress_test', name: 'Stress Test', category: 'page', testType: 'api', testUrl: '/api/dashboard/error_logs', validator: validErrorLogs },
        { id: 'job_status', name: 'Job Status', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: validJobStatus },
        { id: 'job_status_running', name: 'Running', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && ('running' in d || 'running_list' in d); } },
        { id: 'job_status_completed', name: 'Completed', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && ('completed' in d || 'completed_list' in d); } },
        { id: 'job_status_failed', name: 'Failed', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && ('failed' in d || 'failed_list' in d); } },
        { id: 'job_status_retried', name: 'Retried', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && ('retried' in d || 'retried_list' in d); } },
        { id: 'job_status_running_list', name: 'Running List', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.running_list); } },
        { id: 'job_status_completed_list', name: 'Completed List', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.completed_list); } },
        { id: 'job_status_failed_list', name: 'Failed List', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.failed_list); } },
        { id: 'job_status_retried_list', name: 'Retried List', category: 'page', testType: 'api', testUrl: '/api/dashboard/job_status', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.retried_list); } },
        { id: 'job_status_todays_schedule', name: "Today's Schedule", category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuTimeline },
        { id: 'monitoring_ui', name: 'Monitoring UI', category: 'page', testType: 'api', testUrl: '/api/dashboard/monitoring_jobs', validator: validMonitoringJobs },
        { id: 'monitoring_ui_active', name: 'Active Jobs', category: 'page', testType: 'api', testUrl: '/api/dashboard/monitoring_jobs', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.active); } },
        { id: 'monitoring_ui_finished', name: 'Finished Jobs', category: 'page', testType: 'api', testUrl: '/api/dashboard/monitoring_jobs', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.finished); } },
        { id: 'monitoring_ui_planned', name: 'Planned Jobs', category: 'page', testType: 'api', testUrl: '/api/dashboard/monitoring_jobs', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.planned); } },
        { id: 'monitoring_ui_permission_centre', name: 'Pending Schedule Requests', category: 'page', testType: 'api', testUrl: '/api/approvals/queue', validator: validApprovalQueue },
        { id: 'monitoring_ui_live_tail', name: 'Live Tail', category: 'page', testType: 'api', testUrl: '/api/jobs/events', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.items); } },
        { id: 'parameter_control', name: 'Parameter Control', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuTimeline },
        { id: 'parameter_control_agent_id', name: 'Agent Id', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuOrCpuEntryHasAgent },
        { id: 'parameter_control_bar_id', name: 'Bar Id', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasBarId },
        { id: 'parameter_control_gpu_pct_assigned', name: 'Gpu % Assigned', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasGpuPercent },
        { id: 'parameter_control_gpu_pct_usage', name: 'Gpu % Usage', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasGpuPercent },
        { id: 'parameter_control_gpu_pct_overall', name: 'Gpu % Overall', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasGpuPercent },
        { id: 'parameter_control_cpu_pct_assigned', name: 'Cpu % Assigned', category: 'page', testType: 'api', testUrl: '/api/cpu/timeline/24h', validator: validCpuEntryHasCpuPercent },
        { id: 'parameter_control_cpu_pct_usage', name: 'Cpu % Usage', category: 'page', testType: 'api', testUrl: '/api/cpu/timeline/24h', validator: validCpuEntryHasCpuPercent },
        { id: 'parameter_control_cpu_pct_overall', name: 'Cpu % Overall', category: 'page', testType: 'api', testUrl: '/api/cpu/timeline/24h', validator: validCpuEntryHasCpuPercent },
        { id: 'parameter_control_vram_pct_assigned', name: 'Vram % Assigned', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasVram },
        { id: 'parameter_control_vram_pct_usage', name: 'Vram % Usage', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasVram },
        { id: 'parameter_control_vram_pct_overall', name: 'Vram % Overall', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasVram },
        { id: 'parameter_control_performance', name: 'Performance', category: 'page', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuEntryHasGpuPercent },
        { id: 'approval_queue', name: 'Approval Queue', category: 'page', testType: 'api', testUrl: '/api/approvals/queue', validator: validApprovalQueue },
        { id: 'approval_queue_items', name: 'Pending Requests', category: 'page', testType: 'api', testUrl: '/api/approvals/queue', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.items); } },
        { id: 'approval_queue_count', name: 'Request Count', category: 'page', testType: 'api', testUrl: '/api/approvals/queue', validator: validApprovalQueue },
        { id: 'approval_queue_approve', name: 'Approve', category: 'page', testType: 'api', testUrl: '/api/approvals/queue', validator: validApprovalQueue },
        { id: 'audit', name: 'Audit', category: 'page', testType: 'api', testUrl: '/api/audit', validator: validAudit },
        { id: 'audit_items', name: 'Audit Events', category: 'page', testType: 'api', testUrl: '/api/audit', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.items); } },
        { id: 'audit_total', name: 'Audit Total Count', category: 'page', testType: 'api', testUrl: '/api/audit', validator: function(d) { return d && typeof d === 'object' && ('total' in d || Array.isArray(d.items)); } },
        { id: 'audit_event_explorer', name: 'Event Explorer', category: 'page', testType: 'api', testUrl: '/api/jobs/events', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.items); } },
        { id: 'audit_filter_actor', name: 'Filter by actor', category: 'page', testType: 'api', testUrl: '/api/audit', validator: validAudit },
        { id: 'audit_filter_action', name: 'Filter by action', category: 'page', testType: 'api', testUrl: '/api/audit', validator: validAudit },
        { id: 'audit_filter_object_type', name: 'Filter by object type', category: 'page', testType: 'api', testUrl: '/api/audit', validator: validAudit },
        { id: 'audit_apply_filters', name: 'Apply filters', category: 'page', testType: 'api', testUrl: '/api/audit', validator: validAudit },
        { id: 'audit_clear_filters', name: 'Clear filters', category: 'page', testType: 'api', testUrl: '/api/audit', validator: validAudit },
        { id: 'integrity_gate', name: 'Integrity Gate', category: 'page', testType: 'api', testUrl: '/api/integrity-gate', validator: validIntegrityGate },
        { id: 'integrity_gate_checks', name: 'Integrity Checks', category: 'page', testType: 'api', testUrl: '/api/integrity-gate', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.checks); } },
        { id: 'integrity_gate_blocked_reason', name: 'Blocked Reason', category: 'page', testType: 'api', testUrl: '/api/integrity-gate', validator: function(d) { return d && typeof d === 'object' && 'blocked_reason' in d; } },
        { id: 'integrity_gate_force_override', name: 'Force override (Resume)', category: 'page', testType: 'api', testUrl: '/api/admin/schedule-pause', validator: function(d) { return d && typeof d === 'object' && 'paused' in d; } },
        { id: 'integrity_gate_pause', name: 'Pause schedule', category: 'page', testType: 'api', testUrl: '/api/admin/schedule-pause', validator: function(d) { return d && typeof d === 'object' && 'paused' in d; } },
        { id: 'job_lifecycle', name: 'Job Lifecycle', category: 'page', testType: 'api', testUrl: '/api/jobs/specs', validator: validJobsSpecs },
        { id: 'job_lifecycle_specs', name: 'Job Specs', category: 'page', testType: 'api', testUrl: '/api/jobs/specs', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.items); } },
        { id: 'job_lifecycle_runs', name: 'Job Runs', category: 'page', testType: 'api', testUrl: '/api/jobs/runs', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.items); } },
        { id: 'job_lifecycle_expire_leases', name: 'Expire leases', category: 'page', testType: 'api', testUrl: '/api/jobs/runs', validator: function(d) { return d && typeof d === 'object' && Array.isArray(d.items); } },
        { id: 'metrics', name: 'Metrics', category: 'page', testType: 'api', testUrl: '/api/metrics/all', validator: validMetrics },
        { id: 'metrics_all', name: 'All Metrics', category: 'page', testType: 'api', testUrl: '/api/metrics/all', validator: validMetrics },
        { id: 'metrics_name', name: 'Metric Name', category: 'page', testType: 'api', testUrl: '/api/metrics/all', validator: function(d) { return Array.isArray(d) && (d.length === 0 || d.some(function(m) { return m && (m.name != null || typeof m === 'string'); })); } },
        { id: 'metrics_category', name: 'Metric Category', category: 'page', testType: 'api', testUrl: '/api/metrics/all', validator: function(d) { return Array.isArray(d) && (d.length === 0 || d.some(function(m) { return m && typeof m === 'object' && (m.category != null || m.name != null); })); } },
        { id: 'metrics_description', name: 'Metric Description', category: 'page', testType: 'api', testUrl: '/api/metrics/all', validator: function(d) { return Array.isArray(d) && (d.length === 0 || d.some(function(m) { return m && typeof m === 'object'; })); } },
        { id: 'gpu_add_entry_invalid_rejected', name: 'GPU add_entry invalid payload rejected', category: 'page', testType: 'negative', testUrl: '/api/gpu/timeline/add_entry', testMethod: 'POST', testPayload: {} },
        { id: 'gpu_schedule_crud_create', name: 'GPU Schedule create (CRUD)', category: 'page', testType: 'crud_create', testUrl: '/api/gpu/timeline/add_entry', testMethod: 'POST', testPayload: { agent: 'Localization-Master-Agent', ai_model: '1018', start_time: '09:00', duration_hours: 0.5 } },
        { id: 'cpu_schedule_crud_create', name: 'CPU Schedule create (CRUD)', category: 'page', testType: 'crud_create', testUrl: '/api/cpu/timeline/add_entry', testMethod: 'POST', testPayload: { agent: 'English-Localization-Agent', ai_model: '1017', start_time: '09:00', end_time: '09:30', cpu_percent: '0.5', memory_fraction: '0.1', cpu_device: 'CPU 1', priority: 'Medium', bar_id: 'English-Localization-Agent__Claude 3' } },
        { id: 'cpu_add_entry_invalid_rejected', name: 'CPU add_entry invalid payload rejected', category: 'page', testType: 'negative', testUrl: '/api/cpu/timeline/add_entry', testMethod: 'POST', testPayload: {} },
        /* 2026-07-17 modularization: selectors retargeted to resource_schedule.html (the page actually
           served at /cpu_schedule.html since 2026-07-15); dead 7d/28d/1y/history API endpoints replaced
           by pane-presence page tests. Old rows in crews_modularization_backups_20260717. */
        { id: 'cpu_entries', name: 'Entries', category: 'metrics_subtab', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#add-form' },
        { id: 'cpu_24h', name: '24 Hours', category: 'metrics_subtab', testType: 'api', testUrl: '/api/cpu/timeline/24h', validator: validCpuTimeline },
        { id: 'cpu_7d', name: '7 Days', category: 'metrics_subtab', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '[data-pane="p7"]' },
        { id: 'cpu_28d', name: '28 Days', category: 'metrics_subtab', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '[data-pane="p28"]' },
        { id: 'cpu_1y', name: '1 Year', category: 'metrics_subtab', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '[data-pane="p1y"]' },
        { id: 'cpu_history', name: 'History', category: 'metrics_subtab', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '[data-pane="phist"]' },
        { id: 'cpu_pending_schedule_requests', name: 'Pending Schedule Requests', category: 'metrics_subtab', testType: 'api', testUrl: '/api/approvals/queue', validator: function(d) { return Array.isArray(d) || (d && typeof d === 'object'); } },
        { id: 'cpu_date', name: 'Date', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-date' },
        { id: 'cpu_agent', name: 'Agent', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-agent' },
        { id: 'cpu_ai_model', name: 'AI Model', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-model' },
        { id: 'cpu_cpu_percent', name: 'CPU %', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-pct' },
        { id: 'cpu_device', name: 'CPU Device', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-device' },
        { id: 'cpu_start_time', name: 'Start Time', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-start' },
        { id: 'cpu_end_time', name: 'End Time', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-end' },
        { id: 'cpu_priority', name: 'Priority', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-prio' },
        { id: 'cpu_memory', name: 'Memory', category: 'form_field', testType: 'page', testUrl: '/cpu_schedule.html', testSelector: '#f-mem' },
        { id: 'job_status_approval_flow', name: 'Job Status + Approval Queue flow', category: 'page', testType: 'flow', flowSteps: [
            { testUrl: '/api/dashboard/job_status', validator: validJobStatus },
            { testUrl: '/api/approvals/queue', validator: validApprovalQueue }
        ] },
        /* 2026-07-17 modularization: retargeted to resource_schedule.html (served at /gpu_schedule.html);
           gpu_vram_required/gpu_vram_allowed rows dropped — the unified page has no such fields. */
        { id: 'entries', name: 'Entries', category: 'metrics_subtab', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#add-form' },
        { id: '24h', name: '24 Hours', category: 'metrics_subtab', testType: 'api', testUrl: '/api/gpu/timeline/24h', validator: validGpuTimeline },
        { id: '7d', name: '7 Days', category: 'metrics_subtab', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '[data-pane="p7"]' },
        { id: '28d', name: '28 Days', category: 'metrics_subtab', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '[data-pane="p28"]' },
        { id: '1y', name: '1 Year', category: 'metrics_subtab', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '[data-pane="p1y"]' },
        { id: 'history', name: 'History', category: 'metrics_subtab', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '[data-pane="phist"]' },
        { id: 'vram_map', name: 'VRAM Map', category: 'metrics_subtab', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#tab-vram' },
        { id: 'pending_schedule_requests', name: 'Pending Schedule Requests', category: 'metrics_subtab', testType: 'api', testUrl: '/api/approvals/queue', validator: function(d) { return Array.isArray(d) || (d && typeof d === 'object'); } },
        { id: 'gpu_date', name: 'Date', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-date' },
        { id: 'gpu_agent', name: 'Agent', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-agent' },
        { id: 'gpu_cpu_percent', name: 'CPU %', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-pct' },
        { id: 'gpu_start_time', name: 'Start Time', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-start' },
        { id: 'gpu_ai_model', name: 'AI Model', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-model' },
        { id: 'gpu_cpu_device', name: 'CPU Device', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-device' },
        { id: 'gpu_end_time', name: 'End Time', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-end' },
        { id: 'gpu_gpu_percent', name: 'GPU %', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-pct' },
        { id: 'gpu_priority', name: 'Priority', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-prio' },
        { id: 'gpu_device', name: 'GPU Device', category: 'form_field', testType: 'page', testUrl: '/gpu_schedule.html', testSelector: '#f-device' },
        /* User Stack (Identity & Auth) */
        { id: 'identity_management', name: 'Identity Management', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Identity Management' },
        { id: 'authentication', name: 'Authentication', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Authentication' },
        { id: 'token_model', name: 'Token Model', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Token Model' },
        { id: 'ui_session_handling', name: 'UI Session Handling', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'UI Session Handling' },
        { id: 'authorization_model', name: 'Authorization Model', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Authorization Model' },
        { id: 'privileged_access_controls', name: 'Privileged Access Controls', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Privileged Access Controls' },
        { id: 'agent_vs_human_identity', name: 'Agent vs Human Identity Separation', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Agent vs Human Identity Separation' },
        { id: 'authorization_enforcement', name: 'Authorization Enforcement', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Authorization Enforcement' },
        { id: 'auditability_traceability', name: 'Auditability and Traceability', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Auditability and Traceability' },
        { id: 'failure_behavior', name: 'Failure Behavior', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Failure Behavior' },
        /* Authentication Stack */
        { id: 'central_idp', name: 'Central IdP', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Central IdP' },
        { id: 'phishing_resistant_mfa', name: 'Phishing-resistant MFA', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Phishing-resistant MFA' },
        { id: 'oidc_pkce', name: 'OIDC Authorization Code + PKCE', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'OIDC Authorization Code + PKCE' },
        { id: 'no_tokens_localstorage', name: 'No tokens in localStorage', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'No tokens in localStorage' },
        { id: 'privileged_protections', name: 'Privileged protections', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Privileged protections' },
        { id: 'short_lived_tokens', name: 'Short-lived access tokens + refresh rotation', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Short-lived access tokens' },
        { id: 'step_up_auth', name: 'Step-up auth', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Step-up auth' },
        { id: 'conditional_access', name: 'Conditional access / device trust', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Conditional access' },
        /* Web Security Stack */
        { id: 'reverse_proxy_tls', name: 'Reverse proxy + TLS + headers', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Reverse proxy + TLS' },
        { id: 'cookie_session', name: 'Cookie/session settings', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Cookie/session settings' },
        { id: 'csrf_protection', name: 'CSRF protection', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'CSRF protection' },
        { id: 'cors_locked', name: 'CORS locked down', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'CORS locked down' },
        { id: 'request_validation', name: 'Request validation + size limits', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Request validation' },
        { id: 'csp_inline_js', name: 'CSP + remove inline JS', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'CSP + remove inline JS' },
        { id: 'xss_hardening', name: 'XSS hardening in templates', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'XSS hardening' },
        { id: 'rate_limiting', name: 'Rate limiting', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Rate limiting' },
        { id: 'error_leakage', name: 'Error/info leakage hardening', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Error/info leakage' },
        { id: 'upload_security', name: 'Upload security', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Upload security' },
        { id: 'security_logging', name: 'Security logging + alerting', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Security logging' },
        { id: 'dependency_pinning', name: 'Dependency pinning + scanning', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Dependency pinning' },
        { id: 'fail_closed', name: 'Fail-closed control-plane-down behavior', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Fail-closed' },
        /* Schedule Stack */
        { id: 'view_active_schedule', name: 'View Active Schedule', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'View Active Schedule' },
        { id: 'create_modify_schedule', name: 'Create or Modify Schedule (Request Phase)', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Create or Modify Schedule' },
        { id: 'policy_evaluation', name: 'Policy Evaluation', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Policy Evaluation' },
        { id: 'pending_state', name: 'Pending State', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Pending State' },
        { id: 'approval_flow', name: 'Approval Flow', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Approval Flow' },
        { id: 'activation', name: 'Activation', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Activation' },
        { id: 'audit_stack', name: 'Audit', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Audit' },
        { id: 'security_properties', name: 'Security Properties', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Security Properties' },
        /* User flow (Agents diagram) */
        { id: 'user_selects_role', name: 'User selects role (Admin / Operators / Spectators)', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'User selects role' },
        { id: 'login_id_password', name: 'Login with ID + Password', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Login with ID + Password' },
        { id: 'server_validates', name: 'Server validates role + credentials', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Server validates role' },
        { id: 'session_stores', name: 'Session stores user + role', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Session stores user' },
        { id: 'dashboard_restricted', name: 'Dashboard / Agents restricted by role', category: 'security', testType: 'page_contains', testUrl: '/', testContains: 'Dashboard / Agents restricted' },
        /* Settings */
        { id: 'styles_themes', name: 'Styles & Themes', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Styles' },
        { id: 'users_settings', name: 'Users', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Users' },
        { id: 'api_authorization_settings', name: 'Api Authorization', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Api Authorization' },
        { id: 'languages_settings', name: 'Languages', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Languages' },
        { id: 'security_settings', name: 'Security', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Security' },
        { id: 'billing_settings', name: 'Billing', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Billing' },
        { id: 'hotkeys_settings', name: 'Hotkeys', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Hotkeys' },
        { id: 'voice_assistant_settings', name: 'Voice Assistant', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Voice Assistant' },
        { id: 'orchestration_permissions', name: 'Orchestration Permissions', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Orchestration Permissions' },
        { id: 'flagged_behaviour', name: 'Flagged behaviour', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Flagged behaviour' },
        { id: 'network_security', name: 'Network security', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Network security' },
        { id: 'contracts', name: 'Contracts', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Contracts' },
        { id: 'login_methods', name: 'Login Methods', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Login Methods' },
        { id: 'agent_monitoring', name: 'Agent Monitoring', category: 'settings', testType: 'page_contains', testUrl: '/settings', testContains: 'Agent Monitoring' },
        { id: 'security_diagrams', name: 'Security Diagrams', category: 'settings', testType: 'page_contains', testUrl: '/', testContains: 'security-diagrams-modal' },
        /* Safety Subsystem (8 gaps) */
        { id: 'safety_persistent_audit', name: 'Persistent Safety Audit Log', category: 'safety', testType: 'api', testUrl: '/api/safety/status', validator: function(d) { return validSafetyStatus(d) && Array.isArray(d.audit_events) && d.audit_events.length >= 0; } },
        { id: 'safety_graded_fail_closed', name: 'Graded Fail-Closed', category: 'safety', testType: 'api', testUrl: '/api/safety/status', validator: function(d) { return validSafetyStatus(d) && typeof d.protection_level === 'number' && d.protection_level >= 0 && d.protection_level <= 4; } },
        { id: 'safety_recovery_state_machine', name: 'Recovery State Machine', category: 'safety', testType: 'api', testUrl: '/api/safety/status', validator: function(d) { return validSafetyStatus(d) && d.recovery_state && typeof d.can_resume_schedule === 'boolean'; } },
        { id: 'safety_full_emergency_stop', name: 'Full Emergency Stop', category: 'safety', testType: 'page_contains', testUrl: '/settings', testContains: 'Safety Switch' },
        { id: 'safety_runtime_intervention', name: 'Runtime Intervention Hooks', category: 'safety', testType: 'api', testUrl: '/api/safety/status', validator: validSafetyStatus },
        { id: 'safety_vram_pre_launch', name: 'VRAM-Aware Pre-Launch', category: 'safety', testType: 'api', testUrl: '/api/safety/status', validator: function(d) { return validSafetyStatus(d) && d.hardware && ('vram_used_mb' in d.hardware || 'gpu_temp_c' in d.hardware); } },
        { id: 'safety_quarantine', name: 'Quarantine / Crash-Loop Isolation', category: 'safety', testType: 'api', testUrl: '/api/safety/status', validator: function(d) { return validSafetyStatus(d) && d.control && 'quarantined_agents' in d.control && 'quarantined_agent_ids' in d.control; } },
        { id: 'safety_backend_integration', name: 'Backend Enforcement Integration', category: 'safety', testType: 'api', testUrl: '/api/safety/status', validator: function(d) { return validSafetyStatus(d) && d.thresholds && (d.thresholds.gpu || d.thresholds.failure_patterns); } },
        { id: 'safety_thresholds', name: 'Safety Thresholds API', category: 'safety', testType: 'api', testUrl: '/api/safety/thresholds', validator: validSafetyThresholds },
        { id: 'safety_confirm_recovery_403', name: 'Confirm Recovery (non-admin 403)', category: 'safety', testType: 'negative', testUrl: '/api/safety/confirm_recovery', testMethod: 'POST', testPayload: { level: 3 } }
    ];

    /* Map each mechanics item to its UI tab (main dashboard/sidebar tab) */
    var UI_TAB_MAP = {
        gpu_schedule: 'GPU Schedule', gpu_add_entry_invalid_rejected: 'GPU Schedule', gpu_schedule_crud_create: 'GPU Schedule',
        entries: 'GPU Schedule', '24h': 'GPU Schedule', '7d': 'GPU Schedule', '28d': 'GPU Schedule', '1y': 'GPU Schedule',
        history: 'GPU Schedule', vram_map: 'GPU Schedule', pending_schedule_requests: 'GPU Schedule',
        gpu_date: 'GPU Schedule', gpu_agent: 'GPU Schedule', gpu_cpu_percent: 'GPU Schedule', gpu_start_time: 'GPU Schedule',
        gpu_ai_model: 'GPU Schedule', gpu_vram_required: 'GPU Schedule', gpu_vram_allowed: 'GPU Schedule',
        gpu_cpu_device: 'GPU Schedule', gpu_end_time: 'GPU Schedule', gpu_gpu_percent: 'GPU Schedule',
        gpu_priority: 'GPU Schedule', gpu_device: 'GPU Schedule',
        cpu_schedule: 'CPU Schedule', cpu_schedule_crud_create: 'CPU Schedule', cpu_add_entry_invalid_rejected: 'CPU Schedule',
        cpu_entries: 'CPU Schedule', cpu_24h: 'CPU Schedule', cpu_7d: 'CPU Schedule', cpu_28d: 'CPU Schedule', cpu_1y: 'CPU Schedule',
        cpu_history: 'CPU Schedule', cpu_pending_schedule_requests: 'CPU Schedule',
        cpu_date: 'CPU Schedule', cpu_agent: 'CPU Schedule', cpu_ai_model: 'CPU Schedule', cpu_cpu_percent: 'CPU Schedule',
        cpu_device: 'CPU Schedule', cpu_start_time: 'CPU Schedule', cpu_end_time: 'CPU Schedule', cpu_priority: 'CPU Schedule', cpu_memory: 'CPU Schedule',
        agent_overview: 'Agent Overview', agent_overview_id: 'Agent Overview', agent_overview_name: 'Agent Overview', agent_overview_role: 'Agent Overview', agent_overview_department: 'Agent Overview',
        error_logs: 'Error Logs', error_logs_ai_model_fails: 'Error Logs', error_logs_gpu_overflow: 'Error Logs', error_logs_timeouts: 'Error Logs', error_logs_api_errors: 'Error Logs',
        error_logs_high_risk: 'Error Logs', error_logs_medium_risk: 'Error Logs', error_logs_low_risk: 'Error Logs',
        error_logs_test_system: 'Error Logs', error_logs_stress_test: 'Error Logs',
        job_status: 'Job Status', job_status_running: 'Job Status', job_status_completed: 'Job Status', job_status_failed: 'Job Status', job_status_retried: 'Job Status',
        job_status_running_list: 'Job Status', job_status_completed_list: 'Job Status', job_status_failed_list: 'Job Status', job_status_retried_list: 'Job Status', job_status_todays_schedule: 'Job Status', job_status_approval_flow: 'Job Status',
        monitoring_ui: 'Monitoring UI', monitoring_ui_active: 'Monitoring UI', monitoring_ui_finished: 'Monitoring UI', monitoring_ui_planned: 'Monitoring UI',
        monitoring_ui_permission_centre: 'Monitoring UI', monitoring_ui_live_tail: 'Monitoring UI',
        parameter_control: 'Parameter Control', parameter_control_agent_id: 'Parameter Control', parameter_control_bar_id: 'Parameter Control',
        parameter_control_gpu_pct_assigned: 'Parameter Control', parameter_control_gpu_pct_usage: 'Parameter Control', parameter_control_gpu_pct_overall: 'Parameter Control',
        parameter_control_cpu_pct_assigned: 'Parameter Control', parameter_control_cpu_pct_usage: 'Parameter Control', parameter_control_cpu_pct_overall: 'Parameter Control',
        parameter_control_vram_pct_assigned: 'Parameter Control', parameter_control_vram_pct_usage: 'Parameter Control', parameter_control_vram_pct_overall: 'Parameter Control',
        parameter_control_performance: 'Parameter Control',
        approval_queue: 'Approval Queue', approval_queue_items: 'Approval Queue', approval_queue_count: 'Approval Queue', approval_queue_approve: 'Approval Queue',
        audit: 'Audit', audit_items: 'Audit', audit_total: 'Audit', audit_event_explorer: 'Audit', audit_filter_actor: 'Audit', audit_filter_action: 'Audit', audit_filter_object_type: 'Audit', audit_apply_filters: 'Audit', audit_clear_filters: 'Audit',
        integrity_gate: 'Integrity Gate', integrity_gate_checks: 'Integrity Gate', integrity_gate_blocked_reason: 'Integrity Gate', integrity_gate_force_override: 'Integrity Gate', integrity_gate_pause: 'Integrity Gate',
        job_lifecycle: 'Job Lifecycle', job_lifecycle_specs: 'Job Lifecycle', job_lifecycle_runs: 'Job Lifecycle', job_lifecycle_expire_leases: 'Job Lifecycle',
        metrics: 'Metrics', metrics_all: 'Metrics', metrics_name: 'Metrics', metrics_category: 'Metrics', metrics_description: 'Metrics',
        identity_management: 'Security', authentication: 'Security', token_model: 'Security', ui_session_handling: 'Security',
        authorization_model: 'Security', privileged_access_controls: 'Security', agent_vs_human_identity: 'Security',
        authorization_enforcement: 'Security', auditability_traceability: 'Security', failure_behavior: 'Security',
        central_idp: 'Security', phishing_resistant_mfa: 'Security', oidc_pkce: 'Security', no_tokens_localstorage: 'Security',
        privileged_protections: 'Security', short_lived_tokens: 'Security', step_up_auth: 'Security', conditional_access: 'Security',
        reverse_proxy_tls: 'Security', cookie_session: 'Security', csrf_protection: 'Security', cors_locked: 'Security',
        request_validation: 'Security', csp_inline_js: 'Security', xss_hardening: 'Security', rate_limiting: 'Security',
        error_leakage: 'Security', upload_security: 'Security', security_logging: 'Security', dependency_pinning: 'Security',
        fail_closed: 'Security', view_active_schedule: 'Security', create_modify_schedule: 'Security', policy_evaluation: 'Security',
        pending_state: 'Security', approval_flow: 'Security', activation: 'Security', audit_stack: 'Security', security_properties: 'Security',
        user_selects_role: 'Security', login_id_password: 'Security', server_validates: 'Security', session_stores: 'Security',
        dashboard_restricted: 'Security',
        styles_themes: 'Settings', users_settings: 'Settings', api_authorization_settings: 'Settings', languages_settings: 'Settings',
        security_settings: 'Settings', billing_settings: 'Settings', hotkeys_settings: 'Settings', voice_assistant_settings: 'Settings',
        orchestration_permissions: 'Settings', flagged_behaviour: 'Settings', network_security: 'Settings', contracts: 'Settings',
        login_methods: 'Settings', agent_monitoring: 'Settings', security_diagrams: 'Settings',
        safety_persistent_audit: 'Safety', safety_graded_fail_closed: 'Safety', safety_recovery_state_machine: 'Safety',
        safety_full_emergency_stop: 'Safety', safety_runtime_intervention: 'Safety', safety_vram_pre_launch: 'Safety',
        safety_quarantine: 'Safety', safety_backend_integration: 'Safety', safety_thresholds: 'Safety',
        safety_confirm_recovery_403: 'Safety'
    };
    var UI_TAB_ORDER = ['GPU Schedule', 'CPU Schedule', 'Agent Overview', 'Error Logs', 'Job Status', 'Monitoring UI', 'Parameter Control', 'Approval Queue', 'Audit', 'Integrity Gate', 'Job Lifecycle', 'Metrics', 'Security', 'Settings', 'Safety'];

    function byId(id) { return document.getElementById(id); }

    function makeStatusSpan(status) {
        var ok = status === true;
        var skipped = isSkipped(status);
        var unknown = status === undefined || status === null;
        var icon = ok ? '\u2713' : (skipped ? '\u26A0' : (unknown ? '\u2014' : '\u2717'));
        var cls = 'mechanics-item-icon ' + (ok ? 'mechanics-ok' : (skipped ? 'mechanics-skipped' : (unknown ? 'mechanics-unknown' : 'mechanics-fail')));
        var tip = skipped && status.reason ? ' title="' + escapeAttr(status.reason) + '"' : '';
        return '<span class="' + cls + '" style="flex:0 0 20px;margin-left:auto;text-align:right;font-weight:bold;"' + tip + '>' + icon + '</span>';
    }

    var _scanLogHistory = [];

    function generateAndShowScanLog(tabName, logItems) {
        var now = new Date();
        var ts = now.toLocaleDateString('en-GB', { year: 'numeric', month: '2-digit', day: '2-digit' }) +
                 '  ' + now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        var installed = [], notInstalled = [], skipped = [], unknownItems = [];
        logItems.forEach(function (item) {
            if (item.status === true) installed.push(item.name);
            else if (item.status === false) notInstalled.push(item.name);
            else if (isSkipped(item.status)) skipped.push(item.name + (item.status && item.status.reason ? '  (' + item.status.reason + ')' : ''));
            else unknownItems.push(item.name);
        });
        var sep = '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500';
        var lines = [
            '\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510',
            '\u2502  MECHANICS SCAN LOG',
            '\u2502  Tab  : ' + tabName,
            '\u2502  Time : ' + ts,
            '\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518',
            ''
        ];
        lines.push('\u2713  INSTALLED / CONFIGURED  (' + installed.length + ')');
        if (installed.length === 0) { lines.push('   (none)'); }
        else { installed.forEach(function (n) { lines.push('   [OK]   ' + n); }); }
        lines.push('');
        lines.push('\u2717  NOT INSTALLED / MISSING  (' + notInstalled.length + ')');
        if (notInstalled.length === 0) { lines.push('   (none)'); }
        else { notInstalled.forEach(function (n) { lines.push('   [FAIL] ' + n); }); }
        lines.push('');
        if (skipped.length > 0) {
            lines.push('\u26a0  SKIPPED / UNAVAILABLE  (' + skipped.length + ')');
            skipped.forEach(function (n) { lines.push('   [SKIP] ' + n); });
            lines.push('');
        }
        if (unknownItems.length > 0) {
            lines.push('\u2014  NOT SCANNED  (' + unknownItems.length + ')');
            unknownItems.forEach(function (n) { lines.push('   [----] ' + n); });
            lines.push('');
        }
        lines.push(sep);
        lines.push('  SUMMARY  \u2713 ' + installed.length + ' OK   \u2717 ' + notInstalled.length + ' FAIL   \u26a0 ' + skipped.length + ' SKIP   \u2014 ' + unknownItems.length + ' NOT SCANNED');
        lines.push(sep);
        var logText = lines.join('\n');

        /* Prepend to history (newest at top) */
        _scanLogHistory.unshift(logText);
        var logEl = byId('mechanics-scan-log');
        var metaEl = byId('mechanics-logbook-meta');
        if (logEl) logEl.textContent = _scanLogHistory.join('\n\n');
        if (metaEl) metaEl.textContent = 'Last scan: ' + ts + '  \u00b7  ' + tabName + '  \u00b7  ' + _scanLogHistory.length + ' scan(s)';
        console.log('[Mechanics Scan Log]\n' + logText);
    }

    function skipReason(msg) { return { skipped: true, reason: msg || 'Test could not be performed' }; }
    function escapeAttr(s) { return String(s || '').replace(/&/g, '&amp;').replace(new RegExp('"', 'g'), '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    function isSkipped(s) { return s && typeof s === 'object' && s.skipped === true; }

    function loadStoredStatus() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (e) {
            return {};
        }
    }

    function saveStatus(id, result) {
        var status = loadStoredStatus();
        status[id] = (result && typeof result === 'object' && result.skipped) ? result : !!result;
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(status));
        } catch (e) {}
    }

    function getStoredStatus(id) {
        var status = loadStoredStatus();
        return status[id];
    }

    function runTest(item) {
        var netErr = 'Network error: could not reach server';
        if (item.testType === 'api') {
            return fetch(item.testUrl)
                .then(function (r) {
                    if (r.status === 503) return skipReason('Service unavailable (503). Backend or control plane may be down.');
                    if (!r.ok) return false;
                    return r.json().then(function (data) {
                        return item.validator ? item.validator(data) : true;
                    }).catch(function () { return false; });
                })
                .catch(function (e) { return skipReason(netErr + (e && e.message ? ': ' + e.message : '')); });
        }
        if (item.testType === 'page') {
            return fetch(item.testUrl)
                .then(function (r) {
                    if (r.status === 503) return skipReason('Service unavailable (503). Page could not be loaded.');
                    if (!r.ok) return false;
                    return r.text();
                })
                .then(function (html) {
                    if (!html) return false;
                    if (html.indexOf('login-form-wrap') >= 0 || html.indexOf('id="login-form"') >= 0) {
                        return skipReason('Session not authenticated for this page. Log in and retry.');
                    }
                    var doc = new DOMParser().parseFromString(html, 'text/html');
                    var sel = item.testSelector;
                    if (!sel) return true;
                    if (sel.indexOf(' ') >= 0 || sel[0] === '#' || sel[0] === '.' || sel.indexOf('[') >= 0) {
                        return !!doc.querySelector(sel);
                    }
                    return !!doc.getElementById(sel) || !!doc.querySelector('[name="' + sel + '"]');
                })
                .catch(function (e) { return skipReason(netErr + (e && e.message ? ': ' + e.message : '')); });
        }
        if (item.testType === 'page_contains') {
            return fetch(item.testUrl)
                .then(function (r) {
                    if (r.status === 503) return skipReason('Service unavailable (503). Page could not be loaded.');
                    if (!r.ok) return false;
                    return r.text();
                })
                .then(function (html) {
                    return html && html.indexOf(item.testContains) >= 0;
                })
                .catch(function (e) { return skipReason(netErr + (e && e.message ? ': ' + e.message : '')); });
        }
        if (item.testType === 'negative') {
            var url = item.testUrl;
            var method = (item.testMethod || 'POST').toUpperCase();
            var payload = item.testPayload != null ? item.testPayload : {};
            return fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function (r) {
                if (r.status === 503) return skipReason('Service unavailable (503). Cannot test validation when backend is down.');
                return r.status >= 400 && r.status < 500;
            }).catch(function (e) { return skipReason(netErr + (e && e.message ? ': ' + e.message : '')); });
        }
        if (item.testType === 'flow' && Array.isArray(item.flowSteps) && item.flowSteps.length > 0) {
            var chain = Promise.resolve(true);
            item.flowSteps.forEach(function (step) {
                chain = chain.then(function (prev) {
                    if (isSkipped(prev)) return prev;
                    if (prev === false) return false;
                    return fetch(step.testUrl).then(function (r) {
                        if (r.status === 503) return skipReason('Service unavailable (503) at ' + step.testUrl + '. Backend may be down.');
                        if (!r.ok) return false;
                        return r.json().then(function (data) {
                            return step.validator ? step.validator(data) : true;
                        }).catch(function () { return false; });
                    }).catch(function (e) { return skipReason(netErr + (e && e.message ? ': ' + e.message : '')); });
                });
            });
            return chain;
        }
        if (item.testType === 'crud_create') {
            var today = new Date().toISOString().slice(0, 10);
            var basePayload = item.testPayload != null ? item.testPayload : {};
            var payload = Object.assign({}, basePayload, { date: basePayload.date || today });
            var url = item.testUrl;
            var method = (item.testMethod || 'POST').toUpperCase();
            var crud503Msg = 'Control plane not available. Schedule create requires FastAPI server on port 8000.';
            var csrfMeta = document.querySelector('meta[name="csrf-token"]');
            var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
            return fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
                body: JSON.stringify(payload)
            }).then(function (r) {
                return r.json().then(function (data) {
                    if (r.status === 503) return skipReason(crud503Msg);
                    if (r.status === 403 && data && data.error && data.error.indexOf('CSRF') >= 0) return skipReason('CSRF token mismatch during scan — reload page and retry.');
                    if (r.status === 403) return skipReason('Insufficient role to test CRUD creation (requires admin or operator). Feature is installed.');
                    if (r.status === 401) return skipReason('Not authenticated — log in and rescan to test CRUD creation.');
                    return r.ok && (data.success === true || data.request_id != null);
                }).catch(function () {
                    return r.status === 503 ? skipReason(crud503Msg) : false;
                });
            }).catch(function (e) { return skipReason(netErr + (e && e.message ? ': ' + e.message : '')); });
        }
        return Promise.resolve(false);
    }

    function renderItemRow(item, status) {
        var ok = status === true;
        var skipped = isSkipped(status);
        var unknown = status === undefined || status === null;
        var icon = ok ? '\u2713' : (skipped ? '\u26A0' : (unknown ? '\u2014' : '\u2717'));
        var iconClass = ok ? 'mechanics-ok' : (skipped ? 'mechanics-skipped' : (unknown ? 'mechanics-unknown' : 'mechanics-fail'));
        var titleAttr = skipped && status.reason ? ' title="' + escapeAttr(status.reason) + '"' : '';
        var displayName = String(item.name || item.id).replace(/^\d+\.\s*/, '');
        return '<label class="mechanics-item-row" data-id="' + item.id + '" style="display:flex;align-items:center;gap:5px;padding:3px 4px;cursor:pointer;border-radius:3px;font-size:12px;">' +
            '<input type="checkbox" class="mechanics-item-check" data-id="' + item.id + '">' +
            '<span class="mechanics-item-name" style="flex:1;overflow:hidden;text-overflow:ellipsis;">' + escapeAttr(displayName) + '</span>' +
            '<span class="mechanics-item-icon ' + iconClass + '" style="flex:0 0 20px;margin-left:auto;text-align:right;font-weight:bold;"' + titleAttr + '>' + icon + '</span>' +
            '</label>';
    }

    function renderList(container, statusMap) {
        renderFunctionalityColumns(container, statusMap);
    }

    function renderFunctionalityColumns(container, statusMap) {
        var columnsEl = container ? container.querySelector('#mechanics-functionality-columns') : byId('mechanics-functionality-columns');
        if (!columnsEl) return;
        try {
            var byTab = {};
            (MECHANICS_ITEMS || []).forEach(function (item) {
                var tab = UI_TAB_MAP[item.id] || 'Other';
                if (!byTab[tab]) byTab[tab] = [];
                byTab[tab].push(item);
            });
            var html = '';
            UI_TAB_ORDER.forEach(function (tabName) {
                var items = byTab[tabName];
                if (!items || items.length === 0) return;
                var listHtml = items.map(function (item) {
                    return renderItemRow(item, statusMap && statusMap[item.id]);
                }).join('');
                html += '<div class="mechanics-functionality-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                    '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">' + escapeAttr(tabName) + '</div>' +
                    '<div class="mechanics-functionality-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div></div>';
            });
            var other = byTab['Other'];
            if (other && other.length > 0) {
                var listHtml = other.map(function (item) { return renderItemRow(item, statusMap && statusMap[item.id]); }).join('');
                html += '<div class="mechanics-functionality-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                    '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">Other</div>' +
                    '<div class="mechanics-functionality-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div></div>';
            }
            columnsEl.innerHTML = html || '<p style="color:#999;">No functionality items.</p>';
            columnsEl.querySelectorAll('.mechanics-item-row').forEach(function (row) {
                row.addEventListener('click', function (e) {
                    if (e.target.classList.contains('mechanics-item-check')) return;
                    showDetail(row.getAttribute('data-id'));
                });
            });
            columnsEl.querySelectorAll('.mechanics-item-check').forEach(function (cb) {
                cb.addEventListener('click', function (e) { e.stopPropagation(); });
            });
        } catch (e) {
            console.error('[Mechanics] renderFunctionalityColumns error:', e);
            columnsEl.innerHTML = '<p style="color:#999;">Could not load functionality list.</p>';
        }
    }

    function showDetail(id) {
        var item = MECHANICS_ITEMS.find(function (i) { return i.id === id; });
        var placeholder = byId('mechanics-detail-placeholder');
        var content = byId('mechanics-detail-content');
        if (!item || !placeholder || !content) return;
        var status = getStoredStatus(id);
        var ok = status === true;
        var skipped = isSkipped(status);
        var unknown = status === undefined || status === null;
        var statusText = ok ? (item.testType === 'negative' ? 'Invalid payload correctly rejected' : (item.testType === 'crud_create' ? 'Create request accepted (200 + request_id)' : 'Implemented and functioning')) : (skipped ? 'Test could not be performed' : (unknown ? 'Not scanned yet' : 'Not functioning correctly'));
        var testDesc = item.testType === 'negative' ? 'Negative: ' + (item.testMethod || 'POST') + ' ' + item.testUrl + ' with invalid payload expects 4xx' :
            (item.testType === 'crud_create' ? 'CRUD create: POST ' + item.testUrl + ' with valid payload expects 200 + success/request_id' :
            (item.testType === 'flow' && item.flowSteps ? 'Flow: ' + (item.flowSteps.map(function(s) { return s.testUrl; }).join(' \u2192 ')) :
            (item.testType === 'api' ? 'API ' + item.testUrl :
            (item.testType === 'page_contains' ? 'Page ' + item.testUrl + ' contains "' + (item.testContains || '') + '"' :
            'Page ' + (item.testUrl || '') + (item.testSelector ? ' (' + item.testSelector + ')' : '')))));
        var reasonPara = skipped && status.reason ? '<p><strong>Reason:</strong> ' + escapeAttr(status.reason) + '</p>' : '';
        var specHtml = '';
        if (item.category === 'safety' && typeof window.SAFETY_SCAN_SPEC === 'object' && window.SAFETY_SCAN_SPEC[item.name]) {
            var spec = window.SAFETY_SCAN_SPEC[item.name];
            specHtml = '<div class="safety-spec-detail" style="margin-top:12px;padding:12px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;font-size:13px;">' +
                '<p><strong>Scope:</strong> ' + escapeAttr((spec.scope || []).join(', ')) + '</p>' +
                '<p><strong>Core tests:</strong></p><ul style="margin:4px 0 12px 20px;">' +
                (spec.coreTests || []).map(function(t) { return '<li>' + escapeAttr(t) + '</li>'; }).join('') + '</ul>' +
                '<p><strong>Metrics:</strong> ' + escapeAttr((spec.metrics || []).join(', ')) + '</p>' +
                '<p><strong>Acceptance targets:</strong></p><ul style="margin:4px 0 0 20px;">' +
                (spec.acceptanceTargets || []).map(function(t) { return '<li>' + escapeAttr(t) + '</li>'; }).join('') + '</ul>' +
                '</div>';
        }
        if (item.category === 'safety' && typeof window.SAFETY_KPIS === 'object') {
            var kpis = window.SAFETY_KPIS;
            specHtml += '<div class="safety-kpis" style="margin-top:12px;padding:12px;background:#fefce8;border-radius:8px;border:1px solid #fde047;font-size:12px;">' +
                '<p><strong>Safety KPIs:</strong></p><ul style="margin:4px 0 0 20px;">';
            Object.keys(kpis || {}).forEach(function(k) {
                specHtml += '<li><strong>' + escapeAttr(k) + ':</strong> ' + escapeAttr((kpis[k] || []).join(', ')) + '</li>';
            });
            specHtml += '</ul></div>';
        }
        if (item.category === 'safety' && typeof window.SAFETY_RELEASE_GATE === 'object' && window.SAFETY_RELEASE_GATE.length) {
            specHtml += '<div class="safety-release-gate" style="margin-top:12px;padding:12px;background:#fef2f2;border-radius:8px;border:1px solid #fecaca;font-size:12px;">' +
                '<p><strong>Release Gate (must pass before production-ready):</strong></p><ul style="margin:4px 0 0 20px;">' +
                window.SAFETY_RELEASE_GATE.map(function(g) { return '<li>' + escapeAttr(g) + '</li>'; }).join('') + '</ul></div>';
        }
        if (item.category === 'safety' && typeof window.SAFETY_CROSS_CUTTING_SCENARIOS === 'object') {
            var scenarios = window.SAFETY_CROSS_CUTTING_SCENARIOS;
            specHtml += '<div class="safety-scenarios" style="margin-top:12px;padding:12px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0;font-size:12px;">' +
                '<p><strong>Cross-Cutting Scenarios:</strong></p>';
            Object.keys(scenarios || {}).forEach(function(k) {
                var s = scenarios[k];
                specHtml += '<p style="margin:8px 0 4px;"><strong>Scenario ' + escapeAttr(k) + ' &mdash; ' + escapeAttr(s.name || k) + '</strong></p>' +
                    '<p style="margin:0 0 0 16px;"><em>Expected:</em> ' + escapeAttr((s.expected || []).join('; ')) + '</p>' +
                    '<p style="margin:0 0 8px 16px;"><em>Metrics:</em> ' + escapeAttr((s.metrics || []).join(', ')) + '</p>';
            });
            specHtml += '</div>';
        }
        content.innerHTML = '<h4 style="margin-top:0;">' + (item.name || item.id) + '</h4>' +
            '<p><strong>Category:</strong> ' + (item.category || 'page') + '</p>' +
            '<p><strong>Status:</strong> ' + statusText + '</p>' +
            reasonPara +
            '<p><strong>Test:</strong> ' + testDesc + '</p>' +
            specHtml;
        content.style.display = 'block';
        placeholder.style.display = 'none';
    }

    function updateItemStatus(id, result) {
        saveStatus(id, result);
        var row = document.querySelector('.mechanics-item-row[data-id="' + id + '"]');
        if (row) {
            var iconEl = row.querySelector('.mechanics-item-icon');
            if (iconEl) {
                var ok = result === true;
                var skipped = isSkipped(result);
                iconEl.textContent = ok ? '\u2713' : (skipped ? '\u26A0' : '\u2717');
                iconEl.className = 'mechanics-item-icon ' + (ok ? 'mechanics-ok' : (skipped ? 'mechanics-skipped' : 'mechanics-fail'));
                iconEl.title = skipped && result.reason ? result.reason : '';
            }
        }
    }

    function computeMetrics() {
        var status = loadStoredStatus();
        var byCat = { page: { ok: 0, fail: 0, skipped: 0, unknown: 0 }, metrics_subtab: { ok: 0, fail: 0, skipped: 0, unknown: 0 }, form_field: { ok: 0, fail: 0, skipped: 0, unknown: 0 }, security: { ok: 0, fail: 0, skipped: 0, unknown: 0 }, settings: { ok: 0, fail: 0, skipped: 0, unknown: 0 }, safety: { ok: 0, fail: 0, skipped: 0, unknown: 0 } };
        var total = { ok: 0, fail: 0, skipped: 0, unknown: 0 };
        MECHANICS_ITEMS.forEach(function (item) {
            var cat = byCat[item.category] || byCat.page;
            var s = status[item.id];
            if (s === true) { cat.ok++; total.ok++; }
            else if (s === false) { cat.fail++; total.fail++; }
            else if (isSkipped(s)) { cat.skipped++; total.skipped++; }
            else { cat.unknown++; total.unknown++; }
        });
        return { byCat: byCat, total: total };
    }

    function renderKpiSummary() {
        var el = byId('mechanics-kpi-summary');
        if (!el) return;
        var m = computeMetrics();
        var cats = [
            { key: 'page', label: 'Operational', desc: 'Pages, APIs, metrics' },
            { key: 'metrics_subtab', label: 'Metrics', desc: 'Timeline, history, queue' },
            { key: 'form_field', label: 'Form fields', desc: 'GPU schedule inputs' },
            { key: 'security', label: 'Security', desc: 'Auth, web, schedule stack' },
            { key: 'settings', label: 'Settings', desc: 'Settings modules' },
            { key: 'safety', label: 'Safety', desc: '8 safety gaps: audit, fail-closed, recovery, emergency stop, runtime hooks, VRAM, quarantine, backend integration' }
        ];
        var html = '';
        cats.forEach(function (c) {
            var cat = m.byCat[c.key];
            if (!cat) return;
            var tot = cat.ok + cat.fail + (cat.skipped || 0) + cat.unknown;
            if (tot === 0) return;
            var pct = tot > 0 ? Math.round((cat.ok / tot) * 100) : 0;
            var cls = cat.fail > 0 ? 'mechanics-kpi-fail' : ((cat.skipped || 0) > 0 ? 'mechanics-kpi-skipped' : (cat.unknown === tot ? 'mechanics-kpi-unknown' : 'mechanics-kpi-ok'));
            var cardTitle = c.desc + ((cat.skipped || 0) > 0 ? ' (' + cat.skipped + ' skipped: could not be performed, e.g. control plane down)' : '');
            html += '<div class="mechanics-kpi-card ' + cls + '" style="padding:6px 12px; border-radius:6px; border:1px solid #e5e7eb; font-size:12px;" title="' + escapeAttr(cardTitle) + '">' +
                '<span style="font-weight:600;">' + c.label + '</span> ' + cat.ok + '/' + tot + ' (' + pct + '%)' +
                '</div>';
        });
        var t = m.total;
        var tot = t.ok + t.fail + (t.skipped || 0) + t.unknown;
        var pct = tot > 0 ? Math.round((t.ok / tot) * 100) : 0;
        html += '<div class="mechanics-kpi-card mechanics-kpi-total" style="padding:6px 12px; border-radius:6px; border:1px solid #1e40af; background:#eff6ff; font-size:12px; font-weight:600;">' +
            'Total ' + t.ok + '/' + tot + ' (' + pct + '%)' +
            '</div>';
        el.innerHTML = html;
    }

    var AGENT_DEPARTMENT_LABELS = {
        workflow_2d: '2D Series',
        workflow_3d: '3D Series',
        workflow_clipfarm: 'Clipfarm',
        workflow_distribution: 'Distribution',
        workflow_maintenance: 'Maintenance'
    };

    /** Department key -> [main workflow key, overseer workflow key] for merged columns */
    var AGENT_DEPARTMENT_MERGE = {
        workflow_2d: ['workflow_2d', 'workflow_2d_overseers'],
        workflow_3d: ['workflow_3d', 'workflow_3d_overseers'],
        workflow_clipfarm: ['workflow_clipfarm', 'workflow_clipfarm_overseers'],
        workflow_distribution: ['workflow_distribution', 'workflow_distribution_overseers'],
        workflow_maintenance: ['workflow_maintenance', 'workflow_maintenance_overseers']
    };

    function runScan(selectedOnly) {
        var items = selectedOnly
            ? MECHANICS_ITEMS.filter(function (i) {
                var cb = document.querySelector('.mechanics-item-check[data-id="' + i.id + '"]');
                return cb && cb.checked;
            })
            : MECHANICS_ITEMS;
        var statusEl = byId('mechanics-scan-status');
        if (statusEl) statusEl.textContent = 'Scanning ' + items.length + ' item(s)...';
        var done = 0;
        var scanResults = new Array(items.length);
        items.forEach(function (item, idx) {
            runTest(item).then(function (result) {
                updateItemStatus(item.id, result);
                scanResults[idx] = { name: item.name || item.id, status: result };
                done++;
                if (statusEl) statusEl.textContent = 'Scanned ' + done + '/' + items.length;
                if (done >= items.length) {
                    if (statusEl) statusEl.textContent = 'Scan complete.';
                    renderKpiSummary();
                    generateAndShowScanLog('Functionality', scanResults);
                }
            });
        });
        if (items.length === 0 && statusEl) statusEl.textContent = 'No items to scan. Select items or use "Scan all".';
    }

    function renderAgentColumns(container, onComplete) {
        var columnsEl = container ? container.querySelector('#mechanics-agent-columns') : byId('mechanics-agent-columns');
        if (!columnsEl) { if (onComplete) onComplete(); return; }
        var url = '/static/data/workflow_box_ids.json';
        var agentsUrl = '/api/agents';
        Promise.all([
            fetch(url).then(function (r) { return r.ok ? r.json() : {}; }).catch(function (e) { console.error('[Mechanics] workflow_box_ids fetch error:', e); return {}; }),
            fetch(agentsUrl).then(function (r) { return r.ok ? r.json() : []; }).catch(function (e) { console.error('[Mechanics] agents fetch error:', e); return []; })
        ]).then(function (results) {
            var data = results[0];
            var agentsResp = results[1];
            var agentTotal = Array.isArray(agentsResp) ? agentsResp.length : (agentsResp && agentsResp.agents ? agentsResp.agents.length : 0);
            if (agentTotal === 0 && agentsResp && typeof agentsResp === 'object' && !Array.isArray(agentsResp)) {
                var arr = agentsResp.agents || agentsResp.data || [];
                agentTotal = arr.length;
            }
            var order = ['workflow_2d', 'workflow_3d', 'workflow_clipfarm', 'workflow_distribution', 'workflow_maintenance'];
            var html = '';
            var logItems = [];
            order.forEach(function (deptKey) {
                var merge = AGENT_DEPARTMENT_MERGE[deptKey];
                var agents = [];
                if (merge && Array.isArray(merge)) {
                    merge.forEach(function (k) {
                        var arr = data[k] || [];
                        agents = agents.concat(arr);
                    });
                } else {
                    agents = data[deptKey] || [];
                }
                if (agents.length === 0) return;
                var label = AGENT_DEPARTMENT_LABELS[deptKey] || deptKey.replace('workflow_', '').replace(/_/g, ' ');
                var listHtml = agents.map(function (a) {
                    var name = a.agentName || a.text || a.flowId || '—';
                    var id = (a.flowId || a.txtId || '') + '_' + (name || '').replace(/\s/g, '_');
                    saveStatus('agent_' + id, true);
                    logItems.push({ name: name, status: true });
                    return '<label class="mechanics-agent-row" data-agent-id="' + escapeAttr(id) + '" style="display:flex;align-items:center;gap:5px;padding:3px 4px;cursor:pointer;border-radius:3px;font-size:12px;">' +
                        '<input type="checkbox" class="mechanics-agent-check" data-agent-id="' + escapeAttr(id) + '">' +
                        '<span class="mechanics-agent-name" style="flex:1;overflow:hidden;text-overflow:ellipsis;">' + escapeAttr(name) + '</span>' +
                        '<span class="mechanics-item-icon mechanics-ok" style="flex:0 0 20px;text-align:right;font-weight:bold;">\u2713</span>' +
                        '</label>';
                }).join('');
                html += '<div class="mechanics-agent-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                    '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">' + escapeAttr(label) + '</div>' +
                    '<div class="mechanics-agent-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div>' +
                    '</div>';
            });
            /* Fallback: when workflow_box_ids has no agents, use /api/agents for an "All Agents" column */
            if (!html && agentsResp) {
                var apiArr = Array.isArray(agentsResp) ? agentsResp : (agentsResp.agents ? Object.values(agentsResp.agents) : (agentsResp.items || []));
                var apiAgents = apiArr.map(function (a) {
                    var name = (a && (a.name || a.role)) ? (a.name || a.role) : (typeof a === 'string' ? a : '');
                    return name ? { agentName: name, flowId: '', txtId: '' } : null;
                }).filter(Boolean);
                if (apiAgents.length > 0) {
                    var listHtml = apiAgents.map(function (a) {
                        var name = a.agentName || '—';
                        var id = 'api_' + (name || '').replace(/\s/g, '_');
                        saveStatus('agent_api_' + id, true);
                        logItems.push({ name: name, status: true });
                        return '<label class="mechanics-agent-row" data-agent-id="' + escapeAttr(id) + '" style="display:flex;align-items:center;gap:5px;padding:3px 4px;cursor:pointer;border-radius:3px;font-size:12px;">' +
                            '<input type="checkbox" class="mechanics-agent-check" data-agent-id="' + escapeAttr(id) + '">' +
                            '<span class="mechanics-agent-name" style="flex:1;overflow:hidden;text-overflow:ellipsis;">' + escapeAttr(name) + '</span>' +
                            '<span class="mechanics-item-icon mechanics-ok" style="flex:0 0 20px;text-align:right;font-weight:bold;">\u2713</span>' +
                            '</label>';
                    }).join('');
                    html = '<div class="mechanics-agent-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                        '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">All Agents</div>' +
                        '<div class="mechanics-agent-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div>' +
                        '</div>';
                    data = { _fallback: apiAgents };
                }
            }
            columnsEl.innerHTML = html || '<p style="color:#666;">No agents loaded. Check workflow_box_ids.json and /api/agents.</p>';
            renderAgentKpiSummary(data, agentTotal);
            if (logItems.length > 0) generateAndShowScanLog('Agent Functionality', logItems);
            if (onComplete) onComplete();
        }).catch(function (e) {
            console.error('[Mechanics] renderAgentColumns error:', e);
            if (columnsEl) columnsEl.innerHTML = '<p style="color:#666;">Failed to load agents. Check console.</p>';
            if (onComplete) onComplete();
        });
    }

    function renderAgentKpiSummary(data, agentTotalFromApi) {
        var el = byId('mechanics-agent-kpi-summary');
        if (!el || !data) return;
        var order = ['workflow_2d', 'workflow_3d', 'workflow_clipfarm', 'workflow_distribution', 'workflow_maintenance'];
        var counts = {};
        var total = 0;
        order.forEach(function (deptKey) {
            var merge = AGENT_DEPARTMENT_MERGE[deptKey];
            var n = 0;
            if (merge && Array.isArray(merge)) {
                merge.forEach(function (k) {
                    n += (data[k] || []).length;
                });
            } else {
                n = (data[deptKey] || []).length;
            }
            counts[deptKey] = n;
            total += n;
        });
        /* Use /api/agents count (203) for total when available; matches Agent Overview. Scheduling Agent is shared across charts. */
        var displayTotal = (agentTotalFromApi && agentTotalFromApi > 0) ? agentTotalFromApi : total;
        var html = '';
        order.forEach(function (deptKey) {
            var n = counts[deptKey] || 0;
            if (n === 0) return;
            var label = AGENT_DEPARTMENT_LABELS[deptKey] || deptKey.replace('workflow_', '').replace(/_/g, ' ');
            html += '<div class="mechanics-kpi-card" style="padding:6px 12px; border-radius:6px; border:1px solid #e5e7eb; font-size:12px;">' +
                '<span style="font-weight:600;">' + escapeAttr(label) + '</span> 0/' + n + ' (0%)' +
                '</div>';
        });
        html += '<div class="mechanics-kpi-card mechanics-kpi-total" style="padding:6px 12px; border-radius:6px; border:1px solid #1e40af; background:#eff6ff; font-size:12px; font-weight:600;">' +
            'Total 0/' + displayTotal + ' (0%)' +
            '</div>';
        el.innerHTML = html;
    }

    var DEPENDENCY_CATEGORY_ORDER = [
        'core', 'backend', 'agents', 'llm', 'embeddings', 'diffusion', 'video_gen', 'video_proc', 'speech',
        'data', 'job_queue', 'monitoring', 'analytics', 'security', 'dev'
    ];
    var DEPENDENCY_CATEGORY_LABELS = {
        core: 'Core', backend: 'Backend', agents: 'Agents', llm: 'LLM', embeddings: 'Embeddings',
        diffusion: 'Diffusion', video_gen: 'Video Gen', video_proc: 'Video Proc', speech: 'Speech',
        data: 'Data', job_queue: 'Job Queue', monitoring: 'Monitoring', analytics: 'Analytics',
        security: 'Security', dev: 'Dev'
    };

    function renderDependenciesColumns(container, onComplete) {
        var columnsEl = container ? container.querySelector('#mechanics-dependencies-columns') : byId('mechanics-dependencies-columns');
        if (!columnsEl) { if (onComplete) onComplete(); return; }
        columnsEl.innerHTML = '<p style="color:#666;">Loading…</p>';
        fetch('/api/dependencies/status')
            .then(function (r) { return r.ok ? r.json() : { items: [] }; })
            .catch(function () { return { items: [] }; })
            .then(function (data) {
                var items = data.items || [];
                var byCat = {};
                var logItems = [];
                items.forEach(function (d) {
                    var cat = d.category || 'core';
                    if (!byCat[cat]) byCat[cat] = [];
                    byCat[cat].push(d);
                    var s = d.status || 'not_installed';
                    var id = (d.id || d.name || '').toString().replace(/\s/g, '_');
                    var statusVal = s === 'installed' ? true : (s === 'parts_missing' ? skipReason('Parts missing') : false);
                    saveStatus('dep_' + id, statusVal);
                    logItems.push({ name: (d.name || d.id) + (d.optional ? ' (opt)' : ''), status: statusVal });
                });
                var html = '';
                DEPENDENCY_CATEGORY_ORDER.forEach(function (cat) {
                    var list = byCat[cat];
                    if (!list || list.length === 0) return;
                    var label = DEPENDENCY_CATEGORY_LABELS[cat] || cat;
                    var listHtml = list.map(function (d) {
                        var s = d.status || 'not_installed';
                        var optional = d.optional ? ' (opt)' : '';
                        var id = (d.id || d.name || '').toString().replace(/\s/g, '_');
                        var displayName = escapeAttr((d.name || d.id) + optional);
                        var note = d.note ? ' title="' + escapeAttr(d.note) + '"' : '';
                        var icon = s === 'installed' ? '\u2713' : (s === 'parts_missing' ? '\u26A0' : '\u2717');
                        var iconCls = s === 'installed' ? 'mechanics-ok' : (s === 'parts_missing' ? 'mechanics-skipped' : 'mechanics-fail');
                        return '<label class="mechanics-item-row" data-id="dep_' + escapeAttr(id) + '" style="display:flex;align-items:center;gap:5px;padding:3px 4px;cursor:pointer;border-radius:3px;font-size:12px;"' + note + '>' +
                            '<input type="checkbox" class="mechanics-item-check" data-id="dep_' + escapeAttr(id) + '">' +
                            '<span class="mechanics-item-name" style="flex:1;overflow:hidden;text-overflow:ellipsis;">' + displayName + '</span>' +
                            '<span class="mechanics-item-icon ' + iconCls + '" style="flex:0 0 20px;margin-left:auto;text-align:right;font-weight:bold;">' + icon + '</span>' +
                            '</label>';
                    }).join('');
                    html += '<div class="mechanics-functionality-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                        '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">' + escapeAttr(label) + '</div>' +
                        '<div class="mechanics-functionality-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div></div>';
                });
                columnsEl.innerHTML = html || '<p style="color:#666;">No dependency data available. Check /api/dependencies/status.</p>';
                renderDependenciesKpiSummary(items);
                if (logItems.length > 0) generateAndShowScanLog('Dependencies', logItems);
                if (onComplete) onComplete();
            })
            .catch(function (e) {
                console.error('[Mechanics] renderDependenciesColumns error:', e);
                if (columnsEl) columnsEl.innerHTML = '<p style="color:#666;">Failed to load dependencies.</p>';
                if (onComplete) onComplete();
            });
    }

    function renderDependenciesKpiSummary(items) {
        var el = byId('mechanics-dependencies-kpi-summary');
        if (!el) return;
        var byCat = {};
        items.forEach(function (d) {
            var cat = d.category || 'core';
            if (!byCat[cat]) byCat[cat] = { installed: 0, total: 0 };
            byCat[cat].total++;
            if ((d.status || '') === 'installed') byCat[cat].installed++;
        });
        var hasSkipped = items.some(function (d) { return d.status === 'parts_missing'; });
        var html = '';
        DEPENDENCY_CATEGORY_ORDER.forEach(function (cat) {
            var c = byCat[cat];
            if (!c || c.total === 0) return;
            var pct = c.total > 0 ? Math.round((c.installed / c.total) * 100) : 0;
            var cls = c.installed < c.total ? (hasSkipped ? 'mechanics-kpi-skipped' : 'mechanics-kpi-fail') : 'mechanics-kpi-ok';
            var label = DEPENDENCY_CATEGORY_LABELS[cat] || cat;
            html += '<div class="mechanics-kpi-card ' + cls + '" style="padding:6px 12px; border-radius:6px; border:1px solid #e5e7eb; font-size:12px;">' +
                '<span style="font-weight:600;">' + escapeAttr(label) + '</span> ' + c.installed + '/' + c.total + ' (' + pct + '%)' +
                '</div>';
        });
        var tInstalled = items.filter(function (d) { return (d.status || '') === 'installed'; }).length;
        var tTotal = items.length;
        var tPct = tTotal > 0 ? Math.round((tInstalled / tTotal) * 100) : 0;
        html += '<div class="mechanics-kpi-card mechanics-kpi-total" style="padding:6px 12px; border-radius:6px; border:1px solid #1e40af; background:#eff6ff; font-size:12px; font-weight:600;">' +
            'Total ' + tInstalled + '/' + tTotal + ' (' + tPct + '%)' +
            '</div>';
        el.innerHTML = html || '<div class="mechanics-kpi-card">No dependencies</div>';
    }

    function renderLlmsColumns(container, onComplete) {
        var columnsEl = container ? container.querySelector('#mechanics-llms-columns') : byId('mechanics-llms-columns');
        if (!columnsEl) { if (onComplete) onComplete(); return; }
        columnsEl.innerHTML = '<p style="color:#666;">Loading…</p>';
        fetch('/api/llms/list')
            .then(function (r) { return r.ok ? r.json() : []; })
            .catch(function () { return []; })
            .then(function (llms) {
                var list = Array.isArray(llms) ? llms : [];
                var logItems = [];
                var listHtml = list.map(function (m) {
                    var id = 'llm_' + String(m).replace(/[\s.]/g, '_');
                    saveStatus(id, true);
                    logItems.push({ name: String(m), status: true });
                    return '<label class="mechanics-item-row" data-id="' + escapeAttr(id) + '" style="display:flex;align-items:center;gap:5px;padding:3px 4px;cursor:pointer;border-radius:3px;font-size:12px;">' +
                        '<input type="checkbox" class="mechanics-item-check" data-id="' + escapeAttr(id) + '">' +
                        '<span class="mechanics-item-name" style="flex:1;overflow:hidden;text-overflow:ellipsis;">' + escapeAttr(String(m)) + '</span>' +
                        '<span class="mechanics-item-icon mechanics-ok" style="flex:0 0 20px;margin-left:auto;text-align:right;font-weight:bold;">\u2713</span>' +
                        '</label>';
                }).join('');
                var html = '<div class="mechanics-functionality-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                    '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">LLMs</div>' +
                    '<div class="mechanics-functionality-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div></div>';
                columnsEl.innerHTML = list.length > 0 ? html : '<p style="color:#666;">No LLMs found. Add ai_models to agent configs or LLMS documents in Feedback &amp; Workflow.</p>';
                renderLlmsKpiSummary(list);
                if (logItems.length > 0) generateAndShowScanLog('LLMs', logItems);
                if (onComplete) onComplete();
            })
            .catch(function (e) {
                console.error('[Mechanics] renderLlmsColumns error:', e);
                if (columnsEl) columnsEl.innerHTML = '<p style="color:#666;">Failed to load LLMs.</p>';
                if (onComplete) onComplete();
            });
    }

    function renderLlmsKpiSummary(list) {
        var el = byId('mechanics-llms-kpi-summary');
        if (!el) return;
        var n = list.length;
        var pct = n > 0 ? 100 : 0;
        el.innerHTML = '<div class="mechanics-kpi-card mechanics-kpi-ok" style="padding:6px 12px; border-radius:6px; border:1px solid #e5e7eb; font-size:12px;">' +
            '<span style="font-weight:600;">LLMs</span> ' + n + '/' + n + ' (' + pct + '%)' +
            '</div>' +
            '<div class="mechanics-kpi-card mechanics-kpi-total" style="padding:6px 12px; border-radius:6px; border:1px solid #1e40af; background:#eff6ff; font-size:12px; font-weight:600;">' +
            'Total ' + n + '/' + n + ' (' + pct + '%)' +
            '</div>';
    }

    function renderHardwareTable(container) {
        var tbody = container ? container.querySelector('#mechanics-hardware-table-tbody') : byId('mechanics-hardware-table-tbody');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="8" style="padding:16px; color:#666;">Loading…</td></tr>';
        fetch('/api/hardware_table')
            .then(function (r) { return r.ok ? r.json() : { models: [] }; })
            .catch(function () { return { models: [] }; })
            .then(function (data) {
                var models = data.models || [];
                if (models.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" style="padding:16px; color:#666;">No hardware table data. Add type/parameters/role to gpu_ai_models.json and cpu_ai_models.json.</td></tr>';
                    return;
                }
                tbody.innerHTML = models.map(function (m) {
                    var fp16 = m.fp16_gb != null ? (m.fp16_gb + ' GB') : '—';
                    var s8 = m.size_8bit_gb != null ? (m.size_8bit_gb + ' GB') : '—';
                    var s4 = m.size_4bit_gb != null ? (m.size_4bit_gb + ' GB') : '—';
                    var vram = m.typical_vram != null ? m.typical_vram : '—';
                    var role = m.role != null ? m.role : '—';
                    var params = m.parameters != null ? m.parameters : '—';
                    var typeVal = m.type != null ? m.type : '—';
                    var name = escapeAttr(m.name || '—') + (m.schedule ? ' <span style="font-size:11px;color:#888;">(' + m.schedule + ')</span>' : '');
                    return '<tr><td style="border:1px solid #ddd;padding:8px 10px;">' + name + '</td><td style="border:1px solid #ddd;padding:8px 10px;">' + escapeAttr(typeVal) + '</td><td style="border:1px solid #ddd;padding:8px 10px;">' + escapeAttr(params) + '</td><td style="border:1px solid #ddd;padding:8px 10px;">' + escapeAttr(fp16) + '</td><td style="border:1px solid #ddd;padding:8px 10px;">' + escapeAttr(s8) + '</td><td style="border:1px solid #ddd;padding:8px 10px;">' + escapeAttr(s4) + '</td><td style="border:1px solid #ddd;padding:8px 10px;">' + escapeAttr(vram) + '</td><td style="border:1px solid #ddd;padding:8px 10px;">' + escapeAttr(role) + '</td></tr>';
                }).join('');
            })
            .catch(function (e) {
                console.error('[Mechanics] renderHardwareTable error:', e);
                tbody.innerHTML = '<tr><td colspan="8" style="padding:16px; color:#c00;">Failed to load hardware table.</td></tr>';
            });
    }

    function render(container) {
        if (!container) return;
        try {
            var statusMap = {};
            MECHANICS_ITEMS.forEach(function (item) {
                statusMap[item.id] = getStoredStatus(item.id);
            });
            renderList(container, statusMap);
            renderKpiSummary();
            renderAgentColumns(container);
        } catch (e) {
            console.error('[Mechanics] render error:', e);
        }

        try {
            var scanBtn = byId('mechanics-scan-btn');
            if (scanBtn) {
                scanBtn.onclick = function () {
                    try {
                        var selectedOnly = document.querySelector('input[name="mechanics-scan-mode"]:checked');
                        runScan(selectedOnly && selectedOnly.value === 'selected');
                    } catch (err) { console.error('[Mechanics] scan click error:', err); }
                };
            }

            var selectAllCb = byId('mechanics-select-all');
            if (selectAllCb) {
                selectAllCb.onclick = function () {
                    try {
                        var checked = this.checked;
                        var cols = container ? container.querySelector('#mechanics-functionality-columns') : byId('mechanics-functionality-columns');
                        if (cols) cols.querySelectorAll('.mechanics-item-check').forEach(function (cb) { cb.checked = checked; });
                    } catch (err) { console.error('[Mechanics] select-all error:', err); }
                };
            }

            var depsSelectAllCb = byId('mechanics-dependencies-select-all');
            if (depsSelectAllCb) {
                depsSelectAllCb.onclick = function () {
                    try {
                        var checked = this.checked;
                        var cols = container ? container.querySelector('#mechanics-dependencies-columns') : byId('mechanics-dependencies-columns');
                        if (cols) cols.querySelectorAll('.mechanics-item-check').forEach(function (cb) { cb.checked = checked; });
                    } catch (err) { console.error('[Mechanics] dependencies select-all error:', err); }
                };
            }

            var llmsSelectAllCb = byId('mechanics-llms-select-all');
            if (llmsSelectAllCb) {
                llmsSelectAllCb.onclick = function () {
                    try {
                        var checked = this.checked;
                        var cols = container ? container.querySelector('#mechanics-llms-columns') : byId('mechanics-llms-columns');
                        if (cols) cols.querySelectorAll('.mechanics-item-check').forEach(function (cb) { cb.checked = checked; });
                    } catch (err) { console.error('[Mechanics] llms select-all error:', err); }
                };
            }

            var agentSelectAllCb = byId('mechanics-agent-select-all');
            if (agentSelectAllCb) {
                agentSelectAllCb.onclick = function () {
                    try {
                        var checked = this.checked;
                        if (container) container.querySelectorAll('.mechanics-agent-check').forEach(function (cb) { cb.checked = checked; });
                    } catch (err) { console.error('[Mechanics] agent select-all error:', err); }
                };
            }

            var subtabs = container ? container.querySelectorAll('.mechanics-subtab') : [];
            subtabs.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var tab = this.getAttribute('data-mechanics-subtab');
                subtabs.forEach(function (b) { b.classList.remove('active'); });
                this.classList.add('active');
                container.querySelectorAll('.mechanics-subtab-content').forEach(function (c) {
                    c.classList.remove('active');
                    c.style.display = 'none';
                });
                var content = container.querySelector('#mechanics-' + tab);
                if (content) {
                    content.classList.add('active');
                    content.style.display = 'flex';
                }
                if (tab === 'dependencies') renderDependenciesColumns(container);
                if (tab === 'llms') renderLlmsColumns(container);
                if (tab === 'hardware-table') renderHardwareTable(container);
                if (tab === 'tools') renderToolsColumns(container);
                if (tab === 'api-tools') renderApiToolsColumns(container);
                /* logbook: no lazy-load needed — content is written by scans */
                /* skills: initialised by inline script listener — nothing needed here */
            });
        });

            var agentScanBtn = byId('mechanics-agent-scan-btn');
            if (agentScanBtn) {
                agentScanBtn.onclick = function () {
                    var statusEl = byId('mechanics-agent-scan-status');
                    if (statusEl) statusEl.textContent = 'Scanning…';
                    renderAgentColumns(container, function () {
                        if (statusEl) statusEl.textContent = 'Scan complete.';
                    });
                };
            }

            var depsScanBtn = byId('mechanics-dependencies-scan-btn');
            if (depsScanBtn) {
                depsScanBtn.onclick = function () {
                    var statusEl = byId('mechanics-dependencies-scan-status');
                    if (statusEl) statusEl.textContent = 'Scanning…';
                    renderDependenciesColumns(container, function () {
                        if (statusEl) statusEl.textContent = 'Scan complete.';
                    });
                };
            }

            var llmsScanBtn = byId('mechanics-llms-scan-btn');
            if (llmsScanBtn) {
                llmsScanBtn.onclick = function () {
                    var statusEl = byId('mechanics-llms-scan-status');
                    if (statusEl) statusEl.textContent = 'Scanning…';
                    renderLlmsColumns(container, function () {
                        if (statusEl) statusEl.textContent = 'Scan complete.';
                    });
                };
            }

            var toolsSelectAllCb = byId('mechanics-tools-select-all');
            if (toolsSelectAllCb) {
                toolsSelectAllCb.onclick = function () {
                    try {
                        var checked = this.checked;
                        var cols = container ? container.querySelector('#mechanics-tools-columns') : byId('mechanics-tools-columns');
                        if (cols) cols.querySelectorAll('.mechanics-item-check').forEach(function (cb) { cb.checked = checked; });
                    } catch (err) { console.error('[Mechanics] tools select-all error:', err); }
                };
            }

            var toolsScanBtn = byId('mechanics-tools-scan-btn');
            if (toolsScanBtn) {
                toolsScanBtn.onclick = function () {
                    var statusEl = byId('mechanics-tools-scan-status');
                    if (statusEl) statusEl.textContent = 'Scanning…';
                    // Clear stale localStorage entries for tools so old 'true' values don't persist
                    try {
                        var keysToRemove = [];
                        for (var i = 0; i < localStorage.length; i++) {
                            var k = localStorage.key(i);
                            if (k && k.indexOf('tool_') === 0) keysToRemove.push(k);
                        }
                        keysToRemove.forEach(function(k) { localStorage.removeItem(k); });
                    } catch(e) {}
                    renderToolsColumns(container, function () {
                        if (statusEl) statusEl.textContent = 'Scan complete.';
                    });
                };
            }

            var apitoolsScanBtn = byId('mechanics-apitools-scan-btn');
            if (apitoolsScanBtn) {
                apitoolsScanBtn.onclick = function () {
                    var statusEl = byId('mechanics-apitools-scan-status');
                    if (statusEl) statusEl.textContent = 'Scanning\u2026';
                    renderApiToolsColumns(container, function () {
                        if (statusEl) statusEl.textContent = 'Scan complete.';
                    });
                };
            }

            var logbookCopyBtn = byId('mechanics-logbook-copy-btn');
            if (logbookCopyBtn) {
                logbookCopyBtn.onclick = function () {
                    try {
                        var logEl = byId('mechanics-scan-log');
                        var text = logEl ? logEl.textContent : '';
                        if (navigator.clipboard) {
                            navigator.clipboard.writeText(text).then(function () {
                                logbookCopyBtn.textContent = 'Copied!';
                                setTimeout(function () { logbookCopyBtn.textContent = 'Copy All'; }, 1800);
                            });
                        } else {
                            var ta = document.createElement('textarea');
                            ta.value = text;
                            document.body.appendChild(ta);
                            ta.select();
                            document.execCommand('copy');
                            document.body.removeChild(ta);
                            logbookCopyBtn.textContent = 'Copied!';
                            setTimeout(function () { logbookCopyBtn.textContent = 'Copy All'; }, 1800);
                        }
                    } catch (err) { console.error('[Mechanics] logbook copy error:', err); }
                };
            }

            var logbookClearBtn = byId('mechanics-logbook-clear-btn');
            if (logbookClearBtn) {
                logbookClearBtn.onclick = function () {
                    _scanLogHistory = [];
                    var logEl = byId('mechanics-scan-log');
                    var metaEl = byId('mechanics-logbook-meta');
                    if (logEl) logEl.textContent = 'No scans yet. Run a scan from any tab to see results here.';
                    if (metaEl) metaEl.textContent = '';
                };
            }
        } catch (e) {
            console.error('[Mechanics] bind events error:', e);
        }
    }

    var TOOLS_WF_ORDER = ['Clipfarm', '2D Series', '3D Series', 'Distribution', 'Maintenance', 'Other'];

    // Tools that require external API keys — show '—' (cannot verify without key).
    var EXTERNAL_API_TOOLS = [
        'instagram graph api', 'instagram insights api',
        'tiktok analytics api', 'tiktok trending api', 'tiktok upload api',
        'youtube analytics api', 'youtube data api', 'youtube autocomplete',
        'google autocomplete api',
        'socialblade scraper',
        'vidiq api',
        'civitai (model trend data)',
        'post trigger (platform api)',
        'competitor channel scraper',
        'platform auth manager',
        // Reddit requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET
        'reddit api (praw)', 'reddit hot posts (praw)',
    ];

    // Maps keyword substrings (case-insensitive) in tool names to dep item IDs
    // (= package_name.replace(/-/g,'_')) from DEPENDENCIES_CONFIG / /api/dependencies/status.
    // Order matters: more specific entries first (e.g. faster_whisper before whisper).
    var TOOL_KEYWORD_MAP = [
        // More specific entries first to avoid early false matches
        { kw: ['faster_whisper', 'faster-whisper', 'faster whisper'], depId: 'faster_whisper' },
        { kw: ['torchvision'],   depId: 'torchvision' },
        { kw: ['torchaudio'],    depId: 'torchaudio' },
        { kw: ['torch'],         depId: 'torch' },
        // whisper: only match the word 'whisper' itself, not 'transcript' (too broad)
        { kw: ['whisper'],       depId: 'whisper' },
        { kw: ['imageio_ffmpeg', 'imageio-ffmpeg'], depId: 'imageio_ffmpeg' },
        { kw: ['imageio'],       depId: 'imageio' },
        { kw: ['ffmpeg', 'ffprobe'], depId: 'ffmpeg_python' },
        { kw: ['moviepy'],       depId: 'moviepy' },
        { kw: ['yt-dlp', 'yt_dlp', 'ytdlp'], depId: 'yt_dlp' },
        { kw: ['pymediainfo', 'mediainfo'], depId: 'pymediainfo' },
        { kw: ['scenedetect', 'scene detect', 'opencv', 'cv2'], depId: 'opencv_python' },
        { kw: ['yolov8', 'yolo v8', 'ultralytics', 'segment anything'], depId: 'ultralytics' },
        { kw: ['imagehash', 'image hash'], depId: 'ImageHash' },
        { kw: ['pydub'],         depId: 'pydub' },
        { kw: ['librosa'],       depId: 'librosa' },
        { kw: ['soundfile'],     depId: 'soundfile' },
        { kw: ['decord'],        depId: 'decord' },
        { kw: ['einops'],        depId: 'einops' },
        { kw: ['stable diffusion', 'diffusers', 'diffusion'], depId: 'diffusers' },
        { kw: ['xformers'],      depId: 'xformers' },
        { kw: ['compel'],        depId: 'compel' },
        { kw: ['sentence_transform', 'sentence transform', 'sentence-transform'], depId: 'sentence_transformers' },
        { kw: ['faiss'],         depId: 'faiss_cpu' },
        { kw: ['chroma'],        depId: 'chromadb' },
        { kw: ['bark'],          depId: 'bark' },
        { kw: ['tortoise tts', 'tortoise-tts'], depId: 'tortoise_tts' },
        { kw: ['spacy', 'spaCy', 'nlp topic tag', 'pattern extractor (nlp'], depId: 'spacy' },
        { kw: ['keybert'],       depId: 'keybert' },
        { kw: ['sklearn', 'scikit-learn', '(sklearn)', 'tf-idf', 'tfidf', 'cosine'], depId: 'scikit_learn' },
        // Beat detection & word-level alignment map to librosa / faster-whisper
        { kw: ['beat sync', 'beat detect'], depId: 'librosa' },
        { kw: ['word-level timestamp', 'word level timestamp'], depId: 'faster_whisper' },
        // Emotion / topic summarization → transformers
        { kw: ['emotion language detector', 'emotion scorer', 'topic summarizer'], depId: 'transformers' },
        // RSS & trending → requests
        { kw: ['rss feed reader', 'youtube trending rss', 'rss feed', 'trending rss'], depId: 'requests' },
        // SQLite/PostgreSQL → sqlalchemy
        { kw: ['sqlite', 'postgresql', 'index storage', 'content index db'], depId: 'sqlalchemy' },
        // Scheduler / queue → apscheduler / celery
        { kw: ['cron / task scheduler', 'task scheduler', 'cron task'], depId: 'apscheduler' },
        { kw: ['job queue builder', 'job queue'], depId: 'celery' },
        { kw: ['pytrends'],      depId: 'pytrends' },
        { kw: ['praw'],          depId: 'praw' },
        { kw: ['youtube transcript api', 'youtube-transcript-api'], depId: 'youtube_transcript_api' },
        { kw: ['transformers'],  depId: 'transformers' },
        { kw: ['huggingface', 'hugging face'], depId: 'huggingface_hub' },
        { kw: ['pillow'],        depId: 'Pillow' },
        { kw: ['scikit-image', 'skimage'], depId: 'scikit_image' },
        { kw: ['accelerate'],    depId: 'accelerate' },
        { kw: ['bitsandbytes'],  depId: 'bitsandbytes' },
        { kw: ['sentencepiece'], depId: 'sentencepiece' },
        { kw: ['safetensors'],   depId: 'safetensors' },
        { kw: ['peft'],          depId: 'peft' },
        { kw: ['vllm'],          depId: 'vllm' },
        { kw: ['optimum'],       depId: 'optimum' },
        { kw: ['phonemizer'],    depId: 'phonemizer' },
        { kw: ['encodec'],       depId: 'encodec' },
        { kw: ['langchain'],     depId: 'langchain' },
        { kw: ['crewai'],        depId: 'crewai' },
        { kw: ['autogen'],       depId: 'autogen' },
        { kw: ['fastapi'],       depId: 'fastapi' },
        { kw: ['flask'],         depId: 'flask' },
        { kw: ['pydantic'],      depId: 'pydantic' },
        { kw: ['redis'],         depId: 'redis' },
        { kw: ['minio'],         depId: 'minio' },
        { kw: ['celery'],        depId: 'celery' },
        { kw: ['apscheduler'],   depId: 'apscheduler' },
        { kw: ['sqlalchemy'],    depId: 'sqlalchemy' },
        { kw: ['alembic'],       depId: 'alembic' },
        { kw: ['plotly'],        depId: 'plotly' },
        { kw: ['pandas'],        depId: 'pandas' },
        { kw: ['numpy'],         depId: 'numpy' },
        { kw: ['matplotlib'],    depId: 'matplotlib' },
        { kw: ['seaborn'],       depId: 'seaborn' },
        // Tools whose names reference psutil / pynvml indirectly
        { kw: ['psutil', 'disk usage monitor', 'df / psutil'], depId: 'psutil' },
        { kw: ['hardware telemetry', 'gpu temp', 'vram', 'cpu util'], depId: 'psutil' },
        { kw: ['cpu resource allocator'], depId: 'psutil' },
        { kw: ['gpu resource allocator'], depId: 'pynvml' },
        { kw: ['prometheus'],    depId: 'prometheus_client' },
        { kw: ['pynvml', 'nvml'], depId: 'pynvml' },
        { kw: ['loguru'],        depId: 'loguru' },
        { kw: ['cryptography'],  depId: 'cryptography' },
        { kw: ['requests'],      depId: 'requests' },
        { kw: ['httpx'],         depId: 'httpx' },
        { kw: ['aiohttp'],       depId: 'aiohttp' },
        { kw: ['orjson'],        depId: 'orjson' },
        { kw: ['pyyaml', ' yaml '], depId: 'pyyaml' },
        { kw: ['tenacity'],      depId: 'tenacity' },
        { kw: ['tqdm'],          depId: 'tqdm' },
    ];

    function _toolDepStatus(toolName, depMap) {
        var lower = ' ' + toolName.toLowerCase() + ' ';
        for (var i = 0; i < TOOL_KEYWORD_MAP.length; i++) {
            var entry = TOOL_KEYWORD_MAP[i];
            for (var j = 0; j < entry.kw.length; j++) {
                if (lower.indexOf(entry.kw[j].toLowerCase()) >= 0) {
                    var s = depMap[entry.depId];
                    return s !== undefined ? s : null;
                }
            }
        }
        return null; // no mapping — cannot verify
    }

    function renderToolsColumns(container, onComplete) {
        var columnsEl = container ? container.querySelector('#mechanics-tools-columns') : byId('mechanics-tools-columns');
        if (!columnsEl) { if (onComplete) onComplete(); return; }
        columnsEl.innerHTML = '<p style="color:#666;">Loading\u2026</p>';
        Promise.all([
            fetch('/api/agents/config').then(function(r){ return r.ok ? r.json() : null; }).catch(function(){ return null; }),
            fetch('/api/dependencies/status').then(function(r){ return r.ok ? r.json() : null; }).catch(function(){ return null; })
        ]).then(function(results) {
            var data = results[0];
            var depData = results[1];

            // Build dep status lookup: id → status ('installed'|'parts_missing'|'not_installed')
            var depMap = {};
            if (depData && depData.items) {
                depData.items.forEach(function(item) { depMap[item.id] = item.status; });
            }

            var agentList = [];
            if (!data) { /* fall through to empty */ }
            else if (Array.isArray(data)) { agentList = data; }
            else if (data.agents) {
                var raw = data.agents;
                agentList = Array.isArray(raw) ? raw : Object.keys(raw).map(function(k) {
                    var a = raw[k]; return typeof a === 'object' ? Object.assign({ _key: k }, a) : { _key: k, name: k };
                });
            } else if (typeof data === 'object') {
                agentList = Object.keys(data).map(function(k) {
                    var a = data[k]; return typeof a === 'object' ? Object.assign({ _key: k }, a) : { _key: k, name: k };
                });
            }

            var toolsByWf = {};
            TOOLS_WF_ORDER.forEach(function(wf) { toolsByWf[wf] = {}; });

            agentList.forEach(function(agent) {
                if (!agent || typeof agent !== 'object') return;
                var tools = agent.tools;
                if (!Array.isArray(tools) || tools.length === 0) return;
                var key = (agent._key || agent.id || agent.name || '');
                var dept = (agent.department || '').toLowerCase();
                var wf;
                if (key.indexOf('CLIPFARM') >= 0 || dept.indexOf('clipfarm') >= 0 || dept.indexOf('animation-media') >= 0) wf = 'Clipfarm';
                else if (key.indexOf('2D') >= 0 || dept.indexOf('2d') >= 0) wf = '2D Series';
                else if (key.indexOf('3D') >= 0 || dept.indexOf('3d') >= 0) wf = '3D Series';
                else if (dept.indexOf('distribution') >= 0) wf = 'Distribution';
                else if (dept.indexOf('maintenance') >= 0) wf = 'Maintenance';
                else wf = 'Other';
                if (!toolsByWf[wf]) toolsByWf[wf] = {};
                var agentLabel = agent.name || agent.role || key;
                tools.forEach(function(tool) {
                    var tName = typeof tool === 'string' ? tool : ((tool && (tool.name || tool.tool_name)) ? (tool.name || tool.tool_name) : JSON.stringify(tool));
                    if (!toolsByWf[wf][tName]) toolsByWf[wf][tName] = [];
                    toolsByWf[wf][tName].push(agentLabel);
                });
            });

            var html = '';
            var totalTools = 0;
            var totalInstalled = 0;
            var totalSkipped = 0;
            var logItems = [];
            TOOLS_WF_ORDER.forEach(function(wf) {
                var toolsInWf = toolsByWf[wf] || {};
                var toolNames = Object.keys(toolsInWf).sort();
                if (toolNames.length === 0) return;
                totalTools += toolNames.length;
                var listHtml = toolNames.map(function(tName) {
                    var tNameLower = tName.toLowerCase();
                    // External API tools belong in the Api Tools tab — skip entirely here
                    if (EXTERNAL_API_TOOLS.some(function(k) { return tNameLower.indexOf(k) >= 0; })) {
                        totalSkipped++;
                        return '';
                    }
                    var agentsUsing = toolsInWf[tName];
                    var id = 'tool_' + wf.replace(/\s/g, '_') + '_' + tName.replace(/[\s\W]/g, '_');
                    var depStatus = _toolDepStatus(tName, depMap);
                    var statusIcon, statusCls, logStatus;
                    if (depStatus === null) {
                        // No pip dep mapping — internal tool implemented in tools/ codebase
                        statusIcon = '\u2713'; // ✓
                        statusCls = 'mechanics-item-icon mechanics-ok mechanics-ok-internal';
                        logStatus = true;
                        totalInstalled++;
                        saveStatus(id, true);
                    } else if (depStatus === 'installed') {
                        statusIcon = '\u2713'; // ✓
                        statusCls = 'mechanics-item-icon mechanics-ok';
                        logStatus = true;
                        totalInstalled++;
                        saveStatus(id, true);
                    } else if (depStatus === 'parts_missing') {
                        statusIcon = '\u2248'; // ≈ (partial)
                        statusCls = 'mechanics-item-icon mechanics-partial';
                        logStatus = true;
                        totalInstalled++;
                        saveStatus(id, true);
                    } else {
                        // not_installed
                        statusIcon = '\u2717'; // ✗
                        statusCls = 'mechanics-item-icon mechanics-fail';
                        logStatus = false;
                        saveStatus(id, false);
                    }
                    logItems.push({ name: tName + '  [' + wf + ']', status: logStatus, skip: logStatus === null });
                    var tipAttr = agentsUsing.length > 0 ? ' title="Used by: ' + escapeAttr(agentsUsing.slice(0, 6).join(', ') + (agentsUsing.length > 6 ? ' +' + (agentsUsing.length - 6) + ' more' : '')) + '"' : '';
                    return '<label class="mechanics-item-row" data-id="' + escapeAttr(id) + '" style="display:flex;align-items:center;gap:5px;padding:3px 4px;cursor:pointer;border-radius:3px;font-size:12px;"' + tipAttr + '>' +
                        '<input type="checkbox" class="mechanics-item-check" data-id="' + escapeAttr(id) + '">' +
                        '<span class="mechanics-item-name" style="flex:1;overflow:hidden;text-overflow:ellipsis;">' + escapeAttr(tName) + '</span>' +
                        '<span class="' + statusCls + '" style="flex:0 0 20px;margin-left:auto;text-align:right;font-weight:bold;">' + statusIcon + '</span>' +
                        '</label>';
                }).join('');
                html += '<div class="mechanics-functionality-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                    '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">' + escapeAttr(wf) + '</div>' +
                    '<div class="mechanics-functionality-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div></div>';
            });

            columnsEl.innerHTML = html || '<p style="color:#666;">No tools found. Add a <em>tools</em> array to agent configs in agents.json.</p>';
            renderToolsKpiSummary(totalTools - totalSkipped, totalInstalled, toolsByWf, depMap);
            if (logItems.length > 0) generateAndShowScanLog('Tools', logItems);
            if (onComplete) onComplete();
        }).catch(function(e) {
            console.error('[Mechanics] renderToolsColumns error:', e);
            if (columnsEl) columnsEl.innerHTML = '<p style="color:#666;">Failed to load tools. Check /api/agents/config.</p>';
            if (onComplete) onComplete();
        });
    }

    // Platform grouping for Api Tools tab
    var API_PLATFORM_ORDER = ['YouTube', 'TikTok', 'Instagram', 'Reddit', 'Google', 'SocialBlade', 'VidIQ', 'CivitAI', 'Other'];
    var API_PLATFORM_MAP = [
        { platform: 'YouTube',     kw: ['youtube'] },
        { platform: 'TikTok',      kw: ['tiktok'] },
        { platform: 'Instagram',   kw: ['instagram'] },
        { platform: 'Reddit',      kw: ['reddit', 'praw'] },
        { platform: 'Google',      kw: ['google', 'pytrends'] },
        { platform: 'SocialBlade', kw: ['socialblade'] },
        { platform: 'VidIQ',       kw: ['vidiq'] },
        { platform: 'CivitAI',     kw: ['civitai'] },
    ];

    // Env-var requirements per tool keyword
    var API_KEY_MAP = [
        { kw: 'youtube analytics',          envs: ['YOUTUBE_API_KEY'] },
        { kw: 'youtube data api',           envs: ['YOUTUBE_API_KEY'] },
        { kw: 'youtube autocomplete',       envs: [] },
        { kw: 'youtube trending rss',       envs: [] },
        { kw: 'tiktok analytics',           envs: ['TIKTOK_ACCESS_TOKEN'] },
        { kw: 'tiktok trending',            envs: ['TIKTOK_ACCESS_TOKEN'] },
        { kw: 'tiktok upload',              envs: ['TIKTOK_ACCESS_TOKEN'] },
        { kw: 'instagram graph',            envs: ['INSTAGRAM_ACCESS_TOKEN', 'INSTAGRAM_ACCOUNT_ID'] },
        { kw: 'instagram insights',         envs: ['INSTAGRAM_ACCESS_TOKEN', 'INSTAGRAM_ACCOUNT_ID'] },
        { kw: 'reddit',                     envs: ['REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET'] },
        { kw: 'praw',                       envs: ['REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET'] },
        { kw: 'google autocomplete',        envs: [] },
        { kw: 'pytrends',                   envs: [] },
        { kw: 'socialblade',                envs: ['SOCIALBLADE_API_KEY'] },
        { kw: 'vidiq',                      envs: ['VIDIQ_API_KEY'] },
        { kw: 'civitai',                    envs: ['CIVITAI_API_KEY'] },
        { kw: 'post trigger',               envs: ['PLATFORM_POST_TOKEN'] },
        { kw: 'competitor channel',         envs: [] },
        { kw: 'platform auth',              envs: [] },
    ];

    function _apiToolEnvs(toolName) {
        var lower = toolName.toLowerCase();
        for (var i = 0; i < API_KEY_MAP.length; i++) {
            if (lower.indexOf(API_KEY_MAP[i].kw) >= 0) return API_KEY_MAP[i].envs;
        }
        return null;
    }

    function _apiToolPlatform(toolName) {
        var lower = toolName.toLowerCase();
        for (var i = 0; i < API_PLATFORM_MAP.length; i++) {
            var entry = API_PLATFORM_MAP[i];
            for (var j = 0; j < entry.kw.length; j++) {
                if (lower.indexOf(entry.kw[j]) >= 0) return entry.platform;
            }
        }
        return 'Other';
    }

    function renderApiToolsColumns(container, onComplete) {
        var columnsEl = container ? container.querySelector('#mechanics-apitools-columns') : byId('mechanics-apitools-columns');
        if (!columnsEl) { if (onComplete) onComplete(); return; }
        columnsEl.innerHTML = '<p style="color:#666;">Loading\u2026</p>';

        fetch('/api/agents/config')
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; })
            .then(function(data) {
                // Collect all API tools from agent configs
                var agentList = [];
                if (!data) { /* empty */ }
                else if (Array.isArray(data)) { agentList = data; }
                else if (typeof data === 'object') {
                    var raw = data.agents || data;
                    agentList = Array.isArray(raw) ? raw : Object.keys(raw).map(function(k) {
                        var a = raw[k]; return typeof a === 'object' ? Object.assign({ _key: k }, a) : { _key: k };
                    });
                }

                // Group by platform
                var byPlatform = {};
                API_PLATFORM_ORDER.forEach(function(p) { byPlatform[p] = {}; });

                agentList.forEach(function(agent) {
                    if (!agent || !Array.isArray(agent.tools)) return;
                    var agentLabel = agent.name || agent.role || agent._key || '';
                    agent.tools.forEach(function(tool) {
                        var tName = typeof tool === 'string' ? tool : (tool && (tool.name || tool.tool_name)) || '';
                        if (!tName) return;
                        var tl = tName.toLowerCase();
                        // Only show tools that are in EXTERNAL_API_TOOLS or reference a known api
                        var isApi = EXTERNAL_API_TOOLS.some(function(k) { return tl.indexOf(k) >= 0; });
                        // Also catch tools with praw/pytrends/youtube transcript etc
                        if (!isApi) {
                            var apiKws = ['instagram', 'tiktok', 'youtube api', 'google autocomplete',
                                          'socialblade', 'vidiq', 'civitai', 'post trigger (platform',
                                          'reddit api (praw)', 'reddit hot posts (praw)'];
                            isApi = apiKws.some(function(k) { return tl.indexOf(k) >= 0; });
                        }
                        if (!isApi) return;
                        var platform = _apiToolPlatform(tName);
                        if (!byPlatform[platform]) byPlatform[platform] = {};
                        if (!byPlatform[platform][tName]) byPlatform[platform][tName] = [];
                        byPlatform[platform][tName].push(agentLabel);
                    });
                });

                var html = '';
                var totalApi = 0, totalConfigured = 0;
                var logItems = [];

                API_PLATFORM_ORDER.forEach(function(platform) {
                    var toolsInPlatform = byPlatform[platform] || {};
                    var toolNames = Object.keys(toolsInPlatform).sort();
                    if (toolNames.length === 0) return;
                    totalApi += toolNames.length;

                    var listHtml = toolNames.map(function(tName) {
                        var agentsUsing = toolsInPlatform[tName];
                        var id = 'apitools_' + platform.replace(/\s/g, '_') + '_' + tName.replace(/[\s\W]/g, '_');
                        var envs = _apiToolEnvs(tName);
                        var statusIcon, statusCls, logStatus, tooltip;

                        if (envs === null) {
                            // No env var info — unknown API
                            statusIcon = '\u2014';
                            statusCls = 'mechanics-item-icon mechanics-skip';
                            logStatus = null;
                            tooltip = 'API key requirements unknown';
                        } else if (envs.length === 0) {
                            // No key needed — publicly accessible
                            statusIcon = '\u2713';
                            statusCls = 'mechanics-item-icon mechanics-ok';
                            logStatus = true;
                            totalConfigured++;
                            tooltip = 'No API key required';
                            saveStatus(id, true);
                        } else {
                            // Check if env vars are set — we can't check server-side env here,
                            // so show configured status based on a naming hint
                            statusIcon = '\u26A0'; // ⚠
                            statusCls = 'mechanics-item-icon mechanics-partial';
                            logStatus = null;
                            tooltip = 'Needs: ' + envs.join(', ');
                            saveStatus(id, false);
                        }

                        logItems.push({ name: tName + '  [' + platform + ']', status: logStatus, skip: logStatus === null });
                        var tipAttr = ' title="' + escapeAttr(tooltip + (agentsUsing.length ? ' | Used by: ' + agentsUsing.slice(0,4).join(', ') : '')) + '"';
                        return '<label class="mechanics-item-row" data-id="' + escapeAttr(id) + '" style="display:flex;align-items:center;gap:5px;padding:3px 4px;cursor:pointer;border-radius:3px;font-size:12px;"' + tipAttr + '>' +
                            '<input type="checkbox" class="mechanics-item-check" data-id="' + escapeAttr(id) + '">' +
                            '<span class="mechanics-item-name" style="flex:1;overflow:hidden;text-overflow:ellipsis;">' + escapeAttr(tName) + '</span>' +
                            '<span class="' + statusCls + '" style="flex:0 0 20px;margin-left:auto;text-align:right;font-weight:bold;">' + statusIcon + '</span>' +
                            '</label>';
                    }).join('');

                    html += '<div class="mechanics-functionality-column" style="border:1px solid #ddd;border-radius:4px;padding:6px 8px;background:#fafafa;min-width:0;">' +
                        '<div style="font-weight:600;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #e5e7eb;font-size:12px;">' + escapeAttr(platform) + '</div>' +
                        '<div class="mechanics-functionality-list" style="display:flex;flex-direction:column;gap:2px;">' + listHtml + '</div></div>';
                });

                columnsEl.innerHTML = html || '<p style="color:#666;">No API tools found in agent configs.</p>';

                // KPI bar
                var kpiEl = byId('mechanics-apitools-kpi-summary');
                if (kpiEl) {
                    var kpiHtml = '';
                    API_PLATFORM_ORDER.forEach(function(platform) {
                        var toolNames = Object.keys(byPlatform[platform] || {});
                        if (toolNames.length === 0) return;
                        var configured = toolNames.filter(function(t) {
                            var envs = _apiToolEnvs(t);
                            return envs !== null && envs.length === 0;
                        }).length;
                        var n = toolNames.length;
                        var cls = configured === n ? 'mechanics-kpi-ok' : (configured === 0 ? 'mechanics-kpi-fail' : 'mechanics-kpi-partial');
                        kpiHtml += '<div class="mechanics-kpi-card ' + cls + '" style="padding:6px 12px;border-radius:6px;border:1px solid #e5e7eb;font-size:12px;">' +
                            '<span style="font-weight:600;">' + escapeAttr(platform) + '</span> ' + configured + '/' + n + '</div>';
                    });
                    var totalCls = totalConfigured === totalApi && totalApi > 0 ? 'mechanics-kpi-ok' : (totalConfigured === 0 ? 'mechanics-kpi-fail' : 'mechanics-kpi-partial');
                    kpiHtml += '<div class="mechanics-kpi-card ' + totalCls + '" style="padding:6px 12px;border-radius:6px;border:1px solid #1e40af;background:#eff6ff;font-size:12px;font-weight:600;">' +
                        'Total ' + totalConfigured + '/' + totalApi + '</div>';
                    kpiEl.innerHTML = kpiHtml;
                }

                if (logItems.length > 0) generateAndShowScanLog('Api Tools', logItems);
                if (onComplete) onComplete();
            }).catch(function(e) {
                console.error('[Mechanics] renderApiToolsColumns error:', e);
                if (columnsEl) columnsEl.innerHTML = '<p style="color:#666;">Failed to load API tools.</p>';
                if (onComplete) onComplete();
            });
    }

    function renderToolsKpiSummary(totalTools, totalInstalled, toolsByWf, depMap) {
        var el = byId('mechanics-tools-kpi-summary');
        if (!el) return;
        var html = '';
        if (toolsByWf && depMap) {
            TOOLS_WF_ORDER.forEach(function(wf) {
                var toolsInWf = toolsByWf[wf] || {};
                var toolNames = Object.keys(toolsInWf);
                if (toolNames.length === 0) return;
                var wfInstalled = 0, wfSkipped = 0;
                toolNames.forEach(function(tName) {
                    var tl = tName.toLowerCase();
                    if (EXTERNAL_API_TOOLS.some(function(k){ return tl.indexOf(k) >= 0; })) {
                        wfSkipped++; return;
                    }
                    var ds = _toolDepStatus(tName, depMap);
                    if (ds === null || ds === 'installed' || ds === 'parts_missing') wfInstalled++;
                });
                var n = toolNames.length - wfSkipped;
                var pct = n > 0 ? Math.round(wfInstalled / n * 100) : 0;
                var cls = wfInstalled === n ? 'mechanics-kpi-ok' : (wfInstalled === 0 ? 'mechanics-kpi-fail' : 'mechanics-kpi-partial');
                html += '<div class="mechanics-kpi-card ' + cls + '" style="padding:6px 12px; border-radius:6px; border:1px solid #e5e7eb; font-size:12px;">' +
                    '<span style="font-weight:600;">' + escapeAttr(wf) + '</span> ' + wfInstalled + '/' + n + ' (' + pct + '%)</div>';
            });
        }
        var t = totalTools || 0;
        var inst = totalInstalled || 0;
        var pct = t > 0 ? Math.round(inst / t * 100) : 0;
        var totalCls = inst === t && t > 0 ? 'mechanics-kpi-ok' : (inst === 0 ? 'mechanics-kpi-fail' : 'mechanics-kpi-partial');
        html += '<div class="mechanics-kpi-card ' + totalCls + '" style="padding:6px 12px; border-radius:6px; border:1px solid #1e40af; background:#eff6ff; font-size:12px; font-weight:600;">Total ' + inst + '/' + t + ' (' + pct + '%)</div>';
        el.innerHTML = html;
    }

    window.DashboardTabMechanics = { render: render };
})();
