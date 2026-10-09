// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/23_creatures.js — Creature Studio (view 'creatures') voice actions.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script, so this file may only
 * REGISTER at top level. Every DOM / studio-global touch happens inside el() or run().
 *
 * Source of truth (inspection.html):
 *   HTML shell ............ 5451-5533   (ids crst-*)
 *   toolbox state CT ...... 13838-13846
 *   tool markup ........... 13912-13924 (every icon is
 *                                        <div class="crst-tool" data-ct="<id>" onclick="ctTool('<id>')">)
 *   the dispatcher ........ 14088-14146 (ctTool's `acts` table — the handler each click runs)
 *   crstEnter ............. 14759-14763
 * Tool ids/labels come from creature_fx.py `_act(...)` (lines 2257-2588); the bars are
 * rendered from that registry, so `run` always goes through ctTool(id) — the exact
 * function the human's click calls — and never re-implements a handler.
 *
 * Deliberately NOT registered: st_clear (empties the stack), st_del (removes an op),
 * ou_del (deletes a bake) and pr_del (deletes a preset) — destructive, per the brief.
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB = W.VB || { actions: {}, aliases: {}, ready: [], views: {} };
  VB.actions = VB.actions || {};

  var VIEW = 'creatures';
  var WAIT_MS = 6000;

  /* ---------------------------------------------------------------- helpers */

  function doc() { return W.document || null; }

  function byId(id) { var d = doc(); return d ? d.getElementById(id) : null; }

  function q(sel) { var d = doc(); return d ? d.querySelector(sel) : null; }

  /** The icon for a registry op, in whichever of the three bars it was drawn on. */
  function toolEl(id) {
    return function () { return q('.crst-tool[data-ct="' + id + '"]'); };
  }

  function isOpen() {
    var v = byId('view-creatures');
    return !!(v && v.style && v.style.display && v.style.display !== 'none');
  }

  /* The studio has an enter function (crstEnter, 14759) which goToView calls: it is
     what loads the op registry and draws the bars, so nothing has a DOM element
     before the view has been opened once. Wait for the control, but never fail on
     the wait alone — a tool that is off-screen is still clickable by name. */
  function ensure(getEl) {
    return Promise.resolve().then(function () {
      if (!isOpen()) {
        if (typeof W.goToView !== 'function') throw new Error('goToView is not available yet');
        W.goToView(VIEW);
      }
      if (typeof getEl !== 'function' || typeof VB.waitFor !== 'function') return null;
      return VB.waitFor(getEl, WAIT_MS).catch(function () { return null; });
    });
  }

  function need(fn) {
    if (typeof W[fn] !== 'function') throw new Error('Creature Studio is not loaded (' + fn + ' missing)');
    return W[fn];
  }

  /** One bar tool: run() is the tool's own onclick, ctTool('<id>'). */
  function tool(id, label, aliases, say) {
    var get = toolEl(id);
    return {
      view: VIEW,
      label: label,
      aliases: aliases,
      args: null,
      el: get,
      run: function () {
        return ensure(get).then(function () { need('ctTool')(id); return id; });
      },
      say: say
    };
  }

  /* ───────────────────────────────────────────────────────────────────────────
     Stack bar — right rail, section "Stack".
     acts table inspection.html 14097-14105; stack functions 14037-14085.
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.undo'] =
    tool('st_undo', 'Undo', ['undo', 'undo that', 'take that back'], 'Undone.');

  VB.actions['creatures.redo'] =
    tool('st_redo', 'Redo', ['redo', 'do it again', 'put that back'], 'Redone.');

  VB.actions['creatures.stack.up'] =
    tool('st_up', 'Move op up', ['move up', 'move the op up', 'earlier in the stack'], 'Moved it up.');

  VB.actions['creatures.stack.down'] =
    tool('st_down', 'Move op down', ['move down', 'move the op down', 'later in the stack'], 'Moved it down.');

  VB.actions['creatures.stack.duplicate'] =
    tool('st_dupe', 'Duplicate op', ['duplicate', 'duplicate the op', 'copy this op'], 'Duplicated the selected op.');

  VB.actions['creatures.stack.bypass'] =
    tool('st_bypass', 'Bypass op', ['bypass', 'mute the op', 'switch the op off'], 'Bypassed the selected op.');

  VB.actions['creatures.stack.solo'] =
    tool('st_solo', 'Solo op', ['solo', 'solo the op', 'only this op'], 'Soloing the selected op.');

  VB.actions['creatures.stack.copy'] =
    tool('st_copy', 'Copy stack', ['copy the stack', 'copy stack', 'grab this stack'], 'Stack copied.');

  VB.actions['creatures.stack.paste'] =
    tool('st_paste', 'Paste stack', ['paste the stack', 'paste stack', 'drop the stack here'], 'Stack pasted.');

  /* The op knobs are drawn by ctKnobs (14296-14325) and written by ctSet (14326).
     The knob input's own onchange is ctSet(i,k,v) with i = the selected row, so the
     spoken form sets a named knob on whatever op is selected. */
  VB.actions['creatures.stack.knob'] = {
    view: VIEW,
    label: 'Set a knob on the selected op',
    aliases: ['set the knob', 'set knob', 'change the knob'],
    args: { key: 'string, the knob key as the registry names it', value: 'number or string, the new value' },
    el: function (args) {
      var CT = W.CT;
      if (!CT || CT.sel < 0 || !args || !args.key) return null;
      return byId('ctk-' + CT.sel + '-' + String(args.key));
    },
    run: function (args) {
      var key = (args && args.key) ? String(args.key) : '';
      if (!key) throw new Error('which knob? name the parameter');
      var self = this;
      return ensure(function () { return self.el(args); }).then(function () {
        var CT = W.CT;
        if (!CT || CT.sel < 0) throw new Error('Select an op in the stack first.');
        var v = (args && args.value !== undefined) ? args.value : '';
        if (typeof v === 'string' && v !== '' && !isNaN(v)) v = parseFloat(v);
        need('ctSet')(CT.sel, key, v);
        return key + ' = ' + v;
      });
    },
    say: 'Knob set.'
  };

  /* ───────────────────────────────────────────────────────────────────────────
     Source bar — which image of the creature the stack acts on.
     acts table inspection.html 14108-14111; ctStep 14374, ctJump 14380.
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.source.pick'] =
    tool('sr_pick', 'Pick source image', ['pick a source', 'choose the source', 'source images'],
         'Source picker open.');

  VB.actions['creatures.source.previous'] =
    tool('sr_prev', 'Previous source image', ['previous image', 'go back an image', 'previous source'],
         'Previous image.');

  VB.actions['creatures.source.next'] =
    tool('sr_next', 'Next source image', ['next image', 'go on an image', 'next source'], 'Next image.');

  VB.actions['creatures.source.hero'] =
    tool('sr_hero', 'Jump to the hero image', ['hero image', 'go to the hero', 'show the hero'],
         'On the hero image.');

  VB.actions['creatures.source.anchor'] =
    tool('sr_anchor', 'Jump to the identity anchor', ['anchor image', 'go to the anchor', 'show the anchor'],
         'On the identity anchor.');

  VB.actions['creatures.source.reload'] =
    tool('sr_reload', 'Reload the creature facts', ['reload the creature', 'refresh the facts', 'reload facts'],
         'Facts reloaded.');

  VB.actions['creatures.source.info'] =
    tool('sr_info', 'Source image info', ['source info', 'about this image', 'image details'],
         'Source details open.');

  VB.actions['creatures.inject'] = {
    view: VIEW,
    label: 'Open the inject creature picker',
    aliases: ['inject a creature', 'load a creature', 'pick a creature', 'inject creature'],
    args: null,
    el: function () { return q('#view-creatures .cs-inject-btn'); },
    run: function () {
      return ensure(this.el).then(function () { need('crstInjectOpen')(); return 'picker open'; });
    },
    say: 'Creature picker open.'
  };

  /* ───────────────────────────────────────────────────────────────────────────
     Render bar — the bake and its settings.
     acts table inspection.html 14112-14119; ctRender 14505; ctPanelRender 14412.
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.render.settings'] =
    tool('rn_seed', 'Open the render settings', ['render settings', 'open render settings', 'bake settings'],
         'Render settings open.');

  VB.actions['creatures.render.reroll'] =
    tool('rn_dice', 'Reroll the seed', ['reroll', 'new seed', 'roll the dice', 'reroll the seed'],
         'New seed rolled.');

  VB.actions['creatures.render.go'] =
    tool('rn_go', 'Render the stack', ['render', 'render now', 'bake it', 'start the render'],
         'Rendering. A generative bake takes minutes.');

  VB.actions['creatures.render.stop'] =
    tool('rn_stop', 'Stop watching the render', ['stop watching', 'cancel the render', 'stop the render'],
         'Stopped watching the job.');

  VB.actions['creatures.render.receipt'] =
    tool('rn_chain', 'Show the render receipt', ['receipt', 'show the receipt', 'what would be sent'],
         'Receipt open.');

  VB.actions['creatures.presets'] =
    tool('pr_load', 'Open the stack presets', ['presets', 'open presets', 'saved stacks'], 'Presets open.');

  /* The six render numbers. Each is drawn by ctOpt (14432-14438) whose own handler is
     `CT.opts.<k>=parseFloat(this.value)` plus the paired number box #cto-<k>; this does
     exactly that, with the panel opened first so the move is visible. */
  function opt(key, label, aliases, mn, mx, say) {
    return {
      view: VIEW,
      label: label,
      aliases: aliases,
      args: { value: 'number ' + mn + '..' + mx },
      el: function () { return byId('cto-' + key); },
      run: function (args) {
        var raw = (args && args.value !== undefined) ? args.value : null;
        var v = parseFloat(raw);
        if (!isFinite(v)) throw new Error(label + ' needs a number between ' + mn + ' and ' + mx);
        v = Math.max(mn, Math.min(mx, v));
        return ensure(function () { return byId('cto-' + key); }).then(function () {
          need('ctPanelOpen')('render');
          var CT = W.CT;
          if (!CT || !CT.opts) throw new Error('Creature Studio is not loaded (CT.opts missing)');
          CT.opts[key] = v;
          var box = byId('cto-' + key);
          if (box) box.value = v;
          return key + ' = ' + v;
        });
      },
      say: say
    };
  }

  VB.actions['creatures.render.seed'] =
    opt('seed', 'Render seed', ['set the seed', 'seed to', 'use seed'], 0, 99999999, 'Seed set.');

  VB.actions['creatures.render.best_of'] =
    opt('best_of', 'Best of N candidates', ['best of', 'set best of', 'how many candidates'], 1, 6,
        'Best of set.');

  VB.actions['creatures.render.steps'] =
    opt('steps', 'Render steps', ['set the steps', 'steps to', 'use steps'], 4, 60, 'Steps set.');

  VB.actions['creatures.render.cfg'] =
    opt('cfg', 'Guidance', ['set the guidance', 'guidance to', 'set cfg'], 1, 12, 'Guidance set.');

  VB.actions['creatures.render.size'] =
    opt('size', 'Render size', ['set the size', 'size to', 'render size'], 256, 2048, 'Size set.');

  VB.actions['creatures.render.strength'] =
    opt('strength', 'Edit strength', ['set the strength', 'strength to', 'edit strength'], 0, 1.5,
        'Edit strength set.');

  /* The identity band is the one enum on that panel: ctPanelRender 14419-14422,
     whose select onchange is `CT.opts.band=this.value`. */
  VB.actions['creatures.render.band'] = {
    view: VIEW,
    label: 'Identity band',
    aliases: ['identity band', 'set the band', 'band to'],
    args: { value: 'string, one of the registry bands, e.g. front, back, top' },
    el: function () { return q('#crst-panel-bd select'); },
    run: function (args) {
      var band = (args && args.value !== undefined) ? String(args.value).trim().toLowerCase() : '';
      if (!band) throw new Error('which band? front, back or top');
      return ensure(function () { return q('#crst-panel-bd select'); }).then(function () {
        need('ctPanelOpen')('render');
        var CT = W.CT;
        if (!CT || !CT.opts) throw new Error('Creature Studio is not loaded (CT.opts missing)');
        var known = (CT.ops && CT.ops.bands) || [];
        if (known.length && known.indexOf(band) < 0) {
          throw new Error('no such band "' + band + '" — try ' + known.join(', '));
        }
        CT.opts.band = band;
        var sel = q('#crst-panel-bd select');
        if (sel) sel.value = band;
        return 'band = ' + band;
      });
    },
    say: 'Identity band set.'
  };

  /* ───────────────────────────────────────────────────────────────────────────
     View bar — how the preview is shown. acts table inspection.html 14122-14129;
     ctZoom 14201, ctZoomStep 14207, ctBgCycle 14212, ct3dToggle 14216.
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.view.fit'] =
    tool('v_fit', 'Fit the image in the pane', ['fit', 'fit the image', 'fit to the pane'], 'Fitted.');

  VB.actions['creatures.view.actual'] =
    tool('v_1to1', 'Show the image at 1 to 1', ['actual size', 'one to one', 'hundred percent'],
         'Showing at 1 to 1.');

  VB.actions['creatures.view.zoom_in'] =
    tool('v_zoomin', 'Zoom in', ['zoom in', 'closer', 'move in closer'], 'Zoomed in.');

  VB.actions['creatures.view.zoom_out'] =
    tool('v_zoomout', 'Zoom out', ['zoom out', 'further back', 'pull back'], 'Zoomed out.');

  VB.actions['creatures.view.ab'] =
    tool('v_ab', 'Toggle the A B compare', ['compare', 'a b compare', 'show me the before'],
         'A B compare toggled.');

  VB.actions['creatures.view.matte'] =
    tool('v_alpha', 'Toggle the matte view', ['matte', 'show the matte', 'alpha view'], 'Matte view toggled.');

  VB.actions['creatures.view.checker'] =
    tool('v_checker', 'Toggle the checker ground', ['checker', 'checkerboard', 'toggle the checker'],
         'Checker toggled.');

  VB.actions['creatures.view.ground'] =
    tool('v_bg', 'Cycle the ground colour', ['change the ground', 'next background', 'cycle the ground'],
         'Ground changed.');

  VB.actions['creatures.view.grid'] =
    tool('v_grid', 'Toggle the grid overlay', ['grid', 'show the grid', 'toggle the grid'], 'Grid toggled.');

  VB.actions['creatures.view.orbit'] =
    tool('v_pin', 'Toggle the 3D orbit view', ['orbit', 'turn it around', 'three d view', 'spin it'],
         'Orbit view toggled.');

  /* ───────────────────────────────────────────────────────────────────────────
     Output bar — what is done with the result. acts inspection.html 14130-14136;
     ctPromote 14595, ctDownload 14665. ou_del is deliberately absent.
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.output.save'] =
    tool('ou_save', 'Save the edit as a bake', ['save the edit', 'keep this edit', 'save this edit'],
         'Saving the edit.');

  VB.actions['creatures.output.hero'] =
    tool('ou_hero', 'Promote a bake to hero', ['make it the hero', 'set as hero', 'promote to hero'],
         'Hero panel open.');

  VB.actions['creatures.output.lock'] =
    tool('ou_lock', 'Set an anchor lock', ['anchor lock', 'set the anchor lock', 'lock the anchor'],
         'Anchor lock panel open.');

  VB.actions['creatures.output.tile'] =
    tool('ou_tile', 'Add a training tile', ['add a training tile', 'training tile', 'add a tile'],
         'Training tile panel open.');

  VB.actions['creatures.output.reference'] =
    tool('ou_ref', 'Add as a reference', ['add as reference', 'add a reference', 'keep as reference'],
         'Reference panel open.');

  VB.actions['creatures.output.download'] =
    tool('ou_png', 'Download the result', ['download', 'download the picture', 'save the png'],
         'Downloading at full size.');

  VB.actions['creatures.output.recipe'] =
    tool('ou_recipe', 'Show the recipe', ['recipe', 'show the recipe', 'how was this made'], 'Recipe open.');

  /* ───────────────────────────────────────────────────────────────────────────
     Pipeline bar — inspection.html 14137-14141.
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.pipeline.brief'] =
    tool('pl_brief', 'Open the creature brief', ['brief', 'open the brief', 'creature brief'], 'Brief open.');

  VB.actions['creatures.pipeline.judge'] =
    tool('pl_judge', 'Run the judge', ['run the judge', 'judge it', 'judge this creature'], 'Judging.');

  VB.actions['creatures.pipeline.sheet'] =
    tool('pl_sheet', 'Rebuild the contact sheet', ['rebuild the sheet', 'contact sheet', 'sheet commands'],
         'Sheet commands open.');

  VB.actions['creatures.pipeline.train'] =
    tool('pl_train', 'Retrain the LoRA', ['retrain', 'retrain the lora', 'training commands'],
         'Training commands open.');

  VB.actions['creatures.pipeline.jobs'] =
    tool('pl_jobs', 'Show the jobs', ['jobs', 'show the jobs', 'what is running'], 'Jobs open.');

  VB.actions['creatures.pipeline.folder'] =
    tool('pl_open', 'Show the folder paths', ['folder', 'show the folder', 'where is it on disk'],
         'Paths open.');

  /* ───────────────────────────────────────────────────────────────────────────
     Measure bar — creature_fx.py 2257-2320; ctTool routes every ms_ id to
     ctMeasure (inspection.html 14143, 14484).
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.measure.identity'] =
    tool('ms_identity', 'Measure identity', ['measure identity', 'identity score', 'how close is it'],
         'Measuring identity.');

  VB.actions['creatures.measure.change'] =
    tool('ms_change', 'Measure the change', ['measure the change', 'how much changed', 'change score'],
         'Measuring the change.');

  VB.actions['creatures.measure.judge'] =
    tool('ms_judge', 'Judge the picture', ['judge', 'judge the picture', 'judge score'], 'Judging the picture.');

  VB.actions['creatures.measure.plan'] =
    tool('ms_plan', 'Measure the body plan', ['body plan', 'measure the body plan', 'check the body plan'],
         'Measuring the body plan.');

  VB.actions['creatures.measure.facts'] =
    tool('ms_facts', 'Show the picture facts', ['facts', 'picture facts', 'show the facts'], 'Facts open.');

  VB.actions['creatures.measure.palette'] =
    tool('ms_palette', 'Measure the palette', ['palette', 'measure the palette', 'what colours'],
         'Measuring the palette.');

  VB.actions['creatures.measure.licence'] =
    tool('ms_licence', 'Show the licence', ['licence', 'show the licence', 'can we sell it'], 'Licence open.');

  VB.actions['creatures.measure.history'] =
    tool('ms_history', 'Show the history', ['history', 'show the history', 'what happened to it'],
         'History open.');

  /* ───────────────────────────────────────────────────────────────────────────
     Studio chrome — the two bar folds and the floating panel.
     inspection.html 5508-5531 (markup), 14009-14031 + 14253 (handlers).
     ────────────────────────────────────────────────────────────────────────── */

  VB.actions['creatures.bars.toggle'] = {
    view: VIEW,
    label: 'Fold or unfold the tool bars',
    aliases: ['hide the tools', 'show the tools', 'fold the bars', 'toggle the bars'],
    args: null,
    el: function () { return byId('crst-arrow'); },
    run: function () {
      return ensure(this.el).then(function () { need('ctBarsToggle')(); return 'bars toggled'; });
    },
    say: 'Tool bars toggled.'
  };

  VB.actions['creatures.dock.toggle'] = {
    view: VIEW,
    label: 'Show or hide the bottom bar',
    aliases: ['hide the bottom bar', 'show the bottom bar', 'toggle the dock'],
    args: null,
    el: function () { return byId('crst-grip'); },
    run: function () {
      return ensure(this.el).then(function () { need('ctDockToggle')(); return 'dock toggled'; });
    },
    say: 'Bottom bar toggled.'
  };

  VB.actions['creatures.panel.close'] = {
    view: VIEW,
    label: 'Close the floating panel',
    aliases: ['close the panel', 'shut the panel', 'dismiss the panel'],
    args: null,
    el: function () { return q('#crst-panel .hd button'); },
    run: function () {
      return ensure(this.el).then(function () { need('ctPanelClose')(); return 'panel closed'; });
    },
    say: 'Panel closed.'
  };

  VB.actions['creatures.panel.stack'] = {
    view: VIEW,
    label: 'Open the stack panel',
    aliases: ['open the stack', 'show the stack', 'stack panel'],
    args: null,
    el: function () { return byId('crst-panel'); },
    run: function () {
      return ensure(this.el).then(function () { need('ctPanelOpen')('stack'); return 'stack panel'; });
    },
    say: 'Stack panel open.'
  };

  VB.views[VIEW] = VB.views[VIEW] || {
    label: 'Creature Studio',
    notes: 'Every tool acts on ONE injected creature and ONE of its images. '
         + 'Inject a creature first — with nothing loaded the toolbox only offers the source picker.'
  };
})();
