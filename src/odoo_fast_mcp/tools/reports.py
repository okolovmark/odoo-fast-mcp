"""Report generation tools: get_report."""

import json
from pathlib import Path
from typing import Annotated

from anyio import to_thread
from pydantic import Field

from odoo_fast_mcp.connection import odoo_manager
from odoo_fast_mcp.server import mcp


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
