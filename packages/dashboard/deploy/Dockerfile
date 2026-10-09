# ═══════════════════════════════════════════════════════════════════════════════
# Zygomatic dashboard — NVIDIA GPU image
# Base: CUDA 12.8 + cuDNN 9 (Ada Lovelace / RTX 40xx, compute 8.9), Python 3.12.
#
# The build context is the REPOSITORY ROOT, not this directory, because the image
# installs the package from pyproject.toml:
#
#   docker build -f deploy/Dockerfile -t zygomatic-dashboard:gpu .
#   docker compose -f deploy/docker-compose.yml up        (sets the context for you)
#
# zygomatic-workflows is a dependency of this package; pip resolves it from the
# index, or mount a checkout and `pip install -e` it over the top.
# ═══════════════════════════════════════════════════════════════════════════════

FROM nvidia/cuda:12.8.0-cudnn9-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

# ── System packages ────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    libsndfile1-dev \
    portaudio19-dev \
    espeak \
    espeak-ng \
    libsm6 \
    libxext6 \
    libglib2.0-0 \
    libgomp1 \
    libgl1-mesa-glx \
    git \
    curl \
    wget \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python  python  /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && python3.12 -m ensurepip \
    && python3.12 -m pip install --upgrade pip setuptools wheel

WORKDIR /app

# ── PyTorch, CUDA 12.8 — before the package, so torch-dependent wheels resolve ─
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 \
    torch torchvision torchaudio

# ── The package itself, from pyproject.toml ───────────────────────────────────
# Editable, so a bind-mounted source tree can be developed against the image.
COPY . /app
RUN pip install --no-cache-dir -e .

# ── Playwright browser (the web research agent drives chromium) ───────────────
RUN python -m playwright install --with-deps chromium

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ZYG_OLLAMA_URL=http://ollama:11434 \
    ZYG_DATA_ROOT=/app/data \
    ZYG_OUTPUT_ROOT=/app/output \
    ZYG_MODELS_ROOT=/models \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -sf http://localhost:5000/ -o /dev/null || exit 1

ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
