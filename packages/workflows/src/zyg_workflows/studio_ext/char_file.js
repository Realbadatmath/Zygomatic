// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ══ Character Studio — the File / Edit / View actions ══════════════════════
   2026-09-18, task 10 of the four-studios wiring tree.

   Ten dock tools were drawn, given an `act:` key and left without a handler:
   Import, Duplicate, Delete, Undo, Copy from, Auto defaults, Batch apply,
   Lock fields, Compare and Sheet grid. This file adds the ten entries to
   CST_ACT and nothing else — it is loaded by /studio_ext/bundle.js AFTER the
   page's own script block, so every global it touches already exists.

   Three rules it keeps, which are the page's rules and not new ones:

   1. A WRITE GOES THROUGH THE ONE WRITER. Every edit this file makes lands via
      cstPost() -> /inspect/api/char/bible/save, or via the server's own
      character_studio.edit(). Nothing here dumps JSON over a bible, so the
      whitelist, the coercion, the lock list and the age invariant apply to a
      batch and to a copy-from exactly as they apply to a single field.
   2. NOTHING DESTRUCTIVE HAPPENS ON THE FIRST CLICK. Import, Delete and Batch
      each open a sheet that names what will change and which character it will
      change, and only the second button does it. Auto defaults never saves at
      all: the server returns the diff and the operator presses Apply.
   3. UNDO IS HONEST ABOUT WHAT IT IS. It is a client-side stack of the values
      this browser saw before each successful save — not a file history. It
      says so in the panel, and it is empty after a reload.
*/

/* ── the extension's own state ────────────────────────────────────────────
   history: [{ts, edits:{path: valueBefore}}], newest last.
   suspend: set while an undo is being written, so the undo does not push
            itself back onto the stack and become un-undoable.
   grid:    what the stage looked like before Sheet grid took it over. */
var CF = { history: [], suspend: false, grid: null, pick: {}, batch: null, cmp: null };

function cfPost(op, body){
  return fetch('/inspect/api/studio/char_file/' + op,
               {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body || {})})
    .then(function(r){ return r.json().then(function(j){ j._code = r.status; return j; }); });
}
/* the library, minus the character standing in the studio */
function cfOthers(){
  return api(withScope('/inspect/api/list')).then(function(d){
    return (d.sheets || []).filter(function(c){ return c.id !== CS.charId; });
  });
}
function cfPortrait(c){
  return (c && c.front_image)
    ? imgUrl(c.id, c.front_image.cat, c.front_image.name, c.front_image.mtime) : '';
}
function cfShow(v){
  return (v === '' || v === null || v === undefined) ? '—' : String(v);
}
/* the non-read-only registry paths, in the server's section order */
function cfEditablePaths(){
  var F = (CST.spec && CST.spec.fields) || {}, secs = (CST.spec && CST.spec.sections) || [];
  return Object.keys(F)
    .filter(function(p){ return F[p].t !== 'ro'; })
    .sort(function(a, b){
      var sa = secs.indexOf(F[a].sec), sb = secs.indexOf(F[b].sec);
      return sa !== sb ? sa - sb : (a < b ? -1 : 1);
    });
}
function cfBusyPanel(id, title){
  cstPanelOpen(id, title, '<div class="todo">asking the server&hellip;</div>');
}
function cfErr(id, title, j){
  cstPanelOpen(id, title, '<div class="cst-warn">'
    + esc(j && (j.error || j.message) ? (j.error || j.message) : ('HTTP ' + ((j && j._code) || '?')))
    + '</div>');
}

/* ── the lock list ────────────────────────────────────────────────────────
   Stored as a JSON list of strings in studio.locked_fields — the same field
   character_studio._locked_paths() parses on the way in, so what this panel
   writes is exactly what the server refuses edits to. */
function cfLocked(){
  var raw = CST.values ? CST.values['studio.locked_fields'] : '';
  if (Array.isArray(raw)) return raw.slice();
  if (typeof raw !== 'string' || !raw.trim()) return [];
  try {
    var p = JSON.parse(raw);
    return Array.isArray(p) ? p.filter(function(x){ return typeof x === 'string'; }) : [];
  } catch (e) { return []; }
}

/* ══ Import ══════════════════════════════════════════════════════════════ */
CST_ACT.import = function(){
  if (!CS.charId) return cstPanelOpen('d_import', 'Import', cstNoChar());
  cstPanelOpen('d_import', 'Import',
    '<div class="cst-hint big">Replaces <b>' + esc(CS.charName || CS.charId) + '</b>’s whole '
    + '<code>character_bible.json</code> with the file you pick. The package’s own '
    + '<code>character_id</code> must name this character — an import restores a character '
    + 'from its own Export, it does not move one bible onto another.</div>'
    + '<div class="cst-field"><input type="file" id="cf-imp" accept="application/json,.json"'
    + ' onchange="cfImportRead()"></div>'
    + '<div class="cst-msg" id="cst-msg"></div>'
    + '<div id="cf-imp-foot"></div>');
};
function cfImportRead(){
  var el = document.getElementById('cf-imp');
  var f = el && el.files && el.files[0];
  if (!f) return;
  var rd = new FileReader();
  rd.onload = function(){
    var pkg;
    try { pkg = JSON.parse(rd.result); }
    catch (e){ return cstMsg('<b>Not JSON.</b> ' + esc(String(e)), 'bad'); }
    if (!pkg || typeof pkg !== 'object' || Array.isArray(pkg))
      return cstMsg('<b>Not a character package.</b> The file has to be the object Export writes.', 'bad');
    CF.pending = pkg;
    var who = String(pkg.character_id || '');
    var mine = (who === CS.charId);
    cstMsg(cstKv('file', f.name) + cstKv('size', cstBytes(f.size))
      + cstKv('character_id in the file', who || '— absent —')
      + cstKv('display_name in the file', pkg.display_name || '—')
      + cstKv('top-level keys', Object.keys(pkg).length)
      + (mine ? '' : '<div class="cst-warn">That is not this character. The server will refuse it.</div>'),
      mine ? 'ok' : 'warn');
    document.getElementById('cf-imp-foot').innerHTML = mine
      ? '<div class="cst-foot"><button class="go" onclick="cfImportGo()">Overwrite this bible</button></div>'
        + '<div class="cst-hint">The file it overwrites is copied to <code>…json.bak-import-&lt;ts&gt;</code> first.</div>'
      : '';
  };
  rd.onerror = function(){ cstMsg('<b>Could not read the file.</b>', 'bad'); };
  rd.readAsText(f);
}
function cfImportGo(){
  if (!CF.pending) return;
  cstMsg('Importing&hellip;', '');
  cfPost('import', {id: CS.charId, package: CF.pending}).then(function(j){
    if (!j.ok) return cstMsg('<b>Refused.</b> ' + esc(j.error || ('HTTP ' + j._code)), 'bad');
    CF.pending = null;
    document.getElementById('cf-imp-foot').innerHTML = '';
    cstLoad().then(function(){
      cstMsg('<b>Imported.</b> ' + j.changed.length + ' registered field(s) differ from what was there.'
        + (j.changed.length ? '<br>' + j.changed.map(esc).join('<br>') : '')
        + '<br><span class="dim">backup: ' + esc(j.backup || 'none — there was no bible') + '</span>', 'ok');
    });
  }).catch(function(e){ cstMsg('<b>Could not reach the server.</b> ' + esc(String(e)), 'bad'); });
}

/* ══ Duplicate ═══════════════════════════════════════════════════════════ */
CST_ACT.duplicate = function(){
  if (!CS.charId) return cstPanelOpen('d_duplicate', 'Duplicate', cstNoChar());
  cstPanelOpen('d_duplicate', 'Duplicate',
    '<div class="cst-hint big">Forks this bible into a new 12-hex id. The copy keeps every '
    + 'descriptor and loses the things that belong to the original: its <b>LoRA paths are '
    + 'cleared</b> and its trigger token is suffixed, so the fork cannot quietly render as '
    + 'the character it came from. No images are copied — only the bible.</div>'
    + cstKv('copying', (CS.charName || '') + '  ·  ' + CS.charId)
    + '<div class="cst-field"><input type="text" id="cf-dupname" value="'
    + esc((CS.charName || CS.charId) + ' (copy)') + '"></div>'
    + '<div class="cst-foot"><button class="go" onclick="cfDupGo()">Make the copy</button></div>'
    + '<div class="cst-msg" id="cst-msg"></div>');
};
function cfDupGo(){
  var el = document.getElementById('cf-dupname');
  var name = el ? String(el.value || '').trim() : '';
  if (!name) return cstMsg('A display name is required.', 'warn');
  cstMsg('Writing the copy&hellip;', '');
  cfPost('duplicate', {id: CS.charId, name: name}).then(function(j){
    if (!j.ok) return cstMsg('<b>Refused.</b> ' + esc(j.error || ('HTTP ' + j._code)), 'bad');
    loadList();
    cstMsg('<b>Copied.</b><br>' + cstKv('new id', j.id) + cstKv('display name', j.name)
      + cstKv('file', j.file)
      + '<div class="cst-foot"><button class="go" onclick="cfOpen(\'' + j.id + '\',\''
      + esc(j.name).replace(/'/g, '&#39;') + '\')">Open it</button></div>', 'ok');
  }).catch(function(e){ cstMsg('<b>Could not reach the server.</b> ' + esc(String(e)), 'bad'); });
}
/* load a character by id through the page's own loader. The list is refetched
   rather than read from STATE.list, which is up to 5 s behind a brand-new id. */
function cfOpen(id, name){
  api(withScope('/inspect/api/list')).then(function(d){
    var c = (d.sheets || []).find(function(x){ return x.id === id; }) || {id: id, name: name || id};
    /* 2026-09-19: the address stays the studio's own ('#characterstudio', see
       ROUTE_SLUG in inspection.html) — a bare '#<id>' here relabelled the page
       as a Library sheet, which is where Back/reload then took you. */
    if (typeof routeSet === 'function') routeSet('characterstudio');
    csLoadChar(c);
  }).catch(function(){ csLoadChar({id: id, name: name || id}); });
}

/* ══ Delete ══════════════════════════════════════════════════════════════ */
CST_ACT.delete = function(){
  if (!CS.charId) return cstPanelOpen('d_delete', 'Delete', cstNoChar());
  var d = CST.derived || {};
  cstPanelOpen('d_delete', 'Delete',
    '<div class="cst-warn">This moves the whole character directory into '
    + '<code>&lt;chars&gt;/.deleted/</code>. It drops out of every listing at once. '
    + 'Nothing is erased — the bible, the contact sheet, the tiles and the training sets '
    + 'go with it and an operator can move the folder back by hand.</div>'
    + cstKv('character', CS.charName || '—')
    + cstKv('id', CS.charId)
    + cstKv('directory', d.dir || '—')
    + cstKv('size on disk', d.dir_bytes ? cstBytes(d.dir_bytes) : '—')
    + '<div class="cst-hint big">The trained LoRA weights live outside this directory and are '
    + 'NOT moved. A delete here removes the character from the library, not its weights from the disk.</div>'
    + '<div class="cst-foot"><button class="go" onclick="cfDeleteGo()">Delete '
    + esc(CS.charId) + '</button><button onclick="cstPanelClose()">Keep it</button></div>'
    + '<div class="cst-msg" id="cst-msg"></div>');
};
function cfDeleteGo(){
  var id = CS.charId;
  cstMsg('Deleting&hellip;', '');
  /* the id travels in the QUERY STRING — that is what kanban_server's
     _delete_character reads, and withScope() adds the origin scope the same
     handler checks the character against */
  fetch(withScope('/inspect/api/delete-character?id=' + encodeURIComponent(id)), {method: 'POST'})
    .then(function(r){ return r.json().then(function(j){ j._code = r.status; return j; }); })
    .then(function(j){
      if (!j.ok) return cstMsg('<b>Refused.</b> ' + esc(j.error || ('HTTP ' + j._code)), 'bad');
      CS.charId = ''; CS.charName = ''; CS.loaded = false;
      CST.values = {}; CST.bible = null; CST.derived = null; CST.dirty = {}; CST.loadErr = '';
      CF.history = [];
      var nm = document.getElementById('cs-cname'), sb = document.getElementById('cs-csub');
      if (nm) nm.textContent = 'Base body';
      if (sb) sb.textContent = (typeof CS_BASE_CREDIT === 'string') ? CS_BASE_CREDIT : '';
      cfGridOff();
      cstToolsRender();
      loadList();
      cstPanelOpen('d_delete', 'Delete',
        '<div class="todo"><b>' + esc(id) + ' deleted.</b><br><br>The directory is in '
        + '<code>.deleted/</code>. The studio is empty — use <b>Inject</b> to load another '
        + 'character.</div>');
    })
    .catch(function(e){ cstMsg('<b>Could not reach the server.</b> ' + esc(String(e)), 'bad'); });
}

/* ══ Undo ════════════════════════════════════════════════════════════════
   cstPost is the page's ONE writer, so wrapping it catches every save — a
   single field, a compound tool, Save all, an Apply from the auto-defaults
   diff. The wrapper does not re-implement the request: it reads the values
   before, lets the original run, and waits for CST.busy to drop, which the
   original clears in both its success and its failure handler. Only paths
   that actually moved are recorded. */
var _cfPostOrig = cstPost;
cstPost = function(edits){
  var suspended = CF.suspend; CF.suspend = false;
  var before = {}, paths = Object.keys(edits || {});
  paths.forEach(function(p){ before[p] = CST.values[p]; });
  _cfPostOrig(edits);
  if (suspended || !CST.busy) return;          /* nothing was sent, or it is an undo */
  var t = setInterval(function(){
    if (CST.busy) return;
    clearInterval(t);
    var snap = {};
    paths.forEach(function(p){
      if (CST.values[p] !== before[p]) snap[p] = before[p];
    });
    if (Object.keys(snap).length){
      CF.history.push({ts: Date.now(), id: CS.charId, edits: snap});
      if (CF.history.length > 40) CF.history.shift();
      cstToolsRender();
    }
  }, 120);
  setTimeout(function(){ clearInterval(t); }, 30000);
};

CST_ACT.undo = function(){
  if (!CS.charId) return cstPanelOpen('d_undo', 'Undo', cstNoChar());
  var mine = CF.history.filter(function(h){ return h.id === CS.charId; });
  var last = mine.slice(-10).reverse();
  cstPanelOpen('d_undo', 'Undo',
    '<div class="cst-hint big">The values this browser saw <b>before</b> each save, newest '
    + 'first. It is a session stack, not a file history: a reload empties it, and it knows '
    + 'nothing about a save made in another tab. Stepping back writes the old value through '
    + 'the same save route, so the writer can refuse it like any other edit.</div>'
    + (last.length
        ? last.map(function(h, i){
            var ks = Object.keys(h.edits);
            return '<div class="cst-grp">' + esc(new Date(h.ts).toLocaleTimeString())
              + ' — ' + ks.length + ' field(s)</div>'
              + ks.map(function(k){
                  return cstKv(k, cfShow(CST.values[k]) + '  ←  ' + cfShow(h.edits[k])); }).join('')
              + (i === 0
                  ? '<div class="cst-foot"><button class="go" onclick="cfUndoGo()">Step back</button></div>'
                  : '');
          }).join('')
        : '<div class="todo">Nothing saved in this session yet, so there is nothing to step back through.</div>')
    + '<div class="cst-msg" id="cst-msg"></div>');
};
function cfUndoGo(){
  var idx = -1;
  for (var i = CF.history.length - 1; i >= 0; i--)
    if (CF.history[i].id === CS.charId){ idx = i; break; }
  if (idx < 0) return;
  var step = CF.history.splice(idx, 1)[0];
  CF.suspend = true;
  cstPost(step.edits);
}

/* ══ Copy from ═══════════════════════════════════════════════════════════ */
CST_ACT.copyfrom = function(){
  if (!CS.charId) return cstPanelOpen('d_copy', 'Copy from', cstNoChar());
  if (!CST.spec) return cstPanelOpen('d_copy', 'Copy from',
    '<div class="todo">The field registry has not loaded, so there are no sections to copy.</div>');
  cfBusyPanel('d_copy', 'Copy from');
  cfOthers().then(function(list){
    var F = CST.spec.fields, secs = CST.spec.sections || [];
    var counts = {};
    Object.keys(F).forEach(function(p){
      if (F[p].t === 'ro') return;
      counts[F[p].sec] = (counts[F[p].sec] || 0) + 1;
    });
    cstPanelOpen('d_copy', 'Copy from',
      '<div class="cst-hint big">Reads another character’s bible and <b>stages</b> the chosen '
      + 'sections onto this one. Nothing is written here — the fields land as unsaved edits and '
      + '<b>Save all</b> writes them through the usual whitelist, so you can look at them first.</div>'
      + '<div class="cst-field"><select id="cf-cpfrom">'
      + list.map(function(c){
          return '<option value="' + esc(c.id) + '">' + esc(c.name) + ' — ' + esc(c.id) + '</option>'; }).join('')
      + '</select></div>'
      + '<div class="cst-grp">sections</div>'
      + secs.filter(function(s){ return counts[s]; }).map(function(s){
          return '<label class="cst-toggle"><input type="checkbox" class="cf-cpsec" value="' + esc(s) + '"'
            + (['identity', 'face', 'eyes', 'hair', 'body'].indexOf(s) >= 0 ? '' : '') + '> <span>'
            + esc(s) + '  <span class="dim">(' + counts[s] + ')</span></span></label>'; }).join('')
      + '<div class="cst-foot"><button class="go" onclick="cfCopyGo()">Stage those sections</button></div>'
      + '<div class="cst-msg" id="cst-msg"></div>');
  }).catch(function(e){
    cstPanelOpen('d_copy', 'Copy from', '<div class="cst-warn">' + esc(String(e)) + '</div>');
  });
};
function cfCopyGo(){
  var sel = document.getElementById('cf-cpfrom');
  var from = sel ? sel.value : '';
  var secs = [].slice.call(document.querySelectorAll('.cf-cpsec:checked')).map(function(x){ return x.value; });
  if (!from) return cstMsg('Pick a character to copy from.', 'warn');
  if (!secs.length) return cstMsg('Pick at least one section.', 'warn');
  cstMsg('Reading ' + esc(from) + '&hellip;', '');
  cfPost('other', {id: from}).then(function(j){
    if (!j.ok) return cstMsg('<b>Refused.</b> ' + esc(j.error || ('HTTP ' + j._code)), 'bad');
    var F = CST.spec.fields, staged = [], same = 0;
    Object.keys(F).forEach(function(p){
      if (F[p].t === 'ro' || secs.indexOf(F[p].sec) < 0) return;
      if (!Object.prototype.hasOwnProperty.call(j.values, p)) return;
      if (j.values[p] === CST.values[p]){ same++; return; }
      /* the same assignment cstStageField() makes — that helper reads a DOM
         editor, and there is no editor on screen for a field being copied */
      CST.dirty[p] = j.values[p];
      staged.push(p);
    });
    cstToolsRender();
    cs3dHooksRun('stage');
    cstMsg('<b>Staged ' + staged.length + ' field(s)</b> from ' + esc(j.name) + '. '
      + same + ' already matched.<br>'
      + staged.map(function(p){ return esc(p) + ' → ' + esc(cfShow(j.values[p])); }).join('<br>')
      + (staged.length ? '<div class="cst-foot"><button class="go" onclick="cstSaveAll()">Save all</button>'
                       + '<button onclick="cstRevertAll()">Drop them</button></div>' : ''),
      staged.length ? 'ok' : 'warn');
  }).catch(function(e){ cstMsg('<b>Could not reach the server.</b> ' + esc(String(e)), 'bad'); });
}

/* ══ Auto defaults ═══════════════════════════════════════════════════════ */
CST_ACT.autodefaults = function(){
  if (!CS.charId) return cstPanelOpen('d_defaults', 'Auto defaults', cstNoChar());
  cfBusyPanel('d_defaults', 'Auto defaults');
  cfPost('autodefaults', {id: CS.charId}).then(function(j){
    if (!j.ok) return cfErr('d_defaults', 'Auto defaults', j);
    CF.defaults = j.changed;
    var ks = Object.keys(j.changed);
    cstPanelOpen('d_defaults', 'Auto defaults',
      '<div class="cst-hint big">The generator’s own <code>apply_auto_defaults</code>, run over '
      + 'this bible. <b>Nothing has been saved.</b> Only fields that were EMPTY are offered — the '
      + 'engine resolves every key it is handed, and an auto-default must not be a way to lose a '
      + 'deliberate choice.</div>'
      + (ks.length
          ? '<div class="cst-grp">' + ks.length + ' empty field(s) would be filled</div>'
            + ks.map(function(k){ return cstKv(k, cfShow(j.changed[k][1])); }).join('')
            + (j.skipped && j.skipped.length
                ? '<div class="cst-grp">refused by the field registry</div>'
                  + j.skipped.map(function(s){ return cstKv(s.path, s.why); }).join('')
                : '')
            + '<div class="cst-foot"><button class="go" onclick="cfDefaultsApply()">Apply these '
            + ks.length + '</button><button onclick="cstPanelClose()">Leave them empty</button></div>'
          : '<div class="todo">Nothing to fill — every field the auto-defaults engine covers already '
            + 'holds a value on this character.</div>')
      + '<div class="cst-msg" id="cst-msg"></div>');
  }).catch(function(e){
    cstPanelOpen('d_defaults', 'Auto defaults', '<div class="cst-warn">' + esc(String(e)) + '</div>');
  });
};
function cfDefaultsApply(){
  var c = CF.defaults || {}, e = {};
  Object.keys(c).forEach(function(k){ e[k] = c[k][1]; });
  if (!Object.keys(e).length) return;
  cstPost(e);
}

/* ══ Batch apply ═════════════════════════════════════════════════════════ */
CST_ACT.batch = function(){
  if (!CST.spec) return cstPanelOpen('d_batch', 'Batch apply',
    '<div class="todo">The field registry has not loaded, so there is no field to apply.</div>');
  cfBusyPanel('d_batch', 'Batch apply');
  api(withScope('/inspect/api/list')).then(function(d){
    CF.batch = {list: d.sheets || [], path: CF.batch && CF.batch.path, ids: (CF.batch && CF.batch.ids) || []};
    cfBatchRender();
  }).catch(function(e){
    cstPanelOpen('d_batch', 'Batch apply', '<div class="cst-warn">' + esc(String(e)) + '</div>');
  });
};
function cfBatchRender(){
  var B = CF.batch, F = CST.spec.fields;
  var paths = cfEditablePaths();
  if (!B.path || !F[B.path]) B.path = paths[0];
  var sp = F[B.path];
  cstPanelOpen('d_batch', 'Batch apply',
    '<div class="cst-hint big">One field, written to every character you tick. Each one goes '
    + 'through <code>character_studio.edit</code> on its own, so a locked field, a bad value or '
    + 'the age invariant are reported per character rather than failing the lot.</div>'
    + '<div class="cst-field"><select id="cf-bpath" onchange="cfBatchPath(this.value)">'
    + paths.map(function(p){
        return '<option value="' + esc(p) + '"' + (p === B.path ? ' selected' : '') + '>'
          + esc(F[p].sec + ' · ' + p) + '</option>'; }).join('')
    + '</select></div>'
    + '<div class="cst-path">' + esc(B.path) + '</div>'
    + '<div class="cst-field">' + cstFieldEditor(B.path, sp, 'cst-in-b') + '</div>'
    + (sp.help ? '<div class="cst-hint big">' + esc(sp.help) + '</div>' : '')
    + '<div class="cst-grp">characters <span class="dim">'
    + '<a href="#" onclick="cfBatchAll(1);return false;">all</a> · '
    + '<a href="#" onclick="cfBatchAll(0);return false;">none</a></span></div>'
    + B.list.map(function(c){
        return '<label class="cst-toggle"><input type="checkbox" class="cf-bid" value="' + esc(c.id) + '"'
          + (B.ids.indexOf(c.id) >= 0 ? ' checked' : '') + '> <span>' + esc(c.name)
          + ' <span class="dim">' + esc(c.id) + '</span></span></label>'; }).join('')
    + '<div class="cst-foot"><button class="go" onclick="cfBatchGo()">Apply to the ticked characters</button></div>'
    + '<div class="cst-msg" id="cst-msg"></div>');
}
function cfBatchIds(){
  return [].slice.call(document.querySelectorAll('.cf-bid:checked')).map(function(x){ return x.value; });
}
function cfBatchPath(p){ CF.batch.ids = cfBatchIds(); CF.batch.path = p; cfBatchRender(); }
function cfBatchAll(on){
  [].slice.call(document.querySelectorAll('.cf-bid')).forEach(function(x){ x.checked = !!on; });
}
function cfBatchGo(){
  var B = CF.batch, ids = cfBatchIds();
  if (!ids.length) return cstMsg('Tick at least one character.', 'warn');
  var v = cstReadEditor(B.path, 'cst-in-b');
  if (v === null) return cstMsg('The editor is not on screen.', 'bad');
  B.ids = ids;
  cstMsg('Writing ' + esc(B.path) + ' to ' + ids.length + ' character(s)&hellip;', '');
  cfPost('batch', {path: B.path, value: v, ids: ids}).then(function(j){
    if (!j.ok) return cstMsg('<b>Refused.</b> ' + esc(j.error || ('HTTP ' + j._code)), 'bad');
    var ok = j.results.filter(function(r){ return r.ok; }).length;
    var names = {};
    B.list.forEach(function(c){ names[c.id] = c.name; });
    cstMsg('<b>' + ok + ' of ' + j.results.length + ' written.</b><br>'
      + j.results.map(function(r){
          return cstKv((names[r.id] || r.id), r.ok
            ? ('written' + (Object.keys(r.forced || {}).length
                ? ' — the writer also changed ' + Object.keys(r.forced).join(', ') : ''))
            : ('REFUSED — ' + r.why));
        }).join(''), ok === j.results.length ? 'ok' : 'warn');
    if (ids.indexOf(CS.charId) >= 0) cstLoad();
    loadList();
  }).catch(function(e){ cstMsg('<b>Could not reach the server.</b> ' + esc(String(e)), 'bad'); });
}

/* ══ Lock fields ═════════════════════════════════════════════════════════ */
CST_ACT.lockfields = function(){
  if (!CS.charId) return cstPanelOpen('d_lock', 'Lock fields', cstNoChar());
  if (!CST.spec) return cstPanelOpen('d_lock', 'Lock fields',
    '<div class="todo">The field registry has not loaded, so there is no field list to lock.</div>');
  var F = CST.spec.fields, secs = CST.spec.sections || [], locked = cfLocked();
  var paths = cfEditablePaths().filter(function(p){ return p !== 'studio.locked_fields'; });
  var bySec = {};
  paths.forEach(function(p){ (bySec[F[p].sec] = bySec[F[p].sec] || []).push(p); });
  cstPanelOpen('d_lock', 'Lock fields',
    '<div class="cst-hint big">A locked path is <b>refused by the writer</b>, not merely hidden '
    + 'here — <code>character_studio.edit</code> checks this list before it coerces anything. '
    + 'The lock list itself is never locked: a list that could lock itself would have no way out.</div>'
    + cstKv('locked now', locked.length)
    + '<div class="cst-hint"><a href="#" onclick="cfLockAll(1);return false;">all</a> · '
    + '<a href="#" onclick="cfLockAll(0);return false;">none</a></div>'
    + secs.filter(function(s){ return bySec[s]; }).map(function(s){
        return '<div class="cst-grp">' + esc(s) + '</div>'
          + bySec[s].map(function(p){
              return '<label class="cst-toggle"><input type="checkbox" class="cf-lock" value="' + esc(p) + '"'
                + (locked.indexOf(p) >= 0 ? ' checked' : '') + '> <span>' + esc(p) + '</span></label>';
            }).join('');
      }).join('')
    + '<div class="cst-foot"><button class="go" onclick="cfLockGo()">Save the lock list</button></div>'
    + '<div class="cst-msg" id="cst-msg"></div>');
};
function cfLockAll(on){
  [].slice.call(document.querySelectorAll('.cf-lock')).forEach(function(x){ x.checked = !!on; });
}
function cfLockGo(){
  var list = [].slice.call(document.querySelectorAll('.cf-lock:checked')).map(function(x){ return x.value; });
  cstPost({'studio.locked_fields': JSON.stringify(list)});
}
/* a locked tool says so in its tooltip. cstToolHtml builds the whole tile, so
   the marker is appended to the title rather than re-implementing the tile. */
var _cfToolHtml = cstToolHtml;
cstToolHtml = function(t){
  var html = _cfToolHtml(t);
  if (!CS.loaded) return html;
  var locked = cfLocked();
  if (!locked.length) return html;
  var mine = (t.f ? [t.f] : (t.fs || [])).filter(function(p){ return locked.indexOf(p) >= 0; });
  if (!mine.length) return html;
  return html.replace(/ title="([^"]*)"/,
    ' title="$1 [locked: ' + esc(mine.join(', ')) + ']" data-cflock="1"');
};

/* ══ Compare ═════════════════════════════════════════════════════════════ */
/* Which sections the two columns show. The brief's "identity / appearance /
   wardrobe" is three WORDS for what the registry splits into seven sections —
   these are the appearance-and-dress half of CST.spec.sections, and nothing
   else, so the columns stay readable. */
var CF_CMP_SECS = ['identity', 'face', 'eyes', 'hair', 'body', 'wardrobe', 'accessories'];
CST_ACT.compare = function(){
  if (!CS.charId) return cstPanelOpen('d_compare', 'Compare', cstNoChar());
  cfBusyPanel('d_compare', 'Compare');
  cfOthers().then(function(list){
    CF.cmp = {list: list};
    if (!list.length) return cstPanelOpen('d_compare', 'Compare',
      '<div class="todo">There is no second character in this library to compare against.</div>');
    cstPanelOpen('d_compare', 'Compare',
      '<div class="cst-hint big">Two bibles side by side — the appearance and dress sections. '
      + 'A highlighted row is one the two characters disagree about.</div>'
      + '<div class="cst-field"><select id="cf-cmpid" onchange="cfCompareGo()">'
      + '<option value="">— pick a character —</option>'
      + list.map(function(c){
          return '<option value="' + esc(c.id) + '">' + esc(c.name) + ' — ' + esc(c.id) + '</option>'; }).join('')
      + '</select></div><div id="cf-cmpbody"></div>');
  }).catch(function(e){
    cstPanelOpen('d_compare', 'Compare', '<div class="cst-warn">' + esc(String(e)) + '</div>');
  });
};
function cfCompareGo(){
  var sel = document.getElementById('cf-cmpid'), body = document.getElementById('cf-cmpbody');
  if (!sel || !body) return;
  var id = sel.value;
  if (!id){ body.innerHTML = ''; return; }
  body.innerHTML = '<div class="todo">reading ' + esc(id) + '&hellip;</div>';
  cfPost('other', {id: id}).then(function(j){
    if (!j.ok){ body.innerHTML = '<div class="cst-warn">' + esc(j.error || ('HTTP ' + j._code)) + '</div>'; return; }
    var other = (CF.cmp.list || []).find(function(c){ return c.id === id; }) || {};
    var mineImg = (document.getElementById('cs-portrait') || {}).src || '';
    var theirs = cfPortrait(other);
    var F = CST.spec.fields, secs = CST.spec.sections || [], diff = 0, rows = '';
    secs.filter(function(s){ return CF_CMP_SECS.indexOf(s) >= 0; }).forEach(function(s){
      var ps = Object.keys(F).filter(function(p){ return F[p].sec === s; });
      if (!ps.length) return;
      rows += '<div class="cst-grp">' + esc(s) + '</div>';
      ps.forEach(function(p){
        var a = cfShow(CST.values[p]), b = cfShow(j.values[p]), ne = (a !== b);
        if (ne) diff++;
        rows += '<div class="kv"' + (ne ? ' style="background:rgba(255,176,0,.10)"' : '') + '>'
          + '<b>' + esc(p.split('.').pop()) + '</b><span>'
          + esc(a) + '<span class="dim"> │ </span>' + esc(b) + '</span></div>';
      });
    });
    body.innerHTML =
      '<div style="display:flex;gap:10px;align-items:flex-start;margin:6px 0 10px">'
      + '<div style="flex:1;min-width:0"><div class="cst-hint">' + esc(CS.charName || CS.charId) + '</div>'
      + (mineImg ? '<img src="' + esc(mineImg) + '" style="width:100%;border-radius:8px">'
                 : '<div class="todo">no portrait</div>') + '</div>'
      + '<div style="flex:1;min-width:0"><div class="cst-hint">' + esc(j.name) + '</div>'
      + (theirs ? '<img src="' + esc(theirs) + '" style="width:100%;border-radius:8px">'
                : '<div class="todo">no portrait</div>') + '</div></div>'
      + cstKv('fields that differ', diff)
      + '<div class="cst-hint">left = this character · right = ' + esc(j.name) + '</div>'
      + rows;
  }).catch(function(e){ body.innerHTML = '<div class="cst-warn">' + esc(String(e)) + '</div>'; });
}

/* ══ Sheet grid ══════════════════════════════════════════════════════════
   The contact-sheet MASTER is not one of /inspect/img's three categories
   (arcane_final, cells, tiles) — it sits at contact_sheet/contact_sheet_*.png
   and is served by this extension's own fenced `sheet` op. */
function cfGridEl(){
  var main = document.querySelector('#view-charstudio .cs-main');
  if (!main) return null;
  var img = document.getElementById('cs-grid');
  if (!img){
    img = document.createElement('img');
    img.id = 'cs-grid';
    img.alt = 'contact sheet';
    img.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:contain;'
      + 'background:#07090c;border-radius:10px;display:none;z-index:3';
    main.appendChild(img);
  }
  return img;
}
function cfGridOn(url){
  var img = cfGridEl(); if (!img) return;
  /* snapshot only on the way IN. Picking a second sheet while the grid is
     already up would otherwise record the hidden state as the one to restore,
     and 'Back to 3D' would put the body back to display:none. */
  if (!CF.grid){
    CF.grid = {};
    ['cs-3d', 'cs-portrait', 'cs-empty', 'cs-credit'].forEach(function(id){
      var el = document.getElementById(id);
      if (el){ CF.grid[id] = el.style.display; el.style.display = 'none'; }
    });
  }
  img.src = url;
  img.style.display = 'block';
}
function cfGridOff(){
  var img = document.getElementById('cs-grid');
  if (img){ img.style.display = 'none'; img.removeAttribute('src'); }
  if (CF.grid){
    Object.keys(CF.grid).forEach(function(id){
      var el = document.getElementById(id);
      if (el) el.style.display = CF.grid[id];
    });
    CF.grid = null;
  }
}
CST_ACT.grid = function(){
  if (!CS.charId) return cstPanelOpen('d_grid', 'Sheet grid', cstNoChar());
  cfBusyPanel('d_grid', 'Sheet grid');
  cfPost('sheets', {id: CS.charId}).then(function(j){
    if (!j.ok) return cfErr('d_grid', 'Sheet grid', j);
    if (!j.sheets.length) return cstPanelOpen('d_grid', 'Sheet grid',
      '<div class="todo">This character has no contact sheet on disk. Whatever images it has '
      + 'were not written by a sheet run.</div>');
    var first = (j.sheets.find(function(s){ return s.which === 'master'; }) || j.sheets[0]).which;
    cfGridShow(first);
    cstPanelOpen('d_grid', 'Sheet grid',
      '<div class="cst-hint big">The contact sheet is in the preview pane instead of the body. '
      + 'These are the sheet files on this character’s disk, at full size — the master is the one '
      + 'the cells were cut from.</div>'
      + j.sheets.map(function(s){
          return '<div class="kv"><b>' + esc(s.which) + '</b><span>'
            + '<button onclick="cfGridShow(\'' + esc(s.which) + '\')">show</button> '
            + esc(cstBytes(s.bytes)) + ' · ' + esc(cstWhen(s.mtime)) + '</span></div>'; }).join('')
      + '<div class="cst-foot"><button class="go" onclick="cfGridOff()">Back to 3D</button></div>'
      + '<div class="cst-hint">Fit and Reset view bring the body back too.</div>');
  }).catch(function(e){
    cstPanelOpen('d_grid', 'Sheet grid', '<div class="cst-warn">' + esc(String(e)) + '</div>');
  });
};
function cfGridShow(which){
  cfGridOn('/inspect/api/studio/char_file/sheet?id=' + encodeURIComponent(CS.charId)
           + '&which=' + encodeURIComponent(which));
}
/* the View tools that mean "show me the body again" put it back */
['full', 'resetcam', 'fit'].forEach(function(k){
  var orig = CST_ACT[k];
  if (typeof orig !== 'function') return;
  CST_ACT[k] = function(t){ cfGridOff(); return orig.call(this, t); };
});

if (window.SX && SX.ready) SX.ready.push('char_file');
