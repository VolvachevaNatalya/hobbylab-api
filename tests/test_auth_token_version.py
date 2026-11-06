"""
Regression tests for token version (tv) — P2 security finding:
"password change does not invalidate previously issued JWTs."

Root cause: change-password updated password_hash only.  Existing access and
refresh tokens remained valid until their natural expiry (previously 12 hours,
now 60 minutes).

Fix:
  - User.token_version column (default 0, incremented on every password change).
  - Every issued token carries a "tv" claim matching the user's token_version.
  - get_current_user and decode_refresh_token reject tokens whose "tv" value
    does not match the user's current token_version.
  - Tokens without a "tv" claim (legacy tokens) default to tv=0 and remain
    valid as long as the user's token_version is also 0 (i.e., password was
    never changed).
"""
import pytest
from jose import jwt

from app.core.auth import ALGORITHM
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    hash_password,
)
from app.models.user import User

_JWT_SECRET = "pytest-test-secret-key"
_CHANGE_PW_URL = "/auth/change-password"
_REFRESH_URL = "/auth/refresh"
_PROTECTED_URL = "/admin/me"
_LOGIN_URL = "/auth/login"


def _make_user(db, email, password="pass123", is_admin=False):
    u = User(
        email=email,
        name="TV Test",
        password_hash=hash_password(password),
        status="active",
        is_system_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user_id: int, tv: int = 0) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id, 'tv': tv})}"}


def _change_password(client, current_pw, new_pw, headers):
    return client.post(
        _CHANGE_PW_URL,
        json={"current_password": current_pw, "new_password": new_pw},
        headers=headers,
    )


# ── Default token_version ─────────────────────────────────────────────────────

def test_new_user_has_token_version_zero(db):
    """token_version must default to 0 for every new user."""
    u = _make_user(db, "tv_zero@test.com")
    db.refresh(u)
    assert (u.token_version or 0) == 0


def test_token_with_tv_zero_valid_for_new_user(client, db):
    """A token with tv=0 must work for a user who has never changed password."""
    u = _make_user(db, "tv_v0@test.com")
    resp = client.get(_PROTECTED_URL, headers=_auth(u.id, tv=0))
    # This user is not an admin so we expect 403 (not 401).
    # 401 would mean the token was rejected; 403 means it was accepted but
    # the user lacks permission.  Both confirm the token is valid.
    assert resp.status_code != 401


# ── Legacy tokens (no tv claim) ───────────────────────────────────────────────

def test_legacy_token_without_tv_works_for_user_with_version_zero(client, db):
    """
    Tokens issued before the tv claim was added have no "tv" key.
    They must still work as long as the user has never changed password
    (token_version=0, default to 0 == 0).
    """
    admin = _make_user(db, "tv_leg@test.com", is_admin=True)
    legacy_token = create_access_token({"user_id": admin.id})  # no tv
    resp = client.get(
        _PROTECTED_URL,
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert resp.status_code == 200


def test_legacy_token_rejected_after_password_change(client, db):
    """
    Regression: a legacy token (no tv claim, defaults to 0) must be rejected
    after the user changes password (token_version becomes 1).
    """
    admin = _make_user(db, "tv_legpw@test.com", is_admin=True)
    legacy_token = create_access_token({"user_id": admin.id})  # no tv

    _change_password(
        client,
        current_pw="pass123",
        new_pw="newpass456",
        headers=_auth(admin.id, tv=0),
    )
    db.refresh(admin)
    assert (admin.token_version or 0) == 1

    resp = client.get(
        _PROTECTED_URL,
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert resp.status_code == 401


# ── Password change invalidates access tokens ─────────────────────────────────

def test_password_change_increments_token_version(client, db):
    """change-password must increment token_version."""
    u = _make_user(db, "tv_incr@test.com")
    _change_password(client, "pass123", "newpass123", headers=_auth(u.id))
    db.refresh(u)
    assert (u.token_version or 0) == 1


def test_access_token_before_password_change_is_rejected(client, db):
    """
    Regression: an access token issued before a password change must be
    rejected after the change, even though it has not yet expired.
    Before the fix: the old token would be accepted for up to 12 hours.
    """
    admin = _make_user(db, "tv_old@test.com", is_admin=True)
    old_token_headers = _auth(admin.id, tv=0)

    _change_password(client, "pass123", "newpass123", headers=old_token_headers)
    db.refresh(admin)
    assert (admin.token_version or 0) == 1

    resp = client.get(_PROTECTED_URL, headers=old_token_headers)
    assert resp.status_code == 401, (
        "token issued before password change must be rejected after the change"
    )


def test_access_token_with_mismatched_version_rejected(client, db):
    """
    A token with tv=0 is rejected when user.token_version=1, regardless of
    whether change-password was actually called (simulates any version mismatch).
    """
    admin = _make_user(db, "tv_mismatch@test.com", is_admin=True)
    admin.token_version = 1
    db.commit()

    stale_token_headers = _auth(admin.id, tv=0)
    resp = client.get(_PROTECTED_URL, headers=stale_token_headers)
    assert resp.status_code == 401


def test_new_token_after_password_change_is_accepted(client, db):
    """
    After a password change, a fresh login must issue a valid token that
    is accepted on protected endpoints.
    """
    admin = _make_user(db, "tv_new@test.com", password="pass123", is_admin=True)
    old_headers = _auth(admin.id, tv=0)

    _change_password(client, "pass123", "newpass456", headers=old_headers)

    login_resp = client.post(
        _LOGIN_URL,
        data={"username": "tv_new@test.com", "password": "newpass456"},
    )
    assert login_resp.status_code == 200
    new_access = login_resp.json()["access_token"]

    resp = client.get(
        _PROTECTED_URL,
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert resp.status_code == 200


def test_new_token_contains_updated_tv_claim(client, db):
    """
    After a password change and fresh login, the issued access token must
    carry tv=1 (the new token_version), not tv=0.
    """
    u = _make_user(db, "tv_claim@test.com", password="pass123")
    _change_password(client, "pass123", "newpass456", headers=_auth(u.id))

    login_resp = client.post(
        _LOGIN_URL,
        data={"username": "tv_claim@test.com", "password": "newpass456"},
    )
    new_access = login_resp.json()["access_token"]
    payload = jwt.decode(new_access, _JWT_SECRET, algorithms=[ALGORITHM])
    assert payload.get("tv") == 1


# ── Password change invalidates refresh tokens ────────────────────────────────

def test_refresh_token_before_password_change_is_rejected(client, db):
    """
    Regression: a refresh token issued before a password change must be
    rejected when presented to POST /auth/refresh after the change.
    """
    u = _make_user(db, "tv_ref@test.com")
    old_refresh = create_refresh_token({"user_id": u.id, "tv": 0})

    _change_password(client, "pass123", "newpass123", headers=_auth(u.id))
    db.refresh(u)
    assert (u.token_version or 0) == 1

    resp = client.post(_REFRESH_URL, json={"refresh_token": old_refresh})
    assert resp.status_code == 401, (
        "refresh token issued before password change must be rejected after the change"
    )


def test_new_refresh_token_after_password_change_is_accepted(client, db):
    """
    The refresh token issued as part of a successful login after a password
    change must be accepted.
    """
    u = _make_user(db, "tv_newref@test.com", password="pass123")
    _change_password(client, "pass123", "newpass456", headers=_auth(u.id))

    login_resp = client.post(
        _LOGIN_URL,
        data={"username": "tv_newref@test.com", "password": "newpass456"},
    )
    new_refresh = login_resp.json()["refresh_token"]

    resp = client.post(_REFRESH_URL, json={"refresh_token": new_refresh})
    assert resp.status_code == 200


# ── Token version in issued tokens ────────────────────────────────────────────

def test_login_token_carries_tv_claim(client, db):
    """POST /auth/login must issue tokens with a tv claim."""
    _make_user(db, "tv_login@test.com", password="pass123")
    login_resp = client.post(
        _LOGIN_URL,
        data={"username": "tv_login@test.com", "password": "pass123"},
    )
    assert login_resp.status_code == 200
    payload = jwt.decode(
        login_resp.json()["access_token"], _JWT_SECRET, algorithms=[ALGORITHM]
    )
    assert "tv" in payload
    assert payload["tv"] == 0


def test_refresh_endpoint_issues_token_with_tv(client, db):
    """POST /auth/refresh must carry tv in the new access token."""
    u = _make_user(db, "tv_refreshed@test.com")
    old_refresh = create_refresh_token({"user_id": u.id, "tv": 0})
    resp = client.post(_REFRESH_URL, json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    payload = jwt.decode(
        resp.json()["access_token"], _JWT_SECRET, algorithms=[ALGORITHM]
    )
    assert "tv" in payload
    assert payload["tv"] == 0


# ── Access token expiry (reduced from 720 → 60 minutes) ──────────────────────

def test_access_token_lifetime_is_60_minutes(db):
    """
    ACCESS_TOKEN_EXPIRE_MINUTES must be 60.
    Reducing from 720 minutes (12 h) to 60 minutes shrinks the attack window
    for stolen tokens from 12 hours to 1 hour.
    """
    assert ACCESS_TOKEN_EXPIRE_MINUTES == 60
