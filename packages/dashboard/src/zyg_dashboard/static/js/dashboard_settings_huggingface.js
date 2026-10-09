// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── HuggingFace settings tab ─────────────────────────────────────────────── */

(function () {
    'use strict';

    // ── Navigation ────────────────────────────────────────────────────────────

    window.showSettingsHuggingFaceView = function () {
        var secBtns = document.getElementById('dashboard-settings-security-buttons');
        var panel   = document.getElementById('dashboard-settings-huggingface');
        if (secBtns) secBtns.style.display = 'none';
        if (panel)   { panel.style.display = 'block'; _hfLoad(); }
    };

    function _backToSecurity() {
        var secBtns = document.getElementById('dashboard-settings-security-buttons');
        var panel   = document.getElementById('dashboard-settings-huggingface');
        if (panel)   panel.style.display = 'none';
        if (secBtns) secBtns.style.display = '';
    }

    // ── Bootstrap ─────────────────────────────────────────────────────────────

    function _init() {
        var backBtn = document.getElementById('dashboard-settings-huggingface-back');
        var openBtn = document.getElementById('dashboard-settings-huggingface-btn');
        var saveBtn = document.getElementById('hf-token-save');
        var testBtn = document.getElementById('hf-token-test');

        if (backBtn) backBtn.addEventListener('click', _backToSecurity);
        if (openBtn) openBtn.addEventListener('click', window.showSettingsHuggingFaceView);
        if (saveBtn) saveBtn.addEventListener('click', _hfSave);
        if (testBtn) testBtn.addEventListener('click', _hfTest);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _init);
    } else {
        _init();
    }

    // ── Load current status ───────────────────────────────────────────────────

    function _hfLoad() {
        var dot  = document.getElementById('hf-status-dot');
        var text = document.getElementById('hf-status-text');
        var inp  = document.getElementById('hf-token-input');
        if (text) text.textContent = 'Checking…';

        fetch('/api/settings/huggingface')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.set) {
                    if (dot)  { dot.style.background  = '#22c55e'; }
                    if (text) { text.textContent = 'Token set — ' + d.masked; }
                    if (inp)  { inp.placeholder   = d.masked; }
                } else {
                    if (dot)  { dot.style.background  = '#ef4444'; }
                    if (text) { text.textContent = 'No token set — pipelines will skip IPAdapter and gated model downloads.'; }
                }
            })
            .catch(function(err) {
                if (text) text.textContent = 'Could not load status: ' + err;
            });
    }

    // ── Save token ────────────────────────────────────────────────────────────

    function _hfSave() {
        var inp  = document.getElementById('hf-token-input');
        var msg  = document.getElementById('hf-token-msg');
        var token = inp ? inp.value.trim() : '';
        if (!token) { _setMsg(msg, 'Please enter a token.', 'error'); return; }
        _setMsg(msg, 'Saving…', 'info');
        _post('/api/settings/huggingface', { token: token })
            .then(function(d) {
                if (d.success) {
                    _setMsg(msg, '✓ ' + (d.message || 'Saved.'), 'ok');
                    if (inp) inp.value = '';
                    _hfLoad();
                } else {
                    _setMsg(msg, '✗ ' + (d.error || 'Save failed.'), 'error');
                }
            })
            .catch(function(e) { _setMsg(msg, '✗ ' + e, 'error'); });
    }

    // ── Test token ────────────────────────────────────────────────────────────

    function _hfTest() {
        var msg = document.getElementById('hf-token-msg');
        var dot = document.getElementById('hf-status-dot');
        var txt = document.getElementById('hf-status-text');
        _setMsg(msg, 'Testing connection…', 'info');
        _post('/api/settings/huggingface/test', {})
            .then(function(d) {
                if (d.success) {
                    _setMsg(msg, '✓ ' + d.message, 'ok');
                    if (dot) dot.style.background = '#22c55e';
                    if (txt) txt.textContent = 'Connected as: ' + d.username;
                } else {
                    _setMsg(msg, '✗ ' + (d.error || 'Test failed.'), 'error');
                    if (dot) dot.style.background = '#ef4444';
                }
            })
            .catch(function(e) { _setMsg(msg, '✗ ' + e, 'error'); });
    }

    // ── Download model weights ────────────────────────────────────────────────

    window.hfDownload = function(btn) {
        var repo = btn.getAttribute('data-hf-repo');
        var file = btn.getAttribute('data-hf-file');
        var msg  = document.getElementById('hf-token-msg');
        var orig = btn.textContent;
        btn.textContent = 'Starting…';
        btn.disabled = true;
        _post('/api/settings/huggingface/download', { repo: repo, filename: file })
            .then(function(d) {
                if (d.success) {
                    _setMsg(msg, '⬇ ' + (d.message || 'Download started in background.'), 'ok');
                    btn.textContent = 'Queued ✓';
                } else {
                    _setMsg(msg, '✗ ' + (d.error || 'Download failed.'), 'error');
                    btn.textContent = orig;
                    btn.disabled = false;
                }
            })
            .catch(function(e) {
                _setMsg(msg, '✗ ' + e, 'error');
                btn.textContent = orig;
                btn.disabled = false;
            });
    };

    // ── Helpers ───────────────────────────────────────────────────────────────

    function _post(url, body) {
        var csrf = (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || '';
        return fetch(url, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body:    JSON.stringify(body),
        }).then(function(r) { return r.json(); });
    }

    function _setMsg(el, text, type) {
        if (!el) return;
        el.textContent = text;
        el.style.color = type === 'ok' ? '#22c55e' : type === 'error' ? '#ef4444' : '#888';
    }

}());
