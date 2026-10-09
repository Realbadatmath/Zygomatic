# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sections 12-14: gate reachability and Stage 3.7, the retry ladder executed
rather than grepped, and the inert-lever guard."""

import json
import os

from .core import (  # noqa: F401  shared harness state, used by the moved sections
    _ast,
    check,
    paths,
    skip,
)


# ── 12. gate wiring: does the gate actually RUN? ───────────────────────────
# The previous version of this test asserted that the string
# 'Stage 3.7: Hand QC' appears in pipeline_scholarly.py somewhere AFTER the
# 'FLUX unloaded' message. It passed for the gate's entire life — and that
# placement was exactly the bug: being textually after the unload put the block
# INSIDE `if not _sch_fw_active:`, a branch that ZYG_SCHOLARLY_FLUX_PERSISTENT=1
# (set in .env) makes permanently false. The gate never executed on a single
# production run, and 52/52 stayed green.
#
# A substring can prove a line was typed. It cannot prove the line runs. These
# tests parse the file and ask about reachability instead.


def _parents(tree):
    m = {}
    for node in _ast.walk(tree):
        for kid in _ast.iter_child_nodes(node):
            m[kid] = node
    return m


def _enclosing_ifs(node, parents):
    """Every `if` test that must be true for `node` to execute."""
    out, cur = [], node
    while cur in parents:
        par = parents[cur]
        if isinstance(par, _ast.If) and any(cur is s or cur in _ast.walk(s) for s in par.body):
            out.append(_ast.unparse(par.test))
        cur = par
    return out


def test_gate_reachability():
    tree = _ast.parse(open('pipeline_scholarly.py', encoding='utf-8').read())
    parents = _parents(tree)

    expected = None
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Assign) and getattr(node.targets[0], 'id', '') == '_GATES_EXPECTED':
            expected = [e.value for e in node.value.elts]
    if not check('_GATES_EXPECTED is declared', bool(expected)):
        return

    receipts = {}
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.Call)
            and getattr(node.func, 'id', '') == '_gate_receipt'
            and node.args
            and isinstance(node.args[0], _ast.Constant)
        ):
            receipts.setdefault(node.args[0].value, []).append(_enclosing_ifs(node, parents))

    # Every gate is pre-registered as NOT RUN before any branch can skip it, so
    # a run always carries one line per gate. A real receipt may legitimately
    # sit behind `if we generated any images` — what must never happen is a
    # gate with no line at all.
    src_txt = open('pipeline_scholarly.py', encoding='utf-8').read()
    check(
        'gates are pre-registered before any branch',
        'for _g_name in _GATES_EXPECTED:' in src_txt and 'pipeline never reached this gate' in src_txt,
    )
    for gate in expected:
        paths = receipts.get(gate)
        check(f'gate {gate!r} files a real receipt', bool(paths), '' if paths else 'only the pre-registration')
        # Its guards must be about whether there was work to do — never about
        # which internal strategy the stage happened to pick.
        for conds in paths or []:
            check(
                f'gate {gate!r} is not gated on an internal strategy flag',
                all('_sch_fw_active' not in c for c in conds),
                str(conds),
            )

    # The specific regression: hand QC must not be gated on the FLUX-unload
    # branch, because the persistent worker makes that branch never run.
    hand = receipts.get('hand_qc') or []
    check(
        'hand QC is not nested under the FLUX-unload branch',
        all('_sch_fw_active' not in c for conds in hand for c in conds),
        str(hand[:1]),
    )


def test_stage37_runs_with_persistent_worker():
    """Stage 3.7 must be reachable on BOTH FLUX paths."""
    tree = _ast.parse(open('pipeline_scholarly.py', encoding='utf-8').read())
    parents = _parents(tree)
    found = []
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.Call)
            and getattr(node.func, 'id', '') == '_stage_start'
            and node.args
            and isinstance(node.args[0], _ast.Constant)
            and 'Stage 3.7' in str(node.args[0].value)
        ):
            found.append(_enclosing_ifs(node, parents))
    if not check('Stage 3.7 is started somewhere', bool(found)):
        return
    conds = found[0]
    check('Stage 3.7 does not depend on _sch_fw_active', all('_sch_fw_active' not in c for c in conds), str(conds))
    txt = open('pipeline_scholarly.py', encoding='utf-8').read()
    check('Stage 3.7 reclaims VRAM before judging', 'VRAM before hand QC' in txt)

    # The judge needs a free card, and the persistent worker only lets go at the
    # end of the FLUX section. Measured: 6.5 GB free inside it, 36.1 GB after.
    # So the pass must be CALLED outside the FLUX block, not merely defined
    # outside the unload branch.
    calls = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and getattr(node.func, 'id', '') == '_sch_hand_qc_pass':
            calls.append(_enclosing_ifs(node, parents))
    if check('hand QC pass is invoked', bool(calls)):
        check(
            'hand QC runs outside the FLUX block, where the card is free',
            all(not any('_flux_ready' in c for c in conds) for conds in calls),
            str(calls),
        )


# ── 13. the retry ladder, executed rather than grepped ─────────────────────
def _ladder_block():
    """Lift the ladder's branch-selection source out of the pipeline."""
    src = open('pipeline_scholarly.py', encoding='utf-8').read().split('\n')
    lo = next(i for i, l in enumerate(src) if l.strip() == 'if _attempt == 0:')
    hi = next(i for i, l in enumerate(src) if i > lo and 'Vary seed slightly on each retry' in l)
    import textwrap

    return textwrap.dedent('\n'.join(src[lo:hi]))


def _run_ladder(attempt, text_fail=False, era_fail=False, smoke=False, clause_used=False, era_rung_used=0):
    """Execute the real branch-selection code for one attempt."""
    import ast as _a

    ns = {}
    full = open('pipeline_scholarly.py', encoding='utf-8').read()
    for node in _a.parse(full).body:
        if (isinstance(node, _a.FunctionDef) and node.name == '_strip_written_subject') or (
            isinstance(node, _a.Assign) and getattr(node.targets[0], 'id', '') == '_WRITTEN_NOUNS'
        ):
            exec(compile(_a.Module([node], []), '<h>', 'exec'), ns)  # noqa: S102  AST subset lifted from a source file shipped in this repo, never from input
    env = {
        '_attempt': attempt,
        '_prompt': 'cinematic photograph two clerks argue '
        'across a ledger in a customs house, medium shot, photorealistic, 8k',
        '_n_steps': 4,
        '_g_scale': 0.0,
        '_vlm_text_fail_prev': text_fail,
        '_vlm_era_fail_prev': era_fail,
        '_SCHOLARLY_SMOKE_MAX_IMAGES': smoke,
        '_strip_written_subject': ns['_strip_written_subject'],
        '_ladder_stats': {
            'reroll': 0,
            'text_clause': 0,
            'text_strip': 0,
            'era_edit': 0,
            'era_escalation': 0,
            'anatomy_escalation': 0,
        },
        '_era_lock': {'period_label': '17th century'},
        # era rung (2026-08-25): flag-derived qualifier, rung counter, family
        '_era_rung_used': era_rung_used,
        '_era_ladder_qualifier': lambda i: ', a horn lantern with a candle inside' if era_fail else '',
        '_sch_qwen_stills': False,
        # attempt 0 always sets these; later rungs inherit unless they assign,
        # so seed them or the guidance assertion below passes vacuously.
        '_scale_attempt': 0.0,
        '_steps_attempt': 4,
        # set by the attempt-2 clause rung; attempt 3 reads it to name the rung
        # it actually followed.
        '_clause_used': clause_used,
        'idx': 1,
        '_debug': lambda *a, **k: None,
        '_log': lambda *a, **k: None,
    }
    # _ladder_block() slices the real branch-selection block out of pipeline_scholarly.py,
    # a source file shipped in this repo; running it is the point of this harness.
    exec(_ladder_block(), env)  # noqa: S102  source slice from this repo, see above
    return env


def test_retry_ladder():
    src = open('pipeline_scholarly.py', encoding='utf-8').read()

    # attempt 1 = the prompt exactly as written
    a1 = _run_ladder(0)
    check('attempt 1 renders the prompt unchanged', a1['_prompt_attempt'] == a1['_prompt'])

    # attempt 2, non-text defect = pure re-roll (same prompt, new seed)
    a2 = _run_ladder(1)
    check(
        'attempt 2 is a pure re-roll for anatomy/era defects',
        a2['_prompt_attempt'] == a2['_prompt'] and a2['_ladder_stats']['reroll'] == 1,
    )

    # attempt 2, TEXT defect = the clause with production evidence behind it.
    # This is the mechanism that cleared all ten slots on the converging run;
    # the pure-re-roll restructure had silently dropped it, leaving the ladder
    # to jump from no remedy straight to rewriting the scene.
    a2t = _run_ladder(1, text_fail=True)
    check(
        'attempt 2 on a text defect appends the suppression clause',
        'no readable lettering anywhere in frame' in a2t['_prompt_attempt'],
    )
    check('...and keeps the original scene intact', 'ledger' in a2t['_prompt_attempt'])
    check('...and is counted as the clause rung', a2t['_ladder_stats']['text_clause'] == 1)

    # attempt 3, text defect = drop the written object entirely
    a3t = _run_ladder(2, text_fail=True)
    check('attempt 3 on a text defect removes the written object', 'ledger' not in a3t['_prompt_attempt'])
    check('...and is counted as the strip rung', a3t['_ladder_stats']['text_strip'] == 1)
    # The clause rung sets _clause_used; attempt 3 must report which rung it
    # actually followed rather than always claiming the clause ran.
    check('attempt 2 clause rung records that it ran', _run_ladder(1, text_fail=True)['_clause_used'] is True)

    # attempt 2, anachronism = the OBJECT qualifier from the era gate's flag,
    # prompt edited, seed kept — the typography ladder's mechanism, not a
    # re-roll that throws the composition away to fix a hat.
    a2e = _run_ladder(1, era_fail=True)
    check(
        'attempt 2 on an anachronism appends the object qualifier',
        'horn lantern with a candle inside' in a2e['_prompt_attempt'],
    )
    check('...keeps the scene', 'ledger' in a2e['_prompt_attempt'])
    check(
        '...is counted as the era-edit rung, not a re-roll',
        a2e['_ladder_stats']['era_edit'] == 1 and a2e['_ladder_stats']['reroll'] == 0,
    )
    check('...and bumps the rung counter', a2e['_era_rung_used'] == 1)
    # attempt 3, anachronism = qualifier + generic period restatement + steps
    a3e = _run_ladder(2, era_fail=True, era_rung_used=1)
    check(
        'attempt 3 on an anachronism restates the period',
        'strictly period-accurate 17th century' in a3e['_prompt_attempt'],
    )
    check('...keeps the object qualifier too', 'horn lantern' in a3e['_prompt_attempt'])
    check('...and is the escalation rung', a3e['_ladder_stats']['era_escalation'] == 1)
    # the seed rule: an era edit keeps the seed, everything else moves it
    lo = src.index('# Vary seed slightly on each retry')
    seed_src = src[lo : lo + 600]
    check('era prompt-edit rungs keep the seed', '_gen_seed if (_vlm_era_fail_prev' in seed_src, seed_src[:200])

    # attempt 3, anatomy
    a3a = _run_ladder(2)
    check('attempt 3 on an anatomy defect asks for correct hands', 'perfectly formed hands' in a3a['_prompt_attempt'])
    check('attempt 3 raises step count', a3a['_steps_attempt'] == 28)

    # No rung may lean on a lever the model discards.
    for tag, env in (('text', a3t), ('era', a3e), ('anatomy', a3a)):
        check(
            f'{tag} rung does not raise guidance (inert on schnell)',
            '_scale_attempt' in env and float(env['_scale_attempt']) <= 0.01,
            f'scale={env.get("_scale_attempt")}',
        )

    check('a still-flagged winner is reported, not shipped silently', 'SHIPPED FLAGGED after' in src)
    check('flagged slots recorded in run state', "pipeline_state['shipped_flagged']" in src)
    check(
        'the completion line names outcomes BY SLOT NUMBER',
        'GATE OUTCOMES' in src and 'unreviewed by anatomy judge: {_unrev["anatomy"]' in src,
    )
    check('...and no longer claims every slot cleared', 'Every slot cleared its gates' not in src)
    check('outcomes recorded in run state', "pipeline_state['slot_gate_outcomes']" in src)
    check('ladder records how far it climbed', "_ladder_stats['attempts']" in src)


# ── 14. inert levers ───────────────────────────────────────────────────────
def test_inert_lever_guard():
    """guidance_scale and negative_prompt are discarded by FLUX.1-schnell.

    Measured, same seed, sha256 of the PNG: guidance 0.0 / guidance 3.5 /
    guidance 3.5 + negative all produced 7ca25f6349e03e6b; only
    true_cfg_scale=3.5 differed (a4a979a3597a1ec7). The guard exists so the
    next parameter that silently does nothing is noticed on the run itself.
    """
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    check('inert-lever guard is defined', 'def _flux_lever_guard' in src)
    check(
        'guard runs before the pipe is called',
        src.find('_flux_lever_guard(_active_pipe') < src.find('_active_pipe(**_gen_kwargs)'),
    )
    check('guard checks guidance_embeds', 'guidance_embeds' in src)
    check('guard checks true_cfg_scale', 'true_cfg_scale' in src)
    check('the false "negatives bite at 3.5" claim is gone', 'finally makes _FLUX_NEGATIVE' not in src)

    cfg = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell' / 'transformer' / 'config.json')
    if os.path.exists(cfg):
        ge = json.load(open(cfg)).get('guidance_embeds')
        check('the shipped model really does discard guidance', ge is False, f'guidance_embeds={ge}')
    else:
        skip('model config readable', 'flux1-schnell not on this box')
