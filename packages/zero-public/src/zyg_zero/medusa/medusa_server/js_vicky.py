# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI script, part 5: Vicky, the chat assistant panel.

Moved verbatim out of medusa_server.py (lines 2905-3475); reassembled in html.py.
"""

JS_VICKY = """  // ── Vicky: Medusa's own chat assistant ──────────────────────────────────
  // The transcript and the CLI session id both live on the SERVER (see the
  // chat store in medusa_vicky.py), not in this closure — so a refresh, a
  // second browser tab, or a medusa.service restart reopens the conversation
  // where it was instead of starting Vicky over as a stranger.
  (function(){
    var log = document.getElementById('v_log');
    var input = document.getElementById('v_input');
    var sendBtn = document.getElementById('v_send');
    var cancelBtn = document.getElementById('v_cancel');
    var attachBtn = document.getElementById('v_attach');
    var fileInput = document.getElementById('v_file');
    var previewsEl = document.getElementById('v_previews');
    var sel = document.getElementById('v_chats');
    var engineSel = document.getElementById('v_engine');
    var metaEl = document.getElementById('v_meta');
    if (!log) return;
    var jobId = null, pollTimer = null, liveEl = null, chatId = null;
    // ENGINES is the server's list, not a hard-coded pair: /api/vicky/engines
    // reports each one's live availability, so an assistant that cannot answer
    // right now is labelled in the dropdown instead of silently offered.
    var ENGINES = [], engine = 'claude';
    // pendingAtts: [{type:'image', name, mime_type, data_b64, dataUrl}
    //            | {type:'video', name, path, uploading?}]
    var pendingAtts = [];

    function nl(t){ return secEsc(t).replace(/\\n/g, '<br>'); }

    // ── attachment previews ──────────────────────────────────────────────
    function renderPreviews(){
      previewsEl.innerHTML = '';
      pendingAtts.forEach(function(att, i){
        var item = document.createElement('div');
        item.className = 'vp-item';
        if(att.type === 'image' && att.dataUrl){
          var img = document.createElement('img');
          img.className = 'vp-img'; img.src = att.dataUrl; img.title = att.name;
          item.appendChild(img);
        } else {
          var pill = document.createElement('div');
          pill.className = 'vp-pill';
          pill.textContent = (att.type === 'video' ? '\\uD83C\\uDFA6 ' : '\\uD83D\\uDCC4 ') +
                             att.name + (att.uploading ? ' (uploading…)' : '');
          item.appendChild(pill);
        }
        var rm = document.createElement('button');
        rm.className = 'vp-remove'; rm.textContent = '\u00d7'; rm.title = 'Remove';
        rm.addEventListener('click', (function(idx){
          return function(){ pendingAtts.splice(idx, 1); renderPreviews(); };
        })(i));
        item.appendChild(rm);
        previewsEl.appendChild(item);
      });
    }

    // ── the model switcher ─────────────────────────────
    function engineRow(id){
      for (var i = 0; i < ENGINES.length; i++){ if (ENGINES[i].id === id) return ENGINES[i]; }
      return null;
    }
    function engineName(id){
      var e = engineRow(id);
      return e ? e.name : (id === 'ollama' ? 'Victor' : 'Vicky');
    }
    function renderEngines(){
      if (!engineSel) return;
      // A switched-off engine (Sonnet, since 2026-09-17) stays in the list as a
      // DISABLED option rather than disappearing. Removing it would leave every
      // chat that was held on it looking like it belonged to an engine that had
      // never existed; showing it greyed says "this exists and is off", which is
      // the thing the operator actually needs to know. Note `enabled` and
      // `available` are different facts: off by choice vs. cannot answer now.
      engineSel.innerHTML = ENGINES.map(function(e){
        var note = (e.enabled === false) ? '  (off)' : (e.available ? '' : '  (offline)');
        return '<option value="' + secEsc(e.id) + '"' +
               (e.id === engine ? ' selected' : '') +
               (e.enabled === false ? ' disabled' : '') + '>' +
               secEsc(e.label) + note + '</option>';
      }).join('');
      engineSel.value = engine;
      var cur = engineRow(engine);
      engineSel.classList.toggle('offline', !!(cur && !cur.available));
      engineSel.title = cur ? (cur.name + ' \u00b7 ' + (cur.model || '?') + ' \u00b7 ' + cur.where +
                               (cur.available ? '' : ' \u2014 ' + (cur.detail || 'not available')))
                            : 'Which assistant answers';
    }
    function loadEngines(){
      return fetch('/api/vicky/engines').then(function(r){ return r.json(); })
        .then(function(d){
          if (!d.ok) return;
          ENGINES = d.engines || [];
          renderEngines();
        })
        .catch(function(){});
    }

    // ── message bubbles ──────────────────────────────────────────────────
    // The store has written a 'ts' on every message since the chat store was
    // built; until 2026-09-17 the panel simply never drew it, so a transcript
    // gave no clue whether an answer was a minute or a week old.  Server
    // timestamps are local wall-clock with no zone ('2026-09-17T20:11:27'),
    // which is exactly what Date() reads them as - do NOT append a Z.
    function fmtTime(ts){
      var d = (ts instanceof Date) ? ts : new Date(String(ts || '').trim());
      if (!d || isNaN(d.getTime())) return '';
      var hh = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
      // A chat that spans days needs the day too, or 09:14 is ambiguous.
      if (d.toDateString() === new Date().toDateString()) return hh;
      var MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      return d.getDate() + ' ' + MON[d.getMonth()] + ' ' + hh;
    }
    function timeTitle(ts){
      var d = (ts instanceof Date) ? ts : new Date(String(ts || '').trim());
      if (!d || isNaN(d.getTime())) return '';
      return d.toLocaleString();
    }
    // A picture Vicky rendered, drawn in her own bubble. `images` is written by
    // the server (medusa_vicky._chat_record_turn) from what the tool actually
    // produced - never from anything the model said - so a thumbnail here means
    // a file exists on disk.
    function shotsHtml(images){
      if (!images || !images.length) return '';
      return '<div class="msg-shots">' + images.map(function(im){
        var url = im.url || ('/api/vicky/image?path=' + encodeURIComponent(im.path || ''));
        return '<div><a href="' + secEsc(url) + '" target="_blank" rel="noopener">' +
               '<img class="msg-shot" src="' + secEsc(url) + '" alt="' + secEsc(im.name || 'render') +
               '" title="' + secEsc(im.path || '') + '"></a>' +
               '<div class="msg-shot-cap">' + secEsc(im.name || '') + '</div></div>';
      }).join('') + '</div>';
    }
    function addMsg(cls, text, meta, atts, who, ts, images){
      var el = document.createElement('div');
      // Two assistants share this transcript, so an answer bubble that does not
      // say who gave it is ambiguous the moment the operator switches engine.
      el.className = 'vicky-msg ' + cls + (who === 'ollama' ? ' local' : '');
      var html = '';
      var whoTxt = (cls === 'vicky' || (cls === 'error' && who)) ? engineName(who || engine) : '';
      var t = fmtTime(ts || new Date());
      html += '<div class="vicky-head"><span class="vicky-who">' + secEsc(whoTxt) + '</span>' +
              '<span class="vicky-time" title="' + secEsc(timeTitle(ts || new Date())) + '">' +
              secEsc(t) + '</span></div>';
      if(atts && atts.length && cls === 'user'){
        // Show image thumbnails and video/file pills inline in the user bubble.
        // On reload these won't re-appear (base64 is never stored in the chat
        // JSON) but the text itself records what was sent.
        html += '<div class="msg-thumbs">';
        atts.forEach(function(a){
          if(a.type === 'image' && a.dataUrl){
            html += '<img class="msg-thumb" src="' + secEsc(a.dataUrl) +
                    '" title="' + secEsc(a.name) + '">';
          } else {
            html += '<span class="msg-pill">' +
                    secEsc((a.type === 'video' ? '\\uD83C\\uDFA6 ' : '\\uD83D\\uDCC4 ') + a.name) +
                    '</span>';
          }
        });
        html += '</div>';
      }
      html += nl(text) + shotsHtml(images) +
              (meta ? '<div class="vicky-meta">' + secEsc(meta) + '</div>' : '');
      el.innerHTML = html;
      // A live bubble is redrawn on every poll; keep its birth time on the node
      // so those redraws do not restamp it with the time of the last poll.
      el._ts = ts || new Date();
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
      return el;
    }

    function msgMeta(m){
      var bits = [];
      if (m.model) bits.push(m.model);
      if (m.elapsed) bits.push(m.elapsed + 's');
      if (m.think_s) bits.push(m.think_s + 's thinking');
      // Victor's cost is a real 0, not a missing number - say 'local' rather
      // than leave a blank where Vicky shows a dollar figure.
      if (m.usage && m.usage.cost_usd) bits.push('$' + m.usage.cost_usd);
      else if (m.engine === 'ollama') bits.push('local, no cost');
      return bits.join(' · ');
    }

    function renderChat(chat){
      chatId = chat.id;
      // The engine lives on the chat, not in this closure - reopening a
      // conversation has to reopen the assistant that has its memory.
      if (chat.engine){ engine = chat.engine; renderEngines(); }
      log.innerHTML = '';
      var msgs = chat.messages || [];
      if (!msgs.length){
        var e = document.createElement('div');
        e.className = 'vicky-empty';
        e.textContent = 'New chat with ' + engineName(engine) +
                        '. Ask for something to be built or changed in Medusa.';
        log.appendChild(e);
      }
      if (chat.trimmed){
        var t = document.createElement('div');
        t.className = 'vicky-empty';
        t.textContent = 'Older messages in this chat were trimmed from the transcript.';
        log.appendChild(t);
      }
      msgs.forEach(function(m){
        addMsg(m.role === 'user' ? 'user' : (m.role === 'error' ? 'error' : 'vicky'),
               m.text || '', m.role === 'vicky' ? msgMeta(m) : '', null, m.engine,
               m.ts, m.images);
      });
      // The two engines remember different halves of a chat, so the meta line
      // says what the CURRENT one actually has: Vicky needs a CLI session id,
      // Victor replays the messages themselves and needs no session at all.
      var mem;
      if (engine === 'ollama'){
        mem = msgs.length ? ' · Victor reads this transcript back each turn'
                          : ' · nothing to remember yet';
      } else {
        mem = chat.session ? ' · Vicky remembers this one' : ' · no memory yet';
      }
      metaEl.textContent = (msgs.length ? msgs.length + ' message' + (msgs.length === 1 ? '' : 's') : 'empty') + mem;
      log.scrollTop = log.scrollHeight;
    }

    function renderList(d){
      var chats = d.chats || [];
      sel.innerHTML = chats.map(function(c){
        var when = String(c.updated || c.created || '').replace('T', ' ').slice(5, 16);
        return '<option value="' + secEsc(c.id) + '"' + (c.id === chatId ? ' selected' : '') + '>' +
               secEsc(c.title) + '  ·  ' + secEsc(when) + '  ·  ' + c.messages + '</option>';
      }).join('') || '<option value="">(no saved chats)</option>';
    }

    function loadList(){
      return fetch('/api/vicky/chats').then(function(r){ return r.json(); })
        .then(function(d){ if (d.ok) renderList(d); return d; })
        .catch(function(){});
    }

    function loadChat(id){
      return fetch('/api/vicky/chat' + (id ? '?id=' + encodeURIComponent(id) : ''))
        .then(function(r){ return r.json(); })
        .then(function(d){
          if (!d.ok) return;
          renderChat(d.chat);
          if (d.running && d.running.id){
            // A turn was still running when the page reloaded — reattach to it
            // rather than showing a chat that looks finished but is not.
            jobId = d.running.id;
            // Stamp the bubble with when the turn STARTED, not when this reload
            // happened - the job reports how long it has been going.
            liveEl = addMsg('vicky', 'Working\u2026', '', null, d.running.engine || engine,
                            new Date(Date.now() - (d.running.elapsed || 0) * 1000));
            setBusy(true);
            pollTimer = setTimeout(poll, 700);
          }
          return loadList();
        })
        .catch(function(){});
    }

    function setBusy(busy){
      sendBtn.disabled = busy;
      cancelBtn.style.display = busy ? 'inline-block' : 'none';
      if(attachBtn) attachBtn.disabled = busy;
    }

    function headHtml(el, whoTxt){
      var ts = (el && el._ts) || new Date();
      return '<div class="vicky-head"><span class="vicky-who">' + secEsc(whoTxt) + '</span>' +
             '<span class="vicky-time" title="' + secEsc(timeTitle(ts)) + '">' +
             secEsc(fmtTime(ts)) + '</span></div>';
    }

    function renderLive(job){
      if (!liveEl) return;
      var who = headHtml(liveEl, engineName(job.engine || engine) +
                                 (job.model ? ' \u00b7 ' + job.model : ''));
      var think = job.thinking ? '<div class="vicky-think">' + secEsc(job.thinking) + '\u2026</div>' : '';
      var body = job.reply_live || job.reply || (job.status === 'running' ? 'Working\u2026' : '');
      // Pictures appear the moment the render tool returns them, not when the
      // model finally stops talking about them.
      liveEl.innerHTML = who + think + nl(body) + shotsHtml(job.images);
      log.scrollTop = log.scrollHeight;
    }

    function poll(){
      fetch('/api/vicky/job?id=' + encodeURIComponent(jobId))
        .then(function(r){ return r.json(); })
        .then(function(job){
          if (!job.ok){ finish('error', job.error || 'lost track of this job'); return; }
          renderLive(job);
          if (job.status === 'done'){
            finish('vicky', job.reply || 'Done.', job.images);
          } else if (job.status === 'error'){
            finish('error', job.error || (engineName(job.engine || engine) + ' hit an error'),
                   job.images);
          } else {
            pollTimer = setTimeout(poll, 1000);
          }
        })
        .catch(function(){ pollTimer = setTimeout(poll, 2000); });
    }

    function finish(cls, text, images){
      if (liveEl){
        liveEl.className = 'vicky-msg ' + cls + (engine === 'ollama' ? ' local' : '');
        liveEl.innerHTML = headHtml(liveEl, engineName(engine)) + nl(text) + shotsHtml(images);
      }
      liveEl = null; jobId = null;
      setBusy(false);
      log.scrollTop = log.scrollHeight;
      // The server wrote this turn into the chat; refresh the meta/list from it.
      loadChat(chatId);
    }

    function send(){
      var text = (input.value || '').trim();
      var atts = pendingAtts.slice();
      // Block send if a video is still uploading
      if(atts.some(function(a){ return a.uploading; })){
        alert('Please wait — a video is still uploading.'); return;
      }
      if((!text && !atts.length) || jobId) return;
      // If no text but there are attachments, synthesise a placeholder so the
      // ledger and chat store have something to record.
      if(!text) text = atts.map(function(a){ return '[' + a.name + ']'; }).join(' ');
      pendingAtts = []; renderPreviews();
      var empty = log.querySelector('.vicky-empty');
      if (empty) empty.remove();
      addMsg('user', text, '', atts);
      input.value = '';
      liveEl = addMsg('vicky', 'Working\u2026', '', null, engine);
      setBusy(true);
      // Build sanitised attachment payload: image data stays as base64,
      // video is the server-side path returned by /api/vicky/upload.
      var attPayload = atts.map(function(a){
        if(a.type === 'image') return {type:'image', name:a.name, mime_type:a.mime_type, data_b64:a.data_b64};
        return {type:'video', name:a.name, path:a.path};
      });
      fetch('/api/vicky/start', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text, chat: chatId, engine: engine, attachments: attPayload})
      })
        .then(function(r){ return r.json(); })
        .then(function(d){
          if (!d.ok){ finish('error', d.error || 'could not start'); return; }
          jobId = d.id;
          chatId = d.chat || chatId;
          if (d.engine) engine = d.engine;
          pollTimer = setTimeout(poll, 700);
        })
        .catch(function(){ finish('error', 'could not reach Medusa'); });
    }

    // ── file attachment handling ─────────────────────────────────────────
    // One ingest path for every way a file can arrive. The accept= filter only
    // constrains the picker, so the type check has to live here - the
    // clipboard will hand us anything that was copied.
    function addAttachFiles(files){
      Array.prototype.slice.call(files || []).forEach(function(f){
        var isImg = f.type.indexOf('image/') === 0;
        var isVid = f.type.indexOf('video/') === 0;
        if(!isImg && !isVid) return;
        // A pasted screenshot carries no name of its own - Chrome calls every
        // one of them 'image.png'. Stamp it, because the name is what the
        // operator reads back in the pill and what Vicky is told for a video.
        var name = f.name || '';
        if(!name || name === 'image.png' || name === 'blob'){
          name = 'pasted-' + new Date().toISOString().replace(/[:.]/g, '-') +
                 (isImg ? '.png' : '.mp4');
        }
        if(isImg){
          var reader = new FileReader();
          reader.onload = function(ev){
            var dataUrl = ev.target.result;
            var b64 = dataUrl.split(',')[1] || '';
            pendingAtts.push({type:'image', name:name, mime_type:f.type,
                              data_b64:b64, dataUrl:dataUrl});
            renderPreviews();
          };
          reader.readAsDataURL(f);
        } else {
          // Video: save to server immediately so Vicky gets a real file path.
          var placeholder = {type:'video', name:name, path:null, uploading:true};
          pendingAtts.push(placeholder);
          renderPreviews();
          var fd = new FormData();
          fd.append('file', f, name);
          fetch('/api/vicky/upload', {method:'POST', body:fd})
            .then(function(r){ return r.json(); })
            .then(function(d){
              placeholder.uploading = false;
              if(d.ok){ placeholder.path = d.path; }
              else { pendingAtts = pendingAtts.filter(function(a){ return a !== placeholder; }); }
              renderPreviews();
            })
            .catch(function(){
              placeholder.uploading = false;
              pendingAtts = pendingAtts.filter(function(a){ return a !== placeholder; });
              renderPreviews();
            });
        }
      });
    }

    if(attachBtn) attachBtn.addEventListener('click', function(){ fileInput.click(); });
    if(fileInput) fileInput.addEventListener('change', function(){
      addAttachFiles(fileInput.files);
      fileInput.value = '';   // reset so the same file can be picked again
    });

    // Paste. Only claim the event when the clipboard actually carries a file we
    // can use, so pasting ordinary text into the composer still behaves exactly
    // as before - a screenshot copied from the OS arrives as an items entry of
    // kind 'file', while copied text does not.
    if(input) input.addEventListener('paste', function(e){
      var dt = e.clipboardData || window.clipboardData;
      if(!dt) return;
      var found = [];
      if(dt.items && dt.items.length){
        Array.prototype.slice.call(dt.items).forEach(function(it){
          if(it.kind === 'file'){
            var f = it.getAsFile();
            if(f) found.push(f);
          }
        });
      } else if(dt.files && dt.files.length){
        found = Array.prototype.slice.call(dt.files);
      }
      var usable = found.filter(function(f){
        return f.type.indexOf('image/') === 0 || f.type.indexOf('video/') === 0;
      });
      if(!usable.length) return;      // plain text paste - leave it alone
      e.preventDefault();
      addAttachFiles(usable);
    });

    function chatPost(action, body){
      return fetch('/api/vicky/chat/' + action, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {})
      }).then(function(r){ return r.json(); });
    }

    function busyGuard(){
      if (jobId){ alert(engineName(engine) + ' is still working on this turn — cancel it first.'); return true; }
      return false;
    }

    sendBtn.addEventListener('click', send);
    cancelBtn.addEventListener('click', function(){
      if (!jobId) return;
      fetch('/api/vicky/cancel', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: jobId})
      }).catch(function(){});
    });
    input.addEventListener('keydown', function(e){
      if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
    });

    if (engineSel) engineSel.addEventListener('change', function(){
      // Mid-turn the switch would silently hand the running answer to the other
      // assistant's bubble, so it is refused rather than queued.
      if (jobId){
        alert(engineName(engine) + ' is still working on this turn — cancel it first.');
        engineSel.value = engine; return;
      }
      var want = engineSel.value;
      var row = engineRow(want);
      if (row && !row.available &&
          !confirm(row.name + ' is not available right now (' + (row.detail || 'offline') +
                   ').\\n\\nSwitch anyway?')){
        engineSel.value = engine; return;
      }
      engine = want;
      renderEngines();
      // Persist on the chat, not in this tab: the next reader has to reopen the
      // conversation on the assistant that holds its memory.
      if (chatId) chatPost('engine', {id: chatId, engine: engine}).then(function(d){
        if (d && d.ok && d.chat) renderChat(d.chat);
      }).then(loadList);
    });

    sel.addEventListener('change', function(){
      if (!sel.value) return;
      if (busyGuard()){ sel.value = chatId; return; }
      chatPost('open', {id: sel.value}).then(function(d){ if (d.ok) renderChat(d.chat); }).then(loadList);
    });
    document.getElementById('v_new').addEventListener('click', function(){
      if (busyGuard()) return;
      chatPost('new', {engine: engine}).then(function(d){ if (d.ok) renderChat(d.chat); }).then(loadList);
    });
    document.getElementById('v_rename').addEventListener('click', function(){
      var cur = sel.options[sel.selectedIndex];
      var name = prompt('Name this chat:', (cur ? cur.textContent.split('  \u00b7  ')[0] : '') || '');
      if (name === null) return;
      chatPost('rename', {id: chatId, title: name}).then(loadList);
    });
    document.getElementById('v_save').addEventListener('click', function(){
      if (!chatId) return;
      window.location = '/api/vicky/chat/export?format=md&id=' + encodeURIComponent(chatId);
    });
    document.getElementById('v_del').addEventListener('click', function(){
      if (busyGuard() || !chatId) return;
      if (!confirm('Delete this chat? The transcript is gone for good (the dated audit ledger is kept).')) return;
      chatPost('delete', {id: chatId}).then(function(d){ if (d.ok) renderChat(d.chat); }).then(loadList);
    });
    document.getElementById('v_clear').addEventListener('click', function(){
      if (busyGuard()) return;
      if (!confirm('Delete EVERY saved chat? This cannot be undone. the dated audit ledger on disk is kept.')) return;
      chatPost('delete', {all: true}).then(function(d){ if (d.ok) renderChat(d.chat); }).then(loadList);
    });

    // ── Pictures gallery: every picture from every chat, one grid ──────────
    // Fed by /api/vicky/pictures, which walks the chat store on the server.
    // The transcript stays untouched underneath; the gallery just covers it
    // while it is open, and "Open chat" jumps to the conversation a picture
    // came from.
    var galleryEl = document.getElementById('v_gallery');
    var picsBtn = document.getElementById('v_pics');
    var galleryOpen = false;
    function picUrl(path){ return '/api/vicky/image?path=' + encodeURIComponent(path || ''); }
    function renderGallery(d){
      var pics = d.pictures || [];
      var head = '<div class="vicky-gallery-head"><b>' + pics.length + ' picture' + (pics.length === 1 ? '' : 's') +
                 '</b> made in chats, newest first' +
                 (d.missing ? ' &middot; <span style="color:#fca5a5">' + d.missing + ' no longer on disk</span>' : '') +
                 ' &middot; click a picture for the full size</div>';
      if (!pics.length){
        galleryEl.innerHTML = head + '<div class="vicky-empty">No chat has made a picture yet. Ask for one and it lands here.</div>';
        return;
      }
      galleryEl.innerHTML = head + '<div class="vicky-gallery-grid">' + pics.map(function(im){
        var when = String(im.ts || '').replace('T', ' ').slice(5, 16);
        var body = im.exists
          ? '<a class="pic" href="' + secEsc(picUrl(im.path)) + '" target="_blank" rel="noopener">' +
            '<img src="' + secEsc(picUrl(im.path)) + '" loading="lazy" alt="' + secEsc(im.name || '') +
            '" title="' + secEsc(im.path || '') + '"></a>'
          : '<a class="pic" title="' + secEsc(im.path || '') + '">file no longer on disk</a>';
        return '<div class="vicky-pic' + (im.exists ? '' : ' gone') + '">' + body +
               '<div class="cap"><span class="t">' + secEsc(im.chat_title || '') + '</span>' +
               (im.prompt ? '<span class="p">' + secEsc(im.prompt) + '</span>' : '') +
               '<div class="row">' +
               (im.chat ? '<button class="vchat-btn" data-open="' + secEsc(im.chat) + '">Open chat</button>' : '') +
               '<span class="when" title="' + secEsc(im.ts || '') + '">' + secEsc(when) + '</span></div></div></div>';
      }).join('') + '</div>';
    }
    function showGallery(on){
      galleryOpen = !!on;
      galleryEl.hidden = !galleryOpen;
      log.hidden = galleryOpen;
      picsBtn.classList.toggle('on', galleryOpen);
      galleryEl.parentElement.classList.toggle('wide', galleryOpen);
      if (!galleryOpen) return;
      galleryEl.innerHTML = '<div class="vicky-empty">Loading pictures\u2026</div>';
      fetch('/api/vicky/pictures').then(function(r){ return r.json(); })
        .then(function(d){ if (d.ok) renderGallery(d); else galleryEl.textContent = d.error || 'Could not list the pictures.'; })
        .catch(function(e){ galleryEl.textContent = 'Could not list the pictures: ' + e; });
    }
    picsBtn.addEventListener('click', function(){ showGallery(!galleryOpen); });
    galleryEl.addEventListener('click', function(ev){
      var b = ev.target.closest('button[data-open]');
      if (!b) return;
      showGallery(false);
      loadChat(b.getAttribute('data-open')).then(loadList);
    });
    // Sending a message or switching chats belongs to the transcript view.
    sel.addEventListener('change', function(){ if (galleryOpen) showGallery(false); });
    sendBtn.addEventListener('click', function(){ if (galleryOpen) showGallery(false); });

    loadEngines().then(function(){ return loadChat(''); });
  })();

"""
