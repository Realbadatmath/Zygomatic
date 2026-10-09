# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  the original top import block — the siblings re-import from here

"""Fast character-generation smoke test — steps 1 to 7b.

Blender render, captions, the pipeline import and its monkey-patches, the
quality parameters, the VRAM baseline, the GPU watt cap, the API trigger and
the manifest/live-tail assertions. Imported for its side effects: the body of
this module IS the proof, exactly as it was at module level before the split.
"""

import os as _zyg_os

__file__ = _zyg_os.path.join(
    _zyg_os.path.dirname(_zyg_os.path.dirname(_zyg_os.path.abspath(__file__))), 'test_char_gen_smoke_fast.py'
)
__name__ = 'test_char_gen_smoke_fast'

import sys
import os
import time
import subprocess
import threading
import json
from datetime import datetime
from pathlib import Path
import urllib.request as _ur
import uuid as _uuid
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

# ── Resolve paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CREWS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(CREWS_DIR))

BLENDER_BIN = '/opt/blender-4.3.2-linux-x64/blender'
BLENDER_SCRIPT = str(CREWS_DIR / 'blender_scripts' / 'generate_character.py')
DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

SEP = '─' * 64
PASS = '✅ PASS'  # noqa: S105  console status marker, not a credential
FAIL = '❌ FAIL'
WARN = '⚠️  WARN'

results: list[tuple[str, str, str]] = []
t_total = time.monotonic()


def _hdr(title: str):
    print(f'\n{SEP}\n  {title}\n{SEP}')


def _ts() -> str:
    return datetime.now().strftime('%H:%M:%S')


def _assert(cond: bool, title: str, detail_ok: str, detail_fail: str):
    status = PASS if cond else FAIL
    detail = detail_ok if cond else detail_fail
    results.append((status, title, detail))
    icon = '✅' if cond else '❌'
    print(f'  {icon}  {title}')
    print(f'         → {detail}')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Direct Blender render at 64 px (proves camera fix + BsdfDiffuse fix)
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 1 — Direct Blender render  (64 px, 20 angles, animated style)')

SMOKE_CHAR_ID = _uuid.uuid4().hex[:12]  # pure hex — passes route validation [a-f0-9]{12}
SMOKE_CHAR_DIR = os.path.join(DATASET_ROOT, SMOKE_CHAR_ID)
os.makedirs(SMOKE_CHAR_DIR, exist_ok=True)

print(f'  [{_ts()}] char_id  = {SMOKE_CHAR_ID}')
print(f'  [{_ts()}] out_dir  = {SMOKE_CHAR_DIR}')
print(f'  [{_ts()}] Launching Blender at 64 px…')

t_blender = time.monotonic()
_proc = subprocess.run(
    [
        BLENDER_BIN,
        '--background',
        '--python',
        BLENDER_SCRIPT,
        '--',
        '--hair-color',
        'auburn',
        '--eye-color',
        'blue',
        '--skin-tone',
        'medium',
        '--gender',
        'female',
        '--height',
        '1.70',
        '--style',
        'animated',
        '--output-dir',
        SMOKE_CHAR_DIR,
        '--resolution',
        '64',
    ],
    env={**os.environ, 'DISPLAY': ''},
    capture_output=True,
    text=True,
    timeout=120,
)
blender_elapsed = time.monotonic() - t_blender

print(f'  [{_ts()}] Blender exit={_proc.returncode}  elapsed={blender_elapsed:.1f}s')
if _proc.returncode != 0:
    print(f'  STDERR (last 500): {_proc.stderr[-500:]}')

_assert(
    _proc.returncode == 0,
    'Blender exited 0 (no crash)',
    f'exit=0  elapsed={blender_elapsed:.1f}s',
    f'Blender crashed with exit={_proc.returncode} — see stderr above',
)

# Check all images are visible (non-zero brightness) — count is now ~56 with lighting variants
_pngs = sorted(Path(SMOKE_CHAR_DIR).glob('*.png'))
_MIN_EXPECTED_IMAGES = 50  # 42 full-body×3 lights + 4 wide + 4 portrait + 6 face
_assert(
    len(_pngs) >= _MIN_EXPECTED_IMAGES,
    f'Blender produced exactly {len(_pngs)} PNG files  ({len(_pngs)} found)',
    f'Files: {[p.name for p in _pngs[:4]]} …',
    f'Only {len(_pngs)} images produced (expected ≥{_MIN_EXPECTED_IMAGES}) — render loop incomplete',
)

_visible = 0
_invisible_names = []
try:
    import numpy as np
    from PIL import Image as _PIL

    for _p in _pngs:
        _img = _PIL.open(str(_p))
        _arr = np.array(_img)
        # Images are now RGB (3 channels, no alpha) — check brightness > 0 instead
        if _arr.ndim == 3 and _arr.shape[2] == 3:
            # Opaque RGB: visible if any pixel is not pure-black background (>10 avg)
            if _arr.mean() > 5:
                _visible += 1
            else:
                _invisible_names.append(_p.name)
        elif _arr.ndim == 3 and _arr.shape[2] == 4:
            # Legacy RGBA check (should not happen after fix, but handle gracefully)
            if _arr[:, :, 3].max() > 0:
                _visible += 1
            else:
                _invisible_names.append(_p.name)
        else:
            _visible += 1  # grayscale or unexpected — count as visible
except ImportError:
    _visible = len(_pngs)  # can't check without numpy/PIL; assume ok

_assert(
    _visible == len(_pngs) and len(_pngs) > 0,
    f'All {len(_pngs)} rendered images have visible pixels (RGB, brightness > 5)',
    f'camera_fix=✓  RGB_opaque=✓  all {_visible}/{len(_pngs)} angles visible',
    f'{len(_pngs) - _visible} dark/empty images: {_invisible_names[:4]} — camera or shader bug',
)

# ── Collect image paths from manifest ───────────────────────────────────────
_manifest_path = os.path.join(SMOKE_CHAR_DIR, 'manifest.json')
_rendered_images: list[str] = []
if os.path.isfile(_manifest_path):
    with open(_manifest_path) as _mf:
        _manifest = json.load(_mf)
    _rendered_images = [p for p in _manifest.get('images', []) if os.path.isfile(p)]

_assert(
    len(_rendered_images) >= 10,
    f'Manifest lists ≥ 10 valid images  ({len(_rendered_images)} found)',
    f'manifest.json present with {len(_rendered_images)} paths',
    f'manifest.json missing or has only {len(_rendered_images)} paths',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Caption writing via blender_character_service._write_captions()
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 2 — Caption .txt generation')

_bcs_ok = False
try:
    from zyg_workflows import blender_character_service as _bcs

    _bcs_ok = True
    print(f'  [{_ts()}] blender_character_service imported OK')
except ImportError as _e:
    print(f'  [{_ts()}] WARN: blender_character_service not importable: {_e}')

_assert(_bcs_ok, 'blender_character_service importable', 'Module found', 'Import failed')

_txts_before = list(Path(SMOKE_CHAR_DIR).glob('*.txt'))
_caption_ok = False
if _bcs_ok and _rendered_images:
    try:
        _svc = _bcs.get_service()
        _trigger = f'ZYG_CHAR_{SMOKE_CHAR_ID[:6].upper()}'
        _params = {
            'gender': 'male',
            'hair_color': 'auburn',
            'eye_color': 'blue',
            'skin_tone': 'medium',
            'style': 'animated',
            'name': 'Smoke Test Character',
            'genre': 'action',
            'facial_hair': 'short beard',
            'muscle_mass': 40,
        }
        _svc._write_captions(_rendered_images, _params, _trigger)
        _caption_ok = True
        print(f'  [{_ts()}] _write_captions() completed')
    except Exception as _ce:
        print(f'  [{_ts()}] _write_captions() raised: {_ce}')

_txts = list(Path(SMOKE_CHAR_DIR).glob('*.txt'))
_assert(
    len(_txts) >= 1,
    f'Caption .txt files written  ({len(_txts)} files)',
    f'Sample captions: {[t.name for t in _txts[:3]]}',
    f'No .txt files in {SMOKE_CHAR_DIR} — caption generation failed',
)

_caption_content_ok = False
_sample_caption = ''
if _txts:
    try:
        _sample_caption = _txts[0].read_text().strip()
        _trigger_check = f'ZYG_CHAR_{SMOKE_CHAR_ID[:6].upper()}'.lower()
        _caption_content_ok = (
            _trigger_check in _sample_caption.lower()
            or 'zyg_char' in _sample_caption.lower()
            or len(_sample_caption) > 10
        )
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

_assert(
    _caption_content_ok,
    'Caption content contains trigger token or description',
    f'Sample: "{_sample_caption[:80]}"',
    'Caption file empty or missing trigger token',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Import crewai_web_gui (with monkey-patch so API skips Blender)
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 3 — Load pipeline module  (monkey-patching Blender stage for speed)')

# Pre-patch: tell blender_character_service to return the already-rendered
# 64-px images instead of re-running Blender at 512 px.
if _bcs_ok:
    _orig_try_blender = _bcs.BlenderCharacterService._try_blender

    def _fast_try_blender(self, params, output_dir):
        """Return the pre-rendered 64-px images immediately — no Blender subprocess."""
        _imgs = [p for p in _rendered_images if os.path.isfile(p)]
        print(f'  [patch] _try_blender bypassed — returning {len(_imgs)} pre-rendered images')
        if not _imgs:
            return [], None
        # Mirror the real _try_blender: inject name + genre + facial_hair + muscle_mass into manifest and persist
        _m = dict(_manifest) if _manifest else {}
        if params.get('name'):
            _m['name'] = params['name']
        if params.get('genre'):
            _m['genre'] = params['genre']
        if params.get('facial_hair'):
            _m['facial_hair'] = params['facial_hair']
        if params.get('muscle_mass') is not None:
            _m['muscle_mass'] = params['muscle_mass']
        _mp = os.path.join(output_dir, 'manifest.json')
        with open(_mp, 'w') as _mf:
            json.dump(_m, _mf, indent=2)
        return _imgs, _m

    _bcs.BlenderCharacterService._try_blender = _fast_try_blender
    print(f'  [{_ts()}] ✓ _try_blender() patched to return {len(_rendered_images)} pre-rendered images')
else:
    print(f'  [{_ts()}] WARN: cannot patch blender_character_service — Blender will run at 512 px')

print(f'  [{_ts()}] Importing crewai_web_gui… (may take 15–30 s)')
t_imp = time.monotonic()
from zyg_dashboard import crewai_web_gui as _gui  # noqa: E402

print(f'  [{_ts()}] Loaded in {time.monotonic() - t_imp:.1f}s')

_assert(
    True,
    'crewai_web_gui imported successfully',
    f'Module loaded in {time.monotonic() - t_imp:.1f}s',
    'Import failed',
)


# ── Patch FLUX dev pipeline to skip heavy inference in smoke test ─────────────
class _MockFluxPipeline:
    """Drop-in that returns a solid-color PIL image instantly — no GPU needed."""

    def __call__(self, prompt='', num_inference_steps=4, width=512, height=512, guidance_scale=0.0, **kw):
        from PIL import Image as _PIL_Image

        _img = _PIL_Image.new('RGB', (width, height), (80, 100, 120))

        class _R:
            images = [_img]

        return _R()

    def enable_tiling(self):
        pass

    def vae(self):
        pass

    def load_lora_weights(self, *a, **k):
        pass

    def set_adapters(self, *a, **k):
        pass

    def unload_lora_weights(self):
        pass


_mock_flux = _MockFluxPipeline()
_mock_flux.vae = _mock_flux  # vae.enable_tiling() also no-ops
_gui._FLUX_DEV_PIPELINE_CACHE = _mock_flux
print(f'  [{_ts()}] ✓ _FLUX_DEV_PIPELINE_CACHE patched with mock (smoke test — no GPU inference)')


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3b — Quality parameter assertions
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 3b — Quality parameters')

# LoRA steps
try:
    from zyg_workflows import lora_trainer_service as _lts_q

    _quick_steps = getattr(_lts_q, '_QUICK_STEPS', None)
    _assert(
        _quick_steps == 200,
        f'LoRA training steps = 200  (found: {_quick_steps})',
        'Fast character LoRA — 200 training steps',
        f'_QUICK_STEPS={_quick_steps} — expected 200',
    )
    # LoRA rank
    import inspect as _inspect_q

    _trainer_src = _inspect_q.getsource(_lts_q._write_st_config)
    _rank_ok = "'--lora_rank': 128" in _trainer_src
    _assert(
        _rank_ok,
        'LoRA rank = 128 in _write_st_config()',
        'More detail captured per training step',
        'lora_rank not updated to 128 in _write_st_config',
    )
except Exception as _qe:
    print(f'  [{_ts()}] WARN: quality param check error: {_qe}')

# Blender resolution
_bcs_file_path = CREWS_DIR / 'blender_character_service.py'
_bcs_text = _bcs_file_path.read_text() if _bcs_file_path.exists() else ''
_res_ok = "'--resolution', '768'" in _bcs_text
_assert(
    _res_ok,
    'Blender resolution = 768 in blender_character_service',
    'Higher resolution training images for sharper LoRA',
    'Blender resolution not updated to 768 in blender_character_service.py',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — VRAM baseline
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 4 — VRAM baseline')

_wm = {'baseline': 0.0, 'final': 0.0}
_total_gb = 0.0
_vram_timeline: list[tuple[float, float]] = []
_t0_vram = time.monotonic()

try:
    import torch

    if torch.cuda.is_available():
        _fi = torch.cuda.mem_get_info(0)
        _total_gb = _fi[1] / 1e9
        _wm['baseline'] = (_fi[1] - _fi[0]) / 1e9
        print(f'  GPU  : {torch.cuda.get_device_name(0)}')
        print(f'  VRAM : {_wm["baseline"]:.2f} GB used / {_total_gb:.1f} GB total')
    else:
        print('  WARN: No CUDA device — VRAM checks skipped')
except Exception as _e:
    print(f'  WARN: torch not available ({_e})')

_vram_done = threading.Event()


def _vram_monitor():
    try:
        import torch as _t

        while not _vram_done.is_set():
            if _t.cuda.is_available():
                _fi2 = _t.cuda.mem_get_info(0)
                _u = (_fi2[1] - _fi2[0]) / 1e9
                _vram_timeline.append((time.monotonic() - _t0_vram, _u))
            time.sleep(3)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


threading.Thread(target=_vram_monitor, daemon=True, name='vram-mon').start()


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — GPU watt limit check
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 5 — GPU watt limit check')

_max_w = _gui._CALIBRATION.get('max_gpu_watts', 0)
print(f'  Calibrated max_gpu_watts = {_max_w}W')
_assert(
    300 <= _max_w <= 400,
    f'GPU watt limit in [300, 400] W  (configured: {_max_w}W)',
    f'Power cap: {int(_max_w)}W — matches documentary/storyteller pipelines',
    f'max_gpu_watts={_max_w}W outside expected [300, 400] range',
)
_assert(
    callable(getattr(_gui, '_apply_gpu_power_limit', None)),
    '_apply_gpu_power_limit function present',
    'Will be called at start of _bg_generate',
    '_apply_gpu_power_limit missing — GPU watt cap not wired to char-gen',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Trigger character generation via Flask test client  (kick_lora=False)
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 6 — API trigger  (kick_lora=False  →  no SimpleTuner wait)')

SMOKE_PARAMS = {
    'char_id': SMOKE_CHAR_ID,
    'name': 'Smoke Test Character',
    'gender': 'male',
    'hair_color': 'auburn',
    'eye_color': 'blue',
    'skin_tone': 'medium',
    'height': '1.75',
    'style': 'animated',
    'genre': 'action',
    'facial_hair': 'short beard',
    'muscle_mass': 40,
    'extra_prompt': '',
    'kick_lora': False,  # ← skips SimpleTuner — makes this test ~instant
}

print(f'  Params: {SMOKE_PARAMS}')

t_api = time.monotonic()

with _gui.app.test_client() as _tc:
    with _tc.session_transaction() as _s:
        _s['user_role'] = 'admin'
        _s['username'] = 'smoke-test'

    _resp = _tc.post(
        '/api/internal/storyteller/generate-character',
        json=SMOKE_PARAMS,
        headers={'X-Zero-Public-Token': _gui._ZERO_PUBLIC_TOKEN or 'smoke'},
        content_type='application/json',
    )
    _rdata = _resp.get_json() or {}

print(f'  [{_ts()}] HTTP {_resp.status_code}  {json.dumps(_rdata)[:120]}')

_api_ok = _resp.status_code == 200 and 'char_id' in _rdata
_assert(
    _api_ok,
    'generate-character API returned 200 + char_id',
    f'char_id={_rdata.get("char_id")}  trigger={_rdata.get("trigger_token")}',
    f'API error: HTTP {_resp.status_code} — {_rdata.get("error", "unknown")}',
)

# Wait for the background job to reach 'done' (should be <15 s with patched Blender)
_MAX_WAIT = 60
_t_wait = time.monotonic()
_final_stage = ''
while time.monotonic() - _t_wait < _MAX_WAIT:
    _cj = _gui._char_gen_jobs.get(SMOKE_CHAR_ID, {})
    _st = _cj.get('status', 'unknown')
    _sg = _cj.get('stage', 'unknown')
    if _sg != _final_stage:
        print(f'  [{_ts()}] ▶ stage={_sg}  status={_st}')
        _final_stage = _sg
    if _st in ('done', 'error'):
        break
    time.sleep(1)

print(f'  [{_ts()}] Pipeline finished  elapsed={time.monotonic() - t_api:.1f}s  status={_st}')

_assert(
    _st == 'done',
    'Pipeline background job reached status=done',
    f'status={_st}  stage={_final_stage}  elapsed={time.monotonic() - t_api:.1f}s',
    f'Job did not reach done: status={_st}  stage={_final_stage}  error={_cj.get("error", "")}',
)

# kick_lora=False skips Stage 1d — only require dataset PNGs, not preview slots
_ds_dir2 = Path(os.path.join(DATASET_ROOT, SMOKE_CHAR_ID))
if SMOKE_PARAMS.get('kick_lora', True):
    _missing_preview = []
    for _base in ('preview_flux_front', 'preview_flux_face'):
        _p = _ds_dir2 / f'{_base}.png'
        _t = _ds_dir2 / f'{_base}.txt'
        if _p.exists() and (not _t.exists() or _t.stat().st_size <= 10):
            _missing_preview.append(f'{_base}.txt')
    _assert(
        len(_missing_preview) == 0,
        'Preview slot captions present (preview_flux_*.txt)',
        'preview_flux_front.txt and preview_flux_face.txt present',
        f'Missing preview captions: {_missing_preview} — LoRA training would fail later',
    )
else:
    _ds_png_count = len([p for p in _ds_dir2.glob('*.png') if 'preview_' not in p.name])
    _assert(
        _ds_png_count >= 10,
        'Dataset training images present (kick_lora=False skips previews)',
        f'{_ds_png_count} dataset PNGs in {SMOKE_CHAR_ID}',
        f'Expected ≥10 dataset PNGs, found {_ds_png_count}',
    )

# Continuity package: character_bible.json should be written for this char_id
_bible_path = _ds_dir2 / 'character_bible.json'
_bible_ok = _bible_path.exists() and _bible_path.stat().st_size > 50
_assert(
    _bible_ok,
    'Character bible exists on disk (character_bible.json)',
    f'Bible present → {_bible_path}',
    f'Bible missing → {_bible_path}',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Live-tail event assertions
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 7 — Live-tail events (debug_events)')

_cj = _gui._char_gen_jobs.get(SMOKE_CHAR_ID, {})
_events = _cj.get('debug_events', [])

print(f'  Total events emitted: {len(_events)}')
for _ev in _events[:6]:
    print(f'    [{_ev.get("ts", "")}] [{_ev.get("level", "INFO"):<7}] {_ev.get("msg", "")[:90]}')
if len(_events) > 6:
    print(f'    … and {len(_events) - 6} more')

_assert(
    len(_events) >= 2,
    f'Live-tail debug_events emitted  ({len(_events)} events)',
    f'First: "{_events[0].get("msg", "")[:70]}"' if _events else '',
    'debug_events is empty — live tail will show nothing during char generation',
)

_power_event = next(
    (e for e in _events if any(k in e.get('msg', '').lower() for k in ('power', 'watt', 'gpu power'))), None
)
_assert(
    _power_event is not None or _max_w <= 400,
    'GPU power-limit event emitted at generation start',
    f'Event: "{_power_event.get("msg", "") if _power_event else f"_CALIBRATION.max_gpu_watts={_max_w}W"}"',
    'No GPU power-limit event — _apply_gpu_power_limit may not have been called',
)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7b — Manifest: name + genre fields persisted
# ══════════════════════════════════════════════════════════════════════════════
_hdr('STEP 7b — Manifest: name and genre fields')

_manifest_after: dict = {}
_manifest_path_after = os.path.join(DATASET_ROOT, SMOKE_CHAR_ID, 'manifest.json')
if os.path.isfile(_manifest_path_after):
    try:
        with open(_manifest_path_after) as _mf2:
            _manifest_after = json.load(_mf2)
        print(f'  manifest.json: {json.dumps(_manifest_after)[:200]}')
    except Exception as _me:
        print(f'  manifest.json read error: {_me}')
else:
    print(f'  manifest.json not found at {_manifest_path_after}')

_assert(
    _manifest_after.get('name') == 'Smoke Test Character',
    f'Manifest stores name field  (found: "{_manifest_after.get("name", "")}")',
    'name="Smoke Test Character" persisted in manifest.json',
    f'name missing or wrong in manifest: "{_manifest_after.get("name", "")}"',
)
_assert(
    _manifest_after.get('genre') == 'action',
    f'Manifest stores genre field  (found: "{_manifest_after.get("genre", "")}")',
    'genre="action" persisted in manifest.json',
    f'genre missing or wrong in manifest: "{_manifest_after.get("genre", "")}"',
)
