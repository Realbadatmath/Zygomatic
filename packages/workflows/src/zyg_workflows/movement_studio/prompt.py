# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.prompt — compose_prompt() and its phrase tables."""

from zyg_workflows.movement_studio.actions_lib import action_prompt
from zyg_workflows.movement_studio.params import sanitize


# ──────────────────────────────────────────────────────────── prompt builder
# Each map turns one dial value into ONE clause. A value absent from its map
# (every 'natural'/'unchanged'/'none' default) contributes nothing, so a default
# dial state composes to the bare action sentence PLUS the two toggles that
# default on — secondary motion and the idle layer. Those two are deliberately
# on: they are the cheapest tokens against the "moving photograph" failure this
# tab exists to avoid. Turn both off to get the exact 2026-08-31 sentence back.
_SPEED = {
    'very slow': 'moving very slowly',
    'slow': 'moving slowly',
    'brisk': 'moving briskly',
    'fast': 'moving quickly',
    'frantic': 'moving frantically',
}
_INTENSITY = {
    'minimal': 'with minimal movement',
    'subtle': 'subtly',
    'strong': 'with strong committed movement',
    'extreme': 'with extreme force',
}
_AMPLITUDE = {
    'tight and contained': 'with a tight contained range of motion',
    'wide and open': 'with a wide open range of motion',
    'exaggerated': 'with an exaggerated range of motion',
}
_STYLE = {
    'graceful': 'the movement graceful',
    'heavy and weighted': 'the movement heavy and weighted',
    'light and floating': 'the movement light and floating',
    'mechanical': 'the movement stiff and mechanical',
    'jerky': 'the movement jerky and uneven',
    'fluid': 'the movement fluid and continuous',
    'animated and exaggerated': 'the movement broad and animated',
}
_EASING = {
    'in': 'starting slowly and building',
    'out': 'decelerating into the end',
    'both': 'easing in at the start and out at the end',
    'snap': 'snapping into the movement then settling',
}
_REPEAT = {
    'twice': 'repeating twice',
    'three': 'repeating three times',
    'loop': 'repeating continuously in a smooth cycle',
}
_HOLD_START = {'beat': 'holds still for a beat, then ', 'long': 'stands motionless, then '}
_HOLD_END = {'beat': 'then settles and holds for a beat', 'long': 'then holds the final pose to the end of the shot'}
_DIRECTION = {
    'toward the camera': 'travelling toward the camera',
    'away from the camera': 'travelling away from the camera',
    'to the left': 'travelling to the left',
    'to the right': 'travelling to the right',
    'diagonally forward-left': 'travelling diagonally forward and to the left',
    'diagonally forward-right': 'travelling diagonally forward and to the right',
    'in a circle': 'travelling in a circle',
    'upward': 'travelling upward',
    'downward': 'travelling downward',
}
_DISTANCE = {
    'on the spot': 'staying on the spot',
    'a single step': 'covering a single step',
    'a few steps': 'covering a few steps',
    'across the frame': 'crossing the frame',
    'out of frame': 'continuing out of frame',
}
_FACING = {
    'facing the camera': 'facing the camera throughout',
    'turning to profile': 'turning to a profile view',
    'turning three-quarter': 'turning to a three-quarter view',
    'turning away from the camera': 'turning away from the camera',
}
_SCALE = {'larger': 'growing larger in frame', 'smaller': 'growing smaller in frame'}
_GROUND = {
    'feet planted': 'feet planted firmly on the ground',
    'full walking cycle': 'a full walking cycle, each foot lifting and planting',
    'one foot lifted': 'one foot lifted clear of the ground',
    'airborne': 'airborne with both feet off the ground',
    'sliding': 'sliding along the ground',
}
_LEAD = {
    'the head': 'led by the head',
    'the chest': 'led by the chest',
    'the hips': 'led by the hips',
    'the left arm': 'led by the left arm',
    'the right arm': 'led by the right arm',
    'both arms': 'led by both arms',
    'the left leg': 'led by the left leg',
    'the right leg': 'led by the right leg',
    'the tail': 'led by the tail',
    'the wings': 'led by the wings',
}
_HEAD = {
    'held still': 'head held still',
    'turning': 'head turning',
    'nodding': 'head nodding',
    'shaking': 'head shaking',
    'tilting': 'head tilting to one side',
    'tracking something': 'head tracking something',
    'thrown back': 'head thrown back',
}
_GAZE = {
    'straight at the camera': 'looking straight at the camera',
    'off to the left': 'looking off to the left',
    'off to the right': 'looking off to the right',
    'upward': 'looking upward',
    'downward': 'looking downward',
    'following the movement': 'the eyes following the movement',
    'eyes closed': 'eyes closed',
    'eyes wide open': 'eyes wide open',
}
_MOUTH = {
    'closed': 'mouth closed',
    'speaking': 'mouth moving as they speak',
    'open': 'mouth open',
    'breathing hard': 'breathing hard through an open mouth',
    'shouting': 'mouth open in a shout',
}
_HANDS = {
    'relaxed at the sides': 'hands relaxed at the sides',
    'gesturing': 'hands gesturing',
    'clenched': 'hands clenched',
    'open palms': 'palms open',
    'holding something': 'hands holding something',
    'hidden from view': 'hands out of view',
}
_POSTURE = {
    'upright': 'posture upright',
    'hunched': 'posture hunched',
    'leaning forward': 'leaning forward',
    'leaning back': 'leaning back',
    'slouched': 'slouched',
    'coiled and ready': 'coiled and ready',
    'sagging': 'sagging',
}
_BREATH = {
    'none visible': 'no visible breathing',
    'subtle': 'subtle breathing',
    'visible': 'visible breathing',
    'heavy': 'breathing heavily',
    'ragged': 'breathing raggedly',
}
_WEIGHT = {
    'light-footed': 'light on their feet',
    'heavy and grounded': 'heavy and grounded',
    'top-heavy': 'top-heavy and unbalanced',
    'weightless': 'weightless',
}


def _clauses(p: dict) -> list:
    """Every modifier clause, in the order they read best. Shared by the base
    sentence and by each beat of a schedule — a beat must be standalone, so it
    gets the same modifiers rather than a bare verb."""
    out = []
    for src, key in (
        (_SPEED, 'speed'),
        (_INTENSITY, 'intensity'),
        (_AMPLITUDE, 'amplitude'),
        (_EASING, 'easing'),
        (_DIRECTION, 'direction'),
        (_DISTANCE, 'distance'),
        (_FACING, 'facing'),
        (_SCALE, 'scale_change'),
        (_GROUND, 'ground'),
        (_LEAD, 'lead'),
        (_HEAD, 'head'),
        (_GAZE, 'gaze'),
        (_MOUTH, 'mouth'),
        (_HANDS, 'hands'),
        (_POSTURE, 'posture'),
        (_BREATH, 'breathing'),
        (_WEIGHT, 'weight'),
        (_STYLE, 'style'),
        (_REPEAT, 'repeat'),
    ):
        c = src.get(str(p.get(key) or ''))
        if c:
            out.append(c)
    if str(p.get('expression') or 'unchanged') != 'unchanged':
        out.append(f'a {p["expression"]} expression')
    if str(p.get('mood') or 'unchanged') != 'unchanged':
        out.append(f'the whole performance reading as {p["mood"]}')
    if p.get('follow_through'):
        out.append('the limbs following through and settling afterwards')
    if p.get('secondary'):
        out.append('hair and loose clothing trailing the movement')
    if p.get('idle_layer'):
        out.append('subtle breathing and small weight shifts continuing underneath')
    env = str(p.get('environment') or '').strip().rstrip('.')
    if env:
        out.append(env)
    return out


def _decorate(base: str, p: dict) -> str:
    """One beat: prefix, verb, modifier clauses, tail hold."""
    base = (base or '').strip().rstrip('.')
    if not base:
        return ''
    pre = _HOLD_START.get(str(p.get('hold_start') or ''), '')
    if p.get('anticipation'):
        pre += 'takes a small wind-up in the opposite direction, then '
    parts = [pre + base] + _clauses(p)
    tail = _HOLD_END.get(str(p.get('hold_end') or ''), '')
    if tail:
        parts.append(tail)
    return ', '.join(parts)


def compose_prompt(p: dict, action_id: str) -> str:
    """The exact motion sentence the render will submit — nothing else builds one.

    Shared by the render worker and by /api/internal/movement/prompt, for the
    same reason video_studio.compose_prompt is: a preview that is assembled
    separately from the submit is a preview that can be wrong, and this pipeline
    has already been bitten once by logging an intended value rather than the
    effective one.

    Note what is NOT here and cannot be: the locked-camera prefix
    ('固定镜头, static shot, ...') and the curated static negative are added
    inside generate_vace_static_clip on every path, and the subject's canon
    binding is prepended by bp_movement. Those three are the recipe, not dials."""
    p = sanitize(p)
    base = action_prompt(action_id, p.get('custom_prompt', ''))
    suffix = str(p.get('prompt_suffix') or '').strip().rstrip('.')
    sched = str(p.get('beat_schedule') or '').strip()

    if str(p.get('prompt_mode')) == 'verbatim':
        beats = [b.strip() for b in sched.split('|') if b.strip()] if sched else [base]
        out = ' | '.join(b for b in beats if b)
    elif sched:
        # Each beat must be standalone — the wrapper selects ONE sub-prompt per
        # context window, so a beat that leans on its neighbours for its modifiers
        # arrives at the sampler with none of them.
        out = ' | '.join(_decorate(b, p) for b in sched.split('|') if b.strip())
    else:
        out = _decorate(base, p)

    if suffix:
        out = ' | '.join(f'{b.strip()}, {suffix}' for b in out.split('|')) if '|' in out else f'{out}, {suffix}'
    return out.strip()
