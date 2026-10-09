// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* voice_ext/30_architecture.js — Architecture Studio voice actions.
 *
 * Loaded from /voice_ext/bundle.js BEFORE the studio script (inspection.html
 * line 6929), so this file may only REGISTER at top level. Every reference to a
 * studio global (goToView, arEnsure, arTool, arWalkEnter…) happens inside run()
 * or el(), never here.
 *
 * The dock is data-driven: AR_TOOLS (inspection.html 29894-30645) is the whole
 * option surface, 232 icons of which 93 are wired — an item carrying `stub:1`
 * is a drawn placeholder and is NOT registered. arTool(id) (31941) is the click
 * entry for every one of them: it dispatches an extension tool (AR_EXT.tools),
 * a one-shot ACTION from its own `acts` table, or falls through to arToolApply
 * (32012) for a drawing MODE. So one run() shape covers the whole table.
 *
 * Not registered, on purpose:
 *   · stubs (they only toast "placeholder")
 *   · anything that stops to ask: v_fov/arFov 32172, l_time/arSunTime 32231,
 *     pr_size/arSnapSize 32273, o_rename/arRenameSel 32304, s_byname 32331,
 *     array/arArray 32600, f_new/arNew 33166 (confirm), f_save + f_saveas
 *     (arSave 33204 prompts for a name), f_jsonin/arImportJson 32488 (confirm)
 *   · destructive: del (arDelete), e_cut (arClipCopy(true) removes the objects)
 *   · anything that SELECTS objects — s_all, s_invert, s_same_mat, s_same_kind
 *     (standing rule). s_none only clears the selection, so it stays.
 *   · c_assist — 10_nav.js owns architecture.assist.
 */
(function () {
  'use strict';

  var W = (typeof window !== 'undefined') ? window : globalThis;
  var VB = W.VB = W.VB || {};
  VB.actions = VB.actions || {};
  VB.views = VB.views || {};

  var VIEW = 'architecture';

  VB.views[VIEW] = {
    enter: 'goToView("architecture") then arEnsure()',
    dock: '#ar-tools .ar-tool[data-tool=ID], #ar-dock .ar-tool[data-tool=ID]',
    note: 'tools come from AR_TOOLS; every click goes through arTool(id)'
  };

  /* The rail and the dock render the same ids from arToolHtml (32040):
     <div class="ar-tool" data-tool="<id>">. Either bar may be collapsed, so
     take whichever one is in the document. */
  function dock(id) {
    return document.querySelector(
      '#ar-tools .ar-tool[data-tool="' + id + '"], #ar-dock .ar-tool[data-tool="' + id + '"]'
    );
  }

  function stage() {
    var v = document.getElementById('view-architecture');
    return (v && v.style.display === 'flex') ? v : null;
  }

  /* arEnter() (inspection.html 33315) runs on tab enter; every entry point in
     the studio itself guards with arEnsure() (31395), which builds the WebGL
     viewport once. So: open the tab, wait for the stage, then arEnsure(). */
  function open() {
    if (stage()) return Promise.resolve(true);
    if (typeof W.goToView !== 'function') return Promise.reject(new Error('goToView is not loaded'));
    W.goToView(VIEW);
    return VB.waitFor(function () { return stage() && document.getElementById('ar-stage'); }, 6000);
  }

  function ready() {
    return open().then(function () {
      if (typeof W.arEnsure !== 'function') throw new Error('Architecture Studio is not loaded');
      if (!W.arEnsure()) throw new Error('Architecture Studio could not start its viewport');
      return true;
    });
  }

  function press(id) {
    return ready().then(function () {
      if (typeof W.arTool !== 'function') throw new Error('arTool is not loaded');
      W.arTool(id);
      return true;
    });
  }

  function reg(name, spec) { VB.actions[VIEW + '.' + name] = spec; }

  /* rows are [action name, AR_TOOLS id, label, aliases, say] */
  function regTools(rows) {
    rows.forEach(function (r) {
      var id = r[1];
      reg(r[0], {
        view: VIEW,
        label: r[2],
        aliases: r[3],
        args: null,
        el: function () { return dock(id); },
        run: function () { return press(id); },
        say: r[4]
      });
    });
  }

  /* ── side bar · Navigate (AR_TOOLS 29895-29911) ─────────────────────── */
  regTools([
    ['select', 'select', 'Select tool', ['select tool', 'pick tool', 'arm select'], 'Select tool armed.'],
    ['orbit', 'orbit', 'Orbit tool', ['orbit', 'orbit tool', 'turn the model'], 'Orbit tool armed.'],
    ['pan', 'pan', 'Pan tool', ['pan', 'pan tool', 'slide the view'], 'Pan tool armed.'],
    ['walk', 'walk', 'Walk mode', ['walk', 'walk mode', 'walk through'], 'Walk mode toggled.'],
    ['zoom.fit', 'zoomfit', 'Zoom to fit', ['fit', 'zoom to fit', 'frame everything'], 'Framed the whole drawing.']
  ]);

  /* ── side bar · Draw (AR_TOOLS 29912-29949) ─────────────────────────── */
  regTools([
    ['draw.wall', 'wall', 'Wall tool', ['wall', 'wall tool', 'draw a wall'], 'Wall tool armed.'],
    ['draw.room', 'room', 'Room tool', ['room', 'room tool', 'draw a room'], 'Room tool armed.'],
    ['draw.slab', 'slab', 'Slab tool', ['slab', 'slab tool', 'draw a floor'], 'Slab tool armed.'],
    ['draw.roof', 'roof', 'Roof tool', ['roof', 'roof tool', 'draw a roof'], 'Roof tool armed.'],
    ['draw.column', 'column', 'Column tool', ['column', 'column tool', 'place a column'], 'Column tool armed.'],
    ['draw.beam', 'beam', 'Beam tool', ['beam', 'beam tool', 'draw a beam'], 'Beam tool armed.'],
    ['draw.stair', 'stair', 'Stair tool', ['stair', 'stairs', 'stair tool'], 'Stair tool armed.'],
    ['draw.line', 'line', 'Guide line tool', ['line', 'guide line', 'line tool'], 'Guide line tool armed.'],
    ['draw.circle', 'circle', 'Guide circle tool', ['circle', 'guide circle', 'circle tool'], 'Guide circle tool armed.']
  ]);

  /* ── side bar · Modify (AR_TOOLS 29950-29978) ───────────────────────── */
  regTools([
    ['move', 'move', 'Move tool', ['move', 'move tool', 'drag the selection'], 'Move tool armed.'],
    ['rotate', 'rotate', 'Rotate tool', ['rotate', 'rotate tool', 'turn the selection'], 'Rotate tool armed.'],
    ['scale', 'scale', 'Scale tool', ['scale', 'scale tool', 'resize the selection'], 'Scale tool armed.'],
    ['pushpull', 'pushpull', 'Push pull tool', ['push pull', 'push and pull', 'change the height'], 'Push pull tool armed.'],
    ['mirror', 'mirror', 'Mirror selection', ['mirror', 'mirror it', 'flip the selection'], 'Mirrored the selection.']
  ]);

  /* ── side bar · Solids (AR_TOOLS 29979-29995) ───────────────────────── */
  regTools([
    ['group', 'group', 'Group selection', ['group', 'group them', 'bind the selection'], 'Grouped the selection.'],
    ['ungroup', 'ungroup', 'Ungroup selection', ['ungroup', 'release the group', 'break the group'], 'Released the group.']
  ]);

  /* ── side bar · Measure (AR_TOOLS 29996-30012) ──────────────────────── */
  regTools([
    ['measure', 'measure', 'Tape measure', ['tape', 'tape measure', 'measure'], 'Tape measure armed.'],
    ['section', 'section', 'Section plane', ['section', 'section plane', 'slice the model'], 'Section plane toggled.']
  ]);

  /* ── side bar · Paint (AR_TOOLS 30013-30020) ────────────────────────── */
  regTools([
    ['paint', 'paint', 'Paint tool', ['paint', 'paint tool', 'apply the material'], 'Paint tool armed.'],
    ['sample', 'eyedrop', 'Sample material', ['sample', 'eyedropper', 'pick up a material'], 'Material sampler armed.']
  ]);

  /* ── dock · View (AR_TOOLS 30034-30089) — arView 32631, arZoomSel 32186,
        arLookAt 32181, arCamPrev/Next 32157, arCamStore/Recall 32167 ───── */
  regTools([
    ['view.top', 'v_top', 'Top view', ['top view', 'look down', 'plan view'], 'Top view.'],
    ['view.front', 'v_front', 'Front view', ['front view', 'front elevation'], 'Front view.'],
    ['view.right', 'v_right', 'Right view', ['right view', 'right elevation'], 'Right view.'],
    ['view.iso', 'v_iso', 'Isometric view', ['iso', 'iso view', 'three quarter view'], 'Isometric view.'],
    ['view.back', 'v_back', 'Back view', ['back view', 'rear view', 'back elevation'], 'Back view.'],
    ['view.left', 'v_left', 'Left view', ['left view', 'left elevation'], 'Left view.'],
    ['view.bottom', 'v_bottom', 'Bottom view', ['bottom view', 'underside', 'look up'], 'Bottom view.'],
    ['view.ortho', 't_ortho', 'Orthographic camera', ['ortho', 'orthographic', 'parallel projection'], 'Camera projection switched.'],
    ['zoom.selection', 'v_selfit', 'Zoom to selection', ['zoom selection', 'frame the selection', 'zoom to what is selected'], 'Framed the selection.'],
    ['view.centre', 'v_lookat', 'Centre on selection', ['centre', 'center on it', 'centre the pivot'], 'Pivot centred on the selection.'],
    ['view.previous', 'v_prev', 'Previous camera', ['previous camera', 'back view step', 'last camera'], 'Back to the previous camera.'],
    ['view.next', 'v_next', 'Next camera', ['next camera', 'forward camera', 'forward view step'], 'Forward to the next camera.'],
    ['view.store', 'v_save', 'Store camera', ['store view', 'store the camera', 'bookmark this view'], 'Camera stored.'],
    ['view.recall', 'v_go', 'Recall camera', ['recall view', 'go to stored view', 'recall the camera'], 'Back at the stored camera.']
  ]);

  /* ── dock · Display (AR_TOOLS 30090-30148) — arGridToggle 32219,
        arAxesToggle 32220, arSkyCycle 32204, arFogToggle 32213,
        arHudToggle 32221, arCellsToggle ──────────────────────────────── */
  regTools([
    ['display.xray', 't_wire', 'X-ray view', ['x ray', 'xray', 'wireframe'], 'X-ray view toggled.'],
    ['display.grid', 'd_grid', 'Ground grid', ['grid', 'ground grid', 'show the grid'], 'Ground grid toggled.'],
    ['display.cells', 'd_cells', 'Cell labels', ['cell labels', 'grid labels', 'name the squares'], 'Cell labels toggled.'],
    ['display.axes', 'd_axes', 'Origin axes', ['axes', 'origin axes', 'show the tripod'], 'Origin axes toggled.'],
    ['display.sky', 'd_sky', 'Cycle the sky', ['sky', 'change the sky', 'cycle the background'], 'Background cycled.'],
    ['display.fog', 'd_fog', 'Depth fog', ['fog', 'depth fog', 'distance haze'], 'Depth fog toggled.'],
    ['display.readout', 'd_hud', 'Readout', ['readout', 'hud', 'show the readout'], 'Readout toggled.']
  ]);

  /* ── dock · Light (AR_TOOLS 30149-30189) — arShadowRes 32249,
        arAmbCycle 32257, arExpoCycle 32264 ───────────────────────────── */
  regTools([
    ['light.shadows', 't_sun', 'Sun shadows', ['shadows', 'sun shadows', 'cast shadows'], 'Shadows toggled.'],
    ['light.softness', 'l_soft', 'Shadow softness', ['shadow softness', 'softer shadows', 'shadow quality'], 'Shadow softness stepped.'],
    ['light.ambient', 'l_amb', 'Ambient light', ['ambient', 'ambient light', 'fill light'], 'Ambient light stepped.'],
    ['light.exposure', 'l_expo', 'Exposure', ['exposure', 'brightness', 'change the exposure'], 'Exposure stepped.']
  ]);

  /* ── dock · Precision (AR_TOOLS 30225-30277) — arLevelStep 32279,
        arLevelZero 32284 ─────────────────────────────────────────────── */
  regTools([
    ['snap.grid', 't_snap', 'Grid snap', ['snap', 'grid snap', 'snap to grid'], 'Grid snap toggled.'],
    ['level.up', 'pr_up', 'Level up', ['level up', 'storey up', 'one floor up'], 'Drawing plane one level up.'],
    ['level.down', 'pr_dn', 'Level down', ['level down', 'storey down', 'one floor down'], 'Drawing plane one level down.'],
    ['level.ground', 'pr_zero', 'Ground level', ['ground level', 'back to the ground', 'level zero'], 'Drawing plane back on the ground.']
  ]);

  /* ── dock · Organise (AR_TOOLS 30278-30321) — arIsolate 32287,
        arLockSel 32295, arUnlockAll 32300 ────────────────────────────── */
  regTools([
    ['isolate', 'o_isolate', 'Isolate selection', ['isolate', 'isolate the selection', 'hide the rest'], 'Selection isolated.'],
    ['lock', 'o_lock', 'Lock selection', ['lock', 'lock the selection', 'lock these'], 'Selection locked.'],
    ['unlock', 'o_unlock', 'Unlock everything', ['unlock', 'unlock all', 'unlock everything'], 'Everything unlocked.']
  ]);

  /* ── dock · Select (AR_TOOLS 30322-30344) — only the one that CLEARS the
        selection: nothing here ever selects objects ──────────────────── */
  regTools([
    ['select.none', 's_none', 'Clear the selection', ['deselect', 'select none', 'clear the selection'], 'Selection cleared.']
  ]);

  /* ── dock · Edit (AR_TOOLS 30345-30388) — arUndo 31383, arRedo 31388,
        arClipCopy 32342, arClipPaste 32351, arDuplicate 32564,
        arHide 32573, arShowAll 32578 ─────────────────────────────────── */
  regTools([
    ['undo', 'undo', 'Undo', ['undo', 'undo that', 'take that back'], 'Undone.'],
    ['redo', 'redo', 'Redo', ['redo', 'redo that', 'put it back'], 'Redone.'],
    ['copy', 'e_copy', 'Copy selection', ['copy', 'copy it', 'copy the selection'], 'Selection copied.'],
    ['paste', 'e_paste', 'Paste', ['paste', 'paste it', 'paste the clipboard'], 'Pasted.'],
    ['paste.inplace', 'e_pastep', 'Paste in place', ['paste in place', 'paste here', 'paste where it was'], 'Pasted in place.'],
    ['duplicate', 'dupe', 'Duplicate selection', ['duplicate', 'duplicate it', 'copy in place'], 'Selection duplicated.'],
    ['hide', 'hide', 'Hide selection', ['hide', 'hide it', 'hide the selection'], 'Selection hidden.'],
    ['showall', 'showall', 'Show everything', ['show all', 'show everything', 'unhide everything'], 'Everything is visible again.']
  ]);

  /* ── dock · Quantities (AR_TOOLS 30389-30420) — arStats 32379,
        arArea 32409, arBom 32425 ─────────────────────────────────────── */
  regTools([
    ['stats', 'q_stats', 'Statistics', ['statistics', 'stats', 'drawing statistics'], 'Statistics sheet open.'],
    ['area', 'q_area', 'Floor area', ['floor area', 'area', 'how much floor area'], 'Floor area sheet open.'],
    ['bom', 'q_bom', 'Bill of materials', ['bill of materials', 'materials list', 'bom'], 'Bill of materials open.']
  ]);

  /* ── dock · File (AR_TOOLS 30532-30596) — arExportJson 32482,
        arExportObj 33223, arBlenderSend, arSnapshotPng 33250.
        The ones that prompt (new, save, save as, import) are left out ── */
  regTools([
    ['export.json', 'f_json', 'Export JSON', ['export json', 'download the json', 'save the json'], 'Drawing exported as JSON.'],
    ['export.obj', 'f_obj', 'Export OBJ', ['export obj', 'download the obj', 'wavefront export'], 'Drawing exported as OBJ.'],
    ['export.blender', 'f_blend', 'Send to Blender', ['to blender', 'send to blender', 'open in blender'], 'Sent to Blender.'],
    ['snapshot', 'f_shot', 'Snapshot', ['snapshot', 'take a snapshot', 'screenshot the viewport'], 'Snapshot taken.']
  ]);

  /* ── dock · Setup (AR_TOOLS 30620-30644) — arShortcuts 32442,
        arRenderInfo 32456, arResetBars 32475 ─────────────────────────── */
  regTools([
    ['shortcuts', 'p_keys', 'Keyboard shortcuts', ['shortcuts', 'keyboard shortcuts', 'show the keys'], 'Shortcuts sheet open.'],
    ['renderer', 'p_gpu', 'Renderer info', ['renderer', 'renderer info', 'which gpu'], 'Renderer information open.'],
    ['bars.reset', 'p_reset', 'Reset the bars', ['reset the bars', 'reset the tool bars', 'bars back'], 'Tool bars reset.']
  ]);

  /* ── walkthrough (arWalkEnter 32664, arWalkLeave 32713) ──────────────
     The dock icon toggles; these two say which way round it goes. */
  reg('walk.enter', {
    view: VIEW,
    label: 'Enter walk mode',
    aliases: ['enter walk mode', 'start walking', 'walk inside'],
    args: null,
    el: function () { return dock('walk'); },
    run: function () {
      return ready().then(function () {
        if (W.AR && W.AR.walk) return true;
        if (typeof W.arWalkEnter !== 'function') throw new Error('arWalkEnter is not loaded');
        W.arWalkEnter();
        return true;
      });
    },
    say: 'Walking at 1.65 m eye height.'
  });

  reg('walk.leave', {
    view: VIEW,
    label: 'Leave walk mode',
    aliases: ['leave walk mode', 'stop walking', 'exit walk'],
    args: null,
    el: function () { return dock('walk'); },
    run: function () {
      return ready().then(function () {
        if (!(W.AR && W.AR.walk)) return true;
        if (typeof W.arWalkLeave !== 'function') throw new Error('arWalkLeave is not loaded');
        W.arWalkLeave();
        return true;
      });
    },
    say: 'Out of walk mode.'
  });

  /* ── the studio chrome (inspection.html 6523-6561) ───────────────────
     #ar-arrow onclick=arBarsToggle (32103); the Properties panel's own
     minimise button onclick=arPanelMin (33066). */
  reg('bars.toggle', {
    view: VIEW,
    label: 'Hide or show the tool bars',
    aliases: ['toggle the bars', 'hide the tool bars', 'show the tool bars'],
    args: null,
    el: function () { return document.getElementById('ar-arrow'); },
    run: function () {
      return ready().then(function () {
        if (typeof W.arBarsToggle !== 'function') throw new Error('arBarsToggle is not loaded');
        W.arBarsToggle();
        return true;
      });
    },
    say: 'Tool bars toggled.'
  });

  reg('properties.toggle', {
    view: VIEW,
    label: 'Collapse or expand the properties panel',
    aliases: ['toggle properties', 'collapse the properties panel', 'expand the properties panel'],
    args: null,
    el: function () { return document.querySelector('#ar-panel .hd button'); },
    run: function () {
      return ready().then(function () {
        if (typeof W.arPanelMin !== 'function') throw new Error('arPanelMin is not loaded');
        W.arPanelMin();
        return true;
      });
    },
    say: 'Properties panel toggled.'
  });
})();
