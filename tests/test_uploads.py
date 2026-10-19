"""A file reaches Odoo over a one-time link, not as base64 in a tool call.

Through the other tools the only way a screenshot gets onto a record is base64
the model types out: expensive, and one wrong character corrupts the image.
`begin_upload` hands out a link instead and the shell sends the bytes. What has
to hold: the link works once, for the person it was issued to, for the record
it names; it refuses what is too big; and the bytes stored are the bytes sent.
"""

import asyncio
import base64
import hashlib
import time

import odoorpc
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import odoo_fast_mcp.uploads as uploads_module
from odoo_fast_mcp.auth.store import OAuthStore, digest
from odoo_fast_mcp.connection import registry
from odoo_fast_mcp.uploads import UPLOAD_PATH, Uploads, begin_upload

BASE = "https://mcp.example.test"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


class FakeManager:
    """The calling identity's Odoo session, recording what was asked of it."""

    def __init__(self, records=None, deny=None):
        self.records = records if records is not None else {("project.task", 42): "Fix the scrap report"}
        self.deny = deny
        self.created = []
        self.calls = []

    def read(self, model, ids, fields=None):
        if model == "ir.attachment":
            values = self.created[ids[0] - 1]
            raw = base64.b64decode(values["datas"])
            return [{
                "id": ids[0],
                "name": values["name"],
                "mimetype": values.get("mimetype", "image/png"),
                "file_size": len(raw),
                "checksum": hashlib.sha1(raw).hexdigest(),  # noqa: S324 - what Odoo stores
            }]
        name = self.records.get((model, ids[0]))
        return [{"id": ids[0], "display_name": name}] if name else []

    def execute_kw(self, model, method, args=None, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        if self.deny == method:
            msg = "You are not allowed to modify this document."
            raise odoorpc.error.RPCError(msg, {"data": {"name": "odoo.exceptions.AccessError"}})
        if (model, method) == ("ir.attachment", "create"):
            self.created.append(args[0])
            return len(self.created)
        return None


@pytest.fixture
def store(tmp_path):
    return OAuthStore(tmp_path / "state.db")


@pytest.fixture
def odoo(monkeypatch):
    """Every identity resolves to one fake session; `seen` records who asked."""
    manager = FakeManager()
    manager.seen = []

    def get(identity):
        manager.seen.append(identity)
        return manager

    monkeypatch.setattr(registry, "get", get)
    return manager


def client_for(service: Uploads) -> TestClient:
    app = Starlette(routes=[Route(f"{UPLOAD_PATH}/{{ticket}}", service.receive, methods=["POST"])])
    return TestClient(app)


def issue(service: Uploads, **overrides) -> str:
    args = {"identity": "mark@example.test", "model": "project.task", "res_id": 42,
            "name": "before.png", "mimetype": None, **overrides}
    url = service.issue(**args)
    return url.removeprefix(BASE)


# --- the store ---------------------------------------------------------------


def test_a_ticket_is_kept_only_as_its_digest(store, tmp_path):
    store.put_upload("the-ticket", {"subject": "s"}, expires_at=time.time() + 60)
    # WAL mode: a fresh row sits in the -wal file until a checkpoint.
    raw = b"".join(path.read_bytes() for path in tmp_path.glob("state.db*"))
    assert b"the-ticket" not in raw
    assert digest("the-ticket").encode() in raw


def test_a_ticket_redeems_once(store):
    store.put_upload("t", {"subject": "s"}, expires_at=time.time() + 60)
    assert store.take_upload("t") == {"subject": "s"}
    assert store.take_upload("t") is None


def test_an_expired_ticket_redeems_nothing(store):
    store.put_upload("t", {"subject": "s"}, expires_at=time.time() - 1)
    assert store.take_upload("t") is None


# --- the route ---------------------------------------------------------------


def test_the_bytes_stored_are_the_bytes_sent(store, odoo):
    service = Uploads(store, BASE)
    response = client_for(service).post(issue(service), content=PNG)

    assert response.status_code == 201
    body = response.json()
    # The check a caller makes: Odoo's checksum against `sha1sum` of the file.
    assert body["checksum"] == hashlib.sha1(PNG).hexdigest()  # noqa: S324
    assert body["file_size"] == len(PNG)
    assert (body["res_model"], body["res_id"]) == ("project.task", 42)

    values = odoo.created[0]
    assert base64.b64decode(values["datas"]) == PNG
    assert (values["name"], values["res_model"], values["res_id"]) == ("before.png", "project.task", 42)
    assert "mimetype" not in values  # left to Odoo when the caller gave none


def test_odoo_is_told_not_to_shrink_the_image(store, odoo):
    # Odoo re-encodes PNG/JPEG over 1920 px at quality 80 unless told not to,
    # and the checksum would then no longer match the file on disk.
    service = Uploads(store, BASE)
    client_for(service).post(issue(service), content=PNG)
    create = next(c for c in odoo.calls if c[1] == "create")
    assert create[3] == {"context": {"image_no_postprocess": True}}


def test_the_file_is_stored_as_the_person_the_link_was_issued_to(store, odoo):
    service = Uploads(store, BASE)
    client_for(service).post(issue(service, identity="someone@example.test"), content=PNG)
    # The request itself carries no token: the identity comes from the ticket.
    assert odoo.seen == ["someone@example.test"]


def test_a_given_mimetype_is_passed_on(store, odoo):
    service = Uploads(store, BASE)
    client_for(service).post(issue(service, name="run.py", mimetype="text/x-python"), content=b"print()")
    assert odoo.created[0]["mimetype"] == "text/x-python"


def test_a_link_works_once(store, odoo):
    service = Uploads(store, BASE)
    client = client_for(service)
    path = issue(service)
    assert client.post(path, content=PNG).status_code == 201
    assert client.post(path, content=PNG).status_code == 404
    assert len(odoo.created) == 1


def test_a_failed_upload_burns_the_link_too(store, odoo):
    service = Uploads(store, BASE, max_bytes=10)
    client = client_for(service)
    path = issue(service)
    assert client.post(path, content=PNG).status_code == 413
    assert client.post(path, content=b"small").status_code == 404


def test_an_unknown_link_stores_nothing(store, odoo):
    response = client_for(Uploads(store, BASE)).post(f"{UPLOAD_PATH}/made-up", content=PNG)
    assert response.status_code == 404
    assert odoo.created == []


def test_an_expired_link_stores_nothing(store, odoo):
    service = Uploads(store, BASE, ttl_seconds=-1)
    assert client_for(service).post(issue(service), content=PNG).status_code == 404
    assert odoo.created == []


def test_too_large_is_refused_before_odoo_hears_of_it(store, odoo):
    service = Uploads(store, BASE, max_bytes=len(PNG) - 1)
    response = client_for(service).post(issue(service), content=PNG)
    assert response.status_code == 413
    assert odoo.created == []


def test_too_large_is_refused_without_a_content_length(store, odoo):
    # A chunked body declares no length; the cap has to hold while reading.
    service = Uploads(store, BASE, max_bytes=len(PNG) - 1)

    def chunks():
        yield PNG[:100]
        yield PNG[100:]

    response = client_for(service).post(issue(service), content=chunks())
    assert response.status_code == 413
    assert odoo.created == []


def test_exactly_the_limit_is_accepted(store, odoo):
    service = Uploads(store, BASE, max_bytes=len(PNG))
    assert client_for(service).post(issue(service), content=PNG).status_code == 201


def test_an_empty_body_is_refused(store, odoo):
    service = Uploads(store, BASE)
    response = client_for(service).post(issue(service), content=b"")
    assert response.status_code == 400
    assert "--data-binary" in response.json()["error"]
    assert odoo.created == []


def test_an_access_error_from_odoo_is_a_403_with_its_message(store, odoo):
    odoo.deny = "create"
    service = Uploads(store, BASE)
    response = client_for(service).post(issue(service), content=PNG)
    assert response.status_code == 403
    assert "not allowed" in response.json()["error"]


def test_no_stored_credential_is_a_401(store, monkeypatch):
    class SignedOut(FakeManager):
        def execute_kw(self, *args, **kwargs):
            msg = "Not connected to Odoo."
            raise ConnectionError(msg)

    monkeypatch.setattr(registry, "get", lambda identity: SignedOut())
    service = Uploads(store, BASE)
    assert client_for(service).post(issue(service), content=PNG).status_code == 401


# --- the tool ----------------------------------------------------------------


@pytest.fixture
def service(store, monkeypatch):
    service = Uploads(store, BASE)
    monkeypatch.setattr(uploads_module, "_uploads", service)
    return service


def test_the_tool_returns_a_link_and_the_command_to_use_it(service, odoo):
    result = asyncio.run(begin_upload("project.task", 42, "before.png"))
    assert result["upload_url"].startswith(f"{BASE}{UPLOAD_PATH}/")
    assert result["command"] == f"curl -sS --fail-with-body --data-binary @FILE '{result['upload_url']}'"
    assert result["record"] == "Fix the scrap report"
    assert result["expires_in"] == service.ttl_seconds
    assert result["max_bytes"] == service.max_bytes


def test_the_link_from_the_tool_uploads(service, odoo):
    result = asyncio.run(begin_upload("project.task", 42, "before.png"))
    response = client_for(service).post(result["upload_url"].removeprefix(BASE), content=PNG)
    assert response.status_code == 201


def test_the_tool_asks_odoo_the_question_create_will_ask(service, odoo):
    asyncio.run(begin_upload("project.task", 42, "before.png"))
    assert ("ir.attachment", "check", ["create"],
            {"values": {"res_model": "project.task", "res_id": 42}}) in odoo.calls


def test_no_link_for_a_record_that_does_not_exist(service, odoo, store):
    with pytest.raises(ValueError, match="does not exist"):
        asyncio.run(begin_upload("project.task", 999, "before.png"))


def test_no_link_for_a_record_the_caller_may_not_change(service, odoo):
    odoo.deny = "check"
    with pytest.raises(odoorpc.error.RPCError):
        asyncio.run(begin_upload("project.task", 42, "before.png"))


def test_the_tool_refuses_when_uploads_are_off(monkeypatch, odoo):
    monkeypatch.setattr(uploads_module, "_uploads", None)
    with pytest.raises(RuntimeError, match="not enabled"):
        asyncio.run(begin_upload("project.task", 42, "before.png"))
