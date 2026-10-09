// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/01_cursor.js — Voice Bridge ghost cursor + caption.
 *
 * Loaded from /voice_ext/bundle.js, which sits right after /arch_ext/bundle.js in
 * inspection.html (line 6911) — i.e. BEFORE <body> and before the studio script.
 * Therefore this file only REGISTERS at top level: every DOM touch happens inside
 * a method call or in the VB.ready callback below.
 *
 * API (all return a Promise that resolves when the animation has finished):
 *   VB.cursor.moveTo(el | {x,y})      ghost arrow travels to the target
 *   VB.cursor.click(el)               moveTo + click pulse — does NOT call el.click();
 *                                     the action's own run() does the real work.
 *   VB.cursor.highlight(el, ms=900)   glowing ring around the element
 *   VB.cursor.caption(text)           bottom-centre pill, fades after 4 s
 *   VB.cursor.hide()                  fade the arrow (and the caption) away
 *
 * ZOOM (measured 2026-09-05, verified again 2026-09-15 by tests/vb_cursor_zoom.html):
 * inspection.html runs html{zoom:.67} and the shim at inspection.html:4764-4787
 * divides getBoundingClientRect()/clientX/innerWidth back into LAYOUT px. A
 * position:fixed element inside the zoomed <html> is laid out in those same layout
 * px, so a rect reading can be used as a left/top without any extra division.
 * Do not "correct" for the zoom here.
 */
(function () {
  'use strict';

  var VB = (window.VB = window.VB || { actions: {}, aliases: {}, ready: [], views: {} });

  var Z_TOP = 2147483000;
  var MOVE_MIN = 350;        // ms, one short hop
  var MOVE_MAX = 700;        // ms, ceiling for a long hop
  var CAPTION_MS = 4000;     // caption lifetime once nothing new arrives
  var PULSE_MS = 520;
  var FADE_MS = 180;

  var CSS = [
    '#vb-cursor{position:fixed;left:0;top:0;width:22px;height:22px;pointer-events:none;',
    '  z-index:' + Z_TOP + ';opacity:0;will-change:transform;',
    '  transform:translate3d(-60px,-60px,0);',
    '  transition:transform ' + MOVE_MIN + 'ms cubic-bezier(.22,.61,.36,1),opacity ' + FADE_MS + 'ms linear;}',
    '#vb-cursor.vb-on{opacity:1;}',
    '#vb-cursor svg{display:block;width:22px;height:22px;overflow:visible;',
    '  filter:drop-shadow(0 0 6px rgba(0,229,255,.85)) drop-shadow(0 1px 2px rgba(0,0,0,.8));}',
    '#vb-cursor .vb-glow{position:absolute;left:-9px;top:-9px;width:20px;height:20px;border-radius:50%;',
    '  background:radial-gradient(circle,rgba(0,229,255,.55) 0%,rgba(0,229,255,0) 70%);}',
    '#vb-pulse{position:fixed;left:0;top:0;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;',
    '  border:2px solid rgba(0,229,255,.9);pointer-events:none;z-index:' + (Z_TOP - 1) + ';opacity:0;',
    '  transform:translate3d(-60px,-60px,0) scale(.25);}',
    '#vb-pulse.vb-go{animation:vb-pulse-kf ' + PULSE_MS + 'ms ease-out forwards;}',
    '@keyframes vb-pulse-kf{0%{opacity:.95;transform:translate3d(var(--vb-px),var(--vb-py),0) scale(.25);}',
    '  100%{opacity:0;transform:translate3d(var(--vb-px),var(--vb-py),0) scale(1.5);}}',
    '#vb-ring{position:fixed;left:0;top:0;pointer-events:none;z-index:' + (Z_TOP - 2) + ';opacity:0;',
    '  border-radius:8px;box-shadow:0 0 0 3px rgba(0,229,255,.9),0 0 18px 4px rgba(0,229,255,.45);',
    '  transition:opacity ' + FADE_MS + 'ms linear;}',
    '#vb-ring.vb-on{opacity:1;}',
    '#vb-caption{position:fixed;left:50%;bottom:34px;transform:translateX(-50%);max-width:70vw;',
    '  padding:10px 20px;border-radius:22px;background:rgba(18,18,20,.92);color:#e4e4e7;',
    '  border:1px solid rgba(0,229,255,.55);box-shadow:0 8px 32px rgba(0,0,0,.6);',
    '  font:18px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;text-align:center;',
    '  pointer-events:none;z-index:' + Z_TOP + ';opacity:0;',
    '  transition:opacity 220ms linear;}',
    '#vb-caption.vb-on{opacity:1;}'
  ].join('\n');

  var ARROW =
    '<svg viewBox="0 0 22 22" aria-hidden="true">' +
    '<path d="M1.5 1 L1.5 17.2 L6.1 13.1 L8.9 19.4 L12.1 18 L9.4 11.9 L15.6 11.6 Z" ' +
    'fill="#ffffff" stroke="#0b0b0d" stroke-width="1.1" stroke-linejoin="round"/></svg>';

  var els = null;            // {cur, pulse, ring, cap}
  var capTimer = 0;
  var ringTimer = 0;
  var at = { x: -60, y: -60 };

  function whenBody() {
    return new Promise(function (res) {
      if (document.body) return res();
      document.addEventListener('DOMContentLoaded', function () { res(); }, { once: true });
    });
  }

  /* Lazy injection: the bundle runs before <body> exists. */
  function build() {
    if (els && els.cur.isConnected) return els;
    var st = document.getElementById('vb-cursor-css');
    if (!st) {
      st = document.createElement('style');
      st.id = 'vb-cursor-css';
      st.textContent = CSS;
      (document.head || document.documentElement).appendChild(st);
    }
    var cur = document.getElementById('vb-cursor');
    if (!cur) {
      cur = document.createElement('div');
      cur.id = 'vb-cursor';
      cur.innerHTML = '<div class="vb-glow"></div>' + ARROW;
      document.body.appendChild(cur);
    }
    var pulse = document.getElementById('vb-pulse');
    if (!pulse) {
      pulse = document.createElement('div');
      pulse.id = 'vb-pulse';
      document.body.appendChild(pulse);
    }
    var ring = document.getElementById('vb-ring');
    if (!ring) {
      ring = document.createElement('div');
      ring.id = 'vb-ring';
      document.body.appendChild(ring);
    }
    var cap = document.getElementById('vb-caption');
    if (!cap) {
      cap = document.createElement('div');
      cap.id = 'vb-caption';
      document.body.appendChild(cap);
    }
    els = { cur: cur, pulse: pulse, ring: ring, cap: cap };
    return els;
  }

  function ready() {
    return whenBody().then(build);
  }

  function wait(ms) {
    return new Promise(function (res) { setTimeout(res, ms); });
  }

  function frame() {
    return new Promise(function (res) { requestAnimationFrame(function () { res(); }); });
  }

  function onScreen(r) {
    return r.width > 0 && r.height > 0 &&
      r.bottom > 0 && r.right > 0 &&
      r.top < window.innerHeight && r.left < window.innerWidth;
  }

  /* Resolve a target to a fixed-position point in LAYOUT px (see the ZOOM note). */
  function pointOf(target) {
    if (!target) return null;
    if (typeof target.x === 'number' && typeof target.y === 'number') {
      return Promise.resolve({ x: target.x, y: target.y, rect: null });
    }
    if (!target.getBoundingClientRect) return null;
    var r = target.getBoundingClientRect();
    if (onScreen(r)) {
      return Promise.resolve({ x: r.left + r.width / 2, y: r.top + r.height / 2, rect: r });
    }
    try { target.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) { target.scrollIntoView(); }
    return frame().then(frame).then(function () {
      var r2 = target.getBoundingClientRect();
      return { x: r2.left + r2.width / 2, y: r2.top + r2.height / 2, rect: r2 };
    });
  }

  function hop(x, y) {
    var dx = x - at.x, dy = y - at.y;
    var dist = Math.sqrt(dx * dx + dy * dy);
    return Math.min(MOVE_MAX, Math.round(MOVE_MIN + dist * 0.25));
  }

  var cursor = {

    /* Move the arrow tip onto el (or an absolute {x,y}). Scrolls the element into
       view first when it is outside the viewport. */
    moveTo: function (target) {
      return ready().then(function (E) {
        var p = pointOf(target);
        if (!p) return null;
        return p.then(function (pt) {
          var ms = hop(pt.x, pt.y);
          E.cur.style.transitionDuration = ms + 'ms, ' + FADE_MS + 'ms';
          E.cur.style.transform = 'translate3d(' + pt.x + 'px,' + pt.y + 'px,0)';
          E.cur.classList.add('vb-on');
          at = { x: pt.x, y: pt.y };
          return wait(ms + 20).then(function () { return pt; });
        });
      });
    },

    /* Show a click on el: travel there, then a 40 px ring that expands and fades at
       the tip. Deliberately does NOT dispatch the click — the action's run() does. */
    click: function (target) {
      return cursor.moveTo(target).then(function (pt) {
        if (!pt) return null;
        var E = build();
        var P = E.pulse;
        P.classList.remove('vb-go');
        P.style.setProperty('--vb-px', pt.x + 'px');
        P.style.setProperty('--vb-py', pt.y + 'px');
        void P.offsetWidth;                       // restart the keyframes
        P.classList.add('vb-go');
        return wait(PULSE_MS + 20).then(function () {
          P.classList.remove('vb-go');
          return pt;
        });
      });
    },

    /* Glowing ring around el for ms milliseconds. */
    highlight: function (target, ms) {
      ms = (typeof ms === 'number' && ms > 0) ? ms : 900;
      return ready().then(function (E) {
        if (!target || !target.getBoundingClientRect) return null;
        var p = pointOf(target);
        if (!p) return null;
        return p.then(function (pt) {
          var r = pt.rect || target.getBoundingClientRect();
          var pad = 4;
          E.ring.style.left = (r.left - pad) + 'px';
          E.ring.style.top = (r.top - pad) + 'px';
          E.ring.style.width = (r.width + pad * 2) + 'px';
          E.ring.style.height = (r.height + pad * 2) + 'px';
          E.ring.classList.add('vb-on');
          clearTimeout(ringTimer);
          return wait(ms).then(function () {
            E.ring.classList.remove('vb-on');
            return wait(FADE_MS);
          });
        });
      });
    },

    /* Bottom-centre pill with the sentence the assistant is saying. Fades 4 s after
       the last call. Passing '' or null hides it at once. */
    caption: function (text) {
      return ready().then(function (E) {
        clearTimeout(capTimer);
        if (text === null || text === undefined || String(text) === '') {
          E.cap.classList.remove('vb-on');
          return wait(220);
        }
        E.cap.textContent = String(text);
        E.cap.classList.add('vb-on');
        capTimer = setTimeout(function () { E.cap.classList.remove('vb-on'); }, CAPTION_MS);
        return wait(220);
      });
    },

    /* Fade everything out. */
    hide: function () {
      return ready().then(function (E) {
        clearTimeout(capTimer);
        clearTimeout(ringTimer);
        E.cur.classList.remove('vb-on');
        E.ring.classList.remove('vb-on');
        E.cap.classList.remove('vb-on');
        return wait(Math.max(FADE_MS, 220));
      });
    },

    /* Escape hatch for the core: build the DOM now. */
    ensure: function () { return ready(); }
  };

  VB.cursor = cursor;

  /* Core calls VB.ready once on DOMContentLoaded — pre-build so the first real
     moveTo() does not pay for element creation mid-animation. */
  if (Array.isArray(VB.ready)) VB.ready.push(function () { build(); });
})();
