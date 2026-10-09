// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ══ Character Studio — the Run dock ════════════════════════════════════════
   2026-09-18, task 11 of the four-studios wiring tree.

   Five dock tools were drawn and given an `act:` key with no handler behind it:
   Render still (d_preview), Re-sheet (d_resheet AND the Sheet rail's own
   `resheet`), Restyle (d_restyle), Train LoRA (d_train) and Stop (d_stop).
   This file adds CST_ACT.preview / resheet / restyle / train / stopjob and
   nothing else. It is loaded by /studio_ext/bundle.js AFTER the page's own
   script block, so CST_ACT, cstPanelOpen, CS, CST, imgUrl and esc all exist.

   Every one of these five presses the GPU, so the shape is the same for all of
   them and it is deliberately three steps, not one:

     PLAN     GET  char_run/plan  — the resolved caller, the real parameters and
              the honest cost, rendered before anything is started. Nothing has
              been taken at this point; closing the panel costs nothing.
     RUN      POST char_run/start — sheet, restyle and train carry confirm:true,
              which is why the plan had to be read first. A still does not: it
              is one png and about a minute.
     WATCH    GET  char_run/status every 3 s — the server's own log tail and its
              outputs. The timer is cleared when the panel closes, when another
              panel takes its place, and when the job leaves queued/running, so
              a forgotten Character Studio tab does not poll for ever.

   Stop writes an ABORT file through char_run/stop. It is a REQUEST the runner
   reads between steps, not a kill — the panel says so, because a Stop button
   that silently fails to stop a training run is worse than no button.
*/

var CR = {
  timer: null,     /* the 3 s poll */
  job: '',         /* the job it polls */
  panel: '',       /* which cst-panel id owns that poll */
  kind: '',
  title: '',
  seen: 0,         /* log lines already rendered, so the <pre> only grows */
};

function crUrl(op, q) {
  var u = '/inspect/api/studio/char_run/' + op;
  var bits = [];
  Object.keys(q || {}).forEach(function (k) {
    bits.push(encodeURIComponent(k) + '=' + encodeURIComponent(q[k]));
  });
  return bits.length ? u + '?' + bits.join('&') : u;
}
function crGet(op, q) {
  return fetch(crUrl(op, q), {cache: 'no-cache'}).then(function (r) {
    return r.json().then(function (j) { j._code = r.status; return j; });
  });
}
function crPost(op, body) {
  return fetch('/inspect/api/studio/char_run/' + op,
               {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body || {})})
    .then(function (r) {
      return r.json().then(function (j) { j._code = r.status; return j; });
    });
}
function crErr(id, title, j) {
  crStopPoll();
  cstPanelOpen(id, title, '<div class="cst-warn">'
    + esc(j && (j.error || j.message) ? (j.error || j.message)
                                      : ('HTTP ' + ((j && j._code) || '?')))
    + '</div>'
    + ((j && j.gpu) ? cstKv('GPU utilisation', j.gpu.util + ' %')
                    + cstKv('free VRAM', j.gpu.free_mb + ' MiB') : '')
    + '<div class="cst-hint">Nothing was started.</div>');
}
function crSecs(a, b) {
  if (!a) return '—';
  var s = Math.max(0, Math.round((b || (Date.now() / 1000)) - a));
  return s < 90 ? (s + ' s') : (Math.floor(s / 60) + ' min ' + (s % 60) + ' s');
}

/* ── the poll ─────────────────────────────────────────────────────────────
   One timer for the whole file. It stops itself on three conditions, and the
   page's own cstPanelClose is wrapped below so closing the panel is one of
   them — a setInterval that outlives its panel is a leak that only shows up
   as load on the server hours later. */
function crStopPoll() {
  if (CR.timer) { clearInterval(CR.timer); CR.timer = null; }
  CR.job = ''; CR.panel = ''; CR.seen = 0;
}
function crStartPoll(job, panelId, kind, title) {
  crStopPoll();
  CR.job = job; CR.panel = panelId; CR.kind = kind; CR.title = title; CR.seen = 0;
  crTick();
  CR.timer = setInterval(crTick, 3000);
}
function crTick() {
  if (!CR.job) return crStopPoll();
  if (CST.panel !== CR.panel) return crStopPoll();   /* another tool took the panel */
  crGet('status', {job: CR.job}).then(function (j) {
    if (!j || !j.ok) return crErr(CR.panel, CR.title, j);
    crRenderJob(j);
    if (j.status !== 'queued' && j.status !== 'running') {
      if (CR.timer) { clearInterval(CR.timer); CR.timer = null; }
    }
  }).catch(function (e) {
    crErr(CR.panel, CR.title, {error: String(e)});
  });
}

/* ── the live job panel ─────────────────────────────────────────────────── */
function crOutputs(j) {
  var outs = j.outputs || [];
  if (!outs.length) return '';
  var html = '<div class="cst-hint big">Outputs</div>';
  outs.forEach(function (o) {
    if (o.kind === 'image') {
      /* the restyle path reports cat+name because /inspect/img is scope-fenced
         and the page's own imgUrl() is the only thing that knows the scope;
         the still path reports a ready /inspect/media url. */
      var src = o.cat ? imgUrl(j.id, o.cat, o.name, j.finished || j.started)
                      : withScope(o.url || '');
      html += '<a href="' + esc(src) + '" target="_blank">'
            + '<img src="' + esc(src) + '" style="width:100%;border-radius:8px;'
            + 'border:1px solid var(--line);margin:6px 0;display:block"></a>'
            + '<div class="cst-hint">' + esc((o.path || '').split('/').pop())
            + ' · ' + esc(cstBytes(o.bytes)) + '</div>';
    } else if (o.kind === 'sheet') {
      html += cstKv('master sheet', (o.path || '').split('/').pop())
            + '<div class="cst-foot"><button class="go" onclick="'
            + (typeof CST_ACT.grid === 'function'
                 ? 'CST_ACT.grid()' : 'CST_ACT.openlib()')
            + '">Open the sheet grid</button></div>';
    } else {
      html += cstKv(o.kind, o.path || '—');
    }
  });
  return html;
}
function crRenderJob(j) {
  var live = (j.status === 'queued' || j.status === 'running');
  var cls = j.status === 'done' ? 'ok'
          : (j.status === 'error' ? 'bad' : (live ? '' : 'warn'));
  var prog = j.progress
    ? (j.progress.done + ' / ' + j.progress.total) : '';
  var body =
      '<div class="cst-msg ' + cls + '"><b>' + esc(j.status)
    + (j.aborting ? ' — stopping' : '') + '</b>'
    + (j.error ? '<br>' + esc(j.error) : '') + '</div>'
    + cstKv('job', j.job)
    + cstKv('character', (j.name || '') + '  ·  ' + j.id)
    + cstKv('kind', j.kind)
    + (prog ? cstKv('progress', prog) : '')
    + cstKv(live ? 'running for' : 'took', crSecs(j.started, j.finished))
    + '<div class="cst-hint big">Server log (last ' + ((j.log || []).length)
    + ' lines, polled every 3 s)</div>'
    + '<pre class="cst-pre" id="cr-log">' + esc((j.log || []).join('\n')) + '</pre>'
    + crOutputs(j)
    + '<div class="cst-foot">'
    + (live
        ? '<button onclick="crStop(\'' + esc(j.job) + '\')">Stop</button>'
        : '<button class="go" onclick="CST_ACT.' + crActFor(j.kind)
          + '()">Plan another</button>')
    + '<button onclick="cstPanelClose()">Close</button></div>'
    + (live
        ? '<div class="cst-hint">Stop writes an ABORT file. The runner reads it '
          + 'between steps and unwinds — no process is signalled, so a step '
          + 'already on the GPU finishes first.</div>'
        : '');
  cstPanelOpen(CR.panel, CR.title, body);
  /* keep the log scrolled to the newest line, the way a tail does */
  var pre = document.getElementById('cr-log');
  if (pre) pre.scrollTop = pre.scrollHeight;
}
function crActFor(kind) {
  return {still: 'preview', sheet: 'resheet',
          restyle: 'restyle', train: 'train'}[kind] || 'stopjob';
}
function crStop(job) {
  crPost('stop', {job: job}).then(function (j) {
    if (!j.ok) return crErr(CR.panel, CR.title, j);
    crTick();
  });
}

/* ── plan → run ───────────────────────────────────────────────────────────
   The plan is the server's, rendered whole: the caller it resolved, the
   parameters it will pass and what it says the run costs. A panel that
   paraphrased that would be a second source of truth for what is about to
   happen on the GPU. */
function crPlanRows(p) {
  var skip = {kind: 1, id: 1, caller: 1, expect: 1, destructive: 1,
              outputs: 1, params: 1, sources: 1, prompt: 1, negative: 1, fn: 1};
  var html = '';
  Object.keys(p).forEach(function (k) {
    if (skip[k]) return;
    var v = p[k];
    html += cstKv(k, (v && typeof v === 'object') ? JSON.stringify(v) : v);
  });
  if (p.prompt) html += '<div class="cst-hint big">Prompt</div>'
                      + '<pre class="cst-pre">' + esc(p.prompt) + '</pre>';
  if (p.negative) html += '<div class="cst-hint big">Negative</div>'
                        + '<pre class="cst-pre">' + esc(p.negative) + '</pre>';
  if (p.sources) html += '<div class="cst-hint big">Sources (' + p.count + ')</div>'
                       + '<pre class="cst-pre">' + esc(p.sources.join('\n')) + '</pre>';
  if (p.params) html += '<div class="cst-hint big">params handed to the pipeline ('
                      + Object.keys(p.params).length + ' keys)</div>'
                      + '<pre class="cst-pre">' + esc(JSON.stringify(p.params, null, 1))
                      + '</pre>';
  return html;
}
function crPlanPanel(kind, id, title, j) {
  var p = j.plan || {};
  var needs = !!j.needs_confirm;
  cstPanelOpen(id, title,
      '<div class="cst-hint big">This is what will run. Nothing has been started '
    + 'and no GPU has been taken yet.</div>'
    + cstKv('character', (CS.charName || '') + '  ·  ' + CS.charId)
    + cstKv('expected cost', p.expect || '—')
    + cstKv('writes', p.outputs || '—')
    + (p.destructive ? '<div class="cst-warn">' + esc(p.destructive) + '</div>' : '')
    + '<div class="cst-hint big">Resolved caller</div>'
    + '<pre class="cst-pre">' + esc(p.caller || '—') + '</pre>'
    + crPlanRows(p)
    + '<div class="cst-foot">'
    + '<button class="go" onclick="crRun(\'' + kind + '\',\'' + id + '\',\''
    + esc(title).replace(/'/g, '') + '\',' + (needs ? 'true' : 'false') + ')">'
    + (needs ? 'Confirm and run' : 'Run') + '</button>'
    + '<button onclick="cstPanelClose()">Cancel</button></div>'
    + (needs
        ? '<div class="cst-hint">This kind needs a confirm token because of how '
          + 'long it holds the GPU — the server refuses it without one, so this '
          + 'button is the confirmation, not a formality.</div>'
        : '<div class="cst-hint">One still, about a minute. No confirm needed.</div>'));
}
function crPlan(kind, id, title) {
  crStopPoll();
  if (!CS.charId) return cstPanelOpen(id, title, cstNoChar());
  cstPanelOpen(id, title, '<div class="todo">resolving the plan&hellip;</div>');
  crGet('plan', {id: CS.charId, kind: kind}).then(function (j) {
    if (!j.ok) return crErr(id, title, j);
    crPlanPanel(kind, id, title, j);
  }).catch(function (e) { crErr(id, title, {error: String(e)}); });
}
function crRun(kind, id, title, confirm) {
  cstPanelOpen(id, title, '<div class="todo">starting&hellip;</div>');
  crPost('start', {id: CS.charId, kind: kind, confirm: !!confirm})
    .then(function (j) {
      if (j.needs_confirm) return crPlanPanel(kind, id, title, j);
      if (!j.ok) return crErr(id, title, j);
      crStartPoll(j.job, id, kind, title);
    }).catch(function (e) { crErr(id, title, {error: String(e)}); });
}

/* ── the five acts ───────────────────────────────────────────────────────
   resheet is reached from TWO tools — the dock's d_resheet and the Sheet
   rail's own `resheet` — so it panels under whichever one was pressed. */
CST_ACT.preview = function (t) { crPlan('still', (t && t.id) || 'd_preview', 'Render still'); };
CST_ACT.resheet = function (t) { crPlan('sheet', (t && t.id) || 'd_resheet', 'Re-sheet'); };
CST_ACT.restyle = function (t) { crPlan('restyle', (t && t.id) || 'd_restyle', 'Restyle'); };
CST_ACT.train   = function (t) { crPlan('train', (t && t.id) || 'd_train', 'Train LoRA'); };

CST_ACT.stopjob = function (t) {
  var id = (t && t.id) || 'd_stop';
  crStopPoll();
  if (!CS.charId) return cstPanelOpen(id, 'Stop', cstNoChar());
  cstPanelOpen(id, 'Stop', '<div class="todo">asking the server&hellip;</div>');
  crGet('list', {id: CS.charId}).then(function (j) {
    if (!j.ok) return crErr(id, 'Stop', j);
    var jobs = j.jobs || [], live = jobs.filter(function (r) { return r.running; });
    var g = j.gpu || {};
    cstPanelOpen(id, 'Stop',
        (live.length
          ? '<div class="cst-hint big">Running for this character</div>'
            + live.map(function (r) {
                return '<div class="kv"><b>' + esc(r.kind) + '</b><span>'
                  + '<button onclick="crWatch(\'' + esc(r.job) + '\',\'' + esc(id)
                  + '\')">watch</button> '
                  + '<button onclick="crStopFromList(\'' + esc(r.job) + '\',\''
                  + esc(id) + '\')">stop</button> '
                  + esc(crSecs(r.started, 0)) + '</span></div>'; }).join('')
          : '<div class="todo">No job is running for <b>'
            + esc(CS.charName || CS.charId) + '</b>. Stop halts a job this dock '
            + 'started — it does not reach a pipeline started anywhere else.</div>')
      + (jobs.length
          ? '<div class="cst-hint big">Recent jobs (' + jobs.length + ')</div>'
            + jobs.slice(0, 10).map(function (r) {
                return cstKv(r.kind + '  ' + r.status,
                             crSecs(r.started, r.finished) + (r.error ? ' — ' + r.error : ''));
              }).join('')
          : '')
      + '<div class="cst-hint big">GPU</div>'
      + cstKv('utilisation', (g.util >= 0 ? g.util + ' %' : 'unreadable')
                             + '  (a run is refused at ' + g.busy_pct + ' %)')
      + cstKv('free VRAM', (g.free_mb >= 0 ? g.free_mb + ' MiB' : 'unreadable')
                           + '  (a run needs ' + g.free_min_mb + ')')
      + cstKv('slot held by', j.busy || 'nobody'));
  }).catch(function (e) { crErr(id, 'Stop', {error: String(e)}); });
};
function crWatch(job, id) {
  crStartPoll(job, id, '', 'Stop');
}
function crStopFromList(job, id) {
  crPost('stop', {job: job}).then(function () { CST_ACT.stopjob({id: id}); });
}

/* ── the timer never outlives its panel ──────────────────────────────────
   cstPanelClose is the page's own; wrapping it is the seam's documented way
   to hook a page function, and it is the only place that knows the panel is
   gone (Escape, the X, and every other tool's close all come through here). */
(function () {
  var orig = cstPanelClose;
  if (typeof orig !== 'function') return;
  cstPanelClose = function () { crStopPoll(); return orig.apply(this, arguments); };
})();

if (window.SX && SX.ready) SX.ready.push('char_run');
