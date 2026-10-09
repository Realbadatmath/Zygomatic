// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/24_movement.js — Movement Studio (view 'movement') voice actions.
 *
 * Loaded by /voice_ext/bundle.js BEFORE the studio script, so nothing here may
 * touch the DOM or a studio global at top level: every reference to goToView,
 * MO, moSet, mvstGenerate … lives inside el()/run().
 *
 * Sources in inspection.html (read 2026-09-15):
 *   HTML  5717-5808   #view-movement — top bar, stage, #mo-bar, #mo-toolcol, #mo-sheet
 *   JS   14903-15610  MO state, the two bars (moBarsRender/moStripHtml/moBarHtml),
 *                     the popover setters moSet/moSetNum/moResetKey/moOpen,
 *                     moPickAction (library), moAction (the Do strip), fold toggles
 *   JS   15619-15877  mvst* — inject picker, preview swap, mode latch, generate/stop,
 *                     mvstEnter (the tab's enter function)
 * Dial keys and action ids are the server spec: movement_studio.py RACKS (lines
 * 293-804), ACTIONS (809-847), LIBRARY (133-266).
 *
 * NOT registered on purpose: moAction('reset') and moPresetDelete (confirm()),
 * moAction('preset_save') (prompt()), moJobDelete (destructive + confirm),
 * mvstInjectApply / the inject list (a picker over server data), view navigation
 * (10_nav.js owns it). Movement Studio has no undo function, so there is no
 * movement.undo.
 */
(function (W) {
  'use strict';

  var VB = W.VB;
  if (!VB || !VB.actions) return;

  var VIEW = 'movement';

  VB.views[VIEW] = {
    title: 'Movement Studio',
    note: 'Inject a subject, pick a movement, shape it with the dials, probe, then render.'
  };

  /* A studio global, or a readable error instead of a ReferenceError. */
  function fn(name) {
    var f = W[name];
    if (typeof f !== 'function') {
      throw new Error('Movement Studio is not loaded yet (' + name + ' is missing)');
    }
    return f;
  }

  function byId(id) {
    return function () { return W.document ? W.document.getElementById(id) : null; };
  }

  /* mvstEnter() builds both bars, so every control below only exists once the
     tab has been entered. Open it, then wait for the control itself. */
  function ensure(id) {
    var get = function () { return W.document ? W.document.getElementById(id) : null; };
    var el = get();
    if (el) return Promise.resolve(el);
    if (typeof W.goToView === 'function') W.goToView(VIEW);
    return VB.waitFor(get, 8000);
  }

  function def(name, spec) {
    spec.view = VIEW;
    VB.actions[name] = spec;
  }

  /* ── the Do strip: moAction(id, el) — JS 15267-15300 ───────────────────── */
  function doAction(id) {
    return function () {
      return ensure('mo-act-' + id).then(function (el) {
        fn('moAction')(id, el);
        return id;
      });
    };
  }

  /* ── the dials: moSet / moSetNum, typed off MO.pmap — JS 15164-15177 ───── */
  function setDial(key) {
    return function (args) {
      var raw = (args && args.value !== undefined && args.value !== null) ? args.value : null;
      if (raw === null || String(raw).trim() === '') {
        throw new Error('the ' + key + ' dial needs a value');
      }
      return ensure('mo-ic-' + key).then(function () {
        var p = (W.MO && W.MO.pmap) ? W.MO.pmap[key] : null;
        var type = p ? p.type : 'select';
        if (type === 'int' || type === 'float') {
          var n = Number(raw);
          if (!isFinite(n)) throw new Error(String(raw) + ' is not a number for ' + key);
          if (p && p.min !== undefined) n = Math.max(Number(p.min), n);
          if (p && p.max !== undefined) n = Math.min(Number(p.max), n);
          if (type === 'int') n = Math.round(n);
          /* moSetNum is the oninput handler; it reads el.value and nothing else. */
          fn('moSetNum')(key, { value: String(n) }, (p && p.unit) || '');
          return key + ' = ' + n;
        }
        if (type === 'toggle') {
          var on = (raw === true) || /^(1|on|yes|true|enabled)$/i.test(String(raw));
          fn('moSet')(key, on);
          return key + ' = ' + (on ? 'on' : 'off');
        }
        var v = String(raw).trim();
        if (type === 'select' && p && p.options) {
          var hit = p.options.filter(function (o) {
            return String(o.v).toLowerCase() === v.toLowerCase() ||
                   String(o.l).toLowerCase() === v.toLowerCase();
          })[0];
          if (!hit) {
            throw new Error(v + ' is not a ' + key + ' option (' +
              p.options.map(function (o) { return o.v; }).join(', ') + ')');
          }
          v = String(hit.v);
        }
        fn('moSet')(key, v);
        return key + ' = ' + v;
      });
    };
  }

  function dial(name, key, label, aliases, argDesc, say) {
    def(name, {
      label: label,
      aliases: aliases,
      args: { value: argDesc },
      el: byId('mo-ic-' + key),
      run: setDial(key),
      say: say
    });
  }

  /* ═══ TOP BAR — HTML 5718-5738 ══════════════════════════════════════════ */

  def('movement.inject', {
    label: 'Open the Inject Subject picker',
    aliases: ['inject subject', 'inject a subject', 'pick a subject', 'load a subject'],
    args: null,
    el: function () {
      return W.document ? W.document.querySelector('#view-movement .cs-inject-btn') : null;
    },
    run: function () {
      return ensure('mvst-inject').then(function () { fn('mvstInjectOpen')(); return 'open'; });
    },
    say: 'Subject picker open. Choose a character, creature or object.'
  });

  def('movement.mode.probe', {
    label: 'Latch the probe mode (33 frames)',
    aliases: ['probe mode', 'switch to probe', 'set probe mode', 'use probe'],
    args: null,
    el: byId('mvst-mode-probe'),
    run: function () {
      return ensure('mvst-mode-probe').then(function () { fn('mvstSetMode')('probe'); return 'probe'; });
    },
    say: 'Probe mode. Generate now renders 33 frames.'
  });

  def('movement.mode.full', {
    label: 'Latch the full clip mode',
    aliases: ['full clip mode', 'switch to full clip', 'set full mode', 'use full clip'],
    args: null,
    el: byId('mvst-mode-full'),
    run: function () {
      return ensure('mvst-mode-full').then(function () { fn('mvstSetMode')('full'); return 'full'; });
    },
    say: 'Full clip mode. Length comes from the engine dial.'
  });

  def('movement.generate', {
    label: 'Generate at the latched mode',
    aliases: ['generate', 'start the render', 'render it', 'start rendering'],
    args: null,
    el: byId('mvst-go'),
    run: function () {
      return ensure('mvst-go').then(function () { fn('mvstGenerate')(); return 'started'; });
    },
    say: 'Render started. Watch the status line above the preview.'
  });

  def('movement.render.full', {
    label: 'Render the full clip',
    aliases: ['render the full clip', 'full render', 'render full length'],
    args: null,
    el: byId('mvst-go'),
    run: function () {
      return ensure('mvst-go').then(function () { fn('mvstGenerate')('full'); return 'started'; });
    },
    say: 'Full clip render started.'
  });

  def('movement.render.probe', {
    label: 'Render a 33 frame probe',
    aliases: ['probe render', 'run a probe', 'probe it', 'quick probe'],
    args: null,
    el: byId('mvst-go'),
    run: function () {
      return ensure('mvst-go').then(function () { fn('mvstGenerate')('probe'); return 'started'; });
    },
    say: 'Probe render started. 33 frames on the same dials.'
  });

  def('movement.stop', {
    label: 'Stop the running render',
    aliases: ['stop the render', 'abort the render', 'stop rendering', 'halt the render'],
    args: null,
    el: byId('mvst-stop'),
    run: function () {
      return ensure('mvst-stop').then(function () { fn('mvstStop')(); return 'stopping'; });
    },
    say: 'Abort written. The watchdog stops the render shortly.'
  });

  /* ═══ FOLD SWITCHES — HTML 5735, 5784, 5791 · JS 15571-15610 ════════════ */

  def('movement.options.toggle', {
    label: 'Fold both option bars away, or back',
    aliases: ['toggle the options', 'fold the options', 'hide the option bars', 'show the option bars'],
    args: null,
    el: byId('mo-bars-btn'),
    run: function () {
      return ensure('mo-bars-btn').then(function () { fn('moBarsToggle')(); return 'toggled'; });
    },
    say: 'Option bars toggled.'
  });

  def('movement.bottombar.toggle', {
    label: 'Fold the bottom bar away, or back',
    aliases: ['toggle the bottom bar', 'fold the bottom bar', 'hide the bottom bar', 'show the bottom bar'],
    args: null,
    el: byId('mo-grip'),
    run: function () {
      return ensure('mo-grip').then(function () { fn('moDockToggle')(); return 'toggled'; });
    },
    say: 'Bottom bar toggled.'
  });

  /* ═══ THE "Do" STRIP — JS 15267-15300, spec movement_studio.ACTIONS ═════ */

  def('movement.prompt.preview', {
    label: 'Preview the prompt these dials produce',
    aliases: ['preview the prompt', 'show the prompt', 'what prompt is this', 'read the prompt'],
    args: null,
    el: byId('mo-act-prompt'),
    run: doAction('prompt'),
    say: 'The composed sentence is on screen.'
  });

  def('movement.recipe', {
    label: 'Show the recipe and the render kwargs',
    aliases: ['show the recipe', 'open the recipe', 'what did i change', 'show non default dials'],
    args: null,
    el: byId('mo-act-recipe'),
    run: doAction('recipe'),
    say: 'Recipe open, with every dial moved off default.'
  });

  def('movement.plate.check', {
    label: 'Check the prop plate',
    aliases: ['check the plate', 'plate check', 'show the prop plate'],
    args: null,
    el: byId('mo-act-plate'),
    run: doAction('plate'),
    say: 'Plate check open.'
  });

  def('movement.log', {
    label: 'Show the render log',
    aliases: ['show the log', 'open the render log', 'read the log'],
    args: null,
    el: byId('mo-act-log'),
    run: doAction('log'),
    say: 'Render log open.'
  });

  def('movement.library', {
    label: 'Open the rendered clip library',
    aliases: ['open the library', 'show the clips', 'movement library', 'show rendered clips'],
    args: null,
    el: byId('mo-act-library'),
    run: doAction('library'),
    say: 'Library open, newest clip first.'
  });

  def('movement.recall', {
    label: 'Recall a finished clip dials',
    aliases: ['recall the dials', 'recall a clip', 'load a clip settings'],
    args: null,
    el: byId('mo-act-recall'),
    run: doAction('recall'),
    say: 'Pick the clip whose dials you want back.'
  });

  def('movement.seed.roll', {
    label: 'Roll a new random seed',
    aliases: ['roll the seed', 'new seed', 'random seed', 'roll the dice'],
    args: null,
    el: byId('mo-act-dice'),
    run: doAction('dice'),
    say: 'New seed rolled.'
  });

  def('movement.preset.load', {
    label: 'Open the saved dial states',
    aliases: ['load a preset', 'open the presets', 'show the presets'],
    args: null,
    el: byId('mo-act-preset_load'),
    run: doAction('preset_load'),
    say: 'Saved dial states listed.'
  });

  def('movement.track.extract', {
    label: 'Extract a track from the driver clip',
    aliases: ['extract the track', 'extract a track', 'run pose track'],
    args: null,
    el: byId('mo-act-track'),
    run: doAction('track'),
    say: 'Track extraction started. This can take many minutes.'
  });

  def('movement.sheet.close', {
    label: 'Close the centred sheet',
    aliases: ['close the sheet', 'close the panel', 'dismiss the sheet'],
    args: null,
    el: byId('mo-sheet'),
    run: function () {
      return ensure('mo-sheet').then(function () { fn('moSheetClose')(); return 'closed'; });
    },
    say: 'Sheet closed.'
  });

  def('movement.popover.close', {
    label: 'Close the dial popover',
    aliases: ['close the dial', 'close the popover', 'close the option'],
    args: null,
    el: byId('mo-pop'),
    run: function () {
      return ensure('mo-pop').then(function () { fn('moPopClose')(); return 'closed'; });
    },
    say: 'Dial closed.'
  });

  /* ═══ THE MOVEMENT LIBRARY — moPickAction, JS 15180-15200 ═══════════════ */

  function pick(id) {
    return function () {
      return ensure('mo-lib-' + id).then(function () { fn('moPickAction')(id); return id; });
    };
  }

  def('movement.pick', {
    label: 'Pick a movement from the library by id',
    aliases: ['pick the movement', 'choose the movement', 'set the movement', 'use the movement'],
    args: { value: 'library id, e.g. walk, run, wave, sit, jump, dance, talk' },
    el: function () { return W.document ? W.document.getElementById('mo-bar') : null; },
    run: function (args) {
      var id = (args && args.value) ? String(args.value).trim().toLowerCase().replace(/\s+/g, '_') : '';
      if (!id) throw new Error('name the movement, e.g. walk');
      if (id === 'custom') throw new Error('use movement.motion.custom with the text instead');
      return ensure('mo-lib-' + id).then(function () { fn('moPickAction')(id); return id; });
    },
    say: 'Movement picked.'
  });

  def('movement.pick.idle', {
    label: 'Movement: idle / breathe',
    aliases: ['idle', 'just breathe', 'stand still', 'idle breathe'],
    args: null, el: byId('mo-lib-idle'), run: pick('idle'),
    say: 'Idle picked. The subject only breathes.'
  });

  def('movement.pick.walk', {
    label: 'Movement: walk',
    aliases: ['walk', 'make it walk', 'walking'],
    args: null, el: byId('mo-lib-walk'), run: pick('walk'),
    say: 'Walk picked.'
  });

  def('movement.pick.run', {
    label: 'Movement: run',
    aliases: ['run', 'make it run', 'running'],
    args: null, el: byId('mo-lib-run'), run: pick('run'),
    say: 'Run picked.'
  });

  def('movement.pick.wave', {
    label: 'Movement: wave',
    aliases: ['wave', 'make it wave', 'waving'],
    args: null, el: byId('mo-lib-wave'), run: pick('wave'),
    say: 'Wave picked.'
  });

  def('movement.pick.jump', {
    label: 'Movement: jump',
    aliases: ['jump', 'make it jump', 'jumping'],
    args: null, el: byId('mo-lib-jump'), run: pick('jump'),
    say: 'Jump picked.'
  });

  def('movement.pick.sit', {
    label: 'Movement: sit down',
    aliases: ['sit', 'sit down', 'make it sit'],
    args: null, el: byId('mo-lib-sit'), run: pick('sit'),
    say: 'Sit down picked.'
  });

  def('movement.pick.talk', {
    label: 'Movement: speak',
    aliases: ['talk', 'speak', 'make it talk'],
    args: null, el: byId('mo-lib-talk'), run: pick('talk'),
    say: 'Speak picked.'
  });

  def('movement.pick.dance', {
    label: 'Movement: dance',
    aliases: ['dance', 'make it dance', 'dancing'],
    args: null, el: byId('mo-lib-dance'), run: pick('dance'),
    say: 'Dance picked.'
  });

  def('movement.motion.custom', {
    label: 'Type a custom motion sentence',
    aliases: ['custom motion', 'describe the motion', 'set the custom motion'],
    args: { text: 'string, the motion to describe in words' },
    el: byId('mo-ic-custom_prompt'),
    run: function (args) {
      var text = (args && (args.text || args.value)) ? String(args.text || args.value).trim() : '';
      if (!text) throw new Error('say the motion you want, in words');
      return ensure('mo-bar').then(function () {
        fn('moSet')('custom_prompt', text);
        fn('moPickAction')('custom');
        return text;
      });
    },
    say: 'Custom motion set. The sentence is rebuilding.'
  });

  /* ═══ MOTION rack — movement_studio.py 293-367 ═════════════════════════ */

  dial('movement.speed', 'speed', 'Speed of the action',
    ['set the speed', 'speed', 'how fast', 'change the speed'],
    'one of: natural, very slow, slow, brisk, fast, frantic',
    'Speed set.');

  dial('movement.intensity', 'intensity', 'Intensity of the action',
    ['set the intensity', 'intensity', 'how hard', 'change the intensity'],
    'one of: natural, minimal, subtle, strong, extreme',
    'Intensity set.');

  dial('movement.amplitude', 'amplitude', 'Range of motion',
    ['set the range of motion', 'range of motion', 'set the amplitude'],
    'one of: natural, tight and contained, wide and open, exaggerated',
    'Range of motion set.');

  dial('movement.style', 'style', 'Motion style',
    ['set the motion style', 'motion style', 'change the style'],
    'one of: natural, graceful, heavy and weighted, light and floating, mechanical, jerky, fluid, animated and exaggerated',
    'Motion style set.');

  dial('movement.easing', 'easing', 'Easing curve',
    ['set the easing', 'easing', 'change the easing'],
    'one of: none, in, out, both, snap',
    'Easing set.');

  dial('movement.repeat', 'repeat', 'Repetition inside the clip',
    ['set the repetition', 'repetition', 'how many times', 'set the repeat'],
    'one of: once, twice, three, loop',
    'Repetition set.');

  dial('movement.anticipation', 'anticipation', 'Anticipation before the action',
    ['anticipation', 'turn anticipation on', 'turn anticipation off'],
    'on or off',
    'Anticipation switched.');

  dial('movement.secondary', 'secondary', 'Secondary motion',
    ['secondary motion', 'turn secondary motion on', 'turn secondary motion off'],
    'on or off',
    'Secondary motion switched.');

  /* ═══ SPACE rack — movement_studio.py 370-415 ══════════════════════════ */

  dial('movement.direction', 'direction', 'Direction of travel',
    ['set the direction', 'direction', 'which way'],
    'e.g. in place, towards camera, away from camera, left, right',
    'Direction set.');

  dial('movement.facing', 'facing', 'Facing',
    ['set the facing', 'facing', 'which way is it facing'],
    'e.g. unchanged, towards camera, away, left, right',
    'Facing set.');

  /* ═══ BODY rack — movement_studio.py 417-489 ═══════════════════════════ */

  dial('movement.expression', 'expression', 'Facial expression',
    ['set the expression', 'expression', 'change the expression'],
    'e.g. unchanged, neutral, smiling, angry, afraid',
    'Expression set.');

  dial('movement.gaze', 'gaze', 'Gaze',
    ['set the gaze', 'gaze', 'where is it looking'],
    'e.g. natural, at camera, away, down',
    'Gaze set.');

  dial('movement.mood', 'mood', 'Mood',
    ['set the mood', 'mood', 'change the mood'],
    'e.g. unchanged, calm, tense, joyful, weary',
    'Mood set.');

  /* ═══ IDENTITY rack — movement_studio.py 526-557 ═══════════════════════ */

  dial('movement.lora.strength', 'lora_strength', 'Subject LoRA strength',
    ['set the lora strength', 'lora strength', 'how strong is the lora'],
    'number 0 to 1, e.g. 0.5',
    'LoRA strength set.');

  dial('movement.binding', 'binding', 'Canon binding',
    ['canon binding', 'turn binding on', 'turn binding off'],
    'on or off',
    'Canon binding switched.');

  /* ═══ VACE PIN rack — movement_studio.py 560-607 ═══════════════════════ */

  dial('movement.pin.strength', 'vace_strength', 'VACE pin strength',
    ['set the pin strength', 'pin strength', 'how strong is the pin'],
    'number 0 to 1, e.g. 0.7',
    'Pin strength set.');

  dial('movement.skeleton', 'char_geom', 'Skeleton guide',
    ['skeleton guide', 'turn the skeleton on', 'turn the skeleton off'],
    'on or off',
    'Skeleton guide switched.');

  /* ═══ ENGINE rack — movement_studio.py 685-734 ═════════════════════════ */

  dial('movement.shift', 'shift', 'Shift, the motion amount',
    ['set the shift', 'shift', 'motion amount'],
    'number, e.g. 5.0 — 2.0 renders frozen',
    'Shift set.');

  dial('movement.steps', 'steps', 'Sampler steps',
    ['set the steps', 'steps', 'how many steps'],
    'whole number, e.g. 30',
    'Steps set.');

  dial('movement.cfg', 'cfg', 'CFG scale',
    ['set the cfg', 'cfg', 'guidance scale'],
    'number, e.g. 6.0',
    'CFG set.');

  dial('movement.seed', 'seed', 'Seed',
    ['set the seed', 'seed', 'change the seed'],
    'whole number, e.g. 7',
    'Seed set.');

  dial('movement.length', 'num_frames', 'Clip length in frames',
    ['set the length', 'how many frames', 'clip length', 'set the frames'],
    'one of: 17, 33, 49, 65, 81, 97, 129',
    'Length set. The full clip button now says so.');

  dial('movement.resolution', 'resolution', 'Render resolution',
    ['set the resolution', 'resolution', 'what size'],
    'e.g. 832x480, 1280x720',
    'Resolution set.');

  dial('movement.attention', 'attention', 'Attention backend',
    ['set the attention', 'attention backend', 'which attention'],
    'one of: sdpa, sageattn, flash_attn',
    'Attention backend set.');

  dial('movement.timeout', 'timeout_s', 'Render timeout in seconds',
    ['set the timeout', 'timeout', 'how long before it gives up'],
    'whole number of seconds, 300 to 10800',
    'Timeout set.');

  /* ═══ LONG CLIPS / FINISH / GATES racks — movement_studio.py 737-804 ═══ */

  dial('movement.windows', 'context_windows', 'Context windows for long clips',
    ['context windows', 'turn context windows on', 'turn context windows off'],
    'on or off',
    'Context windows switched.');

  dial('movement.interpolate', 'interpolate', 'Interpolate to 24 fps',
    ['interpolate', 'turn interpolation on', 'turn interpolation off'],
    'on or off',
    'Interpolation switched.');

  dial('movement.gate.mask', 'mask_gate', 'Mask preflight gate',
    ['mask gate', 'turn the mask gate on', 'turn the mask gate off'],
    'on or off',
    'Mask gate switched.');

  dial('movement.gate.beat', 'beat_gate', 'Beat map gate',
    ['beat gate', 'turn the beat gate on', 'turn the beat gate off'],
    'on or off',
    'Beat gate switched.');

  /* ═══ per-dial popover: open, and reset one dial — JS 15121, 15172 ═════ */

  def('movement.dial.open', {
    label: 'Open one dial popover',
    aliases: ['open the dial', 'show me the dial', 'open the option'],
    args: { value: 'dial key, e.g. shift, steps, seed, resolution' },
    el: function () { return W.document ? W.document.getElementById('mo-bar') : null; },
    run: function (args) {
      var key = (args && args.value) ? String(args.value).trim() : '';
      if (!key) throw new Error('name the dial to open');
      return ensure('mo-ic-' + key).then(function (el) {
        fn('moOpen')(key, el);
        return key;
      });
    },
    say: 'Dial open.'
  });

  def('movement.dial.reset', {
    label: 'Reset one dial to its default',
    aliases: ['reset the dial', 'put the dial back', 'default this dial'],
    args: { value: 'dial key, e.g. shift, steps, seed, resolution' },
    el: function () { return W.document ? W.document.getElementById('mo-bar') : null; },
    run: function (args) {
      var key = (args && args.value) ? String(args.value).trim() : '';
      if (!key) throw new Error('name the dial to reset');
      return ensure('mo-ic-' + key).then(function () {
        fn('moResetKey')(key);
        return key;
      });
    },
    say: 'Dial back at its default.'
  });

}(typeof window !== 'undefined' ? window : this));
