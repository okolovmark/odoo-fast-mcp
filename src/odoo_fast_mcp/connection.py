"""Odoo connection manager with thread-safe operations."""

import logging
import threading
import time
from typing import Any, cast

import odoorpc

logger = logging.getLogger(__name__)


class OdooConnectionManager:
    """Manages OdooRPC connection with thread-safe operations.

    All state mutations and reads are guarded by a reentrant lock
    to prevent races when tool handlers run in concurrent worker threads.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._odoo: odoorpc.ODOO | None = None
        self._connected: bool = False

    @property
    def odoo(self) -> odoorpc.ODOO:
        """Get the current Odoo connection."""
        with self._lock:
            if not self._odoo or not self._connected:
                msg = "Not connected to Odoo. Use 'connect' tool first."
                raise ConnectionError(msg)
            return self._odoo

    @property
    def is_connected(self) -> bool:
        """Check if connected to Odoo."""
        with self._lock:
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
        """Establish connection to Odoo server.

        The current session (if any) is swapped out only after the new login
        succeeds — a failed attempt must not clobber a working connection.
        """
        with self._lock:
            try:
                new_odoo = odoorpc.ODOO(host, protocol, port)
                new_odoo.config["timeout"] = timeout

                if database and username and password:
                    new_odoo.login(database, username, password)
                    self._odoo = new_odoo
                    self._connected = True
                    return {
                        "status": "connected",
                        "host": host,
                        "port": port,
                        "database": database,
                        "user": self.get_user_info()["name"],
                        "uid": self._odoo.env.uid,
                        "version": self._odoo.version,
                    }

                # Reachability probe only — keep whatever session is active.
                return {
                    "status": "connected_no_auth",
                    "host": host,
                    "port": port,
                    "message": (
                        "Server reachable but not authenticated; any previous "
                        "session is kept. Re-run 'connect' with database, "
                        "username, and password to authenticate."
                    ),
                }

            except Exception as e:
                msg = f"Connection failed: {e}"
                raise ConnectionError(msg) from e

    def get_user_info(self, with_company: bool = False) -> dict[str, Any]:
        """Read the authenticated user's name (and company) with an explicit field list.

        A bare ``env.user.name`` makes odoorpc read the whole res.users record,
        which fires every computed field on the model — restricted service
        accounts then hit AccessError on models they cannot read (e.g. a custom
        compute touching account.move.line without compute_sudo).
        """
        fields = ["name", "company_id"] if with_company else ["name"]
        rec = self.odoo.execute("res.users", "read", [self.odoo.env.uid], fields)[0]
        info: dict[str, Any] = {"name": rec["name"]}
        if with_company:
            info["company"] = rec["company_id"][1] if rec["company_id"] else None
        return info

    def disconnect(self) -> dict[str, str]:
        """Disconnect from Odoo server."""
        with self._lock:
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
    ) -> Any:
        """Execute any method on a model (positional args only).

        odoorpc's ``execute`` accepts no keyword arguments — passing any
        would TypeError. Use :meth:`execute_kw` when kwargs are needed.
        """
        return self.odoo.execute(model, method, *args)

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
    ) -> dict[str, Any]:
        """Look up an Odoo report and return its metadata.

        Note: Due to CSRF protection in Odoo 16+, direct report downloads
        via HTTP/RPC are not supported. This method returns the report metadata
        along with guidance on how to obtain the actual PDF.
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
        return {
            "report_name": report_info["report_name"],
            "display_name": report_info["name"],
            "model": report_info["model"],
            "report_type": report_info["report_type"],
            "record_ids": record_ids,
            "download_supported": False,
            "guidance": (
                "Report download is not supported for Odoo 16+ due to CSRF protection. "
                "Use the Odoo web interface to download reports, or consider "
                "using scheduled actions for automated report generation."
            ),
        }

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


DEFAULT_IDENTITY = "default"


class ConnectionRegistry:
    """One :class:`OdooConnectionManager` per caller identity.

    Over stdio the server belongs to a single person and one connection is the
    whole story. Over HTTP the same process serves the whole organisation, and a
    single shared connection would make every record land under whichever
    account the server was started with — the Odoo audit trail would name the
    server, not the person who asked. Keying by identity keeps each caller on
    their own Odoo session.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._managers: dict[str, OdooConnectionManager] = {}
        self._last_used: dict[str, float] = {}

    def get(self, identity: str) -> OdooConnectionManager:
        """Return this identity's manager, creating an unconnected one if new."""
        with self._lock:
            manager = self._managers.get(identity)
            if manager is None:
                manager = OdooConnectionManager()
                self._managers[identity] = manager
            self._last_used[identity] = time.monotonic()
            return manager

    def release_idle(self, max_idle_seconds: float) -> list[str]:
        """Disconnect identities untouched for ``max_idle_seconds``.

        Long-lived sessions are the cost of a shared deployment: without this,
        everyone who ran one query in the morning still holds an Odoo session at
        midnight. ``DEFAULT_IDENTITY`` is exempt — it is the stdio/env-credential
        connection, and nothing would re-establish it.
        """
        cutoff = time.monotonic() - max_idle_seconds
        with self._lock:
            stale = [
                identity
                for identity, last_used in self._last_used.items()
                if last_used < cutoff and identity != DEFAULT_IDENTITY
            ]
            for identity in stale:
                self._managers.pop(identity).disconnect()
                del self._last_used[identity]
            return stale

    def shutdown(self) -> None:
        """Disconnect every identity. Called once on server shutdown."""
        with self._lock:
            for manager in self._managers.values():
                manager.disconnect()
            self._managers.clear()
            self._last_used.clear()

    @property
    def identities(self) -> list[str]:
        with self._lock:
            return sorted(self._managers)


registry = ConnectionRegistry()


def current_identity() -> str:
    """Identity of the caller currently being served.

    Reads the authenticated subject from the access token when the server runs
    behind an auth provider. Everything else — stdio, an unauthenticated HTTP
    deployment, code called outside a request — shares ``DEFAULT_IDENTITY``, so
    the single-user behaviour is exactly what it was before identities existed.

    fastmcp is imported lazily: this module is otherwise transport-agnostic and
    stays importable (and testable) without a server context.

    A failure to *read* a token is deliberately not caught. Once auth is
    configured, falling back to the default identity would hand the caller the
    server's own env-credential connection — a broken token must fail the
    request, not quietly upgrade it.
    """
    try:
        from fastmcp.server.dependencies import get_access_token
    except ImportError:  # used as a library, without the server extras
        return DEFAULT_IDENTITY

    token = get_access_token()
    if token is None:  # no auth provider, or no request in flight
        return DEFAULT_IDENTITY
    return token.subject or token.client_id or DEFAULT_IDENTITY


class _CurrentManager:
    """Module-level stand-in that resolves to the calling identity's manager.

    Tool modules bind ``odoo_manager`` once at import time, so the object they
    hold must stay the same forever while the connection behind it changes from
    request to request. Forwarding attribute access keeps all ~40 call sites —
    and the stdio path — untouched by the move to per-identity connections.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(registry.get(current_identity()), name)

    def __repr__(self) -> str:
        return f"<odoo_manager identity={current_identity()!r}>"


# Global entry point: looks like one manager, resolves to the caller's own.
odoo_manager: OdooConnectionManager = cast("OdooConnectionManager", _CurrentManager())
