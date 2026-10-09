# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI script, part 4: the Resources tab.

Moved verbatim out of medusa_server.py (lines 2373-2904); reassembled in html.py.
"""

JS_RESOURCES = """  // ── Resources tab: saved page in → one folder of pictures out ─────────────
  // Scope is deliberately narrow and the GUI says so out loud: this uploads
  // pages the operator saved in their own browser and fetches only the
  // addresses those pages already contain. No crawler, no sign-in, no cookie
  // replay — see medusa_resources.py's docstring for why that line is drawn
  // where it is.
  (function(){
    var drop = document.getElementById('r_drop');
    if (!drop) return;

    var input     = document.getElementById('r_file');
    var pickBtn   = document.getElementById('r_pick');
    var goBtn     = document.getElementById('r_go');
    var statusEl  = document.getElementById('r_status');
    var pickedBox = document.getElementById('r_picked');
    var mergeBox  = document.getElementById('r_merge');
    var mergeName = document.getElementById('r_mergename');
    var urlsBox   = document.getElementById('r_urls');
    var urlSet    = document.getElementById('r_urlset');
    var urlCount  = document.getElementById('r_urlcount');
    var picked    = [];
    var pollTimer = null;
    var PAGE_EXTS = ['.html', '.htm', '.xhtml', '.mhtml', '.mht'];

    function extOf(name){
      var s = String(name || '');
      var i = s.lastIndexOf('.');
      return i < 0 ? '' : s.slice(i).toLowerCase();
    }
    function fmtBytes(n){
      n = Number(n) || 0;
      if (n >= 1073741824) return (n / 1073741824).toFixed(1) + ' GB';
      if (n >= 1048576)    return (n / 1048576).toFixed(1) + ' MB';
      if (n >= 1024)       return Math.round(n / 1024) + ' KB';
      return n + ' B';
    }
    function setStatus(text, cls){
      statusEl.className = 'sec-status' + (cls ? ' ' + cls : '');
      statusEl.textContent = text || '';
    }

    // ── File selection ──
    function addFiles(list){
      var rejected = [];
      Array.prototype.forEach.call(list || [], function(f){
        if (PAGE_EXTS.indexOf(extOf(f.name)) < 0) { rejected.push(f.name); return; }
        var dup = picked.some(function(p){ return p.name === f.name && p.size === f.size; });
        if (!dup) picked.push(f);
      });
      renderPicked();
      if (rejected.length) {
        setStatus('Not a saved page, ignored: ' + rejected.slice(0, 3).join(', ')
                  + (rejected.length > 3 ? ' +' + (rejected.length - 3) + ' more' : ''), 'err');
      } else {
        setStatus('');
      }
    }
    function renderPicked(){
      if (!picked.length) { pickedBox.innerHTML = ''; refreshGo(); return; }
      pickedBox.innerHTML = picked.map(function(f, i){
        var ext = extOf(f.name);
        var isM = (ext === '.mhtml' || ext === '.mht');
        return '<div class="res-file">' +
                 '<span class="fmt ' + (isM ? 'mhtml">self-contained' : 'html">needs refetch') + '</span>' +
                 '<span class="nm">' + secEsc(f.name) + '</span>' +
                 '<span class="sz">' + fmtBytes(f.size) + '</span>' +
                 '<button data-drop="' + i + '" title="Remove">&times;</button>' +
               '</div>';
      }).join('');
      pickedBox.querySelectorAll('[data-drop]').forEach(function(b){
        b.addEventListener('click', function(){
          picked.splice(parseInt(b.getAttribute('data-drop'), 10), 1);
          renderPicked();
        });
      });
      refreshGo();
    }

    // ── Typed addresses ──
    // Rough client-side count only; medusa_resources._split_urls does the real
    // parsing so the two can't disagree about what actually gets fetched.
    function parseUrls(){
      var out = [], seen = {};
      (urlsBox.value || '').split(/\\s+/).forEach(function(t){
        t = t.replace(/^[<"']+|[>"']+$/g, '');
        if (t.charAt(0) === '#') return;
        var low = t.toLowerCase();
        if ((low.indexOf('http://') === 0 || low.indexOf('https://') === 0) && !seen[t]) {
          seen[t] = 1;
          out.push(t);
        }
      });
      return out;
    }

    function refreshGo(){
      var n = parseUrls().length;
      urlCount.className = 'sec-status' + (n ? ' ok' : '');
      urlCount.textContent = n ? (n + (n === 1 ? ' address' : ' addresses') + ' ready') : '';
      goBtn.disabled = (picked.length === 0 && n === 0);
      if (previewBtn) previewBtn.disabled = (n === 0);
      var bits = [];
      if (picked.length) {
        bits.push(mergeBox.checked
          ? '1 folder from ' + picked.length + ' page' + (picked.length === 1 ? '' : 's')
          : picked.length + (picked.length === 1 ? ' folder' : ' folders'));
      }
      if (n) bits.push('1 folder from ' + n + ' address' + (n === 1 ? '' : 'es'));
      goBtn.textContent = bits.length ? 'Extract to ' + bits.join(' + ') : 'Extract to folders';
    }

    pickBtn.addEventListener('click', function(){ input.click(); });
    input.addEventListener('change', function(){ addFiles(input.files); input.value = ''; });
    drop.addEventListener('click', function(e){ if (e.target === drop || e.target.className.indexOf('res-drop-') === 0) input.click(); });
    ['dragenter', 'dragover'].forEach(function(ev){
      drop.addEventListener(ev, function(e){ e.preventDefault(); drop.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function(ev){
      drop.addEventListener(ev, function(e){ e.preventDefault(); drop.classList.remove('over'); });
    });
    drop.addEventListener('drop', function(e){
      if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
    });
    mergeBox.addEventListener('change', function(){
      mergeName.disabled = !mergeBox.checked;
      if (mergeBox.checked) mergeName.focus();
      refreshGo();
    });
    urlsBox.addEventListener('input', refreshGo);
    refreshGo();

    // ── Start ──
    // Both inputs share one button and one set of options. Whichever is filled
    // in runs; if both are, they start side by side into separate folders.
    function optionFields(){
      return {
        delay:      document.getElementById('r_delay').value || '2',
        workers:    document.getElementById('r_workers').value || '2',
        min_bytes:  String(Math.round((parseFloat(document.getElementById('r_minkb').value) || 0) * 1024)),
        min_edge:   document.getElementById('r_minedge').value || '0',
        base_url:   document.getElementById('r_base').value.trim(),
        stop_phrases:   document.getElementById('r_stop').value,
        exclude_words:  document.getElementById('r_exclude').value,
        respect_robots: document.getElementById('r_robots').checked ? '1' : '0',
        deep_scan:         document.getElementById('r_deep').checked ? '1' : '0',
        drop_junk:         document.getElementById('r_junk').checked ? '1' : '0',
        collapse_variants: document.getElementById('r_collapse').checked ? '1' : '0',
        merge_by_name:     document.getElementById('r_mergename2').checked ? '1' : '0',
        dedup_similar:     document.getElementById('r_similar').checked ? '1' : '0'
      };
    }

    // ── Dry run ──
    // Answers "why did it find so many?" without downloading anything: the
    // per-collector breakdown names the culprit, and `unfiltered` is the same
    // page with every filter switched off.
    var previewBtn = document.getElementById('r_preview');
    var previewOut = document.getElementById('r_previewout');

    function renderPreview(d){
      previewOut.className = 'res-preview show';
      if (!d.ok) {
        previewOut.innerHTML = '<span class="warn">' + secEsc(d.error || 'preview failed') + '</span>';
        return;
      }
      var how = Object.keys(d.by_how || {}).map(function(k){
        return '<span class="k"><b>' + d.by_how[k] + '</b> ' + secEsc(k) + '</span>';
      }).join('');
      var folders = Object.keys(d.by_folder || {}).map(function(k){
        return '<li><code>' + secEsc(k) + '</code> — ' + d.by_folder[k] + '</li>';
      }).join('');
      var st = d.stats || {};
      var lines = [];
      if (st.cut) {
        lines.push('Stopped at <b>“' + secEsc(st.cut.phrase) + '”</b> on line ' + st.cut.line +
                   ' — <b>' + st.dropped_after_cut + '</b> pictures after it left alone.');
      } else {
        lines.push('<span class="warn">No stop phrase matched</span> — the whole page was read. ' +
                   'Add the heading that follows the wanted pictures to the box above.');
      }
      var exc = Object.keys(st.excluded || {});
      if (exc.length) {
        lines.push('Excluded by name: ' + exc.map(function(w){
          return '<b>' + st.excluded[w] + '</b> containing “' + secEsc(w) + '”';
        }).join(', ') + ' — these are never requested.');
      }
      if (st.junk_block_count) {
        lines.push('Skipped <b>' + st.junk_block_count + '</b> related/sponsored block(s): ' +
                   (st.junk_blocks || []).slice(0, 4).map(function(b){
                     return '<code>' + secEsc(b.class || b.id || b.tag) + '</code>';
                   }).join(', '));
      }
      var who = d.character
        ? '<div style="margin-bottom:8px">Character: <b style="color:#f1f5f9">' +
          secEsc(d.character) + '</b> <span class="k">(from the ' + secEsc(d.named_by) +
          ')</span> &rarr; folder <code>' + secEsc(d.folder) + '</code></div>'
        : '<div class="warn" style="margin-bottom:8px">No character name found on this page — ' +
          'the folder would fall back to <code>' + secEsc(d.folder || '') + '</code>. ' +
          'Type one in the Folder name box.</div>';
      previewOut.innerHTML = who +
        '<h4><span class="big">' + d.kept + '</span> addresses would be collected' +
        (d.unfiltered > d.kept ? ' <span class="k">(with every filter off: ' + d.unfiltered + ')</span>' : '') +
        '</h4>' +
        '<div class="row">' + how + '</div>' +
        lines.map(function(l){ return '<div>' + l + '</div>'; }).join('') +
        (folders ? '<div style="margin-top:8px">Folders they come from:<ul>' + folders + '</ul></div>' : '') +
        '<div style="margin-top:8px" class="k">Duplicate sizes are collapsed after this ' +
        'step, so the number of files that actually land is usually lower still.</div>';
    }

    previewBtn.addEventListener('click', function(){
      var urls = parseUrls();
      if (!urls.length) { setStatus('Paste an address to dry-run.', 'err'); return; }
      previewBtn.disabled = true;
      previewOut.className = 'res-preview show';
      previewOut.textContent = 'Reading ' + urls[0] + ' …';
      var body = optionFields();
      body.urls = urls[0];
      fetch('/api/resources/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(function(r){ return r.json(); })
        .then(renderPreview)
        .catch(function(){ renderPreview({ ok: false, error: 'Medusa unreachable' }); })
        .then(function(){ previewBtn.disabled = false; refreshGo(); });
    });

    function sendUpload(){
      return new Promise(function(resolve){
        var fd = new FormData();
        picked.forEach(function(f){ fd.append('pages', f, f.name); });
        var opts = optionFields();
        Object.keys(opts).forEach(function(k){ fd.append(k, opts[k]); });
        if (mergeBox.checked) fd.append('merge_as', mergeName.value.trim());
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/resources/upload');
        xhr.upload.onprogress = function(e){
          if (e.lengthComputable) setStatus('Uploading… ' + Math.round(e.loaded / e.total * 100) + '%');
        };
        xhr.onload = function(){
          var d = {};
          try { d = JSON.parse(xhr.responseText); } catch (err) { d = {}; }
          if (xhr.status >= 200 && xhr.status < 300 && d.ok) {
            picked = [];
            renderPicked();
            resolve({ ok: true, n: (d.started || []).length });
          } else {
            resolve({ ok: false, error: d.error || ('upload HTTP ' + xhr.status) });
          }
        };
        xhr.onerror = function(){ resolve({ ok: false, error: 'upload failed — Medusa unreachable' }); };
        xhr.send(fd);
      });
    }

    function sendUrls(urls){
      var body = optionFields();
      body.urls = urls;
      body.set_name = urlSet.value.trim();
      return fetch('/api/resources/fetch-urls', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(function(r){ return r.json().then(function(d){
          return { ok: r.ok && d.ok, n: (d.started || []).length, error: d.error };
        }); })
        .catch(function(){ return { ok: false, error: 'addresses failed — Medusa unreachable' }; });
    }

    goBtn.addEventListener('click', function(){
      var urls = parseUrls();
      if (!picked.length && !urls.length) return;
      if (picked.length && mergeBox.checked && !mergeName.value.trim()) {
        setStatus('Give the merged folder a name.', 'err');
        mergeName.focus();
        return;
      }
      goBtn.disabled = true;
      setStatus('Starting…');
      var running = [];
      if (picked.length) running.push(sendUpload());
      if (urls.length)   running.push(sendUrls(urls));
      Promise.all(running).then(function(results){
        var bad = results.filter(function(r){ return !r.ok; });
        if (bad.length) {
          setStatus(bad.map(function(r){ return r.error; }).join(' · '), 'err');
        } else {
          var n = results.reduce(function(a, r){ return a + (r.n || 0); }, 0);
          if (urls.length) { urlsBox.value = ''; urlSet.value = ''; }
          setStatus('Started ' + n + ' extraction' + (n === 1 ? '' : 's') + '.', 'ok');
        }
        goBtn.disabled = false;
        refreshGo();
        rPoll();
      });
    });

    // ── Jobs + folders ──
    function renderJobs(jobs){
      var box = document.getElementById('r_jobs');
      if (!jobs || !jobs.length) {
        box.innerHTML = '<div class="train-empty">Nothing running.</div>';
        return false;
      }
      var busy = false;
      box.innerHTML = jobs.map(function(j){
        var active = (j.state === 'queued' || j.state === 'parsing' || j.state === 'downloading');
        if (active) busy = true;
        var pct = j.total ? Math.round(j.done / j.total * 100) : (active ? 0 : 100);
        return '<div class="res-job">' +
          '<div class="res-h">' +
            '<span class="res-name">' + secEsc(j.set || '(naming from the pages…)') + '</span>' +
            (j.character ? '<span class="res-state done">' + secEsc(j.character) + '</span>' : '') +
            (j.appended ? '<span class="res-state">added to existing</span>' : '') +
            '<span class="res-state ' + secEsc(j.state) + '">' + secEsc(j.state) + '</span>' +
            '<span class="res-spacer"></span>' +
            (active ? '<button class="btn-ghost" data-cancel="' + secEsc(j.id) + '">Cancel</button>' : '') +
          '</div>' +
          '<div class="res-msg">' + secEsc(j.message || '') + '</div>' +
          (j.total ? '<div class="res-bar"><div class="res-bar-fill" style="width:' + pct + '%"></div></div>' : '') +
          '<div class="res-stats">' +
            '<span><b>' + (j.saved || 0) + '</b> kept</span>' +
            (j.embedded ? '<span>' + j.embedded + ' from the file</span>' : '') +
            (j.variants ? '<span>' + j.variants + ' duplicate sizes skipped</span>' : '') +
            (j.excluded ? '<span>' + j.excluded + ' excluded by name</span>' : '') +
            (j.upgraded ? '<span>' + j.upgraded + ' replaced by a bigger copy</span>' : '') +
            '<span>' + (j.skipped || 0) + ' skipped</span>' +
            '<span>' + (j.failed || 0) + ' failed</span>' +
            '<span>' + fmtBytes(j.bytes) + '</span>' +
          '</div>' +
          (j.errors && j.errors.length
            ? '<details class="res-errs"><summary>' + j.errors.length + ' problem'
              + (j.errors.length === 1 ? '' : 's') + '</summary>'
              + j.errors.map(function(e){
                  return '<div>' + secEsc(e.reason) + (e.url ? ' — ' + secEsc(e.url) : '') + '</div>';
                }).join('') + '</details>'
            : '') +
        '</div>';
      }).join('');
      box.querySelectorAll('[data-cancel]').forEach(function(b){
        b.addEventListener('click', function(){
          b.disabled = true;
          fetch('/api/resources/jobs/' + b.getAttribute('data-cancel') + '/cancel',
                { method: 'POST' }).then(rPoll).catch(rPoll);
        });
      });
      return busy;
    }

    function renderSets(sets, root){
      var box = document.getElementById('r_sets');
      var count = document.getElementById('r_setcount');
      count.textContent = (sets && sets.length ? sets.length + ' in ' : 'in ') + (root || '');
      if (!sets || !sets.length) {
        box.innerHTML = '<div class="train-empty">No folders yet — upload a saved page above.</div>';
        return;
      }
      box.innerHTML = sets.map(function(s){
        var enc = encodeURIComponent(s.set);
        var shown = (s.preview || []).length;
        var thumbs = (s.preview || []).map(function(n){
          return '<button class="res-open" data-set="' + secEsc(s.set) + '" ' +
                 'data-img="' + secEsc(n) + '" title="' + secEsc(n) + '">' +
                 '<img loading="lazy" src="/api/resources/sets/' + enc + '/thumb/' +
                 encodeURIComponent(n) + '" alt=""></button>';
        }).join('');
        var more = s.images > shown
          ? '<button class="res-more res-open" data-set="' + secEsc(s.set) + '" ' +
            'data-at="' + shown + '">+' + (s.images - shown) + ' more</button>' : '';
        return '<div class="res-set">' +
          '<div class="res-h">' +
            '<span class="res-name">' + secEsc(s.set) + '</span>' +
            '<span class="res-state ' + secEsc(s.state || '') + '">' + secEsc(s.images) + ' pictures</span>' +
            '<span class="res-spacer"></span>' +
            '<button class="btn-decline" data-del="' + secEsc(s.set) + '">Delete folder</button>' +
          '</div>' +
          (thumbs ? '<div class="res-gal">' + thumbs + more + '</div>' : '') +
          '<div class="res-path">' + secEsc(s.path) + '</div>' +
          '<div class="res-stats" style="margin-top:6px">' +
            '<span>' + fmtBytes(s.bytes) + '</span>' +
            '<span>' + (s.skipped || 0) + ' skipped</span>' +
            '<span>' + (s.failed || 0) + ' failed</span>' +
            '<span>from ' + secEsc(s.source || 'page') + '</span>' +
          '</div>' +
        '</div>';
      }).join('');
      box.querySelectorAll('.res-open').forEach(function(b){
        b.addEventListener('click', function(){
          var at = b.getAttribute('data-at');
          lbOpen(b.getAttribute('data-set'), b.getAttribute('data-img') || '',
                 at ? parseInt(at, 10) : 0);
        });
      });
      box.querySelectorAll('[data-del]').forEach(function(b){
        b.addEventListener('click', function(){
          var name = b.getAttribute('data-del');
          // HTML is a plain (non-raw) Python string, so a newline escape has to
          // survive Python first — hence the doubled backslashes.
          if (!confirm('Delete the folder "' + name + '" and every picture in it?\\n\\n'
                       + 'This cannot be undone.')) return;
          b.disabled = true;
          fetch('/api/resources/sets/' + encodeURIComponent(name), { method: 'DELETE' })
            .then(rPoll).catch(rPoll);
        });
      });
    }

    // ── Picture viewer ──
    // The card shows at most eight previews, but the arrows must walk the whole
    // folder — so the full file list is fetched when the viewer opens.
    var lb       = document.getElementById('r_lb');
    var lbImg    = document.getElementById('r_lbimg');
    var lbName   = document.getElementById('r_lbname');
    var lbCount  = document.getElementById('r_lbcount');
    var lbStage  = document.getElementById('r_lbstage');
    var lbSet    = '';
    var lbList   = [];
    var lbIndex  = 0;

    function lbSrc(name){
      return '/api/resources/sets/' + encodeURIComponent(lbSet) +
             '/image/' + encodeURIComponent(name);
    }
    function lbWrap(i){
      if (!lbList.length) return 0;
      return ((i % lbList.length) + lbList.length) % lbList.length;
    }
    function lbShow(i){
      if (!lbList.length) return;
      lbIndex = lbWrap(i);
      lbImg.src = lbSrc(lbList[lbIndex]);
      lbName.textContent = lbList[lbIndex];
      lbCount.textContent = (lbIndex + 1) + ' / ' + lbList.length;
      // Warm the neighbours so holding an arrow key stays smooth.
      [lbIndex - 1, lbIndex + 1].forEach(function(k){
        var pre = new Image();
        pre.src = lbSrc(lbList[lbWrap(k)]);
      });
    }
    function lbOpen(setName, startName, startIndex){
      lbSet = setName;
      lbList = [];
      lb.classList.add('open');
      lb.focus();
      lbImg.removeAttribute('src');
      lbName.textContent = startName || '';
      lbCount.textContent = '…';
      fetch('/api/resources/sets/' + encodeURIComponent(setName))
        .then(function(r){ return r.json(); })
        .then(function(d){
          lbList = (d && d.images) || [];
          var at = startName ? lbList.indexOf(startName) : (startIndex || 0);
          lbShow(at < 0 ? 0 : at);
        })
        .catch(function(){
          lbList = startName ? [startName] : [];
          lbShow(0);
        });
    }
    function lbClose(){
      lb.classList.remove('open');
      lbImg.removeAttribute('src');
      lbList = [];
    }

    document.getElementById('r_lbprev').addEventListener('click', function(){ lbShow(lbIndex - 1); });
    document.getElementById('r_lbnext').addEventListener('click', function(){ lbShow(lbIndex + 1); });
    document.getElementById('r_lbclose').addEventListener('click', lbClose);
    document.getElementById('r_lbfull').addEventListener('click', function(){
      if (lbList.length) window.open(lbSrc(lbList[lbIndex]), '_blank', 'noopener');
    });
    // Clicking the backdrop (bar or the empty space around the picture) closes.
    lb.addEventListener('click', function(e){ if (e.target === lb) lbClose(); });
    lbStage.addEventListener('click', function(e){ if (e.target === lbStage) lbClose(); });

    document.addEventListener('keydown', function(e){
      if (!lb.classList.contains('open')) return;
      if (e.key === 'ArrowLeft')       { e.preventDefault(); lbShow(lbIndex - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); lbShow(lbIndex + 1); }
      else if (e.key === 'Escape')     { e.preventDefault(); lbClose(); }
      else if (e.key === 'Home')       { e.preventDefault(); lbShow(0); }
      else if (e.key === 'End')        { e.preventDefault(); lbShow(lbList.length - 1); }
    });

    function rPoll(){
      return fetch('/api/resources/jobs')
        .then(function(r){ return r.json(); })
        .then(function(d){
          var busy = renderJobs(d.jobs || []);
          renderSets(d.sets || [], d.root);
          document.getElementById('r_root').textContent = d.root || '';
          schedule(busy ? 2000 : 8000);
        })
        .catch(function(){
          document.getElementById('r_sets').innerHTML =
            '<div class="train-empty">Resources API unreachable.</div>';
          schedule(8000);
        });
    }
    function schedule(ms){
      if (pollTimer) clearTimeout(pollTimer);
      var panel = document.querySelector('.panel[data-panel="resources"]');
      if (!panel || !panel.classList.contains('active')) { pollTimer = null; return; }
      pollTimer = setTimeout(rPoll, ms);
    }

    // Seed the tunables from the server's own defaults, so the stop-phrase list
    // in the box is exactly the one medusa_resources.py would apply and the two
    // cannot drift apart.
    fetch('/api/resources/config')
      .then(function(r){ return r.json(); })
      .then(function(d){
        var def = (d && d.defaults) || {};
        var stop = document.getElementById('r_stop');
        if (def.stop_phrases && !stop.value) stop.value = def.stop_phrases.join('\\n');
        var exc = document.getElementById('r_exclude');
        if (def.exclude_words && !exc.value) exc.value = def.exclude_words.join(', ');
        if (def.workers) document.getElementById('r_workers').value = def.workers;
        if (def.delay != null) document.getElementById('r_delay').value = def.delay;
        document.getElementById('r_deep').checked = !!def.deep_scan;
        if (d && d.max_workers) document.getElementById('r_workers').max = d.max_workers;
      })
      .catch(function(){});

    document.getElementById('r_refresh').addEventListener('click', rPoll);
    var resTab = document.querySelector('.tab[data-tab="resources"]');
    if (resTab) resTab.addEventListener('click', rPoll);
  })();

"""
