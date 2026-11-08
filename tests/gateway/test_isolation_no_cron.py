"""HERMES_ISOLATION_NO_CRON skips the cron ticker. The default stays unchanged."""

import asyncio

import gateway.isolation as isolation


def test_default_leaves_cron_enabled(monkeypatch):
    monkeypatch.delenv("HERMES_ISOLATION_NO_CRON", raising=False)
    assert isolation.isolation_disables_cron() is False


def test_only_exact_one_disables_cron(monkeypatch):
    monkeypatch.setenv("HERMES_ISOLATION_NO_CRON", "1")
    assert isolation.isolation_disables_cron() is True
    monkeypatch.setenv("HERMES_ISOLATION_NO_CRON", "true")
    assert isolation.isolation_disables_cron() is False


def test_flag_does_not_start_the_ticker(monkeypatch):
    monkeypatch.setenv("HERMES_ISOLATION_NO_CRON", "1")
    from gateway import run as gateway_run

    class Runner:
        adapters = {}
        config = None

    async def start():
        return gateway_run._start_gateway_start_cron_and_housekeeping(Runner())

    cron_stop, provider, thread, housekeeping = asyncio.run(start())
    assert provider is None
    assert thread is None
    assert isolation.cron_scheduler_started() is False
    cron_stop.set()
    housekeeping.join(timeout=2)
