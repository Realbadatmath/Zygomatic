# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from zyg_dashboard import paths

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


# ── Tunables ────────────────────────────────────────────────────────────────
# A session is ACTIVE when it is measurably using the hardware *now*.  The
# thresholds sit above idle noise: a parked python interpreter ticks a fraction
# of a core, and a CUDA context that has been emptied still shows a few tens of
# MiB.
#
# CPU IS COUNTED IN CORES, NOT PERCENT.  psutil reports per-process CPU on a
# "percent of ONE core" scale, so a session using three cores reads 300% and a
# busy one on this 24-core box reads in the thousands — a number indistinguish-
# able at a glance from the whole-machine CPU ring beside it, which is exactly
# how it was read as "the system total" (2026-08-30).  The measurement was
# never wrong: a controlled 3-core burn reported 300.0% against 299.9% of
# /proc ground truth while the machine sat at 1500-2300%.  The UNIT was.  Every
# surface now says cores, and `cpu_pct` survives in the payload as the raw
# reading.
_CPU_ACTIVE_CORES = float(
    os.environ.get('ZYG_AGENT_CPU_CORES', str(float(os.environ.get('ZYG_AGENT_CPU_PCT', '8')) / 100))
)
_CPU_ACTIVE_PCT = _CPU_ACTIVE_CORES * 100
_VRAM_ACTIVE_MB = float(os.environ.get('ZYG_AGENT_VRAM_MB', '192'))
# RSS, summed. Deliberately NOT PSS: /proc/<pid>/smaps_rollup is the only
# shared-aware number available and it measured 90 ms per read on the 25 GB
# ComfyUI process (page-table walk) — unaffordable every 2 s, and it stalls the
# process being measured. Summed RSS overcounts a forked worker pool by ~11%
# (measured: 547 MB RSS vs 494 MB PSS across four forks), so every surface
# labels it RSS rather than implying an exact footprint.
_RAM_ACTIVE_MB = float(os.environ.get('ZYG_AGENT_RAM_MB', '3072'))
_NCPU = os.cpu_count() or 1
# CPU% is a DELTA measurement — it needs two samples.  The sampler runs on its
# own thread so the number is real the first time the panel is opened, and so
# process start/stop events are captured while the panel is closed (the whole
# point: the operator must be able to scroll back and see what ran).
_SAMPLE_S = float(os.environ.get('ZYG_AGENT_SAMPLE_S', '2.0'))
# Was 4.0 against an nvidia-smi subprocess (19 ms a call), which left half the
# samples reading VRAM up to 4 s stale — measured as a 736 MiB disagreement
# with ground truth mid-render. NVML costs 0.36 ms for processes + memory +
# utilisation together, so the GPU is now read on every sample.
_NVIDIA_S = float(os.environ.get('ZYG_AGENT_NVIDIA_S', '0'))  # 0 = every sample
_EVENT_CAP = 400  # global ring buffer
_SESS_EVENT_CAP = 250  # per-session ring buffer
_TAIL_BYTES = 320_000  # transcript tail read per session (cached on mtime)

_HOME = os.path.expanduser('~')
_SESS_DIR = os.path.join(_HOME, '.claude', 'sessions')
_PROJ_DIR = os.path.join(_HOME, '.claude', 'projects')

# ── Activity ledger (2026-09-05) ─────────────────────────────────────────────
# The GPU/CPU schedule pages (:5000 resource_schedule.html) read this to draw
# agent sessions as orange bars next to production runs — historically, not
# just while the Live Tail happens to be open.  One line per closed SPAN: a
# contiguous stretch in which a session was measurably on one device (gpu =
# VRAM over threshold; cpu = CPU cores or RSS over threshold).  A span stays
# open through short idle gaps (_SPAN_GRACE_S) so a render that pauses between
# frames is one bar, not fifty; anything shorter than _SPAN_MIN_S is noise and
# is not written.  Open spans are mirrored to _OPEN_SPANS_FILE so a restart of
# this server closes them at their last busy sample instead of losing them.
_LEDGER_DIR = str(paths.DATA_DIR / 'runtime')
_LEDGER_FILE = os.environ.get('ZYG_AGENT_LEDGER', os.path.join(_LEDGER_DIR, 'agent_sessions_ledger.jsonl'))
_OPEN_SPANS_FILE = os.environ.get('ZYG_AGENT_OPEN_SPANS', os.path.join(_LEDGER_DIR, 'agent_sessions_open.json'))
_SPAN_GRACE_S = float(os.environ.get('ZYG_AGENT_SPAN_GRACE_S', '180'))
_SPAN_MIN_S = float(os.environ.get('ZYG_AGENT_SPAN_MIN_S', '30'))
_OPEN_FLUSH_S = 30.0

_UID = os.getuid()
_CLOCK_TICKS = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100

# The Claude binary itself, its MCP helpers and the shell-snapshot wrapper are
# infrastructure, not work.  They must never be reported as an agent "burning
# the hardware" — the whole panel would read as permanently busy.
_SELF_RE = re.compile(
    r'(native-binary/claude(\s|$)|--claude-in-chrome-mcp|/claude\s+mcp\b'
    r'|claude-code[-\w]*/resources/)'
)

# What kind of work is this?  Used for the icon and for the one-line event text.
_KIND_PATTERNS = [
    ('train', re.compile(r'simpletuner|train\.py|train_network|lora_train|accelerate\s+launch|sd-scripts')),
    ('test', re.compile(r'\bpytest\b|\bsmoke\b|tests?/|test_[\w]+\.py|unittest|golden[_-]suite')),
    ('comfy', re.compile(r'comfyui|comfy/main\.py')),
    ('render', re.compile(r'\bffmpeg\b|\bffprobe\b|blender|\bconvert\b')),
    (
        'pipeline',
        re.compile(
            r'pipeline_|creature_worker|contact_sheet|storyteller|documentary|kids_music|remixai|arcane_restyle|scene_'
        ),
    ),
    ('model', re.compile(r'\bollama\b|llama[-_]?cpp|vllm|torchrun|\btorch\b|diffusers|transformers')),
    ('python', re.compile(r'(^|/)python[\d.]*\b')),
]

_ICONS = {
    'train': '🎓',
    'test': '🧪',
    'comfy': '🧩',
    'render': '🎬',
    'pipeline': '⚙',
    'model': '🧠',
    'python': '🐍',
    'proc': '▸',
}

# Anything that smells like a credential is stripped before a command line is
# put on a page.  The board is unauthenticated on the LAN; a token pasted into
# an env assignment on a one-off command must not leak through this panel.
_REDACT_RE = re.compile(
    r'((?:api[_-]?key|token|secret|password|passwd|authorization|bearer)'
    r'\s*[=:]\s*)([^\s\'"]+)',
    re.I,
)

# Claude Code's Bash tool wraps every command in a shell-snapshot preamble.
# Showing that preamble would make every line in the tail identical for the
# first 300 characters, so the real command is unwrapped out of the `eval`.
_EVAL_RE = re.compile(r"eval\s+'(.*)'\s*(?:<\s*/dev/null\s*)?(?:&&\s*pwd\s+-P|$)", re.S)
_EVAL_RE2 = re.compile(r'eval\s+"(.*)"\s*(?:<\s*/dev/null\s*)?(?:&&\s*pwd\s+-P|$)', re.S)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec='seconds')
    except Exception:
        return ''
