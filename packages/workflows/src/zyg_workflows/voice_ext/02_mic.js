// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/02_mic.js — the microphone leg of the Voice Bridge.
 *
 * Loaded from /voice_ext/bundle.js, which is injected BEFORE the studio script,
 * so nothing here may touch the DOM or a studio global at parse time. Everything
 * that does runs inside init(), which the core drains off VB.ready.
 *
 * What this file owns:
 *   - the 🎙 button in #topbar (inserted next to the settings gear; inspection.html
 *     is never edited for it) and the #vb-panel control panel,
 *   - the microphone stream, device pick, push-to-talk and open-mic client VAD,
 *   - one MediaRecorder per utterance -> base64 -> POST /inspect/api/voice/utterance,
 *   - VB.speak(text, wavUrl): the reply voice, with the VAD muted while it plays.
 *
 * What it deliberately does NOT own: the SSE connection, the ghost cursor and the
 * action registry (core), the speaker panel and the voice picker (two placeholder
 * divs are left for them).
 */
(function () {
  'use strict';

  var VB = window.VB = window.VB || { actions: {}, aliases: {}, ready: [], views: {} };

  /* ── tuning constants (VAD is specified in milliseconds, not in frames) ───── */
  var FRAME_MS      = 20;     /* RMS is measured on 20 ms frames                */
  var START_MS      = 100;    /* above threshold this long => speech started    */
  var END_MS        = 700;    /* below threshold this long => speech ended      */
  var MIN_UTTER_MS  = 400;    /* shorter than this is a cough, not a command    */
  var MAX_UTTER_MS  = 12000;  /* hard stop, the recorder is closed regardless   */
  var RMS_THRESHOLD = 0.02;   /* ~ -34 dBFS; VB.mic.threshold retunes it live   */
  var SAY_TIMEOUT_MS = 6000;  /* wav neither plays nor errors => treat as dead  */
  var LOG_KEEP      = 8;      /* last N utterances shown in the panel           */

  var MIME = 'audio/webm;codecs=opus';
  var BITRATE = 32000;

  /* ── state ────────────────────────────────────────────────────────────────── */
  var V = VB.mic = VB.mic || {};
  V.state      = 'idle';      /* idle | listening | thinking | acting | speaking */
  V.mode       = 'ptt';       /* ptt | open                                      */
  V.armed      = false;       /* open-mic VAD running                            */
  V.speaking   = false;       /* a reply is playing -> VAD is muted              */
  V.rms        = 0;
  V.vadTrips   = 0;           /* speech-start count; the smoke test reads this   */
  V.threshold  = RMS_THRESHOLD;
  V.log        = [];          /* last LOG_KEEP utterance records                 */
  V.acks       = {};          /* action id -> {ok, error} (core calls noteAck)   */
  V.deviceId   = null;
  V.stream     = null;
  V.error      = '';

  var els = {};               /* the DOM handles, filled by init()               */
  var audioCtx = null, srcNode = null, procNode = null;
  var rec = null, chunks = [], utterStart = 0, maxTimer = 0;
  var sayAudio = null, sayTimer = 0;
  var inited = false;

  /* ── small helpers ────────────────────────────────────────────────────────── */
  function ls(k, d) { try { var v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  function lsDel(k) { try { localStorage.removeItem(k); } catch (e) { /* private mode */ } }

  function driverToken() { return (VB.driver || ls('vb.driver', '') || ''); }

  function randomToken() {
    var out = '', i;
    if (window.crypto && window.crypto.getRandomValues) {
      var a = new Uint8Array(6);
      window.crypto.getRandomValues(a);
      for (i = 0; i < a.length; i++) out += ('0' + a[i].toString(16)).slice(-2);
    } else {
      for (i = 0; i < 12; i++) out += '0123456789abcdef'[Math.floor(Math.random() * 16)];
    }
    return out;
  }

  function currentView() {
    if (typeof VB.currentView === 'function') { try { return VB.currentView(); } catch (e) { /* fall through */ } }
    var t = document.querySelector('#topbar .top-tab.active');
    if (t && t.getAttribute('data-view')) return t.getAttribute('data-view');
    var h = (location.hash || '').replace('#', '');
    return h || 'home';
  }

  function registryCount(view) {
    var n = 0, k;
    for (k in VB.actions) { if (VB.actions[k] && VB.actions[k].view === view) n++; }
    return n;
  }

  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.text().then(function (txt) {
        var j = {};
        try { j = txt ? JSON.parse(txt) : {}; } catch (e) { j = { error: txt.slice(0, 200) }; }
        if (!r.ok) throw new Error(j.error || ('http ' + r.status));
        return j;
      });
    });
  }

  function blobToB64(blob) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onerror = function () { reject(new Error('could not read the recording')); };
      fr.onload = function () {
        var s = String(fr.result || '');
        var c = s.indexOf(',');
        resolve(c >= 0 ? s.slice(c + 1) : s);
      };
      fr.readAsDataURL(blob);
    });
  }

  /* Core owns the shared state machine when it is loaded; this keeps the two in
     step and still works when 02_mic.js is the only file on the page. */
  function setState(s) {
    V.state = s;
    if (typeof VB.setState === 'function' && VB.state !== s) { try { VB.setState(s); } catch (e) { /* no core */ } }
    if (els.state) els.state.textContent = s;
    if (els.btn) {
      els.btn.setAttribute('data-vb-state', s);
      els.btn.title = 'Voice — ' + s + (V.mode === 'ptt' ? ' (hold F8 to talk)' : ' (open mic)');
    }
  }

  function setError(msg) {
    V.error = msg || '';
    if (els.notice) {
      els.notice.textContent = V.error;
      els.notice.style.display = V.error ? 'block' : 'none';
    }
    if (V.error) try { console.warn('[vb.mic] ' + V.error); } catch (e) { /* no console */ }
  }

  /* ══ VAD ═══════════════════════════════════════════════════════════════════
     feedSamples() is the only way audio enters the detector, so the same code
     path serves the live ScriptProcessor and the smoke test's synthetic buffer. */
  var acc = null, accN = 0, accI = 0;
  var aboveMs = 0, belowMs = 0, speechMs = 0, inSpeech = false;

  function resetVad() { aboveMs = 0; belowMs = 0; speechMs = 0; inSpeech = false; accI = 0; }

  function onFrame(rms) {
    V.rms = rms;
    if (els.level) els.level.style.width = Math.min(100, Math.round(rms * 600)) + '%';
    if (V.speaking) return;                       /* muted while a reply plays  */
    if (V.mode !== 'open' || !V.armed) return;    /* push-to-talk gates itself  */

    if (rms > V.threshold) {
      aboveMs += FRAME_MS; belowMs = 0;
      if (!inSpeech && aboveMs >= START_MS) {
        inSpeech = true; speechMs = aboveMs;
        V.vadTrips++;
        startUtterance('vad');
      } else if (inSpeech) {
        speechMs += FRAME_MS;
      }
    } else {
      aboveMs = 0;
      if (inSpeech) {
        speechMs += FRAME_MS; belowMs += FRAME_MS;
        if (belowMs >= END_MS) {
          var ok = speechMs - belowMs >= MIN_UTTER_MS;
          inSpeech = false; speechMs = 0; belowMs = 0;
          stopUtterance(ok ? 'vad' : 'too-short');
        }
      }
    }
    if (inSpeech && speechMs >= MAX_UTTER_MS) {
      inSpeech = false; speechMs = 0; belowMs = 0; aboveMs = 0;
      stopUtterance('max');
    }
  }

  function feedSamples(data, sampleRate) {
    var sr = sampleRate || (audioCtx && audioCtx.sampleRate) || 48000;
    var n = Math.max(1, Math.round(sr * FRAME_MS / 1000));
    if (!acc || accN !== n) { acc = new Float32Array(n); accN = n; accI = 0; }
    for (var i = 0; i < data.length; i++) {
      acc[accI++] = data[i];
      if (accI >= n) {
        var s = 0;
        for (var j = 0; j < n; j++) s += acc[j] * acc[j];
        accI = 0;
        onFrame(Math.sqrt(s / n));
      }
    }
  }
  V.feedSamples = feedSamples;

  /* ══ microphone ════════════════════════════════════════════════════════════ */
  function secure() { return window.isSecureContext !== false; }
  /* the host serving this page, so the hint never names a hardcoded domain */
  function insecureHint() { return 'microphone needs https (https://' + location.host + ')'; }

  function openStream() {
    if (V.stream) return Promise.resolve(V.stream);
    if (!secure()) return Promise.reject(new Error(insecureHint()));
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
      return Promise.reject(new Error('this browser exposes no microphone API'));
    var audio = { echoCancellation: true, noiseSuppression: true, channelCount: 1 };
    if (V.deviceId) audio.deviceId = { exact: V.deviceId };
    return navigator.mediaDevices.getUserMedia({ audio: audio }).then(function (stream) {
      V.stream = stream;
      attachAnalyser(stream);
      return stream;
    });
  }

  function closeStream() {
    detachAnalyser();
    if (V.stream) {
      try { V.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { /* already gone */ }
      V.stream = null;
    }
  }

  /* A ScriptProcessor rather than an AudioWorklet: the worklet needs a separate
     module URL, and this node does nothing but hand 20 ms of mono samples to
     feedSamples() — the deprecation costs nothing at this duty cycle. */
  function attachAnalyser(stream) {
    detachAnalyser();
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    audioCtx = new AC();
    if (audioCtx.state === 'suspended' && audioCtx.resume) { try { audioCtx.resume(); } catch (e) { /* user gesture */ } }
    srcNode = audioCtx.createMediaStreamSource(stream);
    procNode = audioCtx.createScriptProcessor(1024, 1, 1);
    procNode.onaudioprocess = function (ev) { feedSamples(ev.inputBuffer.getChannelData(0), audioCtx.sampleRate); };
    srcNode.connect(procNode);
    /* a zero-gain sink keeps the processor pulling without any monitoring path */
    var sink = audioCtx.createGain();
    sink.gain.value = 0;
    procNode.connect(sink);
    sink.connect(audioCtx.destination);
  }

  function detachAnalyser() {
    if (procNode) { try { procNode.disconnect(); procNode.onaudioprocess = null; } catch (e) { /* gone */ } procNode = null; }
    if (srcNode) { try { srcNode.disconnect(); } catch (e) { /* gone */ } srcNode = null; }
    if (audioCtx) { try { audioCtx.close(); } catch (e) { /* gone */ } audioCtx = null; }
    resetVad();
  }

  /* ── device list: Music Studio already solved the blank-label dance ───────── */
  function listDevices() {
    if (typeof window.mgRecDevices === 'function') return window.mgRecDevices();
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices)
      return Promise.reject(new Error('this browser exposes no microphone API'));
    return navigator.mediaDevices.enumerateDevices().then(function (l) {
      return l.filter(function (d) { return d.kind === 'audioinput'; });
    });
  }

  function fillDevices() {
    if (!els.dev) return;
    listDevices().then(function (ins) {
      els.dev.innerHTML = '';
      var o = document.createElement('option');
      o.value = ''; o.textContent = 'default input';
      els.dev.appendChild(o);
      ins.forEach(function (d, i) {
        var op = document.createElement('option');
        op.value = d.deviceId;
        op.textContent = d.label || ('input ' + (i + 1));
        els.dev.appendChild(op);
      });
      if (V.deviceId) els.dev.value = V.deviceId;
    }).catch(function (e) { setError(e.message || String(e)); });
  }

  /* ══ recording one utterance ═══════════════════════════════════════════════ */
  function startUtterance(why) {
    if (rec) return;
    setState('listening');
    if (!V.stream || typeof window.MediaRecorder !== 'function') return;  /* VAD-only (tests) */
    var opts = { audioBitsPerSecond: BITRATE };
    if (window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(MIME)) opts.mimeType = MIME;
    try { rec = new window.MediaRecorder(V.stream, opts); }
    catch (e) { setError('recorder refused: ' + (e.message || e)); rec = null; return; }
    chunks = [];
    utterStart = Date.now();
    rec.ondataavailable = function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); };
    rec.onstop = function () {
      var blob = new Blob(chunks, { type: rec.mimeType || MIME });
      var ms = Date.now() - utterStart;
      rec = null; chunks = [];
      if (maxTimer) { clearTimeout(maxTimer); maxTimer = 0; }
      if (ms < MIN_UTTER_MS || !blob.size) { setState(V.armed ? 'idle' : 'idle'); return; }
      sendUtterance(blob, utterStart);
    };
    rec.start();
    maxTimer = setTimeout(function () { stopUtterance('max'); }, MAX_UTTER_MS);
    if (why === 'ptt') resetVad();
  }

  function stopUtterance(why) {
    if (maxTimer) { clearTimeout(maxTimer); maxTimer = 0; }
    if (!rec) { if (V.state === 'listening') setState('idle'); return; }
    if (why === 'too-short') {
      var r = rec; rec = null; chunks = [];
      try { r.onstop = null; r.stop(); } catch (e) { /* already stopped */ }
      setState('idle');
      return;
    }
    try { rec.stop(); } catch (e) { rec = null; setState('idle'); }
  }

  function sendUtterance(blob, tStart) {
    setState('thinking');
    var view = currentView();
    blobToB64(blob).then(function (b64) {
      return post('/inspect/api/voice/utterance', {
        driver: driverToken(),
        audio_b64: b64,
        mime: 'audio/webm',
        view: view,
        t_start: tStart / 1000
      });
    }).then(function (res) {
      noteUtterance({
        text: res.text || '',
        speaker: res.speaker || null,
        tier: res.tier || 'none',
        actions: (res.actions || []).map(function (a) { return a && (a.name || a.id) ? (a.name || a.id) : String(a); }),
        ids: (res.actions || []).map(function (a) { return a && a.id; })
      });
      if (res.actions && res.actions.length) setState('acting');
      if (res.say && (res.say.text || res.say.wav)) VB.speak(res.say.text || '', res.say.wav || '');
      else if (!res.actions || !res.actions.length) setState('idle');
    }).catch(function (e) {
      setError(e.message || String(e));
      setState('idle');
    });
  }

  function noteUtterance(rowIn) {
    V.log.unshift(rowIn);
    if (V.log.length > LOG_KEEP) V.log.length = LOG_KEEP;
    renderLog();
  }

  /* Core POSTs the ack; it may mirror the result here so the panel can show it. */
  V.noteAck = function (id, ok, error) {
    V.acks[id] = { ok: !!ok, error: error || '' };
    renderLog();
    if (V.state === 'acting') setState(V.speaking ? 'speaking' : 'idle');
  };

  /* ══ the reply voice ═══════════════════════════════════════════════════════ */
  function clearSay() {
    if (sayTimer) { clearTimeout(sayTimer); sayTimer = 0; }
    if (sayAudio) {
      try { sayAudio.onended = sayAudio.onerror = sayAudio.onplaying = null; sayAudio.pause(); } catch (e) { /* gone */ }
      sayAudio = null;
    }
    try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (e) { /* none */ }
  }

  function saySpeechSynthesis(text) {
    if (ls('vb.ttsFallback', '0') !== '1') { doneSpeaking(); return; }
    if (!window.speechSynthesis || typeof window.SpeechSynthesisUtterance !== 'function') { doneSpeaking(); return; }
    var u = new window.SpeechSynthesisUtterance(text);
    u.onend = doneSpeaking;
    u.onerror = doneSpeaking;
    try { window.speechSynthesis.speak(u); } catch (e) { doneSpeaking(); }
  }

  function doneSpeaking() {
    V.speaking = false;
    resetVad();
    setState('idle');
  }

  /* VB.speak(text, wavUrl) — caption it, play it, and keep the VAD muted for the
     whole of it (echo cancellation is not enough at desk volume). One at a time:
     a new say interrupts the one in flight. */
  VB.speak = function (text, wavUrl) {
    clearSay();
    text = text == null ? '' : String(text);
    if (VB.cursor && typeof VB.cursor.caption === 'function') { try { VB.cursor.caption(text); } catch (e) { /* cursor absent */ } }
    if (els.say) els.say.textContent = text;
    V.speaking = true;
    setState('speaking');
    if (!wavUrl) { saySpeechSynthesis(text); return; }
    var a = sayAudio = new Audio(wavUrl);
    var fell = false;
    var fallback = function () {
      if (fell || sayAudio !== a) return;
      fell = true;
      clearSay();
      saySpeechSynthesis(text);
    };
    sayTimer = setTimeout(fallback, SAY_TIMEOUT_MS);
    a.onplaying = function () { if (sayTimer) { clearTimeout(sayTimer); sayTimer = 0; } };
    a.onended = function () { if (sayAudio === a) { sayAudio = null; doneSpeaking(); } };
    a.onerror = fallback;
    var p = a.play();
    if (p && p.catch) p.catch(fallback);
  };

  /* ══ push-to-talk ══════════════════════════════════════════════════════════ */
  var pttDown = false;

  function pttStart() {
    if (pttDown || V.mode !== 'ptt') return;
    pttDown = true;
    openStream().then(function () { startUtterance('ptt'); })
      .catch(function (e) { pttDown = false; setError(e.message || String(e)); });
  }

  function pttStop() {
    if (!pttDown) return;
    pttDown = false;
    stopUtterance('ptt');
  }

  /* ══ open mic ══════════════════════════════════════════════════════════════ */
  function armOpen() {
    if (V.armed) return Promise.resolve();
    return openStream().then(function () {
      V.armed = true;
      resetVad();
      setState('idle');
      renderPanel();
    }).catch(function (e) { setError(e.message || String(e)); throw e; });
  }

  function disarm() {
    V.armed = false;
    stopUtterance('too-short');
    closeStream();
    setState('idle');
    renderPanel();
  }

  function setMode(m) {
    V.mode = (m === 'open') ? 'open' : 'ptt';
    lsSet('vb.mode', V.mode);
    if (V.mode === 'ptt' && V.armed) disarm();
    setState(V.state);
    renderPanel();
  }

  /* ══ panel ═════════════════════════════════════════════════════════════════ */
  var CSS = [
    '#vb-mic[data-vb-state="listening"]{color:var(--good,#1db954);background:rgba(29,185,84,.16);}',
    '#vb-mic[data-vb-state="thinking"]{color:var(--warn,#ffcc00);background:rgba(255,204,0,.14);}',
    '#vb-mic[data-vb-state="acting"]{color:var(--acc,#00e5ff);background:rgba(0,229,255,.16);}',
    '#vb-mic[data-vb-state="speaking"]{color:var(--acc,#00e5ff);background:rgba(0,229,255,.24);}',
    '#vb-mic{margin-left:auto;margin-right:0;}',
    '#vb-mic-chev{padding:8px 4px;font-size:.8rem;margin:0;}',
    '#vb-panel{position:fixed;top:54px;right:10px;width:360px;max-width:360px;z-index:9600;display:none;',
    '  background:var(--panel,#1e1e22);border:1px solid var(--line,#383842);border-radius:10px;',
    '  box-shadow:0 14px 40px rgba(0,0,0,.6);color:var(--txt,#e4e4e7);font-size:12px;line-height:1.45;',
    '  font-family:"Manrope",system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;',
    '  max-height:calc(calc(100vh / var(--ui-zoom,1)) - 70px);overflow:auto;padding:10px 12px 12px;}',
    '#vb-panel.on{display:block;}',
    '#vb-panel h4{margin:0 0 8px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted,#a1a1aa);}',
    '#vb-panel .vb-row{display:flex;align-items:center;gap:8px;margin:5px 0;}',
    '#vb-panel .vb-row > span.vb-k{color:var(--muted,#a1a1aa);min-width:86px;}',
    '#vb-panel button.vb-b{background:var(--panel2,#2a2a30);border:1px solid var(--line,#383842);color:var(--txt,#e4e4e7);',
    '  border-radius:6px;padding:3px 9px;font-size:12px;cursor:pointer;font-family:inherit;}',
    '#vb-panel button.vb-b.on{border-color:var(--acc,#00e5ff);color:var(--acc,#00e5ff);background:rgba(0,229,255,.14);}',
    '#vb-panel select,#vb-panel input{background:var(--panel2,#2a2a30);border:1px solid var(--line,#383842);',
    '  color:var(--txt,#e4e4e7);border-radius:6px;padding:3px 6px;font-size:12px;max-width:230px;font-family:inherit;}',
    '#vb-panel .vb-level{height:4px;background:var(--panel2,#2a2a30);border-radius:3px;overflow:hidden;flex:1;}',
    '#vb-panel .vb-level i{display:block;height:100%;width:0;background:var(--acc,#00e5ff);}',
    '#vb-panel .vb-notice{display:none;margin:6px 0;padding:5px 7px;border-radius:6px;font-size:11.5px;',
    '  background:rgba(255,59,48,.14);border:1px solid rgba(255,59,48,.5);color:var(--bad,#ff3b30);}',
    '#vb-panel .vb-sep{border-top:1px solid var(--line,#383842);margin:9px 0 7px;}',
    '#vb-panel .vb-u{border-top:1px dashed var(--line,#383842);padding:5px 0 4px;}',
    '#vb-panel .vb-u:first-child{border-top:0;}',
    '#vb-panel .vb-u .vb-t{color:var(--txt,#e4e4e7);word-break:break-word;}',
    '#vb-panel .vb-u .vb-m{color:var(--muted,#a1a1aa);font-size:11px;}',
    '#vb-panel .vb-ok{color:var(--good,#1db954);} #vb-panel .vb-no{color:var(--bad,#ff3b30);}',
    '#vb-panel .vb-say{color:var(--muted,#a1a1aa);font-style:italic;word-break:break-word;min-height:1em;}'
  ].join('\n');

  function el(tag, attrs, text) {
    var n = document.createElement(tag), k;
    if (attrs) for (k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function buildPanel() {
    var p = el('div', { id: 'vb-panel' });
    p.innerHTML =
      '<h4>Voice bridge</h4>' +
      '<div class="vb-notice" id="vb-notice"></div>' +
      '<div class="vb-row"><span class="vb-k">this tab</span>' +
        '<button class="vb-b" id="vb-driver">executes</button>' +
        '<span class="vb-m" id="vb-driver-tok"></span></div>' +
      '<div class="vb-row"><span class="vb-k">mode</span>' +
        '<button class="vb-b" id="vb-mode-ptt">push to talk</button>' +
        '<button class="vb-b" id="vb-mode-open">open mic</button></div>' +
      '<div class="vb-row"><span class="vb-k">input</span>' +
        '<select id="vb-device"></select></div>' +
      '<div class="vb-row"><span class="vb-k">state</span>' +
        '<b id="vb-state">idle</b>' +
        '<span class="vb-level"><i id="vb-level"></i></span></div>' +
      '<div class="vb-row"><span class="vb-k">actions here</span>' +
        '<span id="vb-regcount">0</span>' +
        '<span class="vb-m" id="vb-regview"></span></div>' +
      '<div class="vb-row"><span class="vb-k">browser voice</span>' +
        '<button class="vb-b" id="vb-fallback">fallback</button></div>' +
      '<div class="vb-sep"></div>' +
      '<div class="vb-say" id="vb-say"></div>' +
      '<div class="vb-sep"></div>' +
      '<div id="vb-panel-speaker"></div>' +
      '<div id="vb-panel-voice"></div>' +
      '<div class="vb-sep"></div>' +
      '<h4>last utterances</h4>' +
      '<div id="vb-log"></div>';
    return p;
  }

  function renderLog() {
    if (!els.log) return;
    els.log.innerHTML = '';
    if (!V.log.length) { els.log.appendChild(el('div', { 'class': 'vb-m' }, 'nothing heard yet')); return; }
    V.log.forEach(function (r) {
      var d = el('div', { 'class': 'vb-u' });
      d.appendChild(el('div', { 'class': 'vb-t' }, r.text || '(no transcript)'));
      var bits = [];
      bits.push('tier ' + (r.tier || 'none'));
      if (r.speaker) {
        bits.push('speaker ' + (r.speaker.name || '?') +
          ' ' + (r.speaker.score == null ? '?' : Number(r.speaker.score).toFixed(2)) +
          (r.speaker.accepted ? '' : ' rejected'));
      }
      d.appendChild(el('div', { 'class': 'vb-m' }, bits.join(' · ')));
      if (r.actions && r.actions.length) {
        var line = el('div', { 'class': 'vb-m' });
        r.actions.forEach(function (name, i) {
          var id = r.ids && r.ids[i];
          var ack = id && V.acks[id];
          var s = el('span', { 'class': ack ? (ack.ok ? 'vb-ok' : 'vb-no') : '' },
            (i ? ' · ' : '') + name + (ack ? (ack.ok ? ' ✓' : ' ✗ ' + (ack.error || '')) : ' …'));
          line.appendChild(s);
        });
        d.appendChild(line);
      }
      els.log.appendChild(d);
    });
  }

  function renderPanel() {
    if (!els.panel) return;
    var drv = driverToken();
    if (els.driver) {
      els.driver.classList.toggle('on', !!drv);
      els.driver.textContent = drv ? 'executes' : 'watches only';
    }
    if (els.driverTok) els.driverTok.textContent = drv ? drv : '';
    if (els.modePtt) els.modePtt.classList.toggle('on', V.mode === 'ptt');
    if (els.modeOpen) els.modeOpen.classList.toggle('on', V.mode === 'open' && V.armed);
    if (els.fallback) els.fallback.classList.toggle('on', ls('vb.ttsFallback', '0') === '1');
    var view = currentView();
    if (els.regCount) els.regCount.textContent = String(registryCount(view));
    if (els.regView) els.regView.textContent = 'in ' + view;
    if (els.state) els.state.textContent = V.state;
    renderLog();
  }
  V.renderPanel = renderPanel;

  function togglePanel(force) {
    if (!els.panel) return;
    var on = (force == null) ? !els.panel.classList.contains('on') : !!force;
    els.panel.classList.toggle('on', on);
    if (on) { renderPanel(); fillDevices(); }
  }
  V.togglePanel = togglePanel;

  /* ══ init ══════════════════════════════════════════════════════════════════ */
  function init() {
    if (inited) return;
    var bar = document.getElementById('topbar');
    if (!bar) return;
    inited = true;

    var style = el('style', { id: 'vb-mic-css' });
    style.textContent = CSS;
    document.head.appendChild(style);

    var btn = el('button', { 'class': 'top-tab top-icon', id: 'vb-mic', title: 'Voice' });
    btn.innerHTML = '&#127897;';
    var chev = el('button', { 'class': 'top-tab top-icon', id: 'vb-mic-chev', title: 'Voice bridge panel' });
    chev.innerHTML = '&#9662;';
    var gear = bar.querySelector('button.top-tab.top-right[data-view="settings"]');
    if (gear) { bar.insertBefore(btn, gear); bar.insertBefore(chev, gear); }
    else { bar.appendChild(btn); bar.appendChild(chev); }

    var panel = buildPanel();
    document.body.appendChild(panel);

    els = {
      btn: btn, chev: chev, panel: panel,
      notice: panel.querySelector('#vb-notice'),
      driver: panel.querySelector('#vb-driver'),
      driverTok: panel.querySelector('#vb-driver-tok'),
      modePtt: panel.querySelector('#vb-mode-ptt'),
      modeOpen: panel.querySelector('#vb-mode-open'),
      dev: panel.querySelector('#vb-device'),
      state: panel.querySelector('#vb-state'),
      level: panel.querySelector('#vb-level'),
      regCount: panel.querySelector('#vb-regcount'),
      regView: panel.querySelector('#vb-regview'),
      fallback: panel.querySelector('#vb-fallback'),
      say: panel.querySelector('#vb-say'),
      log: panel.querySelector('#vb-log')
    };

    V.mode = (ls('vb.mode', 'ptt') === 'open') ? 'open' : 'ptt';

    /* panel wiring */
    els.driver.addEventListener('click', function () {
      var on = !driverToken();
      var tok = on ? randomToken() : '';
      if (typeof VB.setDriver === 'function') {
        try { VB.setDriver(tok); } catch (e) { setError('driver toggle failed: ' + (e.message || e)); }
      } else if (on) {
        lsSet('vb.driver', tok);
        if (typeof VB.connect === 'function') { try { VB.connect(); } catch (e) { /* no core */ } }
      } else {
        lsDel('vb.driver');
        if (typeof VB.disconnect === 'function') { try { VB.disconnect(); } catch (e) { /* no core */ } }
      }
      renderPanel();
    });
    els.modePtt.addEventListener('click', function () { setMode('ptt'); });
    els.modeOpen.addEventListener('click', function () {
      if (V.mode === 'open' && V.armed) { disarm(); return; }
      setMode('open');
      armOpen().catch(function () { /* the notice already says why */ });
    });
    els.dev.addEventListener('change', function () {
      V.deviceId = els.dev.value || null;
      if (V.stream) { closeStream(); if (V.mode === 'open') { V.armed = false; armOpen().catch(function () {}); } }
    });
    els.fallback.addEventListener('click', function () {
      lsSet('vb.ttsFallback', ls('vb.ttsFallback', '0') === '1' ? '0' : '1');
      renderPanel();
    });

    /* the mic button: modifier-click opens the panel, the chevron always does */
    chev.addEventListener('click', function (ev) { ev.preventDefault(); togglePanel(); });
    btn.addEventListener('click', function (ev) {
      if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) { ev.preventDefault(); togglePanel(); return; }
      if (V.mode === 'open') { if (V.armed) disarm(); else armOpen().catch(function () {}); }
    });
    btn.addEventListener('pointerdown', function (ev) {
      if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
      if (V.mode !== 'ptt') return;
      ev.preventDefault();
      pttStart();
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (n) {
      btn.addEventListener(n, function () { pttStop(); });
    });

    /* F8 is the hold-to-talk key; it is not bound anywhere else in the studio */
    window.addEventListener('keydown', function (ev) {
      if (ev.key !== 'F8' || ev.repeat) return;
      ev.preventDefault();
      pttStart();
    });
    window.addEventListener('keyup', function (ev) {
      if (ev.key !== 'F8') return;
      ev.preventDefault();
      pttStop();
    });

    if (!secure()) {
      setError(insecureHint());
      btn.disabled = true;
      btn.style.opacity = '.45';
      btn.style.cursor = 'not-allowed';
    }

    /* core drives its own transitions (acting, idle after the queue drains) and
       reports every action's outcome — mirror both into the panel */
    if (typeof VB.on === 'function') {
      VB.on('state', function (s) { V.state = s; if (els.state) els.state.textContent = s; if (els.btn) els.btn.setAttribute('data-vb-state', s); });
      VB.on('action', function (d) {
        if (!d || !d.id) return;
        if (d.phase === 'done') V.noteAck(d.id, true, '');
        else if (d.phase === 'error') V.noteAck(d.id, false, d.error || 'failed');
      });
      VB.on('driver', function () { renderPanel(); });
    }

    setState('idle');
    renderPanel();
    if (V.mode === 'open' && secure() && ls('vb.autoarm', '0') === '1') armOpen().catch(function () {});
    document.documentElement.setAttribute('data-vb-mic', 'ready');
  }
  V.init = init;

  /* Registration only at top level. The core drains VB.ready on DOMContentLoaded;
     the listener below is the belt-and-braces path when this file is loaded on
     its own (the smoke page). init() is idempotent, so both may fire. */
  VB.ready.push(init);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 0); });
  } else {
    setTimeout(init, 0);
  }
})();
