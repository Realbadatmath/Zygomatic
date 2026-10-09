// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── Control Settings tab (Settings > Security > Control Settings) ──────────
   Master catalogue of guardrails / quality gates / parameters / policy rules
   across Medusa, Creator Nexus, port 5000, and all workflows. Gated by its
   own password (separate from the dashboard login), username fixed to
   "Zygomatic". Added 2026-08-05. */
(function () {
    'use strict';

    const CATS = ['guardrails', 'quality_gates', 'parameters', 'policy_rules'];
    let activeCat = 'guardrails';
    let dataByCat = { guardrails: [], quality_gates: [], parameters: [], policy_rules: [] };
    let dirty = false;

    // ── Navigation ────────────────────────────────────────────────────────────

    window.showSettingsControlSettingsView = function () {
        const securityView = document.getElementById('dashboard-settings-security');
        const panel = document.getElementById('dashboard-settings-control-settings');
        if (securityView) securityView.style.display = 'none';
        if (panel) panel.style.display = 'block';
        csRefreshStatus();
    };

    function _backToSecurity() {
        if (dirty && !confirm('You have unsaved changes to this list. Leave anyway?')) return;
        const secBtns = document.getElementById('dashboard-settings-security-buttons');
        const panel = document.getElementById('dashboard-settings-control-settings');
        if (panel) panel.style.display = 'none';
        if (secBtns) secBtns.style.display = '';
    }

    function _init() {
        const backBtn = document.getElementById('dashboard-settings-control-settings-back');
        if (backBtn) backBtn.addEventListener('click', _backToSecurity);

        const setupBtn = document.getElementById('cs-setup-submit');
        if (setupBtn) setupBtn.addEventListener('click', csSubmitSetup);
        const unlockBtn = document.getElementById('cs-unlock-submit');
        if (unlockBtn) unlockBtn.addEventListener('click', csSubmitUnlock);
        const lockBtn = document.getElementById('cs-lock-btn');
        if (lockBtn) lockBtn.addEventListener('click', csLock);

        ['cs-setup-password', 'cs-setup-confirm'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') csSubmitSetup(); });
        });
        const unlockPw = document.getElementById('cs-unlock-password');
        if (unlockPw) unlockPw.addEventListener('keydown', e => { if (e.key === 'Enter') csSubmitUnlock(); });

        document.querySelectorAll('.cs-subtab').forEach(btn => {
            btn.addEventListener('click', () => {
                if (dirty && !confirm('You have unsaved changes to this list. Switch tabs anyway?')) return;
                document.querySelectorAll('.cs-subtab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                activeCat = btn.getAttribute('data-cat');
                dirty = false;
                csRenderTable();
            });
        });

        const search = document.getElementById('cs-search');
        if (search) search.addEventListener('input', csRenderTable);
        const progFilter = document.getElementById('cs-program-filter');
        if (progFilter) progFilter.addEventListener('change', csRenderTable);

        const addBtn = document.getElementById('cs-add-row-btn');
        if (addBtn) addBtn.addEventListener('click', csAddRow);
        const saveBtn = document.getElementById('cs-save-btn');
        if (saveBtn) saveBtn.addEventListener('click', csSaveActive);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _init);
    } else {
        _init();
    }

    // ── Gate: status / setup / unlock / lock ────────────────────────────────────

    function csRefreshStatus() {
        fetch('/api/control-settings/status')
            .then(r => r.json())
            .then(data => {
                const setupBox = document.getElementById('cs-gate-setup');
                const unlockBox = document.getElementById('cs-gate-unlock');
                const content = document.getElementById('cs-content');
                if (!data.success) {
                    if (setupBox) setupBox.style.display = 'none';
                    if (unlockBox) unlockBox.style.display = 'none';
                    if (content) content.style.display = 'none';
                    return;
                }
                if (data.unlocked) {
                    if (setupBox) setupBox.style.display = 'none';
                    if (unlockBox) unlockBox.style.display = 'none';
                    if (content) content.style.display = 'block';
                    csLoadAll();
                } else if (data.configured) {
                    if (setupBox) setupBox.style.display = 'none';
                    if (unlockBox) unlockBox.style.display = 'block';
                    if (content) content.style.display = 'none';
                } else {
                    if (setupBox) setupBox.style.display = 'block';
                    if (unlockBox) unlockBox.style.display = 'none';
                    if (content) content.style.display = 'none';
                }
            })
            .catch(() => {});
    }

    function csSubmitSetup() {
        const pw = document.getElementById('cs-setup-password').value;
        const confirm_ = document.getElementById('cs-setup-confirm').value;
        const msg = document.getElementById('cs-setup-msg');
        if (pw.length < 10) { msg.textContent = 'Password must be at least 10 characters.'; return; }
        if (pw !== confirm_) { msg.textContent = 'Password and confirmation do not match — please re-enter both.'; return; }
        msg.style.color = '#666';
        msg.textContent = 'Creating…';
        fetch('/api/control-settings/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken() },
            body: JSON.stringify({ password: pw, confirm_password: confirm_ }),
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) { msg.style.color = '#b91c1c'; msg.textContent = data.message || 'Setup failed.'; return; }
                document.getElementById('cs-setup-password').value = '';
                document.getElementById('cs-setup-confirm').value = '';
                csRefreshStatus();
            })
            .catch(() => { msg.style.color = '#b91c1c'; msg.textContent = 'Request failed.'; });
    }

    function csSubmitUnlock() {
        const pw = document.getElementById('cs-unlock-password').value;
        const msg = document.getElementById('cs-unlock-msg');
        msg.style.color = '#666';
        msg.textContent = 'Checking…';
        fetch('/api/control-settings/unlock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken() },
            body: JSON.stringify({ password: pw }),
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) { msg.style.color = '#b91c1c'; msg.textContent = data.message || 'Incorrect password.'; return; }
                document.getElementById('cs-unlock-password').value = '';
                msg.textContent = '';
                csRefreshStatus();
            })
            .catch(() => { msg.style.color = '#b91c1c'; msg.textContent = 'Request failed.'; });
    }

    function csLock() {
        if (dirty && !confirm('You have unsaved changes to this list. Lock anyway?')) return;
        fetch('/api/control-settings/lock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken() },
            body: '{}',
        })
            .then(() => { dirty = false; csRefreshStatus(); })
            .catch(() => {});
    }

    // ── Data load / render ───────────────────────────────────────────────────

    function csLoadAll() {
        fetch('/api/control-settings/data')
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                dataByCat = data.data;
                dirty = false;
                csRenderTable();
            })
            .catch(() => {});
    }

    const PROGRAM_LABEL = { medusa: 'Medusa', creator_nexus: 'Creator Nexus', port5000: 'Port 5000', workflows: 'Workflows' };
    const ACTIVATED_COLOR = { yes: '#065f46', no: '#991b1b', conditional: '#92400e' };
    const ACTIVATED_BG = { yes: '#d1fae5', no: '#fee2e2', conditional: '#fff3cd' };

    function csRenderTable() {
        const tbody = document.getElementById('cs-tbody');
        if (!tbody) return;
        const items = dataByCat[activeCat] || [];
        const q = (document.getElementById('cs-search').value || '').toLowerCase().trim();
        const prog = document.getElementById('cs-program-filter').value;
        const filtered = items.filter(it => {
            if (prog && it.program !== prog) return false;
            if (!q) return true;
            const hay = ((it.name || '') + ' ' + (it.function || '') + ' ' + (it.location || '') + ' ' + (it.id || '')).toLowerCase();
            return hay.indexOf(q) !== -1;
        });
        document.getElementById('cs-count').textContent = filtered.length + ' / ' + items.length + ' entries';

        if (!filtered.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="padding:20px;color:#999;text-align:center;">No entries match.</td></tr>';
            return;
        }

        tbody.innerHTML = '';
        filtered.forEach(it => {
            const idx = items.indexOf(it);
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #e5e7eb';

            const tdId = document.createElement('td');
            tdId.style.cssText = 'padding:6px 8px;font-family:monospace;font-size:0.82rem;color:#555;';
            tdId.textContent = it.id || '';
            tr.appendChild(tdId);

            const tdProg = document.createElement('td');
            tdProg.style.cssText = 'padding:6px 8px;';
            const progSel = document.createElement('select');
            progSel.className = 'dashboard-settings-input cs-field';
            progSel.style.cssText = 'padding:4px;font-size:0.82rem;width:100%;';
            Object.keys(PROGRAM_LABEL).forEach(p => {
                const opt = document.createElement('option');
                opt.value = p; opt.textContent = PROGRAM_LABEL[p];
                if (it.program === p) opt.selected = true;
                progSel.appendChild(opt);
            });
            progSel.addEventListener('change', () => { items[idx].program = progSel.value; dirty = true; csFlagDirty(); });
            tdProg.appendChild(progSel);
            tr.appendChild(tdProg);

            tr.appendChild(_editableCell(items, idx, 'name', '220px'));
            tr.appendChild(_editableCell(items, idx, 'function', '340px', true));

            const tdAct = document.createElement('td');
            tdAct.style.cssText = 'padding:6px 8px;';
            const actSel = document.createElement('select');
            actSel.className = 'dashboard-settings-input cs-field';
            actSel.style.cssText = 'padding:4px;font-size:0.82rem;width:100%;font-weight:600;color:' + (ACTIVATED_COLOR[it.activated] || '#333') + ';background:' + (ACTIVATED_BG[it.activated] || '#fff') + ';border-radius:6px;';
            ['yes', 'no', 'conditional'].forEach(v => {
                const opt = document.createElement('option');
                opt.value = v; opt.textContent = v.charAt(0).toUpperCase() + v.slice(1);
                if (it.activated === v) opt.selected = true;
                actSel.appendChild(opt);
            });
            actSel.addEventListener('change', () => {
                items[idx].activated = actSel.value;
                actSel.style.color = ACTIVATED_COLOR[actSel.value] || '#333';
                actSel.style.background = ACTIVATED_BG[actSel.value] || '#fff';
                dirty = true; csFlagDirty();
            });
            tdAct.appendChild(actSel);
            if (it.activation_note) {
                const note = document.createElement('div');
                note.style.cssText = 'font-size:0.72rem;color:#888;margin-top:3px;';
                note.textContent = it.activation_note;
                tdAct.appendChild(note);
            }
            tr.appendChild(tdAct);

            tr.appendChild(_editableCell(items, idx, 'location', '200px'));

            const tdDel = document.createElement('td');
            tdDel.style.cssText = 'padding:6px 8px;text-align:center;';
            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.title = 'Remove entry';
            delBtn.textContent = '✕';
            delBtn.style.cssText = 'background:none;border:none;color:#991b1b;cursor:pointer;font-size:1rem;';
            delBtn.addEventListener('click', () => {
                if (!confirm('Remove "' + (it.name || it.id) + '" from this list?')) return;
                const realIdx = items.indexOf(it);
                if (realIdx !== -1) items.splice(realIdx, 1);
                dirty = true; csFlagDirty();
                csRenderTable();
            });
            tdDel.appendChild(delBtn);
            tr.appendChild(tdDel);

            tbody.appendChild(tr);
        });
    }

    function _editableCell(items, idx, field, minWidth, multiline) {
        const td = document.createElement('td');
        td.style.cssText = 'padding:6px 8px;';
        const input = document.createElement(multiline ? 'textarea' : 'input');
        if (!multiline) input.type = 'text';
        else { input.rows = 2; }
        input.className = 'dashboard-settings-input cs-field';
        input.style.cssText = 'padding:4px;font-size:0.82rem;width:100%;min-width:' + minWidth + ';resize:vertical;';
        input.value = items[idx][field] || '';
        input.addEventListener('input', () => { items[idx][field] = input.value; dirty = true; csFlagDirty(); });
        td.appendChild(input);
        return td;
    }

    function csFlagDirty() {
        const msg = document.getElementById('cs-save-msg');
        if (msg) { msg.style.color = '#92400e'; msg.textContent = 'Unsaved changes'; }
    }

    function csAddRow() {
        const items = dataByCat[activeCat] || (dataByCat[activeCat] = []);
        items.push({ id: '', program: 'workflows', name: '', function: '', activated: 'no', location: '' });
        dirty = true;
        csFlagDirty();
        csRenderTable();
        const search = document.getElementById('cs-search');
        if (search) search.value = '';
        const progFilter = document.getElementById('cs-program-filter');
        if (progFilter) progFilter.value = '';
    }

    function csSaveActive() {
        const msg = document.getElementById('cs-save-msg');
        msg.style.color = '#666';
        msg.textContent = 'Saving…';
        fetch('/api/control-settings/data/' + encodeURIComponent(activeCat), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfToken() },
            body: JSON.stringify({ items: dataByCat[activeCat] || [] }),
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) { msg.style.color = '#b91c1c'; msg.textContent = data.message || 'Save failed.'; return; }
                dataByCat[activeCat] = data.items;
                dirty = false;
                msg.style.color = '#065f46';
                msg.textContent = 'Saved.';
                csRenderTable();
            })
            .catch(() => { msg.style.color = '#b91c1c'; msg.textContent = 'Request failed.'; });
    }

    function _csrfToken() {
        const el = document.querySelector('meta[name="csrf-token"]') || document.getElementById('csrf-token');
        return el ? (el.content || el.value || '') : '';
    }
})();
