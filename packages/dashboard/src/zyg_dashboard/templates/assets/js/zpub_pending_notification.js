// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

(function () {
  'use strict';

  var PENDING_KEY      = 'zpub_pending_req';
  var DISMISSED_PREFIX = 'zpub_dismissed_';
  var _pollTimer       = null;
  var _overlayEl       = null;
  var _cardEl          = null;

  function _lsGet(k)    { try { return localStorage.getItem(k); }    catch(_) { return null; } }
  function _lsSet(k, v) { try { localStorage.setItem(k, v); }        catch(_) {} }
  function _lsRemove(k) { try { localStorage.removeItem(k); }        catch(_) {} }

  function _savePending(id, prompt) { _lsSet(PENDING_KEY, JSON.stringify({ id: id, prompt: prompt })); }
  function _getStoredPending() { try { var s = _lsGet(PENDING_KEY); return s ? JSON.parse(s) : null; } catch(_) { return null; } }
  function _isDismissed(id) { return _lsGet(DISMISSED_PREFIX + id) === '1'; }

  function _resetSubmitBtn() {
    var btn = document.getElementById('submit-btn');
    if (btn) { btn.disabled = false; btn.innerHTML = 'Create →'; btn.style.opacity = ''; }
  }

  function _dismiss(id) {
    _lsRemove(PENDING_KEY);
    _lsSet(DISMISSED_PREFIX + id, '1');
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_overlayEl) { _overlayEl.remove(); _overlayEl = null; _cardEl = null; }
    _resetSubmitBtn();
  }

  var STATES = {
    pending:  { icon: '⏳', title: 'Pending approval',  body: 'Your request is awaiting manual approval. You will be notified here once a decision is made.', color: '#c4b5fd', bg: 'linear-gradient(135deg,#1e3a5f,#1a2540)', border: 'rgba(99,102,241,0.45)' },
    queued:   { icon: '🕐', title: 'Request queued',    body: 'Your request has been placed in the processing queue.',                                          color: '#93c5fd', bg: 'linear-gradient(135deg,#0f2940,#0a1e30)', border: 'rgba(59,130,246,0.45)'  },
    approved: { icon: '✅', title: 'Request accepted',  body: 'Your request was approved and is now being generated.',                                          color: '#86efac', bg: 'linear-gradient(135deg,#052e16,#064e3b)', border: 'rgba(34,197,94,0.45)'   },
    declined: { icon: '❌', title: 'Request declined',  body: 'Unfortunately your request was declined. You can dismiss this and try submitting again.',        color: '#fca5a5', bg: 'linear-gradient(135deg,#3b0a0a,#1c0505)', border: 'rgba(239,68,68,0.45)'   },
    done:     { icon: '🎬', title: 'Your video is ready!', body: 'Your documentary has been generated. Download it from your library on the left.',            color: '#6ee7b7', bg: 'linear-gradient(135deg,#052e16,#064e3b)', border: 'rgba(52,211,153,0.55)'   },
    failed:   { icon: '⚠️', title: 'Generation failed',    body: 'Something went wrong during generation. You can dismiss this and try submitting again.',     color: '#fca5a5', bg: 'linear-gradient(135deg,#3b0a0a,#1c0505)', border: 'rgba(239,68,68,0.45)'   },
  };

  function _createModal(reqId) {
    if (_overlayEl) return;
    var overlay = document.createElement('div');
    overlay.id = 'zpub-notif-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(0,0,0,0.52);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);';

    var card = document.createElement('div');
    card.id = 'zpub-notif-banner';
    card.style.cssText = 'max-width:420px;width:100%;border-radius:20px;padding:36px 36px 28px;box-shadow:0 20px 60px rgba(0,0,0,0.65);border:1px solid transparent;transition:background 0.4s,border-color 0.4s;text-align:center;';
    card.innerHTML =
      '<div id="zpub-notif-icon" style="font-size:3.2rem;margin-bottom:18px;line-height:1;">⏳</div>' +
      '<strong id="zpub-notif-title" style="display:block;font-size:1.15rem;margin-bottom:10px;letter-spacing:0.01em;"></strong>' +
      '<span id="zpub-notif-body" style="display:block;opacity:0.82;font-size:0.92rem;line-height:1.6;margin-bottom:26px;"></span>' +
      '<button id="zpub-notif-close" style="background:rgba(255,255,255,0.13);border:1px solid rgba(255,255,255,0.24);border-radius:9px;color:inherit;font-size:0.9rem;padding:10px 26px;cursor:pointer;font-weight:600;letter-spacing:0.03em;">Dismiss ✕</button>';

    overlay.appendChild(card);
    document.body.appendChild(overlay);
    document.getElementById('zpub-notif-close').addEventListener('click', function() { _dismiss(reqId); });
    _overlayEl = overlay;
    _cardEl    = card;
  }

  function _setBannerState(reqId, stateKey) {
    var s = STATES[stateKey] || STATES.pending;
    _createModal(reqId);
    if (!_cardEl) return;
    _cardEl.style.background  = s.bg;
    _cardEl.style.borderColor = s.border;
    _cardEl.style.color       = s.color;
    var icon    = document.getElementById('zpub-notif-icon');
    var titleEl = document.getElementById('zpub-notif-title');
    var bodyEl  = document.getElementById('zpub-notif-body');
    if (icon)    icon.textContent    = s.icon;
    if (titleEl) titleEl.textContent = s.title;
    if (bodyEl)  bodyEl.textContent  = s.body;
  }

  var _jobDoneTimer = null;

  // Poll /api/status/<jobId> until it's done or failed, then update banner + library.
  function _pollJobDone(jobId, reqId) {
    if (_jobDoneTimer) return;
    _jobDoneTimer = setInterval(function() {
      fetch('/api/status/' + encodeURIComponent(jobId))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(d) {
          if (!d) return;
          if (d.status === 'done') {
            clearInterval(_jobDoneTimer); _jobDoneTimer = null;
            _setBannerState(reqId, 'done');
            if (typeof loadSidebar === 'function') loadSidebar();
          } else if (d.status === 'failed') {
            clearInterval(_jobDoneTimer); _jobDoneTimer = null;
            _setBannerState(reqId, 'failed');
          }
        })
        .catch(function() {});
    }, 10000);
  }

  function _startPoll(reqId) {
    if (_pollTimer) return;
    _pollTimer = setInterval(function() {
      fetch('/api/pending_status/' + encodeURIComponent(reqId))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(pd) {
          if (!pd) return;
          if (pd.status === 'approved') {
            clearInterval(_pollTimer); _pollTimer = null;
            _setBannerState(reqId, 'approved');
            if (pd.job_id) {
              if (typeof window._zpubOnApproved === 'function') {
                try { window._zpubOnApproved(pd.job_id); } catch(_) {}
              }
              if (typeof loadSidebar === 'function') loadSidebar();
              _pollJobDone(pd.job_id, reqId);
            }
          } else if (pd.status === 'queued') {
            clearInterval(_pollTimer); _pollTimer = null;
            _setBannerState(reqId, 'queued');
          } else if (pd.status === 'declined') {
            clearInterval(_pollTimer); _pollTimer = null;
            _setBannerState(reqId, 'declined');
          }
        })
        .catch(function() {});
    }, 5000);
  }

  function _checkOnLoad() {
    var stored = _getStoredPending();
    if (!stored || !stored.id) return;
    var reqId = stored.id;
    if (_isDismissed(reqId)) return;
    fetch('/api/pending_status/' + encodeURIComponent(reqId))
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(pd) {
        if (!pd) return;
        var s = pd.status;
        if (s === 'pending') {
          _setBannerState(reqId, 'pending');
          _startPoll(reqId);
        } else if (s === 'queued') {
          _setBannerState(reqId, 'queued');
          _startPoll(reqId);
        } else if (s === 'approved') {
          _setBannerState(reqId, 'approved');
          if (pd.job_id) {
            if (typeof window._zpubOnApproved === 'function') {
              try { window._zpubOnApproved(pd.job_id); } catch(_) {}
            }
            // Refresh library immediately and poll until job is done.
            // This handles both the page-open case and the come-back-later case.
            if (typeof loadSidebar === 'function') loadSidebar();
            // Check if the job is already done (returned while the user was away)
            fetch('/api/status/' + encodeURIComponent(pd.job_id))
              .then(function(r) { return r.ok ? r.json() : null; })
              .then(function(d) {
                if (!d) return;
                if (d.status === 'done') {
                  _setBannerState(reqId, 'done');
                  if (typeof loadSidebar === 'function') loadSidebar();
                } else if (d.status === 'failed') {
                  _setBannerState(reqId, 'failed');
                } else {
                  // Still running — keep polling
                  _pollJobDone(pd.job_id, reqId);
                }
              })
              .catch(function() { _pollJobDone(pd.job_id, reqId); });
          }
        } else if (s === 'declined') {
          _setBannerState(reqId, 'declined');
        }
      })
      .catch(function() {});
  }

  window._zpubSavePending = function(id, prompt) {
    _savePending(id, prompt || '');
    if (_overlayEl) _setBannerState(id, 'pending');
    if (!_pollTimer) _startPoll(id);
  };

  document.addEventListener('DOMContentLoaded', _checkOnLoad);
})();
