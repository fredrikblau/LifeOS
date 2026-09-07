"""Optional shared-secret gate in front of the whole API.

LifeOS assumes a private network: the app has no authentication of its own,
and the CORS allowlist in ``api/main.py`` is written around "the tailnet" as
the security boundary. That is a sound assumption on a laptop or a tailnet
host, and a dangerous one on a public VPS — a 2026-09 audit of one deployment
found unrelated internet hosts had already read ``/api/memories`` and browsed
the ``/crm`` pages.

So this middleware is *opt-in and inert by default*: with ``LIFEOS_API_TOKEN``
unset, every request passes untouched and a private deployment behaves exactly
as it did before. Set the variable and any non-loopback caller must present the
token — as a ``Bearer`` credential, an ``X-LifeOS-Token`` header, a
``lifeos_token`` cookie, or a one-time ``?token=`` query parameter that is then
stored as a cookie so the browser UI only needs it in the URL once.

Loopback callers are exempt on purpose: the watchdogs, sync scripts, MCP
server and Telegram worker all reach the API over localhost, and anything
already running as the LifeOS user can read the databases directly anyway.

This is a perimeter, not a login system: one shared secret, one user. It stops
the internet from reading a personal life. It is not a substitute for keeping
the port off the public internet — do both.
"""
import ipaddress
import logging
import secrets
from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

COOKIE_NAME = "lifeos_token"
QUERY_PARAM = "token"
HEADER_NAME = "X-LifeOS-Token"

# One year: the cookie is a convenience for a single-user browser session, and
# re-pasting the token into a URL is the recovery path if it ever expires.
_COOKIE_MAX_AGE = 365 * 24 * 3600


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AccessTokenMiddleware(BaseHTTPMiddleware):
    """Require a shared token from non-loopback callers, when one is set."""

    def __init__(self, app, token: str = "", exempt_paths: Iterable[str] = ()):
        super().__init__(app)
        self.token = (token or "").strip()
        self.exempt_paths = tuple(exempt_paths)

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _presented_token(self, request: Request) -> tuple[str, bool]:
        """Return the caller's token and whether it arrived as a query param."""
        authorization = request.headers.get("authorization", "")
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() == "bearer" and credential.strip():
            return credential.strip(), False

        header = request.headers.get(HEADER_NAME)
        if header:
            return header.strip(), False

        cookie = request.cookies.get(COOKIE_NAME)
        if cookie:
            return cookie.strip(), False

        query = request.query_params.get(QUERY_PARAM)
        if query:
            return query.strip(), True

        return "", False

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        if any(path == exempt or path.startswith(exempt.rstrip("/") + "/")
               for exempt in self.exempt_paths):
            return await call_next(request)

        if _is_loopback(request.client.host if request.client else None):
            return await call_next(request)

        presented, from_query = self._presented_token(request)
        # compare_digest keeps a wrong guess from leaking its correct prefix
        # through response timing.
        if not presented or not secrets.compare_digest(presented, self.token):
            client = request.client.host if request.client else "unknown"
            logger.warning("Rejected unauthenticated %s %s from %s",
                           request.method, path, client)
            return JSONResponse(
                {"detail": "Unauthorized: LIFEOS_API_TOKEN required."},
                status_code=401,
            )

        response = await call_next(request)
        if from_query:
            # Carry the credential forward so the rest of the browsing session
            # (and the UI's own fetches, which have no token in their URLs)
            # keeps working without the token in every link.
            response.set_cookie(
                COOKIE_NAME, self.token, max_age=_COOKIE_MAX_AGE,
                httponly=True, samesite="lax",
                secure=request.url.scheme == "https",
            )
        return response
