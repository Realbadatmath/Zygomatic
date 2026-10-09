#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
test_documentary_smoke.py — Documentary (Scholarly) Pipeline Smoke Test
========================================================================

Runs the documentary pipeline end-to-end with minimal inference parameters
to verify: essay research, script prep, AI image generation, video assembly,
and VRAM cleanup — all in ~8–12 minutes.

What it proves
--------------
  ✅ A1  Pipeline status = completed       → no stuck/failed stages
  ✅ A2  No CUDA out-of-memory errors      → zero OOM lines in pipeline log
  ✅ A3  Academic research stage completes → essay text collected
  ✅ A4  Script preparation completes      → "Essay ready for narration: N words"
                                             (the Whisper "Alignment: …" line is excluded)
  ✅ A4b Still family that actually ran    → Qwen-Image-2512 via ComfyUI (default) or
                                             in-process FLUX.1-schnell (ZYG_SCHOLARLY_STILL_FAMILY=flux)
  ✅ A5  Stills really rendered            → counted from "ComfyGen: saved …/flux_images/flux_NNN"
                                             events AND from <output>/flux_images/ (kept for smoke
                                             runs); ≥ 1 still, each ≥ 1280×720 (size reported)
  ✅ A6  Video assembled                   → final .mp4 in output dir (> 50 KB)
  ✅ A7  VRAM returns to baseline          → < 1 GB delta (driver-level mem_get_info)
  ✅ A8  Still backend released VRAM       → Qwen: "Pre-Comfy VRAM wait" logged and NO
                                             "Loading FLUX.1-schnell"; FLUX: ≥ 2 GB free after unload
  ✅ A9  ControlNet lifecycle              → FLUX: loaded + unloaded; Qwen: nothing FLUX-side loaded
  ✅ A10 Smoke output quarantined          → out_dir under data/output/smoke or a SMOKE_RUN marker
  ✅ A11 No desktop delivery               → no "Windows Desktop" / "clips →" line (no SFTP)
  ✅ A12 Production GUI survived           → crewai-gui.service active, same MainPID as before
                                             (WARN + skip when systemctl / the unit is unavailable)
  ✅ A13 Run flagged as smoke              → job['smoke'] or pipeline_<id>_state.json "smoke": true

Smoke parameters (vs production)
---------------------------------
  WAN inference steps : 1     (vs 20)   → blurry but exercises load/unload
  WAN sub-clips/scene : 1     (vs 4)    → saves 3× sub-clip time
  WAN frames/clip     : 13    (vs 65)   → 0.75 s clip
  WAN resolution      : 480×272 (vs 832×480)
  Narration           : off   (skips TTS stage entirely for speed)
  Stills              : 3     (vs ~48 production) → exercises the Qwen/Comfy (or FLUX) path only
  Topic               : short human-interest topic → small essay, few images

Environment guards (set with setdefault BEFORE any pipeline module is imported)
-------------------------------------------------------------------------------
  ZYG_SPORTS_SCHEDULER=0  ZYG_MARKET_SCHEDULER=0   → importing crewai_web_gui must not
                                                     start the background schedulers
  ZYG_NO_DELIVERY=1                                → no SFTP of smoke output to the desktop
  ZYG_SMOKE_RUN=1                                  → smoke quarantine (output root + marker)

2026-08-25 (S-02): the previous version proved less than it reported — A5 ran after
Cleanup had deleted flux_images/ and passed on _thumbnail.jpg; A8 passed on a Qwen
run where no in-process FLUX was ever loaded; A4 printed the Whisper alignment line
as its script proof; and the run SIGTERMed the production GUI (P-01) and SFTP'd a
3-still smoke video to the desktop (P-03). Every one of those is now an assertion.

Usage
-----
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  python3 scripts/test_documentary_smoke.py

  Optional env var: SMOKE_TOPIC="your topic"
  Default topic:    "ancient Roman architecture"
"""

import sys
import os
import re as _re
import json
import subprocess
import time
import uuid
import threading
from datetime import datetime
from pathlib import Path
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ── Resolve paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CREWS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(CREWS_DIR))

# ══════════════════════════════════════════════════════════════════════════════
# STEP 0 — Environment guards BEFORE any pipeline module is imported
# ══════════════════════════════════════════════════════════════════════════════
# 2026-08-25 (S-02 / P-01 / P-03): importing crewai_web_gui starts the sports and
# market schedulers (bp_sports / bp_market read their flag AT IMPORT TIME), and a
# finished run SFTPs its output to the Windows desktop. A smoke run must do none
# of that. setdefault → an operator's explicit value still wins.
SMOKE_ENV = {
    'ZYG_SPORTS_SCHEDULER': '0',  # bp_sports: no background fixture scheduler
    'ZYG_MARKET_SCHEDULER': '0',  # bp_market: no background market scheduler
    'ZYG_NO_DELIVERY': '1',  # stage_runner: skip the SFTP delivery to the desktop
    'ZYG_SMOKE_RUN': '1',  # pipeline_scholarly / pipeline_common: smoke quarantine
    'ZYG_KILL_SIBLING_FLASK': '0',  # vram_manager: a smoke run has no reason to SIGTERM any GUI
}
for _env_k, _env_v in SMOKE_ENV.items():
    os.environ.setdefault(_env_k, _env_v)

SEP = '─' * 64
PASS = '✅ PASS'  # noqa: S105  console status marker, not a credential
FAIL = '❌ FAIL'
WARN = '⚠️  WARN'


def _hdr(title: str):
    print(f'\n{SEP}\n  {title}\n{SEP}')


def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Patch WAN inference parameters before crewai_web_gui loads them
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 1 — Patching WAN inference parameters')
print('  Environment guards (STEP 0, setdefault):')
for _env_k in SMOKE_ENV:
    print(f'    {_env_k:<22} = {os.environ.get(_env_k)!r}')
print()

from zyg_workflows import wan_video_service as _wan  # noqa: E402

ORIG_WAN = {k: getattr(_wan, k) for k in ('_INFER_STEPS', '_N_CHAINED', '_CLIP_FRAMES', '_WIDTH', '_HEIGHT')}

SMOKE_PARAMS = {
    '_INFER_STEPS': 1,
    '_N_CHAINED': 1,
    '_CLIP_FRAMES': 13,  # 0.75 s @ 17 fps
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

# Cap FLUX images to 3 for smoke test — avoids generating 79 images (4+ min).
# The cap has to be set on pipeline_scholarly as well: that module does
# `from crewai_web_gui import _SCHOLARLY_SMOKE_MAX_IMAGES`, which binds the
# value at import time, so rebinding it on _gui alone left the pipeline running
# the full production image count while the harness reported a smoke run.
_gui._SCHOLARLY_SMOKE_MAX_IMAGES = 3
from zyg_workflows import pipeline_scholarly as _ps_smoke  # noqa: E402

_ps_smoke._SCHOLARLY_SMOKE_MAX_IMAGES = 3

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
    """Return (used_gb, free_gb) using mem_get_info() — driver-level, includes reserved pool.

    This matches the production _check_vram() fix applied to controlnet_service.py.
    memory_allocated() misses PyTorch's reserved pool, which is exactly the region
    where stranded FLUX tensors live after a broken unload.
    """
    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    used_bytes = total_bytes - free_bytes
    return round(used_bytes / 1024**3, 2), round(free_bytes / 1024**3, 2)


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
# STEP 3b — Production GUI unit state BEFORE the run (P-01 witness for A12)
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 3b — crewai-gui.service state before the run')

GUI_UNIT = 'crewai-gui.service'


def _systemctl_show(prop: str) -> str | None:
    """`systemctl show -p <prop> --value crewai-gui.service`.

    Returns None when systemctl is unavailable or fails (tolerated: A12 becomes a
    WARN + skip). A missing unit still returns '' / '0' / 'inactive' with exit 0."""
    try:
        r = subprocess.run(
            ['systemctl', 'show', '-p', prop, '--value', GUI_UNIT],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


gui_pid_before = _systemctl_show('MainPID')
gui_state_before = _systemctl_show('ActiveState')
if gui_pid_before is None:
    print(f'  {WARN} systemctl unavailable — {GUI_UNIT} cannot be witnessed (A12 will be skipped)')
else:
    print(f'  {GUI_UNIT}: ActiveState={gui_state_before!r} MainPID={gui_pid_before!r}')
    if gui_state_before != 'active' or gui_pid_before in ('', '0'):
        print(f'  {WARN} unit not active before the run — A12 will be skipped')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Run pipeline
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 4 — Running documentary pipeline in smoke configuration')

TOPIC = os.environ.get('SMOKE_TOPIC', 'ancient Roman architecture')
DIRECTIVE = os.environ.get('SMOKE_DIRECTIVE', f'documentary about {TOPIC}')

pipeline_id = f'docsmoke-{uuid.uuid4().hex[:8]}'
stop_event = threading.Event()

print(f'  Pipeline ID  : {pipeline_id}')
print(f'  Topic        : {TOPIC}')
print(f'  Directive    : {DIRECTIVE}')
print('  Narration    : off (TTS skipped for speed)')
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


_mon = threading.Thread(target=_monitor_vram, daemon=True, name='docsmoke-vram-monitor')
_mon.start()

# ── Inject job dict ────────────────────────────────────────────────────────────
_gui._workflow_jobs[pipeline_id] = {
    'status': 'running',
    'pipeline_id': pipeline_id,
    'department': 'scholarly',
    'scholarly_topic': TOPIC,
    'started': datetime.utcnow().isoformat(),
    'current_stage': None,
    'stages': {},
    'stage_timeline': [],
    'result': None,
    'error': None,
    'stop_event': stop_event,
    'narration_enabled': False,
    'visual_style': 'documentary',
    'debug_events': [],
}

print(f'  [{_ts()}] Pipeline start')
print()

_pipeline_exception = None
t_start = time.monotonic()
try:
    _gui._run_scholarly_pipeline(
        pipeline_id=pipeline_id,
        topic=TOPIC,
        directive=DIRECTIVE,
        narration_enabled=False,
        visual_style='documentary',
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


def _warn(title: str, detail: str) -> None:
    """Record a skipped check. WARN rows are printed in RESULTS but never fail the run."""
    results.append((WARN, title, detail))
    print(f'  {WARN}  {title} — {detail}')


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

# ── A3: Academic research produced essay material ────────────────────────────
research_done = any(
    'stage 2: academic research' in (e.get('status', '') + e.get('name', '')).lower() and e.get('status') == 'completed'
    for e in stage_tl
)
essay_msgs = [m for m in msgs if 'combined essay' in m.lower() or 'essay material' in m.lower() or 'chars' in m.lower()]
_assert(
    research_done or bool(essay_msgs),
    'Academic research stage completed',
    f'Essay material collected — {essay_msgs[0][:80] if essay_msgs else "stage_timeline confirmed"}',
    'Research stage did not complete or essay material was empty',
)

# ── A4: Script preparation stage completed ───────────────────────────────────
# 2026-08-25 (S-02): the old keyword test ('script' + 'words') matched the Whisper
# "Alignment: … subtitle words" line and printed THAT as the script proof. The proof
# is the pipeline's own Stage 3 line "Essay ready for narration: N words (LLM: …)".
script_done = any(
    'stage 3: script preparation' in (e.get('status', '') + e.get('name', '')).lower()
    and e.get('status') == 'completed'
    for e in stage_tl
)
_ESSAY_READY_RE = _re.compile(r'essay ready for narration:\s*(\d+)\s*words', _re.I)
script_msgs = [m for m in msgs if 'alignment' not in m.lower() and _ESSAY_READY_RE.search(m)]
script_words = int(_ESSAY_READY_RE.search(script_msgs[-1]).group(1)) if script_msgs else 0
_assert(
    bool(script_msgs) and script_words > 0,
    f'Script preparation stage completed  (essay: {script_words} words)',
    f'Script prepared — {script_msgs[-1][:80] if script_msgs else ""}'
    + ('' if script_done else '  [stage_timeline has no completed Stage 3 entry]'),
    f"No 'Essay ready for narration: N words' line in {len(msgs)} events (stage_timeline completed={script_done})",
)

# ── A4b: the still family that actually rendered ────────────────────────────
# 2026-08-25: Qwen-Image-2512 via ComfyUI is the production default
# (scholarly_stills_backend.scholarly_still_family); FLUX.1-schnell in-process is
# the ZYG_SCHOLARLY_STILL_FAMILY=flux path. Assert the path the run was
# CONFIGURED for, not the 2026-06 default.
from zyg_workflows import scholarly_stills_backend as _ssb_smoke  # noqa: E402

_family = _ssb_smoke.scholarly_still_family()
_inproc_flux = any('loading flux.1-schnell' in m.lower() for m in msgs)
_qwen_path = any('qwen-image path' in m.lower() and 'comfy only' in m.lower() for m in msgs)
_qwen_rendered = any('comfygen (comfy_qwen_txt2img)' in m.lower() for m in msgs)
_qwen_fallback = any('qwen stills requested but unavailable' in m.lower() for m in msgs)
if _family == 'qwen':
    _assert(
        _qwen_path and _qwen_rendered and not _qwen_fallback,
        'Stage 3.5 renders stills on Qwen-Image-2512 via ComfyUI',
        'Qwen-Image path logged and every slot rendered comfy_qwen_txt2img',
        f'qwen_path={_qwen_path} rendered={_qwen_rendered} fell_back={_qwen_fallback} — '
        f'check ZYG_USE_COMFYUI / the 2512 checkpoint',
    )
else:
    _assert(
        _inproc_flux,
        'Stage 3.5 uses in-process FLUX + diffusers LoRA',
        'Loading FLUX.1-schnell logged',
        f'inproc={_inproc_flux} — expected the diffusers documentary path (family={_family})',
    )

# ── A5: stills were really rendered (render events + kept flux_images/) ─────
# 2026-08-25 (S-02): the old rglob ran AFTER Cleanup had deleted flux_images/ and
# passed on _thumbnail.jpg. Now stills are counted from the render events
# ("ComfyGen: saved …/flux_images/flux_NNN.jpg" on the Qwen path, or any message
# naming flux_images/flux_*) AND from the files in <output_dir>/flux_images/ (kept
# for smoke runs), excluding names starting with "_". A real still must be
# ≥ 1280×720 — the 512×288 smoke render left the film-look, thumbnail and ESRGAN
# stages untested (the thumbnail was a 512×288 still on a black 1280×720 canvas).
_STILL_EVENT_RE = _re.compile(r'flux_images/(flux_[^\s/()\[\]]+?\.(?:jpe?g|png))', _re.I)
_still_names_from_events: set[str] = set()
_still_saved_events = 0
for _m in msgs:
    if 'ComfyGen: saved' in _m:
        _still_saved_events += 1
    for _hit in _STILL_EVENT_RE.findall(_m):
        _still_names_from_events.add(_hit)
_n_still_events = max(len(_still_names_from_events), _still_saved_events)

still_files: list[Path] = []
_flux_dir = Path(output_dir) / 'flux_images' if output_dir else None
if _flux_dir is not None and _flux_dir.is_dir():
    still_files = sorted(
        f
        for f in _flux_dir.iterdir()
        if f.is_file()
        and not f.name.startswith('_')
        and f.suffix.lower() in ('.jpg', '.jpeg', '.png')
        and f.stat().st_size > 10_000
    )
n_stills = max(_n_still_events, len(still_files))

_still_dims: list[tuple[str, int, int]] = []
_dims_ok = True
if still_files:
    try:
        from PIL import Image as _PILImg

        for _sf in still_files:
            with _PILImg.open(_sf) as _im:
                _w, _h = _im.size
            _still_dims.append((_sf.name, _w, _h))
            if _w < 1280 or _h < 720:
                _dims_ok = False
    except Exception as _pil_e:
        _dims_ok = False
        _still_dims.append((f'PIL failed: {_pil_e}', 0, 0))
_dims_txt = ', '.join(f'{n} {w}×{h}' for (n, w, h) in _still_dims[:4]) or 'no still files on disk'
_assert(
    n_stills >= 1 and _dims_ok,
    f'Stills really rendered  (events: {_n_still_events}, files: {len(still_files)}, min 1280×720)',
    _dims_txt + ('' if still_files else '  [flux_images/ absent — counted from render events only]'),
    (
        f'No real still: saved-events={_still_saved_events} named={len(_still_names_from_events)} '
        f'files={len(still_files)} in {str(_flux_dir)!r} — render failed or flux_images/ was cleaned'
        if n_stills < 1
        else f'Still below 1280×720: {_dims_txt} — smoke rendered at reduced resolution'
    ),
)

# ── A6: Video assembled (final MP4 in output dir) ────────────────────────────
final_video = job.get('final_output_file', '')
if not final_video and output_dir and os.path.isdir(output_dir):
    mp4s = sorted(f for f in Path(output_dir).glob('*.mp4') if f.stat().st_size > 50_000)
    if mp4s:
        final_video = str(mp4s[0])

final_video_ok = bool(final_video and os.path.exists(final_video) and os.path.getsize(final_video) > 50_000)
_assert(
    final_video_ok,
    'Final video assembled  (MP4 > 50 KB)',
    f'Video: {Path(final_video).name if final_video else "n/a"} ({os.path.getsize(final_video) // 1024} KB)'
    if final_video_ok
    else '',
    f'No final MP4 in {output_dir!r} — assembly stage failed or no clips generated',
)

# ── A7: VRAM returned to baseline ────────────────────────────────────────────
vram_delta = (wm['final_used'] or 0.0) - wm['baseline_used']
_assert(
    vram_delta < 1.0,
    f'VRAM returned to baseline  (delta: {vram_delta:+.2f} GB)',
    f'All models offloaded — VRAM baseline restored (used: {wm["final_used"]:.2f} GB)',
    f'VRAM leak: {vram_delta:.2f} GB still allocated — a model was not offloaded',
)

# ── A8: the still backend released VRAM cleanly (family-aware) ───────────────
# 2026-08-25 (S-02): the old check parsed "VRAM after FLUX unload: X GB free" and
# PASSED on a Qwen run where no in-process FLUX was ever loaded (the line came from
# the deep-unload of an EMPTY cache). On the Qwen family the proof is that Stage 3.5
# waited for Comfy headroom ("Pre-Comfy VRAM wait: ok=… free=… GB") and never loaded
# FLUX.1-schnell in-process. The FLUX family keeps the unload check:
#   before the fix: "VRAM after FLUX unload: 0.9GB free" (gc after empty_cache)
#   after the fix:  "VRAM after FLUX unload: X.XGB free" where X >> 1 (components to CPU first)
_pre_comfy_wait_msgs = [m for m in msgs if 'pre-comfy vram wait' in m.lower()]
_pre_comfy_wait_ok = [m for m in _pre_comfy_wait_msgs if 'ok=true' in m.lower().replace(' ', '')]
_flux_load_msgs = [m for m in msgs if 'loading flux.1-schnell' in m.lower()]
if _family == 'qwen':
    _assert(
        bool(_pre_comfy_wait_ok) and not _flux_load_msgs,
        'Qwen path: Pre-Comfy VRAM wait logged, no in-process FLUX.1-schnell load',
        f'{_pre_comfy_wait_ok[-1][:80] if _pre_comfy_wait_ok else ""}',
        f'pre_comfy_wait ok={len(_pre_comfy_wait_ok)} (any={len(_pre_comfy_wait_msgs)}) '
        f'flux_loads={len(_flux_load_msgs)}'
        + (f' — {_pre_comfy_wait_msgs[-1][:80]}' if _pre_comfy_wait_msgs and not _pre_comfy_wait_ok else '')
        + (f' — {_flux_load_msgs[0][:60]}' if _flux_load_msgs else ''),
    )
else:
    _flux_unload_msgs = [m for m in msgs if 'vram after flux unload' in m.lower()]
    _flux_unload_free_gb = 0.0
    if _flux_unload_msgs:
        _m = _re.search(r'([\d.]+)\s*gb\s*free', _flux_unload_msgs[-1], _re.I)
        if _m:
            _flux_unload_free_gb = float(_m.group(1))
    _assert(
        _flux_unload_free_gb >= 2.0,
        f'FLUX unload freed VRAM cleanly  (free after unload: {_flux_unload_free_gb:.1f} GB)',
        f'FLUX unload fix confirmed — {_flux_unload_free_gb:.1f} GB free after unload (broken state was 0.9 GB)',
        f'FLUX unload BROKEN — only {_flux_unload_free_gb:.1f} GB free after unload (expected ≥ 2 GB)'
        + (f' — log: {_flux_unload_msgs[-1][:80]}' if _flux_unload_msgs else ' — no FLUX unload log line found'),
    )

# ── A9: ControlNet loaded and unloaded cleanly ────────────────────────────────
# Scholarly pipeline loads ControlNet for anatomy shots and should unload it at
# the end of Stage 3.5. A missing unload means ~6.6 GB stays pinned in VRAM.
_cn_loaded = any('controlnet pose conditioning loaded' in m.lower() for m in msgs)
_cn_unloaded = any('controlnet' in m.lower() and 'unloaded' in m.lower() for m in msgs)
if _family == 'qwen':
    # No in-process ControlNet on the Qwen/Comfy path — the check is that
    # nothing FLUX-side was loaded at all.
    _assert(
        not _cn_loaded and not _inproc_flux,
        'No in-process FLUX/ControlNet loaded on the Qwen path',
        'Qwen path left the diffusers stack untouched',
        f'inproc_flux={_inproc_flux} cn_loaded={_cn_loaded} — a FLUX-side load leaked into the Qwen path',
    )
else:
    _assert(
        _cn_loaded and _cn_unloaded,
        'ControlNet loaded + unloaded cleanly',
        'ControlNet lifecycle complete — loaded for anatomy shots, unloaded after Stage 3.5',
        f'ControlNet load={_cn_loaded} unload={_cn_unloaded} — check ControlNet teardown in Stage 3.5',
    )

# ── A10: smoke output is quarantined from production ─────────────────────────
# 2026-08-25 (P-03): docsmoke-/gatecheck- folders sat beside production runs in
# data/output/clips (28 of them, ≈4 GB) and were picked up by the Videos tab, the
# SFTP delivery and every scanner. Contract: pipeline_common.smoke_output_root()
# (= <data>/output/smoke) and a SMOKE_MARKER_FILE ("SMOKE_RUN") inside the run dir.
from zyg_workflows import pipeline_common as _pc_smoke  # noqa: E402

_smoke_root_fn = getattr(_pc_smoke, 'smoke_output_root', None)
try:
    _smoke_root = str(_smoke_root_fn()) if _smoke_root_fn else os.path.join(_gui.DATA_DIR, 'output', 'smoke')
except Exception:
    _smoke_root = os.path.join(_gui.DATA_DIR, 'output', 'smoke')
_smoke_marker_name = str(getattr(_pc_smoke, 'SMOKE_MARKER_FILE', 'SMOKE_RUN'))
_out_real = os.path.realpath(output_dir) if output_dir else ''
_root_real = os.path.realpath(_smoke_root)
_under_smoke_root = bool(_out_real) and (_out_real == _root_real or _out_real.startswith(_root_real + os.sep))
_marker_present = bool(output_dir) and os.path.isfile(os.path.join(output_dir, _smoke_marker_name))
_assert(
    _under_smoke_root or _marker_present,
    f'Smoke output quarantined  (under {os.path.relpath(_smoke_root, CREWS_DIR)} or {_smoke_marker_name} marker)',
    (f'under {_smoke_root}' if _under_smoke_root else f'marker {_smoke_marker_name} present') + f' — {output_dir}',
    f'output_dir={output_dir!r} is neither under {_smoke_root} nor carries a {_smoke_marker_name} '
    f'marker — this run sits beside production episodes',
)

# ── A11: nothing was delivered to the Windows desktop ────────────────────────
# 2026-08-25 (P-03): the previous smoke SFTP'd its 3-still video to
# "Desktop/zygomatic output/…" — stage_runner._scp_output_to_windows had no smoke
# filter. Its "📤 N clips → Windows Desktop: …" line is written via _agent_log (NOT
# the job's debug_events), so BOTH sinks are checked: the job events and this run's
# entries in data/runtime/clipfarm_processing_log.json. WAN's "stitched N sub-clips →"
# line also contains "clips →" and is excluded explicitly.
_DELIVERY_MARKS = ('Windows Desktop', 'clips →')


def _is_delivery_line(text: str) -> bool:
    return 'sub-clips' not in text and any(k in text for k in _DELIVERY_MARKS)


_delivery_hits = [m for m in msgs if _is_delivery_line(m)]
_agent_log_hits: list[str] = []
# Positive witness: stage_runner._scp_output_to_windows logs this line when it
# refuses a test run. Absence of the success line alone would also pass on an
# ATTEMPTED-but-failed delivery ([SFTP ERROR] carries neither marker).
_SKIP_MARK = 'Desktop delivery skipped'
_skip_hits: list[str] = []
try:
    with open(_gui._runtime_path('clipfarm_processing_log.json'), encoding='utf-8') as _alf:
        for _e in json.load(_alf):
            if _e.get('pipeline_id') != pipeline_id:
                continue
            _e_msg = str(_e.get('message', ''))
            if _is_delivery_line(_e_msg):
                _agent_log_hits.append(_e_msg)
            if _SKIP_MARK in _e_msg:
                _skip_hits.append(_e_msg)
except Exception as _exc:
    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
_assert(
    not _delivery_hits and not _agent_log_hits and bool(_skip_hits),
    'No SFTP delivery to the Windows desktop (delivery explicitly skipped)',
    f"No 'Windows Desktop' / 'clips →' line in {len(msgs)} events; "
    f'agent log says: {_skip_hits[0][:80] if _skip_hits else ""}',
    (
        f'Delivery happened ({len(_delivery_hits)} event / {len(_agent_log_hits)} agent-log hit(s)): '
        f'{(_delivery_hits + _agent_log_hits)[0][:100]}'
    )
    if (_delivery_hits or _agent_log_hits)
    else f"No '{_SKIP_MARK}' line for {pipeline_id} in the agent log — delivery was never refused",
)

# ── A12: the production GUI survived the run (P-01) ──────────────────────────
# vram_manager._stop_secondary_flask_dashboards used to `pgrep -f crewai_web_gui.py`
# and SIGTERM everything but itself — from a standalone smoke the systemd unit was
# "secondary" and went down for 2–4 minutes on every docsmoke-/gatecheck- run.
gui_pid_after = _systemctl_show('MainPID')
gui_state_after = _systemctl_show('ActiveState')
if gui_pid_before is None or gui_pid_after is None:
    _warn('Production GUI survived the run (A12) — skipped', 'systemctl unavailable, the unit cannot be witnessed')
elif gui_state_before != 'active' or gui_pid_before in ('', '0'):
    _warn(
        'Production GUI survived the run (A12) — skipped',
        f'{GUI_UNIT} was not active before the run (state={gui_state_before!r}, MainPID={gui_pid_before!r})',
    )
else:
    _assert(
        gui_state_after == 'active' and gui_pid_after == gui_pid_before,
        f'Production GUI survived the run  ({GUI_UNIT} MainPID {gui_pid_before})',
        f'{GUI_UNIT} still active with the same MainPID {gui_pid_after}',
        f'{GUI_UNIT} state={gui_state_after!r} MainPID {gui_pid_before}→{gui_pid_after} — '
        f'the run killed or restarted the production GUI',
    )

# ── A13: the run is flagged as smoke (job + persisted state) ─────────────────
# Contract: pipeline_scholarly sets job['smoke'] = True and pipeline_state['smoke']
# = True for smoke runs; the state file is data/runtime/pipeline_<id>_state.json.
_job_smoke = bool(job.get('smoke'))
_state_smoke = False
_state_path = _gui._runtime_path(f'pipeline_{pipeline_id}_state.json')
try:
    with open(_state_path, encoding='utf-8') as _stf:
        _state_smoke = json.load(_stf).get('smoke') is True
except Exception as _exc:
    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
_assert(
    _job_smoke or _state_smoke,
    "Run flagged as smoke  (job['smoke'] / pipeline_state['smoke'])",
    f'job.smoke={_job_smoke} state.smoke={_state_smoke}',
    f'job.smoke={_job_smoke} state.smoke={_state_smoke} ({os.path.basename(_state_path)}) — '
    f'the pipeline did not mark this run as smoke',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Print report
# ══════════════════════════════════════════════════════════════════════════════
_hdr('RESULTS')

# WARN rows (a skipped check, e.g. A12 without systemctl) never fail the run.
all_pass = all(r[0] != FAIL for r in results)

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
        print(f'    {icon}  {entry.get("name", "?"):<45}  {entry.get("status", "?")}')

print()
if all_pass:
    n_warn = sum(1 for r in results if r[0] == WARN)
    print(
        f'  🎉  ALL {len(results) - n_warn} TESTS PASSED — documentary pipeline is working correctly'
        + (f'  ({n_warn} check(s) skipped with WARN)' if n_warn else '')
    )
else:
    n_fail = sum(1 for r in results if r[0] == FAIL)
    print(f'  ⚠️   {n_fail}/{len(results)} TESTS FAILED — see details above')
print(SEP)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Key log lines
# ══════════════════════════════════════════════════════════════════════════════
_hdr('KEY LOG LINES (VRAM / Qwen-Comfy / FLUX / WAN / Script / Quarantine)')

# 2026-08-25: Qwen-Image-2512 via ComfyUI is the default still path — its lines
# say "ComfyGen", "Qwen-Image path", "Pre-Comfy VRAM wait"; the P-01 fix logs
# "protected: PID …"; P-03 logs the smoke quarantine and any (forbidden) delivery.
KEYWORDS = (
    'flux',
    'wan:',
    'stage 2',
    'stage 3',
    'stage 4',
    'stage 5',
    'stage 6',
    'controlnet',
    'cuda',
    'oom',
    'vram',
    'essay',
    'script',
    'video',
    'loaded',
    'unloaded',
    'free',
    'skipped',
    'assembled',
    'assembly',
    'qwen',
    'comfy',
    'still',
    'smoke',
    'protected',
    'secondary flask',
    'interrupt',
    'sftp',
    'windows desktop',
    'cleanup',
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
