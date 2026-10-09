"""pipeline_scholarly.constants — the narration clock, the seed-registry guards, the title/duration helpers and the visual intensity dial.

Lines 63-300 of the original pipeline_scholarly.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from zyg_workflows import pipeline_config as _pipeline_config
from zyg_workflows import scholarly_motion as _scholarly_motion
from zyg_workflows.pipeline_config import _SCHOLARLY_SMOKE_MAX_IMAGES
import os
import re
import time
import logging as _zyg_logging

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


# Wall-clock moment this module was imported. The staleness gate in
# _run_scholarly_pipeline compares it against this file's mtime so a run
# executing pre-edit code says so instead of quietly passing for the new code.
_MODULE_IMPORTED_AT = time.time()


def _smoke_cap() -> int:
    """Smoke-image cap read at CALL time, not import time (S-02).

    ``_SCHOLARLY_SMOKE_MAX_IMAGES`` is from-imported above, so that name is a
    COPY bound when this module was first imported. A harness that sets the
    attribute on ``zyg_workflows.pipeline_config`` — its definition site — would
    never be seen by the copy, and a "smoke" run would render the full
    production image set while reporting a smoke run. Both names are read and
    the higher wins, so either setter works.
    """
    _live = getattr(_pipeline_config, '_SCHOLARLY_SMOKE_MAX_IMAGES', _SCHOLARLY_SMOKE_MAX_IMAGES)
    _vals = []
    for _v in (_live, _SCHOLARLY_SMOKE_MAX_IMAGES):
        try:
            _vals.append(int(_v or 0))
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('smoke cap %r is not a number, it does not count towards the cap: %s', _v, _exc)
    return max(_vals) if _vals else 0


# One narration clock (P-13). Three word-rate constants used to coexist — the
# silent placeholder used words/2.8, the Stage 3.5 estimate words/2.5 — and
# neither matched the measured Elder-Gravel rate (~0.55 s/word across the last
# four production episodes). Every estimate derives from this one number, and
# once Stage 4 has MEASURED tts_duration that measurement wins everywhere.
_SCHOLARLY_SEC_PER_WORD = float(os.environ.get('ZYG_SCHOLARLY_SEC_PER_WORD', '0.55') or 0.55)


# Seed-registry guards (P-09). A subject that is really the essay-title
# fallback, a sentence-opener the entity extractor promoted, or a single word
# with no person in the prompt must NOT lock a seed: on the Black Death run
# every "black death" slot rendered from seed 6141 — in every episode.
_SEED_STOPWORDS = frozenset(
    {
        'most',
        'there',
        'what',
        'you',
        'not',
        'some',
        'others',
        'the',
        'this',
        'that',
        'they',
        'we',
        'it',
        'one',
        'all',
        'many',
        'each',
    }
)
_PERSON_NOUN_RE = re.compile(
    r'\b(?:man|men|woman|women|child|children|boy|girl|figure|face|hand|people|'
    r'merchant|priest|monk|soldier|mother|father)s?\b',
    re.IGNORECASE,
)
# The alternate benched moondream wordings (scripts/bench_vlm_gate_question.py
# QUESTIONS['ORIGINAL'] / ['SHIPPED']) — a same-wording retry at temperature 0
# is pointless, so an empty verdict is re-asked with the OTHER one (P-08).
_ANATOMY_Q_ORIGINAL = (
    'Say yes if this image contains grotesquely distorted or screaming faces, '
    'melted facial features, or deformed anatomy, otherwise say no.'
)
_ANATOMY_Q_SHIPPED = (
    'Say yes if this image contains grotesquely distorted faces, melted facial '
    'features, or deformed anatomy, otherwise say no.'
)


def _title_from_directive(directive: str) -> str:
    """Derive a display title from the user's directive (strip boilerplate prefixes)."""
    if not directive or not str(directive).strip():
        return ''
    import re as _re_dir

    t = str(directive).strip()
    t = _re_dir.sub(
        r'(?i)^(create|make|write)\s+(a\s+)?(documentary|video|story|film)\s+(about|on|of)\s+',
        '',
        t,
    )
    t = _re_dir.sub(r'(?i)^(a\s+)?documentary\s+(about|on)\s+', '', t)
    t = t.strip(' .,;:!?"\'')
    if not t:
        return ''
    return t[0].upper() + t[1:] if len(t) > 1 else t.upper()


def _research_title_matches_directive(title: str, directive: str) -> bool:
    """True when research title contains directive subject terms (relevance guard)."""
    if not title or not directive:
        return False
    subj = _title_from_directive(directive).lower()
    words = [w for w in subj.split() if len(w) >= 4]
    if not words:
        words = [w for w in directive.lower().split() if len(w) >= 5]
    if not words:
        return True
    tl = title.lower()
    return all(w in tl for w in words) if len(words) >= 2 else words[0] in tl


def _scholarly_n_images(duration_s: float) -> int:
    """How many pictures this episode needs — one per LTX-2.5 clip, no surplus.

    Every documentary workflow (crime / religion / luxury / finance / general)
    reaches the slideshow through this pipeline, so putting the rule here is what
    makes "generate only the pictures we actually need" true for all of them.
    The old rule was ``max(10, int(duration / 20))`` repeated at two sites; the
    floor alone handed a 60 s episode ten pictures of six seconds each.
    """
    return _scholarly_motion.n_images_for(duration_s)


def _scholarly_duration_targets(pipeline_options: dict | None) -> dict:
    """Word-count and image caps from Advanced Settings (documentary scholarly pipeline)."""
    po = pipeline_options or {}
    min_words = 1400
    target_words = 2250
    max_words = 2500
    duration_capped = False
    td = po.get('total_duration_sec')
    if td:
        td = float(td)
        duration_capped = True
        target_words = max(150, int(td * 2.5))
        min_words = max(120, int(target_words * 0.85))
        max_words = max(min_words + 30, int(target_words * 1.15))

    scene_count = po.get('scene_count')
    if scene_count is not None:
        try:
            n_flux_images = max(1, min(30, int(scene_count)))
        except (TypeError, ValueError):
            n_flux_images = None
    elif td:
        # Same derived rule as a full run: one picture per LTX clip, no surplus.
        n_flux_images = _scholarly_n_images(float(td))
    else:
        n_flux_images = None

    return {
        'target_words': target_words,
        'min_words': min_words,
        'max_words': max_words,
        'min_word_gate': min_words if duration_capped else 1400,
        'n_flux_images': n_flux_images,
        'duration_capped': duration_capped,
        'total_duration_sec': float(td) if td else None,
    }


# ── Visual intensity dial ────────────────────────────────────────────────────
# Every image in a documentary used to be written at one flat pitch, and the
# OPENING frame was the flattest of the set: slot 0 always resolves to
# arc_zone='exposition', and exposition force-returns a wide establishing shot
# regardless of the emotion curve (murch_engine.get_shot_type_grammar), blocks
# counterpoint, and draws its style row from the calm indices. The first thing a
# viewer ever sees was therefore, by construction, the least arresting frame in
# the episode.
#
# This dial is the single knob that changes that. It is read once per run from
# Advanced Settings (pipeline_options['image_intensity']) and threaded into the
# six places that were independently damping the imagery:
#   1. Stage 3.1 shock dampening      — skipped at high/extreme
#   2. Stage 3.5a scene descriptions  — high-impact tone mapping + hook line
#   3. Stage 3.5 batch prompt writer  — always-on intensity directive
#   4. Murch shot grammar             — hook slot escapes the exposition lock
#   5. Counterpoint mode              — suppressed at the peaks it was blunting
#   6. FLUX negative + VLM gate       — stop deleting what we just asked for
#
# WHAT "INTENSITY" MEANS HERE. Dramatic force, not shock value. The dial asks for
# the image a viewer cannot scroll past: close on a face, a body under strain, a
# moment of danger, crushing scale, fire and weather and ruin, a threat inside
# the frame. Injury and death are in that vocabulary when the subject genuinely
# contains them — they are not the point of it, and the prompts say so
# explicitly, because a model handed "be intense" with no steer will reach for
# gore as the cheapest reading. Arresting is the goal; graphic is one register
# among many and the subject decides when it applies.
#
# 'standard' reproduces the pre-dial behaviour exactly, so a department that
# wants the old restraint can still have it.
_INTENSITY_RANK = {'standard': 0, 'high': 1, 'extreme': 2}
_INTENSITY_DEFAULT = 'high'

# Prompt-side vocabulary per level. The hook slot always renders one level above
# the episode level (capped at 'extreme'), which is what makes the default
# 'high' episode open on an 'extreme' frame.
_INTENSITY_STYLE_CTX = {
    'standard': '',
    'high': 'high-impact and arresting, dramatic, physically charged',
    'extreme': ('maximally arresting, unflinching — the strongest single image in the film'),
}
_INTENSITY_MOOD_SUFFIX = {
    'standard': '',
    'high': (
        ', charged with physical stakes, sweat and grime and strain, hard directional light, tight arresting framing'
    ),
    'extreme': (
        ', overwhelming presence filling the frame, raw physical stakes, '
        'sweat and dirt and strain, harsh dramatic light, extreme tight '
        'framing, impossible to look away from'
    ),
}


def _scholarly_image_intensity(pipeline_options: dict | None) -> dict:
    """
    Resolve the visual intensity dial for this run.

    Returns level/rank for the episode body plus hook_level/hook_rank for image
    slot 0. `enabled` is the single boolean every call site guards on, so that
    'standard' leaves every one of the six damping paths untouched.
    """
    po = pipeline_options or {}
    _lvl = str(po.get('image_intensity') or '').strip().lower()
    if _lvl not in _INTENSITY_RANK:
        _lvl = _INTENSITY_DEFAULT
    _rank = _INTENSITY_RANK[_lvl]
    # The opening frame is pushed one level up — this is the whole point of the
    # hook slot, and it is why an episode left at the default still opens hard.
    _hook_rank = min(_rank + 1, 2)
    _hook_lvl = next(k for k, v in _INTENSITY_RANK.items() if v == _hook_rank)
    return {
        'level': _lvl,
        'rank': _rank,
        'enabled': _rank >= 1,
        'hook_level': _hook_lvl,
        'hook_rank': _hook_rank,
    }
