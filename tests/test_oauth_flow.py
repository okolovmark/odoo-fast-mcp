"""The whole sign-in path, against a real Odoo.

Unit tests cannot catch what this catches. The bug that prompted it — FastMCP
converting an SDK access token and dropping `subject` on the way, so every
caller resolved to their client id and reached Odoo as nobody — passed every
isolated test and only showed up as ``connected: false`` at the far end of the
flow.

The upload tests live here for the same reason: only a live Odoo shows how its
RPC binds arguments (the unit tests passed a `check` call Odoo rejected) and
what `ir.attachment.create` does to an image's bytes.

Runs only when pointed at an Odoo instance:

    ODOO_TEST_URL=http://localhost:8069 ODOO_TEST_DB=mydb \\
    ODOO_TEST_USER=admin ODOO_TEST_SECRET=admin pytest tests/test_oauth_flow.py
"""

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import sys
import time
import zlib
from urllib.parse import parse_qs, urlparse

import pytest

httpx = pytest.importorskip("httpx")

ODOO_URL = os.getenv("ODOO_TEST_URL")
ODOO_DB = os.getenv("ODOO_TEST_DB")
ODOO_USER = os.getenv("ODOO_TEST_USER")
ODOO_SECRET = os.getenv("ODOO_TEST_SECRET")

pytestmark = pytest.mark.skipif(
    not all([ODOO_URL, ODOO_DB, ODOO_USER, ODOO_SECRET]),
    reason="set ODOO_TEST_URL / _DB / _USER / _SECRET to run the OAuth flow against Odoo",
)

REDIRECT = "http://localhost:9999/callback"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """A server of our own, authenticating against the configured Odoo."""
    from cryptography.fernet import Fernet

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "MCP_AUTH": "odoo",
        "MCP_BASE_URL": base,
        "MCP_CREDENTIAL_KEY": Fernet.generate_key().decode(),
        "MCP_STATE_DB": str(tmp_path_factory.mktemp("state") / "state.db"),
        "ODOO_URL": ODOO_URL,
        "ODOO_DATABASE": ODOO_DB,
    }
    env.pop("ODOO_USERNAME", None)
    env.pop("ODOO_PASSWORD", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "odoo_fast_mcp.server", "--transport", "http",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"server exited early:\n{process.stdout.read()}")
        try:
            httpx.get(f"{base}/.well-known/oauth-authorization-server", timeout=2)
            break
        except httpx.HTTPError:
            time.sleep(0.3)
    else:
        process.kill()
        pytest.fail("server did not come up")

    yield base
    process.terminate()
    process.wait(timeout=15)


@pytest.fixture
def client():
    with httpx.Client(follow_redirects=False, timeout=30) as c:
        yield c


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest(),
    ).decode().rstrip("=")
    return verifier, challenge


def _register(client, server) -> str:
    response = client.post(f"{server}/register", json={
        "client_name": "test", "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none",
    })
    assert response.status_code in (200, 201), response.text
    return response.json()["client_id"]


def _sign_in(client, server, client_id, challenge, secret=ODOO_SECRET):
    """Walk authorize -> sign-in page -> redirect, returning the final response."""
    authorize = client.get(f"{server}/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
    })
    handle = parse_qs(urlparse(authorize.headers["location"]).query)["session"][0]
    return client.post(f"{server}/login", data={
        "session": handle, "username": ODOO_USER, "secret": secret,
    })


def test_unauthenticated_calls_are_refused(client, server):
    response = client.post(f"{server}/mcp", headers={"Accept": "application/json"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}})
    assert response.status_code == 401


def test_the_wrong_secret_never_reaches_a_code(client, server):
    client_id = _register(client, server)
    _, challenge = _pkce()
    response = _sign_in(client, server, client_id, challenge, secret="definitely-wrong")
    assert response.status_code == 401
    assert "code=" not in response.headers.get("location", "")


def test_a_signed_in_caller_reaches_odoo_as_themselves(client, server):
    client_id = _register(client, server)
    verifier, challenge = _pkce()

    redirect = _sign_in(client, server, client_id, challenge)
    assert redirect.status_code == 302
    query = parse_qs(urlparse(redirect.headers["location"]).query)
    assert query["state"] == ["xyz"]

    token = client.post(f"{server}/token", data={
        "grant_type": "authorization_code", "code": query["code"][0],
        "client_id": client_id, "redirect_uri": REDIRECT, "code_verifier": verifier,
    })
    assert token.status_code == 200, token.text
    access = token.json()["access_token"]

    headers = {
        "Authorization": f"Bearer {access}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    init = client.post(f"{server}/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}})
    assert init.status_code == 200
    headers["mcp-session-id"] = init.headers["mcp-session-id"]
    client.post(f"{server}/mcp", headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    status = client.post(f"{server}/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_connection_status", "arguments": {}}})
    # The identity has to survive from the token all the way into a live Odoo
    # session; anything less and the tool answers "connected: false".
    assert '\\"connected\\":true' in status.text or '"connected": true' in status.text, status.text


def test_a_code_works_once(client, server):
    client_id = _register(client, server)
    verifier, challenge = _pkce()
    redirect = _sign_in(client, server, client_id, challenge)
    code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
    body = {"grant_type": "authorization_code", "code": code, "client_id": client_id,
            "redirect_uri": REDIRECT, "code_verifier": verifier}

    assert client.post(f"{server}/token", data=body).status_code == 200
    replay = client.post(f"{server}/token", data=body)
    assert replay.status_code in (400, 401)
    assert "access_token" not in replay.text


def test_the_wrong_verifier_is_refused(client, server):
    client_id = _register(client, server)
    _, challenge = _pkce()
    redirect = _sign_in(client, server, client_id, challenge)
    code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]

    response = client.post(f"{server}/token", data={
        "grant_type": "authorization_code", "code": code, "client_id": client_id,
        "redirect_uri": REDIRECT, "code_verifier": secrets.token_urlsafe(48),
    })
    assert response.status_code in (400, 401)
    assert "access_token" not in response.text


def _mcp_session(client, server) -> dict[str, str]:
    """Sign in and open an MCP session; returns the headers that carry it."""
    client_id = _register(client, server)
    verifier, challenge = _pkce()
    redirect = _sign_in(client, server, client_id, challenge)
    code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
    token = client.post(f"{server}/token", data={
        "grant_type": "authorization_code", "code": code, "client_id": client_id,
        "redirect_uri": REDIRECT, "code_verifier": verifier,
    })
    headers = {
        "Authorization": f"Bearer {token.json()['access_token']}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    init = client.post(f"{server}/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}})
    headers["mcp-session-id"] = init.headers["mcp-session-id"]
    client.post(f"{server}/mcp", headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return headers


def _call(client, server, headers, name, arguments):
    """One tools/call; returns the tool's structured result."""
    response = client.post(f"{server}/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": name, "arguments": arguments}})
    data = next(line[5:] for line in response.text.splitlines() if line.startswith("data:"))
    result = json.loads(data)["result"]
    assert not result.get("isError"), result
    structured = result["structuredContent"]
    return structured.get("result", structured)


def test_a_file_uploads_through_a_link_byte_for_byte(client, server):
    headers = _mcp_session(client, server)
    partner = _call(client, server, headers, "search", {"model": "res.partner", "limit": 1})[0]
    # Larger than 1920 px would be re-encoded by Odoo unless told not to; a
    # plain byte string is enough to prove the bytes arrive unchanged.
    payload = secrets.token_bytes(64 * 1024)

    link = _call(client, server, headers, "begin_upload", {
        "model": "res.partner", "res_id": partner, "filename": "upload-test.bin",
        "mimetype": "application/octet-stream",
    })
    uploaded = client.post(link["upload_url"], content=payload)
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    try:
        assert attachment["checksum"] == hashlib.sha1(payload).hexdigest()  # noqa: S324
        assert attachment["file_size"] == len(payload)
        stored = _call(client, server, headers, "read", {
            "model": "ir.attachment", "ids": json.dumps([attachment["id"]]),
            "fields": '["res_model", "res_id", "create_uid"]', "with_url": False,
        })[0]
        assert (stored["res_model"], stored["res_id"]) == ("res.partner", partner)

        assert client.post(link["upload_url"], content=payload).status_code == 404
    finally:
        _call(client, server, headers, "unlink", {
            "model": "ir.attachment", "ids": json.dumps([attachment["id"]]),
        })


def _wide_png(width: int = 2400, height: int = 16) -> bytes:
    """A PNG wider than Odoo's 1920 px resize threshold, built without Pillow."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + secrets.token_bytes(width * 3) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def test_a_wide_screenshot_is_stored_unshrunk(client, server):
    # Odoo re-encodes PNG/JPEG over 1920 px on create unless the context says
    # not to; this proves the context reaches it over RPC.
    headers = _mcp_session(client, server)
    partner = _call(client, server, headers, "search", {"model": "res.partner", "limit": 1})[0]
    png = _wide_png()
    link = _call(client, server, headers, "begin_upload", {
        "model": "res.partner", "res_id": partner, "filename": "wide.png",
    })
    uploaded = client.post(link["upload_url"], content=png)
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    try:
        assert attachment["mimetype"] == "image/png"
        assert attachment["checksum"] == hashlib.sha1(png).hexdigest()  # noqa: S324
    finally:
        _call(client, server, headers, "unlink", {
            "model": "ir.attachment", "ids": json.dumps([attachment["id"]]),
        })
