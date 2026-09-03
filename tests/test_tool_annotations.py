"""Every tool states what it does to the environment, and states it truthfully.

Clients read these hints before they call anything: some gate a confirmation
prompt on `destructiveHint`, some retry on `idempotentHint`, some hide
non-read-only tools in a read-only mode. A wrong hint is therefore not a
cosmetic slip — it is the server lying about consequences that land in
somebody's ERP.

The table below is the whole tool surface, so a tool added without deciding
its four hints fails here rather than shipping with copied ones.
"""

import asyncio

import odoo_fast_mcp.server as server

# name: (readOnly, destructive, idempotent, openWorld)
EXPECTED = {
    # --- Reads. Nothing to destroy, same answer for the same arguments.
    #     `list_databases` reaches a host the caller names, hence open-world;
    #     the rest speak only to the connection already established.
    "search": (True, False, True, False),
    "read": (True, False, True, False),
    "search_read": (True, False, True, False),
    "search_count": (True, False, True, False),
    "name_search": (True, False, True, False),
    "get_model_fields": (True, False, True, False),
    "list_models": (True, False, True, False),
    "get_report": (True, False, True, False),
    "get_server_version": (True, False, True, False),
    "get_connection_status": (True, False, True, False),
    "list_databases": (True, False, True, True),
    # --- Session management. Mutates the server's own state, never Odoo data.
    "connect": (False, False, True, True),
    "disconnect": (False, False, True, False),
    # --- Writes.
    # `create` only adds: destructive False. Called twice it makes two records,
    # so not idempotent.
    "create": (False, False, False, False),
    # `write` replaces values that were there, with no undo — destructive. And
    # not idempotent: x2many values are command lists, so
    # {"order_line": [[0, 0, {...}]]} appends another line every call.
    "write": (False, True, False, False),
    "unlink": (False, True, False, False),
    # `execute` runs any method on any model: unlink and action_cancel included
    # (destructive), and a method may post mail or call out through a connector,
    # which no other tool here can do (open-world).
    "execute": (False, True, False, True),
}


def _annotations() -> dict[str, tuple[bool, bool, bool, bool]]:
    tools = asyncio.run(server.mcp._list_tools())
    return {
        tool.name: (
            tool.annotations.readOnlyHint,
            tool.annotations.destructiveHint,
            tool.annotations.idempotentHint,
            tool.annotations.openWorldHint,
        )
        for tool in tools
    }


def test_the_table_covers_exactly_the_published_tools():
    # A new tool must be given its hints deliberately, not inherit whatever the
    # tool above it was copied from.
    assert set(_annotations()) == set(EXPECTED)


def test_every_tool_declares_the_hints_it_promises():
    assert _annotations() == EXPECTED


def test_a_destructive_tool_is_never_marked_read_only():
    # readOnlyHint True makes destructiveHint meaningless per the spec, and a
    # client in read-only mode would offer the tool anyway.
    for name, (read_only, destructive, _idempotent, _open_world) in EXPECTED.items():
        assert not (read_only and destructive), name
