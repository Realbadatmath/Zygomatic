// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Frequency
 * FL Studio-style waveform board — one canvas lane per LLM/tool/dependency.
 * 60fps rAF animation with 2s data polling and lerp interpolation.
 */
(function () {
    'use strict';

    /* ── Entity catalogue ─────────────────────────────────────────────── */
    // resource_profile: which resource categories this entity participates in
    // weight: relative load contribution within a stage (sum per stage ≈ 1.0)
    // freq_mult: unique wave frequency multiplier (visual differentiation)
    var ENTITIES = [
        // LLMs
        { id: 'claude-sonnet-4-6',    label: 'Claude Sonnet 4.6',    cat: 'llm',    gpu: false, vram: false, cpu: true,  ram: true,  weight: 0.9, freq: 0.72 },
        { id: 'qwen2.5:72b',          label: 'Qwen2.5 72B',          cat: 'llm',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.8, freq: 0.61 },
        { id: 'qwen3.5:9b',           label: 'Qwen3.5 9B (vision)',  cat: 'llm',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.75, freq: 0.55 },
        { id: 'gpt-oss:20b',          label: 'GPT-OSS 20B',           cat: 'llm',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.4, freq: 0.83 },
        { id: 'qwen3.6:35b-a3b',      label: 'Qwen3.6 35B-A3B',       cat: 'llm',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.85, freq: 0.66 },
        
        { id: 'qwen2.5-coder:32b',    label: 'Qwen2.5-Coder 32B',    cat: 'llm',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.7, freq: 0.77 },
        { id: 'deepseek-coder:33b',   label: 'DeepSeek-Coder 33B',   cat: 'llm',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.72, freq: 0.49 },
        { id: 'moondream:latest',     label: 'Moondream',             cat: 'llm',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.3, freq: 0.91 },
        // Image Generation
        { id: 'flux.1-schnell',       label: 'FLUX.1-schnell',        cat: 'imggen', gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 1.0, freq: 0.44 },
        { id: 'controlnet',           label: 'ControlNet',            cat: 'imggen', gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.6, freq: 0.53 },
        { id: 'ipadapter',            label: 'IPAdapter',             cat: 'imggen', gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.55, freq: 0.68 },
        { id: 'flux-fill',            label: 'FLUX Fill',             cat: 'imggen', gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.65, freq: 0.37 },
        { id: 'realesrgan',           label: 'RealESRGAN x4',         cat: 'imggen', gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.45, freq: 0.58 },
        // TTS / Audio
        { id: 'fish-speech',          label: 'Fish Speech S2-Pro',    cat: 'tts',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.7, freq: 0.81 },
        { id: 'orpheus-3b',           label: 'Orpheus 3B',            cat: 'tts',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.65, freq: 0.74 },
        { id: 'indextts2',            label: 'IndexTTS-2',            cat: 'tts',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.35, freq: 1.12 },
        { id: 'musicgen',             label: 'MusicGen',              cat: 'tts',    gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.6, freq: 0.63 },
        // Video
        { id: 'wan2.1-i2v',          label: 'Wan2.1-I2V-14B',        cat: 'video',  gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 1.0, freq: 0.39 },
        { id: 'rife',                 label: 'RIFE (frame interp)',   cat: 'video',  gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.5, freq: 0.47 },
        { id: 'object-track',         label: 'Object Tracking',       cat: 'video',  gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.4, freq: 0.56 },
        // Computer Vision
        { id: 'yolov8n',             label: 'YOLOv8n',               cat: 'cv',     gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.35, freq: 0.88 },
        { id: 'mediapipe',           label: 'MediaPipe',             cat: 'cv',     gpu: false, vram: false, cpu: true,  ram: true,  weight: 0.25, freq: 0.97 },
        { id: 'opencv',              label: 'OpenCV (cv2)',          cat: 'cv',     gpu: false, vram: false, cpu: true,  ram: true,  weight: 0.2, freq: 1.05 },
        // Infrastructure
        { id: 'whisper',             label: 'Whisper (openai)',      cat: 'infra',  gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.5, freq: 0.71 },
        { id: 'ffmpeg',              label: 'ffmpeg',                cat: 'infra',  gpu: false, vram: false, cpu: true,  ram: true,  weight: 0.45, freq: 0.93 },
        { id: 'pytorch',             label: 'PyTorch / CUDA',        cat: 'infra',  gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.3, freq: 0.41 },
        { id: 'ollama',              label: 'Ollama service',        cat: 'infra',  gpu: true,  vram: true,  cpu: true,  ram: true,  weight: 0.35, freq: 0.52 },
    ];

    /* ── Stage → active entity ids ───────────────────────────────────── */
    var STAGE_ENTITIES = {
        'stage 1':   ['claude-sonnet-4-6'],
        'stage 2':   ['claude-sonnet-4-6'],
        'stage 3':   ['claude-sonnet-4-6'],
        'stage 3b':  ['qwen3.5:9b'],
        'stage 3.1': ['qwen2.5:72b'],
        'stage 3.5': ['flux.1-schnell', 'controlnet', 'ipadapter', 'pytorch'],
        'stage 3.6': ['controlnet', 'realesrgan', 'pytorch'],
        'stage 4':   ['indextts2', 'chatterbox', 'whisper'],
        'stage 5':   ['ffmpeg'],
        'stage 6':   ['ffmpeg', 'rife', 'opencv'],
    };

    /* ── Category color palettes (gradient pairs [inner, outer]) ─────── */
    var CAT_COLORS = {
        llm:    ['#a855f7', '#22d3ee'],   // violet → cyan
        imggen: ['#f97316', '#ec4899'],   // orange → magenta
        tts:    ['#22c55e', '#a3e635'],   // green → lime
        video:  ['#ef4444', '#fbbf24'],   // red → gold
        cv:     ['#3b82f6', '#7dd3fc'],   // blue → sky
        infra:  ['#94a3b8', '#f1f5f9'],   // slate → white
    };

    var CAT_LABEL = { llm: 'LLMs', imggen: 'Image Gen', tts: 'TTS/Audio', video: 'Video', cv: 'Computer Vision', infra: 'Infrastructure' };

    /* ── Per-entity unique vivid colors (one per entity in declaration order) ─── */
    var ENTITY_COLORS = [
        '#22d3ee','#a855f7','#f97316','#22c55e','#ef4444',
        '#eab308','#ec4899','#14b8a6','#84cc16','#6366f1',
        '#f43f5e','#0ea5e9','#10b981','#f59e0b','#8b5cf6',
        '#06b6d4','#d946ef','#3b82f6','#4ade80','#fb7185',
        '#fbbf24','#34d399','#c084fc','#60a5fa','#2dd4bf',
        '#fb923c','#a3e635',
    ];
    ENTITIES.forEach(function(e, i) { e._colorIdx = i; });

    function hexToRgb(hex) {
        return parseInt(hex.slice(1,3),16) + ',' + parseInt(hex.slice(3,5),16) + ',' + parseInt(hex.slice(5,7),16);
    }

    /* ── State ───────────────────────────────────────────────────────── */
    var _mode       = 'all';    // 'gpu' | 'vram' | 'cpu' | 'ram' | 'all'
    var _rafId      = null;
    var _pollTimer  = null;
    var _startTime  = 0;
    var _liveData   = null;     // last API response
    var _histMode   = false;    // playback from historical run
    var _histData   = null;     // { telemetry:[], stages:[] }
    var _histFrame  = 0;
    var _histPaused = false;
    var _container  = null;
    var _canvas     = null;
    var _ctx        = null;
    var _tooltip    = null;
    var _histPanel  = null;
    var _allRuns    = [];
    var _modelList  = null;
    var _onKeyDown  = null;     // single keydown listener — removed/re-added each render()

    // Calibration hard limits (synced from server via /api/calibrate)
    var _calibration = {
        max_vram_gb:   48.0,
        max_gpu_watts: 450.0,
        max_cpu_pct:   80.0,
        max_ram_gb:    56.0,
    };

    // Per-entity interpolation state
    var _entityState = {};
    ENTITIES.forEach(function(e) {
        _entityState[e.id] = { cur: 0, target: 0, lerpT: 1 };
    });

    /* ── Helpers ─────────────────────────────────────────────────────── */
    function byId(id) { return document.getElementById(id); }

    function lerp(a, b, t) { return a + (b - a) * Math.min(1, Math.max(0, t)); }

    function getVisibleEntities() {
        if (_mode === 'all') return ENTITIES;
        return ENTITIES.filter(function(e) {
            if (_mode === 'gpu')  return e.gpu;
            if (_mode === 'vram') return e.vram;
            if (_mode === 'cpu')  return e.cpu;
            if (_mode === 'ram')  return e.ram;
            return true;
        });
    }

    /* ── Amplitude calculation ───────────────────────────────────────── */
    function computeTargetAmplitude(entity, liveData, activeEntityIds) {
        if (!liveData) return 0;
        var live = liveData.live || {};

        // Resource % scaled by entity.weight — each entity shows its own share of the available spec.
        // entity.weight (0–1) represents how much of the resource this entity claims when active.
        var rawVal = 0;
        if (_mode === 'gpu' || _mode === 'all') {
            if (entity.gpu) rawVal = Math.max(rawVal, (live.gpu_util_pct || 0) / 100);
        }
        if (_mode === 'vram' || _mode === 'all') {
            if (entity.vram) {
                var vramCeilMb = _calibration.max_vram_gb * 1024;
                rawVal = Math.max(rawVal, vramCeilMb > 0 ? (live.vram_used_mb || 0) / vramCeilMb : 0);
            }
        }
        if (_mode === 'cpu' || _mode === 'all') {
            if (entity.cpu) rawVal = Math.max(rawVal, (live.cpu_pct || 0) / _calibration.max_cpu_pct);
        }
        if (_mode === 'ram' || _mode === 'all') {
            if (entity.ram) {
                var ramCeilMb = _calibration.max_ram_gb * 1024;
                rawVal = Math.max(rawVal, ramCeilMb > 0 ? (live.ram_used_mb || 0) / ramCeilMb : 0);
            }
        }
        // Scale by entity weight — heavier entities fill more of the available spec
        return Math.min(1, rawVal * (entity.weight || 1));
    }

    function computeHistAmplitude(entity, row) {
        if (!row) return 0;
        var val = 0;
        if (_mode === 'gpu'  && entity.gpu)  val = (row.gpu_util_pct || 0) / 100;
        if (_mode === 'vram' && entity.vram) val = row.vram_total_mb > 0 ? (row.vram_used_mb || 0) / row.vram_total_mb : 0;
        if (_mode === 'cpu'  && entity.cpu)  val = (row.cpu_pct || 0) / 100;
        if (_mode === 'ram'  && entity.ram)  val = row.ram_total_mb > 0 ? (row.ram_used_mb || 0) / row.ram_total_mb : 0;
        if (_mode === 'all') {
            if (entity.gpu)  val = Math.max(val, (row.gpu_util_pct || 0) / 100);
            if (entity.vram) val = Math.max(val, row.vram_total_mb > 0 ? (row.vram_used_mb || 0) / row.vram_total_mb : 0);
            if (entity.cpu)  val = Math.max(val, (row.cpu_pct || 0) / 100);
            if (entity.ram)  val = Math.max(val, row.ram_total_mb > 0 ? (row.ram_used_mb || 0) / row.ram_total_mb : 0);
        }
        return Math.min(1, val * (entity.weight || 1));
    }

    /* ── Determine active entities from live data ────────────────────── */
    function getActiveEntityIds(liveData) {
        if (!liveData) return [];
        var ids = (liveData.active_entities || []).map(function(s){ return s.toLowerCase(); });
        // Also check active stages
        (liveData.active_stages || []).forEach(function(stageName) {
            var key = stageName.toLowerCase().replace(/^stage\s*/, 'stage ');
            Object.keys(STAGE_ENTITIES).forEach(function(k) {
                if (key.indexOf(k) !== -1 || k.indexOf(key.replace('stage ', '')) !== -1) {
                    STAGE_ENTITIES[k].forEach(function(id) {
                        if (ids.indexOf(id) === -1) ids.push(id);
                    });
                }
            });
        });
        return ids;
    }

    /* ── Canvas drawing ──────────────────────────────────────────────── */
    function drawFrame(timestamp) {
        if (!_ctx || !_canvas) return;
        var t    = (timestamp - _startTime) / 1000;
        var W    = _canvas.width;
        var H    = _canvas.height;
        var vis  = getVisibleEntities();
        var midY = H * 0.5;
        var MIN_FREQ = 0.37, MAX_FREQ = 1.12;

        // Deep dark background
        _ctx.fillStyle = '#070712';
        _ctx.fillRect(0, 0, W, H);

        // Clip all wave drawing to canvas bounds — prevents overflow
        _ctx.save();
        _ctx.beginPath();
        _ctx.rect(0, 0, W, H);
        _ctx.clip();

        // Subtle horizontal grid
        _ctx.strokeStyle = 'rgba(255,255,255,0.025)';
        _ctx.lineWidth = 1;
        [0.2, 0.35, 0.65, 0.8].forEach(function(p) {
            _ctx.beginPath(); _ctx.moveTo(0, H * p); _ctx.lineTo(W, H * p); _ctx.stroke();
        });

        // Center dashed line
        _ctx.strokeStyle = 'rgba(255,255,255,0.10)';
        _ctx.lineWidth = 1;
        _ctx.setLineDash([8, 6]);
        _ctx.beginPath(); _ctx.moveTo(0, midY); _ctx.lineTo(W, midY); _ctx.stroke();
        _ctx.setLineDash([]);

        // Draw each entity wave — all overlaid on the same canvas
        vis.forEach(function(entity) {
            var st = _entityState[entity.id];
            st.lerpT = Math.min(1, st.lerpT + 0.04);
            st.cur   = lerp(st.cur, st.target, st.lerpT);

            var amp    = st.cur;
            var color  = ENTITY_COLORS[entity._colorIdx % ENTITY_COLORS.length];
            var rgb    = hexToRgb(color);
            var maxAmp = H * 0.245;
            var waveH  = amp * maxAmp;
            if (waveH < 1) return;

            // Map entity.freq → peak X position (EQ spectrum distribution)
            var peakPos  = 0.1 + normFreq * 0.8;
            var speed    = 1.4 + entity.freq * 0.35;
            var STEP     = 4;

            // Sample upper wave with Gaussian envelope (peaks at peakPos)
            var upperPts = [];
            for (var xi = 0; xi <= W; xi += STEP) {
                var envX = Math.exp(-Math.pow((xi / W) - peakPos, 2) * 7);
                var px   = entity.freq * xi * 0.010 + t * speed;
                var yOff = envX * (Math.sin(px) * waveH + Math.sin(px * 1.73 + 1.2) * waveH * 0.3);
                upperPts.push({ x: xi, y: midY - Math.abs(yOff) });
            }

            // Lower mirror (symmetric around center line)
            var lowerPts = upperPts.slice().reverse().map(function(p) {
                return { x: p.x, y: midY + (midY - p.y) };
            });

            // Gradient fill between upper and lower
            var fillA = Math.min(0.28, 0.06 + amp * 0.24);
            var grad  = _ctx.createLinearGradient(0, midY - waveH, 0, midY + waveH);
            grad.addColorStop(0,   'rgba(' + rgb + ',' + fillA + ')');
            grad.addColorStop(0.5, 'rgba(' + rgb + ',' + Math.min(0.45, fillA * 2.2) + ')');
            grad.addColorStop(1,   'rgba(' + rgb + ',' + fillA + ')');
            _ctx.beginPath();
            upperPts.forEach(function(p, i) { i ? _ctx.lineTo(p.x, p.y) : _ctx.moveTo(p.x, p.y); });
            lowerPts.forEach(function(p)    { _ctx.lineTo(p.x, p.y); });
            _ctx.closePath();
            _ctx.fillStyle = grad;
            _ctx.fill();

            // Glow — wide soft stroke above upper line; thickness scales with amplitude
            var glowA = Math.min(0.35, amp * 0.5);
            var lineW_glow  = Math.max(2.0, amp * 14.0);
            var lineW_crisp = Math.max(0.8, amp * 4.0);
            _ctx.strokeStyle = 'rgba(' + rgb + ',' + glowA + ')';
            _ctx.lineWidth = lineW_glow; _ctx.lineJoin = 'round';
            _ctx.beginPath();
            upperPts.forEach(function(p, i) { i ? _ctx.lineTo(p.x, p.y) : _ctx.moveTo(p.x, p.y); });
            _ctx.stroke();

            // Crisp bright upper line
            _ctx.strokeStyle = 'rgba(' + rgb + ',' + Math.min(0.92, 0.3 + amp * 0.8) + ')';
            _ctx.lineWidth = lineW_crisp;
            _ctx.beginPath();
            upperPts.forEach(function(p, i) { i ? _ctx.lineTo(p.x, p.y) : _ctx.moveTo(p.x, p.y); });
            _ctx.stroke();

            // Lower mirror glow + crisp line
            _ctx.strokeStyle = 'rgba(' + rgb + ',' + glowA + ')';
            _ctx.lineWidth = lineW_glow;
            _ctx.beginPath();
            lowerPts.forEach(function(p, i) { i ? _ctx.lineTo(p.x, p.y) : _ctx.moveTo(p.x, p.y); });
            _ctx.stroke();
            _ctx.strokeStyle = 'rgba(' + rgb + ',' + Math.min(0.92, 0.3 + amp * 0.8) + ')';
            _ctx.lineWidth = lineW_crisp;
            _ctx.beginPath();
            lowerPts.forEach(function(p, i) { i ? _ctx.lineTo(p.x, p.y) : _ctx.moveTo(p.x, p.y); });
            _ctx.stroke();
        });

        // Restore clip so stage markers / playhead don't get clipped
        _ctx.restore();
        if (_histMode && _histData && _histData.stages && _histData.telemetry.length > 0) {
            var totalFrames = _histData.telemetry.length;
            _histData.stages.forEach(function(stg) {
                if (!stg.started_at || !_histData.telemetry[0]) return;
                var stgTs = stg.started_at.replace('T', ' ').slice(0, 19);
                for (var fi = 0; fi < totalFrames; fi++) {
                    if ((_histData.telemetry[fi].ts || '').slice(0, 19) >= stgTs) {
                        var markerX = (fi / totalFrames) * W;
                        _ctx.strokeStyle = 'rgba(255,220,50,0.5)';
                        _ctx.lineWidth = 1;
                        _ctx.setLineDash([3, 3]);
                        _ctx.beginPath(); _ctx.moveTo(markerX, 0); _ctx.lineTo(markerX, H); _ctx.stroke();
                        _ctx.setLineDash([]);
                        _ctx.save();
                        _ctx.translate(markerX + 3, 12);
                        _ctx.fillStyle = 'rgba(255,220,50,0.9)';
                        _ctx.font = '9px monospace';
                        _ctx.textAlign = 'left'; _ctx.textBaseline = 'top';
                        _ctx.fillText(stg.name.replace('Stage ', 'S'), 0, 0);
                        _ctx.restore();
                        break;
                    }
                }
            });
            // Playhead
            var playX = (_histFrame / Math.max(1, totalFrames - 1)) * W;
            _ctx.strokeStyle = 'rgba(255,80,80,0.9)';
            _ctx.lineWidth = 2;
            _ctx.beginPath(); _ctx.moveTo(playX, 0); _ctx.lineTo(playX, H); _ctx.stroke();
        }

        _rafId = requestAnimationFrame(drawFrame);
    }

    /* ── Data polling (live) ──────────────────────────────────────────── */
    function pollLive() {
        fetch('/api/frequency/data', { credentials: 'same-origin' })
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; })
            .then(function(data) {
                if (!data) return;
                _liveData = data;
                // Sync calibration from server response
                if (data.calibration) {
                    _calibration.max_vram_gb   = data.calibration.max_vram_gb   || _calibration.max_vram_gb;
                    _calibration.max_gpu_watts = data.calibration.max_gpu_watts || _calibration.max_gpu_watts;
                    _calibration.max_cpu_pct   = data.calibration.max_cpu_pct   || _calibration.max_cpu_pct;
                    _calibration.max_ram_gb    = data.calibration.max_ram_gb    || _calibration.max_ram_gb;
                }
                var activeIds = getActiveEntityIds(data);
                ENTITIES.forEach(function(e) {
                    var target = computeTargetAmplitude(e, data, activeIds);
                    _entityState[e.id].target = target;
                    _entityState[e.id].lerpT  = 0;
                });
                updateStatusBar(data);
            });
    }

    /* ── Calibrate panel ──────────────────────────────────────────────── */
    function openCalibratePanel() {
        if (byId('freq-calibrate-overlay')) { byId('freq-calibrate-overlay').remove(); return; }

        var overlay = document.createElement('div');
        overlay.id  = 'freq-calibrate-overlay';
        overlay.style.cssText = [
            'position:fixed;top:0;left:0;right:0;bottom:0;',
            'background:rgba(0,0,0,0.72);backdrop-filter:blur(4px);',
            'display:flex;align-items:center;justify-content:center;z-index:9998;',
        ].join('');

        var ROW_STYLE = 'display:flex;align-items:center;gap:10px;margin-bottom:14px;';
        var LBL_STYLE = 'color:#94a3b8;font-size:11px;width:150px;flex-shrink:0;text-transform:uppercase;letter-spacing:1px;';
        var INP_STYLE = 'background:#0d0d1a;border:1px solid #334155;color:#e2e8f0;padding:5px 9px;border-radius:6px;font-family:monospace;font-size:13px;width:90px;';
        var UNIT_STYLE = 'color:#475569;font-size:11px;';

        function makeRow(id, label, unit, value, listId, presets) {
            var opts = presets.map(function(p) { return '<option value="' + p + '">'; }).join('');
            return '<div style="' + ROW_STYLE + '">'
                + '<span style="' + LBL_STYLE + '">' + label + '</span>'
                + '<input id="calib-' + id + '" type="number" list="calib-list-' + id + '" '
                + 'value="' + value + '" style="' + INP_STYLE + '" step="any">'
                + '<datalist id="calib-list-' + id + '">' + opts + '</datalist>'
                + '<span style="' + UNIT_STYLE + '">' + unit + '</span>'
                + '</div>';
        }

        var panel = document.createElement('div');
        panel.style.cssText = [
            'background:#0a0a14;border:1px solid #a855f7;border-radius:12px;',
            'padding:28px 32px;width:440px;',
            'box-shadow:0 0 40px rgba(168,85,247,0.25);',
            'font-family:"SF Mono","Fira Mono",monospace;',
        ].join('');

        panel.innerHTML =
            '<div style="display:flex;align-items:center;margin-bottom:22px;">'
            + '<span style="color:#a855f7;font-size:16px;font-weight:700;letter-spacing:2px;">⚙ CALIBRATE</span>'
            + '<span style="color:#334155;font-size:10px;margin-left:10px;">Hard limits — stages block until hardware is under ceiling</span>'
            + '<button id="calib-close" style="margin-left:auto;background:none;border:none;color:#555;font-size:20px;cursor:pointer;line-height:1;">✕</button>'
            + '</div>'
            + makeRow('vram',  'Max VRAM',       'GB',  _calibration.max_vram_gb,   'vram',  [16, 24, 32, 40, 44, 48])
            + makeRow('watts', 'Max GPU Wattage','W',   _calibration.max_gpu_watts, 'watts', [150, 200, 250, 300, 350, 400, 450])
            + makeRow('cpu',   'Max CPU',        '%',   _calibration.max_cpu_pct,   'cpu',   [50, 60, 70, 75, 80, 90, 100])
            + makeRow('ram',   'Max RAM',        'GB',  _calibration.max_ram_gb,    'ram',   [16, 32, 48, 56, 60, 64])
            + '<div style="display:flex;gap:10px;margin-top:8px;">'
            + '<button id="calib-apply" style="flex:1;background:#a855f7;border:none;color:#fff;padding:9px;border-radius:7px;font-size:13px;font-family:inherit;cursor:pointer;font-weight:700;letter-spacing:1px;">APPLY</button>'
            + '<button id="calib-cancel" style="flex:1;background:#1e1e2e;border:1px solid #334155;color:#94a3b8;padding:9px;border-radius:7px;font-size:13px;font-family:inherit;cursor:pointer;">Cancel</button>'
            + '</div>'
            + '<div id="calib-msg" style="color:#ef4444;font-size:11px;margin-top:10px;min-height:16px;text-align:center;"></div>';

        overlay.appendChild(panel);
        document.body.appendChild(overlay);

        function closeOverlay() {
            var el = byId('freq-calibrate-overlay');
            if (el) el.remove();
        }

        byId('calib-close').onclick  = closeOverlay;
        byId('calib-cancel').onclick = closeOverlay;

        overlay.addEventListener('mousedown', function(e) {
            if (e.target === overlay) closeOverlay();
        });

        byId('calib-apply').onclick = function() {
            var payload = {
                max_vram_gb:   parseFloat(byId('calib-vram').value),
                max_gpu_watts: parseFloat(byId('calib-watts').value),
                max_cpu_pct:   parseFloat(byId('calib-cpu').value),
                max_ram_gb:    parseFloat(byId('calib-ram').value),
            };
            byId('calib-msg').textContent = '';
            var csrfTok = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
            var postHeaders = { 'Content-Type': 'application/json' };
            if (csrfTok) postHeaders['X-CSRFToken'] = csrfTok;
            fetch('/api/calibrate', {
                method:      'POST',
                credentials: 'same-origin',
                headers:     postHeaders,
                body:        JSON.stringify(payload),
            })
            .then(function(r) { return r.json(); })
            .catch(function() { return { success: false, errors: ['Network error'] }; })
            .then(function(d) {
                if (d.success) {
                    _calibration = Object.assign(_calibration, d.calibration);
                    if (d.hw_msg) {
                        // Brief flash of hw_msg before closing
                        var msgEl = byId('calib-msg');
                        if (msgEl) {
                            msgEl.style.color = d.hw_msg.indexOf('Warning') === -1 ? '#22c55e' : '#f59e0b';
                            msgEl.textContent = d.hw_msg;
                        }
                        setTimeout(closeOverlay, 900);
                    } else {
                        closeOverlay();
                    }
                } else {
                    byId('calib-msg').textContent = (d.errors || ['Unknown error']).join(' | ');
                }
            });
        };

        // Enter key applies
        panel.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') byId('calib-apply').click();
            if (e.key === 'Escape') closeOverlay();
        });

        // Focus first input
        setTimeout(function() { var el = byId('calib-vram'); if (el) el.focus(); }, 50);
    }

    /* ── Model list (M key) ──────────────────────────────────────────── */
    function openModelList() {
        if (_modelList && document.body.contains(_modelList)) {
            _modelList.remove(); _modelList = null; return;
        }
        var vis = getVisibleEntities();
        var panel = document.createElement('div');
        panel.id = 'freq-model-list';
        panel.style.cssText = [
            'position:absolute;top:0;left:0;',
            'background:rgba(7,7,18,0.94);backdrop-filter:blur(12px);',
            'border-right:1px solid rgba(168,85,247,0.25);border-bottom:1px solid rgba(168,85,247,0.25);',
            'border-radius:0 0 10px 0;padding:6px 0 10px;min-width:236px;',
            'max-height:calc(100% - 8px);overflow-y:auto;z-index:200;font-family:monospace;',
        ].join('');

        var cats = {};
        vis.forEach(function(e) {
            if (!cats[e.cat]) cats[e.cat] = [];
            cats[e.cat].push(e);
        });

        var html = '<div style="color:#a855f7;font-size:10px;letter-spacing:2px;padding:8px 14px;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:4px;">Models &amp; Tools — M to close</div>';
        Object.keys(cats).forEach(function(cat) {
            html += '<div style="color:#475569;font-size:9px;letter-spacing:2px;padding:7px 14px 2px;text-transform:uppercase;">' + (CAT_LABEL[cat] || cat) + '</div>';
            cats[cat].forEach(function(e) {
                var color = ENTITY_COLORS[e._colorIdx % ENTITY_COLORS.length];
                var pct   = (_entityState[e.id] ? (_entityState[e.id].cur * 100) : 0).toFixed(0);
                html += '<div style="display:flex;align-items:center;gap:8px;padding:4px 14px;">'
                    + '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';flex-shrink:0;display:inline-block;box-shadow:0 0 6px ' + color + ';"></span>'
                    + '<span style="color:#cbd5e1;font-size:11px;flex:1;">' + e.label + '</span>'
                    + '<span style="color:' + color + ';font-size:10px;width:32px;text-align:right;">' + pct + '%</span>'
                    + '</div>';
            });
        });
        panel.innerHTML = html;

        panel.addEventListener('mouseleave', function() {
            if (_modelList) { _modelList.remove(); _modelList = null; }
        });

        var boardWrap = _container.querySelector('.freq-board-wrap');
        if (boardWrap) boardWrap.appendChild(panel);
        _modelList = panel;
    }

    /* ── Historical playback ─────────────────────────────────────────── */
    function startHistPlayback(data) {
        _histMode   = true;
        _histData   = data;
        _histFrame  = 0;
        _histPaused = false;
        updateHistControls();
        advanceHistFrame();
    }

    function advanceHistFrame() {
        if (!_histMode || _histPaused || !_histData) return;
        var frames = _histData.telemetry;
        if (_histFrame >= frames.length) {
            _histFrame = 0; // loop
        }
        var row = frames[_histFrame];
        ENTITIES.forEach(function(e) {
            _entityState[e.id].target = computeHistAmplitude(e, row);
            _entityState[e.id].lerpT  = 0;
        });
        _histFrame++;
        // Each frame = 1s real telemetry; play at 30× speed = ~33ms interval
        setTimeout(advanceHistFrame, 33);
    }

    function updateHistControls() {
        var playBtn = byId('freq-hist-play');
        if (playBtn) playBtn.textContent = _histPaused ? '▶ Play' : '⏸ Pause';
    }

    /* ── Status bar ──────────────────────────────────────────────────── */
    function updateStatusBar(data) {
        var el = byId('freq-status-bar');
        if (!el || !data) return;
        var live = data.live || {};
        var parts = [];
        var gpu = (live.gpu_util_pct || 0).toFixed(0);
        var vram = live.vram_total_mb > 0 ? ((live.vram_used_mb / live.vram_total_mb) * 100).toFixed(1) : '—';
        var cpu  = (live.cpu_pct || 0).toFixed(0);
        var ram  = live.ram_total_mb > 0 ? ((live.ram_used_mb / live.ram_total_mb) * 100).toFixed(1) : '—';
        parts.push('GPU ' + gpu + '%');
        parts.push('VRAM ' + vram + '%');
        parts.push('CPU ' + cpu + '%');
        parts.push('RAM ' + ram + '%');
        if (live.gpu_power_w > 0) parts.push(live.gpu_power_w.toFixed(0) + 'W / ' + _calibration.max_gpu_watts.toFixed(0) + 'W');
        if (live.gpu_temp_c > 0)  parts.push(live.gpu_temp_c.toFixed(0) + '°C');
        var pipe = data.active_pipeline_id ? ('▶ ' + data.active_pipeline_id.slice(0, 8)) : '— idle';
        if (data.pipeline_topic) pipe += ' — ' + data.pipeline_topic.slice(0, 40);
        el.innerHTML = '<span style="color:#22d3ee;">' + parts.join('  |  ') + '</span>'
            + '  &nbsp;&nbsp;  '
            + '<span style="color:#a855f7;">' + pipe + '</span>';
    }

    /* ── Canvas mouse → tooltip ──────────────────────────────────────── */
    function onCanvasMouseMove(e) {
        if (!_canvas || !_tooltip) return;
        var rect   = _canvas.getBoundingClientRect();
        var mouseX = e.clientX - rect.left;
        var mouseY = e.clientY - rect.top;
        var H      = _canvas.height;
        var midY   = H * 0.5;
        var vis    = getVisibleEntities();
        var live   = (_liveData && _liveData.live) || {};
        var t      = (_startTime > 0) ? ((performance.now() - _startTime) / 1000) : 0;
        var MIN_FREQ = 0.37, MAX_FREQ = 1.12;

        // Find entity whose upper wave y-value at mouseX is closest to mouseY
        var closest = null;
        var closestDist = Infinity;
        vis.forEach(function(entity) {
            var st = _entityState[entity.id];
            if (!st || st.cur < 0.01) return;
            var normFreq = (entity.freq - MIN_FREQ) / (MAX_FREQ - MIN_FREQ);
            var peakPos  = 0.1 + normFreq * 0.8;
            var maxAmp   = H * 0.245;
            var waveH    = st.cur * maxAmp;
            var envX     = Math.exp(-Math.pow((mouseX / H) - peakPos, 2) * 7);
            var speed    = 1.4 + entity.freq * 0.35;
            var px       = entity.freq * mouseX * 0.010 + t * speed;
            var yOff     = envX * (Math.sin(px) * waveH + Math.sin(px * 1.73 + 1.2) * waveH * 0.3);
            var waveY    = midY - Math.abs(yOff);
            var dist     = Math.abs(mouseY - waveY);
            if (dist < closestDist) { closestDist = dist; closest = entity; }
        });

        if (!closest || closestDist > 80) {
            _tooltip.style.display = 'none';
            return;
        }

        var color  = ENTITY_COLORS[closest._colorIdx % ENTITY_COLORS.length];
        var st     = _entityState[closest.id];
        var lines  = [
            '<strong style="color:' + color + '">' + closest.label + '</strong>',
            'Category: ' + (CAT_LABEL[closest.cat] || closest.cat),
        ];
        if (closest.gpu)  lines.push('GPU util: ' + (live.gpu_util_pct || 0).toFixed(1) + '%');
        if (live.gpu_power_w > 0) lines.push('Power: ' + live.gpu_power_w.toFixed(0) + 'W / ' + _calibration.max_gpu_watts.toFixed(0) + 'W');
        if (closest.vram) lines.push('VRAM: ' + ((live.vram_used_mb || 0) / 1024).toFixed(1) + ' / ' + _calibration.max_vram_gb.toFixed(0) + ' GB');
        if (closest.cpu)  lines.push('CPU: ' + (live.cpu_pct || 0).toFixed(1) + '% / ' + _calibration.max_cpu_pct.toFixed(0) + '%');
        if (closest.ram)  lines.push('RAM: ' + ((live.ram_used_mb || 0) / 1024).toFixed(1) + ' GB / ' + _calibration.max_ram_gb.toFixed(0) + ' GB');
        lines.push('Amplitude: ' + (st ? (st.cur * 100).toFixed(1) : '0') + '%');
        if (_liveData && _liveData.active_entities && _liveData.active_entities.indexOf(closest.id) !== -1) {
            lines.push('<span style="color:#22c55e">● Active in pipeline</span>');
        }
        _tooltip.innerHTML = lines.join('<br>');
        var tx = e.clientX + 14, ty = e.clientY - 10;
        if (tx + 220 > window.innerWidth) tx = e.clientX - 234;
        _tooltip.style.left    = tx + 'px';
        _tooltip.style.top     = ty + 'px';
        _tooltip.style.display = 'block';
    }

    /* ── History panel ───────────────────────────────────────────────── */
    function openHistoryPanel() {
        if (_histPanel) { _histPanel.style.display = 'flex'; return; }
        _histPanel = document.createElement('div');
        _histPanel.id = 'freq-history-panel';
        _histPanel.style.cssText = 'position:absolute;top:0;right:0;width:320px;height:100%;background:#0f0f1a;border-left:1px solid #333;display:flex;flex-direction:column;z-index:100;font-family:monospace;';
        _histPanel.innerHTML =
            '<div style="display:flex;align-items:center;padding:10px 12px;border-bottom:1px solid #222;">'
            + '<span style="color:#a855f7;font-weight:700;font-size:13px;">Pipeline History</span>'
            + '<button id="freq-hist-close" style="margin-left:auto;background:none;border:none;color:#888;font-size:18px;cursor:pointer;">✕</button>'
            + '</div>'
            + '<div id="freq-hist-list" style="flex:1;overflow-y:auto;padding:8px 0;"></div>';
        _container.querySelector('.freq-board-wrap').appendChild(_histPanel);

        byId('freq-hist-close').onclick = function() { _histPanel.style.display = 'none'; };

        fetch('/api/frequency/history', { credentials: 'same-origin' })
            .then(function(r) { return r.ok ? r.json() : { runs: [] }; })
            .catch(function() { return { runs: [] }; })
            .then(function(d) {
                _allRuns = d.runs || [];
                renderHistList();
            });
    }

    function renderHistList() {
        var el = byId('freq-hist-list');
        if (!el) return;
        if (!_allRuns.length) {
            el.innerHTML = '<div style="color:#555;padding:16px;font-size:12px;">No pipeline runs with telemetry found.</div>';
            return;
        }
        el.innerHTML = _allRuns.map(function(r, i) {
            var date = (r.started || '').slice(0, 16).replace('T', ' ');
            var hasTelem = r.has_telemetry;
            var col  = r.status === 'completed' ? '#22c55e' : r.status === 'failed' ? '#ef4444' : '#888';
            return '<div class="freq-hist-item" data-idx="' + i + '" style="padding:8px 14px;border-bottom:1px solid #1a1a2e;cursor:' + (hasTelem ? 'pointer' : 'default') + ';opacity:' + (hasTelem ? 1 : 0.4) + ';">'
                + '<div style="color:#e2e8f0;font-size:11px;font-weight:600;">' + (r.topic || r.id.slice(0, 20)) + '</div>'
                + '<div style="color:#64748b;font-size:10px;margin-top:2px;">' + (r.department || '') + ' · ' + date + '</div>'
                + '<div style="font-size:10px;margin-top:2px;">'
                + '<span style="color:' + col + ';">' + r.status + '</span>'
                + (r.elapsed_s > 0 ? ' · ' + r.elapsed_s.toFixed(0) + 's' : '')
                + (hasTelem ? ' <span style="color:#a855f7;">⟳ telemetry</span>' : '')
                + '</div></div>';
        }).join('');

        el.querySelectorAll('.freq-hist-item').forEach(function(item) {
            item.addEventListener('click', function() {
                var idx = parseInt(this.getAttribute('data-idx'));
                var run = _allRuns[idx];
                if (!run || !run.has_telemetry) return;
                loadHistRun(run.id);
            });
            item.addEventListener('mouseenter', function() { if (this.style.opacity !== '0.4') this.style.background = '#1a1a2e'; });
            item.addEventListener('mouseleave', function() { this.style.background = ''; });
        });
    }

    function loadHistRun(pipelineId) {
        var el = byId('freq-hist-list');
        if (el) el.innerHTML = '<div style="color:#a855f7;padding:16px;font-size:12px;">Loading telemetry…</div>';

        fetch('/api/frequency/history/' + encodeURIComponent(pipelineId), { credentials: 'same-origin' })
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; })
            .then(function(data) {
                if (!data || !data.telemetry || !data.telemetry.length) {
                    if (el) el.innerHTML = '<div style="color:#ef4444;padding:16px;font-size:12px;">No telemetry data.</div>';
                    return;
                }
                if (_histPanel) _histPanel.style.display = 'none';
                _histMode = false; // reset
                // Add playback controls
                var ctrlBar = byId('freq-hist-ctrl');
                if (!ctrlBar) {
                    ctrlBar = document.createElement('div');
                    ctrlBar.id = 'freq-hist-ctrl';
                    ctrlBar.style.cssText = 'position:absolute;bottom:0;left:0;right:0;background:#0f0f1a;border-top:1px solid #333;display:flex;align-items:center;gap:8px;padding:6px 12px;font-family:monospace;font-size:11px;z-index:50;';
                    _container.querySelector('.freq-board-wrap').appendChild(ctrlBar);
                }
                ctrlBar.innerHTML = '<span style="color:#a855f7;font-weight:700;">HIST:</span>'
                    + '<span style="color:#94a3b8;">' + (data.topic || pipelineId.slice(0, 12)) + '</span>'
                    + '<button id="freq-hist-play" style="background:#1e1e2e;border:1px solid #333;color:#e2e8f0;padding:2px 10px;border-radius:4px;cursor:pointer;">⏸ Pause</button>'
                    + '<button id="freq-hist-stop" style="background:#1e1e2e;border:1px solid #333;color:#e2e8f0;padding:2px 10px;border-radius:4px;cursor:pointer;">⏹ Live</button>'
                    + '<span id="freq-hist-frame-info" style="color:#64748b;margin-left:8px;"></span>';
                byId('freq-hist-play').onclick = function() {
                    _histPaused = !_histPaused;
                    updateHistControls();
                    if (!_histPaused) advanceHistFrame();
                };
                byId('freq-hist-stop').onclick = function() {
                    _histMode  = false;
                    _histData  = null;
                    _histFrame = 0;
                    ctrlBar.remove();
                    // Resume live polling
                    if (_pollTimer) clearInterval(_pollTimer);
                    _pollTimer = setInterval(pollLive, 2000);
                    pollLive();
                };
                startHistPlayback(data);
                // Pause live polling during playback
                if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
            });
    }

    /* ── Canvas resize ───────────────────────────────────────────────── */
    function resizeCanvas() {
        if (!_canvas || !_container) return;
        var board = _canvas.parentElement;
        var W = board ? (board.clientWidth  || window.innerWidth)  : window.innerWidth;
        var H = board ? (board.clientHeight || window.innerHeight - 60) : window.innerHeight - 60;
        _canvas.width  = W;
        _canvas.height = H;
    }

    /* ── Main render entry ───────────────────────────────────────────── */
    function render(container) {
        _container = container;
        if (!container) return;

        container.style.cssText = 'position:fixed;top:0;left:192px;right:0;bottom:0;z-index:100;overflow:hidden;background:#070712;color:#e2e8f0;padding:0;display:flex;flex-direction:column;font-family:"SF Mono","Fira Mono",monospace;';

        container.innerHTML =
            // Header bar
            '<div style="display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #1a1a2e;background:#0a0a14;">'
            + '<span style="font-size:18px;font-weight:700;color:#a855f7;letter-spacing:1px;">⌘ FREQUENCY</span>'
            + '<span style="color:#334155;font-size:11px;margin-left:4px;">waveform activity monitor</span>'
            // Mode buttons
            + '<div id="freq-mode-btns" style="display:flex;gap:4px;margin-left:16px;">'
            + ['gpu','vram','cpu','ram','all'].map(function(m) {
                return '<button class="freq-mode-btn" data-mode="' + m + '" style="padding:4px 14px;border-radius:20px;border:1px solid #333;background:' + (m === _mode ? '#a855f7' : '#1e1e2e') + ';color:' + (m === _mode ? '#fff' : '#94a3b8') + ';font-size:11px;cursor:pointer;font-family:inherit;text-transform:uppercase;letter-spacing:1px;">' + m + '</button>';
              }).join('')
            + '</div>'
            // Status bar
            + '<div id="freq-status-bar" style="flex:1;font-size:10px;margin-left:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></div>'
            // History button
            + '<button id="freq-hist-btn" title="Pipeline run history" style="background:none;border:1px solid #334155;color:#94a3b8;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:13px;margin-left:8px;">🕐</button>'
            // Calibrate button
            + '<button id="freq-calib-btn" title="Calibrate hard limits  (C)" style="background:none;border:1px solid #475569;color:#64748b;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px;margin-left:4px;letter-spacing:1px;">⚙ C</button>'
            // Models button
            + '<button id="freq-model-btn" title="Show model list  (M)" style="background:none;border:1px solid #334155;color:#64748b;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px;margin-left:4px;letter-spacing:1px;">≡ M</button>'
            + '</div>'
            // Board — fills remaining height
            + '<div class="freq-board-wrap" style="position:relative;flex:1;overflow:hidden;">'
            + '<canvas id="freq-canvas" style="display:block;width:100%;height:100%;cursor:crosshair;"></canvas>'
            + '</div>'
            // Tooltip
            + '<div id="freq-tooltip" style="position:fixed;display:none;background:#0f0f1a;border:1px solid #a855f7;padding:8px 12px;border-radius:8px;font-size:11px;color:#e2e8f0;pointer-events:none;z-index:9999;max-width:220px;line-height:1.6;"></div>';

        _canvas  = byId('freq-canvas');
        _ctx     = _canvas.getContext('2d');
        _tooltip = byId('freq-tooltip');

        // Mode button clicks
        container.querySelectorAll('.freq-mode-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                _mode = btn.getAttribute('data-mode');
                container.querySelectorAll('.freq-mode-btn').forEach(function(b) {
                    b.style.background = b.getAttribute('data-mode') === _mode ? '#a855f7' : '#1e1e2e';
                    b.style.color      = b.getAttribute('data-mode') === _mode ? '#fff' : '#94a3b8';
                });
                resizeCanvas();
            });
        });

        // History button
        byId('freq-hist-btn').addEventListener('click', openHistoryPanel);

        // Calibrate button + keyboard shortcut
        byId('freq-calib-btn').addEventListener('click', openCalibratePanel);
        // Models button + keyboard shortcut
        byId('freq-model-btn').addEventListener('click', openModelList);
        // Keyboard shortcuts — remove stale listener first to prevent duplicates
        if (_onKeyDown) document.removeEventListener('keydown', _onKeyDown);
        _onKeyDown = function(e) {
            if (!_container || !document.body.contains(_container)) {
                document.removeEventListener('keydown', _onKeyDown);
                _onKeyDown = null;
                return;
            }
            if ((e.key === 'c' || e.key === 'C') && !e.ctrlKey && !e.metaKey && !e.altKey) {
                var tag = (document.activeElement || {}).tagName || '';
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
                openCalibratePanel();
            }
            if ((e.key === 'm' || e.key === 'M') && !e.ctrlKey && !e.metaKey && !e.altKey) {
                var tag2 = (document.activeElement || {}).tagName || '';
                if (tag2 === 'INPUT' || tag2 === 'TEXTAREA' || tag2 === 'SELECT') return;
                openModelList();
            }
        };
        document.addEventListener('keydown', _onKeyDown);

        // Canvas hover tooltip
        _canvas.addEventListener('mousemove', onCanvasMouseMove);
        _canvas.addEventListener('mouseleave', function() { if (_tooltip) _tooltip.style.display = 'none'; });

        // Resize observer
        if (window.ResizeObserver) {
            new ResizeObserver(resizeCanvas).observe(_canvas.parentElement);
        } else {
            window.addEventListener('resize', resizeCanvas);
        }

        resizeCanvas();
        requestAnimationFrame(resizeCanvas); // re-measure after browser reflow

        // Start animation loop
        _startTime = performance.now();
        if (_rafId) cancelAnimationFrame(_rafId);
        _rafId = requestAnimationFrame(drawFrame);

        // Start data polling
        if (_pollTimer) clearInterval(_pollTimer);
        pollLive();
        _pollTimer = setInterval(pollLive, 2000);
    }

    /* ── Cleanup when tab is navigated away ─────────────────────────── */
    function destroy() {
        if (_rafId)    { cancelAnimationFrame(_rafId); _rafId = null; }
        if (_pollTimer){ clearInterval(_pollTimer);    _pollTimer = null; }
        if (_onKeyDown){ document.removeEventListener('keydown', _onKeyDown); _onKeyDown = null; }
    }

    window.DashboardTabFrequency = { render: render, destroy: destroy };
})();
