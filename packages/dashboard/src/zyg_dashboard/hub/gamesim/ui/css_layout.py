# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stylesheet: main body layout, left nav, creation panel, summary bar, and the ui-zoom pair."""

CSS_LAYOUT = """  /* ── Main body layout ── */
  .main-body {
    display: flex;
    gap: 20px;
    align-items: flex-start;
  }

  /* ── Left nav ── */
  .left-nav {
    flex-shrink: 0;
    width: 160px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 8px;
    position: sticky;
    top: 24px;
  }

  .nav-tab {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 10px 12px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: var(--muted);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    text-align: left;
    transition: background 0.2s, color 0.2s;
    width: 100%;
  }

  .nav-tab svg {
    width: 15px; height: 15px;
    stroke: currentColor;
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    flex-shrink: 0;
  }

  .nav-tab:hover:not(.active) { background: rgba(255,255,255,0.05); color: var(--text); }

  .nav-tab.active {
    background: rgba(244,114,182,0.12);
    color: #f472b6;
    border: 1px solid rgba(244,114,182,0.2);
  }

  .content { flex: 1; min-width: 0; }

  /* ── Creation panel ── */
  .create-toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }

  .create-search-wrap {
    position: relative;
    flex: 1;
    min-width: 200px;
  }

  .create-search-wrap svg {
    position: absolute;
    left: 12px; top: 50%;
    transform: translateY(-50%);
    width: 14px; height: 14px;
    stroke: var(--muted);
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
    pointer-events: none;
  }

  .create-search {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text);
    font-size: 13px;
    padding: 9px 12px 9px 34px;
    outline: none;
    transition: border-color 0.2s;
  }
  .create-search:focus { border-color: rgba(244,114,182,0.4); }
  .create-search::placeholder { color: var(--muted); }

  .btn-sm {
    padding: 8px 14px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--muted);
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .btn-sm:hover { color: var(--text); border-color: rgba(244,114,182,0.3); }
  .btn-sm.btn-pink {
    background: rgba(244,114,182,0.12);
    border-color: rgba(244,114,182,0.3);
    color: #f472b6;
  }
  .btn-sm.btn-pink:hover { background: rgba(244,114,182,0.2); }

  .games-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: 10px;
    margin-bottom: 20px;
  }

  .game-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s, transform 0.15s;
    user-select: none;
    position: relative;
  }

  .game-card:hover { border-color: rgba(244,114,182,0.25); transform: translateY(-1px); }

  .game-card.selected {
    border-color: rgba(244,114,182,0.5);
    background: rgba(244,114,182,0.06);
  }

  .game-card.selected::after {
    content: "✓";
    position: absolute;
    top: 10px; right: 12px;
    width: 18px; height: 18px;
    background: #f472b6;
    border-radius: 50%;
    font-size: 10px;
    font-weight: 700;
    color: #07070f;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 18px;
    text-align: center;
  }

  .gc-name {
    font-size: 13px;
    font-weight: 700;
    color: #f1f5f9;
    margin-bottom: 8px;
    padding-right: 22px;
  }

  .gc-spec {
    font-size: 11px;
    color: var(--muted);
    margin-bottom: 10px;
  }

  .gc-spec span { color: #94a3b8; }

  .gc-installed {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid transparent;
  }

  .gc-installed::before {
    content: "";
    width: 6px; height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .gc-installed.yes {
    background: rgba(74,222,128,0.1);
    color: #4ade80;
    border-color: rgba(74,222,128,0.25);
  }
  .gc-installed.yes::before { background: #4ade80; box-shadow: 0 0 4px rgba(74,222,128,0.6); }

  .gc-installed.no {
    background: rgba(100,116,139,0.1);
    color: #64748b;
    border-color: rgba(100,116,139,0.2);
  }
  .gc-installed.no::before { background: #475569; }

  .gc-installed:hover { opacity: 0.75; }

  /* ── Summary bar ── */
  .summary-bar {
    background: var(--surface);
    border: 1px solid rgba(244,114,182,0.2);
    border-radius: 12px;
    padding: 16px 20px;
    display: flex;
    align-items: center;
    gap: 24px;
    flex-wrap: wrap;
  }

  .sum-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .sum-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
  }

  .sum-value {
    font-size: 18px;
    font-weight: 700;
    color: #f1f5f9;
    font-variant-numeric: tabular-nums;
  }

  .sum-value.pink { color: #f472b6; }

  .sum-btn {
    margin-left: auto;
    padding: 10px 22px;
    border-radius: 10px;
    border: none;
    background: linear-gradient(135deg, #f472b6, #c084fc);
    color: #07070f;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.2s;
  }
  .sum-btn:hover { opacity: 0.9; transform: translateY(-1px); }
  .sum-btn:disabled { opacity: 0.3; cursor: not-allowed; transform: none; }

  @keyframes fadeDown {
    from { opacity: 0; transform: translateY(-12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(12px); }
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
"""
