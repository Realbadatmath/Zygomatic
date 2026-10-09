// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/03_panel_extras.js — the two blocks 02_mic.js leaves empty in the
 * Voice Bridge panel: speaker enrolment and the reply-voice picker.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script, so nothing here may
 * touch the DOM at parse time: everything runs inside init(), which the core
 * drains off VB.ready, and which first waits (VB.waitFor) for the two host divs
 * #vb-panel-speaker and #vb-panel-voice that 02_mic.js renders.
 *
 * Server seam (voice_ext/speaker.py, voice_ext/tts.py, ext dispatch):
 *   GET  /inspect/api/voice/ext/speaker/list    -> {ok, speakers:[{name,slug,n_windows,seconds,created}], count}
 *   POST /inspect/api/voice/ext/speaker/enrol   {name, audio_b64, mime}
 *   POST /inspect/api/voice/ext/speaker/delete  {name|slug}
 *   GET/POST .../speaker/config                 {speaker_threshold, speaker_gate}
 *   GET  /inspect/api/voice/ext/tts/voices      -> {ok, voices:[{id,name,role,has_active_preset}], voice_id, engine}
 *   GET/POST .../tts/config                     {voice_id, engine}  (+ engines, resolved_engine)
 *   GET  .../tts/say?text=...                   -> the wav itself
 *
 * The 30 s enrolment recorder uses VB.mic.recordFor(ms) when 02_mic.js exposes
 * it; it does not today, so this file opens its own getUserMedia stream with a
 * MediaRecorder and closes it again the moment the take is finished.
 */
(function () {
  'use strict';

  var VB = window.VB = window.VB || { actions: {}, aliases: {}, ready: [], views: {} };

  var API        = '/inspect/api/voice/ext/';
  var ENROL_MS   = 30000;   /* speaker.py wants >= 20 s; 30 s leaves a margin   */
  var TICK_MS    = 100;     /* progress-ring refresh                           */
  var MIME       = 'audio/webm;codecs=opus';
  var THR_MIN    = 0.30;
  var THR_MAX    = 0.80;
  var ENGINES    = ['auto', 'indextts2', 'chatterbox'];
  var TEST_TEXT  = 'Opening Video Studio';
  var PRERENDER_NOTE = 're-render fixed phrases: tools/vb_prerender.py --clear';

  /* ── state (read by the smoke test) ───────────────────────────────────────── */
  var X = VB.panelExtras = VB.panelExtras || {};
  X.speakers  = [];
  X.voices    = [];
  X.speakerCfg = { speaker_threshold: 0.55, speaker_gate: false };
  X.voiceCfg  = { voice_id: '', engine: 'auto' };
  X.recording = false;
  X.error     = '';

  var els = {};
  var inited = false;
  var recTimer = 0;

  /* ── tiny helpers ─────────────────────────────────────────────────────────── */
  function el(tag, attrs, text) {
    var n = document.createElement(tag), k;
    if (attrs) for (k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function getJSON(url) {
    return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (r) {
      return r.json();
    });
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }

  function note(msg, bad) {
    X.error = bad ? String(msg || '') : '';
    if (!els.msg) return;
    els.msg.textContent = msg || '';
    els.msg.className = 'vb-m' + (bad ? ' vb-no' : '');
  }

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  function blobToB64(blob) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onload = function () {
        var s = String(fr.result || '');
        var comma = s.indexOf(',');
        resolve(comma >= 0 ? s.slice(comma + 1) : s);
      };
      fr.onerror = function () { reject(new Error('could not read the recording')); };
      fr.readAsDataURL(blob);
    });
  }

  /* ── CSS (the panel's own classes come from 02_mic.js) ────────────────────── */
  var CSS = [
    '#vb-panel .vb-ring{width:26px;height:26px;flex:0 0 26px;}',
    '#vb-panel .vb-ring circle{fill:none;stroke-width:3;}',
    '#vb-panel .vb-ring .vb-ring-bg{stroke:var(--line,#383842);}',
    '#vb-panel .vb-ring .vb-ring-fg{stroke:var(--acc,#00e5ff);transform:rotate(-90deg);',
    '  transform-origin:13px 13px;transition:stroke-dashoffset .1s linear;}',
    '#vb-panel .vb-spk{display:flex;align-items:center;gap:6px;padding:2px 0;}',
    '#vb-panel .vb-spk .vb-spk-n{color:var(--txt,#e4e4e7);}',
    '#vb-panel .vb-spk .vb-spk-m{color:var(--muted,#a1a1aa);font-size:11px;margin-left:auto;}',
    '#vb-panel .vb-spk button.vb-b{padding:1px 7px;}',
    '#vb-panel #vb-voice-sel{max-width:230px;width:230px;}',
    '#vb-panel #vb-voice-filter{max-width:230px;width:230px;}',
    '#vb-panel .vb-hint{color:var(--muted,#a1a1aa);font-size:11px;margin:4px 0 2px;word-break:break-word;}'
  ].join('\n');

  /* ══ speaker block ═════════════════════════════════════════════════════════ */
  function buildSpeaker(host) {
    host.innerHTML =
      '<h4>Speaker</h4>' +
      '<div class="vb-row"><span class="vb-k">name</span>' +
        '<input id="vb-spk-name" type="text" placeholder="who is speaking" autocomplete="off">' +
        '<button class="vb-b" id="vb-spk-rec">Record 30 s</button></div>' +
      '<div class="vb-row"><span class="vb-k">take</span>' +
        '<svg class="vb-ring" viewBox="0 0 26 26" aria-hidden="true">' +
          '<circle class="vb-ring-bg" cx="13" cy="13" r="11"></circle>' +
          '<circle class="vb-ring-fg" id="vb-spk-ring" cx="13" cy="13" r="11"></circle>' +
        '</svg>' +
        '<span class="vb-m" id="vb-spk-msg">not recording</span></div>' +
      '<div id="vb-spk-list"></div>' +
      '<div class="vb-row"><span class="vb-k">gate</span>' +
        '<label><input id="vb-spk-gate" type="checkbox"> only enrolled voices act</label></div>' +
      '<div class="vb-row"><span class="vb-k">threshold</span>' +
        '<input id="vb-spk-thr" type="range" min="0.3" max="0.8" step="0.01">' +
        '<b id="vb-spk-thr-v">0.55</b></div>';

    els.spkName = host.querySelector('#vb-spk-name');
    els.spkRec  = host.querySelector('#vb-spk-rec');
    els.ring    = host.querySelector('#vb-spk-ring');
    els.msg     = host.querySelector('#vb-spk-msg');
    els.spkList = host.querySelector('#vb-spk-list');
    els.gate    = host.querySelector('#vb-spk-gate');
    els.thr     = host.querySelector('#vb-spk-thr');
    els.thrVal  = host.querySelector('#vb-spk-thr-v');

    var circ = 2 * Math.PI * 11;
    els.ring.setAttribute('stroke-dasharray', circ.toFixed(2));
    els.ring.setAttribute('stroke-dashoffset', circ.toFixed(2));
    els.ringCirc = circ;

    els.spkRec.addEventListener('click', function () { enrol(); });
    els.gate.addEventListener('change', function () {
      saveSpeakerCfg({ speaker_gate: !!els.gate.checked });
    });
    els.thr.addEventListener('input', function () {
      els.thrVal.textContent = Number(els.thr.value).toFixed(2);
    });
    els.thr.addEventListener('change', function () {
      saveSpeakerCfg({ speaker_threshold: Number(els.thr.value) });
    });
  }

  function renderSpeakers() {
    if (!els.spkList) return;
    els.spkList.innerHTML = '';
    if (!X.speakers.length) {
      els.spkList.appendChild(el('div', { 'class': 'vb-m' }, 'nobody enrolled yet'));
      return;
    }
    X.speakers.forEach(function (s) {
      var row = el('div', { 'class': 'vb-spk', 'data-speaker': s.slug || s.name || '' });
      row.appendChild(el('span', { 'class': 'vb-spk-n' }, s.name || s.slug || '?'));
      var meta = [];
      if (s.n_windows != null) meta.push(s.n_windows + ' windows');
      if (s.seconds != null) meta.push(Number(s.seconds).toFixed(0) + ' s');
      row.appendChild(el('span', { 'class': 'vb-spk-m' }, meta.join(' · ')));
      var del = el('button', { 'class': 'vb-b vb-spk-del', title: 'forget this speaker' }, 'delete');
      del.addEventListener('click', function () { removeSpeaker(s); });
      row.appendChild(del);
      els.spkList.appendChild(row);
    });
  }

  function renderSpeakerCfg() {
    if (!els.thr) return;
    var thr = clamp(Number(X.speakerCfg.speaker_threshold), THR_MIN, THR_MAX);
    if (!isFinite(thr)) thr = 0.55;
    els.thr.value = String(thr);
    els.thrVal.textContent = thr.toFixed(2);
    els.gate.checked = !!X.speakerCfg.speaker_gate;
  }

  function loadSpeakers() {
    return getJSON(API + 'speaker/list').then(function (j) {
      X.speakers = (j && j.speakers) || [];
      renderSpeakers();
    })['catch'](function (e) { note('speaker list failed: ' + e.message, true); });
  }

  function loadSpeakerCfg() {
    return getJSON(API + 'speaker/config').then(function (j) {
      if (j && j.speaker_threshold != null) X.speakerCfg.speaker_threshold = j.speaker_threshold;
      if (j && j.speaker_gate != null) X.speakerCfg.speaker_gate = j.speaker_gate;
      renderSpeakerCfg();
    })['catch'](function (e) { note('speaker config failed: ' + e.message, true); });
  }

  function saveSpeakerCfg(patch) {
    return postJSON(API + 'speaker/config', patch).then(function (j) {
      if (j && j.error) { note(j.error, true); return; }
      if (j && j.speaker_threshold != null) X.speakerCfg.speaker_threshold = j.speaker_threshold;
      if (j && j.speaker_gate != null) X.speakerCfg.speaker_gate = j.speaker_gate;
      renderSpeakerCfg();
      note('saved');
    })['catch'](function (e) { note('save failed: ' + e.message, true); });
  }

  function removeSpeaker(s) {
    return postJSON(API + 'speaker/delete', { name: s.name, slug: s.slug })
      .then(function (j) {
        if (j && j.error) { note(j.error, true); return; }
        note('deleted ' + (s.name || s.slug));
        return loadSpeakers();
      })['catch'](function (e) { note('delete failed: ' + e.message, true); });
  }

  /* ── the 30 s take ────────────────────────────────────────────────────────── */
  function ringTo(fraction) {
    if (!els.ring) return;
    var c = els.ringCirc;
    els.ring.setAttribute('stroke-dashoffset', (c * (1 - clamp(fraction, 0, 1))).toFixed(2));
  }

  /* 02_mic.js may one day expose VB.mic.recordFor(ms); until it does, open our
     own stream and close it again straight after the take. */
  function recordFor(ms) {
    if (VB.mic && typeof VB.mic.recordFor === 'function') return VB.mic.recordFor(ms);
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
      return Promise.reject(new Error('this browser has no microphone API'));
    if (typeof window.MediaRecorder !== 'function')
      return Promise.reject(new Error('this browser has no MediaRecorder'));

    var audio = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
    var devId = VB.mic && VB.mic.deviceId;
    if (devId) audio.deviceId = { exact: devId };

    return navigator.mediaDevices.getUserMedia({ audio: audio }).then(function (stream) {
      return new Promise(function (resolve, reject) {
        var opts = {};
        try {
          if (window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(MIME))
            opts = { mimeType: MIME, audioBitsPerSecond: 32000 };
        } catch (e) { opts = {}; }
        var rec, chunks = [], stopAt = 0;
        function shut() {
          if (stopAt) { clearTimeout(stopAt); stopAt = 0; }
          try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { /* gone */ }
        }
        try { rec = new window.MediaRecorder(stream, opts); }
        catch (e) { shut(); reject(new Error('MediaRecorder refused the stream: ' + e.message)); return; }
        rec.ondataavailable = function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); };
        rec.onerror = function (ev) { shut(); reject(new Error('recorder error: ' + ((ev && ev.error && ev.error.message) || 'unknown'))); };
        rec.onstop = function () {
          shut();
          resolve(new Blob(chunks, { type: rec.mimeType || MIME }));
        };
        rec.start();
        stopAt = setTimeout(function () { try { rec.stop(); } catch (e) { /* already stopped */ } }, ms);
      });
    });
  }

  function enrol() {
    if (X.recording) return Promise.resolve();
    var name = (els.spkName && els.spkName.value || '').trim();
    if (!name) { note('give the speaker a name first', true); return Promise.resolve(); }

    X.recording = true;
    els.spkRec.disabled = true;
    els.spkRec.classList.add('on');
    var started = Date.now();
    ringTo(0);
    note('recording 30 s — keep talking');
    recTimer = setInterval(function () {
      var done = (Date.now() - started) / ENROL_MS;
      ringTo(done);
      var left = Math.max(0, Math.ceil((ENROL_MS - (Date.now() - started)) / 1000));
      note('recording — ' + left + ' s left');
    }, TICK_MS);

    function finish() {
      if (recTimer) { clearInterval(recTimer); recTimer = 0; }
      X.recording = false;
      els.spkRec.disabled = false;
      els.spkRec.classList.remove('on');
      ringTo(0);
    }

    return recordFor(ENROL_MS).then(function (blob) {
      ringTo(1);
      note('sending ' + Math.round(blob.size / 1024) + ' kB');
      return blobToB64(blob).then(function (b64) {
        return postJSON(API + 'speaker/enrol', {
          name: name, audio_b64: b64, mime: blob.type || MIME
        });
      });
    }).then(function (j) {
      finish();
      if (j && j.error) { note(j.error, true); return; }
      note('enrolled ' + name);
      if (els.spkName) els.spkName.value = '';
      return loadSpeakers();
    })['catch'](function (e) {
      finish();
      note('enrol failed: ' + e.message, true);
    });
  }

  /* ══ reply-voice block ═════════════════════════════════════════════════════ */
  function buildVoice(host) {
    host.innerHTML =
      '<h4>Reply voice</h4>' +
      '<div class="vb-row"><span class="vb-k">search</span>' +
        '<input id="vb-voice-filter" type="text" placeholder="filter 326 voices" autocomplete="off"></div>' +
      '<div class="vb-row"><span class="vb-k">voice</span>' +
        '<select id="vb-voice-sel" size="1"></select></div>' +
      '<div class="vb-row"><span class="vb-k">engine</span>' +
        '<select id="vb-voice-engine"></select>' +
        '<button class="vb-b" id="vb-voice-test">Test</button></div>' +
      '<div class="vb-hint" id="vb-voice-note">' + PRERENDER_NOTE + '</div>';

    els.filter = host.querySelector('#vb-voice-filter');
    els.sel    = host.querySelector('#vb-voice-sel');
    els.engine = host.querySelector('#vb-voice-engine');
    els.test   = host.querySelector('#vb-voice-test');

    ENGINES.forEach(function (e) {
      els.engine.appendChild(el('option', { value: e }, e));
    });

    els.filter.addEventListener('input', function () { renderVoices(); });
    els.sel.addEventListener('change', function () {
      saveVoiceCfg({ voice_id: els.sel.value });
    });
    els.engine.addEventListener('change', function () {
      saveVoiceCfg({ engine: els.engine.value });
    });
    els.test.addEventListener('click', function () { testVoice(); });
  }

  function voiceLabel(v) {
    var s = v.name || v.id;
    if (v.role) s += ' — ' + v.role;
    if (v.has_active_preset) s += ' ✦';
    return s;
  }

  function renderVoices() {
    if (!els.sel) return;
    var q = (els.filter && els.filter.value || '').trim().toLowerCase();
    var want = X.voiceCfg.voice_id;
    var rows = X.voices.filter(function (v) {
      if (!q) return true;
      if (v.id === want) return true;            /* never hide the current pick */
      return (String(v.id) + ' ' + String(v.name || '') + ' ' + String(v.role || ''))
        .toLowerCase().indexOf(q) >= 0;
    });
    els.sel.innerHTML = '';
    if (!rows.length) {
      els.sel.appendChild(el('option', { value: '' }, 'no voice matches ' + q));
      return;
    }
    rows.forEach(function (v) {
      var o = el('option', { value: v.id, 'data-voice': v.id }, voiceLabel(v));
      if (v.id === want) o.selected = true;
      els.sel.appendChild(o);
    });
    if (want && els.sel.value !== want) els.sel.value = want;
  }

  function renderVoiceCfg() {
    if (!els.engine) return;
    var eng = X.voiceCfg.engine || 'auto';
    if (ENGINES.indexOf(eng) < 0) {
      els.engine.appendChild(el('option', { value: eng }, eng));
      ENGINES.push(eng);
    }
    els.engine.value = eng;
  }

  function loadVoices() {
    return getJSON(API + 'tts/voices').then(function (j) {
      X.voices = (j && j.voices) || [];
      if (j && j.voice_id) X.voiceCfg.voice_id = j.voice_id;
      if (j && j.engine) X.voiceCfg.engine = j.engine;
      renderVoices();
      renderVoiceCfg();
    })['catch'](function (e) { note('voice list failed: ' + e.message, true); });
  }

  function loadVoiceCfg() {
    return getJSON(API + 'tts/config').then(function (j) {
      if (j && j.voice_id) X.voiceCfg.voice_id = j.voice_id;
      if (j && j.engine) X.voiceCfg.engine = j.engine;
      renderVoiceCfg();
      renderVoices();
    })['catch'](function (e) { note('voice config failed: ' + e.message, true); });
  }

  function saveVoiceCfg(patch) {
    return postJSON(API + 'tts/config', patch).then(function (j) {
      if (j && j.error) { note(j.error, true); return; }
      if (j && j.voice_id) X.voiceCfg.voice_id = j.voice_id;
      if (j && j.engine) X.voiceCfg.engine = j.engine;
      renderVoiceCfg();
      note('saved · ' + PRERENDER_NOTE);
    })['catch'](function (e) { note('save failed: ' + e.message, true); });
  }

  function testVoice() {
    var url = API + 'tts/say?text=' + encodeURIComponent(TEST_TEXT);
    note('speaking the test phrase');
    if (typeof VB.speak === 'function') { VB.speak(TEST_TEXT, url); return; }
    try { new Audio(url).play(); } catch (e) { note('cannot play: ' + e.message, true); }
  }

  /* ══ wiring ════════════════════════════════════════════════════════════════ */
  function reload() {
    return Promise.all([loadSpeakers(), loadSpeakerCfg(), loadVoices(), loadVoiceCfg()]);
  }
  X.reload = reload;

  /* The operator expects the truth when he opens the panel. 02_mic.js's chevron
     calls its own local togglePanel(), not VB.mic.togglePanel, so a wrapper would
     never fire: watch the one thing the open actually does — #vb-panel.on. */
  function hookPanelOpen() {
    var p = document.getElementById('vb-panel');
    if (!p || typeof window.MutationObserver !== 'function' || p.__vbExtrasWatched) return;
    p.__vbExtrasWatched = true;
    var was = p.classList.contains('on');
    new window.MutationObserver(function () {
      var on = p.classList.contains('on');
      if (on && !was) reload();
      was = on;
    }).observe(p, { attributes: true, attributeFilter: ['class'] });
  }

  function init() {
    if (inited) return;
    inited = true;
    return VB.waitFor(function () {
      var a = document.getElementById('vb-panel-speaker');
      var b = document.getElementById('vb-panel-voice');
      return (a && b) ? [a, b] : null;
    }, 8000).then(function (hosts) {
      if (!document.getElementById('vb-ext-css')) {
        var style = el('style', { id: 'vb-ext-css' });
        style.textContent = CSS;
        document.head.appendChild(style);
      }
      buildSpeaker(hosts[0]);
      buildVoice(hosts[1]);
      renderSpeakers();
      renderSpeakerCfg();
      hookPanelOpen();
      return reload();
    })['catch'](function (e) {
      inited = false;
      if (VB.emit) VB.emit('error', { where: 'panel-extras', message: (e && e.message) || String(e) });
    });
  }
  X.init = init;

  /* Registration only at top level; the core drains VB.ready on DOMContentLoaded. */
  VB.ready.push(init);
})();
