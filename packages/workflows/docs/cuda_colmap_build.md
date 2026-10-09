# Building a CUDA COLMAP — the recipe, and why it is deferred

**Status: DEFERRED, deliberately, 2026-08-08.** Not forgotten — `geom/sfm_capability.py`
probes for it and gate `t4_sfm_capability` reports its absence on every suite run, with the
consequence spelled out. If you are reading this because that gate told you to, everything
you need is below.

---

## Why it is deferred

Three reasons, in descending order of importance:

1. **There is nothing to reconstruct.** No real person has been photographed. Dense stereo
   would have no input.
2. **`geom/scan_ingest.py` is blocked behind a different, unsolved problem** — separating
   proportion from detail. Even a perfect dense reconstruction feeds a stage that currently
   leaks a measured 13.7% of a mid-scale proportion into the "detail" layer. Fixing the
   reconstruction while that is open would improve the wrong term.
3. Building it is 1–2 hours with real dependency friction, and `pycolmap` publishes **no
   source distribution** (`pip download --no-binary :all: pycolmap` → *No matching
   distribution found*), so this is a git clone and a CMake build, not a pip rebuild.

None of that is permanent. Do it the day someone stands in front of a camera.

---

## Read this before you install anything

The thing that made this look dangerous was a conflation on my part. Two different objects:

| | what it is | how many can exist |
|---|---|---|
| **Driver** | `nvidia.ko` kernel module + `libcuda.so` | **exactly one per machine** |
| **Toolkit** | `nvcc`, `libcudart`, headers | **any number, side by side** |

**CUDA is backward compatible in the direction that matters: a driver exposing CUDA 13.0
runs binaries built by any older toolkit.** So toolkit 12.x on this machine's driver 580 is
the normal supported case, *not* a mismatch. Building against an older toolkit is fine.

**You cannot switch drivers per job.** One kernel module is bound to the GPU; swapping it
means unloading `nvidia.ko`, which requires every CUDA process on the box to exit first —
ComfyUI included. It is a reboot-class operation, not a toggle. Containers do not change
this: the NVIDIA Container Toolkit passes the *host* driver into the container. Containers
share one driver and bring their own toolkit, which is toolkit isolation again.

**You can trivially have several toolkits.** They install to versioned paths and you select
one per job with `CUDA_HOME` / `PATH` / `LD_LIBRARY_PATH`.

### The one thing that would actually break this workstation

> **NEVER install Ubuntu's `nvidia-cuda-toolkit`, and never install NVIDIA's `cuda`
> meta-package.**

Both reach into the *driver* stack. `apt-cache depends --recurse nvidia-cuda-toolkit` on
this box matched `nvidia-driver` / `nvidia-dkms` / `nvidia-kernel` packages **20 times**.
If a package operation replaces `libnvidia-compute-*` at a version other than the running
`580.173.02`, CUDA initialisation starts failing across every service on the machine, with
errors that point nowhere near the cause. **This project has already lost time to exactly
that outage.** `geom/sfm_capability.check_driver_stack()` exists to catch it, and reports
it as `BROKEN` rather than as a warning, because there is no state in which a split driver
stack is worth continuing to render on.

Use `cuda-toolkit-12-6` (toolkit only) or the pip route below. Both leave the driver alone.

---

## Recipe A — pip `nvcc`, no sudo touches anything NVIDIA (safest)

The compiler lives inside the venv and cannot reach the system driver by construction.

```bash
VENV="$(dirname "$(dirname "$ZYG_ASR_PYTHON")")"   # the out-of-process ASR venv
$VENV/bin/pip install nvidia-cuda-nvcc-cu12          # 12.9.86 available as of 2026-08-08
export CUDA_HOME=$($VENV/bin/python -c "import nvidia.cuda_nvcc,os;print(os.path.dirname(nvidia.cuda_nvcc.__file__))")
export PATH="$CUDA_HOME/bin:$PATH"
nvcc --version
```

Plain C++ dev libraries still come from apt. **None of these touch NVIDIA anything** — they
are Eigen, Boost and friends:

```bash
sudo apt-get install -y \
  build-essential cmake ninja-build git \
  libeigen3-dev libboost-program-options-dev libboost-filesystem-dev \
  libboost-graph-dev libboost-system-dev libboost-test-dev \
  libceres-dev libgoogle-glog-dev libgflags-dev \
  libfreeimage-dev libglew-dev libsqlite3-dev libflann-dev libmetis-dev \
  liblz4-dev libmetis-dev qtbase5-dev libqt5opengl5-dev
```

Verify the dry run removes nothing before committing:

```bash
sudo apt-get install -s -y <the list above> | grep '^Remv'    # MUST be empty
```

## Recipe B — NVIDIA's own repo, toolkit only

```bash
# add NVIDIA's apt repo for ubuntu2404, then:
sudo apt-get install -y cuda-toolkit-12-6     # NOT `cuda`, which pulls a driver
export CUDA_HOME=/usr/local/cuda-12.6
export PATH="$CUDA_HOME/bin:$PATH"
```

## Then build COLMAP + pycolmap

```bash
git clone https://github.com/colmap/colmap.git && cd colmap
cmake -B build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DCUDA_ENABLED=ON \
      -DCMAKE_CUDA_ARCHITECTURES=89 \
      -DCMAKE_INSTALL_PREFIX="$HOME/.local/colmap-cuda"
ninja -C build -j20                 # 20, not all 24 — see the CPU cap rule
ninja -C build install

cd pycolmap
$VENV/bin/pip install . -v
```

`CMAKE_CUDA_ARCHITECTURES=89` is the RTX 4090 (Ada, sm_89). Building for the one
architecture present cuts compile time substantially over the default fat binary.

`-j20` because this machine has a **standing system-wide cap of 20 of 24 cores**; see
`feedback_cpu_core_cap` and `/home/zygomatic/bin/zyg_cpu_cap.sh`.

---

## After building — do all four, in order

```bash
cd "$ZYG_CREWS_ROOT"
V="$ZYG_ASR_PYTHON"

# 1. Did anything move the driver? This is the check that matters most.
$V -m geom.sfm_capability --fail-on-broken

# 2. Prove dense stereo actually EXECUTES rather than merely reporting has_cuda=True.
$V -m geom.sfm_capability --deep --fail-on-broken

# 3. Only if both pass, adopt the new state as the thing to defend.
$V -m geom.sfm_capability --record-baseline --deep

# 4. Confirm no gate regressed.
$V -m geom.anthro check all
```

**Do not skip step 2.** `pycolmap.has_cuda` is a compile-time constant baked into the
wheel: it reports what the build was configured with, not what this machine can do now. A
build that claims dense stereo and cannot perform it is strictly more dangerous than one
that honestly reports it cannot, because only the first one gets trusted.

**Do not run step 3 before steps 1 and 2 pass.** The baseline is the record of a state
worth defending. Recording a broken state teaches the gate that broken is normal, and from
then on it detects nothing.

---

## What the build actually buys, measured

| capability | today | with CUDA COLMAP |
|---|---|---|
| sparse SfM (the `mvconsist` gate) | works, CPU SIFT, 118–300 s per 48-cell sheet | same result, faster |
| **dense patch-match stereo** | **cannot run at all** | runs |
| `scan_ingest` dense stage | degrades to two-view `cv2.StereoSGBM` | real MVS |

The middle row is the only reason to do this. Everything else is wall-clock.

**The `mvconsist` band does not need re-deriving after this build.** It was measured on CPU
SIFT, and GPU SIFT changes speed, not the geometry that the band scores. What *would*
invalidate it is changing the bundle-adjustment linear solver, which this build does not do
— see `data/assets/sfm/PROVENANCE.json`.

---

## Licence note

Settled 2026-08-08 and recorded in `data/assets/sfm/PROVENANCE.json`: this stack is never
distributed, so the GPL-2.0-or-later content statically linked into pycolmap (CHOLMOD
Supernodal/MatrixOps, SPQR) imposes nothing — GPL obligations attach to *conveying*, and
GPL-2.0 §0 states that running the program is not restricted. Keep the supernodal solver;
it is the fast path. This only reopens if a binary ever leaves this machine.
