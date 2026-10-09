// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/31_mesh_lib_settings.js — Mesh tab + Library tab + Settings tab.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script (inspection.html
 * 6916..34826), so NOTHING here may touch the DOM or a studio global at top
 * level — every lookup happens inside el()/run().
 *
 * Every run() calls the exact function the human click calls:
 *   Mesh viewer bar      inspection.html HTML 5336-5357, JS 9519-9566, 9745-9778
 *   Mesh board + jobs    inspection.html JS 9173-9452 (meshRun/meshDrawer/loadMesh)
 *   Library board        inspection.html HTML 5363-5368, JS 7295-7757, 9096-9110
 *   Settings board       inspection.html HTML 6574-6582, JS 9044-9086
 *
 * Deliberately NOT registered: meshRun('reissue', …) — its handler opens a
 * confirm() dialog (inspection.html 9338).
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB = W.VB || {};
  VB.actions = VB.actions || {};

  /* ------------------------------------------------------------- helpers */

  function doc() {
    if (!W.document) throw new Error('no document on this page');
    return W.document;
  }

  function byId(id) {
    try { return doc().getElementById(id); } catch (e) { return null; }
  }

  function qs(sel) {
    try { return doc().querySelector(sel); } catch (e) { return null; }
  }

  function qsa(sel) {
    try { return Array.prototype.slice.call(doc().querySelectorAll(sel)); } catch (e) { return []; }
  }

  /** The studio function a click would call, or a readable error. */
  function studio(name) {
    var fn = W[name];
    if (typeof fn !== 'function') throw new Error(name + '() is not on this page');
    return fn;
  }

  /** switchView() sets an explicit display on every #view-* div. */
  function viewOpen(view) {
    var host = byId('view-' + view);
    return !!(host && host.style.display !== 'none');
  }

  /**
   * Open `view` if it is not on screen (the tabs' own goToView, which is what
   * the top-bar buttons call) and wait for `probe` to return an element.
   */
  function ensureView(view, probe) {
    if (!viewOpen(view)) studio('goToView')(view);
    var fn = probe || function () { return viewOpen(view) ? byId('view-' + view) : null; };
    return VB.waitFor(fn, 5000);
  }

  function num(v, fallback) {
    var n = Number(v);
    return isFinite(n) ? n : fallback;
  }

  function text(v) {
    return String(v === undefined || v === null ? '' : v).trim();
  }

  function norm(v) {
    return text(v).toLowerCase().replace(/[\s_-]+/g, ' ');
  }

  /* ====================================================================== */
  /* Mesh — viewer top bar (HTML 5336-5347, JS 9519-9566)                    */
  /* ====================================================================== */

  /** The lightbox is display:flex while a card is open (mvIsOpen, JS 9520). */
  function viewerOpen() {
    var el = byId('mesh-viewer');
    return !!(el && el.style.display === 'flex');
  }

  function needViewer() {
    if (!viewerOpen()) throw new Error('no mesh card is open — say "open mesh <name>" first');
  }

  function meshSeq() {
    var seq = W.MESH_SEQ;
    return Array.isArray(seq) ? seq : [];
  }

  /** Index into MESH_SEQ for a spoken skeleton/prop name. */
  function meshIndex(name) {
    var want = norm(name);
    if (!want) throw new Error('which mesh? say a skeleton or prop name');
    var seq = meshSeq();
    if (!seq.length) throw new Error('the mesh board has not loaded yet');
    var exact = -1, part = -1;
    for (var i = 0; i < seq.length; i++) {
      var have = norm((seq[i] || {}).name);
      if (have === want) { exact = i; break; }
      if (part < 0 && have.indexOf(want) >= 0) part = i;
    }
    var hit = exact >= 0 ? exact : part;
    if (hit < 0) throw new Error('no mesh called "' + text(name) + '" on the board');
    return hit;
  }

  VB.actions['mesh.open'] = {
    view: 'mesh',
    label: 'Open a mesh card in the viewer',
    aliases: ['open mesh', 'show mesh', 'open skeleton', 'show me the mesh'],
    args: { name: 'string, the skeleton or prop name on the board' },
    el: function () { return byId('mesh-board'); },
    run: function (args) {
      return ensureView('mesh', function () { return meshSeq().length ? byId('mesh-board') : null; })
        .then(function () {
          var i = meshIndex(args && args.name);
          studio('mvOpen')(i);
          return meshSeq()[i].name;
        });
    },
    say: 'Opening that mesh in the viewer.'
  };

  VB.actions['mesh.close'] = {
    view: 'mesh',
    label: 'Close the mesh viewer',
    aliases: ['close the mesh viewer', 'close the viewer', 'close the mesh'],
    args: null,
    el: function () { return qs('#mesh-viewer .mv-close'); },
    run: function () { needViewer(); studio('mvClose')(); return 'closed'; },
    say: 'Viewer closed.'
  };

  VB.actions['mesh.next'] = {
    view: 'mesh',
    label: 'Next skeleton in the viewer',
    aliases: ['next skeleton', 'next mesh', 'next body'],
    args: null,
    el: function () { return qsa('#mesh-viewer .mv-arrow')[1] || null; },
    run: function () { needViewer(); studio('mvNav')(1); return 'next'; },
    say: 'Next skeleton.'
  };

  VB.actions['mesh.previous'] = {
    view: 'mesh',
    label: 'Previous skeleton in the viewer',
    aliases: ['previous skeleton', 'previous mesh', 'go back a skeleton'],
    args: null,
    el: function () { return qsa('#mesh-viewer .mv-arrow')[0] || null; },
    run: function () { needViewer(); studio('mvNav')(-1); return 'previous'; },
    say: 'Previous skeleton.'
  };

  VB.actions['mesh.renders'] = {
    view: 'mesh',
    label: 'Show the rendered views (2D)',
    aliases: ['renders', 'show the renders', 'two d', 'flat renders'],
    args: null,
    el: function () { return byId('mv-mode-2d'); },
    run: function () { needViewer(); studio('mvSetMode')('2d'); return '2d'; },
    say: 'Showing the renders.'
  };

  VB.actions['mesh.orbit'] = {
    view: 'mesh',
    label: 'Switch to the 3D orbit',
    aliases: ['three d orbit', 'orbit', 'show the 3d mesh', 'rotate it'],
    args: null,
    el: function () { return byId('mv-mode-3d'); },
    run: function () { needViewer(); studio('mvSetMode')('3d'); return '3d'; },
    say: 'Switching to 3D orbit.'
  };

  VB.actions['mesh.grid'] = {
    view: 'mesh',
    label: 'Toggle the quad grid (wireframe)',
    aliases: ['toggle the grid', 'grid', 'wireframe', 'show the wires'],
    args: null,
    el: function () { return byId('mv-wirebtn'); },
    run: function () {
      needViewer();
      studio('mvToggleWire')();
      var MV = W.MV || {};
      return 'grid: ' + (MV.wire ? 'on' : 'off');
    },
    say: 'Grid toggled.'
  };

  VB.actions['mesh.anthro'] = {
    view: 'mesh',
    label: 'Toggle the anthropometric report',
    aliases: ['anthro', 'anthropometric report', 'show the gate report', 'toggle anthro'],
    args: null,
    el: function () { return byId('mv-anthro-btn'); },
    run: function () {
      needViewer();
      studio('mvToggleAnthro')();
      var MV = W.MV || {};
      return MV.anthro ? 'open' : 'closed';
    },
    say: 'Anthro report toggled.'
  };

  /* ---- the view-angle strip under the picture (#mv-views, JS 9773-9778) -- */

  VB.actions['mesh.view'] = {
    view: 'mesh',
    label: 'Pick a view angle by number',
    aliases: ['view angle', 'pick view', 'go to view', 'angle number'],
    args: { value: 'number, 1-based index of the view thumbnail' },
    el: function (args) {
      var i = num(args && args.value, 1) - 1;
      return qsa('#mv-views .vth')[i < 0 ? 0 : i] || byId('mv-views');
    },
    run: function (args) {
      needViewer();
      var n = num(args && args.value, NaN);
      if (!isFinite(n)) throw new Error('which view? say a number');
      var strip = qsa('#mv-views .vth');
      var i = Math.round(n) - 1;
      if (i < 0 || (strip.length && i >= strip.length)) {
        throw new Error('view ' + Math.round(n) + ' is outside 1 to ' + (strip.length || 1));
      }
      studio('mvSetView')(i);
      return 'view ' + (i + 1);
    },
    say: 'Showing that view angle.'
  };

  VB.actions['mesh.view_next'] = {
    view: 'mesh',
    label: 'Next view angle',
    aliases: ['next view', 'next angle', 'turn it'],
    args: null,
    el: function () { return byId('mv-views'); },
    run: function () { needViewer(); studio('mvViewStep')(1); return 'next view'; },
    say: 'Next view angle.'
  };

  VB.actions['mesh.view_previous'] = {
    view: 'mesh',
    label: 'Previous view angle',
    aliases: ['previous view', 'previous angle', 'back one angle'],
    args: null,
    el: function () { return byId('mv-views'); },
    run: function () { needViewer(); studio('mvViewStep')(-1); return 'previous view'; },
    say: 'Previous view angle.'
  };

  /* ====================================================================== */
  /* Mesh — board and the per-card job buttons (JS 9292-9452)                */
  /* ====================================================================== */

  VB.actions['mesh.reload'] = {
    view: 'mesh',
    label: 'Reload the mesh board',
    aliases: ['reload the mesh board', 'refresh the meshes', 'reload the skeletons'],
    args: null,
    el: function () { return byId('mesh-board'); },
    run: function () {
      return ensureView('mesh').then(function () { studio('loadMesh')(); return 'reloaded'; });
    },
    say: 'Mesh board reloaded.'
  };

  VB.actions['mesh.gate'] = {
    view: 'mesh',
    label: 'Run the anthropometric gate on a body',
    aliases: ['run the gate', 'gate this body', 'run the anthro gate'],
    args: { name: 'string, the skeleton name on the board' },
    el: function () { return byId('mesh-board'); },
    run: function (args) {
      return ensureView('mesh', function () { return meshSeq().length ? byId('mesh-board') : null; })
        .then(function () {
          var name = meshSeq()[meshIndex(args && args.name)].name;
          studio('meshRun')('gate', name);
          return 'gate started on ' + name;
        });
    },
    say: 'Running the gate. Receipts open on the right.'
  };

  VB.actions['mesh.dry_run'] = {
    view: 'mesh',
    label: 'Dry-run a reissue (reads only)',
    aliases: ['dry run', 'dry run reissue', 'rehearse the reissue'],
    args: { name: 'string, the skeleton name on the board' },
    el: function () { return byId('mesh-board'); },
    run: function (args) {
      return ensureView('mesh', function () { return meshSeq().length ? byId('mesh-board') : null; })
        .then(function () {
          var name = meshSeq()[meshIndex(args && args.name)].name;
          studio('meshRun')('dry', name);
          return 'dry run started on ' + name;
        });
    },
    say: 'Dry run started. Nothing is written.'
  };

  VB.actions['mesh.receipts_close'] = {
    view: 'mesh',
    label: 'Close the mesh receipts drawer',
    aliases: ['close the receipts', 'close the drawer', 'hide the receipts'],
    args: null,
    el: function () { return qs('#mesh-drawer .md-x'); },
    run: function () { studio('meshDrawerClose')(); return 'closed'; },
    say: 'Receipts closed.'
  };

  /* ====================================================================== */
  /* Library — the category grid (LIB_CATS, JS 7295-7335; libOpenCat 7591)   */
  /* ====================================================================== */

  // key -> spoken forms. The keys and labels are LIB_CATS' own (JS 7295-7335).
  var LIB_CATS = [
    ['characters', 'Characters', ['characters', 'the character library', 'open characters']],
    ['creatures', 'Creatures', ['creatures', 'the creature library', 'open creatures']],
    ['videos', 'Videos', ['videos', 'the video library', 'open videos']],
    ['melodies', 'Melodies', ['melodies', 'the melody library', 'open melodies', 'songs']],
    ['movement', 'Movement', ['movement', 'the movement library', 'open movement']],
    ['vfx', 'VFX', ['v f x', 'the vfx library', 'open vfx', 'effects']],
    ['architecture', 'Architecture', ['architecture', 'the architecture library', 'open architecture']],
    ['mesh', 'Mesh', ['the mesh library', 'mesh library', 'open the mesh library']],
    ['sfx', 'SFX', ['s f x', 'the sound library', 'open sfx', 'sound effects']],
    ['voices', 'Voices', ['voices', 'the voice library', 'open voices']]
  ];

  function openCat(key) {
    // The tiles only exist at level 0, so enter the tab before clicking through.
    return ensureView('inspections', function () { return byId('lib-board-cats'); })
      .then(function () { studio('libOpenCat')(key); return key; });
  }

  LIB_CATS.forEach(function (row) {
    var key = row[0], label = row[1], aliases = row[2];
    VB.actions['inspections.cat_' + key] = {   // one per LIB_CATS tile
      view: 'inspections',
      label: 'Library: ' + label,
      aliases: aliases,
      args: null,
      el: function () { return byId('kcat-' + key); },
      run: function () { return openCat(key); },
      say: 'Opening the ' + label + ' library.'
    };
  });

  VB.actions['inspections.open_library'] = {
    view: 'inspections',
    label: 'Open a library by name',
    aliases: ['open the library', 'open library', 'show me the library'],
    args: { name: 'string, one of characters creatures videos melodies movement vfx architecture mesh sfx voices' },
    el: function (args) {
      var want = norm(args && args.name);
      var hit = null;
      LIB_CATS.forEach(function (row) {
        if (!hit && (norm(row[0]) === want || norm(row[1]) === want)) hit = row[0];
      });
      return hit ? byId('kcat-' + hit) : byId('lib-board-cats');
    },
    run: function (args) {
      var want = norm(args && args.name);
      if (!want) throw new Error('which library? name one of the ten tiles');
      var hit = null;
      LIB_CATS.forEach(function (row) {
        if (!hit && (norm(row[0]) === want || norm(row[1]) === want)) hit = row[0];
      });
      if (!hit) {
        LIB_CATS.forEach(function (row) {
          if (!hit && norm(row[1]).indexOf(want) >= 0) hit = row[0];
        });
      }
      if (!hit) throw new Error('no library called "' + text(args && args.name) + '"');
      return openCat(hit);
    },
    say: 'Opening that library.'
  };

  /* ---- the crumb trail + the 5 s loader (JS 7393-7497, 9096-9110) -------- */

  VB.actions['inspections.top'] = {
    view: 'inspections',
    label: 'Back to the library grid',
    aliases: ['back to the library', 'library grid', 'all the libraries', 'top of the library'],
    args: null,
    el: function () { return qs('#lib-crumbs .cr-link'); },
    run: function () {
      return ensureView('inspections', function () { return byId('lib-board-cats'); })
        .then(function () { studio('libGoCats')(); return 'level 0'; });
    },
    say: 'Back at the library grid.'
  };

  VB.actions['inspections.back'] = {
    view: 'inspections',
    label: 'Back one level in the library',
    aliases: ['back one level', 'go back a level', 'up one level', 'back to the board'],
    args: null,
    el: function () { return byId('lib-crumbs'); },
    run: function () {
      return ensureView('inspections', function () { return byId('lib-crumbs'); })
        .then(function () { studio('libGoItems')(); return 'level 1'; });
    },
    say: 'Back one level.'
  };

  VB.actions['inspections.refresh'] = {
    view: 'inspections',
    label: 'Refresh the library board',
    aliases: ['refresh the library', 'reload the library', 'refresh the board'],
    args: null,
    el: function () { return byId('lib-board'); },
    run: function () {
      return ensureView('inspections', function () { return byId('lib-board'); })
        .then(function () { studio('libRefresh')(); return 'refreshed'; });
    },
    say: 'Library refreshed.'
  };

  /* ---- one character sheet by name (libOpenCharacter, JS 7735) ----------- */

  VB.actions['inspections.open_sheet'] = {
    view: 'inspections',
    label: 'Open a character sheet by name',
    aliases: ['open the sheet', 'open character', 'show me the character', 'open the character sheet'],
    args: { name: 'string, the character name or id as it reads on the card' },
    el: function () { return byId('lib-board'); },
    run: function (args) {
      var want = norm(args && args.name);
      if (!want) throw new Error('which character? say a name');
      return ensureView('inspections', function () {
        var S = W.STATE || {};
        return (S.list && S.list.length) ? byId('lib-board-item') : null;
      }).then(function () {
        var list = (W.STATE || {}).list || [];
        var exact = null, part = null;
        list.forEach(function (x) {
          var nm = norm(x.name), id = norm(x.id);
          if (!exact && (nm === want || id === want)) exact = x;
          if (!part && (nm.indexOf(want) >= 0 || id.indexOf(want) >= 0)) part = x;
        });
        var pick = exact || part;
        if (!pick) throw new Error('no character called "' + text(args && args.name) + '"');
        studio('libOpenCharacter')(pick.id);
        return pick.name || pick.id;
      });
    },
    say: 'Opening that character sheet.'
  };

  /* ====================================================================== */
  /* Settings — the tab board (HTML 6574-6582, JS 9044-9086)                 */
  /* ====================================================================== */

  // STG_TABS' own ids and labels (JS 9044-9059).
  var STG_TABS = [
    ['bakeoff', 'Comparison'],
    ['inspections', 'Library'],
    ['videos', 'Video Studio'],
    ['mesh', 'Mesh'],
    ['pictures', 'Picture Studio'],
    ['charstudio', 'Character Studio'],
    ['creatures', 'Creature Studio'],
    ['movement', 'Movement Studio'],
    ['voices1', 'Voice Studio'],
    ['musicstudio', 'Music Studio'],
    ['sfx', 'Sfx Studio'],
    ['vfx', 'VFX Studio'],
    ['music', 'Melody Studio'],
    ['architecture', 'Architecture Studio']
  ];

  function stgOpen(id) {
    return ensureView('settings', function () { return byId('stg-board'); })
      .then(function () { studio('stgOpen')(id); return id; });
  }

  VB.actions['settings.open_tab'] = {
    view: 'settings',
    label: 'Open one tab\u2019s settings',
    aliases: ['settings for', 'open the settings for', 'show the settings for'],
    args: { name: 'string, the tab label, e.g. "vfx studio" or "library"' },
    el: function () { return byId('stg-board'); },
    run: function (args) {
      var want = norm(args && args.name);
      if (!want) throw new Error('settings for which tab?');
      var hit = null;
      STG_TABS.forEach(function (row) {
        if (!hit && (norm(row[0]) === want || norm(row[1]) === want)) hit = row[0];
      });
      if (!hit) {
        STG_TABS.forEach(function (row) {
          if (!hit && norm(row[1]).indexOf(want) >= 0) hit = row[0];
        });
      }
      if (!hit) throw new Error('no settings tab called "' + text(args && args.name) + '"');
      return stgOpen(hit);
    },
    say: 'Opening those settings.'
  };

  VB.actions['settings.vfx_taxonomy'] = {
    view: 'settings',
    label: 'VFX Studio settings (observable taxonomy)',
    aliases: ['vfx settings', 'the vfx taxonomy', 'observable taxonomy'],
    args: null,
    el: function () { return byId('stg-panel'); },
    run: function () { return stgOpen('vfx'); },
    say: 'Opening the VFX taxonomy.'
  };

  VB.actions['settings.refresh'] = {
    view: 'settings',
    label: 'Redraw the settings board',
    aliases: ['refresh the settings', 'redraw the settings', 'reload the settings'],
    args: null,
    el: function () { return byId('stg-board'); },
    run: function () {
      return ensureView('settings', function () { return byId('stg-board'); })
        .then(function () { studio('stgEnter')(); return 'redrawn'; });
    },
    say: 'Settings board redrawn.'
  };

  /* Notes for the panel / the language model — free-form, per the contract. */
  VB.views = VB.views || {};
  VB.views.mesh = VB.views.mesh || {};
  VB.views.mesh.note = 'Open a card first; the viewer bar (renders / 3D orbit / grid / anthro) '
    + 'only works while a mesh is open. Reissue is deliberately not voice-operable.';
  VB.views.inspections = VB.views.inspections || {};
  VB.views.inspections.note = 'Three levels: the ten library tiles, that library\u2019s board, then one item.';
  VB.views.settings = VB.views.settings || {};
  VB.views.settings.note = 'One card per top tab; only VFX Studio has real settings today.';
})();
