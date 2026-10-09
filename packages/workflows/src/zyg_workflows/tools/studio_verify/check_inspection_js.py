#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Syntax-check every inline <script> block of inspection.html with `node --check`.
Exit 0 when all blocks parse. Usage: check_inspection_js.py [path]"""

import os
import re
import subprocess
import sys
import tempfile
from zyg_workflows.bin import exe

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', '..', 'inspection.html')
src = open(p, encoding='utf-8').read()
blocks = [(m.start(), m.group(2)) for m in re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(\s*)(.*?)</script>', src, re.S)]
bad = 0
for i, (pos, body) in enumerate(blocks):
    if not body.strip():
        continue
    line = src.count('\n', 0, pos) + 1
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(body)
        tmp = f.name
    r = subprocess.run([exe('node'), '--check', tmp], capture_output=True, text=True)
    os.unlink(tmp)
    if r.returncode != 0:
        bad += 1
        _zyg_log.info(f'BLOCK {i} (starts line {line}): {r.stderr.strip()[:600]}')
    else:
        _zyg_log.info(f'BLOCK {i} (line {line}, {len(body)} chars): ok')
_zyg_log.info(' '.join(str(a) for a in ('inline blocks:', len(blocks), 'bad:', bad)))
sys.exit(1 if bad else 0)
