// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* dashboard_tab_asset_manager_rfd.js — RFD, Sources, Documents, Voices */
(function() {
'use strict';

// ─── RFD ─────────────────────────────────────────────────────────────────────
function loadRFD() {
    var tbody = document.getElementById('rfd-tbody');
    var countEl = document.getElementById('rfd-count');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#888;">Loading…</td></tr>';
    fetch('/api/rfd/clips', { credentials: 'same-origin' })
        .then(function(r){ return r.json(); })
        .then(function(data) {
            var clips = data.clips || [];
            if (countEl) countEl.textContent = clips.length + ' clip' + (clips.length!==1?'s':'') + ' ready';
            if (!clips.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:32px;color:#888;">No clips ready for deployment yet.</td></tr>';
                return;
            }
            tbody.innerHTML = '';
            clips.forEach(function(clip) {
                var tr = document.createElement('tr');
                tr.style.cursor = 'pointer';
                var created = clip.created ? clip.created.replace('T',' ').substring(0,16) : '—';
                tr.innerHTML =
                    '<td style="font-weight:500;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="'+escHtml(clip.title)+'">'+escHtml(clip.title)+'</td>' +
                    '<td>'+escHtml(clip.channel||'—')+'</td>' +
                    '<td><span style="background:#e8f0fe;color:#1a56db;border-radius:4px;padding:2px 7px;font-size:0.78rem;">'+escHtml(clip.category||'—')+'</span></td>' +
                    '<td>'+(clip.runtime_min?clip.runtime_min+' min':'—')+'</td>' +
                    '<td>'+(clip.size_mb?clip.size_mb+' MB':'—')+'</td>' +
                    '<td>'+created+'</td>' +
                    '<td><button type="button" class="btn dashboard-btn" style="padding:3px 10px;font-size:0.78rem;" data-clip-id="'+escHtml(clip.clip_id)+'">Details</button></td>';
                tr.addEventListener('click', function(e) {
                    if (e.target.tagName !== 'BUTTON') showRFDDetail(clip);
                });
                tr.querySelector('button').addEventListener('click', function(e) {
                    e.stopPropagation(); showRFDDetail(clip);
                });
                tbody.appendChild(tr);
            });
            window._rfdClips = clips;
        })
        .catch(function(e) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#c00;">Error loading clips: '+e+'</td></tr>';
        });
}

function showRFDDetail(clip) {
    var dialog = document.getElementById('rfd-detail-dialog');
    var title = document.getElementById('rfd-dialog-title');
    var tbody = document.getElementById('rfd-dialog-tbody');
    if (!dialog) return;
    title.textContent = clip.title || clip.filename;
    var rows = [
        ['Created', clip.created ? clip.created.replace('T',' ').substring(0,19) : '—'],
        ['Department', clip.department || 'Clipfarm'],
        ['Channel', clip.channel || '—'],
        ['Category', clip.category || '—'],
        ['File Size', clip.size_mb ? clip.size_mb + ' MB' : '—'],
        ['Runtime (est.)', clip.runtime_min ? clip.runtime_min + ' min' : '—'],
        ['Pipeline Run ID', clip.pipeline_id || '—'],
        ['Pipeline Started', clip.pipeline_started ? clip.pipeline_started.replace('T',' ').substring(0,19) : '—'],
        ['Source Video ID', clip.video_id || '—'],
        ['Source URL', clip.source_url ? '<a href="'+escHtml(clip.source_url)+'" target="_blank" style="color:#1a56db;">'+escHtml(clip.source_url)+'</a>' : '—'],
        ['Source Timestamp', clip.source_ts ? clip.source_ts + 's' : '—'],
        ['Flags / Errors', clip.flags && clip.flags.length ? '<span style="color:#c00;">'+escHtml(clip.flags.join('; '))+'</span>' : '<span style="color:#1a6b3a;">None</span>'],
        ['Status', '<span style="background:#dcfce7;color:#1a6b3a;border-radius:4px;padding:2px 8px;font-size:0.8rem;font-weight:600;">✔ Ready</span>'],
    ];
    tbody.innerHTML = rows.map(function(r) {
        return '<tr><td style="padding:7px 10px;border-bottom:1px solid #f0f0f0;font-weight:600;white-space:nowrap;color:#555;width:160px;">'+r[0]+'</td><td style="padding:7px 10px;border-bottom:1px solid #f0f0f0;">'+r[1]+'</td></tr>';
    }).join('');
    dialog.style.display = 'flex';
}

document.addEventListener('click', function(e) {
    var dialog = document.getElementById('rfd-detail-dialog');
    if (!dialog) return;
    if (e.target.id === 'rfd-dialog-close' || e.target === dialog) {
        dialog.style.display = 'none';
    }
});

var rfdRefreshBtn = document.getElementById('rfd-refresh-btn');
if (rfdRefreshBtn) rfdRefreshBtn.addEventListener('click', loadRFD);

// ─── Sources ──────────────────────────────────────────────────────────────────
var _allSources = [];
function loadSources() {
    var tbody = document.getElementById('sources-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:#888;">Loading…</td></tr>';
    fetch('/api/sources', { credentials: 'same-origin' })
        .then(function(r){ return r.json(); })
        .then(function(data) {
            _allSources = data.sources || [];
            renderSourcesTable(_allSources);
        })
        .catch(function(e) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:#c00;">Error: '+e+'</td></tr>';
        });
}

function renderSourcesTable(sources) {
    var tbody = document.getElementById('sources-tbody');
    if (!tbody) return;
    if (!sources.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:32px;color:#888;">No sources found.</td></tr>';
        return;
    }
    tbody.innerHTML = '';
    sources.forEach(function(src) {
        var tr = document.createElement('tr');
        tr.style.cursor = 'default';
        tr.dataset.description = src.description || '';
        tr.dataset.license = src.license || '';
        var licColor = src.license && src.license.toLowerCase().includes('public domain') ? '#1a6b3a' :
                       src.license && src.license.toLowerCase().includes('free') ? '#1a56db' : '#666';
        tr.innerHTML =
            '<td style="font-weight:500;">'+escHtml(src.name)+'</td>' +
            '<td><span style="background:#f3f4f6;border-radius:4px;padding:2px 7px;font-size:0.78rem;">'+escHtml(src.category||'—')+'</span></td>' +
            '<td><span style="color:'+licColor+';font-size:0.82rem;">'+escHtml(src.license||'—')+'</span></td>' +
            '<td><a href="https://'+escHtml(src.url)+'" target="_blank" style="color:#1a56db;font-size:0.82rem;">'+escHtml(src.url)+'</a></td>';
        tr.addEventListener('mouseenter', function(e) { showSourceTooltip(e, src); });
        tr.addEventListener('mousemove', function(e) { moveSourceTooltip(e); });
        tr.addEventListener('mouseleave', function() { hideSourceTooltip(); });
        tbody.appendChild(tr);
    });
}

function showSourceTooltip(e, src) {
    var tt = document.getElementById('sources-tooltip');
    if (!tt) return;
    tt.innerHTML = '<strong>'+escHtml(src.name)+'</strong><br>'+escHtml(src.description||'')+(src.requires_account?'<br><em style="color:#f59e0b;">⚠ Account required</em>':'');
    tt.style.display = 'block';
    moveSourceTooltip(e);
}
function moveSourceTooltip(e) {
    var tt = document.getElementById('sources-tooltip');
    if (!tt || tt.style.display==='none') return;
    tt.style.left = (e.clientX + 14) + 'px';
    tt.style.top  = (e.clientY - 10) + 'px';
}
function hideSourceTooltip() {
    var tt = document.getElementById('sources-tooltip');
    if (tt) tt.style.display = 'none';
}

var srcFilter = document.getElementById('sources-filter-category');
if (srcFilter) {
    srcFilter.addEventListener('change', function() {
        var cat = this.value;
        renderSourcesTable(cat ? _allSources.filter(function(s){ return s.category === cat; }) : _allSources);
    });
}

// ─── Court Cases ──────────────────────────────────────────────────────────────
function loadCourtCases() {
    var tbody = document.getElementById('court-cases-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#888;">Loading…</td></tr>';
    fetch('/api/court-cases', { credentials: 'same-origin' })
        .then(function(r){ return r.json(); })
        .then(function(data) {
            var cases = (data.cases || []).sort(function(a,b){ return a.severity_rank - b.severity_rank; });
            if (!cases.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:32px;color:#888;">No court cases in database.</td></tr>';
                return;
            }
            tbody.innerHTML = '';
            cases.forEach(function(c) {
                var tr = document.createElement('tr');
                var statusColor = c.episode_status === 'available' ? '#1a6b3a' : '#c00';
                tr.innerHTML =
                    '<td style="font-weight:700;color:#b91c1c;text-align:center;">'+c.severity_rank+'</td>' +
                    '<td style="font-weight:500;">'+escHtml(c.name)+'</td>' +
                    '<td style="font-size:0.82rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="'+escHtml(c.case_title)+'">'+escHtml(c.case_title)+'</td>' +
                    '<td><span style="background:#fef2f2;color:#b91c1c;border-radius:4px;padding:2px 7px;font-size:0.78rem;">'+escHtml(c.crime_category)+'</span></td>' +
                    '<td>'+escHtml(c.state||'—')+'</td>' +
                    '<td>'+escHtml(String(c.year||'—'))+'</td>' +
                    '<td><span style="color:'+statusColor+';font-size:0.82rem;font-weight:600;">'+escHtml(c.episode_status||'—')+'</span></td>';
                tr.title = (c.summary||'') + (c.why_narrate ? ' | '+c.why_narrate : '');
                tbody.appendChild(tr);
            });
        })
        .catch(function(e) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#c00;">Error: '+e+'</td></tr>';
        });
}

// ─── Voices Settings ──────────────────────────────────────────────────────────
var _voicesData = [];
var _channelAssignments = {};
var _currentAssignChannel = null;

function loadVoicesPage() {
    // Library rendering is owned by dashboard_settings_voices.js (openVoices).
    // rfd.js only handles channel assignments.
    loadChannelAssignments();
}

function loadVoicesLibrary() {
    var tbody = document.getElementById('voices-library-tbody');
    if (!tbody) return;
    fetch('/api/voices', { credentials: 'same-origin' })
        .then(function(r){ return r.json(); })
        .then(function(data) {
            _voicesData = data.voices || [];
            if (!_voicesData.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="padding:24px;text-align:center;color:#888;">No voices found.</td></tr>';
                return;
            }
            tbody.innerHTML = '';
            _voicesData.forEach(function(v) {
                var tr = document.createElement('tr');
                tr.innerHTML =
                    '<td style="font-weight:500;">'+escHtml(v.label||v.profile_id)+'</td>' +
                    '<td>'+escHtml(v.gender||'—')+'</td>' +
                    '<td>'+escHtml(v.age_group||'—')+'</td>' +
                    '<td>'+escHtml(v.style||'—')+'</td>' +
                    '<td style="font-size:0.8rem;color:#666;">'+escHtml(v.voice||'—')+'</td>' +
                    '<td style="font-size:0.82rem;color:#555;max-width:200px;">'+escHtml(v.description||'—')+'</td>' +
                    '<td><button type="button" class="btn dashboard-btn" style="padding:3px 10px;font-size:0.78rem;" data-profile-id="'+escHtml(v.profile_id)+'">▶ Play</button></td>';
                tr.querySelector('button').addEventListener('click', function() {
                    playVoicePreview(v.profile_id, this);
                });
                tbody.appendChild(tr);
            });
        });
}

function playVoicePreview(profileId, btn) {
    var origText = btn.textContent;
    btn.textContent = '…';
    btn.disabled = true;
    var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
    var headers = { 'Content-Type': 'application/json' };
    if (csrf) headers['X-CSRFToken'] = csrf;
    fetch('/api/voices/play', {
        method: 'POST',
        credentials: 'same-origin',
        headers: headers,
        body: JSON.stringify({ profile_id: profileId })
    })
    .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.blob();
    })
    .then(function(blob) {
        var url = URL.createObjectURL(blob);
        var audio = new Audio(url);
        audio.play();
        audio.onended = function() { URL.revokeObjectURL(url); };
        btn.textContent = '▶ Play';
        btn.disabled = false;
    })
    .catch(function(e) {
        btn.textContent = origText;
        btn.disabled = false;
        alert('Preview failed: ' + e);
    });
}

function loadChannelAssignments() {
    var tbody = document.getElementById('voices-channel-tbody');
    if (!tbody) return;
    fetch('/api/voices/channel-assignments', { credentials: 'same-origin' })
        .then(function(r){ return r.json(); })
        .then(function(data) {
            _channelAssignments = data.assignments || {};
            var channels = data.channels || [];
            var depts = [{channel_id:'__crime__',name:'Crime'}];
            var all = channels.concat(depts.filter(function(d){ return !channels.find(function(c){ return c.channel_id===d.channel_id; }); }));
            if (!all.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="padding:24px;text-align:center;color:#888;">No channels configured.</td></tr>';
                return;
            }
            tbody.innerHTML = '';
            all.forEach(function(ch) {
                var asgn = _channelAssignments[ch.channel_id];
                var profileId = asgn ? asgn.profile_id : '';
                var voiceInfo = _voicesData.find(function(v){ return v.profile_id === profileId; }) || {};
                var tr = document.createElement('tr');
                tr.innerHTML =
                    '<td style="font-weight:500;cursor:pointer;color:#1a56db;text-decoration:underline;" data-ch-id="'+escHtml(ch.channel_id)+'" data-ch-name="'+escHtml(ch.name||ch.channel_id)+'">'+escHtml(ch.name||ch.channel_id)+'</td>' +
                    '<td>'+(voiceInfo.label||profileId||'<em style="color:#aaa;">Not assigned</em>')+'</td>' +
                    '<td>'+(voiceInfo.gender||'—')+'</td>' +
                    '<td>'+(voiceInfo.rate||'—')+'</td>' +
                    '<td>'+(voiceInfo.pitch||'—')+'</td>' +
                    '<td>'+(voiceInfo.age_group||'—')+'</td>' +
                    '<td>'+(voiceInfo.style||'—')+'</td>';
                tr.querySelector('td').addEventListener('click', function() {
                    openVoiceModal(ch.channel_id, ch.name||ch.channel_id);
                });
                tbody.appendChild(tr);
            });
        });
}

function openVoiceModal(channelId, channelName) {
    _currentAssignChannel = { id: channelId, name: channelName };
    var modal = document.getElementById('voice-assign-modal');
    var title = document.getElementById('voice-modal-title');
    var list  = document.getElementById('voice-modal-list');
    if (!modal) return;
    title.textContent = 'Select voice for: ' + channelName;
    list.innerHTML = '';
    _voicesData.forEach(function(v) {
        var div = document.createElement('div');
        var current = (_channelAssignments[channelId]||{}).profile_id === v.profile_id;
        div.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:6px;cursor:pointer;border:1px solid '+(current?'#1a56db':'#e5e7eb')+';background:'+(current?'#eff6ff':'#fff')+';';
        div.innerHTML =
            '<span style="flex:1;font-weight:'+(current?'600':'400')+';">'+escHtml(v.label||v.profile_id)+'</span>' +
            '<span style="color:#888;font-size:0.8rem;">'+escHtml(v.gender+' · '+v.age_group+' · '+v.style)+'</span>' +
            (current?'<span style="color:#1a56db;font-size:0.8rem;">✔ Current</span>':'');
        div.addEventListener('click', function() {
            assignVoice(channelId, channelName, v.profile_id);
        });
        list.appendChild(div);
    });
    modal.style.display = 'flex';
}

function assignVoice(channelId, channelName, profileId) {
    var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
    var headers = { 'Content-Type': 'application/json' };
    if (csrf) headers['X-CSRFToken'] = csrf;
    fetch('/api/voices/assign', {
        method: 'POST', credentials: 'same-origin', headers: headers,
        body: JSON.stringify({ channel_id: channelId, channel_name: channelName, profile_id: profileId })
    })
    .then(function(r){ return r.json(); })
    .then(function(d) {
        if (d.success) {
            document.getElementById('voice-assign-modal').style.display = 'none';
            loadChannelAssignments();
        } else { alert('Failed: ' + (d.error||'unknown error')); }
    });
}

document.addEventListener('click', function(e) {
    var modal = document.getElementById('voice-assign-modal');
    if (!modal) return;
    if (e.target.id === 'voice-modal-close' || e.target === modal) {
        modal.style.display = 'none';
    }
});

// ─── Tab switching wiring ──────────────────────────────────────────────────────
document.addEventListener('click', function(e) {
    // Asset manager tab switching for new tabs
    if (e.target.classList.contains('asset-manager-subtab')) {
        var dept = e.target.dataset.department;
        if (dept === 'rfd') loadRFD();
        else if (dept === 'sources') loadSources();
        else if (dept === 'documents') loadCourtCases();
        else if (dept === 'prompts') loadPrompts();
    }
    // Documents sub-tab switching
    if (e.target.classList.contains('docs-subtab')) {
        document.querySelectorAll('.docs-subtab').forEach(function(b){ b.classList.remove('active'); });
        e.target.classList.add('active');
        var tab = e.target.dataset.docsTab;
        document.querySelectorAll('.docs-panel').forEach(function(p){ p.style.display='none'; p.classList.remove('active'); });
        var panel = document.getElementById('docs-content-' + tab);
        if (panel) { panel.style.display=''; panel.classList.add('active'); }
        if (tab === 'court-cases') loadCourtCases();
    }
});

// ─── Settings Voices page wiring ───────────────────────────────────────────────
var voicesBtn = document.getElementById('dashboard-settings-voices-btn');
var voicesBack = document.getElementById('dashboard-settings-voices-back');
if (voicesBtn) {
    voicesBtn.addEventListener('click', function() {
        document.querySelectorAll('.dashboard-settings-view').forEach(function(v){ v.style.setProperty('display', 'none', 'important'); });
        var page = document.getElementById('dashboard-settings-voices');
        if (page) { page.style.display=''; loadVoicesPage(); }
    });
}
if (voicesBack) {
    voicesBack.addEventListener('click', function() {
        document.getElementById('dashboard-settings-voices').style.display='none';
        var main = document.getElementById('dashboard-settings-main');
        if (main) main.style.display='';
    });
}

// ─── Util ─────────────────────────────────────────────────────────────────────
function escHtml(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── Prompts — 3-tab view ─────────────────────────────────────────────────────
var _allTemplatePrompts = [];
var _allSentPrompts     = [];
var _allReceivedPrompts = [];
var _activePromptSubtab = 'templates';

function _chip(label, val, color) {
    color = color || '#4f46e5';
    return '<span style="display:inline-flex;align-items:center;gap:4px;background:' + color + '15;color:' + color + ';border:1px solid ' + color + '40;border-radius:4px;padding:2px 8px;font-size:0.78rem;white-space:nowrap;">'
        + escHtml(label) + ': <b>' + escHtml(String(val||'—')) + '</b></span>';
}

function _llmColor(llm) {
    if (!llm) return '#888';
    if (llm.includes('claude')) return '#d97706';
    if (llm.includes('gpt')) return '#059669';
    if (llm.includes('qwen') || llm.includes('mistral')) return '#7c3aed';
    return '#4f46e5';
}

function _directionBadge(dir) {
    if (dir === 'sent') return '<span style="background:#dbeafe;color:#1d4ed8;border-radius:4px;padding:1px 7px;font-size:0.75rem;font-weight:600;">📤 SENT</span>';
    if (dir === 'received') return '<span style="background:#dcfce7;color:#166534;border-radius:4px;padding:1px 7px;font-size:0.75rem;font-weight:600;">📥 RECV</span>';
    return '<span style="background:#f3f4f6;color:#555;border-radius:4px;padding:1px 7px;font-size:0.75rem;">📋 TPL</span>';
}

function activatePromptSubtab(subtab) {
    _activePromptSubtab = subtab;
    document.querySelectorAll('.prompt-subtab-btn').forEach(function(b) {
        var active = b.getAttribute('data-subtab') === subtab;
        b.style.color = active ? '#6c63ff' : '#888';
        b.style.borderBottomColor = active ? '#6c63ff' : 'transparent';
    });
    document.querySelectorAll('.prompt-subpanel').forEach(function(p) {
        p.style.display = 'none';
    });
    var panel = document.getElementById('prompt-subpanel-' + subtab);
    if (panel) panel.style.display = '';
    updatePromptsCount();
}

function updatePromptsCount() {
    var el = document.getElementById('prompts-count');
    if (!el) return;
    if (_activePromptSubtab === 'templates') el.textContent = _allTemplatePrompts.length + ' templates';
    else if (_activePromptSubtab === 'sent') el.textContent = _allSentPrompts.length + ' entries';
    else el.textContent = _allReceivedPrompts.length + ' entries';
}

function loadPrompts() {
    var llmFilter = (document.getElementById('prompts-filter-llm') || {}).value || '';
    var pipeFilter = (document.getElementById('prompts-filter-pipeline') || {}).value || '';

    // Load templates from prompt registry
    var templBody = document.getElementById('prompts-templates-tbody');
    if (templBody) templBody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;color:#888;">Loading…</td></tr>';

    fetch('/api/asset_manager/prompts').then(function(r){ return r.json(); }).then(function(data) {
        _allTemplatePrompts = data.prompts || [];
        renderTemplatesTable(_allTemplatePrompts);
    }).catch(function(err) {
        if (templBody) templBody.innerHTML = '<tr><td colspan="8" style="color:#c00;padding:16px;">Error: ' + escHtml(String(err)) + '</td></tr>';
    });

    // Load sent + received from prompt_log
    var logParams = '?limit=1000';
    if (llmFilter) logParams += '&llm=' + encodeURIComponent(llmFilter);
    fetch('/api/prompt_log' + logParams).then(function(r){ return r.json(); }).then(function(data) {
        var entries = data.entries || [];
        if (pipeFilter) {
            entries = entries.filter(function(e) {
                return (e.pipeline_type || (e.meta && e.meta.pipeline_type) || '').indexOf(pipeFilter) !== -1
                    || (e.type || '').indexOf(pipeFilter) !== -1
                    || (e.stage || '').toLowerCase().indexOf(pipeFilter) !== -1;
            });
        }
        _allSentPrompts     = entries.filter(function(e){ return e.direction === 'sent'; });
        _allReceivedPrompts = entries.filter(function(e){ return e.direction === 'received'; });
        renderLogTable('sent', _allSentPrompts);
        renderLogTable('received', _allReceivedPrompts);
        updatePromptsCount();
    }).catch(function(err) {
        var sb = document.getElementById('prompts-sent-tbody');
        var rb = document.getElementById('prompts-received-tbody');
        if (sb) sb.innerHTML = '<tr><td colspan="6" style="color:#c00;padding:16px;">Error: ' + escHtml(String(err)) + '</td></tr>';
        if (rb) rb.innerHTML = '<tr><td colspan="6" style="color:#c00;padding:16px;">Error: ' + escHtml(String(err)) + '</td></tr>';
    });

    updatePromptsCount();
}

function _verBadge(v) {
    v = v || 1;
    var colors = ['#4f46e5','#059669','#d97706','#dc2626','#7c3aed'];
    var col = colors[(v - 1) % colors.length];
    return '<span style="display:inline-block;min-width:28px;text-align:center;background:' + col + ';color:#fff;border-radius:10px;padding:1px 7px;font-size:0.75rem;font-weight:700;">v' + v + '</span>';
}

function renderTemplatesTable(prompts) {
    var tbody = document.getElementById('prompts-templates-tbody');
    if (!tbody) return;
    var active = prompts.filter(function(p){ return p.active !== false; });
    // Sort most used → least used, then alphabetically by name
    active.sort(function(a, b) {
        var diff = (b.use_count || 0) - (a.use_count || 0);
        if (diff !== 0) return diff;
        return (a.name || '').localeCompare(b.name || '');
    });
    if (!active.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:32px;color:#888;">No templates registered yet. Run a pipeline to populate.</td></tr>';
        return;
    }
    var rows = active.map(function(p, idx) {
        var created  = p.created_at  ? p.created_at.replace('T',' ').slice(0,16)  : '—';
        var lastUsed = p.last_used_at ? p.last_used_at.replace('T',' ').slice(0,16) : '—';
        var catLabel = (p.category||'').replace(/_/g,' ');
        var histCount = (p.version_history || []).length;
        var histBtn = histCount > 0
            ? '<button onclick="event.stopPropagation();showVersionHistory(window.__tplData_' + idx + ')" style="padding:2px 8px;font-size:0.75rem;background:#f3f4f6;border:1px solid #ccc;border-radius:4px;cursor:pointer;" title="View ' + histCount + ' previous version(s)">📜 ' + histCount + '</button>'
            : '<span style="color:#ccc;font-size:0.75rem;">—</span>';
        window['__tplData_' + idx] = p;
        return '<tr style="cursor:pointer;" onmouseover="this.style.background=\'#f0f4ff\'" onmouseout="this.style.background=\'\'" onclick="showTemplateDetail(window.__tplData_' + idx + ')">'
            + '<td style="padding:8px 6px;text-align:center;">' + _verBadge(p.version) + '</td>'
            + '<td style="padding:8px 6px;font-weight:600;color:#1a1a2e;">' + escHtml(p.name) + '</td>'
            + '<td style="padding:8px 6px;color:#4f46e5;">' + escHtml(catLabel) + '</td>'
            + '<td style="padding:8px 6px;color:#444;font-size:0.82rem;">' + escHtml((p.function_desc||'').slice(0,80) + ((p.function_desc||'').length>80?'…':'')) + '</td>'
            + '<td style="padding:8px 6px;color:#666;font-size:0.82rem;white-space:nowrap;">' + escHtml(created) + '</td>'
            + '<td style="padding:8px 6px;color:#666;font-size:0.82rem;white-space:nowrap;">' + escHtml(lastUsed) + '</td>'
            + '<td style="padding:8px 6px;text-align:center;color:#333;">' + escHtml(String(p.use_count||0)) + '</td>'
            + '<td style="padding:8px 6px;text-align:center;" onclick="event.stopPropagation();">' + histBtn + '</td>'
            + '</tr>';
    });
    tbody.innerHTML = rows.join('');
    updatePromptsCount();
}

function renderLogTable(direction, entries) {
    var tbodyId = direction === 'sent' ? 'prompts-sent-tbody' : 'prompts-received-tbody';
    var tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    if (!entries.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:32px;color:#888;">No ' + direction + ' prompts logged yet. Run a pipeline first.</td></tr>';
        return;
    }
    var rows = entries.map(function(e, idx) {
        var ts = (e.timestamp||'').replace('T',' ').slice(0,19);
        var llm = e.llm || e.to_who || e.from_who || '';
        var llmColor = _llmColor(llm);
        var preview = (e.prompt||'').slice(0,120).replace(/\s+/g,' ');
        if ((e.prompt||'').length > 120) preview += '…';
        var pid = e.pipeline_id || '';
        window['__logEntry_' + direction + '_' + idx] = e;
        return '<tr style="cursor:pointer;" onmouseover="this.style.background=\'#f0f4ff\'" onmouseout="this.style.background=\'\'" onclick="showLogDetail(window.__logEntry_' + direction + '_' + idx + ')">'
            + '<td style="padding:7px 6px;color:#555;font-size:0.82rem;white-space:nowrap;">' + escHtml(ts) + '</td>'
            + '<td style="padding:7px 6px;"><span style="color:' + llmColor + ';font-weight:600;font-size:0.82rem;">' + escHtml(llm||'—') + '</span></td>'
            + '<td style="padding:7px 6px;color:#444;font-size:0.82rem;">' + escHtml(e.stage||'—') + '</td>'
            + '<td style="padding:7px 6px;color:#666;font-size:0.80rem;font-family:monospace;">' + escHtml((pid||'').slice(0,10) + (pid.length>10?'…':'')) + '</td>'
            + '<td style="padding:7px 6px;">' + escHtml(e.type||'—') + '</td>'
            + '<td style="padding:7px 6px;color:#333;font-size:0.80rem;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(preview) + '</td>'
            + '</tr>';
    });
    tbody.innerHTML = rows.join('');
}

// Current prompt open in dialog (for edit/save)
var _openTemplatePrompt = null;

function _enterEditMode() {
    if (!_openTemplatePrompt) return;
    document.getElementById('prompt-text-view-block').style.display = 'none';
    document.getElementById('prompt-edit-block').style.display = '';
    document.getElementById('prompt-edit-btn').style.display = 'none';
    document.getElementById('prompt-save-btn').style.display = '';
    document.getElementById('prompt-cancel-edit-btn').style.display = '';
    var ta = document.getElementById('prompt-edit-textarea');
    if (ta) ta.value = _openTemplatePrompt.prompt_text || '';
    var notes = document.getElementById('prompt-change-notes');
    if (notes) notes.value = '';
}

function _exitEditMode() {
    document.getElementById('prompt-text-view-block').style.display = '';
    document.getElementById('prompt-edit-block').style.display = 'none';
    document.getElementById('prompt-edit-btn').style.display = '';
    document.getElementById('prompt-save-btn').style.display = 'none';
    document.getElementById('prompt-cancel-edit-btn').style.display = 'none';
}

function _saveTemplateEdit() {
    if (!_openTemplatePrompt) return;
    var ta    = document.getElementById('prompt-edit-textarea');
    var notes = document.getElementById('prompt-change-notes');
    var newText     = ta ? ta.value.trim() : '';
    var changeNotes = notes ? notes.value.trim() : '';
    if (!newText) { alert('Prompt text cannot be empty.'); return; }
    var saveBtn = document.getElementById('prompt-save-btn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
    fetch('/api/prompt_registry/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt_id: _openTemplatePrompt.id, new_text: newText, change_notes: changeNotes})
    }).then(function(r){ return r.json(); }).then(function(data) {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '💾 Save'; }
        if (data.success) {
            _exitEditMode();
            loadPrompts();
            var dlg = document.getElementById('prompt-detail-dialog');
            if (dlg) dlg.style.display = 'none';
            if (data.changed) {
                alert('✅ New version saved! Previous version is preserved in history.');
            } else {
                alert('No changes detected — text was identical.');
            }
        } else {
            alert('Error: ' + (data.error || 'Unknown error'));
        }
    }).catch(function(err) {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '💾 Save'; }
        alert('Save failed: ' + String(err));
    });
}

function revertToVersion(oldPromptId, versionNum) {
    if (!confirm('Revert to v' + versionNum + '? The current version will be retired and this text becomes the new active version.')) return;
    fetch('/api/prompt_registry/revert', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt_id: oldPromptId})
    }).then(function(r){ return r.json(); }).then(function(data) {
        if (data.success) {
            var dlg = document.getElementById('prompt-detail-dialog');
            if (dlg) dlg.style.display = 'none';
            loadPrompts();
            alert('✅ Reverted to v' + versionNum + '! The old text is now active again as a new version.');
        } else {
            alert('Revert failed: ' + (data.error || 'Unknown'));
        }
    }).catch(function(err) { alert('Revert failed: ' + String(err)); });
}

function showVersionHistory(p) {
    if (!p) return;
    _openTemplatePrompt = p;
    var dlg = document.getElementById('prompt-detail-dialog');
    if (!dlg) return;
    _exitEditMode();
    document.getElementById('prompt-dialog-title').textContent = '📜 History — ' + (p.name || '');
    document.getElementById('prompt-dialog-text-label').textContent = 'Current Version Text';
    document.getElementById('prompt-dialog-text').textContent = p.prompt_text || '';
    document.getElementById('prompt-dialog-meta').innerHTML =
        _chip('Category', (p.category||'').replace(/_/g,' '), '#4f46e5')
        + _verBadge(p.version) + ' (current)'
        + _chip('Created', (p.created_at||'').replace('T',' ').slice(0,19), '#555')
        + _chip('By', p.created_by||'system', '#7c3aed')
        + (p.change_notes ? _chip('Note', p.change_notes, '#d97706') : '');
    var sysBlock = document.getElementById('prompt-dialog-system-block');
    if (sysBlock) sysBlock.style.display = 'none';
    var histBlock = document.getElementById('prompt-dialog-history-block');
    if (histBlock) histBlock.style.display = 'none';
    // Version history block
    var vhBlock = document.getElementById('prompt-version-history-block');
    var vhList  = document.getElementById('prompt-version-list');
    var vhCount = document.getElementById('prompt-version-count');
    var chain = p.version_history || [];
    if (vhBlock) vhBlock.style.display = '';
    if (vhCount) vhCount.textContent = '(' + chain.length + ' prior version' + (chain.length !== 1 ? 's' : '') + ')';
    if (vhList) {
        if (!chain.length) {
            vhList.innerHTML = '<div style="color:#888;font-size:0.85rem;padding:8px 0;">No prior versions — this is the original.</div>';
        } else {
            vhList.innerHTML = chain.slice().reverse().map(function(v) {
                var ts = (v.created_at||'').replace('T',' ').slice(0,19);
                var retired = (v.retired_at||'').replace('T',' ').slice(0,19);
                var preview = (v.prompt_text||'').slice(0,200);
                if ((v.prompt_text||'').length > 200) preview += '…';
                return '<div style="border:1px solid #e5e7eb;border-radius:7px;padding:12px 14px;background:#fafafa;">'
                    + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">'
                    + _verBadge(v.version)
                    + _chip('Created', ts, '#555')
                    + _chip('By', v.created_by||'system', '#7c3aed')
                    + _chip('Used', String(v.use_count||0) + '×', '#059669')
                    + (v.retired_at ? _chip('Retired', retired, '#888') : '')
                    + (v.change_notes ? _chip('Note', v.change_notes, '#d97706') : '')
                    + '<button onclick="revertToVersion(\'' + escHtml(v.id) + '\',' + escHtml(String(v.version)) + ')" style="margin-left:auto;padding:3px 10px;font-size:0.78rem;background:#4f46e5;color:#fff;border:none;border-radius:4px;cursor:pointer;">↩ Revert</button>'
                    + '</div>'
                    + '<pre style="background:#1e1e2e;color:#cdd6f4;padding:10px 12px;border-radius:5px;font-size:0.78rem;white-space:pre-wrap;word-break:break-word;margin:0;max-height:160px;overflow-y:auto;">' + escHtml(preview) + '</pre>'
                    + '</div>';
            }).join('');
        }
    }
    // Show edit button for current active template
    document.getElementById('prompt-edit-btn').style.display = '';
    dlg.style.display = 'flex';
}

function showTemplateDetail(p) {
    if (!p) return;
    _openTemplatePrompt = p;
    var dlg = document.getElementById('prompt-detail-dialog');
    if (!dlg) return;
    _exitEditMode();
    document.getElementById('prompt-dialog-title').textContent = '📋 ' + (p.name || 'Template');
    document.getElementById('prompt-dialog-text-label').textContent = 'Template Text';
    var sysBlock = document.getElementById('prompt-dialog-system-block');
    if (sysBlock) sysBlock.style.display = 'none';
    // Meta chips — full info
    var created   = (p.created_at||'').replace('T',' ').slice(0,19);
    var lastUsed  = (p.last_used_at||'').replace('T',' ').slice(0,19);
    var createdBy = p.created_by || 'system';
    document.getElementById('prompt-dialog-meta').innerHTML =
        _chip('Category', (p.category||'').replace(/_/g,' '), '#4f46e5')
        + _verBadge(p.version)
        + _chip('Created', created, '#555')
        + _chip('By', createdBy, '#7c3aed')
        + _chip('Last used', lastUsed, '#059669')
        + _chip('Uses', String(p.use_count||0), '#d97706')
        + (p.change_notes ? _chip('Note', p.change_notes, '#d97706') : '')
        + '<span style="background:#d1fae5;color:#065f46;border-radius:4px;padding:2px 8px;font-size:0.78rem;">active</span>';
    document.getElementById('prompt-dialog-text').textContent = p.prompt_text || '';
    // Show edit button
    document.getElementById('prompt-edit-btn').style.display = '';
    // Version history hidden in simple detail view
    var vhBlock = document.getElementById('prompt-version-history-block');
    if (vhBlock) vhBlock.style.display = 'none';
    // Use history
    var histBlock = document.getElementById('prompt-dialog-history-block');
    if (histBlock) histBlock.style.display = '';
    var hist = p.use_history || [];
    document.getElementById('prompt-history-count').textContent = '(' + hist.length + ')';
    var hbody = document.getElementById('prompt-history-tbody');
    if (!hist.length) {
        hbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:14px;color:#888;">No use history yet.</td></tr>';
    } else {
        hbody.innerHTML = hist.slice().reverse().map(function(h) {
            return '<tr>'
                + '<td style="padding:5px 8px;white-space:nowrap;">' + escHtml((h.ts||h.used_at||'').replace('T',' ').slice(0,19)) + '</td>'
                + '<td style="padding:5px 8px;font-family:monospace;font-size:0.8rem;">' + escHtml(h.pipeline_id||'—') + '</td>'
                + '<td style="padding:5px 8px;">' + escHtml(h.stage||'—') + '</td>'
                + '<td style="padding:5px 8px;">' + escHtml(h.topic||'—') + '</td>'
                + '</tr>';
        }).join('');
    }
    dlg.style.display = 'flex';
}

function showLogDetail(e) {
    if (!e) return;
    _openTemplatePrompt = null;
    var dlg = document.getElementById('prompt-detail-dialog');
    if (!dlg) return;
    _exitEditMode();
    var dir = e.direction || '';
    var llm = e.llm || e.to_who || e.from_who || '?';
    var icon = dir === 'sent' ? '📤' : '📥';
    document.getElementById('prompt-dialog-title').textContent = icon + ' ' + (e.type||'Prompt') + ' — ' + llm;
    document.getElementById('prompt-dialog-text-label').textContent = dir === 'sent' ? 'Sent Prompt' : 'Received Response';
    // Hide edit button for log entries
    document.getElementById('prompt-edit-btn').style.display = 'none';
    // System prompt block
    var sysBlock = document.getElementById('prompt-dialog-system-block');
    var sysPre   = document.getElementById('prompt-dialog-system');
    if (e.system_prompt && sysBlock && sysPre) {
        sysBlock.style.display = '';
        sysPre.textContent = e.system_prompt;
    } else if (sysBlock) {
        sysBlock.style.display = 'none';
    }
    // Meta chips
    var llmColor = _llmColor(llm);
    var ts = (e.timestamp||'').replace('T',' ').slice(0,19);
    var fromTo = dir === 'sent'
        ? _chip('From', e.from_who||'system', '#555') + _chip('To', e.to_who||llm, llmColor)
        : _chip('From', e.from_who||llm, llmColor) + _chip('To', e.to_who||'system', '#555');
    document.getElementById('prompt-dialog-meta').innerHTML =
        _chip('Time', ts, '#555')
        + '<span style="background:' + llmColor + '15;color:' + llmColor + ';border:1px solid ' + llmColor + '40;border-radius:4px;padding:2px 8px;font-size:0.78rem;font-weight:600;">' + escHtml(llm) + '</span>'
        + _chip('Stage', e.stage, '#4f46e5')
        + _chip('Type', e.type, '#7c3aed')
        + _chip('Pipeline', e.pipeline_id ? e.pipeline_id.slice(0,12) : '—', '#059669')
        + fromTo
        + (e.words ? _chip('Words', e.words, '#d97706') : '')
        + (e.n_sents ? _chip('Sentences', e.n_sents, '#d97706') : '');
    document.getElementById('prompt-dialog-text').textContent = e.prompt || '';
    var vhBlock = document.getElementById('prompt-version-history-block');
    if (vhBlock) vhBlock.style.display = 'none';
    var histBlock = document.getElementById('prompt-dialog-history-block');
    if (histBlock) histBlock.style.display = 'none';
    dlg.style.display = 'flex';
}

// Dialog close + edit/save/cancel
document.addEventListener('click', function(e) {
    if (e.target.id === 'prompt-dialog-close') {
        var dlg = document.getElementById('prompt-detail-dialog');
        if (dlg) dlg.style.display = 'none';
        _exitEditMode();
    }
    if (e.target.id === 'prompt-detail-dialog') {
        e.target.style.display = 'none';
        _exitEditMode();
    }
    if (e.target.id === 'prompt-edit-btn')        _enterEditMode();
    if (e.target.id === 'prompt-cancel-edit-btn') _exitEditMode();
    if (e.target.id === 'prompt-save-btn')        _saveTemplateEdit();
});

// Sub-tab switching
document.addEventListener('click', function(e) {
    var btn = e.target.closest('.prompt-subtab-btn');
    if (btn) activatePromptSubtab(btn.getAttribute('data-subtab'));
    if (e.target.id === 'prompts-refresh-btn') loadPrompts();
});

// Filter changes
document.addEventListener('change', function(e) {
    if (e.target.id === 'prompts-filter-llm' || e.target.id === 'prompts-filter-pipeline') loadPrompts();
});

// Expose prompt dialog functions globally so inline onclick attrs in rendered HTML can reach them
window.showTemplateDetail  = showTemplateDetail;
window.showVersionHistory  = showVersionHistory;
window.showLogDetail       = showLogDetail;
window.revertToVersion     = revertToVersion;
window.showRFDDetail       = showRFDDetail;

})();
