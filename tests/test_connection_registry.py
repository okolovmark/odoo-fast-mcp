"""The registry has to keep callers apart — that is its whole job."""

import threading
import time

import pytest

from odoo_fast_mcp.connection import (
    DEFAULT_IDENTITY,
    ConnectionRegistry,
    OdooConnectionManager,
    current_identity,
    odoo_manager,
)


@pytest.fixture
def registry():
    reg = ConnectionRegistry()
    yield reg
    reg.shutdown()


def test_each_identity_gets_its_own_manager(registry):
    alice = registry.get("alice@example.com")
    bob = registry.get("bob@example.com")
    assert alice is not bob


def test_same_identity_keeps_its_session(registry):
    first = registry.get("alice@example.com")
    assert registry.get("alice@example.com") is first


def test_unauthenticated_callers_share_the_default_identity():
    # No request in flight and no auth provider: the stdio case.
    assert current_identity() == DEFAULT_IDENTITY


def test_module_level_manager_proxies_to_the_current_identity():
    # Tool modules bind this object once at import time; it must stay usable.
    assert odoo_manager.is_connected is False
    assert DEFAULT_IDENTITY in repr(odoo_manager)


def test_missing_attributes_still_raise_attribute_error():
    with pytest.raises(AttributeError):
        odoo_manager.no_such_method  # noqa: B018


def test_idle_identities_are_released(registry):
    registry.get("alice@example.com")
    registry.get("bob@example.com")
    released = registry.release_idle(max_idle_seconds=-1)
    assert sorted(released) == ["alice@example.com", "bob@example.com"]
    assert registry.identities == []


def test_default_identity_survives_the_sweep(registry):
    # Nothing would re-establish the env-credential connection, so it must stay.
    registry.get(DEFAULT_IDENTITY)
    registry.get("alice@example.com")
    assert registry.release_idle(max_idle_seconds=-1) == ["alice@example.com"]
    assert registry.identities == [DEFAULT_IDENTITY]


def test_idle_sessions_are_swept_without_a_background_task():
    # The sweep rides along with ordinary lookups, so it must actually fire.
    reg = ConnectionRegistry(idle_timeout_seconds=0, sweep_interval_seconds=0)
    reg.get("alice@example.com")
    reg.get("bob@example.com")
    assert "alice@example.com" not in reg.identities
    reg.shutdown()


def test_sweeping_holds_off_between_intervals():
    reg = ConnectionRegistry(idle_timeout_seconds=0, sweep_interval_seconds=3600)
    reg.get("alice@example.com")
    reg.get("bob@example.com")
    assert sorted(reg.identities) == ["alice@example.com", "bob@example.com"]
    reg.shutdown()


def test_busy_identities_are_kept(registry):
    registry.get("alice@example.com")
    assert registry.release_idle(max_idle_seconds=3600) == []
    assert registry.identities == ["alice@example.com"]


def test_credential_provider_logs_an_identity_in(registry, monkeypatch):
    seen = {}

    def fake_connect(self, **kwargs):
        seen.update(kwargs)
        # Mirror what a real login leaves behind: is_connected wants both.
        self._odoo = object()
        self._connected = True
        return {"status": "connected"}

    monkeypatch.setattr(OdooConnectionManager, "connect", fake_connect)
    registry.set_credential_provider(
        lambda identity: {"host": "odoo.example.com", "username": identity} if identity == "alice"
        else None,
    )

    assert registry.get("alice").is_connected
    assert seen == {"host": "odoo.example.com", "username": "alice"}


def test_identity_without_a_credential_stays_out(registry):
    registry.set_credential_provider(lambda identity: None)
    assert registry.get("stranger").is_connected is False


def test_a_slow_login_does_not_block_other_callers(registry, monkeypatch):
    # Logging in is a network round trip; if it were held under the registry
    # lock, one person signing in would freeze everyone else's lookups.
    def fake_connect(self, **kwargs):
        if kwargs.get("username") == "slow":
            time.sleep(0.5)
        self._odoo = object()
        self._connected = True
        return {"status": "connected"}

    monkeypatch.setattr(OdooConnectionManager, "connect", fake_connect)
    registry.set_credential_provider(lambda identity: {"username": identity})

    slow = threading.Thread(target=registry.get, args=("slow",))
    slow.start()
    time.sleep(0.05)  # let the slow login get under way

    started = time.monotonic()
    registry.get("quick")
    assert time.monotonic() - started < 0.3

    slow.join()


def test_connected_identity_is_not_logged_in_twice(registry, monkeypatch):
    calls = []

    def fake_connect(self, **kwargs):
        calls.append(kwargs)
        # Mirror what a real login leaves behind: is_connected wants both.
        self._odoo = object()
        self._connected = True
        return {"status": "connected"}

    monkeypatch.setattr(OdooConnectionManager, "connect", fake_connect)
    registry.set_credential_provider(lambda identity: {"host": "h"})

    registry.get("alice")
    registry.get("alice")
    assert len(calls) == 1
