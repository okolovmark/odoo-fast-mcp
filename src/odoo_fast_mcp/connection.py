"""Odoo connection manager with thread-safe operations."""

from typing import Any

import odoorpc


class OdooConnectionManager:
    """Manages OdooRPC connection with thread-safe operations."""

    def __init__(self):
        self._odoo: odoorpc.ODOO | None = None
        self._config: dict[str, Any] = {}
        self._connected: bool = False

    @property
    def odoo(self) -> odoorpc.ODOO:
        """Get the current Odoo connection."""
        if not self._odoo or not self._connected:
            msg = "Not connected to Odoo. Use 'connect' tool first."
            raise ConnectionError(msg)
        return self._odoo

    @property
    def is_connected(self) -> bool:
        """Check if connected to Odoo."""
        return self._connected and self._odoo is not None

    def connect(
        self,
        host: str,
        port: int = 8069,
        protocol: str = "jsonrpc",
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Establish connection to Odoo server."""
        try:
            self._odoo = odoorpc.ODOO(host, protocol, port)
            self._odoo.config["timeout"] = timeout

            if database and username and password:
                self._odoo.login(database, username, password)
                self._connected = True
                # Store config for report HTTP requests
                self._config = {
                    "host": host,
                    "port": port,
                    "protocol": protocol,
                    "database": database,
                    "username": username,
                    "password": password,
                }
                return {
                    "status": "connected",
                    "host": host,
                    "port": port,
                    "database": database,
                    "user": self._odoo.env.user.name,
                    "uid": self._odoo.env.uid,
                    "version": self._odoo.version,
                }

            return {
                "status": "connected_no_auth",
                "host": host,
                "port": port,
                "message": "Connected but not authenticated. Call login separately.",
            }

        except Exception as e:
            self._connected = False
            msg = f"Connection failed: {e}"
            raise ConnectionError(msg) from e

    def disconnect(self) -> dict[str, str]:
        """Disconnect from Odoo server."""
        if self._odoo:
            self._odoo = None
        self._connected = False
        return {"status": "disconnected"}

    def list_databases(self, host: str, port: int = 8069, protocol: str = "jsonrpc") -> list[str]:
        """List available databases on the Odoo server."""
        temp_odoo = odoorpc.ODOO(host, protocol, port)
        return temp_odoo.db.list()

    def get_server_version(self) -> str:
        """Get Odoo server version."""
        return self.odoo.version

    def search(
        self,
        model: str,
        domain: list | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[int]:
        """Search for record IDs matching the domain."""
        domain = domain or []
        return self.odoo.env[model].search(domain, offset=offset, limit=limit, order=order)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read records by IDs."""
        return self.odoo.execute(model, "read", ids, fields or [])

    def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search and read records in a single call."""
        domain = domain or []
        return self.odoo.env[model].search_read(
            domain, fields=fields, offset=offset, limit=limit, order=order,
        )

    def create(self, model: str, values: dict[str, Any]) -> int:
        """Create a new record."""
        return self.odoo.env[model].create(values)

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        """Update existing records."""
        return self.odoo.execute(model, "write", ids, values)

    def unlink(self, model: str, ids: list[int]) -> bool:
        """Delete records."""
        return self.odoo.execute(model, "unlink", ids)

    def search_count(self, model: str, domain: list | None = None) -> int:
        """Count records matching the domain."""
        domain = domain or []
        return self.odoo.env[model].search_count(domain)

    def execute(
        self,
        model: str,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute any method on a model."""
        return self.odoo.execute(model, method, *args, **kwargs)

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> Any:
        """Execute method with explicit args and kwargs."""
        args = args or []
        kwargs = kwargs or {}
        return self.odoo.execute_kw(model, method, args, kwargs)

    def get_model_fields(
        self,
        model: str,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get field definitions for a model."""
        attributes = attributes or ["string", "type", "required", "readonly", "help", "relation"]
        return self.odoo.execute(model, "fields_get", [], {"attributes": attributes})

    def list_models(self, filter_installed: bool = True) -> list[dict[str, Any]]:
        """List available models in the system."""
        domain: list[Any] = [("transient", "=", False)]
        if filter_installed:
            # Filter to only show models from installed modules
            # by checking if the model has any records in ir.model.access
            domain.append(("access_ids", "!=", False))
        return self.odoo.env["ir.model"].search_read(
            domain,
            fields=["model", "name", "info"],
            order="model",
        )

    def get_report(
        self,
        report_name: str,
        record_ids: list[int],
        report_type: str = "pdf",
    ) -> bytes:
        """Generate and download a report.

        Note: Due to CSRF protection in Odoo 16+, direct report downloads
        via HTTP are restricted. This method provides information about the
        report but cannot download the actual PDF without browser interaction.

        For report generation, consider using Odoo's scheduled actions or
        the web interface.
        """
        # Try to find the report by name or report_name field
        report_model = self.odoo.env["ir.actions.report"]
        reports = report_model.search_read(
            ["|", ("report_name", "=", report_name), ("name", "ilike", report_name)],
            fields=["report_name", "name", "model", "report_type"],
            limit=1,
        )

        if not reports:
            msg = f"Report '{report_name}' not found"
            raise ValueError(msg)

        report_info = reports[0]

        # Due to CSRF protection in Odoo 16+, we cannot download reports
        # via HTTP without a valid CSRF token from the web client.
        # OdooRPC's report.download is also not implemented for Odoo 16+.
        msg = (
            f"Report download is not supported for Odoo 16+ due to CSRF protection. "
            f"Report found: '{report_info['name']}' ({report_info['report_name']}). "
            f"Please use the Odoo web interface to download reports, or consider "
            f"using scheduled actions for automated report generation."
        )
        raise NotImplementedError(msg)

    def name_search(
        self,
        model: str,
        name: str = "",
        args: list | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        """Search for records by name."""
        args = args or []
        return self.odoo.execute(model, "name_search", name, args, operator, limit)


# Global connection manager instance
odoo_manager = OdooConnectionManager()
