"""
Regression tests: blocked / inactive users must not be able to access
protected endpoints, refresh tokens, or authenticate via social login.

Coverage:
  - Google OAuth login     (blocked → 403, mocked token verification)
  - JWT access on protected endpoint  (blocked user with valid token → 403)
  - Token refresh          (blocked user with valid refresh token → 403)
  - Active system admin    (unaffected by status checks)
  - email/password accounts blocked at Google OAuth (provider mismatch)

Facebook and Apple login exercise identical code paths to Google; they are
not covered here because they require mocking external HTTP calls (httpx)
to the Facebook Graph API and Apple JWKS endpoint.
"""
import pytest
from unittest.mock import patch

from app.api.auth import _login_attempts
from app.core.security import create_access_token, create_refresh_token
from app.models.user import User

_REFRESH_URL = "/auth/refresh"
_PROTECTED_URL = "/admin/me"          # requires system admin
_AUTH_ENDPOINT = "/subscriptions/organization/1"  # requires any authenticated user


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_login_rate_limit():
    """Clear the in-process login rate-limit bucket before and after every test."""
    _login_attempts.clear()
    yield
    _login_attempts.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, status="active", is_admin=False, password_hash=None):
    u = User(
        email=email,
        name="Test User",
        password_hash=password_hash,
        status=status,
        is_system_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _bearer(user_id: int, token_type="access") -> dict:
    if token_type == "refresh":
        token = create_refresh_token({"user_id": user_id})
    else:
        token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── JWT access on protected endpoints ────────────────────────────────────────

def test_active_user_can_access_protected_endpoint(client, db):
    user = _make_user(db, "active_jwt@test.com", status="active", is_admin=True)
    resp = client.get(_PROTECTED_URL, headers=_bearer(user.id))
    assert resp.status_code == 200


def test_blocked_user_jwt_rejected_on_protected_endpoint(client, db):
    """A valid JWT for a blocked user must return 403, not 200."""
    user = _make_user(db, "blocked_jwt@test.com", status="blocked", is_admin=True)
    resp = client.get(_PROTECTED_URL, headers=_bearer(user.id))
    assert resp.status_code == 403


def test_inactive_user_jwt_rejected_on_protected_endpoint(client, db):
    user = _make_user(db, "inactive_jwt@test.com", status="inactive")
    resp = client.get(_AUTH_ENDPOINT, headers=_bearer(user.id))
    assert resp.status_code == 403


def test_blocked_user_jwt_rejected_on_non_admin_endpoint(client, db):
    """Status check fires before any route logic on all authenticated endpoints."""
    user = _make_user(db, "blocked_me@test.com", status="blocked")
    resp = client.get(_AUTH_ENDPOINT, headers=_bearer(user.id))
    assert resp.status_code == 403


# ── Token refresh ─────────────────────────────────────────────────────────────

def test_active_user_can_refresh_token(client, db):
    user = _make_user(db, "active_ref@test.com", status="active")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_blocked_user_cannot_refresh_token(client, db):
    """A blocked user's refresh token must be rejected."""
    user = _make_user(db, "blocked_ref@test.com", status="blocked")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    assert resp.status_code == 403


def test_inactive_user_cannot_refresh_token(client, db):
    user = _make_user(db, "inactive_ref@test.com", status="inactive")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    assert resp.status_code == 403


# ── Active system admin is unaffected ────────────────────────────────────────

def test_active_system_admin_can_access_admin_endpoint(client, db):
    user = _make_user(db, "sysadmin@test.com", status="active", is_admin=True)
    resp = client.get(_PROTECTED_URL, headers=_bearer(user.id))
    assert resp.status_code == 200


def test_blocked_system_admin_jwt_rejected(client, db):
    """is_system_admin does not bypass the status check."""
    user = _make_user(db, "blocked_admin_jwt@test.com", status="blocked", is_admin=True)
    resp = client.get(_PROTECTED_URL, headers=_bearer(user.id))
    assert resp.status_code == 403


# ── Google login with mocked token verification ───────────────────────────────

def _mock_google_id_info(email: str, sub: str = "google_sub_123") -> dict:
    return {"email": email, "name": "Test User", "sub": sub, "email_verified": True}


def test_active_user_google_login_succeeds(client, db):
    _make_user(db, "active_google@test.com", status="active")
    id_info = _mock_google_id_info("active_google@test.com")
    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post("/auth/google-login", json={"id_token": "fake-token"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_blocked_user_google_login_rejected(client, db):
    _make_user(db, "blocked_google@test.com", status="blocked")
    id_info = _mock_google_id_info("blocked_google@test.com")
    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post("/auth/google-login", json={"id_token": "fake-token"})
    assert resp.status_code == 403


def test_new_user_google_login_succeeds(client, db):
    """A brand-new user created by Google OAuth has status 'active' and should succeed."""
    id_info = _mock_google_id_info("newuser_google@test.com")
    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post("/auth/google-login", json={"id_token": "fake-token"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_email_password_account_blocked_at_google_login(client, db):
    """
    Regression: an account with password_hash must not authenticate via Google
    OAuth even if the email matches.  Allowing it would let email/password
    credentials bypass the social-only requirement.
    """
    from app.core.security import hash_password

    _make_user(
        db,
        "ep_user@test.com",
        status="active",
        password_hash=hash_password("secret"),
    )
    id_info = _mock_google_id_info("ep_user@test.com")
    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post("/auth/google-login", json={"id_token": "fake-token"})
    assert resp.status_code == 403, (
        f"email/password account must not authenticate via Google (got {resp.status_code})"
    )
