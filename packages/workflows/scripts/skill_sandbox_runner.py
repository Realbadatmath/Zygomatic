# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""skill_sandbox_runner.py — Isolated subprocess entrypoint for skill behavioral probes.

This script is launched by skill_sandbox.py as a child process.  Before
executing any skill code it applies:

  1. pyseccomp filter  — blocks socket/connect/bind/accept syscalls → no network
  2. resource limits   — caps CPU time, virtual memory, file size
  3. clean environment — strips all secrets / API keys from os.environ
  4. chdir to tmpdir   — skill cannot escape via relative paths

Receives a JSON payload via stdin, writes a JSON result to stdout.

Stdin JSON schema:
    {
        "code":       "<python source string to exec>",
        "entry":      "<function name to call>",       // optional
        "mock_input": { ... },                          // passed to entry fn
        "tmpdir":     "/tmp/sandbox_<id>"
    }

Stdout JSON schema:
    {
        "ok":            true/false,
        "return_value":  ...,         // stringified if not JSON-serialisable
        "stdout":        "...",
        "stderr":        "...",
        "network_block": true,        // seccomp network block active
        "error":         null | "..."
    }
"""

import json
import os
import resource
import sys
import tempfile
import traceback
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Secret patterns to strip from environment ────────────────────────────────
_SECRET_PATTERNS = (
    'KEY',
    'TOKEN',
    'SECRET',
    'PASSWORD',
    'PASSWD',
    'CREDENTIAL',
    'AUTH',
    'API',
    'OPENAI',
    'ANTHROPIC',
    'HUGGING',
    'GITHUB',
    'AWS',
    'GCP',
    'AZURE',
    'DATABASE',
    'DB_',
    'MONGO',
    'REDIS',
    'POSTGRES',
    'MYSQL',
    'PRIVATE',
)


def _clean_env(home: str) -> None:
    """Remove all environment variables that look like secrets.

    *home* becomes ``$HOME`` so the skill cannot read the real ``~/.config``,
    ``~/.ssh`` etc. — it is the per-probe sandbox directory, not shared ``/tmp``.
    """
    for key in list(os.environ.keys()):
        if any(p in key.upper() for p in _SECRET_PATTERNS):
            del os.environ[key]
    os.environ['HOME'] = home
    os.environ['PATH'] = '/usr/bin:/bin'


def _apply_resource_limits() -> None:
    """Cap CPU time (30s), virtual memory (2 GB), file size (50 MB)."""
    # CPU time: 30 seconds hard limit
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    # Virtual memory: 2 GB
    two_gb = 2 * 1024 * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (two_gb, two_gb))
    except ValueError as _exc:
        _zyg_log.warning('address space rlimit not applied, the sandbox runs without a memory cap: %s', _exc)
    # Max file write: 50 MB
    fifty_mb = 50 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (fifty_mb, fifty_mb))
    # No new processes
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))


def _apply_network_seccomp() -> bool:
    """Block all network syscalls via seccomp ERRNO(EACCES). Returns True if applied."""
    try:
        import errno as _errno
        import pyseccomp as seccomp

        f = seccomp.SyscallFilter(defaction=seccomp.ALLOW)
        # Block the syscalls needed to create/use network sockets
        for syscall in (
            'socket',
            'connect',
            'bind',
            'accept',
            'accept4',
            'listen',
            'sendto',
            'recvfrom',
            'sendmsg',
            'recvmsg',
            'socketpair',
            'socketcall',
        ):
            try:
                f.add_rule(seccomp.ERRNO(_errno.EACCES), syscall)
            except Exception as _exc:
                _zyg_log.warning('seccomp rule for %s not added, the syscall stays allowed: %s', syscall, _exc)
        f.load()
        return True
    except Exception:
        return False


def main() -> None:
    payload = json.loads(sys.stdin.read())
    code = payload.get('code', '')
    entry = payload.get('entry', '')
    mock_input = payload.get('mock_input', {})
    # No tmpdir in the payload means nobody prepared a sandbox: make a private one
    # (mkdtemp is 0o700) rather than running the probe in the shared /tmp.
    tmpdir = payload.get('tmpdir') or tempfile.mkdtemp(prefix='skill_sandbox_')

    result = {
        'ok': False,
        'return_value': None,
        'stdout': '',
        'stderr': '',
        'network_block': False,
        'error': None,
    }

    try:
        # 1. Apply network seccomp filter FIRST — pyseccomp needs the full PATH to
        #    locate libseccomp.so.2 via ldconfig (/sbin/ldconfig).  The filter is
        #    irreversible once loaded so it will still cover all subsequent code.
        result['network_block'] = _apply_network_seccomp()

        # 2. Move to sandbox tmpdir
        os.chdir(tmpdir)

        # 3. Strip secrets from environment (restricts PATH — must be AFTER seccomp)
        _clean_env(tmpdir)

        # 4. Apply resource limits
        _apply_resource_limits()

        # 5. Redirect stdout/stderr capture
        import io

        _stdout_buf = io.StringIO()
        _stderr_buf = io.StringIO()
        _real_stdout = sys.stdout
        _real_stderr = sys.stderr
        sys.stdout = _stdout_buf
        sys.stderr = _stderr_buf

        try:
            # 6. Execute skill code in isolated namespace
            _ns: dict = {}
            # Running the probe's source IS this script's job; the seccomp network
            # block, the rlimits and the throwaway cwd/HOME above are the sandbox.
            exec(compile(code, '<skill>', 'exec'), _ns)  # nosec B102  # noqa: S102  the sandbox entrypoint

            # 7. Call entry function if requested
            if entry and entry in _ns and callable(_ns[entry]):
                ret = _ns[entry](**mock_input)
                try:
                    json.dumps(ret)
                    result['return_value'] = ret
                except (TypeError, ValueError):
                    result['return_value'] = str(ret)

            result['ok'] = True
        finally:
            sys.stdout = _real_stdout
            sys.stderr = _real_stderr
            result['stdout'] = _stdout_buf.getvalue()[:4000]
            result['stderr'] = _stderr_buf.getvalue()[:4000]

    except Exception:
        result['error'] = traceback.format_exc()[-2000:]

    # Write result to real stdout
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()


if __name__ == '__main__':
    main()
