// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Agent Zero – User-facing chatbot. Wake with "z" anywhere in dashboard.
 * Zero understands metrics, executes directives, answers questions, explains limitations.
 * Minimize sends dialog to bottom tab; ESC closes entirely.
 */
(function () {
    'use strict';

    var ZERO_HOTKEY = 'z';
    var userName = (typeof window.DASHBOARD_USER_NAME !== 'undefined' && window.DASHBOARD_USER_NAME) ? window.DASHBOARD_USER_NAME : ((typeof window.DASHBOARD_USER_ID !== 'undefined' && window.DASHBOARD_USER_ID) ? window.DASHBOARD_USER_ID : 'User');

    var overlay, dialog, minimizedTab, logEl, inputEl, micBtn, minimizeBtn, attachBtn, fileInput, previewWrap;
    var recognition = null;
    var isListening = false;
    var attachedImageB64 = null;
    var zeroStyleInjected = false;
    var flowState = '';
    var flowData = {};
    var conversationHistory = [];   // rolling {role, text} — last 10 kept
    var MAX_HISTORY = 10;

    // ── Pending manual-permission request polling ──────────────────────────
    var _pendingManualCount = 0;
    var _pendingPollInterval = null;
    var _pendingBadgeEl = null;
    var _lastNotifiedPendingCount = -1;  // -1 = not yet polled
    var _pendingListCache = [];           // latest fetched pending list
    var _blinkInterval = null;           // shared JS blink loop (keeps both buttons in sync)
    var _blinkHigh = false;              // current blink phase

    // ── Live Tail state ────────────────────────────────────────────────────
    var liveTailEnabled = false;
    var liveTailDialog = null;
    var liveTailSSE = null;
    var liveTailLogEl = null;
    var liveTailSubsEl = null;
    var liveTailSubsInterval = null;
    var liveTailActiveTab = 'log'; // 'log' | 'subs' | 'timeline'
    var _liveTailTimelineInterval = null;
    var _liveTailCurrentPipelineId = null;
    var _pipelinePollInterval = null;

    // ── Flag state ─────────────────────────────────────────────────────────
    var _ltFlags = [];           // [{level, stage, message, ts}]
    var _ltFlagPopover = null;   // popover DOM element
    var _ltCtxPopover  = null;   // context ledger popover
    var _currentMode = '';          // 'information'|'integrity'|'coding'|''
    var _workflowIssues = [];       // issues pending user decision before launch
    var _issueIndex = 0;            // which issue we're currently reviewing

    function byId(id) { return document.getElementById(id); }

    function centerDialog() {
        if (!dialog) return;
        var w = Math.min(420, window.innerWidth - 40);
        var h = Math.min(480, window.innerHeight - 80);
        dialog.style.left = (window.innerWidth / 2 - w / 2) + 'px';
        dialog.style.top = (window.innerHeight / 2 - h / 2) + 'px';
    }

    function minimizeZero() {
        if (overlay) overlay.style.display = 'none';
        if (dialog) dialog.style.display = 'none';
        if (minimizedTab) {
            minimizedTab.style.position = 'fixed';
            minimizedTab.style.bottom = '0';
            minimizedTab.style.zIndex = '99998';
            minimizedTab.style.left = '';
            minimizedTab.style.transform = '';
            minimizedTab.style.display = 'flex';
        }
    }

    function expandZero() {
        if (overlay) overlay.style.display = 'flex';
        if (dialog) dialog.style.display = 'flex';
        if (minimizedTab) minimizedTab.style.display = 'none';
        if (inputEl) { inputEl.focus(); }
        // If log is empty and there are pending requests, jump straight to them
        if (_pendingManualCount > 0 && logEl && logEl.children.length === 0 && _pendingListCache.length > 0) {
            appendLog('<strong>Zero:</strong> Pending request awaiting your decision.', true);
            _showPendingRequests(_pendingListCache);
        }
    }

    function isZeroVisible() {
        return (overlay && overlay.style.display === 'flex') || (minimizedTab && minimizedTab.style.display === 'flex');
    }

    function isZeroMinimized() {
        return minimizedTab && minimizedTab.style.display === 'flex';
    }

    function initDialogDrag(header) {
        var minBtn = header && header.querySelector('.agent-zero-minimize');
        var startX, startY, startLeft, startTop;
        if (!header) return;
        header.addEventListener('mousedown', function (e) {
            if (minBtn && minBtn.contains(e.target)) return;
            e.preventDefault();
            startX = e.clientX;
            startY = e.clientY;
            var rect = dialog.getBoundingClientRect();
            startLeft = rect.left;
            startTop = rect.top;
            document.body.style.cursor = 'grabbing';
            document.body.style.userSelect = 'none';
            function onMove(e2) {
                var dx = e2.clientX - startX;
                var dy = e2.clientY - startY;
                dialog.style.left = (startLeft + dx) + 'px';
                dialog.style.top = (startTop + dy) + 'px';
            }
            function onUp() {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    function initMinimizedTabDrag(tabEl, expandFn) {
        var SIDEBAR = 180;
        var startX, startLeft, moved;
        if (!tabEl) return;
        tabEl.addEventListener('mousedown', function (e) {
            if (e.target !== tabEl && !tabEl.contains(e.target)) return;
            e.preventDefault();
            e.stopPropagation();
            startX = e.clientX;
            moved = false;
            var rect = tabEl.getBoundingClientRect();
            startLeft = rect.left;
            document.body.style.cursor = 'grabbing';
            document.body.style.userSelect = 'none';
            function onMove(e2) {
                var dx = e2.clientX - startX;
                if (!moved && Math.abs(dx) < 5) return;
                moved = true;
                var newLeft = Math.max(SIDEBAR, Math.min(window.innerWidth - rect.width - 20, startLeft + dx));
                tabEl.style.left = newLeft + 'px';
                tabEl.style.transform = 'none';
            }
            function onUp() {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                if (!moved && typeof expandFn === 'function') expandFn();
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    function injectZeroStyles() {
        if (zeroStyleInjected) return;
        zeroStyleInjected = true;
        var style = document.createElement('style');
        style.id = 'agent-zero-styles';
        style.textContent =
            '.agent-zero-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9000;display:flex;align-items:center;justify-content:center;padding:20px;}' +
            '.agent-zero-dialog{position:fixed;z-index:9001;background:#f5f5f7;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.22);border:1px solid #cbd5e0;width:100%;max-width:420px;min-width:320px;max-height:calc(70vh / var(--ui-zoom,1));display:flex;flex-direction:column;overflow:hidden;}' +
            '.agent-zero-tab{position:fixed;bottom:0;left:50%;transform:translateX(-50%);z-index:99998;background:linear-gradient(140deg,#e8ecf7,#b8c5e0);border:1px solid #7a8bb3;border-bottom:none;border-radius:10px 10px 0 0;padding:10px 28px;cursor:pointer;font-weight:600;font-size:14px;color:#0d1117!important;display:inline-flex;align-items:center;gap:8px;width:max-content;white-space:nowrap;box-shadow:0 -4px 12px rgba(0,0,0,0.15);pointer-events:auto!important;transition:background 0.5s ease,border-color 0.5s ease,box-shadow 0.5s ease,color 0.3s ease;}' +
            '.agent-zero-tab:hover{background:linear-gradient(140deg,#dde3f4,#a8b8e0);}' +
            '.agent-zero-tab .agent-zero-tab-label{color:#0d1117!important;}' +
            '.agent-zero-header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;background:linear-gradient(140deg,#e8ecf7,#b8c5e0 50%,#7a8bb3);color:#0d1117;font-weight:600;cursor:grab;user-select:none;border-radius:12px 12px 0 0;}' +
            '.agent-zero-header:active{cursor:grabbing;}' +
            '.agent-zero-header-btns{display:flex;gap:4px;align-items:center;}' +
            '.agent-zero-minimize{background:#7a8bb3;border:none;border-radius:6px;color:#fff;font-size:18px;line-height:1;width:28px;height:28px;cursor:pointer;display:flex;align-items:center;justify-content:center;}' +
            '.agent-zero-minimize:hover{background:#6a7ba3;}' +
            '.agent-zero-log{flex:1;min-height:200px;max-height:320px;overflow-y:auto;padding:16px;font-size:14px;line-height:1.6;background:#fafafa;}' +
            '.agent-zero-msg{margin-bottom:12px;}' +
            '.agent-zero-response{color:#333;padding:10px 12px;background:linear-gradient(135deg,#e8ecf7,#f0f4ff);border-radius:8px;border-left:4px solid #7a8bb3;}' +
            '.agent-zero-preview-wrap{display:none;padding:8px 16px;border-top:1px solid #ddd;background:#f0f4ff;align-items:center;gap:8px;}' +
            '.agent-zero-input-wrap{padding:12px 16px;border-top:1px solid #ddd;display:flex;gap:8px;align-items:center;}' +
            '.agent-zero-input{flex:1;padding:10px 14px;border:1px solid #cbd5e0;border-radius:8px;font-size:14px;background:#fff;}' +
            '.agent-zero-input:focus{outline:none;border-color:#7a8bb3;box-shadow:0 0 0 2px rgba(122,139,179,0.25);}' +
            '.agent-zero-btn{background:linear-gradient(140deg,#7a8bb3,#6a7ba3);border:none;border-radius:8px;color:#fff;width:42px;height:42px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;}' +
            '.agent-zero-btn:hover{background:linear-gradient(140deg,#6a7ba3,#5a6b93);}' +
            '.agent-zero-choice-btn{display:inline-block;margin:4px 8px 4px 0;padding:8px 14px;background:linear-gradient(140deg,#e8ecf7,#dde3f4);border:1px solid #7a8bb3;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;color:#0d1117;}' +
            '.agent-zero-choice-btn:hover{background:linear-gradient(140deg,#dde3f4,#c7d2fe);}' +
            '.agent-zero-choice-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}' +
            '.agent-zero-field{display:flex;align-items:center;gap:8px;margin:8px 0;}' +
            '.agent-zero-field input{flex:1;min-width:80px;padding:8px 12px;border:1px solid #cbd5e0;border-radius:6px;}' +
            '.agent-zero-summary{background:#f0f4ff;padding:12px;border-radius:8px;margin:12px 0;font-size:13px;line-height:1.5;}' +
            '.zpub-pending-badge{position:absolute;top:-6px;right:-6px;background:#dc2626;color:#fff;border-radius:50%;width:18px;height:18px;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;pointer-events:none;}';
        document.head.appendChild(style);
    }

    function createOverlay() {
        if (overlay) return;
        injectZeroStyles();
        overlay = document.createElement('div');
        overlay.id = 'agent-zero-overlay';
        overlay.className = 'agent-zero-overlay';
        overlay.style.display = 'none';
        overlay.onclick = function (e) { if (e.target === overlay) minimizeZero(); };
        document.body.appendChild(overlay);

        dialog = document.createElement('div');
        dialog.id = 'agent-zero-dialog';
        dialog.className = 'agent-zero-dialog';
        dialog.innerHTML =
            '<div class="agent-zero-header">' +
            '<span class="agent-zero-title">Zero</span>' +
            '<div class="agent-zero-header-btns">' +
            '<button type="button" class="agent-zero-minimize" id="agent-zero-minimize" aria-label="Minimize" title="Minimize to bottom">&minus;</button>' +
            '</div></div>' +
            '<div class="agent-zero-log" id="agent-zero-log"></div>' +
            '<div class="agent-zero-preview-wrap" id="agent-zero-preview"></div>' +
            '<div class="agent-zero-input-wrap">' +
            '<input type="file" id="agent-zero-file" accept="image/*" style="display:none;">' +
            '<button type="button" id="agent-zero-attach" class="agent-zero-btn" aria-label="Attach image" title="Attach image">&#128247;</button>' +
            '<button type="button" id="agent-zero-gear" class="agent-zero-btn" aria-label="Functions" title="Functions" style="font-size:16px;">&#9881;</button>' +
            '<div id="agent-zero-gear-menu" style="display:none;position:absolute;bottom:48px;left:8px;background:#1e1e2e;border:1px solid #444;border-radius:8px;padding:6px 0;z-index:99999;min-width:160px;box-shadow:0 4px 16px rgba(0,0,0,0.5);">' +
            '<div id="agent-zero-livetail-btn" style="padding:8px 16px;cursor:pointer;color:#cdd6f4;font-size:13px;display:flex;align-items:center;gap:8px;user-select:none;" onmouseenter="this.style.background=\'#313244\'" onmouseleave="this.style.background=\'transparent\'">' +
            '<span id="agent-zero-livetail-dot" style="width:10px;height:10px;border-radius:50%;background:#555;display:inline-block;transition:background 0.2s;"></span>' +
            'Live Tail' +
            '</div>' +
            '</div>' +
            '<input type="text" id="agent-zero-input" class="agent-zero-input" placeholder="Ask or tell Zero... (or paste image)" autocomplete="off">' +
            '<button type="button" id="agent-zero-mic" class="agent-zero-btn" aria-label="Speech input" title="Hold to talk">&#127908;</button>' +
            '</div>';
        dialog.style.display = 'none';
        document.body.appendChild(dialog);

        minimizedTab = document.createElement('div');
        minimizedTab.id = 'agent-zero-tab';
        minimizedTab.className = 'agent-zero-tab';
        minimizedTab.innerHTML = '<span class="agent-zero-tab-label">Zero</span>';
        // Force fixed positioning inline — CSS class alone can be overridden by animation layers or other rules
        minimizedTab.style.position = 'fixed';
        minimizedTab.style.bottom = '0';
        minimizedTab.style.zIndex = '99998';
        minimizedTab.style.display = 'none';
        document.body.appendChild(minimizedTab);

        logEl = byId('agent-zero-log');
        inputEl = byId('agent-zero-input');
        micBtn = byId('agent-zero-mic');
        minimizeBtn = byId('agent-zero-minimize');
        attachBtn = byId('agent-zero-attach');
        fileInput = byId('agent-zero-file');
        previewWrap = byId('agent-zero-preview');

        if (minimizeBtn) minimizeBtn.onclick = minimizeZero;
        if (minimizedTab) initMinimizedTabDrag(minimizedTab, openZero);
        if (attachBtn && fileInput) {
            attachBtn.onclick = function () { fileInput.click(); };
            fileInput.onchange = function () {
                var f = fileInput.files && fileInput.files[0];
                if (!f || !f.type.startsWith('image/')) return;
                var r = new FileReader();
                r.onload = function () {
                    var data = r.result;
                    attachedImageB64 = (typeof data === 'string' && data.indexOf('base64,') >= 0) ? data.split('base64,')[1] : data;
                    showImagePreview();
                };
                r.readAsDataURL(f);
                fileInput.value = '';
            };
        }

        // ── Gear menu ─────────────────────────────────────────────────────
        var gearBtn = byId('agent-zero-gear');
        var gearMenu = byId('agent-zero-gear-menu');
        var liveTailBtn = byId('agent-zero-livetail-btn');
        var liveTailDot = byId('agent-zero-livetail-dot');
        if (gearBtn && gearMenu) {
            gearBtn.onclick = function (e) {
                e.stopPropagation();
                gearMenu.style.display = gearMenu.style.display === 'none' ? 'block' : 'none';
            };
            document.addEventListener('click', function (e) {
                if (gearMenu && !gearMenu.contains(e.target) && e.target !== gearBtn) {
                    gearMenu.style.display = 'none';
                }
            });
        }
        if (liveTailBtn) {
            liveTailBtn.onclick = function () {
                gearMenu.style.display = 'none';
                toggleLiveTail();
            };
        }
        if (inputEl) {
            inputEl.addEventListener('paste', handlePaste);
        }
        document.addEventListener('paste', handlePaste);
        if (inputEl) {
            inputEl.onkeydown = function (e) {
                if (e.key === 'Enter') { e.preventDefault(); sendMessage(); }
                if (e.key === 'Escape') closeZero();
            };
        }
        var header = dialog.querySelector('.agent-zero-header');
        if (header) initDialogDrag(header);
        if (micBtn) {
            micBtn.addEventListener('mousedown', startListening);
            micBtn.addEventListener('mouseup', stopListening);
            micBtn.addEventListener('mouseleave', stopListening);
        }
        initSpeechRecognition();
        initChoiceDelegation();
    }

    function handlePaste(e) {
        if (!overlay || overlay.style.display !== 'flex') return;
        var items = (e.clipboardData && e.clipboardData.items) || [];
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (item.kind === 'file' && item.type.indexOf('image/') === 0) {
                e.preventDefault();
                var blob = item.getAsFile();
                if (!blob) return;
                var r = new FileReader();
                r.onload = function () {
                    var data = r.result;
                    attachedImageB64 = (typeof data === 'string' && data.indexOf('base64,') >= 0) ? data.split('base64,')[1] : data;
                    showImagePreview();
                };
                r.readAsDataURL(blob);
                return;
            }
        }
    }

    function showImagePreview() {
        if (!previewWrap) return;
        if (!attachedImageB64) {
            previewWrap.style.display = 'none';
            previewWrap.innerHTML = '';
            return;
        }
        var src = 'data:image/jpeg;base64,' + attachedImageB64;
        previewWrap.innerHTML = '<img src="' + src + '" alt="Attached" style="max-width:80px;max-height:80px;border-radius:6px;object-fit:cover;">' +
            '<span style="font-size:12px;color:#666;">Image attached</span>' +
            '<button type="button" aria-label="Remove image" style="margin-left:auto;background:#e74c3c;color:#fff;border:none;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;">Remove</button>';
        previewWrap.style.display = 'flex';
        var btn = previewWrap.querySelector('button');
        if (btn) btn.onclick = clearImage;
    }

    function clearImage() {
        attachedImageB64 = null;
        showImagePreview();
    }

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function addToHistory(role, text) {
        conversationHistory.push({ role: role, text: String(text).substring(0, 600) });
        if (conversationHistory.length > MAX_HISTORY) conversationHistory.shift();
    }

    function disableOldChoices() {
        if (!logEl) return;
        logEl.querySelectorAll('.agent-zero-choice-btn').forEach(function (btn) {
            btn.disabled = true;
            btn.style.opacity = '0.35';
            btn.style.cursor = 'default';
            btn.style.pointerEvents = 'none';
        });
    }

    function menuAlreadyShown() {
        if (!logEl) return false;
        var last = logEl.lastElementChild;
        return !!(last && last.querySelector && last.querySelector('[data-zero-choice="planning"]'));
    }

    function appendModeBar(modeName) {
        var div = document.createElement('div');
        div.className = 'agent-zero-msg agent-zero-response';
        div.style.cssText = 'display:flex;align-items:center;justify-content:space-between;font-size:12px;opacity:0.8;padding:6px 12px;';
        var span = document.createElement('span');
        span.innerHTML = 'Mode: <strong>' + escapeHtml(modeName) + '</strong>';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'agent-zero-choice-btn';
        btn.textContent = '← Menu';
        btn.setAttribute('data-zero-choice', '_back_to_menu');
        btn.style.cssText = 'margin:0;padding:4px 10px;font-size:12px;';
        div.appendChild(span);
        div.appendChild(btn);
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;
    }

    function fetchWorkflowHealth() {
        return fetch('/api/zero/workflow-health', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : { issues: [], unresolved_count: 0 }; })
            .catch(function () { return { issues: [], unresolved_count: 0 }; });
    }

    function resolveIssue(issueId, action, onDone) {
        var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
        var headers = { 'Content-Type': 'application/json' };
        if (csrf) headers['X-CSRFToken'] = csrf;
        fetch('/api/zero/workflow-override', {
            method: 'POST', headers: headers,
            body: JSON.stringify({ issue_id: issueId, action: action }),
            credentials: 'same-origin'
        }).then(function () { if (onDone) onDone(); })
          .catch(function () { if (onDone) onDone(); });
    }

    function showNextIssue() {
        // Skip already-resolved issues
        while (_issueIndex < _workflowIssues.length && _workflowIssues[_issueIndex].resolved) {
            _issueIndex++;
        }
        if (_issueIndex >= _workflowIssues.length) {
            // All issues handled — proceed to summary
            appendLog('<strong>Zero:</strong> All workflow issues resolved. Proceeding to launch.', true);
            showClipfarmSummary();
            return;
        }
        var issue = _workflowIssues[_issueIndex];
        var sevColor = issue.severity === 'error' ? '#c0392b' : '#e67e22';
        var sevLabel = issue.severity === 'error' ? '🔴 Error' : '⚠️ Warning';
        var html = '<strong>Zero:</strong> <div class="agent-zero-summary" style="border-left:4px solid ' + sevColor + ';margin-top:6px;">'
            + '<div style="font-weight:600;margin-bottom:4px;">' + sevLabel + ' — ' + escapeHtml(issue.title) + '</div>'
            + '<div style="font-size:12px;color:#444;margin-bottom:6px;">' + escapeHtml(issue.description) + '</div>'
            + (issue.skip_note ? '<div style="font-size:12px;color:#2980b9;"><em>If skipped: ' + escapeHtml(issue.skip_note) + '</em></div>' : '')
            + '</div>';
        appendLog(html, true, true);
        var choices = [];
        if (issue.fix_available) choices.push({ label: '🔧 Fix now', value: '_issue_fix' });
        choices.push({ label: '⏭ Skip this step', value: '_issue_skip' });
        choices.push({ label: '✖ Ignore', value: '_issue_ignore' });
        appendChoices(choices);
        flowState = 'workflow_issues';
    }

    function showContextualGreeting(ctx) {
        var pipeline = ctx.pipeline;
        var approvals = ctx.pending_approvals || 0;
        var pendingManual = ctx.pending_manual || 0;
        if (pipeline && pipeline.active) {
            appendLog('<strong>Zero:</strong> Pipeline is running — <em>' + escapeHtml(pipeline.stage_name || 'in progress') + '</em>.', true);
            var choices = [{ label: '📊 Pipeline progress', value: '_show_pipeline_status' }];
            if (approvals > 0) choices.push({ label: '✅ Approvals (' + approvals + ')', value: '_show_approvals' });
            if (pendingManual > 0) choices.push({ label: '🔔 Pending requests (' + pendingManual + ')', value: '_show_zpub_pending' });
            choices.push({ label: '💬 Main menu', value: '_back_to_menu' });
            appendChoices(choices);
            return;
        }
        // Surface unresolved workflow issues on open
        fetchWorkflowHealth().then(function (health) {
            var unresolved = (health.issues || []).filter(function (i) { return !i.resolved; });
            if (unresolved.length > 0) {
                appendLog(
                    '<strong>Zero:</strong> I detected <strong>' + unresolved.length + '</strong> workflow issue'
                    + (unresolved.length > 1 ? 's' : '') + ' that need your attention before running.',
                    true
                );
                var choices = [{ label: '🔍 Review issues (' + unresolved.length + ')', value: '_review_issues' }];
                if (approvals > 0) choices.push({ label: '✅ Approvals (' + approvals + ')', value: '_show_approvals' });
                if (pendingManual > 0) choices.push({ label: '🔔 Pending requests (' + pendingManual + ')', value: '_show_zpub_pending' });
                choices.push({ label: '💬 Main menu', value: '_back_to_menu' });
                appendChoices(choices);
                return;
            }
            if (pendingManual > 0) {
                var manualMsg = '<strong>Zero:</strong> <strong>' + pendingManual + '</strong> manual-permission request'
                    + (pendingManual > 1 ? 's are' : ' is') + ' waiting for your decision.';
                if (approvals > 0) manualMsg += ' There ' + (approvals > 1 ? 'are also <strong>' + approvals + '</strong> workflow approvals.' : 'is also <strong>1</strong> workflow approval.');
                appendLog(manualMsg, true);
                var choices = [{ label: '🔔 Review requests (' + pendingManual + ')', value: '_show_zpub_pending' }];
                if (approvals > 0) choices.push({ label: '✅ Approvals (' + approvals + ')', value: '_show_approvals' });
                choices.push({ label: '🚀 Start Clipfarm', value: '_quick_clipfarm' });
                choices.push({ label: '💬 Main menu', value: '_back_to_menu' });
                appendChoices(choices);
                return;
            }
            if (approvals > 0) {
                appendLog('<strong>Zero:</strong> Pipeline idle — <strong>' + approvals + '</strong> pending approval' + (approvals > 1 ? 's' : '') + ' waiting.', true);
                appendChoices([
                    { label: '✅ Review approvals (' + approvals + ')', value: '_show_approvals' },
                    { label: '🚀 Start Clipfarm', value: '_quick_clipfarm' },
                    { label: '💬 Main menu', value: '_back_to_menu' }
                ]);
                return;
            }
            showMainMenu();
        });
    }

    function startPipelinePolling(jobId) {
        if (_pipelinePollInterval) clearInterval(_pipelinePollInterval);
        _activePipelineJobId = jobId;
        _saveState();
        var widgetId = 'zero-pipeline-widget-' + jobId;
        _pipelinePollInterval = setInterval(function () {
            fetch('/api/workflow_status/' + jobId, { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data) return;
                    var el = document.getElementById(widgetId);
                    if (!el) return;
                    var status = data.status || 'running';
                    var stage = data.current_stage || '';
                    el.innerHTML = escapeHtml(status) + (stage ? ' — ' + escapeHtml(stage) : '');
                    if (status === 'completed') {
                        clearInterval(_pipelinePollInterval);
                        _pipelinePollInterval = null;
                        _activePipelineJobId = null;
                        _saveState();
                        appendLog('<strong>Zero:</strong> Pipeline complete. ' + escapeHtml(data.result || ''), true);
                    } else if (status === 'failed') {
                        clearInterval(_pipelinePollInterval);
                        _pipelinePollInterval = null;
                        _activePipelineJobId = null;
                        _saveState();
                        var errMsg = data.error || 'Unknown error — check server logs.';
                        // Find which stage/agent failed
                        var failDetail = '';
                        if (data.stages) {
                            data.stages.forEach(function(s) {
                                if (s.details) {
                                    Object.keys(s.details).forEach(function(agentId) {
                                        var a = s.details[agentId];
                                        if (a && a.status === 'failed' && a.error) {
                                            failDetail += '\n• ' + agentId + ': ' + a.error.substring(0, 200);
                                        }
                                    });
                                }
                            });
                        }
                        appendLog('<strong>Zero:</strong> ❌ Pipeline failed.<br><div class="agent-zero-summary" style="margin-top:6px;color:#c0392b;">' +
                            '<strong>Reason:</strong> ' + escapeHtml(errMsg) +
                            (failDetail ? '<br><br><strong>Agent errors:</strong><pre style="font-size:11px;white-space:pre-wrap;">' + escapeHtml(failDetail) + '</pre>' : '') +
                            '</div>', true);
                    }
                });
        }, 5000);
    }

    var _SS_KEY = 'zero_chat_state';

    function _saveState() {
        try {
            sessionStorage.setItem(_SS_KEY, JSON.stringify({
                html: logEl ? logEl.innerHTML : '',
                flowState: flowState,
                history: conversationHistory,
                pipelineJobId: _activePipelineJobId || null,
            }));
        } catch (_) {}
    }

    function _restoreState() {
        try {
            var raw = sessionStorage.getItem(_SS_KEY);
            if (!raw) return false;
            var s = JSON.parse(raw);
            if (!s || !s.html) return false;
            if (logEl) logEl.innerHTML = s.html;
            if (s.flowState) flowState = s.flowState;
            if (s.history) conversationHistory = s.history;
            // Disable all historical choice buttons, then re-enable the last (current) set
            disableOldChoices();
            var choiceRows = logEl ? logEl.querySelectorAll('.agent-zero-choice-row') : [];
            if (choiceRows.length > 0) {
                choiceRows[choiceRows.length - 1].querySelectorAll('.agent-zero-choice-btn').forEach(function (b) {
                    b.disabled = false;
                    b.style.opacity = '';
                    b.style.cursor = 'pointer';
                    b.style.pointerEvents = '';
                });
            }
            // Resume pipeline polling if a job was running
            if (s.pipelineJobId) {
                _activePipelineJobId = s.pipelineJobId;
                startPipelinePolling(s.pipelineJobId);
            }
            return true;
        } catch (_) { return false; }
    }

    var _activePipelineJobId = null;

    function appendLog(html, isZero) {
        if (!logEl) return;
        var div = document.createElement('div');
        div.className = 'agent-zero-msg' + (isZero ? ' agent-zero-response' : '');
        div.innerHTML = html;
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;
        _saveState();
    }

    function appendChoices(choices) {
        if (!logEl) return;
        var wrap = document.createElement('div');
        wrap.className = 'agent-zero-choice-row';
        choices.forEach(function (c) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'agent-zero-choice-btn';
            btn.textContent = c.label;
            btn.setAttribute('data-zero-choice', c.value);
            wrap.appendChild(btn);
        });
        var div = document.createElement('div');
        div.className = 'agent-zero-msg agent-zero-response';
        div.appendChild(wrap);
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;
        _saveState();
    }

    function handleFlowChoice(value) {
        disableOldChoices();
        var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
        var headers = { 'Content-Type': 'application/json' };
        if (csrf) headers['X-CSRFToken'] = csrf;

        /* Global nav — back to menu from any state */
        if (value === '_back_to_menu') {
            _currentMode = '';
            showMainMenu();
            return;
        }

        /* Context-aware quick actions */
        if (value === '_quick_clipfarm') {
            flowState = 'production_type';
            flowData = { type: 'production' };
            appendLog('<strong>Zero:</strong> Launching Clipfarm — niche or analytics?', true);
            appendChoices([
                { label: '* Preferred niche *', value: 'niche' },
                { label: '* Analytics *', value: 'analytics' }
            ]);
            // Skip directly to clipfarm_niche_or_analytics
            flowState = 'clipfarm_niche_or_analytics';
            flowData.productionType = 'clipfarm';
            return;
        }

        if (value === '_show_pipeline_status') {
            appendLog('<em>Fetching pipeline status…</em>', true);
            fetch('/api/zero/context', { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : {}; })
                .then(function (ctx) {
                    var last = logEl.querySelector('.agent-zero-msg:last-child');
                    if (last && last.textContent.indexOf('Fetching') >= 0) last.remove();
                    var p = ctx.pipeline;
                    if (p && p.active) {
                        appendLog('<strong>Zero:</strong> <div class="agent-zero-summary">Job: ' + escapeHtml(p.job_id || '?') + '<br>Stage: ' + escapeHtml(p.stage_name || '?') + '</div>', true);
                    } else {
                        appendLog('<strong>Zero:</strong> No active pipeline.', true);
                    }
                    showMainMenu();
                })
                .catch(function () {
                    appendLog('<strong>Zero:</strong> Could not fetch pipeline status.', true);
                    showMainMenu();
                });
            return;
        }

        if (value === '_show_approvals') {
            appendLog('<em>Loading approval queue…</em>', true);
            fetch('/api/approval-queue', { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : { items: [] }; })
                .then(function (data) {
                    var last = logEl.querySelector('.agent-zero-msg:last-child');
                    if (last && last.textContent.indexOf('Loading') >= 0) last.remove();
                    var items = data.items || data.queue || [];
                    if (items.length === 0) {
                        appendLog('<strong>Zero:</strong> No pending approvals.', true);
                    } else {
                        var html = '<strong>Zero:</strong> Pending approvals:<div class="agent-zero-summary" style="margin-top:8px;">';
                        items.forEach(function (item) {
                            html += '<div style="margin-bottom:6px;border-bottom:1px solid #ddd;padding-bottom:4px;"><strong>' + escapeHtml(item.id || item.request_id || '?') + '</strong><br>' + escapeHtml(item.description || item.reason || '') + '</div>';
                        });
                        html += '</div>';
                        appendLog(html, true);
                    }
                    showMainMenu();
                })
                .catch(function () {
                    appendLog('<strong>Zero:</strong> Could not load approvals.', true);
                    showMainMenu();
                });
            return;
        }

        // ── Manual permission pending requests ────────────────────────────
        if (value === '_show_zpub_pending') {
            appendLog('<em>Loading pending requests…</em>', true);
            fetch('/api/zero_public/pending', { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : { pending: [] }; })
                .then(function (data) {
                    var last = logEl.querySelector('.agent-zero-msg:last-child');
                    if (last && last.textContent.indexOf('Loading') >= 0) last.remove();
                    _showPendingRequests(data.pending || []);
                })
                .catch(function () {
                    appendLog('<strong>Zero:</strong> Could not load pending requests.', true);
                    showMainMenu();
                });
            return;
        }

        if (value && value.indexOf('_zpub_allow:') === 0) {
            var reqId = value.replace('_zpub_allow:', '');
            // Arming delay removed 2026-07-19 at the owner's request — Allow
            // acts immediately. Decision latency is still AUDITED server-side
            // (zpub_decision_latency in zero_audit.jsonl), just never blocked.
            _decidePending(reqId, 'allow');
            return;
        }
        if (value && value.indexOf('_zpub_queue:') === 0) {
            var reqId = value.replace('_zpub_queue:', '');
            _decidePending(reqId, 'queue');
            return;
        }
        if (value && value.indexOf('_zpub_decline:') === 0) {
            var reqId = value.replace('_zpub_decline:', '');
            _decidePending(reqId, 'decline');
            return;
        }

        /* Workflow issue review — triggered from contextual greeting or pre-launch */
        if (value === '_review_issues') {
            fetchWorkflowHealth().then(function (health) {
                _workflowIssues = health.issues || [];
                _issueIndex = 0;
                var unresolvedCount = _workflowIssues.filter(function (i) { return !i.resolved; }).length;
                if (unresolvedCount === 0) {
                    appendLog('<strong>Zero:</strong> No issues — all good.', true);
                    showMainMenu();
                    return;
                }
                appendLog('<strong>Zero:</strong> Reviewing <strong>' + unresolvedCount + '</strong> workflow issue' + (unresolvedCount > 1 ? 's' : '') + ':', true);
                showNextIssue();
            });
            return;
        }

        if (flowState === 'workflow_issues') {
            var currentIssue = _workflowIssues[_issueIndex];
            if (value === '_issue_skip') {
                appendLog('<strong>' + escapeHtml(userName) + ':</strong> Skip', false);
                appendLog('<strong>Zero:</strong> Skipping <em>' + escapeHtml(currentIssue.title) + '</em>. ' + escapeHtml(currentIssue.skip_note || ''), true);
                resolveIssue(currentIssue.id, 'skip', function () {
                    currentIssue.resolved = true;
                    _issueIndex++;
                    showNextIssue();
                });
                return;
            }
            if (value === '_issue_ignore') {
                appendLog('<strong>' + escapeHtml(userName) + ':</strong> Ignore', false);
                appendLog('<strong>Zero:</strong> Noted — ignoring <em>' + escapeHtml(currentIssue.title) + '</em>.', true);
                resolveIssue(currentIssue.id, 'ignore', function () {
                    currentIssue.resolved = true;
                    _issueIndex++;
                    showNextIssue();
                });
                return;
            }
            if (value === '_issue_fix') {
                appendLog('<strong>' + escapeHtml(userName) + ':</strong> Fix now', false);
                appendLog('<strong>Zero:</strong> Fix not yet automated for this issue. Add the required credentials to <code>data/runtime/clipfarm_credentials.json</code> and reopen Zero.', true);
                _issueIndex++;
                showNextIssue();
                return;
            }
        }

        /* If a main-menu option is clicked from any state, switch immediately */
        var MAIN_MENU_VALUES = ['planning', 'production', 'information', 'integrity', 'governance', 'coding'];
        if (MAIN_MENU_VALUES.indexOf(value) >= 0 && flowState !== 'main_menu') {
            flowState = 'main_menu';
            flowData = {};
        }

        if (flowState === 'llms_prompt' && value === 'yes') {
            flowState = 'llms_installing';
            appendLog('<strong>Zero:</strong> Installing LLMs… This may take a few minutes.', true);
            fetch('/api/zero/install-llms', { method: 'POST', headers: headers, credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    flowState = '';
                    flowData = {};
                    if (data.success) {
                        appendLog('<strong>Zero:</strong> LLMs installed. You can now use me fully. How can I help you?', true);
                        showMainMenu();
                    } else {
                        appendLog('<strong>Zero:</strong> Install failed: ' + (data.message || 'Unknown error') + '. Try running <code>ollama pull qwen3.6:35b-a3b</code> manually.', true);
                    }
                })
                .catch(function (err) {
                    flowState = '';
                    if (!window._serverRestarting) appendLog('<strong>Zero:</strong> Could not install: ' + (err.message || 'Network error'), true);
                });
            return;
        }
        if (flowState === 'llms_prompt' && value === 'no') {
            flowState = '';
            appendLog('<strong>Zero:</strong> Without the LLMs I cannot assist fully. Open me again when you are ready to install.', true);
            return;
        }

        if (flowState === 'main_menu') {
            if (value === 'planning') {
                appendLog('<strong>' + userName + ':</strong> Planning', false);
                flowState = 'planning_goal';
                flowData = { goal: '' };
                appendLog('<strong>Zero:</strong> What goal should I break into tasks? Type your goal in the input below, then press Enter. I will return backend, UI, schema, test, and audit subtasks with specialist routing.', true);
                return;
            }
            if (value === 'production') {
                flowState = 'production_type';
                flowData.type = 'production';
                appendLog('<strong>' + userName + ':</strong> Production', false);
                appendLog('<strong>Zero:</strong> What type of production?', true);
                appendChoices([
                    { label: '* 2D Series *', value: '2d' },
                    { label: '* 3D Series *', value: '3d' },
                    { label: '* Clipfarm *', value: 'clipfarm' },
                    { label: '* Distribution *', value: 'distribution' },
                    { label: '* Affiliate Marketing *', value: 'affiliate' }
                ]);
            } else if (value === 'information') {
                appendLog('<strong>' + userName + ':</strong> Information', false);
                appendLog('<strong>Zero:</strong> Information mode — ask me anything about the system, metrics, agents, or schedules.', true);
                flowState = '';
                _currentMode = 'information';
                appendModeBar('Information');
            } else if (value === 'integrity') {
                appendLog('<strong>' + userName + ':</strong> Integrity', false);
                appendLog('<strong>Zero:</strong> Integrity — I can report on system health, safety status, and approval queues.', true);
                flowState = '';
                _currentMode = 'integrity';
                appendModeBar('Integrity');
            } else if (value === 'governance') {
                appendLog('<strong>' + userName + ':</strong> Governance', false);
                appendLog('<strong>Zero:</strong> Governance — project constitution, task state, validation checklist, audit trail, change impact.', true);
                appendChoices([
                    { label: 'View task state', value: 'gov_task_state' },
                    { label: 'Update task state', value: 'gov_task_update' },
                    { label: 'Validation checklist', value: 'gov_checklist' },
                    { label: 'Audit trail', value: 'gov_audit' },
                    { label: 'Change impact', value: 'gov_impact' }
                ]);
                flowState = 'governance';
            } else if (value === 'coding') {
                appendLog('<strong>' + userName + ':</strong> Coding', false);
                appendLog('<strong>Zero:</strong> Coding mode — powered by ' + (window.zeroLlms && window.zeroLlms.code ? window.zeroLlms.code : 'qwen2.5-coder:32b') + '. Describe what you need: new features, bug fixes, refactors, or code review. Type your request below.', true);
                flowState = 'coding';
                _currentMode = 'coding';
                appendModeBar('Coding');
            }
            return;
        }

        if (flowState === 'governance') {
            if (value === 'gov_task_state') {
                appendLog('<strong>' + userName + ':</strong> Task state', false);
                fetch('/api/zero/task-state', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (data) {
                    var s = data.phase || '(none)';
                    var goal = data.current_goal || '(none)';
                    var issues = (data.open_issues || []).length;
                    var blocked = (data.blocked || []).length;
                    var html = '<strong>Zero:</strong> <div class="agent-zero-summary">Phase: ' + escapeHtml(s) + '<br>Goal: ' + escapeHtml(goal) + '<br>Open issues: ' + issues + '<br>Blocked: ' + blocked + '</div>';
                    appendLog(html, true, true);
                    appendLog('<strong>Zero:</strong> Use Update task state below or POST /api/zero/task-state to change.', true);
                }).catch(function () { appendLog('<strong>Zero:</strong> Could not load task state.', true); });
                flowState = '';
                showMainMenu();
                return;
            }
            if (value === 'gov_task_update') {
                appendLog('<strong>' + userName + ':</strong> Update task state', false);
                flowState = 'gov_task_update_input';
                appendLog('<strong>Zero:</strong> Type: <code>phase=implementation, goal=Add new API</code> (or just phase or goal). Press Enter.', true, true);
                return;
            }
            if (value === 'gov_checklist') {
                appendLog('<strong>' + userName + ':</strong> Validation checklist', false);
                fetch('/api/zero/validation-checklist', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (data) {
                    var items = (data.checklist || []).map(function (c) { return '• ' + (c.label || ''); }).join('<br>');
                    appendLog('<strong>Zero:</strong> Pre-merge checklist (review before accepting changes):<div class="agent-zero-summary" style="margin-top:8px;">' + items + '</div>', true, true);
                }).catch(function () { appendLog('<strong>Zero:</strong> Could not load checklist.', true); });
                flowState = '';
                showMainMenu();
                return;
            }
            if (value === 'gov_audit') {
                appendLog('<strong>' + userName + ':</strong> Audit trail', false);
                appendLog('<em>Loading…</em>', true);
                fetch('/api/zero/audit-trail?limit=20', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (data) {
                    var last = logEl.querySelector('.agent-zero-msg:last-child');
                    if (last && last.textContent.indexOf('Loading') >= 0) last.remove();
                    var entries = data.entries || [];
                    if (entries.length === 0) {
                        appendLog('<strong>Zero:</strong> No audit entries yet. Actions (chat, decompose, task_state_update) are logged here.', true);
                    } else {
                        var html = '<strong>Zero:</strong> Last ' + entries.length + ' audit entries:<div class="agent-zero-summary" style="margin-top:8px;max-height:200px;overflow-y:auto;">';
                        entries.forEach(function (e) {
                            html += '<div style="margin-bottom:6px;font-size:12px;">' + escapeHtml(e.timestamp || '') + ' | ' + escapeHtml(e.action || '') + ' | ' + escapeHtml(JSON.stringify(e.payload || {}).substring(0, 80)) + '…</div>';
                        });
                        html += '</div>';
                        appendLog(html, true, true);
                    }
                }).catch(function () {
                    var last = logEl.querySelector('.agent-zero-msg:last-child');
                    if (last && last.textContent.indexOf('Loading') >= 0) last.remove();
                    appendLog('<strong>Zero:</strong> Could not load audit trail.', true);
                });
                flowState = '';
                showMainMenu();
                return;
            }
            if (value === 'gov_impact') {
                appendLog('<strong>' + userName + ':</strong> Change impact', false);
                flowState = 'gov_impact_input';
                appendLog('<strong>Zero:</strong> Enter file path(s) to analyze (e.g. <code>crewai_web_gui.py</code> or <code>legacy/flask_dashboard/data/agents.json</code>). Type path and press Enter.', true, true);
                return;
            }
            return;
        }

        if (flowState === 'production_type') {
            appendLog('<strong>' + userName + ':</strong> ' + value, false);
            flowData.productionType = value;
            if (value === 'clipfarm') {
                flowState = 'clipfarm_niche_or_analytics';
                appendLog('<strong>Zero:</strong> Do you have a <em>preferred niche</em> or should I use <em>analytics</em> to determine valuable niches?', true);
                appendChoices([
                    { label: '* Preferred niche *', value: 'niche' },
                    { label: '* Analytics *', value: 'analytics' }
                ]);
            } else {
                appendLog('<strong>Zero:</strong> ' + value + ' production — configuration for this type is coming soon. How can I help you?', true);
                flowState = '';
                showMainMenu();
            }
            return;
        }

        if (flowState === 'clipfarm_niche_or_analytics') {
            appendLog('<strong>' + userName + ':</strong> ' + (value === 'niche' ? 'Preferred niche' : 'Analytics'), false);
            if (value === 'niche') {
                flowState = 'clipfarm_niche';
                flowData.nicheOrAnalytics = 'niche';
                appendLog('<strong>Zero:</strong> Choose a niche:', true);
                appendChoices([
                    { label: '* Luxury *', value: 'luxury' },
                    { label: '* Entertainment *', value: 'entertainment' },
                    { label: '* Cosmetics *', value: 'cosmetics' },
                    { label: '* Clothes *', value: 'clothes' },
                    { label: '* Hypes *', value: 'hypes' },
                    { label: '* War *', value: 'war' },
                    { label: '* Technology *', value: 'technology' },
                    { label: '* Crime *', value: 'crime' },
                    { label: '* Scholarly *', value: 'scholarly' }
                ]);
            } else {
                flowData.nicheOrAnalytics = 'analytics';
                runWorkflowHealthThenSummary();
            }
            return;
        }

        if (flowState === 'clipfarm_niche') {
            if (value === 'scholarly') {
                // Scholarly: show the same 8 niches as topic sub-selection
                appendLog('<strong>' + userName + ':</strong> Scholarly', false);
                flowData.niche = 'scholarly';
                flowState = 'scholarly_topic';
                appendLog('<strong>Zero:</strong> Scholarly mode — choose a topic for academic research:', true);
                appendChoices([
                    { label: '* Luxury *',       value: 'luxury' },
                    { label: '* Entertainment *', value: 'entertainment' },
                    { label: '* Cosmetics *',     value: 'cosmetics' },
                    { label: '* Clothes *',       value: 'clothes' },
                    { label: '* Hypes *',         value: 'hypes' },
                    { label: '* War *',           value: 'war' },
                    { label: '* Technology *',    value: 'technology' },
                    { label: '* Crime *',         value: 'crime' },
                    { label: '* History *',       value: 'history' },
                    { label: '* Psychology *',    value: 'psychology' },
                    { label: '* Philosophy *',    value: 'philosophy' },
                    { label: '* Economics *',     value: 'economics' },
                    { label: '* Politics *',      value: 'politics' },
                    { label: '* Environment *',   value: 'environment' },
                    { label: '* Medicine *',      value: 'medicine' },
                    { label: '* Religion *',      value: 'religion' },
                    { label: '* Space *',         value: 'space' },
                    { label: '* Architecture *',  value: 'architecture' },
                    { label: '* Art *',           value: 'art' },
                    { label: '* Music *',         value: 'music' }
                ]);
            } else {
                appendLog('<strong>' + userName + ':</strong> ' + value, false);
                flowData.niche = value;
                runWorkflowHealthThenSummary();
            }
            return;
        }

        if (flowState === 'scholarly_topic') {
            appendLog('<strong>' + userName + ':</strong> ' + value, false);
            flowData.scholarlyTopic = value;
            runWorkflowHealthThenSummary();
            return;
        }


        if (flowState === 'clipfarm_summary' && value === 'yes') {
            appendLog('<strong>' + userName + ':</strong> Yes', false);
            flowState = 'clipfarm_confirm_updates';
            appendLog('<strong>Zero:</strong> I will wake up the Overseers and we\'ll get to work. Do you want me to update you when agents successfully complete a task?', true);
            appendChoices([{ label: 'Yes', value: 'updates_yes' }, { label: 'No', value: 'updates_no'}]);
            return;
        }

        if (flowState === 'clipfarm_summary' && value === 'no') {
            appendLog('<strong>' + userName + ':</strong> No', false);
            appendLog('<strong>Zero:</strong> Let\'s adjust. What would you like to change? You can start over with Production.', true);
            flowState = '';
            showMainMenu();
            return;
        }

        if (flowState === 'clipfarm_confirm_updates' && (value === 'updates_yes' || value === 'updates_no')) {
            appendLog('<strong>' + userName + ':</strong> ' + (value === 'updates_yes' ? 'Yes' : 'No'), false);
            flowData.wantUpdates = value === 'updates_yes';
            appendLog('<strong>Zero:</strong> Starting Clipfarm now…', true);
            var cfCsrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
            var cfHeaders = { 'Content-Type': 'application/json' };
            if (cfCsrf) cfHeaders['X-CSRFToken'] = cfCsrf;
            var cfPayload = {
                directive: 'Start' + (flowData.niche === 'scholarly'
                    ? ' Scholarly niche: ' + (flowData.scholarlyTopic || 'crime')
                    : flowData.niche ? ' Clipfarm niche: ' + flowData.niche : ' Clipfarm using analytics'),
                niche: flowData.niche || null,
                scholarly_topic: flowData.scholarlyTopic || null,
                mode: flowData.nicheOrAnalytics || 'analytics',
                user_name: userName,
                url: window.location.href
            };
            var wantUpdates = flowData.wantUpdates;
            flowState = '';
            flowData = {};
            // Clear any previous manual stop before launching a new run
            fetch('/api/zero/stop/reset', { method: 'POST', headers: cfHeaders, credentials: 'same-origin' }).catch(function(){});
            fetch('/api/start_clipfarm_workflow', {
                method: 'POST', headers: cfHeaders, body: JSON.stringify(cfPayload), credentials: 'same-origin'
            }).then(function (r) { return r.ok ? r.json() : { error: 'Server error ' + r.status }; })
              .then(function (data) {
                var jobId = data.pipeline_id || data.job_id;
                if (jobId) {
                    var wid = 'zero-pipeline-widget-' + jobId;
                    appendLog('<strong>Zero:</strong> Pipeline started — <span id="' + wid + '">Stage 1 — Discovery</span>', true);
                    if (wantUpdates) startPipelinePolling(jobId);
                } else {
                    appendLog('<strong>Zero:</strong> ' + (data.error || 'Pipeline start failed.'), true);
                }
              }).catch(function (err) {
                if (!window._serverRestarting) appendLog('<strong>Zero:</strong> Could not start pipeline: ' + (err.message || 'Network error'), true);
              });
            showMainMenu();
        }
    }

    function runWorkflowHealthThenSummary() {
        appendLog('<em>Checking workflow health…</em>', true);
        fetchWorkflowHealth().then(function (health) {
            var last = logEl.querySelector('.agent-zero-msg:last-child');
            if (last && last.textContent.indexOf('Checking') >= 0) last.remove();
            _workflowIssues = health.issues || [];
            _issueIndex = 0;
            var unresolved = _workflowIssues.filter(function (i) { return !i.resolved; });
            if (unresolved.length > 0) {
                appendLog(
                    '<strong>Zero:</strong> Before launching, I need to flag <strong>' + unresolved.length
                    + '</strong> issue' + (unresolved.length > 1 ? 's' : '') + ' in the workflow.',
                    true
                );
                showNextIssue();
            } else {
                showClipfarmSummary();
            }
        });
    }

    function showClipfarmSummary() {
        flowState = 'clipfarm_summary';
        var nicheDisplay = flowData.niche || '?';
        if (flowData.niche === 'scholarly' && flowData.scholarlyTopic) {
            nicheDisplay = 'Scholarly — ' + flowData.scholarlyTopic;
        }
        var modeLabel = flowData.nicheOrAnalytics === 'niche'
            ? 'Niche — <strong>' + escapeHtml(nicheDisplay) + '</strong>'
            : 'Analytics-driven (auto-select niches)';
        appendLog('<strong>Zero:</strong> Ready to launch Clipfarm:', true);
        appendLog('<div class="agent-zero-summary"><div>Production: Clipfarm</div><div>Mode: ' + modeLabel + '</div></div>Confirm?', true, true);
        appendChoices([{ label: '✅ Yes, launch', value: 'yes' }, { label: '✗ Change', value: 'no' }]);
    }

    function showMainMenu() {
        disableOldChoices();
        if (menuAlreadyShown()) { flowState = 'main_menu'; _currentMode = ''; return; }
        flowState = 'main_menu';
        _currentMode = '';
        appendLog('<strong>Zero:</strong> How can I help?', true);
        appendChoices([
            { label: '* Planning *', value: 'planning' },
            { label: '* Production *', value: 'production' },
            { label: '* Information *', value: 'information' },
            { label: '* Integrity *', value: 'integrity' },
            { label: '* Governance *', value: 'governance' },
            { label: '* Coding *', value: 'coding' }
        ]);
    }

    function initChoiceDelegation() {
        if (!logEl) return;
        logEl.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-zero-choice]');
            if (btn) {
                e.preventDefault();
                var val = btn.getAttribute('data-zero-choice');
                if (val) handleFlowChoice(val);
            }
        });
    }

    function sendMessage() {
        var msg = inputEl ? inputEl.value.trim() : '';
        var hasImg = !!attachedImageB64;
        if (!msg && !hasImg) return;
        if (inputEl) inputEl.value = '';
        var displayMsg = msg || (hasImg ? '[Image]' : '');
        appendLog('<strong>' + escapeHtml(userName) + ':</strong> ' + escapeHtml(displayMsg) + (hasImg ? ' &#128247;' : ''), false);

        // ── MANUAL SAFETY STOP ──────────────────────────────────────────────
        var _msgLower = msg.trim().toLowerCase();
        var _isStopCmd = _msgLower === 'stop' ||
            _msgLower === 'stop!' ||
            _msgLower === 'stop pipeline' ||
            _msgLower === 'stop the pipeline' ||
            _msgLower === 'please stop' ||
            _msgLower === 'halt' ||
            _msgLower === 'cancel' ||
            _msgLower === 'cancel pipeline' ||
            /^stop[!.\s]*$/.test(_msgLower);
        if (_isStopCmd) {
            if (_pipelinePollInterval) { clearInterval(_pipelinePollInterval); _pipelinePollInterval = null; }
            _activePipelineJobId = null;
            var csrf2 = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
            var h2 = { 'Content-Type': 'application/json' };
            if (csrf2) h2['X-CSRFToken'] = csrf2;
            fetch('/api/zero/stop', { method: 'POST', headers: h2, credentials: 'same-origin' })
                .then(function(r) { return r.ok ? r.json() : { message: 'Stop signal sent.' }; })
                .then(function(d) {
                    appendLog('<strong>Zero:</strong> ⛔ <strong>STOP — all pipeline activity halted.</strong> ' +
                        escapeHtml(d.message || '') + '<br><small>Say <em>resume</em> or start a new run when ready.</small>', true);
                    _saveState();
                })
                .catch(function() {
                    appendLog('<strong>Zero:</strong> ⛔ Stop signal sent (could not confirm server response).', true);
                });
            return;
        }

        var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
        var headers = { 'Content-Type': 'application/json' };
        if (csrf) headers['X-CSRFToken'] = csrf;

        if (flowState === 'gov_task_update_input' && msg) {
            flowState = '';
            flowData = {};
            var state = {};
            msg.split(',').forEach(function (part) {
                part = part.trim();
                var eq = part.indexOf('=');
                if (eq > 0) {
                    var k = part.substring(0, eq).trim().toLowerCase();
                    var v = part.substring(eq + 1).trim();
                    if (k === 'phase') state.phase = v;
                    else if (k === 'goal') state.current_goal = v;
                    else if (k === 'open_issues') state.open_issues = v.split(';').map(function (x) { return x.trim(); }).filter(Boolean);
                    else if (k === 'blocked') state.blocked = v.split(';').map(function (x) { return x.trim(); }).filter(Boolean);
                }
            });
            if (Object.keys(state).length === 0) return;
            appendLog('<strong>' + userName + ':</strong> ' + msg, false);
            var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
            var headers = { 'Content-Type': 'application/json' };
            if (csrf) headers['X-CSRFToken'] = csrf;
            fetch('/api/zero/task-state', { method: 'POST', headers: headers, body: JSON.stringify(state), credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    appendLog('<strong>Zero:</strong> Task state updated. Phase: ' + (data.phase || '(unchanged)') + ', Goal: ' + (data.current_goal || '(unchanged)'), true);
                })
                .catch(function (err) { if (!window._serverRestarting) appendLog('<strong>Zero:</strong> Update failed: ' + (err.message || 'Network error'), true); });
            showMainMenu();
            return;
        }

        if (flowState === 'gov_impact_input' && msg) {
            flowState = '';
            flowData = {};
            var paths = msg.split(/[\n,;]/).map(function (p) { return p.trim(); }).filter(Boolean);
            if (paths.length === 0) return;
            appendLog('<strong>' + escapeHtml(userName) + ':</strong> ' + escapeHtml(paths.join(', ')), false);
            appendLog('<em>Analyzing…</em>', true);
            var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
            var headers = { 'Content-Type': 'application/json' };
            if (csrf) headers['X-CSRFToken'] = csrf;
            fetch('/api/zero/change-impact', { method: 'POST', headers: headers, body: JSON.stringify({ paths: paths }), credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    var last = logEl.querySelector('.agent-zero-msg:last-child');
                    if (last && last.textContent.indexOf('Analyzing') >= 0) last.remove();
                    var results = data.results || [];
                    var html = '<strong>Zero:</strong> Change impact:<div class="agent-zero-summary" style="margin-top:8px;">';
                    results.forEach(function (r) {
                        html += '<div style="margin-bottom:10px;border-bottom:1px solid #ddd;padding-bottom:8px;">';
                        html += '<strong>' + escapeHtml(r.file || '') + '</strong><br>';
                        if (r.module) html += 'Module: ' + escapeHtml(r.module) + '<br>';
                        if ((r.data_entities || []).length) html += 'Data: ' + (r.data_entities || []).join(', ') + '<br>';
                        if (r.route_impact) html += '<span style="color:#b45309;">Route impact</span><br>';
                        if (r.safety_impact) html += '<span style="color:#b45309;">Safety impact</span><br>';
                        (r.notes || []).forEach(function (n) { html += '• ' + escapeHtml(n) + '<br>'; });
                        html += '</div>';
                    });
                    html += '</div>';
                    appendLog(html, true, true);
                    appendLog('<strong>Zero:</strong> Review validation checklist before applying in Cursor.', true);
                })
                .catch(function (err) {
                    var last = logEl.querySelector('.agent-zero-msg:last-child');
                    if (last && last.textContent.indexOf('Analyzing') >= 0) last.remove();
                    if (!window._serverRestarting) appendLog('<strong>Zero:</strong> Impact analysis failed: ' + (err.message || 'Network error'), true);
                });
            showMainMenu();
            return;
        }

        if (flowState === 'planning_goal' && msg) {
            flowState = '';
            flowData = {};
            appendLog('<em>Decomposing into tasks…</em>', true);
            fetch('/api/zero/decompose', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ goal: msg }),
                credentials: 'same-origin'
            }).then(function (r) { return r.json(); }).then(function (data) {
                var last = logEl.querySelector('.agent-zero-msg:last-child');
                if (last && last.textContent.indexOf('Decomposing') >= 0) last.remove();
                if (data.error) {
                    appendLog('<strong>Zero:</strong> ' + data.error, true);
                } else {
                    var subs = data.subtasks || [];
                    var html = '<strong>Zero:</strong> Task breakdown for: <em>' + escapeHtml(data.goal || msg) + '</em><div class="agent-zero-summary" style="margin-top:8px;">';
                    subs.forEach(function (t, i) {
                        html += '<div><strong>' + (i + 1) + '.</strong> [' + (t.specialist || t.type) + '] ' + escapeHtml(t.description || '') + '</div>';
                    });
                    html += '</div>';
                    appendLog(html, true, true);
                    appendLog('<strong>Zero:</strong> Use Cursor for file edits. I can answer architecture questions or refine the plan. What next?', true);
                }
                showMainMenu();
            }).catch(function (err) {
                var last = logEl.querySelector('.agent-zero-msg:last-child');
                if (last && last.textContent.indexOf('Decomposing') >= 0) last.remove();
                if (!window._serverRestarting) appendLog('<strong>Zero:</strong> Decompose failed: ' + (err.message || 'Network error'), true);
                showMainMenu();
            });
            return;
        }

        addToHistory('user', msg || '[image]');
        appendLog('<em>Zero is thinking…</em>', true);
        var payload = { message: msg, history: conversationHistory.slice(-8) };
        if (flowState === 'coding' || _currentMode === 'coding') payload.task_type = 'code';
        if (attachedImageB64) { payload.image_base64 = attachedImageB64; payload.task_type = 'vision'; }
        attachedImageB64 = null;
        clearImage();

        fetch('/api/zero/chat', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(payload),
            credentials: 'same-origin'
        }).then(function (r) { return r.json(); }).then(function (data) {
            var last = logEl.querySelector('.agent-zero-msg:last-child');
            if (last && last.textContent.indexOf('thinking') >= 0) last.remove();
            var resp = data.response || data.error || 'No response.';
            addToHistory('zero', resp);
            appendLog('<strong>Zero:</strong> ' + resp, true);
            // In named modes, stay in mode — show mode bar again for follow-ups
            if (_currentMode) {
                appendModeBar(_currentMode.charAt(0).toUpperCase() + _currentMode.slice(1));
            }
            // In free chat (no mode, no flowState), stay open — don't push main menu
        }).catch(function (err) {
            var last = logEl.querySelector('.agent-zero-msg:last-child');
            if (last && last.textContent.indexOf('thinking') >= 0) last.remove();
            if (!window._serverRestarting) appendLog('<strong>Zero:</strong> I could not reach the server: ' + (err.message || 'Network error'), true);
        });
    }

    function initSpeechRecognition() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) return;
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';
        recognition.onresult = function (e) {
            var last = e.results.length - 1;
            var transcript = e.results[last][0].transcript;
            if (e.results[last].isFinal && transcript && inputEl) {
                inputEl.value = (inputEl.value + ' ' + transcript).trim();
            }
        };
    }

    function startListening() {
        if (!recognition || isListening) return;
        try {
            recognition.start();
            isListening = true;
            if (micBtn) { micBtn.style.background = '#c0392b'; micBtn.title = 'Listening… release to stop'; }
        } catch (_) {}
    }

    function stopListening() {
        if (!recognition || !isListening) return;
        try {
            recognition.stop();
            isListening = false;
            if (micBtn) { micBtn.style.background = ''; micBtn.title = 'Hold to talk'; }
        } catch (_) {}
    }

    function openZero() {
        createOverlay();
        overlay.style.display = 'flex';
        dialog.style.display = 'flex';
        if (minimizedTab) minimizedTab.style.display = 'none';
        centerDialog();
        // Pending requests take priority — always show fresh data, never stale saved state
        if (_pendingManualCount > 0 && _pendingListCache.length > 0) {
            if (logEl) logEl.innerHTML = '';
            try { sessionStorage.removeItem(_SS_KEY); } catch (_) {}
            appendLog('<strong>Zero:</strong> Pending request awaiting your decision.', true);
            _showPendingRequests(_pendingListCache);
            if (inputEl) inputEl.focus();
            return;
        }
        // Restore chat from sessionStorage if this is a fresh page load
        if (logEl && logEl.children.length === 0) {
            if (_restoreState()) {
                if (inputEl) inputEl.focus();
                return;
            }
        }
        if (logEl && logEl.children.length === 0) {
            fetch('/api/zero/llms-status', { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : { ready: true }; })
                .catch(function () { return { ready: true }; })
                .then(function (data) {
                    if (!data.ready) {
                        flowState = 'llms_prompt';
                        appendLog('<strong>Zero:</strong> Install the missing LLMs I require to function. Want to install the LLMs?', true);
                        appendChoices([{ label: 'Yes', value: 'yes' }, { label: 'No', value: 'no' }]);
                        return;
                    }
                    fetch('/api/zero/context', { credentials: 'same-origin' })
                        .then(function (r) { return r.ok ? r.json() : {}; })
                        .catch(function () { return {}; })
                        .then(function (ctx) { showContextualGreeting(ctx); });
                });
        }
        if (inputEl) { inputEl.focus(); }
    }

    function closeZero() {
        stopListening();
        if (overlay) overlay.style.display = 'none';
        if (dialog) dialog.style.display = 'none';
        if (minimizedTab) minimizedTab.style.display = 'none';
    }

    function onEscape(e) {
        if (e.key !== 'Escape') return;
        if (!isZeroVisible()) return;
        closeZero();
        e.preventDefault();
    }

    function resetZero() {
        // Clear conversation, stop any active pipeline poll, wipe sessionStorage, show fresh menu
        if (_pipelinePollInterval) { clearInterval(_pipelinePollInterval); _pipelinePollInterval = null; }
        _activePipelineJobId = null;
        flowState = '';
        flowData = {};
        conversationHistory = [];
        _currentMode = '';
        _workflowIssues = [];
        _issueIndex = 0;
        if (logEl) logEl.innerHTML = '';
        try { sessionStorage.removeItem(_SS_KEY); } catch (_) {}
        if (!isZeroVisible()) {
            if (overlay) overlay.style.display = 'flex';
            if (dialog) dialog.style.display = 'flex';
            if (minimizedTab) minimizedTab.style.display = 'none';
            centerDialog();
        }
        showMainMenu();
    }

    function initHotkey() {
        document.addEventListener('keydown', onEscape);
        document.addEventListener('keydown', function (e) {
            if (e.key.toLowerCase() !== ZERO_HOTKEY) return;
            var tag = (e.target || document.activeElement).tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA') return;
            e.preventDefault();
            if (isZeroMinimized()) {
                expandZero();
            } else if (overlay && overlay.style.display === 'flex') {
                closeZero();
            } else {
                openZero();
            }
        });
        // Ctrl+R while Zero is open = hard reset conversation back to main menu
        document.addEventListener('keydown', function (e) {
            if (!e.ctrlKey || e.key.toLowerCase() !== 'r') return;
            if (!isZeroVisible()) return;
            var tag = (e.target || document.activeElement).tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA') return;
            e.preventDefault();
            resetZero();
        });
    }

    function initSidebarTab() {
        var tab = byId('dashboard-sidebar-agent-zero');
        if (tab) {
            tab.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                openZero();
            });
        }
        _startPendingPoll();
    }

    // ── Pending manual-request polling & blinking ──────────────────────────
    function _startPendingPoll() {
        if (_pendingPollInterval) return;
        _pollPendingManual();
        _pendingPollInterval = setInterval(_pollPendingManual, 5000);
        // Expose globally so the restart handler can clear it
        window._agentZeroPendingPollInterval = _pendingPollInterval;
    }

    function _pollPendingManual() {
        if (window._serverRestarting) return;
        fetch('/api/zero_public/pending', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data) return;
                var count = data.count || 0;
                var list  = (data.pending || []).filter(function (r) { return r.status === 'pending'; });
                _setPendingCount(count, list);
            })
            .catch(function () {});
    }

    // ── Shared JS blink loop — keeps sidebar button and bottom tab perfectly in sync ──
    function _applyBlinkFrame(high) {
        var sidebarBtn = byId('dashboard-sidebar-agent-zero');
        var tab = minimizedTab;
        // Soft blue-gray brightening — same palette as the buttons, just more saturated
        var bgHighSidebar = 'rgba(148,168,210,0.55)';
        var bgHighTab     = 'linear-gradient(140deg,#bfcde6,#96aece)';
        var borderHigh    = '#8facd4';
        var shadowSidebar = '0 0 10px rgba(140,165,210,0.4)';
        var shadowTab     = '0 -4px 16px rgba(120,148,195,0.45)';
        if (sidebarBtn) {
            sidebarBtn.style.background  = high ? bgHighSidebar : '';
            sidebarBtn.style.borderColor = high ? borderHigh    : '';
            sidebarBtn.style.color       = '';   // keep default text colour always
            sidebarBtn.style.boxShadow   = high ? shadowSidebar : '';
        }
        if (tab && tab.style.display !== 'none') {
            tab.style.background  = high ? bgHighTab   : '';
            tab.style.borderColor = high ? borderHigh  : '';
            tab.style.color       = '';   // keep default text colour always
            tab.style.boxShadow   = high ? shadowTab   : '';
        }
    }

    function _startBlinkLoop() {
        if (_blinkInterval) return;
        _blinkHigh = false;
        _blinkInterval = setInterval(function () {
            _blinkHigh = !_blinkHigh;
            _applyBlinkFrame(_blinkHigh);
        }, 900);  // 900ms per half-cycle → 1.8s full blink cycle
    }

    function _stopBlinkLoop() {
        if (_blinkInterval) { clearInterval(_blinkInterval); _blinkInterval = null; }
        _blinkHigh = false;
        _applyBlinkFrame(false);  // reset both to normal colours
    }

    function _setPendingCount(count, pendingList) {
        _pendingManualCount = count;
        _pendingListCache = pendingList || [];
        // Ensure overlay/tab elements exist
        if (!minimizedTab) createOverlay();

        var sidebarBtn = byId('dashboard-sidebar-agent-zero');
        var tab = minimizedTab || byId('agent-zero-tab') || document.querySelector('.agent-zero-tab');

        if (count > 0) {
            // ── Show sidebar button ──────────────────────────────────────────
            if (sidebarBtn) {
                sidebarBtn.style.display = 'block';
                // Update/create badge
                var badge = sidebarBtn.querySelector('.zpub-pending-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'zpub-pending-badge';
                    sidebarBtn.appendChild(badge);
                }
                badge.textContent = count;
                badge.style.display = 'flex';
            }
            // ── Show bottom tab ──────────────────────────────────────────────
            if (tab) {
                tab.style.position = 'fixed';
                tab.style.bottom = '0';
                tab.style.zIndex = '99998';
                if (!isZeroVisible()) tab.style.display = 'flex';
                var tabBadge = tab.querySelector('.zpub-pending-badge');
                if (!tabBadge) {
                    tabBadge = document.createElement('span');
                    tabBadge.className = 'zpub-pending-badge';
                    tab.style.position = 'fixed';  // keep fixed (not relative!)
                    tab.appendChild(tabBadge);
                }
                tabBadge.textContent = count;
                tabBadge.style.display = 'flex';
            }
            // ── Start shared blink loop (guarantees both blink in sync) ──────
            _startBlinkLoop();
        } else {
            // ── Hide sidebar button ──────────────────────────────────────────
            if (sidebarBtn) {
                sidebarBtn.style.display = 'none';
                var badge = sidebarBtn.querySelector('.zpub-pending-badge');
                if (badge) badge.style.display = 'none';
            }
            // ── Hide bottom tab (unless Zero is open/minimized) ──────────────
            if (tab) {
                var tabBadge = tab.querySelector('.zpub-pending-badge');
                if (tabBadge) tabBadge.style.display = 'none';
                if (!isZeroVisible()) tab.style.display = 'none';
            }
            // ── Stop blink loop ──────────────────────────────────────────────
            _stopBlinkLoop();
        }

        _lastNotifiedPendingCount = count;
    }

    function _decidePending(reqId, action) {
        var label = action === 'allow' ? 'Allowing' : action === 'queue' ? 'Queuing' : 'Declining';
        appendLog('<em>' + label + ' request…</em>', true);
        fetch('/api/zero_public/pending/' + reqId + '/decide', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var last = logEl.querySelector('.agent-zero-msg:last-child');
                if (last && last.textContent.indexOf('ing request') >= 0) last.remove();
                if (data.ok) {
                    var msgs = {
                        allow:   '✅ Request <strong>approved</strong> — job queued.',
                        queue:   '🕐 Request <strong>queued</strong> — it will wait until you allow it.',
                        decline: '❌ Request <strong>declined</strong>.',
                    };
                    appendLog('<strong>Zero:</strong> ' + (msgs[action] || 'Done.'), true);
                    _pollPendingManual();
                    // Show remaining pending if any
                    fetch('/api/zero_public/pending', { credentials: 'same-origin' })
                        .then(function (r) { return r.ok ? r.json() : { pending: [] }; })
                        .then(function (d) {
                            var stillPending = (d.pending || []).filter(function (r) { return r.status === 'pending'; });
                            if (stillPending.length > 0) {
                                _showPendingRequests(stillPending);
                            } else {
                                appendChoices([{ label: '← Main menu', value: '_back_to_menu' }]);
                            }
                        });
                } else {
                    appendLog('<strong>Zero:</strong> Error — ' + escapeHtml(data.error || 'unknown error'), true);
                    appendChoices([{ label: '← Back', value: '_back_to_menu' }]);
                }
            })
            .catch(function (err) {
                appendLog('<strong>Zero:</strong> Request failed: ' + escapeHtml(String(err)), true);
                appendChoices([{ label: '← Back', value: '_back_to_menu' }]);
            });
    }

    function _showPendingRequests(pendingList) {
        var pending = (pendingList || []).filter(function (r) { return r.status === 'pending'; });
        if (pending.length === 0) {
            appendLog('<strong>Zero:</strong> No pending requests at this time.', true);
            appendChoices([{ label: '← Back', value: '_back_to_menu' }]);
            return;
        }
        pending.forEach(function (req) {
            var label    = req.label || req.token || 'unknown';
            var url      = req.invite_url || '';
            var prompt   = req.prompt ? req.prompt.substring(0, 120) : '—';
            var pipeline = req.pipeline || 'unknown';
            var reqAt    = req.requested_at ? req.requested_at.replace('T', ' ').substring(0, 16) : '';
            // Delivered-vs-selected disclosure (2026-07-20): the anchor gate ships
            // the closest face FLUX could render and syncs to it, so surface the
            // deltas on the contact-sheet review card before the operator commits.
            var deltaHtml = '';
            var deltas = req.attribute_deltas || [];
            if (deltas.length) {
                var hard = deltas.filter(function (d) { return !d.advisory; });
                var adv  = deltas.filter(function (d) { return d.advisory; });
                function _row(d) {
                    return escapeHtml(d.label) + ': <b>' + escapeHtml(String(d.delivered)) +
                           '</b> (you selected ' + escapeHtml(String(d.selected)) + ')';
                }
                if (hard.length) {
                    deltaHtml += '<b style="color:#dc2626">⚠ Delivered differs from selection:</b><br>' +
                                 hard.map(function (d) { return '&nbsp;&nbsp;• ' + _row(d); }).join('<br>') + '<br>';
                }
                if (adv.length) {
                    deltaHtml += '<b style="color:#b45309">Advisory (FLUX can\'t reliably hit these):</b><br>' +
                                 adv.map(function (d) { return '&nbsp;&nbsp;• ' + _row(d); }).join('<br>') + '<br>';
                }
            }
            // Clickable review link (2026-07-21): the sheet path used to sit in
            // the prompt text as plain, un-clickable text. Build a real link from
            // the card's char_id to the main-app image route — a logged-in
            // dashboard session is authorized for /api/internal/ without a token,
            // so it opens straight in a new tab. char_id is regex-validated, so
            // it is safe to interpolate directly (no user-controlled content).
            var reviewHtml = '';
            var cid = req.char_id || '';
            if ((pipeline === 'contact_sheet_review' || pipeline === 'contact_sheet') &&
                /^[a-f0-9]{12}$/.test(cid)) {
                var sheetUrl = '/api/internal/storyteller/contact-sheet/image/' + cid;
                var linkStyle = 'color:#2563eb;text-decoration:underline;font-weight:600';
                // Default the primary review link to the TRAINING-SET sheet
                // (2026-07-22): it shows exactly the tiles that train — the
                // QC-excluded distortion tiles (smeared full-body, bad-eye
                // close-ups) are absent, so the operator reviews what the LoRA
                // actually learns instead of being alarmed by dropped tiles. The
                // full 48-angle sheet is kept as a secondary link.
                reviewHtml =
                    '<b>Review sheet:</b> ' +
                    '<a href="' + sheetUrl + '?variant=training" target="_blank" rel="noopener" style="' + linkStyle + '">🖼 open review sheet (what trains)</a>' +
                    ' &nbsp;·&nbsp; <a href="' + sheetUrl + '" target="_blank" rel="noopener" style="' + linkStyle + '">full 48-angle sheet</a>' +
                    ' &nbsp;·&nbsp; <a href="' + sheetUrl + '?variant=training&download=1" target="_blank" rel="noopener" style="' + linkStyle + '">⬇ download</a>' +
                    '<br>';
            }
            // Creature sheet review (2026-08-26): the creature gate parks a run
            // whose whole deliverable is one sheet, so the card links straight
            // at it. Same session-auth /api/internal route the contact-sheet
            // link uses; creature_id is 12-hex-validated server-side.
            var crid = req.creature_id || '';
            if (pipeline === 'creature_review' && /^[a-f0-9]{12}$/.test(crid)) {
                var crUrl = '/api/internal/creature/' + crid + '/sheet';
                var crStyle = 'color:#2563eb;text-decoration:underline;font-weight:600';
                var rep = req.sheet_report || {};
                reviewHtml +=
                    '<b>Review sheet:</b> ' +
                    '<a href="' + crUrl + '" target="_blank" rel="noopener" style="' + crStyle + '">\uD83D\uDDBC open creature sheet</a>' +
                    ' &nbsp;\u00b7&nbsp; <a href="' + crUrl + '?download=1" target="_blank" rel="noopener" style="' + crStyle + '">\u2b07 download</a>' +
                    '<br>';
                if (rep.cell_count) {
                    reviewHtml += '<b>Cells:</b> ' + escapeHtml(String(rep.pass_count)) + '/' +
                        escapeHtml(String(rep.cell_count)) + ' pass' +
                        (rep.judged_any ? '' : ' <span style="color:#b45309">(judge offline \u2014 structural + DINO only)</span>') +
                        '<br>';
                }
            }
            // Style-calibration preview links (2026-07-26): clickable links to a
            // character's Arcane sweep/preview grids, served by the contact-sheet
            // image route's ?preview= handler. cid is 12-hex-validated.
            var _pvs = req.preview_images || [];
            if (_pvs.length && /^[a-f0-9]{12}$/.test(cid)) {
                var _pbase = '/api/internal/storyteller/contact-sheet/image/' + cid + '?preview=';
                var _pstyle = 'color:#a855f7;text-decoration:underline;font-weight:600';
                reviewHtml += '<b>Style preview:</b> ' + _pvs.map(function (p) {
                    var _n = (typeof p === 'string') ? p : (p.name || '');
                    var _l = (typeof p === 'string') ? p : (p.label || p.name || '');
                    return '<a href="' + _pbase + encodeURIComponent(_n) + '" target="_blank" rel="noopener" style="' + _pstyle + '">🎨 ' + escapeHtml(_l) + '</a>';
                }).join(' &nbsp;·&nbsp; ') + '<br>';
            }
            appendLog(
                '<strong>Zero:</strong> <span style="color:#dc2626">Pending request</span><br>' +
                '<b>User:</b> ' + escapeHtml(label) + '<br>' +
                (url ? '<b>URL:</b> <code style="font-size:0.85em">' + escapeHtml(url) + '</code><br>' : '') +
                '<b>Pipeline:</b> ' + escapeHtml(pipeline) + '<br>' +
                '<b>Prompt:</b> ' + escapeHtml(prompt) + '<br>' +
                reviewHtml +
                deltaHtml +
                '<b>Requested:</b> ' + escapeHtml(reqAt),
                true
            );
            appendChoices([
                { label: '✅ Allow',   value: '_zpub_allow:'   + req.id },
                { label: '🕐 Queue',   value: '_zpub_queue:'   + req.id },
                { label: '❌ Decline', value: '_zpub_decline:' + req.id },
            ]);
        });
        appendChoices([{ label: '← Back', value: '_back_to_menu' }]);
    }

    // ── Live Tail ──────────────────────────────────────────────────────────
    function toggleLiveTail() {
        liveTailEnabled = !liveTailEnabled;
        var dot = byId('agent-zero-livetail-dot');
        if (dot) dot.style.background = liveTailEnabled ? '#a6e3a1' : '#555';

        if (liveTailEnabled) {
            openLiveTailDialog();
        } else {
            closeLiveTailDialog();
        }
    }

    function openLiveTailDialog() {
        if (liveTailDialog) { liveTailDialog.style.display = 'flex'; return; }

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
            '</div></div>'+
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
            '</tr></thead>'+
            '<tbody id="lt-subs-body"></tbody>' +
            '</table></div>' +
            // ── timeline pane ──
            '<div id="live-tail-timeline" style="flex:1;overflow-y:auto;padding:8px 12px;display:none;">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
            '<span style="color:#8b949e;font-size:10px;">Pipeline stage timings — live &#9210;</span>' +
            '<button id="lt-timeline-download" title="Download timeline as .txt" style="background:none;border:none;cursor:pointer;font-size:16px;color:#8b949e;padding:0 4px;" onclick="_ltDownloadTimeline()">&#128196;</button>' +
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

        // Tab switching
        byId('lt-tab-log').onclick      = function () { _ltSwitchTab('log'); };
        byId('lt-tab-subs').onclick     = function () { _ltSwitchTab('subs'); };
        byId('lt-tab-timeline').onclick = function () { _ltSwitchTab('timeline'); };

        byId('live-tail-close').onclick = function () {
            liveTailEnabled = false;
            var dot = byId('agent-zero-livetail-dot');
            if (dot) dot.style.background = '#555';
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
        logPane.style.display      = 'none';
        subsPane.style.display     = 'none';
        if (timelinePane) timelinePane.style.display = 'none';
        [tabLog, tabSubs, tabTimeline].forEach(function(t) {
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

    function _ltStartSubsPolling() {
        if (liveTailSubsInterval) clearInterval(liveTailSubsInterval);
        _ltFetchSubs();
        liveTailSubsInterval = setInterval(_ltFetchSubs, 1000);
    }

    function _ltFetchSubs() {
        fetch('/api/subprocesses').then(function(r){ return r.json(); }).then(function(d) {
            var tbody = byId('lt-subs-body');
            if (!tbody) return;
            var procs = (d.subprocesses || []).slice(0, 120);
            // Build map of existing rows
            var existingPids = {};
            var rows = tbody.querySelectorAll('tr[data-pid]');
            rows.forEach(function(r) { existingPids[r.getAttribute('data-pid')] = r; });
            procs.forEach(function(p) {
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
                        '<td style="padding:3px 6px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(p.label||'') + '">' + escapeHtml(p.label||'') + '</td>' +
                        '<td style="padding:3px 6px;color:#484f58;font-size:10px;">' + escapeHtml(ts) + '</td>' +
                        '<td style="padding:3px 6px;">' + cpu + '</td>' +
                        '<td style="padding:3px 6px;">' + gpu + '</td>' +
                        '<td style="padding:3px 6px;">' + mcpu + '</td>' +
                        '<td style="padding:3px 6px;">' + mgpu + '</td>' +
                        '<td style="padding:3px 6px;"><span style="color:' + statusColor + ';">' + statusText + '</span></td>';
                    tr.onclick = (function(proc) { return function() { _ltOpenWorkerDetail(proc); }; })(p);
                    tbody.insertBefore(tr, tbody.firstChild);
                }
            });
        }).catch(function(){});
    }

    function _ltOpenWorkerDetail(p) {
        // Fetch fresh data with samples
        fetch('/api/subprocesses/' + p.pid).then(function(r){ return r.json(); }).then(function(data) {
            if (data.error) data = p; // fallback to passed object
            var started = (data.started || '').replace('T', ' ').substring(0, 19);
            var ended   = data.ended ? (data.ended || '').replace('T', ' ').substring(0, 19) : '—';
            var dur = '—';
            if (data.started && data.ended) {
                try {
                    var ms = new Date(data.ended) - new Date(data.started);
                    var s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
                    dur = h ? h + 'h ' + (m % 60) + 'm ' + (s % 60) + 's' : m ? m + 'm ' + (s % 60) + 's' : s + 's';
                } catch(_) {}
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
                samples.slice(-30).forEach(function(s) {
                    samplesHtml += '<tr><td style="padding:2px 6px;color:#484f58;font-size:10px;">' + (s.t||'').replace('T',' ').substring(0,19) + '</td>' +
                        '<td style="padding:2px 6px;">' + (s.cpu||0).toFixed(1) + '</td>' +
                        '<td style="padding:2px 6px;">' + (s.gpu||0).toFixed(1) + '</td></tr>';
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
                '<span style="color:#58a6ff;font-weight:bold;">Worker Detail — PID ' + escapeHtml(String(data.pid||'')) + '</span>' +
                '<button style="background:#da3633;color:#fff;border:none;border-radius:5px;padding:2px 8px;cursor:pointer;">&#10005;</button>' +
                '</div>' +
                '<div style="padding:12px;overflow-y:auto;flex:1;">' +
                '<p style="margin:4px 0;"><strong>Label:</strong> ' + escapeHtml(data.label||'—') + '</p>' +
                '<p style="margin:4px 0;"><strong>Pipeline:</strong> ' + escapeHtml(data.pipeline_id||'—') + '</p>' +
                '<p style="margin:4px 0;"><strong>Started:</strong> ' + escapeHtml(started) + '</p>' +
                '<p style="margin:4px 0;"><strong>Ended:</strong> ' + escapeHtml(ended) + '</p>' +
                '<p style="margin:4px 0;"><strong>Duration:</strong> ' + escapeHtml(dur) + '</p>' +
                '<p style="margin:4px 0;"><strong>Max CPU:</strong> ' + (data.max_cpu_pct||0).toFixed(1) + '%</p>' +
                '<p style="margin:4px 0;"><strong>Max GPU:</strong> ' + (data.max_gpu_pct||0).toFixed(1) + '%</p>' +
                samplesHtml +
                '</div>';
            dlg.querySelector('button').onclick = function() { dlg.remove(); };
            document.body.appendChild(dlg);
        }).catch(function(){ });
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
        fetch('/api/pipeline/active').then(function(r){ return r.json(); }).then(function(d) {
            var pid = d.pipeline_id || null;
            if (pid) _liveTailCurrentPipelineId = pid;
            var resolvedId = _liveTailCurrentPipelineId;
            if (!resolvedId) {
                var tbody = byId('lt-timeline-body');
                if (tbody) tbody.innerHTML = '<tr><td colspan="3" style="color:#484f58;padding:10px 8px;font-size:11px;">No active pipeline. Run a video to see timeline.</td></tr>';
                return;
            }
            fetch('/api/pipeline/timeline/' + resolvedId).then(function(r){ return r.json(); }).then(function(td) {
                var tbody = byId('lt-timeline-body');
                if (!tbody) return;
                // The endpoint returns 'stages' — reading 'stage_timeline' here
                // left the table permanently empty and the total at 0s.
                var stages = td.stages || td.stage_timeline || [];
                var pipelineLive = td.runtime_running === true;
                tbody.innerHTML = '';
                stages.forEach(function(s) {
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
            }).catch(function(){ });
        }).catch(function(){ });
    }

    function _ltDownloadTimeline() {
        var pid = _liveTailCurrentPipelineId;
        if (!pid) { alert('No pipeline timeline available yet.'); return; }
        window.location = '/api/pipeline/timeline/' + pid + '/download';
    }

    function _ltFetchFlags() {
        fetch('/api/pipeline/flags').then(function(r){ return r.json(); }).then(function(d) {
            _ltFlags = d.flags || [];
            _ltUpdateFlagBadge();
            if (_ltFlagPopover && _ltFlagPopover.parentNode) _ltRenderFlagList();
        }).catch(function(){});
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
        _ltFlagPopover.querySelector('#lt-flag-close').onclick = function() {
            if (_ltFlagPopover) { _ltFlagPopover.remove(); _ltFlagPopover = null; }
        };
        // Close when clicking outside
        setTimeout(function() {
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
        _ltFlags.forEach(function(f) {
            var isErr = f.level === 'ERROR';
            var color = isErr ? '#f85149' : '#d29922';
            var icon  = isErr ? '✗' : '⚠';
            var ts = '';
            if (f.ts) {
                try {
                    var _hasTz = f.ts.endsWith('Z') || /[+\-]\d{2}:?\d{2}$/.test(f.ts);
                    var d = new Date(_hasTz ? f.ts : (f.ts + 'Z'));
                    var pad = function(n){ return n < 10 ? '0'+n : n; };
                    ts = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
                } catch(_) { ts = f.ts.substring(11, 19); }
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

    function closeLiveTailDialog() {
        if (liveTailSSE) { liveTailSSE.close(); liveTailSSE = null; }
        if (liveTailSubsInterval) { clearInterval(liveTailSubsInterval); liveTailSubsInterval = null; }
        if (_liveTailTimelineInterval) { clearInterval(_liveTailTimelineInterval); _liveTailTimelineInterval = null; }
        if (liveTailDialog) { liveTailDialog.style.display = 'none'; }
    }

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
                    var alreadyHave = _ltFlags.some(function(f) { return (f.message || '').substring(0, 120) === msgKey; });
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

    var _ltCurrentPipelineId = null;

    var LEVEL_COLORS = { INFO: '#58a6ff', WARNING: '#d29922', ERROR: '#f85149', SYS: '#3fb950' };

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
                var pad = function(n){ return n < 10 ? '0'+n : n; };
                ts = d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) +
                     ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
            } catch(_) {
                ts = entry.ts.replace('T', ' ').substring(0, 19);
            }
        }
        var line = document.createElement('div');
        // Highlight WARNING/ERROR rows with a subtle background
        var rowBg = entry.level === 'ERROR'   ? 'background:rgba(248,81,73,0.08);' :
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

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initHotkey();
            initSidebarTab();
        });
    } else {
        initHotkey();
        initSidebarTab();
    }

    window.AgentZero = { open: openZero, close: closeZero };
})();
