// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* movement_track.js — Movement Studio's Track action, for real (2026-09-18).

   WHAT CHANGED. moTrackExtract used to POST /inspect/api/movement/driver and
   sit on the response for up to an hour, and the route it called answered 501
   "not built yet" because geom.pose_track was unbuilt. Both halves are real
   now: bp_movement runs pose_track AND geom.track_plates in a background thread
   behind job.json, so this posts once, polls, and fills BOTH folder fields —
   Control frames with the composite plate folder, Mask frames with the tracked
   masks. Nothing here composes a path or guesses a frame count; every value
   shown comes off the job the server wrote.

   The dials are set through moSet(), not by assigning MO.params directly, so
   the live sentence and the dot markers refresh the same way a typed edit
   refreshes them.

   2026-09-18b: the Mask frames field stayed empty on every early job because
   geom.pose_track only segments a subject when it is handed a phrase to find —
   without one it does a whole-image single-person track and writes no masks at
   all. So the sheet now ASKS first: a Subject box, prefilled with the loaded
   subject's name, sent with the clip. When the masks still come back 0 the
   sheet says which phrase SAM 3 failed on instead of quietly leaving the field
   alone. */
(function () {
  if (typeof moSheetOpen !== 'function' || typeof moSet !== 'function') return;

  var MT = { job: '', timer: 0, subject: '' };

  /* Movement Studio's one-line status field doubles as its toast — it is the
     only notification surface this view has, and it is free while no render is
     running. Never written while a render owns it. */
  function mtToast(msg, cls) {
    var st = document.getElementById('mvst-status');
    if (!st || (typeof MVST !== 'undefined' && MVST.running)) return;
    st.textContent = msg;
    st.className = 'mvst-status ' + (cls || 'done');
    clearTimeout(MT.toastT);
    MT.toastT = setTimeout(function () {
      if (typeof MVST !== 'undefined' && MVST.running) return;
      st.textContent = ''; st.className = 'mvst-status';
    }, 8000);
  }

  function mtBody(html) {
    if (MO.sheet === 'track') moSheetBody(html);   /* never clobber another sheet */
  }

  function mtLog(j) {
    var lg = (j && j.log) || [];
    return '<span class="k">log</span><pre>'
      + esc(lg.slice(-14).join('\n') || 'starting…') + '</pre>';
  }

  function mtStop() { clearTimeout(MT.timer); MT.timer = 0; MT.job = ''; }

  function mtPoll() {
    var job = MT.job;
    fetch(withScope('/inspect/api/movement/driver?job=' + encodeURIComponent(job)))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (MT.job !== job) return;                /* a newer extraction took over */
        if (!j || j.error) {
          mtBody('<span class="k">lost the job</span><pre>'
            + esc((j && j.error) || 'no answer') + '</pre>');
          return mtStop();
        }
        if (j.status === 'error') {
          mtBody('<span class="k">failed</span><pre>' + esc(j.error || 'no reason given')
            + '</pre>' + mtLog(j));
          mtToast('Track failed — see the sheet.', 'err');
          return mtStop();
        }
        if (j.status === 'done') {
          mtStop();
          /* Only what the extraction actually produced. control_dir is the
             track_plates folder (a real control channel); the raw video frames
             pose_track also writes are NOT one and are never offered here. */
          if (j.control_dir) moSet('control_dir', j.control_dir);
          if (j.mask_dir) moSet('mask_dir', j.mask_dir);
          var subj = j.subject || MT.subject || '';
          mtBody(moKV('track', j.track)
            + moKV('subject', subj)
            + moKV('plate mode', j.plate_mode)
            + moKV('plate frames', j.frames)
            + moKV('plate size', (j.size && j.size.length === 2) ? j.size.join('x') : '')
            + moKV('Control frames set to', j.control_dir || 'not filled')
            + moKV('mask frames', j.masks)
            + moKV('Mask frames set to', j.mask_dir || 'not filled')
            /* Silence here was the whole bug report: the field simply stayed
               empty and nothing said the phrase was the reason. */
            + (!j.masks
                ? '<span class="k">no masks</span><pre>'
                  + esc('SAM 3 found no subject for "' + subj + '" — try a more specific '
                        + 'description') + '</pre>'
                : '')
            + (j.plate_audit_ok === false
                ? '<span class="k">plate audit warning</span><pre>' + esc(j.plate_audit || '')
                  + '\n\nThe plates exist but came out near-constant — check the clip '
                  + 'actually has a tracked body in it before rendering off them.</pre>'
                : '')
            + mtLog(j));
          mtToast('Track ready: ' + (j.frames || 0) + ' frames', 'done');
          return;
        }
        mtBody('<span class="k">' + esc(j.status || 'running') + '</span><pre>'
          + esc(j.clip || '') + '\n\npose_track then track_plates on the GPU — this can '
          + 'take many minutes. The job keeps running if you close this sheet.</pre>'
          + mtLog(j));
        MT.timer = setTimeout(mtPoll, 3000);
      })
      .catch(function (e) {
        if (MT.job !== job) return;
        mtBody('<pre>' + esc(String(e)) + '</pre>');
        MT.timer = setTimeout(mtPoll, 3000);       /* a dropped poll is not a dead job */
      });
  }

  window.moTrackExtract = function () {
    var clip = (MO.params.driver_clip || '').trim();
    if (!clip) {
      moSheetOpen('track', 'Extract track', 'mv-track',
        '<span class="k">no driver clip</span><pre>Put a video path in the Driver clip '
        + 'field on the CONTROL PATH rack first.</pre>');
      return;
    }
    if (MT.job) {                                  /* already ours — show it, do not queue */
      moSheetOpen('track', 'Extract track', 'mv-track', '<pre>reading…</pre>');
      return mtPoll();
    }
    /* Ask before spending the GPU: the phrase decides whether there will be
       masks at all, and it is not recoverable after the fact. */
    var pre = (typeof MVST !== 'undefined' && MVST.subjectName) ? MVST.subjectName : '';
    moSheetOpen('track', 'Extract track', 'mv-track',
      moKV('driver clip', clip)
      + moKV('plate mode', MO.params.plate_mode || 'composite')
      + '<span class="k">subject</span>'
      + '<div class="mt-row"><input type="text" id="mt-subject" value="' + esc(pre) + '"'
      + ' placeholder="who to mask, e.g. &quot;the young man in the red coat&quot;">'
      + '<button type="button" id="mt-go">Extract</button></div>'
      + '<pre>The phrase SAM 3 looks for, one subject. Leave it empty and the job '
      + 'falls back to the loaded subject\'s name, then to "the person" — pose_track '
      + 'writes masks only for what it was asked to find, so a vague phrase is how '
      + 'Mask frames comes back empty.</pre>');
    var go = document.getElementById('mt-go');
    var inp = document.getElementById('mt-subject');
    if (go) go.onclick = function () { mtStart(clip, (inp && inp.value) || ''); };
    if (inp) {
      inp.onkeydown = function (e) { if (e.key === 'Enter') { e.preventDefault(); go.click(); } };
      inp.focus();
      inp.select();
    }
  };

  function mtStart(clip, subject) {
    MT.subject = String(subject || '').trim();
    moSheetBody('<pre>starting the track job over\n' + esc(clip)
      + '\n\nsubject: ' + esc(MT.subject || '(the loaded subject, else "the person")')
      + '</pre>');
    var mode = (MO.params.plate_mode || 'composite');
    fetch(withScope('/inspect/api/movement/driver'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        clip: clip, plate_mode: mode, subject: MT.subject,
        subject_name: (typeof MVST !== 'undefined' && MVST.subjectName) || ''
      })
    })
      .then(function (r) { return r.json().then(function (d) { d._code = r.status; return d; }); })
      .then(function (d) {
        if (!d || !d.ok) {
          mtBody('<span class="k">failed (' + ((d && d._code) || '?') + ')</span><pre>'
            + esc((d && d.error) || 'no answer') + '</pre>'
            + ((d && d.running_id)
                ? '<pre>running track job: ' + esc(d.running_id) + '</pre>' : ''));
          return;
        }
        MT.job = d.job_id;
        mtBody('<pre>job ' + esc(d.job_id) + ' started…</pre>');
        MT.timer = setTimeout(mtPoll, 1200);
      })
      .catch(function (e) { mtBody('<pre>' + esc(String(e)) + '</pre>'); });
  }

  /* The sheet has no input styling of its own — it has never held a control
     before this one. Scoped to .mt-row so nothing else in the sheet moves. */
  var st = document.createElement('style');
  st.textContent = '.mt-row{display:flex;gap:6px;align-items:center;margin:6px 0 4px}'
    + '.mt-row input{flex:1 1 auto;min-width:0;background:#0c0f14;color:inherit;'
    + 'border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit;'
    + 'font-size:.72rem}'
    + '.mt-row button{flex:0 0 auto;background:#131923;color:inherit;'
    + 'border:1px solid var(--line);border-radius:6px;padding:5px 11px;font:inherit;'
    + 'font-size:.72rem;cursor:pointer}'
    + '.mt-row button:hover{border-color:var(--accent,#6ea8fe)}';
  document.head.appendChild(st);
})();
