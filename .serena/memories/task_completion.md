# Task Completion Checklist

## Before Marking a Task Complete

1. **Syntax Check**
   ```bash
   python -m py_compile src/odoo_fast_mcp/server.py
   ```

2. **Linting** (if ruff is installed)
   ```bash
   ruff check src/
   ```

3. **Type Checking** (if ty is installed)
   ```bash
   ty check src/
   ```

4. **Test Import**
   ```bash
   python -c "from odoo_fast_mcp.server import mcp; print('Import OK')"
   ```

5. **Update build directory** (if modifying source)
   ```bash
   cp src/odoo_fast_mcp/server.py build/lib/odoo_fast_mcp/server.py
   ```

## For New Features

1. Add type hints to all parameters and return values
2. Add docstring with description
3. Add MCP tool annotations (title, hints)
4. Update README.md if adding new tools
5. Keep parameter descriptions clear for LLMs

## For Bug Fixes

1. Identify root cause
2. Implement fix
3. Verify syntax and linting
4. Consider edge cases

## Known Limitations

### get_report Tool
- **Status**: NOT SUPPORTED for Odoo 16+
- **Reason**: CSRF protection prevents HTTP-based report downloads
- **OdooRPC**: `report.download` throws `NotImplementedError` for Odoo 16+
- **Current behavior**: Verifies report exists, then raises `NotImplementedError` with workaround guidance
- **Workarounds**: 
  - Use Odoo web interface
  - Use scheduled actions to generate reports as attachments
  - Query `ir.attachment` for stored reports