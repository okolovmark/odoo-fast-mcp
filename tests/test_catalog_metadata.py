"""Every catalog entry carries the display metadata clients render.

Nothing here changes what the server can do — it guards what a client, a
registry or an audit tool (mcpscore) sees before any tool is called. A prompt
or resource added later without a `title=` falls back to its programmatic name
in every picker UI, which is the regression these tests exist to catch.
"""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest

import odoo_fast_mcp.server as server

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(coro):
    return asyncio.run(coro)


def test_server_info_declares_its_project_url():
    assert server.mcp.website_url == server.PROJECT_URL
    assert server.PROJECT_URL.startswith("https://")


def test_server_info_declares_a_renderable_icon():
    icons = server.mcp._mcp_server.icons or []
    assert icons, "serverInfo must declare at least one icon"
    for icon in icons:
        # Clients only fetch https:// or inline data: sources; anything else is
        # silently dropped, which is indistinguishable from declaring no icon.
        assert icon.src.startswith(("https://", "data:")), icon.src
        assert icon.mimeType == "image/svg+xml"
        assert icon.sizes == ["any"]


def test_declared_icon_files_exist_in_the_repository():
    # The icon is served from the default branch, so a rename or a move here
    # turns the declared URL into a 404 no test would otherwise notice.
    for icon in server.mcp._mcp_server.icons or []:
        if not icon.src.startswith(server.RAW_CONTENT_URL):
            continue
        relative = urlsplit(icon.src[len(server.RAW_CONTENT_URL) :]).path.lstrip("/")
        assert (REPO_ROOT / relative).is_file(), relative


@pytest.mark.parametrize(
    "lister",
    [
        pytest.param(lambda: server.mcp._list_prompts(), id="prompts"),
        pytest.param(lambda: server.mcp._list_resources(), id="resources"),
        pytest.param(lambda: server.mcp._list_resource_templates(), id="templates"),
    ],
)
def test_every_catalog_entry_has_a_display_title(lister):
    entries = _run(lister())
    assert entries, "nothing registered — the assertion below would pass vacuously"
    untitled = [entry.name for entry in entries if not getattr(entry, "title", None)]
    assert not untitled, f"missing a display title: {untitled}"


def test_tools_that_can_destroy_data_say_so():
    # `execute` runs any method — unlink and action_cancel included. A client
    # that gates its confirmation prompt on destructiveHint must not be told
    # otherwise.
    tools = {tool.name: tool for tool in _run(server.mcp._list_tools())}
    for name in ("unlink", "execute"):
        assert tools[name].annotations.destructiveHint is True, name
