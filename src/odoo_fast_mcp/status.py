"""A public front page and a health check for the HTTP transport.

Both answer the one question people ask when a client says the server is not
responding: is the connector up, and can it reach Odoo. Neither needs a sign-in,
so neither shows anything about callers or the process beyond that.
"""

import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

PROJECT_URL = "https://github.com/okolovmark/odoo-fast-mcp"
STARTED_AT = datetime.now(timezone.utc)

PROBE_TTL = 30.0
PROBE_TIMEOUT = 5.0


@dataclass(frozen=True)
class ProbeResult:
    reachable: bool
    latency_ms: int
    checked_at: datetime
    detail: str | None = None


class OdooProbe:
    """Asks Odoo's ``/web/health``, at most once per ``ttl`` however many ask.

    The page is public. Without the cache every hit on it would be a request to
    Odoo; with it, concurrent callers wait for the one probe in flight.
    """

    def __init__(
        self,
        odoo_url: str,
        ttl: float = PROBE_TTL,
        timeout: float = PROBE_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = f"{odoo_url.rstrip('/')}/web/health"
        self._ttl = ttl
        self._timeout = timeout
        self._transport = transport
        self._lock = anyio.Lock()
        self._result: ProbeResult | None = None
        self._probed_at = -math.inf

    async def check(self) -> ProbeResult:
        async with self._lock:
            if self._result is None or time.monotonic() - self._probed_at >= self._ttl:
                self._result = await self._probe()
                self._probed_at = time.monotonic()
            return self._result

    async def _probe(self) -> ProbeResult:
        started = time.monotonic()
        detail = None
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport,
            ) as client:
                response = await client.get(self.url)
            reachable = response.status_code == 200
            if not reachable:
                detail = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            reachable = False
            detail = type(exc).__name__
        return ProbeResult(
            reachable=reachable,
            latency_ms=round((time.monotonic() - started) * 1000),
            checked_at=datetime.now(timezone.utc),
            detail=detail,
        )


def build_ref() -> str:
    """The deployed commit, as the connector's install.sh records it, else the version."""
    try:
        return (Path(sys.prefix) / ".installed-ref").read_text().strip()[:7]
    except OSError:
        pass
    try:
        return version("odoo-fast-mcp")
    except PackageNotFoundError:
        return "unknown"


class StatusPage:
    def __init__(self, probe: OdooProbe, odoo_url: str, mcp_url: str) -> None:
        self._probe = probe
        self._odoo_host = urlsplit(odoo_url).hostname or odoo_url
        self._mcp_url = mcp_url

    async def healthz(self, request: Request) -> Response:
        """200 when Odoo answers, 503 when it does not: the connector is useless without it."""
        result = await self._probe.check()
        body: dict[str, Any] = {
            "status": "ok" if result.reachable else "degraded",
            "started_at": STARTED_AT.isoformat(timespec="seconds"),
            "build": build_ref(),
            "odoo": {
                "reachable": result.reachable,
                "latency_ms": result.latency_ms,
                "checked_at": result.checked_at.isoformat(timespec="seconds"),
            },
        }
        if result.detail:
            body["odoo"]["detail"] = result.detail
        return JSONResponse(body, status_code=200 if result.reachable else 503)

    async def page(self, request: Request) -> Response:
        result = await self._probe.check()
        mcp_url = self._mcp_url or f"{str(request.base_url).rstrip('/')}/mcp"
        if result.reachable:
            odoo = f"reachable, {result.latency_ms} ms"
        else:
            odoo = "not reachable" + (f" ({result.detail})" if result.detail else "")
        build = build_ref()
        build_html = f"<code>{escape(build)}</code>"
        if len(build) == 7 and all(c in "0123456789abcdef" for c in build):
            build_html = f"<a href='{PROJECT_URL}/commit/{build}'>{build_html}</a>"
        body = f"""
        <h1>Odoo MCP connector</h1>
        <p class="lead">Lets Claude and other MCP clients work in Odoo, each person
        signed in as their own Odoo user.</p>
        <dl>
          <dt><span class="dot ok"></span>Connector</dt>
          <dd>up since {_when(STARTED_AT)}</dd>
          <dt><span class="dot {'ok' if result.reachable else 'bad'}"></span>Odoo</dt>
          <dd>{escape(self._odoo_host)}: {escape(odoo)}</dd>
          <dt><span class="dot none"></span>Build</dt>
          <dd>{build_html}</dd>
        </dl>
        <h2>Connect</h2>
        <p>Add it to your MCP client as a remote server with this URL
        (in claude.ai: Settings &rarr; Connectors):</p>
        <p class="url"><code>{escape(mcp_url)}</code></p>
        <p class="hint">Odoo checked at {result.checked_at:%H:%M:%S} UTC.
        This page refreshes every {int(PROBE_TTL)} s.
        For monitors: <a href="/healthz">/healthz</a>.</p>
        """
        return HTMLResponse(_page(body), status_code=200)


def enable_status(mcp: FastMCP, odoo_url: str, mcp_url: str = "") -> StatusPage:
    """Serve the front page at ``/`` and the health check at ``/healthz``."""
    status = StatusPage(OdooProbe(odoo_url), odoo_url, mcp_url)
    mcp.custom_route("/", methods=["GET"])(status.page)
    mcp.custom_route("/healthz", methods=["GET"])(status.healthz)
    return status


def _when(moment: datetime) -> str:
    return f"{moment:%d %b %Y, %H:%M} UTC"


# Inline only: the connector's nginx sends `default-src 'none'; style-src
# 'unsafe-inline'`, which blocks scripts, images and external stylesheets.
_STYLE = """
:root { color-scheme: light dark; --muted: #666; --ok: #16a34a; --bad: #dc2626; }
@media (prefers-color-scheme: dark) { :root { --muted: #9a9a9a; } }
body { font-family: system-ui, sans-serif; max-width: 32rem; margin: 4rem auto;
       padding: 0 1rem; line-height: 1.5; }
h1 { font-size: 1.35rem; margin-bottom: .25rem; }
h2 { font-size: 1rem; margin-top: 2rem; }
.lead { color: var(--muted); margin-top: 0; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .4rem 1.25rem;
     margin: 1.5rem 0; }
dt { font-weight: 600; }
dd { margin: 0; overflow-wrap: anywhere; }
.dot { display: inline-block; width: .6rem; height: .6rem; border-radius: 50%;
       margin-right: .5rem; vertical-align: .05rem; }
.dot.ok { background: var(--ok); }
.dot.bad { background: var(--bad); }
.dot.none { background: transparent; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .9em; }
.url code { overflow-wrap: anywhere; }
a { color: inherit; }
.hint { color: var(--muted); font-size: .85rem; margin-top: 2rem; }
"""


def _page(body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<meta http-equiv='refresh' content='{int(PROBE_TTL)}'>"
        f"<title>Odoo MCP connector</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
