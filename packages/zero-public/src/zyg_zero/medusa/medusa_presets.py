#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Medusa Presets — standalone preset-driven submitter.  Port 5301.

A SECOND service (separate process) that feeds the SAME guarded entry as the
Medusa GUI: it POSTs to the crews endpoint

    POST {CREWS_API}/api/medusa/generate     (bp_medusa.py, :5000)

so every request still passes the server-side guardrails baked into that route:
  • women-only + swimwear wardrobe
  • adults-only (age >= 18; minor / explicit language in the free-text prompt is
    rejected by sanitize_char_prompt)
  • operator-approval queue (each request is parked as 'pending' and must be
    allow/declined before the pipeline runs)

The difference from the :5300 GUI's /api/generate_character front door is the
INPUT: instead of a live form, this service submits a saved *preset* — a bare
JSON / YAML / YML file holding the character body. Presets live in a dedicated
directory (default: medusa/config/presets/) so engine-config files in the parent
config store are never mistaken for character requests.

This process has NO generation deps of its own — the real work lives on :5000.
It only reads preset files off disk and forwards them, exactly like the GUI
proxy does. Adults-only is also fast-rejected here, but the crews route remains
the authoritative gate.

Run:  /usr/bin/python3 medusa_presets.py
Then: http://$ZYG_LAN_HOST:5301  (loopback unless ZYG_LAN_HOST names the box)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, Response, jsonify, request, send_file

import medusa_ipgate
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


app = Flask(__name__)

# ── Client IP allowlist (2026-08-08) ─────────────────────────────────────────
# THIS APP WAS THE OPEN DOOR. It binds 0.0.0.0:5301 with no session and proxies
# /api/medusa/pending and /api/medusa/pending/<id>/decide straight into the
# crews API, whose guard only checks that the CALLER is localhost — which this
# process always is. Until this gate existed, any device on the LAN could read
# the operator approval queue and APPROVE OR REJECT items in it. Gating :5300
# alone did not close it; see medusa_ipgate.py.
medusa_ipgate.install(app, service_name='medusa_presets:5301')

PORT = 5301
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Favicon — reuse the Medusa artwork that lives next to medusa_server.py.
FAVICON_PNG = os.path.join(BASE_DIR, 'favicon.png')
FAVICON_ICO = os.path.join(BASE_DIR, 'favicon.ico')

# The guarded entry. Same crews API the :5300 GUI proxies to.
CREWS_API = os.environ.get('MEDUSA_CREWS_API', 'http://127.0.0.1:5000')
GUARDED_PATH = '/api/medusa/generate'

# Preset store — a dedicated subdir of the Medusa config tree. Only character
# presets live here; the parent config/ dir (model_params.json, etc.) is left
# alone so engine configs are never submitted as characters. Override with
# MEDUSA_PRESETS_DIR if you want to point somewhere else.
PRESETS_DIR = os.path.realpath(os.environ.get('MEDUSA_PRESETS_DIR', os.path.join(BASE_DIR, 'config', 'presets')))
_PRESET_EXTS = ('.json', '.yaml', '.yml')
_MAX_PRESET_BYTES = 1_000_000
ADULT_MIN_AGE = 18


# ── Safe preset-file resolution (path-traversal hardened) ────────────────────
def _safe_preset_path(name):
    """Resolve a bare preset filename to a real path strictly inside PRESETS_DIR,
    or None on any violation (traversal, absolute path, bad extension, symlink,
    dotfile). Mirrors medusa_server._safe_config_path."""
    if not isinstance(name, str):
        return None
    if not name or name != os.path.basename(name) or name.startswith('.'):
        return None
    if not name.lower().endswith(_PRESET_EXTS):
        return None
    root = os.path.realpath(PRESETS_DIR)
    p = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(p) != root:
        return None
    return p


def _parse_preset_text(name, text):
    """Parse preset text (JSON or YAML-safe) into a dict, or raise ValueError.

    YAML is loaded with safe_load and code-constructing tags are rejected, so a
    malicious preset file can never build arbitrary objects. The parsed result
    MUST be a JSON object (dict) — the crews route does dict(raw), so a list or
    scalar is meaningless as a character body."""
    if len(text) > _MAX_PRESET_BYTES:
        raise ValueError('preset too large (>1MB)')
    low = name.lower()
    if low.endswith('.json'):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f'invalid JSON: {exc}') from exc
    else:  # .yaml / .yml
        if any(tok in text for tok in ('!!python/', '!!ruby/', '!!java', '!<tag:')):
            raise ValueError('unsafe YAML tag rejected')
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - pyyaml is installed here
            raise ValueError('YAML presets need PyYAML installed') from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f'invalid YAML: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError('preset must be a JSON/YAML object (mapping) of character fields')
    return data


def _load_preset(name):
    """(body_dict, raw_text) for a named preset, or raise ValueError."""
    p = _safe_preset_path(name)
    if not p or not os.path.isfile(p):
        raise ValueError('invalid or missing preset — use a bare *.json / *.yaml / *.yml name')
    try:
        with open(p, 'rb') as fh:
            raw = fh.read(_MAX_PRESET_BYTES + 1)
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    if len(raw) > _MAX_PRESET_BYTES:  # true BYTE cap (text-mode read() counts chars)
        raise ValueError('preset too large (>1MB)')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(f'preset is not valid UTF-8: {exc}') from exc
    return _parse_preset_text(name, text), text


def _preset_summary(body):
    """A compact preview of a character body for the listing UI."""
    prompt = body.get('char_prompt')
    if prompt is None:
        prompt = body.get('extra_prompt')
    return {
        'name': body.get('name'),
        'age': body.get('age'),
        'prompt': (str(prompt)[:160] if prompt else None),
    }


def _age_fast_reject(body):
    """Fast client-side adults-only reject. Returns an error string or None.

    The crews route is still authoritative (it re-validates the age and the
    free-text prompt); this only short-circuits an obviously under-age preset
    before we bother the pipeline server."""
    age = body.get('age')
    if age in (None, '', 'auto'):
        return None
    try:
        if int(float(age)) < ADULT_MIN_AGE:
            return f'Adults only — age must be {ADULT_MIN_AGE}+.'
    except (TypeError, ValueError):
        return 'Invalid age.'
    return None


# ── Crews proxy helpers (same pattern as medusa_server) ──────────────────────
def _crews_proxy(method, path, body=None):
    """Forward a request to the crews API; return (text, status)."""
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'} if data is not None else {}
    url = CREWS_API + path
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ('http', 'https'):
        raise ValueError(f'refusing to open {scheme or "scheme-less"} crews URL: {url}')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310  scheme checked above
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310  # noqa: S310  scheme checked above
        return resp.read().decode('utf-8'), resp.status


def _forward_to_guard(body):
    """POST a character body through the guarded entry and return a Flask Response
    that faithfully passes through the crews route's status + JSON (including its
    400 age/prompt rejections and 202 'parked for approval')."""
    try:
        payload, status = _crews_proxy('POST', GUARDED_PATH, body)
        return Response(payload, status=status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:  # noqa: BLE001 — surface unreachable-crews cleanly
        return jsonify(
            {
                'ok': False,
                'error': f'Could not reach crews API at {CREWS_API} (is the :5000 workflows server up?): {exc}',
            }
        ), 502


# ── Routes ───────────────────────────────────────────────────────────────────
@app.route('/favicon.png')
def favicon_png():
    return send_file(FAVICON_PNG, mimetype='image/png')


@app.route('/favicon.ico')
def favicon_ico():
    return send_file(FAVICON_ICO, mimetype='image/x-icon')


@app.route('/healthz')
def healthz():
    return jsonify(
        {
            'ok': True,
            'service': 'medusa-presets',
            'port': PORT,
            'presets_dir': PRESETS_DIR,
            'crews_api': CREWS_API,
            'guarded_path': GUARDED_PATH,
        }
    )


@app.route('/')
def index():
    return Response(HTML, content_type='text/html; charset=utf-8', headers={'Cache-Control': 'no-store'})


@app.route('/api/presets')
def api_presets():
    """List preset files with a parsed summary (invalid files flagged, not hidden)."""
    try:
        os.makedirs(PRESETS_DIR, exist_ok=True)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    out = []
    try:
        names = sorted(
            f
            for f in os.listdir(PRESETS_DIR)
            if f.lower().endswith(_PRESET_EXTS)
            and os.path.isfile(os.path.join(PRESETS_DIR, f))
            and not os.path.islink(os.path.join(PRESETS_DIR, f))
        )
    except OSError:
        names = []
    for name in names:
        row = {'name': name}
        try:
            body, _ = _load_preset(name)
            row['valid'] = True
            row['summary'] = _preset_summary(body)
        except ValueError as exc:
            row['valid'] = False
            row['error'] = str(exc)
        out.append(row)
    return jsonify({'ok': True, 'presets': out, 'count': len(out)})


@app.route('/api/preset')
def api_preset():
    """Raw text + parsed body for one preset (for the preview pane)."""
    name = request.args.get('name', '')
    try:
        body, text = _load_preset(name)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'name': name, 'content': text, 'parsed': body, 'summary': _preset_summary(body)})


@app.route('/api/generate_from_preset', methods=['POST'])
def api_generate_from_preset():
    """Load a saved preset (or accept an inline body) and submit it through the
    guarded /api/medusa/generate entry. The crews route enforces women-only +
    swimwear + adults-only and parks the request for operator approval."""
    req = request.get_json(silent=True) or {}

    # Accept a filename under several keys, or an inline character body.
    fname = req.get('preset') or req.get('file') or req.get('name')
    inline = req.get('inline') if isinstance(req.get('inline'), dict) else None

    if inline is not None:
        body = inline
        source = 'inline'
    elif fname:
        try:
            body, _ = _load_preset(fname)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        source = fname
    else:
        return jsonify(
            {'ok': False, 'error': "provide 'preset' (a *.json/*.yaml/*.yml filename) or an 'inline' object"}
        ), 400

    if not isinstance(body, dict):
        return jsonify({'ok': False, 'error': 'preset body must be an object'}), 400

    age_err = _age_fast_reject(body)
    if age_err:
        return jsonify({'ok': False, 'error': age_err, 'source': source}), 400

    return _forward_to_guard(body)


# ── Operator-approval proxies (so the guarded flow is usable standalone) ──────
@app.route('/api/medusa/pending', methods=['GET'])
def api_pending_proxy():
    try:
        payload, status = _crews_proxy('GET', '/api/medusa/pending')
        return Response(payload, status=status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:  # noqa: BLE001
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


@app.route('/api/medusa/pending/<req_id>/decide', methods=['POST'])
def api_decide_proxy(req_id):
    body = request.get_json(silent=True) or {}
    try:
        payload, status = _crews_proxy('POST', f'/api/medusa/pending/{req_id}/decide', body)
        return Response(payload, status=status, content_type='application/json')
    except urllib.error.HTTPError as exc:
        return Response(exc.read().decode('utf-8', 'replace'), status=exc.code, content_type='application/json')
    except Exception as exc:  # noqa: BLE001
        return jsonify({'ok': False, 'error': f'crews API unreachable: {exc}'}), 502


# ─────────────────────────────────────────────────────────────────────────────
# Minimal Medusa-themed UI: pick a preset → preview → submit through the guard →
# approve/decline in the pending panel. Plain string (NOT an f-string) so the
# CSS { } braces stay literal.
# ─────────────────────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Medusa · Presets</title>
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #07070f; --surface: #0e0e1a; --panel: #0b0b14;
    --border: rgba(255,255,255,0.07); --text: #e2e8f0; --muted: #64748b;
    --accent: #10b981; --accent-2: #34d399; --accent-rgb: 16,185,129;
    --danger: #f43f5e; --warn: #f59e0b;
  }
  html, body { height: 100%; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
  body { padding: 28px clamp(16px, calc(4vw / var(--ui-zoom,1)), 56px); max-width: 1100px; margin: 0 auto; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 6px; }
  .logo-hex { width: 40px; height: 40px; flex: none; overflow: hidden;
    clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
    background: rgba(var(--accent-rgb),0.15); }
  .logo-hex img { width: 100%; height: 100%; object-fit: cover; }
  h1 { font-size: 20px; font-weight: 650; letter-spacing: .2px; }
  h1 span { color: var(--accent-2); }
  .sub { color: var(--muted); font-size: 13px; margin: 2px 0 22px; line-height: 1.5; }
  .sub code { color: var(--accent-2); background: rgba(var(--accent-rgb),0.08);
    padding: 1px 6px; border-radius: 5px; font-size: 12px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  @media (max-width:549px)/*was 820px @67%*/ { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 18px; }
  .card h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .6px;
    color: var(--muted); margin-bottom: 14px; font-weight: 600; }
  label { display: block; font-size: 12px; color: var(--muted); margin: 0 0 6px; }
  select, textarea { width: 100%; background: var(--panel); color: var(--text);
    border: 1px solid var(--border); border-radius: 9px; padding: 10px 12px;
    font-size: 13px; font-family: inherit; }
  textarea { min-height: 200px; resize: vertical; white-space: pre;
    font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
  .row { display: flex; gap: 10px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
  button { border: 1px solid var(--border); border-radius: 9px; padding: 9px 16px;
    font-size: 13px; font-weight: 600; cursor: pointer; background: var(--panel);
    color: var(--text); transition: .15s; }
  button:hover { border-color: rgba(var(--accent-rgb),0.5); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #04120c; }
  button.primary:hover { background: var(--accent-2); }
  button:disabled { opacity: .45; cursor: default; }
  button.ghost { padding: 6px 12px; font-size: 12px; }
  button.approve { color: var(--accent-2); }
  button.decline { color: var(--danger); }
  .out { margin-top: 14px; font-size: 12.5px; line-height: 1.55; padding: 12px 14px;
    border-radius: 9px; border: 1px solid var(--border); background: var(--panel);
    display: none; white-space: pre-wrap; word-break: break-word; }
  .out.show { display: block; }
  .out.ok { border-color: rgba(var(--accent-rgb),0.4); }
  .out.err { border-color: rgba(244,63,94,0.4); color: #fda4b4; }
  .meta { font-size: 12px; color: var(--muted); margin-top: 10px; }
  .meta b { color: var(--text); font-weight: 600; }
  .pend { list-style: none; display: flex; flex-direction: column; gap: 10px; }
  .pend li { background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 11px 13px; }
  .pend .lbl { font-size: 13px; font-weight: 600; }
  .pend .id { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; }
  .pend .pill { font-size: 10.5px; text-transform: uppercase; letter-spacing: .5px;
    padding: 2px 8px; border-radius: 20px; border: 1px solid var(--border); }
  .pill.pending { color: var(--warn); }
  .pill.approved { color: var(--accent-2); }
  .pill.declined { color: var(--danger); }
  .empty { color: var(--muted); font-size: 13px; }
  .badge { display: inline-block; font-size: 10px; padding: 1px 7px; border-radius: 20px;
    border: 1px solid var(--border); color: var(--danger); margin-left: 6px; }
</style>
<style id="ui-zoom">
  /* 2026-09-05: whole-page scale. This GUI was laid out while the operator browsed at 67% zoom;
     this renders that same layout at 100%. ONE factor, four consumers — keep them in step:
       (a) html{zoom:.67} below (Chrome's standardized zoom: layout viewport = screen/.67);
       (b) every vh/vw length in this page and its stylesheets is calc(Nvh / var(--ui-zoom,1)) —
           Chrome does NOT scale viewport units with zoom (100vh would be 723 screen px);
       (c) @media min/max-width breakpoints are multiplied by .67 (they see the REAL viewport);
       (d) the shim script next to this block: under zoom Chrome reports clientX/Y, pageX/Y,
           getBoundingClientRect() and innerWidth/Height in SCREEN px while offset/client/scroll
           sizes stay in layout px — the shim divides the screen-px readings back so menus, drags
           and canvas hit-tests land under the pointer.
     A page loaded inside an <iframe> switches itself OFF (see the shim): the parent's zoom already reaches it.
     Undo: set both .67 values to 1 (calc + shim become no-ops), or restore *.bak-zoom67-20260905. */
  html{zoom:.67;}
  :root{--ui-zoom:.67;}
</style>
<script>
(function(){ /* zoom coordinate shim — see the ui-zoom style block, item (d). No-op when zoom is 1. */
  if(window.self!==window.top){ /* framed (e.g. the kanban board inside the dashboard): Chrome carries the parent's
       zoom into the frame — layout, vh and pointer coordinates already behave like browser zoom in here, and a second
       zoom would shrink the frame to 45%. Trust the parent. Measured 2026-09-05. */
    document.documentElement.style.zoom='1'; document.documentElement.style.setProperty('--ui-zoom','1'); return; }
  var Z=parseFloat(getComputedStyle(document.documentElement).zoom);
  if(!(Z>0)||Z===1) return;
  window.UI_ZOOM=Z;
  document.documentElement.style.setProperty('--ui-zoom',String(Z));
  function wrap(obj,name,f){
    var d=Object.getOwnPropertyDescriptor(obj,name);
    if(!d||typeof d.get!=='function') return;
    var g=d.get;
    Object.defineProperty(obj,name,{configurable:true,enumerable:d.enumerable,get:function(){return f(g.call(this));}});
  }
  var down=function(v){return v/Z;};
  ['clientX','clientY','pageX','pageY','offsetX','offsetY','movementX','movementY'].forEach(function(n){wrap(MouseEvent.prototype,n,down);});
  if(window.Touch) ['clientX','clientY','pageX','pageY'].forEach(function(n){wrap(Touch.prototype,n,down);});
  ['innerWidth','innerHeight'].forEach(function(n){wrap(window,n,down);});
  wrap(window,'devicePixelRatio',function(v){return v*Z;});
  var gbcr=Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect=function(){var r=gbcr.call(this);return new DOMRect(r.x/Z,r.y/Z,r.width/Z,r.height/Z);};
  var gcr=Element.prototype.getClientRects;
  Element.prototype.getClientRects=function(){return Array.prototype.map.call(gcr.call(this),function(r){return new DOMRect(r.x/Z,r.y/Z,r.width/Z,r.height/Z);});};
  var efp=Document.prototype.elementFromPoint, efps=Document.prototype.elementsFromPoint;
  Document.prototype.elementFromPoint=function(x,y){return efp.call(this,x*Z,y*Z);};
  Document.prototype.elementsFromPoint=function(x,y){return efps.call(this,x*Z,y*Z);};
})();
</script>
</head>
<body>
<header>
  <div class="logo-hex"><img src="/favicon.png" alt="Medusa"></div>
  <div>
    <h1>Medusa · <span>Presets</span></h1>
  </div>
</header>
<p class="sub">
  Submit a saved character preset through the same guarded entry
  (<code>POST /api/medusa/generate</code>). Women-only + swimwear + adults-only are
  enforced server-side, and every request is parked for operator approval.
</p>

<div class="grid">
  <section class="card">
    <h2>Preset → guarded entry</h2>
    <label for="sel">Preset file</label>
    <select id="sel"><option value="">Loading…</option></select>
    <div class="meta" id="summary"></div>
    <label for="preview" style="margin-top:14px">Preview (read-only)</label>
    <textarea id="preview" readonly placeholder="Select a preset to preview its body…"></textarea>
    <div class="row">
      <button class="primary" id="submit" disabled>Submit through guard</button>
      <button class="ghost" id="reload">Reload presets</button>
    </div>
    <div class="out" id="result"></div>
  </section>

  <section class="card">
    <h2>Operator approval queue</h2>
    <div class="row" style="margin-top:0;margin-bottom:12px">
      <button class="ghost" id="refresh">Refresh pending</button>
    </div>
    <ul class="pend" id="pending"><li class="empty">Loading…</li></ul>
  </section>
</div>

<script>
const $ = (id) => document.getElementById(id);
const sel = $("sel"), preview = $("preview"), summary = $("summary"),
      submitBtn = $("submit"), result = $("result"), pending = $("pending");

// Escape EVERY preset/crews-supplied value before it touches innerHTML. A preset's
// 'name' (and the crews-built 'label' derived from it) is operator/attacker text and
// is NOT HTML-sanitized upstream, so raw interpolation would be DOM/stored XSS.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function showOut(msg, ok) {
  result.textContent = msg;
  result.className = "out show " + (ok ? "ok" : "err");
}

async function loadPresets() {
  sel.innerHTML = '<option value="">Loading…</option>';
  submitBtn.disabled = true;
  try {
    const r = await fetch("/api/presets");
    const j = await r.json();
    const list = (j.presets || []);
    if (!list.length) {
      sel.innerHTML = '<option value="">(no presets found)</option>';
      return;
    }
    sel.innerHTML = '<option value="">Choose a preset…</option>';
    for (const p of list) {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = p.name + (p.valid ? "" : "  ⚠ invalid");
      opt.disabled = !p.valid;
      sel.appendChild(opt);
    }
  } catch (e) {
    sel.innerHTML = '<option value="">(failed to load)</option>';
    showOut("Failed to list presets: " + e, false);
  }
}

async function loadPreview(name) {
  summary.textContent = ""; preview.value = "";
  submitBtn.disabled = true;
  result.className = "out";
  if (!name) return;
  try {
    const r = await fetch("/api/preset?name=" + encodeURIComponent(name));
    const j = await r.json();
    if (!j.ok) { showOut(j.error || "Could not read preset", false); return; }
    preview.value = j.content || "";
    const s = j.summary || {};
    summary.innerHTML = "<b>" + esc(s.name || "(unnamed)") + "</b>" +
      " · age " + esc(s.age ?? "auto") +
      (s.prompt ? " · " + esc(s.prompt) : "");
    submitBtn.disabled = false;
  } catch (e) {
    showOut("Failed to read preset: " + e, false);
  }
}

async function submitPreset() {
  const name = sel.value;
  if (!name) return;
  submitBtn.disabled = true;
  showOut("Submitting through guarded entry…", true);
  try {
    const r = await fetch("/api/generate_from_preset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset: name }),
    });
    const j = await r.json();
    if (r.ok && (j.ok || j.pending)) {
      showOut("✓ " + (j.message || "Parked for operator approval.") +
        "\\nlabel:   " + (j.label || "—") +
        "\\nchar_id: " + (j.char_id || "—") +
        "\\npending: " + (j.pending_id || "—"), true);
      loadPending();
    } else {
      showOut("✗ " + (j.error || ("HTTP " + r.status)), false);
    }
  } catch (e) {
    showOut("Request failed: " + e, false);
  } finally {
    submitBtn.disabled = false;
  }
}

async function loadPending() {
  try {
    const r = await fetch("/api/medusa/pending");
    const j = await r.json();
    const rows = (j.all || j.pending || []);
    if (!rows.length) { pending.innerHTML = '<li class="empty">No requests yet.</li>'; return; }
    pending.innerHTML = "";
    for (const rec of rows.slice().reverse()) {
      const li = document.createElement("li");
      const st = rec.status || "pending";
      let actions = "";
      if (st === "pending" || st === "queued") {
        const rid = esc(rec.id);
        actions = '<button class="ghost approve" data-id="' + rid + '" data-act="allow">Approve</button>' +
                  '<button class="ghost decline" data-id="' + rid + '" data-act="decline">Decline</button>';
      }
      const stc = esc(st);
      li.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">' +
          '<span class="lbl">' + esc(rec.label || rec.name || "request") + '</span>' +
          '<span class="pill ' + stc + '">' + stc + '</span>' +
        '</div>' +
        '<div class="id">' + esc(rec.char_id || rec.id || "") + '</div>' +
        (actions ? '<div class="row" style="margin-top:8px">' + actions + '</div>' : "");
      pending.appendChild(li);
    }
    pending.querySelectorAll("button[data-id]").forEach(b => {
      b.onclick = () => decide(b.dataset.id, b.dataset.act);
    });
  } catch (e) {
    pending.innerHTML = '<li class="empty">Could not reach crews API.</li>';
  }
}

async function decide(id, action) {
  try {
    await fetch("/api/medusa/pending/" + encodeURIComponent(id) + "/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
  } catch (e) {}
  loadPending();
}

sel.addEventListener("change", () => loadPreview(sel.value));
submitBtn.addEventListener("click", submitPreset);
$("reload").addEventListener("click", loadPresets);
$("refresh").addEventListener("click", loadPending);
loadPresets();
loadPending();
</script>
</body>
</html>
"""


if __name__ == '__main__':  # the CLI lives in medusa_presets_cli
    from zyg_zero.medusa.medusa_presets_cli import main as _cli_main

    raise SystemExit(_cli_main())
