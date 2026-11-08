"""MCP SDK availability: a failed symbol import is a miss, and a stale flag can recover.

The CLI probe used to trust ``find_spec`` from import time. A later path (PM
activation, a just-enabled extra) could make ``import mcp`` succeed in the same
interpreter while ``hermes mcp test`` still reported the SDK missing. These
tests do not start a server and do not install packages.
"""

from __future__ import annotations

import importlib.util

import pytest


def test_failed_sdk_symbol_import_is_unavailable(monkeypatch):
    """A distribution named mcp without the client symbols is not the SDK."""
    import tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_tool, "_MCP_SDK_IMPORT_ATTEMPTED", False)
    monkeypatch.setattr(mcp_tool, "ClientSession", None)
    monkeypatch.setattr(mcp_tool, "_import_sdk_names", lambda *_a, **_k: False)

    assert mcp_tool._ensure_mcp_sdk() is False
    assert mcp_tool._MCP_AVAILABLE is False


def test_stale_unavailable_flag_recovers_when_sdk_imports(monkeypatch):
    """``_MCP_AVAILABLE = False`` at import must not stick once the SDK is visible."""
    if importlib.util.find_spec("mcp") is None:
        pytest.skip("mcp extra is not installed in this interpreter")
    import tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "_MCP_AVAILABLE", False)
    monkeypatch.setattr(mcp_tool, "_MCP_SDK_IMPORT_ATTEMPTED", False)
    monkeypatch.setattr(mcp_tool, "ClientSession", None)

    assert mcp_tool._ensure_mcp_sdk() is False
    assert mcp_tool.prepare_mcp_sdk_for_cli() is True
    assert mcp_tool.ClientSession is not None


def test_prepare_asks_pm_for_the_mcp_extra_when_the_anchor_is_missing(monkeypatch):
    """No network and no install: the missing anchor asks PM once, then stays missing."""
    import tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "_MCP_AVAILABLE", False)
    monkeypatch.setattr(mcp_tool, "_MCP_SDK_IMPORT_ATTEMPTED", False)
    monkeypatch.setattr(mcp_tool, "ClientSession", None)
    monkeypatch.setattr(mcp_tool, "_mcp_spec_present", lambda: False)
    asked: list[str] = []

    def _refuse(extra: str) -> None:
        asked.append(extra)
        raise RuntimeError("lazy install disabled")

    monkeypatch.setattr("pm.ensure_import", _refuse)

    assert mcp_tool.prepare_mcp_sdk_for_cli() is False
    assert asked == ["mcp"]
    assert mcp_tool._MCP_AVAILABLE is False


def test_mcp_test_no_install_flag_is_opt_in():
    import argparse

    from hermes_cli.subcommands.mcp import build_mcp_parser

    parser = argparse.ArgumentParser()
    build_mcp_parser(parser.add_subparsers(dest="command"), cmd_mcp=lambda _ns: 0)
    opted = parser.parse_args(["mcp", "test", "cua-driver", "--no-install"])
    plain = parser.parse_args(["mcp", "test", "cua-driver"])
    assert opted.no_install is True
    assert plain.no_install is False


def test_no_install_does_not_call_ensure_import_when_sdk_is_absent(monkeypatch):
    """``allow_install=False`` must not reach PM, even when the anchor is missing."""
    import tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "_ensure_mcp_sdk", lambda: False)
    monkeypatch.setattr(mcp_tool, "_mcp_spec_present", lambda: False)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("installer path reached")

    monkeypatch.setattr("pm.ensure_import", _forbidden)
    monkeypatch.setattr("pm.extras.ensure_import", _forbidden)
    monkeypatch.setattr("pm.client.sync_venv", _forbidden)

    assert mcp_tool.prepare_mcp_sdk_for_cli(allow_install=False) is False


def test_patched_unavailable_flag_still_blocks_stdio_without_prepare():
    """The stdio gate itself still honors a patched miss. CLI refresh is opt-in."""
    import asyncio
    from unittest.mock import patch

    from tools.mcp_tool import MCPServerTask

    server = MCPServerTask("local")

    async def _run():
        with patch("tools.mcp_tool._MCP_AVAILABLE", False):
            with pytest.raises(ImportError, match="mcp"):
                await server._run_stdio({"command": "python3", "args": ["echo.py"]})

    asyncio.run(_run())
