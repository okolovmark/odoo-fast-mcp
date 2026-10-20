"""Files into Odoo without passing them through the model.

A tool call carries JSON, so through the other tools the only way a file reaches
Odoo is base64 that the model types out in the call: hundreds of thousands of
characters for one screenshot, each a chance to corrupt it, all of it paid for
in context. Here the model asks for an upload link instead, and the shell it
runs in sends the bytes straight to this server, which stores them in Odoo as
the person who asked.

Offered only when callers sign in. The link is bound to that person's stored
credential, which is what lets a request carrying no token act as them; over
stdio there is no HTTP server to send a file to.
"""

import base64
import logging
import time
from typing import Annotated, Any

import odoorpc
from anyio import to_thread
from fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from odoo_fast_mcp.auth.store import OAuthStore, new_secret
from odoo_fast_mcp.connection import current_identity, odoo_manager, registry

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/upload"
UPLOAD_TTL_SECONDS = 10 * 60
# Screenshots are well under 1 MB and a demo GIF runs 3-10 MB. The nginx vhost
# in front of the server allows the same on this path and 1 MB everywhere else.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class Uploads:
    """Issues one-time upload links and turns what arrives on them into attachments."""

    def __init__(
        self,
        store: OAuthStore,
        base_url: str,
        max_bytes: int = MAX_UPLOAD_BYTES,
        ttl_seconds: int = UPLOAD_TTL_SECONDS,
    ) -> None:
        self._store = store
        self._base_url = base_url.rstrip("/")
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds

    def issue(
        self,
        identity: str,
        model: str,
        res_id: int,
        name: str,
        mimetype: str | None,
    ) -> str:
        """A link that stores one file on one record as ``identity``. Returns its URL."""
        ticket = new_secret()
        self._store.put_upload(
            ticket,
            {
                "subject": identity,
                "model": model,
                "res_id": res_id,
                "name": name,
                "mimetype": mimetype,
            },
            expires_at=time.time() + self.ttl_seconds,
        )
        return f"{self._base_url}{UPLOAD_PATH}/{ticket}"

    async def receive(self, request: Request) -> Response:
        """``POST /upload/<ticket>`` with the raw file as the body."""
        # Burnt before anything else: a link that failed half-way is not left
        # lying around to be retried by whoever reads the log line.
        ticket = self._store.take_upload(request.path_params["ticket"])
        if ticket is None:
            return _error(404, "This upload link is unknown, used or expired. Ask for a new one.")

        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            return _error(413, f"The file is larger than {self.max_bytes} bytes.")
        body = await _read_capped(request, self.max_bytes)
        if body is None:
            return _error(413, f"The file is larger than {self.max_bytes} bytes.")
        if not body:
            return _error(400, "The request had no body. Send the file with --data-binary @FILE.")

        try:
            attachment = await to_thread.run_sync(lambda: _store_in_odoo(ticket, body))
        except ConnectionError:
            # No stored credential any more: signed out, or the key was revoked.
            return _error(401, "Not signed in to Odoo. Reconnect the connector and try again.")
        except odoorpc.error.RPCError as exc:
            info = exc.info if isinstance(exc.info, dict) else {}
            name = info.get("data", {}).get("name", "")
            return _error(403 if name.endswith("AccessError") else 400, str(exc))

        logger.info(
            "Stored %s (%d bytes) on %s,%s as attachment %s for %s",
            ticket["name"], len(body), ticket["model"], ticket["res_id"],
            attachment["id"], ticket["subject"],
        )
        return JSONResponse(attachment, status_code=201)


async def _read_capped(request: Request, limit: int) -> bytes | None:
    """The request body, or None as soon as it grows past ``limit``.

    Content-Length is only a claim, and a chunked body has none: the count that
    matters is the one taken while reading.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _store_in_odoo(ticket: dict[str, Any], body: bytes) -> dict[str, Any]:
    """Create the attachment as the person the ticket was issued to."""
    manager = registry.get(ticket["subject"])
    values = {
        "name": ticket["name"],
        "datas": base64.b64encode(body).decode(),
        "res_model": ticket["model"],
        "res_id": ticket["res_id"],
    }
    if ticket["mimetype"]:
        values["mimetype"] = ticket["mimetype"]
    # Odoo shrinks PNG/JPEG over 1920 px on the way in. A screenshot is evidence:
    # the bytes on the record are the bytes that were sent, and their checksum
    # matches the file on disk.
    attachment_id = manager.execute_kw(
        "ir.attachment", "create", [values], {"context": {"image_no_postprocess": True}},
    )
    row = manager.read("ir.attachment", [attachment_id], ["name", "mimetype", "file_size", "checksum"])
    return {**row[0], "res_model": ticket["model"], "res_id": ticket["res_id"]}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


# =============================================================================
# The tool
# =============================================================================

_uploads: Uploads | None = None


async def begin_upload(
    model: Annotated[str, Field(description="Model of the record the file goes on, e.g. 'project.task'")],
    res_id: Annotated[int, Field(description="ID of that record", ge=1)],
    filename: Annotated[
        str, Field(description="Name the attachment gets in Odoo, e.g. 'KIO-1234_before.png'", min_length=1),
    ],
    mimetype: Annotated[
        str | None,
        Field(description="MIME type. Leave empty and Odoo infers it from the name and content."),
    ] = None,
) -> dict[str, Any]:
    """Get a one-time link that stores a local file on an Odoo record as an attachment.

    Use this instead of base64 `datas` in `create` on ir.attachment: run the
    returned `command` in a shell with FILE replaced by the file's path. The
    bytes go straight to this server, never through the conversation, and are
    stored exactly as sent, as the signed-in user.

    One link, one file, within `expires_in` seconds, up to `max_bytes`. The
    upload answers with the attachment's `id` and its sha1 `checksum`; compare
    it with `sha1sum FILE`. To show files in the chatter, post a note with
    `message_post` and `attachment_ids`: one note can carry several.

    Needs a shell that can reach this server. Without one, a small file can
    still go through `create` on ir.attachment with base64 `datas`.
    """
    if _uploads is None:
        msg = "Uploads are not enabled on this server."
        raise RuntimeError(msg)
    uploads = _uploads
    identity = current_identity()

    def check() -> str:
        # Asked now rather than when the file arrives, so a record that is not
        # there, or not theirs to change, costs no upload.
        rows = odoo_manager.read(model, [res_id], ["display_name"])
        if not rows:
            msg = f"{model} {res_id} does not exist."
            raise ValueError(msg)
        # The question Odoo itself asks when the attachment is created: write
        # access to the record it is attached to. An @api.model method, so no ids.
        odoo_manager.execute_kw(
            "ir.attachment", "check", ["create"],
            {"values": {"res_model": model, "res_id": res_id}},
        )
        return rows[0]["display_name"]

    record = await to_thread.run_sync(check)
    url = uploads.issue(identity, model, res_id, filename, mimetype)
    return {
        "record": record,
        "upload_url": url,
        "command": f"curl -sS --fail-with-body --data-binary @FILE '{url}'",
        "expires_in": uploads.ttl_seconds,
        "max_bytes": uploads.max_bytes,
    }


def enable_uploads(mcp: FastMCP, uploads: Uploads) -> None:
    """Publish `begin_upload` and the route its links point at. Safe to call twice."""
    global _uploads  # noqa: PLW0603 - one service per process, set once at startup
    already = _uploads is not None
    _uploads = uploads
    if already:
        return
    mcp.tool(
        annotations={
            "title": "Upload a File",
            # Issues a link; the write happens when the file arrives on it.
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )(begin_upload)
    mcp.custom_route(f"{UPLOAD_PATH}/{{ticket}}", methods=["POST"])(_route)


async def _route(request: Request) -> Response:
    # Resolved per request rather than bound at registration, so the route
    # follows whatever service `enable_uploads` installed last.
    if _uploads is None:
        return _error(404, "Uploads are not enabled on this server.")
    return await _uploads.receive(request)
