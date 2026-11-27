import pytest

from tests.conftest import PASSWORD, AppHarness

pytestmark = pytest.mark.postgres


async def test_register_login_me_logout(harness: AppHarness) -> None:
    client = harness.client()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "Kay@Example.com", "password": PASSWORD, "display_name": " Kay "},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "kay@example.com"
    assert body["user"]["display_name"] == "Kay"
    cookie = response.headers["set-cookie"]
    assert "kaygpt_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "password" not in response.text

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["csrf_token"] == body["csrf_token"]

    # Logout needs the CSRF token.
    assert (await client.post("/api/v1/auth/logout")).status_code == 403
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    login = await client.post(
        "/api/v1/auth/login", json={"email": "kay@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["csrf_token"] != body["csrf_token"]  # new session, new token


async def test_logout_revokes_session_server_side(harness: AppHarness) -> None:
    client = await harness.user_client()
    token = client.cookies.get("kaygpt_session")
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    replay = harness.client()
    replay.cookies.set("kaygpt_session", token or "")
    rejected = await replay.get("/api/v1/auth/me")
    assert rejected.status_code == 401
    # The stale cookie is cleared so the frontend's redirect guard cannot loop.
    assert 'kaygpt_session=""' in rejected.headers["set-cookie"]


async def test_duplicate_email_and_bad_credentials(harness: AppHarness) -> None:
    client = harness.client()
    payload = {"email": "dup@example.com", "password": PASSWORD}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    dup = await client.post("/api/v1/auth/register", json=payload)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "email_taken"

    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "dup@example.com", "password": "nope-nope-nope"}
    )
    assert wrong.status_code == 401
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_validation_errors(harness: AppHarness) -> None:
    client = harness.client()
    short = await client.post(
        "/api/v1/auth/register", json={"email": "a@b.co", "password": "short"}
    )
    assert short.status_code == 422
    assert short.json()["error"]["code"] == "validation_error"
    bad_email = await client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD}
    )
    assert bad_email.status_code == 422


async def test_protected_endpoints_require_auth(harness: AppHarness) -> None:
    client = harness.client()
    for method, path in [
        ("GET", "/api/v1/conversations"),
        ("GET", "/api/v1/documents"),
        ("GET", "/api/v1/memory"),
        ("GET", "/api/v1/preferences"),
        ("POST", "/api/v1/chat/stream"),
    ]:
        response = await client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 401, path


async def test_csrf_and_origin_enforced_for_mutations(harness: AppHarness) -> None:
    client = await harness.user_client()
    csrf = client.headers.pop("X-CSRF-Token")
    missing = await client.post("/api/v1/conversations", json={})
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "csrf_failed"

    client.headers["X-CSRF-Token"] = csrf
    client.headers["Origin"] = "https://evil.example"
    evil = await client.post("/api/v1/conversations", json={})
    assert evil.status_code == 403 and evil.json()["error"]["code"] == "origin_not_allowed"

    client.headers["Origin"] = "http://localhost:3000"
    assert (await client.post("/api/v1/conversations", json={})).status_code == 201


async def test_auth_rate_limit(harness: AppHarness) -> None:
    harness.settings.rate_limit_auth_per_minute = 3
    client = harness.client()
    codes = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": "x@example.com", "password": "whatever-123"}
            )
        ).status_code
        for _ in range(4)
    ]
    assert codes == [401, 401, 401, 429]


async def test_health_endpoints(harness: AppHarness) -> None:
    client = harness.client()
    assert (await client.get("/api/v1/health")).json()["status"] == "ok"
    ready = await client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] == "ok"
    assert "x-request-id" in ready.headers


async def test_chat_rate_limit_is_per_user_not_per_ip(harness: AppHarness) -> None:
    harness.settings.rate_limit_chat_per_minute = 2
    alice = await harness.user_client()
    bob = await harness.user_client()
    for i in range(2):
        response = await alice.post(
            "/api/v1/chat/stream",
            json={"message": f"hi {i}"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},  # changing IP does not help
        )
        assert response.status_code == 200
    limited = await alice.post(
        "/api/v1/chat/stream", json={"message": "again"}, headers={"X-Forwarded-For": "10.9.9.9"}
    )
    assert limited.status_code == 429 and "retry-after" in limited.headers
    assert (await bob.post("/api/v1/chat/stream", json={"message": "hi"})).status_code == 200
