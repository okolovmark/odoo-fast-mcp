"""Durable OAuth state: clients, codes, tokens and pending logins.

Everything here outlives a restart on purpose. A deploy that signed the whole
organisation out of Claude, or that lost the client registration and forced
every person to re-add the connector, would make routine maintenance
user-visible.

Codes and tokens are stored as SHA-256 digests. They are bearer secrets: whoever
holds the string is the user. Keeping only the digest means a copy of the
database file — a backup, a stray scp — cannot be replayed as a live session.
"""

import hashlib
import json
import logging
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS oauth_client (
        client_id  TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_code (
        digest     TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        expires_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_token (
        digest     TEXT PRIMARY KEY,
        kind       TEXT NOT NULL,
        subject    TEXT NOT NULL,
        client_id  TEXT NOT NULL,
        data       TEXT NOT NULL,
        expires_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_login (
        digest     TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        expires_at REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS oauth_token_subject ON oauth_token (subject)",
)


def new_secret() -> str:
    """A fresh bearer string: code, token or login-session handle."""
    return secrets.token_urlsafe(32)


def digest(secret: str) -> str:
    """What we keep on disk instead of the secret itself."""
    return hashlib.sha256(secret.encode()).hexdigest()


class OAuthStore:
    """SQLite-backed OAuth state, shared with the credential store's database."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- clients ----------------------------------------------------------

    def put_client(self, client_id: str, data: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_client (client_id, data, created_at) VALUES (?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET data = excluded.data
                """,
                (client_id, json.dumps(data), time.time()),
            )

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM oauth_client WHERE client_id = ?", (client_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    # -- authorization codes ----------------------------------------------

    def put_code(self, code: str, data: dict[str, Any], expires_at: float) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO oauth_code (digest, data, expires_at) VALUES (?, ?, ?)",
                (digest(code), json.dumps(data), expires_at),
            )

    def take_code(self, code: str) -> dict[str, Any] | None:
        """Read a code and delete it in one step.

        Authorization codes are single-use by specification, and deleting on read
        is what enforces it: a replayed code finds nothing.
        """
        key = digest(code)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data, expires_at FROM oauth_code WHERE digest = ?", (key,),
            ).fetchone()
            conn.execute("DELETE FROM oauth_code WHERE digest = ?", (key,))
        if row is None or row[1] < time.time():
            return None
        return json.loads(row[0])

    # -- pending logins ----------------------------------------------------

    def put_login(self, handle: str, data: dict[str, Any], expires_at: float) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO oauth_login (digest, data, expires_at) VALUES (?, ?, ?)",
                (digest(handle), json.dumps(data), expires_at),
            )

    def get_login(self, handle: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data, expires_at FROM oauth_login WHERE digest = ?", (digest(handle),),
            ).fetchone()
        if row is None or row[1] < time.time():
            return None
        return json.loads(row[0])

    def drop_login(self, handle: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM oauth_login WHERE digest = ?", (digest(handle),))

    # -- tokens ------------------------------------------------------------

    def put_token(
        self,
        token: str,
        kind: str,
        subject: str,
        client_id: str,
        data: dict[str, Any],
        expires_at: float | None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_token (digest, kind, subject, client_id, data, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (digest(token), kind, subject, client_id, json.dumps(data), expires_at),
            )

    def get_token(self, token: str, kind: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data, expires_at FROM oauth_token WHERE digest = ? AND kind = ?",
                (digest(token), kind),
            ).fetchone()
        if row is None:
            return None
        if row[1] is not None and row[1] < time.time():
            return None
        return json.loads(row[0])

    def drop_token(self, token: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM oauth_token WHERE digest = ?", (digest(token),))

    def drop_subject_tokens(self, subject: str) -> int:
        """Sign a person out everywhere. Returns how many tokens were dropped."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM oauth_token WHERE subject = ?", (subject,))
            return cursor.rowcount

    # -- housekeeping ------------------------------------------------------

    def purge_expired(self) -> int:
        """Delete everything past its expiry. Returns the number of rows removed."""
        now = time.time()
        with self._lock, self._connect() as conn:
            removed = 0
            for table in ("oauth_code", "oauth_login"):
                removed += conn.execute(
                    f"DELETE FROM {table} WHERE expires_at < ?",  # noqa: S608 - fixed names
                    (now,),
                ).rowcount
            removed += conn.execute(
                "DELETE FROM oauth_token WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            ).rowcount
            return removed
