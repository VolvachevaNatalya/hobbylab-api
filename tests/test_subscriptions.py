"""
Authorization regression tests for /subscriptions/ endpoints.

GET /subscriptions/organization/{id}  — system admin or any org member.
POST / PUT / DELETE                   — system admin only.
Flutter makes no calls to these endpoints.
"""
from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.subscription import Subscription
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


def _make_membership(db, org_id, user_id, role="member"):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def _make_subscription(db, org_id, plan_type="basic"):
    s = Subscription(organization_id=org_id, plan_type=plan_type, status="active")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── GET: unauthenticated → 401 ───────────────────────────────────────────────

def test_get_subscription_unauthenticated(client, db):
    org = _make_org(db)
    assert client.get(f"/subscriptions/organization/{org.id}").status_code == 401


# ── GET: unrelated user (no membership) → 403 ────────────────────────────────

def test_get_subscription_unrelated_user(client, db):
    org = _make_org(db)
    stranger = _make_user(db, "stranger@test.com")
    assert client.get(
        f"/subscriptions/organization/{org.id}", headers=_auth(stranger.id)
    ).status_code == 403


# ── GET: any org member (role=member) → 200 ──────────────────────────────────

def test_get_subscription_org_member_sees_own_org(client, db):
    org = _make_org(db)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    _make_subscription(db, org.id)

    resp = client.get(f"/subscriptions/organization/{org.id}", headers=_auth(member.id))
    assert resp.status_code == 200
    assert resp.json()["plan_type"] == "basic"


def test_get_subscription_org_member_cannot_see_other_org(client, db):
    org_a = _make_org(db)
    org_b = _make_org(db)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org_a.id, member.id, role="member")

    assert client.get(
        f"/subscriptions/organization/{org_b.id}", headers=_auth(member.id)
    ).status_code == 403


def test_get_subscription_returns_none_when_no_subscription(client, db):
    org = _make_org(db)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.get(f"/subscriptions/organization/{org.id}", headers=_auth(member.id))
    assert resp.status_code == 200
    assert resp.json() == {"subscription": None}


# ── GET: org admin → 200 ─────────────────────────────────────────────────────

def test_get_subscription_org_admin(client, db):
    org = _make_org(db)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    _make_subscription(db, org.id, plan_type="pro")

    resp = client.get(f"/subscriptions/organization/{org.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["plan_type"] == "pro"


# ── GET: system admin → 200 (any org) ────────────────────────────────────────

def test_get_subscription_system_admin(client, db):
    org = _make_org(db)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    _make_subscription(db, org.id, plan_type="enterprise")

    resp = client.get(f"/subscriptions/organization/{org.id}", headers=_auth(sysadmin.id))
    assert resp.status_code == 200
    assert resp.json()["plan_type"] == "enterprise"


# ── POST: unauthenticated → 401, non-admin → 403 ─────────────────────────────

def test_create_subscription_unauthenticated(client, db):
    org = _make_org(db)
    resp = client.post("/subscriptions/", json={"organization_id": org.id, "plan_type": "basic"})
    assert resp.status_code == 401


def test_create_subscription_non_admin(client, db):
    org = _make_org(db)
    user = _make_user(db, "user@test.com")
    _make_membership(db, org.id, user.id, role="owner")
    resp = client.post(
        "/subscriptions/",
        json={"organization_id": org.id, "plan_type": "basic"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 403


def test_create_subscription_system_admin(client, db):
    org = _make_org(db)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.post(
        "/subscriptions/",
        json={"organization_id": org.id, "plan_type": "pro", "status": "active"},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["plan_type"] == "pro"


# ── PUT: unauthenticated → 401, non-admin → 403 ──────────────────────────────

def test_update_subscription_unauthenticated(client, db):
    org = _make_org(db)
    sub = _make_subscription(db, org.id)
    assert client.put(f"/subscriptions/{sub.id}", json={"status": "cancelled"}).status_code == 401


def test_update_subscription_non_admin(client, db):
    org = _make_org(db)
    sub = _make_subscription(db, org.id)
    user = _make_user(db, "user@test.com")
    _make_membership(db, org.id, user.id, role="owner")
    resp = client.put(
        f"/subscriptions/{sub.id}",
        json={"status": "cancelled"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 403


def test_update_subscription_system_admin(client, db):
    org = _make_org(db)
    sub = _make_subscription(db, org.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)

    resp = client.put(
        f"/subscriptions/{sub.id}",
        json={"status": "cancelled"},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


# ── DELETE: unauthenticated → 401, non-admin → 403 ───────────────────────────

def test_delete_subscription_unauthenticated(client, db):
    org = _make_org(db)
    sub = _make_subscription(db, org.id)
    assert client.delete(f"/subscriptions/{sub.id}").status_code == 401


def test_delete_subscription_non_admin(client, db):
    org = _make_org(db)
    sub = _make_subscription(db, org.id)
    user = _make_user(db, "user@test.com")
    _make_membership(db, org.id, user.id, role="owner")
    assert client.delete(f"/subscriptions/{sub.id}", headers=_auth(user.id)).status_code == 403


def test_delete_subscription_system_admin(client, db):
    org = _make_org(db)
    sub = _make_subscription(db, org.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)

    resp = client.delete(f"/subscriptions/{sub.id}", headers=_auth(sysadmin.id))
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}


# ── 404 on missing resources ──────────────────────────────────────────────────

def test_update_nonexistent_subscription(client, db):
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    assert client.put(
        "/subscriptions/99999", json={"status": "cancelled"}, headers=_auth(sysadmin.id)
    ).status_code == 404


def test_delete_nonexistent_subscription(client, db):
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    assert client.delete("/subscriptions/99999", headers=_auth(sysadmin.id)).status_code == 404
