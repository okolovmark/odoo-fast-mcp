"""Per-user Odoo credentials for a shared deployment.

A server that authenticates its callers still has to reach Odoo *as* each of
them. Odoo offers no impersonation over RPC, so the only way a write can be
attributed to a real person is to hold that person's own credentials and log in
with them. A credential is verified against Odoo once, when the person hands it
over, and kept encrypted afterwards so later requests can re-establish the
session without asking again.

The secret is normally an Odoo API key rather than a password: a key can be
revoked from the user's own preferences without changing their login, which is
the recovery path we want when a laptop goes missing.
"""

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from odoo_fast_mcp.connection import OdooConnectionManager

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS odoo_credential (
    subject    TEXT PRIMARY KEY,
    host       TEXT NOT NULL,
    port       INTEGER NOT NULL,
    protocol   TEXT NOT NULL,
    database   TEXT NOT NULL,
    username   TEXT NOT NULL,
    secret     BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class CredentialError(Exception):
    """A credential was rejected by Odoo, or could not be read back."""


@dataclass(frozen=True)
class OdooCredentials:
    """One person's way into Odoo.

    ``secret`` is an API key or a password; the store never writes it in clear.
    """

    host: str
    database: str
    username: str
    secret: str
    port: int = 8069
    protocol: str = "jsonrpc"
    timeout: int = 30

    def to_connect_kwargs(self) -> dict[str, Any]:
        """Arguments for :meth:`OdooConnectionManager.connect`."""
        return {
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "database": self.database,
            "username": self.username,
            "password": self.secret,
            "timeout": self.timeout,
        }

    def redacted(self) -> dict[str, Any]:
        """The same credential with the secret removed, safe to log."""
        return {
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "database": self.database,
            "username": self.username,
        }


def verify_credentials(credentials: OdooCredentials) -> dict[str, Any]:
    """Log in to Odoo once to prove the credential works.

    Runs before anything is stored: an unusable credential kept on disk would
    only surface later, as a confusing failure in the middle of someone's task.
    Returns the Odoo user it resolved to, so the caller can show *who* they were
    recognised as — a wrong-account mistake is easier to catch at login than
    three tool calls later.
    """
    manager = OdooConnectionManager()
    try:
        result = manager.connect(**credentials.to_connect_kwargs())
    except ConnectionError as exc:
        raise CredentialError(str(exc)) from exc
    finally:
        manager.disconnect()

    if result.get("status") != "connected":
        msg = "Odoo accepted the connection but not the login"
        raise CredentialError(msg)
    return {"uid": result["uid"], "name": result["user"], "database": result["database"]}


class CredentialStore:
    """Encrypted, on-disk credentials keyed by authenticated subject.

    On disk rather than in memory because a restart must not sign the whole
    organisation out; SQLite rather than a server because this rides along with
    a single deployment and adding Redis to the estate would be the larger cost.

    The encryption key comes from the environment and is deliberately not
    generated on the fly: a key written next to its ciphertext protects nobody,
    and one regenerated per boot would lock everyone out after a restart.
    """

    def __init__(self, path: str | Path, key: str | bytes) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        try:
            self._fernet = Fernet(key if isinstance(key, bytes) else key.encode())
        except (ValueError, TypeError) as exc:
            msg = (
                "Invalid credential encryption key: expected a 32-byte url-safe "
                "base64 value, as produced by Fernet.generate_key()"
            )
            raise CredentialError(msg) from exc
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def put(self, subject: str, credentials: OdooCredentials) -> None:
        """Store (or replace) one subject's credential."""
        now = datetime.now(timezone.utc).isoformat()
        secret = self._fernet.encrypt(credentials.secret.encode())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO odoo_credential
                    (subject, host, port, protocol, database, username, secret,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject) DO UPDATE SET
                    host=excluded.host, port=excluded.port, protocol=excluded.protocol,
                    database=excluded.database, username=excluded.username,
                    secret=excluded.secret, updated_at=excluded.updated_at
                """,
                (
                    subject,
                    credentials.host,
                    credentials.port,
                    credentials.protocol,
                    credentials.database,
                    credentials.username,
                    secret,
                    now,
                    now,
                ),
            )
        logger.info("Stored Odoo credential for %s", subject)

    def get(self, subject: str) -> OdooCredentials | None:
        """Return the subject's credential, or None if they have not linked one."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT host, port, protocol, database, username, secret
                FROM odoo_credential WHERE subject = ?
                """,
                (subject,),
            ).fetchone()
        if row is None:
            return None
        host, port, protocol, database, username, secret = row
        try:
            plain = self._fernet.decrypt(secret).decode()
        except InvalidToken as exc:
            # Rotating the key without re-linking leaves undecryptable rows. Say
            # so plainly instead of failing later as "wrong login ID or password".
            msg = f"Stored credential for {subject} cannot be decrypted with the current key"
            raise CredentialError(msg) from exc
        return OdooCredentials(
            host=host,
            database=database,
            username=username,
            secret=plain,
            port=port,
            protocol=protocol,
        )

    def delete(self, subject: str) -> bool:
        """Forget a subject's credential. Returns whether there was one."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM odoo_credential WHERE subject = ?", (subject,))
            return cursor.rowcount > 0

    def subjects(self) -> list[str]:
        """Every subject holding a credential, for operational visibility."""
        with self._lock, self._connect() as conn:
            return [row[0] for row in conn.execute("SELECT subject FROM odoo_credential")]


def generate_key() -> str:
    """A fresh encryption key, for operators setting the deployment up."""
    return Fernet.generate_key().decode()
