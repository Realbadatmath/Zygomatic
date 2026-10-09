# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The done gate and the MCP shim.

Moved verbatim out of the old single-file arch_assistant.py (lines 3234-3503).
"""

from __future__ import annotations

import re

# ── the done gate (2026-09-08, design rules) ─────────────────────────────────
# `done` runs the design check; while it reports ERRORS the first two calls are
# refused with the findings (the model fixes and calls again), the third — or
# any call with force=true — is accepted and the outstanding findings are
# appended to the summary so the operator sees them in the chat.
GATE_MAX = 2


# 2026-09-16: eight findings that say the same thing about eight records are one
# fact, and eight lines of it are eight lines of the model's reading budget spent
# on repetition (the live tower reports circ_core_clash 8 times, once per stair
# record). Findings that share a code AND a text-shape — the text with every
# record id stripped out — collapse into the FIRST of them with an 'xN' marker
# and the ids that were folded in, so the model still knows which records to fix.
_ID_RE = re.compile(r'\bo\d+\b')


def _finding_shape(f: dict) -> tuple:
    return (str(f.get('code') or ''), str(f.get('sev') or ''), _ID_RE.sub('#', str(f.get('text') or '')))


def dedupe_findings(findings: list) -> list:
    """Collapse findings with the same code and the same text-shape into one
    line carrying the count. Order is kept (the caller sorted errors first)."""
    out: list = []
    seen: dict = {}
    for f in findings:
        if not isinstance(f, dict):
            continue
        key = _finding_shape(f)
        i = seen.get(key)
        if i is None:
            seen[key] = len(out)
            out.append(dict(f, _n=1, _ids=_ID_RE.findall(str(f.get('text') or ''))))
            continue
        row = out[i]
        row['_n'] += 1
        for oid in _ID_RE.findall(str(f.get('text') or '')):
            if oid not in row['_ids']:
                row['_ids'].append(oid)
    for row in out:
        n = row.pop('_n')
        ids = row.pop('_ids')
        if n < 2:
            continue
        more = [i for i in ids if i not in _ID_RE.findall(row['text'])]
        tail = f' (also {", ".join(more[:6])}{", ..." if len(more) > 6 else ""})' if more else ''
        row['text'] = f'x{n}: {row["text"]}{tail}'
    return out


def design_findings(d) -> list:
    mod = EXT_MODULES.get('design_rules')
    if mod is None or d is None:
        return []
    try:
        return dedupe_findings(mod.run_checks(d))
    except Exception as e:  # noqa: BLE001
        return [{'sev': 'info', 'code': 'check_error', 'text': f'design check failed: {e!r}'}]


def design_gate(j: dict, d, args: dict, log) -> str:
    """'' when done may proceed, else the refusal text for the model."""
    # 2026-09-16: the schedule paints before the check, not after the refusal.
    # Drawing.new finishes a record at birth, but records drawn BEFORE
    # plan_building set the finish level keep their presets — this is the sweep
    # that catches them, so finish_rules.check_luxury_finishes never spends the
    # model's calls on a repaint it could have had for nothing.
    fs = EXT_MODULES.get('finish_schedule')
    if fs is not None and d is not None:
        try:
            n = fs.autofinish(d)
            if n:
                log(f'finishes: {n} flat presets painted by the {fs.finish_level(d)} schedule before the check')
        except Exception as e:  # noqa: BLE001 — a finish never blocks the gate
            log(f'finishes: the schedule could not run ({e!r})')
    findings = design_findings(d)
    j['_design'] = findings
    # 2026-09-11: the author does not hold the gate. Job 94f5813b called done(force=true)
    # as its FIRST done and the error it 'explained away' stayed in the drawing. The
    # flag is gone from the tool schema; only the job may carry operator_force (a
    # panel action), and whatever the model passes is ignored.
    force = bool(j.get('operator_force'))
    # 2026-09-10, the fourth layer: the author does not verify its own work. done
    # is refused until present() has rendered THIS drawing — the signature pins the
    # records, so a drawing changed after the views were shown is shown again.
    sigfn = getattr(EXT_MODULES.get('blender_power'), 'present_sig', None)
    if sigfn is not None and d is not None and d.objs and not force:
        try:
            want = sigfn(d)
        except Exception:  # noqa: BLE001
            want = None
        shown = d.ext.get('presented') if isinstance(d.ext.get('presented'), dict) else {}
        if want is not None and shown.get('sig') != want:
            n = int(j.get('_gate') or 0)
            if n < GATE_MAX:
                j['_gate'] = n + 1
                log(f'done refused ({n + 1}/{GATE_MAX}): present() has not shown this drawing')
                return (
                    'done REFUSED — call present() first: it renders the approach, section, elevation, aerial '
                    'and lobby views of the CURRENT drawing and lists the design-check findings under them; '
                    f'then done(summary). Attempt {n + 1} of {GATE_MAX}.'
                )
        # 2026-09-23, the operator's standing rule: "after every drawing, make
        # sure ai assistant delivers portfolio folder with 40+ images". Five
        # views are what the author chose to show; the portfolio is fifty the
        # author did not choose — right round it, a cut at six stations, and
        # two from inside EVERY level — plus the surface audit. A hand-over
        # without one is a hand-over on the author's word.
        book = d.ext.get('portfolio') if isinstance(d.ext.get('portfolio'), dict) else {}
        if want is not None and book.get('sig') != want:
            n = int(j.get('_gate') or 0)
            if n < GATE_MAX:
                j['_gate'] = n + 1
                log(f'done refused ({n + 1}/{GATE_MAX}): portfolio() has not photographed this drawing')
                return (
                    'done REFUSED — call portfolio() first: about fifty renders of the CURRENT drawing in '
                    'one pass, written to a folder the operator opens, with a surface audit of the '
                    'materials and the curves. LOOK at the contact sheets it hands back and fix what they '
                    f'show before done(summary). Attempt {n + 1} of {GATE_MAX}.'
                )
    errors = [f for f in findings if f['sev'] == 'error']
    if not errors or force:
        return ''
    n = int(j.get('_gate') or 0)
    if n >= GATE_MAX:
        return ''
    j['_gate'] = n + 1
    mod = EXT_MODULES.get('design_rules')
    body = mod.format_findings(findings) if mod else '\n'.join(f['text'] for f in errors)
    log(f'done refused ({n + 1}/{GATE_MAX}): {len(errors)} design error(s)')
    return (
        'done REFUSED — the design check found errors. Fix them with the drawing tools, then call done again '
        f'(there is no force flag: an error still open when the gate gives up marks the job UNFINISHED). '
        f'Attempt {n + 1} of {GATE_MAX}.\n' + body
    )


def design_note(j: dict) -> str:
    fs = [f for f in (j.get('_design') or []) if f['sev'] in ('error', 'warn')]
    if not fs:
        return ''
    return '\n\nDesign check: ' + '; '.join(f'[{f["sev"]}] {f["text"].split(" — ")[0]}' for f in fs[:6])


def shim_tools(q: dict) -> dict:
    """GET /assistant/tools?id&token — the tool list for the shim (extensions included)."""
    if not _shim_job(q):
        return {'ok': False, 'error': 'unknown job or bad token'}
    return {
        'ok': True,
        'tools': [
            {'name': t['name'], 'description': t['description'], 'input_schema': t['input_schema']} for t in TOOL_DEFS
        ],
    }


def shim_tool(body: dict) -> dict:
    """POST /assistant/tool {id, token, name, args} — one tool call from the CLI,
    run on the job's Drawing copy. Same semantics as the in-process loop:
    ask_user posts the question, done records the summary, look parks the job
    in need_client until the studio renders (≤ 120 s), everything else draws."""
    j = _shim_job(body)
    if not j:
        return {'ok': False, 'error': 'unknown job or bad token'}
    if j['cancel']:
        return {'ok': False, 'error': 'cancelled'}
    d = j.get('_d')
    name = str(body.get('name') or '')
    if name.startswith('mcp__' + MCP_SERVER + '__'):
        name = name[len('mcp__' + MCP_SERVER + '__') :]
    args = body.get('args') if isinstance(body.get('args'), dict) else {}

    def log(line):
        j['log'].append(str(line)[:300])

    if name == 'ask_user':
        j['question'] = str(args.get('question') or j.get('reply') or 'What do you mean?')
        log('question: ' + j['question'][:200])
        return {
            'ok': True,
            'text': 'Question posted to the user. End your turn now, with no more tool calls and no '
            'further drawing; the answer arrives as the next message.',
        }
    if name == 'done':
        refusal = design_gate(j, d, args, log)
        if refusal:
            return {'ok': True, 'text': refusal}
        errs = [f for f in (j.get('_design') or []) if f.get('sev') == 'error']
        if errs:
            # 2026-09-11: the gate gave up (GATE_MAX) or the operator forced it — the job is
            # handed over, but shown as UNFINISHED with the count, never as a clean done.
            j['incomplete'] = True
            j['stop'] = f'{len(errs)} design error(s) still open at done'
            log(f'done accepted with {len(errs)} open design error(s) — job marked UNFINISHED')
        j['_final'] = (
            (f'UNFINISHED — {len(errs)} design error(s) open. ' if errs else '')
            + str(args.get('summary') or j.get('reply') or 'Done.')
            + design_note(j)
        )
        log('done: ' + j['_final'][:200])
        return {'ok': True, 'text': 'ok — the drawing is handed to the studio. End your turn now.'}
    if name == 'look':
        if d is None:
            return {'ok': False, 'error': 'no drawing on this job'}
        j['need'] = {
            'kind': 'render',
            'view': args.get('view') or 'iso',
            'storey': args.get('storey'),
            'cells': bool(args.get('cells')),
            'doc': d.to_doc(),
        }
        j['status'] = 'need_client'
        j['_ev'].clear()
        log(
            f'look: {args.get("view")} view'
            + (f' storey {args.get("storey")}' if args.get('storey') is not None else '')
        )
        got = j['_ev'].wait(120)
        j['status'] = 'running'
        if j['cancel']:
            return {'ok': False, 'error': 'cancelled'}
        img = _img_parts(j.get('_render') or '') if got else None
        return {
            'ok': True,
            'text': 'here is the view' if img else 'the studio did not answer with a picture',
            'image': list(img) if img else None,
        }
    if d is None:
        return {'ok': False, 'error': 'no drawing on this job'}
    arg_txt = ', '.join(f'{k}={v}' for k, v in list(args.items())[:6])
    log(f'{name}({arg_txt[:160]})')
    # 2026-09-10, the drawing budget: MAX_CALLS calls that CHANGE the drawing. Reads,
    # checks, spec/explain and renders are free and stay free once it is spent, so
    # the model can still look at what it made, present it and hand it over.
    if int(j.get('_draw_calls') or 0) >= MAX_CALLS and draws(name):
        txt = (
            f'refused: the drawing budget ({MAX_CALLS} drawing calls) is spent — call present() and then done(summary)'
        )
        log('  ' + txt)
        return {'ok': True, 'text': txt}
    sig_before = (len(d.objs), len(d.added), len(d.removed), len(d.changed_ids()))
    try:
        res = call_tool(d, name, args)
    except Exception as e:  # noqa: BLE001
        log(f'  error: {e}'[:200])
        return {'ok': False, 'error': f'{name} failed: {e}'[:300]}
    if (len(d.objs), len(d.added), len(d.removed), len(d.changed_ids())) != sig_before:
        if draws(name):
            j['_draw_calls'] = int(j.get('_draw_calls') or 0) + 1
            log(f'budget: {j["_draw_calls"]}/{MAX_CALLS} drawing calls')
        else:
            log('budget: fix call (free)')
    # 2026-09-11: a tool may hand the model PICTURES to judge, not just numbers —
    # {'text': str, 'images': [[mime, b64], ...]} (present()). Only this caller
    # unwraps it; call_tool still returns something that str()s to the text, so
    # the in-process loop and every test keep their string.
    if isinstance(res, dict) and isinstance(res.get('text'), str) and isinstance(res.get('images'), list):
        txt, imgs = res['text'], [list(i) for i in res['images'][:3]]
        log('  ' + txt[:200])
        log(f'present: {len(imgs)} pictures handed to the model')
        return {'ok': True, 'text': txt, 'images': imgs}
    img = None
    if isinstance(res, tuple):  # (text, data_url): a tool that hands back a picture
        res, img = str(res[0]), _img_parts(res[1] if len(res) > 1 else '')
    res = str(res)
    log('  ' + res[:200])
    return {'ok': True, 'text': res, 'image': list(img) if img else None}


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    MAX_CALLS,
    MCP_SERVER,
    draws,
)
from zyg_workflows.arch_assistant.walls import TOOL_DEFS  # noqa: E402
from zyg_workflows.arch_assistant.ground import EXT_MODULES  # noqa: E402
from zyg_workflows.arch_assistant.prompts import call_tool  # noqa: E402
from zyg_workflows.arch_assistant.backends import _img_parts  # noqa: E402
from zyg_workflows.arch_assistant.cli_backend import _shim_job  # noqa: E402
