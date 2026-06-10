"""MCP resources: odoo://status, odoo://models, odoo://model/{model_name}/fields."""

from typing import Any

from anyio import to_thread

from odoo_fast_mcp.connection import odoo_manager
from odoo_fast_mcp.server import mcp


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
            "user": odoo_manager.get_user_info()["name"],
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
