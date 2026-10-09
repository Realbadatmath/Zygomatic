# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STEP 5b — the operator-facing markdown rendering of a finished report."""

import json
import os

from zyg_workflows.vlm_report.constants import (
    CONTEXT_STRIDE_FRAMES,
    LESSONS_PATH,
    MIN_CROP_PX,
    NATIVE_FPS,
    _DIR,
)
from zyg_workflows.vlm_report.synthesis import _fmt_metric_table

# ── STEP 5b: markdown ────────────────────────────────────────────────────────


def _write_markdown(path, ctx):
    f = ctx['findings']
    fails = [x for x in f if x['status'] == 'fail']
    unk = [x for x in f if x['status'] == 'unknown']
    lines = []
    A = lines.append
    A(f'# Defect report — {os.path.basename(ctx["clip"])}')
    A('')
    A(
        f'*Automated analysis. No human interpreted any frame; the verdict below '
        f'was written by a local {ctx["synth_model"] or "LLM"} from the evidence in '
        f'this document.*'
    )
    A('')
    if ctx['synth_text']:
        A(ctx['synth_text'].strip())
    else:
        A('## Verdict')
        A('')
        A(
            f'**{ctx["verdict"]}** — the local LLM synthesis step did not produce '
            f'text ({ctx["synth_error"]}). The measured evidence below is complete '
            f'and unaffected; only the prose layer is missing.'
        )
    A('')
    A('---')
    A('')
    A('## Findings table (machine-generated, not LLM prose)')
    A('')
    A(
        f'Overall gate verdict: **{ctx["verdict"]}** — '
        f'{len(fails)} failing, {len(unk)} unknown, '
        f'{len(f) - len(fails) - len(unk)} passing.'
    )
    A('')
    A(_fmt_metric_table(f))
    A('')
    A(
        '`source` is who witnessed the finding: `vlm` = the vision-language judge '
        'only, `pixel` = the measured metrics only, `both` = independently '
        'corroborated. The judge is measurably blind to temporal defects (frozen '
        'regions, seam morphing) and scored 0/7 on a confirmed ink defect, so a '
        '`vlm`-only PASS on those classes is not evidence of a clean render.'
    )
    A('')
    if fails:
        A('## Failing findings in detail')
        A('')
        for x in fails:
            A(f'### {x["id"]}  ({x["severity"]}, witnesses: {x["source"]})')
            A('')
            if x['times']:
                A(f'Timestamps: {", ".join(f"{t}s" for t in x["times"][:12])}')
                A('')
            for s in x['signals']:
                if s['status'] != 'fail':
                    continue
                if s['source'] == 'vlm':
                    A(
                        f'- **[judge] {s["name"]}** asked on the '
                        f'`{s.get("asked_on")}` crop — answered `{s.get("answer")}`, '
                        f'a correct render answers `{s.get("expected")}` '
                        f'(k={s.get("k")}, votes={s.get("votes")}).'
                    )
                    if s.get('reason'):
                        A(f'  Judge\'s own words: *"{str(s["reason"])[:300]}"*')
                    if s.get('fail_times'):
                        A(f'  Reproduced at: {s["fail_times"]}')
                else:
                    A(f'- **[metrics] {s["name"]}** — {s.get("reason")}')
                    m = s.get('measured')
                    if isinstance(m, dict):
                        keep = {
                            k: v
                            for k, v in m.items()
                            if k
                            in (
                                'flow_mean',
                                'flow_p95',
                                'churn_mean',
                                'churn_p95',
                                'ncc_min',
                                'ncc_max',
                                'detect_rate',
                                'issue_counts',
                                'chirality_flips',
                            )
                        }
                        if keep:
                            A(f'  Measured: `{json.dumps(keep)}`  Threshold: `{json.dumps(s.get("threshold"))}`')
            for b in x['boxes'][:6]:
                A(
                    f'- Location (full-frame fractional box, remapped from the crop): '
                    f'`{b["box_frac"]}`' + (f' at t={b["t"]}s' if b.get('t') is not None else '') + f' [{b["source"]}]'
                )
            for c in x['caveats']:
                A(f'- ⚠ {c}')
            if x['evidence']:
                A('- Evidence crops: ' + ', '.join(f'`crops/{os.path.basename(p)}`' for p in x['evidence'][:6]))
            A('')
    if unk:
        A('## Findings that could not be decided')
        A('')
        for x in unk:
            why = '; '.join(
                str(s.get('skipped_reason') or s.get('reason'))[:160] for s in x['signals'] if s['status'] == 'unknown'
            )
            A(f'- `{x["id"]}` ({x["severity"]}) — {why}')
        A('')
    A('## Passing findings')
    A('')
    for x in f:
        if x['status'] != 'pass':
            continue
        A(
            f'- `{x["id"]}` ({x["severity"]}, {x["source"]}) — '
            + '; '.join(str(s.get('reason'))[:140] for s in x['signals'])[:400]
        )
        for c in x['caveats']:
            A(f'    - ⚠ {c}')
    A('')
    A('## Cross-run memory')
    A('')
    pr = ctx['prior']
    if pr.get('trends'):
        A('| gate | passed/n | recent vs prior pass rate | last seen | trend |')
        A('|---|---|---|---|---|')
        for g in pr['trends'][:24]:
            A(
                f'| {g.get("gate")} | {g.get("passed")}/{g.get("n")} | '
                f'{g.get("recent_pass_rate")} vs {g.get("prior_pass_rate")} | '
                f'{g.get("last_seen")} | '
                f'{(g.get("shift") or "-")}'
                f'{(" (z=" + str(g.get("z")) + ")") if g.get("shift") else ""} |'
            )
    else:
        A('No prior gate history for these gate names — this run seeds it.')
    A('')
    if pr.get('lessons'):
        A('Previously recorded diagnoses for this scene:')
        A('')
        for l in pr['lessons']:
            A(f'- {l.get("ts")} `{l.get("finding")}` ({l.get("severity")}, {l.get("source")}) at t={l.get("times")}')
    else:
        A('No previously recorded diagnoses for this scene — this run seeds them.')
    A('')
    A(
        f'This run wrote {ctx["ledger_rows"]} gate rows to the run ledger and '
        f'{ctx["lesson_rows"]} lesson row(s) to `{os.path.relpath(LESSONS_PATH, _DIR)}`, '
        f"so the next analysis of this scene starts with this one's conclusions."
    )
    A('')
    A('## How this was measured (provenance)')
    A('')
    A(f'- run_id: `{ctx["run_id"]}`')
    A(f'- clip: `{ctx["clip"]}` — {ctx["w"]}x{ctx["h"]}, {ctx["fps"]:.2f} fps, {ctx["dur"]:.2f}s')
    A(f'- sampled timestamps: {ctx["times"]}')
    _tgt_desc = ', '.join('%s[%s]' % (k, v['source']) for k, v in sorted(ctx['targets'].items()))
    A(f'- targets derived: {len(ctx["targets"])} ({_tgt_desc})')
    A(
        f'- crops derived and judged: **{ctx["n_crops"]}** in `crops/` '
        f'(upscaled to >= {MIN_CROP_PX}px long edge; `crops/INDEX.json` records the '
        f'full-frame box each one was cut from)'
    )
    A(
        f'- judge (per-crop binary items): {ctx["inspect_model"]} at tier '
        f'`{ctx["inspect_tier"]}`, {ctx["n_vlm_calls"]} worker runs, '
        f'k={ctx["k_critical"]} majority vote on critical items'
    )
    A(
        f"- synthesis (this document's prose): {ctx['synth_model']} at tier "
        f'`{ctx["synth_tier"]}`'
        + (f' (FELL BACK from `{ctx["requested_tier"]}`)' if ctx['fell_back'] else '')
        + f', {ctx["synth_seconds"]}s'
    )
    A(
        f'- context-window seam times used for prop consistency: '
        f'{[p[1] for p in (ctx["pixel"].get("_seam_pairs") or [])]} '
        f'(native {NATIVE_FPS:.0f} fps, stride {CONTEXT_STRIDE_FRAMES} frames — '
        f"NOT the delivered clip's {ctx['fps']:.0f} fps)"
    )
    A(
        f'- peak GPU memory: {ctx["peak_vram_mb"]} MiB used on the whole card '
        f"during the analysis. This is the CARD total, not this job's share — the "
        f'GPU is shared (a transcriber service permanently holds ~6 GB and other '
        f'agents may co-tenant), which is why every GPU step is tier-gated rather '
        f'than assuming the card is free.'
        + (
            f" The synthesis process's own torch peak was {ctx['synth_peak_gb']} GB."
            if ctx.get('synth_peak_gb')
            else ''
        )
    )
    A(f'- wall time: {ctx["elapsed_s"]}s')
    if ctx['pixel'].get('errors'):
        A(f'- metric errors (non-fatal): {ctx["pixel"]["errors"]}')
    A('')
    A('### Bounding-box maths')
    A('')
    A(
        'Qwen3-VL emits grounding boxes as RELATIVE 0-1000 coordinates of the image '
        'it was shown, and it was shown a CROP. `vlm_worker.parse_bbox` divides by '
        '1000; this module then maps crop space to frame space with '
        '`full = crop_origin + box * crop_size` per axis. Localization passes send '
        'exactly one crop per call because the worker always grounds on `images[0]`, '
        'so a multi-crop call would attribute the box to the wrong frame.'
    )
    A('')
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        return path
    except Exception:
        return None
