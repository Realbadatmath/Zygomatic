// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard Command Center – Alt+Ctrl+Home opens chat; executes commands globally.
 */
(function () {
    'use strict';

    var CMD_HOTKEY = { alt: true, ctrl: true, key: 'Home' };
    var userName = (typeof window.DASHBOARD_USER_NAME !== 'undefined' && window.DASHBOARD_USER_NAME) ? window.DASHBOARD_USER_NAME : ((typeof window.DASHBOARD_USER_ID !== 'undefined' && window.DASHBOARD_USER_ID) ? window.DASHBOARD_USER_ID : 'User');

    var COMMAND_LEGEND = [
        { cmd: 'gridview', desc: 'Opens latest gridview line data; shows dotted overlay over elements.' },
        { cmd: 'gridview reset', desc: 'Resets current gridview lines, loads all new lines and data, sets new gridlines.' },
        { cmd: 'lock gridview', desc: 'Disables gridview function.' },
        { cmd: 'reveal gridview text', desc: 'Displays original text in cells and objects during gridview.' },
        { cmd: 'lock text', desc: 'Locks the text in all buttons so it cannot be selected or copied.' },
        { cmd: 'unlock text', desc: 'Unlocks all text in all buttons so it can be selected and copied.' },
        { cmd: 'element', desc: 'Shows by what name element is recognized in/by system; name shown when hovering over an element.' },
        { cmd: 'lock element', desc: 'Locks every element; hovering no longer shows any information except original set information.' },
        { cmd: 'button function', desc: 'When hovering over any button or element it shows its function inside the system.' },
        { cmd: 'lock button function', desc: 'Disables hovering over buttons and elements function.' },
        { cmd: 'colored lines', desc: 'If any charts are present with lines, hovering over these lines reveals their color code and how recognized by the system.' },
        { cmd: 'lock colored lines', desc: 'Disables the colored lines function.' },
        { cmd: 'flag element', desc: 'Allows right-click on any object/element to flag it. Saves flagged elements to Flagged.json.' },
        { cmd: 'disable flag element', desc: 'Disables the flag element function.' },
        { cmd: 'id', desc: 'Shows all unique IDs for each element/cell/box/agent etc (hides all other text).' },
        { cmd: 'lock id', desc: 'Disables ID display mode.' },
        { cmd: 'l', desc: 'Opens list with all commands; hover shows function, double-click types and sends command.' },
        { cmd: 'legende', desc: 'Opens list with all commands; hover shows function, double-click types and sends command.' },
        { cmd: 'legend', desc: 'Opens list with all commands; hover shows function, double-click types and sends command.' },
        { cmd: 'legenda', desc: 'Opens list with all commands; hover shows function, double-click types and sends command.' },
        { cmd: 'close cm', desc: 'Closes the command center chat box.' },
        { cmd: 'close command', desc: 'Closes the command center chat box.' },
        { cmd: 'bp', desc: 'Creates a full dashboard blueprint (routes, agents, roles, buttons, functions) and saves to Zygomatic Origin/Blueprint.' }
    ];

    var state = {
        gridview: false,
        gridviewLocked: false,
        gridviewRevealText: false,
        textLocked: false,
        elementMode: false,
        elementLocked: false,
        buttonFunctionMode: false,
        buttonFunctionLocked: false,
        coloredLinesMode: false,
        coloredLinesLocked: false,
        flagElementMode: false,
        idMode: false,
        gridviewLines: []
    };

    var overlay, dialog, minimizedTab, chatLog, inputEl, minimizeBtn, legendPanel, legendListEl, minimizedLegendTab;

    var CMD_TOGGLE_OFF = {
        'gridview': 'lock gridview',
        'lock gridview': 'gridview reset',
        'lock text': 'unlock text',
        'element': 'lock element',
        'lock element': 'element',
        'button function': 'lock button function',
        'lock button function': 'button function',
        'colored lines': 'lock colored lines',
        'lock colored lines': 'colored lines',
        'flag element': 'disable flag element',
        'disable flag element': 'flag element',
        'id': 'lock id',
        'lock id': 'id'
    };

    function byId(id) { return document.getElementById(id); }

    function isCommandActive(cmd) {
        switch (cmd) {
            case 'gridview': return state.gridview && !state.gridviewLocked;
            case 'lock gridview': return state.gridviewLocked;
            case 'reveal gridview text': return state.gridviewRevealText;
            case 'lock text': return state.textLocked;
            case 'element': return state.elementMode && !state.elementLocked;
            case 'lock element': return state.elementLocked;
            case 'button function': return state.buttonFunctionMode && !state.buttonFunctionLocked;
            case 'lock button function': return state.buttonFunctionLocked;
            case 'colored lines': return state.coloredLinesMode && !state.coloredLinesLocked;
            case 'lock colored lines': return state.coloredLinesLocked;
            case 'flag element': return state.flagElementMode;
            case 'disable flag element': return !state.flagElementMode;
            case 'id': return state.idMode;
            case 'lock id': return false;
            default: return false;
        }
    }

    function getToggleOffCommand(cmd) { return CMD_TOGGLE_OFF[cmd] || null; }

    function refreshLegendHighlights() {
        if (!legendListEl) return;
        Array.prototype.forEach.call(legendListEl.querySelectorAll('.command-center-legend-item'), function (li) {
            var cmd = li.getAttribute('data-cmd');
            li.classList.toggle('command-center-legend-item-active', isCommandActive(cmd));
        });
    }

    function showLegend() {
        createOverlay();
        if (!legendPanel) {
            legendPanel = document.createElement('div');
            legendPanel.id = 'command-center-legend-panel';
            legendPanel.className = 'command-center-legend-panel command-center-legend-floating';
            legendPanel.innerHTML = '<div class="command-center-legend-header"><span class="command-center-legend-title">Commands</span><button type="button" class="command-center-legend-minimize" aria-label="Minimize legend" title="Minimize">&minus;</button></div><div class="command-center-legend-list" id="command-center-legend-list"></div>';
            document.body.appendChild(legendPanel);
            legendListEl = byId('command-center-legend-list');
            if (legendListEl) {
                COMMAND_LEGEND.forEach(function (item) {
                    var li = document.createElement('div');
                    li.className = 'command-center-legend-item';
                    li.setAttribute('data-cmd', item.cmd);
                    li.textContent = item.cmd;
                    li.title = item.desc;
                    li.addEventListener('mouseenter', function () {
                        var tip = byId('command-center-legend-tooltip');
                        if (tip) tip.remove();
                        tip = document.createElement('div');
                        tip.id = 'command-center-legend-tooltip';
                        tip.className = 'command-center-legend-tooltip';
                        tip.textContent = item.desc;
                        document.body.appendChild(tip);
                        var rect = li.getBoundingClientRect();
                        tip.style.left = (rect.right + 8) + 'px';
                        tip.style.top = rect.top + 'px';
                    });
                    li.addEventListener('mouseleave', function () {
                        var tip = byId('command-center-legend-tooltip');
                        if (tip) tip.remove();
                    });
                    li.addEventListener('dblclick', function () {
                        var toRun = isCommandActive(item.cmd) ? getToggleOffCommand(item.cmd) : item.cmd;
                        if (toRun && inputEl) {
                            inputEl.value = toRun;
                            executeCommand(toRun);
                            inputEl.value = '';
                        }
                    });
                    legendListEl.appendChild(li);
                });
            }
            minimizedLegendTab = document.createElement('div');
            minimizedLegendTab.id = 'command-center-legend-tab';
            minimizedLegendTab.className = 'dashboard-command-center-tab command-center-legend-tab';
            minimizedLegendTab.innerHTML = '<span class="dashboard-command-center-tab-label">Commands</span>';
            minimizedLegendTab.style.display = 'none';
            document.body.appendChild(minimizedLegendTab);
            initMinimizedTabDrag(minimizedLegendTab, expandLegend);
            var minLegendBtn = legendPanel.querySelector('.command-center-legend-minimize');
            if (minLegendBtn) minLegendBtn.onclick = minimizeLegend;
            var header = legendPanel.querySelector('.command-center-legend-header');
            if (header) initLegendDrag(header);
        }
        legendPanel.style.display = 'flex';
        refreshLegendHighlights();
    }

    function initLegendDrag(header) {
        var minBtn = header.querySelector('.command-center-legend-minimize');
        var startX, startY, startLeft, startTop;
        header.addEventListener('mousedown', function (e) {
            if (minBtn && minBtn.contains(e.target)) return;
            e.preventDefault();
            startX = e.clientX;
            startY = e.clientY;
            var rect = legendPanel.getBoundingClientRect();
            startLeft = rect.left;
            startTop = rect.top;
            document.body.style.cursor = 'grabbing';
            document.body.style.userSelect = 'none';
            function onMove(e2) {
                var dx = e2.clientX - startX;
                var dy = e2.clientY - startY;
                legendPanel.style.left = (startLeft + dx) + 'px';
                legendPanel.style.top = (startTop + dy) + 'px';
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

    function minimizeLegend() {
        if (legendPanel) legendPanel.style.display = 'none';
        var tip = byId('command-center-legend-tooltip');
        if (tip) tip.remove();
        if (minimizedLegendTab) {
            minimizedLegendTab.style.left = '';
            minimizedLegendTab.style.transform = '';
            minimizedLegendTab.style.display = 'flex';
        }
    }

    function expandLegend() {
        if (legendPanel) legendPanel.style.display = 'flex';
        if (minimizedLegendTab) minimizedLegendTab.style.display = 'none';
        refreshLegendHighlights();
    }

    function hideLegend() {
        if (legendPanel) legendPanel.style.display = 'none';
        if (minimizedLegendTab) minimizedLegendTab.style.display = 'none';
        var tip = byId('command-center-legend-tooltip');
        if (tip) tip.remove();
    }

    function appendMessage(text, isSystem) {
        if (!chatLog) return;
        var div = document.createElement('div');
        div.className = 'command-center-msg' + (isSystem ? ' command-center-system' : '');
        div.textContent = text;
        chatLog.appendChild(div);
        chatLog.scrollTop = chatLog.scrollHeight;
    }

    function centerDialog() {
        if (!dialog) return;
        var w = Math.min(480, window.innerWidth - 40);
        var h = Math.min(400, window.innerHeight - 80);
        dialog.style.left = (window.innerWidth / 2 - w / 2) + 'px';
        dialog.style.top = (window.innerHeight / 2 - h / 2) + 'px';
    }

    function minimizeChat() {
        if (overlay) overlay.style.display = 'none';
        if (dialog) dialog.style.display = 'none';
        if (minimizedTab) {
            minimizedTab.style.left = '';
            minimizedTab.style.transform = '';
            minimizedTab.style.display = 'flex';
        }
    }

    function expandChat() {
        if (overlay) overlay.style.display = 'flex';
        if (dialog) dialog.style.display = 'flex';
        if (minimizedTab) minimizedTab.style.display = 'none';
        if (inputEl) { inputEl.focus(); inputEl.value = ''; }
    }

    function initDialogDrag(header) {
        var minBtn = header.querySelector('.dashboard-command-center-minimize');
        var startX, startY, startLeft, startTop;
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
                moved = true;
                var dx = e2.clientX - startX;
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

    function createOverlay() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.id = 'dashboard-command-center-overlay';
        overlay.className = 'dashboard-command-center-overlay';
        overlay.innerHTML = '';
        document.body.appendChild(overlay);

        dialog = document.createElement('div');
        dialog.id = 'dashboard-command-center-dialog';
        dialog.className = 'dashboard-command-center-dialog';
        dialog.innerHTML =
            '<div class="dashboard-command-center-header">' +
            '<h3 class="dashboard-command-center-title">Command Center</h3>' +
            '<div class="dashboard-command-center-header-btns">' +
            '<button type="button" class="dashboard-command-center-minimize" id="command-center-minimize" aria-label="Minimize" title="Minimize">&minus;</button>' +
            '</div></div>' +
            '<div class="dashboard-command-center-log" id="command-center-log"></div>' +
            '<div class="dashboard-command-center-input-wrap">' +
            '<input type="text" id="command-center-input" class="dashboard-command-center-input" placeholder="Type command and press Enter..." autocomplete="off">' +
            '</div>';
        document.body.appendChild(dialog);

        minimizedTab = document.createElement('div');
        minimizedTab.id = 'dashboard-command-center-tab';
        minimizedTab.className = 'dashboard-command-center-tab';
        minimizedTab.innerHTML = '<span class="dashboard-command-center-tab-label">Command Center</span>';
        minimizedTab.style.display = 'none';
        document.body.appendChild(minimizedTab);

        chatLog = byId('command-center-log');
        inputEl = byId('command-center-input');
        minimizeBtn = byId('command-center-minimize');

        var style = document.createElement('style');
        style.textContent =
            '.dashboard-command-center-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9000;display:flex;align-items:center;justify-content:center;padding:20px;}' +
            '.dashboard-command-center-dialog{position:fixed;z-index:9001;background:#f5f5f7;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.25);width:100%;max-width:480px;max-height:calc(70vh / var(--ui-zoom,1));min-width:360px;display:flex;flex-direction:column;overflow:hidden;}' +
            '.dashboard-command-center-tab{position:fixed;bottom:0;transform:translateX(-50%);z-index:99999;background:linear-gradient(140deg,#e8ecf7,#b8c5e0);border:1px solid #7a8bb3;border-bottom:none;border-radius:10px 10px 0 0;padding:10px 24px;cursor:pointer;font-weight:600;font-size:14px;color:#0d1117!important;display:flex;align-items:center;gap:8px;box-shadow:0 -4px 12px rgba(0,0,0,0.15);visibility:visible!important;opacity:1!important;pointer-events:auto!important;}' +
            '#command-center-legend-tab{left:calc(50% - 195px)!important;}' +
            '#dashboard-command-center-tab{left:calc(50% + 15px)!important;}' +
            '.dashboard-command-center-tab:hover{background:linear-gradient(140deg,#dde3f4,#a8b8e0);}' +
            '.dashboard-command-center-tab .dashboard-command-center-tab-label{color:#0d1117!important;}' +
            '.dashboard-command-center-header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;background:linear-gradient(140deg,#e8ecf7,#b8c5e0 50%,#7a8bb3);color:#0d1117;font-weight:600;cursor:grab;user-select:none;}' +
            '.dashboard-command-center-header:active{cursor:grabbing;}' +
            '.dashboard-command-center-header-btns{display:flex;gap:4px;align-items:center;}' +
            '.dashboard-command-center-minimize{background:#7a8bb3;border:none;border-radius:4px;color:#fff;font-size:18px;line-height:1;width:28px;height:28px;cursor:pointer;display:flex;align-items:center;justify-content:center;}' +
            '.dashboard-command-center-minimize:hover{background:#6a7ba3;}' +
            '.command-center-legend-panel{display:flex;flex-direction:column;width:220px;min-width:220px;background:#fafafa;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.15);border-radius:8px;border:1px solid #ddd;}' +
            '.command-center-legend-panel.command-center-legend-floating{position:fixed;z-index:9010;top:80px;left:50px;}' +
            '.command-center-legend-header{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;font-weight:600;font-size:13px;border-bottom:1px solid #ddd;background:#eee;cursor:grab;user-select:none;}' +
            '.command-center-legend-header:active{cursor:grabbing;}' +
            '.command-center-legend-title{flex:1;}' +
            '.command-center-legend-minimize,.command-center-legend-close{flex-shrink:0;background:#ddd;border:1px solid #bbb;border-radius:4px;font-size:16px;line-height:1;width:24px;height:24px;cursor:pointer;color:#444;padding:0;display:flex;align-items:center;justify-content:center;}' +
            '.command-center-legend-minimize:hover,.command-center-legend-close:hover{background:#ccc;color:#000;}' +
            '.command-center-legend-list{flex:1;overflow-y:auto;padding:8px 0;}' +
            '.command-center-legend-item{padding:8px 12px;font-size:12px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}' +
            '.command-center-legend-item:hover{background:#e8ecf7;}' +
            '.command-center-legend-item-active{background:#c7d2fe;font-weight:600;}' +
            '.command-center-legend-tooltip{position:fixed;max-width:260px;padding:10px 12px;background:#333;color:#fff;font-size:12px;line-height:1.4;border-radius:8px;z-index:9010;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,0.3);}' +
            '.dashboard-command-center-log{flex:1;min-height:180px;max-height:320px;overflow-y:auto;padding:16px;font-size:14px;line-height:1.5;}' +
            '.command-center-msg{margin-bottom:8px;color:#333;}' +
            '.command-center-system{color:#555;font-style:italic;}' +
            '.dashboard-command-center-input-wrap{padding:12px 16px;border-top:1px solid #ddd;}' +
            '.dashboard-command-center-input{width:100%;padding:10px 14px;border:1px solid #ccc;border-radius:8px;font-size:14px;box-sizing:border-box;}';
        document.head.appendChild(style);

        if (minimizeBtn) minimizeBtn.onclick = minimizeChat;
        if (minimizedTab) initMinimizedTabDrag(minimizedTab, expandChat);
        overlay.onclick = function (e) { if (e.target === overlay) minimizeChat(); };
        inputEl.onkeydown = function (e) {
            if (e.key === 'Enter') { e.preventDefault(); executeCommand(inputEl.value.trim()); inputEl.value = ''; }
            if (e.key === 'Escape') closeCommandCenter();
        };
        var header = dialog.querySelector('.dashboard-command-center-header');
        if (header) initDialogDrag(header);
        appendMessage('Hello ' + userName + ', How Can I Assist You?', true);
    }

    function openCommandCenter() {
        createOverlay();
        overlay.style.display = 'flex';
        overlay.classList.add('command-center-visible');
        dialog.style.display = 'flex';
        minimizedTab.style.display = 'none';
        centerDialog();
        if (inputEl) { inputEl.focus(); inputEl.value = ''; }
    }

    function closeCommandCenter() {
        if (overlay) {
            overlay.style.display = 'none';
            overlay.classList.remove('command-center-visible');
        }
        if (dialog) dialog.style.display = 'none';
        if (minimizedTab) minimizedTab.style.display = 'none';
    }

    function normalizeCmd(s) {
        return (s || '').toLowerCase().replace(/\s+/g, ' ').trim();
    }

    function matchCmd(input, cmd) {
        var n = normalizeCmd(input);
        var c = normalizeCmd(cmd);
        if (n === c) return true;
        if (c.indexOf(' ') >= 0) return n === c;
        var parts = n.split(' ');
        return parts[0] === c || n.indexOf(c) === 0;
    }

    function runGridview() {
        state.gridview = true;
        state.gridviewLocked = false;
        document.body.classList.add('command-center-gridview-active');
        if (state.gridviewRevealText) document.body.classList.add('command-center-reveal-gridview-text');
        renderGridview();
    }

    function parsePx(val) { return val ? parseInt(String(val).replace(/[^0-9.-]/g, ''), 10) || 0 : 0; }

    /** When element bounds are much larger than its visible content, return a tighter rect (union of children). */
    function getTightRect(el, fullRect) {
        var children = el.children;
        if (!children || children.length === 0) return fullRect;
        var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        var hasValid = false;
        for (var i = 0; i < children.length; i++) {
            var cr = children[i].getBoundingClientRect();
            if (cr.width < 2 || cr.height < 2) continue;
            hasValid = true;
            minX = Math.min(minX, cr.left);
            minY = Math.min(minY, cr.top);
            maxX = Math.max(maxX, cr.right);
            maxY = Math.max(maxY, cr.bottom);
        }
        if (!hasValid) return fullRect;
        var contentW = maxX - minX;
        var contentH = maxY - minY;
        var elemW = fullRect.width;
        var elemH = fullRect.height;
        if (elemW < 2 || elemH < 2) return fullRect;
        var contentArea = contentW * contentH;
        var elemArea = elemW * elemH;
        if (contentArea < elemArea * 0.5 || contentW < elemW * 0.7 || contentH < elemH * 0.7) {
            return { left: minX, top: minY, right: maxX, bottom: maxY, width: contentW, height: contentH };
        }
        return fullRect;
    }

    function showCellDialog(name, x, y, w, h, padding, margin, border) {
        var existing = document.getElementById('command-center-cell-dialog');
        if (existing) existing.remove();
        var d = document.createElement('div');
        d.id = 'command-center-cell-dialog';
        d.className = 'command-center-cell-dialog';
        d.innerHTML =
            '<div class="command-center-cell-dialog-header"><span>Cell Info</span><button type="button" class="command-center-cell-dialog-close" aria-label="Close">&times;</button></div>' +
            '<div class="command-center-cell-dialog-body">' +
            '<p><strong>Name:</strong> ' + (name || '-') + '</p>' +
            '<p><strong>Position:</strong> ' + Math.round(x) + ', ' + Math.round(y) + '</p>' +
            '<p><strong>Size:</strong> ' + Math.round(w) + ' &times; ' + Math.round(h) + ' px</p>' +
            (padding ? '<p><strong>Padding:</strong> ' + padding + '</p>' : '') +
            (margin ? '<p><strong>Margin:</strong> ' + margin + '</p>' : '') +
            (border ? '<p><strong>Border:</strong> ' + border + '</p>' : '') +
            '</div>';
        d.style.cssText = 'position:fixed;left:' + Math.min(x + 20, window.innerWidth - 280) + 'px;top:' + Math.min(y + 20, window.innerHeight - 200) + 'px;';
        document.body.appendChild(d);
        d.querySelector('.command-center-cell-dialog-close').onclick = function () { d.remove(); };
        setTimeout(function () {
            document.addEventListener('click', function onClick(e) {
                if (!d.parentNode) { document.removeEventListener('click', onClick); return; }
                if (!d.contains(e.target)) { d.remove(); document.removeEventListener('click', onClick); }
            });
        }, 0);
    }

    function showGapDialog(gap, name1, name2, x, y) {
        var existing = document.getElementById('command-center-cell-dialog');
        if (existing) existing.remove();
        var d = document.createElement('div');
        d.id = 'command-center-cell-dialog';
        d.className = 'command-center-cell-dialog';
        d.innerHTML =
            '<div class="command-center-cell-dialog-header"><span>Gap Info</span><button type="button" class="command-center-cell-dialog-close" aria-label="Close">&times;</button></div>' +
            '<div class="command-center-cell-dialog-body">' +
            '<p><strong>Gap:</strong> ' + gap + ' px</p>' +
            '<p><strong>Between:</strong></p>' +
            '<p style="margin-left:12px;">' + (name1 || '-') + '</p>' +
            '<p style="margin-left:12px;">' + (name2 || '-') + '</p>' +
            '</div>';
        d.style.cssText = 'position:fixed;left:' + Math.min(x + 20, window.innerWidth - 280) + 'px;top:' + Math.min(y + 20, window.innerHeight - 200) + 'px;';
        document.body.appendChild(d);
        d.querySelector('.command-center-cell-dialog-close').onclick = function () { d.remove(); };
        setTimeout(function () {
            document.addEventListener('click', function onClick(e) {
                if (!d.parentNode) { document.removeEventListener('click', onClick); return; }
                if (!d.contains(e.target)) { d.remove(); document.removeEventListener('click', onClick); }
            });
        }, 0);
    }

    /** When a modal covers the page (e.g. Security Diagrams expanded), restrict gridview to that modal so we only see its elements. */
    function getGridviewRoot() {
        var modal = document.getElementById('security-diagrams-modal');
        var dialog = document.getElementById('security-diagrams-dialog') || (modal && modal.querySelector('.security-diagrams-dialog'));
        if (modal && modal.classList.contains('security-diagrams-open')) {
            var cs = window.getComputedStyle(modal);
            if (cs.display !== 'none' && cs.visibility !== 'hidden') {
                return dialog && dialog.classList.contains('security-diagrams-fullscreen') ? dialog : modal;
            }
        }
        if (dialog && dialog.classList.contains('security-diagrams-fullscreen')) {
            var dcs = window.getComputedStyle(dialog);
            if (dcs.display !== 'none' && dcs.visibility !== 'hidden') {
                return dialog;
            }
        }
        var overlay = document.getElementById('dashboard-command-center-overlay');
        if (overlay) {
            var ocs = window.getComputedStyle(overlay);
            if (ocs.display !== 'none' && ocs.visibility !== 'hidden') {
                return overlay;
            }
        }
        return document.body;
    }

    function renderGridview() {
        if (state.gridviewLocked || !state.gridview) return;
        var container = document.getElementById('dashboard-command-center-gridview-layer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'dashboard-command-center-gridview-layer';
            container.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:8999;';
            document.body.appendChild(container);
        }
        container.innerHTML = '';
        container.style.pointerEvents = 'auto';
        if (!state.gridview) return;

        var vw = window.innerWidth;
        var vh = window.innerHeight;
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', vw);
        svg.setAttribute('height', vh);
        svg.setAttribute('viewBox', '0 0 ' + vw + ' ' + vh);
        svg.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:8998;';
        container.appendChild(svg);

        var root = getGridviewRoot();
        var els = [];
        var nodes = [root].concat([].slice.call(root.querySelectorAll('*')));
        var coveringRoot = null;
        var secModal = document.getElementById('security-diagrams-modal');
        var secDialog = document.getElementById('security-diagrams-dialog') || (secModal && secModal.querySelector('.security-diagrams-dialog'));
        if (root === document.body) {
            if (secDialog && secDialog.classList.contains('security-diagrams-fullscreen')) {
                var dcs = window.getComputedStyle(secDialog);
                if (dcs.display !== 'none' && dcs.visibility !== 'hidden') coveringRoot = secDialog;
            } else if (secModal && secModal.classList.contains('security-diagrams-open')) {
                var mcs = window.getComputedStyle(secModal);
                if (mcs.display !== 'none' && mcs.visibility !== 'hidden') coveringRoot = secModal;
            }
        }
        nodes.forEach(function (el) {
            if (el.id === 'dashboard-command-center-gridview-layer' || el.id === 'dashboard-command-center-overlay' || el.id === 'command-center-cell-dialog' || el.id === 'command-center-legend-panel') return;
            if (coveringRoot && !coveringRoot.contains(el)) return;
            var r = el.getBoundingClientRect();
            r = getTightRect(el, r);
            if (r.width < 1 && r.height < 1) return;
            var cs = window.getComputedStyle(el);
            var pt = parsePx(cs.paddingTop);
            var pr = parsePx(cs.paddingRight);
            var pb = parsePx(cs.paddingBottom);
            var pl = parsePx(cs.paddingLeft);
            var mt = parsePx(cs.marginTop);
            var mr = parsePx(cs.marginRight);
            var mb = parsePx(cs.marginBottom);
            var ml = parsePx(cs.marginLeft);
            var bt = parsePx(cs.borderTopWidth);
            var br = parsePx(cs.borderRightWidth);
            var bb = parsePx(cs.borderBottomWidth);
            var bl = parsePx(cs.borderLeftWidth);
            var name = el.tagName + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + (el.className.split(' ')[0] || '') : '');
            els.push({ el: el, r: r, name: name, pt: pt, pr: pr, pb: pb, pl: pl, mt: mt, mr: mr, mb: mb, ml: ml, bt: bt, br: br, bb: bb, bl: bl });
        });

        els.forEach(function (d) {
            var r = d.r;
            var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            var outer = 'M' + r.left + ',' + r.top + ' L' + (r.left + r.width) + ',' + r.top + ' L' + (r.left + r.width) + ',' + (r.top + r.height) + ' L' + r.left + ',' + (r.top + r.height) + ' Z';
            path.setAttribute('d', outer);
            path.setAttribute('stroke', '#667eea');
            path.setAttribute('stroke-width', '1');
            path.setAttribute('fill', 'none');
            path.setAttribute('pointer-events', 'auto');
            path.style.cursor = 'pointer';
            path.onclick = function (e) {
                e.preventDefault();
                e.stopPropagation();
                var pad = (d.pt || d.pr || d.pb || d.pl) ? (d.pt + ' ' + d.pr + ' ' + d.pb + ' ' + d.pl + ' px') : null;
                var mar = (d.mt || d.mr || d.mb || d.ml) ? (d.mt + ' ' + d.mr + ' ' + d.mb + ' ' + d.ml + ' px') : null;
                var bor = (d.bt || d.br || d.bb || d.bl) ? (d.bt + ' ' + d.br + ' ' + d.bb + ' ' + d.bl + ' px') : null;
                showCellDialog(d.name, r.left, r.top, r.width, r.height, pad, mar, bor);
            };
            svg.appendChild(path);

            var innerLeft = r.left + d.bl + d.pl;
            var innerTop = r.top + d.bt + d.pt;
            var innerRight = r.right - d.br - d.pr;
            var innerBottom = r.bottom - d.bb - d.pb;
            if (innerRight > innerLeft && innerBottom > innerTop) {
                var innerPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                innerPath.setAttribute('d', 'M' + innerLeft + ',' + innerTop + ' L' + innerRight + ',' + innerTop + ' L' + innerRight + ',' + innerBottom + ' L' + innerLeft + ',' + innerBottom + ' Z');
                innerPath.setAttribute('stroke', '#9f7aea');
                innerPath.setAttribute('stroke-width', '1');
                innerPath.setAttribute('fill', 'none');
                innerPath.setAttribute('pointer-events', 'auto');
                innerPath.style.cursor = 'pointer';
                innerPath.onclick = function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var pad = (d.pt || d.pr || d.pb || d.pl) ? (d.pt + ' ' + d.pr + ' ' + d.pb + ' ' + d.pl + ' px') : null;
                    var mar = (d.mt || d.mr || d.mb || d.ml) ? (d.mt + ' ' + d.mr + ' ' + d.mb + ' ' + d.ml + ' px') : null;
                    var bor = (d.bt || d.br || d.bb || d.bl) ? (d.bt + ' ' + d.br + ' ' + d.bb + ' ' + d.bl + ' px') : null;
                    showCellDialog(d.name, r.left, r.top, r.width, r.height, pad, mar, bor);
                };
                svg.appendChild(innerPath);
            }

            if (d.pt > 0 || d.pr > 0 || d.pb > 0 || d.pl > 0) {
                var padStr = d.pt + ' ' + d.pr + ' ' + d.pb + ' ' + d.pl;
                var label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                label.setAttribute('x', r.left + d.bl + d.pl / 2);
                label.setAttribute('y', r.top + d.bt + d.pt / 2 - 2);
                label.setAttribute('fill', '#764ba2');
                label.setAttribute('font-size', '9');
                label.setAttribute('pointer-events', 'none');
                label.textContent = 'pad:' + padStr;
                svg.appendChild(label);
            }
        });

        var distCount = 0;
        els.forEach(function (d, i) {
            els.forEach(function (d2, j) {
                if (j <= i || distCount >= 80) return;
                var r = d.r;
                var r2 = d2.r;
                var overlapX = Math.min(r.right, r2.right) - Math.max(r.left, r2.left);
                var overlapY = Math.min(r.bottom, r2.bottom) - Math.max(r.top, r2.top);
                var gap = 0;
                var isVert = false;
                if (overlapX > 20 && Math.abs(r.bottom - r2.top) < 6) {
                    gap = r2.top - r.bottom;
                    isVert = true;
                } else if (overlapX > 20 && Math.abs(r.top - r2.bottom) < 6) {
                    gap = r.top - r2.bottom;
                    isVert = true;
                } else if (overlapY > 20 && Math.abs(r.right - r2.left) < 6) {
                    gap = r2.left - r.right;
                } else if (overlapY > 20 && Math.abs(r.left - r2.right) < 6) {
                    gap = r.left - r2.right;
                }
                if (gap > 1 && gap < 80) {
                    var mx = (r.left + r.right + r2.left + r2.right) / 4;
                    var my = (r.top + r.bottom + r2.top + r2.bottom) / 4;
                    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                    if (isVert) {
                        line.setAttribute('x1', mx);
                        line.setAttribute('y1', Math.min(r.bottom, r2.bottom));
                        line.setAttribute('x2', mx);
                        line.setAttribute('y2', Math.max(r.top, r2.top));
                    } else {
                        line.setAttribute('x1', Math.min(r.right, r2.right));
                        line.setAttribute('y1', my);
                        line.setAttribute('x2', Math.max(r.left, r2.left));
                        line.setAttribute('y2', my);
                    }
                    line.setAttribute('stroke', '#a78bfa');
                    line.setAttribute('stroke-width', '1');
                    g.appendChild(line);
                    var hitPad = 10;
                    var rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                    if (isVert) {
                        rect.setAttribute('x', mx - hitPad);
                        rect.setAttribute('y', Math.min(r.bottom, r2.bottom));
                        rect.setAttribute('width', hitPad * 2);
                        rect.setAttribute('height', Math.max(r.top, r2.top) - Math.min(r.bottom, r2.bottom));
                    } else {
                        rect.setAttribute('x', Math.min(r.right, r2.right));
                        rect.setAttribute('y', my - hitPad);
                        rect.setAttribute('width', Math.max(r.left, r2.left) - Math.min(r.right, r2.right));
                        rect.setAttribute('height', hitPad * 2);
                    }
                    rect.setAttribute('fill', 'transparent');
                    rect.setAttribute('pointer-events', 'auto');
                    rect.style.cursor = 'pointer';
                    rect.onclick = function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        showGapDialog(gap, d.name, d2.name, mx, my);
                    };
                    g.appendChild(rect);
                    svg.appendChild(g);
                    var lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    lbl.setAttribute('x', mx);
                    lbl.setAttribute('y', my - 4);
                    lbl.setAttribute('fill', '#7c3aed');
                    lbl.setAttribute('font-size', '9');
                    lbl.setAttribute('text-anchor', 'middle');
                    lbl.setAttribute('pointer-events', 'auto');
                    lbl.style.cursor = 'pointer';
                    lbl.textContent = gap + 'px';
                    lbl.onclick = function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        showGapDialog(gap, d.name, d2.name, mx, my);
                    };
                    svg.appendChild(lbl);
                    distCount++;
                }
            });
        });

        var dotWrap = document.createElement('div');
        dotWrap.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9000;';
        container.appendChild(dotWrap);
        els.forEach(function (d) {
            var r = d.r;
            var cx = r.left + r.width / 2;
            var cy = r.top + r.height / 2;
            var dot = document.createElement('div');
            dot.className = 'command-center-grid-dot';
            dot.style.cssText = 'position:fixed;left:' + (cx - 4) + 'px;top:' + (cy - 4) + 'px;width:8px;height:8px;background:#667eea;border-radius:50%;pointer-events:auto;cursor:pointer;z-index:9001;';
            dot.title = d.name + ' @ ' + Math.round(cx) + ',' + Math.round(cy);
            dot.onclick = function (e) {
                e.preventDefault();
                e.stopPropagation();
                var pad = (d.pt || d.pr || d.pb || d.pl) ? (d.pt + ' ' + d.pr + ' ' + d.pb + ' ' + d.pl + ' px') : null;
                var mar = (d.mt || d.mr || d.mb || d.ml) ? (d.mt + ' ' + d.mr + ' ' + d.mb + ' ' + d.ml + ' px') : null;
                var bor = (d.bt || d.br || d.bb || d.bl) ? (d.bt + ' ' + d.br + ' ' + d.bb + ' ' + d.bl + ' px') : null;
                showCellDialog(d.name, r.left, r.top, r.width, r.height, pad, mar, bor);
            };
            dotWrap.appendChild(dot);
        });
    }

    function runGridviewReset() {
        state.gridview = true;
        state.gridviewLocked = false;
        document.body.classList.add('command-center-gridview-active');
        if (state.gridviewRevealText) document.body.classList.add('command-center-reveal-gridview-text');
        var layer = document.getElementById('dashboard-command-center-gridview-layer');
        if (layer) layer.remove();
        renderGridview();
    }

    function runLockGridview() {
        state.gridview = false;
        state.gridviewLocked = true;
        document.body.classList.remove('command-center-gridview-active', 'command-center-reveal-gridview-text');
        var layer = document.getElementById('dashboard-command-center-gridview-layer');
        if (layer) layer.remove();
        var dlg = document.getElementById('command-center-cell-dialog');
        if (dlg) dlg.remove();
    }

    function runRevealGridviewText() {
        state.gridviewRevealText = true;
        document.body.classList.add('command-center-reveal-gridview-text');
    }

    function runLockText() {
        state.textLocked = true;
        document.body.classList.add('command-center-lock-text');
    }

    function runUnlockText() {
        state.textLocked = false;
        document.body.classList.remove('command-center-lock-text');
    }

    function runElementMode() {
        state.elementMode = true;
        state.elementLocked = false;
        document.body.classList.add('command-center-element-mode');
    }

    function runLockElement() {
        state.elementLocked = true;
        state.elementMode = false;
        document.body.classList.remove('command-center-element-mode');
    }

    function runButtonFunction() {
        state.buttonFunctionMode = true;
        state.buttonFunctionLocked = false;
        document.body.classList.add('command-center-button-function');
    }

    function runLockButtonFunction() {
        state.buttonFunctionLocked = true;
        state.buttonFunctionMode = false;
        document.body.classList.remove('command-center-button-function');
    }

    function runColoredLines() {
        state.coloredLinesMode = true;
        state.coloredLinesLocked = false;
        document.body.classList.add('command-center-colored-lines');
    }

    function runLockColoredLines() {
        state.coloredLinesLocked = true;
        state.coloredLinesMode = false;
        document.body.classList.remove('command-center-colored-lines');
    }

    function runFlagElement() {
        state.flagElementMode = true;
        document.body.classList.add('command-center-flag-element');
    }

    function runDisableFlagElement() {
        state.flagElementMode = false;
        document.body.classList.remove('command-center-flag-element');
    }

    function runIdMode() {
        state.idMode = true;
        document.body.classList.add('command-center-id-mode');
    }

    function executeCommand(raw) {
        if (!raw) return;
        var cmd = normalizeCmd(raw);
        var recognized = false;

        if (matchCmd(raw, 'gridview') && !matchCmd(raw, 'gridview reset') && !matchCmd(raw, 'lock gridview')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () {
                if (state.gridview && !state.gridviewLocked) {
                    runLockGridview();
                } else {
                    runGridview();
                }
                appendMessage('Command executed, Awaiting New Command', true);
            }, 50);
        } else if (matchCmd(raw, 'gridview reset')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () {
                runGridviewReset();
                appendMessage('Command executed, Awaiting New Command', true);
            }, 50);
        } else if (matchCmd(raw, 'lock gridview')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () {
                runLockGridview();
                appendMessage('Command executed, Awaiting New Command', true);
            }, 50);
        } else if (matchCmd(raw, 'reveal gridview text')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () {
                runRevealGridviewText();
                appendMessage('Command executed, Awaiting New Command', true);
            }, 50);
        } else if (matchCmd(raw, 'lock text')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runLockText(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'unlock text')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runUnlockText(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'element')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runElementMode(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'lock element')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runLockElement(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'button function')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runButtonFunction(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'lock button function')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runLockButtonFunction(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'colored lines')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runColoredLines(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'lock colored lines')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runLockColoredLines(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'flag element')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runFlagElement(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'disable flag element')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () { runDisableFlagElement(); appendMessage('Command executed, Awaiting New Command', true); }, 50);
        } else if (matchCmd(raw, 'id')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () {
                state.idMode = !state.idMode;
                document.body.classList.toggle('command-center-id-mode', state.idMode);
                appendMessage('Command executed, Awaiting New Command', true);
            }, 50);
        } else if (matchCmd(raw, 'lock id') || matchCmd(raw, 'disable id')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            setTimeout(function () {
                state.idMode = false;
                document.body.classList.remove('command-center-id-mode');
                appendMessage('Command executed, Awaiting New Command', true);
            }, 50);
        } else if (matchCmd(raw, 'bp')) {
            recognized = true;
            appendMessage('Executing order, please wait', true);
            fetch('/api/dashboard/blueprint', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            }).then(function (r) { return r.json(); }).then(function (data) {
                if (data.success) appendMessage('Blueprint created: ' + (data.path || 'dashboard_blueprint.md') + ' – Awaiting New Command', true);
                else appendMessage('Blueprint failed: ' + (data.error || 'Unknown error') + ' – Awaiting New Command', true);
            }).catch(function (err) {
                appendMessage('Blueprint failed: ' + (err.message || String(err)) + ' – Awaiting New Command', true);
            });
        } else if (matchCmd(raw, 'close cm') || matchCmd(raw, 'close command')) {
            recognized = true;
            closeCommandCenter();
        } else if (normalizeCmd(raw) === 'l' || matchCmd(raw, 'legende') || matchCmd(raw, 'legend') || matchCmd(raw, 'legenda')) {
            recognized = true;
            showLegend();
        }

        if (!recognized) appendMessage('Command not recognized', true);
        setTimeout(refreshLegendHighlights, 60);
    }

    function initHotkey() {
        document.addEventListener('keydown', function (e) {
            if (e.altKey && e.ctrlKey && e.key === 'Home') {
                e.preventDefault();
                openCommandCenter();
            }
        });
    }

    function initHoverModes() {
        document.addEventListener('mouseover', function (e) {
            var t = e.target;
            if (state.elementMode && !state.elementLocked) {
                var name = t.tagName + (t.id ? '#' + t.id : '') + (t.className && typeof t.className === 'string' ? '.' + (t.className.split(' ')[0] || '') : '');
                t.setAttribute('title', (t.getAttribute('title') || '') + ' [Element: ' + name + ']');
            }
            if (state.buttonFunctionMode && !state.buttonFunctionLocked && (t.tagName === 'BUTTON' || t.tagName === 'A' || t.hasAttribute('data-help'))) {
                var fn = t.getAttribute('data-help') || t.getAttribute('onclick') || 'No function defined';
                t.setAttribute('title', (t.getAttribute('title') || '') + ' [Function: ' + fn + ']');
            }
        }, true);
    }

    function initFlagElement() {
        document.addEventListener('contextmenu', function (e) {
            if (!state.flagElementMode) return;
            e.preventDefault();
            var el = e.target;
            var id = el.id || '';
            var tag = el.tagName || '';
            var cls = (el.className && typeof el.className === 'string') ? el.className : '';
            if (confirm('Do you wish to flag this element?')) {
                fetch('/api/flagged/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: id, tag: tag, className: cls, html: el.outerHTML ? el.outerHTML.substring(0, 500) : '' })
                }).then(function () {}).catch(function () {});
            }
        }, true);
    }

    function initIdModeStyles() {
        var style = document.createElement('style');
        style.id = 'command-center-styles';
        style.textContent =
            '.command-center-lock-text *{user-select:none;-webkit-user-select:none;-moz-user-select:none;-ms-user-select:none;}' +
            '.command-center-id-mode *, .command-center-id-mode * *{font-size:0 !important;}' +
            '.command-center-id-mode [id]{font-size:12px !important;}' +
            '.command-center-id-mode [id]::before{content:"#" attr(id);font-size:12px !important;display:block;}' +
            'body.command-center-gridview-active:not(.command-center-reveal-gridview-text) *{color:transparent !important;}' +
            'body.command-center-gridview-active #dashboard-command-center-overlay, body.command-center-gridview-active #dashboard-command-center-overlay *, body.command-center-gridview-active #dashboard-command-center-dialog, body.command-center-gridview-active #dashboard-command-center-dialog *, body.command-center-gridview-active #dashboard-command-center-tab, body.command-center-gridview-active #dashboard-command-center-tab *, body.command-center-gridview-active #command-center-legend-panel, body.command-center-gridview-active #command-center-legend-panel *, body.command-center-gridview-active #command-center-cell-dialog, body.command-center-gridview-active #command-center-cell-dialog *{color:#333!important;}' +
            'body.command-center-gridview-active #command-center-legend-tooltip, body.command-center-gridview-active #command-center-legend-tooltip *{color:#fff!important;}' +
            '.command-center-cell-dialog{background:#fff;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.2);padding:0;z-index:99998;min-width:240px;border:1px solid #ddd;pointer-events:auto;color:#333!important;}' +
            '.command-center-cell-dialog *{color:#333!important;}' +
            '.command-center-cell-dialog-header{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:#e8ecf7;border-radius:8px 8px 0 0;font-weight:600;font-size:13px;}' +
            '.command-center-cell-dialog-close{background:none;border:none;font-size:20px;cursor:pointer;color:#666;line-height:1;padding:0 6px;}' +
            '.command-center-cell-dialog-close:hover{color:#000;}' +
            '.command-center-cell-dialog-body{padding:12px 14px;font-size:13px;line-height:1.6;}' +
            '.command-center-cell-dialog-body p{margin:6px 0;}';
        document.head.appendChild(style);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initHotkey();
            initHoverModes();
            initFlagElement();
            initIdModeStyles();
        });
    } else {
        initHotkey();
        initHoverModes();
        initFlagElement();
        initIdModeStyles();
    }

    window.DashboardCommandCenter = { open: openCommandCenter, close: closeCommandCenter, execute: executeCommand };
})();
