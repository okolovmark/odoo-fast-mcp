"""Odoo FastMCP - MCP server for Odoo ERP integration."""

from odoo_fast_mcp.config import load_config
from odoo_fast_mcp.connection import OdooConnectionManager, odoo_manager
from odoo_fast_mcp.server import main_cli, mcp

__all__ = [
    "OdooConnectionManager",
    "load_config",
    "main_cli",
    "mcp",
    "odoo_manager",
]
