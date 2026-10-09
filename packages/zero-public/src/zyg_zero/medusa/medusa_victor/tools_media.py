# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_victor.tools_media — the picture, character-sheet and video tools, with the sheet consent gate.

Lines 517-989 of the original medusa_victor.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import re
import time

from .constants import IMAGE_APPROVAL, STILLS_DEFAULT_FAMILY, STILLS_WAIT

from .backends import _TURN, _crews, _record_image, _stills

from zyg_zero import paths as _zero_paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_zero.medusa.medusa_victor')


# ── one picture from one prompt (:8899) ──────────────────────────────────────
def _still_dim(v, default: int) -> int:
    """Snap a requested size to what the still service will accept: 512..1536 and
    a multiple of 16. A model that asks for 1024x1024 or 1920x1080 means a size,
    not a rejection — the endpoint answers 400 on anything else, and a 400 here
    costs the operator their picture."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = default
    n = max(512, min(1536, n))
    return n - (n % 16)


def _t_picture_generate(
    prompt: str,
    negative: str = '',
    width: int = 1280,
    height: int = 720,
    seed: int = 0,
    family: str = '',
    label: str = '',
    wait: bool = True,
) -> dict:
    """Render ONE picture from a text prompt and wait for it.

    This is what "generate a picture/image of X" means in a chat: one prompt,
    one PNG, back in the conversation. It is a different service from the
    character generator and has no angles, no character fields and no approval
    queue — see STILLS_API.

    Returns the finished file's path, and hands that path to the panel so the
    picture itself appears in the chat (see _record_image). With wait=False it
    returns the job id instead and picture_status polls it.
    """
    prompt = str(prompt or '').strip()
    if not prompt:
        return {'ok': False, 'error': 'prompt is required — say what the picture should show'}
    fam = str(family or STILLS_DEFAULT_FAMILY).strip().lower()
    if fam not in ('qwen', 'klein'):
        return {'ok': False, 'error': "family must be 'qwen' or 'klein' (FLUX is paused here)"}
    body = {
        'prompt': prompt[:2000],
        'negative': str(negative or ''),
        'width': _still_dim(width, 1280),
        'height': _still_dim(height, 720),
        'seed': int(seed or 0),
        'family': fam,
        'label': str(label or ''),
        # This IS Medusa-app content: attaches the active Medusa base LoRA
        # for this family and applies the adults-only prompt floor.
        'medusa': True,
    }
    res = _stills('POST', '/video/api/still', body)
    if not res.get('ok'):
        return {'ok': False, 'error': res.get('error'), 'note': 'Nothing is rendering. Report this as it stands.'}
    job = (res.get('data') or {}).get('job') or {}
    jid = str(job.get('id') or '')
    if not jid:
        return {'ok': False, 'error': f'the still service returned no job id: {res.get("data")}'}
    out = {
        'ok': True,
        'job_id': jid,
        'prompt': prompt,
        'seed': job.get('seed'),
        'family': fam,
        'width': body['width'],
        'height': body['height'],
    }
    if not wait:
        out['state'] = job.get('state') or 'queued'
        out['note'] = 'Rendering. Poll it with picture_status(job_id).'
        return out

    deadline = time.time() + STILLS_WAIT
    st: dict = {}
    while time.time() < deadline:
        time.sleep(3)
        got = _stills('GET', f'/video/api/still?id={jid}')
        if not got.get('ok'):
            continue
        st = got.get('data') or {}
        if st.get('state') in ('done', 'error'):
            break
    state = str(st.get('state') or 'running')
    if state == 'done':
        path = str(st.get('path') or '')
        _record_image(path, os.path.basename(path), prompt)
        out.update(
            {
                'state': 'done',
                'path': path,
                'seconds': st.get('seconds'),
                'backend': st.get('backend'),
                'note': 'Rendered. The picture has already been put into the chat for the '
                'operator — say what it is, do not paste the path as if it were the '
                'picture.',
            }
        )
        return out
    if state == 'error':
        out.update(
            {
                'ok': False,
                'state': 'error',
                'error': st.get('error') or 'render failed',
                'note': 'No picture was produced. Say what the error said.',
            }
        )
        return out
    out.update(
        {
            'state': state,
            'note': f'Still rendering after {STILLS_WAIT}s — it is not lost. Poll picture_status("{jid}").',
        }
    )
    return out


def _t_picture_status(job_id: str) -> dict:
    """Where one picture_generate job got to. A finished one is put into the
    chat from here too, so a picture started with wait=False still arrives."""
    got = _stills('GET', f'/video/api/still?id={str(job_id or "").strip()}')
    if not got.get('ok'):
        return got
    st = got.get('data') or {}
    if st.get('state') == 'done' and st.get('path'):
        _record_image(str(st['path']), os.path.basename(str(st['path'])), str(st.get('prompt') or ''))
    return {
        'ok': True,
        'state': st.get('state'),
        'path': st.get('path'),
        'error': st.get('error'),
        'seconds': st.get('seconds'),
        'prompt': st.get('prompt'),
        'seed': st.get('seed'),
        'log': (st.get('log') or [])[-6:],
    }


# ── character generation (the crews :5000 API — the same endpoints Vicky curls) ──
# ── the character-sheet consent gate ────────────────────────────────────
# 2026-09-22. Twice now a chat asking for ONE picture has started a 48-angle
# sheet: 4d2295ba282c on 09-17 (stopped at 9/48) and 1f138fca1f56 today
# (stopped at 14/48 after ~1h51m). After the first one the rules file and both
# tool descriptions were rewritten to keep a picture and a sheet apart — and it
# happened again anyway, because the system prompt still closed that paragraph
# with "start them when the work calls for them rather than asking whether you
# should". A small model weighing a cautionary paragraph against a direct
# instruction takes the instruction. Prose lost twice; this is the loop-level
# fix, the same shape as the narration and refusal guards above.
#
# The operator's rule (2026-09-22): a picture request always means ONE picture,
# and a sheet is never started until they have said yes IN THE CHAT.
#
# Consent cannot be reported by the model — it would simply assert it, the way
# it asserts a picture it never rendered (_claims_picture). So it is a two-turn
# handshake decided from the transcript: the first call renders nothing and
# records the question, the assistant asks it, and only the operator's OWN next
# message can answer. Consent is consumed on use, so every sheet costs its own
# question — "always ask", not "ask once per chat".
_SHEET_ASK_DIR = str(_zero_paths.MEDUSA_DIR / 'data' / 'runtime' / 'vicky')
# An unanswered question goes stale instead of sitting there for ever: a yes has
# to belong to the question actually asked, not to one from yesterday.
_SHEET_ASK_TTL_S = 3600.0

# A yes, and nothing looser. The match is anchored at the start of the message
# so it reads an ANSWER ("yes", "go ahead", "do it") and not a yes buried in a
# fresh request ("yes I know, now make me a picture of X").
_SHEET_YES = re.compile(
    r'^\W*(?:yes|yep|yeah|yup|ok|okay|sure|go ahead|go|do it|start(?: it)?|'
    r'proceed|confirm(?:ed)?|approved?|permission granted|'
    r'(?:make|build|generate|render)(?: the| a| the full)? sheet|full sheet|the sheet)\b',
    re.IGNORECASE,
)
# Checked first, and deliberately allowed anywhere in the message: "yes but just
# one picture" is a no to the sheet.
_SHEET_NO = re.compile(
    r"\b(?:no|nope|don'?t|do not|stop|cancel|never|instead|"
    r'just one|only one|one picture|single picture|a picture)\b',
    re.IGNORECASE,
)


def _sheet_ask_path() -> str:
    cid = str(getattr(_TURN, 'chat_id', '') or 'nochat')
    safe = re.sub(r'[^A-Za-z0-9_-]', '', cid)[:64] or 'nochat'
    return os.path.join(_SHEET_ASK_DIR, f'sheet_ask_{safe}.json')


def _sheet_consent() -> tuple[bool, str]:
    """(granted, why) for THIS turn, from the operator's own last message.

    False whenever anything is unclear — an unreadable file, a stale question, a
    message that is a new request rather than an answer. The cost of a false no
    is one more question; the cost of a false yes is hours of GPU.
    """
    try:
        with open(_sheet_ask_path(), 'r', encoding='utf-8') as fh:
            ask = json.load(fh)
    except Exception:
        return False, 'no sheet question has been put to the operator in this chat yet'
    if time.time() - float(ask.get('ts') or 0) > _SHEET_ASK_TTL_S:
        return False, 'the last sheet question is over an hour old — ask again'
    said = str(getattr(_TURN, 'user_text', '') or '').strip()
    if not said:
        return False, 'the operator has not answered the sheet question yet'
    if _SHEET_NO.search(said):
        return False, f'the operator said {said[:60]!r} — that is not a yes'
    if _SHEET_YES.match(said):
        return True, f'the operator answered {said[:60]!r}'
    return False, (
        f'the operator has not said yes — their message was {said[:60]!r}, '
        'which reads as a new request, not an answer to the sheet question'
    )


def _sheet_record_ask(body: dict) -> None:
    """Park the question so the operator's next message can answer it."""
    try:
        os.makedirs(_SHEET_ASK_DIR, exist_ok=True)
        with open(_sheet_ask_path(), 'w', encoding='utf-8') as fh:
            json.dump({'ts': time.time(), 'body': body}, fh)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _sheet_clear_ask() -> None:
    """One question, one sheet — consent never carries to the next request."""
    try:
        os.remove(_sheet_ask_path())
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _t_image_generate(
    name: str = '',
    age: str = '',
    hair_color: str = '',
    eye_color: str = '',
    skin_tone: str = '',
    ethnic_heritage: str = '',
    char_prompt: str = '',
    angle_ids: list | None = None,
) -> dict:
    """POST /api/medusa/generate, then approve it — one tool call, the render is
    running when this returns.

    The endpoint itself only ever parks a request (see IMAGE_APPROVAL): it
    answers 202 with a `pending_id` and starts nothing. Asking the operator to go
    and click Approve on something they just asked for is the thing that was
    wrong, so the second call lives here instead. Set ZYG_MEDUSA_APPROVAL=on to
    park it and stop, as it used to.

    The approve is a separate HTTP call, so it can fail on its own. When it does,
    the request is still safely parked and the note says so — never report a
    render as started unless `started` is true."""
    body = {
        k: v
        for k, v in (
            ('name', name),
            ('age', age),
            ('hair_color', hair_color),
            ('eye_color', eye_color),
            ('skin_tone', skin_tone),
            ('ethnic_heritage', ethnic_heritage),
            ('char_prompt', char_prompt),
        )
        if str(v or '').strip()
    }

    # ASK FIRST — see the consent gate above. This runs before the angle lookup
    # and before any HTTP call, so a sheet nobody agreed to touches nothing.
    granted, why = _sheet_consent()
    if not granted:
        _sheet_record_ask(body)
        return {
            'ok': False,
            'started': False,
            'needs_permission': True,
            'error': 'a character sheet needs the operator to say yes in the chat first',
            'why': why,
            'note': (
                'ASK FIRST. NOTHING was submitted and no GPU is running. A character '
                'sheet is 48 camera angles and hours of GPU, so it is never started on '
                'your own reading of a request. Ask the operator now, in one plain '
                'sentence, whether they want the full character sheet, and tell them '
                'you will render a single picture otherwise. Then stop — do not call '
                'image_generate again this turn. If what they actually wanted was a '
                'picture, call picture_generate instead: one picture is the default '
                'and needs no permission.'
            ),
        }
    _sheet_clear_ask()

    if angle_ids:
        # Check the ids against the live catalog HERE. The endpoint does not
        # reject an unknown id: build_angle_selection resolves the list, gets
        # nothing, and quietly falls back to the full 48-angle sheet. Measured
        # 2026-09-17 — a request for one angle spent hours rendering all of them
        # because the id passed was 'cell_00', which is a contact-sheet cell name
        # and not an angle id (they look like a1, b3, e6).
        known = []
        cat = _crews('GET', '/api/medusa/angles')
        if cat.get('ok'):
            known = re.findall(r'"id"\s*:\s*"([^"]+)"', json.dumps(cat.get('data'), default=str))
        bad = [a for a in angle_ids if known and a not in known]
        if bad:
            return {
                'ok': False,
                'started': False,
                'error': f'not angle ids: {", ".join(map(str, bad))}',
                'known': known[:8] + (['...'] if len(known) > 8 else []),
                'note': 'Nothing was submitted. An unknown id would silently render the '
                'whole 48-angle sheet, so this stops instead. Call image_angles '
                'for the catalog.',
            }
        body['angle_set'] = 'custom'
        body['angle_ids'] = list(angle_ids)
    res = _crews('POST', '/api/medusa/generate', body)
    res['started'] = False

    if IMAGE_APPROVAL:
        res['note'] = (
            'Parked for operator approval — nothing renders until it is approved in '
            'Pending Approvals (image_pending / image_decide).'
        )
        return res

    pending_id = (res.get('data') or {}).get('pending_id') if res.get('ok') else None
    if not pending_id:
        res['note'] = (
            'The request was NOT accepted, so there is nothing to approve. '
            'Report this error as-is; do not claim a render started.'
        )
        return res

    ok = _crews('POST', f'/api/medusa/pending/{pending_id}/decide', {'action': 'allow'})
    res['approval'] = ok
    if ok.get('ok'):
        res['started'] = True
        res['note'] = (
            f'The operator agreed in the chat ({why}), so the sheet was submitted and '
            f'the render is RUNNING now. Poll it with image_jobs; a full 48-angle '
            f'sheet takes hours, a few angles far less. That yes is now spent — the '
            f'next sheet needs its own question.'
        )
    else:
        res['note'] = (
            f'Submitted but the auto-approve failed, so it is still parked as '
            f'{pending_id} and NOTHING is rendering. Say so, and offer to retry with '
            f'image_decide.'
        )
    return res


def _t_image_angles() -> dict:
    return _crews('GET', '/api/medusa/angles')


def _t_image_pending() -> dict:
    return _crews('GET', '/api/medusa/pending')


def _t_image_decide(pending_id: str, action: str) -> dict:
    action = str(action or '').strip().lower()
    if action not in ('allow', 'approve', 'decline', 'deny'):
        return {'ok': False, 'error': "action must be 'allow' or 'decline'"}
    return _crews('POST', f'/api/medusa/pending/{pending_id}/decide', {'action': action})


def _t_image_jobs() -> dict:
    return _crews('GET', '/api/medusa/jobs')


def _t_image_edit(
    char_id: str, cat: str, name: str, tool: str, scale: int = 2, prompt: str = '', scope: str = ''
) -> dict:
    """POST /api/internal/picture_studio/submit — upscale / inpaint / bg_remove.
    Returns a job; poll it with image_edit_status."""
    body = {'id': char_id, 'cat': cat, 'name': name, 'tool': tool, 'scope': scope}
    if tool == 'upscale':
        body['scale'] = max(2, min(4, int(scale or 2)))
    elif tool == 'inpaint':
        body['prompt'] = prompt
        return {
            'ok': False,
            'error': 'inpaint needs a mask_b64 that Victor cannot draw — '
            'ask the operator to run this one from the Picture Studio GUI',
        }
    return _crews('POST', '/api/internal/picture_studio/submit', body)


def _t_image_edit_status(job_id: str) -> dict:
    return _crews('GET', f'/api/internal/picture_studio/job/{job_id}')


def _t_image_capability() -> dict:
    return _crews('GET', '/api/internal/picture_studio/capability')


# ── video generation (Movement Studio on the same crews API) ────────────────
def _t_video_spec() -> dict:
    """GET /api/internal/movement/spec — every dial a render accepts, read live.
    Call this BEFORE video_render_start rather than guessing parameter names."""
    return _crews('GET', '/api/internal/movement/spec')


def _t_video_prompt(subject_type: str, subject_id: str, motion_prompt: str = '', params: dict | None = None) -> dict:
    """The exact sentence a render with these dials would submit — a dry run that
    renders nothing. The cheap way to check a prompt before a real job."""
    return _crews(
        'POST',
        '/api/internal/movement/prompt',
        {
            'subject_type': subject_type,
            'subject_id': subject_id,
            'motion_prompt': motion_prompt,
            'params': params or {},
        },
    )


def _t_video_render_start(
    subject_type: str,
    subject_id: str,
    motion_prompt: str,
    mode: str = 'probe',
    params: dict | None = None,
    subject_name: str = '',
) -> dict:
    """POST /api/internal/movement/start. Defaults to `probe` (33 frames, same
    dials) on purpose: a full render is long and the probe is the same recipe, so
    an unattended model should not be able to spend an hour on its first guess.
    Pass mode='full' only when the operator asked for the real thing."""
    mode = 'full' if str(mode).lower() == 'full' else 'probe'
    body = {
        'subject_type': subject_type,
        'subject_id': subject_id,
        'motion_prompt': motion_prompt,
        'mode': mode,
        'params': params or {},
    }
    if subject_name:
        body['subject_name'] = subject_name
    res = _crews('POST', '/api/internal/movement/start', body)
    if res.get('status') == 409:
        res['note'] = 'The render pipeline is already busy — do not retry in a loop; report it.'
    return res


def _t_video_render_status(job_id: str) -> dict:
    return _crews('GET', f'/api/internal/movement/status?job_id={job_id}')


def _t_video_render_stop(job_id: str) -> dict:
    return _crews('POST', '/api/internal/movement/stop', {'job_id': job_id})


def _t_crews_api(method: str, path: str, body: dict | None = None) -> dict:
    """The general seam onto the :5000 API — anything the typed tools above do
    not cover. This is what keeps Victor's reach EQUAL to Vicky's (who can curl
    any of it from Bash) instead of a hand-picked subset of it."""
    if not str(path or '').startswith('/api/'):
        return {
            'ok': False,
            'error': "path must start with /api/ — this tool only reaches the crews API's own endpoints",
        }
    if str(method).upper() not in ('GET', 'POST', 'DELETE', 'PUT'):
        return {'ok': False, 'error': 'method must be GET, POST, PUT or DELETE'}
    return _crews(method, path, body)
