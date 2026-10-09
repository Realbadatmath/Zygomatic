#!/bin/bash
# ─── Zygomatic Docker Entrypoint ──────────────────────────────────────────────
# Validates required env vars, then starts the Flask dashboard with auto-restart.
set -euo pipefail

echo "[entrypoint] Zygomatic starting — $(date '+%Y-%m-%dT%H:%M:%S')"

# ── Validate required secrets ─────────────────────────────────────────────────
if [ -z "${FLASK_SECRET_KEY:-}" ]; then
    echo "[entrypoint] ERROR: FLASK_SECRET_KEY is not set."
    echo "             Set it in your .env file or pass -e FLASK_SECRET_KEY=<value>"
    exit 1
fi

# ── Optional: warn about missing API keys ─────────────────────────────────────
[ -z "${ANTHROPIC_API_KEY:-}" ] && echo "[entrypoint] WARNING: ANTHROPIC_API_KEY not set — Claude features disabled"
[ -z "${OPENAI_API_KEY:-}"    ] && echo "[entrypoint] WARNING: OPENAI_API_KEY not set — GPT features disabled"

# ── Wait for Redis (if ZYG_REDIS_URL is set) ──────────────────────────────────
if [ -n "${ZYG_REDIS_URL:-}" ]; then
    echo "[entrypoint] Waiting for Redis at ${ZYG_REDIS_URL}..."
    for i in $(seq 1 30); do
        if python -c "import redis; r = redis.from_url('${ZYG_REDIS_URL}'); r.ping()" 2>/dev/null; then
            echo "[entrypoint] Redis is ready."
            break
        fi
        [ "$i" -eq 30 ] && echo "[entrypoint] WARNING: Redis not reachable after 30s — continuing anyway"
        sleep 1
    done
fi

# ── Wait for Ollama (if ZYG_OLLAMA_URL is set) ────────────────────────────────
if [ -n "${ZYG_OLLAMA_URL:-}" ]; then
    echo "[entrypoint] Waiting for Ollama at ${ZYG_OLLAMA_URL}..."
    for i in $(seq 1 60); do
        if curl -sf "${ZYG_OLLAMA_URL}/api/tags" -o /dev/null 2>/dev/null; then
            echo "[entrypoint] Ollama is ready."
            break
        fi
        [ "$i" -eq 60 ] && echo "[entrypoint] WARNING: Ollama not reachable after 60s — continuing anyway"
        sleep 2
    done
fi

# ── Auto-restart loop (mirrors dashboard_launcher.sh) ────────────────────────
CRASH_LOG="/tmp/zygomatic_crashes.log"
_crash_times=()

echo "[entrypoint] Starting Flask dashboard on port ${FLASK_PORT:-5000}..."
while true; do
    python -m zyg_dashboard.crewai_web_gui &
    _pid=$!
    echo "[entrypoint] Server PID: $_pid"
    wait $_pid
    _exit=$?
    _ts="$(date '+%Y-%m-%dT%H:%M:%S')"
    echo "[entrypoint] $_ts — server exited (code $_exit)"
    echo "$_ts  exit=$_exit  pid=$_pid" >> "$CRASH_LOG"

    # Clean shutdown or SIGINT — stop container
    [[ $_exit -eq 0 || $_exit -eq 130 ]] && { echo "[entrypoint] Clean shutdown."; break; }

    # UI-requested restart — immediate
    [[ $_exit -eq 100 ]] && { echo "[entrypoint] UI restart — restarting..."; continue; }

    # Crash-storm guard
    _now=$(date +%s)
    _crash_times+=($_now)
    [[ ${#_crash_times[@]} -gt 5 ]] && _crash_times=("${_crash_times[@]: -5}")
    if [[ ${#_crash_times[@]} -eq 5 ]]; then
        _oldest=${_crash_times[0]}
        if (( _now - _oldest < 60 )); then
            echo "[entrypoint] Crash storm (5x in <60s) — pausing 30s..."
            sleep 30
        fi
    fi

    echo "[entrypoint] Restarting in 3s..."
    sleep 3
done
