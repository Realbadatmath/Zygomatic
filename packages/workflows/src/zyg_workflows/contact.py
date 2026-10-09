# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The contact address this deployment puts in outgoing User-Agent strings.

OSM, OpenAlex and Unpaywall all ask an automated client to identify a reachable
human. Set ZYG_CONTACT_EMAIL to yours; the default is deliberately unroutable.
"""

from __future__ import annotations

import os

DEFAULT_CONTACT_EMAIL = 'contact@example.invalid'


def contact_email() -> str:
    """ZYG_CONTACT_EMAIL, or an unroutable placeholder when it is not set."""
    return (os.environ.get('ZYG_CONTACT_EMAIL', '') or '').strip() or DEFAULT_CONTACT_EMAIL
