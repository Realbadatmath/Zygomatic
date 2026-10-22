# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""demucs_split.py — two-stem (vocals / accompaniment) separation, over stdout JSON.

Runs in the agents venv (which owns demucs + torch), NOT in the GUI process —
same subprocess+JSON contract voice_qc uses for Praat, and for the same reason:
importing torch into the dashboard would put a CUDA context in a process that
must stay light.

The demucs CLI is deliberately not used. Its writer goes through
torchaudio.save -> save_with_torchcodec, which raises ImportError on this box
(TorchCodec is not installed and installing it to write a wav would be a silly
dependency). The model API plus soundfile writes the same samples with nothing
extra installed.

The separation itself is the command line (demucs_split_cli), because its
deliverable is the JSON line it prints; this module keeps the logger that code
writes through, and the connector that `python -m` and `python
tools/demucs_split.py` both reach.

Usage:  python demucs_split.py IN_AUDIO OUT_DIR [--device cuda|cpu]
Prints one JSON line: {'ok', 'vocals', 'rest', 'vocal_rms_db', 'rest_rms_db',
                       'ratio_db', 'seconds', 'device', 'error'}
"""

import sys
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


if __name__ == '__main__':  # the CLI lives in demucs_split_cli
    from zyg_workflows.tools.demucs_split_cli import main as _cli_main

    raise SystemExit(_cli_main(sys.argv[1:]))
