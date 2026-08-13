"""Credentials are the one thing here worth being paranoid about."""

import pytest

from odoo_fast_mcp.auth import CredentialError, CredentialStore, OdooCredentials
from odoo_fast_mcp.auth.credentials import generate_key


@pytest.fixture
def credentials():
    return OdooCredentials(
        host="odoo.example.com",
        port=443,
        protocol="jsonrpc+ssl",
        database="prod",
        username="alice@example.com",
        secret="super-secret-api-key",
    )


@pytest.fixture
def store(tmp_path):
    return CredentialStore(tmp_path / "creds.db", generate_key())


def test_round_trip_preserves_the_credential(store, credentials):
    store.put("alice", credentials)
    assert store.get("alice") == credentials


def test_unknown_subject_returns_nothing(store):
    assert store.get("nobody") is None


def test_secret_is_not_written_in_clear(tmp_path, credentials):
    path = tmp_path / "creds.db"
    CredentialStore(path, generate_key()).put("alice", credentials)
    assert credentials.secret.encode() not in path.read_bytes()


def test_relinking_replaces_the_old_secret(store, credentials):
    store.put("alice", credentials)
    rotated = OdooCredentials(**{**credentials.__dict__, "secret": "a-new-key"})
    store.put("alice", rotated)
    assert store.get("alice").secret == "a-new-key"
    assert store.subjects() == ["alice"]


def test_subjects_are_kept_apart(store, credentials):
    store.put("alice", credentials)
    store.put("bob", OdooCredentials(**{**credentials.__dict__, "username": "bob@example.com"}))
    assert store.get("alice").username == "alice@example.com"
    assert sorted(store.subjects()) == ["alice", "bob"]


def test_delete_forgets_the_credential(store, credentials):
    store.put("alice", credentials)
    assert store.delete("alice") is True
    assert store.get("alice") is None
    assert store.delete("alice") is False


def test_a_rotated_key_says_so(tmp_path, credentials):
    path = tmp_path / "creds.db"
    CredentialStore(path, generate_key()).put("alice", credentials)
    with pytest.raises(CredentialError, match="cannot be decrypted"):
        CredentialStore(path, generate_key()).get("alice")


def test_a_malformed_key_is_refused_at_startup(tmp_path):
    with pytest.raises(CredentialError, match="Invalid credential encryption key"):
        CredentialStore(tmp_path / "creds.db", "not-a-fernet-key")


def test_the_store_survives_a_restart(tmp_path, credentials):
    path, key = tmp_path / "creds.db", generate_key()
    CredentialStore(path, key).put("alice", credentials)
    # A restart must not sign the organisation out.
    assert CredentialStore(path, key).get("alice") == credentials


def test_redacted_never_leaks_the_secret(credentials):
    assert credentials.secret not in str(credentials.redacted())


def test_connect_kwargs_map_the_secret_onto_password(credentials):
    kwargs = credentials.to_connect_kwargs()
    assert kwargs["password"] == credentials.secret
    assert kwargs["username"] == credentials.username
