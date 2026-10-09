# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Layer 2 — scene type, shot grammar, counterpoint mode, entity seed anchoring.

Moved verbatim from murch_engine.py lines 1410-1841.
"""

from __future__ import annotations
import json
import hashlib

from zyg_workflows.net import safe_urlopen

from zyg_workflows.murch_engine.base import (
    MURCH_LLM_MODEL,
    _dbg,
    _ollama_response_text,
)

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2a — Scene Type Classifier + Weight Profiles
# ─────────────────────────────────────────────────────────────────────────────

_SCENE_TYPE_KEYWORDS = {
    'action': [
        'battle',
        'war',
        'fought',
        'charged',
        'attacked',
        'cavalry',
        'siege',
        'storm',
        'fled',
        'pursuit',
        'clash',
    ],
    'speech': [
        'declared',
        'announced',
        'speech',
        'said',
        'proclaimed',
        'argued',
        'debated',
        'wrote',
        'letter',
        'speech',
        'testified',
    ],
    'reflection': [
        'remembered',
        'legacy',
        'historians',
        'significance',
        'impact',
        'meaning',
        'consider',
        'perspective',
        'understood',
        'century later',
    ],
    'revelation': [
        'discovered',
        'revealed',
        'uncovered',
        'found',
        'realized',
        'secret',
        'truth',
        'exposed',
        'confessed',
        'emerged',
    ],
    'transition': [
        'meanwhile',
        'however',
        'years later',
        'in contrast',
        'by this time',
        'following this',
        'as a result',
        'turning point',
    ],
}

_SCENE_WEIGHT_PROFILES = {
    # emotion%, story%, rhythm%, eye_trace%, continuity%
    'action': {'emotion': 0.40, 'story': 0.15, 'rhythm': 0.30, 'eye_trace': 0.10, 'continuity': 0.05},
    'speech': {'emotion': 0.45, 'story': 0.30, 'rhythm': 0.10, 'eye_trace': 0.10, 'continuity': 0.05},
    'reflection': {'emotion': 0.50, 'story': 0.20, 'rhythm': 0.10, 'eye_trace': 0.10, 'continuity': 0.10},
    'revelation': {'emotion': 0.60, 'story': 0.25, 'rhythm': 0.10, 'eye_trace': 0.05, 'continuity': 0.00},
    'transition': {'emotion': 0.20, 'story': 0.20, 'rhythm': 0.20, 'eye_trace': 0.20, 'continuity': 0.20},
}


def classify_scene_type(text: str, debug_log: list | None = None) -> dict[str, float]:
    """
    Classify a text segment into scene type probabilities.
    Returns {scene_type: confidence, ...} and the blended weight profile.
    """
    if debug_log is None:
        debug_log = []

    text_lower = text.lower()
    raw_scores: dict[str, float] = {}
    for stype, kws in _SCENE_TYPE_KEYWORDS.items():
        hits = sum(1 for kw in kws if kw in text_lower)
        raw_scores[stype] = hits

    total = sum(raw_scores.values()) or 1
    confidences = {k: v / total for k, v in raw_scores.items()}

    if max(confidences.values()) < 0.3:
        # Low confidence — default to reflection (most neutral)
        confidences['reflection'] = max(confidences.get('reflection', 0), 0.5)
        _dbg(debug_log, 'classify_scene', 'Low confidence — defaulting to reflection', 'DEBUG')

    # Blend weight profiles by confidence
    blended_weights: dict[str, float] = {k: 0.0 for k in ('emotion', 'story', 'rhythm', 'eye_trace', 'continuity')}
    for stype, conf in confidences.items():
        if conf > 0:
            profile = _SCENE_WEIGHT_PROFILES[stype]
            for dim in blended_weights:
                blended_weights[dim] += profile[dim] * conf

    # Normalize blended weights
    wsum = sum(blended_weights.values()) or 1
    blended_weights = {k: round(v / wsum, 3) for k, v in blended_weights.items()}

    top_type = max(confidences, key=confidences.get)
    _dbg(
        debug_log,
        'classify_scene',
        f'Scene type: {top_type} ({confidences[top_type]:.0%}) | weights={blended_weights}',
        'DEBUG',
    )

    return {
        'confidences': confidences,
        'top_type': top_type,
        'blended_weights': blended_weights,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2b — Shot Grammar with Arc Awareness
# ─────────────────────────────────────────────────────────────────────────────

# Shot grammar state machine: tracks position in current shot sequence per named entity
_SHOT_GRAMMAR_STATE: dict[str, int] = {}

# Grammar sequence: wide → medium → close → detail → (reset to wide or medium)
_SHOT_GRAMMAR_SEQUENCE = [
    'wide establishing shot',
    'medium shot, cinematic',
    'close-up, dramatic',
    'extreme close-up, detail',
    'medium wide shot, pull back',
]


def get_shot_type_grammar(
    slot_idx: int,
    emotion: str,
    intensity: float,
    arc_zone: str,
    scene_weights: dict,
    subject: str,
    previous_shot: str,
    debug_log: list | None = None,
    hook_slot: bool = False,
    exposition_alternate: bool = False,
) -> str:
    """
    Layer 2b: Determine shot type using grammar + emotion + arc zone.
    Rules:
      - Hook slot: bypasses everything — the opening frame is a hard close-up
      - Climax zone: emotion overrides grammar (close-up / extreme close-up for high intensity)
      - Rising zone: progress through grammar (wide → medium → close as intensity rises)
      - Exposition/Resolution: prefer wide/medium regardless of intensity
      - Scene type weights influence tightness preference

    `hook_slot` exists because image 0 always resolves to arc_zone='exposition'
    (get_arc_zone starts at 'exposition' and only advances past a turning point),
    and exposition force-returns a wide establishing shot below. The first frame
    a viewer ever saw was therefore guaranteed to be the widest, calmest one in
    the episode — the opposite of what an opening frame is for. Callers that
    want a cold open pass hook_slot=True; every existing caller keeps the old
    behaviour by default.

    `exposition_alternate` (2026-08-25, intensity dial): exposition used to
    force EVERY slot in the zone wide, so slots 1-4 of a high-intensity episode
    opened on four establishing shots in a row right after the hook — the
    measured "flat half" of the Black Death body. When True, exposition slots
    alternate medium / close by slot index instead (slot 0 is the hook and never
    reaches here). Default False keeps the legacy lock.
    """
    if debug_log is None:
        debug_log = []

    if hook_slot:
        shot = 'extreme close-up, tight crop, raw arresting detail'
        _dbg(debug_log, 'shot_grammar', f'slot={slot_idx} HOOK SLOT → force {shot} (exposition lock bypassed)', 'DEBUG')
        return shot

    # Arc zone overrides
    if arc_zone == 'exposition':
        if exposition_alternate:
            shot = (
                'medium shot, cinematic, something at stake in frame'
                if slot_idx % 2 == 1
                else 'close-up, tight focus, charged detail'
            )
            _dbg(
                debug_log,
                'shot_grammar',
                f'slot={slot_idx} arc=exposition → alternate {shot} (wide lock lifted)',
                'DEBUG',
            )
            return shot
        # Always start wide — establish the world
        shot = 'wide establishing shot, cinematic'
        _dbg(debug_log, 'shot_grammar', f'slot={slot_idx} arc=exposition → force wide', 'DEBUG')
        return shot

    if arc_zone == 'resolution':
        # Wind down — prefer medium or medium-wide
        shot = 'medium wide shot, reflective' if intensity < 0.5 else 'medium shot, somber'
        _dbg(debug_log, 'shot_grammar', f'slot={slot_idx} arc=resolution → {shot}', 'DEBUG')
        return shot

    if arc_zone == 'climax':
        # Pure emotion — override grammar completely
        if intensity >= 0.85:
            shot = 'extreme close-up, tight crop, raw emotion'
        elif intensity >= 0.65:
            shot = 'medium shot, dramatic angle, intense'
        else:
            shot = 'medium wide shot, tension building'
        _dbg(
            debug_log,
            'shot_grammar',
            f'slot={slot_idx} arc=climax emo={emotion} intensity={intensity:.2f} → {shot}',
            'DEBUG',
        )
        return shot

    # Rising / Falling: use grammar progression scaled by emotion weight
    emotion_weight = scene_weights.get('emotion', 0.45)
    rhythm_weight = scene_weights.get('rhythm', 0.15)

    # Grammar progression index: 0=wide, 1=medium, 2=close, 3=extreme, 4=pullback
    grammar_idx = min(4, int(intensity * 4 * (emotion_weight + rhythm_weight)))

    # Avoid repeating the exact previous shot
    candidate = _SHOT_GRAMMAR_SEQUENCE[grammar_idx]
    if candidate == previous_shot and grammar_idx < 4:
        grammar_idx += 1
        candidate = _SHOT_GRAMMAR_SEQUENCE[grammar_idx]

    _dbg(
        debug_log,
        'shot_grammar',
        f'slot={slot_idx} arc={arc_zone} intensity={intensity:.2f} grammar_idx={grammar_idx} → {candidate}',
        'DEBUG',
    )
    return candidate


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2c — Counterpoint Mode
# ─────────────────────────────────────────────────────────────────────────────

# Track consecutive illustrative images to decide when to apply counterpoint
_CONSECUTIVE_ILLUSTRATIVE = 0

_COUNTERPOINT_PROMPTS = {
    'triumph': 'the hidden cost of victory — empty battlefield at dusk, silent mourning, emotional aftermath',
    'shock': 'the moment before the disaster — ordinary life just before catastrophe, false calm',
    'grief': 'what was lost — a place of memory, an abandoned home, a portrait of the departed',
    'tension': 'the people caught between the forces — ordinary civilians watching from a distance',
    'awe': 'the human scale against the monumental — a single figure dwarfed by the vast landscape',
    'mystery': 'the seeker, not the secret — an explorer or scholar studying ancient evidence',
    'unease': 'the shadow before the storm — ominous gathering clouds, quiet streets, waiting faces',
    'calm': 'the illusion of peace — surface tranquility concealing underlying complexity',
}


def should_apply_counterpoint(
    slot_idx: int,
    emotion: str,
    intensity: float,
    arc_zone: str,
    turning_points: list[dict],
    debug_log: list | None = None,
    suppress_above: float | None = None,
) -> bool:
    """
    Layer 2c: Decide if this slot should use counterpoint (metaphorical) image.
    Rules:
      - Only at arc turning points or when intensity >= 0.65
      - Not more than once every 3 consecutive images
      - Never in exposition (need clear context first)
      - Never above `suppress_above` intensity, when a caller sets it

    `suppress_above` exists because counterpoint fires hardest at exactly the
    peaks: at intensity >= 0.60 near a turning point it replaces the literal
    moment with its metaphor ('shock' → "ordinary life just before catastrophe,
    false calm"). That is the right call for a restrained cut and the wrong one
    for a high-impact cut, so callers running the intensity dial up pass a
    ceiling. Default None = unchanged behaviour.
    """
    global _CONSECUTIVE_ILLUSTRATIVE
    if debug_log is None:
        debug_log = []

    if suppress_above is not None and intensity >= suppress_above:
        _CONSECUTIVE_ILLUSTRATIVE += 1
        _dbg(
            debug_log,
            'counterpoint',
            f'slot={slot_idx}: intensity={intensity:.2f} >= suppress_above='
            f'{suppress_above:.2f} → literal image, counterpoint suppressed',
            'DEBUG',
        )
        return False

    if arc_zone == 'exposition':
        _CONSECUTIVE_ILLUSTRATIVE += 1
        return False

    # Check if this slot is near a turning point
    near_turning_point = any(
        abs(tp['sentence_idx'] - slot_idx) <= 2 and tp['type'] in ('climax', 'falling', 'revelation')
        for tp in turning_points
    )

    if _CONSECUTIVE_ILLUSTRATIVE >= 3 and intensity >= 0.55:
        # Break the pattern — viewer needs variety
        _CONSECUTIVE_ILLUSTRATIVE = 0
        _dbg(
            debug_log,
            'counterpoint',
            f'slot={slot_idx}: 3+ illustrative in a row + intensity={intensity:.2f} → counterpoint',
            'DEBUG',
        )
        return True

    if near_turning_point and intensity >= 0.60:
        _CONSECUTIVE_ILLUSTRATIVE = 0
        _dbg(
            debug_log,
            'counterpoint',
            f'slot={slot_idx}: near turning point + intensity={intensity:.2f} → counterpoint',
            'DEBUG',
        )
        return True

    _CONSECUTIVE_ILLUSTRATIVE += 1
    return False


def reset_counterpoint_state():
    """Call at start of each pipeline run."""
    global _CONSECUTIVE_ILLUSTRATIVE
    _CONSECUTIVE_ILLUSTRATIVE = 0


def build_counterpoint_prompt(
    emotion: str,
    subject: str,
    narration_segment: str,
    shot_type: str,
    ollama_url: str,
    debug_log: list | None = None,
) -> str:
    """Build counterpoint image prompt — shows consequence/cause rather than direct depiction."""
    if debug_log is None:
        debug_log = []

    base = _COUNTERPOINT_PROMPTS.get(emotion, 'the human cost and quiet aftermath')
    # Try to get a more specific counterpoint from the LLM
    if not ollama_url:
        return f'{base}, {subject}, {shot_type}, cinematic documentary style, historical atmosphere, emotional depth'
    try:
        prompt = (
            f'A historical documentary narration says: "{narration_segment[:150]}"\n'
            f'The emotion is {emotion}.\n'
            f'Instead of directly depicting this event, describe ONE image that shows '
            f'its EMOTIONAL CONSEQUENCE or CAUSE — something metaphorical, not literal.\n'
            f'The subject involves: {subject}\n'
            f'Keep it to one sentence. Describe what the camera would show.\n'
            f'Response (one sentence only):'
        )
        payload = json.dumps(
            {
                'model': MURCH_LLM_MODEL,
                'prompt': prompt,
                'stream': False,
                'think': False,
                'options': {'temperature': 0.4, 'num_predict': 60},
            }
        ).encode()
        with safe_urlopen(f'{ollama_url}/api/generate', data=payload, timeout=12) as resp:
            raw_resp = _ollama_response_text(resp.read())
        if len(raw_resp) > 20:
            _dbg(debug_log, 'counterpoint_prompt', f'LLM counterpoint: {raw_resp[:80]}', 'DEBUG')
            return f'{raw_resp}, {shot_type}, cinematic documentary style, highly detailed'
    except Exception as e:
        _dbg(debug_log, 'counterpoint_prompt', f'LLM counterpoint call failed: {e} — using template', 'WARN')

    return f'{base}, {subject}, {shot_type}, cinematic documentary style, historical atmosphere, emotional depth'


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2d — Named Entity Seed Anchoring
# ─────────────────────────────────────────────────────────────────────────────

_ENTITY_SEEDS: dict[str, int] = {}


def get_entity_seed(entity: str, base_seed: int = 42, salt: str = '') -> int:
    """
    Layer 2d: Return a consistent FLUX seed for a named entity.
    Same entity always gets the same seed → visual consistency across images.

    `salt` (2026-08-25) is mixed into the hash so one subject can carry several
    seeds — per slot, for instance, so "black death" in slot 1 and slot 2 no
    longer render the same picture when the subject fell back to the topic.
    salt='' reproduces the historical value bit for bit (same md5 over
    entity.lower(), same cache key), so every existing caller is unchanged.
    Pass it BY KEYWORD: the second positional slot is base_seed.
    """
    if not entity:
        return base_seed
    _salt = str(salt) if salt else ''
    _key = entity if not _salt else f'{entity}\x1f{_salt}'
    if _key not in _ENTITY_SEEDS:
        # Hash entity name (+ salt) to a seed in 1000–9999 range
        _src = entity.lower() if not _salt else f'{entity.lower()}\x1f{_salt}'
        h = int(hashlib.md5(_src.encode(), usedforsecurity=False).hexdigest(), 16)
        _ENTITY_SEEDS[_key] = (h % 9000) + 1000
    return _ENTITY_SEEDS[_key]


def reset_entity_seeds():
    """Call at start of each pipeline run to allow fresh seed allocation."""
    _ENTITY_SEEDS.clear()
