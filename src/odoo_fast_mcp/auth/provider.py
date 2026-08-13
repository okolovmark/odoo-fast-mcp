"""An authorization server whose source of truth is Odoo itself.

MCP clients such as Claude authenticate through OAuth, which needs something to
decide who a person is. Rather than bolt on a second identity system, this
provider asks the question Odoo can already answer: sign in with your Odoo login
and an API key, and the identity you get is the Odoo user you signed in as.
Authorisation is then whatever Odoo grants that user — there is no second set of
permissions to keep in step.

FastMCP's :class:`OAuthProvider` serves the endpoints and the discovery metadata,
and the MCP SDK's token handler enforces PKCE, redirect-URI matching and code
expiry. What lives here is the part that is genuinely ours: storage, issuance,
and the sign-in page.
"""

import logging
import time
from dataclasses import dataclass
from html import escape
from typing import Any

# FastMCP's AccessToken subclasses the SDK's. The distinction matters: when a
# request carries the SDK type, FastMCP converts it and the conversion drops
# `subject` — the field this server keys its Odoo connections on. Issue the
# FastMCP type and the identity survives the round trip.
from fastmcp.server.auth.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from odoo_fast_mcp.auth.credentials import (
    CredentialError,
    CredentialStore,
    OdooCredentials,
    verify_credentials,
)
from odoo_fast_mcp.auth.store import OAuthStore, new_secret

logger = logging.getLogger(__name__)

LOGIN_PATH = "/login"
LOGIN_TTL_SECONDS = 10 * 60
CODE_TTL_SECONDS = 5 * 60
ACCESS_TOKEN_TTL_SECONDS = 60 * 60
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class OdooTarget:
    """Which Odoo the sign-in page authenticates against.

    Fixed by the operator rather than typed by the person signing in: a login
    form that accepts an arbitrary host is a phishing tool, and the server can
    only reach one Odoo anyway.
    """

    host: str
    database: str
    port: int = 8069
    protocol: str = "jsonrpc"

    def credentials(self, username: str, secret: str) -> OdooCredentials:
        return OdooCredentials(
            host=self.host,
            database=self.database,
            username=username,
            secret=secret,
            port=self.port,
            protocol=self.protocol,
        )


class OdooAuthProvider(OAuthProvider):
    """OAuth for MCP clients, with Odoo as the identity provider."""

    def __init__(
        self,
        *,
        base_url: str,
        target: OdooTarget,
        oauth_store: OAuthStore,
        credential_store: CredentialStore,
        required_scopes: list[str] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            # Claude registers itself on first connect; without this an operator
            # would have to mint a client by hand for every MCP client added.
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=required_scopes,
        )
        self._target = target
        self._oauth = oauth_store
        self._credentials = credential_store

    # -- clients -----------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self._oauth.get_client(client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._oauth.put_client(client_info.client_id, client_info.model_dump(mode="json"))
        logger.info("Registered OAuth client %s", client_info.client_id)

    # -- authorization -----------------------------------------------------

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Park the request and send the person to the sign-in page.

        The authorization request is kept server-side and referenced by an
        unguessable handle, so nothing about the pending grant travels through
        the browser where it could be tampered with on the way back.
        """
        handle = new_secret()
        self._oauth.put_login(
            handle,
            {
                "client_id": client.client_id,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "code_challenge": params.code_challenge,
                "state": params.state,
                "scopes": params.scopes or [],
                "resource": params.resource,
            },
            expires_at=time.time() + LOGIN_TTL_SECONDS,
        )
        return f"{str(self.base_url).rstrip('/')}{LOGIN_PATH}?session={handle}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        data = self._oauth.take_code(authorization_code)
        if data is None or data.get("client_id") != client.client_id:
            return None
        return AuthorizationCode.model_validate(data)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        return self._issue_tokens(
            client_id=client.client_id,
            subject=authorization_code.subject or "",
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
        )

    # -- tokens ------------------------------------------------------------

    def _issue_tokens(
        self,
        *,
        client_id: str,
        subject: str,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken:
        access, refresh = new_secret(), new_secret()
        now = time.time()
        access_expires = now + ACCESS_TOKEN_TTL_SECONDS

        self._oauth.put_token(
            access,
            kind="access",
            subject=subject,
            client_id=client_id,
            data={
                "token": access,
                "client_id": client_id,
                "scopes": scopes,
                "expires_at": int(access_expires),
                "resource": resource,
                "subject": subject,
            },
            expires_at=access_expires,
        )
        refresh_expires = now + REFRESH_TOKEN_TTL_SECONDS
        self._oauth.put_token(
            refresh,
            kind="refresh",
            subject=subject,
            client_id=client_id,
            data={
                "token": refresh,
                "client_id": client_id,
                "scopes": scopes,
                "expires_at": int(refresh_expires),
                "subject": subject,
            },
            expires_at=refresh_expires,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = self._oauth.get_token(token, kind="access")
        return AccessToken.model_validate(data) if data else None

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        data = self._oauth.get_token(refresh_token, kind="refresh")
        if data is None or data.get("client_id") != client.client_id:
            return None
        return RefreshToken.model_validate(data)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # One use per refresh token: a replayed one finds nothing, which turns a
        # stolen token into a detectable failure rather than a quiet second session.
        self._oauth.drop_token(refresh_token.token)
        return self._issue_tokens(
            client_id=client.client_id,
            subject=refresh_token.subject or "",
            scopes=scopes or refresh_token.scopes,
            resource=None,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._oauth.drop_token(token.token)

    # -- the sign-in page --------------------------------------------------

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        return [
            *super().get_routes(mcp_path),
            Route(LOGIN_PATH, self._login_form, methods=["GET"]),
            Route(LOGIN_PATH, self._login_submit, methods=["POST"]),
        ]

    async def _login_form(self, request: Request) -> Response:
        handle = request.query_params.get("session", "")
        if not handle or self._oauth.get_login(handle) is None:
            return HTMLResponse(_page(_EXPIRED), status_code=400)
        return HTMLResponse(_page(self._form_body(handle)))

    async def _login_submit(self, request: Request) -> Response:
        form = await request.form()
        handle = str(form.get("session", ""))
        username = str(form.get("username", "")).strip()
        secret = str(form.get("secret", ""))

        pending = self._oauth.get_login(handle) if handle else None
        if pending is None:
            return HTMLResponse(_page(_EXPIRED), status_code=400)
        if not username or not secret:
            return HTMLResponse(
                _page(self._form_body(handle, error="Enter your login and API key.")),
                status_code=400,
            )

        credentials = self._target.credentials(username, secret)
        try:
            user = verify_credentials(credentials)
        except CredentialError as exc:
            # Odoo's own wording ("Wrong login ID or password") is the honest
            # message here; anything vaguer sends people hunting the wrong problem.
            logger.info("Rejected sign-in for %s: %s", username, exc)
            return HTMLResponse(
                _page(self._form_body(handle, error=str(exc))),
                status_code=401,
            )

        subject = username
        self._credentials.put(subject, credentials)
        self._oauth.drop_login(handle)

        code = new_secret()
        self._oauth.put_code(
            code,
            {
                "code": code,
                "client_id": pending["client_id"],
                "redirect_uri": pending["redirect_uri"],
                "redirect_uri_provided_explicitly": pending["redirect_uri_provided_explicitly"],
                "code_challenge": pending["code_challenge"],
                "scopes": pending["scopes"],
                "resource": pending["resource"],
                "expires_at": int(time.time() + CODE_TTL_SECONDS),
                "subject": subject,
            },
            expires_at=time.time() + CODE_TTL_SECONDS,
        )
        logger.info("Signed in %s as Odoo uid %s", subject, user["uid"])

        return RedirectResponse(
            construct_redirect_uri(pending["redirect_uri"], code=code, state=pending["state"]),
            status_code=302,
        )

    def _form_body(self, handle: str, error: str | None = None) -> str:
        banner = f'<p class="error">{escape(error)}</p>' if error else ""
        return f"""
        <h1>Sign in to Odoo</h1>
        <p class="target">{escape(self._target.database)} at {escape(self._target.host)}</p>
        {banner}
        <form method="post" action="{LOGIN_PATH}">
          <input type="hidden" name="session" value="{escape(handle)}">
          <label for="username">Odoo login</label>
          <input id="username" name="username" type="email" autocomplete="username" required
                 autofocus>
          <label for="secret">API key</label>
          <input id="secret" name="secret" type="password" autocomplete="current-password"
                 required>
          <button type="submit">Sign in</button>
        </form>
        <p class="hint">
          Create an API key in Odoo under Preferences &rarr; Account Security.
          Your key is stored encrypted and can be revoked there at any time.
        </p>
        """

    # -- bridge to the connection registry ---------------------------------

    def credential_provider(self, identity: str) -> dict[str, Any] | None:
        """Connect arguments for an identity, or None if it has not signed in."""
        credentials = self._credentials.get(identity)
        return credentials.to_connect_kwargs() if credentials else None


_EXPIRED = """
<h1>This sign-in link has expired</h1>
<p class="hint">Close this page and connect again from your MCP client.</p>
"""

_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; max-width: 22rem; margin: 4rem auto; padding: 0 1rem;
       line-height: 1.5; }
h1 { font-size: 1.25rem; margin-bottom: .25rem; }
.target { color: #666; margin-top: 0; font-size: .9rem; }
label { display: block; margin-top: 1rem; font-size: .9rem; }
input { width: 100%; padding: .5rem; margin-top: .25rem; box-sizing: border-box;
        border: 1px solid #999; border-radius: .25rem; }
button { margin-top: 1.5rem; width: 100%; padding: .6rem; border: 0; border-radius: .25rem;
         background: #714b67; color: #fff; font-size: 1rem; cursor: pointer; }
.error { background: #fde8e8; border-left: 3px solid #c81e1e; padding: .5rem .75rem;
         color: #9b1c1c; font-size: .9rem; }
.hint { color: #666; font-size: .85rem; margin-top: 1.5rem; }
"""


def _page(body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Sign in to Odoo</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
