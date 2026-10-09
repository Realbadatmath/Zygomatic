#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The serve entry: ``python -m zyg_dashboard.crewai_web_gui``.

Lines 4970-5102 of the original single-file module, verbatim — its
``if __name__ == '__main__':`` block. That block ran because every launcher starts
the dashboard with ``python -m zyg_dashboard.crewai_web_gui``
(deploy/systemd/user/crewai-gui.service, deploy/dashboard_launcher.sh,
deploy/docker-entrypoint.sh); now that the module is a package, ``-m`` runs this
file instead, so the same command keeps the same meaning. Importing the package
still starts nothing that listens.

The paths the moved block builds — the ``.env`` the secrets-hardening check reads,
the zero-public server it spawns and that subprocess' working directory — come from
``zyg_dashboard.paths``, which is where the ``zyg_dashboard`` package directory is
named once.
"""

# ruff: noqa: E402  the collaborators have to be imported before the moved block runs

from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.crewai_web_gui import (
    BACKEND_DEBUG,
    BIND_HOST,
    LOGIN_DEBUG,
    PAGE_LOAD_DEBUG,
    ZYG_DASHBOARD_URL,
    _char_reload_jobs_from_disk,
    _comfy_idle_vram_sweeper_loop,
    _contact_sheet_reload_jobs_from_disk,
    _release_pipeline_vram,
    _startup_vram_sweep,
    _zyg_log,
    app,
    gui_state,
    os,
    require_flask_secret,
    sys,
    threading,
    tmp_dir,
)


if __name__ == '__main__':
    import signal as _signal
    import atexit as _atexit
    import stat as _stat

    # Serve entry: the import was allowed without a secret, starting is not.
    require_flask_secret()

    # ── Secrets hardening check ───────────────────────────────────────────────
    _env_path = str(_dash_paths.PKG_DIR.parent / '.env')  # packages/dashboard/src/.env
    if os.path.exists(_env_path):
        _mode = os.stat(_env_path).st_mode
        if _mode & (_stat.S_IRGRP | _stat.S_IROTH | _stat.S_IWGRP | _stat.S_IWOTH):
            print(
                f'[SECURITY WARNING] .env file is readable/writable by group or others!\n'
                f'  Path: {_env_path}\n'
                f'  Permissions: {oct(_mode & 0o777)}\n'
                f'  Fix with: chmod 600 "{_env_path}"',
                flush=True,
            )
            os.chmod(_env_path, 0o600)
            print('[SECURITY] .env permissions auto-corrected to 600.', flush=True)
        else:
            print(f'[SECURITY] .env permissions OK ({oct(_mode & 0o777)}).', flush=True)
    # ─────────────────────────────────────────────────────────────────────────

    def _log_exit_reason(code=0):
        print(f'[SERVER-EXIT] Process {os.getpid()} exiting (code {code})', flush=True)

    def _handle_signal(sig, frame):
        sig_name = {2: 'SIGINT', 15: 'SIGTERM'}.get(sig, f'SIG{sig}')
        print(f'[SERVER-SIGNAL] Received {sig_name} — shutting down PID {os.getpid()}', flush=True)
        sys.exit(0)

    _atexit.register(_log_exit_reason)

    def _shutdown_vram_free():
        try:
            _release_pipeline_vram('shutdown', log_fn=lambda m: print(f'[VRAM] {m}', flush=True))
        except Exception as _exc:
            _zyg_log.debug('shutdown vram release skipped: %s', _exc)

    _atexit.register(_shutdown_vram_free)
    _signal.signal(_signal.SIGTERM, _handle_signal)
    _signal.signal(_signal.SIGINT, _handle_signal)

    # ── Auto-launch zero_public_server.py ────────────────────────────────────
    def _launch_zero_server():
        """Spawn zero_public_server.py and restart it automatically if it exits.
        Skips startup if port 5001 is already bound (external instance running)."""
        import subprocess as _sp
        import time as _time
        import socket as _sock

        _zero_path = str(_dash_paths.PKG_DIR / 'zero_public_server.py')
        _zero_log = str(tmp_dir('dashboard') / 'zero_public_server.log')
        if not os.path.isfile(_zero_path):
            print(f'[ZeroLauncher] zero_public_server.py not found at {_zero_path} — skipping.', flush=True)
            return

        def _port_in_use(port: int) -> bool:
            with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
                return s.connect_ex(('127.0.0.1', port)) == 0

        # If an external instance is already running, yield entirely — don't manage it.
        if _port_in_use(5001):
            print(
                '[ZeroLauncher] Port 5001 already in use — external zero_public_server detected, skipping watchdog.',
                flush=True,
            )
            return

        _zero_proc = None
        while True:
            try:
                # If port is now occupied by an external process, stop trying
                if _port_in_use(5001) and (_zero_proc is None or _zero_proc.poll() is not None):
                    print('[ZeroLauncher] Port 5001 occupied by external process — stopping watchdog.', flush=True)
                    return
                with open(_zero_log, 'a') as _logf:
                    print(f'[ZeroLauncher] Starting zero_public_server.py (log → {_zero_log})', flush=True)
                    _zero_proc = _sp.Popen(
                        [sys.executable, _zero_path],
                        stdout=_logf,
                        stderr=_logf,
                        cwd=str(_dash_paths.PKG_DIR),
                    )
                _zero_proc.wait()
                print(
                    f'[ZeroLauncher] zero_public_server.py exited (code {_zero_proc.returncode}) — restarting in 5 s…',
                    flush=True,
                )
            except Exception as _e:
                print(f'[ZeroLauncher] Error: {_e} — retrying in 5 s…', flush=True)
            _time.sleep(5)

    _zero_thread = threading.Thread(target=_launch_zero_server, daemon=True, name='zero-launcher')
    _zero_thread.start()
    print('[ZeroLauncher] zero_public_server watchdog started.', flush=True)
    # ─────────────────────────────────────────────────────────────────────────

    print('Starting CrewAI Web GUI...')
    print(f'Open your browser and go to: {ZYG_DASHBOARD_URL}')
    try:
        gui_state._CHAR_GEN_RELOAD_DONE = False
        _n_char = _char_reload_jobs_from_disk()
        gui_state._CHAR_GEN_RELOAD_DONE = True
        if _n_char:
            print(f'[CHAR-STATE] Startup: hydrated {_n_char} character job(s) from disk', flush=True)
    except Exception as _char_boot_e:
        print(f'[CHAR-STATE] Startup hydrate warning: {_char_boot_e}', flush=True)
    try:
        _n_cs = _contact_sheet_reload_jobs_from_disk()
        gui_state._CONTACT_SHEET_RELOAD_DONE = True
        if _n_cs:
            print(f'[CONTACT-SHEET] Startup: hydrated {_n_cs} contact-sheet job(s) from disk', flush=True)
    except Exception as _cs_boot_e:
        print(f'[CONTACT-SHEET] Startup hydrate warning: {_cs_boot_e}', flush=True)
    if PAGE_LOAD_DEBUG:
        print('[PAGE_LOAD] Page load/navigation debug is ON. Set CREWAI_PAGE_LOAD_DEBUG=0 to turn off.')
    if LOGIN_DEBUG:
        print('[LOGIN_DEBUG] Session/login debug is ON. Set CREWAI_LOGIN_DEBUG=1 to enable.')
    if not BACKEND_DEBUG:
        print('[BACKEND_DEBUG] Timeline/API debug is OFF. Set CREWAI_BACKEND_DEBUG=1 to turn on.')
    _startup_vram_sweep()
    _vram_sweeper_thread = threading.Thread(
        target=_comfy_idle_vram_sweeper_loop,
        daemon=True,
        name='comfy-vram-sweeper',
    )
    _vram_sweeper_thread.start()
    print('[VRAM] Comfy idle VRAM sweeper started (ZYG_COMFY_IDLE_FREE_SEC=90, set 0 to disable).', flush=True)
    app.run(host=BIND_HOST, port=5000, debug=False, use_reloader=False, threaded=True)
