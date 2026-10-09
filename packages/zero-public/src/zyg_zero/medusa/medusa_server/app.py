# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Flask app object, its limits, the IP gate, the Resources blueprint and the favicons.

Moved verbatim out of medusa_server.py (lines 37-62), save for the BASE_DIR line
noted below.
"""

import os

from flask import Flask

import medusa_ipgate
import medusa_resources

app = Flask(__name__)

PORT = 5300
# The one line this split could not move verbatim: BASE_DIR must keep naming the
# medusa/ folder — favicon.png/.ico sit there, and /api/vicky/info publishes it as
# "Medusa's own folder" — while this module now lives one level deeper, inside the
# medusa_server/ package. Hence the extra dirname; the value is unchanged.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Saved pages are big — a Chrome "single file" .mhtml of a photo gallery runs to
# tens of MB because every picture is embedded in it. Flask's default is
# unlimited; this is a ceiling, not a target.
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024

# ── Client IP allowlist ──────────────────────────────────────────────────────
# Shared with medusa_presets.py (:5301) — see medusa_ipgate.py for the trust
# model and the confused-deputy problem both apps create. Configure with
# MEDUSA_ALLOWED_IPS; loopback is always allowed so a bad value cannot lock the
# operator out.
medusa_ipgate.install(app, service_name='medusa_server:5300')

# Resources tab (/api/resources/*) — saved-page upload and per-set extraction.
# Registered after the IP gate so its before_request guard covers these routes
# too; they write to the shared Training import root.
medusa_resources.install(app)

# Favicon — user-supplied Medusa artwork, cropped to the head + snake hair.
# Files (favicon.png 256px, favicon.ico multi-size) live next to this script.
FAVICON_PNG = os.path.join(BASE_DIR, 'favicon.png')
FAVICON_ICO = os.path.join(BASE_DIR, 'favicon.ico')
