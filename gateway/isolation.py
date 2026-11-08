"""Explicit isolation switch for a gateway that must not run cron.

Unset, empty, or any value other than ``1`` leaves the scheduler on. Green sets
``HERMES_ISOLATION_NO_CRON=1`` in its own unit. Production does not.
"""

from __future__ import annotations

import os

_cron_scheduler_started = False


def isolation_disables_cron() -> bool:
    """True only for the explicit isolation opt-in."""
    return os.environ.get("HERMES_ISOLATION_NO_CRON", "").strip() == "1"


def mark_cron_scheduler_started() -> None:
    global _cron_scheduler_started
    _cron_scheduler_started = True


def cron_scheduler_started() -> bool:
    """Whether this process started the cron ticker. False until it does."""
    return _cron_scheduler_started
