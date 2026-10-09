#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
test_intro_smoke.py — Intro Pipeline Smoke Test
================================================

Runs the intro pipeline end-to-end: a single short cinematic scene followed
by a studio title card (ending text overlay). Validates that:
  - FLUX generates the scene image
  - WAN produces the video clip
  - ffmpeg title card is appended to the final video
  - VRAM is fully released afterward

What it proves
--------------
  ✅ FLUX produces scene image         → non-trivial PNG file (> 10 KB)
  ✅ WAN produces video clip           → non-empty MP4 file (> 50 KB)
  ✅ Title card appended               → final video duration > 2.5 s
  ✅ Pipeline status = completed        → no stuck/failed stages
  ✅ VRAM returns to baseline           → < 1 GB delta after completion
  ✅ No CUDA out-of-memory errors       → zero OOM lines in pipeline log

Smoke parameters (vs production)
---------------------------------
  Duration            : 0.25 min (15 s → 1 scene)
  WAN inference steps : 1     (vs 20)
  WAN sub-clips/scene : 1     (vs 4)
  WAN frames/clip     : 13    (vs 65)   → 0.75 s clip
  WAN resolution      : 480×272 (vs 832×480)
  Narration           : off   (intro clips are silent)
  Ending text         : "A SMOKE TEST PRODUCTION"

Usage
-----
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  python3 scripts/test_intro_smoke.py

  Optional env vars:
    SMOKE_DIRECTIVE="your scene description"
    SMOKE_ENDING_TEXT="YOUR STUDIO NAME"
"""

import sys
import os
import time
import uuid
import threading
from datetime import datetime
from pathlib import Path

# ── Resolve paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CREWS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(CREWS_DIR))

SEP = '─' * 64
PASS = '✅ PASS'  # noqa: S105  console status marker, not a credential
FAIL = '❌ FAIL'


def _hdr(title: str):
    print(f'\n{SEP}\n  {title}\n{SEP}')


def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Patch WAN inference parameters
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 1 — Patching WAN inference parameters')

from zyg_workflows import wan_video_service as _wan  # noqa: E402

ORIG_WAN = {k: getattr(_wan, k) for k in ('_INFER_STEPS', '_N_CHAINED', '_CLIP_FRAMES', '_WIDTH', '_HEIGHT')}

SMOKE_PARAMS = {
    '_INFER_STEPS': 1,
    '_N_CHAINED': 1,
    '_CLIP_FRAMES': 13,  # 0.75 s @ 17 fps — enough to prove offload
    '_WIDTH': 480,
    '_HEIGHT': 272,
}

for k, v in SMOKE_PARAMS.items():
    setattr(_wan, k, v)

print(f'  {"Parameter":<20} {"Production":>12}  →  {"Smoke":>8}')
print(f'  {"─" * 20} {"─" * 12}     {"─" * 8}')
for k, v in SMOKE_PARAMS.items():
    print(f'  {k:<20} {str(ORIG_WAN[k]):>12}  →  {str(v):>8}')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Import the main module
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 2 — Importing pipeline module (crewai_web_gui.py)')
print(f'  [{_ts()}] Loading… (may take 15–30 s)')
t_import = time.monotonic()

from zyg_dashboard import crewai_web_gui as _gui  # noqa: E402

elapsed_import = time.monotonic() - t_import
print(f'  [{_ts()}] Import complete in {elapsed_import:.1f}s')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — VRAM baseline
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 3 — VRAM baseline')

import torch  # noqa: E402

if not torch.cuda.is_available():
    print('  ❌ CUDA not available — aborting smoke test')
    sys.exit(1)


def _vram() -> tuple[float, float]:
    props = torch.cuda.get_device_properties(0)
    total = props.total_memory
    alloc = torch.cuda.memory_allocated(0)
    return round(alloc / 1024**3, 2), round((total - alloc) / 1024**3, 2)


total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
used0, free0 = _vram()

print(f'  GPU         : {torch.cuda.get_device_name(0)}')
print(f'  Total VRAM  : {total_gb:.1f} GB')
print(f'  Baseline    : used={used0:.2f} GB  free={free0:.2f} GB')

wm = {
    'baseline_used': used0,
    'peak_used': used0,
    'final_used': None,
}


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Run intro pipeline
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 4 — Running intro pipeline in smoke configuration')

DIRECTIVE = os.environ.get('SMOKE_DIRECTIVE', 'a cinematic sweep over a misty mountain at golden hour')
ENDING_TEXT = os.environ.get('SMOKE_ENDING_TEXT', 'A SMOKE TEST PRODUCTION')
DURATION_MIN = 0.25  # 15 s → forced single scene

pipeline_id = f'introsmoke-{uuid.uuid4().hex[:8]}'
stop_event = threading.Event()

print(f'  Pipeline ID  : {pipeline_id}')
print(f'  Directive    : {DIRECTIVE}')
print(f'  Ending text  : {ENDING_TEXT!r}')
print(f'  Duration     : {DURATION_MIN} min ({int(DURATION_MIN * 60)}s → 1 scene)')
print('  Narration    : off (intro clips are silent)')
print(f'  WAN steps    : {_wan._INFER_STEPS}  (production: {ORIG_WAN["_INFER_STEPS"]})')
print()

# ── VRAM monitor thread ────────────────────────────────────────────────────────
_done_flag = threading.Event()
_vram_timeline: list[tuple[float, float, float]] = []
_t_pipeline_start = time.monotonic()


def _monitor_vram():
    while not _done_flag.is_set():
        t_now = time.monotonic() - _t_pipeline_start
        u, f = _vram()
        _vram_timeline.append((round(t_now, 1), u, f))
        if u > wm['peak_used']:
            wm['peak_used'] = u
        _done_flag.wait(timeout=3)


_mon = threading.Thread(target=_monitor_vram, daemon=True, name='introsmoke-vram-monitor')
_mon.start()

# ── Inject job dict ────────────────────────────────────────────────────────────
_gui._workflow_jobs[pipeline_id] = {
    'status': 'running',
    'pipeline_id': pipeline_id,
    'department': 'video',
    'started': datetime.utcnow().isoformat(),
    'current_stage': None,
    'stages': {},
    'stage_timeline': [],
    'result': None,
    'error': None,
    'stop_event': stop_event,
    'image_paths': [],
    'narration_enabled': False,
    'visual_style': 'cinematic',
    'scene_mode': 'independent',
    'ending_text': ENDING_TEXT,
    'debug_events': [],
}

print(f'  [{_ts()}] Pipeline start')
print()

_pipeline_exception = None
t_start = time.monotonic()
try:
    _gui._run_video_pipeline(
        pipeline_id=pipeline_id,
        directive=DIRECTIVE,
        image_paths=[],
        video_duration_minutes=DURATION_MIN,
        narration_enabled=False,
        visual_style='cinematic',
        scene_mode='independent',
        ending_text=ENDING_TEXT,
    )
except Exception as _exc:
    _pipeline_exception = _exc
    print(f'\n  [{_ts()}] ❌ Pipeline raised exception: {_exc}')
finally:
    elapsed_total = time.monotonic() - t_start
    _done_flag.set()
    _mon.join(timeout=5)

wm['final_used'], _ = _vram()
print(f'\n  [{_ts()}] Pipeline finished in {elapsed_total:.0f}s')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Collect evidence
# ══════════════════════════════════════════════════════════════════════════════
job = _gui._workflow_jobs.get(pipeline_id, {})
events = job.get('debug_events', [])
msgs = [ev.get('msg', '') for ev in events]
output_dir = job.get('output_dir', '')
stage_tl = job.get('stage_timeline', [])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Assertions
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 6 — Test assertions')

results: list[tuple[str, str, str]] = []


def _assert(condition: bool, title: str, pass_detail: str, fail_detail: str) -> bool:
    status = PASS if condition else FAIL
    detail = pass_detail if condition else fail_detail
    results.append((status, title, detail))
    return condition


# ── A1: Pipeline completed cleanly ───────────────────────────────────────────
final_status = job.get('status', 'unknown')
_assert(
    final_status in ('done', 'completed'),
    f'Pipeline status = completed  (actual: {final_status})',
    f'All stages completed cleanly (status: {final_status})',
    f"Pipeline ended with status '{final_status}'"
    + (f' — exception: {_pipeline_exception}' if _pipeline_exception else ''),
)

# ── A2: No CUDA OOM errors ────────────────────────────────────────────────────
oom_msgs = [m for m in msgs if 'out of memory' in m.lower() or ('cuda' in m.lower() and 'oom' in m.lower())]
_assert(
    len(oom_msgs) == 0,
    'No CUDA out-of-memory errors',
    'Zero CUDA allocation failures detected',
    f'CUDA OOM still occurring ({len(oom_msgs)} instance(s)): {oom_msgs[0][:100] if oom_msgs else "?"}',
)

# ── A3: FLUX produced real images ────────────────────────────────────────────
flux_images: list[Path] = []
if output_dir and os.path.isdir(output_dir):
    flux_images = sorted(f for f in Path(output_dir).rglob('scene_*.png') if f.stat().st_size > 10_000)
_assert(
    len(flux_images) > 0,
    f'FLUX produced scene image  (found {len(flux_images)} ≥ 10 KB PNG)',
    f'Images: {[f.name for f in flux_images]}',
    f'No substantial PNG files in {output_dir!r} — blank fallback triggered or FLUX stage failed',
)

# ── A4: WAN produced video clip ───────────────────────────────────────────────
wan_clips: list[Path] = []
if output_dir and os.path.isdir(output_dir):
    wan_clips = sorted(f for f in Path(output_dir).glob('*.mp4') if f.stat().st_size > 50_000)
_assert(
    len(wan_clips) > 0,
    f'WAN produced video clip  (found {len(wan_clips)} ≥ 50 KB MP4)',
    f'Clips: {[f.name for f in wan_clips]}',
    f'No substantial MP4 files in {output_dir!r} — WAN failed or was skipped',
)

# ── A5: Ending title card appended (video duration > 2.5 s) ──────────────────
final_video: Path | None = None
title_card_ok = False
tc_detail_pass = ''
tc_detail_fail = ''
if output_dir and os.path.isdir(output_dir):
    mp4s = sorted(Path(output_dir).glob('video_introsmoke-*.mp4'), key=lambda f: f.stat().st_size, reverse=True)
    if not mp4s:
        mp4s = sorted(Path(output_dir).glob('*.mp4'), key=lambda f: f.stat().st_size, reverse=True)
    if mp4s:
        final_video = mp4s[0]

try:
    import subprocess as _sp_tc

    if final_video and final_video.exists():
        _dur_r = _sp_tc.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                str(final_video),
            ],
            capture_output=True,
            timeout=15,
        )
        dur_s = float((_dur_r.stdout or b'0').decode().strip() or '0')
        title_card_ok = dur_s > 2.5
        if title_card_ok:
            tc_detail_pass = f'Final video duration {dur_s:.1f}s (title card adds ≥ 3 s)'
        else:
            tc_detail_fail = (
                f'Final video duration {dur_s:.1f}s — title card may not have been appended (file: {final_video.name})'
            )
    else:
        tc_detail_fail = 'No final video found to probe'
except Exception as _tc_exc:
    tc_detail_fail = f'ffprobe error: {_tc_exc}'

_assert(
    title_card_ok,
    'Ending title card appended  (video duration > 2.5 s)',
    tc_detail_pass,
    tc_detail_fail,
)

# ── A6: VRAM returned to baseline ────────────────────────────────────────────
vram_delta = (wm['final_used'] or 0.0) - wm['baseline_used']
_assert(
    vram_delta < 1.0,
    f'VRAM returned to baseline  (delta: {vram_delta:+.2f} GB)',
    f'All models offloaded — VRAM baseline restored (used: {wm["final_used"]:.2f} GB)',
    f'VRAM leak: {vram_delta:.2f} GB still allocated — a model was not offloaded',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Print report
# ══════════════════════════════════════════════════════════════════════════════
_hdr('RESULTS')

all_pass = all(r[0] == PASS for r in results)

for status, title, detail in results:
    print(f'  {status}  {title}')
    print(f'         → {detail}')
    print()

print(f'  Total elapsed   : {int(elapsed_total // 60)}m {int(elapsed_total % 60)}s')
print(f'  VRAM peak       : {wm["peak_used"]:.2f} GB / {total_gb:.1f} GB  ({wm["peak_used"] / total_gb * 100:.1f}%)')
print(f'  VRAM baseline   : {wm["baseline_used"]:.2f} GB')
print(f'  VRAM final      : {wm["final_used"]:.2f} GB  (delta: {vram_delta:+.2f} GB)')

if stage_tl:
    print()
    print('  Stage timeline:')
    for entry in stage_tl:
        icon = {'completed': '✅', 'failed': '❌', 'running': '🔄'}.get(entry.get('status', ''), '⬜')
        print(f'    {icon}  {entry.get("name", "?"):<40}  {entry.get("status", "?")}')

print()
if all_pass:
    print(f'  🎉  ALL {len(results)} TESTS PASSED — intro pipeline is working correctly')
else:
    n_fail = sum(1 for r in results if r[0] == FAIL)
    print(f'  ⚠️   {n_fail}/{len(results)} TESTS FAILED — see details above')
print(SEP)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Key log lines
# ══════════════════════════════════════════════════════════════════════════════
_hdr('KEY LOG LINES (VRAM / FLUX / WAN / Title Card)')

KEYWORDS = (
    'flux',
    'wan:',
    'stage 2',
    'stage 4',
    'stage 5',
    'controlnet',
    'cuda',
    'oom',
    'vram',
    'title',
    'ending',
    'card',
    'drawtext',
    'loaded',
    'unloaded',
    'free',
    'skipped',
)

for ev in events:
    msg = ev.get('msg', '')
    if any(k in msg.lower() for k in KEYWORDS):
        ts_str = ev.get('ts', '')
        lvl = ev.get('level', 'INFO')
        stage = ev.get('stage', '')
        print(f'  [{ts_str}] [{lvl:<7}] [{stage}] {msg[:110]}')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — VRAM timeline
# ══════════════════════════════════════════════════════════════════════════════
if _vram_timeline:
    _hdr('VRAM TIMELINE (3-second samples)')
    BAR_WIDTH = 40
    for t_s, used, _free in _vram_timeline:
        bar_len = int((used / total_gb) * BAR_WIDTH)
        bar = '█' * bar_len + '░' * (BAR_WIDTH - bar_len)
        print(f'  t+{t_s:>6.1f}s  [{bar}]  {used:>5.2f} / {total_gb:.1f} GB')

print()
sys.exit(0 if all_pass else 1)
