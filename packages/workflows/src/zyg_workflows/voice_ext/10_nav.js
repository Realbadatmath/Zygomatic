// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/10_nav.js — navigation: one `nav.<view>` action per tab of the top bar,
 * plus the two Architecture Studio verbs that have no tab of their own.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script (inspection.html 6934..),
 * so this file may only REGISTER at top level. goToView, switchView, AR, arEnsure,
 * arAssistRender, arAssistSend and arUndo do not exist yet when this runs — they are
 * only ever reached from inside run()/el(), which fire long after the page is up.
 *
 * Every run() calls the studio's own handler (goToView, the very function the tab's
 * onclick calls) and then waits until the view div is actually displayed, so the
 * action does not report success before the tab is on screen.
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB = W.VB || { actions: {}, aliases: {}, ready: [], views: {} };
  VB.actions = VB.actions || {};

  var WAIT_MS = 6000;

  /* view id -> the name the operator hears, and the phrases he would say.
     The view ids are exactly the ones switchView() (inspection.html 8970) knows;
     the buttons are #topbar button.top-tab[data-view="..."] (5285..5303), home
     being the eye in #topbar .brand (5281). */
  var TABS = [
    { view: 'home',         studio: 'Home',                spoken: ['home'] },
    { view: 'inspections',  studio: 'the Library',         spoken: ['library'] },
    { view: 'videos',       studio: 'Video Studio',        spoken: ['video studio', 'videos'] },
    { view: 'mesh',         studio: 'Mesh',                spoken: ['mesh'] },
    { view: 'pictures',     studio: 'Picture Studio',      spoken: ['picture studio', 'pictures'] },
    { view: 'charstudio',   studio: 'Character Studio',    spoken: ['character studio'] },
    { view: 'creatures',    studio: 'Creature Studio',     spoken: ['creature studio', 'creatures'] },
    { view: 'movement',     studio: 'Movement Studio',     spoken: ['movement studio'] },
    { view: 'voices1',      studio: 'Voice Studio',        spoken: ['voice studio', 'voices'] },
    { view: 'musicstudio',  studio: 'Music Studio',        spoken: ['music studio'] },
    { view: 'sfx',          studio: 'Sfx Studio',          spoken: ['sfx studio', 'sound effects'] },
    { view: 'vfx',          studio: 'VFX Studio',          spoken: ['vfx studio', 'effects'] },
    { view: 'music',        studio: 'Melody Studio',       spoken: ['melody studio', 'melody'] },
    { view: 'architecture', studio: 'Architecture Studio', spoken: ['architecture studio', 'architecture'] },
    { view: 'settings',     studio: 'Settings',            spoken: ['settings'] }
  ];

  /* "video studio" -> "video studio", "go to video studio", "open video studio". */
  function phrases(spoken) {
    var out = [];
    spoken.forEach(function (p) {
      var k = String(p).trim().toLowerCase();
      if (!k) return;
      out.push(k);
      out.push('go to ' + k);
      out.push('open ' + k);
    });
    return out;
  }

  function shown(view) {
    var el = W.document && W.document.getElementById('view-' + view);
    return !!(el && el.style && el.style.display !== 'none');
  }

  // goToView (9165) sets location.hash; switchView (8970) does the display work.
  function go(view) {
    if (typeof W.goToView !== 'function') throw new Error('goToView is not loaded yet');
    W.goToView(view);
    return VB.waitFor(function () { return shown(view); }, WAIT_MS);
  }
  VB.go = go;

  TABS.forEach(function (tab) {
    VB.actions['nav.' + tab.view] = {
      view: tab.view,
      label: 'Go to ' + tab.studio,
      aliases: phrases(tab.spoken),
      args: null,
      el: function () {
        if (!W.document) return null;
        if (tab.view === 'home') return W.document.querySelector('#topbar .brand');
        return W.document.querySelector('#topbar button.top-tab[data-view="' + tab.view + '"]');
      },
      run: function () {
        return go(tab.view).then(function () { return tab.view; });
      },
      say: 'Opening ' + tab.studio
    };
  });

  /* ------------------------------------------------- architecture assistant */

  /* The drawing request goes into the assistant's textarea (#ar-assist-in, built by
     arAssistRender 33561) and is sent with arAssistSend (33641), which reads
     inp.value — exactly what the human Send button does. Nothing is selected
     afterwards: AR.sel is never touched here. */
  VB.actions['architecture.assist'] = {
    view: 'architecture',
    label: 'Ask the Architecture Studio assistant to draw something',
    aliases: [
      'draw', 'draw that', 'ask the architect', 'ask the assistant to draw',
      'architecture assistant', 'tell the architect', 'build that'
    ],
    args: { text: 'string, the drawing request in plain words' },
    el: function () { return W.document ? W.document.getElementById('ar-assist-in') : null; },
    run: function (args) {
      var text = (args && args.text) ? String(args.text).trim() : '';
      if (!text) throw new Error('architecture.assist needs the drawing request in args.text');
      return go('architecture')
        .then(function () {
          // arEnsure (31394) builds the three.js scene once; it returns true when ready.
          return VB.waitFor(function () {
            return W.AR && typeof W.arEnsure === 'function' && W.arEnsure();
          }, WAIT_MS);
        })
        .then(function () {
          if (typeof W.arAssistRender !== 'function') throw new Error('arAssistRender is not loaded yet');
          W.AR.assist.open = true;
          W.arAssistRender();
          return VB.waitFor(function () { return W.document.getElementById('ar-assist-in'); }, WAIT_MS);
        })
        .then(function (inp) {
          if (typeof W.arAssistSend !== 'function') throw new Error('arAssistSend is not loaded yet');
          inp.value = text;
          W.arAssistSend();
          return 'sent to the architecture assistant';
        });
    },
    say: 'Drawing that now'
  };

  /* arUndo (31382) has no button of its own — it is Ctrl+Z (33276) — so el() is null. */
  VB.actions['architecture.undo'] = {
    view: 'architecture',
    label: 'Undo the last change in Architecture Studio',
    aliases: [
      'undo', 'undo that', 'undo the last change', 'architecture undo', 'take that back'
    ],
    args: null,
    el: function () { return null; },
    run: function () {
      return go('architecture').then(function () {
        if (typeof W.arUndo !== 'function') throw new Error('arUndo is not loaded yet');
        W.arUndo();
        return 'undone';
      });
    },
    say: 'Undone'
  };

  if (typeof VB.reindex === 'function') VB.reindex();
})();
