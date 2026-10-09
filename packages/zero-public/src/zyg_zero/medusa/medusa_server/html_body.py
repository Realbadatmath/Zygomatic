# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI markup, part 3: the ui-zoom block, its coordinate shim and the body.

Moved verbatim out of medusa_server.py (lines 826-1318); reassembled in html.py.
"""

BODY = """<style id="ui-zoom">
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
<div class="app">

  <!-- ── Left sidebar: 8 tabs ── -->
  <nav class="sidebar">
    <div class="brand">
      <div class="logo-hex"><img src="/favicon.png" alt="Medusa"></div>
      <span class="brand-name">Medusa</span>
    </div>

    <div class="tabs" id="tabs">
      <button class="tab active" data-tab="medusa" data-title="Medusa">Medusa</button>
      <button class="tab" data-tab="inspection" data-title="Inspection">Inspection</button>
      <button class="tab" data-tab="training" data-title="Training">Training</button>
      <button class="tab" data-tab="tab4" data-title="Vicky">Vicky</button>
      <button class="tab" data-tab="tab5" data-title="Models">Models</button>
      <button class="tab" data-tab="tab6" data-title="Tab 6">Tab 6</button>
      <button class="tab" data-tab="resources" data-title="Resources">Resources</button>
    </div>

    <!-- Filled from location.host by the script below: the page states the address the
         browser actually reached it on, so no deployment's address is baked in here. -->
    <div class="sidebar-footer" id="sidebarHost"></div>
  </nav>

  <!-- ── Right: content ── -->
  <main class="content">
    <div class="content-header">
      <span class="content-title" id="contentTitle"><span class="dot"></span>Medusa</span>
    </div>
    <div class="panels" id="panels">
      <section class="panel active" data-panel="medusa">
        <div class="studio">
          <h2 class="studio-title">Character Studio</h2>
          <p class="studio-sub">Generate an original <strong>woman</strong> character in catalog swimwear — contact sheet (angles of your choosing, up to all 48) + FLUX LoRA, using the existing crews pipeline (:5000). Every field is optional; blanks auto-fill. The run <strong>waits for operator approval</strong> before any GPU work starts.</p>
          <div class="studio-grid">
            <label>Name <span class="opt">(optional)</span><input id="m_name" placeholder="auto"></label>
            <label>Age <span class="opt">(optional)</span>
              <select id="m_age"><option value="">auto</option></select>
            </label>
            <label>Hair color <span class="opt">(optional)</span>
              <select id="m_hair">
                <option value="">auto</option>
                <option value="black">black</option>
                <option value="dark brown">dark brown</option>
                <option value="brown">brown</option>
                <option value="light brown">light brown</option>
                <option value="auburn">auburn</option>
                <option value="red">red</option>
                <option value="ginger">ginger</option>
                <option value="blonde">blonde</option>
                <option value="platinum blonde">platinum blonde</option>
                <option value="gray">gray</option>
                <option value="silver">silver</option>
                <option value="white">white</option>
              </select>
            </label>
            <label>Eye color <span class="opt">(optional)</span>
              <select id="m_eyes">
                <option value="">auto</option>
                <option value="brown">brown</option>
                <option value="dark brown">dark brown</option>
                <option value="hazel">hazel</option>
                <option value="green">green</option>
                <option value="blue">blue</option>
                <option value="gray">gray</option>
                <option value="amber">amber</option>
              </select>
            </label>
            <label>Skin tone <span class="opt">(optional)</span>
              <select id="m_skin">
                <option value="">auto</option>
                <option value="fair">fair</option>
                <option value="medium-light">medium-light</option>
                <option value="medium">medium</option>
                <option value="olive">olive</option>
                <option value="tan">tan</option>
                <option value="dark">dark</option>
                <option value="deep">deep</option>
              </select>
            </label>
            <label>Heritage <span class="opt">(optional)</span>
              <select id="m_heritage">
                <option value="">auto</option>
                <option value="African">African</option>
                <option value="African American">African American</option>
                <option value="Arab / Middle Eastern">Arab / Middle Eastern</option>
                <option value="British / Irish">British / Irish</option>
                <option value="Caribbean">Caribbean</option>
                <option value="Central Asian">Central Asian</option>
                <option value="East Asian">East Asian</option>
                <option value="Eastern European">Eastern European</option>
                <option value="Hispanic / Latina">Hispanic / Latina</option>
                <option value="Indigenous American">Indigenous American</option>
                <option value="Mediterranean">Mediterranean</option>
                <option value="Nordic / Scandinavian">Nordic / Scandinavian</option>
                <option value="Pacific Islander">Pacific Islander</option>
                <option value="South Asian">South Asian</option>
                <option value="Southeast Asian">Southeast Asian</option>
                <option value="Western European">Western European</option>
              </select>
            </label>
          </div>
          <div class="ang-box">
            <div class="ang-head">
              <span class="ang-title">Angles</span>
              <span id="ang_count" class="ang-count">—</span>
              <button id="ang_toggle" type="button" class="btn-ghost ang-toggle">Choose angles</button>
            </div>
            <p class="ang-sub">How many angles the contact sheet renders, and which ones. Each angle is one
              generation (~5 min), so the count sets the run length. The <strong>front view</strong> is the
              identity anchor every other cell is edited from — it is always rendered first.</p>
            <div id="ang_presets" class="ang-presets"></div>
            <div id="ang_groups" class="ang-groups">Loading angles…</div>
          </div>
          <label class="studio-prompt-label">Character prompt <span class="opt">(optional — describe the character freely)</span>
            <textarea id="m_prompt" class="studio-prompt" placeholder="e.g. athletic build, warm confident smile, freckles, wavy auburn hair, standing on a sunny beach…"></textarea>
          </label>
          <div class="studio-actions">
            <button id="m_generate" class="btn-primary">Generate Character</button>
            <span class="studio-note">Women only · swimwear · fictional</span>
          </div>
          <div id="m_result" class="studio-result"></div>
        </div>
        <div class="studio-approvals">
          <div class="appr-head">
            <h3 class="appr-title">Pending Approvals</h3>
            <button id="m_refresh" class="btn-ghost">Refresh</button>
          </div>
          <div id="m_pending" class="appr-list">Loading…</div>
        </div>
      </section>
      <section class="panel panel-inspection" data-panel="inspection">
        <div class="subtabs" id="insp-subtabs">
          <button class="subtab active" data-sub="inspections">Inspections</button>
          <button class="subtab" data-sub="contactsheet">Contact Sheet</button>
          <button class="subtab" data-sub="loras">LoRA</button>
        </div>
        <div class="subpanel active" data-subpanel="inspections">
          <iframe id="insp-frame" title="Medusa Inspections"></iframe>
        </div>
        <div class="subpanel" data-subpanel="contactsheet">
          <div class="cs-wrap">
            <div class="cs-head">
              <div>
                <h2 class="train-title">Contact Sheets</h2>
                <p class="train-sub">Sheets prepared in the Training tab. Medusa-only — these are not
                  visible in the workflow dashboard, the asset manager, or the public store.</p>
              </div>
              <div class="cs-head-actions">
                <button id="cs_build_all" class="btn-decline">Build missing sheets</button>
                <button id="cs_refresh" class="btn-decline">Refresh</button>
              </div>
            </div>
            <div id="cs_status" class="sec-status"></div>
            <div id="cs_list" class="cs-list">Loading…</div>
          </div>
        </div>
        <div class="subpanel" data-subpanel="loras">
          <div class="cs-wrap">
            <div class="cs-head">
              <div>
                <h2 class="train-title">Trained LoRAs</h2>
                <p class="train-sub">Finished adapters from the Training tab, with the validation
                  renders each run produced. The path shown is the one a render actually loads.
                  Medusa-only — nothing here comes from the shared character trees.</p>
              </div>
              <div class="cs-head-actions">
                <button id="lr_refresh" class="btn-decline">Refresh</button>
              </div>
            </div>
            <div id="lr_list" class="cs-list">Loading…</div>
          </div>
        </div>
      </section>
      <section class="panel" data-panel="training">
        <div class="train">
          <h2 class="train-title">Contact Sheet Preparation</h2>
          <p class="train-sub">Turn photographs you already have into a canonical multi-angle contact sheet:
            every picture is measured for camera angle, captioned from a fixed vocabulary, QC'd and
            assembled — on CPU, seconds per character. Training a LoRA afterwards is optional and separate.
            <strong>Isolated by design</strong> — this data, and every character prepared here, lives in a
            dedicated store that the public workflow pipeline (the dashboard's
            <code>/workflows</code> board) and the public store never read from.</p>

          <!-- ── Bulk folder import: one folder = one character ── -->
          <div class="train-card">
            <div class="train-card-h"><h3>Import folders — one folder becomes one character</h3></div>
            <p class="train-hint">Drop your prepared character folders into
              <em id="t_root_path">the Medusa import folder</em>, then Scan.
              Each <em>subfolder</em> becomes one character and every picture inside it becomes one sheet cell.
              There is no cap on how many pictures a folder may hold.
              Only this folder is readable — that is deliberate, so a scan can never reach the rest of your files.</p>
            <div class="train-scan-row">
              <input id="t_scan_path" placeholder="(the Medusa import folder)">
              <button id="t_scan" class="btn-decline">Scan folder</button>
              <button id="t_pick_dirs" class="btn-decline" title="Pick folders in the browser instead — works for folders outside the import folder">Browse…</button>
            </div>
            <input id="t_dirpicker" type="file" accept="image/*" multiple webkitdirectory directory hidden>
            <div id="t_scan_result" class="sec-status"></div>
            <div id="t_scan_list" class="train-scan-list"></div>
            <div id="t_scan_actions" class="train-actions" style="display:none">
              <label class="train-inline">Model family
                <select id="t_batch_family"><option value="flux">FLUX</option><option value="sdxl">SDXL</option></select>
              </label>
              <label class="train-inline"><input type="checkbox" id="t_batch_sheets" checked> Build contact sheets automatically</label>
              <button id="t_import" class="btn-primary">Create Contact Sheet</button>
            </div>
            <div id="t_import_status" class="sec-status"></div>
          </div>

          <!-- ── Single character ── -->
          <div class="train-card">
            <div class="train-card-h"><h3>Single character</h3></div>
            <div class="train-grid">
              <label>Name<input id="t_name" placeholder="e.g. Studio Model A"></label>
              <label>Model family
                <select id="t_family"><option value="flux">FLUX</option><option value="sdxl">SDXL</option></select>
              </label>
              <label>Trigger token <span class="opt">(optional — auto-generated)</span><input id="t_trigger" placeholder="auto"></label>
              <label>Caption suffix <span class="opt">(optional — applied to every photo)</span><input id="t_suffix" placeholder="e.g. studio portrait, neutral background"></label>
              <label>Mode
                <select id="t_mode">
                  <option value="identity">Identity — this exact person</option>
                  <option value="body">Body template — build only, no face</option>
                </select>
              </label>
              <label id="t_prompt_wrap" style="display:none">Hair, skin and clothing <span class="opt">(required for body templates — captioned so they stay promptable)</span><input id="t_promptables" placeholder="e.g. short black hair, medium-brown skin, grey tank top and jeans"></label>
            </div>
            <button id="t_create" class="btn-primary">Create Contact Sheet</button>
            <div id="t_create_result" class="studio-result"></div>
          </div>

          <div id="t_list" class="train-list">Loading…</div>
        </div>
      </section>
      <section class="panel" data-panel="tab4">
        <div class="vicky">
          <div class="vchat-bar">
            <select class="vchat-engine" id="v_engine" title="Which assistant answers"></select>
            <select class="vchat-select" id="v_chats" title="Saved chats"></select>
            <button class="vchat-btn" id="v_new">New chat</button>
            <button class="vchat-btn" id="v_rename">Rename</button>
            <button class="vchat-btn" id="v_save">Save</button>
            <button class="vchat-btn" id="v_pics" title="Every picture any chat has made, in one grid">Pictures</button>
            <button class="vchat-btn danger" id="v_del">Delete</button>
            <button class="vchat-btn danger" id="v_clear">Clear all</button>
            <span class="vchat-meta" id="v_meta"></span>
          </div>
          <div class="vicky-gallery" id="v_gallery" hidden></div>
          <div class="vicky-log" id="v_log"></div>
          <input type="file" id="v_file" multiple accept="image/*,video/*" hidden>
          <div class="vicky-previews" id="v_previews"></div>
          <div class="vicky-row">
            <button class="vicky-attach" id="v_attach" title="Attach images or videos" aria-label="Attach images or videos"><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg></button>
            <textarea class="vicky-input" id="v_input" placeholder="Ask Vicky or Victor to build or change something in Medusa…"></textarea>
            <button class="vicky-send" id="v_send">Send</button>
            <button class="vicky-cancel" id="v_cancel">Cancel</button>
          </div>
        </div>
      </section>
      <section class="panel" data-panel="tab5">
        <!-- Models tab (2026-09-18): BASE-model LoRA training per model family.
             Isolated from every other workflow — see bp_medusa_models.py and
             medusa_model_lora.py. Lanes are DERIVED from facts on disk, never
             from a stored status field, so a lane cannot be green while the
             thing it describes is unreachable. -->
        <div class="mdl-wrap">
          <div class="mdl-head">
            <div class="mdl-fams" id="mdlFams"></div>
            <div class="mdl-headright">
              <span class="mdl-active" id="mdlActive"></span>
              <button class="btn-appr" id="mdlNewBtn">New model</button>
            </div>
          </div>
          <p class="mdl-sub">
            A <strong>base</strong> LoRA changes what the model itself renders, for every
            Medusa render on that family. It is trained from its own dataset and applies
            <strong>only</strong> to Medusa app content — Character Studio runs and Vicky's
            pictures. Storyteller, documentary, creature and kids renders are untouched:
            they load a graph that has no slot for it.
            Adults-only (<span id="mdlMinAge">18</span>+) attestation is required before
            training and before switching a model on.
          </p>

          <div class="mdl-new" id="mdlNew" hidden>
            <input type="text" id="mdlNewName" placeholder="Model name (e.g. Medusa base — photoreal)" maxlength="80">
            <select id="mdlNewFamily"></select>
            <input type="number" id="mdlNewScale" value="0.85" min="0" max="2" step="0.05" title="LoRA strength">
            <button class="btn-appr" id="mdlNewCreate">Create</button>
            <button class="btn-decl" id="mdlNewCancel">Cancel</button>
          </div>

          <div class="mdl-board" id="mdlBoard"></div>
        </div>

        <div class="mdl-modal" id="mdlModal" hidden>
          <div class="mdl-modal-inner">
            <div class="mdl-modal-head">
              <strong id="mdlDetailName">—</strong>
              <button class="btn-decl" id="mdlDetailClose">Close</button>
            </div>
            <div class="mdl-modal-body" id="mdlDetailBody"></div>
          </div>
        </div>
      </section>
      <section class="panel" data-panel="tab6"></section>
      <section class="panel" data-panel="resources">
        <div class="res">
          <h2 class="train-title">Resources</h2>
          <p class="train-sub">Upload a page you saved in your own browser and every picture it
            shows is written into <strong>its own folder</strong>. <strong>One page = one
            folder</strong>, named after the file you uploaded. Folders land in the import root
            below, so they show up straight away in <strong>Training &rarr; Scan folder</strong>,
            where one folder is one character.</p>

          <div class="train-card">
            <div class="train-card-h"><h3>Upload saved pages</h3><span class="sec-status" id="r_root"></span></div>
            <p class="train-hint"><em>Save as MHTML where you can.</em> In Chrome that is
              <code>Ctrl+S &rarr; Webpage, Single File</code>: every picture the page displayed is
              baked into the file, so extracting it touches the network zero times and nothing can
              be rate-limited or refused. A plain <code>.html</code> only carries addresses, so
              those pictures have to be fetched again one at a time.</p>
            <p class="train-hint">This reads the page you give it and nothing else — it does not
              browse a site, follow links to other pages, or sign in. Anything the page only shows
              to a logged-in session comes back as <em>HTTP 403 (needs a session)</em> in the error
              list. A gallery split over several pages: save each page, tick <em>merge</em> below,
              and the batch becomes one folder.</p>

            <div class="res-drop" id="r_drop">
              <input type="file" id="r_file" multiple accept=".html,.htm,.xhtml,.mhtml,.mht" hidden>
              <div class="res-drop-t">Drop saved pages here</div>
              <div class="res-drop-s">or <button class="btn-ghost" id="r_pick">choose files</button>
                &nbsp;&mdash;&nbsp; .mhtml, .mht, .html</div>
            </div>
            <div class="res-files" id="r_picked"></div>

            <div class="res-or"><span>or type the addresses yourself</span></div>

            <label class="res-urls-label">Addresses &mdash; one per line
              <span class="opt">(a picture link is fetched directly; a page link is read once for
              the pictures on it, and links it holds to other pages are not followed)</span>
              <textarea id="r_urls" spellcheck="false" placeholder="https://example.com/gallery/01.jpg
https://example.com/gallery/02.jpg
https://example.com/gallery/page-2

# lines starting with # are ignored"></textarea>
            </label>
            <div class="res-urlbar">
              <span class="sec-status" id="r_urlcount"></span>
              <span class="res-spacer"></span>
              <label class="res-inline">Folder name
                <input id="r_urlset" type="text"
                       placeholder="auto — the character named on the page"></label>
            </div>

            <div class="res-opts">
              <label>Parallel downloads <span class="opt">(1&ndash;6 &mdash; 2 is about one
                request a second at the default delay)</span>
                <input id="r_workers" type="number" min="1" max="6" step="1" value="2"></label>
              <label>Delay between requests <span class="opt">(seconds, per worker)</span>
                <input id="r_delay" type="number" min="0" max="60" step="0.5" value="2"></label>
              <label>Smallest file kept <span class="opt">(KB &mdash; drops icons and spacers)</span>
                <input id="r_minkb" type="number" min="0" step="1" value="15"></label>
              <label>Smallest edge kept <span class="opt">(px &mdash; drops thumbnails)</span>
                <input id="r_minedge" type="number" min="0" step="16" value="256"></label>
              <label>Skip addresses containing <span class="opt">(comma-separated, matched
                anywhere in the address &mdash; never requested at all)</span>
                <input id="r_exclude" type="text" placeholder="masonry"></label>
              <label>Base address <span class="opt">(only for an uploaded .html with relative links)</span>
                <input id="r_base" type="text" placeholder="https://…"></label>
            </div>

            <label class="res-urls-label" style="margin-bottom:14px">Stop collecting at
              <span class="opt">(one phrase per line, case-insensitive. Everything from the first
              of these onwards is left alone &mdash; this is what keeps <em>Related Galleries</em>
              and <em>Free Sites</em> out. Clear the box to collect the whole page.)</span>
              <textarea id="r_stop" spellcheck="false" class="res-stop"></textarea>
            </label>

            <div class="res-checks">
              <label><input type="checkbox" id="r_collapse" checked> Collapse duplicate sizes
                &mdash; a gallery shows each photo as a thumbnail, a full-size and one or more
                srcset widths; fetch only the biggest of each</label>
              <label><input type="checkbox" id="r_similar" checked> Drop near-identical pictures
                &mdash; catches the same photo under an unrelated filename, keeping the larger
                copy</label>
              <label><input type="checkbox" id="r_junk" checked> Skip related / sponsored /
                promo blocks</label>
              <label><input type="checkbox" id="r_mergename2" checked> Name each folder after the
                character on the page, and add to that character's folder if they already have
                one &mdash; so a second gallery of the same person joins it instead of making
                a <em>-2</em></label>
              <label><input type="checkbox" id="r_robots" checked> Obey robots.txt</label>
              <label><input type="checkbox" id="r_deep"> Deep scan &mdash; also read addresses out
                of inline scripts. <em>Off by default:</em> that blob usually lists every other
                gallery on the site, and is the main reason a page seems to hold far more pictures
                than it shows</label>
              <label><input type="checkbox" id="r_merge"> Merge this whole batch into one folder
                <input type="text" id="r_mergename" placeholder="folder name" disabled></label>
            </div>

            <div class="train-actions">
              <button class="btn-primary" id="r_go" disabled>Extract to folders</button>
              <button class="btn-ghost" id="r_preview" disabled>Dry run &mdash; what would it take?</button>
              <span class="sec-status" id="r_status"></span>
            </div>
            <div id="r_previewout" class="res-preview"></div>
          </div>

          <div class="train-card">
            <div class="train-card-h"><h3>Extraction jobs</h3>
              <button class="btn-ghost" id="r_refresh">Refresh</button></div>
            <div id="r_jobs" class="train-list"><div class="train-empty">Nothing running.</div></div>
          </div>

          <div class="train-card">
            <div class="train-card-h"><h3>Folders</h3><span class="sec-status" id="r_setcount"></span></div>
            <div id="r_sets" class="train-list">Loading…</div>
          </div>
        </div>

        <!-- Picture viewer. Opens on a thumbnail click; walks the WHOLE folder,
             not just the eight previews on the card. -->
        <div class="res-lb" id="r_lb" tabindex="-1">
          <div class="res-lb-bar">
            <span class="res-lb-name" id="r_lbname"></span>
            <span class="res-lb-count" id="r_lbcount"></span>
            <span class="res-lb-hint"><kbd>&larr;</kbd> <kbd>&rarr;</kbd> move
              &middot; <kbd>Esc</kbd> close</span>
            <span class="res-spacer"></span>
            <button class="btn-ghost" id="r_lbfull">Open original</button>
            <button class="btn-ghost" id="r_lbclose">Close</button>
          </div>
          <div class="res-lb-stage" id="r_lbstage">
            <button class="res-lb-nav prev" id="r_lbprev" title="Previous (←)">&lsaquo;</button>
            <img id="r_lbimg" alt="">
            <button class="res-lb-nav next" id="r_lbnext" title="Next (→)">&rsaquo;</button>
          </div>
        </div>
      </section>
    </div>
  </main>

</div>

"""
