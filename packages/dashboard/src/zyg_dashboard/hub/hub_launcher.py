# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Zygomatic Hub Launcher
Compile to .exe on Windows:
    pip install pyinstaller
    pyinstaller --onefile --noconsole --name "Zygomatic Hub" hub_launcher.py
"""

import os
import threading
import webbrowser
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 7777

# The host the cards link to. The hub is a LAN bookmark: the page is opened from
# phones and other machines, so the links cannot be 127.0.0.1 unless you really
# are on the box. Set ZYG_LAN_HOST to this machine's LAN address to publish it.
LAN_HOST_PLACEHOLDER = '__ZYG_LAN_HOST__'
LAN_HOST = os.environ.get('ZYG_LAN_HOST', '127.0.0.1')

HUB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zygomatic Hub</title>
<link rel="icon" type="image/png" href="data:image/png;base64,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">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #07070f;
    --surface:   #0e0e1a;
    --border:    rgba(255,255,255,0.07);
    --text:      #e2e8f0;
    --muted:     #64748b;
    --zero:      #38bdf8;
    --nexus:     #22d3ee;
    --arena:   #fb923c;
    --houdini:   #a78bfa;
    --sandbox:   #fb7185;
  }

  html, body {
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  body::before, body::after {
    content: "";
    position: fixed;
    border-radius: 50%;
    filter: blur(120px);
    pointer-events: none;
    z-index: 0;
  }
  body::before {
    width: 600px; height: 600px;
    top: -200px; left: -150px;
    background: radial-gradient(circle, rgba(56,189,248,0.08) 0%, transparent 70%);
  }
  body::after {
    width: 500px; height: 500px;
    bottom: -150px; right: -100px;
    background: radial-gradient(circle, rgba(167,139,250,0.08) 0%, transparent 70%);
  }

  .page {
    position: relative;
    z-index: 1;
    min-height: calc(100vh / var(--ui-zoom,1));
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 28px 24px 28px;
  }

  /* ── Header ── */
  header {
    text-align: center;
    margin-bottom: 26px;
    animation: fadeDown 0.6s ease both;
  }

  .wordmark {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 14px;
    margin-bottom: 8px;
  }

  .logo-hex {
    width: 48px; height: 48px;
    background: linear-gradient(135deg, var(--zero), var(--houdini));
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    font-weight: 800;
    color: #fff;
    letter-spacing: -1px;
    flex-shrink: 0;
  }

  .brand-name {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    background: linear-gradient(90deg, var(--zero), #818cf8, var(--houdini));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .subtitle {
    color: var(--muted);
    font-size: 13px;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-top: 4px;
  }

  .time-display {
    color: var(--muted);
    font-size: 12px;
    margin-top: 12px;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.5px;
  }

  /* ── Grid ── */
  .grid {
    display: grid;
    grid-template-columns: repeat(3, 234px);
    gap: 11px;
    width: 100%;
    max-width: 724px;
  }

  @media (max-width:485px)/*was 724px @67%*/ {
    .grid { grid-template-columns: repeat(2, 234px); max-width: 479px; }
  }
  @media (max-width:321px)/*was 479px @67%*/ {
    .grid { grid-template-columns: 1fr; max-width: 240px; }
  }

  /* ── Card ── */
  .card {
    position: relative;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 16px 12px;
    text-decoration: none;
    color: inherit;
    display: block;
    overflow: hidden;
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    animation: fadeUp 0.5s ease both;
  }

  .card:nth-child(1) { animation-delay: 0.05s; }
  .card:nth-child(2) { animation-delay: 0.10s; }
  .card:nth-child(3) { animation-delay: 0.15s; }
  .card:nth-child(4) { animation-delay: 0.20s; }
  .card:nth-child(5) { animation-delay: 0.25s; }
  .card:nth-child(6) { animation-delay: 0.30s; }
  .card:nth-child(7) { animation-delay: 0.35s; }
  .card:nth-child(8) { animation-delay: 0.40s; }
  .card:nth-child(9) { animation-delay: 0.45s; }
  .card:nth-child(10) { animation-delay: 0.50s; }
  .card:nth-child(11) { animation-delay: 0.55s; }
  .card:nth-child(12) { animation-delay: 0.60s; }
  .card:nth-child(13) { animation-delay: 0.65s; }
  .card:nth-child(14) { animation-delay: 0.70s; }
  .card:nth-child(15) { animation-delay: 0.75s; }
  .card:nth-child(16) { animation-delay: 0.80s; }

  .card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent);
    border-radius: 10px 10px 0 0;
  }

  .card::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 10px;
    background: radial-gradient(ellipse at top left, rgba(var(--accent-rgb),0.06) 0%, transparent 60%);
    pointer-events: none;
  }

  .card:hover {
    transform: translateY(-4px);
    border-color: rgba(var(--accent-rgb), 0.35);
    box-shadow: 0 10px 24px rgba(0,0,0,0.4), 0 0 18px rgba(var(--accent-rgb), 0.08);
  }

  .card-zero    { --accent: var(--zero);    --accent-rgb: 56, 189, 248; }
  .card-nexus   { --accent: var(--nexus);   --accent-rgb: 34, 211, 238; }
  .card-sandbox   { --accent: var(--sandbox); --accent-rgb: 251, 113, 133; }
  .card-medusa    { --accent: #10b981;        --accent-rgb: 16, 185, 129;  }
  .card-sessiontree { --accent: #22d3ee;      --accent-rgb: 34, 211, 238;  }
  .card-nomologin { --accent: #8b5cf6;       --accent-rgb: 139, 92, 246;  }

  .card-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }

  .status-dot {
    width: 4px; height: 4px;
    border-radius: 50%;
    background: #374151;
    flex-shrink: 0;
    transition: background 0.4s ease, box-shadow 0.4s ease;
  }
  .status-dot.online  { background: #4ade80; box-shadow: 0 0 4px rgba(74,222,128,0.6); }
  .status-dot.offline { background: #ef4444; }

  .status-label {
    font-size: 8px;
    font-weight: 600;
    letter-spacing: 0.7px;
    text-transform: uppercase;
    color: var(--muted);
    flex: 1;
  }

  .restart-btn {
    position: relative;
    z-index: 10;
    width: 22px; height: 22px;
    border-radius: 5px;
    border: 1px solid rgba(var(--accent-rgb), 0.2);
    background: rgba(var(--accent-rgb), 0.08);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.2s ease, border-color 0.2s ease;
    flex-shrink: 0;
  }

  .restart-btn:hover {
    background: rgba(var(--accent-rgb), 0.18);
    border-color: rgba(var(--accent-rgb), 0.45);
  }

  .restart-btn svg {
    width: 11px; height: 11px;
    stroke: var(--accent);
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: transform 0.3s ease;
    display: block;
  }

  .restart-btn:hover svg    { transform: rotate(60deg); }
  .restart-btn.spinning svg { animation: spin 0.7s linear infinite; }
  .restart-btn.done svg     { stroke: #4ade80; }

  /* Power on/off toggle — injected next to the restart button (JS, per card) */
  .power-btn {
    position: relative;
    z-index: 10;
    width: 22px; height: 22px;
    border-radius: 5px;
    border: 1px solid rgba(var(--accent-rgb), 0.2);
    background: rgba(var(--accent-rgb), 0.08);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.2s ease, border-color 0.2s ease;
    flex-shrink: 0;
  }
  .power-btn:hover {
    background: rgba(var(--accent-rgb), 0.18);
    border-color: rgba(var(--accent-rgb), 0.45);
  }
  .power-btn svg {
    width: 10px; height: 10px;
    stroke: var(--muted);
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    display: block;
  }
  .power-btn.is-on svg  { stroke: #4ade80; }   /* running — click to turn OFF */
  .power-btn.is-off svg { stroke: #ef4444; }   /* stopped — click to turn ON  */
  .power-btn.spinning svg { animation: spin 0.7s linear infinite; }

  @keyframes spin { to { transform: rotate(360deg); } }

  .card-name {
    font-size: 14px;
    font-weight: 700;
    color: #f1f5f9;
    margin-bottom: 11px;
    letter-spacing: -0.2px;
  }

  .card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .port-tag {
    font-size: 8px;
    color: var(--muted);
    letter-spacing: 0.3px;
    font-variant-numeric: tabular-nums;
    background: rgba(255,255,255,0.04);
    padding: 2px 5px;
    border-radius: 4px;
    border: 1px solid var(--border);
  }

  .launch-btn {
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    color: var(--accent);
    display: flex;
    align-items: center;
    gap: 4px;
    transition: gap 0.2s ease;
  }

  .card:hover .launch-btn { gap: 6px; }

  .launch-arrow { font-size: 8px; transition: transform 0.2s ease; }
  .card:hover .launch-arrow { transform: translateX(2px); }

  /* ── Toast ── */
  #toast {
    position: fixed;
    bottom: 28px;
    left: 50%;
    transform: translateX(-50%) translateY(20px);
    background: #1e293b;
    border: 1px solid rgba(255,255,255,0.1);
    color: #e2e8f0;
    font-size: 13px;
    padding: 10px 20px;
    border-radius: 10px;
    opacity: 0;
    transition: opacity 0.25s ease, transform 0.25s ease;
    pointer-events: none;
    white-space: nowrap;
    z-index: 100;
  }
  #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

  /* ── Footer ── */
  .hub-footer {
    margin-top: 48px;
    text-align: center;
    color: #1e293b;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
    animation: fadeUp 0.5s 0.4s ease both;
  }

  @keyframes fadeDown {
    from { opacity: 0; transform: translateY(-16px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(16px); }
    to   { opacity: 1; transform: translateY(0); }
  }
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
<div class="page">

  <header>
    <div class="wordmark">
      <div class="logo-hex">Z</div>
      <span class="brand-name">Zygomatic</span>
    </div>
    <p class="subtitle">App Hub</p>
    <p class="time-display" id="clock"></p>
  </header>

  <div class="grid">

    <a class="card card-zero" href="http://__ZYG_LAN_HOST__:5000" target="_blank" data-url="http://__ZYG_LAN_HOST__:5000" data-app="zero">
      <div class="card-meta">
        <div class="status-dot" data-status></div>
        <span class="status-label">Online</span>
        <button class="restart-btn" data-restart="zero" title="Restart Zero">
          <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/></svg>
        </button>
      </div>
      <div class="card-name">Zero</div>
      <div class="card-footer">
        <span class="port-tag">:5000</span>
        <span class="launch-btn">Open <span class="launch-arrow">&#8594;</span></span>
      </div>
    </a>

    <a class="card card-nexus" href="http://__ZYG_LAN_HOST__:8090" target="_blank" data-url="http://__ZYG_LAN_HOST__:8090" data-app="nexus">
      <div class="card-meta">
        <div class="status-dot" data-status></div>
        <span class="status-label">Online</span>
        <button class="restart-btn" data-restart="nexus" title="Restart Creator Nexus">
          <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/></svg>
        </button>
      </div>
      <div class="card-name">Creator Nexus</div>
      <div class="card-footer">
        <span class="port-tag">:8090</span>
        <span class="launch-btn">Open <span class="launch-arrow">&#8594;</span></span>
      </div>
    </a>

    <a class="card card-sandbox" href="http://__ZYG_LAN_HOST__:5555" target="_blank" data-url="http://__ZYG_LAN_HOST__:5555" data-app="sandbox">
      <div class="card-meta">
        <div class="status-dot" data-status></div>
        <span class="status-label">Online</span>
        <button class="restart-btn" data-restart="sandbox" title="Restart Sandbox">
          <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/></svg>
        </button>
      </div>
      <div class="card-name">Sandbox</div>
      <div class="card-footer">
        <span class="port-tag">:5555</span>
        <span class="launch-btn">Open <span class="launch-arrow">&#8594;</span></span>
      </div>
    </a>

    <a class="card card-medusa" href="http://__ZYG_LAN_HOST__:5300" target="_blank" data-url="http://__ZYG_LAN_HOST__:5300" data-app="medusa">
      <div class="card-meta">
        <div class="status-dot" data-status></div>
        <span class="status-label">Online</span>
        <button class="restart-btn" data-restart="medusa" title="Restart Medusa">
          <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/></svg>
        </button>
      </div>
      <div class="card-name">Medusa</div>
      <div class="card-footer">
        <span class="port-tag">:5300</span>
        <span class="launch-btn">Open <span class="launch-arrow">&#8594;</span></span>
      </div>
    </a>

    <a class="card card-sessiontree" href="http://__ZYG_LAN_HOST__:7100" target="_blank" data-url="http://__ZYG_LAN_HOST__:7100" data-app="sessiontree">
      <div class="card-meta">
        <div class="status-dot" data-status></div>
        <span class="status-label">Online</span>
        <button class="restart-btn" data-restart="sessiontree" title="Restart Session Tree">
          <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/></svg>
        </button>
      </div>
      <div class="card-name">Session Tree</div>
      <div class="card-footer">
        <span class="port-tag">:7100</span>
        <span class="launch-btn">Open <span class="launch-arrow">&#8594;</span></span>
      </div>
    </a>

    <a class="card card-nomologin" href="http://127.0.0.1:8750" target="_blank" data-url="http://127.0.0.1:8750" data-app="nomologin" data-probe="api">
      <div class="card-meta">
        <div class="status-dot" data-status></div>
        <span class="status-label">Online</span>
        <button class="restart-btn" data-restart="nomologin" title="Restart Nomologin">
          <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><polyline points="3 3 3 8 8 8"/></svg>
        </button>
      </div>
      <div class="card-name">Nomologin</div>
      <div class="card-footer">
        <span class="port-tag">:8750</span>
        <span class="launch-btn">Open <span class="launch-arrow">&#8594;</span></span>
      </div>
    </a>

  </div>

  <div class="hub-footer">__ZYG_LAN_HOST__ &nbsp;&bull;&nbsp; Local Network</div>
</div>

<div id="toast"></div>

<script>
  const RESTART_API = 'http://__ZYG_LAN_HOST__:7001';

  function updateClock() {
    const now = new Date();
    const d = now.toLocaleDateString('en-AU', { weekday:'long', day:'numeric', month:'long' });
    const t = now.toLocaleTimeString('en-AU', { hour:'2-digit', minute:'2-digit' });
    document.getElementById('clock').textContent = d + '  —  ' + t;
  }
  updateClock();
  setInterval(updateClock, 10000);

  let toastTimer;
  function showToast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
  }

  // 2026-09-23: cards marked data-probe="api" are asked about via restart_api instead of
  // by fetching their own URL from this browser. A loopback-bound service (Nomologin on
  // 127.0.0.1:8750) can never be probed from another machine — 127.0.0.1 is whatever box
  // you are sitting at — so it read Offline from Windows even while running. restart_api
  // lives beside the apps, so it can answer truthfully for any viewer. Falls back to the
  // direct fetch if the API itself is unreachable, so a dead restart_api does not black
  // out the dots.
  async function probeViaApi(appId) {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), 3000);
    try {
      const res = await fetch(RESTART_API + '/status/' + appId, { signal: ctrl.signal });
      const data = await res.json();
      return !!data.online;
    } finally {
      clearTimeout(id);
    }
  }

  async function probeDirect(url) {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), 3000);
    try {
      await fetch(url, { mode: 'no-cors', signal: ctrl.signal });
      return true;
    } finally {
      clearTimeout(id);
    }
  }

  async function checkStatus(card, dot, label) {
    let online;
    try {
      if (card.dataset.probe === 'api') {
        try {
          online = await probeViaApi(card.dataset.app);
        } catch {
          online = await probeDirect(card.dataset.url);
        }
      } else {
        online = await probeDirect(card.dataset.url);
      }
    } catch {
      online = false;
    }
    dot.classList.toggle('online', online);
    dot.classList.toggle('offline', !online);
    label.textContent = online ? 'Online' : 'Offline';
  }

  function pollAll() {
    document.querySelectorAll('.card[data-url]').forEach(card => {
      checkStatus(card, card.querySelector('[data-status]'), card.querySelector('.status-label'));
    });
  }
  pollAll();
  setInterval(pollAll, 15000);

  document.querySelectorAll('.restart-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.preventDefault();
      e.stopPropagation();
      const appId = btn.dataset.restart;
      const card  = btn.closest('.card');
      const dot   = card.querySelector('[data-status]');
      const label = card.querySelector('.status-label');
      btn.classList.add('spinning');
      btn.disabled = true;
      dot.classList.remove('online', 'offline');
      label.textContent = 'Restarting…';
      showToast('Restarting ' + card.querySelector('.card-name').textContent + '…');
      try {
        const res  = await fetch(RESTART_API + '/restart/' + appId, { method: 'POST' });
        const data = await res.json();
        btn.classList.remove('spinning');
        if (data.ok) {
          btn.classList.add('done');
          showToast('Restarted — waiting for server…');
          let attempts = 0;
          const poll = setInterval(async () => {
            attempts++;
            try {
              const ctrl = new AbortController();
              setTimeout(() => ctrl.abort(), 2000);
              await fetch(card.dataset.url, { mode: 'no-cors', signal: ctrl.signal });
              clearInterval(poll);
              dot.classList.add('online');
              label.textContent = 'Online';
              showToast('Server is back online');
              btn.classList.remove('done');
            } catch {
              if (attempts >= 15) {
                clearInterval(poll);
                label.textContent = 'Check manually';
                btn.classList.remove('done');
              }
            }
          }, 2000);
        } else {
          label.textContent = 'Error';
          showToast('Restart failed: ' + (data.error || 'unknown error'));
        }
      } catch {
        btn.classList.remove('spinning');
        label.textContent = 'API unreachable';
        showToast('Cannot reach restart API — is restart_api.py running?');
      }
      btn.disabled = false;
    });
  });

  // ── Power on/off toggle (added next to each restart button) ──
  const POWER_SVG = '<svg viewBox="0 0 24 24"><path d="M12 4v8"/><path d="M7.5 7.5a6.5 6.5 0 1 0 9 0"/></svg>';

  function syncPower(card) {
    const btn = card.querySelector('.power-btn');
    if (!btn || btn.classList.contains('spinning')) return;
    const online = card.querySelector('[data-status]').classList.contains('online');
    btn.classList.toggle('is-on', online);
    btn.classList.toggle('is-off', !online);
    btn.title = online ? 'Turn off' : 'Turn on';
  }

  document.querySelectorAll('.card[data-app]').forEach(card => {
    const meta    = card.querySelector('.card-meta');
    const restart = meta ? meta.querySelector('.restart-btn') : null;
    if (!meta || !restart) return;
    const appId = card.dataset.app;

    const pbtn = document.createElement('button');
    pbtn.className = 'power-btn';
    pbtn.dataset.power = appId;
    pbtn.innerHTML = POWER_SVG;
    pbtn.title = 'Toggle on/off';
    meta.insertBefore(pbtn, restart);

    pbtn.addEventListener('click', async e => {
      e.preventDefault();
      e.stopPropagation();
      const dot    = card.querySelector('[data-status]');
      const label  = card.querySelector('.status-label');
      const name   = card.querySelector('.card-name').textContent;
      const online = dot.classList.contains('online');
      const action = online ? 'stop' : 'start';

      pbtn.disabled = true;
      if (action === 'start') pbtn.classList.add('spinning');
      dot.classList.remove('online', 'offline');
      label.textContent = online ? 'Stopping…' : 'Starting…';
      showToast((online ? 'Stopping ' : 'Starting ') + name + '…');

      try {
        const res  = await fetch(RESTART_API + '/' + action + '/' + appId, { method: 'POST' });
        const data = await res.json();
        if (!data.ok) {
          pbtn.classList.remove('spinning');
          label.textContent = 'Error';
          showToast(action + ' failed: ' + (data.error || 'unknown error'));
          pbtn.disabled = false;
          syncPower(card);
          return;
        }
        if (action === 'stop') {
          dot.classList.add('offline');
          label.textContent = 'Offline';
          showToast(name + ' stopped');
          pbtn.disabled = false;
          syncPower(card);
        } else {
          let attempts = 0;
          const poll = setInterval(async () => {
            attempts++;
            try {
              const ctrl = new AbortController();
              setTimeout(() => ctrl.abort(), 2000);
              await fetch(card.dataset.url, { mode: 'no-cors', signal: ctrl.signal });
              clearInterval(poll);
              pbtn.classList.remove('spinning');
              dot.classList.add('online');
              label.textContent = 'Online';
              showToast(name + ' is online');
              pbtn.disabled = false;
              syncPower(card);
            } catch {
              if (attempts >= 15) {
                clearInterval(poll);
                pbtn.classList.remove('spinning');
                label.textContent = 'Check manually';
                pbtn.disabled = false;
                syncPower(card);
              }
            }
          }, 2000);
        }
      } catch {
        pbtn.classList.remove('spinning');
        label.textContent = 'API unreachable';
        showToast('Cannot reach restart API — is restart_api.py running?');
        pbtn.disabled = false;
        syncPower(card);
      }
    });
  });

  // Keep each power icon's colour in sync with the card's live status.
  setTimeout(() => document.querySelectorAll('.card[data-app]').forEach(syncPower), 500);
  setInterval(() => document.querySelectorAll('.card[data-app]').forEach(syncPower), 1500);
</script>
</body>
</html>"""


def render_hub_html(host: str = '') -> str:
    """The hub page with every card URL pointed at `host` (default: ZYG_LAN_HOST)."""
    return HUB_HTML.replace(LAN_HOST_PLACEHOLDER, host or LAN_HOST)


class HubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(render_hub_html().encode('utf-8'))

    def log_message(self, *args):
        pass


def run_server():
    server = HTTPServer(('127.0.0.1', PORT), HubHandler)
    server.serve_forever()


if __name__ == '__main__':
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(0.4)
    webbrowser.open(f'http://127.0.0.1:{PORT}')

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.mainloop()
    except Exception:
        while True:
            time.sleep(60)
