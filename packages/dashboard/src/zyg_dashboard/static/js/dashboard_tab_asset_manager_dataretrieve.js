// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Data Retrieval tab — Asset Manager
 * Loads channel groups from /api/channel-data/groups, renders a sidebar,
 * and fetches live data per channel via /api/channel-data/<key>.
 */
(function () {
    'use strict';

    var _initialized  = false;
    var _groups       = [];
    var _cache        = {};          // channel_key → last result
    var _activeKey    = null;

    function byId(id) { return document.getElementById(id); }

    function esc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function fmtDate(s) {
        if (!s) return '';
        try {
            var d = new Date(s);
            if (isNaN(d.getTime())) return s.slice(0, 16);
            return d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'});
        } catch (e) { return s.slice(0, 16); }
    }

    // ── Single-image lightbox ───────────────────────────────────────────────────

    function ensureLightbox() {
        if (byId('dr-img-lightbox')) return;
        var overlay = document.createElement('div');
        overlay.id = 'dr-img-lightbox';
        overlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:9950;'
            + 'background:rgba(0,0,0,0.85);backdrop-filter:blur(4px);'
            + 'align-items:center;justify-content:center;flex-direction:column;';
        overlay.innerHTML =
            '<div style="position:relative;max-width:calc(90vw / var(--ui-zoom,1));max-height:calc(90vh / var(--ui-zoom,1));display:flex;flex-direction:column;align-items:center;gap:12px;">'
            + '<button id="dr-lb-close" style="position:absolute;top:-36px;right:0;background:rgba(255,255,255,0.12);'
            +   'border:1px solid rgba(255,255,255,0.25);color:#fff;border-radius:6px;padding:2px 12px;'
            +   'cursor:pointer;font-size:1.1rem;line-height:1.6;">✕</button>'
            + '<img id="dr-lb-img" src="" alt="" style="max-width:calc(88vw / var(--ui-zoom,1));max-height:calc(76vh / var(--ui-zoom,1));border-radius:8px;'
            +   'object-fit:contain;display:block;box-shadow:0 8px 40px rgba(0,0,0,0.6);" />'
            + '<div id="dr-lb-cap" style="color:#e5e7eb;font-size:0.88rem;text-align:center;'
            +   'max-width:720px;line-height:1.5;padding:0 12px;"></div>'
            + '<a id="dr-lb-link" href="#" target="_blank" rel="noopener" '
            +   'style="display:none;color:#38bdf8;font-size:0.8rem;text-decoration:none;">Open article ↗</a>'
            + '</div>';
        document.body.appendChild(overlay);

        byId('dr-lb-close').addEventListener('click', function () { overlay.style.display = 'none'; });
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.style.display = 'none';
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && byId('dr-img-lightbox').style.display !== 'none') {
                byId('dr-img-lightbox').style.display = 'none';
            }
        });
    }

    function openLightbox(imageUrl, title, link) {
        ensureLightbox();
        var overlay = byId('dr-img-lightbox');
        var img     = byId('dr-lb-img');
        var cap     = byId('dr-lb-cap');
        var lnk     = byId('dr-lb-link');

        img.src = imageUrl;
        cap.textContent = title || '';
        if (link) { lnk.href = link; lnk.style.display = 'inline'; }
        else       { lnk.style.display = 'none'; }

        overlay.style.display = 'flex';
    }

    // ── Sidebar ──────────────────────────────────────────────────────────────

    function buildSidebar(groups) {
        var sidebar = byId('dr-sidebar');
        if (!sidebar) return;
        var html = '';
        groups.forEach(function (g) {
            html += '<div style="margin-bottom:4px;">';
            html += '<div style="font-size:0.68rem;font-weight:700;color:#888;letter-spacing:0.08em;'
                  + 'text-transform:uppercase;padding:8px 0 4px 2px;">' + esc(g.group) + '</div>';
            g.channels.forEach(function (ch) {
                var key   = ch[0];
                var label = ch[1];
                html += '<div class="dr-ch-item" data-key="' + esc(key) + '" '
                      + 'onclick="drSelectChannel(\'' + esc(key) + '\')" '
                      + 'style="display:flex;align-items:center;justify-content:space-between;'
                      + 'padding:5px 8px 5px 10px;border-radius:5px;cursor:pointer;font-size:0.82rem;'
                      + 'color:#374151;transition:background 0.1s;">'
                      + '<span class="dr-ch-label">' + esc(label) + '</span>'
                      + '<span class="dr-ch-badge" id="dr-badge-' + esc(key) + '" '
                      + 'style="font-size:0.68rem;border-radius:3px;padding:1px 5px;display:none;"></span>'
                      + '</div>';
            });
            html += '</div>';
        });
        sidebar.innerHTML = html;

        sidebar.addEventListener('mouseover', function (e) {
            var el = e.target.closest('.dr-ch-item');
            if (el && el.getAttribute('data-key') !== _activeKey) {
                el.style.background = '#f3f4f6';
            }
        });
        sidebar.addEventListener('mouseout', function (e) {
            var el = e.target.closest('.dr-ch-item');
            if (el && el.getAttribute('data-key') !== _activeKey) {
                el.style.background = '';
            }
        });
    }

    function setActiveStyle(key) {
        var items = document.querySelectorAll('.dr-ch-item');
        items.forEach(function (el) {
            if (el.getAttribute('data-key') === key) {
                el.style.background  = '#e0f2fe';
                el.style.color       = '#0e7490';
                el.style.fontWeight  = '600';
            } else {
                el.style.background  = '';
                el.style.color       = '';
                el.style.fontWeight  = '';
            }
        });
    }

    // ── Result panel ─────────────────────────────────────────────────────────

    function showLoading(label) {
        var tbody = byId('dr-result-tbody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:40px;color:#aaa;">Loading ' + esc(label) + '…</td></tr>';
        var title = byId('dr-result-title');
        if (title) title.textContent = label;
        var badge = byId('dr-result-badge');
        if (badge) { badge.style.display = 'none'; }
        var srcEl = byId('dr-result-source');
        if (srcEl) srcEl.textContent = '';
        var timeEl = byId('dr-result-time');
        if (timeEl) timeEl.textContent = '';
    }

    function renderResult(result) {
        var title  = byId('dr-result-title');
        var srcEl  = byId('dr-result-source');
        var badge  = byId('dr-result-badge');
        var timeEl = byId('dr-result-time');
        var tbody  = byId('dr-result-tbody');
        var thead  = byId('dr-result-thead');
        if (!tbody) return;

        if (title)  title.textContent  = result.label || result.channel || '';
        if (srcEl)  srcEl.textContent  = result.source ? '· ' + result.source : '';
        if (timeEl) timeEl.textContent = result.fetched_at ? 'Fetched ' + fmtDate(result.fetched_at) : '';

        if (badge) {
            if (result.status === 'ok') {
                badge.textContent      = result.item_count + ' items';
                badge.style.background = '#d1fae5';
                badge.style.color      = '#065f46';
                badge.style.display    = 'inline-block';
            } else {
                badge.textContent      = 'Error';
                badge.style.background = '#fee2e2';
                badge.style.color      = '#991b1b';
                badge.style.display    = 'inline-block';
            }
        }

        if (result.status === 'error') {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:32px;color:#991b1b;">'
                + esc(result.error || 'Unknown error') + '</td></tr>';
            return;
        }

        var items = result.items || [];
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:32px;color:#aaa;">No items returned.</td></tr>';
            return;
        }

        // Detect column shape
        var first        = items[0];
        var isLocalFile  = first.link && first.link.startsWith('/');
        var hasDownloads = 'downloads' in first;

        if (thead) {
            if (isLocalFile) {
                thead.innerHTML = '<tr><th>File</th><th>Size</th><th>Modified</th></tr>';
            } else if (hasDownloads) {
                thead.innerHTML = '<tr><th>Model</th><th>Stats</th><th>Last Updated</th></tr>';
            } else {
                thead.innerHTML = '<tr>'
                    + '<th style="min-width:220px;">Title</th>'
                    + '<th>Summary</th>'
                    + '<th style="min-width:90px;">Date</th>'
                    + '</tr>';
            }
        }

        var rows = items.map(function (item) {
            var titleText  = esc(item.title || '');
            var titleInner = item.link
                ? '<a href="' + esc(item.link) + '" target="_blank" rel="noopener" '
                  + 'style="color:#0e7490;text-decoration:none;">' + titleText + '</a>'
                : titleText;

            // Image icon — shown only when this specific item has an image
            var imgIcon = '';
            if (item.image) {
                imgIcon = '<button class="dr-img-icon-btn" '
                    + 'data-img="' + esc(item.image) + '" '
                    + 'data-title="' + esc(item.title || '') + '" '
                    + 'data-link="' + esc(item.link || '') + '" '
                    + 'title="View image" '
                    + 'style="margin-left:7px;background:none;border:none;cursor:pointer;'
                    + 'padding:0 2px;vertical-align:middle;font-size:0.95rem;line-height:1;'
                    + 'color:#0e7490;opacity:0.75;transition:opacity 0.15s;" '
                    + 'onmouseover="this.style.opacity=\'1\'" onmouseout="this.style.opacity=\'0.75\'">🖼</button>';
            }

            var sumCell  = esc(item.summary || '');
            var dateCell = esc(fmtDate(item.published) || '');

            return '<tr>'
                + '<td style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px;">'
                +   titleInner + imgIcon
                + '</td>'
                + '<td style="color:#555;font-size:0.79rem;">' + sumCell + '</td>'
                + '<td style="white-space:nowrap;color:#888;">' + dateCell + '</td>'
                + '</tr>';
        });

        tbody.innerHTML = rows.join('');

        // Event delegation for image icon clicks
        tbody._drImgHandler && tbody.removeEventListener('click', tbody._drImgHandler);
        tbody._drImgHandler = function (e) {
            var btn = e.target.closest('.dr-img-icon-btn');
            if (!btn) return;
            openLightbox(
                btn.getAttribute('data-img'),
                btn.getAttribute('data-title'),
                btn.getAttribute('data-link')
            );
        };
        tbody.addEventListener('click', tbody._drImgHandler);
    }

    // ── Per-channel badge update ──────────────────────────────────────────────

    function updateBadge(key, result) {
        var el = byId('dr-badge-' + key);
        if (!el) return;
        if (result.status === 'ok') {
            el.textContent      = result.item_count;
            el.style.background = '#d1fae5';
            el.style.color      = '#065f46';
        } else {
            el.textContent      = '!';
            el.style.background = '#fee2e2';
            el.style.color      = '#991b1b';
        }
        el.style.display = 'inline-block';
    }

    // ── Fetch a single channel ────────────────────────────────────────────────

    function fetchChannel(key, label, onDone) {
        fetch('/api/channel-data/' + encodeURIComponent(key))
            .then(function (r) { return r.json(); })
            .then(function (result) {
                _cache[key] = result;
                updateBadge(key, result);
                if (onDone) onDone(result);
            })
            .catch(function (err) {
                var errResult = {channel: key, label: label, source: '', status: 'error',
                                 error: String(err), item_count: 0, items: [],
                                 fetched_at: new Date().toISOString()};
                _cache[key] = errResult;
                updateBadge(key, errResult);
                if (onDone) onDone(errResult);
            });
    }

    // ── Public: select + display a channel ───────────────────────────────────

    window.drSelectChannel = function (key) {
        _activeKey = key;
        setActiveStyle(key);

        var label = key;
        for (var i = 0; i < _groups.length; i++) {
            var chs = _groups[i].channels;
            for (var j = 0; j < chs.length; j++) {
                if (chs[j][0] === key) { label = chs[j][1]; break; }
            }
        }

        if (_cache[key]) {
            renderResult(_cache[key]);
            return;
        }
        showLoading(label);
        fetchChannel(key, label, function (result) {
            if (_activeKey === key) renderResult(result);
        });
    };

    // ── Fetch All ─────────────────────────────────────────────────────────────

    function fetchAll() {
        var allChannels = [];
        _groups.forEach(function (g) {
            g.channels.forEach(function (ch) { allChannels.push(ch); });
        });

        var total   = allChannels.length;
        var done    = 0;
        var summary = byId('dr-status-summary');

        function progress() {
            done++;
            if (summary) summary.textContent = 'Fetching… ' + done + ' / ' + total;
            if (done >= total && summary) {
                var ok   = Object.values(_cache).filter(function (r) { return r.status === 'ok'; }).length;
                var fail = total - ok;
                summary.textContent = ok + ' OK' + (fail ? '  ·  ' + fail + ' failed' : '');
                if (_activeKey && _cache[_activeKey]) renderResult(_cache[_activeKey]);
            }
        }

        _cache = {};
        if (summary) summary.textContent = 'Fetching 0 / ' + total;

        var queue   = allChannels.slice();
        var running = 0;
        var MAX     = 4;

        function next() {
            while (running < MAX && queue.length) {
                var ch  = queue.shift();
                var key = ch[0], lbl = ch[1];
                running++;
                fetchChannel(key, lbl, function () {
                    running--;
                    progress();
                    next();
                });
            }
        }
        next();
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    function init() {
        if (_initialized) return;
        _initialized = true;

        ensureLightbox();

        fetch('/api/channel-data/groups')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _groups = data.groups || [];
                buildSidebar(_groups);
            })
            .catch(function (err) {
                var s = byId('dr-sidebar');
                if (s) s.innerHTML = '<p style="color:#991b1b;font-size:0.82rem;">Failed to load channels: ' + esc(String(err)) + '</p>';
            });

        var fetchAllBtn = byId('dr-fetch-all-btn');
        if (fetchAllBtn) fetchAllBtn.addEventListener('click', fetchAll);
    }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.asset-manager-subtab');
        if (btn && btn.getAttribute('data-department') === 'data_retrieval') {
            setTimeout(init, 50);
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            var panel = document.getElementById('asset-manager-content-data_retrieval');
            if (panel && panel.style.display !== 'none') init();
        });
    } else {
        var panel = document.getElementById('asset-manager-content-data_retrieval');
        if (panel && panel.style.display !== 'none') init();
    }

})();
