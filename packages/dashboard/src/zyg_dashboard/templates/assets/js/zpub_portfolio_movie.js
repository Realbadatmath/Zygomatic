// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* Portfolio movie engine — plays a deck of still pictures like a film.
 *
 * One engine, two hosts: the full page (/portfolio-slideshow, fit "contain")
 * and the 420 px card on the invite page (fit "cover"). The deck comes from
 * /portfolio-slideshow/deck.json (zpub_portfolio_deck.py).
 *
 * How a still becomes a shot
 *   - Ken Burns: every picture drifts and zooms a little (Web Animations API),
 *     a different direction each time, so nothing is static on screen.
 *   - Crossfade: two stacked <img> layers; the next picture is fetched AND
 *     decoded before the fade starts, so the cut lands on a ready frame.
 *   - Captions: chapter kicker, title, one-line "what", up to three bullets,
 *     staggered in like lower thirds.
 *   - Pacing: a shot lasts as long as its caption takes to read
 *     (4 s + 0.3 s per word, clamped 5-12 s), times the chosen speed.
 *   - Chapter cards between chapters, a hero at the start, a thank-you at the end.
 *   - Timeline: a progress bar with chapter ticks; click to seek. The clock
 *     is requestAnimationFrame based, so pause/resume keeps its place.
 *
 * Respects prefers-reduced-motion (no drift, plain fades).
 *
 * Usage
 *   var movie = new PortfolioMovie(container, deck, {
 *     fit: 'contain' | 'cover', controls: true | 'mini' | false,
 *     speed: 1, autoplay: false, openUrl: '/portfolio-slideshow',
 *     slideUrl: function (file) {...}, onFrame: function (i, frame) {...},
 *     onEnd: function () {...}, keys: false
 *   });
 *   movie.play(); movie.pause(); movie.toggle(); movie.next(); movie.prev();
 *   movie.goto(i); movie.gotoChapter(id); movie.setSpeed(x); movie.destroy();
 */
(function (global) {
  'use strict';

  var FADE_MS = 750;
  var REDUCED = false;
  try {
    REDUCED = global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch (e) { REDUCED = false; }

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function words(s) { return String(s || '').trim().split(/\s+/).filter(Boolean).length; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  /* Reading-time pacing. Hero and chapter cards are fixed beats. */
  function frameSeconds(f) {
    if (f.kind === 'hero') return 6;
    if (f.kind === 'chapter') return 3.2;
    var n = words(f.title) + words(f.what) + (f.points || []).reduce(function (a, p) { return a + words(p); }, 0);
    var s = 4 + 0.3 * n;
    return f.file ? clamp(s, 5, 12) : clamp(s, 4, 9);
  }

  /* Flatten deck → frames. */
  function flatten(deck) {
    var frames = [];
    var chapters = deck.chapters || [];
    if (deck.hero) frames.push({ kind: 'hero', hero: deck.hero, chapterIdx: -1 });
    chapters.forEach(function (ch, ci) {
      frames.push({ kind: 'chapter', title: ch.title, lead: ch.lead || '', chapterIdx: ci, chapterId: ch.id, num: ci + 1 });
      (ch.slides || []).forEach(function (s) {
        frames.push({
          kind: s.file ? 'slide' : 'text',
          file: s.file || null, title: s.title || '', what: s.what || '',
          points: (s.points || []).slice(0, 3),
          chapterIdx: ci, chapterId: ch.id, chapter: ch.title, num: ci + 1
        });
      });
    });
    frames.forEach(function (f) { f.sec = frameSeconds(f); });
    return frames;
  }

  function PortfolioMovie(container, deck, opts) {
    if (!container) throw new Error('PortfolioMovie: container missing');
    this.opts = Object.assign({
      fit: 'contain', controls: true, speed: 1, autoplay: false,
      openUrl: null, keys: false,
      slideUrl: function (file) { return '/portfolio-slideshow/slide/' + encodeURIComponent(file); },
      onFrame: null, onEnd: null, onState: null
    }, opts || {});
    this.deck = deck || { chapters: [] };
    this.frames = flatten(this.deck);
    this.total = this.frames.reduce(function (a, f) { return a + f.sec; }, 0);
    this.idx = -1;
    this.playing = false;
    this.elapsed = 0;       // seconds into the current frame (at speed 1)
    this._lastTs = 0;
    this._raf = 0;
    this._anim = null;
    this._front = 0;        // which layer is visible
    this._destroyed = false;
    this._build(container);
    if (this.frames.length) this.goto(0, true);
    if (this.opts.autoplay) this.play();
  }

  PortfolioMovie.prototype._build = function (container) {
    var self = this;
    container.classList.add('pm', 'pm-fit-' + this.opts.fit);
    if (REDUCED) container.classList.add('pm-reduced');
    this.root = container;

    this.stage = el('div', 'pm-stage');
    this.layers = [el('img', 'pm-layer'), el('img', 'pm-layer')];
    this.layers.forEach(function (im) {
      im.alt = ''; im.draggable = false; im.decoding = 'async';
      im.addEventListener('contextmenu', function (e) { e.preventDefault(); });
      self.stage.appendChild(im);
    });
    this.card = el('div', 'pm-card');            // hero / chapter / text frames
    this.caption = el('div', 'pm-caption');      // lower third on picture frames
    this.stage.appendChild(this.card);
    this.stage.appendChild(this.caption);

    // Tap/click on the picture: advance (and pause) — the slideshow habit.
    this.stage.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('.pm-controls, .pm-bar, .pm-index')) return;
      if (self.opts.clickAdvances === false) return;
      self.pause(); self.next();
    });

    // Timeline with chapter ticks.
    this.bar = el('div', 'pm-bar');
    this.barFill = el('div', 'pm-bar-fill');
    this.bar.appendChild(this.barFill);
    var acc = 0;
    this.frames.forEach(function (f) {
      if (f.kind === 'chapter') {
        var t = el('span', 'pm-tick');
        t.style.left = (acc / self.total * 100) + '%';
        t.title = f.title;
        self.bar.appendChild(t);
      }
      acc += f.sec;
    });
    this.bar.addEventListener('click', function (e) {
      var r = self.bar.getBoundingClientRect();
      var p = clamp((e.clientX - r.left) / r.width, 0, 0.9999);
      self.seekTo(p * self.total);
    });

    container.appendChild(this.stage);
    container.appendChild(this.bar);
    if (this.opts.controls === 'mini') container.classList.add('pm-has-mini');
    if (this.opts.controls) this._buildControls(this.opts.controls === 'mini');
    if (this.opts.keys) this._bindKeys();
  };

  PortfolioMovie.prototype._buildControls = function (mini) {
    var self = this;
    var c = el('div', 'pm-controls' + (mini ? ' pm-controls-mini' : ''));
    function btn(cls, html, label, fn) {
      var b = el('button', 'pm-btn ' + cls, html);
      b.type = 'button'; b.setAttribute('aria-label', label); b.title = label;
      b.addEventListener('click', function (e) { e.stopPropagation(); fn(); });
      c.appendChild(b); return b;
    }
    this.btnPrev = btn('pm-btn-prev', '&#8249;', 'Previous', function () { self.pause(); self.prev(); });
    this.btnPlay = btn('pm-btn-play', '&#9654;', 'Play', function () { self.toggle(); });
    this.btnNext = btn('pm-btn-next', '&#8250;', 'Next', function () { self.pause(); self.next(); });
    this.counter = el('span', 'pm-counter', '');
    c.appendChild(this.counter);
    this.clock = el('span', 'pm-clock', '');
    c.appendChild(this.clock);
    var spacer = el('span', 'pm-spacer'); c.appendChild(spacer);
    if (!mini) {
      this.btnSpeed = btn('pm-btn-speed', '1×', 'Speed', function () {
        var s = self.opts.speed >= 2 ? 0.75 : self.opts.speed >= 1.5 ? 2 : self.opts.speed >= 1 ? 1.5 : 1;
        self.setSpeed(s);
      });
      this.btnIndex = btn('pm-btn-index', '&#9776;', 'Chapters', function () { self.toggleIndex(); });
    }
    if (this.opts.openUrl) {
      var a = el('a', 'pm-btn pm-btn-open', mini ? '&#10530;' : '&#10530; Open');
      a.href = this.opts.openUrl; a.title = 'Open the full presentation';
      a.addEventListener('click', function (e) { e.stopPropagation(); });
      c.appendChild(a);
    }
    this.btnFull = btn('pm-btn-full', '&#9974;', 'Fullscreen', function () { self.fullscreen(); });
    this.root.appendChild(c);
    this.controls = c;
    this._buildIndex();
  };

  PortfolioMovie.prototype._buildIndex = function () {
    var self = this;
    var ix = el('div', 'pm-index');
    var head = el('div', 'pm-index-head',
      '<span>Chapters</span><button type="button" class="pm-btn pm-index-close" aria-label="Close">&#10005;</button>');
    head.querySelector('button').addEventListener('click', function (e) { e.stopPropagation(); self.toggleIndex(false); });
    ix.appendChild(head);
    var list = el('ol', 'pm-index-list');
    (this.deck.chapters || []).forEach(function (ch, ci) {
      var li = el('li', 'pm-index-item');
      li.innerHTML = '<span class="pm-index-num">' + (ci + 1) + '</span>' +
        '<span class="pm-index-title">' + esc(ch.title) + '</span>' +
        '<span class="pm-index-count">' + (ch.slides || []).length + '</span>';
      li.addEventListener('click', function (e) {
        e.stopPropagation(); self.toggleIndex(false); self.gotoChapter(ch.id); self.play();
      });
      list.appendChild(li);
    });
    ix.appendChild(list);
    var extra = this.deck.extra || [];
    if (extra.length) {
      ix.appendChild(el('div', 'pm-index-sub', 'More screens (' + extra.length + ') — not in the film'));
      var grid = el('div', 'pm-index-grid');
      extra.forEach(function (x) {
        var fig = el('figure', 'pm-thumb');
        var im = el('img'); im.loading = 'lazy'; im.alt = x.title; im.src = self.opts.slideUrl(x.file);
        im.draggable = false;
        fig.appendChild(im);
        fig.appendChild(el('figcaption', null, esc(x.title)));
        fig.addEventListener('click', function (e) {
          e.stopPropagation(); self.toggleIndex(false); self.showLoose(x.file, x.title);
        });
        grid.appendChild(fig);
      });
      ix.appendChild(grid);
    }
    ix.addEventListener('click', function (e) { e.stopPropagation(); });
    this.index = ix;
    this.root.appendChild(ix);
  };

  PortfolioMovie.prototype.toggleIndex = function (force) {
    if (!this.index) return;
    var on = typeof force === 'boolean' ? force : !this.index.classList.contains('pm-open');
    this.index.classList.toggle('pm-open', on);
    if (on) this.pause();
  };

  PortfolioMovie.prototype._bindKeys = function () {
    var self = this;
    this._keyHandler = function (e) {
      if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      if (e.key === 'ArrowRight' || e.key === 'PageDown') { self.pause(); self.next(); }
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { self.pause(); self.prev(); }
      else if (e.key === ' ' || e.key === 'k') { e.preventDefault(); self.toggle(); }
      else if (e.key === 'Home') { self.pause(); self.goto(0); }
      else if (e.key === 'End') { self.pause(); self.goto(self.frames.length - 1); }
      else if (e.key === 'f') { self.fullscreen(); }
      else if (e.key === 'c') { self.toggleIndex(); }
      else if (e.key === 'Escape' && self.index && self.index.classList.contains('pm-open')) {
        // Consumed here: the host page must not treat this Escape as "leave".
        e.stopImmediatePropagation(); self.toggleIndex(false);
      }
      else return;
    };
    document.addEventListener('keydown', this._keyHandler);
  };

  /* ── Rendering ─────────────────────────────────────────────────────────── */

  PortfolioMovie.prototype._kenBurns = function (img, sec) {
    if (this._anim) { try { this._anim.cancel(); } catch (e) { /* noop */ } this._anim = null; }
    if (REDUCED || !img.animate) { img.style.transform = 'none'; return; }
    var cover = this.opts.fit === 'cover';
    var z0 = cover ? 1.04 : 1.0, z1 = cover ? 1.14 : 1.05;
    var dx = (Math.random() * 2 - 1) * (cover ? 3 : 1.6);
    var dy = (Math.random() * 2 - 1) * (cover ? 2.5 : 1.2);
    var zoomIn = Math.random() < 0.5;
    var from = 'translate(' + (-dx / 2) + '%, ' + (-dy / 2) + '%) scale(' + (zoomIn ? z0 : z1) + ')';
    var to = 'translate(' + (dx / 2) + '%, ' + (dy / 2) + '%) scale(' + (zoomIn ? z1 : z0) + ')';
    this._anim = img.animate([{ transform: from }, { transform: to }],
      { duration: (sec / this.opts.speed) * 1000 + FADE_MS * 2, easing: 'linear', fill: 'forwards' });
  };

  PortfolioMovie.prototype._renderCard = function (f) {
    var h = '';
    if (f.kind === 'hero') {
      var hero = f.hero || {};
      h += '<div class="pm-hero">';
      h += '<div class="pm-kicker">' + esc(hero.sub || 'Portfolio') + '</div>';
      h += '<h1 class="pm-hero-name">' + esc(hero.name || '') + '</h1>';
      h += '<p class="pm-hero-tag">' + esc(hero.tagline || '') + '</p>';
      if (hero.facts && hero.facts.length) {
        h += '<div class="pm-facts">';
        hero.facts.forEach(function (x) {
          h += '<div class="pm-fact"><div class="pm-fact-k">' + esc(x.k) + '</div><div class="pm-fact-v">' + esc(x.v) + '</div></div>';
        });
        h += '</div>';
      }
      h += '</div>';
    } else if (f.kind === 'chapter') {
      h += '<div class="pm-chapter"><div class="pm-kicker">Chapter ' + f.num + '</div>' +
        '<h2 class="pm-chapter-title">' + esc(f.title) + '</h2>' +
        (f.lead ? '<p class="pm-chapter-lead">' + esc(f.lead) + '</p>' : '') + '</div>';
    } else { // text
      h += '<div class="pm-text"><div class="pm-kicker">' + esc(f.chapter || '') + '</div>' +
        '<h2 class="pm-chapter-title">' + esc(f.title) + '</h2>' +
        (f.what ? '<p class="pm-chapter-lead">' + esc(f.what) + '</p>' : '');
      if (f.points && f.points.length) {
        h += '<ul class="pm-points">' + f.points.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') + '</ul>';
      }
      h += '</div>';
    }
    this.card.innerHTML = h;
    this.card.classList.add('pm-on');
    this.caption.classList.remove('pm-on');
  };

  PortfolioMovie.prototype._renderCaption = function (f) {
    var h = '<div class="pm-cap-kicker">' + (f.num ? '<span class="pm-cap-num">' + f.num + '</span>' : '') + esc(f.chapter || '') + '</div>' +
      '<div class="pm-cap-title">' + esc(f.title) + '</div>' +
      (f.what ? '<div class="pm-cap-what">' + esc(f.what) + '</div>' : '');
    if (f.points && f.points.length) {
      h += '<ul class="pm-cap-points">' + f.points.map(function (p, i) {
        return '<li style="animation-delay:' + (0.9 + i * 0.45) + 's">' + esc(p) + '</li>';
      }).join('') + '</ul>';
    }
    this.caption.innerHTML = h;
    // restart the entrance animations
    this.caption.classList.remove('pm-on');
    void this.caption.offsetWidth;
    this.caption.classList.add('pm-on');
    this.card.classList.remove('pm-on');
  };

  PortfolioMovie.prototype._swapTo = function (file, sec, done) {
    var self = this;
    var back = this.layers[1 - this._front];
    var front = this.layers[this._front];
    var url = this.opts.slideUrl(file);
    var fired = false;
    function go() {
      if (fired || self._destroyed) return; fired = true;
      back.classList.add('pm-on');
      front.classList.remove('pm-on');
      self._front = 1 - self._front;
      self._kenBurns(back, sec);
      if (done) done();
    }
    back.onload = null; back.onerror = null;
    back.src = url;
    var p = back.decode ? back.decode() : Promise.resolve();
    p.then(go, go);
    setTimeout(go, 1500); // never stall on a slow decode
  };

  PortfolioMovie.prototype._hidePictures = function () {
    this.layers.forEach(function (im) { im.classList.remove('pm-on'); });
    if (this._anim) { try { this._anim.cancel(); } catch (e) { /* noop */ } this._anim = null; }
  };

  PortfolioMovie.prototype._preload = function (i) {
    var f = this.frames[i];
    if (f && f.file) { var im = new Image(); im.src = this.opts.slideUrl(f.file); }
  };

  /* ── Navigation ────────────────────────────────────────────────────────── */

  PortfolioMovie.prototype.goto = function (i, silent) {
    if (!this.frames.length) return;
    i = clamp(i | 0, 0, this.frames.length - 1);
    var f = this.frames[i];
    this.idx = i;
    this.elapsed = 0;
    this._loose = null;
    this.root.setAttribute('data-kind', f.kind);
    if (f.kind === 'slide') {
      this._renderCaption(f);
      this._swapTo(f.file, f.sec);
    } else {
      this._hidePictures();
      this._renderCard(f);
    }
    for (var k = 1; k <= 2; k++) this._preload(i + k);
    this._updateUi();
    if (!silent && this.opts.onFrame) this.opts.onFrame(i, f);
  };

  PortfolioMovie.prototype.next = function () {
    if (this.idx >= this.frames.length - 1) {
      this.pause();
      if (this.opts.onEnd) this.opts.onEnd();
      return;
    }
    this.goto(this.idx + 1);
  };
  PortfolioMovie.prototype.prev = function () { this.goto(Math.max(0, this.idx - 1)); };

  PortfolioMovie.prototype.gotoChapter = function (id) {
    for (var i = 0; i < this.frames.length; i++) {
      if (this.frames[i].kind === 'chapter' && this.frames[i].chapterId === id) { this.goto(i); return; }
    }
  };

  PortfolioMovie.prototype.seekTo = function (sec) {
    var acc = 0;
    for (var i = 0; i < this.frames.length; i++) {
      if (sec < acc + this.frames[i].sec) { this.goto(i); this.elapsed = sec - acc; this._updateUi(); return; }
      acc += this.frames[i].sec;
    }
    this.goto(this.frames.length - 1);
  };

  /* Show one picture that is not in the film (the "more screens" grid). */
  PortfolioMovie.prototype.showLoose = function (file, title) {
    this.pause();
    this._loose = { file: file, title: title };
    this.root.setAttribute('data-kind', 'loose');
    this.caption.innerHTML = '<div class="pm-cap-kicker">More screens</div><div class="pm-cap-title">' + esc(title) + '</div>';
    this.caption.classList.remove('pm-on'); void this.caption.offsetWidth; this.caption.classList.add('pm-on');
    this.card.classList.remove('pm-on');
    this._swapTo(file, 8);
  };

  /* ── Clock ─────────────────────────────────────────────────────────────── */

  PortfolioMovie.prototype.play = function () {
    if (this.playing || !this.frames.length) return;
    if (this.idx >= this.frames.length - 1 && this.elapsed >= this.frames[this.idx].sec - 0.01) this.goto(0);
    if (this._loose) this.goto(this.idx);
    this.playing = true;
    this.root.classList.add('pm-playing');
    this._lastTs = 0;
    var self = this;
    var tick = function (ts) {
      if (!self.playing || self._destroyed) return;
      if (self._lastTs) self.elapsed += ((ts - self._lastTs) / 1000) * self.opts.speed;
      self._lastTs = ts;
      var f = self.frames[self.idx];
      if (self.elapsed >= f.sec) {
        if (self.idx >= self.frames.length - 1) { self.elapsed = f.sec; self._updateUi(); self.next(); return; }
        self.goto(self.idx + 1);
      }
      self._updateUi();
      self._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
    this._updateUi();
    if (this.opts.onState) this.opts.onState(true);
  };

  PortfolioMovie.prototype.pause = function () {
    if (!this.playing) return;
    this.playing = false;
    this.root.classList.remove('pm-playing');
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
    if (this._anim && this._anim.pause) { try { this._anim.pause(); } catch (e) { /* noop */ } }
    this._updateUi();
    if (this.opts.onState) this.opts.onState(false);
  };

  PortfolioMovie.prototype.toggle = function () { this.playing ? this.pause() : this.play(); };

  PortfolioMovie.prototype.setSpeed = function (s) {
    this.opts.speed = s;
    if (this.btnSpeed) this.btnSpeed.textContent = (s % 1 ? s.toFixed(2).replace(/0+$/, '') : s) + '×';
    var f = this.frames[this.idx];
    if (f && f.kind === 'slide') this._kenBurns(this.layers[this._front], Math.max(0.5, f.sec - this.elapsed));
  };

  PortfolioMovie.prototype.fullscreen = function () {
    var r = this.opts.fullscreenTarget || this.root;
    if (document.fullscreenElement) { document.exitFullscreen(); }
    else if (r.requestFullscreen) { r.requestFullscreen().catch(function () { /* denied */ }); }
  };

  PortfolioMovie.prototype.timeBefore = function (i) {
    var acc = 0;
    for (var k = 0; k < i && k < this.frames.length; k++) acc += this.frames[k].sec;
    return acc;
  };

  function mmss(s) { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }

  PortfolioMovie.prototype._updateUi = function () {
    var f = this.frames[this.idx];
    if (!f) return;
    var pos = this.timeBefore(this.idx) + Math.min(this.elapsed, f.sec);
    this.barFill.style.width = (pos / this.total * 100) + '%';
    if (this.counter) this.counter.textContent = (this.idx + 1) + ' / ' + this.frames.length;
    if (this.clock) this.clock.textContent = mmss(pos) + ' / ' + mmss(this.total);
    if (this.btnPlay) {
      this.btnPlay.innerHTML = this.playing ? '&#10074;&#10074;' : '&#9654;';
      this.btnPlay.setAttribute('aria-label', this.playing ? 'Pause' : 'Play');
    }
    if (this.btnPrev) this.btnPrev.disabled = this.idx <= 0;
    if (this.index) {
      var items = this.index.querySelectorAll('.pm-index-item');
      for (var i = 0; i < items.length; i++) items[i].classList.toggle('pm-current', i === f.chapterIdx);
    }
  };

  PortfolioMovie.prototype.destroy = function () {
    this._destroyed = true;
    this.pause();
    if (this._keyHandler) document.removeEventListener('keydown', this._keyHandler);
    this.root.innerHTML = '';
    this.root.classList.remove('pm', 'pm-fit-contain', 'pm-fit-cover', 'pm-playing');
  };

  PortfolioMovie.flatten = flatten;
  PortfolioMovie.frameSeconds = frameSeconds;
  global.PortfolioMovie = PortfolioMovie;
})(window);
