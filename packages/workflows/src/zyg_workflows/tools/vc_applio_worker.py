# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vc_applio_worker.py — RVC (Applio) training and conversion, run INSIDE the
Applio venv (models/vc_applio/.venv, Python 3.12, torch 2.11) with cwd = the
Applio checkout, as a subprocess — the same isolation the diarization and
embedding workers use. Nothing here imports the crews pipeline.

Licences checked at file level 2026-09-15 (record: models/vc_applio/PROVENANCE.json):
  Applio code MIT (IAHispano/Applio LICENSE); terms of use require owning the
  processed audio (ACE-Step output is ours); pretrained v2 HiFi-GAN G/D MIT
  (lj1995/VoiceConversionWebUI card), trained on VCTK (CC BY 4.0, attribution);
  ContentVec MIT (auspicious3000/contentvec LICENSE); RMVPE MIT.
  DDSP-SVC was NOT installed: its required vocoder (openvpi NSF-HiFiGAN) is
  "Attribution-NonCommercial-ShareAlike 4.0 International".

Usage (cwd = models/vc_applio):
  .venv/bin/python <this> prerequisites
  .venv/bin/python <this> train   MODEL DATASET_DIR [EPOCHS] [SAMPLE_RATE]
  .venv/bin/python <this> convert MODEL IN_DIR OUT_DIR [INDEX_RATE] [PROTECT]
Prints one JSON line on stdout.
"""

import glob
import os
import sys


def _latest_weights(model):
    pths = sorted(glob.glob(os.path.join('logs', model, f'{model}_*e_*s.pth')), key=os.path.getmtime)
    if not pths:
        pths = sorted(glob.glob(os.path.join('logs', model, '*.pth')), key=os.path.getmtime)
        pths = [p for p in pths if not os.path.basename(p).startswith(('G_', 'D_'))]
    idx = sorted(glob.glob(os.path.join('logs', model, '*.index')), key=os.path.getmtime)
    return (pths[-1] if pths else None), (idx[-1] if idx else '')


if __name__ == '__main__':  # the CLI lives in vc_applio_worker_cli
    try:
        from zyg_workflows.tools.vc_applio_worker_cli import main as _cli_main
    except ModuleNotFoundError:  # run by path from the Applio venv (voice_conversion.WORKER)
        from vc_applio_worker_cli import main as _cli_main

    raise SystemExit(_cli_main(sys.argv[1:]))
