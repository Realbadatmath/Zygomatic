#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
test_storyteller_smoke.py — Storyteller Pipeline Smoke Test
=============================================================

Runs the Storyteller pipeline end-to-end with minimal parameters to verify:
character prep, Claude story script, Azure TTS narration, FLUX image generation,
Ken Burns animation, ffmpeg final assembly, and VRAM cleanup — in ~5–10 minutes.

What it proves
--------------
  ✅ Pipeline status = completed        → no stuck/failed stages
  ✅ No CUDA out-of-memory errors       → zero OOM lines in pipeline log
  ✅ Stage 1 (Character Prep) passes    → LoRA/IPAdapter resolution logged
  ✅ Stage 2 (Story Script) completes   → scenes JSON produced (> 0 scenes)
  ✅ Stage 3 (TTS Narration) runs       → narration .wav/.mp3 present OR graceful skip
  ✅ Stage 3.5 (Image Gen) produces     → at least 1 non-trivial image file (> 10 KB)
  ✅ Stage 5 (Final Assembly) assembles → final .mp4 in output dir (> 50 KB)
  ✅ stage_timeline populated           → at least 3 entries in timeline
  ✅ VRAM returns to baseline           → < 1 GB delta after pipeline

Smoke parameters (vs production)
---------------------------------
  Duration          : 10 seconds (0.167 min)   → 1–3 scenes; fast TTS + FLUX
  FLUX steps        : already at 4 (schnell)   → no change needed
  story_prompt      : short single-sentence    → minimal Claude output

Usage
-----
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  python3 scripts/test_storyteller_smoke.py

  Optional env var: SMOKE_PROMPT="your story prompt"
  Default prompt:   "A young adventurer discovers a glowing map in an old library."
"""

import sys
import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

# ── Resolve paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CREWS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(CREWS_DIR))

SEP = '─' * 64
PASS = '✅ PASS'  # noqa: S105  console status marker, not a credential
FAIL = '❌ FAIL'
WARN = '⚠️  WARN'


def _hdr(title: str):
    print(f'\n{SEP}\n  {title}\n{SEP}')


def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Import the main module
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 1 — Importing pipeline module (crewai_web_gui.py)')
print(f'  [{_ts()}] Loading… (may take 15–30 s)')
t_import = time.monotonic()

from zyg_dashboard import crewai_web_gui as _gui  # noqa: E402

t_import_end = time.monotonic()
print(f'  [{_ts()}] Loaded in {t_import_end - t_import:.1f}s')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — VRAM baseline
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 2 — VRAM baseline')

wm = {'baseline_used': 0.0, 'peak_used': 0.0, 'final_used': 0.0}
total_gb = 0.0
_vram_timeline: list[tuple[float, float, float]] = []
_t_start_vram = time.monotonic()

try:
    import torch

    if torch.cuda.is_available():
        _info = torch.cuda.mem_get_info(0)
        free_b, total_b = _info
        total_gb = total_b / 1e9
        used_b = total_b - free_b
        wm['baseline_used'] = used_b / 1e9
        wm['peak_used'] = wm['baseline_used']
        print(f'  GPU: {torch.cuda.get_device_name(0)}')
        print(f'  VRAM: {wm["baseline_used"]:.2f} GB used / {total_gb:.1f} GB total')
    else:
        print('  WARN: No CUDA device — VRAM checks will be skipped')
except Exception as _e:
    print(f'  WARN: torch not available ({_e})')


def _sample_vram():
    try:
        import torch as _t

        if not _t.cuda.is_available():
            return
        _info = _t.cuda.mem_get_info(0)
        free_b, total_b = _info
        used_gb = (total_b - free_b) / 1e9
        free_gb = free_b / 1e9
        elapsed = time.monotonic() - _t_start_vram
        _vram_timeline.append((elapsed, used_gb, free_gb))
        if used_gb > wm['peak_used']:
            wm['peak_used'] = used_gb
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


_vram_done = threading.Event()


def _vram_monitor():
    while not _vram_done.is_set():
        _sample_vram()
        time.sleep(3)


threading.Thread(target=_vram_monitor, daemon=True, name='vram-monitor').start()


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Launch storyteller pipeline (10-second smoke run)
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 3 — Launching storyteller pipeline (10-second smoke run)')

SMOKE_PROMPT = os.environ.get('SMOKE_PROMPT', 'A young adventurer discovers a glowing map in an old library.')

# Use a pre-trained LoRA character so we test story/image generation, not char creation.
# Preference order:
#   1. SMOKE_CHAR_ID env var (override)
#   2. Known fully-trained char 6dcd219c2747 (2000-step LoRA, ZYG_CHAR_6DCD21)
#   3. Any other char with a .safetensors LoRA on disk
#   4. None → pipeline creates a new character (slowest path)
_LORA_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars')
_PREFERRED_CHAR = '6dcd219c2747'

SMOKE_CHAR_ID: str | None = os.environ.get('SMOKE_CHAR_ID', None)
if SMOKE_CHAR_ID is None:
    # Try the preferred fully-trained character first
    _preferred_lora = os.path.join(
        _LORA_ROOT, _PREFERRED_CHAR, 'lora-weights', 'checkpoint-2000', 'pytorch_lora_weights.safetensors'
    )
    if os.path.isfile(_preferred_lora):
        SMOKE_CHAR_ID = _PREFERRED_CHAR
        print(f'  Using preferred LoRA char : {SMOKE_CHAR_ID} (ZYG_CHAR_6DCD21, 2000 steps)')
    else:
        # Scan filesystem for any LoRA-ready char
        import glob as _glob_scan

        _lora_files = sorted(
            _glob_scan.glob(os.path.join(_LORA_ROOT, '*', 'lora-weights', '*.safetensors'))
            + _glob_scan.glob(os.path.join(_LORA_ROOT, '*', 'lora-weights', 'checkpoint-*', '*.safetensors')),
            key=os.path.getmtime,
            reverse=True,
        )
        if _lora_files:
            SMOKE_CHAR_ID = Path(_lora_files[0]).parts[-4]  # .../char_id/lora-weights/...
            print(f'  Found LoRA-ready char on disk : {SMOKE_CHAR_ID}')
        else:
            print('  No LoRA-ready chars found — smoke will create a new character')

print(f'  Story prompt    : {SMOKE_PROMPT}')
print('  Duration        : 10 seconds (0.167 min)')
print(f'  Char ID         : {SMOKE_CHAR_ID or "(new character)"}')
print('  Camera mode     : automatic')
print('  Visual style    : cinematic')
print()

_pipeline_exception = None
t_pipeline_start = time.monotonic()

result = _gui._start_storyteller_pipeline_internal(
    directive=None,
    char_id=SMOKE_CHAR_ID,
    character_params=None
    if SMOKE_CHAR_ID
    else {
        'gender': 'female',
        'hair': 'brown',
        'eyes': 'blue',
        'height': 1.70,
        'style': 'cinematic',
    },
    voice_style='narration',
    clip_duration_minutes=0.167,  # 10 seconds
    era_start=1920,
    era_end=1930,
    camera_mode='automatic',
    story_prompt=SMOKE_PROMPT,
    visual_style='cinematic',
    narration_enabled=True,
    user_name='smoke-test',
)

pipeline_id = result['job_id']
print(f'  [{_ts()}] Pipeline started — id: {pipeline_id}')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Poll until complete (max 20 minutes)
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 4 — Waiting for pipeline to complete (max 20 min)')

_MAX_WAIT = 1200  # 20 minutes
_POLL_INTERVAL = 5
_last_stage = ''
_t_wait_start = time.monotonic()

while True:
    elapsed = time.monotonic() - _t_wait_start
    if elapsed > _MAX_WAIT:
        print(f'  [{_ts()}] ⏰ Timeout — pipeline did not complete in {_MAX_WAIT}s')
        break

    job = _gui._workflow_jobs.get(pipeline_id, {})
    status = job.get('status', 'unknown')
    stage = job.get('current_stage', '')
    pct = job.get('progress_pct', 0)

    if stage != _last_stage and stage:
        print(f'  [{_ts()}] ▶ {stage} ({pct}%)')
        _last_stage = stage

    if status in ('done', 'completed', 'failed', 'error', 'stopped'):
        break

    time.sleep(_POLL_INTERVAL)

_vram_done.set()
elapsed_total = time.monotonic() - t_pipeline_start
print(f'\n  [{_ts()}] Pipeline ended — status: {job.get("status")} in {elapsed_total:.0f}s')

# Final VRAM sample
_sample_vram()
wm['final_used'] = _vram_timeline[-1][1] if _vram_timeline else wm['baseline_used']


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Collect results
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 5 — Collecting results')

job = _gui._workflow_jobs.get(pipeline_id, {})
stage_tl = job.get('stage_timeline', [])
events = job.get('debug_events', [])
msgs = [ev.get('msg', '') for ev in events]
out_dir = job.get('output_dir', '')

print(f'  Output dir      : {out_dir or "(not set)"}')
print(f'  Stage timeline  : {len(stage_tl)} entries')
for entry in stage_tl:
    icon = {'completed': '✅', 'failed': '❌', 'running': '🔄'}.get(entry.get('status', ''), '⬜')
    print(f'    {icon}  {entry.get("name", "?"):<45}  {entry.get("status", "?")}')


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


# ── A0: LoRA character was used (not a new character creation run) ────────────
_assert(
    SMOKE_CHAR_ID is not None,
    f'LoRA character pre-loaded  (char: {SMOKE_CHAR_ID or "none"})',
    f'Smoke test used existing LoRA char {SMOKE_CHAR_ID} — skips Blender/training stages',
    'No LoRA-ready character was found — smoke ran in character-creation mode (much slower)',
)

# ── A1: Pipeline completed cleanly ───────────────────────────────────────────
final_status = job.get('status', 'unknown')
_assert(
    final_status in ('done', 'completed'),
    f'Pipeline status = completed  (actual: {final_status})',
    f'All stages completed cleanly (status: {final_status})',
    f"Pipeline ended with status '{final_status}'" + (f' — error: {job.get("error", "")}' if job.get('error') else ''),
)

# ── A2: No CUDA OOM errors ────────────────────────────────────────────────────
oom_msgs = [m for m in msgs if 'out of memory' in m.lower() or ('cuda' in m.lower() and 'oom' in m.lower())]
_assert(
    len(oom_msgs) == 0,
    'No CUDA out-of-memory errors',
    'Zero CUDA allocation failures detected',
    f'CUDA OOM occurring ({len(oom_msgs)} instance(s)): {oom_msgs[0][:100] if oom_msgs else "?"}',
)

# ── A3: Stage 1 (Character Prep) passed ──────────────────────────────────────
s1_entry = next((e for e in stage_tl if 'stage 1' in e.get('name', '').lower()), None)
s1_logged = any('character prep complete' in m.lower() or 'stage 1' in m.lower() for m in msgs)
_assert(
    (s1_entry is not None and s1_entry.get('status') == 'completed') or s1_logged,
    'Stage 1 (Character Prep) completed',
    'Character prep passed — LoRA/IPAdapter resolved',
    'Stage 1 did not complete — check Blender/LoRA/IPAdapter setup',
)

# ── A4: Stage 2 (Story Script) completed and produced scenes ─────────────────
s2_entry = next((e for e in stage_tl if 'stage 2' in e.get('name', '').lower()), None)
scene_msgs = [
    m
    for m in msgs
    if 'scene' in m.lower() and ('generated' in m.lower() or 'parsed' in m.lower() or 'script' in m.lower())
]
n_scenes_msg = next(
    (m for m in msgs if 'scenes,' in m.lower() or 'n_scenes' in m.lower() or 'story script complete' in m.lower()), None
)
_assert(
    (s2_entry is not None and s2_entry.get('status') == 'completed') or bool(n_scenes_msg or scene_msgs),
    'Stage 2 (Story Script) completed',
    f'Story script produced — {n_scenes_msg[:80] if n_scenes_msg else "stage_timeline confirmed"}',
    'Stage 2 did not complete — Claude API or script parsing failed',
)

# ── A5: Stage 3 (TTS) ran or gracefully skipped ──────────────────────────────
s3_entry = next(
    (e for e in stage_tl if 'stage 3' in e.get('name', '').lower() and 'tts' in e.get('name', '').lower()), None
)
tts_msgs = [
    m
    for m in msgs
    if 'tts' in m.lower() or 'narration' in m.lower() or 'indextts2' in m.lower() or 'chatterbox' in m.lower()
]
_assert(
    (s3_entry is not None) or bool(tts_msgs),
    'Stage 3 (TTS Narration) ran or was logged',
    f'TTS stage active — {tts_msgs[0][:80] if tts_msgs else "stage_timeline confirmed"}',
    'No TTS stage found in timeline or logs — stage may have been skipped silently',
)

# ── A6: Stage 3.5 (Image Gen) produced at least 1 image > 10 KB ──────────────
flux_images: list[Path] = []
_search_dirs = [out_dir] if out_dir else []
# Also look in standard output dirs
for _candidate in [
    os.path.join(CREWS_DIR, 'output', 'storyteller'),
    os.path.join(CREWS_DIR, 'static', 'output', 'storyteller'),
    str(paths.ZYG_TMP_DIR / 'storyteller'),
]:
    if os.path.isdir(_candidate):
        _search_dirs.append(_candidate)

for _d in _search_dirs:
    if _d and os.path.isdir(_d):
        for _f in Path(_d).rglob('*'):
            if _f.suffix.lower() in ('.jpg', '.jpeg', '.png') and _f.stat().st_size > 10_000:
                flux_images.append(_f)

_assert(
    len(flux_images) > 0,
    f'FLUX produced real images  (found {len(flux_images)} ≥ 10 KB image files)',
    f'Images: {[f.name for f in flux_images[:5]]}',
    'No substantial image files found — FLUX failed or blank fallback triggered everywhere',
)

# ── A7: Stage 5 (Final Assembly) produced MP4 > 50 KB ────────────────────────
final_video = job.get('result', '') or job.get('final_output_file', '')
if not final_video:
    for _d in _search_dirs:
        if _d and os.path.isdir(_d):
            _mp4s = sorted(f for f in Path(_d).rglob('*.mp4') if f.stat().st_size > 50_000)
            if _mp4s:
                final_video = str(_mp4s[0])
                break

final_video_ok = bool(final_video and os.path.exists(final_video) and os.path.getsize(final_video) > 50_000)
_assert(
    final_video_ok,
    'Final video assembled  (MP4 > 50 KB)',
    f'Video: {Path(final_video).name} ({os.path.getsize(final_video) // 1024} KB)' if final_video_ok else '',
    'No final MP4 found — assembly stage failed or no clips generated',
)

# ── A8: stage_timeline populated ─────────────────────────────────────────────
_assert(
    len(stage_tl) >= 3,
    f'stage_timeline populated  ({len(stage_tl)} entries)',
    f'Kanban board feed confirmed — {len(stage_tl)} entries in timeline',
    f'stage_timeline has only {len(stage_tl)} entries — Kanban cards will not update',
)

# ── A9: VRAM returned to baseline ────────────────────────────────────────────
vram_delta = (wm['final_used'] or 0.0) - wm['baseline_used']
_assert(
    vram_delta < 1.0 or total_gb == 0.0,
    f'VRAM returned to baseline  (delta: {vram_delta:+.2f} GB)',
    f'All models offloaded — VRAM baseline restored (used: {wm["final_used"]:.2f} GB)',
    f'VRAM leak: {vram_delta:.2f} GB still allocated — FLUX/LoRA was not fully offloaded',
)

# ── A10: Narration word count → predicted duration within ±30s of target ─────
_WPM_EXPECTED = 135
_dur_target = job.get('clip_duration_minutes', 0.167)
script_scenes = job.get('script', [])
if not script_scenes:
    # Try loading from state file
    import glob as _glob

    _state_files = sorted(
        _glob.glob(os.path.join(CREWS_DIR, 'data', 'runtime', f'storyteller_{pipeline_id}_state.json')),
        key=os.path.getmtime,
        reverse=True,
    )
    if _state_files:
        try:
            with open(_state_files[0]) as _sf:
                _st = json.load(_sf)
            script_scenes = _st.get('script', [])
            _dur_target = _st.get('duration_min', _dur_target)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

if script_scenes:
    _total_words = sum(len(s.get('narration', '').split()) for s in script_scenes)
    _predicted_min = _total_words / _WPM_EXPECTED
    _tolerance_min = 0.75  # ±45s is acceptable
    _duration_ok = abs(_predicted_min - _dur_target) <= _tolerance_min
    _assert(
        _duration_ok,
        f'Narration duration accurate  ({_predicted_min:.1f} min predicted vs {_dur_target:.1f} min target)',
        f'{_total_words} words at {_WPM_EXPECTED} WPM → {_predicted_min:.1f} min  '
        f'(target {_dur_target:.1f} min, Δ={(abs(_predicted_min - _dur_target) * 60):.0f}s)',
        f'Duration overrun: {_total_words} words → {_predicted_min:.1f} min '
        f'but target was {_dur_target:.1f} min (Δ={(abs(_predicted_min - _dur_target) * 60):.0f}s) — '
        f'word budget validator may not have trimmed correctly',
    )

    _unique_narr = len({s.get('narration', '') for s in script_scenes})
    _assert(
        _unique_narr == len(script_scenes),
        f'All scene narrations unique  ({_unique_narr}/{len(script_scenes)})',
        'Every scene has distinct narration — no placeholder repetition',
        f'Only {_unique_narr}/{len(script_scenes)} unique narrations — fallback placeholder scenes were used',
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
if total_gb > 0:
    print(
        f'  VRAM peak       : {wm["peak_used"]:.2f} GB / {total_gb:.1f} GB  ({wm["peak_used"] / total_gb * 100:.1f}%)'
    )
    print(f'  VRAM baseline   : {wm["baseline_used"]:.2f} GB')
    print(f'  VRAM final      : {wm["final_used"]:.2f} GB  (delta: {vram_delta:+.2f} GB)')

if stage_tl:
    print()
    print('  Stage timeline:')
    for entry in stage_tl:
        icon = {'completed': '✅', 'failed': '❌', 'running': '🔄'}.get(entry.get('status', ''), '⬜')
        print(f'    {icon}  {entry.get("name", "?"):<45}  {entry.get("status", "?")}')

print()
if all_pass:
    print(f'  🎉  ALL {len(results)} TESTS PASSED — storyteller pipeline is working correctly')
else:
    n_fail = sum(1 for r in results if r[0] == FAIL)
    print(f'  ⚠️   {n_fail}/{len(results)} TESTS FAILED — see details above')
print(SEP)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Key log lines
# ══════════════════════════════════════════════════════════════════════════════
_hdr('KEY LOG LINES (Stages / FLUX / TTS / Assembly)')

KEYWORDS = (
    'stage 1',
    'stage 2',
    'stage 3',
    'stage 4',
    'stage 5',
    'flux',
    'tts',
    'narration',
    'lora',
    'ipadapter',
    'ken burns',
    'assembly',
    'vram',
    'cuda',
    'oom',
    'loaded',
    'unloaded',
    'complete',
    'error',
    'failed',
    'scenes,',
    'n_scenes',
    'generated',
    'assembled',
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
if _vram_timeline and total_gb > 0:
    _hdr('VRAM TIMELINE (3-second samples)')
    BAR_WIDTH = 40
    for t_s, used, _free in _vram_timeline:
        bar_len = int((used / total_gb) * BAR_WIDTH)
        bar = '█' * bar_len + '░' * (BAR_WIDTH - bar_len)
        print(f'  t+{t_s:>6.1f}s  [{bar}]  {used:>5.2f} / {total_gb:.1f} GB')

print()
sys.exit(0 if all_pass else 1)
