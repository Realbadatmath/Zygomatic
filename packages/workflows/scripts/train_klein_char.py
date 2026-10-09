#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""train_klein_char.py — train one character LoRA on FLUX.2 [klein] 4B and wait.

    python3 scripts/train_klein_char.py 0015c8a3f2e3            # Cornelis
    python3 scripts/train_klein_char.py <char_id> --steps 1092

Drives lora_trainer_service exactly as the GUI would (start_training +
get_status polling), so the run exercises the production trainer path — the
family dispatch, the VRAM pre-flight, the status files, the alpha stamp, the
bible update — not a hand-rolled SimpleTuner invocation that would prove only
that SimpleTuner works.

The process must stay alive: the trainer runs in a daemon thread of THIS
interpreter. Exiting early kills the run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)
os.chdir(CREWS)

_VENV_DIR = os.path.join(os.path.dirname(CREWS), '.venv')
_VENV_PY = os.path.join(_VENV_DIR, 'bin', 'python')
if (
    os.path.exists(_VENV_PY)
    and os.path.abspath(sys.prefix) != os.path.abspath(_VENV_DIR)
    and not os.environ.get('ZYG_TEST_NO_REEXEC')
):
    print(f'[re-exec] {sys.executable} -> {_VENV_PY}', flush=True)
    os.execv(_VENV_PY, [_VENV_PY, '-u', os.path.abspath(__file__)] + sys.argv[1:])  # noqa: S606  re-exec under the venv interpreter: no shell, argv is this file's own


def _load_env() -> None:
    for cand in (
        os.path.join(os.path.dirname(os.path.dirname(CREWS)), '.env'),
        os.path.join(os.path.dirname(CREWS), '.env'),
    ):
        if not os.path.isfile(cand):
            continue
        with open(cand, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))
        return


_load_env()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--family', default='klein')
    ap.add_argument('--steps', type=int, default=0, help='0 = epoch-scaled default')
    ap.add_argument('--dataset', default='')
    ap.add_argument('--poll', type=int, default=30)
    a = ap.parse_args()

    from zyg_workflows import lora_trainer_service as lts
    from zyg_workflows import licence_provenance as lp

    cid = a.char_id.strip().lower()
    dataset = a.dataset or os.path.join(lts._DATASET_ROOT, cid, 'training')
    if not os.path.isdir(dataset):
        print(f'dataset dir missing: {dataset}')
        return 2
    n_img = sum(1 for f in os.listdir(dataset) if f.lower().endswith(('.png', '.jpg', '.jpeg')))
    print(f'char {cid}  family {a.family}  dataset {dataset}  ({n_img} images)', flush=True)

    tr = lts.get_trainer()
    kw = dict(model_family=a.family, cleanup_after=True)
    if a.steps:
        kw['total_steps'] = a.steps
    tr.start_training(cid, dataset, **kw)
    res = lts.last_start_result(cid)
    print('start_training ->', json.dumps(res), flush=True)
    if not res.get('started'):
        print(f'REFUSED: {res.get("reason")}')
        return 3

    out_dir = os.path.join(lts._OUTPUT_ROOT, cid)
    cfg_path = os.path.join(out_dir, f'st_config_{a.family}', 'config.json')

    # Surface the emitted config early — a wrong key here fails 60 s in, and
    # the failure text SimpleTuner prints is rarely about the key.
    for _ in range(40):
        if os.path.isfile(cfg_path):
            break
        time.sleep(1)
    if os.path.isfile(cfg_path):
        cfg = json.load(open(cfg_path))
        keep = (
            '--model_family',
            '--model_flavour',
            '--pretrained_model_name_or_path',
            '--lora_rank',
            '--lora_alpha',
            '--max_train_steps',
            '--learning_rate',
            '--base_model_precision',
            '--text_encoder_1_precision',
            '--resolution',
            '--flow_schedule_auto_shift',
            '--validation_guidance',
        )
        print('config:', json.dumps({k: cfg.get(k) for k in keep}, indent=1), flush=True)
        bad = [k for k in cfg if 'flux_guidance' in k or 'pretrained_text_encoder' in k]
        if bad:
            print('WARNING: keys that must be absent for klein are present:', bad, flush=True)

    t0 = time.time()
    last = -1
    while True:
        st = tr.get_status(cid, model_family=a.family)
        step, total = int(st.get('step') or 0), int(st.get('total_steps') or 0)
        if step != last:
            el = time.time() - t0
            rate = (el / step) if step else 0
            eta = (total - step) * rate if step else 0
            print(
                f'[{time.strftime("%H:%M:%S")}] step {step}/{total}  '
                f'{el / 60:.1f} min elapsed  eta {eta / 60:.0f} min  status={st.get("status")}',
                flush=True,
            )
            last = step
        if st.get('failed'):
            print('FAILED:', st.get('error'), flush=True)
            tail = st.get('log_tail') or []
            for l in tail[-15:]:
                print('   ', l.rstrip()[:200])
            return 4
        if st.get('done'):
            break
        time.sleep(a.poll)

    lora = st.get('lora_path')
    print(f'\nDONE in {(time.time() - t0) / 60:.1f} min -> {lora}', flush=True)
    if not lora or not os.path.isfile(lora):
        print('no LoRA file on disk')
        return 5
    print('size:', f'{os.path.getsize(lora) / 1e6:.1f} MB')

    # alpha stamped? (loaders apply 2x without it — project_lora_alpha_loss)
    try:
        from safetensors import safe_open

        with safe_open(lora, 'pt') as fh:
            keys = list(fh.keys())
        n_alpha = sum(1 for k in keys if k.endswith('.alpha'))
        n_a = sum(1 for k in keys if k.endswith('.lora_A.weight'))
        print(
            f'keys: {len(keys)}  lora_A: {n_a}  alpha: {n_alpha}  '
            f'{"STAMPED" if n_alpha == n_a and n_a else "NOT STAMPED"}'
        )
        print('sample key:', next((k for k in keys if 'lora_A' in k), '?'))
    except Exception as exc:
        print('alpha check failed:', exc)

    # licence: the whole point of the family
    try:
        c = lp.classify_weight(os.path.basename(lora), kind='lora', path=lora)
        print('licence:', {k: c.get(k) for k in ('status', 'licence', 'base_family')})
    except Exception as exc:
        print('licence check failed:', exc)

    # bible
    try:
        from zyg_workflows import character_bible_service as cbs

        cond = (cbs.load(cid) or {}).get('conditioning') or {}
        print('bible klein_lora_path:', cond.get('klein_lora_path'))
        print(
            'bible model_family (must be untouched):',
            cond.get('model_family'),
            '| lora_path (must be untouched):',
            (cond.get('lora_path') or '')[-50:],
        )
    except Exception as exc:
        print('bible check failed:', exc)
    return 0


if __name__ == '__main__':
    sys.exit(main())
