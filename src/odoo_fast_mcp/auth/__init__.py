"""Authentication for shared deployments.

Only needed when the server is reachable by more than one person. Over stdio the
process belongs to whoever started it and none of this is used.
"""

from odoo_fast_mcp.auth.credentials import (
    CredentialError,
    CredentialStore,
    OdooCredentials,
    verify_credentials,
)

__all__ = [
    "CredentialError",
    "CredentialStore",
    "OdooCredentials",
    "verify_credentials",
]
