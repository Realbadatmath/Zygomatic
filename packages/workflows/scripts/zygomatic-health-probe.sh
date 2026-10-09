#!/bin/bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Zygomatic health probe — catches alive-but-dead states systemd cannot see:
# a wedged ComfyUI executor (HTTP up, queue frozen) and unresponsive Flask apps.
# Requires two consecutive bad probes (timer runs every 2 min) before acting,
# and never touches a service younger than 3 minutes (startup grace).
STATE=/var/tmp/zygomatic-health
LOG=/var/log/zygomatic-health.log
MAINT_FLAG=/var/tmp/zygomatic-maintenance.flag
mkdir -p "$STATE"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; logger -t zyg-health "$*"; }

# Deliberate maintenance (restart_flask.sh) sets the flag; skip all probing
# while it is fresh so we never fire a competing restart mid-maintenance
# (2026-07-15: probe restarted crewai-gui at 23:21 while restart_flask.sh
# from 23:18 was still mid-flight). Flags older than 15 min are ignored so
# a crashed maintenance run cannot silence monitoring indefinitely.
if [ -f "$MAINT_FLAG" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$MAINT_FLAG" 2>/dev/null || echo 0) ))
  if [ "$age" -lt 900 ]; then
    log "maintenance flag present (${age}s old) — skipping probes"
    exit 0
  fi
  log "ignoring stale maintenance flag (${age}s old)"
fi

# ── In-flight interlock (2026-08-29) ────────────────────────────────────────
# A long render can make :5000 stop answering for a while, and restarting the
# GUI underneath it kills the run: 30 such restarts since 8 July, one at 19:32
# on 2026-08-29, each leaving a manifest-less folder behind.
#
# A running pipeline writes /var/tmp/zygomatic-inflight/<dept>-<id>.flag and
# REFRESHES it as it works. While such a flag is fresh we defer restarts of the
# services that would kill the run — but we keep probing and keep logging, and
# the deferral is bounded twice over:
#   * a flag that stops being refreshed goes stale in 5 min and protects nothing,
#     so a crashed run cannot silence monitoring;
#   * a single flag cannot defer for more than INFLIGHT_MAX (45 min) since it was
#     created — a run hung that long IS the fault we are supposed to catch.
INFLIGHT_DIR=/var/tmp/zygomatic-inflight
INFLIGHT_STALE=300
INFLIGHT_MAX=2700

inflight() {  # is a pipeline genuinely mid-run right now?
  [ -d "$INFLIGHT_DIR" ] || return 1
  local now f mtime ctime
  now=$(date +%s)
  for f in "$INFLIGHT_DIR"/*.flag; do
    [ -e "$f" ] || continue
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    # Heartbeat age: stale flags protect nothing.
    [ $(( now - mtime )) -lt "$INFLIGHT_STALE" ] || { rm -f "$f"; continue; }
    # Total age, read from the flag's own "started" field, so a heartbeat
    # cannot extend the deferral forever.
    ctime=$(sed -n 's/.*"started": *\([0-9]*\).*/\1/p' "$f" 2>/dev/null)
    [ -n "$ctime" ] || ctime=$mtime
    if [ $(( now - ctime )) -lt "$INFLIGHT_MAX" ]; then
      INFLIGHT_JOB=$(basename "$f" .flag)
      return 0
    fi
    log "in-flight flag $(basename "$f") exceeded ${INFLIGHT_MAX}s — no longer deferring"
  done
  return 1
}

young() {  # service started <180s ago?
  local ts; ts=$(systemctl show -p ActiveEnterTimestampMonotonic --value "$1" 2>/dev/null)
  [ -z "$ts" ] || [ "$ts" = "0" ] && return 1
  local now; now=$(awk '{print int($1*1000000)}' /proc/uptime)
  [ $(( now - ts )) -lt 180000000 ]
}

# Services whose restart would kill an in-flight render. zero-public is not one
# of them — it serves public requests and does not host the render threads.
defers_for_inflight() {
  case "$1" in
    crewai-gui.service|comfyui.service) return 0 ;;
    *) return 1 ;;
  esac
}

strike() {  # strike NAME REASON — restart on 2nd consecutive strike
  local n="$1" reason="$2" f="$STATE/$1.strikes"
  local c=0; [ -f "$f" ] && c=$(cat "$f")
  c=$((c+1)); echo "$c" > "$f"
  if [ "$c" -ge 2 ] && defers_for_inflight "$n" && inflight; then
    # Strikes are KEPT, not cleared: if the job finishes and the service is
    # still bad, the very next probe restarts it. Deferring is not forgiving.
    log "DEFER restart of $n — $reason (strike $c) — $INFLIGHT_JOB is mid-run"
    return
  fi
  if [ "$c" -ge 2 ]; then
    log "RESTART $n — $reason (strike $c)"
    # reset-failed clears systemd's start-rate-limit counter so a start-limited
    # unit (e.g. after a crash-loop) can actually be resurrected (2026-07-15)
    systemctl reset-failed "$n" 2>/dev/null
    if systemctl restart "$n"; then
      rm -f "$f"
    else
      log "RESTART FAILED for $n — keeping strikes, retrying next cycle"
    fi
  else
    log "strike 1 for $n — $reason (waiting for confirmation)"
  fi
}
clear_strikes() { rm -f "$STATE/$1.strikes"; }

# ComfyUI: reachable + executor actually draining
if ! young comfyui.service; then
  Q=$(curl -s --max-time 8 http://127.0.0.1:8188/queue 2>/dev/null)
  if [ -z "$Q" ]; then
    strike comfyui.service "queue endpoint unreachable"
  else
    read -r RUN PEND HEAD <<< "$(echo "$Q" | python3 -c 'import json,sys; d=json.load(sys.stdin); p=d.get("queue_pending",[]); print(len(d.get("queue_running",[])), len(p), p[0][1] if p else "-")' 2>/dev/null)"
    if [ "${PEND:-0}" -gt 0 ] && [ "${RUN:-0}" -eq 0 ]; then
      # Only a real wedge if the SAME head job is still pending with nothing
      # running on consecutive probes — a snapshot of a fresh head id is just
      # the normal pending->running handoff (every 2026-07 "wedged" strike-1
      # was this race and self-cleared; none ever confirmed).
      PREV=$(cat "$STATE/comfyui.wedge_head" 2>/dev/null)
      echo "$HEAD" > "$STATE/comfyui.wedge_head"
      if [ -n "$PREV" ] && [ "$PREV" = "$HEAD" ]; then
        strike comfyui.service "executor wedged: head job $HEAD stuck pending, 0 running"
      fi
    else
      rm -f "$STATE/comfyui.wedge_head"
      clear_strikes comfyui.service
    fi
  fi
fi

# Flask apps: HTTP answering at all
if ! young crewai-gui.service; then
  if curl -s -o /dev/null --max-time 10 http://127.0.0.1:5000/login; then
    clear_strikes crewai-gui.service
  else
    strike crewai-gui.service "port 5000 not answering"
  fi
fi
if ! young zero-public.service; then
  if curl -s -o /dev/null --max-time 10 http://127.0.0.1:5001/; then
    clear_strikes zero-public.service
  else
    strike zero-public.service "port 5001 not answering"
  fi
fi
