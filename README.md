# odoo-fast-mcp

A Model Context Protocol (MCP) server for Odoo 16+ using OdooRPC. This server enables AI assistants to interact with Odoo ERP systems through a standardized interface.

## Features 🚀

- **Full CRUD Operations**: Create, Read, Update, Delete records in any Odoo model
- **Connection Management**: Connect to multiple databases, auto-connect from config
- **Model Introspection**: Discover models and field definitions
- **Method Execution**: Call any Odoo model method (workflow actions, custom methods)
- **Report Generation**: Generate and download Odoo reports (PDF)
- **MCP Resources**: Access connection status and model info as MCP resources
- **Multi-user mode**: OAuth sign-in with each caller's own Odoo login, one session per person

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

### Record links

`read`, `search_read` and `create` add `_url` to every record: its form view in
the Odoo web client, built from the connection's host, port and protocol. The
agent gets the fields, the person gets a link they can open to check the record
for themselves. Pass `with_url=false` to leave it out of bulk pulls.

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

### Stdio Transport (default)

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

### HTTP Transport (Streamable HTTP)

HTTP transport turns the MCP server into a web service accessible via URL. This is required for MCP Apps, remote deployments, and multi-client setups.

```bash
# Start HTTP server on default port 8000
odoo-fast-mcp --transport http

# Custom host and port
odoo-fast-mcp --transport http --host 127.0.0.1 --port 3001

# With debug logging
odoo-fast-mcp --transport http --port 3001 --debug
```

The server will be available at `http://<host>:<port>/mcp`.

You can also configure transport via environment variables in your `.env` file:

```bash
MCP_TRANSPORT=http
MCP_HOST=0.0.0.0
MCP_PORT=8000
```

> **Note:** CLI arguments take precedence over environment variables, which take precedence over defaults.

### SSE Transport (legacy)

```bash
odoo-fast-mcp --transport sse --port 8000
```

### Connecting from MCP clients (HTTP mode)

When using HTTP transport, configure your MCP client to connect via URL instead of stdio:

```json
"odoo": {
    "type": "http",
    "url": "http://localhost:8000/mcp"
}
```

## Multi-user mode (OAuth) 🔐

By default the server holds one Odoo session, from the credentials in its
environment — right for stdio, where the process belongs to one person. A server
reachable by a team needs the opposite: every caller reaching Odoo **as
themselves**, so that a record written through the MCP is attributed to the
person who asked for it and not to a shared account.

Odoo offers no impersonation over RPC, so each person signs in once with their
own Odoo login and an **API key**, which is verified against Odoo, encrypted and
kept. From then on the server opens a separate Odoo session per identity,
reconnecting silently when one expires and dropping sessions that go idle.

The server acts as an OAuth 2.1 authorization server whose identity provider is
Odoo itself. It serves discovery metadata, accepts dynamic client registration
and enforces PKCE, so an MCP client can connect with no configuration beyond the
URL.

```bash
MCP_AUTH=odoo
MCP_BASE_URL=https://mcp.example.com        # exactly as clients reach it
MCP_CREDENTIAL_KEY=<Fernet key>             # encrypts stored Odoo API keys
MCP_STATE_DB=/var/lib/odoo-mcp/state.db     # credentials, clients, tokens

ODOO_URL=https://odoo.example.com
ODOO_DATABASE=mydb
# ODOO_USERNAME / ODOO_PASSWORD deliberately unset — see below
```

Generate the encryption key once and keep it safe:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then run the server as usual with `--transport http`. Notes worth knowing:

- **`MCP_BASE_URL` must equal the public URL exactly.** It is published in the
  OAuth metadata and used to build the sign-in redirect; a mismatch fails in ways
  that are hard to read.
- **The startup auto-connect is skipped** while `MCP_AUTH=odoo` is set. A shared
  server should hold no Odoo session that is not somebody's own, so leave
  `ODOO_USERNAME` / `ODOO_PASSWORD` unset.
- **Back up `MCP_CREDENTIAL_KEY` and the state database.** Lose the key and every
  stored API key becomes undecryptable; lose the database and everyone signs in
  again and re-adds the server.
- **Behind a reverse proxy**, turn buffering off and raise the read timeout —
  streamable HTTP holds a response open and streams events down it. And do not
  send a `form-action` CSP: it governs the whole redirect chain after a form
  submission, so it silently blocks the last hop of sign-in, back to the client's
  callback.

### Adding it to Claude on the web

In claude.ai, **Settings → Connectors → Add custom connector**, with the URL
`https://mcp.example.com/mcp`. Leave the OAuth client fields empty — the server
registers clients dynamically. On Team and Enterprise plans only an Owner can add
a connector for the organization; each person then presses **Connect** and signs
in with their own Odoo login and API key. An Odoo API key is created under
**Preferences → Account Security**, and can be revoked there at any time.

Claude connects from Anthropic's cloud, so the server must be reachable over the
public internet (or have those addresses allowed through the firewall).

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
