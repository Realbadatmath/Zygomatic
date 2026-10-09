// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── Concurrent-pipeline test simulator ──────────────────────────────────────
   Injects fake _allRuns entries so the stacking UI can be tested without
   actually launching multiple pipelines.
   _simPipelineCount = 0  → simulation off, real API data drives _allRuns
   _simPipelineCount = N  → N fake runs are merged into _allRuns on every
                            renderBoard() call (real poll data ignored for runs)
────────────────────────────────────────────────────────────────────────────── */
let _simPipelineCount = 0;

// Fake card statuses per fake pipeline — cycles through meaningful patterns
// so each pipeline looks different on the board.
const _SIM_STATUS_PATTERNS = [
  { done: 0, running: 0 },   // idx 0 = primary, handled by real API
  { done: 2, running: 1 },   // pipeline 2: first 2 done, 1 running
  { done: 5, running: 1 },   // pipeline 3: 5 done, 1 running
  { done: 0, running: 0 },   // pipeline 4: all queued
  { done: 8, running: 1 },   // pipeline 5: most done
  { done: 3, running: 2 },   // pipeline 6: 3 done, 2 running
  { done: 1, running: 0 },   // pipeline 7: 1 done
  { done: 6, running: 1 },   // pipeline 8: 6 done, 1 running
];

const FAKE_TOPICS = [
  '', // primary, unused
  'Ancient Rome',
  'Deep Sea Creatures',
  'Space Exploration',
  'Medieval Knights',
  'Rainforest Ecosystems',
  'Viking Age',
  'Ocean Currents',
];

function _buildSimRuns() {
  if (_simPipelineCount <= 1) return;
  // Get the card names from the current primary run (or JOBS)
  const cardNames = JOBS.map(j => j.prompt);
  const fakeRuns = [];
  for (let i = 1; i < _simPipelineCount; i++) {
    const pat   = _SIM_STATUS_PATTERNS[i] || _SIM_STATUS_PATTERNS[i % _SIM_STATUS_PATTERNS.length];
    const cards = {};
    cardNames.forEach((name, idx) => {
      if (idx < pat.done)              cards[name] = 'done';
      else if (idx === pat.done)       cards[name] = 'running';
      else                             cards[name] = 'queued';
    });
    fakeRuns.push({
      pipeline_id: 'sim-run-' + i,
      cards,
      colorIdx:    i,   // uncapped — pipelineColor() derives past 8
      user_name:   'Simulator',
      topic:       FAKE_TOPICS[i] || (FAKE_TOPICS[1 + (i % (FAKE_TOPICS.length - 1))] + ' ' + (i + 1)),
    });
  }
  // Replace non-primary runs in _allRuns with simulated ones
  _allRuns = [_allRuns[0] || { pipeline_id: 'primary', cards: {}, colorIdx: 0, topic: '' }, ...fakeRuns];
}

// Apply simulated JOBS statuses for the focused pipeline
function _applySimFocusedRun() {
  if (!_focusPipelineId || !_focusPipelineId.startsWith('sim-')) return;
  const run = _allRuns.find(r => r.pipeline_id === _focusPipelineId);
  if (!run) return;
  JOBS.forEach(job => {
    const st = run.cards[job.prompt] || 'queued';
    job.status   = st;
    job.progress = st === 'done' ? 100 : st === 'running' ? 45 : 0;
  });
}

// ── UI: toggle the number picker popup ────────────────────────────────────────
function ltSimToggle(e) {
  if (e) e.stopPropagation();
  const popup = document.getElementById('lt-sim-popup');
  const btn   = document.getElementById('lt-sim-btn');
  const isOpen = popup.classList.contains('open');

  if (!isOpen) {
    // Build number buttons. 1–9 step one at a time (that is where the
    // stacked-tab layout lives); past that they jump, so the grid layout can
    // be checked all the way to the 100-run board ceiling without 100 buttons.
    const nums = document.getElementById('lt-sim-nums');
    nums.innerHTML = '';
    const SIM_COUNTS = [1,2,3,4,5,6,7,8,9,10,12,16,20,24,30,40,50,60,80,100];
    SIM_COUNTS.forEach((n) => {
      const b = document.createElement('button');
      b.className = 'sim-num' + (n === (_simPipelineCount || 1) ? ' active' : '');
      b.dataset.n = String(n);
      b.textContent = String(n);
      b.title = n === 1 ? 'Single pipeline (real data)'
              : n + ' concurrent pipelines (simulated' + (n > 9 ? ', grid layout' : ', stacked tabs') + ')';
      b.addEventListener('click', (ev) => { ev.stopPropagation(); ltSimSet(n); });
      nums.appendChild(b);
    });
    // Position popup just above the button using fixed coords
    const rect = btn.getBoundingClientRect();
    popup.style.left   = rect.right + 'px';
    popup.style.top    = rect.bottom + 8 + 'px';
    // Clamp to viewport
    popup.style.transform = '';
    popup.classList.add('open');
    btn.classList.add('active');

    // Clamp horizontally after render
    requestAnimationFrame(() => {
      const pr = popup.getBoundingClientRect();
      if (pr.right > window.innerWidth - 8) {
        popup.style.left = (rect.right - pr.width) + 'px';
      }
    });

    // Close on outside click
    setTimeout(() => {
      document.addEventListener('click', function _closeSimPopup(ev) {
        const p = document.getElementById('lt-sim-popup');
        const b = document.getElementById('lt-sim-btn');
        if (!p.contains(ev.target) && ev.target !== b) {
          p.classList.remove('open');
          b.classList.remove('active');
          document.removeEventListener('click', _closeSimPopup);
        }
      });
    }, 10);
  } else {
    popup.classList.remove('open');
    btn.classList.remove('active');
  }
}

function ltSimSet(n) {
  _simPipelineCount = n;
  _focusPipelineId  = null;   // reset focus to primary

  // Update button highlight in popup
  document.querySelectorAll('.sim-num').forEach(b => {
    b.classList.toggle('active', Number(b.dataset.n) === n);
  });

  // Update the Test button label to show active count
  const btn = document.getElementById('lt-sim-btn');
  if (n <= 1) {
    btn.textContent = '⚗ Test';
    btn.title = 'Simulate concurrent pipelines';
    _simPipelineCount = 0;
  } else {
    btn.textContent = '⚗ ' + n + '×';
    btn.title = 'Simulating ' + n + ' concurrent pipelines — click to change';
  }

  // Rebuild fake runs and re-render
  if (_simPipelineCount > 1) {
    _buildSimRuns();
  } else {
    // Restore real _allRuns from last API data (trigger a re-poll)
    _allRuns = _allRuns.slice(0, 1);
  }
  renderBoard();

  // Close popup
  document.getElementById('lt-sim-popup').classList.remove('open');
  document.getElementById('lt-sim-btn').classList.remove('active');
}

// Hook into renderBoard to inject simulated runs before painting
const _origRenderBoard = renderBoard;
// Patch: whenever renderBoard is called while simulation is active, inject fake runs first.
// We override the switchPipeline function to also handle sim-run- IDs.
const _origSwitchPipeline = switchPipeline;
window.switchPipeline = function(pid) {
  _origSwitchPipeline(pid);
  if (_simPipelineCount > 1 && pid && pid.startsWith('sim-')) {
    _applySimFocusedRun();
    renderBoard();
  }
};

// Patch renderBoard to rebuild sim runs on every paint (so board changes don't wipe them)
window.renderBoard = function() {
  if (_simPipelineCount > 1) {
    _buildSimRuns();
    if (_focusPipelineId && _focusPipelineId.startsWith('sim-')) {
      _applySimFocusedRun();
    }
  }
  _origRenderBoard();
};

// Wire up sim button (onclick was removed from HTML to avoid header drag interference)
document.addEventListener('DOMContentLoaded', function() {
  const simBtn = document.getElementById('lt-sim-btn');
  if (simBtn) simBtn.addEventListener('click', ltSimToggle);
});
