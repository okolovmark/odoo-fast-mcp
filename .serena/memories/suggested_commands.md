# Suggested Commands

## Development Setup

```bash
# Create and activate virtual environment
uv venv .venv --seed
source .venv/bin/activate

# Install dependencies
uv sync

# Install with dev dependencies
uv sync --extra dev
```

## Running the Server

```bash
# Run with config file
odoo-fast-mcp --config config.json

# Run with debug logging
odoo-fast-mcp --config config.json --debug

# Run directly with Python
python -m odoo_fast_mcp.server --config config.json
```

## Linting and Formatting

```bash
# Check code with ruff
ruff check src/

# Fix auto-fixable issues
ruff check --fix src/

# Format code
ruff format src/
```

## Type Checking

```bash
# Run type checker (if ty is installed)
ty check src/
```

## Building

```bash
# Build the package
python -m build

# Install in development mode
pip install -e .
```

## Testing Syntax

```bash
# Quick syntax check
python -m py_compile src/odoo_fast_mcp/server.py
```
