// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/27_musicstudio.js — Music Studio (view 'musicstudio') voice actions.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script (inspection.html
 * 6916..34826), so this file may only REGISTER at top level. Every reference to
 * a studio global (goToView, mmg*, mst*, mus*, MMG, MST, MUS) is resolved INSIDE
 * run()/el(), never here.
 *
 * Source of every handler below (inspection.html):
 *   markup   6172-6249 (mus-/mmg-/mst- ids)  ·  6252-6263 (musa- analysis sheet)
 *   library  19703-20070  (MUS / mus*)
 *   mixer    20076-21400  (MMG / mmg*)
 *   toolbox  21507-22214  (MST / mst*, MST_DOCK, the delegated click handler)
 *
 * The three bars are rendered from MST_DOCK() + the server's 299-option roster;
 * a human click goes through the delegated handler at 22203-22214, which does
 * mstFlash(id) -> mstFns()[id].fn() -> mstRender(). dockRun() below is that exact
 * path, so a spoken tool press and a mouse press run the same code.
 *
 * Deliberately NOT registered (contract): mstImport / t_import (file picker),
 * mmgClear / t_clearall + t_dellayer + t_chainclear (destructive), mmgSave,
 * mstSaveLayer, mstExport, mstPresetSave (prompt()), t_applyall (confirm()),
 * mstHelp + mstLicence (alert()), and tab navigation (10_nav.js owns it).
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB = W.VB || { actions: {}, aliases: {}, ready: [], views: {} };
  VB.actions = VB.actions || {};
  VB.views = VB.views || {};

  var VIEW = 'musicstudio';

  VB.views[VIEW] = {
    title: 'Music Studio',
    note: 'The Sfx Studio on the 66,028 sampled instrument one-shots: library rail, '
        + 'mixer board, three tool bars (left "the sound", right "this sound", foot dock).'
  };

  /* ------------------------------------------------------------ plumbing */

  function doc() { return W.document || null; }

  function byId(id) {
    var d = doc();
    return (d && d.getElementById) ? d.getElementById(id) : null;
  }

  function sel(q) {
    var d = doc();
    try { return (d && d.querySelector) ? d.querySelector(q) : null; } catch (e) { return null; }
  }

  /** A studio global, or a readable error naming what is missing. */
  function fn(name) {
    var f = W[name];
    if (typeof f !== 'function') throw new Error('Music Studio: ' + name + '() is not loaded yet');
    return f;
  }

  /** The button the ghost cursor points at for a dock/rail/left-bar tool id. */
  function tool(id) {
    return sel('#mst-dock [data-mst="' + id + '"]')
        || sel('#mst-tools [data-mst="' + id + '"]')
        || sel('#mst-left [data-mst="' + id + '"]');
  }

  function viewOpen() {
    var v = byId('view-' + VIEW);
    return (v && v.style && v.style.display === 'flex') ? v : null;
  }

  /** Open the tab if it is not the visible one, then wait for it (musEnter runs on the hash change). */
  function enter() {
    var open = viewOpen();
    if (open) return Promise.resolve(open);
    fn('goToView')(VIEW);
    return VB.waitFor(viewOpen, 8000);
  }

  /** Every run() is "make sure the studio is up, then call the studio's own handler". */
  function act(body) {
    return function (args) {
      return enter().then(function () { return body(args || {}); });
    };
  }

  /** Stamp the view and the default arg shape onto a spec; the caller names it. */
  function reg(spec) {
    spec.view = VIEW;
    if (!('args' in spec)) spec.args = null;
    return spec;
  }

  /** Spoken "on"/"off"/"yes"/"no"/true/false -> boolean, anything else -> null (= plain toggle). */
  function wantBool(args) {
    var v = (args && ('value' in args)) ? args.value : undefined;
    if (v === undefined || v === null || v === '') return null;
    if (typeof v === 'boolean') return v;
    var s = String(v).trim().toLowerCase();
    if (s === 'on' || s === 'yes' || s === 'true' || s === '1' || s === 'show') return true;
    if (s === 'off' || s === 'no' || s === 'false' || s === '0' || s === 'hide') return false;
    return null;
  }

  /** args.value as a whole number of repeats, clamped; 1 when nothing was said. */
  function steps(args, max) {
    var n = parseInt((args && args.value), 10);
    if (!isFinite(n) || n < 1) n = 1;
    return Math.min(n, max || 8);
  }

  /** Press a tool of the three bars exactly the way the delegated click handler does (22203-22214). */
  function dockRun(id) {
    var t = fn('mstFns')()[id];
    if (!t || typeof t.fn !== 'function') throw new Error('Music Studio: no tool "' + id + '" in the dock');
    if (t.off) throw new Error('Music Studio: "' + (t.lb || id) + '" is not available right now');
    try { fn('mstFlash')(id); } catch (e) { /* cosmetic only */ }
    t.fn();
    fn('mstRender')();
  }

  /* ═══════════════════════════════════════════════════════════════════════
     THE TAB AND THE THREE BARS
     markup 6172-6249 · musEnter 19715-19728 · mstBarsToggle/mstDockToggle
     22157-22166 · mmgShow/mmgHide 20124-20128 · goToView 9165-9171
     ═══════════════════════════════════════════════════════════════════════ */

  VB.actions['musicstudio.open'] = reg({
    label: 'Open the Music Studio',
    aliases: ['music studio', 'open the music studio', 'go to the music studio', 'show the instruments'],
    el: function () { return sel('.top-tab[data-view="musicstudio"]'); },
    run: act(function () { return viewOpen(); }),
    say: 'Music Studio is open.'
  });

  VB.actions['musicstudio.bars.show'] = reg({
    label: 'Show the three tool bars',
    aliases: ['show the bars', 'show the tool bars', 'bring the bars back'],
    el: function () { return byId('mst-arrow'); },
    run: act(function () {
      if (W.MST && W.MST.bars) return;
      fn('mstBarsToggle')();
    }),
    say: 'The three bars are showing.'
  });

  VB.actions['musicstudio.bars.hide'] = reg({
    label: 'Hide the three tool bars',
    aliases: ['hide the bars', 'hide the tool bars', 'fold the bars away'],
    el: function () { return byId('mst-arrow'); },
    run: act(function () {
      if (W.MST && !W.MST.bars) return;
      fn('mstBarsToggle')();
    }),
    say: 'The bars are hidden.'
  });

  VB.actions['musicstudio.dock.show'] = reg({
    label: 'Show the bottom dock',
    aliases: ['show the dock', 'open the dock', 'show the bottom bar'],
    el: function () { return byId('mst-grip'); },
    run: act(function () {
      if (W.MST && W.MST.dock) return;
      fn('mstDockToggle')();
    }),
    say: 'The dock is showing.'
  });

  VB.actions['musicstudio.dock.hide'] = reg({
    label: 'Hide the bottom dock',
    aliases: ['hide the dock', 'close the dock', 'hide the bottom bar'],
    el: function () { return byId('mst-grip'); },
    run: act(function () {
      if (W.MST && !W.MST.dock) return;
      fn('mstDockToggle')();
    }),
    say: 'The dock is hidden.'
  });

  VB.actions['musicstudio.mixer.show'] = reg({
    label: 'Show the mixer panel',
    aliases: ['show the mixer', 'open the mixer panel', 'show the board'],
    el: function () { return byId('mus-mmgbtn'); },
    run: act(function () {
      if (W.MMG && W.MMG.shown) return;
      fn('mmgShow')();
    }),
    say: 'The mixer is showing.'
  });

  VB.actions['musicstudio.mixer.hide'] = reg({
    label: 'Hide the mixer panel',
    aliases: ['hide the mixer', 'close the mixer panel', 'hide the board'],
    el: function () { return byId('mmg-panel'); },
    run: act(function () {
      if (W.MMG && !W.MMG.shown) return;
      fn('mmgHide')();
    }),
    say: 'The mixer is hidden. The tracks are kept.'
  });

  /* ═══════════════════════════════════════════════════════════════════════
     TRANSPORT — markup 6196-6201 · mmgTogglePlay/mmgStop/mmgReplay/
     mmgToggleLoop 20249-20269 · dock section 'Transport' 21624-21635
     ═══════════════════════════════════════════════════════════════════════ */

  VB.actions['musicstudio.play'] = reg({
    label: 'Play the mix',
    aliases: ['play', 'start playback', 'play the mix', 'play it'],
    el: function () { return tool('t_play') || byId('mmg-play'); },
    run: act(function () {
      if (W.MMG && W.MMG.playing) return;
      fn('mmgTogglePlay')();
    }),
    say: 'Playing the mix.'
  });

  VB.actions['musicstudio.pause'] = reg({
    label: 'Pause the mix',
    aliases: ['pause', 'pause the mix', 'hold it', 'pause playback'],
    el: function () { return tool('t_play') || byId('mmg-play'); },
    run: act(function () {
      if (W.MMG && !W.MMG.playing) return;
      fn('mmgTogglePlay')();
    }),
    say: 'Paused.'
  });

  VB.actions['musicstudio.stop'] = reg({
    label: 'Stop and rewind',
    /* no bare 'stop': that phrase belongs to core.stop (00_core.js) and VB.reindex is first-wins */
    aliases: ['stop playback', 'stop the mix', 'stop the music', 'rewind to the start'],
    el: function () { return tool('t_stop') || byId('mmg-play'); },
    run: act(function () { fn('mmgStop')(); }),
    say: 'Stopped and rewound to the start.'
  });

  VB.actions['musicstudio.replay'] = reg({
    label: 'Play again from the start',
    aliases: ['replay', 'play again', 'play from the start', 'from the top'],
    el: function () { return tool('t_replay') || byId('mmg-replay'); },
    run: act(function () { fn('mmgReplay')(); }),
    say: 'Playing again from the start.'
  });

  VB.actions['musicstudio.loop.on'] = reg({
    label: 'Loop the mix',
    aliases: ['loop', 'loop it', 'turn looping on', 'keep looping'],
    el: function () { return tool('t_loop') || byId('mmg-loop'); },
    run: act(function () {
      if (W.MMG && W.MMG.loop) return;
      fn('mmgToggleLoop')();
    }),
    say: 'Looping is on.'
  });

  VB.actions['musicstudio.loop.off'] = reg({
    label: 'Stop looping the mix',
    aliases: ['stop looping', 'turn looping off', 'no loop', 'loop off'],
    el: function () { return tool('t_loop') || byId('mmg-loop'); },
    run: act(function () {
      if (W.MMG && !W.MMG.loop) return;
      fn('mmgToggleLoop')();
    }),
    say: 'Looping is off.'
  });

  VB.actions['musicstudio.solo'] = reg({
    label: 'Solo the selected layer',
    aliases: ['solo', 'solo this layer', 'play this layer alone', 'solo the layer'],
    el: function () { return tool('t_solo'); },
    run: act(function () { dockRun('t_solo'); }),
    say: 'Playing the selected layer alone.'
  });

  /* ═══════════════════════════════════════════════════════════════════════
     TIMELINE — markup 6205-6213 · mmgZoom 20521-20532 · mmgLaneZoom
     20534-20540 · mmgZoomFit 20541-20554 · mstNudge 21758-21765 ·
     dock section 'Timeline' 21636-21648
     ═══════════════════════════════════════════════════════════════════════ */

  VB.actions['musicstudio.zoom.in'] = reg({
    label: 'Zoom the ruler in',
    aliases: ['zoom in', 'closer', 'zoom the ruler in'],
    args: { value: 'number of zoom steps, 1 to 8, default 1' },
    el: function () { return tool('t_zoomin'); },
    run: act(function (a) {
      var z = fn('mmgZoom'), n = steps(a, 8);
      for (var i = 0; i < n; i++) z(1);
    }),
    say: 'Zoomed in.'
  });

  VB.actions['musicstudio.zoom.out'] = reg({
    label: 'Zoom the ruler out',
    aliases: ['zoom out', 'wider', 'zoom the ruler out'],
    args: { value: 'number of zoom steps, 1 to 8, default 1' },
    el: function () { return tool('t_zoomout'); },
    run: act(function (a) {
      var z = fn('mmgZoom'), n = steps(a, 8);
      for (var i = 0; i < n; i++) z(-1);
    }),
    say: 'Zoomed out.'
  });

  VB.actions['musicstudio.zoom.fit'] = reg({
    label: 'Fit the whole mix on screen',
    aliases: ['fit', 'zoom to fit', 'fit the whole mix', 'show everything'],
    el: function () { return tool('t_zoomfit'); },
    run: act(function () { fn('mmgZoomFit')(); }),
    say: 'The whole mix is on screen.'
  });

  VB.actions['musicstudio.lanes.taller'] = reg({
    label: 'Make the lanes taller',
    aliases: ['taller lanes', 'make the lanes taller', 'bigger lanes'],
    args: { value: 'number of 8 pixel steps, 1 to 6, default 1' },
    el: function () { return tool('t_taller'); },
    run: act(function (a) { fn('mmgLaneZoom')(8 * steps(a, 6)); }),
    say: 'The lanes are taller.'
  });

  VB.actions['musicstudio.lanes.shorter'] = reg({
    label: 'Make the lanes shorter',
    aliases: ['shorter lanes', 'make the lanes shorter', 'smaller lanes'],
    args: { value: 'number of 8 pixel steps, 1 to 6, default 1' },
    el: function () { return tool('t_shorter'); },
    run: act(function (a) { fn('mmgLaneZoom')(-8 * steps(a, 6)); }),
    say: 'The lanes are shorter.'
  });

  VB.actions['musicstudio.nudge.earlier'] = reg({
    label: 'Nudge the selected layer earlier',
    aliases: ['nudge earlier', 'move it earlier', 'nudge left', 'a bit earlier'],
    args: { value: 'milliseconds to move, 1 to 1000, default 10' },
    el: function () { return tool('t_nudgel'); },
    run: act(function (a) {
      var ms = parseFloat(a && a.value);
      if (!isFinite(ms) || ms <= 0) ms = 10;
      fn('mstNudge')(-Math.min(1000, ms) / 1000);
    }),
    say: 'Nudged the layer earlier.'
  });

  VB.actions['musicstudio.nudge.later'] = reg({
    label: 'Nudge the selected layer later',
    aliases: ['nudge later', 'move it later', 'nudge right', 'a bit later'],
    args: { value: 'milliseconds to move, 1 to 1000, default 10' },
    el: function () { return tool('t_nudger'); },
    run: act(function (a) {
      var ms = parseFloat(a && a.value);
      if (!isFinite(ms) || ms <= 0) ms = 10;
      fn('mstNudge')(Math.min(1000, ms) / 1000);
    }),
    say: 'Nudged the layer later.'
  });

  VB.actions['musicstudio.timestamp'] = reg({
    label: 'Set an exact start time for the layer',
    aliases: ['set the timestamp', 'set the start time', 'type a start time'],
    el: function () { return tool('t_stamp'); },
    run: act(function () { dockRun('t_stamp'); }),
    say: 'The timestamp box is open.'
  });

  /* ═══════════════════════════════════════════════════════════════════════
     LAYER — dock section 'Layer' 21649-21666 · mmgAdd 20132 ·
     mmgTrackClone 20904 · mmgTrackMute 20900 · mmgTrackMove 20912
     ═══════════════════════════════════════════════════════════════════════ */

  VB.actions['musicstudio.layer.add'] = reg({
    label: 'Add the playing sound as a layer',
    aliases: ['add this sound', 'add a layer', 'put it on the board', 'add sound'],
    el: function () { return tool('t_addlayer'); },
    run: act(function () { dockRun('t_addlayer'); }),
    say: 'Added the sound as a new layer.'
  });

  VB.actions['musicstudio.layer.duplicate'] = reg({
    label: 'Duplicate the selected layer',
    aliases: ['duplicate the layer', 'copy this layer', 'duplicate it'],
    el: function () { return tool('t_dup'); },
    run: act(function () { dockRun('t_dup'); }),
    say: 'Duplicated the layer, chain and all.'
  });

  VB.actions['musicstudio.layer.mute'] = reg({
    label: 'Mute or unmute the selected layer',
    aliases: ['mute this layer', 'unmute this layer', 'mute the layer', 'toggle mute'],
    el: function () { return tool('t_mute'); },
    run: act(function () { dockRun('t_mute'); }),
    say: 'Switched the mute on the selected layer.'
  });

  VB.actions['musicstudio.layer.up'] = reg({
    label: 'Move the selected layer one lane up',
    aliases: ['move the layer up', 'move it up', 'one lane up'],
    el: function () { return tool('t_up'); },
    run: act(function () { dockRun('t_up'); }),
    say: 'Moved the layer one lane up.'
  });

  VB.actions['musicstudio.layer.down'] = reg({
    label: 'Move the selected layer one lane down',
    aliases: ['move the layer down', 'move it down', 'one lane down'],
    el: function () { return tool('t_down'); },
    run: act(function () { dockRun('t_down'); }),
    say: 'Moved the layer one lane down.'
  });

  /* ═══════════════════════════════════════════════════════════════════════
     CHAIN — dock section 'Chain' 21667-21702 · mstBypass 21769-21780 ·
     mstUndo/mstRedo 21589-21598 · mmgMixerOpen 20944
     ═══════════════════════════════════════════════════════════════════════ */

  VB.actions['musicstudio.mixer.open'] = reg({
    label: 'Open the slot list for the selected layer',
    aliases: ['open the slot list', 'show the effect chain', 'open the layer mixer'],
    el: function () { return tool('t_mixer'); },
    run: act(function () { dockRun('t_mixer'); }),
    say: 'The slot list for this layer is open.'
  });

  VB.actions['musicstudio.chain.bypass'] = reg({
    label: 'Bypass the chain on the selected layer',
    aliases: ['bypass the chain', 'a b the chain', 'bypass', 'chain off and on'],
    el: function () { return tool('t_bypass'); },
    run: act(function () { fn('mstBypass')(); fn('mstRender')(); }),
    say: 'Switched the chain bypass on this layer.'
  });

  VB.actions['musicstudio.chain.copy'] = reg({
    label: 'Copy the selected layer chain',
    aliases: ['copy the chain', 'copy this chain', 'copy the effects'],
    el: function () { return tool('t_copy'); },
    run: act(function () { dockRun('t_copy'); }),
    say: 'Copied the effect chain.'
  });

  VB.actions['musicstudio.chain.paste'] = reg({
    label: 'Paste the copied chain onto the layer',
    aliases: ['paste the chain', 'paste this chain', 'paste the effects'],
    el: function () { return tool('t_paste'); },
    run: act(function () { dockRun('t_paste'); }),
    say: 'Pasted the copied chain onto this layer.'
  });

  VB.actions['musicstudio.undo'] = reg({
    label: 'Undo the last board or chain edit',
    aliases: ['undo', 'undo that', 'take that back', 'step back'],
    el: function () { return tool('t_undo'); },
    run: act(function () { fn('mstUndo')(); fn('mstRender')(); }),
    say: 'Undone.'
  });

  VB.actions['musicstudio.redo'] = reg({
    label: 'Redo what was just undone',
    aliases: ['redo', 'redo that', 'put it back', 'step forward'],
    el: function () { return tool('t_redo'); },
    run: act(function () { fn('mstRedo')(); fn('mstRender')(); }),
    say: 'Redone.'
  });

  VB.actions['musicstudio.preset.load'] = reg({
    label: 'Load a stored chain preset',
    aliases: ['load a chain preset', 'load a preset', 'show the chain presets'],
    el: function () { return tool('t_presetload'); },
    run: act(function () { dockRun('t_presetload'); }),
    say: 'The stored chain presets are listed.'
  });

  /* ═══════════════════════════════════════════════════════════════════════
     MEASURE — dock section 'Measure' 21709-21720 · mstAnalyze 21916-21928 ·
     musaClose 21915 · markup 6252-6261
     ═══════════════════════════════════════════════════════════════════════ */

  VB.actions['musicstudio.analyse'] = reg({
    label: 'Measure the selected sound',
    aliases: ['analyse', 'analyze this sound', 'measure it', 'show the statistics'],
    el: function () { return tool('t_stats'); },
    run: act(function () { fn('mstAnalyze')('stats'); }),
    say: 'Measuring peak, RMS, LUFS and crest.'
  });

  VB.actions['musicstudio.spectrogram'] = reg({
    label: 'Draw the spectrogram',
    aliases: ['spectrogram', 'show the spectrogram', 'draw the spectrogram'],
    el: function () { return tool('t_spectro'); },
    run: act(function () { fn('mstAnalyze')('spectrogram'); }),
    say: 'Drawing the spectrogram.'
  });

  VB.actions['musicstudio.waveform'] = reg({
    label: 'Draw the full waveform',
    aliases: ['waveform', 'show the waveform', 'draw the waveform'],
    el: function () { return tool('t_wave'); },
    run: act(function () { fn('mstAnalyze')('waveform'); }),
    say: 'Drawing the waveform.'
  });

  VB.actions['musicstudio.loudness'] = reg({
    label: 'Measure the loudness',
    aliases: ['loudness', 'how loud is this', 'measure the loudness', 'check the lufs'],
    el: function () { return tool('t_lufs'); },
    run: act(function () { fn('mstAnalyze')('loudness'); }),
    say: 'Measuring EBU R128 loudness and range.'
  });

  VB.actions['musicstudio.clipcheck'] = reg({
    label: 'Check the layer for clipping',
    aliases: ['clip check', 'is this clipping', 'check for clipping'],
    el: function () { return tool('t_clipcheck'); },
    run: act(function () { fn('mstAnalyze')('clip'); }),
    say: 'Checking true peak against 0 dBFS.'
  });

  VB.actions['musicstudio.analysis.close'] = reg({
    label: 'Close the analysis sheet',
    aliases: ['close the analysis', 'close the sheet', 'close the measurement'],
    el: function () { return byId('musa-modal'); },
    run: act(function () { fn('musaClose')(); }),
    say: 'The analysis sheet is closed.'
  });

  /* ═══════════════════════════════════════════════════════════════════════
     LIBRARY RAIL — MUS 19703-19713 · musSetCat 19822-19830 ·
     musSetQuery 19831 · musToggle 19832-19834 · musSort 19835-19838 ·
     musStep 20027-20034 · musStop 20035-20040 · categories 22016
     ═══════════════════════════════════════════════════════════════════════ */

  var MUS_CATS = ['instruments', 'soundtracks', 'merged', 'recorded'];

  VB.actions['musicstudio.library.category'] = reg({
    label: 'Open one library in the rail',
    aliases: ['open the library', 'show the library', 'pick a library', 'switch library'],
    args: { value: 'one of: instruments, soundtracks, merged, recorded' },
    el: function () { return byId('mus-rail'); },
    run: act(function (a) {
      var k = String((a && a.value) || '').trim().toLowerCase();
      if (MUS_CATS.indexOf(k) < 0) {
        throw new Error('Music Studio: no library "' + k + '" — try ' + MUS_CATS.join(', '));
      }
      if (W.MUS && W.MUS.cat === k) return;
      fn('musSetCat')(k);
    }),
    say: 'That library is open in the rail.'
  });

  VB.actions['musicstudio.library.all'] = reg({
    label: 'Show every library again',
    aliases: ['all libraries', 'show all libraries', 'clear the library filter'],
    el: function () { return byId('mus-rail'); },
    run: act(function () {
      var cur = W.MUS && W.MUS.cat;
      if (!cur) return;
      fn('musSetCat')(cur);
    }),
    say: 'Showing every library again.'
  });

  VB.actions['musicstudio.library.search'] = reg({
    label: 'Search the instrument library',
    aliases: ['search for', 'search the library', 'find a sample', 'look for'],
    args: { value: 'the words to search for; empty clears the search' },
    el: function () { return sel('#mus-bar input[type="search"]') || byId('mus-rail'); },
    run: act(function (a) {
      var q = (a && a.value !== undefined && a.value !== null) ? String(a.value) : '';
      fn('musSetQuery')(q);
    }),
    say: 'Searching the library now.'
  });

  VB.actions['musicstudio.library.clean'] = reg({
    label: 'Show model-clean files only',
    aliases: ['model clean only', 'only clean files', 'hide the vendor packs'],
    args: { value: 'on or off; leave it out to toggle' },
    el: function () { return sel('#mus-bar input[type="checkbox"]') || byId('mus-rail'); },
    run: act(function (a) {
      var want = wantBool(a);
      if (want !== null && W.MUS && !!W.MUS.clean === want) return;
      fn('musToggle')('clean');
    }),
    say: 'Switched the model-clean filter.'
  });

  VB.actions['musicstudio.library.noverbal'] = reg({
    label: 'Hide files with spoken words in them',
    aliases: ['hide verbal', 'hide the spoken files', 'no talking'],
    args: { value: 'on or off; leave it out to toggle' },
    el: function () { return byId('mus-rail'); },
    run: act(function (a) {
      var want = wantBool(a);
      if (want !== null && W.MUS && !!W.MUS.noverbal === want) return;
      fn('musToggle')('noverbal');
    }),
    say: 'Switched the hide-verbal filter.'
  });

  VB.actions['musicstudio.library.sort'] = reg({
    label: 'Sort the library list',
    aliases: ['sort the library', 'sort by', 'order the list'],
    args: { value: 'one of: pack, name, group, dur, new, fmt' },
    el: function () { return byId('mus-rail'); },
    run: act(function (a) {
      var keys = ['pack', 'name', 'group', 'dur', 'new', 'fmt'];
      var k = String((a && a.value) || '').trim().toLowerCase();
      if (k === 'duration' || k === 'length') k = 'dur';
      if (k === 'newest' || k === 'date') k = 'new';
      if (k === 'format') k = 'fmt';
      if (keys.indexOf(k) < 0) {
        throw new Error('Music Studio: cannot sort by "' + k + '" — try ' + keys.join(', '));
      }
      fn('musSort')(k);
    }),
    say: 'The library list is sorted.'
  });

  VB.actions['musicstudio.sample.next'] = reg({
    label: 'Play the next sample in the rail',
    aliases: ['next sample', 'next one', 'play the next sample', 'next instrument'],
    el: function () { return sel('#mus-rail .mus-file.on') || byId('mus-rail'); },
    run: act(function () { fn('musStep')(1); }),
    say: 'Playing the next sample.'
  });

  VB.actions['musicstudio.sample.previous'] = reg({
    label: 'Play the previous sample in the rail',
    aliases: ['previous sample', 'the one before', 'play the previous sample', 'go back one sample'],
    el: function () { return sel('#mus-rail .mus-file.on') || byId('mus-rail'); },
    run: act(function () { fn('musStep')(-1); }),
    say: 'Playing the previous sample.'
  });

  VB.actions['musicstudio.sample.stop'] = reg({
    label: 'Stop the library preview',
    aliases: ['stop the sample', 'stop the preview', 'silence the library'],
    el: function () { return sel('#mus-rail .mus-file.on') || byId('mus-rail'); },
    run: act(function () { fn('musStop')(); }),
    say: 'The library preview is stopped.'
  });
})();
