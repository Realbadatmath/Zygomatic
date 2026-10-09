// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Asset Manager
 * Browse assets by department: 2D Series, 3D Series, Clipfarm, Mechanics.
 * Table columns: Date Created, ID, Created By, Asset Type.
 */
(function () {
    'use strict';

    function byId(id) { return document.getElementById(id); }

    var ASSETLIB_CATS = ['items', 'food', 'weapons', 'agriculture', 'water', 'clouds', 'geology', 'furniture', 'sfx', 'vocal_fx', 'foley', 'instruments', 'soundtracks'];
    var DEPARTMENTS = ['2d_series', '3d_series', 'clipfarm', 'mechanics', 'rfd', 'sources', 'documents', 'imagery', 'videos', 'storyteller', 'prompts', 'data_retrieval', 'templates', 'environments', 'effects', 'wardrobe'].concat(ASSETLIB_CATS);
    var DEPARTMENT_LABELS = {
        '2d_series': '2D Series',
        '3d_series': '3D Series',
        'clipfarm': 'Clipfarm',
        'mechanics': 'Mechanics'
    };

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function formatAssetRow(asset) {
        var dateCreated = escapeHtml(asset.date_created || asset.dateCreated || asset.created_at || '-');
        var id = escapeHtml(asset.id || asset.asset_id || '-');
        var createdBy = escapeHtml(asset.created_by || asset.createdBy || asset.creator || '-');
        var assetType = escapeHtml(asset.asset_type || asset.assetType || asset.type || '-');
        return '<tr><td>' + dateCreated + '</td><td>' + id + '</td><td>' + createdBy + '</td><td>' + assetType + '</td></tr>';
    }

    function fillTable(department, assets) {
        var tbody = byId('asset-manager-tbody-' + department);
        if (!tbody) return;
        if (!Array.isArray(assets) || assets.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:32px;color:#666;">No assets. Connect to asset API or add data.</td></tr>';
            return;
        }
        tbody.innerHTML = assets.map(formatAssetRow).join('');
    }

    function fetchAssets(department) {
        var endpoint = '/api/assets/' + department;
        return fetch(endpoint)
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; });
    }

    function loadDepartment(department) {
        fetchAssets(department).then(function (data) {
            var assets = (data && (data.assets || data.items || data)) || [];
            if (Array.isArray(assets)) {
                fillTable(department, assets);
            } else if (data && typeof data === 'object') {
                fillTable(department, []);
            }
        });
    }

    function switchSubtab(department) {
        DEPARTMENTS.forEach(function (dep) {
            var panel = byId('asset-manager-content-' + dep);
            var btn = document.querySelector('.asset-manager-subtab[data-department="' + dep + '"]');
            if (panel) panel.style.display = dep === department ? 'block' : 'none';
            if (panel) panel.classList.toggle('active', dep === department);
            if (btn) {
                btn.classList.toggle('active', dep === department);
                btn.setAttribute('aria-selected', dep === department ? 'true' : 'false');
                btn.setAttribute('tabindex', dep === department ? '0' : '-1');
            }
        });
        if (ASSETLIB_CATS.indexOf(department) >= 0) {
            if (typeof window.amLoadAssetLib === 'function') window.amLoadAssetLib(department);
        } else if (department !== 'clipfarm' && department !== 'rfd' && department !== 'sources'
                && department !== 'documents' && department !== 'imagery'
                && department !== 'videos' && department !== 'storyteller' && department !== 'prompts'
                && department !== 'templates' && department !== 'environments' && department !== 'effects'
                && department !== 'wardrobe') {
            loadDepartment(department);
        } else if (department === 'templates') {
            if (typeof window.amTemplatesRefresh === 'function') window.amTemplatesRefresh();
        } else if (department === 'environments') {
            if (typeof window.amLoadEnvironments === 'function') window.amLoadEnvironments();
        } else if (department === 'effects') {
            if (typeof window.amLoadEffects === 'function') window.amLoadEffects();
        } else if (department === 'wardrobe') {
            if (typeof window.amLoadWardrobe === 'function') window.amLoadWardrobe();
        } else if (department === 'storyteller') {
            // Storyteller episodes have their own tab + endpoint (/api/storyteller/episodes).
            if (typeof window.amLoadEpisodes === 'function') window.amLoadEpisodes();
        } else if (department === 'clipfarm') {
            // Refresh the SFX/Reaction panel when user switches to Clipfarm tab
            if (typeof caLoadStatusFn === 'function') caLoadStatusFn();
        }
        // rfd/sources/documents/imagery/videos/prompts are loaded by dashboard_tab_asset_manager_rfd.js
    }

    var caLoadStatusFn = null;  // exposed so switchSubtab can refresh on tab activation

    function render(container) {
        if (!container) return;

        // ── Clipfarm asset downloader panel (injected into Clipfarm tab) ─────
        var clipfarmPanel = byId('asset-manager-content-clipfarm');
        if (clipfarmPanel && !byId('clipfarm-asset-dl-panel')) {
            var dlPanel = document.createElement('div');
            dlPanel.id = 'clipfarm-asset-dl-panel';
            dlPanel.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;';
            dlPanel.innerHTML =
                '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">' +
                '<span style="color:#58a6ff;font-weight:700;font-size:14px;">🎵 Clipfarm Assets — SFX &amp; Reaction Clips</span>' +
                '<div style="display:flex;gap:8px;">' +
                '<button id="ca-refresh-btn" style="background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:5px;padding:4px 12px;cursor:pointer;font-size:12px;">⟳ Refresh</button>' +
                '<button id="ca-download-btn" style="background:#238636;color:#fff;border:none;border-radius:5px;padding:4px 14px;cursor:pointer;font-size:12px;font-weight:600;">⬇ Download Missing</button>' +
                '</div></div>' +
                '<div style="display:flex;gap:18px;">' +
                // SFX table
                '<div style="flex:1;">' +
                '<div style="color:#8b949e;font-size:11px;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em;">Sound Effects (.mp3)</div>' +
                '<table style="width:100%;border-collapse:collapse;font-size:12px;" id="ca-sfx-table">' +
                '<thead><tr style="color:#484f58;border-bottom:1px solid #30363d;">' +
                '<th style="text-align:left;padding:3px 6px;">File</th>' +
                '<th style="text-align:center;padding:3px 6px;">Status</th>' +
                '<th style="text-align:right;padding:3px 6px;">Size</th>' +
                '</tr></thead><tbody id="ca-sfx-tbody"><tr><td colspan="3" style="color:#484f58;padding:8px 6px;">Loading…</td></tr></tbody>' +
                '</table></div>' +
                // Reaction clips table
                '<div style="flex:1;">' +
                '<div style="color:#8b949e;font-size:11px;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em;">Reaction Clips (.mp4)</div>' +
                '<table style="width:100%;border-collapse:collapse;font-size:12px;" id="ca-reaction-table">' +
                '<thead><tr style="color:#484f58;border-bottom:1px solid #30363d;">' +
                '<th style="text-align:left;padding:3px 6px;">File</th>' +
                '<th style="text-align:left;padding:3px 6px;">Source / Note</th>' +
                '<th style="text-align:center;padding:3px 6px;">Status</th>' +
                '<th style="text-align:right;padding:3px 6px;">Size</th>' +
                '</tr></thead><tbody id="ca-reaction-tbody"><tr><td colspan="4" style="color:#484f58;padding:8px 6px;">Loading…</td></tr></tbody>' +
                '</table></div>' +
                '</div>' +
                '<div id="ca-status-bar" style="margin-top:8px;font-size:11px;color:#484f58;"></div>';
            clipfarmPanel.appendChild(dlPanel);

            function escHtml(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

            // ── Preview modal ─────────────────────────────────────────────────
            function ensureModal() {
                if (byId('ca-preview-modal')) return;
                var m = document.createElement('div');
                m.id = 'ca-preview-modal';
                m.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,0.82);z-index:9999;align-items:center;justify-content:center;';
                m.innerHTML =
                    '<div style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px;max-width:560px;width:90%;position:relative;">' +
                    '<button id="ca-modal-close" style="position:absolute;top:10px;right:14px;background:none;border:none;color:#8b949e;font-size:20px;cursor:pointer;line-height:1;">✕</button>' +
                    '<div id="ca-modal-title" style="color:#58a6ff;font-weight:700;font-size:15px;margin-bottom:12px;padding-right:24px;"></div>' +
                    '<div id="ca-modal-media" style="margin-bottom:14px;text-align:center;"></div>' +
                    '<div id="ca-modal-desc" style="color:#c9d1d9;font-size:13px;margin-bottom:8px;line-height:1.6;"></div>' +
                    '<div id="ca-modal-use" style="background:#0d1117;border-left:3px solid #58a6ff;padding:10px 14px;border-radius:4px;color:#8b949e;font-size:12px;line-height:1.6;"></div>' +
                    '</div>';
                document.body.appendChild(m);
                m.addEventListener('click', function(e){ if (e.target === m) closeModal(); });
                byId('ca-modal-close').onclick = closeModal;
            }
            function closeModal() {
                var m = byId('ca-preview-modal');
                if (!m) return;
                m.style.display = 'none';
                // stop media playback
                var vid = m.querySelector('video');
                var aud = m.querySelector('audio');
                if (vid) { vid.pause(); vid.src = ''; }
                if (aud) { aud.pause(); aud.src = ''; }
            }
            function openModal(title, mediaHtml, desc, useWhen) {
                ensureModal();
                byId('ca-modal-title').textContent = title;
                byId('ca-modal-media').innerHTML = mediaHtml;
                byId('ca-modal-desc').textContent = desc || '';
                byId('ca-modal-desc').style.display = desc ? 'block' : 'none';
                byId('ca-modal-use').innerHTML = useWhen
                    ? '<strong style="color:#58a6ff;">📌 Use when:</strong> ' + escHtml(useWhen)
                    : '<em style="color:#484f58;">No usage notes.</em>';
                var m = byId('ca-preview-modal');
                m.style.display = 'flex';
            }

            function caLoadStatus() {
                fetch('/api/assets/status').then(function(r){ return r.json(); }).then(function(d) {
                    var sfxTbody = byId('ca-sfx-tbody');
                    var reactTbody = byId('ca-reaction-tbody');
                    if (sfxTbody) {
                        var sfx = d.sfx || [];
                        if (sfx.length) {
                            sfxTbody.innerHTML = sfx.map(function(s) {
                                var dot = s.present ? '<span style="color:#3fb950;">✅</span>' : '<span style="color:#f85149;">✗</span>';
                                var hasInfo = s.desc || s.use_when;
                                return '<tr style="border-bottom:1px solid #161b22;' + (hasInfo ? 'cursor:pointer;' : '') + '" ' +
                                    (hasInfo ? 'data-sfx-file="' + escHtml(s.file) + '" data-sfx-name="' + escHtml(s.name||s.file) + '" data-sfx-desc="' + escHtml(s.desc||'') + '" data-sfx-use="' + escHtml(s.use_when||'') + '"' : '') + '>' +
                                    '<td style="padding:3px 6px;color:#c9d1d9;">' + escHtml(s.file) + (hasInfo ? ' <span style="color:#484f58;font-size:10px;">ℹ</span>' : '') + '</td>' +
                                    '<td style="padding:3px 6px;text-align:center;">' + dot + '</td>' +
                                    '<td style="padding:3px 6px;text-align:right;color:#484f58;">' + (s.present ? s.size_kb + ' KB' : '—') + '</td></tr>';
                            }).join('');
                            // bind click for SFX rows
                            sfxTbody.querySelectorAll('tr[data-sfx-file]').forEach(function(row) {
                                row.addEventListener('click', function() {
                                    var file = row.getAttribute('data-sfx-file');
                                    var name = row.getAttribute('data-sfx-name');
                                    var desc = row.getAttribute('data-sfx-desc');
                                    var use  = row.getAttribute('data-sfx-use');
                                    var audioHtml = '<audio controls autoplay style="width:100%;margin-bottom:4px;">' +
                                        '<source src="/api/assets/preview/sfx/' + encodeURIComponent(file) + '" type="audio/mpeg">' +
                                        '</audio>';
                                    openModal('🔊 ' + name, audioHtml, desc, use);
                                });
                                row.addEventListener('mouseenter', function(){ row.style.background='#1c2128'; });
                                row.addEventListener('mouseleave', function(){ row.style.background=''; });
                            });
                        } else {
                            sfxTbody.innerHTML = '<tr><td colspan="3" style="color:#484f58;padding:6px;">No catalogue</td></tr>';
                        }
                    }
                    if (reactTbody) {
                        var react = d.reaction_clips || [];
                        if (react.length) {
                            reactTbody.innerHTML = react.map(function(r) {
                                var dot = r.present ? '<span style="color:#3fb950;">✅</span>' : '<span style="color:#f85149;">✗</span>';
                                var hasInfo = r.present && (r.desc || r.use_when);
                                return '<tr style="border-bottom:1px solid #161b22;' + (hasInfo ? 'cursor:pointer;' : '') + '" ' +
                                    (hasInfo ? 'data-react-file="' + escHtml(r.file) + '" data-react-desc="' + escHtml(r.desc||'') + '" data-react-use="' + escHtml(r.use_when||'') + '"' : '') + '>' +
                                    '<td style="padding:3px 6px;color:#c9d1d9;">' + escHtml(r.file) + (hasInfo ? ' <span style="color:#484f58;font-size:10px;">ℹ</span>' : '') + '</td>' +
                                    '<td style="padding:3px 6px;color:#8b949e;font-size:11px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escHtml(r.desc) + '">' + escHtml(r.desc || r.source || '—') + '</td>' +
                                    '<td style="padding:3px 6px;text-align:center;">' + dot + '</td>' +
                                    '<td style="padding:3px 6px;text-align:right;color:#484f58;">' + (r.present ? r.size_kb + ' KB' : '—') + '</td></tr>';
                            }).join('');
                            // bind click for reaction rows
                            reactTbody.querySelectorAll('tr[data-react-file]').forEach(function(row) {
                                row.addEventListener('click', function() {
                                    var file = row.getAttribute('data-react-file');
                                    var desc = row.getAttribute('data-react-desc');
                                    var use  = row.getAttribute('data-react-use');
                                    var videoHtml = '<video controls autoplay muted loop style="width:100%;max-height:280px;border-radius:6px;background:#000;">' +
                                        '<source src="/api/assets/preview/reaction/' + encodeURIComponent(file) + '" type="video/mp4">' +
                                        '</video>';
                                    openModal('🎬 ' + file, videoHtml, desc, use);
                                });
                                row.addEventListener('mouseenter', function(){ row.style.background='#1c2128'; });
                                row.addEventListener('mouseleave', function(){ row.style.background=''; });
                            });
                        } else {
                            reactTbody.innerHTML = '<tr><td colspan="4" style="color:#484f58;padding:6px;">No catalogue</td></tr>';
                        }
                    }
                    var totalMissing = ((d.sfx||[]).filter(function(s){return !s.present;}).length) +
                                      ((d.reaction_clips||[]).filter(function(r){return !r.present;}).length);
                    var statusBar = byId('ca-status-bar');
                    if (statusBar) statusBar.textContent = totalMissing === 0 ? '✅ All assets present' : totalMissing + ' file(s) missing — click Download Missing to fetch them';
                }).catch(function(){});
            }
            caLoadStatusFn = caLoadStatus;

            var dlBtn = byId('ca-download-btn');
            if (dlBtn) {
                dlBtn.onclick = function() {
                    dlBtn.disabled = true;
                    dlBtn.textContent = '⬇ Downloading… (watch Live Tail)';
                    fetch('/api/assets/download', {method:'POST'}).then(function(r){ return r.json(); }).then(function(d) {
                        var statusBar = byId('ca-status-bar');
                        if (statusBar) statusBar.textContent = '⬇ Download started — progress visible in Live Tail';
                        setTimeout(function(){ dlBtn.disabled = false; dlBtn.textContent = '⬇ Download Missing'; caLoadStatus(); }, 5000);
                    }).catch(function(){ dlBtn.disabled = false; dlBtn.textContent = '⬇ Download Missing'; });
                };
            }
            var refreshBtn = byId('ca-refresh-btn');
            if (refreshBtn) refreshBtn.onclick = caLoadStatus;

            caLoadStatus();
        }

        // ── existing subtab wiring ────────────────────────────────────────────
        var subtabs = container.querySelectorAll('.asset-manager-subtab');
        subtabs.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var dep = this.getAttribute('data-department');
                if (dep) switchSubtab(dep);
            });
        });
        var active = container.querySelector('.asset-manager-subtab.active');
        var initialDept = (active && active.getAttribute('data-department')) || '2d_series';
        switchSubtab(initialDept);
    }

    if (typeof window !== 'undefined') {
        window.DashboardTabAssetManager = { render: render };
    }
})();

