"""Tests for access/refresh token mechanics."""
from datetime import datetime, timedelta

import pytest
from jose import jwt

from app.core.security import (
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    hash_password,
)
from app.models.user import User

_JWT_SECRET = "pytest-test-secret-key"  # matches conftest DATABASE_URL env

_LOGIN_URL = "/auth/login"
_REFRESH_URL = "/auth/refresh"
_PROTECTED_URL = "/admin/me"  # requires valid access token + is_system_admin


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="tok@x.com", password="pass123", is_admin=False):
    u = User(
        email=email,
        name="Token Test",
        password_hash=hash_password(password),
        is_system_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client, email, password):
    return client.post(
        _LOGIN_URL,
        data={"username": email, "password": password},
    )


def _expired_token(user_id: int, token_type: str) -> str:
    """Create a token that expired 1 second ago."""
    payload = {
        "user_id": user_id,
        "type": token_type,
        "exp": datetime.utcnow() - timedelta(seconds=1),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=ALGORITHM)


def _legacy_access_token(user_id: int) -> str:
    """Simulate a pre-refresh-token access token: no 'type' claim."""
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(hours=12),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=ALGORITHM)


# ═══════════════════════════════════════════════════════════════════════════════
# Login response shape
# ═══════════════════════════════════════════════════════════════════════════════

def test_login_returns_access_token(client, db):
    _make_user(db, "lt_acc@x.com", "pw1")
    resp = _login(client, "lt_acc@x.com", "pw1")
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_returns_refresh_token(client, db):
    _make_user(db, "lt_ref@x.com", "pw1")
    resp = _login(client, "lt_ref@x.com", "pw1")
    assert resp.status_code == 200
    assert "refresh_token" in resp.json()


def test_login_returns_token_type_bearer(client, db):
    _make_user(db, "lt_typ@x.com", "pw1")
    resp = _login(client, "lt_typ@x.com", "pw1")
    assert resp.json()["token_type"] == "bearer"


def test_login_access_token_has_correct_type_claim(client, db):
    _make_user(db, "lt_atc@x.com", "pw1")
    resp = _login(client, "lt_atc@x.com", "pw1")
    payload = jwt.decode(resp.json()["access_token"], _JWT_SECRET, algorithms=[ALGORITHM])
    assert payload["type"] == "access"


def test_login_refresh_token_has_correct_type_claim(client, db):
    _make_user(db, "lt_rtc@x.com", "pw1")
    resp = _login(client, "lt_rtc@x.com", "pw1")
    payload = jwt.decode(resp.json()["refresh_token"], _JWT_SECRET, algorithms=[ALGORITHM])
    assert payload["type"] == "refresh"


def test_login_refresh_token_has_longer_expiry_than_access(client, db):
    _make_user(db, "lt_exp@x.com", "pw1")
    resp = _login(client, "lt_exp@x.com", "pw1")
    data = resp.json()
    a_exp = jwt.decode(data["access_token"], _JWT_SECRET, algorithms=[ALGORITHM])["exp"]
    r_exp = jwt.decode(data["refresh_token"], _JWT_SECRET, algorithms=[ALGORITHM])["exp"]
    assert r_exp > a_exp


def test_login_refresh_token_approx_30_days(client, db):
    _make_user(db, "lt_30d@x.com", "pw1")
    resp = _login(client, "lt_30d@x.com", "pw1")
    payload = jwt.decode(resp.json()["refresh_token"], _JWT_SECRET, algorithms=[ALGORITHM])
    expected = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    actual = datetime.utcfromtimestamp(payload["exp"])
    assert abs((actual - expected).total_seconds()) < 10


# ═══════════════════════════════════════════════════════════════════════════════
# Access token — normal authentication
# ═══════════════════════════════════════════════════════════════════════════════

def test_access_token_authenticates_protected_endpoint(client, db):
    admin = _make_user(db, "at_auth@x.com", "pw1", is_admin=True)
    token = create_access_token({"user_id": admin.id})
    resp = client.get(_PROTECTED_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_legacy_access_token_without_type_still_works(client, db):
    """Tokens issued before the type claim was added must remain valid."""
    admin = _make_user(db, "at_leg@x.com", "pw1", is_admin=True)
    token = _legacy_access_token(admin.id)
    resp = client.get(_PROTECTED_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Token type separation — refresh token rejected at normal endpoints
# ═══════════════════════════════════════════════════════════════════════════════

def test_refresh_token_cannot_authenticate_normal_endpoint(client, db):
    admin = _make_user(db, "ts_ref@x.com", "pw1", is_admin=True)
    refresh = create_refresh_token({"user_id": admin.id})
    resp = client.get(_PROTECTED_URL, headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401


def test_refresh_token_rejected_on_any_protected_endpoint(client, db):
    """get_current_user rejects refresh tokens before admin check runs."""
    user = _make_user(db, "ts_any@x.com", "pw1")
    refresh = create_refresh_token({"user_id": user.id})
    # Even a non-admin user gets 401 (not 403) because the token type is wrong.
    resp = client.get("/admin/me", headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# POST /auth/refresh
# ═══════════════════════════════════════════════════════════════════════════════

def test_valid_refresh_token_returns_200(client, db):
    user = _make_user(db, "rf_ok@x.com", "pw1")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    assert resp.status_code == 200


def test_valid_refresh_returns_new_access_token(client, db):
    user = _make_user(db, "rf_acc@x.com", "pw1")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    assert "access_token" in resp.json()


def test_valid_refresh_returns_new_refresh_token(client, db):
    user = _make_user(db, "rf_rot@x.com", "pw1")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    assert "refresh_token" in resp.json()


def test_refresh_issues_a_new_refresh_token_for_same_user(client, db):
    """The returned refresh token must be a valid refresh token for the same user."""
    user = _make_user(db, "rf_new@x.com", "pw1")
    old_refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": old_refresh})
    new_refresh = resp.json()["refresh_token"]
    payload = jwt.decode(new_refresh, _JWT_SECRET, algorithms=[ALGORITHM])
    assert payload["type"] == "refresh"
    assert payload["user_id"] == user.id
    # Using the new refresh token must succeed (proving it is independently valid)
    resp2 = client.post(_REFRESH_URL, json={"refresh_token": new_refresh})
    assert resp2.status_code == 200


def test_new_access_token_belongs_to_same_user(client, db):
    user = _make_user(db, "rf_uid@x.com", "pw1")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    payload = jwt.decode(resp.json()["access_token"], _JWT_SECRET, algorithms=[ALGORITHM])
    assert payload["user_id"] == user.id


def test_new_access_token_has_type_access(client, db):
    user = _make_user(db, "rf_typ@x.com", "pw1")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    payload = jwt.decode(resp.json()["access_token"], _JWT_SECRET, algorithms=[ALGORITHM])
    assert payload["type"] == "access"


def test_new_refresh_token_has_type_refresh(client, db):
    user = _make_user(db, "rf_rtyp@x.com", "pw1")
    refresh = create_refresh_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    payload = jwt.decode(resp.json()["refresh_token"], _JWT_SECRET, algorithms=[ALGORITHM])
    assert payload["type"] == "refresh"


def test_refreshed_access_token_works_on_protected_endpoint(client, db):
    admin = _make_user(db, "rf_use@x.com", "pw1", is_admin=True)
    refresh = create_refresh_token({"user_id": admin.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    new_access = resp.json()["access_token"]
    protected = client.get(_PROTECTED_URL, headers={"Authorization": f"Bearer {new_access}"})
    assert protected.status_code == 200


# ── Rejection cases ───────────────────────────────────────────────────────────

def test_access_token_at_refresh_endpoint_returns_401(client, db):
    user = _make_user(db, "rf_rej@x.com", "pw1")
    access = create_access_token({"user_id": user.id})
    resp = client.post(_REFRESH_URL, json={"refresh_token": access})
    assert resp.status_code == 401


def test_legacy_token_without_type_at_refresh_returns_401(client, db):
    """Old tokens without 'type' must not be accepted at /auth/refresh."""
    user = _make_user(db, "rf_leg@x.com", "pw1")
    token = _legacy_access_token(user.id)
    resp = client.post(_REFRESH_URL, json={"refresh_token": token})
    assert resp.status_code == 401


def test_invalid_refresh_token_returns_401(client, db):
    resp = client.post(_REFRESH_URL, json={"refresh_token": "not.a.valid.jwt"})
    assert resp.status_code == 401


def test_expired_refresh_token_returns_401(client, db):
    user = _make_user(db, "rf_exp@x.com", "pw1")
    expired = _expired_token(user.id, "refresh")
    resp = client.post(_REFRESH_URL, json={"refresh_token": expired})
    assert resp.status_code == 401


def test_expired_access_token_at_refresh_returns_401(client, db):
    user = _make_user(db, "rf_expac@x.com", "pw1")
    expired = _expired_token(user.id, "access")
    resp = client.post(_REFRESH_URL, json={"refresh_token": expired})
    assert resp.status_code == 401


def test_refresh_token_for_deleted_user_returns_401(client, db):
    user = _make_user(db, "rf_del@x.com", "pw1")
    uid = user.id
    refresh = create_refresh_token({"user_id": uid})
    db.delete(user)
    db.commit()
    resp = client.post(_REFRESH_URL, json={"refresh_token": refresh})
    assert resp.status_code == 401


def test_refresh_response_does_not_leak_error_details(client, db):
    """401 body must not reveal internal info about why the token failed."""
    resp = client.post(_REFRESH_URL, json={"refresh_token": "garbage"})
    assert resp.status_code == 401
    body = resp.text.lower()
    assert "secret" not in body
    assert "jwt" not in body
    assert "signature" not in body


def test_refresh_missing_body_returns_422(client, db):
    resp = client.post(_REFRESH_URL, json={})
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# Admin auth compatibility
# ═══════════════════════════════════════════════════════════════════════════════

def test_admin_me_still_works_with_access_token(client, db):
    admin = _make_user(db, "adm_compat@x.com", "pw1", is_admin=True)
    token = create_access_token({"user_id": admin.id})
    resp = client.get("/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "adm_compat@x.com"


def test_admin_me_returns_401_with_refresh_token(client, db):
    admin = _make_user(db, "adm_refrej@x.com", "pw1", is_admin=True)
    refresh = create_refresh_token({"user_id": admin.id})
    resp = client.get("/admin/me", headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401
