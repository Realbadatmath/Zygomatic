// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/22_charstudio.js — Voice Bridge actions for Character Studio.
 *
 * Loaded from /voice_ext/bundle.js, which sits right after /arch_ext/bundle.js
 * (inspection.html line 6911) — i.e. BEFORE the studio script (6916..34826).
 * So this file only REGISTERS at top level; every DOM touch and every studio
 * global (goToView, csInjectOpen, cstStageField, ...) is reached inside el()/run().
 *
 * How this studio is wired (inspection.html):
 *   · view div            #view-charstudio, HTML 5646-5705 (display:flex when open)
 *   · tool tables         CS_TOOLS 10304-10923 — one flat table for BOTH bars.
 *                         `bar:'side'` sections (the parts of the character) are
 *                         rendered into #cst-dock, `bar:'dock'` sections (the
 *                         session: File/Run/Edit/View) into #cst-tools — the swap
 *                         lives in CST_PLACE (10941).
 *   · one click handler   10963-10986 renders every tool as
 *                         <div data-cstool="<id>">, and the single delegated
 *                         listener at 11698-11711 does the work:
 *                            t.f   -> cstFieldPanel(t)
 *                            t.act -> CST_ACT[t.act](t)   (CST_ACT 11491-11680)
 *                         There is NO per-tool function to call, so run() clicks
 *                         the live element and lets that listener dispatch — the
 *                         exact path a human click takes. VB.cursor.click() does
 *                         not click for us (01_cursor.js:10), so nothing runs twice.
 *   · field editing       cstFieldPanel builds one editor with id #cst-in;
 *                         "Stage" calls cstStageField(path) (11170), which reads
 *                         #cst-in. The set.* actions below fill that same input and
 *                         call cstStageField — they do not write CST.dirty directly.
 *
 * NOT registered, on purpose: d_delete / d_revert (drop-everything buttons with no
 * confirm of their own), d_import (file picker), and the ~92 placeholder icons that
 * have neither `f` nor `act`. Character Studio has no undo function — d_undo
 * (10883) is a drawn placeholder and CST_ACT has no `undo` — so charstudio.undo is
 * not registered. The ctSet / ct. functions (13838-14660) belong to #view-creatures
 * (5451), not to this view, so none of them are registered here.
 */
(function () {
  'use strict';

  var VB = (window.VB = window.VB || { actions: {}, aliases: {}, ready: [], views: {} });

  var VIEW = 'charstudio';
  var WAIT_MS = 6000;

  VB.views[VIEW] = VB.views[VIEW] || {
    title: 'Character Studio',
    note: 'Injected character preview; the rail is the session, the foot bar the parts.'
  };

  /* ── plumbing ─────────────────────────────────────────────────────────── */

  function viewEl() { return document.getElementById('view-charstudio'); }

  /* switchView() sets display:flex on the open view (the studio's own keyboard
     handler tests exactly this, inspection.html:11716) */
  function isOpen() {
    var v = viewEl();
    return !!(v && v.style && v.style.display === 'flex');
  }

  /* csEnter() (10251) builds both bars, so nothing below exists until the view
     has been entered once */
  function enter() {
    if (isOpen()) return Promise.resolve(true);
    if (typeof window.goToView !== 'function') {
      return Promise.reject(new Error('goToView is not on the page yet'));
    }
    window.goToView(VIEW);
    return VB.waitFor(function () { return isOpen() ? true : null; }, WAIT_MS);
  }

  function toolEl(id) {
    var v = viewEl();
    return v ? v.querySelector('[data-cstool="' + id + '"]') : null;
  }

  /* open the view, wait for the icon, then click it — the delegated listener at
     11698 is the handler the human click reaches */
  function tool(id) {
    return enter()
      .then(function () { return VB.waitFor(function () { return toolEl(id); }, WAIT_MS); })
      .then(function (el) {
        if (el.classList && el.classList.contains('dis')) {
          throw new Error('inject a character first — ' + id + ' needs one');
        }
        el.click();
        return true;
      });
  }

  /* for controls that are plain onclick="..." in the HTML */
  function callGlobal(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    return enter().then(function () {
      var fn = window[name];
      if (typeof fn !== 'function') throw new Error(name + ' is not on the page');
      return fn.apply(window, args);
    });
  }

  /* open a field tool's panel, put the number in its editor (#cst-in) and press
     Stage for it — cstStageField(path) is the studio's own reader/writer */
  function stageNumber(toolId, path, raw) {
    var n = Number(raw);
    if (!isFinite(n)) {
      return Promise.reject(new Error('"' + raw + '" is not a number'));
    }
    return tool(toolId)
      .then(function () {
        return VB.waitFor(function () { return document.getElementById('cst-in'); }, WAIT_MS);
      })
      .then(function (input) {
        if (typeof window.cstStageField !== 'function') {
          throw new Error('cstStageField is not on the page');
        }
        input.value = String(n);
        window.cstStageField(path);
        return true;
      });
  }

  /* the spec for an action that is one icon in one of the two bars */
  function toolSpec(id, label, aliases, say) {
    return {
      view: VIEW,
      label: label,
      aliases: aliases,
      args: null,
      el: function () { return toolEl(id); },
      run: function () { return tool(id); },
      say: say
    };
  }

  /* ── header: inject (HTML 5646-5654) ──────────────────────────────────── */

  VB.actions['charstudio.inject'] = {
    view: VIEW,
    label: 'Inject character',
    aliases: ['inject character', 'inject a character', 'load a character', 'pick a character'],
    args: null,
    el: function () {
      var v = viewEl();
      return v ? v.querySelector('.cs-inject-btn') : null;
    },
    run: function () { return callGlobal('csInjectOpen'); },
    say: 'Character picker is open. Choose one.'
  };

  /* ── rail: File (CS_TOOLS 10828-10850) ────────────────────────────────── */

  VB.actions['charstudio.bible'] = toolSpec('d_bible', 'Whole bible',
    ['show the bible', 'whole bible', 'character bible', 'open the bible'],
    'The character bible, exactly as it sits on disk.');

  VB.actions['charstudio.export'] = toolSpec('d_export', 'Export bible',
    ['export the bible', 'download the bible', 'export this character', 'save a copy'],
    'Downloading this character bible as JSON.');

  VB.actions['charstudio.rename'] = toolSpec('d_rename', 'Rename',
    ['rename', 'rename the character', 'change the name', 'edit the name'],
    'Name editor is open.');

  /* ── rail: Run (CS_TOOLS 10852-10874) ─────────────────────────────────── */

  VB.actions['charstudio.refresh'] = toolSpec('d_refresh', 'Refresh from disk',
    ['refresh', 'reload from disk', 'read it again', 'refresh the character'],
    'Read the bible and the files off disk again.');

  VB.actions['charstudio.library'] = toolSpec('d_library', 'Open in Library',
    ['open in library', 'show in the library', 'find it in the library'],
    'Opening this character in the Library list.');

  /* ── rail: Edit (CS_TOOLS 10876-10898; cstSaveAll 11187) ──────────────── */

  VB.actions['charstudio.save'] = toolSpec('d_save', 'Save all edits',
    ['save', 'save all', 'save the edits', 'write it to the bible'],
    'Writing every staged edit to the bible.');

  /* ── rail: View (CS_TOOLS 10900-10922; CST_ACT 11509-11511) ───────────── */

  VB.actions['charstudio.fit'] = toolSpec('d_fit', 'Fit the preview',
    ['fit', 'fit the preview', 'frame the character', 'fit to view'],
    'Preview framed again.');

  VB.actions['charstudio.view.reset'] = toolSpec('d_reset', 'Reset the camera',
    ['reset the view', 'reset the camera', 'put the camera back'],
    'Camera is back where it started.');

  VB.actions['charstudio.angles'] = toolSpec('d_angles', 'Front / side angles',
    ['front and side', 'canonical angles', 'snap to front', 'show the angles'],
    'Snapped to the plate angles, front and side.');

  VB.actions['charstudio.plate'] = toolSpec('d_plate', 'Plate',
    ['show the plate', 'depth plate', 'pose plate', 'open plates'],
    'Reading the plate manifest for this character.');

  VB.actions['charstudio.fullscreen'] = toolSpec('d_full', 'Full screen preview',
    ['full screen', 'hide the bars', 'preview only', 'bars out of the way'],
    'Both bars hidden. Preview has the whole stage.');

  /* ── the two bars and the panel (HTML 5675-5689, 5699-5704;
        cstBarsToggle 11011, cstDockToggle 11026, cstPanelClose 11038) ───── */

  VB.actions['charstudio.bars.toggle'] = {
    view: VIEW,
    label: 'Show or hide both tool bars',
    aliases: ['toggle the bars', 'hide both bars', 'show the bars', 'toggle the tool bars'],
    args: null,
    el: function () { return document.getElementById('cst-arrow'); },
    run: function () { return callGlobal('cstBarsToggle'); },
    say: 'Both tool bars toggled.'
  };

  VB.actions['charstudio.dock.toggle'] = {
    view: VIEW,
    label: 'Show or hide the bottom bar',
    aliases: ['toggle the bottom bar', 'hide the bottom bar', 'show the bottom bar', 'toggle the dock'],
    args: null,
    el: function () { return document.getElementById('cst-grip'); },
    run: function () { return callGlobal('cstDockToggle'); },
    say: 'Bottom tool bar toggled.'
  };

  VB.actions['charstudio.panel.close'] = {
    view: VIEW,
    label: 'Close the open panel',
    aliases: ['close the panel', 'close it', 'shut the panel', 'dismiss the panel'],
    args: null,
    el: function () {
      var p = document.getElementById('cst-panel');
      return p ? p.querySelector('.hd button') : null;
    },
    run: function () { return callGlobal('cstPanelClose'); },
    say: 'Panel closed.'
  };

  /* ── foot bar: Voice and Motion (CS_TOOLS 10712-10761) ────────────────── */

  VB.actions['charstudio.voice.pick'] = toolSpec('voicepick', 'Pick a voice',
    ['pick a voice', 'choose a voice', 'open the voice picker', 'change the voice'],
    'Voice picker is open. Ten voices to choose from.');

  VB.actions['charstudio.voice.studio'] = toolSpec('voicestudio', 'Open Voice Studio',
    ['open voice studio', 'go to voice studio', 'take me to the voices'],
    'Opening Voice Studio.');

  VB.actions['charstudio.movement.studio'] = toolSpec('motionstudio', 'Open Movement Studio',
    ['open movement studio', 'go to movement studio', 'open the motion studio'],
    'Opening Movement Studio.');

  /* ── foot bar: Body (CS_TOOLS 10446-10480) ────────────────────────────── */

  VB.actions['charstudio.body.proportions'] = toolSpec('proportions', 'Proportions',
    ['proportions', 'body proportions', 'show the proportions', 'head to body'],
    'Proportions panel is open.');

  VB.actions['charstudio.body.hands'] = toolSpec('hands', 'Hands',
    ['hands', 'show the hands', 'hand axis', 'open hands'],
    'Hands panel is open.');

  /* ── foot bar: Accessories and Expression (10517-10544, 10567-10594) ──── */

  VB.actions['charstudio.props'] = toolSpec('props', 'Handheld props',
    ['handheld props', 'show the props', 'prop meshes', 'open props'],
    'Reading the registered prop meshes.');

  VB.actions['charstudio.smile'] = toolSpec('smile', 'Smile intent',
    ['smile intent', 'show the smile keys', 'is she smiling', 'open smile'],
    'Smile keys read straight off this bible.');

  /* ── foot bar: Model (CS_TOOLS 10660-10711) ───────────────────────────── */

  VB.actions['charstudio.loras'] = toolSpec('loras', 'LoRA files',
    ['lora files', 'show the loras', 'which weights', 'open the loras'],
    'LoRA files, as the bible claims and as disk holds them.');

  VB.actions['charstudio.refs'] = toolSpec('refs', 'Reference images',
    ['reference images', 'show the references', 'ip adapter references'],
    'Reference images listed for this character.');

  /* ── foot bar: Sheet (CS_TOOLS 10762-10792) ───────────────────────────── */

  VB.actions['charstudio.sheet'] = toolSpec('sheet', 'Contact sheet',
    ['contact sheet', 'show the sheet', 'open the contact sheet'],
    'Contact sheet manifest is open.');

  VB.actions['charstudio.finals'] = toolSpec('finals', 'Arcane finals',
    ['arcane finals', 'show the finals', 'finished pictures'],
    'Counting the finished pictures on disk.');

  VB.actions['charstudio.training'] = toolSpec('training', 'Training sets',
    ['training sets', 'show the training images', 'training folders'],
    'Training folders counted off disk.');

  /* ── foot bar: Checks (CS_TOOLS 10793-10827) ──────────────────────────── */

  VB.actions['charstudio.qc'] = toolSpec('qc', 'Identity QC',
    ['identity qc', 'show the qc', 'quality control', 'open qc'],
    'Identity QC as this run recorded it.');

  VB.actions['charstudio.approval'] = toolSpec('approval', 'Approval',
    ['approval', 'is it approved', 'show the approval'],
    'Approval read off the sheet manifest.');

  VB.actions['charstudio.licence'] = toolSpec('licence', 'Licence',
    ['licence', 'license', 'show the licence', 'which licence'],
    'Licence of the model family the bible names.');

  VB.actions['charstudio.disk'] = toolSpec('disk', 'On disk',
    ['on disk', 'how big is it', 'disk usage', 'show the folder'],
    'Folder size and images by folder.');

  VB.actions['charstudio.history'] = toolSpec('history', 'Scene history',
    ['scene history', 'show the history', 'which scenes'],
    'Scene history for this character.');

  VB.actions['charstudio.stats'] = toolSpec('stats', 'Generation stats',
    ['generation stats', 'show the stats', 'render statistics'],
    'Generation stats recorded in this bible.');

  VB.actions['charstudio.diff'] = toolSpec('diff', 'Unsaved edits',
    ['unsaved edits', 'what is staged', 'show the diff', 'what have i changed'],
    'Every staged edit, against what is on disk.');

  /* ── field editors: open the panel (cstFieldPanel 11141) ──────────────── */

  VB.actions['charstudio.field.name'] = toolSpec('name', 'Name field',
    ['edit the name', 'name field', 'open the name'],
    'Name editor is open.');

  VB.actions['charstudio.field.hair.colour'] = toolSpec('haircolor', 'Hair colour field',
    ['hair colour', 'hair color', 'edit the hair colour'],
    'Hair colour editor is open.');

  VB.actions['charstudio.field.eye.colour'] = toolSpec('eyecolor', 'Eye colour field',
    ['eye colour', 'eye color', 'edit the eye colour'],
    'Eye colour editor is open.');

  VB.actions['charstudio.field.skin.tone'] = toolSpec('skintone', 'Skin tone field',
    ['skin tone', 'edit the skin tone', 'complexion tone'],
    'Skin tone editor is open.');

  VB.actions['charstudio.field.clothing'] = toolSpec('clothing', 'Default clothing field',
    ['clothing', 'what they wear', 'edit the clothing', 'default clothing'],
    'Clothing editor is open.');

  /* ── numeric setters: fill #cst-in, then cstStageField (11170) ────────── */

  VB.actions['charstudio.set.age'] = {
    view: VIEW,
    label: 'Stage a new age',
    aliases: ['set the age', 'change the age', 'set age to', 'age them to'],
    args: { value: 'number 1..99, the character age in years' },
    el: function () { return toolEl('age'); },
    run: function (args) { return stageNumber('age', 'identity.age', args && args.value); },
    say: 'Age staged. Say save to write it.'
  };

  VB.actions['charstudio.set.height'] = {
    view: VIEW,
    label: 'Stage a new height',
    aliases: ['set the height', 'change the height', 'set height to', 'make them taller'],
    args: { value: 'height in metres, e.g. 1.75' },
    el: function () { return toolEl('height'); },
    run: function (args) { return stageNumber('height', 'identity.height_m', args && args.value); },
    say: 'Height staged. Say save to write it.'
  };

  VB.actions['charstudio.set.muscle'] = {
    view: VIEW,
    label: 'Stage muscle mass',
    aliases: ['set the muscle mass', 'change the muscle', 'how muscular'],
    args: { value: 'number 1..100' },
    el: function () { return toolEl('muscle'); },
    run: function (args) { return stageNumber('muscle', 'identity.muscle_mass', args && args.value); },
    say: 'Muscle mass staged. Say save to write it.'
  };

  VB.actions['charstudio.set.lora.scale'] = {
    view: VIEW,
    label: 'Stage the LoRA scale',
    aliases: ['set the lora scale', 'change the lora scale', 'lora strength'],
    args: { value: 'LoRA weight, typically 0 to 1.5' },
    el: function () { return toolEl('lorascale'); },
    run: function (args) { return stageNumber('lorascale', 'conditioning.lora_scale', args && args.value); },
    say: 'LoRA scale staged. Say save to write it.'
  };

  VB.actions['charstudio.set.ipadapter.scale'] = {
    view: VIEW,
    label: 'Stage the IPAdapter scale',
    aliases: ['set the ip adapter scale', 'change the ip adapter scale', 'reference strength'],
    args: { value: 'IPAdapter weight, typically 0 to 1' },
    el: function () { return toolEl('ipascale'); },
    run: function (args) {
      return stageNumber('ipascale', 'conditioning.ipadapter_scale', args && args.value);
    },
    say: 'IPAdapter scale staged. Say save to write it.'
  };
}());
