"""
MCP Prompts for common Odoo analysis workflows.

Predefined prompt templates that guide LLMs through multi-step Odoo tasks
without the user needing to know the right sequence of tool calls.
"""

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register all Odoo workflow prompts on the MCP server instance."""

    @mcp.prompt(
        description="Full analysis of an Odoo model: fields, relations, and record count.",
    )
    def analyze_model(model: str) -> str:
        """Perform a comprehensive analysis of an Odoo model.

        Args:
            model: Technical model name (e.g., 'res.partner', 'sale.order').
        """
        return (
            f"Analyze the Odoo model '{model}':\n"
            f"\n"
            f"1. Use get_model_fields to retrieve all field definitions for '{model}'\n"
            f"2. Use search_count to get the total number of records\n"
            f"3. Identify relation fields (many2one, one2many, many2many) and their target models\n"
            f"4. Identify computed fields vs stored fields\n"
            f"5. List all required fields\n"
            f"\n"
            f"Summarize your findings:\n"
            f"- Total field count and breakdown by type (char, integer, boolean, etc.)\n"
            f"- Required fields and their types\n"
            f"- Relation fields with their target models and relation type\n"
            f"- Computed/readonly fields\n"
            f"- Total record count in the database\n"
        )

    @mcp.prompt(
        description="Audit records in an Odoo model for data quality issues.",
    )
    def audit_records(model: str, domain: str = "[]") -> str:
        """Check a model for data quality issues such as missing required fields,
        orphaned references, and potential duplicates.

        Args:
            model: Technical model name (e.g., 'res.partner').
            domain: Optional search domain as JSON string to filter records (default: all records).
        """
        return (
            f"Audit data quality for the Odoo model '{model}' "
            f"with domain filter {domain}:\n"
            f"\n"
            f"1. Use get_model_fields to retrieve field definitions for '{model}'\n"
            f"2. Identify all required fields from the field definitions\n"
            f"3. Use search_count with domain {domain} to get total records in scope\n"
            f"4. For each required field, use search_read to find records where the field "
            f"is empty or False (check with domain: [('field_name', '=', False)])\n"
            f"5. Identify many2one relation fields, then check for orphaned references "
            f"by looking for records pointing to non-existent related records\n"
            f"6. Look for potential duplicates by checking commonly unique fields "
            f"(name, email, reference) using search_read grouped by those fields\n"
            f"\n"
            f"Report your findings:\n"
            f"- Total records audited\n"
            f"- Records with missing required fields (list field name and count)\n"
            f"- Potential orphaned references\n"
            f"- Potential duplicate records\n"
            f"- Overall data quality assessment and recommendations\n"
        )

    @mcp.prompt(
        description="Sample and summarize data in an Odoo model for quick exploration.",
    )
    def explore_data(
        model: str,
        fields: str = "",
        limit: str = "10",
    ) -> str:
        """Sample and summarize data in an Odoo model.

        Args:
            model: Technical model name (e.g., 'res.partner', 'product.product').
            fields: Comma-separated list of field names to include (empty = auto-select).
            limit: Number of sample records to retrieve (default: 10).
        """
        fields_instruction = (
            f"focusing on fields: {fields}"
            if fields
            else "auto-selecting the most relevant fields (name, key identifiers, "
            "status fields, and important dates)"
        )

        return (
            f"Explore and summarize data in the Odoo model '{model}', "
            f"{fields_instruction}:\n"
            f"\n"
            f"1. Use get_model_fields to understand the model structure\n"
            f"2. Use search_count with domain '[]' to get the total record count\n"
            f"3. Select the most informative fields if none were specified "
            f"(prefer name, state/status, dates, key relations)\n"
            f"4. Use search_read with limit={limit} to fetch sample records\n"
            f"5. If the model has a state or status field, use search_read grouped "
            f"by that field to show the distribution of records across states\n"
            f"\n"
            f"Summarize your findings:\n"
            f"- Model description and total record count\n"
            f"- Sample records in a readable table format\n"
            f"- Distribution of records by state/status (if applicable)\n"
            f"- Key observations about the data (patterns, common values, gaps)\n"
        )

    @mcp.prompt(
        description="Compare the structure of two Odoo models side by side.",
    )
    def compare_models(model_a: str, model_b: str) -> str:
        """Diff the field structure of two Odoo models.

        Args:
            model_a: First model technical name (e.g., 'sale.order').
            model_b: Second model technical name (e.g., 'purchase.order').
        """
        return (
            f"Compare the structure of Odoo models '{model_a}' and '{model_b}':\n"
            f"\n"
            f"1. Use get_model_fields to retrieve field definitions for '{model_a}'\n"
            f"2. Use get_model_fields to retrieve field definitions for '{model_b}'\n"
            f"3. Use search_count to get the record count for each model\n"
            f"\n"
            f"Compare and report:\n"
            f"- Fields present in '{model_a}' but not in '{model_b}'\n"
            f"- Fields present in '{model_b}' but not in '{model_a}'\n"
            f"- Fields with the same name but different types or attributes\n"
            f"- Common fields shared by both models\n"
            f"- Relation fields and how the models connect to other parts of Odoo\n"
            f"- Record count comparison\n"
            f"\n"
            f"Present the comparison in a clear table format and highlight "
            f"the key structural differences and similarities.\n"
        )
