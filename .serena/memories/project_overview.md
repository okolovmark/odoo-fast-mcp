# Odoo Fast MCP - Project Overview

## Purpose
MCP (Model Context Protocol) server for Odoo 16+ using OdooRPC. Enables AI assistants to interact with Odoo ERP systems through a standardized interface.

## Tech Stack
- **Language**: Python 3.10+
- **Dependencies**:
  - `OdooRPC==0.10.1` - Odoo RPC client library
  - `fastmcp==2.14.4` - FastMCP framework for building MCP servers
- **Dev Dependencies**: `ruff` (linter/formatter), `ty` (type checker)
- **Build System**: setuptools with pyproject.toml

## Project Structure
```
src/odoo_fast_mcp/
├── __init__.py
└── server.py       # Main MCP server implementation
config.json         # Odoo connection configuration
pyproject.toml      # Project configuration and dependencies
README.md           # Documentation
```

## Key Components
1. **OdooConnectionManager**: Handles all OdooRPC operations (connect, CRUD, execute)
2. **FastMCP Server**: Exposes Odoo operations as MCP tools
3. **Auto-connect**: Server can auto-connect using config.json credentials

## Available Tools (17 total)
- **Connection**: connect, disconnect, list_databases, get_server_version, get_connection_status
- **Read**: search, read, search_read, search_count, name_search
- **Write**: create, write, unlink
- **Meta**: get_model_fields, list_models
- **Advanced**: execute, get_report

## MCP Resources
- `odoo://status` - Connection status
- `odoo://models` - Available models list
- `odoo://model/{model_name}/fields` - Field definitions
