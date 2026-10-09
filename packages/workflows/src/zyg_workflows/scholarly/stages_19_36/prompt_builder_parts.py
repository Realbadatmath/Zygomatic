# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The slot-level pieces `_build_image_prompt` is assembled from.

`prompt_builder._make_build_image_prompt` binds the twenty-three stage locals
the closure used to read into one `PromptSlotContext` and then orchestrates the
helpers below, in the order the single file ran them. Every helper here is a
contiguous block of the old 489-line closure: same values, same log lines, same
mutations of the stage's rolling windows (`recent_emotions`, `recent_shot_sizes`,
`recent_shot_types`, `used_entities`), only reachable from a test.
"""

from __future__ import annotations

import logging as _zyg_logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._common import _INTENSITY_MOOD_SUFFIX, _OLLAMA_BASE_URL, _TEXT_FRAMING_FIX, _TEXT_SUBJECT_RE

# Same logger name the statements had in pipeline_scholarly, so the warnings of
# a run keep landing under one name.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')

# The Murch weight profile a caller gets when it passes none.
DEFAULT_SCENE_WEIGHTS = {'emotion': 0.45, 'story': 0.25, 'rhythm': 0.15, 'eye_trace': 0.10, 'continuity': 0.05}

QUALITY_FOOTER = (
    ', photorealistic, 8k, film grain, cinematic render, sharp focus, subject centered, symmetrical composition'
)
# Qwen-Image-2512 reads the whole prompt through a 7B encoder and obeys it
# (P-12): 'film grain' stacked on the writer's own grain, and 'subject centered,
# symmetrical composition' put a symmetry instruction on every still. The qwen
# footer keeps only what the renderer should reinforce.
QUALITY_FOOTER_QWEN = ', photorealistic, 8k, cinematic render, sharp focus'

EMOTION_MOOD_MAP = {
    'shock': 'shattered moment, raw emotion, stark lighting',
    'grief': 'grief and mourning, dim torchlight, emotional weight',
    'triumph': 'raised banners, crowd cheering, golden light flooding scene',
    'awe': 'monumental scale, golden hour, awe-inspiring panorama',
    'tension': 'figures in shadow, dramatic side lighting, tense standoff',
}
# The standard row names the emotion; the intense row names what the CAMERA does
# about it — how close, how hard the light, what is physically at stake in frame.
# Nothing here is graphic by default: the difference is proximity and force.
EMOTION_MOOD_MAP_INTENSE = {
    'shock': ('the instant of impact, a body caught mid-reaction, stark raking light, nothing else in frame'),
    'grief': ("a face collapsing at arm's length, shoulders folded in, close and unguarded, guttering low light"),
    'triumph': ('roaring faces and thrown-up arms, hard light breaking across the crowd, low heroic angle'),
    'awe': ('crushing scale against one small figure, smoke and haze, overwhelming depth'),
    'tension': ('jaw set, bared teeth and held breath, hard side lighting, the moment before it breaks'),
    'unease': ('something wrong at the edge of frame, cold light, held stillness, dread'),
    'fear': ('wide-eyed face lit from below, body recoiling, harsh shadow, raw panic'),
}
# The hook does not inherit its mood from the curve: slot 0 sits where the
# emotion is routinely 'calm' or 'mystery', neither of which is in the intense
# map, so the opening frame would have carried no mood row at all. No lighting
# clause here — the 'extreme' entry of _INTENSITY_MOOD_SUFFIX, which the hook
# always gets, already carries one, and repeating it eats CLIP's token budget.
HOOK_MOOD = ', the strongest single image in the film, held close to the lens — a face, a body mid-action'


@dataclass
class PromptSlotContext:
    """The stage locals `_build_image_prompt` closed over, in one object.

    The list and dict fields are the stage's own objects, not copies: the rolling
    windows below are mutated in place across slots exactly as the closure did.
    """

    arc_style_map: dict
    emotion_relief_slots: set
    shot_rotation: list
    style_suffixes: list
    debug: Callable
    era_variants: list
    extract_named_entities: Callable
    is_hook_slot: Callable
    is_modern_topic: bool
    log: Callable
    recent_emotions: list
    recent_shot_sizes: list
    recent_shot_types: list
    sch_intensity: dict
    sentence_event_tag: Callable
    shot_size_of: Callable
    slot_word_bounds: Callable
    tag_sentence: Callable
    used_entities: list
    ctx: Any
    narration_script: str
    pipeline_id: str
    pipeline_state: dict


@dataclass
class SlotSegment:
    """The narration window one image slot covers: its spoken text and sentence range."""

    text: str
    start: int
    end: int
    sentences: list


def slot_segment(slot_word_bounds, narration_script, idx, n_total, sentences) -> SlotSegment:
    """Time-lock slot `idx` to the words actually spoken during its audio window.

    `slot_word_bounds(idx, n_total)` gives the word range; the sentence range is
    the one spanning those words, used for tag/emotion/anchor lookups. The old
    even sentence split dumped the integer-division remainder into the last slot
    and drifted minutes off the audio mid-video.
    """
    _w0_seg, _w1_seg = slot_word_bounds(idx, n_total)
    _all_words_seg = narration_script.split()
    _seg_text = ' '.join(_all_words_seg[_w0_seg:_w1_seg])
    _cum_seg = 0
    _seg_start = None
    _seg_end = None
    for _si_seg, _sent_seg in enumerate(sentences):
        _slen_seg = len(_sent_seg.split())
        if _seg_start is None and _cum_seg + _slen_seg > _w0_seg:
            _seg_start = _si_seg
        if _cum_seg < _w1_seg:
            _seg_end = _si_seg + 1
        _cum_seg += _slen_seg
    _seg_start = _seg_start if _seg_start is not None else max(len(sentences) - 1, 0)
    _seg_end = _seg_end if _seg_end is not None and _seg_end > _seg_start else _seg_start + 1
    return SlotSegment(_seg_text, _seg_start, _seg_end, sentences[_seg_start:_seg_end])


def slot_emotion(emotion_curve, seg: SlotSegment, n_sentences: int) -> tuple[str, float]:
    """Murch rule #1: the peak emotion of the curve slice this slot covers.

    Returns `('calm', 0.2)` when there is no curve at all.
    """
    _slot_emotion = 'calm'
    _slot_intensity = 0.2
    if emotion_curve:
        _ec_start = int(seg.start * len(emotion_curve) / max(n_sentences, 1))
        _ec_end = int(seg.end * len(emotion_curve) / max(n_sentences, 1))
        _ec_slice = (
            emotion_curve[_ec_start:_ec_end] if _ec_end > _ec_start else emotion_curve[_ec_start : _ec_start + 1]
        )
        if _ec_slice:
            _peak = max(_ec_slice, key=lambda x: x['intensity'])
            _slot_emotion = _peak['emotion']
            _slot_intensity = _peak['intensity']
    return _slot_emotion, _slot_intensity


def slot_arc_zone(seg: SlotSegment, turning_points, n_sentences: int) -> str:
    """The story-arc zone of this slot: murch_engine's reading of the turning points.

    Falls back to a fixed fractional split of the script when murch_engine cannot
    answer, so the zone is never missing.
    """
    try:
        from zyg_workflows import murch_engine as _me2b

        return _me2b.get_arc_zone(int((seg.start + seg.end) // 2), turning_points, n_sentences)
    except Exception:
        frac = seg.start / max(n_sentences, 1)
        return (
            'exposition'
            if frac < 0.15
            else 'rising'
            if frac < 0.45
            else 'climax'
            if frac < 0.65
            else 'falling'
            if frac < 0.85
            else 'resolution'
        )


def enforce_emotion_diversity(recent_emotions, relief_slots, emotion, intensity, arc_zone) -> tuple[str, float]:
    """Force a calm/mystery beat when the last 5 emotions were all high-intensity.

    A genuine climax is never overridden. Appends the emotion this slot ends up
    with to `recent_emotions` (the stage's rolling window, capped at 10) and
    returns the possibly-corrected `(emotion, intensity)`.
    """
    if (
        len(recent_emotions) >= 5
        and not any(e in relief_slots for e in recent_emotions[-5:])
        and arc_zone not in ('climax',)
    ):
        emotion = 'mystery'
        intensity = min(intensity, 0.45)
    recent_emotions.append(emotion)
    if len(recent_emotions) > 10:
        recent_emotions.pop(0)
    return emotion, intensity


def slot_subject(extract_named_entities, used_entities, seg_text, fallback_subject) -> tuple[str, bool]:
    """Story clarity: what this slot is about, deduped against the last 3 images.

    Returns `(subject, subject_is_entity)`. `subject_is_entity` is False when the
    essay-title fallback was used, so the seed registry never locks a seed on the
    topic (P-09). A real entity is appended to `used_entities`.
    """
    _entity = extract_named_entities(seg_text)
    if _entity and _entity in used_entities[-3:]:
        _candidates = [
            w for w in seg_text.split() if w and w[0].isupper() and len(w) > 3 and w not in used_entities[-3:]
        ]
        if _candidates:
            _entity = _candidates[0]
    _subject = _entity if _entity else fallback_subject
    if _entity:
        used_entities.append(_entity)
    return _subject, bool(_entity)


def entity_seed(subject, pipeline_id):
    """The seed anchored on a named entity, salted per run, or None if unavailable.

    The per-run salt keeps one entity from reproducing the same noise layout
    across episodes (P-09).
    """
    try:
        from zyg_workflows import murch_engine as _me2d

        return _me2d.get_entity_seed(subject, salt=pipeline_id)
    except Exception:
        return None


def slot_event_tag(sentence_event_tag, tag_sentence, seg_sentences) -> str:
    """The event tag for the slot: the first sentence-level tag, else the modal tag.

    'historical archive' when the slot covers no sentence at all.
    """
    _event_tag = ''
    for _s in seg_sentences:
        _event_tag = sentence_event_tag(_s)
        if _event_tag:
            break
    if not _event_tag:
        _seg_tags = [tag_sentence(_s) for _s in seg_sentences]
        _event_tag = max(set(_seg_tags), key=_seg_tags.count) if _seg_tags else 'historical archive'
    return _event_tag


def scene_weight_profile(seg_text, scene_weights, murch_debug) -> dict:
    """The blended Murch weight profile for this slot's scene type.

    Returns the weights passed in when murch_engine cannot classify the text.
    """
    try:
        from zyg_workflows import murch_engine as _me2a

        _scene_info = _me2a.classify_scene_type(seg_text, murch_debug)
        return _scene_info.get('blended_weights', scene_weights)
    except Exception:
        return scene_weights


def slot_shot_type(
    idx,
    emotion,
    intensity,
    arc_zone,
    weights,
    subject,
    prev_prompt,
    murch_debug,
    *,
    hook_slot: bool,
    exposition_alternate: bool,
) -> str:
    """The shot grammar for this slot, arc-aware, with the legacy intensity ladder as fallback.

    `exposition_alternate` is the intensity dial: slots 1-4 are briefed exposition
    and exposition forced wide, so with the dial up they alternate medium/close.
    """
    try:
        from zyg_workflows import murch_engine as _me2b2

        return _me2b2.get_shot_type_grammar(
            idx,
            emotion,
            intensity,
            arc_zone,
            weights,
            subject,
            prev_prompt,
            murch_debug,
            hook_slot=hook_slot,
            exposition_alternate=exposition_alternate,
        )
    except Exception:
        if hook_slot:
            return 'extreme close-up, tight crop, raw arresting detail'
        if arc_zone == 'exposition' and exposition_alternate:
            return (
                'medium shot, cinematic, something at stake in frame'
                if idx % 2 == 1
                else 'close-up, tight focus, charged detail'
            )
        if intensity >= 0.85:
            return 'extreme close-up, tight crop'
        if intensity >= 0.65:
            return 'medium shot, dramatic angle'
        if intensity >= 0.45:
            return 'medium wide shot, cinematic'
        return 'wide establishing shot'


def enforce_shot_diversity(
    recent_shot_sizes,
    recent_shot_types,
    shot_rotation,
    shot_size_of,
    shot_type,
    arc_zone,
    *,
    flat_half: bool,
) -> str:
    """Rotate the framing away from a repeated shot SIZE, and return the shot to use.

    Compares shot size, not the full descriptor: 'medium shot, cinematic' and
    'medium shot, somber' read as one framing, and the Sikh Empire run came out
    20/41 medium because the old test compared the strings. Trips on the same size
    3× running or 3 of the last 4; the climax zone is exempt, where repeated
    close-ups are intentional. With `flat_half` the rotation may vary the framing
    but may not push a slot into a wide/aerial environment shot. Both rolling
    windows (sizes and types, capped at 6) are updated in place.
    """
    recent_shot_sizes.append(shot_size_of(shot_type))
    if len(recent_shot_sizes) > 6:
        recent_shot_sizes.pop(0)
    if arc_zone not in ('climax',):
        _cur_size = recent_shot_sizes[-1]
        _win = recent_shot_sizes[-4:]
        if (len(recent_shot_sizes) >= 3 and all(_s == _cur_size for _s in recent_shot_sizes[-3:])) or (
            len(_win) == 4 and _win.count(_cur_size) >= 3
        ):
            _blocked = {shot_size_of(_s) for _s in recent_shot_sizes[-2:]}
            if flat_half:
                _blocked |= {'ws', 'aerial'}
            for _rot in shot_rotation:
                if shot_size_of(_rot) not in _blocked:
                    shot_type = _rot
                    recent_shot_sizes[-1] = shot_size_of(_rot)
                    break
    recent_shot_types.append(shot_type)
    if len(recent_shot_types) > 6:
        recent_shot_types.pop(0)
    return shot_type


def composition_constraint(prev_focal_zone, emotion, arc_zone, murch_debug) -> str:
    """Layer 3b: the composition clause derived from the previous slot's focal zone.

    Empty when murch_engine cannot provide one; the slot is then framed without.
    """
    try:
        from zyg_workflows import murch_engine as _me3b

        return _me3b.get_composition_constraint(prev_focal_zone, emotion, arc_zone, murch_debug)
    except Exception as _exc:  # noqa: BLE001 — murch_engine raises its own errors
        _zyg_log.warning('composition constraint unavailable, this slot is framed without one: %s', _exc)
        return ''


def kuleshov_modifier(prev_prompt, intensity) -> str:
    """The Kuleshov clause: how this slot reads against the previous prompt's mood.

    Empty unless a calm predecessor is followed by a charged slot, or a tense one
    by a quiet slot.
    """
    if not prev_prompt:
        return ''
    _prev_calm = any(w in prev_prompt for w in ['wide', 'establishing', 'landscape', 'peaceful', 'flourished'])
    _prev_tense = any(w in prev_prompt for w in ['battle', 'death', 'fire', 'collapse', 'shock', 'extreme close'])
    if _prev_calm and intensity >= 0.6:
        return ', dramatic contrast with preceding calm, sudden visual shift'
    if _prev_tense and intensity <= 0.4:
        return ', reflective aftermath, quiet desolation, emotional release'
    return ''


def style_suffix(arc_style_map, style_suffixes, style_zone, idx) -> str:
    """The style suffix for this slot: its arc zone's row, else the flat rotation."""
    _arc_style_indices = arc_style_map.get(style_zone, [])
    if _arc_style_indices:
        return style_suffixes[_arc_style_indices[idx % len(_arc_style_indices)]]
    return style_suffixes[idx % len(style_suffixes)]


def counterpoint_prompt(
    pb: PromptSlotContext,
    idx,
    seg: SlotSegment,
    *,
    emotion,
    intensity,
    arc_zone,
    style_zone,
    subject,
    shot_type,
    turning_points,
    murch_debug,
    composition,
    anatomy_hint,
    hook_slot: bool,
) -> str | None:
    """Layer 2c: the finished counterpoint prompt for this slot, or None if it does not fire.

    Counterpoint swaps the literal moment for its metaphor and fires hardest at
    the peaks, so the intensity dial caps it (0.75 at high, 0.60 at extreme — the
    engine's own trigger floor, so a peak is effectively never intercepted) and
    the hook slot never counterpoints at all. With the dial up it is allowed only
    in the FALLING zone: on the Black Death body it swapped 9 slots for human-free
    aftermath and those document stills were the three weakest frames in the film.
    Disabled outright for modern/documentary topics.
    """
    _cp_suppress_above = None if not pb.sch_intensity['enabled'] else 0.60 if pb.sch_intensity['rank'] >= 2 else 0.75
    _cp_zone_ok = (not pb.sch_intensity['enabled']) or (arc_zone == 'falling')
    _ollama_url_cp = _OLLAMA_BASE_URL
    try:
        from zyg_workflows import murch_engine as _me2c

        if (
            not pb.is_modern_topic
            and not hook_slot
            and _cp_zone_ok
            and _me2c.should_apply_counterpoint(
                idx,
                emotion,
                intensity,
                arc_zone,
                turning_points,
                murch_debug,
                suppress_above=_cp_suppress_above,
            )
        ):
            _prebuilt = pb.ctx._prebuilt_prompts
            _pb_cp = _prebuilt[idx] if _prebuilt and idx < len(_prebuilt) else None
            if _pb_cp and isinstance(_pb_cp, dict) and _pb_cp.get('counterpoint'):
                _cp_prompt = _pb_cp['counterpoint']
            else:
                _cp_prompt = _me2c.build_counterpoint_prompt(
                    emotion,
                    subject,
                    seg.text,
                    shot_type,
                    _ollama_url_cp,
                    murch_debug,
                )
                # The batch pairs went through _text_subject_guard; an
                # ollama-built counterpoint did not. Same rule here.
                if _TEXT_SUBJECT_RE.search(_cp_prompt or '') and _TEXT_FRAMING_FIX not in (_cp_prompt or ''):
                    _cp_prompt = _cp_prompt.rstrip(' .,') + _TEXT_FRAMING_FIX
            _style = style_suffix(pb.arc_style_map, pb.style_suffixes, style_zone, idx)
            _era_suffix_cp = ', ' + pb.era_variants[idx % len(pb.era_variants)]
            _full_prompt = _cp_prompt + _style + _era_suffix_cp
            if composition:
                _full_prompt += f', {composition}'
            if anatomy_hint:
                _full_prompt += f', {anatomy_hint}'
            pb.log('INFO', 'Stage 3.5', f'Slot {idx}: counterpoint mode ({emotion})')
            return _full_prompt
    except Exception as _cpe:
        pb.debug('Stage 3.5', f'Counterpoint check failed: {_cpe}', level='WARN')
    return None


def intensity_suffix(sch_intensity, *, hook_slot: bool) -> str:
    """The intensity-dial suffix for this slot — the hook gets the level above the episode's.

    The batch writer already wrote the prompt with the intensity directive in its
    system prompt, so this suffix is reinforcement at the pixel level: FLUX
    responds to concrete render nouns far more reliably than to a directive.
    """
    return _INTENSITY_MOOD_SUFFIX[sch_intensity['hook_level'] if hook_slot else sch_intensity['level']]


def prebuilt_prompt(prebuilt_prompts, idx, *, quality_footer, suffix, era_suffix, anatomy_hint) -> str | None:
    """The batch-written (Claude Sonnet) prompt for this slot, plus its footers.

    None when the single upfront batch call produced nothing for `idx`. The 10-part
    prompt already covers style, lighting, camera, texture and realism, so only a
    minimal quality footer, the intensity suffix, the era anchor and the anatomy
    hint are appended.
    """
    if not (prebuilt_prompts and idx < len(prebuilt_prompts)):
        return None
    _pb_std = prebuilt_prompts[idx]
    _pre = _pb_std['standard'] if isinstance(_pb_std, dict) else _pb_std
    _pre_with_hints = _pre + quality_footer + suffix + era_suffix
    if anatomy_hint:
        _pre_with_hints += f', {anatomy_hint}'
    return _pre_with_hints


def fallback_scene_desc(pipeline_state, seg_start, subject) -> str:
    """Stage 3b's LLM scene description for this slot, or the subject word.

    `visual_tags[i]['scene_desc']` is a specific 15-30 word image description for
    the narration segment; anything shorter than 4 words is not usable.
    """
    _vt_fallback = pipeline_state.get('visual_tags', [])
    _vt_for_slot = _vt_fallback[seg_start] if _vt_fallback and seg_start < len(_vt_fallback) else {}
    _scene_desc = _vt_for_slot.get('scene_desc', '') or ''
    if not _scene_desc or len(_scene_desc.split()) < 4:
        _scene_desc = subject
    return _scene_desc


def emotion_mood(emotion, intensity, *, intense: bool, hook_slot: bool) -> str:
    """EMOTION > LOGIC: the mood row appended at high intensity, empty below the gate.

    With the dial up the gate drops from 0.70 to 0.55, so mid-range beats get
    pushed too, and the rows name what the camera does rather than the emotion.
    The hook always gets its own row, whatever the curve said.
    """
    _mood_gate, _mood_src = (0.55, EMOTION_MOOD_MAP_INTENSE) if intense else (0.70, EMOTION_MOOD_MAP)
    _emotion_mood = ''
    if emotion in _mood_src and intensity >= _mood_gate:
        _emotion_mood = ', ' + _mood_src[emotion]
    if hook_slot:
        _emotion_mood = HOOK_MOOD
    return _emotion_mood


def assemble_fallback_prompt(
    scene_desc,
    shot_type,
    *,
    mood,
    style,
    kuleshov,
    era_suffix,
    suffix,
    composition,
    anatomy_hint,
) -> str:
    """Join the rows of a from-scratch prompt in the order FLUX reads them.

    Scene, shot, mood, style, Kuleshov clause, era anchor and intensity suffix,
    then the optional composition constraint and anatomy hint.
    """
    _prompt = scene_desc + f', {shot_type}' + mood + style + kuleshov + era_suffix + suffix
    if composition:
        _prompt += f', {composition}'
    if anatomy_hint:
        _prompt += f', {anatomy_hint}'
    return _prompt
