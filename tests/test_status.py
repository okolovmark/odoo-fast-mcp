"""The front page and /healthz say whether the connector can reach Odoo."""

import asyncio

import httpx
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from odoo_fast_mcp.status import OdooProbe, StatusPage

ODOO = "https://odoo.example.test"
MCP_URL = "https://mcp.example.test/mcp"


class FakeOdoo:
    """Answers /web/health with a fixed status, or fails to connect; counts calls."""

    def __init__(self, status=200, fail=False):
        self.status = status
        self.fail = fail
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert request.url.path == "/web/health"
        if self.fail:
            msg = "refused"
            raise httpx.ConnectError(msg, request=request)
        return httpx.Response(self.status, json={"status": "pass"})


def _client(odoo: FakeOdoo, ttl: float = 30.0) -> TestClient:
    probe = OdooProbe(ODOO, ttl=ttl, transport=httpx.MockTransport(odoo))
    status = StatusPage(probe, ODOO, MCP_URL)
    app = Starlette(routes=[
        Route("/", status.page, methods=["GET"]),
        Route("/healthz", status.healthz, methods=["GET"]),
    ])
    return TestClient(app)


def test_healthz_is_ok_when_odoo_answers():
    response = _client(FakeOdoo()).get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["odoo"]["reachable"] is True
    assert "detail" not in body["odoo"]


def test_healthz_is_503_when_odoo_errors():
    response = _client(FakeOdoo(status=502)).get("/healthz")
    assert response.status_code == 503
    assert response.json()["odoo"] == {**response.json()["odoo"], "reachable": False, "detail": "HTTP 502"}


def test_healthz_is_503_when_odoo_cannot_be_reached():
    response = _client(FakeOdoo(fail=True)).get("/healthz")
    assert response.status_code == 503
    assert response.json()["odoo"]["detail"] == "ConnectError"


def test_page_shows_both_states_and_how_to_connect():
    up = _client(FakeOdoo()).get("/")
    assert up.status_code == 200
    assert "odoo.example.test: reachable" in up.text
    assert MCP_URL in up.text
    assert "dot bad" not in up.text

    down = _client(FakeOdoo(fail=True)).get("/").text
    assert "odoo.example.test: not reachable (ConnectError)" in down
    assert "dot bad" in down


def test_odoo_is_probed_once_per_ttl_however_many_ask():
    odoo = FakeOdoo()
    client = _client(odoo)
    for path in ("/", "/healthz", "/", "/healthz"):
        client.get(path)
    assert odoo.calls == 1


def test_concurrent_callers_share_one_probe():
    odoo = FakeOdoo()
    probe = OdooProbe(ODOO, transport=httpx.MockTransport(odoo))

    async def many():
        return await asyncio.gather(*(probe.check() for _ in range(20)))

    results = asyncio.run(many())
    assert odoo.calls == 1
    assert len({id(r) for r in results}) == 1


def test_an_expired_result_is_probed_again():
    odoo = FakeOdoo()
    client = _client(odoo, ttl=0)
    client.get("/healthz")
    client.get("/healthz")
    assert odoo.calls == 2
