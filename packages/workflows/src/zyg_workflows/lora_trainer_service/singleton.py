# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Module-level LoraTrainerService singleton."""

import logging
from typing import Optional
import logging as _zyg_logging
from zyg_workflows.lora_trainer_service.service import (  # noqa: F401
    LoraTrainerService,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')

# ── Module-level singleton ────────────────────────────────────────────────────────
_trainer_instance: Optional[LoraTrainerService] = None


def get_trainer() -> LoraTrainerService:
    global _trainer_instance
    if _trainer_instance is None:
        _trainer_instance = LoraTrainerService()
    return _trainer_instance
