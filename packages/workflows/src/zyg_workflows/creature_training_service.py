# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_training_service.py
============================
Creature Creation — brief → anchor → judged multi-angle sheet → [review gate]
→ captions → LoRA training → judged previews.

Rebuilt 2026-08-25 (the May flow rendered 20 unlinked FLUX.1-dev stills, wrote
template captions and trained on FLUX.1-dev; FLUX is paused under the licence
gate and nothing in that flow judged its own output). What changed:

  * The dataset is a CONTACT SHEET (creature_sheet_service): every cell is a
    camera-rotation EDIT of one anchor, so identity is inherited, not re-rolled.
  * Source is explicit — ``reference`` (1..n operator images) or ``scratch``
    (text brief → FLUX.2 klein-4B anchor). Both are Apache-2.0 paths.
  * Every stage judges what it produced: anchors and cells through the
    Qwen3-VL checklist + DINOv2 drift, previews through the same strip judge.
  * A REVIEW GATE (default on) parks the run at ``awaiting_review`` after the
    sheet, so the operator inspects exactly the tiles that would train before
    any GPU-hour is spent on a LoRA. ``approve`` resumes with phase='train'.
  * Training family is klein by default (ZYG_CREATURE_TRAIN_FAMILY); FLUX is
    refused by the trainer's own licence pause.

State contract: this module mutates *job* in place and the caller persists it.
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from zyg_workflows import creature_lora_service as _cls
from zyg_workflows import paths
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_AMS = ZoneInfo('Europe/Amsterdam')
DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'creatures')
OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'creatures')

STAGE_BRIEF = 'Creature Brief'
STAGE_ANCHOR = 'Reference Anchor'
STAGE_SHEET = 'Multi-Angle Sheet'
STAGE_QC = 'Sheet QC'
STAGE_REVIEW = 'Sheet Review'
STAGE_CAPTIONS = 'Caption Generation'
STAGE_TRAIN = 'LoRA Training'
STAGE_PREVIEW = 'Preview Render'
STAGES_ORDER = (
    STAGE_BRIEF,
    STAGE_ANCHOR,
    STAGE_SHEET,
    STAGE_QC,
    STAGE_REVIEW,
    STAGE_CAPTIONS,
    STAGE_TRAIN,
    STAGE_PREVIEW,
)

# THE MARGIN RULE (2026-08-26). A 'body' slot must leave floor under the
# subject or the smallest parts are cropped at the moment they would render.
# Measured on the Pufferball previews: the feet are ~0.28% of frame in the
# training cells (≈11 latent tokens of 4096 at 1024px/16 — about 5 per foot,
# the resolution floor), and the two body previews framed him so large that
# 97.9% and 99.8% of the bottom pixel row was subject. The training cells sat
# at 39–59%. The judge's 'whole_body' flag fired on both and, being a SOFT
# flag, marked without blocking. Say "standing on the ground, full body in
# frame with space below the feet" rather than trusting "full body" alone.
_FULL_BODY_FRAMING = (
    'full body in frame, standing on the ground, entire body including feet visible, space below the feet'
)
_PREVIEW_SLOTS = [
    (
        'preview_front',
        f'front view, {_FULL_BODY_FRAMING}, dramatic studio lighting',
        'body',
        'a straight-on front view showing the whole body',
    ),
    (
        'preview_three_quarter',
        f'three-quarter left view, {_FULL_BODY_FRAMING}, cinematic',
        'body',
        'a three-quarter view turned to the left',
    ),
    ('preview_closeup', 'close-up portrait, detailed eyes and texture', 'head', 'a close-up of the face and eyes'),
]

_OLLAMA_HOST = os.environ.get('OLLAMA_HOST', paths.ZYG_OLLAMA_URL).rstrip('/')
BRIEF_MODEL = os.environ.get('ZYG_CREATURE_BRIEF_MODEL', 'qwen3.5:9b').strip()


def train_family() -> str:
    fam = (os.environ.get('ZYG_CREATURE_TRAIN_FAMILY') or 'klein').strip().lower()
    return fam if fam in ('klein', 'qwen', 'sdxl', 'flux') else 'klein'


def normalize_options(raw) -> dict:
    """Sanitised creature_options. Unknown keys dropped, values clamped."""
    po = raw if isinstance(raw, dict) else {}
    src = str(po.get('source') or '').strip().lower()
    if src in ('scratch', 'text', 'from_scratch'):
        src = 'scratch'
    elif src in ('reference', 'ref', 'image', 'images', 'photo'):
        src = 'reference'
    else:
        src = ''  # decided by whether images were supplied
    angles = str(po.get('angles') or 'standard').strip().lower()
    angles = angles if angles in ('standard', 'compact') else 'standard'
    rg = po.get('review_gate', True)
    review_gate = rg if isinstance(rg, bool) else str(rg).strip().lower() not in ('0', 'false', 'no', 'off')
    return {'source': src, 'angles': angles, 'review_gate': review_gate}


# ── operator review card (Agent Zero pending queue) ──────────────────────────
# 2026-08-26. The gate used to park the run, write ONE log line and stop. Nothing
# reached the operator: no Zero card, no badge, no board affordance — the only
# way to approve was `curl`/scripts/run_creature_sheet.py --approve. A gate
# nobody is told about is a stall, so parking now queues the same pending card
# the character contact-sheet review has used since July (Zero blinks, the card
# offers Allow/Decline). Written here rather than in the GUI because a creature
# run also executes in scripts/creature_worker.py, a SEPARATE process with no
# Flask app to call into — the file IS the channel both share.
_RUNTIME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'runtime')
_PENDING_PATH = os.path.join(_RUNTIME_DIR, 'zpub_pending.json')
REVIEW_PIPELINE = 'creature_review'


def _pending_rw(mutate):
    """Read-modify-write zpub_pending.json under an fcntl lock, returning
    whatever *mutate* returns. The lock serialises the two worker processes
    against each other; the GUI's own request-time writes hold only a
    threading.Lock, so a simultaneous operator decision is still a (rare,
    operator-paced) race — worth knowing, not worth a schema change."""
    import fcntl

    os.makedirs(_RUNTIME_DIR, exist_ok=True)
    with open(_PENDING_PATH + '.lock', 'w') as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            with open(_PENDING_PATH, encoding='utf-8') as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                data = []
        except (FileNotFoundError, ValueError):
            data = []
        out, changed = mutate(data)
        if changed:
            tmp = _PENDING_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, _PENDING_PATH)
        return out


def push_review_card(creature_id: str, job: dict, sheet_path: str = '') -> str:
    """Queue the sheet review in the Agent Zero pending store. Returns the card
    id (or '' when one is already open for this creature)."""
    import uuid as _uuid

    brief = job.get('brief') or {}
    summary = job.get('sheet_report') or {}
    name = (brief.get('name') or job.get('directive') or creature_id[:8]).strip()
    fam = job.get('train_family') or train_family()
    npass, ncell = summary.get('pass_count'), summary.get('cell_count')
    judged = 'judged' if summary.get('judged_any') else 'JUDGE OFFLINE — structural + DINO only'
    prompt = (
        f'Creature sheet for "{name}" is ready — {npass}/{ncell} cells pass ({judged}). '
        f'Allow → captions + {fam} LoRA training; Decline → nothing trains and the '
        f'dataset stays on disk.'
    )

    def _mutate(data):
        if any(
            r.get('pipeline') == REVIEW_PIPELINE
            and r.get('creature_id') == creature_id
            and r.get('status') in ('pending', 'queued')
            for r in data
        ):
            return '', False
        req_id = 'preq_' + _uuid.uuid4().hex[:12]
        data.append(
            {
                'id': req_id,
                'token': '',
                'label': f'Review creature sheet — {name}',
                'invite_url': '',
                'prompt': prompt,
                'pipeline': REVIEW_PIPELINE,
                'voice': '',
                'style': (brief.get('style_hint') or ''),
                'model': fam,
                'ip': 'internal',
                'session_id': '',
                # char_id mirrors creature_id so the generic dashboard fields that
                # key on char_id keep working; the creature link builder reads
                # creature_id, and the decide handler dispatches on `pipeline`.
                'creature_id': creature_id,
                'char_id': creature_id,
                'sheet_path': sheet_path or job.get('sheet_path') or '',
                'sheet_report': {
                    k: summary.get(k) for k in ('pass_count', 'cell_count', 'pass_rate', 'judged_any', 'judge_tier')
                },
                'body_snapshot': {},
                'requested_at': datetime.now(_AMS).astimezone(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
                'status': 'pending',
                'decided_at': None,
                'approved_job_id': None,
            }
        )
        return req_id, True

    return _pending_rw(_mutate)


def resolve_review_card(creature_id: str, status: str) -> int:
    """Close any open review card for this creature — called by approve/reject
    however they were triggered (Zero, the API route, the CLI helper), so a run
    approved by curl stops the badge blinking instead of leaving a ghost card."""

    def _mutate(data):
        n = 0
        for r in data:
            if (
                r.get('pipeline') == REVIEW_PIPELINE
                and r.get('creature_id') == creature_id
                and r.get('status') in ('pending', 'queued')
            ):
                r['status'] = status
                r['decided_at'] = datetime.now(_AMS).astimezone(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
                if status == 'approved':
                    r['approved_job_id'] = creature_id
                n += 1
        return n, bool(n)

    return _pending_rw(_mutate)


def _ensure_comfy_env() -> None:
    try:
        from zyg_workflows import _comfy_client as _cc
    except ImportError:
        return
    if _cc.server_reachable():
        os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
        os.environ.setdefault('ZYG_USE_COMFYUI', '1')


# ── brief ────────────────────────────────────────────────────────────────────


def _b64(path: str, max_side: int = 1024) -> str | None:
    try:
        import io
        from PIL import Image

        im = Image.open(path).convert('RGB')
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=88)
        return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return None


def _ollama_json(prompt: str, images_b64: list[str] | None, log_fn) -> dict | None:
    """One Ollama /api/generate call (vision when images given) → parsed JSON or None."""
    try:
        from zyg_workflows import cell_vlm_judge as _cvj
        from zyg_workflows import llm_audit as _la

        payload = {
            'model': BRIEF_MODEL,
            'prompt': prompt,
            'stream': False,
            # unload right after: the next step loads a 41 GB edit model on the same card
            'keep_alive': 0,
            'options': {'num_ctx': 8192, 'num_predict': 600, 'temperature': 0.2},
        }
        if images_b64:
            payload['images'] = images_b64
        payload = _cvj._ollama_vision_payload(payload)
        resp = _la.ollama_post(f'{_OLLAMA_HOST}/api/generate', payload, timeout=240, stage='creature/brief')
        text = (resp or {}).get('response') or ''
        parsed = _cvj._parse_json(text)
        if not parsed and text.strip().startswith('{'):
            parsed = json.loads(text)
        return parsed or None
    except Exception as exc:
        log_fn(f'brief LLM call failed ({exc})')
        return None


def _generate_creature_brief(directive: str, log_fn, reference_paths: list[str] | None = None) -> dict:
    """Bible-style creature brief. Reference images are DESCRIBED by the local
    vision model (qwen3.5:9b) so captions carry what the pixels show, not what
    the operator typed; the directive supplies the name and any override."""
    profile_key, _profile = _cls.resolve_profile(directive)
    fallback = {
        'name': (directive or '')[:60].strip() or 'Creature',
        'description': (directive or '')[:300],
        'species': 'creature',
        'profile_key': profile_key,
        'visual_traits': (directive or '')[:200],
        'style_hint': '',
        'brief_source': 'heuristic',
    }
    refs = [p for p in (reference_paths or []) if p and os.path.isfile(p)]
    imgs = [b for b in (_b64(p) for p in refs[:3]) if b]
    if imgs:
        prompt = (
            'You are describing a creature for an image-generation training dataset. '
            + (f'The operator calls it: "{directive.strip()}". ' if (directive or '').strip() else '')
            + 'Look at the image(s) and return ONLY a JSON object with keys: '
            'name (short, ≤40 chars), species (what kind of creature, ≤40 chars), '
            'description (≤250 chars, purely visual: body shape, colours, eyes, fur/skin/scales, '
            'distinctive features), visual_traits (≤180 chars, comma-separated key traits), '
            'style_hint (≤60 chars: the rendering style, e.g. "3D animated film render", '
            '"watercolour illustration", "photorealistic"). No prose outside the JSON.'
        )
        data = _ollama_json(prompt, imgs, log_fn)
        if data:
            out = {
                'name': str(data.get('name') or fallback['name'])[:80],
                'description': str(data.get('description') or fallback['description'])[:300],
                'species': str(data.get('species') or 'creature')[:80],
                'profile_key': profile_key,
                'visual_traits': str(data.get('visual_traits') or fallback['visual_traits'])[:200],
                'style_hint': str(data.get('style_hint') or '')[:80],
                'brief_source': f'ollama_vision:{BRIEF_MODEL}',
            }
            if (directive or '').strip() and len(directive.strip()) <= 60:
                out['name'] = directive.strip()
            return out
        log_fn('vision brief unavailable — falling back to text brief')
    if (directive or '').strip():
        prompt = (
            f'Creature concept: "{directive.strip()}"\n\n'
            'Return ONLY a JSON object with keys: name (≤40 chars), species (≤40 chars), '
            'description (≤250 chars, purely visual), visual_traits (≤180 chars, comma-separated), '
            'style_hint (≤60 chars rendering style, or "").'
        )
        data = _ollama_json(prompt, None, log_fn)
        if data:
            return {
                'name': str(data.get('name') or fallback['name'])[:80],
                'description': str(data.get('description') or fallback['description'])[:300],
                'species': str(data.get('species') or 'creature')[:80],
                'profile_key': profile_key,
                'visual_traits': str(data.get('visual_traits') or fallback['visual_traits'])[:200],
                'style_hint': str(data.get('style_hint') or '')[:80],
                'brief_source': f'ollama_text:{BRIEF_MODEL}',
            }
    log_fn('brief LLM unavailable — using heuristic brief')
    return fallback


# Operator-owned brief keys (body-plan lock, 2026-08-25): survive a brief
# regeneration and are written by scripts/creature_lock.py.
OPERATOR_BRIEF_KEYS = ('body_plan', 'anchor_locks', 'negative', 'operator_notes')


def _brief_for_run(job: dict, directive: str, dataset_dir: str, refs: list[str], log_fn) -> dict:
    """The brief a (re)run works from. A RESUMED run reuses brief.json verbatim
    (the vision brief is one LLM draw; regenerating it would re-caption the
    whole set differently and drop the operator's locks). A fresh run generates
    one and carries the operator keys over from any brief.json already there."""
    path = os.path.join(dataset_dir, 'brief.json')
    existing = _read_json(path)
    if job.get('resumed') and existing.get('description'):
        log_fn(
            'brief reused from brief.json (resume)'
            + (f' — body plan: "{str(existing.get("body_plan"))[:90]}"' if existing.get('body_plan') else '')
            + (
                f' — locks: {sorted((existing.get("anchor_locks") or {}).keys())}'
                if existing.get('anchor_locks')
                else ''
            )
        )
        brief = dict(existing)
    else:
        brief = _generate_creature_brief(directive, log_fn, reference_paths=refs)
        for k in OPERATOR_BRIEF_KEYS:
            if existing.get(k) and not brief.get(k):
                brief[k] = existing[k]
                log_fn(f'brief: operator key {k!r} carried over from brief.json')
    brief['profile_key'] = brief.get('profile_key') or _cls.resolve_profile(directive)[0]
    return brief


# ── training ─────────────────────────────────────────────────────────────────


def _wait_for_lora_training(creature_id: str, fam: str, log_fn, timeout_s: int = 3 * 3600, halt_check=None) -> dict:
    from zyg_workflows import lora_trainer_service as _lts

    trainer = _lts.get_trainer()
    elapsed, last_pct, status = 0, -1, {}
    while elapsed < timeout_s:
        if callable(halt_check):
            halt_check()
        time.sleep(10)
        elapsed += 10
        status = trainer.get_status(creature_id, model_family=fam, output_root=OUTPUT_ROOT)
        pct = int(status.get('pct') or 0)
        if pct != last_pct and pct > 0 and pct % 10 == 0:
            log_fn(f'LoRA training {pct}% ({status.get("step", 0)}/{status.get("total_steps", 0)} steps)')
            last_pct = pct
        if status.get('done'):
            log_fn(f'LoRA training complete: {status.get("lora_path") or "checkpoint saved"}')
            return status
        if status.get('failed'):
            raise RuntimeError(status.get('error') or 'LoRA training failed')
    raise RuntimeError(f'LoRA training timed out after {timeout_s // 3600} h')


def _clip_desc(desc: str, limit: int = 220) -> str:
    """Trim a brief's description for a validation prompt.

    A validation prompt is encoded once per sample and every family truncates
    (CLIP hardest), so a runaway brief pushes the trigger token — the one word
    the sample exists to test — out of the useful end of the context. Prefer the
    last SENTENCE that fits; fall back to a word boundary only when that would
    throw away most of the description.
    """
    desc = ' '.join((desc or '').split())
    if len(desc) <= limit:
        return desc.rstrip(' ,;.')
    head = desc[:limit]
    dot = head.rfind('. ')
    if dot >= int(limit * 0.6):
        return head[:dot].rstrip(' ,;.')
    return head.rsplit(' ', 1)[0].rstrip(' ,;.')


def _plan_clause(brief: dict, limit: int = 600) -> str:
    """The brief's body-plan sentence, trimmed, ready to splice into a prompt.

    THE CAPTION/RENDER AGREEMENT (2026-08-26). training_tiles() puts this exact
    sentence in EVERY training caption — that is how the LoRA binds the words
    "tail", "arms", "feet" to those pixels. Every render prompt therefore has to
    carry it too, or the render asks for a creature the adapter was never
    conditioned on.

    Measured on the Zygo AI Pufferball (d0e44ab002ad): the body plan was in all
    17 captions and in NO render prompt, so the preview prompt reduced to the
    brief description — "Round, puffy body covered in soft white fur with a
    turquoise face. Large golden-brown eyes… Small mouth showing tiny teeth" —
    which names no tail, no arms and no feet. All three previews came back as a
    fur ball with a face, exactly what was asked for. The tail is in 15 of 16
    training cells at 5–26% of frame; it was never missing from the weights.

    The limit is a runaway guard, NOT a budget — deliberately generous. A body
    plan is operator-written (OPERATOR_BRIEF_KEYS / scripts/creature_lock.py),
    not LLM-drafted, so it does not run away; and the parts are listed in
    descending prominence, which means an aggressive cap eats precisely the
    small parts this function exists to protect. Caught in review at limit=240:
    the Pufferball's own 253-char plan cut cleanly after "…curling up behind the
    body" and silently dropped "two short turquoise arms; two turquoise
    three-toed feet" — the exact two parts missing from his renders.

    When it does have to cut, it cuts on a part boundary: a body plan is a
    semicolon list, and half a part ("two turquoise three-") is worse than one
    part fewer."""
    bp = ' '.join((brief.get('body_plan') or '').split()).strip().rstrip(' ,;.')
    if len(bp) <= limit:
        return bp
    head = bp[:limit]
    cut = max(head.rfind('; '), head.rfind(', '))
    if cut >= int(limit * 0.5):
        return head[:cut].rstrip(' ,;.')
    return head.rsplit(' ', 1)[0].rstrip(' ,;.')


def _val_prompt(brief: dict, trigger: str) -> str:
    """The prompt SimpleTuner validates a CREATURE LoRA with.

    lora_trainer_service only ever branched its validation prompt on train_mode
    ('body' vs 'identity'), both of which describe a HUMAN — so every creature
    trained before 2026-08-26 was validated as "<trigger> person, head and
    shoulders portrait ... visible pores" and its frames came back as people.
    The weights were fine; the only picture anyone looks at was of the wrong
    species.

    Shaped like the front slot of _PREVIEW_SLOTS on purpose: the validation
    frame and preview_front then differ only by training step, which is the one
    comparison worth having. Description is clipped on a word boundary — a
    validation prompt is encoded once per sample and a runaway brief would push
    the trigger token out of the useful end of the context.

    Carries the body plan for the reason in _plan_clause: without it the
    validation frame asks for a different creature than every caption trained.
    """
    desc = _clip_desc(brief.get('description') or brief.get('visual_traits') or brief.get('species') or 'creature')
    style = (brief.get('style_hint') or '').strip()
    plan = _plan_clause(brief)
    return (
        f'{trigger}, {desc}'
        + (f', {plan}' if plan else '')
        + ', front view, full body, whole body inside the frame'
        + ', dramatic studio lighting'
        + (f', {style}' if style else '')
        + ', single creature, clean background, highly detailed'
    )


def _render_previews(
    creature_id: str,
    brief: dict,
    lora_path: str,
    fam: str,
    dataset_dir: str,
    trigger: str,
    anchor_ref: str | None,
    log_fn,
) -> tuple[list[str], dict]:
    """Three LoRA renders, each judged against the identity anchor (strip + DINO)."""
    if not lora_path or not os.path.isfile(lora_path):
        log_fn('Preview skipped — no trained LoRA checkpoint')
        return [], {}
    _ensure_comfy_env()
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import creature_identity as _cid
    from zyg_workflows import creature_judge as _cj
    from zyg_workflows import creature_sheet_service as _css

    if not _cgs.is_available():
        log_fn('Preview skipped — ComfyUI unavailable')
        return [], {}
    desc = brief.get('description') or brief.get('visual_traits') or 'creature'
    style = brief.get('style_hint') or ''
    plan = _plan_clause(brief)
    pkg = {'conditioning': {f'{fam}_lora_path': lora_path}, 'style_profile': {'render_style': 'stylized'}}
    rendered: list[str] = []
    recs: list[dict] = []
    for i, (stem, angle, kind, angle_desc) in enumerate(_PREVIEW_SLOTS):
        # body slots carry the plan (they can show a tail/limbs); a face
        # close-up cannot, and asking for feet in a head shot only fights it.
        _plan = plan if kind != 'head' else ''
        prompt = (
            f'{trigger}, {desc}'
            + (f', {_plan}' if _plan else '')
            + f', {angle}'
            + (f', {style}' if style else '')
            + ', single creature, clean background, highly detailed'
        )
        dest = os.path.join(dataset_dir, f'{stem}.png')
        ok, backend = _cgs.generate_still(
            dest,
            prompt,
            width=1024,
            height=1024,
            steps=20,
            cfg=4.0,
            seed=42 + i,
            model_family=fam,
            character_package=pkg,
            char_id=creature_id,
            log_fn=log_fn,
            extra_negative=_css._NEG,
            skip_qa=True,
            prompt_finalized=True,
            human_subject=False,
        )
        if ok and os.path.isfile(dest):
            rendered.append(dest)
            recs.append({'stem': stem, 'path': dest, 'kind': kind, 'angle_desc': angle_desc, 'backend': backend})
            log_fn(f'Preview {stem} OK ({backend})')
        else:
            log_fn(f'Preview {stem} failed ({backend})')
    report: dict = {'previews': recs, 'anchor': anchor_ref}
    if recs and anchor_ref and os.path.isfile(anchor_ref):
        base = _cj.load_items(_cj.PREVIEW_CHECKLIST)
        jobs = []
        for r in recs:
            sp = os.path.join(_css.sheet_dir(dataset_dir), 'strips', f'{r["stem"]}_strip.png')
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            _css.make_strip(anchor_ref, r['path'], sp, cand_label='LORA RENDER')
            r['strip'] = sp
            r['dino'] = _cid.similarity(anchor_ref, r['path']) if _cid.enabled() else None
            # body_plan= is what arms the checklist's body_plan question. Without
            # it cell_items() silently DROPS that item (the '{body_plan}' branch
            # continues on an empty plan), so the preview judge asked 8 questions
            # where the sheet asks 9 — and the one it skipped is the only one that
            # looks for a missing tail, missing arms or missing feet. That is how
            # the Pufferball's three previews scored 3/3 PASS on renders with no
            # tail and no arms (run 2026-08-26, log 'questions=8').
            jobs.append(
                {
                    'key': r['stem'],
                    'image': sp,
                    'items': _cj.cell_items(
                        r['angle_desc'], kind=r['kind'], base=base, body_plan=brief.get('body_plan') or ''
                    ),
                    'preamble': base.get('preamble', ''),
                }
            )
        vs = _cj.judge_batch(jobs, offload=True, log_fn=log_fn)
        for r in recs:
            v = vs.get(r['stem']) or {}
            r['judged'] = bool(v.get('judged'))
            r['ok'] = bool(v.get('ok', True))
            r['flags'] = v.get('flags', [])
            r['verdicts'] = v.get('verdicts', [])
        report['pass_count'] = sum(1 for r in recs if r.get('ok'))
        report['judged_any'] = any(r.get('judged') for r in recs)
        log_fn(
            f'preview judge: {report["pass_count"]}/{len(recs)} pass'
            + ('' if report['judged_any'] else ' (JUDGE OFFLINE — DINO only)')
        )
        # A 'major' never fails _aggregate's ok outside strict mode, so an
        # anatomy miss would sit in manifest.json and print PASS. Say it out
        # loud: body_plan is the whole reason the question is asked, and
        # whole_body is how a cropped foot announces itself.
        anat = [r['stem'] for r in recs if 'body_plan' in (r.get('flags') or [])]
        crop = [r['stem'] for r in recs if 'whole_body' in (r.get('flags') or [])]
        if anat:
            log_fn(
                'preview ANATOMY MISMATCH (body plan not met) on '
                + ', '.join(anat)
                + ' — check tail/limbs/feet before shipping'
            )
        if crop:
            log_fn(
                'preview body cut off by frame on ' + ', '.join(crop) + ' — smallest parts (feet) are the first lost'
            )
        report['body_plan_flagged'] = anat
        report['whole_body_flagged'] = crop
    return rendered, report


def _write_manifest(dataset_dir: str, data: dict) -> None:
    with open(os.path.join(dataset_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, default=str)


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def sheet_summary(report: dict) -> dict:
    cells = report.get('cells') or []
    return {
        'sheet_path': report.get('sheet_path'),
        'pass_count': report.get('pass_count'),
        'soft_count': report.get('soft_count'),
        'cell_count': report.get('cell_count'),
        'pass_rate': report.get('pass_rate'),
        'judged_any': report.get('judged_any'),
        'judge_tier': next((c.get('judge_tier') for c in cells if c.get('judge_tier')), None),
        'identity_model': (report.get('identity') or {}).get('model'),
        'excluded': [c.get('label') for c in cells if not c.get('ok')],
        'source': report.get('source'),
        'seconds': report.get('seconds'),
        'body_plan': (report.get('brief') or {}).get('body_plan') or '',
        'side_anchor': bool((report.get('anchors') or {}).get('side')),
    }


# ── the run ──────────────────────────────────────────────────────────────────


def run_creature_training(
    job: dict,
    creature_id: str,
    directive: str,
    *,
    image_paths: list[str] | None = None,
    model_family: str = 'flux',
    set_stage,
    complete_stage,
    fail_stage,
    log_fn,
    halt_check=None,
    phase: str = 'full',
) -> None:
    """Run one phase. ``full`` = sheet then (unless the review gate holds) train;
    ``sheet`` = stop after the sheet regardless; ``train`` = resume from a
    reviewed sheet on disk. Mutates *job* in place."""
    dataset_dir = os.path.join(DATASET_ROOT, creature_id)
    os.makedirs(dataset_dir, exist_ok=True)
    trigger = f'ZYG_CREATURE_{creature_id[:6].upper()}'
    opts = normalize_options(job.get('creature_options'))
    job['creature_options'] = opts
    job['creature_id'] = creature_id
    job['dataset_dir'] = dataset_dir
    job['trigger_token'] = trigger
    job['output_root'] = OUTPUT_ROOT
    fam = train_family()
    job['train_family'] = fam

    def _slog(msg: str, stage: str = 'Creature', level: str = 'INFO') -> None:
        log_fn(level, stage, msg)

    def _halt():
        if callable(halt_check):
            halt_check()

    try:
        from zyg_workflows import creature_sheet_service as _css

        refs = [p for p in (image_paths or []) if p and os.path.isfile(p)]
        source = opts['source'] or ('reference' if refs else 'scratch')
        job['source'] = source

        if phase in ('full', 'sheet'):
            _halt()
            set_stage(STAGE_BRIEF)
            _slog(
                f'brief: "{(directive or "")[:120]}" source={source} refs={len(refs)} angles={opts["angles"]}',
                'Stage 1',
            )
            try:
                from zyg_workflows import _comfy_client as _cc

                if _cc.server_reachable():
                    _cc.free_vram()  # the vision brief needs ~7 GB beside whatever ComfyUI held
            except Exception as _exc:
                _zyg_log.debug('comfy vram free before the vision brief skipped: %s', _exc)
            brief = _brief_for_run(job, directive, dataset_dir, refs, lambda m: _slog(m, 'Stage 1'))
            job['brief'] = brief
            job['creature_profile'] = brief['profile_key']
            with open(os.path.join(dataset_dir, 'brief.json'), 'w', encoding='utf-8') as fh:
                json.dump(brief, fh, indent=2)
            _slog(
                f'brief ({brief.get("brief_source")}): {brief.get("name")} / {brief.get("species")} — {brief.get("description", "")[:140]}',
                'Stage 1',
            )
            complete_stage(STAGE_BRIEF)

            _ensure_comfy_env()
            set_stage(STAGE_ANCHOR)
            _stage_map = {'Anchor': STAGE_ANCHOR, 'Multi-Angle Sheet': STAGE_SHEET, 'Sheet QC': STAGE_QC}
            _seen: set[str] = set()

            def _progress(name: str) -> None:
                st = _stage_map.get(name)
                if not st:
                    return
                # complete the earlier stages in order, mark this one running
                for prev in (STAGE_ANCHOR, STAGE_SHEET, STAGE_QC):
                    if prev == st:
                        break
                    if prev in _seen:
                        complete_stage(prev)
                _seen.add(st)
                set_stage(st)

            report = _css.build_sheet(
                dataset_dir,
                brief,
                source=source,
                reference_paths=refs,
                preset=opts['angles'],
                log_fn=lambda m: _slog(m, 'Stage 2'),
                halt_check=halt_check,
                progress_fn=_progress,
            )
            for st in (STAGE_ANCHOR, STAGE_SHEET, STAGE_QC):
                complete_stage(st)
            summary = sheet_summary(report)
            job['sheet_path'] = report.get('sheet_path')
            job['sheet_report'] = summary
            job['image_count'] = int(report.get('pass_count') or 0) + len(report.get('refs') or [])
            job['preview_images'] = [p for p in (report.get('sheet_root_copy'),) if p]
            _write_manifest(
                dataset_dir,
                {
                    'creature_id': creature_id,
                    'name': brief.get('name'),
                    'description': brief.get('description'),
                    'species': brief.get('species'),
                    'profile_key': brief.get('profile_key'),
                    'style_hint': brief.get('style_hint'),
                    'trigger_token': trigger,
                    'body_plan': brief.get('body_plan') or '',
                    'anchor_locks': brief.get('anchor_locks') or {},
                    'source': f'{source}_sheet',
                    'train_family': fam,
                    'sheet': report.get('sheet_root_copy'),
                    'sheet_report': summary,
                    'refs': [r.get('src') for r in report.get('refs') or []],
                    'images': [c.get('path') for c in report.get('cells') or [] if c.get('ok')],
                    'total': int(report.get('pass_count') or 0),
                    'status': 'sheet_ready',
                },
            )
            _slog(
                f'sheet ready: {summary["pass_count"]}/{summary["cell_count"]} cells pass'
                + ('' if summary['judged_any'] else ' — JUDGE OFFLINE (structural + DINO only)'),
                'Stage 2',
            )
            if phase == 'sheet' or opts['review_gate']:
                set_stage(STAGE_REVIEW)
                job['status'] = 'awaiting_review'
                job['review_requested'] = datetime.now(_AMS).isoformat()
                try:
                    _card = push_review_card(creature_id, job, report.get('sheet_root_copy') or '')
                    job['review_card_id'] = _card or job.get('review_card_id', '')
                    _slog(
                        'parked for operator review — Zero card queued '
                        + (f'({_card})' if _card else '(one was already open)')
                        + '; approve to caption + train, or reject',
                        'Review',
                    )
                except Exception as _rc_exc:  # a broken queue must not lose the park
                    log_fn('WARN', 'Review', f'review card push failed: {_rc_exc}')
                    _slog('parked for operator review — approve to caption + train, or reject', 'Review')
                return
        else:
            brief = job.get('brief') or _read_json(os.path.join(dataset_dir, 'brief.json'))
            report = _css.load_report(dataset_dir)
            if not brief or not report.get('cells'):
                raise RuntimeError('cannot resume: no reviewed sheet on disk for this creature')
            job['brief'] = brief
            complete_stage(STAGE_REVIEW)

        # ── captions + training + previews ───────────────────────────────
        _halt()
        set_stage(STAGE_CAPTIONS)
        tiles = _css.training_tiles(report, dataset_dir, trigger, brief, log_fn=lambda m: _slog(m, 'Stage 3'))
        if len(tiles) < 6:
            raise RuntimeError(f'only {len(tiles)} training tiles passed QC — need at least 6 to train')
        job['image_count'] = len(tiles)
        complete_stage(STAGE_CAPTIONS)

        _halt()
        set_stage(STAGE_TRAIN)
        from zyg_workflows import lora_trainer_service as _lts

        trainer = _lts.get_trainer()
        train_dir = os.path.join(dataset_dir, 'training')
        started = trainer.start_training(
            creature_id,
            train_dir,
            trigger_token=trigger,
            model_family=fam,
            output_root=OUTPUT_ROOT,
            # Without this the trainer validates the creature as a human portrait.
            validation_prompt=_val_prompt(brief, trigger),
        )
        if not started:
            reason = ''
            try:
                reason = (_lts.last_start_result(creature_id) or {}).get('reason', '')
            except Exception as _exc:
                _zyg_log.debug('trainer start-reason lookup failed: %s', _exc)
            if reason == 'already_trained':
                _slog(f'LoRA already trained for {fam} — reusing', 'Stage 4')
            else:
                raise RuntimeError(f'trainer refused to start ({reason or "unknown"}; family={fam})')
        _slog(f'SimpleTuner {fam} LoRA training started on {len(tiles)} tiles (trigger {trigger})', 'Stage 4')
        train_status = _wait_for_lora_training(creature_id, fam, lambda m: _slog(m, 'Stage 4'), halt_check=halt_check)
        lora_path = train_status.get('lora_path') or trainer.get_lora_path(
            creature_id, model_family=fam, output_root=OUTPUT_ROOT
        )
        job['lora_path'] = lora_path
        complete_stage(STAGE_TRAIN)

        _halt()
        set_stage(STAGE_PREVIEW)
        anchor_ref = ((report.get('anchors') or {}).get('identity') or {}).get('path')
        previews, preview_report = _render_previews(
            creature_id,
            brief,
            lora_path or '',
            fam,
            dataset_dir,
            trigger,
            anchor_ref,
            lambda m: _slog(m, 'Stage 5'),
        )
        job['preview_images'] = previews + [p for p in (report.get('sheet_root_copy'),) if p]
        job['preview_report'] = {k: v for k, v in preview_report.items() if k != 'previews'} | {
            'previews': [
                {k: r.get(k) for k in ('stem', 'path', 'ok', 'judged', 'flags', 'dino')}
                for r in preview_report.get('previews', [])
            ]
        }
        complete_stage(STAGE_PREVIEW)

        manifest = _read_json(os.path.join(dataset_dir, 'manifest.json'))
        manifest.update(
            {
                'lora_path': lora_path,
                'status': 'trained',
                'train_family': fam,
                'images': tiles,
                'total': len(tiles),
                'previews': previews,
                'preview_report': job['preview_report'],
            }
        )
        _write_manifest(dataset_dir, manifest)
        job['status'] = 'completed'
        job['result'] = {
            'creature_id': creature_id,
            'trigger_token': trigger,
            'dataset_dir': dataset_dir,
            'lora_path': lora_path,
            'output_root': OUTPUT_ROOT,
            'train_family': fam,
            'profile_key': brief.get('profile_key'),
            'preview_images': previews,
            'sheet_path': report.get('sheet_root_copy'),
            'sheet_report': job.get('sheet_report'),
            'preview_report': job['preview_report'],
            'image_count': len(tiles),
        }
        job['ended'] = datetime.now(_AMS).isoformat()
        _slog(f'Creature LoRA ready — trigger {trigger}, family {fam}, lora={lora_path}', 'Done')

    except Exception as exc:
        import traceback

        if 'stopped by user' in str(exc).lower():
            raise
        fail_stage(job.get('current_stage') or 'Creature Training', str(exc))
        job['status'] = 'failed'
        job['error'] = str(exc)
        job['ended'] = datetime.now(_AMS).isoformat()
        log_fn('ERROR', 'Creature Training', traceback.format_exc()[-800:])
