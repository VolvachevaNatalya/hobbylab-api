"""
Authorization regression tests for group mutation endpoints.

POST / PUT / DELETE /groups/ require org owner/admin or system admin.
The owning organization is resolved via group→class→organization (never from payload).
GET endpoints remain public.
"""
from app.core.security import create_access_token
from app.models.category import Category
from app.models.classes import Class
from app.models.group import Group
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


def _make_class(db, org_id):
    cat = Category(name="Cat")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    c = Class(organization_id=org_id, category_id=cat.id, name="Test Class")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_group(db, class_id, name="Test Group"):
    g = Group(class_id=class_id, name=name)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def _make_membership(db, org_id, user_id, role):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


# ── POST /groups/ ─────────────────────────────────────────────────────────────

def test_create_group_unauthenticated(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    assert client.post("/groups/", json={"class_id": cls.id, "name": "G"}).status_code == 401


def test_create_group_read_only_member_blocked(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    assert client.post(
        "/groups/", json={"class_id": cls.id, "name": "G"}, headers=_auth(member.id)
    ).status_code == 403


def test_create_group_org_admin_allowed(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.post("/groups/", json={"class_id": cls.id, "name": "G"}, headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["name"] == "G"


def test_create_group_org_owner_allowed(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    assert client.post("/groups/", json={"class_id": cls.id, "name": "G"}, headers=_auth(owner.id)).status_code == 200


def test_create_group_system_admin_allowed(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    assert client.post("/groups/", json={"class_id": cls.id, "name": "G"}, headers=_auth(sysadmin.id)).status_code == 200


# ── PUT /groups/{id} ──────────────────────────────────────────────────────────

def test_update_group_unauthenticated(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    assert client.put(f"/groups/{grp.id}", json={"name": "Y"}).status_code == 401


def test_update_group_read_only_member_blocked(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    assert client.put(f"/groups/{grp.id}", json={"name": "Y"}, headers=_auth(member.id)).status_code == 403


def test_update_group_org_admin_allowed(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.put(f"/groups/{grp.id}", json={"name": "Updated"}, headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


def test_update_group_cross_org_blocked(client, db):
    """Owner of org_a must not update a group belonging to org_b."""
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    cls_b = _make_class(db, org_b.id)
    grp_b = _make_group(db, cls_b.id)
    owner_a = _make_user(db, "ownera@test.com")
    _make_membership(db, org_a.id, owner_a.id, role="owner")
    assert client.put(f"/groups/{grp_b.id}", json={"name": "Y"}, headers=_auth(owner_a.id)).status_code == 403


def test_update_group_system_admin_allowed(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.put(f"/groups/{grp.id}", json={"name": "SysUpdated"}, headers=_auth(sysadmin.id))
    assert resp.status_code == 200


# ── DELETE /groups/{id} ───────────────────────────────────────────────────────

def test_delete_group_unauthenticated(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    assert client.delete(f"/groups/{grp.id}").status_code == 401


def test_delete_group_read_only_member_blocked(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    assert client.delete(f"/groups/{grp.id}", headers=_auth(member.id)).status_code == 403


def test_delete_group_org_owner_allowed(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    assert client.delete(f"/groups/{grp.id}", headers=_auth(owner.id)).status_code == 200


def test_delete_group_cross_org_blocked(client, db):
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    cls_b = _make_class(db, org_b.id)
    grp_b = _make_group(db, cls_b.id)
    owner_a = _make_user(db, "ownera@test.com")
    _make_membership(db, org_a.id, owner_a.id, role="owner")
    assert client.delete(f"/groups/{grp_b.id}", headers=_auth(owner_a.id)).status_code == 403


def test_delete_group_system_admin_allowed(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    assert client.delete(f"/groups/{grp.id}", headers=_auth(sysadmin.id)).status_code == 200


# ── GET endpoints remain public ───────────────────────────────────────────────

def test_get_groups_is_public(client, db):
    assert client.get("/groups/").status_code == 200


def test_get_groups_by_class_is_public(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    assert client.get(f"/groups/class/{cls.id}").status_code == 200
