#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fail if an LLM call site can execute without being recorded.

Opt-in prompt logging let 39 of 45 call sites (87%) go unrecorded — including
the documentary's fact-check, its era lock and its scene anchors. `llm_audit`
now captures Anthropic automatically by patching the SDK, so the only calls
that can still escape are RAW Ollama posts written by hand.

This checks for those: a raw /api/generate or /api/chat post that neither goes
through llm_audit.ollama_generate nor sits next to an explicit _log_prompt.

  python3 scripts/check_llm_logging.py          # report
  python3 scripts/check_llm_logging.py --strict # exit 1 on any finding
"""

import ast
import glob
import os
import sys

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Modules that legitimately post to Ollama as part of implementing the audited
# helper itself, or that probe the server rather than generate.
EXEMPT = {'llm_audit.py', 'vram_manager.py', '_comfy_client.py'}


def scan(path):
    try:
        src = open(path, encoding='utf-8').read()
        tree = ast.parse(src)
    except Exception:
        return []
    lines = src.split('\n')
    if 'llm_audit.ollama_generate' in src:
        pass  # still check individual sites below
    findings = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        ln = getattr(node, 'lineno', 0)
        txt = lines[ln - 1] if 0 < ln <= len(lines) else ''
        if '/api/generate' not in txt and '/api/chat' not in txt:
            continue
        lo, hi = max(0, ln - 45), min(len(lines), ln + 25)
        window = '\n'.join(lines[lo:hi])
        if '_log_prompt(' in window or 'llm_audit' in window:
            continue
        # Evictions and warm-ups are not generations: they post keep_alive 0
        # purely to free or reserve VRAM. Nothing is produced, so there is
        # nothing to audit. Checked against THIS call's own payload block only
        # — a wide window exempts a real call that merely happens to sit near
        # an eviction, which is how briefing_jobs:279 first slipped through.
        plo, phi = max(0, ln - 14), min(len(lines), ln + 2)
        payload_block = '\n'.join(lines[plo:phi])
        if "'keep_alive': 0" in payload_block or '"keep_alive": 0' in payload_block:
            continue
        if ln in seen:  # ast.walk visits nested calls on the same line
            continue
        seen.add(ln)
        findings.append((ln, txt.strip()[:88]))
    return findings


def main():
    strict = '--strict' in sys.argv
    total = 0
    for path in sorted(glob.glob(os.path.join(CREWS, '*.py'))):
        if os.path.basename(path) in EXEMPT:
            continue
        for ln, txt in scan(path):
            total += 1
            print(f'UNAUDITED  {os.path.basename(path)}:{ln}  {txt}')
    if total:
        print(f'\n{total} raw Ollama call site(s) not routed through llm_audit.ollama_generate().')
        print('Anthropic calls need no change — the SDK is patched in crewai_web_gui at startup.')
        return 1 if strict else 0
    print('OK — no unaudited raw Ollama call sites.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
