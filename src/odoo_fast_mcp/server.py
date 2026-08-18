"""
Odoo FastMCP Server - MCP server for Odoo 16 using OdooRPC.

Provides comprehensive tools for interacting with Odoo ERP:
- Connection management
- CRUD operations (Create, Read, Update, Delete)
- Model introspection
- Method execution
- Report generation
"""

import argparse
import logging
import os
from contextlib import asynccontextmanager, suppress
from functools import partial
from typing import Any

import anyio
import odoorpc
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import Icon

from odoo_fast_mcp.config import load_config, parse_odoo_url
from odoo_fast_mcp.connection import odoo_manager, registry
from odoo_fast_mcp.prompts import register_prompts

logger = logging.getLogger(__name__)

# Catalog metadata surfaced to clients and registries in the `initialize`
# response. The icon is served from the default branch rather than inlined as a
# data URI so `initialize` stays small; it moves with the repository.
PROJECT_URL = "https://github.com/okolovmark/odoo-fast-mcp"
RAW_CONTENT_URL = "https://raw.githubusercontent.com/okolovmark/odoo-fast-mcp/main"


# =============================================================================
# Lifespan and Middleware
# =============================================================================


@asynccontextmanager
async def lifespan(mcp: FastMCP):
    """Lifespan manager for the MCP server.

    Deliberately free of background tasks: idle connections are swept by the
    registry itself, so nothing here has to survive being entered and exited in
    different tasks — a startup failure then reports the failure rather than a
    cancel-scope error raised while unwinding.
    """
    logger.info("Starting Odoo FastMCP server...")
    try:
        yield {"odoo_manager": odoo_manager}
    finally:
        logger.info("Shutting down Odoo FastMCP server...")
        registry.shutdown()


class LoggingMiddleware(Middleware):
    """Middleware that logs all MCP operations."""

    async def on_message(self, context: MiddlewareContext, call_next):
        """Called for all MCP messages."""
        logger.debug("Processing %s from %s", context.method, context.source)
        result = await call_next(context)
        logger.debug("Completed %s", context.method)
        return result


# What the server tells a model about itself once callers sign in. The default
# instructions open with "use connect first", which is exactly wrong here.
AUTHENTICATED_INSTRUCTIONS = """
    This server provides tools to interact with an Odoo ERP system via OdooRPC.

    ## Getting Started
    You are already connected, as the Odoo user who signed in — there is no
    connect step and no credentials to supply. `get_connection_status` reports
    who that is. Everything you do is done as that user and is subject to their
    Odoo permissions; an AccessError means their account lacks the right, so
    report it rather than working around it.

    ## Available Operations
    - **Read**: search, read, search_read, search_count, name_search
    - **Write**: create, write (update), unlink (delete)
    - **Meta**: get_model_fields, list_models, get_server_version
    - **Advanced**: execute (call any model method), get_report

    ## Domain Syntax
    Domains are lists of conditions: [('field', 'operator', 'value')]
    Common operators: =, !=, >, >=, <, <=, like, ilike, in, not in
    Combine with '&' (AND), '|' (OR), '!' (NOT)

    Example: [['active', '=', true], ['name', 'ilike', 'test']]
"""


# =============================================================================
# FastMCP Server Instance
# =============================================================================


mcp: FastMCP = FastMCP(
    name="Odoo Fast MCP",
    website_url=PROJECT_URL,
    icons=[
        Icon(
            src=f"{RAW_CONTENT_URL}/assets/icon.svg",
            mimeType="image/svg+xml",
            sizes=["any"],
        ),
    ],
    instructions="""
        This server provides tools to interact with Odoo ERP systems via OdooRPC.

        ## Getting Started
        1. Use `connect` to establish a connection to your Odoo server
           - `connect(env_profile="prod")` reads ODOO_URL_PROD / ODOO_DATABASE_PROD /
             ODOO_USERNAME_PROD / ODOO_PASSWORD_PROD from the server environment —
             credentials never appear in the tool call. `env_profile="default"`
             returns to the unsuffixed ODOO_* connection (local).
        2. Or use `list_databases` to see available databases first

        ## Available Operations
        - **Connection**: connect, disconnect, list_databases, get_server_version
        - **Read**: search, read, search_read, search_count, name_search
        - **Write**: create, write (update), unlink (delete)
        - **Meta**: get_model_fields, list_models
        - **Advanced**: execute (call any model method), get_report

        ## Domain Syntax
        Domains are lists of conditions: [('field', 'operator', 'value')]
        Common operators: =, !=, >, >=, <, <=, like, ilike, in, not in
        Combine with '&' (AND), '|' (OR), '!' (NOT)

        Example: [['active', '=', true], ['name', 'ilike', 'test']]
    """,
    lifespan=lifespan,
)
mcp.add_middleware(LoggingMiddleware())
register_prompts(mcp)


# Import tools and resources to trigger decorator-based registration.
# These must come after `mcp` is defined so submodules can import it.
import odoo_fast_mcp.resources  # noqa: E402, F401
import odoo_fast_mcp.tools  # noqa: E402, F401

# =============================================================================
# Entry Points
# =============================================================================


def _enable_odoo_auth(config: dict[str, Any]) -> None:
    """Make every caller sign in as themselves, with Odoo deciding who they are.

    Turning this on replaces the server's single env-credential session: the
    connection registry is fed from each person's own stored credential, so what
    they may do in Odoo is whatever Odoo already grants their user.
    """
    from odoo_fast_mcp.auth import CredentialStore
    from odoo_fast_mcp.auth.provider import OdooAuthProvider, OdooTarget
    from odoo_fast_mcp.auth.store import OAuthStore

    missing = [
        name
        for name, value in (
            ("MCP_BASE_URL", config["base_url"]),
            ("MCP_CREDENTIAL_KEY", config["credential_key"]),
            ("ODOO_DATABASE", config["database"]),
        )
        if not value
    ]
    if missing:
        msg = f"MCP_AUTH=odoo needs {', '.join(missing)}"
        raise SystemExit(msg)

    odoo_host, odoo_port, protocol = parse_odoo_url(config["odoo_url"])
    provider = OdooAuthProvider(
        base_url=config["base_url"],
        target=OdooTarget(
            host=odoo_host,
            database=config["database"],
            port=odoo_port,
            protocol=protocol,
        ),
        oauth_store=OAuthStore(config["state_db"]),
        credential_store=CredentialStore(config["state_db"], config["credential_key"]),
    )
    mcp.auth = provider
    registry.set_credential_provider(provider.credential_provider)

    # The connection-management tools are wrong here, and worse than useless.
    # `connect` reads credentials from the environment — deliberately absent in
    # this mode — so a model following the default instructions calls it, gets a
    # KeyError, and shows the person an error before carrying on to work fine.
    # It would also let a caller point their session at any host they name, which
    # a shared, internet-facing server has no business offering. The session is
    # opened from the caller's own stored credential; there is nothing to connect.
    # `get_connection_status` stays: it answers "am I in, and as whom".
    for tool in ("connect", "disconnect", "list_databases"):
        # Already withdrawn is fine: enabling auth twice must not fail.
        with suppress(KeyError):
            mcp.local_provider.remove_tool(tool)

    mcp.instructions = AUTHENTICATED_INSTRUCTIONS
    logger.info("Authentication enabled: callers sign in with their own Odoo login")


async def _main_async(
    env_path: str | None = None,
    transport: str = "stdio",
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Async entry point for the MCP server."""
    config = load_config(env_path)

    # Allow env vars to override CLI defaults
    transport = os.getenv("MCP_TRANSPORT", transport)
    host = os.getenv("MCP_HOST", host)
    port = int(os.getenv("MCP_PORT", str(port)))

    authenticated = config["auth"] == "odoo"
    if authenticated:
        _enable_odoo_auth(config)

    # Auto-connect if config has credentials. Skipped under authentication: a
    # shared server should hold no session that isn't somebody's own.
    if not authenticated and all(
        config.get(k) for k in ["odoo_url", "database", "username", "password"]
    ):
        try:
            odoo_host, odoo_port, protocol = parse_odoo_url(config["odoo_url"])

            odoo_manager.connect(
                host=odoo_host,
                port=odoo_port,
                protocol=protocol,
                database=config["database"],
                username=config["username"],
                password=config["password"],
                timeout=config.get("timeout", 30),
            )
            logger.info("Auto-connected to Odoo at %s", config["odoo_url"])
        except (ConnectionError, odoorpc.error.RPCError, OSError) as e:
            logger.warning("Auto-connect failed: %s. Use 'connect' tool manually.", e)

    if transport == "http":
        logger.info("Starting HTTP (Streamable HTTP) transport on %s:%d", host, port)
        await mcp.run_async(transport="http", host=host, port=port)
    elif transport == "sse":
        logger.info("Starting SSE transport on %s:%d", host, port)
        await mcp.run_async(transport="sse", host=host, port=port)
    else:
        logger.info("Starting stdio transport")
        await mcp.run_async(transport="stdio")


def main_cli() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="Run the Odoo Fast MCP server.")
    parser.add_argument("--env", help="Path to .env configuration file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport protocol: stdio (default), http (Streamable HTTP), or sse",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind HTTP/SSE server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP/SSE server (default: 8000)",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    anyio.run(
        partial(
            _main_async,
            env_path=args.env,
            transport=args.transport,
            host=args.host,
            port=args.port,
        ),
    )


if __name__ == "__main__":
    # `python -m odoo_fast_mcp.server` loads this file twice: once as __main__,
    # and again as odoo_fast_mcp.server when the tool modules import it back.
    # Each copy builds its own FastMCP instance, and the tools register on the
    # imported one — so running __main__'s instance would serve a server with no
    # tools at all, with nothing in the log to say why. Hand over to the copy the
    # tools attached themselves to.
    from odoo_fast_mcp.server import main_cli as _registered_main_cli

    _registered_main_cli()
