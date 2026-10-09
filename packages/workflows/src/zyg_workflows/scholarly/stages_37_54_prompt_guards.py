# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The four prompt-batch helpers of Stage 3.5, hoisted to module level.

`stage_11_flux_prompt_batch` was 981 lines: one closure,
`_batch_generate_flux_prompts`, holding five more. Four of those five are here —
the user-message builder and the three guards that run over the parsed prompt
pairs — and the fifth, `call_claude`, is in `stages_37_54_prompt_batch` next to
the caller it shares every argument with.

No statement changed and no side effect moved: the guards are called in the same
order with the same values and log the same lines. What changed is how each
function reaches the names it used to close over, and there are only two kinds:

* `ctx` — the `RunContext`, re-bound to plain locals in the head of the
  function, in the head/tail glue style the rest of this package uses (see
  `README.md`), because the run inputs these bodies read (`narration_script`,
  `pipeline_state`, `_era_lock`, `_log`, …) are fields of it;
* the values `batch_generate_flux_prompts` derives once before the first call —
  `_style_ctx`, `_quality_tag`, `_period_lock_rule`, `_system`, the API key —
  passed as **keyword-only** parameters. Keyword-only so that a caller cannot
  silently swap two of the seven strings; none of them is ever rebound by a
  callee, so none needs a state object.

`_make_user_msg` had no docstring; the three guards' docstrings are theirs,
verbatim.
"""

import re as _re_bp

from zyg_workflows.pipeline_scholarly import (
    _MODERN_TERM_RE,
    _TEXT_FRAMING_FIX,
    _TEXT_SUBJ_WINDOW,
    _TEXT_SUBJECT_RE,
    _period_hair_backstop,
    _period_noun_rewrite,
    _render_safety_rewrite,
    _scan_modern_terms,
)
from zyg_workflows.runtime import _record_token_usage
from zyg_workflows.stage_runner import _log_prompt
from zyg_workflows.subscription_llm import (
    MODEL_LARGE as _LLM_LARGE,
    anthropic_client as _llm_client,
)


def make_user_msg(
    ctx,
    slot_start: int,
    slot_end: int,
    *,
    n: int,
    _style_ctx: str,
    _quality_tag: str,
    _is_battle_topic: bool,
    _period_lock_section: str,
    _period_lock_rule: str,
    _hands_rule: str,
    _skin_rule: str,
) -> str:
    """The user half of one Claude batch call: slots `slot_start`..`slot_end` of `n`."""
    _essay_title_for_prompt = ctx._essay_title_for_prompt
    _narration_sentences = ctx._narration_sentences
    _sch_family_early = ctx._sch_family_early
    _sch_intensity = ctx._sch_intensity
    _slot_word_bounds = ctx._slot_word_bounds
    narration_script = ctx.narration_script
    pipeline_state = ctx.pipeline_state
    topic = ctx.topic
    n_batch = slot_end - slot_start
    # Per-slot narration: the words actually spoken during each
    # slot's audio window. The old single flat excerpt was cut at
    # 4000 chars — Claude never saw the back half of the script and
    # invented its own beat order, so images ran minutes ahead of
    # the narration.
    _seg_words = narration_script.split()
    _slot_narration_lines = []
    for _si_nl in range(slot_start, slot_end):
        _w0_nl, _w1_nl = _slot_word_bounds(_si_nl, n)
        _slot_narration_lines.append(f'  Slot {_si_nl + 1}: "{" ".join(_seg_words[_w0_nl:_w1_nl])[:400]}"')
    _narration_section = (
        'NARRATION BY SLOT — each image is on screen while EXACTLY these '
        'words are spoken; depict what its own slot narrates:\n' + '\n'.join(_slot_narration_lines)
    )

    # ── Per-slot Murch brief ──────────────────────────────────────
    # Pull emotion curve + turning points from pipeline state and
    # compute arc_zone + shot grammar for each slot so Claude can
    # honour the emotional arc and camera language Murch calculated.
    from zyg_workflows import murch_engine as _me2b

    _ec = pipeline_state.get('emotion_curve', [])
    _tp = pipeline_state.get('turning_points', [])
    _n_s = len(_narration_sentences)
    _murch_briefs = []
    for _si in range(slot_start, slot_end):
        # Emotion at this slot (proportional mapping into curve)
        _emotion = 'calm'
        _intens = 0.2
        if _ec:
            _ci = int(_si * len(_ec) / max(n, 1))
            _ci = min(_ci, len(_ec) - 1)
            _emotion = _ec[_ci].get('emotion', 'calm')
            _intens = round(_ec[_ci].get('intensity', 0.2), 2)

        # Arc zone
        _frac = _si / max(n - 1, 1)
        if _tp:
            try:
                _az = _me2b.get_arc_zone(_si, _tp, n)
            except Exception:
                _az = (
                    'exposition'
                    if _frac < 0.15
                    else 'rising'
                    if _frac < 0.45
                    else 'climax'
                    if _frac < 0.65
                    else 'falling'
                    if _frac < 0.85
                    else 'resolution'
                )
        else:
            _az = (
                'exposition'
                if _frac < 0.15
                else 'rising'
                if _frac < 0.45
                else 'climax'
                if _frac < 0.65
                else 'falling'
                if _frac < 0.85
                else 'resolution'
            )

        # Shot grammar from arc + emotion
        _shot_map = {
            'exposition': 'wide establishing shot',
            'resolution': 'medium wide shot, reflective',
        }
        # HOOK SLOT: slot 0 is always arc=exposition, so this map
        # was handing the writer "wide establishing shot" for the
        # opening frame of every episode ever made. Override the
        # whole branch — the brief is what the writer follows, and
        # the rules block below says the brief wins over its own
        # camera preference.
        if _si == 0 and _sch_intensity['hook_rank'] >= 2:
            _shot = 'extreme close-up, tight crop, raw arresting detail'
            _az = 'hook'
        elif _az == 'exposition' and _sch_intensity['enabled']:
            # FLAT HALF: no wide lock on exposition with the dial up —
            # slots 1-4 alternate medium / close.
            _shot = (
                'medium shot, something at stake in frame' if _si % 2 == 1 else 'close-up, tight focus, charged detail'
            )
        elif _az in _shot_map:
            _shot = _shot_map[_az]
        elif _az == 'climax':
            _shot = (
                'extreme close-up, raw emotion'
                if _intens >= 0.85
                else 'medium shot, dramatic angle'
                if _intens >= 0.65
                else 'medium wide shot, tension building'
            )
        else:
            _gi = min(4, int(_intens * 4))
            _seq = ['wide shot', 'medium wide shot', 'medium shot', 'close-up', 'extreme close-up']
            _shot = _seq[_gi]

        # Counterpoint hint for high-intensity shock/grief.
        # INTENSITY DIAL: this line told the writer to substitute the
        # aftermath for the act at exactly the beats meant to land
        # hardest. At high/extreme it inverts into its opposite.
        _cp_hint = ''
        if _si == 0 and _sch_intensity['hook_rank'] >= 2:
            _cp_hint = ' [HOOK — the opening frame; most extreme image in the episode]'
        elif _emotion in ('shock', 'grief') and _intens >= 0.75:
            _cp_hint = (
                ' [hit the literal act — the moment of harm itself, in close, not its aftermath or its symbol]'
                if _sch_intensity['enabled']
                else ' [hit the emotion, not the literal act — show impact/aftermath]'
            )

        _murch_briefs.append(f'  Slot {_si + 1}: arc={_az} | emotion={_emotion}({_intens}) | shot={_shot}{_cp_hint}')

    _murch_section = 'MURCH CINEMATIC BRIEF — follow these per-slot directives exactly:\n' + '\n'.join(_murch_briefs)

    # ── Per-slot visual scene anchors ────────────────────────────
    # Prefer the Stage 3.5a time-locked scene list: one description
    # per slot, anchored to the exact words spoken in that slot's
    # audio window. Fall back to Stage 3b visual tags (index-mapped)
    # only when the time-locked list doesn't match the slot grid.
    _tls_scenes_bp = pipeline_state.get('_stage3_scene_list', [])
    _tls_anchor_ok = len(_tls_scenes_bp) == n
    _vt_all_bp = pipeline_state.get('visual_tags', [])
    _n_vt_bp = max(len(_vt_all_bp), 1)
    _anchor_lines = []
    for _si_a in range(slot_start, slot_end):
        if _tls_anchor_ok and _tls_scenes_bp[_si_a]:
            _anchor_lines.append(f'  Slot {_si_a + 1}: {_tls_scenes_bp[_si_a]}')
            continue
        _vt_i_a = min(int(_si_a * _n_vt_bp / max(n, 1)), _n_vt_bp - 1)
        _sd_a = _vt_all_bp[_vt_i_a].get('scene_desc', '') if _vt_all_bp else ''
        if _sd_a:
            _anchor_lines.append(f'  Slot {_si_a + 1}: {_sd_a}')
    _anchor_section = (
        ('VISUAL SCENE ANCHORS (grounded in narration — enrich, do not ignore):\n' + '\n'.join(_anchor_lines) + '\n\n')
        if _anchor_lines
        else ''
    )

    # ── INTENSITY DIAL — user-message half ───────────────────────
    # The system prompt sets the writer's disposition; these are the
    # enforceable rules it is checked against. The hook rule only
    # appears in the batch that actually contains slot 1 — repeating
    # it in batch 2 of a >50-image episode would have the writer
    # trying to open a batch that starts at slot 51.
    _hook_on = _sch_intensity['hook_rank'] >= 2 and slot_start == 0 and slot_end > 0
    _intensity_rules = ''
    if _sch_intensity['enabled']:
        _intensity_rules = (
            '  - INTENSITY: this episode is cut for maximum impact — the test for '
            'every S prompt is whether a viewer scrolling past would stop. Get '
            'close: faces, bodies under strain, the moment of danger or '
            'exhaustion or defiance. Use crushing scale, fire, smoke, weather, '
            'darkness, ruin. Do not default to artifacts, architecture or empty '
            'landscapes when a human moment is available in those words\n'
            '  - Intensity means dramatic FORCE, not shock value. Do NOT reach for '
            'gratuitous gore or cruelty — hardship, injury and death belong in a '
            "prompt only when that slot's narration is genuinely about them. What "
            'you are always reaching for is the image nobody can look away from\n'
            '  - Do NOT soften a violent, fatal or tragic beat into its aftermath, '
            'its symbol or its memorial. Show the moment itself. The C prompt is '
            'where indirection belongs — the S prompt is literal\n'
            '  - Calm/exposition/resolution slots still need a charge: stillness '
            'with something at stake visible in frame, not neutral scenery\n'
        )
        if _sch_intensity['rank'] >= 2:
            _intensity_rules += (
                '  - EXTREME: go to the hardest moment the subject genuinely '
                'contains and render it with photographic specificity rather than '
                'implication. Injury, death, suffering and ruin are in scope where '
                'the subject is actually about them — never as decoration\n'
            )
    if _hook_on:
        _intensity_rules += (
            '  - SLOT 1 IS THE HOOK — the first frame the viewer sees, and the one '
            'that decides whether they watch. Write it as the single most arresting '
            'image in the whole episode: close, direct and impossible to scroll '
            'past — a face filling the frame, a body mid-action, a moment of danger, '
            'a detail nobody expects. It must NOT be an establishing shot, a '
            'landscape, an object, a building or a wide view of anywhere. Its Murch '
            "brief says arc=hook and shot=extreme close-up; obey both. If slot 1's "
            'own narration is calm or introductory, ignore that and draw the image '
            'from the most compelling material anywhere in this episode. It must '
            "carry ONE unmistakable cue of this episode's subject — the object, "
            'costume, symptom, weapon or setting a viewer would name the topic '
            'from — so the frame could belong to no other film\n'
        )

    return (
        f'I am creating a {n}-image documentary slideshow.\n'
        f'Topic: {topic} — "{_essay_title_for_prompt}"\n'
        f'Visual style: {_style_ctx}\n\n'
        f'{_period_lock_section}'
        f'{_murch_section}\n\n'
        f'{_anchor_section}'
        f'Generate exactly {n_batch} FLUX image prompt PAIRS for image slots '
        f'{slot_start + 1}–{slot_end} of {n}.\n\n'
        f'For EACH slot write TWO prompts:\n'
        f'  S (Standard) — directly depicts the narrative beat using the 10-part framework below\n'
        f'  C (Counterpoint) — instead of the literal act, shows its emotional consequence or '
        f'cause; metaphorical, indirect; what the camera lingers on after the moment passes; '
        f'30–50 words; same period and style, different visual angle\n\n'
        f'Apply this 10-part framework to each S prompt:\n'
        f'  1. Subject — the primary visual anchor (person, object, or scene centrepiece)\n'
        f'  2. Action + Context — what is happening and why it matters narratively\n'
        f'  3. Environment + Setting — specific, grounded, named location or era\n'
        f'  4. Foreground Depth — a near-camera element (face, object, texture — never a hand) that frames the scene\n'
        f'  5. Visual Style — genre, aesthetic, medium ({_style_ctx})\n'
        f'  6. Lighting + Color — dominant palette and lighting that reinforce the arc zone emotion\n'
        f'  7. Camera + Composition — use the exact shot type from the Murch brief above\n'
        f'  8. Detail + Texture — materials, surfaces, micro-detail that sell period and realism\n'
        f'  9. Human Presence — are people visible? how many, their posture and expression\n'
        f' 10. Quality — {_quality_tag}\n\n'
        f'Rules:\n'
        f'  - S prompt = one dense paragraph of 50–70 words, no line breaks inside it\n'
        f'  - C prompt = one sentence or short paragraph of 30–50 words, no line breaks\n'
        f'  - NEVER repeat the same visual setting, angle, or subject in consecutive S prompts\n'
        f'  - Vary: close-up ↔ wide shot, interior ↔ exterior, people ↔ objects ↔ spaces\n'
        f'  - TIME-LOCK: each image depicts the beat in ITS OWN slot narration above — '
        f'never a beat from an earlier or later slot, and never reveal later story '
        f'developments early'
        + (
            ' (SLOT 1 IS EXEMPT — the hook is a mood frame, not a time-locked '
            'beat, and may draw on the most compelling subject matter anywhere '
            'in the episode; it must still obey the period lock)\n'
            if _hook_on
            else '\n'
        )
        + (
            '  - The renderer WILL print legible text — keep written surfaces '
            'out of frame, cropped away, or physically unreadable (blur, '
            'distance, shadow). '
            if _sch_family_early == 'qwen'
            else '  - FLUX cannot render legible text — it produces convincing-looking gibberish. '
        )
        + 'A document may appear in a shot, but it must never be the '
        'SUBJECT of one. Never open a prompt with a manuscript, map, scroll, '
        'letter, treaty, ledger, inscription or banner as the thing the camera '
        'is looking at. When a beat is genuinely about a written thing, show '
        'the ACT instead — the hand that seals it, the courier who carries it, '
        'the faces of the men it condemns — with the document oblique, cropped '
        'by the frame edge, or thrown out of the focal plane so its lettering '
        'reads as texture and nothing on it is presented to be read\n'
        '  - The shot type in the Murch brief overrides your own camera preference\n'
        + _period_lock_rule
        + _hands_rule
        + _skin_rule
        + (
            '  - BATTLE/COMBAT TOPIC: Prioritize flesh, muscle, sweat, blood, weapon '
            'impact, motion blur on blades, fire, dust, screaming crowds. '
            'ONLY use calm/scholarly imagery when arc_zone=exposition or arc_zone=resolution.\n'
            if _is_battle_topic
            else ''
        )
        + _intensity_rules
        + f'  - Write ONLY the numbered pairs. No headers, preamble, or commentary.\n'
        f'  - Strict format (every slot, in order):\n'
        f'    "{slot_start + 1}S. [standard prompt]"\n'
        f'    "{slot_start + 1}C. [counterpoint prompt]"\n'
        f'    "{slot_start + 2}S. [next standard]"\n'
        f'    "{slot_start + 2}C. [next counterpoint]"\n\n'
        f'{_narration_section}'
    )


def period_guard(ctx, pairs: list, *, n: int, _ak: str, _system: str, _period_lock_rule: str) -> list:
    """
    Reject present-day imagery before it reaches the renderer.

    The PERIOD LOCK instruction steers; this decides. A prompt that
    still names a car, a shopfront or "contemporary" anything gets
    one corrective re-ask, then a deterministic scrub — the episode
    never renders a modern frame because a model ignored a rule.
    """
    _era_lock = ctx._era_lock
    _log = ctx._log
    _slot_word_bounds = ctx._slot_word_bounds
    narration_script = ctx.narration_script
    pipeline_id = ctx.pipeline_id
    topic = ctx.topic
    if not _era_lock['is_historical'] or not pairs:
        return pairs
    _viol = []
    for _pi_g, _pair in enumerate(pairs):
        _hits_s = _scan_modern_terms(_pair.get('standard', ''))
        _hits_c = _scan_modern_terms(_pair.get('counterpoint', ''))
        if _hits_s or _hits_c:
            _viol.append({'idx': _pi_g, 'slot': _pi_g + 1, 'terms': sorted(set(_hits_s) | set(_hits_c))})
    if not _viol:
        _log('INFO', 'Stage 3.5', f'Period guard: {len(pairs)} prompts clean — no present-day imagery')
        return pairs

    _log(
        'WARNING',
        'Stage 3.5',
        f'Period guard: {len(_viol)} prompt(s) contain present-day imagery — '
        f're-asking: ' + '; '.join(f'slot {v["slot"]} {v["terms"]}' for v in _viol[:6]),
    )

    # ── One corrective re-ask, offending slots only ──────────────
    _fixed: dict = {}
    _guard_words = narration_script.split()
    try:
        _lines = []
        for _v in _viol:
            _w0_g, _w1_g = _slot_word_bounds(_v['idx'], n)
            _lines.append(
                f'  Slot {_v["slot"]} — rejected for: {", ".join(_v["terms"])}\n'
                f'    narration: "{" ".join(_guard_words[_w0_g:_w1_g])[:300]}"\n'
                f'    rejected prompt: {pairs[_v["idx"]].get("standard", "")[:300]}'
            )
        _fix_msg = (
            f'These documentary image prompts were rejected: they depict the '
            f'present day, but every image in this episode must depict '
            f'{_era_lock["period_label"]}.\n\n'
            + '\n'.join(_lines)
            + '\n\n'
            + 'The narration words "today", "still", "now" and "modern" are '
            'rhetorical — they describe legacy, not a present-day scene. '
            'Rewrite each as the HISTORICAL subject the beat refers to.\n\n'
            + _period_lock_rule
            + '\n'
            + 'Return ONLY the replacement pairs in this exact format, '
            'one prompt per line:\n'
            '  "<slot>S. [standard prompt, 50-70 words]"\n'
            '  "<slot>C. [counterpoint prompt, 30-50 words]"\n'
        )
        _rf = _llm_client(_ak).messages.create(
            model=_LLM_LARGE,
            max_tokens=4000,
            temperature=0.7,
            system=_system,
            messages=[{'role': 'user', 'content': _fix_msg}],
        )
        _rf_raw = _rf.content[0].text.strip()
        _log_prompt(
            'claude_period_fix',
            'Stage 3.5',
            pipeline_id,
            _rf_raw,
            meta={'topic': topic, 'pipeline_type': 'scholarly', 'slots': [v['slot'] for v in _viol]},
            direction='received',
            role='assistant',
            llm=_LLM_LARGE,
            from_who=_LLM_LARGE,
            to_who='system',
        )
        _record_token_usage(
            model=_LLM_LARGE,
            prompt_tokens=_rf.usage.input_tokens,
            completion_tokens=_rf.usage.output_tokens,
            pipeline_id=pipeline_id,
            stage='Stage 3.5',
            pipeline_type='scholarly',
        )
        for _ln in _rf_raw.split('\n'):
            _m = _re_bp.match(r'^\s*"?(\d+)([SC])\.\s+(.*?)"?\s*$', _ln.strip())
            if _m:
                _fixed.setdefault(int(_m.group(1)), {})[_m.group(2)] = _m.group(3).strip()
    except Exception as _fe:
        _log('WARNING', 'Stage 3.5', f'Period guard re-ask failed: {_fe}')

    # ── Apply, then scrub anything still dirty ───────────────────
    _repaired, _scrubbed = 0, 0
    for _v in _viol:
        _cand = _fixed.get(_v['slot'], {})
        for _key, _tag in (('standard', 'S'), ('counterpoint', 'C')):
            _new = _cand.get(_tag, '')
            if _new and len(_new.split()) >= 10 and not _scan_modern_terms(_new):
                pairs[_v['idx']][_key] = _new
                _repaired += 1
                continue
            _cur = pairs[_v['idx']].get(_key, '')
            if _scan_modern_terms(_cur):
                # Last resort: strip the present-day tokens and restate
                # the period. Never let a modern prompt through.
                _clean = _MODERN_TERM_RE.sub('', _cur)
                _clean = _re_bp.sub(r'\s{2,}', ' ', _clean)
                _clean = _re_bp.sub(r'\s+([,.])', r'\1', _clean)
                _clean = _re_bp.sub(r'(,\s*){2,}', ', ', _clean).strip(' ,')
                pairs[_v['idx']][_key] = (
                    f'{_clean}, period-accurate {_era_lock["period_label"]}, historical reconstruction'
                )
                _scrubbed += 1
    _log(
        'INFO',
        'Stage 3.5',
        f'Period guard: {_repaired} prompt(s) rewritten, {_scrubbed} scrubbed — 0 present-day prompts reach FLUX',
    )
    return pairs


def bare_noun_guard(ctx, pairs: list) -> list:
    """
    The deterministic backstop behind the NO BARE NOUNS rule.

    _period_guard rejects present-day WORDS; this rewrites present-day
    DEFAULTS: a bare "boat", "shoe", "lantern", "window", "shirt" is
    replaced by its period form for this episode's era bucket, a
    watch or bracelet is dropped, any prompt with people and no hair
    described gets the period hair line, and below 'extreme' the
    medical nouns the renderer paints as gore are rewritten onto
    intact skin. Runs on every S and C prompt. Idempotent.
    """
    _era_lock = ctx._era_lock
    _log = ctx._log
    _sch_intensity = ctx._sch_intensity
    if not pairs:
        return pairs
    _n_noun = _n_hair = _n_gore = 0
    _samples: list = []
    for _pair in pairs:
        for _key in ('standard', 'counterpoint'):
            _txt = _pair.get(_key, '')
            if not _txt:
                continue
            if _era_lock['is_historical']:
                _txt, _ch = _period_noun_rewrite(_txt, _era_lock)
                if _ch:
                    _n_noun += len(_ch)
                    _samples.extend(_ch[:2])
                _txt, _added = _period_hair_backstop(_txt, _era_lock)
                _n_hair += int(_added)
            _txt, _gch = _render_safety_rewrite(_txt, _sch_intensity['rank'])
            if _gch:
                _n_gore += len(_gch)
                _samples.extend(_gch[:2])
            _pair[_key] = _txt
    _log(
        'INFO',
        'Stage 3.5',
        f'Bare-noun guard: {_n_noun} noun(s) given their period form, '
        f'{_n_hair} hair line(s) added, {_n_gore} render-gore noun(s) rewritten'
        + (f' — e.g. {"; ".join(_samples[:4])}' if _samples else ''),
    )
    return pairs


def text_subject_guard(ctx, pairs: list) -> list:
    """
    Stop a shot being BUILT AROUND writing.

    FLUX renders convincing-looking gibberish, so a manuscript filling
    the frame is always a defect — the viewer's eye goes straight to
    lettering that says nothing. A document in the scene is fine; a
    document as the subject is not. "Subject" is decided by position:
    the thing a prompt opens on is the thing the camera is looking at.

    Deliberately NOT a pixel gate. moondream is blind to ink, and a
    model-free MSER text detector measured no separation on real
    renders here (a cavalry frame scored above every document frame),
    so gating on it would block good images and pass bad ones.
    """
    _log = ctx._log
    if not pairs:
        return pairs
    _treated = 0
    for _pair in pairs:
        for _key in ('standard', 'counterpoint'):
            _txt = _pair.get(_key, '')
            if not _txt or _TEXT_FRAMING_FIX in _txt:
                continue
            _body = _re_bp.sub(r'^\s*cinematic photograph\s*', '', _txt, flags=_re_bp.I)
            # S prompts: the subject is what the prompt OPENS on
            # (7-word window, measured — see _TEXT_SUBJ_WINDOW). C
            # prompts are 30-50 words of "what the camera lingers on
            # after the moment passes": a written thing anywhere in
            # one is the thing being lingered on. Slot 35 of the
            # Black Death run shipped a parchment map as the subject
            # through exactly this gap — its C prompt named the map
            # past the window.
            _head = _body if _key == 'counterpoint' else ' '.join(_body.split()[:_TEXT_SUBJ_WINDOW])
            if _TEXT_SUBJECT_RE.search(_head):
                _pair[_key] = _txt.rstrip(' .,') + _TEXT_FRAMING_FIX
                _treated += 1
    if _treated:
        _log(
            'INFO',
            'Stage 3.5',
            f'Text-subject guard: {_treated} prompt(s) reframed — document pushed off-axis and out of the focal plane',
        )
    return pairs
