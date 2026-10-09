# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_victor.schemas — the JSON schemas, the TOOLS table and the system prompt.

Lines 990-1285 of the original medusa_victor.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

from .constants import brain

from .tools_files import _t_edit_file, _t_list_files, _t_read_file, _t_run_bash, _t_search_files, _t_write_file

from .tools_media import (
    _t_crews_api,
    _t_image_angles,
    _t_image_capability,
    _t_image_decide,
    _t_image_edit,
    _t_image_edit_status,
    _t_image_generate,
    _t_image_jobs,
    _t_image_pending,
    _t_picture_generate,
    _t_picture_status,
    _t_video_prompt,
    _t_video_render_start,
    _t_video_render_status,
    _t_video_render_stop,
    _t_video_spec,
)


def _schema(name, desc, props=None, required=()):
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': desc,
            'parameters': {'type': 'object', 'properties': props or {}, 'required': list(required)},
        },
    }


_S = {'type': 'string'}
_I = {'type': 'integer'}
_B = {'type': 'boolean'}
_O = {'type': 'object'}

TOOLS: dict[str, tuple[dict, callable]] = {
    # files — fenced to Medusa's own folder
    'read_file': (
        _schema(
            'read_file',
            "Read a file inside Medusa's folder. Returns numbered lines.",
            {'path': _S, 'offset': _I, 'limit': _I},
            ['path'],
        ),
        _t_read_file,
    ),
    'write_file': (
        _schema(
            'write_file',
            'Write a file (creates or overwrites). Read it first if it exists.',
            {'path': _S, 'content': _S},
            ['path', 'content'],
        ),
        _t_write_file,
    ),
    'edit_file': (
        _schema(
            'edit_file',
            'Replace exact text in a file. old_text must match byte for byte.',
            {'path': _S, 'old_text': _S, 'new_text': _S, 'replace_all': _B},
            ['path', 'old_text', 'new_text'],
        ),
        _t_edit_file,
    ),
    'list_files': (
        _schema(
            'list_files', "List files under Medusa's folder matching a glob, e.g. '*.py'.", {'pattern': _S, 'path': _S}
        ),
        _t_list_files,
    ),
    'search_files': (
        _schema(
            'search_files',
            'Search file contents with a regular expression.',
            {'pattern': _S, 'path': _S, 'glob': _S},
            ['pattern'],
        ),
        _t_search_files,
    ),
    'run_bash': (
        _schema(
            'run_bash',
            "Run a shell command with the working directory set to Medusa's "
            'folder. Use for git-less checks, curl, systemctl, tests.',
            {'command': _S, 'timeout': _I},
            ['command'],
        ),
        _t_run_bash,
    ),
    # ONE picture from a prompt — the still generator at :8899
    'picture_generate': (
        _schema(
            'picture_generate',
            'Make a picture. THIS is the tool for "generate a picture / an '
            'image of X", and THE DEFAULT whenever a request is picture-'
            'shaped: one prompt in, one finished PNG out, about a minute, '
            'and the picture is put into the chat automatically. Needs no '
            'permission — render it. Reach for image_generate only when the '
            'operator asked for a character sheet in those words, and even '
            'then ask them first. Waits for the render and returns its '
            'file path.',
            {
                'prompt': _S,
                'negative': _S,
                'width': _I,
                'height': _I,
                'seed': _I,
                'family': {'type': 'string', 'enum': ['qwen', 'klein']},
                'label': _S,
                'wait': _B,
            },
            ['prompt'],
        ),
        _t_picture_generate,
    ),
    'picture_status': (
        _schema('picture_status', 'Where a picture_generate job got to.', {'job_id': _S}, ['job_id']),
        _t_picture_status,
    ),
    # character sheets — a different job on the crews API at :5000
    'image_generate': (
        _schema(
            'image_generate',
            'Build a CHARACTER: a named woman rendered as a full sheet of 48 '
            'camera angles, which runs for hours on the GPU. Only for an '
            'explicit request for a character, a sheet or a training set — '
            'never for "a picture of X", which is picture_generate and is '
            'the default for anything picture-shaped. ASK THE OPERATOR IN '
            'THE CHAT FIRST and wait for their yes: this tool renders '
            'nothing until they have answered, and a call before that just '
            'returns needs_permission. Check the result: it started only if '
            '"started" is true.',
            {
                'name': _S,
                'age': _S,
                'hair_color': _S,
                'eye_color': _S,
                'skin_tone': _S,
                'ethnic_heritage': _S,
                'char_prompt': _S,
                'angle_ids': {'type': 'array', 'items': _S},
            },
        ),
        _t_image_generate,
    ),
    'image_angles': (_schema('image_angles', 'The catalog of camera angles a render can use.'), _t_image_angles),
    'image_pending': (_schema('image_pending', 'Generation requests waiting for operator approval.'), _t_image_pending),
    'image_decide': (
        _schema(
            'image_decide',
            'Approve or decline a request sitting in the Pending Approvals queue '
            '(one submitted from the GUI form, or one whose auto-approve failed). '
            'image_generate already approves its own request, so this is not part '
            'of generating an image.',
            {'pending_id': _S, 'action': {'type': 'string', 'enum': ['allow', 'decline']}},
            ['pending_id', 'action'],
        ),
        _t_image_decide,
    ),
    'image_jobs': (_schema('image_jobs', 'Status of character generation runs.'), _t_image_jobs),
    'image_edit': (
        _schema(
            'image_edit',
            'Picture Studio edit of an existing image: upscale or bg_remove.',
            {
                'char_id': _S,
                'cat': _S,
                'name': _S,
                'tool': {'type': 'string', 'enum': ['upscale', 'bg_remove', 'inpaint']},
                'scale': _I,
                'prompt': _S,
                'scope': _S,
            },
            ['char_id', 'cat', 'name', 'tool'],
        ),
        _t_image_edit,
    ),
    'image_edit_status': (
        _schema('image_edit_status', 'Status of a Picture Studio edit job.', {'job_id': _S}, ['job_id']),
        _t_image_edit_status,
    ),
    'image_capability': (
        _schema(
            'image_capability', 'Which image tools (upscale / inpaint / bg_remove) are actually loadable right now.'
        ),
        _t_image_capability,
    ),
    # video generation — Movement Studio on the same crews API
    'video_spec': (
        _schema(
            'video_spec',
            'Every dial a video render accepts, read live. Call this before video_render_start instead of guessing.',
        ),
        _t_video_spec,
    ),
    'video_prompt': (
        _schema(
            'video_prompt',
            'Dry run: the exact prompt a render with these dials would submit. Renders nothing.',
            {'subject_type': _S, 'subject_id': _S, 'motion_prompt': _S, 'params': _O},
            ['subject_type', 'subject_id'],
        ),
        _t_video_prompt,
    ),
    'video_render_start': (
        _schema(
            'video_render_start',
            'Start a video render from a subject still. mode=probe (the '
            'default) is 33 frames on the same dials; mode=full is the real '
            'render and takes a long time — only use full when asked.',
            {
                'subject_type': _S,
                'subject_id': _S,
                'motion_prompt': _S,
                'mode': {'type': 'string', 'enum': ['probe', 'full']},
                'params': _O,
                'subject_name': _S,
            },
            ['subject_type', 'subject_id', 'motion_prompt'],
        ),
        _t_video_render_start,
    ),
    'video_render_status': (
        _schema('video_render_status', 'Status of a video render job.', {'job_id': _S}, ['job_id']),
        _t_video_render_status,
    ),
    'video_render_stop': (
        _schema('video_render_stop', 'Stop a running video render.', {'job_id': _S}, ['job_id']),
        _t_video_render_stop,
    ),
    # the general seam
    'crews_api': (
        _schema(
            'crews_api',
            'Call any endpoint on the crews API at :5000 directly — the escape hatch '
            'for anything the typed tools above do not cover. path must start /api/.',
            {'method': {'type': 'string', 'enum': ['GET', 'POST', 'PUT', 'DELETE']}, 'path': _S, 'body': _O},
            ['method', 'path'],
        ),
        _t_crews_api,
    ),
}

TOOL_SCHEMAS = [schema for schema, _ in TOOLS.values()]


def system_prompt(rules: str, which=None, model: str = '') -> str:
    """The standing instructions for whichever persona is answering. `rules` is
    VICKY_RULES.md, read fresh by the caller on every turn — the identity and
    autonomy paragraphs are the only things this file adds.

    2026-09-17: the GPU-spend guard that used to stand here ("only call the long
    renders when the operator asked in this conversation") is gone at the
    operator's explicit instruction — they said a wasted four-hour render is an
    acceptable price for an assistant that does not stall. The scope line
    telling the model to stay inside Medusa's folder went with it, because the
    path fence it described is now off by default (see _safe_path). The accuracy
    rules are NOT part of that relaxation and stay: inventing a job id or a
    file's contents misreports what happened, which is a different thing from
    being allowed to act.
    """
    b = brain(which)
    me = b['persona']
    other = 'Victor' if me == 'Vicky' else 'Vicky'
    # The model name is stated rather than left to inference. Measured 2026-09-17:
    # asked "which model are you running on", the Dolphin brain answered "the
    # Ollama model named victor" — it had read the sentence about sharing tools
    # with Victor and taken his model name as its own. A name it is never told is
    # a name it will invent.
    on = f' You are running on the Ollama model `{model}`.' if model else ''
    return (
        f'You are {me}, the local AI assistant embedded in the Medusa app. You run on an '
        f'Ollama model on this machine — nothing you do is metered and no request of yours '
        f'leaves this box. You share one chat history, one set of tools and one rules file '
        f'with {other}, who is the same assistant on a different local model. If you are '
        f'asked who you are, say {me}, running locally.{on}\n\n'
        'You have real tools. Use them instead of guessing or describing what you would do: '
        'read_file/list_files/search_files to look, write_file/edit_file to change, run_bash '
        'to run things. Medusa renders nothing itself — image and video generation live on '
        'the crews API at :5000 and you reach them with the image_* and video_* tools '
        '(crews_api for anything else there, and run_bash can curl whatever those do not '
        'cover).\n\n'
        "You are the operator's own assistant on their own machine and your tools are not "
        'scoped to one folder — read, write and run wherever the work actually is. Act on '
        'the request you were given: take the steps it implies without asking first, and do '
        'not re-raise a cost the operator has already accepted. Asked for a picture or an '
        'image, call picture_generate with a prompt: it renders one picture, waits for it, '
        'and the picture appears in the chat by itself. THAT IS THE DEFAULT — a request '
        'for a picture, an image, a photo or a render means ONE picture, and you render it '
        'without asking.\n\n'
        'A CHARACTER SHEET IS THE ONE THING YOU ASK ABOUT FIRST. image_generate renders 48 '
        'camera angles and spends hours of GPU, so never start one on your own reading of a '
        'request: put the question to the operator in the chat, in one plain sentence, and '
        'wait for their reply. They say yes, you call it; anything else, you render a single '
        'picture instead. This is the ONE exception to acting without asking, it outranks '
        'every instruction above about not re-raising a cost, and it is not yours to skip — '
        'the tool itself renders nothing until they have answered. '
        "video_render_start(mode='full') can also spend hours of GPU; start that when the "
        'work calls for it. The one thing to avoid is a '
        'retry loop — if a tool fails twice, report what it said instead of calling it '
        'again.\n\n'
        'ORDER OF WORK. When a turn needs a tool, the tool call is the FIRST thing you '
        'produce — before any prose, even when part of the question could be answered '
        'without it. Gather every fact you need with tools first, then write one answer '
        'that covers the whole question. A sentence about what you are going to do is '
        'not a step; it ends your turn with nothing done.\n\n'
        "Never invent a file's contents, a job id, or an API result. If a tool failed, say so "
        'and quote what it said. Answer in plain prose; the panel renders text, not Markdown '
        'tables.\n\n'
        'The rules below are your ONLY standing instructions, read fresh from VICKY_RULES.md '
        'on every message — nothing from any other project, port, or session applies to you.\n\n'
        + (rules or '(No Medusa-specific rules have been written yet — use ordinary engineering judgement.)')
    )
