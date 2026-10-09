# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SFTP delivery of a finished output directory to the Windows desktop."""

import json
import os
import subprocess
from zyg_workflows.runtime import _agent_log
from zyg_workflows.runtime import _ams_now
from zyg_workflows.subproc_registry import _finish_subproc
from zyg_workflows.stage_runner.prompts import _is_test_pid
from zyg_workflows.subproc_registry import _register_subproc
from zyg_workflows.runtime import _runtime_path
from zyg_workflows import provenance_seal as _seal

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


def _scp_output_to_windows(out_dir: str, pipeline_id: str):
    """Transfer output clips (+ their .srt sidecars) to Windows desktop via SFTP.
    Each run lands in its own dated subfolder so clips never overwrite each other.

    Smoke / gatecheck / other TEST runs are never delivered (P-03, 2026-08-25:
    the 621 s silent Florence smoke went to the Desktop under a dated production
    folder). Three independent signals, any one of which keeps the run local:
    the id prefix, the SMOKE_RUN marker the pipeline writes into out_dir, and
    ZYG_NO_DELIVERY=1 in the environment (set by the GUI smoke launcher)."""
    try:
        try:
            from zyg_workflows.pipeline_common import is_smoke_output_dir as _is_smoke_dir

            _smoke_dir = _is_smoke_dir(out_dir)
        except Exception:
            _smoke_dir = bool(out_dir) and os.path.isfile(os.path.join(out_dir, 'SMOKE_RUN'))
        if _is_test_pid(pipeline_id) or _smoke_dir or os.environ.get('ZYG_NO_DELIVERY') == '1':
            _msg = 'smoke/test run — Desktop delivery skipped'
            _zyg_log.info(f'[SFTP] {_msg} ({pipeline_id})')
            _agent_log('INFO', 'SCP', pipeline_id, 'Output Transfer', _msg)
            return
        cfg_path = _runtime_path('output_scp_config.json')
        with open(cfg_path) as _cf:
            cfg = json.load(_cf)
        if not cfg.get('enabled'):
            return
        host = cfg.get('host', '').strip()
        if not host:
            return
        user = cfg.get('user', '').strip()
        remote_base = cfg.get('remote_path', '').strip()
        ssh_key = cfg.get('ssh_key', '').strip()

        _names = os.listdir(out_dir)
        mp4s = sorted(f for f in _names if f.endswith('.mp4'))
        if not mp4s:
            _agent_log(
                'WARNING',
                'SCP',
                pipeline_id,
                'Output Transfer',
                '⚠️ No clips to transfer — output dir has no .mp4 files',
            )
            return
        # P-13: the documentary never burns captions — the .srt sidecar IS the
        # subtitle track, so a Desktop copy without it has no captions at all.
        srts = sorted(f for f in _names if f.endswith('.srt'))

        # 2026-10-06: the last gate before a file leaves this machine. Anything already
        # sealed upstream ships as it is; anything else is signed here, with 'egress' as
        # the pipeline, because a deliverable without a content credential cannot say
        # what made it. The seal is fail-safe, so under the default ZYG_C2PA=warn an
        # unsignable clip is still delivered — under ZYG_C2PA=strict it is not.
        strict = (os.environ.get('ZYG_C2PA', 'warn') or '').strip().lower() == 'strict'
        _sealed_mp4s = []
        for _clip in mp4s:
            _clip_path = os.path.join(out_dir, _clip)
            if not _seal.is_sealed(_clip_path):
                _res = _seal.seal(
                    _clip_path,
                    pipeline='egress',
                    run_id=pipeline_id,
                    log_fn=lambda _m: _zyg_log.info(_m),
                )
                if strict and _res.get('ok') is not True:
                    _refused = f'[seal] refused to ship unsealed {_clip}'
                    _zyg_log.info(_refused)
                    _agent_log('ERROR', 'SCP', pipeline_id, 'Output Transfer', _refused)
                    continue
            _sealed_mp4s.append(_clip)
        mp4s = _sealed_mp4s
        clips = mp4s + srts

        # Each run gets its own dated subfolder → clips never overwrite previous runs
        run_date = _ams_now().strftime('%Y-%m-%d_%H%M')
        remote_path = f'{remote_base}/{run_date}'

        import tempfile as _tmp

        _batch_file = _tmp.NamedTemporaryFile(mode='w', suffix='.sftp', delete=False)
        # mkdir -p equivalent: sftp mkdir is silent if dir already exists
        _batch_file.write(f'-mkdir "{remote_base}"\n')
        _batch_file.write(f'-mkdir "{remote_path}"\n')
        _batch_file.write(f'cd "{remote_path}"\n')
        for clip in sorted(clips):
            _batch_file.write(f'put "{os.path.join(out_dir, clip)}"\n')
        _batch_file.write('bye\n')
        _batch_file.close()

        cmd = ['sftp', '-i', ssh_key, '-o', 'StrictHostKeyChecking=no', '-b', _batch_file.name, f'{user}@{host}']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _register_subproc(proc.pid, f'sftp → {host} ({len(clips)} clips → {run_date})', pipeline_id)
        _, stderr = proc.communicate(timeout=600)
        _finish_subproc(proc.pid, ok=(proc.returncode == 0))
        try:
            os.unlink(_batch_file.name)
        except OSError as _exc:
            _zyg_log.debug('temp batch file cleanup skipped: %s', _exc)

        if proc.returncode == 0:
            msg = (
                f'📤 {len(mp4s)} clips'
                + (f' + {len(srts)} subtitle file(s)' if srts else '')
                + f' → Windows Desktop: {remote_path}'
            )
            _zyg_log.info(f'[SFTP] {msg}')
            _agent_log('INFO', 'SCP', pipeline_id, 'Output Transfer', msg)
        else:
            err = stderr.decode(errors='replace')[:600]
            _zyg_log.info(f'[SFTP ERROR] {err}')
            _agent_log(
                'ERROR',
                'SCP',
                pipeline_id,
                'Output Transfer',
                f'❌ SFTP to Windows failed (exit {proc.returncode}): {err}',
            )
    except Exception as _e:
        _zyg_log.info(f'[SFTP ERROR] {_e}')
        _agent_log('ERROR', 'SCP', pipeline_id, 'Output Transfer', f'❌ SFTP transfer crashed — exception: {_e}')
