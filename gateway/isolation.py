"""Explicit isolation switch for a gateway that must not run cron.

Unset, empty, or any value other than ``1`` leaves the scheduler on. Green sets
``HERMES_ISOLATION_NO_CRON=1`` in its own unit. Production does not.
"""

from __future__ import annotations

import os

_cron_scheduler_started = False
_dispatcher_started = False
_initialization_complete = False


def isolation_disables_cron() -> bool:
    """True only for the explicit isolation opt-in."""
    return os.environ.get("HERMES_ISOLATION_NO_CRON", "").strip() == "1"


def mark_cron_scheduler_started() -> None:
    global _cron_scheduler_started
    _cron_scheduler_started = True


def cron_scheduler_started() -> bool:
    """Whether this process started the cron ticker. False until it does."""
    return _cron_scheduler_started


def mark_dispatcher_started() -> None:
    global _dispatcher_started
    _dispatcher_started = True


def dispatcher_started() -> bool:
    return _dispatcher_started


def mark_initialization_complete() -> None:
    global _initialization_complete
    _initialization_complete = True


def initialization_complete() -> bool:
    return _initialization_complete


def isolation_status_ready(status: dict) -> bool:
    """Ready only after startup finished and neither background worker started."""
    return (
        status.get("initialization_complete") is True
        and status.get("cron_scheduler_started") is False
        and status.get("dispatcher_started") is False
    )
