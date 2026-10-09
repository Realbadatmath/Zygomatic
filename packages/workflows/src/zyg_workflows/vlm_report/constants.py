# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Environment flags, render geometry and the crop/defect lookup tables."""

import os

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── render-recipe geometry ───────────────────────────────────────────────────
# The delivered file is usually upscaled AND frame-interpolated (scene20_v8b is
# 1664x960 @ 24 fps) while the chaining geometry that creates context seams is a
# property of the NATIVE render (17 fps, context 81 - overlap 24 = stride 57).
# Seam times must therefore be computed in NATIVE frames and converted to
# SECONDS — never in the delivered clip's own frame indices, which would put the
# seams at 2.375 s instead of 3.353 s and measure nothing.
NATIVE_FPS = float(os.environ.get('ZYG_NATIVE_FPS') or 17.0)
CONTEXT_STRIDE_FRAMES = int(os.environ.get('ZYG_CONTEXT_STRIDE') or 57)

MIN_CROP_PX = int(os.environ.get('ZYG_VLM_REPORT_MIN_CROP_PX') or 512)
MAX_LOCALIZE_FRAMES = int(os.environ.get('ZYG_VLM_REPORT_MAXLOC') or 6)
SYNTH_TOKENS = int(os.environ.get('ZYG_VLM_REPORT_SYNTH_TOKENS') or 1700)
SYNTH_WAIT_S = float(os.environ.get('ZYG_VLM_REPORT_SYNTH_WAIT_S') or 420)

LESSONS_PATH = os.path.join(_DIR, 'data', 'runtime', 'vlm_report_lessons.jsonl')

# ── pin -> crop geometry ─────────────────────────────────────────────────────
# A pin is a POINT in shot_metadata; a judge needs a BOX. These half-extents are
# fractional (of frame width / height) and were chosen so the resulting crop is
# roughly square in pixels on a 16:9 frame and contains the object plus enough
# context for the question to be answerable ("is a hand cupping the bowl" needs
# to see the hand too, not just the bowl).
PIN_HALF = {
    'bowl': (0.115, 0.150),
    'mouth': (0.100, 0.135),
}
# Boxes taken straight from metadata get a small pad so the object is not flush
# against the crop edge (the judge reads clipped objects as "cut off").
BOX_PAD = 0.035

# ── GroundingDINO prompts ────────────────────────────────────────────────────
# Scored in ONE forward pass by continuity_qc._detect, so extra prompts are free.
# The five object prompts are the checklist's nouns; the two actor prompts exist
# because the person-scoped CRITICAL items (two_hands_each, boy_smoking) need a
# tight person crop and a left/right half-frame fallback is a much weaker crop.
GROUND_PROMPTS = {
    'pipe': 'white clay tobacco pipe',
    'candle': 'lit candle in a holder',
    'book': 'open book',
    'hand': 'hand',
    'quill': 'quill',
    'man': 'a grown bearded man',
    'boy': 'a young boy',
}

# Candidate SELECTION rules. Measured 2026-07-30 on FINAL_scene20_v8b.mp4: the
# raw top-scoring GroundingDINO candidate for 'a grown bearded man' and for 'a
# young boy' was the WHOLE FRAME (0.002-0.994 on both axes), and the top 'white
# clay tobacco pipe' candidate landed on the boy's sleeve at x=0.83 while the
# pipe is at x~0.39. Taking the top score unfiltered would therefore have cropped
# the "tight region crops" as full frames and pointed the pipe questions at the
# wrong object — silently converting the whole crop rule into a no-op. Three
# cheap constraints fix it, and each one is a statement about the SCENE, not a
# fudge factor:
#   * an area cap — a box covering most of the frame is a detector failure, not
#     an object;
#   * a side constraint for the two actors — the blocking is authored
#     ("man at the LEFT, boy at the RIGHT"), so a 'boy' box centred left is wrong;
#   * a pin anchor — when shot_metadata says where a prop is supposed to be, the
#     detection that AGREES with the authored intent is the one to track. When no
#     candidate agrees, that disagreement is recorded (agrees_with_pin=False) and
#     reported instead of being hidden.
ROLE_PIN_ANCHOR = {'pipe': 'bowl', 'quill': 'page', 'candle': 'candle', 'book': 'book'}
PERSON_SIDE = {'man': 'left', 'boy': 'right'}
PERSON_FALLBACK = {'man': (0.00, 0.02, 0.52, 1.00), 'boy': (0.48, 0.02, 1.00, 1.00)}
MAX_OBJECT_AREA = 0.35
MAX_PERSON_AREA = 0.62
MAX_HAND_AREA = 0.20

# ── which checklist item is asked about which crop ───────────────────────────
# THE crop-rule table. Roles that do not exist in a given render are skipped
# silently; an item with no surviving role falls back to the 'frame' target so it
# is still asked (with a recorded caveat that it was asked at full-frame scale,
# where recall is measurably worse).
ITEM_TARGETS = {
    # 2026-08-04 FIX: was ('bowl', 'pipe'). The bowl crop CANNOT SHOW THE STEM,
    # so the judge failed this at all 6 timestamps giving its own reason — "the
    # stem is not visible in any of the frames" — while the identical question on
    # the 'pipe' crop PASSED. That single mis-mapping drove a critical FAIL on a
    # correct render. A question must be asked of evidence that can answer it;
    # see ITEM_REQUIRES_VISIBLE below, which now states the requirement so the
    # mapping cannot silently regress.
    'pipe_held_by_stem': ('pipe', 'man_hands'),
    'pipe_at_lips': ('mouth',),
    'hand_covers_bowl': ('bowl', 'man_hands'),
    'stray_smoke': ('frame',),
    'boy_smoking': ('boy',),
    'two_hands_each': ('man', 'boy'),
    'candle_intact': ('candle',),
    'ink_off_page': ('page', 'book'),
    'quill_at_page': ('page', 'quill'),
    'identity_match': ('man', 'boy'),
}

# ── what must be VISIBLE for each question to be answerable ──────────────────
# The crop-rule's other half. ITEM_TARGETS says where to look; this says what has
# to be in frame for a "no" to mean "defect" rather than "I could not see it".
# A target that cannot show the required evidence is a TEST defect, not a subject
# defect — the distinction that stops an operator re-rendering a fine shot.
# Enforced by tests/test_vlm_crop_rule.py.
ITEM_REQUIRES_VISIBLE = {
    'pipe_held_by_stem': ('stem', 'hand'),
    'pipe_at_lips': ('lips', 'pipe'),
    'hand_covers_bowl': ('bowl', 'hand'),
    'stray_smoke': ('frame',),
    'boy_smoking': ('boy', 'face'),
    'two_hands_each': ('hands',),
    'candle_intact': ('candle',),
    'ink_off_page': ('page',),
    'quill_at_page': ('page', 'quill'),
    'identity_match': ('face',),
}
# Which crop roles can actually show which evidence. 'bowl' deliberately does NOT
# list 'stem' — that omission is the whole fix.
ROLE_SHOWS = {
    'bowl': ('bowl',),
    'pipe': ('bowl', 'stem', 'pipe'),
    'mouth': ('lips', 'pipe', 'face'),
    'man_hands': ('hand', 'hands', 'stem'),
    'boy': ('boy', 'face', 'hands'),
    'man': ('face', 'hands'),
    'candle': ('candle',),
    'page': ('page', 'quill'),
    'book': ('page',),
    'quill': ('quill', 'page'),
    'frame': ('frame', 'boy', 'face', 'hands', 'candle', 'page', 'quill', 'pipe', 'bowl', 'stem', 'lips', 'hand'),
}

# Items whose expected answer depends on WHEN in the scene they are asked.
# 'pipe_at_lips' is the documented case: the scene DELIBERATELY has the pipe away
# from the lips between draws (draws at 5.0s and 12.5s), so a "no" at a rest beat
# is a spec error, not a render defect. Outside its beats the verdict is UNKNOWN.
ITEM_BEAT_SCOPED = {
    'pipe_at_lips': {
        'beats': ('draw',),
        'tolerance_s': 1.5,
        'note': 'expected only during a draw; rest pose is pipe at chest, held by the stem',
    },
}


def item_answerable_on(item, role):
    """Can this crop role show what the question needs? False -> UNKNOWN + a
    TEST defect, never a subject FAIL."""
    need = set(ITEM_REQUIRES_VISIBLE.get(item, ()))
    if not need:
        return True
    return bool(need & set(ROLE_SHOWS.get(role, ())))


def first_answerable_target(item):
    """The crop this item SHOULD be asked on. Returns None if the mapping is
    broken, which the test suite treats as a build failure."""
    for role in ITEM_TARGETS.get(item, ()):
        if item_answerable_on(item, role):
            return role
    return None


# ── defect classes: how a VLM verdict and a pixel measurement become ONE row ──
# (region, class). Two signals that land on the same (region, class) are fused
# into a single finding whose source becomes 'both'. This is the attribution
# machinery required by the blind-spot rule: it makes visible which claims have
# two independent witnesses and which have exactly one.
VLM_CLASS = {
    'pipe_held_by_stem': ('pipe', 'prop_handling'),
    'pipe_at_lips': ('pipe', 'prop_handling'),
    'hand_covers_bowl': ('pipe', 'prop_handling'),
    'stray_smoke': ('frame', 'smoke'),
    'boy_smoking': ('boy', 'action_ownership'),
    'two_hands_each': ('frame', 'anatomy_hands'),
    'candle_intact': ('candle', 'prop_integrity'),
    'ink_off_page': ('page', 'ink_containment'),
    'quill_at_page': ('page', 'writing_action'),
    'identity_match': ('frame', 'identity'),
}
# Items the judge is MEASURED to be unreliable on. A FAIL is still worth acting
# on (specificity was 8/8); a PASS proves nothing and is labelled as such.
VLM_UNRELIABLE_PASS = {
    'ink_off_page': (
        '0/7 recall on the confirmed scene20_v7 ink defect across 3 '
        'phrasings x 2 crops x 2 devices — a "no" here is NOT '
        'evidence the page is clean'
    ),
}

SEVERITY_ORDER = {'critical': 3, 'major': 2, 'info': 1}
STATUS_ORDER = {'fail': 3, 'unknown': 2, 'pass': 1}
