"""Smoke tests for the admin FastAPI app via TestClient — no live server needed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novax.admin.app import create_app
from novax.admin.auth import generate_csrf, hash_password

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SECRET = "test-session-secret-32chars-xxxx"
_PASSWORD = "hunter2-admin"
# Hash computed once at import time (argon2 is fast enough for tests)
_HASH = hash_password(_PASSWORD)


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app(
        password_hash=_HASH,
        session_secret=_SECRET,
        check_db=lambda: True,
        cookie_secure=False,  # TestClient uses HTTP, not HTTPS
    )
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------


def test_login_page_renders(client: TestClient) -> None:
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "login" in resp.text.lower()


def test_login_page_contains_csrf_field(client: TestClient) -> None:
    resp = client.get("/login")
    assert 'name="csrf_token"' in resp.text


# ---------------------------------------------------------------------------
# Protected routes redirect when unauthenticated
# ---------------------------------------------------------------------------


def test_root_redirects_unauthenticated(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/login")


def test_health_redirects_unauthenticated(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/login")


# ---------------------------------------------------------------------------
# Login flow
# ---------------------------------------------------------------------------


def test_correct_login_redirects_and_sets_cookie(client: TestClient) -> None:
    csrf = generate_csrf(_SECRET)
    resp = client.post("/login", data={"password": _PASSWORD, "csrf_token": csrf})
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/")
    assert "session" in resp.cookies


def test_wrong_password_stays_on_login(client: TestClient) -> None:
    csrf = generate_csrf(_SECRET)
    resp = client.post("/login", data={"password": "wrongpassword", "csrf_token": csrf})
    assert resp.status_code == 401
    assert "invalid credentials" in resp.text.lower()


def test_missing_csrf_rejected(client: TestClient) -> None:
    resp = client.post("/login", data={"password": _PASSWORD, "csrf_token": ""})
    assert resp.status_code == 400


def test_tampered_csrf_rejected(client: TestClient) -> None:
    csrf = generate_csrf(_SECRET) + "tampered"
    resp = client.post("/login", data={"password": _PASSWORD, "csrf_token": csrf})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Authenticated session
# ---------------------------------------------------------------------------


def test_authenticated_session_reaches_dashboard(client: TestClient) -> None:
    csrf = generate_csrf(_SECRET)
    login = client.post("/login", data={"password": _PASSWORD, "csrf_token": csrf})
    assert login.status_code == 303

    session_cookie = login.cookies["session"]
    resp = client.get("/", cookies={"session": session_cookie})
    assert resp.status_code == 200
    assert "dashboard" in resp.text.lower()


def test_authenticated_session_reaches_health(client: TestClient) -> None:
    csrf = generate_csrf(_SECRET)
    login = client.post("/login", data={"password": _PASSWORD, "csrf_token": csrf})
    session_cookie = login.cookies["session"]

    resp = client.get("/health", cookies={"session": session_cookie})
    assert resp.status_code == 200
    assert "health" in resp.text.lower()


def test_already_logged_in_redirects_away_from_login(client: TestClient) -> None:
    csrf = generate_csrf(_SECRET)
    login = client.post("/login", data={"password": _PASSWORD, "csrf_token": csrf})
    session_cookie = login.cookies["session"]

    resp = client.get("/login", cookies={"session": session_cookie})
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/")


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_clears_session(client: TestClient) -> None:
    csrf = generate_csrf(_SECRET)
    login = client.post("/login", data={"password": _PASSWORD, "csrf_token": csrf})
    session_cookie = login.cookies["session"]

    logout_csrf = generate_csrf(_SECRET)
    logout = client.post(
        "/logout",
        data={"csrf_token": logout_csrf},
        cookies={"session": session_cookie},
    )
    assert logout.status_code == 303
    assert logout.headers["location"].endswith("/login")
