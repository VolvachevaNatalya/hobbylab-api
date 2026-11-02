"""
Rate-limiting regression tests for POST /auth/login and OAuth login endpoints.

All four token-issuance endpoints share one in-process IP-keyed bucket:
10 attempts per 15-minute window. Tests import _login_attempts directly and
clear it in an autouse fixture so each test starts with a clean slate.
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


# ── POST /auth/login ───────────────────────────────────────────────────────────

def test_tenth_login_attempt_succeeds(client, db):
    """The limit boundary: the 10th attempt from an IP must not be blocked."""
    from app.core.security import hash_password
    from app.models.user import User

    u = User(email="valid@test.com", name="V", password_hash=hash_password("pass123"))
    db.add(u)
    db.commit()

    for i in range(_LOGIN_RATE_LIMIT - 1):
        client.post(
            "/auth/login",
            data={"username": f"no{i}@test.com", "password": "wrong"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/login",
        data={"username": "valid@test.com", "password": "pass123"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 200


def test_eleventh_login_attempt_blocked(client):
    """The 11th attempt from the same IP returns 429."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/login",
            data={"username": "x@test.com", "password": "wrong"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/login",
        data={"username": "x@test.com", "password": "wrong"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_login_rate_limit_returns_retry_after_header(client):
    """429 response must include a Retry-After header with a positive integer value."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/login",
            data={"username": "x@test.com", "password": "wrong"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/login",
        data={"username": "x@test.com", "password": "wrong"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429
    assert "retry-after" in resp.headers
    assert int(resp.headers["retry-after"]) >= 1


def test_login_rate_limit_is_per_ip(client):
    """Exhausting IP_A's limit must not block IP_B."""
    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/login",
            data={"username": "x@test.com", "password": "wrong"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/login",
        data={"username": "y@test.com", "password": "wrong"},
        headers={"X-Real-IP": _IP_B},
    )
    assert resp.status_code != 429


def test_login_pydantic_errors_do_not_consume_slots(client, db):
    """Requests rejected by Pydantic (422) before the handler runs must not count."""
    from app.core.security import hash_password
    from app.models.user import User

    u = User(email="ok@test.com", name="OK", password_hash=hash_password("pass123"))
    db.add(u)
    db.commit()

    # OAuth2PasswordRequestForm requires form data; sending JSON → 422
    for _ in range(_LOGIN_RATE_LIMIT + 5):
        resp = client.post(
            "/auth/login",
            json={"username": "ok@test.com", "password": "pass123"},
            headers={"X-Real-IP": _IP_A},
        )
        assert resp.status_code == 422

    # Rate limit bucket must still be intact
    resp = client.post(
        "/auth/login",
        data={"username": "ok@test.com", "password": "pass123"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 200


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
            json={"id_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    resp = client.post(
        "/auth/apple-login",
        json={"id_token": "fake"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_oauth_and_password_login_share_bucket(client):
    """Mixing OAuth and password-login attempts from the same IP shares one bucket."""
    for _ in range(5):
        client.post(
            "/auth/login",
            data={"username": "x@test.com", "password": "wrong"},
            headers={"X-Real-IP": _IP_A},
        )
    for _ in range(5):
        client.post(
            "/auth/google-login",
            json={"id_token": "fake"},
            headers={"X-Real-IP": _IP_A},
        )
    # 10 total attempts → next attempt (any endpoint) must be 429
    resp = client.post(
        "/auth/login",
        data={"username": "x@test.com", "password": "wrong"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 429


def test_login_and_registration_limits_are_independent(client, db):
    """Login and registration limits use separate buckets; exhausting one
    must not block the other."""
    from app.api.auth import _reg_attempts
    _reg_attempts.clear()

    for _ in range(_LOGIN_RATE_LIMIT):
        client.post(
            "/auth/login",
            data={"username": "x@test.com", "password": "wrong"},
            headers={"X-Real-IP": _IP_A},
        )

    resp = client.post(
        "/auth/register",
        json={"email": "brand_new@test.com", "name": "New", "password": "pass1234"},
        headers={"X-Real-IP": _IP_A},
    )
    assert resp.status_code == 200
