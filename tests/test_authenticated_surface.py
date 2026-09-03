"""What the server offers a model changes once callers sign in.

The default instructions open with "use `connect` first", and `connect` reads
credentials from the environment — which authenticated mode deliberately does
not have. A model that follows them calls the tool, gets a KeyError and shows
the person an error before carrying on to work fine anyway. Observed in
production; these tests are why it should not come back.
"""

import asyncio
import json
import os
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def authenticated_server(tmp_path, monkeypatch):
    """The module-level server with authentication switched on."""
    import odoo_fast_mcp.server as server

    for name, value in {
        "MCP_AUTH": "odoo",
        "MCP_BASE_URL": "https://mcp.example.test",
        "MCP_CREDENTIAL_KEY": Fernet.generate_key().decode(),
        "MCP_STATE_DB": str(tmp_path / "state.db"),
        "ODOO_URL": "https://odoo.example.test",
        "ODOO_DATABASE": "db",
    }.items():
        monkeypatch.setenv(name, value)

    original_instructions = server.mcp.instructions
    # Withdrawal happens on the module-level server, so without putting the
    # tools back this fixture decides what every later test file sees.
    withdrawn = [
        asyncio.run(server.mcp.local_provider.get_tool(name))
        for name in ("connect", "disconnect", "list_databases")
    ]
    server._enable_odoo_auth(server.load_config(None))
    yield server
    # The server object is module-level and shared across tests.
    server.mcp.instructions = original_instructions
    for tool in withdrawn:
        server.mcp.local_provider.add_tool(tool)
    server.registry.set_credential_provider(None)
    server.mcp.auth = None


def tool_names(server) -> set[str]:
    return {tool.name for tool in asyncio.run(server.mcp._list_tools())}


def test_connection_management_tools_are_withdrawn(authenticated_server):
    # `connect` cannot work without env credentials, and would let a caller
    # point their session at any host they name.
    names = tool_names(authenticated_server)
    assert not {"connect", "disconnect", "list_databases"} & names


def test_the_work_tools_remain(authenticated_server):
    names = tool_names(authenticated_server)
    assert {"search_read", "read", "create", "write", "execute"} <= names


def test_status_stays_so_a_caller_can_ask_who_they_are(authenticated_server):
    assert "get_connection_status" in tool_names(authenticated_server)


def test_instructions_no_longer_ask_for_a_connect_step(authenticated_server):
    instructions = authenticated_server.mcp.instructions.lower()
    # Saying the words "no connect step" is fine; telling the model to call the
    # tool is what sent it down the failing path.
    assert "use `connect`" not in instructions
    assert "`connect`" not in instructions
    assert "already connected" in instructions


def test_the_credential_provider_is_wired_to_the_registry(authenticated_server):
    # Without this the registry hands out unconnected managers and every tool
    # call fails with "Not connected to Odoo".
    assert authenticated_server.registry._credentials is not None


def _stdio_tool_names() -> set[str]:
    """Tool names a plain stdio server publishes, in a process of its own.

    Spawned rather than inspected in-process: the FastMCP instance is
    module-level, and a test that ran with authentication on has already
    withdrawn tools from it.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MCP_", "ODOO_"))}
    process = subprocess.Popen(
        [sys.executable, "-m", "odoo_fast_mcp.server", "--transport", "stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1, env=env,
    )

    def send(payload):
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def read():
        while line := process.stdout.readline():
            if line.strip().startswith("{"):
                return json.loads(line)
        return None

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "t", "version": "0"}}})
        read()
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        return {tool["name"] for tool in read()["result"]["tools"]}
    finally:
        process.terminate()
        process.wait(timeout=15)


def test_local_use_keeps_the_connection_tools():
    # Withdrawing them is a property of authenticated mode, not of the server.
    # Over stdio the process belongs to one person, their credentials are their
    # own, and moving between databases — connect(env_profile="prod") — is the
    # point of the tool.
    assert {"connect", "disconnect", "list_databases"} <= _stdio_tool_names()
