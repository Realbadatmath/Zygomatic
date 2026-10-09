// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

  // ── State ─────────────────────────────────────────────────────────────────
  let currentJobId  = window.ZPUB_BOOT.activeJobId;
  let inviteToken   = window.ZPUB_BOOT.inviteToken;
  let evtSource     = null;
  let _lastPrompt   = '';  // saved so we can pre-fill on abort/error
  let _selectedStyle = 'documentary';
  let _narrationEnabled = true;  // documentary=on by default
  let _sceneMode = 'continuous';  // 'independent' or 'continuous' — continuous is default
  let _uploadedFiles = [];

  // ── Styles dropdown ───────────────────────────────────────────────────────
  function toggleStylesDropdown(e) {
    e.stopPropagation();
    document.getElementById('styles-dropdown').classList.toggle('open');
  }
  document.addEventListener('click', () => {
    const dd = document.getElementById('styles-dropdown');
    if (dd) dd.classList.remove('open');
  });
  function selectStyle(style, el) {
    let _stPipelinePref = null;
    if (style === 'contact_sheet') {
      _stPipelinePref = 'contact_sheet';
      style = 'storyteller';
      const stEl = document.querySelector('.style-option[data-style="storyteller"]');
      if (stEl) el = stEl;
    }
    _selectedStyle = style;
    document.querySelectorAll('.style-option').forEach(o => o.classList.remove('active'));
    if (el) el.classList.add('active');
    const icons  = { documentary: '🎬', video: '🎥', manga: '📖', intro: '🎞', storyteller: '🎭', contact_sheet: '📋', creature: '🐉', character: '', templates: '🗂' };
    const labels = { documentary: 'Documentary', video: 'Video', manga: 'Manga', intro: 'Intro', storyteller: 'Storyteller', contact_sheet: 'Multi-Angle Contact Sheet', creature: 'Creature Creation', character: 'Character Generation', templates: 'Templates' };
    const displayStyle = _stPipelinePref === 'contact_sheet' ? 'contact_sheet' : style;
    const iconEl = document.getElementById('styles-icon');
    const labelEl = document.getElementById('styles-label');
    if (iconEl) iconEl.textContent = icons[displayStyle] || icons[style] || '🎬';
    if (iconEl) iconEl.style.display = (style === 'character') ? 'none' : '';
    if (labelEl) labelEl.textContent = labels[displayStyle] || labels[style] || style;
    document.getElementById('styles-dropdown').classList.remove('open');
    // Toggle upload area
    const ua = document.getElementById('upload-area');
    if (ua) ua.style.display = (style === 'video' || style === 'manga') ? 'block' : (style === 'creature' ? 'block' : 'none');
    // Toggle duration picker — creature trains a LoRA, not a timed video
    const dw = document.getElementById('duration-wrap');
    if (dw) dw.style.display = (style === 'video' || style === 'manga') ? 'block' : 'none';
    // Toggle scene mode dropdown
    const sms = document.getElementById('scene-mode-select');
    if (sms) sms.style.display = style === 'video' ? 'inline-block' : 'none';
    // Toggle ending text input (intro mode only)
    const etw = document.getElementById('ending-text-wrap');
    if (etw) etw.style.display = style === 'intro' ? 'block' : 'none';
    const vidCharWrap = document.getElementById('vid-char-library-wrap');
    if (vidCharWrap) vidCharWrap.style.display = style === 'video' ? 'block' : 'none';
    const crWrap = document.getElementById('creature-library-wrap');
    if (crWrap) crWrap.style.display = style === 'creature' ? 'block' : 'none';
    const crOpts = document.getElementById('creature-options-wrap');
    if (crOpts) crOpts.style.display = style === 'creature' ? 'block' : 'none';
    if (style === 'creature') {
      crOpenCreatureLibrary();
    } else {
      crClearSelectedCreature();
    }
    const vidStillHint = document.getElementById('video-still-hint');
    if (vidStillHint) vidStillHint.style.display = style === 'video' ? 'block' : 'none';
    if (style !== 'video') vidClearSelectedChar();
    // Toggle main form vs storyteller/character wizard vs templates panel
    const mainForm = document.getElementById('form-section');
    const stWizard = document.getElementById('storyteller-wizard');
    const tplPanel = document.getElementById('templates-panel');
    const isWizard = style === 'storyteller' || style === 'character';
    const isTpl    = style === 'templates';
    if (mainForm) mainForm.style.display = (isWizard || isTpl) ? 'none' : 'block';
    if (stWizard) stWizard.style.display = isWizard ? 'block' : 'none';
    if (tplPanel) tplPanel.style.display = isTpl    ? 'block' : 'none';
    if (isTpl) svPollStatus();
    if (isTpl) svLoadTournaments();
    if (_stPipelinePref === 'contact_sheet' && stWizard) {
      const csRadio = document.querySelector('input[name="st-pipeline-mode"][value="contact_sheet"]');
      if (csRadio) { csRadio.checked = true; if (typeof stOnPipelineModeChange === 'function') stOnPipelineModeChange(); }
      const wrap = document.getElementById('st-pipeline-mode-wrap');
      if (wrap) try { wrap.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch {}
    }
    // Character-only mode: only show step 1, update header, hide other steps
    window._stCharOnlyMode = (style === 'character');
    const hdr = document.getElementById('st-step1-header');
    if (style === 'character') {
      if (hdr) hdr.textContent = 'Character Generation';
      // Ensure we're on step 1 (reset if coming back)
      const s1 = document.getElementById('st-step1');
      if (s1) s1.style.display = 'block';
      for (let i = 2; i <= 5; i++) {
        const si = document.getElementById(`st-step${i}`);
        if (si) si.style.display = 'none';
      }
      // Re-show the (possibly collapsed) form when re-entering character mode.
      const _fForm = document.getElementById('st-step1-form');
      if (_fForm) _fForm.style.display = '';
    } else if (style === 'storyteller') {
      if (hdr) hdr.textContent = '🎭 Step 1 — Create Your Character';
    }
    // Ensure the wizard model selector mirrors the main selector (since the main
    // form is hidden in wizard mode).
    try {
      _syncModelFamilySelect(_getModelFamily());
    } catch {}
    // Set narration default: documentary=on, others=off
    _narrationEnabled = (style === 'documentary');
    _updateNarrationBtn();
    _syncSubsWithNarration();
    // Update placeholder
    const ta = document.getElementById('prompt-input');
    if (ta) ta.placeholder = style === 'video'
      ? 'e.g. Create a cinematic video about ancient Sparta…\ne.g. Make a video about the rise of the Roman Empire…'
      : style === 'manga'
      ? 'e.g. A manga story about a lone samurai crossing a haunted forest…\ne.g. Comic panels: detectives unravel a cold case in neo-Tokyo…'
      : style === 'intro'
      ? 'e.g. Zygomatic Studios — a short cinematic intro reveal\ne.g. Grand opening title for a documentary about Rome…'
      : style === 'creature'
      ? 'e.g. A crimson dragon with obsidian scales and glowing amber eyes…\ne.g. A bioluminescent deep-sea leviathan with translucent fins…'
      : 'e.g. Make a documentary about the fall of the Roman Empire…\ne.g. Create a documentary about the Zodiac Killer case…';
    const _docHint = document.getElementById('adv-doc-cap-hint');
    if (_docHint) _docHint.style.display = (style === 'documentary') ? 'block' : 'none';
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  }

  // ── Sports video pipeline ────────────────────────────────────────────────
  var _svSelectedSport = 'football';
  var _svPollTimer = null;

  // Default date input to today
  (function() {
    var el = document.getElementById('sv-date-input');
    if (el) {
      var now = new Date();
      var y = now.getFullYear();
      var m = String(now.getMonth() + 1).padStart(2, '0');
      var d = String(now.getDate()).padStart(2, '0');
      el.value = y + '-' + m + '-' + d;
    }
  })();

  // Tournament dropdown fetch
  function svLoadTournaments() {
    var sport = _svSelectedSport;
    var dateEl = document.getElementById('sv-date-input');
    var date = dateEl && dateEl.value ? dateEl.value : new Date().toISOString().slice(0, 10);
    var sel = document.getElementById('sv-tournament-select');
    var loading = document.getElementById('sv-tournament-loading');
    if (!sel) return;
    if (loading) loading.style.display = '';
    sel.disabled = true;
    fetch('/api/sports-video/tournaments?sport=' + encodeURIComponent(sport) + '&date=' + encodeURIComponent(date))
      .then(function(r) { return r.json(); })
      .then(function(d) {
        sel.innerHTML = '<option value="">All tournaments</option>';
        (d.tournaments || []).forEach(function(t) {
          var opt = document.createElement('option');
          opt.value = t.name;
          opt.textContent = t.name + ' (' + t.count + ')';
          sel.appendChild(opt);
        });
        sel.disabled = false;
        if (loading) loading.style.display = 'none';
      })
      .catch(function() {
        sel.disabled = false;
        if (loading) loading.style.display = 'none';
      });
  }

  // Reload tournaments when date changes
  (function() {
    var dateEl = document.getElementById('sv-date-input');
    if (dateEl) dateEl.addEventListener('change', svLoadTournaments);
    svLoadTournaments(); // initial load
  })();

  function svSelectSport(sport, el) {
    _svSelectedSport = sport;
    document.querySelectorAll('.sv-sport-card').forEach(function (c) { c.classList.remove('active'); });
    if (el) el.classList.add('active');
    svLoadTournaments();
  }

  function svUpdateStatusUI(d) {
    var dot   = document.getElementById('sv-state-dot');
    var lbl   = document.getElementById('sv-state-label');
    var pLbl  = document.getElementById('sv-progress-label');
    var pWrap = document.getElementById('sv-progress-bar-wrap');
    var pBar  = document.getElementById('sv-progress-bar');
    var vidEl = document.getElementById('sv-last-video-info');
    if (!dot) return;
    var colors = { idle: '#4b5563', running: '#f59e0b', done: '#22c55e', error: '#ef4444' };
    dot.style.background = colors[d.state] || '#4b5563';
    var stepMap = { init: 'Initialising', vram_check: 'Checking VRAM', build_template: 'Building template',
      tts: 'Generating narration', render: 'Rendering frames', composite: 'Compositing video',
      cleanup: 'Cleaning up', done: 'Done ✓', error: 'Error ✗' };
    lbl.textContent = d.state === 'running'
      ? 'Running — ' + (stepMap[d.step] || d.step || '…') + (d.sport ? ' · ' + d.sport : '')
      : d.state === 'done'  ? 'Last render complete ✓'
      : d.state === 'error' ? 'Error: ' + (d.last_error || '').slice(0, 80)
      : 'Pipeline idle';
    var pct = d.progress || 0;
    pLbl.textContent = d.state === 'running' ? pct + '%' : '';
    pWrap.style.display = d.state === 'running' ? 'block' : 'none';
    if (pBar) pBar.style.width = pct + '%';
    if (vidEl) {
      if (d.last_video) {
        vidEl.textContent = '↳ Last: ' + d.last_video.split('/').pop() +
          (d.last_video_size_mb ? ' · ' + d.last_video_size_mb + ' MB' : '');
        vidEl.style.display = 'block';
      } else {
        vidEl.style.display = 'none';
      }
    }
  }

  function svPollStatus() {
    clearTimeout(_svPollTimer);
    fetch('/api/sports-video/status')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (d) {
        svUpdateStatusUI(d);
        if (d.state === 'running' && document.getElementById('templates-panel').style.display !== 'none') {
          _svPollTimer = setTimeout(svPollStatus, 4000);
        }
      })
      .catch(function () {});
  }

  function triggerSportsBettingPipeline(isTest) {
    var btn = isTest ? document.getElementById('sv-test-btn') : document.getElementById('sv-generate-btn');
    var msg = document.getElementById('sv-trigger-msg');
    if (btn) { btn.disabled = true; btn.textContent = isTest ? 'Running test…' : 'Starting…'; }
    if (msg) msg.textContent = '';
    var dateEl = document.getElementById('sv-date-input');
    var selectedDate = dateEl && dateEl.value ? dateEl.value : new Date().toISOString().slice(0, 10);
    var tourSel = document.getElementById('sv-tournament-select');
    var tournament = tourSel && tourSel.value ? tourSel.value : null;
    fetch('/api/sports-video/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sport: _svSelectedSport, date: selectedDate, tournament: tournament, test: isTest || false })
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) {
        var matchInfo = d.match_count ? d.match_count + ' matches · ' : '';
        var testTag = d.test ? ' [TEST]' : '';
        if (msg) msg.textContent = '✓ Pipeline started' + testTag + ' · ' + _svSelectedSport + ' · ' + selectedDate + ' · ' + matchInfo + (d.data_file || '').split('/').pop();
        if (btn) { btn.disabled = false; btn.textContent = isTest ? '⚗ Test' : 'Generate Sports Video →'; }
        svPollStatus();
      } else {
        if (msg) { msg.textContent = '✗ ' + (d.error || 'Unknown error'); msg.style.color = '#f87171'; }
        if (btn) { btn.disabled = false; btn.textContent = isTest ? '⚗ Test' : 'Generate Sports Video →'; }
      }
    })
    .catch(function () {
      if (msg) { msg.textContent = '✗ Request failed'; msg.style.color = '#f87171'; }
      if (btn) { btn.disabled = false; btn.textContent = isTest ? '⚗ Test' : 'Generate Sports Video →'; }
    });
  }

  function _syncSubsWithNarration() {
    const subsEl = document.getElementById('adv-out-subs');
    if (!subsEl) return;
    const docWithVoice = (_selectedStyle === 'documentary' && _narrationEnabled);
    if (docWithVoice) {
      subsEl.checked = true;
      subsEl.disabled = true;
      subsEl.title = 'Subtitles are always on when Documentary narrator voice is enabled';
    } else {
      subsEl.disabled = false;
      subsEl.title = '';
    }
  }

  function _updateNarrationBtn() {
    const btn = document.getElementById('narration-btn');
    const lbl = document.getElementById('narration-label');
    if (!btn) return;
    if (_narrationEnabled) {
      btn.classList.remove('off');
      btn.firstChild.textContent = '🎙️ ';
      lbl.textContent = 'Voice On';
    } else {
      btn.classList.add('off');
      btn.firstChild.textContent = '🔇 ';
      lbl.textContent = 'No Voice';
    }
    _syncSubsWithNarration();
  }

  function toggleNarration() {
    _narrationEnabled = !_narrationEnabled;
    _updateNarrationBtn();
  }

  function setSceneMode(mode) {
    _sceneMode = (mode === 'continuous') ? 'continuous' : 'independent';
    const sel = document.getElementById('scene-mode-select');
    if (sel) sel.value = _sceneMode;
  }

  function syncDurationFromMainSelect() {
    if (_selectedStyle !== 'video' && _selectedStyle !== 'manga' && _selectedStyle !== 'creature') return;
    const durSel = document.getElementById('duration-select');
    if (!durSel) return;
    const totalSec = parseFloat(durSel.value) || 30;
    _advBtnState['total-dur'] = String(totalSec);
    document.querySelectorAll('#adv-panel-duration .adv-btn-opt').forEach(btn => {
      const onclick = btn.getAttribute('onclick') || '';
      if (!onclick.includes("'total-dur'")) return;
      btn.classList.toggle('active', btn.getAttribute('data-val') === String(totalSec));
    });
    let sceneCount = 1;
    let sceneDur = totalSec;
    if (totalSec <= 15) {
      sceneCount = 1;
      sceneDur = totalSec;
    } else if (totalSec <= 45) {
      sceneCount = Math.min(3, Math.max(2, Math.round(totalSec / 15)));
      sceneDur = Math.min(15, Math.ceil(totalSec / sceneCount));
    } else {
      sceneCount = Math.min(12, Math.max(1, Math.round(totalSec / 15)));
      sceneDur = 15;
    }
    const scEl = document.getElementById('adv-scene-count');
    if (scEl) {
      scEl.value = String(sceneCount);
      const v = document.getElementById('adv-scene-count-val');
      if (v) v.textContent = String(sceneCount);
    }
    _advBtnState['scene-dur'] = String(sceneDur);
    document.querySelectorAll('#adv-panel-duration .adv-btn-opt').forEach(btn => {
      const onclick = btn.getAttribute('onclick') || '';
      if (!onclick.includes("'scene-dur'")) return;
      btn.classList.toggle('active', btn.getAttribute('data-val') === String(sceneDur));
    });
  }

  function onDurationChange(val) {
    syncDurationFromMainSelect();
    const sel = document.getElementById('scene-mode-select');
    if (!sel) return;
    const totalSec = parseFloat(val) || 30;
    const isSingle = totalSec <= 15;
    if (isSingle) {
      // Force and lock to Single Scene
      _sceneMode = 'independent';
      sel.value = 'single_scene';
      sel.disabled = true;
      sel.title = '15 sec or less = 1 scene — chaining requires 2+ scenes';
    } else {
      // Restore normal options
      sel.disabled = false;
      sel.title = 'Scene chaining mode';
      // Restore to whatever was selected before (default continuous)
      if (sel.value === 'single_scene') {
        _sceneMode = 'continuous';
        sel.value = 'continuous';
      }
    }
  }

  // Initialize duration-dependent UI state on page load
  document.addEventListener('DOMContentLoaded', function() {
    const durSel = document.getElementById('duration-select');
    if (durSel) onDurationChange(durSel.value);
    const _docHint = document.getElementById('adv-doc-cap-hint');
    if (_docHint && _selectedStyle === 'documentary') _docHint.style.display = 'block';
    _narrationEnabled = (_selectedStyle === 'documentary');
    _updateNarrationBtn();
  });

  // ── Image upload handlers ─────────────────────────────────────────────────
  function handleFileInput(files) {
    for (const f of files) {
      if (_uploadedFiles.length < 40) _uploadedFiles.push(f);
    }
    renderThumbs();
  }
  function handleDrop(e) {
    e.preventDefault();
    document.getElementById('upload-area').classList.remove('drag-over');
    handleFileInput(e.dataTransfer.files);
  }
  function clearUploads() {
    _uploadedFiles = [];
    document.getElementById('image-file-input').value = '';
    renderThumbs();
  }
  function renderThumbs() {
    const container = document.getElementById('upload-thumbs');
    const ua = document.getElementById('upload-area');
    const clr = document.getElementById('upload-clear');
    container.innerHTML = '';
    _uploadedFiles.forEach(f => {
      const img = document.createElement('img');
      img.className = 'upload-thumb';
      img.src = URL.createObjectURL(f);
      container.appendChild(img);
    });
    if (_uploadedFiles.length) {
      ua.classList.add('has-files');
      clr.style.display = 'block';
    } else {
      ua.classList.remove('has-files');
      clr.style.display = 'none';
    }
  }

  // Stage → percentage map
  const STAGE_PCT = {
    '1': 12, '2': 28, '3': 44, '4': 60, '5': 76, '6': 90,
    'connecting': 4, 'starting': 8, 'done': 100,
  };

  function _stageToPercent(stage) {
    if (!stage) return 0;
    const s = stage.toLowerCase();
    const m = stage.match(/stage\s*(\d)/i);
    if (m) return STAGE_PCT[m[1]] || 50;
    if (/connect/i.test(stage))  return STAGE_PCT.connecting;
    if (/start/i.test(stage))    return STAGE_PCT.starting;
    // Named late-pipeline stages → near-complete values
    if (/audio|foley|bgm|music|sound/i.test(s))    return 82;
    if (/assembl|chain|stitch|merge|blend/i.test(s)) return 88;
    if (/upscal|esrgan|enhance/i.test(s))            return 72;
    if (/caption|subtitle|overlay|burn/i.test(s))    return 92;
    if (/export|render|finaliz|output/i.test(s))     return 96;
    if (/temporal|rife|interpolat/i.test(s))         return 68;
    if (/object.track|tracking/i.test(s))            return 64;
    return 50;
  }

  function _setRing(pct) {
    const circ = 2 * Math.PI * 22; // r=22 → 138.23
    const arc  = document.getElementById('ring-arc');
    const lbl  = document.getElementById('ring-pct');
    if (!arc) return;
    arc.style.strokeDashoffset = circ * (1 - pct / 100);
    lbl.textContent = pct < 5 ? '—' : pct + '%';
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    const ta = document.getElementById('prompt-input');
    if (ta) {
      ta.addEventListener('input', () => {
        document.getElementById('char-count').textContent = ta.value.length;
      });
      ta.addEventListener('keydown', e => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submitPrompt();
      });
    }

    // Resume an active job if loaded via /job/<id>
    if (currentJobId) {
      document.getElementById('form-section').style.display = 'none';
      document.getElementById('status-section').style.display = '';
      // Immediately fetch current status so download links appear on refresh
      // without waiting for the SSE stream to connect.
      fetch(`/api/status/${currentJobId}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) { startStream(currentJobId); return; }
          // Save the prompt from any status fetch so abort-handling can pre-fill it
          if (data.prompt) _lastPrompt = data.prompt;
          if (data.status === 'done') {
            showResultCard(data.output_files, currentJobId);
          } else if (data.status === 'failed' || data.status === 'stopped') {
            showErrorCard(data.error || 'The pipeline was interrupted.');
          } else {
            // Still in progress — start live stream
            startStream(currentJobId);
          }
        })
        .catch(() => startStream(currentJobId));
    }
  });

  // ── Submit ────────────────────────────────────────────────────────────────
  function _confirmDocumentaryCaps(prompt, pipelineOptions) {
    if (_selectedStyle !== 'documentary') return true;
    const msgs = [];
    const td = pipelineOptions && pipelineOptions.total_duration_sec;
    if (td && td < 300) {
      msgs.push(
        'Documentary mode targets ~10–14 min by default. Your duration setting (' +
        td + ' sec) will cap script length and image count. Continue?'
      );
    }
    const sc = pipelineOptions && pipelineOptions.scene_count;
    if (sc) {
      msgs.push(
        'Scene count (' + sc + ') will cap scholarly documentary image generation (not the full default set). Continue?'
      );
    }
    if (/\b(story|tale|manga|comic|panel|ronin|samurai adventure)\b/i.test(prompt)) {
      msgs.push(
        'Your prompt looks like a story/manga. Consider Manga or Video style instead. Continue with Documentary?'
      );
    }
    for (const m of msgs) {
      if (!confirm(m)) return false;
    }
    return true;
  }

  async function submitPrompt() {
    const ta     = document.getElementById('prompt-input');
    const prompt = ta.value.trim();
    if (!prompt) { ta.focus(); return; }
    _lastPrompt = prompt;

    const btn = document.getElementById('submit-btn');
    btn.disabled    = true;
    btn.innerHTML   = '<span class="spinner"></span>Submitting…';

    try {
      const _vsEl = document.getElementById('vs-select');
      const _visualStyle = _vsEl ? _vsEl.value : 'cinematic';
      const _modelFamily = _getModelFamily();
      const _pipelineOptions = collectPipelineOptions();
      if (!_confirmDocumentaryCaps(prompt, _pipelineOptions)) {
        btn.disabled = false;
        btn.innerHTML = 'Create →';
        return;
      }
      let resp;
      if (_selectedStyle === 'video') {
        const fd = new FormData();
        syncDurationFromMainSelect();
        collectPipelineOptions();
        const durSel = document.getElementById('duration-select');
        const totalSec = durSel ? (parseFloat(durSel.value) || 30) : 30;
        fd.append('prompt', prompt);
        fd.append('invite_token', inviteToken);
        fd.append('pipeline_style', 'video');
        fd.append('video_duration_minutes', String(totalSec / 60));
        fd.append('narration_enabled', _narrationEnabled ? 'true' : 'false');
        fd.append('visual_style', _visualStyle);
        fd.append('model_family', _modelFamily);
        fd.append('pipeline_options', JSON.stringify(_pipelineOptions));
        fd.append('scene_mode', _sceneMode);
        if (window._vidSelectedChar && window._vidSelectedChar.char_id) {
          fd.append('char_id', window._vidSelectedChar.char_id);
        }
        _uploadedFiles.forEach((f, i) => fd.append('images', f, f.name));
        resp = await fetch('/api/submit', { method: 'POST', body: fd });
      } else if (_selectedStyle === 'manga') {
        const fd = new FormData();
        syncDurationFromMainSelect();
        collectPipelineOptions();
        const durSel = document.getElementById('duration-select');
        const totalSec = durSel ? (parseFloat(durSel.value) || 30) : 30;
        fd.append('prompt', prompt);
        fd.append('invite_token', inviteToken);
        fd.append('pipeline_style', 'manga');
        fd.append('video_duration_minutes', String(totalSec / 60));
        fd.append('narration_enabled', _narrationEnabled ? 'true' : 'false');
        fd.append('visual_style', 'manga');
        fd.append('model_family', _modelFamily);
        fd.append('pipeline_options', JSON.stringify(_pipelineOptions));
        fd.append('scene_mode', 'independent');
        _uploadedFiles.forEach((f, i) => fd.append('images', f, f.name));
        resp = await fetch('/api/submit', { method: 'POST', body: fd });
      } else if (_selectedStyle === 'creature') {
        const fd = new FormData();
        fd.append('prompt', prompt);
        fd.append('invite_token', inviteToken);
        fd.append('pipeline_style', 'creature');
        fd.append('narration_enabled', 'false');
        fd.append('visual_style', 'cinematic');
        fd.append('model_family', _modelFamily);
        fd.append('pipeline_options', JSON.stringify(_pipelineOptions));
        const _crOpts = collectCreatureOptions();
        if (_crOpts.source === 'reference' && !_uploadedFiles.length) {
          alert('Creature from reference: upload at least one reference image, or choose "From scratch".');
          btn.disabled = false; btn.innerHTML = 'Create →';
          return;
        }
        fd.append('creature_options', JSON.stringify(_crOpts));
        _uploadedFiles.forEach((f, i) => fd.append('images', f, f.name));
        resp = await fetch('/api/submit', { method: 'POST', body: fd });
      } else if (_selectedStyle === 'intro') {
        const fd = new FormData();
        const endingText = (document.getElementById('ending-text-input') || {}).value || '';
        fd.append('prompt', prompt);
        fd.append('invite_token', inviteToken);
        fd.append('pipeline_style', 'intro');
        fd.append('video_duration_minutes', '0.25');
        fd.append('narration_enabled', 'false');
        fd.append('visual_style', _visualStyle);
        fd.append('model_family', _modelFamily);
        fd.append('pipeline_options', JSON.stringify(_pipelineOptions));
        fd.append('scene_mode', 'independent');
        fd.append('ending_text', endingText.trim());
        resp = await fetch('/api/submit', { method: 'POST', body: fd });
      } else {
        resp = await fetch('/api/submit', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({
            prompt, invite_token: inviteToken, pipeline_style: 'documentary',
            narration_enabled: _narrationEnabled, visual_style: _visualStyle,
            model_family: _modelFamily, pipeline_options: _pipelineOptions,
          }),
        });
      }
      const data = await resp.json();

      // Manual-permission users get 202 with {pending: true} — show holding message
      if (resp.status === 202 && data.pending) {
        // Keep button disabled so the user can't submit duplicates while waiting
        btn.disabled      = true;
        btn.innerHTML     = '⏳ Awaiting approval…';
        btn.style.opacity = '0.65';
        const _pendingId = data.pending_id || '';
        // Save to localStorage so the notification survives page refreshes
        if (_pendingId && window._zpubSavePending) window._zpubSavePending(_pendingId, prompt);
        // Hook for when operator approves — triggers the generation pipeline in this scope
        window._zpubOnApproved = function(jobId) {
          currentJobId = jobId;
          const fs = document.getElementById('form-section');
          const ss = document.getElementById('status-section');
          if (fs) fs.style.display = 'none';
          if (ss) ss.style.display = '';
          if (typeof showProgressCard === 'function') showProgressCard('Starting…');
          if (typeof startStream    === 'function') startStream(jobId);
        };
        return;
      }

      if (!resp.ok) {
        btn.disabled  = false;
        btn.innerHTML = 'Create →';
        alert(data.error || 'Submission failed.');
        return;
      }

      currentJobId = data.job_id;
      // Update browser URL without reload
      history.pushState({}, '', `/job/${data.job_id}`);

      if (data.ahead > 0) {
        showQueueCard(data.ahead, data.eta_minutes, data.queue_position);
      } else {
        showProgressCard('Starting…');
      }

      document.getElementById('form-section').style.display = 'none';
      document.getElementById('status-section').style.display = '';

      startStream(data.job_id);

    } catch (err) {
      btn.disabled  = false;
      btn.innerHTML = 'Create →';
      alert(err.message || 'Network error — please try again.');
    }
  }

  // ── SSE stream ────────────────────────────────────────────────────────────
  function startStream(jobId) {
    if (evtSource) evtSource.close();

    evtSource = new EventSource(`/api/stream/${jobId}`);

    evtSource.onmessage = e => {
      let data;
      try { data = JSON.parse(e.data); } catch { return; }

      if (data.error) {
        showErrorCard(data.error);
        evtSource.close();
        return;
      }

      if (data.status === 'queued') {
        showQueueCard(data.ahead, data.eta_minutes, data.queue_position);

      } else if (data.status === 'running') {
        showProgressCard(data.current_stage);

      } else if (data.status === 'done') {
        _finishMsgCycle();
        setTimeout(() => { showResultCard(data.output_files, jobId); _progressCardShown = false; }, 3000);
        evtSource.close();

      } else if (data.status === 'failed' || data.status === 'stopped') {
        _finishMsgCycle();
        setTimeout(() => { showErrorCard(data.error || 'The pipeline was interrupted.'); _progressCardShown = false; }, 2000);
        evtSource.close();
      }
    };

    // Polling fallback: if SSE disconnects while job is still in progress,
    // poll /api/status every 5s so we never get permanently stuck.
    let _sseErrPoller = null;
    evtSource.onerror = () => {
      if (_sseErrPoller) return; // already polling
      _sseErrPoller = setInterval(() => {
        fetch(`/api/status/${jobId}`)
          .then(r => r.ok ? r.json() : null)
          .then(d => {
            if (!d) return;
            if (d.status === 'done') {
              clearInterval(_sseErrPoller); _sseErrPoller = null;
              _finishMsgCycle();
              setTimeout(() => { showResultCard(d.output_files, jobId); _progressCardShown = false; }, 3000);
            } else if (d.status === 'failed' || d.status === 'stopped') {
              clearInterval(_sseErrPoller); _sseErrPoller = null;
              _finishMsgCycle();
              setTimeout(() => { showErrorCard(d.error || 'The pipeline was interrupted.'); _progressCardShown = false; }, 2000);
            }
          })
          .catch(() => {});
      }, 5000);
    };
  }

  // ── Card renderers ────────────────────────────────────────────────────────
  function hideAllCards() {
    ['queue-card','progress-card','result-card','error-card'].forEach(id => {
      document.getElementById(id).style.display = 'none';
    });
  }

  function showQueueCard(ahead, etaMin, position) {
    hideAllCards();
    document.getElementById('queue-card').style.display = '';
    document.getElementById('eta-text').textContent =
      etaMin > 60
        ? `~${Math.round(etaMin/60)} h ${etaMin % 60} min`
        : `~${etaMin} min`;
    document.getElementById('position-text').textContent =
      ahead > 0
        ? `${ahead} job${ahead !== 1 ? 's' : ''} ahead of you`
        : 'You are next';
  }

  // ── Pipeline activity messages ────────────────────────────────────────────
  const PIPELINE_MESSAGES = [
    'Finding monkeys to harvest bananas.',
    'Do not underestimate the trolley problem analysis.',
    'Proper prior planning prevents piss poor performance.',
    'Where 10 men fight , karen is responsible.',
    'Monkeys are eating harvested bananas.',
    "Its not the water surrounding the boat that makes the boat sink , its the water that gets in.",
    'Enforce monkeys to deliver harvested bananas.',
    'We all know it can happen , nobody believes it will happen , but it does happen.\n"A black Swan Event"',
    'Harvested bananas delivered , organizing stocks.',
    'Progression is like driving backwards on the highway.\n"Levi Harley"',
    'Fear not the man who practiced 10.000 kicks once , Fear the man who has practiced one kick 10.000 times\n"Bruce Lee"',
    'Your production is complete, We lost 2 monkeys.',
  ];
  const MSG_DURATION_MS = 15000;
  let _msgIndex       = 0;
  let _msgTimer       = null;
  let _msgRunning     = false;
  let _msgFinished    = false;

  function _renderMsg(text) {
    const el = document.getElementById('stage-text');
    if (!el) return;
    // Support two-line messages (quote on second line)
    const parts = text.split('\n');
    if (parts.length > 1) {
      el.innerHTML = parts[0] + '<br><em style="font-size:0.82em;opacity:0.75;">' + parts[1] + '</em>';
    } else {
      el.textContent = text;
    }
  }

  function _advanceMsg() {
    if (_msgIndex >= PIPELINE_MESSAGES.length) return;
    _renderMsg(PIPELINE_MESSAGES[_msgIndex]);
    const next = _msgIndex + 1;
    if (_msgIndex === 10) {
      // Bruce Lee — hold until pipeline finishes
      if (!_msgFinished) {
        _msgTimer = setTimeout(_advanceMsg, 5000); // keep polling
        return;
      }
      // Finished — jump to completion msg
      _msgIndex = 11;
      _renderMsg(PIPELINE_MESSAGES[11]);
      return;
    }
    if (next < PIPELINE_MESSAGES.length - 1) {
      _msgIndex = next;
      _msgTimer = setTimeout(_advanceMsg, MSG_DURATION_MS);
    } else {
      // Reached Bruce Lee (index 10) — stay there
      _msgIndex = 10;
      _msgTimer = setTimeout(_advanceMsg, 5000);
    }
  }

  function _startMsgCycle() {
    if (_msgRunning) return;
    _msgRunning  = true;
    _msgFinished = false;
    _msgIndex    = 0;
    clearTimeout(_msgTimer);
    _advanceMsg();
  }

  function _finishMsgCycle() {
    _msgFinished = true;
    clearTimeout(_msgTimer);
    // If stuck at Bruce Lee, advance to completion immediately
    if (_msgIndex === 10) {
      _msgIndex = 11;
      _renderMsg(PIPELINE_MESSAGES[11]);
    } else if (_msgIndex < 10) {
      _msgIndex = 11;
      _renderMsg(PIPELINE_MESSAGES[11]);
    }
    _msgRunning = false;
  }

  let _progressCardShown = false;

  function showProgressCard(stage) {
    hideAllCards();
    document.getElementById('progress-card').style.display = '';
    _setRing(_stageToPercent((stage || '').replace(/^(scholarly|crime)\s*/i, '').trim()));
    if (!_progressCardShown) {
      _progressCardShown = true;
      _startMsgCycle();
    }
  }

  function showResultCard(files, jobId) {
    hideAllCards();
    document.getElementById('result-card').style.display = '';
    const list = document.getElementById('file-list');
    if (!files || !files.length) {
      list.innerHTML = '<p style="color:var(--muted)">Pipeline completed but no output files were found.</p>';
    } else {
      list.innerHTML = files.map(f => `
        <div class="file-item">
          <div>
            <div class="file-name">${escHtml(f.name)}</div>
            <div class="file-size">${f.size_mb} MB</div>
          </div>
          <a class="btn-download" href="/download/${jobId}/${encodeURIComponent(f.name)}">
            ↓ Download
          </a>
        </div>
      `).join('');
    }
    // Refresh sidebar and auto-expand it so download appears in the list
    loadSidebar();
    const sidebarEl = document.getElementById('sidebar');
    if (sidebarEl) sidebarEl.classList.remove('collapsed');

    // Countdown ticker then auto-reset so user can create another
    const countEl = document.getElementById('result-countdown');
    let _secsLeft = 8;
    function _tick() {
      if (!document.getElementById('result-card') ||
          document.getElementById('result-card').style.display === 'none') return;
      if (countEl) countEl.textContent = `Returning to prompt in ${_secsLeft}s…`;
      if (_secsLeft <= 0) { resetForm(); _lastPrompt = ''; return; }
      _secsLeft--;
      setTimeout(_tick, 1000);
    }
    _tick();
  }

  function showErrorCard(msg) {
    hideAllCards();
    // If job was aborted (server restart / stopped), pre-fill the prompt and
    // bring back the form so the user can resubmit without retyping.
    const isAbort = msg && (
      msg.toLowerCase().includes('abort') ||
      msg.toLowerCase().includes('restart') ||
      msg.toLowerCase().includes('stopped') ||
      msg.toLowerCase().includes('interrupted') ||
      msg.toLowerCase().includes('server') ||
      msg.toLowerCase().includes('connect')
    );
    if (isAbort && _lastPrompt) {
      // Restore form with pre-filled prompt and a banner
      document.getElementById('status-section').style.display = 'none';
      document.getElementById('form-section').style.display = '';
      const ta = document.getElementById('prompt-input');
      ta.value = _lastPrompt;
      document.getElementById('char-count').textContent = _lastPrompt.length;
      document.getElementById('submit-btn').disabled  = false;
      document.getElementById('submit-btn').innerHTML = 'Create →';
      const banner = document.createElement('div');
      banner.style.cssText = 'background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:0.85rem;color:#fbbf24;';
      banner.textContent = '⚠ The server restarted and your job was interrupted. Your prompt has been restored — press Create to resubmit.';
      const formCard = document.getElementById('form-section');
      formCard.insertBefore(banner, formCard.firstChild);
      currentJobId = null;
      history.pushState({}, '', inviteToken && inviteToken !== '__admin__' ? `/u/${inviteToken}` : '/');
      return;
    }
    document.getElementById('error-card').style.display = '';
    document.getElementById('error-text').textContent = msg;
    // Replace the /job/<id> URL with / so that a browser refresh loads the
    // clean homepage rather than reloading this error page.
    currentJobId = null;
    history.replaceState({}, '', inviteToken && inviteToken !== '__admin__' ? `/u/${inviteToken}` : '/');
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function resetForm() {
    if (evtSource) evtSource.close();
    currentJobId = null;
    document.getElementById('form-section').style.display = '';
    document.getElementById('status-section').style.display = 'none';
    document.getElementById('submit-btn').disabled  = false;
    document.getElementById('submit-btn').innerHTML = 'Create →';
    _setRing(0);
    history.pushState({}, '', inviteToken && inviteToken !== '__admin__' ? `/u/${inviteToken}` : '/');
  }

  // ── Sidebar: hover to expand job list ─────────────────────────────────────
  function initSidebarHover() {
    const el = document.getElementById('sidebar');
    if (!el) return;
    const sync = () => { if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion(); };
    el.addEventListener('mouseenter', () => {
      el.classList.remove('collapsed');
      sync();
    });
    el.addEventListener('mouseleave', () => {
      el.classList.add('collapsed');
      sync();
    });
  }

  // ── Sidebar ───────────────────────────────────────────────────────────────
  function loadSidebar() {
    const sidebar = document.getElementById('sidebar-content');
    if (!sidebar || !inviteToken) return;
    fetch('/api/token_jobs/' + encodeURIComponent(inviteToken))
      .then(r => r.json())
      .then(jobs => {
        if (!jobs.length) {
          sidebar.innerHTML = '<div class="sidebar-empty">No creations yet.<br>Your videos and pictures will appear here.</div>';
          return;
        }
        const pills = { done:'pill-done', running:'pill-running', queued:'pill-queued', error:'pill-error', failed:'pill-error' };
        sidebar.innerHTML = '<div class="sidebar-list">' + jobs.map(j => {
          const _rawDate = j.created_at ? (j.created_at.endsWith('Z') || j.created_at.includes('+') ? j.created_at : j.created_at + 'Z') : null;
          const date = _rawDate ? new Date(_rawDate).toLocaleDateString('en-GB', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Amsterdam'}) : '';
          const dls  = (j.output_files || []).map(f =>
            `<a class="btn-sidebar-dl" href="/download/${j.job_id}/${encodeURIComponent(f.name)}" download>
               ↓ ${escHtml(f.name)}<span class="sidebar-file-size">${f.size_mb} MB</span>
             </a>`
          ).join('');
          return `<div class="sidebar-job">
            <div class="sidebar-job-prompt">${escHtml(j.prompt)}</div>
            <div class="sidebar-job-meta">
              <span class="status-pill ${pills[j.status] || ''}">${j.status}</span>
              <span class="sidebar-job-date">${date}</span>
            </div>
            ${dls ? '<div class="sidebar-job-dls">' + dls + '</div>' : ''}
          </div>`;
        }).join('') + '</div>';
      })
      .catch(() => {});
  }

  document.addEventListener('DOMContentLoaded', () => {
    initSidebarHover();
    loadSidebar();
    setInterval(loadSidebar, 10000);
  });

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Advanced Settings ─────────────────────────────────────────────────────
  const ADV_MAX_SLOTS = 10;

  // characters: array of {img, obj, ani} each null | {file, url}
  // animals:    array of {img, obj}     each null | {file, url}
  // scenes / objects: array of null | {file, url}
  const _advData = {
    scenes:     [null, null, null],
    characters: [
      {img:null, obj:null, ani:null},
      {img:null, obj:null, ani:null},
      {img:null, obj:null, ani:null}
    ],
    objects:    [null, null, null],
    animals:    [
      {img:null, obj:null},
      {img:null, obj:null},
      {img:null, obj:null}
    ],
  };

  // Keep model-family selectors (main + wizard) in sync; libraries follow automatically.
  function _getModelFamily() {
    const a = document.getElementById('model-family-select');
    const b = document.getElementById('model-family-select-st');
    const v = ((b && b.value) || (a && a.value) || 'flux').toLowerCase();
    return (v === 'sdxl') ? 'sdxl' : 'flux';
  }
  function _updateCharLibraryFilterLabels(mf) {
    const label = (mf === 'sdxl' ? 'SDXL' : 'FLUX') + ' characters only';
    const stF = document.getElementById('st-char-library-filter');
    const vidF = document.getElementById('vid-char-library-filter');
    if (stF) stF.textContent = label;
    if (vidF) vidF.textContent = label;
  }
  function _clearCharSelectionsForFamilySwitch() {
    window._stSelectedExistingChar = null;
    window._vidSelectedChar = null;
    if (typeof stClearExistingChar === 'function') stClearExistingChar();
    const vidInfo = document.getElementById('vid-char-selected-info');
    if (vidInfo) vidInfo.style.display = 'none';
    document.querySelectorAll('#vid-char-library-grid > div').forEach(c => {
      c.style.borderColor = 'var(--border)';
    });
  }
  function _filterCharsForModelFamily(chars) {
    const mf = _getModelFamily();
    return (chars || []).filter(c => {
      if (!c.lora_ready) return false;
      const fams = c.lora_families || [];
      if (fams.length) return fams.indexOf(mf) >= 0;
      const cmf = (c.model_family || '').toLowerCase();
      return !cmf || cmf === mf;
    });
  }
  function _syncModelFamilySelect(val) {
    try {
      const v = (val || 'flux').toLowerCase();
      const fixed = (v === 'sdxl') ? 'sdxl' : 'flux';
      window._stModelFamily = fixed;
      const a = document.getElementById('model-family-select');
      const b = document.getElementById('model-family-select-st');
      if (a && a.value !== fixed) a.value = fixed;
      if (b && b.value !== fixed) b.value = fixed;
      const hintSt = document.getElementById('model-family-hint-st');
      if (hintSt) hintSt.innerHTML = fixed === 'sdxl'
        ? '<strong>SDXL path:</strong> Story scenes use Comfy SDXL (no FLUX VRAM preload). Character library shows SDXL LoRAs only.'
        : '<strong>FLUX path:</strong> Story scenes use FLUX diffusers + Comfy. Character library shows FLUX LoRAs only.';
      _updateCharLibraryFilterLabels(fixed);
      _clearCharSelectionsForFamilySwitch();
      const stPanel = document.getElementById('st-existing-chars-panel');
      if (stPanel && stPanel.style.display !== 'none' && typeof stLoadExistingChars === 'function') {
        stLoadExistingChars();
      } else if (stPanel && typeof stLoadExistingChars === 'function') {
        const grid = document.getElementById('st-existing-chars-grid');
        if (grid) grid.innerHTML = '';
      }
      const vidPanel = document.getElementById('vid-char-library-panel');
      if (vidPanel && vidPanel.style.display !== 'none' && typeof vidLoadCharLibrary === 'function') {
        vidLoadCharLibrary();
      } else if (vidPanel) {
        const vgrid = document.getElementById('vid-char-library-grid');
        if (vgrid) vgrid.innerHTML = '';
      }
    } catch {}
  }
  function _charPreviewSlotNames() {
    const mf = ((window._stModelFamily || _getModelFamily() || 'flux') + '').toLowerCase();
    if (mf === 'sdxl') {
      return ['preview_sdxl_front', 'preview_sdxl_face', 'preview_flux_front', 'preview_flux_face'];
    }
    return ['preview_flux_front', 'preview_flux_face'];
  }
  const _advBtnState = {};
  // Documentary caps apply only after the user picks duration/scene count in Advanced Settings.
  window._advDocCapsExplicit = { totalDur: false, sceneCount: false };

  function _advMarkSceneCountExplicit() {
    window._advDocCapsExplicit.sceneCount = true;
  }

  function _advBtnVal(group) {
    return _advBtnState[group] || '';
  }
  function collectCreatureOptions() {
    // 2026-08-25 creature sheet workflow: source + review gate + angle preset
    const scratch = document.getElementById('cr-source-scratch');
    const gate = document.getElementById('cr-review-gate');
    const ang = document.getElementById('cr-angles');
    return {
      source: (scratch && scratch.checked) ? 'scratch' : 'reference',
      review_gate: gate ? !!gate.checked : true,
      angles: ang ? (ang.value || 'standard') : 'standard',
    };
  }

  function collectPipelineOptions() {
    syncDurationFromMainSelect();
    const subsEl = document.getElementById('adv-out-subs');
    const bgmEl = document.getElementById('adv-out-bgm');
    const wmEl = document.getElementById('adv-out-watermark');
    const scEl = document.getElementById('adv-scene-count');
    const tdSec = parseFloat(_advBtnVal('total-dur') || '0');
    const sdSec = parseFloat(_advBtnVal('scene-dur') || '0');
    const isVideoLike = _selectedStyle === 'video' || _selectedStyle === 'manga';
    const isCreatureLoRA = _selectedStyle === 'creature';
    const useTotalDur = isVideoLike || window._advDocCapsExplicit.totalDur;
    const useSceneCount = isVideoLike || window._advDocCapsExplicit.sceneCount;
    const docWithVoice = (_selectedStyle === 'documentary' && _narrationEnabled);
    const opts = {
      enable_bgm:       bgmEl ? !!bgmEl.checked : true,
      burn_subtitles:   docWithVoice ? true : (subsEl ? !!subsEl.checked : true),
      enable_watermark: wmEl ? !!wmEl.checked : false,
      scene_count:      useSceneCount && scEl ? parseInt(scEl.value, 10) : null,
      total_duration_sec: useTotalDur && tdSec > 0 ? tdSec : null,
      scene_duration_sec: sdSec > 0 ? sdSec : null,
      duration_caps_explicit: {
        totalDur: !!window._advDocCapsExplicit.totalDur,
        sceneCount: !!window._advDocCapsExplicit.sceneCount,
      },
    };
    try { localStorage.setItem('zyg_pipeline_options', JSON.stringify(opts)); } catch {}
    window._pipelineOptions = opts;
    return opts;
  }
  function loadPipelineOptionsFromStorage() {
    try {
      const raw = localStorage.getItem('zyg_pipeline_options');
      if (!raw) return;
      const o = JSON.parse(raw);
      const caps = o.duration_caps_explicit || {};
      window._advDocCapsExplicit.totalDur = !!caps.totalDur;
      window._advDocCapsExplicit.sceneCount = !!caps.sceneCount;
      const subsEl = document.getElementById('adv-out-subs');
      const bgmEl = document.getElementById('adv-out-bgm');
      const wmEl = document.getElementById('adv-out-watermark');
      const scEl = document.getElementById('adv-scene-count');
      if (subsEl && typeof o.burn_subtitles === 'boolean') subsEl.checked = o.burn_subtitles;
      _syncSubsWithNarration();
      if (bgmEl && typeof o.enable_bgm === 'boolean') bgmEl.checked = o.enable_bgm;
      if (wmEl && typeof o.enable_watermark === 'boolean') wmEl.checked = o.enable_watermark;
      if (scEl && caps.sceneCount && o.scene_count) {
        scEl.value = String(o.scene_count);
        const v = document.getElementById('adv-scene-count-val');
        if (v) v.textContent = String(o.scene_count);
      }
      if (caps.totalDur && o.total_duration_sec) {
        const sec = String(o.total_duration_sec);
        _advBtnState['total-dur'] = sec;
        document.querySelectorAll('#adv-panel-duration .adv-btn-opt').forEach(btn => {
          const onclick = btn.getAttribute('onclick') || '';
          if (!onclick.includes("'total-dur'")) return;
          btn.classList.toggle('active', btn.getAttribute('data-val') === sec);
        });
      }
      window._pipelineOptions = o;
    } catch {}
  }
  document.addEventListener('DOMContentLoaded', () => {
    try {
      const a = document.getElementById('model-family-select');
      const b = document.getElementById('model-family-select-st');
      if (a) a.addEventListener('change', () => _syncModelFamilySelect(a.value));
      if (b) b.addEventListener('change', () => _syncModelFamilySelect(b.value));
      if (a && b) b.value = a.value || 'flux';
      _syncModelFamilySelect(_getModelFamily());
      loadPipelineOptionsFromStorage();
      document.querySelectorAll('.adv-btn-opt.active').forEach(btn => {
        const m = (btn.getAttribute('onclick') || '').match(/advSetBtnOpt\('([^']+)'/);
        if (!m || m[1] === 'total-dur') return;
        _advBtnState[m[1]] = btn.getAttribute('data-val') || '';
      });
    } catch {}
  });

  const _advCatLabel    = { scenes:'Add Image', objects:'Add Object' };
  const _advCatSingular = { scenes:'Scene', characters:'Character', objects:'Object', animals:'Animal' };

  function openAdvModal() {
    alert('Under construction');
  }

  function closeAdvModal() {
    document.getElementById('adv-overlay').classList.remove('open');
    document.body.style.overflow = '';
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  }

  function advModalClose(e) {
    if (e.target === document.getElementById('adv-overlay')) closeAdvModal();
  }

  function advSelectTab(name, el) {
    document.querySelectorAll('#adv-tab-list .adv-tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.adv-content .adv-panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById('adv-panel-' + name);
    if (panel) panel.classList.add('active');
    if (name === 'benchmark') advLoadBenchmark();
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  }

  function advLoadBenchmark() {
    const loading = document.getElementById('adv-bm-loading');
    const errEl   = document.getElementById('adv-bm-error');
    const table   = document.getElementById('adv-bm-table');
    const empty   = document.getElementById('adv-bm-empty');
    const tbody   = document.getElementById('adv-bm-tbody');
    if (!loading) return;
    loading.style.display = 'block';
    table.style.display   = 'none';
    empty.style.display   = 'none';
    errEl.style.display   = 'none';
    errEl.textContent     = '';
    fetch('/api/benchmark')
      .then(r => r.json())
      .then(data => {
        loading.style.display = 'none';
        const rows = data.rows || [];
        if (!rows.length) { empty.style.display = 'block'; return; }
        tbody.innerHTML = rows.map(r => {
          const avg  = r.avg_s_per_unit  ? r.avg_s_per_unit.toFixed(1)  + 's/' + r.unit : '—';
          const last = r.last_s_per_unit ? r.last_s_per_unit.toFixed(1) + 's/' + r.unit : '—';
          const ts   = r.last_ts ? r.last_ts.replace('T',' ').replace('Z','') : '—';
          return `<tr style="border-bottom:1px solid var(--border)">
            <td style="padding:7px 8px">${r.emoji || '📊'} ${r.tool}</td>
            <td style="text-align:right;padding:7px 8px;color:var(--accent)">${avg}</td>
            <td style="text-align:right;padding:7px 8px">${last}</td>
            <td style="text-align:right;padding:7px 8px;color:var(--text-muted)">${r.total_samples}</td>
            <td style="text-align:right;padding:7px 8px;color:var(--text-muted);font-size:0.78rem">${ts}</td>
          </tr>`;
        }).join('');
        table.style.display = 'table';
      })
      .catch(e => {
        loading.style.display = 'none';
        errEl.textContent = 'Failed to load benchmark data: ' + e;
        errEl.style.display = 'block';
      });
  }

  // ── Simple grid (scenes / objects) ──────────────────────────────────────
  function _renderSimpleGrid(category) {
    const grid = document.getElementById(category + '-grid');
    if (!grid) return;
    const slots = _advData[category];
    const label = _advCatLabel[category];
    grid.innerHTML = '';
    slots.forEach((entry, i) => {
      const div = document.createElement('div');
      if (entry && entry.generated) {
        // AI-generated prompt placeholder
        div.className = 'adv-img-slot adv-generated';
        div.style.position = 'relative';
        div.innerHTML =
          `<div class="adv-gen-content">` +
            `<span class="adv-gen-icon">🤖</span>` +
            `<span class="adv-gen-label">AI Prompt</span>` +
            `<span class="adv-gen-prompt">${escHtml(entry.prompt)}</span>` +
          `</div>` +
          `<button class="adv-slot-delete" title="Delete slot" onclick="advDeleteSlot('${category}',${i})">🗑</button>` +
          `<span class="adv-slot-num">${i + 1}</span>`;
      } else {
        div.className = 'adv-img-slot' + (entry ? ' has-image' : '');
        div.style.position = 'relative';
        if (entry) {
          div.innerHTML =
            `<img src="${entry.url}" alt="slot ${i+1}">` +
            `<button class="adv-slot-remove" title="Clear image" onclick="advClearSlot('${category}',${i})">✕</button>` +
            `<button class="adv-slot-delete" title="Delete slot" onclick="advDeleteSlot('${category}',${i})">🗑</button>` +
            `<span class="adv-slot-num">${i + 1}</span>`;
        } else {
          div.innerHTML =
            `<div class="adv-slot-placeholder" onclick="advTriggerUpload('${category}',${i})">` +
            `<span class="adv-slot-icon">🖼️</span>` +
            `<span class="adv-slot-label">${label}</span>` +
            `</div>` +
            `<button class="adv-slot-delete" title="Delete slot" onclick="advDeleteSlot('${category}',${i})">🗑</button>` +
            `<span class="adv-slot-num">${i + 1}</span>`;
        }
      }
      grid.appendChild(div);
    });
    _updateAddBtn(category);
    _updateCreateBtn(category);
  }

  // ── Character grid ───────────────────────────────────────────────────────
  function _renderCharGrid() {
    const grid = document.getElementById('characters-grid');
    if (!grid) return;
    grid.innerHTML = '';
    _advData.characters.forEach((card, i) => {
      const img = card.img;
      let imgHtml;
      if (img && img.generated) {
        imgHtml =
          `<div class="adv-char-img-gen">` +
            `<span class="adv-gen-icon">🤖</span>` +
            `<span class="adv-gen-label" style="font-size:0.7rem;font-weight:700;color:var(--accent2)">AI Prompt</span>` +
            `<span class="adv-gen-prompt">${escHtml(img.prompt)}</span>` +
            `<button class="adv-slot-remove" title="Clear" onclick="advClearCharImg(${i})" style="position:absolute;top:4px;right:4px">✕</button>` +
          `</div>`;
      } else if (img) {
        imgHtml =
          `<div class="adv-img-slot has-image" style="position:relative;border-radius:0;width:100%;height:118px;border:none;border-bottom:1px solid var(--border)">` +
            `<img src="${img.url}" alt="char ${i+1}">` +
            `<button class="adv-slot-remove" title="Clear image" onclick="advClearCharImg(${i})">✕</button>` +
          `</div>`;
      } else {
        imgHtml =
          `<div class="adv-img-slot" style="border-radius:0;width:100%;height:118px;border:none;border-bottom:1px solid var(--border)">` +
            `<div class="adv-slot-placeholder" onclick="advTriggerCharImg(${i})">` +
              `<span class="adv-slot-icon">🧍</span>` +
              `<span class="adv-slot-label">Add Character</span>` +
            `</div>` +
          `</div>`;
      }
      const wrapper = document.createElement('div');
      wrapper.className = 'adv-char-card';
      wrapper.innerHTML =
        `<div class="adv-char-card-hdr">` +
          `<span class="adv-char-card-num">Character ${i+1}</span>` +
          `<button class="adv-char-delete-btn" title="Delete card" onclick="advDeleteSlot('characters',${i})">🗑</button>` +
        `</div>` +
        imgHtml +
        `<div class="adv-sub-slots">` +
          _subSlotHTML('char-obj', 'characters', i, 'obj', '📦', 'Add Object') +
          _subSlotHTML('char-ani', 'characters', i, 'ani', '🐾', 'Add Animal') +
        `</div>`;
      grid.appendChild(wrapper);
    });
    _updateAddBtn('characters');
    _updateCreateBtn('characters');
  }

  // ── Animal grid ──────────────────────────────────────────────────────────
  function _renderAniGrid() {
    const grid = document.getElementById('animals-grid');
    if (!grid) return;
    grid.innerHTML = '';
    _advData.animals.forEach((card, i) => {
      const img = card.img;
      let imgHtml;
      if (img && img.generated) {
        imgHtml =
          `<div class="adv-char-img-gen">` +
            `<span class="adv-gen-icon">🤖</span>` +
            `<span class="adv-gen-label" style="font-size:0.7rem;font-weight:700;color:var(--accent2)">AI Prompt</span>` +
            `<span class="adv-gen-prompt">${escHtml(img.prompt)}</span>` +
            `<button class="adv-slot-remove" title="Clear" onclick="advClearAniImg(${i})" style="position:absolute;top:4px;right:4px">✕</button>` +
          `</div>`;
      } else if (img) {
        imgHtml =
          `<div class="adv-img-slot has-image" style="position:relative;border-radius:0;width:100%;height:118px;border:none;border-bottom:1px solid var(--border)">` +
            `<img src="${img.url}" alt="animal ${i+1}">` +
            `<button class="adv-slot-remove" title="Clear image" onclick="advClearAniImg(${i})">✕</button>` +
          `</div>`;
      } else {
        imgHtml =
          `<div class="adv-img-slot" style="border-radius:0;width:100%;height:118px;border:none;border-bottom:1px solid var(--border)">` +
            `<div class="adv-slot-placeholder" onclick="advTriggerAniImg(${i})">` +
              `<span class="adv-slot-icon">🐾</span>` +
              `<span class="adv-slot-label">Add Animal</span>` +
            `</div>` +
          `</div>`;
      }
      const wrapper = document.createElement('div');
      wrapper.className = 'adv-char-card';
      wrapper.innerHTML =
        `<div class="adv-char-card-hdr">` +
          `<span class="adv-char-card-num">Animal ${i+1}</span>` +
          `<button class="adv-char-delete-btn" title="Delete card" onclick="advDeleteSlot('animals',${i})">🗑</button>` +
        `</div>` +
        imgHtml +
        `<div class="adv-sub-slots">` +
          _subSlotHTML('ani-obj', 'animals', i, 'obj', '📦', 'Add Object') +
        `</div>`;
      grid.appendChild(wrapper);
    });
    _updateAddBtn('animals');
    _updateCreateBtn('animals');
  }

  function _subSlotHTML(inputKey, category, cardIdx, subKey, icon, label) {
    const entry = _advData[category][cardIdx][subKey];
    const hasCls = entry ? ' has-image' : '';
    const img = entry ? `<img src="${entry.url}" alt="${label}">` : '';
    const clr = entry
      ? `<button class="adv-sub-clear" title="Clear" onclick="advClearSubSlot('${category}',${cardIdx},'${subKey}')">✕</button>`
      : '';
    return `<div class="adv-sub-slot${hasCls}" onclick="advTriggerSubUpload('${inputKey}',${cardIdx})">` +
      img + clr +
      `<span class="adv-sub-slot-icon">${icon}</span>` +
      `<span class="adv-sub-slot-label">${label}</span>` +
    `</div>`;
  }

  // ── Dispatch ─────────────────────────────────────────────────────────────
  function advRenderGrid(category) {
    if (category === 'characters') { _renderCharGrid(); return; }
    if (category === 'animals')    { _renderAniGrid();  return; }
    _renderSimpleGrid(category);
  }

  function _updateAddBtn(category) {
    const addBtn = document.getElementById(category + '-add-btn');
    if (!addBtn) return;
    const atMax = _advData[category].length >= ADV_MAX_SLOTS;
    addBtn.disabled = atMax;
    addBtn.textContent = atMax ? `✓ Maximum ${ADV_MAX_SLOTS} reached` : `+ Add ${_advCatSingular[category]}`;
  }

  function _updateCreateBtn(category) {
    const btn = document.getElementById(category + '-create-btn');
    if (btn) btn.disabled = _advData[category].length >= ADV_MAX_SLOTS;
  }

  // ── Main image upload helpers ─────────────────────────────────────────────
  function advTriggerUpload(category, index) {
    const inp = document.getElementById('adv-file-input-' + category);
    if (!inp) return;
    inp._targetIndex = index;
    inp.value = '';
    inp.click();
  }

  function advHandleFile(category) {
    const inp = document.getElementById('adv-file-input-' + category);
    if (!inp || !inp.files || !inp.files[0]) return;
    const i = inp._targetIndex;
    if (typeof i !== 'number') return;
    const url = URL.createObjectURL(inp.files[0]);
    // For simple categories (scenes/objects), store {file, url} directly
    _advData[category][i] = { file: inp.files[0], url };
    advRenderGrid(category);
  }

  function advTriggerCharImg(cardIdx) {
    const inp = document.getElementById('adv-file-input-characters');
    if (!inp) return;
    inp._targetIndex = cardIdx;
    inp.value = '';
    inp.click();
  }
  // Override advHandleFile for characters to set card.img
  const _origHandleFile = advHandleFile;
  // Patch: characters/animals file inputs (DOM below this script — bind on DOMContentLoaded).
  function _bindAdvCharAniFileInputs() {
    const charInp = document.getElementById('adv-file-input-characters');
    if (charInp && !charInp._advImgPatchBound) {
      charInp._advImgPatchBound = true;
      charInp.addEventListener('change', function() {
        if (!this.files || !this.files[0]) return;
        const i = this._targetIndex;
        if (typeof i !== 'number') return;
        _advData.characters[i].img = { file: this.files[0], url: URL.createObjectURL(this.files[0]) };
        _renderCharGrid();
      });
    }
    const aniInp = document.getElementById('adv-file-input-animals');
    if (aniInp && !aniInp._advImgPatchBound) {
      aniInp._advImgPatchBound = true;
      aniInp.addEventListener('change', function() {
        if (!this.files || !this.files[0]) return;
        const i = this._targetIndex;
        if (typeof i !== 'number') return;
        _advData.animals[i].img = { file: this.files[0], url: URL.createObjectURL(this.files[0]) };
        _renderAniGrid();
      });
    }
  }
  document.addEventListener('DOMContentLoaded', _bindAdvCharAniFileInputs);

  function advTriggerAniImg(cardIdx) {
    const inp = document.getElementById('adv-file-input-animals');
    if (!inp) return;
    inp._targetIndex = cardIdx;
    inp.value = '';
    inp.click();
  }

  function advClearCharImg(cardIdx) {
    _advData.characters[cardIdx].img = null;
    _renderCharGrid();
  }
  function advClearAniImg(cardIdx) {
    _advData.animals[cardIdx].img = null;
    _renderAniGrid();
  }

  // ── Sub-slot upload helpers ───────────────────────────────────────────────
  const _subUploadCtx = {}; // stores {category, cardIdx} by inputId

  function advTriggerSubUpload(inputKey, cardIdx) {
    const id = 'adv-file-input-' + inputKey;
    const inp = document.getElementById(id);
    if (!inp) return;
    _subUploadCtx[id] = cardIdx;
    inp.value = '';
    inp.click();
  }

  function advHandleSubFile(inputId, category, subKey) {
    const inp = document.getElementById(inputId);
    if (!inp || !inp.files || !inp.files[0]) return;
    const cardIdx = _subUploadCtx[inputId];
    if (typeof cardIdx !== 'number') return;
    _advData[category][cardIdx][subKey] = {
      file: inp.files[0],
      url: URL.createObjectURL(inp.files[0])
    };
    advRenderGrid(category);
  }

  function advClearSubSlot(category, cardIdx, subKey) {
    _advData[category][cardIdx][subKey] = null;
    advRenderGrid(category);
  }

  // ── Clear (image only) vs Delete (remove entire slot) ────────────────────
  function advClearSlot(category, index) {
    _advData[category][index] = null;
    advRenderGrid(category);
  }

  function advDeleteSlot(category, index) {
    _advData[category].splice(index, 1);
    // Ensure at least 1 slot remains
    if (_advData[category].length === 0) {
      if (category === 'characters') _advData.characters.push({img:null,obj:null,ani:null});
      else if (category === 'animals') _advData.animals.push({img:null,obj:null});
      else _advData[category].push(null);
    }
    advRenderGrid(category);
  }

  function advAddSlot(category) {
    if (_advData[category].length >= ADV_MAX_SLOTS) return;
    if (category === 'characters') _advData.characters.push({img:null,obj:null,ani:null});
    else if (category === 'animals') _advData.animals.push({img:null,obj:null});
    else _advData[category].push(null);
    advRenderGrid(category);
    _updateCreateBtn(category);
  }

  // ── Style / btn helpers ───────────────────────────────────────────────────
  function advSetStyleCard(el) {
    document.querySelectorAll('#adv-style-grid .adv-style-card').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
  }

  function advSetBtnOpt(group, el) {
    const parent = el.closest('.adv-btn-group');
    if (parent) parent.querySelectorAll('.adv-btn-opt').forEach(b => b.classList.remove('active'));
    el.classList.add('active');
    _advBtnState[group] = el.getAttribute('data-val') || '';
    if (group === 'total-dur') window._advDocCapsExplicit.totalDur = true;
  }

  function advUpdatePipelineType(val) {
    const note = document.getElementById('adv-intro-note');
    if (note) note.classList.toggle('visible', val === 'intro');
  }

  // ── Create-from-prompt dialog ─────────────────────────────────────────────
  const _CREATE_META = {
    scenes:     { title: '✨ Create Scene',     hint: 'Describe the scene you want to generate.',     icon: '🎬', singular: 'Scene'     },
    characters: { title: '✨ Create Character', hint: 'Describe the character you want to generate.', icon: '🧍', singular: 'Character' },
    objects:    { title: '✨ Create Object',    hint: 'Describe the object you want to generate.',    icon: '📦', singular: 'Object'    },
    animals:    { title: '✨ Create Animal',    hint: 'Describe the animal you want to generate.',    icon: '🐾', singular: 'Animal'    },
  };
  let _createCategory = null;

  function advOpenCreate(category) {
    if (_advData[category].length >= ADV_MAX_SLOTS) return;
    _createCategory = category;
    const m = _CREATE_META[category];
    document.getElementById('adv-create-title').textContent = m.title;
    document.getElementById('adv-create-hint').textContent  = m.hint;
    document.getElementById('adv-create-prompt').value = '';
    document.getElementById('adv-create-overlay').classList.add('open');
    setTimeout(() => document.getElementById('adv-create-prompt').focus(), 120);
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  }

  function advCloseCreate(e) {
    // Called with no arg (button click) or with click event (overlay click)
    if (e instanceof Event && e.target !== document.getElementById('adv-create-overlay')) return;
    document.getElementById('adv-create-overlay').classList.remove('open');
    _createCategory = null;
    if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
  }
  // Alias for internal use without an event
  const _advCloseCreateDirect = () => advCloseCreate();

  function advDoCreate() {
    const prompt = document.getElementById('adv-create-prompt').value.trim();
    if (!prompt) { document.getElementById('adv-create-prompt').focus(); return; }
    const cat = _createCategory;
    if (!cat || _advData[cat].length >= ADV_MAX_SLOTS) {
      _advCloseCreateDirect(); return;
    }
    const entry = { prompt, generated: true };
    if (cat === 'characters') {
      _advData.characters.push({ img: entry, obj: null, ani: null });
    } else if (cat === 'animals') {
      _advData.animals.push({ img: entry, obj: null });
    } else {
      _advData[cat].push(entry);
    }
    _advCloseCreateDirect();
    advRenderGrid(cat);
  }

  // Allow Escape to close the create dialog too
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.ctrlKey) {
      const ov = document.getElementById('adv-create-overlay');
      if (ov && ov.classList.contains('open')) { advDoCreate(); return; }
    }
    if (e.key === 'Escape') {
      const createOv = document.getElementById('adv-create-overlay');
      if (createOv && createOv.classList.contains('open')) { _advCloseCreateDirect(); return; }
      const overlay = document.getElementById('adv-overlay');
      if (overlay && overlay.classList.contains('open')) closeAdvModal();
    }
  });

  // ── Tooltip system ────────────────────────────────────────────────────────
  // Lookup table: data-val → tooltip text (for btn-opts + style cards)
  const _ADV_TT = {
    // ── Pipeline Type
    'documentary': 'Documentary — Structured narration-led format. Informative, authoritative tone with b-roll style visuals.',
    'video':       'Video — Flexible narrative format. Balanced between story and visual spectacle.',
    'intro':       'Intro — 10–12 second cinematic series/brand opener. No narration, high-impact, hook-first design.',
    // ── Visual Styles
    'cinematic':   'Cinematic — Wide aspect, film-like composition with dramatic lighting. The Hollywood look.',
    'realism':     'Realism — Photorealistic output. Looks like actual footage shot on a real camera.',
    'anime':       'Anime — Japanese animation style with bold outlines, expressive faces, and vivid colours.',
    'disney':      'Disney 2D — Classic hand-drawn animation. Soft edges, bright palette, expressive characters.',
    'art':         'Digital Art — Illustrated, painterly look. Rich textures with a hand-crafted feel.',
    '3d_render':   '3D Render — Clean CGI aesthetic. Polished surface lighting and depth typical of 3D software.',
    'scenery':     'Scenery — Wide, beautiful landscape focus. Nature, architecture and environment-first shots.',
    'filmic':      'Filmic — Grain, lens flares and analogue film character. Feels like it was shot on 35mm.',
    'artistic':    'Artistic — Stylised, expressive visual treatment. Creative and genre-defying aesthetic.',
    // ── Camera Motion
    'auto':        'Auto — AI selects the best camera movement per scene context. Recommended default.',
    'static':      'Static — Camera stays completely fixed. Ideal for dramatic or intimate moments.',
    'pan':         'Pan — Smooth horizontal camera sweep. Perfect for landscapes and wide scene reveals.',
    'tilt':        'Tilt — Vertical sweep up or down. Great for tall subjects or dramatic reveals.',
    'zoom_in':     'Zoom In — Gradually move closer to the subject. Builds tension and draws focus.',
    'zoom_out':    'Zoom Out — Pull back to reveal more context. Creates an epic or distancing effect.',
    'dolly':       'Dolly — Camera physically moves forward/backward on a track. Immersive and cinematic.',
    'push_in':     'Push In — Aggressive dolly toward subject. Intensifies focus or drama.',
    'pull_out':    'Pull Out — Camera retreats from subject. Creates unease or a sense of detachment.',
    'orbit':       'Orbit — Camera arcs in a full circle around the subject. Classic hero showcase shot.',
    'crane':       'Crane — Camera sweeps vertically up or down. Grand, sweeping perspective change.',
    'handheld':    'Handheld — Subtle organic camera shake. Adds realism and documentary authenticity.',
    'whip_pan':    'Whip Pan — Ultra-fast horizontal snap transition. Used for energy and action punctuation.',
    // ── Color Grading
    'neutral':         'Neutral — Clean, balanced colour with no tint bias. Universal starting point.',
    'warm':            'Warm — Amber/orange push. Feels cosy, nostalgic, or desert-bathed.',
    'cool':            'Cool — Blue tint. Clinical, futuristic, or cold/isolated atmosphere.',
    'noir':            'Noir — High contrast near-monochrome. Classic crime, mystery or thriller look.',
    'vivid':           'Vivid — Fully saturated, punchy colours. Eye-catching and energetic.',
    'teal_orange':     'Teal & Orange — Industry-standard Hollywood contrast. Skin tones pop against teal shadows.',
    'golden_hour':     'Golden Hour — Warm amber light with soft contrast. Romantic, cinematic magic-hour feel.',
    'vintage':         'Vintage — Faded, slightly washed-out with a warm cast. Nostalgic analogue film look.',
    'desaturated':     'Desaturated — Muted, low-colour palette. Serious, gritty or documentary tone.',
    'high_contrast':   'High Contrast — Strong shadows and bright highlights. Dramatic and visually bold.',
    'matte':           'Matte/Log — Flat, low-contrast base. Common in grading pipelines; lets colour pop subtly.',
    'neon':            'Neon — Vivid purple/cyan/magenta palette. Cyberpunk and night-city aesthetic.',
    // ── Narrator tone
    'neutral-tone':    'Neutral Tone — Balanced, journalistic delivery with no strong emotion.',
    'authoritative':   'Authoritative — Confident, expert delivery. Strong, credible and reliable.',
    'dramatic':        'Dramatic — Heightened emotional delivery. Tension, impact and gravitas.',
    'calm':            'Calm — Soft, soothing delivery. Ideal for nature, wellness or meditative content.',
    'enthusiastic':    'Enthusiastic — High energy, upbeat tone. Great for commercial or motivational content.',
    'whispering':      'Whispering — Intimate, hushed delivery. Creates closeness or dramatic tension.',
    'melancholic':     'Melancholic — Wistful, slightly sad tone. Perfect for reflective or historical content.',
    'comedic':         'Comedic — Light, playful tone with a hint of wit.',
    // ── Voice gender
    'male':   'Male Voice — Deep or mid-range male narrator.',
    'female': 'Female Voice — Warm or crisp female narrator.',
    // ── Voice age
    'young':  'Young Voice — Youthful, fresh-sounding narrator.',
    'adult':  'Adult Voice — Standard mature narrator. Works for most content.',
    'mature': 'Mature Voice — Older, experienced-sounding. Projects authority and wisdom.',
    // ── Narrator speed
    'slow':   'Slow Pace — Deliberate, thoughtful delivery. Good for serious or complex topics.',
    'normal': 'Normal Pace — Standard delivery speed for documentary narration.',
    'fast':   'Fast Pace — Energetic, rapid delivery. Great for action or hype content.',
    // ── Total Duration
    '10':  '10 seconds — Ultra-short clip. Best for social media teasers or intro sequences.',
    '15':  '15 seconds — Short-form. Optimised for Instagram Reels, TikTok, or punchy social clips.',
    '30':  '30 seconds — Short promo or teaser. Good for ads or highlight reels.',
    '60':  '1 minute — Standard short documentary or explainer video.',
    '120': '2 minutes — Extended short-form. Enough for a complete mini-story.',
    '180': '3 minutes — Full short documentary or brand film.',
    '300': '5 minutes — Long-form documentary or deep-dive video.',
    // ── Scene Length
    '3':  '3 seconds — Very quick cuts. High energy, fast action sequences.',
    '5':  '5 seconds — Fast-paced. Maintains energy without rushing the scene.',
    '8':  '8 seconds — Balanced scene length. A good default for most content types.',
    // 10 already defined above for duration; override for scene context handled below
    // ── Transitions
    'none':      'No Transition — Instant hard cut between scenes. Raw, aggressive energy.',
    'fade':      'Fade — Gentle cross-fade between scenes. Smooth and cinematic.',
    'cut':       'Hard Cut — Instant switch, no blend. Punchy and direct.',
    'dissolve':  'Dissolve — One scene slowly blends into the next. Dreamlike and soft.',
    'wipe':      'Wipe — One scene slides off to reveal the next. Classic broadcast look.',
    'slide':     'Slide — New scene slides in from the side. Dynamic and modern.',
    'zoom_trans':'Zoom Transition — Push-in or pull-out leads into the next scene. High-energy.',
    'glitch':    'Glitch — Digital artefact break between scenes. Edgy, cyberpunk, music-video aesthetic.',
    // ── Resolution
    '720p':         '720p HD — Standard HD resolution. Smaller file size, good for web streaming.',
    '1080p':        '1080p Full HD — Broadcast quality. Best balance of quality and file size.',
    '4k':           '4K Ultra HD — Maximum quality output. Large file, cinematic resolution.',
    'vertical_1080':'Vertical 9:16 — Portrait format optimised for TikTok, Reels and Stories.',
    'square_1080':  'Square 1:1 — Equal width and height. Ideal for Instagram feed posts.',
    // ── Frame Rate
    '24': '24 fps — The cinematic standard. Classic film frame rate used in Hollywood.',
    // 30 already defined; add note below
    // ── Format
    'mp4':  'MP4 — Most universally compatible video format. Works everywhere.',
    'mov':  'MOV — Apple ProRes-friendly container. High quality, larger file size.',
    'webm': 'WebM — Open web format. Great for browser embedding and streaming.',
    // ── Quality
    'standard': 'Standard Quality — Faster render time, smaller output file.',
    'high':     'High Quality — Balanced quality and render time. Recommended default.',
    'ultra':    'Ultra Quality — Maximum fidelity output. Slowest to render.',
    // ── Subtitle Position
    'bottom': 'Bottom — Standard broadcast position. Subtitles appear at the bottom of frame.',
    'middle': 'Middle — Centred subtitles. Used for artistic or sign-translation placement.',
    'top':    'Top — Avoids covering lower-frame action. Common in theatrical releases.',
    // ── Subtitle Style
    'plain':   'Plain — No background or border on subtitles. Clean and minimal.',
    'shadow':  'Drop Shadow — Subtle shadow behind text for legibility on any background.',
    'outline': 'Outline — Thin stroke around text. High contrast on varied backgrounds.',
    'box':     'Box Background — Semi-opaque background behind subtitle text. Maximum legibility.',
    // ── Subtitle colour
    'white':  'White — Classic subtitle colour. High contrast on most backgrounds.',
    'yellow': 'Yellow — Warm, readable colour. Common in film and broadcast.',
    'cyan':   'Cyan — Cool tint. Good on warm-coloured backgrounds.',
    'green':  'Green — High legibility on dark backgrounds.',
    'orange': 'Orange — Warm, energetic. Stands out on blue/cool backgrounds.',
  };

  // Extra tooltips by element ID (for inputs, checkboxes, selects)
  const _ADV_TT_ID = {
    'adv-sub-enabled':    'Enable Subtitles — Burn subtitle text directly into the video frames.',
    'adv-sub-lang':       'Subtitle Language — Choose the display language for burned-in subtitles.',
    'adv-sub-size':       'Font Size — Drag to set the subtitle text size (16–52px).',
    'adv-nar-lang':       'Narrator Language — Sets the language and accent for the voice narration.',
    'adv-scene-count':    'Number of Scenes — Slider to set how many scenes the video is split into (1–10).',
    'adv-out-bgm':        'Background Music — Add AI-generated ambient music under the narration.',
    'adv-out-subs':       'Burn Subtitles into the final output video file.',
    'adv-out-watermark':  'Zygomatic Watermark — Add a subtle branded watermark to the video output.',
  };

  function _applyAdvTooltips() {
    // btn-opts: key by data-val (skip neutral since it overlaps tone/color)
    document.querySelectorAll('#adv-modal .adv-btn-opt[data-val]').forEach(el => {
      const v = el.dataset.val;
      // For nar-tone neutral, use specific key
      const parent = el.closest('.adv-field, .adv-section');
      const txt = _ADV_TT[v] || null;
      if (txt && !el.dataset.tooltip) el.dataset.tooltip = txt;
    });
    // Neutral tone override (distinguish from neutral colour-grade)
    document.querySelectorAll('#adv-modal .adv-btn-opt[data-val="neutral"]').forEach(el => {
      const row = el.closest('.adv-panel');
      if (!row) return;
      if (row.id === 'adv-panel-narrator') el.dataset.tooltip = _ADV_TT['neutral-tone'];
      else if (!el.dataset.tooltip) el.dataset.tooltip = _ADV_TT['neutral'];
    });
    // Scene-length 10s vs total-dur 10s — context by group
    document.querySelectorAll('#adv-panel-duration .adv-btn-opt[data-val="10"]').forEach((el, idx) => {
      // first group = total-dur, second = scene-dur
      el.dataset.tooltip = idx === 0
        ? _ADV_TT['10']
        : '10 seconds — Slower, more considered scene. Good for narration-heavy moments.';
    });
    document.querySelectorAll('#adv-panel-duration .adv-btn-opt[data-val="15"]').forEach((el, idx) => {
      el.dataset.tooltip = idx === 0 ? _ADV_TT['15'] : '15 seconds — Lingering scene. Documentary or artistic approach.';
    });
    document.querySelectorAll('#adv-panel-duration .adv-btn-opt[data-val="30"]').forEach((el, idx) => {
      el.dataset.tooltip = idx === 0 ? _ADV_TT['30'] : '30 frames per second — Broadcast/web standard. Smooth and widely compatible.';
    });
    document.querySelectorAll('#adv-panel-output .adv-btn-opt[data-val="30"]').forEach(el => {
      el.dataset.tooltip = '30 fps — Broadcast/web standard. Smooth and widely compatible.';
    });
    // Style cards
    document.querySelectorAll('#adv-style-grid .adv-style-card[data-val]').forEach(el => {
      const txt = _ADV_TT[el.dataset.val];
      if (txt) el.dataset.tooltip = txt;
    });
    // IDs
    Object.entries(_ADV_TT_ID).forEach(([id, tip]) => {
      const el = document.getElementById(id);
      if (el) el.dataset.tooltip = tip;
      // also label wrapping it
      const lbl = el && el.closest('label');
      if (lbl) lbl.dataset.tooltip = tip;
    });
    // Range slider labels
    document.querySelectorAll('#adv-modal label').forEach(el => {
      const inp = el.querySelector('input[id]') || (el.htmlFor && document.getElementById(el.htmlFor));
      if (inp && inp.id && _ADV_TT_ID[inp.id] && !el.dataset.tooltip)
        el.dataset.tooltip = _ADV_TT_ID[inp.id];
    });
    // adv-toggle-row wrappers
    document.querySelectorAll('#adv-modal .adv-toggle-row').forEach(row => {
      const cb = row.querySelector('input[type=checkbox]');
      if (cb && _ADV_TT_ID[cb.id]) row.dataset.tooltip = _ADV_TT_ID[cb.id];
    });
    // Add-slot & create-slot buttons (panel-level)
    const panelTips = {
      'scenes-add-btn':        'Add a new scene slot — upload a reference image for the opening frame of this scene.',
      'scenes-create-btn':     'Describe a scene in text — the AI will generate a visual description for the pipeline.',
      'characters-add-btn':    'Add a new character card — upload a reference image of a character.',
      'characters-create-btn': 'Describe a character in text — AI will create a visual description to guide generation.',
      'objects-add-btn':       'Add a new object slot — upload a reference image of a specific object.',
      'objects-create-btn':    'Describe an object in text — AI will generate a visual description for this object.',
      'animals-add-btn':       'Add a new animal card — upload a reference image of an animal.',
      'animals-create-btn':    'Describe an animal in text — AI will generate a visual description for this animal.',
    };
    Object.entries(panelTips).forEach(([id, tip]) => {
      const el = document.getElementById(id);
      if (el) el.dataset.tooltip = tip;
    });
  }

  // ── Generate button ───────────────────────────────────────────────────────
  function advGenerate() {
    const tdBtn = document.querySelector('#adv-panel-duration .adv-btn-opt.active[onclick*="total-dur"]');
    if (tdBtn) window._advDocCapsExplicit.totalDur = true;
    const opts = collectPipelineOptions();
    // Apply duration to main video duration selector when user set total-dur in Advanced.
    if (opts.total_duration_sec) {
      const durSel = document.getElementById('duration-select');
      if (durSel) {
        const sec = String(opts.total_duration_sec);
        const hasOpt = Array.from(durSel.options).some(o => o.value === sec);
        if (hasOpt) durSel.value = sec;
      }
    }
    const btn = document.getElementById('adv-generate-btn');
    btn.textContent = '✓ Settings Applied';
    btn.classList.add('applied');
    setTimeout(() => {
      btn.textContent = '▶ Apply Settings';
      btn.classList.remove('applied');
      closeAdvModal();
    }, 800);
  }

  // Init tooltip system after the full DOM (modal HTML is below this script)
  document.addEventListener('DOMContentLoaded', () => {
    _applyAdvTooltips();

    // Tooltip event delegation on modal + create dialog
    const tt = document.getElementById('adv-tt');
    if (!tt) return;
    let _hideTimer = null;

    function _showTT(el) {
      const text = el.dataset.tooltip;
      if (!text) return;
      clearTimeout(_hideTimer);
      tt.textContent = text;
      tt.classList.add('visible');
      _posTT(el);
    }

    function _posTT(el) {
      const r = el.getBoundingClientRect();
      const margin = 10;
      const ttW = 260, ttH = 80;
      let top  = r.bottom + 8;
      let left = r.left;
      if (top + ttH > window.innerHeight - margin)  top  = r.top - ttH - 8;
      if (left + ttW > window.innerWidth  - margin)  left = window.innerWidth - ttW - margin;
      if (left < margin) left = margin;
      tt.style.top  = top  + 'px';
      tt.style.left = left + 'px';
    }

    function _hideTT() {
      _hideTimer = setTimeout(() => tt.classList.remove('visible'), 80);
    }

    ['adv-modal', 'adv-create-dialog'].forEach(id => {
      const root = document.getElementById(id);
      if (!root) return;
      root.addEventListener('mouseover', e => {
        const el = e.target.closest('[data-tooltip]');
        if (el) _showTT(el);
      });
      root.addEventListener('mouseout', e => {
        const el = e.target.closest('[data-tooltip]');
        if (el) _hideTT();
      });
    });
  });
