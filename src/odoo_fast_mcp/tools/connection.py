"""Connection management tools: connect, disconnect, list_databases, get_server_version, get_connection_status."""

from typing import Annotated, Any, Literal

from anyio import to_thread
from pydantic import Field

from odoo_fast_mcp.connection import odoo_manager
from odoo_fast_mcp.server import mcp


@mcp.tool(
    annotations={
        "title": "Connect to Odoo",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def connect(
    host: Annotated[str, Field(description="Odoo server hostname or IP address")],
    database: Annotated[str, Field(description="Database name to connect to")],
    username: Annotated[str, Field(description="Username for authentication")],
    password: Annotated[str, Field(description="Password for authentication")],
    port: Annotated[int, Field(description="Odoo server port", ge=1, le=65535)] = 8069,
    protocol: Annotated[
        Literal["jsonrpc", "jsonrpc+ssl"],
        Field(description="Protocol to use (jsonrpc or jsonrpc+ssl)"),
    ] = "jsonrpc",
    timeout: Annotated[int, Field(description="Connection timeout in seconds", ge=1)] = 30,
) -> dict[str, Any]:
    """Connect and authenticate to an Odoo server.

    Establishes a connection to the Odoo server and authenticates with the provided credentials.
    This must be called before using most other tools.
    """
    return await to_thread.run_sync(
        lambda: odoo_manager.connect(
            host=host,
            port=port,
            protocol=protocol,
            database=database,
            username=username,
            password=password,
            timeout=timeout,
        ),
    )


@mcp.tool(
    annotations={
        "title": "Disconnect from Odoo",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def disconnect() -> dict[str, str]:
    """Disconnect from the current Odoo server session."""
    return await to_thread.run_sync(odoo_manager.disconnect)


@mcp.tool(
    annotations={
        "title": "List Odoo Databases",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_databases(
    host: Annotated[str, Field(description="Odoo server hostname or IP address")],
    port: Annotated[int, Field(description="Odoo server port", ge=1, le=65535)] = 8069,
    protocol: Annotated[
        Literal["jsonrpc", "jsonrpc+ssl"],
        Field(description="Protocol to use"),
    ] = "jsonrpc",
) -> list[str]:
    """List available databases on an Odoo server.

    Can be called without authentication to discover available databases.
    """
    return await to_thread.run_sync(
        lambda: odoo_manager.list_databases(host, port, protocol),
    )


@mcp.tool(
    annotations={
        "title": "Get Server Version",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_server_version() -> str:
    """Get the version of the connected Odoo server."""
    return await to_thread.run_sync(odoo_manager.get_server_version)


@mcp.tool(
    annotations={
        "title": "Get Connection Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_connection_status() -> dict[str, Any]:
    """Get the current connection status and user information."""
    def _get_status() -> dict[str, Any]:
        if not odoo_manager.is_connected:
            return {"connected": False}
        odoo = odoo_manager.odoo
        return {
            "connected": True,
            "database": odoo.env.db,
            "user_id": odoo.env.uid,
            "user_name": odoo.env.user.name,
            "company": odoo.env.user.company_id.name,
            "version": odoo.version,
        }
    return await to_thread.run_sync(_get_status)
