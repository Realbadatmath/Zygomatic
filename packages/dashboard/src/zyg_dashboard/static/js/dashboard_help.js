// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard help: show explanation after 3s hover (no mouse move), fade in 1s; fade out 0.5s on mouse move/leave.
 * Works on any element with data-help="..." or matches help suggestions from JSON file.
 */
(function() {
    const HOVER_DELAY_MS = 3000;
    const FADE_IN_DURATION_MS = 1000;
    const FADE_OUT_DURATION_MS = 500;

    let tooltipEl = null;
    let hoverTimer = null;
    let currentTarget = null;
    let fadeOutTimer = null;
    let cancelMoveListener = null;
    const MOVE_THRESHOLD_PX = 12;
    let hoverStartX = 0;
    let hoverStartY = 0;
    let helpSuggestions = null;
    let helpSuggestionsLoaded = false;

    function loadHelpSuggestions() {
        if (helpSuggestionsLoaded) return Promise.resolve();
        return fetch('/static/data/help_suggestions.json')
            .then(function(res) { return res.ok ? res.json() : null; })
            .then(function(data) {
                helpSuggestions = data || {};
                helpSuggestionsLoaded = true;
            })
            .catch(function() {
                helpSuggestions = {};
                helpSuggestionsLoaded = true;
            });
    }

    function getHelpTextFromSuggestions(el) {
        if (!helpSuggestions || !el) return null;
        var id = el.id;
        var className = el.className;
        var tagName = el.tagName ? el.tagName.toLowerCase() : '';
        var text = null;
        if (id && helpSuggestions.buttons && helpSuggestions.buttons[id]) {
            text = helpSuggestions.buttons[id];
            if (text) return text;
        }
        if (el.classList) {
            if (el.classList.contains('dashboard-circle-wrap') || el.classList.contains('dashboard-overview-circle-wrap') || el.classList.contains('dashboard-job-bar-item') || el.classList.contains('dashboard-error-bar-item')) {
                text = helpSuggestions.progression_bars && helpSuggestions.progression_bars.circular_progress_bar;
                if (!text) {
                    var labelEl = el.querySelector('.dashboard-circle-label');
                    if (!labelEl) {
                        var parent = el.parentElement;
                        if (parent) labelEl = parent.querySelector('.dashboard-circle-label');
                    }
                    if (labelEl) {
                        var label = labelEl.textContent.trim();
                        if (label) {
                            text = 'View details for ' + label + '.';
                        }
                    }
                }
                if (text) return text;
            }
            if (el.classList.contains('timeline-bar') || el.classList.contains('timeline-vertical-bar')) {
                text = helpSuggestions.progression_bars && helpSuggestions.progression_bars.timeline_bar;
                if (text) return text;
            }
            if (el.classList.contains('dashboard-progression-bar') || el.classList.contains('schedule-bar')) {
                text = helpSuggestions.progression_bars && helpSuggestions.progression_bars[el.classList.contains('dashboard-progression-bar') ? 'dashboard-progression-bar' : 'schedule-bar'];
                if (text) return text;
            }
            if (el.classList.contains('dashboard-sidebar-tab')) {
                text = helpSuggestions.selectors && helpSuggestions.selectors['.dashboard-sidebar-tab'];
                if (text) return text;
            }
            if (el.classList.contains('tab-btn')) {
                text = helpSuggestions.selectors && helpSuggestions.selectors['.tab-btn'];
                if (text) return text;
            }
            if (el.classList.contains('btn') || el.classList.contains('dashboard-btn')) {
                var btnText = helpSuggestions.selectors && helpSuggestions.selectors['.dashboard-btn'];
                if (!btnText) btnText = helpSuggestions.selectors && helpSuggestions.selectors['.btn'];
                if (btnText) return btnText;
            }
        }
        if (className) {
            var classes = className.split(/\s+/);
            for (var i = 0; i < classes.length; i++) {
                if (helpSuggestions.buttons && helpSuggestions.buttons['.' + classes[i]]) {
                    text = helpSuggestions.buttons['.' + classes[i]];
                    if (text) return text;
                }
                if (helpSuggestions.selectors && helpSuggestions.selectors['.' + classes[i]]) {
                    text = helpSuggestions.selectors['.' + classes[i]];
                    if (text) return text;
                }
            }
        }
        if (!text && tagName) {
            if (helpSuggestions.selectors && helpSuggestions.selectors[tagName]) {
                text = helpSuggestions.selectors[tagName];
            }
        }
        return text;
    }

    function getHelpText(el) {
        if (!el) return null;
        var raw = el.getAttribute('data-help') || (el.getAttribute('title') && el.hasAttribute('data-help-title') ? el.getAttribute('title') : null);
        if (raw && raw.trim()) return raw.trim();
        if (el.getAttribute('title') && !raw) {
            raw = el.getAttribute('title');
            if (raw && raw.trim()) return raw.trim();
        }
        if (helpSuggestionsLoaded) {
            var suggestion = getHelpTextFromSuggestions(el);
            if (suggestion) return suggestion;
        }
        return null;
    }

    function createTooltip() {
        if (tooltipEl) return tooltipEl;
        tooltipEl = document.createElement('div');
        tooltipEl.id = 'dashboard-help-tooltip';
        tooltipEl.setAttribute('role', 'tooltip');
        tooltipEl.style.cssText = [
            'position:fixed;z-index:99999;max-width:320px;padding:12px 16px;',
            'background:rgba(20,23,33,0.96);color:#e8eaed;border-radius:10px;',
            'font-size:13px;line-height:1.45;box-shadow:0 4px 20px rgba(0,0,0,0.35);',
            'pointer-events:none;border:1px solid rgba(255,255,255,0.1);',
            'opacity:0;transition:opacity ' + (FADE_IN_DURATION_MS / 1000) + 's ease-out;'
        ].join(' ');
        document.body.appendChild(tooltipEl);
        return tooltipEl;
    }

    function positionTooltip(target) {
        const tip = createTooltip();
        const rect = target.getBoundingClientRect();
        const gap = 8;
        let left = rect.left;
        let top = rect.bottom + gap;
        const viewW = window.innerWidth;
        const viewH = window.innerHeight;
        const tipW = 320;
        const tipH = tip.offsetHeight || 80;
        if (left + tipW > viewW - 16) left = viewW - tipW - 16;
        if (left < 16) left = 16;
        if (top + tipH > viewH - 16) top = rect.top - tipH - gap;
        if (top < 16) top = 16;
        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
    }

    function showTooltip(target, text) {
        if (!target || !text) return;
        if (currentTarget !== target) return;
        clearTimeout(hoverTimer);
        hoverTimer = null;
        document.removeEventListener('mousemove', onMoveOrLeave);
        document.removeEventListener('mouseleave', onMoveOrLeave);
        const tip = createTooltip();
        tip.style.display = '';
        tip.style.transitionDuration = (FADE_IN_DURATION_MS / 1000) + 's';
        tip.textContent = text;
        tip.style.opacity = '0';
        positionTooltip(target);
        requestAnimationFrame(function() {
            requestAnimationFrame(function() {
                if (currentTarget === target && tip) {
                    tip.style.opacity = '1';
                }
            });
        });
        document.addEventListener('mousemove', onMoveOrLeave, { passive: true });
        document.addEventListener('mouseleave', onMoveOrLeave);
    }

    function hideTooltip() {
        document.removeEventListener('mousemove', onMoveOrLeave);
        document.removeEventListener('mouseleave', onMoveOrLeave);
        if (!tooltipEl) return;
        var wasShowing = tooltipEl.style.opacity === '1';
        tooltipEl.style.transitionDuration = (FADE_OUT_DURATION_MS / 1000) + 's';
        tooltipEl.style.opacity = '0';
        if (wasShowing) {
            fadeOutTimer = setTimeout(function() {
                if (tooltipEl) {
                    tooltipEl.style.display = 'none';
                    tooltipEl.textContent = '';
                }
                fadeOutTimer = null;
            }, FADE_OUT_DURATION_MS);
        } else {
            if (tooltipEl) {
                tooltipEl.style.display = 'none';
                tooltipEl.textContent = '';
            }
            fadeOutTimer = null;
        }
    }

    function onMoveOrLeave(e) {
        if (fadeOutTimer) return;
        if (tooltipEl && tooltipEl.style.opacity === '1') {
            var moveEl = findHelpElement(e && e.target ? e.target : null);
            if (moveEl === currentTarget || (currentTarget && typeof currentTarget.contains === 'function' && currentTarget.contains(moveEl))) {
                return;
            }
            hideTooltip();
            return;
        }
        if (hoverTimer) {
            clearTimeout(hoverTimer);
            hoverTimer = null;
        }
    }

    function clearHoverTimer() {
        clearTimeout(hoverTimer);
        hoverTimer = null;
        if (cancelMoveListener) {
            try {
                document.removeEventListener('mousemove', cancelMoveListener);
                document.removeEventListener('mouseleave', cancelMoveListener);
            } catch (e) {}
            cancelMoveListener = null;
        }
    }

    function findHelpElement(target) {
        if (!target) return null;
        if (target.nodeType === 3) {
            target = target.parentElement;
        }
        if (!target || target === document.body || target === document.documentElement) return null;
        var el = target.closest && target.closest('[data-help]');
        if (el) return el;
        var checkEl = function(elem) {
            if (!elem || elem.nodeType !== 1) return false;
            var tag = elem.tagName ? elem.tagName.toLowerCase() : '';
            if (tag === 'button' || tag === 'a') return true;
            if (!elem.classList) return false;
            return (
                elem.classList.contains('btn') || 
                elem.classList.contains('dashboard-btn') || 
                elem.classList.contains('tab-btn') || 
                elem.classList.contains('dashboard-sidebar-tab') || 
                elem.classList.contains('parameter-control-mode') || 
                elem.classList.contains('timeline-bar') || 
                elem.classList.contains('timeline-vertical-bar') || 
                elem.classList.contains('dashboard-progression-bar') || 
                elem.classList.contains('schedule-bar') ||
                elem.classList.contains('dashboard-circle-wrap') ||
                elem.classList.contains('dashboard-overview-circle-wrap') ||
                elem.classList.contains('dashboard-job-bar-item') ||
                elem.classList.contains('dashboard-error-bar-item')
            );
        };
        if (checkEl(target)) return target;
        var parent = target.parentElement;
        var maxDepth = 15;
        var depth = 0;
        while (parent && parent !== document.body && parent !== document.documentElement && depth < maxDepth) {
            if (parent.closest && parent.closest('[data-help]')) {
                return parent.closest('[data-help]');
            }
            if (checkEl(parent)) return parent;
            parent = parent.parentElement;
            depth++;
        }
        return null;
    }

    function onEnter(e) {
        var el = findHelpElement(e.target);
        if (!el) {
            if (currentTarget && currentTarget !== el) {
                clearHoverTimer();
                if (tooltipEl && tooltipEl.style.opacity === '1') {
                    hideTooltip();
                }
                currentTarget = null;
            }
            return;
        }
        var text = getHelpText(el);
        if (!text) {
            if (currentTarget && currentTarget !== el) {
                clearHoverTimer();
                if (tooltipEl && tooltipEl.style.opacity === '1') {
                    hideTooltip();
                }
                currentTarget = null;
            }
            return;
        }
        if (currentTarget === el && hoverTimer) {
            return;
        }
        if (currentTarget && currentTarget !== el) {
            clearHoverTimer();
            if (tooltipEl && tooltipEl.style.opacity === '1') {
                hideTooltip();
            }
        }
        clearTimeout(fadeOutTimer);
        fadeOutTimer = null;
        if (tooltipEl && currentTarget !== el) {
            tooltipEl.style.opacity = '0';
            tooltipEl.style.display = 'none';
            tooltipEl.textContent = '';
        }
        currentTarget = el;
        hoverStartX = (e.clientX != null) ? e.clientX : 0;
        hoverStartY = (e.clientY != null) ? e.clientY : 0;
        hoverTimer = setTimeout(function() {
            if (currentTarget === el && text) {
                clearHoverTimer();
                showTooltip(el, text);
            }
        }, HOVER_DELAY_MS);
        cancelMoveListener = function(ev) {
            if (ev.type === 'mouseleave') {
                var related = ev.relatedTarget;
                if (related && typeof el.contains === 'function' && el.contains(related)) return;
                clearHoverTimer();
                if (currentTarget === el) {
                    currentTarget = null;
                }
                return;
            }
            var moveEl = findHelpElement(ev.target);
            if (!moveEl) {
                if (el && typeof el.contains === 'function' && el.contains(ev.target)) {
                    return;
                }
                clearHoverTimer();
                if (currentTarget === el) {
                    currentTarget = null;
                }
                return;
            }
            if (moveEl !== el) {
                if (el && typeof el.contains === 'function' && el.contains(moveEl)) {
                    return;
                }
                if (moveEl && typeof moveEl.contains === 'function' && moveEl.contains(el)) {
                    return;
                }
                clearHoverTimer();
                if (currentTarget === el) {
                    currentTarget = null;
                }
                return;
            }
            var dx = (ev.clientX != null ? ev.clientX : 0) - hoverStartX;
            var dy = (ev.clientY != null ? ev.clientY : 0) - hoverStartY;
            if (dx * dx + dy * dy > MOVE_THRESHOLD_PX * MOVE_THRESHOLD_PX) {
                clearHoverTimer();
                if (currentTarget === el) {
                    currentTarget = null;
                }
            }
        };
        document.addEventListener('mousemove', cancelMoveListener, { passive: true });
        document.addEventListener('mouseleave', cancelMoveListener);
    }

    function onLeave(e) {
        var el = findHelpElement(e.target);
        if (!el) {
            if (currentTarget) {
                clearHoverTimer();
                if (tooltipEl && tooltipEl.style.opacity === '1') {
                    hideTooltip();
                }
                currentTarget = null;
            }
            return;
        }
        var related = e.relatedTarget;
        if (related && typeof el.contains === 'function' && el.contains(related))
            return;
        if (currentTarget === el) {
            clearHoverTimer();
            if (tooltipEl && tooltipEl.style.opacity === '1') {
                hideTooltip();
            }
            currentTarget = null;
        }
    }

    function init() {
        loadHelpSuggestions().then(function() {
            document.body.addEventListener('mouseover', onEnter, true);
            document.body.addEventListener('mouseout', onLeave, true);
        });
    }

    if (document.readyState === 'loading')
        document.addEventListener('DOMContentLoaded', init);
    else
        init();
})();
