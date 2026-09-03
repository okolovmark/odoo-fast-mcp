"""Configuration loading for Odoo FastMCP Server."""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def load_config(env_path: str | None = None) -> dict[str, Any]:
    """Load configuration from .env file or environment variables.

    Environment variables:
        ODOO_URL: Odoo server URL (e.g., http://localhost:8069)
        ODOO_DATABASE: Database name
        ODOO_USERNAME: Username for authentication
        ODOO_PASSWORD: Password for authentication
        ODOO_TIMEOUT: Connection timeout in seconds (default: 30)

    Multi-user HTTP deployments additionally read:
        MCP_AUTH: set to "odoo" to make callers sign in with their own Odoo login
        MCP_BASE_URL: the server's public URL, used in OAuth metadata and redirects
        MCP_STATE_DB: where credentials and OAuth state live (default: ./mcp-state.db)
        MCP_CREDENTIAL_KEY: Fernet key encrypting stored Odoo secrets
    """
    # Load .env file if it exists
    path = Path(env_path) if env_path else Path(".env")
    if path.exists():
        load_dotenv(path)
    else:
        load_dotenv()  # Try default locations

    return {
        "odoo_url": os.getenv("ODOO_URL", "http://localhost:8069"),
        "database": os.getenv("ODOO_DATABASE", ""),
        "username": os.getenv("ODOO_USERNAME", "admin"),
        "password": os.getenv("ODOO_PASSWORD", "admin"),
        "timeout": int(os.getenv("ODOO_TIMEOUT", "30")),
        "auth": os.getenv("MCP_AUTH", "").strip().lower(),
        "base_url": os.getenv("MCP_BASE_URL", ""),
        "state_db": os.getenv("MCP_STATE_DB", "mcp-state.db"),
        "credential_key": os.getenv("MCP_CREDENTIAL_KEY", ""),
    }


def parse_odoo_url(url: str) -> tuple[str, int, str]:
    """Parse an Odoo URL into ``(host, port, protocol)`` for odoorpc.

    Accepts ``http(s)://host[:port][/path]``; a missing port defaults to
    443 for https and 8069 for http.
    """
    protocol = "jsonrpc+ssl" if url.startswith("https") else "jsonrpc"
    host_part = url.replace("https://", "").replace("http://", "")
    host_part = host_part.split("/", 1)[0]
    if ":" in host_part:
        host, port_str = host_part.split(":")
        port = int(port_str)
    else:
        host = host_part
        port = 443 if "ssl" in protocol else 8069
    return host, port, protocol


def web_base_url(host: str, port: int, protocol: str) -> str:
    """Inverse of :func:`parse_odoo_url`: the origin a browser opens for this connection.

    Drops the port when it is the scheme's default, so links read the way
    people type them (``https://odoo.example.com``, not ``:443``).
    """
    scheme = "https" if protocol.endswith("+ssl") else "http"
    default_port = 443 if scheme == "https" else 80
    netloc = host if port == default_port else f"{host}:{port}"
    return f"{scheme}://{netloc}"


def load_profile(profile: str = "default") -> dict[str, Any]:
    """Load connection settings for a named env-suffix profile.

    Profile ``prod`` reads ``ODOO_URL_PROD`` / ``ODOO_DATABASE_PROD`` /
    ``ODOO_USERNAME_PROD`` / ``ODOO_PASSWORD_PROD`` (and optional
    ``ODOO_TIMEOUT_PROD``). Profile ``default`` (or ``""``) reads the
    unsuffixed ``ODOO_*`` variables — the same ones the startup
    auto-connect uses. Credentials therefore never need to travel
    through tool-call arguments.

    Raises KeyError naming the missing variables (names only, never
    values) and listing profiles that do have an ``ODOO_URL_*`` set.
    """
    load_dotenv()  # pick up profiles added after server start; no override
    name = profile.strip().lower() or "default"
    suffix = "" if name == "default" else f"_{name.upper()}"
    var_names = {key: f"ODOO_{key}{suffix}" for key in ("URL", "DATABASE", "USERNAME", "PASSWORD")}
    missing = [var for var in var_names.values() if not os.getenv(var)]
    if missing:
        available = sorted(
            key.removeprefix("ODOO_URL_").lower()
            for key in os.environ
            if key.startswith("ODOO_URL_")
        )
        msg = (
            f"Env profile '{name}': missing {', '.join(missing)}. "
            f"Suffixed profiles available: {available or 'none'}"
        )
        raise KeyError(msg)
    timeout = os.getenv(f"ODOO_TIMEOUT{suffix}") or os.getenv("ODOO_TIMEOUT") or "30"
    return {
        "odoo_url": os.environ[var_names["URL"]],
        "database": os.environ[var_names["DATABASE"]],
        "username": os.environ[var_names["USERNAME"]],
        "password": os.environ[var_names["PASSWORD"]],
        "timeout": int(timeout),
    }
