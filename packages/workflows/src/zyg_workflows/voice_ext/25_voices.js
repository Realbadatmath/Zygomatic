// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/25_voices.js — Voice Bridge actions for the Voice Studio (view 'voices1').
 *
 * Source of truth, all in inspection.html:
 *   markup        6274..6353   (#view-voices1, #vo-toolcol, #vo-dock, the merger)
 *   VO_TOOLS      33964..34574 (the option table both bars are rendered from)
 *   vo* functions 34577..34940 (the delegated click handler and the live tools)
 *
 * Every action below calls the SAME function the human click calls. The bars are
 * rendered by voRender() into [data-vo="<id>"] tiles (voToolHtml, 34599), so that
 * attribute — not an id — is how a tile is addressed here.
 *
 * Only st:'live' tools are registered: a st:'park' / st:'stub' tile opens an
 * explanatory sheet and does nothing, so voicing it would be a lie. Deliberately
 * left out as well (see the report): 'msave' (m1Save opens prompt()), 'mclear'
 * (m1Clear opens confirm()), 'refmic' (m1RecToggle arms the microphone the voice
 * bridge is itself listening on), and 'save', whose act is the same
 * voTune(null,null) that 'tune' already carries.
 *
 * The bundle loads this file BEFORE the studio script, so nothing here may touch
 * the DOM or a studio global at top level — only inside el() / run().
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : this;
  var VB = W.VB = W.VB || { actions: {}, aliases: {}, ready: [], views: {} };
  var VIEW = 'voices1';

  VB.views[VIEW] = {
    label: 'Voice Studio',
    note: 'A 293-voice rail, one player and the voice merger. The right rail is the '
      + 'VOICE half of the toolkit (identity, delivery, tone, dynamics, space, output, '
      + 'analysis, rights); the bottom dock is the SESSION half (transport, takes, '
      + 'presets, library, merge, browse, session).'
  };

  /* ---------------------------------------------------------------- helpers */

  /** The tile the ghost cursor should move to, by its VO_TOOLS id. */
  function tool(id) {
    return function () { return document.querySelector('[data-vo="' + id + '"]'); };
  }
  function byId(id) {
    return function () { return document.getElementById(id); };
  }
  function byQuery(sel) {
    return function () { return document.querySelector(sel); };
  }

  /** The studio's own handler, or a readable error if the script has not loaded. */
  function fn(name) {
    var f = W[name];
    if (typeof f !== 'function') throw new Error('Voice Studio: ' + name + '() is not loaded');
    return f;
  }

  /** The view counts as open once switchView has displayed it (inspection.html 8984). */
  function shown() {
    var v = document.getElementById('view-voices1');
    return (v && v.style && v.style.display !== 'none') ? v : null;
  }

  /**
   * Open the tab if it is not the one on screen, wait for it, then hand back the
   * action's own control (best effort — a control that only exists once a voice is
   * selected must not turn the whole action into a timeout).
   */
  function enter(elFn) {
    var here = (typeof VB.currentView === 'function') ? VB.currentView() : '';
    if (here !== VIEW && typeof W.goToView === 'function') W.goToView(VIEW);
    return VB.waitFor(shown, 4000).then(function () {
      if (typeof elFn !== 'function') return null;
      return VB.waitFor(elFn, 1200).catch(function () { return null; });
    });
  }

  /** Every run() goes through here: view first, then the studio's own handler. */
  function go(elFn, body) {
    return enter(elFn).then(function () { return body(); });
  }

  /** A rail knob tile: open the real Tune dialog scrolled to that knob (34647). */
  function knob(id, name) {
    return function () { return go(tool(id), function () { fn('voTune')(null, name); }); };
  }

  /* ═══ right rail · Identity — VO_TOOLS 33966..34032 ═════════════════════ */

  VB.actions['voices1.seed.k'] = {
    view: VIEW,
    label: 'Tune seed k (reference resample)',
    aliases: ['seed k', 'seed size', 'resample the reference', 'open seed k'],
    args: null,
    el: tool('seedk'),
    run: knob('seedk', 'seed_k'),
    say: 'Tune is open on seed k.'
  };

  VB.actions['voices1.seed.m'] = {
    view: VIEW,
    label: 'Tune seed m (reference pitch)',
    aliases: ['seed m', 'seed pitch', 'shift the reference pitch', 'open seed m'],
    args: null,
    el: tool('seedm'),
    run: knob('seedm', 'seed_m'),
    say: 'Tune is open on seed m.'
  };

  VB.actions['voices1.blend'] = {
    view: VIEW,
    label: 'Open the voice blend board',
    aliases: ['blend', 'voice blend', 'open the blend board', 'blend voices'],
    args: null,
    el: tool('blend'),
    run: function () { return go(tool('blend'), function () { fn('m1Show')(); }); },
    say: 'The blend board is open.'
  };

  /* ═══ right rail · Delivery — VO_TOOLS 34033..34099 ═════════════════════ */

  VB.actions['voices1.tempo'] = {
    view: VIEW,
    label: 'Tune tempo (pace only)',
    aliases: ['tempo', 'pace', 'speed knob', 'open tempo'],
    args: null,
    el: tool('tempo'),
    run: knob('tempo', 'tempo'),
    say: 'Tune is open on tempo.'
  };

  /* ═══ right rail · Tone — VO_TOOLS 34101..34177 ═════════════════════════ */

  VB.actions['voices1.tone'] = {
    view: VIEW,
    label: 'Open the whole tone rack',
    aliases: ['eq', 'tone', 'tone rack', 'equaliser'],
    args: null,
    el: tool('eq'),
    run: function () { return go(tool('eq'), function () { fn('voTune')('tone', null); }); },
    say: 'Tune is open on the tone rack.'
  };

  VB.actions['voices1.tone.rumble'] = {
    view: VIEW,
    label: 'Tune rumble (high-pass filter)',
    aliases: ['rumble', 'high pass', 'cut the rumble', 'open rumble'],
    args: null,
    el: tool('hpf'),
    run: knob('hpf', 'hpf'),
    say: 'Tune is open on rumble.'
  };

  VB.actions['voices1.tone.warmth'] = {
    view: VIEW,
    label: 'Tune warmth',
    aliases: ['warmth', 'warmer', 'open warmth'],
    args: null,
    el: tool('warmth'),
    run: knob('warmth', 'warmth'),
    say: 'Tune is open on warmth.'
  };

  VB.actions['voices1.tone.body'] = {
    view: VIEW,
    label: 'Tune body',
    aliases: ['body', 'more body', 'open body'],
    args: null,
    el: tool('body'),
    run: knob('body', 'body'),
    say: 'Tune is open on body.'
  };

  VB.actions['voices1.tone.presence'] = {
    view: VIEW,
    label: 'Tune presence',
    aliases: ['presence', 'more presence', 'open presence'],
    args: null,
    el: tool('presence'),
    run: knob('presence', 'presence'),
    say: 'Tune is open on presence.'
  };

  VB.actions['voices1.tone.air'] = {
    view: VIEW,
    label: 'Tune air',
    aliases: ['air', 'more air', 'open air'],
    args: null,
    el: tool('air'),
    run: knob('air', 'air'),
    say: 'Tune is open on air.'
  };

  /* ═══ right rail · Dynamics — VO_TOOLS 34143..34214 ═════════════════════ */

  VB.actions['voices1.dynamics.compress'] = {
    view: VIEW,
    label: 'Tune the compressor',
    aliases: ['compress', 'compressor', 'compression', 'open the compressor'],
    args: null,
    el: tool('comp'),
    run: knob('comp', 'comp'),
    say: 'Tune is open on the compressor.'
  };

  VB.actions['voices1.dynamics.deess'] = {
    view: VIEW,
    label: 'Tune the de-esser',
    aliases: ['de ess', 'de esser', 'sibilance knob', 'open the de esser'],
    args: null,
    el: tool('deess'),
    run: knob('deess', 'deess'),
    say: 'Tune is open on the de-esser.'
  };

  /* ═══ right rail · Space — VO_TOOLS 34180..34251 ════════════════════════ */

  VB.actions['voices1.space.room'] = {
    view: VIEW,
    label: 'Tune room amount',
    aliases: ['room', 'room amount', 'reverb amount', 'open room'],
    args: null,
    el: tool('room'),
    run: knob('room', 'room'),
    say: 'Tune is open on room.'
  };

  VB.actions['voices1.space.room_size'] = {
    view: VIEW,
    label: 'Tune room size',
    aliases: ['room size', 'bigger room', 'open room size'],
    args: null,
    el: tool('roomms'),
    run: knob('roomms', 'room_ms'),
    say: 'Tune is open on room size.'
  };

  /* ═══ right rail · Output — VO_TOOLS 34217..34278 ═══════════════════════ */

  VB.actions['voices1.output.loudness'] = {
    view: VIEW,
    label: 'Tune loudness target',
    aliases: ['loudness', 'lufs', 'loudness target', 'open loudness'],
    args: null,
    el: tool('lufs'),
    run: knob('lufs', 'lufs'),
    say: 'Tune is open on loudness.'
  };

  VB.actions['voices1.output.true_peak'] = {
    view: VIEW,
    label: 'Tune true peak ceiling',
    aliases: ['true peak', 'peak ceiling', 'open true peak'],
    args: null,
    el: tool('tp'),
    run: knob('tp', 'tp'),
    say: 'Tune is open on true peak.'
  };

  /* ═══ right rail · Analysis — VO_TOOLS 34244..34335 ═════════════════════ */

  VB.actions['voices1.meters'] = {
    view: VIEW,
    label: 'Show the meters for the loaded take',
    aliases: ['meters', 'show the meters', 'measurements', 'what does it measure'],
    args: null,
    el: tool('meters'),
    run: function () { return go(tool('meters'), function () { fn('voMetrics')(); }); },
    say: 'The meters for this take are up.'
  };

  VB.actions['voices1.qc'] = {
    view: VIEW,
    label: 'Show the voice QC verdict',
    aliases: ['qc verdict', 'voice qc', 'the verdict', 'quality check'],
    args: null,
    el: tool('qc'),
    run: function () { return go(tool('qc'), function () { fn('voMetrics')(1); }); },
    say: 'The QC verdict is up.'
  };

  /* ═══ right rail · Rights — VO_TOOLS 34301..34357 ═══════════════════════ */

  VB.actions['voices1.licence'] = {
    view: VIEW,
    label: 'Show the licence of this voice',
    aliases: ['licence', 'license', 'show the licence', 'rights'],
    args: null,
    el: tool('lic'),
    run: function () { return go(tool('lic'), function () { fn('voLicence')(); }); },
    say: 'The licence for this voice is up.'
  };

  VB.actions['voices1.publishable'] = {
    view: VIEW,
    label: 'May this voice reach published audio',
    aliases: ['publishable', 'can i publish this', 'publication policy'],
    args: null,
    el: tool('pub'),
    run: function () { return go(tool('pub'), function () { fn('voLicence')(1); }); },
    say: 'The publication answer is up.'
  };

  /* ═══ bottom dock · Transport — VO_TOOLS 34324..34394 ═══════════════════ */

  VB.actions['voices1.play'] = {
    view: VIEW,
    label: 'Play or pause the selected voice',
    aliases: ['play', 'start playback', 'pause', 'play the voice'],
    args: null,
    el: tool('play'),
    run: function () { return go(tool('play'), function () { fn('voPlay')(); }); },
    say: 'Playing.'
  };

  VB.actions['voices1.stop'] = {
    view: VIEW,
    label: 'Stop the voice player',
    /* not the bare 'stop' — core.stop registers that first and VB.reindex is
       first-wins, so the abort keeps the one-word command */
    aliases: ['stop playing', 'stop the voice', 'stop the player'],
    args: null,
    el: tool('stop'),
    run: function () { return go(tool('stop'), function () { fn('s1Stop')(); }); },
    say: 'Stopped.'
  };

  VB.actions['voices1.prev'] = {
    view: VIEW,
    label: 'Previous voice in the list',
    aliases: ['previous voice', 'go back one voice', 'the one before'],
    args: null,
    el: tool('prev'),
    run: function () { return go(tool('prev'), function () { fn('s1Step')(-1); }); },
    say: 'Playing the previous voice.'
  };

  VB.actions['voices1.next'] = {
    view: VIEW,
    label: 'Next voice in the list',
    aliases: ['next voice', 'go forward one voice', 'the next one'],
    args: null,
    el: tool('next'),
    run: function () { return go(tool('next'), function () { fn('s1Step')(1); }); },
    say: 'Playing the next voice.'
  };

  VB.actions['voices1.loop'] = {
    view: VIEW,
    label: 'Loop the take that is playing',
    aliases: ['loop', 'loop the take', 'repeat the take'],
    args: null,
    el: tool('loop'),
    run: function () { return go(tool('loop'), function () { fn('voLoop')(); }); },
    say: 'Take loop toggled.'
  };

  /* ═══ bottom dock · Takes — VO_TOOLS 34424..34455 ═══════════════════════ */

  VB.actions['voices1.export'] = {
    view: VIEW,
    label: 'Download the loaded take',
    aliases: ['export', 'download this take', 'save the take to disk'],
    args: null,
    el: tool('export'),
    run: function () { return go(tool('export'), function () { fn('voExport')(); }); },
    say: 'Downloading the take.'
  };

  /* ═══ bottom dock · Presets — VO_TOOLS 34456..34482 ═════════════════════ */

  VB.actions['voices1.tune'] = {
    view: VIEW,
    label: 'Open the Tune dialog',
    aliases: ['tune', 'open tune', 'the knobs', 'open the knob panel'],
    args: null,
    el: tool('tune'),
    run: function () { return go(tool('tune'), function () { fn('voTune')(null, null); }); },
    say: 'Tune is open on this voice.'
  };

  /* ═══ bottom dock · Library — VO_TOOLS 34483..34509 ═════════════════════ */

  VB.actions['voices1.assign'] = {
    view: VIEW,
    label: 'Open Assign for this voice',
    aliases: ['assign', 'assign this voice', 'open assign', 'cast this voice'],
    args: null,
    el: tool('assign'),
    run: function () { return go(tool('assign'), function () { fn('voAssign')(); }); },
    say: 'Assign is open on this voice.'
  };

  /* ═══ bottom dock · Merge — VO_TOOLS 34510..34546, markup 6297..6332 ════ */

  VB.actions['voices1.merger'] = {
    view: VIEW,
    label: 'Show or hide the merger',
    aliases: ['merger', 'show the merger', 'hide the merger', 'merge board'],
    args: null,
    el: tool('merger'),
    run: function () { return go(tool('merger'), function () { fn('voMerger')(); }); },
    say: 'The merger is toggled.'
  };

  VB.actions['voices1.merge.play'] = {
    view: VIEW,
    label: 'Play or pause the merged mix',
    aliases: ['play the mix', 'play the merge', 'pause the mix'],
    args: null,
    el: tool('mplay'),
    run: function () { return go(tool('mplay'), function () { fn('m1TogglePlay')(); }); },
    say: 'Playing the mix.'
  };

  VB.actions['voices1.merge.replay'] = {
    view: VIEW,
    label: 'Replay the mix from the start',
    aliases: ['replay the mix', 'from the top', 'play the mix again'],
    args: null,
    el: byId('m1-replay'),
    run: function () { return go(byId('m1-replay'), function () { fn('m1Replay')(); }); },
    say: 'Replaying the mix from the start.'
  };

  VB.actions['voices1.merge.stop'] = {
    view: VIEW,
    label: 'Stop the merged mix',
    aliases: ['stop the mix', 'stop the merge', 'halt the mix'],
    args: null,
    el: byQuery('#m1-transport button[onclick="m1Stop()"]'),
    run: function () {
      return go(byQuery('#m1-transport button[onclick="m1Stop()"]'),
        function () { fn('m1Stop')(); });
    },
    say: 'The mix is stopped.'
  };

  VB.actions['voices1.merge.loop'] = {
    view: VIEW,
    label: 'Loop the merged mix',
    aliases: ['loop the mix', 'loop the merge', 'repeat the mix'],
    args: null,
    el: tool('mloop'),
    run: function () { return go(tool('mloop'), function () { fn('m1ToggleLoop')(); }); },
    say: 'Mix loop toggled.'
  };

  VB.actions['voices1.merge.tweak'] = {
    view: VIEW,
    label: 'Tweak the first merge layer',
    aliases: ['tweak the layer', 'open tweak', 'layer knobs'],
    args: null,
    el: tool('mtweak'),
    run: function () { return go(tool('mtweak'), function () { fn('voTweakHint')(); }); },
    say: 'Tweak is open on the first layer.'
  };

  VB.actions['voices1.merge.fit'] = {
    view: VIEW,
    label: 'Fit the whole merge on screen',
    aliases: ['fit the merge', 'zoom to fit', 'show the whole mix'],
    args: null,
    el: tool('mzoom'),
    run: function () { return go(tool('mzoom'), function () { fn('m1ZoomFit')(); }); },
    say: 'The whole merge is on screen.'
  };

  /* the merger's own +/- pair (markup 6312-6313): one step per call, sign only */
  VB.actions['voices1.merge.zoom'] = {
    view: VIEW,
    label: 'Zoom the merge board in or out',
    aliases: ['zoom the merge', 'zoom in', 'zoom out', 'zoom the board'],
    args: { value: 'number, -1 to zoom out or 1 to zoom in' },
    el: function (args) {
      var dir = Number((args && args.value !== undefined) ? args.value : 1) < 0 ? -1 : 1;
      return document.querySelector('#m1-opts button[onclick="m1Zoom(' + dir + ')"]');
    },
    run: function (args) {
      var dir = Number((args && args.value !== undefined) ? args.value : 1) < 0 ? -1 : 1;
      return go(function () {
        return document.querySelector('#m1-opts button[onclick="m1Zoom(' + dir + ')"]');
      }, function () { fn('m1Zoom')(dir); });
    },
    say: 'Merge board zoomed one step.'
  };

  /* ═══ bottom dock · Browse — VO_TOOLS 34547..34578, list bar 22473..22491 ═ */

  VB.actions['voices1.search'] = {
    view: VIEW,
    label: 'Focus the voice search box',
    aliases: ['search', 'search the voices', 'find a voice'],
    args: null,
    el: tool('search'),
    run: function () { return go(tool('search'), function () { fn('voSearch')(); }); },
    say: 'The search box has the cursor.'
  };

  /* s1SetQuery is the search box's own oninput handler (22423) — it filters
     whether or not the bar is rendered, so the text can be set by voice. */
  VB.actions['voices1.search.text'] = {
    view: VIEW,
    label: 'Search the voice list for a word',
    aliases: ['search for', 'filter the voices', 'look for a voice'],
    args: { text: 'string, the words to filter the voice list by ("" clears it)' },
    el: byQuery('#s1-bar input[type=search]'),
    run: function (args) {
      var text = (args && args.text != null) ? String(args.text) : '';
      return go(byQuery('#s1-bar input[type=search]'), function () {
        var box = document.querySelector('#s1-bar input[type=search]');
        if (box) box.value = text;
        fn('s1SetQuery')(text);
      });
    },
    say: 'The voice list is filtered.'
  };

  VB.actions['voices1.banks'] = {
    view: VIEW,
    label: 'Show which bank the list is on',
    aliases: ['banks', 'which bank', 'show the banks'],
    args: null,
    el: tool('banks'),
    run: function () { return go(tool('banks'), function () { fn('voBanks')(); }); },
    say: 'The bank chips are in view.'
  };

  VB.actions['voices1.only_publishable'] = {
    view: VIEW,
    label: 'Show only publishable voices',
    aliases: ['publishable only', 'only publishable voices', 'clean voices only'],
    args: null,
    el: tool('onlypub'),
    run: function () { return go(tool('onlypub'), function () { fn('s1Toggle')('clean'); }); },
    say: 'Publishable-only filter toggled.'
  };

  VB.actions['voices1.hide_reference'] = {
    view: VIEW,
    label: 'Hide reference-only voices',
    aliases: ['hide reference only', 'hide the reference voices', 'no reference voices'],
    args: null,
    el: tool('onlyref'),
    run: function () { return go(tool('onlyref'), function () { fn('s1Toggle')('noverbal'); }); },
    say: 'Reference-only filter toggled.'
  };

  VB.actions['voices1.sort'] = {
    view: VIEW,
    label: 'Cycle the voice list sort',
    aliases: ['sort', 'change the sort', 'sort the voices'],
    args: null,
    el: tool('sort'),
    run: function () { return go(tool('sort'), function () { fn('voSort')(); }); },
    say: 'The list sort moved on one.'
  };

  VB.actions['voices1.reload'] = {
    view: VIEW,
    label: 'Reload the voice registry',
    aliases: ['reload', 'refresh the voices', 'pull the registry again'],
    args: null,
    el: tool('refresh'),
    run: function () { return go(tool('refresh'), function () { fn('voRefresh')(); }); },
    say: 'Re-pulling the voice registry.'
  };

  /* ═══ bottom dock · Session — VO_TOOLS 34558..34573, bars 6341..6352 ════ */

  VB.actions['voices1.keys'] = {
    view: VIEW,
    label: 'Show the keyboard shortcuts',
    aliases: ['keys', 'keyboard shortcuts', 'what are the keys'],
    args: null,
    el: tool('keys'),
    run: function () { return go(tool('keys'), function () { fn('voKeys')(); }); },
    say: 'The key list is up.'
  };

  VB.actions['voices1.options'] = {
    view: VIEW,
    label: 'List every option in both bars',
    aliases: ['all options', 'what can this studio do', 'the option index'],
    args: null,
    el: tool('index'),
    run: function () { return go(tool('index'), function () { fn('voIndex')(); }); },
    say: 'Every option is on one sheet.'
  };

  VB.actions['voices1.bars'] = {
    view: VIEW,
    label: 'Show or hide both option bars',
    aliases: ['bars', 'hide the bars', 'show the option bars'],
    args: null,
    el: tool('bars'),
    run: function () { return go(tool('bars'), function () { fn('voBarsToggle')(); }); },
    say: 'Both option bars toggled.'
  };

  VB.actions['voices1.session_bar'] = {
    view: VIEW,
    label: 'Show or hide the session bar',
    aliases: ['session bar', 'hide the session bar', 'the bottom bar'],
    args: null,
    el: byId('vo-grip'),
    run: function () { return go(byId('vo-grip'), function () { fn('voDockToggle')(); }); },
    say: 'The session bar is toggled.'
  };

  VB.actions['voices1.sheet.close'] = {
    view: VIEW,
    label: 'Close the option sheet',
    aliases: ['close the sheet', 'close that panel', 'dismiss the sheet'],
    args: null,
    el: byId('vo-info'),
    run: function () { return go(byId('vo-info'), function () { fn('voSheetClose')(); }); },
    say: 'The sheet is closed.'
  };

  /* ═══ the tab itself — switchView 8984..9002 calls s1Enter -> voEnter ════ */

  VB.actions['voices1.enter'] = {
    view: VIEW,
    label: 'Open the Voice Studio',
    aliases: ['voice studio', 'open the voice studio', 'go to voices', 'show the voices'],
    args: null,
    el: byId('vo-tools'),
    run: function () { return go(byId('vo-tools'), function () { return 'voice studio open'; }); },
    say: 'Voice Studio is open.'
  };

}());
