#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Production WSGI Server for CrewAI Video Production System
Optimized for handling multiple concurrent video processing tasks

The listening address is ``zyg_workflows.paths.BIND_HOST`` and defaults to
``127.0.0.1``: the dashboard is loopback-only unless LAN exposure is asked for
explicitly by setting ``BIND_HOST=0.0.0.0`` in the environment.
"""

import sys
import logging
import signal
import threading
import time
import webbrowser
import subprocess
import platform
from zyg_workflows.bin import exe
from zyg_workflows.paths import BIND_HOST, ZYG_DASHBOARD_URL
from zyg_dashboard.crewai_web_gui import app, require_flask_secret

_zyg_log = logging.getLogger(__name__)

# Try to import waitress, fallback to Flask development server
try:
    from waitress import serve

    WAITRESS_AVAILABLE = True
except ImportError:
    WAITRESS_AVAILABLE = False
    _zyg_log.info('Warning: Waitress not available, using Flask development server')

# Global flag for graceful shutdown
shutdown_flag = threading.Event()


def configure_production_logging():
    """Attach the production.log file handler and the stdout handler.

    Called by the server entry point only: importing this module must configure
    nothing, or every import — the import smoke, the tests, CI — leaves an empty
    production.log in whatever directory it ran from.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler('production.log'), logging.StreamHandler(sys.stdout)],
    )


def kill_existing_flask_processes():
    """Kill any existing Flask processes on port 5000"""
    try:
        system = platform.system().lower()

        if system == 'windows':
            # Windows: Find and kill processes using port 5000
            try:
                # Find processes using port 5000
                result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, check=True)

                lines = result.stdout.split('\n')
                flask_pids = []

                for line in lines:
                    if ':5000' in line and 'LISTENING' in line:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            flask_pids.append(pid)

                # Kill the processes
                for pid in flask_pids:
                    try:
                        subprocess.run(['taskkill', '/F', '/PID', pid], check=True)
                        _zyg_log.info(f'Killed existing Flask process with PID: {pid}')
                    except subprocess.CalledProcessError:
                        _zyg_log.warning(f'Could not kill process {pid}')

            except subprocess.CalledProcessError:
                _zyg_log.warning('Could not check for existing Flask processes')

        else:
            # Linux/Mac: Find and kill processes using port 5000
            try:
                # Find processes using port 5000
                result = subprocess.run([exe('lsof'), '-ti:5000'], capture_output=True, text=True, check=True)

                pids = result.stdout.strip().split('\n')

                for pid in pids:
                    if pid:
                        try:
                            subprocess.run(['kill', '-9', pid], check=True)
                            _zyg_log.info(f'Killed existing Flask process with PID: {pid}')
                        except subprocess.CalledProcessError:
                            _zyg_log.warning(f'Could not kill process {pid}')

            except subprocess.CalledProcessError:
                _zyg_log.info('No existing Flask processes found on port 5000')

        # Wait a moment for processes to fully terminate
        time.sleep(2)

    except Exception as e:
        _zyg_log.warning(f'Error during Flask process cleanup: {e}')


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    _zyg_log.info(f'Received signal {signum}, initiating graceful shutdown...')
    shutdown_flag.set()


def open_browser():
    """Open the web browser to the CrewAI dashboard"""
    try:
        # Wait a moment for the server to fully start
        time.sleep(2)
        webbrowser.open(ZYG_DASHBOARD_URL)
        _zyg_log.info(f'Browser opened automatically to {ZYG_DASHBOARD_URL}')
    except Exception as e:
        _zyg_log.warning(f'Could not open browser automatically: {e}')
        _zyg_log.info(f'Please manually open: {ZYG_DASHBOARD_URL}')


def create_production_app():
    """Create production-ready Flask app with optimizations"""

    # Serve entry: crewai_web_gui may be imported without FLASK_SECRET_KEY, but it
    # must never be served without one, and the key is never defaulted here.
    require_flask_secret()

    # Production configurations
    app.config.update(
        DEBUG=False,
        TESTING=False,
        PREFERRED_URL_SCHEME='https',
    )

    # Add production middleware
    from flask import request

    @app.before_request
    def log_request():
        _zyg_log.info(f'Request: {request.method} {request.path}')

    @app.after_request
    def log_response(response):
        _zyg_log.info(f'Response: {response.status_code}')
        return response

    return app


def run_production_server():
    """Run the production server with optimized settings"""

    configure_production_logging()

    # Kill any existing Flask processes first
    _zyg_log.info('Checking for existing Flask processes...')
    kill_existing_flask_processes()

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    _zyg_log.info('Starting CrewAI Production Server...')
    _zyg_log.info('Optimized for video production workloads')
    _zyg_log.info(f'Server will be available at: {ZYG_DASHBOARD_URL}')

    if WAITRESS_AVAILABLE:
        # Production server configuration with Waitress
        _zyg_log.info('Using Waitress production server')

        # Start browser opening in a separate thread
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()

        # Create a thread for the server
        def serve_app():
            serve(
                create_production_app(),
                host=BIND_HOST,
                port=5000,
                threads=8,  # Multiple threads for concurrent video tasks
                connection_limit=1000,  # Handle many concurrent connections
                cleanup_interval=30,  # Clean up connections every 30 seconds
                channel_timeout=120,  # 2 minute timeout for video processing
                max_request_body_size=1073741824,  # 1GB for large video files
            )

        server_thread = threading.Thread(target=serve_app, daemon=True)
        server_thread.start()

        # Wait for shutdown signal
        try:
            while not shutdown_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            _zyg_log.info('Keyboard interrupt received, shutting down...')

        _zyg_log.info('Shutting down production server...')

    else:
        # Fallback to Flask development server
        _zyg_log.info('Using Flask development server (fallback)')

        # Start browser opening in a separate thread
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()

        try:
            create_production_app().run(host=BIND_HOST, port=5000, debug=False, threaded=True)
        except KeyboardInterrupt:
            _zyg_log.info('Keyboard interrupt received, shutting down...')


if __name__ == '__main__':
    run_production_server()
