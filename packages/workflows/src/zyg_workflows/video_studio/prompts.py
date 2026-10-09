# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, prompt builder — dials to the positive/negative prompt pair.

Moved verbatim (lines 4002-4162 of the old single-file module). Shared by the
render worker and by /video/api/prompt, so the preview the operator reads
cannot drift from what is submitted.
"""

from zyg_workflows import wan_video_service as _wan

from .spec import sanitize


# ──────────────────────────────────────────────────────────── prompt builder
_MOTION_AMOUNT_TOKENS = {
    'subtle': 'subtle restrained movement, minimal drift',
    'moderate': 'moderate natural movement',
    'dynamic': 'dynamic energetic movement',
    'frenetic': 'frenetic rapid movement, kinetic chaos',
}
_STYLE_TOKENS = {
    'documentary': 'observational documentary footage, natural available light',
    'animated': 'stylised animation, cel-shaded rendering, expressive linework',
    'painterly': 'painterly rendering, visible brushwork, illustrative',
}
_MOTION_SUBJECT_TOKENS = {
    'camera': 'the camera moves, the subject holds still',
    'subject': 'the camera is locked off, only the subject moves',
    'both': 'both the camera and the subject are in motion',
}


def compose_prompt(p: dict, subject: str) -> tuple:
    """Return (positive, negative) exactly as the render worker will send them.

    Shared by _render_worker and /video/api/prompt so the preview cannot drift
    from what is actually submitted — the same reason the pipeline logs its
    effective negative rather than the one it meant to send.

    Two routes into wan_video_service._build_prompt, chosen so that no dial is
    inert:

      * cinematic + camera move on auto + not locked → the heuristic route. _build_prompt's
        shot-type → camera map runs and appends the tested cinematic suffix.
      * anything else → the wan_prompt route (the same door a Claude-written
        pipeline prompt comes through). Taken because the heuristic route
        OVERRIDES meta['camera_motion'] with its shot-type map whenever
        visual_style is cinematic, and hard-codes a "Photorealistic ... " tail
        for every other style — so an explicit camera move or a painterly /
        animated look would silently never reach the model.
    """
    p = sanitize(p)
    base = (p['scene_prompt'] or subject or '').strip()

    # Every select below stores its own prompt phrase as its VALUE, so the
    # whole creative rail collapses to one loop. Order is the order a shot is
    # described on a call sheet: what the subject does, how the camera sees it,
    # then what it looks like — the model weights early tokens harder, and a
    # performance beat is worth more than a film stock.
    tokens = []
    _CLAUSE_ORDER = (
        # subject and performance
        'emotion_beat',
        'body_motion',
        'head_motion',
        'eye_motion',
        'mouth_motion',
        'secondary_motion',
        'env_motion',
        'background_action',
        # camera
        'camera_rig',
        'camera_height',
        'camera_angle',
        'camera_speed',
        'focus_pull',
        'framing_rule',
        'lens',
        'depth_of_field',
        # picture
        'lighting',
        'light_temp',
        'time_of_day',
        'weather',
        'atmosphere',
        'palette',
        'contrast_look',
        'film_stock',
        'texture_look',
        'lens_flare',
    )
    for key in _CLAUSE_ORDER:
        # A locked-off camera has no move to pace, and saying otherwise is how
        # a "Locked camera" clip ends up with a drifting frame anyway.
        if key == 'camera_speed' and p.get('static_shot'):
            continue
        v = str(p.get(key) or '').strip()
        if v and v != 'auto':
            tokens.append(v)
    if p['motion_amount'] != 'auto':
        tokens.append(_MOTION_AMOUNT_TOKENS.get(p['motion_amount'], ''))
    if p['motion_subject'] != 'auto':
        tokens.append(_MOTION_SUBJECT_TOKENS.get(p['motion_subject'], ''))
    if p['visual_style'] and p['visual_style'] != 'cinematic':
        tokens.append(_STYLE_TOKENS.get(p['visual_style'], ''))
    tokens = [t for t in tokens if t]
    token_str = ', '.join(tokens)

    # Free-text clauses. Kept OUT of the token list and appended as their own
    # sentences: a wardrobe or a setting is a statement about the world, and a
    # comma-spliced token list is where the model starts attaching them to the
    # wrong noun.
    clauses = [str(p.get(k) or '').strip() for k in ('setting', 'wardrobe', 'props', 'style_ref')]
    clause_str = '. '.join(c.rstrip('. ') for c in clauses if c)

    meta = {
        'subject': subject,
        'prompt': base,
        'shot_type': p['shot_type'],
        'emotion': p['motion_style'],
        'static_shot': p['static_shot'],
    }
    if p['camera_move'] not in ('auto', ''):
        meta['camera_motion'] = p['camera_move']

    if p['prompt_mode'] == 'verbatim':
        meta['wan_prompt'] = base or subject
        positive = _wan._build_prompt(meta, visual_style=None)
    elif p['visual_style'] == 'cinematic' and p['camera_move'] == 'auto' and not p['static_shot']:
        if token_str:
            meta['prompt'] = f'{base}. {token_str}' if base else token_str
        positive = _wan._build_prompt(meta, visual_style='cinematic')
    else:
        # static_shot routes here too: _build_prompt only honours its trained
        # static grammar (固定镜头 / locked-off tripod) on the wan_prompt door,
        # and a camera-motion lead would contradict it.
        if p['static_shot']:
            lead = ''
        else:
            lead = (
                p['camera_move'] if p['camera_move'] != 'auto' else _wan._MOTION_BY_EMOTION.get(p['motion_style'], '')
            )
        parts = [x for x in (lead, base, token_str, p['shot_type']) if x]
        meta['wan_prompt'] = '. '.join(parts) + '.'
        positive = _wan._build_prompt(meta, visual_style=('cinematic' if p['visual_style'] == 'cinematic' else None))

    if clause_str:
        positive = positive.rstrip('. ') + '. ' + clause_str
    suffix = (p['prompt_suffix'] or '').strip()
    if suffix:
        positive = positive.rstrip('. ') + '. ' + suffix

    negative = (p['negative_prompt'] or '').strip() or (_wan._STATIC_SHOT_NEG if p['static_shot'] else None)
    return positive[:600], (negative[:600] if negative else None)


def compose_link_prompts(p: dict, subject: str, n_links: int) -> list:
    """One (positive, negative) pair per chained sub-clip.

    'Prompt per link' is split on " || ". Link i takes piece i; a missing or
    empty piece falls back to the Scene description, so a half-filled box still
    renders. Each piece goes through compose_prompt unchanged, which is what
    keeps the camera/motion/look phrases on every link instead of only the
    first."""
    pieces = [s.strip() for s in str(p.get('link_prompts') or '').split('||')]
    out = []
    for i in range(n_links):
        if i < len(pieces) and pieces[i]:
            out.append(compose_prompt(dict(p, scene_prompt=pieces[i]), subject))
        else:
            out.append(compose_prompt(p, subject))
    return out
