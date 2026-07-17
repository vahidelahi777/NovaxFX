"""FastAPI admin application factory.

Only module in the admin package that imports FastAPI. Keep route handlers thin:
all logic lives in auth.py (pure) and services.py (pure).

Usage:
    from novax.admin.app import create_app
    app = create_app(password_hash=..., session_secret=...)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .auth import (
    RateLimiter,
    generate_csrf,
    issue_session,
    verify_csrf,
    verify_password,
    verify_session,
)
from .services import health_snapshot

__all__ = ["create_app"]

_VIEWS_DIR = Path(__file__).parent / "views"
_SESSION_COOKIE = "session"
_SESSION_MAX_AGE = 8 * 3600  # 8 hours


def create_app(
    *,
    password_hash: str,
    session_secret: str,
    check_db: Callable[[], bool] | None = None,
    cookie_secure: bool = True,
) -> FastAPI:
    """Construct and wire the admin FastAPI application.

    Args:
        password_hash:  argon2id hash of the admin password (from env).
        session_secret: Secret for itsdangerous signing (from env).
        check_db:       Zero-arg callable returning True when DB is reachable.
        cookie_secure:  Set Secure flag on session cookie; disable in tests.
    """
    _check_db: Callable[[], bool] = check_db if check_db is not None else lambda: False
    _rate_limiter = RateLimiter()
    templates = Jinja2Templates(directory=str(_VIEWS_DIR))

    app = FastAPI(title="NovaxFX Admin", docs_url=None, redoc_url=None)

    # ------------------------------------------------------------------
    # Helpers (closures over config)
    # ------------------------------------------------------------------

    def _get_identity(request: Request) -> str | None:
        token = request.cookies.get(_SESSION_COOKIE)
        if token is None:
            return None
        return verify_session(session_secret, token, max_age=_SESSION_MAX_AGE)

    def _set_session(response: RedirectResponse, identity: str) -> None:
        token = issue_session(session_secret, identity)
        response.set_cookie(
            _SESSION_COOKIE,
            token,
            max_age=_SESSION_MAX_AGE,
            httponly=True,
            secure=cookie_secure,
            samesite="strict",
        )

    def _clear_session(response: RedirectResponse) -> None:
        response.delete_cookie(
            _SESSION_COOKIE,
            httponly=True,
            secure=cookie_secure,
            samesite="strict",
        )

    # ------------------------------------------------------------------
    # Auth routes
    # ------------------------------------------------------------------

    @app.get("/login")
    async def login_get(request: Request) -> Response:
        if _get_identity(request) is not None:
            return RedirectResponse(url="/", status_code=302)
        csrf = generate_csrf(session_secret)
        return templates.TemplateResponse(
            request, "login.html", {"csrf_token": csrf, "error": None}
        )

    @app.post("/login")
    async def login_post(
        request: Request,
        password: Annotated[str, Form()] = "",
        csrf_token: Annotated[str, Form()] = "",
    ) -> Response:
        ip = request.client.host if request.client is not None else "unknown"

        if not verify_csrf(session_secret, csrf_token):
            csrf = generate_csrf(session_secret)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"csrf_token": csrf, "error": "Invalid request."},
                status_code=400,
            )

        if _rate_limiter.is_locked(ip):
            csrf = generate_csrf(session_secret)
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "csrf_token": csrf,
                    "error": "Too many attempts. Please try again later.",
                },
                status_code=429,
            )

        if not verify_password(password_hash, password):
            _rate_limiter.record_failure(ip)
            csrf = generate_csrf(session_secret)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"csrf_token": csrf, "error": "Invalid credentials."},
                status_code=401,
            )

        _rate_limiter.reset(ip)
        response = RedirectResponse(url="/", status_code=303)
        _set_session(response, "admin")
        return response

    @app.post("/logout")
    async def logout(
        request: Request,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if not verify_csrf(session_secret, csrf_token):
            return RedirectResponse(url="/login", status_code=302)
        response = RedirectResponse(url="/login", status_code=303)
        _clear_session(response)
        return response

    # ------------------------------------------------------------------
    # Protected routes
    # ------------------------------------------------------------------

    @app.get("/")
    async def dashboard(request: Request) -> Response:
        identity = _get_identity(request)
        if identity is None:
            return RedirectResponse(url="/login", status_code=302)
        csrf = generate_csrf(session_secret)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"admin_user": identity, "csrf_token": csrf},
        )

    @app.get("/health")
    async def health(request: Request) -> Response:
        identity = _get_identity(request)
        if identity is None:
            return RedirectResponse(url="/login", status_code=302)
        snap = health_snapshot(_check_db)
        csrf = generate_csrf(session_secret)
        return templates.TemplateResponse(
            request,
            "health.html",
            {
                "admin_user": identity,
                "csrf_token": csrf,
                "snapshot": snap,
            },
        )

    return app
