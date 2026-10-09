# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The steps of ``generate_scene`` — one function per seam of the per-scene pass.

``stage_035_scene_loop.generate_scene`` was a single 399-line function with
seven comment-banner seams: compose the prompt, condition IPAdapter, render with
up to three QC-driven retries, rescue the scene when strict QC never passed,
settle the file on disk, reset the conditioning, lock scene 0 as the IPAdapter
master and record the scene in ``img_paths`` plus the image-meta list Stage 3.6
repairs. Each is a function here; ``generate_scene`` is the list of calls.

Two small value objects carry what used to be plain locals across the seams:
:class:`ScenePrompt` (what composition produced) and :class:`RenderOutcome`
(what the retry loop learned, which the rescue rungs then update). Nothing else
changed — same calls, same log lines, same order, same state writes."""

from __future__ import annotations

import logging as _zyg_logging
import os
import shutil
from dataclasses import dataclass, field

from zyg_workflows import gui_state
from zyg_workflows.pipeline_storyteller import _st_env_on
from zyg_workflows.stage_runner import _log_prompt
from zyg_workflows.storyteller.stage_035_generate import generate_one
from zyg_workflows.storyteller.stage_035_qa import scene_quality_ok, scene_quality_reason

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')

_SHOT_KEYWORDS = {
    # 2026-07-24 r3: 'close-up portrait, face in frame' made FLUX
    # render EXTREME macro crops (eyes-and-forehead filling 720p)
    # whose huge smooth regions measure near-zero sharpness — at
    # cfg 3.5 double guidance they collapsed into the dd36662e
    # gradient blob. Head-and-shoulders keeps a real composition.
    'close-up': 'head and shoulders close-up portrait, natural camera distance, ',
    'medium': 'medium shot, waist up, ',
    'wide': 'wide establishing shot, full body visible, ',
    'establishing': 'wide establishing shot, environment prominent, ',
    'over-the-shoulder': 'over-the-shoulder shot, background visible, ',
}

# The tint cycle the two reference fallbacks share, so consecutive rescued
# scenes do not ship as byte-identical frames.
_BRIGHTNESS_TINTS = [1.0, 0.92, 1.08, 0.96, 1.04, 0.90, 1.12]


@dataclass
class ScenePrompt:
    """Everything prompt composition decided for one scene.

    ``prompt`` is the composed FLUX prompt (already logged), ``shot_type`` and
    ``emotion`` are the scene's own fields as the renderer wants them, and
    ``img_path`` is where this scene's frame must end up."""

    prompt: str
    shot_type: str
    emotion: str
    img_path: str


@dataclass
class RenderOutcome:
    """What the three render attempts produced for one scene.

    ``generated`` is the only thing the later steps gate on; the rescue rungs
    set it when they substitute a frame. ``best_snap`` is the path of the
    highest-ranked attempt's snapshot and ``best_qc_score`` its rank (``-999.0``
    when nothing was ranked, ``<= 0`` when every attempt read as
    greybox/dark/unreadable). The ``best_hand_*`` fields track the best hand-QC
    reading across attempts; the delivered frame is scored separately."""

    best_snap: str
    generated: bool = False
    best_qc_score: float = -999.0
    best_hand_qa: float = -1.0
    best_hand_issues: list = field(default_factory=list)


def scene_bible(pipeline_state, char_id):
    """The character bible for this run — from the pipeline state, else loaded.

    Returns the bible package, or ``None`` when there is no character or the
    service cannot produce one."""
    bible = pipeline_state.get('character_bible') if isinstance(pipeline_state, dict) else None
    if not bible and char_id:
        try:
            from zyg_workflows import character_bible_service as _cbs_st

            bible = _cbs_st.load(char_id)
        except Exception:
            bible = None
    return bible


def animated_package(bible):
    """The bible the prompt composer should see for an animated render.

    A deep copy whose ``style_profile.render_style`` is forced to ``animated``,
    so the composer appends the toon quality suffix rather than the photoreal
    one. Returns ``bible`` unchanged if the copy cannot be made."""
    try:
        import copy as _copy_anim_pkg

        pkg = _copy_anim_pkg.deepcopy(bible or {})
        pkg.setdefault('style_profile', {})['render_style'] = 'animated'
        return pkg
    except Exception:
        return bible


def shot_keyword(shot_type):
    """The framing phrase for a shot type, or '' for an unknown one."""
    return _SHOT_KEYWORDS.get(shot_type, '')


def continuity_prefix(scenes, _si, pipeline_state):
    """The continuity slot of the prompt: what carries over into scene ``_si``.

    Up to two of the previous scene's ``character_state`` clothing/hair/lighting
    values (truncated to 40 characters), then — because
    ``compose_storyteller_render_prompt`` would otherwise append it in the
    highest-weight tail position, where an invite-link holder could restate and
    thereby override the character's appearance — the sanitised public
    ``extra_prompt``. Returns '' when neither applies."""
    prefix = ''
    if _si > 0:
        _prev_state = scenes[_si - 1].get('character_state') or {}
        if isinstance(_prev_state, dict) and _prev_state:
            _cont_parts = [
                v
                for v in [
                    _prev_state.get('clothing'),
                    _prev_state.get('hair'),
                    _prev_state.get('lighting'),
                ]
                if v
            ]
            if _cont_parts:
                prefix = ', '.join(_cont_parts[:2])[:40] + ', '

    # 2026-07-31: the PUBLIC extra_prompt no longer rides in
    # char_extra. It is sanitised in Stage 1 and injected HERE, in the
    # continuity slot: after the scene core, BEFORE the style
    # prefix, the quality suffix and the identity snippet.
    _extra_clean_st = str(pipeline_state.get('_st_extra_prompt_clean') or '')
    if _extra_clean_st:
        prefix = f'{prefix}{_extra_clean_st}, ' if prefix else f'{_extra_clean_st}, '
    return prefix


def identity_extra(bible):
    """The compact canonical identity snippet for the prompt tail.

    2026-07-24 r3: appended so txt2img scenes hold hair/eyes/heritage/skin
    against any generic re-description in the LLM scene prompt. Returns '' when
    the bible carries none, or when the service is unavailable (logged)."""
    try:
        from zyg_workflows import character_bible_service as _cbs_ident

        return _cbs_ident.storyteller_identity_snippet(bible) or ''
    except Exception as _exc:
        _zyg_log.warning('canonical identity snippet unavailable, the scene prompt continues without it: %s', _exc)
        return ''


def compose_scene_prompt(ctx, st, _si: int, scene) -> ScenePrompt:
    """Compose, log and return the prompt for scene ``_si``.

    Scene text (or its description) gains the trigger token, the shot keyword,
    the continuity prefix, the style prefix and the identity snippet through
    ``compose_storyteller_render_prompt``; a composer failure falls back to the
    flat concatenation capped at 1200 characters. Writes the Stage 3.5 log line
    and the prompt log, then returns the :class:`ScenePrompt`."""
    _flux_prompt_raw = scene.get('flux_prompt', '') or scene.get('description', '')
    _b_st = scene_bible(ctx.pipeline_state, ctx.char_id)
    # animated-effective package for the prompt composer (toon
    # quality suffix, not photoreal). Built here where _b_st exists.
    _comp_pkg_st = animated_package(_b_st) if ctx._animated_render else _b_st

    if ctx.trigger_token and ctx.trigger_token not in _flux_prompt_raw:
        _flux_prompt_raw = f'{ctx.trigger_token} {_flux_prompt_raw}'

    _shot_type_st = scene.get('shot_type', 'medium')
    _shot_kw = shot_keyword(_shot_type_st)
    _cont_prefix = continuity_prefix(ctx.scenes, _si, ctx.pipeline_state)
    _char_extra_st = identity_extra(_b_st)
    _scene_emotion_st = str(scene.get('emotion', 'calm'))
    try:
        from zyg_workflows import character_bible_service as _cbs_comp

        _flux_prompt_st = _cbs_comp.compose_storyteller_render_prompt(
            _flux_prompt_raw,
            _comp_pkg_st,
            shot_type=_shot_type_st,
            shot_keyword=_shot_kw,
            style_prefix=st._style_prefix_st,
            continuity_prefix=_cont_prefix,
            char_extra=_char_extra_st,
        )
    except Exception:
        _flux_prompt_st = (f'{_shot_kw}{_flux_prompt_raw}, {st._style_prefix_st}{_cont_prefix}')[:1200]

    ctx._log('INFO', 'Stage 3.5', f'[{_si + 1}/{ctx.n_scenes}] {_flux_prompt_st[:80]}…')
    _log_prompt('flux_image', 'Stage 3.5', ctx.pipeline_id, _flux_prompt_st, {'scene': _si + 1})
    return ScenePrompt(
        prompt=_flux_prompt_st,
        shot_type=_shot_type_st,
        emotion=_scene_emotion_st,
        img_path=os.path.join(ctx.out_dir, f'scene_{_si:03d}.png'),
    )


def condition_ipadapter(ctx, st, _si: int) -> bool:
    """Condition the FLUX pipeline on the master reference for scenes 1+.

    Diffusers path only, and only once a scene-0 master has been registered.
    Returns whether conditioning was actually set, so the caller knows to reset
    it afterwards. A broken service (2026-07-31) disables IPAdapter for the rest
    of the run loudly, rather than raising a silent AttributeError per scene."""
    _ipa_was_set = False
    if st._st_use_flux_diffusers and st._ipa_ready_st and st._ipa_svc_st is not None and _si > 0 and st._ipa_ref_path:
        try:
            _ipa_was_set = st._ipa_svc_st.condition_pipe(
                gui_state._FLUX_DEV_PIPELINE_CACHE,
                'scene_ref',
                scale=0.55,
                log_fn=lambda m: ctx._log('INFO', 'Stage 3.5', m),
            )
        except (AttributeError, TypeError) as _ipa_ae:
            # 2026-07-31: an identity mechanism that is BROKEN must
            # not read as a healthy one — this used to be a silent
            # AttributeError on a None service, every scene.
            st._ipa_ready_st = False
            ctx._log(
                'WARNING',
                'Stage 3.5',
                f'IPAdapter conditioning is BROKEN ({_ipa_ae!r}) — '
                f'disabled for the rest of the run; scenes have NO '
                f'identity conditioning on the diffusers path',
            )
        except Exception as _ipa_ce:
            ctx._log('WARNING', 'Stage 3.5', f'IPAdapter condition: {_ipa_ce!r}')
    return _ipa_was_set


def render_with_retries(ctx, st, _si: int, sp: ScenePrompt) -> RenderOutcome:
    """Render the scene up to three times, stopping at the first strict-QC pass.

    Each attempt varies seed and prompt suffix; a blurred second or third
    attempt gets a sharpen pass before QC, and every rendered attempt is ranked
    so the best one survives as a snapshot for the rescue rungs. A FLUX error
    (rather than a QC failure) stops retrying at once. Returns the
    :class:`RenderOutcome`."""
    _log = ctx._log
    outcome = RenderOutcome(best_snap=f'{sp.img_path}.best_attempt.png')
    for _attempt in range(3):
        _prompt_attempt = sp.prompt + st._ssh_st.retry_prompt_suffix(_attempt)
        _ok = generate_one(
            ctx,
            st,
            _prompt_attempt,
            sp.img_path,
            init_img=st._char_ref_img,
            seed_attempt=_attempt,
            scene_index=_si,
            shot_type=sp.shot_type,
            scene_emotion=sp.emotion,
        )
        # r4 review fix: a failed FLUX attempt has no image to
        # judge — None (unknown), not 0.0 (the 0.0 sentinel
        # leaked into meta qa_score and sent fallback frames
        # into Stage 3.6 repair).
        _hand_s, _hand_iss = st._hand_qa_fn(sp.img_path) if _ok else (None, [])
        # r4: _hand_s may be None (QC unavailable) — unknown is
        # neither best nor worst; skip the best-tracking then.
        if _hand_s is not None and _hand_s > outcome.best_hand_qa:
            outcome.best_hand_qa = _hand_s
            outcome.best_hand_issues = _hand_iss
        if _ok and _attempt >= 1 and scene_quality_reason(ctx, st, sp.img_path) == 'blur':
            if st._ssh_st.sharpen_image_file(sp.img_path):
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Scene {_si + 1}: applied sharpen pass before QC (attempt {_attempt + 1})',
                )
        if _ok:
            _rank = st._ssh_st.scene_qc_rank_score(
                sp.img_path,
                st._qc_style_st,
                hand_qa_fn=st._hand_qa_fn,
                lora_active=st._st_lora_active,
            )
            if _rank > outcome.best_qc_score:
                outcome.best_qc_score = _rank
                shutil.copy2(sp.img_path, outcome.best_snap)
        if _ok and scene_quality_ok(ctx, st, sp.img_path):
            outcome.generated = True
            break
        if _ok:
            if _attempt < 2:
                _qc_reason = scene_quality_reason(ctx, st, sp.img_path)
                _hand_lbl = 'n/a' if _hand_s is None else f'{_hand_s:.2f}'
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Scene {_si + 1} QC retry ({_qc_reason}, hand={_hand_lbl}) — '
                    f'attempt {_attempt + 2}/3 (seed+prompt vary)…',
                )
        else:
            break  # FLUX error — stop retrying
    return outcome


def tint_copy(src, dest, _si: int) -> float:
    """Write a 1280x720 brightness-tinted copy of ``src`` to ``dest``.

    The tint comes from the shared seven-step cycle indexed by the scene number,
    so consecutive fallback scenes are not byte-identical. Returns the tint
    factor used; raises whatever PIL raises."""
    from PIL import Image as _PIL_fb, ImageEnhance as _IE_fb

    _ref_img_fb = _PIL_fb.open(src).convert('RGB').resize((1280, 720))
    _b_tint = _BRIGHTNESS_TINTS[_si % len(_BRIGHTNESS_TINTS)]
    _ref_img_fb = _IE_fb.Brightness(_ref_img_fb).enhance(_b_tint)
    _ref_img_fb.save(dest)
    return _b_tint


def rescue_scene(ctx, st, _si: int, sp: ScenePrompt, outcome: RenderOutcome) -> None:
    """Try to salvage a scene that never passed strict QC, in three rungs.

    1. the best ranked attempt, if any attempt ranked above zero — 2026-07-24:
       a real render always beats a tinted reference still, and the old >5.0
       gate meant the rescue never fired and 17/25 scenes shipped as tints;
    2. a tinted copy of the scene-0 master, for scenes 1+;
    3. a tinted copy of the character portrait — ONLY behind
       ``ZYG_ST_PORTRAIT_FRAME_FALLBACK=1`` (default off), because a resized
       character portrait is never a correct story frame and when the reference
       was a bogus preview it was a portrait of the WRONG PERSON.

    Sets ``outcome.generated`` and records the scene under
    ``_st_rescued_scenes`` / ``_st_fallback_scenes`` when a rung succeeds."""
    _log = ctx._log
    pipeline_state = ctx.pipeline_state
    if os.path.isfile(outcome.best_snap) and outcome.best_qc_score > 0.0:
        shutil.copy2(outcome.best_snap, sp.img_path)
        _log(
            'WARNING',
            'Stage 3.5',
            f'Scene {_si + 1}: strict QC failed — using best attempt (score={outcome.best_qc_score:.1f})',
        )
        # 2026-07-24 r3: rescues are below-standard frames and MUST
        # count toward the degradation gate — run dd36662e shipped a
        # rescued defocused blob as the opener with no state trace.
        pipeline_state.setdefault('_st_rescued_scenes', []).append(_si + 1)
        outcome.generated = True
    elif _si > 0 and pipeline_state.get('_st_scene0_master'):
        try:
            _b_tint = tint_copy(pipeline_state['_st_scene0_master'], sp.img_path, _si)
            _log(
                'WARNING',
                'Stage 3.5',
                f'Scene {_si + 1}: scene_000 master fallback (tint {_b_tint:.2f})',
            )
            pipeline_state.setdefault('_st_fallback_scenes', []).append(_si + 1)
            outcome.generated = True
        except Exception as _fb_e:
            _log('WARNING', 'Stage 3.5', f'scene_000 fallback failed: {_fb_e}')
    elif (
        _st_env_on('ZYG_ST_PORTRAIT_FRAME_FALLBACK', '0')
        and not st._st_blender_ds
        and pipeline_state.get('char_reference_image')
        and os.path.isfile(pipeline_state['char_reference_image'])
    ):
        try:
            _b_tint = tint_copy(pipeline_state['char_reference_image'], sp.img_path, _si)
            _log(
                'WARNING',
                'Stage 3.5',
                f'Scene {_si + 1}: photo reference fallback (tint {_b_tint:.2f}) — ZYG_ST_PORTRAIT_FRAME_FALLBACK=1',
            )
            pipeline_state.setdefault('_st_fallback_scenes', []).append(_si + 1)
            outcome.generated = True
        except Exception as _fb_e:
            _log('WARNING', 'Stage 3.5', f'Photo fallback failed: {_fb_e}')


def record_failed_scene(ctx, _si: int) -> None:
    """Record scene ``_si`` as failed and say so in the log.

    2026-07-31: a scene that survived neither three attempts nor a rescue is
    tracked explicitly — and counted by the degradation gate — instead of being
    papered over with a portrait."""
    ctx.pipeline_state.setdefault('_st_failed_scenes', []).append(_si + 1)
    ctx._log(
        'ERROR',
        'Stage 3.5',
        f'Scene {_si + 1}: FAILED after 3 attempts and no usable '
        f'master — no portrait substitution (a character portrait '
        f'is not a story frame); counted toward the degradation gate',
    )


def finalize_scene_file(ctx, st, _si: int, sp: ScenePrompt, outcome: RenderOutcome) -> None:
    """Settle the scene's file on disk and lock scene 0 as the photoreal master.

    A failed scene with no file at all gets a near-black slate so later stages
    have something to read; otherwise the best-attempt snapshot is removed.
    Scene 0 is recorded as ``_st_scene0_master`` when it exists and passes
    strict QC, which is what the rescue rung 2 of later scenes falls back to."""
    if not outcome.generated and not os.path.isfile(sp.img_path):
        try:
            from PIL import Image as _PIL_st

            _PIL_st.new('RGB', (1280, 720), (10, 10, 15)).save(sp.img_path)
        except Exception as _exc:
            _zyg_log.warning('placeholder frame write failed, this scene has no image: %s', _exc)
    elif os.path.isfile(outcome.best_snap):
        try:
            os.remove(outcome.best_snap)
        except OSError as _exc:
            _zyg_log.debug('rejected snapshot cleanup skipped: %s', _exc)

    if _si == 0 and os.path.isfile(sp.img_path) and scene_quality_ok(ctx, st, sp.img_path):
        ctx.pipeline_state['_st_scene0_master'] = sp.img_path
        ctx._log('INFO', 'Stage 3.5', 'Scene 0 locked as photoreal master for later scenes')


def reset_ipadapter(ctx, st, ipa_was_set: bool) -> None:
    """Drop the scene conditioning this pass set, if it set any.

    2026-07-31: was a silent no-op on a None service, so conditioning could
    persist into the next scene unnoticed."""
    if ipa_was_set and st._ipa_svc_st is not None and gui_state._FLUX_DEV_PIPELINE_CACHE is not None:
        try:
            st._ipa_svc_st.reset_conditioning(gui_state._FLUX_DEV_PIPELINE_CACHE)
        except (AttributeError, TypeError) as _ipa_rc:
            ctx._log('WARNING', 'Stage 3.5', f'IPAdapter reset_conditioning failed: {_ipa_rc!r}')
        except Exception as _exc:
            _zyg_log.warning('IPAdapter reset_conditioning failed, conditioning may persist: %s', _exc)


def lock_ipadapter_master(ctx, st, _si: int, sp: ScenePrompt) -> None:
    """Scene 0 only: make the frame good enough to be the IPAdapter reference.

    Up to two extra full regenerations if scene 0 failed strict QC, then
    register it as the ``scene_ref`` every later scene conditions on.
    2026-07-31: the guard is on the SERVICE, not just the flag — those
    regenerations used to be spent and then thrown away because
    ``register_reference`` raised AttributeError on a None service every time,
    so no scene was ever IPAdapter-conditioned."""
    if not (
        _si == 0
        and st._st_use_flux_diffusers
        and st._ipa_svc_st is not None
        and st._ipa_ready_st
        and st._ipa_ref_path is None
    ):
        return
    _log = ctx._log
    if not scene_quality_ok(ctx, st, sp.img_path):
        _log('INFO', 'Stage 3.5', 'Scene 0 failed quality check — regenerating for master reference…')
        for _r0 in range(2):
            generate_one(
                ctx,
                st,
                sp.prompt + st._ssh_st.retry_prompt_suffix(_r0 + 1),
                sp.img_path,
                init_img=st._char_ref_img,
                seed_attempt=_r0 + 1,
                scene_index=0,
                shot_type=sp.shot_type,
                scene_emotion=sp.emotion,
            )
            if scene_quality_reason(ctx, st, sp.img_path) == 'blur':
                st._ssh_st.sharpen_image_file(sp.img_path)
            if scene_quality_ok(ctx, st, sp.img_path):
                _log('INFO', 'Stage 3.5', f'Scene 0 quality OK on regen {_r0 + 1}')
                break
    try:
        st._ipa_svc_st.register_reference('scene_ref', sp.img_path)
        st._ipa_ref_path = sp.img_path
        _log('INFO', 'Stage 3.5', 'IPAdapter master reference locked: scene_000')
    except (AttributeError, TypeError) as _ipa_rae:
        st._ipa_ready_st = False
        _log(
            'WARNING',
            'Stage 3.5',
            f'IPAdapter register_reference is BROKEN ({_ipa_rae!r}) — identity conditioning disabled for this run',
        )
    except Exception as _ipa_re:
        _log('WARNING', 'Stage 3.5', f'IPAdapter register failed: {_ipa_re!r}')


def record_scene_meta(ctx, st, _si: int, scene, sp: ScenePrompt) -> None:
    """Append the delivered frame to ``img_paths`` and the Stage 3.6 meta list.

    r4 review fix: the DELIVERED file is scored, not the best attempt — rescue
    and fallback can ship different content than the frame that earned the best
    hand-QC reading. Hand QC is memoized per (path, mtime), so this re-score is
    free when the delivered file is the last-scored one. Also advances the job's
    progress percentage for this scene."""
    st.img_paths.append(sp.img_path)
    _del_score, _del_issues = st._hand_qa_fn(sp.img_path)
    st._st_image_meta.append(
        {
            'path': sp.img_path,
            'index': _si,
            'prompt': sp.prompt,
            'qa_score': (None if _del_score is None else round(_del_score, 3)),
            'qa_issues': _del_issues,
            'subject': (scene.get('description') or '')[:60],
        }
    )
    ctx.job['progress_pct'] = 30 + int((_si + 1) / ctx.n_scenes * 30)
