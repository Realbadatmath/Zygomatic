# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""lora_attest.gate — graph walking and the attestation gate itself.

Verbatim sections of the original lora_attest.py (lines 421-755): the node/wiring
walk, collect_model_refs, attest_graph, merge_overrides and attest_submit.
"""

from __future__ import annotations

from zyg_workflows.lora_attest.constants import (
    AttestationError,
    _MODEL_EXT,
    _NODE_FOLDERS,
    _STRENGTH_KEYS,
    _log_noop,
    _record_fallback,
    _record_gate,
    _truthy,
    os,
    time,
)
from zyg_workflows.lora_attest.pins import _pin_for, load_pins, model_roots, resolve_model_path, sha256_file


# ── graph walking ────────────────────────────────────────────────────────────


def _node_class(node):
    return str((node or {}).get('class_type') or (node or {}).get('class') or '')


def _is_output_class(cls):
    c = cls or ''
    return (
        c.startswith('Save')
        or c.startswith('Preview')
        or 'VideoCombine' in c
        or c in ('CreateVideo', 'SaveVideo', 'SaveAnimatedWEBP')
    )


def _wiring_known(graph):
    for node in (graph or {}).values():
        for v in ((node or {}).get('inputs') or {}).values():
            if isinstance(v, list):
                return True
    return False


def _reachable_nodes(graph):
    """Node ids reachable walking UPSTREAM from the graph's output nodes."""
    upstream = {nid: set() for nid in graph}
    referenced = set()
    for nid, node in graph.items():
        for v in ((node or {}).get('inputs') or {}).values():
            if isinstance(v, list) and v and isinstance(v[0], (str, int)):
                src = str(v[0])
                if src in graph:
                    upstream[nid].add(src)
                    referenced.add(src)
    sinks = [nid for nid, n in graph.items() if _is_output_class(_node_class(n))]
    if not sinks:
        sinks = [nid for nid in graph if nid not in referenced]
    seen, stack = set(), list(sinks)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(upstream.get(cur, ()))
    return seen


def _guess_kind(cls, key):
    c, k = (cls or '').lower(), (key or '').lower()
    if 'lora' in c or 'lora' in k:
        return 'lora', ['loras']
    if 'vae' in c or 'vae' in k:
        return 'vae', ['vae']
    if 'clipvision' in c.replace('_', '') or 'clip_vision' in k:
        return 'clip_vision', ['clip_vision']
    if 'textencoder' in c.replace('_', '') or 'clip' in c or 'clip' in k or 't5' in k:
        return 'text_encoder', ['text_encoders', 'clip']
    if 'controlnet' in c or 'control_net' in k:
        return 'controlnet', ['controlnet']
    if 'upscale' in c or 'upscale' in k:
        return 'upscale', ['upscale_models']
    if 'checkpoint' in c or 'unet' in c or 'model' in c or 'ckpt' in k or 'unet' in k:
        return 'checkpoint', ['diffusion_models', 'unet', 'checkpoints']
    return 'other', []


def _node_strength(node, kind):
    if kind != 'lora':
        return None
    inputs = (node or {}).get('inputs') or {}
    for k in _STRENGTH_KEYS:
        if k in inputs:
            try:
                return float(inputs[k])
            except (TypeError, ValueError):
                return None
    return None


def collect_model_refs(graph):
    """[(node_id, class, input_key, name, kind, folders)] for every model file the
    graph references. Recognised loader classes first, then any string input that
    looks like a weights filename."""
    refs = []
    for nid, node in (graph or {}).items():
        cls = _node_class(node)
        for key, val in ((node or {}).get('inputs') or {}).items():
            if not isinstance(val, str) or not val.strip():
                continue
            known = _NODE_FOLDERS.get((cls, key))
            if known:
                kind, folders = known
            elif val.lower().endswith(_MODEL_EXT):
                kind, folders = _guess_kind(cls, key)
            else:
                continue
            refs.append((str(nid), cls, key, val.strip(), kind, folders))
    return refs


# ── the gate ─────────────────────────────────────────────────────────────────


def attest_graph(graph_dict, log_fn=None, pins_path=None, run_id=None, tag='', pins=None, record=True):
    """Hash every model file a ComfyUI graph references and diff against the pins.

    Returns (never raises)::

        {'ok': True|False|None,
         'artifacts':  [{'kind','name','path','sha256','strength',
                         'node','class','pinned','status','size'}],
         'mismatches': [{'kind','name','path','reason','expected','actual','node'}],
         'unpinned':   ['name', ...],
         'wiring_checked': bool,
         'elapsed_s': float,
         'error': str            # only when ok is None
        }

    ok is False on any mismatch, True on a clean attestation, None when the graph
    carried no model references or the check itself broke (fail-safe unknown).
    """
    log = log_fn or _log_noop
    t0 = time.time()
    out = {'ok': None, 'artifacts': [], 'mismatches': [], 'unpinned': [], 'wiring_checked': False, 'elapsed_s': 0.0}
    try:
        graph = graph_dict or {}
        if not isinstance(graph, dict) or not graph:
            out['error'] = 'empty or non-dict graph'
            return out
        pinmap = load_pins(pins_path) if pins is None else dict(pins or {})
        allow_zero = _truthy(os.environ.get('ZYG_ATTEST_ALLOW_ZERO_STRENGTH'))
        refs = collect_model_refs(graph)
        if not refs:
            out['error'] = 'no model references found in graph'
            return out

        reachable = None
        if _wiring_known(graph):
            out['wiring_checked'] = True
            try:
                reachable = _reachable_nodes(graph)
            except Exception:
                reachable = None
                out['wiring_checked'] = False

        for nid, cls, _key, name, kind, folders in refs:
            path = resolve_model_path(name, folders)
            strength = _node_strength(graph.get(nid), kind)
            art = {
                'kind': kind,
                'name': name,
                'path': path,
                'sha256': None,
                'strength': strength,
                'node': nid,
                'class': cls,
                'pinned': False,
                'status': 'ok',
                'size': None,
            }
            if not path:
                art['status'] = 'missing_file'
                out['mismatches'].append(
                    {
                        'kind': kind,
                        'name': name,
                        'path': None,
                        'node': nid,
                        'reason': 'missing_file',
                        'expected': 'file on disk',
                        'actual': 'not found under ' + ', '.join(model_roots() or ['<no root>']),
                    }
                )
                out['artifacts'].append(art)
                continue
            try:
                art['size'] = int(os.path.getsize(path))
            except OSError:
                art['size'] = None
            digest = sha256_file(path, log_fn=log)
            art['sha256'] = digest
            if not digest:
                art['status'] = 'unreadable'
                out['mismatches'].append(
                    {
                        'kind': kind,
                        'name': name,
                        'path': path,
                        'node': nid,
                        'reason': 'unreadable',
                        'expected': 'sha256',
                        'actual': 'hash failed',
                    }
                )
                out['artifacts'].append(art)
                continue
            pin = _pin_for(pinmap, name)
            if pin:
                art['pinned'] = True
                if pin.lower() != digest.lower():
                    art['status'] = 'hash_mismatch'
                    out['mismatches'].append(
                        {
                            'kind': kind,
                            'name': name,
                            'path': path,
                            'node': nid,
                            'reason': 'hash_mismatch',
                            'expected': pin,
                            'actual': digest,
                        }
                    )
                    _record_fallback(
                        f'{kind}:{name}',
                        expected=pin[:16],
                        actual=digest[:16],
                        detail=f'attest {tag}: pinned weights replaced on disk',
                        run_id=run_id,
                    )
            elif pinmap:
                out['unpinned'].append(name)
            # a LoRA at strength 0 is applied to nothing — the inert-LoRA signature
            if kind == 'lora' and strength is not None and abs(strength) < 1e-6:
                if allow_zero:
                    log(f'[attest] NOTE {name} at strength 0 (allowed by env)')
                else:
                    art['status'] = 'strength_zero' if art['status'] == 'ok' else art['status']
                    out['mismatches'].append(
                        {
                            'kind': kind,
                            'name': name,
                            'path': path,
                            'node': nid,
                            'reason': 'strength_zero',
                            'expected': '> 0',
                            'actual': '0.0',
                        }
                    )
                    _record_fallback(
                        f'lora:{name}', expected='applied', actual='strength 0', detail=f'attest {tag}', run_id=run_id
                    )
            # a loader node nothing downstream consumes never touches the sampler
            if reachable is not None and nid not in reachable:
                art['status'] = 'not_wired' if art['status'] == 'ok' else art['status']
                out['mismatches'].append(
                    {
                        'kind': kind,
                        'name': name,
                        'path': path,
                        'node': nid,
                        'reason': 'not_wired',
                        'expected': 'consumed downstream',
                        'actual': f'node {nid} unreachable from graph outputs',
                    }
                )
                _record_fallback(
                    f'{kind}:{name}',
                    expected='wired into model chain',
                    actual='orphan node',
                    detail=f'attest {tag} node {nid}',
                    run_id=run_id,
                )
            out['artifacts'].append(art)

        out['ok'] = not out['mismatches']
        n_lora = sum(1 for a in out['artifacts'] if a['kind'] == 'lora')
        if out['ok']:
            log(
                f'[attest] {tag or "graph"}: PASS — {len(out["artifacts"])} artifacts '
                f'({n_lora} LoRA) hashed, {sum(1 for a in out["artifacts"] if a["pinned"])} pinned'
                + (f', {len(out["unpinned"])} unpinned' if out['unpinned'] else '')
            )
        else:
            log(f'[attest] {tag or "graph"}: FAIL — {len(out["mismatches"])} mismatch(es)')
            for m in out['mismatches']:
                log(
                    f'[attest]   {m["reason"]}: {m["name"]} '
                    f'(expected {str(m["expected"])[:24]}, got {str(m["actual"])[:40]})'
                )
        if not out['wiring_checked']:
            log('[attest] note: wiring not checkable on this graph (list inputs stripped) — orphan-LoRA check skipped')
    except Exception as exc:
        out['ok'] = None
        out['error'] = f'{type(exc).__name__}: {exc}'
        log(f'[attest] attestation broke (generation continues): {out["error"]}')
    out['elapsed_s'] = round(time.time() - t0, 3)
    if record:
        outcome = {True: 'PASS', False: 'FAIL'}.get(out['ok'], 'UNKNOWN')
        _record_gate(run_id, outcome, score=float(len(out['mismatches'])), tag=tag or 'graph')
    return out


def merge_overrides(graph, overrides=None):
    """The graph as ComfyUI will see it: template nodes + per-node input overrides."""
    merged = {}
    for nid, node in (graph or {}).items():
        node = node or {}
        merged[str(nid)] = {
            'class_type': _node_class(node),
            'inputs': {
                **(node.get('inputs') or {}),
                **((overrides or {}).get(nid) or (overrides or {}).get(str(nid)) or {}),
            },
        }
    return merged


def attest_submit(graph, overrides=None, tag='', log_fn=None, run_id=None, pins_path=None):
    """Submit-site hook. Attest the effective graph; WARN-ONLY by default.

    ``ZYG_LORA_ATTEST``: unset/anything → warn only (log + ledger, submit proceeds);
    ``strict`` → raise :class:`AttestationError` before submit on a FAIL;
    ``off``/``0`` → skip entirely (returns {'ok': None, 'skipped': ...}).

    Only AttestationError escapes; every other failure is swallowed so a broken QC
    layer can never block generation.
    """
    log = log_fn or _log_noop
    mode = os.environ.get('ZYG_LORA_ATTEST', '').strip().lower()
    if mode in ('off', '0', 'false', 'no', 'none'):
        return {'ok': None, 'skipped': 'ZYG_LORA_ATTEST=off', 'artifacts': [], 'mismatches': []}
    try:
        merged = merge_overrides(graph, overrides)
        res = attest_graph(merged, log_fn=log, pins_path=pins_path, run_id=run_id, tag=tag)
    except Exception as exc:  # belt and braces — attest_graph is already fail-safe
        log(f'[attest] hook skipped ({type(exc).__name__}: {exc})')
        return {'ok': None, 'error': f'{type(exc).__name__}: {exc}', 'artifacts': [], 'mismatches': []}
    if mode == 'strict' and res.get('ok') is False:
        detail = '; '.join(f'{m["reason"]}:{m["name"]}' for m in res.get('mismatches', [])[:4])
        raise AttestationError(f'model attestation FAILED for {tag or "graph"} — {detail}')
    return res
