# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Constants, the angle plan, the path helpers and the record helpers.

Carries the original top import block, so the package's ``os``/``json``/
``_cid``/``_cj`` attributes keep resolving. The three record helpers
(``_split_flags``, ``caption_mode``, ``_score_key``) open the original
'the run' section but are pure functions over a cell record, so they sit
here with the rest of the vocabulary instead of forcing a back import.
"""

from __future__ import annotations

import json
import os
from typing import Any

from zyg_workflows import creature_identity as _cid
from zyg_workflows import creature_judge as _cj
import logging as _zyg_logging

# ``_cid``/``_cj`` are not read here: this module holds them so that the package
# attributes ``creature_sheet_service._cid``/``._cj`` keep resolving and so that the
# monkeypatch fan-out in __init__.py (which writes through to every section module
# holding the name) reaches this one too, as the docstring above says.
__all__ = ['_cid', '_cj']

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.creature_sheet_service')


SHEET_DIRNAME = 'contact_sheet'
SHEET_FILENAME = 'sheet.png'
REPORT_FILENAME = 'sheet.json'
CELL_SIZE = int(os.environ.get('ZYG_CREATURE_CELL_PX', '1024'))
MAX_REGEN = int(os.environ.get('ZYG_CREATURE_MAX_REGEN', '2'))
SCRATCH_ANCHOR_SEEDS = int(os.environ.get('ZYG_CREATURE_ANCHOR_SEEDS', '3'))

# ── The angle plan ───────────────────────────────────────────────────────────
# kind: body (full-body cells edit the FULL-BODY anchor), head (close cells
#       edit the identity anchor, which may itself be a close-up), wide, detail.
# band: which DINO floor applies (creature_identity.BANDS).
# instruction: the Qwen-Image-Edit camera move. Phrasing follows what the human
#       sheet learned the hard way: say where the CAMERA MOVES, pin the subject
#       upright, never say "tilt" (frames came back upside-down), spell out the
#       no-face constraint for behind/top views.
_KEEP = 'Same creature, same colours, fur and proportions. Plain background, no people, no text.'
# Flags that do NOT exclude a strong-identity tile: the tile still trains, with a
# caption that does not lie about the view (the human sheet keeps mislabeled-
# angle tiles with angle-neutral captions the same way). Everything else —
# a different creature, a second creature, a human, broken anatomy, text — excludes.
SOFT_FLAGS = frozenset({'angle_match', 'whole_body', 'body_plan'})
# View/framing flags an operator-LOCKED copy is exempt from: the operator picked
# that image AS that view, and a copy cannot be re-rendered into anything else.
# (The judge called the pufferball's in-frame tail tip "cut off" — a false
# positive that would have captioned a perfect profile as a partial view.)
LOCKED_VIEW_EXEMPT = frozenset({'angle_match', 'whole_body'})
MAX_REGEN_SOFT = int(os.environ.get('ZYG_CREATURE_MAX_REGEN_SOFT', '1'))

# ── Body-plan lock (2026-08-25) ──────────────────────────────────────────────
# A front-view anchor hides whatever sits behind the creature, so every rotation
# INVENTED it: on the pufferball sheet one cell grew a segmented tail and the
# other fifteen grew arms, fins or nothing. Two operator locks live in the brief
# (brief.json; scripts/creature_lock.py writes them):
#   brief['body_plan']    - one anatomy sentence ("a ball-shaped body; one
#                           segmented turquoise tail curling up behind; two short
#                           arms; two three-toed feet"). Spliced into EVERY edit
#                           instruction (keep_sentence), every caption, and asked
#                           of the judge (soft flag 'body_plan': never excludes,
#                           marks the cell, earns one regen round).
#   brief['anchor_locks'] - {'full_body': path, 'side': path}. full_body replaces
#                           the derived anchor. side is a RIGHT-side profile that
#                           SHOWS the tail; it becomes the rotation source of the
#                           side/back/top cells ('side_source' in ANGLES) and the
#                           left profile is its mirror (the creatures are
#                           bilaterally symmetric, and a 180-degree turn is the
#                           move Qwen under-rotates most).
# Prompts steer, pixels guarantee: the sentence keeps the KIND of appendage
# consistent; only a source image that shows it keeps its SHAPE.
# Without locks, a body_plan still runs a "conform" pass on the derived anchor
# (best-of-N judged, angles LoRA off) so the anchor itself matches the sentence.
# Cell checkpoints carry a signature of (source image, instruction, body plan):
# re-picking the side anchor re-renders exactly the cells rotated from it.
CONFORM_SEEDS = int(os.environ.get('ZYG_CREATURE_CONFORM_SEEDS', '2'))
# Camera direction that continues from the RIGHT-side profile toward the back.
# The angles LoRA orbits consistently: front -> "90 right" = creature facing the
# right edge (cell 04) -> a further "45/90 right" = rear three-quarter / behind.
# MEASURED 2026-08-25 (pufferball side anchor, seed 9190): "90 degrees to the
# right" AND "to the left" + the rear-view clause both produced a true back view
# (tail centred, no face) - from a side view the text clause decides; the
# direction word is kept for the 45-degree cells, where it disambiguates.
SIDE_TOWARD_BACK = (os.environ.get('ZYG_CREATURE_SIDE_TOWARD_BACK') or 'right').strip().lower()
_SIDE_TEXT_Q = (
    'Rear three-quarter view: mostly the back and one side of the creature, '
    'the face turned away, whole body, feet included.'
)
_SIDE_TEXT_BACK = (
    'Rear view: the creature seen from directly behind, only its back visible, no face, whole body, feet included.'
)


def keep_sentence(body_plan: str = '') -> str:
    """The identity clause appended to every edit, with the body plan spliced in."""
    bp = (body_plan or '').strip().rstrip('.')
    if not bp:
        return _KEEP
    return f'Same creature, same colours, fur and proportions. Its anatomy: {bp}. Plain background, no people, no text.'


def anchor_locks(brief: dict) -> dict[str, str]:
    """{'full_body': path, 'side': path} - only the locks whose file exists."""
    raw = (brief or {}).get('anchor_locks') or {}
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for k in ('full_body', 'side'):
            p = str(raw.get(k) or '').strip()
            if p and os.path.isfile(p):
                out[k] = p
    return out


def _file_sig(path: str | None) -> str:
    """Short content hash of a file ('' when missing)."""
    import hashlib

    if not path or not os.path.isfile(path):
        return ''
    h = hashlib.sha1(usedforsecurity=False)
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:12]


def _text_sig(text: str) -> str:
    """Process-stable short hash of a string (hash() is salted per process)."""
    import hashlib

    return hashlib.sha1((text or '').encode('utf-8'), usedforsecurity=False).hexdigest()[:8]


def _mirror(src: str, dst: str) -> str:
    from PIL import Image, ImageOps

    ImageOps.mirror(Image.open(src).convert('RGB')).save(dst, format='PNG')
    return dst


def _opposite(direction: str) -> str:
    return 'left' if direction == 'right' else 'right'


def side_instruction(a: dict) -> str | None:
    """The camera move for an angle rendered FROM the side anchor (or its mirror).

    None = the cell is a copy of that source (side_turn None). side_turn 0 = the
    angle's own instruction (a non-orbit move such as top-down); N = orbit N
    degrees toward the back from the side view (45 = rear three-quarter,
    90 = directly behind). The mirror faces the other way, so its direction word
    flips."""
    turn = a.get('side_turn')
    if turn is None:
        return None
    if not turn:
        return a['instruction']
    direction = SIDE_TOWARD_BACK if a.get('side_source') == 'side' else _opposite(SIDE_TOWARD_BACK)
    return f'Rotate the camera {int(turn)} degrees to the {direction}. {a["side_text"]}'


ANGLES: list[dict[str, Any]] = [
    {
        'id': 'front_full',
        'label': 'front view, full body',
        'kind': 'body',
        'band': 'front',
        'anchor': True,
        'instruction': None,
        'desc': 'straight-on front view showing the whole body',
    },
    {
        'id': 'q45_left',
        'label': 'three-quarter left, full body',
        'kind': 'body',
        'band': 'quarter',
        'instruction': 'Rotate the camera 45 degrees to the left. Three-quarter view of the whole creature, feet included.',
        'desc': 'a three-quarter view turned about 45 degrees to the left, whole body visible',
    },
    {
        'id': 'q45_right',
        'label': 'three-quarter right, full body',
        'kind': 'body',
        'band': 'quarter',
        'instruction': 'Rotate the camera 45 degrees to the right. Three-quarter view of the whole creature, feet included.',
        'desc': 'a three-quarter view turned about 45 degrees to the right, whole body visible',
    },
    {
        'id': 'side_left',
        'label': 'left side profile, full body',
        'kind': 'body',
        'band': 'side',
        'side_source': 'mirror',
        'side_turn': None,
        'instruction': 'Rotate the camera 90 degrees to the left. Side profile view: the creature faces the left edge of the frame and only one side of it is visible, whole body, feet included.',
        'desc': 'a true side profile from the left, the creature facing the left edge of the frame',
    },
    {
        'id': 'side_right',
        'label': 'right side profile, full body',
        'kind': 'body',
        'band': 'side',
        'side_source': 'side',
        'side_turn': None,
        'instruction': 'Rotate the camera 90 degrees to the right. Side profile view: the creature faces the right edge of the frame and only one side of it is visible, whole body, feet included.',
        'desc': 'a true side profile from the right, the creature facing the right edge of the frame',
    },
    {
        'id': 'back_q_left',
        'label': 'back three-quarter left',
        'kind': 'body',
        'band': 'back',
        'side_source': 'mirror',
        'side_turn': 45,
        'side_text': _SIDE_TEXT_Q,
        'instruction': 'Rotate the camera 135 degrees to the left. Rear three-quarter view: mostly the back and left side of the creature, the face turned away, whole body.',
        'desc': 'a back three-quarter view, mostly the back and one side visible, the face mostly turned away',
    },
    {
        'id': 'back_q_right',
        'label': 'back three-quarter right',
        'kind': 'body',
        'band': 'back',
        'side_source': 'side',
        'side_turn': 45,
        'side_text': _SIDE_TEXT_Q,
        'instruction': 'Rotate the camera 135 degrees to the right. Rear three-quarter view: mostly the back and right side of the creature, the face turned away, whole body.',
        'desc': 'a back three-quarter view, mostly the back and one side visible, the face mostly turned away',
    },
    {
        'id': 'back',
        'label': 'from directly behind',
        'kind': 'body',
        'band': 'back',
        'side_source': 'side',
        'side_turn': 90,
        'side_text': _SIDE_TEXT_BACK,
        'instruction': 'Rotate the camera 180 degrees. Rear view: the creature seen from directly behind, only its back visible, no face, whole body.',
        'desc': 'directly from behind, only the back visible and no face',
    },
    {
        'id': 'high_front',
        'label': 'high angle, looking down',
        'kind': 'body',
        'band': 'front',
        'instruction': 'Turn the camera to a high-angle view, looking steeply down at the creature from above; the creature stays upright, whole body.',
        'desc': 'a high camera angle looking down at the creature from above',
    },
    {
        'id': 'low_front',
        'label': 'low angle, looking up',
        'kind': 'body',
        'band': 'front',
        'instruction': 'Turn the camera to a low-angle view, looking steeply up at the creature from below; the creature stays upright, whole body.',
        'desc': 'a low camera angle looking up at the creature from below',
    },
    {
        'id': 'top_down',
        'label': 'top-down view',
        'kind': 'body',
        'band': 'top',
        'side_source': 'side',
        'side_turn': 0,
        'instruction': "Turn the camera to a top-down view, looking straight down onto the top of the creature's head and back; the face is not visible.",
        'desc': 'a top-down view straight down onto the top of the head and back',
    },
    # ref_source: this cell may be edited from the operator's own reference even
    # when that reference is a close-up crop. It is the only head cell that
    # qualifies, because its camera move is a DOLLY (closer, same bearing) — it
    # never has to invent what sits outside the crop. The two three-quarter
    # close-ups orbit 45 degrees and therefore must come from the locked
    # full-body anchor; see _cell_source (2026-08-26).
    {
        'id': 'close_front',
        'label': 'face close-up, front',
        'kind': 'head',
        'band': 'close',
        'ref_source': True,
        'instruction': "Move the camera closer for a close-up of the creature's face and eyes filling the frame.",
        'desc': 'a front close-up of the face and eyes filling the frame',
    },
    {
        'id': 'close_q_left',
        'label': 'face close-up, three-quarter left',
        'kind': 'head',
        'band': 'close',
        'instruction': "Rotate the camera 45 degrees to the left and move closer for a close-up of the creature's face, a three-quarter view.",
        'desc': 'a close-up of the face turned about 45 degrees to the left',
    },
    {
        'id': 'close_q_right',
        'label': 'face close-up, three-quarter right',
        'kind': 'head',
        'band': 'close',
        'instruction': "Rotate the camera 45 degrees to the right and move closer for a close-up of the creature's face, a three-quarter view.",
        'desc': 'a close-up of the face turned about 45 degrees to the right',
    },
    {
        'id': 'wide',
        'label': 'wide shot, small in frame',
        'kind': 'wide',
        'band': 'wide',
        'instruction': 'Zoom out to a wide shot: the whole creature small in the centre of the frame, facing the camera, lots of plain space around it.',
        'desc': 'a wide shot with the whole creature small in the centre of the frame',
    },
    {
        'id': 'detail',
        'label': 'extreme close-up, surface detail',
        'kind': 'detail',
        'band': 'detail',
        'instruction': "Move the camera very close to the creature's body: an extreme close-up where the fur, skin or scale texture fills the entire frame.",
        'desc': 'an extreme close-up where the body surface texture fills the frame',
    },
]
COMPACT_IDS = ('front_full', 'q45_left', 'q45_right', 'side_left', 'back', 'high_front', 'close_front', 'close_q_left')


def angle_plan(preset: str = 'standard') -> list[dict[str, Any]]:
    if (preset or '').lower() == 'compact':
        return [a for a in ANGLES if a['id'] in COMPACT_IDS]
    return list(ANGLES)


def sheet_dir(dataset_dir: str) -> str:
    return os.path.join(dataset_dir, SHEET_DIRNAME)


def sheet_path(dataset_dir: str) -> str:
    return os.path.join(sheet_dir(dataset_dir), SHEET_FILENAME)


def report_path(dataset_dir: str) -> str:
    return os.path.join(sheet_dir(dataset_dir), REPORT_FILENAME)


def load_report(dataset_dir: str) -> dict:
    try:
        with open(report_path(dataset_dir), encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


# ── the run ──────────────────────────────────────────────────────────────────


def _split_flags(reasons: list[str]) -> tuple[list[str], list[str]]:
    """(hard, soft) from a stored reasons list ('vlm:angle_match' is soft)."""
    hard, soft = [], []
    for r in reasons or []:
        (soft if (r.startswith('vlm:') and r[4:] in SOFT_FLAGS) else hard).append(r)
    return hard, soft


def caption_mode(rec: dict) -> str:
    """'angle' = caption the requested view; 'neutral' = the view did not come
    out as asked (caption says 'alternate view'); 'partial' adds cropped framing."""
    soft = rec.get('soft') or []
    if 'vlm:angle_match' in soft and 'vlm:whole_body' in soft:
        return 'neutral_partial'
    if 'vlm:angle_match' in soft:
        return 'neutral'
    if 'vlm:whole_body' in soft:
        return 'partial'
    return 'angle'


def _score_key(rec: dict) -> tuple:
    """Best-of-N ordering: no hard fail, then no soft flag, then DINO."""
    return (
        1 if rec.get('ok') else 0,
        0 if rec.get('soft') else 1,
        rec.get('dino') if isinstance(rec.get('dino'), (int, float)) else -1.0,
    )
