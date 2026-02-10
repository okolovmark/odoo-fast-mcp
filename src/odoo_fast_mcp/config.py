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
    }
