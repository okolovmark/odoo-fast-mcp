"""CRUD tools: search, read, search_read, search_count, name_search, create, write, unlink."""

import json
from typing import Annotated, Any, Literal

from anyio import to_thread
from pydantic import Field

from odoo_fast_mcp.connection import odoo_manager
from odoo_fast_mcp.server import mcp

# =============================================================================
# Record links
# =============================================================================


def _record_url(base: str, model: str, record_id: int) -> str:
    """Form view of one record in the Odoo web client.

    The hash-router form Odoo 16 uses; 17+ redirects it to ``/odoo/<model>/<id>``.
    """
    return f"{base}/web#id={record_id}&model={model}&view_type=form"


def _with_urls(records: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    """Attach ``_url`` to every record.

    The agent reads the fields; the person who asked opens the link. A record
    they can look at in Odoo beats a paraphrase they have to trust, and it costs
    one short string per row. ``_url`` sits outside the field namespace: no
    Odoo model declares a field with a leading underscore (that prefix is the
    ORM's own, cf. ``__last_update``), and custom fields must start with ``x_``.
    """
    base = odoo_manager.web_url  # one identity lookup, not one per record
    for record in records:
        record["_url"] = _record_url(base, model, record["id"])
    return records


WITH_URL_DESCRIPTION = (
    "Attach `_url` — the record's form view in the Odoo web client — to each "
    "record. Turn off for bulk pulls nobody will click."
)


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
    with_url: Annotated[bool, Field(description=WITH_URL_DESCRIPTION)] = True,
) -> list[dict[str, Any]]:
    """Read specific records by their IDs.

    Returns full record data for the specified IDs. Each record carries `_url`,
    its form view in the Odoo web client — quote it so the person can open the
    record and check for themselves.
    """
    parsed_ids = json.loads(ids)
    parsed_fields = json.loads(fields) if fields else None
    records = await to_thread.run_sync(
        lambda: odoo_manager.read(model=model, ids=parsed_ids, fields=parsed_fields),
    )
    return _with_urls(records, model) if with_url else records


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
    with_url: Annotated[bool, Field(description=WITH_URL_DESCRIPTION)] = True,
) -> list[dict[str, Any]]:
    """Search for records and return their data in a single operation.

    This is the most efficient way to query Odoo data. Combines search and read
    into one RPC call. Each record carries `_url`, its form view in the Odoo web
    client — quote it so the person can open the record and check for themselves.

    ## Domain Examples:
    - All active partners: [["active", "=", true]]
    - Partners in specific country: [["country_id", "=", 1]]
    - Orders this month: [["date_order", ">=", "2024-01-01"]]
    - Combine conditions: [["active", "=", true], ["customer_rank", ">", 0]]
    """
    parsed_domain = json.loads(domain)
    parsed_fields = json.loads(fields) if fields else None
    records = await to_thread.run_sync(
        lambda: odoo_manager.search_read(
            model=model,
            domain=parsed_domain,
            fields=parsed_fields,
            offset=offset,
            limit=limit,
            order=order,
        ),
    )
    return _with_urls(records, model) if with_url else records


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
) -> dict[str, Any]:
    """Create a new record in the specified model.

    Returns the new record's `id` and `_url` (its form view in the Odoo web
    client) — show the link so the person can see what was created.

    ## Value Examples:
    - Partner: {"name": "John", "email": "john@example.com", "is_company": false}
    - Product: {"name": "Widget", "list_price": 99.99, "type": "product"}
    """
    parsed_values = json.loads(values)
    record_id = await to_thread.run_sync(
        lambda: odoo_manager.create(model=model, values=parsed_values),
    )
    return {"id": record_id, "_url": _record_url(odoo_manager.web_url, model, record_id)}


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
