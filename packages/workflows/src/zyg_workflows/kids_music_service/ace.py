# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The ACE-Step leg: availability, prompt, negative prompt and the render itself.

Moved verbatim out of the old single-file kids_music_service.py (lines 620-1026, 1376-1395).
"""

from __future__ import annotations

import json
import os
from zyg_workflows import paths
from zyg_workflows import kids_music_theory as T

from zyg_workflows.kids_music_service.base import (
    A2A_DENOISE,
    ACE_CHECKPOINT,
    ACE_NEG_NODE,
    ACE_STEPS,
    ACE_WORKFLOW,
    ACE_WORKFLOW_A2A,
    ACE_WORKFLOW_COVER,
    ACE_WORKFLOW_NEG,
    _ff,
    _log_noop,
    _zyg_log,
)

# ── ACE-Step leg ─────────────────────────────────────────────────────────────


def ace_available():
    """Is the ACE-Step leg runnable right now?

    `_comfy_client.is_enabled()` reads ZYG_USE_COMFYUI, which nothing sets in the
    shell — the GUI process gets it from `vram_manager._ensure_comfy_offload_env`,
    which defaults it ONLY when the server actually answers. Calling that same
    helper is what makes a standalone run (CLI, or a worker thread that has not
    imported vram_manager yet) see the same ComfyUI the dashboard sees, instead
    of reporting 'unavailable' beside a perfectly healthy server.
    """
    if not os.path.isfile(os.path.join(str(paths.ZYG_COMFY_ROOT / 'models' / 'checkpoints'), ACE_CHECKPOINT)):
        return False
    try:
        from zyg_workflows import vram_manager as _vm

        _vm._ensure_comfy_offload_env()
    except Exception as _exc:  # noqa: BLE001 — optional convenience
        _zyg_log.debug('comfy offload env setup skipped: %s', _exc)
    try:
        from zyg_workflows import _comfy_client as _cc

        return _cc.is_enabled() and _cc.server_reachable()
    except Exception:  # noqa: BLE001
        return False


def _family_of(plan_or_brief):
    """Which style family this plan (or brief) was composed under.

    'children' when nothing says otherwise, so every pre-family record — every
    manifest, every stored plan, every hand-built brief — resolves to the
    behaviour it already had.
    """
    d = plan_or_brief or {}
    return str(d.get('family') or (d.get('brief') or {}).get('family') or 'children')


def ace_prompt(plan):
    """ACE-Step tag string for this plan.

    Built from the plan, not from the user's sentence: the model is told the same
    tempo, metre and key the score already fixed. The theme rides along as
    flavour, never as the whole prompt.

    THE SINGER CLAUSE COMES FIRST, straight after the genre. It is the only
    lever that moves the voice, and its position in the tag list matters: the
    caption is read as a weighted bag and a vocal instruction buried behind eight
    production adjectives steers less than one at the front.

    The audience clause is GONE. "for toddler children" was rendering literally
    into the caption of a song that is sung by an adult, and it was doing no
    work the plan does not already do symbolically — the age band constrains
    range, leap, density and syllable count during composition and is recorded
    in the manifest. "children's music" stays: that is the GENRE, not the singer.
    """
    b = plan['brief']
    mood = T.MOODS[b['mood']]
    # A style names the instruments the score is actually PLAYED on, so its tag
    # string is the truthful caption — the mood's generic tags would describe a
    # different arrangement from the one ACE-Step is conditioned on. Without a
    # style nothing changes.
    S = T.style_for_plan(plan)
    if _family_of(plan) == 'cinematic':
        # A different GENRE, not a children's song with the singer removed.
        # "children's music" at the head of the caption is the single strongest
        # token in the bag and it drags an orchestral cue towards nursery
        # instrumentation; and "simple singable melody" asks for the one thing a
        # cue is not. The theme rides along only when the operator actually
        # named one — the composer's placeholder is not a subject.
        bits = [
            'cinematic instrumental score',
            'instrumental, no vocals',
            S['ace_tags'] if S else mood['tags'],
            f'{plan["bpm"]} bpm',
            f'{plan["meter"]} time',
            plan['key']['label'],
            'clean mix',
            'no distortion',
        ]
        theme = str(b.get('theme') or '').strip()
        if theme and theme != T.DEFAULT_THEME:
            bits.append(f'about {theme}')
    else:
        bits = ["children's music"]
        if b.get('sung'):
            singer = T.SINGERS.get(b.get('singer') or T.DEFAULT_SINGER, T.SINGERS[T.DEFAULT_SINGER])
            bits.append(singer['caption'])
            bits.append('easy words, clear diction')
        else:
            bits.append('instrumental, no vocals')
        bits += [
            S['ace_tags'] if S else mood['tags'],
            f'{plan["bpm"]} bpm',
            f'{plan["meter"]} time',
            plan['key']['label'],
            'simple singable melody',
            'clean mix',
            'no distortion',
        ]
        if b.get('theme'):
            bits.append(f'about {b["theme"]}')
    # Some mood tag strings already carry a phrase this function adds ("simple
    # singable melody" is in the `happy` tags), and a caption that says the same
    # thing twice spends weight on it twice.
    seen, out = set(), []
    for bit in ', '.join(bits).split(', '):
        k = bit.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(bit.strip())
    return ', '.join(out)[:900]


def ace_negative(plan):
    """The caption_negative for a sung plan — empty for an instrumental.

    Second line of defence only. The KSampler negative branch in the graph is
    INERT (it runs at cfg 1.0, where ComfyUI skips the uncond pass entirely, and
    the turbo DiT is guidance-distilled), and raising that cfg is not the answer:
    measured, cfg 2 and 4 still render but crest factor drops 1.5 and 2.4 dB.
    The slot that carries real CFG is the audio-code LM's text_negative, which
    defaults to the positive caption because the stock text encoder never
    forwards one. The custom node in _comfy_nodes fills it.

    A cinematic cue is the one instrumental that gets a negative anyway: it is
    the family's whole contract that no voice appears, and 'instrumental, no
    vocals' in the positive caption is a weaker statement than naming the thing
    to keep out.
    """
    if _family_of(plan) == 'cinematic':
        return 'vocals, singing, lyrics, children singing'
    return T.SINGER_NEGATIVE if plan['brief'].get('sung') else ''


def _attest(wf, log_fn=None, run_id='', tag=''):
    """Classify every weight this graph references, through the existing gate.

    licence_provenance.attest_licences() already exists, already passes this
    graph by hand, and was CALLED FROM NOWHERE. On a monetised channel an
    unchecked graph is the whole point of having the check.
    """
    try:
        from zyg_workflows import licence_provenance as _lp

        return _lp.attest_licences(wf, log_fn=log_fn, run_id=run_id, tag=tag)
    except Exception as e:  # noqa: BLE001
        return {
            'ok': None,
            'error': f'{type(e).__name__}: {e}'[:200],
            'artifacts': [],
            'violations': [],
            'unknowns': [],
        }


def ace_render(
    plan,
    out_path,
    *,
    seed=None,
    timeout_s=None,
    log_fn=None,
    should_abort=None,
    info=None,
    melody_wav=None,
    cover_wav=None,
    lm_seed=None,
    denoise=None,
):
    """Generate the ACE-Step variation through ComfyUI's native ACE-Step 1.5 nodes.

    Uses its OWN workflow template so ace_step_service.py and ace_step_bgm.json —
    which the documentary and storyteller beds depend on — are untouched. The
    difference that matters is that this one passes lyrics, bpm, keyscale and
    time signature through instead of hard-coding an instrumental bed.

    Three modes, in precedence order:
      cover_wav   ReferenceTimbreAudio — ACE-Step's cover task. The reference is
                  tokenised into the semantic codes the DiT uses as its source
                  context, so the melody, rhythm and chords of the reference are
                  re-performed. Wins over melody_wav when both are given.
      melody_wav  a2a — the sampler starts from the score render's latent at
                  denoise A2A_DENOISE. Texture and timing only.
      neither     text-to-music; the LM invents the audio codes.

    `lm_seed`, when given, seeds the TEXT ENCODER node separately from the
    sampler (which keeps `seed`). A ComfyUI latent batch shares one LM plan and
    only sampler noise differs across it, so holding one seed while varying the
    other is what attributes register variance to the LM or to diffusion.

    `info` (optional dict) receives what actually ran: the resolved caption, the
    negative, the checkpoint basename, the seed, the workflow name and the
    licence attestation. None of that used to be recorded anywhere, so no shipped
    song could be audited — and ACE_CHECKPOINT is env-overridable, so the
    manifest has to name the file that ran rather than a constant.
    """
    log_fn = log_fn or _log_noop
    rec = info if isinstance(info, dict) else {}
    abort = should_abort or (lambda: False)
    den = A2A_DENOISE if denoise is None else float(denoise)
    rec.update({'ran': False, 'reason': '', 'checkpoint': ACE_CHECKPOINT})
    if abort():
        rec['reason'] = 'halt requested before submit'
        log_fn('ace: skipped (halt requested)')
        return None
    if not ace_available():
        rec['reason'] = 'ComfyUI down or checkpoint missing'
        log_fn(f'ace: unavailable ({rec["reason"]})')
        return None
    import random as _rnd
    import shutil
    from zyg_workflows import _comfy_client as _cc

    if seed is None:
        seed = _rnd.randint(0, 2**31 - 1)
    seconds = max(10.0, min(float(os.environ.get('ZYG_ACE_MAX_SECONDS', '210')), float(plan['seconds'])))
    lyrics = plan.get('lyrics_block') or '[inst]'
    tags = ace_prompt(plan)
    neg = ace_negative(plan)
    # The negative-capable graph is used when the crews node is installed;
    # otherwise the original graph runs unchanged and the negative is recorded as
    # unavailable rather than silently dropped.
    wf_name = ACE_WORKFLOW
    node2 = {
        'tags': tags,
        'lyrics': lyrics,
        'seed': seed,
        'bpm': int(plan['bpm']),
        'duration': seconds,
        'timesignature': str(plan['ts']),
        'keyscale': plan['key']['ace_keyscale'],
    }
    if lm_seed is not None:
        node2['seed'] = int(lm_seed)
    extra = {}
    mode = 'text'
    if cover_wav and os.path.isfile(cover_wav):
        if melody_wav:
            log_fn('ace: cover_wav given — it wins over melody_wav')
        # A separate stem so the cover source cannot land on the melody
        # staging's filename: both can be staged in one process.
        staged = _stage_comfy_audio(cover_wav, log_fn=log_fn, stem='src')
        if staged:
            wf_name = ACE_WORKFLOW_COVER
            extra = {'8': {'audio': staged}}
            node2['generate_audio_codes'] = False
            neg = ''
            mode = 'cover'
            rec['cover_source'] = os.path.basename(cover_wav)
            log_fn(f'ace: COVER mode on {os.path.basename(cover_wav)} (reference re-performed, LM audio codes off)')
        else:
            log_fn('ace: could not stage the cover source — falling back')
    if not extra and melody_wav and os.path.isfile(melody_wav):
        # Melody conditioning wins over the negative graph: they are separate
        # workflow files and only one can run. The negative is a second line of
        # defence; following the composed tune is the whole point of the leg.
        staged = _stage_comfy_audio(melody_wav, log_fn=log_fn)
        if staged:
            wf_name = ACE_WORKFLOW_A2A
            extra = {'8': {'audio': staged}, '5': {'denoise': den}}
            neg = ''
            mode = 'a2a'
            log_fn(f'ace: melody conditioning ON (denoise {den:g})')
        else:
            log_fn('ace: could not stage the melody — falling back to noise')
    if not extra and neg and _negative_node_available():
        wf_name = ACE_WORKFLOW_NEG
        node2['caption_negative'] = neg
    elif not extra and neg:
        log_fn('ace: caption-negative node not installed — positive caption only')
        neg = ''
    rec.update(
        {
            'workflow': wf_name,
            'ace_tags': tags,
            'caption_negative': neg,
            'mode': mode,
            'melody_conditioned': mode == 'a2a',
            'a2a_denoise': den if mode == 'a2a' else None,
            'steps': ACE_STEPS or None,
            'seed': seed,
            'lm_seed': int(lm_seed) if lm_seed is not None else None,
            'seconds': round(seconds, 2),
            'lyrics_head': (lyrics or '').strip().splitlines()[:4],
            'bpm': int(plan['bpm']),
            'keyscale': plan['key']['ace_keyscale'],
            'timesignature': str(plan['ts']),
        }
    )
    log_fn(f'ace: {seconds:.0f}s @ {plan["bpm"]}bpm {plan["key"]["ace_keyscale"]} ts={plan["ts"]} seed={seed}')
    try:
        wf = _cc.load_workflow(wf_name)
        overrides = {'1': {'ckpt_name': ACE_CHECKPOINT}, '2': node2, '4': {'seconds': seconds}, '5': {'seed': seed}}
        if ACE_STEPS:
            overrides['5']['steps'] = ACE_STEPS
        for nid, vals in extra.items():
            overrides.setdefault(nid, {}).update(vals)
        # Only override nodes this graph actually has. The melody-conditioned
        # workflow has no EmptyAceStep1.5LatentAudio — its latent comes from
        # VAEEncodeAudio — so sending node 4 to it is an error, not a no-op.
        overrides = {k: v for k, v in overrides.items() if k in wf}
        # Attest the graph AS SUBMITTED, so the checkpoint override is what gets
        # classified rather than the template's placeholder.
        graph = json.loads(json.dumps(wf))
        for nid, vals in overrides.items():
            if nid in graph:
                graph[nid].setdefault('inputs', {}).update(vals)
        att = _attest(graph, log_fn=log_fn, tag='kidsmusic')
        rec['licence_attestation'] = {
            'ok': att.get('ok'),
            'violations': [a.get('name') for a in (att.get('violations') or [])],
            'unknowns': [a.get('name') for a in (att.get('unknowns') or [])],
            'error': att.get('error', ''),
        }
        if att.get('ok') is False:
            rec['reason'] = 'licence attestation FAILED: ' + ', '.join(rec['licence_attestation']['violations'])
            log_fn(f'ace: {rec["reason"]} — leg refused')
            return None  # fail CLOSED on a real violation
        if att.get('ok') is None:
            log_fn(
                'ace: licence attestation returned UNKNOWN — '
                f'{rec["licence_attestation"]["unknowns"] or att.get("error")}'
            )
        outputs = _cc.submit(
            wf,
            overrides=overrides,
            timeout_s=float(timeout_s or os.environ.get('ZYG_ACE_TIMEOUT_S', '900')),
            **_submit_abort_kw(should_abort),
        )
        # Time spent queued behind ANOTHER client's job is not this render's
        # cost; the voice leg's budgets subtract it (see repair_take).
        rec['lock_wait_s'] = float((getattr(_cc, 'last_submit_timing', {}) or {}).get('lock_wait_s') or 0.0)
    except Exception as e:  # noqa: BLE001 — a dead render must
        rec['reason'] = f'{type(e).__name__}: {e}'[:200]
        log_fn(f'ace: generation failed — {rec["reason"]}')
        return None  # not take the whole song down

    mp3s = [p for p in outputs if p.lower().endswith(('.mp3', '.flac', '.wav')) and os.path.isfile(p)]
    if not mp3s:
        rec['reason'] = 'job completed but produced no audio'
        log_fn(f'ace: {rec["reason"]}')
        return None
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    shutil.copy2(mp3s[0], out_path)
    try:
        os.remove(mp3s[0])
    except OSError as _exc:
        _zyg_log.debug('intermediate mp3 %s removal skipped: %s', mp3s[0], _exc)
    if os.path.getsize(out_path) < 10_000:
        rec['reason'] = 'output too small to be audio'
        log_fn(f'ace: {rec["reason"]}')
        return None
    rec['ran'] = True
    log_fn(f'ace: ✅ {os.path.basename(out_path)} ({os.path.getsize(out_path) // 1024} KB)')
    return out_path


def _stage_comfy_audio(wav, log_fn=None, stem='melody'):
    """Copy a wav into ComfyUI's input dir so LoadAudio can see it.

    `_comfy_client` has stage_input_image but no audio sibling; this is the
    audio one, kept local rather than added to the shared client so nothing
    else changes shape.
    """
    log_fn = log_fn or _log_noop
    try:
        base = str(paths.ZYG_COMFY_INPUT)
        if not os.path.isdir(base):
            return ''
        name = f'kidsmusic_{stem}_{os.getpid()}.wav'
        dst = os.path.join(base, name)
        if _ff(['-i', wav, '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', dst], log_fn=log_fn):
            return name
    except Exception as e:  # noqa: BLE001
        log_fn(f'ace: staging failed ({type(e).__name__})')
    return ''


def _negative_node_available():
    """Is the crews caption-negative node loaded on the live ComfyUI?"""
    if os.environ.get('ZYG_KIDSMUSIC_NEG', '1').strip() in ('0', 'false', 'no'):
        return False
    try:
        from zyg_workflows import _comfy_client as _cc

        for fn in ('object_info', 'has_node', 'node_types'):
            f = getattr(_cc, fn, None)
            if callable(f):
                r = f() if fn != 'has_node' else f(ACE_NEG_NODE)
                if isinstance(r, bool):
                    return r
                if isinstance(r, dict):
                    return ACE_NEG_NODE in r
                if isinstance(r, (list, set, tuple)):
                    return ACE_NEG_NODE in r
        from zyg_workflows.net import safe_urlopen as _safe_urlopen

        base = os.environ.get('ZYG_COMFYUI_URL', paths.ZYG_COMFY_URL).rstrip('/')
        with _safe_urlopen(f'{base}/object_info/{ACE_NEG_NODE}', timeout=5) as r:
            return ACE_NEG_NODE in json.loads(r.read().decode('utf-8') or '{}')
    except Exception:  # noqa: BLE001 — absent means absent
        return False


def _submit_abort_kw(should_abort):
    """Pass should_abort to _comfy_client.submit only if it accepts one.

    The stop button used to reach the dispatcher and stop there, while an
    in-flight ACE render carried on to completion. Feature-detected rather than
    assumed so this cannot break on a client that has no such parameter.
    """
    if should_abort is None:
        return {}
    try:
        import inspect
        from zyg_workflows import _comfy_client as _cc

        params = inspect.signature(_cc.submit).parameters
        for name in ('should_abort', 'abort', 'cancel_cb', 'stop_check'):
            if name in params:
                return {name: should_abort}
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('abort-callback kwarg probe failed, submitting without one: %s', _exc)
    return {}
