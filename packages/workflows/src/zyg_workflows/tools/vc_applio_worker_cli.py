# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.vc_applio_worker`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.vc_applio_worker` still reaches it.

voice_conversion.py runs the worker as a FILE (`WORKER`) with the Applio venv's own interpreter,
where the crews package is not installed — so the one library name this needs is reached as a
sibling module there (sys.path[0] is the tools directory for a script run by path).
"""

import glob
import json
import os
import sys
import time

try:
    from zyg_workflows.tools.vc_applio_worker import _latest_weights
except ModuleNotFoundError:  # inside the Applio venv: the module sits beside this file
    from vc_applio_worker import _latest_weights


def main(argv):
    # This file lives in crews/tools; Applio's core.py is in the cwd.
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    import core

    cmd = argv[0]
    out = {'ok': False, 'cmd': cmd, 'error': ''}
    t0 = time.time()
    try:
        if cmd == 'prerequisites':
            core.run_prerequisites_script(pretraineds_hifigan=True, models=True, exe=False)
            out['ok'] = True
        elif cmd == 'train':
            model, dataset = argv[1], argv[2]
            epochs = int(argv[3]) if len(argv) > 3 else 300
            sr = int(argv[4]) if len(argv) > 4 else 40000
            cores = int(os.environ.get('VC_CPU_CORES', '16'))
            out['preprocess'] = core.run_preprocess_script(
                model_name=model,
                dataset_path=dataset,
                sample_rate=sr,
                cpu_cores=cores,
                cut_preprocess='Automatic',
                process_effects=False,
                noise_reduction=False,
                clean_strength=0.7,
                chunk_len=3.0,
                overlap_len=0.3,
            )
            out['extract'] = core.run_extract_script(
                model_name=model, f0_method='rmvpe', cpu_cores=cores, gpu=0, sample_rate=sr, embedder_model='contentvec'
            )
            out['train'] = core.run_train_script(
                model_name=model,
                save_every_epoch=max(10, epochs // 6),
                save_only_latest=True,
                save_every_weights=True,
                total_epoch=epochs,
                sample_rate=sr,
                batch_size=8,
                gpu=0,
                pretrained=True,
                cleanup=False,
                index_algorithm='Auto',
                vocoder='HiFi-GAN',
            )
            out['index'] = core.run_index_script(model_name=model, index_algorithm='Auto')
            pth, idx = _latest_weights(model)
            out.update(
                {
                    'pth': os.path.abspath(pth) if pth else None,
                    'index': os.path.abspath(idx) if idx else None,
                    'ok': bool(pth),
                }
            )
        elif cmd == 'extract':
            # The inference weights from the last G_ checkpoint. Applio's own
            # end-of-training extraction reads assets/config.json, which only its
            # GUI creates on first launch — headless, every extraction failed with
            # ENOENT while the checkpoints saved fine (2026-09-15).
            import torch
            from rvc.train.process.extract_model import extract_model
            from rvc.train.utils import HParams

            model = argv[1]
            cfg_path = os.path.join('assets', 'config.json')
            if not os.path.isfile(cfg_path):
                import shutil

                shutil.copyfile(os.path.join('assets', 'config_template.json'), cfg_path)
            gs = sorted(glob.glob(os.path.join('logs', model, 'G_*.pth')), key=os.path.getmtime)
            if not gs:
                raise RuntimeError(f'no G_ checkpoint for {model}')
            ck = torch.load(gs[-1], map_location='cpu', weights_only=True)
            hps = HParams(**json.load(open(os.path.join('logs', model, 'config.json'))))
            epoch = int(ck.get('iteration') or 0)
            steps = len(open(os.path.join('logs', model, 'filelist.txt')).read().splitlines())
            # the step count only names the file; training ran at batch 8
            step = epoch * max(1, steps // int(os.environ.get('VC_BATCH_SIZE', '8')))
            dst = os.path.join('logs', model, f'{model}_{epoch}e_{step}s.pth')
            extract_model(
                ckpt=ck['model'],
                sr=int(hps.data.sample_rate),
                name=model,
                model_path=dst,
                epoch=epoch,
                step=step,
                hps=hps,
                vocoder='HiFi-GAN',
            )
            out.update(
                {
                    'pth': os.path.abspath(dst) if os.path.isfile(dst) else None,
                    'epoch': epoch,
                    'ok': os.path.isfile(dst),
                }
            )
        elif cmd == 'convert':
            model, src, dst = argv[1], argv[2], argv[3]
            index_rate = float(argv[4]) if len(argv) > 4 else 0.5
            protect = float(argv[5]) if len(argv) > 5 else 0.33
            pth, idx = _latest_weights(model)
            # A pinned weights file (VC_PTH, a basename in logs/<model>) — the
            # pipeline pins the one the bench passed, so a retrain cannot
            # silently change the voice that ships.
            pin = os.environ.get('VC_PTH', '').strip()
            if pin:
                pth = os.path.join('logs', model, os.path.basename(pin))
                if not os.path.isfile(pth):
                    raise RuntimeError(f'pinned weights {pin} not found for {model}')
                pth = os.path.abspath(pth)
            if not pth:
                raise RuntimeError(f'no trained weights for {model}')
            os.makedirs(dst, exist_ok=True)
            done = []
            for wav in sorted(glob.glob(os.path.join(src, '*.wav'))):
                o = os.path.join(dst, os.path.basename(wav))
                core.run_infer_script(
                    pitch=0,
                    index_rate=index_rate,
                    volume_envelope=1.0,
                    protect=protect,
                    f0_method='rmvpe',
                    input_path=os.path.abspath(wav),
                    output_path=os.path.abspath(o),
                    pth_path=pth,
                    index_path=idx or '',
                    split_audio=False,
                    f0_autotune=False,
                    f0_autotune_strength=1.0,
                    proposed_pitch=False,
                    proposed_pitch_threshold=155.0,
                    clean_audio=False,
                    clean_strength=0.7,
                    export_format='WAV',
                    embedder_model='contentvec',
                )
                if os.path.isfile(o):
                    done.append(os.path.basename(o))
            out.update(
                {
                    'pth': pth,
                    'index': idx,
                    'converted': done,
                    'index_rate': index_rate,
                    'protect': protect,
                    'ok': bool(done),
                }
            )
        else:
            raise ValueError(f'unknown command {cmd}')
    except Exception as e:  # noqa: BLE001
        out['error'] = f'{type(e).__name__}: {e}'[:400]
    out['seconds'] = round(time.time() - t0, 1)
    print(json.dumps(out))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
