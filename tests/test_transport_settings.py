"""Transport settings: a CLI argument wins, then the environment, then the default."""

import pytest

from odoo_fast_mcp.server import resolve_transport


@pytest.fixture
def env(monkeypatch):
    for name in ("MCP_TRANSPORT", "MCP_HOST", "MCP_PORT"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_without_arguments_or_environment(env):
    assert resolve_transport() == ("stdio", "0.0.0.0", 8000)


def test_environment_fills_what_the_cli_left_out(env):
    env.setenv("MCP_TRANSPORT", "http")
    env.setenv("MCP_HOST", "127.0.0.1")
    env.setenv("MCP_PORT", "9000")
    assert resolve_transport() == ("http", "127.0.0.1", 9000)


def test_an_explicit_cli_argument_beats_the_environment(env):
    env.setenv("MCP_TRANSPORT", "sse")
    env.setenv("MCP_HOST", "0.0.0.0")
    env.setenv("MCP_PORT", "9000")
    assert resolve_transport("http", "127.0.0.1", 8000) == ("http", "127.0.0.1", 8000)


def test_each_setting_falls_back_on_its_own(env):
    env.setenv("MCP_PORT", "9000")
    assert resolve_transport(transport="http") == ("http", "0.0.0.0", 9000)
