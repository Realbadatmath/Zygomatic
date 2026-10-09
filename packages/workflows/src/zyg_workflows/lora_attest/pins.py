# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""lora_attest.pins — sha256 hashing, ComfyUI model-root resolution and model_pins.json.

Verbatim sections of the original lora_attest.py (lines 212-420): the hashing
cache, model_roots/resolve_model_path, and the pins load/save/seed trio.
"""

from __future__ import annotations

from zyg_workflows.lora_attest.constants import (
    PINS_PATH,
    _ALL_FOLDERS,
    _HASH_CACHE_PATH,
    _RUNTIME_DIR,
    _SEED_GLOBS,
    _SEED_GLOBS_EXTRA,
    _ledger,
    _log_noop,
    hashlib,
    json,
    os,
    paths,
    time,
)


# ── hashing ──────────────────────────────────────────────────────────────────


def _sha256_local(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(chunk), b''):
            h.update(block)
    return h.hexdigest()


def _load_cache():
    try:
        with open(_HASH_CACHE_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_cache(cache):
    try:
        os.makedirs(_RUNTIME_DIR, exist_ok=True)
        tmp = _HASH_CACHE_PATH + f'.tmp{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=0, sort_keys=True)
        os.replace(tmp, _HASH_CACHE_PATH)
        return True
    except Exception:
        return False


def sha256_file(path, use_cache=True, log_fn=None):
    """sha256 of a file, cached on (size, mtime_ns). Returns hex str or None.

    Delegates to ``run_ledger.sha256_file`` when that module exposes it, so the
    debug stack has a single hashing implementation; falls back to a local
    chunked implementation when run_ledger is absent or older.
    """
    log = log_fn or _log_noop
    try:
        if not (path and os.path.isfile(path)):
            return None
        st = os.stat(path)
        key = os.path.realpath(path)
        sig = [int(st.st_size), int(st.st_mtime_ns)]
        cache = _load_cache() if use_cache else {}
        hit = cache.get(key)
        if use_cache and isinstance(hit, list) and len(hit) == 3 and hit[:2] == sig:
            return hit[2]
        digest = None
        rl = _ledger()
        fn = getattr(rl, 'sha256_file', None) if rl is not None else None
        if callable(fn):
            try:
                digest = fn(path)
            except Exception:
                digest = None
        if not digest:
            t0 = time.time()
            digest = _sha256_local(path)
            dt = time.time() - t0
            if dt > 2.0:
                log(f'[attest] hashed {os.path.basename(path)} ({st.st_size / 1e9:.1f} GB) in {dt:.0f}s')
        if use_cache and digest:
            cache[key] = [sig[0], sig[1], digest]
            _save_cache(cache)
        return digest
    except Exception as exc:
        log(f'[attest] hash failed for {path}: {type(exc).__name__}: {exc}')
        return None


# ── model roots + name resolution ────────────────────────────────────────────


def model_roots():
    """ComfyUI models/ roots, most-specific first. De-duplicated, existing only."""
    cands = []
    env = os.environ.get('ZYG_COMFY_MODELS', '').strip()
    if env:
        cands.extend(p for p in env.split(os.pathsep) if p.strip())
    out = str(paths.ZYG_COMFY_OUTPUT)
    cands.append(os.path.join(os.path.dirname(out.rstrip('/')), 'models'))
    cands.append(str(paths.ZYG_COMFY_ROOT / 'models'))
    roots, seen = [], set()
    for c in cands:
        c = os.path.abspath(os.path.expanduser(c))
        if c not in seen and os.path.isdir(c):
            seen.add(c)
            roots.append(c)
    return roots


def resolve_model_path(name, folders=None):
    """ComfyUI-relative model name → absolute path on disk, or None.

    ``name`` may carry a sub-folder ('wan_chars/x.safetensors'). Windows-style
    separators are normalised. Falls back to a basename search across every known
    sub-folder of every root when the declared folders miss.
    """
    if not name or not isinstance(name, str):
        return None
    rel = name.replace('\\', '/').strip().lstrip('/')
    if os.path.isabs(name) and os.path.isfile(name):
        return os.path.abspath(name)
    folders = list(folders or []) + [f for f in _ALL_FOLDERS if f not in (folders or [])]
    roots = model_roots()
    for root in roots:
        for folder in folders:
            p = os.path.join(root, folder, rel)
            if os.path.isfile(p):
                return p
    base = os.path.basename(rel)
    if base != rel:
        for root in roots:
            for folder in folders:
                p = os.path.join(root, folder, base)
                if os.path.isfile(p):
                    return p
    for root in roots:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return p
    return None


# ── pins ─────────────────────────────────────────────────────────────────────


def load_pins(pins_path=None):
    """Flat {name: sha256} map. Missing/broken pins file → {} (never raises)."""
    path = pins_path or PINS_PATH
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {}
        return {str(k): str(v).lower() for k, v in d.items() if isinstance(v, str) and len(v) == 64}
    except Exception:
        return {}


def save_pins(pins, pins_path=None):
    path = pins_path or PINS_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f'.tmp{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(dict(sorted(pins.items())), f, indent=2, sort_keys=True)
            f.write('\n')
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _pin_for(pins, name):
    """Pin lookup: exact ComfyUI-relative name first, then basename."""
    if name in pins:
        return pins[name]
    base = os.path.basename(str(name).replace('\\', '/'))
    if base in pins:
        return pins[base]
    for k, v in pins.items():
        if os.path.basename(k) == base:
            return v
    return None


def seed_pins(extra=False, pins_path=None, log_fn=None, merge=True):
    """(Re)write model_pins.json from the weights currently on disk.

    Default set: wan_chars/*.safetensors (character LoRAs), wan_props/*.safetensors
    (hero-prop LoRAs, when staged) and the Wan2.1 T2V fp8 checkpoint.
    ``extra=True`` additionally pins the VACE module, the Wan VAE and umT5.
    Returns {'ok', 'pins', 'added', 'changed', 'path'}.
    """
    import glob as _glob

    log = log_fn or _log_noop
    try:
        pins = load_pins(pins_path) if merge else {}
        before = dict(pins)
        globs = list(_SEED_GLOBS) + (list(_SEED_GLOBS_EXTRA) if extra else [])
        roots = model_roots()
        for folder, pattern in globs:
            for root in roots:
                for path in sorted(_glob.glob(os.path.join(root, folder, pattern))):
                    if not os.path.isfile(path):
                        continue
                    name = os.path.relpath(path, os.path.join(root, folder)).replace('\\', '/')
                    digest = sha256_file(path, log_fn=log)
                    if not digest:
                        log(f'[attest] seed: could not hash {name}')
                        continue
                    pins[name] = digest
        added = [k for k in pins if k not in before]
        changed = [k for k in pins if k in before and before[k] != pins[k]]
        ok = save_pins(pins, pins_path)
        log(
            f'[attest] pins {"written" if ok else "WRITE FAILED"}: '
            f'{len(pins)} entries (+{len(added)} new, {len(changed)} changed)'
        )
        return {'ok': bool(ok), 'pins': pins, 'added': added, 'changed': changed, 'path': pins_path or PINS_PATH}
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'pins': {}, 'added': [], 'changed': []}
