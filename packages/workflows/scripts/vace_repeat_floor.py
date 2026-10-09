#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Same-seed repeat floor for the VACE identity instrument (CPU only).

Reads existing receipt ledgers and re-scores NOTHING. It answers one question:
how much does the identity cosine move between two renders that differ only in
the noise draw of the sampler, and is that movement smaller than the movement
across seeds?  If it is not, seed is not a lever and every identity delta below
~2x the same-seed sd is noise.

Inputs (all ledger.json, all the `neutral` arm — no control channel):
  same-seed (seed 7): receipt A + 3 repeats rendered 2026-09-05
  across-seed        : the seed sweep 7/11/23/42/101 (seed 7 = receipt A)

Four-state ledger: an arm whose identity state is not `found` is reported as
such and excluded from the sd, with the surviving n stated.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from zyg_workflows import paths

CREWS = paths.ZYG_CREWS_ROOT
RECEIPTS = CREWS / 'output/vace_receipts'
RECEIPT_A = RECEIPTS / '2026-09-03_c3345deb5bde_registry'
REPEATS = [RECEIPTS / f'2026-09-05_c3345deb5bde_registry_repeat{r}' for r in (1, 2, 3)]
SWEEP_SEEDS = [11, 23, 42, 101]
OUT = RECEIPTS / '2026-09-05_c3345deb5bde_registry_repeat_floor'

MEASURED_STATE = 'found'


def read_arm(ledger_path: Path, label: str) -> dict:
    """Pull the neutral arm's identity block out of one ledger."""
    rec = {
        'label': label,
        'ledger': str(ledger_path),
        'ledger_exists': ledger_path.is_file(),
        'seed': None,
        'state': 'unmeasurable',
        'cosine': None,
        'cosine_min': None,
        'spread': None,
        'clip': None,
        'clip_exists': False,
        'frame_ledger': None,
        'note': '',
    }
    if not rec['ledger_exists']:
        rec['note'] = 'ledger.json missing'
        return rec
    try:
        doc = json.loads(ledger_path.read_text())
    except Exception as exc:  # a truncated ledger is unmeasurable, not zero
        rec['note'] = f'ledger unreadable: {exc}'
        return rec
    rec['seed'] = doc.get('seed')
    arm = (doc.get('arms') or {}).get('neutral')
    if not arm:
        rec['note'] = 'no neutral arm in ledger'
        return rec
    ident = arm.get('identity') or {}
    rec['state'] = ident.get('state', 'unmeasurable')
    rec['cosine'] = ident.get('cosine')
    rec['cosine_min'] = ident.get('cosine_min')
    rec['spread'] = ident.get('spread')
    rec['frame_ledger'] = (ident.get('raw') or {}).get('ledger')
    clip = arm.get('clip')
    if clip:
        p = Path(clip)
        if not p.is_absolute():
            p = CREWS / p
        rec['clip'] = str(p)
        rec['clip_exists'] = p.is_file()
        if rec['clip_exists']:
            rec['clip_bytes'] = p.stat().st_size
    if rec['state'] == MEASURED_STATE and rec['cosine'] is None:
        rec['state'] = 'unmeasurable'
        rec['note'] = 'state found but no cosine recorded'
    return rec


PROBE_FRAMES = (0, 20, 40)  # first / middle / last of a 41-frame clip


def clip_fingerprint(clip: str | None) -> dict:
    """Hash the CONTAINER and three DECODED frames.

    The two are different questions. Two mp4s always differ in their container
    bytes (muxer timestamps, encoder metadata), so a container md5 only proves
    the files are separate artefacts. Whether the renders are separate *images*
    is a question about decoded pixels, which is what PROBE_FRAMES answers.
    """
    out = {'container_md5': None, 'frames': {}, 'note': ''}
    if not clip or not Path(clip).is_file():
        out['note'] = 'clip missing'
        return out
    cp = Path(clip)
    out['container_md5'] = hashlib.md5(cp.read_bytes(), usedforsecurity=False).hexdigest()
    with tempfile.TemporaryDirectory() as td:
        for n in PROBE_FRAMES:
            png = Path(td) / f'f{n}.png'
            proc = subprocess.run(
                [
                    'ffmpeg',
                    '-nostdin',
                    '-v',
                    'error',
                    '-y',
                    '-i',
                    str(cp),
                    '-vf',
                    f'select=eq(n\\,{n})',
                    '-frames:v',
                    '1',
                    '-f',
                    'image2',
                    str(png),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0 or not png.is_file():
                out['frames'][f'frame{n}'] = None
                out['note'] = f'ffmpeg rc={proc.returncode} on frame {n}: {proc.stderr.strip()[:160]}'
                continue
            out['frames'][f'frame{n}'] = hashlib.md5(png.read_bytes(), usedforsecurity=False).hexdigest()
    out['pixel_md5'] = hashlib.md5(
        '|'.join(str(out['frames'].get(f'frame{n}')) for n in PROBE_FRAMES).encode(), usedforsecurity=False
    ).hexdigest()[:16]
    return out


def sd_block(records: list[dict], name: str) -> dict:
    """Sample sd over the measurable arms only; the rest are named, not dropped."""
    good = [r for r in records if r['state'] == MEASURED_STATE and r['cosine'] is not None]
    excluded = [{'label': r['label'], 'state': r['state'], 'note': r['note']} for r in records if r not in good]
    vals = [float(r['cosine']) for r in good]
    blk = {
        'name': name,
        'n_arms': len(records),
        'n_measured': len(good),
        'excluded': excluded,
        'cosines': {r['label']: round(float(r['cosine']), 4) for r in good},
        'mean': round(statistics.fmean(vals), 4) if vals else None,
        'sd': round(statistics.stdev(vals), 4) if len(vals) >= 2 else None,
        'sd_ddof0': round(statistics.pstdev(vals), 4) if len(vals) >= 2 else None,
        'min': round(min(vals), 4) if vals else None,
        'max': round(max(vals), 4) if vals else None,
        'range': round(max(vals) - min(vals), 4) if vals else None,
    }
    return blk


def main() -> int:
    same: list[dict] = [read_arm(RECEIPT_A / 'ledger.json', 'seed7_receiptA')]
    for i, d in enumerate(REPEATS, start=1):
        same.append(read_arm(d / 'ledger.json', f'seed7_repeat{i}'))

    across: list[dict] = [same[0]]  # seed 7 is receipt A itself
    for s in SWEEP_SEEDS:
        across.append(read_arm(RECEIPTS / f'2026-09-03_c3345deb5bde_registry_seed{s}' / 'ledger.json', f'seed{s}'))

    # fingerprint every seed-7 clip: container bytes AND decoded pixels
    frames = {}
    for r in same:
        frames[r['label']] = clip_fingerprint(r.get('clip'))
        r['container_md5'] = frames[r['label']]['container_md5']
        r['pixel_md5'] = frames[r['label']].get('pixel_md5')
    containers = [v['container_md5'] for v in frames.values() if v['container_md5']]
    pixels = [v.get('pixel_md5') for v in frames.values() if v.get('pixel_md5')]
    containers_distinct = len(set(containers)) == len(containers) and len(containers) > 1
    n_pixel_groups = len(set(pixels))
    pixel_groups = {}
    for lab, v in frames.items():
        pixel_groups.setdefault(v.get('pixel_md5'), []).append(lab)

    same_blk = sd_block(same, 'same_seed_seed7')
    across_blk = sd_block(across, 'across_seed_7_11_23_42_101')

    ratio = None
    if same_blk['sd'] and across_blk['sd']:
        ratio = round(across_blk['sd'] / same_blk['sd'], 3)

    good_same = [r for r in same if r['state'] == MEASURED_STATE and r['cosine'] is not None]
    same_vals = [float(r['cosine']) for r in good_same]
    max_excursion = round(max(same_vals) - min(same_vals), 4) if len(same_vals) >= 2 else None

    if ratio is None:
        reading = (
            "UNDECIDED: one of the two sd's could not be computed "
            f'(same n={same_blk["n_measured"]}, across n={across_blk["n_measured"]}).'
        )
    elif ratio <= 2.0:
        reading = (
            f'SEED IS NOT A LEVER: across-seed sd is only {ratio}x the same-seed sd '
            f'({across_blk["sd"]} vs {same_blk["sd"]}) — the seed sweep measured the '
            f"sampler's noise, not the seed. Any identity delta below "
            f'{round(2 * same_blk["sd"], 4)} (2x same-seed sd) is noise.'
        )
    else:
        reading = (
            f'SEED CARRIES SIGNAL: across-seed sd is {ratio}x the same-seed sd '
            f'({across_blk["sd"]} vs {same_blk["sd"]}) — seed moves identity beyond the '
            f'render-to-render floor. Any identity delta below '
            f'{round(2 * same_blk["sd"], 4)} (2x same-seed sd) is still noise.'
        )

    shape = f'{n_pixel_groups} distinct pixel outcome(s) across {len(pixels)} seed-7 renders: ' + '; '.join(
        f'[{", ".join(v)}]' for v in pixel_groups.values()
    )
    if n_pixel_groups == 1:
        det = (
            'The sampler is bit-deterministic at a fixed seed: every seed-7 render decoded to '
            'identical pixels, so the same-seed sd is exactly 0 and the whole spread in the '
            'seed sweep is the seed.'
        )
    elif n_pixel_groups < len(pixels):
        det = (
            'The sampler is MOSTLY deterministic at a fixed seed but not always: '
            f'{shape}. The same-seed sd of {same_blk["sd"]} is therefore NOT a gaussian '
            'width — it is driven entirely by the render(s) that diverged, and the floor is '
            f'better read as its max excursion, {max_excursion}. Treat any identity delta '
            f'below {max_excursion} as within the render-to-render floor.'
        )
    else:
        det = (
            f'Every seed-7 render decoded to different pixels ({shape}); the same-seed sd of '
            f'{same_blk["sd"]} is a genuine render-to-render width.'
        )

    doc = {
        'schema': 'vace_repeat_floor/2',
        'generated': __import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'),
        'char_id': 'c3345deb5bde',
        'arm': 'neutral (no control channel)',
        'config': '480x704, 41 frames, 30 steps, receipt-A still/mask/LoRA',
        'same_seed_arms': same,
        'across_seed_arms': across,
        'same_seed': same_blk,
        'across_seed': across_blk,
        'noise_floor_cosine_sd': same_blk['sd'],
        'noise_threshold_2sd': round(2 * same_blk['sd'], 4) if same_blk['sd'] else None,
        'ratio_across_over_same': ratio,
        'clip_fingerprints': frames,
        'containers_all_distinct': containers_distinct,
        'n_distinct_pixel_outcomes': n_pixel_groups,
        'pixel_groups': {k: v for k, v in pixel_groups.items()},
        'max_same_seed_excursion': max_excursion,
        'determinism_reading': det,
        'reading': reading,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'floor.json').write_text(json.dumps(doc, indent=2) + '\n')

    L = []
    L.append('# Same-seed repeat floor — identity instrument (neutral arm)\n')
    L.append(f'Generated {doc["generated"]} · char c3345deb5bde · {doc["config"]}\n')
    L.append('Reads ledgers only; nothing was re-scored.\n')
    L.append('\n## 1. Per-render identity (seed 7, four renders of the same config)\n\n')
    L.append('| render | state | cosine | cosine_min | spread | container md5 | pixel md5 (frames 0/20/40) |\n')
    L.append('|---|---|---|---|---|---|---|\n')
    for r in same:
        L.append(
            f'| {r["label"]} | {r["state"]} | {r["cosine"]} | {r["cosine_min"]} | '
            f'{r["spread"]} | {(r.get("container_md5") or "n/a")[:12]} | '
            f'{(r.get("pixel_md5") or "n/a")[:12]} |\n'
        )
    L.append(
        f'\nAll four are separate files (distinct container md5): **{containers_distinct}**. '
        f'Distinct *decoded* outcomes: **{n_pixel_groups}** of {len(pixels)}.\n\n'
    )
    for pm, labs in pixel_groups.items():
        L.append(f'- pixel group `{(pm or "n/a")[:12]}`: {", ".join(labs)}\n')
    for lab, f in frames.items():
        if f['note']:
            L.append(f'- {lab}: {f["note"]}\n')
    L.append(f'\n{det}\n')

    L.append('\n## 2. SAME-SEED sd — the floor\n\n')
    L.append(
        f'n measured = {same_blk["n_measured"]} of {same_blk["n_arms"]}; '
        f'mean {same_blk["mean"]}, sd {same_blk["sd"]}, range {same_blk["range"]} '
        f'({same_blk["min"]}..{same_blk["max"]})\n'
    )
    if same_blk['excluded']:
        L.append('Excluded (four-state ledger):\n')
        for e in same_blk['excluded']:
            L.append(f'- {e["label"]}: {e["state"]} — {e["note"] or "no cosine"}\n')

    L.append('\n## 3. ACROSS-SEED sd — the seed sweep\n\n')
    L.append(
        f'seeds 7/11/23/42/101, n measured = {across_blk["n_measured"]} of '
        f'{across_blk["n_arms"]}; mean {across_blk["mean"]}, sd {across_blk["sd"]}, '
        f'range {across_blk["range"]} ({across_blk["min"]}..{across_blk["max"]})\n'
    )
    if across_blk['excluded']:
        L.append('Excluded (four-state ledger):\n')
        for e in across_blk['excluded']:
            L.append(f'- {e["label"]}: {e["state"]} — {e["note"] or "no cosine"}\n')

    L.append('\n## 4. Ratio and reading\n\n')
    L.append(f'across-seed sd / same-seed sd = **{ratio}**\n\n')
    L.append(f'{reading}\n\n')
    L.append(f'Max same-seed excursion (max-min cosine over the seed-7 renders): **{max_excursion}**\n')
    (OUT / 'FLOOR.md').write_text(''.join(L))

    print(
        json.dumps(
            {
                'same_seed_sd': same_blk['sd'],
                'across_seed_sd': across_blk['sd'],
                'ratio': ratio,
                'n_same': same_blk['n_measured'],
                'n_across': across_blk['n_measured'],
                'n_pixel_outcomes': n_pixel_groups,
                'max_same_seed_excursion': max_excursion,
                'out': str(OUT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
