// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ════════════════════════════════════════════════════════════════════════════
   Zero Cinema — board + player
   ────────────────────────────────────────────────────────────────────────────
   Two playback modes:

   direct     The file is byte-for-byte browser-playable. <video src> points at
              it and the browser's own Range requests do the seeking.

   transcode  ffmpeg re-encodes on the fly. There is no byte offset to ask for,
              so a SEEK IS A NEW REQUEST: the client keeps its own time origin
              (S.offset) and the element's currentTime counts from there.
              The server is asked where it will really land first — on the
              stream-copy path ffmpeg can only start at a keyframe, which is up
              to ~5 s from the requested time, and subtitles must be rebased by
              that true offset or the whole track drifts.

   Transcoded titles are delivered as HLS through hls.js, NOT as one long
   <video src> response. The reason is the buffer: measured 2026-09-04, Chrome
   reading from loopback off NVMe with the encoder running 19x realtime held a
   flat 2.3-2.4 s ahead of the playhead and refused to fetch more — on the
   direct path and the progressive transcode alike. That window is the media
   element's, and no amount of server speed widens it. Under MSE the buffer is
   OURS, so hls.js is told to keep ~60 s. Same time-origin model either way:
   the HLS session starts at S.offset and currentTime counts from there, which
   is why seeking, subtitle shifting and now() are untouched by this.

   The progressive path is kept as the fallback for when a session cannot be
   opened (no scratch disk, no MSE), so nothing here is a single point of
   failure.
   ════════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var video   = $('player');
  var stage   = $('stage');
  var railEl  = $('rail-body');
  var ctx     = $('ctxmenu');

  var S = {
    view: 'movies',
    board: { movies: [], series: [], roots: [], count: 0 },
    show: null,
    range: null,          // active 100-episode bucket (its start), null = first
    epView: 'auto',       // 'auto' | 'grid' | 'cards'
    filter: '',
    item: null,
    mode: 'direct',
    offset: 0,
    duration: 0,
    subId: '',
    audioId: 0,
    burn: '',
    dragging: false,
    seekToken: 0,
    hideTimer: null,
    scanTimer: null,
    pickPath: '',
    railBeforeFull: true,
    queue: [],
    qIndex: -1,
    mountGen: 0,
    errRetries: 0,
    errRetryTimer: null,
    hls: null,            // live Hls.js instance, or null on the fallback path
    hlsSession: '',       // server-side session id to release when we are done
    marks: {},            // {intro:{start,end}, outro:{start}, auto_skip_outro}
    prefs: {},            // effective prefs for the open title
    showKey: '',
    introDone: false,     // the skip button has had its ten seconds
    outroFired: false     // the ending has already been skipped for this item
  };

  /* ── helpers ───────────────────────────────────────────────────────────── */
  function fmt(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    sec = Math.floor(sec);
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    var mm = (h && m < 10) ? '0' + m : String(m);
    return (h ? h + ':' : '') + mm + ':' + (s < 10 ? '0' + s : s);
  }
  function fmtLong(sec) {
    if (!isFinite(sec) || sec <= 0) return '';
    var h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    if (m === 60) { h += 1; m = 0; }
    return h ? h + 'h ' + m + 'm' : m + 'm';
  }
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var toastTimer;
  function toast(msg, kind) {
    var el = $('toast');
    el.textContent = msg;
    el.className = 'toast show' + (kind ? ' ' + kind : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.className = 'toast'; }, kind === 'err' ? 5200 : 3000);
  }

  function api(url, opts) {
    return fetch(url, opts || {}).then(function (r) {
      if (r.status === 403) { window.location.href = '/'; throw new Error('locked'); }
      return r.json().catch(function () { return { success: false, error: 'Bad response' }; });
    });
  }

  function swapIcon(btnId, showSel, hideSel) {
    // SVGElement does not implement the `hidden` IDL attribute — `el.hidden = true`
    // just sets a JS expando and never touches the DOM (verified: 'hidden' in svg
    // === false). The content attribute has to be set explicitly.
    var b = $(btnId);
    if (!b) return;
    var show = b.querySelector(showSel), hide = b.querySelector(hideSel);
    if (show) show.removeAttribute('hidden');
    if (hide) hide.setAttribute('hidden', '');
  }

  /* ── resume positions ──────────────────────────────────────────────────── */
  function posKey(id) { return 'cine:pos:' + id; }
  function getPos(id) {
    try { return parseFloat(localStorage.getItem(posKey(id))) || 0; } catch (e) { return 0; }
  }
  function setPos(id, t) {
    try {
      if (t > 25 && S.duration && t < S.duration - 45) localStorage.setItem(posKey(id), String(Math.floor(t)));
      else localStorage.removeItem(posKey(id));
    } catch (e) { /* private mode */ }
  }

  /* ══ Board ═══════════════════════════════════════════════════════════════ */
  function loadBoard(keepSelection) {
    return api('/api/cinema/board').then(function (d) {
      if (!d.success) { toast(d.error || 'Could not load the library', 'err'); return; }
      S.board = d;
      $('dd-count-movies').textContent = d.movies.length || '';
      $('dd-count-series').textContent = d.series.length || '';
      if (!keepSelection && S.view === 'episodes') {
        var still = d.series.filter(function (x) { return x.title === (S.show || {}).title; })[0];
        if (still) S.show = still; else { S.view = 'series'; S.show = null; }
      }
      renderRail();
    });
  }

  function matches(text) {
    if (!S.filter) return true;
    return String(text || '').toLowerCase().indexOf(S.filter) !== -1;
  }

  var FILM_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M3.2 7.2h17.6v11.6H3.2z"/><path d="M3.2 7.2 6 3.4M9.6 7.2 12.4 3.4M16 7.2l2.8-3.8"/></svg>';

  function cardHTML(c, opts) {
    opts = opts || {};
    // Classify on WIDTH, not height: scope-ratio releases are 1920x800-ish, so a
    // height test labelled Deadpool "802P" instead of HD.
    var res = c.width >= 3000 ? '4K' : (c.width >= 1900 ? 'HD'
            : (c.width >= 1200 ? '720p' : (c.width ? 'SD' : '')));
    var chips = '';
    if (res) chips += '<span class="chip hd">' + res + '</span>';
    if (c.subs) chips += '<span class="chip cc">CC</span>';

    var pos = getPos(c.id);
    var pct = (pos && c.duration) ? clamp((pos / c.duration) * 100, 0, 100) : 0;

    var meta = [];
    if (opts.episodeLabel) meta.push('<b>' + esc(opts.episodeLabel) + '</b>');
    else if (c.year) meta.push('<b>' + c.year + '</b>');
    if (c.duration) meta.push(fmtLong(c.duration));
    if (opts.extra) meta.push(esc(opts.extra));

    return '' +
      '<div class="card-thumb">' +
        '<div class="thumb-fallback">' + FILM_SVG + '</div>' +
        '<img loading="lazy" alt="" src="/api/cinema/thumb/' + encodeURIComponent(opts.thumbId || c.id) + '.jpg"' +
          ' onload="this.classList.add(\'ready\')" onerror="this.remove()">' +
        '<div class="card-badges">' + chips + '</div>' +
        (c.duration ? '<div class="card-dur">' + fmt(c.duration) + '</div>' : '') +
        (pct ? '<div class="card-resume"><i style="width:' + pct.toFixed(1) + '%"></i></div>' : '') +
      '</div>' +
      '<div class="card-name">' +
        '<div class="card-title">' + esc(opts.name || c.title) +
          (c.version ? ' <span class="card-ver">' + esc(c.version) + '</span>' : '') + '</div>' +
        (meta.length ? '<div class="card-meta">' + meta.join('<span>·</span>') + '</div>' : '') +
      '</div>';
  }

  function emptyHTML(title, body) {
    return '<div class="rail-empty">' + FILM_SVG + '<b>' + esc(title) + '</b>' + esc(body) + '</div>';
  }

  var GRID_SVG  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="3.5" width="7" height="7" rx="1.4"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.4"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.4"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.4"/></svg>';
  var CARDS_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="6" rx="1.4"/><rect x="3.5" y="13.5" width="17" height="6" rx="1.4"/></svg>';

  /* ── Episodes ──────────────────────────────────────────────────────────── */
  function flatEpisodes(show) {
    var out = [];
    (show.seasons || []).forEach(function (s) {
      s.episodes.forEach(function (e) {
        // Season lives on the parent, but the grid renders one flat run, so
        // every episode has to carry its own season for the S..E.. tag.
        out.push(Object.assign({ season: s.season }, e));
      });
    });
    return out.sort(function (a, b) { return (a.abs || 0) - (b.abs || 0); });
  }

  function epTag(e) {
    return 'S' + String(e.season || 1).padStart(2, '0') +
           'E' + String(e.episode || 0).padStart(2, '0');
  }

  function epMatches(e) {
    if (!S.filter) return true;
    return matches(e.episode_title) || matches(S.show.title) ||
           matches('s' + e.season + 'e' + e.episode) ||
           matches(String(e.abs || '')) || matches(String(e.episode || ''));
  }

  function bucketOf(n) { return Math.floor(Math.max(0, n - 1) / 100) * 100 + 1; }

  function gridHTML(eps, ranges) {
    // Buckets come from the FULL show, but the filter may empty some of them —
    // chip counts have to follow what is actually on screen or they lie.
    var live = {};
    eps.forEach(function (e) {
      var b = bucketOf(e.abs || 0);
      (live[b] = live[b] || []).push(e);
    });
    var starts = Object.keys(live).map(Number).sort(function (a, b) { return a - b; });
    if (!starts.length) return emptyHTML('No match', 'No episodes match "' + S.filter + '".');

    var active = starts.indexOf(S.range) !== -1 ? S.range : starts[0];
    var html = '';

    if (starts.length > 1) {
      html += '<div class="ep-ranges">';
      starts.forEach(function (start) {
        var end = start + 99;
        html += '<button type="button" class="ep-range' + (start === active ? ' on' : '') +
                '" data-range="' + start + '">' + start + '–' + end +
                '<i>' + live[start].length + '</i></button>';
      });
      html += '</div>';
    }

    html += '<div class="ep-grid">';
    live[active].forEach(function (e) {
      var pos = getPos(e.id);
      var pct = (pos && e.duration) ? clamp((pos / e.duration) * 100, 0, 100) : 0;
      var label = e.episode_title ? e.episode_title + ' — ' + epTag(e) : epTag(e);
      html += '<button type="button" class="ep-sq' + (pct ? ' seen' : '') +
              '" data-id="' + e.id + '" title="' + esc(label) + '">' +
              (e.abs || e.episode || 0) +
              (pct ? '<i style="width:' + pct.toFixed(1) + '%"></i>' : '') +
              '</button>';
    });
    html += '</div>';
    return html;
  }

  function renderRail() {
    var html = '';
    var crumb = $('rail-crumb');
    $('crumb-rename').hidden = true;

    if (S.view === 'movies') {
      crumb.hidden = true;
      var list = S.board.movies.filter(function (m) {
        return matches(m.title) || matches(m.year);
      });
      if (!list.length) {
        html = S.board.movies.length
          ? emptyHTML('No match', 'Nothing here matches "' + S.filter + '".')
          : emptyHTML('No movies yet', 'Use Upload (top right) to scan a folder.');
      } else {
        list.forEach(function (m) {
          html += '<div class="card" role="button" tabindex="0" data-id="' + m.id + '">' +
                  cardHTML(m) + '</div>';
        });
      }
      $('rail-foot').innerHTML = '<span>' + list.length + ' movie' + (list.length === 1 ? '' : 's') +
        '</span><span>' + (S.board.count || 0) + ' in library</span>';

    } else if (S.view === 'series') {
      crumb.hidden = true;
      var shows = S.board.series.filter(function (s) { return matches(s.title); });
      if (!shows.length) {
        html = S.board.series.length
          ? emptyHTML('No match', 'Nothing here matches "' + S.filter + '".')
          : emptyHTML('No series yet', 'Episodes named like S01E02 are grouped here automatically.');
      } else {
        shows.forEach(function (s, i) {
          var seasons = s.seasons.length;
          html += '<div class="card" role="button" tabindex="0" data-show="' + i + '">' +
            cardHTML({ id: s.poster, title: s.title, duration: 0, height: 0, subs: 0, direct: true },
                     { thumbId: s.poster, name: s.title,
                       extra: seasons + ' season' + (seasons === 1 ? '' : 's') + ' · ' +
                              s.episodes + ' episode' + (s.episodes === 1 ? '' : 's') }) +
            '</div>';
        });
      }
      $('rail-foot').innerHTML = '<span>' + shows.length + ' series</span><span>' +
        (S.board.count || 0) + ' in library</span>';

    } else {
      crumb.hidden = false;
      $('crumb-text').textContent = S.show.title;
      $('crumb-rename').hidden = false;
      var ranges = S.show.ranges || [];
      var grid = (S.epView === 'grid') || (S.epView === 'auto' && ranges.length > 1);
      var viewBtn = $('crumb-view');
      viewBtn.hidden = false;
      viewBtn.innerHTML = grid ? CARDS_SVG : GRID_SVG;
      viewBtn.title = grid ? 'Show episode cards' : 'Show numbered grid';

      var eps = flatEpisodes(S.show).filter(epMatches);
      var total = eps.length;

      if (!total) {
        html = emptyHTML('No match', 'No episodes match "' + S.filter + '".');
      } else if (grid) {
        html = gridHTML(eps, ranges);
      } else {
        var season = null;
        eps.forEach(function (e) {
          if (e.season !== season) {
            season = e.season;
            html += '<div class="season-head">Season ' + season + '</div>';
          }
          html += '<div class="card" role="button" tabindex="0" data-id="' + e.id + '">' +
                  cardHTML(e, { name: e.episode_title || epTag(e), episodeLabel: epTag(e) }) +
                  '</div>';
        });
      }
      $('rail-foot').innerHTML = '<span>' + total + ' episode' + (total === 1 ? '' : 's') +
        '</span><span>' + esc(S.show.title) + '</span>';
    }

    railEl.innerHTML = html;
    markPlaying();
  }

  function markPlaying() {
    Array.prototype.forEach.call(railEl.querySelectorAll('.card, .ep-sq'), function (c) {
      c.classList.toggle('playing', !!S.item && c.dataset.id === S.item.id);
    });
  }

  railEl.addEventListener('click', function (e) {
    var range = e.target.closest('.ep-range');
    if (range) {
      S.range = parseInt(range.dataset.range, 10);
      renderRail();
      // Only the grid scrolls back; the chip row is sticky and stays put.
      var g = railEl.querySelector('.ep-grid');
      if (g) g.scrollIntoView({ block: 'nearest' });
      return;
    }
    var sq = e.target.closest('.ep-sq');
    if (sq) { enterFullscreen(); openItem(sq.dataset.id); return; }

    var card = e.target.closest('.card');
    if (!card) return;
    if (card.dataset.show !== undefined) {
      S.show = S.board.series[parseInt(card.dataset.show, 10)];
      S.view = 'episodes';
      S.range = null;
      $('rail-filter').value = '';
      S.filter = '';
      renderRail();
      railEl.scrollTop = 0;
    } else if (card.dataset.id) {
      enterFullscreen();
      openItem(card.dataset.id);
    }
  });
  railEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') {
      var card = e.target.closest('.card');
      if (card) { e.preventDefault(); card.click(); }
    }
  });

  $('crumb-back').addEventListener('click', function () {
    S.view = 'series'; S.show = null; S.range = null;
    $('crumb-view').hidden = true;
    renderRail();
  });

  $('crumb-view').addEventListener('click', function () {
    var ranges = (S.show && S.show.ranges) || [];
    var grid = (S.epView === 'grid') || (S.epView === 'auto' && ranges.length > 1);
    S.epView = grid ? 'cards' : 'grid';
    renderRail();
    railEl.scrollTop = 0;
  });

  $('rail-filter').addEventListener('input', function () {
    S.filter = this.value.trim().toLowerCase();
    renderRail();
  });

  /* ── view dropdown ─────────────────────────────────────────────────────── */
  var dd = $('dd-view');
  $('dd-btn').addEventListener('click', function (e) {
    e.stopPropagation();
    dd.classList.toggle('open');
    $('dd-btn').setAttribute('aria-expanded', dd.classList.contains('open'));
    syncDd();
  });
  document.addEventListener('click', function () {
    dd.classList.remove('open');
    $('dd-btn').setAttribute('aria-expanded', 'false');
  });
  function syncDd() {
    Array.prototype.forEach.call($('dd-menu').querySelectorAll('.dd-item'), function (b) {
      var want = (S.view === 'episodes') ? 'series' : S.view;
      b.classList.toggle('active', b.dataset.view === want);
    });
  }
  $('dd-menu').addEventListener('click', function (e) {
    var b = e.target.closest('.dd-item');
    if (!b) return;
    S.view = b.dataset.view;
    S.show = null;
    S.range = null;
    $('crumb-view').hidden = true;
    $('dd-label').textContent = S.view === 'movies' ? 'Movies' : 'Series';
    $('rail-filter').value = ''; S.filter = '';
    renderRail();
    railEl.scrollTop = 0;
    document.body.classList.add('rail-open');
  });

  /* ══ Player ══════════════════════════════════════════════════════════════ */
  function now() {
    return S.mode === 'direct' ? video.currentTime : S.offset + video.currentTime;
  }

  function transcodeUrl(t) {
    return '/api/cinema/transcode/' + encodeURIComponent(S.item.id) +
           '?t=' + t.toFixed(3) +
           '&a=' + S.audioId +
           (S.burn ? '&burn=' + encodeURIComponent(S.burn) : '') +
           '&_=' + Date.now();
  }

  function spinner(on, label) {
    $('stage-spinner').hidden = !on;
    if (on) $('spin-label').textContent = label || 'Loading…';
  }
  function showError(msg) {
    var el = $('stage-error');
    el.hidden = !msg;
    el.textContent = msg || '';
    if (msg) spinner(false);
  }

  function openItem(id) {
    spinner(true, 'Opening…');
    showError('');
    api('/api/cinema/item/' + encodeURIComponent(id)).then(function (d) {
      if (!d.success) { showError(d.error || 'Could not open this title.'); return; }
      S.item = d.item;
      S.duration = d.item.duration || 0;
      // The server ranks the tracks (Japanese audio, full-dialogue subtitles by
      // default) — the client just obeys, so one rule covers every series.
      S.audioId = d.item.default_audio || 0;
      S.burn = '';
      S.subId = d.item.default_sub || '';
      S.marks = d.item.marks || {};
      S.prefs = d.item.prefs || {};
      S.showKey = d.item.show_key || '';
      S.errRetries = 0;
      clearTimeout(S.errRetryTimer);
      // A burn-in default cannot be applied without forcing a re-encode; keep
      // it selected but let mount() route it.
      buildQueue(id);
      var resume = getPos(id);
      mount(resume > 20 ? resume : 0);
      if (resume > 20) toast('Resuming at ' + fmt(resume));
    });
  }

  function buildQueue(id) {
    S.queue = [];
    if (S.view === 'episodes' && S.show) {
      flatEpisodes(S.show).forEach(function (e) { S.queue.push(e.id); });
    } else if (S.view === 'movies') {
      S.queue = S.board.movies.map(function (m) { return m.id; });
    }
    S.qIndex = S.queue.indexOf(id);
  }

  function mount(startAt) {
    var it = S.item;
    if (!it) return;
    S.mountGen += 1;
    // Direct play never reaches startTranscodeAt, so a session left over from
    // the previous title would otherwise idle out holding an ffmpeg process.
    releaseHls(false);
    stage.classList.remove('no-media');
    // A fresh open should read as just the movie, not the browse UI's leftover
    // show-ui state — force the bar closed rather than waiting on the idle timer.
    stage.classList.remove('show-ui');
    $('topbar').classList.remove('show');
    clearTimeout(S.hideTimer);
    $('stage-idle').hidden = true;
    showError('');
    $('ctl-title').textContent = titleOf(it);
    $('t-dur').textContent = fmt(S.duration);
    document.title = titleOf(it) + ' — Cinema';

    var sub = subById(S.subId);
    var wantsBurn = sub && !sub.text;
    S.burn = wantsBurn ? S.subId : '';

    // A direct file exposes only its FIRST audio track to the browser
    // (HTMLMediaElement.audioTracks is unimplemented in Chrome), so any other
    // track — including a Japanese default that isn't track 1 — means ffmpeg.
    var canDirect = it.direct && !wantsBurn && !S.audioId;
    S.mode = canDirect ? 'direct' : 'transcode';
    resetSkips(startAt || 0);

    var badge = $('badge-mode');
    if (S.mode === 'transcode') {
      badge.hidden = false;
      badge.textContent = wantsBurn ? 'burning subtitles'
        : (S.audioId && it.direct ? 'switching audio'
           : (it.transcode_reason === 'audio' ? 'live audio' : 'live transcode'));
      badge.title = 'This file is not natively playable in a browser — it is being converted as it plays.';
    } else { badge.hidden = true; }

    spinner(true, S.mode === 'transcode' ? 'Preparing stream…' : 'Loading…');

    if (S.mode === 'direct') {
      S.offset = 0;
      video.src = '/api/cinema/play/' + encodeURIComponent(it.id);
      video.load();
      var applyStart = function () {
        video.removeEventListener('loadedmetadata', applyStart);
        if (startAt > 0) video.currentTime = startAt;
        applySubtitle(S.subId);
        video.play().catch(function () { /* autoplay policy */ });
      };
      video.addEventListener('loadedmetadata', applyStart);
    } else {
      startTranscodeAt(startAt || 0, true);
    }
    markPlaying();
  }

  function titleOf(it) {
    if (it.kind === 'episode') {
      var tag = 'S' + String(it.season || 1).padStart(2, '0') +
                'E' + String(it.episode || 0).padStart(2, '0');
      return (it.series || it.title) + ' · ' + tag +
             (it.episode_title ? ' — ' + it.episode_title : '');
    }
    return it.title + (it.version ? ' ' + it.version : '') +
           (it.year ? ' (' + it.year + ')' : '');
  }

  function subById(id) {
    if (!id || !S.item) return null;
    return (S.item.subs || []).filter(function (s) { return s.id === id; })[0] || null;
  }

  /* ── HLS session lifecycle ─────────────────────────────────────────────── */
  function hlsSupported() {
    return typeof Hls !== 'undefined' && Hls.isSupported();
  }

  /* Tear down the current session. `beacon` is for pagehide, where a normal
     fetch is cancelled before it leaves — without it the server would hold the
     ffmpeg process until its idle timeout instead of freeing it now. */
  function releaseHls(beacon) {
    if (S.hls) {
      try { S.hls.destroy(); } catch (e) { /* already gone */ }
      S.hls = null;
    }
    var id = S.hlsSession;
    S.hlsSession = '';
    if (!id) return;
    var url = '/api/cinema/hls/' + encodeURIComponent(id) + '/close';
    if (beacon && navigator.sendBeacon) { navigator.sendBeacon(url); return; }
    fetch(url, { method: 'POST', credentials: 'same-origin' })
      .catch(function () { /* the idle reaper is the backstop */ });
  }

  function attachHls(sessionId, wasPlaying, token) {
    var src = '/api/cinema/hls/' + encodeURIComponent(sessionId) + '/index.m3u8';
    // Buffer targets: 60 s is ~25x what a bare <video src> would hold, and at
    // the ~5.4 Mbps these transcodes measure it lands near 40 MB — inside
    // Chrome's per-SourceBuffer budget, so it never trips a quota eviction.
    // The server lets ffmpeg run 180 s ahead of the furthest segment fetched,
    // which keeps the encoder comfortably in front of this without letting it
    // race away and write the whole film to the library's own volume.
    S.hls = new Hls({
      maxBufferLength: 60,
      maxMaxBufferLength: 180,
      maxBufferSize: 120 * 1000 * 1000,
      backBufferLength: 30,
      startFragPrefetch: true,
      lowLatencyMode: false,
      // startPosition 0 is NOT a default worth losing. The playlist is an EVENT
      // playlist (it grows, so it cannot be VOD), and hls.js reads a growing
      // playlist as live: its default start is liveSyncDurationCount segments
      // back from the END. Measured before this line existed — a session opened
      // at t=300 with 198 s already encoded began playing at 180 s into the
      // stream, i.e. 480 s into the film. The session's first segment IS the
      // requested time, so the start position is always zero.
      startPosition: 0,
      xhrSetup: function (xhr) { xhr.withCredentials = true; }
    });
    S.hlsSession = sessionId;
    S.hls.on(Hls.Events.ERROR, function (_e, data) {
      if (!data || !data.fatal || token !== S.seekToken) return;
      // A reaped session answers 410; anything else fatal gets the same
      // treatment the media element's own error handler applies.
      onPlaybackError(data.type === Hls.ErrorTypes.NETWORK_ERROR);
    });
    S.hls.on(Hls.Events.MANIFEST_PARSED, function () {
      if (token !== S.seekToken) return;
      if (wasPlaying) video.play().catch(function () {});
    });
    S.hls.loadSource(src);
    S.hls.attachMedia(video);
  }

  /* Transcode start/seek: ask the server where it will REALLY land first.
     /api/cinema/hls/start resolves that keyframe-true offset itself, so the HLS
     path needs one round trip where the progressive path needed two. */
  function startTranscodeAt(t, autoplay) {
    var token = ++S.seekToken;
    var wasPlaying = autoplay || !video.paused;
    spinner(true, 'Seeking…');
    releaseHls(false);
    var q = '?t=' + Math.max(0, t).toFixed(3) +
            '&a=' + S.audioId + (S.burn ? '&burn=' + encodeURIComponent(S.burn) : '');

    function progressive() {
      var url = '/api/cinema/seek/' + encodeURIComponent(S.item.id) +
                '?t=' + Math.max(0, t).toFixed(3) +
                (S.burn ? '&burn=' + encodeURIComponent(S.burn) : '');
      return api(url).then(function (d) {
        if (token !== S.seekToken) return;
        S.offset = (d && d.success) ? d.start : Math.max(0, t);
        video.src = transcodeUrl(S.offset);
        video.load();
        applySubtitle(S.subId);
        paint();
        if (wasPlaying) video.play().catch(function () {});
      });
    }

    if (!hlsSupported() && !video.canPlayType('application/vnd.apple.mpegurl')) {
      progressive().catch(function () {
        if (token === S.seekToken) showError('Could not start playback.');
      });
      return;
    }

    fetch('/api/cinema/hls/start/' + encodeURIComponent(S.item.id) + q,
          { method: 'POST', credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (token !== S.seekToken) return;
        if (!d || !d.success) throw new Error(d && d.error);
        S.offset = d.offset;
        applySubtitle(S.subId);
        paint();
        if (hlsSupported()) {
          attachHls(d.id, wasPlaying, token);
        } else {
          // Safari/iOS play HLS natively; MSE is neither available nor needed.
          S.hlsSession = d.id;
          video.src = '/api/cinema/hls/' + encodeURIComponent(d.id) + '/index.m3u8';
          video.load();
          if (wasPlaying) video.play().catch(function () {});
        }
      })
      .catch(function () {
        // No scratch disk, or every ladder step failed: the progressive stream
        // needs neither, so it is still worth a try before giving up.
        if (token !== S.seekToken) return;
        progressive().catch(function () {
          if (token === S.seekToken) showError('Could not start playback.');
        });
      });
  }

  function seekTo(t) {
    if (!S.item) return;
    t = clamp(t, 0, S.duration || t);
    // A seek is a statement about where the viewer wants to be: going back
    // before the intro offers the button again, and seeking INTO the ending
    // means they want to watch it, so the auto-skip stands down.
    var m = S.marks || {};
    if (m.intro && t < m.intro.start + 1) S.introDone = false;
    if (m.outro) S.outroFired = t >= m.outro.start - 1;
    if (S.mode === 'direct') {
      video.currentTime = t;
    } else if (seekInSession(t)) {
      // Landed inside the running session — no new ffmpeg, no reload.
    } else {
      startTranscodeAt(t, !video.paused);
    }
    paint(t);
  }

  /* An HLS session keeps every segment it has produced, so a seek that lands
     inside it is an ordinary currentTime move — instant, and it keeps the
     buffer that is already there. Only a seek outside that window has to pay
     for a new ffmpeg. Returns false when there is no session to seek within,
     which is also the whole of the progressive path's behaviour. */
  function seekInSession(t) {
    if (!S.hls || !video.seekable || !video.seekable.length) return false;
    var local = t - S.offset;
    var end;
    try { end = video.seekable.end(video.seekable.length - 1); }
    catch (e) { return false; }
    // A one-second margin off the produced edge: seeking exactly onto it lands
    // in a fragment the demuxer has not appended yet and stalls the element.
    if (local < 0 || local > end - 1) return false;
    video.currentTime = local;
    return true;
  }

  /* ── subtitles ─────────────────────────────────────────────────────────── */
  function applySubtitle(subId) {
    // ORDER MATTERS. Removing a <track> element takes its TextTrack out of
    // video.textTracks, so the loop that followed disabled nothing and Chrome
    // kept the cue boxes it had already PAINTED on screen. Measured on a
    // transcoded episode: after six seeks the picture carried six stale lines
    // from six different timestamps, while textTracks reported one active cue.
    // Switching every track off FIRST tears those boxes down.
    for (var i = 0; i < video.textTracks.length; i++) video.textTracks[i].mode = 'disabled';
    Array.prototype.forEach.call(video.querySelectorAll('track'), function (t) { t.remove(); });

    S.subId = subId || '';
    $('btn-subs').classList.toggle('on', !!S.subId);
    var sub = subById(S.subId);
    if (!sub || !sub.text) return;      // off, or painted into the picture

    var url = '/api/cinema/subtitle/' + encodeURIComponent(S.item.id) + '/' +
              encodeURIComponent(S.subId) + '.vtt';
    // The transcoded stream's clock restarts at the seek point, so cues have to
    // be rebased by the same amount or the whole track runs early.
    if (S.mode === 'transcode' && S.offset > 0) url += '?shift=' + S.offset.toFixed(3);

    var tr = document.createElement('track');
    tr.kind = 'subtitles';
    tr.label = sub.label;
    tr.srclang = sub.lang || 'und';
    tr.src = url;
    tr.default = true;
    video.appendChild(tr);
    var enable = function () {
      for (var i = 0; i < video.textTracks.length; i++) {
        video.textTracks[i].mode = (i === video.textTracks.length - 1) ? 'showing' : 'disabled';
      }
    };
    tr.addEventListener('load', enable);
    tr.addEventListener('error', function () {
      toast('That subtitle could not be loaded', 'err');
    });
    setTimeout(enable, 60);
  }

  function chooseSubtitle(id) {
    var sub = subById(id);
    var wasBurn = !!S.burn;
    var wantsBurn = !!(sub && !sub.text);
    if (wantsBurn || wasBurn) {
      // Burn-in changes the ffmpeg graph — the stream has to be rebuilt. The
      // choice still has to be remembered here: this path returns early, so
      // picking a burn-in track used to be forgotten the moment the episode
      // ended, while picking a text one was kept.
      var at = now();
      S.subId = id || '';
      if (sub) rememberSub(sub);
      mount(at);
      return;
    }
    applySubtitle(id);
    toast(id ? 'Subtitles: ' + (sub ? sub.label : '') : 'Subtitles off');
    if (sub) rememberSub(sub);
  }

  /* A subtitle choice is remembered as language + the distinctive word in its
     label ('Dialogue', a fansub group's name), because ids are per FILE. */
  function rememberSub(sub) {
    if (!S.showKey || !sub) return;
    var patch = {};
    if (sub.lang) patch.sub_langs = [sub.lang];
    var words = String(sub.label || '').toLowerCase().match(/[a-z][a-z'-]{3,}/g) || [];
    var stop = { english: 1, japanese: 1, dutch: 1, german: 1, french: 1, spanish: 1,
                 subtitles: 1, subtitle: 1, track: 1, default: 1, burn: 1, none: 1 };
    var keys = words.filter(function (w) { return !stop[w]; }).slice(0, 3);
    if (keys.length) patch.sub_prefer = keys;
    if (Object.keys(patch).length) rememberForShow(patch);
  }

  function chooseAudio(i) {
    if (S.audioId === i) return;
    S.audioId = i;
    var at = now();
    if (S.mode === 'direct') toast('Switching audio track…');
    // Remember the LANGUAGE, not the index: track order differs from release to
    // release, so an index would pick the wrong stream on the next episode.
    var lang = ((S.item.audio || [])[i] || {}).lang;
    if (lang) rememberForShow({ audio_langs: [lang] }, 'Japanese');
    mount(at);
  }

  /* Store a preference against the whole series so every other episode — and
     every episode added later — opens the same way. */
  function rememberForShow(patch, _hint) {
    if (!S.showKey) return;
    api('/api/cinema/prefs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ show: S.showKey, prefs: patch })
    }).then(function (d) {
      if (!d || !d.success) return;
      Object.keys(patch).forEach(function (k) { S.prefs[k] = patch[k]; });
    }).catch(function () { /* a lost preference is not worth an error */ });
  }

  /* ══ Intro / ending skips ════════════════════════════════════════════════
     The marks come from the server (named chapters when the file has them, the
     series' own setting next, the global default last), so the player only has
     to decide when to SHOW the button and when to act.

     The ten seconds are counted in PLAYBACK time, not wall-clock: a paused
     video is still at the start of its intro, and a card that expired while the
     viewer was answering the door would be a card that was never there. */
  var skipBtn = $('btn-skip-intro');

  function resetSkips(startAt) {
    S.introDone = false;
    hideSkip(false);
    var out = S.marks && S.marks.outro;
    // Landing INSIDE the ending — a resume, or a deliberate seek — is a choice
    // to be there. Don't bounce straight out of it.
    S.outroFired = !!(out && startAt >= out.start - 1);
  }

  function showSkip(label) {
    $('skip-intro-label').textContent = label || 'Skip intro';
    if (!skipBtn.hidden) return;              // already up — leave it alone
    skipBtn.hidden = false;
    requestAnimationFrame(function () { skipBtn.classList.add('show'); });
  }
  function hideSkip(fade) {
    if (skipBtn.hidden) return;
    skipBtn.classList.remove('show');
    if (!fade) { skipBtn.hidden = true; return; }
    setTimeout(function () {
      if (!skipBtn.classList.contains('show')) skipBtn.hidden = true;
    }, 240);
  }

  function marksTick(t) {
    var m = S.marks || {};
    var intro = m.intro;
    if (intro && !S.introDone) {
      var win = m.button_seconds || 10;
      var upTo = Math.min(intro.start + win, intro.end);
      if (t >= intro.start - 0.4 && t < upTo) showSkip();
      else if (t >= upTo) { S.introDone = true; hideSkip(true); }
    }
    if (m.outro && m.auto_skip_outro && !S.outroFired && t >= m.outro.start) {
      S.outroFired = true;
      skipEnding();
    }
  }

  function skipIntro() {
    var intro = (S.marks || {}).intro;
    if (!intro) return;
    S.introDone = true;
    hideSkip(true);
    seekTo(intro.end);
    toast('Intro skipped');
  }
  skipBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    skipIntro();
  });

  function skipEnding() {
    var hasNext = S.qIndex >= 0 && S.qIndex + 1 < S.queue.length;
    if (S.item) setPos(S.item.id, 0);          // watched, as far as resume cares
    if (hasNext) {
      toast('Skipped the ending — next episode');
      playNext();
    } else {
      toast('Skipped the ending — that was the last one');
      video.pause();
      showUI(true);
    }
  }

  /* Re-read the marks after a settings change: the server owns how chapters,
     series settings and defaults combine, so never re-derive them here. */
  function refreshMarks(done) {
    if (!S.item) return;
    api('/api/cinema/item/' + encodeURIComponent(S.item.id)).then(function (d) {
      if (d && d.success) {
        S.marks = d.item.marks || {};
        S.prefs = d.item.prefs || {};
        S.item.prefs_overrides = d.item.prefs_overrides || [];
        resetSkips(now());
      }
      if (done) done();
    }).catch(function () { if (done) done(); });
  }

  /* ── paint ─────────────────────────────────────────────────────────────── */
  function paint(forced) {
    var t = (forced != null) ? forced : now();
    var d = S.duration || video.duration || 0;
    var pct = d ? clamp((t / d) * 100, 0, 100) : 0;
    $('scrub-played').style.width = pct + '%';
    $('scrub-ball').style.left = pct + '%';
    $('t-cur').textContent = fmt(t);
    if (d) $('t-dur').textContent = fmt(d);

    var buf = 0;
    try {
      if (video.buffered.length) {
        var end = video.buffered.end(video.buffered.length - 1);
        buf = (S.mode === 'direct') ? end : S.offset + end;
      }
    } catch (e) { /* not ready */ }
    $('scrub-buffer').style.width = (d ? clamp((buf / d) * 100, 0, 100) : 0) + '%';
  }

  video.addEventListener('timeupdate', function () {
    if (S.dragging) return;
    paint();
    marksTick(now());
  });
  video.addEventListener('progress', function () { if (!S.dragging) paint(); });
  video.addEventListener('loadedmetadata', function () {
    if (S.mode === 'direct' && video.duration && isFinite(video.duration)) {
      S.duration = video.duration;
    }
    paint();
  });
  video.addEventListener('playing', function () { spinner(false); showError(''); S.errRetries = 0; });
  video.addEventListener('canplay', function () { spinner(false); });
  video.addEventListener('waiting', function () { spinner(true, 'Buffering…'); });
  video.addEventListener('play', function () {
    document.body.classList.add('playing');
    swapIcon('btn-play', '.ic-pause', '.ic-play');
    kickUI();
  });
  video.addEventListener('pause', function () {
    document.body.classList.remove('playing');
    swapIcon('btn-play', '.ic-play', '.ic-pause');
    showUI(true);
  });
  video.addEventListener('ended', function () {
    if (S.item) setPos(S.item.id, 0);
    playNext();
  });
  var MAX_ERR_RETRIES = 4;

  /* Shared by the media element and by hls.js, which reports its own fatal
     errors rather than surfacing them on the element.

     NETWORK (2) and, as a knock-on effect of a connection that was cut
     mid-buffer, DECODE (3) are almost always a dropped tunnel/wifi link, not a
     bad file — the direct-play byte stream runs over the public Cloudflare
     tunnel and a stalled Range request there surfaces to the browser exactly
     like this. On the HLS path a reaped session behaves the same way: the
     playlist starts answering 410. Re-mounting from the current position picks
     a fresh connection (and a fresh session) and usually just works, so retry a
     few times with backoff before bothering the user. */
  function onPlaybackError(retryable) {
    if (!S.item) return;
    if (retryable && S.errRetries < MAX_ERR_RETRIES) {
      S.errRetries += 1;
      var at = now();
      var gen = S.mountGen;
      spinner(true, 'Reconnecting…');
      clearTimeout(S.errRetryTimer);
      S.errRetryTimer = setTimeout(function () {
        if (gen !== S.mountGen || !S.item) return; // user navigated away meanwhile
        mount(at);
      }, Math.min(1000 * Math.pow(2, S.errRetries - 1), 8000));
      return;
    }
    spinner(false);
    showError(retryable
      ? 'Lost the connection to the server after several tries. Tap to try again.'
      : 'Playback failed for this file. It may be missing or in a format ffmpeg could not convert.');
  }

  video.addEventListener('error', function () {
    // hls.js owns its errors; the element's blob: source reports secondary ones
    // that would double-count against the retry budget.
    if (S.hls || !S.item || !video.currentSrc) return;
    var code = video.error && video.error.code;
    onPlaybackError(code === MediaError.MEDIA_ERR_NETWORK ||
                    code === MediaError.MEDIA_ERR_DECODE);
  });

  $('stage-error').addEventListener('click', function () {
    if (!S.item) return;
    S.errRetries = 0;
    clearTimeout(S.errRetryTimer);
    mount(now());
  });

  setInterval(function () {
    if (S.item && !video.paused) setPos(S.item.id, now());
  }, 5000);

  // pagehide, not unload: it is the only one iOS Safari reliably fires, and it
  // also covers the back/forward cache where unload never runs at all.
  window.addEventListener('pagehide', function () { releaseHls(true); });

  function playNext() {
    if (S.qIndex < 0 || S.qIndex + 1 >= S.queue.length) { showUI(true); return; }
    S.qIndex += 1;
    openItem(S.queue[S.qIndex]);
  }

  /* ── scrubber (draggable ball) ─────────────────────────────────────────── */
  var hit = $('scrub-hit'), scrubWrap = $('scrub'), tip = $('scrub-tip');

  function timeAt(clientX) {
    var r = hit.getBoundingClientRect();
    var ratio = clamp((clientX - r.left) / r.width, 0, 1);
    return ratio * (S.duration || video.duration || 0);
  }
  function moveTip(clientX, t) {
    var r = hit.getBoundingClientRect();
    tip.textContent = fmt(t);
    tip.style.left = clamp(clientX - r.left, 26, r.width - 26) + 'px';
  }

  hit.addEventListener('pointermove', function (e) {
    if (S.dragging) return;
    moveTip(e.clientX, timeAt(e.clientX));
  });

  hit.addEventListener('pointerdown', function (e) {
    if (!S.item) return;
    e.preventDefault();
    S.dragging = true;
    scrubWrap.classList.add('dragging');
    hit.setPointerCapture(e.pointerId);
    var t = timeAt(e.clientX);
    paint(t);
    moveTip(e.clientX, t);
  });

  hit.addEventListener('pointermove', function (e) {
    if (!S.dragging) return;
    var t = timeAt(e.clientX);
    paint(t);
    moveTip(e.clientX, t);
    // Direct play can scrub live; a transcode would spawn an ffmpeg per pixel,
    // so it commits on release instead.
    if (S.mode === 'direct') video.currentTime = t;
  });

  function endDrag(e) {
    if (!S.dragging) return;
    S.dragging = false;
    scrubWrap.classList.remove('dragging');
    var t = timeAt(e.clientX);
    seekTo(t);
  }
  hit.addEventListener('pointerup', endDrag);
  hit.addEventListener('pointercancel', function () {
    S.dragging = false;
    scrubWrap.classList.remove('dragging');
    paint();
  });

  /* ── controls ──────────────────────────────────────────────────────────── */
  function togglePlay() {
    if (!S.item) return;
    if (video.paused) video.play().catch(function () {}); else video.pause();
    pulse(video.paused);
  }
  function pulse(paused) {
    var el = $('pulse');
    el.innerHTML = paused
      ? '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6.5 4.5h4v15h-4zM13.5 4.5h4v15h-4z"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>';
    el.classList.remove('go');
    void el.offsetWidth;
    el.classList.add('go');
  }

  $('btn-play').addEventListener('click', togglePlay);
  $('btn-back').addEventListener('click', function () { seekTo(now() - 10); });
  $('btn-fwd').addEventListener('click', function () { seekTo(now() + 10); });

  $('btn-mute').addEventListener('click', function () {
    video.muted = !video.muted;
    syncVol();
  });
  $('vol-range').addEventListener('input', function () {
    video.volume = parseFloat(this.value);
    video.muted = video.volume === 0;
    syncVol();
  });
  function syncVol() {
    var m = video.muted || video.volume === 0;
    swapIcon('btn-mute', m ? '.ic-muted' : '.ic-vol', m ? '.ic-vol' : '.ic-muted');
    $('vol-range').value = m ? 0 : video.volume;
    try { localStorage.setItem('cine:vol', String(video.volume)); localStorage.setItem('cine:muted', m ? '1' : '0'); } catch (e) {}
  }
  try {
    var sv = parseFloat(localStorage.getItem('cine:vol'));
    if (isFinite(sv)) video.volume = clamp(sv, 0, 1);
    video.muted = localStorage.getItem('cine:muted') === '1';
  } catch (e) {}
  syncVol();

  $('btn-subs').addEventListener('click', function (e) {
    e.stopPropagation();
    openMenu('subs', e.currentTarget.getBoundingClientRect());
  });
  $('btn-settings').addEventListener('click', function (e) {
    e.stopPropagation();
    openMenu('root', e.currentTarget.getBoundingClientRect());
  });

  $('btn-pip').addEventListener('click', function () {
    if (!document.pictureInPictureEnabled) { toast('Picture-in-picture is not available here', 'err'); return; }
    if (document.pictureInPictureElement) document.exitPictureInPicture();
    else video.requestPictureInPicture().catch(function () { toast('Picture-in-picture failed', 'err'); });
  });

  $('btn-full').addEventListener('click', toggleFull);
  function toggleFull() {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(function () {});
  }
  // One-directional entry, called from the rail's click handler so a movie always
  // opens full-screen. Must run synchronously inside the click handler (not after
  // openItem's fetch resolves) — the Fullscreen API requires an active user gesture.
  function enterFullscreen() {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(function () {});
  }
  document.addEventListener('fullscreenchange', function () {
    var on = !!document.fullscreenElement;
    swapIcon('btn-full', on ? '.ic-fsx' : '.ic-fs', on ? '.ic-fs' : '.ic-fsx');
    // Fullscreen means the picture, nothing else: stow the board and give it
    // back exactly as it was on the way out.
    if (on) {
      S.railBeforeFull = document.body.classList.contains('rail-open');
      document.body.classList.remove('rail-open');
    } else if (S.railBeforeFull) {
      document.body.classList.add('rail-open');
    }
  });

  /* ── UI auto-hide ──────────────────────────────────────────────────────── */
  function showUI(sticky) {
    stage.classList.add('show-ui');
    $('topbar').classList.add('show');
    clearTimeout(S.hideTimer);
    if (!sticky) S.hideTimer = setTimeout(hideUI, 2800);
  }
  function hideUI() {
    if (!S.item || video.paused || ctx.classList.contains('open')) return;
    stage.classList.remove('show-ui');
    $('topbar').classList.remove('show');
  }
  function kickUI() { showUI(false); }
  stage.addEventListener('pointermove', kickUI);
  stage.addEventListener('pointerleave', function () { if (!video.paused) hideUI(); });
  $('topbar').addEventListener('pointerenter', function () { showUI(true); });
  $('topbar').addEventListener('pointerleave', function () { if (!video.paused) kickUI(); });
  // A pointer resting ON the control bar fires no pointermove, so without this the
  // bar hid itself out from under the cursor 2.8 s after you stopped moving —
  // right as you were reaching for the scrub ball.
  $('controls').addEventListener('pointerenter', function () { showUI(true); });
  $('controls').addEventListener('pointerleave', function () { if (!video.paused) kickUI(); });
  // A remote/keyboard focuses a button instead of hovering it, so the bar needs the
  // same "stay open while in use" treatment pointerenter/leave give the mouse path.
  $('controls').addEventListener('focusin', function () { showUI(true); });
  $('controls').addEventListener('focusout', function () {
    if (video.paused) return;
    // focusout fires before the next element (possibly still inside #controls)
    // takes focus, so activeElement isn't settled until the next tick.
    setTimeout(function () {
      if (!$('controls').contains(document.activeElement)) kickUI();
    }, 0);
  });
  showUI(true);

  video.addEventListener('click', function (e) { e.preventDefault(); togglePlay(); });
  video.addEventListener('dblclick', function (e) { e.preventDefault(); toggleFull(); });

  /* ══ Right-click menu ════════════════════════════════════════════════════ */
  var TICK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m4.5 12.5 5 5 10-11"/></svg>';
  var ARROW = '<svg class="cx-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9.5 5.5 6.5 6.5-6.5 6.5"/></svg>';

  function row(label, opts) {
    opts = opts || {};
    return '<button class="cx-item" ' + (opts.disabled ? 'disabled ' : '') +
      (opts.act ? 'data-act="' + opts.act + '" ' : '') +
      (opts.val !== undefined ? 'data-val="' + esc(opts.val) + '" ' : '') + 'role="menuitem">' +
      '<span class="cx-tick">' + (opts.on ? TICK : '') + '</span>' +
      '<span class="cx-label">' + esc(label) + '</span>' +
      (opts.right ? '<span class="cx-val">' + esc(opts.right) + '</span>' : '') +
      (opts.arrow ? ARROW : '') + '</button>';
  }

  function menuHTML(page) {
    var it = S.item;
    if (!it) return '<div class="cx-info">Nothing is playing.</div>';

    if (page === 'subs') {
      var h = '<div class="cx-head">Subtitles</div>';
      h += row('Off', { act: 'sub', val: '', on: !S.subId });
      (it.subs || []).forEach(function (s) {
        h += row(s.label, { act: 'sub', val: s.id, on: S.subId === s.id,
                            right: s.text ? '' : 'burn-in' });
      });
      if (!(it.subs || []).length) h += '<div class="cx-info">No subtitles found for this title.</div>';
      h += '<div class="cx-sep"></div>' + row('Back', { act: 'page', val: 'root' });
      return h;
    }
    if (page === 'audio') {
      var a = '<div class="cx-head">Audio track</div>';
      (it.audio || []).forEach(function (t) {
        a += row(t.label, { act: 'audio', val: t.id, on: S.audioId === t.id });
      });
      if (!(it.audio || []).length) a += '<div class="cx-info">No audio tracks.</div>';
      a += '<div class="cx-sep"></div>' + row('Back', { act: 'page', val: 'root' });
      return a;
    }
    if (page === 'speed') {
      var sp = '<div class="cx-head">Playback speed</div>';
      [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].forEach(function (r) {
        sp += row(r === 1 ? 'Normal' : r + '×', { act: 'rate', val: r, on: Math.abs(video.playbackRate - r) < 0.01 });
      });
      sp += '<div class="cx-sep"></div>' + row('Back', { act: 'page', val: 'root' });
      return sp;
    }
    if (page === 'series') {
      var isEp = it.kind === 'episode';
      var who = isEp ? (it.series || it.title) : it.title;
      var m = S.marks || {};
      var srcWord = { chapter: 'from this file\u2019s chapters', show: 'set for this series',
                      setting: 'from the global setting', default: 'default' };
      var v = '<div class="cx-head">' + esc(isEp ? who : 'This title') + '</div>';
      v += row('Auto-skip the ending', { act: 'skipauto', on: !!m.auto_skip_outro,
                                         right: m.outro ? fmt(m.outro.start) : 'no mark' });
      v += row('Intro ends here', { act: 'introhere', right: fmt(now()) });
      v += row('Ending starts here', { act: 'outrohere', right: fmt(now()) });
      v += '<div class="cx-sep"></div>';
      v += '<div class="cx-info">' +
           '<b>Intro</b> ' + (m.intro ? fmt(m.intro.start) + '\u2013' + fmt(m.intro.end) +
             ' <span class="dim">(' + esc(srcWord[m.intro.source] || m.intro.source) + ')</span>'
             : 'none') + '<br>' +
           '<b>Ending</b> ' + (m.outro ? 'from ' + fmt(m.outro.start) +
             ' <span class="dim">(' + esc(srcWord[m.outro.source] || m.outro.source) + ')</span>'
             : 'none') +
           (isEp ? '<br><span class="dim">These apply to every episode of this series, including ones added later.</span>' : '') +
           '</div>';
      if (isEp) v += row('Rename this series\u2026', { act: 'rename', right: who });
      v += row('Clear these settings', { act: 'clearshow',
                                         disabled: !(it.prefs_overrides || []).length });
      v += '<div class="cx-sep"></div>' + row('Back', { act: 'page', val: 'root' });
      return v;
    }
    if (page === 'info') {
      var res = it.width && it.height ? it.width + '×' + it.height : '—';
      var gb = it.size ? (it.size / 1073741824).toFixed(2) + ' GB' : '—';
      var mode = S.mode === 'direct' ? 'Direct play'
        : 'Live transcode' + (it.transcode_reason ? ' (' + it.transcode_reason + ')' : '');
      return '<div class="cx-head">Details</div><div class="cx-info">' +
        '<b>File</b> ' + esc(it.filename) + '<br>' +
        '<b>Resolution</b> ' + res + '<br>' +
        '<b>Video</b> ' + esc(it.vcodec || '—') + ' &nbsp; <b>Audio</b> ' + esc(it.acodec || '—') + '<br>' +
        '<b>Size</b> ' + gb + ' &nbsp; <b>Length</b> ' + fmt(it.duration) + '<br>' +
        '<b>Mode</b> ' + esc(mode) +
        (S.mode === 'transcode' ? '<br><b>Stream origin</b> ' + fmt(S.offset) : '') +
        '</div><div class="cx-sep"></div>' + row('Back', { act: 'page', val: 'root' });
    }

    var subLabel = S.subId ? ((subById(S.subId) || {}).label || 'On') : 'Off';
    var audioLabel = ((it.audio || [])[S.audioId] || {}).label || '—';
    var h2 = '';
    h2 += row('Subtitles', { act: 'page', val: 'subs', arrow: true, right: subLabel });
    h2 += row('Audio', { act: 'page', val: 'audio', arrow: true, right: audioLabel,
                         disabled: (it.audio || []).length < 2 });
    h2 += row('Speed', { act: 'page', val: 'speed', arrow: true,
                         right: video.playbackRate === 1 ? 'Normal' : video.playbackRate + '×' });
    h2 += '<div class="cx-sep"></div>';
    h2 += row(video.paused ? 'Play' : 'Pause', { act: 'toggle' });
    h2 += row(video.loop ? 'Loop: on' : 'Loop: off', { act: 'loop', on: video.loop });
    h2 += row('Picture-in-picture', { act: 'pip' });
    h2 += row(document.fullscreenElement ? 'Exit fullscreen' : 'Fullscreen', { act: 'full' });
    h2 += '<div class="cx-sep"></div>';
    h2 += row(it.kind === 'episode' ? 'Series playback' : 'Skips & marks',
              { act: 'page', val: 'series', arrow: true,
                right: (S.marks || {}).auto_skip_outro ? 'ending auto-skipped' : '' });
    h2 += row('Details', { act: 'page', val: 'info', arrow: true });
    return h2;
  }

  function openMenu(page, rect, x, y) {
    ctx.innerHTML = menuHTML(page || 'root');
    ctx.classList.add('open');
    ctx.style.visibility = 'hidden';
    ctx.style.left = '0px'; ctx.style.top = '0px';
    var w = ctx.offsetWidth, h = ctx.offsetHeight;
    var px, py;
    if (rect) {
      px = clamp(rect.left + rect.width / 2 - w / 2, 8, innerWidth - w - 8);
      py = clamp(rect.top - h - 10, 8, innerHeight - h - 8);
    } else {
      px = clamp(x, 8, innerWidth - w - 8);
      py = clamp(y, 8, innerHeight - h - 8);
    }
    ctx.style.left = px + 'px';
    ctx.style.top = py + 'px';
    ctx.style.visibility = '';
    showUI(true);
  }
  function closeMenu() {
    ctx.classList.remove('open');
    if (S.item && !video.paused) kickUI();
  }

  stage.addEventListener('contextmenu', function (e) {
    e.preventDefault();
    openMenu('root', null, e.clientX, e.clientY);
  });
  document.addEventListener('click', function (e) {
    if (!ctx.contains(e.target)) closeMenu();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && ctx.classList.contains('open')) closeMenu();
  });

  ctx.addEventListener('click', function (e) {
    var b = e.target.closest('.cx-item');
    if (!b || b.disabled) return;
    e.stopPropagation();
    var act = b.dataset.act, val = b.dataset.val;
    if (act === 'page') { openMenuKeepPos(val); return; }
    if (act === 'sub') { chooseSubtitle(val); closeMenu(); return; }
    if (act === 'audio') { chooseAudio(parseInt(val, 10)); closeMenu(); return; }
    if (act === 'rate') { video.playbackRate = parseFloat(val); openMenuKeepPos('speed'); return; }
    if (act === 'toggle') { togglePlay(); closeMenu(); return; }
    if (act === 'loop') { video.loop = !video.loop; openMenuKeepPos('root'); return; }
    if (act === 'pip') { $('btn-pip').click(); closeMenu(); return; }
    if (act === 'full') { toggleFull(); closeMenu(); return; }
    if (act === 'skipauto') { setShowPref({ auto_skip_outro: !(S.marks || {}).auto_skip_outro }); return; }
    if (act === 'introhere') {
      // Both of these read the CURRENT position, so they only mean anything if
      // the picture is actually at the moment being marked. Refuse the rest:
      // storing "the intro ends at 0:03" would silently switch the mark off.
      if (!S.duration || now() < 2 || now() > S.duration * 0.5) {
        toast('Play up to the moment the intro ends first, then use this', 'err');
        return;
      }
      setShowPref({ intro_start: 0, intro_end: Math.round(now() * 10) / 10 });
      return;
    }
    if (act === 'outrohere') {
      if (!S.duration || now() < S.duration * 0.5) {
        toast('Play up to the moment the ending starts first, then use this', 'err');
        return;
      }
      var lead = Math.round(((S.duration || 0) - now()) * 10) / 10;
      setShowPref({ outro_lead: Math.max(5, lead), auto_skip_outro: true });
      return;
    }
    if (act === 'rename') {
      if (!S.item) return;
      var cur = S.item.series || S.item.title;
      closeMenu();
      renameSeries(cur);
      return;
    }
    if (act === 'clearshow') {
      setShowPref({ intro_end: null, intro_start: null, outro_lead: null,
                    auto_skip_outro: null, audio_langs: null, sub_langs: null,
                    sub_prefer: null });
      return;
    }
  });

  /* Write one series setting, then let the server tell us what the marks became
     (chapters, series setting and defaults are combined there, not here). */
  function setShowPref(patch) {
    if (!S.showKey) { toast('No series to remember this against', 'err'); return; }
    api('/api/cinema/prefs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ show: S.showKey, prefs: patch })
    }).then(function (d) {
      if (!d || !d.success) { toast((d && d.error) || 'Could not save that', 'err'); return; }
      refreshMarks(function () { openMenuKeepPos('series'); });
    }).catch(function () { toast('Could not save that', 'err'); });
  }

  function openMenuKeepPos(page) {
    var left = ctx.style.left, top = ctx.style.top;
    ctx.innerHTML = menuHTML(page);
    ctx.style.left = left; ctx.style.top = top;
    var r = ctx.getBoundingClientRect();
    if (r.bottom > innerHeight - 8) ctx.style.top = Math.max(8, innerHeight - r.height - 8) + 'px';
  }

  /* ══ Keyboard ════════════════════════════════════════════════════════════ */
  document.addEventListener('keydown', function (e) {
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    var k = e.key;
    if (k === ' ' || k === 'k') { e.preventDefault(); togglePlay(); }
    else if (k === 'ArrowLeft') { e.preventDefault(); seekTo(now() - (e.shiftKey ? 60 : 10)); showUI(false); }
    else if (k === 'ArrowRight') { e.preventDefault(); seekTo(now() + (e.shiftKey ? 60 : 10)); showUI(false); }
    else if (k === 'j') seekTo(now() - 30);
    else if (k === 'l') seekTo(now() + 30);
    else if (k === 'ArrowUp') { e.preventDefault(); video.volume = clamp(video.volume + 0.05, 0, 1); video.muted = false; syncVol(); showUI(false); }
    else if (k === 'ArrowDown') { e.preventDefault(); video.volume = clamp(video.volume - 0.05, 0, 1); syncVol(); showUI(false); }
    else if (k === 'm') { video.muted = !video.muted; syncVol(); }
    else if (k === 'f') toggleFull();
    else if (k === 'c') { cycleSubs(); }
    else if (k === 's') { if (!skipBtn.hidden) skipIntro(); }
    else if (k === 'b') { document.body.classList.toggle('rail-open'); }
    else if (k >= '0' && k <= '9') { if (S.duration) seekTo(S.duration * (parseInt(k, 10) / 10)); }
  });

  function cycleSubs() {
    var subs = (S.item && S.item.subs) || [];
    if (!subs.length) { toast('No subtitles for this title'); return; }
    var ids = [''].concat(subs.map(function (s) { return s.id; }));
    var next = ids[(ids.indexOf(S.subId) + 1) % ids.length];
    chooseSubtitle(next);
  }

  /* Naming a series. Some releases carry the show's name nowhere — the folder
     is '01. Season 1 + Special' and the files are 'S01E14-Title [CRC].mkv' — so
     the name has to be told to the library once, against the folder. */
  function renameSeries(current, after) {
    var name = window.prompt('Name this series', current || '');
    if (name === null) return;                       // cancelled
    name = name.trim();
    api('/api/cinema/series_name', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ show: current, name: name })
    }).then(function (d) {
      if (!d || !d.success) { toast((d && d.error) || 'Could not rename that', 'err'); return; }
      toast(name ? 'Renamed to ' + name : 'Name cleared', 'ok');
      if (S.show) S.show.title = name || S.show.title;
      if (S.item) S.item.series = name || S.item.series;
      loadBoard(true).then(function () {
        // The prefs key follows the displayed name, so re-read the marks.
        if (S.item) refreshMarks();
        if (after) after();
      });
    }).catch(function () { toast('Could not rename that', 'err'); });
  }

  $('crumb-rename').addEventListener('click', function (e) {
    e.stopPropagation();
    if (S.show) renameSeries(S.show.title);
  });

  /* ══ Rail toggle / lock ══════════════════════════════════════════════════ */
  $('rail-toggle').addEventListener('click', function () {
    document.body.classList.toggle('rail-open');
  });
  $('btn-lock').addEventListener('click', function () {
    fetch('/api/cinema/lock', { method: 'POST' }).then(function () { window.location.href = '/'; });
  });

  /* ══ Folder picker + scan ════════════════════════════════════════════════ */
  var modal = $('scan-modal');
  function openScan() {
    modal.classList.add('open');
    $('scan-progress').hidden = true;
    $('scan-start').disabled = true;
    browse('');
  }
  function closeScan() {
    modal.classList.remove('open');
    clearTimeout(S.scanTimer);
  }
  $('btn-upload').addEventListener('click', openScan);
  $('scan-close').addEventListener('click', closeScan);
  $('scan-cancel').addEventListener('click', closeScan);
  modal.addEventListener('mousedown', function (e) { if (e.target === modal) closeScan(); });

  var FOLDER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M3 6.6h6l1.8 2.2H21v8.6a1.8 1.8 0 0 1-1.8 1.8H4.8A1.8 1.8 0 0 1 3 17.4z"/></svg>';
  var UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5.5"/><path d="m6.5 11 5.5-5.5 5.5 5.5"/></svg>';

  function browse(path) {
    api('/api/cinema/browse?path=' + encodeURIComponent(path)).then(function (d) {
      if (!d.success) { toast(d.error || 'Cannot open that folder', 'err'); return; }
      S.pickPath = d.path || '';
      $('picker-path').textContent = d.path || 'Choose a starting point';
      $('scan-start').disabled = !d.path;

      var html = '';
      if (d.path && d.parent) {
        html += '<button class="pick-row up" data-path="' + esc(d.parent) + '">' + UP +
                '<span>Up one level</span></button>';
      }
      (d.dirs || []).forEach(function (dir) {
        html += '<button class="pick-row" data-path="' + esc(dir.path) + '">' + FOLDER +
                '<span>' + esc(dir.name) + '</span></button>';
      });
      if (!html) html = '<div class="picker-note">No sub-folders here.</div>';
      $('picker-list').innerHTML = html;

      var note = '';
      if (d.path) {
        note = d.videos
          ? '<b>' + d.videos + ' video file' + (d.videos === 1 ? '' : 's') + '</b> directly in this folder — sub-folders are scanned too.'
          : 'No video files directly here. Sub-folders are still scanned.';
      } else {
        note = 'Pick a folder to start from.';
      }
      $('picker-note').innerHTML = note;
    });
  }

  $('picker-list').addEventListener('click', function (e) {
    var b = e.target.closest('.pick-row');
    if (b) browse(b.dataset.path);
  });

  $('scan-start').addEventListener('click', function () {
    if (!S.pickPath) return;
    $('scan-start').disabled = true;
    $('scan-progress').hidden = false;
    $('scan-bar').style.width = '4%';
    $('scan-text').textContent = 'Starting…';
    api('/api/cinema/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: S.pickPath })
    }).then(function (d) {
      if (!d.success) {
        $('scan-progress').hidden = true;
        $('scan-start').disabled = false;
        toast(d.error || 'Scan could not start', 'err');
        return;
      }
      pollScan(d.scan_id);
    });
  });

  function pollScan(id) {
    clearTimeout(S.scanTimer);
    api('/api/cinema/scan/' + encodeURIComponent(id)).then(function (d) {
      if (!d.success) { toast(d.error || 'Lost track of the scan', 'err'); return; }
      var pct = d.total ? Math.round((d.found / d.total) * 100) : 6;
      $('scan-bar').style.width = clamp(pct, 4, 100) + '%';
      var line = d.state === 'running'
        ? (d.total ? d.found + ' of ' + d.total + ' · ' : '') + (d.current || 'Looking for video files…')
        : (d.state === 'failed' ? 'Failed: ' + (d.error || 'unknown error')
           : 'Done — ' + d.added + ' new, ' + d.updated + ' updated' +
             (d.skipped ? ', ' + d.skipped + ' skipped' : ''));
      $('scan-text').textContent = line;

      if (d.state === 'running') {
        S.scanTimer = setTimeout(function () { pollScan(id); }, 900);
        loadBoardThrottled();
      } else {
        $('scan-start').disabled = false;
        loadBoard(true).then(function () {
          if (d.state === 'done') {
            toast(d.added ? 'Added ' + d.added + ' title' + (d.added === 1 ? '' : 's') : 'Library is up to date', 'ok');
          } else {
            toast('Scan failed: ' + (d.error || 'unknown error'), 'err');
          }
        });
        // Thumbnails are generated after the index is written, so refresh once more.
        setTimeout(function () { loadBoard(true); }, 4000);
      }
    });
  }

  var lastBoard = 0;
  function loadBoardThrottled() {
    if (Date.now() - lastBoard < 2500) return;
    lastBoard = Date.now();
    loadBoard(true);
  }

  /* ══ Boot ════════════════════════════════════════════════════════════════ */
  stage.classList.add('no-media');
  document.body.classList.add('rail-open');
  syncDd();
  loadBoard().then(function () {
    if (!S.board.count) {
      $('idle-hint').textContent = 'Nothing in the library yet — use Upload (top right) to scan a folder.';
    }
  });
})();
