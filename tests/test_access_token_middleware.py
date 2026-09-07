"""Optional shared-secret gate for the LifeOS API.

LifeOS was designed for a private tailnet and ships with no authentication of
its own (see the CORS note in ``api/main.py``). That assumption breaks the
moment the same process runs on a public VPS: the 2026-09 audit of one such
deployment found unrelated hosts on the open internet had already fetched
``/api/memories`` and the whole ``/crm`` UI.

``LIFEOS_API_TOKEN`` closes that hole without changing the tailnet story: unset
(the default) the middleware is inert, so an existing private deployment
behaves exactly as before.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.access_token import AccessTokenMiddleware

pytestmark = pytest.mark.unit


def _app(token: str, **kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AccessTokenMiddleware, token=token, **kwargs)

    @app.get("/api/memories")
    async def memories():
        return {"memories": []}

    return app


class TestDisabledByDefault:
    def test_no_token_configured_leaves_every_request_alone(self):
        client = TestClient(_app(""))
        assert client.get("/api/memories").status_code == 200

    def test_whitespace_only_token_is_treated_as_unset(self):
        client = TestClient(_app("   "))
        assert client.get("/api/memories").status_code == 200


class TestEnabled:
    @pytest.fixture
    def client(self):
        # A remote client address: TestClient defaults to "testclient", which
        # is not a loopback address, so these requests take the guarded path.
        return TestClient(_app("s3cret"))

    def test_request_without_credentials_is_rejected(self, client):
        response = client.get("/api/memories")
        assert response.status_code == 401
        assert "memories" not in response.text

    def test_bearer_token_is_accepted(self, client):
        response = client.get(
            "/api/memories", headers={"Authorization": "Bearer s3cret"}
        )
        assert response.status_code == 200

    def test_wrong_bearer_token_is_rejected(self, client):
        response = client.get(
            "/api/memories", headers={"Authorization": "Bearer wrong"}
        )
        assert response.status_code == 401

    def test_header_token_is_accepted(self, client):
        response = client.get("/api/memories", headers={"X-LifeOS-Token": "s3cret"})
        assert response.status_code == 200

    def test_cookie_token_is_accepted(self, client):
        client.cookies.set("lifeos_token", "s3cret")
        assert client.get("/api/memories").status_code == 200

    def test_query_token_is_accepted_and_sets_a_cookie(self, client):
        """So the browser UI needs the token in the URL exactly once."""
        response = client.get("/api/memories?token=s3cret")
        assert response.status_code == 200
        assert response.cookies.get("lifeos_token") == "s3cret"

    def test_loopback_callers_are_exempt(self):
        """Watchdogs, sync scripts and the Telegram worker all call localhost."""
        client = TestClient(_app("s3cret"), client=("127.0.0.1", 5555))
        assert client.get("/api/memories").status_code == 200

    def test_exempt_paths_stay_open(self):
        app = _app("s3cret", exempt_paths=("/health",))

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        client = TestClient(app)
        assert client.get("/health").status_code == 200
        assert client.get("/api/memories").status_code == 401
