// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

  const PREVIEW_CONFIG = {
    DEFAULT_WIDTH: 150,
    DEFAULT_HEIGHT: 150,
    HOVER_WIDTH_VIDEO: 300,
    HOVER_HEIGHT_VIDEO: 200,
    HOVER_WIDTH_IMAGE: 200,
    HOVER_HEIGHT_IMAGE: 200,
    STORAGE_KEY: 'zero_preview_windows',
    MIRROR_DETACHED_KEY: 'zero_preview_mirror_detached',
    AUDIO_UNLOCK_KEY: 'zero_preview_audio_unlocked',
    // Output level after limiter; per-clip calibration normalizes to this peak.
    PREVIEW_OUTPUT_GAIN: 0.65,
    PREVIEW_TARGET_PEAK: 0.18,
    PREVIEW_CALIB_SAMPLES: 10,
    DEFAULT_PREVIEW_VOLUME: 1.0,
    PREVIEW_MAX_VIDEO_MB: 1024,
    // Cloudflare tunnel / proxy often rejects single POST bodies above ~100 MB.
    PREVIEW_TUNNEL_MAX_MB: 100,
    PREVIEW_CHUNK_BYTES: 8 * 1024 * 1024,
    DEBUG_STORAGE_KEY: 'zero_preview_debug',
    /** IndexedDB cache for /uploads preview media (fast refresh). */
    PREVIEW_IDB_NAME: 'zero-preview-media-v1',
    PREVIEW_CACHE_NAME: 'zero-preview-media-v1',
    PREVIEW_LOAD_CONCURRENCY: 4,
    /** false = reliable video.volume (recommended). true = Web Audio compressor/limiter. */
    PREVIEW_USE_WEB_AUDIO: false
  };

  let _previewLastPlayError = null;

  const PreviewDebug = {
    enabled: false,
    maxEntries: 220,
    filterKind: '',
    entries: [],
    _panel: null,
    _logEl: null,
    _stateEl: null,

    init() {
      const qs = new URLSearchParams(window.location.search);
      const stored = localStorage.getItem(PREVIEW_CONFIG.DEBUG_STORAGE_KEY) === '1';
      if (qs.get('preview_debug') === '1' || stored) this.setEnabled(true, false);
      this._ensurePanel();
      document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'D') {
          e.preventDefault();
          this.toggle();
        }
      });
      window.PreviewDebug = this;
      if (this.enabled) {
        this.log('sys', 'Debug panel open', { hint: 'Ctrl+Shift+D to toggle' });
      }
    },

    _ensurePanel() {
      if (this._panel) return;
      const panel = document.createElement('div');
      panel.id = 'preview-debug-panel';
      panel.innerHTML =
        '<div class="pdbg-hdr">' +
        '<span class="pdbg-title">Preview debug</span>' +
        '<button type="button" class="pdbg-btn" data-act="snap">Snap</button>' +
        '<button type="button" class="pdbg-btn" data-act="export">Export</button>' +
        '<button type="button" class="pdbg-btn" data-act="clear">Clear</button>' +
        '<button type="button" class="pdbg-btn" data-act="close">✕</button>' +
        '</div>' +
        '<div class="pdbg-filters">' +
        '<label>Filter <select id="preview-debug-filter">' +
        '<option value="">all</option>' +
        '<option value="media">media</option>' +
        '<option value="audio">audio</option>' +
        '<option value="occlude">occlude</option>' +
        '<option value="drag">drag</option>' +
        '<option value="sys">sys</option>' +
        '</select></label>' +
        '</div>' +
        '<div class="pdbg-state" id="preview-debug-state">—</div>' +
        '<div class="pdbg-log" id="preview-debug-log"></div>';
      document.body.appendChild(panel);
      this._panel = panel;
      this._stateEl = panel.querySelector('#preview-debug-state');
      this._logEl = panel.querySelector('#preview-debug-log');
      panel.querySelector('[data-act="clear"]').addEventListener('click', () => this.clear());
      panel.querySelector('[data-act="close"]').addEventListener('click', () => this.setEnabled(false));
      panel.querySelector('[data-act="snap"]').addEventListener('click', () => {
        this.log('sys', 'Manual snapshot', this.snapshot());
        this._renderState();
      });
      panel.querySelector('[data-act="export"]').addEventListener('click', () => {
        const blob = new Blob([JSON.stringify({ snapshot: this.snapshot(), entries: this.entries }, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'preview-debug-' + Date.now() + '.json';
        a.click();
        URL.revokeObjectURL(a.href);
        this.log('sys', 'Exported log', { entries: this.entries.length });
      });
      const filt = panel.querySelector('#preview-debug-filter');
      if (filt) {
        filt.addEventListener('change', () => {
          this.filterKind = filt.value || '';
          this._rerenderLog();
        });
      }
    },

    _rerenderLog() {
      if (!this._logEl) return;
      this._logEl.innerHTML = '';
      this.entries.forEach((e) => {
        if (this.filterKind && e.kind !== this.filterKind) return;
        this._appendEntry(e);
      });
    },

    setEnabled(on, persist = true) {
      this.enabled = !!on;
      this._ensurePanel();
      if (this._panel) this._panel.classList.toggle('open', this.enabled);
      if (persist) {
        try {
          if (this.enabled) localStorage.setItem(PREVIEW_CONFIG.DEBUG_STORAGE_KEY, '1');
          else localStorage.removeItem(PREVIEW_CONFIG.DEBUG_STORAGE_KEY);
        } catch (_) {}
      }
      if (this.enabled) this._renderState();
    },

    toggle() {
      this.setEnabled(!this.enabled);
      this.log('sys', this.enabled ? 'Debug panel ON' : 'Debug panel OFF');
    },

    clear() {
      this.entries = [];
      _previewLastPlayError = null;
      if (this._logEl) this._logEl.innerHTML = '';
      this._renderState();
    },

    log(kind, message, data) {
      const entry = {
        t: new Date().toISOString().slice(11, 23),
        kind: kind || 'sys',
        message: String(message || ''),
        data: data !== undefined ? data : null
      };
      this.entries.push(entry);
      if (this.entries.length > this.maxEntries) this.entries.shift();
      const show = this.enabled && (!this.filterKind || this.filterKind === entry.kind);
      if (show) this._appendEntry(entry);
      if (this.enabled) this._renderState();
      try { console.debug('[preview-debug]', entry.kind, entry.message, entry.data); } catch (_) {}
    },

    _appendEntry(entry) {
      if (!this._logEl) return;
      const row = document.createElement('div');
      row.className = 'pdbg-entry k-' + (entry.kind || 'sys');
      const dataStr = entry.data != null
        ? ' ' + (typeof entry.data === 'string' ? entry.data : JSON.stringify(entry.data))
        : '';
      row.innerHTML =
        '<span class="t">' + entry.t + '</span>' +
        '<span class="k">' + entry.kind + '</span>' +
        entry.message + dataStr;
      this._logEl.appendChild(row);
      this._logEl.scrollTop = this._logEl.scrollHeight;
    },

    snapshot() {
      const ctx = _previewAudioCtx;
      const wins = [];
      if (typeof PreviewWindowManager !== 'undefined') {
        PreviewWindowManager.windows.forEach((win, id) => {
          const video = win.element?.querySelector('video');
          wins.push({
            id,
            mirror: !!win.isMirror,
            video: !!win.isVideo,
            x: Math.round(win.x),
            y: Math.round(win.y),
            enlarged: !!win.isEnlarged,
            dragging: !!win.isDragging,
            occluded: win.element?.classList.contains('occluded'),
            url: (win.imageUrl || '').slice(0, 48),
            vMuted: video ? video.muted : null,
            vPaused: video ? video.paused : null,
            vVol: video ? video.volume : null,
            vTime: video && !isNaN(video.currentTime) ? +video.currentTime.toFixed(2) : null,
            vDur: video && !isNaN(video.duration) ? +video.duration.toFixed(2) : null,
            vRs: video ? video.readyState : null,
            hoverPlay: !!win._hoverPlaying,
            deferredSrc: !!win._deferredVideoSrc,
            playGen: win._playGen || 0
          });
        });
      }
      const hv = _hoveredPreviewWin;
      const hvVid = hv?.element?.querySelector('video');
      return {
        audioCtx: ctx ? ctx.state : 'none',
        userActivated: !!_previewUserActivated,
        sessionGesture: !!_previewSessionGesture,
        hovered: hv ? hv.id : null,
        hoverPlaying: hv ? !!hv._hoverPlaying : false,
        playGen: hv ? (hv._playGen || 0) : 0,
        lastPlayError: _previewLastPlayError,
        sharedMediaCache: _previewSharedBlobByUrl.size,
        idb: !!window.indexedDB,
        keepAlive: !!_previewAudioKeepAliveTimer,
        windowCount: wins.length,
        windows: wins
      };
    },

    _renderState() {
      if (!this._stateEl || !this.enabled) return;
      const s = this.snapshot();
      const hv = _hoveredPreviewWin?.element?.querySelector('video');
      this._stateEl.textContent =
        'ctx=' + s.audioCtx +
        ' | gesture=' + s.sessionGesture +
        ' | hover=' + (s.hovered || '—') +
        (s.hoverPlaying ? ' PLAYING gen=' + s.playGen : '') +
        (hv ? ' muted=' + hv.muted + ' paused=' + hv.paused + ' rs=' + hv.readyState : '') +
        (s.lastPlayError ? ' | ERR=' + s.lastPlayError.slice(0, 40) : '') +
        ' | mediaCache=' + s.sharedMediaCache +
        ' | wins=' + s.windowCount;
    }
  };

  function _pdbg(kind, message, data) {
    if (PreviewDebug.enabled) PreviewDebug.log(kind, message, data);
  }

  function _pdbgWarn(kind, message, data) {
    _pdbg(kind, message, data);
    try { console.warn('[preview-debug]', kind, message, data || ''); } catch (_) {}
  }

  /** Upload preview image/video; uses chunked POST for large videos through proxies. */
  async function uploadPreviewFileToServer(file) {
    const chunkSize = PREVIEW_CONFIG.PREVIEW_CHUNK_BYTES || (8 * 1024 * 1024);
    const tunnelBytes = (PREVIEW_CONFIG.PREVIEW_TUNNEL_MAX_MB || 100) * 1024 * 1024;
    const useChunks = file.size > Math.floor(tunnelBytes * 0.85);

    async function postForm(fd) {
      const r = await fetch('/api/preview_upload', { method: 'POST', body: fd, credentials: 'same-origin' });
      let d = {};
      try { d = await r.json(); } catch (_) {}
      if (!r.ok || !d.success) {
        throw new Error((d && d.error) || `Upload failed (HTTP ${r.status})`);
      }
      return d;
    }

    if (!useChunks) {
      const fd = new FormData();
      fd.append('file', file, file.name);
      if (typeof inviteToken === 'string' && inviteToken) {
        fd.append('invite_token', inviteToken);
      }
      const d = await postForm(fd);
      if (!d.url) throw new Error('Upload incomplete');
      return d.url;
    }

    const totalChunks = Math.ceil(file.size / chunkSize);
    const uploadId = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID().replace(/-/g, '')
      : Array.from(crypto.getRandomValues(new Uint8Array(16)))
          .map((b) => b.toString(16).padStart(2, '0')).join('');

    for (let i = 0; i < totalChunks; i++) {
      const fd = new FormData();
      const start = i * chunkSize;
      fd.append('file', file.slice(start, start + chunkSize), file.name);
      fd.append('upload_id', uploadId);
      fd.append('chunk_index', String(i));
      fd.append('total_chunks', String(totalChunks));
      fd.append('filename', file.name);
      fd.append('total_size', String(file.size));
      if (typeof inviteToken === 'string' && inviteToken) {
        fd.append('invite_token', inviteToken);
      }
      const d = await postForm(fd);
      if (d.url) return d.url;
    }
    throw new Error('Upload incomplete');
  }
  const uploadPreviewVideoToServer = uploadPreviewFileToServer;

  let _previewAudioCtx = null;
  let _previewAudioCtxWatchBound = false;
  let _previewAudioKeepAliveTimer = null;
  /** @type {Map<string, number>} cached output gain per video URL */
  const _previewLevelCache = new Map();
  const _previewMediaErrorCodes = { 1: 'MEDIA_ERR_ABORTED', 2: 'MEDIA_ERR_NETWORK', 3: 'MEDIA_ERR_DECODE', 4: 'MEDIA_ERR_SRC_NOT_SUPPORTED' };
  /** One blob URL per http(s) /uploads URL — mirrors share a single download. */
  const _previewSharedBlobByUrl = new Map();
  const _previewInflightByUrl = new Map();

  function _previewPlayableVideoSrc(url) {
    return (url || '').trim();
  }

  function _previewVideoErrorDetail(video) {
    const e = video?.error;
    if (!e) return null;
    return { code: e.code, name: _previewMediaErrorCodes[e.code] || 'unknown' };
  }

  const _previewMediaLoadQueue = [];
  let _previewMediaLoadActive = 0;
  let _previewIdbPromise = null;

  function _enqueuePreviewMediaLoad(task) {
    _previewMediaLoadQueue.push(task);
    _drainPreviewMediaLoadQueue();
  }

  function _openPreviewIdb() {
    if (_previewIdbPromise) return _previewIdbPromise;
    _previewIdbPromise = new Promise((resolve) => {
      if (!window.indexedDB) {
        resolve(null);
        return;
      }
      const name = PREVIEW_CONFIG.PREVIEW_IDB_NAME || 'zero-preview-media-v1';
      const req = indexedDB.open(name, 1);
      req.onerror = () => resolve(null);
      req.onsuccess = () => resolve(req.result);
      req.onupgradeneeded = (ev) => {
        const db = ev.target.result;
        if (!db.objectStoreNames.contains('blobs')) {
          db.createObjectStore('blobs');
        }
      };
    });
    return _previewIdbPromise;
  }

  async function _previewIdbGet(url) {
    const db = await _openPreviewIdb();
    if (!db) return null;
    return new Promise((resolve) => {
      const tx = db.transaction('blobs', 'readonly');
      const req = tx.objectStore('blobs').get(url);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => resolve(null);
    });
  }

  async function _previewIdbPut(url, blob) {
    const db = await _openPreviewIdb();
    if (!db || !blob) return false;
    return new Promise((resolve) => {
      const tx = db.transaction('blobs', 'readwrite');
      tx.objectStore('blobs').put(blob, url);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  }

  async function _previewIdbDelete(url) {
    const db = await _openPreviewIdb();
    if (!db) return;
    return new Promise((resolve) => {
      const tx = db.transaction('blobs', 'readwrite');
      tx.objectStore('blobs').delete(url);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  }

  async function _previewCachePut(url, response) {
    if (!window.caches) return;
    try {
      const cache = await caches.open(PREVIEW_CONFIG.PREVIEW_CACHE_NAME || 'zero-preview-media-v1');
      await cache.put(url, response.clone());
    } catch (_) {}
  }

  async function _previewCacheGetBlob(url) {
    if (!window.caches) return null;
    try {
      const cache = await caches.open(PREVIEW_CONFIG.PREVIEW_CACHE_NAME || 'zero-preview-media-v1');
      const res = await cache.match(url);
      if (!res || !res.ok) return null;
      return res.blob();
    } catch (_) {
      return null;
    }
  }

  async function _previewCacheDelete(url) {
    if (!window.caches) return;
    try {
      const cache = await caches.open(PREVIEW_CONFIG.PREVIEW_CACHE_NAME || 'zero-preview-media-v1');
      await cache.delete(url);
    } catch (_) {}
  }

  function _previewBlobUrlFromBlob(httpUrl, blob, source) {
    const blobUrl = URL.createObjectURL(blob);
    _previewSharedBlobByUrl.set(httpUrl, blobUrl);
    _pdbg('media', source, { url: httpUrl.slice(-44), kb: Math.round(blob.size / 1024) });
    return blobUrl;
  }

  /** Local site storage: IndexedDB + Cache API (survives refresh). */
  async function _previewPersistGetBlobUrl(httpUrl) {
    const u = (httpUrl || '').trim();
    if (!u || u.startsWith('data:') || u.startsWith('blob:')) return u;
    if (_previewSharedBlobByUrl.has(u)) return _previewSharedBlobByUrl.get(u);

    let blob = await _previewIdbGet(u);
    if (blob && blob.size > 8) {
      return _previewBlobUrlFromBlob(u, blob, 'IDB hit');
    }
    blob = await _previewCacheGetBlob(u);
    if (blob && blob.size > 8) {
      _previewIdbPut(u, blob);
      return _previewBlobUrlFromBlob(u, blob, 'Cache API hit');
    }
    return null;
  }

  async function _previewPersistStoreBlob(httpUrl, blob) {
    const u = (httpUrl || '').trim();
    if (!u || !blob || blob.size < 8) return null;
    await _previewIdbPut(u, blob);
    try {
      await _previewCachePut(u, new Response(blob, {
        headers: { 'Content-Type': blob.type || 'application/octet-stream' }
      }));
    } catch (_) {}
    return _previewBlobUrlFromBlob(u, blob, 'stored locally');
  }

  async function _drainPreviewMediaLoadQueue() {
    const max = PREVIEW_CONFIG.PREVIEW_LOAD_CONCURRENCY || 4;
    while (_previewMediaLoadQueue.length && _previewMediaLoadActive < max) {
      const task = _previewMediaLoadQueue.shift();
      _previewMediaLoadActive++;
      Promise.resolve()
        .then(() => task())
        .catch(() => {})
        .finally(() => {
          _previewMediaLoadActive--;
          _drainPreviewMediaLoadQueue();
        });
    }
  }

  async function _previewInvalidateSharedMedia(url, bustBlob = true) {
    const u = (url || '').trim();
    if (!u) return;
    if (bustBlob) {
      const blob = _previewSharedBlobByUrl.get(u);
      if (blob && blob.startsWith('blob:')) {
        try { URL.revokeObjectURL(blob); } catch (_) {}
      }
      _previewSharedBlobByUrl.delete(u);
      await _previewIdbDelete(u);
      await _previewCacheDelete(u);
    }
    _previewInflightByUrl.delete(u);
  }

  /** Network fetch (once per URL); saved to IndexedDB for instant refresh. */
  async function _fetchPreviewMediaBlob(httpUrl) {
    const u = (httpUrl || '').trim();
    if (!u || u.startsWith('data:') || u.startsWith('blob:')) return u;
    const cached = await _previewPersistGetBlobUrl(u);
    if (cached && cached.startsWith('blob:')) return cached;
    if (_previewInflightByUrl.has(u)) return _previewInflightByUrl.get(u);

    const task = (async () => {
      for (let attempt = 0; attempt < 6; attempt++) {
        try {
          const r = await fetch(u, { credentials: 'same-origin', cache: 'default' });
          if (r.status === 429) {
            const wait = Math.min(32000, Math.round(1200 * Math.pow(1.85, attempt)));
            _pdbgWarn('media', 'HTTP 429 — retry', { url: u.slice(-44), attempt, waitMs: wait });
            await new Promise((res) => setTimeout(res, wait));
            continue;
          }
          if (!r.ok) {
            _pdbgWarn('media', 'fetch not ok', { status: r.status, url: u.slice(-44) });
            return null;
          }
          const blob = await r.blob();
          return _previewPersistStoreBlob(u, blob);
        } catch (err) {
          _pdbgWarn('media', 'fetch error', { url: u.slice(-44), err: String(err), attempt });
          await new Promise((res) => setTimeout(res, 900 * (attempt + 1)));
        }
      }
      return null;
    })();

    _previewInflightByUrl.set(u, task);
    try {
      return await task;
    } finally {
      _previewInflightByUrl.delete(u);
    }
  }

  async function _resolvePreviewMediaSrc(url) {
    const raw = _previewPlayableVideoSrc(url);
    if (!raw) return '';
    if (raw.startsWith('data:') || raw.startsWith('blob:')) return raw;
    if (!raw.startsWith('/') && !raw.startsWith('http')) return raw;

    const local = await _previewPersistGetBlobUrl(raw);
    if (local) return local;

    const fetched = await _fetchPreviewMediaBlob(raw);
    return fetched || raw;
  }

  function _flushDeferredVideoSrc(win) {
    if (!win?.isVideo || !win._deferredVideoSrc) return;
    const video = win.element?.querySelector('video');
    const src = win._deferredVideoSrc;
    win._deferredVideoSrc = null;
    if (!video || !src || video.src === src) return;
    try {
      video.src = src;
      video.load();
      _pdbg('media', 'applied deferred src', { id: win.id });
    } catch (err) {
      _pdbgWarn('media', 'deferred src failed', { id: win.id, err: String(err) });
    }
  }

  /** @returns {'unchanged'|'applied'|'deferred'} */
  function _applyPrefetchedSrcToVideo(video, url, win) {
    if (!video || !url) return 'unchanged';
    const src = _previewPlayableVideoSrc(url);
    if (!src || video.src === src) return 'unchanged';
    if (win && win._hoverPlaying) {
      win._deferredVideoSrc = src;
      _pdbg('media', 'deferred src (hovering)', {
        id: win.id,
        rs: video.readyState,
        paused: video.paused
      });
      return 'deferred';
    }
    try {
      video.src = src;
      video.load();
      _pdbg('media', 'src applied', { id: win?.id, rs: video.readyState });
      return 'applied';
    } catch (err) {
      _pdbgWarn('media', 'src apply failed', { id: win?.id, err: String(err) });
      return 'unchanged';
    }
  }

  /** Chromium suspends AudioContext after ~30s; routed preview video then goes silent. */
  function _resumePreviewAudioContext() {
    const ctx = _getPreviewAudioContext();
    if (!ctx || ctx.state === 'closed') return Promise.resolve(false);
    if (ctx.state === 'running') return Promise.resolve(true);
    return ctx.resume().then(() => ctx.state === 'running').catch(() => false);
  }

  function _bindPreviewAudioContextWatch() {
    if (_previewAudioCtxWatchBound || !_previewAudioCtx) return;
    _previewAudioCtxWatchBound = true;
    _previewAudioCtx.addEventListener('statechange', () => {
      _pdbg('audio', 'AudioContext statechange', { state: _previewAudioCtx.state });
      if (_previewAudioCtx.state !== 'suspended') return;
      if (!_hoveredPreviewWin || !_hoveredPreviewWin.isVideo) return;
      const video = _hoveredPreviewWin.element?.querySelector('video');
      if (!video || video.paused || video.muted) return;
      _resumePreviewAudioContext().then((ok) => {
        _pdbg('audio', 'Auto-resume after suspend', { ok });
        if (ok && _hoveredPreviewWin) _hoveredPreviewWin.enableSound(true);
      });
    });
  }

  function _startPreviewAudioKeepAlive() {
    _stopPreviewAudioKeepAlive();
    _pdbg('audio', 'Audio keepalive started');
    _previewAudioKeepAliveTimer = setInterval(() => {
      if (!_hoveredPreviewWin || !_hoveredPreviewWin.isVideo) {
        _stopPreviewAudioKeepAlive();
        return;
      }
      const video = _hoveredPreviewWin.element?.querySelector('video');
      if (!video || video.paused || video.muted) return;
      const ctx = _previewAudioCtx;
      if (!ctx || ctx.state === 'running') return;
      _resumePreviewAudioContext().then((ok) => {
        if (ok && _hoveredPreviewWin) _hoveredPreviewWin.enableSound(true);
      });
    }, 8000);
  }

  function _stopPreviewAudioKeepAlive() {
    if (_previewAudioKeepAliveTimer) {
      _pdbg('audio', 'Audio keepalive stopped');
      clearInterval(_previewAudioKeepAliveTimer);
      _previewAudioKeepAliveTimer = null;
    }
  }

  function _getPreviewAudioContext() {
    if (!_previewAudioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      _previewAudioCtx = new Ctx();
      _bindPreviewAudioContextWatch();
    }
    return _previewAudioCtx;
  }

  function _previewCacheKey(urlKey, video) {
    return (urlKey || video?.currentSrc || video?.src || '').trim();
  }

  function _clearPreviewLevelCalibration(video) {
    if (!video) return;
    if (video._previewCalibTimer) {
      clearTimeout(video._previewCalibTimer);
      video._previewCalibTimer = null;
    }
  }

  function _applyCachedPreviewGain(video, urlKey) {
    const cacheKey = _previewCacheKey(urlKey, video);
    if (!video?._previewGainNode || !cacheKey || !_previewLevelCache.has(cacheKey)) return false;
    video._previewGainNode.gain.value = _previewLevelCache.get(cacheKey);
    return true;
  }

  function _schedulePreviewLevelCalibration(video, urlKey) {
    if (!video) return;
    _clearPreviewLevelCalibration(video);
    const cacheKey = _previewCacheKey(urlKey, video);
    if (_applyCachedPreviewGain(video, urlKey)) return;

    const base = PREVIEW_CONFIG.PREVIEW_OUTPUT_GAIN ?? 0.65;
    const target = PREVIEW_CONFIG.PREVIEW_TARGET_PEAK ?? 0.18;
    const maxSamples = PREVIEW_CONFIG.PREVIEW_CALIB_SAMPLES || 10;
    const peaks = [];

    const finish = () => {
      if (!video._previewGainNode) return;
      const ctx = _getPreviewAudioContext();
      let out = base;
      if (peaks.length) {
        const sorted = peaks.slice().sort((a, b) => b - a);
        const ref = sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * 0.15)))];
        if (ref > 0.002) {
          out = base * Math.min(4, Math.max(0.08, target / ref));
        }
      }
      if (ctx) video._previewGainNode.gain.setTargetAtTime(out, ctx.currentTime, 0.05);
      else video._previewGainNode.gain.value = out;
      if (cacheKey) _previewLevelCache.set(cacheKey, out);
      _pdbg('audio', 'level calibrated', { samples: peaks.length, out: +out.toFixed(3) });
    };

    const run = () => {
      video._previewCalibTimer = null;
      if (!video._previewAnalyser || !video._previewGainNode || video.paused || video.muted) return;
      const buf = new Float32Array(video._previewAnalyser.fftSize);
      video._previewAnalyser.getFloatTimeDomainData(buf);
      let peak = 0;
      for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i]));
      if (peak > 0.001) peaks.push(peak);
      if (peaks.length >= maxSamples) {
        finish();
        return;
      }
      video._previewCalibTimer = setTimeout(run, 220);
    };
    video._previewCalibTimer = setTimeout(run, 200);
  }

  function _wirePreviewAudioGraph(video, urlKey) {
    if (!video) return false;
    if (video._previewAudioWired) {
      _applyCachedPreviewGain(video, urlKey);
      return true;
    }
    const base = PREVIEW_CONFIG.PREVIEW_OUTPUT_GAIN ?? 0.65;
    const ctx = _getPreviewAudioContext();
    if (!ctx) {
      video._previewDirectAudio = true;
      video.volume = base;
      return false;
    }
    try {
      const src = ctx.createMediaElementSource(video);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      const compressor = ctx.createDynamicsCompressor();
      compressor.threshold.value = -24;
      compressor.knee.value = 12;
      compressor.ratio.value = 16;
      compressor.attack.value = 0.002;
      compressor.release.value = 0.18;
      const gain = ctx.createGain();
      gain.gain.value = base;
      src.connect(analyser);
      analyser.connect(compressor);
      compressor.connect(gain);
      gain.connect(ctx.destination);
      video._previewGainNode = gain;
      video._previewAnalyser = analyser;
      video._previewCompressor = compressor;
      video._previewMediaSource = src;
      video._previewAudioWired = true;
      video.volume = 1.0;
      _applyCachedPreviewGain(video, urlKey);
      return true;
    } catch (err) {
      _pdbg('audio', 'WebAudio wire failed — direct output', { err: String(err) });
      video._previewDirectAudio = true;
      video.volume = base;
      return false;
    }
  }

  function _previewDirectVolume(urlKey, video) {
    const cacheKey = _previewCacheKey(urlKey, video);
    return cacheKey && _previewLevelCache.has(cacheKey)
      ? _previewLevelCache.get(cacheKey)
      : (PREVIEW_CONFIG.PREVIEW_OUTPUT_GAIN ?? 0.65);
  }

  /** Unmute when session is unlocked (hover counts — browser may still reject unmuted play()). */
  function _setPreviewAudible(video, urlKey) {
    if (!video) return;
    if (!_previewSessionGesture) {
      video.muted = true;
      video.setAttribute('muted', '');
      return;
    }
    _previewUserActivated = true;
    let wired = false;
    const wantWebAudio = PREVIEW_CONFIG.PREVIEW_USE_WEB_AUDIO === true;
    const ctx = wantWebAudio ? _getPreviewAudioContext() : null;
    if (wantWebAudio && ctx && ctx.state === 'running' && !video._previewAudioWired) {
      wired = _wirePreviewAudioGraph(video, urlKey);
    }
    if (!wired || video._previewDirectAudio) {
      video._previewDirectAudio = true;
      try { video.volume = _previewDirectVolume(urlKey, video); } catch (_) {}
    } else {
      try { video.volume = 1.0; } catch (_) {}
      _schedulePreviewLevelCalibration(video, urlKey);
    }
    video.muted = false;
    video.removeAttribute('muted');
    _pdbg('audio', 'set audible', {
      wired,
      direct: !!video._previewDirectAudio,
      vol: video.volume,
      ctx: ctx ? ctx.state : 'skipped'
    });
  }

  function _stopPreviewAudioWatchdog(win) {
    if (!win?._audioWatchdog) return;
    clearInterval(win._audioWatchdog);
    win._audioWatchdog = null;
  }

  function _startPreviewAudioWatchdog(win) {
    _stopPreviewAudioWatchdog(win);
    if (!win || !win.isVideo) return;
    win._audioWatchdog = setInterval(() => {
      if (!win._hoverPlaying) {
        _stopPreviewAudioWatchdog(win);
        return;
      }
      const video = win.element?.querySelector('video');
      if (!video || video.paused) return;
      if (!_previewSessionGesture) return;
      if (video.muted) {
        _pdbg('audio', 'watchdog unmute', { id: win.id });
        _setPreviewAudible(video, win.imageUrl);
        video.play().catch(() => {});
      }
      _resumePreviewAudioContext();
    }, 350);
  }

  let _previewUserActivated = false;
  /** True after pointer/keyboard/touch this session — allows Web Audio routing. */
  let _previewSessionGesture = false;
  let _hoveredPreviewWin = null;

  (function _initPreviewAudioFromStorage() {
    try {
      if (localStorage.getItem(PREVIEW_CONFIG.AUDIO_UNLOCK_KEY) === '1') {
        _previewUserActivated = true;
        _previewSessionGesture = true;
      }
    } catch (_) {}
  })();

  /** Hover is the unlock moment — always try audible preview (browser may still block on cold first visit). */
  function _previewUnlockForHover() {
    _previewSessionGesture = true;
    _previewUserActivated = true;
    return true;
  }

  function _previewMarkAudibleSuccess() {
    try { localStorage.setItem(PREVIEW_CONFIG.AUDIO_UNLOCK_KEY, '1'); } catch (_) {}
  }

  function _unlockPreviewAudio() {
    _previewSessionGesture = true;
    _previewUserActivated = true;
    _pdbg('audio', 'audio unlocked (user gesture)');
    try { localStorage.setItem(PREVIEW_CONFIG.AUDIO_UNLOCK_KEY, '1'); } catch (_) {}
    const ctx = _getPreviewAudioContext();
    if (ctx && ctx.state === 'suspended') {
      try { ctx.resume(); } catch (_) {}
    }
    _resumePreviewAudioContext();
    if (_hoveredPreviewWin && _hoveredPreviewWin.isVideo) {
      const v = _hoveredPreviewWin.element?.querySelector('video');
      if (v && !v.paused) _hoveredPreviewWin._ensurePreviewAudio(v);
      else _hoveredPreviewWin.enableSound(true);
      _startPreviewAudioKeepAlive();
    }
  }
  window.addEventListener('pointerdown', _unlockPreviewAudio, { passive: true });
  window.addEventListener('click', _unlockPreviewAudio, { passive: true });
  window.addEventListener('keydown', _unlockPreviewAudio, { passive: true });
  window.addEventListener('touchstart', _unlockPreviewAudio, { passive: true });
  document.addEventListener('focusin', (e) => {
    if (e.target.closest('textarea, input, select, button, [contenteditable="true"]')) {
      _unlockPreviewAudio();
    }
  }, { passive: true });

  /* First pointer entry anywhere on the page (including moving straight to a preview). */
  window.addEventListener('pointerover', () => {
    _previewUnlockForHover();
  }, { passive: true, capture: true, once: true });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible' || !_previewSessionGesture) return;
    _resumePreviewAudioContext().then((ok) => {
      _pdbg('audio', 'visibility resume', { ok });
      if (ok && _hoveredPreviewWin?.isVideo) _hoveredPreviewWin.enableSound(true);
    });
  });

  let _occlusionScheduled = false;
  window._schedulePreviewOcclusion = function() {
    if (_occlusionScheduled) return;
    _occlusionScheduled = true;
    requestAnimationFrame(() => {
      _occlusionScheduled = false;
      if (typeof PreviewWindowManager !== 'undefined') PreviewWindowManager.updateOcclusion();
    });
  };

  class PreviewWindow {
    constructor(id, imageUrl, isVideo = false, x = null, y = null) {
      this.id = id;
      this.isMirror = PreviewWindowManager._isMirrorId(id);
      this.imageUrl = imageUrl;
      this.isVideo = isVideo;
      this.isDragging = false;
      this.isEnlarged = false;
      this.dragOffsetX = 0;
      this.dragOffsetY = 0;
      this.x = x !== null ? x : Math.random() * 200 + 100;
      this.y = y !== null ? y : Math.random() * 200 + 100;
      this._hoverPlaying = false;
      this._leaveDebounceTimer = null;
      
      this.createElement();
      this._syncMediaTypeClass();
      this.attachEvents();
      this.applyPosition();
      requestAnimationFrame(() => this._playIfAlreadyHovered());
    }

    /** Cursor already over the tile (e.g. reload) — pointerenter may not fire. */
    _playIfAlreadyHovered() {
      if (!this.element?.matches(':hover') || !this.isVideo) return;
      _hoveredPreviewWin = this;
      _previewUnlockForHover();
      this._tryPlayAudibleOnPointerEnter();
      this.playPreview().catch(() => {});
    }

    _ensureMediaErrorOverlay() {
      const content = this.element?.querySelector('.preview-content');
      if (!content || content.querySelector('.preview-media-load-err')) return;
      const el = document.createElement('div');
      el.className = 'preview-media-load-err';
      el.innerHTML =
        '<span>Media failed to load</span>' +
        '<button type="button">Retry</button>';
      el.querySelector('button').addEventListener('click', (e) => {
        e.stopPropagation();
        _previewInvalidateSharedMedia(this.imageUrl, true);
        this._clearMediaLoadError();
        this._mediaSrcApplied = false;
        this._applyMediaSrcNow(true);
      });
      content.appendChild(el);
    }

    _showMediaLoadError(reason) {
      this._ensureMediaErrorOverlay();
      this.element?.classList.add('preview-media-failed');
      _pdbgWarn('media', 'media load failed', { id: this.id, reason });
    }

    _clearMediaLoadError() {
      this.element?.classList.remove('preview-media-failed');
    }

    _bindPreviewMediaError(mediaEl) {
      if (!mediaEl || mediaEl._previewErrBound) return;
      mediaEl._previewErrBound = true;
      const onOk = () => this._clearMediaLoadError();
      if (mediaEl.tagName === 'VIDEO') {
        mediaEl.addEventListener('loadeddata', onOk, { once: false });
      } else {
        mediaEl.addEventListener('load', onOk, { once: false });
      }
      mediaEl.addEventListener('error', () => {
        if (mediaEl._previewErrRecovering) return;
        const httpUrl = _previewPlayableVideoSrc(this.imageUrl);
        if (!httpUrl || httpUrl.startsWith('data:') || httpUrl.startsWith('blob:')) {
          this._showMediaLoadError(mediaEl.tagName);
          return;
        }
        mediaEl._previewErrRecovering = true;
        _fetchPreviewMediaBlob(httpUrl).then((blobSrc) => {
          mediaEl._previewErrRecovering = false;
          if (blobSrc && this.element) {
            mediaEl.src = blobSrc;
            this._clearMediaLoadError();
            if (mediaEl.tagName === 'VIDEO') {
              try { mediaEl.load(); } catch (_) {}
            }
            return;
          }
          this._showMediaLoadError(mediaEl.tagName);
        });
      });
    }

    /** Apply image/video src (local IDB first, then shared network fetch). */
    _applyMediaSrcNow(priority = false) {
      if (!this.element || !this._hasRealMedia()) return Promise.resolve();

      const apply = async () => {
        const httpUrl = _previewPlayableVideoSrc(this.imageUrl);
        let src = await _previewPersistGetBlobUrl(httpUrl);
        if (!src) {
          src = await _fetchPreviewMediaBlob(httpUrl);
        }
        if (!src) src = httpUrl;
        if (!src || !this.element) return;
        this._clearMediaLoadError();
        if (this.isVideo) {
          const v = this.element.querySelector('video.preview-media');
          if (!v) return;
          if (v.src === src || (v.currentSrc && v.currentSrc === src)) {
            this._mediaSrcApplied = true;
            return;
          }
          v.src = src;
          try { v.load(); } catch (_) {}
          this._mediaSrcApplied = true;
          return;
        }
        const img = this.element.querySelector('img.preview-media');
        if (!img) return;
        if (img.src === src) {
          this._mediaSrcApplied = true;
          return;
        }
        img.src = src;
        this._mediaSrcApplied = true;
      };

      if (priority) {
        return apply().catch(() => {
          this._showMediaLoadError('fetch');
        });
      }
      return new Promise((resolve) => {
        _enqueuePreviewMediaLoad(async () => {
          try { await apply(); } catch (_) { this._showMediaLoadError('fetch'); }
          resolve();
        });
      });
    }

    _hasRealMedia() {
      if (typeof PreviewWindowManager === 'undefined') return false;
      return !PreviewWindowManager._isPlaceholderUrl(this.imageUrl);
    }

    _syncMediaTypeClass() {
      if (!this.element) return;
      this.element.classList.remove('preview-has-video', 'preview-has-image', 'preview-has-empty', 'preview-media-playing');
      if (!this._hasRealMedia()) {
        this.element.classList.add('preview-has-empty');
      } else if (this.isVideo) {
        this.element.classList.add('preview-has-video');
      } else {
        this.element.classList.add('preview-has-image');
      }
      this._ensureMediaHint();
    }

    _setPreviewPlayingUi(playing) {
      if (!this.element || !this.isVideo) return;
      this.element.classList.toggle('preview-media-playing', !!playing);
    }

    _ensureMediaHint() {
      const content = this.element?.querySelector('.preview-content');
      if (!content) return;
      content.querySelectorAll('.preview-media-hint').forEach((el) => el.remove());
      if (!this._hasRealMedia() || !this.isVideo) return;
      const hint = document.createElement('span');
      hint.className = 'preview-media-hint preview-play-hint';
      hint.setAttribute('aria-hidden', 'true');
      hint.title = 'Video — hover to play';
      hint.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-7z"/></svg>';
      const uploadBtn = content.querySelector('.preview-upload-btn');
      if (uploadBtn) content.insertBefore(hint, uploadBtn);
      else content.appendChild(hint);
    }

    _getMediaDisplaySize() {
      if (this.isVideo && this._hasRealMedia()) {
        return {
          w: PREVIEW_CONFIG.HOVER_WIDTH_VIDEO || 300,
          h: PREVIEW_CONFIG.HOVER_HEIGHT_VIDEO || 200
        };
      }
      if (this._hasRealMedia()) {
        return {
          w: PREVIEW_CONFIG.HOVER_WIDTH_IMAGE || 200,
          h: PREVIEW_CONFIG.HOVER_HEIGHT_IMAGE || 200
        };
      }
      return {
        w: PREVIEW_CONFIG.DEFAULT_WIDTH || 150,
        h: PREVIEW_CONFIG.DEFAULT_HEIGHT || 150
      };
    }

    _bindVideoPlaybackDebug(video) {
      if (!video || video._previewDbgBound) return;
      video._previewDbgBound = true;
      const logVid = (ev) => {
        _pdbg('media', `video.${ev}`, {
          id: this.id,
          t: +video.currentTime.toFixed(2),
          dur: isNaN(video.duration) ? null : +video.duration.toFixed(2),
          paused: video.paused,
          muted: video.muted,
          rs: video.readyState
        });
      };
      ['play', 'pause', 'ended', 'waiting', 'stalled', 'emptied'].forEach((ev) => {
        video.addEventListener(ev, () => logVid(ev));
      });
      video.addEventListener('play', () => {
        if (this._hoverPlaying) this._setPreviewPlayingUi(true);
      });
      video.addEventListener('pause', () => {
        if (!this._hoverPlaying) this._setPreviewPlayingUi(false);
      });
      video.addEventListener('error', () => {
        logVid('error');
      });
      video.addEventListener('volumechange', () => {
        _pdbg('audio', 'video.volumechange', {
          id: this.id,
          muted: video.muted,
          vol: video.volume,
          wired: !!video._previewAudioWired
        });
      });
      video.addEventListener('ended', () => {
        if (!this._hoverPlaying) return;
        _pdbg('media', 'video.loop restart', { id: this.id });
        try {
          video.currentTime = 0;
          if (_previewSessionGesture) _setPreviewAudible(video, this.imageUrl);
          video.play().catch(() => {});
        } catch (_) {}
      });
      video.addEventListener('playing', () => {
        if (!_previewUserActivated || !this._hoverPlaying) return;
        if (!video.muted && _previewSessionGesture && video._previewAudioWired) {
          _schedulePreviewLevelCalibration(video, this.imageUrl);
        }
      });
    }

    /** Frozen on screen — page scrolls underneath; position never adjusted for scroll. */
    applyPosition() {
      if (!this.element) return;
      this.element.style.left = `${this.x}px`;
      this.element.style.top = `${this.y}px`;
    }

    static stopAllOtherVideos(exceptElement = null) {
      try {
        const vids = document.querySelectorAll('#preview-container video.preview-media');
        vids.forEach(v => {
          if (exceptElement && v === exceptElement) return;
          try {
            v.pause();
            v.currentTime = 0;
            v.muted = true;
          } catch (_) {}
        });
      } catch (_) {}
    }

    createElement() {
      const container = document.createElement('div');
      container.className = 'preview-window';
      container.id = `preview-${this.id}`;
      container.dataset.preview = this.id;
      
      const content = document.createElement('div');
      content.className = 'preview-content';
      
      if (this.imageUrl && this.imageUrl !== 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"%3E%3Crect fill="%23262d3a" width="200" height="200"/%3E%3C/svg%3E') {
        if (this.isVideo) {
          content.innerHTML = `<video class="preview-media" muted loop playsinline preload="metadata"></video>`;
        } else {
          content.innerHTML = `<img class="preview-media" alt="Preview">`;
        }
      } else {
        content.innerHTML = `<div class="preview-media" style="background: #1a1a1a; display: flex; align-items: center; justify-content: center;"></div>`;
      }

      const uploadBtn = document.createElement('button');
      uploadBtn.className = 'preview-upload-btn';
      uploadBtn.innerHTML = '+';
      uploadBtn.type = 'button';

      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'preview-delete-btn';
      deleteBtn.innerHTML = '×';
      deleteBtn.type = 'button';
      deleteBtn.title = 'Remove this preview';
      
      const fileInput = document.createElement('input');
      fileInput.className = 'preview-file-input';
      fileInput.type = 'file';
      fileInput.accept = 'image/*,video/*';
      
      content.appendChild(uploadBtn);
      content.appendChild(deleteBtn);
      content.appendChild(fileInput);
      container.appendChild(content);
      
      document.getElementById('preview-container')?.appendChild(container);
      this.element = container;
      this.fileInput = fileInput;
      this.uploadBtn = uploadBtn;
      this.deleteBtn = deleteBtn;
      const media = container.querySelector('.preview-media');
      if (media) {
        this._bindPreviewMediaError(media);
        if (media.tagName === 'VIDEO') this._bindVideoPlaybackDebug(media);
        if (this._hasRealMedia()) this._applyMediaSrcNow(false);
      }
      this._ensureMediaHint();
    }

    remove() {
      PreviewWindowManager.removeWindow(this.id);
    }

    attachEvents() {
      this.element.addEventListener('mousedown', (e) => {
        if (e.target.closest('.preview-delete-btn, .preview-upload-btn, .preview-file-input')) return;
        this.bringToFront();
        if (this.isVideo) {
          _unlockPreviewAudio();
          const v = this.element.querySelector('video');
          if (v && _previewSessionGesture) {
            if (this._hoverPlaying) this._ensurePreviewAudio(v);
            else _setPreviewAudible(v, this.imageUrl);
          }
        }
      });
      this.element.addEventListener('dblclick', (e) => this.toggleEnlarge(e));
      this.element.addEventListener('pointerenter', () => {
        if (this._leaveDebounceTimer) {
          clearTimeout(this._leaveDebounceTimer);
          this._leaveDebounceTimer = null;
        }
        const now = Date.now();
        if (this._lastPointerEnterAt && now - this._lastPointerEnterAt < 50) return;
        this._lastPointerEnterAt = now;
        _hoveredPreviewWin = this;
        _previewUnlockForHover();
        _pdbg('media', 'pointerenter', { id: this.id, video: this.isVideo });
        this.bringToFront();
        if (this.isVideo) this._tryPlayAudibleOnPointerEnter();
        this.playPreview().catch(() => {});
      });
      this.element.addEventListener('mouseleave', () => {
        _pdbg('media', 'mouseleave (pending)', { id: this.id });
        if (this._leaveDebounceTimer) clearTimeout(this._leaveDebounceTimer);
        this._leaveDebounceTimer = setTimeout(() => {
          this._leaveDebounceTimer = null;
          if (this.element.matches(':hover')) {
            _pdbg('media', 'mouseleave cancelled — still inside', { id: this.id });
            return;
          }
          _pdbg('media', 'mouseleave confirmed', { id: this.id });
          if (_hoveredPreviewWin === this) _hoveredPreviewWin = null;
          this.stopPreview(true);
          this.scaleDown();
        }, 150);
      });
      
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.isEnlarged) {
          this.scaleDown();
        }
      });
      
      this.uploadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.fileInput.click();
      });

      this.deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        this.remove();
      });
      
      this.fileInput.addEventListener('change', (e) => this.handleFileUpload(e));
    }

    toggleEnlarge(e) {
      e.stopPropagation();
      if (this.isEnlarged) {
        this.scaleDown();
      } else {
        this.scaleUp();
      }
    }

    scaleUp() {
      this._preEnlargeX = this.x;
      this._preEnlargeY = this.y;
      this.isEnlarged = true;
      this._syncMediaTypeClass();
      this.element.classList.add('enlarged');
      const sz = this._getMediaDisplaySize();
      this.x = window.innerWidth / 2 - sz.w / 2;
      this.y = window.innerHeight / 2 - sz.h / 2;
      this.applyPosition();
      if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
    }

    scaleDown() {
      this.isEnlarged = false;
      this.element.classList.remove('enlarged');
      if (this._preEnlargeX != null) {
        this.x = this._preEnlargeX;
        this.y = this._preEnlargeY;
      }
      this.applyPosition();
      if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
    }

    handleFileUpload(e) {
      const file = e.target.files[0];
      if (!file) return;
      _pdbg('media', 'file selected', { id: this.id, name: file.name, type: file.type, mb: (file.size / 1048576).toFixed(2) });
      if (this.isMirror) {
        PreviewWindowManager.promoteMirrorToStandalone(this);
        PreviewWindowManager._persistWindows();
        _pdbg('mirror', 'mirror promoted on upload', { id: this.id });
      }
      const isVideo = file.type.startsWith('video/');
      // Videos exceed browser localStorage quota if stored as data: URLs, so they
      // disappear on refresh. Persist videos by uploading to the server and
      // storing a stable /uploads/... URL in localStorage.
      if (isVideo) {
        const maxMb = PREVIEW_CONFIG.PREVIEW_MAX_VIDEO_MB || 1024;
        const sizeMb = file.size / (1024 * 1024);
        if (sizeMb > maxMb) {
          alert(`Video is ${sizeMb.toFixed(1)} MB — server limit is ${maxMb} MB. Try compressing or use mp4/webm.`);
          this.fileInput.value = '';
          return;
        }

        uploadPreviewFileToServer(file)
          .then((url) => {
            this._ephemeralVideo = false;
            this.imageUrl = url;
            this.isVideo = true;
            this.updateMedia();
            this._syncMediaTypeClass();
            this.savePosition();
            PreviewWindowManager.syncMirrors();
          })
          .catch((err) => {
            console.error('Video preview upload failed:', err);
            try {
              this._ephemeralVideo = true;
              this.imageUrl = URL.createObjectURL(file);
              this.isVideo = true;
              this.updateMedia();
              this._syncMediaTypeClass();
              this.savePosition();
              PreviewWindowManager.syncMirrors();
              alert(
                `Could not save video on server (${err.message || 'unknown error'}).` +
                ' Preview works until you refresh. Try mp4 or webm, or compress the file.'
              );
            } catch (fallbackErr) {
              alert(`Video upload failed: ${err.message || 'unknown error'}`);
            }
          })
          .finally(() => { this.fileInput.value = ''; });
        return;
      }

      // Persist images on the server so left/right previews survive refresh
      // (data: URLs in localStorage often exceed quota and silently fail to save).
      uploadPreviewFileToServer(file)
        .then((url) => {
          this.imageUrl = url;
          this.isVideo = false;
          this.updateMedia();
          this._syncMediaTypeClass();
          this.savePosition();
          PreviewWindowManager.syncMirrors();
        })
        .catch((err) => {
          console.warn('Image preview server upload failed, using data URL:', err);
          const reader = new FileReader();
          reader.onload = (event) => {
            this.imageUrl = event.target.result;
            this.isVideo = false;
            this.updateMedia();
            this._syncMediaTypeClass();
            this.savePosition();
            PreviewWindowManager.syncMirrors();
          };
          reader.readAsDataURL(file);
        })
        .finally(() => { this.fileInput.value = ''; });
    }

    updateMedia() {
      const content = this.element.querySelector('.preview-content');
      const existingMedia = content.querySelector('.preview-media');
      
      if (existingMedia) {
        if (existingMedia._previewCalibTimer) clearTimeout(existingMedia._previewCalibTimer);
        existingMedia.remove();
      }
      
      const media = document.createElement(this.isVideo ? 'video' : 'img');
      media.className = 'preview-media';
      
      if (this.isVideo) {
        // Start muted so hover autoplay works; we unmute after audio unlock.
        media.muted = true;
        media.loop = true;
        media.playsInline = true;
        media.preload = 'metadata';
        media.style.width = '100%';
        media.style.height = '100%';
        media.style.objectFit = 'cover';
        media.style.display = 'block';
        try { media.volume = PREVIEW_CONFIG.DEFAULT_PREVIEW_VOLUME; } catch (_) {}
      } else {
        media.src = this.imageUrl;
        media.alt = 'Preview';
        media.style.width = '100%';
        media.style.height = '100%';
        media.style.objectFit = 'cover';
        media.style.display = 'block';
      }
      
      const uploadBtn = content.querySelector('.preview-upload-btn');
      content.insertBefore(media, uploadBtn);
      if (this.isVideo && media.tagName === 'VIDEO') this._bindVideoPlaybackDebug(media);
      this._bindPreviewMediaError(media);
      this._syncMediaTypeClass();
      if (this._hasRealMedia()) this._applyMediaSrcNow(false);
    }

    bringToFront() {
      this.element.style.zIndex = 1500;
      const allWindows = document.querySelectorAll('.preview-window');
      allWindows.forEach(win => {
        if (win !== this.element) {
          win.style.zIndex = 100;
        }
      });
    }

    enableSound(keepPlaying = false) {
      if (!this.isVideo || !_previewSessionGesture) return;
      const video = this.element.querySelector('video');
      if (!video) return;
      _pdbg('audio', 'enableSound', {
        id: this.id,
        keepPlaying,
        paused: video.paused,
        wasMuted: video.muted
      });
      if (!video.paused || keepPlaying) {
        this._ensurePreviewAudio(video);
        return;
      }
      video.muted = true;
      video.play().then(() => this._ensurePreviewAudio(video)).catch((err) => {
        _previewLastPlayError = String(err);
        _pdbgWarn('media', 'enableSound play failed', { id: this.id, err: String(err) });
      });
    }

    /** Synchronous play+unmute in hover event (best chance before async src/load). */
    _tryPlayAudibleOnPointerEnter() {
      if (!this.isVideo || !this.element) return;
      let v = this.element.querySelector('video.preview-media');
      if (!v || !this._hasRealMedia()) return;
      const httpUrl = _previewPlayableVideoSrc(this.imageUrl);
      const cached = _previewSharedBlobByUrl.get(httpUrl);
      if (cached && v.src !== cached) {
        try { v.src = cached; } catch (_) {}
      }
      if (!v.src && !v.currentSrc) return;
      if (v.readyState < HTMLMediaElement.HAVE_METADATA) return;
      this._hoverPlaying = true;
      v = this._useDirectPreviewVideoElement(v);
      _setPreviewAudible(v, this.imageUrl);
      const p = v.play();
      if (!p || !p.then) return;
      p.then(() => {
        if (!v.paused && !v.muted) _previewMarkAudibleSuccess();
        this._audioUpgradedThisHover = true;
        this._setPreviewPlayingUi(true);
        _startPreviewAudioKeepAlive();
        _startPreviewAudioWatchdog(this);
        _pdbg('audio', 'hover sync play ok', { id: this.id, vol: v.volume });
      }).catch(() => {});
    }

    /** Web Audio createMediaElementSource blocks normal output — replace element if needed. */
    _useDirectPreviewVideoElement(video) {
      if (!video || PREVIEW_CONFIG.PREVIEW_USE_WEB_AUDIO === true) return video;
      if (!video._previewAudioWired) return video;
      const t = video.currentTime || 0;
      const src = video.currentSrc || video.src;
      const parent = video.parentNode;
      if (!parent) return video;
      const fresh = document.createElement('video');
      fresh.className = video.className;
      fresh.muted = true;
      fresh.loop = true;
      fresh.playsInline = true;
      fresh.preload = 'metadata';
      if (src) fresh.src = src;
      parent.replaceChild(fresh, video);
      this._bindVideoPlaybackDebug(fresh);
      this._bindPreviewMediaError(fresh);
      try { fresh.currentTime = t; } catch (_) {}
      _pdbg('audio', 'replaced wired video for direct audio', { id: this.id });
      return fresh;
    }

    _ensurePreviewAudio(video) {
      if (!this._hoverPlaying || !_previewSessionGesture || !video) return;
      video = this._useDirectPreviewVideoElement(video);
      const finish = () => {
        if (!this._hoverPlaying) return;
        const v = this.element?.querySelector('video.preview-media') || video;
        _setPreviewAudible(v, this.imageUrl);
        _startPreviewAudioKeepAlive();
        _startPreviewAudioWatchdog(this);
        _pdbg('audio', 'upgraded on play', {
          id: this.id,
          direct: !!v._previewDirectAudio,
          muted: v.muted,
          vol: v.volume,
          paused: v.paused
        });
        if (v.paused) v.play().catch((err) => {
          _pdbgWarn('media', 'play after upgrade failed', { id: this.id, err: String(err) });
        });
      };
      if (this._audioUpgradedThisHover) {
        if (!video.muted) return;
        finish();
        return;
      }
      this._audioUpgradedThisHover = true;
      if (PREVIEW_CONFIG.PREVIEW_USE_WEB_AUDIO === true) {
        _resumePreviewAudioContext().then(() => finish());
      } else {
        finish();
      }
    }

    async playPreview() {
      if (!this.isVideo) return;
      const video = this.element.querySelector('video');
      if (!video || !this.imageUrl) return;

      this._playGen = (this._playGen || 0) + 1;
      const gen = this._playGen;

      _pdbg('media', 'playPreview', {
        id: this.id,
        gen,
        rs: video.readyState,
        gesture: _previewSessionGesture,
        paused: video.paused,
        src: (video.currentSrc || video.src || '').slice(0, 40)
      });
      this._hoverPlaying = true;
      const hadAudibleHover = this._audioUpgradedThisHover;
      PreviewWindow.stopAllOtherVideos(video);
      _stopPreviewAudioKeepAlive();
      _stopPreviewAudioWatchdog(this);
      await this._applyMediaSrcNow(true);
      if (!this._hoverPlaying || this._playGen !== gen) return;
      _applyPrefetchedSrcToVideo(video, this.imageUrl, this);
      _previewUnlockForHover();

      let v = this.element?.querySelector('video.preview-media') || video;
      if (!hadAudibleHover && !this._audioUpgradedThisHover) {
        v = this._useDirectPreviewVideoElement(v);
        _setPreviewAudible(v, this.imageUrl);
        this._audioUpgradedThisHover = true;
        _startPreviewAudioKeepAlive();
        _startPreviewAudioWatchdog(this);
      }

      const attemptPlay = (reason) => {
        if (!this._hoverPlaying || this._playGen !== gen) return;
        const el = this.element?.querySelector('video.preview-media') || v;
        const errDetail = _previewVideoErrorDetail(el);
        if (errDetail) {
          _pdbg('media', 'play skip (video error)', { id: this.id, reason, ...errDetail });
          return;
        }
        if (el.paused) {
          _setPreviewAudible(el, this.imageUrl);
        }
        const p = el.play();
        if (!p || !p.then) return;
        p.then(() => {
          if (!this._hoverPlaying || this._playGen !== gen) return;
          _previewLastPlayError = null;
          if (!el.muted) _previewMarkAudibleSuccess();
          _pdbg('media', 'play ok', {
            id: this.id,
            reason,
            gen,
            t: +el.currentTime.toFixed(2),
            muted: el.muted,
            vol: el.volume
          });
          this._setPreviewPlayingUi(true);
          if (el.muted) this._ensurePreviewAudio(el);
        }).catch((err) => {
          if (!el.muted) {
            el.muted = true;
            el.setAttribute('muted', '');
            el.play().then(() => this._ensurePreviewAudio(el)).catch(() => {});
            _pdbgWarn('media', 'audible play blocked — muted fallback', { id: this.id, err: String(err) });
            return;
          }
          _previewLastPlayError = String(err);
          _pdbgWarn('media', 'play() rejected', {
            id: this.id,
            reason,
            gen,
            rs: el.readyState,
            err: String(err)
          });
        });
      };

      attemptPlay('start');
      [250, 800].forEach((ms) => setTimeout(() => attemptPlay('retry@' + ms), ms));
      const onReady = () => attemptPlay('ready');
      video.addEventListener('loadeddata', onReady, { once: true });
      video.addEventListener('canplay', onReady, { once: true });
    }

    stopPreview(resetTime = true) {
      if (!this.isVideo) return;
      const video = this.element.querySelector('video');
      _pdbg('media', 'stopPreview', {
        id: this.id,
        resetTime,
        t: video ? +video.currentTime.toFixed(2) : null
      });
      this._hoverPlaying = false;
      this._audioUpgradedThisHover = false;
      this._playGen = (this._playGen || 0) + 1;
      this._setPreviewPlayingUi(false);
      _stopPreviewAudioKeepAlive();
      _stopPreviewAudioWatchdog(this);
      if (video) {
        _clearPreviewLevelCalibration(video);
        try {
          video.pause();
          if (resetTime) {
            video.currentTime = 0;
            requestAnimationFrame(() => {
              try { if (!this._hoverPlaying) video.currentTime = 0; } catch (_) {}
            });
          }
        } catch (_) {}
        video.muted = true;
        video.setAttribute('muted', '');
      }
      _flushDeferredVideoSrc(this);
    }

    savePosition() {
      PreviewWindowManager._persistWindows();
    }

    getState() {
      const url = this.imageUrl;
      const ephemeral = this._ephemeralVideo || (this.isVideo && url && url.startsWith('blob:'));
      const state = {
        id: this.id,
        imageUrl: ephemeral ? '' : url,
        isVideo: this.isVideo,
        x: this.x,
        y: this.y
      };
      if (this.mirrorDetachedFrom) state.mirrorDetachedFrom = this.mirrorDetachedFrom;
      return state;
    }
  }

  class PreviewWindowManager {
    static windows = new Map();
    /** Right-side source ids whose left mirror the user customized (no re-sync). */
    static _detachedMirrorSources = new Set();

    static _loadDetachedMirrors() {
      try {
        const raw = localStorage.getItem(PREVIEW_CONFIG.MIRROR_DETACHED_KEY);
        if (!raw) return;
        JSON.parse(raw).forEach((id) => {
          if (id) this._detachedMirrorSources.add(String(id));
        });
      } catch (_) {}
    }

    static _saveDetachedMirrors() {
      try {
        localStorage.setItem(
          PREVIEW_CONFIG.MIRROR_DETACHED_KEY,
          JSON.stringify([...this._detachedMirrorSources])
        );
      } catch (_) {}
    }

    static _detachMirrorSource(sourceId) {
      const sid = String(sourceId || '').trim();
      if (!sid || this._detachedMirrorSources.has(sid)) return;
      this._detachedMirrorSources.add(sid);
      this._saveDetachedMirrors();
    }

    /** Drop stale detaches — only keep sources with a saved customized left standalone. */
    static _reconcileDetachedMirrors() {
      const keep = new Set();
      this.windows.forEach((win, id) => {
        if (this._isMirrorId(id)) return;
        const src = win.mirrorDetachedFrom;
        if (!src) return;
        if (!this._isPlaceholderUrl(win.imageUrl)) keep.add(String(src));
      });
      this._detachedMirrorSources = keep;
      this._saveDetachedMirrors();
    }

    static _persistWindows() {
      const windows = this.getAllPositions();
      try {
        localStorage.setItem(PREVIEW_CONFIG.STORAGE_KEY, JSON.stringify(windows));
        _pdbg('persist', 'saved to localStorage', { count: windows.length, bytes: JSON.stringify(windows).length });
      } catch (err) {
        _pdbg('persist', 'localStorage save FAILED', { error: String(err) });
      }
    }

    static removeWindow(id) {
      const win = this.windows.get(id);
      if (!win) return;
      _pdbg('sys', 'removeWindow', { id });
      if (this._isMirrorId(id)) {
        const sourceId = id.slice('mirror:'.length);
        this._detachMirrorSource(sourceId);
      }
      if (win.mirrorDetachedFrom) {
        this._detachedMirrorSources.delete(String(win.mirrorDetachedFrom));
        this._saveDetachedMirrors();
      }
      try { win.stopPreview(true); } catch (_) {}
      if (win.element) win.element.remove();
      this.windows.delete(id);
      this._persistWindows();
      try { this.syncMirrors(); } catch (_) {}
      if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
    }

    static _isMostlyBlackPreview(win) {
      if (!win || win.isVideo) return false;
      const url = (win.imageUrl || '').trim();
      if (url.startsWith('data:image') && url.length < 800) return true;
      return false;
    }

    static _checkAndRemoveBlackWin(id, img) {
      if (!this.windows.has(id)) return;
      try {
        const c = document.createElement('canvas');
        c.width = c.height = 12;
        const ctx = c.getContext('2d');
        if (!ctx) return;
        ctx.drawImage(img, 0, 0, 12, 12);
        const d = ctx.getImageData(0, 0, 12, 12).data;
        let sum = 0;
        for (let i = 0; i < d.length; i += 4) {
          sum += d[i] + d[i + 1] + d[i + 2];
        }
        const avg = sum / (d.length / 4) / 3;
        if (avg < 15) this.removeWindow(id);
      } catch (_) {}
    }

    /** Drop solid-black uploads (accidental blank/black image uploads). */
    static _purgeBlackUploadPreviews() {
      const toRemove = [];
      this.windows.forEach((win, id) => {
        if (this._isMirrorId(id)) return;
        if (this._isMostlyBlackPreview(win)) toRemove.push(id);
      });
      toRemove.forEach((id) => this.removeWindow(id));
      this.windows.forEach((win, id) => {
        if (this._isMirrorId(id)) return;
        const img = win.element?.querySelector('img.preview-media');
        if (!img) return;
        const run = () => this._checkAndRemoveBlackWin(id, img);
        if (img.complete && img.naturalWidth) run();
        else img.addEventListener('load', run, { once: true });
      });
    }

    static _isMirrorId(id) {
      return String(id || '').startsWith('mirror:');
    }

    static _mirrorIdFor(sourceId) {
      return `mirror:${sourceId}`;
    }

    static _isPlaceholderUrl(url) {
      if (!url || typeof url !== 'string') return true;
      const u = url.trim();
      if (!u || u.startsWith('data:image/svg+xml')) return true;
      return false;
    }

    static _windowWidth(win) {
      try {
        const r = win.element && win.element.getBoundingClientRect();
        if (r && r.width > 0) return r.width;
      } catch (_) {}
      return PREVIEW_CONFIG.DEFAULT_WIDTH || 150;
    }

    static _isRightSide(win) {
      const w = this._windowWidth(win);
      const cx = win.x + w / 2;
      return cx >= window.innerWidth / 2;
    }

    static _isLeftSide(win) {
      const w = this._windowWidth(win);
      const cx = win.x + w / 2;
      return cx < window.innerWidth / 2;
    }

    static _isOffScreen(win) {
      const pw = this._windowWidth(win);
      const ph = PREVIEW_CONFIG.DEFAULT_HEIGHT || 150;
      return win.x + pw < 4 || win.y + ph < 4
        || win.x > window.innerWidth - 4 || win.y > window.innerHeight - 4;
    }

    static _mirrorX(sourceX, width) {
      return window.innerWidth - sourceX - width;
    }

    static _nextWindowId() {
      let n = this.windows.size + 1;
      let id = `Preview ${n}`;
      while (this.windows.has(id)) {
        n += 1;
        id = `Preview ${n}`;
      }
      return id;
    }

    /** Linked left clone becomes an independent saved window after user edits it. */
    static promoteMirrorToStandalone(win) {
      if (!win || !win.isMirror) return win;
      const oldId = win.id;
      _pdbg('mirror', 'promoteMirrorToStandalone', { from: oldId });
      const sourceId = oldId.startsWith('mirror:') ? oldId.slice('mirror:'.length) : null;
      if (sourceId) {
        this._detachMirrorSource(sourceId);
        win.mirrorDetachedFrom = sourceId;
      }
      const newId = this._nextWindowId();
      win.id = newId;
      win.isMirror = false;
      if (win.element) {
        win.element.id = `preview-${newId}`;
        win.element.dataset.preview = newId;
      }
      this.windows.delete(oldId);
      this.windows.set(newId, win);
      return win;
    }

    static _constrainMirrorPosition(mx, my, pw) {
      const ph = PREVIEW_CONFIG.DEFAULT_HEIGHT || 150;
      const pad = 8;
      mx = this._clamp(mx, pad, Math.max(pad, window.innerWidth - pw - pad));
      my = this._clamp(my, pad, Math.max(pad, window.innerHeight - ph - pad));
      try {
        const sidebar = document.getElementById('sidebar');
        if (sidebar && !sidebar.classList.contains('collapsed') && this._isVisible(sidebar)) {
          const sr = sidebar.getBoundingClientRect();
          if (mx < sr.right && mx + pw > sr.left) {
            mx = Math.min(sr.right + pad, window.innerWidth - pw - pad);
          }
        }
      } catch (_) {}
      return { x: mx, y: my };
    }

    static _windowRect(win) {
      const pw = this._windowWidth(win);
      const ph = PREVIEW_CONFIG.DEFAULT_HEIGHT || 150;
      return { left: win.x, top: win.y, right: win.x + pw, bottom: win.y + ph };
    }

    /** True when a mirror at (mx,my) would cover a saved standalone preview. */
    static _overlapsStandaloneWindow(mx, my, pw, ph, excludeIds = []) {
      const mr = { left: mx, top: my, right: mx + pw, bottom: my + ph };
      for (const [id, win] of this.windows) {
        if (this._isMirrorId(id)) continue;
        if (excludeIds.includes(id)) continue;
        if (this._isPlaceholderUrl(win.imageUrl)) continue;
        if (this._rectsOverlap(mr, this._windowRect(win), 6)) return true;
      }
      return false;
    }

    /** One-time mirror placement — never auto-reorganize to a grid. */
    static _initialMirrorPosition(src, pw) {
      const ph = PREVIEW_CONFIG.DEFAULT_HEIGHT || 150;
      const pos = this._constrainMirrorPosition(this._mirrorX(src.x, pw), src.y, pw);
      if (this._overlapsStandaloneWindow(pos.x, pos.y, pw, ph, [src.id])) return null;
      return pos;
    }

    static _syncMirrorMedia(mirrorWin, src) {
      if (!mirrorWin || !src) return;
      if (mirrorWin.imageUrl === src.imageUrl && mirrorWin.isVideo === src.isVideo) return;
      mirrorWin.imageUrl = src.imageUrl;
      mirrorWin.isVideo = src.isVideo;
      mirrorWin.updateMedia();
      mirrorWin._syncMediaTypeClass();
    }

    /** Create/update left-side clones for right-half previews with real media. */
    static syncMirrors({ allowCreate = true } = {}) {
      const sources = [];
      this.windows.forEach((win, id) => {
        if (this._isMirrorId(id)) return;
        if (!this._isRightSide(win)) return;
        if (this._isPlaceholderUrl(win.imageUrl)) return;
        sources.push(win);
      });

      const needed = new Set(sources.map((s) => this._mirrorIdFor(s.id)));

      [...this.windows.keys()].forEach((id) => {
        if (!this._isMirrorId(id) || needed.has(id)) return;
        const win = this.windows.get(id);
        if (win?.element) win.element.remove();
        this.windows.delete(id);
      });

      let mirrorsCreated = 0;
      let mirrorsSynced = 0;
      for (const src of sources) {
        if (this._detachedMirrorSources.has(src.id)) continue;

        const mid = this._mirrorIdFor(src.id);
        const pw = this._windowWidth(src);

        let mirrorWin = this.windows.get(mid);
        if (mirrorWin) {
          if (mirrorWin.isDragging) continue;
          // Position is fixed after creation — only sync media from the source.
          this._syncMirrorMedia(mirrorWin, src);
          mirrorsSynced += 1;
          continue;
        }

        if (!allowCreate) continue;

        const pos = this._initialMirrorPosition(src, pw);
        if (!pos) continue;

        mirrorWin = new PreviewWindow(mid, src.imageUrl, src.isVideo, pos.x, pos.y);
        this.windows.set(mid, mirrorWin);
        mirrorsCreated += 1;
      }
      if (mirrorsCreated || mirrorsSynced) {
        _pdbg('mirror', 'syncMirrors', { created: mirrorsCreated, synced: mirrorsSynced, sources: sources.length });
      }
      if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
    }

    static _rectsOverlap(a, b, pad = 1) {
      return !(a.right <= b.left + pad || a.left >= b.right - pad ||
               a.bottom <= b.top + pad || a.top >= b.bottom - pad);
    }

    static _isVisible(el) {
      if (!el) return false;
      let node = el;
      while (node && node !== document.body) {
        const st = window.getComputedStyle(node);
        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) {
          return false;
        }
        node = node.parentElement;
      }
      const r = el.getBoundingClientRect();
      return r.width > 2 && r.height > 2;
    }

    static _addObstructorRect(rects, el) {
      if (!this._isVisible(el)) return;
      const r = el.getBoundingClientRect();
      if (r.width > 2 && r.height > 2) rects.push(r);
    }

    static _getObstructorRects() {
      const rects = [];

      // Only occlude for overlays/modals that should *always* be on top.
      // Do NOT occlude for normal page cards like the prompt form — that was
      // making previews "disappear" when dragged too close.

      const sidebar = document.getElementById('sidebar');
      if (sidebar && !sidebar.classList.contains('collapsed')) {
        this._addObstructorRect(rects, sidebar);
      }

      const advOverlay = document.getElementById('adv-overlay');
      if (advOverlay?.classList.contains('open')) {
        this._addObstructorRect(rects, document.getElementById('adv-modal'));
      }

      const createOverlay = document.getElementById('adv-create-overlay');
      if (createOverlay?.classList.contains('open')) {
        this._addObstructorRect(rects, document.getElementById('adv-create-dialog'));
      }

      const hairModal = document.getElementById('st-hair-modal');
      if (hairModal && window.getComputedStyle(hairModal).display !== 'none') {
        this._addObstructorRect(rects, document.getElementById('st-hair-modal-box'));
      }

      const facialModal = document.getElementById('st-facial-modal');
      if (facialModal && window.getComputedStyle(facialModal).display !== 'none') {
        this._addObstructorRect(rects, document.getElementById('st-facial-modal-box'));
      }

      return rects;
    }

    static _getForbiddenDragRects() {
      // Areas previews are not allowed to overlap while dragging.
      // Currently: the main prompt card (#form-section).
      const rects = [];
      try {
        const form = document.getElementById('form-section');
        if (this._isVisible(form)) rects.push(form.getBoundingClientRect());
      } catch (_) {}
      return rects;
    }

    static _clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }

    static constrainPreviewPosition(x, y, el) {
      const pad = 8;
      const w = (el && el.getBoundingClientRect ? el.getBoundingClientRect().width : (PREVIEW_CONFIG.DEFAULT_WIDTH || 150)) || (PREVIEW_CONFIG.DEFAULT_WIDTH || 150);
      const h = (el && el.getBoundingClientRect ? el.getBoundingClientRect().height : (PREVIEW_CONFIG.DEFAULT_HEIGHT || 150)) || (PREVIEW_CONFIG.DEFAULT_HEIGHT || 150);

      let nx = x;
      let ny = y;
      // Keep within viewport
      nx = this._clamp(nx, pad, Math.max(pad, window.innerWidth - w - pad));
      ny = this._clamp(ny, pad, Math.max(pad, window.innerHeight - h - pad));

      // Avoid forbidden drag rects (prompt card)
      const rSelf = () => ({ left: nx, top: ny, right: nx + w, bottom: ny + h });
      const overlaps = (a, b) => !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);

      for (const fr of this._getForbiddenDragRects()) {
        let rs = rSelf();
        if (!overlaps(rs, fr)) continue;

        // Push out with minimal displacement.
        const pushLeft   = (fr.left - w - pad) - nx;
        const pushRight  = (fr.right + pad) - nx;
        const pushUp     = (fr.top - h - pad) - ny;
        const pushDown   = (fr.bottom + pad) - ny;

        const options = [
          { dx: pushLeft,  dy: 0,  cost: Math.abs(pushLeft)  },
          { dx: pushRight, dy: 0,  cost: Math.abs(pushRight) },
          { dx: 0, dy: pushUp,     cost: Math.abs(pushUp)    },
          { dx: 0, dy: pushDown,   cost: Math.abs(pushDown)  },
        ].sort((a, b) => a.cost - b.cost);

        for (const opt of options) {
          const tx = this._clamp(nx + opt.dx, pad, Math.max(pad, window.innerWidth - w - pad));
          const ty = this._clamp(ny + opt.dy, pad, Math.max(pad, window.innerHeight - h - pad));
          const test = { left: tx, top: ty, right: tx + w, bottom: ty + h };
          if (!overlaps(test, fr)) {
            nx = tx; ny = ty;
            break;
          }
        }
      }

      return { x: nx, y: ny };
    }

    static updateOcclusion() {
      const obstructors = this._getObstructorRects();
      const changed = [];
      this.windows.forEach(win => {
        const el = win.element;
        if (!el) return;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return;
        const occluded = obstructors.some(o => this._rectsOverlap(r, o));
        const wasOccluded = el.classList.contains('occluded');
        // Never hide/stop the window the user is actively hovering — avoids abrupt pause mid-playback.
        if (occluded && _hoveredPreviewWin === win) {
          if (wasOccluded) {
            el.classList.remove('occluded');
            changed.push({ id: win.id, occluded: false, reason: 'hover-active' });
          }
          return;
        }
        if (occluded) {
          if (!wasOccluded) {
            el.classList.add('occluded');
            changed.push({ id: win.id, occluded: true });
            win.stopPreview();
          }
        } else if (wasOccluded) {
          el.classList.remove('occluded');
          changed.push({ id: win.id, occluded: false });
          if (_hoveredPreviewWin === win && win.isVideo) {
            win.playPreview();
            if (_previewSessionGesture) _startPreviewAudioKeepAlive();
          }
        }
      });
      if (changed.length) _pdbg('occlude', 'occlusion update', changed);
    }

    static _bindOcclusionWatchers() {
      window.addEventListener('resize', () => {
        window._schedulePreviewOcclusion();
      }, { passive: true });
      window.addEventListener('scroll', () => window._schedulePreviewOcclusion(), { passive: true });

      const watchIds = ['storyteller-wizard', 'form-section', 'progress-card', 'result-card', 'queue-card', 'adv-overlay', 'adv-create-overlay', 'sidebar', 'st-hair-modal', 'st-facial-modal'];
      const mo = new MutationObserver(() => window._schedulePreviewOcclusion());
      watchIds.forEach(id => {
        const node = document.getElementById(id);
        if (node) mo.observe(node, { attributes: true, attributeFilter: ['style', 'class'] });
      });

      document.querySelectorAll('.main-content > .form-card, .main-content > .card, #storyteller-wizard > .form-card').forEach(node => {
        mo.observe(node, { attributes: true, attributeFilter: ['style', 'class'] });
      });
    }

    static init() {
      _pdbg('sys', 'PreviewWindowManager.init');
      const container = document.createElement('div');
      container.id = 'preview-container';
      document.body.insertBefore(container, document.body.firstChild);
      this._loadDetachedMirrors();
      this.loadPositions();
      this._reconcileDetachedMirrors();
      this._purgeBlackUploadPreviews();
      this._bindOcclusionWatchers();
      window._schedulePreviewOcclusion();
      // Only nudge windows that fell off-screen — never reorganize left-side saved previews.
      try {
        this.windows.forEach(win => {
          if (!win?.element || win.isEnlarged || win.isMirror) return;
          if (this._isLeftSide(win) && !this._isOffScreen(win)) return;
          if (!this._isOffScreen(win)) return;
          const c = this.constrainPreviewPosition(win.x, win.y, win.element);
          win.x = c.x; win.y = c.y;
          win.applyPosition();
        });
      } catch (_) {}
      try { this.syncMirrors(); } catch (_) {}
      setTimeout(() => this._primeMediaEngagement(), 1200);
      _pdbg('sys', 'init complete', PreviewDebug.snapshot());
    }

    /** Quiet muted play once per clip — raises browser media-engagement score for hover audio. */
    static _primeMediaEngagement() {
      const seen = new Set();
      this.windows.forEach((win) => {
        if (!win.isVideo || !win._hasRealMedia()) return;
        const httpUrl = _previewPlayableVideoSrc(win.imageUrl);
        if (!httpUrl || seen.has(httpUrl)) return;
        seen.add(httpUrl);
        _previewPersistGetBlobUrl(httpUrl).then(() => {
          const v = win.element?.querySelector('video');
          if (!v || !v.src) return;
          v.muted = true;
          v.setAttribute('muted', '');
          const done = () => {
            try {
              v.pause();
              v.currentTime = 0;
            } catch (_) {}
          };
          v.play().then(done).catch(() => {});
        });
      });
    }

    static create(id, imageUrl, isVideo = false, x = null, y = null) {
      if (this.windows.has(id)) return;
      const win = new PreviewWindow(id, imageUrl, isVideo, x, y);
      this.windows.set(id, win);
      if (window._schedulePreviewOcclusion) window._schedulePreviewOcclusion();
      return win;
    }

    static createEmpty(id, x = null, y = null) {
      this.create(id, 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"%3E%3Crect fill="%23262d3a" width="200" height="200"/%3E%3C/svg%3E', false, x, y);
    }

    static getAllPositions() {
      const positions = [];
      this.windows.forEach(win => positions.push(win.getState()));
      return positions;
    }

    static loadPositions() {
      const saved = localStorage.getItem(PREVIEW_CONFIG.STORAGE_KEY);
      if (saved) {
        try {
          const positions = JSON.parse(saved);
          _pdbg('persist', 'loadPositions', { count: positions.length });
          positions.forEach(pos => {
            this.create(pos.id, pos.imageUrl, pos.isVideo, pos.x, pos.y);
            const win = this.windows.get(pos.id);
            if (pos.mirrorDetachedFrom && win) {
              this._detachMirrorSource(pos.mirrorDetachedFrom);
              win.mirrorDetachedFrom = pos.mirrorDetachedFrom;
            }
          });
        } catch (e) {
          console.error('Failed to load preview positions:', e);
          this.createDefaultWindows();
        }
      } else {
        this.createDefaultWindows();
      }
    }

    static createDefaultWindows() {
      const defaultPositions = [
        [100, 100], [350, 100], [600, 100], [850, 100],
        [100, 350], [350, 350], [600, 350], [850, 350]
      ];
      
      for (let i = 0; i < 8; i++) {
        const [x, y] = defaultPositions[i];
        this.createEmpty(`Preview ${i + 1}`, x, y);
      }
    }

    static toggleUploadButtons() {
      const buttons = document.querySelectorAll('.preview-upload-btn');
      buttons.forEach(btn => {
        btn.style.display = btn.style.display === 'none' ? 'flex' : 'none';
      });
    }

    static createNewWindow() {
      const id = `Preview ${this.windows.size + 1}`;
      const pw = PREVIEW_CONFIG.DEFAULT_WIDTH || 150;
      const ph = PREVIEW_CONFIG.DEFAULT_HEIGHT || 150;

      // Try a few random placements that don't overlap the prompt card.
      let x = Math.random() * Math.max(0, window.innerWidth - pw);
      let y = Math.random() * Math.max(0, window.innerHeight - ph);
      for (let i = 0; i < 10; i++) {
        const x0 = x, y0 = y;
        const c = this.constrainPreviewPosition(x0, y0, { getBoundingClientRect: () => ({ width: pw, height: ph }) });
        // If constrained didn't have to move us much, accept.
        if (Math.abs(c.x - x0) < 2 && Math.abs(c.y - y0) < 2) { x = c.x; y = c.y; break; }
        // Otherwise sample a new random point and retry.
        x = Math.random() * Math.max(0, window.innerWidth - pw);
        y = Math.random() * Math.max(0, window.innerHeight - ph);
      }
      this.createEmpty(id, x, y);
      return this.windows.get(id);
    }
  }

  // Keyboard shortcut handler for Ctrl+1,2,3
  let ctrlSequence = [];
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && (e.key === '1' || e.key === '2' || e.key === '3')) {
      e.preventDefault();
      ctrlSequence.push(e.key);
      
      // Check if sequence is Ctrl+1,2,3
      if (ctrlSequence.length >= 3) {
        const lastThree = ctrlSequence.slice(-3).join('');
        if (lastThree === '123') {
          PreviewWindowManager.toggleUploadButtons();
          ctrlSequence = [];
        } else if (!['1', '2', '3'].includes(ctrlSequence[ctrlSequence.length - 1])) {
          ctrlSequence = [];
        }
      }
    }
  });

/* 2026-07-17 modularization: ModalDebug system removed (tracked only the deleted recruitment modals) — original in crews_modularization_backups_20260717 */
