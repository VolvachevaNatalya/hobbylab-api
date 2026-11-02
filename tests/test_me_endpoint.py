"""
Regression tests for GET /me and PATCH /me.

Finding: PATCH /me returned the raw SQLAlchemy User ORM object, which
FastAPI serialises to JSON including password_hash and is_system_admin.
Both fields must be absent from every response.
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

_SENSITIVE_FIELDS = {"password_hash", "is_system_admin"}
_EXPECTED_FIELDS = {"id", "email", "name", "phone", "avatar_url", "provider",
                    "provider_user_id", "status", "created_at"}


def _make_user(db, email="me_test@test.com", name="Me User", password="pw123",
               is_admin=False, status="active"):
    u = User(
        email=email,
        name=name,
        password_hash=hash_password(password),
        is_system_admin=is_admin,
        status=status,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


# ── GET /me ───────────────────────────────────────────────────────────────────

def test_get_me_requires_auth(client, db):
    assert client.get("/me").status_code == 401


def test_get_me_returns_expected_fields(client, db):
    user = _make_user(db)
    resp = client.get("/me", headers=_auth(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user.id
    assert body["email"] == user.email
    assert body["name"] == user.name


def test_get_me_does_not_expose_password_hash(client, db):
    user = _make_user(db, email="getsafe@test.com")
    resp = client.get("/me", headers=_auth(user.id))
    assert resp.status_code == 200
    body = resp.json()
    for field in _SENSITIVE_FIELDS:
        assert field not in body, f"GET /me must not expose {field}"


# ── PATCH /me — sensitive-field regression ───────────────────────────────────

def test_patch_me_requires_auth(client, db):
    assert client.patch("/me", json={"name": "Hacker"}).status_code == 401


def test_patch_me_does_not_expose_password_hash(client, db):
    """
    Regression: before the fix, PATCH /me returned the raw ORM object which
    included password_hash in the JSON response.
    """
    user = _make_user(db, email="patchsafe@test.com")
    resp = client.patch("/me", json={"name": "New Name"}, headers=_auth(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert "password_hash" not in body, "PATCH /me must never return password_hash"


def test_patch_me_does_not_expose_is_system_admin(client, db):
    """is_system_admin is an internal flag and must not appear in user-facing responses."""
    user = _make_user(db, email="patchadmin@test.com", is_admin=True)
    resp = client.patch("/me", json={"name": "Updated"}, headers=_auth(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert "is_system_admin" not in body, "PATCH /me must never return is_system_admin"


def test_patch_me_returns_all_expected_fields(client, db):
    user = _make_user(db, email="patchfields@test.com")
    resp = client.patch("/me", json={"name": "Updated Name"}, headers=_auth(user.id))
    assert resp.status_code == 200
    body = resp.json()
    for field in _EXPECTED_FIELDS:
        assert field in body, f"PATCH /me must include {field}"


def test_patch_me_name_update_persists(client, db):
    user = _make_user(db, email="nameupdate@test.com", name="Old Name")
    resp = client.patch("/me", json={"name": "New Name"}, headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"

    # Confirm the GET also reflects the change.
    get_resp = client.get("/me", headers=_auth(user.id))
    assert get_resp.json()["name"] == "New Name"


def test_patch_me_phone_update(client, db):
    user = _make_user(db, email="phoneupdate@test.com")
    resp = client.patch("/me", json={"phone": "+972501234567"}, headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["phone"] == "+972501234567"


def test_patch_me_avatar_update(client, db):
    user = _make_user(db, email="avatarupdate@test.com")
    url = "https://static.hobbylab.co.il/abc.jpg"
    resp = client.patch("/me", json={"avatar_url": url}, headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["avatar_url"] == url


def test_patch_me_partial_update_preserves_other_fields(client, db):
    user = _make_user(db, email="partial@test.com", name="Original Name")
    resp = client.patch("/me", json={"phone": "050-000-0000"}, headers=_auth(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Original Name"
    assert body["phone"] == "050-000-0000"
