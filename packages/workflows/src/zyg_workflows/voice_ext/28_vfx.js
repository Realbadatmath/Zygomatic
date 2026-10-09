// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/28_vfx.js — VFX Studio (view 'vfx') voice actions.
 *
 * Every run() calls the studio's OWN handler, the one the click calls:
 *   - both tool bars are rendered from /inspect/api/vfx/fx/ops and dispatch
 *     through vfTool(id)  (inspection.html 27433-27441 builds the cell,
 *     27644-27678 is the dispatcher), so a toolbox action is vfTool('<op id>')
 *     and its element is `.vf-tool[data-fx="<op id>"]` — the attribute the
 *     renderer writes, not an id, because the same cell is drawn on whichever
 *     bar VF_PLACE (27477) sends its family to.
 *   - the Measure trio is prepended by vfMeasureHtml (27461) and carries
 *     `data-sub` for the analyzer/probes panes (vxToolSync, 27316).
 *
 * Top level only registers. Anything touching the DOM or a studio global (VF,
 * VX, goToView, vfTool, vxSub, ...) runs inside el()/run().
 */
(function () {
  'use strict';
  var VB = window.VB;
  var VIEW = 'vfx';

  function reg(name, spec) {
    spec.view = VIEW;
    VB.actions[name] = spec;
  }

  /* ── element locators ─────────────────────────────────────────────────── */

  function byId(id) { return document.getElementById(id); }

  /* a toolbox cell, on either bar (vfToolHtml writes data-fx) */
  function toolEl(fx) {
    return document.querySelector('.vf-tool[data-fx="' + fx + '"]');
  }
  /* an analyzer/probes latch (vfMeasureHtml writes data-sub) */
  function subEl(sub) {
    return document.querySelector('.vf-tool[data-sub="' + sub + '"]');
  }
  /* the Measure cells have no id and Info has no data-sub, so it is found by
     the label the renderer prints into its .lb span */
  function labelEl(label) {
    var cells = document.querySelectorAll('.vf-tool');
    for (var i = 0; i < cells.length; i++) {
      var lb = cells[i].querySelector('.lb');
      if (lb && String(lb.textContent || '').trim().toLowerCase() === label) return cells[i];
    }
    return null;
  }

  /* ── shared run helpers ───────────────────────────────────────────────── */

  /* Open the studio if the control is not on the page yet, then hand the
     element over. goToView('vfx') -> switchView('vfx') -> vxEnter() (9166 /
     9006), which is what loads the toolbox. */
  function ensure(get) {
    var found = null;
    try { found = get(); } catch (e) { found = null; }
    if (found) return Promise.resolve(found);
    if (typeof goToView !== 'function') {
      return Promise.reject(new Error('goToView is not available on this page'));
    }
    goToView(VIEW);
    return VB.waitFor(get, 8000);
  }

  function callTool(fx) {
    return ensure(function () { return toolEl(fx); }).then(function () {
      if (typeof vfTool !== 'function') throw new Error('vfTool() is not loaded');
      vfTool(fx);
      return fx;
    });
  }

  /* One registration for a toolbox entry: same handler, same element. */
  function tool(name, fx, label, aliases, say) {
    reg(name, {
      label: label,
      aliases: aliases,
      args: null,
      el: function () { return toolEl(fx); },
      run: function () { return callTool(fx); },
      say: say
    });
  }

  function num(v, dflt) {
    var n = parseFloat(v);
    return isFinite(n) ? n : dflt;
  }

  /* ══ Measure — vfMeasureHtml 27450-27467, vxSub 27304, vxInfoOpen 29475 ══ */

  reg('vfx.analyzer.toggle', {
    label: 'Show or hide the Analyzer pane',
    aliases: ['analyzer', 'show the analyzer', 'hide the analyzer', 'open analyzer'],
    args: null,
    el: function () { return subEl('analyzer') || labelEl('analyzer'); },
    run: function () {
      return ensure(function () { return subEl('analyzer'); }).then(function () {
        if (typeof vxSub !== 'function') throw new Error('vxSub() is not loaded');
        vxSub('analyzer');
        return 'analyzer';
      });
    },
    say: 'Analyzer pane toggled.'
  });

  reg('vfx.probes.toggle', {
    label: 'Show or hide the Probes pane',
    aliases: ['probes', 'show the probes', 'hide the probes', 'open probes'],
    args: null,
    el: function () { return subEl('probes') || labelEl('probes'); },
    run: function () {
      return ensure(function () { return subEl('probes'); }).then(function () {
        if (typeof vxSub !== 'function') throw new Error('vxSub() is not loaded');
        vxSub('probes');
        return 'probes';
      });
    },
    say: 'Probes pane toggled.'
  });

  reg('vfx.info.open', {
    label: 'Open the run report',
    aliases: ['run report', 'open the report', 'show the run report', 'info'],
    args: null,
    el: function () { return labelEl('info') || byId('vxi-modal'); },
    run: function () {
      return ensure(function () { return byId('vxi-modal'); }).then(function () {
        if (typeof vxInfoOpen !== 'function') throw new Error('vxInfoOpen() is not loaded');
        vxInfoOpen();
        return 'open';
      });
    },
    say: 'Run report open.'
  });

  reg('vfx.info.close', {
    label: 'Close the run report',
    aliases: ['close the report', 'close the run report', 'close info'],
    args: null,
    el: function () { return byId('vxi-modal'); },
    run: function () {
      if (typeof vxInfoClose !== 'function') throw new Error('vxInfoClose() is not loaded');
      vxInfoClose();
      return 'closed';
    },
    say: 'Run report closed.'
  });

  reg('vfx.analyzer.scan', {
    label: 'Scan every frame of the selected clip',
    aliases: ['scan every frame', 'scan the clip', 'start the scan', 'analyse the clip'],
    args: null,
    el: function () { return byId('vx-go'); },
    run: function () {
      return ensure(function () { return byId('vx-go'); }).then(function () {
        if (typeof vxStart !== 'function') throw new Error('vxStart() is not loaded');
        if (!byId('vx-start') || !byId('vx-dur')) {
          throw new Error('the Analyzer pane is not open — say "analyzer" first');
        }
        vxStart();
        return 'scanning';
      });
    },
    say: 'Scanning every frame now.'
  });

  /* ══ Stack actions — dispatcher table vfTool 27644-27678 ════════════════
     Destructive members of the same table are deliberately NOT registered:
     st_del, st_clear, f_revert (they drop the stack), pr_del (the preset
     dialog's own delete), and f_recipe_load (it opens a file picker). */

  tool('vfx.undo', 'st_undo', 'Undo the last stack change',
       ['undo', 'undo that', 'step back'], 'Undone.');
  tool('vfx.redo', 'st_redo', 'Redo the last undone change',
       ['redo', 'redo that', 'step forward'], 'Redone.');
  tool('vfx.stack.up', 'st_up', 'Move the selected op up',
       ['move it up', 'move the op up', 'earlier in the stack'], 'Op moved up.');
  tool('vfx.stack.down', 'st_down', 'Move the selected op down',
       ['move it down', 'move the op down', 'later in the stack'], 'Op moved down.');
  tool('vfx.stack.duplicate', 'st_dupe', 'Duplicate the selected op',
       ['duplicate the op', 'duplicate that', 'another one of those'], 'Op duplicated.');
  tool('vfx.stack.bypass', 'st_bypass', 'Switch the selected op off or on',
       ['bypass', 'bypass that op', 'switch the op off'], 'Op bypass toggled.');
  tool('vfx.stack.solo', 'st_solo', 'Solo the selected op',
       ['solo', 'solo that op', 'only this op'], 'Solo toggled.');
  tool('vfx.stack.copy', 'st_copy', 'Copy the whole stack',
       ['copy the stack', 'copy the whole stack'], 'Stack copied.');
  tool('vfx.stack.paste', 'st_paste', 'Paste the copied stack',
       ['paste the stack', 'paste the copied stack'], 'Stack pasted.');

  /* ══ View / channel / scopes — v_* rows of the same table ═══════════════ */

  tool('vfx.view.rgb', 'v_rgb', 'Show the RGB picture',
       ['rgb', 'show rgb', 'normal picture', 'back to colour'], 'Showing the RGB picture.');
  tool('vfx.view.alpha', 'v_alpha', 'Show the alpha channel',
       ['alpha', 'show the alpha', 'show the matte'], 'Showing the alpha channel.');
  tool('vfx.view.red', 'v_r', 'Show the red channel',
       ['red channel', 'show red'], 'Showing the red channel.');
  tool('vfx.view.green', 'v_g', 'Show the green channel',
       ['green channel', 'show green'], 'Showing the green channel.');
  tool('vfx.view.blue', 'v_b', 'Show the blue channel',
       ['blue channel', 'show blue'], 'Showing the blue channel.');
  tool('vfx.scope.histogram', 'v_hist', 'Histogram scope',
       ['histogram', 'show the histogram'], 'Histogram up.');
  tool('vfx.scope.waveform', 'v_wave', 'Waveform scope',
       ['waveform', 'show the waveform'], 'Waveform up.');
  tool('vfx.scope.vectorscope', 'v_vector', 'Vectorscope',
       ['vectorscope', 'show the vectorscope'], 'Vectorscope up.');
  tool('vfx.scope.parade', 'v_scope_rgb', 'RGB parade scope',
       ['parade', 'rgb parade', 'show the parade'], 'RGB parade up.');
  tool('vfx.compare.ab', 'v_ab', 'A / B against the source',
       ['compare', 'a b compare', 'split with the source'], 'A B compare toggled.');
  tool('vfx.ground.cycle', 'v_bg', 'Cycle the preview ground',
       ['change the ground', 'next background', 'cycle the ground'], 'Ground changed.');
  tool('vfx.overlay.grid', 'v_grid', 'Grid overlay',
       ['grid', 'show the grid', 'hide the grid'], 'Grid toggled.');
  tool('vfx.overlay.safe', 'v_safe', 'Safe area overlay',
       ['safe areas', 'show the safe area', 'title safe'], 'Safe areas toggled.');
  tool('vfx.picker', 'v_picker', 'Colour picker on the preview',
       ['colour picker', 'color picker', 'pick a colour'], 'Colour picker toggled.');
  tool('vfx.zoom.fit', 'v_fit', 'Fit the preview to the box',
       ['fit', 'fit the preview', 'zoom to fit'], 'Preview fitted.');
  tool('vfx.zoom.actual', 'v_1to1', 'Show the preview one to one',
       ['one to one', 'actual pixels', 'hundred percent'], 'Preview at one to one.');

  /* ══ Presets, output, file — pr_* / o_* / f_* rows of the same table ════ */

  tool('vfx.preset.load', 'pr_load', 'Open the presets',
       ['presets', 'open the presets', 'load a preset'], 'Presets open.');
  tool('vfx.preset.save', 'pr_save', 'Save the stack as a preset',
       ['save a preset', 'save this as a preset'], 'Preset dialog open.');
  tool('vfx.output.settings', 'o_format', 'Output settings',
       ['output settings', 'output format', 'change the format'], 'Output settings open.');
  tool('vfx.render.open', 'f_render', 'Open the bake dialog',
       ['render', 'bake the stack', 'open the render dialog'], 'Render dialog open.');
  tool('vfx.chain.show', 'f_chain', 'Show the compiled ffmpeg chain',
       ['show the chain', 'compiled chain', 'show the ffmpeg command'], 'Compiling the chain.');
  tool('vfx.recipe.save', 'f_recipe_save', 'Write the stack out as a recipe',
       ['save the recipe', 'write out the recipe'], 'Recipe written out.');
  tool('vfx.analyzer.handover', 'f_analyze', 'Hand the result to the Analyzer',
       ['send to the analyzer', 'hand it to the analyzer'], 'Handed to the Analyzer.');

  /* ══ The look kit — side ops added to the stack by vfAdd via vfTool ═════
     ids are vfx_fx.py's own (_op(...) lines 384-1606); the same data-fx cell. */

  tool('vfx.add.blur', 'gblur', 'Add a gaussian blur',
       ['add a blur', 'blur it', 'gaussian blur'], 'Gaussian blur added.');
  tool('vfx.add.sharpen', 'unsharp', 'Add an unsharp mask',
       ['sharpen it', 'add sharpening', 'unsharp mask'], 'Unsharp mask added.');
  tool('vfx.add.saturation', 'sat', 'Add a saturation op',
       ['add saturation', 'saturate it', 'more colour'], 'Saturation added.');
  tool('vfx.add.contrast', 'bc', 'Add brightness and contrast',
       ['add contrast', 'brightness and contrast'], 'Bright contrast added.');
  tool('vfx.add.exposure', 'exposure', 'Add an exposure op',
       ['add exposure', 'change the exposure'], 'Exposure added.');
  tool('vfx.add.mono', 'mono', 'Add a monochrome op',
       ['make it black and white', 'add monochrome', 'desaturate it'], 'Monochrome added.');
  tool('vfx.add.invert', 'negate', 'Add an invert op',
       ['invert it', 'add invert', 'negate it'], 'Invert added.');
  tool('vfx.add.glow', 'glow', 'Add a glow or bloom',
       ['add a glow', 'add bloom', 'make it glow'], 'Glow added.');
  tool('vfx.add.vignette', 'vignette', 'Add a vignette',
       ['add a vignette', 'darken the corners'], 'Vignette added.');
  tool('vfx.add.grain', 'noise', 'Add film grain',
       ['add grain', 'add some grain', 'add noise'], 'Grain added.');
  tool('vfx.add.chromakey', 'chromakey', 'Add a chroma key',
       ['add a chroma key', 'key the green', 'green screen key'], 'Chroma key added.');
  tool('vfx.add.filmlook', 'filmlook', 'Add the film look',
       ['add the film look', 'make it filmic'], 'Film look added.');

  /* ══ The floating stack panel and its knobs — vfStackRender 27740 draws
        #vf-stackfl and #vf-setfl; vfSelect 27596, vfFold 27786,
        vfSetOpen 27790, vfSetClose 27799, vfSet 27908, vfReset 27926 ══════ */

  reg('vfx.stack.select', {
    label: 'Select a row of the effect stack',
    aliases: ['select op', 'pick op', 'select the op'],
    args: { value: 'the row number shown in the stack, 1 .. stack length' },
    el: function () { return byId('vf-stackfl'); },
    run: function (args) {
      if (typeof vfSelect !== 'function') throw new Error('vfSelect() is not loaded');
      if (typeof VF === 'undefined') throw new Error('the effect toolbox is not loaded');
      var i = Math.round(num((args || {}).value, 0)) - 1;
      if (i < 0 || i >= VF.stack.length) throw new Error('there is no op number ' + (i + 1));
      vfSelect(i);
      return 'row ' + (i + 1);
    },
    say: 'Op selected.'
  });

  reg('vfx.stack.fold', {
    label: 'Fold or open the stack panel',
    aliases: ['fold the stack', 'open the stack', 'collapse the stack'],
    args: null,
    el: function () { return byId('vf-stackfl'); },
    run: function () {
      return ensure(function () { return byId('vf-stackfl'); }).then(function () {
        if (typeof vfFold !== 'function') throw new Error('vfFold() is not loaded');
        vfFold();
        return 'folded';
      });
    },
    say: 'Stack panel toggled.'
  });

  reg('vfx.knobs.open', {
    label: 'Open the settings of the selected op',
    aliases: ['open the settings', 'show the knobs', 'settings for this op'],
    args: null,
    el: function () { return byId('vf-stackfl'); },
    run: function () {
      return ensure(function () { return byId('vf-stackfl'); }).then(function () {
        if (typeof vfSetOpen !== 'function') throw new Error('vfSetOpen() is not loaded');
        vfSetOpen(-1);
        return 'knobs';
      });
    },
    say: 'Settings panel open.'
  });

  reg('vfx.knobs.close', {
    label: 'Close the settings panel',
    aliases: ['close the settings', 'hide the knobs', 'close the knobs'],
    args: null,
    el: function () { return byId('vf-setfl'); },
    run: function () {
      if (typeof vfSetClose !== 'function') throw new Error('vfSetClose() is not loaded');
      vfSetClose();
      return 'closed';
    },
    say: 'Settings panel closed.'
  });

  reg('vfx.knob.set', {
    label: 'Set a knob on the selected op',
    args: { key: 'the knob key of the selected op, e.g. sigma', value: 'the value; vfSet coerces it to the knob type' },
    aliases: ['set the knob', 'change a setting', 'set a parameter'],
    el: function () { return byId('vf-setfl') || byId('vf-stackfl'); },
    run: function (args) {
      var a = args || {};
      if (!a.key) throw new Error('which knob? pass key');
      if (typeof vfSet !== 'function') throw new Error('vfSet() is not loaded');
      if (typeof VF === 'undefined' || VF.sel < 0 || !VF.stack[VF.sel]) {
        throw new Error('no op is selected in the stack');
      }
      vfSet(String(a.key), a.value);
      return String(a.key) + '=' + a.value;
    },
    say: 'Knob set.'
  });

  reg('vfx.knob.defaults', {
    label: 'Put the selected op back to its defaults',
    aliases: ['back to defaults', 'reset the settings', 'default the op'],
    args: null,
    el: function () { return byId('vf-setfl') || byId('vf-stackfl'); },
    run: function () {
      if (typeof vfReset !== 'function') throw new Error('vfReset() is not loaded');
      if (typeof VF === 'undefined' || VF.sel < 0 || !VF.stack[VF.sel]) {
        throw new Error('no op is selected in the stack');
      }
      vfReset();
      return 'defaults';
    },
    say: 'Op back to its defaults.'
  });

  /* ══ Bars — vfBarsToggle 27535, vfDockToggle 27550 (HTML 6411-6424) ═════ */

  reg('vfx.bars.toggle', {
    label: 'Show or hide both tool bars',
    aliases: ['hide the tool bars', 'show the tool bars', 'toggle the bars'],
    args: null,
    el: function () { return byId('vf-arrow'); },
    run: function () {
      return ensure(function () { return byId('vf-arrow'); }).then(function () {
        if (typeof vfBarsToggle !== 'function') throw new Error('vfBarsToggle() is not loaded');
        vfBarsToggle();
        return 'bars';
      });
    },
    say: 'Tool bars toggled.'
  });

  reg('vfx.dock.toggle', {
    label: 'Show or hide the bottom tool bar',
    aliases: ['hide the bottom bar', 'show the bottom bar', 'toggle the dock'],
    args: null,
    el: function () { return byId('vf-grip'); },
    run: function () {
      return ensure(function () { return byId('vf-grip'); }).then(function () {
        if (typeof vfDockToggle !== 'function') throw new Error('vfDockToggle() is not loaded');
        vfDockToggle();
        return 'dock';
      });
    },
    say: 'Bottom bar toggled.'
  });

  /* ══ The preview stage — HTML 6372-6382, vxStageSpawn 28751, Full 28898 ══ */

  reg('vfx.stage.add', {
    label: 'Add a linked player to the stage',
    aliases: ['add a player', 'another player', 'split the stage'],
    args: null,
    el: function () { return byId('vx-ic-add'); },
    run: function () {
      return ensure(function () { return byId('vx-ic-add'); }).then(function () {
        if (typeof vxStageSpawn !== 'function') throw new Error('vxStageSpawn() is not loaded');
        vxStageSpawn();
        return 'spawned';
      });
    },
    say: 'Another player on the stage.'
  });

  reg('vfx.stage.fullscreen', {
    label: 'Fullscreen the preview stage',
    aliases: ['fullscreen the stage', 'full screen', 'leave fullscreen'],
    args: null,
    el: function () { return byId('vx-ic-full'); },
    run: function () {
      return ensure(function () { return byId('vx-ic-full'); }).then(function () {
        if (typeof vxStageFull !== 'function') throw new Error('vxStageFull() is not loaded');
        vxStageFull();
        return 'fullscreen';
      });
    },
    say: 'Stage fullscreen toggled.'
  });

  /* ══ Sprite flipbook transport — vxPreviewSprite 28963-28973 builds it;
        vxFlipToggle 29031, vxFlipSeek 29013, vxFlipFps 29018 ═════════════ */

  reg('vfx.sprite.play', {
    label: 'Play or pause the sprite flipbook',
    aliases: ['play', 'start playback', 'pause', 'play the sprite'],
    args: null,
    el: function () { return byId('vx-flipbtn'); },
    run: function () {
      var b = byId('vx-flipbtn');
      if (!b) throw new Error('no sprite run is previewed — pick a numbered sprite first');
      if (typeof vxFlipToggle !== 'function') throw new Error('vxFlipToggle() is not loaded');
      vxFlipToggle();
      return 'toggled';
    },
    say: 'Flipbook toggled.'
  });

  reg('vfx.sprite.fps', {
    label: 'Set the flipbook frame rate',
    aliases: ['set the fps', 'play at 6 fps', 'play at 12 fps', 'play at 24 fps'],
    args: { value: 'frames per second, one of 6, 12 or 24' },
    el: function () { return byId('vx-pvtransport'); },
    run: function (args) {
      if (typeof vxFlipFps !== 'function') throw new Error('vxFlipFps() is not loaded');
      var f = num((args || {}).value, 12);
      if (!byId('vx-flipbtn')) throw new Error('no sprite run is previewed');
      vxFlipFps(f);
      return f + ' fps';
    },
    say: 'Frame rate set.'
  });

  reg('vfx.sprite.frame', {
    label: 'Go to a frame of the flipbook',
    aliases: ['go to frame', 'show frame', 'seek the flipbook'],
    args: { value: 'frame index, 0 .. frames - 1' },
    el: function () { return byId('vx-flipsl'); },
    run: function (args) {
      if (typeof vxFlipSeek !== 'function') throw new Error('vxFlipSeek() is not loaded');
      if (!byId('vx-flipsl')) throw new Error('no sprite run is previewed');
      var i = Math.round(num((args || {}).value, 0));
      vxFlipSeek(i);
      return 'frame ' + i;
    },
    say: 'Flipbook moved.'
  });

  /* ══ Preview transport for a stack over a clip — vfTransport 28060-28080.
        The slider has no id; its inline oninput IS the handler, so run()
        repeats exactly what it does. ═════════════════════════════════════ */

  reg('vfx.frame.at', {
    label: 'Preview the frame at a time in seconds',
    aliases: ['frame at', 'go to second', 'preview at'],
    args: { value: 'seconds into the clip, 0 .. duration' },
    el: function () { return document.querySelector('#vx-pvtransport .vx-transsl'); },
    run: function (args) {
      if (typeof VF === 'undefined') throw new Error('the effect toolbox is not loaded');
      if (typeof vfPreviewSoon !== 'function') throw new Error('vfPreviewSoon() is not loaded');
      VF.t = num((args || {}).value, 0);
      var n = byId('vf-tnum');
      if (n) n.textContent = VF.t.toFixed(2) + ' s';
      vfPreviewSoon(220);
      return VF.t + ' s';
    },
    say: 'Preview moved.'
  });

  /* ══ Ledger filter — vxChip 29510-29512 sets VX.filter inline, then
        vxLedger() + vxChips(); this repeats that, nothing more. ══════════ */

  reg('vfx.ledger.filter', {
    label: 'Filter the run ledger',
    aliases: ['show found', 'show not found', 'filter the ledger', 'show unknowns'],
    args: { value: 'found | not_found | unmeasurable | not_detectable | unknowns' },
    el: function () { return document.querySelector('#vx-report .vx-chip'); },
    run: function (args) {
      if (typeof VX === 'undefined') throw new Error('the VFX Studio is not loaded');
      var ok = ['found', 'not_found', 'unmeasurable', 'not_detectable', 'unknowns'];
      var v = String((args || {}).value || 'found').trim().toLowerCase().replace(/\s+/g, '_');
      if (ok.indexOf(v) < 0) throw new Error('unknown ledger state ' + v);
      VX.filter = v;
      if (typeof vxLedger === 'function') vxLedger();
      if (typeof vxChips === 'function') vxChips();
      return v;
    },
    say: 'Ledger filtered.'
  });
})();
