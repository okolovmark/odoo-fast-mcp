# odoo-fast-mcp

A Model Context Protocol (MCP) server for Odoo 16+ using OdooRPC. This server enables AI assistants to interact with Odoo ERP systems through a standardized interface.

## Features 🚀

- **Full CRUD Operations**: Create, Read, Update, Delete records in any Odoo model
- **Connection Management**: Connect to multiple databases, auto-connect from config
- **Model Introspection**: Discover models and field definitions
- **Method Execution**: Call any Odoo model method (workflow actions, custom methods)
- **Report Generation**: Generate and download Odoo reports (PDF)
- **MCP Resources**: Access connection status and model info as MCP resources

## Usage 📚

If you downloaded this repo, you can configure your MCP client (e.g., VSCode) to use the server by adding the following configuration:

```json
"odoo": {
    "type": "stdio",
    "command": "uvx",
    "args": [
        "--from",
        ".",
        "odoo-fast-mcp"
    ],
    "envFile": "${workspaceFolder}/.env"
},
```

in other project you can use it like this:

```json
"odoo": {
    "type": "stdio",
    "command": "uvx",
    "args": [
        "--from",
        "git+https://github.com/okolovmark/odoo-fast-mcp",
        "odoo-fast-mcp"
    ],
    "envFile": "${workspaceFolder}/.env"
},
```

## Available Tools 🛠️

### Connection Tools

| Tool                    | Description                                     |
| ----------------------- | ----------------------------------------------- |
| `connect`               | Connect and authenticate to an Odoo server      |
| `disconnect`            | Disconnect from the current session             |
| `list_databases`        | List available databases on an Odoo server      |
| `get_server_version`    | Get the version of the connected Odoo server    |
| `get_connection_status` | Get current connection status and user info     |

### Read Operations

| Tool           | Description                                                 |
| -------------- | ----------------------------------------------------------- |
| `search`       | Search for record IDs matching a domain filter              |
| `read`         | Read specific records by their IDs                          |
| `search_read`  | Search and read records in a single operation (recommended) |
| `search_count` | Count records matching a domain                             |
| `name_search`  | Search records by name with fuzzy matching                  |

### Write Operations

| Tool     | Description                    |
| -------- | ------------------------------ |
| `create` | Create a new record in a model |
| `write`  | Update existing records        |
| `unlink` | Delete records (destructive)   |

### Metadata Tools

| Tool               | Description                                    |
| ------------------ | ---------------------------------------------- |
| `get_model_fields` | Get field definitions for a model              |
| `list_models`      | List all available models in the Odoo instance |

### Advanced Tools

| Tool         | Description                             |
| ------------ | --------------------------------------- |
| `execute`    | Execute any method on an Odoo model     |
| `get_report` | Generate and save an Odoo report as PDF |

## Configuration ⚙️

Create a `.env` file with your Odoo connection details:

```bash
# Copy the example file
cp .env.example .env

# Edit with your settings
ODOO_URL=http://localhost:8069
ODOO_DATABASE=your_database
ODOO_USERNAME=admin
ODOO_PASSWORD=admin
ODOO_TIMEOUT=30
```

The server will auto-connect using these credentials on startup.

You can also set these as environment variables directly without a `.env` file.

## Domain Syntax 📝

Odoo domains are lists of conditions used for filtering records:

```python
# Basic syntax
[["field", "operator", "value"]]

# Common operators
=, !=, >, >=, <, <=, like, ilike, in, not in

# Combine conditions (implicit AND)
[["active", "=", true], ["name", "ilike", "john"]]

# Explicit operators
["&", ["field1", "=", "value1"], ["field2", "=", "value2"]]  # AND
["|", ["field1", "=", "value1"], ["field2", "=", "value2"]]  # OR
["!", ["field", "=", "value"]]  # NOT
```

## MCP Resources 📦

The server also exposes these MCP resources:

- `odoo://status` - Current connection status
- `odoo://models` - List of all available models
- `odoo://model/{model_name}/fields` - Field definitions for a specific model

---

## Creating a virtual environment with `uv` 🔧

### Quick steps

1. Create the virtual environment in the project root (seed `pip`, `setuptools`, `wheel`):

    ```bash
    uv venv .venv --seed
    # or to select a Python version:
    uv venv -p python3.11 .venv
    ```

2. Activate the venv:

    ```bash
    source .venv/bin/activate
    ```

3. Install project dependencies into the active environment:

    ```bash
    uv sync --active
    ```

## Installing the App 📦

Once the virtual environment is set up and activated:

1. **Install the app and its dependencies:**

    ```bash
    uv sync
    ```

    This installs the `odoo-fast-mcp` package in editable mode along with runtime dependencies (`OdooRPC`, `fastmcp`).

2. **For development (includes linting and type checking tools):**

    ```bash
    uv sync --extra dev
    ```

    This adds `ruff` (linter/formatter) and `ty` (type checker) to the environment.

## Running the Server 🏃

```bash
# Run with .env file in current directory
odoo-fast-mcp

# Run with custom .env file path
odoo-fast-mcp --env /path/to/.env

# Run with debug logging
odoo-fast-mcp --debug

# Or run directly
python -m odoo_fast_mcp.server
```

## Known Limitations ⚠️

### Report Download (get_report)

Due to CSRF protection in Odoo 16+, the `get_report` tool cannot download reports directly. When called, it will:

1. Verify the report exists in Odoo
2. Return report metadata (name, report_name, model)
3. Raise a `NotImplementedError` with guidance

**Workarounds:**

- Use the Odoo web interface to download reports manually
- Set up scheduled actions in Odoo to generate and store reports as attachments
- Use the `search_read` tool on `ir.attachment` to retrieve stored report attachments

---

If you want a different workflow (e.g., using system site-packages or custom prompt), run `uv help venv` for more options.
