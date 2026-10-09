// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── Asset Manager: Templates board ──
 * 2026-07-25: repointed from the (unused) sports templates_store to the Storyteller
 * daily-serial templates (/api/storyteller/templates/list). Renders the 22 series
 * templates: character, setting, episode/arc progress, SDXL realistic-animation,
 * and LoRA-readiness. The legacy /api/templates/* sports endpoints are left intact.
 */
function _amEsc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

var _AM_SRC_LABEL = {
    'The Second Ledger - Series Bible': 'SECOND LEDGER',
    'FARNAH - series premise': 'FARNAH',
    "Twenty Premises from the World's Conflict Zones (Expanded, July 2026)": 'CONFLICT ZONES'
};

window.amTemplatesRefresh = function() {
    var count = document.getElementById('am-tpl-count');
    if (count) count.textContent = 'Loading…';
    fetch('/api/storyteller/templates/list')
        .then(function(r){ return r.ok ? r.json() : {templates:[]}; })
        .then(function(d){ amTemplatesRender(d.templates || [], d); })
        .catch(function(){ amTemplatesRender([], {}); });
};

function amTemplatesRender(templates, meta) {
    var board = document.getElementById('am-templates-board');
    var countEl = document.getElementById('am-tpl-count');
    if (!board) return;

    var html = '';
    templates.forEach(function(t) {
        var ready   = !!t.ready;
        var srcTag  = _AM_SRC_LABEL[t.source_doc] || 'STORYTELLER';
        var badgeBg = ready ? '#1a6b3a' : '#b45309';
        var totalTxt = t.total_episodes ? (' / ' + t.total_episodes) : '';
        var loraBg  = ready ? 'rgba(34,197,94,0.16)' : 'rgba(201,138,58,0.18)';
        var loraFg  = ready ? '#4ade80' : '#e0a458';
        var loraTxt = ready ? '● LoRA linked' : '○ awaiting LoRA';
        var who = _amEsc(t.character || '') + (t.age != null ? ', ' + t.age : '');

        html += '<div class="am-tpl-card" title="' + _amEsc(t.logline || '') + '">'
            + '<div class="am-tpl-badge" style="background:' + badgeBg + ';">' + srcTag + '</div>'
            + '<div class="am-tpl-body">'
            + '<div class="am-tpl-name">🎭 ' + _amEsc(t.series_title || 'Series') + '</div>'
            + '<div class="am-tpl-meta">' + who + (t.setting ? ' · ' + _amEsc(t.setting) : '') + '</div>'
            + '<div class="am-tpl-meta" style="margin-top:2px;">'
            +     'Ep ' + (t.episode_no || 0) + totalTxt
            +     (t.current_arc ? ' · ' + _amEsc(t.current_arc) : '')
            +     ' · ' + _amEsc((t.model_family || 'sdxl').toUpperCase()) + ' realistic-animation'
            + '</div>'
            + '<div class="am-tpl-actions" style="align-items:center;">'
            + '<span style="background:' + loraBg + ';color:' + loraFg + ';border-radius:6px;'
            +       'padding:3px 9px;font-size:11px;font-weight:600;">' + loraTxt + '</span>'
            + '<button class="am-tpl-btn" style="background:#b45309;color:#fff;" '
            +       'onclick="amTemplateView(\'' + _amEsc(t.id||'') + '\')">Details</button>'
            + '</div></div></div>';
    });

    var placeholders = Math.max(0, 4 - templates.length);
    for (var i = 0; i < placeholders; i++) {
        html += '<div class="am-tpl-slot"><div class="am-tpl-slot-icon">🎭</div><span>Empty slot</span></div>';
    }
    board.innerHTML = html;

    if (countEl) {
        var blocked = templates.filter(function(t){ return !t.ready; }).length;
        countEl.textContent = templates.length
            ? (templates.length + ' series' + (blocked ? ' · ' + blocked + ' awaiting LoRA' : ''))
            : 'No storyteller templates found';
    }
}

window.amTemplateView = function(id) {
    fetch('/api/storyteller/templates/' + encodeURIComponent(id))
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(t){
            if (!t) { alert('Template not found: ' + id); return; }
            var c = t.character || {};
            var ser = t.serialization || {};
            var lines = [
                t.series_title || id,
                '',
                'Logline: ' + (t.logline || ''),
                'Setting: ' + (t.setting || ''),
                'Character: ' + (c.name || '') + ' (' + (c.gender||'') + ', ' + (c.age||'?') + ') — ' + (c.ethnic_heritage||''),
                'LoRA: ' + (c.char_id ? c.char_id : 'not linked yet') + ' [' + (c.lora_status||'pending') + ']',
                'Model: ' + ((t.settings||{}).model_family||'sdxl') + ' · ' + ((t.settings||{}).render_style||''),
                'Length: ' + (((t.settings||{}).duration_min_range)||[12,18]).join('–') + ' min',
                'Total episodes: ' + (ser.total_episodes || '—'),
                '',
                'Premise:',
                (t.engine||{}).premise || ''
            ];
            alert(lines.join('\n'));
        })
        .catch(function(){ alert('Failed to load template ' + id); });
};

// Auto-load when the Templates subtab is clicked
(function() {
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.asset-manager-subtab[data-department="templates"]').forEach(function(btn) {
            btn.addEventListener('click', function() { setTimeout(amTemplatesRefresh, 80); });
        });
    });
})();
