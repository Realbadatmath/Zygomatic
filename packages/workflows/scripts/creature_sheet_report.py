#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_sheet_report.py — self-contained HTML review page for a creature sheet.

    .venv/bin/python scripts/creature_sheet_report.py <dataset_dir> [-o out.html]

Reads <dataset_dir>/contact_sheet/sheet.json (+ brief.json, manifest.json) and
embeds the labelled sheet, the reference/anchors and every cell with its three
verdicts (structural / DINOv2 / Qwen3-VL, with the judge's own reasons) as data
URIs, so the page can be published as an Artifact and inspected anywhere.
Images are re-encoded to keep the page well under the 16 MB artifact cap.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import sys

from PIL import Image
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)


def _data_uri(path: str, max_w: int, quality: int = 84) -> str:
    if not path or not os.path.isfile(path):
        return ''
    im = Image.open(path).convert('RGB')
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format='JPEG', quality=quality, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def _esc(x) -> str:
    return html.escape('' if x is None else str(x))


def _fmt(x) -> str:
    return f'{x:.2f}' if isinstance(x, (int, float)) else 'n/a'


def build(dataset_dir: str) -> str:
    sheet_dir = os.path.join(dataset_dir, 'contact_sheet')
    rep = json.load(open(os.path.join(sheet_dir, 'sheet.json'), encoding='utf-8'))
    brief = {}
    try:
        brief = json.load(open(os.path.join(dataset_dir, 'brief.json'), encoding='utf-8'))
    except Exception:
        brief = rep.get('brief') or {}
    state = {}
    cid = os.path.basename(dataset_dir.rstrip('/'))
    try:
        state = json.load(open(os.path.join(_CREWS, 'data', 'runtime', f'creature_gen_{cid}.json'), encoding='utf-8'))
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    cells = rep.get('cells') or []
    n_ok = sum(1 for c in cells if c.get('ok'))
    judged = bool(rep.get('judged_any'))
    tier = next((c.get('judge_tier') for c in cells if c.get('judge_tier')), None)
    name = brief.get('name') or rep.get('brief', {}).get('name') or 'Creature'
    ident = (rep.get('identity') or {}).get('model') or 'n/a'
    src = rep.get('source', '')
    anchors = rep.get('anchors') or {}
    refs = rep.get('refs') or []

    sheet_uri = _data_uri(rep.get('sheet_path'), 1800, 82)
    ref_uri = _data_uri((anchors.get('identity') or {}).get('path'), 520)
    full_uri = _data_uri((anchors.get('full_body') or {}).get('path'), 520)
    full_from = (anchors.get('full_body') or {}).get('from', '')
    side = anchors.get('side') or {}
    side_uri = _data_uri(side.get('path'), 520)
    body_plan = brief.get('body_plan') or rep.get('brief', {}).get('body_plan') or ''
    locks = brief.get('anchor_locks') or rep.get('brief', {}).get('anchor_locks') or {}

    # operator candidates (scripts/creature_variants.py): one card per variant,
    # the locked one highlighted, the lock command under each so a re-pick is one line
    variants_html = ''
    vroot = os.path.join(sheet_dir, 'variants')
    lock_names = {k: os.path.basename(str(v)) for k, v in (locks or {}).items() if v}
    if os.path.isdir(vroot):
        blocks = []
        for vname in sorted(os.listdir(vroot)):
            vj = os.path.join(vroot, vname, 'variants.json')
            if not os.path.isfile(vj):
                continue
            vs = json.load(open(vj, encoding='utf-8'))
            kind = 'side' if vs.get('band') == 'side' else 'full_body'
            flag = '--side' if kind == 'side' else '--full'
            prefix = vs.get('prefix') or ''
            cards = ''
            for tag, r in (vs.get('variants') or {}).items():
                best = (r.get('candidates') or [{}])[0] if r.get('candidates') else {}
                img = _data_uri(best.get('path'), 640, 82)
                if not img:
                    continue
                locked = lock_names.get(kind) == f'{kind}_{os.path.basename(str(best.get("path") or ""))}'
                ok = bool(best.get('ok'))
                soft = best.get('soft') or []
                text = str(r.get('instruction') or '')
                if prefix and text.startswith(prefix):
                    text = text[len(prefix) :]
                text = text.strip()
                cards += f'''<article class="pick {'locked' if locked else ''}">
  <img src="{img}" alt="variant {_esc(tag)}">
  <header><span class="letter">{_esc(tag)}</span><span class="pill {'bad' if not ok else ('soft' if soft else 'ok')}">{'FLAGGED' if not ok else ('PASS*' if soft else 'PASS')}</span>{'<span class="locktag">LOCKED · in the sheet</span>' if locked else ''}</header>
  <p class="desc">{_esc(text[:200])}</p>
  <p class="meta">DINOv2 {_fmt(best.get('dino'))} vs reference{(' · judge flags: ' + _esc(', '.join(best.get('flags') or []))) if best.get('flags') else ''} · {_esc(os.path.basename(str(best.get('path') or '')))}</p>
  {'<p class="meta">Rotation source of the side, back and top cells.</p>' if locked else f'<div class="mono cmd">scripts/creature_lock.py {_esc(cid)} {flag} {_esc(best.get("path"))}<br>scripts/creature_worker.py --resume {_esc(cid)} --phase sheet</div>'}
</article>'''
            if cards:
                blocks.append(
                    f'<h3 class="pickhead">{_esc(vs.get("label") or vname)}</h3>'
                    f'<p class="meta">Edited from {_esc(os.path.basename(str(vs.get("source") or "")))} with the angles LoRA off, {_esc(vs.get("seeds"))} seed(s) per variant, judged against the reference; the best seed of each is shown. '
                    + (
                        'Lock a different one and re-run: only the cells rotated from it re-render.'
                        if kind == 'side'
                        else 'Lock a different one and re-run: every cell edited from the front anchor re-renders.'
                    )
                    + f'</p><div class="picks">{cards}</div>'
                )
        if blocks:
            variants_html = '<section class="section"><h2>Operator picks</h2>' + ''.join(blocks) + '</section>'

    # the previous sheet (archived by the operator before a re-run) for a before/after
    prev_html = ''
    import glob as _glob

    prevs = sorted(_glob.glob(os.path.join(dataset_dir, 'contact_sheet_prev_*', 'sheet.png')))
    if prevs:
        prev_uri = _data_uri(prevs[-1], 1400, 78)
        if prev_uri:
            prev_html = (
                f'<details class="prev"><summary>Previous sheet ({_esc(os.path.basename(os.path.dirname(prevs[-1])))}) — before the body-plan lock</summary>'
                f'<div class="sheet"><img src="{prev_uri}" alt="previous contact sheet"></div></details>'
            )

    def cell_card(c: dict) -> str:
        thumb = _data_uri(c.get('path'), 360, 80)
        ok = bool(c.get('ok'))
        dino = c.get('dino')
        dv = c.get('dino_verdict') or {}
        st = c.get('structural') or {}
        v_rows = ''
        for v in c.get('verdicts') or []:
            a = v.get('answer')
            vok = v.get('ok')
            cls = 'q-unk' if vok is None else ('q-ok' if vok else 'q-bad')
            v_rows += (
                f'<tr class="{cls}"><td class="qid">{_esc(v.get("id"))}</td>'
                f'<td>{_esc(a)}</td><td class="mono">{_esc(v.get("expected"))}</td>'
                f'<td class="reason">{_esc((v.get("reason") or "")[:220])}'
                + (f' <em>error: {_esc(v.get("error"))}</em>' if v.get('error') else '')
                + (f' <em>raw: {_esc(v.get("raw"))}</em>' if v.get('raw') else '')
                + '</td></tr>'
            )
        hist = c.get('history') or []
        hist_txt = ''
        if hist:
            hist_txt = (
                '<p class="hist">Regenerated: '
                + ' → '.join(
                    f'r{h.get("attempt", 0)} {"ok" if h.get("ok") else ",".join(h.get("reasons") or [])} (dino {_fmt(h.get("dino"))})'
                    for h in hist
                )
                + f' → r{c.get("attempt", 0)} kept</p>'
            )
        reasons = ', '.join(c.get('reasons') or [])
        soft = ', '.join(c.get('soft') or [])
        warn = ', '.join(c.get('warnings') or [])
        mode = c.get('caption_mode') or 'angle'
        soft_txt = {
            'neutral': 'kept with an angle-neutral caption (the view did not come out as asked)',
            'partial': 'kept with a partial-view caption (body cut by the frame)',
            'neutral_partial': 'kept with an angle-neutral, partial-view caption',
        }.get(mode, '')
        judge_line = (
            'VLM judge: ' + ('PASS' if not [r for r in (c.get('reasons') or []) if r.startswith('vlm:')] else 'FLAGGED')
            if c.get('judged')
            else 'VLM judge: offline (' + _esc(c.get('judge_offline') or 'not run') + ')'
        )
        dino_line = (
            (
                f'DINOv2 {_fmt(dino)} (floor {_fmt(dv.get("floor"))}, band {_esc(c.get("band"))})'
                + ('' if dv.get('soft_ok', True) else ' — below soft floor')
            )
            if dv.get('measured')
            else 'DINOv2 not measured'
        )
        struct_line = (
            ('structural ok' if st.get('ok', True) else 'structural: ' + ', '.join(st.get('reasons') or []))
            + (f' · std {st.get("std")}' if st.get('std') is not None else '')
            + (f' · Δphash vs anchor {st.get("phash_anchor")}' if st.get('phash_anchor') is not None else '')
        )
        return f"""
<article class="cell {'excluded' if not ok else ('soft' if soft else 'pass')}">
  <div class="thumb">{f'<img src="{thumb}" alt="{_esc(c.get("label"))}">' if thumb else '<div class="missing">no image</div>'}</div>
  <div class="body">
    <header><span class="idx">{int(c.get('idx', 0)):02d}</span><h3>{_esc(c.get('label'))}</h3>
      <span class="pill {'bad' if not ok else ('soft' if soft else 'ok')}">{'EXCLUDED' if not ok else ('PASS* — trains' if soft else 'PASS — trains')}</span></header>
    <p class="meta">{_esc(judge_line)} · {_esc(dino_line)} · {_esc(struct_line)}</p>
    {f'<p class="why">Why excluded: {_esc(reasons)}</p>' if not ok else ''}
    {f'<p class="warn">{_esc(soft_txt)} — judge flags: {_esc(soft)}</p>' if (ok and soft) else ''}
    {f'<p class="warn">Warning: {_esc(warn)}</p>' if warn else ''}
    {hist_txt}
    <details><summary>Judge answers ({len(c.get('verdicts') or [])})</summary>
      <div class="scroll"><table><thead><tr><th>check</th><th>answer</th><th>expected</th><th>judge's reason</th></tr></thead>
      <tbody>{v_rows or '<tr><td colspan="4">no verdicts recorded</td></tr>'}</tbody></table></div></details>
    <p class="path mono">{_esc(os.path.relpath(c.get('path') or '', dataset_dir))} · seed {_esc(c.get('seed'))} · edited from {_esc(os.path.basename(c.get('source_anchor') or ''))}</p>
  </div>
</article>"""

    ref_rows = ''
    for i, r in enumerate(refs):
        flags = ', '.join(r.get('flags') or [])
        ref_rows += (
            f'<li><span class="mono">ref_{i:02d}</span> {_esc(os.path.basename(r.get("src") or ""))} — '
            + ('judged: ' + ('clean' if not flags else 'flagged ' + _esc(flags)) if r.get('judged') else 'not judged')
            + (', whole body visible' if r.get('whole_body') else ', partial view')
            + '</li>'
        )
    agree = rep.get('refs_agreement')
    agree_txt = f' · reference agreement (DINO) min {_fmt(agree.get("min"))}' if agree else ''

    status = state.get('status', '')
    approve = f"""<div class="next">
  <strong>Review gate.</strong> Run <span class="mono">{_esc(cid)}</span> is <span class="mono">{_esc(status or 'on disk')}</span>.
  Approve trains a FLUX.2 klein-4B LoRA on the {n_ok} passing cells + {len(refs)} reference(s); reject leaves the dataset on disk and trains nothing.
  <div class="mono cmd">scripts/run_creature_sheet.py --approve {_esc(cid)}<br>scripts/run_creature_sheet.py --reject {_esc(cid)} --reason "…"</div>
</div>"""

    judge_note = (
        f'Qwen3-VL judge ran ({_esc(tier)} tier)' if judged else 'JUDGE OFFLINE — verdicts are structural + DINOv2 only'
    )
    return f"""<title>{_esc(name)} Sheet Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--bg:#F2F5F4;--surface:#FFFFFF;--surface2:#E7EDEB;--ink:#1C2422;--muted:#5B6966;--line:#CFD9D6;--accent:#1F8F86;--accent-ink:#0E5C56;--ok:#2E8B57;--bad:#C6423D;--warn:#B8791C;--unk:#8A94A3}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#111716;--surface:#182120;--surface2:#1F2B29;--ink:#E4ECEA;--muted:#9AAAA6;--line:#2B3A37;--accent:#3FB8AE;--accent-ink:#8EDDD5;--ok:#5FC585;--bad:#E4736E;--warn:#E0A64A;--unk:#8A94A3}}}}
:root[data-theme="dark"]{{--bg:#111716;--surface:#182120;--surface2:#1F2B29;--ink:#E4ECEA;--muted:#9AAAA6;--line:#2B3A37;--accent:#3FB8AE;--accent-ink:#8EDDD5;--ok:#5FC585;--bad:#E4736E;--warn:#E0A64A;--unk:#8A94A3}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15px;line-height:1.5}}
.wrap{{max-width:1280px;margin:0 auto;padding:28px 24px 64px}}
h1,h2,h3{{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;text-wrap:balance;margin:0}}
h1{{font-size:clamp(28px,4vw,40px);font-weight:700;letter-spacing:-.01em}}
h2{{font-size:20px;font-weight:700;margin:0 0 12px}}
h3{{font-size:16px;font-weight:600}}
.eyebrow{{font-family:"IBM Plex Mono",monospace;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}
.mono{{font-family:"IBM Plex Mono",monospace;font-size:12.5px;font-variant-numeric:tabular-nums}}
.hero{{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:end;margin-bottom:18px}}
.chips{{display:flex;gap:8px;flex-wrap:wrap}}
.chip{{padding:6px 10px;border-radius:6px;background:var(--surface2);font-family:"IBM Plex Mono",monospace;font-size:12.5px;border:1px solid var(--line)}}
.chip.ok{{color:var(--ok);border-color:var(--ok)}} .chip.bad{{color:var(--bad);border-color:var(--bad)}} .chip.warn{{color:var(--warn);border-color:var(--warn)}}
.brief{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:0 0 22px;display:grid;grid-template-columns:2fr 1fr;gap:14px}}
.brief p{{margin:0 0 6px}} .brief ul{{margin:6px 0 0 18px;padding:0}}
.sheet{{border:1px solid var(--line);border-radius:8px;background:var(--surface);padding:10px;overflow-x:auto;margin-bottom:22px}}
.sheet img{{display:block;max-width:100%;height:auto;border-radius:4px}}
.anchors{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:26px}}
.anchor{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px}}
.anchor img{{width:100%;height:auto;border-radius:4px;display:block}} .anchor p{{margin:8px 0 0;font-size:13px;color:var(--muted)}}
.cells{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}}
.cell{{display:grid;grid-template-columns:132px 1fr;gap:12px;background:var(--surface);border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:8px;padding:10px;min-width:0}}
.cell.excluded{{border-left-color:var(--bad)}} .cell.soft{{border-left-color:var(--warn)}} .pill.soft{{color:var(--warn);border-color:var(--warn)}}
.thumb img{{width:132px;height:132px;object-fit:cover;border-radius:4px;display:block}} .missing{{width:132px;height:132px;display:grid;place-items:center;background:var(--surface2);color:var(--muted);border-radius:4px}}
.cell header{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}} .idx{{font-family:"IBM Plex Mono",monospace;color:var(--muted)}}
.pill{{margin-left:auto;font-family:"IBM Plex Mono",monospace;font-size:11.5px;padding:3px 8px;border-radius:999px;border:1px solid}} .pill.ok{{color:var(--ok);border-color:var(--ok)}} .pill.bad{{color:var(--bad);border-color:var(--bad)}}
.meta,.path,.hist{{margin:6px 0 0;font-size:12.5px;color:var(--muted)}} .why{{margin:6px 0 0;color:var(--bad);font-weight:500}} .warn{{margin:6px 0 0;color:var(--warn)}}
details{{margin-top:8px}} summary{{cursor:pointer;color:var(--accent-ink);font-weight:500}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}} th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);vertical-align:top}} th{{color:var(--muted);font-weight:500}}
.q-ok td.qid{{color:var(--ok)}} .q-bad td.qid{{color:var(--bad);font-weight:600}} .q-unk td.qid{{color:var(--unk)}} .reason{{color:var(--muted)}}
.picks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin-bottom:18px}}
.pick{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:8px;min-width:0}}
.pick.locked{{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}}
.pick img{{width:100%;height:auto;border-radius:4px;display:block}}
.pick header{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}} .pick .pill{{margin-left:0}}
.letter{{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;font-size:24px;font-weight:700;color:var(--accent-ink);line-height:1}}
.locktag{{margin-left:auto;font-family:"IBM Plex Mono",monospace;font-size:11.5px;letter-spacing:.06em;color:var(--accent-ink)}}
.pick .desc{{margin:0;font-size:13.5px}} .pick .cmd{{margin-top:auto;font-size:11.5px}}
.pickhead{{margin:14px 0 4px}} details.prev{{margin-bottom:22px}} details.prev summary{{margin-bottom:10px}}
.next{{margin:26px 0 0;padding:14px 16px;border:1px solid var(--accent);border-radius:8px;background:var(--surface)}} .cmd{{margin-top:8px;padding:8px 10px;background:var(--surface2);border-radius:6px;overflow-x:auto}}
ul.refs{{margin:0;padding-left:18px}} .section{{margin-bottom:26px}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
</style>
<div class="wrap">
  <div class="hero">
    <div><div class="eyebrow">Creature sheet · {_esc(src)} mode · {_esc(cid)}</div><h1>{_esc(name)}</h1></div>
    <div class="chips">
      <span class="chip {'ok' if n_ok == len(cells) else ('warn' if n_ok >= len(cells) * 0.6 else 'bad')}">{n_ok}/{len(cells)} cells train</span>
      {f'<span class="chip warn">{sum(1 for c in cells if c.get("ok") and c.get("soft"))} kept with neutral/partial captions</span>' if any(c.get('ok') and c.get('soft') for c in cells) else ''}
      <span class="chip {'ok' if judged else 'bad'}">{_esc(judge_note)}</span>
      <span class="chip">identity: {_esc(ident)}</span>
      <span class="chip">{_esc(rep.get('seconds'))} s</span>
    </div>
  </div>
  <div class="brief">
    <div><p><strong>{_esc(brief.get('species') or 'creature')}</strong> — {_esc(brief.get('description'))}</p>
      <p class="mono">traits: {_esc(brief.get('visual_traits'))}</p>
      <p class="mono">style: {_esc(brief.get('style_hint') or '—')} · brief from {_esc(brief.get('brief_source') or '—')}</p>
      {f'<p class="mono">body plan (locked): {_esc(body_plan)}</p>' if body_plan else ''}
      {f'<p class="mono">anchor locks: {_esc(", ".join(f"{k} ← {os.path.basename(str(v))}" for k, v in locks.items() if v))}</p>' if locks else ''}</div>
    <div><div class="eyebrow">References</div><ul class="refs">{ref_rows or '<li>none (from scratch)</li>'}</ul><p class="mono">{_esc(agree_txt.strip(' ·'))}</p></div>
  </div>
  <section class="section"><h2>Labelled sheet</h2>
    <p class="meta">Green frame = passes all three judges and trains with its view caption. Amber frame (PASS*) = same creature, but the judge says the view or framing is not what was asked — it trains with an angle-neutral / partial-view caption so the caption does not lie. Red frame = EXCLUDED (different creature, second creature, human, broken anatomy or text). Cell 00 is the full-body anchor itself; every other cell is a Qwen-Image-Edit camera rotation of an anchor.</p>
    <div class="sheet">{f'<img src="{sheet_uri}" alt="labelled contact sheet">' if sheet_uri else '<p>sheet missing</p>'}</div></section>
  <section class="section"><h2>Anchors</h2><div class="anchors">
    <div class="anchor">{f'<img src="{ref_uri}" alt="identity anchor">' if ref_uri else ''}<p><strong>Identity anchor</strong> — {_esc((anchors.get('identity') or {}).get('from'))}. Every strip's LEFT panel; every close-up edits this.</p></div>
    <div class="anchor">{f'<img src="{full_uri}" alt="full-body anchor">' if full_uri else ''}<p><strong>Full-body anchor</strong> — {_esc(full_from)}. Every body/wide/top cell edits this{' (except the side/back/top cells, which rotate from the side anchor)' if side else ''}. {'Derived from the reference by edit and judged against it.' if full_from == 'edit_of_reference' else ''}</p></div>
    {f'<div class="anchor"><img src="{side_uri}" alt="side anchor"><p><strong>Side anchor</strong> — {_esc(side.get("from"))}. Rotation source of {_esc(", ".join(side.get("cells") or []))}; the left profile is its mirror. DINO vs full-body anchor {_fmt(side.get("dino_vs_full"))}.</p></div>' if side_uri else ''}
  </div></section>
  {variants_html}
  {prev_html}
  <section class="section"><h2>Cells</h2><div class="cells">{''.join(cell_card(c) for c in cells)}</div></section>
  {approve}
</div>
"""


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dataset_dir')
    ap.add_argument('-o', '--out', default='')
    a = ap.parse_args()
    page = build(a.dataset_dir)
    out = a.out or os.path.join(a.dataset_dir, 'contact_sheet', 'review.html')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(page)
    print(f'{out} ({os.path.getsize(out) / 1024 / 1024:.1f} MB)')
