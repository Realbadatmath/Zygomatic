#!/bin/bash
# Zygomatic Dashboard Launcher (Linux)
# Auto-restarts on crash; exit code 100 = intentional restart from the UI.
#
# Prefer the systemd unit (deploy/systemd/user/crewai-gui.service) on a real host.
# This wrapper exists for terminal sessions and for machines without systemd.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${ZYG_PYTHON:-$HOME/repos/.venv/bin/python}"
ENV_FILE="${ZYG_ENV_FILE:-$HOME/.config/zygomatic/env}"
CRASH_LOG="${ZYG_CRASH_LOG:-/tmp/zygomatic_dashboard_crashes.log}"

# Load the env file if present (same file the systemd units use as EnvironmentFile).
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$')
    set +a
fi

# Validate required env vars
if [ -z "$FLASK_SECRET_KEY" ]; then
    echo "ERROR: FLASK_SECRET_KEY is not set. Put it in $ENV_FILE first."
    echo "       Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    echo "ERROR: no interpreter at $PYTHON. Create the venv and install both packages:"
    echo "       python -m venv ~/repos/.venv"
    echo "       ~/repos/.venv/bin/pip install -e ../zygomatic-workflows -e ."
    echo "       Or set ZYG_PYTHON to the interpreter you want."
    exit 1
fi

COMFY_START="${ZYG_COMFY_ROOT:-$HOME/ai-models/comfyui}/start_server.sh"
if [ "${ZYG_COMFY_PRIMARY:-0}" = "1" ] || [ "${ZYG_USE_COMFYUI:-0}" = "1" ]; then
    if ! curl -sf "http://${ZYG_COMFY_HOST:-127.0.0.1}:${ZYG_COMFY_PORT:-8188}/system_stats" >/dev/null 2>&1; then
        echo "[launcher] Starting ComfyUI…"
        nohup bash "$COMFY_START" >/dev/null 2>&1 &
        for _i in $(seq 1 30); do
            curl -sf "http://${ZYG_COMFY_HOST:-127.0.0.1}:${ZYG_COMFY_PORT:-8188}/system_stats" >/dev/null 2>&1 && break
            sleep 1
        done
    fi
fi

echo "[launcher] Zygomatic Dashboard auto-restart wrapper starting..."
echo "[launcher] Crash log: $CRASH_LOG"

cd "$REPO_ROOT" || exit 1

_crash_times=()   # ring buffer of recent crash timestamps

while true; do
    echo "[launcher] $(date '+%Y-%m-%dT%H:%M:%S') — starting server (PID will follow)"
    "$PYTHON" -m zyg_dashboard.crewai_web_gui &
    _srv_pid=$!
    echo "[launcher] Server PID: $_srv_pid"
    wait $_srv_pid
    _exit=$?
    _ts="$(date '+%Y-%m-%dT%H:%M:%S')"
    echo "[launcher] $_ts — server exited (code $_exit, PID $_srv_pid)"
    echo "$_ts  exit=$_exit  pid=$_srv_pid" >> "$CRASH_LOG"

    # Exit code 0 or SIGINT (130) = intentional shutdown, do NOT restart
    if [[ $_exit -eq 0 || $_exit -eq 130 ]]; then
        echo "[launcher] Clean shutdown — not restarting."
        break
    fi

    # Exit code 100 = UI-requested restart — restart immediately
    if [[ $_exit -eq 100 ]]; then
        echo "[launcher] UI restart requested — restarting immediately..."
        continue
    fi

    # Crash storm guard: if 5+ crashes in the last 60 seconds, pause 30s
    _now=$(date +%s)
    _crash_times+=($_now)
    # Keep only the last 5 entries
    if [[ ${#_crash_times[@]} -gt 5 ]]; then
        _crash_times=("${_crash_times[@]: -5}")
    fi
    if [[ ${#_crash_times[@]} -eq 5 ]]; then
        _oldest=${_crash_times[0]}
        if (( _now - _oldest < 60 )); then
            echo "[launcher] Crash storm detected (5 crashes in <60s) — pausing 30s..."
            sleep 30
        fi
    fi

    echo "[launcher] Restarting in 3s..."
    sleep 3
done
