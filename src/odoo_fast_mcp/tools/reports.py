"""Report generation tools: get_report."""

import json
from typing import Annotated, Any

from anyio import to_thread
from pydantic import Field

from odoo_fast_mcp.connection import odoo_manager
from odoo_fast_mcp.server import mcp


@mcp.tool(
    annotations={
        "title": "Get Report Info",
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
) -> dict[str, Any]:
    """Look up an Odoo report and return its metadata.

    Due to CSRF protection in Odoo 16+, direct report download via RPC
    is not supported. This tool returns report metadata and guidance on
    how to obtain the actual PDF.

    Common reports:
    - Invoice: account.report_invoice
    - Sale Order: sale.report_saleorder
    - Purchase Order: purchase.report_purchaseorder
    - Delivery Slip: stock.report_deliveryslip
    """
    parsed_ids = json.loads(ids)
    return await to_thread.run_sync(
        lambda: odoo_manager.get_report(report_name, parsed_ids),
    )
