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
from contextlib import asynccontextmanager
from functools import partial

import anyio
import odoorpc
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext

from odoo_fast_mcp.config import load_config, parse_odoo_url
from odoo_fast_mcp.connection import odoo_manager, registry
from odoo_fast_mcp.prompts import register_prompts

logger = logging.getLogger(__name__)

# A shared deployment accumulates one Odoo session per person who ever called it;
# drop the ones nobody is using rather than hold them until restart.
IDLE_TIMEOUT_SECONDS = 30 * 60
IDLE_SWEEP_SECONDS = 5 * 60


# =============================================================================
# Lifespan and Middleware
# =============================================================================


async def _sweep_idle_connections() -> None:
    """Disconnect per-identity sessions that have gone quiet."""
    while True:
        await anyio.sleep(IDLE_SWEEP_SECONDS)
        released = registry.release_idle(IDLE_TIMEOUT_SECONDS)
        if released:
            logger.info("Released %d idle Odoo connection(s)", len(released))


@asynccontextmanager
async def lifespan(mcp: FastMCP):
    """Lifespan manager for the MCP server."""
    logger.info("Starting Odoo FastMCP server...")
    async with anyio.create_task_group() as tg:
        tg.start_soon(_sweep_idle_connections)
        try:
            yield {"odoo_manager": odoo_manager}
        finally:
            logger.info("Shutting down Odoo FastMCP server...")
            registry.shutdown()
            tg.cancel_scope.cancel()


class LoggingMiddleware(Middleware):
    """Middleware that logs all MCP operations."""

    async def on_message(self, context: MiddlewareContext, call_next):
        """Called for all MCP messages."""
        logger.debug("Processing %s from %s", context.method, context.source)
        result = await call_next(context)
        logger.debug("Completed %s", context.method)
        return result


# =============================================================================
# FastMCP Server Instance
# =============================================================================


mcp: FastMCP = FastMCP(
    name="Odoo Fast MCP",
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

    # Auto-connect if config has credentials
    if all(config.get(k) for k in ["odoo_url", "database", "username", "password"]):
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
    main_cli()
