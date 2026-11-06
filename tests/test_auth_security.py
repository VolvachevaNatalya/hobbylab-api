"""
Regression tests for two P2 auth security findings.

1. OAuth exception leakage — Google/Apple/Facebook error handlers expose raw
   Python exception strings in HTTP response bodies.  After the fix every
   failing OAuth attempt returns a generic "Invalid credentials" message.

2. POST /auth/refresh rate limiting — the refresh endpoint previously had no
   rate limit, allowing unlimited token-refresh attempts.  After the fix it
   shares the existing login IP bucket (10 attempts per 15-minute window).
"""
import os
from unittest.mock import patch

import pytest

from app.api.auth import (
    _LOGIN_RATE_LIMIT, _login_attempts,
    _REFRESH_RATE_LIMIT, _refresh_attempts,
)
from app.core.security import create_refresh_token, hash_password
from app.models.user import User

_REFRESH_URL = "/auth/refresh"
_GOOGLE_URL = "/auth/google-login"
_APPLE_URL = "/auth/apple-login"
_FACEBOOK_URL = "/auth/facebook-login"

_IP_A = "203.0.113.50"
_IP_B = "203.0.113.51"


@pytest.fixture(autouse=True)
def clear_rate_limits():
    _login_attempts.clear()
    _refresh_attempts.clear()
    yield
    _login_attempts.clear()
    _refresh_attempts.clear()


def _make_user(db, email="sec@test.com"):
    u = User(
        email=email,
        name="Security Test",
        password_hash=hash_password("pw"),
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ── Finding 1: OAuth exception strings must not appear in HTTP responses ──────

class TestGoogleErrorLeakage:
    """Regression: ValueError from google-auth must not reach the HTTP client."""

    def test_invalid_google_token_returns_401(self, client):
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client-id"}), \
             patch("google.oauth2.id_token.verify_oauth2_token",
                   side_effect=ValueError("Token has been expired or revoked.")):
            resp = client.post(
                _GOOGLE_URL,
                json={"id_token": "fake-token"},
                headers={"X-Real-IP": _IP_B},
            )
        assert resp.status_code == 401

    def test_google_error_body_does_not_contain_exception_message(self, client):
        """
        Regression: the raw ValueError text must not be forwarded to clients.
        Before the fix: detail contained 'Token has been expired or revoked.'
        After the fix:  detail is a generic message.
        """
        exc_text = "Token has been expired or revoked."
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client-id"}), \
             patch("google.oauth2.id_token.verify_oauth2_token",
                   side_effect=ValueError(exc_text)):
            resp = client.post(
                _GOOGLE_URL,
                json={"id_token": "fake-token"},
                headers={"X-Real-IP": _IP_B},
            )
        body = resp.text
        assert exc_text not in body, (
            f"Exception string leaked into response body: {body!r}"
        )

    def test_google_error_body_does_not_contain_internal_error_prefix(self, client):
        """The 'Invalid Google token:' prefix itself must not appear in the response."""
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client-id"}), \
             patch("google.oauth2.id_token.verify_oauth2_token",
                   side_effect=ValueError("some internal detail")):
            resp = client.post(
                _GOOGLE_URL,
                json={"id_token": "fake-token"},
                headers={"X-Real-IP": _IP_B},
            )
        body = resp.text.lower()
        assert "some internal detail" not in body
        assert "invalid google token" not in body

    def test_google_error_returns_generic_message(self, client):
        """After the fix the detail must be a safe, user-facing string."""
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client-id"}), \
             patch("google.oauth2.id_token.verify_oauth2_token",
                   side_effect=ValueError("audience mismatch")):
            resp = client.post(
                _GOOGLE_URL,
                json={"id_token": "fake-token"},
                headers={"X-Real-IP": _IP_B},
            )
        assert resp.status_code == 401
        detail = resp.json().get("detail", "")
        assert "audience mismatch" not in detail


class TestAppleErrorLeakage:
    """Regression: JWTError from python-jose must not reach the HTTP client."""

    def test_invalid_apple_token_error_not_in_response(self, client):
        """
        Regression: 'Invalid Apple token: <jose internals>' was previously
        forwarded verbatim.
        """
        import httpx as _httpx

        jwks_payload = {"keys": []}
        mock_jwks_resp = _httpx.Response(200, json=jwks_payload)

        from jose import JWTError

        with patch("httpx.get", return_value=mock_jwks_resp), \
             patch("jose.jwt.decode",
                   side_effect=JWTError("Signature verification failed.")):
            resp = client.post(
                _APPLE_URL,
                json={"id_token": "fake-token"},
                headers={"X-Real-IP": _IP_B},
            )

        assert resp.status_code == 401
        assert "Signature verification failed." not in resp.text
        assert "Invalid Apple token" not in resp.text


# ── Finding 2: POST /auth/refresh must be rate limited ────────────────────────

class TestRefreshRateLimit:
    """
    /auth/refresh uses its own lenient bucket (30/15 min) separate from the
    login bucket (10/15 min).  This prevents NAT exhaustion: when 10+ users on
    the same school network all have their 60-minute tokens expire at once, they
    should all be able to refresh without being blocked by the tighter login limit.
    """

    def test_refresh_below_limit_succeeds(self, client, db):
        """The _REFRESH_RATE_LIMIT-th attempt from one IP must still be accepted."""
        user = _make_user(db, "rl_ok@test.com")
        refresh_tok = create_refresh_token({"user_id": user.id})

        for _ in range(_REFRESH_RATE_LIMIT - 1):
            client.post(
                _REFRESH_URL,
                json={"refresh_token": "garbage-not-valid"},
                headers={"X-Real-IP": _IP_A},
            )

        resp = client.post(
            _REFRESH_URL,
            json={"refresh_token": refresh_tok},
            headers={"X-Real-IP": _IP_A},
        )
        assert resp.status_code == 200

    def test_refresh_over_limit_returns_429(self, client):
        """The (REFRESH_LIMIT+1)-th refresh attempt from one IP must return 429."""
        for _ in range(_REFRESH_RATE_LIMIT):
            client.post(
                _REFRESH_URL,
                json={"refresh_token": "garbage"},
                headers={"X-Real-IP": _IP_A},
            )

        resp = client.post(
            _REFRESH_URL,
            json={"refresh_token": "garbage"},
            headers={"X-Real-IP": _IP_A},
        )
        assert resp.status_code == 429

    def test_refresh_429_includes_retry_after_header(self, client):
        """Rate-limited refresh response must include a Retry-After header."""
        for _ in range(_REFRESH_RATE_LIMIT):
            client.post(
                _REFRESH_URL,
                json={"refresh_token": "garbage"},
                headers={"X-Real-IP": _IP_A},
            )

        resp = client.post(
            _REFRESH_URL,
            json={"refresh_token": "garbage"},
            headers={"X-Real-IP": _IP_A},
        )
        assert resp.status_code == 429
        assert "retry-after" in resp.headers
        assert int(resp.headers["retry-after"]) >= 1

    def test_refresh_rate_limit_is_per_ip(self, client, db):
        """Exhausting IP_A's refresh limit must not affect IP_B."""
        user = _make_user(db, "rl_ipb@test.com")
        refresh_tok = create_refresh_token({"user_id": user.id})

        for _ in range(_REFRESH_RATE_LIMIT):
            client.post(
                _REFRESH_URL,
                json={"refresh_token": "garbage"},
                headers={"X-Real-IP": _IP_A},
            )

        resp = client.post(
            _REFRESH_URL,
            json={"refresh_token": refresh_tok},
            headers={"X-Real-IP": _IP_B},
        )
        assert resp.status_code == 200

    def test_refresh_and_login_use_independent_buckets(self, client, db):
        """
        Login and refresh have separate buckets.  Exhausting the login limit
        must NOT block refresh, and vice versa.  This prevents NAT exhaustion
        when multiple users on the same IP refresh simultaneously.
        """
        user = _make_user(db, "rl_indep@test.com")
        refresh_tok = create_refresh_token({"user_id": user.id})

        # Exhaust the login bucket completely.
        for _ in range(_LOGIN_RATE_LIMIT):
            client.post(
                "/auth/login",
                data={"username": "x@test.com", "password": "wrong"},
                headers={"X-Real-IP": _IP_A},
            )

        # Refresh must still work from the same IP.
        resp = client.post(
            _REFRESH_URL,
            json={"refresh_token": refresh_tok},
            headers={"X-Real-IP": _IP_A},
        )
        assert resp.status_code == 200, (
            "exhausting the login bucket must not block the refresh endpoint"
        )

    def test_pydantic_rejection_does_not_consume_rate_limit_slot(self, client, db):
        """
        Requests rejected by Pydantic (missing refresh_token field, 422) must
        not count against the rate limit — the handler never runs.
        """
        user = _make_user(db, "rl_pyd@test.com")
        refresh_tok = create_refresh_token({"user_id": user.id})

        for _ in range(_REFRESH_RATE_LIMIT + 5):
            client.post(
                _REFRESH_URL,
                json={},
                headers={"X-Real-IP": _IP_A},
            )

        resp = client.post(
            _REFRESH_URL,
            json={"refresh_token": refresh_tok},
            headers={"X-Real-IP": _IP_A},
        )
        assert resp.status_code == 200
