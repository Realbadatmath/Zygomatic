# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bg_remove_service.py — one-click background removal for Picture Studio.

CPU-only, in-process, via rembg's u2net model (MIT-licensed weights,
Apache-2.0 library) — no GPU, no ComfyUI graph. Nothing in this codebase's
existing ComfyUI custom_nodes does automatic one-click matting (only SAM2,
which needs interactive box/point prompts), so this is the one genuinely new
tool wrapper Picture Studio's edit tools need; everything else reuses an
already-working service.

The u2net weights are already cached on this box at ~/.u2net/u2net.onnx
(rembg's default cache path) — no model download happens here, only
inference. Requires `pip install rembg` in the crews venv.
"""

from __future__ import annotations

import os
from typing import Callable

_U2NET_MODEL = os.path.expanduser('~/.u2net/u2net.onnx')

_session = None


def _weights_present() -> bool:
    return os.path.isfile(_U2NET_MODEL)


def is_available() -> bool:
    if not _weights_present():
        return False
    try:
        import rembg  # noqa: F401
    except Exception:
        return False
    return True


def status_detail() -> str:
    if not _weights_present():
        return f'u2net weights missing at {_U2NET_MODEL}'
    try:
        import rembg  # noqa: F401
    except Exception as e:
        return f'rembg not importable: {type(e).__name__}: {e}'
    return 'u2net via rembg — ready'


def _get_session():
    global _session
    if _session is None:
        import rembg

        _session = rembg.new_session('u2net')
    return _session


def remove_background(src_path: str, dst_path: str, *, log_fn: Callable[[str], None] | None = None) -> str:
    """Matte the subject out of src_path, writing an RGBA PNG to dst_path.
    dst_path must end in .png — the result carries an alpha channel."""
    import rembg

    if log_fn:
        log_fn(f'rembg: removing background from {os.path.basename(src_path)}')
    with open(src_path, 'rb') as fh:
        data = fh.read()
    out = rembg.remove(data, session=_get_session())
    os.makedirs(os.path.dirname(dst_path) or '.', exist_ok=True)
    with open(dst_path, 'wb') as fh:
        fh.write(out)
    if log_fn:
        log_fn(f'rembg: wrote {os.path.basename(dst_path)}')
    return dst_path
