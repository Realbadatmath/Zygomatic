#!/bin/bash
# Zygomatic dashboard — Ubuntu setup
# Run once on a fresh Ubuntu machine: system packages, one virtualenv, both packages.
# Usage: bash deploy/setup_ubuntu.sh
#
# Dependencies come from pyproject.toml. There is no requirements/ directory.

set -e

echo "=== Zygomatic dashboard setup ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKFLOWS="${ZYG_WORKFLOWS_SRC:-$(dirname "$REPO_ROOT")/zygomatic-workflows}"
VENV="${ZYG_VENV:-$(dirname "$REPO_ROOT")/.venv}"
ENV_FILE="${ZYG_ENV_FILE:-$HOME/.config/zygomatic/env}"

# ── 1. System packages ─────────────────────────────────────────
echo "[1/4] Installing system packages..."
sudo apt update
sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip \
    ffmpeg libsndfile1 portaudio19-dev \
    lsof \
    postgresql postgresql-contrib \
    nginx \
    git curl wget

# ── 2. One virtualenv for both packages ────────────────────────
# zygomatic-workflows is the base library; the dashboard imports it. Installing
# both editable from one venv is what the systemd units expect
# (ExecStart=%h/repos/.venv/bin/python -m zyg_dashboard...).
echo "[2/4] Creating the virtualenv at $VENV..."
python3.11 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
if [ -d "$WORKFLOWS" ]; then
    "$VENV/bin/pip" install -e "$WORKFLOWS"
else
    echo "  !! zygomatic-workflows not found at $WORKFLOWS."
    echo "     Clone it next to this repository, or set ZYG_WORKFLOWS_SRC, then re-run."
    exit 1
fi
"$VENV/bin/pip" install -e "$REPO_ROOT[dev]"

# ── 3. Environment file ────────────────────────────────────────
# One file, outside the repository, 0600, never committed. The systemd units read
# it as EnvironmentFile; see deploy/README.md for every variable it may hold.
echo "[3/4] Setting up $ENV_FILE..."
if [ ! -f "$ENV_FILE" ]; then
    mkdir -p "$(dirname "$ENV_FILE")"
    umask 077
    {
        echo "# Zygomatic environment — read by the systemd units and the launcher."
        echo "FLASK_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    } > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "  Created $ENV_FILE with a fresh FLASK_SECRET_KEY (mode 600)."
    echo "  Add your API keys and ZYG_* overrides to it before starting."
fi

# ── 4. PostgreSQL database ─────────────────────────────────────
# Only needed by the run ledger and the QC trend job; the GUI starts without it.
echo "[4/4] Setting up PostgreSQL..."
sudo -u postgres psql -c "CREATE USER zygomatic WITH PASSWORD 'changeme';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE zygomatic OWNER zygomatic;" 2>/dev/null || true
echo "  Database 'zygomatic' ready. Put its real password in DATABASE_URL in $ENV_FILE."

echo ""
echo "Setup complete. Next:"
echo "  1. Edit $ENV_FILE (FLASK_SECRET_KEY is set; add API keys and ZYG_* overrides)"
echo "  2. Install the user units:  cp deploy/systemd/user/* ~/.config/systemd/user/"
echo "  3. systemctl --user daemon-reload && systemctl --user enable --now crewai-gui.service"
echo "  4. Dashboard on http://127.0.0.1:5000 — see deploy/README.md for the rest"
echo ""
