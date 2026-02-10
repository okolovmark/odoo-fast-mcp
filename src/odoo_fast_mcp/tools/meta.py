"""Metadata tools: get_model_fields, list_models, execute."""

import json
from typing import Annotated, Any

from anyio import to_thread
from pydantic import Field

from odoo_fast_mcp.connection import odoo_manager
from odoo_fast_mcp.server import mcp


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
