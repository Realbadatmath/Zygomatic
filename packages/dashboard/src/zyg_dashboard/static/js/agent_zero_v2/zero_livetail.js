/**
 * Agent Zero v2 — Live Tail.
 *
 * Faithful move of Static/js/dashboard_agent_zero.js lines 1749-2456: the SSE
 * log tail, the Tail Subs table, the pipeline Timeline tab, the flag popover
 * and the context-ledger popover. Same endpoints, same DOM ids, same
 * behaviour.
 *
 * The old dialog's internals (dialog, logEl, appendLog, byId, escapeHtml, the
 * gear-menu ids) are replaced by window.AgentZeroUI hooks plus local helpers.
 * Loads safely before or after zero_chat.js — it waits for the hook object
 * with a short poll (max 10 s).
 */
(function () {
    'use strict';

    var HOOK_POLL_MS = 150;
    var HOOK_POLL_MAX_MS = 10000;
    var GEAR_ID = 'zero-live-tail';

    var UI = null;                       // window.AgentZeroUI once resolved
    var liveTailEnabled = false;
    var liveTailDialog = null;
    var liveTailSSE = null;
    var liveTailLogEl = null;
    var liveTailSubsEl = null;
    var liveTailSubsInterval = null;
    var liveTailActiveTab = 'log';       // 'log' | 'subs' | 'timeline'
    var _liveTailTimelineInterval = null;
    var _liveTailCurrentPipelineId = null;
    var _ltCurrentPipelineId = null;     // last pipeline id seen on the SSE stream

    var _ltFlags = [];                   // [{level, stage, message, ts}]
    var _ltFlagPopover = null;           // popover DOM element
    var _ltCtxPopover = null;            // context ledger popover
    var _styleInjected = false;

    var LEVEL_COLORS = { INFO: '#58a6ff', WARNING: '#d29922', ERROR: '#f85149', SYS: '#3fb950' };

    // ── Local helpers (were module-wide in the old script) ─────────────────
    function byId(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ── Styles ─────────────────────────────────────────────────────────────
    // The old code styled Live Tail entirely with inline style attributes; the
    // inline styles below are kept verbatim, and the dialog shell is also
    // declared here as CSS scoped to the live-tail ids so the panel survives a
    // host stylesheet that resets inline-styled children.
    function injectStyles() {
        if (_styleInjected) return;
        _styleInjected = true;
        var style = document.createElement('style');
        style.id = 'zero-livetail-styles';
        style.textContent =
            '#live-tail-dialog{position:fixed;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;' +
            'border-radius:10px;display:flex;flex-direction:column;' +
            'font-family:"Consolas","Courier New",monospace;font-size:12px;z-index:99998;' +
            'box-shadow:0 8px 32px rgba(0,0,0,0.7);resize:both;overflow:hidden;}' +
            '#live-tail-dialog button{font-family:inherit;}' +
            '#live-tail-log,#live-tail-subs,#live-tail-timeline{flex:1;overflow-y:auto;}' +
            '#lt-flag-popover,#lt-ctx-popover{position:fixed;z-index:99999;' +
            'font-family:"Consolas","Courier New",monospace;font-size:11px;' +
            'display:flex;flex-direction:column;overflow:hidden;}';
        document.head.appendChild(style);
    }

    // ── Toggle ─────────────────────────────────────────────────────────────
    function toggleLiveTail() {
        liveTailEnabled = !liveTailEnabled;
        _setDot(liveTailEnabled);
        if (liveTailEnabled) {
            openLiveTailDialog();
        } else {
            closeLiveTailDialog();
        }
    }

    function _setDot(on) {
        if (UI && UI.setGearDot) { try { UI.setGearDot(GEAR_ID, !!on); } catch (_) {} }
    }

    // ── Anchor the dialog next to the Zero window ──────────────────────────
    function _anchorToWindow() {
        if (!liveTailDialog) return;
        var win = null;
        if (UI && UI.getWindowEl) { try { win = UI.getWindowEl(); } catch (_) {} }
        if (!win || !win.getBoundingClientRect) return;
        var r = win.getBoundingClientRect();
        if (!r.width && !r.height) return;
        var w = liveTailDialog.offsetWidth || 620;
        var h = liveTailDialog.offsetHeight || 400;
        // Prefer the free space left of the window, else right of it.
        var left = (r.left - w - 12 >= 4) ? (r.left - w - 12)
                 : Math.min(window.innerWidth - w - 4, r.right + 12);
        var top = Math.max(4, Math.min(window.innerHeight - h - 4, r.top));
        liveTailDialog.style.left = Math.max(4, left) + 'px';
        liveTailDialog.style.top = top + 'px';
        liveTailDialog.style.right = 'auto';
        liveTailDialog.style.bottom = 'auto';
    }

    function openLiveTailDialog() {
        if (liveTailDialog) {
            liveTailDialog.style.display = 'flex';
            _anchorToWindow();
            startSSE();
            _ltStartSubsPolling();
            return;
        }

        injectStyles();
        liveTailDialog = document.createElement('div');
        liveTailDialog.id = 'live-tail-dialog';
        liveTailDialog.style.cssText = [
            'position:fixed', 'bottom:80px', 'right:20px',
            'width:620px', 'height:400px',
            'background:#0d1117', 'color:#c9d1d9',
            'border:1px solid #30363d', 'border-radius:10px',
            'display:flex', 'flex-direction:column',
            'font-family:"Consolas","Courier New",monospace', 'font-size:12px',
            'z-index:99998', 'box-shadow:0 8px 32px rgba(0,0,0,0.7)',
            'resize:both', 'overflow:hidden',
        ].join(';');

        liveTailDialog.innerHTML =
            // ── header ──
            '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#161b22;border-bottom:1px solid #30363d;border-radius:10px 10px 0 0;cursor:move;user-select:none;" id="live-tail-header">' +
            '<span style="color:#58a6ff;font-weight:bold;font-size:13px;">&#9654; Live Tail</span>' +
            '<div style="display:flex;gap:6px;align-items:center;">' +
            '<button id="lt-flag-btn" title="Flags &amp; Warnings" style="position:relative;background:#21262d;color:#d29922;border:1px solid #30363d;border-radius:5px;padding:2px 8px;cursor:pointer;font-size:11px;">⚑ Flags <span id="lt-flag-badge" style="display:none;background:#f85149;color:#fff;border-radius:9px;padding:0 5px;font-size:10px;margin-left:2px;"></span></button>' +
            '<button id="lt-ctx-btn" title="Context Ledger — token usage per LLM call" style="background:#21262d;color:#3fb950;border:1px solid #30363d;border-radius:5px;padding:2px 8px;cursor:pointer;font-size:11px;">&#128196; CTX</button>' +
            '<button id="live-tail-clear" style="background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:5px;padding:2px 8px;cursor:pointer;font-size:11px;">Clear</button>' +
            '<button id="live-tail-close" style="background:#da3633;color:#fff;border:none;border-radius:5px;padding:2px 8px;cursor:pointer;font-size:13px;">&#10005;</button>' +
            '</div></div>' +
            // ── tab bar ──
            '<div style="display:flex;background:#161b22;border-bottom:1px solid #30363d;">' +
            '<button id="lt-tab-log" style="flex:1;padding:5px 0;background:#0d1117;color:#58a6ff;border:none;border-bottom:2px solid #58a6ff;cursor:pointer;font-size:11px;font-family:inherit;">Agent Activity</button>' +
            '<button id="lt-tab-subs" style="flex:1;padding:5px 0;background:#161b22;color:#8b949e;border:none;border-bottom:2px solid transparent;cursor:pointer;font-size:11px;font-family:inherit;">Tail Subs</button>' +
            '<button id="lt-tab-timeline" style="flex:1;padding:5px 0;background:#161b22;color:#8b949e;border:none;border-bottom:2px solid transparent;cursor:pointer;font-size:11px;font-family:inherit;">&#9200; Timeline</button>' +
            '</div>' +
            // ── log pane ──
            '<div id="live-tail-log" style="flex:1;overflow-y:auto;padding:8px 12px;line-height:1.6;display:block;"></div>' +
            // ── subs pane ──
            '<div id="live-tail-subs" style="flex:1;overflow-y:auto;padding:8px 12px;display:none;">' +
            '<table style="width:100%;border-collapse:collapse;" id="lt-subs-table">' +
            '<thead><tr style="color:#8b949e;font-size:10px;border-bottom:1px solid #30363d;">' +
            '<th style="text-align:left;padding:3px 6px;">PID</th>' +
            '<th style="text-align:left;padding:3px 6px;">Worker</th>' +
            '<th style="text-align:left;padding:3px 6px;">Started</th>' +
            '<th style="text-align:left;padding:3px 6px;">CPU%</th>' +
            '<th style="text-align:left;padding:3px 6px;">GPU%</th>' +
            '<th style="text-align:left;padding:3px 6px;">Max CPU</th>' +
            '<th style="text-align:left;padding:3px 6px;">Max GPU</th>' +
            '<th style="text-align:left;padding:3px 6px;">Status</th>' +
            '</tr></thead>' +
            '<tbody id="lt-subs-body"></tbody>' +
            '</table></div>' +
            // ── timeline pane ──
            '<div id="live-tail-timeline" style="flex:1;overflow-y:auto;padding:8px 12px;display:none;">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
            '<span style="color:#8b949e;font-size:10px;">Pipeline stage timings — live &#9210;</span>' +
            '<button id="lt-timeline-download" title="Download timeline as .txt" style="background:none;border:none;cursor:pointer;font-size:16px;color:#8b949e;padding:0 4px;">&#128196;</button>' +
            '</div>' +
            '<table style="width:100%;border-collapse:collapse;" id="lt-timeline-table">' +
            '<thead><tr style="color:#8b949e;font-size:10px;border-bottom:1px solid #30363d;">' +
            '<th style="text-align:left;padding:3px 8px;">Stage</th>' +
            '<th style="text-align:right;padding:3px 8px;white-space:nowrap;">Elapsed</th>' +
            '<th style="text-align:center;padding:3px 8px;">Status</th>' +
            '</tr></thead>' +
            '<tbody id="lt-timeline-body"></tbody>' +
            '</table>' +
            '<div id="lt-timeline-total" style="margin-top:8px;font-size:10px;color:#484f58;"></div>' +
            '</div>' +
            // ── status bar ──
            '<div style="padding:4px 12px;background:#161b22;border-top:1px solid #30363d;border-radius:0 0 10px 10px;color:#484f58;font-size:10px;" id="live-tail-status">Connecting…</div>';

        document.body.appendChild(liveTailDialog);

        liveTailLogEl  = byId('live-tail-log');
        liveTailSubsEl = byId('live-tail-subs');

        initLiveTailDrag(byId('live-tail-header'), liveTailDialog);
        _anchorToWindow();

        // Tab switching
        byId('lt-tab-log').onclick      = function () { _ltSwitchTab('log'); };
        byId('lt-tab-subs').onclick     = function () { _ltSwitchTab('subs'); };
        byId('lt-tab-timeline').onclick = function () { _ltSwitchTab('timeline'); };

        // The old markup called a page-global _ltDownloadTimeline() from an
        // inline onclick; inside this module it is bound in JS instead.
        byId('lt-timeline-download').onclick = _ltDownloadTimeline;

        byId('live-tail-close').onclick = function () {
            liveTailEnabled = false;
            _setDot(false);
            closeLiveTailDialog();
        };
        byId('live-tail-clear').onclick = function () {
            // Clear every pane regardless of which tab is active
            if (liveTailLogEl) liveTailLogEl.innerHTML = '';
            var subsBody = byId('lt-subs-body');
            if (subsBody) subsBody.innerHTML = '';
            var tlBody = byId('lt-timeline-body');
            if (tlBody) tlBody.innerHTML = '';
            var tlTotal = byId('lt-timeline-total');
            if (tlTotal) tlTotal.textContent = '';
            // Clear flags + badge so the error count resets
            _ltFlags = [];
            _ltUpdateFlagBadge();
            if (_ltFlagPopover && _ltFlagPopover.parentNode) {
                _ltFlagPopover.remove();
                _ltFlagPopover = null;
            }
        };

        // ── Flag button ──
        byId('lt-flag-btn').onclick = function (e) {
            e.stopPropagation();
            _ltToggleFlagPopover();
        };
        // ── Context Ledger button ──
        byId('lt-ctx-btn').onclick = function (e) {
            e.stopPropagation();
            _ltToggleCtxPopover();
        };
        // Load flags from server immediately
        _ltFetchFlags();

        startSSE();
        _ltStartSubsPolling();
    }

    function _ltSwitchTab(tab) {
        liveTailActiveTab = tab;
        var logPane      = byId('live-tail-log');
        var subsPane     = byId('live-tail-subs');
        var timelinePane = byId('live-tail-timeline');
        var tabLog       = byId('lt-tab-log');
        var tabSubs      = byId('lt-tab-subs');
        var tabTimeline  = byId('lt-tab-timeline');
        if (!logPane || !subsPane) return;

        // Reset all panes + tabs
        logPane.style.display  = 'none';
        subsPane.style.display = 'none';
        if (timelinePane) timelinePane.style.display = 'none';
        [tabLog, tabSubs, tabTimeline].forEach(function (t) {
            if (t) { t.style.background = '#161b22'; t.style.color = '#8b949e'; t.style.borderBottom = '2px solid transparent'; }
        });

        if (tab === 'log') {
            logPane.style.display = 'block';
            if (tabLog) { tabLog.style.background = '#0d1117'; tabLog.style.color = '#58a6ff'; tabLog.style.borderBottom = '2px solid #58a6ff'; }
        } else if (tab === 'subs') {
            subsPane.style.display = 'block';
            if (tabSubs) { tabSubs.style.background = '#0d1117'; tabSubs.style.color = '#3fb950'; tabSubs.style.borderBottom = '2px solid #3fb950'; }
        } else if (tab === 'timeline') {
            if (timelinePane) timelinePane.style.display = 'block';
            if (tabTimeline) { tabTimeline.style.background = '#0d1117'; tabTimeline.style.color = '#e3b341'; tabTimeline.style.borderBottom = '2px solid #e3b341'; }
            _ltStartTimelinePolling();
        }
    }

    // ── Tail Subs tab ──────────────────────────────────────────────────────
    function _ltStartSubsPolling() {
        if (liveTailSubsInterval) clearInterval(liveTailSubsInterval);
        _ltFetchSubs();
        liveTailSubsInterval = setInterval(_ltFetchSubs, 1000);
    }

    function _ltFetchSubs() {
        fetch('/api/subprocesses').then(function (r) { return r.json(); }).then(function (d) {
            var tbody = byId('lt-subs-body');
            if (!tbody) return;
            var procs = (d.subprocesses || []).slice(0, 120);
            // Build map of existing rows
            var existingPids = {};
            var rows = tbody.querySelectorAll('tr[data-pid]');
            rows.forEach(function (r) { existingPids[r.getAttribute('data-pid')] = r; });
            procs.forEach(function (p) {
                var pidStr = String(p.pid);
                var isSynthetic = p.pid >= 10000000;
                var statusColor = p.status === 'running'  ? '#3fb950'
                                : p.status === 'done'     ? '#8b949e'
                                : p.status === 'queued'   ? '#e3b341'
                                : p.status === 'pipeline' ? '#58a6ff'
                                : p.status === 'failed'   ? '#f85149'
                                : p.status === 'killed'   ? '#f85149'
                                : '#3fb950';
                var statusText  = p.status === 'done'     ? '&#10003; done'
                                : p.status === 'killed'   ? '&#10008; killed'
                                : p.status === 'failed'   ? '&#10008; failed'
                                : p.status === 'queued'   ? '&#9900; queued'
                                : p.status === 'pipeline' ? '&#9654; active'
                                : '&#9679; running';
                var ts = (p.started || '').replace('T', ' ').substring(0, 19);
                var cpu  = (!isSynthetic && p.cpu_pct  != null) ? p.cpu_pct.toFixed(1)  : '—';
                var gpu  = (!isSynthetic && p.gpu_pct  != null) ? p.gpu_pct.toFixed(1)  : '—';
                var mcpu = (!isSynthetic && p.max_cpu_pct != null) ? p.max_cpu_pct.toFixed(1) : '—';
                var mgpu = (!isSynthetic && p.max_gpu_pct != null) ? p.max_gpu_pct.toFixed(1) : '—';
                var pidDisplay = isSynthetic ? '—' : escapeHtml(pidStr);
                if (existingPids[pidStr]) {
                    var cells = existingPids[pidStr].querySelectorAll('td');
                    // Update label in case it changed (queued→running transition)
                    if (cells[1]) { cells[1].textContent = p.label || ''; cells[1].title = p.label || ''; }
                    if (cells[3]) cells[3].textContent = cpu;
                    if (cells[4]) cells[4].textContent = gpu;
                    if (cells[5]) cells[5].textContent = mcpu;
                    if (cells[6]) cells[6].textContent = mgpu;
                    if (cells[7]) cells[7].innerHTML = '<span style="color:' + statusColor + ';">' + statusText + '</span>';
                } else {
                    var tr = document.createElement('tr');
                    tr.setAttribute('data-pid', pidStr);
                    tr.style.borderBottom = '1px solid #161b22';
                    tr.style.cursor = 'pointer';
                    // Pipeline/queued markers get slightly different row background
                    if (p.status === 'pipeline') tr.style.background = 'rgba(88,166,255,0.05)';
                    if (p.status === 'queued')   tr.style.background = 'rgba(227,179,65,0.05)';
                    tr.innerHTML =
                        '<td style="padding:3px 6px;color:#484f58;font-size:10px;">' + pidDisplay + '</td>' +
                        '<td style="padding:3px 6px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(p.label || '') + '">' + escapeHtml(p.label || '') + '</td>' +
                        '<td style="padding:3px 6px;color:#484f58;font-size:10px;">' + escapeHtml(ts) + '</td>' +
                        '<td style="padding:3px 6px;">' + cpu + '</td>' +
                        '<td style="padding:3px 6px;">' + gpu + '</td>' +
                        '<td style="padding:3px 6px;">' + mcpu + '</td>' +
                        '<td style="padding:3px 6px;">' + mgpu + '</td>' +
                        '<td style="padding:3px 6px;"><span style="color:' + statusColor + ';">' + statusText + '</span></td>';
                    tr.onclick = (function (proc) { return function () { _ltOpenWorkerDetail(proc); }; })(p);
                    tbody.insertBefore(tr, tbody.firstChild);
                }
            });
        }).catch(function () {});
    }

    function _ltOpenWorkerDetail(p) {
        // Fetch fresh data with samples
        fetch('/api/subprocesses/' + p.pid).then(function (r) { return r.json(); }).then(function (data) {
            if (data.error) data = p; // fallback to passed object
            var started = (data.started || '').replace('T', ' ').substring(0, 19);
            var ended   = data.ended ? (data.ended || '').replace('T', ' ').substring(0, 19) : '—';
            var dur = '—';
            if (data.started && data.ended) {
                try {
                    var ms = new Date(data.ended) - new Date(data.started);
                    var s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
                    dur = h ? h + 'h ' + (m % 60) + 'm ' + (s % 60) + 's' : m ? m + 'm ' + (s % 60) + 's' : s + 's';
                } catch (_) {}
            }
            var samples = data.samples || [];
            var samplesHtml = '';
            if (samples.length) {
                samplesHtml = '<table style="width:100%;border-collapse:collapse;margin-top:10px;">' +
                    '<thead><tr style="color:#8b949e;font-size:10px;border-bottom:1px solid #30363d;">' +
                    '<th style="text-align:left;padding:2px 6px;">Time</th>' +
                    '<th style="text-align:left;padding:2px 6px;">CPU%</th>' +
                    '<th style="text-align:left;padding:2px 6px;">GPU%</th>' +
                    '</tr></thead><tbody>';
                samples.slice(-30).forEach(function (s) {
                    samplesHtml += '<tr><td style="padding:2px 6px;color:#484f58;font-size:10px;">' + (s.t || '').replace('T', ' ').substring(0, 19) + '</td>' +
                        '<td style="padding:2px 6px;">' + (s.cpu || 0).toFixed(1) + '</td>' +
                        '<td style="padding:2px 6px;">' + (s.gpu || 0).toFixed(1) + '</td></tr>';
                });
                samplesHtml += '</tbody></table>';
            }
            var dlg = document.createElement('div');
            dlg.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
                'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:10px;' +
                'width:480px;max-height:calc(70vh / var(--ui-zoom,1));display:flex;flex-direction:column;' +
                'font-family:"Consolas","Courier New",monospace;font-size:12px;z-index:99999;' +
                'box-shadow:0 8px 32px rgba(0,0,0,0.8);overflow:hidden;';
            dlg.innerHTML =
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#161b22;border-bottom:1px solid #30363d;">' +
                '<span style="color:#58a6ff;font-weight:bold;">Worker Detail — PID ' + escapeHtml(String(data.pid || '')) + '</span>' +
                '<button style="background:#da3633;color:#fff;border:none;border-radius:5px;padding:2px 8px;cursor:pointer;">&#10005;</button>' +
                '</div>' +
                '<div style="padding:12px;overflow-y:auto;flex:1;">' +
                '<p style="margin:4px 0;"><strong>Label:</strong> ' + escapeHtml(data.label || '—') + '</p>' +
                '<p style="margin:4px 0;"><strong>Pipeline:</strong> ' + escapeHtml(data.pipeline_id || '—') + '</p>' +
                '<p style="margin:4px 0;"><strong>Started:</strong> ' + escapeHtml(started) + '</p>' +
                '<p style="margin:4px 0;"><strong>Ended:</strong> ' + escapeHtml(ended) + '</p>' +
                '<p style="margin:4px 0;"><strong>Duration:</strong> ' + escapeHtml(dur) + '</p>' +
                '<p style="margin:4px 0;"><strong>Max CPU:</strong> ' + (data.max_cpu_pct || 0).toFixed(1) + '%</p>' +
                '<p style="margin:4px 0;"><strong>Max GPU:</strong> ' + (data.max_gpu_pct || 0).toFixed(1) + '%</p>' +
                samplesHtml +
                '</div>';
            dlg.querySelector('button').onclick = function () { dlg.remove(); };
            document.body.appendChild(dlg);
        }).catch(function () {});
    }

    // ── Timeline tab ────────────────────────────────────────────────────────
    function _ltStartTimelinePolling() {
        if (_liveTailTimelineInterval) clearInterval(_liveTailTimelineInterval);
        _ltFetchTimeline();
        _liveTailTimelineInterval = setInterval(_ltFetchTimeline, 2000);
    }

    function _fmtSecs(s) {
        if (s == null || isNaN(s)) return '—';
        s = Math.round(s);
        if (s < 60) return s + 's';
        return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
    }

    function _ltFetchTimeline() {
        // First resolve active pipeline id
        fetch('/api/pipeline/active').then(function (r) { return r.json(); }).then(function (d) {
            var pid = d.pipeline_id || null;
            if (pid) _liveTailCurrentPipelineId = pid;
            var resolvedId = _liveTailCurrentPipelineId;
            if (!resolvedId) {
                var tbody = byId('lt-timeline-body');
                if (tbody) tbody.innerHTML = '<tr><td colspan="3" style="color:#484f58;padding:10px 8px;font-size:11px;">No active pipeline. Run a video to see timeline.</td></tr>';
                return;
            }
            fetch('/api/pipeline/timeline/' + resolvedId).then(function (r) { return r.json(); }).then(function (td) {
                var tbody = byId('lt-timeline-body');
                if (!tbody) return;
                // The endpoint returns 'stages' — reading 'stage_timeline' here
                // left the table permanently empty and the total at 0s.
                var stages = td.stages || td.stage_timeline || [];
                var pipelineLive = td.runtime_running === true;
                tbody.innerHTML = '';
                stages.forEach(function (s) {
                    var elapsed = s.elapsed_s;
                    var liveCounter = '';
                    // A stage record left open by a crash still says 'running'.
                    // Only tick it against the wall clock when the SERVER says a
                    // worker is actually live, or the row counts up forever.
                    if (s.status === 'running' && s.started_at && pipelineLive) {
                        // Compute live elapsed from ISO timestamp. Server emits
                        // Amsterdam-aware timestamps with offset (e.g. +02:00);
                        // legacy runs may be naive UTC — accept both.
                        var _hasTz = s.started_at.endsWith('Z') || /[+\-]\d{2}:?\d{2}$/.test(s.started_at);
                        var startMs = new Date(_hasTz ? s.started_at : (s.started_at + 'Z')).getTime();
                        elapsed = (Date.now() - startMs) / 1000;
                        liveCounter = ' <span style="color:#e3b341;font-size:9px;">&#9210;</span>';
                    }
                    var statusIcon = s.status === 'done'    ? '<span style="color:#3fb950;">&#10003;</span>'
                                   : s.status === 'running' ? '<span style="color:#e3b341;">&#9679;</span>'
                                   : s.status === 'failed'  ? '<span style="color:#f85149;">&#10007;</span>'
                                   : '<span style="color:#484f58;">&#9675;</span>';
                    var tr = document.createElement('tr');
                    tr.style.cssText = 'border-bottom:1px solid #21262d;font-size:11px;';
                    tr.innerHTML =
                        '<td style="padding:4px 8px;color:#c9d1d9;">' + (s.name || '') + '</td>' +
                        '<td style="padding:4px 8px;text-align:right;color:#58a6ff;white-space:nowrap;">' + _fmtSecs(elapsed) + liveCounter + '</td>' +
                        '<td style="padding:4px 8px;text-align:center;">' + statusIcon + '</td>';
                    tbody.appendChild(tr);
                });
                var totalDiv = byId('lt-timeline-total');
                if (totalDiv) {
                    // Total comes from the server (pipeline_runtime.py). Summing
                    // the rows here double-counted every nested stage — Stage 3.6
                    // runs inside 3.5, Color Grade inside Stage 6 — so the total
                    // grew past the run's own wall clock.
                    var pStatus = td.status || '';
                    var totalSecs = td.total_elapsed_s;
                    var totalLabel = totalSecs == null ? 'Elapsed: —'
                                   : pStatus === 'completed' ? 'Total: ' + _fmtSecs(totalSecs) + ' ✓'
                                   : pStatus === 'failed'    ? 'Failed after ' + _fmtSecs(totalSecs)
                                   : pipelineLive            ? 'Elapsed so far: ' + _fmtSecs(totalSecs)
                                   : 'Ran for ' + _fmtSecs(totalSecs) + ' (clock paused)';
                    totalDiv.textContent = totalLabel;
                }
            }).catch(function () {});
        }).catch(function () {});
    }

    function _ltDownloadTimeline() {
        var pid = _liveTailCurrentPipelineId;
        if (!pid) { alert('No pipeline timeline available yet.'); return; }
        window.location = '/api/pipeline/timeline/' + pid + '/download';
    }

    // ── Flags ──────────────────────────────────────────────────────────────
    function _ltFetchFlags() {
        fetch('/api/pipeline/flags').then(function (r) { return r.json(); }).then(function (d) {
            _ltFlags = d.flags || [];
            _ltUpdateFlagBadge();
            if (_ltFlagPopover && _ltFlagPopover.parentNode) _ltRenderFlagList();
        }).catch(function () {});
    }

    function _ltUpdateFlagBadge() {
        var badge = byId('lt-flag-badge');
        if (!badge) return;
        var count = _ltFlags.length;
        if (count > 0) {
            badge.textContent = count;
            badge.style.display = 'inline';
            var btn = byId('lt-flag-btn');
            if (btn) btn.style.color = count > 0 ? '#f85149' : '#d29922';
        } else {
            badge.style.display = 'none';
            var btn2 = byId('lt-flag-btn');
            if (btn2) btn2.style.color = '#d29922';
        }
    }

    function _ltToggleFlagPopover() {
        if (_ltFlagPopover && _ltFlagPopover.parentNode) {
            _ltFlagPopover.remove();
            _ltFlagPopover = null;
            return;
        }
        _ltFlagPopover = document.createElement('div');
        _ltFlagPopover.id = 'lt-flag-popover';
        _ltFlagPopover.style.cssText = [
            'position:fixed', 'background:#161b22', 'border:1px solid #f85149',
            'border-radius:8px', 'padding:0', 'z-index:99999',
            'width:480px', 'max-height:320px',
            'box-shadow:0 8px 32px rgba(0,0,0,0.8)',
            'font-family:"Consolas","Courier New",monospace', 'font-size:11px',
            'overflow:hidden', 'display:flex', 'flex-direction:column',
        ].join(';');
        // Position below flag button
        var btn = byId('lt-flag-btn');
        if (btn) {
            var r = btn.getBoundingClientRect();
            _ltFlagPopover.style.top  = (r.bottom + 6) + 'px';
            _ltFlagPopover.style.left = Math.max(4, r.right - 480) + 'px';
        }
        _ltFlagPopover.innerHTML =
            '<div style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px;background:#21262d;border-bottom:1px solid #30363d;">' +
            '<span style="color:#f85149;font-weight:bold;">⚑ Pipeline Flags &amp; Warnings</span>' +
            '<button id="lt-flag-close" style="background:none;border:none;color:#8b949e;cursor:pointer;font-size:13px;">&#10005;</button>' +
            '</div>' +
            '<div id="lt-flag-list" style="overflow-y:auto;flex:1;"></div>' +
            '<div style="padding:4px 10px;background:#21262d;border-top:1px solid #30363d;color:#484f58;font-size:10px;" id="lt-flag-footer"></div>';
        document.body.appendChild(_ltFlagPopover);
        _ltRenderFlagList();
        _ltFlagPopover.querySelector('#lt-flag-close').onclick = function () {
            if (_ltFlagPopover) { _ltFlagPopover.remove(); _ltFlagPopover = null; }
        };
        // Close when clicking outside
        setTimeout(function () {
            document.addEventListener('click', function _ltOutside(ev) {
                if (_ltFlagPopover && !_ltFlagPopover.contains(ev.target)) {
                    var flagBtn = byId('lt-flag-btn');
                    if (!flagBtn || !flagBtn.contains(ev.target)) {
                        _ltFlagPopover.remove();
                        _ltFlagPopover = null;
                    }
                }
                document.removeEventListener('click', _ltOutside);
            });
        }, 50);
    }

    function _ltRenderFlagList() {
        var list = byId('lt-flag-list');
        var footer = byId('lt-flag-footer');
        if (!list) return;
        if (_ltFlags.length === 0) {
            list.innerHTML = '<div style="padding:16px;color:#3fb950;text-align:center;">✓ No flags — pipeline running clean</div>';
            if (footer) footer.textContent = '';
            return;
        }
        var html = '';
        _ltFlags.forEach(function (f) {
            var isErr = f.level === 'ERROR';
            var color = isErr ? '#f85149' : '#d29922';
            var icon  = isErr ? '✗' : '⚠';
            var ts = '';
            if (f.ts) {
                try {
                    var _hasTz = f.ts.endsWith('Z') || /[+\-]\d{2}:?\d{2}$/.test(f.ts);
                    var d = new Date(_hasTz ? f.ts : (f.ts + 'Z'));
                    var pad = function (n) { return n < 10 ? '0' + n : n; };
                    ts = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
                } catch (_) { ts = f.ts.substring(11, 19); }
            }
            html += '<div style="padding:6px 10px;border-bottom:1px solid #21262d;display:flex;gap:8px;align-items:flex-start;">' +
                '<span style="color:' + color + ';flex-shrink:0;font-weight:bold;">' + icon + '</span>' +
                '<div style="flex:1;">' +
                '<div style="color:' + color + ';font-weight:bold;font-size:10px;">' + escapeHtml(f.stage || '?') +
                (ts ? ' <span style="color:#484f58;font-weight:normal;">' + ts + '</span>' : '') + '</div>' +
                '<div style="color:#c9d1d9;margin-top:2px;">' + escapeHtml(f.message || '') + '</div>' +
                '</div></div>';
        });
        list.innerHTML = html;
        if (footer) footer.textContent = _ltFlags.length + ' flag' + (_ltFlags.length !== 1 ? 's' : '') + ' from last pipeline run';
    }

    // ── Context ledger ─────────────────────────────────────────────────────
    function _ltToggleCtxPopover() {
        if (_ltCtxPopover && _ltCtxPopover.parentNode) {
            _ltCtxPopover.remove();
            _ltCtxPopover = null;
            return;
        }
        _ltCtxPopover = document.createElement('div');
        _ltCtxPopover.id = 'lt-ctx-popover';
        _ltCtxPopover.style.cssText = [
            'position:fixed', 'background:#161b22', 'border:1px solid #3fb950',
            'border-radius:8px', 'padding:0', 'z-index:99999',
            'width:640px', 'max-height:440px',
            'box-shadow:0 8px 32px rgba(0,0,0,0.8)',
            'font-family:"Consolas","Courier New",monospace', 'font-size:11px',
            'overflow:hidden', 'display:flex', 'flex-direction:column',
        ].join(';');
        var btn = byId('lt-ctx-btn');
        if (btn) {
            var r = btn.getBoundingClientRect();
            _ltCtxPopover.style.top  = (r.bottom + 6) + 'px';
            _ltCtxPopover.style.left = Math.max(4, r.right - 640) + 'px';
        }
        _ltCtxPopover.innerHTML =
            '<div style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px;background:#21262d;border-bottom:1px solid #30363d;">' +
            '<span style="color:#3fb950;font-weight:bold;">&#128196; Context Ledger</span>' +
            '<div style="display:flex;gap:6px;align-items:center;">' +
            '<span id="lt-ctx-pid" style="color:#484f58;font-size:10px;"></span>' +
            '<button id="lt-ctx-refresh" style="background:none;border:1px solid #30363d;border-radius:4px;color:#8b949e;cursor:pointer;font-size:10px;padding:1px 6px;">&#8635; Refresh</button>' +
            '<button id="lt-ctx-close" style="background:none;border:none;color:#8b949e;cursor:pointer;font-size:13px;">&#10005;</button>' +
            '</div></div>' +
            '<div id="lt-ctx-summary" style="padding:5px 10px;background:#0d1117;border-bottom:1px solid #30363d;color:#8b949e;font-size:10px;line-height:1.6;"></div>' +
            '<div id="lt-ctx-body" style="overflow-y:auto;flex:1;"></div>' +
            '<div style="padding:3px 10px;background:#21262d;border-top:1px solid #30363d;color:#484f58;font-size:10px;">Persisted permanently · context_ledger.jsonl · never rotated</div>';
        document.body.appendChild(_ltCtxPopover);
        _ltCtxPopover.querySelector('#lt-ctx-close').onclick = function () {
            if (_ltCtxPopover) { _ltCtxPopover.remove(); _ltCtxPopover = null; }
        };
        _ltCtxPopover.querySelector('#lt-ctx-refresh').onclick = _ltFetchCtxLedger;
        setTimeout(function () {
            document.addEventListener('click', function _ltCtxOut(ev) {
                if (_ltCtxPopover && !_ltCtxPopover.contains(ev.target)) {
                    var b = byId('lt-ctx-btn');
                    if (!b || !b.contains(ev.target)) {
                        _ltCtxPopover.remove();
                        _ltCtxPopover = null;
                    }
                }
                document.removeEventListener('click', _ltCtxOut);
            });
        }, 50);
        _ltFetchCtxLedger();
    }

    function _ltFetchCtxLedger() {
        var body     = byId('lt-ctx-body');
        var summary  = byId('lt-ctx-summary');
        var pidLabel = byId('lt-ctx-pid');
        if (!body) return;
        body.innerHTML = '<div style="padding:14px;color:#484f58;text-align:center;">Loading…</div>';
        fetch('/api/pipeline/active').then(function (r) { return r.json(); }).then(function (d) {
            var pid = (d && (d.pipeline_id || d.active_pipeline_id)) || '';
            var url = pid ? '/api/context_ledger?pipeline_id=' + encodeURIComponent(pid)
                          : '/api/context_ledger?latest=1';
            return fetch(url);
        }).then(function (r) { return r.json(); }).then(function (data) {
            var entries = data.entries || [];
            var sum     = data.summary || {};
            if (pidLabel) pidLabel.textContent = data.pipeline_id ? data.pipeline_id.substring(0, 14) + '…' : 'latest run';
            if (summary) {
                var modelParts = Object.entries(sum.by_model || {}).map(function (kv) {
                    return '<b style="color:#58a6ff;">' + escapeHtml(String(kv[0])) + '</b> ' + Number(kv[1]).toLocaleString() + ' tok';
                }).join(' &nbsp;·&nbsp; ');
                summary.innerHTML =
                    '<b style="color:#3fb950;">' + (sum.total_tokens || 0).toLocaleString() + ' total tokens</b>' +
                    ' &nbsp;·&nbsp; <b>' + (sum.call_count || 0) + '</b> LLM calls' +
                    (modelParts ? '<br>' + modelParts : '');
            }
            if (!entries.length) {
                body.innerHTML = '<div style="padding:16px;color:#484f58;text-align:center;">No context data recorded for this pipeline yet.</div>';
                return;
            }
            var rows = entries.map(function (e) {
                var ts  = (e.timestamp || '').replace('T', ' ').substring(0, 19);
                var pct = typeof e.context_pct === 'number' ? e.context_pct.toFixed(1)
                                                            : ((e.total_tokens || 0) / 128000 * 100).toFixed(1);
                var barW  = Math.min(100, parseFloat(pct));
                var barColor = barW > 80 ? '#f85149' : barW > 50 ? '#d29922' : '#3fb950';
                return '<tr style="border-bottom:1px solid #21262d;">' +
                    '<td style="padding:3px 5px;color:#484f58;white-space:nowrap;font-size:10px;">' + escapeHtml(ts) + '</td>' +
                    '<td style="padding:3px 5px;color:#8b949e;">' + escapeHtml(e.stage || '?') + '</td>' +
                    '<td style="padding:3px 5px;color:#58a6ff;">' + escapeHtml(e.model || '?') + '</td>' +
                    '<td style="padding:3px 5px;text-align:right;color:#8b949e;">' + (e.prompt_tokens || 0).toLocaleString() + '</td>' +
                    '<td style="padding:3px 5px;text-align:right;color:#8b949e;">' + (e.completion_tokens || 0).toLocaleString() + '</td>' +
                    '<td style="padding:3px 5px;text-align:right;color:#c9d1d9;font-weight:bold;">' + (e.total_tokens || 0).toLocaleString() + '</td>' +
                    '<td style="padding:3px 8px;min-width:90px;">' +
                      '<div style="background:#21262d;border-radius:3px;height:7px;width:80px;overflow:hidden;display:inline-block;vertical-align:middle;">' +
                      '<div style="background:' + barColor + ';height:100%;width:' + barW + '%;"></div></div>' +
                      '<span style="font-size:9px;color:' + barColor + ';margin-left:4px;">' + pct + '%</span>' +
                    '</td>' +
                    '</tr>';
            }).join('');
            body.innerHTML =
                '<table style="width:100%;border-collapse:collapse;">' +
                '<thead><tr style="color:#484f58;font-size:10px;border-bottom:1px solid #30363d;background:#161b22;">' +
                '<th style="padding:3px 5px;text-align:left;position:sticky;top:0;background:#161b22;">Timestamp (UTC)</th>' +
                '<th style="padding:3px 5px;text-align:left;position:sticky;top:0;background:#161b22;">Stage</th>' +
                '<th style="padding:3px 5px;text-align:left;position:sticky;top:0;background:#161b22;">Model</th>' +
                '<th style="padding:3px 5px;text-align:right;position:sticky;top:0;background:#161b22;">Prompt</th>' +
                '<th style="padding:3px 5px;text-align:right;position:sticky;top:0;background:#161b22;">Compl.</th>' +
                '<th style="padding:3px 5px;text-align:right;position:sticky;top:0;background:#161b22;">Total</th>' +
                '<th style="padding:3px 5px;position:sticky;top:0;background:#161b22;">Context %</th>' +
                '</tr></thead>' +
                '<tbody>' + rows + '</tbody>' +
                '</table>';
        }).catch(function (err) {
            if (body) body.innerHTML = '<div style="padding:16px;color:#f85149;">Failed to load: ' + err + '</div>';
        });
    }

    // ── Teardown ───────────────────────────────────────────────────────────
    function closeLiveTailDialog() {
        if (liveTailSSE) { liveTailSSE.close(); liveTailSSE = null; }
        if (liveTailSubsInterval) { clearInterval(liveTailSubsInterval); liveTailSubsInterval = null; }
        if (_liveTailTimelineInterval) { clearInterval(_liveTailTimelineInterval); _liveTailTimelineInterval = null; }
        if (liveTailDialog) { liveTailDialog.style.display = 'none'; }
    }

    // ── SSE log stream ─────────────────────────────────────────────────────
    function startSSE() {
        if (liveTailSSE) { liveTailSSE.close(); }
        var status = byId('live-tail-status');
        liveTailSSE = new EventSource('/api/live_log');
        liveTailSSE.onopen = function () {
            if (status) status.textContent = 'Connected — streaming live';
            if (status) status.style.color = '#3fb950';
        };
        liveTailSSE.onmessage = function (e) {
            try {
                var entry = JSON.parse(e.data);
                appendLiveTail(entry);
                // Live flag capture — add WARNING/ERROR entries to flags in real-time
                if (entry.level === 'WARNING' || entry.level === 'ERROR') {
                    // Reset flags when a new pipeline run starts
                    if (entry.pipeline_id && entry.pipeline_id !== _ltCurrentPipelineId) {
                        _ltCurrentPipelineId = entry.pipeline_id;
                        _ltFlags = [];
                        _ltUpdateFlagBadge();
                    }
                    var msgKey = (entry.msg || '').substring(0, 120);
                    var alreadyHave = _ltFlags.some(function (f) { return (f.message || '').substring(0, 120) === msgKey; });
                    if (!alreadyHave) {
                        _ltFlags.push({
                            level: entry.level,
                            stage: (entry.msg || '').replace(/^\[([^\]]+)\].*/, '$1') || '?',
                            message: entry.msg || '',
                            ts: entry.ts || '',
                        });
                        _ltUpdateFlagBadge();
                        if (_ltFlagPopover && _ltFlagPopover.parentNode) _ltRenderFlagList();
                    }
                }
            } catch (_) {
                appendLiveTail({ msg: e.data, level: 'INFO' });
            }
        };
        liveTailSSE.onerror = function () {
            if (status) { status.textContent = 'Disconnected — retrying…'; status.style.color = '#f85149'; }
        };
    }

    function appendLiveTail(entry) {
        if (!liveTailLogEl) return;
        var color = LEVEL_COLORS[entry.level] || '#c9d1d9';
        var ts = '';
        if (entry.ts) {
            try {
                // Server emits Amsterdam-aware ISO with offset; legacy lines
                // are naive UTC. Both render as the correct local wall-clock.
                var _hasTz = entry.ts.endsWith('Z') || /[+\-]\d{2}:?\d{2}$/.test(entry.ts);
                var d = new Date(_hasTz ? entry.ts : (entry.ts + 'Z'));
                var pad = function (n) { return n < 10 ? '0' + n : n; };
                ts = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
                     ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
            } catch (_) {
                ts = entry.ts.replace('T', ' ').substring(0, 19);
            }
        }
        var line = document.createElement('div');
        // Highlight WARNING/ERROR rows with a subtle background
        var rowBg = entry.level === 'ERROR'    ? 'background:rgba(248,81,73,0.08);' :
                    entry.level === 'WARNING'  ? 'background:rgba(210,153,34,0.08);' : '';
        line.style.cssText = 'padding:1px 0;border-bottom:1px solid #161b22;white-space:pre-wrap;word-break:break-all;' + rowBg;
        line.innerHTML =
            (ts ? '<span style="color:#484f58;">' + ts + ' </span>' : '') +
            '<span style="color:' + color + ';font-weight:bold;">[' + (entry.level || 'INFO') + ']</span> ' +
            '<span>' + escapeHtml(entry.msg || '') + '</span>';
        liveTailLogEl.appendChild(line);
        // Auto-scroll to bottom
        liveTailLogEl.scrollTop = liveTailLogEl.scrollHeight;
        // Keep max 500 lines
        while (liveTailLogEl.children.length > 500) {
            liveTailLogEl.removeChild(liveTailLogEl.firstChild);
        }
    }

    function initLiveTailDrag(handle, panel) {
        var dx = 0, dy = 0, x0 = 0, y0 = 0;
        handle.onmousedown = function (e) {
            e.preventDefault();
            x0 = e.clientX; y0 = e.clientY;
            document.onmousemove = function (e2) {
                dx = x0 - e2.clientX; dy = y0 - e2.clientY;
                x0 = e2.clientX; y0 = e2.clientY;
                panel.style.top = (panel.offsetTop - dy) + 'px';
                panel.style.left = (panel.offsetLeft - dx) + 'px';
                panel.style.bottom = 'auto'; panel.style.right = 'auto';
            };
            document.onmouseup = function () {
                document.onmousemove = null; document.onmouseup = null;
            };
        };
    }

    // ── Boot ───────────────────────────────────────────────────────────────
    function start(ui) {
        UI = ui;
        try { UI.registerGearItem(GEAR_ID, 'Live Tail', toggleLiveTail, { dot: false }); } catch (_) {}
        _setDot(false);
        window.addEventListener('beforeunload', function () {
            liveTailEnabled = false;
            closeLiveTailDialog();
        });
    }

    function waitForUI() {
        var waited = 0;
        (function poll() {
            if (window.AgentZeroUI) { start(window.AgentZeroUI); return; }
            waited += HOOK_POLL_MS;
            if (waited >= HOOK_POLL_MAX_MS) return;   // new window not present — stay silent
            setTimeout(poll, HOOK_POLL_MS);
        })();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', waitForUI);
    } else {
        waitForUI();
    }
})();
