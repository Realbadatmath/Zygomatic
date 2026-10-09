# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
import os
import re
import threading
from zyg_workflows import gui_state

from zyg_workflows.subproc_registry import _register_marker, _update_marker
from zyg_workflows.vram_manager import (
    _hw_monitor_loop,
    _release_pipeline_vram,
)
from zyg_workflows.pipeline_config import _RUNTIME_DIR
from zyg_workflows.runtime import (
    _ams_iso,
    _push_error_log,
    _runtime_path,
    workflow_jobs as _workflow_jobs,
)
from zyg_workflows import paths

# The seal call itself moved to storyteller/stage_05b_subtitles.py with Stage 5b.
# This binding stays: tests/test_storyteller_seal.py asserts `P._seal is provenance_seal`,
# the cheapest proof that the hooked module still imports.
from zyg_workflows import provenance_seal as _seal  # noqa: F401  # the seal test asserts this binding
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# 2026-07-31: identity-audit hardening. Everything below exists because a broken
# preview-sweep endpoint wrote a generic adult-female non-LoRA PNG into a
# 12-year-old boy's dataset ROOT as preview_flux_front.png and that ONE file
# propagated into the render path, the identity-QC anchor and the delivered
# frames — while the client-supplied character_params described a different
# person than the server-side bible and nothing ever compared the two.
_ST_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')


def _st_env_on(name: str, default: str = '1') -> bool:
    """2026-07-31: ZYG_ flag helper — the DEFAULT value is the NEW (fixed)
    behaviour; set the flag to 0/false/no/off to roll back to the old one."""
    return str(os.environ.get(name, default)).strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def _st_char_manifest(char_id: str, bible: dict | None = None) -> dict:
    """2026-07-31: the on-disk training manifest — the SERVER's record of how a
    character was actually trained (source / render_mode / training stills).

    Render mode is a property of how the character was TRAINED; it must never be
    read from the request body (finding #58). Degrades to {} — every caller
    treats an empty manifest as "unknown", never as an assertion."""
    _dirs = []
    try:
        _bd = ((bible or {}).get('dataset_dir') or '').strip()
        if _bd:
            _dirs.append(_bd)
    except (AttributeError, TypeError) as _exc:
        _zyg_log.debug('bible dataset_dir unreadable: %s', _exc)
    if char_id:
        _dirs.append(os.path.join(_ST_DATASET_ROOT, char_id))
    for _d in _dirs:
        try:
            _p = os.path.join(_d, 'manifest.json')
            if os.path.isfile(_p):
                with open(_p, encoding='utf-8') as _f:
                    _m = json.load(_f)
                if isinstance(_m, dict):
                    return _m
        except (OSError, json.JSONDecodeError) as _exc:
            _zyg_log.debug('render-mode manifest not readable in %s: %s', _d, _exc)
            continue
    return {}


# (param key, bible section, bible key) — 'presentation' reads
# default_presentation first, then the legacy flat style_profile mirror.
_ST_BIBLE_PARAM_MAP = (
    ('gender', 'identity', 'gender'),
    ('age', 'identity', 'age'),
    ('age_range', 'identity', 'age_range'),
    ('height', 'identity', 'height_m'),
    ('skin_tone', 'identity', 'skin_tone'),
    ('hair_color', 'identity', 'hair_color'),
    ('hair_style', 'identity', 'hair_style'),
    ('hair_length', 'identity', 'hair_length'),
    ('hair_texture', 'identity', 'hair_texture'),
    ('eye_color', 'identity', 'eye_color'),
    ('eye_shape', 'identity', 'eye_shape'),
    ('eyebrow_style', 'identity', 'eyebrow_style'),
    ('face_shape', 'identity', 'face_shape'),
    ('nose_shape', 'identity', 'nose_shape'),
    ('lip_shape', 'identity', 'lip_shape'),
    ('facial_hair', 'identity', 'facial_hair'),
    ('body_build', 'identity', 'body_build'),
    ('muscle_mass', 'identity', 'muscle_mass'),
    ('distinctive_marks', 'identity', 'distinctive_marks'),
    ('ethnic_heritage', 'identity', 'ethnic_heritage'),
    ('default_clothing', 'presentation', 'default_clothing'),
    ('default_expression', 'presentation', 'default_expression'),
    ('accessories', 'presentation', 'accessories'),
    ('posture', 'presentation', 'posture'),
    ('style', 'style_profile', 'render_style'),
    ('render_style', 'style_profile', 'render_style'),
    ('genre', 'style_profile', 'genre'),
)
# Identity-bearing keys the CLIENT may never decide for a character that already
# has a bible. Non-identity keys (extra_prompt, era, camera…) pass through.
_ST_IDENTITY_PARAM_KEYS = tuple(sorted({k for (k, _s, _b) in _ST_BIBLE_PARAM_MAP}))


def _st_bible_derived_params(bible: dict | None) -> dict:
    """2026-07-31: rebuild character_params from the SERVER-side bible.

    Only keys the bible actually carries are emitted — an empty/'auto' bible
    field is left to the client value rather than clobbered with a default
    (the 'female / brown hair / medium skin' default family is exactly what
    produced the wrong-person renders)."""
    if not isinstance(bible, dict) or not bible:
        return {}
    _ident = bible.get('identity') or {}
    _style = bible.get('style_profile') or {}
    _pres = bible.get('default_presentation') or {}
    out: dict = {}
    for _pk, _sec, _bk in _ST_BIBLE_PARAM_MAP:
        if _sec == 'identity':
            _v = _ident.get(_bk)
        elif _sec == 'style_profile':
            _v = _style.get(_bk)
        else:
            _v = _pres.get(_bk)
            if _v in (None, ''):
                _v = _style.get(_bk)
        if _v is None:
            continue
        if isinstance(_v, str):
            _v = _v.strip()
            if _v == '' or _v.lower() == 'auto':
                continue
        out[_pk] = _v
    return out


def _st_reconcile_params_with_bible(
    client_params: dict | None,
    bible: dict | None,
) -> tuple[dict, list]:
    """2026-07-31: THE BIBLE BEATS THE CLIENT (finding #35).

    character_params arrives as unvalidated JSON from a public browser and was
    the SOLE source of gender/age/hair/eyes/skin/build/clothing for the Stage 2a
    story, the Stage 2b render prompts and the fallback scene builder. Returns
    ({**client, **bible_derived}, conflicts) — conflicts lists every identity
    field where the client disagreed with the server."""
    merged = dict(client_params or {})
    derived = _st_bible_derived_params(bible)
    conflicts: list = []
    for _k, _v in derived.items():
        _cv = merged.get(_k)
        _cvs = '' if _cv is None else str(_cv).strip()
        if _cvs and _cvs.lower() not in ('auto', 'none') and _cvs.lower() != str(_v).strip().lower():
            conflicts.append(f'{_k}: client={_cvs[:60]!r} → bible={str(_v)[:60]!r}')
        merged[_k] = _v
    return merged, conflicts


def _st_age_from_params(params: dict | None) -> int | None:
    """2026-07-31: numeric age from the reconciled params, falling back to a
    nominal age for the bible's age_range bucket (voice + minor gating)."""
    _p = params or {}
    _a = _p.get('age')
    try:
        if _a is not None and str(_a).strip() != '':
            _ai = int(float(str(_a).strip()))
            if 0 < _ai < 130:
                return _ai
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('non-numeric age %r, falling back to the age_range bucket: %s', _a, _exc)
    _r = str(_p.get('age_range') or '').strip().lower()
    return {'child': 10, 'teen': 15, 'young': 24, 'adult': 35, 'mature': 50, 'elder': 70}.get(_r)


def _st_is_minor(params: dict | None) -> bool:
    """2026-07-31: True when the RESOLVED (bible) identity is a minor."""
    _p = params or {}
    _age = _st_age_from_params(_p)
    if _age is not None and _age < 18:
        return True
    return str(_p.get('age_range') or '').strip().lower() in ('child', 'teen')


def _st_pick_voice(
    gender: str,
    age: int | None,
    *,
    kind: str = 'character',
    prefer: tuple = (),
) -> tuple[str, str]:
    """2026-07-31: pick an Azure voice by GENDER + AGE from the shared catalog
    (finding: a 12-year-old boy was narrated by en-US-BrianNeural, an adult).

    Returns (voice_id, why). ('', reason) when the catalog is unavailable — the
    caller keeps its hardcoded fallback. Guarded import by design."""
    try:
        from zyg_workflows import storyteller_voice_catalog as _svc_st

        rows = _svc_st.list_storyteller_voices(kind=kind) or []
    except Exception as _svc_e:  # catalog missing → caller falls back
        return '', f'voice catalog unavailable ({_svc_e!r})'
    if not rows:
        return '', 'voice catalog empty'
    _g = str(gender or '').strip().lower()
    if _g.startswith('f') or _g in ('woman', 'girl'):
        _g = 'female'
    elif _g.startswith('m') or _g in ('man', 'boy'):
        _g = 'male'
    else:
        _g = ''

    def _gap(v: dict) -> int:
        if age is None:
            return 0
        try:
            _lo, _hi = int(v.get('age_min', 0)), int(v.get('age_max', 120))
        except Exception:
            return 0
        if _lo <= age <= _hi:
            return 0
        return _lo - age if age < _lo else age - _hi

    _by_id = {str(v.get('id')): v for v in rows}
    for _pid in prefer:
        _pv = _by_id.get(_pid)
        if _pv and _gap(_pv) == 0 and (not _g or str(_pv.get('gender', '')).lower() in (_g, 'neutral')):
            return _pid, f'catalog preferred ({_pv.get("tag", "")})'
    _best, _best_key = None, None
    for v in rows:
        _vg = str(v.get('gender', '')).strip().lower()
        if _g and _vg not in (_g, 'neutral'):
            continue
        # Gender tier dominates the age gap: an adult 'neutral' narrator voice
        # must NOT win over the same-gender child voice for a child character
        # (that is exactly how a 12-year-old boy ended up with en-US-BrianNeural).
        _tier = (0 if _vg == _g else 1) if _g else (0 if _vg == 'neutral' else 1)
        _key = (_tier, _gap(v))
        if _best_key is None or _key < _best_key:
            _best, _best_key = v, _key
    if _best is None:
        return '', f'no {kind} voice matches gender={_g or "unspecified"}'
    _why = (
        f'{_best.get("label", "")} ({_best.get("tag", "")}) '
        f'gender={_best.get("gender", "?")} '
        f'age_range={_best.get("age_min", 0)}-{_best.get("age_max", 120)}'
    )
    if _best_key and _best_key[1]:
        _why += f' — no exact age match for {age}, closest by {_best_key[1]}y'
    return str(_best.get('id') or ''), _why


# Prompt-control characters: attention weights `(x:1.4)`, BREAK/alternation
# `[a|b]`, embeddings `<lora:…>`, comfy-style `{a|b}` wildcards, CLI switches.
_ST_EXTRA_STRIP_RE = re.compile(r'[\(\)\[\]\{\}<>\|\\/:;=~^*"`\r\n\t]+')
_ST_EXTRA_WEIGHT_RE = re.compile(r'\b\d+(?:\.\d+)?\s*(?::|x)\s*', re.IGNORECASE)
_ST_EXTRA_DENY = (
    # appearance/identity override + NSFW — an invite-link holder must not be
    # able to re-describe a character (finding #59).
    'nude',
    'naked',
    'nsfw',
    'topless',
    'undress',
    'lingerie',
    'bikini',
    'underwear',
    'erotic',
    'sexy',
    'sexual',
    'porn',
    'fetish',
    'breast',
    'nipple',
    'genital',
    'buttock',
    'cleavage',
    'seductive',
    'provocative',
    'loli',
    'shota',
    'petite girl',
    'petite boy',
    'ignore previous',
    'disregard',
    'instead of',
    'override',
)


def _st_sanitize_extra_prompt(raw: str, *, minor: bool = False) -> tuple[str, list]:
    """2026-07-31: sanitise the PUBLIC, unvalidated extra_prompt (finding #59).

    It used to be appended verbatim to the tail of every scene prompt — the
    highest-weight position for the text encoder, AFTER the identity and quality
    clauses — so any invite-link holder could re-describe any character.
    Returns (clean_text, notes). Notes are logged into debug_events so an
    operator can audit exactly what a public user injected."""
    notes: list = []
    _txt = str(raw or '').strip()
    if not _txt:
        return '', notes
    if minor:
        return '', ['dropped entirely — resolved bible identity is a minor']
    _cap = int(os.environ.get('ZYG_ST_EXTRA_PROMPT_MAX', '200'))
    _stripped = _ST_EXTRA_WEIGHT_RE.sub(' ', _txt)
    _stripped = _ST_EXTRA_STRIP_RE.sub(' ', _stripped)
    _stripped = re.sub(r'\s{2,}', ' ', _stripped).strip(' ,.-')
    if _stripped != _txt:
        notes.append('stripped prompt-control punctuation / attention weights')
    _low = _stripped.lower()
    _hits = [w for w in _ST_EXTRA_DENY if w in _low]
    if _hits:
        return '', [f'rejected — blocked term(s) {_hits}']
    if len(_stripped) > _cap:
        _cut = _stripped[:_cap]
        _sp = _cut.rfind(' ')
        _stripped = (_cut[:_sp] if _sp > _cap // 2 else _cut).strip(' ,')
        notes.append(f'truncated to {_cap} chars')
    return _stripped, notes


def _run_storyteller_pipeline(pipeline_id: str):
    """
    Storyteller pipeline: character LoRA + Claude story script → FLUX images →
    Azure TTS narration → Ken Burns animation → ffmpeg assembly.

    Stages:
      1. Character Prep   — verify character dataset; resolve LoRA / IPAdapter
      2. Story Script     — Claude writes scene-by-scene narrative for the character
      3. TTS Narration    — IndexTTS-2 → per-scene audio (Whisper word timestamps)
      3.5 Image Gen       — FLUX (LoRA trigger + IPAdapter) → one image per scene
      4. Ken Burns        — PIL pan/zoom animation per image slot
      5. Final Assembly   — ffmpeg concat + subtitles + colour grade
    """
    import subprocess as _sp_st

    job = _workflow_jobs.get(pipeline_id)
    if not job:
        return

    # 2026-07-25: storyteller writes to its OWN output folder (output/storyteller/)
    # so the documentary auto-upload scanner (Creator Nexus, which polls
    # output/clips/) never picks up storyteller episodes and pushes them to the
    # documentary YouTube channel. Every workflow gets its own root.
    out_dir = os.path.join(os.path.dirname(_RUNTIME_DIR), 'output', 'storyteller', pipeline_id)
    os.makedirs(out_dir, exist_ok=True)
    job['output_dir'] = out_dir
    state_file = _runtime_path(f'storyteller_{pipeline_id}_state.json')

    char_id = job.get('char_id', '')
    character_params = job.get('character_params', {})
    voice_style = job.get('voice_style', 'narration')
    narrator_voice = job.get('narrator_voice', '')
    character_voice = job.get('character_voice', '')
    duration_min = float(job.get('clip_duration_minutes', 10.0))
    era_start = job.get('era_start')
    era_end = job.get('era_end')
    camera_mode = job.get('camera_mode', 'automatic')
    story_prompt = job.get('story_prompt', '')
    visual_style = job.get('visual_style', 'cinematic')
    narration_enabled = job.get('narration_enabled', True)
    model_family = job.get('model_family', 'flux')
    # 2026-07-25: SDXL ⟹ ANIMATED for a TWIN (marker sdxl_render_style=animated).
    # Gate the photoreal-QC skips on that marker, not mere SDXL family — legacy
    # photoreal SDXL-primary chars (Aria/Nia) have no marker and must keep their
    # ArcFace/hand/sharpness gates.
    _animated_render = False
    if str(model_family).strip().lower() == 'sdxl' and os.environ.get('ZYG_SDXL_ANIMATED', '1').strip().lower() not in (
        '0',
        'false',
        'no',
    ):
        try:
            from zyg_workflows import character_bible_service as _cbs_anim0

            _cond_anim0 = (_cbs_anim0.load(char_id) or {}).get('conditioning') or {}
            _animated_render = str(_cond_anim0.get('sdxl_render_style') or '').strip().lower() == 'animated'
        except Exception:
            _animated_render = False

    # 2026-07-27: RESTYLE (Arcane) episode render — parallel to _animated_render but
    # DISTINCT: renders Juggernaut + the baked arcane LoRA (checkpoint lives in comfy),
    # KEEPS identity QC via the style-agnostic VLM skin/hair gate (not ArcFace vs the
    # photoreal master), uses the arcane caption prefix, and relaxes the photoreal
    # scene/hand/FaceDetailer/drift gates. Gated on style_profile.restyle resolving —
    # an explicit per-char opt-in, so NOT behind ZYG_SDXL_ANIMATED.
    _restyle_render = False
    _restyle_caption_prefix = ''
    if str(model_family).strip().lower() == 'sdxl':
        try:
            from zyg_workflows import character_bible_service as _cbs_rs0
            from zyg_workflows import arcane_restyle as _ar_rs0

            _rs_name0 = ((_cbs_rs0.load(char_id) or {}).get('style_profile') or {}).get('restyle')
            if _rs_name0:
                _rp0 = _ar_rs0.load_profile(str(_rs_name0))
                if _rp0 and _rp0.get('restyle'):
                    _restyle_render = True
                    _cc0 = ((_rp0.get('restyle') or {}).get('caption_clause') or '').strip().rstrip(',')
                    if _cc0:
                        _restyle_caption_prefix = _cc0 + ', '
        except Exception:
            _restyle_render = False

    # Era string for Claude/FLUX prompts
    if era_start and era_end and era_start != era_end:
        era_str = f'{era_start}–{era_end}'
    elif era_start:
        era_str = str(era_start)
    else:
        era_str = 'modern day'

    import re as _re_slug_st

    _raw_slug_st = (story_prompt or 'story').lower()
    _slug_st = _re_slug_st.sub(r'[^a-z0-9]+', '_', _raw_slug_st).strip('_')[:40].rstrip('_') or 'story'

    pipeline_state = {
        'pipeline_id': pipeline_id,
        'department': 'storyteller',
        'char_id': char_id,
        'model_family': model_family,
        'era': era_str,
        'duration_min': duration_min,
        'story_prompt': story_prompt,
        'started': _ams_iso(),
        'script': [],
        'tts_path': '',
        'tts_duration': 0,
        'flux_images': [],
        'video_path': '',
        'output_dir': out_dir,
    }

    _pipeline_marker = _register_marker(
        f'🎭 Storyteller Pipeline {pipeline_id[:8]} — {story_prompt[:40]} — starting',
        pipeline_id=pipeline_id,
        status='pipeline',
    )
    threading.Thread(
        target=_hw_monitor_loop, args=(pipeline_id,), daemon=True, name=f'hw-monitor-{pipeline_id[:8]}'
    ).start()

    def _save():
        try:
            pipeline_state['debug_events'] = job.get('debug_events', [])
            with open(state_file, 'w') as _f:
                json.dump(pipeline_state, _f, indent=2)
        except Exception as _exc:
            _zyg_log.warning('pipeline state file write failed, the live view will lag: %s', _exc)

    def _log(level, stage, msg):
        # Store full UTC ISO timestamp so live tail / analysis tools can parse
        # consistently across pipelines and convert to local time in the browser.
        _ts_utc = _ams_iso()
        entry = {'ts': _ts_utc, 'level': level, 'stage': stage, 'msg': msg}
        job.setdefault('debug_events', []).append(entry)
        # Cap debug_events list size so long pipelines don't bloat memory
        if len(job['debug_events']) > 1000:
            job['debug_events'] = job['debug_events'][-700:]
        # Forward to error log (kanban Errors panel) for WARN/ERROR
        try:
            if str(level).upper() in ('WARN', 'WARNING', 'ERROR', 'CRITICAL'):
                _push_error_log(level, stage, msg, job.get('pipeline_id', ''))
        except Exception as _exc:
            _zyg_log.debug('error-log forward to the kanban panel skipped: %s', _exc)
        _zyg_log.info(f'[STORYTELLER|{level}|{stage}] {msg}')
        _save()

    def _check_stop():
        from zyg_workflows import pipeline_control as _pc_st

        if (
            gui_state._pipeline_stop_flag
            or _pc_st.halt_requested()
            or job.get('stop_event', threading.Event()).is_set()
        ):
            raise RuntimeError('Pipeline stopped by user')

    def _update_stage(stage: str, pct: int = None):
        job['current_stage'] = stage
        if pct is not None:
            job['progress_pct'] = pct
        # Maintain stage_timeline so Kanban board can resolve card statuses.
        # Timestamped since 2026-08-26: the rows used to carry name + status
        # only, so the Kanban card dialog had nothing to date its Started and
        # Duration rows with and reported "0s ago / 0s" for every card.
        _tl_now = _ams_iso()
        tl = job.setdefault('stage_timeline', [])
        for entry in tl:
            if entry.get('status') == 'running':
                entry['status'] = 'completed'
                if not entry.get('ended_at'):
                    entry['ended_at'] = _tl_now
        existing = next((e for e in tl if e.get('name') == stage), None)
        if existing:
            existing['status'] = 'running'
            existing['ended_at'] = None
            if not existing.get('started_at'):
                existing['started_at'] = _tl_now
        else:
            tl.append({'name': stage, 'status': 'running', 'started_at': _tl_now, 'ended_at': None})
        _log('INFO', stage, f'▶ {stage}')

    # The stage modules import helpers out of THIS module at module level, so
    # this import has to stay inside the function — see storyteller/__init__.py.
    from zyg_workflows.storyteller.context import StorytellerContext
    from zyg_workflows.storyteller.stage_01_character_prep import stage_01_character_prep
    from zyg_workflows.storyteller.stage_02b_render_prompts import stage_02b_render_prompts
    from zyg_workflows.storyteller.stage_035_image_gen import stage_035_image_generation
    from zyg_workflows.storyteller.stage_05b_subtitles import stage_05b_burn_subtitles
    from zyg_workflows.storyteller.stages_02_story_script import stage_02_scene_budget, stage_02a_sonnet_story
    from zyg_workflows.storyteller.stages_03_05_tts_assembly import (
        stage_03_tts,
        stage_04_ken_burns,
        stage_05_final_assembly,
    )

    ctx = StorytellerContext(
        pipeline_id=pipeline_id,
        job=job,
        pipeline_state=pipeline_state,
        out_dir=out_dir,
        char_id=char_id,
        character_params=character_params,
        voice_style=voice_style,
        narrator_voice=narrator_voice,
        character_voice=character_voice,
        duration_min=duration_min,
        camera_mode=camera_mode,
        story_prompt=story_prompt,
        visual_style=visual_style,
        narration_enabled=narration_enabled,
        model_family=model_family,
        era_str=era_str,
        _slug_st=_slug_st,
        _pipeline_marker=_pipeline_marker,
        _sp_st=_sp_st,
        _animated_render=_animated_render,
        _restyle_render=_restyle_render,
        _restyle_caption_prefix=_restyle_caption_prefix,
        _save=_save,
        _log=_log,
        _check_stop=_check_stop,
        _update_stage=_update_stage,
    )

    try:
        stage_01_character_prep(ctx)
        stage_02_scene_budget(ctx)
        stage_02a_sonnet_story(ctx)
        stage_02b_render_prompts(ctx)
        stage_03_tts(ctx)
        stage_035_image_generation(ctx)
        stage_04_ken_burns(ctx)
        stage_05_final_assembly(ctx)
        stage_05b_burn_subtitles(ctx)

    except Exception as exc:
        _log('ERROR', 'PIPELINE', f'Storyteller pipeline error: {exc}')
        job['status'] = 'failed'
        job['error'] = str(exc)
        job['current_stage'] = f'Failed: {str(exc)[:120]}'
        try:
            _update_marker(_pipeline_marker, status='error', label=str(exc)[:200])
        except Exception as _exc:
            _zyg_log.warning('pipeline marker not set to error, the job may still read as running: %s', _exc)
        _save()

    finally:
        _release_pipeline_vram('post-pipeline', lambda m: _log('INFO', 'Cleanup', m))
