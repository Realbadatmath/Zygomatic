// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Voices Settings — top table: voice library with Play; bottom table: channel/dept assignments.
 */
(function () {
    'use strict';

    var PREVIEW_TEXT = 'Alignment is not mixing guava with petrol and expecting gravy.';

    // Map voice locale prefix → ethnicity label
    var LOCALE_ETHNICITY = {
        'en-US': 'American',
        'en-GB': 'British',
        'en-AU': 'Australian',
        'en-IE': 'Irish',
        'en-CA': 'Canadian',
        'en-NZ': 'New Zealand',
        'en-IN': 'Indian'
    };

    function getEthnicity(voiceId) {
        if (!voiceId) return '—';
        var parts = voiceId.split('-');
        var locale = parts.slice(0, 2).join('-');
        return LOCALE_ETHNICITY[locale] || locale;
    }

    // ── State ──────────────────────────────────────────────────────────────────
    var _voiceLibrary = [];         // [{profile_id, label, gender, age_group, style, voice, rate, pitch, description}]
    var _assignments = {};          // {channel_id: {channel_name, profile_id, ...}}
    var _clipfarmChannels = [];     // [{channel_id, name, platform, ...}]
    var _currentChannelId = null;   // which channel row the modal is open for
    var _currentAudio = null;       // currently playing Audio element
    var _loadingPlay = null;        // profile_id currently being loaded for play

    // ── DOM helpers ────────────────────────────────────────────────────────────
    function byId(id) { return document.getElementById(id); }

    function getCsrfToken() {
        var m = document.getElementById('csrf-token');
        if (m) return m.value || m.getAttribute('data-csrf') || '';
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content') || '';
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var c = cookies[i].trim();
            if (c.startsWith('csrf_token=')) return decodeURIComponent(c.slice(11));
        }
        return '';
    }

    function jsonPost(url, body, cb) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        var csrf = getCsrfToken();
        if (csrf) xhr.setRequestHeader('X-CSRFToken', csrf);
        xhr.onload = function () {
            try { cb(null, JSON.parse(xhr.responseText)); }
            catch (e) { cb(e, null); }
        };
        xhr.onerror = function () { cb(new Error('Network error'), null); };
        xhr.send(JSON.stringify(body));
    }

    // ── Voice Library Table ────────────────────────────────────────────────────
    function renderVoiceLibrary() {
        var tbody = byId('voices-library-tbody');
        if (!tbody) return;
        if (!_voiceLibrary.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#888;">No voices loaded.</td></tr>';
            return;
        }
        var rows = _voiceLibrary.map(function (v) {
            var ethnicity = getEthnicity(v.voice || '');
            return '<tr>' +
                '<td><strong>' + esc(v.label || v.profile_id) + '</strong></td>' +
                '<td>' + esc(capFirst(v.gender || '')) + '</td>' +
                '<td>' + esc(capFirst(v.age_group || '')) + '</td>' +
                '<td>' + esc(capFirst(v.style || '')) + '</td>' +
                '<td>' + esc(v.engine || 'indextts2') + '</td>' +
                '<td style="max-width:200px;font-size:0.78rem;color:#555;">' + esc(v.description || '') + '</td>' +
                '<td style="text-align:center;">' +
                  '<button type="button" class="btn dashboard-btn" style="padding:3px 10px;font-size:0.78rem;" ' +
                  'data-voices-play="' + esc(v.profile_id) + '" aria-label="Preview ' + esc(v.label || v.profile_id) + '">▶ Play</button>' +
                '</td>' +
                '</tr>';
        });
        tbody.innerHTML = rows.join('');
    }

    // ── Channel Assignments Table ──────────────────────────────────────────────
    function renderChannelTable() {
        var tbody = byId('voices-channel-tbody');
        if (!tbody) return;

        // Build unified list: departments first (__xxx__ keys), then YouTube channels
        var rows = [];

        // Departments (keys starting with __)
        Object.keys(_assignments).forEach(function (key) {
            if (key.startsWith('__')) {
                rows.push({ id: key, name: _assignments[key].channel_name || key, isDept: true });
            }
        });

        // Clipfarm channels
        _clipfarmChannels.forEach(function (ch) {
            rows.push({ id: ch.channel_id, name: ch.name || ch.channel_id, isDept: false });
        });

        // Also include any assigned channels not in clipfarm list
        Object.keys(_assignments).forEach(function (key) {
            if (!key.startsWith('__')) {
                var already = _clipfarmChannels.some(function (c) { return c.channel_id === key; });
                if (!already) {
                    rows.push({ id: key, name: _assignments[key].channel_name || key, isDept: false });
                }
            }
        });

        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#888;">No channels configured.</td></tr>';
            return;
        }

        var html = rows.map(function (row) {
            var assign = _assignments[row.id];
            var profileId = assign ? assign.profile_id : null;
            var voice = profileId ? _voiceLibrary.find(function (v) { return v.profile_id === profileId; }) : null;
            var voiceLabel = voice ? voice.label : (profileId || '<em style="color:#aaa;">Not assigned</em>');
            var gender    = voice ? capFirst(voice.gender || '') : '—';
            var speed     = voice ? (voice.rate || '—') : '—';
            var pitch     = voice ? (voice.pitch || '—') : '—';
            var age       = voice ? capFirst(voice.age_group || '') : '—';
            var ethnicity = voice ? getEthnicity(voice.voice || '') : '—';
            var badge = row.isDept
                ? '<span style="font-size:0.7rem;background:#e6f0ff;color:#2255aa;border-radius:4px;padding:1px 6px;margin-left:6px;">dept</span>'
                : '';
            return '<tr style="cursor:pointer;" data-voices-channel-id="' + esc(row.id) + '" data-voices-channel-name="' + esc(row.name) + '">' +
                '<td><span style="font-weight:600;">' + esc(row.name) + '</span>' + badge + '</td>' +
                '<td>' + voiceLabel + '</td>' +
                '<td>' + gender + '</td>' +
                '<td>' + speed + '</td>' +
                '<td>' + pitch + '</td>' +
                '<td>' + age + '</td>' +
                '<td>' + ethnicity + '</td>' +
                '</tr>';
        });
        tbody.innerHTML = html.join('');
    }

    // ── Play Button ────────────────────────────────────────────────────────────
    function playVoice(profileId, btnEl) {
        if (_loadingPlay === profileId) return;
        if (_currentAudio) { _currentAudio.pause(); _currentAudio = null; }

        // Reset all play buttons
        document.querySelectorAll('[data-voices-play]').forEach(function (b) {
            b.textContent = '▶ Play';
            b.disabled = false;
        });

        if (btnEl) { btnEl.textContent = '⏳'; btnEl.disabled = true; }
        _loadingPlay = profileId;

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/voices/play', true);
        xhr.withCredentials = true;
        xhr.setRequestHeader('Content-Type', 'application/json');
        var csrf = getCsrfToken();
        if (csrf) xhr.setRequestHeader('X-CSRFToken', csrf);
        xhr.responseType = 'blob';
        xhr.onload = function () {
            _loadingPlay = null;
            if (btnEl) { btnEl.disabled = false; }
            if (xhr.status !== 200) {
                if (btnEl) btnEl.textContent = '✗ Err';
                return;
            }
            var blob = xhr.response;
            var url = URL.createObjectURL(blob);
            var audio = new Audio(url);
            _currentAudio = audio;
            if (btnEl) btnEl.textContent = '⏸ Stop';
            audio.onended = function () {
                URL.revokeObjectURL(url);
                _currentAudio = null;
                if (btnEl) btnEl.textContent = '▶ Play';
            };
            audio.onerror = function () {
                URL.revokeObjectURL(url);
                _currentAudio = null;
                if (btnEl) btnEl.textContent = '✗ Err';
            };
            audio.play();
            // Clicking again while playing → stop
            if (btnEl) {
                btnEl._stopFn = function () {
                    audio.pause();
                    URL.revokeObjectURL(url);
                    _currentAudio = null;
                    btnEl.textContent = '▶ Play';
                    btnEl._stopFn = null;
                };
            }
        };
        xhr.onerror = function () {
            _loadingPlay = null;
            if (btnEl) { btnEl.textContent = '✗ Err'; btnEl.disabled = false; }
        };
        xhr.send(JSON.stringify({ profile_id: profileId }));
    }

    // ── Voice Assignment Modal ─────────────────────────────────────────────────
    function openAssignModal(channelId, channelName) {
        _currentChannelId = channelId;
        var modal = byId('voice-assign-modal');
        var title = byId('voice-modal-title');
        var list = byId('voice-modal-list');
        if (!modal || !list) return;

        if (title) title.textContent = 'Select Voice for: ' + channelName;

        var currentAssign = _assignments[channelId];
        var currentProfileId = currentAssign ? currentAssign.profile_id : null;

        var html = _voiceLibrary.map(function (v) {
            var ethnicity = getEthnicity(v.voice || '');
            var isActive = v.profile_id === currentProfileId;
            var activeCls = isActive ? 'style="background:#e8f4e8;border-color:#4caf50;"' : '';
            var check = isActive ? '<span style="color:#4caf50;font-weight:700;margin-right:6px;">✓</span>' : '';
            return '<div class="voice-modal-option" data-profile-id="' + esc(v.profile_id) + '" ' + activeCls +
                ' style="display:flex;align-items:center;padding:8px 12px;border:1px solid #ddd;border-radius:6px;cursor:pointer;gap:8px;">' +
                check +
                '<div style="flex:1;">' +
                  '<div style="font-weight:600;font-size:0.9rem;">' + esc(v.label || v.profile_id) + '</div>' +
                  '<div style="font-size:0.75rem;color:#666;">' +
                    capFirst(v.gender || '') + ' · ' + capFirst(v.age_group || '') + ' · ' + capFirst(v.style || '') + ' · ' + ethnicity +
                  '</div>' +
                  '<div style="font-size:0.73rem;color:#888;">' + esc(v.description || '') + '</div>' +
                '</div>' +
                '<button type="button" class="btn dashboard-btn" style="padding:2px 8px;font-size:0.75rem;" ' +
                  'data-modal-play="' + esc(v.profile_id) + '" aria-label="Preview ' + esc(v.label || v.profile_id) + '">▶</button>' +
                '</div>';
        });
        list.innerHTML = html.join('');

        modal.style.display = 'flex';
    }

    function closeAssignModal() {
        var modal = byId('voice-assign-modal');
        if (modal) modal.style.display = 'none';
        _currentChannelId = null;
        if (_currentAudio) { _currentAudio.pause(); _currentAudio = null; }
    }

    function assignVoice(channelId, profileId, channelName) {
        jsonPost('/api/voices/assign', { channel_id: channelId, profile_id: profileId, channel_name: channelName }, function (err, res) {
            if (err || !res || !res.success) {
                alert('Failed to save voice assignment. Please try again.');
                return;
            }
            // Update local state
            _assignments[channelId] = _assignments[channelId] || {};
            _assignments[channelId].channel_name = channelName;
            _assignments[channelId].profile_id = profileId;
            renderChannelTable();
            closeAssignModal();
        });
    }

    // ── Event Delegation ───────────────────────────────────────────────────────
    function onVoicesViewClick(e) {
        var target = e.target;

        // Play button in top table
        var playEl = target.closest('[data-voices-play]');
        if (playEl) {
            var profileId = playEl.getAttribute('data-voices-play');
            if (_currentAudio && playEl._stopFn) {
                playEl._stopFn();
                return;
            }
            playVoice(profileId, playEl);
            return;
        }

        // Play button inside assign modal
        var modalPlayEl = target.closest('[data-modal-play]');
        if (modalPlayEl) {
            e.stopPropagation();
            var mpId = modalPlayEl.getAttribute('data-modal-play');
            playVoice(mpId, modalPlayEl);
            return;
        }

        // Clicking a voice option in the modal (not its play button)
        var optionEl = target.closest('.voice-modal-option');
        if (optionEl && !target.closest('[data-modal-play]')) {
            var selProfileId = optionEl.getAttribute('data-profile-id');
            var chId = _currentChannelId;
            var chAssign = _assignments[chId];
            var chName = chAssign ? chAssign.channel_name : '';
            // Also try to get name from table row
            if (!chName) {
                var chRow = document.querySelector('[data-voices-channel-id="' + chId + '"]');
                if (chRow) chName = chRow.getAttribute('data-voices-channel-name') || '';
            }
            assignVoice(chId, selProfileId, chName);
            return;
        }

        // Channel row in bottom table
        var chRowEl = target.closest('[data-voices-channel-id]');
        if (chRowEl && !byId('voice-assign-modal').contains(target)) {
            openAssignModal(
                chRowEl.getAttribute('data-voices-channel-id'),
                chRowEl.getAttribute('data-voices-channel-name') || ''
            );
            return;
        }

        // Modal close button / backdrop
        if (target.id === 'voice-modal-close' || target.id === 'voice-assign-modal') {
            closeAssignModal();
        }
    }

    // ── Load & Render ──────────────────────────────────────────────────────────
    function load() {
        // Load voice library
        var xhr1 = new XMLHttpRequest();
        xhr1.open('GET', '/api/voices', true);
        xhr1.withCredentials = true;
        xhr1.onload = function () {
            try {
                var d = JSON.parse(xhr1.responseText);
                _voiceLibrary = d.voices || [];
            } catch (e) { _voiceLibrary = []; }
            renderVoiceLibrary();
        };
        xhr1.onerror = function () { _voiceLibrary = []; renderVoiceLibrary(); };
        xhr1.send();

        // Load channel assignments
        var xhr2 = new XMLHttpRequest();
        xhr2.open('GET', '/api/voices/channel-assignments', true);
        xhr2.withCredentials = true;
        xhr2.onload = function () {
            try {
                var d = JSON.parse(xhr2.responseText);
                _assignments = d.assignments || {};
                _clipfarmChannels = d.channels || [];
            } catch (e) { _assignments = {}; _clipfarmChannels = []; }
            renderChannelTable();
        };
        xhr2.onerror = function () { _assignments = {}; _clipfarmChannels = []; renderChannelTable(); };
        xhr2.send();
    }

    // ── Open / Init ────────────────────────────────────────────────────────────
    function openVoices() {
        load();

        var voicesView = byId('dashboard-settings-voices');
        if (!voicesView) return;

        // Attach event listener once
        if (!voicesView._voicesListenerBound) {
            voicesView._voicesListenerBound = true;
            voicesView.addEventListener('click', onVoicesViewClick);
        }
    }

    // ── Show / Hide panel (matches showSettingsStylesView pattern in dashboard_tabs.js) ──
    function showSettingsVoicesView() {
        var main = byId('dashboard-settings-main');
        var voicesView = byId('dashboard-settings-voices');
        if (!voicesView) return;
        if (main) main.style.setProperty('display', 'none', 'important');
        voicesView.style.display = '';
        openVoices();
    }

    function showSettingsVoicesBack() {
        var main = byId('dashboard-settings-main');
        var voicesView = byId('dashboard-settings-voices');
        if (voicesView) voicesView.style.display = 'none';
        if (main) main.style.display = 'flex';
        closeAssignModal();
    }

    // Wire back button as soon as DOM is ready
    function _wireBackBtn() {
        var backBtn = byId('dashboard-settings-voices-back');
        if (backBtn && !backBtn._voicesBackBound) {
            backBtn._voicesBackBound = true;
            backBtn.addEventListener('click', showSettingsVoicesBack);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _wireBackBtn);
    } else {
        _wireBackBtn();
    }

    // ── Utilities ──────────────────────────────────────────────────────────────
    function esc(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function capFirst(s) {
        if (!s) return '';
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    // ── Export ─────────────────────────────────────────────────────────────────
    window.DashboardSettingsVoices = { openVoices: openVoices };
    window.showSettingsVoicesView  = showSettingsVoicesView;
}());
