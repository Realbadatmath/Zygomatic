# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI script, part 3: the Inspection tab (Contact Sheet and LoRA sub-tabs).

Moved verbatim out of medusa_server.py (lines 2135-2372); reassembled in html.py.
"""

JS_INSPECTION = """  // ── Inspection → Contact Sheet sub-tab ────────────────────────────────
  var _csInit = false, _csTimer = null;

  document.querySelectorAll('.subtab').forEach(function(btn){
    btn.addEventListener('click', function(){
      var name = btn.dataset.sub;
      document.querySelectorAll('.subtab').forEach(function(b){ b.classList.toggle('active', b === btn); });
      document.querySelectorAll('.subpanel').forEach(function(p){
        p.classList.toggle('active', p.dataset.subpanel === name);
      });
      if(name === 'contactsheet') csInit();
      if(name === 'loras') lrInit();
    });
  });

  function csCoverageChips(cov){
    if(!cov) return '';
    var chips = (cov.yaw_covered||[]).map(function(g){
      var n = (cov.group_counts||{})[g] || 0;
      return '<span class="cs-chip have">' + secEsc(g) + ' · ' + n + '</span>';
    }).concat((cov.yaw_missing||[]).map(function(g){
      return '<span class="cs-chip miss">' + secEsc(g) + ' · none</span>';
    }));
    (cov.sided_gaps||[]).forEach(function(g){
      chips.push('<span class="cs-chip warn">' + secEsc(g.group) + ': no ' + secEsc(g.missing) + '</span>');
    });
    (cov.framing_missing||[]).forEach(function(f){
      chips.push('<span class="cs-chip warn">no ' + secEsc(f) + '</span>');
    });
    if(cov.unknown_angle) chips.push('<span class="cs-chip warn">' + cov.unknown_angle + ' unclassified</span>');
    return '<div class="cs-cov">' + chips.join('') + '</div>';
  }

  function csCardHtml(s){
    var st = s.status || {};
    var isBody = (s.mode === 'body');
    var head =
      '<div class="cs-card-h">' +
        '<span class="cs-name">' + secEsc(s.display_name||s.char_id) + '</span>' +
        '<span class="cs-mode-badge ' + (isBody?'body':'identity') + '">' +
          (isBody?'body template':'identity') + '</span>' +
        '<span class="cs-meta">' + secEsc(s.trigger_token||'') + ' · ' + (s.image_count||0) + ' pics</span>' +
        '<span class="cs-spacer"></span>' +
        (s.built_at ? '<span class="cs-meta">' + secEsc(s.built_at) + ' · ' + (s.duration_s||0) + 's</span>' : '') +
      '</div>';

    if(st.running){
      var pct = st.total ? Math.round(100*(st.processed||0)/st.total) : 0;
      return '<div class="cs-card">' + head +
        '<div class="cs-bar"><div class="cs-bar-fill" style="width:' + pct + '%"></div></div>' +
        '<div class="train-sheet-line">' + secEsc(st.phase||'working') + ' — ' +
          (st.total ? (st.processed||0) + '/' + st.total : 'queued') + '</div></div>';
    }
    if(st.failed){
      return '<div class="cs-card">' + head +
        '<div class="train-sheet-line">Failed: ' + secEsc(st.error||'unknown') + '</div></div>';
    }
    var notes = [];
    if((s.flagged||[]).length) notes.push(s.flagged.length + ' picture(s) flagged for review');
    if((s.duplicate_groups||[]).length) notes.push(s.duplicate_groups.length + ' near-duplicate group(s)');
    var imgFor = function(p){
      return '<img loading="lazy" src="/api/medusa/training/characters/' +
        encodeURIComponent(s.char_id) + '/sheet/page/' + encodeURIComponent(p) + '">';
    };
    var pages = (s.pages||[]).map(imgFor).join('');

    // Body mode: report what will actually be ignored by the loss, and show the
    // mask check sheet. A misplaced mask is invisible in the training images
    // themselves — this is the only place the operator can catch one.
    var bodyBlock = '';
    if(isBody){
      var rep = s.body_report;
      var bst = s.body_status || {};
      if(bst.running){
        bodyBlock = '<div class="train-sheet-line">Preparing body dataset…</div>';
      } else if(!rep){
        bodyBlock = '<div class="train-sheet-line">Body dataset not prepared yet — ' +
                    'use <b>Prepare body dataset</b> in the Training tab.</div>';
      } else {
        var pct = (rep.mean_masked_fraction*100);
        var cls = pct > 15 ? 'miss' : (pct > 10 ? 'warn' : 'have');
        bodyBlock =
          '<div class="cs-cov">' +
            '<span class="cs-chip have">' + rep.admitted + '/' + rep.total + ' usable</span>' +
            '<span class="cs-chip ' + cls + '">avg ' + pct.toFixed(1) + '% of frame ignored</span>' +
            (rep.quarantined_count ? '<span class="cs-chip warn">' + rep.quarantined_count + ' held back</span>' : '') +
            (rep.masks_placed_off_head ? '<span class="cs-chip miss">' + rep.masks_placed_off_head +
               ' mask(s) off-head — do not train</span>' : '') +
          '</div>' +
          '<div class="train-sheet-line">Faces are <b>masked out of the training loss</b>, not edited — ' +
            'the photographs themselves are untouched. Grey shows what is ignored.</div>' +
          '<div class="cs-pages">' + ((rep.pages||[]).map(imgFor).join('') ||
            '<span class="cs-empty">No mask check pages.</span>') + '</div>';
      }
    }

    return '<div class="cs-card">' + head + csCoverageChips(s.coverage) +
      (notes.length ? '<div class="train-sheet-line">' + secEsc(notes.join(' · ')) + '</div>' : '') +
      bodyBlock +
      '<div class="cs-pages">' + (pages || '<span class="cs-empty">No sheet pages.</span>') + '</div></div>';
  }

  function csLoad(){
    fetch('/api/medusa/training/sheets').then(function(r){ return r.json(); }).then(function(d){
      var box = document.getElementById('cs_list');
      if(!box) return;
      if(!d || !d.ok){ box.innerHTML = '<div class="cs-empty">Crews API (:5000) unreachable.</div>'; return; }
      var sheets = d.sheets || [];
      if(!sheets.length){
        box.innerHTML = '<div class="cs-empty">No contact sheets yet — prepare one in the Training tab.</div>';
        return;
      }
      box.innerHTML = sheets.map(csCardHtml).join('');
    }).catch(function(){
      var box = document.getElementById('cs_list');
      if(box) box.innerHTML = '<div class="cs-empty">Crews API (:5000) unreachable.</div>';
    });
  }

  function csInit(){
    if(!_csInit){
      _csInit = true;
      document.getElementById('cs_refresh').addEventListener('click', csLoad);
      document.getElementById('cs_build_all').addEventListener('click', function(){
        var st = document.getElementById('cs_status');
        st.className='sec-status'; st.textContent='Queueing…';
        fetch('/api/medusa/training/sheets/build-all', {
          method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})
        }).then(function(r){ return r.json(); }).then(function(d){
          if(!d || !d.ok){ st.className='sec-status err'; st.textContent='Error: ' + ((d&&d.error)||'failed'); return; }
          st.className='sec-status ok';
          st.textContent = 'Queued ' + d.started_count + ' sheet build(s)' +
                           ((d.skipped||[]).length ? ' · ' + d.skipped.length + ' skipped' : '') + '.';
          csLoad();
        }).catch(function(err){ st.className='sec-status err'; st.textContent='Request failed: ' + err; });
      });
      _csTimer = setInterval(function(){
        var panel = document.querySelector('.subpanel[data-subpanel="contactsheet"]');
        var tab = document.querySelector('.tab[data-tab="inspection"]');
        if(panel && panel.classList.contains('active') && tab && tab.classList.contains('active')) csLoad();
      }, 5000);
    }
    csLoad();
  }

  // ── Inspection → LoRA sub-tab ─────────────────────────────────────────
  // Same isolation story as Contact Sheet: fed only by /api/medusa/training/*,
  // which scans the dedicated medusa_training output root and nothing else.
  var _lrInit = false, _lrTimer = null, _lrSig = '';

  function lrSize(n){
    var mb = n / 1048576;
    return mb >= 1024 ? (mb/1024).toFixed(2) + ' GB' : Math.round(mb) + ' MB';
  }

  function lrElapsed(s){
    var h = Math.floor(s/3600), m = Math.round((s%3600)/60);
    return h ? h + 'h ' + m + 'm' : m + 'm';
  }

  function lrCardHtml(l){
    var state = l.failed ? 'failed' : (l.ready ? 'ready' : 'running');
    var head =
      '<div class="cs-card-h">' +
        '<span class="cs-name">' + secEsc(l.display_name||l.char_id) + '</span>' +
        '<span class="lr-fam">' + secEsc(l.model_family) + '</span>' +
        '<span class="lr-state ' + state + '">' +
          (l.failed ? 'failed' : (l.ready ? 'ready' : 'training')) + '</span>' +
        '<span class="cs-meta">' + secEsc(l.trigger_token||'') + ' · ' +
          (l.image_count||0) + ' pics</span>' +
        '<span class="cs-spacer"></span>' +
        (l.finished_at ? '<span class="cs-meta">' + secEsc(l.finished_at) + '</span>' : '') +
      '</div>';

    if(l.failed){
      return '<div class="cs-card">' + head +
        '<div class="train-sheet-line">Failed: ' + secEsc(l.error||'unknown') + '</div></div>';
    }
    if(!l.ready){
      return '<div class="cs-card">' + head +
        '<div class="cs-bar"><div class="cs-bar-fill" style="width:' +
          Math.round(l.pct||0) + '%"></div></div>' +
        '<div class="train-sheet-line">' + (l.step||0) + '/' + (l.total_steps||'?') + ' steps' +
          (l.eta_iso ? ' · done ~' + secEsc(l.eta_iso) : '') + '</div></div>';
    }

    var facts = [(l.step||0) + ' steps'];
    if(l.size_bytes) facts.push(lrSize(l.size_bytes));
    if(l.elapsed_s) facts.push('trained in ' + lrElapsed(l.elapsed_s));
    if(l.mode === 'body') facts.push('body template');

    var samples = (l.samples||[]).map(function(n){
      var u = '/api/medusa/training/loras/' + encodeURIComponent(l.char_id) + '/' +
              encodeURIComponent(l.model_family) + '/sample/' + encodeURIComponent(n);
      return '<figure><a href="' + u + '" target="_blank" rel="noopener">' +
        '<img loading="lazy" src="' + u + '"></a><figcaption>' +
        secEsc(n.replace('_1024x1024.png','').replace('.png','')) + '</figcaption></figure>';
    }).join('');

    return '<div class="cs-card">' + head +
      '<div class="train-sheet-line">' + secEsc(facts.join(' · ')) + '</div>' +
      '<div class="lr-path">' + secEsc(l.lora_path||'') + '</div>' +
      '<div class="lr-samples">' + (samples ||
        '<span class="cs-empty">This run saved no validation renders.</span>') + '</div></div>';
  }

  function lrLoad(){
    fetch('/api/medusa/training/loras').then(function(r){ return r.json(); }).then(function(d){
      var box = document.getElementById('lr_list');
      if(!box) return;
      if(!d || !d.ok){ box.innerHTML = '<div class="cs-empty">Crews API (:5000) unreachable.</div>'; return; }
      var loras = d.loras || [];
      // Re-rendering identical markup would re-fetch every sample image and
      // wipe the operator's scroll position on each poll.
      var sig = JSON.stringify(loras);
      if(sig === _lrSig) return;
      _lrSig = sig;
      box.innerHTML = loras.length ? loras.map(lrCardHtml).join('')
        : '<div class="cs-empty">No LoRAs yet — train one in the Training tab.</div>';
    }).catch(function(){
      var box = document.getElementById('lr_list');
      if(box) box.innerHTML = '<div class="cs-empty">Crews API (:5000) unreachable.</div>';
    });
  }

  function lrInit(){
    if(!_lrInit){
      _lrInit = true;
      document.getElementById('lr_refresh').addEventListener('click', function(){ _lrSig=''; lrLoad(); });
      _lrTimer = setInterval(function(){
        var panel = document.querySelector('.subpanel[data-subpanel="loras"]');
        var tab = document.querySelector('.tab[data-tab="inspection"]');
        if(panel && panel.classList.contains('active') && tab && tab.classList.contains('active')) lrLoad();
      }, 5000);
    }
    lrLoad();
  }

"""
