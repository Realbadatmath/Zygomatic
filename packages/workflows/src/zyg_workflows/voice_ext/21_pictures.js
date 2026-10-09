// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/21_pictures.js — Picture Studio (view 'pictures') voice actions.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script, so nothing here may
 * touch the DOM or a studio global at top level: every reference to ptTool,
 * goToView, PT, … lives inside run()/el().
 *
 * THE PAGE HOLDS NO TOOL LIST. All three bars are drawn from
 * /inspect/api/picture/fx/ops (picture_fx.py) by ptRenderBars() / ptDockRender()
 * (inspection.html 12835-12865), and every icon is
 *     <div class="crst-tool" data-pt="<op id>" onclick="ptTool('<op id>')">
 * (ptToolHtml, inspection.html 12776-12796). So the ONE handler a human click
 * calls is ptTool(id) and the live element is .crst-tool[data-pt="id"] — that is
 * what every action below uses. The op ids are declared by _act() in
 * picture_fx.py 1669 + 2165-2330.
 *
 * NOT registered on purpose: sk_clear (empties the stack), sk_del (removes an
 * op), ou_del (the delete-a-bake lane) — destructive; and plain navigation,
 * which belongs to 10_nav.js.
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB;
  if (!VB || !VB.actions) return;

  var VIEW = 'pictures';

  function byId(id) { return W.document.getElementById(id); }

  /* The live icon the ghost cursor moves to. An op can be drawn on the right
     rail, the left rail or the foot bar — the data attribute is the same in all
     three, which is why this is one selector and not three. */
  function tool(id) {
    return W.document.querySelector('.crst-tool[data-pt="' + id + '"]');
  }

  /* switchView() calls ptEnter() (inspection.html 8997 / 13720), which is what
     loads the registry and draws the bars — so "open the view" and "the tools
     exist" are the same wait. */
  function enter() {
    var host = byId('view-pictures');
    if (!host) throw new Error('Picture Studio is not in this page');
    if (host.style.display !== 'flex') {
      if (typeof W.goToView !== 'function') throw new Error('goToView is not available yet');
      W.goToView(VIEW);
    }
    return VB.waitFor(function () {
      var rail = byId('pt-tools');
      return rail && rail.querySelector('.crst-tool');
    }, 8000);
  }

  function fn(name) {
    var f = W[name];
    if (typeof f !== 'function') throw new Error('Picture Studio is not loaded (' + name + ' missing)');
    return f;
  }

  /* run() for a tool icon: enter the studio, then call the SAME ptTool() the
     click calls. ptTool refuses and toasts by itself when the tool is disabled,
     so nothing here second-guesses it. */
  function click(id) {
    return function () {
      return enter().then(function () { fn('ptTool')(id); });
    };
  }

  function num(args, lo, hi, whole) {
    var raw = (args && args.value !== undefined && args.value !== null) ? args.value : '';
    var v = parseFloat(raw);
    if (!isFinite(v)) throw new Error('expected a number between ' + lo + ' and ' + hi + ', got "' + raw + '"');
    if (whole) v = Math.round(v);
    return Math.max(lo, Math.min(hi, v));
  }

  function add(name, spec) {
    spec.view = VIEW;
    VB.actions[VIEW + '.' + name] = spec;
  }

  /* One tool icon, one action. */
  function icon(name, id, label, aliases, say) {
    add(name, {
      label: label,
      aliases: aliases,
      args: null,
      el: function () { return tool(id); },
      run: click(id),
      say: say
    });
  }

  /* ── Stack (Session rail) — picture_fx.py 2165-2196, dispatch 12978-12981 ── */

  icon('stack.open', 'sk_open', 'Open the stack panel',
       ['stack', 'open the stack', 'show the stack'],
       'Stack panel open.');
  icon('stack.move_up', 'sk_up', 'Move the selected op up',
       ['move up', 'move the op up', 'earlier in the stack'],
       'Moved that op up one place.');
  icon('stack.move_down', 'sk_down', 'Move the selected op down',
       ['move down', 'move the op down', 'later in the stack'],
       'Moved that op down one place.');
  icon('stack.duplicate', 'sk_dup', 'Duplicate the selected op',
       ['duplicate', 'duplicate the op', 'copy this op'],
       'Duplicated the selected op.');
  icon('stack.bypass', 'sk_bypass', 'Bypass the selected op',
       ['bypass', 'bypass this op', 'switch the op off'],
       'Bypass toggled on the selected op.');
  icon('stack.solo', 'sk_solo', 'Solo the selected op',
       ['solo', 'solo this op', 'one op only'],
       'Solo toggled.');
  icon('undo', 'sk_undo', 'Undo the last stack change',
       ['undo', 'undo that', 'take that back'],
       'Undone.');
  icon('redo', 'sk_redo', 'Redo the last undone change',
       ['redo', 'redo that', 'put it back'],
       'Redone.');

  /* The stack rows themselves — ptSelectRow(i) / ptToggleRow(i,ev),
     inspection.html 12924-12926, drawn by ptPanelStack 13126-13136. */
  add('stack.select_row', {
    label: 'Select a row in the stack',
    aliases: ['select row', 'pick row', 'select stack row'],
    args: { value: 'number, 1 = the first row of the stack' },
    el: function (args) {
      var i = num(args, 1, 999, true) - 1;
      return W.document.querySelectorAll('#pt-panel-bd .crst-row')[i] || null;
    },
    run: function (args) {
      var i = num(args, 1, 999, true) - 1;
      return enter().then(function () {
        var st = (W.PT && W.PT.stack) || [];
        if (i >= st.length) throw new Error('the stack has only ' + st.length + ' row(s)');
        fn('ptSelectRow')(i);
      });
    },
    say: 'Selected that row.'
  });

  add('stack.toggle_row', {
    label: 'Switch a stack row on or off in place',
    aliases: ['toggle row', 'switch row off', 'switch row on'],
    args: { value: 'number, 1 = the first row of the stack' },
    el: function (args) {
      var i = num(args, 1, 999, true) - 1;
      var row = W.document.querySelectorAll('#pt-panel-bd .crst-row')[i];
      return (row && row.querySelector('.eye')) || row || null;
    },
    run: function (args) {
      var i = num(args, 1, 999, true) - 1;
      return enter().then(function () {
        var st = (W.PT && W.PT.stack) || [];
        if (i >= st.length) throw new Error('the stack has only ' + st.length + ' row(s)');
        fn('ptToggleRow')(i);
      });
    },
    say: 'Toggled that row.'
  });

  /* ── Source — picture_fx.py 2201-2222, dispatch 12982-12983 ─────────────── */

  icon('inject', 'sr_inject', 'Open the inject picker',
       ['inject picture', 'inject a picture', 'open the picker'],
       'Inject picker open.');
  icon('source.pick', 'sr_pick', 'Pick another image of this subject',
       ['pick image', 'pick another image', 'change the source'],
       'Image picker open.');
  icon('source.info', 'sr_info', 'Show the source info panel',
       ['source info', 'picture info', 'show the source details'],
       'Source info panel open.');
  icon('source.reload', 'sr_reload', 'Reload the subject facts',
       ['reload', 'reload the source', 'refresh the subject'],
       'Reloading the subject.');

  /* The two lanes of the inject picker — ptInjectType, inspection.html 13579,
     buttons at 5855-5856; ptInjectApply at 13670, button pt-igo at 5871. */
  add('inject.characters', {
    label: 'Show characters in the inject picker',
    aliases: ['characters', 'show characters', 'character library'],
    args: null,
    el: function () { return byId('pt-type-char'); },
    run: function () {
      return enter().then(function () {
        fn('ptInjectOpen')(); fn('ptInjectType')('char');
      });
    },
    say: 'Showing the character library.'
  });

  add('inject.creatures', {
    label: 'Show creatures in the inject picker',
    aliases: ['creatures', 'show creatures', 'creature library'],
    args: null,
    el: function () { return byId('pt-type-creature'); },
    run: function () {
      return enter().then(function () {
        fn('ptInjectOpen')(); fn('ptInjectType')('creature');
      });
    },
    say: 'Showing the creature library.'
  });

  add('inject.apply', {
    label: 'Load the selected picture onto the stage',
    aliases: ['load it', 'inject it', 'load the picture', 'put it on the stage'],
    args: null,
    el: function () { return byId('pt-igo'); },
    run: function () {
      return enter().then(function () {
        if (!(W.PT && W.PT.inject && W.PT.inject.img)) throw new Error('no picture is selected in the inject picker');
        fn('ptInjectApply')();
      });
    },
    say: 'Loading that picture onto the stage.'
  });

  /* ── Render — picture_fx.py 2225-2247, dispatch 12984-12987 ─────────────── */

  icon('render.open', 'rn_go', 'Open the render panel',
       ['render panel', 'open render', 'show the render panel'],
       'Render panel open.');
  icon('render.settings', 'rn_opts', 'Open the render settings',
       ['render settings', 'render options', 'show the settings'],
       'Render settings open.');
  icon('render.receipt', 'rn_chain', 'Show the render receipt',
       ['receipt', 'show the receipt', 'what would it do'],
       'Receipt panel open.');
  icon('render.jobs', 'rn_jobs', 'Show this session\u2019s renders',
       ['renders', 'show the renders', 'render jobs'],
       'Renders panel open.');

  /* The primary button inside the render panel — ptRender(), inspection.html
     13290, button at 13272. It refuses by itself on an empty stack. */
  add('render.start', {
    label: 'Render and save',
    aliases: ['render it', 'render and save', 'start the render', 'bake it'],
    args: null,
    el: function () {
      return W.document.querySelector('#pt-panel-bd .crst-btn.pri') || tool('rn_go');
    },
    run: function () {
      return enter().then(function () {
        fn('ptPanelOpen')('render');
        fn('ptRender')();
      });
    },
    say: 'Render started.'
  });

  /* Render option bar — ptOptKnob / ptOptSet, inspection.html 13278-13289.
     The ranges are the ones ptPanelRender declares at 13263-13267. Re-opening
     the panel is how the studio itself redraws the knobs at their new value. */
  function optKnob(name, key, label, aliases, lo, hi, whole, say) {
    add(name, {
      label: label,
      aliases: aliases,
      args: { value: 'number ' + lo + '..' + hi },
      el: function () { return byId('pto-' + key); },
      run: function (args) {
        var v = num(args, lo, hi, whole);
        return enter().then(function () {
          fn('ptOptSet')(key, v, 1);
          fn('ptPanelOpen')('render');
        });
      },
      say: say
    });
  }

  optKnob('render.seed', 'seed', 'Set the render seed',
          ['seed', 'set the seed', 'change the seed'], 0, 99999999, true,
          'Seed set.');
  optKnob('render.best_of', 'best_of', 'Set best of N candidates',
          ['best of', 'set best of', 'how many candidates'], 1, 6, true,
          'Best of N set.');
  optKnob('render.steps', 'steps', 'Set the number of steps',
          ['steps', 'set the steps', 'how many steps'], 4, 60, true,
          'Steps set.');
  optKnob('render.guidance', 'cfg', 'Set the guidance value',
          ['guidance', 'set the guidance', 'set c f g'], 1, 12, false,
          'Guidance set.');
  optKnob('render.size', 'size', 'Set the output size',
          ['output size', 'set the size', 'render size'], 256, 2048, true,
          'Output size set.');

  /* ── View — picture_fx.py 2252-2290, dispatch 12988-12995 ───────────────── */

  icon('view.fit', 'vw_fit', 'Fit the picture in the stage',
       ['fit', 'fit the picture', 'fit to screen'],
       'Fitting the picture to the stage.');
  icon('view.actual_size', 'vw_1to1', 'Show the picture at 1:1',
       ['actual size', 'one to one', 'hundred percent'],
       'Showing the picture at 1 to 1.');
  icon('view.zoom_in', 'vw_zoomin', 'Zoom in a step',
       ['zoom in', 'closer', 'zoom in a step'],
       'Zoomed in.');
  icon('view.zoom_out', 'vw_zoomout', 'Zoom out a step',
       ['zoom out', 'further out', 'zoom out a step'],
       'Zoomed out.');
  icon('view.ab', 'vw_ab', 'Toggle the A / B split against the source',
       ['a b', 'compare', 'split view', 'show me the before'],
       'A B split toggled.');
  icon('view.matte', 'vw_alpha', 'Toggle the matte view',
       ['matte view', 'show the matte', 'alpha view'],
       'Matte view toggled.');
  icon('view.checker', 'vw_checker', 'Toggle the checkerboard ground',
       ['checker', 'checkerboard', 'toggle the checker'],
       'Checkerboard toggled.');
  icon('view.ground', 'vw_bg', 'Cycle the ground colour',
       ['ground', 'next ground', 'change the background'],
       'Ground colour changed.');
  icon('view.grid', 'vw_grid', 'Toggle the composition grid',
       ['grid', 'show the grid', 'toggle the grid'],
       'Grid toggled.');

  /* ── Output — picture_fx.py 2295-2330, dispatch 12997-13004 ─────────────── */

  icon('output.save_bake', 'ou_save', 'Open save bake',
       ['save bake', 'save the bake', 'save this edit'],
       'Save panel open.');
  icon('output.bakes', 'ou_bakes', 'Show this studio\u2019s edits',
       ['studio edits', 'show the bakes', 'my edits'],
       'Studio edits panel open.');
  icon('output.download_png', 'ou_png', 'Download the preview as a PNG',
       ['download', 'download the png', 'save a png'],
       'Downloading the preview as a PNG.');
  icon('output.recipe', 'ou_recipe', 'Show the recipe of a bake',
       ['recipe', 'show the recipe', 'how was it made'],
       'Recipe lane open.');
  icon('output.presets', 'ou_presets', 'Show the saved presets',
       ['presets', 'show the presets', 'my presets'],
       'Presets panel open.');
  icon('output.save_preset', 'ou_preset', 'Save the stack as a preset',
       ['save preset', 'save this preset', 'keep this stack'],
       'Preset lane open.');
  icon('output.paths', 'ou_paths', 'Show where this subject lives on disk',
       ['paths', 'show the paths', 'where is it on disk'],
       'Paths panel open.');

  /* ── Enhance / repair — picture_fx.py 1669, ptRepairToggle 13454 ────────── */

  icon('repair.toggle', 'en_repair', 'Toggle the masked repair brush',
       ['repair area', 'paint a repair', 'repair brush'],
       'Repair brush toggled.');

  /* Brush size: the knob at 13537 assigns PT.repair.brush inline, so that
     assignment IS the handler this mirrors. */
  add('repair.brush', {
    label: 'Set the repair brush size',
    aliases: ['brush size', 'set the brush', 'bigger brush', 'smaller brush'],
    args: { value: 'number 4..90, the brush radius in pixels' },
    el: function () {
      return W.document.querySelector('#pt-panel-bd input[type="range"]');
    },
    run: function (args) {
      var v = num(args, 4, 90, true);
      return enter().then(function () {
        if (!W.PT || !W.PT.repair) throw new Error('Picture Studio is not loaded (PT missing)');
        W.PT.repair.brush = v;
        var sl = W.document.querySelector('#pt-panel-bd input[type="range"]');
        if (sl) sl.value = String(v);
      });
    },
    say: 'Brush size set.'
  });

  add('repair.undo', {
    label: 'Undo the last repair stroke',
    aliases: ['undo the stroke', 'undo the paint', 'undo that stroke'],
    args: null,
    el: function () {
      return W.document.querySelector('#pt-panel-bd .crst-btn[onclick*="ptRepairUndo"]');
    },
    run: function () {
      return enter().then(function () { fn('ptRepairUndo')(); });
    },
    say: 'Last repair stroke undone.'
  });

  /* ── The three bars and the panel — inspection.html 5609-5620, 12875-12897,
        ptPanelClose 13098 ──────────────────────────────────────────────────── */

  add('bars.toggle', {
    label: 'Hide or show all three tool bars',
    aliases: ['hide the bars', 'show the bars', 'toggle the bars', 'fold the tools away'],
    args: null,
    el: function () { return byId('pt-arrow'); },
    run: function () {
      return enter().then(function () { fn('ptBarsToggle')(); });
    },
    say: 'Tool bars toggled.'
  });

  add('dock.toggle', {
    label: 'Hide or show the bottom tool bar',
    aliases: ['hide the bottom bar', 'show the bottom bar', 'toggle the dock'],
    args: null,
    el: function () { return byId('pt-grip'); },
    run: function () {
      return enter().then(function () { fn('ptDockToggle')(); });
    },
    say: 'Bottom bar toggled.'
  });

  add('panel.close', {
    label: 'Close the floating panel',
    aliases: ['close the panel', 'close that', 'dismiss the panel'],
    args: null,
    el: function () { return W.document.querySelector('#pt-panel .hd button'); },
    run: function () {
      return enter().then(function () { fn('ptPanelClose')(); });
    },
    say: 'Panel closed.'
  });

  VB.views[VIEW] = VB.views[VIEW] || {
    label: 'Picture Studio',
    note: 'Tool bars are drawn from /inspect/api/picture/fx/ops; every icon '
        + 'dispatches through ptTool(id). Nothing acts until a picture is injected.'
  };
})();
