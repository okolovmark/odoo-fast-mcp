"""The state database gives its file descriptors back after every operation."""

import gc
import os
import sqlite3
from pathlib import Path

import pytest

from odoo_fast_mcp.auth import CredentialStore, OdooCredentials
from odoo_fast_mcp.auth.credentials import generate_key
from odoo_fast_mcp.auth.store import OAuthStore

FD_DIR = Path("/proc/self/fd")
pytestmark = pytest.mark.skipif(not FD_DIR.is_dir(), reason="counts /proc/self/fd (Linux)")

CALLS = 200


def _open_fds() -> int:
    return len(os.listdir(FD_DIR))


@pytest.fixture(autouse=True)
def no_gc():
    # An unclosed connection is released only when the collector reaches it,
    # which hid the leak in light use. With the collector off it shows at once.
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


@pytest.fixture
def oauth_store(tmp_path):
    store = OAuthStore(tmp_path / "state.db")
    store.put_token("token", "access", "alice", "client", {"scopes": []}, None)
    return store


def test_token_lookups_hold_no_descriptors(oauth_store):
    before = _open_fds()
    for _ in range(CALLS):
        assert oauth_store.get_token("token", "access") is not None
    assert _open_fds() == before


def test_a_failed_write_holds_no_descriptors(oauth_store):
    oauth_store.put_code("code", {}, expires_at=0)
    before = _open_fds()
    for _ in range(CALLS):
        with pytest.raises(sqlite3.IntegrityError):
            oauth_store.put_code("code", {}, expires_at=0)
    assert _open_fds() == before


def test_credential_lookups_hold_no_descriptors(tmp_path):
    store = CredentialStore(tmp_path / "state.db", generate_key())
    store.put(
        "alice",
        OdooCredentials(host="odoo.example.com", database="prod", username="alice", secret="k"),
    )
    before = _open_fds()
    for _ in range(CALLS):
        assert store.get("alice") is not None
    assert _open_fds() == before


def test_a_write_is_committed_before_the_connection_closes(tmp_path):
    path = tmp_path / "state.db"
    OAuthStore(path).put_token("token", "access", "alice", "client", {}, None)
    assert OAuthStore(path).get_token("token", "access") == {}
