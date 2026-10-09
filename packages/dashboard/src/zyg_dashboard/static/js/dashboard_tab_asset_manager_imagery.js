// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// ── Asset Manager: Imagery & Videos tabs ─────────────────────────────────
(function() {
    function loadImagery() {
        fetch('/api/scholarly/imagery').then(r => r.json()).then(data => {
            const items = data.images || [];
            document.getElementById('imagery-count').textContent = items.length + ' images';
            const tbody = document.getElementById('imagery-tbody');
            if (!items.length) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:32px;color:#666;">No imagery found yet.</td></tr>';
                return;
            }
            tbody.innerHTML = items.map(img => `
                <tr style="border-bottom:1px solid #eee;">
                    <td style="padding:6px;"><img src="/api/scholarly/imagery/thumb?path=${encodeURIComponent(img.path)}" style="width:80px;height:60px;object-fit:cover;border-radius:3px;" onerror="this.style.display='none'"/></td>
                    <td style="padding:6px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${(img.caption||'').replace(/"/g,'&quot;')}">${img.caption||'—'}</td>
                    <td style="padding:6px;font-size:0.82rem;color:#444;">${img.essay_title||'—'}</td>
                    <td style="padding:6px;"><span style="background:#e8f4e8;padding:2px 6px;border-radius:10px;font-size:0.78rem;">${img.topic||'—'}</span></td>
                    <td style="padding:6px;font-size:0.82rem;">${img.duration_s ? Math.round(img.duration_s)+'s' : '—'}</td>
                    <td style="padding:6px;"><span style="color:${img.used?'#1a6b3a':'#888'};font-size:0.82rem;">${img.used?'✓ Used':'Pending'}</span></td>
                </tr>
            `).join('');
        }).catch(e => console.warn('Imagery load failed:', e));
    }

    function loadVideos() {
        fetch('/api/scholarly/videos').then(r => r.json()).then(data => {
            const items = data.videos || [];
            document.getElementById('videos-count').textContent = items.length + ' videos';
            const tbody = document.getElementById('videos-tbody');
            if (!items.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:32px;color:#666;">No scholarly videos found yet.</td></tr>';
                return;
            }
            tbody.innerHTML = items.map(v => `
                <tr style="border-bottom:1px solid #eee;">
                    <td style="padding:6px;font-size:0.78rem;color:#888;">${v.pipeline_id||'—'}</td>
                    <td style="padding:6px;"><span style="background:#e8f4e8;padding:2px 6px;border-radius:10px;font-size:0.78rem;">${v.topic||'—'}</span></td>
                    <td style="padding:6px;font-size:0.85rem;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${(v.title||'').replace(/"/g,'&quot;')}">${v.title||'—'}</td>
                    <td style="padding:6px;font-size:0.82rem;">${v.duration_s ? (v.duration_s/60).toFixed(1)+'min' : '—'}</td>
                    <td style="padding:6px;font-size:0.82rem;">${v.episode||'1'}</td>
                    <td style="padding:6px;font-size:0.78rem;color:#888;">${(v.created||'').slice(0,16)}</td>
                    <td style="padding:6px;">
                        ${v.episode2_ready ? '<button class="btn dashboard-btn" style="font-size:0.78rem;padding:2px 8px;background:#1a6b3a;color:#fff;" onclick="alert(\'Episode 2 queuing coming soon\')">▶ Queue Ep.2</button>' : ''}
                    </td>
                </tr>
            `).join('');
        }).catch(e => console.warn('Videos load failed:', e));
    }

    /* 2026-07-24: Storyteller episodes in the Asset Manager (Videos sub-tab) */
    function loadEpisodes() {
        fetch('/api/storyteller/episodes').then(r => r.json()).then(data => {
            const items = data.episodes || [];
            const cnt = document.getElementById('episodes-count');
            if (cnt) cnt.textContent = items.length + ' episodes';
            const tbody = document.getElementById('episodes-tbody');
            if (!tbody) return;
            if (!items.length) {
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:32px;color:#666;">No storyteller episodes found yet.</td></tr>';
                return;
            }
            tbody.innerHTML = items.map(e => {
                const q = e.quality === 'good'
                    ? '<span style="background:#e8f4e8;color:#1a6b3a;padding:2px 8px;border-radius:10px;font-size:0.78rem;">good</span>'
                    : '<span style="background:#fdecea;color:#b3261e;padding:2px 8px;border-radius:10px;font-size:0.78rem;" title="' + (e.issues || []).join(', ').replace(/"/g, '&quot;') + '">degraded</span>';
                const vurl = '/api/storyteller/episodes/' + encodeURIComponent(e.pipeline_id) + '/video';
                return `
                <tr style="border-bottom:1px solid #eee;">
                    <td style="padding:6px;font-size:0.78rem;color:#888;">${(e.pipeline_id || '—').slice(0, 8)}</td>
                    <td style="padding:6px;"><span style="background:#eef2ff;color:#4f46e5;padding:2px 8px;border-radius:10px;font-size:0.78rem;">${e.character || '—'}</span></td>
                    <td style="padding:6px;font-size:0.85rem;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${(e.title || '').replace(/"/g, '&quot;')}">${e.title || '—'}</td>
                    <td style="padding:6px;font-size:0.82rem;">${e.duration_s ? (e.duration_s / 60).toFixed(1) + 'min' : '—'}</td>
                    <td style="padding:6px;">${q}</td>
                    <td style="padding:6px;font-size:0.78rem;color:#888;">${(e.created || '').slice(0, 16)}</td>
                    <td style="padding:6px;font-size:0.82rem;">${e.filesize ? (e.filesize / 1048576).toFixed(0) + ' MB' : '—'}</td>
                    <td style="padding:6px;white-space:nowrap;">
                        <a class="btn dashboard-btn" style="font-size:0.78rem;padding:2px 8px;text-decoration:none;" href="${vurl}" target="_blank">▶ Play</a>
                        <a class="btn dashboard-btn" style="font-size:0.78rem;padding:2px 8px;text-decoration:none;" href="${vurl}?download=1">⬇</a>
                    </td>
                </tr>`;
            }).join('');
        }).catch(e => console.warn('Episodes load failed:', e));
    }

    /* 2026-07-25: storyteller episodes moved to their own Asset Manager tab.
       Expose the loader so the tab switcher (dashboard_tab_asset_manager.js)
       can populate it when the Storyteller tab is activated. */
    window.amLoadEpisodes = loadEpisodes;

    document.addEventListener('DOMContentLoaded', function() {
        const imgBtn = document.getElementById('imagery-refresh-btn');
        if (imgBtn) imgBtn.addEventListener('click', loadImagery);
        const vidBtn = document.getElementById('videos-refresh-btn');
        if (vidBtn) vidBtn.addEventListener('click', loadVideos);
        const epBtn = document.getElementById('episodes-refresh-btn');
        if (epBtn) epBtn.addEventListener('click', loadEpisodes);
    });

    /* ── Environments / Effects asset grids (2026-07-28) ── */
    function _envfxEsc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _loadEnvfx(dept) {
        const grid = document.getElementById(dept + '-grid');
        const cnt = document.getElementById(dept + '-count');
        if (!grid) return;
        fetch('/api/' + dept + '/list').then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                const items = (d && d.items) || [];
                if (cnt) cnt.textContent = items.length + ' asset' + (items.length === 1 ? '' : 's');
                if (!items.length) {
                    grid.innerHTML = '<div style="color:#888;">No ' + dept + ' assets yet. Run an ' + dept + ' job (2D/3D toggle picks the mode) to populate this.</div>';
                    return;
                }
                grid.innerHTML = items.map(function (it) {
                    const media = it.kind === 'video'
                        ? '<video src="' + it.url + '" controls preload="metadata" style="width:100%;border-radius:8px 8px 0 0;background:#000;aspect-ratio:16/10;object-fit:cover;"></video>'
                        : '<img src="' + it.url + '" loading="lazy" style="width:100%;border-radius:8px 8px 0 0;aspect-ratio:16/10;object-fit:cover;background:#111;" onerror="this.style.opacity=0.2">';
                    const tag = it.render_mode ? '<span style="font-size:.7rem;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,.12);">' + _envfxEsc(String(it.render_mode).toUpperCase()) + '</span>' : '';
                    const dl = it.url + (it.kind === 'video' ? '?download=1' : '');
                    return '<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:8px;overflow:hidden;">'
                        + media
                        + '<div style="padding:8px 10px;font-size:.78rem;">'
                        + '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px;"><b>' + _envfxEsc(it.name) + '</b>' + tag + '</div>'
                        + '<div style="color:#999;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + _envfxEsc(it.directive || '') + '">' + _envfxEsc(it.directive || '—') + '</div>'
                        + '<a href="' + dl + '"' + (it.kind === 'image' ? ' download' : '') + ' style="color:#7fd4df;font-size:.72rem;">&#x2b07; download</a>'
                        + '</div></div>';
                }).join('');
            })
            .catch(function () { grid.innerHTML = '<div style="color:#c66;">Failed to load ' + dept + ' assets.</div>'; });
    }
    window.amLoadEnvironments = function () { _loadEnvfx('environments'); };
    window.amLoadEffects = function () {
        _wdEnsureMenus();
        var box = document.getElementById('effects-library');
        var cnt = document.getElementById('effects-count');
        if (box) {
            fetch('/api/effects/library').then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    var effects = (d && d.effects) || [];
                    if (cnt) cnt.textContent = effects.length + ' effect' + (effects.length === 1 ? '' : 's') + ' · right-click a card';
                    box.innerHTML = effects.length ? effects.map(function (fx) {
                        var is3d = fx.kind === '3d';
                        var kindTag = '<span style="font-size:.66rem;padding:2px 6px;border-radius:4px;background:' + (is3d ? 'rgba(122,63,110,.5)' : 'rgba(20,110,140,.5)') + ';color:#fff;">' + (is3d ? '3D' : '2D') + '</span>';
                        var prevUrl = '/api/effects/preview?id=' + encodeURIComponent(fx.id);
                        var prev;
                        if (!fx.has_preview) {
                            prev = '<div style="width:100%;aspect-ratio:16/10;border-radius:7px 7px 0 0;background:repeating-linear-gradient(45deg,#161c24,#161c24 10px,#1b222b 10px,#1b222b 20px);display:flex;align-items:center;justify-content:center;color:#556;font-size:.72rem;text-align:center;padding:8px;">preview rendering…</div>';
                        } else if (is3d) {
                            prev = '<video src="' + prevUrl + '" autoplay loop muted playsinline preload="metadata" style="width:100%;aspect-ratio:16/10;object-fit:cover;border-radius:7px 7px 0 0;background:#000;"></video>';
                        } else {
                            prev = '<img src="' + prevUrl + '" style="width:100%;aspect-ratio:16/10;object-fit:cover;border-radius:7px 7px 0 0;background:#0f141a;">';
                        }
                        return '<div class="fx-card" data-fid="' + _envfxEsc(fx.id) + '" title="Right-click for options" '
                            + 'style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:8px;overflow:hidden;cursor:context-menu;">'
                            + prev
                            + '<div style="padding:8px 10px;"><div style="display:flex;justify-content:space-between;align-items:center;gap:6px;"><span style="font-weight:600;font-size:.84rem;">' + _envfxEsc(fx.name || fx.id) + '</span>' + kindTag + '</div>'
                            + '<div style="color:#999;font-size:.72rem;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + _envfxEsc(fx.description || '') + '">' + _envfxEsc(fx.description || '') + '</div></div>'
                            + '</div>';
                    }).join('') : '<div style="color:#888;">No effects.</div>';
                    // left-click a card → enlarge in the lightbox (←/→ navigates, click-away closes)
                    box.onclick = function (e) {
                        var card = e.target.closest ? e.target.closest('.fx-card') : null;
                        if (!card) return;
                        if (e.target.tagName === 'VIDEO') { /* fall through — enlarge the clip too */ }
                        var lbItems = effects.filter(function (fx) { return fx.has_preview; }).map(function (fx) {
                            return { id: fx.id, kind: fx.kind === '3d' ? 'video' : 'img',
                                     title: fx.name || fx.id, sub: fx.description || '',
                                     src: '/api/effects/preview?id=' + encodeURIComponent(fx.id) };
                        });
                        var at = lbItems.findIndex(function (it) { return it.id === card.dataset.fid; });
                        if (at >= 0) _amLbOpen(lbItems, at);
                    };
                    box.oncontextmenu = function (e) {
                        var card = e.target.closest ? e.target.closest('.fx-card') : null;
                        if (!card) return;
                        e.preventDefault();
                        var fid = card.dataset.fid;
                        _wdKind = 'effects'; _wdCat = null;
                        _wdCurrent = (effects.filter(function (fx) { return fx.id === fid; })[0]) || { id: fid };
                        _wdEnsureMenus();
                        var lbl = document.getElementById('wd-del-label'); if (lbl) lbl.textContent = 'Delete effect';
                        var apRow = document.querySelector('#wd-ctxmenu [data-act="apply"]'); if (apRow) apRow.style.display = '';
                        var ctx = document.getElementById('wd-ctxmenu');
                        document.getElementById('wd-charmenu').style.display = 'none';
                        ctx.style.display = 'block';
                        var x = Math.min(e.clientX, window.innerWidth - 190), y = Math.min(e.clientY, window.innerHeight - 90);
                        ctx.style.left = x + 'px'; ctx.style.top = y + 'px';
                    };
                })
                .catch(function () { box.innerHTML = '<div style="color:#c66;">Failed to load effects library.</div>'; });
        }
        _loadEnvfx('effects');   // generated results into #effects-grid
    };
    /* ── Wardrobe + Effects card boards + shared right-click menu (Apply to character / Delete) ── */
    var _wdChars = null;                       // cached character list
    var _wdCurrent = null;                     // asset (outfit/effect/library asset) the menu acts on
    var _wdKind = 'wardrobe';                  // 'wardrobe' | 'effects' | 'assetlib'
    var _wdCat = null;                         // assetlib category when _wdKind === 'assetlib'
    /* ── card lightbox: left-click enlarges, click-away closes, ←/→ navigates ── */
    var _amLb = { items: [], idx: -1 };        // items: [{src, kind:'img'|'video', title, sub}]
    function _amLbEl() {
        var lb = document.getElementById('am-lightbox');
        if (lb) return lb;
        lb = document.createElement('div');
        lb.id = 'am-lightbox';
        lb.style.cssText = 'position:fixed;inset:0;z-index:100000;display:none;background:rgba(8,10,14,.88);'
            + 'align-items:center;justify-content:center;flex-direction:column;gap:12px;cursor:zoom-out;';
        lb.innerHTML = '<div id="am-lb-media" style="max-width:calc(86vw / var(--ui-zoom,1));max-height:calc(78vh / var(--ui-zoom,1));cursor:default;display:flex;align-items:center;justify-content:center;"></div>'
            + '<div id="am-lb-cap" style="color:#dfe5ec;font-size:.95rem;font-weight:600;text-align:center;max-width:calc(80vw / var(--ui-zoom,1));"></div>'
            + '<div id="am-lb-hint" style="color:#8a93a0;font-size:.75rem;">&#8592; / &#8594; navigate &nbsp;·&nbsp; click anywhere to close</div>';
        document.body.appendChild(lb);
        // click ANYWHERE on the page (backdrop, caption, outside) closes — except the media itself
        lb.addEventListener('click', function (e) {
            var m = document.getElementById('am-lb-media');
            if (m && m.contains(e.target)) return;
            _amLbClose();
        });
        return lb;
    }
    function _amLbRender() {
        var it = _amLb.items[_amLb.idx];
        if (!it) return;
        var m = document.getElementById('am-lb-media');
        m.innerHTML = it.kind === 'video'
            ? '<video src="' + it.src + '" autoplay loop muted playsinline controls style="max-width:calc(86vw / var(--ui-zoom,1));max-height:calc(78vh / var(--ui-zoom,1));border-radius:10px;box-shadow:0 10px 44px rgba(0,0,0,.6);background:#000;"></video>'
            : '<img src="' + it.src + '" style="max-width:calc(86vw / var(--ui-zoom,1));max-height:calc(78vh / var(--ui-zoom,1));border-radius:10px;box-shadow:0 10px 44px rgba(0,0,0,.6);background:#0f141a;">';
        document.getElementById('am-lb-cap').innerHTML =
            _envfxEsc(it.title || '') + ' <span style="opacity:.55;font-weight:400;">· ' + (_amLb.idx + 1) + ' / ' + _amLb.items.length + '</span>'
            + (it.sub ? '<div style="color:#9aa4b2;font-size:.76rem;font-weight:400;margin-top:4px;">' + _envfxEsc(it.sub) + '</div>' : '');
    }
    function _amLbOpen(items, idx) {
        if (!items || !items.length) return;
        _amLb.items = items; _amLb.idx = Math.max(0, Math.min(idx || 0, items.length - 1));
        _wdCloseMenus();
        _amLbEl().style.display = 'flex';
        _amLbRender();
    }
    function _amLbClose() {
        var lb = document.getElementById('am-lightbox');
        if (lb) lb.style.display = 'none';
        var m = document.getElementById('am-lb-media');
        if (m) m.innerHTML = '';   // stop any playing video
        _amLb.items = []; _amLb.idx = -1;
    }
    function _amLbOpenState() {
        var lb = document.getElementById('am-lightbox');
        return !!(lb && lb.style.display !== 'none' && _amLb.items.length);
    }
    document.addEventListener('keydown', function (e) {
        if (!_amLbOpenState()) return;
        if (e.key === 'Escape') { _amLbClose(); return; }
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
            e.preventDefault(); _amLb.idx = (_amLb.idx + 1) % _amLb.items.length; _amLbRender();
        } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
            e.preventDefault(); _amLb.idx = (_amLb.idx - 1 + _amLb.items.length) % _amLb.items.length; _amLbRender();
        }
    });
    function _wdCsrf() { var m = document.querySelector('meta[name=csrf-token]'); return m ? m.content : ''; }
    function _wdToast(msg, ok) {
        var t = document.createElement('div');
        t.textContent = msg;
        t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:100002;'
            + 'background:' + (ok ? '#1a6b3a' : '#8a3b2e') + ';color:#fff;padding:10px 18px;border-radius:8px;'
            + 'font-size:.85rem;box-shadow:0 4px 16px rgba(0,0,0,.4);';
        document.body.appendChild(t);
        setTimeout(function () { t.remove(); }, 3200);
    }
    function _wdCloseMenus() {
        var c = document.getElementById('wd-ctxmenu'); if (c) c.style.display = 'none';
        var s = document.getElementById('wd-charmenu'); if (s) s.style.display = 'none';
    }
    function _wdEnsureMenus() {
        if (document.getElementById('wd-ctxmenu')) return;
        var mS = 'position:fixed;z-index:100001;display:none;background:#1b222b;border:1px solid #33404d;'
            + 'border-radius:8px;padding:5px;min-width:170px;box-shadow:0 8px 28px rgba(0,0,0,.5);font-size:.83rem;';
        var iS = 'padding:8px 12px;border-radius:5px;cursor:pointer;color:#e7ebf0;display:flex;justify-content:space-between;gap:10px;';
        var ctx = document.createElement('div'); ctx.id = 'wd-ctxmenu'; ctx.style.cssText = mS;
        ctx.innerHTML = '<div class="wd-mi" data-act="apply" style="' + iS + '">Apply to character <span style="opacity:.6">&#9656;</span></div>'
            + '<div class="wd-mi" data-act="delete" style="' + iS + 'color:#e5988a;"><span id="wd-del-label">Delete outfit</span></div>';
        document.body.appendChild(ctx);
        var sub = document.createElement('div'); sub.id = 'wd-charmenu'; sub.style.cssText = mS + 'min-width:230px;max-height:calc(60vh / var(--ui-zoom,1));overflow:hidden;display:none;';
        sub.innerHTML = '<input id="wd-charsearch" placeholder="Search characters…" '
            + 'style="width:100%;box-sizing:border-box;background:#0f141a;border:1px solid #33404d;color:#e7ebf0;'
            + 'border-radius:6px;padding:7px 10px;font-size:.8rem;margin-bottom:5px;">'
            + '<div id="wd-charlist" style="max-height:calc(48vh / var(--ui-zoom,1));overflow-y:auto;"></div>';
        document.body.appendChild(sub);
        ctx.querySelectorAll('.wd-mi').forEach(function (mi) {
            mi.addEventListener('mouseenter', function () { mi.style.background = '#2a3542'; });
            mi.addEventListener('mouseleave', function () { mi.style.background = 'transparent'; });
        });
        ctx.querySelector('[data-act="apply"]').addEventListener('mouseenter', function () {
            var r = ctx.getBoundingClientRect();
            var s2 = document.getElementById('wd-charmenu');
            s2.style.display = 'block';
            var left = r.right + 4; if (left + 240 > window.innerWidth) left = r.left - 244;
            s2.style.left = left + 'px'; s2.style.top = r.top + 'px';
            _wdRenderChars('');
            var si = document.getElementById('wd-charsearch'); if (si) { si.value = ''; si.focus(); }
        });
        ctx.querySelector('[data-act="delete"]').addEventListener('click', function () {
            var noun = _wdKind === 'effects' ? 'effect' : (_wdKind === 'assetlib' ? 'asset' : 'outfit');
            var libName = _wdKind === 'assetlib' ? (_wdCat + ' library') : (_wdKind + ' library');
            if (_wdCurrent && confirm('Delete ' + noun + ' "' + (_wdCurrent.name || _wdCurrent.id) + '" from the ' + libName + '?')) {
                _wdDelete(_wdCurrent.id);
            }
            _wdCloseMenus();
        });
        document.getElementById('wd-charsearch').addEventListener('input', function (e) { _wdRenderChars(e.target.value); });
        document.getElementById('wd-charsearch').addEventListener('click', function (e) { e.stopPropagation(); });
        document.addEventListener('click', function (e) {
            if (!ctx.contains(e.target) && !sub.contains(e.target)) _wdCloseMenus();
        });
        // Close on PAGE scroll, but NOT when scrolling inside the menus themselves
        // (the character list scrolls internally — capture-phase scroll must ignore it).
        window.addEventListener('scroll', function (e) {
            if ((sub && sub.contains(e.target)) || (ctx && ctx.contains(e.target))) return;
            _wdCloseMenus();
        }, true);
    }
    function _wdRenderChars(filter) {
        var list = document.getElementById('wd-charlist'); if (!list) return;
        var render = function (chars) {
            var f = (filter || '').toLowerCase();
            var shown = chars.filter(function (c) { return !f || (c.name || '').toLowerCase().indexOf(f) >= 0 || (c.char_id || '').indexOf(f) >= 0; });
            list.innerHTML = shown.length ? shown.map(function (c) {
                return '<div class="wd-char" data-cid="' + _envfxEsc(c.char_id) + '" style="padding:7px 10px;border-radius:5px;cursor:pointer;color:#e7ebf0;">'
                    + _envfxEsc(c.name || c.char_id) + '<span style="opacity:.5;font-size:.72rem;"> · ' + _envfxEsc((c.model_family || '')) + '</span></div>';
            }).join('') : '<div style="padding:8px 10px;color:#888;">No matches.</div>';
            list.querySelectorAll('.wd-char').forEach(function (el) {
                el.addEventListener('mouseenter', function () { el.style.background = '#2a3542'; });
                el.addEventListener('mouseleave', function () { el.style.background = 'transparent'; });
                el.addEventListener('click', function () { _wdApply(_wdCurrent && _wdCurrent.id, el.dataset.cid, el.textContent); });
            });
        };
        if (_wdChars) { render(_wdChars); return; }
        list.innerHTML = '<div style="padding:8px 10px;color:#888;">Loading characters…</div>';
        fetch('/api/internal/storyteller/list-chars').then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { _wdChars = (d && d.chars) || []; render(_wdChars); })
            .catch(function () { list.innerHTML = '<div style="padding:8px 10px;color:#c66;">Failed to load characters.</div>'; });
    }
    function _wdApply(assetId, charId, charName) {
        _wdCloseMenus();
        if (!assetId || !charId) return;
        var isFx = _wdKind === 'effects', isAl = _wdKind === 'assetlib';
        var noun = isFx ? 'effect' : (isAl ? 'asset' : 'outfit');
        _wdToast('Applying ' + noun + ' to ' + charName + '…', true);
        var body;
        if (isAl) body = { pipeline_type: 'asset_apply', category: _wdCat, asset_id: assetId, char_id: charId, directive: '' };
        else if (isFx) body = { pipeline_type: 'effects', char_id: charId, effect_id: assetId, directive: '' };
        else body = { pipeline_type: 'wardrobe', char_id: charId, outfit_id: assetId, directive: '' };
        fetch('/api/internal/pipeline/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _wdCsrf() },
            body: JSON.stringify(body)
        }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
            .then(function (res) {
                if (res.ok && res.j.job_id) _wdToast(noun.charAt(0).toUpperCase() + noun.slice(1) + ' job started — result appears under Generated below.', true);
                else _wdToast('Could not start: ' + (res.j.error || 'a pipeline may be running'), false);
            })
            .catch(function () { _wdToast('Request failed.', false); });
    }
    function _wdDelete(assetId) {
        var isFx = _wdKind === 'effects', isAl = _wdKind === 'assetlib';
        var cat = _wdCat;
        var url = isAl ? '/api/assetlib/delete' : (isFx ? '/api/effects/delete' : '/api/wardrobe/delete');
        var payload = isAl ? { cat: cat, id: assetId } : { id: assetId };
        fetch(url, {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _wdCsrf() },
            body: JSON.stringify(payload)
        }).then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _wdToast(d && d.ok ? 'Deleted.' : 'Delete failed.', !!(d && d.ok));
                if (isAl) { window.amLoadAssetLib(cat); }
                else if (isFx) { window.amLoadEffects(); } else { window.amLoadWardrobe(); }
            })
            .catch(function () { _wdToast('Delete failed.', false); });
    }
    window.amLoadWardrobe = function () {
        _wdEnsureMenus();
        var box = document.getElementById('wardrobe-outfits');
        var cnt = document.getElementById('wardrobe-count');
        if (box) {
            fetch('/api/wardrobe/outfits').then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    var outfits = (d && d.outfits) || [];
                    if (cnt) cnt.textContent = outfits.length + ' outfit' + (outfits.length === 1 ? '' : 's') + ' · right-click a card';
                    box.innerHTML = outfits.length ? outfits.map(function (o) {
                        var prev = o.has_preview
                            ? '<img src="/api/wardrobe/preview?id=' + encodeURIComponent(o.id) + '" style="width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:7px 7px 0 0;background:#0f141a;">'
                            : '<div style="width:100%;aspect-ratio:3/4;border-radius:7px 7px 0 0;background:repeating-linear-gradient(45deg,#161c24,#161c24 10px,#1b222b 10px,#1b222b 20px);display:flex;align-items:center;justify-content:center;color:#556;font-size:.72rem;text-align:center;padding:8px;">preview rendering…</div>';
                        return '<div class="wd-card" data-oid="' + _envfxEsc(o.id) + '" title="Right-click for options" '
                            + 'style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:8px;overflow:hidden;cursor:context-menu;">'
                            + prev
                            + '<div style="padding:8px 10px;"><div style="font-weight:600;font-size:.84rem;">' + _envfxEsc(o.name || o.id) + '</div>'
                            + '<div style="color:#999;font-size:.72rem;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + _envfxEsc(o.prompt_clause || '') + '">' + _envfxEsc(o.prompt_clause || '') + '</div></div>'
                            + '</div>';
                    }).join('') : '<div style="color:#888;">No outfits.</div>';
                    // left-click a card → enlarge in the lightbox (←/→ navigates, click-away closes)
                    box.onclick = function (e) {
                        var card = e.target.closest ? e.target.closest('.wd-card') : null;
                        if (!card) return;
                        var lbItems = outfits.filter(function (o) { return o.has_preview; }).map(function (o) {
                            return { id: o.id, kind: 'img', title: o.name || o.id, sub: o.prompt_clause || '',
                                     src: '/api/wardrobe/preview?id=' + encodeURIComponent(o.id) };
                        });
                        var at = lbItems.findIndex(function (it) { return it.id === card.dataset.oid; });
                        if (at >= 0) _amLbOpen(lbItems, at);
                    };
                    // one delegated right-click handler for the whole grid
                    box.oncontextmenu = function (e) {
                        var card = e.target.closest ? e.target.closest('.wd-card') : null;
                        if (!card) return;
                        e.preventDefault();
                        var oid = card.dataset.oid;
                        _wdKind = 'wardrobe'; _wdCat = null;
                        _wdCurrent = (outfits.filter(function (o) { return o.id === oid; })[0]) || { id: oid };
                        _wdEnsureMenus();
                        var lbl = document.getElementById('wd-del-label'); if (lbl) lbl.textContent = 'Delete outfit';
                        var apRow = document.querySelector('#wd-ctxmenu [data-act="apply"]'); if (apRow) apRow.style.display = '';
                        var ctx = document.getElementById('wd-ctxmenu');
                        document.getElementById('wd-charmenu').style.display = 'none';
                        ctx.style.display = 'block';
                        var x = Math.min(e.clientX, window.innerWidth - 190), y = Math.min(e.clientY, window.innerHeight - 90);
                        ctx.style.left = x + 'px'; ctx.style.top = y + 'px';
                    };
                })
                .catch(function () { box.innerHTML = '<div style="color:#c66;">Failed to load wardrobe library.</div>'; });
        }
        _loadEnvfx('wardrobe');   // generated results into #wardrobe-grid
    };
    /* ── Generic asset-library card boards (items/food/weapons/agriculture/water/clouds/geology/sfx/vocal_fx/soundtracks) ── */

    // Audio records carry no prompt_clause — a visual asset's card subtitle. Build
    // one from what an audio file actually is, so the card is not blank.
    function _alAudioDesc(a) {
        var bits = [];
        if (a.sex) bits.push(a.sex);
        if (a.group) bits.push(a.group);
        var head = bits.join(' · ');
        if (a.descriptor) return head ? head + ' — ' + a.descriptor : a.descriptor;
        return head;
    }

    // Everything a filter box should match on, lower-cased once per card.
    function _alHaystack(a) {
        return [a.id, a.name, a.group, a.descriptor, a.sex, a.license_id,
                a.prompt_clause, a.notes].join(' ').toLowerCase();
    }

    // A flat grid stops being a library somewhere around a hundred cards, and
    // vocal_fx holds 315. The filter is client-side because the whole list is
    // already in hand — one fetch, instant typing, no endpoint to keep in sync.
    function _alWireFilter(cat, box, cnt, assets, renderCards) {
        var host = document.getElementById(cat + '-alfilter');
        if (!host) {
            host = document.createElement('div');
            host.id = cat + '-alfilter';
            host.style.cssText = 'margin:0 0 10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;';
            box.parentNode.insertBefore(host, box);
        }
        var groups = [];
        assets.forEach(function (a) {
            if (a.group && groups.indexOf(a.group) < 0) groups.push(a.group);
        });
        groups.sort();
        host.innerHTML =
            '<input id="' + cat + '-alq" placeholder="Filter ' + assets.length + ' files…" '
            + 'style="flex:1;min-width:200px;padding:6px 10px;border-radius:6px;border:1px solid rgba(255,255,255,.15);background:#0f141a;color:#dde;">'
            + (groups.length > 1
                ? '<select id="' + cat + '-algrp" style="padding:6px 10px;border-radius:6px;border:1px solid rgba(255,255,255,.15);background:#0f141a;color:#dde;">'
                  + '<option value="">all groups</option>'
                  + groups.map(function (g) { return '<option value="' + _envfxEsc(g) + '">' + _envfxEsc(g) + '</option>'; }).join('')
                  + '</select>'
                : '')
            + '<span id="' + cat + '-alnote" style="color:#888;font-size:.72rem;"></span>';

        var pre = assets.map(function (a) { return { a: a, hay: _alHaystack(a) }; });
        function apply() {
            var qEl = document.getElementById(cat + '-alq');
            var gEl = document.getElementById(cat + '-algrp');
            var q = ((qEl && qEl.value) || '').trim().toLowerCase();
            var g = (gEl && gEl.value) || '';
            var terms = q ? q.split(/\s+/) : [];
            var hit = pre.filter(function (r) {
                if (g && r.a.group !== g) return false;
                for (var i = 0; i < terms.length; i++) {
                    if (r.hay.indexOf(terms[i]) < 0) return false;
                }
                return true;
            }).map(function (r) { return r.a; });
            renderCards(hit);
            var note = document.getElementById(cat + '-alnote');
            if (note) note.textContent = (q || g) ? hit.length + ' of ' + assets.length : '';
        }
        var qEl = document.getElementById(cat + '-alq');
        if (qEl) qEl.addEventListener('input', apply);
        var gEl = document.getElementById(cat + '-algrp');
        if (gEl) gEl.addEventListener('change', apply);
        return apply;
    }

    window.amLoadAssetLib = function (cat) {
        _wdEnsureMenus();
        var box = document.getElementById(cat + '-library');
        var cnt = document.getElementById(cat + '-count');
        if (!box) return;
        fetch('/api/assetlib/list?cat=' + encodeURIComponent(cat)).then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                var assets = (d && d.assets) || [];
                var isAudio = (d && d.kind) === 'audio';
                if (cnt) cnt.textContent = assets.length + ' asset' + (assets.length === 1 ? '' : 's') + (assets.length ? ' · right-click a card' : '');
                if (!assets.length) {
                    box.innerHTML = isAudio
                        ? '<div style="color:#888;">No audio files yet. Drop .wav / .mp3 files into <code>data/asset_libraries/' + _envfxEsc(cat) + '/</code> and hit Refresh.</div>'
                        : '<div style="color:#888;">Library is empty.</div>';
                    return;
                }
                var renderCards = function (list) {
                box.innerHTML = list.map(function (a) {
                    var prevUrl = '/api/assetlib/preview?cat=' + encodeURIComponent(cat) + '&id=' + encodeURIComponent(a.id);
                    var prev;
                    if (isAudio) {
                        prev = '<div style="padding:22px 12px 8px;display:flex;flex-direction:column;align-items:center;gap:10px;background:#10151c;border-radius:7px 7px 0 0;">'
                            + '<div style="font-size:2rem;">' + (cat === 'soundtracks' ? '🎵' : cat === 'vocal_fx' ? '🗣️' : cat === 'foley' ? '🥁' : cat === 'instruments' ? '🎸' : '🔊') + '</div>'
                            + '<audio controls preload="none" src="' + prevUrl + '" style="width:100%;"></audio></div>';
                    } else if (a.has_preview) {
                        prev = '<img src="' + prevUrl + '" loading="lazy" style="width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:7px 7px 0 0;background:#0f141a;">';
                    } else {
                        prev = '<div style="width:100%;aspect-ratio:4/3;border-radius:7px 7px 0 0;background:repeating-linear-gradient(45deg,#161c24,#161c24 10px,#1b222b 10px,#1b222b 20px);display:flex;align-items:center;justify-content:center;color:#556;font-size:.72rem;text-align:center;padding:8px;">preview rendering…</div>';
                    }
                    var anchorTag = (!isAudio && a.anchor)
                        ? '<span style="font-size:.62rem;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,.1);color:#aab;">' + _envfxEsc(a.anchor) + '</span>' : '';
                    // audio cards: license line — warn whenever commercial_ok is not exactly true
                    var licLine = '';
                    if (isAudio) {
                        var licOk = a.commercial_ok === true;
                        var restrict = [];
                        if (a.no_ai_training) restrict.push('no AI training');
                        if (a.no_redistribute) restrict.push('no redistribution');
                        licLine = '<div style="font-size:.68rem;margin-top:3px;color:' + (licOk ? '#7fa982' : '#e0a640') + ';">'
                            + (licOk ? '' : '⚠ ') + _envfxEsc(a.license_id || 'no license')
                            + (licOk ? '' : ' — not cleared for publication')
                            + (restrict.length ? ' · <span style="color:#c99a55;">mix-only (' + _envfxEsc(restrict.join(', ')) + ')</span>' : '')
                            + '</div>';
                        if (a.verbal) {
                            licLine += '<div style="font-size:.68rem;margin-top:2px;color:#e0a640;">⚠ contains speech — wrong for a non-English or period scene</div>';
                        }
                    }
                    return '<div class="al-card" data-aid="' + _envfxEsc(a.id) + '" title="Right-click for options" '
                        + 'style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:8px;overflow:hidden;cursor:context-menu;">'
                        + prev
                        + '<div style="padding:8px 10px;"><div style="display:flex;justify-content:space-between;align-items:center;gap:6px;"><span style="font-weight:600;font-size:.84rem;">' + _envfxEsc(a.name || a.id) + '</span>' + anchorTag + '</div>'
                        + '<div style="color:#999;font-size:.72rem;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + _envfxEsc(a.prompt_clause || a.notes || '') + '">' + _envfxEsc(a.prompt_clause || _alAudioDesc(a)) + '</div>' + licLine + '</div>'
                        + '</div>';
                }).join('') || '<div style="color:#888;">Nothing matches that filter.</div>';
                };
                renderCards(assets);
                // Big libraries get a filter box; small ones stay as they were.
                if (assets.length > 40) _alWireFilter(cat, box, cnt, assets, renderCards);
                // left-click a card → enlarge in the lightbox (visual categories only; audio
                // cards keep their inline player untouched)
                box.onclick = function (e) {
                    if (isAudio) return;
                    var card = e.target.closest ? e.target.closest('.al-card') : null;
                    if (!card) return;
                    var lbItems = assets.filter(function (a) { return a.has_preview; }).map(function (a) {
                        return { id: a.id, kind: 'img', title: a.name || a.id, sub: a.prompt_clause || '',
                                 src: '/api/assetlib/preview?cat=' + encodeURIComponent(cat) + '&id=' + encodeURIComponent(a.id) };
                    });
                    var at = lbItems.findIndex(function (it) { return it.id === card.dataset.aid; });
                    if (at >= 0) _amLbOpen(lbItems, at);
                };
                box.oncontextmenu = function (e) {
                    var card = e.target.closest ? e.target.closest('.al-card') : null;
                    if (!card) return;
                    if (e.target.tagName === 'AUDIO') return;   // let the player's own menu work
                    e.preventDefault();
                    var aid = card.dataset.aid;
                    _wdKind = 'assetlib'; _wdCat = cat;
                    _wdCurrent = (assets.filter(function (a) { return a.id === aid; })[0]) || { id: aid };
                    _wdEnsureMenus();
                    var lbl = document.getElementById('wd-del-label'); if (lbl) lbl.textContent = 'Delete asset';
                    // audio assets can't be applied to a character — hide the Apply row for them
                    var apRow = document.querySelector('#wd-ctxmenu [data-act="apply"]');
                    if (apRow) apRow.style.display = isAudio ? 'none' : '';
                    var ctx = document.getElementById('wd-ctxmenu');
                    document.getElementById('wd-charmenu').style.display = 'none';
                    ctx.style.display = 'block';
                    var x = Math.min(e.clientX, window.innerWidth - 190), y = Math.min(e.clientY, window.innerHeight - 90);
                    ctx.style.left = x + 'px'; ctx.style.top = y + 'px';
                };
            })
            .catch(function () { box.innerHTML = '<div style="color:#c66;">Failed to load ' + _envfxEsc(cat) + ' library.</div>'; });
        // generated apply-results (visual categories only — wrap stays hidden when empty)
        var grid = document.getElementById(cat + '-grid');
        var wrap = document.getElementById(cat + '-generated-wrap');
        if (grid && wrap) {
            fetch('/api/assetlib/generated?cat=' + encodeURIComponent(cat)).then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    var items = (d && d.items) || [];
                    wrap.style.display = items.length ? 'block' : 'none';
                    grid.innerHTML = items.map(function (it) {
                        var media = it.kind === 'video'
                            ? '<video src="' + it.url + '" controls preload="metadata" style="width:100%;border-radius:8px 8px 0 0;background:#000;aspect-ratio:16/10;object-fit:cover;"></video>'
                            : '<img src="' + it.url + '" loading="lazy" style="width:100%;border-radius:8px 8px 0 0;aspect-ratio:16/10;object-fit:cover;background:#111;">';
                        return '<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:8px;overflow:hidden;">'
                            + media
                            + '<div style="padding:8px 10px;font-size:.78rem;"><b>' + _envfxEsc(it.name) + '</b>'
                            + '<div style="color:#999;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _envfxEsc(it.directive || '') + '</div></div></div>';
                    }).join('');
                })
                .catch(function () { });
        }
    };
})();
