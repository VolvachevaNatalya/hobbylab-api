"""
Authorization regression tests for class mutation endpoints.

POST / PUT / DELETE /classes/ require the caller to be an org owner/admin
or system admin. GET endpoints remain public.

Flutter calls these endpoints only from org management screens gated by
_isAdminOrOwner, so owners and admins will continue to work as before.
"""
import pytest

from app.core.security import create_access_token
from app.models.category import Category
from app.models.classes import Class
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Test Org"):
    o = Organization(name=name, status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_category(db):
    c = Category(name="Cat")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_class(db, org_id, cat_id):
    c = Class(organization_id=org_id, category_id=cat_id, name="Test Class")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_membership(db, org_id, user_id, role):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


# ── POST /classes/ ─────────────────────────────────────────────────────────────

def test_create_class_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    resp = client.post("/classes/", json={"organization_id": org.id, "category_id": cat.id, "name": "X"})
    assert resp.status_code == 401


def test_create_class_unrelated_user(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    stranger = _make_user(db, "stranger@test.com")
    resp = client.post(
        "/classes/",
        json={"organization_id": org.id, "category_id": cat.id, "name": "X"},
        headers=_auth(stranger.id),
    )
    assert resp.status_code == 403


def test_create_class_read_only_member_blocked(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    resp = client.post(
        "/classes/",
        json={"organization_id": org.id, "category_id": cat.id, "name": "X"},
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_create_class_org_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.post(
        "/classes/",
        json={"organization_id": org.id, "category_id": cat.id, "name": "New Class"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Class"


def test_create_class_org_owner_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    resp = client.post(
        "/classes/",
        json={"organization_id": org.id, "category_id": cat.id, "name": "New Class"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200


def test_create_class_system_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.post(
        "/classes/",
        json={"organization_id": org.id, "category_id": cat.id, "name": "SysClass"},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 200


# ── PUT /classes/{id} ─────────────────────────────────────────────────────────

def test_update_class_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    assert client.put(f"/classes/{cls.id}", json={"name": "Y"}).status_code == 401


def test_update_class_read_only_member_blocked(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    assert client.put(f"/classes/{cls.id}", json={"name": "Y"}, headers=_auth(member.id)).status_code == 403


def test_update_class_org_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.put(f"/classes/{cls.id}", json={"name": "Updated"}, headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


def test_update_class_org_owner_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    resp = client.put(f"/classes/{cls.id}", json={"name": "Updated"}, headers=_auth(owner.id))
    assert resp.status_code == 200


def test_update_class_cross_org_blocked(client, db):
    """A user who is owner of org_a must not update a class belonging to org_b."""
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    cat = _make_category(db)
    cls_b = _make_class(db, org_b.id, cat.id)
    owner_a = _make_user(db, "ownera@test.com")
    _make_membership(db, org_a.id, owner_a.id, role="owner")
    assert client.put(f"/classes/{cls_b.id}", json={"name": "Y"}, headers=_auth(owner_a.id)).status_code == 403


def test_update_class_system_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.put(f"/classes/{cls.id}", json={"name": "SysUpdated"}, headers=_auth(sysadmin.id))
    assert resp.status_code == 200


# ── DELETE /classes/{id} ──────────────────────────────────────────────────────

def test_delete_class_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    assert client.delete(f"/classes/{cls.id}").status_code == 401


def test_delete_class_read_only_member_blocked(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    assert client.delete(f"/classes/{cls.id}", headers=_auth(member.id)).status_code == 403


def test_delete_class_org_owner_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    assert client.delete(f"/classes/{cls.id}", headers=_auth(owner.id)).status_code == 200


def test_delete_class_cross_org_blocked(client, db):
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    cat = _make_category(db)
    cls_b = _make_class(db, org_b.id, cat.id)
    owner_a = _make_user(db, "ownera@test.com")
    _make_membership(db, org_a.id, owner_a.id, role="owner")
    assert client.delete(f"/classes/{cls_b.id}", headers=_auth(owner_a.id)).status_code == 403


def test_delete_class_system_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    assert client.delete(f"/classes/{cls.id}", headers=_auth(sysadmin.id)).status_code == 200


# ── GET endpoints remain public ───────────────────────────────────────────────

def test_get_classes_is_public(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    _make_class(db, org.id, cat.id)
    assert client.get("/classes/").status_code == 200


def test_get_class_by_id_is_public(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    assert client.get(f"/classes/{cls.id}").status_code == 200
