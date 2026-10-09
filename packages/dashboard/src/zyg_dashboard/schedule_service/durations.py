# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .base import _DURATION_CACHE, _DURATION_CACHE_TTL_S, _RUNTIME, _load_json, json, os, re, statistics, time
import logging as _zyg_logging_split

_zyg_log = _zyg_logging_split.getLogger('zyg_dashboard.schedule_service')

# ── duration table ───────────────────────────────────────────────────────────

# Fallbacks from the measured 2026-07-12 contact-sheet run f6fc59bce991 and
# documentary stage_timeline history. Values in seconds.
DEFAULT_DURATIONS: dict[str, dict[str, float]] = {
    'contact_sheet': {
        'sheet_generate': 5650,
        'awaiting_approval': 60,
        'tile_crop': 5,
        'identity_qc': 2700,
        'captions': 5,
        'lora_training': 5000,
        'angle_expansion': 800,
        'lora_refine': 1900,
    },
    'char_gen': {
        'Stage 1 — Character Bible': 10,
        'Stage 1a — Character Render': 240,
        'Stage 1b — Caption Generation': 120,
        'Stage 1c — FLUX LoRA Training': 3800,
        'Stage 1c — LoRA Training': 3800,
        'Stage 1c — SDXL LoRA Training': 1300,
        'Stage 1d — Preview Render': 180,
    },
    'documentary': {
        'Stage 1: Topic Setup': 5,
        'Stage 2: Academic Research': 60,
        'Stage 3: Script Preparation': 120,
        'Stage 3b: Visual Tagging': 30,
        'Stage 3.1: Emotion Analysis': 20,
        'Stage 3.5a: Time-Locked Scenes': 20,
        'Stage 3.5: AI Image Generation': 600,
        'Stage 3.6: Anatomy Repair': 120,
        'Stage 4: TTS Narration': 180,
        'Stage 5: Stock Footage': 120,
        'Stage 6: Video Assembly': 300,
        'Color Grade': 60,
        'Subtitle Burn': 60,
    },
    'storyteller': {'__total__': 2400},
    'video': {'__total__': 3600},
    'manga': {'__total__': 1800},
    'clipfarm': {'__total__': 5400},
    'creature': {'__total__': 4000},
    'environments': {'__total__': 600},
    'effects': {'__total__': 600},
    'wardrobe': {'__total__': 300},
    # asset-library apply jobs (qwen-edit single image) — one entry per category board
    'asset_apply': {'__total__': 300},
    'assetlib_items': {'__total__': 300},
    'assetlib_food': {'__total__': 300},
    'assetlib_weapons': {'__total__': 300},
    'assetlib_agriculture': {'__total__': 300},
    'assetlib_water': {'__total__': 300},
    'assetlib_clouds': {'__total__': 300},
    'assetlib_geology': {'__total__': 300},
    'assetlib_furniture': {'__total__': 300},
}

_STATE_FILE_TYPES = (
    ('pipeline_*_state.json', 'documentary'),
    ('storyteller_*_state.json', 'storyteller'),
    ('contact_sheet_*.json', 'contact_sheet'),
    ('char_gen_*.json', 'char_gen'),
    ('creature_gen_*.json', 'creature'),
)


_TEST_ID_PREFIXES_FALLBACK = ('docsmoke-', 'gatecheck-', 'introsmoke-', 'smoke')


def _is_test_state(path: str, d: dict) -> bool:
    """P-03 (2026-08-25): smoke/gatecheck runs (3 stills, silent narration)
    must not feed the per-stage duration medians. The shared predicate is
    pipeline_common.is_test_pipeline_id; this module stays stdlib-only, so the
    import is lazy with a literal fallback. Checks both the state's
    pipeline_id and the id embedded in the filename."""
    pid = str((d or {}).get('pipeline_id') or '')
    m = re.match(r'^[a-z_]+?_(.+)_state\.json$', os.path.basename(path or ''))
    fname_id = m.group(1) if m else ''
    try:
        from zyg_workflows.pipeline_common import is_test_pipeline_id as _t

        return _t(pid) or _t(fname_id)
    except Exception:
        return any(x.strip().lower().startswith(_TEST_ID_PREFIXES_FALLBACK) for x in (pid, fname_id) if x)


def get_duration_table(force: bool = False) -> dict:
    """Median per-(pipeline, stage) durations from stage_timeline history,
    cached in data/runtime/schedule_durations.json, over DEFAULT_DURATIONS."""
    cache = _load_json(_DURATION_CACHE, None)
    if not force and isinstance(cache, dict) and time.time() - float(cache.get('_built_ts', 0)) < _DURATION_CACHE_TTL_S:
        return cache
    import glob as _glob

    samples: dict[str, dict[str, list[float]]] = {}
    for pat, ptype in _STATE_FILE_TYPES:
        for f in _glob.glob(os.path.join(_RUNTIME, pat)):
            d = _load_json(f, None)
            if not isinstance(d, dict):
                continue
            if ptype in ('documentary', 'storyteller') and _is_test_state(f, d):
                continue
            total = 0.0
            for s in d.get('stage_timeline') or []:
                el = s.get('elapsed_s')
                nm = s.get('name') or ''
                if el is None or not nm or nm.lower() == 'done':
                    continue
                samples.setdefault(ptype, {}).setdefault(nm, []).append(float(el))
                total += float(el)
            if total > 60:
                samples.setdefault(ptype, {}).setdefault('__total__', []).append(total)
    table: dict = {'_built_ts': time.time()}
    for ptype, defaults in DEFAULT_DURATIONS.items():
        merged = dict(defaults)
        for nm, vals in (samples.get(ptype) or {}).items():
            if vals:
                merged[nm] = round(statistics.median(vals), 1)
        table[ptype] = merged
    for ptype, stages in samples.items():
        if ptype not in table:
            table[ptype] = {nm: round(statistics.median(v), 1) for nm, v in stages.items() if v}
    try:
        os.makedirs(_RUNTIME, exist_ok=True)
        _tmp = f'{_DURATION_CACHE}.{os.getpid()}.tmp'
        with open(_tmp, 'w', encoding='utf-8') as fh:
            json.dump(table, fh, indent=1)
        os.replace(_tmp, _DURATION_CACHE)
    except OSError as _exc:
        _zyg_log.warning('duration cache %s not written, durations are re-derived next time: %s', _DURATION_CACHE, _exc)
    return table


def _pipeline_total(ptype: str, table: dict | None = None) -> float:
    table = table or get_duration_table()
    stages = table.get(ptype) or {}
    if '__total__' in stages:
        return float(stages['__total__'])
    return float(sum(v for k, v in stages.items() if not k.startswith('_'))) or 3600.0


# ── pipeline → agent/model/device mapping ────────────────────────────────────

PIPELINE_AGENT = {
    'contact_sheet': 'Contact-Sheet-Agent',
    'char_gen': 'Contact-Sheet-Agent',
    'storyteller': 'Storyteller-Agent',
    'documentary': 'Documentary-Agent',
    'scholarly': 'Documentary-Agent',
    'video': 'Video-Pipeline-Agent',
    'intro': 'Video-Pipeline-Agent',
    'manga': 'Manga-Pipeline-Agent',
    'clipfarm': 'CLIPFARM-Overview-Agent',
    'creature': 'Creature-Pipeline-Agent',
    'training': 'Contact-Sheet-Agent',
    'batch': 'Zero',
    'publish': 'Zero',
}

# stage substring (lowercased) → (model slug, device); first match wins.
_STAGE_MODEL_RULES: dict[str, list[tuple[str, str, str]]] = {
    # needles are matched against a space-normalized lowercase stage string, so
    # they must cover BOTH the internal keys ('identity_qc') and the display
    # names written to stage_timeline ('Identity QC (ArcFace)').
    'contact_sheet': [
        ('angle expansion', 'qwen-image-edit-2509', 'gpu'),
        ('sheet generat', 'qwen-image-edit-2509', 'gpu'),
        ('awaiting approval', 'qwen-image-edit-2509', 'gpu'),
        ('tile crop', 'arcface-identity-qc', 'gpu'),
        ('identity qc', 'arcface-identity-qc', 'gpu'),
        ('caption', 'arcface-identity-qc', 'gpu'),
        ('sdxl', 'simpletuner-sdxl-lora', 'gpu'),
        ('lora refine', 'simpletuner-flux-lora', 'gpu'),
        ('lora training', 'simpletuner-flux-lora', 'gpu'),
    ],
    'char_gen': [
        ('sdxl lora', 'simpletuner-sdxl-lora', 'gpu'),
        ('lora training', 'simpletuner-flux-lora', 'gpu'),
        ('caption', 'ollama-vision', 'gpu'),
        ('preview', 'flux-1-dev', 'gpu'),
        ('render', 'flux-1-dev', 'gpu'),
        ('bible', 'claude-api', 'cpu'),
    ],
    'documentary': [
        ('research', 'claude-api', 'cpu'),
        ('script', 'claude-api', 'cpu'),
        ('topic', 'claude-api', 'cpu'),
        ('emotion', 'claude-api', 'cpu'),
        ('visual tagging', 'claude-api', 'cpu'),
        ('time-locked', 'claude-api', 'cpu'),
        ('tts', 'indextts2', 'gpu'),
        ('image generation', 'flux-1-dev', 'gpu'),
        ('anatomy', 'flux-1-fill', 'gpu'),
        ('wan', 'wan2-1-i2v', 'gpu'),
        ('stock', 'ffmpeg-nvenc', 'cpu'),
        ('assembly', 'ffmpeg-nvenc', 'cpu'),
        ('grade', 'ffmpeg-nvenc', 'cpu'),
        ('subtitle', 'ffmpeg-nvenc', 'cpu'),
    ],
    'storyteller': [
        ('script', 'claude-api', 'cpu'),
        ('story', 'claude-api', 'cpu'),
        ('tts', 'indextts2', 'gpu'),
        ('narration', 'indextts2', 'gpu'),
        ('image', 'flux-1-dev', 'gpu'),
        ('ken burns', 'ffmpeg-nvenc', 'cpu'),
        ('assembly', 'ffmpeg-nvenc', 'cpu'),
    ],
    'video': [
        ('plan', 'claude-api', 'cpu'),
        ('tts', 'indextts2', 'gpu'),
        ('image', 'flux-1-dev', 'gpu'),
        ('video generation', 'wan2-1-i2v', 'gpu'),
        ('assembly', 'ffmpeg-nvenc', 'cpu'),
    ],
    'manga': [
        ('plan', 'claude-api', 'cpu'),
        ('tts', 'indextts2', 'gpu'),
        ('panel', 'flux-1-dev', 'gpu'),
        ('image', 'flux-1-dev', 'gpu'),
        ('assembly', 'ffmpeg-nvenc', 'cpu'),
    ],
    'clipfarm': [
        ('discovery', 'gpt-4o-api', 'cpu'),
        ('analysis', 'ollama-llm', 'gpu'),
        ('selection', 'ollama-llm', 'gpu'),
        ('fetch', 'yt-dlp-fetch', 'cpu'),
        ('processing', 'ffmpeg-nvenc', 'cpu'),
        ('qc', 'ollama-vision', 'gpu'),
        ('publish', 'yt-publish', 'cpu'),
    ],
    'creature': [
        # 2026-08-25 sheet workflow: brief (Ollama vision) → anchor + rotations
        # (Qwen-Image-Edit-2509) → sheet QC / review (Qwen3-VL judge) → captions
        # → klein LoRA → klein previews. Nothing routes through FLUX.1-dev.
        ('brief', 'ollama-vision', 'gpu'),
        ('sheet qc', 'qwen3-vl-judge-8b-fp8-resident-32b-fp8-boundary', 'gpu'),
        ('review', 'qwen3-vl-judge-8b-fp8-resident-32b-fp8-boundary', 'gpu'),
        ('anchor', 'qwen-image-edit-2509', 'gpu'),
        ('multi-angle', 'qwen-image-edit-2509', 'gpu'),
        ('sheet', 'qwen-image-edit-2509', 'gpu'),
        ('reference', 'qwen-image-edit-2509', 'gpu'),
        ('caption', 'ollama-vision', 'gpu'),
        ('lora', 'simpletuner-klein-lora-train', 'gpu'),
        ('training', 'simpletuner-klein-lora-train', 'gpu'),
        ('preview', 'flux-2-klein-4b-apache-2-0', 'gpu'),
        ('render', 'flux-2-klein-4b-apache-2-0', 'gpu'),
    ],
}

_PIPELINE_FALLBACK_MODEL = {
    'contact_sheet': ('qwen-image-edit-2509', 'gpu'),
    'char_gen': ('flux-1-dev', 'gpu'),
    'documentary': ('flux-1-dev', 'gpu'),
    'scholarly': ('flux-1-dev', 'gpu'),
    'storyteller': ('flux-1-dev', 'gpu'),
    'video': ('flux-1-dev', 'gpu'),
    'intro': ('flux-1-dev', 'gpu'),
    'manga': ('flux-1-dev', 'gpu'),
    'clipfarm': ('ollama-llm', 'gpu'),
    'creature': ('qwen-image-edit-2509', 'gpu'),
    'environments': ('sdxl-juggernaut', 'gpu'),
    'effects': ('sdxl-juggernaut', 'gpu'),
    'wardrobe': ('qwen-image-edit-2509', 'gpu'),
    'asset_apply': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_items': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_food': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_weapons': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_agriculture': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_water': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_clouds': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_geology': ('qwen-image-edit-2509', 'gpu'),
    'assetlib_furniture': ('qwen-image-edit-2509', 'gpu'),
    'training': ('simpletuner-flux-lora', 'gpu'),
    'batch': ('claude-api', 'cpu'),
    'publish': ('yt-publish', 'cpu'),
}


def _stage_model(ptype: str, stage: str) -> tuple[str, str]:
    # normalize so internal keys ('identity_qc') and display names
    # ('Identity QC (ArcFace)') both hit the same space-form needles
    st = (stage or '').lower().replace('_', ' ').replace('-', ' ')
    for needle, slug, dev in _STAGE_MODEL_RULES.get(ptype, []):
        if needle in st:
            return slug, dev
    return _PIPELINE_FALLBACK_MODEL.get(ptype, ('flux-1-dev', 'gpu'))
