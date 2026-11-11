"""One SQLite connection per operation, closed when the operation ends."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the state database for one operation: commit or roll back, then close.

    ``with sqlite3.connect(...) as conn`` ends the transaction and nothing more.
    The connection stays open, holding the database and its WAL file, until the
    garbage collector reaches it; and in WAL mode SQLite keeps even a collected
    connection's descriptors while any other connection to the same file is
    open, since closing them would drop that connection's locks. Every
    authenticated request reads a token, so the process ran out of descriptors
    (EMFILE): it accepted no request, and asyncio's accept loop spun at full CPU
    logging the failure, while the service still showed as running.
    """
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            yield conn
    finally:
        conn.close()
