"""
Authorization regression tests for /payments/ endpoints.

All four endpoints are restricted to system admins until a real payment
provider is integrated. Flutter makes no calls to these endpoints.
"""
from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.payment import Payment
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db):
    o = Organization(name="Test Org", status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_payment(db, org_id):
    p = Payment(organization_id=org_id, amount=99.00, status="pending")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


_CREATE_PAYLOAD = {"organization_id": 1, "amount": 50.0}


# ── Unauthenticated requests → 401 ───────────────────────────────────────────

def test_list_payments_unauthenticated(client):
    assert client.get("/payments/").status_code == 401


def test_get_payment_unauthenticated(client):
    assert client.get("/payments/1").status_code == 401


def test_create_payment_unauthenticated(client):
    assert client.post("/payments/", json=_CREATE_PAYLOAD).status_code == 401


def test_update_payment_unauthenticated(client):
    assert client.put("/payments/1", json={"status": "paid"}).status_code == 401


# ── Authenticated non-admin requests → 403 ───────────────────────────────────

def test_list_payments_non_admin(client, db):
    user = _make_user(db, "user@test.com")
    assert client.get("/payments/", headers=_auth(user.id)).status_code == 403


def test_get_payment_non_admin(client, db):
    user = _make_user(db, "user@test.com")
    assert client.get("/payments/1", headers=_auth(user.id)).status_code == 403


def test_create_payment_non_admin(client, db):
    user = _make_user(db, "user@test.com")
    org = _make_org(db)
    resp = client.post(
        "/payments/",
        json={"organization_id": org.id, "amount": 50.0},
        headers=_auth(user.id),
    )
    assert resp.status_code == 403


def test_update_payment_non_admin(client, db):
    user = _make_user(db, "user@test.com")
    assert client.put("/payments/1", json={"status": "paid"}, headers=_auth(user.id)).status_code == 403


# ── System admin retains full access ─────────────────────────────────────────

def test_list_payments_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    org = _make_org(db)
    _make_payment(db, org.id)

    resp = client.get("/payments/", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_payment_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    org = _make_org(db)

    resp = client.post(
        "/payments/",
        json={"organization_id": org.id, "amount": 75.0, "currency": "ILS", "status": "pending"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["organization_id"] == org.id
    assert float(data["amount"]) == 75.0
    assert data["status"] == "pending"


def test_get_payment_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    org = _make_org(db)
    payment = _make_payment(db, org.id)

    resp = client.get(f"/payments/{payment.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["id"] == payment.id


def test_update_payment_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    org = _make_org(db)
    payment = _make_payment(db, org.id)

    resp = client.put(
        f"/payments/{payment.id}",
        json={"status": "paid"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


def test_get_nonexistent_payment_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    assert client.get("/payments/99999", headers=_auth(admin.id)).status_code == 404


def test_update_nonexistent_payment_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    assert client.put("/payments/99999", json={"status": "paid"}, headers=_auth(admin.id)).status_code == 404
