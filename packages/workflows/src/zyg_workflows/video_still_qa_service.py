# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
video_still_qa_service.py
=========================
Blank-frame detection and CLIP-based subject matching for video pipeline stills.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

_BLANK_SIZE_BYTES = int(os.environ.get('ZYG_VIDEO_BLANK_THRESH', str(100 * 1024)))
_SUBJECT_MIN_SCORE = float(os.environ.get('ZYG_VIDEO_SUBJECT_MIN_SCORE', '0.17'))
_HUMAN_CONFLICT_MARGIN = float(os.environ.get('ZYG_VIDEO_HUMAN_CONFLICT_MARGIN', '0.02'))
_INDOOR_CONFLICT_MARGIN = float(os.environ.get('ZYG_VIDEO_INDOOR_CONFLICT_MARGIN', '0.015'))
_MAX_PORTRAIT_FACES = int(os.environ.get('ZYG_VIDEO_MAX_PORTRAIT_FACES', '1'))

_CREATURE_KW = frozenset(
    {
        'dragon',
        'griffin',
        'phoenix',
        'wyvern',
        'drake',
        'serpent',
        'beast',
        'creature',
        'monster',
        'dinosaur',
        'wolf',
        'tiger',
        'lion',
        'eagle',
        'horse',
        'animal',
        'cat',
        'dog',
        'bird',
        'fish',
        'shark',
        'whale',
        'bear',
        'snake',
    }
)

_HUMAN_KW = frozenset(
    {
        'woman',
        'man',
        'person',
        'girl',
        'boy',
        'face',
        'portrait',
        'character',
        'lady',
        'female',
        'male',
        'human',
    }
)

_PORTRAIT_SHOTS = frozenset(
    {
        'close-up',
        'close up',
        'extreme close-up',
        'extreme close up',
        'portrait',
    }
)

_HUMAN_SCENE_TEXT = 'person man woman people office classroom desk laptop computer indoor room students'

_INDOOR_SCENE_TEXT = 'modern office open plan desks laptops sunset window workplace classroom'

_DUPLICATE_SCENE_TEXT = 'multiple identical people cloned duplicated faces twins smeared repeated figures'

_BASE_STILL_NEGATIVE = (
    'duplicate person, cloned face, twins, multiple identical people, motion smear, '
    'ghosting, repeated figure, watermark, text overlay'
)

_clip_bundle: Optional[tuple] = None


def _load_clip_text_image():
    global _clip_bundle
    if _clip_bundle is not None:
        return _clip_bundle
    try:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            'ViT-B-32',
            pretrained='openai',
        )
        tokenizer = open_clip.get_tokenizer('ViT-B-32')
        model.eval()
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        model = model.to(device)

        def score(image_path: str, text: str) -> float:
            from PIL import Image

            img = preprocess(Image.open(image_path).convert('RGB')).unsqueeze(0).to(device)
            tokens = tokenizer([text[:220]]).to(device)
            with torch.no_grad():
                img_f = model.encode_image(img)
                txt_f = model.encode_text(tokens)
                img_f = img_f / img_f.norm(dim=-1, keepdim=True)
                txt_f = txt_f / txt_f.norm(dim=-1, keepdim=True)
                return float((img_f @ txt_f.T).squeeze().cpu().item())

        _clip_bundle = (score, 'openclip')
        return _clip_bundle
    except Exception:
        _clip_bundle = (None, 'unavailable')
        return _clip_bundle


def is_blank_still(image_path: str) -> bool:
    if not image_path or not os.path.isfile(image_path):
        return True
    try:
        if os.path.getsize(image_path) < _BLANK_SIZE_BYTES:
            return True
    except OSError:
        return True
    return False


def _extract_subject_phrase(topic: str, flux_prompt: str = '') -> str:
    src = f'{topic} {flux_prompt}'.strip().lower()
    tokens = re.findall(r'[a-z]{3,}', src)
    seen: set[str] = set()
    picked: list[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        if t in _CREATURE_KW or len(picked) < 6:
            picked.append(t)
        if len(picked) >= 8:
            break
    return ' '.join(picked[:8]) or topic[:120]


def is_creature_topic(topic: str) -> bool:
    tl = (topic or '').lower()
    return any(re.search(rf'\b{re.escape(kw)}\b', tl) for kw in _CREATURE_KW)


def is_human_focus_topic(topic: str, scene_data: dict | None = None) -> bool:
    sc = scene_data or {}
    if str(sc.get('scene_type') or '').lower() == 'character':
        return True
    tl = (topic or '').lower()
    return any(re.search(rf'\b{re.escape(kw)}\b', tl) for kw in _HUMAN_KW)


def is_portrait_scene(scene_data: dict | None) -> bool:
    sc = scene_data or {}
    shot = str(sc.get('shot_type') or '').strip().lower()
    if any(p in shot for p in _PORTRAIT_SHOTS):
        return True
    if str(sc.get('scene_type') or '').lower() == 'character':
        return True
    flux = str(sc.get('flux_prompt') or '').lower()
    return any(k in flux for k in ('close-up', 'close up', 'portrait'))


def topic_negative_prompt(
    topic: str,
    scene_data: dict | None = None,
    flux_prompt: str = '',
) -> str:
    """Extra negatives for Comfy still generation."""
    parts = [_BASE_STILL_NEGATIVE]
    if is_creature_topic(topic):
        parts.append(
            'human, person, man, woman, people, face portrait, office, classroom, '
            'desk, laptop, computer, student, teacher, indoor room'
        )
    elif is_human_focus_topic(topic, scene_data) or is_portrait_scene(scene_data):
        parts.append(
            'office, classroom, desk, chair, laptop, computer, open plan workplace, '
            'sunset window, balcony, sea view, man in foreground, crowd, group photo, '
            'duplicate person, cloned face, twins, multiple identical women, smeared faces'
        )
    return ', '.join(parts)


def count_prominent_faces(image_path: str) -> int:
    """Return detected frontal face count, or -1 if detection unavailable."""
    try:
        import cv2

        img = cv2.imread(image_path)
        if img is None:
            return -1
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml',
        )
        faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(36, 36))
        return int(len(faces)) if faces is not None else 0
    except Exception:
        return -1


def check_still_subject(
    image_path: str,
    topic: str,
    flux_prompt: str = '',
    log_fn: Callable[[str], None] | None = None,
) -> tuple[bool, float, str]:
    """Return (passed, score, reason)."""
    log = log_fn or (lambda _m: None)
    if is_blank_still(image_path):
        return False, 0.0, 'blank or missing still frame'

    subject = _extract_subject_phrase(topic, flux_prompt)
    scorer, backend = _load_clip_text_image()
    if scorer is None:
        log('VideoStillQA: CLIP unavailable — subject check cannot pass')
        return False, 0.0, 'clip unavailable'

    try:
        score = scorer(image_path, subject)
    except Exception as exc:
        log(f'VideoStillQA: CLIP score failed ({exc})')
        return False, 0.0, f'clip error: {exc}'

    if score >= _SUBJECT_MIN_SCORE:
        return True, score, f'subject match ok ({score:.3f}, {backend})'

    return False, score, f'low subject match ({score:.3f} < {_SUBJECT_MIN_SCORE})'


def check_indoor_conflict(
    image_path: str,
    topic: str,
    flux_prompt: str,
    scene_data: dict | None,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Fail when indoor/office CLIP score beats the intended portrait/subject."""
    if not (is_human_focus_topic(topic, scene_data) or is_portrait_scene(scene_data)):
        return True, 'not a human portrait job'
    if is_creature_topic(topic):
        return True, 'creature topic'

    scorer, backend = _load_clip_text_image()
    if scorer is None:
        return True, 'clip unavailable'

    subject = _extract_subject_phrase(topic, flux_prompt)
    try:
        subj_score = scorer(image_path, subject or flux_prompt[:120] or topic[:120])
        indoor_score = scorer(image_path, _INDOOR_SCENE_TEXT)
    except Exception as exc:
        return True, f'indoor check skipped ({exc})'

    if indoor_score > subj_score + _INDOOR_CONFLICT_MARGIN:
        return False, (
            f'office/indoor scene detected (indoor={indoor_score:.3f} > subject={subj_score:.3f}, {backend})'
        )

    if is_portrait_scene(scene_data):
        try:
            dup_score = scorer(image_path, _DUPLICATE_SCENE_TEXT)
        except Exception:
            dup_score = 0.0
        if dup_score > subj_score + _INDOOR_CONFLICT_MARGIN:
            return False, (f'crowd/duplicate scene detected (dup={dup_score:.3f} > subject={subj_score:.3f})')
    return True, 'indoor conflict ok'


def check_duplicate_faces(
    image_path: str,
    scene_data: dict | None,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Fail portrait stills with more than one prominent face."""
    if not is_portrait_scene(scene_data):
        return True, 'not portrait'
    count = count_prominent_faces(image_path)
    if count < 0:
        return True, 'face count unavailable'
    if count > _MAX_PORTRAIT_FACES:
        return False, f'too many faces detected ({count} > {_MAX_PORTRAIT_FACES})'
    return True, f'face count ok ({count})'


def check_still_complete(
    image_path: str,
    topic: str,
    flux_prompt: str,
    scene_data: dict | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[bool, float, str]:
    """Run all still QA gates. Returns (passed, score, reason)."""
    log = log_fn or (lambda _m: None)
    if is_blank_still(image_path):
        return False, 0.0, 'blank or missing still frame'

    dup_ok, dup_reason = check_duplicate_faces(image_path, scene_data, log_fn=log)
    if not dup_ok:
        log(f'VideoStillQA: {dup_reason}')
        return False, 0.0, dup_reason

    indoor_ok, indoor_reason = check_indoor_conflict(
        image_path,
        topic,
        flux_prompt,
        scene_data,
        log_fn=log,
    )
    if not indoor_ok:
        log(f'VideoStillQA: {indoor_reason}')
        return False, 0.0, indoor_reason

    ok, score, reason = check_still_subject(
        image_path,
        topic,
        flux_prompt,
        log_fn=log,
    )
    if not ok and is_creature_topic(topic):
        scorer, _ = _load_clip_text_image()
        if scorer is not None:
            try:
                human_score = scorer(image_path, _HUMAN_SCENE_TEXT)
            except Exception:
                human_score = 0.0
            if human_score > score + _HUMAN_CONFLICT_MARGIN:
                return (
                    False,
                    score,
                    f'human/indoor scene detected (human={human_score:.3f} > subject={score:.3f})',
                )

    return ok, score, reason
