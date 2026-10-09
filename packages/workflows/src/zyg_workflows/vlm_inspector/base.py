# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging as _zyg_logging
import os

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.vlm_inspector')


_DIR = str(paths.PKG_DIR)

VLM_HOME = paths.ZYG_VLM_HOME
_VLM_PY = os.path.join(VLM_HOME, '.venv', 'bin', 'python')
_VLM_WORKER = os.path.join(VLM_HOME, 'vlm_worker.py')
_MODELS_JSON = os.path.join(VLM_HOME, 'models.json')
_CHECKLIST_PATH = os.environ.get('ZYG_VLM_CHECKLISTS', os.path.join(_DIR, 'config', 'vlm_checklists.json'))

# Repo ids: Apache-2.0 at every size, multi-image + video input, 2D bbox
# grounding.  These are the module DEFAULTS; the installer's models.json (if
# present) and then the ZYG_VLM_*_MODEL env vars override them, in that order —
# so nothing here needs editing when the judge install lands a different pin.
# 2026-07-30 PINNED TO WHAT IS ACTUALLY ON DISK. These constants were authored before
# the runtime install reported back, and named checkpoints that were never downloaded
# (plain -32B-Instruct; only the -FP8 build exists locally) with bnb4 quantization that
# would have been applied ON TOP of an already-quantized checkpoint. Verified present in
# ~/.cache/huggingface, all Apache-2.0 (license read from each model card):
#   Qwen3-VL-32B-Instruct-FP8  35.5 GB  boundary (GPU free / ComfyUI offloaded)
#   Qwen3-VL-8B-Instruct-FP8   10.6 GB  resident (fits beside a ~33 GB render)
#   Qwen3-VL-8B-Instruct bf16  17.5 GB  CPU tier + bnb4 source
#   Qwen3-VL-4B-Instruct        8.9 GB  low-VRAM / faster-CPU fallback
BOUNDARY_MODEL = 'Qwen/Qwen3-VL-32B-Instruct-FP8'
RESIDENT_MODEL = 'Qwen/Qwen3-VL-8B-Instruct-FP8'
CPU_MODEL = 'Qwen/Qwen3-VL-8B-Instruct'  # bf16 weights; CPU has no fp8 kernels

# min_free_gb is what the tier needs to LOAD. FP8 checkpoints carry their own
# quantization, so the worker must be told 'fp8' — NOT bnb4 on top of it.
# Fallback order is boundary -> resident -> cpu.
TIER_ORDER = ('boundary', 'resident', 'cpu')
TIERS = {
    'boundary': {'device': 'cuda', 'quantization': 'fp8', 'min_free_gb': 40.0, 'needs_gpu': True, 'timeout_s': 1800},
    'resident': {'device': 'cuda', 'quantization': 'fp8', 'min_free_gb': 14.0, 'needs_gpu': True, 'timeout_s': 900},
    'cpu': {'device': 'cpu', 'quantization': 'none', 'min_free_gb': 0.0, 'needs_gpu': False, 'timeout_s': 3600},
}

_ANSWER_YES = ('yes', 'y', 'true', 'correct', 'affirmative', '1')
_ANSWER_NO = ('no', 'n', 'false', 'incorrect', 'negative', '0')


# ── small helpers ────────────────────────────────────────────────────────────


def _mklog(log_fn):
    def _l(msg):
        try:
            if log_fn:
                log_fn(f'[vlm] {msg}')
            else:
                _zyg_log.info(f'[vlm_inspector] {msg}')
        except Exception as _exc:
            _zyg_log.debug('vlm log line not emitted: %s', _exc)

    return _l


def _enabled():
    return os.environ.get('ZYG_VLM', '1') != '0'


def _strict():
    return os.environ.get('ZYG_VLM_STRICT', '0') == '1'


def _skipped(reason, **extra):
    """Fail-safe empty result: ok=True so a missing judge never blocks a run."""
    out = {
        'ok': True,
        'skipped': True,
        'reason': reason,
        'verdicts': [],
        'flags': [],
        'criticals': [],
        'majors': [],
        'unknown': [],
        'bboxes': {},
        'frames': [],
        'n_frames': 0,
        'seconds': 0.0,
    }
    out.update(extra)
    return out


def available():
    """True when the isolated judge venv + worker are installed and enabled."""
    return bool(_enabled() and os.path.isfile(_VLM_PY) and os.path.isfile(_VLM_WORKER))


def _models_json():
    """Installer-written pins, if the judge install left any.  {} on any error."""
    try:
        with open(_MODELS_JSON, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _as_model_id(val):
    if isinstance(val, str) and val.strip():
        return val.strip()
    if isinstance(val, dict):
        for k in ('model_id', 'repo_id', 'id', 'model', 'hf_id'):
            v = val.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def model_for(tier):
    """Repo id for a tier: env > models.json > module constant."""
    tier = tier if tier in TIERS else 'boundary'
    env_key = {'boundary': 'ZYG_VLM_BOUNDARY_MODEL', 'resident': 'ZYG_VLM_RESIDENT_MODEL', 'cpu': 'ZYG_VLM_CPU_MODEL'}[
        tier
    ]
    env_val = (os.environ.get(env_key) or '').strip()
    if env_val:
        return env_val
    mj = _models_json()
    key = tier if tier in ('boundary', 'resident', 'cpu') else 'boundary'
    for probe in (mj.get(key), (mj.get('models') or {}).get(key) if isinstance(mj.get('models'), dict) else None):
        mid = _as_model_id(probe)
        if mid:
            return mid
    # CPU has no fp8 kernels — the cpu tier must never inherit an FP8 checkpoint
    return {'boundary': BOUNDARY_MODEL, 'resident': RESIDENT_MODEL, 'cpu': CPU_MODEL}[tier]


def _quant_for(tier):
    """Quantization flag for a tier: env > models.json > tier default.

    Env-overridable because the worker's accepted vocabulary ('bnb4', 'none',
    'awq', ...) is owned by the judge install, not by this module.
    """
    env_val = (
        os.environ.get('ZYG_VLM_BOUNDARY_QUANT' if tier == 'boundary' else 'ZYG_VLM_RESIDENT_QUANT') or ''
    ).strip()
    if env_val:
        return env_val
    mj = _models_json()
    src = mj.get('boundary' if tier == 'boundary' else 'resident')
    if isinstance(src, dict):
        q = src.get('quantization') or src.get('quant')
        if isinstance(q, str) and q.strip():
            return q.strip()
    return TIERS[tier]['quantization']


def _timeout_for(tier):
    try:
        env = (os.environ.get('ZYG_VLM_TIMEOUT') or '').strip()
        if env:
            return max(60, int(float(env)))
    except Exception as _exc:
        _zyg_log.warning('ZYG_VLM_TIMEOUT is not a number, using the tier default: %s', _exc)
    return TIERS[tier]['timeout_s']


# ── checklists ───────────────────────────────────────────────────────────────


def load_checklist(name='scene20_binary', path=None, log_fn=None):
    """Load one checklist from config/vlm_checklists.json.

    Returns {'name', 'description', 'preamble', 'items': [...]}; {} (with a loud
    log) when the file or the name is missing — callers treat that as "skip".
    """
    log = _mklog(log_fn)
    p = path or _CHECKLIST_PATH
    try:
        with open(p, encoding='utf-8') as f:
            doc = json.load(f)
        book = doc.get('checklists') or {}
        cl = book.get(name)
        if not isinstance(cl, dict):
            log(f'checklist "{name}" not found in {p} (have: {", ".join(sorted(book)) or "none"})')
            return {}
        items = [i for i in (cl.get('items') or []) if isinstance(i, dict) and i.get('id')]
        if not items:
            log(f'checklist "{name}" has no usable items')
            return {}
        return {
            'name': name,
            'description': cl.get('description', ''),
            'preamble': cl.get('preamble', ''),
            'items': items,
        }
    except Exception as e:
        log(f'load_checklist({name}) failed: {e}')
        return {}


def _select_items(items, frame_kind, has_refs):
    """Drop 'beats'-only questions on non-beat frames and ref-only questions
    when no reference images were supplied."""
    out = []
    for it in items:
        if it.get('needs_refs') and not has_refs:
            continue
        if str(it.get('frames', 'all')).lower() == 'beats' and frame_kind != 'beats':
            continue
        out.append(it)
    return out


# ── worker plumbing ──────────────────────────────────────────────────────────


def _questions_payload(items, preamble, n_refs):
    """Build the questions the worker gets: preamble + reference note + question.

    Kept deliberately self-contained per question — the worker is a dumb runner
    and each question is answered independently (per-failure-class decomposition
    is what makes a local judge reliable).
    """
    ref_note = ''
    if n_refs:
        ref_note = (
            f'The first {n_refs} image(s) are REFERENCE PORTRAITS of the '
            f'intended characters and are not part of the video; the '
            f'remaining images are the video frames to judge. '
        )
    qs = []
    for it in items:
        q = ' '.join(x for x in (preamble, ref_note, str(it.get('question', ''))) if x)
        rec = {
            'id': it['id'],
            'question': q,
            'expected': str(it.get('expected', 'yes')).lower(),
            'severity': str(it.get('severity', 'major')).lower(),
            'grounding': bool(it.get('grounding')),
        }
        # Optional per-question image selection (2026-08-25, era gate): a list
        # of indices into the image list the worker receives. Distinct from the
        # checklist's string-valued 'frames' ('all'/'beats'), which is a
        # frame-KIND filter, not a selection. The worker reads 'frames'.
        _fi = it.get('frame_indices')
        if isinstance(_fi, (list, tuple)) and _fi:
            rec['frames'] = [int(i) for i in _fi]
        qs.append(rec)
    if os.environ.get('ZYG_VLM_QPAYLOAD', 'list') == 'dict':
        return {'questions': qs, 'n_reference_images': int(n_refs)}
    return qs


def _norm_answer(val):
    """'yes' / 'no' / 'unknown' from whatever the worker put in 'answer'."""
    if isinstance(val, bool):
        return 'yes' if val else 'no'
    s = str(val or '').strip().lower().rstrip('.!,')
    if not s:
        return 'unknown'
    first = s.split()[0].strip('"\'')
    if first in _ANSWER_YES or s.startswith('yes'):
        return 'yes'
    if first in _ANSWER_NO or s.startswith('no'):
        return 'no'
    return 'unknown'
