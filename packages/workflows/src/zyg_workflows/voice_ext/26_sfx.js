// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/26_sfx.js — Voice Bridge actions for the Sfx Studio (view 'sfx').
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script (inspection.html
 * 6916..34826), so this file may only REGISTER at top level. Every reference to
 * a studio global (goToView, mgTogglePlay, SXT_DOCK, sxtAddFx, …) is made from
 * inside run()/el(), never here.
 *
 * Sources in inspection.html — the three option bars of the tab:
 *   library bar + rail  HTML #sx-bar / #sx-rail      JS 17330..17548
 *   merger header bar   HTML 6088..6105 (#mg-opts)   JS 17641..17786, 18036..18069
 *   bottom dock         HTML 6126 (#sxt-dock)        JS 19269..19431 (SXT_DOCK)
 *   effect rail         HTML 6139 (#sxt-tools)       JS 19221..19266
 *
 * Deliberately NOT registered: mgRec* (the mic recorder), t_import (file
 * picker), t_clearall / t_dellayer / t_chainclear (destructive), t_applyall
 * (confirm()), mgSave / sxtSaveLayer / sxtExport / sxtPresetSave / sxtPresetLoad
 * (prompt()), sxtLicence / sxtHelp (blocking alert()).
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB = W.VB || {};
  VB.actions = VB.actions || {};

  var VIEW = 'sfx';

  /* ------------------------------------------------------------- helpers */

  function byId(id) {
    return (W.document && W.document.getElementById) ? W.document.getElementById(id) : null;
  }
  function pick(sel) {
    return (W.document && W.document.querySelector) ? W.document.querySelector(sel) : null;
  }
  function tool(id) {                       /* a tool icon in either bar (19243) */
    return pick('[data-sxt="' + id + '"]');
  }
  function shown() {
    var v = byId('view-sfx');
    return (v && v.style && v.style.display === 'flex') ? v : null;
  }
  /** Open the tab (sxEnter runs off goToView) and wait for `what` to be there. */
  function enter(what) {
    var want = what || shown;
    var have = null;
    try { have = want(); } catch (e) { have = null; }
    if (shown() && have) return Promise.resolve(have);
    if (typeof W.goToView === 'function') W.goToView(VIEW);
    return VB.waitFor(function () { return shown() ? want() : null; }, 6000);
  }
  /** Call a studio function by name, exactly as its control's onclick does. */
  function call(fn) {
    var args = Array.prototype.slice.call(arguments, 1);
    if (typeof W[fn] !== 'function') throw new Error('Sfx Studio has no ' + fn + '()');
    return W[fn].apply(W, args);
  }
  /** The dock's own table entry (19269..19391); its fn IS the click handler. */
  function dockItem(id) {
    var found = null;
    if (typeof W.SXT_DOCK !== 'function') return null;
    W.SXT_DOCK().forEach(function (sec) {
      (sec.items || []).forEach(function (t) { if (t.id === id) found = t; });
    });
    return found;
  }
  /** What the delegated dock listener does on a click (19422..19431). */
  function runDock(id) {
    return enter(function () { return tool(id); }).then(function () {
      var t = dockItem(id);
      if (!t || typeof t.fn !== 'function') throw new Error('no dock tool "' + id + '" in this build');
      if (typeof W.sxtFlash === 'function') W.sxtFlash(id);
      t.fn();
      if (typeof W.sxtRender === 'function') W.sxtRender();
    });
  }
  /** Fills in the one field every action of this file shares. */
  function spec(s) { s.view = VIEW; s.args = s.args || null; return s; }
  /** One dock tool -> one action; `run` is the dock table's own fn. */
  function dockSpec(id, label, aliases, say) {
    return spec({
      label: label,
      aliases: aliases,
      el: function () { return tool(id); },
      run: function () { return runDock(id); },
      say: say
    });
  }
  function searchBox() { return pick('#sx-bar input[type="search"]'); }

  /* ═════════════════════════ library bar — #sx-bar, JS 17330..17346 ═════ */

  VB.actions['sfx.search'] = spec({
    label: 'Search the sfx library',
    aliases: ['search sfx', 'search the library', 'find a sound', 'search sounds'],
    args: { value: 'text typed into the library search box' },
    el: function () { return searchBox(); },
    run: function (args) {
      var q = String((args && args.value != null) ? args.value : '');
      return enter(searchBox).then(function (box) {
        if (box) box.value = q;
        call('sxSetQuery', q);
      });
    },
    say: 'Searching the sfx library.'
  });

  VB.actions['sfx.search.clear'] = spec({
    label: 'Clear the sfx search',
    aliases: ['clear the search', 'clear search', 'show every sound'],
    el: function () { return searchBox(); },
    run: function () {
      return enter(searchBox).then(function (box) {
        if (box) box.value = '';
        call('sxSetQuery', '');
      });
    },
    say: 'Search cleared.'
  });

  VB.actions['sfx.filter.modelclean'] = spec({
    label: 'Model-clean only (toggle)',
    aliases: ['model clean only', 'toggle model clean', 'clean files only'],
    el: function () { return pick('#sx-bar .tg input[type="checkbox"]'); },
    run: function () {
      return enter(function () { return pick('#sx-bar .tg input[type="checkbox"]'); })
        .then(function () { call('sxToggle', 'clean'); });
    },
    say: 'Model-clean filter toggled.'
  });

  VB.actions['sfx.filter.verbal'] = spec({
    label: 'Hide verbal files (toggle)',
    aliases: ['hide verbal', 'toggle hide verbal', 'hide spoken files'],
    el: function () {
      var all = (W.document && W.document.querySelectorAll)
        ? W.document.querySelectorAll('#sx-bar .tg input[type="checkbox"]') : [];
      return all[1] || null;
    },
    run: function () {
      return enter(function () { return pick('#sx-bar .tg'); })
        .then(function () { call('sxToggle', 'noverbal'); });
    },
    say: 'Verbal filter toggled.'
  });

  VB.actions['sfx.library.all'] = spec({
    label: 'Show every sfx library',
    aliases: ['all libraries', 'show all libraries', 'clear the library filter'],
    el: function () { return pick('#sx-bar .vchip.on'); },
    run: function () {
      return enter(function () { return byId('sx-bar'); }).then(function () { call('sxSetCat', ''); });
    },
    say: 'Showing every sfx library.'
  });

  VB.actions['sfx.library.select'] = spec({
    label: 'Open one sfx library',
    aliases: ['open the library', 'select a library', 'filter by library'],
    args: { value: 'library key, e.g. sfx, foley, vocal_fx, merged, recorded' },
    el: function () { return byId('sx-bar'); },
    run: function (args) {
      var key = String((args && args.value != null) ? args.value : '').trim();
      if (!key) throw new Error('which library? say the library name');
      return enter(function () { return byId('sx-bar'); }).then(function () { call('sxSetCat', key); });
    },
    say: 'Opening that sfx library.'
  });

  /* ═════════════════════════ library rail playback — JS 17513..17548 ════ */

  VB.actions['sfx.sample.next'] = spec({
    label: 'Play the next sample',
    aliases: ['next sample', 'next sound', 'play the next one'],
    el: function () { return pick('#sx-rail .sx-file.on'); },
    run: function () {
      return enter(function () { return byId('sx-rail'); }).then(function () { call('sxStep', 1); });
    },
    say: 'Playing the next sample.'
  });

  VB.actions['sfx.sample.previous'] = spec({
    label: 'Play the previous sample',
    aliases: ['previous sample', 'previous sound', 'go back one sample'],
    el: function () { return pick('#sx-rail .sx-file.on'); },
    run: function () {
      return enter(function () { return byId('sx-rail'); }).then(function () { call('sxStep', -1); });
    },
    say: 'Playing the previous sample.'
  });

  VB.actions['sfx.sample.stop'] = spec({
    label: 'Stop the library player',
    aliases: ['stop the sample', 'stop playing', 'stop the sound'],
    el: function () { return pick('#sx-rail .sx-file.on'); },
    run: function () {
      return enter(function () { return byId('sx-rail'); }).then(function () { call('sxStop'); });
    },
    say: 'Sample stopped.'
  });

  /* ══════════ merger header bar — HTML 6088..6105, JS 17641..17786 ══════ */

  VB.actions['sfx.merger.show'] = spec({
    label: 'Show the merger',
    aliases: ['show the merger', 'open the merger', 'open the merge board'],
    el: function () { return byId('sx-mgbtn'); },
    run: function () {
      return enter(function () { return byId('mg-panel'); }).then(function () { call('mgShow'); });
    },
    say: 'Merger open.'
  });

  VB.actions['sfx.merger.hide'] = spec({
    label: 'Hide the merger',
    aliases: ['hide the merger', 'close the merger', 'put the merger away'],
    el: function () { return pick('#mg-opts .mg-btn:last-child'); },
    run: function () {
      return enter(function () { return byId('mg-panel'); }).then(function () { call('mgHide'); });
    },
    say: 'Merger hidden. The merge list is kept.'
  });

  VB.actions['sfx.merge.play'] = spec({
    label: 'Play or pause the merge',
    aliases: ['play the merge', 'pause the merge', 'play', 'pause'],
    el: function () { return byId('mg-play') || tool('t_play'); },
    run: function () {
      return enter(function () { return byId('mg-play') || tool('t_play'); })
        .then(function () { call('mgTogglePlay'); });
    },
    say: 'Merge playing or paused.'
  });

  VB.actions['sfx.merge.replay'] = spec({
    label: 'Replay the merge from the start',
    aliases: ['replay the merge', 'play from the start', 'start again'],
    el: function () { return byId('mg-replay') || tool('t_replay'); },
    run: function () {
      return enter(function () { return byId('mg-replay') || tool('t_replay'); })
        .then(function () { call('mgReplay'); });
    },
    say: 'Replaying the merge from the start.'
  });

  VB.actions['sfx.merge.stop'] = spec({
    label: 'Stop the merge',
    aliases: ['stop the merge', 'stop the board', 'stop and rewind'],
    el: function () { return tool('t_stop'); },
    run: function () {
      return enter(function () { return tool('t_stop') || byId('mg-play'); })
        .then(function () { call('mgStop'); });
    },
    say: 'Merge stopped and rewound.'
  });

  VB.actions['sfx.merge.loop'] = spec({
    label: 'Loop the merge (toggle)',
    aliases: ['loop the merge', 'toggle loop', 'turn looping on'],
    el: function () { return byId('mg-loop') || tool('t_loop'); },
    run: function () {
      return enter(function () { return byId('mg-loop') || tool('t_loop'); })
        .then(function () { call('mgToggleLoop'); });
    },
    say: 'Loop toggled.'
  });

  /* ── the ruler: mg-opts 6099..6101, dock Timeline 19282..19294 ── */

  VB.actions['sfx.zoom.in'] = spec({
    label: 'Zoom the ruler in',
    aliases: ['zoom in', 'closer on the ruler', 'zoom the timeline in'],
    el: function () { return tool('t_zoomin'); },
    run: function () {
      return enter(function () { return tool('t_zoomin'); }).then(function () { call('mgZoom', 1); });
    },
    say: 'Zoomed in.'
  });

  VB.actions['sfx.zoom.out'] = spec({
    label: 'Zoom the ruler out',
    aliases: ['zoom out', 'wider on the ruler', 'zoom the timeline out'],
    el: function () { return tool('t_zoomout'); },
    run: function () {
      return enter(function () { return tool('t_zoomout'); }).then(function () { call('mgZoom', -1); });
    },
    say: 'Zoomed out.'
  });

  VB.actions['sfx.zoom.fit'] = spec({
    label: 'Fit the whole merge',
    aliases: ['fit the merge', 'zoom to fit', 'fit on screen'],
    el: function () { return tool('t_zoomfit'); },
    run: function () {
      return enter(function () { return tool('t_zoomfit'); }).then(function () { call('mgZoomFit'); });
    },
    say: 'The whole merge is on screen.'
  });

  VB.actions['sfx.lanes.taller'] = spec({
    label: 'Taller lanes',
    aliases: ['taller lanes', 'make the lanes taller', 'bigger lanes'],
    el: function () { return tool('t_taller'); },
    run: function () {
      return enter(function () { return tool('t_taller'); }).then(function () { call('mgLaneZoom', 8); });
    },
    say: 'Lanes are taller.'
  });

  VB.actions['sfx.lanes.shorter'] = spec({
    label: 'Shorter lanes',
    aliases: ['shorter lanes', 'make the lanes shorter', 'smaller lanes'],
    el: function () { return tool('t_shorter'); },
    run: function () {
      return enter(function () { return tool('t_shorter'); }).then(function () { call('mgLaneZoom', -8); });
    },
    say: 'Lanes are shorter.'
  });

  /* ═════════ bottom dock — SXT_DOCK() 19269..19391, click 19422..19431 ══ */

  /* Transport (19270..19281) — play/stop/replay/loop are above, on the bar. */
  VB.actions['sfx.solo'] = dockSpec('t_solo', 'Solo the selected layer',
    ['solo the layer', 'solo this layer', 'play this layer alone'],
    'Playing the selected layer alone.');

  /* Timeline (19282..19294) */
  VB.actions['sfx.nudge.earlier'] = dockSpec('t_nudgel', 'Nudge the layer earlier',
    ['nudge earlier', 'move it earlier', 'nudge left'],
    'Nudged 10 milliseconds earlier.');
  VB.actions['sfx.nudge.later'] = dockSpec('t_nudger', 'Nudge the layer later',
    ['nudge later', 'move it later', 'nudge right'],
    'Nudged 10 milliseconds later.');

  /* Layer (19295..19312) — Remove layer and Clear board are left out. */
  VB.actions['sfx.layer.add'] = dockSpec('t_addlayer', 'Add the playing sound as a layer',
    ['add this sound', 'add a layer', 'add the sound to the board'],
    'Added that sound as a new layer.');
  VB.actions['sfx.layer.duplicate'] = dockSpec('t_dup', 'Duplicate the selected layer',
    ['duplicate the layer', 'copy this layer', 'duplicate it'],
    'Layer duplicated, chain and all.');
  VB.actions['sfx.layer.mute'] = dockSpec('t_mute', 'Mute or unmute the selected layer',
    ['mute the layer', 'unmute the layer', 'toggle mute'],
    'Layer muted or unmuted.');
  VB.actions['sfx.layer.up'] = dockSpec('t_up', 'Move the layer one lane up',
    ['move the layer up', 'move it up', 'one lane up'],
    'Layer moved up one lane.');
  VB.actions['sfx.layer.down'] = dockSpec('t_down', 'Move the layer one lane down',
    ['move the layer down', 'move it down', 'one lane down'],
    'Layer moved down one lane.');

  /* Chain (19313..19348) — Clear chain and Apply to every layer are left out. */
  VB.actions['sfx.mixer'] = dockSpec('t_mixer', 'Open the mixer for the layer',
    ['open the mixer', 'show the chain', 'show the slot list'],
    'Mixer open for the selected layer.');
  VB.actions['sfx.bypass'] = dockSpec('t_bypass', 'Bypass the chain (A/B)',
    ['bypass the chain', 'a b the chain', 'toggle the bypass'],
    'Chain bypassed, or put back.');
  VB.actions['sfx.chain.copy'] = dockSpec('t_copy', 'Copy the effect chain',
    ['copy the chain', 'copy the effects', 'copy this chain'],
    'Effect chain copied.');
  VB.actions['sfx.chain.paste'] = dockSpec('t_paste', 'Paste the effect chain',
    ['paste the chain', 'paste the effects', 'paste that chain'],
    'Effect chain pasted onto the selected layer.');
  VB.actions['sfx.undo'] = dockSpec('t_undo', 'Undo the last edit',
    ['undo', 'undo that', 'take that back'],
    'Undone.');
  VB.actions['sfx.redo'] = dockSpec('t_redo', 'Redo the last undone edit',
    ['redo', 'redo that', 'put it back'],
    'Redone.');

  /* Measure (19355..19366) */
  VB.actions['sfx.analyse'] = dockSpec('t_stats', 'Analyse the sound',
    ['analyse the sound', 'analyze this', 'measure the sound', 'show the numbers'],
    'Measuring the layer after its chain.');
  VB.actions['sfx.spectrogram'] = dockSpec('t_spectro', 'Draw the spectrogram',
    ['show the spectrogram', 'draw the spectrogram', 'spectrogram'],
    'Drawing the spectrogram.');
  VB.actions['sfx.waveform'] = dockSpec('t_wave', 'Draw the waveform',
    ['show the waveform', 'draw the waveform', 'waveform'],
    'Drawing the waveform.');
  VB.actions['sfx.loudness'] = dockSpec('t_lufs', 'Measure the loudness',
    ['measure the loudness', 'show the loudness', 'how loud is it'],
    'Measuring integrated loudness and range.');
  VB.actions['sfx.clipcheck'] = dockSpec('t_clipcheck', 'Check for clipping',
    ['check for clipping', 'clip check', 'is it clipping'],
    'Checking true peak against 0 decibels.');

  /* ═══════ effect rail — #sxt-tools, sxtRailRender 19247, sxtAddFx 19221 ═ */

  VB.actions['sfx.effect.add'] = spec({
    label: 'Add an effect to the selected sound',
    aliases: ['add an effect', 'put an effect on it', 'add the effect'],
    args: { value: 'effect id from the rail, e.g. fx_reverb, fx_denoise, lsp_compressor' },
    el: function (args) {
      var id = String((args && args.value != null) ? args.value : '').trim();
      return id ? tool(id) : byId('sxt-tools');
    },
    run: function (args) {
      var id = String((args && args.value != null) ? args.value : '').trim();
      if (!id) throw new Error('which effect? say its name, e.g. reverb');
      return enter(function () { return byId('sxt-tools'); }).then(function () {
        if (!tool(id)) throw new Error('no effect "' + id + '" in the rail');
        if (typeof W.sxtFlash === 'function') W.sxtFlash(id);
        call('sxtAddFx', id);
      });
    },
    say: 'Effect added to the selected sound.'
  });

  /* ═══════════════ view bars — sxtBarsToggle 19660, sxtDockToggle 19665 ═ */

  VB.actions['sfx.bars.toggle'] = spec({
    label: 'Hide or show the bars',
    aliases: ['hide the bars', 'show the bars', 'toggle the effect rail'],
    el: function () { return byId('sxt-arrow'); },
    run: function () {
      return enter(function () { return byId('sxt-arrow'); }).then(function () { call('sxtBarsToggle'); });
    },
    say: 'Effect rail and dock toggled.'
  });

  VB.actions['sfx.dock.toggle'] = spec({
    label: 'Hide or show the dock',
    aliases: ['hide the dock', 'show the dock', 'toggle the dock'],
    el: function () { return byId('sxt-grip'); },
    run: function () {
      return enter(function () { return byId('sxt-grip'); }).then(function () { call('sxtDockToggle'); });
    },
    say: 'Bottom dock toggled.'
  });

  VB.views[VIEW] = VB.views[VIEW] || {};
  VB.views[VIEW].label = 'Sfx Studio';
  VB.views[VIEW].note = 'Library bar, merger board and the effect dock. '
    + 'Tools act on the selected card, else the sound last played.';
})();
