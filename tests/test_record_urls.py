"""Records come back with a link a person can open.

The agent reads the fields; the person who asked reads the record in Odoo.
Handing them ``_url`` beats asking them to trust a paraphrase — and the URL is
built from the connection, so it is right for whichever database is in use.
"""

import asyncio
import json

import pytest

import odoo_fast_mcp.tools.crud as crud
from odoo_fast_mcp.config import web_base_url
from odoo_fast_mcp.connection import OdooConnectionManager

WEB = "https://odoo.example.test"


@pytest.mark.parametrize(
    ("host", "port", "protocol", "expected"),
    [
        ("odoo.example.test", 443, "jsonrpc+ssl", "https://odoo.example.test"),
        ("odoo.example.test", 8443, "jsonrpc+ssl", "https://odoo.example.test:8443"),
        ("localhost", 8069, "jsonrpc", "http://localhost:8069"),
        ("intranet", 80, "jsonrpc", "http://intranet"),
    ],
)
def test_web_base_url_is_what_a_browser_would_open(host, port, protocol, expected):
    assert web_base_url(host, port, protocol) == expected


class _FakeOdoo:
    """odoorpc.ODOO stand-in: logs in without a network."""

    version = "16.0"

    def __init__(self, host, protocol, port):
        self.config = {}
        self.env = type("Env", (), {"uid": 7})()

    def login(self, database, username, password):
        pass

    def execute(self, model, method, *args):
        return [{"name": "Someone"}]


def test_manager_learns_its_web_url_on_login(monkeypatch):
    monkeypatch.setattr("odoo_fast_mcp.connection.odoorpc.ODOO", _FakeOdoo)
    manager = OdooConnectionManager()
    with pytest.raises(ConnectionError):
        _ = manager.web_url

    result = manager.connect("odoo.example.test", 443, "jsonrpc+ssl", "db", "u", "p")
    assert manager.web_url == WEB
    assert result["web_url"] == WEB

    manager.disconnect()
    with pytest.raises(ConnectionError):
        _ = manager.web_url


class _FakeManager:
    web_url = WEB

    def search_read(self, model, domain, fields, offset, limit, order):
        return [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]

    def read(self, model, ids, fields):
        return [{"id": i, "name": f"R{i}"} for i in ids]

    def create(self, model, values):
        return 42


@pytest.fixture
def fake_manager(monkeypatch):
    fake = _FakeManager()
    monkeypatch.setattr(crud, "odoo_manager", fake)
    return fake


def test_search_read_links_every_record(fake_manager):
    records = asyncio.run(crud.search_read(model="res.partner"))
    assert [r["_url"] for r in records] == [
        f"{WEB}/web#id=1&model=res.partner&view_type=form",
        f"{WEB}/web#id=2&model=res.partner&view_type=form",
    ]


def test_bulk_pulls_can_leave_the_links_out(fake_manager):
    records = asyncio.run(crud.search_read(model="res.partner", with_url=False))
    assert records and all("_url" not in r for r in records)


def test_read_links_every_record(fake_manager):
    records = asyncio.run(crud.read(model="sale.order", ids="[5]"))
    assert records[0]["_url"] == f"{WEB}/web#id=5&model=sale.order&view_type=form"


def test_create_answers_with_the_new_record_and_its_link(fake_manager):
    result = asyncio.run(crud.create(model="res.partner", values=json.dumps({"name": "N"})))
    assert result == {"id": 42, "_url": f"{WEB}/web#id=42&model=res.partner&view_type=form"}
