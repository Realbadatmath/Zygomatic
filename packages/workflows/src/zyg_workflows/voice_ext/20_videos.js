// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/20_videos.js — Voice Bridge actions for VIDEO STUDIO (view 'videos').
 *
 * Source of every fact below: inspection.html.
 *   HTML   5383-5426  the view: #vst-status, #vst-rate (onchange vstSetRate),
 *                     #vst-left / #vst-rail / #vst-bar (all built by JS),
 *                     #vst-media, #vst-variants, #vst-log.
 *   JS     11764      var VST — .spec/.params/.pmap/.rackOf/.open/.rate
 *          11779-11792 vstActHtml / vstParHtml: an ACTION icon is #vst-act-<id>
 *                     with onclick vstAction('<id>',this); a PARAMETER icon is
 *                     #vst-ic-<key> with onclick vstOpen('<key>',this).
 *          11796-11832 vstStrip/vstDock/vstBars — the rails are rendered from
 *                     /video/api/spec (video_studio.py RACKS + ACTIONS), so the
 *                     icons only exist once the tab has been entered.
 *          11917-11958 vstFieldHtml — the control vstOpen() puts in #vst-pop:
 *                     select -> vstSet(key,this.value)
 *                     toggle -> vstSet(key,this.checked)
 *                     text/longtext -> vstSet(key,this.value)
 *                     int    -> vstSetNum(key,this)
 *                     knob   -> vstSetKnob(key,this,unit)
 *          12022-12047 vstSet / vstSetNum / vstSetKnob / vstResetKey
 *          12050-12125 vstAction — inject|render|assemble|reset|prompt|
 *                     preset_save|preset_load|history
 *          12167-12211 VST_RATES + vstSetRate/vstRateApply (preview speed)
 *          12521-12527 vstEnter / vstLeave
 *
 * Every run() below drives the studio through its OWN handler, the same one the
 * click fires: a parameter is changed by opening its popover (vstOpen) and then
 * moving the control inside it, exactly as a human does.
 *
 * NOT registered, deliberately: 'inject' (a file/clip picker), 'reset' (it opens
 * confirm()), and view navigation (10_nav.js owns that). Video Studio has no
 * undo function, so there is no videos.undo — vstResetKey is per-option and is
 * exposed as videos.option.reset instead.
 *
 * Top level may only REGISTER: this file is in the bundle that loads BEFORE the
 * studio script, so nothing here may touch the DOM or a vst* global until run().
 */
(function () {
  'use strict';

  var W = window;
  var VB = W.VB;
  var VIEW = 'videos';

  function g(id) { return document.getElementById(id); }

  /* The rails do not exist until the tab has been entered and /video/api/spec
     has come back (vstEnter -> vstLoadSpec -> vstBars). */
  function enter() {
    try {
      if (VB.currentView() !== VIEW) {
        if (typeof W.goToView !== 'function') throw new Error('goToView is not available');
        W.goToView(VIEW);
      }
    } catch (e) { return Promise.reject(e); }
    return VB.waitFor(function () { return g('vst-rail'); }, 6000);
  }

  function param(key) {
    var p = (W.VST && W.VST.pmap) ? W.VST.pmap[key] : null;
    if (!p) throw new Error('Video Studio option "' + key + '" is not in the spec');
    if (p.todo) throw new Error('"' + p.label + '" is listed but not built in Video Studio');
    return p;
  }

  /* Click the icon: vstOpen() draws the single control into #vst-pop. Calling it
     while that key is already open would TOGGLE the popover shut (11962). */
  function openIcon(key) {
    return enter()
      .then(function () { return VB.waitFor(function () { return g('vst-ic-' + key); }, 6000); })
      .then(function (ic) {
        param(key);
        if (W.VST.open !== key) W.vstOpen(key, ic);
        return ic;
      });
  }

  /* the live control inside the popover vstOpen just drew */
  function field(css) {
    return VB.waitFor(function () {
      var pop = g('vst-pop');
      return pop ? pop.querySelector(css) : null;
    }, 3000);
  }

  function matchOption(p, want) {
    var opts = p.options || [];
    var w = String(want === undefined || want === null ? '' : want).trim().toLowerCase();
    if (!w) throw new Error('say which value you want for "' + p.label + '"');
    var hit = opts.filter(function (o) {
      return String(o.v).toLowerCase() === w || String(o.l).toLowerCase() === w;
    })[0];
    if (!hit) {
      hit = opts.filter(function (o) {
        return String(o.l).toLowerCase().indexOf(w) >= 0 || String(o.v).toLowerCase().indexOf(w) >= 0;
      })[0];
    }
    if (!hit) {
      throw new Error('"' + want + '" is not a ' + p.label + ' — choose one of: '
        + opts.map(function (o) { return o.l; }).join(', '));
    }
    return hit;
  }

  function setSelect(key, want) {
    return openIcon(key).then(function () {
      var hit = matchOption(param(key), want);
      return field('select').then(function (el) {
        el.value = String(hit.v);
        W.vstSet(key, el.value);              /* the select's own onchange */
        return hit.l;
      });
    });
  }

  function setToggle(key, want) {
    return openIcon(key).then(function () {
      var w = String(want === undefined || want === null ? 'on' : want).trim().toLowerCase();
      var on = w === 'toggle' ? !W.VST.params[key] : !/^(off|false|no|0)$/.test(w);
      return field('input[type=checkbox]').then(function (el) {
        el.checked = on;
        W.vstSet(key, el.checked);            /* the checkbox's own onchange */
        return on ? 'on' : 'off';
      });
    });
  }

  function setNumber(key, want) {
    return openIcon(key).then(function () {
      var p = param(key);
      var v = parseFloat(want);
      if (!isFinite(v)) throw new Error('"' + want + '" is not a number for ' + p.label);
      var lo = parseFloat(p.min), hi = parseFloat(p.max);
      if (isFinite(lo) && v < lo) v = lo;
      if (isFinite(hi) && v > hi) v = hi;
      if (p.type === 'int') v = Math.round(v);
      var css = p.type === 'int' ? 'input[type=number]' : 'input[type=range]';
      return field(css).then(function (el) {
        el.value = String(v);
        if (p.type === 'int') W.vstSetNum(key, el);           /* 12035 */
        else W.vstSetKnob(key, el, p.unit || '');             /* 12037 */
        return v;
      });
    });
  }

  function setText(key, want) {
    return openIcon(key).then(function () {
      var txt = String(want === undefined || want === null ? '' : want);
      return field('textarea').then(function (el) {
        el.value = txt;
        W.vstSet(key, txt);                   /* the textarea's own oninput */
        return txt.slice(0, 60);
      });
    });
  }

  function runAction(id) {
    return enter()
      .then(function () { return VB.waitFor(function () { return g('vst-act-' + id); }, 6000); })
      .then(function (el) { return W.vstAction(id, el); });   /* 12050 */
  }

  /* ─────────────────────────────────────────────────────────────────────────
     PREVIEW PLAYER — HTML 5404-5410, JS 12167-12211 (#vst-rate / vstSetRate)
     ───────────────────────────────────────────────────────────────────────── */

  function setRate(want) {
    return enter()
      .then(function () { return VB.waitFor(function () { return g('vst-rate'); }, 6000); })
      .then(function (sel) {
        var v = parseFloat(String(want === undefined || want === null ? '' : want)
          .replace(/[x\u00d7\s]/g, ''));
        if (!isFinite(v)) throw new Error('say a playback speed, for example 2 or 0.5');
        var rates = (W.VST_RATES || []).map(function (r) { return r[0]; });
        if (rates.length) {
          v = rates.reduce(function (a, b) { return Math.abs(b - v) < Math.abs(a - v) ? b : a; });
        }
        sel.value = String(v);
        W.vstSetRate(sel.value);              /* the select's own onchange, 5408 */
        return v;
      });
  }

  VB.actions['videos.speed'] = {
    view: VIEW,
    label: 'Preview playback speed',
    aliases: ['preview speed', 'playback speed', 'play the preview faster', 'set preview speed'],
    args: { value: 'playback rate 0.25-30, snapped to the menu' },
    el: function () { return g('vst-rate'); },
    run: function (args) { return setRate((args || {}).value); },
    say: 'Preview speed set.'
  };

  VB.actions['videos.speed.normal'] = {
    view: VIEW,
    label: 'Preview at normal speed',
    aliases: ['normal speed', 'play at normal speed', 'reset preview speed'],
    args: null,
    el: function () { return g('vst-rate'); },
    run: function () { return setRate(1); },
    say: 'Preview back to normal speed.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     DO strip + SESSION dock — vstActHtml 11779-11783, vstAction 12050-12125.
     'inject' and 'reset' are skipped (picker / confirm()).
     ───────────────────────────────────────────────────────────────────────── */

  VB.actions['videos.prompt.preview'] = {
    view: VIEW,
    label: 'Preview the built prompt',
    aliases: ['show the prompt', 'preview the prompt', 'what prompt will it use', 'built prompt'],
    args: null,
    el: function () { return g('vst-act-prompt'); },
    run: function () { return runAction('prompt'); },
    say: 'Here is the prompt the sampler receives.'
  };

  VB.actions['videos.render'] = {
    view: VIEW,
    label: 'Render the clip',
    aliases: ['render', 'render the clip', 'start the render', 'make the video'],
    args: null,
    el: function () { return g('vst-act-render'); },
    run: function () { return runAction('render'); },
    say: 'Render queued. I will say when it is done.'
  };

  VB.actions['videos.assemble'] = {
    view: VIEW,
    label: 'Assemble the shot list',
    aliases: ['assemble', 'assemble the shots', 'cut the shot list together'],
    args: null,
    el: function () { return g('vst-act-assemble'); },
    run: function () { return runAction('assemble'); },
    say: 'Assembling the shot list now.'
  };

  VB.actions['videos.presets.save'] = {
    view: VIEW,
    label: 'Save preset',
    aliases: ['save a preset', 'save preset', 'store these settings'],
    args: null,
    el: function () { return g('vst-act-preset_save'); },
    run: function () { return runAction('preset_save'); },
    say: 'Save panel open. Type a preset name.'
  };

  VB.actions['videos.presets.load'] = {
    view: VIEW,
    label: 'Load preset',
    aliases: ['load a preset', 'load preset', 'open the presets', 'show presets'],
    args: null,
    el: function () { return g('vst-act-preset_load'); },
    run: function () { return runAction('preset_load'); },
    say: 'Presets listed. Pick one to apply.'
  };

  VB.actions['videos.history'] = {
    view: VIEW,
    label: 'Render history',
    aliases: ['render history', 'show the history', 'previous renders', 'past jobs'],
    args: null,
    el: function () { return g('vst-act-history'); },
    run: function () { return runAction('history'); },
    say: 'This session had these renders.'
  };

  VB.actions['videos.popover.close'] = {
    view: VIEW,
    label: 'Close the option panel',
    aliases: ['close the panel', 'close the popover', 'dismiss the option'],
    args: null,
    el: function () { return g('vst-pop'); },
    run: function () { return enter().then(function () { W.vstPopClose(); }); },   /* 12008 */
    say: 'Panel closed.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     SCENE rack — right rail; icons #vst-ic-<key> built by vstStrip 11796-11805
     ───────────────────────────────────────────────────────────────────────── */

  VB.actions['videos.scene.prompt'] = {
    view: VIEW,
    label: 'Scene description',
    aliases: ['scene description', 'set the scene', 'describe the scene', 'scene prompt'],
    args: { value: 'free prose describing the shot' },
    el: function () { return g('vst-ic-scene_prompt'); },
    run: function (args) { return setText('scene_prompt', (args || {}).value); },
    say: 'Scene description written.'
  };

  VB.actions['videos.scene.negative'] = {
    view: VIEW,
    label: 'Negative prompt',
    aliases: ['negative prompt', 'set the negative prompt', 'things to avoid'],
    args: { value: 'free prose listing what must not appear' },
    el: function () { return g('vst-ic-negative_prompt'); },
    run: function (args) { return setText('negative_prompt', (args || {}).value); },
    say: 'Negative prompt written.'
  };

  VB.actions['videos.scene.setting'] = {
    view: VIEW,
    label: 'Setting or location',
    aliases: ['setting', 'location', 'set the location', 'where is the shot'],
    args: { value: 'free prose naming the place' },
    el: function () { return g('vst-ic-setting'); },
    run: function (args) { return setText('setting', (args || {}).value); },
    say: 'Setting written.'
  };

  VB.actions['videos.scene.mode'] = {
    view: VIEW,
    label: 'Prompt mode',
    aliases: ['prompt mode', 'verbatim prompt', 'automatic prompt'],
    args: { value: 'auto or verbatim' },
    el: function () { return g('vst-ic-prompt_mode'); },
    run: function (args) { return setSelect('prompt_mode', (args || {}).value); },
    say: 'Prompt mode changed.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     CAMERA rack — right rail
     ───────────────────────────────────────────────────────────────────────── */

  VB.actions['videos.camera.shot'] = {
    view: VIEW,
    label: 'Shot type',
    aliases: ['shot type', 'set the shot', 'close up', 'wide shot'],
    args: { value: 'e.g. close-up, medium shot, wide shot' },
    el: function () { return g('vst-ic-shot_type'); },
    run: function (args) { return setSelect('shot_type', (args || {}).value); },
    say: 'Shot type set.'
  };

  VB.actions['videos.camera.move'] = {
    view: VIEW,
    label: 'Camera move',
    aliases: ['camera move', 'camera movement', 'push in', 'pull back'],
    args: { value: 'e.g. slow push in, slow pan left, orbiting' },
    el: function () { return g('vst-ic-camera_move'); },
    run: function (args) { return setSelect('camera_move', (args || {}).value); },
    say: 'Camera move set.'
  };

  VB.actions['videos.camera.lens'] = {
    view: VIEW,
    label: 'Lens',
    aliases: ['lens', 'set the lens', 'focal length'],
    args: { value: 'e.g. 24mm, 35mm, 50mm, 85mm' },
    el: function () { return g('vst-ic-lens'); },
    run: function (args) { return setSelect('lens', (args || {}).value); },
    say: 'Lens set.'
  };

  VB.actions['videos.camera.height'] = {
    view: VIEW,
    label: 'Camera height',
    aliases: ['camera height', 'low angle', 'eye level', 'overhead shot'],
    args: { value: 'e.g. eye-level, low angle, overhead' },
    el: function () { return g('vst-ic-camera_height'); },
    run: function (args) { return setSelect('camera_height', (args || {}).value); },
    say: 'Camera height set.'
  };

  VB.actions['videos.camera.locked'] = {
    view: VIEW,
    label: 'Locked camera',
    aliases: ['lock the camera', 'locked camera', 'static shot', 'unlock the camera'],
    args: { value: 'on, off or toggle' },
    el: function () { return g('vst-ic-static_shot'); },
    run: function (args) { return setToggle('static_shot', (args || {}).value); },
    say: 'Locked camera switched.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     MOTION rack — right rail
     ───────────────────────────────────────────────────────────────────────── */

  VB.actions['videos.motion.style'] = {
    view: VIEW,
    label: 'Motion mood',
    aliases: ['motion mood', 'mood', 'set the mood', 'motion style'],
    args: { value: 'e.g. calm, tense, joyful, sad, triumphant' },
    el: function () { return g('vst-ic-motion_style'); },
    run: function (args) { return setSelect('motion_style', (args || {}).value); },
    say: 'Motion mood set.'
  };

  VB.actions['videos.motion.amount'] = {
    view: VIEW,
    label: 'Motion amount',
    aliases: ['motion amount', 'how much motion', 'more motion', 'less motion'],
    args: { value: 'auto, subtle, moderate, dynamic or frenetic' },
    el: function () { return g('vst-ic-motion_amount'); },
    run: function (args) { return setSelect('motion_amount', (args || {}).value); },
    say: 'Motion amount set.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     LOOK rack — right rail
     ───────────────────────────────────────────────────────────────────────── */

  VB.actions['videos.look.style'] = {
    view: VIEW,
    label: 'Visual style',
    aliases: ['visual style', 'look', 'make it cinematic', 'documentary look'],
    args: { value: 'cinematic, documentary, animated or painterly' },
    el: function () { return g('vst-ic-visual_style'); },
    run: function (args) { return setSelect('visual_style', (args || {}).value); },
    say: 'Visual style set.'
  };

  VB.actions['videos.look.lighting'] = {
    view: VIEW,
    label: 'Lighting',
    aliases: ['lighting', 'set the lighting', 'soft light', 'hard light'],
    args: { value: 'e.g. soft diffused, hard directional, rim, low-key' },
    el: function () { return g('vst-ic-lighting'); },
    run: function (args) { return setSelect('lighting', (args || {}).value); },
    say: 'Lighting set.'
  };

  VB.actions['videos.look.time'] = {
    view: VIEW,
    label: 'Time of day',
    aliases: ['time of day', 'golden hour', 'shoot at night', 'set the time of day'],
    args: { value: 'e.g. dawn, midday, golden hour, dusk, night' },
    el: function () { return g('vst-ic-time_of_day'); },
    run: function (args) { return setSelect('time_of_day', (args || {}).value); },
    say: 'Time of day set.'
  };

  VB.actions['videos.look.grade'] = {
    view: VIEW,
    label: 'Grade',
    aliases: ['grade', 'colour grade', 'color grade', 'teal and orange'],
    args: { value: 'none, teal_orange, bleach, warm, cool, sepia, mono' },
    el: function () { return g('vst-ic-grade'); },
    run: function (args) { return setSelect('grade', (args || {}).value); },
    say: 'Grade applied.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     SAMPLER rack — right rail since 2026-09-06 (see comment at 11742)
     ───────────────────────────────────────────────────────────────────────── */

  VB.actions['videos.sampler.duration'] = {
    view: VIEW,
    label: 'Clip duration',
    aliases: ['duration', 'clip length', 'how long is the clip', 'set the duration'],
    args: { value: 'seconds: 1.7, 3.4, 5.1, 6.8 or 10.2' },
    el: function () { return g('vst-ic-duration_s'); },
    run: function (args) { return setSelect('duration_s', (args || {}).value); },
    say: 'Duration set.'
  };

  VB.actions['videos.sampler.steps'] = {
    view: VIEW,
    label: 'Sampler steps',
    aliases: ['steps', 'sampler steps', 'set the steps', 'how many steps'],
    args: { value: 'integer 4-60' },
    el: function () { return g('vst-ic-steps'); },
    run: function (args) { return setNumber('steps', (args || {}).value); },
    say: 'Steps set.'
  };

  VB.actions['videos.sampler.guidance'] = {
    view: VIEW,
    label: 'Guidance (CFG)',
    aliases: ['guidance', 'cfg', 'set the guidance', 'prompt adherence'],
    args: { value: 'number 1-15' },
    el: function () { return g('vst-ic-guidance'); },
    run: function (args) { return setNumber('guidance', (args || {}).value); },
    say: 'Guidance set.'
  };

  VB.actions['videos.sampler.seed'] = {
    view: VIEW,
    label: 'Seed',
    aliases: ['seed', 'set the seed', 'change the seed'],
    args: { value: 'integer 0-999999' },
    el: function () { return g('vst-ic-seed'); },
    run: function (args) { return setNumber('seed', (args || {}).value); },
    say: 'Seed set.'
  };

  VB.actions['videos.sampler.variants'] = {
    view: VIEW,
    label: 'Variants',
    aliases: ['variants', 'how many variants', 'render variants'],
    args: { value: 'integer 1-4' },
    el: function () { return g('vst-ic-variants'); },
    run: function (args) { return setNumber('variants', (args || {}).value); },
    say: 'Variant count set.'
  };

  VB.actions['videos.sampler.resolution'] = {
    view: VIEW,
    label: 'Resolution',
    aliases: ['resolution', 'set the resolution', 'render size', 'make it 720p'],
    args: { value: 'e.g. 832x480, 1280x720, 720x1280' },
    el: function () { return g('vst-ic-resolution'); },
    run: function (args) { return setSelect('resolution', (args || {}).value); },
    say: 'Resolution set.'
  };

  VB.actions['videos.sampler.fps'] = {
    view: VIEW,
    label: 'Render fps',
    aliases: ['frame rate', 'render fps', 'frames per second', 'set the fps'],
    args: { value: 'number 8-60' },
    el: function () { return g('vst-ic-fps'); },
    run: function (args) { return setNumber('fps', (args || {}).value); },
    say: 'Frame rate set.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     LEFT rail — SOURCE / MEMORY / ACCELERATE (vstStrip('left'), 11828)
     ───────────────────────────────────────────────────────────────────────── */

  VB.actions['videos.source.start'] = {
    view: VIEW,
    label: 'Start frame',
    aliases: ['start frame', 'start from the last frame', 'start from the first frame'],
    args: { value: 'last, first or time' },
    el: function () { return g('vst-ic-start_from'); },
    run: function (args) { return setSelect('start_from', (args || {}).value); },
    say: 'Start frame set.'
  };

  VB.actions['videos.memory.blockswap'] = {
    view: VIEW,
    label: 'Block swap',
    aliases: ['block swap', 'swap blocks', 'set the block swap'],
    args: { value: 'integer 0-48' },
    el: function () { return g('vst-ic-block_swap'); },
    run: function (args) { return setNumber('block_swap', (args || {}).value); },
    say: 'Block swap set.'
  };

  VB.actions['videos.memory.offload'] = {
    view: VIEW,
    label: 'Force offload',
    aliases: ['force offload', 'offload the model', 'stop offloading'],
    args: { value: 'on, off or toggle' },
    el: function () { return g('vst-ic-force_offload'); },
    run: function (args) { return setToggle('force_offload', (args || {}).value); },
    say: 'Force offload switched.'
  };

  VB.actions['videos.accel.cache'] = {
    view: VIEW,
    label: 'Accelerator cache',
    aliases: ['cache mode', 'turn on teacache', 'turn off the cache', 'use magcache'],
    args: { value: 'off, teacache, magcache or easycache' },
    el: function () { return g('vst-ic-cache_mode'); },
    run: function (args) { return setSelect('cache_mode', (args || {}).value); },
    say: 'Cache mode set.'
  };

  /* ─────────────────────────────────────────────────────────────────────────
     Per-option reset — vstResetKey 12042. Video Studio has NO undo; this is the
     nearest reversible thing a click can do, and it names one option only.
     ───────────────────────────────────────────────────────────────────────── */

  function keyByLabel(want) {
    var pmap = (W.VST && W.VST.pmap) || {};
    var w = String(want === undefined || want === null ? '' : want).trim().toLowerCase();
    if (!w) throw new Error('say which option to reset');
    var keys = Object.keys(pmap);
    var hit = keys.filter(function (k) {
      return k.toLowerCase() === w || String(pmap[k].label || '').toLowerCase() === w;
    })[0];
    if (!hit) {
      hit = keys.filter(function (k) {
        return String(pmap[k].label || '').toLowerCase().indexOf(w) >= 0;
      })[0];
    }
    if (!hit) throw new Error('no Video Studio option called "' + want + '"');
    return hit;
  }

  VB.actions['videos.option.reset'] = {
    view: VIEW,
    label: 'Reset one option to its default',
    aliases: ['reset that option', 'put it back to default', 'reset the option'],
    args: { value: 'the option label, e.g. guidance or shot type' },
    el: function (args) { return g('vst-ic-' + keyByLabel((args || {}).value)); },
    run: function (args) {
      return enter().then(function () {
        var key = keyByLabel((args || {}).value);
        return VB.waitFor(function () { return g('vst-ic-' + key); }, 6000)
          .then(function () { W.vstResetKey(key); return key; });
      });
    },
    say: 'That option is back at its default.'
  };

  VB.views[VIEW] = VB.views[VIEW] || {};
  VB.views[VIEW].notes = 'Video Studio: rails built from /video/api/spec on entry; '
    + 'a parameter is changed by opening its icon popover, then moving that control.';
})();
