"""
Auth/authorization verification for payment endpoints.

All four payment endpoints already require `Depends(require_system_admin)`:
  GET  /payments/
  GET  /payments/{id}
  POST /payments/
  PUT  /payments/{id}

These tests confirm that:
  1. Unauthenticated requests are rejected with 401.
  2. Authenticated non-admin requests are rejected with 403.
  3. Admin access is accepted (200/201).

No changes were required to payments.py — this file documents the ALREADY-OK
state found during the MVP Block 1 audit.
"""
from app.core.security import create_access_token
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False, provider="google", pid=None):
    pid = pid or f"google_{email}"
    u = User(
        email=email,
        name="Test",
        password_hash=None,
        status="active",
        provider=provider,
        provider_user_id=pid,
        is_system_admin=is_system_admin,
        token_version=0,
    )
    db.add(u)
    db.flush()
    db.add(UserAuthProvider(user_id=u.id, provider=provider, provider_user_id=pid, provider_email=email))
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    token = create_access_token({"user_id": user.id, "tv": user.token_version or 0})
    return {"Authorization": f"Bearer {token}"}


# ── unauthenticated ────────────────────────────────────────────────────────────

def test_list_payments_requires_auth(client, db):
    resp = client.get("/payments/")
    assert resp.status_code == 401


def test_get_payment_requires_auth(client, db):
    resp = client.get("/payments/1")
    assert resp.status_code == 401


def test_create_payment_requires_auth(client, db):
    resp = client.post("/payments/", json={})
    assert resp.status_code == 401


def test_update_payment_requires_auth(client, db):
    resp = client.put("/payments/1", json={})
    assert resp.status_code == 401


# ── non-admin authenticated ────────────────────────────────────────────────────

def test_list_payments_rejects_non_admin(client, db):
    user = _make_user(db, "pay_nonadmin_list@test.com")
    resp = client.get("/payments/", headers=_auth(user))
    assert resp.status_code == 403


def test_get_payment_rejects_non_admin(client, db):
    user = _make_user(db, "pay_nonadmin_get@test.com")
    resp = client.get("/payments/1", headers=_auth(user))
    assert resp.status_code == 403


def test_create_payment_rejects_non_admin(client, db):
    user = _make_user(db, "pay_nonadmin_post@test.com")
    resp = client.post("/payments/", json={}, headers=_auth(user))
    assert resp.status_code == 403


def test_update_payment_rejects_non_admin(client, db):
    user = _make_user(db, "pay_nonadmin_put@test.com")
    resp = client.put("/payments/1", json={}, headers=_auth(user))
    assert resp.status_code == 403


# ── admin authenticated ────────────────────────────────────────────────────────

def test_list_payments_allows_admin(client, db):
    admin = _make_user(db, "pay_admin_list@test.com", is_system_admin=True, pid="google_admin_list")
    resp = client.get("/payments/", headers=_auth(admin))
    # 200 (possibly empty list) — not 401 or 403
    assert resp.status_code == 200


def test_get_payment_admin_gets_404_not_403(client, db):
    """Admin user hitting a non-existent payment ID should get 404, not auth error."""
    admin = _make_user(db, "pay_admin_get@test.com", is_system_admin=True, pid="google_admin_get")
    resp = client.get("/payments/999999", headers=_auth(admin))
    assert resp.status_code in (200, 404)
    assert resp.status_code != 403
