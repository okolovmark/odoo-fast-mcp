"""Connection management tools: connect, disconnect, list_databases, get_server_version, get_connection_status."""

from typing import Annotated, Any, Literal

from anyio import to_thread
from pydantic import Field

from odoo_fast_mcp.config import load_profile, parse_odoo_url
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
    host: Annotated[
        str | None, Field(description="Odoo server hostname or IP address"),
    ] = None,
    database: Annotated[str | None, Field(description="Database name to connect to")] = None,
    username: Annotated[str | None, Field(description="Username for authentication")] = None,
    password: Annotated[str | None, Field(description="Password for authentication")] = None,
    port: Annotated[int, Field(description="Odoo server port", ge=1, le=65535)] = 8069,
    protocol: Annotated[
        Literal["jsonrpc", "jsonrpc+ssl"],
        Field(description="Protocol to use (jsonrpc or jsonrpc+ssl)"),
    ] = "jsonrpc",
    timeout: Annotated[int, Field(description="Connection timeout in seconds", ge=1)] = 30,
    env_profile: Annotated[
        str | None,
        Field(
            description="Connect using an env-suffix profile instead of explicit "
            "credentials: 'prod' reads ODOO_URL_PROD / ODOO_DATABASE_PROD / "
            "ODOO_USERNAME_PROD / ODOO_PASSWORD_PROD from the server's "
            "environment (.env); 'default' reads the unsuffixed ODOO_* "
            "variables. When set, the explicit credential arguments are "
            "ignored and secrets never travel through the tool call.",
        ),
    ] = None,
) -> dict[str, Any]:
    """Connect and authenticate to an Odoo server.

    Two ways to authenticate:
    - `env_profile="prod"` — the server itself reads ODOO_*_PROD variables
      from its environment; nothing secret appears in the tool arguments.
    - Explicit `host` + `database` + `username` + `password`.

    This must be called before using most other tools.
    """
    if env_profile is not None:
        cfg = load_profile(env_profile)
        p_host, p_port, p_protocol = parse_odoo_url(cfg["odoo_url"])
        return await to_thread.run_sync(
            lambda: odoo_manager.connect(
                host=p_host,
                port=p_port,
                protocol=p_protocol,
                database=cfg["database"],
                username=cfg["username"],
                password=cfg["password"],
                timeout=cfg["timeout"],
            ),
        )

    if not (host and database and username and password):
        msg = (
            "Provide either env_profile, or all of host, database, "
            "username and password."
        )
        raise ValueError(msg)

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
        info = odoo_manager.get_user_info(with_company=True)
        return {
            "connected": True,
            "database": odoo.env.db,
            "user_id": odoo.env.uid,
            "user_name": info["name"],
            "company": info["company"],
            "version": odoo.version,
        }
    return await to_thread.run_sync(_get_status)
