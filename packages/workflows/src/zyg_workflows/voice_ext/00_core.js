// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/00_core.js — Voice Bridge core.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script, so this file may only
 * REGISTER at top level: tables, functions, one DOMContentLoaded hook. Nothing here
 * touches the DOM or a studio global until run()/el()/VB.ready fire.
 *
 * Provides: the action registry, a tiny event bus, VB.waitFor, a strictly serial
 * executor with id de-duplication + ack, the SSE client, and the hello handshake.
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB = W.VB || {};

  VB.actions = VB.actions || {};   // name -> {view,label,aliases,args,el,run,say}
  VB.aliases = VB.aliases || {};   // spoken phrase -> action name
  VB.ready = VB.ready || [];       // callbacks run once on DOMContentLoaded
  VB.views = VB.views || {};       // view id -> free-form per-studio notes
  VB.log = VB.log || [];           // last 100 events
  VB.state = 'idle';               // idle | listening | thinking | acting | speaking

  var LOG_MAX = 100;
  var SEEN_MAX = 500;
  var HELLO_URL = '/inspect/api/voice/hello';
  var ACK_URL = '/inspect/api/voice/ack';
  var EVENTS_URL = '/inspect/api/voice/events';

  /* ---------------------------------------------------------------- storage */

  function lsGet(key) {
    try { return (W.localStorage && W.localStorage.getItem(key)) || null; } catch (e) { return null; }
  }
  function lsSet(key, value) {
    try {
      if (!W.localStorage) return;
      if (value === null || value === undefined || value === '') W.localStorage.removeItem(key);
      else W.localStorage.setItem(key, String(value));
    } catch (e) { /* private mode */ }
  }

  // The ONE tab that executes actions holds this token; other tabs only watch.
  VB.driver = lsGet('vb.driver') || null;

  /* -------------------------------------------------------------- event bus */

  var handlers = {};

  VB.on = function (evt, fn) {
    if (typeof fn !== 'function') return fn;
    (handlers[evt] = handlers[evt] || []).push(fn);
    return fn;
  };

  VB.off = function (evt, fn) {
    var list = handlers[evt] || [];
    var i = list.indexOf(fn);
    if (i >= 0) list.splice(i, 1);
    return fn;
  };

  VB.emit = function (evt, data) {
    var rec = { t: Date.now(), evt: evt, data: data };
    VB.log.push(rec);
    if (VB.log.length > LOG_MAX) VB.log.splice(0, VB.log.length - LOG_MAX);
    var list = (handlers[evt] || []).concat(handlers['*'] || []);
    for (var i = 0; i < list.length; i++) {
      try { list[i](data, evt); } catch (e) { /* a listener must never break the queue */ }
    }
    return rec;
  };

  VB.setState = function (s) {
    if (VB.state !== s) { VB.state = s; VB.emit('state', s); }
    return VB.state;
  };

  /* ----------------------------------------------------------------- basics */

  VB.waitFor = function (fn, ms) {
    var limit = (typeof ms === 'number' && ms > 0) ? ms : 4000;
    return new Promise(function (resolve, reject) {
      var first = null;
      try { first = fn(); } catch (e) { first = null; }
      if (first) { resolve(first); return; }
      var waited = 0;
      var timer = setInterval(function () {
        var got = null;
        try { got = fn(); } catch (e) { got = null; }
        if (got) { clearInterval(timer); resolve(got); return; }
        waited += 50;
        if (waited >= limit) { clearInterval(timer); reject(new Error('waitFor timed out after ' + limit + ' ms')); }
      }, 50);
    });
  };

  VB.currentView = function () {
    var hash = '';
    try { hash = (W.location && W.location.hash) || ''; } catch (e) { hash = ''; }
    return String(hash).replace('#', '') || 'home';
  };

  VB.reindex = function () {
    var map = {};
    Object.keys(VB.actions).forEach(function (name) {
      var spec = VB.actions[name] || {};
      (spec.aliases || []).forEach(function (a) {
        var k = String(a || '').trim().toLowerCase();
        if (k && !map[k]) map[k] = name;
      });
    });
    VB.aliases = map;
    return map;
  };

  VB.registry = function () {
    VB.reindex();
    return Object.keys(VB.actions).sort().map(function (name) {
      var spec = VB.actions[name] || {};
      return {
        name: name,
        view: spec.view || 'home',
        label: spec.label || name,
        aliases: (spec.aliases || []).slice(),
        args: spec.args || null
      };
    });
  };

  /* ------------------------------------------------------------------- HTTP */

  function post(url, payload) {
    try {
      if (typeof W.fetch !== 'function') return Promise.resolve(null);
      return W.fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (r) {
        if (!r || typeof r.json !== 'function') return null;
        return Promise.resolve(r.json()).catch(function () { return null; });
      }).catch(function () { return null; });
    } catch (e) {
      return Promise.resolve(null);
    }
  }
  VB.post = post;

  VB.ack = function (payload) { return post(ACK_URL, payload); };

  // Only the driver tab says hello; watchers stay silent — the same rule
  // VB.connect follows. The server keys the registry on the driver token and
  // answers 400 without one, so a token-less handshake is a console error on
  // every page load of every watcher tab, and a registry the server throws away.
  VB.hello = function () {
    if (!VB.driver) return Promise.resolve(null);
    return post(HELLO_URL, {
      driver: VB.driver,
      registry: VB.registry(),
      view: VB.currentView()
    });
  };

  // hashchange re-send: the view only, the registry has not moved.
  VB.helloView = function () {
    if (!VB.driver) return Promise.resolve(null);
    return post(HELLO_URL, { driver: VB.driver, view: VB.currentView() });
  };

  /* --------------------------------------------------------------- executor */

  var seen = new Set();
  var seenOrder = [];
  var queue = [];
  var running = false;
  var seq = 0;

  function firstTime(id) {
    if (seen.has(id)) return false;
    seen.add(id);
    seenOrder.push(id);
    while (seenOrder.length > SEEN_MAX) seen.delete(seenOrder.shift());
    return true;
  }

  function pointAt(spec, args) {
    if (!VB.cursor || typeof spec.el !== 'function') return Promise.resolve(null);
    var el = null;
    try { el = spec.el(args); } catch (e) { el = null; }
    if (!el) return Promise.resolve(null);
    var moved = null;
    try {
      if (typeof VB.cursor.moveTo === 'function') moved = VB.cursor.moveTo(el);
    } catch (e) { moved = null; }
    return Promise.resolve(moved).catch(function () { return null; }).then(function () {
      try { if (typeof VB.cursor.highlight === 'function') VB.cursor.highlight(el, 900); } catch (e) { /* cosmetic */ }
      return el;
    });
  }

  function runOne(action) {
    var name = String(action.name || '');
    var args = action.args || {};
    var spec = VB.actions[name];

    if (!spec || typeof spec.run !== 'function') {
      var miss = { id: action.id, name: name, ok: false, error: 'unknown action', view: VB.currentView() };
      VB.emit('action', { phase: 'error', id: action.id, name: name, args: args, error: miss.error });
      VB.ack(miss);
      return Promise.resolve(miss);
    }

    VB.setState('acting');
    VB.emit('action', { phase: 'start', id: action.id, name: name, args: args, label: spec.label || name });

    return pointAt(spec, args)
      .then(function () { return spec.run(args); })
      .then(function (res) {
        var detail = (typeof res === 'string') ? res : ((res && res.detail) || null);
        var ok = {
          id: action.id, name: name, ok: true, detail: detail,
          view: VB.currentView(), say: spec.say || ''
        };
        VB.emit('action', { phase: 'done', id: action.id, name: name, args: args, detail: detail });
        VB.ack(ok);
        return ok;
      }, function (err) {
        var bad = {
          id: action.id, name: name, ok: false,
          error: (err && err.message) ? err.message : String(err),
          view: VB.currentView()
        };
        VB.emit('action', { phase: 'error', id: action.id, name: name, args: args, error: bad.error });
        VB.ack(bad);
        return bad;
      });
  }

  function pump() {
    if (running) return;
    var job = queue.shift();
    if (!job) { if (VB.state === 'acting') VB.setState('idle'); return; }
    running = true;
    runOne(job.action).then(function (result) {
      running = false;
      job.resolve(result);
      pump();
    });
  }

  // Actions run strictly one after another; duplicates of an id are dropped.
  VB.exec = function (action) {
    var act = action || {};
    if (!act.id) act.id = 'local-' + (++seq);
    if (!firstTime(act.id)) {
      VB.emit('action', { phase: 'duplicate', id: act.id, name: act.name });
      return Promise.resolve({ id: act.id, ok: true, duplicate: true });
    }
    // "stop" must not wait behind the actions it is meant to cancel.
    if (act.name === 'core.stop') {
      var dropped = VB.stop();
      var stopped = {
        id: act.id, name: 'core.stop', ok: true,
        detail: 'dropped ' + dropped, view: VB.currentView(), say: ''
      };
      VB.emit('action', { phase: 'done', id: act.id, name: 'core.stop', detail: stopped.detail });
      VB.ack(stopped);
      return Promise.resolve(stopped);
    }
    return new Promise(function (resolve) {
      queue.push({ action: act, resolve: resolve });
      VB.emit('action', { phase: 'queued', id: act.id, name: act.name, queued: queue.length });
      pump();
    });
  };

  // Abort everything still queued (the action already running finishes its own turn).
  VB.stop = function () {
    var dropped = queue.splice(0, queue.length);
    dropped.forEach(function (job) {
      try { job.resolve({ id: job.action.id, ok: false, error: 'aborted' }); } catch (e) { /* ignore */ }
    });
    VB.setState(running ? 'acting' : 'idle');
    VB.emit('stop', { dropped: dropped.length });
    return dropped.length;
  };

  VB.pending = function () { return queue.length + (running ? 1 : 0); };

  /* ---------------------------------------------------------- core actions */

  VB.actions['core.stop'] = {
    view: 'home',
    label: 'Stop what you are doing',
    aliases: ['stop', 'stop it', 'cancel that', 'abort', 'never mind'],
    args: null,
    el: function () { return null; },
    run: function () { var n = VB.stop(); return 'dropped ' + n; },
    say: ''
  };

  VB.actions['core.say'] = {
    view: 'home',
    label: 'Say a sentence out loud',
    aliases: ['say', 'speak', 'repeat after me'],
    args: { text: 'string, the sentence to speak' },
    el: function () { return null; },
    run: function (args) {
      var text = (args && args.text) ? String(args.text) : '';
      if (!text) return 'nothing to say';
      if (typeof VB.speak !== 'function') return 'no voice';
      return Promise.resolve(VB.speak(text)).then(function () { return 'said'; });
    },
    say: ''
  };

  /* ---------------------------------------------------------------- SSE */

  var source = null;
  var backoff = 1000;
  var retryTimer = null;

  function parseEvent(ev) {
    if (!ev || typeof ev.data !== 'string') return null;
    try { return JSON.parse(ev.data); } catch (e) { return null; }
  }

  function scheduleReconnect() {
    if (retryTimer || !VB.driver) return;
    var wait = backoff;
    backoff = Math.min(backoff * 2, 10000);
    retryTimer = setTimeout(function () { retryTimer = null; VB.connect(); }, wait);
    VB.emit('sse', { state: 'retry', in_ms: wait });
  }

  VB.disconnect = function () {
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    if (source) { try { source.close(); } catch (e) { /* ignore */ } source = null; }
    VB.emit('sse', { state: 'closed' });
    return null;
  };

  // Only the driver tab opens the stream; watchers stay silent.
  VB.connect = function () {
    if (!VB.driver) return null;
    if (typeof W.EventSource !== 'function') return null;
    VB.disconnect();

    try {
      source = new W.EventSource(EVENTS_URL + '?driver=' + encodeURIComponent(VB.driver));
    } catch (e) {
      source = null;
      scheduleReconnect();
      return null;
    }

    source.addEventListener('open', function () { backoff = 1000; VB.emit('sse', { state: 'open' }); });

    source.addEventListener('action', function (ev) {
      var d = parseEvent(ev);
      if (d && d.name) VB.exec(d);
    });

    source.addEventListener('say', function (ev) {
      var d = parseEvent(ev);
      if (!d) return;
      VB.emit('say', d);
      if (typeof VB.speak === 'function') {
        try { VB.speak(d.text || '', d.wav || null); } catch (e) { /* audio is best effort */ }
      }
    });

    source.addEventListener('status', function (ev) {
      var d = parseEvent(ev);
      VB.emit('status', d !== null ? d : ((ev && ev.data) || ''));
    });

    source.onerror = function () {
      if (source) { try { source.close(); } catch (e) { /* ignore */ } source = null; }
      VB.emit('sse', { state: 'error' });
      scheduleReconnect();
    };

    VB.emit('sse', { state: 'connecting' });
    return source;
  };

  VB.setDriver = function (token) {
    VB.driver = token || null;
    lsSet('vb.driver', VB.driver);
    VB.emit('driver', VB.driver);
    if (VB.driver) VB.connect(); else VB.disconnect();
    return VB.driver;
  };

  /* ---------------------------------------------------------------- boot */

  VB.boot = function () {
    if (VB._booted) return VB;
    VB._booted = true;
    var callbacks = VB.ready.splice(0, VB.ready.length);
    callbacks.forEach(function (fn) {
      try { fn(VB); } catch (e) { VB.emit('error', { where: 'ready', message: (e && e.message) || String(e) }); }
    });
    // Anything registered after boot runs immediately.
    VB.ready.push = function (fn) {
      try { if (typeof fn === 'function') fn(VB); } catch (e) { VB.emit('error', { where: 'ready', message: (e && e.message) || String(e) }); }
      return 0;
    };
    VB.hello();
    VB.connect();
    VB.emit('boot', { view: VB.currentView(), actions: Object.keys(VB.actions).length });
    return VB;
  };

  try {
    var doc = W.document;
    if (doc && typeof doc.addEventListener === 'function') {
      if (doc.readyState === 'complete' || doc.readyState === 'interactive') {
        if (typeof W.setTimeout === 'function') W.setTimeout(function () { VB.boot(); }, 0);
      } else {
        doc.addEventListener('DOMContentLoaded', function () { VB.boot(); });
      }
    }
    if (typeof W.addEventListener === 'function') {
      W.addEventListener('hashchange', function () {
        VB.emit('view', VB.currentView());
        VB.helloView();
      });
    }
  } catch (e) { /* no DOM (checker / tests) */ }
})();
