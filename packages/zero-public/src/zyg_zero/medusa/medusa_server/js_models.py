# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI script, part 6: the Models tab (BASE-model LoRA kanban).

Moved verbatim out of medusa_server.py (lines 3476-3883); reassembled in html.py.
"""

JS_MODELS = """  // ── Models tab: BASE-model LoRA kanban ────────────────────────────────────
  // One board per model family. Lanes come from the server's DERIVED `lane`
  // field, never from anything this page stores — see bp_medusa_models._lane.
  (function(){
    var LANES = [
      ['collecting', 'Collecting',  'Building the dataset'],
      ['ready',      'Ready',       'Attested and big enough'],
      ['training',   'Training',    'On the GPU now'],
      ['trained',    'Trained',     'Adapter on disk, switched off'],
      ['active',     'Active',      'Live for Medusa renders'],
      ['parked',     'Parked',      'Set aside']
    ];
    var famSel = '', models = [], meta = {}, openId = '', pollTimer = null;

    function esc(s){
      return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
      });
    }
    function api(method, path, body){
      var opt = {method: method};
      if (body !== undefined){
        opt.headers = {'Content-Type':'application/json'};
        opt.body = JSON.stringify(body);
      }
      return fetch('/api/medusa/models' + path, opt).then(function(r){
        return r.json().then(function(d){
          if (!r.ok) throw new Error(d && d.error ? d.error : ('HTTP ' + r.status));
          return d;
        });
      });
    }

    function load(){
      return api('GET', famSel ? ('?family=' + encodeURIComponent(famSel)) : '')
        .then(function(d){
          models = d.models || [];
          meta = d;
          if (!famSel && d.families && d.families.length) famSel = d.families[0];
          var age = document.getElementById('mdlMinAge');
          if (age) age.textContent = d.min_age || 18;
          renderFams(); renderBoard(); renderActive();
          // Re-render the open panel only when the user is not typing in it —
          // a 5 s poll must not wipe a half-typed prompt or link list.
          var ae = document.activeElement;
          var typing = ae && document.getElementById('mdlDetailBody').contains(ae) &&
                       /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName);
          if (openId && !typing) renderDetail();
        })
        .catch(function(e){ boardError(e.message); });
    }

    function boardError(msg){
      document.getElementById('mdlBoard').innerHTML =
        '<div class="mdl-empty">Could not reach the models API: ' + esc(msg) + '</div>';
    }

    function renderFams(){
      var box = document.getElementById('mdlFams');
      var fams = (meta.families || []);
      box.innerHTML = fams.map(function(f){
        var on = (meta.active || {})[f];
        return '<button class="mdl-fam' + (f === famSel ? ' on' : '') + '" data-fam="' + esc(f) + '">' +
               esc(f.toUpperCase()) + (on ? '<span class="mdl-fam-dot" title="a model is live on this family"></span>' : '') +
               '</button>';
      }).join('');
      var sel = document.getElementById('mdlNewFamily');
      if (sel && !sel.options.length){
        sel.innerHTML = fams.map(function(f){
          return '<option value="' + esc(f) + '">' + esc(f.toUpperCase()) + '</option>';
        }).join('');
      }
    }

    function renderActive(){
      var el = document.getElementById('mdlActive');
      var id = (meta.active || {})[famSel];
      if (!id){ el.innerHTML = esc(famSel.toUpperCase()) + ': stock base (no LoRA)'; return; }
      var m = models.filter(function(x){ return x.model_id === id; })[0];
      el.innerHTML = esc(famSel.toUpperCase()) + ': <b>' + esc(m ? m.name : id) + '</b>';
    }

    function renderBoard(){
      var mine = models.filter(function(m){ return m.family === famSel; });
      document.getElementById('mdlBoard').innerHTML = LANES.map(function(L){
        var key = L[0];
        var cards = mine.filter(function(m){ return m.lane === key; });
        return '<div class="mdl-lane lane-' + key + '">' +
          '<div class="mdl-lane-head"><h4>' + esc(L[1]) + '</h4><span>' + cards.length + '</span></div>' +
          '<div class="mdl-lane-body">' +
          (cards.length ? cards.map(card).join('')
                        : '<div class="mdl-empty">' + esc(L[2]) + '</div>') +
          '</div></div>';
      }).join('');
    }

    function card(m){
      var t = m.training || {};
      var pct = (t.pct != null && !t.done) ? Math.round(t.pct) : 0;
      var badges = '';
      if (!m.attested) badges += '<span class="mdl-badge age">no ' + (meta.min_age||18) + '+ attestation</span>';
      if (m.trained) badges += '<span class="mdl-badge ok">adapter</span>';
      if (m.active) badges += '<span class="mdl-badge ok">LIVE</span>';
      if (t.failed) badges += '<span class="mdl-badge warn">failed</span>';
      return '<div class="mdl-card" data-id="' + esc(m.model_id) + '">' +
        '<h5>' + esc(m.name) + '</h5>' +
        '<div class="mdl-meta"><span>' + m.images + ' imgs</span>' +
        '<span>scale ' + esc(m.scale) + '</span>' + badges + '</div>' +
        (m.lane === 'training'
          ? '<div class="mdl-bar"><i style="width:' + pct + '%"></i></div>' +
            '<div class="mdl-meta" style="margin-top:4px">step ' + (t.step||0) + '/' + (t.total_steps||0) + '</div>'
          : '') +
        phaseLine(m) +
        (m.sample && m.sample.lora
          ? '<img class="mdl-card-thumb" loading="lazy" src="' + sampleUrl(m, m.sample.lora) + '">' : '') +
        '</div>';
    }

    function sampleUrl(m, name){
      return '/api/medusa/models/' + encodeURIComponent(m.model_id) + '/sample/' + encodeURIComponent(name);
    }
    // One line saying what the background chain is doing right now. The chain
    // lives on the server, so this is the only place captioning/sampling shows.
    function phaseLine(m){
      var ph = m.phase || {};
      var p = ph.phase || '';
      if (p === 'captioning') return '<div class="mdl-phase">Captioning ' + (ph.done||0) + '/' + (ph.total||0) + '</div>';
      if (p === 'waiting') return '<div class="mdl-phase">Waiting for Vicky to finish a reply</div>';
      if (p === 'freeing' || p === 'starting') return '<div class="mdl-phase">Starting training…</div>';
      if (p === 'sampling') return '<div class="mdl-phase">Rendering sample…</div>';
      if (m.awaiting_sample && m.lane !== 'training') return '<div class="mdl-phase">Sample queued</div>';
      if (p === 'failed') return '<div class="mdl-phase err">Failed: ' + esc(ph.error || '') + '</div>';
      if (m.train_error) return '<div class="mdl-phase err">Training failed: ' + esc(m.train_error) + '</div>';
      if (m.sample && m.sample.error) return '<div class="mdl-phase err">Sample failed</div>';
      return '';
    }

    // ── detail modal ──
    function openDetail(id){ openId = id; document.getElementById('mdlModal').hidden = false; renderDetail(); }
    function closeDetail(){ openId = ''; document.getElementById('mdlModal').hidden = true; }

    function renderDetail(){
      var m = models.filter(function(x){ return x.model_id === openId; })[0];
      if (!m){ closeDetail(); return; }
      document.getElementById('mdlDetailName').textContent = m.name + '  ·  ' + m.family.toUpperCase();
      var att = m.age_attestation || null;
      var minAge = meta.min_age || 18;
      var body = '';

      if (m.trained || m.sample){
        var sm = m.sample || {};
        var busy = (m.phase || {}).phase === 'sampling';
        body += '<div class="mdl-sec"><h6>Sample' + (m.active ? ' — live on ' + esc(m.family.toUpperCase()) : '') + '</h6>';
        if (busy){
          body += '<p class="mdl-note">Rendering the sample pair (about 2–4 minutes)…</p>';
        } else if (sm.lora){
          body += '<div class="mdl-pair">' +
            '<figure class="main"><a href="' + sampleUrl(m, sm.lora) + '" target="_blank"><img src="' + sampleUrl(m, sm.lora) + '"></a>' +
            '<figcaption>With this model (strength ' + esc(m.scale) + ')</figcaption></figure>' +
            (sm.base ? '<figure><a href="' + sampleUrl(m, sm.base) + '" target="_blank"><img src="' + sampleUrl(m, sm.base) + '"></a>' +
              '<figcaption>Stock base — same prompt, same seed</figcaption></figure>' : '') +
            '</div>' +
            '<p class="mdl-note">Prompt (from a training caption): ' + esc(sm.prompt || '') + ' · seed ' + esc(sm.seed) + '</p>';
        } else if (sm.error){
          body += '<p class="mdl-note" style="color:#fca5a5">Sample failed: ' + esc(sm.error) + '</p>';
        } else if (m.awaiting_sample){
          body += '<p class="mdl-note">A sample renders automatically when training finishes.</p>';
        }
        body += '<div class="mdl-row" style="margin-top:8px">' +
          '<input type="text" id="mdlSamplePrompt" placeholder="Custom prompt (blank = a random training caption)" value="' +
          esc(m.sample_prompt || '') + '" style="flex:1">' +
          '<button class="btn-appr" id="mdlResample"' + (busy || !m.trained ? ' disabled' : '') + '>Render new sample</button>' +
          '</div></div>';
      }

      body += '<div class="mdl-sec"><h6>Adults only — required</h6>' +
        '<div class="mdl-age-box' + (att ? ' done' : '') + '">' +
        (att
          ? '<div style="font-size:12px;line-height:1.6">Attested ' + esc(att.attested_at) +
            ' by ' + esc(att.attested_by) + ' (' + esc(att.min_age) + '+).' +
            (att.note ? '<br>Note: ' + esc(att.note) : '') +
            '<br><button class="btn-decl" id="mdlRevoke" style="margin-top:8px">Revoke</button></div>'
          : '<label><input type="checkbox" id="mdlAttChk">' +
            '<span>I confirm every person depicted in this dataset is ' + minAge + ' or older, ' +
            'and that I am entitled to use these images for training.</span></label>' +
            '<div class="mdl-row" style="margin-top:8px">' +
            '<input type="text" id="mdlAttNote" placeholder="Source / licence note (optional)" style="flex:1">' +
            '<button class="btn-appr" id="mdlAttest">Record attestation</button></div>') +
        '</div></div>';

      body += '<div class="mdl-sec"><h6>Dataset — ' + m.images + ' images</h6>' +
        '<div class="mdl-row">' +
        '<input type="file" id="mdlFiles" multiple accept=".png,.jpg,.jpeg,.webp">' +
        '<button class="btn-appr" id="mdlUpload">Upload</button></div>' +
        '<div class="mdl-row" style="margin-top:8px">' +
        '<input type="text" id="mdlFolder" placeholder="Folder to import (relative to the resources root)" style="flex:1">' +
        '<button class="btn-appr" id="mdlFolderPreview">Preview</button>' +
        '<button class="btn-appr" id="mdlFolderImport">Import folder</button></div>' +
        '<div style="margin-top:8px"><textarea id="mdlUrls" placeholder="One link per line. Direct image URLs, or a .txt / .csv whose cells hold image URLs."></textarea>' +
        '<div class="mdl-row" style="margin-top:6px"><button class="btn-appr" id="mdlIngestUrls">Fetch links</button>' +
        '<span class="mdl-note">Each stored file records its source URL in provenance.jsonl.</span></div></div>' +
        '<div class="mdl-thumbs" id="mdlThumbs" style="margin-top:10px"></div></div>';

      body += '<div class="mdl-sec"><h6>Train</h6><div class="mdl-row">' +
        '<input type="number" id="mdlSteps" placeholder="steps (blank = auto)" min="0" step="50" style="width:180px">' +
        '<button class="btn-appr" id="mdlTrain"' + (m.can_train ? '' : ' disabled') + '>Start training</button>' +
        (m.trained && !m.active ? '<button class="btn-appr" id="mdlActivate">Switch on for ' + esc(m.family.toUpperCase()) + '</button>' : '') +
        (m.active ? '<button class="btn-decl" id="mdlDeactivate">Switch off</button>' : '') +
        '</div>' +
        (m.blockers && m.blockers.length
          ? '<p class="mdl-note">Blocked: ' + m.blockers.map(esc).join(' · ') + '</p>' : '') +
        (m.adapter ? '<p class="mdl-note">Adapter: <code>' + esc(m.adapter) + '</code></p>' : '') +
        '</div>';

      body += '<div class="mdl-sec"><h6>Settings</h6><div class="mdl-row">' +
        '<input type="text" id="mdlName" value="' + esc(m.name) + '" style="flex:1 1 260px">' +
        '<input type="number" id="mdlScale" value="' + esc(m.scale) + '" min="0" max="2" step="0.05" style="width:100px" title="LoRA strength">' +
        '<button class="btn-appr" id="mdlSave">Save</button>' +
        '<button class="btn-decl" id="mdlPark">' + (m.parked ? 'Unpark' : 'Park') + '</button>' +
        '<button class="btn-decl" id="mdlDelete">Delete</button></div>' +
        '<div class="mdl-row" style="margin-top:8px">' +
        '<input type="text" id="mdlPrefix" value="' + esc(m.caption_prefix || '') + '" ' +
        'placeholder="Caption prefix — words put at the front of EVERY training caption" style="flex:1">' +
        '<button class="btn-appr" id="mdlSavePrefix">Save prefix</button>' +
        '<button class="btn-decl" id="mdlRecaption">Re-caption on next training</button></div>' +
        (m.captions ? '<p class="mdl-note">Last captioning: ' + (m.captions.written||0) + ' written, ' +
          (m.captions.fallback||0) + ' fell back to the prefix (model refused or returned nothing), ' +
          (m.captions.flagged||0) + ' replaced by the age check. Hover a thumbnail to read its caption.</p>' : '') +
        (m.captions && m.captions.flagged_files && m.captions.flagged_files.length
          ? '<p class="mdl-note" style="color:#fca5a5">Check these images — the caption model described them as a minor: ' +
            m.captions.flagged_files.map(function(f){
              return '<a target="_blank" href="/api/medusa/models/' + encodeURIComponent(m.model_id) + '/images/' +
                     encodeURIComponent(f.file) + '">' + esc(f.file) + '</a> (&ldquo;' + esc(f.said) + '&rdquo;)';
            }).join(', ') + '</p>' : '') +
        '</div>';

      body += '<div class="mdl-status" id="mdlStatus"></div>';
      document.getElementById('mdlDetailBody').innerHTML = body;
      loadThumbs(m.model_id);
    }

    function say(msg, cls){
      var el = document.getElementById('mdlStatus');
      if (el){ el.textContent = msg; el.className = 'mdl-status ' + (cls || ''); }
    }

    function loadThumbs(id){
      fetch('/api/medusa/models/' + encodeURIComponent(id) + '/images?per=60')
        .then(function(r){ return r.json(); })
        .then(function(d){
          var box = document.getElementById('mdlThumbs');
          if (!box) return;
          var caps = d.captions || {};
          box.innerHTML = (d.images || []).map(function(n){
            return '<img loading="lazy" src="/api/medusa/models/' + encodeURIComponent(id) +
                   '/images/' + encodeURIComponent(n) + '" title="' + esc(caps[n] || 'not captioned yet') + '">';
          }).join('');
        }).catch(function(){});
    }

    // ── events (delegated: the board and modal are re-rendered constantly) ──
    document.getElementById('mdlFams').addEventListener('click', function(e){
      var b = e.target.closest('.mdl-fam'); if (!b) return;
      famSel = b.getAttribute('data-fam'); renderFams(); renderBoard(); renderActive();
    });
    document.getElementById('mdlBoard').addEventListener('click', function(e){
      var c = e.target.closest('.mdl-card'); if (!c) return;
      openDetail(c.getAttribute('data-id'));
    });
    document.getElementById('mdlDetailClose').addEventListener('click', closeDetail);
    document.getElementById('mdlModal').addEventListener('click', function(e){
      if (e.target === this) closeDetail();
    });
    document.getElementById('mdlNewBtn').addEventListener('click', function(){
      var n = document.getElementById('mdlNew');
      n.hidden = !n.hidden;
      if (!n.hidden) document.getElementById('mdlNewFamily').value = famSel;
    });
    document.getElementById('mdlNewCancel').addEventListener('click', function(){
      document.getElementById('mdlNew').hidden = true;
    });
    document.getElementById('mdlNewCreate').addEventListener('click', function(){
      var name = document.getElementById('mdlNewName').value.trim();
      if (!name){ alert('Name the model first.'); return; }
      api('POST', '', {
        name: name,
        family: document.getElementById('mdlNewFamily').value,
        scale: parseFloat(document.getElementById('mdlNewScale').value) || 0.85
      }).then(function(){
        document.getElementById('mdlNewName').value = '';
        document.getElementById('mdlNew').hidden = true;
        return load();
      }).catch(function(e){ alert(e.message); });
    });

    document.getElementById('mdlDetailBody').addEventListener('click', function(e){
      var id = openId; if (!id) return;
      var t = e.target;
      if (t.id === 'mdlAttest'){
        if (!document.getElementById('mdlAttChk').checked){
          say('Tick the confirmation box first.', 'err'); return;
        }
        api('POST', '/' + id + '/attest', {
          confirm: true, note: document.getElementById('mdlAttNote').value
        }).then(load).catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlRevoke'){
        api('POST', '/' + id + '/attest', {confirm: true, revoke: true})
          .then(load).catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlUpload'){
        var f = document.getElementById('mdlFiles').files;
        if (!f.length){ say('Pick files first.', 'err'); return; }
        var fd = new FormData();
        for (var i = 0; i < f.length; i++) fd.append('files', f[i]);
        say('Uploading ' + f.length + '…');
        fetch('/api/medusa/models/' + encodeURIComponent(id) + '/images', {method:'POST', body: fd})
          .then(function(r){ return r.json(); })
          .then(function(d){
            if (d.error) throw new Error(d.error);
            say('Added ' + d.added + ', ' + d.duplicates + ' duplicates' +
                (d.errors && d.errors.length ? ', ' + d.errors.length + ' errors' : ''), 'ok');
            return load();
          }).catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlFolderPreview' || t.id === 'mdlFolderImport'){
        var prev = (t.id === 'mdlFolderPreview');
        say(prev ? 'Scanning…' : 'Importing…');
        api('POST', '/' + id + '/ingest/folder', {
          path: document.getElementById('mdlFolder').value, preview: prev
        }).then(function(d){
          say(prev ? ('Found ' + d.found + ' images')
                   : ('Added ' + d.added + ', ' + d.duplicates + ' duplicates, of ' + d.found + ' found'), 'ok');
          if (!prev) return load();
        }).catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlIngestUrls'){
        var urls = document.getElementById('mdlUrls').value.trim();
        if (!urls){ say('Paste some links first.', 'err'); return; }
        say('Fetching…');
        api('POST', '/' + id + '/ingest/urls', {urls: urls}).then(function(d){
          say('Added ' + d.added + ' of ' + d.attempted + ' attempted, ' + d.duplicates +
              ' duplicates' + (d.errors && d.errors.length ? '. First error: ' + d.errors[0] : ''),
              d.added ? 'ok' : 'err');
          return load();
        }).catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlTrain'){
        var st = parseInt(document.getElementById('mdlSteps').value, 10);
        say('Starting…');
        api('POST', '/' + id + '/train', st > 0 ? {steps: st} : {})
          .then(function(){ say('Training started.', 'ok'); return load(); })
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlActivate'){
        api('POST', '/' + id + '/activate', {})
          .then(function(){ say('Switched on.', 'ok'); return load(); })
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlDeactivate'){
        api('POST', '/' + id + '/deactivate', {}).then(load)
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlSave'){
        api('PATCH', '/' + id, {
          name: document.getElementById('mdlName').value,
          scale: parseFloat(document.getElementById('mdlScale').value)
        }).then(function(){ say('Saved.', 'ok'); return load(); })
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlPark'){
        var m = models.filter(function(x){ return x.model_id === id; })[0];
        api('PATCH', '/' + id, {parked: !(m && m.parked)}).then(load)
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlResample'){
        say('Rendering…');
        api('POST', '/' + id + '/sample', {prompt: document.getElementById('mdlSamplePrompt').value.trim()})
          .then(function(){ say('Sample rendering — it appears here when done.', 'ok'); return load(); })
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlSavePrefix'){
        api('PATCH', '/' + id, {caption_prefix: document.getElementById('mdlPrefix').value})
          .then(function(){ say('Prefix saved. It applies to captions written from now on.', 'ok'); return load(); })
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlRecaption'){
        if (!confirm("Delete this dataset's captions? They are rewritten automatically on the next training run.")) return;
        api('POST', '/' + id + '/captions/reset', {})
          .then(function(d){ say('Removed ' + d.removed + ' captions.', 'ok'); return load(); })
          .catch(function(err){ say(err.message, 'err'); });
      } else if (t.id === 'mdlDelete'){
        if (!confirm('Delete this model, its dataset and its adapters? This cannot be undone.')) return;
        api('DELETE', '/' + id).then(function(){ closeDetail(); return load(); })
          .catch(function(err){ say(err.message, 'err'); });
      }
    });

    // Poll only while the tab is visible AND something is training — a board
    // nobody is looking at should not wake the crews API every few seconds.
    var tabBtn = document.querySelector('.tab[data-tab="tab5"]');
    function visible(){
      var p = document.querySelector('.panel[data-panel="tab5"]');
      return p && p.classList.contains('active');
    }
    function tick(){
      if (!visible()) return;
      if (models.some(function(m){
            var p = (m.phase || {}).phase;
            return m.lane === 'training' || m.awaiting_sample || p === 'sampling';
          })) load();
    }
    if (tabBtn){
      tabBtn.addEventListener('click', function(){
        load();
        if (!pollTimer) pollTimer = setInterval(tick, 5000);
      });
    }
  })();
</script>
"""
