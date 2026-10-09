# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Part 1 of a Stage 3.5 slot: the prompt, the seed and the ladder's opening state.

`generate_one` in `stages_37_54_flux_slot` was 646 lines, and the first third of
it decided everything the retry ladder then works from. Those statements are
here, in their original order, as six helpers plus one pure classifier:

* `compose_prompt` — `_build_image_prompt`, the dedup against the previous
  slot, the style prefix/suffix, the Qwen "photograph" register, the period
  backstops, the render-safety pass and the era anchor at the front;
* `resolve_seed` — the per-subject seed lock (P-09) and the fresh-seed branch;
* `abort_before_cuda` — the last stop check, which cannot be made mid-inference;
* `classify_anatomy_shot` / `choose_quality_tier` — the shot classification and
  the steps / guidance / model tier it picks;
* `apply_prompt_hooks` — the bible identity prefix, the anatomy suffix and the
  storyteller DSL overrides;
* `new_slot_state` — the per-slot review record and the `SlotState` the ladder
  carries from attempt to attempt.

What used to be thirty-odd locals of one frame crosses on `SlotPlan`: the
helpers read and rebind its fields instead of the frame's, so the orchestrator
is the call sequence and nothing else.
"""

import os
import re
from dataclasses import dataclass
from typing import Any

from zyg_workflows import gui_state
from zyg_workflows.pipeline_config import (
    _STYLE_LORA_CONFIG,
    _dsl,
)
from zyg_workflows.pipeline_scholarly import (
    _PERSON_NOUN_RE,
    _SEED_STOPWORDS,
    _period_hair_backstop,
    _period_noun_rewrite,
    _render_safety_rewrite,
    _smoke_cap,
)
from zyg_workflows.scholarly import stages_37_54_flux_state as _flux_state

# The shot words that make a frame an anatomy shot, and the ones that veto it.
# A wide establishing shot of a crowd is not an anatomy shot however many
# people stand in it, so the veto list wins.
_ANATOMY_SHOT_WORDS = (
    'close',
    'portrait',
    'figure',
    'person',
    'face',
    'tight',
    'chest',
    'waist',
    'bust',
)
_WIDE_SHOT_WORDS = (
    'wide',
    'establishing',
    'aerial',
    'drone',
    'overhead',
    'landscape',
)


@dataclass
class SlotPlan:
    """What one slot's prompt section decided, before the retry ladder runs.

    The nine fields `_build_image_prompt` returns, the seed, and the quality
    tier the shot classification picks. `prompt`, `gen_seed`, `n_steps` and
    `g_scale` are rebound by the helpers after it — the DSL hook rewrites all
    four at once — so a field here is the current value, not the first one.
    """

    idx: int = -1
    prompt: str = ''
    subj: str = ''
    tag: Any = None
    seg_preview: Any = None
    shot_type: str = ''
    emotion: Any = None
    seed_override: Any = None
    cp_used: Any = None
    subj_is_entity: Any = None
    gen_seed: int = 0
    is_anatomy_shot: bool = False
    n_steps: int = 0
    g_scale: float = 0.0
    model_label: str = ''


def compose_prompt(fs, ctx, idx):
    """Build slot *idx*'s FLUX prompt and return the `SlotPlan` it opens.

    In: the loop state (for `fs._last_prompt` and `fs._prev_focal_zone`) and the
    run context. Out: a plan whose `prompt` has been through the dedup, the
    visual-style prefix/suffix, the Qwen register fix, the period and
    render-safety rewrites and the front era anchor. Rebinds `fs._last_prompt`
    to the deduped prompt, which is the one state the next slot reads.
    """
    _debug = ctx._debug
    _era_lock = ctx._era_lock
    _STYLE_SUFFIXES = ctx._STYLE_SUFFIXES
    (
        _prompt,
        _subj,
        _tag,
        _seg_preview,
        _shot_type,
        _emotion,
        _seed_override,
        _cp_used,
        _subj_is_entity,
    ) = ctx._build_image_prompt(
        idx,
        ctx._n_flux_images,
        ctx._narration_sentences,
        ctx._fallback_subject,
        prev_prompt=fs._last_prompt,
        emotion_curve=ctx.pipeline_state.get('emotion_curve', []),
        turning_points=ctx._murch_turning_points,
        prev_focal_zone=fs._prev_focal_zone,
        murch_debug=ctx._murch_image_debug,
    )
    # Dedup: if prompt identical to last, force next style suffix
    if _prompt == fs._last_prompt:
        _alt_style = _STYLE_SUFFIXES[(idx + 1) % len(_STYLE_SUFFIXES)]
        _tmpl = ctx._FLUX_PROMPT_TEMPLATES.get(_tag, ctx._DEFAULT_FLUX_PROMPT)
        _prompt = _tmpl.format(subject=_subj) + _alt_style
    fs._last_prompt = _prompt

    # ── Visual style injection (documentary mode) ───────────────
    # Prepend prefix and append suffix from _STYLE_LORA_CONFIG so
    # the FLUX prompt reflects the user's chosen visual style.
    _sch_vscfg = _STYLE_LORA_CONFIG.get(ctx.visual_style, _STYLE_LORA_CONFIG['cinematic'])
    _sch_vs_prefix = _sch_vscfg.get('prefix', '')
    _sch_vs_suffix = _sch_vscfg.get('suffix', '')
    if _sch_vs_prefix:
        # Comma, not a space: "cinematic photograph 14th-century
        # Florence" read as one noun phrase (P-12).
        _prompt = f'{_sch_vs_prefix}, {_prompt}'
    if _sch_vs_suffix:
        _prompt = f'{_prompt}, {_sch_vs_suffix}'
    if ctx._sch_qwen_stills and 'photograph' in _prompt.lower():
        # One style register survives on Qwen: it obeys both
        # "photograph" and "oil painting realism" and paints
        # neither cleanly (P-12).
        _prompt_np = re.sub(r',?\s*oil painting realism', '', _prompt, flags=re.IGNORECASE).strip(' ,')
        if _prompt_np != _prompt:
            _debug(
                'Stage 3.5',
                f'Slot {idx}: dropped "oil painting realism" (photograph register on Qwen)',
            )
            _prompt = _prompt_np
    # ── Period backstops at the render choke point ──────────
    # Every prompt passes through here — prebuilt, counterpoint,
    # ollama-built and the no-Claude fallback — so this is where
    # the deterministic period pass is guaranteed to have run:
    # bare nouns -> period form, people without hair described
    # -> period hair line, render-gore nouns -> intact skin.
    # Idempotent, so the batch pass and this one do not stack.
    if _era_lock['is_historical']:
        _prompt, _bn_ch = _period_noun_rewrite(_prompt, _era_lock)
        _prompt, _hair_added = _period_hair_backstop(_prompt, _era_lock)
        if _bn_ch or _hair_added:
            _debug(
                'Stage 3.5',
                f'Slot {idx}: period backstop — '
                f'{"; ".join(_bn_ch[:3]) or "no bare nouns"}'
                f'{", hair line added" if _hair_added else ""}',
            )
    _prompt, _gore_ch = _render_safety_rewrite(_prompt, ctx._sch_intensity['rank'])
    if _gore_ch:
        _debug('Stage 3.5', f'Slot {idx}: render-safety — {"; ".join(_gore_ch[:3])}')
    # ── Era anchor at the FRONT ────────────────────────────
    # CLIP-L reads only the first ~320 chars of a FLUX prompt,
    # so the period must be the first thing it sees, not the
    # last. Short on purpose: the full anchor line sits at the
    # end for T5 / the Qwen encoder. Modern episodes: nothing.
    if _era_lock['is_historical'] and _era_lock.get('period_label'):
        _era_front = str(_era_lock['period_label']).strip().rstrip('.,')
        if _era_front.lower() not in _prompt[:160].lower():
            _prompt = f'{_era_front}, {_prompt}'
    return SlotPlan(
        idx=idx,
        prompt=_prompt,
        subj=_subj,
        tag=_tag,
        seg_preview=_seg_preview,
        shot_type=_shot_type,
        emotion=_emotion,
        seed_override=_seed_override,
        cp_used=_cp_used,
        subj_is_entity=_subj_is_entity,
    )


def resolve_seed(fs, ctx, plan):
    """Return slot *plan*'s generation seed, locking it per subject when it may be.

    In: the subject, tag and prompt the plan carries. Out: the seed, and — when
    the subject is a real named person or entity — a new entry in
    `fs._subject_seed_registry` so every later slot about it renders the same
    anatomy. Environment and abstract tags always get a fresh seed: there,
    variety beats consistency.
    """
    _debug = ctx._debug
    _IDENTITY_TAGS = fs._IDENTITY_TAGS
    _subject_seed_registry = fs._subject_seed_registry
    # ───────────────────────────────────────────────────────────
    # For identity tags (people, characters): reuse the same seed
    # each time the subject appears — keeps anatomy consistent.
    # For environment/abstract tags: always use a fresh random seed
    # so backgrounds vary naturally.
    # A seed is LOCKED only for a real named person/entity
    # (P-09): identity tag AND the subject came from the slot
    # text (not the essay-title fallback, not a stopword the
    # extractor promoted) AND it is either a multi-word name
    # or the prompt actually names a person. "black death"
    # locked seed 6141 on every slot of every episode.
    _subj_key = plan.subj.lower().strip()[:40]
    _fallback_key = str(ctx._fallback_subject or '').lower().strip()[:40]
    _lock_seed = bool(
        plan.tag in _IDENTITY_TAGS
        and plan.subj_is_entity
        and _subj_key
        and _subj_key != _fallback_key
        and _subj_key not in _SEED_STOPWORDS
        and (len(_subj_key.split()) >= 2 or _PERSON_NOUN_RE.search(plan.prompt) is not None)
    )
    if _lock_seed:
        if _subj_key not in _subject_seed_registry:
            # Assign seed: prefer murch entity hash, else random
            _subject_seed_registry[_subj_key] = (
                plan.seed_override if plan.seed_override is not None else fs._rnd_flux.randint(0, 2**31)
            )
            _debug(
                'Stage 3.5',
                f'Seed registry: new subject "{_subj_key}" → seed {_subject_seed_registry[_subj_key]}',
            )
        else:
            _debug(
                'Stage 3.5',
                f'Seed registry: reusing seed {_subject_seed_registry[_subj_key]} for "{_subj_key}"',
            )
        _gen_seed = _subject_seed_registry[_subj_key]
    else:
        # Environment/abstract/fallback — always fresh (variety > consistency)
        _gen_seed = fs._rnd_flux.randint(0, 2**31)
        if plan.tag in _IDENTITY_TAGS:
            _why_nolock = (
                'title fallback'
                if (not plan.subj_is_entity or _subj_key == _fallback_key)
                else 'stopword'
                if _subj_key in _SEED_STOPWORDS
                else 'single word, no person named in prompt'
            )
            _debug('Stage 3.5', f'Seed registry: "{_subj_key}" not locked ({_why_nolock}) — fresh seed')
    return _gen_seed


def abort_before_cuda(ctx, idx):
    """True when the run was asked to stop, checked immediately before the CUDA call.

    In: the run context and the slot number. Out: whether this slot must be
    abandoned. Inference cannot be aborted once it has started, so this is the
    last point at which a stop costs nothing; the warning it logs names both
    the flag and the event so a stop that came from the other one is visible.
    """
    _inner_stop_ev = ctx.job.get('stop_event')
    if (_inner_stop_ev and _inner_stop_ev.is_set()) or gui_state._pipeline_stop_flag:
        ctx._debug(
            'Stage 3.5',
            f'FLUX _generate_one({idx}) aborted before CUDA call '
            f'[stop_flag={gui_state._pipeline_stop_flag}, stop_event={_inner_stop_ev.is_set() if _inner_stop_ev else False}]',
            level='WARN',
        )
        return True
    return False


def classify_anatomy_shot(shot_type):
    """True when *shot_type* describes a frame whose anatomy a viewer can inspect.

    In: the shot description `_build_image_prompt` chose. Out: whether the slot
    gets the higher step count and the anatomy gates. A close or tight framing
    of a person qualifies; a wide, aerial or landscape framing never does, so
    the veto words override the anatomy words rather than adding to them.
    """
    _shot_lo = shot_type.lower()
    return any(kw in _shot_lo for kw in _ANATOMY_SHOT_WORDS) and not any(kw in _shot_lo for kw in _WIDE_SHOT_WORDS)


def quality_tier(qwen_stills, is_anatomy_shot, smoke):
    """Return `(steps, guidance, model_label)` for one slot's inference tier.

    In: whether the run renders on Qwen-Image, whether the frame is an anatomy
    shot, and whether the smoke cap is on. Out: the three numbers the sampler
    is called with. Qwen has one validated video-still tier (20 steps / cfg
    2.5); on FLUX only anatomy shots pay for 20 steps, everything else renders
    schnell at 4 steps and guidance 0.
    """
    if qwen_stills:
        # Qwen-Image-2512: 20 steps / cfg 2.5 is the validated
        # video-still tier (video_flux_still_service). Ladder:
        # attempt 2 re-rolls the seed at the same tier; attempt
        # 3 (era / anatomy rungs) climbs to 28 steps / cfg 3.5
        # with the defect terms routed into the LIVE negative
        # (P-11). Real CFG here, so _FLUX_NEGATIVE and the era
        # negatives are live for the first time.
        return (8 if smoke else 20), 2.5, 'Qwen-Image-2512'
    if is_anatomy_shot:
        # Smoke-test mode: skip expensive anatomy settings to avoid VRAM OOM
        return (
            (4 if smoke else 20),
            (0.0 if smoke else 3.5),
            'FLUX.1-schnell' if smoke else 'FLUX.1-schnell/quality',
        )
    return 4, 0.0, 'FLUX.1-schnell'


def choose_quality_tier(ctx, plan):
    """Classify slot *plan*'s shot and set the tier it renders at.

    In: the plan with its `shot_type`. Out: nothing — `is_anatomy_shot`,
    `n_steps`, `g_scale` and `model_label` are set on the plan and the mode line
    is logged, so the receipt says which tier a frame was rendered at.
    """
    # ── Adaptive inference quality: anatomy shots get higher steps ──
    plan.is_anatomy_shot = classify_anatomy_shot(plan.shot_type)
    plan.n_steps, plan.g_scale, plan.model_label = quality_tier(
        ctx._sch_qwen_stills,
        plan.is_anatomy_shot,
        _smoke_cap() > 0,
    )
    ctx._debug(
        'Stage 3.5',
        f'Slot {plan.idx}: {"anatomy" if plan.is_anatomy_shot else "environment"} mode — '
        f'steps={plan.n_steps} {"cfg" if ctx._sch_qwen_stills else "guidance"}={plan.g_scale} '
        f'shot="{plan.shot_type[:40]}"',
    )


def apply_prompt_hooks(ctx, plan):
    """Graft the character bible and the storyteller DSL onto slot *plan*.

    In: the plan with its tier already chosen. Out: nothing — `prompt` gains the
    bible identity prefix and the anatomy suffix on anatomy shots, and the DSL
    may rewrite `prompt`, `gen_seed`, `n_steps` and `g_scale` together. Both
    hooks are optional by design: a failure in either is logged and the slot
    renders with what it already had.
    """
    # Tier 1: bible identity + first-pass anatomy suffix (attempt #1 quality).
    if plan.is_anatomy_shot:
        try:
            from zyg_workflows import character_bible_service as _cbs_an

            _pkg_an = ctx.pipeline_state.get('character_bible')
            _ident_an = _cbs_an.identity_prompt_prefix(_pkg_an)
            if _ident_an and _ident_an.lower() not in plan.prompt.lower():
                plan.prompt = f'{_ident_an}, {plan.prompt}'
            _anat_suf = _cbs_an.scholarly_anatomy_prompt_suffix(_pkg_an)
            if _anat_suf.lower() not in plan.prompt.lower():
                plan.prompt = f'{plan.prompt}, {_anat_suf}'
        except Exception as _an_inj_e:
            ctx._debug('Stage 3.5', f'Anatomy prompt inject skipped: {_an_inj_e}', level='WARN')

    if _dsl is not None and _dsl.is_enabled('storyteller'):
        try:
            from zyg_workflows.dsl_runtime import merge_flux_generation_params, scene_yaml_path

            _st_dsl_dir = os.path.join(ctx.out_dir, 'dsl')
            plan.prompt, plan.gen_seed, plan.n_steps, plan.g_scale = merge_flux_generation_params(
                plan.prompt,
                seed=plan.gen_seed,
                steps=plan.n_steps,
                cfg=plan.g_scale,
                dsl_yaml_path=scene_yaml_path(_st_dsl_dir, plan.idx),
                is_schnell=(not ctx._sch_qwen_stills and plan.n_steps <= 8 and plan.g_scale <= 0.01),
            )
        except Exception as _dsl_st_e:
            ctx._debug('Stage 3.5', f'DSL FLUX merge skipped: {_dsl_st_e}', level='WARN')


def always_reroll_enabled(environ=None):
    """True when ZYG_SCHOLARLY_ALWAYS_REROLL asks for a second take of every slot.

    In: an environment mapping (defaults to the process environment). Out: the
    flag. ZYG_SCHOLARLY_ALWAYS_REROLL=1 renders a second take of EVERY slot and
    keeps the better one, even when the first is clean. Off by default: it
    roughly doubles Stage 3.5 (~40 min -> ~80 min on a 45-slot film) to improve
    slots that nothing flagged. On, the ladder is unchanged — the extra take is
    just no longer conditional on a defect.
    """
    _env = os.environ if environ is None else environ
    return _env.get('ZYG_SCHOLARLY_ALWAYS_REROLL', '0').lower() in ('1', 'true', 'yes')


def new_slot_state(fs, plan):
    """Open slot *plan*'s review record and return the `SlotState` the ladder carries.

    In: the loop state and the finished plan. Out: a `SlotState` holding the
    prompt, seed and tier plus the seven flags one attempt tells the next; as a
    side effect `fs._slot_review[idx]` is created, so the completion line can
    name the slots a judge never looked at instead of claiming they all passed.
    """
    # Per-slot review record: which judge actually looked at the
    # winning frame. The completion line lists slots by number
    # from this, instead of "every slot cleared its gates".
    fs._slot_review[plan.idx] = {
        'anatomy': 'unreviewed',
        'typography': 'unreviewed',
        'era': 'unreviewed',
        'score': None,
        'attempts': 0,
        'repaired': [],
        'flagged': [],
        'winner_attempt': None,
    }
    return _flux_state.SlotState(
        idx=plan.idx,
        _prompt=plan.prompt,
        _subj=plan.subj,
        _n_steps=plan.n_steps,
        _g_scale=plan.g_scale,
        _gen_seed=plan.gen_seed,
        _is_anatomy_shot=plan.is_anatomy_shot,
        _qa_attempts=[],
        _best_path=None,
        _best_qa_score=-1.0,
        _clause_used=False,  # the suppression clause ran for THIS slot
        _era_rung_used=0,  # era prompt-edit rungs taken on THIS slot
        _vlm_fail_prev=False,  # VLM gate flagged the previous attempt
        _vlm_era_fail_prev=False,  # ...and it was an anachronism
        _vlm_text_fail_prev=False,  # ...or it was readable lettering
        _always_reroll=always_reroll_enabled(),
    )
