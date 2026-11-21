"""
Rate-limiting regression tests for social login endpoints.

Google, Facebook, and Apple login share one in-process IP-keyed bucket:
10 attempts per 15-minute window.
"""
import pytest

from app.api.auth import _LOGIN_RATE_LIMIT, _login_attempts

_IP_A = "203.0.113.10"
_IP_B = "203.0.113.20"


@pytest.fixture(autouse=True)
def clear_login_rate_limit():
    _login_attempts.clear()
    yield
    _login_attempts.clear()


# ── OAuth endpoints share the same bucket ─────────────────────────────────────

def test_google_login_rate_limited(client):
    """POST /auth/google-login participates in the shared login rate limit."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/google-login",
            json={"id_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/google-login",
        json={"id_token": "fake"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_facebook_login_rate_limited(client):
    """POST /auth/facebook-login participates in the shared login rate limit."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/facebook-login",
            json={"access_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/facebook-login",
        json={"access_token": "fake"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_apple_login_rate_limited(client):
    """POST /auth/apple-login participates in the shared login rate limit."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/apple-login",
            json={"id_token": "fake", "nonce": "fake-nonce"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/apple-login",
        json={"id_token": "fake", "nonce": "fake-nonce"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_social_login_rate_limit_is_per_ip(client):
    """Exhausting IP_A's login limit must not block IP_B."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/google-login",
            json={"id_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/google-login",
        json={"id_token": "fake"},
        headers={"X-Real-IP": _IP_B},
    )
    assert resp.status_code != 429


def test_social_login_rate_limit_returns_retry_after_header(client):
    """429 response must include a Retry-After header with a positive integer value."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/google-login",
            json={"id_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/google-login",
        json={"id_token": "fake"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429
    assert "retry-after" in resp.headers
    assert int(resp.headers["retry-after"]) >= 1


def test_cross_provider_attempts_share_bucket(client):
    """Mixing Google and Facebook attempts from the same IP shares one bucket."""
    for _ in range(5):
        client.post(
            "/auth/google-login",
            json={"id_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    for _ in range(5):
        client.post(
            "/auth/facebook-login",
            json={"access_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    # 10 total → next attempt must be 429
    resp = client.post(
        "/auth/apple-login",
        json={"id_token": "fake", "nonce": "fake-nonce"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429
