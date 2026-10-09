// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Safety Subsystem Scan Specification
 * Scope, core tests, metrics, acceptance targets for the 8 safety gaps.
 * Used by Mechanics scan dashboard for detail view and report.
 */
(function () {
    'use strict';

    var SAFETY_SCAN_SPEC = {
        'Persistent Safety Audit Log': {
            scope: ['SAFETY_AUDIT_LOG_PATH', 'safety_audit_log.jsonl', 'init_safety_audit()', '_append_audit_to_file()'],
            coreTests: [
                'audit file created on first event',
                'JSONL append works for every safety event',
                'startup loads last 500 events correctly',
                'invalid/corrupted line handling does not crash subsystem',
                'event ordering preserved by timestamp',
                'concurrent append operations do not corrupt file',
                'restart preserves historical safety events',
                'emergency stop events persisted',
                'threshold changes persisted',
                'recovery confirmation persisted',
                'quarantine events persisted'
            ],
            metrics: ['audit persistence success rate', 'append latency per event', 'file corruption incidence', 'startup load success rate', 'event loss rate across restart', 'duplicate event rate', 'malformed-line recovery rate', 'percentage of safety actions with persisted audit entry', 'audit write failure count', 'audit flush latency'],
            acceptanceTargets: ['100% persistence for critical safety events', '0 silent event loss on normal shutdown/restart', 'startup recovery succeeds with partial file corruption', 'append latency remains within operational SLA']
        },
        'Graded Fail-Closed': {
            scope: ['_assess_telemetry_fail_closed()', 'telemetry_source = control_plane | local | none', 'protection mapping: none→level 3, local→level 2, partial→level 1'],
            coreTests: [
                'control plane telemetry available → no fail-closed escalation',
                'local fallback active → level 2 applied correctly',
                'no telemetry → level 3 applied correctly',
                'partial telemetry with missing critical metrics → level 1 or stronger',
                'telemetry source switching during runtime',
                'stale telemetry correctly classified',
                'telemetry error does not crash safety subsystem',
                'launch blocked appropriately when telemetry state insufficient',
                'dashboard shows degraded source accurately'
            ],
            metrics: ['fail-closed classification accuracy', 'telemetry-source detection accuracy', 'stale telemetry detection latency', 'false hard-stop rate', 'false warning/degradation rate', 'unsafe fail-open count', 'source-switch detection latency', 'percentage of launches blocked under missing telemetry', 'telemetry degradation event count'],
            acceptanceTargets: ['0 unsafe fail-open behavior for missing telemetry', '100% correct classification for none, local, control_plane', 'degraded telemetry state visible in UI and API', 'critical actions blocked when telemetry quality is insufficient']
        },
        'Recovery State Machine': {
            scope: ['auto-recovery for level 1–2', 'admin confirmation for level 3', 'staged recovery for level 4', 'recovery_state', 'can_resume_schedule', 'resume_blocked_reason', 'POST /api/safety/confirm_recovery'],
            coreTests: [
                'level 1 recovers automatically when metrics normalize',
                'level 2 recovers automatically when metrics normalize',
                'level 3 remains blocked until admin confirmation',
                'non-admin cannot confirm recovery',
                'level 4 staged recovery executes in correct order: ui, scheduler, agents, heavy_models',
                'recovery blocked if root condition still active',
                'recovery state survives restart if intended',
                'schedule cannot resume while blocked',
                'recovery audit event created at each stage',
                'failed stage blocks next stage',
                'repeated trip during recovery returns system to protected state'
            ],
            metrics: ['auto-recovery success rate', 'manual recovery confirmation success rate', 'unauthorized recovery attempt block rate', 'stage transition accuracy', 'recovery latency by protection level', 'premature recovery incident count', 'repeated-trip-after-recovery count', 'blocked-resume accuracy', 'recovery audit coverage', 'mean time from normalized telemetry to resumed operations'],
            acceptanceTargets: ['100% correct enforcement of admin-only recovery for level 3', '100% correct stage order for level 4 recovery', '0 resume while blocking condition remains', 'every recovery transition audited']
        },
        'Full Emergency Stop': {
            scope: ['POST /admin/jobs/runs/{run_id}/terminate', 'terminate_job_run()', 'POST /api/safety/emergency_stop_full', 'schedule pause + terminate all running jobs'],
            coreTests: [
                'emergency stop pauses schedule',
                'emergency stop terminates all running jobs',
                'new jobs cannot launch after stop',
                'repeated emergency stop call is idempotent or safely handled',
                'partial terminate failure still leaves system in protected state',
                'non-admin cannot trigger full emergency stop',
                'emergency stop audit event created',
                'emergency stop during degraded backend still works',
                'no orphan running jobs remain after stop',
                'emergency stop reason propagated to terminated jobs',
                'UI reflects emergency stop status immediately'
            ],
            metrics: ['emergency stop trigger latency', 'schedule-pause latency', 'running-job termination latency', 'percentage of running jobs terminated successfully', 'orphan-job count after stop', 'emergency stop audit coverage', 'unauthorized emergency stop attempts blocked', 'idempotent repeat-call success rate', 'residual compute activity after stop', 'time to fully quiescent system'],
            acceptanceTargets: ['100% schedule pause on emergency stop', '100% termination of targetable running jobs', '0 new launches after emergency stop until recovery', 'every invocation audited with actor and reason']
        },
        'Runtime Intervention Hooks': {
            scope: ['request_terminate_run(run_id, reason, terminate_fn)', 'request_reduce_concurrency(agent_id, new_max, reduce_fn)', 'reduce_agent_concurrency()'],
            coreTests: [
                'terminate hook kills targeted run',
                'terminate hook handles already-finished run gracefully',
                'terminate hook propagates reason',
                'concurrency reduction applies correct new max',
                'concurrency reduction blocks excessive future launches',
                'repeated reduction requests do not corrupt budget',
                'terminate/reduce actions audited',
                'hook failure does not crash safety subsystem',
                'runtime hook can be triggered from safety event',
                'agent-specific reduction does not affect unrelated agents unless intended'
            ],
            metrics: ['terminate hook success rate', 'terminate hook latency', 'concurrency reduction success rate', 'policy-to-action latency', 'audit coverage for intervention hooks', 'failed intervention count', 'wrong-target intervention count', 'reduced-load stabilization rate', 'number of crashes prevented by runtime reduction'],
            acceptanceTargets: ['runtime interventions execute reliably under stress', '100% reason propagation for forced termination', 'no silent failure of concurrency reduction action']
        },
        'VRAM-Aware Pre-Launch': {
            scope: ['can_launch_job(vram_required_mb, telemetry, device_id, thresholds, reserved_total_mb)', 'device-aware VRAM validation', 'min_reserve_vram_mb'],
            coreTests: [
                'launch allowed when required VRAM within safe capacity',
                'launch blocked when required VRAM exceeds safe allowance',
                'launch blocked when reserved total + required exceeds budget',
                'launch blocked when min reserve would be violated',
                'correct behavior per device_id in multi-GPU environment',
                'missing telemetry blocks or degrades per fail-closed rules',
                'invalid/missing vram_required_mb rejected',
                'fragmentation-reserve logic respected if implemented',
                'launch of multiple queued jobs preserves total reserve margin',
                'UI/API returns clear reason for rejection'
            ],
            metrics: ['VRAM launch-check accuracy', 'preventable OOM rate', 'blocked-unsafe-launch count', 'false-block rate for safe launches', 'device-mapping accuracy', 'required-vs-actual VRAM delta', 'reserve-margin violation count', 'pre-launch check latency', 'launches rejected due to insufficient telemetry', 'multi-GPU placement correctness'],
            acceptanceTargets: ['0 preventable OOMs from launches that should have been blocked', '100% enforcement of minimum reserve margin', '100% correct device-aware VRAM validation']
        },
        'Quarantine / Crash-Loop Isolation': {
            scope: ['record_agent_failure()', 'record_model_failure()', 'is_quarantined_agent()', 'is_quarantined_model()', 'get_quarantined_agents()', 'rolling 5-minute window', 'failure_patterns thresholds', 'quarantined_agents', 'quarantined_agent_ids'],
            coreTests: [
                'repeated agent failures within 5 min triggers quarantine',
                'repeated model failures within 5 min triggers quarantine',
                'failures below threshold do not quarantine',
                'quarantine expires or persists according to policy',
                'quarantined agent blocked from dispatch',
                'quarantined model blocked from launch',
                'quarantine state visible in safety status',
                'quarantine audit event created',
                'manual recovery/unquarantine path respects policy',
                'one bad agent does not quarantine unrelated agents',
                'one bad model does not block unrelated models',
                'rolling window resets correctly after time elapses'
            ],
            metrics: ['quarantine trigger accuracy', 'crash-loop detection latency', 'false quarantine rate', 'missed quarantine count', 'blocked-dispatch rate for quarantined agents', 'blocked-launch rate for quarantined models', 'quarantine duration accuracy', 'recovery-from-quarantine success rate', 'repeated-failure-after-unquarantine count', 'isolation containment rate'],
            acceptanceTargets: ['100% dispatch/launch block for quarantined entities', '0 unrelated entities quarantined due to wrong attribution', '100% quarantine visibility in status/API']
        },
        'Backend Enforcement Integration': {
            scope: ['pre-launch VRAM check', 'pre-dispatch quarantine check', 'schedule pause', 'full emergency stop', 'runtime concurrency reduction', 'recovery state machine', 'SAFETY_INTEGRATION.md'],
            coreTests: [
                'pre-launch VRAM check invoked on every heavy launch',
                'pre-dispatch quarantine check invoked on every dispatch',
                'schedule pause blocks dispatch globally',
                'emergency stop path overrides normal orchestration',
                'runtime concurrency reduction updates dispatch behavior',
                'recovery state machine gates restart/resume',
                'integration points still function after restart',
                'integration calls fail safely if control plane partially unavailable',
                'documentation matches actual implementation behavior',
                'backend enforcement exists even if UI bypass attempted'
            ],
            metrics: ['integration coverage %', 'percentage of heavy launches passing through safety pre-check', 'percentage of dispatches passing through quarantine check', 'bypass attempt success rate', 'enforcement latency at each integration point', 'documentation-to-implementation parity %', 'fail-safe behavior rate when integration dependency unavailable', 'unauthorized direct-backend action block rate'],
            acceptanceTargets: ['100% safety gating coverage on heavy launches and dispatches', '0 backend bypass of enforced safety controls', 'docs reflect real implementation with no critical drift']
        }
    };

    var SAFETY_KPIS = {
        persistence: ['persisted safety events', 'audit write failures', 'audit replay/load success', 'last persisted event timestamp'],
        failClosed: ['telemetry source state', 'stale telemetry count', 'fail-closed events by level', 'launches blocked due to telemetry quality'],
        recovery: ['current recovery state', 'recovery blocked reason', 'auto-recovery count', 'manual recovery confirmations', 'failed recoveries', 'repeated trips after recovery'],
        emergencyStop: ['emergency stop count', 'mean halt latency', 'terminated jobs count', 'residual orphan jobs count'],
        runtimeIntervention: ['forced terminations', 'concurrency reduction actions', 'intervention success rate', 'stabilization success rate'],
        vramEnforcement: ['unsafe launches blocked', 'required vs actual VRAM variance', 'preventable OOM count', 'reserve margin violations'],
        quarantine: ['quarantined agents count', 'quarantined models count', 'false quarantine incidents', 'blocked launches/dispatches from quarantine']
    };

    var RELEASE_GATE = [
        '100% persistent audit coverage for critical safety actions',
        '0 unsafe fail-open launches under missing telemetry',
        '100% admin enforcement for protected recovery and emergency actions',
        '100% heavy-job VRAM pre-launch checks',
        '100% dispatch blocking for quarantined agents/models',
        '0 new launches after full emergency stop until recovery',
        '100% staged order correctness for level 4 recovery',
        '0 backend safety-bypass findings in integration testing'
    ];

    var CROSS_CUTTING_SCENARIOS = {
        A: { name: 'Missing telemetry + heavy launch request', expected: ['fail-closed classification applied', 'launch blocked', 'audit event written', 'UI shows degraded source and protection level'], metrics: ['detection latency', 'launch block accuracy', 'audit persistence success'] },
        B: { name: 'Repeated OOM on same model', expected: ['model failure counter increments', 'model quarantined when threshold reached', 'further launches blocked', 'event persisted to JSONL', 'recovery required if policy says so'], metrics: ['OOM-to-quarantine latency', 'quarantine accuracy', 'repeated failed launch suppression rate'] },
        C: { name: 'Thermal event during running jobs', expected: ['runtime intervention hook fires', 'concurrency reduced and/or run terminated', 'emergency stop available if escalation continues', 'recovery blocked until normalized'], metrics: ['intervention latency', 'system stabilization time', 'prevented cascade count'] },
        D: { name: 'Full emergency stop during active workload', expected: ['schedule paused', 'running jobs terminated', 'no new launches', 'audit persisted', 'recovery state exposed'], metrics: ['total halt latency', 'residual active job count', 'audit completeness'] },
        E: { name: 'Level 4 staged recovery', expected: ['stages occur in order', 'failed stage prevents later stages', 'admin-only control where required', 'audit event per stage'], metrics: ['stage-order accuracy', 'stage success rate', 'blocked-advance accuracy'] }
    };

    window.SAFETY_SCAN_SPEC = SAFETY_SCAN_SPEC;
    window.SAFETY_KPIS = SAFETY_KPIS;
    window.SAFETY_RELEASE_GATE = RELEASE_GATE;
    window.SAFETY_CROSS_CUTTING_SCENARIOS = CROSS_CUTTING_SCENARIOS;
})();
