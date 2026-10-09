// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── Electronic Water-Drop Neural Ripple v3 + Moon Landing ───────────────── */
(function () {
  'use strict';

  var canvas = document.getElementById('neural-drop-canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');

  /* Offscreen canvas used to build the union ring mask each frame */
  var oc  = document.createElement('canvas');
  var oct = oc.getContext('2d');

  var W = 0, H = 0;

  function resize() {
    W = canvas.width = oc.width  = window.innerWidth;
    H = canvas.height = oc.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  /* For users that prefer reduced motion: show the network statically */
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    var imgEl = document.querySelector('.neural-net-glow');
    if (imgEl) imgEl.style.opacity = '0.9';
    return;
  }

  /* Load the SVG for canvas drawing (the <img> tag stays opacity:0) */
  var netImg   = new Image();
  var netReady = false;
  netImg.onload = function () { netReady = true; };
  netImg.src = '/assets/zero/neural-network.svg?v=2';


  /* ── Exclusion zones (2D) ───────────────────────────────────────────────── */
  var AVOID_IDS = ['form-section', 'sidebar', 'result-card', 'error-card',
                   'st-char-preview-modal', 'adv-panel-output'];
  var AVOID_PAD = 40;

  function getForbidden() {
    var out = [];
    AVOID_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      var st = window.getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden') return;
      var r = el.getBoundingClientRect();
      if (r.width < 4) return;
      out.push({ x: r.left - AVOID_PAD, y: r.top - AVOID_PAD,
                 w: r.width + AVOID_PAD * 2, h: r.height + AVOID_PAD * 2 });
    });
    /* Also catch all floating preview windows by class */
    document.querySelectorAll('.preview-window').forEach(function (el) {
      var st = window.getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden') return;
      var r = el.getBoundingClientRect();
      if (r.width < 4) return;
      out.push({ x: r.left - AVOID_PAD, y: r.top - AVOID_PAD,
                 w: r.width + AVOID_PAD * 2, h: r.height + AVOID_PAD * 2 });
    });
    return out;
  }

  function pickSpot(forbidden) {
    var x, y, tries = 0;
    do {
      x = 80 + Math.random() * (W - 160);
      y = H * (0.20 + Math.random() * 0.62); /* 20 – 82 % screen height */
    } while (++tries < 120 && forbidden.some(function (r) {
      return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
    }));
    return { x: x, landY: y };
  }

  /* ── Teardrop bezier path ────────────────────────────────────────────────── */
  function teardrop(c, cx, cy, r) {
    c.beginPath();
    c.moveTo(cx, cy - r * 1.65);
    c.bezierCurveTo(cx + r * 1.05, cy - r * 0.6, cx + r * 1.05, cy + r * 0.35, cx, cy + r);
    c.bezierCurveTo(cx - r * 1.05, cy + r * 0.35, cx - r * 1.05, cy - r * 0.6, cx, cy - r * 1.65);
    c.closePath();
  }

  /* ── Drop ────────────────────────────────────────────────────────────────── */
  function Drop(spot) {
    this.x      = spot.x;
    this.landY  = spot.landY;
    this.y      = -40;
    this.vy     = 2.0 + Math.random() * 1.8;
    this.grav   = 0.42;
    this.size   = 5.5 + Math.random() * 3.5;
    this.trail  = [];
    this.phase  = 'falling'; /* 'falling' | 'imprint' */
    this.landTs = 0;
    this.done   = false;
  }
  Drop.prototype.update = function (ts) {
    if (this.done) return;
    if (this.phase === 'imprint') {
      if (ts - this.landTs > 2000) this.done = true;
      return;
    }
    this.vy += this.grav;
    this.trail.unshift({ x: this.x, y: this.y });
    if (this.trail.length > 14) this.trail.pop();
    this.y += this.vy;
    if (this.y >= this.landY) {
      this.y      = this.landY;
      this.phase  = 'imprint';
      this.landTs = ts;
      ripples.push(new Ripple(this.x, this.landY));
    }
  };
  Drop.prototype.draw = function (c, ts) {
    /* imprint: glow splash at landing point, visible 1s then fades over 1s */
    if (this.phase === 'imprint') {
      var elapsed = ts - this.landTs;
      var alpha   = elapsed <= 1000 ? 1.0 : Math.max(0, 1.0 - (elapsed - 1000) / 1000);
      c.save();
      c.globalAlpha = alpha;
      c.shadowColor = '#3bd4ff';
      c.shadowBlur  = 30;
      c.beginPath();
      c.arc(this.x, this.landY, this.size * 1.6, 0, Math.PI * 2);
      c.fillStyle = 'rgba(65,185,255,0.50)';
      c.fill();
      c.shadowColor = '#ffffff';
      c.shadowBlur  = 14;
      c.beginPath();
      c.arc(this.x, this.landY, this.size * 0.5, 0, Math.PI * 2);
      c.fillStyle = 'rgba(215,248,255,0.96)';
      c.fill();
      c.restore();
      return;
    }
    /* motion trail */
    for (var i = 0; i < this.trail.length; i++) {
      var t  = 1 - i / this.trail.length;
      var tr = this.trail[i];
      c.beginPath();
      c.arc(tr.x, tr.y, this.size * 0.36 * t, 0, Math.PI * 2);
      c.fillStyle = 'rgba(80,205,255,' + (t * 0.42) + ')';
      c.fill();
    }
    /* glow body */
    c.save();
    c.shadowColor = '#3bd4ff';
    c.shadowBlur  = 24;
    teardrop(c, this.x, this.y, this.size);
    c.fillStyle = 'rgba(65,185,255,0.90)';
    c.fill();
    /* bright core */
    c.shadowColor = '#ffffff';
    c.shadowBlur  = 12;
    teardrop(c, this.x, this.y, this.size * 0.46);
    c.fillStyle = 'rgba(215,248,255,0.96)';
    c.fill();
    c.restore();
  };

  /* ── Ripple — single wide ring that reveals the neural network ───────────── */
  var RING_HALF = 42.5; /* 42.5 px each side = 85 px total band */
  var RING_SPD  = 3.6;  /* px per frame at 60 fps — 20% slower */

  function Ripple(x, y) {
    this.x    = x;
    this.y    = y;
    this.r    = 0;
    this.maxR = Math.hypot(W, H) + RING_HALF + 60;
    this.done = false;
    /* Sinusoidal harmonics — unique organic shape per ripple */
    var amp = RING_HALF * 0.52;
    this.hz = [
      { f: 2, a: amp * 0.55, p: Math.random() * 6.283 },
      { f: 3, a: amp * 0.30, p: Math.random() * 6.283 },
      { f: 5, a: amp * 0.12, p: Math.random() * 6.283 },
      { f: 7, a: amp * 0.06, p: Math.random() * 6.283 }
    ];
  }
  Ripple.prototype.update = function () {
    this.r += RING_SPD;
    if (this.r > this.maxR) this.done = true;
  };
  Ripple.prototype.shapeOff = function (theta) {
    var off = 0, hz = this.hz;
    for (var i = 0; i < hz.length; i++) off += hz[i].a * Math.sin(hz[i].f * theta + hz[i].p);
    return off;
  };

  /* ── State ───────────────────────────────────────────────────────────────── */
  var drops   = [];
  var ripples = [];

  /* One drop every 6 seconds */
  var BEAT_MS  = 6000;
  var lastDrop = -BEAT_MS * 2; /* fire immediately on first frame */

  /* ── Render loop ─────────────────────────────────────────────────────────── */
  function loop(ts) {

    /* 1 ── Spawn drop on heartbeat */
    if (ts - lastDrop >= BEAT_MS) {
      lastDrop = ts;
      drops.push(new Drop(pickSpot(getForbidden())));
    }

    /* 2 ── Update drops (may push to ripples[]) */
    for (var i = drops.length - 1; i >= 0; i--) {
      drops[i].update(ts);
      if (drops[i].done) drops.splice(i, 1);
    }

    /* 3 ── Update ripples */
    for (var j = 0; j < ripples.length; j++) {
      ripples[j].update();
    }

    /* 4 ── Clear canvas */
    ctx.clearRect(0, 0, W, H);

    /* 5 ── Draw neural network revealed only inside ring bands */
    if (netReady && ripples.length > 0) {

      /* 5a — Draw the full network (boosted for the "lit" look) */
      ctx.save();
      ctx.filter = 'brightness(2.0) saturate(2.6) hue-rotate(3deg)';
      ctx.drawImage(netImg, 0, 0, W, H);
      ctx.restore();

      /* 5b — Organic ring mask: path clips to non-circular shape, radial
               gradient provides the soft inner/outer fade — no per-frame blur. */
      oct.clearRect(0, 0, W, H);
      var SEG = 96;
      for (var k = 0; k < ripples.length; k++) {
        var rip   = ripples[k];
        if (rip.r < 1) continue;
        var life  = Math.max(0, 1 - Math.max(0, rip.r - RING_HALF) / rip.maxR);
        var inner = Math.max(0, rip.r - RING_HALF);
        var outer = rip.r + RING_HALF;

        /* Outer boundary */
        oct.beginPath();
        for (var si = 0; si <= SEG; si++) {
          var th = (si / SEG) * Math.PI * 2;
          var ro = rip.r + RING_HALF + rip.shapeOff(th);
          var px = rip.x + ro * Math.cos(th);
          var py = rip.y + ro * Math.sin(th);
          if (si === 0) oct.moveTo(px, py); else oct.lineTo(px, py);
        }
        oct.closePath();

        /* Inner cutout — evenodd punches the hole */
        for (var si = 0; si <= SEG; si++) {
          var th = (si / SEG) * Math.PI * 2;
          var ri = Math.max(0, rip.r - RING_HALF + rip.shapeOff(th) * 0.65);
          var px = rip.x + ri * Math.cos(th);
          var py = rip.y + ri * Math.sin(th);
          if (si === 0) oct.moveTo(px, py); else oct.lineTo(px, py);
        }
        oct.closePath();

        /* Soft radial gradient gives smooth fade at inner/outer edges */
        var grd = oct.createRadialGradient(rip.x, rip.y, inner, rip.x, rip.y, outer);
        grd.addColorStop(0,    'rgba(255,255,255,0)');
        grd.addColorStop(0.15, 'rgba(255,255,255,' + life + ')');
        grd.addColorStop(0.85, 'rgba(255,255,255,' + life + ')');
        grd.addColorStop(1,    'rgba(255,255,255,0)');
        oct.fillStyle = grd;
        oct.fill('evenodd');
      }

      /* 5c — Apply mask */
      ctx.globalCompositeOperation = 'destination-in';
      ctx.drawImage(oc, 0, 0);
      ctx.globalCompositeOperation = 'source-over';

    }

    /* 6 ── Draw drops on top (always visible) */
    for (var n = 0; n < drops.length; n++) {
      drops[n].draw(ctx, ts);
    }

    /* 7 ── Remove done ripples */
    for (var p = ripples.length - 1; p >= 0; p--) {
      if (ripples[p].done) ripples.splice(p, 1);
    }

    requestAnimationFrame(loop);
  }

  requestAnimationFrame(loop);
})();
