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
import json
import logging
import os
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
import odoorpc
from anyio import to_thread
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from pydantic import Field

from odoo_fast_mcp.prompts import register_prompts

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


def load_config(env_path: str | None = None) -> dict[str, Any]:
    """Load configuration from .env file or environment variables.

    Environment variables:
        ODOO_URL: Odoo server URL (e.g., http://localhost:8069)
        ODOO_DATABASE: Database name
        ODOO_USERNAME: Username for authentication
        ODOO_PASSWORD: Password for authentication
        ODOO_TIMEOUT: Connection timeout in seconds (default: 30)
    """
    # Load .env file if it exists
    path = Path(env_path) if env_path else Path(".env")
    if path.exists():
        load_dotenv(path)
    else:
        load_dotenv()  # Try default locations

    return {
        "odoo_url": os.getenv("ODOO_URL", "http://localhost:8069"),
        "database": os.getenv("ODOO_DATABASE", ""),
        "username": os.getenv("ODOO_USERNAME", "admin"),
        "password": os.getenv("ODOO_PASSWORD", "admin"),
        "timeout": int(os.getenv("ODOO_TIMEOUT", "30")),
    }


# =============================================================================
# Odoo Connection Manager
# =============================================================================


class OdooConnectionManager:
    """Manages OdooRPC connection with thread-safe operations."""

    def __init__(self):
        self._odoo: odoorpc.ODOO | None = None
        self._config: dict[str, Any] = {}
        self._connected: bool = False

    @property
    def odoo(self) -> odoorpc.ODOO:
        """Get the current Odoo connection."""
        if not self._odoo or not self._connected:
            msg = "Not connected to Odoo. Use 'connect' tool first."
            raise ConnectionError(msg)
        return self._odoo

    @property
    def is_connected(self) -> bool:
        """Check if connected to Odoo."""
        return self._connected and self._odoo is not None

    def connect(
        self,
        host: str,
        port: int = 8069,
        protocol: str = "jsonrpc",
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Establish connection to Odoo server."""
        try:
            self._odoo = odoorpc.ODOO(host, protocol, port)
            self._odoo.config["timeout"] = timeout

            if database and username and password:
                self._odoo.login(database, username, password)
                self._connected = True
                # Store config for report HTTP requests
                self._config = {
                    "host": host,
                    "port": port,
                    "protocol": protocol,
                    "database": database,
                    "username": username,
                    "password": password,
                }
                return {
                    "status": "connected",
                    "host": host,
                    "port": port,
                    "database": database,
                    "user": self._odoo.env.user.name,
                    "uid": self._odoo.env.uid,
                    "version": self._odoo.version,
                }

            return {
                "status": "connected_no_auth",
                "host": host,
                "port": port,
                "message": "Connected but not authenticated. Call login separately.",
            }

        except Exception as e:
            self._connected = False
            msg = f"Connection failed: {e}"
            raise ConnectionError(msg) from e

    def disconnect(self) -> dict[str, str]:
        """Disconnect from Odoo server."""
        if self._odoo:
            self._odoo = None
        self._connected = False
        return {"status": "disconnected"}

    def list_databases(self, host: str, port: int = 8069, protocol: str = "jsonrpc") -> list[str]:
        """List available databases on the Odoo server."""
        temp_odoo = odoorpc.ODOO(host, protocol, port)
        return temp_odoo.db.list()

    def get_server_version(self) -> str:
        """Get Odoo server version."""
        return self.odoo.version

    def search(
        self,
        model: str,
        domain: list | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[int]:
        """Search for record IDs matching the domain."""
        domain = domain or []
        return self.odoo.env[model].search(domain, offset=offset, limit=limit, order=order)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read records by IDs."""
        return self.odoo.execute(model, "read", ids, fields or [])

    def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search and read records in a single call."""
        domain = domain or []
        return self.odoo.env[model].search_read(
            domain, fields=fields, offset=offset, limit=limit, order=order,
        )

    def create(self, model: str, values: dict[str, Any]) -> int:
        """Create a new record."""
        return self.odoo.env[model].create(values)

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        """Update existing records."""
        return self.odoo.execute(model, "write", ids, values)

    def unlink(self, model: str, ids: list[int]) -> bool:
        """Delete records."""
        return self.odoo.execute(model, "unlink", ids)

    def search_count(self, model: str, domain: list | None = None) -> int:
        """Count records matching the domain."""
        domain = domain or []
        return self.odoo.env[model].search_count(domain)

    def execute(
        self,
        model: str,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute any method on a model."""
        return self.odoo.execute(model, method, *args, **kwargs)

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> Any:
        """Execute method with explicit args and kwargs."""
        args = args or []
        kwargs = kwargs or {}
        return self.odoo.execute_kw(model, method, args, kwargs)

    def get_model_fields(
        self,
        model: str,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get field definitions for a model."""
        attributes = attributes or ["string", "type", "required", "readonly", "help", "relation"]
        return self.odoo.execute(model, "fields_get", [], {"attributes": attributes})

    def list_models(self, filter_installed: bool = True) -> list[dict[str, Any]]:
        """List available models in the system."""
        domain: list[Any] = [("transient", "=", False)]
        if filter_installed:
            # Filter to only show models from installed modules
            # by checking if the model has any records in ir.model.access
            domain.append(("access_ids", "!=", False))
        return self.odoo.env["ir.model"].search_read(
            domain,
            fields=["model", "name", "info"],
            order="model",
        )

    def get_report(
        self,
        report_name: str,
        record_ids: list[int],
        report_type: str = "pdf",
    ) -> bytes:
        """Generate and download a report.

        Note: Due to CSRF protection in Odoo 16+, direct report downloads
        via HTTP are restricted. This method provides information about the
        report but cannot download the actual PDF without browser interaction.

        For report generation, consider using Odoo's scheduled actions or
        the web interface.
        """
        # Try to find the report by name or report_name field
        report_model = self.odoo.env["ir.actions.report"]
        reports = report_model.search_read(
            ["|", ("report_name", "=", report_name), ("name", "ilike", report_name)],
            fields=["report_name", "name", "model", "report_type"],
            limit=1,
        )

        if not reports:
            msg = f"Report '{report_name}' not found"
            raise ValueError(msg)

        report_info = reports[0]

        # Due to CSRF protection in Odoo 16+, we cannot download reports
        # via HTTP without a valid CSRF token from the web client.
        # OdooRPC's report.download is also not implemented for Odoo 16+.
        msg = (
            f"Report download is not supported for Odoo 16+ due to CSRF protection. "
            f"Report found: '{report_info['name']}' ({report_info['report_name']}). "
            f"Please use the Odoo web interface to download reports, or consider "
            f"using scheduled actions for automated report generation."
        )
        raise NotImplementedError(msg)

    def name_search(
        self,
        model: str,
        name: str = "",
        args: list | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        """Search for records by name."""
        args = args or []
        return self.odoo.execute(model, "name_search", name, args, operator, limit)


# Global connection manager instance
odoo_manager = OdooConnectionManager()


# =============================================================================
# Lifespan and Middleware
# =============================================================================


@asynccontextmanager
async def lifespan(mcp: FastMCP):
    """Lifespan manager for the MCP server."""
    logger.info("Starting Odoo FastMCP server...")
    yield {"odoo_manager": odoo_manager}
    logger.info("Shutting down Odoo FastMCP server...")
    odoo_manager.disconnect()


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


# =============================================================================
# Connection Tools
# =============================================================================


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


# =============================================================================
# Read Tools
# =============================================================================


@mcp.tool(
    annotations={
        "title": "Search Records",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def search(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner', 'sale.order')")],
    domain: Annotated[
        str,
        Field(
            description="Search domain as JSON string, e.g., '[[\"active\", \"=\", true]]'. "
            "Use empty list '[]' for no filter.",
        ),
    ] = "[]",
    offset: Annotated[int, Field(description="Number of records to skip", ge=0)] = 0,
    limit: Annotated[
        int | None, Field(description="Maximum number of records to return (None for all)"),
    ] = 100,
    order: Annotated[
        str | None, Field(description="Sort order, e.g., 'name asc, id desc'"),
    ] = None,
) -> list[int]:
    """Search for record IDs matching a domain filter.

    Returns a list of record IDs that can be used with the 'read' tool.
    Use search_read for better performance when you need both IDs and data.
    """
    parsed_domain = json.loads(domain)
    return await to_thread.run_sync(
        lambda: odoo_manager.search(
            model=model,
            domain=parsed_domain,
            offset=offset,
            limit=limit,
            order=order,
        ),
    )


@mcp.tool(
    annotations={
        "title": "Read Records",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def read(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    ids: Annotated[str, Field(description="JSON array of record IDs to read, e.g., '[1, 2, 3]'")],
    fields: Annotated[
        str | None,
        Field(
            description="JSON array of field names to read, e.g., '[\"name\", \"email\"]'. "
            "None returns all fields.",
        ),
    ] = None,
) -> list[dict[str, Any]]:
    """Read specific records by their IDs.

    Returns full record data for the specified IDs.
    """
    parsed_ids = json.loads(ids)
    parsed_fields = json.loads(fields) if fields else None
    return await to_thread.run_sync(
        lambda: odoo_manager.read(model=model, ids=parsed_ids, fields=parsed_fields),
    )


@mcp.tool(
    annotations={
        "title": "Search and Read Records",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def search_read(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner', 'sale.order')")],
    domain: Annotated[
        str,
        Field(
            description="Search domain as JSON string. Examples:\n"
            "- '[]' for all records\n"
            "- '[[\"active\", \"=\", true]]'\n"
            "- '[[\"name\", \"ilike\", \"john\"], [\"country_id\", \"=\", 1]]'",
        ),
    ] = "[]",
    fields: Annotated[
        str | None,
        Field(
            description="JSON array of field names, e.g., '[\"name\", \"email\", \"phone\"]'. "
            "None returns all fields.",
        ),
    ] = None,
    offset: Annotated[int, Field(description="Number of records to skip", ge=0)] = 0,
    limit: Annotated[
        int | None, Field(description="Maximum number of records (None for all, use carefully)"),
    ] = 100,
    order: Annotated[
        str | None, Field(description="Sort order, e.g., 'create_date desc'"),
    ] = None,
) -> list[dict[str, Any]]:
    """Search for records and return their data in a single operation.

    This is the most efficient way to query Odoo data. Combines search and read
    into one RPC call.

    ## Domain Examples:
    - All active partners: [["active", "=", true]]
    - Partners in specific country: [["country_id", "=", 1]]
    - Orders this month: [["date_order", ">=", "2024-01-01"]]
    - Combine conditions: [["active", "=", true], ["customer_rank", ">", 0]]
    """
    parsed_domain = json.loads(domain)
    parsed_fields = json.loads(fields) if fields else None
    return await to_thread.run_sync(
        lambda: odoo_manager.search_read(
            model=model,
            domain=parsed_domain,
            fields=parsed_fields,
            offset=offset,
            limit=limit,
            order=order,
        ),
    )


@mcp.tool(
    annotations={
        "title": "Count Records",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def search_count(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    domain: Annotated[
        str,
        Field(description="Search domain as JSON string, e.g., '[[\"active\", \"=\", true]]'"),
    ] = "[]",
) -> int:
    """Count the number of records matching a domain.

    Useful for pagination or checking if records exist without fetching data.
    """
    parsed_domain = json.loads(domain)
    return await to_thread.run_sync(
        lambda: odoo_manager.search_count(model=model, domain=parsed_domain),
    )


@mcp.tool(
    annotations={
        "title": "Search by Name",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def name_search(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    name: Annotated[str, Field(description="Name to search for")] = "",
    domain: Annotated[
        str,
        Field(description="Additional domain filter as JSON string"),
    ] = "[]",
    operator: Annotated[
        Literal["ilike", "like", "=", "!=", "=like", "=ilike"],
        Field(description="Comparison operator for name matching"),
    ] = "ilike",
    limit: Annotated[int, Field(description="Maximum results to return", ge=1)] = 100,
) -> list[dict[str, Any]]:
    """Search for records by name with fuzzy matching.

    Returns a list of {id, name} pairs for records matching the search term.
    Useful for autocomplete and quick lookups.
    """
    parsed_domain = json.loads(domain)
    results = await to_thread.run_sync(
        lambda: odoo_manager.name_search(
            model=model,
            name=name,
            args=parsed_domain,
            operator=operator,
            limit=limit,
        ),
    )
    return [{"id": r[0], "name": r[1]} for r in results]


# =============================================================================
# Write Tools
# =============================================================================


@mcp.tool(
    annotations={
        "title": "Create Record",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def create(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    values: Annotated[
        str,
        Field(
            description="JSON object of field values, e.g., "
            "'{\"name\": \"John Doe\", \"email\": \"john@example.com\"}'",
        ),
    ],
) -> int:
    """Create a new record in the specified model.

    Returns the ID of the newly created record.

    ## Value Examples:
    - Partner: {"name": "John", "email": "john@example.com", "is_company": false}
    - Product: {"name": "Widget", "list_price": 99.99, "type": "product"}
    """
    parsed_values = json.loads(values)
    return await to_thread.run_sync(
        lambda: odoo_manager.create(model=model, values=parsed_values),
    )


@mcp.tool(
    annotations={
        "title": "Update Records",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def write(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    ids: Annotated[
        str, Field(description="JSON array of record IDs to update, e.g., '[1, 2, 3]'"),
    ],
    values: Annotated[
        str,
        Field(
            description="JSON object of field values to update, e.g., "
            "'{\"name\": \"Updated Name\"}'",
        ),
    ],
) -> bool:
    """Update existing records with new values.

    Modifies the specified fields on all records matching the given IDs.
    Returns True on success.
    """
    parsed_ids = json.loads(ids)
    parsed_values = json.loads(values)
    return await to_thread.run_sync(
        lambda: odoo_manager.write(model=model, ids=parsed_ids, values=parsed_values),
    )


@mcp.tool(
    annotations={
        "title": "Delete Records",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def unlink(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    ids: Annotated[
        str, Field(description="JSON array of record IDs to delete, e.g., '[1, 2, 3]'"),
    ],
) -> bool:
    """Delete records from the database.

    WARNING: This permanently removes records. Some models may prevent deletion
    if records are referenced elsewhere.

    Note: Some models (like res.partner) may have many triggers and hooks
    that can cause slow deletion times. If timeouts occur, consider increasing
    the connection timeout or checking for server-side issues.
    """
    parsed_ids = json.loads(ids)
    return await to_thread.run_sync(
        lambda: odoo_manager.unlink(model=model, ids=parsed_ids),
    )


# =============================================================================
# Metadata Tools
# =============================================================================


@mcp.tool(
    annotations={
        "title": "Get Model Fields",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_model_fields(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    attributes: Annotated[
        str | None,
        Field(
            description="JSON array of field attributes to return. Default: "
            '["string", "type", "required", "readonly", "help", "relation"]',
        ),
    ] = None,
) -> dict[str, Any]:
    """Get field definitions for a model.

    Returns metadata about all fields including their type, label, and constraints.
    Useful for understanding a model's structure before querying or writing data.
    """
    parsed_attrs = json.loads(attributes) if attributes else None
    return await to_thread.run_sync(
        lambda: odoo_manager.get_model_fields(model=model, attributes=parsed_attrs),
    )


@mcp.tool(
    annotations={
        "title": "List Available Models",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def list_models(
    filter_installed: Annotated[
        bool, Field(description="Only show models from installed modules"),
    ] = True,
) -> list[dict[str, Any]]:
    """List all available models in the Odoo instance.

    Returns model technical names and display names.
    Use this to discover available models for queries.
    """
    return await to_thread.run_sync(
        lambda: odoo_manager.list_models(filter_installed=filter_installed),
    )


# =============================================================================
# Advanced Tools
# =============================================================================


@mcp.tool(
    annotations={
        "title": "Execute Model Method",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def execute(
    model: Annotated[str, Field(description="Model name (e.g., 'res.partner')")],
    method: Annotated[str, Field(description="Method name to call (e.g., 'action_confirm')")],
    args: Annotated[
        str,
        Field(
            description="JSON array of positional arguments. "
            "First argument is usually a list of IDs, e.g., '[[1, 2]]'",
        ),
    ] = "[]",
    kwargs: Annotated[
        str,
        Field(description="JSON object of keyword arguments, e.g., '{\"context\": {}}'"),
    ] = "{}",
) -> Any:
    """Execute any method on an Odoo model.

    This is a powerful tool for calling arbitrary model methods like:
    - Workflow actions: action_confirm, action_done, action_cancel
    - Business logic: _compute_*, onchange_*
    - Custom methods defined in modules

    ## Examples:
    - Confirm sale order: model="sale.order", method="action_confirm", args="[[order_id]]"
    - Post invoice: model="account.move", method="action_post", args="[[invoice_id]]"
    """
    parsed_args = json.loads(args)
    parsed_kwargs = json.loads(kwargs)
    return await to_thread.run_sync(
        lambda: odoo_manager.execute_kw(
            model=model,
            method=method,
            args=parsed_args,
            kwargs=parsed_kwargs,
        ),
    )


@mcp.tool(
    annotations={
        "title": "Generate Report",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_report(
    report_name: Annotated[
        str,
        Field(
            description="Report technical name (e.g., 'account.report_invoice', "
            "'sale.report_saleorder')",
        ),
    ],
    ids: Annotated[
        str, Field(description="JSON array of record IDs to include in report, e.g., '[1, 2]'"),
    ],
    output_path: Annotated[
        str,
        Field(description="File path to save the report (PDF format)"),
    ],
) -> dict[str, str | int]:
    """Generate and save an Odoo report as PDF.

    Common reports:
    - Invoice: account.report_invoice
    - Sale Order: sale.report_saleorder
    - Purchase Order: purchase.report_purchaseorder
    - Delivery Slip: stock.report_deliveryslip
    """
    parsed_ids = json.loads(ids)

    def _generate() -> dict[str, str | int]:
        report_data = odoo_manager.get_report(report_name, parsed_ids)
        path = Path(output_path)
        path.write_bytes(report_data)
        return {
            "status": "success",
            "path": str(path.absolute()),
            "size_bytes": len(report_data),
        }

    return await to_thread.run_sync(_generate)


# =============================================================================
# Resources
# =============================================================================


@mcp.resource("odoo://status")
async def get_status() -> dict[str, Any]:
    """Get current Odoo connection status."""
    if not odoo_manager.is_connected:
        return {"connected": False}

    def _get_info() -> dict[str, Any]:
        odoo = odoo_manager.odoo
        return {
            "connected": True,
            "database": odoo.env.db,
            "user": odoo.env.user.name,
            "uid": odoo.env.uid,
            "version": odoo.version,
        }

    return await to_thread.run_sync(_get_info)


@mcp.resource("odoo://models")
async def get_models_resource() -> list[dict[str, Any]]:
    """List all available Odoo models as a resource."""
    if not odoo_manager.is_connected:
        return []
    return await to_thread.run_sync(lambda: odoo_manager.list_models())


@mcp.resource("odoo://model/{model_name}/fields")
async def get_model_fields_resource(model_name: str) -> dict[str, Any]:
    """Get field definitions for a specific model."""
    if not odoo_manager.is_connected:
        return {"error": "Not connected"}
    return await to_thread.run_sync(lambda: odoo_manager.get_model_fields(model_name))


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
            # Parse URL to get host and port
            url = config["odoo_url"]
            protocol = "jsonrpc+ssl" if url.startswith("https") else "jsonrpc"
            # Remove protocol prefix
            host_part = url.replace("https://", "").replace("http://", "")
            # Split host and port
            if ":" in host_part:
                odoo_host, port_str = host_part.split(":")
                odoo_port = int(port_str)
            else:
                odoo_host = host_part
                odoo_port = 443 if "ssl" in protocol else 8069

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
