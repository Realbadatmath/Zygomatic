// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/29_melody.js — Melody Studio (view 'music') for the Voice Bridge.
 *
 * Loaded by /voice_ext/bundle.js BEFORE the studio script, so nothing here may
 * touch the DOM or a km* global at top level: every reference to goToView, KM,
 * kmPlay, kmBarsToggle … lives inside run()/el(), which only fire on a spoken
 * command.
 *
 * Every run() calls the SAME handler the human click calls. For a tool in the
 * rail or the dock that means clicking the tool itself — one delegated listener
 * (inspection.html 26195-26206) owns both bars, checks `live`, `needs:'song'`
 * and the disabled state, flashes the icon and then dispatches KM_ACT[id]. Going
 * through the element rather than round it is why a voice press of "piano roll"
 * on an empty player behaves exactly like a mouse press of it.
 *
 * Sources (inspection.html): markup 6459-6514 and 5971-5986; KM state 25480-25493;
 * KM_TOOLS 25517-25839; renderers/toggles 25844-25963; KM_ACT 25985-26142;
 * tab lifecycle 26228-26256; inject picker 26289-26353; composer 26369-26572;
 * player 26657-26663 and 27053-27104.
 */
(function () {
  'use strict';

  var VB = window.VB = window.VB || { actions: {}, aliases: {}, ready: [], views: {} };
  var VIEW = 'music';

  VB.views[VIEW] = {
    title: 'Melody Studio',
    note: 'One melody at a time. Inject one before any tool marked "needs a song".'
  };

  /* ── helpers ─────────────────────────────────────────────────────────────
     enter(): the tab's own entry path — goToView (inspection.html 9165) puts
     view-music on screen, kmEnter() (26228) renders the bars, and we wait for
     the control rather than assume it is already painted. */
  function enter(get, ms) {
    if (VB.currentView() !== VIEW) {
      if (typeof window.goToView !== 'function') {
        return Promise.reject(new Error('This page has no goToView — the studio script has not loaded.'));
      }
      window.goToView(VIEW);
    }
    return VB.waitFor(get, ms || 5000);
  }

  function byId(id) { return function () { return document.getElementById(id); }; }
  function toolEl(id) { return function () { return document.querySelector('[data-kmtool="' + id + '"]'); }; }

  /* Press a tool the way a mouse does: the delegated click handler at 26195
     decides whether it is live, whether it needs a song, and which KM_ACT runs. */
  function tool(id, label) {
    return function () {
      return enter(toolEl(id)).then(function (el) {
        var cls = el.classList;
        if (cls && cls.contains('dis')) {
          throw new Error('"' + label + '" needs a melody — inject one first.');
        }
        if (cls && cls.contains('stub')) {
          throw new Error('"' + label + '" is drawn but not wired yet.');
        }
        el.click();
        return true;
      });
    };
  }

  /* The composer is a floating panel opened by the New song tool (KM_ACT.new,
     25987). Its fields do not exist until it is open, so a field action opens it
     first — by clicking the same tool — and then waits for the field. */
  function composer(fieldId) {
    return enter(byId('km-panel')).then(function () {
      var f = document.getElementById(fieldId);
      if (f) return f;
      var t = document.querySelector('[data-kmtool="new"]');
      if (!t) throw new Error('Melody Studio is not showing its tool rail.');
      t.click();
      return VB.waitFor(function () { return document.getElementById(fieldId); }, 8000);
    });
  }

  /* A spoken value is matched against the option values first, then their
     labels, so "cinematic" and "Cinematic Score" both land. */
  function setSelect(sel, value) {
    var want = String(value === undefined || value === null ? '' : value).trim();
    var opts = sel.options ? Array.prototype.slice.call(sel.options) : [];
    var low = want.toLowerCase();
    var hit = opts.filter(function (o) { return String(o.value) === want; })[0]
      || opts.filter(function (o) { return String(o.value).toLowerCase() === low; })[0]
      || opts.filter(function (o) { return String(o.textContent || '').trim().toLowerCase() === low; })[0]
      || (low ? opts.filter(function (o) { return String(o.textContent || '').toLowerCase().indexOf(low) >= 0; })[0] : null);
    if (!hit) {
      throw new Error('"' + want + '" is not on that list: '
        + opts.map(function (o) { return String(o.value); }).filter(Boolean).join(', '));
    }
    sel.value = hit.value;
    return hit.value;
  }

  function num(args, lo, hi, what) {
    var v = Number(args && args.value);
    if (!isFinite(v)) throw new Error('Say a number for the ' + what + '.');
    if (v < lo || v > hi) throw new Error('The ' + what + ' must be between ' + lo + ' and ' + hi + '.');
    return v;
  }

  var YES = ['on', '1', 'yes', 'true', 'tick', 'ticked', 'enable', 'enabled', 'want'];
  var NO = ['off', '0', 'no', 'false', 'untick', 'unticked', 'disable', 'disabled', 'none'];
  function bool(args) {
    var v = args && args.value;
    if (typeof v === 'boolean') return v;
    var s = String(v === undefined || v === null ? 'on' : v).trim().toLowerCase();
    if (YES.indexOf(s) >= 0) return true;
    if (NO.indexOf(s) >= 0) return false;
    throw new Error('Say on or off.');
  }

  /* ══ the tab's own chrome ═════════════════════════════════════════════════
     markup 6459-6514 · kmBarsToggle 25900 · kmDockToggle 25914 · kmPanelClose 25925 */

  VB.actions['music.bars'] = {
    view: VIEW,
    label: 'Hide or show both tool bars',
    aliases: ['hide the tool bars', 'show the tool bars', 'toggle the melody bars', 'tool bars'],
    args: null,
    el: byId('km-arrow'),
    run: function () {
      return enter(byId('km-arrow')).then(function (el) { el.click(); return true; });
    },
    say: 'Tool bars switched.'
  };

  VB.actions['music.dock'] = {
    view: VIEW,
    label: 'Hide or show the bottom bar',
    aliases: ['hide the bottom bar', 'show the bottom bar', 'toggle the dock', 'the song parts bar'],
    args: null,
    el: byId('km-grip'),
    run: function () {
      return enter(byId('km-grip')).then(function (el) { el.click(); return true; });
    },
    say: 'Bottom bar switched.'
  };

  VB.actions['music.close_panel'] = {
    view: VIEW,
    label: 'Close the open panel',
    aliases: ['close the panel', 'shut the panel', 'close that', 'dismiss the panel'],
    args: null,
    el: function () { return document.querySelector('#km-panel .hd button'); },
    run: function () {
      return enter(byId('km-panel')).then(function () {
        if (typeof window.kmPanelClose !== 'function') throw new Error('Melody Studio has no panel to close.');
        window.kmPanelClose();
        return true;
      });
    },
    say: 'Panel closed.'
  };

  /* ══ rail · File ══════════════════════════════════════════════════════════
     KM_TOOLS 25744-25772 · KM_ACT open/new/export 25986, 25987, 26000 */

  VB.actions['music.inject'] = {
    view: VIEW,
    label: 'Inject a melody into the player',
    aliases: ['inject a melody', 'load a melody', 'open the melody picker', 'pick a song'],
    args: null,
    el: toolEl('open'),
    run: tool('open', 'Inject melody'),
    say: 'Melody picker open. Choose one and say inject.'
  };

  VB.actions['music.new_song'] = {
    view: VIEW,
    label: 'Open the composer for a new song',
    aliases: ['new song', 'open the composer', 'write a new song', 'start a new melody'],
    args: null,
    el: toolEl('new'),
    run: tool('new', 'New song'),
    say: 'Composer open. Tell me what the song is about.'
  };

  VB.actions['music.download'] = {
    view: VIEW,
    label: 'Download the delivered audio',
    aliases: ['download the song', 'download the melody', 'save the audio', 'get the file'],
    args: null,
    el: toolEl('export'),
    run: tool('export', 'Download'),
    say: 'Downloading the delivered take.'
  };

  /* ══ rail · Run ═══════════════════════════════════════════════════════════
     KM_TOOLS 25774-25793 · KM_ACT compose 25988, log 26119 */

  VB.actions['music.compose'] = {
    view: VIEW,
    label: 'Compose the song in the composer',
    aliases: ['compose the song', 'compose it', 'start the composer run', 'make the song'],
    args: null,
    el: toolEl('compose'),
    run: tool('compose', 'Compose'),
    say: 'Composing. The run log will show each step.'
  };

  VB.actions['music.run_log'] = {
    view: VIEW,
    label: 'Show the run log',
    aliases: ['run log', 'show the log', 'what is the pipeline doing', 'open the run log'],
    args: null,
    el: toolEl('log'),
    run: tool('log', 'Run log'),
    say: 'Run log open.'
  };

  /* ══ rail · View ══════════════════════════════════════════════════════════
     KM_TOOLS 25816-25838 · KM_ACT v_board 26014 */

  VB.actions['music.storyboard_strip'] = {
    view: VIEW,
    label: 'Jump to the storyboard strip',
    aliases: ['jump to the storyboard', 'scroll to the pictures', 'show the picture strip'],
    args: null,
    el: toolEl('v_board'),
    run: tool('v_board', 'Storyboard'),
    say: 'Storyboard strip in view.'
  };

  /* ══ dock · Tune ══════════════════════════════════════════════════════════
     KM_TOOLS 25520-25545 · kmRollPanel 26144 */

  VB.actions['music.piano_roll'] = {
    view: VIEW,
    label: 'Show the piano roll',
    aliases: ['piano roll', 'show the roll', 'show the notes', 'open the piano roll'],
    args: null,
    el: toolEl('roll'),
    run: tool('roll', 'Piano roll'),
    say: 'Piano roll open.'
  };

  /* ══ dock · Arrangement ═══════════════════════════════════════════════════
     KM_TOOLS 25576-25601 · KM_ACT reroll 26129 — opens the composer prefilled,
     it starts nothing on its own */

  VB.actions['music.reroll'] = {
    view: VIEW,
    label: 'Re-roll the tune from this brief',
    aliases: ['re roll the tune', 'reroll the melody', 'compose it again', 'another tune'],
    args: null,
    el: toolEl('reroll'),
    run: tool('reroll', 'Re-roll the tune'),
    say: 'Composer prefilled from this song. Press compose when ready.'
  };

  /* ══ dock · Voice ═════════════════════════════════════════════════════════
     KM_TOOLS 25604-25629 · KM_ACT lyrics 26006 */

  VB.actions['music.lyrics'] = {
    view: VIEW,
    label: 'Show the lyrics',
    aliases: ['show the lyrics', 'lyrics', 'what are the words', 'open the lyric'],
    args: null,
    el: toolEl('lyrics'),
    run: tool('lyrics', 'Lyrics'),
    say: 'Lyrics open.'
  };

  /* ══ dock · Pictures ══════════════════════════════════════════════════════
     KM_TOOLS 25660-25685 · kmBoardPanel 26154 */

  VB.actions['music.storyboard'] = {
    view: VIEW,
    label: 'Show the storyboard',
    aliases: ['show the storyboard', 'storyboard', 'show the picture list', 'open the board'],
    args: null,
    el: toolEl('board'),
    run: tool('board', 'Storyboard'),
    say: 'Storyboard open.'
  };

  /* ══ dock · Measure ═══════════════════════════════════════════════════════
     KM_TOOLS 25716-25741 · KM_ACT score 26020, follow 26032, pacing 26048,
     beat 26065, licence 26077, gates 26092, files 26106, remeasure 26001 */

  VB.actions['music.score'] = {
    view: VIEW,
    label: 'Show the composer score',
    aliases: ['show the score', 'score', 'how did it score', 'open the score'],
    args: null,
    el: toolEl('score'),
    run: tool('score', 'Score'),
    say: 'Score open, with every subscore.'
  };

  VB.actions['music.follow'] = {
    view: VIEW,
    label: 'Show the melody follow measurement',
    aliases: ['melody follow', 'does it follow the tune', 'show the follow score'],
    args: null,
    el: toolEl('follow'),
    run: tool('follow', 'Melody follow'),
    say: 'Melody follow open. Above z 2 is a match.'
  };

  VB.actions['music.pacing'] = {
    view: VIEW,
    label: 'Show the picture pacing',
    aliases: ['picture pacing', 'show the pacing', 'how fast are the pictures'],
    args: null,
    el: toolEl('pacing'),
    run: tool('pacing', 'Picture pacing'),
    say: 'Pacing open, taken from the worst 5 second window.'
  };

  VB.actions['music.beat'] = {
    view: VIEW,
    label: 'Show the beat accuracy',
    aliases: ['beat accuracy', 'show the beats', 'how close are the cuts'],
    args: null,
    el: toolEl('beat'),
    run: tool('beat', 'Beat accuracy'),
    say: 'Beat accuracy open, in milliseconds.'
  };

  VB.actions['music.licence'] = {
    view: VIEW,
    label: 'Show the licence',
    aliases: ['show the licence', 'licence', 'can i sell this', 'licence check'],
    args: null,
    el: toolEl('licence'),
    run: tool('licence', 'Licence'),
    say: 'Licence open, read from the manifest.'
  };

  VB.actions['music.gates'] = {
    view: VIEW,
    label: 'Show the gates this run passed',
    aliases: ['show the gates', 'gates', 'which gates passed', 'open the gates'],
    args: null,
    el: toolEl('gates'),
    run: tool('gates', 'Gates'),
    say: 'Gates open, with what each one returned.'
  };

  VB.actions['music.files'] = {
    view: VIEW,
    label: 'Show the files this song wrote',
    aliases: ['show the files', 'files', 'what did it write', 'list the files'],
    args: null,
    el: toolEl('files'),
    run: tool('files', 'Files'),
    say: 'Files open, with sizes.'
  };

  VB.actions['music.remeasure'] = {
    view: VIEW,
    label: 'Read every manifest again',
    aliases: ['re measure', 'refresh the numbers', 'read the manifests again', 'reload the songs'],
    args: null,
    el: toolEl('remeasure'),
    run: tool('remeasure', 'Re-measure'),
    say: 'Manifests read again. The numbers are current.'
  };

  /* ══ the player ═══════════════════════════════════════════════════════════
     kmLegHtml 26657 builds the leg buttons, each calling kmPlay(id, file, label)
     — 27053. kmPlay toggles, so play() only calls it when the delivered leg is
     not already running and pause() calls it on whatever is. */

  function deliveredLeg() {
    var KM = window.KM;
    var id = KM && KM.pick;
    if (!id) throw new Error('No melody is injected — inject one first.');
    var s = (typeof window.kmSong === 'function') ? window.kmSong(id) : null;
    var f = (typeof window.kmBestFile === 'function') ? window.kmBestFile(s || {}) : '';
    if (!f) throw new Error('This melody delivered no audio file.');
    return { id: id, f: f };
  }

  VB.actions['music.play'] = {
    view: VIEW,
    label: 'Play the delivered take',
    aliases: ['play the melody', 'play the song', 'start playback', 'play it'],
    args: null,
    el: function () { return document.querySelector('#km-list .km-leg:not(.dl)'); },
    run: function () {
      return enter(byId('km-audio')).then(function (a) {
        var leg = deliveredLeg(), cur = window.KM.cur;
        if (cur && cur.id === leg.id && cur.f === leg.f && !a.paused) return true;
        window.kmPlay(leg.id, leg.f, 'Delivered take');
        return true;
      });
    },
    say: 'Playing the delivered take.'
  };

  VB.actions['music.pause'] = {
    view: VIEW,
    label: 'Pause the player',
    aliases: ['pause the melody', 'pause the song', 'stop playing', 'pause it'],
    args: null,
    el: function () { return document.querySelector('#km-list .km-leg.on') || document.getElementById('km-audio'); },
    run: function () {
      return enter(byId('km-audio')).then(function (a) {
        if (a.paused) return true;
        var cur = window.KM && window.KM.cur;
        if (cur) window.kmPlay(cur.id, cur.f, 'Delivered take');
        else { a.pause(); if (typeof window.kmMark === 'function') window.kmMark(); }
        return true;
      });
    },
    say: 'Paused.'
  };

  /* ══ the composer form ════════════════════════════════════════════════════
     kmComposerHtml 26369-26433 draws the fields; kmFamilyApply 26503,
     kmStyleApply 26521 and kmAgeHint 26434 are the onchange handlers. Setting
     .value fires no event, so each action calls the field's OWN handler after
     it, exactly as the select does. */

  VB.actions['music.family'] = {
    view: VIEW,
    label: 'Set the composer family',
    aliases: ['set the family', 'children family', 'cinematic family', 'switch family'],
    args: { value: "'children' or 'cinematic'" },
    el: byId('km-family'),
    run: function (args) {
      return composer('km-family').then(function (sel) {
        var got = setSelect(sel, (args || {}).value);
        if (typeof window.kmFamilyApply === 'function') window.kmFamilyApply();
        return got;
      });
    },
    say: 'Family set. The style list follows it.'
  };

  VB.actions['music.style'] = {
    view: VIEW,
    label: 'Set the composer style',
    aliases: ['set the style', 'use the style', 'style', 'change the style'],
    args: { value: "style key, e.g. 'lullaby', 'counting', 'chase'" },
    el: byId('km-style'),
    run: function (args) {
      return composer('km-style').then(function (sel) {
        var got = setSelect(sel, (args || {}).value);
        if (typeof window.kmStyleApply === 'function') window.kmStyleApply();
        return got;
      });
    },
    say: 'Style set. It filled the rest of the form.'
  };

  VB.actions['music.age_band'] = {
    view: VIEW,
    label: 'Set the age band',
    aliases: ['set the age band', 'age band', 'who is it for', 'set the band'],
    args: { value: "band key, e.g. 'toddler', 'preschool', 'early_years'" },
    el: byId('km-age'),
    run: function (args) {
      return composer('km-age').then(function (sel) {
        var got = setSelect(sel, (args || {}).value);
        if (typeof window.kmAgeHint === 'function') window.kmAgeHint();
        return got;
      });
    },
    say: 'Age band set.'
  };

  VB.actions['music.singer'] = {
    view: VIEW,
    label: 'Set the singer',
    aliases: ['set the singer', 'who sings it', 'singer', 'change the voice'],
    args: { value: "singer key, e.g. 'adult_male', 'adult_female'" },
    el: byId('km-singer'),
    run: function (args) {
      return composer('km-singer').then(function (sel) {
        var got = setSelect(sel, (args || {}).value);
        if (typeof window.kmAgeHint === 'function') window.kmAgeHint();
        return got;
      });
    },
    say: 'Singer set. Every singer is an adult.'
  };

  VB.actions['music.mood'] = {
    view: VIEW,
    label: 'Set the mood',
    aliases: ['set the mood', 'mood', 'make it happy', 'make it calm'],
    args: { value: "mood key, e.g. 'happy', 'calm', 'marching'" },
    el: byId('km-mood'),
    run: function (args) {
      return composer('km-mood').then(function (sel) { return setSelect(sel, (args || {}).value); });
    },
    say: 'Mood set.'
  };

  VB.actions['music.form'] = {
    view: VIEW,
    label: 'Set the song form',
    aliases: ['set the form', 'form', 'use a a b a', 'song shape'],
    args: { value: "form key, e.g. 'AABA', 'ABAB'" },
    el: byId('km-form'),
    run: function (args) {
      return composer('km-form').then(function (sel) { return setSelect(sel, (args || {}).value); });
    },
    say: 'Form set.'
  };

  VB.actions['music.metre'] = {
    view: VIEW,
    label: 'Set the metre',
    aliases: ['set the metre', 'set the meter', 'metre', 'time signature'],
    args: { value: "metre key, e.g. '4/4', '3/4', '6/8'" },
    el: byId('km-meter'),
    run: function (args) {
      return composer('km-meter').then(function (sel) { return setSelect(sel, (args || {}).value); });
    },
    say: 'Metre set.'
  };

  VB.actions['music.key'] = {
    view: VIEW,
    label: 'Set the key',
    aliases: ['set the key', 'key of', 'tonic', 'change the key'],
    args: { value: "tonic letter, e.g. 'C', 'Eb', 'G'" },
    el: byId('km-tonic'),
    run: function (args) {
      return composer('km-tonic').then(function (sel) { return setSelect(sel, (args || {}).value); });
    },
    say: 'Key set.'
  };

  VB.actions['music.tempo'] = {
    view: VIEW,
    label: 'Set the tempo in bpm',
    aliases: ['set the tempo', 'tempo', 'set the bpm', 'beats per minute'],
    args: { value: 'number 40..200, bpm' },
    el: byId('km-bpm'),
    run: function (args) {
      var v = num(args, 40, 200, 'tempo');
      return composer('km-bpm').then(function (f) { f.value = String(Math.round(v)); return v; });
    },
    say: 'Tempo set.'
  };

  VB.actions['music.length'] = {
    view: VIEW,
    label: 'Set the song length in seconds',
    aliases: ['set the length', 'how long', 'set the seconds', 'song length'],
    args: { value: 'number 20..180, seconds' },
    el: byId('km-sec'),
    run: function (args) {
      var v = num(args, 20, 180, 'length');
      return composer('km-sec').then(function (f) { f.value = String(Math.round(v)); return v; });
    },
    say: 'Length set.'
  };

  VB.actions['music.candidates'] = {
    view: VIEW,
    label: 'Set how many tunes are composed',
    aliases: ['set the candidates', 'candidates', 'how many tunes', 'melody candidates'],
    args: { value: 'number 1..200, tunes composed before the best is kept' },
    el: byId('km-cand'),
    run: function (args) {
      var v = num(args, 1, 200, 'candidate count');
      return composer('km-cand').then(function (f) { f.value = String(Math.round(v)); return v; });
    },
    say: 'Candidate count set.'
  };

  VB.actions['music.sung'] = {
    view: VIEW,
    label: 'Sung, with written lyrics, on or off',
    aliases: ['make it sung', 'make it instrumental', 'sung on', 'sung off'],
    args: { value: "'on' or 'off'" },
    el: byId('km-sung'),
    run: function (args) {
      var want = bool(args);
      return composer('km-sung').then(function (f) {
        f.checked = want;
        if (typeof window.kmAgeHint === 'function') window.kmAgeHint();
        return want;
      });
    },
    say: 'Sung setting changed.'
  };

  VB.actions['music.produced_take'] = {
    view: VIEW,
    label: 'Produced take on the GPU, on or off',
    aliases: ['produced take on', 'produced take off', 'use ace step', 'skip the produced take'],
    args: { value: "'on' or 'off'" },
    el: byId('km-ace'),
    run: function (args) {
      var want = bool(args);
      return composer('km-ace').then(function (f) { f.checked = want; return want; });
    },
    say: 'Produced take setting changed.'
  };

  VB.actions['music.illustrated_video'] = {
    view: VIEW,
    label: 'Illustrated video, on or off',
    aliases: ['video on', 'video off', 'draw the pictures', 'skip the video'],
    args: { value: "'on' or 'off'" },
    el: byId('km-video'),
    run: function (args) {
      var want = bool(args);
      return composer('km-video').then(function (f) { f.checked = want; return want; });
    },
    say: 'Illustrated video setting changed.'
  };

  if (typeof VB.reindex === 'function') VB.reindex();
})();
