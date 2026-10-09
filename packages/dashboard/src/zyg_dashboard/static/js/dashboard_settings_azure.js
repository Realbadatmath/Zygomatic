// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── Azure Cloud settings tab ──────────────────────────────────────────────── */

(function () {
    'use strict';

    // ── Navigation ────────────────────────────────────────────────────────────

    window.showSettingsAzureView = function () {
        var securityView = document.getElementById('dashboard-settings-security');
        var azurePanel = document.getElementById('dashboard-settings-azure');
        if (securityView) securityView.style.display = 'none';
        if (azurePanel) { azurePanel.style.display = 'block'; azureLoadAll(); }
    };

    function _backToSecurity() {
        const secBtns = document.getElementById('dashboard-settings-security-buttons');
        const azurePanel = document.getElementById('dashboard-settings-azure');
        if (azurePanel) azurePanel.style.display = 'none';
        if (secBtns)   secBtns.style.display = '';
    }

    // ── Bootstrap ─────────────────────────────────────────────────────────────

    function _init() {
        const backBtn = document.getElementById('dashboard-settings-azure-back');
        if (backBtn) backBtn.addEventListener('click', _backToSecurity);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _init);
    } else {
        _init();
    }

    // ── Load config + usage ───────────────────────────────────────────────────

    function azureLoadAll() {
        azureLoadConfig();
        azureLoadUsage();
    }
    window.azureLoadAll = azureLoadAll;

    window.azureLoadConfig = function () {
        fetch('/api/azure/config')
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                const c = data.config;
                _setVal('azure-blob-connection-string', c.blob_connection_string);
                _setVal('azure-blob-container',         c.blob_container);
                _setVal('azure-eventgrid-endpoint',     c.eventgrid_endpoint);
                _setVal('azure-eventgrid-key',          c.eventgrid_key);
                _setVal('azure-function-url',           c.function_url);
                _setVal('azure-function-key',           c.function_key);
                _setVal('azure-speech-key',             c.speech_key);
                _setVal('azure-speech-region',          c.speech_region || 'westeurope');
                if (c.speech_voice) _setSelect('azure-speech-voice', c.speech_voice);
                _setCheck('azure-blob-enabled',        !!c.blob_enabled);
                _setCheck('azure-eventgrid-enabled',   !!c.eventgrid_enabled);
                _setCheck('azure-function-enabled',    !!c.function_enabled);
                _setCheck('azure-speech-enabled',      !!c.speech_enabled);
            })
            .catch(err => console.error('[Azure] config load error:', err));
    };

    window.azureLoadUsage = function () {
        const wrap = document.getElementById('azure-usage-meters');
        if (!wrap) return;
        wrap.innerHTML = '<div style="color:#999;font-size:0.85rem;">Loading…</div>';
        fetch('/api/azure/usage')
            .then(r => r.json())
            .then(data => {
                if (!data.success) { wrap.innerHTML = '<span style="color:#dc2626;font-size:0.85rem;">Failed to load usage.</span>'; return; }
                const usage = data.usage;
                const rows = [
                    { key: 'blob_uploads',      label: '🗄️ Blob uploads',      unit: 'ops'   },
                    { key: 'blob_bytes',        label: '🗄️ Blob data',          unit: 'bytes' },
                    { key: 'function_calls',    label: '⚙️ Function calls',     unit: 'calls' },
                    { key: 'eventgrid_events',  label: '⚡ Event Grid events',  unit: 'events'},
                    { key: 'apim_calls',        label: '🛡️ APIM calls',         unit: 'calls' },
                ];
                wrap.innerHTML = rows.map(r => {
                    const svc = usage[r.key];
                    if (!svc) return '';
                    const pct = Math.min(100, Math.round((svc.used / svc.limit) * 100));
                    const cls = svc.status === 'ok' ? 'azure-meter-ok' : svc.status === 'warn' ? 'azure-meter-warn' : 'azure-meter-crit';
                    const badge = svc.status === 'blocked'
                        ? '<span style="background:#fef2f2;color:#dc2626;border-radius:8px;padding:1px 7px;font-weight:600;font-size:0.78rem;">PAUSED</span>'
                        : svc.status === 'warn'
                            ? '<span style="background:#fffbeb;color:#92400e;border-radius:8px;padding:1px 7px;font-size:0.78rem;">⚠ Near limit</span>'
                            : '';
                    const valStr = r.unit === 'bytes' ? _fmtBytes(svc.used) + ' / ' + _fmtBytes(svc.limit) : svc.used.toLocaleString() + ' / ' + svc.limit.toLocaleString() + ' ' + r.unit;
                    return `<div class="azure-meter-row ${cls}" style="margin-bottom:4px;">
                        <span style="min-width:160px;">${r.label}</span>
                        <div class="azure-meter-bar"><div class="azure-meter-fill" style="width:${pct}%"></div></div>
                        <span style="min-width:120px;color:#555;">${valStr}</span>
                        <span style="color:#888;font-size:0.78rem;">${pct}%</span>
                        ${badge}
                        <button type="button" onclick="azureResetCounter('${r.key}')" title="Reset counter" style="background:none;border:none;cursor:pointer;color:#9ca3af;font-size:0.82rem;padding:0 4px;">↺</button>
                    </div>`;
                }).join('');
            })
            .catch(err => { wrap.innerHTML = '<span style="color:#dc2626;font-size:0.85rem;">Error loading usage.</span>'; console.error('[Azure] usage error:', err); });
    };

    // ── Save config ───────────────────────────────────────────────────────────

    window.azureSaveConfig = function () {
        const payload = {
            blob_connection_string: _getVal('azure-blob-connection-string'),
            blob_container:         _getVal('azure-blob-container') || 'zygomatic-outputs',
            blob_enabled:           _getCheck('azure-blob-enabled'),
            eventgrid_endpoint:     _getVal('azure-eventgrid-endpoint'),
            eventgrid_key:          _getVal('azure-eventgrid-key'),
            eventgrid_enabled:      _getCheck('azure-eventgrid-enabled'),
            function_url:           _getVal('azure-function-url'),
            function_key:           _getVal('azure-function-key'),
            function_enabled:       _getCheck('azure-function-enabled'),
            speech_key:             _getVal('azure-speech-key'),
            speech_region:          _getVal('azure-speech-region') || 'westeurope',
            speech_voice:           _getSelect('azure-speech-voice') || 'en-GB-RyanNeural',
            speech_enabled:         _getCheck('azure-speech-enabled'),
        };
        const msg = document.getElementById('azure-save-msg');
        if (msg) msg.textContent = 'Saving…';
        fetch('/api/azure/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken() },
            body: JSON.stringify(payload),
        })
            .then(r => r.json())
            .then(data => {
                if (msg) msg.textContent = data.success ? '✅ Saved' : '❌ ' + (data.error || 'Failed');
                setTimeout(() => { if (msg) msg.textContent = ''; }, 3000);
                if (data.success) azureLoadConfig(); // re-load to show masked secrets
            })
            .catch(() => { if (msg) msg.textContent = '❌ Network error'; });
    };

    // ── Toggle a service on/off and auto-save ─────────────────────────────────

    window.azureToggleService = function (service, enabled) {
        const payload = {};
        payload[service + '_enabled'] = enabled;
        fetch('/api/azure/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken() },
            body: JSON.stringify(payload),
        }).catch(err => console.error('[Azure] toggle error:', err));
    };

    // ── Reset a single usage counter ──────────────────────────────────────────

    window.azureResetCounter = function (service) {
        fetch('/api/azure/reset_counter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken() },
            body: JSON.stringify({ service }),
        })
            .then(r => r.json())
            .then(data => { if (data.success) azureLoadUsage(); })
            .catch(err => console.error('[Azure] reset error:', err));
    };

    // ── Helpers ───────────────────────────────────────────────────────────────

    function _getVal(id)  { const el = document.getElementById(id); return el ? el.value.trim() : ''; }
    function _setVal(id, v) { const el = document.getElementById(id); if (el && v) el.value = v; }
    function _getCheck(id) { const el = document.getElementById(id); return el ? el.checked : false; }
    function _setCheck(id, v) { const el = document.getElementById(id); if (el) el.checked = !!v; }
    function _getSelect(id) { const el = document.getElementById(id); return el ? el.value : ''; }
    function _setSelect(id, v) { const el = document.getElementById(id); if (el && v) el.value = v; }

    function _csrfToken() {
        const el = document.querySelector('meta[name="csrf-token"]') || document.getElementById('csrf-token');
        return el ? (el.content || el.value || '') : '';
    }

    function _fmtBytes(b) {
        if (b < 1024) return b + ' B';
        if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
        if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
        return (b / 1073741824).toFixed(2) + ' GB';
    }

})();
