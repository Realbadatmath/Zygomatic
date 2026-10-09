// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ══ Character Studio — Sheet / Checks / Voice actions ══════════════════════
   2026-09-18, task 12 of the four-studios wiring tree.

   Four dock tools were drawn with an `act:` key and nothing behind it:

     angles  -> act 'angleset'    the 48-cell angle grid
     handqc  -> act 'handqc'      hand boxes + the VLM CROP verdicts
     anachronism -> act 'anachronism'  the era gate against wardrobe.period
     audition -> act 'audition'   one line in this character's voice

   This file adds CST_ACT.angleset / handqc / anachronism / audition and
   nothing else. It is loaded by /studio_ext/bundle.js AFTER the page's own
   script block, so CST_ACT, CST, CS, cstPanelOpen, cstKv, imgUrl, withScope,
   api and esc all exist by the time it runs.

   Everything slow lives behind a press, never behind opening the panel:
   hand QC is a detector plus one VLM call per crop, and the era gate is ~40 s
   of Qwen3-VL on six tiles. So each of those two panels draws its plan first,
   with a button — pressing a tool must never be the thing that takes the GPU.

   The audition poll is the same shape as char_run.js's: one timer for the
   file, stopped when the panel changes, when the job leaves queued/running,
   and when the panel is closed.
*/

var CC = {
  timer: null,      /* the audition poll */
  job: '',
  panel: '',
  voice: '',
  meta: null,       /* the audition op's own reply, kept across polls */
};

function ccUrl(op, q) {
  var u = '/inspect/api/studio/char_checks/' + op, bits = [];
  Object.keys(q || {}).forEach(function (k) {
    if (q[k] === '' || q[k] === null || q[k] === undefined) return;
    bits.push(encodeURIComponent(k) + '=' + encodeURIComponent(q[k]));
  });
  return bits.length ? u + '?' + bits.join('&') : u;
}
function ccGet(op, q) {
  return fetch(ccUrl(op, q), {cache: 'no-cache'}).then(function (r) {
    return r.json().then(function (j) { j._code = r.status; return j; });
  });
}
function ccPost(op, body) {
  return fetch('/inspect/api/studio/char_checks/' + op,
               {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body || {})})
    .then(function (r) {
      return r.json().then(function (j) { j._code = r.status; return j; });
    });
}
function ccErr(id, title, j) {
  cstPanelOpen(id, title, '<div class="cst-warn">'
    + esc(j && (j.error || j.message) ? (j.error || j.message)
                                      : ('HTTP ' + ((j && j._code) || '?')))
    + '</div>'
    + ((j && j.log && j.log.length)
        ? '<pre class="cst-pre">' + esc(j.log.join('\n')) + '</pre>' : '')
    + '<div class="cst-hint">Nothing was written.</div>');
}
function ccWait(id, title, what) {
  cstPanelOpen(id, title,
    '<div class="cst-hint big">' + esc(what) + '</div>'
    + '<div class="cc-bar"><i></i></div>');
}
function ccChip(ok, txt) {
  return '<span class="cc-chip ' + (ok ? 'ok' : 'bad') + '">' + esc(txt) + '</span>';
}

/* one stylesheet for the four panels, injected once */
(function () {
  if (document.getElementById('cc-style')) return;
  var s = document.createElement('style');
  s.id = 'cc-style';
  s.textContent =
    '.cc-grid{display:grid;grid-template-columns:repeat(8,1fr);gap:4px;margin:8px 0}'
  + '.cc-cell{position:relative;aspect-ratio:4/5;border-radius:4px;overflow:hidden;'
  + 'border:1px solid var(--line);background:#0c0f14}'
  + '.cc-cell img{width:100%;height:100%;object-fit:cover;display:block}'
  + '.cc-cell.gap{border:1px dashed var(--warn);background:repeating-linear-gradient('
  + '45deg,transparent,transparent 4px,rgba(255,255,255,.05) 4px,rgba(255,255,255,.05) 8px)}'
  + '.cc-cell .n{position:absolute;left:2px;top:1px;font-size:.52rem;line-height:1.2;'
  + 'padding:0 3px;border-radius:3px;background:rgba(0,0,0,.66);color:#cfd6e0}'
  + '.cc-chip{display:inline-block;font-size:.62rem;padding:1px 7px;border-radius:9px;'
  + 'margin:0 4px 4px 0;border:1px solid currentColor}'
  + '.cc-chip.ok{color:var(--ok,#5fbf7f)}.cc-chip.bad{color:var(--bad,#e06a6a)}'
  + '.cc-hand{display:flex;gap:8px;align-items:flex-start;margin:8px 0;'
  + 'padding:7px;border:1px solid var(--line);border-radius:7px}'
  + '.cc-hand img{width:110px;border-radius:5px;display:block;flex:0 0 auto}'
  + '.cc-bar{height:3px;border-radius:2px;background:var(--line);overflow:hidden;margin:10px 0}'
  + '.cc-bar i{display:block;height:100%;width:34%;background:var(--accent,#6ea8fe);'
  + 'animation:cc-slide 1.15s ease-in-out infinite}'
  + '@keyframes cc-slide{0%{transform:translateX(-100%)}100%{transform:translateX(330%)}}'
  + '.cc-row{display:flex;gap:6px;align-items:center;margin:8px 0;flex-wrap:wrap}'
  + '.cc-row select,.cc-row input{background:#0c0f14;color:inherit;border:1px solid var(--line);'
  + 'border-radius:6px;padding:4px 7px;font:inherit;font-size:.72rem}'
  + '.cc-q{font-size:.66rem;line-height:1.45;margin:0 0 7px;padding-bottom:6px;'
  + 'border-bottom:1px solid var(--line)}';
  document.head.appendChild(s);
})();

/* ── angle set ─────────────────────────────────────────────────────────────
   48 cells, drawn from the character's OWN manifest.cell_angles — a sheet made
   under a different angle set is reported against the list it was made from,
   not against today's default. Present cells are thumbnails through the page's
   own imgUrl (scope-fenced); missing ones are dashed, and the title carries
   the count so the panel answers "how complete is this sheet" at a glance. */
function ccAnglesPanel() {
  if (!CS.charId) return cstPanelOpen('angles', 'Angle set', cstNoChar());
  ccWait('angles', 'Angle set', 'Reading the sheet manifest…');
  ccGet('angles', {id: CS.charId}).then(function (j) {
    if (!j || !j.ok) return ccErr('angles', 'Angle set', j);
    var grid = j.angles.map(function (a) {
      var t = '#' + a.idx + ' · ' + a.name;
      if (!a.present) {
        return '<div class="cc-cell gap" title="' + esc(t + ' — not on disk') + '">'
             + '<span class="n">' + a.idx + '</span></div>';
      }
      var src = a.cat ? imgUrl(CS.charId, a.cat, a.img, a.mtime, 1) : '';
      return '<div class="cc-cell" title="' + esc(t) + '">'
           + (src ? '<img loading="lazy" src="' + esc(src) + '">' : '')
           + '<span class="n">' + a.idx + '</span></div>';
    }).join('');
    var miss = j.missing.length
      ? '<div class="cst-warn">Missing: ' + esc(j.missing.join(', ')) + '</div>'
        + '<div class="cst-hint">' + esc(j.angles.filter(function (a) { return !a.present; })
            .slice(0, 8).map(function (a) { return '#' + a.idx + ' ' + a.name; }).join(' · ')) + '</div>'
      : '<div class="cst-hint">Every angle in this character\u2019s list is on disk.</div>';
    cstPanelOpen('angles',
      'Angle set <span style="opacity:.65;font-weight:400">'
      + j.present + ' / ' + j.total + '</span>',
      '<div class="cc-grid">' + grid + '</div>'
      + miss
      + cstKv('angle set', j.angle_set)
      + cstKv('list from', j.source,
              'manifest.cell_angles is what the run really used; the pipeline default is only the fallback')
      + cstKv('sheet approved', j.sheet_approved === null || j.sheet_approved === undefined
                ? 'not recorded' : String(j.sheet_approved))
      + '<div class="cst-hint big">The list is this character\u2019s own '
      + '<code>contact_sheet/manifest.json</code>, not today\u2019s default set \u2014 a sheet '
      + 'built under an older or a custom selection is measured against the angles it '
      + 'was actually asked for.</div>');
  }).catch(function (e) { ccErr('angles', 'Angle set', {error: String(e)}); });
}

/* ── hand QC ───────────────────────────────────────────────────────────────
   The panel opens with a plan, not a run: the judge is one VLM call per crop.
   MEASURED and the reason the op exists — the judge passes melted hands on a
   full frame, so it only ever sees crops, and the panel says which image was
   looked at and how it was chosen. */
function ccHandPanel(cell) {
  if (!CS.charId) return cstPanelOpen('handqc', 'Hand QC', cstNoChar());
  cstPanelOpen('handqc', 'Hand QC',
    '<div class="cst-hint big">Detects hand boxes on one image, then asks the VLM about '
    + 'each <b>crop</b>. Measured: the same judge scores melted hands as fine when it is '
    + 'shown the whole frame, so a crop is the only view it is trusted on.</div>'
    + '<div class="cc-row"><label style="font-size:.7rem">Cell</label>'
    + '<input id="cc-cell" placeholder="master reference" value="' + esc(cell || '') + '" '
    + 'style="width:130px" title="a cell file name, e.g. cell_24.png — empty means the '
    + 'bible\u2019s master reference">'
    + '<button class="go" onclick="ccHandRun()">Judge</button></div>'
    + '<div class="cst-hint">Full-body cells (the A-pose ring) are where the hands are; '
    + 'a head-and-shoulders master reference usually has none.</div>');
}
function ccHandRun() {
  var el = document.getElementById('cc-cell');
  var cell = el ? el.value.trim() : '';
  ccWait('handqc', 'Hand QC', 'Detecting hands, then judging each crop\u2026');
  ccGet('handqc', {id: CS.charId, image: cell}).then(function (j) {
    if (!j || !j.ok) return ccErr('handqc', 'Hand QC', j);
    var hands = (j.hands || []).map(function (h) {
      var v = h.verdict, chip;
      if (!v) chip = ccChip(false, h.why || 'judge unavailable');
      else if (!v.hand_visible) chip = ccChip(false, 'judge sees no hand here');
      else if (v.defective) chip = ccChip(false, 'defective');
      else chip = ccChip(true, 'clean');
      return '<div class="cc-hand">'
        + (h.crop_b64 ? '<img src="data:image/jpeg;base64,' + h.crop_b64 + '">' : '')
        + '<div style="min-width:0">' + chip
        + '<div class="cst-hint">box ' + esc(h.box.join(', '))
        + ' \u00b7 detector ' + h.conf + '</div>'
        + (v ? '<div class="cst-hint">' + esc(v.problem || 'no problem named')
               + ' \u00b7 confidence ' + esc(String(v.confidence || '?')) + '</div>' : '')
        + (h.why && v ? '<div class="cst-warn">' + esc(h.why) + '</div>' : '')
        + '</div></div>';
    }).join('');
    cstPanelOpen('handqc', 'Hand QC',
      '<div class="cst-hint big">' + esc(j.verdict) + '</div>'
      + (j.judge_error ? '<div class="cst-warn">The judge could not be reached for at '
          + 'least one crop: ' + esc(j.judge_error) + '. Those hands are NOT a pass \u2014 '
          + 'they were never looked at.</div>' : '')
      + (hands || '<div class="todo">No hand box on this image. That is the detector\u2019s '
          + 'answer, not the judge\u2019s \u2014 nothing was judged.</div>')
      + cstKv('image', (j.image || '').split('/').pop())
      + cstKv('chosen', j.how)
      + cstKv('detector', j.backend)
      + cstKv('judge', j.vlm_model)
      + '<div class="cst-foot"><button class="go" onclick="ccHandRun()">Judge again</button>'
      + '<button class="go" onclick="ccHandPanel(' + JSON.stringify(
            (j.how || '').indexOf('cell ') === 0 ? j.how.slice(5) : '') + ')">'
      + 'Another image</button></div>');
  }).catch(function (e) { ccErr('handqc', 'Hand QC', {error: String(e)}); });
}

/* ── anachronism ───────────────────────────────────────────────────────────
   The period is the bible's wardrobe.period unless the operator picks another
   one here. 'contemporary', '2000s' and 'science fiction' are NOT gated and the
   server says so in words — a period with no "after" has no question to ask,
   and rendering that as a pass would be the worst kind of green tick. */
function ccPeriodOptions(sel) {
  var sp = (CST.spec && CST.spec.fields) ? CST.spec.fields['wardrobe.period'] : null;
  var ch = (sp && sp.choices) ? sp.choices
         : ['contemporary', '2000s', '1980s', '1950s', '1920s', 'victorian', 'regency',
            '18th century', '17th century', 'renaissance', 'medieval', 'ancient',
            'timeless fantasy', 'science fiction'];
  return ch.map(function (c) {
    return '<option value="' + esc(c) + '"' + (c === sel ? ' selected' : '') + '>'
         + esc(c) + '</option>';
  }).join('');
}
function ccAnachPanel(period) {
  if (!CS.charId) return cstPanelOpen('anachronism', 'Anachronism', cstNoChar());
  var cur = period || cstVal('wardrobe.period') || 'contemporary';
  cstPanelOpen('anachronism', 'Anachronism',
    '<div class="cst-hint big">Asks Qwen3-VL about six overlapping crops of this '
    + 'character\u2019s reference, with the period tells as the questions. About 40 s on '
    + 'the GPU.</div>'
    + '<div class="cc-row"><label style="font-size:.7rem">Period</label>'
    + '<select id="cc-period">' + ccPeriodOptions(cur) + '</select>'
    + '<button class="go" onclick="ccAnachRun()">Run the gate</button></div>'
    + cstKv('wardrobe.period', cstVal('wardrobe.period') || 'not set (contemporary)')
    + '<div class="cst-hint">The bible\u2019s own period is preselected. Picking another one '
    + 'here does not write to the bible \u2014 it asks what this character would look like '
    + 'out of place in.</div>');
}
function ccAnachRun() {
  var el = document.getElementById('cc-period');
  var period = el ? el.value : '';
  ccWait('anachronism', 'Anachronism', 'Tiling the reference and asking the judge\u2026');
  ccGet('anachronism', {id: CS.charId, period: period}).then(function (j) {
    if (!j || !j.ok) return ccErr('anachronism', 'Anachronism', j);
    if (!j.gated) {
      return cstPanelOpen('anachronism', 'Anachronism \u00b7 ' + esc(j.period),
        '<div class="cst-warn">' + esc(j.reason) + '</div>'
        + '<div class="cc-row"><label style="font-size:.7rem">Period</label>'
        + '<select id="cc-period">' + ccPeriodOptions(j.period) + '</select>'
        + '<button class="go" onclick="ccAnachRun()">Run the gate</button></div>');
    }
    var kinds = (j.kinds || []).length
      ? j.kinds.map(function (k) {
          return '<div class="cc-q"><b>' + esc(k.kind || k.id) + '</b><br>'
               + esc(k.question) + '</div>';
        }).join('')
      : '<div class="cst-warn">' + esc(j.kinds_note || 'No object-specific question.') + '</div>';
    var checks = (j.checks || []).map(function (c) {
      return '<div class="cc-q">' + ccChip(c.ok, c.ok ? 'pass' : 'FLAG')
           + '<span style="opacity:.6">' + esc(c.id) + ' \u00b7 ' + esc(c.source) + '</span><br>'
           + esc(c.question) + '</div>';
    }).join('');
    var flags = (j.flags || []).length
      ? '<div class="cst-warn">' + j.flags.map(function (f) {
          return esc(f.id) + ': ' + esc(f.reason || 'flagged');
        }).join('<br>') + '</div>'
      : '';
    cstPanelOpen('anachronism',
      'Anachronism <span style="opacity:.65;font-weight:400">' + esc(j.period) + '</span>',
      '<div class="cst-hint big">'
      + ((j.flags || []).length
          ? (j.flags.length + ' flag(s) against ' + esc(j.period))
          : 'Nothing out of period was found for ' + esc(j.period) + '.')
      + ((j.unknown || []).length
          ? ' ' + j.unknown.length + ' question(s) the judge would not answer \u2014 those '
            + 'are not a pass.' : '')
      + '</div>'
      + flags
      + '<div class="cst-hint big">Objects named from this bible</div>' + kinds
      + '<div class="cst-hint big">Every question and its answer</div>' + checks
      + cstKv('period used', j.period + (j.from_bible ? ' (from the bible)' : ' (picked here)'))
      + cstKv('era bucket', j.bucket + ' \u00b7 after ' + (j.era && j.era.period_end))
      + cstKv('judge', j.judge)
      + cstKv('seconds', j.seconds)
      + cstKv('image', (j.image || '').split('/').pop())
      + cstKv('wardrobe prose', j.prose || 'empty')
      + '<div class="cst-foot"><button class="go" onclick="ccAnachPanel('
      + JSON.stringify(j.period) + ')">Another period</button></div>');
  }).catch(function (e) { ccErr('anachronism', 'Anachronism', {error: String(e)}); });
}

/* ── audition ──────────────────────────────────────────────────────────────
   MEASURED: voice_profile.character_voice in the bibles holds AZURE names
   ('en-US-BrianNeural') or free prose, and 108 of them are empty — the local
   cloning engines cannot speak any of that. The server refuses with the id it
   was handed rather than auditioning somebody else's voice, and this panel
   offers the session's picked voice (CS.voice) as the way out. */
function ccStopPoll() {
  if (CC.timer) { clearInterval(CC.timer); CC.timer = null; }
  CC.job = ''; CC.panel = '';
}
function ccAuditionPanel(text) {
  if (!CS.charId) return cstPanelOpen('audition', 'Audition', cstNoChar());
  ccStopPoll();
  var claimed = cstVal('voice_profile.character_voice') || '';
  var picked = (CS.voice && CS.voice.id) || '';
  var name = CS.charName || CS.charId;
  var line = text || (name + ' here. This is how I sound today.');
  cstPanelOpen('audition', 'Audition',
    '<div class="cc-row"><textarea id="cc-line" rows="2" style="flex:1;min-width:190px;'
    + 'background:#0c0f14;color:inherit;border:1px solid var(--line);border-radius:6px;'
    + 'padding:5px 7px;font:inherit;font-size:.72rem">' + esc(line) + '</textarea></div>'
    + '<div class="cc-row"><button class="go" onclick="ccAuditionRun()">Render</button>'
    + '<span class="cst-hint" style="margin:0">voice: <b>'
    + esc(picked || claimed || 'none') + '</b></span></div>'
    + cstKv('voice_profile.character_voice', claimed || 'empty')
    + cstKv('picked this session', picked || 'none')
    + '<div class="cst-hint big">The bibles on disk carry Azure voice names '
    + '(<code>en-US-BrianNeural</code>) and free prose in that field. The Voice Studio '
    + 'engines are cloners with their own ids, so a bible value that is not one of them '
    + 'is refused by name rather than quietly swapped \u2014 use <b>Pick a voice</b> first.</div>');
}
function ccAuditionRun() {
  var el = document.getElementById('cc-line');
  var text = el ? el.value.trim() : '';
  var picked = (CS.voice && CS.voice.id) || '';
  ccWait('audition', 'Audition', 'Starting the render\u2026');
  ccPost('audition', {id: CS.charId, text: text, voice: picked}).then(function (j) {
    if (!j || !j.ok) return ccErr('audition', 'Audition', j);
    CC.voice = j.voice;
    ccAuditionRender(j, j.job || {});
    ccStartPoll((j.job || {}).id || '');
  }).catch(function (e) { ccErr('audition', 'Audition', {error: String(e)}); });
}
function ccStartPoll(jid) {
  ccStopPoll();
  if (!jid) return;
  CC.job = jid; CC.panel = 'audition';
  CC.timer = setInterval(ccTick, 2500);
}
function ccTick() {
  if (!CC.job) return ccStopPoll();
  if (CST.panel !== CC.panel) return ccStopPoll();  /* another tool took the panel */
  api(withScope('/voice/api/job?id=' + encodeURIComponent(CC.job))).then(function (j) {
    if (!j) return;
    ccAuditionRender(null, j);
    if (j.state !== 'queued' && j.state !== 'running') ccStopPoll();
  }).catch(function () { ccStopPoll(); });
}
function ccAuditionRender(meta, job) {
  if (meta) CC.meta = meta;
  var m = CC.meta || {};
  var done = job.state && job.state !== 'queued' && job.state !== 'running';
  var player = (done && job.wav)
    ? '<audio controls autoplay style="width:100%;margin:8px 0" src="'
      + esc(withScope('/voice/audio?p=' + encodeURIComponent(job.wav))) + '"></audio>'
    : (job.state === 'error' || job.error)
      ? '<div class="cst-warn">' + esc(job.error || 'the render failed') + '</div>'
      : '<div class="cc-bar"><i></i></div>';
  cstPanelOpen('audition', 'Audition \u00b7 ' + esc(m.voice || CC.voice || ''),
    '<div class="cst-hint big">' + esc(m.text || job.text || '') + '</div>'
    + player
    + cstKv('state', job.state || '?')
    + cstKv('voice', m.voice || job.voice || '')
    + cstKv('from the bible', m.voice ? String(!!m.from_bible) : '—')
    + cstKv('engine', (job.params && job.params.engine) || '')
    + cstKv('file', job.wav || 'not written yet')
    + ((job.log && job.log.length)
        ? '<pre class="cst-pre">' + esc(job.log.slice(-8).join('\n')) + '</pre>' : '')
    + '<div class="cst-foot"><button class="go" onclick="ccAuditionPanel('
    + JSON.stringify(m.text || job.text || '') + ')">New line</button></div>');
}

/* ── the four handlers ───────────────────────────────────────────────────── */
CST_ACT.angleset    = function () { ccAnglesPanel(); };
CST_ACT.handqc      = function () { ccHandPanel(''); };
CST_ACT.anachronism = function () { ccAnachPanel(''); };
CST_ACT.audition    = function () { ccAuditionPanel(''); };

/* a setInterval that outlives its panel is a leak that only shows up as load
   on the server hours later — the same wrap char_run.js uses. */
if (typeof cstPanelClose === 'function') {
  var _ccClose = cstPanelClose;
  cstPanelClose = function () { ccStopPoll(); return _ccClose.apply(this, arguments); };
}
