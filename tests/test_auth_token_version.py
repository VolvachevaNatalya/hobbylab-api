"""
Regression tests for token version (tv) — P2 security finding:
"password change does not invalidate previously issued JWTs."

The token_version column is incremented whenever the user's session should be
globally invalidated (e.g. by an admin action or account recovery).  Every
issued token carries a "tv" claim matching the user's token_version.
get_current_user and decode_refresh_token reject tokens whose "tv" value does
not match the user's current token_version.

Tokens without a "tv" claim (legacy tokens) default to tv=0 and remain valid
as long as the user's token_version is also 0.

Note: the /auth/change-password endpoint has been removed (social-only auth).
Token version increment is now an admin/server-side operation.  The tv
enforcement tests below use direct DB manipulation to simulate a version change.
"""
import pytest
from jose import jwt

from app.core.auth import ALGORITHM
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
)
from app.models.user import User

_JWT_SECRET = "pytest-test-secret-key"
_REFRESH_URL = "/auth/refresh"
_PROTECTED_URL = "/admin/me"


def _make_user(db, email, is_admin=False):
    u = User(
        email=email,
        name="TV Test",
        password_hash=None,
        status="active",
        is_system_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user_id: int, tv: int = 0) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id, 'tv': tv})}"}


# ── Default token_version ─────────────────────────────────────────────────────

def test_new_user_has_token_version_zero(db):
    """token_version must default to 0 for every new user."""
    u = _make_user(db, "tv_zero@test.com")
    db.refresh(u)
    assert (u.token_version or 0) == 0


def test_token_with_tv_zero_valid_for_new_user(client, db):
    """A token with tv=0 must work for a user who has never had their version bumped."""
    u = _make_user(db, "tv_v0@test.com")
    resp = client.get(_PROTECTED_URL, headers=_auth(u.id, tv=0))
    # This user is not an admin so we expect 403 (not 401).
    # 401 would mean the token was rejected; 403 means it was accepted but
    # the user lacks permission — both confirm the token is valid.
    assert resp.status_code != 401


# ── Legacy tokens (no tv claim) ───────────────────────────────────────────────

def test_legacy_token_without_tv_works_for_user_with_version_zero(client, db):
    """
    Tokens issued before the tv claim was added have no "tv" key.
    They must still work as long as the user has never had their version bumped
    (token_version=0, default to 0 == 0).
    """
    admin = _make_user(db, "tv_leg@test.com", is_admin=True)
    legacy_token = create_access_token({"user_id": admin.id})  # no tv
    resp = client.get(
        _PROTECTED_URL,
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert resp.status_code == 200


# ── Token version mismatch ────────────────────────────────────────────────────

def test_access_token_with_mismatched_version_rejected(client, db):
    """
    A token with tv=0 is rejected when user.token_version=1, regardless of
    how the version was incremented (simulates any version mismatch).
    """
    admin = _make_user(db, "tv_mismatch@test.com", is_admin=True)
    admin.token_version = 1
    db.commit()

    stale_token_headers = _auth(admin.id, tv=0)
    resp = client.get(_PROTECTED_URL, headers=stale_token_headers)
    assert resp.status_code == 401


def test_token_with_current_version_accepted_after_bump(client, db):
    """After a version bump, a fresh token carrying the new tv is accepted."""
    admin = _make_user(db, "tv_fresh@test.com", is_admin=True)
    admin.token_version = 1
    db.commit()

    fresh_token_headers = _auth(admin.id, tv=1)
    resp = client.get(_PROTECTED_URL, headers=fresh_token_headers)
    assert resp.status_code == 200


def test_refresh_token_with_mismatched_version_rejected(client, db):
    """A refresh token with stale tv must be rejected at /auth/refresh."""
    u = _make_user(db, "tv_ref_mismatch@test.com")
    old_refresh = create_refresh_token({"user_id": u.id, "tv": 0})

    # Simulate a server-side session invalidation.
    u.token_version = 1
    db.commit()

    resp = client.post(_REFRESH_URL, json={"refresh_token": old_refresh})
    assert resp.status_code == 401, (
        "refresh token with stale tv must be rejected after version bump"
    )


# ── Refresh endpoint issues token with correct tv ─────────────────────────────

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
