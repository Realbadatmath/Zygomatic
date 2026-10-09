#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Install GPU/cooling tools (Ubuntu 24.04 + RTX 4090).
# Run: sudo bash install_gpu_cooling_tools.sh
# Optional: sudo bash install_gpu_cooling_tools.sh --with-gwe
set -euo pipefail

WITH_GWE=false
for arg in "$@"; do
  case "$arg" in
    --with-gwe) WITH_GWE=true ;;
    -h|--help)
      echo "Usage: sudo bash $0 [--with-gwe]"
      exit 0
      ;;
  esac
done

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: run as root: sudo bash $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# When run via sudo, HOME is often /root — resolve the invoking user's paths.
COOLING_USER="${SUDO_USER:-${USER:-zygomatic}}"
USER_HOME="$(getent passwd "${COOLING_USER}" 2>/dev/null | cut -d: -f6)"
USER_HOME="${USER_HOME:-/home/${COOLING_USER}}"
OPT="${OPT:-${USER_HOME}/.local/opt/cooling}"
NVFD_SRC="${NVFD_SRC:-${USER_HOME}/.local/src/nvfd}"
STAGED_NVFD="${STAGED_NVFD:-${USER_HOME}/.local/bin/nvfd}"

echo "==> [1/6] Base dependencies"
apt-get update -qq
apt-get install -y \
  curl apt-transport-https ca-certificates gnupg \
  build-essential git \
  libjansson-dev libncurses-dev \
  libnvidia-ml-dev \
  liquidctl lm-sensors

echo "==> [2/6] CoolerControl"
DEB_DIR="${OPT}/debs"
if [[ -f "${DEB_DIR}/coolercontrold_4.3.1_amd64_ubuntu.deb" ]]; then
  apt-get install -y "${DEB_DIR}/coolercontrold_4.3.1_amd64_ubuntu.deb" \
    "${DEB_DIR}/coolercontrol_4.3.1_amd64_ubuntu.deb" || true
  dpkg -i "${DEB_DIR}/coolercontrold_4.3.1_amd64_ubuntu.deb" \
         "${DEB_DIR}/coolercontrol_4.3.1_amd64_ubuntu.deb" 2>/dev/null || true
  apt-get install -f -y
else
  curl -1sLf 'https://dl.cloudsmith.io/public/coolercontrol/coolercontrol/setup.deb.sh' | bash
  apt-get update -qq
  apt-get install -y coolercontrol coolercontrold
fi

echo "==> [3/6] NVFD"
if [[ ! -d "${NVFD_SRC}/.git" ]]; then
  git clone --depth 1 https://github.com/Infinirc/nvfd.git "${NVFD_SRC}"
fi
if systemctl is-active --quiet nvfd.service 2>/dev/null; then
  systemctl stop nvfd.service
fi
cd "${NVFD_SRC}"
if [[ -x "${STAGED_NVFD}" ]] && [[ -f build/nvfd ]]; then
  install -m755 build/nvfd /usr/local/bin/nvfd
else
  make clean && make
  install -m755 build/nvfd /usr/local/bin/nvfd
fi
make install
make install-utils
systemctl daemon-reload

echo "==> [4/6] Fan curve + config"
mkdir -p /etc/nvfd
if [[ -f "${OPT}/staging/etc/nvfd/curve.json" ]]; then
  install -m644 "${OPT}/staging/etc/nvfd/curve.json" /etc/nvfd/curve.json
  install -m644 "${OPT}/staging/etc/nvfd/config.json" /etc/nvfd/config.json
else
  cat > /etc/nvfd/curve.json <<'EOF'
{
    "30": 30,
    "45": 35,
    "55": 45,
    "65": 58,
    "70": 68,
    "75": 78,
    "80": 88,
    "83": 100
}
EOF
  cat > /etc/nvfd/config.json <<'EOF'
{
  "gpu0": {
    "mode": "curve"
  }
}
EOF
  chmod 644 /etc/nvfd/curve.json /etc/nvfd/config.json
fi

if [[ -f /etc/systemd/system/nvfd-fan-control.service ]]; then
  sed -i 's|^ExecStart=.*|ExecStart=/usr/local/bin/nvfd-fan-control.sh --threshold-up 55 --threshold-down 45|' \
    /etc/systemd/system/nvfd-fan-control.service || true
  systemctl daemon-reload
  systemctl enable nvfd-fan-control.service
  systemctl restart nvfd-fan-control.service
fi
systemctl enable nvfd.service
systemctl restart nvfd.service

echo "==> [5/6] CoolerControl daemon"
systemctl enable coolercontrold.service
systemctl restart coolercontrold.service

if [[ "$WITH_GWE" == true ]]; then
  echo "==> [6/6] GreenWithEnvy (Flatpak)"
  apt-get install -y flatpak
  flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
  flatpak install -y flathub com.leinardi.gwe || true
else
  echo "==> [6/6] Skipping GreenWithEnvy (use --with-gwe to install)"
fi

echo ""
echo "=============================================="
echo " GPU cooling tools installed"
echo "=============================================="
echo "NVFD:  sudo nvfd status"
echo "CC UI: http://127.0.0.1:11987"
echo 'Leave GPU fans on AUTO in CoolerControl; NVFD controls GPU fans.'
systemctl is-active nvfd.service coolercontrold.service 2>/dev/null || true
nvidia-smi --query-gpu=name,temperature.gpu,fan.speed,power.draw --format=csv,noheader 2>/dev/null || true
