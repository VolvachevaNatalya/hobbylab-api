"""
Tests for GET/POST/DELETE /me/auth-providers/ (provider management API).
"""
import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from jose import jwt

from app.core.security import create_access_token, ALGORITHM
from app.core.auth import SECRET_KEY
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(db, email: str, status: str = "active") -> User:
    u = User(email=email, name="Test User", password_hash=None, status=status)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _add_provider(db, user: User, provider: str, provider_user_id: str, provider_email: str = "") -> UserAuthProvider:
    ap = UserAuthProvider(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        provider_email=provider_email or None,
    )
    db.add(ap)
    db.commit()
    db.refresh(ap)
    return ap


def _bearer(user_id: int) -> dict:
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def _old_bearer(user_id: int, age_seconds: int = 1800) -> dict:
    """Create an access token with iat set to age_seconds ago (simulates stale token)."""
    iat = int(time.time()) - age_seconds
    payload = {
        "user_id": user_id,
        "iat": iat,
        "exp": int(time.time()) + 3600,
        "type": "access",
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


# ── List providers ─────────────────────────────────────────────────────────────

def test_list_providers_empty(client, db):
    user = _make_user(db, "list_empty@test.com")
    resp = client.get("/me/auth-providers/", headers=_bearer(user.id))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_providers_returns_linked(client, db):
    user = _make_user(db, "list_one@test.com")
    _add_provider(db, user, "google", "gsub1", "list_one@test.com")
    resp = client.get("/me/auth-providers/", headers=_bearer(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["provider"] == "google"
    assert body[0]["provider_email"] == "list_one@test.com"


def test_list_providers_requires_auth(client):
    resp = client.get("/me/auth-providers/")
    assert resp.status_code == 401


# ── Link Google ────────────────────────────────────────────────────────────────

def test_link_google_success(client, db):
    user = _make_user(db, "link_g@test.com")
    id_info = {"sub": "gsub_link", "email": "link_g@test.com", "name": "Link G", "email_verified": True}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post(
            "/me/auth-providers/google",
            json={"id_token": "fake"},
            headers=_bearer(user.id),
        )

    assert resp.status_code == 200
    assert resp.json()["provider"] == "google"

    ap = db.query(UserAuthProvider).filter_by(user_id=user.id, provider="google").first()
    assert ap is not None
    assert ap.provider_user_id == "gsub_link"


def test_link_google_unverified_email_rejected(client, db):
    user = _make_user(db, "link_g_unv@test.com")
    id_info = {"sub": "gsub_unv", "email": "link_g_unv@test.com", "name": "G", "email_verified": False}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post(
            "/me/auth-providers/google",
            json={"id_token": "fake"},
            headers=_bearer(user.id),
        )

    assert resp.status_code == 400


def test_link_google_duplicate_rejected(client, db):
    user = _make_user(db, "link_g_dup@test.com")
    _add_provider(db, user, "google", "gsub_dup")
    id_info = {"sub": "gsub_dup", "email": "link_g_dup@test.com", "name": "G", "email_verified": True}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post(
            "/me/auth-providers/google",
            json={"id_token": "fake"},
            headers=_bearer(user.id),
        )

    assert resp.status_code == 200  # idempotent


def test_link_google_already_owned_by_other_user(client, db):
    owner = _make_user(db, "owner@test.com")
    _add_provider(db, owner, "google", "gsub_owned")
    requester = _make_user(db, "requester@test.com")

    id_info = {"sub": "gsub_owned", "email": "requester@test.com", "name": "R", "email_verified": True}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post(
            "/me/auth-providers/google",
            json={"id_token": "fake"},
            headers=_bearer(requester.id),
        )

    assert resp.status_code == 409


# ── Link Facebook ──────────────────────────────────────────────────────────────

def test_link_facebook_success(client, db):
    user = _make_user(db, "link_fb@test.com")
    fb_data = {"id": "fb123", "name": "FB User", "email": "link_fb@test.com"}

    with patch("app.api.auth._validate_facebook_token", return_value=fb_data):
        resp = client.post(
            "/me/auth-providers/facebook",
            json={"access_token": "fake-fb"},
            headers=_bearer(user.id),
        )

    assert resp.status_code == 200
    assert resp.json()["provider"] == "facebook"


# ── Link Apple ─────────────────────────────────────────────────────────────────

def test_link_apple_success(client, db):
    user = _make_user(db, "link_apple@test.com")
    apple_claims = {"sub": "apple_sub_1", "email": "link_apple@test.com", "email_verified": True}

    with patch("app.api.auth._validate_apple_token", return_value=apple_claims):
        resp = client.post(
            "/me/auth-providers/apple",
            json={"id_token": "fake-apple", "nonce": "dummy-nonce"},
            headers=_bearer(user.id),
        )

    assert resp.status_code == 200
    assert resp.json()["provider"] == "apple"


def test_link_apple_unverified_email_stored_as_null(client, db):
    user = _make_user(db, "link_apple_pv@test.com")
    apple_claims = {"sub": "apple_sub_pv", "email": "private@privaterelay.appleid.com", "email_verified": False}

    with patch("app.api.auth._validate_apple_token", return_value=apple_claims):
        resp = client.post(
            "/me/auth-providers/apple",
            json={"id_token": "fake-apple", "nonce": "dummy-nonce"},
            headers=_bearer(user.id),
        )

    assert resp.status_code == 200
    ap = db.query(UserAuthProvider).filter_by(user_id=user.id, provider="apple").first()
    assert ap is not None
    assert ap.provider_email is None


# ── Unlink ─────────────────────────────────────────────────────────────────────

def test_unlink_provider_success(client, db):
    user = _make_user(db, "unlink@test.com")
    ap1 = _add_provider(db, user, "google", "gsub_unlink")
    ap2 = _add_provider(db, user, "facebook", "fb_unlink")

    resp = client.delete(
        f"/me/auth-providers/{ap1.id}",
        headers=_bearer(user.id),
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "unlinked"
    db.expire_all()
    assert db.query(UserAuthProvider).filter_by(id=ap1.id).first() is None
    assert db.query(UserAuthProvider).filter_by(id=ap2.id).first() is not None


def test_unlink_last_provider_rejected(client, db):
    user = _make_user(db, "unlink_last@test.com")
    ap = _add_provider(db, user, "google", "gsub_last")

    resp = client.delete(
        f"/me/auth-providers/{ap.id}",
        headers=_bearer(user.id),
    )

    assert resp.status_code == 400
    assert "last" in resp.json()["detail"].lower()


def test_unlink_bumps_token_version(client, db):
    user = _make_user(db, "tv_bump@test.com")
    ap1 = _add_provider(db, user, "google", "gsub_tv1")
    ap2 = _add_provider(db, user, "facebook", "fb_tv1")

    old_tv = user.token_version or 0

    resp = client.delete(
        f"/me/auth-providers/{ap1.id}",
        headers=_bearer(user.id),
    )

    assert resp.status_code == 200
    db.refresh(user)
    assert (user.token_version or 0) == old_tv + 1


def test_unlink_other_users_provider_rejected(client, db):
    owner = _make_user(db, "owner_prov@test.com")
    ap = _add_provider(db, owner, "google", "gsub_owner")
    _add_provider(db, owner, "facebook", "fb_owner")
    attacker = _make_user(db, "attacker@test.com")

    resp = client.delete(
        f"/me/auth-providers/{ap.id}",
        headers=_bearer(attacker.id),
    )

    assert resp.status_code == 404


def test_unlink_requires_auth(client, db):
    user = _make_user(db, "unlink_noauth@test.com")
    ap = _add_provider(db, user, "google", "gsub_noauth")
    _add_provider(db, user, "facebook", "fb_noauth")

    resp = client.delete(f"/me/auth-providers/{ap.id}")
    assert resp.status_code == 401


# ── Re-authentication requirement ─────────────────────────────────────────────

def test_unlink_requires_recent_auth(client, db):
    """DELETE /me/auth-providers/{id} with a stale (>15 min old) token must return 403."""
    user = _make_user(db, "unlink_reauth@test.com")
    ap1 = _add_provider(db, user, "google", "gsub_reauth")
    _add_provider(db, user, "facebook", "fb_reauth")

    resp = client.delete(
        f"/me/auth-providers/{ap1.id}",
        headers=_old_bearer(user.id, age_seconds=1800),
    )
    assert resp.status_code == 403
    assert "re-authentication" in resp.json()["detail"].lower()


def test_unlink_allows_recent_token(client, db):
    """DELETE with a fresh token must succeed (re-auth check passes)."""
    user = _make_user(db, "unlink_fresh@test.com")
    ap1 = _add_provider(db, user, "google", "gsub_fresh")
    _add_provider(db, user, "facebook", "fb_fresh")

    resp = client.delete(
        f"/me/auth-providers/{ap1.id}",
        headers=_bearer(user.id),
    )
    assert resp.status_code == 200


def test_link_google_requires_recent_auth(client, db):
    """POST /me/auth-providers/google with stale token must return 403."""
    user = _make_user(db, "link_reauth@test.com")
    id_info = {"sub": "gsub_reauth_link", "email": "link_reauth@test.com", "name": "G", "email_verified": True}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post(
            "/me/auth-providers/google",
            json={"id_token": "fake"},
            headers=_old_bearer(user.id, age_seconds=1800),
        )

    assert resp.status_code == 403
    assert "re-authentication" in resp.json()["detail"].lower()


def test_link_google_missing_iat_requires_reauth(client, db):
    """POST with token that has no 'iat' claim must return 403."""
    user = _make_user(db, "link_noiat@test.com")
    # Craft a token with no iat
    payload = {
        "user_id": user.id,
        "exp": int(time.time()) + 3600,
        "type": "access",
        "tv": 0,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    id_info = {"sub": "gsub_noiat", "email": "link_noiat@test.com", "name": "G", "email_verified": True}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post(
            "/me/auth-providers/google",
            json={"id_token": "fake"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 403


# ── Session invalidation after unlink ─────────────────────────────────────────

def test_unlink_invalidates_existing_access_token(client, db):
    """After unlinking a provider (which bumps token_version), old access tokens must be rejected."""
    user = _make_user(db, "tv_invalidate@test.com")
    ap1 = _add_provider(db, user, "google", "gsub_tv_inv")
    _add_provider(db, user, "facebook", "fb_tv_inv")

    # Issue an access token now
    old_token = create_access_token({"user_id": user.id, "tv": user.token_version or 0})
    old_headers = {"Authorization": f"Bearer {old_token}"}

    # Token works before unlink
    resp_before = client.get("/me/auth-providers/", headers=old_headers)
    assert resp_before.status_code == 200

    # Unlink — bumps token_version
    resp_unlink = client.delete(
        f"/me/auth-providers/{ap1.id}",
        headers=_bearer(user.id),
    )
    assert resp_unlink.status_code == 200

    # Old token must now be rejected
    resp_after = client.get("/me/auth-providers/", headers=old_headers)
    assert resp_after.status_code == 401


# ── email_verified absent = not verified ──────────────────────────────────────

def test_google_login_email_verified_absent_rejected(client, db):
    """Google token with no email_verified claim must be rejected (absent != True)."""
    # No email_verified key in id_info at all
    id_info = {"sub": "gsub_noev", "email": "noev@test.com", "name": "G"}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post("/auth/google-login", json={"id_token": "fake"})

    assert resp.status_code == 400
    assert "verified" in resp.json()["detail"].lower()


def test_link_google_email_verified_absent_rejected(client, db):
    """Link Google with absent email_verified claim must be rejected."""
    user = _make_user(db, "link_noev@test.com")
    id_info = {"sub": "gsub_link_noev", "email": "link_noev@test.com", "name": "G"}

    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        resp = client.post(
            "/me/auth-providers/google",
            json={"id_token": "fake"},
            headers=_bearer(user.id),
        )

    assert resp.status_code == 400


# ── Facebook token expiration ─────────────────────────────────────────────────

def test_facebook_expired_token_rejected(client, db):
    """Facebook debug_token response with past expires_at must be rejected."""
    import os
    past_expires = int(time.time()) - 3600  # 1 hour ago

    with patch.dict(os.environ, {"FACEBOOK_APP_ID": "fake-app-id", "FACEBOOK_APP_SECRET": "fake-secret"}), \
         patch("httpx.get") as mock_get:

        mock_debug_resp = type("R", (), {
            "status_code": 200,
            "json": lambda self: {
                "data": {
                    "is_valid": True,
                    "app_id": "fake-app-id",
                    "user_id": "fb_exp_test",
                    "expires_at": past_expires,
                }
            },
        })()
        mock_get.return_value = mock_debug_resp

        resp = client.post("/auth/facebook-login", json={"access_token": "fake-fb"})

    assert resp.status_code == 401


# ── Apple nonce ───────────────────────────────────────────────────────────────

import hashlib as _hashlib


def _apple_mock_valid(apple_sub="apple_nonce_sub", email="nonce@test.com", extra_claims=None):
    """Return minimal valid Apple claims dict."""
    claims = {
        "sub": apple_sub,
        "email": email,
        "email_verified": True,
        "iss": "https://appleid.apple.com",
        "aud": "il.co.hobbylab.app",
    }
    if extra_claims:
        claims.update(extra_claims)
    return claims


def _apple_patch(claims):
    """Context manager that patches both header decode and JWT decode for Apple tests."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("app.api.auth._get_apple_public_key", return_value={"kty": "RSA"}))
    stack.enter_context(patch("jose.jwt.get_unverified_header", return_value={"kid": "fake-kid", "alg": "RS256"}))
    stack.enter_context(patch("jose.jwt.decode", return_value=claims))
    return stack


def test_apple_login_no_nonce_rejected(client, db):
    """Login without nonce field is rejected (nonce is now required)."""
    with _apple_patch(_apple_mock_valid()):
        resp = client.post("/auth/apple-login", json={"id_token": "fake-apple"})
    assert resp.status_code == 422


def test_apple_login_nonce_valid(client, db):
    """Login with matching nonce is accepted."""
    raw_nonce = "my-secret-nonce-value"
    nonce_hash = _hashlib.sha256(raw_nonce.encode()).hexdigest()
    claims = _apple_mock_valid(extra_claims={"nonce": nonce_hash})

    with _apple_patch(claims):
        resp = client.post("/auth/apple-login", json={"id_token": "fake-apple", "nonce": raw_nonce})
    assert resp.status_code == 200


def test_apple_login_nonce_mismatch_rejected(client, db):
    """Login with wrong raw_nonce is rejected (sha256 mismatch)."""
    correct_nonce = "correct-nonce"
    nonce_hash = _hashlib.sha256(correct_nonce.encode()).hexdigest()
    claims = _apple_mock_valid(extra_claims={"nonce": nonce_hash})

    with _apple_patch(claims):
        resp = client.post("/auth/apple-login", json={"id_token": "fake-apple", "nonce": "wrong-nonce"})
    assert resp.status_code == 400
    assert "nonce mismatch" in resp.json()["detail"].lower()


def test_apple_login_nonce_missing_from_token_rejected(client, db):
    """Client sends nonce but token has no nonce claim — rejected."""
    claims = _apple_mock_valid()  # no nonce claim

    with _apple_patch(claims):
        resp = client.post("/auth/apple-login", json={"id_token": "fake-apple", "nonce": "some-nonce"})
    assert resp.status_code == 400
    assert "missing nonce" in resp.json()["detail"].lower()


def test_apple_login_no_nonce_field_rejected_422(client, db):
    """Missing nonce field is rejected at request validation — 422 regardless of token contents."""
    claims = _apple_mock_valid(extra_claims={"nonce": "some-hash"})

    with _apple_patch(claims):
        resp = client.post("/auth/apple-login", json={"id_token": "fake-apple"})
    assert resp.status_code == 422


def test_apple_link_nonce_forwarded_to_validator(client, db):
    """Link Apple endpoint forwards the nonce field to _validate_apple_token."""
    user = _make_user(db, "link_apple_nonce@test.com")
    raw_nonce = "link-nonce-value"
    nonce_hash = _hashlib.sha256(raw_nonce.encode()).hexdigest()
    received_nonce = []

    def _mock_validate(id_token, ip="unknown", nonce=None):
        received_nonce.append(nonce)
        return _apple_mock_valid(apple_sub="apple_link_nonce", extra_claims={"nonce": nonce_hash})

    with patch("app.api.auth._validate_apple_token", side_effect=_mock_validate):
        resp = client.post(
            "/me/auth-providers/apple",
            json={"id_token": "fake-apple", "nonce": raw_nonce},
            headers=_bearer(user.id),
        )
    assert resp.status_code == 200
    assert received_nonce == [raw_nonce], "nonce was not forwarded to _validate_apple_token"


def test_apple_link_nonce_mismatch_rejected(client, db):
    """Link Apple provider: nonce mismatch from validator surfaces as 400."""
    from fastapi import HTTPException as _HTTPException
    user = _make_user(db, "link_apple_nonce_bad@test.com")

    def _mock_validate_bad(id_token, ip="unknown", nonce=None):
        raise _HTTPException(status_code=400, detail="Apple nonce mismatch")

    with patch("app.api.auth._validate_apple_token", side_effect=_mock_validate_bad):
        resp = client.post(
            "/me/auth-providers/apple",
            json={"id_token": "fake-apple", "nonce": "wrong-nonce"},
            headers=_bearer(user.id),
        )
    assert resp.status_code == 400
    assert "nonce mismatch" in resp.json()["detail"].lower()


def test_apple_login_empty_nonce_rejected(client, db):
    """Empty string nonce passes Pydantic validation but is rejected by _validate_apple_token."""
    nonce_hash = _hashlib.sha256("valid-nonce".encode()).hexdigest()
    claims = _apple_mock_valid(extra_claims={"nonce": nonce_hash})

    with _apple_patch(claims):
        resp = client.post("/auth/apple-login", json={"id_token": "fake-apple", "nonce": ""})
    assert resp.status_code == 400
    assert "nonce is required" in resp.json()["detail"].lower()


def test_apple_link_no_nonce_field_rejected(client, db):
    """Link Apple without nonce field is rejected at request validation — 422."""
    user = _make_user(db, "link_apple_nononce@test.com")
    with patch("app.api.auth._validate_apple_token", return_value=_apple_mock_valid()):
        resp = client.post(
            "/me/auth-providers/apple",
            json={"id_token": "fake-apple"},
            headers=_bearer(user.id),
        )
    assert resp.status_code == 422


# ── Last-provider locking (serial behavior, SQLite) ───────────────────────────

def test_unlink_last_provider_blocked_with_lock(client, db):
    """Serial delete: first delete succeeds; second delete with fresh token returns 400."""
    user = _make_user(db, "serial_unlink@test.com")
    ap1 = _add_provider(db, user, "google", "gsub_serial")
    ap2 = _add_provider(db, user, "facebook", "fb_serial")

    # First unlink: should succeed (2 → 1), bumps token_version
    r1 = client.delete(f"/me/auth-providers/{ap1.id}", headers=_bearer(user.id))
    assert r1.status_code == 200

    # Fetch updated token_version and issue a fresh token
    db.expire_all()
    db.refresh(user)
    new_tv = user.token_version or 0
    fresh_token = create_access_token({"user_id": user.id, "tv": new_tv})
    fresh_headers = {"Authorization": f"Bearer {fresh_token}"}

    # Second unlink: last provider, must be blocked
    r2 = client.delete(f"/me/auth-providers/{ap2.id}", headers=fresh_headers)
    assert r2.status_code == 400
    assert "last" in r2.json()["detail"].lower()


def test_unlink_other_user_provider_not_found_after_lock(client, db):
    """Cannot delete a provider that belongs to another user (ownership check via locked set)."""
    owner = _make_user(db, "owner_lock@test.com")
    ap_owner = _add_provider(db, owner, "google", "gsub_lock_owner")
    _add_provider(db, owner, "facebook", "fb_lock_owner")

    attacker = _make_user(db, "attacker_lock@test.com")
    # ap_owner is not in attacker's locked set → 404
    resp = client.delete(f"/me/auth-providers/{ap_owner.id}", headers=_bearer(attacker.id))
    assert resp.status_code == 404
