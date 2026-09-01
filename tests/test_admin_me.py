"""Tests for GET /admin/me."""
import pytest

from app.core.security import create_access_token
from app.models.user import User


def _make_user(db, email="user@admin-test.com", is_system_admin=False):
    user = User(email=email, name="Test User", password_hash="x",
                is_system_admin=is_system_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def test_admin_me_returns_200_for_system_admin(client, db):
    user = _make_user(db, email="admin@example.com", is_system_admin=True)
    resp = client.get("/admin/me", headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user.id
    assert data["email"] == "admin@example.com"
    assert data["name"] == "Test User"


def test_admin_me_does_not_expose_password_or_sensitive_fields(client, db):
    user = _make_user(db, email="admin2@example.com", is_system_admin=True)
    resp = client.get("/admin/me", headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert "password_hash" not in data
    assert "password" not in data
    assert set(data.keys()) == {"id", "email", "name"}


def test_admin_me_returns_403_for_non_admin(client, db):
    user = _make_user(db, email="regular@example.com", is_system_admin=False)
    resp = client.get("/admin/me", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_me_returns_401_for_unauthenticated(client, db):
    resp = client.get("/admin/me")
    assert resp.status_code == 401
