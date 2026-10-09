#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# gpu_run.sh — serialise GPU work on ONE lock file, and host RAM on a floor.
#
# WHY. This box has one GPU and one lock file for it, but nothing has ever
# serialised host RAM: on 2026-09-03 a `pip install flash-attn` build (nvcc, 3-5 GB
# per job) took the machine's free RAM down far enough that the OOM killer took
# ComfyUI out mid-render. The GPU lock would not have helped — that build never
# touches the GPU. So this wrapper does the two guards independently:
#
#     --no-lock       RAM floor only, for CPU builds (pip/nvcc) that must NEVER
#                     take the GPU lock (holding it for a 40-minute compile is the
#                     other half of the same failure).
#     default         GPU lock for the WHOLE command, plus the RAM floor.
#
# The lock is taken with flock(1) on fd 9 and held until the command exits, because
# the command is exec'd into this shell and inherits the fd. Every other GPU job on
# the box blocks in the same syscall, so waiters are woken in kernel order rather
# than losing a polling race.
#
# USAGE
#     scripts/gpu_run.sh [--ram-gb N] [--ram-wait S] [--lock-wait S] [--no-lock] \
#                        -- <command...>
#
#     --ram-gb N     MemAvailable floor in GB before the command starts (default 12)
#     --ram-wait S   how long to wait for that floor, seconds (default 900)
#     --lock-wait S  how long to wait for the GPU lock, seconds (default 7200)
#     --no-lock      skip the GPU lock entirely (RAM guard still applies)
#
# EXIT CODES
#     75  RAM floor not reached within --ram-wait; the command was NOT run
#     69  GPU lock not acquired within --lock-wait; the command was NOT run
#     2   usage error
#     *   otherwise the command's own exit code, passed through
#
# ENV
#     ZYG_GPU_LOCK   lock file (default $HOME/.zyg_gpu.lock)
#     ZYG_GPU_LOG    log file  (default <lock>.log)
set -u

LOCK="${ZYG_GPU_LOCK:-$HOME/.zyg_gpu.lock}"
LOG="${ZYG_GPU_LOG:-${LOCK}.log}"
RAM_GB=12
RAM_WAIT=900
LOCK_WAIT=7200
USE_LOCK=1

usage() {
    sed -n '2,40p' "$0" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --ram-gb)    [ $# -ge 2 ] || usage; RAM_GB="$2";    shift 2 ;;
        --ram-wait)  [ $# -ge 2 ] || usage; RAM_WAIT="$2";  shift 2 ;;
        --lock-wait) [ $# -ge 2 ] || usage; LOCK_WAIT="$2"; shift 2 ;;
        --no-lock)   USE_LOCK=0; shift ;;
        -h|--help)   usage ;;
        --)          shift; break ;;
        *)           echo "gpu_run.sh: unknown option '$1' (options must precede --)" >&2
                     usage ;;
    esac
done

[ $# -ge 1 ] || { echo "gpu_run.sh: no command given after --" >&2; usage; }

# MemAvailable in GB, one decimal. /proc/meminfo reports kB.
ram_avail_gb() {
    awk '/^MemAvailable:/ {printf "%.1f", $2 / 1048576.0; exit}' /proc/meminfo
}

# integer-safe comparison: is MemAvailable >= floor? (awk, no bc dependency)
ram_ok() {
    awk -v have="$1" -v want="$2" 'BEGIN {exit !(have + 0 >= want + 0)}'
}

CMD_LOG="$*"
CMD_LOG="${CMD_LOG:0:120}"
T0=$(date +%s)

# ---------------------------------------------------------------- GPU lock
LOCK_WAITED=0
if [ "$USE_LOCK" = "1" ]; then
    exec 9>>"$LOCK" || { echo "gpu_run.sh: cannot open lock $LOCK" >&2; exit 2; }
    if ! flock -w "$LOCK_WAIT" 9; then
        echo "gpu_run.sh: GPU lock $LOCK not acquired within ${LOCK_WAIT}s; not running" >&2
        exit 69
    fi
    LOCK_WAITED=$(( $(date +%s) - T0 ))
    [ "$LOCK_WAITED" -gt 2 ] && \
        echo "gpu_run.sh: GPU lock acquired after ${LOCK_WAITED}s" >&2
fi

# ---------------------------------------------------------------- RAM floor
# Held INSIDE the lock on purpose: a job that has the GPU should not release it
# just because the host is briefly short of RAM, or the queue thrashes.
RAM=$(ram_avail_gb)
RAM_WAITED=0
if ! ram_ok "$RAM" "$RAM_GB"; then
    while ! ram_ok "$RAM" "$RAM_GB"; do
        NOW=$(( $(date +%s) - T0 - LOCK_WAITED ))
        [ "$NOW" -ge "$RAM_WAIT" ] && break
        LEFT=$(( RAM_WAIT - NOW ))
        [ "$LEFT" -gt 10 ] && LEFT=10
        sleep "$LEFT"
        RAM=$(ram_avail_gb)
    done
    RAM_WAITED=$(( $(date +%s) - T0 - LOCK_WAITED ))
    if ! ram_ok "$RAM" "$RAM_GB"; then
        echo "gpu_run.sh: RAM floor not met after ${RAM_WAITED}s: ${RAM} GB available," \
             "need ${RAM_GB} GB (short $(awk -v h="$RAM" -v w="$RAM_GB" \
             'BEGIN{printf "%.1f", w - h}') GB); NOT running: ${CMD_LOG}" >&2
        exit 75
    fi
    echo "gpu_run.sh: waited ${RAM_WAITED}s for RAM (${RAM} GB available, floor ${RAM_GB} GB)" >&2
fi

WAITED=$(( $(date +%s) - T0 ))
printf '%s pid=%s waited_s=%s ram_avail_gb=%s lock=%s cmd=%s\n' \
    "$(date +%Y-%m-%dT%H:%M:%S)" "$$" "$WAITED" "$RAM" \
    "$([ "$USE_LOCK" = 1 ] && echo held || echo none)" "$CMD_LOG" >>"$LOG" 2>/dev/null

# fd 9 survives the exec, so the lock is held for the command's whole life and
# released by the kernel when it exits — however it exits.
exec "$@"
