"""Tool registration package.

Importing this package triggers all tool registrations via decorators.
"""

from odoo_fast_mcp.tools import connection, crud, meta, reports  # noqa: F401
