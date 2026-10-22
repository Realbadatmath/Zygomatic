# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for zyg_dashboard.bp_integrity_ops_steps.steps_stack.

Every probe the module makes — nvidia-smi, /proc, ss, systemctl, the ComfyUI
and Ollama HTTP endpoints, the Anthropic SDK and the zyg_workflows services —
is monkeypatched, and every root it derives is repointed inside tmp_path. No
test reaches a real port, a real GPU, or anything the repo tracks.
"""

import builtins
import importlib
import importlib.util
import json
import os
import sys
import threading
import types

import pytest
import zyg_workflows as wf


class _NativeStubFinder:
    """Empty stand-ins for the native stack this package's `__init__` drags in."""

    ROOTS = ('numpy', 'matplotlib')

    def find_spec(self, name, path=None, target=None):
        return importlib.util.spec_from_loader(name, self) if name.split('.')[0] in self.ROOTS else None

    def create_module(self, spec):
        mod = types.ModuleType(spec.name)
        mod.__path__ = []
        mod.__getattr__ = lambda attr: types.SimpleNamespace()
        return mod

    def exec_module(self, module):
        """Nothing to execute: the stand-in is empty by design."""


def _import_under_test():
    """Import the module under test past two hazards that sit in front of it.

    coverage.py resolves `--cov=<module>` by importing it inside
    `sys_modules_saved()` and then dropping every entry that import added. The
    chain reaches matplotlib -> numpy, whose extension stays initialised while
    its `sys.modules` entries are gone, so the next real `import numpy` dies
    with "cannot load module more than once per process"; empty stand-ins let
    it finish (no step under test touches numpy). And `constants.py` imports
    the Flask GUI package, which builds the app and starts ~19 watcher threads
    — tests/api/conftest.py imports it with a session key in the environment
    and `Thread.start` neutered; this is the same guard, for runs that get here
    first.
    """
    try:
        importlib.import_module('numpy')
    except ImportError:
        sys.meta_path.insert(0, _NativeStubFinder())

    os.environ.setdefault('CREWAI_PAGE_LOAD_DEBUG', '0')
    os.environ.setdefault('FLASK_SECRET_KEY', 'a' * 64)
    real_start = threading.Thread.start
    # The Otel exporter is the exception the API harness documents: its atexit handler
    # joins the thread, and joining one that never started raises at interpreter exit.
    threading.Thread.start = lambda self: real_start(self) if self.name.startswith('Otel') else None
    try:
        from zyg_dashboard.bp_integrity_ops_steps import constants, steps_stack
    finally:
        threading.Thread.start = real_start
    return constants, steps_stack


C = M = None


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """Every root the module derives, repointed inside tmp_path, which is returned:
    file specs are tmp-relative, so 'comfy/models/vae/x' is what the probes read.

    The import is deferred to here, not done at collection: the GUI package it
    reaches puts its own tree on `sys.path`, and an `importorskip` elsewhere in
    the suite changes verdict when that happens before collection finishes.
    """
    global C, M
    if M is None:
        C, M = _import_under_test()
    for name in [n for n in os.environ if n.startswith('ZYG_')] + ['ANTHROPIC_API_KEY']:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / 'comfy' / 'models').mkdir(parents=True)
    (tmp_path / 'hub').mkdir()
    for mod in (C, M):
        monkeypatch.setattr(mod, '_COMFY_ROOT', str(tmp_path / 'comfy'), raising=False)
        monkeypatch.setattr(mod, '_COMFY_MODELS', str(tmp_path / 'comfy' / 'models'), raising=False)
    monkeypatch.setattr(C, '_HF_HUB', str(tmp_path / 'hub'))
    monkeypatch.setattr(M.paths, 'ZYG_HOME', tmp_path, raising=False)
    monkeypatch.setattr(M.paths, 'ZYG_FLUX_ROOT', tmp_path / 'flux', raising=False)
    monkeypatch.setattr(M.paths, 'ZYG_REALESRGAN_ROOT', tmp_path / 'esrgan', raising=False)
    monkeypatch.setattr(M, 'exe', lambda n: n)
    return tmp_path


def _make(root, specs):
    """Create tmp-relative files — a spec ending in '/' becomes a directory."""
    for spec in specs:
        path = root / spec
        (path if spec.endswith('/') else path.parent).mkdir(parents=True, exist_ok=True)
        if not spec.endswith('/'):
            path.write_bytes(b'x' * 16)


def _fake_mod(monkeypatch, dotted, **attrs):
    """Install a stub module (and, for zyg_workflows.X, the package attribute)."""
    mod = types.ModuleType(dotted)
    for key, val in attrs.items():
        setattr(mod, key, val)
    monkeypatch.setitem(sys.modules, dotted, mod)
    if dotted.startswith('zyg_workflows.'):
        monkeypatch.setattr(wf, dotted.split('.', 1)[1], mod, raising=False)
    return mod


def _unimportable(monkeypatch, dotted):
    """Make `from zyg_workflows import mod` raise, whatever is on disk."""
    monkeypatch.setitem(sys.modules, dotted, None)
    monkeypatch.delattr(wf, dotted.split('.', 1)[1], raising=False)


def _proc(monkeypatch, check_output=None, run=None):
    """Replace the module's `subprocess` with the two calls it makes."""

    def _refuse(*a, **k):
        raise AssertionError('unexpected subprocess call')

    monkeypatch.setattr(
        M, 'subprocess', types.SimpleNamespace(check_output=check_output or _refuse, run=run or _refuse)
    )


def _redirect_open(monkeypatch, tmp_path, mapping):
    """Serve the given absolute paths from tmp files (None = not found)."""
    real_open = builtins.open
    files = {}
    for i, (path, text) in enumerate(mapping.items()):
        if text is None:
            files[path] = None
            continue
        files[path] = tmp_path / 'proc' / str(i)
        files[path].parent.mkdir(parents=True, exist_ok=True)
        files[path].write_text(text)

    def fake_open(path, *a, **k):
        if str(path) in files:
            if files[str(path)] is None:
                raise FileNotFoundError(path)
            return real_open(files[str(path)], *a, **k)
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, 'open', fake_open)


def _urlopen(mapping):
    """safe_urlopen stub: first matching url fragment wins; a value may raise."""

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode()

    def safe_urlopen(url, timeout=None):
        for fragment, payload in mapping.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return _Resp(payload)
        raise AssertionError(f'unexpected url {url}')

    return safe_urlopen


def _raiser(exc):
    """A callable that raises, whatever it is handed."""

    def _raise(*a, **k):
        raise exc

    return _raise


def _expect(result, status, fragments):
    got, detail = result
    assert got == status
    for fragment in fragments:
        assert fragment in detail


# ── Hardware ─────────────────────────────────────────────────────────────────
_ROW_FREE = b'NVIDIA RTX 6000 Ada, 49140, 20000, 29140\n'
_ROW_FULL = b'NVIDIA RTX 6000 Ada, 49140, 45044, 4096\n'
_APPS = b'12000, /opt/comfyui/.venv/bin/python\n4000, /usr/bin/ollama\n512, /usr/bin/weird\n'


def _smi(row=_ROW_FREE, apps=_APPS):
    def check_output(cmd, timeout=None):
        payload = apps if 'compute-apps' in cmd[1] else row
        if payload is None:
            raise OSError('nvidia-smi: not found')
        return payload

    return check_output


def test_hw_vram_without_nvidia_smi_warns(stack, monkeypatch):
    _proc(monkeypatch, check_output=_smi(row=None))
    _expect(M._step_hw_vram(False), 'warn', ('nvidia-smi unavailable',))


def test_hw_vram_with_a_free_card_passes_and_lists_holders(stack, monkeypatch):
    _proc(monkeypatch, check_output=_smi())
    free = '28.5 GB free / 48 GB total (41% used, all processes)'
    _expect(M._step_hw_vram(False), 'pass', (free, 'held by: ComfyUI 11.7 GB, Ollama 3.9 GB, weird 0.5 GB'))


def test_hw_vram_holder_breakdown_failure_is_cosmetic(stack, monkeypatch):
    _proc(monkeypatch, check_output=_smi(apps=None))
    status, detail = M._step_hw_vram(False)
    assert status == 'pass'
    assert 'held by' not in detail


@pytest.mark.parametrize(
    ('gpu_busy', 'active', 'status', 'fragment'),
    [
        (False, lambda: False, 'warn', 'resident models are holding the card'),
        (False, lambda: True, 'pass', 'GPU job running (expected)'),
        (True, _raiser(OSError('runtime dir gone')), 'pass', 'GPU job running (expected)'),
        (False, _raiser(RuntimeError('no runtime state')), 'warn', 'resident models are holding the card'),
    ],
)
def test_hw_vram_on_a_full_card(stack, monkeypatch, gpu_busy, active, status, fragment):
    _proc(monkeypatch, check_output=_smi(row=_ROW_FULL))
    monkeypatch.setattr(M, '_gpu_work_active', active)
    _expect(M._step_hw_vram(gpu_busy), status, (fragment,))


_MEMINFO = 'MemTotal: {total} kB\nMemAvailable: {avail} kB\nBuffers: 500000 kB\nCached: 2000000 kB\nnoise\n'


@pytest.mark.parametrize(('avail_kb', 'status'), [(40 * 1024**2, 'pass'), (8 * 1024**2, 'warn'), (1 * 1024**2, 'fail')])
def test_hw_ram_thresholds(stack, monkeypatch, tmp_path, avail_kb, status):
    _redirect_open(monkeypatch, tmp_path, {'/proc/meminfo': _MEMINFO.format(total=64 * 1024**2, avail=avail_kb)})
    _expect(M._step_hw_ram(), status, ('64 GB total', 'buffers+cache: 2.4 GB'))


def test_hw_ram_unreadable_meminfo_warns(stack, monkeypatch, tmp_path):
    _redirect_open(monkeypatch, tmp_path, {'/proc/meminfo': None})
    assert M._step_hw_ram()[0] == 'warn'


@pytest.mark.parametrize(('free_gb', 'status'), [(400, 'pass'), (100, 'warn'), (10, 'fail')])
def test_hw_disk_thresholds(stack, monkeypatch, free_gb, status):
    total, free = 1000 * 1024**3, free_gb * 1024**3
    usage = types.SimpleNamespace(free=free, total=total, used=total - free)
    monkeypatch.setattr(M, '_shu_ig', types.SimpleNamespace(disk_usage=lambda p: usage))
    _expect(M._step_hw_disk(), status, (f'{free_gb} GB free / 1000 GB total',))


def test_hw_disk_failure_warns(stack, monkeypatch):
    monkeypatch.setattr(M, '_shu_ig', types.SimpleNamespace(disk_usage=_raiser(OSError('no such partition'))))
    assert M._step_hw_disk() == ('warn', 'no such partition')


def test_hw_cuda_driver_reports_the_smi_line(stack, monkeypatch):
    _proc(monkeypatch, check_output=lambda cmd, timeout=None: b'RTX 6000 Ada, 580.95.05, 49140 MiB\n')
    assert M._step_hw_cuda_driver() == ('pass', 'RTX 6000 Ada, 580.95.05, 49140 MiB')


def test_hw_cuda_driver_without_smi_warns(stack, monkeypatch):
    _proc(monkeypatch, check_output=_smi(row=None))
    _expect(M._step_hw_cuda_driver(), 'warn', ('nvidia-smi not available:',))


# ── ComfyUI, Ollama, Anthropic ───────────────────────────────────────────────
_STATS = {'system': {'comfyui_version': '0.3.69'}}
_QUEUE = {'queue_running': [1], 'queue_pending': [2, 3]}
_LISTENER = 'LISTEN 0 2048 *:8188 users:(("python",pid=4242,fd=7))'
_CG_UNIT = '0::/user.slice/comfyui.service\n'
_CG_OUT = '0::/user.slice/session-3.scope\n'


def _comfy(monkeypatch, tmp_path, enabled=True, stats=_STATS, ss='', cgroup=None, unit='active running', boom=False):
    _fake_mod(
        monkeypatch,
        'zyg_workflows._comfy_client',
        _url=lambda p: f'http://127.0.0.1:8188{p}',
        COMFY_PORT=8188,
        is_enabled=lambda: enabled,
    )
    _fake_mod(monkeypatch, 'zyg_workflows.net', safe_urlopen=_urlopen({'/system_stats': stats, '/queue': _QUEUE}))

    def run(cmd, **kwargs):
        if cmd[1] == '-ltnpH':
            return types.SimpleNamespace(stdout=ss)
        if boom:
            raise OSError('systemctl missing')
        return types.SimpleNamespace(stdout=unit)

    _proc(monkeypatch, run=run)
    _redirect_open(monkeypatch, tmp_path, {'/proc/4242/cgroup': cgroup})


_COMFY_CASES = [
    ({'stats': OSError('connection refused')}, 'fail', ('not reachable on :8188 (connection refused)',)),
    ({'enabled': False}, 'warn', ('ComfyUI 0.3.69 on :8188 | queue: 1 running, 2 pending', 'USE_COMFYUI is off')),
    ({}, 'pass', ('listener pid not visible — systemd ownership unchecked',)),
    ({'ss': _LISTENER, 'cgroup': _CG_UNIT}, 'pass', ('pid 4242 under comfyui.service',)),
    ({'ss': _LISTENER, 'cgroup': _CG_OUT}, 'warn', ('pid 4242 runs OUTSIDE comfyui.service (unit active/running)',)),
    ({'ss': _LISTENER, 'cgroup': _CG_OUT, 'unit': ''}, 'warn', ('OUTSIDE comfyui.service (unit unknown)',)),
    ({'ss': _LISTENER, 'cgroup': _CG_OUT, 'boom': True}, 'warn', ('OUTSIDE comfyui.service (unit unknown)',)),
]


@pytest.mark.parametrize(('kwargs', 'status', 'fragments'), _COMFY_CASES)
def test_comfyui_server(stack, monkeypatch, kwargs, status, fragments):
    _comfy(monkeypatch, stack, **kwargs)
    _expect(M._step_comfyui_server(), status, fragments)


_TAGS = {'models': [{'name': 'qwen3:32b', 'size': 20 * 1024**3}, {'name': 'llama3.1:8b'}]}
_OLLAMA = 'http://127.0.0.1:11434'


def test_ollama_service_lists_models(stack, monkeypatch):
    _fake_mod(monkeypatch, 'zyg_workflows.net', safe_urlopen=_urlopen({'/api/tags': _TAGS}))
    _expect(M._step_ollama_service(_OLLAMA), 'pass', ('2 models: qwen3:32b, llama3.1:8b',))


def test_ollama_service_down_fails(stack, monkeypatch):
    _fake_mod(monkeypatch, 'zyg_workflows.net', safe_urlopen=_urlopen({'/api/tags': OSError('refused')}))
    assert M._step_ollama_service(_OLLAMA) == ('fail', 'Not reachable: refused')


@pytest.mark.parametrize(
    ('tags', 'model_id', 'status', 'fragment'),
    [
        (_TAGS, 'qwen3:32b', 'pass', 'Available 20.0 GB | writer'),
        (_TAGS, 'llama3.1:8b', 'pass', 'Available  | writer'),
        (_TAGS, 'qwen3:8b', 'warn', 'Partial match only (exact tag "qwen3:8b" not found)'),
        (_TAGS, 'mistral:7b', 'warn', 'Not pulled — run: ollama pull mistral:7b'),
        (OSError('refused'), 'any:1b', 'warn', 'Could not check: refused'),
    ],
)
def test_ollama_model_check_verdicts(stack, monkeypatch, tags, model_id, status, fragment):
    _fake_mod(monkeypatch, 'zyg_workflows.net', safe_urlopen=_urlopen({'/api/tags': tags}))
    _expect(M._step_ollama_model_check(_OLLAMA, model_id, 'writer')(), status, (fragment,))


def test_anthropic_api_without_a_key_fails(stack):
    _expect(M._step_anthropic_api(), 'fail', ('ANTHROPIC_API_KEY not set',))


@pytest.mark.parametrize(
    ('ids', 'exc', 'status', 'fragment'),
    [
        (None, RuntimeError('401 invalid x-api-key'), 'fail', 'models endpoint refused the key'),
        (['claude-sonnet-4-6-20260101'], None, 'warn', 'not listed for this key: claude-haiku-4-5'),
        (['claude-sonnet-4-6-x', 'claude-haiku-4-5-x'], None, 'pass', 'credit balance is not visible from here'),
    ],
)
def test_anthropic_api_with_a_key(stack, monkeypatch, ids, exc, status, fragment):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')
    models = types.SimpleNamespace(
        list=lambda limit=None: _raiser(exc)() if exc else [types.SimpleNamespace(id=i) for i in ids]
    )
    _fake_mod(monkeypatch, 'anthropic', Anthropic=lambda **kwargs: types.SimpleNamespace(models=models))
    _expect(M._step_anthropic_api(), status, (fragment,))


# ── Weights on disk: one table, every verdict ────────────────────────────────
_MD = 'comfy/models/'
_QWEN_T2I = (
    _MD + 'diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors',
    _MD + 'text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors',
    _MD + 'vae/qwen_image_vae.safetensors',
)
_QEDIT = _MD + 'diffusion_models/qwen_image_edit_2509_bf16.safetensors'
_QEDIT8 = _MD + 'diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors'
_ANGLES = _MD + 'loras/a.safetensors'
_ANG_ENV = {'ZYG_QWEN_EDIT_ANGLES_LORA': ' a.safetensors '}
_KLEIN = (_MD + 'text_encoders/qwen_3_4b.safetensors', _MD + 'vae/flux2-vae.safetensors')
_K_DIST = _MD + 'diffusion_models/flux-2-klein-4b.safetensors'
_K_BASE = _MD + 'diffusion_models/flux-2-klein-base-4b.safetensors'
_K_LORA = _MD + 'loras/ada_klein.safetensors'
_INPAINT = _MD + 'controlnet/Qwen-Image-InstantX-ControlNet-Inpainting.safetensors'
_ESR = (_MD + 'upscale_models/RealESRGAN_x2.pth', 'esrgan/RealESRGAN_x4plus.pth')
_WAN_I2V = (
    _MD + 'diffusion_models/Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors',
    _MD + 'text_encoders/umt5-xxl-enc-bf16.safetensors',
    _MD + 'clip_vision/open-clip-xlm-roberta-large-vit-huge-14_visual_fp32.safetensors',
    _MD + 'vae/Wan2_1_VAE_bf16.safetensors',
)
_WAN_HF = 'hub/models--Wan-AI--Wan2.1-I2V-14B-480P-Diffusers/snapshots/a/w.safetensors'
_SAGE_ENV = {'ZYG_USE_COMFYUI': '1', 'ZYG_WAN_ATTENTION': 'sageattn'}
_WAN22 = (
    _MD + 'diffusion_models/Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_scaled_KJ.safetensors',
    _MD + 'diffusion_models/Wan2_2-I2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors',
    _MD + 'loras/wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors',
    _MD + 'loras/wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors',
)
_VACE = _WAN_I2V[1:] + (
    _MD + 'diffusion_models/t2v.safetensors',
    _MD + 'diffusion_models/vace.safetensors',
    _MD + 'loras/wan_chars/ada.safetensors',
    _MD + 'loras/wan_chars/bo.safetensors',
    _MD + 'loras/wan_props/ball.safetensors',
)
_VACE_ENV = {'ZYG_WAN_T2V_MODEL': 't2v.safetensors', 'ZYG_WAN_VACE_MODULE': 'vace.safetensors'}
_ANIMATE = (
    _MD + 'diffusion_models/Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors',
    _MD + 'text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors',
    _MD + 'vae/wan_2.1_vae.safetensors',
    _MD + 'clip_vision/clip_vision_h.safetensors',
)
_SAGE = 'comfy/.venv/lib/python3.12/site-packages/sageattention-2.2.0.dist-info/'

_FS_CASES = [
    ('qwen_t2i', {}, (), 'fail', ('Qwen-Image-2512 UNet missing',)),
    ('qwen_t2i', {}, _QWEN_T2I[:1], 'fail', ('graph inputs missing: text_encoders/qwen_2.5',)),
    ('qwen_t2i', {'ZYG_VIDEO_STILL_FAMILY': ' KLEIN '}, _QWEN_T2I, 'pass', ('anchor-still family: klein',)),
    ('qwen_t2i', {'ZYG_VIDEO_STILL_FAMILY': ' '}, _QWEN_T2I, 'pass', ('anchor-still family: qwen',)),
    ('qwen_edit', {}, (), 'fail', ('no Qwen-Image-Edit UNet resolvable (on disk: none)',)),
    ('qwen_edit', {}, (_QEDIT, _QEDIT8), 'warn', ('MISSING', 'not selected: qwen_image_edit_2509_f')),
    ('qwen_edit', _ANG_ENV, (_QEDIT, _ANGLES), 'pass', ('angle LoRA: a.safetensors |',)),
    ('klein', {}, (), 'fail', ('missing UNet, Qwen3-4B encoder, FLUX.2 VAE',)),
    ('klein', {'ZYG_KLEIN_DISTILLED': '1'}, _KLEIN + (_K_DIST, _K_LORA), 'pass', ('(distilled)', '1 character LoRA')),
    ('klein', {}, _KLEIN + (_K_BASE,), 'pass', ('base, undistilled', '0 character LoRAs')),
    ('hand_fixer', {'ZYG_HAND_FIXER_ENGINE': ' FLUX '}, (), 'warn', ('non-commercial',)),
    ('hand_fixer', {}, _QWEN_T2I[:1], 'warn', ('degrades to TELEA / HandDetailer',)),
    ('hand_fixer', {}, _QWEN_T2I[:1] + (_INPAINT,), 'pass', ('graph hand_fixer_qwen_inpaint',)),
    ('esrgan', {}, (), 'warn', ('missing RealESRGAN x2, x4plus',)),
    ('esrgan', {}, _ESR, 'pass', ('x2 via ComfyUI',)),
    ('wan_i2v', {}, (), 'fail', ('wan_i2v graph inputs missing',)),
    ('wan_i2v', {}, _WAN_I2V, 'warn', ('USE_COMFYUI is off', 'fallback not cached', 'attention: default')),
    ('wan_i2v', _SAGE_ENV, _WAN_I2V + (_WAN_HF,), 'pass', ('umT5-XXL + CLIP-H + VAE', 'attention: sageattn')),
    ('wan22', {}, (), 'warn', ('ZYG_WAN22 off, ZYG_WAN_LIGHTNING off',)),
    ('wan22', {'ZYG_WAN22': 'on'}, (), 'fail', ('ZYG_WAN22 ON, ZYG_WAN_LIGHTNING off',)),
    ('wan22', {'ZYG_WAN_LIGHTNING': 'true'}, _WAN22, 'pass', ('A14B HIGH + LOW experts',)),
    ('wan_vace', {}, (), 'fail', ('VACE graph inputs missing',)),
    ('wan_vace', _VACE_ENV, _VACE, 'pass', ('LoRAs: 2 character, 1 prop, 0 anti-real',)),
    ('wan_animate', {}, (), 'warn', ('wan22_animate graph inputs missing',)),
    ('wan_animate', {}, _ANIMATE, 'pass', ('Wan2.2-Animate-14B fp8',)),
    ('sageattention', {'ZYG_WAN_ATTENTION': 'sageattn'}, (), 'fail', ('ZYG_WAN_ATTENTION=sageattn',)),
    ('sageattention', {}, (), 'warn', ('not installed in the ComfyUI venv', 'ATTENTION=unset')),
    ('sageattention', {}, (_SAGE,), 'pass', ('sageattention 2.2.0 (triton)',)),
    ('diarizer', {}, (), 'warn', ('ZYG_SORTFORMER_MODEL not set',)),
    ('diarizer', {'ZYG_SORTFORMER_MODEL': '/nowhere/absent.nemo'}, (), 'fail', ('pinned diarizer missing',)),
]


@pytest.mark.parametrize(('step', 'env', 'files', 'status', 'fragments'), _FS_CASES)
def test_weights_on_disk(stack, monkeypatch, step, env, files, status, fragments):
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    _make(stack, files)
    _expect(getattr(M, '_step_' + step)(), status, fragments)


def test_diarizer_present_reports_its_size(stack, monkeypatch):
    _make(stack, ('sortformer.nemo',))
    (stack / 'sortformer.nemo').write_bytes(b'x' * 3 * 1024**2)
    monkeypatch.setenv('ZYG_SORTFORMER_MODEL', f' {stack / "sortformer.nemo"} ')
    _expect(M._step_diarizer(), 'pass', ('sortformer.nemo (3 MB)',))


# ── Steps that ask a zyg_workflows service ───────────────────────────────────
def _setup(fn, **kw):
    """Bind a row's keyword arguments to a setup helper of signature (mp, root)."""
    return lambda mp, root: fn(mp, root, **kw)


def _licence(mp, root, status):
    got = {'status': status}
    _fake_mod(mp, 'zyg_workflows.licence_provenance', load_registry=dict, classify_weight=lambda *a, **k: got)


def _tiers(mp, root, tiers):
    _fake_mod(mp, 'zyg_workflows.flux_fill_service', available_tiers=lambda use_flux_fill=True: tiers)


def _rife(mp, root):
    _fake_mod(mp, 'zyg_workflows.rife_service', _RIFE_BINARY=str(root / 'rife'), _RIFE_MODEL_DIR=str(root / 'rife-v4'))


def _gone(mp, root, dotted):
    _unimportable(mp, dotted)


def _tts(mp, root, idx=True, cbx=True, seeds=3):
    def path(name, exists):
        if exists:
            _make(root, (name,))
        return str(root / name)

    _fake_mod(
        mp,
        'zyg_workflows.tts_service',
        _INDEXTTS_PY=path('idx-python', idx),
        _INDEXTTS_WORKER=path('idx-worker', idx),
        _CHATTERBOX_PY=path('cbx-python', cbx),
        _CHATTERBOX_WORKER=path('cbx-worker', cbx),
        _SEED_POOL_DIR=str(root / 'seeds'),
        _seed_pool=lambda: ['a.wav'] * seeds,
    )


def _ace(mp, root, available):
    _fake_mod(
        mp,
        'zyg_workflows.ace_step_service',
        is_available=lambda: available,
        model_id=lambda: 'ACE-Step-1.5',
        CHECKPOINT='ace_step_v1_3.5b.safetensors',
    )


_AUDIO_FNS = ('mix_foley_into_audio', 'mix_bgm_into_video', 'get_music_for_topic')


def _audio(mp, root, full):
    _fake_mod(mp, 'zyg_workflows.audio_service', **(dict.fromkeys(_AUDIO_FNS) if full else {}))


def _whisper(mp, root, installed, model=None):
    if model:
        mp.setenv('ZYG_WHISPER_MODEL', model)
    real = importlib.util.find_spec
    found = object() if installed else None
    mp.setattr(importlib.util, 'find_spec', lambda n, *a, **k: found if n == 'faster_whisper' else real(n, *a, **k))


def _diffusers(mp, root, version=None, persistent=False):
    if persistent:
        mp.setenv('ZYG_SCHOLARLY_FLUX_PERSISTENT', 'yes')
    if version is None:
        mp.setitem(sys.modules, 'diffusers', None)
    else:
        _fake_mod(mp, 'diffusers', __version__=version)


_SDXL = _MD + 'checkpoints/sd_xl_base_1.0.safetensors'
_DYNA = _MD + 'checkpoints/DynaVisionXL.safetensors'
_TIERS = ['qwen_inpaint_comfy', 'cv2_telea']
_ACE_CK = _MD + 'checkpoints/ace_step_v1_3.5b.safetensors'
_WHISP = 'hub/models--Systran--faster-whisper-large-v3/snapshots/a/model.bin'
_WHISP_MED = 'hub/models--Systran--faster-whisper-medium/snapshots/a/model.bin'
_SCHNELL = 'flux/flux1-schnell/transformer/diffusion_pytorch_model.safetensors'

_SVC_CASES = [
    (_setup(_licence, status='cleared'), 'sdxl', (), 'fail', ('no SDXL checkpoints in checkpoints/',)),
    (_setup(_licence, status='cleared'), 'sdxl', (_SDXL,), 'pass', ('sd_xl_base_1.0 [cleared]',)),
    (_setup(_licence, status='open question'), 'sdxl', (_DYNA,), 'pass', ('1 not cleared for commercial use',)),
    (_setup(_tiers, tiers=[]), 'anatomy_repair', (), 'fail', ('no licence-clean repair tier can run',)),
    (_setup(_tiers, tiers=['cv2_telea']), 'anatomy_repair', (), 'warn', ('cv2 TELEA only',)),
    (_setup(_tiers, tiers=_TIERS), 'anatomy_repair', (), 'pass', ('tiers: qwen_inpaint_comfy → cv2_telea',)),
    (_rife, 'rife', (), 'warn', ('temporal repair skipped',)),
    (_rife, 'rife', ('rife', 'rife-v4/'), 'pass', ('rife-ncnn-vulkan + rife-v4',)),
    (_setup(_gone, dotted='zyg_workflows.tts_service'), 'tts_engines', (), 'fail', ('tts_service not importable',)),
    (_setup(_tts, seeds=0), 'tts_engines', (), 'fail', ('no voice seeds in',)),
    (_setup(_tts, idx=False, cbx=False), 'tts_engines', (), 'fail', ('neither IndexTTS-2 nor Chatterbox',)),
    (_setup(_tts, idx=False), 'tts_engines', (), 'warn', ('running on the Chatterbox fallback (3 seeds)',)),
    (_setup(_tts, cbx=False), 'tts_engines', (), 'warn', ('IndexTTS-2 has no safety net (3 seeds)',)),
    (_setup(_tts), 'tts_engines', (), 'pass', ('IndexTTS-2 + Chatterbox workers present, 3 seed voices',)),
    (_setup(_ace, available=True), 'ace_step', (), 'pass', ('ACE-Step-1.5 via ComfyUI native nodes | MIT',)),
    (_setup(_ace, available=False), 'ace_step', (), 'warn', ('ACE-Step checkpoint missing',)),
    (_setup(_ace, available=False), 'ace_step', (_ACE_CK,), 'warn', ('ComfyUI server unreachable',)),
    (_setup(_audio, full=True), 'infra_audio_svc', (), 'pass', ('foley SFX, BGM mix, Claude mood override',)),
    (_setup(_audio, full=False), 'infra_audio_svc', (), 'pass', ('audio_service ready — loaded',)),
    (_setup(_gone, dotted='zyg_workflows.audio_service'), 'infra_audio_svc', (), 'warn', ('audio_service',)),
    (_setup(_whisper, installed=False), 'asr_whisper', (), 'fail', ('faster_whisper not installed',)),
    (_setup(_whisper, installed=True), 'asr_whisper', (), 'warn', ('faster-whisper large-v3 not cached',)),
    (_setup(_whisper, installed=True), 'asr_whisper', (_WHISP,), 'pass', ('faster-whisper large-v3 cached',)),
    (_setup(_whisper, installed=True, model='medium'), 'asr_whisper', (_WHISP_MED,), 'pass', ('medium cached',)),
    (_setup(_diffusers), 'flux_schnell', (), 'fail', ('documentary stills cannot render',)),
    (_setup(_diffusers), 'flux_schnell', ('flux/flux1-schnell/',), 'fail', ('diffusers not importable',)),
    (_setup(_diffusers, version='0.36.0'), 'flux_schnell', (_SCHNELL,), 'pass', ('via diffusers 0.36.0',)),
    (_setup(_diffusers, version='0.36.0', persistent=True), 'flux_schnell', (_SCHNELL,), 'pass', ('persistent',)),
]


@pytest.mark.parametrize(('setup', 'step', 'files', 'status', 'fragments'), _SVC_CASES)
def test_service_backed_steps(stack, monkeypatch, setup, step, files, status, fragments):
    _make(stack, files)
    setup(monkeypatch, stack)
    _expect(getattr(M, '_step_' + step)(), status, fragments)
