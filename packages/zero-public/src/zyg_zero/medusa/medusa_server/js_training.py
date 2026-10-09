# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI script, part 2: the Training tab and bulk folder import.

Moved verbatim out of medusa_server.py (lines 1612-2134); reassembled in html.py.
"""

JS_TRAINING = """  // ── Training tab: upload-your-own-photos dedicated character LoRAs ──
  // Isolated by design — proxied to the crews (:5000) medusa_training routes,
  // which write to a dataset/output root the public workflow pipeline never
  // reads from. See bp_medusa_training.py for the isolation contract.
  var T_CHARS = [];
  var _trainPollTimer = null;
  var _trainInit = false;

  function tStatusClass(training){
    if(!training) return '';
    if(training.failed) return 'error';
    if(training.done) return 'done';
    if((training.step||0) > 0) return 'running';
    return '';
  }
  function tStatusText(training, canTrain, imageCount){
    if(!training) return canTrain ? 'Ready to train' : 'Needs ' + Math.max(0,5-imageCount) + ' more photo(s)';
    if(training.failed) return 'Failed: ' + (training.error || 'unknown error');
    if(training.done) return 'Trained ✓ (' + (training.model_family||'') + ')';
    if((training.step||0) > 0) return 'Training… ' + training.step + '/' + training.total_steps + ' (' + training.pct + '%)';
    return canTrain ? 'Ready to train' : 'Needs ' + Math.max(0,5-imageCount) + ' more photo(s)';
  }
  function tCharCardHtml(c){
    var isBody = (c.mode === 'body');
    var training = c.training;
    var statusClass = tStatusClass(training);
    var statusText = tStatusText(training, c.can_train, c.image_count);
    var running = statusClass === 'running';
    var thumbs = (c.images||[]).map(function(img){
      return '<div class="train-thumb">' +
        '<img src="/api/medusa/training/characters/' + encodeURIComponent(c.char_id) + '/images/' + encodeURIComponent(img.id) + '" loading="lazy">' +
        '<button data-del-img="' + secEsc(img.id) + '" title="Remove">×</button>' +
      '</div>';
    }).join('');
    var progressBar = training && (training.step||0) > 0 && !training.done ?
      '<div class="train-progress-track"><div class="train-progress-fill" style="width:' + (training.pct||0) + '%"></div></div>' : '';
    var trainBtn = training && training.done ?
      '' : '<button class="btn-appr t-train-btn" ' + (c.can_train && !running ? '' : 'disabled') + '>' + (running ? 'Training…' : 'Start Training') + '</button>';

    // Contact sheet state — the sheet is the primary artifact here, the LoRA is optional.
    var ss = c.sheet_status || null;
    var sheetRunning = !!(ss && ss.running);
    var sheetLine = '';
    if(sheetRunning){
      var pct = ss.total ? Math.round(100*(ss.processed||0)/ss.total) : 0;
      sheetLine = '<div class="train-sheet-line">Building sheet — <b>' + (ss.phase||'') + '</b> ' +
                  (ss.total ? (ss.processed||0) + '/' + ss.total + ' (' + pct + '%)' : '') + '</div>';
    } else if(ss && ss.failed){
      sheetLine = '<div class="train-sheet-line">Sheet failed: ' + secEsc(ss.error||'unknown') + '</div>';
    } else if(c.has_sheet && c.sheet_coverage){
      var cov = c.sheet_coverage;
      sheetLine = '<div class="train-sheet-line">Sheet built — angle coverage <b>' + cov.yaw_coverage_pct + '%</b>' +
        (cov.yaw_missing && cov.yaw_missing.length ? ', missing: ' + secEsc(cov.yaw_missing.join(', ')) : '') +
        (cov.unknown_angle ? ', ' + cov.unknown_angle + ' unclassified' : '') + '</div>';
    }
    var sheetBtn = '<button class="btn-appr t-sheet-btn" ' + (c.image_count && !sheetRunning ? '' : 'disabled') + '>' +
      (sheetRunning ? 'Building…' : (c.has_sheet ? 'Rebuild Contact Sheet' : 'Build Contact Sheet')) + '</button>';

    // Body-template characters need the masked-loss dataset prepared before
    // they can train; identity characters train straight off training/.
    var bs = c.body_status || null;
    var bodyRunning = !!(bs && bs.running);
    var bodyBtn = '';
    if(isBody){
      bodyBtn = '<button class="btn-appr t-body-btn" ' + (c.has_sheet && !bodyRunning ? '' : 'disabled') + '>' +
        (bodyRunning ? 'Preparing…' : 'Prepare body dataset') + '</button>';
      var rep = (bs && bs.report) || c.body_report;
      if(bodyRunning){
        sheetLine += '<div class="train-sheet-line">Masking faces out of the training loss…</div>';
      } else if(bs && bs.failed){
        sheetLine += '<div class="train-sheet-line">Body prepare failed: ' + secEsc(bs.error||'unknown') + '</div>';
      } else if(rep){
        sheetLine += '<div class="train-sheet-line">Body dataset — <b>' + rep.admitted + '/' + rep.total +
          '</b> usable, ' + (rep.quarantined_count||0) + ' held back, avg <b>' +
          (rep.mean_masked_fraction*100).toFixed(1) + '%</b> of frame ignored' +
          (rep.masks_placed_off_head ? ' · <b>' + rep.masks_placed_off_head + ' mask(s) off-head — do not train</b>' : '') +
          '</div>';
      }
    }

    return '' +
    '<div class="train-char-card" data-char="' + secEsc(c.char_id) + '">' +
      '<div class="train-char-h">' +
        '<span class="train-char-name">' + secEsc(c.display_name||'Untitled') + '</span>' +
        '<span class="cs-mode-badge ' + (isBody?'body':'identity') + '">' + (isBody?'body template':'identity') + '</span>' +
        '<span class="train-char-meta">' + secEsc(c.trigger_token||'') + ' · ' + secEsc(c.model_family||'flux') + ' · ' + c.image_count + ' photo(s)</span>' +
        '<span class="train-char-spacer"></span>' +
        '<span class="train-char-status ' + statusClass + '">' + secEsc(statusText) + '</span>' +
        '<button class="btn-decline t-del-char-btn">Delete</button>' +
      '</div>' +
      progressBar + sheetLine +
      '<div class="train-gallery">' + thumbs +
        '<button class="train-thumb-add t-add-btn" title="Upload photos">+</button>' +
        '<input type="file" class="t-file-input" multiple accept="image/png,image/jpeg,image/webp" hidden>' +
      '</div>' +
      '<div class="train-actions">' + sheetBtn + bodyBtn + trainBtn + '<span class="t-upload-status sec-status"></span></div>' +
    '</div>';
  }
  function tRender(){
    var box = document.getElementById('t_list');
    if(!box) return;
    if(!T_CHARS.length){ box.innerHTML = '<div class="train-empty">No dedicated characters yet — create one above, then upload reference photos.</div>'; return; }
    box.innerHTML = T_CHARS.map(tCharCardHtml).join('');

    box.querySelectorAll('.t-add-btn').forEach(function(btn){
      btn.addEventListener('click', function(){
        btn.parentElement.querySelector('.t-file-input').click();
      });
    });
    box.querySelectorAll('.t-file-input').forEach(function(inp){
      inp.addEventListener('change', function(e){
        var card = inp.closest('.train-char-card');
        var charId = card.getAttribute('data-char');
        if(e.target.files && e.target.files.length) tUploadFiles(charId, e.target.files, card);
        e.target.value = '';
      });
    });
    box.querySelectorAll('[data-del-img]').forEach(function(btn){
      btn.addEventListener('click', function(){
        var card = btn.closest('.train-char-card');
        tDeleteImage(card.getAttribute('data-char'), btn.getAttribute('data-del-img'));
      });
    });
    box.querySelectorAll('.t-del-char-btn').forEach(function(btn){
      btn.addEventListener('click', function(){
        var card = btn.closest('.train-char-card');
        var charId = card.getAttribute('data-char');
        if(confirm('Delete this dedicated character and all its training data? This cannot be undone.')) tDeleteCharacter(charId);
      });
    });
    box.querySelectorAll('.t-train-btn').forEach(function(btn){
      btn.addEventListener('click', function(){
        var card = btn.closest('.train-char-card');
        tStartTraining(card.getAttribute('data-char'));
      });
    });
    box.querySelectorAll('.t-sheet-btn').forEach(function(btn){
      btn.addEventListener('click', function(){
        var card = btn.closest('.train-char-card');
        tBuildSheet(card.getAttribute('data-char'));
      });
    });
    box.querySelectorAll('.t-body-btn').forEach(function(btn){
      btn.addEventListener('click', function(){
        var card = btn.closest('.train-char-card');
        tPrepareBody(card.getAttribute('data-char'));
      });
    });
  }
  function tPrepareBody(charId){
    fetch('/api/medusa/training/characters/' + encodeURIComponent(charId) + '/body-prepare',
          {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
      .then(function(r){ return r.json(); }).then(function(d){
        if(!d || !d.ok) alert('Could not prepare the body dataset: ' + ((d&&d.error)||'unknown error'));
        tLoadCharacters();
      }).catch(function(err){ alert('Request failed: ' + err); });
  }
  function tBuildSheet(charId){
    fetch('/api/medusa/training/characters/' + encodeURIComponent(charId) + '/sheet', {method:'POST'})
      .then(function(r){ return r.json(); }).then(function(d){
        if(!d || !d.ok) alert('Could not build contact sheet: ' + ((d&&d.error)||'unknown error'));
        tLoadCharacters();
      }).catch(function(err){ alert('Request failed: ' + err); });
  }
  // tRender() replaces every card's DOM. While an upload is in flight that
  // would detach the very .t-upload-status node the upload writes progress
  // into, so a 400-photo run (10 sequential chunks) would silently lose its
  // progress display on the first 6s poll. Suspend re-rendering instead.
  var _tBusy = 0;
  function tLoadCharacters(){
    if(_tBusy > 0) return Promise.resolve();
    return fetch('/api/medusa/training/characters').then(function(r){return r.json();}).then(function(d){
      if(d && d.ok){ T_CHARS = d.characters || []; tRender(); }
    }).catch(function(){
      var box = document.getElementById('t_list');
      if(box) box.innerHTML = '<div class="train-empty">Crews API (:5000) unreachable.</div>';
    });
  }
  function tCreateCharacter(){
    var val = function(id){ var el = document.getElementById(id); return el ? el.value.trim() : ''; };
    var out = document.getElementById('t_create_result');
    var body = {
      display_name: val('t_name'),
      model_family: val('t_family'),
      trigger_token: val('t_trigger'),
      caption_suffix: val('t_suffix'),
      mode: val('t_mode'),
      body_promptables: val('t_promptables'),
    };
    if(body.mode === 'body' && !body.body_promptables){
      out.className = 'studio-result bad';
      out.textContent = 'Body templates need a hair / skin / clothing description.';
      return;
    }
    out.className = 'studio-result'; out.textContent = 'Creating…';
    fetch('/api/medusa/training/characters', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok, d:d}; }); })
      .then(function(res){
        if(res.ok && res.d.ok){
          out.className = 'studio-result good'; out.textContent = 'Created "' + (res.d.character.display_name) + '".';
          ['t_name','t_trigger','t_suffix'].forEach(function(id){ document.getElementById(id).value = ''; });
          tLoadCharacters();
        } else {
          out.className = 'studio-result bad'; out.textContent = 'Error: ' + ((res.d && res.d.error) || 'unknown');
        }
      }).catch(function(err){ out.className = 'studio-result bad'; out.textContent = 'Request failed: ' + err; });
  }
  // Uploads are CHUNKED so an arbitrarily large selection works: the server
  // caps files per request (not per character), so a 400-photo folder simply
  // becomes 10 sequential requests instead of one oversized one.
  var T_UPLOAD_CHUNK = 40;
  function tUploadChunked(charId, files, onProgress){
    var list = Array.prototype.slice.call(files);
    var uploaded = 0, failed = 0;
    function step(i){
      if(i >= list.length) return Promise.resolve({uploaded: uploaded, failed: failed});
      var slice = list.slice(i, i + T_UPLOAD_CHUNK);
      var fd = new FormData();
      slice.forEach(function(f){ fd.append('images', f); });
      if(onProgress) onProgress(Math.min(i + slice.length, list.length), list.length);
      return fetch('/api/medusa/training/characters/' + encodeURIComponent(charId) + '/images', {
        method: 'POST', body: fd,
      }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok, d:d}; }); })
        .then(function(res){
          if(res.ok && res.d && res.d.ok){
            uploaded += (res.d.uploaded||[]).length;
            failed += (res.d.errors||[]).length;
          } else {
            failed += slice.length;
          }
          return step(i + T_UPLOAD_CHUNK);
        });
    }
    return step(0);
  }
  function tUploadFiles(charId, fileList, card){
    // Re-resolve the status node by char id on every write: even with
    // rendering suspended, an unrelated render (create, delete) can replace it.
    var setS = function(txt, cls){
      var c = document.querySelector('.train-char-card[data-char="' + charId + '"]');
      var status = c ? c.querySelector('.t-upload-status') : null;
      if(status){ status.textContent = txt; status.className = 'sec-status t-upload-status' + (cls||''); }
    };
    _tBusy++;
    setS('Uploading ' + fileList.length + ' photo(s)…', '');
    return tUploadChunked(charId, fileList, function(done, total){
      setS('Uploading ' + done + '/' + total + '…', '');
    }).then(function(r){
      _tBusy--;
      setS(r.uploaded + ' uploaded' + (r.failed ? ', ' + r.failed + ' failed' : ''), r.failed ? ' err' : ' ok');
      tLoadCharacters();
      return r;
    }).catch(function(err){
      _tBusy--;
      setS('Upload failed: ' + err, ' err');
    });
  }
  function tDeleteImage(charId, imageId){
    fetch('/api/medusa/training/characters/' + encodeURIComponent(charId) + '/images/' + encodeURIComponent(imageId), {method:'DELETE'})
      .then(tLoadCharacters).catch(tLoadCharacters);
  }
  function tDeleteCharacter(charId){
    fetch('/api/medusa/training/characters/' + encodeURIComponent(charId), {method:'DELETE'})
      .then(function(r){ return r.json(); }).then(function(d){
        if(!d || !d.ok) alert('Could not delete: ' + ((d&&d.error)||'unknown error'));
        tLoadCharacters();
      }).catch(tLoadCharacters);
  }
  function tStartTraining(charId){
    fetch('/api/medusa/training/characters/' + encodeURIComponent(charId) + '/train', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({}),
    }).then(function(r){ return r.json(); }).then(function(d){
      if(!d || !d.ok) alert('Could not start training: ' + ((d&&d.error)||'unknown error'));
      tLoadCharacters();
    }).catch(function(err){ alert('Request failed: ' + err); });
  }
  // ── Bulk folder import ────────────────────────────────────────────────
  // Two routes to the same outcome, ONE FOLDER = ONE CHARACTER either way:
  //   (a) server-side scan of a path the operator types — no upload at all,
  //       which is what makes 80 folders x 60 photos practical;
  //   (b) the browser's directory picker, for folders the server cannot see.
  var T_SCAN = null;

  // Prefill the path box from the server so the operator never has to remember
  // where the drop folder is, and so the UI can't drift from the allowlist.
  function tLoadImportRoot(){
    return fetch('/api/medusa/training/import-root').then(function(r){ return r.json(); })
      .then(function(d){
        if(!d || !d.ok) return;
        var box = document.getElementById('t_scan_path');
        if(box && !box.value) box.value = d.root;
        var lbl = document.getElementById('t_root_path');
        if(lbl) lbl.textContent = d.root;
      }).catch(function(){});
  }

  function tScanFolder(){
    var path = (document.getElementById('t_scan_path').value||'').trim();
    var out = document.getElementById('t_scan_result');
    var list = document.getElementById('t_scan_list');
    var actions = document.getElementById('t_scan_actions');
    // Empty path is fine — the server falls back to the dedicated import root.
    out.className='sec-status'; out.textContent='Scanning…';
    list.innerHTML=''; actions.style.display='none'; T_SCAN=null;

    fetch('/api/medusa/training/scan-folder', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path:path})
    }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok,d:d}; }); })
      .then(function(res){
        if(!res.ok || !res.d.ok){
          out.className='sec-status err'; out.textContent = 'Error: ' + ((res.d&&res.d.error)||'scan failed');
          return;
        }
        var folders = res.d.folders || [];
        if(!folders.length){
          out.className='sec-status err';
          out.textContent = 'No images found in that folder or its subfolders.';
          return;
        }
        T_SCAN = {path: res.d.path, folders: folders, mode: res.d.mode};
        out.className='sec-status ok';
        out.textContent = folders.length + ' character folder(s), ' + res.d.total_images + ' picture(s) total' +
          (res.d.mode === 'single' ? ' — treating this folder itself as one character' : '') +
          (res.d.loose_images ? ' · ' + res.d.loose_images + ' loose picture(s) in the parent will be ignored' : '');
        list.innerHTML = folders.map(function(f){
          var nm = secEsc(f.name);
          return '<div class="train-scan-item" data-folder="' + nm + '">' +
            '<label class="t-scan-head">' +
              '<input type="checkbox" class="t-scan-cb" value="' + nm + '" checked>' +
              '<span class="nm">' + nm + '</span>' +
              '<span class="ct">' + f.image_count + ' pics</span>' +
            '</label>' +
            '<div class="t-scan-mode">' +
              '<label title="Keeps the face. Everything that makes this person recognisable binds to the trigger word.">' +
                '<input type="radio" name="mode-' + nm + '" class="t-mode" value="identity" checked> Identity — this exact person</label>' +
              '<label title="Learns build, proportions and posture. The face is masked out of the training loss, so nothing about it is learned.">' +
                '<input type="radio" name="mode-' + nm + '" class="t-mode" value="body"> Body template — build only, no face</label>' +
            '</div>' +
            '<input class="t-promptables" placeholder="Describe hair, skin and clothing — required for body templates" style="display:none">' +
          '</div>';
        }).join('');
        // Body mode needs the promptables field; identity mode must not show it.
        list.querySelectorAll('.t-mode').forEach(function(r){
          r.addEventListener('change', function(){
            var item = r.closest('.train-scan-item');
            item.querySelector('.t-promptables').style.display =
              (item.querySelector('.t-mode[value="body"]').checked ? 'block' : 'none');
          });
        });
        actions.style.display='flex';
      }).catch(function(err){ out.className='sec-status err'; out.textContent='Request failed: ' + err; });
  }

  // The POST is in flight for a moment with no visible change, which invites a
  // second click. Nothing server-side dedupes by source folder, so that second
  // click would create a whole duplicate set of characters — 160 from 80
  // folders, each needing manual deletion. Latch the button instead.
  var _tImporting = false;
  function tImportFolders(){
    if(!T_SCAN || _tImporting) return;
    var items = Array.prototype.slice.call(document.querySelectorAll('.train-scan-item'))
      .filter(function(it){ return it.querySelector('.t-scan-cb').checked; });
    var st = document.getElementById('t_import_status');
    var btn = document.getElementById('t_import');
    if(!items.length){ st.className='sec-status err'; st.textContent='Select at least one folder.'; return; }
    var names = [], missing = [];
    items.forEach(function(it){
      var mode = it.querySelector('.t-mode[value="body"]').checked ? 'body' : 'identity';
      var pr = (it.querySelector('.t-promptables').value||'').trim();
      if(mode === 'body' && !pr) missing.push(it.getAttribute('data-folder'));
      names.push({name: it.getAttribute('data-folder'), mode: mode, body_promptables: pr});
    });
    if(missing.length){
      st.className='sec-status err';
      st.textContent = 'Body templates need a hair / skin / clothing description: ' + missing.join(', ');
      return;
    }
    _tImporting = true; btn.disabled = true;
    st.className='sec-status'; st.textContent='Starting import of ' + names.length + ' folder(s)…';

    fetch('/api/medusa/training/import-folders', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        path: T_SCAN.path, folders: names,
        model_family: document.getElementById('t_batch_family').value,
        build_sheets: document.getElementById('t_batch_sheets').checked,
      })
    }).then(function(r){ return r.json().then(function(d){ return {ok:r.ok,d:d}; }); })
      .then(function(res){
        if(!res.ok || !res.d.ok){
          st.className='sec-status err'; st.textContent='Error: ' + ((res.d&&res.d.error)||'import failed');
          _tImporting = false; btn.disabled = false;
          return;
        }
        tPollImport(res.d.batch_id, function(){ _tImporting = false; btn.disabled = false; });
      }).catch(function(err){
        st.className='sec-status err'; st.textContent='Request failed: ' + err;
        _tImporting = false; btn.disabled = false;
      });
  }

  function tPollImport(batchId, onDone){
    var st = document.getElementById('t_import_status');
    function finish(){ if(onDone){ var f = onDone; onDone = null; f(); } }
    function tick(){
      fetch('/api/medusa/training/import/' + encodeURIComponent(batchId))
        .then(function(r){ return r.json(); }).then(function(d){
          if(!d || !d.ok){
            st.className='sec-status err'; st.textContent='Lost track of the import.';
            finish(); return;
          }
          var b = d.batch;
          if(b.running){
            st.className='sec-status';
            st.textContent = 'Importing… folder ' + (b.done_folders||0) + '/' + (b.total_folders||0) +
              ' · ' + (b.done_images||0) + '/' + (b.total_images||0) + ' pictures' +
              (b.current ? ' · ' + b.current : '');
            setTimeout(tick, 1500);
          } else {
            var nerr = (b.errors||[]).length;
            st.className = 'sec-status' + (nerr ? ' err' : ' ok');
            st.textContent = 'Imported ' + (b.created||[]).length + ' character(s), ' +
              (b.done_images||0) + ' picture(s)' + (nerr ? ' · ' + nerr + ' problem(s)' : '') +
              '. Contact sheets build in the background — see Inspection → Contact Sheet.';
            finish();
          }
          tLoadCharacters();
        }).catch(function(){ setTimeout(tick, 3000); });
    }
    tick();
  }

  // Browser directory picker: group the selection by its top-level folder so
  // each folder still becomes exactly one character.
  function tImportPickedDirs(files){
    var st = document.getElementById('t_import_status');
    var groups = {};
    var okExt = ['.png','.jpg','.jpeg','.webp'];
    Array.prototype.slice.call(files).forEach(function(f){
      // Match on extension rather than MIME type — browsers report an empty
      // type for plenty of legitimate files, and the server allows exactly
      // these four extensions anyway.
      var nm = (f.name||'').toLowerCase();
      if(!okExt.some(function(e){ return nm.slice(-e.length) === e; })) return;
      var rel = f.webkitRelativePath || f.name;
      var parts = rel.split('/');
      var key = parts.length > 1 ? parts[0] : '(root)';
      (groups[key] = groups[key] || []).push(f);
    });
    var names = Object.keys(groups);
    if(!names.length){ st.className='sec-status err'; st.textContent='No images in that selection.'; return; }
    if(_tImporting) return;

    var family = document.getElementById('t_batch_family').value;
    var buildSheets = document.getElementById('t_batch_sheets').checked;
    _tImporting = true; _tBusy++;
    st.className='sec-status';
    st.textContent = 'Uploading ' + names.length + ' folder(s)…';

    var done = 0;
    function next(i){
      if(i >= names.length){
        _tImporting = false; _tBusy--;
        st.className='sec-status ok';
        st.textContent = 'Imported ' + done + ' character(s). Contact sheets build in the background — ' +
                         'see Inspection → Contact Sheet.';
        tLoadCharacters();
        return;
      }
      var name = names[i], group = groups[name];
      st.textContent = 'Uploading "' + name + '" (' + (i+1) + '/' + names.length + ', ' + group.length + ' pics)…';
      fetch('/api/medusa/training/characters', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({display_name: name, model_family: family})
      }).then(function(r){ return r.json(); }).then(function(d){
        if(!d || !d.ok) throw new Error((d&&d.error)||'create failed');
        var cid = d.character.char_id;
        return tUploadChunked(cid, group, function(a,b){
          st.textContent = 'Uploading "' + name + '" — ' + a + '/' + b + ' (folder ' + (i+1) + '/' + names.length + ')';
        }).then(function(){
          done++;
          if(!buildSheets) return null;
          return fetch('/api/medusa/training/characters/' + encodeURIComponent(cid) + '/sheet', {method:'POST'});
        });
      }).then(function(){ next(i+1); })
        .catch(function(err){
          st.className='sec-status err';
          st.textContent = 'Failed on "' + name + '": ' + err + ' — continuing.';
          next(i+1);
        });
    }
    next(0);
  }

  function tInit(){
    if(_trainInit) return; _trainInit = true;
    document.getElementById('t_create').addEventListener('click', tCreateCharacter);
    document.getElementById('t_mode').addEventListener('change', function(e){
      document.getElementById('t_prompt_wrap').style.display =
        (e.target.value === 'body') ? 'flex' : 'none';
    });
    document.getElementById('t_scan').addEventListener('click', tScanFolder);
    document.getElementById('t_import').addEventListener('click', tImportFolders);
    document.getElementById('t_scan_path').addEventListener('keydown', function(e){
      if(e.key === 'Enter') tScanFolder();
    });
    tLoadImportRoot();
    var picker = document.getElementById('t_dirpicker');
    document.getElementById('t_pick_dirs').addEventListener('click', function(){ picker.click(); });
    picker.addEventListener('change', function(e){
      if(e.target.files && e.target.files.length) tImportPickedDirs(e.target.files);
      e.target.value = '';
    });
    tLoadCharacters();
    _trainPollTimer = setInterval(function(){
      var tab = document.querySelector('.tab[data-tab="training"]');
      if(tab && tab.classList.contains('active')) tLoadCharacters();
    }, 6000);
  }
  var _trainTab = document.querySelector('.tab[data-tab="training"]');
  if(_trainTab) _trainTab.addEventListener('click', tInit);

"""
